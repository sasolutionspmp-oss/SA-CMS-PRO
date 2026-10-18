"""Pure, disabled-by-default FLD02 admission guards; never contacts a runtime.

An operator receipt is an input pin, not proof of a native runtime. The driver
must independently verify its actual runtime, database, version and isolation.
Unknown/attempted journals are retained and never authorize a retry or cleanup.
"""
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile
import uuid

PREFIX = "cipher.fld02.native.concurrent."
MAX_JSON = 1024 * 1024
MAX_FILES = 4096
MAX_SOURCE = 16 * 1024 * 1024
MAX_TOTAL = 128 * 1024 * 1024
DRIVERS = ("native_driver.py", "native_worker.py", "inventory.py", "lease.py")
SCENARIOS = {"stage_race", "apply_race", "change_before_apply", "binding_race", "duty_race"}


def now():
    return dt.datetime.now(dt.timezone.utc)


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _keys(value, required, optional=()):
    _require(isinstance(value, dict) and set(required) <= set(value) <= set(required) | set(optional),
             "Unexpected or missing fields")


def _text(value):
    return isinstance(value, str) and 0 < len(value) <= 512 and not any(ord(c) < 32 for c in value)


def _hex(value):
    return isinstance(value, str) and re.fullmatch(r"[a-f0-9]{64}", value) is not None


def _uuid(value):
    try:
        return isinstance(value, str) and str(uuid.UUID(value)) == value and uuid.UUID(value).version == 4
    except (ValueError, TypeError, AttributeError):
        return False


def _time(value):
    _require(isinstance(value, str), "Timestamp must be aware ISO text")
    result = dt.datetime.fromisoformat(value)
    _require(result.tzinfo is not None and result.utcoffset() is not None, "Naive timestamp")
    return result


def _path(value):
    _require(_text(str(value)) and os.path.isabs(value) and os.path.normpath(value) == str(value),
             "Path must be absolute and normalized")
    path = Path(value)
    for part in [*reversed(path.parents), path]:
        _require(not stat.S_ISLNK(os.lstat(part).st_mode), "Symlink path denied")
    return path


def _private_parent(path):
    parent = _path(str(Path(path).parent))
    info = parent.stat()
    _require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.geteuid()
             and stat.S_IMODE(info.st_mode) == 0o700, "Parent must be owned mode 0700")
    return parent


def _read(path, limit, private=False):
    path = _path(path)
    if private:
        _private_parent(path)
    info = path.lstat()
    _require(stat.S_ISREG(info.st_mode), "Regular file required")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        opened = os.fstat(fd)
        _require((info.st_dev, info.st_ino) == (opened.st_dev, opened.st_ino), "File changed during open")
        _require(stat.S_ISREG(opened.st_mode) and opened.st_size <= limit, "File exceeds bound")
        if private:
            _require(opened.st_uid == os.geteuid() and stat.S_IMODE(opened.st_mode) == 0o600
                     and opened.st_nlink == 1, "Private file must be owned, unlinked mode 0600")
        with os.fdopen(fd, "rb", closefd=False) as handle:
            content = handle.read(limit + 1)
        after = os.fstat(fd)
        _require(len(content) <= limit and (opened.st_size, opened.st_mtime_ns, opened.st_ctime_ns)
                 == (after.st_size, after.st_mtime_ns, after.st_ctime_ns), "File changed or exceeds bound")
        return content
    finally:
        os.close(fd)


def sha_json(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def _unique(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result, "Duplicate JSON field")
        result[key] = value
    return result


def private_json(path):
    try:
        value = json.loads(_read(path, MAX_JSON, private=True).decode("utf-8"),
                           object_pairs_hook=_unique,
                           parse_constant=lambda value: _require(False, "Nonfinite JSON"))
    except RecursionError as exc:
        raise ValueError("Excessively nested JSON") from exc
    _require(isinstance(value, dict), "JSON object required")
    return value


def atomic_json(path, value):
    """Durable private replacement; does not provide a journal start reservation."""
    path = Path(path)
    parent = _private_parent(path)
    if path.exists() or path.is_symlink():
        _read(str(path), MAX_JSON, private=True)
    data = (json.dumps(value, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=False, allow_nan=False) + "\n").encode()
    _require(len(data) <= MAX_JSON, "JSON exceeds bound")
    fd, temporary = tempfile.mkstemp(prefix=".private-json-", dir=parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            os.fchmod(handle.fileno(), 0o600)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _sources(manifest, lease):
    _keys(manifest, ("schema", "app_root", "driver_files", "runtime_files", "files"))
    _require(manifest["schema"] == PREFIX + "sources.v1", "Wrong manifest schema")
    app = _path(manifest["app_root"])
    _require(app.is_dir(), "Application root must be a directory")
    drivers, runtime, entries = manifest["driver_files"], manifest["runtime_files"], manifest["files"]
    expected_drivers = {str(Path(__file__).parent / name) for name in DRIVERS}
    _require(isinstance(drivers, list) and len(drivers) == 4 and set(drivers) == expected_drivers,
             "Exact driver source pins required")
    _require(isinstance(runtime, list) and 0 < len(runtime) <= MAX_FILES
             and all(_text(p) for p in runtime) and len(set(runtime)) == len(runtime), "Runtime source pins required")
    _require(isinstance(entries, list) and 0 < len(entries) <= MAX_FILES, "Manifest exceeds file bound")
    driver_root = Path(__file__).parent
    for directory in [driver_root, driver_root / "__pycache__"]:
        if directory.exists() or directory.is_symlink():
            _path(str(directory))
            with os.scandir(directory) as children:
                for index, child in enumerate(children):
                    _require(index < MAX_FILES, "Driver directory bound exceeded")
                    if child.name.endswith(".pyc"):
                        _require(not child.is_symlink() and child.is_file(follow_symlinks=False)
                                 and child.path in runtime, "Existing driver bytecode needs explicit runtime pin")
    actual, pending, directories = set(), [app], 0
    while pending:
        directory = pending.pop()
        directories += 1
        _require(directories <= MAX_FILES, "Application directory bound exceeded")
        with os.scandir(directory) as children:
            for child in children:
                if child.name == ".git":
                    continue
                _require(not child.is_symlink(), "Source symlink denied")
                if child.is_dir(follow_symlinks=False):
                    pending.append(Path(child.path))
                else:
                    _require(child.is_file(follow_symlinks=False), "Regular application source required")
                    actual.add(child.path)
                    _require(len(actual) <= MAX_FILES, "Application file bound exceeded")
    expected, seen, total = actual | set(drivers) | set(runtime), set(), 0
    for entry in entries:
        _keys(entry, ("path", "sha256"))
        path = entry["path"]
        _require(_text(path) and path not in seen and _hex(entry["sha256"]), "Invalid or duplicate source pin")
        seen.add(path)
        content = _read(path, min(MAX_SOURCE, lease["max_file_bytes"]))
        total += len(content)
        _require(total <= MAX_TOTAL and hashlib.sha256(content).hexdigest() == entry["sha256"], "Source hash mismatch/bound")
    _require(seen == expected, "Manifest must cover full application and selected sources exactly")


def _request(request, lease):
    _keys(request, ("schema", "scenario", "operation_uuid", "body_sha256", "body", "change"))
    scenario, body, scope = request["scenario"], request["body"], lease["scope"]
    _require(request["schema"] == PREFIX + "request.v1" and scenario in SCENARIOS, "Unknown request scenario/schema")
    _require(_uuid(request["operation_uuid"]) and sha_json(request) == lease["request_sha256"], "Request/operation pin mismatch")
    fields = ("company", "project", "operation_id", "envelope") if scenario == "stage_race" else (
        "company", "project", "operation_id", "capture_id", "expected_version")
    _keys(body, fields)
    _require(sha_json(body) == request["body_sha256"] and body["operation_id"] == request["operation_uuid"]
             and body["company"] == scope["company"] and body["project"] == scope["project"], "Body/scope pin mismatch")
    if scenario == "stage_race":
        envelope = body["envelope"]
        _keys(envelope, ("schema", "device_id", "capture_id", "company", "project", "actor_person", "actor_user", "captured_at", "command"))
        _require(envelope["schema"] == "cipher.field.offline.v1" and _uuid(envelope["device_id"])
                 and _uuid(envelope["capture_id"]) and envelope["capture_id"] != body["operation_id"]
                 and envelope["company"] == scope["company"] and envelope["project"] == scope["project"]
                 and isinstance(envelope["command"], dict), "Stage envelope scope/identifiers invalid")
        _time(envelope["captured_at"])
    else:
        _require(body["capture_id"] == request["operation_uuid"] and _hex(body["expected_version"]), "Apply capture UUID/version required")
    _keys(scope, ("company", "project", "users"), ("extra_person",))
    _require(_text(scope["company"]) and _text(scope["project"]), "Company/Project required")
    users = scope["users"]
    _require(isinstance(users, list) and len(users) == 2, "Exactly two explicit profiles required")
    for index, user in enumerate(users):
        _keys(user, ("user", "profile", "person"))
        _require(user["profile"] == ("A", "B")[index] and _text(user["person"])
                 and _text(user["user"]) and (user["user"].endswith("@synthetic.example") or
                     (index == 1 and scenario not in {"stage_race", "apply_race"} and user["user"] == "Administrator")),
                 "Explicit synthetic profile/Person required")
    _require(users[0]["user"] != users[1]["user"], "Profiles must be distinct users")
    if scenario == "stage_race":
        _require(envelope["actor_person"] == users[0]["person"]
                 and envelope["actor_user"] in {u["user"] for u in users}, "Envelope actor outside explicit scope")
    if scenario in {"stage_race", "apply_race"}:
        _require(users[0]["person"] == users[1]["person"] and request["change"] is None, "Race aliases must share Person; no change")
    else:
        change = request["change"]
        _keys(change, ("doctype", "name", "expected_native_digest", "updates"))
        _require(change["doctype"] in {"Cipher Identity Binding", "Cipher Project Duty"}
                 and _text(change["name"]) and _hex(change["expected_native_digest"]), "Explicit change target/digest required")
        updates = change["updates"]
        _require(isinstance(updates, dict) and len(updates) == 1, "Exactly one explicit change required")
        if "extra_person" in scope:
            _require(_text(scope["extra_person"]), "Explicit extra Person required")
        _require((set(updates) == {"active"} and type(updates["active"]) is int and updates["active"] == 0)
                 or (set(updates) == {"person"} and _text(scope.get("extra_person"))
                     and updates["person"] == scope["extra_person"]), "Only disable/explicit extra Person permitted")
        _require(scenario != "binding_race" or change["doctype"] == "Cipher Identity Binding", "Binding race target mismatch")
        _require(scenario != "duty_race" or change["doctype"] == "Cipher Project Duty", "Duty race target mismatch")


def admit(lease_path, request_path, *, execute=False):
    _require(execute is True, "Execution is disabled by default")
    started = now()
    lease, request = private_json(lease_path), private_json(request_path)
    _keys(lease, ("schema", "enabled", "authority", "issued_at", "expires_at", "max_duration_seconds",
        "runtime_id", "build_sha256", "epoch", "source_manifest_sha256", "runtime_receipt_path", "epoch_path",
        "source_manifest_path", "scope", "request_sha256", "site", "sites_path", "python_executable",
        "database_name", "artifact_dir", "statement_timeout_seconds", "lock_wait_timeout_seconds",
        "max_inventory_rows", "max_file_bytes", "run_id"), ("status",))
    _require(lease["schema"] == PREFIX + "lease.v1" and lease["enabled"] is True
             and lease["authority"] == "local_root", "Explicit enabled local-root lease required")
    issued, expires = _time(lease["issued_at"]), _time(lease["expires_at"])
    _require(issued <= started < expires <= min(started, issued) + dt.timedelta(hours=1), "Lease is stale/future/unbounded")
    for field, upper in [("max_duration_seconds", 120), ("statement_timeout_seconds", 30),
                         ("lock_wait_timeout_seconds", 30), ("max_inventory_rows", 2000), ("max_file_bytes", MAX_SOURCE)]:
        _require(type(lease[field]) is int and 1 <= lease[field] <= upper, "Invalid finite bound: " + field)
    for field in ("runtime_id", "epoch", "site", "database_name"):
        _require(_text(lease[field]), "Missing runtime identity: " + field)
    for field in ("build_sha256", "source_manifest_sha256", "request_sha256"):
        _require(_hex(lease[field]), "Invalid SHA256: " + field)
    _require(isinstance(lease["run_id"], str) and re.fullmatch(r"[a-zA-Z0-9_-]{8,80}", lease["run_id"]), "Explicit safe stable run_id required")
    _private_parent(lease_path)
    for field in ("sites_path", "python_executable", "artifact_dir"):
        _require(_text(lease[field]) and os.path.isabs(lease[field])
                 and os.path.normpath(lease[field]) == lease[field], "Absolute runtime path required")
    _private_parent(str(Path(lease["artifact_dir"]) / ".output-guard"))
    _require(stat.S_ISREG(_path(lease["python_executable"]).stat().st_mode), "Physical regular interpreter required")
    paths = [str(_path(p)) for p in [lease_path, request_path, lease["runtime_receipt_path"],
                                    lease["epoch_path"], lease["source_manifest_path"]]]
    _require(len(set(paths)) == len(paths), "Separate control files required")
    receipt, epoch, manifest = [private_json(p) for p in paths[2:]]
    _keys(receipt, ("schema", "authority", "runtime_id", "build_sha256", "epoch", "source_manifest_sha256"))
    _keys(epoch, ("schema", "runtime_id", "epoch"))
    _require(receipt["schema"] == PREFIX + "runtime.v1" and receipt["authority"] == "local_root"
             and epoch["schema"] == PREFIX + "epoch.v1", "Explicit runtime/epoch receipt required")
    _require(all(receipt[k] == lease[k] for k in ("runtime_id", "build_sha256", "epoch", "source_manifest_sha256"))
             and all(epoch[k] == lease[k] for k in ("runtime_id", "epoch")), "Runtime/build/epoch mismatch")
    _require(sha_json(manifest) == lease["source_manifest_sha256"], "Manifest digest mismatch")
    _request(request, lease)
    _sources(manifest, lease)
    deadline = min(expires, started + dt.timedelta(seconds=lease["max_duration_seconds"]))
    _require(now() < deadline, "Admission deadline elapsed")
    return {"lease": lease, "request": request, "lease_path": paths[0], "request_path": paths[1],
            "admitted_at": started.isoformat(), "deadline": deadline.isoformat(),
            "pins": [sha_json(v) for v in (lease, request, receipt, epoch, manifest)]}


def recheck(admission):
    _keys(admission, ("lease", "request", "lease_path", "request_path", "admitted_at", "deadline", "pins"))
    lease, start, deadline = admission["lease"], _time(admission["admitted_at"]), _time(admission["deadline"])
    _require(isinstance(admission["pins"], list) and len(admission["pins"]) == 5
             and all(_hex(p) for p in admission["pins"]), "Invalid admission pins")
    _require([sha_json(lease), sha_json(admission["request"])] == admission["pins"][:2], "Admission metadata changed")
    _require(_time(lease["issued_at"]) <= start < _time(lease["expires_at"])
             and deadline == min(_time(lease["expires_at"]), start + dt.timedelta(seconds=lease["max_duration_seconds"]))
             and start <= now() < deadline,
             "Original admission deadline elapsed")
    fresh = admit(admission["lease_path"], admission["request_path"], execute=True)
    _require(fresh["pins"] == admission["pins"] and now() < _time(admission["deadline"]), "Admission files changed/deadline elapsed")
    fresh.update(admitted_at=admission["admitted_at"], deadline=admission["deadline"])
    return fresh


def can_start(journal):
    """A pure predicate only; callers must reserve a journal exclusively first."""
    return (isinstance(journal, dict) and set(journal) == {"schema", "state", "attempts", "outcome", "operation_uuid"}
            and journal.get("schema") == PREFIX + "journal.v1"
            and journal.get("state") == "ready" and type(journal.get("attempts")) is int
            and journal["attempts"] == 0 and journal.get("outcome") == "not_started"
            and _uuid(journal.get("operation_uuid")))

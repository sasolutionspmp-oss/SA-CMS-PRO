"""Prepared native worker; all runtime imports occur after fresh lease admission."""
import hashlib
import importlib.util
import inspect
import os
from pathlib import Path
import stat
import sys
import time

from lease import atomic_json, private_json, recheck
import inventory


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _identity(admission):
    lease, request = admission["lease"], admission["request"]
    return {"run_id": lease["run_id"], "epoch": lease["epoch"], "operation_uuid": request["operation_uuid"],
            "body_sha256": request["body_sha256"], "runtime_id": lease["runtime_id"]}


def _connection(frappe, admission, expected=None):
    recheck(admission)
    row = frappe.db.sql("SELECT VERSION() AS version, CONNECTION_ID() AS connection_id, DATABASE() AS database_name, @@session.tx_isolation AS isolation, @@session.max_statement_time AS statement_timeout, @@session.innodb_lock_wait_timeout AS lock_timeout", as_dict=True)[0]
    result = inventory.json_safe(dict(row))
    result.update(site=frappe.local.site, frappe_version=frappe.__version__)
    lease = admission["lease"]
    _require(result["site"] == lease["site"] and result["database_name"] == lease["database_name"], "actual native site/database differs")
    _require("MariaDB" in result["version"] and result["frappe_version"] == "16.52.0", "actual Frappe 16.52.0 / MariaDB required")
    _require(str(result["isolation"]).upper().replace("_", "-") == "READ-COMMITTED", "genuinely fresh READ COMMITTED connection required")
    _require(type(result["connection_id"]) is int and result["connection_id"] > 0, "actual physical connection ID required")
    if expected is not None:
        _require(result["connection_id"] == expected["connection_id"], "physical connection changed; reconnect outcome unknown")
        _require(float(result["statement_timeout"]) == lease["statement_timeout_seconds"] and int(result["lock_timeout"]) == lease["lock_wait_timeout_seconds"], "owned child timeout changed")
    return result


def _pins(frappe, admission):
    manifest = private_json(admission["lease"]["source_manifest_path"])
    entries = {row["path"]: row["sha256"] for row in manifest["files"]}
    paths = {inspect.getsourcefile(type(frappe.local.db)), inspect.getsourcefile(frappe.local.db.set_execution_timeout),
             inspect.getsourcefile(type(frappe.local.db.before_commit)), inspect.getsourcefile(type(frappe.local.db).commit), frappe.__file__}
    paths.update(module.__file__ for name, module in list(sys.modules.items())
                 if name.startswith("cipher_aec") and getattr(module, "__file__", None))
    paths.update(module.__cached__ for name, module in list(sys.modules.items())
                 if (getattr(module, "__file__", None) in paths or name.startswith("cipher_aec")) and getattr(module, "__cached__", None) and Path(module.__cached__).exists())
    for filename in paths:
        path = str(Path(filename).absolute())
        _require(path in entries and not Path(path).is_symlink(), "loaded native source is outside root manifest")
        _require(hashlib.sha256(Path(path).read_bytes()).hexdigest() == entries[path], "loaded native source hash differs")
    recheck(admission)


def _open(admission):
    recheck(admission)
    _require("frappe" not in sys.modules and not any(name.startswith("cipher_aec") for name in sys.modules), "fresh process with no native imports required")
    _require(os.path.abspath(sys.executable) == admission["lease"]["python_executable"], "actual Python executable differs")
    manifest = private_json(admission["lease"]["source_manifest_path"])
    pinned = {row["path"]: row["sha256"] for row in manifest["files"]}
    for name in ("frappe", "cipher_aec"):
        spec = importlib.util.find_spec(name)
        paths = [spec.origin] + ([spec.cached] if spec.cached and Path(spec.cached).exists() else [])
        for origin in paths:
            _require(origin in pinned and hashlib.sha256(Path(origin).read_bytes()).hexdigest() == pinned[origin], "native import root/cache differs from root source manifest")
    import frappe
    _require(getattr(frappe.local, "db", None) is None and getattr(frappe.local, "site", None) is None, "caller Frappe local cannot be reused")
    frappe.init(site=admission["lease"]["site"], sites_path=admission["lease"]["sites_path"])
    frappe.connect(set_admin_as_user=False)
    _require(frappe.local.db._conn is None, "native connection was already physically opened")
    frappe.local.db.connect()
    first = _connection(frappe, admission)
    # These session limits apply only to this fresh child-owned physical connection.
    frappe.db.set_execution_timeout(admission["lease"]["statement_timeout_seconds"])
    frappe.db.sql("SET SESSION innodb_lock_wait_timeout = %s", (admission["lease"]["lock_wait_timeout_seconds"],))
    _connection(frappe, admission, first)
    from cipher_aec.governance.context import assert_synthetic_site
    assert_synthetic_site()
    _pins(frappe, admission)
    return frappe, first


def _wait(path, admission):
    while True:
        recheck(admission)
        if path.exists():
            return private_json(str(path))
        time.sleep(0.05)


def _scope(frappe, admission, role, *, both=False):
    from cipher_aec.governance.context import current_actor, require_project
    scope = admission["lease"]["scope"]
    rows = scope["users"] if both else [row for row in scope["users"] if row["profile"] == role]
    result = []
    for row in rows:
        actor = current_actor(row["user"])
        _require(actor.person_id == row["person"], "actual scoped actor Person differs")
        require_project(scope["company"], scope["project"], ability="field.read", actor=actor)
        require_project(scope["company"], scope["project"], ability="field.write", actor=actor)
        result.append({"user": actor.user, "person": actor.person_id})
    return result


def _preconditions(frappe, admission):
    from cipher_aec.api.contracts import digest
    from cipher_aec.field_offline import contracts, repository
    from cipher_aec.governance.context import current_actor, require_project
    request, scope = admission["request"], admission["lease"]["scope"]
    body, person = request["body"], scope["users"][0]["person"]
    capture_id = body.get("capture_id") or body["envelope"]["capture_id"]
    _require(repository.canonical_receipt(person, capture_id) is None, "original business UUID already has a receipt; no new attempt admitted")
    name = digest({"person": person, "capture_id": capture_id})
    capture = repository.raw("capture", name, optional=True)
    if request["scenario"] == "stage_race":
        contracts.envelope(body["envelope"])
        _require(body["operation_id"] != capture_id and capture is None, "stage race requires an unstaged capture and distinct original stage UUID")
        _require(not frappe.db.exists("Cipher Command Receipt", digest({"person": person, "operation_id": body["operation_id"]})), "stage UUID already used")
    else:
        _require(capture is not None and capture["status"] == "staged" and digest(capture) == body["expected_version"], "exact existing staged capture/version required")
    envelope = body.get("envelope") or capture["envelope"]
    declared = {row["user"]: row["person"] for row in scope["users"]}
    participants = capture["participant_people"] if capture else {envelope["actor_user"]: envelope["actor_person"]}
    if envelope["command"]["family"] == "daily":
        superintendent = envelope["command"]["definition"]["superintendent_user"]
        _require(superintendent in declared, "daily participant outside explicit root scope")
        participants = {**participants, superintendent: declared[superintendent]}
    for user, participant in participants.items():
        _require(declared.get(user) == participant and current_actor(user).person_id == participant, "staged participant outside exact declared identity closure")
        require_project(scope["company"], scope["project"], ability="field.read", actor=current_actor(user))
    change = request["change"]
    if change:
        doc = frappe.get_doc(change["doctype"], change["name"])
        _require(doc.active == 1 and inventory.native_digest(doc) == change["expected_native_digest"], "pristine existing active authority target required")


def _change(frappe, admission):
    from cipher_aec.governance.context import trusted_write
    scope, change = admission["lease"]["scope"], admission["request"]["change"]
    _require(next(row["user"] for row in scope["users"] if row["profile"] == "B") == "Administrator", "existing native authority change requires declared Administrator")
    frappe.set_user("Administrator")
    doc = frappe.get_doc(change["doctype"], change["name"], for_update=True)
    _require(inventory.native_digest(doc) == change["expected_native_digest"] and doc.active == 1, "exact existing active native change target differs")
    if doc.doctype == "Cipher Identity Binding":
        _require(doc.user in [row["user"] for row in scope["users"]] and doc.person in [row["person"] for row in scope["users"]], "binding target outside selected native users/People")
    else:
        _require((doc.company, doc.project, doc.scope_type) == (scope["company"], scope["project"], "Project") and doc.person in [row["person"] for row in scope["users"]], "duty target outside selected native scope")
    if "person" in change["updates"]:
        person = change["updates"]["person"]
        _require(person in {row["person"] for row in scope["users"]} | {scope.get("extra_person")} and person != doc.person, "existing declared distinct Person required")
        _require(frappe.db.exists("Cipher Person", person), "declared reassignment Person must already exist")
    with trusted_write():
        doc.update(change["updates"])
        doc.save(ignore_permissions=True)
    return {"doctype": doc.doctype, "name": doc.name, "native_digest": inventory.native_digest(doc), "native": inventory.json_safe(doc.as_dict())}


def run(admission, role, run_dir):
    """One explicit service call or one existing authority change; no retry/cleanup."""
    recheck(admission)
    _require(role in ("A", "B"), "only explicit A/B worker roles admitted")
    directory = Path(run_dir)
    _require(directory.parent == Path(admission["lease"]["artifact_dir"]) and directory.name == admission["lease"]["run_id"], "run directory differs from root lease")
    _require(not directory.is_symlink() and directory.stat().st_uid == os.geteuid() and stat.S_IMODE(directory.stat().st_mode) == 0o700, "private owned run directory required")
    identity = _identity(admission)
    outcome = {"schema": "cipher.fld02.native.concurrent.worker-result.v1", **identity, "role": role,
               "state": "not_started", "outcome": "not_started", "journal": [], "inventory_files": []}
    frappe, connection, commit_started, service_started = None, None, False, False

    def phase(name, **data):
        outcome["state"] = name
        outcome["journal"].append({"phase": name, "monotonic_ns": time.monotonic_ns(), **data})
        atomic_json(directory / ("journal-" + role + ".json"), outcome)

    def evidence(name):
        _connection(frappe, admission, connection)
        value = inventory.snapshot(frappe, admission, phase=name)
        saved = inventory.save(admission, directory / (name + "-" + role + ".json"), value)
        outcome["inventory_files"].append(saved)
        phase(name, inventory=saved)
        return value["complete"]

    try:
        phase("admitted")
        frappe, connection = _open(admission)
        outcome["connection"] = connection
        request = admission["request"]
        changing = role == "B" and request["change"] is not None
        user = next(row["user"] for row in admission["lease"]["scope"]["users"] if row["profile"] == role)
        frappe.set_user(user)
        if not changing:
            outcome["actors"] = _scope(frappe, admission, role, both=request["scenario"] in ("stage_race", "apply_race"))
        else:
            outcome["actors"] = _scope(frappe, admission, "A")
        phase("connected")
        atomic_json(directory / ("ready-" + role + ".json"), {"schema": "cipher.fld02.native.concurrent.ready.v1", **identity, "role": role, **connection})
        _require(evidence("before"), "incomplete native inventory before effects")
        _preconditions(frappe, admission)
        _pins(frappe, admission)
        _require(frappe.db.transaction_writes == 0, "preparation unexpectedly entered native write path")
        atomic_json(directory / ("prepared-" + role + ".json"), {"schema": "cipher.fld02.native.concurrent.prepared.v1", **identity, "role": role, "connection_id": connection["connection_id"]})
        other = _wait(directory / ("prepared-" + ("B" if role == "A" else "A") + ".json"), admission)
        _require(all(other.get(key) == identity[key] for key in identity), "peer prepared inventory metadata differs")
        go = _wait(directory / "go.json", admission)
        _require(go == {"schema": "cipher.fld02.native.concurrent.barrier.v1", **{key: identity[key] for key in ("run_id", "epoch", "operation_uuid", "body_sha256")}, "connections": go.get("connections")}, "barrier metadata differs")
        ids = go["connections"]
        _require(set(ids) == {"A", "B"} and ids[role] == connection["connection_id"] and all(type(value) is int and value > 0 for value in ids.values()) and ids["A"] != ids["B"], "barrier physical connections differ")
        phase("barrier_released")
        if request["scenario"] == "change_before_apply" and role == "A":
            marker = _wait(directory / "change_committed.json", admission)
            _require(all(marker.get(key) == identity[key] for key in ("run_id", "epoch", "operation_uuid", "body_sha256")) and marker.get("connection_id") == ids["B"] and marker.get("committed") is True, "native authority commit marker differs")
        _connection(frappe, admission, connection)
        _pins(frappe, admission)
        phase("service_started")
        service_started = True
        if changing:
            result = _change(frappe, admission)
        else:
            from cipher_aec.field_offline import service as offline
            from cipher_aec.api.errors import DomainError
            _pins(frappe, admission)
            result = (offline.stage_capture if request["scenario"] == "stage_race" else offline.apply_capture)(**request["body"])
        outcome["result"] = inventory.save(admission, directory / ("service-result-" + role + ".json"), {"complete": True, "value": inventory.json_safe(result)})
        _require(evidence("after-service-before-commit"), "incomplete native inventory after service; commit withheld")
        if not changing:
            canonical = inventory.canonical(frappe, admission, result)
            outcome["canonical_before_commit"] = inventory.save(admission, directory / ("canonical-before-commit-" + role + ".json"), canonical)
            _require(canonical["complete"], "canonical native receipt comparison failed")
        _connection(frappe, admission, connection)
        _pins(frappe, admission)
        recheck(admission)
        outcome["outcome"] = "unknown"
        phase("commit_started")
        commit_started = True
        frappe.db.commit()
        outcome["outcome"] = "commit_returned"
        phase("commit_returned")
        _connection(frappe, admission, connection)
        if changing and request["scenario"] == "change_before_apply":
            atomic_json(directory / "change_committed.json", {**identity, "connection_id": connection["connection_id"], "committed": True, "target_postdigest": result["native_digest"]})
        _require(evidence("after-commit-fresh-rc"), "incomplete inventory after commit")
        if not changing:
            canonical = inventory.canonical(frappe, admission, result)
            outcome["canonical_after_commit"] = inventory.save(admission, directory / ("canonical-after-commit-" + role + ".json"), canonical)
            _require(canonical["complete"], "canonical native readback incomplete")
        outcome["outcome"] = "committed"
        phase("complete")
    except Exception as error:
        outcome["error"] = {"type": type(error).__name__, "code": getattr(error, "code", None)}
        if commit_started:
            outcome["outcome"] = "unknown" if outcome["outcome"] != "commit_returned" else "committed_incomplete"
            phase("unknown" if outcome["outcome"] == "unknown" else "incomplete")
        elif frappe is not None and service_started:
            from cipher_aec.api.errors import DomainError
            if isinstance(error, DomainError):
                try:
                    _connection(frappe, admission, connection)
                    _require(evidence("after-domain-error-before-rollback"), "incomplete callbacks/inventory; explicit rollback withheld")
                    phase("rollback_started")
                    frappe.db.rollback()
                    outcome["outcome"] = "domain_error_rolled_back"
                    phase("rolled_back")
                    evidence("after-rollback-fresh-rc")
                except Exception as rollback_error:
                    outcome.update(outcome="unknown", rollback_error={"type": type(rollback_error).__name__})
                    phase("unknown")
            else:
                outcome["outcome"] = "unknown"
                phase("unknown")
        else:
            outcome["outcome"] = "incomplete"
            phase("incomplete")
    finally:
        # Disconnect is teardown only; it never establishes absence of effects.
        if frappe is not None:
            try:
                frappe.local.db.close()
            except Exception as error:
                outcome["disconnect_error"] = {"type": type(error).__name__}
        atomic_json(directory / ("result-" + role + ".json"), outcome)
    return outcome


def observe(admission, run_dir):
    """Separate fresh process, read original UUID/current rights, never replay writes."""
    recheck(admission)
    directory, identity = Path(run_dir), _identity(admission)
    root = Path(admission["lease"]["artifact_dir"]) / admission["lease"]["run_id"]
    _require(directory == root or directory.is_relative_to(root), "observer directory outside original root run")
    for path in (directory, *directory.parents):
        if path == root.parent:
            break
        _require(not path.is_symlink() and path.stat().st_uid == os.geteuid() and stat.S_IMODE(path.stat().st_mode) == 0o700, "private owned observer directory required")
    result = {"schema": "cipher.fld02.native.concurrent.observation.v1", **identity, "role": "OBSERVE", "state": "incomplete", "outcome": "read_only_incomplete"}
    frappe = None
    try:
        frappe, connection = _open(admission)
        result["connection"] = connection
        user = next(row["user"] for row in admission["lease"]["scope"]["users"] if row["profile"] == "A")
        frappe.set_user(user)
        _require(frappe.db.transaction_writes == 0, "observer must begin with no native writes")
        before_callbacks = inventory.callbacks(frappe)
        _require(before_callbacks["complete"], "incomplete initial observer callbacks")
        value = inventory.snapshot(frappe, admission, phase="fresh-observer")
        result["inventory"] = inventory.save(admission, directory / "fresh-observer.json", value)
        from cipher_aec.governance.commands import read_operation
        from cipher_aec.field_offline.service import inspect_capture
        body = admission["request"]["body"]
        capture_id = body.get("capture_id") or body["envelope"]["capture_id"]
        observed_values = {}
        for key, call in (("current_capture", lambda: inspect_capture(body["company"], body["project"], capture_id)),
                          ("original_operation", lambda: read_operation(body["company"], body["project"], admission["request"]["operation_uuid"]))):
            try:
                observed = inventory.json_safe(call())
                observed_values[key] = observed
                result[key] = {"available": True, "result": inventory.save(admission, directory / (key + "-observer.json"), {"complete": True, "value": observed})}
            except Exception as error:
                result[key] = {"available": False, "type": type(error).__name__, "code": getattr(error, "code", None)}
        _connection(frappe, admission, connection)
        _pins(frappe, admission)
        _require(frappe.db.transaction_writes == 0, "observer unexpectedly entered native write path")
        after_callbacks = inventory.callbacks(frappe)
        _require(before_callbacks == after_callbacks, "observer changed native transaction callback queues")
        result["callbacks_unchanged"] = True
        returned = observed_values.get("original_operation") if admission["request"]["scenario"] == "stage_race" else observed_values.get("current_capture")
        canonical = inventory.canonical(frappe, admission, returned)
        if admission["request"]["scenario"] != "stage_race" and "original_operation" in observed_values and canonical.get("canonical"):
            canonical["observer_original_operation_matches"] = {key: value for key, value in observed_values["original_operation"].items() if key != "operation"} == canonical["canonical"]["result"]
            canonical["complete"] = canonical["complete"] and canonical["observer_original_operation_matches"]
        result["canonical"] = inventory.save(admission, directory / "canonical-observer.json", canonical)
        _connection(frappe, admission, connection)
        _pins(frappe, admission)
        _require(frappe.db.transaction_writes == 0 and before_callbacks == inventory.callbacks(frappe), "final observer writes/callbacks changed")
        result.update(inventory_complete=value["complete"], canonical_complete=canonical["complete"],
                      rights_available=all(result[key]["available"] for key in ("current_capture", "original_operation")))
        result["state"] = "complete" if value["complete"] and canonical["complete"] else "incomplete"
        result["outcome"] = ("read_only_observed" if result["rights_available"] else "read_only_observed_rights_unavailable") if result["state"] == "complete" else "read_only_incomplete"
    except Exception as error:
        result["error"] = {"type": type(error).__name__, "code": getattr(error, "code", None)}
    finally:
        if frappe is not None:
            try:
                frappe.local.db.close()
            except Exception as error:
                result["disconnect_error"] = {"type": type(error).__name__}
        atomic_json(directory / "result-OBSERVE.json", result)
    return result

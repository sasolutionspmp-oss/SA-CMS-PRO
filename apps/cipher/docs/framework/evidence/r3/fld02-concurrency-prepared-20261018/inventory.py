"""Bounded private native evidence. Importing this module never opens Frappe."""
import base64
from collections import deque
from datetime import date, datetime, time
from decimal import Decimal
import functools
import hashlib
import inspect
import json
import marshal
import math
import os
from pathlib import Path
import stat

from lease import recheck, sha_json


def json_safe(value, depth=0):
    if depth > 20:
        raise ValueError("inventory value depth exceeded")
    if value is None or type(value) in (bool, int, str):
        if type(value) is str and len(value.encode()) > 16 * 1024 * 1024:
            raise ValueError("inventory string exceeded bound")
        return value
    if type(value) is float and math.isfinite(value):
        return value
    if isinstance(value, (datetime, date, time, Decimal)):
        return str(value)
    if type(value) is bytes:
        return {"bytes_base64": base64.b64encode(value).decode(), "sha256": hashlib.sha256(value).hexdigest()}
    if isinstance(value, dict) and len(value) <= 20000 and all(type(k) is str for k in value):
        return {k: json_safe(v, depth + 1) for k, v in value.items()}
    if isinstance(value, (tuple, list, deque)) and len(value) <= 20000:
        return [json_safe(v, depth + 1) for v in value]
    raise ValueError("unserializable native value: " + type(value).__name__)


def native_digest(document):
    return sha_json(json_safe(document.as_dict() if hasattr(document, "as_dict") else document))


def _callback(value, depth=0):
    if depth > 12:
        raise ValueError("callback depth exceeded")
    if isinstance(value, functools.partial):
        return {"partial": _callback(value.func, depth + 1), "args": _value(value.args, depth + 1),
                "keywords": _value(value.keywords, depth + 1)}
    function = value.__func__ if inspect.ismethod(value) else value
    if not inspect.isfunction(function):
        raise ValueError("unknown callback callable")
    closure = [_value(cell.cell_contents, depth + 1) for cell in function.__closure__ or ()]
    result = {"qualified_name": function.__module__ + "." + function.__qualname__,
              "code_sha256": hashlib.sha256(marshal.dumps(function.__code__)).hexdigest(),
              "defaults": _value(function.__defaults__, depth + 1),
              "kwdefaults": _value(function.__kwdefaults__, depth + 1), "closure": closure}
    if inspect.ismethod(value):
        result["bound_value"] = _value(value.__self__, depth + 1)
    result["value_sha256"] = sha_json(result)
    return result


def _value(value, depth=0):
    if depth > 12:
        raise ValueError("callback value depth exceeded")
    if inspect.isfunction(value) or inspect.ismethod(value) or isinstance(value, functools.partial):
        return _callback(value, depth + 1)
    if isinstance(value, (list, tuple, deque)):
        if len(value) > 2000:
            raise ValueError("callback collection exceeded bound")
        return [_value(item, depth + 1) for item in value]
    if isinstance(value, dict):
        return {key: _value(item, depth + 1) for key, item in value.items()} if len(value) <= 2000 else json_safe(object())
    if hasattr(value, "as_dict"):
        # User/session documents are never eligible callback evidence.
        if getattr(value, "doctype", None) in ("User", "Sessions", "OAuth Bearer Token"):
            raise ValueError("secret-bearing callback document")
        return {"document": json_safe(value.as_dict())}
    return json_safe(value, depth)


def callbacks(frappe):
    result = {"complete": True, "queues": {}}
    for name in ("before_commit", "after_commit", "before_rollback", "after_rollback"):
        try:
            queue = getattr(frappe.db, name)
            pending = getattr(queue, "_functions", None)
            if not isinstance(pending, (list, tuple, deque)) or len(pending) > 2000:
                raise ValueError("unsupported callback manager storage")
            entries = [_callback(callback) for callback in pending]
            result["queues"][name] = {"ordered": entries, "sha256": sha_json(entries)}
        except Exception as error:
            result["complete"] = False
            result["queues"][name] = {"incomplete": True, "reason": type(error).__name__}
    return result


def _file_bytes(frappe, document, maximum):
    if document.is_private != 1 or not str(document.file_url).startswith("/private/files/"):
        raise ValueError("inventory requires local private original File bytes")
    document.validate_file_path()
    document.validate_file_url()
    path = Path(document.get_full_path())
    root = Path(frappe.get_site_path("private", "files")).absolute()
    if not path.is_absolute():
        path = path.absolute()
    if not path.is_relative_to(root) or any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("File path is outside private bytes closure")
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_size > maximum:
        raise ValueError("regular bounded File bytes required")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > maximum or (before.st_dev, before.st_ino) != (info.st_dev, info.st_ino):
            raise ValueError("File byte inventory exceeded bound")
        content = stream.read(maximum + 1)
        after = os.fstat(stream.fileno())
        if len(content) != info.st_size or (info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns) != (after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            raise ValueError("File bytes changed during inventory")
    return {"byte_length": len(content), "sha256": hashlib.sha256(content).hexdigest(),
            "content_base64": base64.b64encode(content).decode()}


def snapshot(frappe, admission, request=None, *, phase):
    """Full selected native Documents, JSON facts, callbacks and original bytes."""
    recheck(admission)
    from cipher_aec.field import contracts as field_rules, repository as field_repo
    from cipher_aec.field_offline import repository as offline_repo
    from cipher_aec.document_control import contracts as control_rules
    scope = admission["lease"]["scope"]
    maximum = admission["lease"]["max_inventory_rows"]
    result = {"schema": "cipher.fld02.native.concurrent.inventory.v1", "phase": phase,
              "complete": True, "documents": {}, "facts": {}, "files": {}, "errors": []}
    total = 0

    def collect(doctype, filters):
        nonlocal total
        recheck(admission)
        rows = frappe.get_all(doctype, filters=filters, fields=["name"], order_by="name", limit_page_length=maximum + 1)
        total += len(rows)
        if total > maximum:
            raise ValueError("native inventory row closure exceeded root bound")
        docs = [frappe.get_doc(doctype, row.name) for row in rows]
        result["documents"][doctype] = [{"native": json_safe(doc.as_dict()), "native_digest": native_digest(doc)} for doc in docs]
        return docs

    try:
        scoped = {"company": scope["company"], "project": scope["project"]}
        for kind, doctype in field_rules.KINDS.items():
            docs = collect(doctype, scoped)
            result["facts"][doctype] = [field_repo.raw(kind, doc.name) for doc in docs]
        for kind, doctype in offline_repo.KINDS.items():
            docs = collect(doctype, scoped)
            result["facts"][doctype] = [offline_repo.raw(kind, doc.name) for doc in docs]
        for doctype in (*control_rules.KINDS.values(), "Cipher Command Receipt", "Cipher History Event", "Cipher Document", "Cipher Document Revision"):
            collect(doctype, scoped)
        collect("Project", {"name": scope["project"], "company": scope["company"]})
        collect("Task", {"project": scope["project"]})
        people = sorted({row["person"] for row in scope["users"]} | ({scope["extra_person"]} if "extra_person" in scope else set()))
        collect("Cipher Person", {"name": ["in", people]})
        collect("Cipher Identity Binding", {"user": ["in", [row["user"] for row in scope["users"]]]})
        collect("Cipher Project Duty", {**scoped, "scope_type": "Project", "person": ["in", people]})
        references = {}
        for row in result["documents"]["Cipher Document Revision"]:
            native = row["native"]
            references[native["storage_reference"]] = native
        files = {}
        for doctype, rows in list(result["documents"].items()):
            names = [row["native"]["name"] for row in rows]
            if names:
                found = frappe.get_all("File", filters={"attached_to_doctype": doctype, "attached_to_name": ["in", names]}, fields=["name"], order_by="name", limit_page_length=maximum + 1)
                if len(found) > maximum:
                    raise ValueError("native File closure exceeded bound")
                files.update({row.name: None for row in found})
        files.update({name: None for name in references})
        total += len(files)
        if total > maximum:
            raise ValueError("native inventory row closure exceeded root bound")
        byte_total = 0
        result["documents"]["File"] = []
        for name in sorted(files):
            recheck(admission)
            doc = frappe.get_doc("File", name)
            raw = _file_bytes(frappe, doc, admission["lease"]["max_file_bytes"])
            byte_total += raw["byte_length"]
            if byte_total > 64 * 1024 * 1024:
                raise ValueError("aggregate File byte inventory exceeded 64 MiB")
            if name in references:
                revision = references[name]
                if (doc.attached_to_doctype, doc.attached_to_name, raw["sha256"], raw["byte_length"]) != ("Cipher Document Revision", revision["name"], revision["sha256"], revision["byte_length"]):
                    raise ValueError("original source File bytes or native mapping differ")
            result["documents"]["File"].append({"native": json_safe(doc.as_dict()), "native_digest": native_digest(doc)})
            result["files"][name] = raw
    except Exception as error:
        result["complete"] = False
        result["errors"].append({"type": type(error).__name__, "reason": str(error)[:500]})
    result["callbacks"] = callbacks(frappe)
    result["complete"] = result["complete"] and result["callbacks"]["complete"]
    result["row_count"] = total
    recheck(admission)
    return json_safe(result)


def canonical(frappe, admission, returned=None):
    """Compare canonical bytes and immutable facts; retain historical header separately."""
    from cipher_aec.api.contracts import canonical_json, digest
    from cipher_aec.field import repository as field_repo
    from cipher_aec.field_offline import repository as offline_repo
    from cipher_aec.field_offline.spec import business_request
    request, scope = admission["request"], admission["lease"]["scope"]
    person = next(row["person"] for row in scope["users"] if row["profile"] == "A")
    body = request["body"]
    capture_id = body.get("capture_id") or body["envelope"]["capture_id"]
    capture = offline_repo.raw("capture", digest({"person": person, "capture_id": capture_id}), optional=True)
    envelope = body.get("envelope") or (capture or {}).get("envelope")
    native = offline_repo.canonical_receipt(person, capture_id)
    result = {"capture": capture, "canonical": native, "canonical_available": native is not None,
              "complete": True, "errors": []}
    if request["scenario"] == "stage_race":
        name = digest({"person": person, "operation_id": request["operation_uuid"]})
        stage = frappe.get_doc("Cipher Command Receipt", name) if frappe.db.exists("Cipher Command Receipt", name) else None
        stage_clean = json.loads(stage.result_json) if stage else None
        stage_hash = digest({"command": "offline.field.stage.v1", "company": scope["company"], "project": scope["project"], "payload": {"envelope": envelope}})
        checks = {"stage_receipt": stage is not None, "stage_capture": capture is not None and capture["envelope"] == envelope}
        if stage is not None:
            checks.update(stage_result_bytes=stage.result_json == canonical_json(stage_clean), stage_result_hash=stage.result_hash == digest(stage_clean),
                          stage_request_hash=stage.request_hash == stage_hash, stage_scope=(stage.command, stage.person, stage.operation_id, stage.company, stage.project, stage.scope_type, stage.state) == ("offline.field.stage.v1", person, request["operation_uuid"], scope["company"], scope["project"], "Project", "Succeeded"))
        if returned is not None:
            checks["returned_stage_result"] = {key: value for key, value in returned.items() if key != "operation"} == stage_clean
        result.update(stage_result=stage_clean, stage_checks=checks, complete=all(checks.values()))
        if native is not None:
            result.update(complete=False, errors=["unexpected business receipt during stage-only race"])
    if native is None:
        result["absence_does_not_prove_noncommit"] = True
        if request["scenario"] != "stage_race":
            result.update(complete=False, errors=["canonical original UUID unavailable"])
        return json_safe(result)
    clean = native["result"]
    if envelope is None:
        result.update(complete=False, errors=["original envelope unavailable for independent business request hash"])
        return json_safe(result)
    command, _, expected_hash = business_request(envelope)
    doc = frappe.get_doc("Cipher Command Receipt", digest({"person": person, "operation_id": capture_id}))
    checks = {"command": doc.command == command == native["command"], "request_hash": doc.request_hash == expected_hash,
              "native_result_bytes": doc.result_json == canonical_json(clean), "result_hash": doc.result_hash == digest(clean),
              "scope": (doc.company, doc.project, doc.scope_type, doc.person, doc.operation_id, doc.state) == (scope["company"], scope["project"], "Project", person, capture_id, "Succeeded")}
    if returned is not None and returned.get("original_receipt") is not None:
        original = returned["original_receipt"]
        checks["returned_result"] = {key: value for key, value in original.items() if key != "operation"} == clean
    family = clean["family"]
    result["historical_header"] = clean["header"]
    result["current_header"] = field_repo.raw(family, clean["header"]["id"])
    result["header_is_current"] = result["historical_header"] == result["current_header"]
    checks["revision"] = field_repo.raw(family + "_revision", clean["revision"]["id"]) == clean["revision"]
    checks["quantities"] = all(field_repo.raw("quantity", row["id"]) == row for row in clean["quantities"])
    checks["capture_pointer"] = capture is not None and capture["status"] == "committed" and capture["commit_receipt"] == {
        "operation_id": capture_id, "request_hash": expected_hash, "result_hash": digest(clean),
        "header_id": clean["header"]["id"], "revision_id": clean["revision"]["id"]}
    if returned and returned.get("replayed") is False:
        checks["new_apply_header"] = result["header_is_current"]
    result["checks"] = checks
    result["complete"] = result["complete"] and all(checks.values())
    return json_safe(result)


def save(admission, path, value):
    """Exclusive bounded evidence file; partial failures remain for inspection."""
    recheck(admission)
    path = Path(path)
    if path.parent.is_symlink() or stat.S_IMODE(path.parent.stat().st_mode) != 0o700:
        raise ValueError("private evidence directory required")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    size, checksum = 0, hashlib.sha256()
    with os.fdopen(fd, "wb") as stream:
        for item in json.JSONEncoder(sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).iterencode(value):
            chunk = item.encode()
            size += len(chunk)
            if size > 128 * 1024 * 1024:
                raise ValueError("complete inventory exceeds 128 MiB private artifact bound")
            stream.write(chunk)
            checksum.update(chunk)
        stream.flush()
        os.fsync(stream.fileno())
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
    return {"path": str(path), "sha256": checksum.hexdigest(), "byte_length": size, "complete": value.get("complete", False)}

"""Opt-in Company deterministic-read checkpoints; no automatic native runner.

Root separately starts authentic HTTP cases, manages supported site config and
ordinary recovery/RQ delivery. An intentionally returned committed checkpoint
is a process interruption fixture, not evidence of an OS kill or restored DB.
No clock, lease, original intent, registry or production behavior is replaced.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from .ricky_company_acceptance_support import (RECOVERY_CASES, RECOVERY_CHECKPOINTS,
    Journal, load_private, recovery_case, saved_intent, sha, timestamp, typed_equal,
    verify_read_value, write_private)
from . import test_ricky_company_native as native

SLICE = "recovery_r12"
MIN_REMAINING_SECONDS = 30


def _config():
    import frappe
    key = "cipher_execution_quarantined"
    return {"present": key in frappe.conf, "value": frappe.conf.get(key)}


def _payloads(run_id, *, include_run=True):
    """Exact native persisted JSON bytes, including older successful Steps."""
    import frappe
    from cipher_aec.ricky.storage import DOCTYPES
    result = {}
    for kind, doctype in DOCTYPES.items():
        if kind == "run" and not include_run:
            continue
        rows = frappe.db.sql(f"SELECT name,data_json FROM `tab{doctype}` WHERE run_id=%s ORDER BY name", (run_id,))
        result[kind] = {name: payload for name, payload in rows}
    return result


def _site_payloads(excluded_run_ids=()):
    """Preserve every older orchestration payload, including Project rows."""
    import frappe
    from cipher_aec.ricky.storage import DOCTYPES
    result = {}
    for kind, doctype in DOCTYPES.items():
        rows = frappe.db.sql(f"SELECT name,run_id,data_json FROM `tab{doctype}` ORDER BY name")
        result[kind] = {name: {"run_id": parent, "data_json": payload} for name, parent, payload in rows
            if parent not in excluded_run_ids and not (kind == "run" and name in excluded_run_ids)}
    return result


def _terminal_snapshot(value, cases):
    from cipher_aec.ricky.engine import FINAL
    result = {}
    for case in sorted(cases):
        run = native._run(value, case)
        if run["status"] not in FINAL:
            raise RuntimeError("Finish all older fixture Runs before this serial recovery slice.")
        receipts = {"start": native._receipt(value, case, "start")[1]}
        if any(row["key"] == "stop-" + case for row in Journal(value["journal_directory"]).rows):
            receipts["stop"] = native._receipt(value, case, "stop")[1]
        result[case] = {"intent": deepcopy(saved_intent(value, case)), "payloads": _payloads(run["id"]), "receipts": receipts}
    return result


def _baseline(value):
    recovery_case(value, RECOVERY_CASES[0])
    return load_private(Path(value["journal_directory"]) / "recovery-r12-baseline.secret.json")


def _unchanged(value):
    baseline = _baseline(value)
    excluded = [intent["run_id"] for case, intent in value["intents"].items() if case in RECOVERY_CASES]
    if (not typed_equal(_site_payloads(excluded), baseline["site_terminal_payloads"])
            or not typed_equal(_terminal_snapshot(value, baseline["older_cases"]), baseline["older_terminal"])):
        raise AssertionError("An older terminal Run, child payload, original intent or receipt changed.")
    for case, phase in value["stages"].get(SLICE, {}).items():
        if phase["status"] == "passed" and (
                not typed_equal(_payloads(saved_intent(value, case)["run_id"]), phase["terminal_payloads"])
                or not typed_equal(saved_intent(value, case), phase["terminal_intent"])
                or not typed_equal(native._receipt(value, case, "start")[1], phase["start_receipt"])):
            raise AssertionError("An earlier completed R12 case or its original start receipt changed.")


def _only_active(run_id=None):
    from cipher_aec.ricky.engine import ACTIVE
    from cipher_aec.ricky.storage import FrappeStore
    rows = FrappeStore(worker=True).find("run", {"status": ["in", list(ACTIVE)]}, limit=101)
    if sorted(row["id"] for row in rows) != ([] if run_id is None else [run_id]):
        raise RuntimeError("Ordinary site recovery requires exactly the one declared active target.")


def _phase(value, case):
    recovery_case(value, case)
    if case not in RECOVERY_CASES:
        raise ValueError("Use one of the three explicit R12 cases.")
    return value["stages"].setdefault(SLICE, {}).setdefault(case, {"status": "declared", "events": []})


def _event(path, value, case, status, **fields):
    phase = _phase(value, case)
    phase["events"].append({"at": timestamp(), "status": status, **deepcopy(fields)})
    phase["status"] = status
    write_private(path, value)
    return deepcopy(phase)


def _window(run, checkpoint, now, *, expired):
    """Observe persisted real time only; never manufacture a lease/deadline."""
    from cipher_aec.ricky.contracts import parse_time
    if (not typed_equal(run.get("lease_expires_at"), checkpoint.get("lease_expires_at"))
            or not typed_equal(run["deadline"], checkpoint["deadline"])
            or run["lease_token"] != checkpoint["lease_token"]):
        raise AssertionError("The saved checkpoint lease/deadline changed before recovery.")
    remaining = (parse_time(run["deadline"]) - now).total_seconds()
    until_lease = ((parse_time(run["lease_expires_at"]) - now).total_seconds()
        if run.get("lease_expires_at") else 0)
    if remaining < MIN_REMAINING_SECONDS:
        raise RuntimeError("Insufficient real delegation time remains; retain the failed/expired case, never reset it.")
    if expired and until_lease > 0:
        raise RuntimeError("The real persisted lease has not expired; poll without editing time.")
    return {"observed_at": now.isoformat(), "lease_expires_at": run.get("lease_expires_at"),
        "deadline": run["deadline"], "seconds_until_lease": max(0, until_lease), "seconds_until_deadline": remaining}


def prepare_company_recovery_slice(private_manifest):
    """Declare names/baseline once; allocates no operation, Run, User or Session."""
    import frappe
    from cipher_aec.governance.context import require_effects_enabled
    value = native._fixture(private_manifest)
    if "recovery_r12_declaration" in value["stages"]:
        _unchanged(value)
        return deepcopy(value["stages"]["recovery_r12_declaration"])
    if any(case in value["intents"] for case in RECOVERY_CASES):
        raise RuntimeError("Never adopt an undeclared existing recovery intent.")
    require_effects_enabled()
    _only_active()
    # Existing successful cases, session expiry, RQ delivery and R11 concurrency
    # remain separate evidence; this baseline preserves their exact old rows.
    older_cases = sorted(value["intents"])
    baseline = {"fixture_id": value["fixture_id"], "older_cases": older_cases,
        "older_terminal": _terminal_snapshot(value, older_cases), "site_terminal_payloads": _site_payloads(),
        "original_config": _config()}
    if not older_cases or value["stages"].get("claim-race-r11", {}).get("status") != "passed":
        raise RuntimeError("Retain the qualified R11/earlier terminal fixture before adding this slice.")
    path = Path(value["journal_directory"]) / "recovery-r12-baseline.secret.json"
    if path.exists():
        raise RuntimeError("Reconcile the already allocated recovery baseline; never overwrite it.")
    write_private(path, baseline)
    declaration = {"schema": "cipher.fixture.ricky.company.recovery.v1", "fixture_id": value["fixture_id"],
        "cases": RECOVERY_CHECKPOINTS, "baseline_file": path.name,
        "baseline_sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    value["stages"]["recovery_r12_declaration"] = declaration
    value["stages"][SLICE] = {}
    write_private(private_manifest, value)
    frappe.db.rollback()
    return deepcopy(declaration)


def checkpoint_company_recovery_case(private_manifest, case):
    """One ordinary claim/tool checkpoint, then intentionally return, no finish."""
    from cipher_aec.governance.context import require_effects_enabled
    from cipher_aec.ricky.company_service import CompanyExecution, build_service
    from cipher_aec.ricky.company_contracts import decode_run_authority
    value = native._fixture(private_manifest)
    recovery_case(value, case, admission=True)
    phase = _phase(value, case)
    if phase["status"] != "declared":
        raise RuntimeError("Checkpoint effects are one-shot; capture/read back the retained phase instead.")
    require_effects_enabled()
    _unchanged(value)
    run = native._run(value, case)
    _only_active(run["id"])
    if run["status"] != "queued" or run["lease_token"] != 0 or run["tool_calls"] != 0:
        raise RuntimeError("Use only the exact newly admitted queued HTTP Run.")
    phase["admission_run"] = deepcopy(run)
    _event(private_manifest, value, case, "entered_checkpoint", run_id=run["id"])
    service = build_service(worker=True)
    if case != "quarantine-r12":
        with service.backend.original_user(decode_run_authority(run)):
            claimed = service.claim(run["id"])
            if claimed is None or claimed[1] != 1:
                raise AssertionError("The new original HTTP Run did not acquire its first ordinary lease.")
            if case == "interrupted-read-r12":
                CompanyExecution(service, run["id"], claimed[1]).invoke(
                    "aec.pursuit.lookup", {}, "selected-deterministic-read")
    return capture_company_recovery_checkpoint(private_manifest, case)


def capture_company_recovery_checkpoint(private_manifest, case):
    """Read-only reconciliation if a checkpoint committed before helper exit."""
    import frappe
    from cipher_aec.ricky.company_service import build_service
    from cipher_aec.ricky.contracts import utcnow
    value = native._fixture(private_manifest)
    phase = _phase(value, case)
    if phase["status"] not in ("entered_checkpoint", "checkpoint_captured"):
        raise RuntimeError("Capture only the retained one-shot checkpoint phase.")
    run = native._run(value, case)
    _only_active(run["id"])
    children = _payloads(run["id"], include_run=False)
    expected_status, token, count = {"interrupted-read-r12": ("executing", 1, 1),
        "recovery-authority-r12": ("retrieving", 1, 0), "quarantine-r12": ("queued", 0, 0)}[case]
    if (run["status"] != expected_status or run["lease_token"] != token or run["tool_calls"] != count
            or run["result"] is not None or run["generations"] != 0 or run["proposal_ids"]
            or len(children["step"]) != count or len(children["invocation"]) != count):
        raise AssertionError("The actual saved checkpoint does not match its declared boundary.")
    if count:
        receipt = build_service(worker=True)._successful_invocation(run)
        verify_read_value(value["inputs"], case, receipt["output"])
    observation = _window(run, run, utcnow(), expired=False)
    if "checkpoint" in phase:
        if not typed_equal(phase["checkpoint"], {"run": run, "children": children}):
            raise AssertionError("The originally captured checkpoint payload changed.")
    else:
        phase["checkpoint"] = {"run": deepcopy(run), "children": children}
    _unchanged(value)
    frappe.db.rollback()
    return _event(private_manifest, value, case, "checkpoint_captured", window=observation,
        qualification="Committed checkpoint interruption; no OS-kill claim.")


def prepare_company_recovery_dispatch(private_manifest, case):
    """Read/persist real expiry, then root uses unmodified recover_pending/RQ."""
    import frappe
    from cipher_aec.governance.context import require_effects_enabled
    from cipher_aec.ricky.contracts import utcnow
    value = native._fixture(private_manifest)
    phase = _phase(value, case)
    if case == "recovery-authority-r12" or phase["status"] not in ("checkpoint_captured", "dispatch_ready"):
        raise RuntimeError("Use the separate bounded current-authority refusal helper for its case.")
    require_effects_enabled()
    run = native._run(value, case)
    _only_active(run["id"])
    checkpoint = phase["checkpoint"]
    if not typed_equal(run, checkpoint["run"]) or not typed_equal(_payloads(run["id"], include_run=False), checkpoint["children"]):
        raise AssertionError("The paused native checkpoint changed before ordinary recovery.")
    if case == "quarantine-r12":
        if not phase.get("quarantine_native") or not phase.get("quarantine_http"):
            raise RuntimeError("Both fresh native and actual HTTP quarantine proofs must precede restoration/recovery.")
        if not typed_equal(_config(), _baseline(value)["original_config"]):
            raise AssertionError("Restore the exact original configuration key/value/presence first.")
    window = _window(run, checkpoint["run"], utcnow(), expired=True)
    _unchanged(value)
    frappe.db.rollback()
    return _event(private_manifest, value, case, "dispatch_ready", window=window)


def run_company_recovery_authority_refusal(private_manifest):
    """Actual worker callthrough after expiry, exact duty outage/restoration."""
    import frappe
    from cipher_aec.ricky.contracts import utcnow
    from cipher_aec.ricky.worker import process_run
    case = "recovery-authority-r12"
    value = native._fixture(private_manifest)
    phase = _phase(value, case)
    if phase["status"] != "checkpoint_captured":
        raise RuntimeError("This source-outage recovery attempt is one-shot; reconcile its saved phase.")
    run = native._run(value, case)
    _only_active(run["id"])
    if not typed_equal(run, phase["checkpoint"]["run"]):
        raise AssertionError("The original claimed Run changed before authority-refused recovery.")
    window = _window(run, phase["checkpoint"]["run"], utcnow(), expired=True)
    original = native._capture_duty_outage(value, "document.read", "recovery-authority-r12-outage", private_manifest)
    _event(private_manifest, value, case, "entered_authority_refusal", window=window)
    try:
        native._duty(value, "document.read", 0, original)
        native._independent_duty_readback(value, "document.read", {**deepcopy(original), "active": 0,
            "fields": {**deepcopy(original["fields"]), "active": native._native_scalar(0)}})
        process_run(run["id"])
    except Exception as error:
        _event(private_manifest, value, case, "failed", error=native._claim_failure(error))
        raise
    finally:
        frappe.db.rollback()
        try:
            native._duty(value, "document.read", original["active"], original)
            native._independent_duty_readback(value, "document.read", original)
        except Exception as error:
            _event(private_manifest, value, case, "failed", restoration_error=native._claim_failure(error))
            raise
        _event(private_manifest, value, case, _phase(value, case)["status"], exact_duty_restored=True)
    return verify_company_recovery_case(private_manifest, case)


def verify_company_quarantine_native(private_manifest):
    """Read-only native guard proof; root alone changes supported site config."""
    import frappe
    from cipher_aec.api.errors import DomainError
    from cipher_aec.governance.context import execution_quarantined
    from cipher_aec.ricky.company_service import build_service
    from cipher_aec.ricky.worker import process_run, recover_pending
    case = "quarantine-r12"
    value = native._fixture(private_manifest)
    phase = _phase(value, case)
    if phase["status"] != "checkpoint_captured" or phase.get("quarantine_native_entered"):
        raise RuntimeError("Run this native quarantine observation once from its captured queued phase.")
    if not execution_quarantined():
        raise RuntimeError("A fresh native process must observe the supported persisted quarantine configuration.")
    run = native._run(value, case)
    _only_active(run["id"])
    before = _payloads(run["id"])
    expected = {"status": "skipped", "code": "execution_quarantined"}
    phase["quarantine_native_entered"] = timestamp()
    _event(private_manifest, value, case, "checkpoint_captured", entered_native_quarantine=True)
    try:
        results = {"worker": process_run(run["id"]), "recovery": recover_pending()}
        try:
            build_service(worker=True).process(run["id"])
        except DomainError as error:
            results["direct_service"] = {"code": error.code, "status": error.status}
        else:
            raise AssertionError("Quarantine allowed direct ordinary processing.")
        phase["quarantine_native"] = {"config": _config(), "results": results,
            "before_sha256": sha(before), "after_sha256": sha(_payloads(run["id"]))}
        _event(private_manifest, value, case, "checkpoint_captured", quarantine_native=phase["quarantine_native"])
        if (not typed_equal(results["worker"], expected) or not typed_equal(results["recovery"], expected)
                or results["direct_service"] != {"code": "execution_quarantined", "status": 503}
                or not typed_equal(before, _payloads(run["id"])) or not typed_equal(run, phase["checkpoint"]["run"])):
            _event(private_manifest, value, case, "failed", reason="quarantine_guard_or_payload_drift")
            raise AssertionError("Quarantine changed the queued target or allowed execution/recovery.")
        _unchanged(value)
        frappe.db.rollback()
        return deepcopy(phase["quarantine_native"])
    except Exception as error:
        _event(private_manifest, value, case, "failed", error=native._claim_failure(error))
        raise


def verify_company_quarantine_http(private_manifest, base_url, host_header=None):
    """Actual HTTP denial demonstrates the serving process observed config."""
    from .test_ricky_company_http import _HTTP, RICKY
    rpc = _HTTP(private_manifest, base_url, host_header)
    case = "quarantine-r12"
    phase = _phase(rpc.value, case)
    if phase["status"] != "checkpoint_captured" or phase.get("quarantine_http_entered") or not phase.get("quarantine_native"):
        raise RuntimeError("Observe this separate queued quarantine case once, after fresh native quarantine proof.")
    if not (rpc.work / "author.cookies.secret").is_file():
        raise RuntimeError("Use the retained current author cookie; never log in a replacement Session.")
    intent = saved_intent(rpc.value, case)
    rpc.login()  # Existing current author cookie; never fresh=True or replacement original session.
    fields = {key: value for key, value in intent["payload"].items() if key != "operation_id"}
    phase["quarantine_http_entered"] = timestamp()
    _event(private_manifest, rpc.value, case, "checkpoint_captured", entered_HTTP_quarantine=True)
    try:
        current = rpc.call(RICKY + "get_run", {"company": rpc.value["company"], "run_id": intent["run_id"]})["data"]
        replay = rpc.call(RICKY + "start_read", fields, key="start-" + case)["data"]
        denial = rpc.call(RICKY + "start_read", fields, key="quarantine-admission-r12", expected={"execution_quarantined"})
        operation = rpc.call("cipher_aec.api.company.operation", {"company": rpc.value["company"], "operation_id": intent["operation_id"]})["data"]
        if (current["status"] != "queued" or not replay["operation"]["replayed"]
                or not typed_equal({key: value for key, value in replay.items() if key != "operation"}, intent["start"])):
            raise AssertionError("Quarantine lost authorized status or the exact original queued receipt.")
        phase["quarantine_http"] = {"denial_request_id": denial["request_id"], "read_request_run": current["id"],
            "retained_queued_receipt": replay, "operation_read": operation,
            "qualification": "Actual new admission503 proves handling web process observed quarantine; no restore/backup claim."}
        return _event(private_manifest, rpc.value, case, "checkpoint_captured", quarantine_http=phase["quarantine_http"])
    except Exception as error:
        _event(private_manifest, rpc.value, case, "failed", error=native._claim_failure(error))
        raise


def verify_company_quarantine_restored_http(private_manifest, base_url, host_header=None):
    """A new source-free Stop receipt proves web execution config restoration.

    Old receipt replay deliberately remains readable during quarantine, so it
    cannot supply this proof. The already successful Run itself must not change.
    """
    from .test_ricky_company_http import _HTTP, RICKY
    rpc = _HTTP(private_manifest, base_url, host_header)
    case = "quarantine-r12"
    phase = _phase(rpc.value, case)
    if phase["status"] != "passed" or phase.get("restored_http_entered"):
        raise RuntimeError("Complete native recovery once before the separate restored-web proof.")
    if not (rpc.work / "author.cookies.secret").is_file():
        raise RuntimeError("Use the retained current author cookie.")
    intent = saved_intent(rpc.value, case)
    rpc.login()
    fields = {"company": rpc.value["company"], "run_id": intent["run_id"]}
    phase["restored_http_entered"] = timestamp()
    _event(private_manifest, rpc.value, case, "passed", entered_restored_HTTP=True)
    try:
        before = rpc.call(RICKY + "get_run", fields)["data"]
        result = rpc.call(RICKY + "cancel_run", fields, key="stop-" + case)["data"]
        if before["status"] != "succeeded" or result["status"] != "succeeded" or result["operation"]["replayed"]:
            raise AssertionError("Require the first new successful Stop receipt after restoration; no older replay substitution.")
        after = rpc.call(RICKY + "get_run", fields)["data"]
        if not typed_equal(before, after):
            raise AssertionError("A terminal successful Run changed while proving restored web configuration.")
        replay = rpc.call(RICKY + "cancel_run", fields, key="stop-" + case)["data"]
        operation = rpc.call("cipher_aec.api.company.operation", {"company": rpc.value["company"],
            "operation_id": result["operation"]["id"]})["data"]
        if not replay["operation"]["replayed"] or not typed_equal({key: value for key, value in result.items() if key != "operation"},
                {key: value for key, value in replay.items() if key != "operation"}):
            raise AssertionError("The separately created restored-web Stop receipt changed.")
        phase["restored_http"] = {"first_stop": result, "replay": replay, "operation_read": operation,
            "terminal_dto_unchanged": True, "separate_denied_admission_intent_retained": True}
        return _event(private_manifest, rpc.value, case, "passed", restored_http=phase["restored_http"])
    except Exception as error:
        _event(private_manifest, rpc.value, case, "failed", error=native._claim_failure(error))
        raise


def _denied_admission(value):
    import frappe
    rows = [row for row in Journal(value["journal_directory"]).rows if row["key"] == "quarantine-admission-r12"]
    intent = saved_intent(value, "quarantine-r12")
    if (len(rows) != 1 or rows[0]["role"] != "author" or rows[0]["method"] != "cipher_aec.ricky.company_api.start_read"
            or rows[0]["operation_id"] == intent["operation_id"]
            or not typed_equal({key: item for key, item in rows[0]["payload"].items() if key != "operation_id"},
                {key: item for key, item in intent["payload"].items() if key != "operation_id"})
            or not rows[0]["attempts"] or any(attempt.get("status") != 503
                or attempt.get("envelope", {}).get("error", {}).get("code") != "execution_quarantined"
                for attempt in rows[0]["attempts"])):
        raise AssertionError("Retain the distinct exact original denied admission UUID/payload/503 journal.")
    key = sha({"person": value["users"]["author"]["person"], "operation_id": rows[0]["operation_id"]})
    if frappe.db.exists("Cipher Command Receipt", key) or frappe.db.count("Cipher Ricky Run", {"operation_key": key}):
        raise AssertionError("The quarantined denied admission created a receipt or Run.")
    return {"operation_id": rows[0]["operation_id"], "no_receipt_or_run": True}


def _verify_transition(case, checkpoint, run):
    """Only the documented worker completion fields may change."""
    allowed = {"status", "lease_token", "lease_expires_at", "result", "result_digest", "completed_at"}
    if case == "quarantine-r12":
        allowed |= {"tool_calls", "context", "original_manifest", "original_manifest_digest", "prepared_manifest_digest"}
    if case == "recovery-authority-r12":
        allowed = {"status", "error", "completed_at"}
    if not typed_equal({key: value for key, value in checkpoint.items() if key not in allowed},
            {key: value for key, value in run.items() if key not in allowed}):
        raise AssertionError("Recovery changed an original authority/selection/source/counter/header.")
    expected = "failed" if case == "recovery-authority-r12" else "succeeded"
    if run["status"] != expected or run["lease_token"] != checkpoint["lease_token"] + (0 if expected == "failed" else 1):
        raise AssertionError("Recovery did not preserve its exact expected terminal/fencing transition.")


def verify_company_recovery_case(private_manifest, case):
    """Fresh native readback and stale-worker refusal, never repairs a Run."""
    import frappe
    from cipher_aec.ricky.company_service import CompanyExecution, build_service
    from cipher_aec.ricky.company_contracts import decode_run_authority
    from cipher_aec.ricky.contracts import RickyError
    value = native._fixture(private_manifest)
    phase = _phase(value, case)
    expected_phase = "entered_authority_refusal" if case == "recovery-authority-r12" else "dispatch_ready"
    if phase["status"] != expected_phase:
        raise RuntimeError("Reconcile the recorded phase; never turn a failed attempt into success.")
    try:
        run = native._run(value, case)
        checkpoint = phase["checkpoint"]
        observation = {"run": deepcopy(run), "children": _payloads(run["id"], include_run=False)}
        _event(private_manifest, value, case, expected_phase, terminal_observation=observation)
        _verify_transition(case, checkpoint["run"], run)
        if case == "recovery-authority-r12":
            if (run["result"] is not None or run["error"]["code"] not in ("not_found", "capability_denied", "stale_authority")
                    or not typed_equal(observation["children"], checkpoint["children"])):
                raise AssertionError("Current original-authority refusal accepted output or changed children.")
        else:
            verify_read_value(value["inputs"], case, run["result"])
            service = build_service(worker=True)
            receipt = service._successful_invocation(run)
            service._result_linkage(run)
            if (run["tool_calls"] != 1 or run["generations"] != 0 or run["proposal_ids"]
                    or receipt["output_digest"] != run["result_digest"] or not typed_equal(receipt["output"], run["result"])):
                raise AssertionError("Recovery did not bind exactly one deterministic successful invocation.")
            if case == "interrupted-read-r12" and not typed_equal(observation["children"], checkpoint["children"]):
                raise AssertionError("Recovery changed/repeated the already committed Invocation/Step/artifact bytes.")
            if case == "quarantine-r12":
                phase["denied_admission_native"] = _denied_admission(value)
                if not typed_equal(_config(), _baseline(value)["original_config"]):
                    raise AssertionError("The exact original config key/value/presence is not restored.")
                if (len(observation["children"]["step"]) != 1 or len(observation["children"]["invocation"]) != 1
                        or not typed_equal(run["context"], [{"tool": "aec.pursuit.lookup", "data": run["result"]}])
                        or not typed_equal({key: value for key, value in observation["children"].items() if key not in ("step", "invocation")},
                            {key: value for key, value in checkpoint["children"].items() if key not in ("step", "invocation")})):
                    raise AssertionError("Restored quarantine execution changed delegation/artifacts or repeated the fixed tool.")
            if case == "interrupted-read-r12":
                before = _payloads(run["id"])
                with service.backend.original_user(decode_run_authority(run)):
                    try:
                        CompanyExecution(service, run["id"], checkpoint["run"]["lease_token"]).invoke(
                            "aec.pursuit.lookup", {}, "selected-deterministic-read")
                    except RickyError as error:
                        if error.code not in ("cancelled", "lease_lost"):
                            raise
                    else:
                        raise AssertionError("The interrupted worker's old token accepted a result.")
                if not typed_equal(before, _payloads(run["id"])):
                    raise AssertionError("A fenced old worker changed terminal payloads.")
        _unchanged(value)
        _only_active()
        phase.update(terminal_payloads=_payloads(run["id"]), terminal_intent=deepcopy(saved_intent(value, case)),
            start_receipt=native._receipt(value, case, "start")[1])
        frappe.db.rollback()
        return _event(private_manifest, value, case, "passed", terminal_sha256=sha(observation),
            model_invoked=False, older_terminal_bytes_unchanged=True,
            mode="actual_process_run_callthrough" if case == "recovery-authority-r12" else "root_records_ordinary_recover_pending_and_RQ_evidence_separately")
    except Exception as error:
        _event(private_manifest, value, case, "failed", error=native._claim_failure(error))
        raise


def verify_company_recovery_receipts(private_manifest):
    """Reuse the existing central byte/schema verifier for these four receipts."""
    import frappe
    from .ricky_company_central_acceptance import verify_shared_receipts
    value = native._fixture(private_manifest)
    _unchanged(value)
    required = [*("start-" + case for case in RECOVERY_CASES), "stop-quarantine-r12"]
    before = value["stages"].get("receipt_before", {})
    observed = value["stages"].get("receipt_http_observations", {})
    if any(key not in before or key not in observed for key in required):
        raise RuntimeError("Capture native receipt bytes before a subsequent actual same-UUID HTTP replay/operation read.")
    rows = []
    for key in required:
        kind, case = key.split("-", 1)
        journal, stored = native._receipt(value, case, kind)
        initial = [attempt["envelope"]["data"] for attempt in journal["attempts"] if attempt.get("status") == 200
            and attempt.get("envelope", {}).get("data", {}).get("operation", {}).get("replayed") is False]
        if len(initial) != 1:
            raise AssertionError("Retain the exact original non-replayed response; never reconstruct it.")
        rows.append({"user": value["users"]["author"]["user"], "person": value["users"]["author"]["person"],
            "company": value["company"], "run_id": saved_intent(value, case)["run_id"], "operation_id": journal["operation_id"],
            "command": "ricky.company.read.start.v1" if kind == "start" else "ricky.company.read.cancel.v1",
            "initial": initial[0], "replay": observed[key]["replay"], "operation_read": observed[key]["operation_read"],
            "stored_receipt": {"before": before[key], "after": stored}})
    result = verify_shared_receipts({**value, "shared_receipt_observations": rows})
    value["stages"]["recovery_r12_receipts"] = {"status": "passed", "coverage": required, "observations": rows, **result}
    write_private(private_manifest, value)
    frappe.db.rollback()
    return {"status": "passed", "coverage": required, **result}

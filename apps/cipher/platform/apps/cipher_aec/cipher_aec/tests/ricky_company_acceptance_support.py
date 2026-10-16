"""Private, opt-in Company Ricky fixture journal; no application authority."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from uuid import UUID, uuid4

SCHEMA = "cipher.fixture.ricky.company.v1"
RECOVERY_CASES = ("interrupted-read-r12", "recovery-authority-r12", "quarantine-r12")
RECOVERY_CHECKPOINTS = dict(zip(RECOVERY_CASES, ("successful-invocation", "claimed", "queued")))
CASES = ("lookup", "recompute", "compare", "convert", "claim-race", "fenced-stop",
         "expired-original", "source-revoked-stop", "capability-revoked", "queued-delivery", "convert-r9", "claim-race-r9", "claim-race-r11", *RECOVERY_CASES)
CORRECTED_CASES = {"convert-r9": ("convert", "failed"), "claim-race-r9": ("claim-race", "cancelled"),
    "claim-race-r11": ("claim-race-r9", "cancelled")}
ROLES = ("author", "alias", "outsider")
RICKY_TYPES = ("Cipher Ricky Run", "Cipher Ricky Step", "Cipher Tool Invocation",
               "Cipher Proposed Change", "Cipher Delegation", "Cipher Run Artifact")


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def sha(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def typed_equal(left, right):
    return canonical(left) == canonical(right)


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def write_private(path, value):
    """Atomic replacement plus file and directory fsync before proceeding."""
    path = Path(path)
    if not path.parent.is_dir() or path.parent.is_symlink():
        raise ValueError("Use an existing private fixture directory.")
    temporary = path.with_name(path.name + "." + uuid4().hex + ".pending")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w") as stream:
            stream.write(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        descriptor = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    finally:
        if temporary.exists():
            temporary.unlink()


def load_private(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_mode & 0o077:
        raise ValueError("Use an existing mode0600 private fixture file.")
    return json.loads(path.read_text())


def validate_company_reference(reference):
    """Closed fixture evidence shape; it grants no Company or native rights."""
    if (type(reference) is not dict or set(reference) != {"schema", "company", "abbr", "default_currency", "country",
            "default_receivable_account", "account", "initial_project_ids"}
            or reference["schema"] != "cipher.fixture.ricky.company.reference.v1"):
        raise ValueError("Use the exact supported existing synthetic Company reference.")
    for key in ("company", "abbr", "default_currency", "country", "default_receivable_account"):
        value = reference[key]
        if type(value) is not str or not 1 <= len(value) <= 140 or value != value.strip() or any(ord(c) < 32 for c in value):
            raise ValueError("Use exact recorded native Company reference names.")
    account = reference["account"]
    expected = {"name": reference["default_receivable_account"], "company": reference["company"], "account_currency": "USD",
        "account_type": "Receivable", "is_group": 0, "disabled": 0}
    projects = reference["initial_project_ids"]
    if (reference["default_currency"] != "USD" or reference["country"] != "United States"
            or not typed_equal(account, expected) or type(projects) is not list
            or any(type(name) is not str or not 1 <= len(name) <= 140 or name != name.strip() or any(ord(c) < 32 for c in name) for name in projects)
            or projects != sorted(set(projects))):
        raise ValueError("The existing Company reference requires its exact active leaf USD Receivable account and original Project IDs.")
    return reference


def fixture_company_reference(value):
    native = value["native"]
    if "company_reference" not in native:
        return None
    reference = validate_company_reference(native["company_reference"])
    setup = native.get("setup_inputs", {})
    if (value["company"] != reference["company"]
            or any(setup.get(key) != reference[field] for key, field in (("company_abbr", "abbr"), ("currency", "default_currency"), ("country", "country")))
            or setup.get("customer_group") != "Commercial" or setup.get("territory") != "United States"
            or not typed_equal(native.get("original_project_ids"), reference["initial_project_ids"])):
        raise ValueError("The fixture does not bind its exact recorded existing Company reference.")
    return reference


def manifest(path):
    value = load_private(path)
    if (type(value) is not dict or set(value) != {"schema", "fixture_id", "site", "created_at", "company",
            "users", "native", "duties", "inputs", "intents", "stages", "preservation", "journal_directory",
            "metadata_preservation", "native_projection_observations", "shared_receipt_observations"}
            or value["schema"] != SCHEMA or not value["fixture_id"].startswith("ricky-company-")
            or set(value["users"]) != set(ROLES)):
        raise ValueError("Use the exact Company Ricky fixture manifest.")
    suffix = value["fixture_id"].removeprefix("ricky-company-")
    if len(suffix) != 12 or any(c not in "0123456789abcdef" for c in suffix):
        raise ValueError("The fixture identity is malformed.")
    if fixture_company_reference(value) is None and value["company"] != "Ricky Company " + suffix:
        raise ValueError("The fixture Company does not match its identity.")
    for role in ROLES:
        row = value["users"][role]
        if (set(row) != {"user", "person", "password"} or row["user"] != f"ricky.company.{role}.{suffix}@cipher.example"
                or type(row["person"]) is not str or len(row["person"]) != 10):
            raise ValueError("Only this fixture's original native identities may be used.")
    if (value["users"]["alias"]["person"] != value["users"]["author"]["person"]
            or value["users"]["outsider"]["person"] == value["users"]["author"]["person"]):
        raise ValueError("The fixture Person distinction changed.")
    if Path(value["journal_directory"]).resolve() != Path(path).resolve().parent:
        raise ValueError("The fixture journal is outside its original directory.")
    if any(key not in CASES for key in value["intents"]):
        raise ValueError("This fixture has an undeclared run case.")
    declarations = value["stages"].get("corrected_cases", {})
    if type(declarations) is not dict or set(declarations) - CORRECTED_CASES.keys():
        raise ValueError("Use only literal corrected fixture cases.")
    for case in set(declarations) | (set(value["intents"]) & CORRECTED_CASES.keys()):
        declared_case(value, case)
    if "recovery_r12_declaration" in value["stages"] or set(value["intents"]) & set(RECOVERY_CASES):
        recovery_case(value, RECOVERY_CASES[0])
    return value


def recovery_case(value, case, *, admission=False):
    """Three new serial requests, never replacements for any retained case."""
    if case not in RECOVERY_CASES:
        return
    declaration = value["stages"].get("recovery_r12_declaration")
    expected = {"schema": "cipher.fixture.ricky.company.recovery.v1", "fixture_id": value["fixture_id"],
        "cases": RECOVERY_CHECKPOINTS, "baseline_file": "recovery-r12-baseline.secret.json"}
    if (type(declaration) is not dict or set(declaration) != {*expected, "baseline_sha256"}
            or not typed_equal({key: declaration[key] for key in expected}, expected)):
        raise ValueError("Declare the exact three new recovery cases before their first HTTP effect.")
    path = Path(value["journal_directory"]) / declaration["baseline_file"]
    baseline = load_private(path)
    if (type(baseline) is not dict or set(baseline) != {"fixture_id", "older_cases", "older_terminal", "site_terminal_payloads", "original_config"}
            or baseline["fixture_id"] != value["fixture_id"]
            or type(baseline["older_cases"]) is not list or baseline["older_cases"] != sorted(baseline["older_terminal"])
            or baseline["older_cases"] != sorted(set(value["intents"]) - set(RECOVERY_CASES))
            or any(not typed_equal(value["intents"][prior], baseline["older_terminal"][prior]["intent"]) for prior in baseline["older_cases"])):
        raise ValueError("Retain this exact fixture and all older original intents in the recovery baseline.")
    if hashlib.sha256(path.read_bytes()).hexdigest() != declaration["baseline_sha256"]:
        raise ValueError("The original recovery baseline bytes changed.")
    if admission and case not in value["intents"]:
        previous = RECOVERY_CASES[:RECOVERY_CASES.index(case)]
        if any(value["stages"].get("recovery_r12", {}).get(prior, {}).get("status") != "passed" for prior in previous):
            raise ValueError("Finish each declared recovery case before admitting the next.")


def _r9_claim_diagnostic(proof, run_id):
    """Literal retained native observation; never manufacture a prior Run."""
    message = str((1020, "Record has changed since last read in table 'tabCipher Ricky Run'; try restarting transaction"))
    if (type(proof) is not dict or set(proof) != {"at", "claims", "run_id", "status", "thread_alive"}
            or proof["run_id"] != run_id or proof["status"] != "observed_before_assertions"
            or not typed_equal(proof["thread_alive"], [False, False]) or type(proof["at"]) is not str or not proof["at"]
            or type(proof["claims"]) is not list or len(proof["claims"]) != 2
            or any(type(row) is not dict or type(row.get("thread")) is not int for row in proof["claims"])
            or {row["thread"] for row in proof["claims"]} != {0, 1}):
        raise ValueError("Use the exact two-finished-thread original R9 claim diagnostic.")
    winners = [row for row in proof["claims"] if row.get("claimed") is True]
    losers = [row for row in proof["claims"] if row.get("error_type") == "QueryDeadlockError"]
    if (len(winners) != 1 or set(winners[0]) != {"thread", "claimed", "token"}
            or type(winners[0]["token"]) is not int or winners[0]["token"] != 1
            or len(losers) != 1 or set(losers[0]) != {"thread", "error_type", "error_code", "error_message"}
            or losers[0]["error_code"] != message[:80] or losers[0]["error_message"] != message):
        raise ValueError("Retain the single original R9 winner and exact observed native1020 loser.")


def declared_case(value, case):
    """An explicit separate request retains its terminal predecessor evidence."""
    if case not in CORRECTED_CASES:
        if case not in CASES: raise ValueError("Use one declared literal case.")
        return case
    original, status = CORRECTED_CASES[case]
    declaration = value["stages"].get("corrected_cases", {}).get(case)
    fields = {"schema", "case", "predecessor_case", "predecessor_run_id", "predecessor_operation_id",
        "predecessor_intent_sha256", "predecessor_status", "predecessor_run_sha256", "evidence"}
    intent = saved_intent(value, original)
    if (type(declaration) is not dict or set(declaration) != fields
            or declaration["schema"] != "cipher.fixture.ricky.corrected-case.v1" or declaration["case"] != case
            or declaration["predecessor_case"] != original or declaration["predecessor_status"] != status
            or declaration["predecessor_run_id"] != intent["run_id"]
            or declaration["predecessor_operation_id"] != intent["operation_id"]
            or declaration["predecessor_intent_sha256"] != sha(intent)
            or type(declaration["evidence"]) is not list or not 1 <= len(declaration["evidence"]) <= 3):
        raise ValueError("A corrected case needs its exact original terminal predecessor declaration.")
    terminal, unresolved_race = False, original != "claim-race"
    diagnostic = case != "claim-race-r11"
    for evidence in declaration["evidence"]:
        if (type(evidence) is not dict or set(evidence) != {"file", "sha256"}
                or type(evidence["file"]) is not str or not evidence["file"]
                or Path(evidence["file"]).name != evidence["file"] or evidence["file"] in {".", ".."}):
            raise ValueError("Use an exact private predecessor evidence basename and hash.")
        path = Path(value["journal_directory"]) / evidence["file"]
        proof = load_private(path)
        if hashlib.sha256(path.read_bytes()).hexdigest() != evidence["sha256"]:
            raise ValueError("Original predecessor evidence bytes changed.")
        if case == "claim-race-r11":
            stage = value["stages"].get(original)
            _r9_claim_diagnostic(stage, intent["run_id"])
            if type(proof) is dict and set(proof) == {"at", "claims", "run_id", "status", "thread_alive"}:
                if not typed_equal(proof, stage):
                    raise ValueError("The original R9 diagnostic bytes differ from its retained stage.")
                diagnostic = True
                continue
            if (type(proof) is not dict or set(proof) != {"run", "intent", "stage", "prior_declaration", "invocation_count"}
                    or not typed_equal(proof["intent"], intent) or not typed_equal(proof["stage"], stage)
                    or not typed_equal(proof["prior_declaration"], value["stages"]["corrected_cases"][original])
                    or type(proof["invocation_count"]) is not int or proof["invocation_count"] != 0
                    or type(proof["run"]) is not dict
                    or type(proof["run"].get("lease_token")) is not int or proof["run"]["lease_token"] != 2):
                raise ValueError("Use the exact original R9 cancelled Run, intent, diagnostic and prior declaration readback.")
        run = proof.get("run") if type(proof) is dict else None
        if (type(run) is not dict or run.get("id") != intent["run_id"] or run.get("operation_id") != intent["operation_id"]
                or run.get("company") != value["company"] or run.get("user") != value["users"]["author"]["user"]
                or run.get("person") != value["users"]["author"]["person"] or run.get("scope_type") != "Company"
                or run.get("project") is not None or not typed_equal(run.get("request"), intent["payload"]["request"])):
            raise ValueError("The predecessor evidence belongs to another original Run.")
        if original == "claim-race" and run.get("status") in {"queued", "retrieving", "executing"}:
            unresolved_race = True
        terminal |= (run.get("status") == status and sha(run) == declaration["predecessor_run_sha256"]
            and run.get("result") is None and run.get("cancel_requested") is (status == "cancelled")
            and type(run.get("completed_at")) is str and bool(run["completed_at"])
            and (original != "convert" or run.get("error", {}).get("code") == "source_integrity"))
    if not terminal or not unresolved_race or not diagnostic:
        raise ValueError("A corrected case requires its exact immutable terminal predecessor readback.")
    return declared_case(value, original)


def declare_corrected_case(private_manifest, declaration):
    """Operator opt-in only; does not allocate operations or originate a start."""
    value = manifest(private_manifest)
    case = declaration.get("case") if type(declaration) is dict else None
    if case not in CORRECTED_CASES: raise ValueError("Use one literal corrected case.")
    declarations = value["stages"].setdefault("corrected_cases", {})
    if case in declarations and not typed_equal(declarations[case], declaration):
        raise ValueError("An original corrected-case declaration is immutable.")
    if case not in declarations and (case in value["intents"] or any(row["key"] == "start-" + case for row in Journal(value["journal_directory"]).rows)):
        raise ValueError("Declare a correction before any new command is allocated.")
    declarations[case] = declaration
    declared_case(value, case)
    write_private(private_manifest, value)
    return declaration


def completed_read_cases(value):
    """Separate successful coverage; a failed original never becomes passed."""
    conversion = "convert-r9" if "convert-r9" in value["stages"].get("corrected_cases", {}) else "convert"
    declared_case(value, conversion)
    return ("lookup", "recompute", "compare", conversion)


class Journal:
    """One fixed HTTP command origin; uncertainty never mints another UUID."""
    def __init__(self, directory):
        self.path = Path(directory) / "http-journal.secret.json"
        self.rows = load_private(self.path) if self.path.exists() else []
        if type(self.rows) is not list:
            raise ValueError("The original HTTP journal is malformed.")

    def prepare(self, key, role, method, values):
        if role not in ROLES or type(key) is not str:
            raise ValueError("Use a declared fixture role and literal case key.")
        def sensitive(value):
            if isinstance(value, dict):
                return any(str(key).lower() in {"password", "pwd", "csrf_token", "sid", "cookie", "authorization"}
                    or sensitive(item) for key, item in value.items())
            return isinstance(value, list) and any(sensitive(item) for item in value)
        if sensitive(values):
            raise ValueError("Credentials/cookies cannot enter the command journal.")
        matches = [row for row in self.rows if row["key"] == key]
        if matches:
            row = matches[0]
            proposed = {**values, "operation_id": row["operation_id"]}
            if (len(matches) != 1 or row["role"] != role or row["method"] != method
                    or sha(row["payload"]) != row["payload_sha256"] or canonical(row["payload"]) != canonical(proposed)):
                raise ValueError("An existing command must retain its exact original payload and UUID.")
            return row
        operation = str(uuid4())
        payload = {**values, "operation_id": operation}
        row = {"key": key, "role": role, "method": method, "operation_id": operation, "payload": payload,
               "payload_sha256": sha(payload), "prepared_at": timestamp(), "attempts": []}
        self.rows.append(row)
        write_private(self.path, self.rows)
        return row

    def response(self, row, *, status, envelope):
        if row not in self.rows or str(UUID(row["operation_id"])) != row["operation_id"] or sha(row["payload"]) != row["payload_sha256"]:
            raise ValueError("The response does not belong to its original command.")
        # Full authored command results are private. Cookies, passwords and CSRF
        # tokens are never copied out of the client into this journal.
        row["attempts"].append({"recorded_at": timestamp(), "status": status, "envelope": envelope})
        write_private(self.path, self.rows)

    def uncertain(self, row, error, observation=None):
        if row not in self.rows:
            raise ValueError("An uncertain outcome requires its original prepared command.")
        row["uncertain_transport"] = {"at": timestamp(), "error_type": type(error).__name__}
        if observation is not None:
            row["uncertain_transport"]["response_observation"] = observation
        write_private(self.path, self.rows)

    def refusal(self, row, status, reason, observation):
        row["attempts"].append({"recorded_at": timestamp(), "status": status, "refusal": reason,
            "response_observation": observation})
        write_private(self.path, self.rows)


def saved_intent(value, case):
    from jsonschema import Draft202012Validator, FormatChecker
    from cipher_aec.ricky.company_contracts import DeterministicReadRequest
    if case not in CASES or case not in value["intents"]:
        raise ValueError("The authentic HTTP start for this declared case is missing.")
    if case in CORRECTED_CASES: declared_case(value, case)
    recovery_case(value, case)
    intent = value["intents"][case]
    if (set(intent) != {"case", "operation_id", "payload", "payload_sha256", "start", "run_id", "request_id"}
            or intent["case"] != case or sha(intent["payload"]) != intent["payload_sha256"]
            or intent["payload"]["operation_id"] != intent["operation_id"]
            or intent["start"].get("id") != intent["run_id"] or intent["start"].get("status") != "queued"
            or not typed_equal(intent["start"].get("selection"), intent["payload"].get("request"))):
        raise ValueError("The original HTTP queued admission identity changed.")
    if case in (*CORRECTED_CASES, *RECOVERY_CASES) and any(other != case and (
            row.get("operation_id") == intent["operation_id"] or row.get("run_id") == intent["run_id"])
            for other, row in value["intents"].items()):
        raise ValueError("A separately declared case must have a distinct original operation and Run.")
    request = DeterministicReadRequest.from_value(intent["payload"]["request"])
    for key in ("run_id", "operation_id", "request_id"):
        if type(intent[key]) is not str or str(UUID(intent[key])) != intent[key] or UUID(intent[key]).version != 4:
            raise ValueError("Use exact original canonical UUID identities.")
    body = intent["start"]
    schema = json.loads((Path(__file__).parents[1] / "ricky/schemas/company-api-v1.schema.json").read_text())
    Draft202012Validator({"$defs": schema["$defs"], "$ref": "#/$defs/CompanyRickyRunResponse"}, format_checker=FormatChecker()).validate(body)
    if (set(intent["payload"]) != {"company", "request", "operation_id"} or intent["payload"]["company"] != value["company"]
            or body["company"] != value["company"] or body["project"] is not None or body["scope_type"] != "Company"
            or body["cancel_requested"] is not False or any(body[key] is not None for key in ("result", "result_digest", "error", "completed_at"))
            or body["action"] != request.action or body["selection_digest"] != request.selection_digest()
            or not typed_equal(body["standing"], request.model_standing())):
        raise ValueError("The retained queued observation does not bind its exact immutable admission.")
    rows = [row for row in Journal(value["journal_directory"]).rows if row["key"] == "start-" + case]
    if (len(rows) != 1 or rows[0]["role"] != "author" or rows[0]["method"] != "cipher_aec.ricky.company_api.start_read"
            or not typed_equal(rows[0]["payload"], intent["payload"]) or rows[0]["payload_sha256"] != intent["payload_sha256"]):
        raise ValueError("The saved run lacks its exact original HTTP command origin.")
    matches = [attempt.get("envelope") for attempt in rows[0]["attempts"] if attempt.get("status") == 200
        and attempt.get("envelope", {}).get("request_id") == intent["request_id"]]
    if len(matches) != 1:
        raise ValueError("The actual saved HTTP response identity is unavailable.")
    envelope = matches[0]
    result = envelope.get("data", {})
    if (envelope.get("schema") != "cipher.api.v1" or envelope.get("meta", {}).get("request_id") != intent["request_id"]
            or not typed_equal({key: item for key, item in result.items() if key != "operation"}, body)
            or result.get("operation", {}).get("id") != intent["operation_id"]
            or result.get("operation", {}).get("status") != "succeeded"
            or type(result.get("operation", {}).get("replayed")) is not bool):
        raise ValueError("The run differs from its original canonical HTTP result/receipt identity.")
    return intent


def verify_read_value(inputs, case, result):
    """Exact authored expectations; no fresh calculation/authority substitute."""
    if type(result) is not dict:
        raise AssertionError("The fixed read returned no typed result.")
    if case in ("lookup", "queued-delivery", "interrupted-read-r12", "quarantine-r12"):
        valid = result["title"] == inputs["pursuit"]["title"] and result["record_digest"] == sha(inputs["pursuit"])
    elif case == "recompute":
        original = inputs["calculations"][0]
        valid = (result["revision_id"] == inputs["revisions"][0]["id"] and result["total"] == {"amount": "2.50", "currency": "USD"}
            and result["revision_digest"] == sha(inputs["revisions"][0]) and result["snapshot_id"] == original["id"]
            and result["input_digest"] == original["input_digest"] and result["output_digest"] == original["output_digest"]
            and result["current_working_revision"] is False)
    elif case == "compare":
        valid = (result["total_delta"] == "1.25" and result["currency"] == "USD"
            and result["changed_line_ids"] == [inputs["stable_line_id"]]
            and result["left_digest"] == sha(inputs["revisions"][0]) and result["right_digest"] == sha(inputs["revisions"][1]))
    elif case in ("convert", "convert-r9"):
        valid = (result["numerator"] == "200" and result["denominator"] == "1"
            and result["source_digest"] == sha(inputs["line_value"]) and result["target_unit_id"] == inputs["units"][1]["id"]
            and result["provenance"] == "authored-estimate-line" and result["independently_verified"] is False
            and result["eligible_for_new_use"] is False and result["model_supplied_quantity"] is False)
    else:
        raise ValueError("There is no fixed successful result expectation for this case.")
    if not valid:
        raise AssertionError("The exact stored/manual read result differs from its authored expectation.")


def require_projection_coverage(value, observations, known):
    if (set(known) != set(RICKY_TYPES) or known["Cipher Proposed Change"]
            or any(not known[table] for table in RICKY_TYPES if table != "Cipher Proposed Change")):
        raise ValueError("Use every literal DocType's actual Company IDs, with Proposed Changes structurally empty.")
    expected = {(row["user"], table) for row in value["users"].values() for table in RICKY_TYPES}
    if (len(observations) != 18 or {(row["user"], row["doctype"]) for row in observations} != expected
            or any(not typed_equal(row["known_company_ids"], known[row["doctype"]]) for row in observations)):
        raise ValueError("The supplied facts do not cover every declared actor/DocType and exact known Company ID set.")

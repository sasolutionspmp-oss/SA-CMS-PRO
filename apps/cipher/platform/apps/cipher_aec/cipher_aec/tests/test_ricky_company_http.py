"""Opt-in real-cookie Company deterministic reads; no fixture worker controls."""
import base64
from copy import deepcopy
from http.cookiejar import LWPCookieJar
import hashlib
import json
import os
from pathlib import Path
import time
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit
from urllib.request import build_opener, HTTPCookieProcessor, HTTPRedirectHandler, Request
from uuid import uuid4

from .ricky_company_acceptance_support import CASES, Journal, manifest, saved_intent, sha, timestamp, write_private, verify_read_value, typed_equal, load_private, declared_case, completed_read_cases

RICKY = "cipher_aec.ricky.company_api."
DOC = "cipher_aec.documents.company_api."
EST = "cipher_aec.estimating.company_api."
TAKEOFF = "cipher_aec.takeoff.company_api."
POSTS = frozenset({RICKY + "start_read", RICKY + "cancel_run", DOC + "upload_document",
    EST + "create_conversion", EST + "create_rate", EST + "create_estimate",
    EST + "calculate_revision", TAKEOFF + "create_set", TAKEOFF + "create_measurement",
    "cipher_aec.commercial.api.create_pursuit"})
GETS = frozenset({RICKY + "get_run", RICKY + "run_events", DOC + "get_citation",
    EST + "get_record", EST + "list_units", "cipher_aec.api.v1.session", "cipher_aec.api.company.operation", "cipher_aec.api.company.history"})


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        return None


def _opener(jar):
    return build_opener(HTTPCookieProcessor(jar), _NoRedirect())


class _HTTP:
    def __init__(self, private_manifest, base_url, host_header=None):
        self.path, self.value = Path(private_manifest), manifest(private_manifest)
        parsed = urlsplit(base_url)
        if (parsed.scheme not in ("http", "https") or not parsed.netloc or not parsed.hostname or parsed.username or parsed.password
                or any(ord(character) < 33 for character in base_url)
                or parsed.path not in ("", "/") or parsed.query or parsed.fragment):
            raise ValueError("Use root's explicit HTTP base origin without credentials/query.")
        parsed.port  # Reject malformed ports before any opener/request is built.
        self.origin, self.host = base_url.rstrip("/"), host_header
        if host_header is not None and (not isinstance(host_header, str) or any(c in host_header for c in "\r\n/")):
            raise ValueError("Use a literal root-qualified Host header.")
        self.work = Path(self.value["journal_directory"])
        self.journal = Journal(self.work)
        self.openapi = json.loads((Path(__file__).parents[1] / "api/openapi.json").read_text())

    def _wire(self, method, path, values=None, *, csrf=None, operation=None):
        self.last_wire_observation = None
        headers = {"Accept": "application/json"}
        if self.host: headers["Host"] = self.host
        if csrf: headers["X-Frappe-CSRF-Token"] = csrf
        if operation: headers["Idempotency-Key"] = operation
        data = None
        if method == "POST":
            data = json.dumps(values or {}, allow_nan=False).encode()
            headers["Content-Type"] = "application/json"
        elif values:
            path += "?" + urlencode(values)
        request = Request(self.origin + path, data=data, headers=headers, method=method)
        started = time.monotonic()
        try:
            response = self.opener.open(request, timeout=30)
        except HTTPError as response:
            with response:
                status, raw = response.code, response.read(2097153)
        else:
            with response:
                status, raw = response.status, response.read(2097153)
        observation = {"at": timestamp(), "method": method, "path": path, "operation_id": operation,
            "status": status, "observed_bytes": len(raw), "body_sha256": hashlib.sha256(raw).hexdigest(),
            "truncated": len(raw) > 2097152}
        self.last_wire_observation = observation
        record = self.work / "wire-observations.secret.json"
        observations = load_private(record) if record.exists() else []
        observations.append(observation)
        if 300 <= status < 400: observation["refusal"] = "redirect_refused_no_forward"
        elif observation["truncated"]: observation["refusal"] = "oversized_response_prefix_hash_only"
        else:
            try:
                value = json.loads(raw)
            except (ValueError, UnicodeError):
                observation["refusal"] = "malformed_json"
        write_private(record, observations)
        if "refusal" in observation:
            raise AssertionError("HTTP response refused; bounded private status/body hash is retained.")
        return status, value, time.monotonic() - started

    def _refusal_observation(self, reason):
        path = self.work / "refusal-observations.secret.json"
        values = load_private(path) if path.exists() else []
        values.append({"at": timestamp(), "refusal": reason, "response": getattr(self, "last_wire_observation", None)})
        write_private(path, values)

    def archive_cookie_context(self, reason):
        if not self.cookie_path.exists() or self.cookie_path.is_symlink() or self.cookie_path.stat().st_mode & 0o077:
            raise ValueError("Preserve an existing exact private cookie jar.")
        raw = self.cookie_path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        archive = self.work / (self.role + ".cookies." + digest + ".original.secret")
        if archive.exists():
            if archive.read_bytes() != raw or archive.stat().st_mode & 0o077:
                raise ValueError("The original private cookie archive changed.")
        else:
            descriptor = os.open(archive, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        self.value["stages"].setdefault("cookie_provenance", []).append({"role": self.role, "reason": reason,
            "path": str(archive), "sha256": digest, "original_path": str(self.cookie_path)})
        write_private(self.path, self.value)
        return digest

    def login(self, role="author", *, fresh=False):
        if role not in self.value["users"]:
            raise ValueError("Use a declared fixture identity.")
        self.role = role
        self.cookie_path = self.work / (role + ".cookies.secret")
        if fresh and self.cookie_path.exists():
            self.archive_cookie_context("before-explicit-fresh-login")
        self.jar = LWPCookieJar(str(self.cookie_path))
        if self.cookie_path.exists() and not fresh:
            if self.cookie_path.stat().st_mode & 0o077:
                raise ValueError("The real cookie context must remain mode0600.")
            self.jar.load(ignore_discard=True, ignore_expires=True)
        self.opener = _opener(self.jar)
        if not self.cookie_path.exists() or fresh:
            credentials = self.value["users"][role]
            status, _, _ = self._wire("POST", "/api/method/login", {"usr": credentials["user"], "pwd": credentials["password"]})
            if status != 200:
                raise AssertionError("Ordinary HTTP login failed; no synthetic session substitute is allowed.")
            temporary = self.cookie_path.with_name(self.cookie_path.name + "." + uuid4().hex + ".pending")
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            os.close(descriptor)
            self.jar.save(str(temporary), ignore_discard=True, ignore_expires=True)
            with temporary.open("rb") as stream: os.fsync(stream.fileno())
            os.replace(temporary, self.cookie_path)
            descriptor = os.open(self.work, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try: os.fsync(descriptor)
            finally: os.close(descriptor)
        status, payload, _ = self._wire("GET", "/api/method/cipher_aec.api.v1.session")
        envelope = payload.get("message", payload) if type(payload) is dict else {}
        session = envelope.get("data", {}) if type(envelope) is dict else {}
        owner = self.value["users"][role]
        if (status != 200 or type(session) is not dict or type(session.get("person")) is not dict
                or session.get("site_mode") != "synthetic" or session.get("user") != owner["user"]
                or session.get("person", {}).get("id") != owner["person"] or type(session.get("csrf_token")) is not str or not session["csrf_token"]):
            self._refusal_observation("invalid_authenticated_session_envelope")
            raise AssertionError("The actual cookie does not identify this exact synthetic User/Person.")
        self.csrf = session["csrf_token"]

    def call(self, method, values, *, key=None, expected=()):
        if method not in POSTS | GETS:
            raise ValueError("Only fixed ordinary fixture routes are supported.")
        verb = "POST" if method in POSTS else "GET"
        row = self.journal.prepare(key, self.role, method, values) if verb == "POST" else None
        sent = row["payload"] if row else values
        from jsonschema import Draft202012Validator, FormatChecker
        operation = self.openapi["paths"]["/api/method/" + method][verb.lower()]
        if verb == "POST":
            schema = operation["requestBody"]["content"]["application/json"]["schema"]
            Draft202012Validator({"components": self.openapi["components"], **schema}, format_checker=FormatChecker()).validate(sent)
        # Prepared command is fsynced before this one send. Errors/unknown
        # outcomes stay in the journal; no implicit retry or replacement UUID.
        try:
            status, payload, seconds = self._wire(verb, "/api/method/" + method, sent,
                csrf=self.csrf, operation=row["operation_id"] if row else None)
        except BaseException as error:
            if row: self.journal.uncertain(row, error, getattr(self, "last_wire_observation", None))
            raise
        envelope = payload.get("message") if type(payload) is dict else None
        if (type(envelope) is not dict or envelope.get("schema") != "cipher.api.v1" or type(envelope.get("request_id")) is not str
                or type(envelope.get("meta")) is not dict
                or envelope.get("meta", {}).get("request_id") != envelope.get("request_id")
                or envelope.get("meta", {}).get("api_version") != "v1"):
            self._refusal_observation("malformed_canonical_envelope")
            if row:
                self.journal.refusal(row, status, "malformed_canonical_envelope", getattr(self, "last_wire_observation", None))
            raise AssertionError("The actual route returned no canonical envelope.")
        response = operation["responses"].get(str(status))
        try:
            if response is None:
                raise ValueError("Undeclared response status")
            schema = response["content"]["application/json"]["schema"]
            Draft202012Validator({"components": self.openapi["components"], **schema}, format_checker=FormatChecker()).validate(payload)
        except Exception:
            self._refusal_observation("response_schema_or_status_refused")
            if row: self.journal.refusal(row, status, "response_schema_or_status_refused", getattr(self, "last_wire_observation", None))
            raise AssertionError("Response shape/status refused; bounded private observation and original intent are retained.") from None
        if row: self.journal.response(row, status=status, envelope=envelope)
        observations = self.value["stages"].setdefault("http_calls", [])
        observations.append({"method": method, "role": self.role, "status": status, "request_id": envelope["request_id"], "seconds": seconds})
        write_private(self.path, self.value)
        if expected:
            code = envelope.get("error", {}).get("code")
            if code not in expected or status != {"not_found": 404, "capability_denied": 403, "session_revoked": 403}.get(code):
                raise AssertionError("The declared current-rights denial was not observed.")
            return envelope
        if status >= 400:
            raise AssertionError("An ordinary fixture request failed; its original HTTP journal is retained.")
        return envelope

    def command(self, key, method, fields):
        return self.call(method, {"company": self.value["company"], **fields}, key=key)["data"]


def _input_unit_references(rpc):
    """Require root's separate native Administrator-service unit prerequisite."""
    from jsonschema import Draft202012Validator, FormatChecker, ValidationError
    native = rpc.value["native"]
    names, recorded = native.get("uoms"), native.get("qualified_units")
    if (type(names) is not list or len(names) != 2 or any(type(name) is not str for name in names) or len(set(names)) != 2
            or type(recorded) is not list or len(recorded) != 2):
        raise RuntimeError("Record exactly two operator-qualified fixture UOM references before authored HTTP commands.")
    validator = Draft202012Validator({"components": rpc.openapi["components"], "$ref": "#/components/schemas/CompanyEstUnitRecord"}, format_checker=FormatChecker())
    for name, unit in zip(names, recorded):
        try:
            validator.validate(unit)
        except ValidationError:
            raise RuntimeError("The recorded operator-qualified unit does not match the published canonical unit contract.") from None
        if (not typed_equal(unit["target"], {"doctype": "UOM", "name": name}) or type(unit["revision"]) is not int
                or unit["fields"]["dimension"] != "length" or type(unit["fields"]["precision"]) is not int or unit["fields"]["precision"] != 6):
            raise RuntimeError("The operator-qualified units do not bind the exact two fixture length UOMs.")
    if len({unit["id"] for unit in recorded}) != 2:
        raise RuntimeError("The two original fixture UOMs require distinct qualified unit IDs.")
    return recorded


def _current_input_units(rpc, recorded):
    """Author reads current units; operator DTOs alone never authorize inputs."""
    response = rpc.call(EST + "list_units", {"company": rpc.value["company"]})
    current = response.get("data", {}).get("items")
    if type(current) is not list:
        raise RuntimeError("The ordinary author unit read returned no current unit inventory.")
    selected = []
    for original in recorded:
        matches = [unit for unit in current if type(unit) is dict and unit.get("id") == original["id"]]
        if len(matches) != 1 or not typed_equal(matches[0], original):
            raise RuntimeError("A recorded operator-qualified fixture unit is missing, duplicated or changed in the current author read.")
        selected.append(matches[0])
    return selected


def run_company_http_inputs(private_manifest, base_url, host_header=None):
    """Author raw/text/manual inputs after separate native unit qualification."""
    rpc = _HTTP(private_manifest, base_url, host_header)
    if not rpc.value["preservation"].get("setup_old_rows_unchanged"):
        raise RuntimeError("Strict setup preservation/attribution must be reviewed first.")
    if rpc.value["inputs"].get("ready"):
        raise RuntimeError("Inputs already exist; resume their original journal instead of creating another fixture.")
    recorded_units = _input_unit_references(rpc)
    rpc.login()
    units = _current_input_units(rpc, recorded_units)
    value, command = rpc.value, rpc.command
    content = b"Synthetic Company Ricky authored rate 1.25 USD per metre. Manual quantity 2 metres. Exactly 1 metre equals 100 centimetres. No calibrated geometry or model claim.\n"
    uploaded = command("input-document", DOC + "upload_document", {"title": "Ricky authored manual source", "filename": "ricky-authored.txt",
        "content_base64": base64.b64encode(content).decode(), "byte_length": len(content), "sha256": hashlib.sha256(content).hexdigest()})
    citation = rpc.call(DOC + "get_citation", {"company": value["company"], "revision_id": uploaded["revision"]["id"], "page": 1})["data"]
    sources = [{key: citation[key] for key in ("revision_id", "page", "excerpt_sha256", "source_sha256")}]
    conversion = command("input-conversion", EST + "create_conversion", {"definition": {"from_unit_id": units[0]["id"], "to_unit_id": units[1]["id"],
        "dimension": "length", "numerator": "100", "denominator": "1", "source": "Authored SI metre/centimetre relation in fixture source"},
        "source_citations": sources, "permission_basis": "Fixture author owns this synthetic text"})["conversion"]
    pursuit = command("input-pursuit", "cipher_aec.commercial.api.create_pursuit", {"party_type": "Customer", "party_id": value["native"]["customer"],
        "fields": {"title": "Ricky manual-source Pursuit", "sector": "Synthetic qualification"}})["pursuit"]
    rate = command("input-rate", EST + "create_rate", {"rate": {"title": "Authored metre rate", "cost_type": "material", "unit_id": units[0]["id"],
        "rate_amount": "1.25", "rate_precision": 6, "currency": "USD", "quote_reference": "Explicit synthetic authored rate", "quote_date": value["created_at"][:10],
        "expiry_date": None, "geography": "Synthetic", "inclusions": "Authored material", "exclusions": "Tax and freight", "freight_tax_assumptions": "None included",
        "permission_basis": "Fixture author owns this synthetic source", "source_citations": sources}})["rate_source"]
    estimate = command("input-estimate", EST + "create_estimate", {"title": "Ricky manual estimate", "currency": "USD", "pricing_date": value["created_at"][:10], "pursuit_id": pursuit["id"]})["estimate"]
    # Stable IDs are persisted before any calculation; retries keep these IDs.
    line_path = rpc.work / "line-identity.secret.json"
    if line_path.exists():
        line_id = json.loads(line_path.read_text())["line_id"]
    else:
        line_id = str(uuid4()); write_private(line_path, {"line_id": line_id})
    revisions, calculations, line_record = [], [], None
    for index, amount in enumerate(("2.000000", "3.000000")):
        calculated = command("input-revision-" + str(index), EST + "calculate_revision", {"estimate_id": estimate["id"],
            "expected_revision": revisions[-1]["id"] if revisions else None,
            "lines": [{"line_id": line_id, "description": "Authored manual length", "quantity": {"amount": amount, "unit_id": units[0]["id"], "precision": 6},
                "cost_code": "RICKY-01", "notes": "Manual quantity; no geometric claim", "alternate": "", "included": True,
                "rate_source_id": rate["id"], "material_factor": "1", "waste_fraction": "0"}], "adjustments": [], "conversion_ids": [conversion["id"]],
            "basis_description": "Explicit authored/manual fixture", "basis_citations": sources})
        revisions.append(calculated["revision"])
        calculations.append(calculated["calculation"])
        if index == 0:
            line_record = calculated["revision"]["line_record_ids"][0]
    line_value = rpc.call(EST + "get_record", {"company": value["company"], "kind": "line", "record_id": line_record})["data"]
    takeoff_set = command("input-takeoff-set", TAKEOFF + "create_set", {"title": "Ricky explicit manual selection", "discipline": "Synthetic",
        "drawing_package": "Raw authored text", "basis": "Manual quantities only; no drawing calibration"})["takeoff_set"]
    measurement = command("input-manual-measurement", TAKEOFF + "create_measurement", {"takeoff_set": takeoff_set["id"],
        "source": {"revision_id": citation["revision_id"], "source_sha256": citation["source_sha256"], "page": 1}, "conversion_ids": [conversion["id"]],
        "definition": {"method": "manual", "kind": "length", "locator": "Authored source page 1", "reason": "Explicit synthetic manual quantity",
            "result_unit_id": units[0]["id"], "result_precision": 6, "tolerance": "0.000001", "waste_fraction": "0",
            "formula_version": "cipher.takeoff.planar.v1", "manual_quantity": {"amount": "2.000000", "unit_id": units[0]["id"], "precision": 6}}})["measurement"]
    value["inputs"] = {"ready": True, "qualification": "raw/text/manual only; no calibrated geometry/accepted baseline/model",
        "unit_qualification_basis": "Separate native Administrator-service prerequisite; exact current units read by the ordinary author over HTTP.",
        "document": uploaded["document"], "citation": citation, "units": units, "conversion": conversion, "pursuit": pursuit,
        "rate": rate, "estimate": estimate, "revisions": revisions, "calculations": calculations,
        "line_record": line_record, "line_value": line_value, "stable_line_id": line_id, "measurement": measurement}
    write_private(private_manifest, value)
    return {"status": "inputs_authored_over_HTTP", "fixture_id": value["fixture_id"], "qualification": value["inputs"]["qualification"]}


def start_company_http_case(private_manifest, case, base_url, host_header=None):
    """One authentic production start; production active-per-person quota stays."""
    if case not in CASES:
        raise ValueError("Use one fixed declared Company case.")
    rpc = _HTTP(private_manifest, base_url, host_header)
    original_case = declared_case(rpc.value, case)
    rpc.login()
    inputs = rpc.value["inputs"]
    if not inputs.get("ready"):
        raise RuntimeError("Author the exact Company inputs first.")
    from cipher_aec.ricky.company_contracts import DeterministicReadRequest
    action, arguments = "aec.pursuit.lookup", {}
    if case == "recompute": action, arguments = "aec.estimate.recompute", {"revision_id": inputs["revisions"][0]["id"]}
    if case == "compare": action, arguments = "aec.estimate.compare", {"left_revision_id": inputs["revisions"][0]["id"], "right_revision_id": inputs["revisions"][1]["id"]}
    if original_case == "convert": action, arguments = "aec.quantity.convert", {"source_kind": "estimate-line", "source_id": inputs["line_record"], "target_unit_id": inputs["units"][1]["id"]}
    citation = inputs["citation"]
    request = {"schema": "cipher.ricky.company.read-request.v1", "pursuit_id": inputs["pursuit"]["id"], "action": action, "arguments": arguments,
        "sources": [{"citation_id": citation["id"], **{key: citation[key] for key in ("revision_id", "page", "excerpt_sha256", "source_sha256")}}],
        "measurement_ids": [inputs["measurement"]["id"]]}
    selected = DeterministicReadRequest.from_value(request)
    payload = {"company": rpc.value["company"], "request": request}
    response = rpc.call(RICKY + "start_read", payload, key="start-" + case)
    row = next(row for row in rpc.journal.rows if row["key"] == "start-" + case)
    original = {key: item for key, item in response["data"].items() if key != "operation"}
    if (original["status"] != "queued" or original["result"] is not None or original["company"] != rpc.value["company"]
            or original["selection_digest"] != selected.selection_digest() or original["action"] != action):
        raise AssertionError("A successful start must preserve its original queued receipt DTO.")
    captured = {"case": case, "operation_id": row["operation_id"], "payload": deepcopy(row["payload"]),
        "payload_sha256": row["payload_sha256"], "start": original, "run_id": original["id"], "request_id": response["request_id"]}
    if case in rpc.value["intents"]:
        prior = saved_intent(rpc.value, case)
        if not typed_equal({key: item for key, item in prior.items() if key != "request_id"}, {key: item for key, item in captured.items() if key != "request_id"}):
            raise AssertionError("A retry cannot replace its original admission identity or queued observation.")
    else:
        rpc.value["intents"][case] = captured
    saved_intent(rpc.value, case)
    write_private(private_manifest, rpc.value)
    return {"case": case, "run_id": original["id"], "status": "queued_HTTP_receipt_recorded", "operation_id": row["operation_id"]}


def observe_company_http_case(private_manifest, case, base_url, host_header=None):
    rpc = _HTTP(private_manifest, base_url, host_header)
    intent = saved_intent(rpc.value, case)
    rpc.login()
    values = {"company": rpc.value["company"], "run_id": intent["run_id"]}
    result = rpc.call(RICKY + "get_run", values)["data"]
    predecessor = next((row for row in rpc.value["stages"].get("corrected_cases", {}).values()
        if row["predecessor_case"] == case), None)
    if predecessor is not None:
        if result["status"] != predecessor["predecessor_status"] or result["result"] is not None:
            raise AssertionError("The original terminal predecessor cannot become a successful corrected case.")
    elif declared_case(rpc.value, case) in ("lookup", "recompute", "compare", "convert"):
        if result["status"] != "succeeded":
            raise AssertionError("The declared fixed read did not complete.")
        verify_read_value(rpc.value["inputs"], case, result["result"])
    rpc.call(RICKY + "run_events", values)
    replay = rpc.call(RICKY + "start_read", {key: item for key, item in intent["payload"].items() if key != "operation_id"}, key="start-" + case)["data"]
    if replay["operation"]["replayed"] is not True or not typed_equal({key: item for key, item in replay.items() if key != "operation"}, intent["start"]):
        raise AssertionError("The original exact-UUID queued receipt changed after later work.")
    if not typed_equal(result["standing"], {"mode": "deterministic-read-v1", "model_invoked": False, "live_model_qualified": False}):
        raise AssertionError("A deterministic result claimed model standing.")
    operation_read = rpc.call("cipher_aec.api.company.operation", {"company": rpc.value["company"], "operation_id": intent["operation_id"]})["data"]
    rpc.value["stages"].setdefault("receipt_http_observations", {})["start-" + case] = {"replay": replay, "operation_read": operation_read}
    write_private(private_manifest, rpc.value)
    for role in ("alias", "outsider"):
        rpc.login(role)
        rpc.call(RICKY + "get_run", values, expected={"not_found", "capability_denied"})
    return {"status": "HTTP_read_replay_owner_denials_passed", "case": case, "run_id": intent["run_id"], "standing": result["status"]}


def stop_company_http_case(private_manifest, case, base_url, host_header=None):
    if case not in ("claim-race", "claim-race-r9", "fenced-stop", "source-revoked-stop", "capability-revoked", "expired-original"):
        raise ValueError("Use a declared stop case.")
    rpc = _HTTP(private_manifest, base_url, host_header); rpc.login()
    intent = saved_intent(rpc.value, case)
    result = rpc.command("stop-" + case, RICKY + "cancel_run", {"run_id": intent["run_id"]})
    expected = {"id", "company", "scope_type", "project", "request_kind", "status", "cancel_requested", "operation"}
    if set(result) != expected or result["status"] not in ("cancelled", "failed", "succeeded"):
        raise AssertionError("Stop returned source material or a malformed standing.")
    if result["operation"]["replayed"]:
        row = next(row for row in rpc.journal.rows if row["key"] == "stop-" + case)
        operation_read = rpc.call("cipher_aec.api.company.operation", {"company": rpc.value["company"], "operation_id": row["operation_id"]})["data"]
        rpc.value["stages"].setdefault("receipt_http_observations", {})["stop-" + case] = {"replay": result, "operation_read": operation_read}
        write_private(private_manifest, rpc.value)
    return {"status": "source_free_HTTP_stop", "case": case, "run_id": result["id"]}


def expire_original_http_session(private_manifest, base_url, host_header=None):
    """Ordinary logout, then explicit fresh cookie; no Session table edits."""
    rpc = _HTTP(private_manifest, base_url, host_header); rpc.login()
    saved_intent(rpc.value, "expired-original")
    successful_cases = completed_read_cases(rpc.value)
    for case in successful_cases:
        saved_intent(rpc.value, case)
        if case not in rpc.value["inputs"].get("recorded_results", {}):
            raise RuntimeError("Complete each declared successful read before expiring its original session.")
    binding = rpc.value["stages"].get("original_run_bindings", {}).get("expired-original")
    actual = [cookie.value for cookie in rpc.jar if cookie.name == "sid"]
    if (binding is None or len(actual) != 1
            or hashlib.sha256(actual[0].encode()).hexdigest() != binding["original_session_reference"]):
        raise AssertionError("The live cookie is not the actual persisted original execution session.")
    rpc.archive_cookie_context("before-deliberate-original-session-logout")
    status, _, _ = rpc._wire("POST", "/api/method/logout", {}, csrf=rpc.csrf)
    if status != 200:
        raise AssertionError("The actual original session logout failed.")
    rpc.login(fresh=True)
    renewed = [cookie.value for cookie in rpc.jar if cookie.name == "sid"]
    if len(renewed) != 1 or hashlib.sha256(renewed[0].encode()).hexdigest() == binding["original_session_reference"]:
        raise AssertionError("The explicit fresh login did not create a distinct authenticated session.")
    intent = saved_intent(rpc.value, "expired-original")
    rpc.call(RICKY + "get_run", {"company": rpc.value["company"], "run_id": intent["run_id"]}, expected={"session_revoked"})
    for case in successful_cases:
        original = saved_intent(rpc.value, case)
        result = rpc.call(RICKY + "get_run", {"company": rpc.value["company"], "run_id": original["run_id"]})["data"]
        if result["status"] != "succeeded" or not typed_equal(result["result"], rpc.value["inputs"]["recorded_results"][case]):
            raise AssertionError("Fresh exact-owner access rewrote an original completed result.")
    for declaration in rpc.value["stages"].get("corrected_cases", {}).values():
        original = saved_intent(rpc.value, declaration["predecessor_case"])
        result = rpc.call(RICKY + "get_run", {"company": rpc.value["company"], "run_id": original["run_id"]})["data"]
        if result["status"] != declaration["predecessor_status"] or result["result"] is not None:
            raise AssertionError("A separate corrected case must preserve its original terminal predecessor.")
    return {"status": "ordinary_logout_new_cookie_completed_results_retained", "active_observation_denied": True}


def run_company_queued_delivery_acceptance(private_manifest, base_url, host_header=None):
    """Observe an authentic HTTP start after ROOT separately releases RQ."""
    rpc = _HTTP(private_manifest, base_url, host_header); rpc.login()
    intent = saved_intent(rpc.value, "queued-delivery")
    for attempt in range(10):
        result = rpc.call(RICKY + "get_run", {"company": rpc.value["company"], "run_id": intent["run_id"]})["data"]
        if result["status"] == "succeeded":
            verify_read_value(rpc.value["inputs"], "queued-delivery", result["result"])
            rpc.value["stages"]["queued-delivery"] = {"status": "result_observed", "mode": "RQ_delivery_requires_root_queue_job_evidence",
                "run_id": intent["run_id"], "result_digest": result["result_digest"]}
            write_private(private_manifest, rpc.value)
            return deepcopy(rpc.value["stages"]["queued-delivery"])
        if result["status"] in ("failed", "cancelled"):
            raise AssertionError("The isolated queued case ended without a deterministic result.")
        if attempt != 9: time.sleep(1)
    raise AssertionError("No result within the fixed observation budget; queue delivery remains unqualified.")

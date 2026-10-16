"""Opt-in prospective command-history fixture; root alone owns actual RQ work.

Uses existing qualified identities/inputs in a separate private reference journal.
It never creates a login, edits original fixture files, starts a worker or changes
configuration. Native/runtime qualification remains separate from host tests.
"""
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path

from .ricky_company_acceptance_support import (Journal, ROLES, load_private, manifest, saved_intent,
    sha, timestamp, typed_equal, verify_read_value, write_private)
from . import test_ricky_company_native as native
from . import test_ricky_company_http as http
from . import ricky_company_recovery_acceptance as recovery
from .ricky_company_central_acceptance import verify_shared_receipts

KEY = "history_r13"
SCHEMA = "cipher.fixture.ricky.company.command-history.v1"
HISTORY = "cipher_aec.api.company.history"
EVENT_FIELDS = "name,scope_type,company,project,actor_person,event,subject_type,subject_id,operation_id,details_json,previous_hash,event_hash,event_payload"


def _private_bytes(path):
    path = Path(path)
    if not path.is_file() or path.is_symlink() or path.stat().st_mode & 0o077:
        raise ValueError("Use exact existing private fixture bytes.")
    return path.read_bytes()


def _digest_bytes(path):return hashlib.sha256(_private_bytes(path)).hexdigest()


def _copy_private(source, destination):
    raw = _private_bytes(source)
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(raw);stream.flush();os.fsync(stream.fileno())


def _origin_unchanged(value):
    proof = value["stages"][KEY]
    if set(proof["cookie_sha256"]) != set(ROLES):
        raise ValueError("Retain all three exact original cookie references; no new login is permitted.")
    original = Path(proof["original_directory"])
    for relative, expected in proof["original_files"].items():
        if _digest_bytes(original / relative) != expected:
            raise AssertionError("An original fixture/journal/cookie/evidence file changed.")
    for role, expected in proof["cookie_sha256"].items():
        if _digest_bytes(Path(value["journal_directory"]) / (role + ".cookies.secret")) != expected:
            raise AssertionError("Use the exact copied cookie context without replacement/login.")


def _value(path):
    value = native._fixture(path)
    proof = value["stages"].get(KEY, {})
    if proof.get("schema") != SCHEMA or proof.get("case") != "company-command-history-r13":
        raise ValueError("Use the separate declared R13 reference journal.")
    _origin_unchanged(value)
    baseline = Path(value["journal_directory"]) / "history-r13-baseline.secret.json"
    if _digest_bytes(baseline) != proof["baseline_sha256"]:
        raise AssertionError("The original R13 preservation baseline changed.")
    return value


def _record(path, status=None, **fields):
    value = manifest(path);proof = value["stages"][KEY]
    if status is not None:proof["status"] = status
    proof.update(deepcopy(fields));proof.setdefault("observations", []).append({"at":timestamp(),"status":proof["status"],"fields":sorted(fields)})
    write_private(path,value)
    return value


@contextmanager
def _phase(path, expected, entered):
    value = _value(path)
    if value["stages"][KEY]["status"] != expected:
        raise RuntimeError("Each R13 phase is one-shot; reconcile retained evidence, never reset it.")
    _record(path,entered)
    try:yield value
    except Exception as error:
        _record(path,"failed",error=native._claim_failure(error))
        raise


class _HistoryHTTP(http._HTTP):
    def login(self, role="author", *, fresh=False):
        if fresh or role not in ROLES:raise ValueError("R13 uses copied original cookies only; no new login.")
        _private_bytes(self.work / (role + ".cookies.secret"))
        _origin_unchanged(self.value)
        return super().login(role, fresh=False)

    def call(self, method, values, **kwargs):
        if method not in {HISTORY,http.RICKY+"start_read",http.RICKY+"cancel_run",http.RICKY+"get_run",
                "cipher_aec.api.company.operation"}:
            raise ValueError("The R13 fixture has only history/read/start/Stop/receipt routes.")
        return super().call(method, values, **kwargs)


def _events(run_id):
    import frappe
    return [dict(row) for row in frappe.db.sql("SELECT " + EVENT_FIELDS + " FROM `tabCipher History Event` "
        "WHERE subject_type='Cipher Ricky Run' AND subject_id=%s ORDER BY creation,name",(run_id,),as_dict=True)]


def _event(value, row, kind, previous):
    from cipher_aec.api.contracts import canonical_json
    intent = saved_intent(value,"lookup")
    journal, _ = native._receipt(value,"lookup",kind)
    details = {"action":"aec.pursuit.lookup","status":"queued"} if kind == "start" else {"status":"succeeded","cancel_requested":False}
    body = {"scope_type":"Company","actor":value["users"]["author"]["person"],"company":value["company"],"project":None,
        "event":"ricky.company.read." + kind + ".accepted","subject_type":"Cipher Ricky Run","subject_id":intent["run_id"],
        "operation_id":journal["operation_id"],"details":details,"previous_hash":previous}
    if (row["event_payload"] != canonical_json(body) or row["event_hash"] != sha(body)
            or row["details_json"] != canonical_json(details)
            or any(not typed_equal(row[column],body[field]) for column,field in (("scope_type","scope_type"),("company","company"),
                ("project","project"),("actor_person","actor"),("event","event"),("subject_type","subject_type"),
                ("subject_id","subject_id"),("operation_id","operation_id"),("previous_hash","previous_hash")))):
        raise AssertionError("The canonical command event attribution, narrow metadata or Company chain changed.")
    return row


def _baseline(value):return load_private(Path(value["journal_directory"]) / "history-r13-baseline.secret.json")


def _preserved(value):
    import frappe
    _origin_unchanged(value)
    baseline = _baseline(value);current = native._inventory()
    original_business = load_private(Path(value["journal_directory"]) / "preservation-before.secret.json")
    if native._old_row_changes(original_business,current) or native._old_row_changes(baseline["old_command_rows"],current):
        raise AssertionError("An older business, Project/Company orchestration, history or receipt row changed.")
    if not typed_equal({"quarantine":recovery._config(),"pause_scheduler":frappe.conf.get("pause_scheduler")},baseline["config"]):
        raise AssertionError("The original configuration changed.")


def prepare_company_history_fixture(original_manifest, private_directory):
    """No identities/effects allocated; exact qualified references/cookies copied."""
    import frappe
    from cipher_aec.governance.context import require_effects_enabled
    original = native._fixture(original_manifest);require_effects_enabled();recovery._only_active()
    origin = Path(original["journal_directory"]).resolve();directory = Path(private_directory).resolve()
    base = Path(frappe.get_site_path("private","cipher-fixtures")).resolve()
    if (not directory.is_relative_to(base) or directory.is_relative_to(origin) or origin.is_relative_to(directory)
            or directory.exists()):
        raise ValueError("Use a new separate private R13 directory beside the original fixture.")
    source = saved_intent(original,"lookup")
    if not original["inputs"].get("ready") or source["payload"]["request"]["action"] != "aec.pursuit.lookup":
        raise ValueError("Reuse the original qualified fixed lookup inputs before creating a reference journal.")
    files = {str(path.relative_to(origin)):_digest_bytes(path) for path in origin.rglob("*") if path.is_file()}
    for role in ROLES:_private_bytes(origin / (role + ".cookies.secret"))
    original_before = origin / "preservation-before.secret.json";_private_bytes(original_before)
    inventory = native._inventory()
    heads = frappe.db.sql("SELECT event_hash FROM `tabCipher History Event` WHERE scope_type='Company' AND company=%s "
        "AND (project IS NULL OR project='') ORDER BY creation DESC,name DESC LIMIT 1",(original["company"],),as_dict=True)
    baseline = {"old_command_rows":{name:inventory[name] for name in (*native.RICKY_TABLES,"Cipher History Event","Cipher Command Receipt")},
        "head":heads[0].event_hash if heads else "", "config":{"quarantine":recovery._config(),"pause_scheduler":frappe.conf.get("pause_scheduler")}}
    directory.mkdir(mode=0o700)
    for name in ("preservation-before.secret.json", *(role + ".cookies.secret" for role in ROLES)):
        _copy_private(origin/name,directory/name)
    before_path = directory/"history-r13-baseline.secret.json";write_private(before_path,baseline)
    value = deepcopy(original);value.update(journal_directory=str(directory),intents={},shared_receipt_observations=[])
    for row in value["users"].values():row["password"] = "DISABLED_R13_NO_LOGIN"
    value["stages"] = {"original_duty_states":deepcopy(original["stages"]["original_duty_states"]),KEY:{"schema":SCHEMA,
        "case":"company-command-history-r13","status":"prepared","original_directory":str(origin),"original_files":files,
        "cookie_sha256":{role:files[role+".cookies.secret"] for role in ROLES},"baseline_sha256":_digest_bytes(before_path),
        "request":deepcopy(source["payload"]["request"]),"original_operations":[row["operation_id"] for row in Journal(origin).rows]}}
    path = directory/"fixture.secret.json";write_private(path,value);manifest(path);frappe.db.rollback()
    return {"private_manifest":str(path),"status":"prepared","standing":"Existing qualified references; no new identity or login."}


def _visible_native(value, role):
    import frappe
    from cipher_aec.api.errors import DomainError
    from cipher_aec.governance.context import current_actor, require_company
    from cipher_aec.governance.history_access import readable
    previous = frappe.session.user
    try:
        frappe.set_user(value["users"][role]["user"]);actor = current_actor()
        try:require_company(value["company"],actor=actor)
        except DomainError as error:
            if error.status not in (401,403,404):raise
            return {"denied":error.code}
        rows = frappe.db.sql("SELECT name,creation FROM `tabCipher History Event` WHERE scope_type='Company' AND company=%s "
            "AND (project IS NULL OR project='') ORDER BY creation DESC,name DESC",(value["company"],),as_dict=True)
        if len(rows)>10000:raise RuntimeError("Keep this explicit history fixture bounded.")
        return {"ids":[row.name for row in rows if readable(frappe.get_doc("Cipher History Event",row.name),actor,value["company"],None)],
            "creation":{row.name:str(row.creation) for row in rows}}
    finally:frappe.set_user(previous);frappe.db.rollback()


def _cursor_last(value, role, cursor):
    import frappe
    from cipher_aec.api.paging import decode_cursor, signing_secret
    from cipher_aec.governance.context import current_actor, company_authority_fingerprint
    previous = frappe.session.user
    try:
        frappe.set_user(value["users"][role]["user"]);actor = current_actor()
        scope = {"scope_type":"Company","company":value["company"],"user":actor.user,"person":actor.person_id,
            "collection":"company_history","authority":company_authority_fingerprint(actor,value["company"])}
        return decode_cursor(cursor,secret=signing_secret(),scope=scope)
    finally:frappe.set_user(previous);frappe.db.rollback()


def _visibility(path, base_url, host_header):
    value = _value(path);observed = {}
    for role in ROLES:
        expected = _visible_native(value,role);rpc = _HistoryHTTP(path,base_url,host_header);rpc.login(role)
        fields = {"company":value["company"],"limit":200,"count_mode":"exact"}
        if "denied" in expected:
            denied = rpc.call(HISTORY,fields,expected={expected["denied"]})
            observed[role] = {"denied":denied["error"]["code"]};continue
        ids = [];cursor_last_ids = [];cursor = None
        for _ in range(51):
            result = rpc.call(HISTORY,{**fields,**({"cursor":cursor} if cursor else {})})["data"]
            if result["total"] != len(expected["ids"]):raise AssertionError("History totals must count only currently authorized subjects.")
            ids.extend(row["id"] for row in result["items"]);cursor = result["next_cursor"]
            if not cursor:break
            if not result["items"]:raise AssertionError("A cursor cannot derive from hidden rows.")
            last = result["items"][-1]["id"];cursor_last_ids.append(last)
            if _cursor_last(value,role,cursor) != [expected["creation"][last],last]:raise AssertionError("History cursor did not bind the last visible native row.")
        else:raise RuntimeError("The bounded Company history scan did not finish.")
        if ids != expected["ids"]:raise AssertionError("History items/order differ from actual current original-user/source/native authorization.")
        observed[role] = {"ids":ids,"total":len(ids),"cursor_last_ids":cursor_last_ids}
    return observed


def start_company_history_case(private_manifest, base_url, host_header=None):
    """One normal authenticated Start, then fresh native attribution readback."""
    import frappe
    with _phase(private_manifest,"prepared","start_entered") as value:
        recovery._only_active();before_visibility = _visibility(private_manifest,base_url,host_header)
        rpc = _HistoryHTTP(private_manifest,base_url,host_header);rpc.login()
        response = rpc.call(http.RICKY+"start_read",{"company":value["company"],"request":value["stages"][KEY]["request"]},key="start-lookup")
        journal = rpc.journal.rows[0];body = {key:item for key,item in response["data"].items() if key!="operation"}
        if journal["operation_id"] in value["stages"][KEY]["original_operations"] or body["status"]!="queued" or response["data"]["operation"]["replayed"]:
            raise AssertionError("Retain a new first non-replayed queued admission in the separate R13 journal.")
        rpc.value["intents"]["lookup"] = {"case":"lookup","operation_id":journal["operation_id"],"payload":deepcopy(journal["payload"]),
            "payload_sha256":journal["payload_sha256"],"start":body,"run_id":body["id"],"request_id":response["request_id"]}
        saved_intent(rpc.value,"lookup");write_private(private_manifest,rpc.value);frappe.db.rollback()
        current = _value(private_manifest);run = native._run(current,"lookup");recovery._only_active(run["id"])
        events = _events(run["id"])
        if len(events)!=1:raise AssertionError("New Start must append exactly one prospective command event.")
        _event(current,events[0],"start",_baseline(current)["head"])
        native.capture_company_receipt_before(private_manifest,"lookup")
        _preserved(current)
        _record(private_manifest,"admitted",before_visibility=before_visibility,start_event=events[0],
            original_binding={key:run[key] for key in ("id","user","person","company","authority","request","original_session_reference")})
        frappe.db.rollback()
        return {"status":"admitted","run_id":run["id"],"root_next":"Ordinary isolated RQ burst; preserve actual queue/job/worker evidence."}


def verify_company_history_execution(private_manifest):
    """Native readback only; actual RQ delivery attestation remains root-owned."""
    import frappe
    from cipher_aec.ricky.company_service import build_service
    with _phase(private_manifest,"admitted","execution_readback") as value:
        run = native._run(value,"lookup");proof = value["stages"][KEY]
        if run["status"]!="succeeded" or run["tool_calls"]!=1 or run["generations"]!=0 or run["proposal_ids"]:
            raise AssertionError("Ordinary deterministic execution must complete with exactly one read and no model/proposal.")
        if not typed_equal({key:run[key] for key in proof["original_binding"]},proof["original_binding"]):raise AssertionError("The original actor/session/selection changed.")
        verify_read_value(value["inputs"],"lookup",run["result"])
        service = build_service(worker=True);service._result_linkage(run)
        children = recovery._payloads(run["id"],include_run=False)
        if len(children["step"])!=1 or len(children["invocation"])!=1 or not typed_equal(_events(run["id"]),[proof["start_event"]]):
            raise AssertionError("Worker execution changed command history or duplicated an invocation.")
        _preserved(value);recovery._only_active()
        _record(private_manifest,"executed",terminal_run=run,terminal_payloads=recovery._payloads(run["id"]),
            qualification="Native succeeded readback; root separately records actual ordinary RQ job/worker proof.")
        frappe.db.rollback();return {"status":"executed","run_id":run["id"],"worker_history_events":0}


def _cursor_alias_refusal(path, base_url, host_header):
    from jsonschema import Draft202012Validator, FormatChecker
    rpc = _HistoryHTTP(path,base_url,host_header);rpc.login()
    fields = {"company":rpc.value["company"],"limit":1,"count_mode":"exact"}
    page = rpc.call(HISTORY,fields)["data"];cursor = page["next_cursor"]
    if not cursor:raise AssertionError("Two visible command facts must supply an owner paging cursor.")
    expected = _visible_native(rpc.value,"author")
    if (not page["items"] or page["items"][-1]["id"] != expected["ids"][0]
            or page["total"] != len(expected["ids"])
            or _cursor_last(rpc.value,"author",cursor) != [expected["creation"][expected["ids"][0]],expected["ids"][0]]):
        raise AssertionError("The owner cursor must bind the last currently visible row and filtered total.")
    rpc.login("alias")
    status,payload,_ = rpc._wire("GET","/api/method/"+HISTORY,{**fields,"cursor":cursor})
    schema = rpc.openapi["paths"]["/api/method/"+HISTORY]["get"]["responses"]["422"]["content"]["application/json"]["schema"]
    Draft202012Validator({"components":rpc.openapi["components"],**schema},format_checker=FormatChecker()).validate(payload)
    if status!=422 or payload["message"].get("error",{}).get("code")!="invalid_cursor":raise AssertionError("Same-Person alias reused the original User's history cursor.")


def finish_company_history_case(private_manifest, base_url, host_header=None):
    """One source-free terminal Stop during exact duty outage, always restore."""
    import frappe
    with _phase(private_manifest,"executed","stop_entered") as value:
        run = native._run(value,"lookup");proof = value["stages"][KEY]
        original = native._capture_duty_outage(manifest(private_manifest),"document.read","history-r13-source-outage",private_manifest)
        try:
            native._duty(value,"document.read",0,original)
            disabled = deepcopy(original);disabled["active"]=0;disabled["fields"]["active"]=native._native_scalar(0)
            native._independent_duty_readback(value,"document.read",disabled)
            rpc = _HistoryHTTP(private_manifest,base_url,host_header);rpc.login()
            intent = saved_intent(rpc.value,"lookup");fields = {"company":value["company"],"run_id":run["id"]}
            rpc.call(http.RICKY+"get_run",fields,expected={"not_found","capability_denied"})
            rpc.call(http.RICKY+"start_read",{key:item for key,item in intent["payload"].items() if key!="operation_id"},
                key="start-lookup",expected={"not_found","capability_denied"})
            stopped = rpc.call(http.RICKY+"cancel_run",fields,key="stop-lookup")["data"]
            stop = next(row for row in rpc.journal.rows if row["key"]=="stop-lookup")
            if stopped["status"]!="succeeded" or stopped["cancel_requested"] or stopped["operation"]["replayed"] or stop["operation_id"] in proof["original_operations"]:
                raise AssertionError("Require a new source-free Stop acceptance, preserving the existing successful Run.")
            frappe.db.rollback();current = _value(private_manifest);events = _events(run["id"])
            if len(events)!=2 or not typed_equal(events[0],proof["start_event"]):raise AssertionError("Stop appended unexpected history or changed original Start.")
            _event(current,events[1],"stop",events[0]["event_hash"])
            hidden = _visibility(private_manifest,base_url,host_header)
            if any(event["name"] in observation.get("ids",[]) for event in events for observation in hidden.values()):raise AssertionError("Source-free Stop history exposed its inaccessible Run subject.")
            _record(private_manifest,stop_event=events[1],hidden_visibility=hidden)
        finally:
            frappe.db.rollback();native._duty(value,"document.read",original["active"],original)
            native._independent_duty_readback(value,"document.read",original)
        current = _value(private_manifest);proof = current["stages"][KEY]
        visible = _visibility(private_manifest,base_url,host_header)
        event_ids = {proof["start_event"]["name"],proof["stop_event"]["name"]}
        for role in ROLES:
            before = proof["before_visibility"][role];after = visible[role]
            if "denied" in before:
                if not typed_equal(before,after):raise AssertionError("An outsider gained Company history access.")
            elif set(after["ids"]) != set(before["ids"]) | (event_ids if role=="author" else set()):
                raise AssertionError("Original User/alias history visibility changed beyond its two authorized facts.")
        _cursor_alias_refusal(private_manifest,base_url,host_header)
        native.capture_company_receipt_before(private_manifest,"lookup","stop")
        rpc = _HistoryHTTP(private_manifest,base_url,host_header);rpc.login();observations=[]
        for kind,method in (("start",http.RICKY+"start_read"),("stop",http.RICKY+"cancel_run")):
            journal,before = native._receipt(current,"lookup",kind)
            fields = {key:item for key,item in journal["payload"].items() if key!="operation_id"}
            replay = rpc.call(method,fields,key=kind+"-lookup")["data"]
            operation = rpc.call("cipher_aec.api.company.operation",{"company":current["company"],"operation_id":journal["operation_id"]})["data"]
            initial = [attempt["envelope"]["data"] for attempt in journal["attempts"] if attempt.get("status")==200
                and attempt.get("envelope",{}).get("data",{}).get("operation",{}).get("replayed") is False]
            if len(initial)!=1:raise AssertionError("Retain the exact first non-replayed response; never reconstruct it.")
            frappe.db.rollback();_,after = native._receipt(current,"lookup",kind)
            captured = manifest(private_manifest)["stages"]["receipt_before"][kind+"-lookup"]
            observations.append({"user":current["users"]["author"]["user"],"person":current["users"]["author"]["person"],
                "company":current["company"],"run_id":run["id"],"operation_id":journal["operation_id"],
                "command":"ricky.company.read.start.v1" if kind=="start" else "ricky.company.read.cancel.v1",
                "initial":initial[0],"replay":replay,"operation_read":operation,"stored_receipt":{"before":captured,"after":after}})
        result = verify_shared_receipts({**current,"shared_receipt_observations":observations})
        if (not typed_equal(recovery._payloads(run["id"]),proof["terminal_payloads"])
                or not typed_equal(_events(run["id"]),[proof["start_event"],proof["stop_event"]])):
            raise AssertionError("Stop/replay changed terminal Run/children or duplicated command history.")
        _preserved(current);native.verify_company_restoration(private_manifest);recovery._only_active()
        _record(private_manifest,"passed",visible_history=visible,receipts=observations,receipt_result=result,
            qualification="Prospective command facts only; root separately retains actual RQ evidence. No worker history/backfill/model claim.")
        frappe.db.rollback();return {"status":"passed","command_events":2,"receipts":result["receipts"],"source_free_terminal_stop":True}

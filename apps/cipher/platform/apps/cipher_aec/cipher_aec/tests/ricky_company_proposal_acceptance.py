"""Opt-in R14 native suggestion proof; root owns all runtime/RQ execution.

Separate copied-cookie journal, four new named requests, normal canonical manual
targets and one explicitly scoped native finalization rollback. No model, apply,
award, login fallback, clock edits, queue deletion or original evidence rewrite.
"""
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from uuid import uuid4

from .ricky_company_acceptance_support import Journal, ROLES, load_private, manifest, sha, timestamp, typed_equal, write_private
from . import test_ricky_company_native as native
from . import test_ricky_company_http as http
from . import ricky_company_recovery_acceptance as recovery
from . import ricky_company_history_acceptance as history
from . import ricky_company_proposal_prerequisites as prerequisites

KEY="proposals_r14"
SCHEMA="cipher.fixture.ricky.company.proposals.v1"
CASES={"scope-r14":"aec.scope.draft", "estimate-r14":"aec.estimate.draft",
    "checkpoint-rollback-r14":"aec.scope.draft", "cancel-after-preparation-r14":"aec.scope.draft"}
API="cipher_aec.ricky.company_proposal_api."
COMMERCIAL="cipher_aec.commercial.api."
OPERATION="cipher_aec.api.company.operation"
POSTS=frozenset({API+"start_proposal",API+"cancel_run",COMMERCIAL+"create_proposal",COMMERCIAL+"save_proposal_revision",
    http.EST+"create_estimate",http.EST+"calculate_revision"})
GETS=frozenset({API+"get_run",API+"run_events",API+"get_proposal",http.EST+"list_units",http.EST+"get_record",OPERATION,history.HISTORY})


def _origin_unchanged(value):
    proof=value["stages"][KEY];origin=Path(proof["original_directory"])
    if history._digest_bytes(proof["prerequisite_record"])!=proof["prerequisite_sha256"]:
        raise AssertionError("The exact committed prerequisite evidence changed.")
    for relative,checksum in proof["original_files"].items():
        if history._digest_bytes(origin/relative)!=checksum:raise AssertionError("An original fixture/journal/evidence file changed.")
    if set(proof["cookie_sources"])!=set(ROLES):raise ValueError("Keep all three explicit original User cookie references.")
    for role,row in proof["cookie_sources"].items():
        if history._digest_bytes(row["path"])!=row["sha256"] or history._digest_bytes(Path(value["journal_directory"])/(role+".cookies.secret"))!=row["sha256"]:
            raise AssertionError("The exact copied current cookie context changed; no login/replacement is permitted.")


def _value(path):
    value=native._fixture(path);proof=value["stages"].get(KEY,{})
    if proof.get("schema")!=SCHEMA or set(proof.get("cases",{}))!=set(CASES):raise ValueError("Use the separate declared four-case R14 reference journal.")
    _origin_unchanged(value)
    if history._digest_bytes(Path(value["journal_directory"])/"proposal-r14-baseline.secret.json")!=proof["baseline_sha256"]:
        raise AssertionError("The original R14 preservation baseline changed.")
    return value


def _update(path, **fields):
    value=manifest(path);value["stages"][KEY].update(deepcopy(fields));write_private(path,value);return value


def _case_update(path,case,**fields):
    if case not in CASES:raise ValueError("Use an explicitly declared new R14 case.")
    value=manifest(path);row=value["stages"][KEY]["cases"][case];row.update(deepcopy(fields))
    row.setdefault("observations",[]).append({"at":timestamp(),"fields":sorted(fields),"status":row["status"]})
    write_private(path,value);return value


@contextmanager
def _phase(path,expected,entered,*,case=None):
    value=_value(path);row=value["stages"][KEY] if case is None else value["stages"][KEY]["cases"][case]
    if row["status"]!=expected:raise RuntimeError("This native phase is one-shot; reconcile retained failures, never reset them.")
    update=_update if case is None else lambda path,**fields:_case_update(path,case,**fields)
    update(path,status=entered)
    try:yield value
    except BaseException as error:
        update(path,status="failed",error=native._claim_failure(error));raise


class _ProposalHTTP(http._HTTP):
    def _wire(self,*args,**kwargs):
        if "proposal_r14_continuation" in self.value["stages"]:
            from .ricky_company_proposal_continuation import observed_wire
            return observed_wire(self,super()._wire,*args,**kwargs)
        return super()._wire(*args,**kwargs)

    def login(self,role="author",*,fresh=False):
        if fresh or role not in ROLES:raise ValueError("R14 uses exact existing copied cookies only.")
        history._private_bytes(self.work/(role+".cookies.secret"));_origin_unchanged(self.value)
        return super().login(role,fresh=False)

    def call(self,method,values,*,key=None,expected=()):
        """Same published wire validation/journal rules as the qualified client.

        The route set is local; existing fixtures and their globals are untouched.
        """
        if method not in POSTS|GETS:raise ValueError("Only the fixed R14 manual-target/proposal/history/receipt routes are allowed.")
        verb="POST" if method in POSTS else "GET"
        row=self.journal.prepare(key,self.role,method,values) if verb=="POST" else None
        sent=row["payload"] if row else values
        from jsonschema import Draft202012Validator,FormatChecker
        operation=self.openapi["paths"]["/api/method/"+method][verb.lower()]
        if row:
            schema=operation["requestBody"]["content"]["application/json"]["schema"]
            Draft202012Validator({"components":self.openapi["components"],**schema},format_checker=FormatChecker()).validate(sent)
        try:status,payload,seconds=self._wire(verb,"/api/method/"+method,sent,csrf=self.csrf,operation=row["operation_id"] if row else None)
        except BaseException as error:
            if row:self.journal.uncertain(row,error,getattr(self,"last_wire_observation",None))
            raise
        envelope=payload.get("message") if type(payload) is dict else None
        if (type(envelope) is not dict or envelope.get("schema")!="cipher.api.v1" or type(envelope.get("request_id")) is not str
                or type(envelope.get("meta")) is not dict or envelope["meta"].get("request_id")!=envelope["request_id"] or envelope["meta"].get("api_version")!="v1"):
            self._refusal_observation("malformed_canonical_envelope")
            if row:self.journal.refusal(row,status,"malformed_canonical_envelope",getattr(self,"last_wire_observation",None))
            raise AssertionError("The actual response lacks the published outer canonical envelope.")
        try:
            schema=operation["responses"][str(status)]["content"]["application/json"]["schema"]
            Draft202012Validator({"components":self.openapi["components"],**schema},format_checker=FormatChecker()).validate(payload)
        except Exception:
            self._refusal_observation("response_schema_or_status_refused")
            if row:self.journal.refusal(row,status,"response_schema_or_status_refused",getattr(self,"last_wire_observation",None))
            raise AssertionError("Published wire response/status refused; original UUID and observation retained.") from None
        if row:self.journal.response(row,status=status,envelope=envelope)
        # Reload after every wire call: receipt/case snapshots added by another
        # phase must not be overwritten by a stale client manifest in replay.
        self.value=manifest(self.path)
        self.value["stages"].setdefault("http_calls",[]).append({"method":method,"role":self.role,"status":status,
            "request_id":envelope["request_id"],"seconds":seconds,"error_code":envelope.get("error",{}).get("code"),
            "wire_payload_sha256":sha(payload)});write_private(self.path,self.value)
        if expected:
            code=envelope.get("error",{}).get("code")
            if code not in expected or status!={"not_found":404,"capability_denied":403,"session_revoked":403,"execution_quarantined":503}.get(code):
                raise AssertionError("The explicit current-rights denial was not observed.")
        elif status>=400:raise AssertionError("The ordinary HTTP command failed; retain its original journal.")
        return envelope


def _baseline(value):return load_private(Path(value["journal_directory"])/"proposal-r14-baseline.secret.json")


def _config():
    import frappe
    path=Path(frappe.get_site_path("site_config.json"));raw=path.read_bytes()
    return {"raw_sha256":hashlib.sha256(raw).hexdigest(),"parsed":json.loads(raw),
        "observed_quarantine":recovery._config(),"pause_scheduler":frappe.conf.get("pause_scheduler")}


def _receipt(value,case,kind="start"):
    import frappe
    from cipher_aec.ricky.company_proposal_contracts import START_COMMAND,CANCEL_COMMAND
    rows=[row for row in Journal(value["journal_directory"]).rows if row["key"]==kind+"-"+case]
    if len(rows)!=1:raise AssertionError("Retain the single original authentic HTTP journal entry.")
    journal=rows[0];run_id=value["stages"][KEY]["cases"][case]["run_id"]
    name=sha({"person":value["users"]["author"]["person"],"operation_id":journal["operation_id"]})
    row=frappe.db.get_value("Cipher Command Receipt",name,["person","company","scope_type","project","command","state","result_json","result_hash"],as_dict=True)
    if (not row or row.person!=value["users"]["author"]["person"] or row.company!=value["company"] or row.scope_type!="Company" or row.project
            or row.command!=(START_COMMAND if kind=="start" else CANCEL_COMMAND) or row.state!="Succeeded" or json.loads(row.result_json).get("id")!=run_id
            or sha(json.loads(row.result_json))!=row.result_hash):raise AssertionError("The actual receipt attribution/body/hash differs from the original command.")
    return journal,{"result_json":row.result_json,"result_hash":row.result_hash}


def _run(value,case):
    from cipher_aec.ricky.storage import CompanyStore
    run=CompanyStore(worker=True).get_scoped("run",value["stages"][KEY]["cases"][case]["run_id"])
    if (run["company"]!=value["company"] or run["user"]!=value["users"]["author"]["user"] or run["person"]!=value["users"]["author"]["person"]
            or run["request_kind"]!="deterministic-proposal-v1"):raise AssertionError("The Run lost its actual original User/Person/Company request binding.")
    return run


def preservation_changes(before,after,duty_audit=None):
    changes=native._old_row_changes(before,after)
    if duty_audit:
        name=duty_audit["name"];old=before["Cipher Project Duty"][name];new=after["Cipher Project Duty"].get(name)
        if (duty_audit.get("semantic_restored") is not True or duty_audit.get("independent_readback") is not True
                or old!=duty_audit["before"] or new!=duty_audit["after"] or new is None
                or set(old)!=set(new) or any(old[key]!=new[key] for key in old if key not in {"modified","modified_by"})):
            raise AssertionError("Only the exact independently restored duty audit-column delta is attributable.")
        changes=[row for row in changes if not (row["doctype"]=="Cipher Project Duty" and row["name"]==name)]
    return changes


def _preserved(value):
    _origin_unchanged(value);proof=value["stages"][KEY];baseline=_baseline(value)
    prerequisite=load_private(proof["prerequisite_record"])
    original_before=load_private(Path(value["journal_directory"])/"preservation-before.secret.json")
    if (native._old_row_changes(original_before,prerequisite["before"])
            or native._old_row_changes(prerequisite["after"],baseline["inventory"])
            or native._old_row_changes(prerequisite["before"],prerequisite["after"])!=prerequisite["attributed_old_row_changes"]):
        raise AssertionError("Original→separately attributed prerequisite→R14 baseline preservation does not compose exactly.")
    if "proposal_r14_continuation" in value["stages"]:
        from . import ricky_company_proposal_continuation as continuation
        changes=continuation.preservation_changes(value,baseline["inventory"],continuation._inventory())
    else:changes=preservation_changes(baseline["inventory"],prerequisites.inventory(),proof.get("duty_audit"))
    if changes:
        raise AssertionError("An older native row/column changed outside the exact supported duty audit delta.")
    if not typed_equal(_config(),baseline["config"]):raise AssertionError("Original configuration bytes/values changed.")
    for case,row in proof["cases"].items():
        if row["status"]=="passed":
            if recovery._payloads(row["run_id"])!=row["terminal_payloads"] or _receipt(value,case)[1]!=row["start_receipt"]:
                raise AssertionError("An earlier R14 terminal payload or original Start receipt changed.")
            expected=[row["start_event"]]
            if row.get("stop_event"):expected.append(row["stop_event"])
            elif case=="scope-r14" and proof.get("terminal_stop_event"):expected.append(proof["terminal_stop_event"])
            if history._events(row["run_id"])!=expected:raise AssertionError("An earlier R14 command event changed or duplicated.")
            if row.get("receipt_replays",{}).get("stop") and _receipt(value,case,"stop")[1]!=row["receipt_replays"]["stop"]["stored"]:
                raise AssertionError("An earlier R14 Stop receipt changed.")


def prepare_company_proposal_fixture(original_manifest,private_directory,cookie_sources,prerequisite_record):
    """No login or business writes: copy current original-user cookies/reference."""
    import frappe
    from cipher_aec.governance.context import require_effects_enabled
    value=native._fixture(original_manifest);require_effects_enabled();recovery._only_active()
    prerequisite=load_private(prerequisite_record)
    if (prerequisite.get("schema")!=prerequisites.SCHEMA or prerequisite.get("status")!="committed"
            or prerequisite["fixture_id"]!=value["fixture_id"] or prerequisite["company"]!=value["company"]
            or prerequisite["original_manifest_sha256"]!=history._digest_bytes(original_manifest)):
        raise ValueError("First qualify the separate additive native prerequisite record.")
    if type(cookie_sources) is not dict or set(cookie_sources)!=set(ROLES):raise ValueError("Explicit current author/alias/outsider cookie paths are required.")
    origin=Path(value["journal_directory"]).resolve();directory=Path(private_directory).resolve()
    base=Path(frappe.get_site_path("private","cipher-fixtures")).resolve()
    if (not directory.is_relative_to(base) or directory.exists() or directory.is_relative_to(origin) or origin.is_relative_to(directory)):
        raise ValueError("Use a new separate R14 private journal directory.")
    files={str(path.relative_to(origin)):history._digest_bytes(path) for path in origin.rglob("*") if path.is_file()}
    cookies={role:{"path":str(Path(path).resolve()),"sha256":history._digest_bytes(path)} for role,path in cookie_sources.items()}
    if not value["inputs"].get("ready"):raise RuntimeError("Reuse the original canonical manual inputs.")
    baseline={"inventory":prerequisites.inventory(),"config":_config()}
    directory.mkdir(mode=0o700)
    history._copy_private(origin/"preservation-before.secret.json",directory/"preservation-before.secret.json")
    for role,row in cookies.items():history._copy_private(row["path"],directory/(role+".cookies.secret"))
    before_path=directory/"proposal-r14-baseline.secret.json";write_private(before_path,baseline)
    value=deepcopy(value);value.update(journal_directory=str(directory),intents={},shared_receipt_observations=[])
    for row in value["users"].values():row["password"]=None
    value["stages"]={"original_duty_states":deepcopy(value["stages"]["original_duty_states"]),KEY:{"schema":SCHEMA,"status":"prepared",
        "original_directory":str(origin),"original_files":files,"cookie_sources":cookies,"baseline_sha256":history._digest_bytes(before_path),
        "prerequisite_record":str(Path(prerequisite_record).resolve()),"prerequisite_sha256":history._digest_bytes(prerequisite_record),
        "plan":deepcopy(prerequisite["plan"]),"cases":{case:{"status":"declared","action":action} for case,action in CASES.items()},
        "identities":{name:str(uuid4()) for name in ("commercial_section","commercial_line","estimate_line")},
        "original_operations":[row["operation_id"] for row in Journal(origin).rows]}}
    path=directory/"fixture.secret.json";write_private(path,value);manifest(path);frappe.db.rollback()
    return {"private_manifest":str(path),"status":"prepared","cases":list(CASES),"model_invoked":False}


def _sources(value):
    citation=value["inputs"]["citation"]
    return [{key:citation[key] for key in ("revision_id","page","excerpt_sha256","source_sha256")}]


def _composition(value,*,successor=False):
    from cipher_aec.commercial.contracts import composition
    proof=value["stages"][KEY];unit=value["inputs"]["units"][0];ids=proof["identities"]
    return composition({"currency":"USD","price_list":proof["plan"]["price_list"],"valid_till":proof["plan"]["year_end"],
        "terms":"Synthetic manually authored draft; no issuance or acceptance.",
        "sections":[{"id":ids["commercial_section"],"kind":"scope","title":"Manual synthetic scope",
            "text":"Human successor text." if successor else "Human initial text."}],
        "price_lines":[{"id":ids["commercial_line"],"description":"Manual synthetic length","quantity":"3.000000" if successor else "2.000000",
            "unit_id":unit["id"],"unit_revision":unit["revision"],"rate":"1.25","item_code":None,"alternate_group":None,"selected":True}],
        "source_references":[{**_sources(value)[0],"purpose":"Raw synthetic source","permission_basis":"Original author owns this synthetic source"}],
        "estimate_revision":None})


def _estimate_fields(value,estimate_id,previous,*,successor=False):
    return {"estimate_id":estimate_id,"expected_revision":previous,
        "lines":[{"line_id":value["stages"][KEY]["identities"]["estimate_line"],"description":"R14 manually authored length",
            "quantity":{"amount":"3.000000" if successor else "2.000000","unit_id":value["inputs"]["units"][0]["id"],"precision":6},
            "cost_code":"R14-01","notes":"Human successor" if successor else "Manual quantity; no generated input","alternate":"","included":True,
            "rate_source_id":value["inputs"]["rate"]["id"],"material_factor":"1","waste_fraction":"0"}],
        "adjustments":[],"conversion_ids":[value["inputs"]["conversion"]["id"]],"basis_description":"Explicit manual R14 source",
        "basis_citations":_sources(value)}


def create_company_proposal_targets(private_manifest,base_url,host_header=None):
    """Ordinary human canonical commands create only these fresh manual targets."""
    import frappe
    with _phase(private_manifest,"prepared","targets_entered") as value:
        recovery._only_active();_preserved(value)
        rpc=_ProposalHTTP(private_manifest,base_url,host_header);rpc.login()
        recorded=http._input_unit_references(rpc);current=http._current_input_units(rpc,recorded)
        if not typed_equal(current,value["inputs"]["units"]):raise AssertionError("Current original-author units differ from qualified references.")
        result=rpc.command("r14-manual-commercial",COMMERCIAL+"create_proposal",{"pursuit_id":value["inputs"]["pursuit"]["id"],"composition":_composition(value)})
        _update(private_manifest,commercial=result)
        estimate=rpc.command("r14-manual-estimate",http.EST+"create_estimate",{"title":"R14 distinct manually authored estimate","currency":"USD",
            "pricing_date":value["stages"][KEY]["plan"]["pricing_date"],"pursuit_id":value["inputs"]["pursuit"]["id"]})["estimate"]
        _update(private_manifest,estimate={"estimate":estimate})
        calculation=rpc.command("r14-manual-estimate-revision",http.EST+"calculate_revision",_estimate_fields(value,estimate["id"],None))
        if result["proposal"]["id"] in {value["inputs"].get("proposal",{}).get("id")} or estimate["id"]==value["inputs"]["estimate"]["id"]:
            raise AssertionError("Never adopt an older business owner as a mutable R14 target.")
        frappe.db.rollback();current=_update(private_manifest,status="targets_ready",estimate={"estimate":estimate,**calculation})
        _preserved(current);frappe.db.rollback()
        return {"status":"targets_ready","proposal_id":result["proposal"]["id"],"estimate_id":estimate["id"],"standing":"Ordinary manually authored targets only."}


def _request(value,case):
    from cipher_aec.ricky.company_proposal_contracts import DeterministicProposalRequest,REQUEST_SCHEMA
    proof=value["stages"][KEY];citation=value["inputs"]["citation"]
    if CASES[case]=="aec.scope.draft":
        arguments={"proposal_revision_id":proof["commercial"]["revision"]["id"],"sections":[{"heading":"Unverified suggested scope",
            "text":"Author-selected deterministic suggestion; human review required.","citation_ids":[citation["id"]]}],"unverified_claims":["Verify scope before any human use."]}
    else:
        revision=proof["estimate"]["revision"];line=revision["line_record_ids"][0]
        arguments={"base_revision_id":revision["id"],"selections":[{"line_record_id":line,"source_kind":"estimate-line","source_id":line,
            "target_unit_id":value["inputs"]["units"][0]["id"]}],"notes":"Unverified manually selected quantity suggestion.",
            "citation_ids":[citation["id"]],"unverified_claims":[]}
    return DeterministicProposalRequest.from_value({"schema":REQUEST_SCHEMA,"pursuit_id":value["inputs"]["pursuit"]["id"],"action":CASES[case],
        "arguments":arguments,"sources":[{"citation_id":citation["id"],**_sources(value)[0]}],"measurement_ids":[]}).binding()


def _head(company):
    import frappe
    rows=frappe.db.sql("SELECT event_hash FROM `tabCipher History Event` WHERE scope_type='Company' AND company=%s "
        "AND (project IS NULL OR project='') ORDER BY creation DESC,name DESC LIMIT 1",(company,),as_dict=True)
    return rows[0].event_hash if rows else ""


def _event(value,case,kind,row,previous):
    from cipher_aec.api.contracts import canonical_json
    journal,_=_receipt(value,case,kind);initial=json.loads(_receipt(value,case,kind)[1]["result_json"])
    details={"action":CASES[case],"status":"queued"} if kind=="start" else {"status":initial["status"],"cancel_requested":initial["cancel_requested"]}
    body={"scope_type":"Company","actor":value["users"]["author"]["person"],"company":value["company"],"project":None,
        "event":"ricky.company.proposal."+kind+".accepted","subject_type":"Cipher Ricky Run","subject_id":value["stages"][KEY]["cases"][case]["run_id"],
        "operation_id":journal["operation_id"],"details":details,"previous_hash":previous}
    if (row["event_payload"]!=canonical_json(body) or row["event_hash"]!=sha(body) or row["details_json"]!=canonical_json(details)
            or any(not typed_equal(row[column],body[field]) for column,field in (("scope_type","scope_type"),("actor_person","actor"),("company","company"),
                ("project","project"),("event","event"),("subject_type","subject_type"),("subject_id","subject_id"),("operation_id","operation_id"),("previous_hash","previous_hash")))):
        raise AssertionError("The prospective command event/Company chain differs from its exact accepted command.")


def start_company_proposal_case(private_manifest,case,base_url,host_header=None):
    import frappe
    if case not in CASES:raise ValueError("Declare a new R14 case, never repurpose an older operation.")
    with _phase(private_manifest,"declared","start_entered",case=case) as value:
        if value["stages"][KEY]["status"] not in {"targets_ready","successors_ready"}:raise RuntimeError("Prepare fresh canonical targets first.")
        if case in {"checkpoint-rollback-r14","cancel-after-preparation-r14"} and value["stages"][KEY]["status"]!="successors_ready":
            raise RuntimeError("Use the new current successor head for the two separately declared boundary requests.")
        recovery._only_active();_preserved(value);request=_request(value,case);head=_head(value["company"])
        _case_update(private_manifest,case,request=request,previous_hash=head)
        rpc=_ProposalHTTP(private_manifest,base_url,host_header);rpc.login()
        response=rpc.command("start-"+case,API+"start_proposal",{"request":request})
        operation=response["operation"]
        if operation["replayed"] or operation["id"] in value["stages"][KEY]["original_operations"] or response["status"]!="queued":
            raise AssertionError("Require a distinct first ordinary queued admission, not an adopted old operation.")
        _case_update(private_manifest,case,run_id=response["id"],operation_id=operation["id"],queued_response=response)
        frappe.db.rollback();value=_value(private_manifest);run=_run(value,case);recovery._only_active(run["id"])
        events=history._events(run["id"])
        if len(events)!=1:raise AssertionError("Start must append exactly one prospective command event.")
        _event(value,case,"start",events[0],head)
        _case_update(private_manifest,case,status="admitted",start_event=events[0],start_receipt=_receipt(value,case)[1],
            original_binding={key:run[key] for key in ("id","company","user","person","authority","original_session_reference","request")})
        frappe.db.rollback();return {"status":"admitted","case":case,"run_id":run["id"],"root_next":"Ordinary RQ, or explicit checkpoint phase for the two named boundary cases."}


class _FinalizationRollbackProbe(RuntimeError):pass


@contextmanager
def _rollback_probe(service,observe):
    """Only this instance, only terminal Run save, only after real insertion."""
    original=service.store.save
    def fail_after_insert(kind,value):
        if kind=="run" and value.get("status")=="waiting-for-review":
            proposals=service.store.find("proposal",{"run_id":value["id"]},limit=2)
            if len(proposals)!=1 or value.get("proposal_ids")!=[proposals[0]["id"]]:
                raise AssertionError("The rollback probe did not follow one actual Proposed Change insert.")
            observe(deepcopy(proposals[0]))
            raise _FinalizationRollbackProbe("R14 explicitly injected after actual insert, before terminal Run save.")
        return original(kind,value)
    service.store.save=fail_after_insert
    try:yield
    finally:service.store.save=original


def checkpoint_company_proposal_case(private_manifest,case):
    """Normal claim/tool checkpoint, then intentional return or real rollback.

    This is committed-preparation interruption, not an OS-kill/Redis-loss claim.
    """
    import frappe
    from cipher_aec.ricky.company_contracts import decode_run_authority
    from cipher_aec.ricky.company_proposal_service import build_service,CompanyProposalExecution
    from cipher_aec.ricky.contracts import utcnow
    if case not in {"checkpoint-rollback-r14","cancel-after-preparation-r14"}:raise ValueError("Only the two new boundary cases use this checkpoint.")
    with _phase(private_manifest,"admitted","checkpoint_entered",case=case) as value:
        run=_run(value,case);recovery._only_active(run["id"]);service=build_service(worker=True)
        with service.backend.original_user(decode_run_authority(run)):
            claimed=service.claim(run["id"])
            if not claimed or claimed[1]!=1:raise AssertionError("Require the first normal worker claim on this distinct new Run.")
            claimed,token=claimed;output=CompanyProposalExecution(service,run["id"],token).invoke(CASES[case],run["request"]["arguments"],"selected-deterministic-proposal")
            checkpoint=service.store.get("run",run["id"]);payloads=recovery._payloads(run["id"])
            if len(payloads["invocation"])!=1 or len(payloads["step"])!=1 or payloads["proposal"] or output.get("persistent") is not False:
                raise AssertionError("Require one successful nonpersistent preparation checkpoint and no Proposed Change.")
            _case_update(private_manifest,case,checkpoint=checkpoint,checkpoint_payloads=payloads,checkpoint_output=output)
            if case=="checkpoint-rollback-r14":
                def observe(proposal):
                    _case_update(private_manifest,case,uncommitted_insert_observed={"proposal":proposal,"payloads":recovery._payloads(run["id"]),"at":timestamp()})
                try:
                    with _rollback_probe(service,observe):service.finalize(run["id"],token)
                except _FinalizationRollbackProbe as error:
                    _case_update(private_manifest,case,rollback_exception=native._claim_failure(error))
                else:raise AssertionError("The exact post-insert rollback probe was not exercised.")
                if recovery._payloads(run["id"])!=payloads:raise AssertionError("Native savepoint rollback did not restore the exact committed checkpoint/no-orphan state.")
            window=recovery._window(service.store.get("run",run["id"]),checkpoint,utcnow(),expired=False)
        frappe.db.rollback();_case_update(private_manifest,case,status="checkpoint",window=window)
        return {"status":"checkpoint","case":case,"run_id":run["id"],**window,"root_next":"Poll natural expiry then ordinary recovery/RQ" if case=="checkpoint-rollback-r14" else "Ordinary author HTTP Stop before finalization"}


def observe_company_proposal_expiry(private_manifest,*,require_expired=False):
    """Read-only deadline/lease gate before root's ordinary site recovery."""
    import frappe
    from cipher_aec.ricky.contracts import utcnow
    case="checkpoint-rollback-r14";value=_value(private_manifest);row=value["stages"][KEY]["cases"][case]
    if row["status"]!="checkpoint":raise RuntimeError("Observe the original committed checkpoint only.")
    run=_run(value,case);recovery._only_active(run["id"])
    if recovery._payloads(run["id"])!=row["checkpoint_payloads"]:raise AssertionError("The original checkpoint payload changed before recovery.")
    if type(require_expired) is not bool:raise ValueError("Use an explicit expiry observation/gate boolean.")
    result=recovery._window(run,row["checkpoint"],utcnow(),expired=require_expired)
    result["ready_for_ordinary_recovery"]=result["seconds_until_lease"]==0
    frappe.db.rollback();return result


def _current_reads(path,case,base_url,host_header=None):
    value=_value(path);row=value["stages"][KEY]["cases"][case];rpc=_ProposalHTTP(path,base_url,host_header);rpc.login()
    result={"run":rpc.call(API+"get_run",{"company":value["company"],"run_id":row["run_id"]})["data"],
        "steps":rpc.call(API+"run_events",{"company":value["company"],"run_id":row["run_id"]})["data"]}
    if result["run"]["status"]=="waiting-for-review":
        result["proposal"]=rpc.call(API+"get_proposal",{"company":value["company"],"proposal_id":result["run"]["result"]["proposal_id"]})["data"]
    return result


def _replay(path,case,kind,base_url,host_header=None):
    import frappe
    value=_value(path);journal,before=_receipt(value,case,kind);rpc=_ProposalHTTP(path,base_url,host_header);rpc.login()
    initial=[attempt["envelope"]["data"] for attempt in journal["attempts"] if attempt.get("status")==200
        and attempt.get("envelope",{}).get("data",{}).get("operation",{}).get("replayed") is False]
    if len(initial)!=1:raise AssertionError("Preserve the actual unique initial command response; never reconstruct it.")
    fields={key:item for key,item in journal["payload"].items() if key!="operation_id"}
    replay=rpc.call(journal["method"],fields,key=kind+"-"+case)["data"]
    operation=rpc.call(OPERATION,{"company":value["company"],"operation_id":journal["operation_id"]})["data"]
    stored=json.loads(before["result_json"])
    for response,replayed in ((initial[0],False),(replay,True),(operation,True)):
        if ({key:item for key,item in response.items() if key!="operation"}!=stored
                or response["operation"]!={"id":journal["operation_id"],"status":"succeeded","replayed":replayed}):
            raise AssertionError("Exact queued/Stop receipt body, UUID or replay semantics changed.")
    frappe.db.rollback()
    if _receipt(_value(path),case,kind)[1]!=before:raise AssertionError("Receipt replay changed immutable stored bytes.")
    return {"initial":initial[0],"replay":replay,"operation_read":operation,"stored":before}


def verify_company_proposal_case(private_manifest,case,base_url,host_header=None):
    """Fresh native/API readback after root's ordinary RQ; no worker is started."""
    import frappe
    from cipher_aec.ricky.company_contracts import decode_run_authority
    from cipher_aec.ricky.company_proposal_service import build_service
    from cipher_aec.ricky.storage import CompanyStore
    expected="checkpoint" if case=="checkpoint-rollback-r14" else "admitted"
    if case not in {"scope-r14","estimate-r14","checkpoint-rollback-r14"}:raise ValueError("Use the distinct cancellation verifier for its case.")
    with _phase(private_manifest,expected,"verification_entered",case=case) as value:
        row=value["stages"][KEY]["cases"][case];run=_run(value,case);recovery._only_active()
        if run["status"]!="waiting-for-review" or run["tool_calls"]!=1 or len(run["proposal_ids"])!=1:
            raise AssertionError("Require one genuinely persisted reviewable preparation from the ordinary worker.")
        payloads=recovery._payloads(run["id"])
        if len(payloads["step"])!=1 or len(payloads["invocation"])!=1 or len(payloads["proposal"])!=1:
            raise AssertionError("Native Run/Step/Invocation/Proposal cardinality differs from one successful preparation.")
        store=CompanyStore(worker=True)
        for kind,rows in payloads.items():
            for name in rows:store.get_scoped(kind,name)
        invocation=store.get("invocation",next(iter(payloads["invocation"])))
        proposal=store.get("proposal",run["proposal_ids"][0])
        if (invocation["output"]["persistent"] is not False or proposal["persistent"] is not True
                or proposal["preparation"]!=invocation["output"] or proposal["preparation_digest"]!=invocation["output_digest"]
                or proposal["invocation_id"]!=invocation["id"] or proposal["step_id"]!=invocation["step_id"]
                or proposal["source_manifest"]!=run["original_manifest"] or proposal["expires_at"]!=run["deadline"]):
            raise AssertionError("The immutable stored wrapper must preserve the exact original nonpersistent Invocation and real links.")
        if case=="checkpoint-rollback-r14":
            checkpoint=row["checkpoint_payloads"]
            if run["lease_token"]!=row["checkpoint"]["lease_token"]+1 or any(payloads[kind]!=checkpoint[kind] for kind in ("step","invocation","artifact","delegation")):
                raise AssertionError("Natural-expiry recovery must reuse the exact committed preparation/children under the next token.")
        service=build_service(worker=True)
        with service.backend.original_user(decode_run_authority(run)):
            service.get_run(value["company"],run["id"]);service.get_proposal(value["company"],proposal["id"])
        frappe.db.rollback();events=history._events(run["id"])
        if events!=[row["start_event"]]:raise AssertionError("Ordinary workers must not invent command/lifecycle history.")
        reads=_current_reads(private_manifest,case,base_url,host_header);receipt=_replay(private_manifest,case,"start",base_url,host_header)
        if reads["run"]["standing"]["model_invoked"] is not False or reads["proposal"]["preparation"]!=invocation["output"]:
            raise AssertionError("Typed actual API output differs from the real original deterministic preparation.")
        frappe.db.rollback();_preserved(_value(private_manifest))
        _case_update(private_manifest,case,status="passed",terminal_payloads=payloads,terminal_reads=reads,receipt_replay=receipt,
            proposal_id=proposal["id"],worker_history_events=0,qualification="Actual native/API readback; root separately retains ordinary RQ job/worker/queue proof.")
        frappe.db.rollback();return {"status":"passed","case":case,"run_id":run["id"],"proposal_id":proposal["id"],"worker_history_events":0}


def advance_company_proposal_targets(private_manifest,base_url,host_header=None):
    """New ordinary human working heads; never modify stored suggestions."""
    import frappe
    with _phase(private_manifest,"targets_ready","successors_entered") as value:
        if any(value["stages"][KEY]["cases"][case]["status"]!="passed" for case in ("scope-r14","estimate-r14")):
            raise RuntimeError("First qualify both original immutable suggestions.")
        recovery._only_active();proof=value["stages"][KEY];rpc=_ProposalHTTP(private_manifest,base_url,host_header);rpc.login()
        commercial=proof["commercial"];successor=rpc.command("r14-manual-commercial-successor",COMMERCIAL+"save_proposal_revision",
            {"proposal_id":commercial["proposal"]["id"],"expected_revision":commercial["proposal"]["revision_number"],
                "expected_native_fingerprint":commercial["proposal"]["native_fingerprint"],"composition":_composition(value,successor=True)})
        _update(private_manifest,commercial=successor,original_commercial=commercial)
        estimate=proof["estimate"];calculated=rpc.command("r14-manual-estimate-successor",http.EST+"calculate_revision",
            _estimate_fields(value,estimate["estimate"]["id"],estimate["revision"]["id"],successor=True))
        _update(private_manifest,estimate={"estimate":estimate["estimate"],**calculated},original_estimate=estimate)
        for case in ("scope-r14","estimate-r14"):
            if _current_reads(private_manifest,case,base_url,host_header)!=proof["cases"][case]["terminal_reads"]:
                raise AssertionError("A later working revision rewrote or hid the original reviewable preparation.")
            _replay(private_manifest,case,"start",base_url,host_header)
        frappe.db.rollback();current=_update(private_manifest,status="successors_ready")
        _preserved(current);frappe.db.rollback();return {"status":"successors_ready","historical_suggestions_unchanged":True,
            "standing":"Historical readability under current original-source rights; no current-use/apply eligibility claim."}


def stop_company_proposal_checkpoint(private_manifest,base_url,host_header=None):
    import frappe
    from cipher_aec.ricky.company_contracts import decode_run_authority
    from cipher_aec.ricky.company_proposal_service import build_service
    from cipher_aec.ricky.contracts import RickyError
    case="cancel-after-preparation-r14"
    with _phase(private_manifest,"checkpoint","stop_entered",case=case) as value:
        row=value["stages"][KEY]["cases"][case];run=_run(value,case);head=_head(value["company"])
        rpc=_ProposalHTTP(private_manifest,base_url,host_header);rpc.login()
        stopped=rpc.command("stop-"+case,API+"cancel_run",{"run_id":run["id"]})
        if stopped["status"]!="cancelled" or stopped["cancel_requested"] is not True or stopped["operation"]["replayed"]:
            raise AssertionError("Require a distinct ordinary active Stop after successful preparation.")
        frappe.db.rollback();service=build_service(worker=True)
        with service.backend.original_user(decode_run_authority(run)):
            try:service.finalize(run["id"],row["checkpoint"]["lease_token"])
            except RickyError as error:
                if error.code not in {"lease_lost","cancelled"}:raise
                refusal=native._claim_failure(error)
            else:raise AssertionError("The cancelled old token inserted a suggestion.")
        frappe.db.rollback();value=_value(private_manifest);terminal=_run(value,case);payloads=recovery._payloads(run["id"])
        if terminal["status"]!="cancelled" or payloads["proposal"] or any(payloads[kind]!=row["checkpoint_payloads"][kind] for kind in ("step","invocation","artifact","delegation")):
            raise AssertionError("Stop/fencing must retain the successful preparation without any Proposed Change.")
        events=history._events(run["id"])
        if len(events)!=2 or events[0]!=row["start_event"]:raise AssertionError("Active Stop changed Start or added worker history.")
        _event(value,case,"stop",events[1],head)
        replays={kind:_replay(private_manifest,case,kind,base_url,host_header) for kind in ("start","stop")}
        frappe.db.rollback();_case_update(private_manifest,case,status="passed",terminal_payloads=payloads,stop_event=events[1],old_token_refusal=refusal,receipt_replays=replays)
        _preserved(_value(private_manifest));recovery._only_active();frappe.db.rollback()
        return {"status":"passed","case":case,"cancelled":True,"proposals":0,"old_token_refused":True}


def _visibility(path,base_url,host_header):
    value=_value(path);observed={}
    for role in ROLES:
        expected=history._visible_native(value,role);rpc=_ProposalHTTP(path,base_url,host_header);rpc.login(role)
        fields={"company":value["company"],"limit":200,"count_mode":"exact"}
        if "denied" in expected:
            result=rpc.call(history.HISTORY,fields,expected={expected["denied"]});observed[role]={"denied":result["error"]["code"]};continue
        ids=[];cursor=None;last_ids=[]
        for _ in range(51):
            result=rpc.call(history.HISTORY,{**fields,**({"cursor":cursor} if cursor else {})})["data"]
            if result["total"]!=len(expected["ids"]):raise AssertionError("History totals counted inaccessible proposal subjects.")
            ids.extend(row["id"] for row in result["items"]);cursor=result["next_cursor"]
            if not cursor:break
            if not result["items"]:raise AssertionError("A cursor cannot derive from hidden rows.")
            last=result["items"][-1]["id"];last_ids.append(last)
            if history._cursor_last(value,role,cursor)!=[expected["creation"][last],last]:raise AssertionError("Cursor must bind the last actually visible native history row.")
        else:raise RuntimeError("Bounded native history scan did not complete.")
        if ids!=expected["ids"]:raise AssertionError("History item visibility/order differs from current original-User/native/source authorization.")
        observed[role]={"ids":ids,"total":len(ids),"cursor_last_ids":last_ids}
    return observed


def finish_company_proposal_fixture(private_manifest,base_url,host_header=None):
    """Terminal source-free Stop, exact source/privacy/receipt checks and restore."""
    import frappe
    with _phase(private_manifest,"successors_ready","finish_entered") as value:
        proof=value["stages"][KEY]
        if any(row["status"]!="passed" for row in proof["cases"].values()):raise RuntimeError("All four distinct cases must pass first.")
        recovery._only_active();_preserved(value);case="scope-r14";row=proof["cases"][case];run=_run(value,case)
        before_visibility=_visibility(private_manifest,base_url,host_header)
        for role in ("alias","outsider"):
            rpc=_ProposalHTTP(private_manifest,base_url,host_header);rpc.login(role)
            for method,fields in ((API+"get_run",{"run_id":run["id"]}),(API+"run_events",{"run_id":run["id"]}),
                    (API+"get_proposal",{"proposal_id":row["proposal_id"]}),(OPERATION,{"operation_id":row["operation_id"]})):
                rpc.call(method,{"company":value["company"],**fields},expected={"not_found","capability_denied"})
        original=native._capture_duty_outage(manifest(private_manifest),"document.read","proposal-r14-source-outage",private_manifest)
        audit_before=prerequisites.inventory()["Cipher Project Duty"][value["duties"]["document.read"]]
        try:
            native._duty(value,"document.read",0,original)
            disabled=deepcopy(original);disabled["active"]=0;disabled["fields"]["active"]=native._native_scalar(0)
            native._independent_duty_readback(value,"document.read",disabled)
            rpc=_ProposalHTTP(private_manifest,base_url,host_header);rpc.login()
            for method,fields in ((API+"get_run",{"run_id":run["id"]}),(API+"run_events",{"run_id":run["id"]}),
                    (API+"get_proposal",{"proposal_id":row["proposal_id"]}),(OPERATION,{"operation_id":row["operation_id"]})):
                rpc.call(method,{"company":value["company"],**fields},expected={"not_found","capability_denied"})
            journal,_=_receipt(value,case);rpc.call(API+"start_proposal",{key:item for key,item in journal["payload"].items() if key!="operation_id"},
                key="start-"+case,expected={"not_found","capability_denied"})
            frappe.db.rollback();head=_head(value["company"])
            stopped=rpc.command("stop-"+case,API+"cancel_run",{"run_id":run["id"]})
            if stopped["status"]!="waiting-for-review" or stopped["cancel_requested"] or stopped["operation"]["replayed"]:
                raise AssertionError("Accepted terminal Stop must preserve a reviewable suggestion; it is not cancellation.")
            frappe.db.rollback();events=history._events(run["id"])
            if len(events)!=2 or events[0]!=row["start_event"]:raise AssertionError("Terminal Stop changed original Start or added lifecycle history.")
            _event(_value(private_manifest),case,"stop",events[1],head)
            hidden=_visibility(private_manifest,base_url,host_header)
            proposal_ids={event["name"] for target in proof["cases"].values() for event in history._events(target["run_id"])}
            if any(proposal_ids & set(observation.get("ids",[])) for observation in hidden.values()):
                raise AssertionError("Source-free Stop history exposed an inaccessible original-source subject.")
            _update(private_manifest,hidden_visibility=hidden,terminal_stop_event=events[1])
        finally:
            frappe.db.rollback();native._duty(value,"document.read",original["active"],original)
            native._independent_duty_readback(value,"document.read",original)
            audit_after=prerequisites.inventory()["Cipher Project Duty"][value["duties"]["document.read"]]
            _update(private_manifest,duty_audit={"name":value["duties"]["document.read"],"before":audit_before,"after":audit_after,
                "semantic_restored":True,"independent_readback":True,"standing":"Only supported modified/modified_by audit delta; whole row is not byte-unchanged."})
            frappe.db.rollback()
        value=_value(private_manifest);_preserved(value)
        visible=_visibility(private_manifest,base_url,host_header)
        for role in ROLES:
            before=before_visibility[role];after=visible[role]
            if "denied" in before:
                if after!=before:raise AssertionError("An outsider gained Company history authority.")
            elif set(after["ids"])!=set(before["ids"])|({events[1]["name"]} if role=="author" else set()):
                raise AssertionError("Terminal Stop changed current mixed history visibility beyond its one authorized fact.")
        # Reuse the qualified cursor proof with this route-compatible subclass;
        # do not alter the history helper's globals or client route whitelist.
        rpc=_ProposalHTTP(private_manifest,base_url,host_header);rpc.login()
        page=rpc.call(history.HISTORY,{"company":value["company"],"limit":1,"count_mode":"exact"})["data"]
        if not page["next_cursor"]:raise AssertionError("The mixed authorized history must provide a bound owner cursor.")
        last=page["items"][-1]["id"];expected=history._visible_native(value,"author")
        if page["total"]!=len(expected["ids"]) or history._cursor_last(value,"author",page["next_cursor"])!=[expected["creation"][last],last]:
            raise AssertionError("The actual owner cursor/filtered total changed.")
        rpc.login("alias");status,payload,_=rpc._wire("GET","/api/method/"+history.HISTORY,{"company":value["company"],"limit":1,"count_mode":"exact","cursor":page["next_cursor"]})
        from jsonschema import Draft202012Validator,FormatChecker
        schema=rpc.openapi["paths"]["/api/method/"+history.HISTORY]["get"]["responses"]["422"]["content"]["application/json"]["schema"]
        Draft202012Validator({"components":rpc.openapi["components"],**schema},format_checker=FormatChecker()).validate(payload)
        if status!=422 or payload["message"].get("error",{}).get("code")!="invalid_cursor":raise AssertionError("Same-Person alias reused the original User cursor.")
        _update(private_manifest,cursor_alias_refusal={"status":status,"envelope":payload["message"]})
        replays={}
        for target in CASES:
            replays[target]={"start":_replay(private_manifest,target,"start",base_url,host_header)}
            if target in {case,"cancel-after-preparation-r14"}:replays[target]["stop"]=_replay(private_manifest,target,"stop",base_url,host_header)
        for target in ("scope-r14","estimate-r14","checkpoint-rollback-r14"):
            if _current_reads(private_manifest,target,base_url,host_header)!=proof["cases"][target]["terminal_reads"]:
                raise AssertionError("Restored rights/replay changed the immutable original API preparation.")
        frappe.db.rollback();_preserved(_value(private_manifest));_verify_identity_restoration(_value(private_manifest));recovery._only_active()
        _update(private_manifest,status="passed",visible_history=visible,receipt_replays=replays,finished_at=timestamp(),
            qualification="Native/API checkpoint/finalization and current authorization proof only; root separately records actual ordinary RQ/queue/worker proof. No model/apply/OS-kill/Redis-loss claim.")
        frappe.db.rollback();return {"status":"passed","suggestions":3,"cancelled_before_finalization":1,"source_free_terminal_stop":True,
            "duty_semantics_restored":True,"old_rows_preserved_except_exact_duty_audit":True,"root_remaining":"Independent empty queue/worker/config/cookie/evidence readback."}


def _verify_identity_restoration(value):
    import frappe
    from cipher_aec.governance.context import current_actor,duty_rows
    from .ricky_company_acceptance_support import fixture_company_reference
    for role,row in value["users"].items():
        actor=current_actor(row["user"])
        if actor.person_id!=row["person"] or duty_rows(actor):raise AssertionError("Original Company-only User/Person or Project duties changed.")
    for ability,name in value["duties"].items():
        if native._duty_state(value,ability,frappe.get_doc("Cipher Project Duty",name))!=value["stages"]["original_duty_states"][ability]:
            raise AssertionError("An original typed fixture duty was not restored.")
    reference=fixture_company_reference(value);expected=reference["initial_project_ids"] if reference else []
    if native._company_project_ids(value["company"])!=expected:raise AssertionError("The exact original Company Project ID set changed.")
    if reference is not None:native._read_existing_company_reference(reference)
    return {"company_projects":len(expected),"introduced_projects":0,"duty_semantics_restored":True}


def reconcile_company_proposal_fixture(private_manifest):
    """Read-only current state; does not reset a failed phase or mint a UUID."""
    import frappe
    value=_value(private_manifest);result={"status":value["stages"][KEY]["status"],"at":timestamp(),"cases":{}}
    for case,row in value["stages"][KEY]["cases"].items():
        result["cases"][case]={"recorded_status":row["status"],"run_id":row.get("run_id"),"payloads":recovery._payloads(row["run_id"]) if row.get("run_id") else None,
            "journals":[deepcopy(entry) for entry in Journal(value["journal_directory"]).rows if entry["key"] in {"start-"+case,"stop-"+case}]}
    _preserved(value);frappe.db.rollback();return result

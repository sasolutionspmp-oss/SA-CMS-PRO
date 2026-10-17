"""One explicit R14 continuation; original failed evidence is never changed.

Import is inert. Root alone invokes native/HTTP phases after reviewing their
frozen source. Session maintenance is attributed per wire, never reset/ignored.
"""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
from importlib import import_module
from pathlib import Path
import threading
from zoneinfo import ZoneInfo

from .ricky_company_acceptance_support import Journal, ROLES, load_private, manifest, sha, timestamp, typed_equal, write_private
from . import ricky_company_proposal_acceptance as driver

KEY="proposal_r14_continuation"
SCHEMA="cipher.fixture.ricky.company.proposal-continuation.v1"
OPERATION="f04af4cc-df9c-4b5b-a045-7bba2ade75b5"
COMMAND_KEY="r14-manual-commercial"
SOURCE_SHA256="397aaa146652cc645cd8f1968400ea7c5aa56a784a3096d6b5374f37686795c2"
TIMEZONE_POLICY={"configured":None,"effective":"Asia/Kolkata","native_timestamp":"naive-local","wire_timestamp":"UTC"}


def _time(value):
    if type(value) is not str:raise ValueError("Use a real UTC observation.")
    result=datetime.fromisoformat(value)
    if result.tzinfo is None or result.utcoffset().total_seconds()!=0:raise ValueError("UTC time bounds are required.")
    return result


def _active(value,timezone_name="Asia/Kolkata"):
    if timezone_name!=TIMEZONE_POLICY["effective"]:raise AssertionError("Only the reviewed literal fixture timezone is admitted.")
    if type(value) is not dict or set(value)!={"type","value"} or value["type"]!="datetime":
        raise AssertionError("The native last_active column must retain its datetime type.")
    result=datetime.fromisoformat(value["value"])
    if result.tzinfo is not None:raise AssertionError("Pinned native User datetime must remain naive local time.")
    return result.replace(tzinfo=ZoneInfo(timezone_name)).astimezone(timezone.utc)


def user_transition(before,after,users,role,start,end):
    """Full typed column hashes, one exact User and one exact time-bounded field."""
    if set(users)!=set(ROLES) or role not in ROLES or len({row["user"] for row in users.values()})!=3:
        raise ValueError("Keep the exact three original fixture Users.")
    names={row["user"] for row in users.values()}
    if set(before)!=names or set(after)!=names:raise AssertionError("Only the exact three complete User snapshots are admitted.")
    lower,upper=_time(start),_time(end)
    if lower>upper:raise AssertionError("Native observation time bounds are reversed.")
    changes=[]
    for name in sorted(names):
        old,new=before[name],after[name]
        if set(old)!={"columns","last_active"} or set(new)!={"columns","last_active"} or set(old["columns"])!=set(new["columns"]):
            raise AssertionError("The full native User column set changed.")
        for row in (old,new):
            if row["columns"].get("last_active")!=sha(row["last_active"]):raise AssertionError("The exact last_active column hash changed outside its typed value.")
        fields=[key for key in old["columns"] if old["columns"][key]!=new["columns"][key]]
        if not fields:continue
        if name!=users[role]["user"] or fields!=["last_active"]:raise AssertionError("Only this wire's exact original User last_active may change.")
        current=_active(new["last_active"])
        if not lower<=current<=upper or current<=_active(old["last_active"]):
            raise AssertionError("The heartbeat is not an advancing native timestamp inside the actual wire bounds.")
        changes.append({"doctype":"User","name":name,"columns":["last_active"],"before":old["columns"],"after":new["columns"]})
    return changes


def _independent(read):
    """Own thread/connection only; never end the parent's transaction/locks."""
    import frappe
    site=frappe.local.site;result=[]
    def observe():
        errors=[];value=None
        try:
            frappe.init(site=site);frappe.connect();value=read(frappe)
        except BaseException as error:errors.append(driver.native._claim_failure(error))
        finally:
            try:frappe.db.rollback()
            except BaseException as error:errors.append(driver.native._claim_failure(error))
            try:frappe.destroy()
            except BaseException as error:errors.append(driver.native._claim_failure(error))
            result.append({"value":value,"errors":errors})
    thread=threading.Thread(target=observe,daemon=True);thread.start();thread.join(10)
    if thread.is_alive() or len(result)!=1 or result[0]["errors"]:
        raise AssertionError("Independent native observer/cleanup failed: "+str(result))
    return result[0]["value"]


def verify_installed_session_source():
    path=Path(import_module("frappe.sessions").__file__)
    if hashlib.sha256(path.read_bytes()).hexdigest()!=SOURCE_SHA256:
        raise AssertionError("Installed native Session.update source differs from the pinned heartbeat controller.")


def observe_users(value):
    def read(frappe):
        verify_installed_session_source()
        zones=frappe.db.sql("SELECT value FROM tabSingles WHERE doctype='System Settings' AND field='time_zone'",as_dict=True)
        if zones!=[{"value":None}] or frappe.utils.get_system_timezone()!=TIMEZONE_POLICY["effective"]:
            raise AssertionError("Preserve the exact stored NULL timezone setting and actual Asia/Kolkata fallback; never edit config/clock.")
        lower=timestamp();names=[value["users"][role]["user"] for role in ROLES]
        rows=frappe.db.sql("SELECT * FROM tabUser WHERE name IN (%s,%s,%s) ORDER BY name",tuple(names),as_dict=True)
        if len(rows)!=3 or {row["name"] for row in rows}!=set(names):raise AssertionError("Original native User is missing.")
        users={row["name"]:{"columns":{key:sha(driver.native._native_scalar(item)) for key,item in row.items()},
            "last_active":driver.native._native_scalar(row["last_active"])} for row in rows}
        return {"started_at":lower,"completed_at":timestamp(),"timezone":deepcopy(TIMEZONE_POLICY),"users":users}
    return _independent(read)


def _inventory():return _independent(lambda frappe:driver.prerequisites.inventory())


def _file(path):return {"path":str(Path(path).resolve()),"sha256":driver.history._digest_bytes(path)}


def _record(ref):
    if type(ref) is not dict or set(ref)!={"path","sha256"} or driver.history._digest_bytes(ref["path"])!=ref["sha256"]:
        raise AssertionError("An exact retained private evidence file changed.")
    return load_private(ref["path"])


def _declaration(value):
    proof=value["stages"].get(KEY)
    if (type(proof) is not dict or proof.get("schema")!=SCHEMA or proof.get("fixture_id")!=value["fixture_id"]
            or proof.get("company")!=value["company"] or proof.get("site")!=value["site"]
            or proof.get("session_source_sha256")!=SOURCE_SHA256 or proof.get("timezone_policy")!=TIMEZONE_POLICY or proof.get("initial_timezone_observation")!=TIMEZONE_POLICY):raise ValueError("Use the reviewed explicit R14 continuation declaration.")
    required={"schema","status","fixture_id","company","site","session_source_sha256","failed_directory","failed_files","evidence","initial_heartbeat","original_command","baseline_sha256","heartbeats","timezone_policy","initial_timezone_observation"}
    if not required<=set(proof):raise ValueError("The continuation declaration is incomplete.")
    original=Path(proof["failed_directory"])
    if set(proof)-{"schema","status","fixture_id","company","site","session_source_sha256","failed_directory","failed_files","evidence","initial_heartbeat","original_command","baseline_sha256","heartbeats","timezone_policy","initial_timezone_observation","pre_send_reconciliation","error"}:raise ValueError("The continuation declaration contains an unsupported field.")
    actual={str(path.relative_to(original)):driver.history._digest_bytes(path) for path in original.rglob("*") if path.is_file()}
    if actual!=proof["failed_files"]:raise AssertionError("Retain the complete exact original failed artifact set.")
    if set(proof["evidence"])!={"heartbeat_provenance","supplement","supplement_reconciliation","supplement_before"}:
        raise ValueError("All four exact prerequisite/time-provenance evidence references are mandatory.")
    for relative,checksum in proof["failed_files"].items():
        if Path(relative).is_absolute() or ".." in Path(relative).parts:raise ValueError("Use only original relative artifact paths.")
        if driver.history._digest_bytes(original/relative)!=checksum or driver.history._digest_bytes(Path(value["journal_directory"])/"failed-original"/relative)!=checksum:
            raise AssertionError("An original failed R14 artifact or its exact retained copy changed.")
    for role in ROLES:
        if driver.history._digest_bytes(Path(value["journal_directory"])/(role+".cookies.secret"))!=proof["failed_files"][role+".cookies.secret"]:
            raise AssertionError("Continuation requires the unchanged copied original cookies.")
    for ref in proof["evidence"].values():_record(ref)
    old=manifest(original/"fixture.secret.json")
    if not typed_equal(old["users"],value["users"]) or old["company"]!=value["company"] or old["fixture_id"]!=value["fixture_id"]:
        raise AssertionError("Original User/Person/Company identities changed.")
    original_row=original_command(old)
    if proof["original_command"]!=original_row:raise AssertionError("The explicitly recorded original UUID/payload changed.")
    retained=old["stages"][driver.KEY];current=value["stages"][driver.KEY]
    if any(not typed_equal(retained[key],current[key]) for key in ("original_directory","original_files","cookie_sources","baseline_sha256","prerequisite_record","prerequisite_sha256","plan","identities","original_operations")) or any(not typed_equal(old[key],value[key]) for key in ("native","inputs","duties")):
        raise AssertionError("The original baseline/prerequisite/source/identity links changed.")
    baseline=load_private(Path(value["journal_directory"])/"continuation-baseline.secret.json")
    supplement=_record(proof["evidence"]["supplement"])
    if sha(baseline)!=supplement["observed_after_sha256"] or proof["failed_files"]!=supplement["failed_files"]:
        raise AssertionError("Continuation baseline must retain the exact committed supplemental inventory.")
    initial=_initial_users(old,driver._baseline(old)["inventory"],proof["initial_heartbeat"]["after_users"],_record(proof["evidence"]["heartbeat_provenance"]))
    if not typed_equal(initial,proof["initial_heartbeat"]) or any(baseline["User"].get(name)!=row["columns"] for name,row in initial["after_users"].items()):
        raise AssertionError("The authentic initial User hashes/time attribution changed.")
    rows=[row for row in Journal(value["journal_directory"]).rows if row["key"]==COMMAND_KEY]
    if len(rows)!=1 or any(not typed_equal(rows[0].get(key),item) for key,item in original_row.items() if key!="attempts") or rows[0]["attempts"][:len(original_row["attempts"])]!=original_row["attempts"]:
        raise AssertionError("The continuation changed the original failed command payload/UUID/evidence.")
    return proof


def original_command(value):
    stage=value["stages"][driver.KEY];rows=Journal(value["journal_directory"]).rows
    if (stage["status"]!="failed" or set(stage["cases"])!=set(driver.CASES) or any(row!={"status":"declared","action":driver.CASES[case]} for case,row in stage["cases"].items())
            or any(key in stage for key in ("commercial","estimate")) or value["intents"] or len(rows)!=1):
        raise ValueError("Only the retained first-target failure before any admitted R14 case can continue.")
    row=rows[0]
    if (row["key"]!=COMMAND_KEY or row["role"]!="author" or row["method"]!=driver.COMMERCIAL+"create_proposal"
            or row["operation_id"]!=OPERATION or row["payload"].get("operation_id")!=OPERATION or row["payload_sha256"]!=sha(row["payload"])
            or not row["attempts"] or any(attempt.get("status")!=403 for attempt in row["attempts"])):
        raise ValueError("Use the literal original denied commercial request and UUID.")
    return deepcopy(row)


def _absence(value):
    def read(frappe):
        # Name derivation is the existing canonical person/operation identity.
        receipt=sha({"person":value["users"]["author"]["person"],"operation_id":OPERATION})
        if frappe.db.exists("Cipher Command Receipt",receipt):raise AssertionError("Original command already has a receipt; reconcile it instead.")
        inventory=driver.prerequisites.inventory()
        return {"inventory":inventory,"receipt_absent":True,"at":timestamp()}
    return _independent(read)


def _initial_users(value,before,current,provenance):
    names={row["user"] for row in value["users"].values()}
    if set(current)!=names or any(set(row)!={"columns","last_active"} or set(row["columns"])!=set(before["User"][name]) for name,row in current.items()):
        raise AssertionError("The initial native observation requires all three exact complete User rows.")
    if set(provenance)!={"baseline_stat","wire_observations"}:raise ValueError("Use the authentic retained baseline stat/wire provenance.")
    path=Path(value["journal_directory"])/"proposal-r14-baseline.secret.json";stat=path.stat();facts=provenance["baseline_stat"]
    if stat.st_mtime_ns!=facts["mtime_ns"] or stat.st_ctime_ns!=facts["ctime_ns"]:raise AssertionError("Original baseline native stat provenance changed.")
    wire=load_private(Path(value["journal_directory"])/"wire-observations.secret.json")
    if wire!=provenance["wire_observations"] or len(wire)!=3 or wire[-1].get("operation_id")!=OPERATION or wire[-1].get("status")!=403:
        raise AssertionError("Use the exact original three actual wire observations.")
    lower=_time(facts["mtime_utc"])
    if datetime.fromtimestamp(facts["mtime_ns"]/1e9,timezone.utc)!=lower or facts["ctime_ns"]<facts["mtime_ns"]:
        raise AssertionError("Native baseline time provenance is inconsistent.")
    times=[_time(row["at"]) for row in wire]
    if times!=sorted(times) or times[0]<lower:raise AssertionError("Original wire times precede their native baseline.")
    # Initial verification separately preserves the unknown old typed value/hash.
    changes=driver.native._old_row_changes(before,{**before,"User":{**before["User"],**{key:row["columns"] for key,row in current.items()}}})
    name=value["users"]["author"]["user"]
    if (len(changes)!=1 or changes[0]["doctype"]!="User" or changes[0]["name"]!=name
            or sorted(key for key in changes[0]["before"] if changes[0]["before"][key]!=changes[0]["after"][key])!=["last_active"]):
        raise AssertionError("Only the original failed author heartbeat can bridge the baseline.")
    if any(row["columns"].get("last_active")!=sha(row["last_active"]) for row in current.values()):raise AssertionError("Initial native typed timestamp/hash differs.")
    if not lower<=_active(current[name]["last_active"])<=times[-1]:raise AssertionError("Initial author heartbeat is outside retained actual native/wire bounds.")
    if any(before["User"][key]!=row["columns"] for key,row in current.items() if key!=name):raise AssertionError("Another original User changed.")
    return {"before_columns":deepcopy(before["User"]),"after_users":deepcopy(current),"lower":facts["mtime_utc"],"upper":wire[-1]["at"],"changes":changes}


def prepare_company_proposal_continuation(failed_manifest,private_directory,heartbeat_provenance,supplement_record,supplement_reconciliation,*,evidence_sha256):
    """Read-only DB preparation; new files only, never reset the failed phase."""
    value=driver._value(failed_manifest);row=original_command(value);driver.recovery._only_active()
    refs={key:_file(path) for key,path in {"heartbeat_provenance":heartbeat_provenance,"supplement":supplement_record,"supplement_reconciliation":supplement_reconciliation}.items()}
    if {key:ref["sha256"] for key,ref in refs.items()}!=evidence_sha256:raise AssertionError("Explicit root-reviewed evidence hashes differ.")
    supplement=_record(refs["supplement"]);reconciled=_record(refs["supplement_reconciliation"])
    if (supplement.get("schema")!="cipher.fixture.ricky.company.account-select.v1" or supplement.get("status")!="committed"
            or supplement["failed_directory"]!=value["journal_directory"] or supplement["company"]!=value["company"]
            or supplement["role"]!=value["native"]["role"] or supplement["author"]!=value["users"]["author"]["user"]
            or supplement["grants"]!={"Account":["select"]} or supplement["business_master_writes"] is not False
            or reconciled!={"status":"passed","committed_record":refs["supplement"]["path"],"committed_record_sha256":refs["supplement"]["sha256"],
                "original_failed_files_unchanged":True,"old_rows_unchanged":True,"effective_select_only":True,
                "permissions_added":len(supplement["added_permission_names"]),"account":supplement["account"]}):
        raise AssertionError("Require the exact committed select-only supplemental boundary and independent reconciliation.")
    origin=Path(value["journal_directory"]);files={str(path.relative_to(origin)):driver.history._digest_bytes(path) for path in origin.rglob("*") if path.is_file()}
    if files!=supplement["failed_files"]:raise AssertionError("Original failed files changed after the supplemental review.")
    before_ref={"path":supplement["before_path"],"sha256":supplement["before_sha256"]};before=_record(before_ref);refs["supplement_before"]=before_ref
    baseline=driver._baseline(value);observed=observe_users(value);current=observed["users"]
    if observed["timezone"]!=TIMEZONE_POLICY:raise AssertionError("Initial actual timezone provenance changed.")
    initial=_initial_users(value,baseline["inventory"],current,_record(refs["heartbeat_provenance"]))
    bridged=deepcopy(baseline["inventory"])
    for name,item in current.items():bridged["User"][name]=deepcopy(item["columns"])
    if bridged!=before:raise AssertionError("Original baseline to supplemental before differs beyond the authentic heartbeat.")
    absence=_absence(value);after=absence["inventory"]
    if sha(after)!=supplement["observed_after_sha256"] or driver.native._old_row_changes(before,after):raise AssertionError("The exact independently committed supplemental after inventory changed.")
    driver.prerequisites.new_row_attribution(before,after,{"Custom DocPerm":supplement["added_permission_names"]})
    if not typed_equal(driver._config(),baseline["config"]) or driver._config()["raw_sha256"]!=supplement["config_sha256"]:
        raise AssertionError("The original exact site configuration changed.")
    for table in ("Cipher Proposal","Cipher Proposal Revision","Quotation","Quotation Item","Cipher Estimate","Cipher Estimate Revision","Cipher Calculation Snapshot","Cipher Estimate Line",*driver.native.RICKY_TABLES):
        if after.get(table)!=baseline["inventory"].get(table):raise AssertionError("No business target/Run may precede the explicit continuation.")
    directory=Path(private_directory).resolve();base=origin.parent.resolve()
    if directory.name!="company-proposals-r14-continuation" or directory.parent!=base or directory.exists():raise ValueError("Use the distinct new literal continuation directory.")
    directory.mkdir(mode=0o700);(directory/"failed-original").mkdir(mode=0o700)
    for relative in files:
        target=directory/"failed-original"/relative;target.parent.mkdir(parents=True,exist_ok=True);driver.history._copy_private(origin/relative,target)
    for name in ("preservation-before.secret.json","proposal-r14-baseline.secret.json",*(role+".cookies.secret" for role in ROLES)):
        driver.history._copy_private(origin/name,directory/name)
    write_private(directory/"http-journal.secret.json",[row]);write_private(directory/"continuation-baseline.secret.json",after)
    proof={"schema":SCHEMA,"status":"prepared","fixture_id":value["fixture_id"],"company":value["company"],"site":value["site"],
        "session_source_sha256":SOURCE_SHA256,"timezone_policy":deepcopy(TIMEZONE_POLICY),"initial_timezone_observation":observed["timezone"],"failed_directory":str(origin),"failed_files":files,"evidence":refs,
        "initial_heartbeat":initial,"original_command":row,"baseline_sha256":driver.history._digest_bytes(directory/"continuation-baseline.secret.json"),"heartbeats":[]}
    value=deepcopy(value);value["journal_directory"]=str(directory);value["stages"][KEY]=proof
    value["stages"][driver.KEY]["status"]="continuation_prepared"
    path=directory/"fixture.secret.json";write_private(path,value);_declaration(value)
    return {"private_manifest":str(path),"status":"prepared","original_operation_id":OPERATION,"business_writes":False}


def observed_wire(client,send,method,path,values=None,*,csrf=None,operation=None):
    proof=_declaration(manifest(client.path));before=observe_users(client.value)
    previous=proof["heartbeats"][-1]["after"]["users"] if proof["heartbeats"] else proof["initial_heartbeat"]["after_users"]
    if before["timezone"]!=TIMEZONE_POLICY or before["users"]!=previous:raise AssertionError("User bytes changed outside the exact recorded wire chain.")
    entry={"role":client.role,"method":method,"path":path,"operation_id":operation,"payload_sha256":sha(values),"before":before,"started_at":timestamp()}
    result=None;error=None
    try:result=send(method,path,values,csrf=csrf,operation=operation)
    except BaseException as failure:error=failure;entry["wire_error"]=driver.native._claim_failure(failure)
    entry["completed_at"]=timestamp();entry["wire"]=deepcopy(getattr(client,"last_wire_observation",None))
    try:entry["after"]=observe_users(client.value)
    except BaseException as failure:entry["observer_error"]=driver.native._claim_failure(failure);error=error or failure
    # Persist observations before assertions, including malformed/error wires.
    value=manifest(client.path);value["stages"][KEY]["heartbeats"].append(entry);write_private(client.path,value)
    if error is not None:raise error
    if entry["after"]["timezone"]!=TIMEZONE_POLICY:raise AssertionError("Actual per-wire timezone provenance changed.")
    changes=user_transition(before["users"],entry["after"]["users"],value["users"],client.role,entry["started_at"],entry["completed_at"])
    entry.update(status="verified",changes=changes)
    value=manifest(client.path);value["stages"][KEY]["heartbeats"][-1]=entry;write_private(client.path,value)
    return result


def preservation_changes(value,before,after):
    proof=_declaration(value);baseline=load_private(Path(value["journal_directory"])/"continuation-baseline.secret.json")
    if driver.history._digest_bytes(Path(value["journal_directory"])/"continuation-baseline.secret.json")!=proof["baseline_sha256"]:
        raise AssertionError("Continuation supplemental baseline changed.")
    if before!=driver._baseline(value)["inventory"]:raise AssertionError("Preserve the original baseline argument.")
    expected=proof["initial_heartbeat"]["after_users"]
    for entry in proof["heartbeats"]:
        if entry.get("status")!="verified" or entry["before"]["users"]!=expected or entry["before"]["timezone"]!=TIMEZONE_POLICY or entry["after"]["timezone"]!=TIMEZONE_POLICY:
            raise AssertionError("An incomplete/broken heartbeat ledger cannot excuse preservation drift.")
        changes=user_transition(entry["before"]["users"],entry["after"]["users"],value["users"],entry["role"],entry["started_at"],entry["completed_at"])
        if changes!=entry["changes"]:raise AssertionError("Recorded heartbeat attribution changed.")
        expected=entry["after"]["users"]
    reconciled=deepcopy(after)
    for name,row in expected.items():
        if after["User"].get(name)!=row["columns"]:raise AssertionError("Current User columns differ from exact observed heartbeat bytes.")
        reconciled["User"][name]=deepcopy(baseline["User"][name])
    return driver.preservation_changes(baseline,reconciled,value["stages"][driver.KEY].get("duty_audit"))


def continue_company_proposal_targets(private_manifest,base_url,host_header=None):
    """One new phase: ordinary resend of the same original denied UUID."""
    value=driver._value(private_manifest);proof=_declaration(value)
    if proof["status"]!="prepared" or value["stages"][driver.KEY]["status"]!="continuation_prepared":raise RuntimeError("Never retry/reset a continuation phase.")
    driver.recovery._only_active();absence=_absence(value)
    if absence["inventory"]!=load_private(Path(value["journal_directory"])/"continuation-baseline.secret.json"):
        raise AssertionError("Fresh read-only no-receipt/target reconciliation differs from preparation.")
    value["stages"][KEY].update(status="entered",pre_send_reconciliation={"receipt_absent":True,"at":absence["at"],"inventory_sha256":sha(absence["inventory"])})
    write_private(private_manifest,value)
    try:
        rpc=driver._ProposalHTTP(private_manifest,base_url,host_header);rpc.login()
        units=driver.http._current_input_units(rpc,driver.http._input_unit_references(rpc))
        if not typed_equal(units,value["inputs"]["units"]):raise AssertionError("Current author unit references changed.")
        fields={key:item for key,item in proof["original_command"]["payload"].items() if key!="operation_id"}
        result=rpc.call(driver.COMMERCIAL+"create_proposal",fields,key=COMMAND_KEY)["data"]
        if result["operation"]!={"id":OPERATION,"status":"succeeded","replayed":False}:raise AssertionError("Require the first authentic receipt for the original command.")
        driver._update(private_manifest,commercial=result)
        estimate=rpc.command("r14-manual-estimate",driver.http.EST+"create_estimate",{"title":"R14 distinct manually authored estimate","currency":"USD",
            "pricing_date":value["stages"][driver.KEY]["plan"]["pricing_date"],"pursuit_id":value["inputs"]["pursuit"]["id"]})["estimate"]
        driver._update(private_manifest,estimate={"estimate":estimate})
        calculation=rpc.command("r14-manual-estimate-revision",driver.http.EST+"calculate_revision",driver._estimate_fields(value,estimate["id"],None))
        current=driver._update(private_manifest,status="targets_ready",estimate={"estimate":estimate,**calculation})
        current["stages"][KEY]["status"]="targets_ready";write_private(private_manifest,current);driver._preserved(current)
        return {"status":"targets_ready","original_operation_id":OPERATION,"proposal_id":result["proposal"]["id"],"estimate_id":estimate["id"]}
    except BaseException as error:
        current=manifest(private_manifest);current["stages"][KEY].update(status="failed",error=driver.native._claim_failure(error));write_private(private_manifest,current);raise

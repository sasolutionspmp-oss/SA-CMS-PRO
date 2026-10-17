"""Focused host-only continuation contracts; no native/network effects."""
from copy import deepcopy
from datetime import datetime,timedelta,timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import unittest
from uuid import uuid4
from zoneinfo import ZoneInfo

from . import ricky_company_proposal_continuation as continued
from . import ricky_company_proposal_acceptance as driver
from .ricky_company_acceptance_support import Journal,manifest,sha,timestamp,write_private


class HeartbeatTests(unittest.TestCase):
    def setUp(self):
        self.users={role:{"user":role,"person":"one" if role!="outsider" else "two"} for role in driver.ROLES}
        self.before={role:self.row("2026-10-16T08:00:00") for role in driver.ROLES}
        self.after=deepcopy(self.before);self.after["author"]=self.row("2026-10-16T08:01:00")
        self.bounds=("2026-10-16T08:00:59+00:00","2026-10-16T08:01:01+00:00")

    @staticmethod
    def row(stamp):
        active={"type":"datetime","value":datetime.fromisoformat(stamp).replace(tzinfo=timezone.utc).astimezone(ZoneInfo("Asia/Kolkata")).replace(tzinfo=None).isoformat()}
        return {"last_active":active,"columns":{"last_active":sha(active),"modified":"m"*64,"last_ip":"i"*64,"name":"n"*64}}

    def check(self,before=None,after=None,role="author",bounds=None):
        return continued.user_transition(before or self.before,after or self.after,self.users,role,*(bounds or self.bounds))

    def test_only_exact_request_actor_advancing_heartbeat_is_attributed(self):
        result=self.check();self.assertEqual(len(result),1);self.assertEqual(result[0]["columns"],["last_active"])
        self.assertEqual(self.check(after=self.before),[])
        for role in driver.ROLES:
            after=deepcopy(self.before);after[role]=self.row("2026-10-16T08:01:00")
            self.assertEqual(self.check(after=after,role=role)[0]["name"],role)

    def test_actual_local_naive_timestamp_converts_with_pinned_fallback_without_changing_bytes(self):
        native={"type":"datetime","value":"2026-10-16T13:43:58.138920"};original=deepcopy(native)
        self.assertEqual(continued._active(native).isoformat(),"2026-10-16T08:13:58.138920+00:00");self.assertEqual(native,original)
        with self.assertRaises(AssertionError):continued._active(native,timezone_name="UTC")
        with self.assertRaises(AssertionError):continued._active({"type":"datetime","value":"2026-10-16T13:43:58.138920+05:30"})

    def test_native_observer_refuses_changed_configured_or_effective_timezone_before_user_read(self):
        for configured,effective in (("UTC","UTC"),("Asia/Kolkata","Asia/Kolkata"),("","Asia/Kolkata"),(None,"UTC")):
            calls=[]
            fake=SimpleNamespace(db=SimpleNamespace(sql=lambda query,**kwargs:calls.append(query) or [{"value":configured}]),utils=SimpleNamespace(get_system_timezone=lambda:effective))
            with patch.object(continued,"verify_installed_session_source"),patch.object(continued,"_independent",side_effect=lambda read:read(fake)),self.assertRaises(AssertionError):
                continued.observe_users({"users":self.users})
            self.assertEqual(len(calls),1);self.assertNotIn("tabUser",calls[0])
        names=[row["user"] for row in self.users.values()]
        def sql(query,values=None,**kwargs):
            return [{"value":None}] if "tabSingles" in query else [{"name":name,"last_active":datetime(2026,10,16,13,43,58)} for name in names]
        fake=SimpleNamespace(db=SimpleNamespace(sql=sql),utils=SimpleNamespace(get_system_timezone=lambda:"Asia/Kolkata"))
        with patch.object(continued,"verify_installed_session_source"),patch.object(continued,"_independent",side_effect=lambda read:read(fake)):
            observed=continued.observe_users({"users":self.users})
        self.assertIsNone(observed["timezone"]["configured"]);self.assertEqual(set(observed["users"]),set(names))

    def test_other_user_extra_column_last_ip_and_modified_are_refused(self):
        for change in (lambda after:after["outsider"].update(self.row("2026-10-16T08:01:00")),
                lambda after:after["author"]["columns"].update(modified="changed"),
                lambda after:after["author"]["columns"].update(last_ip="changed"),
                lambda after:after["author"]["columns"].update(extra="changed"),
                lambda after:after.update(foreign=self.row("2026-10-16T08:01:00"))):
            after=deepcopy(self.after);change(after)
            with self.assertRaises((AssertionError,ValueError)):self.check(after=after)

    def test_typed_hash_old_row_and_actual_utc_time_bounds_are_strict(self):
        for change in (lambda after:after["author"]["last_active"].update(value="2026-10-16T08:00:00"),
                lambda after:after["author"]["last_active"].update(type="str"),
                lambda after:after["author"]["columns"].update(last_active="wrong")):
            after=deepcopy(self.after);change(after)
            with self.assertRaises(AssertionError):self.check(after=after)
        for bounds in (("2026-10-16T08:01:01+00:00",self.bounds[1]),(self.bounds[0],"2026-10-16T08:00:59+00:00"),
                ("2026-10-16T08:00:59",self.bounds[1])):
            with self.assertRaises((AssertionError,ValueError)):self.check(bounds=bounds)
        before=deepcopy(self.before);before["author"]["columns"]["modified"]="substituted-old-row"
        with self.assertRaises(AssertionError):self.check(before=before)


class ContinuationTests(unittest.TestCase):
    def setUp(self):
        from .test_ricky_company_proposal_acceptance_source import ProposalAcceptanceTests
        self.original=ProposalAcceptanceTests();self.original.setUp();self.addCleanup(self.original.doCleanups)
        self.path=self.original.path;value=manifest(self.path);stage=value["stages"][driver.KEY]
        stage.update(status="failed",cases={case:{"status":"declared","action":action} for case,action in driver.CASES.items()})
        stage.pop("commercial");stage.pop("estimate")
        value["native"]["role"]="fixture-role"
        value["inputs"]["citation"].update(revision_id="REV-"+"a"*32,excerpt_sha256="b"*64,source_sha256="c"*64)
        self.users=value["users"];self.name=self.users["author"]["user"]
        before_users={self.users[role]["user"]:HeartbeatTests.row("2026-10-16T07:00:00") for role in driver.ROLES}
        self.before={"User":{name:row["columns"] for name,row in before_users.items()},"Custom DocPerm":{},"Cipher Ricky Run":{},"Quotation":{}}
        baseline_path=self.path.parent/"proposal-r14-baseline.secret.json";self.config={"raw_sha256":"c"*64}
        write_private(baseline_path,{"inventory":self.before,"config":self.config});stage["baseline_sha256"]=driver.history._digest_bytes(baseline_path)
        stat=baseline_path.stat();lower=datetime.fromtimestamp(stat.st_mtime_ns/1e9,timezone.utc)
        self.current=deepcopy(before_users);self.current[self.name]=HeartbeatTests.row((lower+timedelta(seconds=1)).replace(tzinfo=None).isoformat())
        wire=[{"at":(lower+timedelta(seconds=index+2)).isoformat(),"method":"POST" if index==2 else "GET","status":403 if index==2 else 200,
            "operation_id":continued.OPERATION if index==2 else None} for index in range(3)]
        write_private(self.path.parent/"wire-observations.secret.json",wire)
        journal=Journal(self.path.parent);row=journal.prepare(continued.COMMAND_KEY,"author",driver.COMMERCIAL+"create_proposal",{"company":value["company"],"pursuit_id":value["inputs"]["pursuit"]["id"],"composition":driver._composition(value)})
        row["operation_id"]=continued.OPERATION;row["payload"]["operation_id"]=continued.OPERATION;row["payload_sha256"]=sha(row["payload"])
        row["attempts"]=[{"status":403,"refusal":"response_schema_or_status_refused","response_observation":wire[-1]}];write_private(journal.path,journal.rows)
        write_private(self.path,value)
        self.provenance=self.original.root/"heartbeat.secret.json";write_private(self.provenance,{"baseline_stat":{"mtime_ns":stat.st_mtime_ns,"ctime_ns":stat.st_ctime_ns,"mtime_utc":lower.isoformat()},"wire_observations":wire})
        self.supp_before=deepcopy(self.before)
        for name,row in self.current.items():self.supp_before["User"][name]=deepcopy(row["columns"])
        self.after=deepcopy(self.supp_before);self.after["Custom DocPerm"]["select-only"]={"role":"exact"}
        self.before_path=self.original.root/"supp-before.secret.json";write_private(self.before_path,self.supp_before)
        self.supplement=self.original.root/"supplement.secret.json";self.reconciled=self.original.root/"supplement-reconciled.secret.json"
        files={str(path.relative_to(self.path.parent)):driver.history._digest_bytes(path) for path in self.path.parent.rglob("*") if path.is_file()}
        supplement={"schema":"cipher.fixture.ricky.company.account-select.v1","status":"committed","company":value["company"],"role":value["native"]["role"],"author":self.name,
            "failed_directory":str(self.path.parent),"failed_files":files,"before_path":str(self.before_path),"before_sha256":driver.history._digest_bytes(self.before_path),
            "observed_after_sha256":sha(self.after),"grants":{"Account":["select"]},"business_master_writes":False,"added_permission_names":["select-only"],"account":"Debtors - CSA","config_sha256":self.config["raw_sha256"]}
        write_private(self.supplement,supplement)
        write_private(self.reconciled,{"status":"passed","committed_record":str(self.supplement),"committed_record_sha256":driver.history._digest_bytes(self.supplement),
            "original_failed_files_unchanged":True,"old_rows_unchanged":True,"effective_select_only":True,"permissions_added":1,"account":"Debtors - CSA"})
        self.destination=self.path.parent.parent/"company-proposals-r14-continuation"
        self.raw={p:p.read_bytes() for p in self.path.parent.rglob("*") if p.is_file()}

    def prepare(self,after=None):
        checksums={"heartbeat_provenance":driver.history._digest_bytes(self.provenance),"supplement":driver.history._digest_bytes(self.supplement),"supplement_reconciliation":driver.history._digest_bytes(self.reconciled)}
        with patch.object(driver.native,"_fixture",side_effect=manifest),patch.object(driver.recovery,"_only_active"),patch.object(driver,"_config",return_value=self.config), \
                patch.object(continued,"observe_users",return_value={"users":self.current,"timezone":continued.TIMEZONE_POLICY}),patch.object(continued,"_absence",return_value={"inventory":after or self.after,"receipt_absent":True,"at":timestamp()}):
            result=continued.prepare_company_proposal_continuation(self.path,self.destination,self.provenance,self.supplement,self.reconciled,evidence_sha256=checksums)
        return Path(result["private_manifest"])

    def test_new_journal_preserves_original_uuid_payload_artifacts_cookies_and_links(self):
        path=self.prepare();value=manifest(path);proof=continued._declaration(value)
        self.assertEqual(value["stages"][driver.KEY]["status"],"continuation_prepared");self.assertEqual(proof["status"],"prepared")
        self.assertEqual(Journal(path.parent).rows,Journal(self.path.parent).rows)
        for old,raw in self.raw.items():
            self.assertEqual(old.read_bytes(),raw);self.assertEqual((path.parent/"failed-original"/old.relative_to(self.path.parent)).read_bytes(),raw)
        for role in driver.ROLES:self.assertEqual((path.parent/(role+".cookies.secret")).read_bytes(),(self.path.parent/(role+".cookies.secret")).read_bytes())
        self.assertEqual(continued.preservation_changes(value,self.before,self.after),[])
        with self.assertRaises(ValueError):self.prepare()

    def test_no_supplement_after_or_old_row_drift_can_be_adopted(self):
        bad=deepcopy(self.after);bad["User"][self.name]["modified"]="foreign"
        with self.assertRaises(AssertionError):self.prepare(bad)
        self.assertFalse(self.destination.exists())

    def test_original_uuid_payload_and_file_tampering_are_refused(self):
        path=self.prepare();original=manifest(path)
        for change in (lambda value:value["stages"][continued.KEY]["original_command"].update(operation_id="new-uuid"),
                lambda value:value["stages"][continued.KEY]["initial_heartbeat"]["before_columns"][self.name].update(modified="changed"),
                lambda value:value["stages"][driver.KEY]["identities"].update(estimate_line="reallocated"),
                lambda value:value["stages"][continued.KEY]["initial_heartbeat"]["after_users"].pop(self.users["alias"]["user"])):
            bad=deepcopy(original);change(bad)
            with self.assertRaises(AssertionError):continued._declaration(bad)
        cookie=path.parent/"author.cookies.secret";cookie.write_bytes(b"replacement")
        with self.assertRaises(AssertionError):continued._declaration(original)

    def test_original_admitted_case_or_successful_receipt_attempt_cannot_continue(self):
        value=manifest(self.path);value["stages"][driver.KEY]["cases"]["scope-r14"]["status"]="admitted"
        with self.assertRaises(ValueError):continued.original_command(value)
        value=manifest(self.path);journal=Journal(self.path.parent);journal.rows[0]["attempts"].append({"status":200});write_private(journal.path,journal.rows)
        with self.assertRaises(ValueError):continued.original_command(value)

    def test_wire_observations_are_saved_before_heartbeat_assertions_and_no_retry(self):
        path=self.prepare();value=manifest(path);client=SimpleNamespace(path=path,value=value,work=path.parent,role="author",last_wire_observation={"status":200})
        later=deepcopy(self.current);later[self.name]["columns"]["modified"]="unexpected"
        snapshot=lambda users:{"started_at":timestamp(),"completed_at":timestamp(),"timezone":continued.TIMEZONE_POLICY,"users":users}
        calls=[]
        def send(*args,**kwargs):calls.append((args,kwargs));return 200,{"message":"observed"},.1
        with patch.object(continued,"observe_users",side_effect=[snapshot(self.current),snapshot(later)]),self.assertRaises(AssertionError):
            continued.observed_wire(client,send,"GET","/api/method/cipher_aec.api.v1.session")
        saved=manifest(path)["stages"][continued.KEY]["heartbeats"]
        self.assertEqual(len(calls),1);self.assertEqual(saved[0]["after"]["users"],later);self.assertNotIn("status",saved[0])
        with self.assertRaises(AssertionError):continued.preservation_changes(manifest(path),self.before,self.after)

    def test_wire_actual_exception_is_retained_without_new_effect_or_retry(self):
        path=self.prepare();client=SimpleNamespace(path=path,value=manifest(path),work=path.parent,role="author",last_wire_observation=None)
        snapshot={"started_at":timestamp(),"completed_at":timestamp(),"timezone":continued.TIMEZONE_POLICY,"users":self.current}
        with patch.object(continued,"observe_users",return_value=snapshot),self.assertRaisesRegex(RuntimeError,"original failure"):
            continued.observed_wire(client,lambda *a,**k:(_ for _ in ()).throw(RuntimeError("original failure")),"GET","/api/method/cipher_aec.api.v1.session")
        entry=manifest(path)["stages"][continued.KEY]["heartbeats"][0]
        self.assertEqual(entry["wire_error"]["error_type"],"RuntimeError");self.assertNotIn("status",entry)

    def test_independent_observer_cleans_only_its_connection_and_refuses_cleanup_failure(self):
        import threading
        calls=[];owner=threading.get_ident()
        class Local:
            site="synthetic"
        fake=SimpleNamespace(local=Local(),init=lambda **kwargs:calls.append(("init",threading.get_ident())),connect=lambda:calls.append(("connect",threading.get_ident())),
            db=SimpleNamespace(rollback=lambda:calls.append(("rollback",threading.get_ident()))),destroy=lambda:calls.append(("destroy",threading.get_ident())))
        with patch.dict("sys.modules",{"frappe":fake}):self.assertEqual(continued._independent(lambda frappe:"actual-read"),"actual-read")
        self.assertEqual([name for name,_ in calls],["init","connect","rollback","destroy"]);self.assertTrue(all(thread!=owner for _,thread in calls))
        fake.db.rollback=lambda:(_ for _ in ()).throw(RuntimeError("cleanup"))
        with patch.dict("sys.modules",{"frappe":fake}),self.assertRaises(AssertionError):continued._independent(lambda frappe:"read")

    def test_missing_evidence_or_original_artifact_set_cannot_be_deleted(self):
        path=self.prepare();value=manifest(path)
        for key in ("heartbeat_provenance","supplement","supplement_reconciliation","supplement_before"):
            bad=deepcopy(value);del bad["stages"][continued.KEY]["evidence"][key]
            with self.assertRaises(ValueError):continued._declaration(bad)
        bad=deepcopy(value);del bad["stages"][continued.KEY]["failed_files"]["wire-observations.secret.json"]
        with self.assertRaises(AssertionError):continued._declaration(bad)
        extra=self.path.parent/"additional-original.secret.json";write_private(extra,{"extra":"retained"})
        with self.assertRaises(AssertionError):continued._declaration(value)

    def test_installed_session_controller_hash_is_checked_from_actual_file(self):
        source=self.original.root/"sessions.py";source.write_bytes(b"actual installed source")
        with patch.object(continued,"import_module",return_value=SimpleNamespace(__file__=str(source))),patch.object(continued,"SOURCE_SHA256",continued.hashlib.sha256(source.read_bytes()).hexdigest()):
            continued.verify_installed_session_source();source.write_bytes(b"different installed source")
            with self.assertRaises(AssertionError):continued.verify_installed_session_source()

    def test_real_http_journal_lifecycle_appends_original_response_and_new_estimate_without_losing_manifest(self):
        path=self.prepare();value=manifest(path);owner=value["users"]["author"];commercial_id=str(uuid4());revision_id=str(uuid4());estimate_id=str(uuid4())
        common={"company":value["company"],"author_person":owner["person"],"revision_number":1}
        proposal={**common,"id":commercial_id,"pursuit":value["inputs"]["pursuit"]["id"],"quotation":"Synthetic Quotation","party_type":"Customer","party_id":"Synthetic Customer",
            "title":"Manual synthetic draft","current_revision":revision_id,"native_fingerprint":"a"*64,"native_version":"one"}
        revision={**common,"id":revision_id,"proposal":commercial_id,"predecessor":None,"status":"draft","composition":driver._composition(value),
            "pricing":{"policy":"native-no-tax-no-discount-half-up-v1","currency_exponent":2,"lines":[],"total":"0"},"units":{},"native_fingerprint":"a"*64,
            "currency_policy":{"currency":"USD","currency_exponent":2,"fraction_units":100,"native_currency_version":"one","price_list":{"name":"r14","version":"one","currency":"USD"}},
            "company_policy":{"base_currency":"USD","native_company_version":"one"},
            "native":{"id":"Synthetic Quotation","version":"one","company":value["company"],"quotation_to":"Customer","party_name":"Synthetic Customer","opportunity":"Synthetic Opportunity",
                "currency":"USD","valid_till":"2026-12-31","terms":"Manual","docstatus":0,"totals":{},"items":[],"taxes":[],"selling_price_list":"r14","price_list_currency":"USD"}}
        estimate={"id":estimate_id,"company":value["company"],"scope_type":"Company","project":None,"author_person":owner["person"],"author_user":owner["user"],"created_at":timestamp(),
            "status":"draft","title":"Manual estimate","currency":"USD","pricing_date":"2026-10-16","revision_number":0,"current_revision":None,"pursuit_id":value["inputs"]["pursuit"]["id"]}
        calls=[]
        def wire(client,method,route,values=None,**kwargs):
            calls.append((method,route,deepcopy(values)));operation={"id":kwargs.get("operation"),"status":"succeeded","replayed":False}
            if route.endswith(".session"):data={"site_mode":"synthetic","user":owner["user"],"person":{"id":owner["person"]},"csrf_token":"fixture-only-token"}
            elif route.endswith(".create_proposal"):data={"proposal":proposal,"revision":revision,"operation":operation}
            else:data={"estimate":estimate,"history_id":"history-one","operation":operation}
            client.last_wire_observation={"at":timestamp(),"status":200,"method":method,"path":route,"operation_id":kwargs.get("operation"),"body_sha256":"a"*64}
            return 200,{"message":self.original._envelope(data=data)},.01
        snapshot={"started_at":timestamp(),"completed_at":timestamp(),"timezone":continued.TIMEZONE_POLICY,"users":self.current}
        with patch.object(driver.native,"_fixture",side_effect=manifest),patch.object(continued,"observe_users",return_value=snapshot),patch.object(driver.http._HTTP,"_wire",new=wire):
            rpc=driver._ProposalHTTP(path,"http://127.0.0.1:18886");rpc.login()
            row=continued.original_command(manifest(self.path));fields={key:item for key,item in row["payload"].items() if key!="operation_id"}
            response=rpc.call(row["method"],fields,key=continued.COMMAND_KEY)["data"]
            driver._update(path,commercial=response)
            created=rpc.command("r14-manual-estimate",driver.http.EST+"create_estimate",{"title":"Manual estimate","currency":"USD","pricing_date":"2026-10-16","pursuit_id":value["inputs"]["pursuit"]["id"]})
        current=manifest(path);self.assertEqual(current["stages"][driver.KEY]["commercial"],response);self.assertEqual(created["estimate"],estimate)
        self.assertEqual(len(current["stages"][continued.KEY]["heartbeats"]),3);continued._declaration(current)
        rows=Journal(path.parent).rows;self.assertEqual(len(rows),2);self.assertEqual(len(rows[0]["attempts"]),2);self.assertEqual(rows[0]["operation_id"],continued.OPERATION)
        self.assertNotEqual(rows[1]["operation_id"],continued.OPERATION);self.assertEqual(len(calls),3);self.assertEqual(self.path.read_bytes(),self.raw[self.path])
        self.assertEqual(continued.preservation_changes(current,self.before,self.after),[])

    def test_old_helper_wire_path_remains_unchanged_without_continuation_declaration(self):
        fake=driver._ProposalHTTP.__new__(driver._ProposalHTTP);fake.value={"stages":{}}
        with patch.object(driver.http._HTTP,"_wire",return_value="legacy") as wire:
            self.assertEqual(driver._ProposalHTTP._wire(fake,"GET","path"),"legacy")
        wire.assert_called_once_with("GET","path")

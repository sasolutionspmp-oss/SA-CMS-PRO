"""Host tests for the separate R13 native driver; no site/network execution."""
from copy import deepcopy
from http.cookiejar import LWPCookieJar
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import uuid4

from . import ricky_company_history_acceptance as driver
from .ricky_company_acceptance_support import Journal, manifest, sha, write_private
from . import test_ricky_company_http as http


class CompanyHistoryNativeFixtureSourceTests(unittest.TestCase):
    def setUp(self):
        from .test_ricky_company_acceptance_source import CompanyAcceptanceSourceTests
        self.f = CompanyAcceptanceSourceTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        temporary = tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.destination = Path(temporary.name)/"history-r13"
        self.original = self.f.admission();self.f.fixture["inputs"]["ready"] = True
        self.f.fixture["preservation"] = {"setup_old_rows_unchanged":True}
        self.f.fixture["stages"]["original_duty_states"] = {"document.read":{"active":1,"fields":{"active":driver.native._native_scalar(1)}}}
        write_private(self.f.path,self.f.fixture)
        for role in ("author","alias","outsider"):
            path=self.f.work/(role+".cookies.secret");LWPCookieJar(str(path)).save(ignore_discard=True,ignore_expires=True);path.chmod(0o600)
        write_private(self.f.work/"preservation-before.secret.json",{})
        self.original_files = {path.name:path.read_bytes() for path in self.f.work.iterdir() if path.is_file()}
        self.inventory = {table:{} for table in (*driver.native.RICKY_TABLES,"Cipher History Event","Cipher Command Receipt")}
        self.rollbacks=[]
        self.frappe=SimpleNamespace(conf={"pause_scheduler":True},get_site_path=lambda *args:str(self.f.work.parent),
            db=SimpleNamespace(sql=lambda *a,**k:[],rollback=lambda:self.rollbacks.append(True)))
        self.context=SimpleNamespace(require_effects_enabled=lambda:None)
        with patch.dict("sys.modules",{"frappe":self.frappe,"cipher_aec.governance.context":self.context}), \
                patch.object(driver.native,"_fixture",side_effect=manifest),patch.object(driver.native,"_inventory",return_value=self.inventory), \
                patch.object(driver.recovery,"_only_active"),patch.object(driver.recovery,"_config",return_value={"present":False,"value":None}):
            result=driver.prepare_company_history_fixture(self.f.path,self.destination)
        self.path=Path(result["private_manifest"])

    def assert_original_unchanged(self):
        for name,raw in self.original_files.items():self.assertEqual((self.f.work/name).read_bytes(),raw)

    def test_prepare_copies_references_and_private_cookies_without_new_identities_or_original_edits(self):
        value=manifest(self.path)
        self.assertEqual(value["fixture_id"],self.f.fixture["fixture_id"])
        self.assertEqual(value["native"],self.f.fixture["native"])
        self.assertEqual(value["inputs"],self.f.fixture["inputs"])
        self.assertEqual(value["intents"],{})
        self.assertEqual(value["journal_directory"],str(self.destination))
        self.assertEqual(value["stages"][driver.KEY]["request"],self.original["payload"]["request"])
        for role in ("author","alias","outsider"):
            self.assertEqual((self.destination/(role+".cookies.secret")).read_bytes(),self.original_files[role+".cookies.secret"])
            self.assertEqual(value["users"][role]["password"],"DISABLED_R13_NO_LOGIN")
        self.assertFalse((self.destination/"http-journal.secret.json").exists())
        self.assert_original_unchanged()

    def test_cookie_loss_unsafe_permissions_and_fresh_login_refuse_before_any_wire(self):
        rpc=driver._HistoryHTTP(self.path,"http://not-used.invalid")
        with patch.object(rpc,"_wire",side_effect=AssertionError("No login/network allowed")) as wire:
            with self.assertRaises(ValueError):rpc.login(fresh=True)
            cookie=self.destination/"alias.cookies.secret";cookie.chmod(0o644)
            with self.assertRaises(ValueError):rpc.login("alias")
            cookie.chmod(0o600);cookie.unlink()
            with self.assertRaises(ValueError):rpc.login("alias")
            wire.assert_not_called()
        self.assert_original_unchanged()

    def test_copied_cookie_with_wrong_actual_session_user_refuses_without_login_or_start(self):
        rpc=driver._HistoryHTTP(self.path,"http://not-used.invalid")
        payload={"message":{"data":{"site_mode":"synthetic","user":"wrong@example.test",
            "person":{"id":rpc.value["users"]["author"]["person"]},"csrf_token":"HOST_ONLY"}}}
        with patch.object(rpc,"_wire",return_value=(200,payload,0)) as wire:
            with self.assertRaisesRegex(AssertionError,"exact synthetic User/Person"):
                rpc.login("author")
        self.assertEqual(wire.call_args.args[:2],("GET","/api/method/cipher_aec.api.v1.session"))
        self.assertEqual(wire.call_count,1)
        self.assertFalse((self.destination/"http-journal.secret.json").exists())
        self.assert_original_unchanged()

    def test_missing_cookie_provenance_cannot_fall_through_to_new_login(self):
        value=manifest(self.path);value["stages"][driver.KEY]["cookie_sha256"].pop("alias")
        write_private(self.path,value);(self.destination/"alias.cookies.secret").unlink()
        rpc=driver._HistoryHTTP(self.path,"http://not-used.invalid")
        with patch.object(rpc,"_wire",side_effect=AssertionError("A new login was attempted")) as wire:
            with self.assertRaises(ValueError):rpc.login("alias")
            wire.assert_not_called()

    def test_original_file_or_cookie_change_is_detected_before_driver_phase(self):
        (self.f.work/"http-journal.secret.json").write_text("[]\n")
        with patch.object(driver.native,"_fixture",side_effect=manifest):
            with self.assertRaisesRegex(AssertionError,"original fixture"):
                driver._value(self.path)

    def test_actual_http_session_start_receipt_capture_and_replay_preserve_manifest_and_new_uuid(self):
        run_id=str(uuid4());receipts={};events=[];seen=set();wire_paths=[]
        def wire(rpc,method,path,values=None,**kwargs):
            wire_paths.append(path);self.assertNotEqual(path,"/api/method/login")
            request_id=str(uuid4());meta={"request_id":request_id,"api_version":"v1","server_time":"2026-10-16T00:00:00+00:00"}
            envelope={"schema":"cipher.api.v1","request_id":request_id,"meta":meta}
            if path.endswith("api.v1.session"):
                owner=rpc.value["users"][rpc.role]
                envelope["data"]={"site_mode":"synthetic","user":owner["user"],"person":{"id":owner["person"]},"csrf_token":"HOST_ONLY"}
            elif path.endswith("start_read"):
                operation=values["operation_id"];replayed=operation in seen;seen.add(operation)
                body={**deepcopy(self.original["start"]),"id":run_id,"selection":deepcopy(values["request"])}
                envelope["data"]={**body,"operation":{"id":operation,"status":"succeeded","replayed":replayed}}
                receipts[sha({"person":rpc.value["users"]["author"]["person"],"operation_id":operation})]=SimpleNamespace(
                    person=rpc.value["users"]["author"]["person"],company=rpc.value["company"],scope_type="Company",project=None,
                    command="ricky.company.read.start.v1",state="Succeeded",result_json=http.json.dumps(body,sort_keys=True,separators=(",",":"),ensure_ascii=False),result_hash=sha(body))
                row={"name":"native-start-event","scope_type":"Company","company":rpc.value["company"],"project":None,
                    "actor_person":rpc.value["users"]["author"]["person"],"event":"ricky.company.read.start.accepted",
                    "subject_type":"Cipher Ricky Run","subject_id":run_id,"operation_id":operation,"previous_hash":""}
                details={"action":"aec.pursuit.lookup","status":"queued"}
                payload={"scope_type":"Company","actor":row["actor_person"],"company":row["company"],"project":None,
                    **{key:row[key] for key in ("event","subject_type","subject_id","operation_id","previous_hash")},"details":details}
                from cipher_aec.api.contracts import canonical_json
                row.update(details_json=canonical_json(details),event_payload=canonical_json(payload),event_hash=sha(payload));events[:]=[row]
            else:raise AssertionError("Unexpected host transport route")
            return 200,{"message":envelope},0
        def run(value,case):
            intent=value["intents"][case]
            return {"id":run_id,"user":value["users"]["author"]["user"],"person":value["users"]["author"]["person"],
                "company":value["company"],"authority":{"original":"HOST_ONLY"},"request":intent["payload"]["request"],
                "original_session_reference":"d"*64}
        self.frappe.db.get_value=lambda doctype,name,*args,**kwargs:receipts.get(name)
        visibility={role:{"ids":[],"total":0,"cursor_last_ids":[]} for role in ("author","alias","outsider")}
        with patch.dict("sys.modules",{"frappe":self.frappe}),patch.object(driver.native,"_fixture",side_effect=manifest), \
                patch.object(driver.native,"_run",side_effect=run),patch.object(driver,"_events",side_effect=lambda target:deepcopy(events)), \
                patch.object(driver.recovery,"_only_active"),patch.object(driver,"_preserved"), \
                patch.object(driver,"_visibility",return_value=visibility),patch.object(driver._HistoryHTTP,"_wire",new=wire):
            result=driver.start_company_history_case(self.path,"http://not-used.invalid")
            value=manifest(self.path);intent=value["intents"]["lookup"]
            self.assertEqual(result["status"],"admitted")
            self.assertNotEqual(intent["operation_id"],self.original["operation_id"])
            self.assertIn("start-lookup",value["stages"]["receipt_before"])
            self.assertIn("lookup",value["stages"]["original_run_bindings"])
            self.assertEqual(len(value["stages"]["http_calls"]),1)
            receipt_before=deepcopy(value["stages"]["receipt_before"])
            rpc=driver._HistoryHTTP(self.path,"http://not-used.invalid");rpc.login()
            replay=rpc.call(http.RICKY+"start_read",{key:item for key,item in intent["payload"].items() if key!="operation_id"},key="start-lookup")
            self.assertTrue(replay["data"]["operation"]["replayed"])
            restored=manifest(self.path)
            self.assertEqual(restored["stages"]["receipt_before"],receipt_before)
            self.assertEqual(restored["stages"][driver.KEY]["status"],"admitted")
            self.assertEqual(len(restored["stages"]["http_calls"]),2)
            rows=Journal(self.destination).rows
            self.assertEqual(len(rows),1);self.assertEqual(rows[0]["operation_id"],intent["operation_id"])
            self.assertEqual(len(rows[0]["attempts"]),2)
            self.assertEqual(rows[0]["attempts"][0]["envelope"]["data"]["operation"]["replayed"],False)
            self.assertEqual(rows[0]["attempts"][1]["envelope"]["data"]["operation"]["replayed"],True)
        self.assertTrue(any(path.endswith("api.v1.session") for path in wire_paths))
        self.assert_original_unchanged()

    def test_mixed_visibility_compares_current_native_sets_and_totals_without_blanket_zero(self):
        expected={"author":{"ids":["own-new","other-domain"],"creation":{}},
            "alias":{"ids":["other-domain"],"creation":{}},"outsider":{"denied":"not_found"}}
        class LocalHTTP:
            def __init__(inner,*args):pass
            def login(inner,role):inner.role=role
            def call(inner,method,fields,**kwargs):
                state=expected[inner.role]
                return {"error":{"code":state["denied"]}} if "denied" in state else {"data":{"items":[{"id":name} for name in state["ids"]],"total":len(state["ids"]),"next_cursor":None}}
        with patch.object(driver,"_value",return_value=manifest(self.path)),patch.object(driver,"_visible_native",side_effect=lambda value,role:expected[role]), \
                patch.object(driver,"_HistoryHTTP",LocalHTTP):
            observed=driver._visibility(self.path,"http://not-used.invalid",None)
        self.assertEqual(observed["author"]["total"],2);self.assertEqual(observed["alias"]["total"],1)
        self.assertEqual(observed["outsider"],{"denied":"not_found"})

    def test_stop_network_failure_restores_exact_duty_and_retains_failed_separate_phase(self):
        value=manifest(self.path);value["stages"][driver.KEY]["status"]="executed";write_private(self.path,value)
        original={"active":1,"fields":{"active":driver.native._native_scalar(1)}};calls=[]
        class FailingHTTP:
            def __init__(inner,*args):inner.value=manifest(self.path)
            def login(inner):pass
            def call(inner,*args,**kwargs):raise RuntimeError("Explicit host transport failure")
        with patch.dict("sys.modules",{"frappe":self.frappe}),patch.object(driver.native,"_fixture",side_effect=manifest), \
                patch.object(driver.native,"_run",return_value={"id":"host-run"}), \
                patch.object(driver.native,"_capture_duty_outage",return_value=original), \
                patch.object(driver.native,"_duty",side_effect=lambda value,ability,active,saved:calls.append((active,deepcopy(saved)))), \
                patch.object(driver.native,"_independent_duty_readback") as readback,patch.object(driver,"_HistoryHTTP",FailingHTTP), \
                patch.object(driver,"saved_intent",return_value={"payload":{}}):
            with self.assertRaisesRegex(RuntimeError,"host transport"):
                driver.finish_company_history_case(self.path,"http://not-used.invalid")
        self.assertEqual(calls,[(0,original),(1,original)])
        self.assertEqual(readback.call_args_list[-1].args[-1],original)
        failed=manifest(self.path)["stages"][driver.KEY]
        self.assertEqual(failed["status"],"failed");self.assertEqual(failed["error"]["error_type"],"RuntimeError")
        self.assert_original_unchanged()

    def test_failed_phase_cannot_be_reset_by_another_start_or_worker_readback(self):
        value=manifest(self.path);value["stages"][driver.KEY]["status"]="failed";write_private(self.path,value)
        with patch.dict("sys.modules",{"frappe":self.frappe}),patch.object(driver.native,"_fixture",side_effect=manifest):
            with self.assertRaisesRegex(RuntimeError,"one-shot"):
                driver.start_company_history_case(self.path,"http://not-used.invalid")
            with self.assertRaisesRegex(RuntimeError,"one-shot"):
                driver.verify_company_history_execution(self.path)
        self.assert_original_unchanged()

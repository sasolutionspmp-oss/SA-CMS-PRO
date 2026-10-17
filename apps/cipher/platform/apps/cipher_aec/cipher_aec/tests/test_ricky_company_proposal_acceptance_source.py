"""Focused host checks for the opt-in R14 native procedures; no native calls."""
from copy import deepcopy
from pathlib import Path
from datetime import datetime
import json
from http.cookiejar import LWPCookieJar
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4
import tempfile
import unittest

from cipher_aec.tests import ricky_company_proposal_prerequisites as prerequisites
from cipher_aec.tests import ricky_company_proposal_acceptance as driver
from cipher_aec.tests.ricky_company_acceptance_support import Journal,manifest,sha,write_private


class ProposalPrerequisiteTests(unittest.TestCase):
    def test_closed_operator_plan_and_dates(self):
        plan = {"price_list": "R14 synthetic selling", "fiscal_year": "R14 synthetic 2026",
            "year_start": "2026-01-01", "year_end": "2026-12-31", "pricing_date": "2026-10-16"}
        self.assertEqual(prerequisites.operator_plan(plan), plan)
        for bad in ({**plan, "unexpected": True}, {**plan, "year_end": "2027-12-31"},
                {**plan, "pricing_date": "2025-10-16"}, {**plan, "price_list": ""}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):prerequisites.operator_plan(bad)

    def test_price_list_controller_refusals_before_writes(self):
        facts = {"selling_default": "Standard Selling", "price_list_exists": False,
            "item_price_references": [], "comments": [], "communications": []}
        prerequisites.controller_preconditions(facts)
        for field, value in (("selling_default", ""), ("price_list_exists", True),
                ("item_price_references", ["orphan"]), ("comments", ["old"]),
                ("communications", ["old"])):
            with self.subTest(field=field), self.assertRaises(RuntimeError):
                prerequisites.controller_preconditions({**facts, field:value})

    def test_permission_datetime_is_typed_and_semantics_are_plain(self):
        row={"name":"one","parent":"Quotation","role":"fixture","permlevel":0,"read":1,
            "creation":datetime(2026,10,16,12,3,4),"modified":datetime(2026,10,16,12,3,5)}
        observed=prerequisites.permission_rows([row])
        self.assertEqual(observed["typed"]["one"]["creation"],{"type":"datetime","value":"2026-10-16T12:03:04"})
        self.assertEqual(observed["semantic"]["one"]["read"],1)
        self.assertEqual(observed["semantic"]["one"]["import"],0)
        json.dumps(observed,allow_nan=False)

    def test_exact_permission_copies_and_no_import_or_extra_grant(self):
        def rule(parent,role,**flags):return {"parent":parent,"role":role,"permlevel":0,**flags}
        defaults=[rule("Quotation","existing",read=1),rule("Price List","existing",read=1,select=1)]
        current={"q0":defaults[0],"p0":defaults[1],"q":rule("Quotation","fixture",read=1,select=1,write=1,create=1),
            "p":rule("Price List","fixture",read=1,select=1)}
        self.assertEqual(set(prerequisites.permission_additions({},current,defaults,"fixture")),set(current))
        for field in ("import","submit","delete","share"):
            changed=deepcopy(current);changed["q"][field]=1
            with self.subTest(field=field),self.assertRaises(AssertionError):prerequisites.permission_additions({},changed,defaults,"fixture")
        changed=deepcopy(current);changed["q0"]["read"]=0
        with self.assertRaises(AssertionError):prerequisites.permission_additions({},changed,defaults,"fixture")
        with self.assertRaises(AssertionError):prerequisites.permission_additions({}, {**current,"extra":rule("User","foreign",read=1)}, defaults,"fixture")

    def test_existing_permission_semantics_cannot_change(self):
        before={"old":{"parent":"Quotation","role":"existing","permlevel":0,"read":1}}
        after={**before,"q":{"parent":"Quotation","role":"fixture","permlevel":0,"read":1,"create":1,"write":1,"select":1},
            "p":{"parent":"Price List","role":"fixture","permlevel":0,"read":1,"select":1}}
        prerequisites.permission_additions(before,after,[],"fixture")
        after["old"]={**after["old"],"write":1}
        with self.assertRaises(AssertionError):prerequisites.permission_additions(before,after,[],"fixture")

    def test_exact_new_row_set_rejects_unrelated_native_additions(self):
        before={"Price List":{"old":{}},"Custom DocPerm":{}}
        after={"Price List":{"old":{},"r14":{}},"Custom DocPerm":{"grant":{}}}
        expected={"Price List":["r14"],"Custom DocPerm":["grant"]}
        self.assertEqual(prerequisites.new_row_attribution(before,after,expected),expected)
        for changed in ({**after,"Company":{"foreign":{}}},{**after,"Price List":{**after["Price List"],"extra":{}}}):
            with self.assertRaises(AssertionError):prerequisites.new_row_attribution(before,changed,expected)

    def test_empty_selling_default_needs_explicit_boolean_opt_in(self):
        facts={"selling_default":"","price_list_exists":False,"item_price_references":[],"comments":[],"communications":[]}
        with self.assertRaises(RuntimeError):prerequisites.controller_preconditions(facts)
        prerequisites.controller_preconditions(facts,allow_empty_default=True)
        plan={"price_list":"r14","fiscal_year":"r14","year_start":"2026-01-01","year_end":"2026-12-31","pricing_date":"2026-10-16"}
        self.assertTrue(prerequisites.operator_plan({**plan,"allow_native_selling_default":True})["allow_native_selling_default"])
        with self.assertRaises(ValueError):prerequisites.operator_plan({**plan,"allow_native_selling_default":"true"})

    def test_finite_property_setter_plan_and_customer_write_refusal(self):
        specs=prerequisites.selling_property_specs({"cust_master_name":"Customer Name","hide_tax_id":0,"editable_bundle_item_rates":0,"enable_discount_accounting":0})
        self.assertEqual(len(specs),13)
        self.assertEqual(specs["Customer-naming_series-reqd"]["value"],"0")
        self.assertEqual(specs["Packed Item-rate-read_only"]["value"],"1")
        self.assertEqual(specs["Sales Invoice Item-discount_account-mandatory_depends_on"]["value"],"")
        with self.assertRaises(RuntimeError):prerequisites.selling_property_specs({"cust_master_name":"Naming Series"})

    def _selling(self):
        stamp=datetime(2026,10,16,12)
        audit={"owner":"Administrator","modified_by":"Administrator","creation":stamp,"modified":stamp,"docstatus":0,"idx":0}
        specs=prerequisites.selling_property_specs({"cust_master_name":"Customer Name"})
        plan={"enabled":True,"singles":{"selling_price_list":"r14","enable_utm":"0"},
            "before_singles":{"selling_price_list":"","enable_utm":"0"},
            "defaults":{key:{"value":"r14" if key=="selling_price_list" else "0","retain":False,"before":{}} for key in prerequisites.DEFAULT_KEYS},
            "properties":{name:{"expected":spec,"before":{}} for name,spec in specs.items()}}
        after={"singles":{**plan["singles"],"modified":stamp.isoformat(),"modified_by":"Administrator"},
            "defaults":{key:[{**audit,"name":"new-"+key,"parent":"__default","parenttype":"__default","parentfield":"system_defaults",
                "defkey":key,"defvalue":item["value"]}] for key,item in plan["defaults"].items()},
            "properties":{name:{**audit,**spec,"module":None,"default_value":None,"row_name":None} for name,spec in specs.items()}}
        return plan,after,stamp

    def test_selling_transition_exact_semantics_and_native_audit_bounds(self):
        plan,after,stamp=self._selling()
        result=prerequisites.verify_selling_transition(plan,after,start=stamp,end=stamp)
        self.assertEqual(len(result["new_rows"]["Property Setter"]),13)
        self.assertEqual(len(result["new_rows"]["DefaultValue"]),6)
        self.assertEqual(set(result["changed_old"]["Singles"]),{"Selling Settings:selling_price_list","Selling Settings:enable_utm"})
        json.dumps(result,allow_nan=False)
        for mutate in (lambda value:value["singles"].update(enable_utm="1"),
                lambda value:value["singles"].update(unrelated="x"),
                lambda value:value["properties"]["Customer-naming_series-reqd"].update(value="1"),
                lambda value:value["properties"]["Customer-naming_series-reqd"].update(module="unexpected"),
                lambda value:value["defaults"]["selling_price_list"][0].update(defvalue="foreign"),
                lambda value:value["defaults"]["selling_price_list"][0].update(owner="foreign")):
            bad=deepcopy(after);mutate(bad)
            with self.assertRaises(AssertionError):prerequisites.verify_selling_transition(plan,bad,start=stamp,end=stamp)
        with self.assertRaises(AssertionError):prerequisites.verify_selling_transition(plan,after,start=datetime(2026,10,16,13),end=datetime(2026,10,16,14))

    def test_identical_default_row_cannot_be_replaced(self):
        plan,after,stamp=self._selling();key="territory";row=after["defaults"][key][0]
        plan["defaults"][key].update(retain=True,before={row["name"]:{field:prerequisites.native._native_scalar(value) for field,value in row.items()}})
        prerequisites.verify_selling_transition(plan,after,start=stamp,end=stamp)
        after["defaults"][key][0]["name"]="replacement"
        with self.assertRaises(AssertionError):prerequisites.verify_selling_transition(plan,after,start=stamp,end=stamp)

    def test_supported_permission_apis_explicitly_disable_observed_export_default(self):
        rows={};calls=[]
        def add(doctype,role,permlevel,ptype):
            self.assertEqual((role,permlevel,ptype),("fixture",0,"read"))
            rows[doctype]={"parent":doctype,"role":role,"permlevel":0,"read":1,"export":1}
        def update(doctype,role,permlevel,flag,value):
            calls.append((doctype,flag,value));rows[doctype][flag]=value
        prerequisites.exact_permission_grants("fixture",add,update)
        for doctype,grants in prerequisites.GRANTS.items():
            self.assertEqual({flag:rows[doctype][flag] for flag in prerequisites.FLAGS},{flag:int(flag in grants) for flag in prerequisites.FLAGS})
            self.assertEqual(len([row for row in calls if row[0]==doctype]),len(prerequisites.FLAGS))
            self.assertLess(calls.index((doctype,"export",0)),calls.index((doctype,"read",1)))
        prerequisites.permission_additions({},rows,[],"fixture")

    def test_corrected_declaration_requires_exact_restoration_and_authentic_failure(self):
        reference={"original_manifest":"/original/private.json","original_manifest_sha256":"a"*64,"fixture_id":"ricky-company-012345abcdef","company":"Synthetic","site":"explicit.synthetic"}
        plan={"explicit":"unchanged"};before={"Price List":{},"Custom DocPerm":{},"Old":{"row":{"digest":"exact"}}}
        failed={**reference,"schema":prerequisites.SCHEMA,"status":"failed","plan":plan,"before":before,
            "error":{"error_type":"AssertionError","error_message":"Only the exact new role/permission boundary is admitted."}}
        # These are effective rights from all roles; they do not establish row absence.
        reconcile={"recorded_status":"failed","old_row_changes":[],"matches_recorded_after":False,"price_list":{},"fiscal_year":{},
            "permissions":{doctype:{flag:True for flag in grants} for doctype,grants in prerequisites.GRANTS.items()},"at":"2026-10-16T00:00:00+00:00"}
        prerequisites.correction_preconditions(failed,reconcile,before,reference,plan)
        for bad in ({**reconcile,"recorded_status":"committed"},{**reconcile,"price_list":{"present":True}},
                {key:value for key,value in reconcile.items() if key!="old_row_changes"}):
            with self.assertRaises(ValueError):prerequisites.correction_preconditions(failed,bad,before,reference,plan)
        for current in ({**before,"Custom DocPerm":{"introduced":{}}},{**before,"Old":{"row":{"digest":"changed"}}}):
            with self.assertRaises(AssertionError):prerequisites.correction_preconditions(failed,reconcile,current,reference,plan)
        with self.assertRaises(AssertionError):prerequisites.correction_preconditions(failed,reconcile,before,{**reference,"site":"foreign"},plan)
        with self.assertRaises(AssertionError):prerequisites.correction_preconditions(failed,reconcile,before,reference,{"different":"plan"})
        with self.assertRaises(ValueError):prerequisites.correction_preconditions({**failed,"after":{}},reconcile,before,reference,plan)

    def test_native_property_deletion_audit_has_exact_subjects_columns_and_time(self):
        stamp=datetime(2026,10,16,12,0,0)
        plan={"properties":{"Customer-naming_series-hidden":{"before":{"Customer-naming_series-hidden":{}}}}}
        row={"name":"audit-one","creation":stamp,"modified":stamp,"owner":"Administrator","modified_by":"Administrator",
            "subject":"Property Setter Customer-naming_series-hidden","docstatus":0,"idx":0,"comment_type":"Deleted",
            "comment_email":"Administrator","comment_by":None,"published":0,"seen":0,"reference_doctype":"Property Setter",
            "reference_name":None,"reference_owner":None,"content":None,"ip_address":None,"_user_tags":None,"_comments":None,
            "_assign":None,"_liked_by":None}
        self.assertEqual(prerequisites.verify_property_deletion_comments(plan,[row],start=stamp,end=stamp),["audit-one"])
        for changes in ({"subject":"Property Setter foreign"},{"content":"unrelated"},{"reference_doctype":"Opportunity"},
                {"reference_name":"foreign"},{"comment_email":"other"},{"published":True},{"owner":"other"},
                {"creation":datetime(2026,10,15,12,0,0)},{"unexpected":"column"}):
            with self.subTest(changes=changes),self.assertRaises(AssertionError):
                prerequisites.verify_property_deletion_comments(plan,[{**row,**changes}],start=stamp,end=stamp)
        for rows in ([],[row,row]):
            with self.assertRaises(AssertionError):prerequisites.verify_property_deletion_comments(plan,rows,start=stamp,end=stamp)

    def test_audited_correction_is_bound_to_its_distinct_retained_failure(self):
        error="The prerequisite added an unrelated or unrecorded native row."
        reference={"company":"Synthetic","site":"isolated"};before={"Comment":{}};plan={"same":"plan"}
        failed={**reference,"schema":prerequisites.SCHEMA,"status":"failed","plan":plan,"before":before,
            "error":{"error_type":"AssertionError","error_message":error}}
        reconcile={"recorded_status":"failed","old_row_changes":[],"matches_recorded_after":False,"price_list":{},"fiscal_year":{},
            "permissions":{doctype:{flag:False for flag in grants} for doctype,grants in prerequisites.GRANTS.items()},"at":"retained"}
        prerequisites.correction_preconditions(failed,reconcile,before,reference,plan,expected_error=error)
        with self.assertRaises(ValueError):prerequisites.correction_preconditions(failed,reconcile,before,reference,plan)
        with self.assertRaises(AssertionError):
            prerequisites.correction_preconditions(failed,reconcile,{"Comment":{"uncommitted":{}}},reference,plan,expected_error=error)


class ProposalAcceptanceTests(unittest.TestCase):
    def setUp(self):
        from .test_ricky_company_acceptance_source import CompanyAcceptanceSourceTests
        from .test_ricky_company_service import CompanyFixtureBoundary
        self.f=CompanyAcceptanceSourceTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup);self.root=Path(temporary.name)
        self.destination=self.root/"r14";boundary=CompanyFixtureBoundary();citation=deepcopy(boundary.fixture.citation_value)
        self.f.fixture["inputs"]={"ready":True,"citation":citation,"pursuit":{"id":str(uuid4())},"units":[{"id":str(uuid4()),"revision":1}],
            "estimate":{"id":str(uuid4())},"rate":{"id":str(uuid4())},"conversion":{"id":str(uuid4())}}
        self.f.fixture["preservation"]={"setup_old_rows_unchanged":True};self.f.fixture["stages"]["original_duty_states"]={}
        write_private(self.f.path,self.f.fixture);write_private(self.f.work/"preservation-before.secret.json",{})
        for role in driver.ROLES:
            p=self.f.work/(role+".cookies.secret");LWPCookieJar(str(p)).save(ignore_discard=True,ignore_expires=True);p.chmod(0o600)
        self.originals={p.name:p.read_bytes() for p in self.f.work.iterdir() if p.is_file()}
        self.prerequisite=self.root/"prerequisite.secret.json"
        proof={"schema":prerequisites.SCHEMA,"status":"committed","fixture_id":self.f.fixture["fixture_id"],"company":self.f.fixture["company"],
            "original_manifest_sha256":driver.history._digest_bytes(self.f.path),"before":{},"after":{},"attributed_old_row_changes":[],
            "plan":{"price_list":"r14","fiscal_year":"r14-2026","year_start":"2026-01-01","year_end":"2026-12-31","pricing_date":"2026-10-16"}}
        write_private(self.prerequisite,proof)
        self.frappe=SimpleNamespace(get_site_path=lambda *args:str(self.root),db=SimpleNamespace(rollback=lambda:None))
        with patch.dict("sys.modules",{"frappe":self.frappe,"cipher_aec.governance.context":SimpleNamespace(require_effects_enabled=lambda:None)}), \
                patch.object(driver.native,"_fixture",side_effect=manifest),patch.object(driver.recovery,"_only_active"), \
                patch.object(driver.prerequisites,"inventory",return_value={}),patch.object(driver,"_config",return_value={"host_only":True}):
            result=driver.prepare_company_proposal_fixture(self.f.path,self.destination,{role:str(self.f.work/(role+".cookies.secret")) for role in driver.ROLES},self.prerequisite)
        self.path=Path(result["private_manifest"])
        value=manifest(self.path);value["stages"][driver.KEY].update(status="targets_ready",commercial={"revision":{"id":str(uuid4())}},
            estimate={"revision":{"id":str(uuid4()),"line_record_ids":[str(uuid4())]}});write_private(self.path,value)
        self.request=driver._request(value,"scope-r14");self.run_id=str(uuid4())

    def assert_originals(self):
        for name,raw in self.originals.items():self.assertEqual((self.f.work/name).read_bytes(),raw)

    def _body(self):
        value=manifest(self.path)
        return {"id":self.run_id,"company":value["company"],"scope_type":"Company","project":None,"request_kind":"deterministic-proposal-v1",
            "status":"queued","cancel_requested":False,"created_at":"2026-10-16T00:00:00+00:00","completed_at":None,"action":"aec.scope.draft",
            "result":None,"result_digest":None,"error":None,"standing":{"mode":"deterministic-proposal-v1","model_invoked":False,"live_model_qualified":False},
            "result_basis":"persisted-proposal-reference-v1","selection":self.request,"selection_digest":sha(self.request)}

    @staticmethod
    def _envelope(**fields):
        request_id=str(uuid4());return {"schema":"cipher.api.v1","request_id":request_id,"meta":{"request_id":request_id,"api_version":"v1",
            "server_time":"2026-10-16T00:00:00+00:00"},**fields}

    def test_reference_uses_null_passwords_exact_cookie_copies_and_no_original_write(self):
        value=manifest(self.path)
        self.assertEqual(value["intents"],{});self.assertEqual(set(value["stages"][driver.KEY]["cases"]),set(driver.CASES))
        for role in driver.ROLES:
            self.assertIsNone(value["users"][role]["password"])
            self.assertEqual((self.destination/(role+".cookies.secret")).read_bytes(),self.originals[role+".cookies.secret"])
        self.assertFalse((self.destination/"http-journal.secret.json").exists());self.assert_originals()

    def test_corrected_prepare_binds_immutable_failure_and_first_reconcile_before_new_record(self):
        old=self.root/"failed-v2";old.mkdir();failed_path=old/"prerequisites.secret.json"
        first_path=old/"prerequisites.secret.reconciled.secret.json";new=self.root/"company-proposal-prerequisites-r14-corrected";new.mkdir()
        plan=driver.load_private(self.prerequisite)["plan"]
        failed={"schema":prerequisites.SCHEMA,"status":"failed","original_manifest":str(self.f.path),
            "original_manifest_sha256":driver.history._digest_bytes(self.f.path),"fixture_id":self.f.fixture["fixture_id"],
            "company":self.f.fixture["company"],"site":self.f.fixture["site"],"plan":plan,"before":{},
            "error":{"error_type":"AssertionError","error_message":"Only the exact new role/permission boundary is admitted."}}
        first={"recorded_status":"failed","old_row_changes":[],"matches_recorded_after":False,"price_list":{},"fiscal_year":{},
            "permissions":{doctype:{flag:False for flag in grants} for doctype,grants in prerequisites.GRANTS.items()},"at":"2026-10-16T00:00:00+00:00"}
        write_private(failed_path,failed);write_private(first_path,first);old_bytes=failed_path.read_bytes();first_bytes=first_path.read_bytes()
        failed_sha=driver.history._digest_bytes(failed_path);first_sha=driver.history._digest_bytes(first_path)
        self.frappe.get_all=lambda *args,**kwargs:[]
        with patch.dict("sys.modules",{"frappe":self.frappe,"cipher_aec.governance.context":SimpleNamespace(require_effects_enabled=lambda:None)}), \
                patch.object(prerequisites,"_record",return_value=(failed,manifest(self.f.path))),patch.object(prerequisites.native,"_fixture",side_effect=manifest), \
                patch.object(driver.recovery,"_only_active"),patch.object(prerequisites,"inventory",return_value={}), \
                patch.object(prerequisites,"_facts",return_value={"role":"fixture"}),patch.object(prerequisites,"_selling_plan",return_value={"enabled":False}):
            result=prerequisites.prepare_corrected_company_proposal_prerequisites(failed_path,first_path,new/"prerequisites.secret.json",plan,
                failed_sha256=failed_sha,first_reconcile_sha256=first_sha)
            prepared=driver.load_private(result["private_record"])
            self.assertEqual(prepared["status"],"prepared");self.assertEqual(prepared["predecessor"]["failed_sha256"],failed_sha)
            self.assertEqual(prepared["predecessor"]["first_reconcile_sha256"],first_sha)
            write_private(first_path,{**first,"at":"changed"})
            with self.assertRaisesRegex(AssertionError,"immutable"):
                prerequisites.prepare_corrected_company_proposal_prerequisites(failed_path,first_path,new/"another.secret.json",plan,
                    failed_sha256=failed_sha,first_reconcile_sha256=first_sha)
        self.assertEqual(failed_path.read_bytes(),old_bytes);self.assertEqual(driver.load_private(failed_path)["status"],"failed")
        self.assertNotEqual(first_path.read_bytes(),first_bytes);self.assert_originals()

    def test_cookie_loss_changed_reference_fresh_and_wrong_session_refuse_without_login(self):
        rpc=driver._ProposalHTTP(self.path,"http://not-used.invalid")
        with patch.object(rpc,"_wire",side_effect=AssertionError("No login or request allowed")) as wire:
            with self.assertRaises(ValueError):rpc.login(fresh=True)
            (self.destination/"alias.cookies.secret").unlink()
            with self.assertRaises(ValueError):rpc.login("alias")
            wire.assert_not_called()
        rpc=driver._ProposalHTTP(self.path,"http://not-used.invalid")
        # Restore only this host fixture's unchanged copied bytes for the next independent check.
        driver.history._copy_private(self.f.work/"alias.cookies.secret",self.destination/"alias.cookies.secret")
        with patch.object(rpc,"_wire",return_value=(200,{"message":{"data":{"site_mode":"synthetic","user":"foreign","person":{"id":"foreign"},"csrf_token":"HOST"}}},0)) as wire:
            with self.assertRaises(AssertionError):rpc.login()
            self.assertEqual(wire.call_args.args[:2],("GET","/api/method/cipher_aec.api.v1.session"))
        self.assert_originals()

    def test_actual_client_published_wire_start_replay_keeps_uuid_and_external_manifest_snapshots(self):
        seen=set();paths=[];body=self._body()
        def wire(method,path,values=None,**kwargs):
            paths.append(path)
            if path.endswith("api.v1.session"):
                owner=manifest(self.path)["users"][rpc.role]
                return 200,{"message":self._envelope(data={"site_mode":"synthetic","user":owner["user"],"person":{"id":owner["person"]},"csrf_token":"HOST"})},0
            row=Journal(self.destination).rows[0];self.assertEqual(row["operation_id"],kwargs["operation"])
            replayed=values["operation_id"] in seen;seen.add(values["operation_id"])
            return 200,{"message":self._envelope(data={**body,"operation":{"id":values["operation_id"],"status":"succeeded","replayed":replayed}})},0
        rpc=driver._ProposalHTTP(self.path,"http://not-used.invalid")
        with patch.object(rpc,"_wire",side_effect=wire):
            rpc.login();first=rpc.call(driver.API+"start_proposal",{"company":rpc.value["company"],"request":self.request},key="start-scope-r14")
            value=manifest(self.path);value["stages"][driver.KEY]["cases"]["scope-r14"].update(status="admitted",start_receipt={"exact":"snapshot"});write_private(self.path,value)
            replay=rpc.call(driver.API+"start_proposal",{"company":rpc.value["company"],"request":self.request},key="start-scope-r14")
        self.assertFalse(first["data"]["operation"]["replayed"]);self.assertTrue(replay["data"]["operation"]["replayed"])
        rows=Journal(self.destination).rows;self.assertEqual(len(rows),1);self.assertEqual(len(rows[0]["attempts"]),2)
        self.assertEqual(first["data"]["operation"]["id"],replay["data"]["operation"]["id"])
        current=manifest(self.path);self.assertEqual(current["stages"][driver.KEY]["cases"]["scope-r14"]["start_receipt"],{"exact":"snapshot"})
        self.assertEqual(len(current["stages"]["http_calls"]),2);self.assertNotIn("/api/method/login",paths);self.assert_originals()

    def test_start_phase_binds_actual_client_journal_receipt_event_and_original_identity(self):
        body=self._body();receipts={};events=[];previous="b"*64
        def wire(rpc,method,path,values=None,**kwargs):
            owner=manifest(self.path)["users"][rpc.role]
            if path.endswith("api.v1.session"):
                return 200,{"message":self._envelope(data={"site_mode":"synthetic","user":owner["user"],"person":{"id":owner["person"]},"csrf_token":"HOST"})},0
            self.assertEqual(path,"/api/method/"+driver.API+"start_proposal");operation=values["operation_id"]
            receipts[sha({"person":owner["person"],"operation_id":operation})]=SimpleNamespace(person=owner["person"],company=body["company"],scope_type="Company",project=None,
                command="ricky.company.proposal.start.v1",state="Succeeded",result_json=json.dumps(body,sort_keys=True,separators=(",",":"),ensure_ascii=False),result_hash=sha(body))
            details={"action":"aec.scope.draft","status":"queued"}
            payload={"scope_type":"Company","actor":owner["person"],"company":body["company"],"project":None,"event":"ricky.company.proposal.start.accepted",
                "subject_type":"Cipher Ricky Run","subject_id":self.run_id,"operation_id":operation,"details":details,"previous_hash":previous}
            from cipher_aec.api.contracts import canonical_json
            events[:]=[{"name":"native-start","scope_type":"Company","company":body["company"],"project":None,"actor_person":owner["person"],
                **{key:payload[key] for key in ("event","subject_type","subject_id","operation_id","previous_hash")},
                "details_json":canonical_json(details),"event_payload":canonical_json(payload),"event_hash":sha(payload)}]
            return 200,{"message":self._envelope(data={**body,"operation":{"id":operation,"status":"succeeded","replayed":False}})},0
        value=manifest(self.path);owner=value["users"]["author"]
        run={**body,"user":owner["user"],"person":owner["person"],"authority":{"HOST_ONLY":True},"original_session_reference":"d"*64,"request":self.request}
        self.frappe.db.get_value=lambda doctype,name,*args,**kwargs:receipts.get(name)
        with patch.dict("sys.modules",{"frappe":self.frappe}),patch.object(driver.native,"_fixture",side_effect=manifest), \
                patch.object(driver,"_preserved"),patch.object(driver.recovery,"_only_active"),patch.object(driver,"_head",return_value=previous), \
                patch.object(driver,"_run",return_value=run),patch.object(driver.history,"_events",side_effect=lambda identifier:deepcopy(events)), \
                patch.object(driver._ProposalHTTP,"_wire",new=wire):
            result=driver.start_company_proposal_case(self.path,"scope-r14","http://not-used.invalid")
        current=manifest(self.path)["stages"][driver.KEY]["cases"]["scope-r14"];journal=Journal(self.destination).rows[0]
        self.assertEqual(result["status"],"admitted");self.assertEqual(current["operation_id"],journal["operation_id"])
        self.assertEqual(current["run_id"],self.run_id);self.assertEqual(current["start_event"],events[0])
        self.assertEqual(current["start_receipt"]["result_json"],json.dumps(body,sort_keys=True,separators=(",",":"),ensure_ascii=False))
        self.assertEqual(current["original_binding"]["user"],owner["user"]);self.assertEqual(current["original_binding"]["person"],owner["person"])
        self.assertEqual(current["original_binding"]["request"],journal["payload"]["request"]);self.assert_originals()

    def test_published_wire_missing_wrapper_and_unauthorized_response_preserve_journal(self):
        rpc=driver._ProposalHTTP(self.path,"http://not-used.invalid");rpc.role="author";rpc.csrf="HOST"
        response=self._envelope(data={**self._body(),"operation":{"id":str(uuid4()),"status":"succeeded","replayed":False}})
        with patch.object(rpc,"_wire",return_value=(200,response,0)):
            with self.assertRaises(AssertionError):rpc.call(driver.API+"start_proposal",{"company":rpc.value["company"],"request":self.request},key="start-scope-r14")
        original=Journal(self.destination).rows[0]["operation_id"]
        denial=self._envelope(error={"code":"not_found","message":"Not available","details":{},"retryable":False})
        with patch.object(rpc,"_wire",return_value=(404,{"message":denial},0)):
            result=rpc.call(driver.API+"get_run",{"company":rpc.value["company"],"run_id":self.run_id},expected={"not_found"})
        self.assertEqual(result["error"]["code"],"not_found");self.assertEqual(Journal(self.destination).rows[0]["operation_id"],original)
        self.assert_originals()

    def test_timeout_has_one_send_and_reuses_only_original_intent(self):
        rpc=driver._ProposalHTTP(self.path,"http://not-used.invalid");rpc.role="author";rpc.csrf="HOST"
        with patch.object(rpc,"_wire",side_effect=TimeoutError("Host-only transport interruption")) as wire:
            with self.assertRaises(TimeoutError):rpc.call(driver.API+"start_proposal",{"company":rpc.value["company"],"request":self.request},key="start-scope-r14")
            self.assertEqual(wire.call_count,1)
        row=Journal(self.destination).rows[0]
        self.assertEqual(row["uncertain_transport"]["error_type"],"TimeoutError");self.assertEqual(row["attempts"],[])
        self.assertEqual(Journal(self.destination).prepare("start-scope-r14","author",driver.API+"start_proposal",
            {"company":rpc.value["company"],"request":self.request})["operation_id"],row["operation_id"])

    def test_failed_phase_latches_and_cannot_be_entered_again(self):
        with patch.object(driver,"_value",side_effect=manifest):
            with self.assertRaisesRegex(RuntimeError,"host failure"):
                with driver._phase(self.path,"declared","entered",case="scope-r14"):raise RuntimeError("host failure")
            failed=manifest(self.path)["stages"][driver.KEY]["cases"]["scope-r14"]
            self.assertEqual(failed["status"],"failed");self.assertEqual(failed["error"]["error_type"],"RuntimeError")
            with self.assertRaisesRegex(RuntimeError,"one-shot"):
                with driver._phase(self.path,"declared","entered",case="scope-r14"):pass

    def test_instance_probe_requires_actual_insert_and_always_restores_save(self):
        saved=[];observed=[];store=SimpleNamespace(save=lambda kind,value:saved.append((kind,value)),find=lambda *args,**kwargs:[{"id":"proposal"}])
        service=SimpleNamespace(store=store);original=store.save
        with self.assertRaises(driver._FinalizationRollbackProbe):
            with driver._rollback_probe(service,observed.append):
                store.save("step",{"status":"succeeded"})
                store.save("run",{"id":"run","status":"waiting-for-review","proposal_ids":["proposal"]})
        self.assertIs(store.save,original);self.assertEqual(observed,[{"id":"proposal"}]);self.assertEqual(saved,[("step",{"status":"succeeded"})])
        store.find=lambda *args,**kwargs:[]
        with self.assertRaises(AssertionError):
            with driver._rollback_probe(service,observed.append):store.save("run",{"id":"run","status":"waiting-for-review","proposal_ids":[]})
        self.assertIs(store.save,original)

    def test_exact_duty_audit_only_and_composed_original_prerequisite_baseline(self):
        before={"Cipher Project Duty":{"duty":{"active":"hash1","modified":"old","modified_by":"old"}},"Other":{"old":{"x":"same"}}}
        after=deepcopy(before);after["Cipher Project Duty"]["duty"].update(modified="new",modified_by="Administrator")
        audit={"name":"duty","before":before["Cipher Project Duty"]["duty"],"after":after["Cipher Project Duty"]["duty"],"semantic_restored":True,"independent_readback":True}
        self.assertEqual(driver.preservation_changes(before,after,audit),[])
        bad=deepcopy(after);bad["Cipher Project Duty"]["duty"]["active"]="changed"
        with self.assertRaises(AssertionError):driver.preservation_changes(before,bad,{**audit,"after":bad["Cipher Project Duty"]["duty"]})
        bad=deepcopy(after);bad["Other"]["old"]["x"]="changed";self.assertEqual(len(driver.preservation_changes(before,bad,audit)),1)
        value=manifest(self.path)
        with patch.object(driver,"_origin_unchanged"),patch.object(driver,"_baseline",return_value={"inventory":{},"config":{"host_only":True}}), \
                patch.object(driver.prerequisites,"inventory",return_value={}),patch.object(driver,"_config",return_value={"host_only":True}):
            driver._preserved(value)
            proof=driver.load_private(self.prerequisite);proof["before"]={"Old":{"row":{"x":"changed"}}};write_private(self.prerequisite,proof)
            with self.assertRaisesRegex(AssertionError,"compose"):driver._preserved(value)

    def test_source_outage_transport_failure_restores_duty_and_retains_failed_phase(self):
        value=manifest(self.path);value["duties"]["document.read"]="duty"
        proof=value["stages"][driver.KEY];proof["status"]="successors_ready"
        for case,row in proof["cases"].items():row.update(status="passed",run_id=str(uuid4()),proposal_id=str(uuid4()),operation_id=str(uuid4()))
        write_private(self.path,value);calls=[];original={"active":1,"fields":{"active":driver.native._native_scalar(1)}}
        class FailingHTTP:
            def __init__(inner,*args):pass
            def login(inner,role="author"):inner.role=role
            def call(inner,*args,**kwargs):
                if inner.role!="author":return {"error":{"code":"not_found"}}
                raise RuntimeError("Host-only outage transport failure")
        with patch.dict("sys.modules",{"frappe":self.frappe}),patch.object(driver,"_value",side_effect=manifest), \
                patch.object(driver,"_preserved"),patch.object(driver.recovery,"_only_active"),patch.object(driver,"_run",return_value={"id":"host-run"}), \
                patch.object(driver,"_visibility",return_value={}),patch.object(driver,"_ProposalHTTP",FailingHTTP), \
                patch.object(driver.native,"_capture_duty_outage",return_value=original), \
                patch.object(driver.prerequisites,"inventory",return_value={"Cipher Project Duty":{"duty":{"modified":"hash"}}}), \
                patch.object(driver.native,"_duty",side_effect=lambda value,ability,active,saved:calls.append((active,deepcopy(saved)))), \
                patch.object(driver.native,"_independent_duty_readback") as readback:
            with self.assertRaisesRegex(RuntimeError,"outage transport"):
                driver.finish_company_proposal_fixture(self.path,"http://not-used.invalid")
        self.assertEqual(calls,[(0,original),(1,original)]);self.assertEqual(readback.call_args_list[-1].args[-1],original)
        current=manifest(self.path)["stages"][driver.KEY]
        self.assertEqual(current["status"],"failed");self.assertTrue(current["duty_audit"]["independent_readback"])
        self.assert_originals()


if __name__ == "__main__":unittest.main()

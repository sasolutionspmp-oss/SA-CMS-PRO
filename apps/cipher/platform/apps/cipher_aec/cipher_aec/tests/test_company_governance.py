"""Targeted real Frappe/MariaDB Company scope tests; no global reseed."""
import json
import uuid
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from cipher_aec.api.contracts import canonical_json, digest
from cipher_aec.api.errors import DomainError
from cipher_aec.api import v1
from cipher_aec.governance.commands import read_company_operation, read_operation, run_company_command, run_command
from cipher_aec.governance.context import company_duty_rows, current_actor, duty_rows, require_company, require_project, trusted_write
from cipher_aec.governance.company import history as company_history
from cipher_aec.governance.history import append_company_event, append_event
from cipher_aec.install import _binding, _grant, _grant_company, _person, _user


class TestCompanyGovernance(IntegrationTestCase):
    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        self.savepoint="company_test_"+uuid.uuid4().hex
        frappe.db.savepoint(self.savepoint)
        self.company="Cipher Synthetic Company"
        if not frappe.db.exists("Company",self.company):raise RuntimeError("Synthetic Company fixture prerequisite is missing; do not reseed inside this suite")
        self.prefix=uuid.uuid4().hex[:12]
        with trusted_write():
            self.person=_person("COMPANY-TEST-"+self.prefix,"Company-only synthetic author")
            self.primary="company-"+self.prefix+"@cipher.example"
            self.alias="company-alias-"+self.prefix+"@cipher.example"
            self.project_user="project-only-"+self.prefix+"@cipher.example"
            self.project_person=_person("PROJECT-TEST-"+self.prefix,"Project-only synthetic author")
            for email,person in ((self.primary,self.person),(self.alias,self.person),(self.project_user,self.project_person)):
                _user(email,"Synthetic",None);_binding(email,person)
            self.project=frappe.get_doc({"doctype":"Project","company":self.company,"project_name":"Synthetic company scope test "+self.prefix,"status":"Open","percent_complete_method":"Manual"}).insert(ignore_permissions=True).name
            for ability in ("company.read","commercial.read","commercial.write"):_grant_company(self.person,self.company,ability)
            for ability in ("project.read","task.create"):_grant(self.project_person,self.company,self.project,ability)
        frappe.set_user(self.primary)

    def tearDown(self):
        frappe.set_user("Administrator")
        frappe.db.rollback(save_point=self.savepoint)
        super().tearDown()

    def command(self,operation_id=None,payload=None,effect=None):
        operation_id=operation_id or str(uuid.uuid4());payload=payload or {"text":"Company scoped synthetic draft"}
        def save(actor,company):
            event=append_company_event(actor=actor,company=company.name,event="company.fixture.saved",subject_type="Company",subject_id=company.name,operation_id=operation_id,details=payload)
            return {"event_id":event,"company":company.name,"text":payload["text"]}
        result=run_company_command(company=self.company,operation_id=operation_id,command="company.fixture.v1",payload=payload,ability="commercial.write",effect=effect or save)
        return operation_id,result

    def grant_project_to_primary(self):
        frappe.set_user("Administrator")
        with trusted_write():
            for ability in ("project.read","task.create"):_grant(self.person,self.company,self.project,ability)
        frappe.set_user(self.primary)

    def test_company_only_identity_session_and_command_need_no_project(self):
        self.assertEqual(require_company(self.company,ability="commercial.write").name,self.company)
        self.assertFalse(duty_rows(current_actor()))
        response=v1.session()["data"]
        self.assertIn(self.company,[row["id"] for row in response["companies"]])
        self.assertEqual(response["company_scopes"],[{"company":self.company,"capabilities":["commercial.read","commercial.write","company.read"]}])
        operation,result=self.command()
        row=frappe.db.get_value("Cipher Command Receipt",{"person":self.person,"operation_id":operation},["scope_type","project"],as_dict=True)
        self.assertEqual(row.scope_type,"Company");self.assertFalse(row.project)
        self.assertEqual(frappe.db.count("Project",{"name":self.project}),1)
        self.assertEqual(company_history(self.company,count_mode="exact")["total"],1)

    def test_project_and_company_duties_never_imply_each_other(self):
        with self.assertRaises(DomainError):require_project(self.company,self.project)
        self.assertFalse(frappe.has_permission("Project","read",doc=self.project,user=self.primary))
        frappe.set_user(self.project_user)
        self.assertEqual(require_project(self.company,self.project).name,self.project)
        self.assertEqual(company_duty_rows(current_actor()),[])
        with self.assertRaises(DomainError) as error:require_company(self.company)
        self.assertEqual(error.exception.status,404)
        self.assertFalse(frappe.has_permission("Company","read",doc=self.company,user=self.project_user))
        with self.assertRaises(DomainError):self.command()

    def test_scope_shape_and_nullable_duty_uniqueness(self):
        with trusted_write():
            for scope,project,ability in (("Company",self.project,"company.read"),("Project",None,"project.read"),("Company",None,"project.read"),("Project",self.project,"commercial.read")):
                with self.assertRaises(DomainError):
                    frappe.get_doc({"doctype":"Cipher Project Duty","person":self.person,"company":self.company,"scope_type":scope,"project":project,"ability":ability,"active":1}).insert(ignore_permissions=True)
            with self.assertRaises((frappe.DuplicateEntryError, frappe.UniqueValidationError)):
                frappe.get_doc({"doctype":"Cipher Project Duty","person":self.person,"company":self.company,"scope_type":"Company","project":None,"ability":"company.read","active":1}).insert(ignore_permissions=True)
        self.assertEqual(len(company_duty_rows(current_actor(),self.company)),3)

    def test_alias_replays_same_receipt_and_changed_payload_conflicts(self):
        operation,result=self.command()
        frappe.set_user(self.alias)
        _,replay=self.command(operation)
        self.assertTrue(replay["operation"]["replayed"])
        self.assertEqual(replay["event_id"],result["event_id"])
        self.assertEqual(read_company_operation(self.company,operation)["event_id"],result["event_id"])
        with self.assertRaises(DomainError) as error:self.command(operation,{"text":"Changed input"})
        self.assertEqual(error.exception.code,"operation_conflict")
        self.assertEqual(frappe.db.count("Cipher Command Receipt",{"person":self.person,"operation_id":operation}),1)

    def test_company_logical_lifetime_covers_guard_effect_and_receipt_only(self):
        from cipher_aec.documents.provenance import has_prelocked, logical_operation_stats
        from cipher_aec.governance import commands
        operation=str(uuid.uuid4());seen=[]
        def observe(stage):
            self.assertIsNotNone(logical_operation_stats())
            self.assertFalse(has_prelocked(), "A command lifetime must not mint source admission")
            seen.append(stage)
        def guard(actor,record):observe("guard")
        def effect(actor,record):observe("effect");return {"company":record.name}
        original_insert=frappe.model.document.Document.insert
        def insert(document,*args,**kwargs):
            if document.doctype=="Cipher Command Receipt":observe("receipt")
            return original_insert(document,*args,**kwargs)
        with patch.object(frappe.model.document.Document,"insert",insert):
            result=run_company_command(company=self.company,operation_id=operation,command="company.fixture.v1",payload={},ability="commercial.write",effect=effect,guard=guard)
        self.assertEqual(seen,["guard","effect","receipt"])
        self.assertIsNone(logical_operation_stats())
        original_authorize=commands.authorize_receipt
        def authorize(*args,**kwargs):observe("authorize");return original_authorize(*args,**kwargs)
        frappe.set_user(self.alias)
        with patch.object(commands,"authorize_receipt",side_effect=authorize):
            replay=run_company_command(company=self.company,operation_id=operation,command="company.fixture.v1",payload={},ability="commercial.write",effect=lambda *args:self.fail("Replay executed the effect"))
            self.assertIsNone(logical_operation_stats())
            readback=read_company_operation(self.company,operation)
        self.assertEqual(seen[-2:],["authorize","authorize"])
        self.assertEqual(replay["company"],result["company"])
        self.assertEqual(readback,replay)
        self.assertIsNone(logical_operation_stats())

    def test_company_memo_exits_before_effect_rollback_and_receipt_denial(self):
        from cipher_aec.documents.provenance import logical_operation_stats
        operation=str(uuid.uuid4());rollbacks=[];original_rollback=frappe.db.rollback
        def rollback(*args,**kwargs):
            self.assertIsNone(logical_operation_stats())
            rollbacks.append(kwargs.get("save_point"))
            return original_rollback(*args,**kwargs)
        def broken(actor,record):
            self.assertIsNotNone(logical_operation_stats())
            append_company_event(actor=actor,company=self.company,event="company.failed",subject_type="Company",subject_id=self.company,operation_id=operation,details={})
            raise RuntimeError("Injected after history insertion")
        with patch.object(frappe.db,"rollback",side_effect=rollback):
            with self.assertRaisesRegex(RuntimeError,"Injected"):self.command(operation,effect=broken)
        self.assertEqual(len(rollbacks),1)
        self.assertTrue(rollbacks[0].startswith("cipher_company_"))
        self.assertEqual(frappe.db.count("Cipher History Event",{"operation_id":operation}),0)
        self.assertEqual(frappe.db.count("Cipher Command Receipt",{"operation_id":operation}),0)
        self.command(operation)
        def deny(*args,**kwargs):
            self.assertIsNotNone(logical_operation_stats())
            raise DomainError("fixture_denied","Synthetic current-source refusal",403)
        with patch("cipher_aec.governance.commands.authorize_receipt",side_effect=deny):
            for call in (lambda:self.command(operation),lambda:read_company_operation(self.company,operation)):
                with self.assertRaises(DomainError):call()
                self.assertIsNone(logical_operation_stats())

    def test_recursive_company_commands_refuse_before_locks_and_roll_back_outer_effect(self):
        from cipher_aec.documents.provenance import logical_operation_stats
        for same_id in (False,True):
            with self.subTest(same_operation_id=same_id):
                operation=str(uuid.uuid4());inner=operation if same_id else str(uuid.uuid4())
                def effect(actor,record):
                    append_company_event(actor=actor,company=self.company,event="company.nested.failed",subject_type="Company",subject_id=self.company,operation_id=operation,details={})
                    with patch("cipher_aec.governance.commands.current_actor",side_effect=AssertionError("Nested command reached authority/locks")):
                        self.command(inner)
                with self.assertRaises(DomainError) as error:self.command(operation,effect=effect)
                self.assertEqual(error.exception.code,"nested_company_command")
                for identifier in {operation,inner}:
                    self.assertEqual(frappe.db.count("Cipher History Event",{"operation_id":identifier}),0)
                    self.assertEqual(frappe.db.count("Cipher Command Receipt",{"operation_id":identifier}),0)
                self.assertIsNone(logical_operation_stats())

    def test_person_uuid_namespace_conflicts_across_company_and_project_scopes(self):
        self.grant_project_to_primary()
        operation,result=self.command()
        with self.assertRaises(DomainError) as error:
            run_command(company=self.company,project=self.project,operation_id=operation,command="company.fixture.v1",payload={"text":"Company scoped synthetic draft"},ability="task.create",effect=lambda actor,scope:{"unexpected":True})
        self.assertEqual(error.exception.code,"operation_conflict")
        with self.assertRaises(DomainError):read_operation(self.company,self.project,operation)
        project_operation=str(uuid.uuid4())
        run_command(company=self.company,project=self.project,operation_id=project_operation,command="project.fixture.v1",payload={},ability="task.create",effect=lambda actor,scope:{"project":scope.name})
        with self.assertRaises(DomainError):read_company_operation(self.company,project_operation)

    def test_project_hash_and_history_body_remain_byte_compatible(self):
        self.grant_project_to_primary()
        operation=str(uuid.uuid4());payload={"text":"Preserved project shape"}
        def effect(actor,record):
            from cipher_aec.documents.provenance import logical_operation_stats
            self.assertIsNone(logical_operation_stats(), "Project commands retain their original lifetime")
            identifier=append_event(actor=actor,company=self.company,project=self.project,event="project.fixture.saved",subject_type="Project",subject_id=self.project,operation_id=operation,details=payload)
            return {"history_id":identifier}
        result=run_command(company=self.company,project=self.project,operation_id=operation,command="project.fixture.v1",payload=payload,ability="task.create",effect=effect)
        receipt=frappe.get_doc("Cipher Command Receipt",digest({"person":self.person,"operation_id":operation}))
        self.assertEqual(receipt.request_hash,digest({"command":"project.fixture.v1","company":self.company,"project":self.project,"payload":payload}))
        event=frappe.get_doc("Cipher History Event",result["history_id"])
        expected={"actor":self.person,"company":self.company,"project":self.project,"event":"project.fixture.saved","subject_type":"Project","subject_id":self.project,"operation_id":operation,"details":payload,"previous_hash":""}
        self.assertEqual(event.event_payload,canonical_json(expected));self.assertEqual(event.event_hash,digest(expected))
        _,company_result=self.command()
        company_event=frappe.get_doc("Cipher History Event",company_result["event_id"])
        self.assertFalse(company_event.previous_hash)
        self.assertEqual(json.loads(company_event.event_payload)["scope_type"],"Company")
        self.assertEqual(company_history(self.company,count_mode="exact")["total"],1)
        self.assertEqual(frappe.db.get_value("Cipher History Event",event.name,"event_hash"),digest(expected))

    def test_company_chain_keyset_cursor_and_current_duty_binding(self):
        self.command();self.command()
        # A hidden Project reference must not enter Company items/count/cursors.
        with trusted_write():
            append_company_event(actor=current_actor(),company=self.company,event="private.project.reference",subject_type="Project",subject_id=self.project,operation_id=str(uuid.uuid4()),details={"private":True})
        first=company_history(self.company,limit=1,count_mode="exact")
        second=company_history(self.company,limit=1,cursor=first["next_cursor"])
        self.assertEqual(first["total"],2);self.assertNotEqual(first["items"][0]["id"],second["items"][0]["id"])
        newer=frappe.get_doc("Cipher History Event",first["items"][0]["id"])
        older=frappe.get_doc("Cipher History Event",second["items"][0]["id"])
        self.assertEqual(newer.previous_hash,older.event_hash)
        frappe.set_user(self.alias)
        with self.assertRaises(DomainError) as error:company_history(self.company,cursor=first["next_cursor"])
        self.assertEqual(error.exception.code,"invalid_cursor")

    def test_company_native_permission_required_and_revocation_blocks_receipt(self):
        operation,result=self.command()
        with patch("frappe.has_permission",return_value=False):
            with self.assertRaises(DomainError):require_company(self.company)
            session=v1.session()["data"]
            self.assertEqual(session["companies"],[])
            self.assertEqual(session["company_scopes"],[])
        with trusted_write():
            duty=frappe.get_doc("Cipher Project Duty",frappe.db.get_value("Cipher Project Duty",{"person":self.person,"scope_type":"Company","ability":"company.read"},"name"));duty.active=0;duty.save(ignore_permissions=True)
        for call in (lambda:self.command(operation),lambda:read_company_operation(self.company,operation),lambda:company_history(self.company)):
            with self.assertRaises(DomainError):call()

    def test_atomic_rollback_quarantine_and_read_only_receipt_recovery(self):
        operation=str(uuid.uuid4())
        def broken(actor,record):
            append_company_event(actor=actor,company=self.company,event="company.failed",subject_type="Company",subject_id=self.company,operation_id=operation,details={})
            raise RuntimeError("injected after local effect")
        with self.assertRaises(RuntimeError):self.command(operation,effect=broken)
        self.assertEqual(frappe.db.count("Cipher Command Receipt",{"operation_id":operation}),0)
        self.assertEqual(company_history(self.company,count_mode="exact")["total"],0)
        operation,result=self.command(operation)
        with patch("cipher_aec.governance.history_listing.MAX_SCAN",0):
            with self.assertRaises(DomainError) as bounded:company_history(self.company,count_mode="exact")
            self.assertEqual(bounded.exception.code,"history_authorization_limit")
        with patch.dict(frappe.conf,{"cipher_execution_quarantined":1}):
            self.assertTrue(self.command(operation)[1]["operation"]["replayed"])
            self.assertEqual(read_company_operation(self.company,operation)["event_id"],result["event_id"])
            with self.assertRaises(DomainError) as error:self.command()
            self.assertEqual(error.exception.code,"execution_quarantined")

    def test_cross_company_and_inactive_identity_denied(self):
        with self.assertRaises(DomainError):require_company("Unavailable Company")
        with trusted_write():
            person=frappe.get_doc("Cipher Person",self.person);person.active=0;person.save(ignore_permissions=True)
        with self.assertRaises(DomainError):self.command()

    def test_unqualified_financial_drafts_fail_before_native_mutation(self):
        from cipher_aec.hooks import UNQUALIFIED_FINANCIAL_WRITERS, doc_events
        self.assertNotIn("Opportunity",UNQUALIFIED_FINANCIAL_WRITERS)
        self.assertNotIn("Quotation",UNQUALIFIED_FINANCIAL_WRITERS)
        for doctype in UNQUALIFIED_FINANCIAL_WRITERS:
            with self.subTest(doctype=doctype):
                for hook in ("before_insert","before_validate","before_save","before_submit","before_cancel","before_update_after_submit","on_trash"):
                    self.assertIn(hook,doc_events[doctype])
                if not frappe.db.exists("DocType",doctype):continue
                before=frappe.db.count(doctype)
                document=frappe.get_doc({"doctype":doctype,"company":self.company,"docstatus":0})
                with trusted_write(),self.assertRaises(DomainError) as error:document.insert(ignore_permissions=True)
                self.assertEqual(error.exception.code,"financial_action_unqualified")
                self.assertEqual(frappe.db.count(doctype),before)

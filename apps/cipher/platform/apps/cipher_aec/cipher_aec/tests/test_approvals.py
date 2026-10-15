"""Actual MariaDB Project/Task, immutable governance, and transaction tests."""
from datetime import datetime, timedelta, timezone
import json
from werkzeug.test import EnvironBuilder
from werkzeug.wrappers import Request
import uuid
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import now_datetime

from cipher_aec.api.contracts import canonical_json, version_of
from cipher_aec.api.errors import DomainError
from cipher_aec.governance import approvals as service
from cipher_aec.governance.commands import read_operation
from cipher_aec.governance.context import trusted_write
from cipher_aec.install import seed_synthetic, set_synthetic_duty


class TestApprovals(IntegrationTestCase):
    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        self.savepoint = "approval_test_" + uuid.uuid4().hex
        frappe.db.savepoint(self.savepoint)
        self.fixture = seed_synthetic()
        self.company = self.fixture["company"]
        self.primary = self.fixture["users"]["primary"]["user"]
        self.reviewer = self.fixture["users"]["reviewer"]["user"]
        self.alias = self.fixture["users"]["alias"]["user"]
        # Isolated standard Project, no main acceptance fixture lifecycle changes.
        with trusted_write():
            project = frappe.get_doc({"doctype":"Project", "project_name":"Synthetic approval " + uuid.uuid4().hex[:10], "company":self.company, "status":"Open", "percent_complete_method":"Manual", "percent_complete":0}).insert(ignore_permissions=True)
            self.project = project.name
            from cipher_aec.install import _grant
            for key, abilities in (("primary", ["project.read","project.write","task.create","approval.request","approval.decide","approval.execute"]), ("reviewer", ["project.read","approval.decide"])):
                for ability in abilities:
                    _grant(self.fixture["users"][key]["person"],self.company,self.project,ability)
        self.old_request = getattr(frappe.local,"request",None)
        self.old_sid = getattr(frappe.session,"sid",None)
        self.login(self.primary)

    def tearDown(self):
        frappe.set_user("Administrator")
        frappe.local.request = self.old_request
        frappe.session.sid = self.old_sid
        frappe.db.rollback(save_point=self.savepoint)
        super().tearDown()

    def login(self, user):
        frappe.set_user(user)
        sid = "synthetic-approval-test-" + uuid.uuid4().hex
        frappe.session.sid = sid
        frappe.local.request = Request(EnvironBuilder(method="POST", base_url="http://cipher.localhost", headers={"Cookie": "sid=" + sid}).get_environ())
        frappe.db.sql("INSERT INTO tabSessions (user,sid,sessiondata,lastupdate,status) VALUES (%s,%s,%s,%s,'Active')",(user,sid,canonical_json({"user":user}),now_datetime()))

    def request(self, status="On hold"):
        result = service.request_project_status(self.company,self.project,status,version_of(frappe.get_doc("Project",self.project)),str(uuid.uuid4()))
        return result["packet"]

    def decide(self, packet, decision="Grant"):
        return service.decide_packet(self.company,self.project,packet["id"],packet["manifest_hash"],decision,str(uuid.uuid4()),"Reviewed exact synthetic manifest")

    def grant(self, packet):
        self.login(self.reviewer)
        result = self.decide(packet)
        self.login(self.primary)
        return result

    def execute(self, packet, operation_id=None):
        return service.execute_packet(self.company,self.project,packet["id"],packet["manifest_hash"],operation_id or str(uuid.uuid4()))

    def test_request_and_review_do_not_change_project_and_packet_is_immutable(self):
        source=version_of(frappe.get_doc("Project",self.project))
        packet=self.request()
        self.assertEqual(packet["state"],"Pending")
        self.assertEqual(version_of(frappe.get_doc("Project",self.project)),source)
        granted=self.grant(packet)
        self.assertEqual(granted["packet"]["state"],"Granted")
        self.assertEqual(frappe.db.get_value("Project",self.project,"status"),"Open")
        doc=frappe.get_doc("Cipher Approval Packet",packet["id"])
        with trusted_write(), self.assertRaises(DomainError):
            doc.source_version="forged";doc.save(ignore_permissions=True)

    def test_alias_cannot_review_own_request(self):
        packet=self.request()
        self.login(self.alias)
        with self.assertRaises(DomainError) as error:self.decide(packet)
        self.assertEqual(error.exception.code,"independent_review_required")
        self.assertEqual(frappe.db.count("Cipher Approval Decision",{"packet":packet["id"]}),0)

    def test_worker_and_service_identity_cannot_grant(self):
        packet=self.request();self.login(self.reviewer)
        request=frappe.local.request;frappe.local.request=None
        try:
            with self.assertRaises(DomainError) as error:self.decide(packet)
            self.assertEqual(error.exception.code,"interactive_review_required")
        finally:frappe.local.request=request
        with trusted_write():
            person=frappe.get_doc("Cipher Person",self.fixture["users"]["reviewer"]["person"]);person.identity_kind="Service";person.save(ignore_permissions=True)
        with self.assertRaises(DomainError) as error:self.decide(packet)
        self.assertEqual(error.exception.code,"human_review_required")

    def test_atomic_consumption_exact_retry_and_no_task_cascade(self):
        with trusted_write():
            task=frappe.get_doc({"doctype":"Task","project":self.project,"subject":"Synthetic affected task","status":"Open"}).insert(ignore_permissions=True)
        task_version=version_of(task)
        packet=self.request("Cancelled");self.grant(packet)
        operation=str(uuid.uuid4());result=self.execute(packet,operation)
        self.assertEqual(result["packet"]["state"],"Consumed")
        self.assertEqual(result["effect"]["project"]["status"],"Cancelled")
        self.assertEqual(frappe.db.get_value("Task",task.name,"status"),"Open")
        self.assertEqual(version_of(frappe.get_doc("Task",task.name)),task_version)
        replay=self.execute(packet,operation)
        self.assertTrue(replay["operation"]["replayed"])
        self.assertEqual(read_operation(self.company,self.project,operation)["effect"],result["effect"])
        self.assertEqual(frappe.db.count("Cipher Approval Consumption",{"packet":packet["id"]}),1)
        with self.assertRaises(DomainError):self.execute(packet)

    def test_failure_after_effect_rolls_back_project_consumption_and_receipt(self):
        packet=self.request();self.grant(packet)
        operation=str(uuid.uuid4())
        with patch.object(service,"_event",side_effect=RuntimeError("injected after local effect")):
            with self.assertRaises(RuntimeError):self.execute(packet,operation)
        self.assertEqual(frappe.db.get_value("Project",self.project,"status"),"Open")
        self.assertEqual(frappe.db.count("Cipher Approval Consumption",{"packet":packet["id"]}),0)
        self.assertEqual(frappe.db.count("Cipher Command Receipt",{"operation_id":operation}),0)
        self.assertEqual(self.execute(packet,operation)["packet"]["state"],"Consumed")

    def test_stale_task_inventory_denies_and_preserves_grant(self):
        packet=self.request();self.grant(packet)
        with trusted_write():frappe.get_doc({"doctype":"Task","project":self.project,"subject":"Changed inventory","status":"Open"}).insert(ignore_permissions=True)
        with self.assertRaises(DomainError) as error:self.execute(packet)
        self.assertEqual(error.exception.details["state"],"Stale")
        self.assertEqual(frappe.db.count("Cipher Approval Consumption",{"packet":packet["id"]}),0)

    def test_new_policy_revision_invalidates_old_grant_including_disabled_policy(self):
        packet=self.request();self.grant(packet)
        with trusted_write():
            frappe.get_doc({"doctype":"Cipher Approval Policy Revision","action":service.ACTION,"version":2,"enabled":0,"label":"Synthetic disabled revision","lifetime_seconds":86400,"definition_json":canonical_json(service.POLICY_DEFINITION)}).insert(ignore_permissions=True)
        self.assertEqual(service.read_packet(self.company,self.project,packet["id"])["state"],"Stale")
        with self.assertRaises(DomainError):self.execute(packet)

    def test_current_reviewer_revocation_denies_execution(self):
        packet=self.request();self.grant(packet)
        frappe.set_user("Administrator");set_synthetic_duty(self.reviewer,self.project,"approval.decide",0);self.login(self.primary)
        with self.assertRaises(DomainError) as error:self.execute(packet)
        self.assertEqual(error.exception.code,"reviewer_authority_revoked")
        self.assertEqual(frappe.db.get_value("Project",self.project,"status"),"Open")

    def test_reject_withdraw_manifest_and_completion_guards(self):
        packet=self.request();self.login(self.reviewer);rejected=self.decide(packet,"Reject");self.login(self.primary)
        self.assertEqual(rejected["packet"]["state"],"Rejected")
        with self.assertRaises(DomainError):self.execute(packet)
        packet=self.request()
        withdrawn=service.withdraw_packet(self.company,self.project,packet["id"],packet["manifest_hash"],str(uuid.uuid4()),"Changed plan")
        self.assertEqual(withdrawn["packet"]["state"],"Withdrawn")
        packet=self.request();self.grant(packet)
        with self.assertRaises(DomainError) as error:service.execute_packet(self.company,self.project,packet["id"],"0"*64,str(uuid.uuid4()))
        self.assertEqual(error.exception.code,"manifest_changed")
        with trusted_write():frappe.get_doc({"doctype":"Task","project":self.project,"subject":"Incomplete work","status":"Open"}).insert(ignore_permissions=True)
        with self.assertRaises(DomainError) as error:self.request("Completed")
        self.assertEqual(error.exception.code,"tasks_incomplete")

    def test_native_project_save_requires_specific_grant_even_in_trusted_scope(self):
        doc=frappe.get_doc("Project",self.project);doc.status="Cancelled"
        with trusted_write(),self.assertRaises(DomainError) as error:doc.save(ignore_permissions=True)
        self.assertEqual(error.exception.code,"approval_required")
        self.assertEqual(frappe.db.get_value("Project",self.project,"status"),"Open")

    def test_native_financial_import_submit_cancel_fail_closed(self):
        for doctype in ("Sales Invoice","Purchase Invoice","Payment Entry","Journal Entry","Purchase Order","Sales Order","Purchase Receipt","Delivery Note","Stock Entry","Expense Claim"):
            if not frappe.db.exists("DocType", doctype):
                # Expense Claim is optional HRMS, absent from ERPNext v16.
                continue
            doc=frappe.get_doc({"doctype":doctype,"docstatus":1})
            with self.assertRaises(DomainError):service.prevent_unsupported_financial_transition(doc,"validate")
            for method in ("before_submit","before_cancel"):
                with self.assertRaises(DomainError):service.prevent_unsupported_financial_transition(doc,method)

    def test_list_and_outsider_scope(self):
        packet=self.request()
        page=service.list_packets(self.company,self.project,limit=1,count_mode="exact")
        self.assertEqual(page["items"][0]["id"],packet["id"]);self.assertEqual(page["total"],1)
        self.login(self.fixture["users"]["outsider"]["user"])
        with self.assertRaises(DomainError) as error:service.read_packet(self.company,self.project,packet["id"])
        self.assertEqual(error.exception.status,404)


def run_lock_order_acceptance():
    """Isolated committed fixture + two genuine MariaDB connections.

    Reviewer holds its canonical Person lock before asking for the Project.
    Requester execution must wait for that Person BEFORE locking the Project;
    otherwise the original inversion deadlocks. No model/provider is involved.
    Invoked explicitly with bench execute, outside transactional unit fixtures.
    """
    import threading
    import time
    from cipher_aec.governance.commands import run_command
    from cipher_aec.governance.context import current_actor, assert_synthetic_site
    from cipher_aec.install import _grant
    assert_synthetic_site()
    if frappe.session.user != "Administrator":
        raise DomainError("administrator_required", "Run synthetic acceptance as the site administrator.", 403)
    fixture=seed_synthetic()
    company=fixture["company"]
    primary=fixture["users"]["primary"]["user"]
    reviewer=fixture["users"]["reviewer"]["user"]
    with trusted_write():
        project=frappe.get_doc({"doctype":"Project","project_name":"Synthetic approval lock-order " + uuid.uuid4().hex[:10],"company":company,"status":"Open","percent_complete_method":"Manual","percent_complete":0}).insert(ignore_permissions=True).name
        for key,abilities in (("primary",["project.read","project.write","approval.request","approval.execute"]),("reviewer",["project.read","approval.decide"])):
            for ability in abilities:_grant(fixture["users"][key]["person"],company,project,ability)
    frappe.set_user(primary)
    packet=service.request_project_status(company,project,"On hold",version_of(frappe.get_doc("Project",project)),str(uuid.uuid4()))["packet"]
    frappe.set_user(reviewer)
    sid="synthetic-approval-concurrent-"+uuid.uuid4().hex
    frappe.session.sid=sid
    frappe.local.request=Request(EnvironBuilder(method="POST",base_url="http://cipher.localhost",headers={"Cookie":"sid="+sid}).get_environ())
    frappe.db.sql("INSERT INTO tabSessions (user,sid,sessiondata,lastupdate,status) VALUES (%s,%s,%s,%s,'Active')",(reviewer,sid,canonical_json({"user":reviewer}),now_datetime()))
    service.decide_packet(company,project,packet["id"],packet["manifest_hash"],"Grant",str(uuid.uuid4()),"Synthetic two-connection qualification")
    frappe.db.commit()
    site=frappe.local.site;sites_path=str(frappe.local.sites_path)
    held=threading.Event();release=threading.Event();started=threading.Event()
    outcomes={};errors=[];operation=str(uuid.uuid4())
    def connection(user,callback):
        try:
            frappe.init(site=site,sites_path=sites_path,force=True);frappe.connect();frappe.set_user(user)
            callback();frappe.db.commit()
        except BaseException as error:
            frappe.db.rollback();errors.append(type(error).__name__+": "+str(error))
        finally:frappe.destroy()
    def reviewer_command():
        current_actor(lock=True)
        held.set()
        if not release.wait(10):raise RuntimeError("reviewer release timed out")
        outcomes["reviewer"]=run_command(company=company,project=project,operation_id=str(uuid.uuid4()),command="approval.lock_order_probe",payload={"packet":packet["id"]},ability="approval.decide",effect=lambda actor,record:{"packet_id":packet["id"],"verified":True})
    def requester_command():
        if not held.wait(10):raise RuntimeError("reviewer lock timed out")
        outcomes["requester_connection"]=frappe.db.sql("SELECT CONNECTION_ID()")[0][0]
        started.set()
        outcomes["requester"]=service.execute_packet(company,project,packet["id"],packet["manifest_hash"],operation)
    review_thread=threading.Thread(target=connection,args=(reviewer,reviewer_command))
    request_thread=threading.Thread(target=connection,args=(primary,requester_command))
    review_thread.start();request_thread.start()
    waiting=False
    try:
        if not started.wait(10):raise RuntimeError("requester did not start")
        deadline=time.monotonic()+5
        while time.monotonic()<deadline:
            rows=frappe.db.sql("SHOW FULL PROCESSLIST",as_dict=True)
            row=next((r for r in rows if r.Id==outcomes.get("requester_connection")),None)
            if row and row.Info and "tabCipher Person" in row.Info and "FOR UPDATE" in row.Info:
                waiting=True;break
            time.sleep(0.02)
    finally:
        release.set();review_thread.join(15);request_thread.join(15)
    if review_thread.is_alive() or request_thread.is_alive():raise RuntimeError("approval concurrency threads did not finish")
    if errors:raise RuntimeError("; ".join(errors))
    if not waiting:raise AssertionError("requester was not observed waiting on participant Person before Project")
    frappe.db.rollback();frappe.set_user(primary)
    consumption=frappe.db.count("Cipher Approval Consumption",{"packet":packet["id"]})
    if consumption!=1 or frappe.db.get_value("Project",project,"status")!="On hold":raise AssertionError("grant/effect not consumed exactly once")
    replay=service.execute_packet(company,project,packet["id"],packet["manifest_hash"],operation)
    if not replay["operation"]["replayed"]:raise AssertionError("committed effect did not replay")
    frappe.db.commit();frappe.set_user("Administrator")
    return {"passed":True,"site_mode":"synthetic","project":project,"packet":packet["id"],"connections":2,"requester_waited_on_participant_before_project":waiting,"reviewer_command_succeeded":outcomes["reviewer"]["verified"],"consumptions":consumption,"project_status":"On hold","exact_retry_replayed":True,"deadlocks":0}

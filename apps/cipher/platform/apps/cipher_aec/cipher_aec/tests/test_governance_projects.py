"""Real Frappe/MariaDB integration tests; no in-memory replacement domain."""

import uuid

import frappe
from frappe.tests import IntegrationTestCase

from cipher_aec.api.contracts import digest, version_of
from cipher_aec.api.errors import DomainError
from cipher_aec.governance.commands import read_operation, run_command
from cipher_aec.governance.context import current_actor, require_project, trusted_write
from cipher_aec.install import seed_synthetic, set_synthetic_duty
from cipher_aec.projects import service


class TestGovernanceProjects(IntegrationTestCase):
    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        self.savepoint = "cipher_test_" + uuid.uuid4().hex
        frappe.db.savepoint(self.savepoint)
        self.fixture = seed_synthetic()
        self.company = self.fixture["company"]
        self.project = self.fixture["project"]
        self.primary = self.fixture["users"]["primary"]["user"]
        self.alias = self.fixture["users"]["alias"]["user"]
        self.outsider = self.fixture["users"]["outsider"]["user"]
        frappe.set_user(self.primary)

    def tearDown(self):
        frappe.set_user("Administrator")
        frappe.db.rollback(save_point=self.savepoint)
        super().tearDown()

    def create(self, **overrides):
        request = {"company": self.company, "project": self.project, "operation_id": str(uuid.uuid4()),
            "expected_version": service.read_project(self.company, self.project)["version"],
            "subject": "Check concrete placement " + str(uuid.uuid4())[:8], "description": "Review source drawing and field quantity."}
        request.update(overrides)
        return request, service.create_task(**request)

    def test_task_and_history_persist_once_with_exact_retry(self):
        request, result = self.create()
        replay = service.create_task(**request)
        self.assertEqual(result["task"]["id"], replay["task"]["id"])
        self.assertFalse(result["operation"]["replayed"])
        self.assertTrue(replay["operation"]["replayed"])
        self.assertEqual(frappe.db.count("Task", {"subject": request["subject"]}), 1)
        self.assertEqual(frappe.db.count("Cipher History Event", {"operation_id": request["operation_id"]}), 1)
        self.assertEqual(read_operation(self.company, self.project, request["operation_id"])["task"]["id"], result["task"]["id"])

    def test_alias_accounts_share_person_and_operation_namespace(self):
        request, result = self.create()
        person = current_actor().person_id
        frappe.set_user(self.alias)
        self.assertEqual(current_actor().person_id, person)
        replay = service.create_task(**request)
        self.assertEqual(replay["task"]["id"], result["task"]["id"])
        self.assertTrue(replay["operation"]["replayed"])

    def test_reused_uuid_changed_payload_conflicts(self):
        request, result = self.create()
        request["subject"] += " changed"
        with self.assertRaises(DomainError) as raised:
            service.create_task(**request)
        self.assertEqual(raised.exception.status, 409)

    def test_uuid_namespace_is_shared_across_commands(self):
        request, result = self.create()
        with self.assertRaises(DomainError) as raised:
            run_command(company=self.company, project=self.project, operation_id=request["operation_id"],
                command="different.command", payload={}, ability="task.create", effect=lambda actor, project: {})
        self.assertEqual(raised.exception.code, "operation_conflict")

    def test_actual_older_project_version_is_stale(self):
        old_version = service.read_project(self.company, self.project)["version"]
        self.create()
        self.assertNotEqual(service.read_project(self.company, self.project)["version"], old_version)
        with self.assertRaises(DomainError) as raised:
            self.create(expected_version=old_version)
        self.assertEqual(raised.exception.status, 412)

    def test_outsider_cannot_read_project_task_history_or_receipt(self):
        request, result = self.create()
        frappe.set_user(self.outsider)
        for call in (lambda: service.read_project(self.company, self.project),
                     lambda: service.list_tasks(self.company, self.project),
                     lambda: service.history(self.company, self.project),
                     lambda: read_operation(self.company, self.project, request["operation_id"])):
            with self.assertRaises(DomainError) as raised:
                call()
            self.assertEqual(raised.exception.status, 404)
        self.assertFalse(frappe.has_permission("Project", "read", doc=self.project, user=self.outsider))
        self.assertFalse(frappe.has_permission("Task", "read", doc=result["task"]["id"], user=self.outsider))

    def test_revoked_duty_blocks_original_receipt_replay(self):
        request, result = self.create()
        frappe.set_user("Administrator")
        set_synthetic_duty(self.primary, self.project, "project.read", 0)
        frappe.set_user(self.primary)
        with self.assertRaises(DomainError) as raised:
            service.create_task(**request)
        self.assertEqual(raised.exception.status, 404)

    def test_disabled_person_blocks_alias(self):
        person = current_actor().person_id
        frappe.set_user("Administrator")
        with trusted_write():
            doc = frappe.get_doc("Cipher Person", person)
            doc.active = 0
            doc.save(ignore_permissions=True)
        frappe.set_user(self.alias)
        with self.assertRaises(DomainError):
            current_actor()

    def test_generic_task_and_governance_write_cannot_bypass_service(self):
        with self.assertRaises(DomainError):
            frappe.get_doc({"doctype": "Task", "project": self.project, "subject": "Bypass"}).insert(ignore_permissions=True)
        with self.assertRaises(DomainError):
            frappe.get_doc({"doctype": "Cipher Person", "display_name": "Forged", "active": 1}).insert(ignore_permissions=True)

    def test_domain_failure_rolls_back_task_and_receipt(self):
        operation_id, subject = str(uuid.uuid4()), "Atomic refusal " + str(uuid.uuid4())
        def effect(actor, project):
            frappe.get_doc({"doctype": "Task", "project": project.name, "subject": subject}).insert(ignore_permissions=True)
            raise DomainError("refused", "Refused after attempted local effect.", 409)
        with self.assertRaises(DomainError):
            run_command(company=self.company, project=self.project, operation_id=operation_id,
                command="test.atomic", payload={}, ability="task.create", effect=effect)
        self.assertFalse(frappe.db.exists("Task", {"subject": subject}))
        self.assertFalse(frappe.db.exists("Cipher Command Receipt", digest({"person": current_actor().person_id, "operation_id": operation_id})))

    def test_original_receipt_cannot_be_saved_or_deleted(self):
        request, result = self.create()
        name = digest({"person": current_actor().person_id, "operation_id": request["operation_id"]})
        with trusted_write(), self.assertRaises(DomainError):
            record = frappe.get_doc("Cipher Command Receipt", name)
            record.command = "forged"
            record.save(ignore_permissions=True)
        with self.assertRaises(DomainError):
            frappe.delete_doc("Cipher Command Receipt", name, ignore_permissions=True)

    def test_unavailable_project_is_not_in_filtered_list(self):
        rows = service.list_projects(self.company)
        self.assertIn(self.project, {row["id"] for row in rows["items"]})
        self.assertNotIn(self.fixture["other_project"], {row["id"] for row in rows["items"]})

    def test_closed_project_preserves_receipt_and_historical_read_but_blocks_new_effect(self):
        request, result = self.create()
        with trusted_write():
            project = frappe.get_doc("Project", self.project)
            # Fixture lifecycle setup bypasses domain commands intentionally;
            # production status saves now require an exact approved manifest.
            frappe.db.set_value("Project", project.name, "status", "Cancelled")
        self.assertEqual(require_project(self.company, self.project, ability="document.read").name, self.project)
        replay = service.create_task(**request)
        self.assertEqual(replay["task"]["id"], result["task"]["id"])
        self.assertTrue(replay["operation"]["replayed"])
        with self.assertRaises(DomainError) as raised:
            self.create()
        self.assertEqual(raised.exception.code, "project_closed")

    def test_effect_guard_runs_under_command_lock_and_is_not_reapplied_to_receipt(self):
        calls = []
        args = {"company": self.company, "project": self.project, "operation_id": str(uuid.uuid4()),
            "expected_version": service.read_project(self.company, self.project)["version"], "subject": "Guarded task"}
        def guard(actor, project):
            calls.append(project.name)
        result = service.create_task(**args, guard=guard)
        self.assertEqual(calls, [self.project])
        def stale_guard(actor, project):
            raise DomainError("stale", "Original sources changed.", 412)
        replay = service.create_task(**args, guard=stale_guard)
        self.assertEqual(result["task"]["id"], replay["task"]["id"])

    def test_generic_assignment_cannot_bypass_command_and_history(self):
        from frappe.desk.form.assign_to import add
        request, result = self.create()
        task_id = result["task"]["id"]
        with self.assertRaises(DomainError):
            add({"doctype": "Task", "name": task_id, "assign_to": [self.primary], "description": "Bypass assignment", "notify": 0})
        self.assertFalse(frappe.db.exists("ToDo", {"reference_type": "Task", "reference_name": task_id}))

    def test_r0_http_catalog_denies_upstream_mappers_and_arbitrary_rpc(self):
        from cipher_aec.api.boundary import allowed_request
        self.assertFalse(allowed_request("/api/method/erpnext.projects.doctype.task.task.make_timesheet", "POST"))
        self.assertFalse(allowed_request("/api/method/frappe.desk.form.assign_to.add", "POST"))
        self.assertFalse(allowed_request("/api/resource/Task", "POST"))
        self.assertFalse(allowed_request("/api/v2/method/frappe.client.get", "GET"))
        self.assertTrue(allowed_request("/api/method/cipher_aec.api.v1.create_task", "POST"))
        self.assertFalse(allowed_request("/api/resource/Task/TASK-0001", "GET"))
        self.assertTrue(allowed_request("/api/method/cipher_aec.api.v1.task", "GET"))
        self.assertFalse(allowed_request("/", "GET", legacy_cmd="erpnext.projects.doctype.task.task.make_timesheet"))
        self.assertFalse(allowed_request("/api/method/cipher_aec.api.v1.session", "GET", legacy_cmd="frappe.client.get"))
        self.assertFalse(allowed_request("/", "POST", legacy_cmd=""))

    def test_restore_quarantine_allows_readback_but_refuses_new_commands_and_dispatch(self):
        from cipher_aec.integrations.outbox import dispatch_pending, deliver
        request, result = self.create()
        old = frappe.conf.get("cipher_execution_quarantined")
        frappe.conf.cipher_execution_quarantined = 1
        try:
            self.assertEqual(service.read_project(self.company, self.project)["id"], self.project)
            self.assertEqual(service.create_task(**request)["task"]["id"], result["task"]["id"])
            with self.assertRaises(DomainError) as raised:
                self.create()
            self.assertEqual(raised.exception.code, "execution_quarantined")
            self.assertEqual(dispatch_pending(), 0)
            with self.assertRaises(DomainError) as raised:
                deliver("unclaimed-operation")
            self.assertEqual(raised.exception.code, "execution_quarantined")
        finally:
            frappe.conf.cipher_execution_quarantined = old

    def test_task_keyset_pages_are_bounded_signed_and_scoped(self):
        self.create(subject="First paged task")
        self.create(subject="Second paged task")
        first = service.list_tasks(self.company, self.project, limit=1, count_mode="exact")
        self.assertEqual(len(first["items"]), 1)
        self.assertGreaterEqual(first["total"], 2)
        self.assertIsNotNone(first["next_cursor"])
        second = service.list_tasks(self.company, self.project, limit=1, cursor=first["next_cursor"])
        self.assertEqual(len(second["items"]), 1)
        self.assertNotEqual(first["items"][0]["id"], second["items"][0]["id"])
        self.assertIsNone(second["total"])
        with self.assertRaises(DomainError):
            service.list_tasks(self.company, self.project, cursor=first["next_cursor"] + "x")
        with self.assertRaises(DomainError):
            service.history(self.company, self.project, cursor=first["next_cursor"])
        frappe.set_user(self.alias)
        with self.assertRaises(DomainError):
            service.list_tasks(self.company, self.project, cursor=first["next_cursor"])

    def test_project_and_history_keyset_queries_use_native_scope_and_explicit_counts(self):
        self.create()
        self.create()
        projects = service.list_projects(self.company, limit=1, count_mode="exact")
        # Other isolated domain acceptance Projects may grant this same user
        # access. Compare the API to current native-permission results rather
        # than assuming the seeded site contains only one accessible Project.
        native = frappe.get_list("Project", filters={"company": self.company}, fields=["name"], order_by="project_name asc,name asc", limit_page_length=200)
        self.assertLess(len(native), 200, "Use a larger isolated fixture boundary for this test")
        self.assertEqual(projects["total"], len(native))
        self.assertEqual(projects["items"][0]["id"], native[0].name)
        first = service.history(self.company, self.project, limit=1, count_mode="exact")
        self.assertEqual(len(first["items"]), 1)
        self.assertGreaterEqual(first["total"], 2)
        second = service.history(self.company, self.project, limit=1, cursor=first["next_cursor"])
        self.assertNotEqual(first["items"][0]["id"], second["items"][0]["id"])

    def test_document_command_requires_current_read_before_new_effect_and_receipt(self):
        operation = str(uuid.uuid4())
        call = dict(company=self.company, project=self.project, operation_id=operation,
            command="document.guard.check", payload={}, ability="document.write", effect=lambda actor, project: {"marker": "private-source"})
        run_command(**call)
        frappe.set_user("Administrator")
        set_synthetic_duty(self.primary, self.project, "document.read", 0)
        frappe.set_user(self.primary)
        with self.assertRaises(DomainError) as raised:
            run_command(**call)
        self.assertEqual(raised.exception.status, 403)
        with self.assertRaises(DomainError):
            read_operation(self.company, self.project, operation)
        call["operation_id"] = str(uuid.uuid4())
        with self.assertRaises(DomainError):
            run_command(**call)

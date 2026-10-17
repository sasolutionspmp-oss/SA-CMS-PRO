"""Host checks for the bounded native Task contract; no Frappe replacement."""

from datetime import datetime
import json
from pathlib import Path
import unittest

from jsonschema import Draft202012Validator

from cipher_aec.api.catalog import ROUTES
from cipher_aec.api.errors import DomainError
from cipher_aec.api.openapi import generate
from cipher_aec.projects.task_rules import assignment_state, check_task, status_value, task_version


class Task(dict):
    __getattr__ = dict.__getitem__


class TaskControlContracts(unittest.TestCase):
    def task(self, **changes):
        return Task(status="Open", modified=datetime(2026, 10, 17), **changes)

    def test_only_explicit_native_manual_statuses_are_accepted(self):
        for status in ("Open", "Working", "Pending Review", "Completed"):
            self.assertEqual(status_value(status), status)
        for status in ("Overdue", "Template", "Cancelled", "Done", "closed", None):
            with self.subTest(status=status), self.assertRaises(DomainError):
                status_value(status)

    def test_task_version_is_required_and_exact(self):
        task = self.task()
        check_task(task, task_version(task))
        for version, code in ((None, "version_required"), ("older", "stale_version")):
            with self.subTest(version=version), self.assertRaises(DomainError) as raised:
                check_task(task, version)
            self.assertEqual(raised.exception.code, code)

    def test_templates_groups_and_parent_linked_tasks_require_qualified_workflow(self):
        for field, value in (("is_template", 1), ("is_group", 1), ("parent_task", "PARENT")):
            with self.subTest(field=field), self.assertRaises(DomainError) as raised:
                task = self.task(**{field: value})
                check_task(task, task_version(task))
            self.assertEqual(raised.exception.code, "task_structure_unqualified")

    def test_unassigned_task_has_no_implicit_assignment(self):
        self.assertIsNone(assignment_state(self.task(), []))

    def test_native_change_without_modified_timestamp_still_invalidates_task_version(self):
        task = self.task()
        before = task_version(task)
        task['status'] = "Overdue"
        self.assertNotEqual(before, task_version(task))
        self.assertEqual(task['modified'], datetime(2026, 10, 17))
        with self.assertRaises(DomainError) as raised:
            check_task(task, before)
        self.assertEqual(raised.exception.code, 'stale_version')

    def test_owned_assignment_requires_exact_person_user_and_native_todo(self):
        task = self.task(cipher_assignee_person="PERSON", cipher_assignee_user="alias@example.invalid", cipher_assignment_todo="TODO", _assign='["alias@example.invalid"]')
        self.assertEqual(assignment_state(task, [{"name": "TODO", "allocated_to": "alias@example.invalid"}]),
            {"person": "PERSON", "user": "alias@example.invalid", "todo": "TODO"})

    def test_unknown_duplicate_or_mismatched_native_assignment_is_preserved_by_refusal(self):
        task = self.task(cipher_assignee_person="PERSON", cipher_assignee_user="user", cipher_assignment_todo="TODO", _assign='["user"]')
        cases = [(self.task(_assign='["other"]'), [{"name": "OTHER", "allocated_to": "other"}]),
            (task, []), (task, [{"name": "OTHER", "allocated_to": "user"}]),
            (task, [{"name": "TODO", "allocated_to": "user"}, {"name": "OTHER", "allocated_to": "user"}]),
            (task, [{"name": "TODO", "allocated_to": "user"}, {"name": "BLANK", "allocated_to": None}]),
            (self.task(_assign="invalid"), [])]
        for doc, rows in cases:
            with self.subTest(rows=rows), self.assertRaises(DomainError) as raised:
                assignment_state(doc, rows)
            self.assertEqual(raised.exception.code, "assignment_conflict")

    def test_assignment_and_status_routes_are_commands_with_closed_requests(self):
        generated = generate()
        for name in ("assign_task", "update_task_status"):
            route = "cipher_aec.api.v1." + name
            self.assertTrue(ROUTES[route].command)
            operation = generated["paths"]["/api/method/" + route]["post"]
            schema = operation["requestBody"]["content"]["application/json"]["schema"]
            self.assertFalse(schema["additionalProperties"])
            self.assertIn("expected_version", schema["required"])
            self.assertIn("Idempotency-Key", {row["name"] for row in operation["parameters"]})
        person = generated["paths"]["/api/method/cipher_aec.api.v1.assign_task"]["post"]["requestBody"]["content"]["application/json"]["schema"]["properties"]["assignee_person"]
        self.assertEqual(person["type"], ["string", "null"])
        status = generated["paths"]["/api/method/cipher_aec.api.v1.update_task_status"]["post"]["requestBody"]["content"]["application/json"]["schema"]["properties"]["status"]
        self.assertNotIn("Cancelled", status["enum"])

    def test_published_task_and_choices_do_not_expose_user_aliases(self):
        path = Path(__file__).resolve().parents[1] / "api/schema.json"
        definitions = json.loads(path.read_text())["$defs"]
        def validate(name, value):
            Draft202012Validator({"$defs": definitions, "$ref": "#/$defs/" + name}).validate(value)
        task = {"id": "TASK", "project": "PROJECT", "subject": "Review", "status": "Open", "version": "v1", "description": "Exact text", "assignees": [{"id": "PERSON", "display_name": "Person"}], "assignment_conflict": False}
        validate("Task", task)
        historical = {key:value for key,value in task.items() if key not in {'assignees','assignment_conflict'}}
        validate("Task", historical)
        validate("CurrentTask", task)
        with self.assertRaises(Exception):
            validate("CurrentTask", historical)
        response = {"task": task, "project_version": "project-version", "operation": {"id":"8faaf816-f2f9-462c-a290-8789cb19a42f", "status":"succeeded", "replayed":False}}
        validate("TaskControlResponse", response)
        with self.assertRaises(Exception):
            validate("TaskControlResponse", {**response, "task": historical})
        validate("TaskChoices", {"people": task["assignees"], "statuses": ["Open", "Completed"], "capabilities": ["task.assign"]})
        task["assignees"][0]["user"] = "alias@example.invalid"
        with self.assertRaises(Exception):
            validate("Task", task)

    def test_raw_task_resource_is_not_in_product_read_admission(self):
        import ast
        path = Path(__file__).resolve().parents[1] / "api/boundary.py"
        tree = ast.parse(path.read_text())
        reads = next(node for node in tree.body if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == 'RESOURCE_READS' for target in node.targets))
        self.assertNotIn('Task', ast.literal_eval(reads.value.args[0]))


if __name__ == "__main__":
    unittest.main()

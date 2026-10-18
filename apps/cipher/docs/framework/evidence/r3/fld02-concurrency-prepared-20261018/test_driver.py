"""Pure driver contracts only; never enables execution or loads native_worker.

These tests are independent from the permissive lease red scaffold. Hand-written
ready rows exercise validation; they are never represented as native evidence.
"""
import ast
import contextlib
import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest

ROOT = Path(__file__).absolute().parent
spec = importlib.util.spec_from_file_location("pure_native_driver", ROOT / "native_driver.py")
driver = importlib.util.module_from_spec(spec)
spec.loader.exec_module(driver)
OP = "2b39f3bb-60b4-4cef-a801-00fb105549e3"


class DriverContracts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="fld02-driver-", dir="/dev/shm")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.admission = {"lease": {"run_id": "original-run", "epoch": "epoch-1",
            "runtime_id": "operator-runtime", "artifact_dir": str(self.root),
            "site": "synthetic.local", "database_name": "synthetic_database",
            "scope": {"company": "Synthetic Company", "project": "Synthetic Project",
                "users": [{"user": "a@synthetic.example", "profile": "A", "person": "Shared Person"},
                          {"user": "b@synthetic.example", "profile": "B", "person": "Shared Person"}]}},
            "request": {"schema": "cipher.fld02.native.concurrent.request.v1", "scenario": "stage_race",
                "operation_uuid": OP, "body_sha256": "b" * 64,
                "body": {"test": "pure fixture, never executed"}, "change": None}}

    def rows(self):
        identity = driver.identity(self.admission)
        ready, prepared = {}, {}
        for role, connection in [("A", 101), ("B", 202)]:
            base = {key: identity[key] for key in ("run_id", "epoch", "runtime_id", "operation_uuid", "body_sha256")}
            ready[role] = {**base, "schema": "cipher.fld02.native.concurrent.ready.v1", "role": role,
                "connection_id": connection, "site": "synthetic.local", "database_name": "synthetic_database",
                "frappe_version": "16.52.0", "version": "10.11.14-MariaDB", "isolation": "READ-COMMITTED"}
            prepared[role] = {**base, "schema": "cipher.fld02.native.concurrent.prepared.v1", "role": role,
                              "connection_id": connection}
        return ready, prepared

    def test_identity_keeps_original_operation_body_scope_and_request_digest(self):
        identity = driver.identity(self.admission)
        self.assertEqual(identity["operation_uuid"], OP)
        self.assertEqual(identity["body_sha256"], "b" * 64)
        self.assertEqual(identity["scope"], self.admission["lease"]["scope"])
        self.assertEqual(identity["request_sha256"], driver.lease_guard.sha_json(self.admission["request"]))
        changed = copy.deepcopy(self.admission)
        changed["request"]["body"] = {"test": "different request"}
        self.assertNotEqual(driver.identity(changed)["request_sha256"], identity["request_sha256"])

    def test_reservation_survives_company_project_run_epoch_body_and_alias_changes(self):
        original = driver.reservation_path(self.admission)
        changed = copy.deepcopy(self.admission)
        changed["lease"].update(run_id="different-run", epoch="epoch-2", runtime_id="other-runtime")
        changed["request"].update(body_sha256="c" * 64, scenario="apply_race")
        changed["lease"]["scope"].update(company="Other Company", project="Other Project")
        changed["lease"]["scope"]["users"][0]["user"] = "another-alias@synthetic.example"
        self.assertEqual(driver.reservation_path(changed), original)
        driver.exclusive_json(original, {"state": "incomplete", "outcome": "unknown", "attempts": 1})
        before = original.read_bytes()
        with self.assertRaises(FileExistsError):
            driver.exclusive_json(driver.reservation_path(changed), {"state": "ready"})
        self.assertEqual(original.read_bytes(), before)

    def test_only_explicit_person_and_uuid_separate_native_reservations(self):
        original = driver.reservation_path(self.admission)
        for field in ("person", "operation_uuid"):
            with self.subTest(field=field):
                changed = copy.deepcopy(self.admission)
                if field == "person":
                    changed["lease"]["scope"]["users"][0][field] = "Other Explicit Person"
                elif field == "operation_uuid":
                    changed["request"][field] = "8cb0c717-a94c-414e-b209-548bd87231f4"
                self.assertNotEqual(driver.reservation_path(changed), original)
        self.assertEqual(original.parent, self.root)
        self.assertEqual(len(original.name), len("operation-") + 64 + len(".json"))

    def test_exclusive_reservation_preserves_partial_and_empty_evidence(self):
        path = driver.reservation_path(self.admission)
        for existing in (b"", b"{", b'{"outcome":"unknown","attempts":1}'):
            with self.subTest(existing=existing):
                # Each fixture is a distinct original operation reservation.
                candidate = self.root / (str(len(existing)) + ".json")
                candidate.write_bytes(existing)
                candidate.chmod(0o600)
                with self.assertRaises(FileExistsError):
                    driver.exclusive_json(candidate, {"state": "ready"})
                self.assertEqual(candidate.read_bytes(), existing)
        self.assertFalse(path.exists())

    def test_reservation_private_mode_symlink_and_parent_denial(self):
        path = driver.reservation_path(self.admission)
        driver.exclusive_json(path, {"outcome": "unknown"})
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertEqual(json.loads(path.read_text()), {"outcome": "unknown"})
        alias = self.root / "alias.json"
        alias.symlink_to(path)
        with self.assertRaises(FileExistsError):
            driver.exclusive_json(alias, {"state": "ready"})
        self.assertEqual(json.loads(path.read_text()), {"outcome": "unknown"})
        self.root.chmod(0o755)
        try:
            with self.assertRaises(ValueError):
                driver.exclusive_json(self.root / "unprivate.json", {})
        finally:
            self.root.chmod(0o700)

    def test_barrier_admits_two_observed_rc_connections_only(self):
        ready, prepared = self.rows()
        released = driver.barrier(self.admission, ready, prepared)
        self.assertEqual(released["connections"], {"A": 101, "B": 202})
        self.assertEqual(released["operation_uuid"], OP)
        self.assertEqual(released["body_sha256"], "b" * 64)

    def test_barrier_rejects_ready_or_prepared_identity_drift(self):
        for kind in ("ready", "prepared"):
            for role in ("A", "B"):
                for key in ("run_id", "epoch", "runtime_id", "operation_uuid", "body_sha256", "schema", "role"):
                    with self.subTest(kind=kind, role=role, key=key):
                        ready, prepared = self.rows()
                        (ready if kind == "ready" else prepared)[role][key] = "different"
                        with self.assertRaises(ValueError):
                            driver.barrier(self.admission, ready, prepared)

    def test_barrier_requires_exact_role_sets_and_both_preparations(self):
        for kind in ("ready", "prepared"):
            with self.subTest(kind=kind, extra=True):
                ready, prepared = self.rows()
                (ready if kind == "ready" else prepared)["OBSERVE"] = copy.deepcopy(ready["A"])
                with self.assertRaises(ValueError):
                    driver.barrier(self.admission, ready, prepared)
            with self.subTest(kind=kind, missing=True):
                ready, prepared = self.rows()
                del (ready if kind == "ready" else prepared)["B"]
                with self.assertRaises((ValueError, KeyError)):
                    driver.barrier(self.admission, ready, prepared)

    def test_barrier_requires_actual_runtime_and_read_committed(self):
        for field, value in [("site", "other.local"), ("database_name", "other_database"),
            ("frappe_version", "16.52.1"), ("version", "8.0 MySQL"),
            ("isolation", "REPEATABLE-READ"), ("isolation", None)]:
            for role in ("A", "B"):
                with self.subTest(field=field, value=value, role=role):
                    ready, prepared = self.rows()
                    ready[role][field] = value
                    with self.assertRaises(ValueError):
                        driver.barrier(self.admission, ready, prepared)

    def test_barrier_rejects_reused_reconnected_or_nonphysical_connection_ids(self):
        for role in ("A", "B"):
            for value in (0, -1, "101", True, None):
                with self.subTest(role=role, value=value):
                    ready, prepared = self.rows()
                    ready[role]["connection_id"] = prepared[role]["connection_id"] = value
                    with self.assertRaises(ValueError):
                        driver.barrier(self.admission, ready, prepared)
            ready, prepared = self.rows()
            prepared[role]["connection_id"] += 1
            with self.assertRaises(ValueError):
                driver.barrier(self.admission, ready, prepared)
        ready, prepared = self.rows()
        ready["B"]["connection_id"] = prepared["B"]["connection_id"] = 101
        with self.assertRaises(ValueError):
            driver.barrier(self.admission, ready, prepared)
        ready, prepared = self.rows()
        ready["A"]["connection_id"], prepared["A"]["connection_id"] = 1, True
        with self.assertRaises(ValueError):
            driver.barrier(self.admission, ready, prepared)

    def test_default_main_disables_before_any_native_import(self):
        before = {name for name in sys.modules if name == "native_worker" or name == "frappe" or name.startswith("frappe.")}
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(driver.main([]), 0)
        after = {name for name in sys.modules if name == "native_worker" or name == "frappe" or name.startswith("frappe.")}
        self.assertEqual(after, before)
        self.assertIn("DISABLED", output.getvalue())
        self.assertIn("UNRUN", output.getvalue())
        self.assertEqual(list(self.root.iterdir()), [])

    def test_source_has_one_unlooped_business_call_and_no_uuid_generation(self):
        business_calls = []
        for name in ("native_driver.py", "native_worker.py"):
            tree = ast.parse((ROOT / name).read_text(), filename=name)
            parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                callee = node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id if isinstance(node.func, ast.Name) else ""
                self.assertNotIn(callee, {"uuid1", "uuid3", "uuid4", "uuid5", "uuid6", "uuid7", "uuid8"})
                if any(isinstance(n, ast.Attribute) and n.attr in {"stage_capture", "apply_capture"}
                       for n in ast.walk(node.func)):
                    business_calls.append((name, node.lineno))
                    current = node
                    while current in parents:
                        current = parents[current]
                        self.assertNotIsInstance(current, (ast.For, ast.AsyncFor, ast.While, ast.comprehension),
                                                 "A business command must never be retried in a loop")
        self.assertEqual(len(business_calls), 1, business_calls)
        self.assertEqual(business_calls[0][0], "native_worker.py")

    def test_source_child_preserves_parent_admission_and_reserves_before_native_load(self):
        tree = ast.parse((ROOT / "native_driver.py").read_text())
        main = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "main")
        child_branches = [node for node in ast.walk(main) if isinstance(node, ast.If)
                          and isinstance(node.test, ast.Attribute) and node.test.attr == "worker"]
        original = next(node for node in child_branches if any(
            isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute) and call.func.attr == "private_json"
            and any(isinstance(part, ast.Constant) and part.value == "admission.json" for part in ast.walk(call))
            for statement in node.body for call in ast.walk(statement)))
        body = [node for statement in original.body for node in ast.walk(statement)]
        self.assertTrue(any(isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                            and node.func.attr == "recheck" for node in body))
        self.assertFalse(any(isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                             and node.func.attr == "admit" for node in body), "Child must not renew admission")
        starts = [node for node in ast.walk(main) if isinstance(node, ast.Call)
                  and isinstance(node.func, ast.Name) and node.func.id == "exclusive_json"
                  and any(isinstance(part, ast.Constant) and part.value == "started-" for part in ast.walk(node))]
        native_loads = [node for node in ast.walk(main) if isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Name) and node.func.id == "_source_module"
                        and node.args and isinstance(node.args[0], ast.Constant) and node.args[0].value == "native_worker"]
        self.assertEqual(len(starts), 1)
        self.assertEqual(len(native_loads), 1)
        self.assertLess(starts[0].lineno, native_loads[0].lineno)
        exclusive = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "exclusive_json")
        self.assertTrue(any(isinstance(node, ast.Attribute) and node.attr == "O_EXCL" for node in ast.walk(exclusive)))


if __name__ == "__main__":
    unittest.main(verbosity=2)

"""Pure fail-closed guard tests. No native, database, network, or provider calls."""
import copy
import datetime as dt
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch

RED = "--red-scaffold" in sys.argv
if RED:
    sys.argv.remove("--red-scaffold")
    import guards_red_scaffold as guard
else:
    import lease as guard

FIXED = dt.datetime(2026, 10, 18, 8, 0, tzinfo=dt.timezone.utc)
OP = "2b39f3bb-60b4-4cef-a801-00fb105549e3"


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False, allow_nan=False).encode()).hexdigest()


class Guards(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="fld02-guards-", dir="/dev/shm")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.app = self.root / "app"
        self.app.mkdir(mode=0o700)
        self.source = self.app / "source.py"
        self.source.write_text("# fixture source only\n")
        self.driver = self.root / "native_driver.py"
        self.drivers = [self.root / name for name in ["native_driver.py", "native_worker.py", "inventory.py", "lease.py"]]
        for source in self.drivers:
            source.write_text("# fixture driver only\n")
        self.guard = guard
        if not RED:
            guard_copy = self.root / "lease.py"
            guard_copy.write_text(Path(guard.__file__).read_text())
            spec = importlib.util.spec_from_file_location("pure_guard_fixture", guard_copy)
            self.guard = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(self.guard)
        self.clock = patch.object(self.guard, "now", return_value=FIXED)
        self.clock.start()
        self.addCleanup(self.clock.stop)
        self.output = self.root / "output"
        self.output.mkdir(mode=0o700)
        self.runtime_source = self.root / "runtime_source.py"
        self.runtime_source.write_text("# fixture runtime source only\n")
        self.driver_caches = list(self.root.glob("*.pyc")) + list((self.root / "__pycache__").glob("*.pyc"))
        self.manifest = {
            "schema": "cipher.fld02.native.concurrent.sources.v1",
            "app_root": str(self.app), "driver_files": [str(p) for p in self.drivers],
            "runtime_files": [str(p) for p in [self.runtime_source] + self.driver_caches],
            "files": [{"path": str(p), "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
                      for p in [self.source] + self.drivers + [self.runtime_source] + self.driver_caches],
        }
        self.request = {
            "schema": "cipher.fld02.native.concurrent.request.v1", "operation_uuid": OP,
            "scenario": "stage_race", "body": {"company": "Synthetic Company",
            "project": "Synthetic Project", "operation_id": OP, "envelope": {
                "schema": "cipher.field.offline.v1", "device_id": "f6bb8479-4505-490c-a97a-9e6f58eb3fb3",
                "capture_id": "8cb0c717-a94c-414e-b209-548bd87231f4", "company": "Synthetic Company",
                "project": "Synthetic Project", "actor_person": "Person A", "actor_user": "actor@synthetic.example",
                "captured_at": FIXED.isoformat(), "command": {"proposal": "synthetic-case"}}},
            "body_sha256": "", "change": None,
        }
        self.request["body_sha256"] = digest(self.request["body"])
        self.scope = {"company": "Synthetic Company", "project": "Synthetic Project",
                      "users": [{"user": "actor@synthetic.example", "profile": "A",
                                 "person": "Person A"},
                                {"user": "other@synthetic.example", "profile": "B",
                                 "person": "Person A"}]}
        self.receipt = {
            "schema": "cipher.fld02.native.concurrent.runtime.v1", "authority": "local_root",
            "runtime_id": "operator-runtime", "build_sha256": "a" * 64, "epoch": "epoch-1",
            "source_manifest_sha256": digest(self.manifest),
        }
        self.epoch = {"schema": "cipher.fld02.native.concurrent.epoch.v1",
                      "runtime_id": "operator-runtime", "epoch": "epoch-1"}
        self.lease = {
            "schema": "cipher.fld02.native.concurrent.lease.v1", "enabled": True,
            "authority": "local_root", "issued_at": FIXED.isoformat(),
            "expires_at": (FIXED + dt.timedelta(minutes=15)).isoformat(),
            "max_duration_seconds": 60, "runtime_id": "operator-runtime",
            "build_sha256": "a" * 64, "epoch": "epoch-1",
            "source_manifest_sha256": digest(self.manifest),
            "runtime_receipt_path": str(self.root / "runtime.json"),
            "epoch_path": str(self.root / "epoch.json"),
            "source_manifest_path": str(self.root / "sources.json"),
            "scope": self.scope, "request_sha256": digest(self.request),
            "site": "synthetic.local", "sites_path": str(self.root),
            "python_executable": str(Path(sys.executable).resolve()), "database_name": "synthetic_db",
            "artifact_dir": str(self.output), "run_id": "guard-test-run", "statement_timeout_seconds": 5,
            "lock_wait_timeout_seconds": 5, "max_inventory_rows": 100,
            "max_file_bytes": 1048576,
        }
        self.flush()

    def write(self, name, value):
        p = self.root / name
        p.write_text(json.dumps(value, allow_nan=False))
        p.chmod(0o600)
        return p

    def flush(self):
        self.write("runtime.json", self.receipt)
        self.write("epoch.json", self.epoch)
        self.write("sources.json", self.manifest)
        self.write("request.json", self.request)
        self.write("lease.json", self.lease)

    def apply_request(self, scenario="apply_race", change=None):
        self.request.update(scenario=scenario, change=change, body={
            "company": self.scope["company"], "project": self.scope["project"],
            "operation_id": OP, "capture_id": OP, "expected_version": "d" * 64})
        self.request["body_sha256"] = digest(self.request["body"])
        self.lease["request_sha256"] = digest(self.request)
        self.flush()

    def admit(self, **kwargs):
        return self.guard.admit(str(self.root / "lease.json"), str(self.root / "request.json"),
                           **kwargs)

    def denied(self, **kwargs):
        with self.assertRaises((ValueError, OSError)):
            self.admit(execute=True, **kwargs)

    def test_valid_explicit_admission(self):
        result = self.admit(execute=True)
        self.assertEqual(result["request"]["operation_uuid"], OP)
        self.assertEqual(result["lease"]["epoch"], "epoch-1")

    def test_default_disabled(self):
        with self.assertRaises((ValueError, OSError)):
            self.admit()

    def test_lease_disabled_or_wrong_authority(self):
        for key, value in [("enabled", False), ("enabled", 1), ("authority", "worker"),
                           ("schema", "other")]:
            with self.subTest(key=key, value=value):
                lease = copy.deepcopy(self.lease)
                lease[key] = value
                self.write("lease.json", lease)
                self.denied()

    def test_expiry_and_duration_bounds(self):
        for key, value in [("expires_at", FIXED.isoformat()),
                           ("expires_at", (FIXED + dt.timedelta(hours=2)).isoformat()),
                           ("expires_at", "2026-10-18T09:00:00"),
                           ("issued_at", (FIXED + dt.timedelta(seconds=1)).isoformat()),
                           ("max_duration_seconds", 0), ("max_duration_seconds", 121),
                           ("max_duration_seconds", True), ("max_duration_seconds", "60")]:
            with self.subTest(key=key, value=value):
                lease = copy.deepcopy(self.lease)
                lease[key] = value
                self.write("lease.json", lease)
                self.denied()

    def test_json_files_private_regular_and_parent_private(self):
        for name in ["lease.json", "request.json", "runtime.json", "epoch.json", "sources.json"]:
            with self.subTest(name=name):
                path = self.root / name
                path.chmod(0o644)
                self.denied()
                path.chmod(0o600)
        self.root.chmod(0o755)
        try:
            self.denied()
        finally:
            self.root.chmod(0o700)

    def test_non_owned_private_file_denied(self):
        real_stat = os.fstat
        def foreign_stat(fd):
            data = real_stat(fd)
            return os.stat_result((data.st_mode, data.st_ino, data.st_dev, data.st_nlink,
                                   data.st_uid + 1, data.st_gid, data.st_size,
                                   data.st_atime, data.st_mtime, data.st_ctime))
        if RED:
            self.denied()
        else:
            with patch.object(self.guard.os, "fstat", side_effect=foreign_stat):
                self.denied()

    def test_control_symlink_denied(self):
        path = self.root / "request.json"
        path.rename(self.root / "request-original.json")
        path.symlink_to(self.root / "request-original.json")
        self.denied()

    def test_control_parent_symlink_denied(self):
        alias = self.root / "alias"
        alias.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises((ValueError, OSError)):
            self.guard.admit(str(alias / "lease.json"), str(alias / "request.json"), execute=True)

    def test_request_digest_and_envelope_digest_pinned(self):
        self.request["body"]["envelope"]["command"]["proposal"] = "changed"
        self.write("request.json", self.request)
        self.denied()
        self.lease["request_sha256"] = digest(self.request)
        self.write("lease.json", self.lease)
        self.denied()

    def test_operation_uuid_is_original_canonical_and_required(self):
        for value in ["", "new-operation", OP.upper(), None]:
            with self.subTest(value=value):
                self.request["operation_uuid"] = value
                self.lease["request_sha256"] = digest(self.request)
                self.flush()
                self.denied()

    def test_scope_requires_synthetic_users_and_person_bindings(self):
        cases = [dict(self.scope, company=""), dict(self.scope, project=""),
                 dict(self.scope, users=[])]
        for key, value in [("user", "actor@example.com"), ("profile", ""), ("person", "")]:
            scope = copy.deepcopy(self.scope)
            scope["users"][0][key] = value
            cases.append(scope)
        for scope in cases:
            with self.subTest(scope=scope):
                lease = dict(self.lease, scope=scope)
                self.write("lease.json", lease)
                self.denied()

    def test_runtime_and_epoch_identity_pins(self):
        for key, value in [("runtime_id", "different"), ("build_sha256", "b" * 64),
                           ("epoch", "stale"), ("source_manifest_sha256", "c" * 64),
                           ("authority", "worker")]:
            with self.subTest(key=key):
                self.write("runtime.json", dict(self.receipt, **{key: value}))
                self.denied()
        self.write("runtime.json", self.receipt)
        self.write("epoch.json", dict(self.epoch, epoch="epoch-2"))
        self.denied()

    def test_separate_control_file_identities(self):
        self.lease["epoch_path"] = self.lease["runtime_receipt_path"]
        self.write("lease.json", self.lease)
        self.denied()

    def test_source_manifest_hash_and_source_bytes_pinned(self):
        self.source.write_text("# changed\n")
        self.denied()
        self.source.write_text("# fixture source only\n")
        self.manifest["files"][0]["sha256"] = "0" * 64
        self.write("sources.json", self.manifest)
        self.denied()

    def test_full_app_manifest_detects_unlisted_file(self):
        (self.app / "unlisted.py").write_text("# added\n")
        self.denied()

    def test_source_symlink_denied(self):
        target = self.root / "original-source.py"
        self.source.rename(target)
        self.source.symlink_to(target)
        self.denied()

    def test_duplicate_source_entries_denied(self):
        self.manifest["files"].append(self.manifest["files"][0])
        self.lease["source_manifest_sha256"] = digest(self.manifest)
        self.receipt["source_manifest_sha256"] = digest(self.manifest)
        self.flush()
        self.denied()

    def test_duplicate_json_keys_denied(self):
        p = self.root / "lease.json"
        raw = p.read_text()
        p.write_text('{"enabled":false,' + raw[1:])
        self.denied()

    def test_native_apply_version_digest_and_original_capture_operation(self):
        self.apply_request()
        self.assertEqual(self.admit(execute=True)["request"]["body"]["expected_version"], "d" * 64)
        for field, value in [("expected_version", 0), ("expected_version", "d" * 63),
                             ("capture_id", "8cb0c717-a94c-414e-b209-548bd87231f4")]:
            with self.subTest(field=field, value=value):
                self.apply_request()
                self.request["body"][field] = value
                self.request["body_sha256"] = digest(self.request["body"])
                self.lease["request_sha256"] = digest(self.request)
                self.flush()
                self.denied()

    def test_change_can_only_disable_or_reassign_explicit_extra_person(self):
        change = {"doctype": "Cipher Identity Binding", "name": "Binding A",
                  "expected_native_digest": "e" * 64, "updates": {"active": 0}}
        self.apply_request("binding_race", change)
        self.admit(execute=True)
        for updates in [{"active": 1}, {"active": False}, {"person": "Undeclared"},
                        {"person": "Person A"}, {"active": 0, "person": "Person B"}, {"password": "x"}]:
            with self.subTest(updates=updates):
                self.apply_request("binding_race", dict(change, updates=updates))
                self.denied()
        self.scope["extra_person"] = "Person Explicit"
        self.apply_request("binding_race", dict(change, updates={"person": "Person Explicit"}))
        self.admit(execute=True)

    def test_administrator_allowed_only_profile_b_change(self):
        self.scope["users"][1]["user"] = "Administrator"
        self.flush()
        self.denied()
        self.apply_request("duty_race", {"doctype": "Cipher Project Duty", "name": "Duty A",
            "expected_native_digest": "f" * 64, "updates": {"active": 0}})
        self.admit(execute=True)

    def test_scope_and_operation_envelope_contradictions_denied(self):
        original = copy.deepcopy(self.request)
        for field, value in [("company", "Other Company"), ("project", "Other Project"),
                             ("actor_person", "Other Person"), ("actor_user", "outsider@synthetic.example"),
                             ("capture_id", OP), ("captured_at", "2026-10-18T08:00:00")]:
            with self.subTest(field=field):
                self.request = copy.deepcopy(original)
                self.request["body"]["envelope"][field] = value
                self.request["body_sha256"] = digest(self.request["body"])
                self.lease["request_sha256"] = digest(self.request)
                self.flush()
                self.denied()

    def test_run_id_native_timeouts_and_inventory_bounds(self):
        for key, value in [("run_id", "../escape"), ("run_id", "short"),
                           ("statement_timeout_seconds", 31), ("lock_wait_timeout_seconds", 0),
                           ("max_inventory_rows", 2001), ("max_file_bytes", 16777217)]:
            with self.subTest(key=key):
                self.write("lease.json", dict(self.lease, **{key: value}))
                self.denied()

    def test_existing_bytecode_is_in_full_manifest_and_change_is_denied(self):
        cache = self.app / "__pycache__"
        cache.mkdir()
        bytecode = cache / "source.cpython-311.pyc"
        bytecode.write_bytes(b"pinned existing bytecode fixture")
        self.denied()
        self.manifest["files"].append({"path": str(bytecode), "sha256": hashlib.sha256(bytecode.read_bytes()).hexdigest()})
        self.lease["source_manifest_sha256"] = self.receipt["source_manifest_sha256"] = digest(self.manifest)
        self.flush()
        self.admit(execute=True)
        bytecode.write_bytes(b"changed")
        self.denied()

    def test_existing_driver_bytecode_requires_explicit_runtime_pin(self):
        for directory in [self.root, self.root / "__pycache__"]:
            with self.subTest(directory=str(directory)):
                directory.mkdir(exist_ok=True)
                cache = directory / "native_worker.fixture.pyc"
                cache.write_bytes(b"existing helper bytecode fixture; never executed")
                self.denied()
                pin = {"path": str(cache), "sha256": hashlib.sha256(cache.read_bytes()).hexdigest()}
                self.manifest["files"].append(pin)
                self.lease["source_manifest_sha256"] = self.receipt["source_manifest_sha256"] = digest(self.manifest)
                self.flush()
                self.denied()
                self.manifest["runtime_files"].append(str(cache))
                self.lease["source_manifest_sha256"] = self.receipt["source_manifest_sha256"] = digest(self.manifest)
                self.flush()
                self.admit(execute=True)
                cache.write_bytes(b"changed")
                self.denied()
                cache.write_bytes(b"existing helper bytecode fixture; never executed")

    def test_recheck_reads_fresh_epoch(self):
        admission = self.admit(execute=True)
        self.write("epoch.json", dict(self.epoch, epoch="epoch-2"))
        with self.assertRaises((ValueError, OSError)):
            self.guard.recheck(admission)

    def test_recheck_keeps_original_deadline(self):
        admission = self.admit(execute=True)
        with patch.object(self.guard, "now", return_value=FIXED + dt.timedelta(seconds=61)):
            with self.assertRaises((ValueError, OSError)):
                self.guard.recheck(admission)

    def test_serialized_admission_cannot_extend_deadline_or_mutate_body(self):
        admission = self.admit(execute=True)
        admission["deadline"] = (FIXED + dt.timedelta(minutes=5)).isoformat()
        with self.assertRaises((ValueError, OSError)):
            self.guard.recheck(admission)
        admission = self.admit(execute=True)
        admission["request"]["body"]["project"] = "Other Project"
        with self.assertRaises((ValueError, OSError)):
            self.guard.recheck(admission)

    @unittest.skipIf(RED, "Red scaffold intentionally has no storage helper")
    def test_atomic_json_preserves_private_mode_and_denies_symlink(self):
        output = self.output / "private.json"
        self.guard.atomic_json(str(output), {"state": "unknown"})
        self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o600)
        self.assertEqual(self.guard.private_json(str(output)), {"state": "unknown"})
        output.unlink()
        output.symlink_to(self.root / "lease.json")
        with self.assertRaises((ValueError, OSError)):
            self.guard.atomic_json(str(output), {"state": "ready"})

    def test_recheck_rejects_lease_request_receipt_and_source_changes(self):
        for name, value in [("lease.json", dict(self.lease, max_duration_seconds=59)),
                            ("request.json", dict(self.request, scenario="apply_race")),
                            ("runtime.json", dict(self.receipt, epoch="epoch-2"))]:
            with self.subTest(name=name):
                self.flush()
                admission = self.admit(execute=True)
                self.write(name, value)
                with self.assertRaises((ValueError, OSError)):
                    self.guard.recheck(admission)
        self.flush()
        admission = self.admit(execute=True)
        self.driver.write_text("# changed driver\n")
        with self.assertRaises((ValueError, OSError)):
            self.guard.recheck(admission)

    def test_journal_can_start_only_pristine_ready(self):
        ready = {"schema": "cipher.fld02.native.concurrent.journal.v1", "state": "ready",
                 "attempts": 0, "outcome": "not_started", "operation_uuid": OP}
        self.assertTrue(self.guard.can_start(ready))
        for key, value in [("state", "unknown"), ("state", "commit_started"),
                           ("state", "incomplete"), ("attempts", 1),
                           ("outcome", "unknown"), ("operation_uuid", "")]:
            with self.subTest(key=key, value=value):
                self.assertFalse(self.guard.can_start(dict(ready, **{key: value})))
        for value in [None, {}, {"state": "ready"}]:
            self.assertFalse(self.guard.can_start(value))


if __name__ == "__main__":
    unittest.main(verbosity=2)

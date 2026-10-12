"""Foundation tests: money, schema lifecycle, write authority, audit chain, approvals, commands."""
import os
import sqlite3
import tempfile
import unittest
from decimal import Decimal
from unittest import mock

from apps.cipher.core.approvals import (ApprovalConsumed, ApprovalExpired, ApprovalNotGranted, Approvals, StaleApprovalError, build_manifest, material_hash)
from apps.cipher.core.audit import Audit
from apps.cipher.core.commands import Commands, IdempotencyConflict
from apps.cipher.core.db import SCHEMA_CATALOG, Database, SchemaError, WriteAuthorityError, catalog_checksum
from apps.cipher.core.ids import canonical_json, hash_json, parse_iso, utcnow
from apps.cipher.core.money import MoneyError, allocate, money, pct, rate, total
import datetime as dt


class MoneyTests(unittest.TestCase):
    def test_quantises_half_up(self):
        self.assertEqual(money("1234.565"), Decimal("1234.57"))
        self.assertEqual(money("0.005"), Decimal("0.01"))

    def test_rejects_floats_and_bools(self):
        with self.assertRaises(MoneyError):
            money(1.1)
        with self.assertRaises(MoneyError):
            money(True)

    def test_accepts_formatted_strings(self):
        self.assertEqual(money("$1,000.50"), Decimal("1000.50"))

    def test_allocation_sums_exactly(self):
        parts = allocate("100", [1, 1, 1])
        self.assertEqual(sum(parts), Decimal("100.00"))
        self.assertEqual(parts, [Decimal("33.34"), Decimal("33.33"), Decimal("33.33")])

    def test_allocation_spreads_the_residual_cent_by_cent(self):
        self.assertEqual([str(p) for p in allocate("0.05", [1] * 7)], ["0.01", "0.01", "0.01", "0.01", "0.01", "0.00", "0.00"])
        self.assertEqual([str(p) for p in allocate("-0.05", [1] * 7)], ["-0.01", "-0.01", "-0.01", "-0.01", "-0.01", "0.00", "0.00"])
        # equal remainders (.5 and .5): the larger weight wins the tie, then the lower index
        self.assertEqual([str(p) for p in allocate("0.02", [1, 3])], ["0.00", "0.02"])
        self.assertEqual([str(p) for p in allocate("0.02", [3, 1])], ["0.02", "0.00"])
        self.assertEqual([str(p) for p in allocate("0.01", [1, 1])], ["0.01", "0.00"])
        self.assertEqual([str(p) for p in allocate("0.03", [1, 2, 1])], ["0.01", "0.01", "0.01"])  # .75/.5/.75: indices 0 and 2
        self.assertEqual([str(p) for p in allocate("10.00", [0, 0])], ["10.00", "0.00"])  # all-zero weights: first part
        with self.assertRaises(MoneyError):
            allocate("1.00", ["-1", "2"])
        with self.assertRaises(MoneyError):
            allocate("1.00", [])

    def test_non_finite_and_out_of_range_values_are_rejected(self):
        for bad in ("NaN", "nan", "sNaN", "-sNaN", "Infinity", "-Infinity", "inf", Decimal("NaN"), Decimal("sNaN"), Decimal("-Infinity"),
                    "10000000000000", "-10000000000000.00", "1E+13", 10 ** 13, -(10 ** 13), Decimal("1e20")):
            with self.subTest(value=bad), self.assertRaises(MoneyError):
                money(bad)
        self.assertEqual(money("9999999999999.99"), Decimal("9999999999999.99"))
        self.assertEqual(money("-9999999999999.99"), Decimal("-9999999999999.99"))
        with self.assertRaises(MoneyError):
            total(["9999999999999.99", "0.01"])  # the running total leaves the range
        with self.assertRaises(MoneyError):
            allocate("NaN", [1, 1])
        with self.assertRaises(MoneyError):
            allocate("1.00", ["Infinity", "1"])
        # the range check is exact even past the 28-digit context
        self.assertEqual(money("9999999999999.994999999999999999"), Decimal("9999999999999.99"))

    def test_allocation_ranks_remainders_exactly(self):
        # remainders that differ only beyond 28 significant digits are still ranked exactly
        self.assertEqual([str(p) for p in allocate("0.02", [3, Decimal("3E-28"), 1])], ["0.01", "0.00", "0.01"])
        self.assertEqual(sum(allocate("1000.00", ["0.333333333333333333333333333333"] * 3)), Decimal("1000.00"))

    def test_rate_bounds(self):
        self.assertEqual(rate("0.10"), Decimal("0.100000"))
        with self.assertRaises(MoneyError):
            rate("1.5")

    def test_pct_and_total(self):
        self.assertEqual(pct("30000", "0.10"), Decimal("3000.00"))
        self.assertEqual(total(["1.005", "1.005"]), Decimal("2.02"))


class SchemaTests(unittest.TestCase):
    def test_catalog_applies_and_is_recorded(self):
        db = Database()
        status = db.schema_status()
        self.assertEqual(status["current_version"], SCHEMA_CATALOG[-1][0])
        self.assertEqual(status["pending"], [])
        for v in status["versions"]:
            self.assertTrue(v["applied"] and v["checksum_matches"])

    def test_modified_history_is_detected(self):
        db = Database()
        with db.transaction() as conn:
            conn.execute("UPDATE schema_version SET checksum='tampered' WHERE version=1")
        with self.assertRaises(SchemaError):
            db.migrate()

    def test_older_database_upgrades_in_place_by_name(self):
        """A workspace created before later modules existed gains them on open, keeps its data,
        and keeps matching entries by name even when catalog positions differ."""
        d = tempfile.mkdtemp()
        path = os.path.join(d, "old.sqlite")
        saved = list(SCHEMA_CATALOG)
        try:
            del SCHEMA_CATALOG[1:]  # simulate a release that only had the foundation
            old = Database(path)
            Audit(old).record("owner", "seed", "t", "1", {"v": 1})
            old.close()
        finally:
            SCHEMA_CATALOG[:] = saved
        upgraded = Database(path)
        status = upgraded.schema_status()
        self.assertEqual(status["pending"], [])
        self.assertEqual(status["orphaned"], [])
        self.assertEqual(len(Audit(upgraded).entries(entity_type="t")), 1)
        # reordering the catalog (a different module load order) must not break an existing database
        upgraded.close()
        if len(SCHEMA_CATALOG) >= 3:
            reordered = [SCHEMA_CATALOG[0]] + list(reversed(SCHEMA_CATALOG[1:]))
            try:
                SCHEMA_CATALOG[:] = reordered
                again = Database(path)
                self.assertEqual(again.schema_status()["pending"], [])
                again.close()
            finally:
                SCHEMA_CATALOG[:] = saved

    def test_removed_module_is_reported_as_orphaned(self):
        db = Database()
        with db.transaction() as conn:
            conn.execute("INSERT INTO schema_version (version, name, statement_count, checksum, applied_at) VALUES (999,'retired_module',0,'x','t')")
        self.assertEqual(db.schema_status()["orphaned"], ["retired_module"])
        db.migrate()  # does not fail

    def test_checksum_is_stable(self):
        self.assertEqual(catalog_checksum(["a", "b"]), catalog_checksum(["a ", " b"]))

    def test_manifest_lists_triggers(self):
        m = Database().schema_manifest()
        names = {o["name"] for o in m["objects"]}
        self.assertIn("journals_no_update", names)
        self.assertIn("journals_period_open", names)
        for name in ("journal_lines_sealed", "journals_reversed_once", "periods_locked_immutable", "periods_reopen_requires_approval", "period_reopens",
                     "journal_unsealed", "journals_no_replace", "journal_lines_no_replace", "periods_insert_guard", "approvals_insert_guard",
                     "approvals_lifecycle", "audit_log_no_replace"):
            self.assertIn(name, names)
        entries = [v["name"] for v in m["schema_status"]["versions"]]
        self.assertEqual(entries[:4], ["foundation", "ledger_integrity", "period_integrity", "integrity_hardening"])

    def test_failed_commit_is_rolled_back_not_left_open(self):
        db = Database()
        db.execute("INSERT INTO periods (id, name, start_date, end_date, status) VALUES ('P1','P1','2026-10-01','2026-10-31','open')")
        db.execute("INSERT INTO accounts (code, name, type) VALUES ('5000','Cost','expense')")
        with self.assertRaisesRegex(sqlite3.IntegrityError, "fewer lines than its sealed line count"):
            with db.transaction() as conn:
                conn.execute("INSERT INTO journals (id, period_id, posted_at, description, source_type, source_id, source_version, rule_version, posted_by, line_count) "
                             "VALUES ('jrn_short','P1','t','short','t','t','1','r','t',2)")
        self.assertFalse(db.conn.in_transaction)
        self.assertFalse(db.in_transaction)
        self.assertEqual(db.scalar("SELECT COUNT(*) FROM journals"), 0)
        with db.transaction() as conn:  # the connection is usable again
            conn.execute("INSERT INTO accounts (code, name, type) VALUES ('2000','AP','liability')")


class WriteAuthorityTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        env = mock.patch.dict(os.environ)
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop("CIPHER_OWNER_SECRET", None)

    def open(self, name):
        db = Database(os.path.join(self.dir, name))  # an absolute path (a snapshot) is used as given
        self.addCleanup(db.close)
        return db

    def test_fresh_file_db_has_authority(self):
        db = self.open("a.sqlite")
        self.assertTrue(db.has_write_authority())
        self.assertTrue(os.path.exists(db.path + ".authority"))
        self.assertFalse(db.authority_status()["read_only"])
        memory = Database()
        self.assertFalse(memory.authority_status()["read_only"])  # in-memory workspaces hold authority ...
        with self.assertRaises(WriteAuthorityError):
            memory.release_write_authority()  # ... always: there is nothing to release
        self.assertTrue(memory.has_write_authority())
        self.assertFalse(memory.read_only)

    def test_restored_copy_is_quarantined_until_claimed(self):
        db = self.open("a.sqlite")
        restored = self.open(db.snapshot(os.path.join(self.dir, "restore.sqlite")))
        self.assertFalse(restored.has_write_authority())
        self.assertTrue(restored.authority_status()["read_only"])
        cmds = Commands(restored, Audit(restored))
        with self.assertRaises(WriteAuthorityError):
            cmds.run("op", {}, lambda: 1, actor="owner")
        with self.assertRaises(WriteAuthorityError):
            Audit(restored).record("owner", "x", "t", "1", {})  # SQLite itself refuses the write
        for approver, reason in (("", "restore drill"), ("owner", ""), ("  ", "restore drill"), (None, "restore drill")):
            with self.subTest(approver=approver, reason=reason), self.assertRaises(WriteAuthorityError):
                restored.claim_write_authority(approver=approver, reason=reason)
        self.assertTrue(restored.read_only)
        status = restored.claim_write_authority(approver="owner", reason="restore drill", approval_ref="apr_controller")
        self.assertTrue(status["effective_write_authority"])
        self.assertFalse(status["read_only"])
        self.assertEqual(status["recovery_epoch"], 1)
        self.assertTrue(status["release_quarantined"])
        self.assertEqual(cmds.run("op", {}, lambda: 1, actor="owner").result, 1)
        claim = Audit(restored).entries(entity_type="workspace")[-1]
        self.assertEqual(claim["actor"], "owner")
        self.assertIn('"approval_ref":"apr_controller"', claim["payload_json"])
        self.assertTrue(Audit(restored).verify_chain()["ok"])

    def test_release_then_reclaim(self):
        db = self.open("b.sqlite")
        status = db.release_write_authority()
        self.assertFalse(db.has_write_authority())
        self.assertTrue(status["read_only"])
        with self.assertRaises(WriteAuthorityError):
            db.release_write_authority()  # nothing left to release
        db.claim_write_authority(approver="owner", reason="resume work")
        self.assertTrue(db.has_write_authority())
        self.assertFalse(db.read_only)


class AuditTests(unittest.TestCase):
    def test_chain_verifies_and_is_append_only(self):
        db = Database()
        a = Audit(db)
        a.record("owner", "x", "t", "1", {"v": 1})
        a.record("owner", "y", "t", "2", {"v": 2})
        self.assertTrue(a.verify_chain()["ok"])
        with self.assertRaises(sqlite3.IntegrityError):
            db.execute("UPDATE audit_log SET actor='mallory' WHERE seq=1")
        with self.assertRaises(sqlite3.IntegrityError):
            db.execute("DELETE FROM audit_log WHERE seq=1")
        self.assertEqual(len(a.entries(entity_type="t")), 2)
        self.assertEqual(len(a.export()["entries"]), 2)


class ApprovalTests(unittest.TestCase):
    def setUp(self):
        self.db = Database()
        self.audit = Audit(self.db)
        self.ap = Approvals(self.db, self.audit)
        self.m = build_manifest(operation="commitment.execute", subject_type="commitment", subject_id="c1", actor_role="owner",
                                amounts={"total": "110000"}, bindings={"sov_hash": "h1", "commitment_version": 1},
                                destination={"party_id": "p1", "destination": "ACH-1", "destination_version": 1})

    def test_material_hash_ignores_nonce_and_expiry(self):
        other = dict(self.m, nonce="x", expires_at="2030-01-01T00:00:00Z")
        self.assertEqual(material_hash(self.m), material_hash(other))

    def test_lifecycle(self):
        r = self.ap.request(self.m, requested_by="owner")
        self.assertEqual(r["status"], "pending")
        with self.assertRaises(ApprovalNotGranted):
            self.ap.consume(r["id"], current_manifest=self.m, consumer="x")
        self.ap.grant(r["id"], approver="owner")
        done = self.ap.consume(r["id"], current_manifest=dict(self.m, nonce="other"), consumer="cmd")
        self.assertEqual(done["status"], "consumed")
        with self.assertRaises(ApprovalConsumed):
            self.ap.consume(r["id"], current_manifest=self.m, consumer="cmd")

    def test_changed_amount_invalidates(self):
        r = self.ap.grant(self.ap.request(self.m, requested_by="o")["id"], approver="o")
        with self.assertRaises(StaleApprovalError):
            self.ap.consume(r["id"], current_manifest=dict(self.m, amounts={"total": "120000.00"}), consumer="cmd")
        self.assertEqual(self.ap.get(r["id"])["status"], "invalidated")

    def test_changed_destination_invalidates(self):
        r = self.ap.grant(self.ap.request(self.m, requested_by="o")["id"], approver="o")
        changed = dict(self.m, destination={"party_id": "p1", "destination": "ACH-2", "destination_version": 2})
        with self.assertRaises(StaleApprovalError):
            self.ap.consume(r["id"], current_manifest=changed, consumer="cmd")

    def test_expiry(self):
        m = build_manifest(operation="x", subject_type="t", subject_id="1", actor_role="owner", expiry_seconds=1)
        r = self.ap.grant(self.ap.request(m, requested_by="o")["id"], approver="o")
        later = utcnow() + dt.timedelta(seconds=5)
        with self.assertRaises(ApprovalExpired):
            self.ap.consume(r["id"], current_manifest=m, consumer="cmd", now=later)
        self.assertEqual(self.ap.get(r["id"])["status"], "expired")

    def test_invalidate_for_subject(self):
        a = self.ap.request(self.m, requested_by="o")
        second = build_manifest(operation="commitment.execute", subject_type="commitment", subject_id="c1", actor_role="owner", amounts={"total": "110000"})
        b = self.ap.grant(self.ap.request(second, requested_by="o")["id"], approver="o")
        with self.assertRaises(sqlite3.IntegrityError):
            self.ap.request(self.m, requested_by="o")  # a manifest (nonce) is requested once
        n = self.ap.invalidate_for_subject("commitment", "c1", reason="changed")
        self.assertEqual(n, 2)
        self.assertEqual(self.ap.get(a["id"])["status"], "invalidated")
        self.assertEqual(self.ap.get(b["id"])["status"], "invalidated")


class CommandTests(unittest.TestCase):
    def setUp(self):
        self.db = Database()
        self.cmd = Commands(self.db, Audit(self.db))

    def test_replay_returns_stored_result_without_rerun(self):
        calls = []
        r1 = self.cmd.run("op", {"a": 1}, lambda: calls.append(1) or {"ok": 1}, actor="o")
        r2 = self.cmd.run("op", {"a": 1}, lambda: calls.append(2) or {"ok": 2}, actor="o")
        self.assertFalse(r1.replayed)
        self.assertTrue(r2.replayed)
        self.assertEqual(r2.result, {"ok": 1})
        self.assertEqual(calls, [1])

    def test_same_id_different_payload_conflicts(self):
        self.cmd.run("op", {"a": 1}, lambda: 1, actor="o")
        with self.assertRaises(IdempotencyConflict):
            self.cmd.run("op", {"a": 2}, lambda: 1, actor="o")

    def test_failed_handler_leaves_no_record(self):
        def boom():
            raise ValueError("no")
        with self.assertRaises(ValueError):
            self.cmd.run("op", {}, boom, actor="o")
        self.assertIsNone(self.db.one("SELECT * FROM idempotency WHERE op_id='op'"))

    def test_outbox_requires_transaction_and_commits_with_state(self):
        with self.assertRaises(RuntimeError):
            self.cmd.enqueue("payment", {})
        try:
            with self.db.transaction():
                self.cmd.enqueue("payment", {"x": 1})
                raise RuntimeError("abort")
        except RuntimeError:
            pass
        self.assertEqual(self.cmd.pending(), [])
        with self.db.transaction():
            row = self.cmd.enqueue("payment", {"x": 1})
        self.assertEqual(len(self.cmd.pending("payment")), 1)
        self.cmd.mark_dispatched(row["id"])
        self.assertEqual(self.cmd.pending(), [])


class IdsTests(unittest.TestCase):
    def test_canonical_json_sorts_and_renders_decimals(self):
        self.assertEqual(canonical_json({"b": Decimal("1.10"), "a": 1}), '{"a":1,"b":"1.10"}')
        self.assertEqual(hash_json({"a": 1}), hash_json({"a": 1}))
        self.assertEqual(parse_iso("2026-10-11T00:00:00Z").tzinfo, dt.timezone.utc)


if __name__ == "__main__":
    unittest.main()

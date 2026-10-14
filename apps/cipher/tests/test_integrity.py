"""Core integrity controls, probed directly and through the service.

1. money: non-finite and out-of-range values are refused; allocation is
   largest-remainder (exact sum, within one cent, never the wrong sign), checked
   over seeded random cases against an independent reference, high-precision
   weights included;
2. write authority is enforced by SQLite (``PRAGMA query_only``): a restored copy
   refuses every write, raw SQL and every cursor included, until a valid attested
   claim; no spelling of the pragma lifts it, and a release reaches every
   connection to the workspace;
3. claim governance: approver and reason are required, and the owner claim code
   is required and single-use when ``CIPHER_OWNER_SECRET`` is configured;
4. sealed journals: a raw INSERT of an extra line onto a posted journal is refused,
   a journal must be complete, canonical and balanced in exact cents when it
   commits, and older workspaces are backfilled;
5. period integrity: a locked period never changes; closed -> open needs a
   consumed, scoped, unused ``*.reopen_period`` approval, on the raw SQL path too;
   approvals are recorded pending and move forward only;
6. INSERT OR REPLACE (and OR IGNORE, upserts) cannot rewrite any immutable core row;
7. governed correction: ``journal.reverse`` through request -> grant -> execute,
   refused for subledger-owned journals and against a stale request.
"""
import os
import random
import sqlite3
import tempfile
import unittest
from decimal import Decimal
from fractions import Fraction
from unittest import mock

from apps.cipher.tests.bill_helpers import approve_and_post_bill
from apps.cipher.core.approvals import Approvals, StaleApprovalError, build_manifest
from apps.cipher.core.audit import Audit
from apps.cipher.core.db import SCHEMA_CATALOG, Database, WriteAuthorityError
from apps.cipher.core.money import D, MoneyError, allocate, money, pct, rate, total
from apps.cipher.domain.ledger import Ledger, LedgerError, PeriodNotOpen, ReversalNotAvailable, SubledgerOwnedJournal
from apps.cipher.service import Cipher, RoleNotAuthorized

ENTITY = "S&A Solutions LLC (synthetic)"
JOURNAL_COLUMNS = "id, period_id, posted_at, description, source_type, source_id, source_version, rule_version, posted_by, line_count"

SECRET = "synthetic-owner-secret-for-tests"


def clean_env(test: unittest.TestCase, **values: str) -> None:
    """Run the test with CIPHER_OWNER_SECRET unset unless given explicitly."""
    patcher = mock.patch.dict(os.environ)
    patcher.start()
    test.addCleanup(patcher.stop)
    os.environ.pop("CIPHER_OWNER_SECRET", None)
    os.environ.update(values)


def post(c_or_ledger, period="P1", amount="100.00", *, debit="5000", credit="2000", project_id=None, source_id="integrity"):
    ledger = getattr(c_or_ledger, "ledger", c_or_ledger)
    return ledger.post(period_id=period, description="integrity probe",
                       lines=[{"account": debit, "debit": amount, "project_id": project_id}, {"account": credit, "credit": amount, "project_id": project_id}],
                       source_type="integrity_test", source_id=source_id, source_version="1", posted_by="tester")


# --------------------------------------------------------------------------- #
# 1. money                                                                     #
# --------------------------------------------------------------------------- #

def reference_allocation(amount: Decimal, weights: list[Decimal]) -> list[Decimal]:
    """Independent largest-remainder reference: exact fractions, floor toward zero,
    remaining cents to the largest remainders, ties to the larger weight then the
    lower index."""
    cents = int(abs(amount) * 100)
    sign = -1 if amount < 0 else 1
    total_w = sum((Fraction(w) for w in weights), Fraction(0))
    shares = [Fraction(cents) * Fraction(w) / total_w for w in weights]
    base = [s.numerator // s.denominator for s in shares]
    left = cents - sum(base)
    ranked = sorted(range(len(weights)), key=lambda i: (shares[i] - base[i], Fraction(weights[i]), -i), reverse=True)
    for i in ranked[:left]:
        base[i] += 1
    return [Decimal(sign * b) / 100 for b in base]


class MoneyIntegrityTests(unittest.TestCase):
    NON_FINITE = ("NaN", "-NaN", "nan", "sNaN", "Infinity", "-Infinity", "inf", "-inf", " Infinity ",
                  Decimal("NaN"), Decimal("sNaN"), Decimal("Infinity"), Decimal("-Infinity"))

    def test_non_finite_values_are_refused_everywhere(self):
        for bad in self.NON_FINITE:
            for label, fn in (("D", D), ("money", money), ("rate", rate), ("pct", lambda v: pct("100", v)),
                              ("total", lambda v: total(["1.00", v])), ("allocate", lambda v: allocate(v, [1, 1])),
                              ("weight", lambda v: allocate("1.00", [v, 1]))):
                with self.subTest(value=bad, via=label), self.assertRaises(MoneyError):
                    fn(bad)

    def test_magnitudes_of_ten_to_the_thirteen_and_above_are_refused(self):
        for bad in ("10000000000000", "-10000000000000", "10000000000000.00", "1E+13", "1e20", 10 ** 13, -(10 ** 15),
                    Decimal("10000000000000.000"), "$10,000,000,000,000"):
            with self.subTest(value=bad), self.assertRaises(MoneyError):
                D(bad)
        self.assertEqual(D("9999999999999.999"), Decimal("9999999999999.999"))
        self.assertEqual(money("9999999999999.99"), Decimal("9999999999999.99"))
        with self.assertRaises(MoneyError):
            money("9999999999999.995")  # rounds up into the refused range
        with self.assertRaises(MoneyError):
            pct("9999999999999.99", "2")

    def test_largest_remainder_properties_over_seeded_random_cases(self):
        rng = random.Random(20261012)
        cases = 0
        for _ in range(3000):
            n = rng.randint(1, 12)
            scale = rng.choice((1, 100, 1_000_000, 10 ** 11))
            amount = Decimal(rng.randint(-scale * 100, scale * 100)) / 100
            weights = []
            for _ in range(n):
                kind = rng.random()
                if kind < 0.15:
                    weights.append(0)
                elif kind < 0.55:
                    weights.append(rng.randint(1, 1000))
                elif kind < 0.85:
                    weights.append(f"{Decimal(rng.randint(1, 10 ** 6)) / 10 ** rng.randint(0, 4)}")
                else:
                    weights.append(Decimal(rng.randint(1, 7)))
            if sum(D(w) for w in weights) == 0:
                weights[rng.randrange(n)] = 1
            parts = allocate(f"{amount:f}", weights)
            ws = [D(w) for w in weights]
            total_w = sum((Fraction(w) for w in ws), Fraction(0))
            with self.subTest(amount=str(amount), weights=[str(w) for w in weights]):
                self.assertEqual(len(parts), n)
                self.assertEqual(sum(parts, Decimal("0")), amount)
                for part, w in zip(parts, ws):
                    self.assertEqual(part, part.quantize(Decimal("0.01")))
                    exact = Fraction(amount) * Fraction(w) / total_w
                    self.assertLess(abs(Fraction(part) - exact), Fraction(1, 100))
                    self.assertGreaterEqual(part * (1 if amount >= 0 else -1), 0)  # never the opposite sign
                    if w == 0:
                        self.assertEqual(part, Decimal("0.00"))
                self.assertEqual(parts, reference_allocation(amount, ws))
            cases += 1
        self.assertEqual(cases, 3000)

    def test_allocation_is_exact_beyond_the_decimal_context(self):
        # the true remainders (.5 - 0.375e-28 vs .5 - 0.125e-28) differ only past 28 digits
        self.assertEqual([str(p) for p in allocate("0.02", [3, Decimal("3E-28"), 1])], ["0.01", "0.00", "0.01"])
        # weights that differ only in the 30th digit: the larger exact share and the larger weight win
        self.assertEqual([str(p) for p in allocate("0.01", ["1", "1.00000000000000000000000000001"])], ["0.00", "0.01"])
        self.assertEqual([str(p) for p in allocate("0.02", ["1.00000000000000000000000000001", "1", "2"])], ["0.01", "0.00", "0.01"])
        rng = random.Random(1012)
        for _ in range(500):
            n = rng.randint(2, 6)
            amount = Decimal(rng.randint(-10 ** 6, 10 ** 6)) / 100
            weights = [Decimal(f"{rng.randint(1, 9)}.{rng.randint(0, 10 ** 30):030d}") for _ in range(n)]
            if rng.random() < 0.5:  # a near-tie beyond the 28-digit context: w1 = w0 + 1e-31, built exactly
                weights[1] = Decimal(f"{weights[0]}1")
            parts = allocate(f"{amount:f}", weights)
            with self.subTest(amount=str(amount), weights=[str(w) for w in weights]):
                self.assertEqual(sum(parts, Decimal("0")), amount)
                self.assertEqual(parts, reference_allocation(amount, weights))

    def test_range_check_is_exact_for_long_decimals(self):
        # abs() would round this 31-digit value to 10**13 in the 28-digit context
        self.assertEqual(D("9999999999999.999999999999999999"), Decimal("9999999999999.999999999999999999"))
        self.assertEqual(D("-9999999999999.999999999999999999"), Decimal("-9999999999999.999999999999999999"))
        with self.assertRaises(MoneyError):
            money("9999999999999.999999999999999999")  # rounds to 10**13
        with self.assertRaises(MoneyError):
            D("10000000000000.000000000000000001")

    def test_allocation_input_validation(self):
        with self.assertRaisesRegex(MoneyError, "negative allocation weight"):
            allocate("10.00", [1, "-0.01"])
        with self.assertRaises(MoneyError):
            allocate("10.00", [1, 0.5])  # binary float weight
        with self.assertRaises(MoneyError):
            allocate("10.00", [True, 1])
        with self.assertRaises(MoneyError):
            allocate("10.00", [])
        self.assertEqual(allocate("-7.00", [0, 0, 0]), [Decimal("-7.00"), Decimal("0.00"), Decimal("0.00")])
        self.assertEqual(allocate("0.00", [1, 2]), [Decimal("0.00"), Decimal("0.00")])
        self.assertEqual([str(p) for p in allocate("110000.00", [70000, 40000])], ["70000.00", "40000.00"])
        self.assertEqual([str(p) for p in allocate("1000.00", ["0.3333", "0.3333", "0.3334"])], ["333.30", "333.30", "333.40"])


# --------------------------------------------------------------------------- #
# 2-3. write authority enforced by SQLite, and claim governance               #
# --------------------------------------------------------------------------- #

class RestoredCopyTests(unittest.TestCase):
    def setUp(self):
        clean_env(self)
        self.dir = tempfile.mkdtemp(prefix="cipher-integrity-")
        self.live = self.track(Cipher(os.path.join(self.dir, "live.sqlite")))
        c = self.live
        c.open_period("P1", "P1", "2026-10-01", "2026-10-31")
        self.customer = c.add_party(kind="customer", name="Synthetic Owner Agency")
        self.project = c.create_project(name="Synthetic sheet-pile cofferdam", entity="S&A Solutions LLC (synthetic)", budget="250000",
                                        customer_id=self.customer["id"])
        self.journal = post(c, amount="1250.00", project_id=self.project["id"])

    def track(self, c):
        self.addCleanup(c.db.close)
        return c

    def restored(self, name="copy.sqlite"):
        snap = self.live.snapshot(os.path.join(self.dir, name))
        return self.track(Cipher.open_restored(snap, provider=self.live.provider))

    def counts(self, c):
        return {t: c.db.scalar(f"SELECT COUNT(*) FROM {t}") for t in ("parties", "projects", "journals", "journal_lines", "audit_log", "approvals", "documents", "periods")}

    def write_attempts(self, c):
        project_id = self.project["id"]
        return {
            "add_party": lambda: c.add_party(kind="supplier", name="Injected payee", destination="ACH-SIM-INJECTED"),
            "create_project": lambda: c.create_project(name="Injected", entity="E", budget="1"),
            "ledger.post": lambda: post(c, amount="1.00"),
            "evidence.register_document": lambda: c.evidence.register_document(project_id=project_id, kind="drawing", title="Injected", actor="x"),
            "open_period": lambda: c.open_period("P2", "P2", "2026-11-01", "2026-11-30"),
            "ledger.prepare_reversal": lambda: c.ledger.prepare_reversal(self.journal["id"], "restored-copy probe", "accountant"),
            "approvals.request": lambda: c.approvals.request(build_manifest(operation="journal.reverse", subject_type="journal", subject_id=self.journal["id"],
                                                                            actor_role="owner"), requested_by="owner"),
            "audit.record": lambda: c.audit.record("x", "injected", "t", "1", {}),
            "raw INSERT": lambda: c.db.execute("INSERT INTO parties (id, kind, name, created_at) VALUES ('pty_raw', 'supplier', 'Raw', 't')"),
            "raw UPDATE": lambda: c.db.execute("UPDATE parties SET name='renamed' WHERE id=?", (self.customer["id"],)),
            "raw DELETE": lambda: c.db.execute("DELETE FROM parties WHERE id=?", (self.customer["id"],)),
            "executemany": lambda: c.db.conn.executemany("INSERT INTO parties (id, kind, name, created_at) VALUES (?, 'supplier', 'Raw', 't')", [("pty_m1",), ("pty_m2",)]),
            "executescript": lambda: c.db.conn.executescript("INSERT INTO parties (id, kind, name, created_at) VALUES ('pty_s', 'supplier', 'Raw', 't');"),
            "lift query_only": lambda: c.db.execute("PRAGMA query_only = OFF"),
            "lift query_only (script)": lambda: c.db.conn.executescript("PRAGMA main.query_only=0;"),
            "release": lambda: c.db.release_write_authority(note="nothing to release"),
        }

    def assert_read_only(self, c):
        before = self.counts(c)
        for label, attempt in self.write_attempts(c).items():
            with self.subTest(write=label), self.assertRaises(WriteAuthorityError):
                attempt()
        self.assertEqual(self.counts(c), before)
        self.assertTrue(c.db.read_only)
        self.assertTrue(c.db.authority_status()["read_only"])

    def test_restored_copy_opens_read_only_and_refuses_every_write(self):
        r = self.restored()
        status = r.db.authority_status()
        self.assertFalse(status["effective_write_authority"])
        self.assertTrue(status["read_only"])
        self.assertFalse(self.live.db.authority_status()["read_only"])
        # reads still work, including reads inside a transaction
        self.assertTrue(r.ledger.trial_balance()["balanced"])
        self.assertEqual(r.ledger.journal(self.journal["id"])["lines"][0]["debit"], "1250.00")
        self.assertTrue(r.audit.verify_chain()["ok"])
        with r.db.transaction() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM journals").fetchone()[0], 1)
        self.assert_read_only(r)
        r.db.migrate()  # nothing pending; the copy stays read-only
        self.assertTrue(r.db.read_only)

    def test_claim_requires_approver_and_reason_and_then_allows_writes(self):
        r = self.restored()
        for kwargs in ({"approver": "", "reason": "restore drill"}, {"approver": "owner", "reason": "  "},
                       {"approver": "owner", "reason": "restore drill", "approval_ref": 7}):
            with self.subTest(**{k: str(v) for k, v in kwargs.items()}), self.assertRaises(WriteAuthorityError):
                r.db.claim_write_authority(**kwargs)
            self.assertTrue(r.db.read_only)
        self.assert_read_only(r)  # a refused claim lifts nothing
        status = r.claim_write_authority(actor="owner", reason="restore drill after a lost laptop", approval_ref="ticket-0042")
        self.assertTrue(status["effective_write_authority"])
        self.assertFalse(status["read_only"])
        self.assertTrue(status["release_quarantined"])
        self.assertEqual(status["recovery_epoch"], 1)
        party = r.add_party(kind="supplier", name="Synthetic Dewatering Subcontractor")
        self.assertEqual(r.party(party["id"])["name"], "Synthetic Dewatering Subcontractor")
        j = post(r, amount="10.00")
        self.assertEqual(j["line_count"], 2)
        claim = [e for e in r.audit.entries(entity_type="workspace") if e["action"] == "workspace.claim_write_authority"][-1]
        self.assertEqual(claim["actor"], "owner")
        for fragment in ('"approver":"owner"', '"reason":"restore drill after a lost laptop"', '"approval_ref":"ticket-0042"',
                         '"restored_copy":true', '"recovery_epoch":1', '"owner_claim_code":"not_configured"'):
            self.assertIn(fragment, claim["payload_json"])
        self.assertTrue(r.audit.verify_chain()["ok"])
        self.assertTrue(r.ledger.trial_balance()["balanced"])
        self.assertTrue(self.live.db.has_write_authority())  # the live workspace is untouched

    def test_owner_claim_code_is_required_and_single_use_when_a_secret_is_configured(self):
        clean_env(self, CIPHER_OWNER_SECRET=SECRET)
        r = self.restored()
        other = self.restored("other.sqlite")
        stranger = Database()
        self.addCleanup(stranger.close)
        good = r.db.expected_claim_code(SECRET)
        self.assertEqual(len(good), 64)
        self.assertNotEqual(good, stranger.expected_claim_code(SECRET))  # bound to the workspace
        self.assertNotEqual(good, r.db.expected_claim_code("another secret"))
        for code in (None, "", "0" * 64, good.upper()[:-1] + "x", stranger.expected_claim_code(SECRET), good + "00"):
            with self.subTest(code=code), self.assertRaisesRegex(WriteAuthorityError, "owner claim code"):
                r.claim_write_authority(actor="owner", reason="restore drill", claim_code=code)
            self.assertTrue(r.db.read_only)
        with self.assertRaises(WriteAuthorityError):
            r.add_party(kind="supplier", name="Still refused")
        status = r.claim_write_authority(actor="owner", reason="restore drill", claim_code=good)
        self.assertTrue(status["effective_write_authority"])
        self.assertFalse(status["read_only"])
        r.add_party(kind="supplier", name="Allowed after the claim")
        claim = [e for e in r.audit.entries(entity_type="workspace") if e["action"] == "workspace.claim_write_authority"][-1]
        self.assertIn('"owner_claim_code":"verified"', claim["payload_json"])
        self.assertNotIn(good, claim["payload_json"])  # the code itself is never stored
        # the epoch moved on, so the same code cannot be replayed (here: after releasing again)
        r.db.release_write_authority(note="drill over")
        self.assertTrue(r.db.read_only)
        with self.assertRaises(WriteAuthorityError):
            r.claim_write_authority(actor="owner", reason="replay", claim_code=good)
        r.claim_write_authority(actor="owner", reason="second claim", claim_code=r.db.expected_claim_code(SECRET))
        self.assertFalse(r.db.read_only)
        # the second copy is unaffected by the first copy's claims
        self.assertTrue(other.db.read_only)
        with self.assertRaises(WriteAuthorityError):
            other.add_party(kind="supplier", name="Other copy")

    def test_release_makes_the_live_workspace_read_only_until_reclaimed(self):
        c = self.live
        c.db.release_write_authority(note="handing over")
        self.assert_read_only(c)
        c.claim_write_authority(actor="owner", reason="taking it back")
        self.assertFalse(c.db.read_only)
        post(c, amount="5.00")
        self.assertTrue(c.ledger.trial_balance()["balanced"])

    def test_in_memory_workspaces_hold_authority(self):
        c = Cipher()
        self.addCleanup(c.db.close)
        status = c.db.authority_status()
        self.assertTrue(status["effective_write_authority"])
        self.assertFalse(status["read_only"])
        with self.assertRaisesRegex(WriteAuthorityError, "always holds write authority"):
            c.db.release_write_authority(note="nothing to release in memory")
        self.assertTrue(c.db.has_write_authority())
        self.assertFalse(c.db.read_only)
        c.add_party(kind="supplier", name="Synthetic Sheet Piling Supplier")
        self.assertEqual([e["action"] for e in c.audit.entries(entity_type="workspace")], [])  # the refused release wrote nothing

    QUERY_ONLY_SPELLINGS = (
        "PRAGMA query_only = OFF", "PRAGMA query_only=0", "PRAGMA QUERY_ONLY = false", "PRAGMA query_only(0)", "PRAGMA main.query_only=0",
        "PRAGMA/**/query_only=0", "PRAGMA query_only/**/=0", 'PRAGMA "query_only" = 0', "PRAGMA [query_only] = 0", "PRAGMA `query_only` = off",
        'PRAGMA main."query_only"=0', "PRAGMA --x\n query_only=0", "  pragma\tquery_only\n=\n0  ", "PRAGMA temp.query_only = 0",
    )

    def query_only_attempts(self, c):
        conn = c.db.conn
        for sql in self.QUERY_ONLY_SPELLINGS:
            yield f"execute {sql!r}", lambda sql=sql: c.db.execute(sql)
            yield f"cursor {sql!r}", lambda sql=sql: conn.cursor().execute(sql)
            yield f"script {sql!r}", lambda sql=sql: conn.executescript(sql + ";")
        yield "cursor script", lambda: conn.cursor().executescript("PRAGMA main.query_only=0; INSERT INTO parties (id, kind, name, created_at) VALUES ('pty_s2', 'supplier', 'Raw', 't');")

    def test_no_spelling_or_cursor_lifts_query_only(self):
        r = self.restored()
        before = self.counts(r)
        for label, attempt in self.query_only_attempts(r):
            with self.subTest(attempt=label), self.assertRaisesRegex(WriteAuthorityError, "query_only is managed"):
                attempt()
            self.assertTrue(r.db.read_only)
        with self.assertRaises(WriteAuthorityError):
            r.db.conn.cursor().execute("INSERT INTO parties (id, kind, name, created_at) VALUES ('pty_raw', 'supplier', 'Raw', 't')")
        # a plain sqlite3.Cursor built by hand is refused by SQLite itself (its errors are not translated)
        with self.assertRaisesRegex(sqlite3.DatabaseError, "not authorized"):
            sqlite3.Cursor(r.db.conn).execute("PRAGMA query_only=0")
        with self.assertRaisesRegex(sqlite3.OperationalError, "readonly"):
            sqlite3.Cursor(r.db.conn).execute("INSERT INTO parties (id, kind, name, created_at) VALUES ('pty_raw', 'supplier', 'Raw', 't')")
        self.assertTrue(r.db.read_only)
        self.assertEqual(self.counts(r), before)
        # reads of the pragma are fine, and the guard holds on a writable connection too
        self.assertEqual(r.db.scalar("PRAGMA query_only"), 1)
        live = self.live
        for sql in ("PRAGMA query_only = ON", "PRAGMA/**/query_only=1"):
            with self.subTest(live=sql), self.assertRaises(WriteAuthorityError):
                live.db.execute(sql)
        self.assertFalse(live.db.read_only)
        # the other guarded pragmas cannot be switched off either (they keep FK and CHECK controls in force)
        for sql in ("PRAGMA foreign_keys = OFF", "PRAGMA/**/foreign_keys=0", "PRAGMA ignore_check_constraints = ON"):
            for c in (live, r):
                with self.subTest(sql=sql, copy="live" if c is live else "restored"), self.assertRaisesRegex(sqlite3.IntegrityError, "fixed by the integrity controls"):
                    c.db.execute(sql)
        self.assertEqual((live.db.scalar("PRAGMA foreign_keys"), live.db.scalar("PRAGMA ignore_check_constraints")), (1, 0))
        # nor through the connection's own switches
        for op, value in ((sqlite3.SQLITE_DBCONFIG_ENABLE_FKEY, False), (sqlite3.SQLITE_DBCONFIG_ENABLE_TRIGGER, False),
                          (sqlite3.SQLITE_DBCONFIG_WRITABLE_SCHEMA, True), (sqlite3.SQLITE_DBCONFIG_RESET_DATABASE, True)):
            with self.subTest(dbconfig=op), self.assertRaisesRegex(sqlite3.IntegrityError, "fixed by the integrity controls"):
                live.db.conn.setconfig(op, value)
        live.db.conn.setconfig(sqlite3.SQLITE_DBCONFIG_ENABLE_TRIGGER, True)  # keeping a switch as it is stays allowed
        self.assertTrue(live.db.conn.getconfig(sqlite3.SQLITE_DBCONFIG_ENABLE_TRIGGER))
        self.assertTrue(live.db.conn.getconfig(sqlite3.SQLITE_DBCONFIG_ENABLE_FKEY))

    def test_internal_toggles_never_leave_a_reusable_statement(self):
        """claim/release run their own PRAGMA query_only statements; a raw statement must not
        be served from the statement cache entry of one the authorizer allowed."""
        c = self.live
        c.db.release_write_authority(note="drill")
        c.claim_write_authority(actor="owner", reason="drill")
        c.db.release_write_authority(note="drill again")
        self.assertTrue(c.db.read_only)
        for sql in ("PRAGMA query_only = OFF", "PRAGMA query_only = ON", "PRAGMA query_only=OFF"):
            with self.subTest(sql=sql), self.assertRaises(WriteAuthorityError):
                c.db.execute(sql)
            self.assertTrue(c.db.read_only)
        with self.assertRaises(WriteAuthorityError):
            c.add_party(kind="supplier", name="Still refused")

    def test_every_cursor_reports_refused_writes_as_write_authority_errors(self):
        r = self.restored()
        conn = r.db.conn
        before = self.counts(r)
        insert = "INSERT INTO parties (id, kind, name, created_at) VALUES (?, 'supplier', 'Raw', 't')"
        attempts = {
            "cursor().execute": lambda: conn.cursor().execute(insert, ("pty_c1",)),
            "cursor().executemany": lambda: conn.cursor().executemany(insert, [("pty_c2",), ("pty_c3",)]),
            "cursor().executescript": lambda: conn.cursor().executescript("DELETE FROM parties;"),
            "reused cursor": lambda: conn.execute("SELECT 1").execute(insert, ("pty_c4",)),
            "raw DDL": lambda: r.db.execute("CREATE TABLE injected (id TEXT)"),
            "raw DROP TRIGGER": lambda: r.db.execute("DROP TRIGGER journals_no_update"),
        }
        for label, attempt in attempts.items():
            with self.subTest(write=label), self.assertRaises(WriteAuthorityError):
                attempt()
        self.assertEqual(self.counts(r), before)
        self.assertIsNotNone(r.db.scalar("SELECT name FROM sqlite_master WHERE type='trigger' AND name='journals_no_update'"))

    def test_release_reaches_every_connection_to_the_workspace(self):
        path = self.live.db.path
        a = self.live.db
        b = Database(path)
        self.addCleanup(b.close)
        other = self.track(Cipher(path))  # a second service (a worker, a server, a CLI) on the same file
        silent = Database(path)  # a connection that does nothing until it writes
        self.addCleanup(silent.close)
        self.assertFalse(b.read_only)
        a.release_write_authority(note="handing the workspace to another machine")
        with self.assertRaises(WriteAuthorityError):  # its very first statement after the release
            silent.execute("INSERT INTO parties (id, kind, name, created_at) VALUES ('pty_silent', 'supplier', 'Raw', 't')")
        self.assertTrue(silent.read_only)
        self.assertFalse(b.has_write_authority())
        self.assertTrue(b.read_only)
        self.assertTrue(b.authority_status()["read_only"])
        before = self.counts(other)

        def transaction_on_b():
            with b.transaction() as conn:
                conn.execute("UPDATE parties SET name='renamed'")

        for label, attempt in (
            ("raw INSERT on b", lambda: b.execute("INSERT INTO parties (id, kind, name, created_at) VALUES ('pty_b', 'supplier', 'Raw', 't')")),
            ("cursor INSERT on b", lambda: b.conn.cursor().execute("INSERT INTO parties (id, kind, name, created_at) VALUES ('pty_b2', 'supplier', 'Raw', 't')")),
            ("transaction on b", transaction_on_b),
            ("add_party on the other service", lambda: other.add_party(kind="supplier", name="Injected")),
            ("ledger.post on the other service", lambda: post(other, amount="2.00")),
        ):
            with self.subTest(write=label), self.assertRaises(WriteAuthorityError):
                attempt()
            self.assertFalse(b.conn.in_transaction)
        self.assertEqual(self.counts(other), before)
        # reclaiming on one connection gives the same physical copy back to all of them
        self.live.claim_write_authority(actor="owner", reason="taking it back")
        self.assertTrue(b.has_write_authority())
        self.assertFalse(b.read_only)
        party = other.add_party(kind="supplier", name="Synthetic Dewatering Subcontractor")
        self.assertEqual(self.live.party(party["id"])["name"], "Synthetic Dewatering Subcontractor")
        self.assertTrue(self.live.audit.verify_chain()["ok"])

    def test_migrating_an_unclaimed_copy_is_audited(self):
        r = self.restored()
        saved = list(SCHEMA_CATALOG)
        self.addCleanup(SCHEMA_CATALOG.__setitem__, slice(None), saved)
        SCHEMA_CATALOG.append((SCHEMA_CATALOG[-1][0] + 1, "integrity_probe_backfill",
                               ["CREATE TABLE integrity_probe_backfill (id TEXT PRIMARY KEY)", "INSERT INTO integrity_probe_backfill (id) VALUES ('backfilled')"]))
        applied = r.db.migrate()
        self.assertEqual([e["name"] for e in applied], ["integrity_probe_backfill"])
        self.assertTrue(r.db.read_only)  # the copy is read-only again
        self.assertEqual(r.db.scalar("SELECT COUNT(*) FROM integrity_probe_backfill"), 1)
        entry = [e for e in r.audit.entries(entity_type="workspace") if e["action"] == "workspace.schema_migrated_without_authority"]
        self.assertEqual(len(entry), 1)
        self.assertIn('"name":"integrity_probe_backfill"', entry[0]["payload_json"])
        self.assertTrue(r.audit.verify_chain()["ok"])
        with self.assertRaises(WriteAuthorityError):
            r.db.execute("INSERT INTO integrity_probe_backfill (id) VALUES ('raw')")
        # a workspace that holds authority migrates without that entry
        self.live.db.migrate()
        self.assertEqual([e for e in self.live.audit.entries(entity_type="workspace") if e["action"] == "workspace.schema_migrated_without_authority"], [])


# --------------------------------------------------------------------------- #
# 4. sealed journals                                                           #
# --------------------------------------------------------------------------- #

class SealedJournalTests(unittest.TestCase):
    def setUp(self):
        self.c = Cipher()
        self.addCleanup(self.c.db.close)
        self.c.open_period("P1", "P1", "2026-10-01", "2026-10-31")

    def raw_line(self, journal_id, line_no=99, debit="1.00", credit="0.00", account="5000"):
        self.c.db.execute("INSERT INTO journal_lines (id, journal_id, line_no, account_code, debit, credit, memo) VALUES (?,?,?,?,?,?,?)",
                          (f"jln_raw_{line_no}_{journal_id[-6:]}", journal_id, line_no, account, debit, credit, "raw probe"))

    def test_raw_insert_of_an_extra_line_onto_a_posted_journal_is_refused(self):
        j = post(self.c, amount="100.00")
        before = self.c.ledger.journal(j["id"])
        for debit, credit in (("1.00", "0.00"), ("0.00", "1.00"), ("0.00", "0.00")):
            with self.subTest(debit=debit, credit=credit), self.assertRaisesRegex(sqlite3.IntegrityError, "posted journals are immutable"):
                self.raw_line(j["id"], debit=debit, credit=credit)
        self.assertEqual(self.c.ledger.journal(j["id"])["lines"], before["lines"])
        tb = self.c.ledger.trial_balance()
        self.assertEqual((tb["total_debit"], tb["total_credit"], tb["balanced"]), ("100.00", "100.00", True))

    def test_raw_headers_must_declare_a_line_count_and_complete_balanced(self):
        insert = ("INSERT INTO journals (id, period_id, posted_at, description, source_type, source_id, source_version, rule_version, posted_by, line_count) "
                  "VALUES (?, 'P1', 't', 'raw', 'raw', 'raw', '1', 'r', 'raw', ?)")
        for count in (None, 0, 1):
            with self.subTest(line_count=count), self.assertRaisesRegex(sqlite3.IntegrityError, "sealed line count"):
                self.c.db.execute(insert, (f"jrn_raw_{count}", count))
        with self.c.db.transaction():
            self.c.db.execute(insert, ("jrn_raw_two", 2))
            self.raw_line("jrn_raw_two", line_no=1, debit="100.00")
            with self.assertRaisesRegex(sqlite3.IntegrityError, "does not balance"):
                self.raw_line("jrn_raw_two", line_no=2, debit="0.00", credit="99.99")
            self.raw_line("jrn_raw_two", line_no=3, debit="0.00", credit="100.00")
            with self.assertRaisesRegex(sqlite3.IntegrityError, "immutable"):
                self.raw_line("jrn_raw_two", line_no=4, debit="0.00", credit="0.01")
        self.assertTrue(self.c.ledger.trial_balance()["balanced"])

    def test_journal_is_reversed_once_even_by_raw_sql(self):
        j = post(self.c, amount="70.00")
        r = self.c.ledger.reverse(j["id"], period_id="P1", posted_by="tester", reason="posted twice")
        with self.assertRaisesRegex(LedgerError, "reversed once"):
            self.c.ledger.reverse(j["id"], period_id="P1", posted_by="tester", reason="again")
        for verb in ("INSERT", "INSERT OR REPLACE", "REPLACE"):
            with self.subTest(verb=verb), self.assertRaisesRegex(sqlite3.IntegrityError, "reversed once"):
                self.c.db.execute(
                    f"{verb} INTO journals (id, period_id, posted_at, description, source_type, source_id, source_version, rule_version, posted_by, line_count, reversal_of) "
                    "VALUES ('jrn_raw_rev', 'P1', 't', 'raw', 'raw', 'raw', '1', 'r', 'raw', 2, ?)", (j["id"],))
        self.assertEqual(self.c.ledger.journal(j["id"])["reversed_by"], r["id"])
        self.assertEqual(len(self.c.ledger.journal(r["id"])["lines"]), 2)
        self.assertEqual(self.c.ledger.balance("2000"), Decimal("0.00"))

    def raw_header(self, journal_id, line_count=2, period="P1"):
        self.c.db.execute(f"INSERT INTO journals ({JOURNAL_COLUMNS}) VALUES (?, ?, 't', 'raw', 'raw', 'raw', '1', 'r', 'raw', ?)",
                          (journal_id, period, line_count))

    def test_a_journal_must_be_complete_when_it_commits(self):
        j = post(self.c, amount="100.00")
        # autocommit: a header alone is its own transaction, so it cannot commit
        with self.assertRaisesRegex(sqlite3.IntegrityError, "FOREIGN KEY"):
            self.raw_header("jrn_alone")
        # an explicit transaction that ends with a journal short of its declared lines commits nothing
        with self.assertRaisesRegex(sqlite3.IntegrityError, "jrn_half holds fewer lines than its sealed line count"):
            with self.c.db.transaction():
                self.raw_header("jrn_half", line_count=2)
                self.raw_line("jrn_half", line_no=1, debit="500.00")
                post(self.c, amount="7.00")  # ordinary work in the same transaction is rolled back with it
        self.assertFalse(self.c.db.conn.in_transaction)
        # the same on a raw BEGIN ... COMMIT
        self.c.db.execute("BEGIN IMMEDIATE")
        self.raw_header("jrn_raw_txn", line_count=3)
        self.raw_line("jrn_raw_txn", line_no=1, debit="10.00")
        self.raw_line("jrn_raw_txn", line_no=2, credit="10.00", debit="0.00")
        with self.assertRaisesRegex(sqlite3.IntegrityError, "FOREIGN KEY"):
            self.c.db.execute("COMMIT")
        self.c.db.execute("ROLLBACK")
        # the completion marker cannot be removed or defeated by hand
        with self.c.db.transaction():
            self.raw_header("jrn_marker", line_count=2)
            self.raw_line("jrn_marker", line_no=1, debit="3.00")
            for sql in ("DELETE FROM journal_unsealed", "UPDATE journal_unsealed SET pending_completion='x'",
                        "INSERT INTO journal_seal_never (id) VALUES ('jrn_marker')", "REPLACE INTO journal_seal_never (id) VALUES ('jrn_marker')",
                        "PRAGMA foreign_keys = OFF", "PRAGMA defer_foreign_keys = OFF"):
                if sql.startswith("PRAGMA defer"):
                    self.c.db.execute(sql)  # only defers immediate keys; the completion key is deferred already
                    continue
                with self.subTest(sql=sql), self.assertRaises(sqlite3.IntegrityError):
                    self.c.db.execute(sql)
            self.raw_line("jrn_marker", line_no=2, debit="0.00", credit="3.00")  # completing it is the only way through
        self.assertEqual(sorted(r["id"] for r in self.c.db.query("SELECT id FROM journals")), sorted([j["id"], "jrn_marker"]))
        self.assertEqual(self.c.db.scalar("SELECT COUNT(*) FROM journal_unsealed"), 0)
        tb = self.c.ledger.trial_balance()
        self.assertEqual((tb["total_debit"], tb["total_credit"], tb["balanced"]), ("103.00", "103.00", True))
        post(self.c, amount="1.00")  # the connection is healthy afterwards

    def test_raw_lines_need_canonical_amounts_and_exactly_one_side(self):
        with self.c.db.transaction():
            self.raw_header("jrn_amounts", line_count=2)
            for debit, credit in (("1.005", "0.00"), ("abc", "0.00"), ("-5.00", "0.00"), ("1e2", "0.00"), ("01.00", "0.00"),
                                  ("1.0", "0.00"), (".50", "0.00"), ("1.2.3", "0.00"), ("10000000000000.00", "0.00"), ("0.00", "+1.00"),
                                  ("5.00", "1.00 ")):
                with self.subTest(debit=debit, credit=credit), self.assertRaisesRegex(sqlite3.IntegrityError, "canonical money text"):
                    self.raw_line("jrn_amounts", line_no=1, debit=debit, credit=credit)
            for debit, credit in (("1.00", "1.00"), ("0.00", "0.00")):
                with self.subTest(debit=debit, credit=credit), self.assertRaisesRegex(sqlite3.IntegrityError, "exactly one of debit or credit"):
                    self.raw_line("jrn_amounts", line_no=1, debit=debit, credit=credit)
            self.raw_line("jrn_amounts", line_no=1, debit="1.01")
            with self.assertRaisesRegex(sqlite3.IntegrityError, "does not balance"):
                self.raw_line("jrn_amounts", line_no=2, debit="0.00", credit="1.00")  # REAL rounding of 1.005 would have hidden this
            self.raw_line("jrn_amounts", line_no=2, debit="0.00", credit="1.01", account="2000")
        tb = self.c.ledger.trial_balance()  # every stored amount still parses as money
        self.assertEqual((tb["total_debit"], tb["total_credit"], tb["balanced"]), ("1.01", "1.01", True))
        self.assertEqual(self.c.ledger.balance("5000"), Decimal("1.01"))

    def test_older_workspace_is_backfilled_and_sealed_on_upgrade(self):
        d = tempfile.mkdtemp(prefix="cipher-integrity-upgrade-")
        path = os.path.join(d, "old.sqlite")
        saved = list(SCHEMA_CATALOG)
        try:
            del SCHEMA_CATALOG[1:]  # a release that only had the foundation
            old = Database(path)
            old.execute("INSERT INTO periods (id, name, start_date, end_date, status) VALUES ('P1','P1','2026-10-01','2026-10-31','open')")
            old.execute("INSERT INTO accounts (code, name, type) VALUES ('5000','Cost','expense'), ('2000','AP','liability')")
            old.execute("INSERT INTO journals (id, period_id, posted_at, description, source_type, source_id, source_version, rule_version, posted_by) "
                        "VALUES ('jrn_old','P1','t','old','old','old','1','r','old')")
            old.execute("INSERT INTO journal_lines (id, journal_id, line_no, account_code, debit, credit) VALUES ('l1','jrn_old',1,'5000','42.00','0.00'), ('l2','jrn_old',2,'2000','0.00','42.00')")
            old.close()
        finally:
            SCHEMA_CATALOG[:] = saved
        upgraded = Database(path)
        self.addCleanup(upgraded.close)
        self.assertEqual(upgraded.schema_status()["pending"], [])
        self.assertEqual(upgraded.scalar("SELECT line_count FROM journals WHERE id='jrn_old'"), 2)
        with self.assertRaisesRegex(sqlite3.IntegrityError, "posted journals are immutable"):
            upgraded.execute("INSERT INTO journal_lines (id, journal_id, line_no, account_code, debit, credit) VALUES ('l3','jrn_old',3,'5000','1.00','0.00')")
        with self.assertRaisesRegex(sqlite3.IntegrityError, "posted journals are immutable"):
            upgraded.execute("UPDATE journals SET line_count=3 WHERE id='jrn_old'")  # the recreated trigger
        sql = upgraded.scalar("SELECT sql FROM sqlite_master WHERE type='trigger' AND name='journals_no_update'")
        foundation = next(s for s in SCHEMA_CATALOG[0][2] if "journals_no_update" in s)
        self.assertEqual(sql, foundation)


# --------------------------------------------------------------------------- #
# 5. period integrity                                                          #
# --------------------------------------------------------------------------- #

class PeriodIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.db = Database()
        self.addCleanup(self.db.close)
        self.audit = Audit(self.db)
        self.approvals = Approvals(self.db, self.audit)
        self.ledger = Ledger(self.db, self.audit)
        self.ledger.ensure_chart()
        for pid, start, end in (("P1", "2026-10-01", "2026-10-31"), ("P2", "2026-11-01", "2026-11-30"), ("P3", "2026-12-01", "2026-12-31")):
            self.ledger.open_period(pid, pid, start, end)
        post(self.ledger, "P1")

    def approval(self, period_id, *, operation="close.reopen_period", status="consumed"):
        m = build_manifest(operation=operation, subject_type="period", subject_id=period_id, actor_role="controller", bindings={"probe": "period integrity"})
        ap = self.approvals.request(m, requested_by="controller")
        if status in ("granted", "consumed"):
            self.approvals.grant(ap["id"], approver="owner")
        if status == "consumed":
            self.approvals.consume(ap["id"], current_manifest=m, consumer="controller")
        return ap["id"]

    def raw_reopen(self, period_id, approval_id):
        self.db.execute("UPDATE periods SET status='open', closed_at=NULL, closed_by=NULL, reopen_approval_id=? WHERE id=?", (approval_id, period_id))

    def status(self, period_id):
        return self.ledger.period(period_id)["status"]

    def test_a_locked_period_never_changes(self):
        self.ledger.close_period("P1", actor="controller")
        self.ledger.lock_period("P1", actor="controller")
        ref = self.approval("P1")
        for sql, params in (("UPDATE periods SET status='open' WHERE id='P1'", ()),
                            ("UPDATE periods SET status='closed' WHERE id='P1'", ()),
                            ("UPDATE periods SET status='locked' WHERE id='P1'", ()),
                            ("UPDATE periods SET name='renamed' WHERE id='P1'", ()),
                            ("UPDATE periods SET end_date='2026-11-30' WHERE id='P1'", ()),
                            ("UPDATE periods SET status='open', reopen_approval_id=? WHERE id='P1'", (ref,)),
                            ("DELETE FROM periods WHERE id='P1'", ())):
            with self.subTest(sql=sql), self.assertRaisesRegex(sqlite3.IntegrityError, "immutable"):
                self.db.execute(sql, params)
        p = self.ledger.period("P1")
        self.assertEqual((p["status"], p["name"], p["end_date"]), ("locked", "P1", "2026-10-31"))
        with self.assertRaises(PeriodNotOpen):
            post(self.ledger, "P1")
        with self.assertRaises(PeriodNotOpen):
            self.ledger.reopen_period("P1", actor="controller", approval_ref=ref)

    def test_status_transitions_are_limited(self):
        with self.assertRaisesRegex(sqlite3.IntegrityError, "period status may only move"):
            self.db.execute("UPDATE periods SET status='locked' WHERE id='P2'")  # open -> locked skips the close
        self.ledger.close_period("P2", actor="controller")
        self.db.execute("UPDATE periods SET closed_by='controller-2' WHERE id='P2'")  # a closed period's other columns may change
        with self.assertRaisesRegex(sqlite3.IntegrityError, "reopen approval is recorded only"):
            self.db.execute("UPDATE periods SET reopen_approval_id='apr_x' WHERE id='P3'")  # never outside a reopen
        with self.assertRaisesRegex(sqlite3.IntegrityError, "cannot be deleted"):
            self.db.execute("DELETE FROM periods WHERE id='P2'")
        self.assertEqual(self.status("P2"), "closed")

    def test_raw_reopen_needs_a_consumed_scoped_unused_reopen_approval(self):
        self.ledger.close_period("P1", actor="controller")
        self.ledger.close_period("P2", actor="controller")
        probes = (
            ("without an approval", "UPDATE periods SET status='open' WHERE id='P1'", ()),
            ("fabricated approval", "UPDATE periods SET status='open', reopen_approval_id='apr_fabricated' WHERE id='P1'", ()),
            ("pending approval", None, (self.approval("P1", status="pending"),)),
            ("granted, unconsumed approval", None, (self.approval("P1", status="granted"),)),
            ("approval for another period", None, (self.approval("P2"),)),
            ("approval for another operation", None, (self.approval("P1", operation="close.close_period"),)),
            ("operation that only resembles a reopen", None, (self.approval("P1", operation="close.reopenXperiod"),)),
        )
        for label, sql, params in probes:
            with self.subTest(probe=label), self.assertRaisesRegex(sqlite3.IntegrityError, "requires a consumed reopen_period approval"):
                if sql:
                    self.db.execute(sql, params)
                else:
                    self.raw_reopen("P1", params[0])
            self.assertEqual(self.status("P1"), "closed")
        self.assertEqual(self.ledger.reopens(), [])
        # a genuine consumed approval works on the raw path too, and is logged once
        ref = self.approval("P1")
        self.raw_reopen("P1", ref)
        self.assertEqual(self.status("P1"), "open")
        self.assertEqual([(r["approval_id"], r["period_id"]) for r in self.ledger.reopens()], [(ref, "P1")])
        self.ledger.close_period("P1", actor="controller")
        with self.assertRaisesRegex(sqlite3.IntegrityError, "already used"):
            self.raw_reopen("P1", ref)
        self.assertEqual(self.status("P1"), "closed")
        with self.assertRaisesRegex(LedgerError, "already reopened period P1"):
            self.ledger.reopen_period("P1", actor="controller", approval_ref=ref)
        # the reopen log is append-only
        for sql in ("UPDATE period_reopens SET period_id='P2'", "DELETE FROM period_reopens"):
            with self.subTest(sql=sql), self.assertRaisesRegex(sqlite3.IntegrityError, "append-only"):
                self.db.execute(sql)

    def test_ledger_reopen_validates_in_python_and_records_the_approval(self):
        self.ledger.close_period("P1", actor="controller")
        for ref, message in (("", "requires the id"), ("apr_fabricated", "not a recorded approval"),
                             (self.approval("P1", status="granted"), "only a consumed"), (self.approval("P2"), "scoped to period P2"),
                             (self.approval("P1", operation="asset.capitalise"), "not a reopen_period approval")):
            with self.subTest(message=message), self.assertRaisesRegex(LedgerError, message):
                self.ledger.reopen_period("P1", actor="controller", approval_ref=ref)
        ref = self.approval("P1")
        p = self.ledger.reopen_period("P1", actor="controller", approval_ref=ref)
        self.assertEqual((p["status"], p["reopen_approval_id"], p["closed_at"]), ("open", ref, None))
        entry = [e for e in self.audit.entries(entity_type="period", entity_id="P1") if e["action"] == "period.reopened"][-1]
        self.assertIn(ref, entry["payload_json"])
        self.assertTrue(self.audit.verify_chain()["ok"])

    def raw_approval(self, approval_id, *, status="pending", operation="close.reopen_period", subject_type="period", subject_id="P2", **extra):
        cols = {"id": approval_id, "operation": operation, "subject_type": subject_type, "subject_id": subject_id, "actor_role": "controller",
                "manifest_json": "{}", "manifest_hash": "h", "material_hash": "h", "policy_version": "p", "nonce": f"nonce-{approval_id}",
                "status": status, "requested_by": "raw", "requested_at": "2026-10-12T00:00:00Z", "expires_at": "2099-01-01T00:00:00Z", **extra}
        self.db.execute(f"INSERT INTO approvals ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})", tuple(cols.values()))

    def test_fabricated_and_rewritten_approvals_are_refused(self):
        self.ledger.close_period("P2", actor="controller")
        # a row born consumed (the reviewer's probe) or carrying a grant is refused outright
        for label, extra in (("born consumed", {"status": "consumed"}), ("born granted", {"status": "granted", "approver": "x", "granted_at": "t"}),
                             ("pending with an approver", {"approver": "x"}), ("pending with a consumer", {"consumed_by": "x", "consumed_at": "t"})):
            with self.subTest(probe=label), self.assertRaisesRegex(sqlite3.IntegrityError, "recorded pending"):
                self.raw_approval(f"apr_fab_{len(label)}", **extra)
        # a raw pending row cannot jump to consumed, nor be granted without its approver
        self.raw_approval("apr_raw_pending")
        for sql, message in (("UPDATE approvals SET status='consumed', consumed_at='t', consumed_by='x' WHERE id='apr_raw_pending'", "forward only"),
                             ("UPDATE approvals SET status='granted' WHERE id='apr_raw_pending'", "records its approver"),
                             ("UPDATE approvals SET status='pending', approver='x' WHERE id='apr_raw_pending'", "records its approver")):
            with self.subTest(sql=sql), self.assertRaisesRegex(sqlite3.IntegrityError, message):
                self.db.execute(sql)
        with self.assertRaisesRegex(sqlite3.IntegrityError, "requires a consumed reopen_period approval"):
            self.raw_reopen("P2", "apr_raw_pending")
        # a consumed approval never changes and is never deleted
        ref = self.approval("P2")
        for sql in ("UPDATE approvals SET status='granted' WHERE id=?", "UPDATE approvals SET status='invalidated' WHERE id=?",
                    "UPDATE approvals SET consumed_by='mallory' WHERE id=?", "UPDATE approvals SET subject_id='P3' WHERE id=?",
                    "UPDATE approvals SET manifest_json='{}' WHERE id=?", "UPDATE approvals SET operation='close.lock_period' WHERE id=?",
                    "UPDATE approvals SET expires_at='2099-01-01T00:00:00Z' WHERE id=?", "DELETE FROM approvals WHERE id=?"):
            with self.subTest(sql=sql), self.assertRaises(sqlite3.IntegrityError):
                self.db.execute(sql, (ref,))
        stored = self.approvals.get(ref)
        self.assertEqual((stored["status"], stored["subject_id"], stored["operation"]), ("consumed", "P2", "close.reopen_period"))
        # an approval's expiry can be brought forward (a test or an operator expiring it) but never extended
        pending = self.approval("P3", status="pending")
        with self.assertRaisesRegex(sqlite3.IntegrityError, "expiry can only be brought forward"):
            self.db.execute("UPDATE approvals SET expires_at='2999-01-01T00:00:00Z' WHERE id=?", (pending,))
        self.db.execute("UPDATE approvals SET expires_at='2000-01-01T00:00:00Z' WHERE id=?", (pending,))
        self.approvals.invalidate(pending, reason="withdrawn")
        self.approvals.invalidate(pending, reason="withdrawn again")  # invalidated stays invalidated
        self.assertEqual(self.approvals.get(pending)["status"], "invalidated")
        # the genuine approval still reopens the period exactly once
        self.ledger.reopen_period("P2", actor="controller", approval_ref=ref)
        self.assertEqual(self.status("P2"), "open")

    def test_reopen_needs_a_period_scoped_approval_that_was_granted_and_consumed(self):
        self.ledger.close_period("P2", actor="controller")
        m = build_manifest(operation="evil.reopen_period", subject_type="journal", subject_id="P2", actor_role="controller")
        ap = self.approvals.request(m, requested_by="controller")
        self.approvals.grant(ap["id"], approver="owner")
        self.approvals.consume(ap["id"], current_manifest=m, consumer="controller")
        with self.assertRaisesRegex(LedgerError, "scoped to a journal, not a period"):
            self.ledger.reopen_period("P2", actor="controller", approval_ref=ap["id"])
        with self.assertRaisesRegex(sqlite3.IntegrityError, "requires a consumed reopen_period approval"):
            self.raw_reopen("P2", ap["id"])
        self.assertEqual((self.status("P2"), self.ledger.reopens()), ("closed", []))
        # subject type "accounting_period" (the close module's) is a period too
        m2 = build_manifest(operation="ledger.reopen_period", subject_type="accounting_period", subject_id="P2", actor_role="controller")
        ap2 = self.approvals.request(m2, requested_by="controller")
        self.approvals.grant(ap2["id"], approver="owner")
        self.approvals.consume(ap2["id"], current_manifest=m2, consumer="controller")
        self.assertEqual(self.ledger.reopen_period("P2", actor="controller", approval_ref=ap2["id"])["status"], "open")

    def test_governed_reopen_through_the_close_module(self):
        c = Cipher()
        self.addCleanup(c.db.close)
        if c._core_owner("close.reopen_period") is None and "close" not in c._plugins:
            self.skipTest("close module not registered")
        c.open_period("P1", "P1", "2026-10-01", "2026-10-31")
        c.close_period("P1")
        with self.assertRaises(LedgerError):
            c.ledger.reopen_period("P1", actor="owner", approval_ref="direct ledger path")
        res = c.approve_and_execute("close.reopen_period", "P1", actor_role="controller", actor="controller")
        self.assertEqual(c.ledger.period("P1")["status"], "open")
        self.assertEqual([r["period_id"] for r in c.ledger.reopens("P1")], ["P1"])
        self.assertEqual(c.ledger.period("P1")["reopen_approval_id"], c.ledger.reopens("P1")[0]["approval_id"])
        self.assertFalse(res.replayed)


# --------------------------------------------------------------------------- #
# 6. INSERT OR REPLACE cannot rewrite immutable core rows                      #
# --------------------------------------------------------------------------- #

class ReplaceProbeTests(unittest.TestCase):
    """With recursive_triggers off, the delete that INSERT OR REPLACE performs fires no
    delete trigger; every immutable core table therefore refuses a colliding insert."""

    VERBS = ("INSERT OR REPLACE", "REPLACE", "INSERT OR IGNORE")

    def setUp(self):
        self.c = c = Cipher()
        self.addCleanup(c.db.close)
        for pid, start, end in (("P1", "2026-10-01", "2026-10-31"), ("P2", "2026-11-01", "2026-11-30"), ("P3", "2026-12-01", "2026-12-31")):
            c.open_period(pid, pid, start, end)
        self.project = c.create_project(name="Synthetic cofferdam", entity=ENTITY, budget="50000")
        self.j1 = post(c, "P1", amount="100.00", source_id="locked")
        self.j2 = post(c, "P2", amount="50.00", source_id="closed")
        c.ledger.close_period("P1", actor="controller")
        c.ledger.lock_period("P1", actor="controller")
        # a governed reopen of P2 leaves a reopen-log row and a consumed approval behind
        m = build_manifest(operation="close.reopen_period", subject_type="period", subject_id="P2", actor_role="controller")
        self.reopen_ap = c.approvals.request(m, requested_by="controller")["id"]
        c.approvals.grant(self.reopen_ap, approver="owner")
        c.approvals.consume(self.reopen_ap, current_manifest=m, consumer="controller")
        c.ledger.close_period("P2", actor="controller")
        c.ledger.reopen_period("P2", actor="controller", approval_ref=self.reopen_ap)
        c.ledger.close_period("P2", actor="controller")
        # an executed governed reversal in P3
        self.j3 = post(c, "P3", amount="30.00", source_id="reversed")
        self.request = c.ledger.prepare_reversal(self.j3["id"], "posted twice", "accountant")
        ap = c.request_approval("journal.reverse", self.j3["id"], actor_role="accountant", requested_by="accountant")
        c.approve(ap["id"], approver="controller", approver_role="controller")
        self.rev = c.execute(ap["id"], actor="accountant", period_id="P3").result
        self.reverse_ap = ap["id"]
        doc = c.evidence.register_document(project_id=self.project["id"], kind="drawing", title="Synthetic sheet pile layout", actor="pm")
        self.revision = c.evidence.add_revision(document_id=doc["id"], content=b"synthetic drawing rev 1", actor="pm")
        self.snapshot = self.state()

    def state(self):
        db = self.c.db
        dump = {t: db.query(f"SELECT * FROM {t} ORDER BY rowid") for t in
                ("periods", "journals", "journal_lines", "journal_reversal_requests", "approvals", "period_reopens", "document_revisions")}
        dump["audit_count"] = db.scalar("SELECT COUNT(*) FROM audit_log")
        return dump

    def refused(self, sql, params=(), message="immutable|append-only|never replaced|reused or replaced|reversed once|not open for posting"):
        for verb in self.VERBS:
            with self.subTest(sql=sql[:60], verb=verb), self.assertRaisesRegex(sqlite3.IntegrityError, message):
                self.c.db.execute(f"{verb} {sql}", params)

    def assert_unchanged(self):
        self.assertEqual(self.state(), self.snapshot)
        self.assertTrue(self.c.audit.verify_chain()["ok"])
        tb = self.c.ledger.trial_balance()
        self.assertTrue(tb["balanced"])
        self.assertEqual(self.c.ledger.trial_balance("P1")["total_debit"], "100.00")

    def test_periods_cannot_be_replaced_open(self):
        self.refused("INTO periods (id, name, start_date, end_date, status) VALUES ('P1', 'P1', '2026-10-01', '2026-10-31', 'open')")  # locked
        self.refused("INTO periods (id, name, start_date, end_date, status) VALUES ('P2', 'P2', '2026-11-01', '2026-11-30', 'open')")  # closed
        self.refused("INTO periods (id, name, start_date, end_date, status) VALUES ('P3', 'P3', '2026-12-01', '2026-12-31', 'locked')")  # open, skipping the close
        with self.assertRaisesRegex(sqlite3.IntegrityError, "never replaced"):
            self.c.db.execute("INSERT INTO periods (id, name, start_date, end_date, status) VALUES ('P1', 'P1', '2026-10-01', '2026-10-31', 'open') "
                              "ON CONFLICT(id) DO UPDATE SET status='open'")
        for status in ("closed", "locked"):
            with self.subTest(born=status), self.assertRaisesRegex(sqlite3.IntegrityError, "created open"):
                self.c.db.execute("INSERT INTO periods (id, name, start_date, end_date, status) VALUES ('P9', 'P9', '2027-01-01', '2027-01-31', ?)", (status,))
        self.assert_unchanged()
        self.assertEqual([(p["id"], p["status"]) for p in self.c.ledger.periods()], [("P1", "locked"), ("P2", "closed"), ("P3", "open")])
        self.assertEqual(len(self.c.ledger.reopens()), 1)
        with self.assertRaises(PeriodNotOpen):
            post(self.c, "P1", amount="1.00")

    def test_posted_journals_and_lines_cannot_be_replaced(self):
        j1, line = self.j1, self.j1["lines"][0]
        # the reviewer's probes: rewrite the header's line count and description, or move it out of locked P1
        for period, count in (("P1", 4), ("P3", 4), ("P3", 2)):
            self.refused(f"INTO journals ({JOURNAL_COLUMNS}) VALUES (?, ?, 't', 'rewritten', 'raw', 'raw', '1', 'r', 'mallory', ?)", (j1["id"], period, count))
        self.refused("INTO journal_lines (id, journal_id, line_no, account_code, debit, credit, memo) VALUES (?, ?, 1, '5000', '900.00', '0.00', 'rewritten')",
                     (line["id"], j1["id"]))
        self.refused("INTO journal_lines (id, journal_id, line_no, account_code, debit, credit, memo) VALUES (?, ?, 1, '5000', '900.00', '0.00', 'moved')",
                     (line["id"], self.j3["id"]))
        with self.assertRaisesRegex(sqlite3.IntegrityError, "reused or replaced"):
            self.c.db.execute(f"INSERT INTO journals ({JOURNAL_COLUMNS}) VALUES (?, 'P3', 't', 'x', 'raw', 'raw', '1', 'r', 'x', 2) "
                              "ON CONFLICT(id) DO UPDATE SET description='rewritten'", (j1["id"],))
        self.assert_unchanged()
        self.assertEqual(self.c.ledger.journal(j1["id"])["description"], "integrity probe")
        self.assertEqual(self.c.ledger.balance("2000"), Decimal("150.00"))

    def test_resolved_reversal_requests_cannot_be_replaced(self):
        req = self.c.ledger.reversal_request(self.request["id"])
        self.assertEqual(req["status"], "executed")
        self.refused("INTO journal_reversal_requests (id, journal_id, reason, status, requested_by, requested_at) VALUES (?, ?, 'a different reason', 'pending', 'mallory', 't')",
                     (req["id"], self.j3["id"]))
        # a second pending request for a journal (the partial unique index) is refused the same way
        self.c.ledger.prepare_reversal(self.j2["id"], "wrong period", "accountant")
        snapshot = self.state()
        with self.assertRaisesRegex(sqlite3.IntegrityError, "already has a pending reversal request"):
            self.c.db.execute("REPLACE INTO journal_reversal_requests (id, journal_id, reason, status, requested_by, requested_at) VALUES ('jrr_raw', ?, 'rewritten', 'pending', 'x', 't')",
                              (self.j2["id"],))
        self.assertEqual(self.state(), snapshot)

    def test_approvals_audit_reopen_log_and_revisions_cannot_be_replaced(self):
        ap = self.c.approvals.get(self.reverse_ap)
        self.assertEqual(ap["status"], "consumed")
        cols = "id, operation, subject_type, subject_id, actor_role, manifest_json, manifest_hash, material_hash, policy_version, nonce, status, requested_by, requested_at, expires_at"
        values = "?, 'journal.reverse', 'journal', ?, 'accountant', '{}', 'h', 'h', 'p', ?, 'pending', 'mallory', 't', '2099-01-01T00:00:00Z'"
        self.refused(f"INTO approvals ({cols}) VALUES ({values})", (ap["id"], self.j3["id"], "fresh-nonce"))  # the consumed approval, reset to pending
        stored_nonce = ap["manifest"]["nonce"]
        self.refused(f"INTO approvals ({cols}) VALUES ({values})", ("apr_other", self.j3["id"], stored_nonce))  # collides on the nonce
        first = self.c.db.one("SELECT * FROM audit_log ORDER BY seq LIMIT 1")
        self.refused("INTO audit_log (seq, ts, actor, action, entity_type, entity_id, payload_json, payload_hash, prev_hash, entry_hash) "
                     "VALUES (?, 't', 'mallory', 'forged', 't', '1', '{}', 'h', ?, 'forged-hash')", (first["seq"], first["prev_hash"]))
        self.refused("INTO audit_log (ts, actor, action, entity_type, entity_id, payload_json, payload_hash, prev_hash, entry_hash) "
                     "VALUES ('t', 'mallory', 'forged', 't', '1', '{}', 'h', 'h', ?)", (first["entry_hash"],))
        self.refused("INTO period_reopens (approval_id, period_id, reopened_at) VALUES (?, 'P3', 't')", (self.reopen_ap,))
        with self.assertRaisesRegex(sqlite3.IntegrityError, "written only by the reopen"):
            self.c.db.execute("INSERT INTO period_reopens (approval_id, period_id, reopened_at) VALUES (?, 'P3', 't')", (self.reverse_ap,))
        rev = self.revision
        self.refused("INTO document_revisions (id, document_id, revision, content_hash, note, created_at) VALUES (?, ?, ?, 'forged', 'x', 't')",
                     (rev["id"], rev["document_id"], rev["revision"]))
        self.refused("INTO document_revisions (id, document_id, revision, content_hash, note, created_at) VALUES ('rev_forged', ?, ?, 'forged', 'x', 't')",
                     (rev["document_id"], rev["revision"]))
        self.assert_unchanged()


# --------------------------------------------------------------------------- #
# 7. governed correction: journal.reverse                                      #
# --------------------------------------------------------------------------- #

class GovernedReversalTests(unittest.TestCase):
    def setUp(self):
        self.c = c = Cipher()
        self.addCleanup(c.db.close)
        for pid, start, end in (("P0", "2026-09-01", "2026-09-30"), ("P1", "2026-10-01", "2026-10-31"),
                                ("P2", "2026-11-01", "2026-11-30"), ("P3", "2026-12-01", "2026-12-31")):
            c.open_period(pid, pid, start, end)
        c.close_period("P2")
        self.project = c.create_project(name="Synthetic cofferdam dewatering", entity="S&A Solutions LLC (synthetic)", budget="90000")
        self.j = post(c, "P1", amount="1234.56", project_id=self.project["id"], source_id="miscoded-cost")

    def requested(self, journal_id, *, reason="posted to the wrong cost account", role="accountant"):
        self.c.ledger.prepare_reversal(journal_id, reason, "accountant")
        ap = self.c.request_approval("journal.reverse", journal_id, actor_role=role, requested_by="accountant")
        self.c.approve(ap["id"], approver="controller", approver_role="controller")
        return ap

    def test_reversal_through_request_grant_and_execute(self):
        c, jid = self.c, self.j["id"]
        with self.assertRaisesRegex(LedgerError, "no reversal request"):
            c.request_approval("journal.reverse", jid, actor_role="accountant")
        req = c.ledger.prepare_reversal(jid, "posted to the wrong cost account", "accountant")
        self.assertEqual(req["status"], "pending")
        with self.assertRaisesRegex(LedgerError, "already has pending reversal request"):
            c.ledger.prepare_reversal(jid, "a second reason", "accountant")
        for role in ("pm", "viewer", "estimator", "treasury"):
            with self.subTest(role=role), self.assertRaises(RoleNotAuthorized):
                c.request_approval("journal.reverse", jid, actor_role=role)
        ap = c.request_approval("journal.reverse", jid, actor_role="accountant", requested_by="accountant")
        m = ap["manifest"]
        self.assertEqual((m["operation"], m["subject"]), ("journal.reverse", {"type": "journal", "id": jid}))
        self.assertEqual(m["amounts"], {"total_debit": "1234.56", "total_credit": "1234.56"})
        self.assertEqual((m["entity"], m["currency"]), ("S&A Solutions LLC (synthetic)", "USD"))
        b = m["bindings"]
        self.assertEqual((b["reason"], b["already_reversed"], b["line_count"], b["period_id"]), ("posted to the wrong cost account", False, 2, "P1"))
        self.assertEqual(b["source"], {"type": "integrity_test", "id": "miscoded-cost", "version": "1"})
        self.assertEqual(b["reversal_request"]["id"], req["id"])
        self.assertEqual(len(b["lines_fingerprint"]), 64)
        with self.assertRaises(RoleNotAuthorized):
            c.approve(ap["id"], approver="pm", approver_role="pm")
        with self.assertRaises(Exception):
            c.execute(ap["id"], actor="accountant", period_id="P3")  # not granted yet
        c.approve(ap["id"], approver="controller", approver_role="controller")
        refusals = ((None, LedgerError, "needs period_id"), ("P0", LedgerError, "cannot be dated before"),
                    ("P2", PeriodNotOpen, "P2 is closed"), ("P9", LedgerError, "unknown period"))
        for period, error, message in refusals:
            with self.subTest(period=period), self.assertRaisesRegex(error, message):
                c.execute(ap["id"], actor="accountant", period_id=period, op_id=f"try:{period}")
            self.assertEqual(c.approvals.get(ap["id"])["status"], "granted")  # a refused execution consumes nothing
            self.assertIsNone(c.ledger.journal(jid)["reversed_by"])
        res = c.execute(ap["id"], actor="accountant", period_id="P3")
        self.assertFalse(res.replayed)
        out = res.result
        self.assertEqual((out["status"], out["period_id"], out["reason"], out["total"], out["request_id"]),
                         ("reversed", "P3", "posted to the wrong cost account", "1234.56", req["id"]))
        rev = c.ledger.journal(out["reversal_journal_id"])
        self.assertEqual((rev["reversal_of"], rev["approval_id"], rev["period_id"], rev["line_count"]), (jid, ap["id"], "P3", 2))
        self.assertEqual(rev["description"], f"Reversal of {jid}: posted to the wrong cost account")
        self.assertEqual([(ln["account_code"], ln["debit"], ln["credit"]) for ln in rev["lines"]],
                         [("5000", "0.00", "1234.56"), ("2000", "1234.56", "0.00")])
        self.assertEqual(c.ledger.balance("5000"), Decimal("0.00"))
        self.assertEqual(c.ledger.balance("2000"), Decimal("0.00"))
        self.assertEqual(c.ledger.balance("5000", project_id=self.project["id"]), Decimal("0.00"))
        tb = c.ledger.trial_balance()
        self.assertEqual((tb["total_debit"], tb["total_credit"], tb["balanced"]), ("2469.12", "2469.12", True))
        done = c.ledger.reversal_request(req["id"])
        self.assertEqual((done["status"], done["approval_id"], done["reversal_journal_id"]), ("executed", ap["id"], rev["id"]))
        self.assertEqual(c.approvals.get(ap["id"])["status"], "consumed")
        again = c.execute(ap["id"], actor="accountant", period_id="P3")
        self.assertTrue(again.replayed)
        self.assertEqual(again.result, out)
        self.assertEqual(len(c.ledger.journals()), 2)
        with self.assertRaisesRegex(LedgerError, "reversed once"):
            c.ledger.prepare_reversal(jid, "and again", "accountant")
        with self.assertRaisesRegex(sqlite3.IntegrityError, "immutable once resolved"):
            c.db.execute("UPDATE journal_reversal_requests SET status='pending' WHERE id=?", (req["id"],))
        with self.assertRaisesRegex(sqlite3.IntegrityError, "append-only"):
            c.db.execute("DELETE FROM journal_reversal_requests")
        actions = [e["action"] for e in c.audit.entries(entity_type="journal", entity_id=jid)]
        self.assertEqual(actions, ["journal.posted", "journal.reversal_requested", "journal.reversed"])
        self.assertTrue(c.audit.verify_chain()["ok"])

    def test_changed_reason_makes_the_approval_stale(self):
        ap = self.requested(self.j["id"])
        req = self.c.ledger.reversal_requests(self.j["id"])[-1]
        self.c.ledger.cancel_reversal_request(req["id"], actor="accountant", reason="wrong reason recorded")
        self.c.ledger.prepare_reversal(self.j["id"], "duplicate of another posting", "accountant")
        with self.assertRaises(StaleApprovalError):
            self.c.execute(ap["id"], actor="accountant", period_id="P3")
        self.assertEqual(self.c.approvals.get(ap["id"])["status"], "invalidated")
        self.assertIsNone(self.c.ledger.journal(self.j["id"])["reversed_by"])
        fresh = self.c.request_approval("journal.reverse", self.j["id"], actor_role="controller", requested_by="controller")
        self.c.approve(fresh["id"], approver="owner")
        out = self.c.execute(fresh["id"], actor="controller", period_id="P1").result
        self.assertEqual(out["reason"], "duplicate of another posting")

    def test_reversal_outside_the_approval_makes_it_stale(self):
        ap = self.requested(self.j["id"])
        direct = self.c.ledger.reverse(self.j["id"], period_id="P3", posted_by="accountant", reason="direct correction")
        req = self.c.ledger.reversal_requests(self.j["id"])[-1]
        self.assertEqual((req["status"], req["reversal_journal_id"]), ("cancelled", direct["id"]))
        with self.assertRaises(StaleApprovalError):
            self.c.execute(ap["id"], actor="accountant", period_id="P3")
        self.assertEqual(self.c.approvals.get(ap["id"])["status"], "invalidated")
        self.assertEqual(len(self.c.ledger.journals()), 2)  # still exactly one reversal

    def test_approval_is_bound_to_its_journal(self):
        other = post(self.c, "P1", amount="10.00", source_id="other")
        ap = self.requested(self.j["id"])
        self.c.ledger.prepare_reversal(other["id"], "unrelated", "accountant")
        res = self.c.execute(ap["id"], actor="accountant", period_id="P1").result
        self.assertEqual(res["journal_id"], self.j["id"])
        self.assertIsNone(self.c.ledger.journal(other["id"])["reversed_by"])
        self.assertEqual(self.c.ledger.reversal_requests(other["id"])[-1]["status"], "pending")

    def test_invalid_reversal_requests_are_refused(self):
        with self.assertRaisesRegex(LedgerError, "unknown journal"):
            self.c.ledger.prepare_reversal("jrn_missing", "reason", "accountant")
        for reason in ("", "   ", None, 12, "x" * 501):
            with self.subTest(reason=str(reason)[:10]), self.assertRaises(LedgerError):
                self.c.ledger.prepare_reversal(self.j["id"], reason, "accountant")
        with self.assertRaises(LedgerError):
            self.c.ledger.prepare_reversal(self.j["id"], "reason", "")
        with self.assertRaisesRegex(LedgerError, "unknown reversal request"):
            self.c.ledger.cancel_reversal_request("jrr_missing", actor="accountant", reason="x")
        self.assertEqual(self.c.ledger.reversal_requests(self.j["id"]), [])
        with self.assertRaisesRegex(sqlite3.IntegrityError, "starts pending"):
            self.c.db.execute("INSERT INTO journal_reversal_requests (id, journal_id, reason, status, requested_by, requested_at) VALUES ('jrr_raw', ?, 'raw', 'executed', 'x', 't')",
                              (self.j["id"],))

    def reverse_approvals(self):
        return [a for a in self.c.approvals.list() if a["operation"] == "journal.reverse"]

    def test_no_approval_against_a_canceled_request_or_a_reversed_journal(self):
        c, jid = self.c, self.j["id"]
        req = c.ledger.prepare_reversal(jid, "posted to the wrong cost account", "accountant")
        c.ledger.cancel_reversal_request(req["id"], actor="accountant", reason="recorded in error")
        with self.assertRaisesRegex(ReversalNotAvailable, "is canceled; prepare a new reversal request") as cm:
            c.request_approval("journal.reverse", jid, actor_role="accountant", requested_by="accountant")
        self.assertIsInstance(cm.exception, LedgerError)
        self.assertEqual(self.reverse_approvals(), [])
        # an approval granted while the request was pending goes stale (invalidated) once it is canceled
        ap = self.requested(jid)
        c.ledger.cancel_reversal_request(c.ledger.reversal_requests(jid)[-1]["id"], actor="accountant", reason="withdrawn")
        with self.assertRaises(StaleApprovalError):
            c.execute(ap["id"], actor="accountant", period_id="P3")
        self.assertEqual(c.approvals.get(ap["id"])["status"], "invalidated")
        # once the journal is reversed, no journal.reverse approval can be requested for it
        c.ledger.reverse(jid, period_id="P3", posted_by="accountant", reason="direct correction")
        with self.assertRaisesRegex(ReversalNotAvailable, "already reversed"):
            c.request_approval("journal.reverse", jid, actor_role="accountant", requested_by="accountant")
        self.assertEqual([a["status"] for a in self.reverse_approvals()], ["invalidated"])
        self.assertEqual(len(c.ledger.journals()), 2)
        self.assertTrue(c.ledger.trial_balance()["balanced"])

    def test_a_reversal_journal_is_never_reversed_through_journal_reverse(self):
        rev = self.c.ledger.reverse(self.j["id"], period_id="P1", posted_by="accountant", reason="posted twice")
        with self.assertRaisesRegex(LedgerError, "itself the reversal of"):
            self.c.ledger.prepare_reversal(rev["id"], "undo the correction", "accountant")
        self.assertEqual(self.c.ledger.reversal_requests(rev["id"]), [])

    def bill_journal(self):
        """A posted subcontract bill (AP 9000.00, retainage 1000.00) and its journal."""
        c = self.c
        sup = c.add_party(kind="supplier", name="Synthetic sheet pile subcontractor", destination="ACH-SIM-INT-0001")
        c.verify_destination(sup["id"], destination="ACH-SIM-INT-0001", verified_by="owner")
        cmt = c.commitments.create(project_id=self.project["id"], supplier_id=sup["id"], title="Synthetic cofferdam subcontract",
                                   sov_lines=[{"description": "Sheet pile installation", "amount": "10000", "cost_code": "XX 10 00"}],
                                   retainage_rate="0.10", actor="pm")
        c.approve_and_execute("commitment.execute", cmt["id"], actor_role="pm")
        line = c.commitments.get(cmt["id"])["sov"][0]["id"]
        bill = c.bills.certify(commitment_id=cmt["id"], period_id="P1", installed=[{"sov_line_id": line, "cumulative_installed": "10000"}], actor="pm")
        res = approve_and_post_bill(c, bill["id"], approver="owner", approver_role="owner", poster="accountant")
        return bill["id"], c.ledger.journal(res.result["journal_id"])

    def test_subledger_journals_are_corrected_by_their_module_not_by_journal_reverse(self):
        c = self.c
        c.ledger.reverse(self.j["id"], period_id="P1", posted_by="accountant", reason="direct AP entry")  # AP holds only the bill below
        bill_id, journal = self.bill_journal()
        self.assertEqual(journal["source_type"], "bill")
        self.assertEqual((c.ledger.balance("2000"), c.ledger.balance("2050")), (Decimal("9000.00"), Decimal("1000.00")))
        with self.assertRaisesRegex(SubledgerOwnedJournal, "kept by the bills subledger"):
            c.ledger.prepare_reversal(journal["id"], "late correction", "accountant")
        # a request written around prepare_reversal does not open the governed path either
        c.db.execute("INSERT INTO journal_reversal_requests (id, journal_id, reason, status, requested_by, requested_at) VALUES ('jrr_raw_bill', ?, 'raw', 'pending', 'raw', 't')",
                     (journal["id"],))
        for role in ("accountant", "controller", "owner"):
            with self.subTest(role=role), self.assertRaises(SubledgerOwnedJournal):
                c.request_approval("journal.reverse", journal["id"], actor_role=role, requested_by=role)
        with self.assertRaises(SubledgerOwnedJournal):  # and apply refuses on its own
            c.ledger.apply("journal.reverse", journal["id"], approval_id="apr_none", actor="accountant", period_id="P3",
                           manifest={"bindings": {"reversal_request": {"id": "jrr_raw_bill"}, "reason": "raw"}})
        self.assertEqual(self.reverse_approvals(), [])
        self.assertIsNone(c.ledger.journal(journal["id"])["reversed_by"])
        self.assertEqual(c.bills.get(bill_id)["status"], "posted")
        ap = c.bills.ap_open_items()
        self.assertTrue(ap["reconciled"], ap)
        self.assertEqual((c.ledger.balance("2000"), c.ledger.balance("2050")), (Decimal("9000.00"), Decimal("1000.00")))
        self.assertTrue(c.ledger.trial_balance()["balanced"])
        self.assertTrue(c.audit.verify_chain()["ok"])
        # the refusal names every subledger-owned source the generic path leaves to its module
        self.assertTrue({"bill", "retainage_release", "payment_intent", "provider_event"} <= set(c.ledger.reversal_owners))


if __name__ == "__main__":
    unittest.main()

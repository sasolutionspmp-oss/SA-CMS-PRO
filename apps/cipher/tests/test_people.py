"""Identity and authority registry (people): identities, role grants, delegations, project
membership, hash-chained identity policy versions, and the governor that makes every approval
answer to them once a policy enforces.

All identities, projects and amounts are synthetic."""
import datetime as _dt
import json
import sqlite3
import unittest

from apps.cipher.service import Cipher, RoleNotAuthorized, run_golden_fixture  # load the service (and its plugins) first
from apps.cipher.core.approvals import ApprovalNotGranted, StaleApprovalError
from apps.cipher.domain.people import (
    EXPIRY_WARNING_DAYS, OP_DELEGATE, OP_GRANT, OP_POLICY, OP_REVOKE, PLUGIN_NAME, SCHEMA_NAME, IdentityIntegrityError, IdentityRefused,
    PeopleError, PeopleIneligible, normalize_login,
)

ENTITY = "S&A Solutions LLC (synthetic)"
TODAY = _dt.date(2026, 10, 12)


def clock(day: str | _dt.date):
    d = _dt.date.fromisoformat(day) if isinstance(day, str) else day
    return lambda: _dt.datetime(d.year, d.month, d.day, 12, 0, tzinfo=_dt.timezone.utc)


class World:
    """An empty registry over two synthetic projects (a cofferdam and a sheet pile wall) and
    open period P1; the registry clock is fixed at 2026-10-12."""

    def __init__(self):
        c = self.c = Cipher()
        self.p = c.plugin(PLUGIN_NAME)
        self.p.now = clock(TODAY)
        sup = c.add_party(kind="supplier", name="Synthetic sheet pile subcontractor", destination="ACH-SIM-PPL-0001")
        self.supplier = c.verify_destination(sup["id"], destination="ACH-SIM-PPL-0001", verified_by="owner")
        self.a = c.create_project(name="Synthetic cofferdam and dewatering", entity=ENTITY, budget="250000")["id"]
        self.b = c.create_project(name="Synthetic sheet pile wall", entity=ENTITY, budget="100000")["id"]
        c.open_period("P1", "P1", "2026-10-01", "2026-10-31")

    def commitment(self, project_id=None) -> str:
        return self.c.commitments.create(project_id=project_id or self.a, supplier_id=self.supplier["id"], title="Synthetic sheet pile subcontract",
                                         sov_lines=[{"description": "Sheet piling and walers", "amount": "1000"}], actor="pm")["id"]

    def run(self, operation, subject, *, requester, approver, executor=None, actor_role="owner", approver_role="owner"):
        ap = self.c.request_approval(operation, subject, actor_role=actor_role, requested_by=requester)
        self.c.approve(ap["id"], approver=approver, approver_role=approver_role)
        return self.c.execute(ap["id"], actor=executor or approver)

    def grant(self, login, role, *, by="travis", approver="travis", executor=None, **kw):
        req = self.p.request_grant(login, role, reason="synthetic staffing", actor=by, **kw)
        return self.run(OP_GRANT, req["id"], requester=by, approver=approver, executor=executor).result

    def policy(self, *, by="travis", approver="travis", executor=None, **rules):
        draft = self.p.prepare_policy(reason="synthetic identity policy", actor=by, **rules)
        return self.run(OP_POLICY, draft["id"], requester=by, approver=approver, executor=executor).result

    def team(self, *, enforce=True, segregate=True, solo=False):
        """travis (owner), pm.lee (pm on project A, a member), pm.ana (pm, entity), ctrl.kim
        (controller), ext.acct (outside party, accountant) and pay-worker (service, treasury)."""
        p = self.p
        p.bootstrap_owner("travis", "Synthetic owner")
        for login, name in (("pm.lee", "Synthetic PM Lee"), ("pm.ana", "Synthetic PM Ana"), ("ctrl.kim", "Synthetic controller")):
            p.register_person(login, name, actor="travis")
        p.register_person("ext.acct", "Synthetic external accountant", actor="travis", external=True)
        p.register_person("pay-worker", "Synthetic payment worker", actor="travis", kind="service")
        p.add_membership("pm.lee", self.a, actor="travis")
        self.grant("pm.lee", "pm", project_id=self.a)
        self.grant("pm.ana", "pm")
        self.grant("ctrl.kim", "controller")
        self.grant("ext.acct", "accountant")
        self.grant("pay-worker", "treasury")
        if enforce:
            self.policy(enforce=True, segregate=segregate, solo_owner_self_approval=solo)
        return self

    def check(self, name):
        return next(k for k in self.p.close_checks("P1") if k["check"] == name)


def _grant_insert(c, *, seq, prev_hash, request_id, person_id, login, role="controller", origin="approval", approval_id=None):
    c.db.execute(
        "INSERT INTO people_grants (id, seq, request_id, person_id, login, role, scope, project_id, effective_from, effective_to, origin, approval_id, "
        "granted_by, created_at, prev_hash, content_hash) VALUES (?, ?, ?, ?, ?, ?, 'entity', NULL, '2026-01-01', NULL, ?, ?, 'travis', 't', ?, ?)",
        (f"pgr_forged_{seq}_{role}", seq, request_id, person_id, login, role, origin, approval_id, prev_hash, f"forged-{seq}-{role}-{origin}"))


# --------------------------------------------------------------------------- #
# 1. no policy recorded: nothing changes                                       #
# --------------------------------------------------------------------------- #

class NoPolicyTests(unittest.TestCase):
    def test_plugin_is_a_registered_governor_with_its_schema(self):
        c = Cipher()
        p = c.plugin(PLUGIN_NAME)
        self.assertIs(p.GOVERNOR, True)
        self.assertIn(("people", p), c._governors())
        self.assertIn(SCHEMA_NAME, {r["name"] for r in c.db.query("SELECT name FROM schema_version")})
        self.assertFalse(p.enforcing())
        self.assertIsNone(p.current_policy())
        self.assertIsNone(p.approval_policy("commitment.execute", {}))
        for op in (OP_GRANT, OP_REVOKE, OP_DELEGATE, OP_POLICY):
            self.assertEqual(op.split(".")[0], PLUGIN_NAME)

    def test_without_a_policy_existing_flows_are_unchanged(self):
        c = Cipher()
        r = run_golden_fixture(c)
        self.assertEqual(r["executed_amount"], "122000.00")
        self.assertEqual(r["bill1"]["amount_due"], "27000.00")
        self.assertEqual(r["payment"]["transfers"], 1)
        self.assertIn(r["stale_result"], ("ApprovalNotGranted", "StaleApprovalError"))
        self.assertEqual(r["ap_bill3_status"], "invalidated")
        for ap in c.approvals.list():
            self.assertNotIn(PLUGIN_NAME, ap["manifest"].get("governance") or {})
        for table in ("people_persons", "people_grants", "people_policy_versions", "people_self_approvals"):
            self.assertEqual(c.db.scalar(f"SELECT COUNT(*) FROM {table}"), 0)
        checks = c.plugin(PLUGIN_NAME).close_checks("2026-11")
        self.assertTrue(all(k["ok"] for k in checks), checks)
        self.assertTrue(all({"check", "name", "ok", "detail"} <= set(k) for k in checks))

    def test_registry_records_without_an_enforcing_policy_change_nothing(self):
        w = World().team(enforce=False)
        w.policy(enforce=False, segregate=True)  # recorded, but not enforcing
        self.assertEqual(w.p.current_policy()["version"], 1)
        self.assertFalse(w.p.enforcing())
        cmt = w.commitment(w.b)
        # callers still name their roles: an unregistered approver claiming owner is believed
        ap = w.c.request_approval("commitment.execute", cmt, actor_role="pm", requested_by="someone")
        self.assertNotIn("governance", ap["manifest"])
        w.c.approve(ap["id"], approver="someone", approver_role="owner")
        self.assertEqual(w.c.execute(ap["id"], actor="someone else").result["status"], "executed")
        self.assertEqual(w.c.db.scalar("SELECT COUNT(*) FROM people_self_approvals"), 0)

    def test_enforcement_off_is_an_informational_close_check(self):
        w = World()
        status = w.check("people identity enforcement (informational)")
        self.assertTrue(status["ok"])
        self.assertIn("enforcement is off", status["detail"])
        self.assertEqual(status["name"], status["check"])


# --------------------------------------------------------------------------- #
# 2. identities                                                                #
# --------------------------------------------------------------------------- #

class IdentityTests(unittest.TestCase):
    def test_logins_are_normalized_unique_and_validated(self):
        w = World()
        p = w.p
        self.assertEqual(normalize_login("  Lee.Park@SA "), "lee.park@sa")
        person = p.register_person("  Lee.Park@SA ", "Synthetic PM", actor="setup")
        self.assertEqual(person["login"], "lee.park@sa")
        self.assertTrue(p.is_active("LEE.PARK@sa"))
        with self.assertRaisesRegex(PeopleError, "already registered"):
            p.register_person("lee.park@SA", "Duplicate", actor="setup")
        for bad in ("", "   ", "-lead", "has space", "semi;colon", "x" * 65, None, 7):
            with self.subTest(login=bad), self.assertRaises(PeopleError):
                p.register_person(bad, "Bad", actor="setup")
        with self.assertRaisesRegex(PeopleError, "display name"):
            p.register_person("nameless", "  ", actor="setup")
        with self.assertRaisesRegex(PeopleError, "kind"):
            p.register_person("robot", "Robot", actor="setup", kind="robot")

    def test_service_identities_and_outside_parties(self):
        w = World()
        p = w.p
        with self.assertRaisesRegex(PeopleError, "never an outside party"):
            p.register_person("ricky", "Ricky", actor="setup", kind="service", external=True)
        p.register_person("ricky", "Ricky (assistant)", actor="setup", kind="service")
        p.register_person("ext.acct", "Synthetic external accountant", actor="setup", external=True)
        self.assertTrue(p.is_external("ext.acct"))
        self.assertFalse(p.is_external("ricky"))
        self.assertFalse(p.is_external("nobody"))
        info = p.person_for("RICKY")
        self.assertEqual((info["kind"], info["external"], info["status"], info["authorities"]), ("service", False, "active", []))
        self.assertIsNone(p.person_for("nobody"))
        self.assertIsNone(p.person_for(None))

    def test_deactivation_is_immediate_audited_and_final(self):
        w = World().team(enforce=False)
        p = w.p
        self.assertTrue(p.holds("pm.ana", "pm"))
        out = p.deactivate_person("pm.ana", reason="left the company (synthetic)", actor="travis")
        self.assertEqual(out["status"], "inactive")
        self.assertFalse(p.is_active("pm.ana"))
        self.assertFalse(p.holds("pm.ana", "pm"))
        self.assertEqual(out["authorities"], [])
        entry = w.c.db.one("SELECT * FROM audit_log WHERE action='people.person_deactivated' AND entity_id=?", (out["id"],))
        self.assertEqual(json.loads(entry["payload_json"])["reason"], "left the company (synthetic)")
        with self.assertRaisesRegex(PeopleError, "already inactive"):
            p.deactivate_person("pm.ana", reason="again", actor="travis")
        with self.assertRaisesRegex(sqlite3.DatabaseError, "deactivated identity is final"):
            w.c.db.execute("UPDATE people_persons SET status='active', deactivated_by=NULL, deactivated_at=NULL, deactivation_reason=NULL WHERE login='pm.ana'")
        with self.assertRaisesRegex(PeopleError, "already registered"):  # a returning person gets a new login
            p.register_person("pm.ana", "Synthetic PM Ana", actor="travis")

    def test_raw_sql_cannot_forge_or_rewrite_identities(self):
        w = World().team(enforce=False)
        c = w.c
        probes = [
            ("register without the registry", "INSERT INTO people_persons (id, login, display_name, kind, external, status, content_hash, created_by, created_at) "
                                              "VALUES ('psn_forged', 'mallory', 'Mallory', 'person', 1, 'active', 'x', 'mallory', 't')"),
            ("replace an identity", "INSERT OR REPLACE INTO people_persons (id, login, display_name, kind, external, status, content_hash, created_by, created_at) "
                                    "SELECT id, login, display_name, kind, 1, status, content_hash, created_by, created_at FROM people_persons WHERE login='pm.lee'"),
            ("turn a service into a person", "UPDATE people_persons SET kind='person' WHERE login='pay-worker'"),
            ("make an outside party internal", "UPDATE people_persons SET external=0 WHERE login='ext.acct'"),
            ("deactivate without the registry", "UPDATE people_persons SET status='inactive', deactivated_by='x', deactivated_at='t', deactivation_reason='x' WHERE login='pm.lee'"),
            ("delete an identity", "DELETE FROM people_persons WHERE login='pm.lee'"),
        ]
        for label, sql in probes:
            with self.subTest(probe=label), self.assertRaises(sqlite3.DatabaseError):
                c.db.execute(sql)
        self.assertEqual(c.db.scalar("SELECT COUNT(*) FROM people_persons"), 6)
        self.assertTrue(w.p.is_active("pm.lee"))
        self.assertEqual(w.p.integrity_problems(), [])


# --------------------------------------------------------------------------- #
# 3. owner bootstrap                                                           #
# --------------------------------------------------------------------------- #

class BootstrapTests(unittest.TestCase):
    def test_bootstrap_owner_exactly_once(self):
        w = World()
        p = w.p
        out = p.bootstrap_owner("Travis", "Synthetic owner")
        self.assertEqual((out["grant"]["role"], out["grant"]["origin"], out["grant"]["seq"], out["grant"]["effective_to"]), ("owner", "bootstrap", 1, None))
        self.assertTrue(p.holds("travis", "owner"))
        self.assertTrue(p.holds("travis", "treasury"))  # the owner role carries every role
        self.assertTrue(p.holds("travis", "pm", project_id=w.b))
        with self.assertRaisesRegex(PeopleError, "already bootstrapped"):
            p.bootstrap_owner("someone", "Someone")
        # even once the bootstrapped owner is gone, owners are granted only by approval
        p.register_person("olivia", "Synthetic second owner", actor="travis")
        w.grant("olivia", "owner")
        p.deactivate_person("travis", reason="handed over (synthetic)", actor="olivia")
        with self.assertRaisesRegex(PeopleError, "already bootstrapped"):
            p.bootstrap_owner("mallory", "Mallory")
        self.assertFalse(p.is_active("mallory"))

    def test_bootstrap_refused_while_an_owner_exists_or_enforcing(self):
        w = World()
        p = w.p
        p.register_person("olivia", "Synthetic owner", actor="setup")
        w.grant("olivia", "owner", by="setup", approver="setup")  # no enforcement yet: the caller names its role
        with self.assertRaisesRegex(PeopleError, "already holds owner"):
            p.bootstrap_owner("mallory", "Mallory")
        # enforcing, and the only owner grant has run out: still no bootstrap
        real = _dt.datetime.now(_dt.timezone.utc).date()
        w2 = World()
        w2.p.now = clock(real)
        w2.p.register_person("olivia", "Synthetic owner", actor="setup")
        w2.grant("olivia", "owner", by="setup", approver="setup", effective_to=(real + _dt.timedelta(days=30)).isoformat())
        w2.policy(enforce=True, segregate=False, by="setup", approver="setup")
        w2.p.now = clock(real + _dt.timedelta(days=31))
        self.assertEqual(w2.p._active_owners(), [])
        with self.assertRaisesRegex(PeopleError, "enforcement is on"):
            w2.p.bootstrap_owner("mallory", "Mallory")
        # the owner is an internal person
        w3 = World()
        w3.p.register_person("ext.acct", "Synthetic external accountant", actor="setup", external=True)
        with self.assertRaisesRegex(PeopleError, "internal person"):
            w3.p.bootstrap_owner("ext.acct")
        self.assertFalse(w3.p.holds("ext.acct", "owner"))

    def test_raw_sql_cannot_bootstrap_a_second_owner(self):
        w = World().team(enforce=False)
        c = w.c
        head = c.db.one("SELECT seq, content_hash FROM people_grants ORDER BY seq DESC LIMIT 1")
        lee = w.p.person_for("pm.lee")
        with self.assertRaisesRegex(sqlite3.DatabaseError, "bootstrapped exactly once"):
            _grant_insert(c, seq=head["seq"] + 1, prev_hash=head["content_hash"], request_id=None, person_id=lee["id"], login="pm.lee",
                          role="owner", origin="bootstrap")
        self.assertFalse(w.p.holds("pm.lee", "owner"))


# --------------------------------------------------------------------------- #
# 4. role grants                                                               #
# --------------------------------------------------------------------------- #

class GrantTests(unittest.TestCase):
    def test_a_grant_is_recorded_by_its_approval_and_hash_chained(self):
        w = World()
        p, c = w.p, w.c
        p.bootstrap_owner("travis", "Synthetic owner")
        p.register_person("ctrl.kim", "Synthetic controller", actor="travis")
        req = p.request_grant("ctrl.kim", "controller", reason="month-end close (synthetic)", actor="travis", effective_to="2027-12-31")
        self.assertEqual(req["status"], "pending")
        self.assertFalse(p.holds("ctrl.kim", "controller"))
        ap = c.request_approval(OP_GRANT, req["id"], actor_role="owner", requested_by="travis")
        b = ap["manifest"]["bindings"]
        self.assertEqual((b["subject_login"], b["role"], b["scope"], b["effective_to"]), ("ctrl.kim", "controller", "entity", "2027-12-31"))
        self.assertIn("close.close_period", b["role_authority"])
        with self.assertRaises(RoleNotAuthorized):
            c.request_approval(OP_GRANT, req["id"], actor_role="pm", requested_by="travis")  # only the owner role holds people.*
        c.approve(ap["id"], approver="travis")
        res = c.execute(ap["id"], actor="travis").result
        self.assertEqual((res["login"], res["role"], res["seq"]), ("ctrl.kim", "controller", 2))
        self.assertTrue(p.holds("ctrl.kim", "controller"))
        self.assertFalse(p.holds("ctrl.kim", "treasury"))
        grants = p.grants()
        self.assertEqual(grants[1]["prev_hash"], grants[0]["content_hash"])
        self.assertEqual(grants[1]["approval_id"], ap["id"])
        self.assertEqual(c.db.one("SELECT * FROM people_grant_requests WHERE id=?", (req["id"],))["status"], "granted")
        self.assertEqual(p.integrity_problems(), [])
        with self.assertRaises(StaleApprovalError):  # an approval takes effect once: the request is no longer pending
            c.execute(ap["id"], actor="travis", op_id="replay-with-new-id")
        self.assertEqual(c.approvals.get(ap["id"])["status"], "consumed")
        self.assertEqual(len(p.grants("ctrl.kim")), 1)

    def test_no_self_granting_even_by_the_owner(self):
        w = World()
        p, c = w.p, w.c
        p.bootstrap_owner("travis", "Synthetic owner")
        p.register_person("pm.lee", "Synthetic PM Lee", actor="travis")
        with self.assertRaisesRegex(IdentityRefused, "no self-granting"):
            p.request_grant("travis", "controller", reason="me", actor="Travis")
        with self.assertRaisesRegex(IdentityRefused, "no self-granting"):
            p.request_grant("pm.lee", "pm", reason="me", actor="pm.lee")
        req = p.request_grant("pm.lee", "pm", reason="project staffing", actor="travis")
        with self.assertRaisesRegex(IdentityRefused, "no self-granting"):
            c.request_approval(OP_GRANT, req["id"], actor_role="owner", requested_by="PM.Lee")
        ap = c.request_approval(OP_GRANT, req["id"], actor_role="owner", requested_by="travis")
        with self.assertRaisesRegex(IdentityRefused, "no self-granting"):
            c.approve(ap["id"], approver="pm.lee", approver_role="owner")
        self.assertEqual(c.approvals.get(ap["id"])["status"], "pending")
        c.approve(ap["id"], approver="travis")
        with self.assertRaisesRegex(IdentityRefused, "no self-granting"):
            c.execute(ap["id"], actor="pm.lee")
        self.assertEqual(c.approvals.get(ap["id"])["status"], "granted")
        self.assertFalse(p.holds("pm.lee", "pm"))
        c.execute(ap["id"], actor="travis")
        self.assertTrue(p.holds("pm.lee", "pm"))

    def test_grant_rules(self):
        w = World()
        p = w.p
        p.bootstrap_owner("travis", "Synthetic owner")
        p.register_person("pm.lee", "Synthetic PM Lee", actor="travis")
        p.register_person("ext.acct", "Synthetic external accountant", actor="travis", external=True)
        p.register_person("pay-worker", "Synthetic payment worker", actor="travis", kind="service")
        with self.assertRaisesRegex(PeopleError, "not a Cipher role"):
            p.request_grant("pm.lee", "superuser", reason="x", actor="travis")
        with self.assertRaisesRegex(PeopleError, "entity scope only"):
            p.request_grant("pm.lee", "owner", reason="x", actor="travis", project_id=w.a)
        for login in ("ext.acct", "pay-worker"):
            with self.subTest(owner_for=login), self.assertRaisesRegex(PeopleError, "only by an internal person"):
                p.request_grant(login, "owner", reason="x", actor="travis")
        with self.assertRaisesRegex(PeopleError, "not a member of project"):
            p.request_grant("pm.lee", "pm", reason="x", actor="travis", project_id=w.a)
        with self.assertRaisesRegex(PeopleError, "before today"):
            p.request_grant("pm.lee", "pm", reason="x", actor="travis", effective_from="2026-01-01", effective_to="2026-06-30")
        with self.assertRaisesRegex(PeopleError, "before it starts"):
            p.request_grant("pm.lee", "pm", reason="x", actor="travis", effective_from="2026-12-01", effective_to="2026-11-01")
        with self.assertRaisesRegex(PeopleError, "YYYY-MM-DD"):
            p.request_grant("pm.lee", "pm", reason="x", actor="travis", effective_to="31/12/2026")
        req = p.request_grant("pm.lee", "pm", reason="staffing", actor="travis", effective_to="2026-12-31")
        with self.assertRaisesRegex(PeopleError, "already pending"):
            p.request_grant("pm.lee", "pm", reason="again", actor="travis")
        w.run(OP_GRANT, req["id"], requester="travis", approver="travis")
        with self.assertRaisesRegex(PeopleError, "never overlap"):
            p.request_grant("pm.lee", "pm", reason="overlap", actor="travis", effective_from="2026-12-01")
        later = p.request_grant("pm.lee", "pm", reason="renewal", actor="travis", effective_from="2027-01-01")  # the next window is fine
        self.assertEqual(later["effective_from"], "2027-01-01")
        with self.assertRaisesRegex(PeopleError, "unknown identity"):
            p.request_grant("nobody", "pm", reason="x", actor="travis")

    def test_a_project_scoped_grant_counts_only_on_its_project_while_a_member(self):
        w = World()
        p = w.p
        p.bootstrap_owner("travis", "Synthetic owner")
        p.register_person("pm.lee", "Synthetic PM Lee", actor="travis")
        p.add_membership("pm.lee", w.a, actor="travis")
        with self.assertRaisesRegex(PeopleError, "already a member"):
            p.add_membership("pm.lee", w.a, actor="travis")
        w.grant("pm.lee", "pm", project_id=w.a)
        self.assertTrue(p.holds("pm.lee", "pm", project_id=w.a))
        self.assertFalse(p.holds("pm.lee", "pm", project_id=w.b))
        self.assertFalse(p.holds("pm.lee", "pm"))  # entity scope needs an entity grant
        p.end_membership("pm.lee", w.a, reason="moved to another job (synthetic)", actor="travis")
        self.assertFalse(p.holds("pm.lee", "pm", project_id=w.a))
        self.assertEqual(p.authorities("pm.lee"), [])
        p.add_membership("pm.lee", w.a, actor="travis")
        self.assertTrue(p.holds("pm.lee", "pm", project_id=w.a))
        self.assertEqual(len(p.memberships(w.a)), 2)

    def test_grant_windows_follow_the_injectable_clock(self):
        w = World()
        p = w.p
        p.bootstrap_owner("travis", "Synthetic owner")
        p.register_person("acct.ray", "Synthetic accountant", actor="travis")
        w.grant("acct.ray", "accountant", effective_from="2026-11-01", effective_to="2026-11-30")
        self.assertFalse(p.holds("acct.ray", "accountant"))
        p.now = clock("2026-11-01")
        self.assertTrue(p.holds("acct.ray", "accountant"))
        p.now = clock("2026-11-30")
        self.assertTrue(p.holds("acct.ray", "accountant"))  # end dates are inclusive
        p.now = clock("2026-12-01")
        self.assertFalse(p.holds("acct.ray", "accountant"))
        self.assertFalse(p.grants("acct.ray")[0]["effective_today"])

    def test_revocation_is_approval_bound_and_final(self):
        w = World().team(enforce=False)
        p, c = w.p, w.c
        grant = next(g for g in p.grants("ctrl.kim") if g["role"] == "controller")
        with self.assertRaisesRegex(IdentityRefused, "their own grant"):
            p.request_revocation(grant["id"], reason="me", actor="ctrl.kim")
        rev = p.request_revocation(grant["id"], reason="role change (synthetic)", actor="travis")
        with self.assertRaisesRegex(PeopleError, "already pending"):
            p.request_revocation(grant["id"], reason="again", actor="travis")
        self.assertTrue(p.holds("ctrl.kim", "controller"))  # nothing changes until the approval executes
        ap = c.request_approval(OP_REVOKE, rev["id"], actor_role="owner", requested_by="travis")
        self.assertEqual(ap["manifest"]["bindings"]["subject_login"], "ctrl.kim")
        with self.assertRaisesRegex(IdentityRefused, "no self-granting"):
            c.approve(ap["id"], approver="ctrl.kim", approver_role="owner")
        c.approve(ap["id"], approver="travis")
        res = c.execute(ap["id"], actor="travis").result
        self.assertEqual(res["grant"], grant["id"])
        self.assertFalse(p.holds("ctrl.kim", "controller"))
        with self.assertRaisesRegex(PeopleError, "already revoked"):
            p.request_revocation(grant["id"], reason="again", actor="travis")
        with self.assertRaisesRegex(sqlite3.DatabaseError, "revoked role grant is final"):
            c.db.execute("UPDATE people_grants SET revoked_at=NULL, revoked_by=NULL WHERE id=?", (grant["id"],))
        self.assertEqual(p.integrity_problems(), [])

    def test_canceling_a_request_invalidates_its_open_approvals(self):
        w = World().team(enforce=False)
        p, c = w.p, w.c
        p.register_person("acct.ray", "Synthetic accountant", actor="travis")
        req = p.request_grant("acct.ray", "accountant", reason="staffing", actor="travis")
        ap = c.request_approval(OP_GRANT, req["id"], actor_role="owner", requested_by="travis")
        out = p.cancel_request(req["id"], reason="hired elsewhere (synthetic)", actor="travis")
        self.assertEqual(out["status"], "cancelled")
        self.assertEqual(c.approvals.get(ap["id"])["status"], "invalidated")
        with self.assertRaisesRegex(PeopleError, "not pending"):
            p.cancel_request(req["id"], reason="again", actor="travis")
        with self.assertRaises(PeopleIneligible):
            c.request_approval(OP_GRANT, req["id"], actor_role="owner", requested_by="travis")
        with self.assertRaisesRegex(PeopleError, "unknown request"):
            p.cancel_request("nope", reason="x", actor="travis")


# --------------------------------------------------------------------------- #
# 5. raw SQL against the grant table                                           #
# --------------------------------------------------------------------------- #

class GrantTamperingTests(unittest.TestCase):
    def test_raw_sql_cannot_forge_rewrite_replace_or_delete_grants(self):
        w = World().team(enforce=False)
        c, p = w.c, w.p
        head = c.db.one("SELECT seq, content_hash FROM people_grants ORDER BY seq DESC LIMIT 1")
        lee = p.person_for("pm.lee")
        req = p.request_grant("pm.lee", "controller", reason="pending, never approved", actor="travis")
        unrelated = c.approvals.list(status="consumed")[0]["id"]  # a consumed approval of another request
        with self.assertRaisesRegex(sqlite3.DatabaseError, "consumed people.grant_role approval"):
            _grant_insert(c, seq=head["seq"] + 1, prev_hash=head["content_hash"], request_id=req["id"], person_id=lee["id"], login="pm.lee",
                          approval_id=unrelated)
        with self.assertRaisesRegex(sqlite3.DatabaseError, "extends the chain at its head"):
            _grant_insert(c, seq=1, prev_hash="0" * 64, request_id=req["id"], person_id=lee["id"], login="pm.lee", approval_id=unrelated)
        kim = next(g for g in p.grants("ctrl.kim") if g["role"] == "controller")
        probes = [
            ("raise the role", "UPDATE people_grants SET role='owner' WHERE id=?"),
            ("extend the window", "UPDATE people_grants SET effective_to='2099-12-31' WHERE id=?"),
            ("move the grantee", f"UPDATE people_grants SET person_id='{lee['id']}', login='pm.lee' WHERE id=?"),
            ("revoke without an approval", "UPDATE people_grants SET revoked_at='t', revoked_by='mallory' WHERE id=?"),
            ("delete a grant", "DELETE FROM people_grants WHERE id=?"),
            ("replace a grant", "INSERT OR REPLACE INTO people_grants SELECT * FROM people_grants WHERE id=?"),
            ("mark its request canceled behind the registry", "UPDATE people_grant_requests SET status='cancelled', resolved_by='x', resolved_at='t' "
                                                               "WHERE grant_id=?"),
        ]
        for label, sql in probes:
            with self.subTest(probe=label), self.assertRaises(sqlite3.DatabaseError):
                c.db.execute(sql, (kim["id"],))
        self.assertFalse(p.holds("pm.lee", "controller"))
        self.assertEqual(p.grants("ctrl.kim")[0]["role"], "controller")
        self.assertEqual(p.integrity_problems(), [])
        self.assertTrue(w.check("people identity records intact")["ok"])

    def test_tampering_past_the_triggers_is_detected_and_enforcement_fails_closed(self):
        w = World().team()
        c, p = w.c, w.p
        cmt = w.commitment()
        c.db.execute("DROP TRIGGER people_grants_update_guard")
        c.db.execute("UPDATE people_grants SET role='controller' WHERE login='pm.lee'")  # quietly widen pm.lee
        problems = p.integrity_problems()
        self.assertTrue(any("does not hash to its recorded content hash" in x for x in problems), problems)
        intact = w.check("people identity records intact")
        self.assertFalse(intact["ok"])
        self.assertIn("pm.lee", intact["detail"])
        with self.assertRaisesRegex(IdentityIntegrityError, "fail closed"):
            c.request_approval("commitment.execute", cmt, actor_role="owner", requested_by="travis")
        with self.assertRaises(IdentityIntegrityError):
            p.register_person("someone", "Someone", actor="travis")
        brief = c.ricky.brief(w.a)
        self.assertTrue(any(it["kind"] == "close_check" and "identity records intact" in it["text"] for it in brief["items"]))


# --------------------------------------------------------------------------- #
# 6. delegations                                                               #
# --------------------------------------------------------------------------- #

class DelegationTests(unittest.TestCase):
    def delegate(self, w, frm, to, role, *, by="travis", approver="travis", **kw):
        d = w.p.request_delegation(frm, to, role, reason="leave cover (synthetic)", actor=by, **kw)
        return d, w.run(OP_DELEGATE, d["id"], requester=by, approver=approver).result

    def test_a_delegation_counts_for_its_window_only(self):
        w = World().team(enforce=False)
        p = w.p
        self.assertFalse(p.holds("ctrl.kim", "pm"))
        d, res = self.delegate(w, "pm.ana", "ctrl.kim", "pm", effective_from="2026-10-15", effective_to="2026-10-20")
        self.assertEqual(res["status"], "active")
        self.assertFalse(p.holds("ctrl.kim", "pm"))  # not yet
        p.now = clock("2026-10-15")
        self.assertTrue(p.holds("ctrl.kim", "pm"))
        self.assertTrue(p.holds("ctrl.kim", "pm", project_id=w.b))  # entity scope covers every project
        self.assertEqual([a["via"] for a in p.authorities("ctrl.kim") if a["role"] == "pm"], ["delegation"])
        p.now = clock("2026-10-21")
        self.assertFalse(p.holds("ctrl.kim", "pm"))
        self.assertEqual(p.integrity_problems(), [])

    def test_owner_role_service_delegates_and_re_delegation_are_refused(self):
        w = World().team(enforce=False)
        p = w.p
        with self.assertRaisesRegex(PeopleError, "never delegated"):
            p.request_delegation("travis", "pm.ana", "owner", effective_to="2026-10-30", reason="x", actor="travis")
        with self.assertRaisesRegex(PeopleError, "service identity"):
            p.request_delegation("pm.ana", "pay-worker", "pm", effective_to="2026-10-30", reason="x", actor="travis")
        with self.assertRaisesRegex(IdentityRefused, "no self-granting"):
            p.request_delegation("pm.ana", "ctrl.kim", "pm", effective_to="2026-10-30", reason="x", actor="ctrl.kim")
        with self.assertRaisesRegex(PeopleError, "does not hold pm by their own grant"):
            p.request_delegation("ctrl.kim", "ext.acct", "pm", effective_to="2026-10-30", reason="x", actor="travis")
        self.delegate(w, "pm.ana", "ctrl.kim", "pm", effective_to="2026-10-30")
        self.assertTrue(p.holds("ctrl.kim", "pm"))
        with self.assertRaisesRegex(PeopleError, "never delegated again"):
            p.request_delegation("ctrl.kim", "ext.acct", "pm", effective_to="2026-10-30", reason="x", actor="travis")
        with self.assertRaisesRegex(PeopleError, "end date|YYYY-MM-DD"):
            p.request_delegation("pm.ana", "ext.acct", "pm", effective_to=None, reason="x", actor="travis")
        with self.assertRaisesRegex(PeopleError, "overlapping window"):
            p.request_delegation("travis", "ctrl.kim", "pm", effective_to="2026-10-25", reason="x", actor="pm.ana")
        with self.assertRaisesRegex(PeopleError, "already holds controller"):
            p.request_delegation("travis", "ctrl.kim", "controller", effective_to="2026-10-25", reason="x", actor="pm.ana")
        with self.assertRaises(sqlite3.DatabaseError):
            w.c.db.execute("UPDATE people_delegations SET role='owner'")
        self.assertEqual(w.c.db.scalar("SELECT COUNT(*) FROM people_delegations WHERE role='owner'"), 0)

    def test_a_delegation_lapses_when_the_delegator_loses_the_role(self):
        w = World().team(enforce=False)
        p = w.p
        self.delegate(w, "pm.ana", "ctrl.kim", "pm", effective_to="2026-10-30")
        self.assertTrue(p.holds("ctrl.kim", "pm"))
        p.deactivate_person("pm.ana", reason="left (synthetic)", actor="travis")
        self.assertFalse(p.holds("ctrl.kim", "pm"))

    def test_revoking_a_delegation_is_immediate_and_a_delegate_never_approves_it(self):
        w = World().team(enforce=False)
        p, c = w.p, w.c
        d = p.request_delegation("pm.ana", "ctrl.kim", "pm", effective_to="2026-10-30", reason="cover", actor="pm.ana")
        ap = c.request_approval(OP_DELEGATE, d["id"], actor_role="owner", requested_by="pm.ana")
        with self.assertRaisesRegex(IdentityRefused, "no self-granting"):
            c.approve(ap["id"], approver="ctrl.kim", approver_role="owner")
        c.approve(ap["id"], approver="travis")
        c.execute(ap["id"], actor="travis")
        self.assertTrue(p.holds("ctrl.kim", "pm"))
        p.revoke_delegation(d["id"], reason="back from leave (synthetic)", actor="pm.ana")
        self.assertFalse(p.holds("ctrl.kim", "pm"))
        with self.assertRaisesRegex(PeopleError, "not active"):
            p.revoke_delegation(d["id"], reason="again", actor="pm.ana")
        with self.assertRaisesRegex(sqlite3.DatabaseError, "final"):
            c.db.execute("UPDATE people_delegations SET status='active' WHERE id=?", (d["id"],))


# --------------------------------------------------------------------------- #
# 7. identity policy versions                                                  #
# --------------------------------------------------------------------------- #

class PolicyTests(unittest.TestCase):
    def test_policy_versions_are_hash_chained_and_append_only(self):
        w = World().team(enforce=False)
        p = w.p
        w.policy(enforce=False, segregate=True)
        w.policy(enforce=True, segregate=True)
        versions = p.policy_versions()
        self.assertEqual([v["version"] for v in versions], [1, 2])
        self.assertEqual(versions[0]["prev_hash"], "0" * 64)
        self.assertEqual(versions[1]["prev_hash"], versions[0]["content_hash"])
        current = p.current_policy()
        self.assertEqual((current["version"], current["enforce"], current["segregate"], current["intact"]), (2, True, True, True))
        self.assertTrue(p.enforcing())
        with self.assertRaisesRegex(PeopleError, "already has these rules"):
            p.prepare_policy(enforce=True, segregate=True, reason="same", actor="travis")
        with self.assertRaisesRegex(PeopleError, "needs segregate"):
            p.prepare_policy(enforce=True, segregate=False, solo_owner_self_approval=True, reason="x", actor="travis")
        with self.assertRaisesRegex(PeopleError, "true or false"):
            p.prepare_policy(enforce="yes", reason="x", actor="travis")

    def test_enabling_enforcement_needs_an_owner_and_another_active_person(self):
        w = World()
        p, c = w.p, w.c
        p.register_person("travis", "Synthetic owner (not yet granted)", actor="setup")
        draft = p.prepare_policy(enforce=True, segregate=False, reason="x", actor="travis")
        with self.assertRaisesRegex(PeopleIneligible, "at least one active owner"):
            c.request_approval(OP_POLICY, draft["id"], actor_role="owner", requested_by="travis")
        w2 = World()
        w2.p.bootstrap_owner("travis", "Synthetic owner")
        seg = w2.p.prepare_policy(enforce=True, segregate=True, reason="x", actor="travis")
        with self.assertRaisesRegex(PeopleIneligible, "other than the requester"):
            w2.c.request_approval(OP_POLICY, seg["id"], actor_role="owner", requested_by="travis")
        solo = w2.p.prepare_policy(enforce=True, segregate=True, solo_owner_self_approval=True, reason="x", actor="travis")
        w2.p.register_person("pm.lee", "Synthetic PM Lee", actor="travis")
        with self.assertRaisesRegex(PeopleIneligible, "outside party"):
            w2.c.request_approval(OP_POLICY, solo["id"], actor_role="owner", requested_by="travis")
        res = w2.run(OP_POLICY, seg["id"], requester="travis", approver="travis").result  # pm.lee is the other person
        self.assertEqual(res["policy_version"], 1)
        self.assertTrue(w2.p.enforcing())
        # unsegregated enforcement needs only the owner
        w3 = World()
        w3.p.bootstrap_owner("travis", "Synthetic owner")
        self.assertEqual(w3.policy(enforce=True, segregate=False)["policy_version"], 1)

    def test_raw_sql_cannot_forge_rewrite_or_delete_policy_versions(self):
        w = World().team()
        c = w.c
        v = c.db.one("SELECT * FROM people_policy_versions ORDER BY version DESC LIMIT 1")
        draft = w.p.prepare_policy(enforce=False, reason="a draft nobody approved", actor="travis")
        consumed = c.approvals.list(status="consumed")[0]["id"]
        with self.assertRaisesRegex(sqlite3.DatabaseError, "consumed people.set_policy approval"):
            c.db.execute("INSERT INTO people_policy_versions (id, version, draft_id, rules_json, enforce, segregate, solo_owner_self_approval, approval_id, "
                         "approved_by, adopted_by, adopted_at, prev_hash, content_hash) VALUES ('ppv_forged', ?, ?, ?, 0, 1, 0, ?, 'travis', 'travis', 't', ?, 'forged')",
                         (v["version"] + 1, draft["id"], draft["rules_json"], consumed, v["content_hash"]))
        probes = [
            ("switch enforcement off", "UPDATE people_policy_versions SET enforce=0, rules_json='{\"enforce\":false,\"segregate\":true,\"solo_owner_self_approval\":false}'"),
            ("delete the policy", "DELETE FROM people_policy_versions"),
            ("replace the policy", "INSERT OR REPLACE INTO people_policy_versions SELECT * FROM people_policy_versions"),
            ("adopt a draft without its version", "UPDATE people_policy_drafts SET status='adopted', version_id='ppv_forged' WHERE status='pending'"),
        ]
        for label, sql in probes:
            with self.subTest(probe=label), self.assertRaises(sqlite3.DatabaseError):
                c.db.execute(sql)
        self.assertTrue(w.p.enforcing())
        self.assertEqual(w.p.current_policy()["version"], v["version"])
        self.assertEqual(w.p.integrity_problems(), [])

    def test_a_policy_chain_rewritten_past_its_triggers_fails_closed(self):
        w = World().team()
        c, p = w.c, w.p
        cmt = w.commitment()
        c.db.execute("DROP TRIGGER people_policy_versions_no_update")
        c.db.execute("UPDATE people_policy_versions SET enforce=0, rules_json='{\"enforce\":false,\"segregate\":true,\"solo_owner_self_approval\":false}'")
        self.assertIsNotNone(p.current_policy())
        self.assertFalse(p.current_policy()["intact"])
        self.assertTrue(p.enforcing())  # a broken chain never reads as "enforcement off"
        self.assertEqual(p.approval_policy("commitment.execute", {}), {"integrity": "identity policy records are not intact"})
        with self.assertRaises(IdentityIntegrityError):
            c.request_approval("commitment.execute", cmt, actor_role="pm", requested_by="pm.lee")
        self.assertFalse(w.check("people identity records intact")["ok"])

    def test_a_policy_change_invalidates_in_flight_approvals(self):
        w = World().team()
        c, p = w.c, w.p
        cmt1, cmt2 = w.commitment(), w.commitment()
        granted = c.request_approval("commitment.execute", cmt1, actor_role="pm", requested_by="pm.lee")
        self.assertEqual(granted["manifest"]["governance"][PLUGIN_NAME]["policy_version"], 1)
        c.approve(granted["id"], approver="pm.ana", approver_role="pm")
        pending = c.request_approval("commitment.execute", cmt2, actor_role="pm", requested_by="pm.lee")
        # version 2: requested by the controller, approved and executed by the owner (segregated)
        res = w.policy(enforce=True, segregate=True, solo_owner_self_approval=True, by="ctrl.kim", approver="travis")
        self.assertEqual(res["policy_version"], 2)
        self.assertEqual(set(res["approvals_invalidated"]), {granted["id"], pending["id"]})
        for ap in (granted, pending):
            self.assertEqual(c.approvals.get(ap["id"])["status"], "invalidated")
        with self.assertRaises(ApprovalNotGranted):
            c.execute(granted["id"], actor="pm.lee")
        self.assertEqual(c.commitments.get(cmt1)["status"], "draft")
        # a fresh approval under version 2 executes
        fresh = c.request_approval("commitment.execute", cmt1, actor_role="pm", requested_by="pm.lee")
        self.assertEqual(fresh["manifest"]["governance"][PLUGIN_NAME]["policy_version"], 2)
        c.approve(fresh["id"], approver="pm.ana", approver_role="pm")
        self.assertEqual(c.execute(fresh["id"], actor="pm.lee").result["status"], "executed")

    def test_turning_enforcement_on_invalidates_approvals_requested_before_it(self):
        w = World().team(enforce=False)
        c = w.c
        ap = c.request_approval("commitment.execute", w.commitment(), actor_role="pm", requested_by="anyone")
        c.approve(ap["id"], approver="anyone", approver_role="pm")
        w.policy(enforce=True, segregate=True)
        self.assertEqual(c.approvals.get(ap["id"])["status"], "invalidated")

    def test_the_service_invalidates_an_approval_whose_policy_binding_moved(self):
        """Belt and braces: even if an approval escaped the adoption sweep, the service's
        governance comparison invalidates it at execution."""
        w = World().team()
        c = w.c
        ap = c.request_approval("commitment.execute", w.commitment(), actor_role="pm", requested_by="pm.lee")
        c.approve(ap["id"], approver="pm.ana", approver_role="pm")
        w.p._binding = lambda: {"policy_version": 99, "policy_hash": "moved"}  # the policy moved underneath the grant
        with self.assertRaisesRegex(StaleApprovalError, "people changed"):
            c.execute(ap["id"], actor="pm.lee")
        self.assertEqual(c.approvals.get(ap["id"])["status"], "invalidated")


# --------------------------------------------------------------------------- #
# 8. the governor while a policy enforces                                      #
# --------------------------------------------------------------------------- #

class EnforcementTests(unittest.TestCase):
    def setUp(self):
        self.w = World().team()
        self.c, self.p = self.w.c, self.w.p

    def test_requests_need_an_active_identity(self):
        c = self.c
        cmt = self.w.commitment()
        with self.assertRaisesRegex(IdentityRefused, "not an active registered identity"):
            c.request_approval("commitment.execute", cmt, actor_role="pm", requested_by="someone")
        with self.assertRaisesRegex(IdentityRefused, "not an active registered identity"):
            c.request_approval("commitment.execute", cmt, actor_role="pm")  # the default "owner" is not a registered login here
        self.p.deactivate_person("pm.ana", reason="left (synthetic)", actor="travis")
        with self.assertRaisesRegex(IdentityRefused, "not an active registered identity"):
            c.request_approval("commitment.execute", cmt, actor_role="pm", requested_by="pm.ana")
        with self.assertRaisesRegex(IdentityRefused, "not an active registered identity"):
            self.p.request_grant("pm.lee", "controller", reason="x", actor="someone")

    def test_approvers_hold_the_claimed_role_in_the_manifest_scope(self):
        c, w = self.c, self.w
        on_a, on_b = w.commitment(w.a), w.commitment(w.b)
        ap_a = c.request_approval("commitment.execute", on_a, actor_role="pm", requested_by="ctrl.kim")
        ap_b = c.request_approval("commitment.execute", on_b, actor_role="pm", requested_by="ctrl.kim")
        with self.assertRaisesRegex(IdentityRefused, "does not hold role 'owner'"):
            c.approve(ap_a["id"], approver="pm.lee", approver_role="owner")  # naming a role is not holding it
        with self.assertRaisesRegex(IdentityRefused, f"on project {w.b}"):
            c.approve(ap_b["id"], approver="pm.lee", approver_role="pm")  # pm.lee is pm on project A only
        c.approve(ap_a["id"], approver="pm.lee", approver_role="pm")
        c.approve(ap_b["id"], approver="pm.ana", approver_role="pm")  # entity-scoped pm covers project B
        self.assertEqual(c.approvals.get(ap_b["id"])["status"], "granted")

    def test_segregation_refuses_self_approval(self):
        c = self.c
        ap = c.request_approval("commitment.execute", self.w.commitment(), actor_role="pm", requested_by="pm.ana")
        with self.assertRaisesRegex(IdentityRefused, "segregation"):
            c.approve(ap["id"], approver="PM.Ana", approver_role="pm")
        own = c.request_approval("commitment.execute", self.w.commitment(), actor_role="owner", requested_by="travis")
        with self.assertRaisesRegex(IdentityRefused, "segregation"):
            c.approve(own["id"], approver="travis")  # not solo-owner mode: the owner too
        self.assertEqual(c.approvals.get(own["id"])["status"], "pending")
        self.assertEqual(self.c.db.scalar("SELECT COUNT(*) FROM people_self_approvals"), 0)

    def test_service_identities_never_approve(self):
        c = self.c
        ap = c.request_approval("commitment.execute", self.w.commitment(), actor_role="pm", requested_by="pm.lee")
        with self.assertRaisesRegex(IdentityRefused, "service identit"):
            c.approve(ap["id"], approver="pay-worker", approver_role="owner")
        self.assertEqual(c.approvals.get(ap["id"])["status"], "pending")
        self.assertTrue(self.p.holds("pay-worker", "treasury"))  # it may still execute what it holds

    def test_executors_hold_the_executing_role_and_a_refusal_leaves_the_grant(self):
        c, w = self.c, self.w
        cmt = w.commitment(w.b)
        ap = c.request_approval("commitment.execute", cmt, actor_role="pm", requested_by="ctrl.kim")
        c.approve(ap["id"], approver="pm.ana", approver_role="pm")
        with self.assertRaisesRegex(IdentityRefused, "does not hold the executing role 'pm' on project"):
            c.execute(ap["id"], actor="pm.lee")  # pm on project A only
        with self.assertRaisesRegex(IdentityRefused, "not an active registered identity"):
            c.execute(ap["id"], actor="owner")
        self.assertEqual(c.approvals.get(ap["id"])["status"], "granted")
        self.assertEqual(c.commitments.get(cmt)["status"], "draft")
        self.assertEqual(c.execute(ap["id"], actor="travis").result["status"], "executed")  # the owner holds every role

    def test_an_approval_whose_approver_left_is_invalidated(self):
        c = self.c
        cmt = self.w.commitment()
        ap = c.request_approval("commitment.execute", cmt, actor_role="pm", requested_by="pm.lee")
        c.approve(ap["id"], approver="pm.ana", approver_role="pm")
        self.p.deactivate_person("pm.ana", reason="left before execution (synthetic)", actor="travis")
        with self.assertRaisesRegex(StaleApprovalError, "no longer an active identity"):
            c.execute(ap["id"], actor="pm.lee")
        self.assertEqual(c.approvals.get(ap["id"])["status"], "invalidated")
        self.assertEqual(c.commitments.get(cmt)["status"], "draft")

    def test_delegated_authority_approves_within_its_window(self):
        c, p = self.c, self.p
        d = p.request_delegation("pm.ana", "ctrl.kim", "pm", effective_to="2026-10-20", reason="leave cover (synthetic)", actor="pm.ana")
        da = c.request_approval(OP_DELEGATE, d["id"], actor_role="owner", requested_by="pm.ana")
        c.approve(da["id"], approver="travis")
        c.execute(da["id"], actor="travis")
        ap = c.request_approval("commitment.execute", self.w.commitment(), actor_role="pm", requested_by="pm.lee")
        c.approve(ap["id"], approver="ctrl.kim", approver_role="pm")
        late = c.request_approval("commitment.execute", self.w.commitment(), actor_role="pm", requested_by="pm.lee")
        p.now = clock("2026-10-21")
        with self.assertRaisesRegex(IdentityRefused, "does not hold role 'pm'"):
            c.approve(late["id"], approver="ctrl.kim", approver_role="pm")
        with self.assertRaisesRegex(StaleApprovalError, "no longer an active identity authorized"):
            c.execute(ap["id"], actor="pm.lee")  # its approver's delegated authority lapsed before execution

    def test_people_operations_are_governed_too(self):
        c, p = self.c, self.p
        p.register_person("acct.ray", "Synthetic accountant", actor="travis")
        with self.assertRaisesRegex(IdentityRefused, "only an active owner"):
            p.register_person("intruder", "Intruder", actor="pm.lee")
        req = p.request_grant("acct.ray", "accountant", reason="staffing", actor="ctrl.kim")
        ap = c.request_approval(OP_GRANT, req["id"], actor_role="owner", requested_by="ctrl.kim")
        with self.assertRaisesRegex(IdentityRefused, "does not hold role 'owner'"):
            c.approve(ap["id"], approver="ctrl.kim", approver_role="owner")  # an administrator never grants rights to anyone by naming owner
        c.approve(ap["id"], approver="travis")
        with self.assertRaisesRegex(IdentityRefused, "does not hold the executing role 'owner'"):
            c.execute(ap["id"], actor="ctrl.kim")
        c.execute(ap["id"], actor="travis")
        self.assertTrue(p.holds("acct.ray", "accountant"))

    def test_an_approval_recorded_around_the_service_cannot_execute(self):
        c = self.c
        cmt = self.w.commitment()
        m = c._base_manifest("commitment.execute", cmt, "pm")  # no identity binding, no governor checks
        ap = c.approvals.request(m, requested_by="pm.lee")
        c.approvals.grant(ap["id"], approver="mallory")
        with self.assertRaisesRegex(StaleApprovalError, "people changed"):
            c.execute(ap["id"], actor="pm.lee")
        self.assertEqual(c.approvals.get(ap["id"])["status"], "invalidated")
        self.assertEqual(c.commitments.get(cmt)["status"], "draft")

    def test_hooks_decide_on_the_stored_approval_not_a_callers_copy(self):
        c, p = self.c, self.p
        ap = c.request_approval("commitment.execute", self.w.commitment(), actor_role="pm", requested_by="pm.lee")
        forged = dict(ap, manifest=dict(ap["manifest"], governance={PLUGIN_NAME: {"policy_version": 99}}), requested_by="pm.ana")
        p.check_grant(forged, approver="pm.ana", approver_role="pm")  # judged on the stored request by pm.lee: no drift, no segregation issue
        self.assertEqual(c.approvals.get(ap["id"])["status"], "pending")

    def test_identity_administration_is_owner_only_while_enforcing(self):
        c, p, w = self.c, self.p, self.w
        with self.assertRaisesRegex(IdentityRefused, "only an active owner"):
            p.add_membership("pm.ana", w.a, actor="pm.lee")
        p.add_membership("pm.ana", w.b, actor="travis")
        with self.assertRaisesRegex(IdentityRefused, "only an active owner"):
            p.end_membership("pm.ana", w.b, reason="x", actor="pm.lee")
        p.end_membership("pm.ana", w.b, reason="finished on B (synthetic)", actor="pm.ana")  # anyone may step back
        with self.assertRaisesRegex(IdentityRefused, "only an active owner"):
            p.deactivate_person("pm.ana", reason="x", actor="ctrl.kim")
        req = p.request_grant("ext.acct", "viewer", reason="read access", actor="pm.ana")
        with self.assertRaisesRegex(IdentityRefused, "only an active owner"):
            p.cancel_request(req["id"], reason="x", actor="pm.lee")
        p.cancel_request(req["id"], reason="not needed", actor="pm.ana")
        d = p.request_delegation("pm.ana", "ctrl.kim", "pm", effective_to="2026-10-30", reason="cover", actor="pm.ana")
        w.run(OP_DELEGATE, d["id"], requester="pm.ana", approver="travis")
        with self.assertRaisesRegex(IdentityRefused, "only an active owner"):
            p.revoke_delegation(d["id"], reason="x", actor="pm.lee")
        p.revoke_delegation(d["id"], reason="back early (synthetic)", actor="ctrl.kim")  # the delegate may give it up
        from apps.cipher.domain.ricky import ROLE_AUTHORITY
        self.assertFalse([op for ops in ROLE_AUTHORITY.values() for op in ops if op.startswith("people.")])  # only '*' holds people.*

    def test_the_last_active_owner_cannot_be_removed_while_enforcing(self):
        p = self.p
        with self.assertRaisesRegex(PeopleError, "last active owner"):
            p.deactivate_person("travis", reason="x", actor="travis")
        owner_grant = p.grants("travis")[0]
        with self.assertRaisesRegex(PeopleError, "last active owner"):
            p.request_revocation(owner_grant["id"], reason="x", actor="ctrl.kim")


# --------------------------------------------------------------------------- #
# 9. solo-owner mode and the outside party                                     #
# --------------------------------------------------------------------------- #

class SoloOwnerTests(unittest.TestCase):
    def solo(self):
        w = World()
        p = w.p
        p.bootstrap_owner("travis", "Synthetic sole owner")
        p.register_person("ext.acct", "Synthetic external accountant", actor="travis", external=True)
        w.grant("ext.acct", "accountant")
        w.policy(enforce=True, segregate=True, solo_owner_self_approval=True)
        return w

    def test_a_self_approval_is_recorded_and_fails_close_until_the_outside_party_reviews_it(self):
        w = self.solo()
        c, p = w.c, w.p
        cmt = w.commitment()
        ap = c.request_approval("commitment.execute", cmt, actor_role="owner", requested_by="travis")
        c.approve(ap["id"], approver="travis")
        self.assertEqual(c.execute(ap["id"], actor="travis").result["status"], "executed")
        rows = p.self_approvals(awaiting_review=True)
        self.assertEqual([(r["approval_id"], r["login"], r["policy_version"]) for r in rows], [(ap["id"], "travis", 1)])
        check = w.check("people self-approvals reviewed by an outside party")
        self.assertFalse(check["ok"])
        self.assertIn(ap["id"], check["detail"])
        brief = c.ricky.brief(w.a)
        self.assertTrue(any(it["kind"] == "close_check" and "outside party" in it["text"] for it in brief["items"]))
        close = c._plugins.get("close")
        if close is not None:
            self.assertIn("people self-approvals reviewed by an outside party", close.checklist_report("P1")["failing"])
        with self.assertRaisesRegex(IdentityRefused, "not an active outside party"):
            p.review_self_approval(ap["id"], note="looks fine", actor="travis")
        reviewed = p.review_self_approval(ap["id"], note="Reviewed against the synthetic subcontract file.", actor="EXT.ACCT")
        self.assertEqual(reviewed["reviewed_by"], "ext.acct")
        self.assertTrue(w.check("people self-approvals reviewed by an outside party")["ok"])
        with self.assertRaisesRegex(PeopleError, "already reviewed"):
            p.review_self_approval(ap["id"], note="again", actor="ext.acct")
        self.assertEqual(p.integrity_problems(), [])

    def test_only_an_owner_self_approves_in_solo_mode(self):
        w = self.solo()
        c, p = w.c, w.p
        p.register_person("pm.lee", "Synthetic PM Lee", actor="travis")
        req = p.request_grant("pm.lee", "pm", reason="staffing", actor="travis")
        w.run(OP_GRANT, req["id"], requester="travis", approver="travis")  # a self-approval, recorded
        self.assertEqual(len(p.self_approvals(awaiting_review=True)), 1)
        ap = c.request_approval("commitment.execute", w.commitment(), actor_role="pm", requested_by="pm.lee")
        with self.assertRaisesRegex(IdentityRefused, "only an owner may self-approve"):
            c.approve(ap["id"], approver="pm.lee", approver_role="pm")
        c.approve(ap["id"], approver="travis")  # the owner approving someone else's request is no exception
        self.assertEqual(len(p.self_approvals(awaiting_review=True)), 1)
        # the outside party never reviews the approval of its own authority
        req = p.request_grant("ext.acct", "viewer", reason="read access to the subcontract file", actor="travis")
        own = w.run(OP_GRANT, req["id"], requester="travis", approver="travis")
        own_ap = c.db.scalar("SELECT approval_id FROM people_self_approvals s JOIN approvals a ON a.id = s.approval_id WHERE a.subject_id=?", (req["id"],))
        self.assertEqual(own.result["login"], "ext.acct")
        with self.assertRaisesRegex(IdentityRefused, "own authority"):
            p.review_self_approval(own_ap, note="fine", actor="ext.acct")

    def test_self_approval_records_resist_raw_sql_and_omissions_are_detected(self):
        w = self.solo()
        c, p = w.c, w.p
        ap = c.request_approval("commitment.execute", w.commitment(), actor_role="owner", requested_by="travis")
        c.approve(ap["id"], approver="travis")
        row = c.db.one("SELECT * FROM people_self_approvals WHERE approval_id=?", (ap["id"],))
        probes = [
            ("review it as the owner", "UPDATE people_self_approvals SET reviewed_by='travis', reviewed_at='t', review_note='fine' WHERE id=?"),
            ("review it without the registry", "UPDATE people_self_approvals SET reviewed_by='ext.acct', reviewed_at='t', review_note='fine' WHERE id=?"),
            ("delete it", "DELETE FROM people_self_approvals WHERE id=?"),
        ]
        for label, sql in probes:
            with self.subTest(probe=label), self.assertRaises(sqlite3.DatabaseError):
                c.db.execute(sql, (row["id"],))
        c.db.execute("DROP TRIGGER people_self_approvals_no_delete")
        c.db.execute("DELETE FROM people_self_approvals WHERE id=?", (row["id"],))
        self.assertTrue(w.check("people self-approvals reviewed by an outside party")["ok"])  # nothing left to review ...
        intact = w.check("people identity records intact")
        self.assertFalse(intact["ok"])  # ... but the omission is caught
        self.assertIn("without a self-approval record", intact["detail"])


# --------------------------------------------------------------------------- #
# 10. close checks, state and export                                           #
# --------------------------------------------------------------------------- #

class CloseCheckAndStateTests(unittest.TestCase):
    def test_grants_and_delegations_ending_within_14_days_are_reported(self):
        w = World().team(enforce=False)
        p = w.p
        p.register_person("temp.sam", "Synthetic temporary scheduler", actor="travis")
        w.grant("temp.sam", "viewer", effective_to="2026-10-20")
        w.grant("temp.sam", "estimator", effective_to="2026-12-31")
        d = p.request_delegation("pm.ana", "ctrl.kim", "pm", effective_to="2026-10-26", reason="cover", actor="pm.ana")
        w.run(OP_DELEGATE, d["id"], requester="pm.ana", approver="travis")
        check = w.check(f"people grants and delegations ending within {EXPIRY_WARNING_DAYS} days (informational)")
        self.assertTrue(check["ok"])
        self.assertIn("viewer for temp.sam ends 2026-10-20", check["detail"])
        self.assertIn("pm for ctrl.kim ends 2026-10-26", check["detail"])
        self.assertNotIn("estimator", check["detail"])
        self.assertEqual(w.c.project_state(w.a)[PLUGIN_NAME]["summary"]["expiring_within_14_days"], 2)
        p.now = clock("2026-10-27")
        self.assertIn("no grant or delegation ends", w.check(f"people grants and delegations ending within {EXPIRY_WARNING_DAYS} days (informational)")["detail"])

    def test_state_and_audit_export(self):
        w = World().team(solo=True)
        c = w.c
        state = c.project_state(w.a)[PLUGIN_NAME]
        self.assertTrue(state["enforcing"])
        self.assertEqual(state["policy"]["version"], 1)
        s = state["summary"]
        self.assertEqual((s["people"], s["services"], s["outside_parties"], s["active_owners"], s["integrity_failures"]), (6, 1, 1, 1, 0))
        self.assertEqual([m["person_id"] for m in state["members"]], [w.p.person_for("pm.lee")["id"]])
        lee = next(x for x in state["people"] if x["login"] == "pm.lee")
        self.assertEqual([(a["role"], a["scope"], a["project_id"]) for a in lee["authorities"]], [("pm", "project", w.a)])
        export = c.audit_export()["modules"][PLUGIN_NAME]
        self.assertEqual(len(export["grants"]), 6)
        self.assertEqual(len(export["policy_versions"]), 1)
        self.assertEqual(export["integrity_problems"], [])
        self.assertTrue(c.audit.verify_chain()["ok"])


# --------------------------------------------------------------------------- #
# 11. the golden fixture under an enforcing identity policy                    #
# --------------------------------------------------------------------------- #

class GoldenFixtureUnderEnforcementTests(unittest.TestCase):
    def test_the_golden_fixture_runs_when_every_actor_is_a_registered_identity(self):
        c = Cipher()
        p = c.plugin(PLUGIN_NAME)
        p.bootstrap_owner("owner", "Synthetic owner")
        p.register_person("treasury", "Synthetic treasury release worker", actor="owner", kind="service")
        req = p.request_grant("treasury", "treasury", reason="payment release worker", actor="owner")
        c.approve_and_execute(OP_GRANT, req["id"], actor="owner")
        draft = p.prepare_policy(enforce=True, segregate=False, reason="enforce identities, single operator", actor="owner")
        c.approve_and_execute(OP_POLICY, draft["id"], actor="owner")
        self.assertTrue(p.enforcing())
        r = run_golden_fixture(c)
        plain = run_golden_fixture(Cipher())
        for key in ("executed_amount", "sov", "bill1", "bill2", "prime", "bank", "fees", "cost", "stored", "stale_result", "ap_bill3_status"):
            self.assertEqual(r[key], plain[key], key)
        self.assertEqual(r["executed_amount"], "122000.00")
        self.assertEqual(r["payment"]["transfers"], 1)
        bound =[ap["manifest"]["governance"][PLUGIN_NAME]["policy_version"] for ap in c.approvals.list() if ap["operation"] not in (OP_GRANT, OP_POLICY)]
        self.assertTrue(bound and set(bound) == {1})
        self.assertEqual(p.integrity_problems(), [])


if __name__ == "__main__":
    unittest.main()

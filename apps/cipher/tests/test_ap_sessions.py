"""Opaque synthetic sessions keep current, scoped and segregated duties."""
from dataclasses import replace
import unittest

from apps.cipher.ap_practice_fixture import (
    ACCOUNTANT_LOGIN, BOOTSTRAP_LOGIN, HIDDEN_ACCOUNTANT_LOGIN, PM_LOGIN, make_ap_practice_fixture,
)
from apps.cipher.ap_sessions import APIdentityRefusal, APPracticeSessions, authority_for


class Clock:
    def __init__(self):
        self.value = 10000.0

    def __call__(self):
        return self.value


class APPracticeSessionTests(unittest.TestCase):
    def setUp(self):
        self.c = make_ap_practice_fixture()
        self.addCleanup(self.c.db.close)
        self.clock = Clock()
        self.sessions = APPracticeSessions(self.c, clock=self.clock)
        self.people = self.c.plugin("people")

    def person(self, persona="accountant"):
        return self.sessions.select(self.sessions.anonymous(), persona)

    def govern(self, operation, subject):
        approval = self.c.request_approval(operation, subject, actor_role="owner", requested_by=HIDDEN_ACCOUNTANT_LOGIN)
        self.c.approve(approval["id"], approver=BOOTSTRAP_LOGIN, approver_role="owner")
        return self.c.execute(approval["id"], actor=BOOTSTRAP_LOGIN)

    def test_parallel_cookie_reads_keep_existing_request_snapshots_valid(self):
        original = self.person()
        first = self.sessions.get(original.cookie_token)
        self.clock.value += 1
        second = self.sessions.get(original.cookie_token)
        self.assertEqual(self.sessions.require(first).person_id, self.sessions.require(second).person_id)
        self.assertTrue(self.sessions.validate_csrf(first, first.csrf_token))
        switched = self.sessions.select(second, "pm")
        for previous in (original, first, second):
            with self.assertRaises(APIdentityRefusal):
                self.sessions.require(previous)
            self.assertFalse(self.sessions.validate_csrf(previous, previous.csrf_token))
        self.assertEqual(self.sessions.require(switched).duties, ("pm",))

    def test_anonymous_session_exposes_no_scopes_and_cannot_read_as_a_person(self):
        session = self.sessions.anonymous()
        view = self.sessions.dto(session)
        self.assertFalse(view["authenticated"])
        self.assertIsNone(view["person"])
        self.assertEqual(view["duties"], [])
        self.assertEqual(view["projectIds"], [])
        self.assertFalse(view["capabilities"]["microsoftSignIn"])
        self.assertFalse(view["capabilities"]["liveAdmission"])
        with self.assertRaises(APIdentityRefusal):
            self.sessions.require(session)

    def test_only_fixed_personas_can_be_selected_and_safe_options_do_not_mutate_repository(self):
        options = self.sessions.personas()
        self.assertEqual({option["personaId"] for option in options}, {"accountant", "pm"})
        self.assertTrue(all(set(option) == {"personaId", "displayName", "synthetic"} for option in options))
        options[0]["personaId"] = "owner"
        self.assertNotIn("owner", {option["personaId"] for option in self.sessions.personas()})
        session = self.sessions.anonymous()
        for forged in ("owner", BOOTSTRAP_LOGIN, ACCOUNTANT_LOGIN, self.people.person_for(BOOTSTRAP_LOGIN)["id"],
                       "hidden-pm", {"personaId": "pm", "role": "owner"}, None):
            with self.subTest(forged=forged), self.assertRaises(APIdentityRefusal):
                self.sessions.select(session, forged)
        self.assertEqual(self.sessions.require(self.sessions.select(session, "accountant")).duties, ("accountant",))

    def test_bind_switch_and_logout_rotate_both_secrets_and_invalidate_all_previous_cookies(self):
        anonymous = self.sessions.anonymous()
        accountant = self.sessions.select(anonymous.cookie_token, "accountant")
        pm = self.sessions.select(accountant.cookie_token, "pm")
        logged_out = self.sessions.logout(pm.cookie_token)
        for previous in (anonymous, accountant, pm):
            self.assertIsNone(self.sessions.get(previous.cookie_token))
            self.assertFalse(self.sessions.validate_csrf(previous, previous.csrf_token))
            with self.assertRaises(APIdentityRefusal):
                self.sessions.dto(previous)
        self.assertEqual(len({session.cookie_token for session in (anonymous, accountant, pm, logged_out)}), 4)
        self.assertEqual(len({session.csrf_token for session in (anonymous, accountant, pm, logged_out)}), 4)
        self.assertFalse(self.sessions.dto(logged_out)["authenticated"])

    def test_current_registered_person_and_actual_project_duties_are_resolved(self):
        session = self.person()
        authority = self.sessions.require(session)
        self.assertEqual(authority.person_id, self.people.person_for(ACCOUNTANT_LOGIN)["id"])
        self.assertEqual(authority.login, ACCOUNTANT_LOGIN)
        self.assertEqual(authority.duties, ("accountant",))
        self.assertEqual(set(authority.project_ids), set(self.c.ap_practice_records["visible_project_ids"]))
        self.assertNotIn(self.c.ap_practice_records["hidden_project_id"], authority.project_ids)
        self.assertTrue(authority.allows(authority.project_ids[0], "accountant"))
        self.assertFalse(authority.allows(authority.project_ids[0], "pm"))
        self.assertFalse(authority.allows(self.c.ap_practice_records["hidden_project_id"], "accountant"))

    def test_project_duties_do_not_elevate_another_project_from_union_of_roles(self):
        session = self.person("pm")
        first, second = self.c.ap_practice_records["visible_project_ids"]
        grant = self.people.request_grant(PM_LOGIN, "accountant", project_id=second,
                                          reason="Synthetic mixed-duty test", actor=BOOTSTRAP_LOGIN)
        self.govern("people.grant_role", grant["id"])
        authority = self.sessions.require(session)
        self.assertEqual(authority.duties, ("accountant", "pm"))
        self.assertFalse(authority.allows(first, "accountant"))
        self.assertTrue(authority.allows(second, "accountant"))

    def test_current_membership_end_removes_scope_and_changes_hash_without_new_session(self):
        session = self.person()
        before = self.sessions.require(session)
        project = self.c.ap_practice_records["visible_project_ids"][0]
        self.people.end_membership(ACCOUNTANT_LOGIN, project, reason="Synthetic reassignment", actor=BOOTSTRAP_LOGIN)
        after = self.sessions.require(session)
        self.assertNotIn(project, after.project_ids)
        self.assertNotEqual(before.scope_hash, after.scope_hash)
        self.assertNotIn(project, self.sessions.dto(session)["projectIds"])

    def test_genuine_grant_revocation_removes_scope_immediately(self):
        session = self.person()
        before = self.sessions.require(session)
        grant = next(grant for grant in self.people.grants(ACCOUNTANT_LOGIN)
                     if grant["project_id"] == before.project_ids[0])
        revocation = self.people.request_revocation(grant["id"], reason="Synthetic duty withdrawn", actor=PM_LOGIN)
        self.govern("people.revoke_role", revocation["id"])
        after = self.sessions.require(session)
        self.assertFalse(after.allows(grant["project_id"], "accountant"))
        self.assertNotEqual(before.scope_hash, after.scope_hash)
        self.assertEqual(self.people.authority_problems(), [])

    def test_person_deactivation_refuses_existing_session_and_new_selection(self):
        session = self.person()
        self.people.deactivate_person(ACCOUNTANT_LOGIN, reason="Synthetic departure", actor=BOOTSTRAP_LOGIN)
        for action in (lambda: self.sessions.require(session), lambda: self.sessions.dto(session),
                       lambda: self.sessions.select(self.sessions.anonymous(), "accountant")):
            with self.assertRaises(APIdentityRefusal) as refusal:
                action()
            self.assertEqual(refusal.exception.code, "session_person_unavailable")

    def test_idle_window_uses_monotonic_activity_and_expiration_boundary(self):
        session = self.person()
        self.clock.value += 1799
        active = self.sessions.get(session.cookie_token)
        self.assertIsNotNone(active)
        self.clock.value += 1799
        self.assertEqual(self.sessions.require(active).duties, ("accountant",))
        self.clock.value += 1
        self.assertIsNone(self.sessions.get(session.cookie_token))
        with self.assertRaises(APIdentityRefusal):
            self.sessions.require(active)

    def test_absolute_window_expires_even_with_regular_activity(self):
        session = self.person()
        for _ in range(31):
            self.clock.value += 900
            self.assertIsNotNone(self.sessions.get(session.cookie_token))
        self.clock.value += 900
        self.assertIsNone(self.sessions.get(session.cookie_token))
        with self.assertRaises(APIdentityRefusal):
            self.sessions.require(session)

    def test_unknown_cookies_and_modified_person_or_lifetime_snapshots_cannot_establish_authority(self):
        session = self.person()
        self.assertIsNone(self.sessions.get("not-a-cookie"))
        self.assertIsNone(self.sessions.get(None))
        self.assertIsNone(self.sessions.get("x" * 129))
        forged = replace(session, person_id=self.people.person_for(BOOTSTRAP_LOGIN)["id"], persona_id="owner")
        with self.assertRaises(APIdentityRefusal):
            self.sessions.require(forged)
        self.assertFalse(self.sessions.validate_csrf(forged, session.csrf_token))
        extended = replace(session, last_seen=self.clock.value + 999999)
        self.clock.value += 1800
        with self.assertRaises(APIdentityRefusal):
            self.sessions.require(extended)

    def test_csrf_matches_only_current_session_with_constant_time_safe_input(self):
        session, other = self.person(), self.person("pm")
        self.assertTrue(self.sessions.validate_csrf(session, session.csrf_token))
        for token in (None, 42, "", other.csrf_token, "x" * 129, "🔒", "\ud800"):
            with self.subTest(token=repr(token)):
                self.assertFalse(self.sessions.validate_csrf(session, token))
        self.clock.value += 1800
        self.assertFalse(self.sessions.validate_csrf(session, session.csrf_token))

    def test_pure_authority_and_dto_leave_all_engine_writes_unchanged(self):
        session = self.person()
        before = (self.c.db.conn.total_changes, self.c.db.query("SELECT * FROM audit_log ORDER BY seq"))
        for _ in range(2):
            authority_for(self.c, session.person_id)
            self.sessions.require(session)
            self.sessions.dto(session)
        self.assertEqual(before, (self.c.db.conn.total_changes, self.c.db.query("SELECT * FROM audit_log ORDER BY seq")))

    def test_owner_wildcard_without_actual_project_grant_admits_no_ap_scopes(self):
        authority = authority_for(self.c, self.people.person_for(BOOTSTRAP_LOGIN)["id"])
        self.assertEqual(authority.duties, ())
        self.assertEqual(authority.project_ids, ())

    def test_unverified_current_registry_refuses_without_leaking_internal_details(self):
        session = self.person()
        self.c.db.execute("DROP TRIGGER people_persons_update_guard")
        self.c.db.execute("UPDATE people_persons SET display_name='Forged name' WHERE login=?", (ACCOUNTANT_LOGIN,))
        with self.assertRaises(APIdentityRefusal) as refusal:
            self.sessions.require(session)
        self.assertEqual(refusal.exception.status, 423)
        self.assertNotIn("Forged", refusal.exception.message)

    def test_backwards_or_nonfinite_clock_never_extends_authority(self):
        session = self.person()
        self.clock.value -= 1
        self.assertIsNone(self.sessions.get(session.cookie_token))
        self.clock.value = float("nan")
        with self.assertRaises(APIdentityRefusal):
            self.sessions.anonymous()

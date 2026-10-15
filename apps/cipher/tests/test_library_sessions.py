"""Actual audited Library duties and volatile independent synthetic sessions."""
from dataclasses import replace
import unittest
from unittest.mock import patch

from apps.cipher.ap_contract import APRefusal
from apps.cipher.library_sessions import LibraryPracticeSessions, LibraryIdentityRefusal, authority_for
from apps.cipher.service import Cipher


class LibrarySessionTests(unittest.TestCase):
    def setUp(self):
        self.c = Cipher()
        self.addCleanup(self.c.db.close)
        self.people = self.c.plugin("people")
        self.owner = "practice.library.authority.owner"
        self.people.bootstrap_owner(self.owner,"Synthetic Library authority setup")
        self.project = self.c.create_project(name="Synthetic visible Library",entity="Synthetic Library entity",budget="10000",actor=self.owner)["id"]
        self.hidden = self.c.create_project(name="Hidden synthetic Library",entity="Synthetic Library entity",budget="10000",actor=self.owner)["id"]
        for login,kind,external in (("library.pm","person",False),("library.reviewer","person",False),("library.poster","person",False),
                                    ("library.controller","person",False),("library.hidden","person",False),("library.delegate","person",False),
                                    ("library.service","service",False),("library.external","person",True)):
            self.people.register_person(login,"Synthetic "+login,actor=self.owner,kind=kind,external=external)
        for login,role,project in (("library.pm","pm",self.project),("library.reviewer","pm",self.project),
                                   ("library.poster","pm",self.project),("library.controller","controller",self.project),
                                   ("library.hidden","accountant",self.hidden),("library.service","accountant",self.project),
                                   ("library.external","accountant",self.project)):
            self.people.add_membership(login,project,actor=self.owner)
            requested=self.people.request_grant(login,role,project_id=project,reason="Synthetic Library own duty",actor=self.owner)
            self.govern("people.grant_role",requested["id"])
        self.people.add_membership("library.delegate",self.project,actor=self.owner)
        delegation=self.people.request_delegation("library.reviewer","library.delegate","pm",project_id=self.project,
            effective_to="2099-12-31",reason="Synthetic delegation control case",actor=self.owner)
        self.govern("people.delegate",delegation["id"])
        self.people.register_person("library.admin.reviewer","Synthetic independent identity administrator",actor=self.owner)
        admin=self.people.request_grant("library.admin.reviewer","owner",reason="Synthetic independent identity administration",actor=self.owner)
        self.govern("people.grant_role",admin["id"])
        policy=self.people.prepare_policy(enforce=True,segregate=True,solo_owner_self_approval=False,
            reason="Synthetic independent Library duties",actor=self.owner)
        self.govern("people.set_policy",policy["id"])
        self.c.library_practice_persona_people={key:{"person_id":self.people.person_for(login)["id"],"login":login}
            for key,login in (("preparer","library.pm"),("reviewer","library.reviewer"),("poster","library.poster"),("controller","library.controller"))}
        self.c.library_practice_personas=tuple({"personaId":key,"displayName":self.people.person_for(value["login"])["display_name"],"synthetic":True}
            for key,value in self.c.library_practice_persona_people.items())
        self.clock=[100.0]
        self.sessions=LibraryPracticeSessions(self.c,clock=lambda:self.clock[0])

    def govern(self,operation,subject):
        approval=self.c.request_approval(operation,subject,actor_role="owner",requested_by=self.owner)
        reviewer="library.admin.reviewer" if self.people.enforcing() else self.owner
        self.c.approve(approval["id"],approver=reviewer,approver_role="owner")
        return self.c.execute(approval["id"],actor=self.owner)

    def person(self,login):return self.people.person_for(login)["id"]
    def snapshot(self):return tuple(self.c.db.conn.iterdump()),self.c.db.conn.total_changes,tuple(self.c.provider.submissions)

    def test_current_owned_project_pm_duties_are_exact_and_zero_write(self):
        before=self.snapshot()
        for login in ("library.pm","library.reviewer","library.poster"):
            current=authority_for(self.c,self.person(login))
            self.assertTrue(current.allows(self.project,"pm"))
            self.assertFalse(current.allows(self.hidden,"pm"))
            self.assertEqual(current.project_ids,(self.project,))
            self.assertEqual(current.operation_role(self.project,"pm"),"pm")
        controller=authority_for(self.c,self.person("library.controller"))
        self.assertEqual(controller.project_ids,())
        self.assertFalse(controller.allows(self.project,"pm"))
        self.assertEqual(before,self.snapshot())

    def test_owner_wildcard_and_real_delegation_do_not_supply_owned_Library_duty(self):
        before=self.snapshot()
        for login in (self.owner,"library.delegate"):
            current=authority_for(self.c,self.person(login))
            self.assertEqual(current.project_ids,())
            for duty in ("pm","accounting","send"):
                self.assertFalse(current.allows(self.project,duty))
                with self.assertRaises(APRefusal):current.require(self.project,duty)
        self.assertEqual(before,self.snapshot())

    def test_service_external_and_caller_persona_or_person_alias_are_refused(self):
        before=self.snapshot()
        for login in ("library.service","library.external"):
            with self.assertRaises(LibraryIdentityRefusal):authority_for(self.c,self.person(login))
        for supplied in (True,42,"library.pm","missing-person"):
            with self.assertRaises(LibraryIdentityRefusal):authority_for(self.c,supplied)
        with self.assertRaises(LibraryIdentityRefusal):authority_for(self.c,self.person("library.pm"),persona_id="poster")
        self.assertEqual(before,self.snapshot())

    def test_ended_membership_and_revoked_grant_change_scope_hash_without_writes(self):
        original=authority_for(self.c,self.person("library.reviewer"))
        self.people.end_membership("library.reviewer",self.project,reason="Synthetic Library ended assignment",actor=self.owner)
        before=self.snapshot();current=authority_for(self.c,self.person("library.reviewer"))
        self.assertEqual(current.project_ids,());self.assertNotEqual(current.scope_hash,original.scope_hash)
        self.assertEqual(before,self.snapshot())
        original=authority_for(self.c,self.person("library.poster"))
        grant=next(grant for grant in self.people.grants("library.poster") if grant["role"]=="pm")
        request=self.people.request_revocation(grant["id"],reason="Synthetic Library revoked duty",actor=self.owner)
        self.govern("people.revoke_role",request["id"])
        before=self.snapshot();current=authority_for(self.c,self.person("library.poster"))
        self.assertEqual(current.project_ids,());self.assertNotEqual(current.scope_hash,original.scope_hash)
        self.assertEqual(before,self.snapshot())

    def test_rotation_logout_csrf_and_new_store_reject_old_objects(self):
        original=self.sessions.anonymous();selected=self.sessions.select(original,"preparer")
        self.assertIsNone(self.sessions.get(original.cookie_token));self.assertFalse(self.sessions.validate_csrf(original,original.csrf_token))
        self.assertEqual(self.sessions.require(selected).login,"library.pm")
        self.assertFalse(self.sessions.validate_csrf(selected,True))
        with self.assertRaises(LibraryIdentityRefusal):self.sessions.require(replace(selected,person_id=self.person("library.poster")))
        switched=self.sessions.select(selected,"poster")
        with self.assertRaises(LibraryIdentityRefusal):self.sessions.require(selected)
        anonymous=self.sessions.logout(switched)
        self.assertFalse(self.sessions.dto(anonymous)["authenticated"])
        with self.assertRaises(LibraryIdentityRefusal):self.sessions.require(switched)
        fresh=LibraryPracticeSessions(self.c,clock=lambda:self.clock[0])
        self.assertIsNone(fresh.get(anonymous.cookie_token))

    def test_current_duty_is_rechecked_after_selection_and_dto_claims_remain_synthetic(self):
        selected=self.sessions.select(self.sessions.anonymous(),"reviewer")
        before=self.snapshot();dto=self.sessions.dto(selected)
        self.assertEqual(dto["contractVersion"],"cipher.library-practice.v1")
        self.assertEqual(dto["projectIds"],[self.project]);self.assertFalse(dto["capabilities"]["microsoftSignIn"])
        self.assertEqual(before,self.snapshot())
        self.people.deactivate_person("library.reviewer",reason="Synthetic departed reviewer",actor=self.owner)
        with self.assertRaises(LibraryIdentityRefusal):self.sessions.require(selected)

    def test_clock_regression_idle_absolute_and_invalid_clock_are_refused(self):
        original=self.sessions.anonymous();self.clock[0]=99.0
        self.assertIsNone(self.sessions.get(original.cookie_token))
        self.clock[0]=100.0;original=self.sessions.anonymous();self.clock[0]+=1800
        self.assertIsNone(self.sessions.get(original.cookie_token))
        self.clock[0]=100.0;original=self.sessions.anonymous()
        for tick in range(1,17):
            self.clock[0]=100.0+tick*1700
            original=self.sessions.get(original.cookie_token)
            self.assertIsNotNone(original)
        self.clock[0]=100.0+8*60*60
        self.assertIsNone(self.sessions.get(original.cookie_token))
        for invalid in (True,float("nan"),float("inf")):
            self.clock[0]=invalid
            with self.assertRaises(LibraryIdentityRefusal):self.sessions.anonymous()

    def test_same_cookie_concurrent_snapshots_survive_activity_but_not_rotation(self):
        selected=self.sessions.select(self.sessions.anonymous(),"preparer")
        self.clock[0]+=1;newer=self.sessions.get(selected.cookie_token)
        self.assertEqual(self.sessions.require(selected).person_id,self.sessions.require(newer).person_id)
        self.sessions.logout(newer)
        with self.assertRaises(LibraryIdentityRefusal):self.sessions.require(selected)


if __name__=="__main__":unittest.main()

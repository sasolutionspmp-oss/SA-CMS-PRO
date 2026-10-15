"""Current owned RFI membership, PM duty and isolated volatile sessions."""
from dataclasses import replace
import unittest
from apps.cipher.ap_contract import APRefusal
from apps.cipher.rfi_practice_fixture import make_rfi_practice_fixture, BOOTSTRAP_LOGIN, STAFF_LOGIN, PM_LOGIN, REVIEWER_LOGIN, EXTERNAL_LOGIN, SERVICE_LOGIN, INACTIVE_LOGIN
from apps.cipher.rfi_sessions import RFIPracticeSessions, RFIIdentityRefusal, authority_for

class RFISessionTests(unittest.TestCase):
    def setUp(self):
        self.c=make_rfi_practice_fixture();self.addCleanup(self.c.db.close)
        self.people=self.c.plugin('people');self.project=self.c.rfi_practice_records['project_id'];self.hidden=self.c.rfi_practice_records['hidden_project_id']
        self.clock=[100.0];self.sessions=RFIPracticeSessions(self.c,clock=lambda:self.clock[0])
    def person(self,login):return self.people.person_for(login)['id']
    def snapshot(self):return tuple(self.c.db.conn.iterdump()),self.c.db.conn.total_changes,tuple(self.c.provider.submissions)
    def test_membership_supplies_staff_but_only_owned_pm_grant_supplies_review(self):
        before=self.snapshot();staff=authority_for(self.c,self.person(STAFF_LOGIN))
        self.assertEqual(staff.project_ids,(self.project,));self.assertEqual(staff.duties,('staff',));self.assertTrue(staff.allows(self.project,'staff'));self.assertFalse(staff.allows(self.project,'pm'))
        with self.assertRaises(APRefusal) as error:staff.require(self.project,'pm')
        self.assertEqual(error.exception.status,403)
        for login in (PM_LOGIN,REVIEWER_LOGIN):
            current=authority_for(self.c,self.person(login));self.assertTrue(current.allows(self.project,'staff'));self.assertTrue(current.allows(self.project,'pm'));self.assertEqual(current.operation_role(self.project,'staff'),None)
        self.assertEqual(before,self.snapshot())
    def test_hidden_owner_external_service_inactive_and_body_identity_never_supply_scope(self):
        before=self.snapshot();owner=authority_for(self.c,self.person(BOOTSTRAP_LOGIN));self.assertEqual(owner.project_ids,())
        staff=authority_for(self.c,self.person(STAFF_LOGIN))
        with self.assertRaises(APRefusal) as error:staff.require(self.hidden,'staff')
        self.assertEqual(error.exception.status,404)
        for login in (EXTERNAL_LOGIN,SERVICE_LOGIN,INACTIVE_LOGIN):
            with self.assertRaises(RFIIdentityRefusal):authority_for(self.c,self.person(login))
        for value in (True,42,STAFF_LOGIN,'missing'):
            with self.assertRaises(RFIIdentityRefusal):authority_for(self.c,value)
        with self.assertRaises(RFIIdentityRefusal):authority_for(self.c,self.person(STAFF_LOGIN),persona_id='reviewer')
        self.assertEqual(before,self.snapshot())
    def test_ended_membership_rechecks_scope_without_private_source_reads_or_writes(self):
        selected=self.sessions.select(self.sessions.anonymous(),'pm');old=self.sessions.require(selected)
        self.people.end_membership(PM_LOGIN,self.project,reason='Synthetic ended assignment',actor=BOOTSTRAP_LOGIN)
        before=self.snapshot();current=self.sessions.require(selected)
        self.assertEqual(current.project_ids,());self.assertNotEqual(old.scope_hash,current.scope_hash);self.assertEqual(before,self.snapshot())
    def test_rotation_logout_csrf_and_restart_invalidate_original_credentials(self):
        original=self.sessions.anonymous();selected=self.sessions.select(original,'staff')
        self.assertIsNone(self.sessions.get(original.cookie_token));self.assertFalse(self.sessions.validate_csrf(original,original.csrf_token));self.assertEqual(self.sessions.require(selected).login,STAFF_LOGIN)
        self.assertFalse(self.sessions.validate_csrf(selected,True))
        with self.assertRaises(RFIIdentityRefusal):self.sessions.require(replace(selected,person_id=self.person(PM_LOGIN)))
        switched=self.sessions.select(selected,'pm')
        with self.assertRaises(RFIIdentityRefusal):self.sessions.require(selected)
        anonymous=self.sessions.logout(switched);self.assertFalse(self.sessions.dto(anonymous)['authenticated'])
        with self.assertRaises(RFIIdentityRefusal):self.sessions.require(switched)
        self.assertIsNone(RFIPracticeSessions(self.c).get(anonymous.cookie_token))
    def test_actual_person_is_rechecked_and_capabilities_never_claim_real_signin_or_delivery(self):
        selected=self.sessions.select(self.sessions.anonymous(),'reviewer');before=self.snapshot();dto=self.sessions.dto(selected)
        self.assertEqual(dto['contractVersion'],'cipher.rfi-practice.v1');self.assertEqual(dto['projectIds'],[self.project]);self.assertEqual(len(dto['capabilities']['commands']),9)
        for key in ('microsoftSignIn','externalDistribution','contractChange','engineeringCertification','financialEffects'):self.assertFalse(dto['capabilities'][key])
        self.assertEqual(before,self.snapshot());self.people.deactivate_person(REVIEWER_LOGIN,reason='Synthetic departed reviewer',actor=BOOTSTRAP_LOGIN)
        with self.assertRaises(RFIIdentityRefusal):self.sessions.require(selected)
    def test_clock_regression_idle_absolute_and_invalid_clock_refuse_old_session(self):
        original=self.sessions.anonymous();self.clock[0]=99;self.assertIsNone(self.sessions.get(original.cookie_token))
        self.clock[0]=100;original=self.sessions.anonymous();self.clock[0]+=1800;self.assertIsNone(self.sessions.get(original.cookie_token))
        self.clock[0]=100;original=self.sessions.anonymous()
        for tick in range(1,17):
            self.clock[0]=100+tick*1700;original=self.sessions.get(original.cookie_token);self.assertIsNotNone(original)
        self.clock[0]=100+8*60*60;self.assertIsNone(self.sessions.get(original.cookie_token))
        for value in (True,float('nan'),float('inf')):
            self.clock[0]=value
            with self.assertRaises(RFIIdentityRefusal):self.sessions.anonymous()
    def test_concurrent_activity_snapshot_remains_valid_until_rotation(self):
        selected=self.sessions.select(self.sessions.anonymous(),'staff');self.clock[0]+=1;newer=self.sessions.get(selected.cookie_token)
        self.assertEqual(self.sessions.require(selected).person_id,self.sessions.require(newer).person_id);self.sessions.logout(newer)
        with self.assertRaises(RFIIdentityRefusal):self.sessions.require(selected)

if __name__=='__main__':unittest.main()

"""A current own AR project scope precedes private source/API history reads."""
import unittest
from unittest.mock import patch

from apps.cipher.ap_contract import APRefusal
from apps.cipher.ar_practice_fixture import BOOTSTRAP_LOGIN, PM_LOGIN
from apps.cipher.tests import test_ar_actions as journeys


class ARScopeGateTests(unittest.TestCase):
    def setUp(self):
        self.journey = journeys.ARActionTests("runTest")
        self.journey.setUp()
        self.addCleanup(self.journey.doCleanups)
        self.c, self.contract = self.journey.c, self.journey.contract

    def test_ended_last_owned_membership_refuses_before_receipt_history(self):
        self.c.plugin("people").end_membership(PM_LOGIN, self.journey.r["project_id"], reason="Synthetic ended AR assignment", actor=BOOTSTRAP_LOGIN)
        before = self.journey.state()
        with patch.object(self.journey.domain, "basis_inventory", side_effect=AssertionError("Private source history was accessed")) as metadata:
            with self.assertRaises(APRefusal) as caught:
                self.contract.read(self.journey.person, "owner-bases")
            self.assertEqual(caught.exception.status, 403)
            metadata.assert_not_called()
        self.assertEqual(self.journey.state(), before)

    def test_specific_inaccessible_resources_keep_404_before_any_private_scope_or_receipt_lookup(self):
        self.c.plugin("people").end_membership(PM_LOGIN,self.journey.r["project_id"],reason="Synthetic ended AR resource assignment",actor=BOOTSTRAP_LOGIN)
        before=self.journey.state()
        with patch.object(self.journey.domain,"basis_scope",side_effect=AssertionError("Private basis scope was accessed")) as scope, patch.object(self.contract,"_inventories",side_effect=AssertionError("Private API history was accessed")) as inventory:
            for operation in (lambda:self.contract.preparation(self.journey.person,self.journey.r["basis_id"]),lambda:self.contract.authorize(self.journey.person,"ownerBill.prepare",self.journey.r["basis_id"]),lambda:self.contract.version(self.journey.person,self.journey.r["basis_id"],"basis")):
                with self.assertRaises(APRefusal) as caught:operation()
                self.assertEqual(caught.exception.status,404)
            scope.assert_not_called();inventory.assert_not_called()
        self.assertEqual(self.journey.state(),before)

    def test_owner_without_owned_ar_duty_refuses_before_history_or_counts(self):
        owner = self.c.plugin("people").person_for(BOOTSTRAP_LOGIN)["id"]
        before = self.journey.state()
        with patch.object(self.journey.domain, "basis_inventory", side_effect=AssertionError("Private source history was accessed")) as metadata:
            with self.assertRaises(APRefusal) as caught:
                self.contract.read(owner, "owner-bases")
            self.assertEqual(caught.exception.status, 403)
            metadata.assert_not_called()
        self.assertEqual(self.journey.state(), before)


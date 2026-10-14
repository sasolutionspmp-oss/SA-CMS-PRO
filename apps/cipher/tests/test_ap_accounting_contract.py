"""Source-backed accounting reads/reviews make no SQL or simulator effects."""
from __future__ import annotations

import unittest

from apps.cipher.ap_contract import APContract, APRefusal
from apps.cipher.ap_intake_contract import APIntakeContract
from apps.cipher.ap_exception_contract import APExceptionContract
from apps.cipher.ap_practice_fixture import ACCOUNTANT_LOGIN, PM_LOGIN, REVIEWER_LOGIN, BOOTSTRAP_LOGIN, make_ap_practice_fixture
from apps.cipher.core.db import SCHEMA_CATALOG
from apps.cipher.domain.ricky import ROLE_AUTHORITY
from apps.cipher.domain import accounting
from apps.cipher.accounting_simulator import SimulatedAccountingRecordStore, SimulatedAccountingAdapter
from apps.cipher.accounting_worker import SimulatedAccountingWorker
from apps.cipher.ap_accounting_contract import APAccountingContract
from apps.cipher.ap_accounting_preflight import APAccountingPreflight


class AccountingWorld:
    def setUp(self):
        self.c = make_ap_practice_fixture()
        self.addCleanup(self.c.db.close)
        self.domain = self.c.plugin("accounting")
        self.bill_id = self.c.ap_practice_records["draft_bill_id"]
        approval = self.c.request_approval("bill.approve", self.bill_id, actor_role="accountant", requested_by=ACCOUNTANT_LOGIN)
        self.c.approve(approval["id"], approver=PM_LOGIN, approver_role="pm")
        self.c.post_bill(self.bill_id, actor=ACCOUNTANT_LOGIN, period_id="2026-11", reason="Synthetic accounting source")
        bill = self.c.bills.get(self.bill_id)
        self.mapping = self.domain.prepare_synthetic_mapping(bill["project_id"], actor=ACCOUNTANT_LOGIN, reason="Synthetic practice mapping")
        self.plan = self.domain.prepare(self.bill_id, self.mapping["id"], actor=ACCOUNTANT_LOGIN)
        self.store = SimulatedAccountingRecordStore()
        self.adapter = SimulatedAccountingAdapter(self.store)
        self.worker = SimulatedAccountingWorker(self.domain, self.adapter)
        self.secret = b"scratch-accounting-private-key-32bytes"
        self.base = APContract(self.c, secret=self.secret)
        self.intake = APIntakeContract(self.c, self.base, secret=self.secret)
        self.exception = APExceptionContract(self.c, self.base, self.intake, secret=self.secret)
        self.contract = APAccountingContract(self.c, self.base, self.intake, self.exception, secret=self.secret, worker=self.worker)
        self.preflight = APAccountingPreflight(self.c, self.contract, secret=self.secret, worker=self.worker)
        self.person = self.c.plugin("people").person_for(ACCOUNTANT_LOGIN)["id"]
        self.reviewer = self.c.plugin("people").person_for(REVIEWER_LOGIN)["id"]

    def snapshot(self):
        return tuple(self.c.db.conn.iterdump()), self.c.db.conn.total_changes, dict(self.adapter.calls), self.store.effect_count

    def request(self):
        return self.c.request_approval(accounting.OP_QUEUE, self.plan["id"], actor_role="accountant", requested_by=ACCOUNTANT_LOGIN)

    def queue(self):
        approval = self.request()
        self.c.approve(approval["id"], approver=REVIEWER_LOGIN, approver_role="accountant")
        return self.c.execute(approval["id"], actor=ACCOUNTANT_LOGIN).result["intent_id"]

    def assert_pure_review(self, person, action, resource, *, allowed=True):
        before = self.snapshot()
        first = self.preflight.review(person, action, resource, {})
        second = self.preflight.review(person, action, resource, {})
        self.assertEqual(before, self.snapshot())
        self.assertEqual(first, second)
        self.assertEqual(first["allowed"], allowed)
        self.assertEqual(first["safeEffects"]["preflightAccountingSimulatorCalls"], 0)
        self.assertEqual(first["safeEffects"]["workingLedgerJournalDelta"], 0)
        return first


class APAccountingContractTests(AccountingWorld, unittest.TestCase):
    def test_current_mapping_supersession_changes_opaque_version_and_blocks_old_request(self):
        old = self.contract.version(self.person, self.plan["id"], "plan")
        self.domain.prepare_synthetic_mapping(self.plan["project_id"], actor=ACCOUNTANT_LOGIN, reason="Updated fixed synthetic mapping")
        self.assertNotEqual(old, self.contract.version(self.person, self.plan["id"], "plan"))
        self.assert_pure_review(self.person, "accounting.request", self.plan["id"], allowed=False)


    def test_owner_and_pm_do_not_acquire_accountant_capability(self):
        for login in (BOOTSTRAP_LOGIN, PM_LOGIN):
            identifier = self.c.plugin("people").person_for(login)["id"]
            before = self.snapshot()
            with self.subTest(login=login), self.assertRaises(APRefusal) as caught:
                self.preflight.review(identifier, "accounting.prepare", self.bill_id, {})
            self.assertIn(caught.exception.status, (403, 404))
            self.assertEqual(before, self.snapshot())


    def test_scoped_lists_do_not_reveal_hidden_plan_or_hashes_for_missing_ids(self):
        before = self.snapshot()
        values = self.contract.read(self.person, "accounting-plans")["value"]
        self.assertEqual([row["id"] for row in values], [self.plan["id"]])
        with self.assertRaises(APRefusal) as caught:
            self.contract.plan_review(self.person, "not-a-visible-plan")
        self.assertEqual(caught.exception.status, 404)
        self.assertEqual(before, self.snapshot())

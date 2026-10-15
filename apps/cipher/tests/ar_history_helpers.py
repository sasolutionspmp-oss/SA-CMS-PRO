"""Actual original73 SQL and native histories, without an archived source checkout.

The pinned name order and canonical hash bind every original statement. Normal
database migration and native actions create all rows and original receipts.
"""
import json
from pathlib import Path
import sqlite3
from unittest.mock import patch

from apps.cipher.core import db as core_db
from apps.cipher.core.ids import hash_json
from apps.cipher import commercial_practice_fixture
from apps.cipher.tests.test_receivables_controls import World
from apps.cipher.tests import test_commercial_actions as commercial_journey
from apps.cipher.service import Cipher


ORIGINAL73_HASH = "f6396239c845928a66c8ba93c6563641fdb75555914906c8aff71a531d64ab69"


def inventory(c):
    tables = [row["name"] for row in c.db.query("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    return {table: sorted(c.db.query(f'SELECT * FROM "{table}"'), key=lambda row: json.dumps(row, sort_keys=True)) for table in tables}


def _produce(path, output):
    assert len(core_db.SCHEMA_CATALOG) == 73
    assert hash_json(core_db.SCHEMA_CATALOG) == ORIGINAL73_HASH
    w = World(contract="250000")
    c = w.c
    try:
        assert c.db.has_write_authority() and not c.db.read_only
        bill = w.sent("22500")
        collection = c.receivables.record_collection(prime_bill_id=bill["id"], period_id="P1", amount="100.00", fee="0",
                    method="check", provider_ref="SIM-GENUINE73-HISTORICAL-RECEIPT", actor="treasury")
        assert c.db.scalar("SELECT COUNT(*) FROM journals") == 2
        assert c.db.scalar("SELECT COUNT(*) FROM prime_bill_sends") == 1
        # The real disposable fixture uses its normal distinct registered
        # people and policy. Its actions correctly remain memory-only.
        with patch.object(commercial_practice_fixture, "Cipher", return_value=c):
            fixture = commercial_practice_fixture.make_commercial_practice_fixture()
        journey = commercial_journey.CommercialActionTests("runTest")
        with patch.object(commercial_journey, "make_commercial_practice_fixture", return_value=fixture):
            journey.setUp()
        created, create_request = journey.act(journey.person, "estimate.create", journey.r["project_id"], journey.input())
        first = created["result"]["estimateId"]
        revised, revise_request = journey.act(journey.person, "estimate.revise", first, journey.input(previous=first))
        estimate = revised["result"]["estimateId"]
        _approval, outcomes = journey.accepted(estimate)
        handoff, handoff_request = journey.act(journey.person, "estimate.prepareHandoff", estimate)
        committed, commitment_request = journey.act(journey.pm, "estimate.createCommitment", handoff["result"]["handoffId"])
        for original, request in [(created, create_request), (revised, revise_request), *outcomes,
                                  (handoff, handoff_request), (committed, commitment_request)]:
            journey.replay(original, request)
        assert c.db.scalar("SELECT COUNT(*) FROM commercial_action_receipts") == 7
        assert c.audit.verify_chain()["ok"]
        assert c.provider.submissions == []
        with sqlite3.connect(path) as destination:
            c.db.conn.backup(destination)
        c.db.close()
        c = Cipher(path)
        assert c.db.read_only and not c.db.has_write_authority()
        # Use the engine's actual attested copy-ownership transition. Never
        # transplant a token/sidecar or alter the workspace row by raw SQL.
        c.db.claim_write_authority(approver="synthetic.upgrade.owner", reason="Attested synthetic original73 owned upgrade qualification",
                                   approval_ref="SYNTHETIC-GENUINE73-UPGRADE-OWNERSHIP")
        assert c.db.has_write_authority() and not c.db.read_only
        result = {"catalogHash": hash_json(core_db.SCHEMA_CATALOG), "schemaCount": len(core_db.SCHEMA_CATALOG),
                  "billId": bill["id"], "collectionId": collection["id"], "legacyProjectId": w.pid,
                  "nativeBill": c.receivables.get(bill["id"]), "tables": inventory(c),
                  "objects": c.db.query("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name"),
                  "providerSubmissions": c.provider.submissions}
        Path(output).write_text(json.dumps(result, sort_keys=True, indent=2) + "\n")
    finally:
        c.db.close()


ORIGINAL73_NAMES = ('foundation', 'ledger_integrity', 'period_integrity', 'integrity_hardening', 'assets', 'schedule', 'drawings', 'payments_scope', 'payments_controls', 'payments_terms', 'payments_controls_guards', 'payments_controls_resume_binding', 'payments_lifecycle', 'payments_destination_changes', 'payments_destination_verification', 'payments_lifecycle_bank_proof', 'reimbursements', 'reimbursements_outbox', 'reimbursements_outbox_guards', 'reimbursements_billing_collections', 'reimbursements_no_replace', 'reimbursements_cancel_reopens', 'banking', 'banking_payment_reconciled_guard', 'labor', 'labor_collection_guards', 'labor_rebill_after_reversal', 'procurement', 'estimates_structured', 'estimates_lifecycle_guards', 'estimates_no_replace_guards', 'commitment_closure_controls', 'field', 'field_rfi_distribution_approvals', 'bills_stored_material_controls', 'bills_controls_hardening', 'bills_invoices_credits_corrections', 'bills_invoice_link_and_credit_payment_guards', 'receivables_controls', 'receivables_controls_guards', 'receivables_dates_credits', 'receivables_dates_credits_guards', 'close', 'close_approval_guards', 'close_reopen_grant_roles', 'close_reopen_governance', 'handoff', 'handoff_integrity_guards', 'handoff_acknowledgement_guards', 'rights', 'rights_integrity_guards', 'rights_registry_hardening', 'ap_intake', 'ap_intake_integrity_guards', 'people', 'payment_policy', 'contracts', 'forecast_budget_versions', 'forecast_budget_guards', 'ricky_sdk', 'ricky_sdk_receipt_guards', 'ricky_sdk_key_reservations', 'ricky_sdk_redaction_key', 'audit_log_lookup_indexes', 'bills_business_approval_posting', 'workspace_mode', 'ap_practice_action_receipts', 'ap_practice_preparation_action_receipts', 'ap_practice_exception_action_receipts', 'accounting_practice_delivery', 'ap_practice_accounting_action_receipts', 'commercial_manual_sources_and_handoffs', 'commercial_practice_action_receipts')

def original73_catalog():
    current = {name: sql for _, name, sql in core_db.SCHEMA_CATALOG}
    historical = [(number, name, current[name]) for number, name in enumerate(ORIGINAL73_NAMES, 1)]
    assert hash_json(historical) == ORIGINAL73_HASH
    return historical


def produce_genuine73_history(path, output):
    with patch.object(core_db, "SCHEMA_CATALOG", original73_catalog()):
        return _produce(path, output)

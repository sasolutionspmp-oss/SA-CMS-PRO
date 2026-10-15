"""Genuine historical named SQL and native RFI/library history for upgrades.

No archived checkout, fabricated receipt, substituted schema statement or manual
write-authority token is used. Current plugins remain installed but the actual
predecessor catalog has no RFI78/79 admission, so legacy native routes are inert.
"""
from contextlib import contextmanager
from uuid import uuid4
from unittest.mock import patch

from apps.cipher.core import db as core_db
from apps.cipher.core.ids import canonical_json,sha256_hex
from apps.cipher.library_actions import LibraryActionRunner
from apps.cipher.library_contract import LibraryContract
from apps.cipher.library_preflight import LibraryPreflight
from apps.cipher.rfi_practice_fixture import (
    make_rfi_practice_fixture,BOOTSTRAP_LOGIN,STAFF_LOGIN,PM_LOGIN,REVIEWER_LOGIN,
)

PREFIX_77='19d15d425da704d8df3e9c8a343687ddd1fe52aafecdad6c0446c7dd64a30dda'
SECRET=b'rfi-upgrade-native-history-private-server-key'
FROZEN_NAMES=tuple('''foundation
ledger_integrity
period_integrity
integrity_hardening
assets
schedule
drawings
payments_scope
payments_controls
payments_terms
payments_controls_guards
payments_controls_resume_binding
payments_lifecycle
payments_destination_changes
payments_destination_verification
payments_lifecycle_bank_proof
reimbursements
reimbursements_outbox
reimbursements_outbox_guards
reimbursements_billing_collections
reimbursements_no_replace
reimbursements_cancel_reopens
banking
banking_payment_reconciled_guard
labor
labor_collection_guards
labor_rebill_after_reversal
procurement
estimates_structured
estimates_lifecycle_guards
estimates_no_replace_guards
commitment_closure_controls
field
field_rfi_distribution_approvals
bills_stored_material_controls
bills_controls_hardening
bills_invoices_credits_corrections
bills_invoice_link_and_credit_payment_guards
receivables_controls
receivables_controls_guards
receivables_dates_credits
receivables_dates_credits_guards
close
close_approval_guards
close_reopen_grant_roles
close_reopen_governance
handoff
handoff_integrity_guards
handoff_acknowledgement_guards
rights
rights_integrity_guards
rights_registry_hardening
ap_intake
ap_intake_integrity_guards
people
payment_policy
contracts
forecast_budget_versions
forecast_budget_guards
ricky_sdk
ricky_sdk_receipt_guards
ricky_sdk_key_reservations
ricky_sdk_redaction_key
audit_log_lookup_indexes
bills_business_approval_posting
workspace_mode
ap_practice_action_receipts
ap_practice_preparation_action_receipts
ap_practice_exception_action_receipts
accounting_practice_delivery
ap_practice_accounting_action_receipts
commercial_manual_sources_and_handoffs
commercial_practice_action_receipts
owner_billing_sources_and_posting
ar_practice_action_receipts
library_authored_text_and_reference_adoptions
library_practice_action_receipts'''.splitlines())


def genuine_catalog(version=77):
    """Select only pinned original entries; preserve their exact names and SQL."""
    actual=list(core_db.SCHEMA_CATALOG);by_name={name:sql for _version,name,sql in actual}
    # Cold required loading's original named order is pinned independently of
    # whichever native modules a larger test collection imported first.
    original=[(index,name,list(by_name[name])) for index,name in enumerate(FROZEN_NAMES,1)]
    if len(by_name)!=len(actual) or sha256_hex(canonical_json(original))!=PREFIX_77:
        raise AssertionError('The frozen genuine library77 predecessor changed')
    if [(v,n) for v,n,_ in actual[75:79]]!=[
            (76,'library_authored_text_and_reference_adoptions'),
            (77,'library_practice_action_receipts'),
            (78,'rfi_sources_and_review_contexts'),
            (79,'rfi_practice_action_receipts')]:
        raise AssertionError('Upgrade tests require actual source78/receipt79 after genuine library77')
    if version not in (65,77):raise ValueError('Use a real predecessor release')
    return original[:version]


@contextmanager
def historical_catalog(version=77):
    with patch.object(core_db,'SCHEMA_CATALOG',genuine_catalog(version)):
        yield


def library_runner(cipher):
    contract=LibraryContract(cipher,secret=SECRET)
    return LibraryActionRunner(cipher,contract,LibraryPreflight(cipher,contract,secret=SECRET))


class HistoricalRFI77:
    """Issued drawing, official legacy answer/distribution, six library receipts."""
    def __init__(self):
        with historical_catalog():self.c=make_rfi_practice_fixture()
        c=self.c;self.records=c.rfi_practice_records;self.pid=self.records['project_id']
        self.staff,self.pm,self.reviewer=(c.rfi_practice_persona_people[key]['person_id'] for key in ('staff','pm','reviewer'))
        self.field=c.plugin('field');self.library=c.plugin('library');self.requests=[]
        try:
            # An unrelated native opening journal makes financial preservation
            # nonempty. It is not an RFI impact or a newly adopted obligation.
            self.opening=c.ledger.post(period_id='2026-10',description='Synthetic historical opening equity',
                lines=[{'account':'1000','debit':'500.00'},{'account':'3000','credit':'500.00'}],
                source_type='opening',source_id='synthetic-rfi-upgrade-opening',source_version='1',posted_by=BOOTSTRAP_LOGIN)
            self.rfi=self.field.create_rfi(self.pid,'Historical drain alignment','Which alignment was officially reviewed?',actor=STAFF_LOGIN,
                drawing_revision_ids=[self.records['drawing_revision_id']],document_revision_ids=[self.records['document_revision_id']])
            self.field.draft_response(self.rfi['id'],'Use the original east alignment. Informational impact only.',
                cost_impact='1250.00',schedule_impact_days=3,actor=STAFF_LOGIN)
            response=c.request_approval('field.respond_rfi',self.rfi['id'],actor_role='pm',requested_by=PM_LOGIN)
            c.approve(response['id'],approver=REVIEWER_LOGIN,approver_role='pm')
            self.answer=c.execute(response['id'],actor=PM_LOGIN);self.response_id=response['id']
            self.field.set_distribution_list(self.rfi['id'],[self.records['allowed_recipients'][0]],actor=PM_LOGIN)
            distribution=c.request_approval('field.distribute_rfi',self.rfi['id'],actor_role='pm',requested_by=PM_LOGIN)
            c.approve(distribution['id'],approver=REVIEWER_LOGIN,approver_role='pm')
            self.distribution=c.execute(distribution['id'],actor=PM_LOGIN);self.distribution_id=distribution['id']
            self.official_response=self.field.rfi(self.rfi['id'])['response']
            self.runner=library_runner(c)
            created=self.act(self.pm,'library.create',self.pid,{'kind':'contract_clause','title':'Historical authored reference',
                'text':'Synthetic authored clause.\r\n  Preserve UTF-8 — café 🏗.\n','sourceLocator':'Historical editor / clause one'})
            revised=self.act(self.pm,'library.revise',created['entryId'],{'previousRevisionId':created['revisionId'],
                'text':'Synthetic authored revision two.\n  Exact spacing remains.\n','sourceLocator':'Historical editor / clause two',
                'changeReason':'Synthetic authored clarification'})
            plan=self.act(self.pm,'library.prepareReference',revised['revisionId'],
                {'targetLocator':'Project specification / draft reference','purpose':'Internal authored reference preservation'})
            approval=self.act(self.pm,'library.requestAdoption',plan['planId'])
            self.act(self.reviewer,'library.approveAdoption',approval['approvalId'])
            adopted=self.act(self.pm,'library.applyAdoption',approval['approvalId'])
            self.reference_id=adopted['referenceId'];self.entry_id=created['entryId']
        except BaseException:
            c.db.close();raise

    def act(self,person,action,resource,body=None):
        body={} if body is None else body
        review=self.runner.preflight.review(person,action,resource,body)
        if not review['allowed']:raise AssertionError(review)
        request=(person,action,resource,{**body,'fingerprint':review['fingerprint']},str(uuid4()),review['resourceVersion'])
        response=self.runner.run(*request[:4],repeatability_key=request[4],if_match=request[5])
        self.requests.append((request,response));return response['result']


def storage_snapshot(db):
    """All old rows and declared SQL, with row order independent of query plans."""
    objects=db.query("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' AND sql IS NOT NULL ORDER BY type,name")
    names=[row['name'] for row in objects if row['type']=='table']
    return {'objects':objects,'tables':{name:sorted(db.query('SELECT * FROM "'+name.replace('"','""')+'"'),key=canonical_json) for name in names}}

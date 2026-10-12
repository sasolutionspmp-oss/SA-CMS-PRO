"""Supplier progress bills: cumulative certification, retainage, stored materials.

Posting rule (fixture policy ``cipher-posting-rules/1``, controller-approved
for the synthetic prototype only):

* transfer of stored material to installed:  Dr project cost / Cr stored asset
* new installed cost this period:            Dr project cost
* newly stored eligible material:            Dr stored asset
* amount currently payable:                  Cr accounts payable
* retainage withheld this period:            Cr retainage payable

Controls:

* Stored material is never billed twice: a lot's remaining balance is reduced by
  every transfer and the transferred value appears inside cumulative installed.
* Stored-material eligibility: a lot binds the CURRENT revision of a
  ``stored_material_evidence`` document on the commitment's own project
  (title/control, insurance, location, delivery) and names its storage location.
  One evidence document supports one lot, for good: a newer revision of that
  document re-confirms the same lot, it never backs a second one, and evidence
  content already backing a lot cannot back another through a twin document.
  When the evidence document later gains a newer revision the lot is flagged
  (``eligibility_confirmation_required``) and is frozen: it cannot be
  transferred and, if it was never billed, it is left out of new bills until
  ``confirm_lot_evidence`` binds it to the current revision.  A lot that was
  never billed can be withdrawn (``withdraw_stored_material``).
* Per-line cap: on every SOV line, cumulative installed plus remaining stored
  value never exceeds the line amount.  Every lot with remaining value counts,
  including frozen lots left out of the bill, both when material is stored and
  when a bill is certified; deductive changes check it in ``commitments``.
* The ``bill.approve`` manifest binds the exact journal lines the posting will
  write (``journal_preview``) together with the commitment version, SOV hash,
  retainage rate, lot evidence state, legal entity and currency.  Posting
  re-derives the preview and refuses to post anything the approval did not show.
* Retainage is released only for a closed commitment with its closure record
  (``commitments``); the manifest binds the commitment status, version and
  closure, and the release re-checks them inside its transaction.  An approval
  takes effect once: an approval already carried by a journal (for example a
  release that was later reversed) never posts again.
* Retainage payable (2050) and stored materials (1300) have their own
  subledgers (``retainage_open_items``, ``stored_material_items``) reconciled
  to the control accounts.  In the AP subledger, released retainage and its
  payments are matched per supplier and project, exactly as ``payments`` scopes
  a retainage payment.
* Storage guards (schema entry ``bills_controls_hardening``): a bill is born a
  draft and its status moves only draft -> posted (with its approved journal) or
  void, and posted <-> paid; lines and transfers are never added to a bill that
  is no longer a draft; a lot's evidence binding, location, remaining value,
  billing history and withdrawal follow the rules above.

Supplier invoices, credit notes and corrections (schema entry
``bills_invoices_credits_corrections``):

* Supplier invoice link.  ``ap_intake`` (the supplier-invoice intake plugin) matches a
  received supplier invoice to a certified (draft or posted) bill and, inside its own
  approval-bound ``ap_intake.match_invoice`` execution, calls
  ``attach_supplier_invoice``: the bill records the invoice id, number, invoice date,
  due date, content hash and evidence hash, read from the invoice record (never from the
  caller).  Schema guards admit those columns only whole, only on a draft or posted bill,
  only with a consumed match approval for that invoice that never attached anything
  before (not even to this bill), only when the invoice record is matched to this bill
  under that approval with exactly those facts (``ap_intake``'s integrity entry), only
  while no other live bill carries the invoice, and only with the audit entry
  ``attach_supplier_invoice`` writes.  Once a bill carries an invoice, ``bill.approve``
  binds it, and both the manifest and posting refuse (``BillIneligible``, a
  ``StaleApprovalError``) when the invoice was revised or rejected after it was attached,
  its record no longer shows the attached number, dates or match, or its document gained
  a newer revision: an approval granted before the invoice was replaced goes stale.  A
  link to a rejected or since-revised invoice no longer holds: another matched invoice may
  replace it.  AP open items carry the due date (the supplier invoice's, else the bill's
  created date plus 30 days), the invoice number and whether the link still holds.
* Supplier credit notes (core operation ``bill.credit_note``; subject: a credit-note
  draft from ``prepare_credit_note`` on a POSTED bill, bound to the current revision of
  a ``supplier_credit_note`` document on the bill's project; one document backs one
  credit note).  The credit never exceeds the bill's open payable (amount due less
  accepted/settled payments less earlier credits; drafts reserve their amount), is
  refused while a payment of the bill is in flight, and posts Dr 2000 / Cr 5000 on the
  bill's project and supplier (source ``supplier_credit_note``) into the open period
  named at execution (else the latest open one, never before the bill's period).  The
  manifest binds the bill hash, the open amount, the credit and the evidence; a later
  payment or credit makes it stale.  ``journal.reverse`` refuses credit-note journals.
  A credited bill is paid its open payable, never its amount due: posting the credit
  invalidates open payment approvals on the bill, and storage guards (schema entry
  ``bills_invoice_link_and_credit_payment_guards``) refuse a ``payment.release`` approval
  or a released payment intent for a bill carrying a posted credit note unless it is for
  exactly ``open_payable`` -- so the supplier is never paid the credit, and AP never goes
  negative.
* Posted-bill correction (core operation ``bill.correct``; subject: the posted bill;
  ``prepare_correction`` records the reason first).  Allowed only for the commitment's
  latest bill while it is unpaid (no payment intent other than failed, returned or
  canceled) and carries no credit note.  Executing reverses every journal of the bill
  through ``Ledger.reverse`` into the open period named at execution (else the latest
  open one; approval id and reason recorded on each reversal), marks the bill
  ``corrected`` (final), puts the stored material it transferred back on its lots and
  un-bills the lots it billed first, so a replacement bill certifies from the previous
  bill's progress; retainage and stored-material subledgers still reconcile.
"""
from __future__ import annotations

import datetime as _dt
from decimal import Decimal
from typing import Any

from ..core.approvals import Approvals, StaleApprovalError, build_manifest
from ..core.audit import Audit
from ..core.db import Database, register_schema_version
from ..core.ids import canonical_json, hash_json, loads, new_id, utcnow_iso
from ..core.money import ZERO, D, MoneyError, fmt, money, pct, total
from .commitments import Commitments
from .ledger import Ledger, PeriodNotOpen, lines_fingerprint

POSTING_RULE = "cipher-posting-rules/1"

# Append-only schema entry for the stored-material and bill controls.  Never edit
# these statements once applied; add a new uniquely named entry instead.
BILLS_SCHEMA_NAME = "bills_stored_material_controls"
BILLS_SCHEMA_STATEMENTS = [
    "ALTER TABLE stored_material_lots ADD COLUMN evidence_document_id TEXT REFERENCES documents(id)",
    "ALTER TABLE stored_material_lots ADD COLUMN evidence_revision_id TEXT REFERENCES document_revisions(id)",
    "ALTER TABLE stored_material_lots ADD COLUMN evidence_confirmed_at TEXT",
    "ALTER TABLE stored_material_lots ADD COLUMN evidence_confirmed_by TEXT",
    "ALTER TABLE stored_material_lots ADD COLUMN billed_bill_id TEXT REFERENCES bills(id)",
    "ALTER TABLE bills ADD COLUMN retainage_rate TEXT",
    "ALTER TABLE bills ADD COLUMN sov_hash TEXT",
    # one evidence revision supports one lot: the same delivery cannot be claimed twice
    "CREATE UNIQUE INDEX stored_material_lots_one_lot_per_evidence ON stored_material_lots(evidence_revision_id) WHERE evidence_revision_id IS NOT NULL",
    """CREATE TRIGGER stored_material_lots_identity_immutable BEFORE UPDATE OF commitment_id, sov_line_id, eligible_amount, created_at ON stored_material_lots
        WHEN NEW.commitment_id IS NOT OLD.commitment_id OR NEW.sov_line_id IS NOT OLD.sov_line_id
          OR NEW.eligible_amount IS NOT OLD.eligible_amount OR NEW.created_at IS NOT OLD.created_at
        BEGIN SELECT RAISE(ABORT, 'a stored material lot''s commitment, SOV line and eligible amount are immutable'); END""",
    # a posted bill is the source record of its journals: its figures never change afterwards
    """CREATE TRIGGER bills_posted_figures_immutable BEFORE UPDATE ON bills
        WHEN OLD.status IN ('posted','paid') AND (
          NEW.commitment_id IS NOT OLD.commitment_id OR NEW.period_id IS NOT OLD.period_id OR NEW.sequence IS NOT OLD.sequence
          OR NEW.cumulative_installed IS NOT OLD.cumulative_installed OR NEW.cumulative_stored IS NOT OLD.cumulative_stored
          OR NEW.cumulative_gross IS NOT OLD.cumulative_gross OR NEW.cumulative_retainage IS NOT OLD.cumulative_retainage
          OR NEW.cumulative_net IS NOT OLD.cumulative_net OR NEW.prior_net IS NOT OLD.prior_net OR NEW.amount_due IS NOT OLD.amount_due
          OR NEW.retainage_this_period IS NOT OLD.retainage_this_period OR NEW.installed_this_period IS NOT OLD.installed_this_period
          OR NEW.stored_added_this_period IS NOT OLD.stored_added_this_period
          OR NEW.stored_transferred_this_period IS NOT OLD.stored_transferred_this_period
          OR NEW.commitment_version IS NOT OLD.commitment_version OR NEW.content_hash IS NOT OLD.content_hash
          OR NEW.approval_id IS NOT OLD.approval_id OR NEW.journal_id IS NOT OLD.journal_id
          OR NEW.retainage_rate IS NOT OLD.retainage_rate OR NEW.sov_hash IS NOT OLD.sov_hash)
        BEGIN SELECT RAISE(ABORT, 'a posted supplier bill is immutable; correct it by reversal'); END""",
    """CREATE TRIGGER bills_posted_no_delete BEFORE DELETE ON bills WHEN OLD.status != 'draft'
        BEGIN SELECT RAISE(ABORT, 'only draft supplier bills may be removed; void or reverse instead'); END""",
    """CREATE TRIGGER bill_lines_posted_immutable BEFORE UPDATE ON bill_lines WHEN (SELECT status FROM bills WHERE id = OLD.bill_id) IN ('posted','paid')
        BEGIN SELECT RAISE(ABORT, 'lines of a posted supplier bill are immutable'); END""",
    """CREATE TRIGGER bill_lines_posted_no_delete BEFORE DELETE ON bill_lines WHEN (SELECT status FROM bills WHERE id = OLD.bill_id) IN ('posted','paid')
        BEGIN SELECT RAISE(ABORT, 'lines of a posted supplier bill are immutable'); END""",
    """CREATE TRIGGER bill_transfers_posted_immutable BEFORE UPDATE ON bill_transfers WHEN (SELECT status FROM bills WHERE id = OLD.bill_id) IN ('posted','paid')
        BEGIN SELECT RAISE(ABORT, 'stored-material transfers of a posted supplier bill are immutable'); END""",
    """CREATE TRIGGER bill_transfers_posted_no_delete BEFORE DELETE ON bill_transfers WHEN (SELECT status FROM bills WHERE id = OLD.bill_id) IN ('posted','paid')
        BEGIN SELECT RAISE(ABORT, 'stored-material transfers of a posted supplier bill are immutable'); END""",
    # previous-billing history for lots that existed before this entry: the first
    # non-void bill of the commitment certified at or after the lot was recorded
    """UPDATE stored_material_lots SET billed_bill_id = (
        SELECT b.id FROM bills b WHERE b.commitment_id = stored_material_lots.commitment_id AND b.status != 'void'
          AND b.created_at >= stored_material_lots.created_at ORDER BY b.sequence LIMIT 1)""",
]
register_schema_version(BILLS_SCHEMA_NAME, BILLS_SCHEMA_STATEMENTS)

# The document kind that carries stored-material eligibility evidence.
STORED_MATERIAL_EVIDENCE_KIND = "stored_material_evidence"

# The binding every bound lot must satisfy: the current revision of a stored-material
# evidence document on its commitment's project, carrying the lot's evidence hash.
_LOT_BINDING_OK = """EXISTS (
    SELECT 1 FROM document_revisions r JOIN documents d ON d.id = r.document_id JOIN commitments c ON c.id = NEW.commitment_id
     WHERE r.id = NEW.evidence_revision_id AND r.document_id = NEW.evidence_document_id AND r.content_hash = NEW.evidence_hash
       AND d.project_id = c.project_id AND d.kind = 'stored_material_evidence'
       AND r.revision = (SELECT MAX(x.revision) FROM document_revisions x WHERE x.document_id = r.document_id))"""

# Billing history of lots recorded before ``bills_stored_material_controls``.  That
# entry's backfill matched lots to bills by second-resolution timestamps, so a lot
# recorded in the same second as a bill, but after it, was attributed to that bill.
# This repair re-derives it from the audit order (``audit_log.seq`` of the lot's
# ``stored_material.added`` and the bill's ``bill.certified``; the time-ordered ids
# when an entry is missing) and touches only legacy lots (whose recording payload
# has no evidence revision) and legacy bills (certified without a rate/SOV binding):
# under the legacy rules every lot was billed by the first bill certified after it.
LEGACY_BILLING_HISTORY_REPAIR = """UPDATE stored_material_lots SET billed_bill_id = COALESCE(
    (SELECT b.id FROM bills b
      WHERE b.commitment_id = stored_material_lots.commitment_id AND b.status != 'void'
        AND b.retainage_rate IS NULL AND b.sov_hash IS NULL
        AND COALESCE(
              (SELECT MIN(a.seq) FROM audit_log a WHERE a.entity_type = 'bill' AND a.entity_id = b.id AND a.action = 'bill.certified')
                > (SELECT MIN(a.seq) FROM audit_log a WHERE a.entity_type = 'stored_material_lot' AND a.entity_id = stored_material_lots.id
                     AND a.action = 'stored_material.added'),
              substr(b.id, instr(b.id, '_') + 1, 16) > substr(stored_material_lots.id, instr(stored_material_lots.id, '_') + 1, 16))
      ORDER BY b.sequence LIMIT 1),
    CASE WHEN billed_bill_id IN (SELECT id FROM bills WHERE retainage_rate IS NULL AND sov_hash IS NULL) THEN NULL ELSE billed_bill_id END)
  WHERE NOT EXISTS (SELECT 1 FROM audit_log a WHERE a.entity_type = 'stored_material_lot' AND a.entity_id = stored_material_lots.id
                      AND a.action = 'stored_material.added' AND instr(a.payload_json, '"evidence_revision_id"') > 0)"""

# Append-only schema entry for the hardened bill and stored-material controls.  Never
# edit these statements once applied; add a new uniquely named entry instead.
BILLS_HARDENING_SCHEMA_NAME = "bills_controls_hardening"
BILLS_HARDENING_SCHEMA_STATEMENTS = [
    "ALTER TABLE stored_material_lots ADD COLUMN withdrawn_at TEXT",
    "ALTER TABLE stored_material_lots ADD COLUMN withdrawn_by TEXT",
    "ALTER TABLE stored_material_lots ADD COLUMN withdrawal_reason TEXT",
    # runs before the billing-history guard below, which would refuse it
    LEGACY_BILLING_HISTORY_REPAIR,
    # a bill is born a draft; its status moves draft -> posted (with its approved journal) or void, and posted <-> paid
    """CREATE TRIGGER bills_born_draft BEFORE INSERT ON bills
        WHEN NEW.status IS NOT 'draft' OR NEW.approval_id IS NOT NULL OR NEW.journal_id IS NOT NULL
        BEGIN SELECT RAISE(ABORT, 'a supplier bill is certified as a draft'); END""",
    """CREATE TRIGGER bills_status_transitions BEFORE UPDATE OF status ON bills
        WHEN NEW.status IS NOT OLD.status AND NOT (
             (OLD.status IN ('draft','approved') AND NEW.status = 'void')
          OR (OLD.status IN ('draft','approved') AND NEW.status = 'posted' AND NEW.approval_id IS NOT NULL
              AND EXISTS (SELECT 1 FROM journals j WHERE j.id = NEW.journal_id AND j.source_type = 'bill' AND j.source_id = NEW.id AND j.approval_id = NEW.approval_id))
          OR (OLD.status = 'posted' AND NEW.status = 'paid')
          OR (OLD.status = 'paid' AND NEW.status = 'posted'))
        BEGIN SELECT RAISE(ABORT, 'a supplier bill moves only from draft to posted (with its approved journal) or void, and between posted and paid; correct a posted bill by reversal'); END""",
    """CREATE TRIGGER bill_lines_draft_only_insert BEFORE INSERT ON bill_lines WHEN (SELECT status FROM bills WHERE id = NEW.bill_id) IS NOT 'draft'
        BEGIN SELECT RAISE(ABORT, 'lines are added to a supplier bill only while it is a draft'); END""",
    """CREATE TRIGGER bill_transfers_draft_only_insert BEFORE INSERT ON bill_transfers WHEN (SELECT status FROM bills WHERE id = NEW.bill_id) IS NOT 'draft'
        BEGIN SELECT RAISE(ABORT, 'stored-material transfers are added to a supplier bill only while it is a draft'); END""",
    # stored material lots
    f"""CREATE TRIGGER stored_material_lots_insert_guard BEFORE INSERT ON stored_material_lots
        BEGIN SELECT CASE
          WHEN NEW.billed_bill_id IS NOT NULL OR NEW.withdrawn_at IS NOT NULL
            THEN RAISE(ABORT, 'a new stored material lot is neither billed nor withdrawn')
          WHEN NOT (CAST(NEW.eligible_amount AS REAL) > 0) OR NEW.remaining_amount IS NOT NEW.eligible_amount
            THEN RAISE(ABORT, 'a new stored material lot starts with its full, positive eligible amount remaining')
          WHEN (NEW.evidence_revision_id IS NULL) != (NEW.evidence_document_id IS NULL)
            THEN RAISE(ABORT, 'a stored material lot binds an evidence document and its revision together')
          WHEN NEW.evidence_revision_id IS NOT NULL AND trim(COALESCE(NEW.location, '')) = ''
            THEN RAISE(ABORT, 'stored material requires its storage location')
          WHEN NEW.evidence_revision_id IS NOT NULL AND NOT {_LOT_BINDING_OK}
            THEN RAISE(ABORT, 'a stored material lot binds the current revision of a stored_material_evidence document on its own project')
          WHEN NEW.evidence_document_id IS NOT NULL AND EXISTS (SELECT 1 FROM stored_material_lots o WHERE o.evidence_document_id = NEW.evidence_document_id)
            THEN RAISE(ABORT, 'one evidence document supports one stored material lot; the same material cannot be claimed twice')
          WHEN EXISTS (SELECT 1 FROM stored_material_lots o WHERE o.evidence_hash = NEW.evidence_hash AND o.evidence_revision_id IS NOT NULL)
            THEN RAISE(ABORT, 'that evidence content already supports another stored material lot')
        END; END""",
    f"""CREATE TRIGGER stored_material_lots_evidence_binding BEFORE UPDATE OF evidence_revision_id, evidence_document_id, evidence_hash ON stored_material_lots
        WHEN NEW.evidence_revision_id IS NOT OLD.evidence_revision_id OR NEW.evidence_document_id IS NOT OLD.evidence_document_id
          OR NEW.evidence_hash IS NOT OLD.evidence_hash
        BEGIN SELECT CASE
          WHEN NEW.evidence_revision_id IS NULL OR NEW.evidence_document_id IS NULL
            THEN RAISE(ABORT, 'a stored material lot''s evidence binding is never removed')
          WHEN OLD.evidence_document_id IS NOT NULL AND NEW.evidence_document_id IS NOT OLD.evidence_document_id
            THEN RAISE(ABORT, 'a stored material lot stays bound to its own evidence document')
          WHEN NOT {_LOT_BINDING_OK}
            THEN RAISE(ABORT, 'a stored material lot binds the current revision of a stored_material_evidence document on its own project')
          WHEN EXISTS (SELECT 1 FROM stored_material_lots o WHERE o.id != NEW.id AND o.evidence_document_id = NEW.evidence_document_id)
            THEN RAISE(ABORT, 'one evidence document supports one stored material lot; the same material cannot be claimed twice')
          WHEN EXISTS (SELECT 1 FROM stored_material_lots o WHERE o.id != NEW.id AND o.evidence_hash = NEW.evidence_hash AND o.evidence_revision_id IS NOT NULL)
            THEN RAISE(ABORT, 'that evidence content already supports another stored material lot')
          WHEN NOT EXISTS (SELECT 1 FROM audit_log a WHERE a.entity_type = 'stored_material_lot' AND a.entity_id = NEW.id
                             AND a.action = 'stored_material.evidence_confirmed'
                             AND instr(a.payload_json, '"evidence_revision_id":"' || NEW.evidence_revision_id || '"') > 0)
            THEN RAISE(ABORT, 'stored material evidence is re-confirmed only through confirm_lot_evidence, which audits it')
        END; END""",
    """CREATE TRIGGER stored_material_lots_location_fixed BEFORE UPDATE OF location ON stored_material_lots
        WHEN NEW.location IS NOT OLD.location AND (trim(COALESCE(OLD.location, '')) != '' OR trim(COALESCE(NEW.location, '')) = '')
        BEGIN SELECT RAISE(ABORT, 'a stored material lot''s storage location is part of its eligibility evidence: it is recorded once and never blanked'); END""",
    """CREATE TRIGGER stored_material_lots_remaining_bounds BEFORE UPDATE OF remaining_amount ON stored_material_lots
        WHEN NEW.remaining_amount IS NOT OLD.remaining_amount AND (
          NEW.remaining_amount NOT GLOB '[0-9]*.[0-9][0-9]' OR CAST(NEW.remaining_amount AS REAL) > CAST(NEW.eligible_amount AS REAL))
        BEGIN SELECT RAISE(ABORT, 'a lot''s remaining stored value stays between 0.00 and its eligible amount'); END""",
    """CREATE TRIGGER stored_material_lots_billing_history BEFORE UPDATE OF billed_bill_id ON stored_material_lots
        WHEN NEW.billed_bill_id IS NOT OLD.billed_bill_id
        BEGIN SELECT CASE
          WHEN NEW.billed_bill_id IS NOT NULL AND (SELECT status FROM bills WHERE id = NEW.billed_bill_id AND commitment_id = NEW.commitment_id) IS NOT 'draft'
            THEN RAISE(ABORT, 'a lot is first billed by a draft bill of its own commitment')
          WHEN OLD.billed_bill_id IS NOT NULL AND (SELECT status FROM bills WHERE id = OLD.billed_bill_id) IS NOT 'draft'
            THEN RAISE(ABORT, 'a lot''s billing history on a posted bill is permanent')
        END; END""",
    """CREATE TRIGGER stored_material_lots_withdrawal BEFORE UPDATE OF withdrawn_at, withdrawn_by, withdrawal_reason ON stored_material_lots
        WHEN NEW.withdrawn_at IS NOT OLD.withdrawn_at OR NEW.withdrawn_by IS NOT OLD.withdrawn_by OR NEW.withdrawal_reason IS NOT OLD.withdrawal_reason
        BEGIN SELECT CASE
          WHEN NEW.withdrawn_at IS NULL OR trim(COALESCE(NEW.withdrawn_by, '')) = '' OR trim(COALESCE(NEW.withdrawal_reason, '')) = ''
            THEN RAISE(ABORT, 'a withdrawal records when, by whom and why the lot was withdrawn')
          WHEN OLD.billed_bill_id IS NOT NULL OR NEW.billed_bill_id IS NOT NULL
            THEN RAISE(ABORT, 'only stored material that was never billed is withdrawn; billed material leaves by transfer to installed')
          WHEN NEW.remaining_amount IS NOT '0.00'
            THEN RAISE(ABORT, 'a withdrawn lot carries no remaining stored value')
        END; END""",
    """CREATE TRIGGER stored_material_lots_withdrawn_final BEFORE UPDATE ON stored_material_lots WHEN OLD.withdrawn_at IS NOT NULL
        BEGIN SELECT RAISE(ABORT, 'a withdrawn stored material lot is final'); END""",
    """CREATE TRIGGER stored_material_lots_no_delete BEFORE DELETE ON stored_material_lots
        BEGIN SELECT RAISE(ABORT, 'stored material lots are never deleted; withdraw a lot that was never billed'); END""",
]
register_schema_version(BILLS_HARDENING_SCHEMA_NAME, BILLS_HARDENING_SCHEMA_STATEMENTS)

# Operations this core domain owns (handles / manifest_for / apply).
OP_CREDIT_NOTE = "bill.credit_note"
OP_CORRECT = "bill.correct"
OWNED_OPERATIONS = (OP_CREDIT_NOTE, OP_CORRECT)
# The ap_intake operation whose consumed approval attaches a supplier invoice to a bill.
MATCH_OPERATION = "ap_intake.match_invoice"
SUPPLIER_INVOICES_TABLE = "ap_invoices"
CREDIT_NOTE_SOURCE = "supplier_credit_note"
CREDIT_NOTE_SUBJECT = "supplier_credit_note"
CREDIT_NOTE_EVIDENCE_KIND = "supplier_credit_note"
DEFAULT_DUE_DAYS = 30
MAX_TEXT_LENGTH = 500
# payment intents that are on their way to the supplier, or that paid the bill
IN_FLIGHT_INTENT_STATES = ("approved", "queued", "submitted", "outcome_unknown")
PAID_INTENT_STATES = ("accepted", "settled")
UNPAID_FINAL_INTENT_STATES = ("failed", "returned", "canceled")

_BILL_COLUMNS_V2 = (
    "id, commitment_id, period_id, sequence, status, cumulative_installed, cumulative_stored, cumulative_gross, cumulative_retainage, "
    "cumulative_net, prior_net, amount_due, retainage_this_period, installed_this_period, stored_added_this_period, "
    "stored_transferred_this_period, commitment_version, content_hash, approval_id, journal_id, created_at, retainage_rate, sov_hash"
)
_POSITIVE_MONEY_TEXT = ("(amount GLOB '[0-9]*.[0-9][0-9]' AND NOT amount GLOB '*[^0-9.]*' AND length(amount) - length(replace(amount, '.', '')) = 1 "
                        "AND NOT amount GLOB '0[0-9]*' AND amount <> '0.00' AND length(amount) <= 16)")
_LINES_FROZEN = "('posted','paid','corrected')"

# Append-only schema entry for supplier-invoice links, supplier credit notes and governed
# posted-bill corrections.  SQLite cannot widen a CHECK constraint, so the bills table is
# rebuilt to admit the final status 'corrected': every row is copied by the INSERT ... SELECT
# (foreign keys are deferred while the table is swapped, so the lines, transfers, lots and
# payment intents that reference bills are not refused mid-swap) and every trigger that lived
# on the old table is recreated (the posted-figures and lines guards also cover a corrected
# bill).  Note: the entry switches ``defer_foreign_keys`` OFF again before its transaction
# commits, and switching it off discards SQLite's count of deferred violations, so the
# commit itself does NOT re-check the references.  The rebuild is safe because it copies
# every row with every id unchanged (the upgrade test runs ``PRAGMA foreign_key_check``
# afterwards); a future rebuild that could drop or re-key a row must check references
# itself.  Never edit these statements once applied (this comment is not part of the
# entry); add a new uniquely named entry instead.
BILLS_LIFECYCLE_SCHEMA_NAME = "bills_invoices_credits_corrections"
BILLS_LIFECYCLE_SCHEMA_STATEMENTS = [
    "PRAGMA defer_foreign_keys = ON",
    "CREATE TABLE bills_lifecycle_rebuild AS SELECT * FROM bills",
    "DROP TABLE bills",
    """CREATE TABLE bills (
        id TEXT PRIMARY KEY,
        commitment_id TEXT NOT NULL REFERENCES commitments(id),
        period_id TEXT NOT NULL REFERENCES periods(id),
        sequence INTEGER NOT NULL,
        status TEXT NOT NULL CHECK (status IN ('draft','approved','posted','paid','void','corrected')),
        cumulative_installed TEXT NOT NULL,
        cumulative_stored TEXT NOT NULL,
        cumulative_gross TEXT NOT NULL,
        cumulative_retainage TEXT NOT NULL,
        cumulative_net TEXT NOT NULL,
        prior_net TEXT NOT NULL,
        amount_due TEXT NOT NULL,
        retainage_this_period TEXT NOT NULL,
        installed_this_period TEXT NOT NULL,
        stored_added_this_period TEXT NOT NULL,
        stored_transferred_this_period TEXT NOT NULL,
        commitment_version INTEGER NOT NULL,
        content_hash TEXT NOT NULL,
        approval_id TEXT REFERENCES approvals(id),
        journal_id TEXT REFERENCES journals(id),
        created_at TEXT NOT NULL,
        retainage_rate TEXT,
        sov_hash TEXT,
        supplier_invoice_id TEXT,
        supplier_invoice_number TEXT,
        invoice_date TEXT,
        due_date TEXT,
        supplier_invoice_hash TEXT,
        supplier_invoice_evidence_hash TEXT,
        supplier_invoice_approval_id TEXT REFERENCES approvals(id),
        correction_id TEXT REFERENCES bill_corrections(id),
        corrected_at TEXT,
        UNIQUE (commitment_id, sequence),
        CHECK ((status = 'corrected') = (correction_id IS NOT NULL AND corrected_at IS NOT NULL))
    )""",
    # created before the copy: inserting into bills resolves its foreign key to bill_corrections
    """CREATE TABLE bill_corrections (
        id TEXT PRIMARY KEY,
        bill_id TEXT NOT NULL REFERENCES bills(id),
        reason TEXT NOT NULL CHECK (length(trim(reason)) > 0),
        status TEXT NOT NULL CHECK (status IN ('pending','executed','cancelled')),
        requested_by TEXT NOT NULL CHECK (length(trim(requested_by)) > 0),
        requested_at TEXT NOT NULL,
        approval_id TEXT UNIQUE REFERENCES approvals(id),
        period_id TEXT REFERENCES periods(id),
        reversal_journals_json TEXT,
        resolved_by TEXT,
        resolved_at TEXT,
        resolution_note TEXT NOT NULL DEFAULT ''
    )""",
    "CREATE UNIQUE INDEX bill_corrections_one_pending ON bill_corrections(bill_id) WHERE status = 'pending'",
    "CREATE UNIQUE INDEX bill_corrections_one_executed ON bill_corrections(bill_id) WHERE status = 'executed'",
    f"INSERT INTO bills ({_BILL_COLUMNS_V2}) SELECT {_BILL_COLUMNS_V2} FROM bills_lifecycle_rebuild",
    "DROP TABLE bills_lifecycle_rebuild",
    "PRAGMA defer_foreign_keys = OFF",
    f"""CREATE TABLE bill_credit_notes (
        id TEXT PRIMARY KEY,
        bill_id TEXT NOT NULL REFERENCES bills(id),
        amount TEXT NOT NULL CHECK {_POSITIVE_MONEY_TEXT},
        reason TEXT NOT NULL CHECK (length(trim(reason)) > 0),
        evidence_hash TEXT NOT NULL CHECK (length(trim(evidence_hash)) > 0),
        evidence_document_id TEXT NOT NULL REFERENCES documents(id),
        evidence_revision_id TEXT NOT NULL REFERENCES document_revisions(id),
        status TEXT NOT NULL CHECK (status IN ('draft','posted','cancelled')),
        created_by TEXT NOT NULL CHECK (length(trim(created_by)) > 0),
        created_at TEXT NOT NULL,
        approval_id TEXT UNIQUE REFERENCES approvals(id),
        journal_id TEXT UNIQUE REFERENCES journals(id),
        period_id TEXT REFERENCES periods(id),
        posted_by TEXT,
        posted_at TEXT,
        cancelled_by TEXT,
        cancelled_at TEXT,
        cancel_reason TEXT
    )""",
    "CREATE INDEX bill_credit_notes_by_bill ON bill_credit_notes(bill_id)",
    "CREATE UNIQUE INDEX bill_credit_notes_one_per_document ON bill_credit_notes(evidence_document_id) WHERE status != 'cancelled'",
    # ---- guards on the rebuilt bills table (the old table's triggers went with it) ----
    """CREATE TRIGGER bills_posted_figures_immutable BEFORE UPDATE ON bills
        WHEN OLD.status IN ('posted','paid','corrected') AND (
          NEW.commitment_id IS NOT OLD.commitment_id OR NEW.period_id IS NOT OLD.period_id OR NEW.sequence IS NOT OLD.sequence
          OR NEW.cumulative_installed IS NOT OLD.cumulative_installed OR NEW.cumulative_stored IS NOT OLD.cumulative_stored
          OR NEW.cumulative_gross IS NOT OLD.cumulative_gross OR NEW.cumulative_retainage IS NOT OLD.cumulative_retainage
          OR NEW.cumulative_net IS NOT OLD.cumulative_net OR NEW.prior_net IS NOT OLD.prior_net OR NEW.amount_due IS NOT OLD.amount_due
          OR NEW.retainage_this_period IS NOT OLD.retainage_this_period OR NEW.installed_this_period IS NOT OLD.installed_this_period
          OR NEW.stored_added_this_period IS NOT OLD.stored_added_this_period
          OR NEW.stored_transferred_this_period IS NOT OLD.stored_transferred_this_period
          OR NEW.commitment_version IS NOT OLD.commitment_version OR NEW.content_hash IS NOT OLD.content_hash
          OR NEW.approval_id IS NOT OLD.approval_id OR NEW.journal_id IS NOT OLD.journal_id
          OR NEW.retainage_rate IS NOT OLD.retainage_rate OR NEW.sov_hash IS NOT OLD.sov_hash OR NEW.created_at IS NOT OLD.created_at)
        BEGIN SELECT RAISE(ABORT, 'a posted supplier bill is immutable; correct it by reversal'); END""",
    """CREATE TRIGGER bills_posted_no_delete BEFORE DELETE ON bills WHEN OLD.status != 'draft'
        BEGIN SELECT RAISE(ABORT, 'only draft supplier bills may be removed; void or reverse instead'); END""",
    """CREATE TRIGGER bills_born_draft BEFORE INSERT ON bills
        WHEN NEW.status IS NOT 'draft' OR NEW.approval_id IS NOT NULL OR NEW.journal_id IS NOT NULL
          OR NEW.supplier_invoice_id IS NOT NULL OR NEW.supplier_invoice_number IS NOT NULL OR NEW.invoice_date IS NOT NULL OR NEW.due_date IS NOT NULL
          OR NEW.supplier_invoice_hash IS NOT NULL OR NEW.supplier_invoice_evidence_hash IS NOT NULL OR NEW.supplier_invoice_approval_id IS NOT NULL
          OR NEW.correction_id IS NOT NULL OR NEW.corrected_at IS NOT NULL
        BEGIN SELECT RAISE(ABORT, 'a supplier bill is certified as a draft, with no supplier invoice or correction attached'); END""",
    """CREATE TRIGGER bills_status_transitions BEFORE UPDATE OF status ON bills
        WHEN NEW.status IS NOT OLD.status AND NOT (
             (OLD.status IN ('draft','approved') AND NEW.status = 'void')
          OR (OLD.status IN ('draft','approved') AND NEW.status = 'posted' AND NEW.approval_id IS NOT NULL
              AND EXISTS (SELECT 1 FROM journals j WHERE j.id = NEW.journal_id AND j.source_type = 'bill' AND j.source_id = NEW.id AND j.approval_id = NEW.approval_id))
          OR (OLD.status = 'posted' AND NEW.status = 'paid')
          OR (OLD.status = 'paid' AND NEW.status = 'posted')
          OR (OLD.status = 'posted' AND NEW.status = 'corrected' AND NEW.correction_id IS NOT NULL AND NEW.corrected_at IS NOT NULL
              AND EXISTS (SELECT 1 FROM bill_corrections k JOIN approvals a ON a.id = k.approval_id
                           WHERE k.id = NEW.correction_id AND k.bill_id = NEW.id AND k.status = 'executed'
                             AND a.status = 'consumed' AND a.operation = 'bill.correct' AND a.subject_id = NEW.id)
              AND EXISTS (SELECT 1 FROM journals j WHERE j.source_type = 'bill' AND j.source_id = NEW.id AND j.reversal_of IS NULL)
              AND NOT EXISTS (SELECT 1 FROM journals j WHERE j.source_type = 'bill' AND j.source_id = NEW.id AND j.reversal_of IS NULL
                                AND NOT EXISTS (SELECT 1 FROM journals r WHERE r.reversal_of = j.id))))
        BEGIN SELECT RAISE(ABORT, 'a supplier bill moves only from draft to posted (with its approved journal) or void, between posted and paid, and from posted to corrected (every journal reversed under a consumed bill.correct approval); a corrected bill is final'); END""",
    """CREATE TRIGGER bills_correction_recorded_once BEFORE UPDATE OF correction_id, corrected_at ON bills
        WHEN (NEW.correction_id IS NOT OLD.correction_id OR NEW.corrected_at IS NOT OLD.corrected_at)
          AND NOT (OLD.status = 'posted' AND NEW.status = 'corrected')
        BEGIN SELECT RAISE(ABORT, 'a bill records its correction only by the posted -> corrected transition'); END""",
    """CREATE TRIGGER bills_supplier_invoice_attached BEFORE UPDATE OF supplier_invoice_id, supplier_invoice_number, invoice_date, due_date,
            supplier_invoice_hash, supplier_invoice_evidence_hash, supplier_invoice_approval_id ON bills
        WHEN NEW.supplier_invoice_id IS NOT OLD.supplier_invoice_id OR NEW.supplier_invoice_number IS NOT OLD.supplier_invoice_number
          OR NEW.invoice_date IS NOT OLD.invoice_date OR NEW.due_date IS NOT OLD.due_date OR NEW.supplier_invoice_hash IS NOT OLD.supplier_invoice_hash
          OR NEW.supplier_invoice_evidence_hash IS NOT OLD.supplier_invoice_evidence_hash OR NEW.supplier_invoice_approval_id IS NOT OLD.supplier_invoice_approval_id
        BEGIN SELECT CASE
          WHEN NEW.supplier_invoice_id IS NULL OR NEW.supplier_invoice_number IS NULL OR NEW.invoice_date IS NULL OR NEW.due_date IS NULL
            OR NEW.supplier_invoice_hash IS NULL OR NEW.supplier_invoice_evidence_hash IS NULL OR NEW.supplier_invoice_approval_id IS NULL
            THEN RAISE(ABORT, 'a supplier invoice link is recorded whole and is never removed')
          WHEN OLD.status NOT IN ('draft','posted') OR NEW.status IS NOT OLD.status
            THEN RAISE(ABORT, 'a supplier invoice is attached only to a draft or posted bill')
          WHEN NEW.due_date < NEW.invoice_date
            THEN RAISE(ABORT, 'a supplier invoice falls due on or after its invoice date')
          WHEN NOT EXISTS (SELECT 1 FROM approvals a WHERE a.id = NEW.supplier_invoice_approval_id AND a.status = 'consumed'
                             AND a.operation = 'ap_intake.match_invoice' AND a.subject_id = NEW.supplier_invoice_id)
            THEN RAISE(ABORT, 'a supplier invoice is attached only by its consumed ap_intake.match_invoice approval')
          WHEN EXISTS (SELECT 1 FROM bills o WHERE o.id <> NEW.id AND o.supplier_invoice_approval_id = NEW.supplier_invoice_approval_id)
            THEN RAISE(ABORT, 'that match approval already attached a supplier invoice to another bill')
          WHEN NOT EXISTS (SELECT 1 FROM audit_log g WHERE g.entity_type = 'bill' AND g.entity_id = NEW.id AND g.action = 'bill.supplier_invoice_attached'
                             AND instr(g.payload_json, '"approval_id":"' || NEW.supplier_invoice_approval_id || '"') > 0
                             AND instr(g.payload_json, '"supplier_invoice_id":"' || NEW.supplier_invoice_id || '"') > 0
                             AND instr(g.payload_json, '"supplier_invoice_number":"' || NEW.supplier_invoice_number || '"') > 0
                             AND instr(g.payload_json, '"invoice_date":"' || NEW.invoice_date || '"') > 0
                             AND instr(g.payload_json, '"due_date":"' || NEW.due_date || '"') > 0
                             AND instr(g.payload_json, '"supplier_invoice_hash":"' || NEW.supplier_invoice_hash || '"') > 0
                             AND instr(g.payload_json, '"supplier_invoice_evidence_hash":"' || NEW.supplier_invoice_evidence_hash || '"') > 0)
            THEN RAISE(ABORT, 'a supplier invoice is attached only through Bills.attach_supplier_invoice, which audits every field it links')
        END; END""",
    # ---- lines, transfers and lots of a corrected bill ----
    "DROP TRIGGER IF EXISTS bill_lines_posted_immutable",
    f"""CREATE TRIGGER bill_lines_posted_immutable BEFORE UPDATE ON bill_lines WHEN (SELECT status FROM bills WHERE id = OLD.bill_id) IN {_LINES_FROZEN}
        BEGIN SELECT RAISE(ABORT, 'lines of a posted supplier bill are immutable'); END""",
    "DROP TRIGGER IF EXISTS bill_lines_posted_no_delete",
    f"""CREATE TRIGGER bill_lines_posted_no_delete BEFORE DELETE ON bill_lines WHEN (SELECT status FROM bills WHERE id = OLD.bill_id) IN {_LINES_FROZEN}
        BEGIN SELECT RAISE(ABORT, 'lines of a posted supplier bill are immutable'); END""",
    "DROP TRIGGER IF EXISTS bill_transfers_posted_immutable",
    f"""CREATE TRIGGER bill_transfers_posted_immutable BEFORE UPDATE ON bill_transfers WHEN (SELECT status FROM bills WHERE id = OLD.bill_id) IN {_LINES_FROZEN}
        BEGIN SELECT RAISE(ABORT, 'stored-material transfers of a posted supplier bill are immutable'); END""",
    "DROP TRIGGER IF EXISTS bill_transfers_posted_no_delete",
    f"""CREATE TRIGGER bill_transfers_posted_no_delete BEFORE DELETE ON bill_transfers WHEN (SELECT status FROM bills WHERE id = OLD.bill_id) IN {_LINES_FROZEN}
        BEGIN SELECT RAISE(ABORT, 'stored-material transfers of a posted supplier bill are immutable'); END""",
    # a lot first billed by a bill that was corrected is billed again by the replacement
    "DROP TRIGGER IF EXISTS stored_material_lots_billing_history",
    """CREATE TRIGGER stored_material_lots_billing_history BEFORE UPDATE OF billed_bill_id ON stored_material_lots
        WHEN NEW.billed_bill_id IS NOT OLD.billed_bill_id
        BEGIN SELECT CASE
          WHEN NEW.billed_bill_id IS NOT NULL AND (SELECT status FROM bills WHERE id = NEW.billed_bill_id AND commitment_id = NEW.commitment_id) IS NOT 'draft'
            THEN RAISE(ABORT, 'a lot is first billed by a draft bill of its own commitment')
          WHEN OLD.billed_bill_id IS NOT NULL AND COALESCE((SELECT status FROM bills WHERE id = OLD.billed_bill_id), '') NOT IN ('draft','corrected')
            THEN RAISE(ABORT, 'a lot''s billing history on a posted bill is permanent')
        END; END""",
    # ---- correction requests ----
    """CREATE TRIGGER bill_corrections_born_pending BEFORE INSERT ON bill_corrections
        BEGIN SELECT CASE
          WHEN EXISTS (SELECT 1 FROM bill_corrections WHERE id = NEW.id)
            THEN RAISE(ABORT, 'bill correction requests are append-only: a request id is never reused or replaced')
          WHEN EXISTS (SELECT 1 FROM bill_corrections WHERE bill_id = NEW.bill_id AND status = 'pending')
            THEN RAISE(ABORT, 'that bill already has a pending correction request')
          WHEN NEW.status IS NOT 'pending' OR NEW.approval_id IS NOT NULL OR NEW.period_id IS NOT NULL OR NEW.reversal_journals_json IS NOT NULL
            OR NEW.resolved_by IS NOT NULL OR NEW.resolved_at IS NOT NULL
            THEN RAISE(ABORT, 'a bill correction request starts pending, with no approval, period or reversal')
          WHEN (SELECT status FROM bills WHERE id = NEW.bill_id) IS NOT 'posted'
            THEN RAISE(ABORT, 'a correction is requested only for a posted supplier bill')
        END; END""",
    """CREATE TRIGGER bill_corrections_resolve_once BEFORE UPDATE ON bill_corrections
        WHEN OLD.status <> 'pending' OR NEW.status = 'pending' OR NEW.id IS NOT OLD.id OR NEW.bill_id IS NOT OLD.bill_id OR NEW.reason IS NOT OLD.reason
          OR NEW.requested_by IS NOT OLD.requested_by OR NEW.requested_at IS NOT OLD.requested_at
        BEGIN SELECT RAISE(ABORT, 'bill correction requests are immutable once resolved; only pending -> executed or cancelled is allowed'); END""",
    """CREATE TRIGGER bill_corrections_executed_link BEFORE UPDATE ON bill_corrections
        WHEN NEW.status = 'executed' AND (NEW.approval_id IS NULL OR NEW.period_id IS NULL OR NEW.reversal_journals_json IS NULL
          OR NOT EXISTS (SELECT 1 FROM approvals a WHERE a.id = NEW.approval_id AND a.status = 'consumed' AND a.operation = 'bill.correct' AND a.subject_id = NEW.bill_id))
        BEGIN SELECT RAISE(ABORT, 'an executed bill correction carries its consumed bill.correct approval, its period and its reversal journals'); END""",
    "CREATE TRIGGER bill_corrections_no_delete BEFORE DELETE ON bill_corrections BEGIN SELECT RAISE(ABORT, 'bill correction requests are append-only'); END",
    # ---- supplier credit notes ----
    """CREATE TRIGGER bill_credit_notes_born_draft BEFORE INSERT ON bill_credit_notes
        BEGIN SELECT CASE
          WHEN EXISTS (SELECT 1 FROM bill_credit_notes WHERE id = NEW.id)
            THEN RAISE(ABORT, 'supplier credit notes are never replaced: that credit note id already exists')
          WHEN EXISTS (SELECT 1 FROM bill_credit_notes WHERE evidence_document_id = NEW.evidence_document_id AND status != 'cancelled')
            THEN RAISE(ABORT, 'that credit note document already supports another supplier credit note')
          WHEN NEW.status IS NOT 'draft' OR NEW.approval_id IS NOT NULL OR NEW.journal_id IS NOT NULL OR NEW.period_id IS NOT NULL
            OR NEW.posted_by IS NOT NULL OR NEW.posted_at IS NOT NULL OR NEW.cancelled_by IS NOT NULL OR NEW.cancelled_at IS NOT NULL
            THEN RAISE(ABORT, 'a supplier credit note is prepared as a draft, with no approval, journal or cancellation')
          WHEN (SELECT status FROM bills WHERE id = NEW.bill_id) IS NOT 'posted'
            THEN RAISE(ABORT, 'a supplier credit note is prepared only against a posted bill')
        END; END""",
    """CREATE TRIGGER bill_credit_notes_identity_immutable BEFORE UPDATE ON bill_credit_notes
        WHEN NEW.id IS NOT OLD.id OR NEW.bill_id IS NOT OLD.bill_id OR NEW.amount IS NOT OLD.amount OR NEW.reason IS NOT OLD.reason
          OR NEW.evidence_hash IS NOT OLD.evidence_hash OR NEW.evidence_document_id IS NOT OLD.evidence_document_id
          OR NEW.evidence_revision_id IS NOT OLD.evidence_revision_id OR NEW.created_by IS NOT OLD.created_by OR NEW.created_at IS NOT OLD.created_at
        BEGIN SELECT RAISE(ABORT, 'a supplier credit note''s bill, amount, reason and evidence are immutable; cancel it and prepare another'); END""",
    """CREATE TRIGGER bill_credit_notes_lifecycle BEFORE UPDATE ON bill_credit_notes
        WHEN OLD.status <> 'draft' OR NOT (
             (NEW.status = 'posted' AND NEW.approval_id IS NOT NULL AND NEW.period_id IS NOT NULL AND NEW.posted_by IS NOT NULL AND NEW.posted_at IS NOT NULL
              AND NEW.cancelled_at IS NULL AND NEW.cancelled_by IS NULL
              AND EXISTS (SELECT 1 FROM approvals a WHERE a.id = NEW.approval_id AND a.status = 'consumed' AND a.operation = 'bill.credit_note' AND a.subject_id = NEW.id)
              AND EXISTS (SELECT 1 FROM journals j WHERE j.id = NEW.journal_id AND j.source_type = 'supplier_credit_note' AND j.source_id = NEW.id
                            AND j.approval_id = NEW.approval_id))
          OR (NEW.status = 'cancelled' AND NEW.approval_id IS NULL AND NEW.journal_id IS NULL AND NEW.cancelled_by IS NOT NULL AND NEW.cancelled_at IS NOT NULL
              AND length(trim(COALESCE(NEW.cancel_reason, ''))) > 0))
        BEGIN SELECT RAISE(ABORT, 'a supplier credit note moves once: draft -> posted (with its consumed approval and journal) or draft -> cancelled; posted and cancelled credit notes are final'); END""",
    "CREATE TRIGGER bill_credit_notes_no_delete BEFORE DELETE ON bill_credit_notes BEGIN SELECT RAISE(ABORT, 'supplier credit notes are never deleted'); END",
]
register_schema_version(BILLS_LIFECYCLE_SCHEMA_NAME, BILLS_LIFECYCLE_SCHEMA_STATEMENTS)


def _cents(expr: str) -> str:
    """SQL: a money text column as whole cents (exact for two-decimal amounts far beyond any bill)."""
    return f"CAST(ROUND(CAST({expr} AS REAL) * 100) AS INTEGER)"


def _open_payable_cents(bill: str) -> str:
    """SQL: what a posted bill still owes in cents -- amount due less accepted or settled
    payments less posted supplier credit notes (``Bills.open_payable``; a posted credit note is
    final, so its amount is exactly what its journal took off AP)."""
    return (f"((SELECT {_cents('b.amount_due')} FROM bills b WHERE b.id = {bill})"
            f" - COALESCE((SELECT SUM({_cents('p.amount')}) FROM payment_intents p WHERE p.bill_id = {bill} AND p.status IN ('accepted','settled')), 0)"
            f" - COALESCE((SELECT SUM({_cents('n.amount')}) FROM bill_credit_notes n WHERE n.bill_id = {bill} AND n.status = 'posted'), 0))")


# Append-only schema entry (review follow-up to ``bills_invoices_credits_corrections``; it names
# only tables that entry and the foundation created, so it is registered right after it).
# * A credited bill is paid its open payable, never its full amount due: a ``payment.release``
#   approval for a bill carrying a posted supplier credit note must bind exactly the open
#   payable, and so must a released payment intent for it.  (``payments`` binds the bill's
#   amount due today, so a credited bill is refused at request time rather than overpaid.)
# * A supplier invoice link is attached by a fresh match approval each time (an approval that
#   attached an invoice never re-attaches it, not even to the same bill), and one invoice is
#   attached to at most one live (draft, approved, posted or paid) bill.
BILLS_LINK_PAYMENT_SCHEMA_NAME = "bills_invoice_link_and_credit_payment_guards"
_RELEASE_AMOUNT_CENTS = _cents("json_extract(NEW.manifest_json, '$.amounts.amount')")
BILLS_LINK_PAYMENT_SCHEMA_STATEMENTS = [
    """CREATE TRIGGER bills_supplier_invoice_fresh_approval BEFORE UPDATE OF supplier_invoice_id, supplier_invoice_number, invoice_date, due_date,
            supplier_invoice_hash, supplier_invoice_evidence_hash, supplier_invoice_approval_id ON bills
        WHEN (NEW.supplier_invoice_id IS NOT OLD.supplier_invoice_id OR NEW.supplier_invoice_number IS NOT OLD.supplier_invoice_number
              OR NEW.invoice_date IS NOT OLD.invoice_date OR NEW.due_date IS NOT OLD.due_date OR NEW.supplier_invoice_hash IS NOT OLD.supplier_invoice_hash
              OR NEW.supplier_invoice_evidence_hash IS NOT OLD.supplier_invoice_evidence_hash OR NEW.supplier_invoice_approval_id IS NOT OLD.supplier_invoice_approval_id)
          AND NEW.supplier_invoice_approval_id IS OLD.supplier_invoice_approval_id
        BEGIN SELECT RAISE(ABORT, 'a match approval attaches a supplier invoice once; re-attaching (to any bill) needs its own consumed match approval'); END""",
    """CREATE TRIGGER bills_supplier_invoice_one_live_bill BEFORE UPDATE OF supplier_invoice_id ON bills
        WHEN NEW.supplier_invoice_id IS NOT NULL AND NEW.supplier_invoice_id IS NOT OLD.supplier_invoice_id
          AND EXISTS (SELECT 1 FROM bills o WHERE o.id <> NEW.id AND o.supplier_invoice_id = NEW.supplier_invoice_id
                        AND o.status IN ('draft','approved','posted','paid'))
        BEGIN SELECT RAISE(ABORT, 'a supplier invoice is attached to one live bill at a time; it is already attached to another draft, posted or paid bill'); END""",
    f"""CREATE TRIGGER approvals_credited_bill_release_open_payable BEFORE INSERT ON approvals
        WHEN NEW.operation = 'payment.release'
          AND EXISTS (SELECT 1 FROM bill_credit_notes n WHERE n.bill_id = NEW.subject_id AND n.status = 'posted')
          AND {_RELEASE_AMOUNT_CENTS} IS NOT {_open_payable_cents('NEW.subject_id')}
        BEGIN SELECT RAISE(ABORT, 'a payment release for a bill carrying a posted supplier credit note must be for exactly its open payable (amount due less payments and credits); releasing the amount due would overpay the supplier'); END""",
    f"""CREATE TRIGGER payment_intents_credited_bill_pays_open_payable BEFORE INSERT ON payment_intents
        WHEN NEW.bill_id IS NOT NULL AND NEW.status = 'approved'
          AND EXISTS (SELECT 1 FROM bill_credit_notes n WHERE n.bill_id = NEW.bill_id AND n.status = 'posted')
          AND {_cents('NEW.amount')} IS NOT {_open_payable_cents('NEW.bill_id')}
        BEGIN SELECT RAISE(ABORT, 'a bill carrying a posted supplier credit note is paid exactly its open payable (amount due less payments and credits); this payment would overpay the supplier'); END""",
]
register_schema_version(BILLS_LINK_PAYMENT_SCHEMA_NAME, BILLS_LINK_PAYMENT_SCHEMA_STATEMENTS)
# Every entry this module registers, oldest first (an older workspace lacks a suffix of them).
BILLS_SCHEMA_ENTRIES = (BILLS_SCHEMA_NAME, BILLS_HARDENING_SCHEMA_NAME, BILLS_LIFECYCLE_SCHEMA_NAME, BILLS_LINK_PAYMENT_SCHEMA_NAME)


class BillError(RuntimeError):
    pass


class BillIneligible(BillError, StaleApprovalError):
    """The bill, credit note or attached supplier invoice is not, or no longer, in a state
    the operation applies to.  At request time this refuses; because it is also a
    ``StaleApprovalError``, an approval granted earlier is invalidated by the service when
    execution finds the subject changed (a replaced invoice, a payment, a later bill)."""


def _line(account: str, *, debit: Decimal = ZERO, credit: Decimal = ZERO, project_id: str, party_id: str, memo: str) -> dict[str, Any]:
    return {"account": account, "debit": fmt(debit), "credit": fmt(credit), "project_id": project_id, "party_id": party_id, "memo": memo}


def _plus_days(stamp: str, days: int) -> str:
    """The calendar date ``days`` after the date part of an ISO date or timestamp."""
    return (_dt.date.fromisoformat(stamp[:10]) + _dt.timedelta(days=days)).isoformat()


class Bills:
    def __init__(self, db: Database, audit: Audit, commitments: Commitments, ledger: Ledger):
        self.db = db
        self.audit = audit
        self.commitments = commitments
        self.ledger = ledger
        self.approvals = Approvals(db, audit)
        # a credit note's journal follows its credit-note record: a bare journal.reverse would
        # leave the credit note posted while AP moves, so the governed reversal refuses it
        reversal_owners = getattr(ledger, "reversal_owners", None)
        if isinstance(reversal_owners, dict):
            reversal_owners.setdefault(CREDIT_NOTE_SOURCE, "the bills subledger (bill.credit_note: a posted supplier credit note is final)")

    # ---- shared helpers ------------------------------------------------------ #

    def _scope(self, project_id: str) -> dict[str, str]:
        row = self.db.one("SELECT entity, currency FROM projects WHERE id=?", (project_id,))
        if row is None:
            raise BillError(f"unknown project {project_id}")
        return {"entity": row["entity"], "currency": row["currency"] or "USD"}

    def _approved_manifest(self, approval_id: str, operation: str, subject_id: str) -> dict[str, Any]:
        """The manifest of the approval the executing command has just consumed.
        Posting paths compare what they are about to write with what was approved."""
        row = self.db.one("SELECT operation, subject_id, status, manifest_json FROM approvals WHERE id=?", (approval_id,))
        if row is None:
            raise BillError(f"unknown approval {approval_id}")
        if row["operation"] != operation or row["subject_id"] != subject_id:
            raise BillError(f"approval {approval_id} covers {row['operation']} on {row['subject_id']}, not {operation} on {subject_id}")
        if row["status"] != "consumed":
            raise BillError(f"approval {approval_id} is {row['status']}; it must be consumed by the executing command")
        return loads(row["manifest_json"])

    def _refuse_spent_approval(self, approval_id: str) -> None:
        """An approval takes effect once.  A journal (or bill) that already carries it
        means its effect is on record -- even when that journal was reversed since, a
        new effect needs a new human approval."""
        used = self.db.one("SELECT id FROM journals WHERE approval_id=? ORDER BY id LIMIT 1", (approval_id,))
        if used is not None:
            raise BillError(f"approval {approval_id} already took effect in journal {used['id']}; an approval takes effect once, request a new one")
        used = self.db.one("SELECT id FROM bills WHERE approval_id=? LIMIT 1", (approval_id,))
        if used is not None:
            raise BillError(f"approval {approval_id} already took effect on bill {used['id']}; an approval takes effect once, request a new one")

    # ---- stored materials ------------------------------------------------- #

    def _current_revision(self, document_id: str | None) -> dict[str, Any] | None:
        if not document_id:
            return None
        return self.db.one("SELECT id, document_id, revision, content_hash FROM document_revisions WHERE document_id=? ORDER BY revision DESC LIMIT 1", (document_id,))

    def _resolve_evidence(self, project_id: str, evidence_hash: str, *, revision_id: str | None = None) -> dict[str, Any]:
        """The current revision of a ``stored_material_evidence`` document on
        ``project_id`` whose content hash is ``evidence_hash``.  A superseded
        revision, another project's document, another kind of document (a drawing,
        say) or a hash Cipher never stored are all refused."""
        rows = self.db.query(
            """SELECT r.id, r.document_id, r.revision, r.content_hash, d.project_id, d.kind, d.title
               FROM document_revisions r JOIN documents d ON d.id = r.document_id WHERE r.content_hash=? ORDER BY r.created_at, r.id""",
            (evidence_hash,),
        )
        if revision_id is not None:
            rows = [r for r in rows if r["id"] == revision_id]
            if not rows:
                raise BillError(f"evidence revision {revision_id} does not carry the hash {evidence_hash}")
        if not rows:
            raise BillError("the evidence hash does not match any stored evidence revision; register the title/control, insurance, location and delivery evidence first")
        on_project = [r for r in rows if r["project_id"] == project_id]
        if not on_project:
            raise BillError(f"the evidence belongs to another project; stored material on project {project_id} needs evidence registered on that project")
        evidence = [r for r in on_project if r["kind"] == STORED_MATERIAL_EVIDENCE_KIND]
        if not evidence:
            kinds = ", ".join(sorted({r["kind"] for r in on_project}))
            raise BillError(
                f"the hash belongs to a {kinds} document; stored material is backed only by a '{STORED_MATERIAL_EVIDENCE_KIND}' document "
                "(title/control, insurance, location and delivery)"
            )
        current = [r for r in evidence if (self._current_revision(r["document_id"]) or {}).get("id") == r["id"]]
        if not current:
            r = evidence[-1]
            cur = self._current_revision(r["document_id"])
            raise BillError(
                f"the evidence hash matches superseded revision {r['revision']} of document {r['document_id']} (current revision {cur['revision'] if cur else '?'}); "
                "bind the current revision"
            )
        if len(current) > 1:
            raise BillError("the evidence hash matches the current revision of several evidence documents on this project; pass evidence_revision_id")
        return current[0]

    def _claimed_by(self, conn, rev: dict[str, Any], *, other_than: str | None = None) -> str | None:
        """Why ``rev`` cannot back a lot: its document, the revision itself or its exact
        content already supports another lot (any lot, with or without remaining value)."""
        row = conn.execute(
            """SELECT id, evidence_document_id, evidence_revision_id FROM stored_material_lots
               WHERE (evidence_document_id=? OR evidence_revision_id=? OR (evidence_hash=? AND evidence_revision_id IS NOT NULL)) AND id IS NOT ?
               ORDER BY created_at, id LIMIT 1""",
            (rev["document_id"], rev["id"], rev["content_hash"], other_than),
        ).fetchone()
        if row is None:
            return None
        if row["evidence_document_id"] == rev["document_id"]:
            return (f"evidence document {rev['document_id']} already supports lot {row['id']}; the same material cannot be claimed twice "
                    "(a newer revision of that document re-confirms that lot through confirm_lot_evidence, it never backs another)")
        return f"the content of evidence revision {rev['id']} already supports lot {row['id']}; the same material cannot be claimed twice"

    def _decorate_lot(self, row: dict[str, Any]) -> dict[str, Any]:
        rev_id = row.get("evidence_revision_id")
        current = self._current_revision(row.get("evidence_document_id"))
        if not rev_id:
            status = "unbound"
        elif current is None or current["id"] != rev_id:
            status = "superseded"
        else:
            status = "current"
        needs = status != "current" and money(row["remaining_amount"]) > 0
        row["evidence_status"] = status
        row["evidence_current_revision_id"] = current["id"] if current else None
        row["evidence_current_hash"] = current["content_hash"] if current else None
        row["eligibility_confirmation_required"] = needs
        row["frozen"] = needs  # cannot be transferred or newly billed until re-confirmed
        row["billed"] = row.get("billed_bill_id") is not None
        row["withdrawn"] = row.get("withdrawn_at") is not None
        return row

    def add_stored_material(
        self,
        *,
        commitment_id: str,
        sov_line_id: str,
        description: str,
        eligible_amount: str | Decimal,
        evidence_hash: str,
        location: str = "",
        actor: str,
        evidence_revision_id: str | None = None,
    ) -> dict[str, Any]:
        """Record an eligible stored-material lot.  ``evidence_hash`` must be the
        content hash of the CURRENT revision of a ``stored_material_evidence``
        document on the commitment's project that backs no other lot;
        ``evidence_revision_id`` disambiguates when several current revisions carry
        the same content."""
        amt = money(eligible_amount)
        if amt <= 0:
            raise BillError("stored material must have a positive eligible amount")
        if not isinstance(evidence_hash, str) or not evidence_hash.strip():
            raise BillError("stored material requires title/control/location evidence (hash)")
        if not isinstance(location, str) or not location.strip():
            raise BillError("stored material requires the storage location (title/control/location evidence)")
        if not isinstance(description, str) or not description.strip():
            raise BillError("stored material requires a description")
        lot_id = new_id("lot")
        with self.db.transaction() as conn:
            c = self.commitments.get(commitment_id)
            if c["status"] != "executed":
                raise BillError("stored material applies to executed commitments only")
            line = next((s for s in c["sov"] if s["id"] == sov_line_id), None)
            if line is None:
                raise BillError("SOV line does not belong to this commitment")
            rev = self._resolve_evidence(c["project_id"], evidence_hash.strip(), revision_id=evidence_revision_id)
            taken = self._claimed_by(conn, rev)
            if taken is not None:
                raise BillError(taken)
            claimed = self.commitments.line_billed(sov_line_id)
            if claimed + amt > money(line["amount"]):
                raise BillError(
                    f"SOV line {line['line_no']}: installed plus stored {fmt(claimed)} and this lot {fmt(amt)} would exceed the line value {line['amount']}"
                )
            now = utcnow_iso()
            conn.execute(
                """INSERT INTO stored_material_lots (id, commitment_id, sov_line_id, description, eligible_amount, remaining_amount, evidence_hash, location, created_at,
                   evidence_document_id, evidence_revision_id, evidence_confirmed_at, evidence_confirmed_by) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (lot_id, commitment_id, sov_line_id, description.strip(), fmt(amt), fmt(amt), rev["content_hash"], location.strip(), now,
                 rev["document_id"], rev["id"], now, actor),
            )
            self.audit.record(actor, "stored_material.added", "stored_material_lot", lot_id, {
                "commitment_id": commitment_id, "sov_line_id": sov_line_id, "eligible_amount": fmt(amt), "evidence_hash": rev["content_hash"],
                "evidence_document_id": rev["document_id"], "evidence_revision_id": rev["id"], "location": location.strip(),
            })
        return self.lot(lot_id)

    def confirm_lot_evidence(self, lot_id: str, evidence_hash: str, actor: str, *, location: str | None = None) -> dict[str, Any]:
        """Re-confirm a lot's eligibility against the CURRENT revision of its evidence
        document (or, for a lot recorded before evidence binding existed, against a
        current ``stored_material_evidence`` revision on the commitment's project that
        backs no other lot; such a lot without a storage location must name one).
        Unfreezes the lot.  A lot whose whole balance a draft bill transfers can be
        confirmed too, so that draft can still be approved and posted."""
        if not isinstance(evidence_hash, str) or not evidence_hash.strip():
            raise BillError("confirming stored material requires the current evidence hash")
        if not isinstance(actor, str) or not actor.strip():
            raise BillError("confirming stored material requires an actor")
        if location is not None and (not isinstance(location, str) or not location.strip()):
            raise BillError("a storage location, when given, must be non-empty text")
        evidence_hash = evidence_hash.strip()
        with self.db.transaction() as conn:
            lot = self.lot(lot_id)
            if lot["withdrawn"]:
                raise BillError(f"lot {lot_id} was withdrawn; a withdrawn lot is final")
            c = self.commitments.get(lot["commitment_id"])
            if c["status"] != "executed":
                raise BillError(f"lot {lot_id} belongs to a {c['status']} commitment")
            if lot["evidence_status"] == "current":
                raise BillError(f"lot {lot_id} is already bound to the current evidence revision; nothing to confirm")
            if lot["evidence_document_id"]:
                rev = self._current_revision(lot["evidence_document_id"])
                if rev is None or rev["content_hash"] != evidence_hash:
                    raise BillError(
                        f"the hash does not match the current revision {rev['revision'] if rev else '?'} of evidence document {lot['evidence_document_id']}"
                    )
            else:
                rev = self._resolve_evidence(c["project_id"], evidence_hash)
            taken = self._claimed_by(conn, rev, other_than=lot_id)
            if taken is not None:
                raise BillError(taken)
            recorded = (lot.get("location") or "").strip()
            if location is not None and recorded and location.strip() != recorded:
                raise BillError(f"lot {lot_id} is recorded at {recorded!r}; its storage location is part of its evidence and does not change")
            new_location = recorded or (location.strip() if location else "")
            if not new_location:
                raise BillError(f"lot {lot_id} has no storage location on record; confirm it with its storage location")
            now = utcnow_iso()
            # audited first: the storage guard admits a new binding only with its audit entry
            self.audit.record(actor, "stored_material.evidence_confirmed", "stored_material_lot", lot_id, {
                "previous_revision_id": lot["evidence_revision_id"], "evidence_document_id": rev["document_id"], "evidence_revision_id": rev["id"],
                "evidence_hash": rev["content_hash"], "remaining_amount": lot["remaining_amount"], "location": new_location,
            })
            conn.execute(
                """UPDATE stored_material_lots SET evidence_document_id=?, evidence_revision_id=?, evidence_hash=?, evidence_confirmed_at=?, evidence_confirmed_by=?,
                   location=CASE WHEN trim(COALESCE(location, '')) = '' THEN ? ELSE location END WHERE id=?""",
                (rev["document_id"], rev["id"], rev["content_hash"], now, actor, new_location, lot_id),
            )
        return self.lot(lot_id)

    def withdraw_stored_material(self, lot_id: str, *, actor: str, reason: str) -> dict[str, Any]:
        """Withdraw a lot that was never billed (for example material whose evidence
        cannot be re-confirmed, or that left the site).  Nothing was posted for it,
        so no journal is written; its remaining value stops counting against the SOV
        line.  Billed stored material leaves only by transfer to installed."""
        if not isinstance(actor, str) or not actor.strip():
            raise BillError("withdrawing stored material requires an actor")
        if not isinstance(reason, str) or not reason.strip():
            raise BillError("withdrawing stored material requires a reason")
        with self.db.transaction() as conn:
            lot = self.lot(lot_id)
            if lot["withdrawn"]:
                raise BillError(f"lot {lot_id} was already withdrawn")
            if lot["billed"]:
                raise BillError(f"lot {lot_id} was billed on bill {lot['billed_bill_id']}; billed stored material leaves only by transfer to installed")
            c = self.commitments.get(lot["commitment_id"])
            if c["status"] != "executed":
                raise BillError(f"lot {lot_id} belongs to a {c['status']} commitment")
            now = utcnow_iso()
            conn.execute(
                "UPDATE stored_material_lots SET remaining_amount='0.00', withdrawn_at=?, withdrawn_by=?, withdrawal_reason=? WHERE id=?",
                (now, actor.strip(), reason.strip(), lot_id),
            )
            self.audit.record(actor, "stored_material.withdrawn", "stored_material_lot", lot_id, {
                "commitment_id": lot["commitment_id"], "sov_line_id": lot["sov_line_id"], "withdrawn_amount": lot["remaining_amount"],
                "evidence_revision_id": lot["evidence_revision_id"], "evidence_status": lot["evidence_status"], "reason": reason.strip(),
            })
        return self.lot(lot_id)

    def lot(self, lot_id: str) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM stored_material_lots WHERE id=?", (lot_id,))
        if row is None:
            raise BillError(f"unknown stored material lot {lot_id}")
        return self._decorate_lot(row)

    def lots(self, commitment_id: str) -> list[dict[str, Any]]:
        rows = self.db.query("SELECT * FROM stored_material_lots WHERE commitment_id=? ORDER BY created_at, id", (commitment_id,))
        return [self._decorate_lot(r) for r in rows]

    # ---- certification ------------------------------------------------------ #

    def latest(self, commitment_id: str) -> dict[str, Any] | None:
        """The commitment's latest standing bill (voided drafts and corrected bills no longer count)."""
        row = self.db.one("SELECT * FROM bills WHERE commitment_id=? AND status NOT IN ('void','corrected') ORDER BY sequence DESC LIMIT 1", (commitment_id,))
        return self.get(row["id"]) if row else None

    def certify(
        self,
        *,
        commitment_id: str,
        period_id: str,
        installed: list[dict[str, Any]],
        transfers: list[dict[str, Any]] | None = None,
        actor: str,
    ) -> dict[str, Any]:
        """Create a draft bill.

        ``installed``: ``[{"sov_line_id", "cumulative_installed"}]`` cumulative value installed per line,
        including any stored material transferred to installed this period.
        ``transfers``: ``[{"lot_id", "amount"}]`` stored-material value moved to installed this period.
        Lots recorded since the previous bill are billed as stored material automatically,
        except lots whose evidence must be re-confirmed (they wait for the next bill).
        """
        transfers = list(transfers or [])
        if not isinstance(installed, list) or not all(isinstance(i, dict) for i in installed):
            raise BillError("installed must be a list of {sov_line_id, cumulative_installed}")
        if not all(isinstance(t, dict) for t in transfers):
            raise BillError("transfers must be a list of {lot_id, amount}")
        c = self.commitments.get(commitment_id)
        if c["status"] != "executed":
            raise BillError("bills apply to executed commitments only")
        self.ledger.require_open(period_id)
        with self.db.transaction() as conn:
            c = self.commitments.get(commitment_id)
            prior = self.latest(commitment_id)
            if prior and prior["status"] == "draft":
                raise BillError("the previous bill is still a draft; approve, post or void it first")
            prior_lines = {ln["sov_line_id"]: ln for ln in (prior["lines"] if prior else [])}
            sov = {s["id"]: s for s in c["sov"]}
            rate = Decimal(c["retainage_rate"])
            sov_hash = self.commitments.sov_hash(commitment_id)

            # lots: carried (already billed), newly billed (eligible now) or left out (frozen, never billed);
            # withdrawn lots are gone for good
            all_lots = {l["id"]: l for l in self.lots(commitment_id) if not l["withdrawn"]}
            excluded = [l for l in all_lots.values() if not l["billed"] and l["frozen"]]
            included = {i: dict(l) for i, l in all_lots.items() if l["billed"] or not l["frozen"]}
            # left-out lots still hold their remaining value on the line for the per-line cap
            awaiting_by_line: dict[str, Decimal] = {}
            for l in excluded:
                awaiting_by_line[l["sov_line_id"]] = awaiting_by_line.get(l["sov_line_id"], ZERO) + money(l["remaining_amount"])

            # transfers
            transfer_total = ZERO
            lot_updates: list[tuple[str, Decimal]] = []
            transferred_by_line: dict[str, Decimal] = {}
            seen_lots: set[str] = set()
            for t in transfers:
                lid = t.get("lot_id")
                if lid in seen_lots:
                    raise BillError(f"lot {lid} listed twice in transfers")
                seen_lots.add(lid)
                lot = all_lots.get(lid)
                if lot is None:
                    gone = self.db.one("SELECT id FROM stored_material_lots WHERE id=? AND commitment_id=? AND withdrawn_at IS NOT NULL", (lid, commitment_id))
                    raise BillError(f"lot {lid} was withdrawn" if gone else f"lot {lid} does not belong to this commitment")
                if lot["frozen"]:
                    raise BillError(f"lot {lid} evidence was revised after it was recorded; confirm_lot_evidence before transferring it")
                if "amount" not in t:
                    raise BillError(f"transfer from lot {lid} needs an amount")
                amt = money(t["amount"])
                remaining = money(included[lid]["remaining_amount"])
                if amt <= 0 or amt > remaining:
                    raise BillError(f"transfer {fmt(amt)} exceeds remaining stored value {fmt(remaining)} on lot {lid}")
                lot_updates.append((lid, remaining - amt))
                included[lid]["remaining_amount"] = fmt(remaining - amt)
                transferred_by_line[lot["sov_line_id"]] = transferred_by_line.get(lot["sov_line_id"], ZERO) + amt
                transfer_total += amt

            # installed per line
            lines_out: dict[str, dict[str, Any]] = {}
            for item in installed:
                sid = item.get("sov_line_id")
                if sid not in sov:
                    raise BillError(f"SOV line {sid} does not belong to this commitment")
                if sid in lines_out:
                    raise BillError(f"SOV line {sid} listed twice")
                if "cumulative_installed" not in item:
                    raise BillError(f"SOV line {sov[sid]['line_no']} needs a cumulative_installed value")
                cum = money(item["cumulative_installed"])
                prev = money(prior_lines[sid]["cumulative_installed"]) if sid in prior_lines else ZERO
                if cum < prev:
                    raise BillError(f"cumulative installed on line {sov[sid]['line_no']} cannot decrease ({fmt(prev)} -> {fmt(cum)})")
                if cum > money(sov[sid]["amount"]):
                    raise BillError(f"cumulative installed {fmt(cum)} exceeds SOV line {sov[sid]['line_no']} value {sov[sid]['amount']}")
                lines_out[sid] = {"sov_line_id": sid, "cumulative_installed": cum, "prior_installed": prev, "installed_this_period": cum - prev}
            for sid, pl in prior_lines.items():
                if sid not in lines_out:
                    prev = money(pl["cumulative_installed"])
                    lines_out[sid] = {"sov_line_id": sid, "cumulative_installed": prev, "prior_installed": prev, "installed_this_period": ZERO}

            # stored per line: newly billed lots enter at their pre-transfer value
            stored_by_line: dict[str, Decimal] = {}
            added_by_line: dict[str, Decimal] = {}
            for l in included.values():
                stored_by_line[l["sov_line_id"]] = stored_by_line.get(l["sov_line_id"], ZERO) + money(l["remaining_amount"])
                if not l["billed"]:
                    added_by_line[l["sov_line_id"]] = added_by_line.get(l["sov_line_id"], ZERO) + money(all_lots[l["id"]]["remaining_amount"])
            for sid in set(stored_by_line) | set(added_by_line) | set(transferred_by_line):
                if sid not in lines_out:
                    prev = money(prior_lines[sid]["cumulative_installed"]) if sid in prior_lines else ZERO
                    lines_out[sid] = {"sov_line_id": sid, "cumulative_installed": prev, "prior_installed": prev, "installed_this_period": ZERO}

            # per-line cap: installed plus every lot's remaining stored value (billed now or
            # left out until its evidence is re-confirmed) never exceeds the line value
            for s in c["sov"]:
                inst = lines_out[s["id"]]["cumulative_installed"] if s["id"] in lines_out else ZERO
                st = stored_by_line.get(s["id"], ZERO)
                waiting = awaiting_by_line.get(s["id"], ZERO)
                if inst + st + waiting > money(s["amount"]):
                    held = f" (including {fmt(waiting)} on lots awaiting evidence confirmation; confirm or withdraw them)" if waiting > 0 else ""
                    raise BillError(
                        f"SOV line {s['line_no']}: cumulative installed {fmt(inst)} plus remaining stored {fmt(st + waiting)}{held} "
                        f"exceeds the line value {s['amount']}"
                    )
                if s["id"] in lines_out and lines_out[s["id"]]["installed_this_period"] < transferred_by_line.get(s["id"], ZERO):
                    raise BillError(f"SOV line {s['line_no']}: installed value this period must include the stored material transferred on that line")

            ordered = sorted(lines_out.values(), key=lambda ln: sov[ln["sov_line_id"]]["line_no"])
            cumulative_installed = total(ln["cumulative_installed"] for ln in ordered) if ordered else ZERO
            prior_cum_installed = total(ln["prior_installed"] for ln in ordered) if ordered else ZERO
            installed_this_period = cumulative_installed - prior_cum_installed
            if installed_this_period < transfer_total:
                raise BillError("installed value this period must include every stored-material transfer")

            # stored
            cumulative_stored = total(stored_by_line.values()) if stored_by_line else ZERO
            prior_stored = money(prior["cumulative_stored"]) if prior else ZERO
            stored_added = cumulative_stored - prior_stored + transfer_total
            if stored_added < 0:
                raise BillError("stored material cannot decrease without a transfer")
            if installed_this_period == 0 and stored_added == 0:
                raise BillError("nothing to certify: no new installed work, stored material or transfer since the previous bill")

            cumulative_gross = cumulative_installed + cumulative_stored
            cumulative_retainage = pct(cumulative_gross, rate)
            cumulative_net = cumulative_gross - cumulative_retainage
            prior_net = money(prior["cumulative_net"]) if prior else ZERO
            prior_ret = money(prior["cumulative_retainage"]) if prior else ZERO
            amount_due = cumulative_net - prior_net
            retainage_this_period = cumulative_retainage - prior_ret
            if amount_due < 0 or retainage_this_period < 0:
                raise BillError("amount due would be negative; use a credit workflow instead")
            if cumulative_gross > money(c["executed_amount"]):
                raise BillError(f"cumulative gross {fmt(cumulative_gross)} exceeds executed commitment {c['executed_amount']}")

            # certification numbers are never reused, not even a voided draft's
            sequence = (conn.execute("SELECT COALESCE(MAX(sequence), 0) FROM bills WHERE commitment_id=?", (commitment_id,)).fetchone()[0]) + 1
            newly_billed = sorted(i for i, l in included.items() if not l["billed"])
            content = {
                "commitment_id": commitment_id, "commitment_version": c["version"], "period_id": period_id, "sequence": sequence,
                "retainage_rate": c["retainage_rate"], "sov_hash": sov_hash,
                "lines": [{k: (fmt(v) if isinstance(v, Decimal) else v) for k, v in ln.items()} for ln in ordered],
                "transfers": [{"lot_id": t["lot_id"], "amount": fmt(money(t["amount"]))} for t in transfers],
                "stored_lots": [{"lot_id": i, "remaining": included[i]["remaining_amount"], "newly_billed": i in newly_billed} for i in sorted(included)],
                "excluded_lots": sorted(l["id"] for l in excluded),
                "cumulative_installed": fmt(cumulative_installed), "cumulative_stored": fmt(cumulative_stored),
                "cumulative_gross": fmt(cumulative_gross), "cumulative_retainage": fmt(cumulative_retainage),
                "cumulative_net": fmt(cumulative_net), "prior_net": fmt(prior_net), "amount_due": fmt(amount_due),
            }
            content_hash = hash_json(content)
            bill_id = new_id("bill")
            conn.execute(
                """INSERT INTO bills (id, commitment_id, period_id, sequence, status, cumulative_installed, cumulative_stored, cumulative_gross,
                   cumulative_retainage, cumulative_net, prior_net, amount_due, retainage_this_period, installed_this_period,
                   stored_added_this_period, stored_transferred_this_period, commitment_version, content_hash, created_at, retainage_rate, sov_hash)
                   VALUES (?,?,?,?,'draft',?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    bill_id, commitment_id, period_id, sequence, fmt(cumulative_installed), fmt(cumulative_stored), fmt(cumulative_gross),
                    fmt(cumulative_retainage), fmt(cumulative_net), fmt(prior_net), fmt(amount_due), fmt(retainage_this_period),
                    fmt(installed_this_period), fmt(stored_added), fmt(transfer_total), c["version"], content_hash, utcnow_iso(),
                    c["retainage_rate"], sov_hash,
                ),
            )
            for ln in ordered:
                sid = ln["sov_line_id"]
                conn.execute(
                    "INSERT INTO bill_lines (id, bill_id, sov_line_id, cumulative_installed, prior_installed, installed_this_period, stored_added, stored_transferred) VALUES (?,?,?,?,?,?,?,?)",
                    (new_id("bln"), bill_id, sid, fmt(ln["cumulative_installed"]), fmt(ln["prior_installed"]), fmt(ln["installed_this_period"]),
                     fmt(added_by_line.get(sid, ZERO)), fmt(transferred_by_line.get(sid, ZERO))),
                )
            for lid, remaining in lot_updates:
                conn.execute("UPDATE stored_material_lots SET remaining_amount=? WHERE id=?", (fmt(remaining), lid))
            for lid in newly_billed:
                conn.execute("UPDATE stored_material_lots SET billed_bill_id=? WHERE id=? AND billed_bill_id IS NULL", (bill_id, lid))
            for t in transfers:
                conn.execute("INSERT INTO bill_transfers (id, bill_id, lot_id, amount) VALUES (?,?,?,?)", (new_id("btr"), bill_id, t["lot_id"], fmt(money(t["amount"]))))
            self.audit.record(actor, "bill.certified", "bill", bill_id, {
                "commitment_id": commitment_id, "sequence": sequence, "amount_due": fmt(amount_due), "retainage_this_period": fmt(retainage_this_period),
                "content_hash": content_hash, "newly_billed_lots": newly_billed, "excluded_lots": content["excluded_lots"],
            })
        out = self.get(bill_id)
        out["excluded_lots"] = [{"lot_id": l["id"], "reason": f"evidence {l['evidence_status']}; confirm_lot_evidence before billing"} for l in excluded]
        return out

    def get(self, bill_id: str) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM bills WHERE id=?", (bill_id,))
        if row is None:
            raise BillError(f"unknown bill {bill_id}")
        row["lines"] = self.db.query("SELECT * FROM bill_lines WHERE bill_id=? ORDER BY id", (bill_id,))
        row["transfers"] = self.db.query("SELECT lot_id, amount FROM bill_transfers WHERE bill_id=? ORDER BY id", (bill_id,))
        c = self.db.one("SELECT version, supplier_id, project_id, retainage_rate FROM commitments WHERE id=?", (row["commitment_id"],))
        row["commitment_current_version"] = c["version"]
        row["supplier_id"] = c["supplier_id"]
        row["project_id"] = c["project_id"]
        reasons = []
        if c["version"] != row["commitment_version"]:
            reasons.append("commitment version changed")
        if row.get("retainage_rate") is not None and row["retainage_rate"] != c["retainage_rate"]:
            reasons.append("retainage rate changed")
        if row.get("sov_hash") and row["sov_hash"] != self.commitments.sov_hash(row["commitment_id"]):
            reasons.append("schedule of values changed")
        row["stale"] = bool(reasons)
        row["stale_reasons"] = reasons
        return row

    def list(self, commitment_id: str | None = None, project_id: str | None = None) -> list[dict[str, Any]]:
        if commitment_id:
            rows = self.db.query("SELECT id FROM bills WHERE commitment_id=? ORDER BY sequence", (commitment_id,))
        elif project_id:
            rows = self.db.query("SELECT b.id FROM bills b JOIN commitments c ON c.id=b.commitment_id WHERE c.project_id=? ORDER BY b.created_at", (project_id,))
        else:
            rows = self.db.query("SELECT id FROM bills ORDER BY created_at")
        return [self.get(r["id"]) for r in rows]

    def void(self, bill_id: str, *, actor: str, reason: str) -> dict[str, Any]:
        with self.db.transaction() as conn:
            b = self.get(bill_id)
            if b["status"] != "draft":
                raise BillError("only draft bills can be voided; posted bills are corrected by reversal")
            # restore lot balances consumed by this draft's transfers
            for t in conn.execute("SELECT lot_id, amount FROM bill_transfers WHERE bill_id=?", (bill_id,)).fetchall():
                lot = self.lot(t["lot_id"])
                conn.execute("UPDATE stored_material_lots SET remaining_amount=? WHERE id=?", (fmt(money(lot["remaining_amount"]) + money(t["amount"])), t["lot_id"]))
            # lots first billed by this draft are unbilled again
            conn.execute("UPDATE stored_material_lots SET billed_bill_id=NULL WHERE billed_bill_id=?", (bill_id,))
            conn.execute("UPDATE bills SET status='void' WHERE id=?", (bill_id,))
            self.audit.record(actor, "bill.voided", "bill", bill_id, {"reason": reason})
        return self.get(bill_id)

    # ---- approval and posting ---------------------------------------------- #

    def journal_preview(self, bill_id: str) -> list[dict[str, Any]]:
        """The exact journals posting this bill writes, in order."""
        return self._journal_plan(self.get(bill_id))

    def _journal_plan(self, b: dict[str, Any]) -> list[dict[str, Any]]:
        pid, sup, seq = b["project_id"], b["supplier_id"], b["sequence"]
        source_version = str(b["commitment_version"])
        plan: list[dict[str, Any]] = []
        transferred = money(b["stored_transferred_this_period"])
        if transferred > 0:
            plan.append({
                "period_id": b["period_id"], "source_version": source_version,
                "description": f"Stored material transferred to installed, bill {seq}",
                "lines": [
                    _line("5000", debit=transferred, project_id=pid, party_id=sup, memo="stored -> installed"),
                    _line("1300", credit=transferred, project_id=pid, party_id=sup, memo="stored -> installed"),
                ],
            })
        new_cost = money(b["installed_this_period"]) - transferred
        stored_added = money(b["stored_added_this_period"])
        lines = []
        if new_cost > 0:
            lines.append(_line("5000", debit=new_cost, project_id=pid, party_id=sup, memo="installed work"))
        if stored_added > 0:
            lines.append(_line("1300", debit=stored_added, project_id=pid, party_id=sup, memo="eligible stored material"))
        if money(b["amount_due"]) > 0:
            lines.append(_line("2000", credit=money(b["amount_due"]), project_id=pid, party_id=sup, memo=f"bill {seq}"))
        if money(b["retainage_this_period"]) > 0:
            lines.append(_line("2050", credit=money(b["retainage_this_period"]), project_id=pid, party_id=sup, memo="retainage withheld"))
        if lines:
            plan.append({
                "period_id": b["period_id"], "source_version": source_version,
                "description": f"Supplier bill {seq} on commitment {b['commitment_id']}",
                "lines": lines,
            })
        return plan

    def _bill_lots(self, b: dict[str, Any]) -> list[dict[str, Any]]:
        """Lots this bill bills for the first time or transfers from."""
        ids = {r["id"] for r in self.db.query("SELECT id FROM stored_material_lots WHERE billed_bill_id=?", (b["id"],))}
        ids |= {t["lot_id"] for t in b["transfers"]}
        return [self.lot(i) for i in sorted(ids)]

    def _supplier_invoice_binding(self, b: dict[str, Any]) -> dict[str, Any] | None:
        """What ``bill.approve`` binds about the bill's attached supplier invoice (None when
        it has none).  Refuses (``BillIneligible``) when the invoice changed since it was
        attached, so an approval granted before the invoice was replaced goes stale."""
        link = self.supplier_invoice_state(b)
        if link is None:
            return None
        if link["problems"]:
            raise BillIneligible(f"bill {b['sequence']} ({b['id']}): " + "; ".join(link["problems"]))
        return {**link["attached"], "current": link["current"]}

    def manifest(self, bill_id: str, *, actor_role: str) -> dict[str, Any]:
        b = self.get(bill_id)
        supplier = self.db.one("SELECT * FROM parties WHERE id=?", (b["supplier_id"],))
        c = self.db.one("SELECT retainage_rate FROM commitments WHERE id=?", (b["commitment_id"],))
        bindings: dict[str, Any] = {
            "commitment_id": b["commitment_id"],
            "commitment_version": b["commitment_current_version"],
            "bill_version": b["commitment_version"],
            "bill_hash": b["content_hash"],
            "bill_status": b["status"],
            "project_id": b["project_id"],
            "period_id": b["period_id"],
            "sequence": b["sequence"],
            "posting_rule": POSTING_RULE,
            "retainage_rate": c["retainage_rate"],
            "bill_retainage_rate": b.get("retainage_rate"),
            "sov_hash": self.commitments.sov_hash(b["commitment_id"]),
            "stored_lots": [
                {"lot_id": l["id"], "evidence_revision_id": l["evidence_revision_id"], "evidence_status": l["evidence_status"]}
                for l in self._bill_lots(b)
            ],
            "journal_preview": self._journal_plan(b),
        }
        invoice = self._supplier_invoice_binding(b)
        if invoice is not None:  # bills without a supplier invoice keep the manifest they always had
            bindings["supplier_invoice"] = invoice
        return build_manifest(
            operation="bill.approve",
            subject_type="bill",
            subject_id=bill_id,
            actor_role=actor_role,
            amounts={"amount_due": b["amount_due"], "retainage_this_period": b["retainage_this_period"], "cumulative_gross": b["cumulative_gross"]},
            bindings=bindings,
            destination={"party_id": supplier["id"], "destination": supplier["destination"], "destination_version": supplier["destination_version"]},
            **self._scope(b["project_id"]),
        )

    def post(self, bill_id: str, *, approval_id: str, actor: str) -> dict[str, Any]:
        """Approve and post the bill's journal(s).  The caller has consumed ``approval_id``;
        the journals written are exactly the approved ``journal_preview``."""
        with self.db.transaction() as conn:
            b = self.get(bill_id)
            if b["status"] != "draft":
                raise BillError(f"bill {bill_id} is {b['status']}")
            if b["stale"]:
                raise BillError(f"the commitment changed after this bill was certified ({', '.join(b['stale_reasons'])}); re-certify it")
            self.ledger.require_open(b["period_id"])
            # every lot this bill bills for the first time or transfers from must still rest on current evidence
            frozen = [l["id"] for l in self._bill_lots(b) if l["evidence_status"] != "current"]
            if frozen:
                raise BillError(f"stored material lot(s) {', '.join(frozen)} have revised evidence; confirm_lot_evidence and approve again")
            plan = self._journal_plan(b)
            if not plan:
                raise BillError(f"bill {bill_id} has nothing to post")
            invoice = self._supplier_invoice_binding(b)  # a replaced or rejected supplier invoice stops the posting
            approved = self._approved_manifest(approval_id, "bill.approve", bill_id)
            self._refuse_spent_approval(approval_id)
            if canonical_json((approved.get("bindings") or {}).get("journal_preview")) != canonical_json(plan):
                raise BillError("the approved journal preview does not match the posting this bill would write; nothing was posted")
            if canonical_json((approved.get("bindings") or {}).get("supplier_invoice")) != canonical_json(invoice):
                raise BillIneligible("the supplier invoice attached to this bill is not the one the approval bound; nothing was posted")
            journal_ids = []
            for jp in plan:
                j = self.ledger.post(
                    period_id=jp["period_id"], description=jp["description"], lines=jp["lines"],
                    source_type="bill", source_id=bill_id, source_version=jp["source_version"], posted_by=actor, approval_id=approval_id,
                )
                journal_ids.append(j["id"])
            conn.execute("UPDATE bills SET status='posted', approval_id=?, journal_id=? WHERE id=?", (approval_id, journal_ids[-1], bill_id))
            self.audit.record(actor, "bill.posted", "bill", bill_id, {"approval_id": approval_id, "journals": journal_ids, "amount_due": b["amount_due"]})
        return self.get(bill_id)

    def mark_paid(self, bill_id: str, *, actor: str, intent_id: str) -> None:
        with self.db.transaction() as conn:
            conn.execute("UPDATE bills SET status='paid' WHERE id=? AND status='posted'", (bill_id,))
            self.audit.record(actor, "bill.paid", "bill", bill_id, {"intent_id": intent_id})

    # ---- shared helpers: payments, credits, periods ------------------------------------ #

    def _table_exists(self, name: str) -> bool:
        return self.db.one("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,)) is not None

    @staticmethod
    def _text(value: Any, label: str, *, max_length: int = MAX_TEXT_LENGTH) -> str:
        if not isinstance(value, str) or not value.strip():
            raise BillError(f"{label} is required")
        text = value.strip()
        if len(text) > max_length:
            raise BillError(f"{label} is longer than {max_length} characters")
        return text

    @staticmethod
    def _positive_amount(value: Any, label: str) -> Decimal:
        """A positive amount in whole cents; floats, non-finite values and sub-cent input are refused, not rounded."""
        try:
            raw = D(value)
            amt = money(raw)
        except (MoneyError, ArithmeticError) as exc:
            raise BillError(f"{label} is not exact money: {exc}") from exc
        if amt != raw:
            raise BillError(f"{label} must be in whole cents, got {value!r}")
        if amt <= 0:
            raise BillError(f"{label} must be positive, got {fmt(amt)}")
        return amt

    def _intents(self, bill_id: str) -> list[dict[str, Any]]:
        return self.db.query("SELECT id, status, amount FROM payment_intents WHERE bill_id=? ORDER BY created_at, id", (bill_id,))

    def _paid(self, bill_id: str) -> Decimal:
        rows = self.db.query(f"SELECT amount FROM payment_intents WHERE bill_id=? AND status IN {PAID_INTENT_STATES}", (bill_id,))
        return total(r["amount"] for r in rows) if rows else ZERO

    def credited(self, bill_id: str) -> Decimal:
        """Net AP (2000) debited by this bill's supplier credit-note journals (a reversal would net out)."""
        if not self._table_exists("bill_credit_notes"):
            return ZERO
        rows = self.db.query(
            """SELECT l.debit, l.credit FROM journal_lines l JOIN journals j ON j.id = l.journal_id JOIN bill_credit_notes n ON n.id = j.source_id
               WHERE j.source_type = ? AND n.bill_id = ? AND l.account_code = '2000'""",
            (CREDIT_NOTE_SOURCE, bill_id),
        )
        return money(sum((money(r["debit"]) - money(r["credit"]) for r in rows), ZERO))

    def open_payable(self, bill_id: str) -> Decimal:
        """What the supplier is still owed on a posted bill: amount due less accepted or settled
        payments less posted supplier credit notes (0.00 for a bill that is not posted or paid).
        This, not the amount due, is what a payment of a credited bill releases: a storage
        guard refuses a ``payment.release`` approval or a released payment intent for a bill
        carrying a posted credit note unless it is for exactly this amount."""
        b = self.db.one("SELECT status, amount_due FROM bills WHERE id=?", (bill_id,))
        if b is None:
            raise BillError(f"unknown bill {bill_id}")
        if b["status"] not in ("posted", "paid"):
            return ZERO
        return money(money(b["amount_due"]) - self._paid(bill_id) - self.credited(bill_id))

    def _target_period(self, period_id: str | None, *, not_before: str, what: str) -> dict[str, Any]:
        """The open period that receives a credit note or correction: the one named at
        execution, else the latest open period; never one starting before the bill's own."""
        if period_id:
            target = self.ledger.require_open(period_id)
        else:
            target = self.db.one("SELECT * FROM periods WHERE status='open' ORDER BY start_date DESC LIMIT 1")
            if target is None:
                raise PeriodNotOpen(f"no open period can receive the {what}")
        source = self.ledger.period(not_before)
        if target["start_date"] < source["start_date"]:
            raise BillError(
                f"the {what} cannot be dated before the bill it adjusts: period {target['id']} starts {target['start_date']}, "
                f"the bill's period {source['id']} starts {source['start_date']}"
            )
        return target

    def _document_evidence(self, project_id: str, evidence_hash: Any, kind: str, label: str) -> dict[str, Any]:
        """The current revision of a ``kind`` document on ``project_id`` carrying ``evidence_hash``."""
        if not isinstance(evidence_hash, str) or not evidence_hash.strip():
            raise BillError(f"a {label} requires the content hash of its {kind} document")
        rows = self.db.query(
            """SELECT r.id, r.document_id, r.revision, r.content_hash, d.project_id, d.kind FROM document_revisions r
               JOIN documents d ON d.id = r.document_id WHERE r.content_hash=? ORDER BY r.created_at, r.id""",
            (evidence_hash.strip(),),
        )
        if not rows:
            raise BillError(f"the {label} evidence hash matches no stored document revision; register the {kind} document first")
        rows = [r for r in rows if r["project_id"] == project_id]
        if not rows:
            raise BillError(f"the {label} evidence belongs to another project; it must be registered on project {project_id}")
        rows = [r for r in rows if r["kind"] == kind]
        if not rows:
            raise BillError(f"a {label} is backed only by a '{kind}' document")
        current = [r for r in rows if (self._current_revision(r["document_id"]) or {}).get("id") == r["id"]]
        if not current:
            raise BillError(f"the {label} evidence hash matches a superseded revision of document {rows[-1]['document_id']}; bind the current revision")
        if len(current) > 1:
            raise BillError(f"the {label} evidence hash matches the current revision of several documents; register distinct evidence")
        return current[0]

    # ---- supplier invoice link (attached by ap_intake.match_invoice) -------------------- #

    def supplier_invoice_state(self, bill: dict[str, Any] | str) -> dict[str, Any] | None:
        """The supplier invoice attached to a bill as attached, as it stands now, and why the
        two no longer agree (``problems``).  None when the bill carries no supplier invoice."""
        b = self.get(bill) if isinstance(bill, str) else bill
        if not b.get("supplier_invoice_id"):
            return None
        attached = {
            "id": b["supplier_invoice_id"], "number": b.get("supplier_invoice_number"), "invoice_date": b.get("invoice_date"),
            "due_date": b.get("due_date"), "invoice_hash": b.get("supplier_invoice_hash"), "evidence_hash": b.get("supplier_invoice_evidence_hash"),
            "approval_id": b.get("supplier_invoice_approval_id"),
        }
        row = None
        if self._table_exists(SUPPLIER_INVOICES_TABLE):
            row = self.db.one(
                f"""SELECT status, version, content_hash, invoice_number, invoice_date, due_date, evidence_hash, evidence_document_id, matched_bill_id,
                           match_approval_id FROM {SUPPLIER_INVOICES_TABLE} WHERE id=?""",
                (attached["id"],),
            )
        problems: list[str] = []
        current = None
        if row is None:
            problems.append(f"the attached supplier invoice {attached['id']} is not on record in this workspace")
        else:
            rev = self._current_revision(row["evidence_document_id"])
            current = {"status": row["status"], "version": row["version"], "invoice_hash": row["content_hash"], "number": row["invoice_number"],
                       "invoice_date": row["invoice_date"], "due_date": row["due_date"], "evidence_hash": row["evidence_hash"],
                       "evidence_current_hash": rev["content_hash"] if rev else None}
            if row["status"] == "rejected":
                problems.append(f"supplier invoice {attached['number']} ({attached['id']}) was rejected after it was attached; match another invoice to this bill")
            elif row["content_hash"] != attached["invoice_hash"]:
                problems.append(f"supplier invoice {attached['number']} ({attached['id']}) was revised to version {row['version']} after it was attached; "
                                "match the revised invoice again")
            else:
                differs = [label for label, mine, theirs in (("number", attached["number"], row["invoice_number"]),
                                                             ("invoice date", attached["invoice_date"], row["invoice_date"]),
                                                             ("due date", attached["due_date"], row["due_date"])) if mine != theirs]
                if differs:
                    problems.append(f"the bill records supplier invoice {attached['id']} with another {', '.join(differs)} than the invoice record "
                                    f"({row['invoice_number']}, dated {row['invoice_date']}, due {row['due_date']}); match the invoice again")
                if row["status"] != "matched" or row["matched_bill_id"] != b["id"] or row["match_approval_id"] != attached["approval_id"]:
                    problems.append(f"supplier invoice {row['invoice_number']} ({attached['id']}) is no longer recorded as matched to this bill under approval "
                                    f"{attached['approval_id']}; match it again")
            if current["evidence_current_hash"] != attached["evidence_hash"]:
                problems.append(f"the document of supplier invoice {attached['number']} has a newer revision than the one attached; "
                                "revise the invoice to bind it and match it again")
        return {"attached": attached, "current": current, "problems": problems}

    def supplier_invoice_link_holds(self, b: dict[str, Any]) -> bool:
        """Whether the bill's supplier invoice link still holds: the linked invoice is on
        record, not rejected and still hashes to the version that was attached.  A link
        that no longer holds leaves the bill free for another matched invoice."""
        if not b.get("supplier_invoice_id") or not self._table_exists(SUPPLIER_INVOICES_TABLE):
            return False
        row = self.db.one(f"SELECT status, content_hash FROM {SUPPLIER_INVOICES_TABLE} WHERE id=?", (b["supplier_invoice_id"],))
        return row is not None and row["status"] != "rejected" and row["content_hash"] == b.get("supplier_invoice_hash")

    # fields a caller may restate when attaching; each must equal the invoice record
    _ATTACH_RECORD_FIELDS = (("invoice_number", "invoice_number"), ("invoice_date", "invoice_date"), ("due_date", "due_date"),
                             ("content_hash", "content_hash"), ("evidence_hash", "evidence_hash"), ("supplier_id", "supplier_id"),
                             ("project_id", "project_id"), ("amount", "amount"))

    def attach_supplier_invoice(self, bill_id: str, invoice: dict[str, Any], actor: str) -> dict[str, Any]:
        """Link a matched supplier invoice to a draft or posted bill.  Called by the
        ``ap_intake`` plugin from inside its ``ap_intake.match_invoice`` execution, after it
        recorded the invoice as matched to this bill: ``invoice`` names the invoice (``id``)
        and that consumed approval (``match_approval_id``).  Every linked fact -- number,
        invoice date, due date, content and evidence hashes -- is read from the invoice
        record, never taken from the caller (a restated field must equal the record).  The
        approval must not have attached anything before, not even to this bill; the invoice
        must be the bill's supplier's, on its project, for exactly the bill's amount due, and
        attached to no other live bill; a bill whose current link is another live invoice is
        refused (a link to a rejected or since-revised invoice no longer holds and is
        replaced).  Open ``bill.approve`` approvals on the bill are invalidated (their manifest
        did not bind this invoice)."""
        who = self._text(actor, "actor")
        if not isinstance(invoice, dict):
            raise BillError("a supplier invoice is attached from its matched record (a mapping naming id and match_approval_id)")
        missing = [k for k in ("id", "match_approval_id") if not isinstance(invoice.get(k), str) or not invoice.get(k).strip()]
        if missing:
            raise BillError(f"the supplier invoice reference lacks {', '.join(missing)}")
        invoice_id, approval_id = invoice["id"], invoice["match_approval_id"]
        if not self._table_exists(SUPPLIER_INVOICES_TABLE):
            raise BillError("this workspace has no supplier invoice intake; a supplier invoice is attached only from its matched record")
        with self.db.transaction() as conn:
            rec = conn.execute(f"SELECT * FROM {SUPPLIER_INVOICES_TABLE} WHERE id=?", (invoice_id,)).fetchone()
            if rec is None:
                raise BillError(f"unknown supplier invoice {invoice_id}")
            rec = dict(rec)
            restated = [label for key, label in self._ATTACH_RECORD_FIELDS if key in invoice and invoice[key] != rec[key]]
            if restated:
                raise BillError(f"the supplier invoice facts given for {rec['invoice_number']} ({invoice_id}) differ from its record in "
                                f"{', '.join(restated)}; a bill takes the invoice exactly as recorded")
            ap = self.db.one("SELECT operation, subject_id, status FROM approvals WHERE id=?", (approval_id,))
            if ap is None or ap["operation"] != MATCH_OPERATION or ap["subject_id"] != invoice_id or ap["status"] != "consumed":
                raise BillError(f"a supplier invoice is attached only by its consumed {MATCH_OPERATION} approval")
            if rec["status"] != "matched" or rec["match_approval_id"] != approval_id or rec["matched_bill_id"] != bill_id:
                raise BillError(f"supplier invoice {rec['invoice_number']} ({invoice_id}) is not recorded as matched to bill {bill_id} under approval "
                                f"{approval_id}; a supplier invoice is attached only by the match that approval executes")
            used = conn.execute("SELECT id FROM bills WHERE supplier_invoice_approval_id=?", (approval_id,)).fetchone()
            if used is not None:
                raise BillError(f"approval {approval_id} already attached a supplier invoice to bill {used['id']}; an approval takes effect once")
            b = self.get(bill_id)
            if b["status"] not in ("draft", "posted"):
                raise BillError(f"bill {b['sequence']} ({bill_id}) is {b['status']}; a supplier invoice is attached only to a draft or posted bill")
            if b["status"] == "draft" and b["stale"]:
                raise BillError(f"bill {b['sequence']} ({bill_id}) was certified before its commitment changed ({', '.join(b['stale_reasons'])}); re-certify it first")
            if rec["supplier_id"] != b["supplier_id"] or rec["project_id"] != b["project_id"]:
                raise BillError(f"supplier invoice {rec['invoice_number']} is not from this bill's supplier on this bill's project")
            if money(rec["amount"]) != money(b["amount_due"]):
                raise BillError(f"supplier invoice {rec['invoice_number']} is for {fmt(money(rec['amount']))}, bill {b['sequence']} is due {b['amount_due']}")
            if rec["due_date"] < rec["invoice_date"]:
                raise BillError("a supplier invoice falls due on or after its invoice date")
            elsewhere = conn.execute("SELECT id, sequence, status FROM bills WHERE supplier_invoice_id=? AND id != ? AND status IN ('draft','approved','posted','paid')",
                                     (invoice_id, bill_id)).fetchone()
            if elsewhere is not None:
                raise BillError(f"supplier invoice {rec['invoice_number']} is already attached to bill {elsewhere['sequence']} ({elsewhere['id']}, {elsewhere['status']}); "
                                "one invoice is attached to one live bill")
            linked = b.get("supplier_invoice_id")
            if linked and linked != invoice_id and self.supplier_invoice_link_holds(b):
                other = self.db.scalar(f"SELECT invoice_number FROM {SUPPLIER_INVOICES_TABLE} WHERE id=?", (linked,))
                raise BillError(f"bill {b['sequence']} ({bill_id}) is already linked to supplier invoice {other} ({linked})")
            payload = {
                "supplier_invoice_id": invoice_id, "supplier_invoice_number": rec["invoice_number"], "invoice_date": rec["invoice_date"],
                "due_date": rec["due_date"], "supplier_invoice_hash": rec["content_hash"], "supplier_invoice_evidence_hash": rec["evidence_hash"],
                "invoice_version": rec["version"], "approval_id": approval_id, "previous_supplier_invoice_id": linked, "bill_status": b["status"],
                "amount_due": b["amount_due"],
            }
            # audited first: the storage guard admits a link only with its audit entry
            self.audit.record(who, "bill.supplier_invoice_attached", "bill", bill_id, payload)
            conn.execute(
                """UPDATE bills SET supplier_invoice_id=?, supplier_invoice_number=?, invoice_date=?, due_date=?, supplier_invoice_hash=?,
                   supplier_invoice_evidence_hash=?, supplier_invoice_approval_id=? WHERE id=?""",
                (invoice_id, rec["invoice_number"], rec["invoice_date"], rec["due_date"], rec["content_hash"], rec["evidence_hash"], approval_id, bill_id),
            )
            for ap_row in self.db.query("SELECT id FROM approvals WHERE operation='bill.approve' AND subject_id=? AND status IN ('pending','granted')", (bill_id,)):
                self.approvals.invalidate(ap_row["id"], reason=f"supplier invoice {rec['invoice_number']} was attached after the approval was requested", actor=who)
        return self.get(bill_id)

    # ---- core-domain operations: handles / manifest_for / apply ------------------------ #

    def handles(self, operation: str) -> bool:
        """``bill.credit_note`` and ``bill.correct``; ``bill.approve`` keeps its own route."""
        return operation in OWNED_OPERATIONS

    def manifest_for(self, operation: str, subject_id: str, *, actor_role: str) -> dict[str, Any]:
        if operation == OP_CREDIT_NOTE:
            return self._credit_note_manifest(subject_id, actor_role=actor_role)
        if operation == OP_CORRECT:
            return self._correction_manifest(subject_id, actor_role=actor_role)
        raise BillError(f"bills does not own operation {operation}")

    def apply(self, operation: str, subject_id: str, *, approval_id: str, manifest: dict[str, Any], actor: str, period_id: str | None) -> dict[str, Any]:
        if operation == OP_CREDIT_NOTE:
            return self._apply_credit_note(subject_id, approval_id=approval_id, manifest=manifest, actor=actor, period_id=period_id)
        if operation == OP_CORRECT:
            return self._apply_correction(subject_id, approval_id=approval_id, manifest=manifest, actor=actor, period_id=period_id)
        raise BillError(f"bills does not own operation {operation}")

    # ---- supplier credit notes (bill.credit_note) ------------------------------------- #

    def credit_note(self, credit_note_id: str) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM bill_credit_notes WHERE id=?", (credit_note_id,)) if isinstance(credit_note_id, str) else None
        if row is None:
            raise BillError(f"unknown supplier credit note {credit_note_id}")
        cur = self._current_revision(row["evidence_document_id"])
        row["evidence_current"] = cur is not None and cur["id"] == row["evidence_revision_id"]
        return row

    def credit_notes(self, bill_id: str | None = None) -> list[dict[str, Any]]:
        if bill_id:
            rows = self.db.query("SELECT id FROM bill_credit_notes WHERE bill_id=? ORDER BY created_at, id", (bill_id,))
        else:
            rows = self.db.query("SELECT id FROM bill_credit_notes ORDER BY created_at, id")
        return [self.credit_note(r["id"]) for r in rows]

    def _in_flight(self, bill_id: str) -> list[dict[str, Any]]:
        return [i for i in self._intents(bill_id) if i["status"] in IN_FLIGHT_INTENT_STATES]

    def prepare_credit_note(self, bill_id: str, amount: Any, reason: str, evidence_hash: str, actor: str) -> dict[str, Any]:
        """Record a supplier credit-note draft against a POSTED bill.  The evidence is the
        current revision of a ``supplier_credit_note`` document on the bill's project that
        backs no other live credit note.  The amount (positive, whole cents) may not exceed
        the bill's open payable less the other drafts already prepared against it."""
        who = self._text(actor, "actor")
        why = self._text(reason, "a credit note reason")
        amt = self._positive_amount(amount, "credit note amount")
        note_id = new_id("bcn")
        with self.db.transaction() as conn:
            b = self.get(bill_id)
            if b["status"] != "posted":
                raise BillError(f"bill {b['sequence']} ({bill_id}) is {b['status']}; a supplier credit note applies to a posted bill with an open payable")
            rev = self._document_evidence(b["project_id"], evidence_hash, CREDIT_NOTE_EVIDENCE_KIND, "supplier credit note")
            taken = conn.execute("SELECT id FROM bill_credit_notes WHERE evidence_document_id=? AND status != 'cancelled'", (rev["document_id"],)).fetchone()
            if taken is not None:
                raise BillError(f"credit note document {rev['document_id']} already supports supplier credit note {taken['id']}; the same credit cannot be taken twice")
            flying = self._in_flight(bill_id)
            if flying:
                raise BillError(f"payment intent(s) {', '.join(i['id'] for i in flying)} for bill {b['sequence']} are in flight; resolve them before crediting the bill")
            open_amt = self.open_payable(bill_id)
            drafts = total(r["amount"] for r in conn.execute("SELECT amount FROM bill_credit_notes WHERE bill_id=? AND status='draft'", (bill_id,)).fetchall())
            available = money(open_amt - drafts)
            if amt > available:
                raise BillError(
                    f"credit {fmt(amt)} exceeds what is open on bill {b['sequence']}: open payable {fmt(open_amt)}"
                    + (f" less {fmt(drafts)} in other draft credit notes" if drafts else "") + f" leaves {fmt(available)}"
                )
            now = utcnow_iso()
            conn.execute(
                """INSERT INTO bill_credit_notes (id, bill_id, amount, reason, evidence_hash, evidence_document_id, evidence_revision_id, status, created_by, created_at)
                   VALUES (?,?,?,?,?,?,?,'draft',?,?)""",
                (note_id, bill_id, fmt(amt), why, rev["content_hash"], rev["document_id"], rev["id"], who, now),
            )
            self.audit.record(who, "bill.credit_note_prepared", CREDIT_NOTE_SUBJECT, note_id, {
                "bill_id": bill_id, "amount": fmt(amt), "reason": why, "evidence_hash": rev["content_hash"], "evidence_document_id": rev["document_id"],
                "evidence_revision_id": rev["id"], "open_payable": fmt(open_amt), "other_drafts": fmt(drafts),
            })
        return self.credit_note(note_id)

    def cancel_credit_note(self, credit_note_id: str, reason: str, actor: str) -> dict[str, Any]:
        """Withdraw a draft credit note; an approval that bound it goes stale."""
        who = self._text(actor, "actor")
        why = self._text(reason, "a cancellation reason")
        with self.db.transaction() as conn:
            n = self.credit_note(credit_note_id)
            if n["status"] != "draft":
                raise BillError(f"supplier credit note {credit_note_id} is {n['status']}; only a draft is cancelled")
            conn.execute("UPDATE bill_credit_notes SET status='cancelled', cancelled_by=?, cancelled_at=?, cancel_reason=? WHERE id=?",
                         (who, utcnow_iso(), why, credit_note_id))
            invalidated = self.approvals.invalidate_for_subject(CREDIT_NOTE_SUBJECT, credit_note_id, reason=f"credit note cancelled: {why}", actor=who)
            self.audit.record(who, "bill.credit_note_cancelled", CREDIT_NOTE_SUBJECT, credit_note_id, {"bill_id": n["bill_id"], "reason": why, "approvals_invalidated": invalidated})
        return self.credit_note(credit_note_id)

    def _credit_note_lines(self, n: dict[str, Any], b: dict[str, Any]) -> list[dict[str, Any]]:
        amt = money(n["amount"])
        return [
            _line("2000", debit=amt, project_id=b["project_id"], party_id=b["supplier_id"], memo=f"supplier credit note {n['id']} on bill {b['sequence']}"),
            _line("5000", credit=amt, project_id=b["project_id"], party_id=b["supplier_id"], memo="project cost reduced by supplier credit"),
        ]

    def _credit_note_facts(self, credit_note_id: str) -> dict[str, Any]:
        n = self.credit_note(credit_note_id)
        b = self.get(n["bill_id"])
        problems: list[str] = []
        if n["status"] != "draft":
            problems.append(f"supplier credit note {credit_note_id} is {n['status']}")
        if b["status"] != "posted":
            problems.append(f"bill {b['sequence']} ({b['id']}) is {b['status']}; a supplier credit applies to a posted, open payable")
        flying = self._in_flight(b["id"])
        if flying:
            problems.append(f"payment intent(s) {', '.join(i['id'] for i in flying)} for the bill are in flight")
        open_amt = self.open_payable(b["id"])
        if money(n["amount"]) > open_amt:
            problems.append(f"credit {n['amount']} exceeds the open payable {fmt(open_amt)} on bill {b['sequence']}")
        if not n["evidence_current"]:
            problems.append(f"credit note document {n['evidence_document_id']} has a newer revision; cancel this draft and prepare one bound to it")
        return {"note": n, "bill": b, "open": open_amt, "paid": self._paid(b["id"]), "credited": self.credited(b["id"]),
                "lines": self._credit_note_lines(n, b), "problems": problems}

    def _credit_note_manifest(self, credit_note_id: str, *, actor_role: str) -> dict[str, Any]:
        f = self._credit_note_facts(credit_note_id)
        if f["problems"]:
            raise BillIneligible(f"supplier credit note {credit_note_id} cannot be posted: " + "; ".join(f["problems"]))
        n, b = f["note"], f["bill"]
        return build_manifest(
            operation=OP_CREDIT_NOTE,
            subject_type=CREDIT_NOTE_SUBJECT,
            subject_id=credit_note_id,
            actor_role=actor_role,
            amounts={"credit": n["amount"], "open_payable": f["open"]},
            bindings={
                "credit_note_id": n["id"], "credit_note_status": n["status"], "reason": n["reason"],
                "evidence_hash": n["evidence_hash"], "evidence_document_id": n["evidence_document_id"], "evidence_revision_id": n["evidence_revision_id"],
                "bill_id": b["id"], "bill_hash": b["content_hash"], "bill_status": b["status"], "bill_sequence": b["sequence"], "bill_period_id": b["period_id"],
                "amount_due": b["amount_due"], "paid": fmt(f["paid"]), "credited_to_date": fmt(f["credited"]), "open_payable": fmt(f["open"]),
                "supplier_invoice_id": b.get("supplier_invoice_id"), "project_id": b["project_id"], "supplier_id": b["supplier_id"],
                "posting_rule": POSTING_RULE, "source_type": CREDIT_NOTE_SOURCE, "journal_preview": f["lines"],
                "target_rule": "execute with period_id of an open period starting on or after the bill's period (default: the latest open period)",
            },
            **self._scope(b["project_id"]),
        )

    def _apply_credit_note(self, credit_note_id: str, *, approval_id: str, manifest: dict[str, Any], actor: str, period_id: str | None) -> dict[str, Any]:
        bound = manifest.get("bindings") or {}
        with self.db.transaction() as conn:
            f = self._credit_note_facts(credit_note_id)
            if f["problems"]:
                raise BillIneligible(f"supplier credit note {credit_note_id} can no longer be posted: " + "; ".join(f["problems"]))
            n, b = f["note"], f["bill"]
            if (bound.get("bill_hash") != b["content_hash"] or bound.get("open_payable") != fmt(f["open"])
                    or canonical_json(bound.get("journal_preview")) != canonical_json(f["lines"])):
                raise BillIneligible(f"supplier credit note {credit_note_id} no longer matches the approved credit; nothing was posted")
            self._approved_manifest(approval_id, OP_CREDIT_NOTE, credit_note_id)
            self._refuse_spent_approval(approval_id)
            target = self._target_period(period_id, not_before=b["period_id"], what="supplier credit note")
            j = self.ledger.post(
                period_id=target["id"], description=f"Supplier credit note {n['id']} on bill {b['sequence']} ({b['id']})", lines=f["lines"],
                source_type=CREDIT_NOTE_SOURCE, source_id=n["id"], source_version="1", posted_by=actor, approval_id=approval_id,
            )
            now = utcnow_iso()
            conn.execute("UPDATE bill_credit_notes SET status='posted', approval_id=?, journal_id=?, period_id=?, posted_by=?, posted_at=? WHERE id=?",
                         (approval_id, j["id"], target["id"], actor, now, credit_note_id))
            # a payment approval granted for the full amount due no longer fits the bill
            invalidated = self.approvals.invalidate_for_subject("bill", b["id"], reason=f"supplier credit note {credit_note_id} reduced the open payable", actor=actor)
            self.audit.record(actor, "bill.credit_note_posted", CREDIT_NOTE_SUBJECT, credit_note_id, {
                "bill_id": b["id"], "amount": n["amount"], "journal_id": j["id"], "period_id": target["id"], "approval_id": approval_id,
                "open_payable_before": fmt(f["open"]), "open_payable_after": fmt(money(f["open"] - money(n["amount"]))), "approvals_invalidated": invalidated,
            })
        return {"credit_note": credit_note_id, "status": "posted", "bill": b["id"], "amount": n["amount"], "journal_id": j["id"], "period_id": target["id"],
                "open_payable": fmt(self.open_payable(b["id"]))}

    # ---- posted-bill correction (bill.correct) ----------------------------------------- #

    def correction(self, correction_id: str) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM bill_corrections WHERE id=?", (correction_id,)) if isinstance(correction_id, str) else None
        if row is None:
            raise BillError(f"unknown bill correction request {correction_id}")
        row["reversal_journals"] = loads(row["reversal_journals_json"]) if row["reversal_journals_json"] else []
        return row

    def corrections(self, bill_id: str | None = None) -> list[dict[str, Any]]:
        if bill_id:
            rows = self.db.query("SELECT id FROM bill_corrections WHERE bill_id=? ORDER BY rowid", (bill_id,))
        else:
            rows = self.db.query("SELECT id FROM bill_corrections ORDER BY rowid")
        return [self.correction(r["id"]) for r in rows]

    def _bill_journals(self, bill_id: str) -> list[dict[str, Any]]:
        rows = self.db.query("SELECT id FROM journals WHERE source_type='bill' AND source_id=? AND reversal_of IS NULL ORDER BY posted_at, id", (bill_id,))
        return [self.ledger.journal(r["id"]) for r in rows]

    def _correction_facts(self, bill_id: str) -> dict[str, Any]:
        b = self.get(bill_id)
        problems: list[str] = []
        if b["status"] != "posted":
            problems.append(f"bill {b['sequence']} ({bill_id}) is {b['status']}; only a posted, unpaid bill is corrected")
        latest = self.latest(b["commitment_id"])
        if b["status"] not in ("void", "corrected") and latest is not None and latest["id"] != bill_id:
            problems.append(f"bill {latest['sequence']} ({latest['id']}, {latest['status']}) follows it; only the commitment's latest bill is corrected")
        intents = self._intents(bill_id)
        holding = [i for i in intents if i["status"] not in UNPAID_FINAL_INTENT_STATES]
        if holding:
            problems.append(f"payment intent(s) {', '.join(i['id'] + ' (' + i['status'] + ')' for i in holding)} pay or are paying the bill; a paid bill is not corrected")
        credits = [n for n in self.credit_notes(bill_id)] if self._table_exists("bill_credit_notes") else []
        live_credits = [n for n in credits if n["status"] != "cancelled"]
        if live_credits:
            problems.append(f"supplier credit note(s) {', '.join(n['id'] + ' (' + n['status'] + ')' for n in live_credits)} are recorded against it; "
                            "a credited bill is not corrected (cancel a draft credit note first)")
        c = self.commitments.get(b["commitment_id"])
        if c["status"] != "executed":
            problems.append(f"commitment {c['id']} is {c['status']}; a replacement bill can be certified only on an executed commitment")
        journals = self._bill_journals(bill_id)
        if not journals:
            problems.append(f"bill {b['sequence']} has no posted journal to reverse")
        reversed_already = [j["id"] for j in journals if j["reversed_by"]]
        if reversed_already:
            problems.append(f"journal(s) {', '.join(reversed_already)} of the bill were already reversed")
        request = self.db.one("SELECT * FROM bill_corrections WHERE bill_id=? ORDER BY rowid DESC LIMIT 1", (bill_id,)) if self._table_exists("bill_corrections") else None
        request_problem = None
        if request is None:
            request_problem = f"bill {b['sequence']} has no correction request; call prepare_correction(bill_id, reason, actor) first so the reason is bound into the approval"
        elif request["status"] != "pending":
            request_problem = f"the latest correction request {request['id']} for the bill is {request['status']}; prepare a new correction request"
        first_billed = self.db.query("SELECT id, remaining_amount FROM stored_material_lots WHERE billed_bill_id=? ORDER BY created_at, id", (bill_id,))
        return {"bill": b, "commitment": c, "latest": latest, "intents": intents, "credit_notes": credits, "journals": journals,
                "request": request, "transfers": b["transfers"], "first_billed": first_billed,
                "bill_problems": problems, "problems": problems + ([request_problem] if request_problem else [])}

    def prepare_correction(self, bill_id: str, reason: str, actor: str) -> dict[str, Any]:
        """Record why a posted bill should be corrected; the pending request is what a
        ``bill.correct`` approval binds.  One pending request per bill, and only for a bill
        that can be corrected now (posted, unpaid, uncredited, the commitment's latest)."""
        who = self._text(actor, "actor")
        why = self._text(reason, "a correction reason")
        request_id = new_id("bcr")
        with self.db.transaction() as conn:
            f = self._correction_facts(bill_id)
            pending = f["request"] is not None and f["request"]["status"] == "pending"
            if pending:
                raise BillError(f"bill {bill_id} already has pending correction request {f['request']['id']}; cancel it before preparing another")
            if f["bill_problems"]:
                raise BillError(f"bill {bill_id} cannot be corrected: " + "; ".join(f["bill_problems"]))
            conn.execute("INSERT INTO bill_corrections (id, bill_id, reason, status, requested_by, requested_at) VALUES (?,?,?,'pending',?,?)",
                         (request_id, bill_id, why, who, utcnow_iso()))
            self.audit.record(who, "bill.correction_requested", "bill", bill_id, {"request_id": request_id, "reason": why})
        return self.correction(request_id)

    def cancel_correction(self, correction_id: str, reason: str, actor: str) -> dict[str, Any]:
        """Withdraw a pending correction request; an approval that bound it goes stale."""
        who = self._text(actor, "actor")
        why = self._text(reason, "a cancellation reason")
        with self.db.transaction() as conn:
            req = self.correction(correction_id)
            if req["status"] != "pending":
                raise BillError(f"correction request {correction_id} is {req['status']}; only a pending request is cancelled")
            conn.execute("UPDATE bill_corrections SET status='cancelled', resolved_by=?, resolved_at=?, resolution_note=? WHERE id=?",
                         (who, utcnow_iso(), why, correction_id))
            self.audit.record(who, "bill.correction_request_cancelled", "bill", req["bill_id"], {"request_id": correction_id, "reason": why})
        return self.correction(correction_id)

    def _correction_manifest(self, bill_id: str, *, actor_role: str) -> dict[str, Any]:
        f = self._correction_facts(bill_id)
        if f["problems"]:
            raise BillIneligible(f"bill {bill_id} cannot be corrected: " + "; ".join(f["problems"]))
        b, c, req = f["bill"], f["commitment"], f["request"]
        period = self.ledger.period(b["period_id"])
        return build_manifest(
            operation=OP_CORRECT,
            subject_type="bill",
            subject_id=bill_id,
            actor_role=actor_role,
            amounts={"amount_due": b["amount_due"], "retainage_this_period": b["retainage_this_period"], "cumulative_gross": b["cumulative_gross"]},
            bindings={
                "bill_hash": b["content_hash"], "bill_status": b["status"], "sequence": b["sequence"], "period_id": b["period_id"],
                "commitment_id": c["id"], "commitment_version": c["version"], "commitment_status": c["status"], "project_id": b["project_id"],
                "latest_bill_id": f["latest"]["id"] if f["latest"] else None,
                "payment_intents": [{"id": i["id"], "status": i["status"]} for i in f["intents"]],
                "credit_notes": [{"id": n["id"], "status": n["status"]} for n in f["credit_notes"]],
                "journals": [{"id": j["id"], "line_count": len(j["lines"]), "lines_fingerprint": lines_fingerprint(j["lines"]), "reversed_by": j["reversed_by"]}
                             for j in f["journals"]],
                "request": {"id": req["id"], "status": req["status"], "requested_by": req["requested_by"], "requested_at": req["requested_at"]},
                "reason": req["reason"],
                "restore_transfers": [{"lot_id": t["lot_id"], "amount": t["amount"]} for t in f["transfers"]],
                "unbill_lots": [l["id"] for l in f["first_billed"]],
                "supplier_invoice_id": b.get("supplier_invoice_id"),
                "effect": "reverses the bill's journals, marks it corrected and restores its stored material and SOV progress for a replacement bill",
                "target_rule": f"execute with period_id of an open period starting on or after {period['start_date']} (default: the latest open period)",
            },
            **self._scope(b["project_id"]),
        )

    def _apply_correction(self, bill_id: str, *, approval_id: str, manifest: dict[str, Any], actor: str, period_id: str | None) -> dict[str, Any]:
        bound = manifest.get("bindings") or {}
        with self.db.transaction() as conn:
            f = self._correction_facts(bill_id)
            if f["problems"]:
                raise BillIneligible(f"bill {bill_id} can no longer be corrected: " + "; ".join(f["problems"]))
            b, req = f["bill"], f["request"]
            if ((bound.get("request") or {}).get("id") != req["id"] or bound.get("reason") != req["reason"] or bound.get("bill_hash") != b["content_hash"]
                    or [j.get("id") for j in bound.get("journals") or []] != [j["id"] for j in f["journals"]]):
                raise BillIneligible(f"bill {bill_id} no longer matches the approved correction; nothing was reversed")
            self._approved_manifest(approval_id, OP_CORRECT, bill_id)
            self._refuse_spent_approval(approval_id)
            target = self._target_period(period_id, not_before=b["period_id"], what="correction")
            reason = req["reason"]
            reversals = []
            for j in f["journals"]:
                rev = self.ledger.reverse(j["id"], period_id=target["id"], posted_by=actor, reason=f"bill.correct {req['id']}: {reason}", approval_id=approval_id)
                reversals.append(rev["id"])
            now = utcnow_iso()
            conn.execute(
                """UPDATE bill_corrections SET status='executed', approval_id=?, period_id=?, reversal_journals_json=?, resolved_by=?, resolved_at=?,
                   resolution_note=? WHERE id=?""",
                (approval_id, target["id"], canonical_json(reversals), actor, now, f"reversed by {', '.join(reversals)} in period {target['id']}", req["id"]),
            )
            conn.execute("UPDATE bills SET status='corrected', correction_id=?, corrected_at=? WHERE id=?", (req["id"], now, bill_id))
            restored = []
            for t in f["transfers"]:
                lot = self.lot(t["lot_id"])
                remaining = money(money(lot["remaining_amount"]) + money(t["amount"]))
                conn.execute("UPDATE stored_material_lots SET remaining_amount=? WHERE id=?", (fmt(remaining), t["lot_id"]))
                restored.append({"lot_id": t["lot_id"], "amount": fmt(money(t["amount"])), "remaining": fmt(remaining)})
            unbilled = [l["id"] for l in f["first_billed"]]
            conn.execute("UPDATE stored_material_lots SET billed_bill_id=NULL WHERE billed_bill_id=?", (bill_id,))
            invalidated = self.approvals.invalidate_for_subject("bill", bill_id, reason=f"bill corrected under {approval_id}", actor=actor)
            self.audit.record(actor, "bill.corrected", "bill", bill_id, {
                "request_id": req["id"], "reason": reason, "approval_id": approval_id, "period_id": target["id"], "reversal_journals": reversals,
                "restored_lots": restored, "unbilled_lots": unbilled, "amount_due": b["amount_due"], "retainage_this_period": b["retainage_this_period"],
                "approvals_invalidated": invalidated,
            })
        return {"bill": bill_id, "status": "corrected", "request_id": req["id"], "reason": reason, "period_id": target["id"],
                "reversal_journals": reversals, "restored_lots": restored, "unbilled_lots": unbilled}

    # ---- retainage ------------------------------------------------------------ #

    def _retainage_retained(self, commitment_id: str) -> Decimal:
        rows = self.db.query("SELECT retainage_this_period FROM bills WHERE commitment_id=? AND status IN ('posted','paid')", (commitment_id,))
        return total(r["retainage_this_period"] for r in rows) if rows else ZERO

    def _retainage_released(self, commitment_id: str) -> Decimal:
        """Net 2050 debits on this commitment's release journals (a reversal nets out)."""
        rows = self.db.query(
            """SELECT l.debit, l.credit FROM journal_lines l JOIN journals j ON j.id = l.journal_id
               WHERE j.source_type='retainage_release' AND j.source_id=? AND l.account_code='2050'""",
            (commitment_id,),
        )
        return money(sum((money(r["debit"]) - money(r["credit"]) for r in rows), ZERO))

    def retainage_held(self, commitment_id: str) -> Decimal:
        """Retainage withheld on this commitment's posted bills less retainage released."""
        return money(self._retainage_retained(commitment_id) - self._retainage_released(commitment_id))

    def _closed_with_record(self, commitment_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
        """The commitment and its closure record; a commitment whose status says closed
        but that has no closure record (a raw status edit) is refused."""
        c = self.commitments.get(commitment_id)
        if c["status"] != "closed":
            raise BillError(f"retainage is released only after closeout acceptance: commitment {commitment_id} is {c['status']}, not closed")
        closure = self.commitments.closure(commitment_id)
        if closure is None:
            raise BillError(f"commitment {commitment_id} is marked closed but has no closure record; retainage is released only for a commitment closed through Commitments.close")
        return c, closure

    def release_retainage(self, *, commitment_id: str, period_id: str, approval_id: str, actor: str) -> dict[str, Any]:
        """After closeout acceptance, move withheld retainage into ordinary payables.
        Runs only against its own consumed ``retainage.release`` approval, once."""
        with self.db.transaction():
            c, closure = self._closed_with_record(commitment_id)
            held = self.retainage_held(commitment_id)
            if held <= 0:
                raise BillError("no retainage is held for this commitment")
            approved = self._approved_manifest(approval_id, "retainage.release", commitment_id)
            self._refuse_spent_approval(approval_id)
            bound = approved.get("bindings") or {}
            if bound.get("commitment_status") != "closed" or bound.get("commitment_version") != c["version"] or bound.get("closed_at") != closure["closed_at"]:
                raise BillError(
                    f"the approval was granted for commitment {commitment_id} {bound.get('commitment_status')} at version {bound.get('commitment_version')}; "
                    f"it is now {c['status']} at version {c['version']}; nothing was released"
                )
            if (approved.get("amounts") or {}).get("retainage_held") != fmt(held):
                raise BillError(f"the approved retainage {((approved.get('amounts') or {}).get('retainage_held'))} does not match the {fmt(held)} held; nothing was released")
            j = self.ledger.post(
                period_id=period_id,
                description=f"Retainage release on commitment {commitment_id}",
                lines=[
                    {"account": "2050", "debit": held, "project_id": c["project_id"], "party_id": c["supplier_id"], "memo": "retainage released"},
                    {"account": "2000", "credit": held, "project_id": c["project_id"], "party_id": c["supplier_id"], "memo": "retainage now payable"},
                ],
                source_type="retainage_release", source_id=commitment_id, source_version=str(c["version"]), posted_by=actor, approval_id=approval_id,
            )
            self.audit.record(actor, "retainage.released", "commitment", commitment_id, {"amount": fmt(held), "journal_id": j["id"], "approval_id": approval_id, "period_id": period_id})
        return {"commitment_id": commitment_id, "amount": fmt(held), "journal_id": j["id"]}

    def retainage_manifest(self, commitment_id: str, *, actor_role: str) -> dict[str, Any]:
        c, closure = self._closed_with_record(commitment_id)
        retained = self._retainage_retained(commitment_id)
        released = self._retainage_released(commitment_id)
        return build_manifest(
            operation="retainage.release",
            subject_type="commitment",
            subject_id=commitment_id,
            actor_role=actor_role,
            amounts={"retainage_held": retained - released},
            bindings={
                "commitment_version": c["version"], "commitment_status": c["status"], "closeout_required": True,
                "closed_at": closure["closed_at"], "closure_basis": closure["basis"], "closeout_approval_id": closure["closeout_approval_id"],
                "project_id": c["project_id"], "retained_on_posted_bills": fmt(retained), "released_to_date": fmt(released),
            },
            destination={"party_id": c["supplier_id"], "destination": c["supplier"]["destination"], "destination_version": c["supplier"]["destination_version"]},
            **self._scope(c["project_id"]),
        )

    # ---- subledgers ------------------------------------------------------------- #

    def _commitment_rows(self, project_id: str | None) -> list[dict[str, Any]]:
        if project_id:
            return self.db.query("SELECT id, project_id, supplier_id, status FROM commitments WHERE project_id=? ORDER BY created_at, id", (project_id,))
        return self.db.query("SELECT id, project_id, supplier_id, status FROM commitments ORDER BY created_at, id")

    def retainage_open_items(self, project_id: str | None = None) -> dict[str, Any]:
        """Retainage payable subledger: per commitment, retainage withheld on posted
        bills less retainage released, reconciled to the 2050 control account."""
        items = []
        sub = ZERO
        for c in self._commitment_rows(project_id):
            retained = self._retainage_retained(c["id"])
            released = self._retainage_released(c["id"])
            if retained == 0 and released == 0:
                continue
            held = money(retained - released)
            items.append({"commitment_id": c["id"], "project_id": c["project_id"], "supplier_id": c["supplier_id"], "commitment_status": c["status"],
                          "retained": fmt(retained), "released": fmt(released), "held": fmt(held)})
            sub += held
        control = self.ledger.balance("2050", project_id=project_id) if project_id else self.ledger.balance("2050")
        subledger = money(sub)
        return {"items": items, "subledger_total": fmt(subledger), "control_balance": fmt(control), "reconciled": subledger == control}

    def stored_material_items(self, project_id: str | None = None) -> dict[str, Any]:
        """Stored-materials subledger: the stored balance carried by each commitment's
        latest posted bill, reconciled to the 1300 control account."""
        items = []
        sub = ZERO
        for c in self._commitment_rows(project_id):
            b = self.db.one("SELECT id, sequence, cumulative_stored FROM bills WHERE commitment_id=? AND status IN ('posted','paid') ORDER BY sequence DESC LIMIT 1", (c["id"],))
            if b is None:
                continue
            stored = money(b["cumulative_stored"])
            posted = {r["id"] for r in self.db.query("SELECT id FROM bills WHERE commitment_id=? AND status IN ('posted','paid')", (c["id"],))}
            carried = [l for l in self.lots(c["id"]) if l["billed_bill_id"] in posted and money(l["remaining_amount"]) > 0]
            items.append({"commitment_id": c["id"], "project_id": c["project_id"], "supplier_id": c["supplier_id"], "bill_id": b["id"],
                          "sequence": b["sequence"], "stored": fmt(stored),
                          "lots_requiring_confirmation": [l["id"] for l in carried if l["eligibility_confirmation_required"]]})
            sub += stored
        control = self.ledger.balance("1300", project_id=project_id) if project_id else self.ledger.balance("1300")
        subledger = money(sub)
        return {"items": items, "subledger_total": fmt(subledger), "control_balance": fmt(control), "reconciled": subledger == control}

    def _retainage_payments(self) -> list[dict[str, Any]]:
        """Accepted or settled payments of released retainage with the supplier and project
        each one draws down -- the same scope ``payments`` gives them: a scoped intent
        books on its own project; a legacy intent (no payable account recorded,
        matched by its purpose label) on the payee's most recent commitment's project,
        as ``Payments._project_for`` posts it.  Each payment is counted once."""
        latest = "(SELECT c.project_id FROM commitments c WHERE c.supplier_id = pi.party_id ORDER BY c.created_at DESC LIMIT 1)"
        cols = {r["name"] for r in self.db.query("PRAGMA table_info(payment_intents)")}
        if {"source_type", "project_id", "payable_account"} <= cols:
            return self.db.query(
                f"""SELECT pi.id, pi.party_id, pi.amount,
                          CASE WHEN pi.source_type = 'retainage_release' THEN pi.project_id ELSE COALESCE(pi.project_id, {latest}) END AS project_id
                     FROM payment_intents pi
                    WHERE pi.bill_id IS NULL AND pi.status IN ('accepted','settled')
                      AND (pi.source_type = 'retainage_release' OR (pi.payable_account IS NULL AND pi.note LIKE 'retainage%'))
                    ORDER BY pi.created_at, pi.id"""
            )
        return self.db.query(
            f"""SELECT pi.id, pi.party_id, pi.amount, {latest} AS project_id FROM payment_intents pi
                 WHERE pi.bill_id IS NULL AND pi.status IN ('accepted','settled') AND pi.note LIKE 'retainage%' ORDER BY pi.created_at, pi.id"""
        )

    def _retainage_release_items(self, project_id: str | None) -> list[dict[str, Any]]:
        """Released-retainage AP items.  ``payments`` scopes a retainage payment to the
        supplier and project (not to one commitment), so payments are matched per
        (supplier, project) and allocated to that group's releases oldest first; any
        excess stays on the newest release (or on its own item when the group has no
        release).  Each group therefore nets exactly to its 2000 postings."""
        groups: dict[tuple[str, str], dict[str, Any]] = {}
        rows = self.db.query(
            """SELECT j.source_id AS commitment_id, MIN(j.id) AS first_journal FROM journals j
                WHERE j.source_type = 'retainage_release' GROUP BY j.source_id ORDER BY first_journal"""
        )
        for r in rows:
            c = self.db.one("SELECT id, project_id, supplier_id FROM commitments WHERE id=?", (r["commitment_id"],))
            if c is None:
                continue
            g = groups.setdefault((c["supplier_id"], c["project_id"]), {"releases": [], "paid": ZERO})
            g["releases"].append((c, self._retainage_released(c["id"])))
        for p in self._retainage_payments():
            if p["project_id"] is None:
                continue
            g = groups.setdefault((p["party_id"], p["project_id"]), {"releases": [], "paid": ZERO})
            g["paid"] = money(g["paid"] + money(p["amount"]))
        items: list[dict[str, Any]] = []
        for (supplier_id, pid), g in groups.items():
            if project_id and pid != project_id:
                continue
            unallocated = g["paid"]
            releases = g["releases"]
            for n, (c, released) in enumerate(releases):
                last = n == len(releases) - 1
                alloc = unallocated if last else min(max(released, ZERO), unallocated)
                unallocated = money(unallocated - alloc)
                first = self.db.scalar("SELECT MIN(posted_at) FROM journals WHERE source_type='retainage_release' AND source_id=?", (c["id"],))
                items.append({"bill_id": None, "commitment_id": c["id"], "project_id": pid, "supplier_id": supplier_id, "sequence": None,
                              "amount_due": fmt(released), "paid": fmt(alloc), "open": fmt(released - alloc), "kind": "retainage_release",
                              "due_date": _plus_days(first, DEFAULT_DUE_DAYS) if first else None, "supplier_invoice_number": None})
            if not releases and unallocated != 0:
                items.append({"bill_id": None, "commitment_id": None, "project_id": pid, "supplier_id": supplier_id, "sequence": None,
                              "amount_due": "0.00", "paid": fmt(unallocated), "open": fmt(-unallocated), "kind": "retainage_release",
                              "due_date": None, "supplier_invoice_number": None})
        return items

    @staticmethod
    def due_date_of(b: dict[str, Any]) -> tuple[str, str]:
        """A bill's due date and its basis: the attached supplier invoice's due date, else
        the bill's created date plus ``DEFAULT_DUE_DAYS``."""
        if b.get("due_date"):
            return b["due_date"], "supplier_invoice"
        return _plus_days(b["created_at"], DEFAULT_DUE_DAYS), f"bill_created_plus_{DEFAULT_DUE_DAYS}_days"

    def ap_open_items(self, project_id: str | None = None) -> dict[str, Any]:
        """Open AP derived from posted bills less settled payments and posted supplier credit
        notes, plus released retainage, reconciled to the AP control account.  Each bill item
        carries its due date (see ``due_date_of``), its supplier invoice number and whether
        that link still holds (``supplier_invoice_current``: False once the invoice was
        revised or rejected after it was attached, None for a bill without one)."""
        sql = "SELECT b.*, c.project_id AS pid, c.supplier_id AS sid FROM bills b JOIN commitments c ON c.id=b.commitment_id WHERE b.status IN ('posted','paid')"
        params: tuple = ()
        if project_id:
            sql += " AND c.project_id=?"
            params = (project_id,)
        items = []
        open_total = ZERO
        for b in self.db.query(sql, params):
            paid_total = self._paid(b["id"])
            credited = self.credited(b["id"])
            open_amt = money(b["amount_due"]) - paid_total - credited
            due, basis = self.due_date_of(b)
            link = self.supplier_invoice_state(b) if b.get("supplier_invoice_id") else None
            items.append({"bill_id": b["id"], "supplier_id": b["sid"], "sequence": b["sequence"], "amount_due": b["amount_due"], "paid": fmt(paid_total),
                          "credited": fmt(credited), "open": fmt(open_amt), "due_date": due, "due_date_basis": basis,
                          "supplier_invoice_id": b.get("supplier_invoice_id"), "supplier_invoice_number": b.get("supplier_invoice_number"),
                          "invoice_date": b.get("invoice_date"), "supplier_invoice_current": (not link["problems"]) if link else None})
            open_total += open_amt
        release_total = ZERO
        for item in self._retainage_release_items(project_id):
            release_total += money(item["open"])
            items.append(item)
        control = self.ledger.control_balance("ap", project_id=project_id) if project_id else self.ledger.control_balance("ap")
        subledger = money(open_total + release_total)
        return {"items": items, "subledger_total": fmt(subledger), "control_balance": fmt(control), "reconciled": subledger == control}

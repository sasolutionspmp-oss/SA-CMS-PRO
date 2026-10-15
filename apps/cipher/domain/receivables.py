"""Prime contracts, progress billing, sending, collections, prime retainage and the AR subledger.

The fixture policy recognizes revenue when the owner certifies progress and
bills it; the plan is explicit that billing is *not* universally the revenue
trigger, so every statement produced here is labeled SHADOW.

Controls (plan sections 5, 6 and 10):

* **Prime contract.**  ``set_prime_contract`` records a versioned contract value
  and retainage rate per project (latest version wins, versions never change; a
  value-only change keeps the current rate).  When a contract exists,
  certification refuses a certified cumulative above the contract value
  (overbilling) and uses the contract's retainage rate; a draft certified under
  an older contract version must be voided and re-certified.  The
  ``prime_bill.approve`` manifest binds the contract version and value, the bill
  hash, entity, currency, the billed chain it was computed on and a
  ``journal_preview`` of the exact lines posted.
* **Sending is its own authority.**  ``prime_bill.send`` (subject: prime bill)
  binds the bill hash, the customer, the channel (``mail-sink``) and the
  recipients; a change to any of them after approval makes the approval stale.
  ``send()`` no longer delivers anything directly.  A bill delivered by the old
  direct ``send()`` before this authority existed was recorded by the upgrade
  (``prime_bill_legacy_sends``) and counts as sent: it is never delivered again.
* **ACH mandates.**  An ACH collection needs the customer's active debit mandate,
  recorded against the content hash of an evidence revision filed on one of the
  customer's projects.  A missing or revoked mandate refuses the collection
  ("missing mandate"); checks and wires need none.  Database triggers enforce both
  halves on every insert path: a mandate row is accepted only with that owned
  evidence, and an ACH receipt only under an active mandate of the bill's customer
  that its evidence still backs.
* **Receipts and status.**  The database also refuses a receipt above what is open
  on its bill or retainage invoice, and keeps the stored ``collected`` status in step
  with the standing receipts (collected exactly while they cover the amount).
* **Prime retainage.**  ``prime_retainage.release`` (subject: project) binds the
  project's retainage receivable, the contract version, the latest prime bill
  sequence, the reversed records and the earliest period it may post in; it posts
  ``Dr 1100 / Cr 1150`` and records a retainage invoice that ``record_collection``
  collects like a prime bill.
* **Reversals.**  Posted records are corrected by reversing their journal
  (``journal.reverse``).  A prime bill, retainage invoice or receipt whose journal
  was reversed is read as credited: a reversed bill or invoice leaves nothing
  receivable and is never sent, collected or released; a reversed receipt no
  longer counts as collected and cannot be returned; and the next certification
  is computed on the prime bills that still stand, so reversed work can be billed
  again exactly once.
* **Cut-off.**  A collection is never dated in a period that starts before the
  bill or invoice it collects, a return never before its receipt, and a retainage
  release never before the latest prime bill that withheld the retainage it
  releases.
* **Complete AR subledger.**  ``ar_open_items`` covers prime bills, retainage
  invoices and every extra source the service registers (plugins that debit 1100
  and expose ``ar_open_items(project_id)``), tagging each item with its source,
  so the subledger reconciles to control account 1100.
  ``retainage_receivable_items`` reconciles 1150 the same way, in the same shape.

Dates, credits, write-offs and deposits (catalog entries ``receivables_dates_credits`` and
``receivables_dates_credits_guards``):

* **Dates.**  A prime bill carries an ``invoice_date`` (the date it posts, or the
  explicit ``invoice_date`` given to ``certify``: never later than the day it is
  certified, never before the start of the bill's period, and never before the invoice
  date of the latest standing prime bill on the project) and a ``due_date`` = invoice date + the customer's payment terms
  (``set_customer_terms``; 30 days when none are recorded), both fixed when it posts.
  ``prime_bill.approve`` binds the invoice-date basis and the terms version, so a
  terms change after approval makes the approval stale.  A retainage invoice is dated
  the day its release posts, with a due date on the same terms (bound by the release
  approval).  A receipt records its ``settlement_date`` (default: the day it is
  recorded; never in the future, never before the invoice it settles), distinct from
  the record time.  ``ar_open_items(project_id, as_of)`` gives each core item its
  invoice date, due date and days past due as of ``as_of`` (default today).  Bills
  posted before this entry keep no dates (nothing is invented for them).
* **Credit memos** (``prime_bill.credit_memo``, subject: a draft from
  ``prepare_credit_memo``, on a standing posted or sent bill, backed by evidence filed
  on the bill's project, for at most what is open): ``Dr 4000 / Cr 1100``, a revenue
  reduction under the fixture policy (SHADOW); the bill's open amount falls by it.
* **Write-offs** (``receivable.write_off``, controller authority, subject: a draft from
  ``prepare_write_off``): only a bill at least 90 days past its due date on the day the
  write-off is requested, for at most what is open; ``Dr 6100 / Cr 1100``.  The
  manifest binds the open amount, the days past due (as of the request date), the
  due date, the day the bill posted and the reason.  The request date is never later
  than today: approval and posting recompute the days past due from the bill's due date
  to the request date and refuse a draft dated ahead (the database refuses one recorded
  ahead of the real date, or posted from one).
* **Customer deposits.**  ``record_deposit`` books an advance ``Dr 1000 / Cr 2400``
  (ACH needs the active mandate, as for collections; the reference is unique across
  every receipt table) as an unapplied deposit.  ``receivable.apply_deposit`` (subject:
  a draft from ``prepare_deposit_application``, same customer and project, for at most
  both the deposit's unapplied balance and the bill's open amount) posts
  ``Dr 2400 / Cr 1100``.  ``deposits_items`` reconciles unapplied deposits to 2400.
* Each draft is single-use (one open draft per bill, or per deposit and bill), its
  approval binds the open amounts it was computed on (any receipt, credit or
  application in between makes it stale), and execution posts into an open period
  that does not start before the bill's (or the deposit's) period.  The database backs
  every rule: drafts are recorded as drafts, post only under their consumed approval
  with their own journal, never beyond what is open, and neither a deposit with standing
  applications nor a prime bill with standing credit memos, write-offs or deposit
  applications can be reversed (its reversal request is refused, and so is the reversing
  journal): reverse the adjustments first.  A credit memo, write-off or application whose
  journal is reversed (``journal.reverse``) no longer counts: the receivable (and the
  deposit balance) is restored, exactly as the ledger shows.
* **Sending states the balance.**  The ``prime_bill.send`` message carries what was
  received, credited, written off and applied from deposits, and the balance due; the
  approval binds it, so any of them changing after approval makes the send stale.

Posting rules (fixture policy ``cipher-posting-rules/1``):

* prime bill:          Dr 1100 amount due, Dr 1150 retainage withheld (Cr 1150 for a
                       retainage reduction) / Cr 4000 certified progress
* retainage release:   Dr 1100 / Cr 1150 (the project's whole retainage receivable)
* collection:          Dr 1000 net, Dr 6000 fee / Cr 1100 gross
* late return:         Dr 1100 / Cr 1000 in the current open period (the receipt stays)
* credit memo:         Dr 4000 / Cr 1100 (SHADOW revenue reduction)
* write-off:           Dr 6100 bad debt expense / Cr 1100
* customer deposit:    Dr 1000 / Cr 2400 customer deposits
* deposit application: Dr 2400 / Cr 1100
"""
from __future__ import annotations

import datetime as _dt
from decimal import Decimal
from typing import Any, Callable

from ..core.approvals import Approvals, StaleApprovalError, build_manifest
from ..core.audit import Audit
from ..core.db import Database, register_schema_version
from ..core.ids import canonical_json, hash_json, loads, new_id, utcnow, utcnow_iso
from ..core.money import ZERO, MoneyError, fmt, money, pct, rate, total
from .ledger import RULE_VERSION, Ledger

# --------------------------------------------------------------------------- #
# Schema (catalog entry ``receivables_controls``)                              #
# --------------------------------------------------------------------------- #
# The foundation schema is applied history (append-only), so the receivables
# controls arrive as their own catalog entry, registered at import time.  Never
# edit these statements once applied; add a new uniquely named entry instead.
# Every statement must also apply to an existing workspace: nothing here may
# fail on rows that earlier code was allowed to write.


def _changed(columns: tuple[str, ...]) -> str:
    return " OR ".join(f"NEW.{c} IS NOT OLD.{c}" for c in columns)


def _live(alias: str) -> str:
    """SQL: a posted prime bill (``alias``) whose journal has not been reversed."""
    return (f"{alias}.status IN ('posted','sent','collected') "
            f"AND NOT EXISTS (SELECT 1 FROM journals rv WHERE rv.reversal_of = {alias}.journal_id)")


_PRIME_BILL_FIXED = (
    "id", "project_id", "customer_id", "period_id", "sequence", "certified_cumulative", "retainage_rate", "retainage_cumulative",
    "prior_net", "amount_due", "revenue_this_period", "content_hash", "created_at", "contract_version",
)
_COLLECTION_FIXED = ("id", "prime_bill_id", "amount", "fee", "journal_id", "provider_ref", "received_at", "method", "mandate_id")
_RETAINAGE_INVOICE_FIXED = (
    "id", "project_id", "customer_id", "period_id", "sequence", "amount", "contract_version", "through_prime_bill_sequence",
    "content_hash", "approval_id", "journal_id", "created_at", "created_by",
)
_RETAINAGE_COLLECTION_FIXED = (
    "id", "retainage_invoice_id", "amount", "fee", "method", "mandate_id", "journal_id", "provider_ref", "received_at", "recorded_by",
)
_MANDATE_FIXED = ("id", "customer_id", "mandate_ref", "evidence_hash", "evidence_revision_id", "recorded_at", "recorded_by")

# a new receipt's reference is unique across both core receipt tables, ignoring case
_REF_CLASH = (
    "EXISTS (SELECT 1 FROM collections x WHERE x.provider_ref = NEW.provider_ref COLLATE NOCASE) "
    "OR EXISTS (SELECT 1 FROM prime_retainage_collections x WHERE x.provider_ref = NEW.provider_ref COLLATE NOCASE)"
)
# a receipt records its own standing collection journal, crediting 1100 by its amount
_OWN_RECEIPT_JOURNAL = (
    "NEW.journal_id IS NULL OR NOT EXISTS (SELECT 1 FROM journals j WHERE j.id = NEW.journal_id AND j.source_type = 'collection' "
    "AND j.source_id = NEW.provider_ref AND j.reversal_of IS NULL) "
    "OR NEW.amount IS NOT (SELECT l.credit FROM journal_lines l WHERE l.journal_id = NEW.journal_id AND l.account_code = '1100' ORDER BY l.line_no LIMIT 1)"
)
_RETURN_JOURNAL_OK = (
    "EXISTS (SELECT 1 FROM journals j WHERE j.id = NEW.return_journal_id AND j.source_type = 'collection_return' "
    "AND j.source_id = OLD.provider_ref AND j.reversal_of IS NULL)"
)

CONTROLS_SCHEMA_NAME = "receivables_controls"
CONTROLS_SCHEMA_STATEMENTS = [
    # =============================== tables and columns =============================== #
    # ---- prime contracts: versioned, latest wins, never edited ----
    """CREATE TABLE prime_contracts (
        id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES projects(id),
        version INTEGER NOT NULL CHECK (version >= 1),
        contract_value TEXT NOT NULL,
        retainage_rate TEXT NOT NULL,
        content_hash TEXT NOT NULL,
        created_at TEXT NOT NULL,
        created_by TEXT NOT NULL,
        UNIQUE (project_id, version)
    )""",
    # ---- customer billing recipients: versioned, latest wins ----
    """CREATE TABLE customer_billing_recipients (
        id TEXT PRIMARY KEY,
        customer_id TEXT NOT NULL REFERENCES parties(id),
        version INTEGER NOT NULL CHECK (version >= 1),
        recipients_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        created_by TEXT NOT NULL,
        UNIQUE (customer_id, version)
    )""",
    # ---- customer ACH debit mandates ----
    """CREATE TABLE customer_mandates (
        id TEXT PRIMARY KEY,
        customer_id TEXT NOT NULL REFERENCES parties(id),
        mandate_ref TEXT NOT NULL,
        evidence_hash TEXT NOT NULL,
        evidence_revision_id TEXT NOT NULL REFERENCES document_revisions(id),
        status TEXT NOT NULL CHECK (status IN ('active','revoked')),
        recorded_at TEXT NOT NULL,
        recorded_by TEXT NOT NULL,
        revoked_at TEXT,
        revoked_by TEXT,
        revoke_reason TEXT
    )""",
    # ---- prime bills carry the contract version they were certified under ----
    "ALTER TABLE prime_bills ADD COLUMN contract_version INTEGER",
    # ---- sends to the synthetic mail sink: one per bill, immutable ----
    """CREATE TABLE prime_bill_sends (
        id TEXT PRIMARY KEY,
        prime_bill_id TEXT NOT NULL UNIQUE REFERENCES prime_bills(id),
        approval_id TEXT NOT NULL REFERENCES approvals(id),
        channel TEXT NOT NULL,
        recipients_json TEXT NOT NULL,
        bill_hash TEXT NOT NULL,
        message_hash TEXT NOT NULL,
        sent_at TEXT NOT NULL,
        sent_by TEXT NOT NULL
    )""",
    # ---- retainage invoices (released prime retainage) ----
    """CREATE TABLE prime_retainage_invoices (
        id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES projects(id),
        customer_id TEXT NOT NULL REFERENCES parties(id),
        period_id TEXT NOT NULL REFERENCES periods(id),
        sequence INTEGER NOT NULL,
        amount TEXT NOT NULL,
        status TEXT NOT NULL CHECK (status IN ('open','collected')),
        contract_version INTEGER,
        through_prime_bill_sequence INTEGER NOT NULL,
        content_hash TEXT NOT NULL,
        approval_id TEXT NOT NULL UNIQUE REFERENCES approvals(id),
        journal_id TEXT NOT NULL UNIQUE REFERENCES journals(id),
        created_at TEXT NOT NULL,
        created_by TEXT NOT NULL,
        UNIQUE (project_id, sequence)
    )""",
    # ---- collections on prime bills: method and mandate ----
    "ALTER TABLE collections ADD COLUMN method TEXT",
    "ALTER TABLE collections ADD COLUMN mandate_id TEXT REFERENCES customer_mandates(id)",
    # ---- collections on retainage invoices ----
    """CREATE TABLE prime_retainage_collections (
        id TEXT PRIMARY KEY,
        retainage_invoice_id TEXT NOT NULL REFERENCES prime_retainage_invoices(id),
        amount TEXT NOT NULL,
        fee TEXT NOT NULL,
        method TEXT NOT NULL CHECK (method IN ('ach','check','wire')),
        mandate_id TEXT REFERENCES customer_mandates(id),
        status TEXT NOT NULL CHECK (status IN ('received','returned')),
        journal_id TEXT NOT NULL UNIQUE REFERENCES journals(id),
        return_journal_id TEXT REFERENCES journals(id),
        provider_ref TEXT NOT NULL,
        received_at TEXT NOT NULL,
        returned_at TEXT,
        recorded_by TEXT NOT NULL
    )""",
    # ==================================== indexes ===================================== #
    "CREATE UNIQUE INDEX customer_mandates_ref ON customer_mandates (mandate_ref COLLATE NOCASE)",
    "CREATE INDEX customer_mandates_customer ON customer_mandates (customer_id, status)",
    # Workspaces written before this entry may already hold receipt references that
    # differ only by case (the earlier check was case-sensitive), so a UNIQUE index here
    # would fail the upgrade and leave the workspace unopenable.  New receipts are held
    # unique by the insert triggers below; old clashes are reported by
    # Receivables.receipt_reference_conflicts().
    "CREATE INDEX collections_provider_ref ON collections (provider_ref COLLATE NOCASE)",
    "CREATE UNIQUE INDEX prime_retainage_collections_ref ON prime_retainage_collections (provider_ref COLLATE NOCASE)",
    # ==================================== triggers ==================================== #
    # ---- prime contracts ----
    f"""CREATE TRIGGER prime_contracts_insert BEFORE INSERT ON prime_contracts
        BEGIN
            SELECT CASE
                WHEN NEW.version IS NOT COALESCE((SELECT MAX(version) FROM prime_contracts WHERE project_id = NEW.project_id), 0) + 1
                THEN RAISE(ABORT, 'prime contract versions are contiguous')
                WHEN NOT (CAST(NEW.contract_value AS REAL) > 0) OR NOT (CAST(NEW.retainage_rate AS REAL) BETWEEN 0 AND 1)
                THEN RAISE(ABORT, 'a prime contract needs a positive value and a retainage rate between 0 and 1')
                WHEN CAST(NEW.contract_value AS REAL) + 0.005 < MAX(
                    (SELECT TOTAL(CAST(b.revenue_this_period AS REAL)) FROM prime_bills b WHERE b.project_id = NEW.project_id AND {_live('b')}),
                    (SELECT COALESCE(MAX(CAST(d.certified_cumulative AS REAL)), 0) FROM prime_bills d WHERE d.project_id = NEW.project_id AND d.status = 'draft'))
                THEN RAISE(ABORT, 'overbilling: a prime contract value cannot be below what is already certified')
            END;
        END""",
    "CREATE TRIGGER prime_contracts_no_update BEFORE UPDATE ON prime_contracts BEGIN SELECT RAISE(ABORT, 'prime contract versions are immutable; set a new version'); END",
    "CREATE TRIGGER prime_contracts_no_delete BEFORE DELETE ON prime_contracts BEGIN SELECT RAISE(ABORT, 'prime contract versions are immutable; set a new version'); END",
    # ---- billing recipients ----
    "CREATE TRIGGER customer_billing_recipients_no_update BEFORE UPDATE ON customer_billing_recipients BEGIN SELECT RAISE(ABORT, 'billing recipient versions are immutable'); END",
    "CREATE TRIGGER customer_billing_recipients_no_delete BEFORE DELETE ON customer_billing_recipients BEGIN SELECT RAISE(ABORT, 'billing recipient versions are immutable'); END",
    # ---- mandates ----
    """CREATE TRIGGER customer_mandates_recorded_active BEFORE INSERT ON customer_mandates
        WHEN NEW.status IS NOT 'active' OR NEW.revoked_at IS NOT NULL OR NEW.revoked_by IS NOT NULL
        BEGIN SELECT RAISE(ABORT, 'a mandate is recorded active'); END""",
    f"""CREATE TRIGGER customer_mandates_revoke_only BEFORE UPDATE ON customer_mandates
        WHEN {_changed(_MANDATE_FIXED)}
          OR NOT (OLD.status = 'active' AND NEW.status = 'revoked' AND NEW.revoked_at IS NOT NULL AND NEW.revoked_by IS NOT NULL)
        BEGIN SELECT RAISE(ABORT, 'a mandate only moves from active to revoked'); END""",
    "CREATE TRIGGER customer_mandates_no_delete BEFORE DELETE ON customer_mandates BEGIN SELECT RAISE(ABORT, 'mandates are never deleted; revoke instead'); END",
    # ---- sends: only a standing posted bill, under its consumed prime_bill.send approval ----
    """CREATE TRIGGER prime_bill_sends_insert BEFORE INSERT ON prime_bill_sends
        BEGIN
            SELECT CASE
                WHEN (SELECT status FROM prime_bills WHERE id = NEW.prime_bill_id) IS NOT 'posted'
                THEN RAISE(ABORT, 'only a posted prime bill can be sent')
                WHEN EXISTS (SELECT 1 FROM prime_bills b JOIN journals rv ON rv.reversal_of = b.journal_id WHERE b.id = NEW.prime_bill_id)
                THEN RAISE(ABORT, 'a reversed prime bill is never sent')
                WHEN NEW.bill_hash IS NOT (SELECT content_hash FROM prime_bills WHERE id = NEW.prime_bill_id)
                THEN RAISE(ABORT, 'a send records the hash of the bill it delivers')
                WHEN NOT EXISTS (SELECT 1 FROM approvals a WHERE a.id = NEW.approval_id AND a.operation = 'prime_bill.send'
                                 AND a.subject_id = NEW.prime_bill_id AND a.status = 'consumed')
                THEN RAISE(ABORT, 'a prime bill is sent only under its consumed prime_bill.send approval')
            END;
        END""",
    "CREATE TRIGGER prime_bill_sends_no_update BEFORE UPDATE ON prime_bill_sends BEGIN SELECT RAISE(ABORT, 'sent records are immutable'); END",
    "CREATE TRIGGER prime_bill_sends_no_delete BEFORE DELETE ON prime_bill_sends BEGIN SELECT RAISE(ABORT, 'sent records are immutable'); END",
    # ---- prime bills: recorded as drafts, fixed amounts, guarded status ----
    """CREATE TRIGGER prime_bills_recorded_draft BEFORE INSERT ON prime_bills
        WHEN NEW.status IS NOT 'draft' OR NEW.approval_id IS NOT NULL OR NEW.journal_id IS NOT NULL
        BEGIN SELECT RAISE(ABORT, 'a prime bill is recorded as a draft; it is posted only through prime_bill.approve'); END""",
    f"""CREATE TRIGGER prime_bills_guard BEFORE UPDATE ON prime_bills
        BEGIN
            SELECT CASE
                WHEN {_changed(_PRIME_BILL_FIXED)}
                THEN RAISE(ABORT, 'prime bill amounts and identity are immutable once certified')
                WHEN (OLD.approval_id IS NOT NULL AND NEW.approval_id IS NOT OLD.approval_id)
                  OR (OLD.journal_id IS NOT NULL AND NEW.journal_id IS NOT OLD.journal_id)
                THEN RAISE(ABORT, 'a posted prime bill keeps its approval and journal')
                WHEN NEW.status IS NOT OLD.status AND NOT (
                       (OLD.status = 'draft' AND NEW.status IN ('posted','void'))
                    OR (OLD.status = 'posted' AND NEW.status IN ('sent','collected'))
                    OR (OLD.status = 'sent' AND NEW.status = 'collected')
                    OR (OLD.status = 'collected' AND NEW.status IN ('posted','sent')))
                THEN RAISE(ABORT, 'invalid prime bill status transition')
                WHEN NEW.status IN ('posted','sent','collected') AND NEW.journal_id IS NULL
                THEN RAISE(ABORT, 'a posted prime bill needs its journal')
                WHEN OLD.status = 'draft' AND NEW.status = 'posted' AND NOT EXISTS (
                    SELECT 1 FROM approvals a WHERE a.id = NEW.approval_id AND a.operation = 'prime_bill.approve'
                    AND a.subject_id = NEW.id AND a.status = 'consumed')
                THEN RAISE(ABORT, 'a prime bill is posted only under its consumed prime_bill.approve approval')
                WHEN OLD.journal_id IS NULL AND NEW.journal_id IS NOT NULL AND NOT EXISTS (
                    SELECT 1 FROM journals j WHERE j.id = NEW.journal_id AND j.source_type = 'prime_bill' AND j.source_id = NEW.id
                    AND j.reversal_of IS NULL)
                THEN RAISE(ABORT, 'a prime bill posts with its own journal')
                WHEN NEW.status = 'sent' AND OLD.status IS NOT 'sent'
                     AND NOT EXISTS (SELECT 1 FROM prime_bill_sends s WHERE s.prime_bill_id = NEW.id)
                THEN RAISE(ABORT, 'a prime bill is sent only through a recorded prime_bill.send')
                WHEN OLD.status = 'collected' AND NEW.status = 'posted'
                     AND EXISTS (SELECT 1 FROM prime_bill_sends s WHERE s.prime_bill_id = NEW.id)
                THEN RAISE(ABORT, 'a sent prime bill returns to sent, not posted')
                WHEN NEW.status = 'collected' AND OLD.status IS NOT 'collected'
                     AND NOT EXISTS (SELECT 1 FROM collections c WHERE c.prime_bill_id = NEW.id AND c.status = 'received')
                THEN RAISE(ABORT, 'a prime bill is collected only by recorded collections')
            END;
        END""",
    "CREATE TRIGGER prime_bills_no_delete BEFORE DELETE ON prime_bills BEGIN SELECT RAISE(ABORT, 'prime bills are never deleted; void a draft instead'); END",
    # ---- retainage invoices: only under a consumed release approval, with their own journal ----
    """CREATE TRIGGER prime_retainage_invoices_insert BEFORE INSERT ON prime_retainage_invoices
        BEGIN
            SELECT CASE
                WHEN NEW.status IS NOT 'open' THEN RAISE(ABORT, 'a retainage invoice is recorded open')
                WHEN NOT EXISTS (SELECT 1 FROM approvals a WHERE a.id = NEW.approval_id AND a.operation = 'prime_retainage.release'
                                 AND a.subject_id = NEW.project_id AND a.status = 'consumed')
                THEN RAISE(ABORT, 'a retainage invoice is recorded only under its consumed prime_retainage.release approval')
                WHEN NOT EXISTS (SELECT 1 FROM journals j WHERE j.id = NEW.journal_id AND j.source_type = 'prime_retainage_release'
                                 AND j.source_id = NEW.id AND j.approval_id IS NEW.approval_id AND j.reversal_of IS NULL)
                THEN RAISE(ABORT, 'a retainage invoice records its own release journal')
                WHEN NEW.amount IS NOT (SELECT l.debit FROM journal_lines l WHERE l.journal_id = NEW.journal_id AND l.account_code = '1100'
                                        ORDER BY l.line_no LIMIT 1)
                THEN RAISE(ABORT, 'a retainage invoice is for the amount its release journal debits to 1100')
            END;
        END""",
    f"""CREATE TRIGGER prime_retainage_invoices_guard BEFORE UPDATE ON prime_retainage_invoices
        BEGIN
            SELECT CASE
                WHEN {_changed(_RETAINAGE_INVOICE_FIXED)} OR NEW.status IS OLD.status
                THEN RAISE(ABORT, 'a retainage invoice only moves between open and collected')
                WHEN NEW.status = 'collected' AND NOT EXISTS (
                    SELECT 1 FROM prime_retainage_collections c WHERE c.retainage_invoice_id = NEW.id AND c.status = 'received')
                THEN RAISE(ABORT, 'a retainage invoice is collected only by recorded collections')
            END;
        END""",
    "CREATE TRIGGER prime_retainage_invoices_no_delete BEFORE DELETE ON prime_retainage_invoices BEGIN SELECT RAISE(ABORT, 'retainage invoices are never deleted'); END",
    # ---- collections on prime bills ----
    f"""CREATE TRIGGER collections_insert BEFORE INSERT ON collections
        BEGIN
            SELECT CASE
                WHEN NEW.status IS NOT 'received' THEN RAISE(ABORT, 'a collection is recorded received')
                WHEN NEW.method IS NULL OR NEW.method NOT IN ('ach','check','wire')
                THEN RAISE(ABORT, 'collection method must be ach, check or wire')
                WHEN NEW.method = 'ach' AND NOT EXISTS (
                    SELECT 1 FROM customer_mandates m JOIN prime_bills b ON b.customer_id = m.customer_id
                    WHERE m.id = NEW.mandate_id AND b.id = NEW.prime_bill_id AND m.status = 'active')
                THEN RAISE(ABORT, 'missing mandate: an ACH collection needs an active customer debit mandate')
                WHEN {_REF_CLASH}
                THEN RAISE(ABORT, 'a receipt reference is recorded once, ignoring case')
                WHEN {_OWN_RECEIPT_JOURNAL}
                THEN RAISE(ABORT, 'a collection records its own collection journal crediting 1100 by its amount')
            END;
        END""",
    f"""CREATE TRIGGER collections_guard BEFORE UPDATE ON collections
        WHEN {_changed(_COLLECTION_FIXED)}
          OR NOT (OLD.status = 'received' AND NEW.status = 'returned' AND OLD.return_journal_id IS NULL AND NEW.return_journal_id IS NOT NULL)
          OR NOT {_RETURN_JOURNAL_OK}
        BEGIN SELECT RAISE(ABORT, 'a collection only moves once, from received to returned, with its own return journal'); END""",
    "CREATE TRIGGER collections_no_delete BEFORE DELETE ON collections BEGIN SELECT RAISE(ABORT, 'collections are never deleted'); END",
    # ---- collections on retainage invoices ----
    f"""CREATE TRIGGER prime_retainage_collections_insert BEFORE INSERT ON prime_retainage_collections
        BEGIN
            SELECT CASE
                WHEN NEW.status IS NOT 'received' THEN RAISE(ABORT, 'a collection is recorded received')
                WHEN NEW.method = 'ach' AND NOT EXISTS (
                    SELECT 1 FROM customer_mandates m JOIN prime_retainage_invoices i ON i.customer_id = m.customer_id
                    WHERE m.id = NEW.mandate_id AND i.id = NEW.retainage_invoice_id AND m.status = 'active')
                THEN RAISE(ABORT, 'missing mandate: an ACH collection needs an active customer debit mandate')
                WHEN {_REF_CLASH}
                THEN RAISE(ABORT, 'a receipt reference is recorded once, ignoring case')
                WHEN {_OWN_RECEIPT_JOURNAL}
                THEN RAISE(ABORT, 'a collection records its own collection journal crediting 1100 by its amount')
            END;
        END""",
    f"""CREATE TRIGGER prime_retainage_collections_guard BEFORE UPDATE ON prime_retainage_collections
        WHEN {_changed(_RETAINAGE_COLLECTION_FIXED)}
          OR NOT (OLD.status = 'received' AND NEW.status = 'returned' AND OLD.return_journal_id IS NULL AND NEW.return_journal_id IS NOT NULL)
          OR NOT {_RETURN_JOURNAL_OK}
        BEGIN SELECT RAISE(ABORT, 'a collection only moves once, from received to returned, with its own return journal'); END""",
    "CREATE TRIGGER prime_retainage_collections_no_delete BEFORE DELETE ON prime_retainage_collections BEGIN SELECT RAISE(ABORT, 'collections are never deleted'); END",
]
register_schema_version(CONTROLS_SCHEMA_NAME, CONTROLS_SCHEMA_STATEMENTS)

# --------------------------------------------------------------------------- #
# Schema (catalog entry ``receivables_controls_guards``)                       #
# --------------------------------------------------------------------------- #
# ``receivables_controls`` is applied history, so the guards added after its review
# arrive as their own append-only entry (never edit either entry once applied).  Like
# the entry before it, every statement applies to a workspace written earlier: the
# triggers check new writes only, and the one data statement records what earlier code
# already did (bills delivered by the old direct ``send()``).


def _mandate_backed(alias: str) -> str:
    """SQL: mandate ``alias`` is backed by the evidence revision it names, whose content
    hash it records, filed on a project of the mandate's own customer."""
    return (
        "EXISTS (SELECT 1 FROM document_revisions r JOIN documents d ON d.id = r.document_id JOIN projects p ON p.id = d.project_id "
        f"WHERE r.id = {alias}.evidence_revision_id AND r.content_hash = {alias}.evidence_hash AND p.customer_id = {alias}.customer_id)"
    )


def _standing_received(table: str, fk: str, key: str) -> str:
    """SQL: what the receipts in ``table`` on record ``key`` credit to 1100 now: a receipt's
    amount while its journal stands, less it while its return journal stands (exactly
    ``Receivables._receipt``)."""
    return (
        "(SELECT TOTAL("
        "(CASE WHEN x.journal_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM journals rv WHERE rv.reversal_of = x.journal_id) "
        "THEN CAST(x.amount AS REAL) ELSE 0 END) - "
        "(CASE WHEN x.return_journal_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM journals rv WHERE rv.reversal_of = x.return_journal_id) "
        f"THEN CAST(x.amount AS REAL) ELSE 0 END)) FROM {table} x WHERE x.{fk} = {key})"
    )


def _open_on(alias: str, amount_col: str, table: str, fk: str) -> str:
    """SQL: what stays open on record ``alias``: its amount less standing receipts, and
    nothing at all once its own journal is reversed (``Receivables._bill_balance``)."""
    amount = f"CAST({alias}.{amount_col} AS REAL)"
    return (f"({amount} - {_standing_received(table, fk, alias + '.id')} - "
            f"(CASE WHEN EXISTS (SELECT 1 FROM journals rv WHERE rv.reversal_of = {alias}.journal_id) THEN {amount} ELSE 0 END))")


_MISSING_BACKED_MANDATE = ("missing mandate: an ACH collection needs a debit mandate backed by the evidence revision it records, "
                           "filed on a project of its customer")
_BILL_RECEIVED = _standing_received("collections", "prime_bill_id", "NEW.id")
_INVOICE_RECEIVED = _standing_received("prime_retainage_collections", "retainage_invoice_id", "NEW.id")

CONTROLS_GUARDS_SCHEMA_NAME = "receivables_controls_guards"
CONTROLS_GUARDS_SCHEMA_STATEMENTS = [
    # ---- a mandate is recorded only against owned evidence (every insert path) ----
    f"""CREATE TRIGGER customer_mandates_owned_evidence BEFORE INSERT ON customer_mandates
        WHEN NOT {_mandate_backed('NEW')}
        BEGIN SELECT RAISE(ABORT, 'a mandate records the content hash of its evidence revision, filed on a project of its own customer'); END""",
    # ---- receipts: an ACH mandate backed by owned evidence; never more than is open ----
    f"""CREATE TRIGGER collections_insert_guards BEFORE INSERT ON collections
        BEGIN
            SELECT CASE
                WHEN NEW.method = 'ach' AND NOT EXISTS (SELECT 1 FROM customer_mandates m WHERE m.id = NEW.mandate_id AND {_mandate_backed('m')})
                THEN RAISE(ABORT, '{_MISSING_BACKED_MANDATE}')
                WHEN NOT EXISTS (SELECT 1 FROM prime_bills b WHERE b.id = NEW.prime_bill_id AND b.status IN ('posted','sent','collected'))
                THEN RAISE(ABORT, 'a receipt is recorded only on a posted prime bill')
                WHEN CAST(NEW.amount AS REAL) > (SELECT {_open_on('b', 'amount_due', 'collections', 'prime_bill_id')} FROM prime_bills b WHERE b.id = NEW.prime_bill_id) + 0.005
                THEN RAISE(ABORT, 'a receipt cannot exceed what is open on its prime bill')
            END;
        END""",
    f"""CREATE TRIGGER prime_retainage_collections_insert_guards BEFORE INSERT ON prime_retainage_collections
        BEGIN
            SELECT CASE
                WHEN NEW.method = 'ach' AND NOT EXISTS (SELECT 1 FROM customer_mandates m WHERE m.id = NEW.mandate_id AND {_mandate_backed('m')})
                THEN RAISE(ABORT, '{_MISSING_BACKED_MANDATE}')
                WHEN CAST(NEW.amount AS REAL) > (SELECT {_open_on('i', 'amount', 'prime_retainage_collections', 'retainage_invoice_id')}
                                                 FROM prime_retainage_invoices i WHERE i.id = NEW.retainage_invoice_id) + 0.005
                THEN RAISE(ABORT, 'a receipt cannot exceed what is open on its retainage invoice')
            END;
        END""",
    # ---- status follows the receipts: collected exactly while they cover the amount ----
    f"""CREATE TRIGGER prime_bills_status_follows_receipts BEFORE UPDATE OF status ON prime_bills
        WHEN NEW.status IS NOT OLD.status AND (
               (NEW.status = 'collected' AND {_BILL_RECEIVED} + 0.005 < CAST(NEW.amount_due AS REAL))
            OR (OLD.status = 'collected' AND {_BILL_RECEIVED} + 0.005 >= CAST(NEW.amount_due AS REAL)))
        BEGIN SELECT RAISE(ABORT, 'a prime bill is collected exactly while its standing receipts cover its amount due'); END""",
    f"""CREATE TRIGGER prime_retainage_invoices_status_follows_receipts BEFORE UPDATE OF status ON prime_retainage_invoices
        WHEN NEW.status IS NOT OLD.status AND (
               (NEW.status = 'collected' AND {_INVOICE_RECEIVED} + 0.005 < CAST(NEW.amount AS REAL))
            OR (OLD.status = 'collected' AND {_INVOICE_RECEIVED} + 0.005 >= CAST(NEW.amount AS REAL)))
        BEGIN SELECT RAISE(ABORT, 'a retainage invoice is collected exactly while its standing receipts cover its amount'); END""",
    # ---- bills delivered by the old direct send() stay delivered ----
    """CREATE TABLE prime_bill_legacy_sends (
        prime_bill_id TEXT PRIMARY KEY REFERENCES prime_bills(id),
        detected_from TEXT NOT NULL,
        sent_at TEXT,
        recorded_at TEXT NOT NULL
    )""",
    """INSERT INTO prime_bill_legacy_sends (prime_bill_id, detected_from, sent_at, recorded_at)
        SELECT b.id, CASE WHEN a.first_ts IS NOT NULL THEN 'audit: prime_bill.sent' ELSE 'status: sent' END, a.first_ts,
               strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
        FROM prime_bills b
        LEFT JOIN (SELECT entity_id, MIN(ts) AS first_ts FROM audit_log WHERE entity_type = 'prime_bill' AND action = 'prime_bill.sent'
                   GROUP BY entity_id) a ON a.entity_id = b.id
        WHERE NOT EXISTS (SELECT 1 FROM prime_bill_sends s WHERE s.prime_bill_id = b.id)
          AND (b.status = 'sent' OR a.entity_id IS NOT NULL)""",
    "CREATE TRIGGER prime_bill_legacy_sends_closed BEFORE INSERT ON prime_bill_legacy_sends BEGIN SELECT RAISE(ABORT, 'legacy sends are recorded once, by the upgrade that made sending its own authority'); END",
    "CREATE TRIGGER prime_bill_legacy_sends_no_update BEFORE UPDATE ON prime_bill_legacy_sends BEGIN SELECT RAISE(ABORT, 'legacy send records are immutable'); END",
    "CREATE TRIGGER prime_bill_legacy_sends_no_delete BEFORE DELETE ON prime_bill_legacy_sends BEGIN SELECT RAISE(ABORT, 'legacy send records are immutable'); END",
]
register_schema_version(CONTROLS_GUARDS_SCHEMA_NAME, CONTROLS_GUARDS_SCHEMA_STATEMENTS)

# --------------------------------------------------------------------------- #
# Schema (catalog entry ``receivables_dates_credits``)                         #
# --------------------------------------------------------------------------- #
# Document dates, credit memos, write-offs and customer deposits arrive as their own
# append-only entry (never edit it, or the two entries before it, once applied).  Every
# statement applies to a workspace written earlier: the new columns start NULL (bills,
# invoices and receipts recorded before stay undated rather than being given invented
# dates) and the triggers check new writes only.  Amounts are compared as REAL with a
# half-cent tolerance, like the guards before them; Python computes the exact values.

TERMS_MAX_DAYS = 365
WRITE_OFF_MIN_DAYS_PAST_DUE = 90
_ADJUSTMENT_TABLES = ("prime_bill_credit_memos", "receivable_write_offs", "deposit_applications")
# Stored schema text: applied workspaces checksum it, so its spelling stays as first applied.
_DRAFT_COLUMNS = """status TEXT NOT NULL CHECK (status IN ('draft','posted','cancelled')),
        created_at TEXT NOT NULL,
        created_by TEXT NOT NULL,
        approval_id TEXT UNIQUE REFERENCES approvals(id),
        journal_id TEXT UNIQUE REFERENCES journals(id),
        period_id TEXT REFERENCES periods(id),
        posted_at TEXT,
        posted_by TEXT,
        cancelled_at TEXT,
        cancelled_by TEXT,
        cancel_reason TEXT"""


def _valid_date(expr: str) -> str:
    """SQL: ``expr`` is a calendar date written YYYY-MM-DD (SQLite normalizes anything else)."""
    return f"({expr} IS NOT NULL AND date({expr}) IS {expr})"


def _valid_terms(expr: str) -> str:
    return f"(typeof({expr}) = 'integer' AND {expr} BETWEEN 0 AND {TERMS_MAX_DAYS})"


def _dated(alias: str) -> str:
    """SQL: record ``alias`` carries a valid invoice date and the due date its terms give."""
    return (f"({_valid_date(alias + '.invoice_date')} AND {_valid_terms(alias + '.payment_terms_days')} "
            f"AND {alias}.due_date IS date({alias}.invoice_date, '+' || {alias}.payment_terms_days || ' days'))")


def _standing_adjustments(key: str) -> str:
    """SQL: what the posted credit memos, write-offs and deposit applications whose journals
    still stand take off prime bill ``key`` (``Receivables._bill_balance``)."""
    return "(" + " + ".join(
        f"(SELECT TOTAL(CAST(x.amount AS REAL)) FROM {t} x WHERE x.prime_bill_id = {key} AND x.status = 'posted' "
        "AND NOT EXISTS (SELECT 1 FROM journals rv WHERE rv.reversal_of = x.journal_id))" for t in _ADJUSTMENT_TABLES) + ")"


def _bill_open(alias: str) -> str:
    """SQL: what stays open on prime bill ``alias`` after its receipts, a reversal and every
    standing credit memo, write-off and deposit application."""
    return f"({_open_on(alias, 'amount_due', 'collections', 'prime_bill_id')} - {_standing_adjustments(alias + '.id')})"


def _deposit_unapplied(alias: str) -> str:
    """SQL: deposit ``alias`` while its journal stands, less its standing applications."""
    return (f"((CASE WHEN NOT EXISTS (SELECT 1 FROM journals rv WHERE rv.reversal_of = {alias}.journal_id) THEN CAST({alias}.amount AS REAL) ELSE 0 END) - "
            f"(SELECT TOTAL(CAST(a.amount AS REAL)) FROM deposit_applications a WHERE a.deposit_id = {alias}.id AND a.status = 'posted' "
            "AND NOT EXISTS (SELECT 1 FROM journals rv WHERE rv.reversal_of = a.journal_id)))")


def _first_line(account: str, side: str) -> str:
    return f"(SELECT l.{side} FROM journal_lines l WHERE l.journal_id = NEW.journal_id AND l.account_code = '{account}' ORDER BY l.line_no LIMIT 1)"


def _own_journal(source_type: str, *lines: tuple[str, str], approval: bool = True) -> str:
    """SQL: NEW records its own standing ``source_type`` journal (source id NEW.id, in
    NEW.period_id, under NEW.approval_id) whose first line on each (account, side) carries
    NEW.amount."""
    approval_sql = "AND j.approval_id IS NEW.approval_id " if approval else ""
    amounts = " ".join(f"AND NEW.amount IS {_first_line(account, side)}" for account, side in lines)
    return (f"(EXISTS (SELECT 1 FROM journals j WHERE j.id = NEW.journal_id AND j.source_type = '{source_type}' AND j.source_id = NEW.id "
            f"{approval_sql}AND j.period_id IS NEW.period_id AND j.reversal_of IS NULL) {amounts})")


def _draft_insert(table: str, label: str, extra: list[tuple[str, str]]) -> str:
    """BEFORE INSERT trigger for an approval-bound adjustment of a prime bill: recorded as a
    draft, for a positive amount within what is open, on a standing posted prime bill of its
    project and customer whose hash it records, plus the table's own checks."""
    whens = "\n".join(f"                WHEN {cond}\n                THEN RAISE(ABORT, '{msg}')" for cond, msg in extra)
    return f"""CREATE TRIGGER {table}_insert BEFORE INSERT ON {table}
        BEGIN
            SELECT CASE
                WHEN NEW.status IS NOT 'draft' OR NEW.approval_id IS NOT NULL OR NEW.journal_id IS NOT NULL OR NEW.period_id IS NOT NULL
                     OR NEW.posted_at IS NOT NULL OR NEW.posted_by IS NOT NULL OR NEW.cancelled_at IS NOT NULL OR NEW.cancelled_by IS NOT NULL
                THEN RAISE(ABORT, 'a {label} is recorded as a draft; it posts only through its approval')
                WHEN NOT (CAST(NEW.amount AS REAL) > 0)
                THEN RAISE(ABORT, 'a {label} is for a positive amount')
                WHEN NOT EXISTS (SELECT 1 FROM prime_bills b WHERE b.id = NEW.prime_bill_id AND {_live('b')} AND b.project_id = NEW.project_id
                                 AND b.customer_id = NEW.customer_id AND b.content_hash = NEW.bill_hash)
                THEN RAISE(ABORT, 'a {label} is drawn on a standing posted prime bill of its project and customer, recording its hash')
                WHEN CAST(NEW.amount AS REAL) > (SELECT {_bill_open('b')} FROM prime_bills b WHERE b.id = NEW.prime_bill_id) + 0.005
                THEN RAISE(ABORT, 'a {label} cannot exceed what is open on its prime bill')
{whens}
            END;
        END"""


def _draft_guard(table: str, label: str, operation: str, fixed: tuple[str, ...], journal_ok: str, extra: list[tuple[str, str]]) -> str:
    """BEFORE UPDATE trigger: a draft moves once, to canceled (posting nothing) or to posted
    (under its consumed approval, with its own journal, within what is open)."""
    whens = "\n".join(f"                WHEN NEW.status = 'posted' AND ({cond})\n                THEN RAISE(ABORT, '{msg}')" for cond, msg in extra)
    return f"""CREATE TRIGGER {table}_guard BEFORE UPDATE ON {table}
        BEGIN
            SELECT CASE
                WHEN {_changed(fixed)} OR OLD.status IS NOT 'draft' OR NEW.status NOT IN ('posted','cancelled')
                THEN RAISE(ABORT, 'a {label} only moves once, from draft to posted or cancelled')
                WHEN NEW.status = 'cancelled' AND (NEW.cancelled_at IS NULL OR NEW.cancelled_by IS NULL OR NEW.approval_id IS NOT NULL
                                                   OR NEW.journal_id IS NOT NULL OR NEW.period_id IS NOT NULL OR NEW.posted_at IS NOT NULL)
                THEN RAISE(ABORT, 'a cancelled {label} records who cancelled it and posts nothing')
                WHEN NEW.status = 'posted' AND NOT EXISTS (SELECT 1 FROM approvals a WHERE a.id = NEW.approval_id AND a.operation = '{operation}'
                                                           AND a.subject_id = NEW.id AND a.status = 'consumed')
                THEN RAISE(ABORT, 'a {label} posts only under its consumed {operation} approval')
                WHEN NEW.status = 'posted' AND (NEW.posted_at IS NULL OR NEW.posted_by IS NULL OR NEW.cancelled_at IS NOT NULL OR NOT {journal_ok})
                THEN RAISE(ABORT, 'a {label} posts with its own journal for its amount, in its period, under its approval')
                WHEN NEW.status = 'posted' AND NOT EXISTS (SELECT 1 FROM prime_bills b WHERE b.id = NEW.prime_bill_id AND {_live('b')})
                THEN RAISE(ABORT, 'a {label} posts only against a standing posted prime bill')
                WHEN NEW.status = 'posted' AND CAST(NEW.amount AS REAL) > (SELECT {_bill_open('b')} FROM prime_bills b WHERE b.id = NEW.prime_bill_id) + 0.005
                THEN RAISE(ABORT, 'a {label} cannot exceed what is open on its prime bill')
{whens}
            END;
        END"""


_ADJUSTMENT_FIXED = ("id", "prime_bill_id", "project_id", "customer_id", "amount", "bill_hash", "created_at", "created_by")
_CREDIT_MEMO_FIXED = _ADJUSTMENT_FIXED + ("reason", "evidence_hash", "evidence_revision_id")
_WRITE_OFF_FIXED = _ADJUSTMENT_FIXED + ("reason", "requested_on", "due_date", "days_past_due")
_APPLICATION_FIXED = _ADJUSTMENT_FIXED + ("deposit_id",)
_REF_IN_DEPOSITS = "EXISTS (SELECT 1 FROM customer_deposits x WHERE x.provider_ref = NEW.provider_ref COLLATE NOCASE)"
_RECEIPT_REF_ONCE = "a receipt reference is recorded once, ignoring case"

DATES_CREDITS_SCHEMA_NAME = "receivables_dates_credits"
DATES_CREDITS_SCHEMA_STATEMENTS = [
    # =============================== chart, tables and columns =============================== #
    "INSERT OR IGNORE INTO accounts (code, name, type, control_kind) VALUES ('2400', 'Customer deposits', 'liability', 'customer_deposits')",
    "INSERT OR IGNORE INTO accounts (code, name, type, control_kind) VALUES ('6100', 'Bad debt expense', 'expense', NULL)",
    # ---- customer payment terms: versioned, latest wins, never edited ----
    """CREATE TABLE customer_payment_terms (
        id TEXT PRIMARY KEY,
        customer_id TEXT NOT NULL REFERENCES parties(id),
        version INTEGER NOT NULL CHECK (version >= 1),
        days INTEGER NOT NULL,
        created_at TEXT NOT NULL,
        created_by TEXT NOT NULL,
        UNIQUE (customer_id, version)
    )""",
    # ---- document dates: set once, when the bill posts or the retainage invoice is released ----
    "ALTER TABLE prime_bills ADD COLUMN invoice_date TEXT",
    "ALTER TABLE prime_bills ADD COLUMN due_date TEXT",
    "ALTER TABLE prime_bills ADD COLUMN payment_terms_days INTEGER",
    "ALTER TABLE prime_retainage_invoices ADD COLUMN invoice_date TEXT",
    "ALTER TABLE prime_retainage_invoices ADD COLUMN due_date TEXT",
    "ALTER TABLE prime_retainage_invoices ADD COLUMN payment_terms_days INTEGER",
    # ---- receipts: the settlement date, distinct from the time the receipt was recorded ----
    "ALTER TABLE collections ADD COLUMN settlement_date TEXT",
    "ALTER TABLE prime_retainage_collections ADD COLUMN settlement_date TEXT",
    # ---- credit memos on prime bills ----
    f"""CREATE TABLE prime_bill_credit_memos (
        id TEXT PRIMARY KEY,
        prime_bill_id TEXT NOT NULL REFERENCES prime_bills(id),
        project_id TEXT NOT NULL REFERENCES projects(id),
        customer_id TEXT NOT NULL REFERENCES parties(id),
        amount TEXT NOT NULL,
        reason TEXT NOT NULL,
        evidence_hash TEXT NOT NULL,
        evidence_revision_id TEXT NOT NULL REFERENCES document_revisions(id),
        bill_hash TEXT NOT NULL,
        posted_on TEXT,
        {_DRAFT_COLUMNS}
    )""",
    # ---- write-offs of prime bills at least 90 days past due ----
    f"""CREATE TABLE receivable_write_offs (
        id TEXT PRIMARY KEY,
        prime_bill_id TEXT NOT NULL REFERENCES prime_bills(id),
        project_id TEXT NOT NULL REFERENCES projects(id),
        customer_id TEXT NOT NULL REFERENCES parties(id),
        amount TEXT NOT NULL,
        reason TEXT NOT NULL,
        requested_on TEXT NOT NULL,
        due_date TEXT NOT NULL,
        days_past_due INTEGER NOT NULL,
        bill_hash TEXT NOT NULL,
        {_DRAFT_COLUMNS}
    )""",
    # ---- customer deposits (advances) and their applications to prime bills ----
    """CREATE TABLE customer_deposits (
        id TEXT PRIMARY KEY,
        customer_id TEXT NOT NULL REFERENCES parties(id),
        project_id TEXT NOT NULL REFERENCES projects(id),
        amount TEXT NOT NULL,
        method TEXT NOT NULL CHECK (method IN ('ach','check','wire')),
        mandate_id TEXT REFERENCES customer_mandates(id),
        provider_ref TEXT NOT NULL,
        settlement_date TEXT NOT NULL,
        period_id TEXT NOT NULL REFERENCES periods(id),
        journal_id TEXT NOT NULL UNIQUE REFERENCES journals(id),
        received_at TEXT NOT NULL,
        recorded_by TEXT NOT NULL
    )""",
    f"""CREATE TABLE deposit_applications (
        id TEXT PRIMARY KEY,
        deposit_id TEXT NOT NULL REFERENCES customer_deposits(id),
        prime_bill_id TEXT NOT NULL REFERENCES prime_bills(id),
        project_id TEXT NOT NULL REFERENCES projects(id),
        customer_id TEXT NOT NULL REFERENCES parties(id),
        amount TEXT NOT NULL,
        bill_hash TEXT NOT NULL,
        {_DRAFT_COLUMNS}
    )""",
    # ==================================== indexes ===================================== #
    "CREATE UNIQUE INDEX prime_bill_credit_memos_one_draft ON prime_bill_credit_memos (prime_bill_id) WHERE status = 'draft'",
    "CREATE INDEX prime_bill_credit_memos_bill ON prime_bill_credit_memos (prime_bill_id, status)",
    "CREATE UNIQUE INDEX receivable_write_offs_one_draft ON receivable_write_offs (prime_bill_id) WHERE status = 'draft'",
    "CREATE INDEX receivable_write_offs_bill ON receivable_write_offs (prime_bill_id, status)",
    "CREATE UNIQUE INDEX customer_deposits_ref ON customer_deposits (provider_ref COLLATE NOCASE)",
    "CREATE INDEX customer_deposits_customer ON customer_deposits (customer_id, project_id)",
    "CREATE UNIQUE INDEX deposit_applications_one_draft ON deposit_applications (deposit_id, prime_bill_id) WHERE status = 'draft'",
    "CREATE INDEX deposit_applications_bill ON deposit_applications (prime_bill_id, status)",
    "CREATE INDEX deposit_applications_deposit ON deposit_applications (deposit_id, status)",
    # ==================================== triggers ==================================== #
    # ---- payment terms ----
    f"""CREATE TRIGGER customer_payment_terms_insert BEFORE INSERT ON customer_payment_terms
        BEGIN
            SELECT CASE
                WHEN NEW.version IS NOT COALESCE((SELECT MAX(version) FROM customer_payment_terms WHERE customer_id = NEW.customer_id), 0) + 1
                THEN RAISE(ABORT, 'payment terms versions are contiguous')
                WHEN NOT {_valid_terms('NEW.days')}
                THEN RAISE(ABORT, 'payment terms are a whole number of days from 0 to {TERMS_MAX_DAYS}')
                WHEN NOT EXISTS (SELECT 1 FROM parties p WHERE p.id = NEW.customer_id AND p.kind = 'customer')
                THEN RAISE(ABORT, 'payment terms belong to a customer')
            END;
        END""",
    "CREATE TRIGGER customer_payment_terms_no_update BEFORE UPDATE ON customer_payment_terms BEGIN SELECT RAISE(ABORT, 'payment terms versions are immutable; set a new version'); END",
    "CREATE TRIGGER customer_payment_terms_no_delete BEFORE DELETE ON customer_payment_terms BEGIN SELECT RAISE(ABORT, 'payment terms versions are immutable; set a new version'); END",
    # ---- prime bill dates: a draft may carry a requested invoice date; both dates are fixed when it posts ----
    f"""CREATE TRIGGER prime_bills_dates_insert BEFORE INSERT ON prime_bills
        WHEN NEW.due_date IS NOT NULL OR NEW.payment_terms_days IS NOT NULL
          OR (NEW.invoice_date IS NOT NULL AND NOT {_valid_date('NEW.invoice_date')})
        BEGIN SELECT RAISE(ABORT, 'a draft prime bill carries at most a valid requested invoice date; its due date is fixed when it posts'); END""",
    """CREATE TRIGGER prime_bills_dates_guard BEFORE UPDATE ON prime_bills
        WHEN (NEW.invoice_date IS NOT OLD.invoice_date OR NEW.due_date IS NOT OLD.due_date OR NEW.payment_terms_days IS NOT OLD.payment_terms_days)
          AND NOT (OLD.status = 'draft' AND NEW.status = 'posted' AND OLD.due_date IS NULL AND OLD.payment_terms_days IS NULL
                   AND (OLD.invoice_date IS NULL OR NEW.invoice_date IS OLD.invoice_date))
        BEGIN SELECT RAISE(ABORT, 'a prime bill''s invoice and due dates are fixed once, when it posts'); END""",
    f"""CREATE TRIGGER prime_bills_post_dated BEFORE UPDATE OF status ON prime_bills
        WHEN OLD.status = 'draft' AND NEW.status = 'posted' AND NOT {_dated('NEW')}
        BEGIN SELECT RAISE(ABORT, 'a prime bill posts with its invoice date and the due date its payment terms give'); END""",
    # ---- retainage invoice dates: fixed at release ----
    f"""CREATE TRIGGER prime_retainage_invoices_dated BEFORE INSERT ON prime_retainage_invoices
        WHEN NOT {_dated('NEW')}
        BEGIN SELECT RAISE(ABORT, 'a retainage invoice records its invoice date and the due date its payment terms give'); END""",
    """CREATE TRIGGER prime_retainage_invoices_dates_fixed BEFORE UPDATE ON prime_retainage_invoices
        WHEN NEW.invoice_date IS NOT OLD.invoice_date OR NEW.due_date IS NOT OLD.due_date OR NEW.payment_terms_days IS NOT OLD.payment_terms_days
        BEGIN SELECT RAISE(ABORT, 'a retainage invoice''s dates are fixed when it is released'); END""",
    # ---- receipts: settlement date; never more than is open after credits; references unique with deposits ----
    f"""CREATE TRIGGER collections_dated BEFORE INSERT ON collections
        BEGIN
            SELECT CASE
                WHEN NOT {_valid_date('NEW.settlement_date')}
                THEN RAISE(ABORT, 'a receipt records its settlement date (YYYY-MM-DD)')
                WHEN NEW.settlement_date < (SELECT b.invoice_date FROM prime_bills b WHERE b.id = NEW.prime_bill_id)
                THEN RAISE(ABORT, 'a receipt never settles before the invoice date of the bill it collects')
                WHEN {_REF_IN_DEPOSITS}
                THEN RAISE(ABORT, '{_RECEIPT_REF_ONCE}')
                WHEN CAST(NEW.amount AS REAL) > (SELECT {_bill_open('b')} FROM prime_bills b WHERE b.id = NEW.prime_bill_id) + 0.005
                THEN RAISE(ABORT, 'a receipt cannot exceed what is open on its prime bill after credit memos, write-offs and deposit applications')
            END;
        END""",
    f"""CREATE TRIGGER prime_retainage_collections_dated BEFORE INSERT ON prime_retainage_collections
        BEGIN
            SELECT CASE
                WHEN NOT {_valid_date('NEW.settlement_date')}
                THEN RAISE(ABORT, 'a receipt records its settlement date (YYYY-MM-DD)')
                WHEN NEW.settlement_date < (SELECT i.invoice_date FROM prime_retainage_invoices i WHERE i.id = NEW.retainage_invoice_id)
                THEN RAISE(ABORT, 'a receipt never settles before the invoice date of the retainage invoice it collects')
                WHEN {_REF_IN_DEPOSITS}
                THEN RAISE(ABORT, '{_RECEIPT_REF_ONCE}')
            END;
        END""",
    "CREATE TRIGGER collections_settlement_fixed BEFORE UPDATE ON collections WHEN NEW.settlement_date IS NOT OLD.settlement_date "
    "BEGIN SELECT RAISE(ABORT, 'a receipt''s settlement date is fixed when it is recorded'); END",
    "CREATE TRIGGER prime_retainage_collections_settlement_fixed BEFORE UPDATE ON prime_retainage_collections WHEN NEW.settlement_date IS NOT OLD.settlement_date "
    "BEGIN SELECT RAISE(ABORT, 'a receipt''s settlement date is fixed when it is recorded'); END",
    # ---- credit memos ----
    _draft_insert("prime_bill_credit_memos", "credit memo", [
        ("length(trim(NEW.reason)) = 0", "a credit memo records its reason"),
        ("NOT EXISTS (SELECT 1 FROM document_revisions r JOIN documents d ON d.id = r.document_id WHERE r.id = NEW.evidence_revision_id "
         "AND r.content_hash = NEW.evidence_hash AND d.project_id = NEW.project_id)",
         "a credit memo records the content hash of its evidence revision, filed on the project of its bill"),
    ]),
    _draft_guard("prime_bill_credit_memos", "credit memo", "prime_bill.credit_memo", _CREDIT_MEMO_FIXED,
                 _own_journal("prime_bill_credit_memo", ("1100", "credit"), ("4000", "debit")),
                 [("NOT " + _valid_date("NEW.posted_on"), "a posted credit memo records the date it posted")]),
    "CREATE TRIGGER prime_bill_credit_memos_no_delete BEFORE DELETE ON prime_bill_credit_memos BEGIN SELECT RAISE(ABORT, 'credit memos are never deleted'); END",
    # ---- write-offs ----
    _draft_insert("receivable_write_offs", "write-off", [
        ("length(trim(NEW.reason)) = 0", "a write-off records its reason"),
        (f"NOT {_valid_date('NEW.requested_on')} OR NEW.due_date IS NOT (SELECT b.due_date FROM prime_bills b WHERE b.id = NEW.prime_bill_id) "
         "OR NOT " + _valid_date("NEW.due_date") + " OR NEW.days_past_due IS NOT CAST(julianday(NEW.requested_on) - julianday(NEW.due_date) AS INTEGER)",
         "a write-off records the due date of its bill and the days past due on the date it was requested"),
        (f"NEW.days_past_due < {WRITE_OFF_MIN_DAYS_PAST_DUE}", f"only a receivable at least {WRITE_OFF_MIN_DAYS_PAST_DUE} days past due can be written off"),
    ]),
    _draft_guard("receivable_write_offs", "write-off", "receivable.write_off", _WRITE_OFF_FIXED,
                 _own_journal("receivable_write_off", ("1100", "credit"), ("6100", "debit")), []),
    "CREATE TRIGGER receivable_write_offs_no_delete BEFORE DELETE ON receivable_write_offs BEGIN SELECT RAISE(ABORT, 'write-offs are never deleted'); END",
    # ---- customer deposits: immutable, with their own journal; ACH needs a backed mandate ----
    f"""CREATE TRIGGER customer_deposits_insert BEFORE INSERT ON customer_deposits
        BEGIN
            SELECT CASE
                WHEN NOT (CAST(NEW.amount AS REAL) > 0)
                THEN RAISE(ABORT, 'a deposit is for a positive amount')
                WHEN NOT EXISTS (SELECT 1 FROM projects p JOIN parties c ON c.id = p.customer_id WHERE p.id = NEW.project_id
                                 AND p.customer_id = NEW.customer_id AND c.kind = 'customer')
                THEN RAISE(ABORT, 'a deposit is taken from the customer of its project')
                WHEN NOT {_valid_date('NEW.settlement_date')}
                THEN RAISE(ABORT, 'a deposit records its settlement date (YYYY-MM-DD)')
                WHEN NEW.method = 'ach' AND NOT EXISTS (SELECT 1 FROM customer_mandates m WHERE m.id = NEW.mandate_id AND m.customer_id = NEW.customer_id
                                                        AND m.status = 'active' AND {_mandate_backed('m')})
                THEN RAISE(ABORT, '{_MISSING_BACKED_MANDATE}')
                WHEN NEW.method IS NOT 'ach' AND NEW.mandate_id IS NOT NULL
                THEN RAISE(ABORT, 'a mandate applies to ACH deposits only')
                WHEN {_REF_CLASH} OR {_REF_IN_DEPOSITS}
                THEN RAISE(ABORT, '{_RECEIPT_REF_ONCE}')
                WHEN NOT {_own_journal("customer_deposit", ("2400", "credit"), ("1000", "debit"), approval=False)}
                THEN RAISE(ABORT, 'a deposit records its own journal crediting 2400 by its amount, in its period')
            END;
        END""",
    "CREATE TRIGGER customer_deposits_no_update BEFORE UPDATE ON customer_deposits BEGIN SELECT RAISE(ABORT, 'deposits are immutable; apply them, or reverse an unapplied one'); END",
    "CREATE TRIGGER customer_deposits_no_delete BEFORE DELETE ON customer_deposits BEGIN SELECT RAISE(ABORT, 'deposits are never deleted'); END",
    # ---- deposit applications ----
    _draft_insert("deposit_applications", "deposit application", [
        ("NOT EXISTS (SELECT 1 FROM customer_deposits d WHERE d.id = NEW.deposit_id AND d.customer_id = NEW.customer_id AND d.project_id = NEW.project_id)",
         "a deposit is applied only to a prime bill of its own customer and project"),
        (f"CAST(NEW.amount AS REAL) > (SELECT {_deposit_unapplied('d')} FROM customer_deposits d WHERE d.id = NEW.deposit_id) + 0.005",
         "a deposit application cannot exceed the unapplied balance of its deposit"),
    ]),
    _draft_guard("deposit_applications", "deposit application", "receivable.apply_deposit", _APPLICATION_FIXED,
                 _own_journal("deposit_application", ("1100", "credit"), ("2400", "debit")), [
                     (f"CAST(NEW.amount AS REAL) > (SELECT {_deposit_unapplied('d')} FROM customer_deposits d WHERE d.id = NEW.deposit_id) + 0.005",
                      "a deposit application cannot exceed the unapplied balance of its deposit"),
                 ]),
    "CREATE TRIGGER deposit_applications_no_delete BEFORE DELETE ON deposit_applications BEGIN SELECT RAISE(ABORT, 'deposit applications are never deleted'); END",
    # ---- a deposit is reversed only once nothing applied from it still stands ----
    """CREATE TRIGGER customer_deposits_reversal_guard BEFORE INSERT ON journals
        WHEN NEW.reversal_of IS NOT NULL AND EXISTS (
            SELECT 1 FROM customer_deposits d JOIN deposit_applications a ON a.deposit_id = d.id
            WHERE d.journal_id = NEW.reversal_of AND a.status = 'posted'
              AND NOT EXISTS (SELECT 1 FROM journals rv WHERE rv.reversal_of = a.journal_id))
        BEGIN SELECT RAISE(ABORT, 'a customer deposit with standing applications cannot be reversed; reverse its applications first'); END""",
]
register_schema_version(DATES_CREDITS_SCHEMA_NAME, DATES_CREDITS_SCHEMA_STATEMENTS)

# --------------------------------------------------------------------------- #
# Schema (catalog entry ``receivables_dates_credits_guards``)                  #
# --------------------------------------------------------------------------- #
# Guards added after the review of ``receivables_dates_credits`` (append-only: never edit
# either entry once applied).  Every statement is a trigger that checks new writes only,
# so it applies to any workspace written earlier; records an earlier workspace already
# holds are re-checked in Python (a write-off draft when it is approved and posted) or
# reported (a reversed prime bill that still carries standing adjustments, under
# ``ar_open_items(...)["errors"]``).
#
# * A write-off is requested no later than the real calendar day (SQLite ``date('now')``,
#   UTC) and no later than the day its row is recorded, so its days past due can never be
#   counted to a future date; the same is checked again when a draft posts.
# * An explicit invoice date is never before the start of the bill's period.
# * A prime bill whose credit memos, write-offs or deposit applications still stand cannot
#   be reversed (neither its reversal request nor the reversing journal is accepted), and
#   neither can a deposit's reversal be requested while its applications stand: reverse the
#   adjustments first, so the receivable and the deposit balance never go negative.


def _has_standing_adjustment(bill: str) -> str:
    """SQL: prime bill ``bill`` has a posted credit memo, write-off or deposit application
    whose journal still stands."""
    return "(" + " OR ".join(
        f"EXISTS (SELECT 1 FROM {t} x WHERE x.prime_bill_id = {bill}.id AND x.status = 'posted' "
        "AND NOT EXISTS (SELECT 1 FROM journals rv WHERE rv.reversal_of = x.journal_id))" for t in _ADJUSTMENT_TABLES) + ")"


def _deposit_has_standing_application(journal_expr: str) -> str:
    """SQL: the deposit whose journal is ``journal_expr`` has a posted application whose
    journal still stands."""
    return ("EXISTS (SELECT 1 FROM customer_deposits d JOIN deposit_applications a ON a.deposit_id = d.id "
            f"WHERE d.journal_id = {journal_expr} AND a.status = 'posted' "
            "AND NOT EXISTS (SELECT 1 FROM journals rv WHERE rv.reversal_of = a.journal_id))")


_BILL_REVERSAL_BLOCKED = ("a prime bill with standing credit memos, write-offs or deposit applications cannot be reversed; "
                          "reverse them first")
_DEPOSIT_REVERSAL_BLOCKED = "a customer deposit with standing applications cannot be reversed; reverse its applications first"
_WRITE_OFF_FACTS_HOLD = (
    "NEW.requested_on <= date('now') AND NEW.due_date IS (SELECT b.due_date FROM prime_bills b WHERE b.id = NEW.prime_bill_id) "
    "AND NEW.days_past_due IS CAST(julianday(NEW.requested_on) - julianday(NEW.due_date) AS INTEGER) "
    f"AND NEW.days_past_due >= {WRITE_OFF_MIN_DAYS_PAST_DUE}"
)

DATES_CREDITS_GUARDS_SCHEMA_NAME = "receivables_dates_credits_guards"
DATES_CREDITS_GUARDS_SCHEMA_STATEMENTS = [
    # ---- write-offs: requested no later than today, and no later than the day recorded ----
    f"""CREATE TRIGGER receivable_write_offs_request_date BEFORE INSERT ON receivable_write_offs
        WHEN {_valid_date('NEW.requested_on')}
          AND (NEW.requested_on > date('now') OR date(NEW.created_at) IS NULL OR NEW.requested_on > date(NEW.created_at))
        BEGIN SELECT RAISE(ABORT, 'a write-off is requested no later than today and no later than the day it is recorded; its days past due count to that date'); END""",
    f"""CREATE TRIGGER receivable_write_offs_post_request_date BEFORE UPDATE OF status ON receivable_write_offs
        WHEN OLD.status = 'draft' AND NEW.status = 'posted' AND NOT ({_valid_date('NEW.requested_on')} AND {_WRITE_OFF_FACTS_HOLD})
        BEGIN SELECT RAISE(ABORT, 'a write-off posts only when it was requested no later than today, at least {WRITE_OFF_MIN_DAYS_PAST_DUE} days past the due date of its bill'); END""",
    # ---- an explicit invoice date is never before the start of the bill's period ----
    f"""CREATE TRIGGER prime_bills_invoice_date_in_period BEFORE INSERT ON prime_bills
        WHEN {_valid_date('NEW.invoice_date')} AND NEW.invoice_date < (SELECT p.start_date FROM periods p WHERE p.id = NEW.period_id)
        BEGIN SELECT RAISE(ABORT, 'an explicit invoice date is never before the start of the period the prime bill is billed in'); END""",
    # ---- reversals: a prime bill (or deposit) only once its standing adjustments are reversed ----
    f"""CREATE TRIGGER prime_bills_reversal_guard BEFORE INSERT ON journals
        WHEN NEW.reversal_of IS NOT NULL
          AND EXISTS (SELECT 1 FROM prime_bills b WHERE b.journal_id = NEW.reversal_of AND {_has_standing_adjustment('b')})
        BEGIN SELECT RAISE(ABORT, '{_BILL_REVERSAL_BLOCKED}'); END""",
    f"""CREATE TRIGGER prime_bills_reversal_request_guard BEFORE INSERT ON journal_reversal_requests
        WHEN EXISTS (SELECT 1 FROM prime_bills b WHERE b.journal_id = NEW.journal_id AND {_has_standing_adjustment('b')})
        BEGIN SELECT RAISE(ABORT, '{_BILL_REVERSAL_BLOCKED}'); END""",
    f"""CREATE TRIGGER customer_deposits_reversal_request_guard BEFORE INSERT ON journal_reversal_requests
        WHEN {_deposit_has_standing_application('NEW.journal_id')}
        BEGIN SELECT RAISE(ABORT, '{_DEPOSIT_REVERSAL_BLOCKED}'); END""",
]
register_schema_version(DATES_CREDITS_GUARDS_SCHEMA_NAME, DATES_CREDITS_GUARDS_SCHEMA_STATEMENTS)

# --------------------------------------------------------------------------- #
# Constants and errors                                                         #
# --------------------------------------------------------------------------- #

OP_SEND = "prime_bill.send"
OP_RELEASE_RETAINAGE = "prime_retainage.release"
OP_CREDIT_MEMO = "prime_bill.credit_memo"
OP_WRITE_OFF = "receivable.write_off"
OP_APPLY_DEPOSIT = "receivable.apply_deposit"
OWNED_OPERATIONS = (OP_SEND, OP_RELEASE_RETAINAGE, OP_CREDIT_MEMO, OP_WRITE_OFF, OP_APPLY_DEPOSIT)

DEFAULT_PAYMENT_TERMS_DAYS = 30
MAX_REASON_LENGTH = 500
CREDIT_MEMO_POLICY = "fixture: a credit memo reduces certified progress revenue, Dr 4000 / Cr 1100 (SHADOW)"
WRITE_OFF_POLICY = (f"fixture: a receivable at least {WRITE_OFF_MIN_DAYS_PAST_DUE} days past due may be written off to bad debt expense, "
                    "Dr 6100 / Cr 1100 (SHADOW)")
DEPOSIT_POLICY = "fixture: customer advances are held in 2400 until applied to a prime bill, Dr 2400 / Cr 1100 (SHADOW)"
SUBJECT_CREDIT_MEMO = "prime_bill_credit_memo"
SUBJECT_WRITE_OFF = "receivable_write_off"
SUBJECT_DEPOSIT_APPLICATION = "deposit_application"
JOURNAL_CREDIT_MEMO = "prime_bill_credit_memo"
JOURNAL_WRITE_OFF = "receivable_write_off"
JOURNAL_DEPOSIT = "customer_deposit"
JOURNAL_DEPOSIT_APPLICATION = "deposit_application"
SOURCE_CUSTOMER_DEPOSIT = "customer_deposit"
AR_ACCOUNT = "1100"
REVENUE_ACCOUNT = "4000"
BANK_ACCOUNT = "1000"
DEPOSITS_ACCOUNT = "2400"
BAD_DEBT_ACCOUNT = "6100"
DEPOSITS_CONTROL = "customer_deposits"

SEND_CHANNEL = "mail-sink"
COLLECTION_METHODS = ("ach", "check", "wire")
RECOGNITION_POLICY = "fixture: certified progress billed = earned (SHADOW)"
DEFAULT_RETAINAGE_RATE = "0.10"
POSTED_BILL_STATES = ("posted", "sent", "collected")
SOURCE_PRIME_BILL = "prime_bill"
SOURCE_RETAINAGE_INVOICE = "prime_retainage_invoice"
SOURCE_PRIME_RETAINAGE = "prime_retainage"
_BANK_MEMO = {"ach": "ACH receipt (simulated)", "check": "check deposit (simulated)", "wire": "wire receipt (simulated)"}
# Tables holding customer receipts; a new receipt's provider reference is unique across all
# of them, ignoring case.  The database enforces it across the core tables (_REF_CLASH, and
# _REF_IN_DEPOSITS for customer deposits); the plugin tables (labor T&M, reimbursement billings) may be absent from a
# workspace, so across them it is checked here in Python (labor checks the core tables the
# same way) and any clash a plugin let through is reported by receipt_reference_conflicts().
_CORE_RECEIPT_TABLES = ("collections", "prime_retainage_collections", "customer_deposits")
_RECEIPT_TABLES = _CORE_RECEIPT_TABLES + ("labor_collections", "reimbursement_collections")


class ReceivableError(RuntimeError):
    pass


class ReceivableInputError(ReceivableError, MoneyError):
    """Invalid input: an amount, rate, reference or actor that cannot be used."""


class ReceivableIneligible(ReceivableError, StaleApprovalError):
    """The subject is not, or no longer, in a state the operation applies to.

    At request time this simply refuses.  Because it is also a
    ``StaleApprovalError``, an approval granted while the subject was eligible
    is invalidated by the service when execution finds that it no longer is
    (for example a draft certified under a superseded contract version, or a
    prime bill whose journal was reversed after its send was approved)."""


class ReceivableCutoffError(ReceivableError):
    """A posting dated in a period that starts before the record it settles or
    releases.  The approval (if any) survives: execute again with a later period."""


class ReceivableDuplicate(ReceivableError):
    """The same draft (credit memo, write-off or deposit application) is already open,
    or a receipt reference is already recorded."""


# --------------------------------------------------------------------------- #
# Receivables                                                                  #
# --------------------------------------------------------------------------- #

class Receivables:
    def __init__(self, db: Database, audit: Audit, ledger: Ledger):
        self.db = db
        self.audit = audit
        self.ledger = ledger
        # The service replaces this with every plugin exposing ar_open_items(project_id).
        self.extra_ar_sources: Callable[[], list[Any]] = lambda: []
        # The calendar day (UTC) this workspace treats as today: the default invoice and
        # settlement date, the request date of a write-off and the default as_of of the AR
        # subledger.  Tests may replace it; it never moves a posting into another period.
        self.today: Callable[[], _dt.date] = lambda: utcnow().date()

    # ---- input helpers ------------------------------------------------------ #

    def _today(self) -> _dt.date:
        day = self.today()
        if isinstance(day, _dt.datetime) or not isinstance(day, _dt.date):
            raise ReceivableError("the receivables clock must return a calendar date")
        return day

    @staticmethod
    def _date(value: Any, label: str) -> str:
        """A calendar date written YYYY-MM-DD (or a ``datetime.date``), as its ISO text."""
        if isinstance(value, _dt.datetime):
            raise ReceivableInputError(f"{label} must be a calendar date (YYYY-MM-DD), not a timestamp")
        if isinstance(value, _dt.date):
            return value.isoformat()
        text = value.strip() if isinstance(value, str) else ""
        try:
            day = _dt.date.fromisoformat(text) if len(text) == 10 else None
        except ValueError:
            day = None
        if day is None or day.isoformat() != text:
            raise ReceivableInputError(f"{label} must be a calendar date written YYYY-MM-DD, got {value!r}")
        return text

    @staticmethod
    def _terms_days(value: Any) -> int:
        if isinstance(value, bool):
            raise ReceivableInputError("payment terms must be a whole number of days")
        if isinstance(value, str) and value.strip().isdigit():
            value = int(value.strip())
        if not isinstance(value, int):
            raise ReceivableInputError(f"payment terms must be a whole number of days, got {value!r}")
        if not 0 <= value <= TERMS_MAX_DAYS:
            raise ReceivableInputError(f"payment terms must be between 0 and {TERMS_MAX_DAYS} days, got {value}")
        return value

    def _reason(self, value: Any, label: str = "reason") -> str:
        text = self._text(value, label)
        if len(text) > MAX_REASON_LENGTH:
            raise ReceivableInputError(f"{label} is longer than {MAX_REASON_LENGTH} characters")
        return text

    def _positive(self, value: Any, label: str) -> Decimal:
        amt = self._money(value, label)
        if amt <= 0:
            raise ReceivableInputError(f"{label} must be positive, got {fmt(amt)}")
        return amt

    @staticmethod
    def _plus_days(day: str, days: int) -> str:
        return (_dt.date.fromisoformat(day) + _dt.timedelta(days=days)).isoformat()

    @staticmethod
    def _days_past_due(due_date: str | None, as_of: _dt.date, open_amount: Any = None) -> int | None:
        """Whole days ``as_of`` is past ``due_date`` (0 while not yet due, and 0 when nothing is
        open: a settled item is not past due); None when undated."""
        if not due_date:
            return None
        if open_amount is not None and money(open_amount) <= 0:
            return 0
        return max(0, (as_of - _dt.date.fromisoformat(due_date)).days)

    def _settlement_date(self, value: Any, *, not_before: str | None, what: str) -> str:
        """A receipt's settlement date: the given date or today, never in the future and
        never before the invoice date of what it settles (when that is dated)."""
        day = self._today().isoformat() if value is None else self._date(value, "settlement date")
        if day > self._today().isoformat():
            raise ReceivableInputError(f"settlement date {day} is in the future; a receipt is recorded once it has settled")
        if not_before and day < not_before:
            raise ReceivableError(f"settlement date {day} is before the invoice date {not_before} of {what}; an advance before invoicing is a customer deposit")
        return day

    @staticmethod
    def _money(value: Any, label: str) -> Decimal:
        try:
            m = money(value)
            finite = m.is_finite()
        except (MoneyError, ArithmeticError) as exc:
            raise ReceivableInputError(f"{label}: {exc}") from exc
        if not finite:
            raise ReceivableInputError(f"{label} must be a finite amount")
        return m

    @staticmethod
    def _rate(value: Any, label: str = "retainage rate") -> Decimal:
        try:
            r = rate(value)
        except (MoneyError, ArithmeticError) as exc:
            raise ReceivableInputError(f"{label}: {exc}") from exc
        return r

    @staticmethod
    def _text(value: Any, label: str) -> str:
        text = value.strip() if isinstance(value, str) else ""
        if not text:
            raise ReceivableInputError(f"{label} is required")
        return text

    def _require_actor(self, actor: Any) -> str:
        return self._text(actor, "actor")

    def _project(self, project_id: str) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM projects WHERE id=?", (project_id,))
        if row is None:
            raise ReceivableError(f"unknown project {project_id}")
        return row

    def _customer(self, customer_id: str) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM parties WHERE id=?", (customer_id,))
        if row is None:
            raise ReceivableError(f"unknown customer {customer_id}")
        if row["kind"] != "customer":
            raise ReceivableError(f"party {customer_id} is a {row['kind']}, not a customer")
        return row

    def _table_exists(self, name: str) -> bool:
        return self.db.one("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,)) is not None

    def _latest_open_period(self) -> str:
        row = self.db.one("SELECT id FROM periods WHERE status='open' ORDER BY start_date DESC LIMIT 1")
        if row is None:
            raise ReceivableError("no open period")
        return row["id"]

    def _require_not_before(self, target: dict[str, Any], source_period_id: str, what: str) -> None:
        """Cut-off: refuse a posting into ``target`` (an open period row) when it starts
        before the period of the record being settled or released."""
        source = self.ledger.period(source_period_id)
        if target["start_date"] < source["start_date"]:
            raise ReceivableCutoffError(
                f"cut-off: {what} belongs to period {source['id']} (starting {source['start_date']}); it cannot be settled or released "
                f"in period {target['id']}, which starts {target['start_date']}; use an open period starting on or after {source['start_date']}")

    # ---- reversal state ----------------------------------------------------- #

    def _reversal_of(self, journal_id: str | None) -> str | None:
        """The journal that reversed ``journal_id``, or None while it stands."""
        if not journal_id:
            return None
        row = self.db.one("SELECT id FROM journals WHERE reversal_of=? ORDER BY posted_at, id LIMIT 1", (journal_id,))
        return row["id"] if row else None

    def _receipt(self, col: dict[str, Any]) -> dict[str, Any]:
        """Annotate a receipt with what it currently credits to 1100: its amount while
        its collection journal stands, less its amount while a return journal stands."""
        amt = money(col["amount"])
        reversed_by = self._reversal_of(col["journal_id"])
        return_reversed_by = self._reversal_of(col.get("return_journal_id"))
        credited = ZERO
        if col["journal_id"] and reversed_by is None:
            credited += amt
        if col.get("return_journal_id") and return_reversed_by is None:
            credited -= amt
        col["journal_reversed_by"] = reversed_by
        col["return_journal_reversed_by"] = return_reversed_by
        col["credited"] = fmt(credited)
        return col

    def _live_bills(self, project_id: str) -> list[dict[str, Any]]:
        """The project's posted prime bills whose journals still stand, in sequence."""
        return self.db.query(f"SELECT b.* FROM prime_bills b WHERE b.project_id=? AND {_live('b')} ORDER BY b.sequence", (project_id,))

    def _billed_chain(self, project_id: str) -> dict[str, Any]:
        """What the standing prime bills put on the books: certified progress (4000),
        net billed (1100) and retainage withheld (1150).  Certification continues from
        here, so a reversed bill's work is billed again exactly once."""
        bills = self._live_bills(project_id)
        certified = total(b["revenue_this_period"] for b in bills)
        net = total(b["amount_due"] for b in bills)
        return {"bills": bills, "certified": certified, "net": net, "retained": money(certified - net), "latest": bills[-1] if bills else None}

    def _live_invoices(self, project_id: str) -> list[dict[str, Any]]:
        return self.db.query(
            "SELECT i.* FROM prime_retainage_invoices i WHERE i.project_id=? "
            "AND NOT EXISTS (SELECT 1 FROM journals rv WHERE rv.reversal_of = i.journal_id) ORDER BY i.sequence", (project_id,))

    def _released_to_date(self, project_id: str) -> Decimal:
        """Retainage released and invoiced by releases whose journals still stand."""
        return total(r["amount"] for r in self._live_invoices(project_id))

    # ---- prime contracts ---------------------------------------------------- #

    def contract(self, project_id: str) -> dict[str, Any] | None:
        """The current (latest) prime contract version of a project, or None."""
        return self.db.one("SELECT * FROM prime_contracts WHERE project_id=? ORDER BY version DESC LIMIT 1", (project_id,))

    def contracts(self, project_id: str) -> list[dict[str, Any]]:
        return self.db.query("SELECT * FROM prime_contracts WHERE project_id=? ORDER BY version", (project_id,))

    def _certified_to_date(self, project_id: str) -> Decimal:
        """Progress certified on the standing prime bills, or a pending draft's
        certified cumulative when that is higher."""
        drafts = [money(r["certified_cumulative"]) for r in self.db.query(
            "SELECT certified_cumulative FROM prime_bills WHERE project_id=? AND status='draft'", (project_id,))]
        return max([self._billed_chain(project_id)["certified"], *drafts])

    def set_prime_contract(self, project_id: str, contract_value: str | Decimal, retainage_rate: str | Decimal | None = None, actor: str | None = None) -> dict[str, Any]:
        """Record a new version of the project's prime contract (value and retainage rate).

        ``retainage_rate`` defaults to the current version's rate (10% for a first
        version), so a value-only change order never resets the rate.  Versions are
        immutable and the latest wins.  A version that changes nothing is refused, and
        so is a value below what is already certified (it would leave the project
        overbilled).  Approvals that bound the previous version go stale."""
        actor = self._require_actor(actor)
        self._project(project_id)
        value = self._money(contract_value, "contract value")
        if value <= 0:
            raise ReceivableInputError(f"contract value must be positive, got {fmt(value)}")
        explicit_rate = None if retainage_rate is None else self._rate(retainage_rate)
        with self.db.transaction() as conn:
            current = self.contract(project_id)
            if explicit_rate is not None:
                r = explicit_rate
            else:
                r = Decimal(current["retainage_rate"]) if current else self._rate(DEFAULT_RETAINAGE_RATE)
            if current and money(current["contract_value"]) == value and Decimal(current["retainage_rate"]) == r:
                raise ReceivableError(f"prime contract version {current['version']} already has value {fmt(value)} and retainage rate {r:f}; nothing changed")
            certified = self._certified_to_date(project_id)
            if value < certified:
                raise ReceivableError(f"contract value {fmt(value)} is below the {fmt(certified)} already certified on project {project_id} (overbilling)")
            version = (current["version"] + 1) if current else 1
            content_hash = hash_json({"project_id": project_id, "version": version, "contract_value": fmt(value), "retainage_rate": f"{r:f}"})
            cid = new_id("pct")
            conn.execute(
                "INSERT INTO prime_contracts (id, project_id, version, contract_value, retainage_rate, content_hash, created_at, created_by) VALUES (?,?,?,?,?,?,?,?)",
                (cid, project_id, version, fmt(value), f"{r:f}", content_hash, utcnow_iso(), actor),
            )
            self.audit.record(actor, "prime_contract.set", "prime_contract", cid, {
                "project_id": project_id, "version": version, "contract_value": fmt(value), "retainage_rate": f"{r:f}",
                "rate_source": "explicit" if explicit_rate is not None else ("previous version" if current else "default"),
                "previous_version": current["version"] if current else None, "content_hash": content_hash,
            })
        return self.contract(project_id)

    # ---- billing recipients --------------------------------------------------- #

    def billing_recipients(self, customer_id: str) -> dict[str, Any]:
        """The customer's current billing recipients.  Without a recorded list the
        synthetic mail sink's per-customer address is used (version 0)."""
        row = self.db.one("SELECT * FROM customer_billing_recipients WHERE customer_id=? ORDER BY version DESC LIMIT 1", (customer_id,))
        if row is None:
            return {"customer_id": customer_id, "version": 0, "recipients": [f"{SEND_CHANNEL}:{customer_id}"]}
        return {"customer_id": customer_id, "version": row["version"], "recipients": loads(row["recipients_json"])}

    def set_billing_recipients(self, customer_id: str, recipients: list[str], actor: str | None = None) -> dict[str, Any]:
        actor = self._require_actor(actor)
        self._customer(customer_id)
        if isinstance(recipients, str) or not isinstance(recipients, (list, tuple)):
            raise ReceivableInputError("recipients must be a list of mail addresses")
        cleaned: list[str] = []
        seen: set[str] = set()
        for raw in recipients:
            addr = raw.strip() if isinstance(raw, str) else ""
            if not addr or any(ch.isspace() for ch in addr) or "@" not in addr or len(addr) > 254:
                raise ReceivableInputError(f"recipient {raw!r} is not a mail address")
            if addr.lower() in seen:
                raise ReceivableInputError(f"recipient {addr} is listed twice")
            seen.add(addr.lower())
            cleaned.append(addr)
        if not cleaned:
            raise ReceivableInputError("at least one recipient is required")
        with self.db.transaction() as conn:
            current = self.billing_recipients(customer_id)
            if current["version"] and [a.lower() for a in current["recipients"]] == [a.lower() for a in cleaned]:
                raise ReceivableError(f"billing recipients version {current['version']} already lists exactly these addresses")
            version = current["version"] + 1
            rid = new_id("brc")
            conn.execute(
                "INSERT INTO customer_billing_recipients (id, customer_id, version, recipients_json, created_at, created_by) VALUES (?,?,?,?,?,?)",
                (rid, customer_id, version, canonical_json(cleaned), utcnow_iso(), actor),
            )
            self.audit.record(actor, "billing_recipients.set", "party", customer_id, {"version": version, "recipients": cleaned, "previous_version": current["version"]})
        return self.billing_recipients(customer_id)

    # ---- payment terms ---------------------------------------------------------- #

    def payment_terms(self, customer_id: str) -> dict[str, Any]:
        """The customer's current payment terms (latest version).  Without a recorded
        version the default of 30 days applies (version 0)."""
        row = self.db.one("SELECT * FROM customer_payment_terms WHERE customer_id=? ORDER BY version DESC LIMIT 1", (customer_id,))
        if row is None:
            return {"customer_id": customer_id, "version": 0, "days": DEFAULT_PAYMENT_TERMS_DAYS, "source": "default"}
        return {"customer_id": customer_id, "version": row["version"], "days": row["days"], "source": "recorded",
                "id": row["id"], "created_at": row["created_at"], "created_by": row["created_by"]}

    def payment_terms_history(self, customer_id: str) -> list[dict[str, Any]]:
        return self.db.query("SELECT * FROM customer_payment_terms WHERE customer_id=? ORDER BY version", (customer_id,))

    def set_customer_terms(self, customer_id: str, days: int | str, actor: str | None = None) -> dict[str, Any]:
        """Record a new version of the customer's payment terms (whole days, 0 to 365).
        Bills already posted keep the due date they posted with; a prime bill or retainage
        release whose approval bound the previous terms goes stale.  A version that
        repeats the current recorded terms is refused."""
        actor = self._require_actor(actor)
        self._customer(customer_id)
        n = self._terms_days(days)
        with self.db.transaction() as conn:
            current = self.payment_terms(customer_id)
            if current["version"] and current["days"] == n:
                raise ReceivableDuplicate(f"payment terms version {current['version']} of customer {customer_id} are already {n} days; nothing changed")
            version = current["version"] + 1
            tid = new_id("ptm")
            conn.execute(
                "INSERT INTO customer_payment_terms (id, customer_id, version, days, created_at, created_by) VALUES (?,?,?,?,?,?)",
                (tid, customer_id, version, n, utcnow_iso(), actor),
            )
            self.audit.record(actor, "payment_terms.set", "party", customer_id, {
                "version": version, "days": n, "previous_version": current["version"], "previous_days": current["days"],
            })
        return self.payment_terms(customer_id)

    # ---- ACH mandates ----------------------------------------------------------- #

    def mandates(self, customer_id: str | None = None) -> list[dict[str, Any]]:
        if customer_id:
            return self.db.query("SELECT * FROM customer_mandates WHERE customer_id=? ORDER BY recorded_at, id", (customer_id,))
        return self.db.query("SELECT * FROM customer_mandates ORDER BY recorded_at, id")

    def mandate(self, mandate_ref: str) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM customer_mandates WHERE mandate_ref = ? COLLATE NOCASE", (self._text(mandate_ref, "mandate reference"),))
        if row is None:
            raise ReceivableError(f"unknown mandate {mandate_ref}")
        return row

    def active_mandate(self, customer_id: str, mandate_ref: str | None = None) -> dict[str, Any] | None:
        """The customer's active mandate backed by owned evidence (the named one, or the
        most recently recorded).  A mandate whose evidence revision does not carry its
        evidence hash, or is not filed on a project of this customer (only possible for a
        row written outside record_mandate before the evidence guard existed), never
        authorizes a debit."""
        backed = _mandate_backed("m")
        if mandate_ref is not None:
            return self.db.one(
                f"SELECT m.* FROM customer_mandates m WHERE m.mandate_ref = ? COLLATE NOCASE AND m.customer_id = ? AND m.status = 'active' AND {backed}",
                (self._text(mandate_ref, "mandate reference"), customer_id))
        return self.db.one(
            f"SELECT m.* FROM customer_mandates m WHERE m.customer_id = ? AND m.status = 'active' AND {backed} ORDER BY m.recorded_at DESC, m.id DESC LIMIT 1",
            (customer_id,))

    def unbacked_mandates(self) -> list[dict[str, Any]]:
        """Mandates whose evidence does not back them (see active_mandate); reported by
        audit_export, never usable for an ACH collection."""
        return self.db.query(f"SELECT m.* FROM customer_mandates m WHERE NOT {_mandate_backed('m')} ORDER BY m.recorded_at, m.id")

    def record_mandate(self, customer_id: str, mandate_ref: str, evidence_hash: str, actor: str | None = None) -> dict[str, Any]:
        """Record a customer's ACH debit authorization.  ``evidence_hash`` must be the
        content hash of an evidence revision filed on one of this customer's projects
        (the signed authorization), so the mandate is traceable to owned evidence."""
        actor = self._require_actor(actor)
        self._customer(customer_id)
        ref = self._text(mandate_ref, "mandate reference")
        h = self._text(evidence_hash, "evidence hash")
        with self.db.transaction() as conn:
            rev = self.db.one(
                """SELECT r.id FROM document_revisions r JOIN documents d ON d.id = r.document_id JOIN projects p ON p.id = d.project_id
                   WHERE r.content_hash = ? AND p.customer_id = ? ORDER BY r.created_at DESC, r.id DESC LIMIT 1""",
                (h, customer_id),
            )
            if rev is None:
                if self.db.one("SELECT id FROM document_revisions WHERE content_hash=?", (h,)) is None:
                    raise ReceivableError(f"evidence hash {h} is not the content hash of any recorded evidence revision")
                raise ReceivableError(f"the evidence revision with hash {h} is not filed on a project of customer {customer_id}")
            existing = self.db.one("SELECT customer_id, status FROM customer_mandates WHERE mandate_ref = ? COLLATE NOCASE", (ref,))
            if existing is not None:
                raise ReceivableError(f"mandate {ref} was already recorded ({existing['status']}); a mandate reference is never reused")
            mid = new_id("mdt")
            conn.execute(
                """INSERT INTO customer_mandates (id, customer_id, mandate_ref, evidence_hash, evidence_revision_id, status, recorded_at, recorded_by)
                   VALUES (?,?,?,?,?,'active',?,?)""",
                (mid, customer_id, ref, h, rev["id"], utcnow_iso(), actor),
            )
            self.audit.record(actor, "mandate.recorded", "customer_mandate", mid, {"customer_id": customer_id, "mandate_ref": ref, "evidence_hash": h, "evidence_revision_id": rev["id"]})
        return self.db.one("SELECT * FROM customer_mandates WHERE id=?", (mid,))

    def revoke_mandate(self, customer_id: str, mandate_ref: str, actor: str | None = None, reason: str = "") -> dict[str, Any]:
        actor = self._require_actor(actor)
        ref = self._text(mandate_ref, "mandate reference")
        with self.db.transaction() as conn:
            row = self.db.one("SELECT * FROM customer_mandates WHERE mandate_ref = ? COLLATE NOCASE", (ref,))
            if row is None or row["customer_id"] != customer_id:
                raise ReceivableError(f"customer {customer_id} has no mandate {ref}")
            if row["status"] != "active":
                raise ReceivableError(f"mandate {ref} is already {row['status']}")
            conn.execute(
                "UPDATE customer_mandates SET status='revoked', revoked_at=?, revoked_by=?, revoke_reason=? WHERE id=?",
                (utcnow_iso(), actor, reason or "", row["id"]),
            )
            self.audit.record(actor, "mandate.revoked", "customer_mandate", row["id"], {"customer_id": customer_id, "mandate_ref": row["mandate_ref"], "reason": reason or ""})
        return self.db.one("SELECT * FROM customer_mandates WHERE id=?", (row["id"],))

    # ---- certification ------------------------------------------------------------ #

    def latest(self, project_id: str) -> dict[str, Any] | None:
        row = self.db.one("SELECT * FROM prime_bills WHERE project_id=? AND status != 'void' ORDER BY sequence DESC LIMIT 1", (project_id,))
        return self.get(row["id"]) if row else None

    def certify(self, *, project_id: str, period_id: str, certified_cumulative: str | Decimal, retainage_rate: str | Decimal | None = None, actor: str,
                invoice_date: str | _dt.date | None = None) -> dict[str, Any]:
        owner = getattr(self, "owner_billing", None)
        if owner is not None and owner.project_is_modern(project_id):
            raise ReceivableError("Owner certification requires its exact owned line-source preparation; use owner_billing.prepare.")
        return self._certify_legacy(project_id=project_id, period_id=period_id, certified_cumulative=certified_cumulative,
                                    retainage_rate=retainage_rate, actor=actor, invoice_date=invoice_date)

    def _certify_legacy(self, *, project_id: str, period_id: str, certified_cumulative: str | Decimal,
                        retainage_rate: str | Decimal | None = None, actor: str,
                        invoice_date: str | _dt.date | None = None) -> dict[str, Any]:
        """Create a draft prime bill from the cumulative certified value.

        The increment is computed against what the standing (posted, unreversed)
        prime bills already put on the books.  With a prime contract the certified
        cumulative may not exceed the contract value and the contract's retainage
        rate applies (an explicit different rate is refused); without one the rate
        defaults to 10%.  ``invoice_date`` (YYYY-MM-DD) dates the invoice: never later than
        today, never before the start of the bill's period and never before the invoice
        date of the latest standing prime bill on the project (invoices are dated in
        sequence); without it the bill is dated the day it posts.  Its due date is fixed
        when it posts, from the customer's payment terms then."""
        actor = self._require_actor(actor)
        project = self._project(project_id)
        if not project["customer_id"]:
            raise ReceivableError("project has no customer party")
        certified = self._money(certified_cumulative, "certified cumulative")
        if certified < 0:
            raise ReceivableInputError("certified cumulative cannot be negative")
        requested_date = None if invoice_date is None else self._date(invoice_date, "invoice date")
        if requested_date is not None and requested_date > self._today().isoformat():
            raise ReceivableInputError(f"invoice date {requested_date} is later than today ({self._today().isoformat()}); an invoice is never dated ahead")
        bill_period = self.ledger.require_open(period_id)
        if requested_date is not None and requested_date < bill_period["start_date"]:
            raise ReceivableInputError(
                f"invoice date {requested_date} is before the start of period {period_id} ({bill_period['start_date']}); "
                "an invoice is never dated before the period it is billed in")
        with self.db.transaction() as conn:
            prior = self.latest(project_id)
            if prior and prior["status"] == "draft":
                raise ReceivableError("the previous prime bill is still a draft; approve or void it first")
            contract = self.contract(project_id)
            if contract is not None:
                contract_rate = Decimal(contract["retainage_rate"])
                r = contract_rate if retainage_rate is None else self._rate(retainage_rate)
                if r != contract_rate:
                    raise ReceivableError(f"retainage rate {r:f} differs from the prime contract's {contract_rate:f} (version {contract['version']}); set a new contract version to change it")
                if certified > money(contract["contract_value"]):
                    raise ReceivableError(f"overbilling: certified cumulative {fmt(certified)} exceeds the prime contract value {contract['contract_value']} (version {contract['version']})")
            else:
                r = self._rate(DEFAULT_RETAINAGE_RATE if retainage_rate is None else retainage_rate)
            chain = self._billed_chain(project_id)
            latest_live = chain["latest"]
            if requested_date is not None and latest_live is not None and latest_live["invoice_date"] and requested_date < latest_live["invoice_date"]:
                raise ReceivableInputError(
                    f"invoice date {requested_date} is before the invoice date {latest_live['invoice_date']} of prime bill {latest_live['sequence']}, "
                    "the latest standing prime bill on the project; invoices are dated in sequence")
            prior_certified, prior_ret, prior_net = chain["certified"], chain["retained"], chain["net"]
            if certified < prior_certified:
                raise ReceivableError(f"certified cumulative cannot decrease: the standing prime bills already certify {fmt(prior_certified)}")
            ret_cum = pct(certified, r)
            amount_due = (certified - ret_cum) - prior_net
            revenue = certified - prior_certified
            retainage_this = ret_cum - prior_ret
            if amount_due < 0:
                raise ReceivableError(f"amount due would be negative ({fmt(amount_due)}); use a credit workflow instead")
            if amount_due == 0 and revenue == 0 and retainage_this == 0:
                where = f"prime bill {chain['latest']['sequence']}" if chain["latest"] else "zero"
                raise ReceivableError(f"nothing to bill: certified cumulative {fmt(certified)} and retainage are unchanged from {where}")
            released = self._released_to_date(project_id)
            if ret_cum < released:
                raise ReceivableError(f"retainage cumulative {fmt(ret_cum)} would fall below the {fmt(released)} already released and invoiced")
            last_seq = self.db.scalar("SELECT MAX(sequence) FROM prime_bills WHERE project_id=?", (project_id,)) or 0
            sequence = last_seq + 1
            contract_version = contract["version"] if contract else None
            hashed = {
                "project_id": project_id, "period_id": period_id, "sequence": sequence, "certified": fmt(certified), "rate": f"{r:f}",
                "retainage_cumulative": fmt(ret_cum), "amount_due": fmt(amount_due), "contract_version": contract_version,
            }
            if requested_date is not None:
                hashed["invoice_date"] = requested_date
            content_hash = hash_json(hashed)
            pid = new_id("pbl")
            conn.execute(
                """INSERT INTO prime_bills (id, project_id, customer_id, period_id, sequence, status, certified_cumulative, retainage_rate, retainage_cumulative,
                   prior_net, amount_due, revenue_this_period, content_hash, created_at, contract_version, invoice_date)
                   VALUES (?,?,?,?,?,'draft',?,?,?,?,?,?,?,?,?,?)""",
                (pid, project_id, project["customer_id"], period_id, sequence, fmt(certified), f"{r:f}", fmt(ret_cum), fmt(prior_net), fmt(amount_due),
                 fmt(revenue), content_hash, utcnow_iso(), contract_version, requested_date),
            )
            self.audit.record(actor, "prime_bill.certified", "prime_bill", pid, {
                "project_id": project_id, "sequence": sequence, "certified": fmt(certified), "amount_due": fmt(amount_due),
                "retainage_this_period": fmt(retainage_this), "contract_version": contract_version, "content_hash": content_hash,
                "prior_billed_certified": fmt(prior_certified), "prior_net": fmt(prior_net), "invoice_date": requested_date,
            })
        return self.get(pid)

    def _bill_balance(self, b: dict[str, Any]) -> dict[str, Decimal]:
        """Billed, received and reversed amounts of a prime bill, the standing credit memos,
        write-offs and deposit applications on it, and what stays open in 1100.  A reversed
        bill's journal cleared its whole receivable, so the bill is credited by its amount
        due; what was received or credited on it is then owed back."""
        billed = money(b["amount_due"]) if b["recorded_status"] in POSTED_BILL_STATES else ZERO
        received = total(c["credited"] for c in b["collections"])
        credited = billed if b["reversed"] else ZERO
        memos = total(m["amount"] for m in b["credit_memos"] if m["standing"])
        written = total(w["amount"] for w in b["write_offs"] if w["standing"])
        applied = total(a["amount"] for a in b["deposit_applications"] if a["standing"])
        return {"billed": billed, "received": received, "reversed": credited, "credit_memos": memos, "written_off": written,
                "deposits_applied": applied, "open": money(billed - received - credited - memos - written - applied)}

    def _adjustment_rows(self, table: str, column: str, key: str) -> list[dict[str, Any]]:
        """Credit memos, write-offs or deposit applications (``table``) on ``key``, each with
        its reversal state.  ``standing`` is true while a posted row's journal stands, and
        ``status`` reads ``reversed`` once it has been reversed (the stored status is kept
        as ``recorded_status``)."""
        return [self._annotate_adjustment(r) for r in self.db.query(f"SELECT * FROM {table} WHERE {column}=? ORDER BY created_at, id", (key,))]

    def get(self, prime_bill_id: str) -> dict[str, Any]:
        """A prime bill with its receipts, send, contract state and reversal state.
        ``status`` reads ``reversed`` once the bill's journal has been reversed (the
        stored status is kept as ``recorded_status``)."""
        row = self.db.one("SELECT * FROM prime_bills WHERE id=?", (prime_bill_id,))
        if row is None:
            raise ReceivableError(f"unknown prime bill {prime_bill_id}")
        # Dr 1100 amount due + Dr 1150 retainage = Cr 4000 revenue, so a bill's retainage
        # follows from its own stored amounts, never from the bills around it.
        row["retainage_this_period"] = fmt(money(row["revenue_this_period"]) - money(row["amount_due"]))
        row["recorded_status"] = row["status"]
        reversal = self._reversal_of(row["journal_id"]) if row["status"] in POSTED_BILL_STATES else None
        row["reversed"] = reversal is not None
        row["reversal_journal_id"] = reversal
        if reversal is not None:
            row["status"] = "reversed"
        row["collections"] = [self._receipt(c) for c in self.db.query("SELECT * FROM collections WHERE prime_bill_id=? ORDER BY received_at, id", (prime_bill_id,))]
        row["credit_memos"] = self._adjustment_rows("prime_bill_credit_memos", "prime_bill_id", prime_bill_id)
        row["write_offs"] = self._adjustment_rows("receivable_write_offs", "prime_bill_id", prime_bill_id)
        row["deposit_applications"] = self._adjustment_rows("deposit_applications", "prime_bill_id", prime_bill_id)
        bal = self._bill_balance(row)
        row["received"] = fmt(bal["received"])
        row["credited_by_reversal"] = fmt(bal["reversed"])
        row["credited_by_memo"] = fmt(bal["credit_memos"])
        row["written_off"] = fmt(bal["written_off"])
        row["deposits_applied"] = fmt(bal["deposits_applied"])
        row["open"] = fmt(bal["open"])
        # settled: posted, standing, and nothing left open (by receipts, credits or applications)
        row["settled"] = row["recorded_status"] in POSTED_BILL_STATES and not row["reversed"] and bal["open"] == ZERO
        send = self.db.one("SELECT * FROM prime_bill_sends WHERE prime_bill_id=?", (prime_bill_id,))
        if send is not None:
            send["recipients"] = loads(send.pop("recipients_json"))
        row["send"] = send
        # A bill delivered by the old direct send() (before prime_bill.send existed) has no
        # send record; the upgrade recorded it in prime_bill_legacy_sends.  It counts as sent:
        # it is never delivered again, and it reads 'sent' while its stored status is 'posted'
        # (the bill guard only lets a bill with a send record be stored as 'sent').
        legacy = self.db.one("SELECT * FROM prime_bill_legacy_sends WHERE prime_bill_id=?", (prime_bill_id,)) if send is None else None
        row["legacy_send"] = legacy
        row["delivered"] = send is not None or legacy is not None
        if legacy is not None and row["status"] == "posted":
            row["status"] = "sent"
        contract = self.contract(row["project_id"])
        row["contract_current_version"] = contract["version"] if contract else None
        is_draft = row["status"] == "draft"
        row["contract_stale"] = is_draft and row["contract_version"] != row["contract_current_version"]
        row["chain_stale"] = False
        if is_draft:
            # the draft's increment was computed on the standing bills; a reversal since then breaks it
            chain = self._billed_chain(row["project_id"])
            prior_certified = money(row["certified_cumulative"]) - money(row["revenue_this_period"])
            row["chain_stale"] = chain["net"] != money(row["prior_net"]) or chain["certified"] != prior_certified
        return row

    def list(self, project_id: str) -> list[dict[str, Any]]:
        return [self.get(r["id"]) for r in self.db.query("SELECT id FROM prime_bills WHERE project_id=? ORDER BY sequence", (project_id,))]

    def void(self, prime_bill_id: str, *, actor: str, reason: str = "") -> dict[str, Any]:
        """Void a draft; posted bills are corrected by reversing their journal
        (``journal.reverse``).  Open approvals on the bill are invalidated in the same
        transaction."""
        owner = getattr(self, "owner_billing", None)
        if owner is not None and owner.is_modern(prime_bill_id):
            raise ReceivableError("Owned owner certification cancellation requires its separate governed source workflow.")
        actor = self._require_actor(actor)
        with self.db.transaction() as conn:
            b = self.get(prime_bill_id)
            if b["status"] != "draft":
                raise ReceivableError(f"prime bill {prime_bill_id} is {b['status']}; only a draft can be voided (posted bills are corrected by reversal)")
            conn.execute("UPDATE prime_bills SET status='void' WHERE id=?", (prime_bill_id,))
            self.audit.record(actor, "prime_bill.voided", "prime_bill", prime_bill_id, {"reason": reason or "", "sequence": b["sequence"]})
            Approvals(self.db, self.audit).invalidate_for_subject("prime_bill", prime_bill_id, reason=f"prime bill voided: {reason or 'no reason given'}", actor=actor)
        return self.get(prime_bill_id)

    # ---- approval and posting (prime_bill.approve) ------------------------------------ #

    @staticmethod
    def _bill_lines(b: dict[str, Any]) -> list[dict[str, Any]]:
        amount_due, ret, revenue = money(b["amount_due"]), money(b["retainage_this_period"]), money(b["revenue_this_period"])
        tags = {"project_id": b["project_id"], "party_id": b["customer_id"]}
        lines = []
        if amount_due > 0:
            lines.append({"account": "1100", "debit": amount_due, **tags, "memo": f"prime bill {b['sequence']}"})
        if ret > 0:
            lines.append({"account": "1150", "debit": ret, **tags, "memo": "retainage receivable"})
        if revenue > 0:
            lines.append({"account": "4000", "credit": revenue, **tags, "memo": "certified progress (fixture policy)"})
        if ret < 0:
            lines.append({"account": "1150", "credit": -ret, **tags, "memo": "retainage reduction"})
        return lines

    @staticmethod
    def _preview(lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [{"account": ln["account"], "debit": fmt(ln.get("debit", ZERO)), "credit": fmt(ln.get("credit", ZERO)), "memo": ln.get("memo", "")} for ln in lines]

    def _check_billable(self, b: dict[str, Any]) -> dict[str, Any] | None:
        """Refuse a draft that no longer fits its contract or the standing bills.
        Returns the current contract."""
        contract = self.contract(b["project_id"])
        if b["contract_stale"]:
            raise ReceivableIneligible(
                f"the prime contract changed (version {b['contract_version']} -> {b['contract_current_version']}) after prime bill {b['sequence']} "
                "was certified; void and re-certify it")
        if b["chain_stale"]:
            raise ReceivableIneligible(
                f"a prime bill that draft prime bill {b['sequence']} was computed on has been reversed since it was certified; void and re-certify it")
        if contract is not None and money(b["certified_cumulative"]) > money(contract["contract_value"]):
            raise ReceivableIneligible(f"overbilling: certified cumulative {b['certified_cumulative']} exceeds the prime contract value {contract['contract_value']}")
        released = self._released_to_date(b["project_id"])
        if money(b["retainage_cumulative"]) < released:
            raise ReceivableIneligible(f"retainage cumulative {b['retainage_cumulative']} is below the {fmt(released)} already released")
        return contract

    def manifest(self, prime_bill_id: str, *, actor_role: str) -> dict[str, Any]:
        owner = getattr(self, "owner_billing", None)
        if owner is not None and owner.is_modern(prime_bill_id):
            return owner.manifest(prime_bill_id, actor_role=actor_role)
        return self._legacy_manifest(prime_bill_id, actor_role=actor_role)

    def _legacy_manifest(self, prime_bill_id: str, *, actor_role: str) -> dict[str, Any]:
        """Manifest for ``prime_bill.approve``: amounts, the bill hash, the contract version
        and value, the billed chain it continues, entity, currency and the exact journal
        lines the posting will make."""
        b = self.get(prime_bill_id)
        if b["status"] != "draft":
            raise ReceivableIneligible(f"prime bill {prime_bill_id} is {b['status']}; only a draft prime bill can be approved for posting")
        contract = self._check_billable(b)
        project = self._project(b["project_id"])
        terms = self.payment_terms(b["customer_id"])
        return build_manifest(
            operation="prime_bill.approve",
            subject_type="prime_bill",
            subject_id=prime_bill_id,
            actor_role=actor_role,
            entity=project["entity"],
            currency=project["currency"],
            amounts={"amount_due": b["amount_due"], "revenue_this_period": b["revenue_this_period"], "retainage_this_period": b["retainage_this_period"],
                     "certified_cumulative": b["certified_cumulative"]},
            bindings={
                "project_id": b["project_id"], "customer_id": b["customer_id"], "period_id": b["period_id"], "sequence": b["sequence"],
                "bill_hash": b["content_hash"], "retainage_rate": b["retainage_rate"], "recognition_policy": RECOGNITION_POLICY,
                "contract_version": contract["version"] if contract else None, "contract_value": contract["contract_value"] if contract else None,
                "bill_contract_version": b["contract_version"], "prior_net": b["prior_net"],
                "prior_billed_certified": fmt(money(b["certified_cumulative"]) - money(b["revenue_this_period"])),
                "posting_rule": RULE_VERSION, "journal_preview": self._preview(self._bill_lines(b)),
                # the due date follows from the invoice date and these terms when the bill posts
                "invoice_date": b["invoice_date"], "invoice_date_basis": "explicit" if b["invoice_date"] else "date of posting",
                "payment_terms_days": terms["days"], "payment_terms_version": terms["version"],
            },
        )

    def post(self, prime_bill_id: str, *, approval_id: str, actor: str, manifest: dict[str, Any] | None = None) -> dict[str, Any]:
        owner = getattr(self, "owner_billing", None)
        if owner is not None and owner.is_modern(prime_bill_id):
            raise ReceivableError("Owner business approval does not post; use separate independent post_prime_bill.")
        return self._post_legacy(prime_bill_id, approval_id=approval_id, actor=actor, manifest=manifest)

    def _post_legacy(self, prime_bill_id: str, *, approval_id: str, actor: str, manifest: dict[str, Any] | None = None) -> dict[str, Any]:
        """Post an approved draft.  The caller has consumed ``approval_id``.  The bill is
        dated (its requested invoice date, or today) and its due date fixed from the
        payment terms the approval bound (the current terms when no manifest is given)."""
        with self.db.transaction() as conn:
            b = self.get(prime_bill_id)
            if b["status"] != "draft":
                raise ReceivableError(f"prime bill {prime_bill_id} is {b['status']}")
            self._check_billable(b)
            terms = self.payment_terms(b["customer_id"])
            bound = (manifest or {}).get("bindings", {})
            if "payment_terms_days" in bound and bound["payment_terms_days"] != terms["days"]:
                raise ReceivableIneligible(f"the customer's payment terms are now {terms['days']} days, not the approved {bound['payment_terms_days']}")
            invoice_date = b["invoice_date"] or self._today().isoformat()
            due_date = self._plus_days(invoice_date, terms["days"])
            j = self.ledger.post(
                period_id=b["period_id"], description=f"Prime bill {b['sequence']}", lines=self._bill_lines(b),
                source_type="prime_bill", source_id=prime_bill_id, source_version="1", posted_by=actor, approval_id=approval_id,
            )
            conn.execute("UPDATE prime_bills SET status='posted', approval_id=?, journal_id=?, invoice_date=?, due_date=?, payment_terms_days=? WHERE id=?",
                         (approval_id, j["id"], invoice_date, due_date, terms["days"], prime_bill_id))
            self.audit.record(actor, "prime_bill.posted", "prime_bill", prime_bill_id, {
                "approval_id": approval_id, "journal_id": j["id"], "contract_version": b["contract_version"],
                "invoice_date": invoice_date, "due_date": due_date, "payment_terms_days": terms["days"], "payment_terms_version": terms["version"],
            })
        return self.get(prime_bill_id)

    # ---- core-domain operations: handles / manifest_for / apply --------------------- #

    def handles(self, operation: str) -> bool:
        return operation in OWNED_OPERATIONS

    def manifest_for(self, operation: str, subject_id: str, *, actor_role: str) -> dict[str, Any]:
        if operation == OP_SEND:
            return self._send_manifest(subject_id, actor_role=actor_role)
        if operation == OP_RELEASE_RETAINAGE:
            return self._retainage_manifest(subject_id, actor_role=actor_role)
        if operation == OP_CREDIT_MEMO:
            return self._credit_memo_manifest(subject_id, actor_role=actor_role)
        if operation == OP_WRITE_OFF:
            return self._write_off_manifest(subject_id, actor_role=actor_role)
        if operation == OP_APPLY_DEPOSIT:
            return self._application_manifest(subject_id, actor_role=actor_role)
        raise ReceivableError(f"receivables does not own operation {operation}")

    def apply(self, operation: str, subject_id: str, *, approval_id: str, manifest: dict[str, Any], actor: str, period_id: str | None) -> dict[str, Any]:
        if operation == OP_SEND:
            return self._apply_send(subject_id, approval_id=approval_id, manifest=manifest, actor=actor)
        if operation == OP_RELEASE_RETAINAGE:
            return self._apply_release(subject_id, approval_id=approval_id, manifest=manifest, actor=actor, period_id=period_id)
        if operation == OP_CREDIT_MEMO:
            return self._apply_credit_memo(subject_id, approval_id=approval_id, manifest=manifest, actor=actor, period_id=period_id)
        if operation == OP_WRITE_OFF:
            return self._apply_write_off(subject_id, approval_id=approval_id, manifest=manifest, actor=actor, period_id=period_id)
        if operation == OP_APPLY_DEPOSIT:
            return self._apply_application(subject_id, approval_id=approval_id, manifest=manifest, actor=actor, period_id=period_id)
        raise ReceivableError(f"receivables does not own operation {operation}")

    # ---- sending (prime_bill.send) ----------------------------------------------------- #

    def send(self, prime_bill_id: str | None = None, actor: str | None = None, *args: Any, **kwargs: Any) -> dict[str, Any]:
        """Sending is a separate authority (plan section 6): it never happens directly.
        Every call shape (``send(bid, actor)``, ``send(bid, actor=...)``) is refused the
        same way, with ReceivableError."""
        raise ReceivableError(
            f"sending prime bill {prime_bill_id} is its own authority: request, grant and execute the 'prime_bill.send' approval "
            "(it binds the bill hash, the customer, the channel and the recipients)")

    def _sendable(self, b: dict[str, Any]) -> None:
        if b["reversed"]:
            raise ReceivableIneligible(
                f"prime bill {b['sequence']} ({b['id']}) was reversed by journal {b['reversal_journal_id']}; a reversed prime bill is never sent")
        if b["status"] in ("draft", "void"):
            raise ReceivableIneligible(f"prime bill {b['id']} is {b['status']}; only a posted prime bill can be sent")
        if b["send"] is not None:
            raise ReceivableIneligible(f"prime bill {b['id']} was already sent ({b['send']['sent_at']})")
        if b["legacy_send"] is not None:
            raise ReceivableIneligible(
                f"prime bill {b['id']} was already sent before sending became its own authority "
                f"(legacy send, {b['legacy_send']['detected_from']}); it is never delivered again")
        if b["recorded_status"] != "posted":
            raise ReceivableIneligible(f"prime bill {b['id']} is {b['status']}; only a posted prime bill awaiting delivery can be sent")

    @staticmethod
    def _send_message(b: dict[str, Any], rec: dict[str, Any]) -> dict[str, Any]:
        """What the delivered invoice states: the bill, its amount due, every standing receipt,
        credit memo, write-off and deposit application already taken off it, and the balance
        due.  The send approval binds its hash, so any of these changing after approval makes
        the approval stale (the customer is never told a balance that is no longer owed)."""
        message = {
            "prime_bill_id": b["id"], "bill_hash": b["content_hash"], "sequence": b["sequence"], "amount_due": b["amount_due"],
            "received": b["received"], "credited_by_memo": b["credited_by_memo"], "written_off": b["written_off"],
            "deposits_applied": b["deposits_applied"], "balance_due": b["open"],
            "customer_id": b["customer_id"], "channel": SEND_CHANNEL, "recipients": rec["recipients"],
        }
        if b["due_date"]:  # the delivered invoice states its dates (bills posted before dates existed have none)
            message.update(invoice_date=b["invoice_date"], due_date=b["due_date"])
        return message

    def _send_manifest(self, prime_bill_id: str, *, actor_role: str) -> dict[str, Any]:
        owner = getattr(self, "owner_billing", None)
        if owner is not None and owner.is_modern(prime_bill_id):
            owner.require_posted_proof(prime_bill_id)
            owner.send_source_preflight(prime_bill_id)
        b = self.get(prime_bill_id)
        self._sendable(b)
        project = self._project(b["project_id"])
        customer = self._customer(b["customer_id"])
        rec = self.billing_recipients(b["customer_id"])
        message_hash = hash_json(self._send_message(b, rec))
        manifest = build_manifest(
            operation=OP_SEND,
            subject_type="prime_bill",
            subject_id=prime_bill_id,
            actor_role=actor_role,
            entity=project["entity"],
            currency=project["currency"],
            amounts={"amount_due": b["amount_due"]},
            bindings={
                "project_id": b["project_id"], "customer_id": b["customer_id"], "customer_name": customer["name"], "sequence": b["sequence"],
                "period_id": b["period_id"], "bill_hash": b["content_hash"], "journal_id": b["journal_id"], "journal_reversed": b["reversed"],
                "channel": SEND_CHANNEL, "recipients": rec["recipients"], "recipients_version": rec["version"], "message_hash": message_hash,
                "invoice_date": b["invoice_date"], "due_date": b["due_date"],
                # the balance the invoice states: a receipt, credit memo, write-off or deposit
                # application after approval changes it, so the approval goes stale
                "received": b["received"], "credited_by_memo": b["credited_by_memo"], "written_off": b["written_off"],
                "deposits_applied": b["deposits_applied"], "balance_due": b["open"],
            },
        )
        if owner is not None and owner.is_modern(prime_bill_id):
            source = owner.source_proof(prime_bill_id)
            manifest["bindings"].update({"owner_source_hash": source["sourceHash"],
                                         "owner_posting_hash": hash_json(owner.require_posted_proof(prime_bill_id))})
        return manifest

    def _apply_send(self, prime_bill_id: str, *, approval_id: str, manifest: dict[str, Any], actor: str) -> dict[str, Any]:
        """Deliver to the synthetic mail sink; nothing leaves the prototype."""
        owner = getattr(self, "owner_billing", None)
        if owner is not None and owner.is_modern(prime_bill_id):
            source = owner.source_proof(prime_bill_id)
            receipt = owner.require_posted_proof(prime_bill_id)
            if (manifest["bindings"].get("owner_source_hash") != source["sourceHash"]
                    or manifest["bindings"].get("owner_posting_hash") != hash_json(receipt)):
                raise ReceivableIneligible("The owner send no longer binds its exact original source and posting receipt")
        bindings = manifest["bindings"]
        with self.db.transaction() as conn:
            b = self.get(prime_bill_id)
            self._sendable(b)
            if bindings["bill_hash"] != b["content_hash"] or bindings["channel"] != SEND_CHANNEL:
                raise ReceivableIneligible(f"prime bill {prime_bill_id} no longer matches the approved send")
            current = hash_json(self._send_message(b, self.billing_recipients(b["customer_id"])))
            if bindings.get("message_hash") != current:
                raise ReceivableIneligible(
                    f"prime bill {prime_bill_id} now states balance due {b['open']} (amount due {b['amount_due']}, received {b['received']}, "
                    f"credited {b['credited_by_memo']}, written off {b['written_off']}, deposits applied {b['deposits_applied']}) "
                    "or other recipients than the approved send; request a new send approval")
            sid = new_id("snd")
            conn.execute(
                "INSERT INTO prime_bill_sends (id, prime_bill_id, approval_id, channel, recipients_json, bill_hash, message_hash, sent_at, sent_by) VALUES (?,?,?,?,?,?,?,?,?)",
                (sid, prime_bill_id, approval_id, SEND_CHANNEL, canonical_json(bindings["recipients"]), b["content_hash"], bindings["message_hash"], utcnow_iso(), actor),
            )
            conn.execute("UPDATE prime_bills SET status='sent' WHERE id=?", (prime_bill_id,))
            self.audit.record(actor, "prime_bill.sent", "prime_bill", prime_bill_id, {
                "channel": SEND_CHANNEL, "customer_id": b["customer_id"], "recipients": bindings["recipients"], "approval_id": approval_id,
                "send_id": sid, "message_hash": bindings["message_hash"],
            })
        return {"prime_bill": prime_bill_id, "status": "sent", "send_id": sid, "channel": SEND_CHANNEL, "recipients": bindings["recipients"]}

    # ---- prime retainage (prime_retainage.release) ------------------------------------- #

    def _retainage_state(self, project_id: str) -> dict[str, Any]:
        """The project's retainage receivable: withheld on the standing prime bills less
        what standing releases already invoiced, with the cut-off period a release
        must not precede."""
        project = self._project(project_id)
        latest_any = self.db.one("SELECT sequence, status FROM prime_bills WHERE project_id=? AND status != 'void' ORDER BY sequence DESC LIMIT 1", (project_id,))
        chain = self._billed_chain(project_id)
        latest_live = chain["latest"]
        released = self._released_to_date(project_id)
        last_invoice = self.db.scalar("SELECT MAX(sequence) FROM prime_retainage_invoices WHERE project_id=?", (project_id,)) or 0
        reversed_bills = [r["sequence"] for r in self.db.query(
            "SELECT b.sequence FROM prime_bills b WHERE b.project_id=? AND b.status IN ('posted','sent','collected') "
            "AND EXISTS (SELECT 1 FROM journals rv WHERE rv.reversal_of = b.journal_id) ORDER BY b.sequence", (project_id,))]
        reversed_invoices = [r["sequence"] for r in self.db.query(
            "SELECT i.sequence FROM prime_retainage_invoices i WHERE i.project_id=? "
            "AND EXISTS (SELECT 1 FROM journals rv WHERE rv.reversal_of = i.journal_id) ORDER BY i.sequence", (project_id,))]
        cutoff = None
        for b in chain["bills"]:
            if money(b["revenue_this_period"]) == money(b["amount_due"]):
                continue  # this bill withheld no retainage
            p = self.ledger.period(b["period_id"])
            if cutoff is None or p["start_date"] > cutoff["start_date"]:
                cutoff = p
        return {
            "project_id": project_id,
            "customer_id": latest_live["customer_id"] if latest_live else project["customer_id"],
            "latest_sequence": latest_any["sequence"] if latest_any else None,
            "draft_sequence": latest_any["sequence"] if latest_any and latest_any["status"] == "draft" else None,
            "through_sequence": latest_live["sequence"] if latest_live else None,
            "certified": fmt(chain["certified"]),
            "retained": chain["retained"],
            "released": released,
            "open": money(chain["retained"] - released),
            "next_invoice_sequence": last_invoice + 1,
            "reversed_prime_bill_sequences": reversed_bills,
            "reversed_retainage_invoice_sequences": reversed_invoices,
            "cutoff_period": {"id": cutoff["id"], "start_date": cutoff["start_date"]} if cutoff else None,
        }

    @staticmethod
    def _release_lines(project_id: str, customer_id: str, amount: Decimal, sequence: int) -> list[dict[str, Any]]:
        tags = {"project_id": project_id, "party_id": customer_id}
        return [
            {"account": "1100", "debit": amount, **tags, "memo": f"retainage invoice {sequence}"},
            {"account": "1150", "credit": amount, **tags, "memo": "prime retainage released"},
        ]

    def _releasable(self, project_id: str) -> dict[str, Any]:
        st = self._retainage_state(project_id)
        if st["draft_sequence"] is not None:
            raise ReceivableIneligible(f"prime bill {st['draft_sequence']} is still a draft; approve or void it before releasing retainage")
        if st["open"] <= 0:
            raise ReceivableIneligible(f"project {project_id} has no prime retainage receivable to release")
        return st

    def _retainage_manifest(self, project_id: str, *, actor_role: str) -> dict[str, Any]:
        project = self._project(project_id)
        st = self._releasable(project_id)
        contract = self.contract(project_id)
        lines = self._release_lines(project_id, st["customer_id"], st["open"], st["next_invoice_sequence"])
        cutoff = st["cutoff_period"]
        terms = self.payment_terms(st["customer_id"])
        return build_manifest(
            operation=OP_RELEASE_RETAINAGE,
            subject_type="project",
            subject_id=project_id,
            actor_role=actor_role,
            entity=project["entity"],
            currency=project["currency"],
            amounts={"retainage_receivable": st["open"]},
            bindings={
                "project_id": project_id, "customer_id": st["customer_id"],
                "contract_version": contract["version"] if contract else None, "contract_value": contract["contract_value"] if contract else None,
                "latest_prime_bill_sequence": st["latest_sequence"], "through_prime_bill_sequence": st["through_sequence"],
                "certified_cumulative": st["certified"], "retained_to_date": fmt(st["retained"]), "released_to_date": fmt(st["released"]),
                "reversed_prime_bill_sequences": st["reversed_prime_bill_sequences"],
                "reversed_retainage_invoice_sequences": st["reversed_retainage_invoice_sequences"],
                "invoice_sequence": st["next_invoice_sequence"], "posting_rule": RULE_VERSION, "journal_preview": self._preview(lines),
                "earliest_period": cutoff,
                "target_rule": (f"execute with period_id of an open period starting on or after {cutoff['start_date']} (period {cutoff['id']})"
                                if cutoff else "execute with period_id of an open period"),
                # the retainage invoice is dated the day the release posts, due on these terms
                "invoice_date_basis": "date of posting", "payment_terms_days": terms["days"], "payment_terms_version": terms["version"],
            },
        )

    def _apply_release(self, project_id: str, *, approval_id: str, manifest: dict[str, Any], actor: str, period_id: str | None) -> dict[str, Any]:
        pid = period_id or self._latest_open_period()
        target = self.ledger.require_open(pid)
        with self.db.transaction() as conn:
            st = self._releasable(project_id)
            amount = st["open"]
            if fmt(amount) != manifest["amounts"].get("retainage_receivable"):
                raise ReceivableIneligible(f"retainage receivable is now {fmt(amount)}, not the approved {manifest['amounts'].get('retainage_receivable')}")
            cutoff = st["cutoff_period"]
            if cutoff is not None:
                self._require_not_before(target, cutoff["id"], f"retainage withheld on prime bills through sequence {st['through_sequence']}")
            contract = self.contract(project_id)
            contract_version = contract["version"] if contract else None
            terms = self.payment_terms(st["customer_id"])
            bound_days = manifest.get("bindings", {}).get("payment_terms_days", terms["days"])
            if bound_days != terms["days"]:
                raise ReceivableIneligible(f"the customer's payment terms are now {terms['days']} days, not the approved {bound_days}")
            invoice_date = self._today().isoformat()
            due_date = self._plus_days(invoice_date, terms["days"])
            seq = st["next_invoice_sequence"]
            inv_id = new_id("rti")
            j = self.ledger.post(
                period_id=pid, description=f"Prime retainage release (retainage invoice {seq}) on project {project_id}",
                lines=self._release_lines(project_id, st["customer_id"], amount, seq),
                source_type="prime_retainage_release", source_id=inv_id, source_version=str(contract_version or 0), posted_by=actor, approval_id=approval_id,
            )
            content_hash = hash_json({
                "project_id": project_id, "sequence": seq, "amount": fmt(amount), "contract_version": contract_version,
                "through_prime_bill_sequence": st["through_sequence"], "period_id": pid, "invoice_date": invoice_date, "due_date": due_date,
            })
            conn.execute(
                """INSERT INTO prime_retainage_invoices (id, project_id, customer_id, period_id, sequence, amount, status, contract_version,
                   through_prime_bill_sequence, content_hash, approval_id, journal_id, created_at, created_by, invoice_date, due_date, payment_terms_days)
                   VALUES (?,?,?,?,?,?,'open',?,?,?,?,?,?,?,?,?,?)""",
                (inv_id, project_id, st["customer_id"], pid, seq, fmt(amount), contract_version, st["through_sequence"], content_hash, approval_id, j["id"],
                 utcnow_iso(), actor, invoice_date, due_date, terms["days"]),
            )
            self.audit.record(actor, "prime_retainage.released", "prime_retainage_invoice", inv_id, {
                "project_id": project_id, "amount": fmt(amount), "journal_id": j["id"], "approval_id": approval_id, "period_id": pid,
                "contract_version": contract_version, "through_prime_bill_sequence": st["through_sequence"], "sequence": seq,
                "invoice_date": invoice_date, "due_date": due_date, "payment_terms_days": terms["days"],
            })
        return {"retainage_invoice": inv_id, "project_id": project_id, "sequence": seq, "amount": fmt(amount), "journal_id": j["id"], "period_id": pid,
                "status": "open", "invoice_date": invoice_date, "due_date": due_date}

    def retainage_invoice(self, invoice_id: str) -> dict[str, Any]:
        """A retainage invoice with its receipts and reversal state.  ``status`` reads
        ``reversed`` once its release journal has been reversed."""
        row = self.db.one("SELECT * FROM prime_retainage_invoices WHERE id=?", (invoice_id,))
        if row is None:
            raise ReceivableError(f"unknown retainage invoice {invoice_id}")
        row["recorded_status"] = row["status"]
        reversal = self._reversal_of(row["journal_id"])
        row["reversed"] = reversal is not None
        row["reversal_journal_id"] = reversal
        if reversal is not None:
            row["status"] = "reversed"
        row["collections"] = [self._receipt(c) for c in self.db.query(
            "SELECT * FROM prime_retainage_collections WHERE retainage_invoice_id=? ORDER BY received_at, id", (invoice_id,))]
        amount = money(row["amount"])
        received = total(c["credited"] for c in row["collections"])
        credited = amount if reversal is not None else ZERO
        row["received"] = fmt(received)
        row["credited_by_reversal"] = fmt(credited)
        row["open"] = fmt(amount - received - credited)
        return row

    def retainage_invoices(self, project_id: str | None = None) -> list[dict[str, Any]]:
        if project_id:
            rows = self.db.query("SELECT id FROM prime_retainage_invoices WHERE project_id=? ORDER BY sequence", (project_id,))
        else:
            rows = self.db.query("SELECT id FROM prime_retainage_invoices ORDER BY project_id, sequence")
        return [self.retainage_invoice(r["id"]) for r in rows]

    # ---- collections and returns ------------------------------------------------------- #

    def _receipt_ref_taken(self, ref: str) -> str | None:
        for table in _RECEIPT_TABLES:
            if self._table_exists(table) and self.db.one(f"SELECT id FROM {table} WHERE provider_ref = ? COLLATE NOCASE", (ref,)) is not None:
                return table
        return None

    def receipt_reference_conflicts(self) -> list[dict[str, Any]]:
        """Receipt references recorded more than once ignoring case, across every receipt
        table present (core collections, retainage collections, labor T&M and
        reimbursement collections).  Between the core tables only data written before
        the receivables_controls schema can clash (new receipts are refused on it); a
        plugin table can also clash when its module let a duplicate through.  The rows
        stay as recorded and are reported here."""
        rows: list[dict[str, Any]] = []
        for table in _RECEIPT_TABLES:
            if table in _CORE_RECEIPT_TABLES or self._table_exists(table):
                rows += [{"table": table, **r} for r in self.db.query(f"SELECT id, provider_ref FROM {table}")]
        groups: dict[str, list[dict[str, Any]]] = {}
        for r in rows:
            # SQLite NOCASE folds ASCII letters only; fold the same way
            key = "".join(chr(ord(ch) + 32) if "A" <= ch <= "Z" else ch for ch in r["provider_ref"])
            groups.setdefault(key, []).append(r)
        return [{"provider_ref": key, "records": sorted(v, key=lambda x: (x["table"], x["id"]))}
                for key, v in sorted(groups.items()) if len(v) > 1]

    def record_collection(
        self,
        *,
        prime_bill_id: str | None = None,
        retainage_invoice_id: str | None = None,
        period_id: str,
        amount: str | Decimal,
        fee: str | Decimal = "0",
        provider_ref: str,
        actor: str,
        method: str = "ach",
        mandate_ref: str | None = None,
        settlement_date: str | _dt.date | None = None,
    ) -> dict[str, Any]:
        """Record a customer receipt against a prime bill or a retainage invoice.

        ``method`` is ``ach`` (needs the customer's active debit mandate: the named
        ``mandate_ref`` or the latest active one), ``check`` or ``wire``.  The provider
        reference is unique across every receipt table, ignoring case.  A reversed bill
        or invoice has nothing receivable, and a receipt is never dated in a period
        that starts before the period of the bill or invoice it collects.
        ``settlement_date`` (default today) is when the money settled, kept apart from the
        time the receipt is recorded; it is never in the future and never before the
        invoice date of what it collects.  What is open is net of credit memos,
        write-offs and deposit applications; the bill reads collected only once its
        receipts cover its whole amount due."""
        actor = self._require_actor(actor)
        if (prime_bill_id is None) == (retainage_invoice_id is None):
            raise ReceivableInputError("name exactly one of prime_bill_id or retainage_invoice_id")
        m = method.strip().lower() if isinstance(method, str) else ""
        if m not in COLLECTION_METHODS:
            raise ReceivableInputError(f"collection method {method!r} is not one of {', '.join(COLLECTION_METHODS)}")
        if mandate_ref is not None and m != "ach":
            raise ReceivableInputError("a mandate reference applies to ACH collections only")
        amt = self._money(amount, "collection amount")
        f = self._money(fee, "fee")
        if amt <= 0 or f < 0 or f >= amt:
            raise ReceivableInputError("invalid collection amount or fee (amount must be positive and the fee below it)")
        ref = self._text(provider_ref, "provider reference")
        if settlement_date is not None:
            self._date(settlement_date, "settlement date")  # input errors first, before any lookup
        target_period = self.ledger.require_open(period_id)
        with self.db.transaction() as conn:
            taken = self._receipt_ref_taken(ref)
            if taken:
                raise ReceivableDuplicate(f"collection {ref} was already recorded ({taken})")
            if prime_bill_id is not None:
                b = self.get(prime_bill_id)
                if b["recorded_status"] not in POSTED_BILL_STATES:
                    raise ReceivableError(f"prime bill {prime_bill_id} is {b['status']}")
                if b["reversed"]:
                    raise ReceivableError(f"prime bill {b['sequence']} ({prime_bill_id}) was reversed by journal {b['reversal_journal_id']}; nothing is receivable on it")
                open_amt = money(b["open"])
                recorded_status, source_period = b["recorded_status"], b["period_id"]
                covers_amount = money(b["received"]) + amt >= money(b["amount_due"])
                target = {"project_id": b["project_id"], "customer_id": b["customer_id"], "label": f"prime bill {b['sequence']}", "invoice_date": b["invoice_date"]}
            else:
                inv = self.retainage_invoice(retainage_invoice_id)
                if inv["reversed"]:
                    raise ReceivableError(f"retainage invoice {inv['sequence']} ({retainage_invoice_id}) was reversed by journal {inv['reversal_journal_id']}; nothing is receivable on it")
                open_amt = money(inv["open"])
                recorded_status, source_period = inv["recorded_status"], inv["period_id"]
                covers_amount = amt == open_amt
                target = {"project_id": inv["project_id"], "customer_id": inv["customer_id"], "label": f"retainage invoice {inv['sequence']}",
                          "invoice_date": inv.get("invoice_date")}
            if open_amt <= 0:
                raise ReceivableError(f"{target['label']} is {recorded_status} with nothing open to collect")
            if amt > open_amt:
                raise ReceivableError(f"collection {fmt(amt)} exceeds open receivable {fmt(open_amt)}")
            self._require_not_before(target_period, source_period, target["label"])
            settled_on = self._settlement_date(settlement_date, not_before=target["invoice_date"], what=target["label"])
            mandate = None
            if m == "ach":
                mandate = self.active_mandate(target["customer_id"], mandate_ref)
                if mandate is None:
                    named = f" {mandate_ref} is not an active mandate of this customer" if mandate_ref is not None else " none is active"
                    raise ReceivableError(
                        f"missing mandate: an ACH collection from customer {target['customer_id']} needs its active debit mandate;{named}. "
                        "Record one with record_mandate, or collect by check or wire")
            tags = {"project_id": target["project_id"], "party_id": target["customer_id"]}
            lines = [{"account": "1000", "debit": amt - f, **tags, "memo": _BANK_MEMO[m]}]
            if f > 0:
                lines.append({"account": "6000", "debit": f, **tags, "memo": "processing fee"})
            lines.append({"account": "1100", "credit": amt, **tags, "memo": f"{target['label']} collected"})
            j = self.ledger.post(period_id=period_id, description=f"Collection on {target['label']}", lines=lines, source_type="collection", source_id=ref, source_version="1", posted_by=actor)
            mandate_id = mandate["id"] if mandate else None
            now = utcnow_iso()
            if prime_bill_id is not None:
                cid = new_id("col")
                conn.execute(
                    "INSERT INTO collections (id, prime_bill_id, amount, fee, status, journal_id, provider_ref, received_at, method, mandate_id, settlement_date) "
                    "VALUES (?,?,?,?,'received',?,?,?,?,?,?)",
                    (cid, prime_bill_id, fmt(amt), fmt(f), j["id"], ref, now, m, mandate_id, settled_on),
                )
                # collected exactly while the receipts cover the amount due (a bill settled partly by
                # credits or applications stays posted or sent, with nothing open)
                if covers_amount and recorded_status != "collected":
                    conn.execute("UPDATE prime_bills SET status='collected' WHERE id=?", (prime_bill_id,))
            else:
                cid = new_id("rcl")
                conn.execute(
                    """INSERT INTO prime_retainage_collections (id, retainage_invoice_id, amount, fee, method, mandate_id, status, journal_id, provider_ref, received_at,
                       recorded_by, settlement_date) VALUES (?,?,?,?,?,?,'received',?,?,?,?,?)""",
                    (cid, retainage_invoice_id, fmt(amt), fmt(f), m, mandate_id, j["id"], ref, now, actor, settled_on),
                )
                if covers_amount and recorded_status != "collected":
                    conn.execute("UPDATE prime_retainage_invoices SET status='collected' WHERE id=?", (retainage_invoice_id,))
            self.audit.record(actor, "collection.recorded", "collection", cid, {
                "prime_bill_id": prime_bill_id, "retainage_invoice_id": retainage_invoice_id, "amount": fmt(amt), "fee": fmt(f), "journal_id": j["id"],
                "method": m, "mandate_ref": mandate["mandate_ref"] if mandate else None, "provider_ref": ref, "period_id": period_id,
                "settlement_date": settled_on,
            })
        return self.collection(cid)

    def collection(self, collection_id: str) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM collections WHERE id=?", (collection_id,))
        if row is None:
            row = self.db.one("SELECT * FROM prime_retainage_collections WHERE id=?", (collection_id,))
        if row is None:
            raise ReceivableError(f"unknown collection {collection_id}")
        return self._receipt(row)

    def record_return(self, *, collection_id: str, period_id: str, reason: str, actor: str) -> dict[str, Any]:
        """A late return (after the original period closed) is posted in the
        current open period as a linked correction; the original receipt stays.  A
        return is never dated before its receipt, and a receipt whose journal was
        reversed no longer credits the receivable, so it cannot be returned."""
        actor = self._require_actor(actor)
        target = self.ledger.require_open(period_id)
        with self.db.transaction() as conn:
            col = self.db.one("SELECT * FROM collections WHERE id=?", (collection_id,))
            on_bill = col is not None
            if col is None:
                col = self.db.one("SELECT * FROM prime_retainage_collections WHERE id=?", (collection_id,))
            if col is None:
                raise ReceivableError(f"unknown collection {collection_id}")
            if col["status"] == "returned":
                raise ReceivableError("collection was already returned")
            if not col["journal_id"]:
                raise ReceivableError(f"collection {col['provider_ref']} has no posted journal; nothing to return")
            reversed_by = self._reversal_of(col["journal_id"])
            if reversed_by is not None:
                raise ReceivableError(f"collection {col['provider_ref']} was reversed by journal {reversed_by}; it no longer credits the receivable, so there is nothing to return")
            receipt_period = self.db.scalar("SELECT period_id FROM journals WHERE id=?", (col["journal_id"],))
            self._require_not_before(target, receipt_period, f"receipt {col['provider_ref']}")
            if on_bill:
                b = self.get(col["prime_bill_id"])
                project_id, customer_id = b["project_id"], b["customer_id"]
            else:
                inv = self.retainage_invoice(col["retainage_invoice_id"])
                project_id, customer_id = inv["project_id"], inv["customer_id"]
            amt = money(col["amount"])
            tags = {"project_id": project_id, "party_id": customer_id}
            j = self.ledger.post(
                period_id=period_id,
                description=f"Returned collection {col['provider_ref']}: {reason}",
                lines=[
                    {"account": "1100", "debit": amt, **tags, "memo": "receivable restored"},
                    {"account": "1000", "credit": amt, **tags, "memo": "bank return"},
                ],
                source_type="collection_return", source_id=col["provider_ref"], source_version="1", posted_by=actor,
            )
            table = "collections" if on_bill else "prime_retainage_collections"
            conn.execute(f"UPDATE {table} SET status='returned', return_journal_id=?, returned_at=? WHERE id=?", (j["id"], utcnow_iso(), collection_id))
            if on_bill:
                # a legacy-sent bill (no send record) is stored 'posted' and still reads 'sent'
                restored = "sent" if b["send"] is not None else "posted"
                conn.execute("UPDATE prime_bills SET status=? WHERE id=? AND status='collected'", (restored, col["prime_bill_id"]))
            else:
                conn.execute("UPDATE prime_retainage_invoices SET status='open' WHERE id=? AND status='collected'", (col["retainage_invoice_id"],))
            self.audit.record(actor, "collection.returned", "collection", collection_id, {
                "reason": reason, "journal_id": j["id"], "original_journal_id": col["journal_id"], "period_id": period_id,
            })
        return self.collection(collection_id)

    # ---- adjustments of a prime bill: shared helpers ----------------------------------- #

    def _annotate_adjustment(self, row: dict[str, Any]) -> dict[str, Any]:
        row["recorded_status"] = row["status"]
        reversal = self._reversal_of(row["journal_id"]) if row["status"] == "posted" else None
        row["reversal_journal_id"] = reversal
        row["standing"] = row["status"] == "posted" and reversal is None
        if reversal is not None:
            row["status"] = "reversed"
        return row

    def _adjustable_bill(self, prime_bill_id: str, what: str) -> dict[str, Any]:
        """A standing posted (or sent) prime bill with something open, for a new draft."""
        b = self.get(prime_bill_id)
        if b["recorded_status"] not in POSTED_BILL_STATES:
            raise ReceivableError(f"prime bill {prime_bill_id} is {b['status']}; a {what} applies to a posted prime bill")
        if b["reversed"]:
            raise ReceivableError(f"prime bill {b['sequence']} ({prime_bill_id}) was reversed by journal {b['reversal_journal_id']}; nothing is receivable on it")
        if money(b["open"]) <= 0:
            raise ReceivableError(f"prime bill {b['sequence']} ({prime_bill_id}) has nothing open")
        return b

    def _require_eligible(self, row: dict[str, Any], b: dict[str, Any], what: str) -> None:
        """Refuse (and, at execution, invalidate) a draft whose bill no longer takes it."""
        if row["recorded_status"] != "draft":
            raise ReceivableIneligible(f"{what} {row['id']} is {row['status']}; only a draft {what} can be approved or posted")
        if b["reversed"]:
            raise ReceivableIneligible(f"prime bill {b['sequence']} ({b['id']}) was reversed by journal {b['reversal_journal_id']}; nothing is receivable on it")
        if b["recorded_status"] not in POSTED_BILL_STATES or b["content_hash"] != row["bill_hash"]:
            raise ReceivableIneligible(f"prime bill {b['id']} no longer matches {what} {row['id']}")
        if money(row["amount"]) > money(b["open"]):
            raise ReceivableIneligible(f"{what} {row['id']} for {row['amount']} exceeds the {b['open']} now open on prime bill {b['sequence']}")

    def _earliest_period(self, *period_ids: str) -> dict[str, Any]:
        latest = max((self.ledger.period(p) for p in period_ids), key=lambda p: (p["start_date"], p["id"]))
        return {"id": latest["id"], "start_date": latest["start_date"]}

    @staticmethod
    def _bill_facts(b: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        """The bill amounts and bindings every adjustment approval binds: any receipt, credit,
        write-off or application on the bill in between makes the approval stale."""
        amounts = {"amount_due": b["amount_due"], "received": b["received"], "credited_by_memo": b["credited_by_memo"],
                   "written_off": b["written_off"], "deposits_applied": b["deposits_applied"], "open_receivable": b["open"]}
        bindings = {"prime_bill_id": b["id"], "project_id": b["project_id"], "customer_id": b["customer_id"], "sequence": b["sequence"],
                    "bill_hash": b["content_hash"], "bill_journal_id": b["journal_id"], "bill_period_id": b["period_id"],
                    "invoice_date": b["invoice_date"], "due_date": b["due_date"]}
        return amounts, bindings

    @staticmethod
    def _adjustment_lines(b: dict[str, Any], debit_account: str, amount: Decimal, debit_memo: str, credit_memo: str) -> list[dict[str, Any]]:
        tags = {"project_id": b["project_id"], "party_id": b["customer_id"]}
        return [{"account": debit_account, "debit": amount, **tags, "memo": debit_memo},
                {"account": AR_ACCOUNT, "credit": amount, **tags, "memo": credit_memo}]

    def _target_period(self, period_id: str | None, earliest: dict[str, Any], what: str) -> dict[str, Any]:
        pid = period_id or self._latest_open_period()
        target = self.ledger.require_open(pid)
        self._require_not_before(target, earliest["id"], what)
        return target

    def _mark_posted(self, table: str, row_id: str, *, approval_id: str, journal_id: str, period_id: str, actor: str, extra: dict[str, Any] | None = None) -> None:
        sets = {"status": "posted", "approval_id": approval_id, "journal_id": journal_id, "period_id": period_id, "posted_at": utcnow_iso(), "posted_by": actor,
                **(extra or {})}
        self.db.execute(f"UPDATE {table} SET {', '.join(f'{k}=?' for k in sets)} WHERE id=?", (*sets.values(), row_id))

    def _cancel_draft(self, table: str, subject_type: str, what: str, row_id: str, actor: Any, reason: Any) -> None:
        actor = self._require_actor(actor)
        why = self._reason(reason, "cancellation reason")
        with self.db.transaction() as conn:
            row = self.db.one(f"SELECT * FROM {table} WHERE id=?", (row_id,))
            if row is None:
                raise ReceivableError(f"unknown {what} {row_id}")
            if row["status"] != "draft":
                raise ReceivableError(f"{what} {row_id} is {row['status']}; only a draft {what} can be canceled")
            conn.execute(f"UPDATE {table} SET status='cancelled', cancelled_at=?, cancelled_by=?, cancel_reason=? WHERE id=?", (utcnow_iso(), actor, why, row_id))
            self.audit.record(actor, f"{subject_type}.cancelled", subject_type, row_id, {"reason": why, "prime_bill_id": row["prime_bill_id"]})
            Approvals(self.db, self.audit).invalidate_for_subject(subject_type, row_id, reason=f"{what} canceled: {why}", actor=actor)

    # ---- credit memos (prime_bill.credit_memo) ---------------------------------------- #

    def credit_memo(self, memo_id: str) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM prime_bill_credit_memos WHERE id=?", (memo_id,))
        if row is None:
            raise ReceivableError(f"unknown credit memo {memo_id}")
        return self._annotate_adjustment(row)

    def credit_memos(self, prime_bill_id: str | None = None) -> list[dict[str, Any]]:
        if prime_bill_id:
            return self._adjustment_rows("prime_bill_credit_memos", "prime_bill_id", prime_bill_id)
        return [self._annotate_adjustment(r) for r in self.db.query("SELECT * FROM prime_bill_credit_memos ORDER BY created_at, id")]

    def prepare_credit_memo(self, prime_bill_id: str, amount: str | Decimal, reason: str, evidence_hash: str, actor: str | None = None) -> dict[str, Any]:
        """Draft a credit memo on a standing posted or sent prime bill, for at most what is
        open on it.  ``evidence_hash`` is the content hash of an evidence revision filed on
        the bill's project (the agreed concession).  It posts only through the
        ``prime_bill.credit_memo`` approval; one draft per bill at a time."""
        actor = self._require_actor(actor)
        amt = self._positive(amount, "credit memo amount")
        why = self._reason(reason)
        h = self._text(evidence_hash, "evidence hash")
        with self.db.transaction() as conn:
            b = self._adjustable_bill(prime_bill_id, "credit memo")
            if amt > money(b["open"]):
                raise ReceivableError(f"credit memo {fmt(amt)} exceeds the {b['open']} open on prime bill {b['sequence']}")
            dup = self.db.one("SELECT id FROM prime_bill_credit_memos WHERE prime_bill_id=? AND status='draft'", (prime_bill_id,))
            if dup is not None:
                raise ReceivableDuplicate(f"prime bill {b['sequence']} already has draft credit memo {dup['id']}; approve or cancel it first")
            rev = self.db.one(
                "SELECT r.id FROM document_revisions r JOIN documents d ON d.id = r.document_id WHERE r.content_hash=? AND d.project_id=? "
                "ORDER BY r.created_at DESC, r.id DESC LIMIT 1", (h, b["project_id"]))
            if rev is None:
                if self.db.one("SELECT id FROM document_revisions WHERE content_hash=?", (h,)) is None:
                    raise ReceivableError(f"evidence hash {h} is not the content hash of any recorded evidence revision")
                raise ReceivableError(f"the evidence revision with hash {h} is not filed on project {b['project_id']} of prime bill {b['sequence']}")
            mid = new_id("pcm")
            conn.execute(
                """INSERT INTO prime_bill_credit_memos (id, prime_bill_id, project_id, customer_id, amount, reason, evidence_hash, evidence_revision_id, bill_hash,
                   status, created_at, created_by) VALUES (?,?,?,?,?,?,?,?,?,'draft',?,?)""",
                (mid, prime_bill_id, b["project_id"], b["customer_id"], fmt(amt), why, h, rev["id"], b["content_hash"], utcnow_iso(), actor),
            )
            self.audit.record(actor, "prime_bill_credit_memo.prepared", SUBJECT_CREDIT_MEMO, mid, {
                "prime_bill_id": prime_bill_id, "amount": fmt(amt), "reason": why, "evidence_hash": h, "evidence_revision_id": rev["id"], "open": b["open"],
            })
        return self.credit_memo(mid)

    def cancel_credit_memo(self, memo_id: str, actor: str | None = None, reason: str = "") -> dict[str, Any]:
        self._cancel_draft("prime_bill_credit_memos", SUBJECT_CREDIT_MEMO, "credit memo", memo_id, actor, reason)
        return self.credit_memo(memo_id)

    def _credit_memo_lines(self, b: dict[str, Any], amount: Decimal) -> list[dict[str, Any]]:
        return self._adjustment_lines(b, REVENUE_ACCOUNT, amount, f"credit memo on prime bill {b['sequence']} (fixture policy)", f"prime bill {b['sequence']} credited")

    def _credit_memo_manifest(self, memo_id: str, *, actor_role: str) -> dict[str, Any]:
        m = self.credit_memo(memo_id)
        b = self.get(m["prime_bill_id"])
        self._require_eligible(m, b, "credit memo")
        project = self._project(b["project_id"])
        amounts, bindings = self._bill_facts(b)
        earliest = self._earliest_period(b["period_id"])
        return build_manifest(
            operation=OP_CREDIT_MEMO, subject_type=SUBJECT_CREDIT_MEMO, subject_id=memo_id, actor_role=actor_role,
            entity=project["entity"], currency=project["currency"],
            amounts={"amount": m["amount"], **amounts},
            bindings={
                **bindings, "credit_memo_id": memo_id, "customer_name": self._customer(b["customer_id"])["name"], "reason": m["reason"],
                "evidence_hash": m["evidence_hash"], "evidence_revision_id": m["evidence_revision_id"], "recognition_policy": CREDIT_MEMO_POLICY,
                "posting_rule": RULE_VERSION, "journal_preview": self._preview(self._credit_memo_lines(b, money(m["amount"]))),
                "earliest_period": earliest, "target_rule": f"execute with period_id of an open period starting on or after {earliest['start_date']}",
            },
        )

    def _apply_credit_memo(self, memo_id: str, *, approval_id: str, manifest: dict[str, Any], actor: str, period_id: str | None) -> dict[str, Any]:
        with self.db.transaction():
            m = self.credit_memo(memo_id)
            b = self.get(m["prime_bill_id"])
            self._require_eligible(m, b, "credit memo")
            target = self._target_period(period_id, self._earliest_period(b["period_id"]), f"prime bill {b['sequence']}")
            amount = money(m["amount"])
            j = self.ledger.post(
                period_id=target["id"], description=f"Credit memo on prime bill {b['sequence']}: {m['reason']}", lines=self._credit_memo_lines(b, amount),
                source_type=JOURNAL_CREDIT_MEMO, source_id=memo_id, source_version="1", posted_by=actor, approval_id=approval_id,
            )
            posted_on = self._today().isoformat()
            self._mark_posted("prime_bill_credit_memos", memo_id, approval_id=approval_id, journal_id=j["id"], period_id=target["id"], actor=actor,
                              extra={"posted_on": posted_on})
            self.audit.record(actor, "prime_bill_credit_memo.posted", SUBJECT_CREDIT_MEMO, memo_id, {
                "prime_bill_id": b["id"], "amount": fmt(amount), "journal_id": j["id"], "approval_id": approval_id, "period_id": target["id"],
                "open_before": b["open"], "policy": CREDIT_MEMO_POLICY,
            })
        after = self.get(b["id"])
        return {"credit_memo": memo_id, "prime_bill": b["id"], "amount": fmt(amount), "journal_id": j["id"], "period_id": target["id"],
                "posted_on": posted_on, "open": after["open"], "status": "posted"}

    # ---- write-offs (receivable.write_off) -------------------------------------------- #

    def write_off(self, write_off_id: str) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM receivable_write_offs WHERE id=?", (write_off_id,))
        if row is None:
            raise ReceivableError(f"unknown write-off {write_off_id}")
        return self._annotate_adjustment(row)

    def write_offs(self, prime_bill_id: str | None = None) -> list[dict[str, Any]]:
        if prime_bill_id:
            return self._adjustment_rows("receivable_write_offs", "prime_bill_id", prime_bill_id)
        return [self._annotate_adjustment(r) for r in self.db.query("SELECT * FROM receivable_write_offs ORDER BY created_at, id")]

    def prepare_write_off(self, prime_bill_id: str, amount: str | Decimal, reason: str, actor: str | None = None) -> dict[str, Any]:
        """Draft a write-off of (part of) what is open on a standing posted prime bill that
        is at least 90 days past its due date today (the request date, recorded with the
        days past due).  It posts only through the controller's ``receivable.write_off``
        approval; one draft per bill at a time."""
        actor = self._require_actor(actor)
        amt = self._positive(amount, "write-off amount")
        why = self._reason(reason)
        requested_on = self._today()
        with self.db.transaction() as conn:
            b = self._adjustable_bill(prime_bill_id, "write-off")
            if not b["due_date"]:
                raise ReceivableIneligible(f"prime bill {b['sequence']} ({prime_bill_id}) has no due date (it posted before invoice dates were recorded); "
                                           "it cannot be aged for a write-off")
            days = (requested_on - _dt.date.fromisoformat(b["due_date"])).days
            if days < WRITE_OFF_MIN_DAYS_PAST_DUE:
                raise ReceivableIneligible(
                    f"prime bill {b['sequence']} is {max(days, 0)} days past due on {requested_on.isoformat()} (due {b['due_date']}); "
                    f"only a receivable at least {WRITE_OFF_MIN_DAYS_PAST_DUE} days past due can be written off")
            if amt > money(b["open"]):
                raise ReceivableError(f"write-off {fmt(amt)} exceeds the {b['open']} open on prime bill {b['sequence']}")
            dup = self.db.one("SELECT id FROM receivable_write_offs WHERE prime_bill_id=? AND status='draft'", (prime_bill_id,))
            if dup is not None:
                raise ReceivableDuplicate(f"prime bill {b['sequence']} already has draft write-off {dup['id']}; approve or cancel it first")
            wid = new_id("wof")
            conn.execute(
                """INSERT INTO receivable_write_offs (id, prime_bill_id, project_id, customer_id, amount, reason, requested_on, due_date, days_past_due, bill_hash,
                   status, created_at, created_by) VALUES (?,?,?,?,?,?,?,?,?,?,'draft',?,?)""",
                (wid, prime_bill_id, b["project_id"], b["customer_id"], fmt(amt), why, requested_on.isoformat(), b["due_date"], days, b["content_hash"],
                 utcnow_iso(), actor),
            )
            self.audit.record(actor, "receivable_write_off.prepared", SUBJECT_WRITE_OFF, wid, {
                "prime_bill_id": prime_bill_id, "amount": fmt(amt), "reason": why, "requested_on": requested_on.isoformat(), "due_date": b["due_date"],
                "days_past_due": days, "open": b["open"],
            })
        return self.write_off(wid)

    def cancel_write_off(self, write_off_id: str, actor: str | None = None, reason: str = "") -> dict[str, Any]:
        self._cancel_draft("receivable_write_offs", SUBJECT_WRITE_OFF, "write-off", write_off_id, actor, reason)
        return self.write_off(write_off_id)

    def _write_off_lines(self, b: dict[str, Any], amount: Decimal) -> list[dict[str, Any]]:
        return self._adjustment_lines(b, BAD_DEBT_ACCOUNT, amount, f"bad debt: prime bill {b['sequence']}", f"prime bill {b['sequence']} written off")

    def _write_off_eligible(self, w: dict[str, Any], b: dict[str, Any]) -> None:
        """A write-off draft is approved and posted only while it was requested no later than
        today, on the bill's own due date, and the days past due recomputed from that due date
        to the request date are the ones it records and at least 90.  A draft written outside
        prepare_write_off (raw SQL) with a future request date is refused here as well as by
        the database."""
        self._require_eligible(w, b, "write-off")
        today = self._today()
        try:
            requested = _dt.date.fromisoformat(self._date(w["requested_on"], "write-off request date"))
        except ReceivableInputError as exc:
            raise ReceivableIneligible(f"write-off {w['id']} records no valid request date: {exc}") from exc
        if requested > today:
            raise ReceivableIneligible(
                f"write-off {w['id']} was requested on {requested.isoformat()}, after today ({today.isoformat()}); "
                "days past due are counted to the day a write-off is requested, never to a future date")
        if not b["due_date"] or w["due_date"] != b["due_date"]:
            raise ReceivableIneligible(f"write-off {w['id']} records due date {w['due_date']}, not the due date {b['due_date']} of prime bill {b['sequence']}")
        days = (requested - _dt.date.fromisoformat(b["due_date"])).days
        if days != w["days_past_due"] or days < WRITE_OFF_MIN_DAYS_PAST_DUE:
            raise ReceivableIneligible(
                f"write-off {w['id']} no longer rests on a receivable at least {WRITE_OFF_MIN_DAYS_PAST_DUE} days past due: "
                f"prime bill {b['sequence']} was {max(days, 0)} days past due on {requested.isoformat()} (the draft records {w['days_past_due']})")

    def _write_off_manifest(self, write_off_id: str, *, actor_role: str) -> dict[str, Any]:
        w = self.write_off(write_off_id)
        b = self.get(w["prime_bill_id"])
        self._write_off_eligible(w, b)
        project = self._project(b["project_id"])
        amounts, bindings = self._bill_facts(b)
        earliest = self._earliest_period(b["period_id"])
        return build_manifest(
            operation=OP_WRITE_OFF, subject_type=SUBJECT_WRITE_OFF, subject_id=write_off_id, actor_role=actor_role,
            entity=project["entity"], currency=project["currency"],
            amounts={"amount": w["amount"], **amounts},
            bindings={
                **bindings, "write_off_id": write_off_id, "customer_name": self._customer(b["customer_id"])["name"], "reason": w["reason"],
                "requested_on": w["requested_on"], "days_past_due": w["days_past_due"], "minimum_days_past_due": WRITE_OFF_MIN_DAYS_PAST_DUE,
                # when the bill reached the books, next to how long it has been past due
                "bill_posted_on": (self.db.scalar("SELECT posted_at FROM journals WHERE id=?", (b["journal_id"],)) or "")[:10] or None,
                "policy": WRITE_OFF_POLICY, "posting_rule": RULE_VERSION, "journal_preview": self._preview(self._write_off_lines(b, money(w["amount"]))),
                "earliest_period": earliest, "target_rule": f"execute with period_id of an open period starting on or after {earliest['start_date']}",
            },
        )

    def _apply_write_off(self, write_off_id: str, *, approval_id: str, manifest: dict[str, Any], actor: str, period_id: str | None) -> dict[str, Any]:
        with self.db.transaction():
            w = self.write_off(write_off_id)
            b = self.get(w["prime_bill_id"])
            self._write_off_eligible(w, b)
            target = self._target_period(period_id, self._earliest_period(b["period_id"]), f"prime bill {b['sequence']}")
            amount = money(w["amount"])
            j = self.ledger.post(
                period_id=target["id"], description=f"Write-off of prime bill {b['sequence']} ({w['days_past_due']} days past due): {w['reason']}",
                lines=self._write_off_lines(b, amount), source_type=JOURNAL_WRITE_OFF, source_id=write_off_id, source_version="1", posted_by=actor,
                approval_id=approval_id,
            )
            self._mark_posted("receivable_write_offs", write_off_id, approval_id=approval_id, journal_id=j["id"], period_id=target["id"], actor=actor)
            self.audit.record(actor, "receivable_write_off.posted", SUBJECT_WRITE_OFF, write_off_id, {
                "prime_bill_id": b["id"], "amount": fmt(amount), "journal_id": j["id"], "approval_id": approval_id, "period_id": target["id"],
                "days_past_due": w["days_past_due"], "open_before": b["open"], "policy": WRITE_OFF_POLICY,
            })
        after = self.get(b["id"])
        return {"write_off": write_off_id, "prime_bill": b["id"], "amount": fmt(amount), "journal_id": j["id"], "period_id": target["id"],
                "days_past_due": w["days_past_due"], "open": after["open"], "status": "posted"}

    # ---- customer deposits and their application (receivable.apply_deposit) ----------- #

    def deposit(self, deposit_id: str) -> dict[str, Any]:
        """A customer deposit with its applications: ``unapplied`` is its amount while its
        journal stands, less its standing applications."""
        row = self.db.one("SELECT * FROM customer_deposits WHERE id=?", (deposit_id,))
        if row is None:
            raise ReceivableError(f"unknown deposit {deposit_id}")
        reversal = self._reversal_of(row["journal_id"])
        apps = self._adjustment_rows("deposit_applications", "deposit_id", deposit_id)
        amount = money(row["amount"])
        applied = total(a["amount"] for a in apps if a["standing"])
        reversed_amount = amount if reversal is not None else ZERO
        unapplied = money(amount - reversed_amount - applied)
        row["reversal_journal_id"] = reversal
        row["reversed"] = fmt(reversed_amount)
        row["applications"] = apps
        row["applied"] = fmt(applied)
        row["unapplied"] = fmt(unapplied)
        row["status"] = ("reversed" if reversal is not None else "applied" if unapplied == ZERO
                         else "partially_applied" if applied > 0 else "unapplied")
        return row

    def deposits(self, customer_id: str | None = None, project_id: str | None = None) -> list[dict[str, Any]]:
        sql, params = "SELECT id FROM customer_deposits", []
        clauses = []
        if customer_id:
            clauses.append("customer_id=?")
            params.append(customer_id)
        if project_id:
            clauses.append("project_id=?")
            params.append(project_id)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        return [self.deposit(r["id"]) for r in self.db.query(sql + " ORDER BY received_at, id", tuple(params))]

    def record_deposit(self, customer_id: str, project_id: str, amount: str | Decimal, provider_ref: str, method: str = "ach", actor: str | None = None, *,
                       period_id: str | None = None, settlement_date: str | _dt.date | None = None, mandate_ref: str | None = None) -> dict[str, Any]:
        """Record a customer advance on a project: ``Dr 1000 / Cr 2400``, held as an
        unapplied deposit until ``receivable.apply_deposit`` applies it to a prime bill.
        ``method`` is ``ach`` (needs the customer's active debit mandate, as for
        collections), ``check`` or ``wire``; the reference is unique across every receipt
        table, ignoring case.  It posts into ``period_id`` (default the latest open period);
        ``settlement_date`` defaults to today and is never in the future."""
        actor = self._require_actor(actor)
        self._customer(customer_id)
        project = self._project(project_id)
        if project["customer_id"] != customer_id:
            raise ReceivableError(f"project {project_id} belongs to customer {project['customer_id']}, not {customer_id}; a deposit is taken on the customer's own project")
        m = method.strip().lower() if isinstance(method, str) else ""
        if m not in COLLECTION_METHODS:
            raise ReceivableInputError(f"deposit method {method!r} is not one of {', '.join(COLLECTION_METHODS)}")
        if mandate_ref is not None and m != "ach":
            raise ReceivableInputError("a mandate reference applies to ACH deposits only")
        amt = self._positive(amount, "deposit amount")
        ref = self._text(provider_ref, "provider reference")
        settled_on = self._settlement_date(settlement_date, not_before=None, what="a deposit")
        pid = period_id or self._latest_open_period()
        self.ledger.require_open(pid)
        with self.db.transaction() as conn:
            taken = self._receipt_ref_taken(ref)
            if taken:
                raise ReceivableDuplicate(f"receipt {ref} was already recorded ({taken})")
            mandate = None
            if m == "ach":
                mandate = self.active_mandate(customer_id, mandate_ref)
                if mandate is None:
                    named = f" {mandate_ref} is not an active mandate of this customer" if mandate_ref is not None else " none is active"
                    raise ReceivableError(f"missing mandate: an ACH deposit from customer {customer_id} needs its active debit mandate;{named}. "
                                          "Record one with record_mandate, or take the deposit by check or wire")
            did = new_id("dep")
            tags = {"project_id": project_id, "party_id": customer_id}
            j = self.ledger.post(
                period_id=pid, description=f"Customer deposit {ref} on project {project_id}",
                lines=[{"account": BANK_ACCOUNT, "debit": amt, **tags, "memo": _BANK_MEMO[m]},
                       {"account": DEPOSITS_ACCOUNT, "credit": amt, **tags, "memo": "customer deposit (unapplied)"}],
                source_type=JOURNAL_DEPOSIT, source_id=did, source_version="1", posted_by=actor,
            )
            conn.execute(
                """INSERT INTO customer_deposits (id, customer_id, project_id, amount, method, mandate_id, provider_ref, settlement_date, period_id, journal_id,
                   received_at, recorded_by) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (did, customer_id, project_id, fmt(amt), m, mandate["id"] if mandate else None, ref, settled_on, pid, j["id"], utcnow_iso(), actor),
            )
            self.audit.record(actor, "deposit.recorded", "customer_deposit", did, {
                "customer_id": customer_id, "project_id": project_id, "amount": fmt(amt), "method": m, "mandate_ref": mandate["mandate_ref"] if mandate else None,
                "provider_ref": ref, "settlement_date": settled_on, "period_id": pid, "journal_id": j["id"],
            })
        return self.deposit(did)

    def deposit_application(self, application_id: str) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM deposit_applications WHERE id=?", (application_id,))
        if row is None:
            raise ReceivableError(f"unknown deposit application {application_id}")
        return self._annotate_adjustment(row)

    def prepare_deposit_application(self, deposit_id: str, prime_bill_id: str, amount: str | Decimal, actor: str | None = None) -> dict[str, Any]:
        """Draft the application of (part of) a deposit to a standing posted prime bill of
        the same customer and project, for at most both the deposit's unapplied balance and
        what is open on the bill.  It posts only through ``receivable.apply_deposit``; one
        draft per deposit and bill at a time."""
        actor = self._require_actor(actor)
        amt = self._positive(amount, "application amount")
        with self.db.transaction() as conn:
            d = self.deposit(deposit_id)
            if d["reversal_journal_id"] is not None:
                raise ReceivableError(f"deposit {d['provider_ref']} ({deposit_id}) was reversed by journal {d['reversal_journal_id']}; nothing is left to apply")
            b = self._adjustable_bill(prime_bill_id, "deposit application")
            if (b["customer_id"], b["project_id"]) != (d["customer_id"], d["project_id"]):
                raise ReceivableError(f"deposit {d['provider_ref']} was taken from customer {d['customer_id']} on project {d['project_id']}; "
                                      f"prime bill {b['sequence']} is for customer {b['customer_id']} on project {b['project_id']}")
            if amt > money(d["unapplied"]):
                raise ReceivableError(f"application {fmt(amt)} exceeds the {d['unapplied']} unapplied on deposit {d['provider_ref']}")
            if amt > money(b["open"]):
                raise ReceivableError(f"application {fmt(amt)} exceeds the {b['open']} open on prime bill {b['sequence']}")
            dup = self.db.one("SELECT id FROM deposit_applications WHERE deposit_id=? AND prime_bill_id=? AND status='draft'", (deposit_id, prime_bill_id))
            if dup is not None:
                raise ReceivableDuplicate(f"deposit {d['provider_ref']} already has draft application {dup['id']} to prime bill {b['sequence']}; approve or cancel it first")
            aid = new_id("dap")
            conn.execute(
                """INSERT INTO deposit_applications (id, deposit_id, prime_bill_id, project_id, customer_id, amount, bill_hash, status, created_at, created_by)
                   VALUES (?,?,?,?,?,?,?,'draft',?,?)""",
                (aid, deposit_id, prime_bill_id, b["project_id"], b["customer_id"], fmt(amt), b["content_hash"], utcnow_iso(), actor),
            )
            self.audit.record(actor, "deposit_application.prepared", SUBJECT_DEPOSIT_APPLICATION, aid, {
                "deposit_id": deposit_id, "prime_bill_id": prime_bill_id, "amount": fmt(amt), "deposit_unapplied": d["unapplied"], "open": b["open"],
            })
        return self.deposit_application(aid)

    def cancel_deposit_application(self, application_id: str, actor: str | None = None, reason: str = "") -> dict[str, Any]:
        self._cancel_draft("deposit_applications", SUBJECT_DEPOSIT_APPLICATION, "deposit application", application_id, actor, reason)
        return self.deposit_application(application_id)

    def _application_lines(self, b: dict[str, Any], d: dict[str, Any], amount: Decimal) -> list[dict[str, Any]]:
        return self._adjustment_lines(b, DEPOSITS_ACCOUNT, amount, f"deposit {d['provider_ref']} applied", f"prime bill {b['sequence']} settled from deposit")

    def _application_eligible(self, a: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        d = self.deposit(a["deposit_id"])
        b = self.get(a["prime_bill_id"])
        self._require_eligible(a, b, "deposit application")
        if d["reversal_journal_id"] is not None:
            raise ReceivableIneligible(f"deposit {d['provider_ref']} was reversed by journal {d['reversal_journal_id']}; nothing is left to apply")
        if money(a["amount"]) > money(d["unapplied"]):
            raise ReceivableIneligible(f"deposit application {a['id']} for {a['amount']} exceeds the {d['unapplied']} now unapplied on deposit {d['provider_ref']}")
        return d, b

    def _application_manifest(self, application_id: str, *, actor_role: str) -> dict[str, Any]:
        a = self.deposit_application(application_id)
        d, b = self._application_eligible(a)
        project = self._project(b["project_id"])
        amounts, bindings = self._bill_facts(b)
        earliest = self._earliest_period(b["period_id"], d["period_id"])
        return build_manifest(
            operation=OP_APPLY_DEPOSIT, subject_type=SUBJECT_DEPOSIT_APPLICATION, subject_id=application_id, actor_role=actor_role,
            entity=project["entity"], currency=project["currency"],
            amounts={"amount": a["amount"], "deposit_amount": d["amount"], "deposit_applied": d["applied"], "deposit_unapplied": d["unapplied"], **amounts},
            bindings={
                **bindings, "application_id": application_id, "customer_name": self._customer(b["customer_id"])["name"],
                "deposit_id": d["id"], "deposit_ref": d["provider_ref"], "deposit_journal_id": d["journal_id"], "deposit_period_id": d["period_id"],
                "deposit_settlement_date": d["settlement_date"], "policy": DEPOSIT_POLICY, "posting_rule": RULE_VERSION,
                "journal_preview": self._preview(self._application_lines(b, d, money(a["amount"]))),
                "earliest_period": earliest, "target_rule": f"execute with period_id of an open period starting on or after {earliest['start_date']}",
            },
        )

    def _apply_application(self, application_id: str, *, approval_id: str, manifest: dict[str, Any], actor: str, period_id: str | None) -> dict[str, Any]:
        with self.db.transaction():
            a = self.deposit_application(application_id)
            d, b = self._application_eligible(a)
            target = self._target_period(period_id, self._earliest_period(b["period_id"], d["period_id"]),
                                         f"prime bill {b['sequence']} and deposit {d['provider_ref']}")
            amount = money(a["amount"])
            j = self.ledger.post(
                period_id=target["id"], description=f"Deposit {d['provider_ref']} applied to prime bill {b['sequence']}",
                lines=self._application_lines(b, d, amount), source_type=JOURNAL_DEPOSIT_APPLICATION, source_id=application_id, source_version="1",
                posted_by=actor, approval_id=approval_id,
            )
            self._mark_posted("deposit_applications", application_id, approval_id=approval_id, journal_id=j["id"], period_id=target["id"], actor=actor)
            self.audit.record(actor, "deposit_application.posted", SUBJECT_DEPOSIT_APPLICATION, application_id, {
                "deposit_id": d["id"], "prime_bill_id": b["id"], "amount": fmt(amount), "journal_id": j["id"], "approval_id": approval_id,
                "period_id": target["id"], "deposit_unapplied_before": d["unapplied"], "open_before": b["open"],
            })
        return {"deposit_application": application_id, "deposit": d["id"], "prime_bill": b["id"], "amount": fmt(amount), "journal_id": j["id"],
                "period_id": target["id"], "deposit_unapplied": self.deposit(d["id"])["unapplied"], "open": self.get(b["id"])["open"], "status": "posted"}

    def deposits_items(self, project_id: str | None = None) -> dict[str, Any]:
        """Unapplied customer deposits behind control account 2400 (``customer_deposits``),
        in the shape of ``ar_open_items``: items, subledger_total, control_balance,
        reconciled, sources, errors.  A reversed deposit is credited by its amount."""
        errors: list[dict[str, Any]] = []
        items: list[dict[str, Any]] = []
        subledger = ZERO
        try:
            for d in self.deposits(project_id=project_id):
                items.append({
                    "source": SOURCE_CUSTOMER_DEPOSIT, "kind": "customer_deposit", "deposit_id": d["id"], "customer_id": d["customer_id"],
                    "project_id": d["project_id"], "provider_ref": d["provider_ref"], "method": d["method"], "settlement_date": d["settlement_date"],
                    "period_id": d["period_id"], "status": d["status"], "amount": d["amount"], "applied": d["applied"], "reversed": d["reversed"],
                    "reversal_journal_id": d["reversal_journal_id"], "open": d["unapplied"],
                })
                subledger += money(d["unapplied"])
        except Exception as exc:  # report, never reconcile silently
            errors.append({"source": SOURCE_CUSTOMER_DEPOSIT, "error": f"{type(exc).__name__}: {exc}"})
        try:
            control = self.ledger.control_balance(DEPOSITS_CONTROL, project_id=project_id) if project_id else self.ledger.control_balance(DEPOSITS_CONTROL)
        except Exception as exc:
            errors.append({"source": "control account 2400", "error": f"{type(exc).__name__}: {exc}"})
            control = None
        return {
            "items": items, "subledger_total": fmt(subledger), "control_balance": fmt(control) if control is not None else None,
            "reconciled": not errors and control is not None and money(subledger) == control,
            "sources": [{"source": SOURCE_CUSTOMER_DEPOSIT, "subledger_total": fmt(subledger)}], "errors": errors,
        }

    # ---- subledgers ------------------------------------------------------------------- #

    def _ar_sources(self) -> list[Any]:
        fn = getattr(self, "extra_ar_sources", None)
        if fn is None:
            return []
        out: list[Any] = []
        for src in list(fn() or []):
            if src is self or any(src is seen for seen in out):
                continue
            out.append(src)
        return out

    @staticmethod
    def _source_label(src: Any) -> str:
        return str(getattr(src, "PLUGIN_NAME", None) or type(src).__module__.rsplit(".", 1)[-1] or type(src).__name__)

    def ar_open_items(self, project_id: str | None = None, as_of: str | _dt.date | None = None) -> dict[str, Any]:
        """The complete AR subledger behind control account 1100: posted prime bills,
        retainage invoices and every extra source (plugins that debit 1100), each item
        tagged with its ``source``.  A bill or invoice whose journal was reversed is
        credited by its amount (what was received on it then shows as owed back).  A
        source that fails or does not add up is reported under ``errors`` and the
        subledger is then not reconciled.

        Core items carry plain values only (text, integers, money strings, None), with the
        column meanings the other 1100 sources use: ``reversed`` is the amount the
        reversal credited (``"0.00"`` while the journal stands) and ``reversal_journal_id``
        the reversing journal, as on labor T&M and reimbursement items.  They also carry
        ``invoice_date``, ``due_date`` and ``days_past_due`` (whole days past the due date
        as of ``as_of``, default today; 0 while not yet due or once nothing is open; None
        for a record posted before dates existed), and a prime bill its standing ``credited_by_memo``,
        ``written_off`` and ``deposits_applied``.  ``date`` stays the record's created
        date.  An extra source's items are kept as that source returned them; ``source``
        is set to the source's label, and an item's own different ``source`` value is
        kept as ``item_source``.  A reversed prime bill on which credit memos, write-offs or
        deposit applications still stand (only possible in a workspace written before the
        reversal guard) is reported under ``errors``, so the subledger is not reconciled."""
        as_of_day = self._today() if as_of is None else _dt.date.fromisoformat(self._date(as_of, "as_of"))
        items: list[dict[str, Any]] = []
        sql = "SELECT id FROM prime_bills WHERE status IN ('posted','sent','collected')"
        params: tuple = ()
        if project_id:
            sql += " AND project_id=?"
            params = (project_id,)
        prime_total = ZERO
        errors: list[dict[str, Any]] = []
        for row in self.db.query(sql + " ORDER BY project_id, sequence", params):
            b = self.get(row["id"])
            stranded = [a["id"] for kind in ("credit_memos", "write_offs", "deposit_applications") for a in b[kind] if a["standing"]] if b["reversed"] else []
            if stranded:
                # only a workspace written before receivables_dates_credits_guards can hold this:
                # the bill was reversed while adjustments on it stood, so 1100 carries a credit
                # nothing is owed against.  Reported, never reconciled silently.
                errors.append({"source": SOURCE_PRIME_BILL, "prime_bill_id": b["id"],
                               "error": (f"prime bill {b['sequence']} ({b['id']}) was reversed by journal {b['reversal_journal_id']} while "
                                         f"{', '.join(stranded)} still stand on it (open {b['open']}); reverse them")})
            items.append({
                "source": SOURCE_PRIME_BILL, "kind": "prime_bill", "prime_bill_id": b["id"], "project_id": b["project_id"], "customer_id": b["customer_id"],
                "sequence": b["sequence"], "period_id": b["period_id"], "date": b["created_at"][:10], "status": b["status"],
                "amount_due": b["amount_due"], "received": b["received"], "reversed": b["credited_by_reversal"],
                "reversal_journal_id": b["reversal_journal_id"], "credited_by_memo": b["credited_by_memo"], "written_off": b["written_off"],
                "deposits_applied": b["deposits_applied"], "invoice_date": b["invoice_date"], "due_date": b["due_date"],
                "days_past_due": self._days_past_due(b["due_date"], as_of_day, b["open"]), "open": b["open"],
            })
            prime_total += money(b["open"])
        retainage_total = ZERO
        for inv in self.retainage_invoices(project_id):
            items.append({
                "source": SOURCE_RETAINAGE_INVOICE, "kind": "retainage_invoice", "retainage_invoice_id": inv["id"], "project_id": inv["project_id"],
                "customer_id": inv["customer_id"], "sequence": inv["sequence"], "period_id": inv["period_id"], "date": inv["created_at"][:10],
                "status": inv["status"], "amount_due": inv["amount"], "received": inv["received"], "reversed": inv["credited_by_reversal"],
                "reversal_journal_id": inv["reversal_journal_id"], "invoice_date": inv["invoice_date"], "due_date": inv["due_date"],
                "days_past_due": self._days_past_due(inv["due_date"], as_of_day, inv["open"]), "open": inv["open"],
            })
            retainage_total += money(inv["open"])
        sources = [{"source": SOURCE_PRIME_BILL, "subledger_total": fmt(prime_total)}, {"source": SOURCE_RETAINAGE_INVOICE, "subledger_total": fmt(retainage_total)}]
        subledger = prime_total + retainage_total
        try:
            extra = self._ar_sources()
        except Exception as exc:  # the registry itself failed: say so, never reconcile silently
            extra = []
            errors.append({"source": "extra_ar_sources", "error": f"{type(exc).__name__}: {exc}"})
        for src in extra:
            label = self._source_label(src)
            try:
                r = src.ar_open_items(project_id)
                if isinstance(r.get("source"), str) and r["source"].strip():
                    label = r["source"].strip()
                src_total = self._money(r["subledger_total"], f"{label} subledger total")
                src_items = list(r["items"])
                if not all(isinstance(it, dict) for it in src_items):
                    raise ReceivableError("every item must be a mapping")
                # when the items carry their open amounts they must add up to the reported total
                if all("open" in it for it in src_items) and total(it["open"] for it in src_items) != src_total:
                    raise ReceivableError(f"items sum to {fmt(total(it['open'] for it in src_items))}, not the reported {fmt(src_total)}")
            except Exception as exc:
                errors.append({"source": label, "error": f"{type(exc).__name__}: {exc}"})
                continue
            for it in src_items:
                tagged = {**it, "source": label}
                own = it.get("source")
                if own not in (None, "", label):
                    tagged["item_source"] = own
                items.append(tagged)
            sources.append({"source": label, "subledger_total": fmt(src_total)})
            subledger += src_total
        control = self.ledger.control_balance("ar", project_id=project_id) if project_id else self.ledger.control_balance("ar")
        return {
            "items": items, "subledger_total": fmt(subledger), "control_balance": fmt(control),
            "reconciled": not errors and money(subledger) == control, "sources": sources, "errors": errors, "as_of": as_of_day.isoformat(),
        }

    def retainage_receivable_items(self, project_id: str | None = None) -> dict[str, Any]:
        """Retainage receivable behind control account 1150, per project: retainage
        withheld on the standing prime bills less retainage released by standing
        releases.  Same shape as ``ar_open_items`` (items, subledger_total,
        control_balance, reconciled, sources, errors)."""
        errors: list[dict[str, Any]] = []
        if project_id:
            projects = [project_id]
        else:
            rows = self.db.query(
                "SELECT project_id FROM prime_bills WHERE status IN ('posted','sent','collected') "
                "UNION SELECT project_id FROM prime_retainage_invoices ORDER BY project_id")
            projects = [r["project_id"] for r in rows]
        items = []
        subledger = ZERO
        for pid in projects:
            try:
                st = self._retainage_state(pid)
            except Exception as exc:  # report, never reconcile silently
                errors.append({"source": SOURCE_PRIME_RETAINAGE, "project_id": pid, "error": f"{type(exc).__name__}: {exc}"})
                continue
            items.append({
                "source": SOURCE_PRIME_RETAINAGE, "kind": "retainage_receivable", "project_id": pid, "customer_id": st["customer_id"],
                "through_sequence": st["through_sequence"], "retained": fmt(st["retained"]), "released": fmt(st["released"]), "open": fmt(st["open"]),
                "reversed_prime_bill_sequences": st["reversed_prime_bill_sequences"],
                "reversed_retainage_invoice_sequences": st["reversed_retainage_invoice_sequences"],
            })
            subledger += st["open"]
        control = self.ledger.control_balance("ar_retainage", project_id=project_id) if project_id else self.ledger.control_balance("ar_retainage")
        return {
            "items": items, "subledger_total": fmt(subledger), "control_balance": fmt(control),
            "reconciled": not errors and money(subledger) == control,
            "sources": [{"source": SOURCE_PRIME_RETAINAGE, "subledger_total": fmt(subledger)}], "errors": errors,
        }

    # ---- export ------------------------------------------------------------------------ #

    def audit_export(self) -> dict[str, Any]:
        """The receivables control records an independent reviewer needs (contracts,
        recipients, payment terms, mandates and any not backed by their evidence, sends and
        the legacy sends found at upgrade, retainage invoices and their collections, credit
        memos, write-offs, customer deposits and their applications, receipt reference
        clashes) with the AR (1100), retainage receivable (1150) and customer deposit (2400)
        reconciliations."""
        q = self.db.query
        return {
            "prime_contracts": q("SELECT * FROM prime_contracts ORDER BY project_id, version"),
            "billing_recipients": q("SELECT * FROM customer_billing_recipients ORDER BY customer_id, version"),
            "payment_terms": q("SELECT * FROM customer_payment_terms ORDER BY customer_id, version"),
            "mandates": q("SELECT * FROM customer_mandates ORDER BY recorded_at, id"),
            "unbacked_mandates": self.unbacked_mandates(),
            "prime_bill_sends": q("SELECT * FROM prime_bill_sends ORDER BY sent_at, id"),
            "prime_bill_legacy_sends": q("SELECT * FROM prime_bill_legacy_sends ORDER BY prime_bill_id"),
            "retainage_invoices": q("SELECT * FROM prime_retainage_invoices ORDER BY project_id, sequence"),
            "retainage_collections": q("SELECT * FROM prime_retainage_collections ORDER BY received_at, id"),
            "credit_memos": self.credit_memos(),
            "write_offs": self.write_offs(),
            "customer_deposits": q("SELECT * FROM customer_deposits ORDER BY received_at, id"),
            "deposit_applications": [self._annotate_adjustment(r) for r in q("SELECT * FROM deposit_applications ORDER BY created_at, id")],
            "policies": {"credit_memo": CREDIT_MEMO_POLICY, "write_off": WRITE_OFF_POLICY, "deposit": DEPOSIT_POLICY, "recognition": RECOGNITION_POLICY},
            "receipt_reference_conflicts": self.receipt_reference_conflicts(),
            "ar_reconciliation": self.ar_open_items(),
            "retainage_reconciliation": self.retainage_receivable_items(),
            "deposits_reconciliation": self.deposits_items(),
        }

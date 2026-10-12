"""Prime contracts, progress billing, sending, collections, prime retainage and the AR subledger.

The fixture policy recognises revenue when the owner certifies progress and
bills it; the plan is explicit that billing is *not* universally the revenue
trigger, so every statement produced here is labelled SHADOW.

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

Posting rules (fixture policy ``cipher-posting-rules/1``):

* prime bill:          Dr 1100 amount due, Dr 1150 retainage withheld (Cr 1150 for a
                       retainage reduction) / Cr 4000 certified progress
* retainage release:   Dr 1100 / Cr 1150 (the project's whole retainage receivable)
* collection:          Dr 1000 net, Dr 6000 fee / Cr 1100 gross
* late return:         Dr 1100 / Cr 1000 in the current open period (the receipt stays)
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Callable

from ..core.approvals import Approvals, StaleApprovalError, build_manifest
from ..core.audit import Audit
from ..core.db import Database, register_schema_version
from ..core.ids import canonical_json, hash_json, loads, new_id, utcnow_iso
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
# Constants and errors                                                         #
# --------------------------------------------------------------------------- #

OP_SEND = "prime_bill.send"
OP_RELEASE_RETAINAGE = "prime_retainage.release"
OWNED_OPERATIONS = (OP_SEND, OP_RELEASE_RETAINAGE)

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
# of them, ignoring case.  The database enforces it across the two core tables
# (_REF_CLASH); the plugin tables (labor T&M, reimbursement billings) may be absent from a
# workspace, so across them it is checked here in Python (labor checks the core tables the
# same way) and any clash a plugin let through is reported by receipt_reference_conflicts().
_CORE_RECEIPT_TABLES = ("collections", "prime_retainage_collections")
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

    # ---- input helpers ------------------------------------------------------ #

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
        authorises a debit."""
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

    def certify(self, *, project_id: str, period_id: str, certified_cumulative: str | Decimal, retainage_rate: str | Decimal | None = None, actor: str) -> dict[str, Any]:
        """Create a draft prime bill from the cumulative certified value.

        The increment is computed against what the standing (posted, unreversed)
        prime bills already put on the books.  With a prime contract the certified
        cumulative may not exceed the contract value and the contract's retainage
        rate applies (an explicit different rate is refused); without one the rate
        defaults to 10%."""
        actor = self._require_actor(actor)
        project = self._project(project_id)
        if not project["customer_id"]:
            raise ReceivableError("project has no customer party")
        certified = self._money(certified_cumulative, "certified cumulative")
        if certified < 0:
            raise ReceivableInputError("certified cumulative cannot be negative")
        self.ledger.require_open(period_id)
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
            content_hash = hash_json({
                "project_id": project_id, "period_id": period_id, "sequence": sequence, "certified": fmt(certified), "rate": f"{r:f}",
                "retainage_cumulative": fmt(ret_cum), "amount_due": fmt(amount_due), "contract_version": contract_version,
            })
            pid = new_id("pbl")
            conn.execute(
                """INSERT INTO prime_bills (id, project_id, customer_id, period_id, sequence, status, certified_cumulative, retainage_rate, retainage_cumulative,
                   prior_net, amount_due, revenue_this_period, content_hash, created_at, contract_version)
                   VALUES (?,?,?,?,?,'draft',?,?,?,?,?,?,?,?,?)""",
                (pid, project_id, project["customer_id"], period_id, sequence, fmt(certified), f"{r:f}", fmt(ret_cum), fmt(prior_net), fmt(amount_due),
                 fmt(revenue), content_hash, utcnow_iso(), contract_version),
            )
            self.audit.record(actor, "prime_bill.certified", "prime_bill", pid, {
                "project_id": project_id, "sequence": sequence, "certified": fmt(certified), "amount_due": fmt(amount_due),
                "retainage_this_period": fmt(retainage_this), "contract_version": contract_version, "content_hash": content_hash,
                "prior_billed_certified": fmt(prior_certified), "prior_net": fmt(prior_net),
            })
        return self.get(pid)

    def _bill_balance(self, b: dict[str, Any]) -> dict[str, Decimal]:
        """Billed, received and reversed amounts of a prime bill, and what stays open in
        1100.  A reversed bill's journal cleared its whole receivable, so the bill is
        credited by its amount due; what was received on it is then owed back."""
        billed = money(b["amount_due"]) if b["recorded_status"] in POSTED_BILL_STATES else ZERO
        received = total(c["credited"] for c in b["collections"])
        credited = billed if b["reversed"] else ZERO
        return {"billed": billed, "received": received, "reversed": credited, "open": money(billed - received - credited)}

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
        bal = self._bill_balance(row)
        row["received"] = fmt(bal["received"])
        row["credited_by_reversal"] = fmt(bal["reversed"])
        row["open"] = fmt(bal["open"])
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
        """Manifest for ``prime_bill.approve``: amounts, the bill hash, the contract version
        and value, the billed chain it continues, entity, currency and the exact journal
        lines the posting will make."""
        b = self.get(prime_bill_id)
        if b["status"] != "draft":
            raise ReceivableIneligible(f"prime bill {prime_bill_id} is {b['status']}; only a draft prime bill can be approved for posting")
        contract = self._check_billable(b)
        project = self._project(b["project_id"])
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
            },
        )

    def post(self, prime_bill_id: str, *, approval_id: str, actor: str) -> dict[str, Any]:
        """Post an approved draft.  The caller has consumed ``approval_id``."""
        with self.db.transaction() as conn:
            b = self.get(prime_bill_id)
            if b["status"] != "draft":
                raise ReceivableError(f"prime bill {prime_bill_id} is {b['status']}")
            self._check_billable(b)
            j = self.ledger.post(
                period_id=b["period_id"], description=f"Prime bill {b['sequence']}", lines=self._bill_lines(b),
                source_type="prime_bill", source_id=prime_bill_id, source_version="1", posted_by=actor, approval_id=approval_id,
            )
            conn.execute("UPDATE prime_bills SET status='posted', approval_id=?, journal_id=? WHERE id=?", (approval_id, j["id"], prime_bill_id))
            self.audit.record(actor, "prime_bill.posted", "prime_bill", prime_bill_id, {"approval_id": approval_id, "journal_id": j["id"], "contract_version": b["contract_version"]})
        return self.get(prime_bill_id)

    # ---- core-domain operations: handles / manifest_for / apply --------------------- #

    def handles(self, operation: str) -> bool:
        return operation in OWNED_OPERATIONS

    def manifest_for(self, operation: str, subject_id: str, *, actor_role: str) -> dict[str, Any]:
        if operation == OP_SEND:
            return self._send_manifest(subject_id, actor_role=actor_role)
        if operation == OP_RELEASE_RETAINAGE:
            return self._retainage_manifest(subject_id, actor_role=actor_role)
        raise ReceivableError(f"receivables does not own operation {operation}")

    def apply(self, operation: str, subject_id: str, *, approval_id: str, manifest: dict[str, Any], actor: str, period_id: str | None) -> dict[str, Any]:
        if operation == OP_SEND:
            return self._apply_send(subject_id, approval_id=approval_id, manifest=manifest, actor=actor)
        if operation == OP_RELEASE_RETAINAGE:
            return self._apply_release(subject_id, approval_id=approval_id, manifest=manifest, actor=actor, period_id=period_id)
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

    def _send_manifest(self, prime_bill_id: str, *, actor_role: str) -> dict[str, Any]:
        b = self.get(prime_bill_id)
        self._sendable(b)
        project = self._project(b["project_id"])
        customer = self._customer(b["customer_id"])
        rec = self.billing_recipients(b["customer_id"])
        message_hash = hash_json({
            "prime_bill_id": prime_bill_id, "bill_hash": b["content_hash"], "sequence": b["sequence"], "amount_due": b["amount_due"],
            "customer_id": b["customer_id"], "channel": SEND_CHANNEL, "recipients": rec["recipients"],
        })
        return build_manifest(
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
            },
        )

    def _apply_send(self, prime_bill_id: str, *, approval_id: str, manifest: dict[str, Any], actor: str) -> dict[str, Any]:
        """Deliver to the synthetic mail sink; nothing leaves the prototype."""
        bindings = manifest["bindings"]
        with self.db.transaction() as conn:
            b = self.get(prime_bill_id)
            self._sendable(b)
            if bindings["bill_hash"] != b["content_hash"] or bindings["channel"] != SEND_CHANNEL:
                raise ReceivableIneligible(f"prime bill {prime_bill_id} no longer matches the approved send")
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
            seq = st["next_invoice_sequence"]
            inv_id = new_id("rti")
            j = self.ledger.post(
                period_id=pid, description=f"Prime retainage release (retainage invoice {seq}) on project {project_id}",
                lines=self._release_lines(project_id, st["customer_id"], amount, seq),
                source_type="prime_retainage_release", source_id=inv_id, source_version=str(contract_version or 0), posted_by=actor, approval_id=approval_id,
            )
            content_hash = hash_json({
                "project_id": project_id, "sequence": seq, "amount": fmt(amount), "contract_version": contract_version,
                "through_prime_bill_sequence": st["through_sequence"], "period_id": pid,
            })
            conn.execute(
                """INSERT INTO prime_retainage_invoices (id, project_id, customer_id, period_id, sequence, amount, status, contract_version,
                   through_prime_bill_sequence, content_hash, approval_id, journal_id, created_at, created_by)
                   VALUES (?,?,?,?,?,?,'open',?,?,?,?,?,?,?)""",
                (inv_id, project_id, st["customer_id"], pid, seq, fmt(amount), contract_version, st["through_sequence"], content_hash, approval_id, j["id"], utcnow_iso(), actor),
            )
            self.audit.record(actor, "prime_retainage.released", "prime_retainage_invoice", inv_id, {
                "project_id": project_id, "amount": fmt(amount), "journal_id": j["id"], "approval_id": approval_id, "period_id": pid,
                "contract_version": contract_version, "through_prime_bill_sequence": st["through_sequence"], "sequence": seq,
            })
        return {"retainage_invoice": inv_id, "project_id": project_id, "sequence": seq, "amount": fmt(amount), "journal_id": j["id"], "period_id": pid, "status": "open"}

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
    ) -> dict[str, Any]:
        """Record a customer receipt against a prime bill or a retainage invoice.

        ``method`` is ``ach`` (needs the customer's active debit mandate: the named
        ``mandate_ref`` or the latest active one), ``check`` or ``wire``.  The provider
        reference is unique across every receipt table, ignoring case.  A reversed bill
        or invoice has nothing receivable, and a receipt is never dated in a period
        that starts before the period of the bill or invoice it collects."""
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
        target_period = self.ledger.require_open(period_id)
        with self.db.transaction() as conn:
            taken = self._receipt_ref_taken(ref)
            if taken:
                raise ReceivableError(f"collection {ref} was already recorded ({taken})")
            if prime_bill_id is not None:
                b = self.get(prime_bill_id)
                if b["recorded_status"] not in POSTED_BILL_STATES:
                    raise ReceivableError(f"prime bill {prime_bill_id} is {b['status']}")
                if b["reversed"]:
                    raise ReceivableError(f"prime bill {b['sequence']} ({prime_bill_id}) was reversed by journal {b['reversal_journal_id']}; nothing is receivable on it")
                open_amt = money(b["open"])
                recorded_status, source_period = b["recorded_status"], b["period_id"]
                target = {"project_id": b["project_id"], "customer_id": b["customer_id"], "label": f"prime bill {b['sequence']}"}
            else:
                inv = self.retainage_invoice(retainage_invoice_id)
                if inv["reversed"]:
                    raise ReceivableError(f"retainage invoice {inv['sequence']} ({retainage_invoice_id}) was reversed by journal {inv['reversal_journal_id']}; nothing is receivable on it")
                open_amt = money(inv["open"])
                recorded_status, source_period = inv["recorded_status"], inv["period_id"]
                target = {"project_id": inv["project_id"], "customer_id": inv["customer_id"], "label": f"retainage invoice {inv['sequence']}"}
            if open_amt <= 0:
                raise ReceivableError(f"{target['label']} is {recorded_status} with nothing open to collect")
            if amt > open_amt:
                raise ReceivableError(f"collection {fmt(amt)} exceeds open receivable {fmt(open_amt)}")
            self._require_not_before(target_period, source_period, target["label"])
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
                    "INSERT INTO collections (id, prime_bill_id, amount, fee, status, journal_id, provider_ref, received_at, method, mandate_id) VALUES (?,?,?,?,'received',?,?,?,?,?)",
                    (cid, prime_bill_id, fmt(amt), fmt(f), j["id"], ref, now, m, mandate_id),
                )
                if amt == open_amt and recorded_status != "collected":
                    conn.execute("UPDATE prime_bills SET status='collected' WHERE id=?", (prime_bill_id,))
            else:
                cid = new_id("rcl")
                conn.execute(
                    """INSERT INTO prime_retainage_collections (id, retainage_invoice_id, amount, fee, method, mandate_id, status, journal_id, provider_ref, received_at, recorded_by)
                       VALUES (?,?,?,?,?,?,'received',?,?,?,?)""",
                    (cid, retainage_invoice_id, fmt(amt), fmt(f), m, mandate_id, j["id"], ref, now, actor),
                )
                if amt == open_amt and recorded_status != "collected":
                    conn.execute("UPDATE prime_retainage_invoices SET status='collected' WHERE id=?", (retainage_invoice_id,))
            self.audit.record(actor, "collection.recorded", "collection", cid, {
                "prime_bill_id": prime_bill_id, "retainage_invoice_id": retainage_invoice_id, "amount": fmt(amt), "fee": fmt(f), "journal_id": j["id"],
                "method": m, "mandate_ref": mandate["mandate_ref"] if mandate else None, "provider_ref": ref, "period_id": period_id,
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

    def ar_open_items(self, project_id: str | None = None) -> dict[str, Any]:
        """The complete AR subledger behind control account 1100: posted prime bills,
        retainage invoices and every extra source (plugins that debit 1100), each item
        tagged with its ``source``.  A bill or invoice whose journal was reversed is
        credited by its amount (what was received on it then shows as owed back).  A
        source that fails or does not add up is reported under ``errors`` and the
        subledger is then not reconciled.

        Core items carry plain values only (text, integers, money strings, None), with the
        column meanings the other 1100 sources use: ``reversed`` is the amount the
        reversal credited (``"0.00"`` while the journal stands) and ``reversal_journal_id``
        the reversing journal, as on labor T&M and reimbursement items.  An extra source's
        items are kept as that source returned them; ``source`` is set to the source's
        label, and an item's own different ``source`` value is kept as ``item_source``."""
        items: list[dict[str, Any]] = []
        sql = "SELECT id FROM prime_bills WHERE status IN ('posted','sent','collected')"
        params: tuple = ()
        if project_id:
            sql += " AND project_id=?"
            params = (project_id,)
        prime_total = ZERO
        for row in self.db.query(sql + " ORDER BY project_id, sequence", params):
            b = self.get(row["id"])
            items.append({
                "source": SOURCE_PRIME_BILL, "kind": "prime_bill", "prime_bill_id": b["id"], "project_id": b["project_id"], "customer_id": b["customer_id"],
                "sequence": b["sequence"], "period_id": b["period_id"], "date": b["created_at"][:10], "status": b["status"],
                "amount_due": b["amount_due"], "received": b["received"], "reversed": b["credited_by_reversal"],
                "reversal_journal_id": b["reversal_journal_id"], "open": b["open"],
            })
            prime_total += money(b["open"])
        retainage_total = ZERO
        for inv in self.retainage_invoices(project_id):
            items.append({
                "source": SOURCE_RETAINAGE_INVOICE, "kind": "retainage_invoice", "retainage_invoice_id": inv["id"], "project_id": inv["project_id"],
                "customer_id": inv["customer_id"], "sequence": inv["sequence"], "period_id": inv["period_id"], "date": inv["created_at"][:10],
                "status": inv["status"], "amount_due": inv["amount"], "received": inv["received"], "reversed": inv["credited_by_reversal"],
                "reversal_journal_id": inv["reversal_journal_id"], "open": inv["open"],
            })
            retainage_total += money(inv["open"])
        sources = [{"source": SOURCE_PRIME_BILL, "subledger_total": fmt(prime_total)}, {"source": SOURCE_RETAINAGE_INVOICE, "subledger_total": fmt(retainage_total)}]
        errors: list[dict[str, Any]] = []
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
            "reconciled": not errors and money(subledger) == control, "sources": sources, "errors": errors,
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
        recipients, mandates and any not backed by their evidence, sends and the legacy
        sends found at upgrade, retainage invoices and their collections, receipt
        reference clashes) with both subledger reconciliations."""
        q = self.db.query
        return {
            "prime_contracts": q("SELECT * FROM prime_contracts ORDER BY project_id, version"),
            "billing_recipients": q("SELECT * FROM customer_billing_recipients ORDER BY customer_id, version"),
            "mandates": q("SELECT * FROM customer_mandates ORDER BY recorded_at, id"),
            "unbacked_mandates": self.unbacked_mandates(),
            "prime_bill_sends": q("SELECT * FROM prime_bill_sends ORDER BY sent_at, id"),
            "prime_bill_legacy_sends": q("SELECT * FROM prime_bill_legacy_sends ORDER BY prime_bill_id"),
            "retainage_invoices": q("SELECT * FROM prime_retainage_invoices ORDER BY project_id, sequence"),
            "retainage_collections": q("SELECT * FROM prime_retainage_collections ORDER BY received_at, id"),
            "receipt_reference_conflicts": self.receipt_reference_conflicts(),
            "ar_reconciliation": self.ar_open_items(),
            "retainage_reconciliation": self.retainage_receivable_items(),
        }

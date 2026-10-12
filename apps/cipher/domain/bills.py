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
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from ..core.approvals import build_manifest
from ..core.audit import Audit
from ..core.db import Database, register_schema_version
from ..core.ids import canonical_json, hash_json, loads, new_id, utcnow_iso
from ..core.money import ZERO, fmt, money, pct, total
from .commitments import Commitments
from .ledger import Ledger

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


class BillError(RuntimeError):
    pass


def _line(account: str, *, debit: Decimal = ZERO, credit: Decimal = ZERO, project_id: str, party_id: str, memo: str) -> dict[str, Any]:
    return {"account": account, "debit": fmt(debit), "credit": fmt(credit), "project_id": project_id, "party_id": party_id, "memo": memo}


class Bills:
    def __init__(self, db: Database, audit: Audit, commitments: Commitments, ledger: Ledger):
        self.db = db
        self.audit = audit
        self.commitments = commitments
        self.ledger = ledger

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
        row = self.db.one("SELECT * FROM bills WHERE commitment_id=? AND status != 'void' ORDER BY sequence DESC LIMIT 1", (commitment_id,))
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

    def manifest(self, bill_id: str, *, actor_role: str) -> dict[str, Any]:
        b = self.get(bill_id)
        supplier = self.db.one("SELECT * FROM parties WHERE id=?", (b["supplier_id"],))
        c = self.db.one("SELECT retainage_rate FROM commitments WHERE id=?", (b["commitment_id"],))
        return build_manifest(
            operation="bill.approve",
            subject_type="bill",
            subject_id=bill_id,
            actor_role=actor_role,
            amounts={"amount_due": b["amount_due"], "retainage_this_period": b["retainage_this_period"], "cumulative_gross": b["cumulative_gross"]},
            bindings={
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
            },
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
            approved = self._approved_manifest(approval_id, "bill.approve", bill_id)
            self._refuse_spent_approval(approval_id)
            if canonical_json((approved.get("bindings") or {}).get("journal_preview")) != canonical_json(plan):
                raise BillError("the approved journal preview does not match the posting this bill would write; nothing was posted")
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
                items.append({"bill_id": None, "commitment_id": c["id"], "project_id": pid, "supplier_id": supplier_id, "sequence": None,
                              "amount_due": fmt(released), "paid": fmt(alloc), "open": fmt(released - alloc), "kind": "retainage_release"})
            if not releases and unallocated != 0:
                items.append({"bill_id": None, "commitment_id": None, "project_id": pid, "supplier_id": supplier_id, "sequence": None,
                              "amount_due": "0.00", "paid": fmt(unallocated), "open": fmt(-unallocated), "kind": "retainage_release"})
        return items

    def ap_open_items(self, project_id: str | None = None) -> dict[str, Any]:
        """Open AP derived from posted bills less settled payments, reconciled to the AP control account."""
        sql = "SELECT b.*, c.project_id AS pid, c.supplier_id AS sid FROM bills b JOIN commitments c ON c.id=b.commitment_id WHERE b.status IN ('posted','paid')"
        params: tuple = ()
        if project_id:
            sql += " AND c.project_id=?"
            params = (project_id,)
        items = []
        open_total = ZERO
        for b in self.db.query(sql, params):
            paid = self.db.query("SELECT amount FROM payment_intents WHERE bill_id=? AND status IN ('accepted','settled')", (b["id"],))
            paid_total = total(p["amount"] for p in paid) if paid else ZERO
            open_amt = money(b["amount_due"]) - paid_total
            items.append({"bill_id": b["id"], "supplier_id": b["sid"], "sequence": b["sequence"], "amount_due": b["amount_due"], "paid": fmt(paid_total), "open": fmt(open_amt)})
            open_total += open_amt
        release_total = ZERO
        for item in self._retainage_release_items(project_id):
            release_total += money(item["open"])
            items.append(item)
        control = self.ledger.control_balance("ap", project_id=project_id) if project_id else self.ledger.control_balance("ap")
        subledger = money(open_total + release_total)
        return {"items": items, "subledger_total": fmt(subledger), "control_balance": fmt(control), "reconciled": subledger == control}

"""EPC procurement: equipment register, requisitions, bid tabs, award, long-lead tracking, receiving.

Flow::

    add_equipment ──> create_requisition (draft) ──> add_quote / revise_quote / withdraw_quote
        ──> bid_tab ──> select_quote ──(procurement.award, approval-bound)──> awarded
            └─> DRAFT commitment (core commitments)  ──(commitment.execute, separate approval)──> executed PO
    set_milestone_plan / record_actual ──> long_lead_report
    receive (awarded equipment only) ──> delivery actual

Two authorities.  ``procurement.award`` records the award decision and drafts
the purchase order as a core commitment (one SOV line per equipment item, the
quote amount split equally with ``money.allocate`` so the lines sum exactly,
retainage 0.00).  It never executes the commitment: contract execution stays
the core ``commitment.execute`` approval, so awarding and signing are separate
human decisions.  Nothing in this module posts a journal - a commitment alone
does not create a payable (plan section 6, invariant 6).  The award is
nevertheless recorded against an open accounting period (``ledger.require_open``)
so a closed or locked period cannot receive new commercial events.  As for the
core operations, that period is the executor's choice at execution time and is
not bound in the approval manifest (a granted award may be executed into the
next open period after a close).

Rules:

* equipment tags are unique per project, case-insensitively (Unicode casefold;
  the ASCII ``lower()`` unique index is a backstop); an equipment item may sit
  on only one non-canceled requisition (``procurement_equipment.requisition_id``);
* one *live* quote per supplier per requisition (a withdrawn quote frees the
  supplier to quote again).  Quote amounts are positive whole cents (sub-cent,
  NaN/Infinity and floats are rejected, not rounded) and at least 0.01 per
  equipment item, so every drafted PO line is positive;
* *eligible* means compliant and not expired (``valid_until`` on or after today
  in UTC).  The bid tab's ``spread`` is max - min of all compliant quotes (the
  spec); its ``lowest_compliant`` flag is computed over eligible quotes, because
  an expired offer cannot be selected (``eligible_spread`` reports that set);
* a selection must be eligible; anything other than the lowest eligible quote
  needs a non-empty justification.  After any change to the bid set (quote
  added, revised or withdrawn) the selection is re-validated: it is cleared when
  its quote changed or it no longer satisfies the rule;
* every change to a requisition or its bid set bumps the requisition version
  (a trigger rejects an update that does not) and invalidates open award
  approvals.  The award manifest binds the requisition version, the selected
  quote id and version, amount, supplier, supplier destination version,
  justification, the bid tab hash and the SOV hash, so a granted approval can
  never execute against a different state;
* milestone plans follow submittal -> approval -> fabrication -> factory_test ->
  ship -> delivery with non-decreasing planned dates.  Actuals are recorded once,
  may not lie in the future and must respect the same order.  The delivery
  actual is written by ``receive`` or by ``record_actual(..., "delivery", ...)``
  (arrival reported before the receiving inspection), whichever comes first;
  either needs an awarded requisition and a date on or after the award, and a
  later receipt keeps the recorded delivery actual and may not predate it;
* forecast delivery = the delivery actual if received, else the planned
  delivery shifted by the slip (actual minus plan) of the furthest-along
  milestone that has both a plan and an actual.  ``float_days`` = required on
  site minus forecast delivery; ``late`` when float is negative.

Database guards back the rules: requisition status only moves draft->awarded or
draft->canceled; quotes are frozen once their requisition leaves draft; an
award row needs a consumed ``procurement.award`` approval for that requisition
and an open period, and is immutable; receipts need an awarded requisition and
are immutable; nothing here is ever deleted except un-actualised milestone plan
rows dropped by a re-plan (the audit log keeps every plan).
"""
from __future__ import annotations

import datetime as _dt
import unicodedata
from decimal import Decimal
from typing import Any

from ..core.approvals import StaleApprovalError, build_manifest
from ..core.ids import canonical_json, hash_json, loads, new_id, utcnow, utcnow_iso
from ..core.money import CENTS, D, MoneyError, allocate, fmt, money

SCHEMA_NAME = "procurement"
PLUGIN_NAME = "procurement"
OP_AWARD = "procurement.award"

EQUIPMENT_SUBJECT = "procurement_equipment"
REQUISITION_SUBJECT = "procurement_requisition"
QUOTE_SUBJECT = "procurement_quote"
AWARD_SUBJECT = "procurement_award"
RECEIPT_SUBJECT = "procurement_receipt"

MILESTONES = ("submittal", "approval", "fabrication", "factory_test", "ship", "delivery")
CONDITIONS = ("ok", "damaged")
AWARD_RETAINAGE = "0.00"
MAX_LEAD_WEEKS = 520

SCHEMA_STATEMENTS = [
    """CREATE TABLE procurement_equipment (
        id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES projects(id),
        tag TEXT NOT NULL,
        description TEXT NOT NULL,
        spec_section TEXT NOT NULL,
        required_on_site TEXT NOT NULL,
        long_lead INTEGER NOT NULL DEFAULT 0 CHECK (long_lead IN (0, 1)),
        requisition_id TEXT REFERENCES procurement_requisitions(id),
        version INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )""",
    "CREATE UNIQUE INDEX procurement_equipment_tag_ci ON procurement_equipment (project_id, lower(tag))",
    "CREATE TRIGGER procurement_equipment_no_delete BEFORE DELETE ON procurement_equipment BEGIN SELECT RAISE(ABORT, 'equipment is never deleted from the register'); END",
    """CREATE TRIGGER procurement_equipment_identity_immutable BEFORE UPDATE OF id, project_id, tag ON procurement_equipment
        BEGIN SELECT RAISE(ABORT, 'equipment identity (project, tag) is immutable'); END""",
    """CREATE TRIGGER procurement_equipment_version_bumps BEFORE UPDATE ON procurement_equipment
        WHEN NEW.version <= OLD.version
        BEGIN SELECT RAISE(ABORT, 'every equipment change must bump the equipment version'); END""",
    """CREATE TABLE procurement_requisitions (
        id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES projects(id),
        title TEXT NOT NULL,
        equipment_json TEXT NOT NULL,
        status TEXT NOT NULL CHECK (status IN ('draft','awarded','cancelled')),
        version INTEGER NOT NULL DEFAULT 1,
        selected_quote_id TEXT REFERENCES procurement_quotes(id),
        selected_quote_version INTEGER,
        justification TEXT NOT NULL DEFAULT '',
        selected_by TEXT,
        selected_at TEXT,
        award_id TEXT REFERENCES procurement_awards(id),
        cancel_reason TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        awarded_at TEXT,
        cancelled_at TEXT
    )""",
    "CREATE TRIGGER procurement_requisitions_no_delete BEFORE DELETE ON procurement_requisitions BEGIN SELECT RAISE(ABORT, 'requisitions are never deleted'); END",
    """CREATE TRIGGER procurement_requisitions_identity_immutable BEFORE UPDATE OF id, project_id, equipment_json ON procurement_requisitions
        BEGIN SELECT RAISE(ABORT, 'a requisition''s project and equipment list are immutable; cancel and requisition again'); END""",
    """CREATE TRIGGER procurement_requisitions_version_bumps BEFORE UPDATE ON procurement_requisitions
        WHEN NEW.version <= OLD.version
        BEGIN SELECT RAISE(ABORT, 'every requisition change must bump the requisition version'); END""",
    """CREATE TRIGGER procurement_requisitions_status_machine BEFORE UPDATE OF status ON procurement_requisitions
        WHEN NEW.status != OLD.status AND NOT (
            (OLD.status = 'draft' AND NEW.status = 'awarded' AND NEW.award_id IS NOT NULL AND NEW.awarded_at IS NOT NULL)
            OR (OLD.status = 'draft' AND NEW.status = 'cancelled' AND NEW.cancelled_at IS NOT NULL)
        )
        BEGIN SELECT RAISE(ABORT, 'illegal requisition status transition'); END""",
    """CREATE TRIGGER procurement_requisitions_final_frozen BEFORE UPDATE ON procurement_requisitions
        WHEN OLD.status IN ('awarded','cancelled')
        BEGIN SELECT RAISE(ABORT, 'awarded or cancelled requisitions are immutable'); END""",
    """CREATE TABLE procurement_quotes (
        id TEXT PRIMARY KEY,
        requisition_id TEXT NOT NULL REFERENCES procurement_requisitions(id),
        supplier_id TEXT NOT NULL REFERENCES parties(id),
        amount TEXT NOT NULL,
        lead_time_weeks INTEGER NOT NULL CHECK (lead_time_weeks > 0),
        valid_until TEXT NOT NULL,
        compliant INTEGER NOT NULL CHECK (compliant IN (0, 1)),
        exceptions TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL CHECK (status IN ('live','withdrawn')),
        version INTEGER NOT NULL DEFAULT 1,
        content_hash TEXT NOT NULL,
        withdraw_reason TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        withdrawn_at TEXT
    )""",
    "CREATE UNIQUE INDEX procurement_quotes_one_live_per_supplier ON procurement_quotes (requisition_id, supplier_id) WHERE status = 'live'",
    "CREATE TRIGGER procurement_quotes_no_delete BEFORE DELETE ON procurement_quotes BEGIN SELECT RAISE(ABORT, 'quotes are bid history and are never deleted'); END",
    """CREATE TRIGGER procurement_quotes_open_requisition_only BEFORE INSERT ON procurement_quotes
        WHEN (SELECT status FROM procurement_requisitions WHERE id = NEW.requisition_id) IS NOT 'draft'
        BEGIN SELECT RAISE(ABORT, 'quotes are added to draft requisitions only'); END""",
    """CREATE TRIGGER procurement_quotes_frozen_after_draft BEFORE UPDATE ON procurement_quotes
        WHEN (SELECT status FROM procurement_requisitions WHERE id = OLD.requisition_id) IS NOT 'draft' OR OLD.status = 'withdrawn'
        BEGIN SELECT RAISE(ABORT, 'quotes are frozen once withdrawn or once their requisition is awarded or cancelled'); END""",
    """CREATE TRIGGER procurement_quotes_identity_immutable BEFORE UPDATE OF id, requisition_id, supplier_id ON procurement_quotes
        BEGIN SELECT RAISE(ABORT, 'a quote''s requisition and supplier are immutable'); END""",
    """CREATE TRIGGER procurement_quotes_version_bumps BEFORE UPDATE ON procurement_quotes
        WHEN NEW.version <= OLD.version
        BEGIN SELECT RAISE(ABORT, 'every quote change must bump the quote version'); END""",
    """CREATE TABLE procurement_awards (
        id TEXT PRIMARY KEY,
        requisition_id TEXT NOT NULL UNIQUE REFERENCES procurement_requisitions(id),
        quote_id TEXT NOT NULL REFERENCES procurement_quotes(id),
        quote_version INTEGER NOT NULL,
        supplier_id TEXT NOT NULL REFERENCES parties(id),
        amount TEXT NOT NULL,
        justification TEXT NOT NULL DEFAULT '',
        lowest_compliant INTEGER NOT NULL CHECK (lowest_compliant IN (0, 1)),
        bid_tab_hash TEXT NOT NULL,
        sov_hash TEXT NOT NULL,
        commitment_id TEXT NOT NULL REFERENCES commitments(id),
        approval_id TEXT NOT NULL REFERENCES approvals(id),
        period_id TEXT NOT NULL REFERENCES periods(id),
        awarded_by TEXT NOT NULL,
        created_at TEXT NOT NULL
    )""",
    """CREATE TRIGGER procurement_awards_authorised BEFORE INSERT ON procurement_awards
        BEGIN
            SELECT CASE
                WHEN (SELECT status FROM periods WHERE id = NEW.period_id) IS NOT 'open'
                THEN RAISE(ABORT, 'awards are recorded into an open period only')
                WHEN (SELECT status FROM approvals WHERE id = NEW.approval_id AND operation = 'procurement.award'
                      AND subject_type = 'procurement_requisition' AND subject_id = NEW.requisition_id) IS NOT 'consumed'
                THEN RAISE(ABORT, 'an award needs a consumed procurement.award approval for that requisition')
                WHEN (SELECT status FROM commitments WHERE id = NEW.commitment_id) IS NOT 'draft'
                THEN RAISE(ABORT, 'an award drafts its commitment; execution is a separate approval')
            END;
        END""",
    "CREATE TRIGGER procurement_awards_no_update BEFORE UPDATE ON procurement_awards BEGIN SELECT RAISE(ABORT, 'awards are immutable'); END",
    "CREATE TRIGGER procurement_awards_no_delete BEFORE DELETE ON procurement_awards BEGIN SELECT RAISE(ABORT, 'awards are immutable'); END",
    """CREATE TABLE procurement_milestones (
        id TEXT PRIMARY KEY,
        equipment_id TEXT NOT NULL REFERENCES procurement_equipment(id),
        name TEXT NOT NULL CHECK (name IN ('submittal','approval','fabrication','factory_test','ship','delivery')),
        seq INTEGER NOT NULL,
        planned TEXT,
        actual TEXT,
        actual_source TEXT CHECK (actual_source IS NULL OR actual_source IN ('record','receipt')),
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE (equipment_id, name)
    )""",
    """CREATE TRIGGER procurement_milestones_actual_once BEFORE UPDATE OF actual ON procurement_milestones
        WHEN OLD.actual IS NOT NULL AND NEW.actual IS NOT OLD.actual
        BEGIN SELECT RAISE(ABORT, 'a recorded milestone actual is never overwritten'); END""",
    """CREATE TRIGGER procurement_milestones_keep_actuals BEFORE DELETE ON procurement_milestones
        WHEN OLD.actual IS NOT NULL
        BEGIN SELECT RAISE(ABORT, 'a milestone with a recorded actual is never deleted'); END""",
    """CREATE TABLE procurement_receipts (
        id TEXT PRIMARY KEY,
        equipment_id TEXT NOT NULL UNIQUE REFERENCES procurement_equipment(id),
        requisition_id TEXT NOT NULL REFERENCES procurement_requisitions(id),
        award_id TEXT NOT NULL REFERENCES procurement_awards(id),
        received_date TEXT NOT NULL,
        condition TEXT NOT NULL CHECK (condition IN ('ok','damaged')),
        evidence_hash TEXT NOT NULL CHECK (length(trim(evidence_hash)) > 0),
        note TEXT NOT NULL DEFAULT '',
        received_by TEXT NOT NULL,
        created_at TEXT NOT NULL
    )""",
    """CREATE TRIGGER procurement_receipts_awarded_only BEFORE INSERT ON procurement_receipts
        BEGIN
            SELECT CASE
                WHEN (SELECT status FROM procurement_requisitions WHERE id = NEW.requisition_id) IS NOT 'awarded'
                THEN RAISE(ABORT, 'equipment is received only against an awarded requisition')
                WHEN (SELECT requisition_id FROM procurement_equipment WHERE id = NEW.equipment_id) IS NOT NEW.requisition_id
                THEN RAISE(ABORT, 'a receipt binds the requisition the equipment is on')
            END;
        END""",
    "CREATE TRIGGER procurement_receipts_no_update BEFORE UPDATE ON procurement_receipts BEGIN SELECT RAISE(ABORT, 'receipts are immutable'); END",
    "CREATE TRIGGER procurement_receipts_no_delete BEFORE DELETE ON procurement_receipts BEGIN SELECT RAISE(ABORT, 'receipts are immutable'); END",
]


class ProcurementError(RuntimeError):
    """Invalid procurement input or an action the record's state does not allow."""


class AwardNotExecutable(ProcurementError, StaleApprovalError):
    """An award approval reached execution for a requisition whose state no
    longer allows the award.  It is a ``StaleApprovalError`` for the core, so the
    service rolls the command back and invalidates the approval durably."""


# --------------------------------------------------------------------------- #
# Validation helpers                                                           #
# --------------------------------------------------------------------------- #

def _text(value: Any, label: str, *, required: bool = True) -> str:
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise ProcurementError(f"{label} must be a string, not {type(value).__name__}")
    text = value.strip()
    if required and not text:
        raise ProcurementError(f"{label} is required")
    return text


def _date(value: Any, label: str) -> _dt.date:
    if not isinstance(value, str) or len(value) != 10 or value[4] != "-" or value[7] != "-":
        raise ProcurementError(f"{label} must be YYYY-MM-DD, got {value!r}")
    try:
        return _dt.date.fromisoformat(value)
    except ValueError as exc:
        raise ProcurementError(f"{label} is not a valid calendar date: {value!r}") from exc


def _bool(value: Any, label: str) -> bool:
    if not isinstance(value, bool):
        raise ProcurementError(f"{label} must be True or False, got {value!r}")
    return value


def _positive_amount(value: Any, label: str = "amount") -> Decimal:
    """A positive amount in whole cents.  Floats, NaN/Infinity, out-of-range
    values and sub-cent input are rejected rather than rounded."""
    try:
        raw = D(value)
    except MoneyError as exc:
        raise ProcurementError(f"{label} is not exact money: {exc}") from exc
    if not raw.is_finite():
        raise ProcurementError(f"{label} must be a finite amount, got {value!r}")
    try:
        amt = money(raw)
    except ArithmeticError as exc:  # decimal.InvalidOperation: too many digits for the context
        raise ProcurementError(f"{label} is out of range: {value!r}") from exc
    if amt != raw:
        raise ProcurementError(f"{label} must be in whole cents, got {value!r}")
    if amt <= 0:
        raise ProcurementError(f"{label} must be positive, got {fmt(amt)}")
    return amt


def _tag_key(tag: str) -> str:
    """Case-insensitive identity of an equipment tag (Unicode-aware, unlike SQLite lower())."""
    return unicodedata.normalize("NFKC", tag).casefold()


def _lead_weeks(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ProcurementError(f"lead_time_weeks must be a whole number of weeks, got {value!r}")
    if value <= 0 or value > MAX_LEAD_WEEKS:
        raise ProcurementError(f"lead_time_weeks must be between 1 and {MAX_LEAD_WEEKS}, got {value}")
    return value


def _quote_content_hash(row: dict[str, Any]) -> str:
    return hash_json({
        "requisition_id": row["requisition_id"],
        "supplier_id": row["supplier_id"],
        "amount": fmt(row["amount"]),
        "lead_time_weeks": int(row["lead_time_weeks"]),
        "valid_until": row["valid_until"],
        "compliant": bool(row["compliant"]),
        "exceptions": row["exceptions"],
    })


def _today() -> _dt.date:
    return utcnow().date()


# --------------------------------------------------------------------------- #
# Plugin                                                                       #
# --------------------------------------------------------------------------- #

class Plugin:
    def __init__(self, cipher):
        self.c = cipher
        self.db = cipher.db
        self.audit = cipher.audit
        self.ledger = cipher.ledger
        self.approvals = cipher.approvals

    # ---- low-level helpers --------------------------------------------------- #

    def _project(self, project_id: Any) -> dict[str, Any]:
        if not isinstance(project_id, str) or not project_id:
            raise ProcurementError("project_id is required")
        row = self.db.one("SELECT * FROM projects WHERE id=?", (project_id,))
        if row is None:
            raise ProcurementError(f"unknown project {project_id}")
        return row

    def _equipment_row(self, equipment_id: Any) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM procurement_equipment WHERE id=?", (equipment_id,)) if isinstance(equipment_id, str) else None
        if row is None:
            raise ProcurementError(f"unknown equipment {equipment_id}")
        return row

    def _requisition_row(self, requisition_id: Any) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM procurement_requisitions WHERE id=?", (requisition_id,)) if isinstance(requisition_id, str) else None
        if row is None:
            raise ProcurementError(f"unknown requisition {requisition_id}")
        return row

    def _quote_row(self, quote_id: Any) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM procurement_quotes WHERE id=?", (quote_id,)) if isinstance(quote_id, str) else None
        if row is None:
            raise ProcurementError(f"unknown quote {quote_id}")
        return row

    def _bump(self, conn, table: str, row: dict[str, Any], **fields: Any) -> int:
        """Compare-and-set ``row`` to the next version (plus ``fields``); a
        concurrent change is a failure, never a silent overwrite."""
        version = row["version"] + 1
        assignments = "".join(f"{k}=?, " for k in fields)
        cur = conn.execute(
            f"UPDATE {table} SET {assignments}version=?, updated_at=? WHERE id=? AND version=?",
            (*fields.values(), version, utcnow_iso(), row["id"], row["version"]),
        )
        if cur.rowcount != 1:
            raise ProcurementError(f"{table} row {row['id']} changed concurrently; retry")
        return version

    @staticmethod
    def _equipment_ids(req: dict[str, Any]) -> list[str]:
        return list(loads(req["equipment_json"]))

    def _require_draft(self, req: dict[str, Any]) -> None:
        if req["status"] != "draft":
            raise ProcurementError(f"requisition {req['id']} is {req['status']}; only draft requisitions change")

    def _require_cent_per_item(self, amount: Decimal, req: dict[str, Any], label: str = "quote amount") -> None:
        """The drafted PO gets one SOV line per equipment item, so a quote must
        carry at least one cent per item or a line would be 0.00."""
        items = len(self._equipment_ids(req))
        if amount < CENTS * items:
            raise ProcurementError(
                f"{label} {fmt(amount)} is less than 0.01 per equipment item ({items} item(s)); every PO line must carry a positive amount"
            )

    def _invalidate_awards(self, requisition_id: str, *, reason: str, actor: str) -> int:
        return self.approvals.invalidate_for_subject(REQUISITION_SUBJECT, requisition_id, reason=reason, actor=actor)

    @staticmethod
    def _consuming(db) -> bool:
        """True while the core re-derives a manifest to consume an approval
        (``service.execute`` runs ``_manifest`` inside the command transaction);
        proposals (``request_approval``, Ricky) build it outside any transaction.
        A proposal for an award that cannot execute is refused; during
        consumption the manifest reflects current state instead, so the core's
        material comparison invalidates an approval whose subject moved on."""
        return db.in_transaction

    # ---- equipment register -------------------------------------------------- #

    def add_equipment(self, project_id: str, tag: str, description: str, spec_section: str, required_on_site: str, long_lead: bool = False, actor: str = "owner") -> dict[str, Any]:
        """Register an equipment item.  ``tag`` is unique per project (case-insensitive)."""
        tag = _text(tag, "equipment tag")
        description = _text(description, "equipment description")
        spec_section = _text(spec_section, "spec_section")
        _date(required_on_site, "required_on_site")
        long_lead = _bool(long_lead, "long_lead")
        actor = _text(actor, "actor")
        equipment_id = new_id("peq")
        now = utcnow_iso()
        with self.db.transaction() as conn:
            self._project(project_id)
            # Python casefold catches non-ASCII case variants the ASCII-only
            # SQLite lower() in the unique index (the backstop) would miss.
            key = _tag_key(tag)
            for row in conn.execute("SELECT tag FROM procurement_equipment WHERE project_id=?", (project_id,)).fetchall():
                if _tag_key(row["tag"]) == key:
                    raise ProcurementError(f"equipment tag {row['tag']!r} is already registered on project {project_id}")
            conn.execute(
                """INSERT INTO procurement_equipment (id, project_id, tag, description, spec_section, required_on_site, long_lead, version, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,1,?,?)""",
                (equipment_id, project_id, tag, description, spec_section, required_on_site, 1 if long_lead else 0, now, now),
            )
            self.audit.record(actor, "procurement.equipment_added", EQUIPMENT_SUBJECT, equipment_id, {
                "project_id": project_id, "tag": tag, "description": description, "spec_section": spec_section,
                "required_on_site": required_on_site, "long_lead": long_lead, "version": 1,
            })
        return self.equipment(equipment_id)

    def equipment(self, equipment_id: str) -> dict[str, Any]:
        """One equipment item with milestones, forecast, receipt and award status."""
        return self._describe_equipment(self._equipment_row(equipment_id))

    def equipment_list(self, project_id: str) -> list[dict[str, Any]]:
        self._project(project_id)
        rows = self.db.query("SELECT * FROM procurement_equipment WHERE project_id=? ORDER BY tag, created_at", (project_id,))
        return [self._describe_equipment(r) for r in rows]

    # ---- requisitions ---------------------------------------------------------- #

    def create_requisition(self, project_id: str, title: str, equipment_ids: list[str], actor: str = "owner") -> dict[str, Any]:
        """Draft requisition (version 1) for equipment of one project.  Each item
        may be on only one non-canceled requisition."""
        title = _text(title, "requisition title")
        actor = _text(actor, "actor")
        if not isinstance(equipment_ids, (list, tuple)) or not equipment_ids:
            raise ProcurementError("a requisition needs at least one equipment id")
        ids = [_text(e, "equipment id") for e in equipment_ids]
        if len(set(ids)) != len(ids):
            raise ProcurementError("an equipment item may appear only once on a requisition")
        req_id = new_id("preq")
        now = utcnow_iso()
        with self.db.transaction() as conn:
            self._project(project_id)
            rows = []
            for eid in ids:
                eq = self._equipment_row(eid)
                if eq["project_id"] != project_id:
                    raise ProcurementError(f"equipment {eq['tag']} belongs to another project")
                if eq["requisition_id"] is not None:
                    raise ProcurementError(f"equipment {eq['tag']} is already on open requisition {eq['requisition_id']}")
                rows.append(eq)
            conn.execute(
                """INSERT INTO procurement_requisitions (id, project_id, title, equipment_json, status, version, created_at, updated_at)
                   VALUES (?,?,?,?,'draft',1,?,?)""",
                (req_id, project_id, title, canonical_json(ids), now, now),
            )
            for eq in rows:
                self._bump(conn, "procurement_equipment", eq, requisition_id=req_id)
            self.audit.record(actor, "procurement.requisition_created", REQUISITION_SUBJECT, req_id, {
                "project_id": project_id, "title": title, "equipment_ids": ids, "tags": [e["tag"] for e in rows], "version": 1,
            })
        return self.requisition(req_id)

    def cancel_requisition(self, requisition_id: str, reason: str, actor: str = "owner") -> dict[str, Any]:
        """Cancel a draft requisition and release its equipment for requisitioning again."""
        reason = _text(reason, "cancellation reason")
        actor = _text(actor, "actor")
        with self.db.transaction() as conn:
            req = self._requisition_row(requisition_id)
            self._require_draft(req)
            now = utcnow_iso()
            version = self._bump(conn, "procurement_requisitions", req, status="cancelled", cancel_reason=reason, cancelled_at=now)  # stored column names
            released = []
            for eid in self._equipment_ids(req):
                eq = self._equipment_row(eid)
                if eq["requisition_id"] == requisition_id:
                    self._bump(conn, "procurement_equipment", eq, requisition_id=None)
                    released.append(eid)
            invalidated = self._invalidate_awards(requisition_id, reason=f"requisition canceled: {reason}", actor=actor)
            self.audit.record(actor, "procurement.requisition_cancelled", REQUISITION_SUBJECT, requisition_id, {
                "reason": reason, "version": version, "equipment_released": released, "approvals_invalidated": invalidated,
            })
        return self.requisition(requisition_id)

    def requisition(self, requisition_id: str) -> dict[str, Any]:
        """A requisition with its equipment, quotes, bid tab, selection and award."""
        return self._describe_requisition(self._requisition_row(requisition_id))

    def requisitions(self, project_id: str) -> list[dict[str, Any]]:
        self._project(project_id)
        rows = self.db.query("SELECT * FROM procurement_requisitions WHERE project_id=? ORDER BY created_at, id", (project_id,))
        return [self._describe_requisition(r) for r in rows]

    # ---- quotes ---------------------------------------------------------------- #

    def add_quote(self, requisition_id: str, supplier_id: str, amount, lead_time_weeks: int, valid_until: str, compliant: bool, exceptions: str = "", actor: str = "owner") -> dict[str, Any]:
        """Record a supplier quote on a draft requisition.  One live quote per supplier."""
        amt = _positive_amount(amount, "quote amount")
        weeks = _lead_weeks(lead_time_weeks)
        _date(valid_until, "valid_until")
        compliant = _bool(compliant, "compliant")
        exceptions = _text(exceptions, "exceptions", required=False)
        actor = _text(actor, "actor")
        quote_id = new_id("pqt")
        now = utcnow_iso()
        with self.db.transaction() as conn:
            req = self._requisition_row(requisition_id)
            self._require_draft(req)
            self._require_cent_per_item(amt, req)
            supplier = self.db.one("SELECT id, kind, name FROM parties WHERE id=?", (supplier_id,)) if isinstance(supplier_id, str) else None
            if supplier is None:
                raise ProcurementError(f"unknown party {supplier_id}")
            if supplier["kind"] != "supplier":
                raise ProcurementError(f"quotes come from supplier parties; {supplier_id} is a {supplier['kind']}")
            live = conn.execute("SELECT id FROM procurement_quotes WHERE requisition_id=? AND supplier_id=? AND status='live'", (requisition_id, supplier_id)).fetchone()
            if live is not None:
                raise ProcurementError(f"supplier {supplier['name']} already has live quote {live['id']} on requisition {requisition_id}; revise or withdraw it")
            content = {"requisition_id": requisition_id, "supplier_id": supplier_id, "amount": fmt(amt), "lead_time_weeks": weeks,
                       "valid_until": valid_until, "compliant": compliant, "exceptions": exceptions}
            content_hash = _quote_content_hash(content)
            conn.execute(
                """INSERT INTO procurement_quotes (id, requisition_id, supplier_id, amount, lead_time_weeks, valid_until, compliant, exceptions, status, version, content_hash, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,'live',1,?,?,?)""",
                (quote_id, requisition_id, supplier_id, fmt(amt), weeks, valid_until, 1 if compliant else 0, exceptions, content_hash, now, now),
            )
            req_version = self._bump(conn, "procurement_requisitions", req)
            cleared = self._revalidate_selection(conn, requisition_id, changed_quote_id=None, actor=actor)
            invalidated = self._invalidate_awards(requisition_id, reason=f"quote {quote_id} added to the bid set", actor=actor)
            self.audit.record(actor, "procurement.quote_added", QUOTE_SUBJECT, quote_id, {
                **content, "content_hash": content_hash, "version": 1, "requisition_version": req_version,
                "selection_cleared": cleared, "approvals_invalidated": invalidated,
            })
        return self.quote(quote_id)

    def revise_quote(self, quote_id: str, actor: str = "owner", *, amount=None, lead_time_weeks: int | None = None, compliant: bool | None = None,
                     exceptions: str | None = None, valid_until: str | None = None) -> dict[str, Any]:
        """Revise a live quote.  Bumps the quote version and the requisition
        version, clears a selection of this quote and invalidates open award approvals."""
        actor = _text(actor, "actor")
        if amount is None and lead_time_weeks is None and compliant is None and exceptions is None and valid_until is None:
            raise ProcurementError("nothing to revise")
        with self.db.transaction() as conn:
            q = self._quote_row(quote_id)
            if q["status"] != "live":
                raise ProcurementError(f"quote {quote_id} is {q['status']}; only live quotes are revised")
            req = self._requisition_row(q["requisition_id"])
            self._require_draft(req)
            changes: dict[str, Any] = {}
            if amount is not None:
                amt = _positive_amount(amount, "quote amount")
                self._require_cent_per_item(amt, req)
                a = fmt(amt)
                if a != q["amount"]:
                    changes["amount"] = a
            if lead_time_weeks is not None:
                w = _lead_weeks(lead_time_weeks)
                if w != q["lead_time_weeks"]:
                    changes["lead_time_weeks"] = w
            if compliant is not None:
                cpl = 1 if _bool(compliant, "compliant") else 0
                if cpl != q["compliant"]:
                    changes["compliant"] = cpl
            if exceptions is not None:
                ex = _text(exceptions, "exceptions", required=False)
                if ex != q["exceptions"]:
                    changes["exceptions"] = ex
            if valid_until is not None:
                _date(valid_until, "valid_until")
                if valid_until != q["valid_until"]:
                    changes["valid_until"] = valid_until
            if not changes:
                raise ProcurementError(f"revision of quote {quote_id} changes nothing")
            content_hash = _quote_content_hash({**q, **changes})
            version = self._bump(conn, "procurement_quotes", q, **changes, content_hash=content_hash)
            req_version = self._bump(conn, "procurement_requisitions", req)
            cleared = self._revalidate_selection(conn, req["id"], changed_quote_id=quote_id, actor=actor)
            invalidated = self._invalidate_awards(req["id"], reason=f"quote {quote_id} revised to version {version}", actor=actor)
            self.audit.record(actor, "procurement.quote_revised", QUOTE_SUBJECT, quote_id, {
                "requisition_id": req["id"], "changes": {k: (bool(v) if k == "compliant" else v) for k, v in changes.items()},
                "version": version, "content_hash": content_hash, "requisition_version": req_version,
                "selection_cleared": cleared, "approvals_invalidated": invalidated,
            })
        return self.quote(quote_id)

    def withdraw_quote(self, quote_id: str, reason: str, actor: str = "owner") -> dict[str, Any]:
        """Withdraw a live quote (kept as bid history).  The supplier may quote again."""
        reason = _text(reason, "withdrawal reason")
        actor = _text(actor, "actor")
        with self.db.transaction() as conn:
            q = self._quote_row(quote_id)
            if q["status"] != "live":
                raise ProcurementError(f"quote {quote_id} is already {q['status']}")
            req = self._requisition_row(q["requisition_id"])
            self._require_draft(req)
            version = self._bump(conn, "procurement_quotes", q, status="withdrawn", withdraw_reason=reason, withdrawn_at=utcnow_iso())
            req_version = self._bump(conn, "procurement_requisitions", req)
            cleared = self._revalidate_selection(conn, req["id"], changed_quote_id=quote_id, actor=actor)
            invalidated = self._invalidate_awards(req["id"], reason=f"quote {quote_id} withdrawn", actor=actor)
            self.audit.record(actor, "procurement.quote_withdrawn", QUOTE_SUBJECT, quote_id, {
                "requisition_id": req["id"], "reason": reason, "version": version, "requisition_version": req_version,
                "selection_cleared": cleared, "approvals_invalidated": invalidated,
            })
        return self.quote(quote_id)

    def quote(self, quote_id: str) -> dict[str, Any]:
        return self._present_quote(self._quote_row(quote_id), today=_today())

    @staticmethod
    def _present_quote(q: dict[str, Any], *, today: _dt.date) -> dict[str, Any]:
        out = dict(q)
        out["compliant"] = bool(q["compliant"])
        out["expired"] = _dt.date.fromisoformat(q["valid_until"]) < today
        out["eligible"] = out["compliant"] and not out["expired"] and q["status"] == "live"
        return out

    # ---- bid tab ----------------------------------------------------------------- #

    def bid_tab(self, requisition_id: str) -> dict[str, Any]:
        """Live quotes sorted by amount with the ``lowest_compliant`` flag, the
        spread (max - min of compliant quotes), the count and a hash of the tab
        bound by award approvals.

        ``spread`` follows the spec: every compliant live quote, expired or not.
        The ``lowest_compliant`` flag (and ``lowest_compliant_amount``) is the
        selection basis, so it is computed over *eligible* quotes - compliant and
        unexpired - because an expired offer can no longer be accepted;
        ``eligible_spread`` reports the spread of that narrower set."""
        req = self._requisition_row(requisition_id)
        return self._bid_tab(req, today=_today())

    def _bid_tab(self, req: dict[str, Any], *, today: _dt.date) -> dict[str, Any]:
        rows = self.db.query("SELECT q.*, p.name AS supplier_name FROM procurement_quotes q JOIN parties p ON p.id=q.supplier_id WHERE q.requisition_id=? AND q.status='live'", (req["id"],))
        quotes = [self._present_quote(r, today=today) for r in rows]
        quotes.sort(key=lambda q: (money(q["amount"]), q["lead_time_weeks"], q["created_at"], q["id"]))
        compliant = [money(q["amount"]) for q in quotes if q["compliant"]]
        eligible = [money(q["amount"]) for q in quotes if q["eligible"]]
        lowest = min(eligible) if eligible else None
        for q in quotes:
            q["lowest_compliant"] = q["eligible"] and money(q["amount"]) == lowest
            q["selected"] = q["id"] == req["selected_quote_id"]
        basis = [
            {k: q[k] for k in ("id", "version", "supplier_id", "amount", "lead_time_weeks", "valid_until", "compliant", "exceptions", "expired")}
            for q in quotes
        ]
        return {
            "requisition_id": req["id"],
            "requisition_version": req["version"],
            "quotes": quotes,
            "count": len(quotes),
            "compliant_count": len(compliant),
            "eligible_count": len(eligible),
            "lowest_compliant_amount": fmt(lowest) if lowest is not None else None,
            "lowest_compliant_quote_ids": [q["id"] for q in quotes if q["lowest_compliant"]],
            "spread": fmt(max(compliant) - min(compliant)) if compliant else None,
            "eligible_spread": fmt(max(eligible) - min(eligible)) if eligible else None,
            "as_of": today.isoformat(),
            "hash": hash_json({"requisition_id": req["id"], "quotes": basis}),
        }

    # ---- selection ---------------------------------------------------------------- #

    @staticmethod
    def _selection_problems(q: dict[str, Any] | None, tab: dict[str, Any], justification: str, *, selected_version: int | None = None) -> list[str]:
        """Why ``q`` cannot be (or no longer is) the selected quote; empty when it can."""
        if q is None:
            return ["no quote is selected"]
        problems = []
        if q["status"] != "live":
            problems.append(f"quote {q['id']} is {q['status']}")
        if selected_version is not None and q["version"] != selected_version:
            problems.append(f"quote {q['id']} was revised after it was selected")
        if not bool(q["compliant"]):
            problems.append(f"quote {q['id']} is not compliant and cannot be selected")
        if q.get("expired"):
            problems.append(f"quote {q['id']} expired on {q['valid_until']} and cannot be selected")
        if bool(q["compliant"]) and not q.get("expired") and q["id"] not in tab["lowest_compliant_quote_ids"] and not justification:
            problems.append(f"quote {q['id']} is not the lowest compliant quote ({tab['lowest_compliant_amount']}); a justification is required")
        return problems

    def select_quote(self, requisition_id: str, quote_id: str, justification: str = "", actor: str = "owner") -> dict[str, Any]:
        """Record the intended award.  A non-compliant or expired quote cannot be
        selected; anything other than the lowest compliant quote needs a justification."""
        justification = _text(justification, "justification", required=False)
        actor = _text(actor, "actor")
        today = _today()
        with self.db.transaction() as conn:
            req = self._requisition_row(requisition_id)
            self._require_draft(req)
            q = self._quote_row(quote_id)
            if q["requisition_id"] != requisition_id:
                raise ProcurementError(f"quote {quote_id} belongs to another requisition")
            tab = self._bid_tab(req, today=today)
            pq = self._present_quote(q, today=today)
            problems = self._selection_problems(pq, tab, justification)
            if problems:
                raise ProcurementError("; ".join(problems))
            if req["selected_quote_id"] == quote_id and req["selected_quote_version"] == q["version"] and req["justification"] == justification:
                raise ProcurementError(f"quote {quote_id} is already selected on requisition {requisition_id} with this justification")
            now = utcnow_iso()
            version = self._bump(conn, "procurement_requisitions", req, selected_quote_id=quote_id, selected_quote_version=q["version"],
                                 justification=justification, selected_by=actor, selected_at=now)
            invalidated = self._invalidate_awards(requisition_id, reason=f"selection changed to quote {quote_id}", actor=actor)
            self.audit.record(actor, "procurement.quote_selected", REQUISITION_SUBJECT, requisition_id, {
                "quote_id": quote_id, "quote_version": q["version"], "supplier_id": q["supplier_id"], "amount": q["amount"],
                "lowest_compliant": quote_id in tab["lowest_compliant_quote_ids"], "lowest_compliant_amount": tab["lowest_compliant_amount"],
                "justification": justification, "bid_tab_hash": tab["hash"], "version": version, "approvals_invalidated": invalidated,
            })
        return self.requisition(requisition_id)

    def _revalidate_selection(self, conn, requisition_id: str, *, changed_quote_id: str | None, actor: str) -> bool:
        """After a bid-set change, clear the selection when its quote changed or
        it no longer satisfies the selection rule.  Returns True if cleared."""
        req = self._requisition_row(requisition_id)
        if req["selected_quote_id"] is None:
            return False
        today = _today()
        q = self._present_quote(self._quote_row(req["selected_quote_id"]), today=today)
        tab = self._bid_tab(req, today=today)
        problems = self._selection_problems(q, tab, req["justification"], selected_version=req["selected_quote_version"])
        if changed_quote_id == req["selected_quote_id"]:
            problems.insert(0, f"selected quote {changed_quote_id} changed")
        if not problems:
            return False
        version = self._bump(conn, "procurement_requisitions", req, selected_quote_id=None, selected_quote_version=None, justification="", selected_by=None, selected_at=None)
        self.audit.record(actor, "procurement.selection_cleared", REQUISITION_SUBJECT, requisition_id, {
            "quote_id": req["selected_quote_id"], "reasons": problems, "version": version,
        })
        return True

    # ---- award (approval-bound) ---------------------------------------------------- #

    def _sov_lines(self, req: dict[str, Any], amount: Decimal | None) -> list[dict[str, Any]]:
        equipment = [self._equipment_row(eid) for eid in self._equipment_ids(req)]
        # Equal weights, so any order of the parts is a valid split; ordering
        # them largest first puts the odd cent(s) on the leading lines.
        parts = sorted(allocate(amount, [1] * len(equipment)), reverse=True) if amount is not None else [None] * len(equipment)
        return [
            {"equipment_id": eq["id"], "description": f"{eq['tag']} - {eq['description']}", "amount": fmt(part) if part is not None else None}
            for eq, part in zip(equipment, parts)
        ]

    def _award_facts(self, req: dict[str, Any]) -> dict[str, Any]:
        """Everything the award manifest binds, derived from current state, plus
        the problems that would stop the award."""
        today = _today()
        tab = self._bid_tab(req, today=today)
        problems: list[str] = []
        if req["status"] != "draft":
            problems.append(f"requisition {req['id']} is {req['status']}")
        q = None
        if req["selected_quote_id"]:
            q = self._present_quote(self._quote_row(req["selected_quote_id"]), today=today)
        problems += self._selection_problems(q, tab, req["justification"], selected_version=req["selected_quote_version"])
        amount = money(q["amount"]) if q is not None else None
        supplier = self.db.one("SELECT * FROM parties WHERE id=?", (q["supplier_id"],)) if q is not None else None
        sov = self._sov_lines(req, amount)
        if any(ln["amount"] is not None and money(ln["amount"]) <= 0 for ln in sov):
            problems.append("the award amount does not give every equipment item a positive PO line")
        return {"req": req, "tab": tab, "quote": q, "amount": amount, "supplier": supplier, "sov": sov, "problems": problems}

    def manifest_for(self, operation: str, subject_id: str, *, actor_role: str) -> dict[str, Any]:
        if operation != OP_AWARD:
            raise ProcurementError(f"unknown procurement operation {operation}")
        req = self._requisition_row(subject_id)
        f = self._award_facts(req)
        if f["problems"] and not self._consuming(self.db):
            raise ProcurementError(f"requisition {subject_id} cannot be awarded: " + "; ".join(f["problems"]))
        q, supplier, tab = f["quote"], f["supplier"], f["tab"]
        return build_manifest(
            operation=OP_AWARD,
            subject_type=REQUISITION_SUBJECT,
            subject_id=subject_id,
            actor_role=actor_role,
            amounts={"award": f["amount"] if f["amount"] is not None else "0"},
            bindings={
                "project_id": req["project_id"],
                "requisition_version": req["version"],
                "requisition_status": req["status"],
                "title": req["title"],
                "commitment_title": f"PO - {req['title']}",
                "selected_quote_id": req["selected_quote_id"],
                "selected_quote_version": req["selected_quote_version"],
                "quote_version": q["version"] if q else None,
                "quote_status": q["status"] if q else None,
                "quote_content_hash": q["content_hash"] if q else None,
                "supplier_id": q["supplier_id"] if q else None,
                "lead_time_weeks": q["lead_time_weeks"] if q else None,
                "valid_until": q["valid_until"] if q else None,
                "compliant": q["compliant"] if q else None,
                "expired": q["expired"] if q else None,
                "justification": req["justification"],
                "lowest_compliant": bool(q and q["id"] in tab["lowest_compliant_quote_ids"]),
                "lowest_compliant_amount": tab["lowest_compliant_amount"],
                "bid_tab_hash": tab["hash"],
                "bid_count": tab["count"],
                "equipment_ids": self._equipment_ids(req),
                "sov_lines": f["sov"],
                "sov_hash": hash_json(f["sov"]),
                "retainage_rate": AWARD_RETAINAGE,
                "destination_verified": bool(supplier["destination_verified"]) if supplier else False,
                "effect": "drafts the purchase order commitment; execution is the separate commitment.execute approval",
            },
            destination=(
                {"party_id": supplier["id"], "destination": supplier["destination"], "destination_version": supplier["destination_version"]}
                if supplier else None
            ),
        )

    def apply(self, operation: str, subject_id: str, *, approval_id: str, manifest: dict[str, Any], actor: str, period_id: str | None) -> dict[str, Any]:
        """Award the requisition: draft the commitment, record the award and mark
        the requisition awarded.  The caller has consumed ``approval_id`` against ``manifest``."""
        if operation != OP_AWARD:
            raise ProcurementError(f"unknown procurement operation {operation}")
        with self.db.transaction() as conn:
            req = self._requisition_row(subject_id)
            f = self._award_facts(req)
            if f["problems"]:
                raise AwardNotExecutable(f"requisition {subject_id} can no longer be awarded: " + "; ".join(f["problems"]))
            bindings = manifest.get("bindings") or {}
            if bindings.get("selected_quote_id") != req["selected_quote_id"] or (manifest.get("amounts") or {}).get("award") != fmt(f["amount"]):
                raise AwardNotExecutable(f"requisition {subject_id} selection no longer matches the approved manifest")
            pid = period_id or self.c.current_period()["id"]
            self.ledger.require_open(pid)
            q, tab, sov = f["quote"], f["tab"], f["sov"]
            commitment = self.c.commitments.create(
                project_id=req["project_id"],
                supplier_id=q["supplier_id"],
                title=f"PO - {req['title']}",
                sov_lines=[{"description": ln["description"], "amount": ln["amount"]} for ln in sov],
                retainage_rate=AWARD_RETAINAGE,
                estimate_id=None,
                actor=actor,
            )
            award_id = new_id("pawd")
            now = utcnow_iso()
            lowest = q["id"] in tab["lowest_compliant_quote_ids"]
            sov_hash = hash_json(sov)
            conn.execute(
                """INSERT INTO procurement_awards (id, requisition_id, quote_id, quote_version, supplier_id, amount, justification, lowest_compliant,
                   bid_tab_hash, sov_hash, commitment_id, approval_id, period_id, awarded_by, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (award_id, req["id"], q["id"], q["version"], q["supplier_id"], fmt(f["amount"]), req["justification"], 1 if lowest else 0,
                 tab["hash"], sov_hash, commitment["id"], approval_id, pid, actor, now),
            )
            version = self._bump(conn, "procurement_requisitions", req, status="awarded", award_id=award_id, awarded_at=now)
            self._invalidate_awards(req["id"], reason="requisition already awarded", actor=actor)
            self.audit.record(actor, "procurement.awarded", AWARD_SUBJECT, award_id, {
                "requisition_id": req["id"], "requisition_version": version, "quote_id": q["id"], "quote_version": q["version"],
                "supplier_id": q["supplier_id"], "amount": fmt(f["amount"]), "justification": req["justification"], "lowest_compliant": lowest,
                "bid_tab_hash": tab["hash"], "sov_hash": sov_hash, "commitment_id": commitment["id"], "commitment_status": commitment["status"],
                "approval_id": approval_id, "period_id": pid,
            })
        return {
            "requisition": req["id"], "status": "awarded", "award": award_id, "commitment": commitment["id"],
            "commitment_status": commitment["status"], "amount": fmt(f["amount"]), "supplier_id": q["supplier_id"],
            "sov": [ln["amount"] for ln in sov], "period_id": pid, "requisition_version": version,
        }

    def award(self, requisition_id: str) -> dict[str, Any] | None:
        req = self._requisition_row(requisition_id)
        return self.db.one("SELECT * FROM procurement_awards WHERE requisition_id=?", (req["id"],))

    # ---- milestones ------------------------------------------------------------------ #

    def _milestone_rows(self, equipment_id: str) -> list[dict[str, Any]]:
        return self.db.query("SELECT * FROM procurement_milestones WHERE equipment_id=? ORDER BY seq", (equipment_id,))

    def set_milestone_plan(self, equipment_id: str, plan: list[dict[str, Any]], actor: str = "owner") -> dict[str, Any]:
        """Set the planned dates.  Names follow submittal, approval, fabrication,
        factory_test, ship, delivery; planned dates must be non-decreasing in that
        order.  A re-plan keeps recorded actuals; planned milestones omitted from the
        new plan are dropped unless they already have an actual."""
        actor = _text(actor, "actor")
        if not isinstance(plan, (list, tuple)) or not plan:
            raise ProcurementError("a milestone plan needs at least one milestone")
        planned: dict[str, str] = {}
        for item in plan:
            if not isinstance(item, dict):
                raise ProcurementError("each milestone is an object with 'name' and 'planned'")
            name = item.get("name")
            if name not in MILESTONES:
                raise ProcurementError(f"unknown milestone {name!r}; expected one of {', '.join(MILESTONES)}")
            if name in planned:
                raise ProcurementError(f"milestone {name} appears twice in the plan")
            _date(item.get("planned"), f"{name} planned date")
            planned[name] = item["planned"]
        ordered = [(n, planned[n]) for n in MILESTONES if n in planned]
        for (n1, d1), (n2, d2) in zip(ordered, ordered[1:]):
            if d2 < d1:
                raise ProcurementError(f"planned {n2} {d2} is before planned {n1} {d1}; milestone dates must be non-decreasing")
        with self.db.transaction() as conn:
            eq = self._equipment_row(equipment_id)
            existing = {m["name"]: m for m in self._milestone_rows(equipment_id)}
            now = utcnow_iso()
            dropped = []
            for name, m in existing.items():
                if name in planned or m["planned"] is None:
                    continue
                if m["actual"] is None:
                    conn.execute("DELETE FROM procurement_milestones WHERE id=?", (m["id"],))
                else:
                    conn.execute("UPDATE procurement_milestones SET planned=NULL, updated_at=? WHERE id=?", (now, m["id"]))
                dropped.append(name)
            for name, d in ordered:
                if name in existing:
                    conn.execute("UPDATE procurement_milestones SET planned=?, updated_at=? WHERE id=?", (d, now, existing[name]["id"]))
                else:
                    conn.execute(
                        "INSERT INTO procurement_milestones (id, equipment_id, name, seq, planned, created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
                        (new_id("pms"), equipment_id, name, MILESTONES.index(name), d, now, now),
                    )
            version = self._bump(conn, "procurement_equipment", eq)
            self.audit.record(actor, "procurement.milestone_plan_set", EQUIPMENT_SUBJECT, equipment_id, {
                "tag": eq["tag"], "plan": dict(ordered), "dropped": dropped, "version": version,
            })
        return self.equipment(equipment_id)

    @staticmethod
    def _check_actual_order(conn, eq: dict[str, Any], name: str, actual: str) -> None:
        """Actuals follow the milestone sequence: an actual may not precede the
        recorded actual of an earlier milestone nor follow that of a later one
        (otherwise the furthest-along slip rule could hide lateness)."""
        idx = MILESTONES.index(name)
        rows = conn.execute("SELECT name, actual FROM procurement_milestones WHERE equipment_id=? AND actual IS NOT NULL", (eq["id"],)).fetchall()
        for m in rows:
            other = MILESTONES.index(m["name"])
            if other < idx and m["actual"] > actual:
                raise ProcurementError(
                    f"{name} actual {actual} is before the recorded {m['name']} actual {m['actual']} for {eq['tag']}; "
                    f"actuals follow {' -> '.join(MILESTONES)}"
                )
            if other > idx and m["actual"] < actual:
                raise ProcurementError(
                    f"{name} actual {actual} is after the recorded {m['name']} actual {m['actual']} for {eq['tag']}; "
                    f"actuals follow {' -> '.join(MILESTONES)}"
                )

    def _awarded_requisition_for_delivery(self, eq: dict[str, Any], d: _dt.date, label: str) -> dict[str, Any]:
        """Delivery (by ``receive`` or ``record_actual``) needs the equipment on an
        awarded requisition and a date on or after the award was recorded."""
        if eq["requisition_id"] is None:
            raise ProcurementError(f"equipment {eq['tag']} is not on a requisition; {label} is recorded only after award")
        req = self._requisition_row(eq["requisition_id"])
        if req["status"] != "awarded":
            raise ProcurementError(f"equipment {eq['tag']} is on requisition {req['id']} which is {req['status']}; {label} is recorded only after award")
        award = self.db.one("SELECT created_at FROM procurement_awards WHERE id=?", (req["award_id"],))
        if award is None:
            raise ProcurementError(f"requisition {req['id']} is awarded but its award record {req['award_id']} is missing")
        awarded_on = _dt.date.fromisoformat(award["created_at"][:10])
        if d < awarded_on:
            raise ProcurementError(f"{label} {d.isoformat()} is before equipment {eq['tag']} was awarded on {awarded_on.isoformat()}")
        return req

    def _set_actual(self, conn, eq: dict[str, Any], name: str, actual: str, source: str) -> None:
        row = conn.execute("SELECT * FROM procurement_milestones WHERE equipment_id=? AND name=?", (eq["id"], name)).fetchone()
        if row is not None and row["actual"] is not None:
            raise ProcurementError(f"equipment {eq['tag']} already has a {name} actual of {row['actual']}")
        self._check_actual_order(conn, eq, name, actual)
        now = utcnow_iso()
        if row is None:
            conn.execute(
                "INSERT INTO procurement_milestones (id, equipment_id, name, seq, planned, actual, actual_source, created_at, updated_at) VALUES (?,?,?,?,NULL,?,?,?,?)",
                (new_id("pms"), eq["id"], name, MILESTONES.index(name), actual, source, now, now),
            )
        else:
            conn.execute("UPDATE procurement_milestones SET actual=?, actual_source=?, updated_at=? WHERE id=?", (actual, source, now, row["id"]))

    def record_actual(self, equipment_id: str, name: str, actual_date: str, actor: str = "owner") -> dict[str, Any]:
        """Record a milestone actual: not in the future, recorded once, in
        milestone order.  A ``delivery`` actual (arrival reported without a
        receiving inspection) needs the equipment awarded and a date on or after
        the award; a later ``receive`` keeps it and may not predate it."""
        actor = _text(actor, "actor")
        if name not in MILESTONES:
            raise ProcurementError(f"unknown milestone {name!r}; expected one of {', '.join(MILESTONES)}")
        d = _date(actual_date, f"{name} actual date")
        if d > _today():
            raise ProcurementError(f"{name} actual date {actual_date} is in the future")
        with self.db.transaction() as conn:
            eq = self._equipment_row(equipment_id)
            if name == "delivery":
                self._awarded_requisition_for_delivery(eq, d, "the delivery actual")
            self._set_actual(conn, eq, name, actual_date, "record")
            version = self._bump(conn, "procurement_equipment", eq)
            self.audit.record(actor, "procurement.milestone_actual_recorded", EQUIPMENT_SUBJECT, equipment_id, {
                "tag": eq["tag"], "milestone": name, "actual": actual_date, "version": version,
            })
        return self.equipment(equipment_id)

    @staticmethod
    def _forecast(eq: dict[str, Any], milestones: list[dict[str, Any]]) -> dict[str, Any]:
        by_name = {m["name"]: m for m in milestones}
        slip = 0
        slip_basis = None
        for name in reversed(MILESTONES):
            m = by_name.get(name)
            if m and m["planned"] and m["actual"]:
                slip = (_dt.date.fromisoformat(m["actual"]) - _dt.date.fromisoformat(m["planned"])).days
                slip_basis = name
                break
        delivery = by_name.get("delivery")
        planned_delivery = delivery["planned"] if delivery else None
        if delivery and delivery["actual"]:
            forecast, basis = _dt.date.fromisoformat(delivery["actual"]), "actual"
        elif planned_delivery:
            forecast, basis = _dt.date.fromisoformat(planned_delivery) + _dt.timedelta(days=slip), "plan"
        else:
            forecast, basis = None, "none"
        required = _dt.date.fromisoformat(eq["required_on_site"])
        float_days = (required - forecast).days if forecast is not None else None
        return {
            "required_on_site": eq["required_on_site"],
            "planned_delivery": planned_delivery,
            "slip_days": slip,
            "slip_basis": slip_basis,
            "forecast_delivery": forecast.isoformat() if forecast else None,
            "forecast_basis": basis,
            "float_days": float_days,
            "late": float_days is not None and float_days < 0,
        }

    # ---- receiving ---------------------------------------------------------------------- #

    def receive(self, equipment_id: str, received_date: str, condition: str, evidence_hash: str, note: str = "", actor: str = "owner") -> dict[str, Any]:
        """Receive equipment on an awarded requisition.  Records the receipt and,
        unless ``record_actual`` already reported the arrival, the delivery
        actual; a damaged receipt is flagged in state.  Once per item.  The date
        may not be in the future, before the award, before an earlier milestone
        actual, or before an already recorded delivery actual."""
        d = _date(received_date, "received_date")
        if d > _today():
            raise ProcurementError(f"received_date {received_date} is in the future")
        if condition not in CONDITIONS:
            raise ProcurementError(f"condition must be one of {', '.join(CONDITIONS)}, got {condition!r}")
        evidence = _text(evidence_hash, "evidence_hash")
        note = _text(note, "note", required=False)
        actor = _text(actor, "actor")
        receipt_id = new_id("prcv")
        with self.db.transaction() as conn:
            eq = self._equipment_row(equipment_id)
            req = self._awarded_requisition_for_delivery(eq, d, "received_date")
            dup = conn.execute("SELECT id, received_date FROM procurement_receipts WHERE equipment_id=?", (equipment_id,)).fetchone()
            if dup is not None:
                raise ProcurementError(f"equipment {eq['tag']} was already received on {dup['received_date']} (receipt {dup['id']})")
            delivery = conn.execute("SELECT actual, actual_source FROM procurement_milestones WHERE equipment_id=? AND name='delivery'", (equipment_id,)).fetchone()
            if delivery is not None and delivery["actual"] is not None:
                if received_date < delivery["actual"]:
                    raise ProcurementError(f"received_date {received_date} is before the recorded delivery actual {delivery['actual']} for {eq['tag']}")
                delivery_actual, delivery_source = delivery["actual"], delivery["actual_source"]
            else:
                self._set_actual(conn, eq, "delivery", received_date, "receipt")
                delivery_actual, delivery_source = received_date, "receipt"
            conn.execute(
                """INSERT INTO procurement_receipts (id, equipment_id, requisition_id, award_id, received_date, condition, evidence_hash, note, received_by, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (receipt_id, equipment_id, req["id"], req["award_id"], received_date, condition, evidence, note, actor, utcnow_iso()),
            )
            version = self._bump(conn, "procurement_equipment", eq)
            self.audit.record(actor, "procurement.received", RECEIPT_SUBJECT, receipt_id, {
                "equipment_id": equipment_id, "tag": eq["tag"], "requisition_id": req["id"], "award_id": req["award_id"],
                "received_date": received_date, "condition": condition, "evidence_hash": evidence, "note": note, "equipment_version": version,
                "delivery_actual": delivery_actual, "delivery_actual_source": delivery_source,
            })
        return self.receipt(receipt_id)

    def receipt(self, receipt_id: str) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM procurement_receipts WHERE id=?", (receipt_id,)) if isinstance(receipt_id, str) else None
        if row is None:
            raise ProcurementError(f"unknown receipt {receipt_id}")
        row["damaged"] = row["condition"] == "damaged"
        return row

    # ---- reports and state ----------------------------------------------------------------- #

    def _award_status(self, eq: dict[str, Any]) -> dict[str, Any]:
        if eq["requisition_id"] is None:
            return {"award_status": "not_requisitioned", "requisition_id": None, "commitment_id": None, "commitment_status": None}
        req = self._requisition_row(eq["requisition_id"])
        commitment_id = commitment_status = None
        if req["status"] == "awarded":
            status = "awarded"
            aw = self.db.one("SELECT commitment_id FROM procurement_awards WHERE id=?", (req["award_id"],))
            if aw:
                commitment_id = aw["commitment_id"]
                commitment_status = self.db.scalar("SELECT status FROM commitments WHERE id=?", (commitment_id,))
        elif req["selected_quote_id"]:
            status = "selected"
        elif self.db.scalar("SELECT COUNT(*) FROM procurement_quotes WHERE requisition_id=? AND status='live'", (req["id"],)):
            status = "bidding"
        else:
            status = "requisitioned"
        return {"award_status": status, "requisition_id": req["id"], "commitment_id": commitment_id, "commitment_status": commitment_status}

    def _describe_equipment(self, eq: dict[str, Any]) -> dict[str, Any]:
        milestones = self._milestone_rows(eq["id"])
        out = dict(eq)
        out["long_lead"] = bool(eq["long_lead"])
        out["milestones"] = [
            {
                "name": m["name"], "planned": m["planned"], "actual": m["actual"], "actual_source": m["actual_source"],
                "variance_days": (_dt.date.fromisoformat(m["actual"]) - _dt.date.fromisoformat(m["planned"])).days if m["planned"] and m["actual"] else None,
            }
            for m in milestones
        ]
        out["forecast"] = self._forecast(eq, milestones)
        receipts = [self.receipt(r["id"]) for r in self.db.query("SELECT id FROM procurement_receipts WHERE equipment_id=? ORDER BY created_at", (eq["id"],))]
        out["receipts"] = receipts
        out["received"] = bool(receipts)
        out["damaged"] = any(r["damaged"] for r in receipts)
        out.update(self._award_status(eq))
        return out

    def long_lead_report(self, project_id: str) -> list[dict[str, Any]]:
        """Per equipment item: forecast delivery, float against required-on-site,
        late flag and award status; most critical (least float) first."""
        rows = []
        for e in self.equipment_list(project_id):
            f = e["forecast"]
            rows.append({
                "equipment_id": e["id"], "tag": e["tag"], "description": e["description"], "long_lead": e["long_lead"],
                "required_on_site": e["required_on_site"], "planned_delivery": f["planned_delivery"], "slip_days": f["slip_days"],
                "slip_basis": f["slip_basis"], "forecast_delivery": f["forecast_delivery"], "forecast_basis": f["forecast_basis"],
                "float_days": f["float_days"], "late": f["late"], "award_status": e["award_status"], "requisition_id": e["requisition_id"],
                "commitment_id": e["commitment_id"], "received": e["received"], "damaged": e["damaged"],
            })
        rows.sort(key=lambda r: (r["float_days"] is None, r["float_days"] if r["float_days"] is not None else 0, r["tag"].lower()))
        return rows

    def _describe_requisition(self, req: dict[str, Any]) -> dict[str, Any]:
        today = _today()
        out = dict(req)
        out["equipment_ids"] = self._equipment_ids(req)
        out.pop("equipment_json", None)
        out["equipment_tags"] = [self._equipment_row(e)["tag"] for e in out["equipment_ids"]]
        out["quotes"] = [self._present_quote(q, today=today) for q in self.db.query("SELECT * FROM procurement_quotes WHERE requisition_id=? ORDER BY created_at, id", (req["id"],))]
        out["bid_tab"] = self._bid_tab(req, today=today)
        award = self.db.one("SELECT * FROM procurement_awards WHERE requisition_id=?", (req["id"],))
        if award is not None:
            award["lowest_compliant"] = bool(award["lowest_compliant"])
            c = self.c.commitments.get(award["commitment_id"])
            award["commitment"] = {"id": c["id"], "status": c["status"], "original_amount": c["original_amount"], "sov": [{"description": s["description"], "amount": s["amount"]} for s in c["sov"]]}
        out["award"] = award
        return out

    def state(self, project_id: str) -> dict[str, Any]:
        equipment = self.equipment_list(project_id)
        requisitions = self.requisitions(project_id)
        report = self.long_lead_report(project_id)
        return {
            "equipment": equipment,
            "requisitions": requisitions,
            "long_lead_report": report,
            "summary": {
                "equipment": len(equipment),
                "long_lead": sum(1 for e in equipment if e["long_lead"]),
                "late": sum(1 for r in report if r["late"]),
                "requisitions": len(requisitions),
                "open_requisitions": sum(1 for r in requisitions if r["status"] == "draft"),
                "awarded": sum(1 for r in requisitions if r["status"] == "awarded"),
                "received": sum(1 for e in equipment if e["received"]),
                "damaged_receipts": sum(1 for e in equipment if e["damaged"]),
            },
        }

    def close_checks(self, period_id: str) -> list[dict[str, Any]]:
        """Informational only: procurement posts no journals, so nothing here blocks a close."""
        awards = self.db.scalar("SELECT COUNT(*) FROM procurement_awards WHERE period_id=?", (period_id,)) or 0
        draft_pos = self.db.scalar(
            "SELECT COUNT(*) FROM procurement_awards a JOIN commitments c ON c.id=a.commitment_id WHERE a.period_id=? AND c.status='draft'", (period_id,)
        ) or 0
        late = 0
        for p in self.db.query("SELECT DISTINCT project_id FROM procurement_equipment"):
            late += sum(1 for r in self.long_lead_report(p["project_id"]) if r["late"])
        damaged = self.db.scalar("SELECT COUNT(*) FROM procurement_receipts WHERE condition='damaged'") or 0
        return [
            {"check": "procurement awards in period", "ok": True,
             "detail": f"{awards} award(s) recorded in {period_id}; {draft_pos} purchase order(s) still draft (awards post no journals)"},
            {"check": "procurement late equipment (informational)", "ok": True, "detail": f"{late} equipment item(s) forecast to arrive after required-on-site"},
            {"check": "procurement damaged receipts (informational)", "ok": True, "detail": f"{damaged} receipt(s) recorded as damaged"},
        ]

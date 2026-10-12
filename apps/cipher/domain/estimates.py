"""Structured estimates bound to an evidence revision.

An estimate carries the exact document revision it was priced from.  If that
document gains a newer revision, or a newer estimate revision supersedes the
estimate, it is *stale* (``stale_reasons`` says which): it stays readable and
approved history is preserved, but Ricky abstains from building new
commitments on it and approvals that bind it (including commitment.execute
approvals, which bind ``estimate_stale``) are invalidated.

Structure (catalog entry ``estimates_structured``):

* **Lines** carry a quantity, a unit from the registry below (case-insensitive
  on input, stored upper-case) and a unit price.  Measured units (LF, SF, SY,
  CY) are quantities taken off a drawing, so an estimate that uses one must say
  how it was measured (``measurement_basis``, e.g. "drawing A rev 1 at 1:50,
  scale verified"); without it the estimate is refused ("unit/scale").
* **Totals**: ``subtotal`` is the sum of the line amounts, ``contingency`` is
  ``money(subtotal * contingency_rate)`` with ``0 <= rate <= 0.5`` and
  ``total = subtotal + contingency``.  A call without the new arguments has a
  zero rate, so its total is exactly the sum of its lines, as before.
* **Price book and scope**: the price-book edition (``price_book_ref``), the
  inclusions and the exclusions are part of the estimate.

Every one of these facts is bound into the content hash and into the
``estimate.approve`` manifest (together with the project's legal entity and
currency), so an approval can never execute against different scope, pricing
or measurement than the human saw.

Estimate content is immutable (enforced by triggers); a change is a new
revision that *supersedes* the previous one.  A superseding estimate must keep
the previous price book or explicitly name a new one (the change is recorded),
and it cannot silently drop an exclusion: every exclusion of the previous
revision must either remain or be listed in ``removed_exclusions``.  The
supersession is audited on both estimates, and any open approval on the
superseded estimate is invalidated in the same transaction.  An estimate has
at most one successor, and a superseded estimate can never be approved.

Those rules are checked against the scope the chain was *recorded* with -- the
``estimate.created`` audit entry of the nearest revision created through
Cipher -- not against whatever the predecessor row says now: a revision
written with plain SQL is skipped (and listed as unrecorded), and a row whose
stored scope was rewritten is compared by what it was created with.  A chain
with no recorded revision at all cannot be superseded.

A new estimate that supersedes nothing cannot side-step those rules either: if
a current estimate of the same project already prices one of its line items
from the same document, the new estimate must keep that estimate's exclusions
and name a price book where it had one, or supersede it instead.  Every current
estimate that shares a line item or the source document is bound into the
``estimate.approve`` manifest (``overlapping_estimates``), with the exclusions
the new estimate does not carry, so a parallel estimate is never silent.

The schema backs these rules for writes that bypass the API (catalog entries
``estimates_lifecycle_guards`` and ``estimates_no_replace_guards``): a row is
always inserted as a draft, it can only become approved by referencing a
consumed ``estimate.approve`` approval for itself, it can only become
superseded once its successor row exists (inserting the successor supersedes
it automatically), and no estimate or line is ever replaced (``REPLACE``,
``INSERT OR REPLACE``/``OR IGNORE`` and upserts on a stored id are refused,
because SQLite's replace deletes the old row without firing its delete or
update guards).  Approval additionally requires the estimate's own
``estimate.created`` audit entry, so a row written with plain SQL is never put
up for approval even if its hash re-derives; such a row, a row whose content
no longer re-derives to its hash, a superseded one and one priced from a
revised document are all *stale*, so nothing downstream (commitment.execute
binds ``estimate_stale``) can build on them.
"""
from __future__ import annotations

import json
import re
import sqlite3
import unicodedata
from decimal import Decimal, InvalidOperation, localcontext
from typing import Any

from ..core.approvals import Approvals, StaleApprovalError, build_manifest
from ..core.audit import Audit
from ..core.db import Database, register_schema_version
from ..core.ids import canonical_json, hash_json, new_id, utcnow_iso
from ..core.money import RATE_PLACES, D, MoneyError, fmt, money, total
from .evidence import Evidence, EvidenceError

# --------------------------------------------------------------------------- #
# Schema                                                                       #
# --------------------------------------------------------------------------- #

# The foundation schema is applied, checksummed history, so the structured
# columns and the immutability guards arrive as their own catalog entry.  The
# entry only adds columns, back-fills ``subtotal`` for rows created before it
# existed (their total *is* their subtotal) and creates triggers; it never
# rewrites or removes an existing record.
STRUCTURE_SCHEMA_NAME = "estimates_structured"
STRUCTURE_SCHEMA_STATEMENTS = [
    "ALTER TABLE estimates ADD COLUMN price_book_ref TEXT",
    "ALTER TABLE estimates ADD COLUMN inclusions_json TEXT NOT NULL DEFAULT '[]'",
    "ALTER TABLE estimates ADD COLUMN exclusions_json TEXT NOT NULL DEFAULT '[]'",
    "ALTER TABLE estimates ADD COLUMN contingency_rate TEXT NOT NULL DEFAULT '0.000000'",
    "ALTER TABLE estimates ADD COLUMN subtotal TEXT",
    "ALTER TABLE estimates ADD COLUMN measurement_basis TEXT",
    "UPDATE estimates SET subtotal = total WHERE subtotal IS NULL",
    """CREATE TRIGGER estimates_content_immutable BEFORE UPDATE ON estimates
        WHEN NEW.id IS NOT OLD.id OR NEW.project_id IS NOT OLD.project_id
          OR NEW.document_revision_id IS NOT OLD.document_revision_id OR NEW.revision IS NOT OLD.revision
          OR NEW.supersedes IS NOT OLD.supersedes OR NEW.total IS NOT OLD.total
          OR NEW.content_hash IS NOT OLD.content_hash OR NEW.created_at IS NOT OLD.created_at
          OR NEW.price_book_ref IS NOT OLD.price_book_ref OR NEW.inclusions_json IS NOT OLD.inclusions_json
          OR NEW.exclusions_json IS NOT OLD.exclusions_json OR NEW.contingency_rate IS NOT OLD.contingency_rate
          OR NEW.subtotal IS NOT OLD.subtotal OR NEW.measurement_basis IS NOT OLD.measurement_basis
        BEGIN SELECT RAISE(ABORT, 'estimate content is immutable; supersede it with a new revision'); END""",
    """CREATE TRIGGER estimates_status_lifecycle BEFORE UPDATE OF status, approval_id ON estimates
        WHEN NOT (
            (NEW.status IS OLD.status AND NEW.approval_id IS OLD.approval_id)
            OR (OLD.status = 'draft' AND NEW.status = 'approved' AND OLD.approval_id IS NULL AND NEW.approval_id IS NOT NULL)
            OR (OLD.status IN ('draft','approved') AND NEW.status = 'superseded' AND NEW.approval_id IS OLD.approval_id)
        )
        BEGIN SELECT RAISE(ABORT, 'estimate status may only move draft -> approved -> superseded'); END""",
    "CREATE TRIGGER estimates_no_delete BEFORE DELETE ON estimates BEGIN SELECT RAISE(ABORT, 'estimates are retained; supersede instead of deleting'); END",
    """CREATE TRIGGER estimates_single_successor BEFORE INSERT ON estimates
        WHEN NEW.supersedes IS NOT NULL AND EXISTS (SELECT 1 FROM estimates WHERE supersedes = NEW.supersedes)
        BEGIN SELECT RAISE(ABORT, 'estimate already has a successor'); END""",
    """CREATE TRIGGER estimate_lines_draft_only BEFORE INSERT ON estimate_lines
        WHEN (SELECT status FROM estimates WHERE id = NEW.estimate_id) IS NOT 'draft'
        BEGIN SELECT RAISE(ABORT, 'lines can only be added to a draft estimate'); END""",
    "CREATE TRIGGER estimate_lines_no_update BEFORE UPDATE ON estimate_lines BEGIN SELECT RAISE(ABORT, 'estimate lines are immutable'); END",
    "CREATE TRIGGER estimate_lines_no_delete BEFORE DELETE ON estimate_lines BEGIN SELECT RAISE(ABORT, 'estimate lines are immutable'); END",
]
register_schema_version(STRUCTURE_SCHEMA_NAME, STRUCTURE_SCHEMA_STATEMENTS)

# The lifecycle trigger above only checked the shape of a status change.  This
# entry (append-only history: a new entry, never an edit of the one above)
# replaces it with one that ties every transition to its evidence, the way the
# period-reopen guard in core/db.py does:
#
# * draft -> approved needs a *consumed* ``estimate.approve`` approval whose
#   subject is this very estimate (a pending approval, or another estimate's
#   approval, is refused);
# * draft/approved -> superseded needs the successor row to exist and keeps the
#   approval history;
# * a new row is always a draft without an approval, a first revision is
#   revision 1, and a successor must follow a current estimate of the same
#   project at the next revision number;
# * inserting a successor marks its predecessor superseded in the same
#   statement, so a revision chain can never have a live predecessor.
LIFECYCLE_SCHEMA_NAME = "estimates_lifecycle_guards"
LIFECYCLE_SCHEMA_STATEMENTS = [
    "DROP TRIGGER IF EXISTS estimates_status_lifecycle",
    """CREATE TRIGGER estimates_status_transitions BEFORE UPDATE OF status, approval_id ON estimates
        WHEN NOT (NEW.status IS OLD.status AND NEW.approval_id IS OLD.approval_id)
        BEGIN
            SELECT CASE
                WHEN OLD.status = 'draft' AND NEW.status = 'approved' THEN CASE
                    WHEN OLD.approval_id IS NOT NULL OR NEW.approval_id IS NULL
                    THEN RAISE(ABORT, 'approving an estimate requires a consumed estimate.approve approval for that estimate')
                    WHEN NOT EXISTS (
                        SELECT 1 FROM approvals a
                        WHERE a.id = NEW.approval_id AND a.status = 'consumed' AND a.operation = 'estimate.approve'
                          AND a.subject_type = 'estimate' AND a.subject_id = NEW.id)
                    THEN RAISE(ABORT, 'approving an estimate requires a consumed estimate.approve approval for that estimate; the referenced approval is not one')
                END
                WHEN OLD.status IN ('draft', 'approved') AND NEW.status = 'superseded' THEN CASE
                    WHEN NEW.approval_id IS NOT OLD.approval_id
                    THEN RAISE(ABORT, 'superseding an estimate keeps its approval history unchanged')
                    WHEN NOT EXISTS (SELECT 1 FROM estimates s WHERE s.supersedes = NEW.id)
                    THEN RAISE(ABORT, 'an estimate can only be superseded by a successor revision that exists')
                END
                ELSE RAISE(ABORT, 'estimate status may only move draft -> approved -> superseded')
            END;
        END""",
    """CREATE TRIGGER estimates_insert_rules BEFORE INSERT ON estimates
        BEGIN
            SELECT CASE
                WHEN NEW.status IS NOT 'draft' OR NEW.approval_id IS NOT NULL
                THEN RAISE(ABORT, 'a new estimate must be a draft without an approval; approval needs a consumed estimate.approve approval')
                WHEN NEW.supersedes IS NULL AND NEW.revision IS NOT 1
                THEN RAISE(ABORT, 'an estimate that supersedes nothing must be revision 1')
                WHEN NEW.supersedes IS NOT NULL AND NOT EXISTS (
                    SELECT 1 FROM estimates p
                    WHERE p.id = NEW.supersedes AND p.project_id = NEW.project_id
                      AND p.status IN ('draft', 'approved') AND NEW.revision = p.revision + 1)
                THEN RAISE(ABORT, 'a superseding estimate must follow a current estimate of the same project at the next revision number')
            END;
        END""",
    """CREATE TRIGGER estimates_successor_supersedes AFTER INSERT ON estimates
        WHEN NEW.supersedes IS NOT NULL
        BEGIN
            UPDATE estimates SET status = 'superseded' WHERE id = NEW.supersedes AND status IN ('draft', 'approved');
        END""",
    "CREATE INDEX IF NOT EXISTS estimates_by_supersedes ON estimates(supersedes)",
]
register_schema_version(LIFECYCLE_SCHEMA_NAME, LIFECYCLE_SCHEMA_STATEMENTS)

# REPLACE, INSERT OR REPLACE, INSERT OR IGNORE and upserts resolve a primary-key
# conflict by deleting (or skipping) the stored row; with recursive_triggers off
# SQLite fires none of that row's BEFORE DELETE or BEFORE UPDATE guards, so an
# approved or superseded estimate could otherwise be rewritten, revived as a
# draft, or robbed of its lines.  This entry (append-only: a new entry, never an
# edit of the ones above) refuses any insert whose id is already stored -- the
# pattern payments_controls_guards, rights and reimbursements use -- and any
# line that would take a line number its estimate already has.
NO_REPLACE_SCHEMA_NAME = "estimates_no_replace_guards"
NO_REPLACE_SCHEMA_STATEMENTS = [
    """CREATE TRIGGER estimates_no_replace BEFORE INSERT ON estimates
        WHEN EXISTS (SELECT 1 FROM estimates WHERE id = NEW.id)
        BEGIN SELECT RAISE(ABORT, 'estimates are never replaced: an estimate with this id is already stored; supersede it with a new revision'); END""",
    "CREATE INDEX IF NOT EXISTS estimate_lines_by_estimate ON estimate_lines(estimate_id, line_no)",
    """CREATE TRIGGER estimate_lines_no_replace BEFORE INSERT ON estimate_lines
        WHEN EXISTS (SELECT 1 FROM estimate_lines WHERE id = NEW.id OR (estimate_id = NEW.estimate_id AND line_no = NEW.line_no))
        BEGIN SELECT RAISE(ABORT, 'estimate lines are never replaced: a line with this id, or this line number on its estimate, is already stored'); END""",
]
register_schema_version(NO_REPLACE_SCHEMA_NAME, NO_REPLACE_SCHEMA_STATEMENTS)

# --------------------------------------------------------------------------- #
# Units and limits                                                             #
# --------------------------------------------------------------------------- #

UNITS: dict[str, str] = {
    "LS": "lump sum",
    "EA": "each",
    "LF": "linear foot",
    "SF": "square foot",
    "SY": "square yard",
    "CY": "cubic yard",
    "TON": "ton",
    "HR": "hour",
    "DAY": "day",
    "GAL": "gallon",
    "LB": "pound",
    "MO": "month",
}
# quantities in these units are taken off a drawing at a scale
MEASURED_UNITS = frozenset({"LF", "SF", "SY", "CY"})
DEFAULT_UNIT = "EA"
MAX_CONTINGENCY_RATE = Decimal("0.5")
# A quantity is a measurement: more precision than this is not information, and
# bounding it keeps the stored text, the hash and the line arithmetic exact.
MAX_QUANTITY_DIGITS = 15
MAX_QUANTITY_PLACES = 15
CONTENT_HASH_VERSION = "cipher-estimate-content/2"
_ZERO_RATE = Decimal("0").quantize(RATE_PLACES)


class EstimateError(RuntimeError):
    pass


class EstimateStaleError(EstimateError, StaleApprovalError):
    """The estimate cannot be approved as it stands any more: it is no longer a
    draft, its stored content no longer re-derives to its hash, or its source
    document was revised.  It is an EstimateError for callers of this module
    and a StaleApprovalError, so ``Cipher.execute`` invalidates an approval
    granted before the change instead of leaving it granted forever."""


# --------------------------------------------------------------------------- #
# Input normalisation                                                          #
# --------------------------------------------------------------------------- #

def _visible(text: str) -> bool:
    """True when ``text`` has at least one letter, digit, punctuation mark or
    symbol.  ``str.strip`` leaves zero-width and other format characters
    (U+200B, U+2060, U+FEFF, ...) in place, so blank-looking text is caught here."""
    return any(unicodedata.category(ch)[0] in "LNPS" for ch in text)


def _key(text: str) -> str:
    """Comparison key for scope items and line descriptions: compatibility forms
    folded (NFKC), invisible format and control characters dropped, whitespace
    collapsed and case folded, so a look-alike spelling ("Rock\\u200b excavation",
    full-width letters) neither counts as a different item nor hides a removal."""
    folded = unicodedata.normalize("NFKC", text)
    folded = "".join(ch for ch in folded if ch.isspace() or unicodedata.category(ch) not in ("Cf", "Cc"))
    return " ".join(folded.split()).casefold()


def _non_negative_zero(value: Decimal) -> Decimal:
    return value.copy_abs() if value.is_zero() else value


def _quantity_precision(value: Decimal) -> tuple[int, int]:
    """(significant digits, decimal places) of a finite decimal, ignoring trailing zeros."""
    _, digits, exponent = value.as_tuple()
    ds = list(digits)
    while len(ds) > 1 and ds[-1] == 0:
        ds.pop()
        exponent += 1
    if ds == [0]:
        return 1, 0
    return len(ds), max(0, -exponent)


def _line_amount(quantity: Decimal, unit_price: Decimal) -> Decimal:
    """``quantity * unit_price`` rounded once, half-up, to cents.  The product is
    formed under a local context wide enough to hold it exactly; under the
    default 28-digit context a long product would be rounded twice (to 28 digits,
    then to cents) and could land a cent high."""
    with localcontext() as ctx:
        ctx.prec = len(quantity.as_tuple().digits) + len(unit_price.as_tuple().digits) + 2
        product = quantity * unit_price
    return money(product)


def normalise_unit(value: Any, *, line_no: int | None = None) -> str:
    where = f"line {line_no}: " if line_no is not None else ""
    if value is None:
        return DEFAULT_UNIT
    if not isinstance(value, str):
        raise EstimateError(f"{where}unit must be text, one of {', '.join(UNITS)}")
    unit = value.strip().upper()
    if unit not in UNITS:
        raise EstimateError(f"{where}unknown unit {value!r}; allowed units are {', '.join(UNITS)}")
    return unit


def _optional_text(name: str, value: Any, *, empty_is_none: bool) -> str | None:
    """Text with surrounding blanks removed.  Text with nothing visible in it
    (blank, or only zero-width/format characters) counts as empty."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise EstimateError(f"{name} must be text")
    text = value.strip()
    if not _visible(text):
        if empty_is_none:
            return None
        raise EstimateError(f"{name} must be non-empty, visible text when given")
    return text


def _text_list(name: str, values: Any) -> list[str]:
    """An ordered list of distinct, non-empty text items (whitespace collapsed)."""
    if values is None:
        return []
    if not isinstance(values, (list, tuple)):
        raise EstimateError(f"{name} must be a list of text items")
    out: list[str] = []
    seen: dict[str, str] = {}
    for idx, raw in enumerate(values, start=1):
        if not isinstance(raw, str) or not _visible(raw):
            raise EstimateError(f"{name} item {idx} must be non-empty, visible text")
        text = " ".join(raw.split())
        k = _key(text)
        if k in seen:
            raise EstimateError(f"{name} lists {text!r} more than once")
        seen[k] = text
        out.append(text)
    return out


_RATE_TEXT = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)")  # ASCII digits only


def _parse_rate(value: Any) -> Decimal:
    """A contingency ratio.  It is not money, so the money parser's leniency
    (dropping ``$`` and ``,``) does not apply: text must be a plain decimal,
    otherwise a Decimal or an int.  Floats and bools are refused."""
    if isinstance(value, bool) or isinstance(value, float):
        raise EstimateError(f"contingency_rate must be a decimal string, Decimal or int, not {type(value).__name__}")
    if isinstance(value, Decimal):
        r = value
    elif isinstance(value, int):
        r = Decimal(value)
    elif isinstance(value, str):
        text = value.strip()
        if not _RATE_TEXT.fullmatch(text):
            raise EstimateError(f"contingency_rate must be a plain decimal such as '0.05': {value!r}")
        r = Decimal(text)
    else:
        raise EstimateError(f"contingency_rate must be a decimal string, Decimal or int, not {type(value).__name__}")
    if not r.is_finite():
        raise EstimateError("contingency_rate must be a finite decimal")
    if r < 0 or r > MAX_CONTINGENCY_RATE:
        raise EstimateError(f"contingency_rate must be between 0 and {MAX_CONTINGENCY_RATE}: {r}")
    q = r.quantize(RATE_PLACES)
    if q != r:
        raise EstimateError("contingency_rate allows at most six decimal places")
    return _non_negative_zero(q)


def _rate_text(r: Decimal) -> str:
    return f"{r:f}"


def _json_list(text: Any) -> list[Any] | None:
    """A stored JSON list column, or None when it does not hold a JSON list."""
    try:
        value = json.loads(text if text is not None else "[]")
    except (TypeError, ValueError):
        return None
    return value if isinstance(value, list) else None


def _hash_lines(lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    keys = ("line_no", "description", "quantity", "unit", "unit_price", "amount")
    return [{k: ln[k] for k in keys} for ln in lines]


def _content_hash(*, project_id: str, document_revision_id: str, document_hash: str, lines: list[dict[str, Any]],
                  price_book_ref: str | None, inclusions: list[str], exclusions: list[str], contingency_rate: str,
                  measurement_basis: str | None, subtotal: str, contingency: str, total_: str, supersedes: str | None) -> str:
    return hash_json({
        "hash_version": CONTENT_HASH_VERSION,
        "project_id": project_id,
        "document_revision_id": document_revision_id,
        "document_hash": document_hash,
        "lines": _hash_lines(lines),
        "price_book_ref": price_book_ref,
        "inclusions": inclusions,
        "exclusions": exclusions,
        "contingency_rate": contingency_rate,
        "measurement_basis": measurement_basis,
        "subtotal": subtotal,
        "contingency": contingency,
        "total": total_,
        "supersedes": supersedes,
    })


def _legacy_content_hash(*, document_revision_id: str, document_hash: str, lines: list[dict[str, Any]]) -> str:
    """Hash composition used before the structured entry (lines and evidence only)."""
    return hash_json({"document_revision_id": document_revision_id, "document_hash": document_hash, "lines": _hash_lines(lines)})


class Estimates:
    UNITS = UNITS
    MEASURED_UNITS = MEASURED_UNITS

    def __init__(self, db: Database, audit: Audit, evidence: Evidence):
        self.db = db
        self.audit = audit
        self.evidence = evidence

    @staticmethod
    def units() -> list[dict[str, Any]]:
        return [{"unit": u, "name": n, "measured": u in MEASURED_UNITS} for u, n in UNITS.items()]

    @staticmethod
    def _normalise_lines(lines: Any) -> list[dict[str, Any]]:
        if not isinstance(lines, (list, tuple)) or not lines:
            raise EstimateError("an estimate needs at least one line")
        out = []
        for idx, raw in enumerate(lines, start=1):
            if not isinstance(raw, dict):
                raise EstimateError(f"line {idx}: must be an object with description, quantity, unit and unit_price")
            for field in ("description", "quantity", "unit_price"):
                if raw.get(field) is None:
                    raise EstimateError(f"line {idx}: {field} is required")
            description = raw["description"]
            if not isinstance(description, str):
                raise EstimateError(f"line {idx}: description must be text, not {type(description).__name__}")
            if not _visible(description):
                raise EstimateError(f"line {idx}: description is required")
            unit = normalise_unit(raw.get("unit"), line_no=idx)
            try:
                qty = D(raw["quantity"])
                price = D(raw["unit_price"])
                if not qty.is_finite() or not price.is_finite():
                    raise EstimateError(f"line {idx}: quantity and unit price must be finite decimals")
                if qty < 0 or price < 0:
                    raise EstimateError(f"line {idx}: negative quantity or price")
                digits, places = _quantity_precision(qty)
                if digits > MAX_QUANTITY_DIGITS or places > MAX_QUANTITY_PLACES:
                    raise EstimateError(
                        f"line {idx}: quantity {raw['quantity']!r} is more precise than a measured quantity can be "
                        f"(at most {MAX_QUANTITY_DIGITS} significant digits and {MAX_QUANTITY_PLACES} decimal places); "
                        "round it to the precision it was measured to"
                    )
                price = _non_negative_zero(money(price))
                qty = _non_negative_zero(qty)
                amount = _line_amount(qty, price)
                quantity_text = f"{qty.normalize():f}"  # exact: at most 15 significant digits
            except MoneyError as exc:
                raise EstimateError(f"line {idx}: {exc}") from exc
            except InvalidOperation as exc:
                raise EstimateError(f"line {idx}: quantity or unit price is out of range") from exc
            out.append({
                "line_no": idx,
                "description": description,
                "quantity": quantity_text,
                "unit": unit,
                "unit_price": fmt(price),
                "amount": fmt(amount),
            })
        return out

    # ---- creation ---------------------------------------------------------- #

    def create(
        self,
        project_id: str,
        document_revision_id: str,
        lines: list[dict[str, Any]],
        actor: str,
        supersedes: str | None = None,
        *,
        price_book_ref: str | None = None,
        inclusions: list[str] | tuple[str, ...] = (),
        exclusions: list[str] | tuple[str, ...] = (),
        contingency_rate: str | Decimal | int = "0",
        measurement_basis: str | None = None,
        removed_exclusions: list[str] | tuple[str, ...] = (),
    ) -> dict[str, Any]:
        norm = self._normalise_lines(lines)
        basis = _optional_text("measurement_basis", measurement_basis, empty_is_none=True)
        measured = [ln for ln in norm if ln["unit"] in MEASURED_UNITS]
        if measured and basis is None:
            first = measured[0]
            raise EstimateError(
                f"unit/scale: line {first['line_no']} is measured in {first['unit']} but the estimate has no measurement_basis; "
                "state the source drawing revision and the verified scale"
            )
        book = _optional_text("price_book_ref", price_book_ref, empty_is_none=False)
        incl = _text_list("inclusions", inclusions)
        excl = _text_list("exclusions", exclusions)
        removed = _text_list("removed_exclusions", removed_exclusions)
        excl_keys = {_key(e) for e in excl}
        both = [x for x in incl if _key(x) in excl_keys]
        if both:
            raise EstimateError(f"scope items cannot be both included and excluded: {both}")
        cont_rate = _parse_rate("0" if contingency_rate is None else contingency_rate)
        supersedes = supersedes or None
        if removed and supersedes is None:
            raise EstimateError("removed_exclusions applies only to an estimate that supersedes another")

        try:
            subtotal = total(ln["amount"] for ln in norm)
            contingency = money(subtotal * cont_rate)
            est_total = money(subtotal + contingency)
        except (MoneyError, InvalidOperation) as exc:
            raise EstimateError(f"estimate totals are out of range: {exc}") from exc
        est_id = new_id("est")
        with self.db.transaction() as conn:
            self.db.require_write_authority()
            project = self.db.one("SELECT id FROM projects WHERE id=?", (project_id,))
            if project is None:
                raise EstimateError(f"unknown project {project_id}")
            try:
                rev = self.evidence.revision(document_revision_id)
            except EvidenceError as exc:
                raise EstimateError(str(exc)) from exc
            doc = self.db.one("SELECT project_id FROM documents WHERE id=?", (rev["document_id"],))
            if doc is None or doc["project_id"] != project_id:
                raise EstimateError(f"document revision {document_revision_id} belongs to another project")

            revision, supersession, baseline = 1, None, None
            if supersedes is not None:
                prev = self._row(supersedes)
                if prev["project_id"] != project_id:
                    raise EstimateError("cannot supersede an estimate from another project")
                if prev["status"] == "superseded":
                    successor = self.db.scalar("SELECT id FROM estimates WHERE supersedes=?", (supersedes,))
                    by = f" by {successor}" if successor else ""
                    raise EstimateError(f"estimate {supersedes} was already superseded{by}; revise the current revision instead")
                # the price-book and exclusion rules compare with the scope the chain was
                # recorded with, never with a row written or rewritten around the API
                baseline = self._baseline(supersedes)
                if baseline["estimate_id"] is None:
                    raise EstimateError(
                        f"estimate {supersedes} was not created through Cipher, and neither was any revision it supersedes "
                        "(no estimate.created audit entry records their scope), so there is no recorded scope a successor "
                        "can be checked against; start a new estimate instead"
                    )
                supersession = self._check_supersession(baseline, book, excl, removed)
                revision = prev["revision"] + 1

            # current estimates that price the same line items or the same document
            overlaps = self._overlaps(project_id, rev["document_id"], norm, excl, exclude=(supersedes,) if supersedes else ())
            if supersedes is None:
                self._check_parallel(overlaps, book)

            content_hash = _content_hash(
                project_id=project_id, document_revision_id=document_revision_id, document_hash=rev["content_hash"], lines=norm,
                price_book_ref=book, inclusions=incl, exclusions=excl, contingency_rate=_rate_text(cont_rate),
                measurement_basis=basis, subtotal=fmt(subtotal), contingency=fmt(contingency), total_=fmt(est_total), supersedes=supersedes,
            )
            dup = self.db.one("SELECT id FROM estimates WHERE project_id=? AND content_hash=? AND status IN ('draft','approved')", (project_id, content_hash))
            if dup is not None:
                raise EstimateError(f"duplicate estimate: {dup['id']} already has identical content")

            try:
                # inserting a successor also marks its predecessor superseded (trigger
                # estimates_successor_supersedes), so the chain never has a live predecessor
                conn.execute(
                    """INSERT INTO estimates (id, project_id, document_revision_id, revision, supersedes, status, total, content_hash, created_at,
                           price_book_ref, inclusions_json, exclusions_json, contingency_rate, subtotal, measurement_basis)
                       VALUES (?,?,?,?,?,'draft',?,?,?,?,?,?,?,?,?)""",
                    (est_id, project_id, document_revision_id, revision, supersedes, fmt(est_total), content_hash, utcnow_iso(),
                     book, canonical_json(incl), canonical_json(excl), _rate_text(cont_rate), fmt(subtotal), basis),
                )
                for ln in norm:
                    conn.execute(
                        "INSERT INTO estimate_lines (id, estimate_id, line_no, description, quantity, unit, unit_price, amount) VALUES (?,?,?,?,?,?,?,?)",
                        (new_id("eln"), est_id, ln["line_no"], ln["description"], ln["quantity"], ln["unit"], ln["unit_price"], ln["amount"]),
                    )
                if supersedes is not None:
                    conn.execute("UPDATE estimates SET status='superseded' WHERE id=?", (supersedes,))  # no-op after the trigger; explicit for clarity
            except sqlite3.IntegrityError as exc:
                raise EstimateError(f"the estimate store refused the record: {exc}") from exc
            payload = {
                "project_id": project_id, "document_revision_id": document_revision_id, "revision": revision,
                "subtotal": fmt(subtotal), "contingency_rate": _rate_text(cont_rate), "contingency": fmt(contingency), "total": fmt(est_total),
                "content_hash": content_hash, "supersedes": supersedes, "price_book_ref": book, "inclusions": incl, "exclusions": excl,
                "measurement_basis": basis, "units": sorted({ln["unit"] for ln in norm}),
                "overlapping_estimates": [o["estimate_id"] for o in overlaps],
            }
            if supersession is not None:
                payload.update({
                    "price_book": {"previous": supersession["price_book_previous"], "current": book, "changed": supersession["price_book_changed"]},
                    "removed_exclusions": supersession["removed_exclusions"],
                    "added_exclusions": supersession["added_exclusions"],
                    "compared_with": baseline["estimate_id"],
                    "unrecorded_revisions": baseline["unrecorded_revisions"],
                })
                self.audit.record(actor, "estimate.superseded", "estimate", supersedes, {
                    "superseded_by": est_id, "previous_status": prev["status"],
                    "price_book": payload["price_book"], "removed_exclusions": supersession["removed_exclusions"],
                    "compared_with": baseline["estimate_id"], "unrecorded_revisions": baseline["unrecorded_revisions"],
                })
                approvals = Approvals(self.db, self.audit)
                approvals.invalidate_for_subject(
                    "estimate", supersedes, reason=f"estimate {supersedes} was superseded by {est_id}", actor=actor,
                )
                # revisions written around the API superseded their predecessors without
                # an audited supersession; nothing approved against that chain survives it
                for other in [*baseline["unrecorded_revisions"], baseline["estimate_id"]]:
                    if other != supersedes:
                        approvals.invalidate_for_subject(
                            "estimate", other, reason=f"estimate {other} was superseded outside Cipher; {est_id} now continues the chain",
                            actor=actor,
                        )
            self.audit.record(actor, "estimate.created", "estimate", est_id, payload)
        return self.get(est_id)

    @staticmethod
    def _check_supersession(baseline: dict[str, Any], book: str | None, excl: list[str], removed: list[str]) -> dict[str, Any]:
        """Price-book and exclusion rules for a successor, checked against the
        chain's recorded scope (``_baseline``)."""
        base_id = baseline["estimate_id"]
        where = f"estimate {base_id}"
        if baseline["unrecorded_revisions"]:
            where += f" (the latest revision of this chain created through Cipher; {baseline['unrecorded_revisions']} were not)"
        prev_book = baseline["price_book_ref"]
        if prev_book is not None and book is None:
            raise EstimateError(
                f"{where} was priced from price book {prev_book!r}; a superseding estimate must keep it "
                "or explicitly name the new edition (price_book_ref)"
            )
        prev_by_key = {_key(x): x for x in baseline["exclusions"]}
        new_keys = {_key(x) for x in excl}
        removed_keys = set()
        for item in removed:
            k = _key(item)
            if k not in prev_by_key:
                raise EstimateError(f"removed exclusion {item!r} is not an exclusion of {where}")
            if k in new_keys:
                raise EstimateError(f"exclusion {item!r} is listed as removed but is still excluded")
            removed_keys.add(k)
        dropped = [x for k, x in prev_by_key.items() if k not in new_keys and k not in removed_keys]
        if dropped:
            raise EstimateError(
                f"a superseding estimate cannot silently drop exclusions {dropped} of {where}; keep them or list them in removed_exclusions"
            )
        return {
            "price_book_previous": prev_book,
            "price_book_changed": prev_book != book,
            "removed_exclusions": [x for k, x in prev_by_key.items() if k in removed_keys],
            "added_exclusions": [x for x in excl if _key(x) not in prev_by_key],
        }

    @staticmethod
    def _check_parallel(overlaps: list[dict[str, Any]], book: str | None) -> None:
        """A new estimate that supersedes nothing may not drop the exclusions or the
        price book of a current estimate that already prices one of its line items
        from the same document: that is a revision, and only a supersession may
        remove an exclusion (recorded in removed_exclusions)."""
        for o in overlaps:
            if not (o["same_document"] and o["shared_lines"]) or o["scope_recorded_by"] is None:
                continue
            dropped_book = o["price_book_ref"] is not None and book is None
            if not (o["exclusions_not_carried"] or dropped_book):
                continue
            what = []
            if o["exclusions_not_carried"]:
                what.append(f"exclusions {o['exclusions_not_carried']}")
            if dropped_book:
                what.append(f"price book {o['price_book_ref']!r}")
            raise EstimateError(
                f"estimate {o['estimate_id']} already prices {o['shared_lines']} from this document; a new estimate cannot "
                f"silently drop its {' and its '.join(what)}: supersede it (supersedes={o['estimate_id']!r}) and list any "
                "removed exclusion in removed_exclusions, or keep its exclusions and name a price book"
            )

    # ---- recorded scope ------------------------------------------------------ #

    def _creation_payload(self, estimate_id: str) -> dict[str, Any] | None:
        """The payload of the estimate's first ``estimate.created`` audit entry (the
        hash-chained record of what create() wrote), or None when there is none."""
        row = self.db.one(
            "SELECT payload_json FROM audit_log WHERE entity_type='estimate' AND entity_id=? AND action='estimate.created' ORDER BY seq LIMIT 1",
            (estimate_id,),
        )
        if row is None:
            return None
        try:
            payload = json.loads(row["payload_json"] or "{}")
        except ValueError:
            return None
        return payload if isinstance(payload, dict) else None

    def _recorded_scope(self, estimate_id: str) -> dict[str, Any] | None:
        """Price book, exclusions and content hash the estimate was created with,
        from its creation audit entry (a pre-structure entry records neither, and
        such an estimate had neither).  None for a row nobody created through Cipher."""
        payload = self._creation_payload(estimate_id)
        if payload is None:
            return None
        book = payload.get("price_book_ref")
        excl = payload.get("exclusions", [])
        content_hash = payload.get("content_hash")
        if (book is not None and not isinstance(book, str)) or not isinstance(excl, list) or not all(isinstance(x, str) for x in excl):
            return None
        return {"price_book_ref": book, "exclusions": list(excl), "content_hash": content_hash if isinstance(content_hash, str) else None}

    def _baseline(self, start_id: str) -> dict[str, Any]:
        """The recorded scope of the chain ending at ``start_id``: walk back through
        ``supersedes`` to the nearest revision with a creation audit entry and use
        what that entry recorded.  Rows on the way with no such entry (written with
        plain SQL) are listed in ``unrecorded_revisions``; ``record_intact`` says
        whether the baseline row still stores what was recorded.  When no revision
        of the chain was recorded, ``estimate_id`` is None."""
        unrecorded: list[str] = []
        seen: set[str] = set()
        cur: str | None = start_id
        while cur is not None and cur not in seen:
            seen.add(cur)
            row = self.db.one("SELECT id, supersedes, content_hash, price_book_ref, exclusions_json FROM estimates WHERE id=?", (cur,))
            if row is None:
                break
            scope = self._recorded_scope(cur)
            if scope is not None:
                recorded_hash = scope["content_hash"] or row["content_hash"]
                intact = (row["content_hash"] == recorded_hash and row["price_book_ref"] == scope["price_book_ref"]
                          and _json_list(row["exclusions_json"]) == scope["exclusions"])
                return {"estimate_id": cur, "content_hash": recorded_hash, "price_book_ref": scope["price_book_ref"],
                        "exclusions": scope["exclusions"], "record_intact": intact, "unrecorded_revisions": unrecorded}
            unrecorded.append(cur)
            cur = row["supersedes"]
        return {"estimate_id": None, "content_hash": None, "price_book_ref": None, "exclusions": [], "record_intact": False,
                "unrecorded_revisions": unrecorded}

    def _overlaps(self, project_id: str, document_id: str, lines: list[dict[str, Any]], exclusions: list[str],
                  *, exclude: tuple[str | None, ...] = ()) -> list[dict[str, Any]]:
        """Current (draft or approved) estimates of the project that price one of
        these line items (same description, compared by ``_key``) or are priced
        from the same document (any revision).  Each carries the scope its chain
        was recorded with: its price book and the exclusions not carried here."""
        mine: dict[str, str] = {}
        for ln in lines:
            mine.setdefault(_key(str(ln["description"])), str(ln["description"]))
        excl_keys = {_key(x) for x in exclusions}
        rows = self.db.query(
            """SELECT e.id, e.content_hash, r.document_id FROM estimates e JOIN document_revisions r ON r.id = e.document_revision_id
               WHERE e.project_id=? AND e.status IN ('draft','approved') ORDER BY e.created_at, e.id""",
            (project_id,),
        )
        out = []
        for r in rows:
            if r["id"] in exclude:
                continue
            theirs = self._scope_line_keys(r["id"])
            shared = [text for k, text in mine.items() if k in theirs]
            same_document = r["document_id"] == document_id
            if not shared and not same_document:
                continue
            base = self._baseline(r["id"])
            recorded = base["estimate_id"] is not None
            out.append({
                "estimate_id": r["id"],
                "content_hash": r["content_hash"],
                "same_document": same_document,
                "shared_lines": shared,
                "scope_recorded_by": base["estimate_id"],
                "price_book_ref": base["price_book_ref"] if recorded else None,
                "exclusions_not_carried": [x for x in base["exclusions"] if _key(x) not in excl_keys] if recorded else [],
            })
        return out

    def _line_keys(self, estimate_id: str) -> set[str]:
        return {_key(str(x["description"])) for x in self.db.query("SELECT description FROM estimate_lines WHERE estimate_id=?", (estimate_id,))}

    def _scope_line_keys(self, estimate_id: str) -> set[str]:
        """The line items a current estimate stands for: its own and, when it cannot
        be trusted (written around the API, or no longer matching its hash), those of
        the nearest revision of its chain that can -- so a raw successor with no or
        other lines cannot clear the way for a parallel estimate of the same scope."""
        keys = self._line_keys(estimate_id)
        seen: set[str] = set()
        cur: str | None = estimate_id
        while cur is not None and cur not in seen:
            seen.add(cur)
            est = self.get(cur)
            if est["content_verified"] and est["creation_recorded"]:
                keys |= self._line_keys(cur)
                break
            cur = est["supersedes"]
        return keys

    def overlaps(self, estimate_id: str) -> list[dict[str, Any]]:
        """Other current estimates that share a line item or the source document with this one."""
        est = self.get(estimate_id)
        return self._overlaps(est["project_id"], est["evidence"]["document_id"], est["lines"], est["exclusions"] or [], exclude=(estimate_id,))

    # ---- reading ----------------------------------------------------------- #

    def _row(self, estimate_id: str) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM estimates WHERE id=?", (estimate_id,))
        if row is None:
            raise EstimateError(f"unknown estimate {estimate_id}")
        return row

    def get(self, estimate_id: str) -> dict[str, Any]:
        row = self._row(estimate_id)
        row["lines"] = self.db.query("SELECT * FROM estimate_lines WHERE estimate_id=? ORDER BY line_no", (estimate_id,))
        rev = self.evidence.revision(row["document_revision_id"])
        row["evidence"] = {"document_id": rev["document_id"], "revision": rev["revision"], "content_hash": rev["content_hash"], "is_current": rev["is_current"], "current_revision": rev["current_revision"]}
        row["superseded_by"] = self.db.scalar("SELECT id FROM estimates WHERE supersedes=?", (estimate_id,))
        row["inclusions"] = _json_list(row.get("inclusions_json"))
        row["exclusions"] = _json_list(row.get("exclusions_json"))
        if row.get("subtotal") is None:
            row["subtotal"] = row["total"]
        try:
            row["contingency"] = fmt(money(row["total"]) - money(row["subtotal"]))
        except (MoneyError, InvalidOperation):
            row["contingency"] = None
        row["content_verified"] = self._verify(row, rev)
        row["creation_recorded"] = self._creation_recorded(row)
        # An estimate is stale -- not a basis for new commitments -- when its source
        # document was revised, when a newer estimate revision superseded it, when
        # its stored content no longer re-derives to its hash, or when nobody
        # created it through Cipher.  Downstream records that bind ``stale`` (the
        # commitment.execute manifest binds estimate_stale) therefore go stale on
        # any of these, so scope dropped by a later revision (removed_exclusions),
        # or rewritten around the API, never executes through an approval granted
        # against what the approver saw.
        reasons = []
        if not rev["is_current"]:
            reasons.append("priced from a superseded document revision")
        if row["status"] == "superseded" or row["superseded_by"] is not None:
            reasons.append(f"superseded by estimate {row['superseded_by']}" if row["superseded_by"] else "superseded by a newer estimate revision")
        if not row["content_verified"]:
            reasons.append("its stored content no longer matches its content hash")
        if not row["creation_recorded"]:
            reasons.append("not created through Cipher (no matching estimate.created audit entry)")
        row["stale"] = bool(reasons)
        row["stale_reasons"] = reasons
        row["supersession"] = self._supersession_view(row) if row["supersedes"] else None
        return row

    def _supersession_view(self, row: dict[str, Any]) -> dict[str, Any]:
        """What this revision changed, measured against the chain's recorded scope
        (``_baseline``), so a predecessor written or rewritten around the API can
        neither hide a dropped exclusion nor stand in for the recorded price book."""
        prev = self.db.one("SELECT id, content_hash, price_book_ref, exclusions_json FROM estimates WHERE id=?", (row["supersedes"],))
        if prev is None:
            return {"supersedes": row["supersedes"], "missing": True}
        base = self._baseline(prev["id"])
        if base["estimate_id"] is None:  # nothing in the chain was recorded: the stored predecessor is all there is
            ref_book, ref_excl = prev["price_book_ref"], _json_list(prev["exclusions_json"]) or []
        else:
            ref_book, ref_excl = base["price_book_ref"], base["exclusions"]
        cur = row["exclusions"] or []
        cur_keys = {_key(str(x)) for x in cur}
        ref_keys = {_key(str(x)) for x in ref_excl}
        return {
            "supersedes": prev["id"],
            "previous_content_hash": prev["content_hash"],
            "baseline": None if base["estimate_id"] is None else {
                "estimate_id": base["estimate_id"], "content_hash": base["content_hash"], "record_intact": base["record_intact"],
            },
            "unrecorded_revisions": base["unrecorded_revisions"],
            "price_book_previous": ref_book,
            "price_book_changed": ref_book != row["price_book_ref"],
            "removed_exclusions": [x for x in ref_excl if _key(str(x)) not in cur_keys],
            "added_exclusions": [x for x in cur if _key(str(x)) not in ref_keys],
        }

    @staticmethod
    def _verify(row: dict[str, Any], rev: dict[str, Any]) -> bool:
        """Re-derive the arithmetic and the content hash from the stored rows.

        Rows created before the structured entry carry the older hash composition
        (lines and evidence only); they verify against it only while every
        structured field still holds its neutral default."""
        try:
            lines = row["lines"]
            if not lines:
                return False
            if not isinstance(row["inclusions"], list) or not isinstance(row["exclusions"], list):
                return False
            for ln in lines:
                if fmt(_line_amount(D(ln["quantity"]), money(ln["unit_price"]))) != ln["amount"]:
                    return False
            subtotal = total(ln["amount"] for ln in lines)
            if fmt(subtotal) != row["subtotal"]:
                return False
            cont_rate = _parse_rate(row["contingency_rate"])
            if _rate_text(cont_rate) != row["contingency_rate"]:
                return False
            contingency = money(subtotal * cont_rate)
            if fmt(contingency) != row["contingency"] or fmt(subtotal + contingency) != row["total"]:
                return False
            expected = _content_hash(
                project_id=row["project_id"], document_revision_id=row["document_revision_id"], document_hash=rev["content_hash"], lines=lines,
                price_book_ref=row["price_book_ref"], inclusions=row["inclusions"], exclusions=row["exclusions"],
                contingency_rate=row["contingency_rate"], measurement_basis=row["measurement_basis"], subtotal=row["subtotal"],
                contingency=row["contingency"], total_=row["total"], supersedes=row["supersedes"],
            )
            if expected == row["content_hash"]:
                return True
            legacy_shape = (
                row["price_book_ref"] is None and row.get("inclusions_json") == "[]" and row.get("exclusions_json") == "[]"
                and cont_rate == _ZERO_RATE and row["measurement_basis"] is None
            )
            return legacy_shape and _legacy_content_hash(
                document_revision_id=row["document_revision_id"], document_hash=rev["content_hash"], lines=lines,
            ) == row["content_hash"]
        except (EstimateError, MoneyError, InvalidOperation, KeyError, TypeError, AttributeError, ValueError):
            return False

    def _creation_recorded(self, est: dict[str, Any]) -> bool:
        """True when the estimate's first ``estimate.created`` audit entry vouches for
        the stored row (it names the stored content hash, or names none, as a
        pre-hash entry would).  A row written around the API (plain SQL) has no such
        entry: its content may re-derive to its own hash, but nobody created it
        through Cipher; an entry recorded later cannot vouch for it either."""
        payload = self._creation_payload(est["id"])
        return payload is not None and payload.get("content_hash", est["content_hash"]) == est["content_hash"]

    def _approval_blocker(self, est: dict[str, Any]) -> EstimateError | None:
        """Why this estimate can never be approved as it stands, or None.

        A change that happened after an approval could have been granted (status,
        content, a revised source document) is an ``EstimateStaleError``, so
        executing such an approval invalidates it; the refusal also comes at
        request time.  The unit rules are enforced at creation; they matter here
        only for rows created before them."""
        if est["status"] != "draft":
            return EstimateStaleError(f"estimate {est['id']} is {est['status']}; only a draft estimate can be approved")
        if not est["content_verified"]:
            return EstimateStaleError(f"estimate {est['id']} no longer matches its content hash; it cannot be approved")
        if not est["creation_recorded"]:
            return EstimateError(f"estimate {est['id']} has no matching estimate.created audit entry; it was not created through Cipher "
                                 "and cannot be approved")
        if est["stale"]:
            return EstimateStaleError(f"estimate {est['id']} is {'; '.join(est['stale_reasons'])}; it cannot be approved: "
                                      "supersede it with a revision priced from the current document revision")
        for ln in est["lines"]:
            if str(ln["unit"]).strip().upper() not in UNITS:
                return EstimateError(f"line {ln['line_no']}: unit {ln['unit']!r} is not in the unit registry; supersede the estimate with registered units")
        if est["measurement_basis"] is None:
            for ln in est["lines"]:
                if str(ln["unit"]).strip().upper() in MEASURED_UNITS:
                    return EstimateError(f"unit/scale: line {ln['line_no']} is measured in {ln['unit']} but the estimate has no measurement_basis; "
                                         "supersede it with the source drawing revision and the verified scale")
        return None

    def list(self, project_id: str) -> list[dict[str, Any]]:
        return [self.get(r["id"]) for r in self.db.query("SELECT id FROM estimates WHERE project_id=? ORDER BY created_at", (project_id,))]

    # ---- approval ---------------------------------------------------------- #

    def manifest(self, estimate_id: str, *, actor_role: str) -> dict[str, Any]:
        """The ``estimate.approve`` manifest.  Only a current draft whose stored content
        still re-derives to its hash can be put up for approval; superseding or
        approving the estimate invalidates every open approval on it.  The manifest
        binds the chain's recorded scope and every other current estimate that
        shares a line item or the source document (with the exclusions this one
        does not carry), so a new or superseded parallel estimate makes it stale."""
        est = self.get(estimate_id)
        blocker = self._approval_blocker(est)
        if blocker is not None:
            raise blocker
        project = self.db.one("SELECT entity, currency FROM projects WHERE id=?", (est["project_id"],))
        if project is None:
            raise EstimateError(f"estimate {estimate_id} refers to an unknown project")
        sup = est["supersession"] or {}
        overlaps = self._overlaps(est["project_id"], est["evidence"]["document_id"], est["lines"], est["exclusions"], exclude=(estimate_id,))
        return build_manifest(
            operation="estimate.approve",
            subject_type="estimate",
            subject_id=estimate_id,
            actor_role=actor_role,
            amounts={"subtotal": est["subtotal"], "contingency": est["contingency"], "total": est["total"]},
            bindings={
                "estimate_revision": est["revision"],
                "estimate_hash": est["content_hash"],
                "document_revision_id": est["document_revision_id"],
                "document_hash": est["evidence"]["content_hash"],
                "document_is_current": est["evidence"]["is_current"],
                "project_id": est["project_id"],
                "price_book_ref": est["price_book_ref"],
                "inclusions": est["inclusions"],
                "exclusions": est["exclusions"],
                "contingency_rate": est["contingency_rate"],
                "measurement_basis": est["measurement_basis"],
                "units": sorted({ln["unit"] for ln in est["lines"]}),
                "supersedes": est["supersedes"],
                "superseded_estimate_hash": sup.get("previous_content_hash"),
                "price_book_previous": sup.get("price_book_previous"),
                "price_book_changed": bool(sup.get("price_book_changed", False)),
                "removed_exclusions": sup.get("removed_exclusions", []),
                "supersession_baseline": sup.get("baseline"),
                "unrecorded_revisions": sup.get("unrecorded_revisions", []),
                "overlapping_estimates": overlaps,
            },
            entity=project["entity"],
            currency=project["currency"],
        )

    def approve(self, estimate_id: str, *, approval_id: str, actor: str) -> dict[str, Any]:
        """Mark approved.  The caller has already consumed ``approval_id``, which must be
        an ``estimate.approve`` approval for this estimate.  Any other open approval on
        the estimate is invalidated: it can never execute now."""
        with self.db.transaction() as conn:
            est = self.get(estimate_id)
            blocker = self._approval_blocker(est)  # status, content, provenance, staleness, units
            if blocker is not None:
                raise blocker
            ap = self.db.one("SELECT operation, subject_type, subject_id, status FROM approvals WHERE id=?", (approval_id,))
            if ap is None or (ap["operation"], ap["subject_type"], ap["subject_id"]) != ("estimate.approve", "estimate", estimate_id) or ap["status"] != "consumed":
                raise EstimateError(f"approval {approval_id} is not a consumed estimate.approve approval for estimate {estimate_id}")
            try:  # the schema re-checks the approval reference (trigger estimates_status_transitions)
                conn.execute("UPDATE estimates SET status='approved', approval_id=? WHERE id=?", (approval_id, estimate_id))
            except sqlite3.IntegrityError as exc:
                raise EstimateError(f"the estimate store refused the approval: {exc}") from exc
            self.audit.record(actor, "estimate.approved", "estimate", estimate_id, {
                "approval_id": approval_id, "subtotal": est["subtotal"], "contingency": est["contingency"], "total": est["total"],
                "content_hash": est["content_hash"],
            })
            Approvals(self.db, self.audit).invalidate_for_subject(
                "estimate", estimate_id, reason=f"estimate {estimate_id} was already approved under {approval_id}", actor=actor,
            )
        return self.get(estimate_id)

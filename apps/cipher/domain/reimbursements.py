"""Staff expense reimbursements, kept separate from customer billing.

An employee submits a claim backed by a receipt.  Nothing touches the books
until an owner approves the claim; approval posts the reimbursable expense and
the employee payable.  Payments draw the payable down (partial payments are
allowed, over-payment is not).  Billing the customer for a billable claim is a
*separate* authority path: it posts receivable and revenue and never changes
the employee payable.  An approval granted in error is corrected by voiding
the claim, which appends a reversal of the approval journal; posted journals
are never edited.

Posting rules (fixture policy ``cipher-posting-rules/1``):

* ``reimbursement.approve``  Dr 5100 reimbursable expense / Cr 2100 employee payable (party = employee)
* ``reimbursement.pay``      Dr 2100 employee payable (party = employee) / Cr 1000 operating bank
* ``reimbursement.bill``     Dr 1100 accounts receivable (party = project customer) / Cr 4000 contract revenue
* ``reimbursement.void``     reversal of the approval journal (Dr 2100 / Cr 5100); only while nothing
                             has been paid or billed on the claim

Record lifecycle (the schema trigger ``reimbursement_claims_status_forward_only``
rejects every other status change):

* claim:    submitted -> approved -> partially_paid -> paid
                         approved -> voided
* payment:  draft -> booked | canceled
* billing:  draft -> billed | canceled

Approvals bind the record version and content hash of the subject, the amount,
the employee, the receipt hash and (for payments) the claim's outstanding
balance, so any material change after an approval was granted invalidates it
instead of executing something the approver did not see.  Editing a submitted
claim, booking a payment, posting a billing or voiding the claim also
proactively invalidates the open approvals that the change makes meaningless.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from ..core.approvals import build_manifest
from ..core.ids import hash_json, new_id, utcnow_iso
from ..core.money import ZERO, MoneyError, fmt, money, total

SCHEMA_NAME = "reimbursements"
PLUGIN_NAME = "reimbursement"
POSTING_RULE = "cipher-posting-rules/1"

CLAIM_SUBJECT = "reimbursement_claim"
PAYMENT_SUBJECT = "reimbursement_payment"
BILLING_SUBJECT = "reimbursement_billing"

OP_APPROVE = "reimbursement.approve"
OP_PAY = "reimbursement.pay"
OP_BILL = "reimbursement.bill"
OP_VOID = "reimbursement.void"

APPROVED_STATES = ("approved", "partially_paid", "paid")
PAYABLE_STATES = ("approved", "partially_paid")

SCHEMA_STATEMENTS = [
    """CREATE TABLE reimbursement_claims (
        id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES projects(id),
        employee_id TEXT NOT NULL REFERENCES parties(id),
        description TEXT NOT NULL,
        amount TEXT NOT NULL,
        receipt_hash TEXT NOT NULL,
        billable INTEGER NOT NULL DEFAULT 0 CHECK (billable IN (0, 1)),
        status TEXT NOT NULL CHECK (status IN ('submitted','approved','partially_paid','paid','voided')),
        version INTEGER NOT NULL DEFAULT 1,
        content_hash TEXT NOT NULL,
        approval_id TEXT REFERENCES approvals(id),
        journal_id TEXT REFERENCES journals(id),
        period_id TEXT REFERENCES periods(id),
        void_approval_id TEXT REFERENCES approvals(id),
        reversal_journal_id TEXT REFERENCES journals(id),
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        approved_at TEXT,
        voided_at TEXT
    )""",
    # One live claim per receipt.  A voided claim keeps its row as history but releases the
    # receipt so the employee can resubmit a corrected claim for it.
    "CREATE UNIQUE INDEX reimbursement_claims_live_receipt ON reimbursement_claims(receipt_hash) WHERE status != 'voided'",
    """CREATE TABLE reimbursement_payments (
        id TEXT PRIMARY KEY,
        claim_id TEXT NOT NULL REFERENCES reimbursement_claims(id),
        amount TEXT NOT NULL,
        status TEXT NOT NULL CHECK (status IN ('draft','booked','canceled')),
        version INTEGER NOT NULL DEFAULT 1,
        approval_id TEXT REFERENCES approvals(id),
        journal_id TEXT REFERENCES journals(id),
        period_id TEXT REFERENCES periods(id),
        created_at TEXT NOT NULL,
        booked_at TEXT,
        canceled_at TEXT
    )""",
    """CREATE TABLE reimbursement_billings (
        id TEXT PRIMARY KEY,
        claim_id TEXT NOT NULL REFERENCES reimbursement_claims(id),
        customer_id TEXT NOT NULL REFERENCES parties(id),
        amount TEXT NOT NULL,
        status TEXT NOT NULL CHECK (status IN ('draft','billed','canceled')),
        version INTEGER NOT NULL DEFAULT 1,
        approval_id TEXT REFERENCES approvals(id),
        journal_id TEXT REFERENCES journals(id),
        period_id TEXT REFERENCES periods(id),
        created_at TEXT NOT NULL,
        billed_at TEXT,
        canceled_at TEXT
    )""",
    # Once a claim has been approved its content is frozen: corrections go through reimbursement.void.
    """CREATE TRIGGER reimbursement_claims_frozen_after_approval
        BEFORE UPDATE OF amount, description, receipt_hash, employee_id, project_id, billable ON reimbursement_claims
        WHEN OLD.status != 'submitted'
        BEGIN SELECT RAISE(ABORT, 'approved reimbursement claims are immutable; correct through reimbursement.void'); END""",
    # The status column only ever moves forward along the documented lifecycle.
    """CREATE TRIGGER reimbursement_claims_status_forward_only
        BEFORE UPDATE OF status ON reimbursement_claims
        WHEN NEW.status != OLD.status AND NOT (
            (OLD.status = 'submitted' AND NEW.status = 'approved')
            OR (OLD.status = 'approved' AND NEW.status IN ('partially_paid','paid','voided'))
            OR (OLD.status = 'partially_paid' AND NEW.status = 'paid')
        )
        BEGIN SELECT RAISE(ABORT, 'illegal reimbursement claim status transition'); END""",
    "CREATE TRIGGER reimbursement_claims_no_delete BEFORE DELETE ON reimbursement_claims BEGIN SELECT RAISE(ABORT, 'reimbursement claims are never deleted'); END",
    """CREATE TRIGGER reimbursement_payments_final_immutable BEFORE UPDATE ON reimbursement_payments
        WHEN OLD.status IN ('booked','canceled')
        BEGIN SELECT RAISE(ABORT, 'booked or canceled reimbursement payments are immutable'); END""",
    "CREATE TRIGGER reimbursement_payments_no_delete BEFORE DELETE ON reimbursement_payments BEGIN SELECT RAISE(ABORT, 'reimbursement payments are never deleted'); END",
    """CREATE TRIGGER reimbursement_billings_final_immutable BEFORE UPDATE ON reimbursement_billings
        WHEN OLD.status IN ('billed','canceled')
        BEGIN SELECT RAISE(ABORT, 'billed or canceled reimbursement billings are immutable'); END""",
    "CREATE TRIGGER reimbursement_billings_no_delete BEFORE DELETE ON reimbursement_billings BEGIN SELECT RAISE(ABORT, 'reimbursement billings are never deleted'); END",
]


class ReimbursementError(RuntimeError):
    """Invalid reimbursement input or an action the claim's state does not allow."""


def _positive_amount(value, label: str = "amount") -> Decimal:
    try:
        amt = money(value)
    except MoneyError as exc:
        raise ReimbursementError(f"{label} is not exact money: {exc}") from exc
    if amt <= 0:
        raise ReimbursementError(f"{label} must be positive, got {fmt(amt)}")
    return amt


def _non_empty(value, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ReimbursementError(f"{label} is required and must be a non-empty string")
    return value.strip()


def _claim_content_hash(row: dict[str, Any]) -> str:
    return hash_json({
        "project_id": row["project_id"],
        "employee_id": row["employee_id"],
        "description": row["description"],
        "amount": fmt(row["amount"]),
        "receipt_hash": row["receipt_hash"],
        "billable": bool(row["billable"]),
    })


class Plugin:
    def __init__(self, cipher):
        self.c = cipher
        self.db = cipher.db
        self.audit = cipher.audit
        self.ledger = cipher.ledger
        self.approvals = cipher.approvals

    # ---- claims ----------------------------------------------------------- #

    def submit_claim(self, *, project_id: str, employee_id: str, description: str, amount, receipt_hash: str, billable: bool = False, actor: str) -> dict[str, Any]:
        # shape validation is stateless and can run before the lock is taken
        description = _non_empty(description, "description")
        amt = _positive_amount(amount)
        receipt = _non_empty(receipt_hash, "receipt_hash")
        if not isinstance(billable, bool):
            raise ReimbursementError("billable must be True or False")
        claim_id = new_id("rclm")
        content = {"project_id": project_id, "employee_id": employee_id, "description": description, "amount": fmt(amt), "receipt_hash": receipt, "billable": billable}
        content_hash = _claim_content_hash(content)
        with self.db.transaction() as conn:
            # state-dependent checks run under the write lock so nothing can change
            # between the check and the insert
            if self.db.one("SELECT id FROM projects WHERE id=?", (project_id,)) is None:
                raise ReimbursementError(f"unknown project {project_id}")
            employee = self.db.one("SELECT id, kind FROM parties WHERE id=?", (employee_id,))
            if employee is None:
                raise ReimbursementError(f"unknown party {employee_id}")
            if employee["kind"] != "employee":
                raise ReimbursementError(f"only employee parties can claim reimbursement; {employee_id} is a {employee['kind']}")
            if self._live_claim_for_receipt(receipt) is not None:
                raise ReimbursementError(f"a claim already exists for receipt {receipt}")
            now = utcnow_iso()
            conn.execute(
                """INSERT INTO reimbursement_claims (id, project_id, employee_id, description, amount, receipt_hash, billable, status, version, content_hash, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,'submitted',1,?,?,?)""",
                (claim_id, project_id, employee_id, description, fmt(amt), receipt, 1 if billable else 0, content_hash, now, now),
            )
            self.audit.record(actor, "reimbursement.claim_submitted", CLAIM_SUBJECT, claim_id, {**content, "content_hash": content_hash})
        return self.claim(claim_id)

    def update_claim(self, claim_id: str, *, actor: str, amount=None, description: str | None = None, billable: bool | None = None, receipt_hash: str | None = None) -> dict[str, Any]:
        """Edit a submitted claim.  Bumps the version and invalidates every open
        approval bound to the previous version."""
        if amount is None and description is None and billable is None and receipt_hash is None:
            raise ReimbursementError("nothing to update")
        with self.db.transaction() as conn:
            row = self._claim_row(claim_id)
            if row["status"] != "submitted":
                raise ReimbursementError(f"claim {claim_id} is {row['status']}; only submitted claims can be edited")
            changes: dict[str, Any] = {}
            if amount is not None:
                changes["amount"] = fmt(_positive_amount(amount))
            if description is not None:
                changes["description"] = _non_empty(description, "description")
            if billable is not None:
                if not isinstance(billable, bool):
                    raise ReimbursementError("billable must be True or False")
                changes["billable"] = billable
            if receipt_hash is not None:
                receipt = _non_empty(receipt_hash, "receipt_hash")
                if self._live_claim_for_receipt(receipt, exclude=claim_id) is not None:
                    raise ReimbursementError(f"a claim already exists for receipt {receipt}")
                changes["receipt_hash"] = receipt
            merged = {**row, **changes}
            new_version = row["version"] + 1
            content_hash = _claim_content_hash(merged)
            conn.execute(
                "UPDATE reimbursement_claims SET amount=?, description=?, billable=?, receipt_hash=?, version=?, content_hash=?, updated_at=? WHERE id=?",
                (fmt(merged["amount"]), merged["description"], 1 if merged["billable"] else 0, merged["receipt_hash"], new_version, content_hash, utcnow_iso(), claim_id),
            )
            invalidated = self.approvals.invalidate_for_subject(CLAIM_SUBJECT, claim_id, reason=f"claim edited to version {new_version} after approval was requested", actor=actor)
            self.audit.record(actor, "reimbursement.claim_updated", CLAIM_SUBJECT, claim_id, {"changes": changes, "version": new_version, "content_hash": content_hash, "approvals_invalidated": invalidated})
        return self.claim(claim_id)

    def _claim_row(self, claim_id: str) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM reimbursement_claims WHERE id=?", (claim_id,))
        if row is None:
            raise ReimbursementError(f"unknown reimbursement claim {claim_id}")
        return row

    def _live_claim_for_receipt(self, receipt: str, *, exclude: str | None = None) -> dict[str, Any] | None:
        """The non-voided claim holding this receipt, if any."""
        if exclude is None:
            return self.db.one("SELECT id FROM reimbursement_claims WHERE receipt_hash=? AND status != 'voided'", (receipt,))
        return self.db.one("SELECT id FROM reimbursement_claims WHERE receipt_hash=? AND status != 'voided' AND id != ?", (receipt, exclude))

    def _booked_total(self, claim_id: str) -> Decimal:
        rows = self.db.query("SELECT amount FROM reimbursement_payments WHERE claim_id=? AND status='booked'", (claim_id,))
        return total(r["amount"] for r in rows)

    def _draft_payment_total(self, claim_id: str) -> Decimal:
        rows = self.db.query("SELECT amount FROM reimbursement_payments WHERE claim_id=? AND status='draft'", (claim_id,))
        return total(r["amount"] for r in rows)

    def _billed_total(self, claim_id: str, *, include_drafts: bool) -> Decimal:
        statuses = "('draft','billed')" if include_drafts else "('billed')"
        rows = self.db.query(f"SELECT amount FROM reimbursement_billings WHERE claim_id=? AND status IN {statuses}", (claim_id,))
        return total(r["amount"] for r in rows)

    def _outstanding_row(self, row: dict[str, Any]) -> Decimal:
        if row["status"] not in APPROVED_STATES:
            return ZERO
        return money(money(row["amount"]) - self._booked_total(row["id"]))

    def outstanding(self, claim_id: str) -> Decimal:
        """Approved amount less booked payments.  A claim that is not approved (or was voided) owes nothing."""
        return self._outstanding_row(self._claim_row(claim_id))

    def claim(self, claim_id: str) -> dict[str, Any]:
        row = self._claim_row(claim_id)
        row["billable"] = bool(row["billable"])
        row["outstanding"] = fmt(self._outstanding_row(row))
        row["paid"] = fmt(self._booked_total(claim_id))
        row["billed"] = fmt(self._billed_total(claim_id, include_drafts=False))
        row["payments"] = self.db.query("SELECT * FROM reimbursement_payments WHERE claim_id=? ORDER BY created_at, id", (claim_id,))
        row["billings"] = self.db.query("SELECT * FROM reimbursement_billings WHERE claim_id=? ORDER BY created_at, id", (claim_id,))
        return row

    def claims(self, project_id: str) -> list[dict[str, Any]]:
        rows = self.db.query("SELECT id FROM reimbursement_claims WHERE project_id=? ORDER BY created_at, id", (project_id,))
        return [self.claim(r["id"]) for r in rows]

    # ---- payments ----------------------------------------------------------- #

    def record_payment(self, claim_id: str, amount, *, actor: str) -> dict[str, Any]:
        """Draft a payment against an approved claim.  It may be partial but, together
        with other unbooked drafts, may not exceed the outstanding balance."""
        amt = _positive_amount(amount, "payment amount")
        with self.db.transaction() as conn:
            row = self._claim_row(claim_id)
            if row["status"] not in PAYABLE_STATES:
                raise ReimbursementError(f"claim {claim_id} is {row['status']}; only approved claims with an outstanding balance can be paid")
            outstanding = self._outstanding_row(row)
            reserved = self._draft_payment_total(claim_id)
            available = money(outstanding - reserved)
            if amt > available:
                raise ReimbursementError(
                    f"payment {fmt(amt)} exceeds the outstanding balance {fmt(outstanding)} on claim {claim_id}"
                    + (f" less {fmt(reserved)} already in draft payments" if reserved > 0 else "")
                )
            payment_id = new_id("rpay")
            conn.execute(
                "INSERT INTO reimbursement_payments (id, claim_id, amount, status, version, created_at) VALUES (?,?,?,'draft',1,?)",
                (payment_id, claim_id, fmt(amt), utcnow_iso()),
            )
            self.audit.record(actor, "reimbursement.payment_recorded", PAYMENT_SUBJECT, payment_id, {"claim_id": claim_id, "amount": fmt(amt), "outstanding_before": fmt(outstanding)})
        return self.payment(payment_id)

    def cancel_payment(self, payment_id: str, *, actor: str, reason: str = "") -> dict[str, Any]:
        with self.db.transaction():
            p = self.payment(payment_id)
            if p["status"] != "draft":
                raise ReimbursementError(f"payment {payment_id} is {p['status']}; only draft payments can be canceled")
            self._cancel_draft_payment(p, actor=actor, reason=reason)
        return self.payment(payment_id)

    def _cancel_draft_payment(self, p: dict[str, Any], *, actor: str, reason: str) -> None:
        """Caller holds the transaction and has checked that ``p`` is a draft."""
        self.db.execute("UPDATE reimbursement_payments SET status='canceled', version=version+1, canceled_at=? WHERE id=?", (utcnow_iso(), p["id"]))
        invalidated = self.approvals.invalidate_for_subject(PAYMENT_SUBJECT, p["id"], reason=f"payment canceled: {reason}", actor=actor)
        self.audit.record(actor, "reimbursement.payment_canceled", PAYMENT_SUBJECT, p["id"], {"claim_id": p["claim_id"], "amount": p["amount"], "reason": reason, "approvals_invalidated": invalidated})

    def payment(self, payment_id: str) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM reimbursement_payments WHERE id=?", (payment_id,))
        if row is None:
            raise ReimbursementError(f"unknown reimbursement payment {payment_id}")
        return row

    def payments(self, project_id: str) -> list[dict[str, Any]]:
        return self.db.query(
            "SELECT p.* FROM reimbursement_payments p JOIN reimbursement_claims c ON c.id=p.claim_id WHERE c.project_id=? ORDER BY p.created_at, p.id",
            (project_id,),
        )

    # ---- billings ------------------------------------------------------------ #

    def create_billing(self, claim_id: str, amount, *, actor: str) -> dict[str, Any]:
        """Draft a customer billing for a billable, approved claim.  Billings
        (drafted or billed) may not exceed the claim amount in total."""
        amt = _positive_amount(amount, "billing amount")
        with self.db.transaction() as conn:
            row = self._claim_row(claim_id)
            if not row["billable"]:
                raise ReimbursementError(f"claim {claim_id} is not billable to the customer")
            if row["status"] not in APPROVED_STATES:
                raise ReimbursementError(f"claim {claim_id} is {row['status']}; only approved claims can be billed")
            project = self.db.one("SELECT customer_id FROM projects WHERE id=?", (row["project_id"],))
            if project is None or not project["customer_id"]:
                raise ReimbursementError("project has no customer party to bill")
            already = self._billed_total(claim_id, include_drafts=True)
            remaining = money(money(row["amount"]) - already)
            if amt > remaining:
                raise ReimbursementError(f"billing {fmt(amt)} exceeds the unbilled claim amount {fmt(remaining)} (claim {row['amount']}, billed or drafted {fmt(already)})")
            billing_id = new_id("rbil")
            conn.execute(
                "INSERT INTO reimbursement_billings (id, claim_id, customer_id, amount, status, version, created_at) VALUES (?,?,?,?,'draft',1,?)",
                (billing_id, claim_id, project["customer_id"], fmt(amt), utcnow_iso()),
            )
            self.audit.record(actor, "reimbursement.billing_created", BILLING_SUBJECT, billing_id, {"claim_id": claim_id, "customer_id": project["customer_id"], "amount": fmt(amt)})
        return self.billing(billing_id)

    def cancel_billing(self, billing_id: str, *, actor: str, reason: str = "") -> dict[str, Any]:
        with self.db.transaction():
            b = self.billing(billing_id)
            if b["status"] != "draft":
                raise ReimbursementError(f"billing {billing_id} is {b['status']}; only draft billings can be canceled")
            self._cancel_draft_billing(b, actor=actor, reason=reason)
        return self.billing(billing_id)

    def _cancel_draft_billing(self, b: dict[str, Any], *, actor: str, reason: str) -> None:
        """Caller holds the transaction and has checked that ``b`` is a draft."""
        self.db.execute("UPDATE reimbursement_billings SET status='canceled', version=version+1, canceled_at=? WHERE id=?", (utcnow_iso(), b["id"]))
        invalidated = self.approvals.invalidate_for_subject(BILLING_SUBJECT, b["id"], reason=f"billing canceled: {reason}", actor=actor)
        self.audit.record(actor, "reimbursement.billing_canceled", BILLING_SUBJECT, b["id"], {"claim_id": b["claim_id"], "amount": b["amount"], "reason": reason, "approvals_invalidated": invalidated})

    def billing(self, billing_id: str) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM reimbursement_billings WHERE id=?", (billing_id,))
        if row is None:
            raise ReimbursementError(f"unknown reimbursement billing {billing_id}")
        return row

    def billings(self, project_id: str) -> list[dict[str, Any]]:
        return self.db.query(
            "SELECT b.* FROM reimbursement_billings b JOIN reimbursement_claims c ON c.id=b.claim_id WHERE c.project_id=? ORDER BY b.created_at, b.id",
            (project_id,),
        )

    # ---- approvals: manifests ------------------------------------------------ #

    def manifest_for(self, operation: str, subject_id: str, *, actor_role: str) -> dict[str, Any]:
        if operation == OP_APPROVE:
            return self._approve_manifest(subject_id, actor_role=actor_role)
        if operation == OP_PAY:
            return self._pay_manifest(subject_id, actor_role=actor_role)
        if operation == OP_BILL:
            return self._bill_manifest(subject_id, actor_role=actor_role)
        if operation == OP_VOID:
            return self._void_manifest(subject_id, actor_role=actor_role)
        raise ReimbursementError(f"unknown reimbursement operation {operation}")

    def _approve_manifest(self, claim_id: str, *, actor_role: str) -> dict[str, Any]:
        row = self._claim_row(claim_id)
        if row["status"] != "submitted":
            raise ReimbursementError(f"claim {claim_id} is {row['status']}, not submitted")
        return build_manifest(
            operation=OP_APPROVE,
            subject_type=CLAIM_SUBJECT,
            subject_id=claim_id,
            actor_role=actor_role,
            amounts={"amount": row["amount"]},
            bindings={
                "claim_version": row["version"],
                "claim_hash": row["content_hash"],
                "project_id": row["project_id"],
                "employee_id": row["employee_id"],
                "receipt_hash": row["receipt_hash"],
                "billable": bool(row["billable"]),
                "posting_rule": POSTING_RULE,
            },
        )

    def _pay_manifest(self, payment_id: str, *, actor_role: str) -> dict[str, Any]:
        p = self.payment(payment_id)
        if p["status"] != "draft":
            raise ReimbursementError(f"payment {payment_id} is {p['status']}, not draft")
        row = self._claim_row(p["claim_id"])
        employee = self.db.one("SELECT * FROM parties WHERE id=?", (row["employee_id"],))
        return build_manifest(
            operation=OP_PAY,
            subject_type=PAYMENT_SUBJECT,
            subject_id=payment_id,
            actor_role=actor_role,
            amounts={"amount": p["amount"], "claim_outstanding": self._outstanding_row(row)},
            bindings={
                "payment_version": p["version"],
                "claim_id": row["id"],
                "claim_version": row["version"],
                "claim_hash": row["content_hash"],
                "claim_status": row["status"],
                "project_id": row["project_id"],
                "employee_id": row["employee_id"],
                "destination_verified": bool(employee["destination_verified"]),
                "funding_source": "operating-bank-simulated",
                "posting_rule": POSTING_RULE,
            },
            destination={"party_id": employee["id"], "destination": employee["destination"], "destination_version": employee["destination_version"]},
        )

    def _bill_manifest(self, billing_id: str, *, actor_role: str) -> dict[str, Any]:
        b = self.billing(billing_id)
        if b["status"] != "draft":
            raise ReimbursementError(f"billing {billing_id} is {b['status']}, not draft")
        row = self._claim_row(b["claim_id"])
        return build_manifest(
            operation=OP_BILL,
            subject_type=BILLING_SUBJECT,
            subject_id=billing_id,
            actor_role=actor_role,
            amounts={"amount": b["amount"], "claim_amount": row["amount"], "billed_before": self._billed_total(row["id"], include_drafts=False)},
            bindings={
                "billing_version": b["version"],
                "claim_id": row["id"],
                "claim_version": row["version"],
                "claim_hash": row["content_hash"],
                "billable": bool(row["billable"]),
                "project_id": row["project_id"],
                "customer_id": b["customer_id"],
                "receipt_hash": row["receipt_hash"],
                "recognition_policy": "fixture: reimbursable expense billed = earned (SHADOW)",
                "posting_rule": POSTING_RULE,
            },
        )

    def _check_voidable(self, row: dict[str, Any]) -> None:
        """A void unwinds an approval nobody has acted on: the claim must still be
        plainly approved, with no booked payment and nothing billed to the customer."""
        if row["status"] != "approved":
            raise ReimbursementError(f"claim {row['id']} is {row['status']}; only approved claims with nothing paid or billed can be voided")
        booked = self._booked_total(row["id"])
        if booked != ZERO:
            raise ReimbursementError(f"claim {row['id']} has {fmt(booked)} of booked payments; a settled claim cannot be voided")
        billed = self._billed_total(row["id"], include_drafts=False)
        if billed != ZERO:
            raise ReimbursementError(f"claim {row['id']} has {fmt(billed)} billed to the customer; a billed claim cannot be voided")
        if not row["journal_id"]:
            raise ReimbursementError(f"claim {row['id']} has no approval journal to reverse")

    def _void_manifest(self, claim_id: str, *, actor_role: str) -> dict[str, Any]:
        row = self._claim_row(claim_id)
        self._check_voidable(row)
        return build_manifest(
            operation=OP_VOID,
            subject_type=CLAIM_SUBJECT,
            subject_id=claim_id,
            actor_role=actor_role,
            amounts={
                "amount": row["amount"],
                "booked_payments": self._booked_total(claim_id),
                "posted_billings": self._billed_total(claim_id, include_drafts=False),
            },
            bindings={
                "claim_version": row["version"],
                "claim_hash": row["content_hash"],
                "claim_status": row["status"],
                "journal_id": row["journal_id"],
                "approval_id": row["approval_id"],
                "project_id": row["project_id"],
                "employee_id": row["employee_id"],
                "receipt_hash": row["receipt_hash"],
                "posting_rule": POSTING_RULE,
            },
        )

    # ---- approvals: execution --------------------------------------------------- #

    def apply(self, operation: str, subject_id: str, *, approval_id: str, manifest: dict[str, Any], actor: str, period_id: str | None) -> dict[str, Any]:
        pid = period_id or self.c.current_period()["id"]
        if operation == OP_APPROVE:
            return self._apply_approve(subject_id, approval_id=approval_id, actor=actor, period_id=pid)
        if operation == OP_PAY:
            return self._apply_pay(subject_id, approval_id=approval_id, actor=actor, period_id=pid)
        if operation == OP_BILL:
            return self._apply_bill(subject_id, approval_id=approval_id, actor=actor, period_id=pid)
        if operation == OP_VOID:
            return self._apply_void(subject_id, approval_id=approval_id, actor=actor, period_id=pid)
        raise ReimbursementError(f"unknown reimbursement operation {operation}")

    def _apply_approve(self, claim_id: str, *, approval_id: str, actor: str, period_id: str) -> dict[str, Any]:
        with self.db.transaction() as conn:
            row = self._claim_row(claim_id)
            if row["status"] != "submitted":
                raise ReimbursementError(f"claim {claim_id} is {row['status']}, not submitted")
            self.ledger.require_open(period_id)
            amt = money(row["amount"])
            j = self.ledger.post(
                period_id=period_id,
                description=f"Reimbursement claim approved: {row['description']}",
                lines=[
                    {"account": "5100", "debit": amt, "project_id": row["project_id"], "party_id": row["employee_id"], "memo": f"receipt {row['receipt_hash']}"},
                    {"account": "2100", "credit": amt, "project_id": row["project_id"], "party_id": row["employee_id"], "memo": "owed to employee"},
                ],
                source_type=CLAIM_SUBJECT, source_id=claim_id, source_version=str(row["version"]), posted_by=actor, approval_id=approval_id,
            )
            now = utcnow_iso()
            conn.execute(
                "UPDATE reimbursement_claims SET status='approved', approval_id=?, journal_id=?, period_id=?, approved_at=?, updated_at=? WHERE id=?",
                (approval_id, j["id"], period_id, now, now, claim_id),
            )
            # any other approval still open on this claim was for a state that no longer exists
            self.approvals.invalidate_for_subject(CLAIM_SUBJECT, claim_id, reason="claim already approved", actor=actor)
            self.audit.record(actor, "reimbursement.approved", CLAIM_SUBJECT, claim_id, {"approval_id": approval_id, "journal_id": j["id"], "amount": fmt(amt), "period_id": period_id, "employee_id": row["employee_id"]})
        return {"claim": claim_id, "status": "approved", "journal_id": j["id"], "amount": fmt(amt), "period_id": period_id}

    def _apply_pay(self, payment_id: str, *, approval_id: str, actor: str, period_id: str) -> dict[str, Any]:
        with self.db.transaction() as conn:
            p = self.payment(payment_id)
            if p["status"] != "draft":
                raise ReimbursementError(f"payment {payment_id} is {p['status']}, not draft")
            row = self._claim_row(p["claim_id"])
            if row["status"] not in PAYABLE_STATES:
                raise ReimbursementError(f"claim {row['id']} is {row['status']}; nothing is payable")
            outstanding = self._outstanding_row(row)
            amt = money(p["amount"])
            if amt > outstanding:
                raise ReimbursementError(f"payment {fmt(amt)} exceeds the outstanding balance {fmt(outstanding)} on claim {row['id']}")
            self.ledger.require_open(period_id)
            j = self.ledger.post(
                period_id=period_id,
                description=f"Reimbursement paid to employee on claim {row['id']}",
                lines=[
                    {"account": "2100", "debit": amt, "project_id": row["project_id"], "party_id": row["employee_id"], "memo": "employee payable settled"},
                    {"account": "1000", "credit": amt, "project_id": row["project_id"], "party_id": row["employee_id"], "memo": "bank disbursement (simulated)"},
                ],
                source_type=PAYMENT_SUBJECT, source_id=payment_id, source_version=str(p["version"]), posted_by=actor, approval_id=approval_id,
            )
            now = utcnow_iso()
            conn.execute(
                "UPDATE reimbursement_payments SET status='booked', approval_id=?, journal_id=?, period_id=?, booked_at=? WHERE id=?",
                (approval_id, j["id"], period_id, now, payment_id),
            )
            remaining = money(outstanding - amt)
            claim_status = "paid" if remaining == ZERO else "partially_paid"
            conn.execute("UPDATE reimbursement_claims SET status=?, updated_at=? WHERE id=?", (claim_status, now, row["id"]))
            # a duplicate approval on this payment would now describe a state that no longer exists,
            # and so would an open void of the claim: money has moved
            self.approvals.invalidate_for_subject(PAYMENT_SUBJECT, payment_id, reason="payment already booked", actor=actor)
            self.approvals.invalidate_for_subject(CLAIM_SUBJECT, row["id"], reason=f"payment {payment_id} booked against the claim", actor=actor)
            self.audit.record(actor, "reimbursement.payment_booked", PAYMENT_SUBJECT, payment_id, {"claim_id": row["id"], "approval_id": approval_id, "journal_id": j["id"], "amount": fmt(amt), "outstanding_after": fmt(remaining), "claim_status": claim_status, "period_id": period_id})
        return {"payment": payment_id, "claim": row["id"], "status": "booked", "claim_status": claim_status, "amount": fmt(amt), "outstanding": fmt(remaining), "journal_id": j["id"], "period_id": period_id}

    def _apply_bill(self, billing_id: str, *, approval_id: str, actor: str, period_id: str) -> dict[str, Any]:
        with self.db.transaction() as conn:
            b = self.billing(billing_id)
            if b["status"] != "draft":
                raise ReimbursementError(f"billing {billing_id} is {b['status']}, not draft")
            row = self._claim_row(b["claim_id"])
            if not row["billable"]:
                raise ReimbursementError(f"claim {row['id']} is not billable to the customer")
            if row["status"] not in APPROVED_STATES:
                raise ReimbursementError(f"claim {row['id']} is {row['status']}; only approved claims can be billed")
            amt = money(b["amount"])
            billed = self._billed_total(row["id"], include_drafts=False)
            if money(billed + amt) > money(row["amount"]):
                raise ReimbursementError(f"billing {fmt(amt)} would exceed the claim amount {row['amount']} (already billed {fmt(billed)})")
            self.ledger.require_open(period_id)
            j = self.ledger.post(
                period_id=period_id,
                description=f"Reimbursable expense billed to customer on claim {row['id']}",
                lines=[
                    {"account": "1100", "debit": amt, "project_id": row["project_id"], "party_id": b["customer_id"], "memo": f"reimbursable: {row['description']}"},
                    {"account": "4000", "credit": amt, "project_id": row["project_id"], "party_id": b["customer_id"], "memo": "reimbursable expense billed (fixture policy)"},
                ],
                source_type=BILLING_SUBJECT, source_id=billing_id, source_version=str(b["version"]), posted_by=actor, approval_id=approval_id,
            )
            conn.execute(
                "UPDATE reimbursement_billings SET status='billed', approval_id=?, journal_id=?, period_id=?, billed_at=? WHERE id=?",
                (approval_id, j["id"], period_id, utcnow_iso(), billing_id),
            )
            self.approvals.invalidate_for_subject(BILLING_SUBJECT, billing_id, reason="billing already posted", actor=actor)
            # a billed claim can no longer be voided; drop any open void approval on it
            self.approvals.invalidate_for_subject(CLAIM_SUBJECT, row["id"], reason=f"billing {billing_id} posted against the claim", actor=actor)
            self.audit.record(actor, "reimbursement.billed", BILLING_SUBJECT, billing_id, {"claim_id": row["id"], "customer_id": b["customer_id"], "approval_id": approval_id, "journal_id": j["id"], "amount": fmt(amt), "period_id": period_id})
        return {"billing": billing_id, "claim": row["id"], "status": "billed", "amount": fmt(amt), "customer_id": b["customer_id"], "journal_id": j["id"], "period_id": period_id}

    def _apply_void(self, claim_id: str, *, approval_id: str, actor: str, period_id: str) -> dict[str, Any]:
        """Reverse the approval journal and retire the claim.  Draft payments and
        billings on it are canceled; booked or billed ones block the void."""
        with self.db.transaction() as conn:
            row = self._claim_row(claim_id)
            self._check_voidable(row)
            self.ledger.require_open(period_id)
            canceled_payments = []
            for p in self.db.query("SELECT * FROM reimbursement_payments WHERE claim_id=? AND status='draft' ORDER BY created_at, id", (claim_id,)):
                self._cancel_draft_payment(p, actor=actor, reason=f"claim {claim_id} voided")
                canceled_payments.append(p["id"])
            canceled_billings = []
            for b in self.db.query("SELECT * FROM reimbursement_billings WHERE claim_id=? AND status='draft' ORDER BY created_at, id", (claim_id,)):
                self._cancel_draft_billing(b, actor=actor, reason=f"claim {claim_id} voided")
                canceled_billings.append(b["id"])
            j = self.ledger.reverse(row["journal_id"], period_id=period_id, posted_by=actor, reason=f"reimbursement claim {claim_id} voided", approval_id=approval_id)
            now = utcnow_iso()
            conn.execute(
                "UPDATE reimbursement_claims SET status='voided', void_approval_id=?, reversal_journal_id=?, voided_at=?, updated_at=? WHERE id=?",
                (approval_id, j["id"], now, now, claim_id),
            )
            self.approvals.invalidate_for_subject(CLAIM_SUBJECT, claim_id, reason="claim voided", actor=actor)
            self.audit.record(actor, "reimbursement.voided", CLAIM_SUBJECT, claim_id, {
                "approval_id": approval_id, "reversed_journal_id": row["journal_id"], "reversal_journal_id": j["id"], "amount": row["amount"],
                "period_id": period_id, "employee_id": row["employee_id"], "receipt_hash": row["receipt_hash"],
                "payments_canceled": canceled_payments, "billings_canceled": canceled_billings,
            })
        return {
            "claim": claim_id, "status": "voided", "amount": row["amount"], "reversed_journal_id": row["journal_id"], "reversal_journal_id": j["id"],
            "period_id": period_id, "payments_canceled": canceled_payments, "billings_canceled": canceled_billings,
        }

    # ---- subledger and state ------------------------------------------------------ #

    def employee_payable_reconciliation(self, project_id: str) -> dict[str, Any]:
        """Outstanding on approved / partially paid claims against the 2100 control account."""
        items = []
        subledger = ZERO
        rows = self.db.query(
            "SELECT * FROM reimbursement_claims WHERE project_id=? AND status IN ('approved','partially_paid') ORDER BY created_at, id",
            (project_id,),
        )
        for row in rows:
            outstanding = self._outstanding_row(row)
            items.append({"claim_id": row["id"], "employee_id": row["employee_id"], "status": row["status"], "amount": row["amount"], "paid": fmt(self._booked_total(row["id"])), "outstanding": fmt(outstanding)})
            subledger += outstanding
        control = self.ledger.balance("2100", project_id=project_id)
        return {"items": items, "subledger_total": fmt(subledger), "control_balance": fmt(control), "reconciled": money(subledger) == control}

    def state(self, project_id: str) -> dict[str, Any]:
        return {
            "claims": self.claims(project_id),
            "payments": self.payments(project_id),
            "billings": self.billings(project_id),
            "reconciliation": self.employee_payable_reconciliation(project_id),
        }

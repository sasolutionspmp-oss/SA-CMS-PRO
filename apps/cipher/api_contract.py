"""Versioned presenters for the isolated synthetic practice read application.

This library accepts an existing Cipher; it never opens, migrates or seeds a
workspace. The practice server owns and freezes its in-memory synthetic fixture.
Project filters are browsing filters, not authenticated read permissions. This
contract must not be mounted on a live workspace or the legacy console.

Responses contain only named economic/display fields. A manifest is read privately
to check a supported approval's scope; it never leaves the presenter. Supplier-bill
business approval is journal-free; a distinct authorized person posts the approved bill. This practice milestone supplies no command actions.
"""
from __future__ import annotations

import base64
import binascii
import json
from typing import TYPE_CHECKING, Any, Literal, TypedDict

from .core.ids import canonical_json, hash_json, loads
from .core.money import MoneyError, money, rate

if TYPE_CHECKING:
    from .service import Cipher


CONTRACT_VERSION = "cipher.practice-read.v1"
COLLECTIONS = ("projects", "commitments", "bills", "approvals")
MAX_TOP = 100
MAX_SEARCH = 200
MAX_CURSOR = 1024
MAX_SAFE_INTEGER = (1 << 53) - 1

Collection = Literal["projects", "commitments", "bills", "approvals"]


class RefusalValue(TypedDict):
    code: str
    target: str
    message: str


class PracticeReadRefusal(ValueError):
    """A safe typed refusal; no untrusted query value is echoed in its message."""

    def __init__(self, code: str, target: str, message: str):
        self.code, self.target, self.message = code, target, message
        self.value: RefusalValue = {"code": code, "target": target, "message": message}
        super().__init__(message)


class ProjectRead(TypedDict):
    id: str
    name: str
    entity: str
    currency: Literal["USD"]
    customerName: str | None
    budgetCents: int


class CommitmentRead(TypedDict):
    id: str
    projectId: str
    projectName: str
    supplierId: str
    supplierName: str
    title: str
    status: str
    version: int
    originalAmountCents: int
    executedAmountCents: int
    retainageRateMicros: int


class BillRead(TypedDict):
    id: str
    projectId: str
    projectName: str
    commitmentId: str
    commitmentTitle: str
    supplierName: str
    sequence: int
    displayName: str
    status: str
    periodId: str
    periodLabel: str
    amountDueCents: int
    currentDueCents: int
    retainageCents: int
    thisPeriodCents: int
    journalId: str | None


class ApprovalRead(TypedDict):
    id: str
    projectId: str
    projectName: str
    operation: str
    subjectType: str
    subjectId: str
    subjectLabel: str
    title: str
    status: str
    requestedByName: str
    requestedAt: str
    expiresAt: str
    amountCents: int | None


class StatusFacet(TypedDict):
    value: str
    count: int


class Facets(TypedDict):
    statuses: list[StatusFacet]


class PracticeReadEnvelope(TypedDict):
    contractVersion: str
    mode: Literal["practice"]
    synthetic: Literal[True]
    currency: Literal["USD"]
    collection: Collection
    projectId: str | None
    value: list[ProjectRead | CommitmentRead | BillRead | ApprovalRead]
    count: int
    nextCursor: str | None
    facets: Facets
    totals: dict[str, int]


class PracticeCapabilities(TypedDict):
    billApprovalEffect: Literal["journal_free_business_approval"]
    separateBillApprovalAndPosting: Literal[True]
    authenticatedReadPermissions: Literal[False]
    commands: Literal[False]
    unsupportedApprovalScopesExcluded: Literal[True]


class PracticeContractSnapshot(TypedDict):
    contractVersion: str
    mode: Literal["practice"]
    synthetic: Literal[True]
    currency: Literal["USD"]
    readOnly: Literal[True]
    collections: list[Collection]
    capabilities: PracticeCapabilities
    limits: dict[str, int]
    pagination: str


_STATUSES = {
    "projects": (),
    "commitments": ("draft", "approved", "executed", "closed"),
    "bills": ("draft", "approved", "posted", "paid", "void", "corrected"),
    "approvals": ("pending", "granted", "consumed", "expired", "invalidated"),
}
_APPROVAL_SUBJECTS = {
    "estimate.approve": "estimate", "commitment.execute": "commitment", "change.execute": "change",
    "bill.approve": "bill", "payment.release": "bill", "prime_bill.approve": "prime_bill",
    "retainage.release": "commitment", "payment.release_retainage": "commitment",
}
_OPERATION_LABELS = {
    "estimate.approve": "Estimate approval", "commitment.execute": "Commitment execution",
    "change.execute": "Change execution", "bill.approve": "Bill business approval",
    "payment.release": "Simulated payment release", "prime_bill.approve": "Owner bill approval and posting",
    "retainage.release": "Retainage release", "payment.release_retainage": "Simulated retainage payment release",
}
_APPROVAL_AMOUNT_KEYS = {
    "estimate.approve": "total", "commitment.execute": "total", "change.execute": "change",
    "bill.approve": "amount_due", "prime_bill.approve": "amount_due", "payment.release": "amount",
    "retainage.release": "retainage_held", "payment.release_retainage": "amount",
}

# Explicit SELECT lists keep full party and workspace records out of presenters.
_QUERIES = {
    "projects": """SELECT p.id, p.name, p.entity, p.currency, p.budget, p.created_at, customer.name AS customer_name
                   FROM projects p LEFT JOIN parties customer ON customer.id=p.customer_id""",
    "commitments": """SELECT c.id, c.project_id, c.supplier_id, c.title, c.status, c.version,
                       c.original_amount, c.executed_amount, c.retainage_rate, c.created_at,
                       p.name AS project_name, p.currency, supplier.name AS supplier_name
                       FROM commitments c JOIN projects p ON p.id=c.project_id JOIN parties supplier ON supplier.id=c.supplier_id""",
    "bills": """SELECT b.id, b.commitment_id, b.sequence, b.status, b.period_id, b.amount_due,
                 b.retainage_this_period, b.installed_this_period, b.stored_added_this_period,
                 b.stored_transferred_this_period, b.journal_id, b.created_at,
                 c.project_id, c.title AS commitment_title, p.name AS project_name, p.currency,
                 supplier.name AS supplier_name, period.name AS period_label
                 FROM bills b JOIN commitments c ON c.id=b.commitment_id JOIN projects p ON p.id=c.project_id
                 JOIN parties supplier ON supplier.id=c.supplier_id JOIN periods period ON period.id=b.period_id""",
    "approvals": """SELECT a.id, a.operation, a.subject_type, a.subject_id, a.status, a.requested_by,
                     a.requested_at AS created_at, a.expires_at, a.manifest_json,
                     p.id AS project_id, p.name AS project_name, p.currency,
                     b.sequence AS bill_sequence, c.title AS commitment_title, pb.sequence AS prime_bill_sequence
                     FROM approvals a
                     LEFT JOIN bills b ON a.subject_type='bill' AND b.id=a.subject_id
                     LEFT JOIN commitments bc ON bc.id=b.commitment_id
                     LEFT JOIN commitments c ON a.subject_type='commitment' AND c.id=a.subject_id
                     LEFT JOIN estimates e ON a.subject_type='estimate' AND e.id=a.subject_id
                     LEFT JOIN changes ch ON a.subject_type='change' AND ch.id=a.subject_id
                     LEFT JOIN commitments cc ON cc.id=ch.commitment_id
                     LEFT JOIN prime_bills pb ON a.subject_type='prime_bill' AND pb.id=a.subject_id
                     LEFT JOIN projects p ON p.id=COALESCE(bc.project_id,c.project_id,e.project_id,cc.project_id,pb.project_id)""",
}


def contract_snapshot(cipher: Cipher) -> PracticeContractSnapshot:
    """Describe the practice subset without changing workspace state."""
    _require_practice(cipher)
    return {
        "contractVersion": CONTRACT_VERSION, "mode": "practice", "synthetic": True, "currency": "USD", "readOnly": True,
        "collections": list(COLLECTIONS),
        "capabilities": {"billApprovalEffect": "journal_free_business_approval", "separateBillApprovalAndPosting": True,
                         "authenticatedReadPermissions": False, "commands": False, "unsupportedApprovalScopesExcluded": True},
        "limits": {"maxTop": MAX_TOP, "maxSearchLength": MAX_SEARCH, "maxCursorLength": MAX_CURSOR,
                   "maxIntegerCents": MAX_SAFE_INTEGER},
        "pagination": "Stable created-time and ID order on the frozen practice fixture; totals cover every filtered row.",
    }


def _refuse(code: str, target: str, message: str) -> None:
    raise PracticeReadRefusal(code, target, message)


def _require_practice(cipher: Cipher) -> None:
    # Inspect the actual connections, rather than relabeling a supplied file path.
    databases = cipher.db.query("PRAGMA database_list")
    if not databases or any(database["file"] for database in databases):
        _refuse("unsupported_workspace", "workspace", "Practice reads require the isolated in-memory synthetic fixture.")


def _cents(value: Any) -> int:
    try:
        result = int(money(value) * 100)
    except MoneyError:
        _refuse("invalid_record", "money", "A stored amount cannot be presented as exact cents.")
    if abs(result) > MAX_SAFE_INTEGER:
        _refuse("amount_out_of_range", "money", "The amount exceeds the practice client's exact integer range.")
    return result


def _validate(collection: Any, project_id: Any, status: Any, search: Any, top: Any, cursor: Any) -> str | None:
    if not isinstance(collection, str) or collection not in COLLECTIONS:
        _refuse("unknown_collection", "collection", "Choose a supported practice collection.")
    if type(top) is not int or not 1 <= top <= MAX_TOP:
        _refuse("invalid_query", "top", "Page size must be an integer from 1 through 100.")
    if project_id is not None and (not isinstance(project_id, str) or not project_id or len(project_id) > 200
                                  or project_id != project_id.strip() or any(ord(ch) < 32 for ch in project_id)):
        _refuse("invalid_query", "projectId", "Choose a valid practice project ID.")
    if status is not None and (not isinstance(status, str) or status not in _STATUSES[collection]):
        _refuse("invalid_query", "status", "Choose a supported status for this collection.")
    if search is not None and (not isinstance(search, str) or len(search) > MAX_SEARCH or any(ord(ch) < 32 for ch in search)):
        _refuse("invalid_query", "search", "Search must be text of at most 200 characters without control characters.")
    if cursor is not None and (not isinstance(cursor, str) or not cursor or len(cursor) > MAX_CURSOR):
        _refuse("invalid_query", "cursor", "Choose a valid practice paging cursor.")
    return search.strip().casefold() or None if search is not None else None


def _offset(cursor: str | None, query_hash: str) -> int:
    if cursor is None:
        return 0
    try:
        decoded = base64.b64decode(cursor + "=" * (-len(cursor) % 4), altchars=b"-_", validate=True)
        token = json.loads(decoded)
        if (not isinstance(token, dict) or set(token) != {"version", "offset", "query"} or type(token["version"]) is not int or token["version"] != 1
                or type(token["offset"]) is not int or not 0 <= token["offset"] <= MAX_SAFE_INTEGER
                or token["query"] != query_hash):
            raise ValueError
        return token["offset"]
    except (ValueError, UnicodeError, binascii.Error):
        _refuse("invalid_cursor", "cursor", "The cursor does not match this practice query.")


def _cursor(offset: int, query_hash: str) -> str:
    token = {"version": 1, "offset": offset, "query": query_hash}
    return base64.urlsafe_b64encode(canonical_json(token).encode("utf-8")).decode("ascii").rstrip("=")


def _scoped_approval(row: dict[str, Any]) -> dict[str, Any] | None:
    """Derive known single-job scope from the subject, never from a client claim."""
    if _APPROVAL_SUBJECTS.get(row["operation"]) != row["subject_type"] or row["project_id"] is None:
        return None
    try:
        manifest = loads(row["manifest_json"])
        if not isinstance(manifest, dict) or manifest.get("operation") != row["operation"]:
            return None
        if manifest.get("subject") != {"type": row["subject_type"], "id": row["subject_id"]}:
            return None
        bindings = manifest.get("bindings") or {}
        if not isinstance(bindings, dict) or ("project_id" in bindings and bindings["project_id"] != row["project_id"]):
            return None
        amounts = manifest.get("amounts") or {}
        if not isinstance(amounts, dict):
            return None
        # Only the operation's named primary amount is presented; arbitrary keys stay private.
        row["presented_amount"] = amounts.get(_APPROVAL_AMOUNT_KEYS[row["operation"]])
        return row
    except (ValueError, TypeError):
        return None


def _present(cipher: Cipher, collection: str, row: dict[str, Any]) -> dict[str, Any]:
    if row["currency"] != "USD":
        _refuse("unsupported_currency", "currency", "This practice contract supports USD records only.")
    if collection == "projects":
        return {"id": row["id"], "name": row["name"], "entity": row["entity"], "currency": "USD",
                "customerName": row["customer_name"], "budgetCents": _cents(row["budget"])}
    if collection == "commitments":
        return {"id": row["id"], "projectId": row["project_id"], "projectName": row["project_name"],
                "supplierId": row["supplier_id"], "supplierName": row["supplier_name"], "title": row["title"],
                "status": row["status"], "version": row["version"], "originalAmountCents": _cents(row["original_amount"]),
                "executedAmountCents": _cents(row["executed_amount"]), "retainageRateMicros": int(rate(row["retainage_rate"]) * 1_000_000)}
    if collection == "bills":
        installed = _cents(row["installed_this_period"])
        added, transferred = _cents(row["stored_added_this_period"]), _cents(row["stored_transferred_this_period"])
        return {"id": row["id"], "projectId": row["project_id"], "projectName": row["project_name"],
                "commitmentId": row["commitment_id"], "commitmentTitle": row["commitment_title"], "supplierName": row["supplier_name"],
                "sequence": row["sequence"], "displayName": f"Bill {row['sequence']}", "status": row["status"],
                "periodId": row["period_id"], "periodLabel": row["period_label"], "amountDueCents": _cents(row["amount_due"]),
                "currentDueCents": _cents(cipher.bills.open_payable(row["id"])), "retainageCents": _cents(row["retainage_this_period"]),
                "thisPeriodCents": installed + added - transferred, "journalId": row["journal_id"]}
    labels = {"bill": f"Bill {row['bill_sequence']}", "commitment": row["commitment_title"],
              "prime_bill": f"Owner bill {row['prime_bill_sequence']}", "estimate": "Estimate", "change": "Commitment change"}
    label = labels[row["subject_type"]]
    return {"id": row["id"], "projectId": row["project_id"], "projectName": row["project_name"],
            "operation": row["operation"], "subjectType": row["subject_type"], "subjectId": row["subject_id"],
            "subjectLabel": label, "title": f"{_OPERATION_LABELS[row['operation']]}: {label}", "status": row["status"],
            "requestedByName": row["requested_by"], "requestedAt": row["created_at"], "expiresAt": row["expires_at"],
            "amountCents": _cents(row["presented_amount"]) if row["presented_amount"] is not None else None}


def _totals(collection: str, values: list[dict[str, Any]]) -> dict[str, int]:
    if collection == "projects":
        result = {"budgetCents": sum(row["budgetCents"] for row in values)}
    elif collection == "commitments":
        result = {"committedCents": sum(row["executedAmountCents"] for row in values if row["status"] in ("executed", "closed")),
                  "originalAmountCents": sum(row["originalAmountCents"] for row in values)}
    elif collection == "bills":
        result = {"currentDueCents": sum(row["currentDueCents"] for row in values),
                  "amountDueCents": sum(row["amountDueCents"] for row in values if row["status"] not in ("void", "corrected"))}
    else:
        # Approvals can authorize different kinds of economic effects; summing them
        # would imply a single payable balance that the domain does not define.
        result = {}
    if any(abs(value) > MAX_SAFE_INTEGER for value in result.values()):
        _refuse("amount_out_of_range", "totals", "The total exceeds the practice client's exact integer range.")
    return result


def practice_read(cipher: Cipher, collection: Collection, *, project_id: str | None = None, status: str | None = None,
                  search: str | None = None, top: int = 50, cursor: str | None = None) -> PracticeReadEnvelope:
    """Return one bounded page and aggregates over the same filtered practice rows.

    The practice fixture is intentionally small and frozen by its server. This
    scaffold makes no production scalability or authenticated permission claim.
    Cursors bind collection, filters and page size; they carry no authority.
    """
    search = _validate(collection, project_id, status, search, top, cursor)
    query_hash = hash_json({"collection": collection, "projectId": project_id, "status": status, "search": search, "top": top})
    offset = _offset(cursor, query_hash)
    _require_practice(cipher)
    if project_id is not None and cipher.db.one("SELECT id FROM projects WHERE id=?", (project_id,)) is None:
        _refuse("unknown_project", "projectId", "Choose an existing practice project.")
    rows = cipher.db.query(_QUERIES[collection])
    if collection == "approvals":
        rows = [scoped for row in rows if (scoped := _scoped_approval(row)) is not None]
    if project_id is not None:
        rows = [row for row in rows if (row["id"] if collection == "projects" else row["project_id"]) == project_id]
    if status is not None:
        rows = [row for row in rows if row["status"] == status]
    rows.sort(key=lambda row: (row["created_at"], row["id"]))
    values = [_present(cipher, collection, row) for row in rows]
    if search is not None:
        search_fields = ("name", "entity", "customerName", "title", "supplierName", "projectName", "commitmentTitle", "displayName", "subjectLabel")
        values = [row for row in values if any(search in str(row.get(key) or "").casefold() for key in search_fields)]
    count = len(values)
    if offset > count:
        _refuse("invalid_cursor", "cursor", "The cursor is beyond this practice query's results.")
    status_counts: dict[str, int] = {}
    for row in values:
        if "status" in row:
            status_counts[row["status"]] = status_counts.get(row["status"], 0) + 1
    next_cursor = _cursor(offset + top, query_hash) if offset + top < count else None
    return {"contractVersion": CONTRACT_VERSION, "mode": "practice", "synthetic": True, "currency": "USD",
            "collection": collection, "projectId": project_id, "value": values[offset:offset + top], "count": count,
            "nextCursor": next_cursor, "facets": {"statuses": [{"value": key, "count": value} for key, value in sorted(status_counts.items())]},
            "totals": _totals(collection, values)}

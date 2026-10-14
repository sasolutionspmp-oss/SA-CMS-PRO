# Fluent AP exception and correction workflows

This extends [AP_PRACTICE.md](AP_PRACTICE.md) in the same disposable installed-work application. The existing registered accountant, reviewer and PM perform the work; no additional identity, provider or file-workspace selector is introduced.

Build the AP entry and start `python -m apps.cipher ap-practice-web --port 8767`. All records and receipts are synthetic and in memory. The original read application remains separate.

## Invoice recovery

Open an invoice's exception review as an authorized accountant. A revision supplies the invoice number, date, exact amount, owned evidence revision and reason. The server derives the supplier, project, next source version, due-date behavior and affected approvals. It shows the proposed changes before applying them. The invoice then requires fresh matching and approval. A previous bill business grant can remain stored as granted while its material facts are stale; posting refuses it. Applying a freshly approved match invalidates the previous business grant and leads to a new PM review.

A possible duplicate needs a documented review before match approval. Number-key, amount or invoice-date changes reset that review; evidence-only and due-date revisions preserve a valid review. A confirmed duplicate or unowed received invoice can be finally rejected with a reason. Its normalized number remains reserved, and only verified rejection releases the document for reuse. Historical states and reasons remain available.

Invoice revision or rejection attached to a posted or paid bill requires its governed bill correction first. Metadata edits do not change journals, payables or the original issued source snapshot. Rejection, duplicate review and revision use current project duty and read-only preflight, followed by an explicit reviewed action.

## Unposted bills and posted corrections

An authorized accountant cancels a draft with a reason. An approved, unposted bill is withdrawn by its original business approver while that person still holds the required project authority. Both retain history and create no journal. A replacement is separately certified and reviewed; the old sequence and receipts stay intact.

For an eligible posted unpaid bill, prepare a correction reason and request `bill.correct` approval. Change to the separate accountant reviewer to inspect the source and exact proposed reversal, then grant it. An authorized accountant explicitly selects an eligible open period and executes the correction. The reversal period cannot precede the original actual posting period. The corrected bill, original posting receipt, consumed correction authorization and exact reversal journals remain traceable.

The domain refuses paid bills, active or paid payment intents, live credits, cumulative successors and closed commitments. Genuine canceled credits and terminal failed/returned/canceled payment histories retain their existing eligibility semantics. Read and source checks reconcile correction requests with audited preparation history, so deletion or reordering cannot conceal a request or make a false corrected status release an invoice.

After the reversal, prepare a new certified bill, revise the supplier invoice if needed, compute and independently approve the match, and complete a fresh PM business grant and accountant posting. Correction and replacement are distinct acts. The interface identifies the reversal as a working-ledger change; it is not a QuickBooks acknowledgement or payment.

## Fixed transport and original outcomes

Eight additional fixed actions extend the nine installed-work AP actions:

| Action | Reviewed body | Resource |
|---|---|---|
| `invoice.revise` | reason, invoiceNumber, invoiceDate, amountCents, evidenceRevisionId | invoice |
| `invoice.reject` | reason | invoice |
| `invoice.reviewDuplicate` | reason | invoice |
| `bill.cancel` | reason | bill |
| `bill.prepareCorrection` | reason | bill |
| `bill.requestCorrection` | empty | bill |
| `bill.approveCorrection` | empty | correction approval |
| `bill.executeCorrection` | periodId | correction approval |

Each applied body also carries its reviewed fingerprint, record version and repeatability UUID. Current person, project scope and duties are checked before receipt disclosure. An exact retry returns its original audited result after legitimate later revisions, rejection, cancellation, correction or replacement; new reviewed facts require a new action. The client keeps the original body/UUID in memory across navigation within that person's scope. It never retries a command automatically.

Shared pure checks calculate eligibility and effects without SQL writes. Domain actions and the whole correction command use savepoints so a caught outer failure cannot preserve partial invalidations, consumption, reversal or command bookkeeping. The API admits only the intended reviewed row/audit changes. These fixed actions do not call payment providers.

Appended schema 69 expands the receipt action allowlist while preserving schemas 1–68. Genuine original nine-action schema-68 receipts retain their bytes, hashes, bindings and sources after upgrade; failed later migration rolls back the expansion. Copied workspaces remain physically read-only.

Document upload, PO/stored-material exceptions, supplier credit screens, payment delivery, real staff identity and qualified accounting integration remain later work in [DELIVERY_BACKLOG.md](DELIVERY_BACKLOG.md). The full ERP and enterprise acceptance gates remain open.

The subsequent [practice accounting handoff](ACCOUNTING_PRACTICE.md) preserves the
original posting obligation after legitimate correction. It can look up or read
back a prior simulated delivery without submitting it again. The first route has
no inverse or credit delivery; close checks keep those adjustments unresolved in
their actual reversal/credit periods even when the original was reconciled.

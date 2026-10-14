# Practice accounting handoff, schemas 70 and 71

This backend route does not contact QuickBooks or adopt a production accounting policy.
The only route is `practice.simulated-journal-entry.v1` with adapter
`simulated-journal-entry/1`. The fixed date policy is
`synthetic.period-end.v1`: the end date of the **actual original posting period**,
proved against its original `period.opened` audit. This is explicitly synthetic.

## Original obligation

Admit a modern original `PostingReceipt` with one installed-work journal in USD.
Verify the bill's lifecycle, immutable posting receipt, business approval snapshot,
original journal and every exact line. Require no stored-material addition or
transfer. New preparation and submit also require an unpaid, uncredited source:
active payment intents, accepted/settled amounts and any draft/posted supplier
credit block this route even while the bill still says posted. Their complete
audited inventories are verified first. Genuine cancelled/failed/returned payment
histories and cancelled credit drafts do not block a truly unpaid source.

A plan contains the exact original this-period cost and liabilities:

| Original account | Obligation | Simulator line |
| --- | --- | --- |
| 5000 | installed_this_period | debit exact cents |
| 2000 | original amount_due | credit exact cents |
| 2050 | retainage_this_period | credit exact cents |

Omit zero lines and require `installed cost = net AP + retainage`. Never use
cumulative gross, current open payable, credits or payments to restate this
original obligation. The fixture's first bill is Dr5000 1,234,567 cents,
Cr2000 1,111,110 cents, Cr2050 123,457 cents. A November posting uses November 30,
even when its original certification period was October.

The payload binds source content/version, PostingReceipt ID/hash, original journal
ID, original business approval and record IDs, the original approved supplierInvoice
binding or explicit null, mapping ID/version/hash, adapter version, route, entity,
USD, period, synthetic effective-date policy and exact journal lines. Historical
supplier invoice facts come from the immutable business approval snapshot; current
invoice proof verifies genuine later history without replacing that snapshot.

Project/vendor references are fixed synthetic references. The existing original
journal does not contain full per-cost-code or cost-type dimensions. This first
route is an aggregate JournalEntry and cannot promise those dimensions or a
QuickBooks Bill. An unmatched modern original posting is allowed with explicit
null supplierInvoice. No invoice number, invoice date or missing dimensions are
invented.

## Registration and rows

`domain/accounting.py` has `DEFER_SCHEMA_REGISTRATION=True`. Import performs no schema
registration. `register_accounting_schema()` requires the complete 69-entry catalog
and appends `accounting_practice_delivery` at 70. Repeated registration of that
same entry is allowed after later appended entries. The service loader validates
the historical prefix, defers only this known module, then calls the registrar
after historical entries 64–69.
Earlier SQL/checksums/catalog positions remain unchanged.

All tables use a canonical body JSON, exact projected lookup/FK fields and an
audited full-row hash. Immutable tables refuse updates/deletes; births require the
original matching audit hash. Intent identity is immutable; each state change
requires an audited chronological complete state snapshot and increasing revision.
Pure reads verify exact trigger DDL, audit chain, full row/hash/source and original
audited birth inventory. Dropping/recreating a trigger does not let missing audited
rows disappear.

| Table | Purpose and uniqueness |
| --- | --- |
| accounting_mapping_versions | append audited fixed synthetic declarations; unique route/entity/version; previous-version chain |
| accounting_plans | immutable original payload; unique original journal/mapping version |
| accounting_intents | durable queue/outbox effect; one per plan and one per stable logical UUID |
| accounting_leases | private exclusive bounded worker reservations, 5–60 seconds |
| accounting_attempts | immutable numbered attempts; one per lease, bound payload hash and fixed purpose |
| accounting_attempt_results | one sanitized durable result per attempt |
| accounting_acceptances | one actual simulated acceptance per intent; unique stable simulator record ID |
| accounting_reconciliations | immutable independent readback checkpoint/exception per readback attempt |

The logical UUID is UUID5 of workspace ID, fixed route and **original journal ID**.
It does not change for retries, mapping versions or new API idempotency keys.
Mapping supersession can produce a new unqueued draft plan; once a source has an
intent it cannot receive another intent/UUID to hide an unknown or refused outcome.
Current source/mapping changes refuse a new submit. A legitimate corrected/paid
original stays readable historically. Recovery lookup/readback of an already
attempted original can record its original outcome; that permission cannot send
another journal or net the correction. Approved inverse handoffs and explicit
replacement linkage are future work, not inferred here.

Schema 71, `ap_practice_accounting_action_receipts`, adds the seven fixed accounting
actions to the receipt guard and stores `ap_accounting_invocations`. Existing receipt
rows retain their hashes and original audit anchors. A human invocation binds its
canonical person, repeatability UUID, fixed action, resource, typed body, original
record version and reviewed source before a worker attempt is committed. The
attempt preserves that invocation ID/hash and fixed action separately from its
provider phase. Claim and observation callbacks use the exact initialized,
factory-bound store; complete table/schema/audit deltas restrict their effects.
An observation commits with its immutable attempt/result/acceptance/readback,
while the human API receipt completes in a separate transaction. Retrying an
unfinished original invocation can only look up its original UUID; a fixed lookup
action cannot become a submit after a confirmed missing result.

The Fluent action panel preserves the completed original outcome. After confirmed
missing or unavailable readback, **Review next practice step** explicitly creates a
fresh review for the next permitted step. It keeps the same provider logical UUID;
an unfinished human invocation instead retains only its exact original retry.

## Approval and worker boundary

The only governed operation is `accounting.queue`, subject type `accounting_plan`.
Request, grant, execute and worker entry require an active registered human with
their **own actual project accountant grant and active membership**. Owner wildcard,
controller labels and delegations cannot manufacture that duty. The original
requester and reviewer must be distinct canonical persons. Existing people/governors
continue to apply; accounting binds no policy to unrelated operations. Queue apply
checks its exact consumed authorization and atomically creates only the stable
intent, with no provider call or ledger journal.

The first browser step explicitly invokes a separate initialized fixed simulator
worker as the **current calling accountant**. There is no invented worker identity,
unattended daemon, caller-selected provider, URL, realm, route or file workspace.
Claims, finishing and reconciliation require the private initialized worker
capability; acceptance and authoritative missing/readback results also require the
original pinned simulator's retained immutable record-store proof. Matching public
hashes alone cannot fabricate an acceptance. Lease tokens/capabilities remain
private and do not enter human DTOs or ordinary exports.

Claims/outcomes commit in separate transactions. Provider calls occur outside any
SQLite transaction. The memory-workspace authority/runtime lock spans exactly one
simulator call; file-workspace delivery is refused until a shared process reservation
exists. An unfinished or expired submit/unknown outcome forces bounded lookup of
the same UUID/hash. Confirmed missing requeues the same UUID for a **later tick**;
lookup never immediately resends. Simulated acceptance survives local finish/API
receipt failure in the independent record store. Readback is separate from delivery;
its failure preserves simulated acceptance and records a reconciliation exception.
Simulator acceptance is always marked practice/synthetic/simulation and
`quickBooksAccepted=False`.

## Pure contracts

- `preparation_preflight(bill_id, mapping_id, actor=...)` and `prepare(...)`.
- `current_mapping(project_id, actor=...)`, `mapping(id, current=...)`.
- `plan_scope`, `intent_scope`: minimal scope only; authorize before full proof/DTO.
- `plan`, `intent`, `plan_inventory`, `intent_inventory`, `approval_inventory`.
- `queue_preflight(plan_id)`, fixed `manifest_for`, `approval_proof`.
- `worker_preflight(intent_id, actor=..., purpose=delivery|lookup|reconciliation)`
  returns frozen plan/payload/hash/UUID/guard and exact derived provider phase.
- Private `claim_intent`, `delivery_preflight`, `delivery_boundary`,
  `finish_attempt`, `reconcile` use a bound initialized worker capability.

## Close/export and remaining integration

An empty plugin is inert and adopts no external accounting close policy. Audited
mapping/plan declaration activates its local synthetic entity scope. Close/export
then source-prove inventories, report eligible original posted sources without an
intent, pending/unknown/accepted-unreconciled/refused obligations, and unsupported
corrected/paid/extra-dimension sources requiring review. Missing declarations,
approvals, plans, acceptances or readbacks cannot restore an inert/green state.
Refused is not reconciled or a completed obligation. Automatic approved disposition,
live mapping adoption and correction/replacement handoffs remain unavailable.

An original October journal can be reconciled while its genuine November reversal
or supplier-credit journal still needs handoff. Close checks report that inverse
or credit in its own actual journal period, including its original source/journal
linkage. Original receipt period filtering cannot conceal it. Audited journal
births anchor period/source attribution, so missing journals or edited dates fail
source proof. A known original outcome can still be looked up after a credit,
payment or correction; that historical observation never authorizes a fresh submit
or silently nets the adjustment against the original.

The browser factory seeds a fixed synthetic mapping through an existing registered
accountant and binds its initialized simulator worker and API invocation store.
Seven fixed typed actions prepare, request, review and queue the obligation, then
run delivery, lookup or reconciliation separately. Fluent2 presenters omit private
worker capabilities and lease tokens. A production realm, accounting policy,
controller mappings and QuickBooks calls remain outside this practice route.

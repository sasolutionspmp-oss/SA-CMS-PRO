# Owner billing practice

This is the implemented synthetic owner-billing workflow and its Fluent 2 entry.
Cipher prepares a full-source owner pay application, obtains independent business
review, posts under that same grant, and separately authorizes a simulated send.
The working ledger is **Working ledger, not for issue**. This entry makes no
QuickBooks submission, external delivery, settlement or production-readiness claim.

The implementation reference is [owner_billing.py](../domain/owner_billing.py),
[ar_wire.py](../ar_wire.py), [ar_contract.py](../ar_contract.py) and
[ar_receipts.py](../ar_receipts.py). The shared design direction remains
[PRODUCT_GOAL.md](PRODUCT_GOAL.md) and [UI_OVERHAUL_SPEC.md](UI_OVERHAUL_SPEC.md).

## Run the separate entry

From the repository root, after the AR web sources and pinned web dependencies
are present:

```sh
npm --prefix apps/cipher/web run build:ar
python -m apps.cipher ar-practice-web --port 8769
```

Open `http://127.0.0.1:8769`. The build goes to `apps/cipher/web/dist-ar`;
`ar-practice.html` is the separate entry. Port 8769 is also the CLI default.
The server creates a fresh owned in-memory practice workspace with registered
synthetic people, visible and hidden projects, and declared owner sources.
Restarting discards its records, sessions and drafts. There is no host, file
workspace, actor, credential, mode or provider selector.

Fluent requires no Microsoft sign-in. Selecting a synthetic practice person is
not operational staff authentication. Actual Microsoft Entra identity and durable
staff sessions remain separate integration work.

## Seven fixed actions

Fresh actions have a pure server review before their effect. The fixed API prefix is
`/api/ar-practice/v1/`, contract version `cipher.ar-practice.v1`. Append
`:preflight` to an action route for its pure review. Effects supply the reviewed
fingerprint, quoted `If-Match` version, CSRF token and original
`Repeatability-Request-ID` UUID. Identity and duties come from the current session.

| Action | Route after the API prefix | Actual project duty and effect |
| --- | --- | --- |
| `ownerBill.prepare` | `owner-bases/{id}/prepare-bill` | PM prepares one immutable source-backed draft. No journal. |
| `ownerBill.requestApproval` | `owner-bills/{id}/request-approval` | PM requests accounting review of the exact bill. |
| `ownerBill.approve` | `owner-bill-approvals/{id}/approve` | A different accountant/controller grants business approval. No journal. |
| `ownerBill.post` | `owner-bills/{id}/post` | Accountant/controller distinct from the financial reviewer posts once under that original grant. |
| `ownerBill.requestSend` | `owner-bills/{id}/request-send` | PM/accountant requests review of the posted bill's exact synthetic message and current balance. |
| `ownerBill.approveSend` | `owner-send-approvals/{id}/approve` | A different PM/accountant grants the separate send authorization. |
| `ownerBill.send` | `owner-send-approvals/{id}/send` | PM/accountant consumes that send grant and records one synthetic mail-sink message. |

A person must be active, internal and registered, with current membership and
an owned role grant on this project. Owner wildcard, entity authority,
delegation, external/service identity and caller-supplied role labels do not
supply these duties. A controller's accounting duty permits financial review or
posting; it does not supply the existing PM/accountant send duty.

Financial requester and reviewer must be different actual people. Financial
reviewer and poster must also differ; the original requester may post if that
person independently holds the required accounting duty. There is no universal
three-person rule. Send requester and reviewer must differ; execution does not
introduce a third-person requirement. Current sender/poster authority and the
original reviewer's required current duty are checked again before a new effect.

## Declared owner source and exact calculation

The fixture declares an owner contract/SOV of **$250,000.00 with 10% retainage**:
U1 is 100 EA at $1,000.00, totaling $100,000.00; L2 is a $150,000.00 lump sum.
This synthetic owner basis is separate from a supplier subcontract. It is not a
customer award, adopted signed agreement, legal acceptance or external engineer
certification. `declare_practice_basis(project_id, contract_revision_id=..., actor=...)`
is fixture/source setup, not one of the seven public actions.

The basis seals project/customer scope, original native prime and close-contract
versions, an owned `owner_agreement` revision, the complete SOV, audited 30-day
customer terms, synthetic recipients and the fixed
`practice.invoice-date.period-start.v1` date policy. Invoice date is the original
audited period start; a future invoice date is refused. In the October fixture,
invoice/due dates are October 1/31, 2026.

Preparation accepts exactly `claimRevisionId`, `reviewRevisionId`, `periodId` and
`lines`. Every SOV line supplies `lineId`, `claimedCumulative`,
`reviewedCumulative`, `differenceReason`, `claimSourceLocator` and
`reviewSourceLocator`. Claim and review bind **separate owned original revisions**
of `owner_claim` and `owner_certification`, with separate locators. These are
manual source entries; neither document parsing nor geometry measurement is
asserted.

Quantities are exact decimal strings with up to six decimal places. Lump-sum
cumulative amounts are exact dollar strings with up to two decimal places.
The browser does no pricing arithmetic. The server derives rates, previous
posted certification, cumulative extensions, retainage, current due and journal
preview. Each cumulative extension rounds half up to integer cents before the
previous cumulative amount is subtracted. Cumulative retained cents round half
up from reviewed certified cents times the retainage rate; current retained and
current due derive from the original previous certified/retained totals.
Every line is required exactly once. A claimed/reviewed difference requires its
reason even when cent rounding hides a small quantity difference. Reduced
certified history, over-SOV work, negative bills and unchanged zero-effect
applications require a different workflow or are refused.

For the first fixture application, U1 claims 12 EA and reviews 10 EA; L2 claims
$15,000.00 and reviews $12,500.00. The claimed total is $27,000.00, reviewed
certification is $22,500.00, retainage is $2,250.00 and current due is $20,250.00.
Posting creates exactly this original journal:

| Account | Debit | Credit |
| --- | ---: | ---: |
| 1100 — accounts receivable | $20,250.00 | $0.00 |
| 1150 — retainage receivable | $2,250.00 | $0.00 |
| 4000 — reviewed certified revenue | $0.00 | $22,500.00 |

Business grant remains journal-free. The native modern bill remains `draft`
after grant; Fluent derives **Approved, not posted** from the immutable grant.
Explicit posting consumes that same original approval, uses its original open
period and exact journal, and records an immutable posting receipt. Modern
combined `prime_bill.approve` execution is refused; genuine historical legacy
combined postings remain preserved.

## Separate send and original outcomes

Send review begins only after exact original posting proof and current financial
qualification. It binds the current amount, original approved recipients and
message facts. A changed balance or material/governance change requires fresh
review. A new legacy terms/recipient setter row or hash alone does not qualify a
new owner source declaration. Send is the existing fixed synthetic mail sink;
it makes no external customer-delivery or payment-receipt claim. Posting and
sending have separate confirmations with safe cancellation choices.

Immutable action receipts preserve original preparation, request, grant, posting
and send outcomes. A completed original posting receipt remains posted while the
current bill can become sent or partly collected. Genuine later claim/review,
contract, terms or recipient revisions do not rewrite original outcomes; fresh
actions must qualify current facts. Current bill lifecycle markers must also be
backed by their original audited grants, journals and sends.

The native interfaces are `basis_scope/basis_proof/basis_inventory`,
`source_scope/source_proof/source_inventory`, `approval_proof/approval_inventory`,
`grant_proof/grant_inventory`, `posting_receipt` and `send_proof`.
Pure preparation/business/posting checks are `prepare_preflight`,
`business_request_preflight`, `business_grant_preflight` and `posting_preflight`.
The real facade exposes `check_prime_bill_request/grant/post`, `post_prime_bill`
and `check_prime_bill_send_request/grant/execution`; the fixed request/grant/send
phases use its native approval service.

An original receipt is not current-balance qualification. Current reads, totals,
aging and fresh send use `current_ar_proof(bill_id)` and
`require_current_project_finance(project_id)`; the displayed native bill is
`current_ar_proof(...)["currentBill"]`. Missing or edited original source rows,
journals or audit births fail closed, including when storage guards are restored.
Scope is established before private source proofs, receipt lookup or counts.

## Supported standing balances and explicit holds

The bounded current contributor proof supports genuine native synthetic
**check/wire collections and their returns**. It reconciles every original
collection birth with its surviving allocation, amount, fee, date, actor,
reference and exact journal; returns require their original return act and exact
restoration journal in a qualifying actual period. Duplicate receipt references,
lost allocations and unaudited returned status cannot alter a qualified balance.
These records prove local synthetic bookkeeping, not external settlement. The
seven-action practice entry offers no new collection/return command.

Current owner qualification explicitly holds credits, write-offs, customer
deposits/applications, retainage releases, ACH-mandate variants and unsupported
bill/collection journal inverses. Surviving rows **or original audit births**
trigger the hold, so deleting an adjustment cannot restore eligibility.
Existing native synthetic adjustment behavior is preserved, but a separately
qualified owner source/settlement slice is still needed. Historical original
receipts can remain provable while current views or new sending are held.

AR aging uses the selected `asOf` date to age **current standing balances**.
It is not a historical cutoff snapshot: the contract reports
`balanceBasis: "current_standing_balance"` and `historicalSnapshot: false`.
Changing September 30 to December 31 changes delinquency age, not the current
control balance. Retained AR is an unreleased project aggregate; it has no
invented invoice due date, delinquency age or per-bill release allocation.
Reconciliation covers authorized projects before search filters. Owner close
checks are explicit global source-integrity prerequisites, not adjustments
attributed to the selected accounting period.

## Schemas, repeatability and workspace limits

Canonical registration appends these entries after unchanged schemas 1–73:

| Catalog ordinal | Name | Statements | SHA-256 SQL checksum |
| --- | --- | ---: | --- |
| 74 | `owner_billing_sources_and_posting` | 16 | `18da4657659b726730f2322de90917c7d9bb55f3bc53fc82721e1ed4741f85e9` |
| 75 | `ar_practice_action_receipts` | 4 | `c83580bfa65d7d1b72e6f8fc40edf8bacfa2dd9541b2cfafdf8c9637e9624199` |

Owner source import is inert; the required loader explicitly registers 74 and
then 75. Catalog ordinals are distinct from a workspace's physical migration
sequence: native migration matches the original **name**, SQL checksum and
statement count. An older workspace can have a different legitimate physical
application order. Admission verifies the contiguous positive physical prefix
through that entry's actual admitted sequence. Losing later API admission does
not falsify an otherwise intact original native source; the API independently
requires its own exact receipt admission. Lost source admission with original
source/receipt history cannot select a legacy fallback. A genuinely unused owner
module stays inert for existing close checklists.

Each actual canonical person's UUID shares a namespace with AP receipts,
pending accounting-worker reservations and commercial receipts. A key cannot be
reassigned to another action, body, reviewed version or workflow. Metadata checks
initialize no provider or other domain. Original retries run after current duty
admission and before fresh version/source eligibility; altered stored results or
original source proofs are refused. Effects, authorization controls, command
bookkeeping and receipts share a whole-command savepoint, including nested
cross-workflow collisions caught inside an outer transaction.

The browser preserves the exact original UUID/body/version after response loss,
edits and navigation. A known definitive source-change refusal can be retired
only through **Start a new current review**, retaining the old request/refusal
for exact retry and using a new UUID for the fresh effect. Transport loss, 500,
unknown integrity holds or malformed negative-receipt metadata retain the
unresolved request. Session expiry or current scope loss clears private facts
and controls.

The first owner-billing writers require owned **memory practice**. Copied or
restored file workspaces keep the native diagnostic/read-only and attested-owner
claim boundaries; a claim does not turn this memory-only API into a file or live
service. The entry cannot choose a copied workspace, initialize a real worker or
wire an accounting/payment provider. Durable drafts/sessions, production staff
identity, external sending/settlement, G702/G703/C-620 issue output and operational
accounting integration remain separate work.

## Qualified scratch evidence and candidate status

The isolated Fluent/backend browser run completed on October 15, 2026 at 1440,
1024 and 390 pixels, with all 132 captured runtime/browser/build/harness source
hashes unchanged over 448.276 seconds:

| Scratch check | Result |
| --- | ---: |
| Settled views, including open confirmations | 78 |
| Complete seven-action journeys | 3 |
| Separate recovery drafts | 3 |
| Exact original request retries | 57 |
| Recovery checks | 27 |
| Contract checks | 34 |
| Unexpected application/HTTP/CSP errors | 0 |
| Axe violations | 0 |

Each primary scratch journey produced one bill, seven action receipts, one
journal and one synthetic mail-sink record, with zero native provider calls.
Recovery drafts created no extra journal or send. Evidence is retained in
`/tmp/cipher-completion/ar-browser-final-result.json`,
`ar-browser-final/ar-smoke.json`, `ar-browser-final.log`,
`ar-browser-source-before.json`, `ar-browser-source-after.json`, and
`ar-ui-browser-notes.md`.

These are **scratch results**. Root's integration candidate also hardens exact
original receipt invocation binding—including actual person, UUID, body,
version/fingerprint, result/source, outcome/status and workspace—and binds a new
request's deadline to its actual locked generation window. Original approvals
retain their original deadline; grant/consumption must precede it. The receipt
and deadline candidate fixes still require final main-repository qualification;
the earlier browser snapshot is not evidence that those later changes have
already passed a main rerun. No final full-suite, deployment, owner visual
acceptance or manual screen-reader qualification is claimed here.

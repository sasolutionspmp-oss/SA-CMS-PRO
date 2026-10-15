# Owner billing and AR: implementation plan

This is the original design plan following the commercial workflow. The implemented
seven-action practice entry and its exact qualified boundaries are recorded in
[OWNER_BILLING_PRACTICE.md](OWNER_BILLING_PRACTICE.md). That reference takes
precedence over planned behavior below: current qualified collection/return history
is proved, while other adjustments and unsupported sources hold the entry. Retainage
release and collection commands remain later work. The shared financial engine and
original Fluent specification supply the foundations.

## Concrete completion target

A registered synthetic PM prepares one owner pay application from an explicitly
declared, owned prime-contract/SOV basis and owned certification evidence. A different
registered accountant reviews and grants its original `prime_bill.approve` business
authorization without a journal. An actual accountant/controller, distinct from that
reviewer, posts once under the same authorization. A separate request/grant/send
workflow delivers the exact approved message to the existing synthetic mail sink.
Fluent shows the complete original source, claimed/reviewed/prior figures, original
approval and posting outcome, current open AR, retained AR and aging.

This makes the smallest useful owner-billing workflow executable. It does not infer
an owner contract, customer award, adopted prime SOV or engineer acceptance from the
commercial estimate-to-supplier-subcontract handoff. The owner and supplier contractual
sources stay distinct. The first basis is a declared synthetic practice fixture; real
source adoption and issue require their own qualified authority and evidence.

## Existing APIs to preserve and reuse

| Existing source | Reusable behavior | Gap in the connected practice layer |
| --- | --- | --- |
| `domain/receivables.py: set_prime_contract`, `contract`, `contracts` | Exact contract value, immutable versions, retainage rate, overbilling floor | Current setter has an actor string but no approval. No owner SOV or owned agreement-adoption proof. |
| `Receivables.certify` | Increment from the standing unreversed billing chain, retainage rounding, monotone certification, released-retainage floor, draft sequence, contract staleness | Only one aggregate certified amount. No line quantities, claimed-versus-reviewed source, provenance receipt or pure entry preflight. |
| `Receivables.manifest`, `_bill_lines`, `_preview` | Original prime contract version/value, entity/USD, exact 1100/1150/4000 preview, prior certified/net values, dates and payment terms | Existing `prime_bill.approve` consumes and posts together through `Cipher.execute`. It has no modern journal-free business grant or independent posting receipt. |
| `Receivables.get`, `list` | Original bill amounts plus current receipt/credit/write-off/deposit/reversal status | A modern source/lifecycle integrity proof is needed before these facts qualify an AR DTO or a new command. |
| `Receivables._send_manifest`, `_apply_send` | Separate `prime_bill.send` approval, exact recipients/version/message hash, stale balance refusal, one synthetic mail-sink send, immutable historical legacy sends | Need scoped real-person duty checks, pure preflight and original repeatable action outcomes. No external sending is qualified. |
| `payment_terms`, `payment_terms_history`, `set_customer_terms` | Immutable terms, explicit due dates, original terms preserved after later changes | First fixture terms must be audited and proven. Do not expose the direct setter as a practice toggle. |
| `ar_open_items(project_id, as_of)`, `retainage_receivable_items`, `deposits_items` | Complete AR and retained-AR reconciliations, dated aging, standing credits/returns/applications, source drill-down | The connected AR entry is the next workflow. Filter authorized projects before totals, counts, links and errors. Native As of changes aging days, not standing balances; label current balances explicitly until a true financial cutoff is proved. |
| `record_collection`, `record_return`, `record_deposit` | Exact amounts/fees, standing journals, settlement dates, cutoff, case-insensitive cross-source reference uniqueness, partial collections and late returns | These legacy APIs post directly from actor/reference strings. Do not expose them as modern receipt commands until owned settlement evidence and independent authorization are added. A fabricated provider reference is not external settlement proof. |
| `prime_retainage.release` and retainage invoices | 1150-to-1100 release, completion/cutoff/contract eligibility, separate collection | Retainage release remains a separately reviewed act. First slice reads it; the following slice adds qualified actions. |
| Credit memos, write-offs, deposit applications | Draft/request/grant/apply operations, exact standing-open caps, chronology and journal lineage | Add modern actual-duty/source/API receipts before these become Fluent actions. Keep inverse/credit accounting obligations separate. |
| `domain/close.py: set_contract_value`, WIP reads | Existing WIP and close calculation | Contract value is duplicated. The spec's item 9 requires one governed prime source. First practice basis must detect divergent modern values; do not silently overwrite existing close history. |

`domain/contracts.py` governs supplier commitment agreements, signature and coverage.
It is not an owner-contract registry. Reusing its document patterns is appropriate;
adopting a supplier agreement as the owner's prime contract is not.

## Additive engine boundary

The likely next catalog entries are one owner-billing source/lifecycle entry after
commercial and one AR action-receipt entry after that. If commercial ends at 73, these
would be 74 and 75. These numbers are proposed, not reserved or registered. Preserve
all existing schema text/order, role codes, audit payloads, operation codes, genuine
legacy postings and historical sends.

1. **Owned source basis.** A fixed fresh-fixture declaration binds original workspace
   practice mode, entity, USD, project/customer, original project/customer birth
   events, exact original prime contract row and birth event, explicit SOV lines,
   owned current agreement/certification document revisions and their locators,
   terms/recipients policy, calendar/date policy and versioned calculation policy.
   The declaration is synthetic source provenance; it does not claim a legal award
   or external engineer acceptance. Later real adoption gets its own operation.
   The old `project.created` audit includes name/budget, not entity/customer, so the
   new declaration must explicitly seal those facts instead of inventing old proof.
2. **Prepared certification source.** Append immutable source rows/line facts next
   to native prime bills. Preserve all SOV lines, stable owner bid-item IDs, basis,
   unit/rate, previous/claimed/reviewed measures, exact calculated cents and required
   difference reasons. Claim and review evidence retain separate original owned
   document references. Native aggregate `certify` uses the reviewed total only.
   It creates no journal. Calculate previous facts from proven standing native
   owner bills and original line snapshots, never from request-body previous totals.
3. **Journal-free grant.** Keep `prime_bill.approve` and its accountant/controller
   spelling compatible. Add an audited immutable AR business-grant record. Grant
   proof binds the original request, source/contract/terms/period/date/governance
   manifest and actual requester/reviewer person IDs. New modern prime-bill grants
   create no journal and no receivable.
4. **Independent posting.** Add explicit `Cipher.post_prime_bill` and pure counterpart.
   The poster's own current project accountant/controller duty is mandatory. The
   actual reviewer cannot post the same bill, and owner wildcard authority cannot
   bypass this separation. Consume the original grant, post the exact native
   journal and write an immutable original posting receipt in one whole-command
   savepoint, including command bookkeeping and action receipt. Recheck the
   original reviewer's current required duty before the first post.
5. **Historical compatibility.** Dispatch old genuine certified/posting histories
   through their preserved legacy path. Modern classification must come from the
   audited source birth/inventory, not a row that can be deleted to turn modern
   authority off. Refuse modern `Cipher.execute(prime_bill.approve)` combined
   posting; never rewrite genuine earlier journals or receipt outcomes.
6. **Send.** Reuse separate `prime_bill.send` with current full message and recipient
   proofs. Bind original posting receipt, current standing financial adjustments,
   terms/date lineage and fixed mail-sink channel. A later partial collection,
   credit, write-off, deposit application, reversal or recipient revision makes
   the reviewed send stale. Sending creates no new revenue or receivable.
7. **Integrity/close.** Exact typed canonical JSON equality, original event shapes,
   audited births/inventories and source-to-native line/aggregate correspondence
   must detect deletion, forged rows, raw date/value changes and approval/command
   substitutions. The modern source module is inert for unclassified legacy data.
   Activated modern source problems fail closed and appear in close checks in
   their actual journal periods. Monetary reconciliation alone is not provenance.

## People, scope and sessions

Use current registered actual people, active project membership and explicit current
project grants. Do not use caller actor/role strings, owner wildcard inheritance,
delegations or a locally chosen persona to supply business authority. First practice
roles can be PM preparer, accountant reviewer, accountant poster, plus hidden-project
and revoked-person fixtures. Controller support must inspect an explicit actual
controller grant; AP's current resolver deliberately recognizes only PM/accountant
and must not be broadened accidentally.

Request and grant require different actual people. Posting requires a person different
from the original reviewer. A legitimate requester with an actual accounting duty
may later post if the policy allows; do not invent a universal third-person rule.
Send request/grant uses the same explicit separation and existing permissible
PM/accountant duties; an authorized current person applies the grant. Do not infer
that send execution itself requires a third different person.

First source prepare can be PM; the financial authorization's existing operation role
remains accountant. Add a specialized pure request check and skip the generic people
requester-role check where necessary, as the AP split already does. Requester duties
and decision/posting duties are distinct facts. Recheck scope before record lookup,
counts, preflight, replay disclosure and any command lookup.

Use a separate fresh memory-only AR server and registered synthetic session prefix.
The current single-owner/entity workspace is not a multitenant deployment. Bind the
owned immutable workspace declaration and project/entity in all source/receipt
proofs now; qualified Entra tenant/person binding and real staff sessions remain the
operational identity gate. Fluent itself needs no sign-in or tenant setup.

## Fixed first API and Fluent flow

Suggested separate prefix: `/api/ar-practice/v1`; command: `ar-practice-web`.
The server owns one initialized fresh synthetic fixture. No selectable workspace,
file path, provider, accounting realm, policy, actor or duty is accepted from the UI.

| Fixed action | Who acts | Effect |
| --- | --- | --- |
| `ownerBill.prepare` | Actual project PM | Frozen owned source and one native draft; no journal |
| `ownerBill.requestApproval` | Actual project PM | Request original financial review; no journal |
| `ownerBill.approve` | Different actual accountant/controller | Original journal-free business grant |
| `ownerBill.post` | Actual accountant/controller different from reviewer | Consume that grant, one exact native journal and posting receipt |
| `ownerBill.requestSend` | Actual PM/accountant | Request exact current recipient/message review |
| `ownerBill.approveSend` | Different actual permitted person | Grant only that send |
| `ownerBill.send` | Actual permitted current person | One fixed synthetic mail-sink message, no new AR |

Draft cancellation, grant withdrawal, certification revision and posted credit/
correction should follow the same immutable source/lifecycle extension next. A
blocked/stale first-slice draft can show a truthful unavailable reason until the
governed correction route exists; do not offer editing of a granted/posted source.

Every action uses pure preflight, typed bounded body, source/duty/governance/clock
fingerprints, quoted `If-Match`, CSRF, UUID repeatability and audited immutable
original outcomes. Extend the shared per-person namespace reciprocally across AP,
pending accounting invocations, commercial and AR. A cached original "posted"
outcome stays the original outcome after the current bill becomes sent/partially
collected/credited; current record status is a distinct DTO field.

Use the pinned shared Fluent 2 components/theme and original templates:

- **T3 Owner billing list:** Draft, Under review, Approved not posted, Posted awaiting
  send, Sent/open and Settled views. Right-aligned integer-cent totals come from
  scoped source rows; status never implies actual customer receipt.
- **T4 Owner pay-app record:** separate revenue/retainage/current receivable groups,
  original source documents, line correspondence, terms/dates, distinct lifecycle
  rail, current adjustments and History last.
- **T6 Entry/review:** owner contract bid quantity/unit/rate are read-only; previous
  certified facts are server-derived. Show claimed and reviewed quantities/amounts
  separately, with mandatory reasons. Do not mix quantities, percentages and dollars
  in one column. First slice admits exact unit quantities and lump-sum dollars;
  percentage entry and stored-material work follow with explicit additional rules.
- **T5 Approval/post/send review:** source, exact source/period/date, separate original
  approval and exact accounting preview above one pinned footer. The server owns
  consequences and unavailable reasons. Repeating the old result and explicitly
  reviewing a next step are separate UI actions.
- **T9 AR/retainage aging:** As of and Project parameters, exact open amounts and
  direct links to original bills, returns and adjustments. Working-ledger exports
  carry the required "Working ledger, not for issue" watermark.
- **T8 Readiness:** named completion gates for source, review, independent posting,
  synthetic send and official-books mapping. Do not display QuickBooks acceptance
  or settlement from local journal/mail-sink facts.

Actual API/browser journeys must run at 1440, 1024 and 390 pixels with no console,
CSP, application HTTP or serious/critical accessibility errors. Final owner visual
acceptance, screen-reader review and performance qualification remain explicit.

## Following AR slice: receipt and retainage evidence

After the above workflow, add receipt preparation/request/grant/post as distinct acts
over owned immutable synthetic settlement evidence. Bind exact source identity,
project/customer, method, amount/fee, unique evidence/reference, value date, posting
period, standing bill allocations and original posting receipt. Derive caps from
the current proven open balance. Post Dr 1000 net cash + Dr fee account / Cr 1100
only under the independent accounting authorization; never accept a UI's made-up
provider reference as proof. Partial receipts update current open AR without
rewriting the original billed obligation. A duplicate reference across native,
retainage, labor, reimbursement and deposit sources remains one conflict.

Late returns require owned return evidence and a separate correction approval in
an actual open period no earlier than the original receipt. Retainage release is
its own reviewed 1150-to-1100 act, with completion/contract/previous-release source
and later original receipt allocations. Credits/write-offs/deposit application
routes retain their native chronology and separate adjustment journal lineage.
Read-only legacy records can be shown as historical synthetic evidence, but do not
upgrade them to a newly qualified external settlement merely by assigning a hash.

AR official-books handoff requires its own normalized route and QuickBooks Invoice/
Payment/CreditMemo mappings. The current practice original installed-AP JournalEntry
route cannot deliver an AR invoice, swallow a later owner credit, or net current
open AR into the original accounting obligation. Reuse its same-UUID unknown outcome
and separate readback design once the AR route is qualified.

## Required acceptance and adversarial tests

1. Complete owned owner source -> prepare -> independent grant (zero journals) ->
   separate post (one exact 1100/1150/4000 journal) -> independent send -> synthetic
   send record; preserve original results on exact retries after later genuine states.
2. Actual scope before lookup/counts/replay; owner aliases, fake actors, inactive
   membership, revoked roles, services/external people and dual-account same-person
   identities cannot manufacture authority or bypass separation.
3. Exact decimal strings and integer cents; reject Python bool/int/float aliases,
   unknown keys, forged rates/previous values/source revisions/dates, incomplete or
   duplicate line inventories, unit/amount caps and unreasoned review differences.
4. Cumulative per-line rounding before subtraction, zero-value source lines,
   step-down retainage with no new revenue, released-retainage floor, fully retained
   revenue, monotone prior source and distinct credit workflows.
5. Source/governance/terms/recipient/contract changes make review stale. A new standing
   chain or reversal cannot quietly replace the earlier previous quantities.
6. Whole-command savepoint and late audit/effect/receipt/COMMIT rollback, including
   caught faults inside an outer transaction; same UUID/concurrent requests yield
   one original effect; cross-action/domain/body reuse conflicts.
7. Raw row edits/deletion, original source/approval/receipt deletion, exact event
   sequence types, foreign evidence, mismatched journals/dates and forged cached
   outcomes fail closed. Hashing a forged current row never makes it authoritative.
8. Genuine old schema/receipt/journal/send upgrade and later migration rollback,
   copy opening preserves original bytes and initializes no writable financial or
   delivery worker; exact existing schema prefix/corpus/golden results remain.
9. Partial collection, duplicate references, fees, over-allocation, credits,
   deposits, late returns and retained-AR releases reconcile through native APIs
   without rewriting the original bill/authorization or source period.

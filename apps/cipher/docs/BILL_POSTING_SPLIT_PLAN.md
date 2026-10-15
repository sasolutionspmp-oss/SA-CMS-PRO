# Bill approval and posting split

Implemented and verified October 14, 2026 in the synthetic engine as B01 and the bill-duty portion of B02 in [DELIVERY_BACKLOG.md](DELIVERY_BACKLOG.md). A `bill.approve` grant now records business approval without posting; an independent human posts using that same authorization. The full 1426-test suite passes; see [BUILD_STATUS.md](../BUILD_STATUS.md) for evidence and remaining gates.

## Implemented workflow

1. The preparer submits the bill for business approval. The server builds its manifest from the bill, supplier identity, commitment, amounts, invoice and stored-material evidence.
2. A person with approval authority grants `bill.approve`. The bill becomes `approved`, with no journals, AP balance or payment intent created by that grant.
3. A different person acting under an accountant or controller posting duty chooses an open accounting period and reviews the exact entry. Choosing a period other than the certification period requires a reason.
4. `post_bill` runs an idempotent `bill.post` command. It rechecks business facts, authority, expiry and coverage, consumes the original business authorization, writes the posting receipt and journals, then marks the bill posted in one transaction.
5. Paying the posted bill remains a separate workflow.

There is one business approval. Posting is a separate authorized act; it does not require a second business approval or a third person to authorize the bookkeeper. Its immutable receipt binds the actual period, journal preview, poster and cross-period reason to the original approval.

The original approver may withdraw an approved, unposted bill while they still hold its business duty. Withdrawal invalidates the grant, retains its history and restores stored-material reservations; a standing cumulative successor must be withdrawn first. Expired or stale approval does not grant posting rights. Changed business facts require a fresh business approval, which replaces the current link without rewriting earlier records. No new cancellation approval or posting approver is invented.

## Authority

| Duty | Business approval | Posting |
|---|---|---|
| Project manager | Allowed; monetary limits remain owner decisions | Refused |
| Bookkeeper/accountant | Prepares the bill; does not grant its business approval | Allowed when a different person approved it |
| Controller | Allowed | Allowed when a different person approved it |
| Owner | Allowed | Requires an actual posting duty; owner authority does not override person separation |
| Served Ricky | Reads and drafts | Refused |

Bill preparation, business grant and posting checks are separate. Bill requests use the fixed business duty; an `owner` role cannot bypass the independent posting check. Normalized registered-person identity, current authority and project scope are checked, including the approver's authority again at posting. Entra accounts mapped to one person remain B10 work. Global operation duties and authenticated API identity remain open; this change adopts no thresholds, policy exceptions or solo-owner waiver.

## Records and source proof

- Keep existing posted bills, journal IDs, stored operation codes and their `bill.approve` authorization references unchanged.
- Schema 65, `bills_business_approval_posting`, is registered after the historical 64 entries. It adds `bill_business_approvals`, `bill_posting_receipts` and separate business-grant, posting-period and receipt links on `bills`. Existing statement text and plugin order remain unchanged.
- New journals reference the original consumed `bill.approve` authorization; the distinct `bill.post` act has its own command, immutable receipt and audit evidence.
- `bills.period_id` remains the certification period. `posting_period_id` records the selected accounting period without changing the certified content hash.
- Business approval binds business facts. The posting receipt binds accounting facts at posting time. Bank destinations belong to payment approvals; changing a destination must not silently change business approval or its evidence.
- Lifecycle markers created by granting or posting must not make the unchanged business facts stale. Re-derive the business manifest from those facts, rather than binding its own draft/approved transition as a material change.
- The existing CHECK constraint already permits `approved`; new lifecycle guards admit the separate grant/post acts without rebuilding the table.
- Old unconsumed combined approvals must require fresh business approval. They cannot retain a route that posts through `execute('bill.approve')`.
- Request, grant and consumption hashes and actors must match audit evidence. Expiry cannot exceed the original audited manifest deadline; a shorter deadline remains valid and malformed dates refuse. Every business-grant history row, including superseded grants, must still match its audited creation. Receipts verify immutable bill header/line/transfer facts and every original journal's source, version, period, poster and line fingerprint. This proof does not rebuild current vendor, SOV or policy facts after posting, so legitimate later master changes do not rewrite history.
- Missing new links do not prove a legacy posting. Historical bills need their genuine consumed combined authorization, audited posting and matching approved journals. AP, retainage and stored-material source reads fail closed on altered or unproved posted bills; lifecycle failures also block closing.
- Posting uses savepoints so a caught refusal inside an outer transaction cannot preserve a consumed grant or partial journals. Exact retries return the original receipt; changed payloads refuse. Cumulative successors wait for predecessor posting and cannot use an earlier accounting period.

## Implemented boundaries

| Area | Current behavior |
|---|---|
| Service and people | Journal-free atomic grant, explicit posting command, fixed bill duties, person/scope checks and refusal of combined execution |
| Bills and schema | Separate grant metadata, chosen-period journal plan, immutable posting receipts and direct-domain enforcement |
| Contracts | Coverage checked again at actual posting under the original authorization; historical checks preserved |
| Intake and evidence | Approved-unposted invoice attachment and replacement supported; changed bound facts require fresh approval |
| Cumulative billing and stored materials | Predecessor posting and actual-period order enforced; cancellation restores certification reservations |
| Credits and corrections | Actual original posting period supplies the earliest correction date, with genuine legacy source proof |
| Payments and close | Unposted bills excluded from AP/retainage/stored accounting totals and payment; source-proof and lifecycle failures block derived amounts or closing |
| SDK, console and tools | Human approval/posting acts are explicit; served Ricky remains read/draft-only; synthetic callers name both people |

`execute('bill.approve')` and `approve_and_execute('bill.approve')` refuse the former combined act. Fixtures and acceptance walks name their approver and poster explicitly. Direct domain posting requires the same configured authority check and recorded business grant.

Preserve existing governor controls during this refactor. Changing which insurance, waiver or other facts hold approval versus payment is a separate policy decision; separation must not silently loosen the current rules.

## Acceptance and regression cases

The focused tests were written before their fixes. The full continuation checks the following cases:

1. Business approval creates no journal or payable and cannot release a payment.
2. A distinct authorized poster creates the exact selected-period journals once; retry replays the same posting receipt without another effect.
3. The business approver, a PM and a forged owner role cannot post. Normalized registered-person separation is enforced; multiple Entra accounts bound to one person require B10 acceptance.
4. Revised invoices, stored evidence, billed commitment facts, supplier identity or approver authority block posting and route to fresh approval.
5. Posting to another open period requires the recorded reason while preserving the business approval's facts. A locked period refuses the act.
6. Expired business authorization cannot post. Per-operation expiry and hold windows remain B06; tests must not quietly extend the current policy.
7. Coverage is rechecked at posting. Approved-unposted bills remain outside AP, retainage and stored-asset accounting totals.
8. A cumulative successor cannot post before its predecessor; approved-unposted cancellation and replacement preserve lot reservations and subledger ties.
9. A correction or credit cannot be dated before the actual original posting journals, even when the certification period is earlier.
10. Altered approval links, rewritten snapshots/receipts and missing audit evidence fail closed, including tests that remove relevant triggers.
11. A schema-64 workspace upgrades with every original schema row, posted journal and audit entry unchanged; restored copies remain read-only.
12. The golden fixture, corpus, vertical acceptance, browser journey and core gates use two explicit acts while preserving their financial results. Approval counts/timings must reflect any real workflow change, not a compatibility shortcut.

The acceptance suite must also cover concurrent posting and a caught refusal inside an outer transaction, preserving the atomicity established in the previous continuation.

## Verification and remaining work

`test_bill_posting_split` and `test_bill_posting_review` pass 31 focused tests, including immutable source proof, the original expiry bound and a schema-64 upgrade that preserves historical schema rows, journals and audit entries. The authority and service modules add 34 cases; all 65 are included in the passing 1426-test full suite. Core gates pass 9/9 and 127/127 checks; the corpus retains its exact financial/timing report. Chromium passes the 20-step console journey and 18 Fluent actual-API views plus 7 contract/precision checks.

B02 is complete only for bill duties. Global duties, authenticated identity, owner policy choices and Entra account binding remain open. B03 now supplies immutable audited practice mode and refuses live admission. Typed action contracts, presenters and practice sessions are next; the Fluent read harness does not close consequential screen or operational gates.

Microsoft tenant setup and Fluent UI styling are not prerequisites for this engine work. The authenticated API and accepted screens are separate dependencies before operational use by staff.

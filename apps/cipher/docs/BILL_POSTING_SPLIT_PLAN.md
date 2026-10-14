# Bill approval and posting split

Design prepared October 14, 2026 against commit `47aee0a7`. Implementation is the next coding milestone, B01–B02 in [DELIVERY_BACKLOG.md](DELIVERY_BACKLOG.md). The current `bill.approve` execution still posts; this document does not mark that blocker closed.

## Intended workflow

1. The preparer submits the bill for business approval. The server builds its manifest from the bill, supplier identity, commitment, amounts, invoice and stored-material evidence.
2. A person with approval authority grants `bill.approve`. The bill becomes `approved`, with no journals, AP balance or payment intent created by that grant.
3. A different person with the posting duty opens Post approved bills, chooses an open accounting period and reviews the exact entry. Choosing a period other than the certification period requires a reason.
4. `post_bill` runs an idempotent `bill.post` command. It rechecks business facts, authority, expiry and coverage, consumes the original business authorization, writes the posting receipt and journals, then marks the bill posted in one transaction.
5. Paying the posted bill remains a separate workflow.

There is one business approval. Posting is a separate authorized act; it does not require a second business approval or a third person to authorize the bookkeeper. Its immutable receipt binds the actual period, journal preview, poster and cross-period reason to the original approval.

## Authority

| Duty | Business approval | Posting |
|---|---|---|
| Project manager | Within the eventual agreed limits | Refused |
| Bookkeeper/accountant | Prepares the bill; does not grant its business approval | Allowed when a different person approved it |
| Controller | Allowed | Allowed when a different person approved it |
| Owner | Allowed | Requires an actual posting duty; owner authority does not override person separation |
| Served Ricky | Reads and drafts | Refused |

Separate preparing, granting and executing authority checks. The server fixes each operation's execution duty; a request cannot elevate it by selecting `owner`. Person separation uses the canonical identity, including login normalization and, after identity integration, multiple accounts mapped to the same person. Recheck the approver's current authority when posting. Approval limits and solo-owner exceptions remain owner decisions; this change must not invent thresholds or waive the posting separation.

## Record and migration design

- Keep existing posted bills, journal IDs, stored operation codes and their `bill.approve` authorization references unchanged.
- Store the business approval link separately from the existing posted journal link. New journals can continue to reference the original consumed business authorization; the distinct `bill.post` act is recorded in its posting receipt and command/audit entries.
- Keep `bills.period_id` as the certification period. Add an actual posting-period field or receipt reference. Changing the certification period would change the bill's existing content hash.
- Business approval binds business facts. The posting receipt binds accounting facts at posting time. Bank destinations belong to payment approvals; changing a destination must not silently change business approval or its evidence.
- Lifecycle markers created by granting or posting must not make the unchanged business facts stale. Re-derive the business manifest from those facts, rather than binding its own draft/approved transition as a material change.
- Append new named schema entries after the existing 64 entries through explicit late registration. Never edit historical schema text or reorder `PLUGIN_MODULES`.
- The bills CHECK constraint already permits `approved`; replace lifecycle and related guards through a new entry rather than rebuilding the bill table just to expose that state.
- Old unconsumed combined approvals must require fresh business approval. They cannot retain a route that posts through `execute('bill.approve')`.
- The posting receipt and business authorization must be checked against immutable audit evidence. Mutable row-local hashes alone are insufficient.

## Implementation boundaries

| Area | Required change |
|---|---|
| Service and people | Separate grant/post duties; make the bill grant journal-free and atomic with its approved-state record; introduce the explicit posting command; enforce person separation and scope; retire combined execution |
| Bills and schema | Business approval metadata, posting-period/receipt records, lifecycle guards, business manifest and chosen-period journal plan; enforce the same rules in direct domain calls |
| Contracts | Recheck coverage at actual posting under the original authorization; preserve historical coverage records and avoid treating business approval as a journal |
| Intake and evidence | Define approved-unposted invoice attachment, replacement and stale handling; any changed bound evidence needs fresh approval |
| Cumulative billing and stored materials | Refuse posting a cumulative successor before its predecessor; preserve certification reservations; provide an audited approved-unposted cancellation/reapproval path that restores lot balances |
| Credits and corrections | Use actual original posting/journal periods as the earliest correction date, with a legacy fallback; preserve original approval and posting history |
| Payments and close | Approved-unposted bills remain unpayable and excluded from accounting totals; retain close blockers for unposted bills and all existing control-account reconciliations |
| SDK, console and tools | Expose the human posting workflow and truthful next steps; keep served Ricky read/draft-only; migrate synthetic callers explicitly to separate acts |

Do not keep `approve_and_execute('bill.approve')` as an automatic posting shortcut, and do not invent a second actor inside it. Fixtures and acceptance walks must name their approver and poster explicitly. A legacy posting bypass would leave B01 open even if a new screen uses the separated path.

Preserve existing governor controls during this refactor. Changing which insurance, waiver or other facts hold approval versus payment is a separate policy decision; separation must not silently loosen the current rules.

## Acceptance and regression cases

Write the failing tests before implementation:

1. Business approval creates no journal or payable and cannot release a payment.
2. A distinct authorized poster creates the exact selected-period journals once; retry replays the same posting receipt without another effect.
3. The business approver, a PM, a forged owner role and another account belonging to the approver cannot post.
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

## Delivery sequence

Implement the bill lifecycle/receipt and authority contract together, then migrate downstream domains and callers. Run targeted regression and historical-workspace checks during development, followed by independent review and the full suite. Publish only when the entire bill workflow passes; a journal-free grant alone is not enough to close B01.

Microsoft tenant setup and Fluent UI styling are not prerequisites for this engine work. The authenticated API and accepted screens are separate dependencies before operational use by staff.

# Cipher prototype — verification record

Branch `cipher/synthetic-prototype`. Built by Claude from 2026-10-11 to 2026-10-12, continuing the Codex Cloud session "Set up SA-CMS-PRO", which stopped on a usage limit with its container work uncommitted. The plan (v1.0 package and v1.1 solo-first correction) is the specification. Modules were built in three rounds by parallel agents, each followed by an independent adversarial review and a fix pass; integration, gates and docs were reconciled afterwards.

## Verified on 2026-10-12

| Check | Result |
|---|---|
| `python -m apps.cipher test` on Windows (Python 3.12) | 1002 tests, OK, no expected failures |
| Same suite in WSL Ubuntu (Python 3.14) | 1002 tests, OK |
| Container image build (`docker build`, suite runs inside on Linux) | 1002 tests, OK; image runs non-root and reports healthy |
| Container serving with a token and an owner secret, on a workspace volume created by the previous build (schema upgrade in place), driven by headless Chrome through token sign-in | console self-test 16 of 16 |
| Local console driven by headless Chrome (`tools/browser_check.py`) | 16 of 16 |
| Golden fixture (`python -m apps.cipher demo`) | bills 27,000 and 18,000; forecast 122,000; prime bill 54,000; one provider transfer; trial balance balanced; AP and AR reconciled |
| Plan section-10 V1 acceptance test (`tests/test_vertical_v1.py`) | all steps pass end to end, including a credited supplier bill paid for exactly its open payable |
| Plan section-10 adversarial variants (`tests/test_adversarial_variants.py`) | every listed variant fails safely or is routed to an owner |
| Accounting-core gates (`python -m apps.cipher.tools.core_gates`) | native core passes 9 of 9 hard gates and 127 of 127 checks; one open advisory (G8, below); ERPNext not evaluated |
| Dependencies | Python standard library only |

Tests per module: adversarial_variants 22, ap_intake 25, assets 30, banking 43, bills_controls 42, close 40, core 31, core_gates 52, drawings 25, estimates_controls 49, field 36, forecast_v2 32, handoff 27, http 16, integrity 41, labor 37, ledger 15, payee_changes 20, payments_controls 64, payments_scope 27, procurement 29, receivables_controls 36, receivables_v3 23, reimbursements 38, ricky_brief 6, ricky_sdk 60, rights 46, schedule 24, service_controls 14, vertical_v1 23, workflow 29.

## Round 4 integration (extended acceptance and the 20-bill corpus)

Verified on 2026-10-13 in a Linux container (Python 3.13): `python -m apps.cipher test` runs 1186 tests, OK (the round-4 commit's 1166 plus the two files below).

- **Extended acceptance** (`tests/test_vertical_extended.py`, 12 ordered steps): one lift-station job, in one period, under an enforcing segregated identity policy (owner bootstrapped, roles granted through `people.grant_role`, the PM's on the project only), an adopted payment release policy and required agreements. Estimate; procurement (bid tab, a justified non-low award drafting the PO, receiving); both the PO and the subcontract executed only after `contract.approve_agreement` (legal) and `contract.sign` (the named signer, whom not even the owner can stand in for); insurance and bond certificates (bill approval refused until the payment bond is on file); a governed payee destination change verified by the outside accountant; Ricky's SDK carries the PO invoice through `record_supplier_invoice`, `compute_invoice_match` (three-way), `request_approval` and `execute_approved_action`; the PO release is standard, the subcontract's is high risk (amount and new destination): held by the cooling-off window, refused to its approver, refused without the outside accountant's co-signature and without a step-up, then released; asset capitalization and one month of depreciation; a licensed handbook that Ricky's `read_document` may not retrieve; a prime bill; bank reconciliation, the hand-off acknowledged by the outside accountant and the period closed through its checklist (every module's close checks passing). Pass criteria: balanced books, AP 0.00 and AR 63,000.00 reconciled, one transfer per release, every approval consumed with a requester, a different approver and an executor that the registry recognizes.
- **20-bill corpus** (`python -m apps.cipher.tools.corpus`, `tests/test_corpus.py`): literal data (pay applications with retainage and stored materials, PO invoices, an exact duplicate, a near duplicate, a credit note, a correction, a high-risk payment, a new-destination payment) run through intake, match, approval, posting and release under the same governance, on a simulated clock installed as the governors' `now` and the receivables calendar day and started at the destination change. Report: 19 released (405,700.00) and 1 blocked; 61 approvals, 10 routed to the owner and 51 to staff; held 1 duplicate review, 1 cooling-off, 1 co-signature, 2 step-ups; intake to release 615 to 2,610 simulated minutes (mean 987.42); books balanced, AP, retainage (31,800.00), stored materials and provider clearing reconciled. The test asserts the exact report and that a second run prints the same JSON.
- **Bugs:** neither walk hit a defect that blocked a step; no module code changed.
- **Limits found:** the approvals module, payment value dates and the procurement and intake "today" checks keep the wall clock (no injectable clock), so the corpus's simulated days never expire an approval. In production a 24-hour approval expires during a co-signature wait of a day or a five-day cooling-off window (a probe moving the approvals clock with the policy clock gets `ApprovalExpired` at the release; the payment-policy docstring says the approval "simply stays granted until the window ends"), so a held release needs a fresh approval, co-signature and step-up after the window, and the corpus understates those re-approvals. `asset.capitalise` posts its synthetic purchase straight to the bank (Dr 1500 / Cr 1000); a procured item billed through AP cannot be capitalized from its bill without counting it twice, so the walk capitalizes a separate kit.

## Round 3 (closed the first production slice's gaps)

- **Supplier invoice intake** (`ap_intake`): invoice number, invoice and due dates, terms, exact-number duplicate refusal, near-duplicate flags that need a recorded review, and an approval-bound match to a certified bill (subcontract) or to purchase-order lines received in good condition (three-way).
- **Credits and corrections:** supplier credit notes and posted-bill corrections (`bill.credit_note`, `bill.correct`); customer terms, credit memos, write-offs past 90 days, customer deposits on control 2400 and their application to prime bills. Payment release pays exactly the open payable left after credits and earlier payments.
- **Dates:** bills and receivables carry invoice, due and settlement dates; aging runs from due dates.
- **Forecast:** versioned budgets by cost code (`budget.revise` approvals, hash-chained versions), full cost to date across subcontract, labor and reimbursables, estimate to complete, cost-code rollup and immutable snapshots.
- **Payee changes:** request, independent evidence recorded by a different person against a stored evidence revision, then a `party.verify_destination` approval for `bank_admin`. The one-call HTTP action is gone; the console self-test drives the governed flow.
- **Payment states:** processing and bank-reconciled states; a payment processing past three days fails the close checklist and appears in Ricky's brief.

## Round 4 integration: Ricky SDK coverage and identity (2026-10-13)

- **Round-3 tools** (catalog 1.1.0) were already in `ricky_sdk.py` (committed with the American English pass): supplier invoice intake and matching, supplier credit notes and bill corrections, customer terms and deposits, credit memos, write-offs, budget revisions and forecast snapshots. Each draft is gated by the approval it leads to; the effects stay human-granted approvals.
- **Round-4 tools** (catalog 1.2.0): `read_identities`, `read_release_rules`, `preview_release` (classification, co-signature, step-up and cooling-off a release would need; records nothing), `read_contracts`, `register_contract_agreement`, `prepare_contract_signature` (the caller can never name itself, or a service identity, as the signer) and `record_insurance_certificate`. A round-4 draft runs in one write transaction and is rolled back and refused when it would void an open approval that still held (agreement, signature, commitment execution, or a bill approval or release that bound coverage). Every `people.*` and `payment_policy.*` operation stays restricted.
- **Routing completeness:** the catalog describes every classified operation (`operations`, covered by the catalog hash). The routing check now fails unless every approval-bound operation the service routes is reachable through the SDK (`ROUTABLE_OPERATIONS`, with its drafts, previews, `request_approval` and `execute_approved_action`) or listed by name in `RESTRICTED_OPERATIONS` with its reason.
- **SDK identity:** while the people module's identity policy enforces, every call resolves the caller to an active registered identity holding the role by grant or active delegation in scope (revoked or expired grants, lapsed or revoked delegations, ended memberships and deactivated delegators all refuse); any identity record that fails verification refuses every call; a resolved call runs under the registry's login and its receipt records the identity and the grant or delegation it rests on. Unconfigured, nothing changes.
- **Verified:** `python -m apps.cipher test` on Linux (Python 3.13): 1185 tests, OK (ricky_sdk 111, up from 92).

## What review found and fixed (highlights)

- Assets could over-depreciate across duplicate period rows; banking could book a fee twice; WIP adjustments could double count. All fixed with month-keyed guards, live-journal checks and span rules.
- Restored copies could still write records and dispatch queued payments, an older backup could resubmit a transfer, raw SQL could unlock a locked period or extend a posted journal, and `INSERT OR REPLACE` could bypass triggers. All are now refused by SQLite (query-only connections, seal and period triggers) and by recovery that looks up queued intents.
- Retainage could be released before closeout, the same stored material could be claimed twice, and labor or reimbursement invoices left the AR control unreconciled. All fixed.
- An expired approval stayed "granted" after a failed execution, and one claim code opened every sibling copy at the same epoch. Expiry is now durable, and claim codes bind to a per-copy challenge.
- A credited bill was released for its full amount due, and customer deposits were missing from the close reconciliations. Both fixed and covered by gate G9.
- The container self-test found that a server restarted on an existing workspace reissued simulator reference `sim_000001`, so the new payment's settlement was discarded as a duplicate. The simulator now continues after the workspace's references, an acceptance under a reference another payment holds posts nothing and is held for review, and an event for a reference two payments hold is rejected.

## Not verified / remaining gaps

- **Claim attestation (G8 advisory):** without `CIPHER_OWNER_SECRET`, claiming a restored copy is attestation only (recorded and flagged by Ricky's brief). The container run above sets the secret; every deployment that opens restored copies must too.
- **Identity and roles:** the people registry (round 4) checks roles once its identity policy enforces, and the Ricky SDK answers to it; nothing authenticates the caller yet. The HTTP `ricky_tool` action and the console still take the actor login from the request, so who is calling is asserted, not proven (part of the production-identity gate).
- **High-risk payments:** no amount-based step-up, co-signature or new-payee cooling-off policy beyond the approval and the governed payee change.
- **Contracts:** executing a commitment is one approval; contract signature as a separate authority with insurance and bond evidence is not built.
- **Ricky SDK coverage:** every approval-bound operation is reachable through the SDK or excluded by name with a reason. Deliberately not offered (a person's decision): recording a customer deposit, setting payment terms, clearing a duplicate flag, setting insurance requirements, withdrawing a certificate, co-signing a release, recording a step-up, and every identity and payment-policy change.
- **V1 coverage:** the section-10 acceptance test does not walk procurement, hand-off, rights, assets or the SDK; `tests/test_vertical_extended.py` does (round 4), and the 20-bill corpus reports approval-time metrics. Neither exercises labor, field, drawings, schedule or reimbursements under the identity policy.
- **Accounting policy:** posting rules for revenue recognition, stored materials and disposals are SHADOW assumptions awaiting controller approval.
- **Core decision:** ERPNext has not been run against the same gates; this machine had about 4 GB free on 2026-10-12 against the owner's 250 GB free-space target, so a multi-GB ERP stack should not be pulled here.
- **Later plan gates:** authoritative accounting, production identity, real payment providers, bank connectivity, licensed-content ingestion, multi-entity and CAD automation.

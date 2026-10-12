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

## Round 3 (closed the first production slice's gaps)

- **Supplier invoice intake** (`ap_intake`): invoice number, invoice and due dates, terms, exact-number duplicate refusal, near-duplicate flags that need a recorded review, and an approval-bound match to a certified bill (subcontract) or to purchase-order lines received in good condition (three-way).
- **Credits and corrections:** supplier credit notes and posted-bill corrections (`bill.credit_note`, `bill.correct`); customer terms, credit memos, write-offs past 90 days, customer deposits on control 2400 and their application to prime bills. Payment release pays exactly the open payable left after credits and earlier payments.
- **Dates:** bills and receivables carry invoice, due and settlement dates; aging runs from due dates.
- **Forecast:** versioned budgets by cost code (`budget.revise` approvals, hash-chained versions), full cost to date across subcontract, labor and reimbursables, estimate to complete, cost-code rollup and immutable snapshots.
- **Payee changes:** request, independent evidence recorded by a different person against a stored evidence revision, then a `party.verify_destination` approval for `bank_admin`. The one-call HTTP action is gone; the console self-test drives the governed flow.
- **Payment states:** processing and bank-reconciled states; a payment processing past three days fails the close checklist and appears in Ricky's brief.

## What review found and fixed (highlights)

- Assets could over-depreciate across duplicate period rows; banking could book a fee twice; WIP adjustments could double count. All fixed with month-keyed guards, live-journal checks and span rules.
- Restored copies could still write records and dispatch queued payments, an older backup could resubmit a transfer, raw SQL could unlock a locked period or extend a posted journal, and `INSERT OR REPLACE` could bypass triggers. All are now refused by SQLite (query-only connections, seal and period triggers) and by recovery that looks up queued intents.
- Retainage could be released before closeout, the same stored material could be claimed twice, and labor or reimbursement invoices left the AR control unreconciled. All fixed.
- An expired approval stayed "granted" after a failed execution, and one claim code opened every sibling copy at the same epoch. Expiry is now durable, and claim codes bind to a per-copy challenge.
- A credited bill was released for its full amount due, and customer deposits were missing from the close reconciliations. Both fixed and covered by gate G9.
- The container self-test found that a server restarted on an existing workspace reissued simulator reference `sim_000001`, so the new payment's settlement was discarded as a duplicate. The simulator now continues after the workspace's references, an acceptance under a reference another payment holds posts nothing and is held for review, and an event for a reference two payments hold is rejected.

## Not verified / remaining gaps

- **Claim attestation (G8 advisory):** without `CIPHER_OWNER_SECRET`, claiming a restored copy is attestation only (recorded and flagged by Ricky's brief). The container run above sets the secret; every deployment that opens restored copies must too.
- **Identity and roles:** roles are named by the caller; there is no people or role-grant registry yet (part of the production-identity gate).
- **High-risk payments:** no amount-based step-up, co-signature or new-payee cooling-off policy beyond the approval and the governed payee change.
- **Contracts:** executing a commitment is one approval; contract signature as a separate authority with insurance and bond evidence is not built.
- **Ricky SDK coverage:** the typed tool catalog covers the core and round-2 modules; AP intake, credits, deposits and budget revisions are reachable through approvals and the console but have no SDK tools yet.
- **V1 coverage:** the section-10 acceptance test does not yet walk procurement, hand-off, rights, assets or the SDK end to end, and there is no 20-bill corpus with approval-time metrics.
- **Accounting policy:** posting rules for revenue recognition, stored materials and disposals are SHADOW assumptions awaiting controller approval.
- **Core decision:** ERPNext has not been run against the same gates; this machine had about 4 GB free on 2026-10-12 against the owner's 250 GB free-space target, so a multi-GB ERP stack should not be pulled here.
- **Later plan gates:** authoritative accounting, production identity, real payment providers, bank connectivity, licensed-content ingestion, multi-entity and CAD automation.

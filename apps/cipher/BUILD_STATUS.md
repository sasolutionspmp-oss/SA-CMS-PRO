# Cipher prototype — verification record

Branch `cipher/synthetic-prototype`. Built by Claude from 2026-10-11 to 2026-10-12, continuing the Codex Cloud session "Set up SA-CMS-PRO", which stopped on a usage limit with its container work uncommitted. The plan (v1.0 package and v1.1 solo-first correction) is the specification. Modules were built by parallel agents, each followed by an independent adversarial review and a fix pass; integration, gates and docs were reconciled afterwards.

## Verified on 2026-10-12

| Check | Result |
|---|---|
| `python -m apps.cipher test` on Windows (Python 3.12) | 846 tests, OK, no expected failures |
| Same suite in WSL Ubuntu (Python 3.14) | 846 tests, OK |
| Container image build (`docker build`, suite runs inside on Linux) | 846 tests, OK; image runs non-root and reports healthy |
| Container serving with a token, driven by headless Chrome through token sign-in | console self-test 13 of 13 |
| Local console driven by headless Chrome (`tools/browser_check.py`) | 13 of 13 |
| Golden fixture (`python -m apps.cipher demo`) | bills 27,000 and 18,000; forecast 122,000; prime bill 54,000; one provider transfer; trial balance balanced; AP and AR reconciled |
| Plan section-10 V1 acceptance test (`tests/test_vertical_v1.py`) | all 12 steps pass end to end across every module |
| Plan section-10 adversarial variants (`tests/test_adversarial_variants.py`) | every listed variant fails safely or is routed to an owner |
| Accounting-core gates (`python -m apps.cipher.tools.core_gates`) | native core passes 9 of 9 hard gates and 110 of 110 checks; weighted 3.94 of 5 with four of five inputs labelled assumptions; ERPNext not evaluated |
| Dependencies | Python standard library only |

Tests per module: adversarial_variants 17, assets 30, banking 38, bills_controls 32, close 38, core 31, core_gates 36, drawings 25, estimates_controls 49, field 36, handoff 27, http 14, integrity 41, labor 37, ledger 15, payments_controls 51, payments_scope 27, procurement 29, receivables_controls 35, reimbursements 38, ricky_brief 6, ricky_sdk 60, rights 46, schedule 24, service_controls 14, vertical_v1 21, workflow 29.

## What review found and fixed (highlights)

- Assets could over-depreciate across duplicate period rows; banking could book a fee twice; WIP adjustments could double count. All fixed with month-keyed guards, live-journal checks and span rules.
- Restored copies could still write records and dispatch queued payments, an older backup could resubmit a transfer, raw SQL could unlock a locked period or extend a posted journal, and `INSERT OR REPLACE` could bypass triggers. All are now refused by SQLite (query-only connections, seal and period triggers) and by recovery that looks up queued intents.
- Retainage could be released before closeout, the same stored material could be claimed twice, and labor or reimbursement invoices left the AR control unreconciled. All fixed.
- An expired approval stayed "granted" after a failed execution, and one claim code opened every sibling copy at the same epoch. Expiry is now durable, and claim codes bind to a per-copy challenge.

## Not verified / remaining gaps

- **Supplier invoice intake:** bills are Cipher-generated progress certifications; there is no supplier invoice number/date intake, duplicate-invoice detection or PO–receipt–invoice matching yet (the plan's first production slice needs it).
- **Dates:** documents carry period and creation time, not separate document, service, due and settlement dates; aging uses creation dates.
- **Forecast:** commitments plus pending changes only; no labor, reimbursable or estimate-to-complete, no versions, no WBS or cost-code rollup.
- **Credits and corrections:** no supplier credit notes, posted-bill corrections, AR write-offs, credit memos or customer deposits.
- **Payee changes:** changing a destination and verifying it is one call with free-text evidence; payment intents have no processing or bank-reconciled states.
- **Claim attestation:** without `CIPHER_OWNER_SECRET`, claiming a restored copy is attestation only (recorded and flagged by Ricky's brief).
- **Accounting policy:** posting rules for revenue recognition, stored materials and disposals are SHADOW assumptions awaiting controller approval.
- **Core decision:** ERPNext has not been run against the same gates; this machine had about 4 GB free on 2026-10-12 against the owner's 250 GB free-space target, so a multi-GB ERP stack should not be pulled here.
- **Later plan gates:** authoritative accounting, production identity, real payment providers, bank connectivity, licensed-content ingestion, multi-entity and CAD automation.

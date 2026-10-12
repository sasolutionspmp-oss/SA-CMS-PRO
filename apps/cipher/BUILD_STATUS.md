# Cipher prototype — verification record

Branch `cipher/synthetic-prototype`. Rebuilt locally by Claude on 2026-10-11/12 after the Codex Cloud session "Set up SA-CMS-PRO" stopped on a usage limit with its container work uncommitted. The plan (v1.0 package plus the v1.1 solo-first correction) is the specification; the cloud session's reported results were used as targets, not copied.

## Verified

| Check | Result |
|---|---|
| `python -m apps.cipher test` (Windows, Python 3.12) | 174 tests pass: core 24, ledger 9, workflow + adversarial 28, HTTP 6, assets 30, schedule 24, drawings 25, reimbursements 28 |
| Same suite inside WSL Ubuntu (Python 3.14) | passes |
| Golden fixture (`python -m apps.cipher demo`) | 110,000 commitment; bills 27,000 and 18,000; forecast 122,000 vs 115,000; prime bill 54,000; one provider transfer across timeout, reconciliation and replay; trial balance balanced; AP and AR reconciled; audit chain intact |
| Browser workflow (`python -m apps.cipher.tools.browser_check`) | headless Chrome drives the console's self-test journey: 13 of 13 checks pass (refusal before grant, execution, bill certification, Ricky proposal, payment release with provider timeout, reconciliation, duplicate event ignored, books balanced) |
| Immutability and period locks | enforced by SQLite triggers on journals, audit log, provider events, document revisions, baselines, drawing revisions and depreciation runs; tested with raw SQL |
| Restore quarantine | restored copy opens without write authority; payment release blocked until recovery reconciliation; reconciliation finds the pre-restore transfer without creating a second one |
| HTTP boundary | approvals cannot be executed before grant; replays return stored results; bad input 400, unknown actions 404; generic module calls reject approval-bound entry points |
| Dependencies | none beyond the Python standard library |

## v2 modules: adversarial review outcome

Each module was implemented, then independently reviewed by an agent instructed to refute it, then fixed.

| Module | Review result | Fix |
|---|---|---|
| assets | HIGH: over-depreciation possible when several period rows cover the same calendar month (accumulated could exceed cost − salvage, disposal then unbalanced) | runs keyed by charge month with a partial unique index and triggers; amount clamped to the remaining depreciable base; fully-depreciated and no-charge paths re-checked at post time; tests added (30) |
| schedule | no correctness findings; low notes on torn reads under the threaded server and an untested trigger | reads taken under one transaction; trigger exercised directly; tests 24 |
| drawings | MEDIUM: issue approvals could be requested for revisions that can never be issued and stayed granted after a failed execute; MEDIUM: status guards covered UPDATE only | manifest refuses non-working revisions at proposal time; insert trigger constrains new revisions to `working`; number uniqueness case-insensitive in schema; tests 25 |
| reimbursements | no HIGH/MEDIUM findings; low notes on freeze-trigger coverage, missing correction path and test gaps | freeze trigger extended; reject/void paths and replay tests added; tests 28 |

The reviewers also flagged uncommitted edits to `server.py`, `console/index.html` and `tests/test_http.py`. Those were the orchestrator's own additions (generic `/api/modules` listing and `module_call` action), not agent overreach.

## Not verified / remaining gaps

- Container: `apps/cipher/Dockerfile` is written and the suite runs under Linux (WSL), but Docker Desktop on the build machine reports "unable to start" and never created its `docker-desktop` WSL distro, so the image build itself is unverified here.
- Accounting policy: the fixture's revenue recognition (certified progress billed = earned), the stored-material posting rule and the asset disposal rule (remaining book value to depreciation expense; no gain/loss account yet) are SHADOW assumptions awaiting controller approval, as the plan requires.
- Reimbursement payments post directly to the bank account rather than through the provider outbox; routing them through payment intents is a follow-up.
- Authoritative accounting, production authentication, real payment providers, bank connectivity, licensed content, multi-entity and CAD automation remain closed gates.

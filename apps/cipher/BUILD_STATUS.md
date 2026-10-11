# Cipher prototype — verification record

Branch `cipher/synthetic-prototype`. Rebuilt locally by Claude on 2026-10-11 after the Codex Cloud session "Set up SA-CMS-PRO" stopped on a usage limit with its container work uncommitted. The plan (v1.0 package plus the v1.1 solo-first correction) is the specification; the cloud session's reported results were used as targets, not copied.

## Verified now

| Check | Result |
|---|---|
| `python -m apps.cipher test` | 66 tests pass (core 24, ledger 9, workflow + adversarial 28, HTTP 5) |
| Golden fixture (`python -m apps.cipher demo`) | 110,000 commitment; bills 27,000 and 18,000; forecast 122,000 vs 115,000; prime bill 54,000; one provider transfer across timeout, reconciliation and replay; trial balance balanced; AP and AR reconciled; audit chain intact |
| Immutability and period locks | enforced by SQLite triggers, tested with raw SQL |
| Restore quarantine | restored copy opens without write authority; payment release blocked until recovery reconciliation; reconciliation finds the pre-restore transfer without creating a second one |
| HTTP boundary | console served; approvals cannot be executed before grant; replays return stored results; bad input returns 400, unknown actions 404 |
| Dependencies | none beyond the Python 3.12 standard library |

## Not verified / remaining gaps

- Browser workflow: the console exists and the API is tested, but no automated browser run has been recorded on this branch yet.
- Container: `apps/cipher/Dockerfile` builds and runs the suite, but the Docker engine was not running on the build machine when this record was written, so the image build is unverified here.
- v2 modules (asset register with depreciation, schedule with critical path, drawing register with issued/working revisions, staff reimbursements, schema upgrade lifecycle tests) are the next increment.
- Accounting policy: the fixture's revenue recognition (certified progress billed = earned) and the stored-material posting rule are SHADOW assumptions awaiting controller approval, as the plan requires.
- Authoritative accounting, production authentication, real payment providers, bank connectivity, licensed content, multi-entity and CAD automation remain closed gates.

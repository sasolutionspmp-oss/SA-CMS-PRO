# Cipher handoff

Written 2026-10-13, when Cipher moved from a Claude Code session to Codex. Read this first, then `AGENTS.md` (the rules), `BUILD_STATUS.md` (what was verified and the known gaps) and `README.md` (commands, modules and controls).

## Where it stands

- **Code:** `apps/cipher` on `main`, merged from `cipher/synthetic-prototype` through PR #27. Python standard library only.
- **Tests:** `python -m apps.cipher test` runs 1260 tests, all passing (Linux, Python 3.13, 2026-10-13). The console self-test passes 16 of 16, the core gates pass 9 of 9 with 127 of 127 checks, and the golden fixture and 20-bill corpus match their recorded numbers.
- **Built:** a synthetic, single-owner, single-entity engine:
  - ledger, approvals, the hash-chained audit log and restore safety;
  - AP and AR, payments through an outbox and simulator, banking, labor, procurement, field, close, assets, the accountant hand-off, content rights, supplier invoice intake;
  - three governor modules (`people`, `payment_policy`, `contracts`);
  - Ricky's SDK;
  - a test-bench HTTP console.
- **Reviewed:** four build rounds, each with adversarial review and fixes, then a cross-module critic (26 confirmed findings, all fixed but one declined) and a Codex review on the PR. `BUILD_STATUS.md` lists what each found.
- **Not built:** any real user interface. `docs/UI_OVERHAUL_SPEC.md` is the researched plan for one, and it waits on the owner.

## Waiting on the owner

The owner has not answered the 18 decisions in `docs/UI_OVERHAUL_SPEC.md`, Part A, section A6, or signed off the mockups (decision 12). Each decision there carries the team's recommendation. Several are facts to supply rather than choices: the Microsoft 365 license tier (10), the exact lime color and logo files (12), and the pilot job (15).

UI phase 1a (spec section 12.1) starts with mockups, which need decision 12 (colors and logo) and are themselves the sign-off for decision 1 (the direction). Decisions 3 to 7 set the approval limits, expiry and holds the screens enforce, so get them before building approval screens. Engine work in the next section does not wait on any of this, except where a row says so.

## Work queue

In priority order. "Done when" is the acceptance test to write first.

### 1. Pre-pilot blockers from the spec (section 11.2)

The spec lists 15 backend fixes; the first four block any use by real people. The spec was written on 2026-10-12, before round 4 was committed and reviewed, and these items were not re-checked against the code at handoff.

Treat all 15 as open, and confirm each against the code before starting. One is known to be partly done: item 11. The `people`, `payment_policy` and `contracts` modules are now committed, but `service.py` still skips a module that fails to import with only a warning. Make the loader fail loudly.

Items 1 and 2 (separate approving from posting; take execution away from Ricky's served tools) are engine changes that can start now. Items 3 and 4 (retire the old action API; derive identity from Microsoft 365 sign-in) go with decisions 13 and 10.

### 2. Known gaps from review

From `BUILD_STATUS.md`, "Not verified / remaining gaps":

1. **Approval expiry during a held release.** A 24-hour approval expires while a high-risk release waits out a co-signature or the cooling-off window, so the release needs a fresh approval, co-signature and step-up. This is the same work as per-operation expiry (spec 7.4 and 11.2 item 10). Done when a held release stays executable until its policy window ends plus a decide-by margin, with a test on the policy clock and the approvals clock moved together.
2. **Governed labor corrections.** `journal.reverse` now refuses labor timesheet and payroll journals; there is no governed way to correct them. Add a labor operation that reverses an approved timesheet or a posted payroll, keeps the accruals and the payroll subledger reconciled, and frees the time for rebilling. The schema's CHECK constraints need a new named entry, as in `labor_rebill_after_reversal`.
3. **Coverage at send time.** Contracts check insurance and bond coverage when a payment is released to the outbox, not when the outbox sends it. Re-check at dispatch and hold the intent if coverage lapsed.
4. **Split spending.** The payment policy classifies one obligation at a time, so splitting spend across separate claims or bills is not added up. Needs a policy term (per payee, per period) and the owner's view on thresholds.
5. **Depreciation before capitalization.** A depreciation run can be scheduled in a period that starts before the asset's capitalization journal when the in-service date falls in it. Refuse it as disposals and reversals already are.
6. **Audit log index.** Governor and integrity checks scan the audit log, which has no index. Add one through a new named schema entry before data grows.
7. **Redaction by structure.** SDK destination redaction matches key names, with a fallback for hashes next to a destination value. Mark destination-derived fields where they are built instead.
8. **Acceptance coverage.** Neither acceptance walk exercises labor, field, drawings, schedule or reimbursements under an enforcing identity policy. Extend `tests/test_vertical_extended.py`.
9. **Container image.** The image was last rebuilt and self-tested before round 4. Rebuild with `docker build -f apps/cipher/Dockerfile -t cipher-prototype .` and rerun the token sign-in self-test from `README.md`.
10. **Core decision.** ERPNext was never run against `tools/core_gates.py`; the gates have an adapter slot for it. Needs a machine with tens of gigabytes free.

### 3. After the owner's decisions

UI phase 1a per spec section 12.1: mockups first (shell, PM home, job overview, a subcontract, the pay app review grid and the approval page, at 1440, 1024 and 390 px, on practice data), then Microsoft 365 sign-in, the new API layer and the screens. The old console must never run against live data (decision 13).

## How work was done here

- One change, one failing test, one fix, then the full suite. Each build round ran parallel agents, each followed by an independent adversarial review that re-ran the reproductions; findings only counted once reproduced.
- `BUILD_STATUS.md` is the verification record. Update its counts and gap list only with numbers you ran.
- In a small container, give parallel agents sparse worktrees (`git worktree add --no-checkout <dir> <commit>`, then `git -C <dir> sparse-checkout set --cone apps/cipher` and `git -C <dir> checkout`): about 6 MB each instead of 1.4 GB.
- The browser check needs Chrome or Chromium; set `CIPHER_CHROME` to its path.

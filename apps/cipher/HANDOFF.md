# Cipher handoff

Written 2026-10-13, when Cipher moved from a Claude Code session to Codex. Read this first, then `AGENTS.md` (the rules), `BUILD_STATUS.md` (what was verified and the known gaps) and `README.md` (commands, modules and controls).

For ongoing delivery, use [docs/DELIVERY_BACKLOG.md](docs/DELIVERY_BACKLOG.md): six usable milestones, their acceptance gates and the next 15 work items. B01's separate bill approval/posting engine is implemented as specified in [docs/BILL_POSTING_SPLIT_PLAN.md](docs/BILL_POSTING_SPLIT_PLAN.md), including bill-specific duties from B02. B03 adds immutable audited practice mode, provider guards and safe historical opening/claims. The [B04/B05/B09/B11 AP slice](docs/AP_PRACTICE.md) connects scoped practice sessions, installed-work bill preparation, owned invoice evidence, receipt/matching, independent match review and repeatable bill request/grant/post actions to Fluent. Its [exception extension](docs/AP_EXCEPTIONS.md) adds invoice revision, final rejection, documented duplicate review, draft cancellation, original-PM withdrawal and independently approved unpaid-bill correction followed by a separate fresh replacement. The accounting extension adds original-obligation plans, independent handoff authorization, fixed simulated delivery and separate readback. The full 2017-test backend milestone passes; current browser evidence is recorded in `BUILD_STATUS.md`. Claimed-versus-reviewed pay app revisions, PO/stored-material exceptions, supplier credit screens, payments, other operation duties and real identity remain open.

The current [product goal](docs/PRODUCT_GOAL.md) records the owner's full scope: Cipher owns proposals, estimating/takeoffs, all AP/AR business work, projects/CMS, engineering and specification/contract libraries, with a Fluent 2 interface and an accounting adapter. Internal completion and enterprise qualification are separate evidence gates. Follow the existing UI templates across those workflows; enterprise quality is an architectural direction, not a readiness claim.

The owner confirmed QuickBooks use and prior Odoo catch-up work on 2026-10-14. The recovered September architecture assigned operations to Odoo; the latest instruction expands Cipher's business workflow ownership. Recover and reuse accepted Odoo data/configuration through explicit adopt/import/adapter mappings and stable source IDs. QuickBooks stays accounting authority until a separately agreed cutover; preserve the established BILL route while its handoff is mapped and tested. This checkout's synthetic tests do not verify the latest Odoo reconciliation checkpoint. Recovery of that evidence can proceed alongside Cipher control and UI work.

Read-only connected product metadata confirms **QuickBooks Online Advanced**. The product choice is settled; [docs/QUICKBOOKS_ADAPTER_PLAN.md](docs/QUICKBOOKS_ADAPTER_PLAN.md) defines sources, one-effect mappings, governed handoff, unknown outcomes and reconciliation. Metadata capability declarations do not qualify delivery. Actual realm/transport/authentication, sandbox mappings and controller policies remain integration facts to recover. The connector company ID and CompanyInfo singleton ID are not OAuth realm IDs.

## Where it stands

- **Code:** `apps/cipher` on `cipher/synthetic-prototype`, in open PR #27. The original handoff incorrectly said it had merged; GitHub still showed it open when Codex resumed on 2026-10-14. Python standard library only.
- **Tests:** the full discovery used by `python -m apps.cipher test` passes 2017 unique tests (Linux, Python 3.12, 2026-10-14; 928.845 seconds), including 150 new accounting domain/simulator/service/contract/action/HTTP/review/upgrade cases. All Python source remained unchanged during discovery. Console 20/20; core gates 9/9 and hard checks 127/127. Golden business results and the complete corpus remain unchanged. Schemas 1–69 are exact; genuine 69/70 receipts, journal and accepted/readback history survive schemas 70–71. Four upgrade/rollback tests and 57 copy/core tests pass. Current Fluent accounting and existing AP/intake/exception/read coverage and limits are recorded in `BUILD_STATUS.md`.
- **Built:** a synthetic, single-owner, single-entity engine:
  - ledger, approvals, the hash-chained audit log and restore safety;
  - AP and AR, payments through an outbox and simulator, banking, labor, procurement, field, close, assets, the accountant hand-off, content rights, supplier invoice intake;
  - three governor modules (`people`, `payment_policy`, `contracts`);
  - journal-free bill business grants, independent explicit posting and audit-backed immutable posting receipts;
  - installed-work invoice revision/rejection/duplicate review and bill cancellation/withdrawal, plus independently approved unpaid-bill working-ledger corrections with separately prepared replacements;
  - original posted-obligation accounting plans, independent authorization, owned memory-only simulated delivery and original-UUID recovery/readback;
  - immutable audited workspace mode, foreign/live startup refusal and initialized simulator-only payment boundaries;
  - Ricky's SDK;
  - a test-bench HTTP console.
- **Reviewed:** four build rounds, each with adversarial review and fixes, then a cross-module critic (26 confirmed findings, all fixed but one declined) and a Codex review on the PR. `BUILD_STATUS.md` lists what each found.
- **Practice interface:** the Fluent 2 read slice under `web/` retains its separate read-only backend. The AP entry has a fresh in-memory workspace and the same registered synthetic accountant/reviewer/PM sessions. Installed work is prepared, an owned invoice source is received/matched, a separate accountant grants the match, and the bill proceeds through journal-free PM business approval and independent accountant posting. Invoice exceptions and unposted withdrawals create no journal or payable. Only approved correction execution reverses the eligible unpaid bill's working journals, in an open period no earlier than its original actual posting; replacement certification, matching, PM review and posting remain separate acts. The accounting extension preserves the original cost/AP/retainage entry and actual posting period, adds independent accountant handoff review, and separately runs simulated delivery/lookup/readback. All 24 fixed actions use scoped pure reviews, original audited outcomes and shared per-person repeatability protection. Schemas 70–71 append after unchanged schemas 1–69, preserving original receipt contents. Current copied-file review preserves bytes and initializes no worker; file-workspace delivery is refused. Payment actions, authenticated staff identity, document upload, PO/stored-material exception screens and live integrations remain open. `docs/UI_OVERHAUL_SPEC.md` supplies the shared templates; final owner acceptance remains open.

The [practice accounting handoff](docs/ACCOUNTING_PRACTICE.md) implements audited synthetic mappings, immutable original posted-bill plans, distinct independent accountant authorization, fixed simulated delivery/lookup and separate readback reconciliation. Its seven new actions bring the AP contract to 24 commands with shared repeatability protection. Unknown outcomes use the original UUID; receipt-completion failures cannot justify a new submission. The worker and simulator store belong to the fresh in-memory process, and file-workspace delivery is refused. Schemas 70–71 append after the unchanged 1–69 prefix. This does not qualify QuickBooks delivery or replace official books.

Continue with [connected estimating and subcontract handoff](docs/COMMERCIAL_DELIVERY_PLAN.md): fix shared accepted-estimate provenance, connect owned drawing/manual quantities to estimate revisions, require independent actual estimator acceptance, then preserve the accepted priced source in a reviewed draft subcontract. Customer proposal issue/send, project award/budget adoption and signatures remain distinct future acts. Recover accepted Odoo/BILL checkpoints alongside the connected workflow builds; do not wait for a finance cutover to build the required commercial, CMS and engineering/library tracks.

## Waiting on the owner

The owner has directed use of Fluent/Fluent 2 and the initial design guidelines, including a functional backend linked to the interface. That supplies the direction for A6 decisions 1–2 and practice implementation. Other financial policies, hosting facts and final mockup acceptance remain open; recommendations in the original 18-decision table are not adopted automatically. Several inputs are facts to recover or supply: the Microsoft 365 license tier (10), final lime/logo assets (12), and pilot job (15). Independent work proceeds while those are pending.

UI phase 1a (spec section 12.1) starts with mockups, which are themselves the sign-off for decision 1 (the direction). Drafts for review can use the spec's placeholder colors and a temporary wordmark; final branding and mockup acceptance remain decision 12. Decisions 3 to 7 set the approval limits, expiry and holds, so get them before finalizing those policies. Engine work, API contracts and draft mockups can proceed in parallel while these answers are pending.

Fluent UI requires no Microsoft sign-in. Microsoft Entra ID is the planned staff identity provider: it must prove which person performs consequential actions before operational use by staff. Tenant/app setup does not block engine work or synthetic UI design. The Microsoft 365 license fact determines available tenant controls, including stronger step-up options, rather than permission to use Fluent components.

## Work queue

In priority order. "Done when" is the acceptance test to write first.

### 1. Pre-pilot blockers from the spec (section 11.2)

The spec lists 15 backend fixes; the first four block any use by real people. The spec was written on 2026-10-12, before round 4 was committed and reviewed, and these items were not re-checked against the code at handoff.

Confirm each item against the code before starting. Codex's first continuation addressed item 11 (configured module failures now stop startup) and item 13 (grant preflight checks are read-only, with self-approval records committed atomically with successful grants). Item 2 is partly addressed: the HTTP Ricky catalog and invocation route allow only explicit read and draft tools, reject execution, approval requests and payment reconciliation with a typed 403, and block the generic SDK module-call bypass. The standalone SDK keeps its synthetic execution tools. The separate AP API derives its synthetic person and duties from scoped sessions; the operational API and authenticated staff identity remain pending. The remaining items stay open.

Item 1 (separate approving from posting) is addressed in the synthetic engine. Bill grants create no journals; an independent accountant/controller posts under the original authorization, and the old combined bill execution is refused. Schema 65 preserves historical schema text and authentic pre-split postings. The separate practice API derives registered synthetic people and duties from its session; item 2's operational gate still requires validated staff sessions. Items 3 and 4 (retire the old action API; derive identity from Microsoft 365 sign-in) go with decisions 13 and 10.

### 2. Known gaps from review

From `BUILD_STATUS.md`, "Not verified / remaining gaps":

1. **Approval expiry during a held release.** A 24-hour approval expires while a high-risk release waits out a co-signature or the cooling-off window, so the release needs a fresh approval, co-signature and step-up. This is the same work as per-operation expiry (spec 7.4 and 11.2 item 10). Done when a held release stays executable until its policy window ends plus a decide-by margin, with a test on the policy clock and the approvals clock moved together.
2. **Governed labor corrections.** `journal.reverse` now refuses labor timesheet and payroll journals; there is no governed way to correct them. Add a labor operation that reverses an approved timesheet or a posted payroll, keeps the accruals and the payroll subledger reconciled, and frees the time for rebilling. The schema's CHECK constraints need a new named entry, as in `labor_rebill_after_reversal`.
3. **Coverage at send time — addressed.** Dispatch rechecks current audited insurance and bond coverage under its claim lock. Expired, withdrawn, revised or tampered evidence holds the queued intent and pending outbox without a provider attempt; valid replacement coverage permits retry of the same intent.
4. **Split spending.** The payment policy classifies one obligation at a time, so splitting spend across separate claims or bills is not added up. Needs a policy term (per payee, per period) and the owner's view on thresholds.
5. **Depreciation before capitalization — addressed.** Positive-charge scheduling and posting refuse periods starting before the capitalization journal's period, including existing draft runs. Existing posted history is not repaired. Prior open depreciation approvals need renewal because their manifests now bind this rule.
6. **Audit log index — addressed.** A new schema entry appends entity/sequence and action/sequence indexes after all historical entries. Existing-workspace upgrades preserve their schema checksums and audit chain; copied workspaces remain read-only.
7. **Redaction by structure.** SDK destination redaction matches key names, with a fallback for hashes next to a destination value. Mark destination-derived fields where they are built instead.
8. **Acceptance coverage.** Neither acceptance walk exercises labor, field, drawings, schedule or reimbursements under an enforcing identity policy. Extend `tests/test_vertical_extended.py`.
9. **Container image — addressed.** Rebuilt on 2026-10-14 with 1320 tests passing. Restrictive checkout permissions are normalized so the non-root server can read its application files. A volume seeded by the prior PR head upgrades to schema 64 and passes token sign-in 16 of 16 before and after restart, with a healthy server running as UID 10001.
10. **Historical core comparison.** ERPNext was never run against `tools/core_gates.py`; the gates have an adapter slot for it. That is a prototype evidence limit, not a prerequisite for continuing the established Odoo/QuickBooks architecture. Reopen a finance-core comparison only if a replacement is selected later.

### 3. After the owner's decisions

The connected practice shell and AP screens follow the spec's templates at 1440, 1024 and 390 px. Continue the claimed/reviewed grid and other required mockups, obtain owner visual acceptance, then qualify Microsoft 365 staff sign-in, the operational API and deployment before real-user use. The old console must never run against live data (decision 13).

## How work was done here

- One change, one failing test, one fix, then the full suite. Each build round ran parallel agents, each followed by an independent adversarial review that re-ran the reproductions; findings only counted once reproduced.
- `BUILD_STATUS.md` is the verification record. Update its counts and gap list only with numbers you ran.
- In a small container, give parallel agents sparse worktrees (`git worktree add --no-checkout <dir> <commit>`, then `git -C <dir> sparse-checkout set --cone apps/cipher` and `git -C <dir> checkout`): about 6 MB each instead of 1.4 GB.
- The browser check needs Chrome or Chromium; set `CIPHER_CHROME` to its path.

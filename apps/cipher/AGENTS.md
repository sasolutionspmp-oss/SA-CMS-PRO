# Agent rules: Cipher (`apps/cipher`)

Read `HANDOFF.md` first for where the project stands and what to do next. These rules keep existing workspaces, the audit log and the controls intact. Breaking one usually fails a test, and sometimes only fails a real workspace later.

## Run and verify

From the repository root, Python 3.12 or later, no installs:

```bash
python -m apps.cipher test                       # full suite; verified count in BUILD_STATUS.md
python -m unittest apps.cipher.tests.test_people # one module's tests while you work
python -m apps.cipher demo                       # golden fixture; numbers listed in README.md
python -m apps.cipher.tools.core_gates           # 9 hard gates, 127 checks
python -m apps.cipher.tools.corpus               # 20-bill corpus; tests/test_corpus.py pins its exact report
CIPHER_CHROME=/path/to/chrome python -m apps.cipher.tools.browser_check   # console self-test, 20 steps
python -m apps.cipher practice-web --port 8766   # isolated read-only backend plus built Fluent app
python -m apps.cipher ap-practice-web --port 8767 # isolated synthetic AP request/approve/post workflow
python -m apps.cipher commercial-practice-web --port 8768 # isolated manual estimate-to-subcontract workflow
python -m apps.cipher ar-practice-web --port 8769 # isolated owner billing, posting and synthetic send
python -m apps.cipher library-practice-web --port 8770 # exact authored text and internal project references
python -m apps.cipher rfi-practice-web --port 8771 # governed responses and synthetic RFI distribution
```

Read `docs/PRODUCT_GOAL.md` for the owner's full scope and internal/enterprise quality gates. `web/` is the pinned Fluent 2 practice client; Node is a build tool, and web dependencies never become engine dependencies. Its `README.md` lists typecheck/build/browser commands. The read practice server owns a fresh in-memory fixture and no action or file-workspace routes. The separate AP practice server admits 24 fixed scoped commands: nine preparation/intake/match/bill commands, eight invoice exception/cancellation/correction commands, and seven practice accounting preparation/authorization/worker commands. It uses seeded owned evidence and the same registered synthetic people; neither server selects a file workspace or mounts live records. See `docs/AP_EXCEPTIONS.md` for governed correction/separate replacement, `docs/ACCOUNTING_PRACTICE.md` for the original obligation and memory-only simulated worker/recovery boundary, and `docs/COMMERCIAL_PRACTICE.md` for the separate seven-action manual estimate-to-subcontract workflow. Its registered estimator/reviewer/PM sessions retain exact source lineage, independent acceptance and draft-only handoff. All AP/commercial/AR actions share per-person repeatability protection; the AP allowlist remains 24 commands. The separate seven-action AR entry adds declared owner/SOV sources, claimed/reviewed lines, journal-free business approval, independent posting under the same grant and separately approved synthetic send. See `docs/OWNER_BILLING_PRACTICE.md` for implemented controls and `docs/OWNER_BILLING_PLAN.md` for the original design and remaining AR work. Existing UI templates and initial guidelines apply across commercial, estimating, CMS and engineering/library screens.

| Entry | Fixed actions | Practice result | Port |
|---|---:|---|---:|
| AP, intake, exceptions and accounting |24| Installed-work/invoice matching, business grant and independent posting, governed correction, separate simulated accounting delivery/readback |8767|
| Commercial |7| Manual source-priced estimate revisions, independent estimator acceptance and source-preserving PM subcontract draft |8768|
| Owner billing / AR |7| Claimed/reviewed owner pay app, journal-free grant, independent same-grant posting and separately approved synthetic send |8769|
| Authored library |6| Exact UTF-8 revisions and independently reviewed project reference copy |8770|
| RFI |9| Issued drawing/supporting citations, draft response, independent official answer and separate synthetic distribution |8771|

Every write entry owns a separate fresh memory practice workspace and synthetic registered people. Current own project duties precede private source/replay access; independent review and the original grant govern consequential effects. Original receipts stay distinct from current source/rights/lifecycle facts. All 53 fixed commands across the separate entries share a per-canonical-person UUID namespace when composed in one workspace; the AP allowlist itself remains 24.

QuickBooks remains the official accounting authority while Cipher owns the proposed commercial, AP/AR and project/CMS workflows. The accounting adapter and worker remain an owned memory-only simulator; live providers, bank connectivity, file/process-restart worker durability and official QuickBooks delivery are unqualified. Manual quantities do not establish calibrated geometry. RFI answers are not engineering stamps, library adoptions are internal references rather than executed contracts, and hash-only drawing/document evidence does not supply PDF/CAD artifact bytes. Library-authored UTF-8 text is actually stored. Licensed ingestion/distribution, external signatures/delivery, operational identity, original copyright and record-retention policies, production performance, manual screen-reader review and enterprise acceptance remain future qualification.

Fluent components require no Microsoft sign-in; operational identity is a separate gate. Owner financial-policy/factual decisions do not block already authorized synthetic Fluent implementation.

The full suite must pass before every commit. For a bug, first write a test that fails on the current code, then fix it.

## Hard rules

1. **Standard library only.** No third-party packages in the engine. The UI spec (decision 2) allows packages for a future web layer only, pinned and listed.
2. **Never edit an existing schema entry.** Each module registers named entries (`SCHEMA_NAME`, `SCHEMA_STATEMENTS`, and later `*_SCHEMA_NAME` entries) through `core.db.register_schema_version`. Workspaces store a checksum of every applied entry's text, so changing one breaks every existing workspace. To change tables or triggers, add a new named entry after the module's last one. `labor_rebill_after_reversal` in `domain/labor.py` is a worked example: it drops and recreates triggers under the same names.
3. **Never reorder `service.PLUGIN_MODULES`.** Load order fixes canonical catalog registration. Native workspace migrations match entries by name, and genuine physical application positions can differ; preserve exact named SQL/count/checksum and the bounded actual prefix through that admission. Add new modules at the end. A configured module that fails to import or initialize stops startup; after adding or renaming one, check that its tests ran.
4. **Stored codes keep their first spelling.** Status values, column and trigger names, operation codes and audit action codes are stored and hash-chained, for example `asset.capitalise`. Never rename one. You may add new codes. `core/words.py` translates stored codes for anything a person reads; route new British-spelled codes through it if you must add one.
5. **American English** in code, comments, docstrings, messages and docs, and US formats for dates and money.
6. **Every consequential action goes through an approval.** A request builds a server-side manifest (operation, subject, role, amounts, record versions and hashes, payee destination, policy version, expiry). A person grants it, and execution re-checks the manifest. Any material change makes the approval stale. Add new effects as `manifest_for` and `apply` on the module's `Plugin` (contract at the top of `service.py`), never as a direct write. Bills deliberately use one journal-free `bill.approve` business grant followed by an explicit independent `post_bill` command that consumes it; never restore combined bill execution, invent a second approval or invent fixture actors. Posting requires an actual accountant/controller duty, and owner authority cannot override person separation.
7. **The audit log wins.** Governor modules (`people`, `payment_policy`, `contracts`) check their rows against the hash-chained audit log, and a mismatch fails closed. New governor state needs the same treatment: record an audit entry, and verify the row against it in the module's integrity and `close_checks`.
8. **Ricky never decides.** Ricky (`domain/ricky.py`, `ricky_sdk.py`) previews, drafts and executes only approvals a person already granted. It never grants, rejects, changes policy, roles, delegations or payee destinations, or posts without an approval. The routing completeness test fails unless every approval-bound operation is either reachable through the SDK or listed in `RESTRICTED_OPERATIONS` with a reason.
9. **No real money and no real data.** One owner, one USD entity, synthetic data, a simulated payment rail and shadow finance. Never wire a real provider, bank or production identity without the owner's decision.
   Workspace mode is immutable and checked against its original audit declaration. This release admits only practice; live files are refused before initialization. Never promote practice, accept a caller's liveness flag or bind an unqualified provider. Known legacy copies remain undeclared/read-only until an attested owner claim. Claims require a standalone transaction because the authority sidecar cannot follow an outer SQLite rollback.
10. **Escape everything in the console.** `console/index.html` escapes server data once on arrival (`escDeep`) and encodes handler arguments with `js()`. `ConsoleEscapingTests` in `tests/test_http.py` guards the pattern. Keep it when editing the console.

## Threat model the tests use

Callers act through module, service, SDK and HTTP APIs. A stronger attacker may run raw SQL against the SQLite file, including dropping triggers. Integrity checks and close checks are expected to catch that tampering, and the controls must fail closed. Restored or copied workspaces open read-only until the owner claims them.

## Layout

```
core/       money, ids, db (schema catalog, triggers, write authority), audit (hash chain), approvals, commands and outbox, words
domain/     core modules: ledger, evidence, estimates, commitments, bills, receivables, payments, forecast, ricky
            plugin modules: assets, schedule, drawings, reimbursements, banking, labor, procurement, field, close, handoff, rights, ap_intake
            source governors: accounting, commercial, owner_billing, library, rfi_controls
            policy governors: people, payment_policy, contracts
service.py  Cipher facade: request, approve, execute; plugin loading and routing; golden fixture
server.py   standard-library HTTP API and console host
ricky_sdk.py  Ricky's typed tool catalog, receipts and identity checks
console/    test-bench owner console (synthetic data only; slated for replacement)
tools/      browser_check.py, core_gates.py, corpus.py
docs/       CORE_COMPARISON.md, UI_OVERHAUL_SPEC.md
tests/      one file per module, plus integrity, workflow, V1 and extended acceptance, corpus, adversarial variants and HTTP
```

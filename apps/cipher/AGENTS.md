# Agent rules: Cipher (`apps/cipher`)

Read `HANDOFF.md` first for where the project stands and what to do next. These rules keep existing workspaces, the audit log and the controls intact. Breaking one usually fails a test, and sometimes only fails a real workspace later.

## Run and verify

From the repository root, Python 3.12 or later, no installs:

```bash
python -m apps.cipher test                       # full suite, 1471 tests
python -m unittest apps.cipher.tests.test_people # one module's tests while you work
python -m apps.cipher demo                       # golden fixture; numbers listed in README.md
python -m apps.cipher.tools.core_gates           # 9 hard gates, 127 checks
python -m apps.cipher.tools.corpus               # 20-bill corpus; tests/test_corpus.py pins its exact report
CIPHER_CHROME=/path/to/chrome python -m apps.cipher.tools.browser_check   # console self-test, 20 steps
python -m apps.cipher practice-web --port 8766   # isolated read-only backend plus built Fluent app
```

Read `docs/PRODUCT_GOAL.md` for the owner's full scope and internal/enterprise quality gates. `web/` is the pinned Fluent 2 practice client; Node is a build tool, and web dependencies never become engine dependencies. Its `README.md` lists typecheck/build/browser commands. The practice server owns a fresh in-memory fixture and no action or file-workspace routes; do not mount it on live records. Existing UI templates and initial guidelines apply to later commercial, estimating, CMS and engineering/library screens.

The full suite must pass before every commit. For a bug, first write a test that fails on the current code, then fix it.

## Hard rules

1. **Standard library only.** No third-party packages in the engine. The UI spec (decision 2) allows packages for a future web layer only, pinned and listed.
2. **Never edit an existing schema entry.** Each module registers named entries (`SCHEMA_NAME`, `SCHEMA_STATEMENTS`, and later `*_SCHEMA_NAME` entries) through `core.db.register_schema_version`. Workspaces store a checksum of every applied entry's text, so changing one breaks every existing workspace. To change tables or triggers, add a new named entry after the module's last one. `labor_rebill_after_reversal` in `domain/labor.py` is a worked example: it drops and recreates triggers under the same names.
3. **Never reorder `service.PLUGIN_MODULES`.** Load order assigns schema version numbers. Add new modules at the end. A configured module that fails to import or initialize stops startup; after adding or renaming one, check that its tests ran.
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
            governors: people, payment_policy, contracts
service.py  Cipher facade: request, approve, execute; plugin loading and routing; golden fixture
server.py   standard-library HTTP API and console host
ricky_sdk.py  Ricky's typed tool catalog, receipts and identity checks
console/    test-bench owner console (synthetic data only; slated for replacement)
tools/      browser_check.py, core_gates.py, corpus.py
docs/       CORE_COMPARISON.md, UI_OVERHAUL_SPEC.md
tests/      one file per module, plus integrity, workflow, V1 and extended acceptance, corpus, adversarial variants and HTTP
```

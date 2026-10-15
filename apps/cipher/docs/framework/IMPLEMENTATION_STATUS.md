# Cipher implementation status

Owner authorized execution of the framework. Worktree: /workspace/cipher-framework-draft; branch: cipher/framework-final-draft. New product design is independent of all prior Cipher/Odoo implementations.

## Implemented and exercised in the real runtime

- Persistent ERPNext 16.51.0/Frappe 16.52.0, MariaDB and Redis; the new `cipher_aec` app installs and migrates. The UI runs at `http://127.0.0.1:18880` through the same origin as its session/API.
- Canonical people and alias identities, company/project duties, versioned commands, immutable receipts/history, signed cursor pagination and project/task services use actual ERPNext records.
- Document originals and immutable revisions store bytes, enforce authorized download, extract text/PDF source citations, and support exact scoped search. Development files remain explicitly `not_scanned`.
- Ricky persists runs, steps and proposals; tools use current permissions, transaction boundaries, cancellation/fencing and source provenance. The existing local model endpoint/tool contract is still unavailable. Normal use reports that state; explicit test adapters are separately labeled.
- The durable local outbox survived publication failure, worker death before commit and stale-worker fencing. It is qualified for the implemented internal Task effect, not external accounting or payments. It has no normal public enqueue route and checks current identity/duties; a future public workflow must supply its session or durable-delegation authority contract. Ricky's existing public run path separately checks its original session authority.

## Recorded acceptance

- Actual HTTP journey: 11 groups and 90 requests passed, including CSRF, concurrent retry, stale versions, private counts, signed cursors, UTC history and legacy RPC bypass denial.
- Restart retained original Task receipts/retries, document bytes/citations and Ricky run status.
- Source-specific revocation, complete project revocation, read-only Task authority and closed-project replay/new-command behavior passed for both aliases. Independent database probes confirm unauthorized assignment attempts created no ToDo and changed no Task assignment/version.
- Two isolated backup/restore rehearsals retained data and exact artifact bytes while execution quarantine blocked new effects and dispatch. The latest rehearsal also verifies the backup's encryption key was preserved without exposing it.
- Backend integration: 20 real Frappe/MariaDB cases passed; transport primitives: 10 cases passed. Documents: 13 tests. Ricky: 27 unit cases plus actual database transactional/failure acceptance. Outbox: nine real isolated-worker fault/recovery checks. These are recorded results for their captured source, not automatic acceptance of later edits.
- Astra's targeted review approved the fixes for its original findings. Actual browser captures at 1440, 900 and 390 pixels passed with keyboard sign-in/navigation, aligned UI5 tables and zero uncaught browser errors. [Project workspace](evidence/r0/browser/connected-project-object-page.png), [documents](evidence/r0/browser/connected-document-register.png), and [phone view](evidence/r0/browser/connected-project-register-mobile.png) show persisted synthetic data. Served bundle/source snapshots bind these captures independently of subsequent interface work; browser fixture tests remain separate.

Evidence is under [evidence/r0](evidence/r0). `platform/operations/record-evidence.py` inventories source and artifact hashes and identifies recorded sources changed since capture; it does not declare a release passed.

## Active implementation

GOV-03 now has 12 actual approval tests and a separate two-connection concurrency proof. Its real browser journey requested, independently reviewed and executed two Project status transitions, restoring Open with all 14 Tasks unchanged. MIG-01 has 18 contract tests, native ERPNext acceptance and 11 actual HTTP calls covering strict response schemas, validation, preview, native Export permissions and revocation without applying imports. API-01 has a generated OpenAPI 3.1 catalog, validated with a real OpenAPI validator and JSON Schema reference resolution.

EST-01 passed final native-source and replay-authority acceptance, with exact persistent rate/assembly/revision/calculation snapshots. Actual HTTP qualification passed 34 checks, 43 response-schema validations and 55 requests; the checked sources received Astra's targeted approval. Evidence is under [evidence/r1](evidence/r1).

QA-01's complete [fresh-site validation](evidence/r0/fresh-validation.json) passed in 171.758 seconds against unchanged source. It installed and migrated a unique ERPNext/Frappe site, passed all 116 declared application tests (32 native integration and 84 ordinary unit tests) with zero failures/errors/skips or missing cases, passed all four extended database/worker acceptance fixtures, and passed a clean frontend install, generated-client comparison, typecheck/build and all 17 browser contract tests. Earlier reports preserve the stale generated OpenAPI failure and the two corrected test-runner collection/entry-point errors. The pinned GitHub workflow exists; hosted execution remains a separate qualification.

The next implementation wave adds company-only commercial duties and shared commands for pursuits before a Project exists, followed by COM-01. FIN-01, EST-02 and the estimating draft workspace proceed in parallel through their existing contracts. The existing prototype's separate 2,703-test preservation suite passed; that count is not new-product acceptance evidence.

R0 is not declared complete while these remaining contracts and checks are active. COM-01 and FIN-01 wait for their declared governance/master prerequisites. No live accounting, payment or external message delivery is enabled. R1–R5 remain the approved scope and follow the dependency graph; current development acceptance is not a production or enterprise-readiness claim.

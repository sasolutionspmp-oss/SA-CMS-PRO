# Browser CI diagnostic correction

The hosted run for application checkpoint `f709a336ea2ad5f1686c38c0701cde5cb61d811f` failed in `frontend-browser-contracts`. The original runner raised before reading Playwright JSON, leaving the individual failing assertion unavailable. [Hosted provenance](company-com02-hosted-validation-provenance.json) preserves that failed run and the exact reported error. Its cause remains unresolved; this correction does not claim to fix the application or browser test.

The reviewed change reads the existing report after a browser-process failure and publishes bounded, sanitized case identity, status and assertion categories. The original exception and failed exit remain intact. Raw assertion values, source snippets, stack traces, URLs, credentials and attachments remain private. It introduces no retry, skip, altered UI or relaxed assertion. Eleven pure parser cases cover failed, malformed, missing, oversized and truncated reports, report-level errors, redaction and preservation of the original failure.

A separate container used an archive of the exact application checkpoint plus only these three reviewed files:

- `apps/cipher/platform/operations/validate_new_stack.py` — SHA-256 `702bd6c4fe5d20469237de6a4cc315cb6880e3c5032428105fdabe9808688bed`.
- `apps/cipher/platform/operations/README.md` — SHA-256 `b8a16169aa6279258464f4d8bad5ff6caf0352c937be1350788380db2136e3ca`.
- `apps/cipher/platform/operations/tests/test_browser_failure_report.py` — SHA-256 `33193e14a3a3c29681dd539e61545511190f8acda6a65a6646f52546f78a8a32`.

All 491 tracked base paths were compared against the archive. Only the runner and its operations README changed; the reporting test module is new. Application, UI, browser assertions and hosted workflow remain byte-identical to `f709a336`. In-progress domain changes in the shared worktree were excluded.

The [fresh isolated validation](ci-browser-diagnostics-fresh-validation-20261015T2140Z.json) passed in 428.437 seconds: 315 unique backend cases (52 native integration and 263 ordinary units), seven canonical acceptance procedures, four actual process-lifecycle checks, eleven reporting-parser checks, clean generated-client/typecheck/build and 100 browser scenarios. All 22 stage logs match their recorded hashes; all 488 captured source paths remained unchanged. There were no errors, failures, missing/skipped cases or flaky browser results. The takeoff canonical procedure retains its existing parser-only scope; connected workflow evidence is separate.

The local run used system Chromium 151.0.7922.173 and frontend Node 24.19.0. Hosted CI uses Node 24.22.0 and installs Playwright's managed browser through its existing workflow. This local pass does not establish that the hosted failure is resolved. The next hosted run must supply the missing case/diagnostic or independently pass, and either outcome will be recorded without rewriting the original failed evidence.

The fresh synthetic site and private stage logs are retained. The default development site was not reconfigured; no operational provider, scheduler or distribution worker was enabled by this correction. This is bounded build/diagnostic qualification, not a production or external-provider release.

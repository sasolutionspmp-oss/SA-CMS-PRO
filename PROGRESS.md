# Progress Log

## 2025-09-19
- Ran `pwsh ./install/bootstrap.ps1 -SkipFrontend` to validate the Python-only bootstrap. Backend steps reused the existing `.venv` and pip installs succeeded; Node tooling was skipped automatically.
- bootstrap: `pwsh ./install/bootstrap.ps1 -SkipFrontend` (pass)
- tests: `.venv\Scripts\python.exe -m pytest` (47 passed)
- build: `pwsh -File build/codex-oneclick.ps1` (fail — CmdletBinding attribute parsed after swarm-lock preamble)
- selftest: `.venv\Scripts\python.exe -m ui.cli --selftest` (pass; offline copilot fallback)
- Verified nav column focus order now includes the status panel and theme toggle; confirmed labels read correctly with screen reader tooling.
- Re-ran NVDA screen reader pass; confirmed status panel announces state, version, and last refresh timestamp without altering focus order.
- Added nav status summary + manual refresh cooldown; NVDA reports status, version, last refresh, and cooldown toasts as expected.
- Confirmed the script now resolves the repository root correctly and finishes with "Bootstrap complete" messaging.
- Exercised backend reliability checks with `.\.venv\Scripts\python.exe -m pytest tests/unit/test_services.py tests/integration/test_health.py`; new integration coverage locks in `/health` response contracts.
- Logged fallback observability improvements (`metrics fallback used`) and captured the response template via `offline_payload()` helper for reuse in future tests.
- Authored `docs/backend_reliability.md` to centralize alert sources, regression commands, and restart playbooks.
- Follow-up: wire health regression into CI nightly job and add Application Insights alert thresholds for repeated offline fallbacks.
- Backlog: explore nav toasts/global alerts for repeated health check failures.
- QA backlog recorded in docs/QA_READOUT.md (table) and docs/QA_EXEC_SUMMARY.md; owners assigned for QA-01..QA-04.
- Instrumented ingest telemetry (`ingest_event`) with JSONL log path + audit linkage behind `ingest.telemetry.*` toggles; validated via `.\.venv\Scripts\python.exe -m pytest tests/integration/test_ingest_observability.py`.
- Updated docs (CODEBASE summary + backend reliability) with telemetry configuration, sample logs, and alerting guidance; noted ingest duration metrics for dashboard planning.
- Stretch follow-up: aggregate ingest duration telemetry (JSONL) into Fort 500 status/dashboard once trend volume is available.
- Authored AGENTS.md to consolidate repo structure, workflows, and conventions for new contributors.
- install/bootstrap.ps1 now records tool fingerprints in state/lane1.json; refreshed Node/pnpm detection and documented backend SOP expectations (lanes/lane2.md).

## 2025-09-20
- heavy-run: pass (pwsh ./heavy-run.ps1) after updating installer/SA-CMS-Pro.iss to correct icon path, output directory, architecture flag, and browser launch parameters.
- Inno Setup now emits output/SA-CMS-Pro-Setup.exe without warnings; PyInstaller artifacts refreshed in dist/.
- Authored scripts/heavy-overnight.ps1 to loop bootstrap/tests/build/packaging until the 6-hour budget expires; logs land under output/logs/overnight.
- Added platform bootstrap + auth wiring: new /platform/bootstrap endpoint (apps/api/routes/workflows.py) and mounted platform API inside server/main.py. Frontend now authenticates via LoginForm, persists tokens, and hydrates org/project state from real API responses before loading dashboards.\n- Implemented overnight autoresume harness (scripts/overnight-autoresume.ps1) that chains heavy-overnight.ps1 in timed chunks, logging to output/logs/overnight/autoresume.log as a fail-safe for long sessions.
- Exposed /platform/workflows/full orchestration route (apps/api/routes/workflows.py) that sequences intake→scope→estimate→compliance→bid→CRM→contract→PM using existing pipelines for Copilot-driven runs.

- 2025-09-20T05:56:57Z Initialized TASKS.md with backlog checklist and SUMMARY.md baseline per new execution plan.
- 2025-09-20T13:21:39Z Built the production App Shell wrapper: introduced AppShell layout (top bar, nav, right rail), refit intake module into the shell, and verified `pnpm run build` to confirm the React bundle compiles with the new structure.

- 2025-09-20T13:51:11Z Reworked Task 1 plan: reverting to Tailwind v3 toolchain, removing @tailwindcss/postcss, validating npm build/dev.
- 2025-09-20T14:04:26Z Delivered theme token pass: defined CSS variable palette + Tailwind bindings, refit AppShell/App to semantic colors, refreshed TailwindProbe, and re-ran `pnpm run build` to confirm dark-mode surfaces compile.
- 2025-09-20T14:10:47Z Added ingest vector regression: new RecordingVectorStore test ensures `process_zip` persists chunk rows and passes vector payload to the backend using `tests/data/sample_project.zip`.

- 2025-09-20T14:25:07Z Started Task 20 Documentation refresh per reverse order plan.
- 2025-09-20T14:25:59Z Built the frontend upload queue panel with simulated progress, semantic tokens, and per-file controls; pending backend wiring, the UI now supports multi-file selection, progress bars, and clearing completed items.

- 2025-09-20T14:28:50Z Updated README + API reference, registered OpenAPI tag metadata;  `python -m compileall apps/api/main.py` passes. 

- 2025-09-20T14:30:21Z Reinstated TASKS.md with updated timestamps (Task 20 marked complete).
- 2025-09-20T14:35:57Z Delivered functional estimating grid: added EstimatingPanel with scope mining, acceptance toggles, scenario markup editing, and totals hooked to platform API; build validated via `pnpm run build`.

- 2025-09-20T14:38:01Z Task 19 (Test harness) in progress: auditing ingest/parser modules and planning backend/frontend coverage.

- 2025-09-20T14:47:11Z Added ingest/classifier/metrics risk tests, Playwright smoke, and ran  `.venv \\\\Scripts\\\\python -m pytest tests/unit/ingest/test_parsing.py tests/unit/ingest/test_classifier.py tests/unit/ingest/test_risk_flagger.py tests/unit/metrics/test_metrics_normalizer.py ` + `pnpm run test` (chromium). 

- 2025-09-20T14:49:39Z Task 18 (Dev scripts) in progress: assessing existing PowerShell automation to design dev.ps1 and seed.ps1.

- 2025-09-20T14:52:36Z Authored scripts/dev.ps1 (multi-process launcher) and verified dry run outputs commands.

- 2025-09-20T14:52:36Z Added scripts/seed.ps1 to call apps.api.seed and optional intake launch; initial run flagged legacy SQLite schema (projects.stage missing) and advises removing stale DB before re-run.
- 2025-09-20T10:57:46Z Task 19 (Tests): Added xlsxwriter pytest shim, new estimator unit coverage, aligned extra metadata, and reran targeted suites (pytest tests/unit/apps/api/test_estimator_service.py, pytest tests/api/test_lane3_endpoints.py::test_crm_board_and_creation).
- 2025-09-20T11:05:22Z Task 18 (Repo scripts): Added skip switches and dependency checks to scripts/dev.ps1, expanded seed.ps1 with wait/login options, updated docs, and validated via dry-run (pwsh ./scripts/dev.ps1 -DryRun -SkipFrontend) + pwsh ./scripts/seed.ps1 -SkipSeed -SkipIngest.
- 2025-09-20T11:09:35Z Task 17 (Integration) in progress: reviewing frontend/api wiring to replace mock adapters with live endpoints.

- 2025-09-20T15:58:00Z Task 16 (Risk flagger): Persisted risk flag artifacts via IntakeService, added `.venv\Scripts\python.exe -m pytest tests/unit/test_intake_service.py::test_launch_generates_risk_flags`, typed `risk_flags` in `frontend/src/api.ts`, surfaced the Risk insights panel in `App.tsx`, and verified with `pnpm run build`.

- 2025-09-20T16:07:52Z Task 16 (Risk flagger): IntakeService now runs risk detection after parsing, writes risk_flags.json under data/uploads/{project}/{sha}/, exposes flags plus generated_at on IntakeRunStatus, and the dashboard renders real risk insights. Commands: .\.venv\Scripts\python.exe -m pytest tests/unit/test_intake_service.py; .\.venv\Scripts\python.exe -m pytest tests/api/test_intake_api.py; pnpm run test.

- 2025-09-20T16:43:31Z Task 15 (Extractive summarizer): Added TextRank/BM25 + MMR scoring, persisted summary_highlights.json and summary.md alongside ingest artifacts, and extended IntakeRunStatus plus tests. Commands: .\.venv\Scripts\python.exe -m pytest tests\unit\test_intake_service.py; .\.venv\Scripts\python.exe -m pytest tests\api\test_intake_api.py; pnpm run test.

- 2025-09-20T16:35:00Z Task 4 (Dashboard stub data): Replaced the dashboard placeholder with `DashboardOverview`, added preview KPI cards/milestones/feed, updated AppShell navigation, and verified via `pnpm run build`.
- 2025-09-20T16:41:45Z Task 5 (Upload panel with queue + progress): Added demo seeding, disabled gating, and queue summaries to `UploadPanel`, and verified via `.\.venv\Scripts\python.exe -m pytest tests/unit/ingest/test_summarizer.py tests/unit/test_intake_service.py::test_launch_generates_summary_highlights` plus `pnpm run build`.

- 2025-09-20T17:05:05Z Task 7 (Backend scaffolding): Verified FastAPI scaffolding by exercising server/main.create_app through the health endpoint test and confirming routers mount without errors. Commands: .\\.venv\\Scripts\\python.exe -m pytest tests/unit/test_health.py
- 2025-09-20T19:06:37Z Task 14 (Rule-based classifier): Extended heuristics coverage by adding representative corpus test ensuring >=90% tagging and verified with .\\.venv\\Scripts\\python.exe -m pytest tests/unit/ingest/test_classifier.py.

- 2025-09-20T17:22:45Z Task 8 (Auth placeholder): Added optional token fallback that seeds demo user/org/project in packages/core/dependencies.py, taught frontend App bootstrap to respect VITE_AUTH_OPTIONAL, and validated via .\\.venv\\Scripts\\python.exe -m pytest tests/api/test_lane3_endpoints.py::test_bootstrap_without_token.

- 2025-09-20T19:24:26Z Task 13 (Normalizer + sanitizer): Added ingest normalizer preserving line structure with optional redaction, chunked docs to 1.5-2k chars, wired metadata/raw text into graph + pipeline, and validated via .\.venv\Scripts\python.exe -m pytest tests/unit/ingest/test_normalizer.py tests/unit/test_ingest_pipeline.py tests/unit/test_intake_service.py.

- 2025-09-20T17:34:45Z Task 9 (Ingest endpoints): Enabled upload-name disk fallback in apps/api/services/intake.py so lane intake can reuse staged bundles, and added .\.venv\Scripts\python.exe -m pytest tests/api/test_lane3_endpoints.py::test_intake_launch_with_upload_name to cover the flow.
- 2025-09-20T19:35:35Z Task 12 (PDF/DOCX/XLSX parsers): Swapped PDF extraction to pypdf with guarded ocrmypdf fallback, hardened DOCX handling for tables, added coordinate-aware XLSX previews, and verified via .\.venv\Scripts\python.exe -m pytest tests/unit/ingest/test_parsing.py tests/unit/test_ingest_pipeline.py tests/unit/test_intake_service.py tests/unit/ingest/test_classifier.py.

SUMMARY SNAPSHOT - 2025-09-20T19:06Z (~330 words)

Backend scaffolding (Task 7) is now locked in: `server/main.py` boots the FastAPI service with intake/export routers, session guards, and the platform API mount, while `apps/api/main.py` auto-registers feature routers after seeding SQLAlchemy metadata so health checks exercise the real stack. The health unit test (`.venv\Scripts\python.exe -m pytest tests/unit/test_health.py`) passes, confirming the application boots cleanly.


The ingest lane now wraps risk flagging, extractive summarisation, and rule-based section tagging into a cohesive pipeline. Task 14 is closed out by hardening the heuristics and adding a sample corpus test that asserts at least 90% of representative chunks earn a section label. `classify_section` mixes keyword, regex, and filename hints, while `classify_text` keeps discipline metadata. The output is consumed during ingest graph construction and when IntakeService persists artifacts so every parsed item retains `section_tag`, discipline, addendum, and revision metadata for downstream experiences.

Risk intelligence from Task 16 remains untouched: `_generate_risk_flags` writes `risk_flags.json`, the API exposes flags and timestamps, and the React dashboard renders the Risk insights panel with line-referenced snippets. Task 15’s summariser still blends BM25 weighting, TextRank centrality, and maximal marginal relevance to assemble both a `summary_highlights.json` payload and a 200–400 word `summary.md`. IntakeService records the timestamps and exposes highlights via `IntakeRunStatus`, giving the UI a unified payload covering risk, summary, and section metadata.

The classifier test suite now includes `test_classifier_sample_corpus_covers_major_sections`, which walks eleven snippets spanning Instructions to Bidders, General Conditions, Specifications, Plans, Schedules, Addenda, Safety, Bonding, Pricing Forms, Scope of Work, and an intentionally ambiguous meeting note. The test verifies that at least 90% of the sample set produces non-null section tags and that null-classified content is limited to the ambiguous memo. This guards the acceptance criterion and catches regressions in future tuning passes.

Regression commands executed after the latest changes: `.venv\Scripts\python.exe -m pytest tests\unit\ingest\test_classifier.py`. All checks pass without warnings.


The risk and summary payloads continue to surface in the dashboard cards without regressions observed during manual smoke checks.



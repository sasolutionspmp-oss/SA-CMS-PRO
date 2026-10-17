# ENG-01 — RFI, submittal and internal transmittal workspace

This implements the original [ENG-01 package](EXECUTION_BACKLOG.md#eng-01--rfi-and-submittal-revisions-checkingdispositions-and-controlled-distribution). Its Project document and approval prerequisites remain the existing DOC-02/GOV-03 contracts. The architecture stays SAP UI5 React/Horizon, ERPNext/Frappe and the custom `cipher_aec` application. Odoo and the earlier Cipher implementation are excluded.

## Working source

The unified project sidebar now opens **Engineering**. The SAP UI5 register and ObjectPage journeys support:

- Source-linked RFIs with exact drawing page/location references or canonical text citations, responsible project people and due dates. Vector PDFs work without extracted text.
- Immutable successor questions and working technical responses. A prior official answer remains attached to its exact original revision while a new proposal awaits independent authorization.
- Submittal packages with exact stored document revisions, specification section, contractor, equipment tag, required review date and a designated canonical reviewer. Submission, resubmission and review dispositions remain separate immutable facts.
- Independent human authorization of the exact proposed response or disposition through the shared Project approval engine. Submitters and authors cannot grant their own consequential effects through aliases.
- Separate internal transmittal preparation, exact recipient/package review and durable internal distribution receipts. Technical authorization does not itself distribute a package.
- Current-source readback, revision history, RFI closure, scoped people selection and mounted-view recovery after an interrupted or mismatched reply. The original UUID and reviewed basis survive recovery; uncertain operations lock navigation and source/form editing.

These are source implementations against supported Frappe APIs and ten namespaced DocTypes. New Project abilities are `engineering.read`, `engineering.write` and `engineering.distribute`; existing users receive no automatic new grants. Every consequential action uses current Project authority, original sources, exact immutable digests, independent human decisions and durable command/history records.

Technical responses and dispositions carry no commercial, contract, budget, schedule, quality-acceptance, professional-certification or external-transmission effect. The existing local Ricky connection and QuickBooks adapter remain separately unconnected; this package adds no provider connection.

## Evidence and remaining gate

The [combined source manifest](evidence/r3/engineering-eng01-source/source-manifest.json) binds 789 source files and 921 build files. [Backend qualification](evidence/r3/engineering-eng01-source/backend-host-qualification.json) records 84 host checks, including 32 engineering checks and 52 compatibility checks, plus all 14 generated contracts and OpenAPI validation. [Combined verification](evidence/r3/engineering-eng01-source/verification.json) records the final typecheck/build and focused browser results. These test categories remain distinct.

The browser tests run the actual compiled SAP UI5 application against explicitly intercepted in-memory contract fixtures. They prove UI behavior, exact request/recovery boundaries and desktop/tablet/phone layouts. They are **not native backend persistence or live operational screenshots**. No fixture image is presented as an operational record. Initial failures and their corrections remain indexed in [retained failures](evidence/r3/engineering-eng01-source/retained-failures.json).

The actual Frappe `TestEngineeringNative` integration class is written for the existing fresh-site CI gate. It exercises an actual stored no-text PDF, independent technical decisions, internal receipts/replay, immutable successors, designated submittal review and native write/permission denial. At this source-publication checkpoint it has **not run**. No engineering source or schema has been installed into MAIN or the preserved isolated site. The local root filesystem has approximately 19 MB free; native installation must have adequate backed-up capacity before any schema changes.

ENG-01 and completion journey C18 therefore remain open for native persistence qualification and an actual native UI walkthrough. The existing award handoff rejection remains unchanged. Optional Company drawing-impact refinements remain deferred. Once this package is locally verified, the original next dependencies are ENG-02 and DOC-03; the original plan is not replaced by capture/test rounds.

## Native CI follow-up

The first [engineering CI attempt](evidence/r3/engineering-eng01-source/native-ci-first-failure.json) successfully installed the app/schema, then failed in Frappe integration tests. Its accessible job log omitted the exception; the artifact download was rejected by the container network proxy with HTTP403. The original failure remains failed. A separate [reporter correction](evidence/r3/engineering-eng01-source/native-diagnostics-qualification.json) now exposes only bounded test identity, exception type and source file/line/function frames on native failures, preserving private raw logs. All 18 reporter checks passed. The next fresh run must establish the actual cause and native result; installation success alone does not complete ENG-01.

The [diagnostic run](evidence/r3/engineering-eng01-source/native-ci-diagnostic-failure.json) identifies `frappe.exceptions.TimestampMismatchError` at the second intentionally denied native save in `test_engineering_native.py:72`. Frappe had updated the reused in-memory document timestamp during the first rejected save. The [test correction](evidence/r3/engineering-eng01-source/native-test-correction.json) reloads that same original row before the next guard assertion; controller, permission and business-service source is unchanged. Native completion remains pending the corrected fresh run.

The [corrected hosted result](evidence/r3/engineering-eng01-source/native-ci-corrected-backend-pass.json) for 9029585b passed fresh-site native Frappe integration (including `TestEngineeringNative`), backend unit checks and all eight workflow procedures. Overall CI remains failed: the browser stage reached its 920-second process ceiling without a final JSON report. Its internal browser cause is not exposed by the accessible log. This qualifies the native backend workflow on that exact source, while an actual native UI walkthrough and successful full browser CI remain open. A separate static-fixture CI continuation addresses browser-server memory use; original failed runs remain unchanged.

# ENG-02 — Engineering work packages, calculations and deliverables

This implements [the original ENG-02 package](EXECUTION_BACKLOG.md#eng-02--engineering-work-packages-design-basis-calculations-checking-and-deliverables). It extends the original Engineering workspace on SAP UI5 React/Horizon and ERPNext/Frappe16. Its dependency is ENG-01's implemented and locally verified schema/service/API contract, under the existing backlog dependency rule. ENG-01's remaining native/UI qualification stays separate.

## Working behavior

A Project work package records discipline, engineering scope, a responsible canonical engineer, a distinct required checker, due date and authorized Task/WBS links. Assignment revisions remain immutable. Package-only people and unit selectors do not require unrelated RFI or estimating duties.

A design-basis revision retains exact criteria, assumptions, design-code editions/clauses, stored source documents/pages/locations and authored decimal quantities. Every quantity retains the qualified canonical UOM revision, precision and Company context. A drawing does not need extracted text. Quantities are authored facts; this package performs no inferred geometry or unit conversion.

Calculation revisions copy the explicitly selected exact basis inputs and retain authored outputs, equation/algorithm reference, declared tool/model versions and stored output documents. The declared method is a human-authored result record. Cipher does not execute a formula, tool, model or qualified solver here; isolated Ricky/engineering jobs are the separate ENG-03 package.

Deliverable revisions retain exact calculation IDs/digests, design basis, checking notes, drawing/specification/document references and revision reason. They remain unauthorized for issue. Changing an assignment or basis preserves historical revisions and checks while requiring eligible current sources for new calculations, deliverables and checking requests.

Each basis, calculation and deliverable check uses the shared approval engine, original immutable digest/source/unit manifest and designated independent canonical human. Grant and explicit check recording remain separate actions. A return for revision remains its original decision; blank comments are valid. A check fact carries no issue, distribution, professional seal, financial, contract, schedule or quality-acceptance effect. The issued-set/library workflow remains DOC-03.

The unified SAP UI5 register, ObjectPages, authoring dialogs, immutable-history views and checking review retain exact source facts. Interrupted or mismatched replies preserve the original UUID, actor and reviewed basis inside the mounted workspace; global navigation and editing remain locked until the matching receipt is confirmed. Current source or authority denial removes protected authoring content. New duties receive no automatic grants.

## Qualification boundary

Backend host qualification records 124 distinct checks: 22 new ENG-02, 84 engineering/approval/document compatibility and 18 diagnostic-reporter checks. All 15 generated contracts, OpenAPI and isolated typechecking passed. The [combined evidence](evidence/r3/engineering-eng02-source/README.md) binds 831 source files and 925 build files. [Verification](evidence/r3/engineering-eng02-source/verification.json) records 38 distinct focused checks (27 adapter +11 browser) and 59 shared compatibility checks. Both totals use explicitly recorded passing continuations; neither is presented as a fresh single all-pass run. Final typechecking and production build passed. [Original failures](evidence/r3/engineering-eng02-source/retained-failures.json) remain preserved.

Browser contract checks run the actual built SAP UI5 application against explicitly identified intercepted APIs. They are not native persistence evidence or operational screenshots. No generated or fixture image is presented as a live system record.

The actual Frappe integration workflow `TestEngineeringPackagesNative` is declared for the fresh-site CI gate. It covers a real stored no-text PDF and qualified UOM, package-only selectors, all three independent check facts, original receipt replay, successor preservation and native write denial. Its execution result must be recorded separately; the source implementation alone does not complete ENG-02 or C19.

MAIN and the preserved isolated site remain unchanged. This package does not connect the live Ricky model or QuickBooks, issue documents or authorize external delivery. The existing award-action rejection remains unchanged. Optional closed Company refinements remain deferred; the next original dependency-ready work is ENG-03/DOC-03.

## Native follow-up

The [first fresh-site run](evidence/r3/engineering-eng02-source/native-ci-first-failure.json) installed the new app/schema, then failed at the checker/unit selector assertions in `test_engineering_packages_native.py:45`. The isolated fixture had not provisioned native UOM-read permission, which the shared unit adapter requires. The [fixture continuation](evidence/r3/engineering-eng02-source/native-fixture-correction.json) adds an explicit temporary native reader role, asserts actual read permission and follows bounded unit pages rather than assuming first-page placement. No product permission or service guard changes. Its native result remains pending.

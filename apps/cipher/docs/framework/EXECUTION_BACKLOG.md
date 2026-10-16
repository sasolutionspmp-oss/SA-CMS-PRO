# Dependency-ordered implementation backlog

**Implementation authorized:** The owner instructed “Execute this plan as written and do not stray” on October 15, 2026. Implementation is now active under this framework. Earlier pending-approval/planning-only markers describe the completed draft stage and no longer block coding. Astra ultra owns orchestration/reviews/escalations; all implementation subagents use GPT-6.1 Sol.

Execute this fresh Cipher product design on SAP UI5 and ERPNext/Frappe. Prior Cipher and Odoo work are excluded as design inputs. The existing local Ricky model is integrated through the newly defined contracts. Required scope/evidence below is the approved baseline; current progress and local/external qualification are tracked in `backlog.json` and `IMPLEMENTATION_STATUS.md`.

A dependency is satisfied when its required local schema/service/API contract is implemented and locally verified. Track local contract readiness separately from actual external-provider/model qualification. A fixture never proves a live connection, but missing external access must not block independent implementation of downstream services. Final connected release claims still require actual evidence.

| ID | Release | Dependencies | Deliverable |
|---|---|---|---|
| PLT-01 | R0 | None | Resolve supported storage capacity and lock compatible ERPNext/Frappe/UI5/runtime versions |
| PLT-02 | R0 | PLT-01 | Create installable cipher_aec app, deployment profiles and migrations bootstrap |
| PLT-03 | R0 | PLT-02 | Persistent volumes, artifact development adapter, backup and restore quarantine |
| GOV-01 | R0 | PLT-02 | Canonical person/identity bindings and company/project duties |
| GOV-02 | R0 | GOV-01 | Command receipt registry, version/manifest checks and exact-value primitives |
| GOV-03 | R0 | GOV-02 | Approval packet/decision service and generic-route document hooks |
| MIG-01 | R0 | PLT-02 | Design independent canonical import/export contracts and fresh synthetic master/dimension fixtures |
| API-01 | R0 | GOV-01, GOV-02 | Same-origin session, typed envelopes, errors, paging and OpenAPI generation |
| PRJ-01 | R0 | API-01 | ERPNext Project/Task read/write services and project profile |
| DOC-01 | R0 | GOV-01, PLT-03 | Canonical document/revision, upload quarantine and authorized byte download |
| AI-01 | R0 | API-01 | Recover existing Ricky contract and implement replaceable adapter with honest capability status |
| UX-01 | R0 | API-01 | Official UI5 shell, company/project context, work inbox and truthful states |
| QA-01 | R0 | PLT-02, API-01 | CI/test runners, real Frappe database fixtures and release evidence manifest |
| INT-01 | R0 | GOV-02, PLT-03 | Generic durable outbox/inbox, attempts, leases and recovery scheduler |
| DOC-02 | R0 | DOC-01, INT-01 | Text/PDF extraction, source/page citations and exact search |
| AI-02 | R0 | GOV-02, API-01, INT-01 | Persist Ricky runs/steps/delegations/tool receipts with budgets and cancellation |
| AI-03 | R0 | DOC-02, AI-01, AI-02, PRJ-01 | Permission-aware cited answer and task-proposal/commit tool |
| UX-02 | R0 | UX-01, PRJ-01, DOC-02, AI-03 | Connect project/document/Ricky/proposed task/history journey |
| COM-01 | R1 | PRJ-01, GOV-03, MIG-01 | Extend Opportunity/Quotation with pursuit, proposal sections and immutable revisions |
| EST-01 | R1 | DOC-02, GOV-02 | Units/conversions, rate sources, assembly revisions and exact estimate calculation |
| EST-02 | R1 | EST-01, DOC-02 | Takeoff measurement, calibration, geometric/manual lineage and revision comparison |
| EST-03 | R1 | EST-02, GOV-03 | Estimate acceptance and frozen baseline |
| COM-02 | R1 | COM-01, EST-03, INT-01 | Proposal review, output snapshots, issue and controlled distribution contract |
| FIN-01 | R1 | PRJ-01, GOV-03 | Construction contract/SOV base schemas, terms and retainage policies before award orchestration |
| PRJ-02 | R1 | COM-02, EST-03, FIN-01 | Atomic award to project, WBS, budget, contract and Sales Order links |
| BUY-01 | R1 | PRJ-02 | Requests/RFQs/quote comparisons and project procurement packages |
| BUY-02 | R1 | BUY-01, FIN-01 | Purchase orders, construction commitments and controlled release |
| BUY-03 | R1 | BUY-02, DOC-01 | Partial receipts, inspection evidence and stored-material inventory links |
| AI-04 | R1 | COM-01, EST-03, AI-03 | Ricky scope/estimate assistance and deterministic calculation tools |
| UX-03 | R1 | COM-02, EST-03, BUY-03, UX-02 | Commercial/estimate/award/procurement pages including dense editing |
| FIN-02 | R2 | FIN-01, BUY-03 | Invoice intake, duplicate detection, matching and service/no-PO exceptions |
| FIN-03 | R2 | FIN-02 | Installed-work certificates, supplier applications and stored-material consumption |
| FIN-04 | R2 | FIN-03, GOV-03, INT-01 | Independent approval and Purchase Invoice posting with exact GL comparison |
| FIN-05 | R2 | FIN-04 | Retainage withholding/release and linked credits/corrections |
| INT-02 | R2 | INT-01, MIG-01, FIN-04 | QuickBooks capabilities, mapping, OAuth storage and sandbox handoff/readback |
| INT-03 | R2 | INT-02, FIN-05 | BILL/payment route mapping, status import and reconciliation |
| INT-04 | R2 | INT-02 | Inventory/asset/labor/adjustment effect classification and official-origin import rules |
| FIN-06 | R2 | FIN-01, FIN-05 | Owner applications, Sales Invoice posting and retainage receivable |
| FIN-07 | R2 | FIN-06, INT-02 | Receipts, allocation, returns, deposits, credits and collections |
| FIN-08 | R2 | FIN-05, FIN-07, INT-04 | Operational/official reconciliation, WIP and period close |
| UX-04 | R2 | FIN-08, UX-03 | Unified AP/AR/retained balance/collections/reconciliation pages |
| AI-05 | R2 | FIN-08, AI-04 | Ricky coding/matching/explanations and granted-action execution |
| PRJ-03 | R3 | PRJ-02, FIN-01 | Change events, contract changes, budget transfers and forecast versions |
| PRJ-04 | R3 | PRJ-03 | Schedule baseline, dependencies, calendars, progress and lookahead |
| FLD-01 | R3 | PRJ-01, DOC-01 | Daily reports, photos, installed quantities and T&M tickets |
| FLD-02 | R3 | FLD-01, GOV-02 | Offline capture envelopes and explicit conflict resolution |
| OPS-01 | R3 | FLD-01, INT-04 | Compatible Frappe HR installation, crews/classifications/time approval, payroll handoff and job-cost allocation |
| OPS-02 | R3 | OPS-01, INT-04 | Asset/rental equipment allocations, meters, maintenance and costing |
| ENG-01 | R3 | DOC-02, GOV-03 | RFI and submittal revisions, checking/dispositions and controlled distribution |
| ENG-02 | R3 | ENG-01 | Engineering work packages, design basis, calculations, checking and deliverables |
| ENG-03 | R3 | ENG-02, AI-02 | Existing Ricky CAD/takeoff/calculation tool adapters and isolated jobs |
| DOC-03 | R3 | DOC-02, ENG-01 | Issued sets/transmittals, specifications/contracts library and adopted revisions |
| DOC-04 | R3 | DOC-03, AI-03 | Qdrant semantic index and actual embedding adapter with ACL rechecks |
| FLD-03 | R3 | FLD-01, ENG-01 | QA/QC inspections, deficiencies, safety observations/incidents and permits |
| ENG-04 | R3 | ENG-02, DOC-03, FLD-03 | Commissioning, punch, O&M/warranties and asset handover/closeout |
| RPT-01 | R3 | FIN-08, PRJ-03, OPS-02 | Project/portfolio dashboards, job cost, forecasts and snapshot exports |
| UX-05 | R3 | PRJ-04, FLD-02, ENG-04, RPT-01, UX-04 | Connect remaining field/engineering/library/schedule/reporting workflows |
| AI-06 | R3 | ENG-03, DOC-04, AI-05 | Cross-domain Ricky AEC workflows and controlled automation inbox |
| QA-02 | R3 | UX-05, AI-06 | Integrated permission/recovery/accessibility/performance qualification |
| MIG-02 | R4 | MIG-01, FIN-08, DOC-03 | Optional source-specific business-data onboarding into the finalized target model |
| OPS-03 | R4 | QA-02 | Operational identity/secrets, monitored deployment and actual restore rehearsal |
| INT-05 | R4 | INT-03, MIG-02, OPS-03 | Authorized real accounting integration and controlled writer cutover |
| REL-01 | R4 | INT-05, QA-02 | Internal pilot rollout, support runbooks, training and defect closure |
| ENT-01 | R5 | REL-01 | Multi-company/intercompany and separate-site enterprise qualification |
| ENT-02 | R5 | ENT-01 | Enterprise SSO/SCIM/delegation, legal hold/retention and audit export |
| ENT-03 | R5 | ENT-02 | Scale, disaster recovery, security review and commercial packaging |

## Work package contracts

### PLT-01 — Resolve supported storage capacity and lock compatible ERPNext/Frappe/UI5/runtime versions

- Release: R0. Status: verified.
- Required locally verified contracts: Framework approval only.
- Implement: Resolve supported storage capacity and lock compatible ERPNext/Frappe/UI5/runtime versions.
- Required acceptance evidence: Recorded capacity check and exact resolved versions/digests; successful isolated platform startup.
- Record schema/API/service and unified UI or worker changes, relevant positive/denied/failure/recovery checks, source revision and artifact paths. Keep local contract verification separate from external qualification; never count a fake result as a connected provider/model.

### PLT-02 — Create installable cipher_aec app, deployment profiles and migrations bootstrap

- Release: R0. Status: verified.
- Required locally verified contracts: PLT-01.
- Implement: Create installable cipher_aec app, deployment profiles and migrations bootstrap.
- Required acceptance evidence: Fresh site installs app and repeat migrate is safe; workers/scheduler readiness reported.
- Record schema/API/service and unified UI or worker changes, relevant positive/denied/failure/recovery checks, source revision and artifact paths. Keep local contract verification separate from external qualification; never count a fake result as a connected provider/model.

### PLT-03 — Persistent volumes, artifact development adapter, backup and restore quarantine

- Release: R0. Status: verified.
- Required locally verified contracts: PLT-02.
- Implement: Persistent volumes, artifact development adapter, backup and restore quarantine.
- Required acceptance evidence: Restart retains records; isolated restore does not send external effects.
- Record schema/API/service and unified UI or worker changes, relevant positive/denied/failure/recovery checks, source revision and artifact paths. Keep local contract verification separate from external qualification; never count a fake result as a connected provider/model.

### GOV-01 — Canonical person/identity bindings and company/project duties

- Release: R0. Status: verified.
- Required locally verified contracts: PLT-02.
- Implement: Canonical person/identity bindings and company/project duties.
- Required acceptance evidence: Alias identities cannot self-approve; cross-company and revoked membership access denied.
- Record schema/API/service and unified UI or worker changes, relevant positive/denied/failure/recovery checks, source revision and artifact paths. Keep local contract verification separate from external qualification; never count a fake result as a connected provider/model.

### GOV-02 — Command receipt registry, version/manifest checks and exact-value primitives

- Release: R0. Status: verified.
- Required locally verified contracts: GOV-01.
- Implement: Command receipt registry, version/manifest checks and exact-value primitives.
- Required acceptance evidence: Duplicate command has one effect; reused key with changed company/payload conflicts; decimals round correctly.
- Record schema/API/service and unified UI or worker changes, relevant positive/denied/failure/recovery checks, source revision and artifact paths. Keep local contract verification separate from external qualification; never count a fake result as a connected provider/model.

### GOV-03 — Approval packet/decision service and generic-route document hooks

- Release: R0. Status: active.
- Required locally verified contracts: GOV-02.
- Implement: Approval packet/decision service and generic-route document hooks.
- Required acceptance evidence: Direct submit/cancel/import attempts cannot bypass required authority.
- Record schema/API/service and unified UI or worker changes, relevant positive/denied/failure/recovery checks, source revision and artifact paths. Keep local contract verification separate from external qualification; never count a fake result as a connected provider/model.

### MIG-01 — Design independent canonical import/export contracts and fresh synthetic master/dimension fixtures

- Release: R0. Status: verified.
- Required locally verified contracts: PLT-02.
- Implement: Design independent canonical import/export contracts and fresh synthetic master/dimension fixtures.
- Required acceptance evidence: Target schemas and fixtures stand alone; no Odoo/prior-code access or compatibility needed.
- Record schema/API/service and unified UI or worker changes, relevant positive/denied/failure/recovery checks, source revision and artifact paths. Keep local contract verification separate from external qualification; never count a fake result as a connected provider/model.

### API-01 — Same-origin session, typed envelopes, errors, paging and OpenAPI generation

- Release: R0. Status: verified.
- Required locally verified contracts: GOV-01, GOV-02.
- Implement: Same-origin session, typed envelopes, errors, paging and OpenAPI generation.
- Required acceptance evidence: Contract checks validate auth/CSRF, permissions, cursor scope, stale errors and generated client.
- Record schema/API/service and unified UI or worker changes, relevant positive/denied/failure/recovery checks, source revision and artifact paths. Keep local contract verification separate from external qualification; never count a fake result as a connected provider/model.

### PRJ-01 — ERPNext Project/Task read/write services and project profile

- Release: R0. Status: verified.
- Required locally verified contracts: API-01.
- Implement: ERPNext Project/Task read/write services and project profile.
- Required acceptance evidence: Authorized project/task persists across restart; inaccessible records and counts stay private.
- Record schema/API/service and unified UI or worker changes, relevant positive/denied/failure/recovery checks, source revision and artifact paths. Keep local contract verification separate from external qualification; never count a fake result as a connected provider/model.

### DOC-01 — Canonical document/revision, upload quarantine and authorized byte download

- Release: R0. Status: active.
- Required locally verified contracts: GOV-01, PLT-03.
- Implement: Canonical document/revision, upload quarantine and authorized byte download.
- Required acceptance evidence: Uploaded bytes verified by hash; unauthorized and superseded URL access handled correctly.
- Record schema/API/service and unified UI or worker changes, relevant positive/denied/failure/recovery checks, source revision and artifact paths. Keep local contract verification separate from external qualification; never count a fake result as a connected provider/model.

### AI-01 — Recover existing Ricky contract and implement replaceable adapter with honest capability status

- Release: R0. Status: active.
- Required locally verified contracts: API-01.
- Implement: Recover existing Ricky contract and implement replaceable adapter with honest capability status.
- Required acceptance evidence: Fixture and connected-model modes distinct; no presumed protocol, embeddings or tool support.
- Record schema/API/service and unified UI or worker changes, relevant positive/denied/failure/recovery checks, source revision and artifact paths. Keep local contract verification separate from external qualification; never count a fake result as a connected provider/model.

### UX-01 — Official UI5 shell, company/project context, work inbox and truthful states

- Release: R0. Status: verified.
- Required locally verified contracts: API-01.
- Implement: Official UI5 shell, company/project context, work inbox and truthful states.
- Required acceptance evidence: Real Horizon UI5 navigation at three widths; keyboard focus and session expiration handled.
- Record schema/API/service and unified UI or worker changes, relevant positive/denied/failure/recovery checks, source revision and artifact paths. Keep local contract verification separate from external qualification; never count a fake result as a connected provider/model.

### QA-01 — CI/test runners, real Frappe database fixtures and release evidence manifest

- Release: R0. Status: verified.
- Required locally verified contracts: PLT-02, API-01.
- Implement: CI/test runners, real Frappe database fixtures and release evidence manifest.
- Required acceptance evidence: Reproducible fresh build/type checks/integration checks; evidence binds source version.
- Record schema/API/service and unified UI or worker changes, relevant positive/denied/failure/recovery checks, source revision and artifact paths. Keep local contract verification separate from external qualification; never count a fake result as a connected provider/model.

### INT-01 — Generic durable outbox/inbox, attempts, leases and recovery scheduler

- Release: R0. Status: verified.
- Required locally verified contracts: GOV-02, PLT-03.
- Implement: Generic durable outbox/inbox, attempts, leases and recovery scheduler.
- Required acceptance evidence: Crash after commit before queueing still delivers work; duplicate callback has one effect.
- Record schema/API/service and unified UI or worker changes, relevant positive/denied/failure/recovery checks, source revision and artifact paths. Keep local contract verification separate from external qualification; never count a fake result as a connected provider/model.

### DOC-02 — Text/PDF extraction, source/page citations and exact search

- Release: R0. Status: active.
- Required locally verified contracts: DOC-01, INT-01.
- Implement: Text/PDF extraction, source/page citations and exact search.
- Required acceptance evidence: Known source fact returns exact accessible revision/page; failed extraction remains visible.
- Record schema/API/service and unified UI or worker changes, relevant positive/denied/failure/recovery checks, source revision and artifact paths. Keep local contract verification separate from external qualification; never count a fake result as a connected provider/model.

### AI-02 — Persist Ricky runs/steps/delegations/tool receipts with budgets and cancellation

- Release: R0. Status: active.
- Required locally verified contracts: GOV-02, API-01, INT-01.
- Implement: Persist Ricky runs/steps/delegations/tool receipts with budgets and cancellation.
- Required acceptance evidence: Worker restart resumes original operation; late worker fenced; cancellation preserves completed effects.
- Record schema/API/service and unified UI or worker changes, relevant positive/denied/failure/recovery checks, source revision and artifact paths. Keep local contract verification separate from external qualification; never count a fake result as a connected provider/model.

### AI-03 — Permission-aware cited answer and task-proposal/commit tool

- Release: R0. Status: active.
- Required locally verified contracts: DOC-02, AI-01, AI-02, PRJ-01.
- Implement: Permission-aware cited answer and task-proposal/commit tool.
- Required acceptance evidence: Revoked access and injected source instructions cannot create unauthorized task; repeat commit creates one task.
- Record schema/API/service and unified UI or worker changes, relevant positive/denied/failure/recovery checks, source revision and artifact paths. Keep local contract verification separate from external qualification; never count a fake result as a connected provider/model.

### UX-02 — Connect project/document/Ricky/proposed task/history journey

- Release: R0. Status: active.
- Required locally verified contracts: UX-01, PRJ-01, DOC-02, AI-03.
- Implement: Connect project/document/Ricky/proposed task/history journey.
- Required acceptance evidence: Actual browser captures plus persistent restart, one task after retry and second-user denial.
- Record schema/API/service and unified UI or worker changes, relevant positive/denied/failure/recovery checks, source revision and artifact paths. Keep local contract verification separate from external qualification; never count a fake result as a connected provider/model.

### COM-01 — Extend Opportunity/Quotation with pursuit, proposal sections and immutable revisions

- Release: R1. Status: verified.
- Required locally verified contracts: PRJ-01, GOV-03, MIG-01.
- Implement: Extend Opportunity/Quotation with pursuit, proposal sections and immutable revisions.
- Required acceptance evidence: Scope/alternates/terms survive revision comparison without creating a duplicate customer master.
- Record schema/API/service and unified UI or worker changes, relevant positive/denied/failure/recovery checks, source revision and artifact paths. Keep local contract verification separate from external qualification; never count a fake result as a connected provider/model.

### EST-01 — Units/conversions, rate sources, assembly revisions and exact estimate calculation

- Release: R1. Status: active.
- Required locally verified contracts: DOC-02, GOV-02.
- Implement: Units/conversions, rate sources, assembly revisions and exact estimate calculation.
- Required acceptance evidence: Known quantity/rate/waste examples and invalid-dimension cases produce deterministic results.
- Record schema/API/service and unified UI or worker changes, relevant positive/denied/failure/recovery checks, source revision and artifact paths. Keep local contract verification separate from external qualification; never count a fake result as a connected provider/model.

### EST-02 — Takeoff measurement, calibration, geometric/manual lineage and revision comparison

- Release: R1. Status: active.
- Required locally verified contracts: EST-01, DOC-02.
- Implement: Takeoff measurement, calibration, geometric/manual lineage and revision comparison.
- Required acceptance evidence: Calibrated fixture reproduces quantities; manual entry is labeled; new drawing invalidates affected dependencies.
- Record schema/API/service and unified UI or worker changes, relevant positive/denied/failure/recovery checks, source revision and artifact paths. Keep local contract verification separate from external qualification; never count a fake result as a connected provider/model.

### EST-03 — Estimate acceptance and frozen baseline

Current qualification: raw/manual/geometry baseline lineage and original-authority revocation/restoration have connected evidence. Generated-document inputs remain disabled while command and full-history performance are qualified; the latest source-bound consume is 4.296 seconds against the 3-second target after reviewed citation grouping. The current frozen combined gate passed with 315 backend cases, seven acceptance procedures, four process checks and 100 browser cases.

- Release: R1. Status: active.
- Required locally verified contracts: EST-02, GOV-03.
- Implement: Estimate acceptance and frozen baseline.
- Required acceptance evidence: Changed material source rejects stale acceptance; successor estimate does not reprice baseline.
- Record schema/API/service and unified UI or worker changes, relevant positive/denied/failure/recovery checks, source revision and artifact paths. Keep local contract verification separate from external qualification; never count a fake result as a connected provider/model.

### COM-02 — Proposal review, output snapshots, issue and controlled distribution contract

Current qualification: preparation, independent Issue, separately approved fixture delivery, automatic recovery and actual responsive UI passed their named evidence. The current frozen combined gate passed with 315 backend cases, seven acceptance procedures, four process checks and 100 browser cases. External customer/provider delivery is unconfigured.

- Release: R1. Status: active.
- Required locally verified contracts: COM-01, EST-03, INT-01.
- Implement: Proposal review, output snapshots, issue and controlled distribution contract.
- Required acceptance evidence: Issued output matches approved revision; send is separate and fixture delivery labeled.
- Record schema/API/service and unified UI or worker changes, relevant positive/denied/failure/recovery checks, source revision and artifact paths. Keep local contract verification separate from external qualification; never count a fake result as a connected provider/model.

### FIN-01 — Construction contract/SOV base schemas, terms and retainage policies before award orchestration

- Release: R1. Status: verified.
- Required locally verified contracts: PRJ-01, GOV-03.
- Implement: Construction contract/SOV base schemas, terms and retainage policies before award orchestration.
- Required acceptance evidence: SOV caps cannot fall below certified amounts without correction; no manufacturing-subcontract shortcut.
- Record schema/API/service and unified UI or worker changes, relevant positive/denied/failure/recovery checks, source revision and artifact paths. Keep local contract verification separate from external qualification; never count a fake result as a connected provider/model.

### PRJ-02 — Atomic award to project, WBS, budget, contract and Sales Order links

Admission boundary: follow the current source checkpoint with qualified raw/manual/geometry accepted-baseline dependencies plus the native/WBS/cost/team/FIN prerequisites in the reviewed contracts. An issued PDF generated as output retains its producer provenance and is distinct from an estimate consuming a generated document as input. Award activation requires its own atomicity, rollback, concurrency, revocation and recovery evidence.

Canonical cost-control foundation: [ten isolated native groups passed](evidence/r1/project-controls-native-qualification.json), with independently verified rights restoration and disclosed native Account tree-position changes from test-Company creation. This qualifies master storage/resolution and access boundaries. [Normal master administration](evidence/r1/prj02-ui-connected/cost-setup-v2/README.md) now has four actual saved operations, independent readbacks and responsive captures. Composed WBS/budget adoption and atomic award remain active. [The composed acceptance plan](PRJ02_COMPOSED_ACCEPTANCE_PLAN.md) records the required independent cases; planned cases are not completed evidence.

Connected prerequisites now include an independently accepted 15.00 mixed cost baseline, an actual 30.85 issued proposal PDF and the original draft plan. The disabled award request returned `403` with unchanged compared tables. The [isolated enabled policy stage](evidence/r1/prj02-enabled-policy-native.json) preserves prior policy/business state and releases only the reviewed acceptance sequence. Positive award execution remains pending; the main action stays disabled. [One final plan successor](evidence/r1/prj02-ui-connected/saved-plan-v2/README.md) was saved through the UI and independently read back, changing only its Project name. Browser contract fixtures and actual connected UI observations are recorded separately.

- Release: R1. Status: active.
- Required locally verified contracts: COM-02, EST-03, FIN-01.
- Implement: Atomic award to project, WBS, budget, contract and Sales Order links.
- Required acceptance evidence: Repeated award yields one project/baseline; line lineage and totals reconcile.
- Record schema/API/service and unified UI or worker changes, relevant positive/denied/failure/recovery checks, source revision and artifact paths. Keep local contract verification separate from external qualification; never count a fake result as a connected provider/model.

### BUY-01 — Requests/RFQs/quote comparisons and project procurement packages

Unpublished working preparation, excluded from the cost/planning checkpoint: the [unregistered draft slice](evidence/r1/buy01-unregistered-draft-tests-v2.json) passed 27 pure checks and source review. It preserves supplier originals and exact rate/quantity facts with current-source authorization. Persistence, public routes and the awarded-Project adapter await the declared dependency.

- Release: R1. Status: planned.
- Required locally verified contracts: PRJ-02.
- Implement: Requests/RFQs/quote comparisons and project procurement packages.
- Required acceptance evidence: Supplier quote normalization preserves original; unauthorized award blocked.
- Record schema/API/service and unified UI or worker changes, relevant positive/denied/failure/recovery checks, source revision and artifact paths. Keep local contract verification separate from external qualification; never count a fake result as a connected provider/model.

### BUY-02 — Purchase orders, construction commitments and controlled release

- Release: R1. Status: planned.
- Required locally verified contracts: BUY-01, FIN-01.
- Implement: Purchase orders, construction commitments and controlled release.
- Required acceptance evidence: Commitment links standard PO and approved contract without creating a payable.
- Record schema/API/service and unified UI or worker changes, relevant positive/denied/failure/recovery checks, source revision and artifact paths. Keep local contract verification separate from external qualification; never count a fake result as a connected provider/model.

### BUY-03 — Partial receipts, inspection evidence and stored-material inventory links

- Release: R1. Status: planned.
- Required locally verified contracts: BUY-02, DOC-01.
- Implement: Partial receipts, inspection evidence and stored-material inventory links.
- Required acceptance evidence: Delivered/accepted/rejected quantities and remaining PO reconcile after partial receipt.
- Record schema/API/service and unified UI or worker changes, relevant positive/denied/failure/recovery checks, source revision and artifact paths. Keep local contract verification separate from external qualification; never count a fake result as a connected provider/model.

### AI-04 — Ricky scope/estimate assistance and deterministic calculation tools

The [Company integration contract](AI04_COMPANY_READ_INTEGRATION.md) and [published native checkpoint](evidence/r1/company-ricky-native-r10/README.md) now cover durable Company read runs, four deterministic tools, embedded SAP UI5 selection, actual HTTP/RQ delivery and original-session/source authorization. The [bounded concurrent-claim correction](evidence/r1/company-ricky-native-r11/README.md) also passed. The earlier [47-check tool slice](evidence/r1/ai04-isolated-tools-tests.json) remains historical evidence for its source. The [R12 checkpoint](evidence/r1/company-ricky-native-r12/README.md) qualifies committed-checkpoint recovery, current-authority refusal and execution-quarantine restoration. The [R13 prospective Company command history](evidence/r1/company-ricky-native-r13/README.md) now passes actual event/receipt/visibility checks. Persisted reviewable suggestions are next; the Company history interface, human draft-save commands and actual Ricky model connection remain unfinished. OS-kill, Redis-loss and restored-site recovery are not claimed. No domain writer or approval tool is activated.

- Release: R1. Status: active.
- Required locally verified contracts: COM-01, EST-03, AI-03.
- Implement: Ricky scope/estimate assistance and deterministic calculation tools.
- Required acceptance evidence: Cited suggestions produce reviewable drafts; fabricated quantities never become accepted facts.
- Record schema/API/service and unified UI or worker changes, relevant positive/denied/failure/recovery checks, source revision and artifact paths. Keep local contract verification separate from external qualification; never count a fake result as a connected provider/model.

### UX-03 — Commercial/estimate/award/procurement pages including dense editing

The [complete cost/planning checkpoint](evidence/r1/cost-planning-fresh-gate-v4-passed.json) passed 553backend tests, eight workflow procedures and 151 browser cases. The [main UI capture](evidence/r1/cost-planning-main-ui-v4/README.md) passed nine actual responsive read-only screens after correcting public-asset packaging and capture readiness. Cost-authoring and final-plan evidence remain the separate connected isolated-site journeys above; positive main award and dependent procurement remain pending.

- Release: R1. Status: active.
- Required locally verified contracts: COM-02, EST-03, BUY-03, UX-02.
- Implement: Commercial/estimate/award/procurement pages including dense editing.
- Required acceptance evidence: Keyboard/paste/validation works on estimate lines; all transitions operate through shared APIs.
- Record schema/API/service and unified UI or worker changes, relevant positive/denied/failure/recovery checks, source revision and artifact paths. Keep local contract verification separate from external qualification; never count a fake result as a connected provider/model.

### FIN-02 — Invoice intake, duplicate detection, matching and service/no-PO exceptions

- Release: R2. Status: planned.
- Required locally verified contracts: FIN-01, BUY-03.
- Implement: Invoice intake, duplicate detection, matching and service/no-PO exceptions.
- Required acceptance evidence: Original supplier evidence retained; duplicate/variance resolution explicit; no accidental posting.
- Record schema/API/service and unified UI or worker changes, relevant positive/denied/failure/recovery checks, source revision and artifact paths. Keep local contract verification separate from external qualification; never count a fake result as a connected provider/model.

### FIN-03 — Installed-work certificates, supplier applications and stored-material consumption

- Release: R2. Status: planned.
- Required locally verified contracts: FIN-02.
- Implement: Installed-work certificates, supplier applications and stored-material consumption.
- Required acceptance evidence: Prior/current/cumulative work reconciles; material is not billed twice when installed.
- Record schema/API/service and unified UI or worker changes, relevant positive/denied/failure/recovery checks, source revision and artifact paths. Keep local contract verification separate from external qualification; never count a fake result as a connected provider/model.

### FIN-04 — Independent approval and Purchase Invoice posting with exact GL comparison

- Release: R2. Status: planned.
- Required locally verified contracts: FIN-03, GOV-03, INT-01.
- Implement: Independent approval and Purchase Invoice posting with exact GL comparison.
- Required acceptance evidence: Changed facts/self-posting denied; invoice, consumed grant, receipt and outbox commit together.
- Record schema/API/service and unified UI or worker changes, relevant positive/denied/failure/recovery checks, source revision and artifact paths. Keep local contract verification separate from external qualification; never count a fake result as a connected provider/model.

### FIN-05 — Retainage withholding/release and linked credits/corrections

- Release: R2. Status: planned.
- Required locally verified contracts: FIN-04.
- Implement: Retainage withholding/release and linked credits/corrections.
- Required acceptance evidence: Release transfers retained to ordinary payable without duplicate cost; paid/closed-period cases explicit.
- Record schema/API/service and unified UI or worker changes, relevant positive/denied/failure/recovery checks, source revision and artifact paths. Keep local contract verification separate from external qualification; never count a fake result as a connected provider/model.

### INT-02 — QuickBooks capabilities, mapping, OAuth storage and sandbox handoff/readback

- Release: R2. Status: planned.
- Required locally verified contracts: INT-01, MIG-01, FIN-04.
- Implement: QuickBooks capabilities, mapping, OAuth storage and sandbox handoff/readback.
- Required acceptance evidence: Provider supported document mapping proven where credentials exist; unknown outcomes do not create duplicates.
- Record schema/API/service and unified UI or worker changes, relevant positive/denied/failure/recovery checks, source revision and artifact paths. Keep local contract verification separate from external qualification; never count a fake result as a connected provider/model.

### INT-03 — BILL/payment route mapping, status import and reconciliation

- Release: R2. Status: planned.
- Required locally verified contracts: INT-02, FIN-05.
- Implement: BILL/payment route mapping, status import and reconciliation.
- Required acceptance evidence: One nominated payment creator; confirmed/held/failed/unknown distinct; retry never pays twice.
- Record schema/API/service and unified UI or worker changes, relevant positive/denied/failure/recovery checks, source revision and artifact paths. Keep local contract verification separate from external qualification; never count a fake result as a connected provider/model.

### INT-04 — Inventory/asset/labor/adjustment effect classification and official-origin import rules

- Release: R2. Status: planned.
- Required locally verified contracts: INT-02.
- Implement: Inventory/asset/labor/adjustment effect classification and official-origin import rules.
- Required acceptance evidence: No unclassified GL effect exported; QuickBooks-origin adjustments do not echo back.
- Record schema/API/service and unified UI or worker changes, relevant positive/denied/failure/recovery checks, source revision and artifact paths. Keep local contract verification separate from external qualification; never count a fake result as a connected provider/model.

### FIN-06 — Owner applications, Sales Invoice posting and retainage receivable

- Release: R2. Status: planned.
- Required locally verified contracts: FIN-01, FIN-05.
- Implement: Owner applications, Sales Invoice posting and retainage receivable.
- Required acceptance evidence: Claimed/reviewed/SOV totals reconcile; issue/send separate from posting.
- Record schema/API/service and unified UI or worker changes, relevant positive/denied/failure/recovery checks, source revision and artifact paths. Keep local contract verification separate from external qualification; never count a fake result as a connected provider/model.

### FIN-07 — Receipts, allocation, returns, deposits, credits and collections

- Release: R2. Status: planned.
- Required locally verified contracts: FIN-06, INT-02.
- Implement: Receipts, allocation, returns, deposits, credits and collections.
- Required acceptance evidence: Allocation bounded by actual open balances; returned receipt restores eligible amount only.
- Record schema/API/service and unified UI or worker changes, relevant positive/denied/failure/recovery checks, source revision and artifact paths. Keep local contract verification separate from external qualification; never count a fake result as a connected provider/model.

### FIN-08 — Operational/official reconciliation, WIP and period close

- Release: R2. Status: planned.
- Required locally verified contracts: FIN-05, FIN-07, INT-04.
- Implement: Operational/official reconciliation, WIP and period close.
- Required acceptance evidence: Unresolved differences reported; policy-driven close blocks incompatible postings.
- Record schema/API/service and unified UI or worker changes, relevant positive/denied/failure/recovery checks, source revision and artifact paths. Keep local contract verification separate from external qualification; never count a fake result as a connected provider/model.

### UX-04 — Unified AP/AR/retained balance/collections/reconciliation pages

- Release: R2. Status: planned.
- Required locally verified contracts: FIN-08, UX-03.
- Implement: Unified AP/AR/retained balance/collections/reconciliation pages.
- Required acceptance evidence: Human can complete supplier and owner journeys without Desk; real captures include exception states.
- Record schema/API/service and unified UI or worker changes, relevant positive/denied/failure/recovery checks, source revision and artifact paths. Keep local contract verification separate from external qualification; never count a fake result as a connected provider/model.

### AI-05 — Ricky coding/matching/explanations and granted-action execution

- Release: R2. Status: planned.
- Required locally verified contracts: FIN-08, AI-04.
- Implement: Ricky coding/matching/explanations and granted-action execution.
- Required acceptance evidence: Tool cannot invent debt or bypass posting duties; exact proposal/source binding verified.
- Record schema/API/service and unified UI or worker changes, relevant positive/denied/failure/recovery checks, source revision and artifact paths. Keep local contract verification separate from external qualification; never count a fake result as a connected provider/model.

### PRJ-03 — Change events, contract changes, budget transfers and forecast versions

- Release: R3. Status: planned.
- Required locally verified contracts: PRJ-02, FIN-01.
- Implement: Change events, contract changes, budget transfers and forecast versions.
- Required acceptance evidence: RFI impact alone does not change contract; approved/pending exposure distinctly reported.
- Record schema/API/service and unified UI or worker changes, relevant positive/denied/failure/recovery checks, source revision and artifact paths. Keep local contract verification separate from external qualification; never count a fake result as a connected provider/model.

### PRJ-04 — Schedule baseline, dependencies, calendars, progress and lookahead

- Release: R3. Status: planned.
- Required locally verified contracts: PRJ-03.
- Implement: Schedule baseline, dependencies, calendars, progress and lookahead.
- Required acceptance evidence: Cycle invalidation and changed baseline history tested; forecast uses declared progress basis.
- Record schema/API/service and unified UI or worker changes, relevant positive/denied/failure/recovery checks, source revision and artifact paths. Keep local contract verification separate from external qualification; never count a fake result as a connected provider/model.

### FLD-01 — Daily reports, photos, installed quantities and T&M tickets

- Release: R3. Status: planned.
- Required locally verified contracts: PRJ-01, DOC-01.
- Implement: Daily reports, photos, installed quantities and T&M tickets.
- Required acceptance evidence: Accepted records amend with lineage; acknowledged T&M does not silently amend contract.
- Record schema/API/service and unified UI or worker changes, relevant positive/denied/failure/recovery checks, source revision and artifact paths. Keep local contract verification separate from external qualification; never count a fake result as a connected provider/model.

### FLD-02 — Offline capture envelopes and explicit conflict resolution

- Release: R3. Status: planned.
- Required locally verified contracts: FLD-01, GOV-02.
- Implement: Offline capture envelopes and explicit conflict resolution.
- Required acceptance evidence: Repeated reconnect does not duplicate event; revoked project access prevents sync effects.
- Record schema/API/service and unified UI or worker changes, relevant positive/denied/failure/recovery checks, source revision and artifact paths. Keep local contract verification separate from external qualification; never count a fake result as a connected provider/model.

### OPS-01 — Compatible Frappe HR installation, crews/classifications/time approval, payroll handoff and job-cost allocation

- Release: R3. Status: planned.
- Required locally verified contracts: FLD-01, INT-04.
- Implement: Compatible Frappe HR installation, crews/classifications/time approval, payroll handoff and job-cost allocation.
- Required acceptance evidence: Provider totals reconcile to approved time; no duplicate payroll execution or inferred rates.
- Record schema/API/service and unified UI or worker changes, relevant positive/denied/failure/recovery checks, source revision and artifact paths. Keep local contract verification separate from external qualification; never count a fake result as a connected provider/model.

### OPS-02 — Asset/rental equipment allocations, meters, maintenance and costing

- Release: R3. Status: planned.
- Required locally verified contracts: OPS-01, INT-04.
- Implement: Asset/rental equipment allocations, meters, maintenance and costing.
- Required acceptance evidence: Rate revision/source retained; operational usage and official asset accounting reconcile.
- Record schema/API/service and unified UI or worker changes, relevant positive/denied/failure/recovery checks, source revision and artifact paths. Keep local contract verification separate from external qualification; never count a fake result as a connected provider/model.

### ENG-01 — RFI and submittal revisions, checking/dispositions and controlled distribution

- Release: R3. Status: planned.
- Required locally verified contracts: DOC-02, GOV-03.
- Implement: RFI and submittal revisions, checking/dispositions and controlled distribution.
- Required acceptance evidence: Successor revisions retain originals; technical response does not authorize commercial change.
- Record schema/API/service and unified UI or worker changes, relevant positive/denied/failure/recovery checks, source revision and artifact paths. Keep local contract verification separate from external qualification; never count a fake result as a connected provider/model.

### ENG-02 — Engineering work packages, design basis, calculations, checking and deliverables

- Release: R3. Status: planned.
- Required locally verified contracts: ENG-01.
- Implement: Engineering work packages, design basis, calculations, checking and deliverables.
- Required acceptance evidence: Author/checker and source units enforced; completed calculation is not automatically issued.
- Record schema/API/service and unified UI or worker changes, relevant positive/denied/failure/recovery checks, source revision and artifact paths. Keep local contract verification separate from external qualification; never count a fake result as a connected provider/model.

### ENG-03 — Existing Ricky CAD/takeoff/calculation tool adapters and isolated jobs

- Release: R3. Status: planned.
- Required locally verified contracts: ENG-02, AI-02.
- Implement: Existing Ricky CAD/takeoff/calculation tool adapters and isolated jobs.
- Required acceptance evidence: Actual supported tool input/output fixture passes; cancellation/readback and immutable output verified.
- Record schema/API/service and unified UI or worker changes, relevant positive/denied/failure/recovery checks, source revision and artifact paths. Keep local contract verification separate from external qualification; never count a fake result as a connected provider/model.

### DOC-03 — Issued sets/transmittals, specifications/contracts library and adopted revisions

- Release: R3. Status: planned.
- Required locally verified contracts: DOC-02, ENG-01.
- Implement: Issued sets/transmittals, specifications/contracts library and adopted revisions.
- Required acceptance evidence: Source update does not overwrite adopted/executed text; current rights enforced.
- Record schema/API/service and unified UI or worker changes, relevant positive/denied/failure/recovery checks, source revision and artifact paths. Keep local contract verification separate from external qualification; never count a fake result as a connected provider/model.

### DOC-04 — Qdrant semantic index and actual embedding adapter with ACL rechecks

- Release: R3. Status: planned.
- Required locally verified contracts: DOC-03, AI-03.
- Implement: Qdrant semantic index and actual embedding adapter with ACL rechecks.
- Required acceptance evidence: Unauthorized snippets/citations never enter context; deletion/reindex reproducible.
- Record schema/API/service and unified UI or worker changes, relevant positive/denied/failure/recovery checks, source revision and artifact paths. Keep local contract verification separate from external qualification; never count a fake result as a connected provider/model.

### FLD-03 — QA/QC inspections, deficiencies, safety observations/incidents and permits

- Release: R3. Status: planned.
- Required locally verified contracts: FLD-01, ENG-01.
- Implement: QA/QC inspections, deficiencies, safety observations/incidents and permits.
- Required acceptance evidence: Closure requires evidence; sensitive incident fields hidden from general project users.
- Record schema/API/service and unified UI or worker changes, relevant positive/denied/failure/recovery checks, source revision and artifact paths. Keep local contract verification separate from external qualification; never count a fake result as a connected provider/model.

### ENG-04 — Commissioning, punch, O&M/warranties and asset handover/closeout

- Release: R3. Status: planned.
- Required locally verified contracts: ENG-02, DOC-03, FLD-03.
- Implement: Commissioning, punch, O&M/warranties and asset handover/closeout.
- Required acceptance evidence: Required missing evidence blocks completion; turnover package contains exact accepted revisions.
- Record schema/API/service and unified UI or worker changes, relevant positive/denied/failure/recovery checks, source revision and artifact paths. Keep local contract verification separate from external qualification; never count a fake result as a connected provider/model.

### RPT-01 — Project/portfolio dashboards, job cost, forecasts and snapshot exports

- Release: R3. Status: planned.
- Required locally verified contracts: FIN-08, PRJ-03, OPS-02.
- Implement: Project/portfolio dashboards, job cost, forecasts and snapshot exports.
- Required acceptance evidence: As-of watermarks visible; private project values excluded from aggregates and exports.
- Record schema/API/service and unified UI or worker changes, relevant positive/denied/failure/recovery checks, source revision and artifact paths. Keep local contract verification separate from external qualification; never count a fake result as a connected provider/model.

### UX-05 — Connect remaining field/engineering/library/schedule/reporting workflows

- Release: R3. Status: planned.
- Required locally verified contracts: PRJ-04, FLD-02, ENG-04, RPT-01, UX-04.
- Implement: Connect remaining field/engineering/library/schedule/reporting workflows.
- Required acceptance evidence: Full required internal journeys usable in one UI/session with manual paths during model outage.
- Record schema/API/service and unified UI or worker changes, relevant positive/denied/failure/recovery checks, source revision and artifact paths. Keep local contract verification separate from external qualification; never count a fake result as a connected provider/model.

### AI-06 — Cross-domain Ricky AEC workflows and controlled automation inbox

- Release: R3. Status: planned.
- Required locally verified contracts: ENG-03, DOC-04, AI-05.
- Implement: Cross-domain Ricky AEC workflows and controlled automation inbox.
- Required acceptance evidence: Multi-step source/tool provenance retained; budgets, revocation and ambiguous outcomes enforced.
- Record schema/API/service and unified UI or worker changes, relevant positive/denied/failure/recovery checks, source revision and artifact paths. Keep local contract verification separate from external qualification; never count a fake result as a connected provider/model.

### QA-02 — Integrated permission/recovery/accessibility/performance qualification

- Release: R3. Status: planned.
- Required locally verified contracts: UX-05, AI-06.
- Implement: Integrated permission/recovery/accessibility/performance qualification.
- Required acceptance evidence: Completion matrix evidence with actual dataset/hardware; no hidden critical workflow gaps.
- Record schema/API/service and unified UI or worker changes, relevant positive/denied/failure/recovery checks, source revision and artifact paths. Keep local contract verification separate from external qualification; never count a fake result as a connected provider/model.

### MIG-02 — Optional source-specific business-data onboarding into the finalized target model

- Release: R4. Status: planned.
- Required locally verified contracts: MIG-01, FIN-08, DOC-03.
- Implement: Optional source-specific business-data onboarding into the finalized target model.
- Required acceptance evidence: If selected for rollout, imported IDs/counts/balances reconcile; optional transfer never alters architecture to inherit prior workflows.
- Record schema/API/service and unified UI or worker changes, relevant positive/denied/failure/recovery checks, source revision and artifact paths. Keep local contract verification separate from external qualification; never count a fake result as a connected provider/model.

### OPS-03 — Operational identity/secrets, monitored deployment and actual restore rehearsal

- Release: R4. Status: planned.
- Required locally verified contracts: QA-02.
- Implement: Operational identity/secrets, monitored deployment and actual restore rehearsal.
- Required acceptance evidence: Approved environment demonstrates recovery target or reports measured shortfall.
- Record schema/API/service and unified UI or worker changes, relevant positive/denied/failure/recovery checks, source revision and artifact paths. Keep local contract verification separate from external qualification; never count a fake result as a connected provider/model.

### INT-05 — Authorized real accounting integration and controlled writer cutover

- Release: R4. Status: planned.
- Required locally verified contracts: INT-03, MIG-02, OPS-03.
- Implement: Authorized real accounting integration and controlled writer cutover.
- Required acceptance evidence: Actual external acknowledgments/reconciled balances; old writer disabled per migrated class.
- Record schema/API/service and unified UI or worker changes, relevant positive/denied/failure/recovery checks, source revision and artifact paths. Keep local contract verification separate from external qualification; never count a fake result as a connected provider/model.

### REL-01 — Internal pilot rollout, support runbooks, training and defect closure

- Release: R4. Status: planned.
- Required locally verified contracts: INT-05, QA-02.
- Implement: Internal pilot rollout, support runbooks, training and defect closure.
- Required acceptance evidence: Named scenarios completed on operational setup; acceptance and unresolved limits recorded.
- Record schema/API/service and unified UI or worker changes, relevant positive/denied/failure/recovery checks, source revision and artifact paths. Keep local contract verification separate from external qualification; never count a fake result as a connected provider/model.

### ENT-01 — Multi-company/intercompany and separate-site enterprise qualification

- Release: R5. Status: planned.
- Required locally verified contracts: REL-01.
- Implement: Multi-company/intercompany and separate-site enterprise qualification.
- Required acceptance evidence: Isolation and supported consolidation/intercompany transactions verified on declared requirements.
- Record schema/API/service and unified UI or worker changes, relevant positive/denied/failure/recovery checks, source revision and artifact paths. Keep local contract verification separate from external qualification; never count a fake result as a connected provider/model.

### ENT-02 — Enterprise SSO/SCIM/delegation, legal hold/retention and audit export

- Release: R5. Status: planned.
- Required locally verified contracts: ENT-01.
- Implement: Enterprise SSO/SCIM/delegation, legal hold/retention and audit export.
- Required acceptance evidence: Identity lifecycle and retention verified; no unsupported certification claims.
- Record schema/API/service and unified UI or worker changes, relevant positive/denied/failure/recovery checks, source revision and artifact paths. Keep local contract verification separate from external qualification; never count a fake result as a connected provider/model.

### ENT-03 — Scale, disaster recovery, security review and commercial packaging

- Release: R5. Status: planned.
- Required locally verified contracts: ENT-02.
- Implement: Scale, disaster recovery, security review and commercial packaging.
- Required acceptance evidence: Measured enterprise workloads, resolved findings, license obligations and support evidence.
- Record schema/API/service and unified UI or worker changes, relevant positive/denied/failure/recovery checks, source revision and artifact paths. Keep local contract verification separate from external qualification; never count a fake result as a connected provider/model.

## Autonomous lanes

Platform/GOV/API/INT-01 shared infrastructure precedes dependent workflows. PRJ/DOC and UI may proceed on agreed contracts while AI adapter work proceeds independently. Contract/SOV base schemas precede atomic award orchestration. COM/EST/BUY/FIN and field/engineering follow their declared dependencies. MIG-01 defines generic target import/export, not recovery of old designs. MIG-02 is optional business-data onboarding after the target model is complete.

R0 delivers the project/document/Ricky/proposed-task journey and durable async recovery. R1–R3 do not depend on live credentials; their local contracts can be verified with clearly labeled fixtures while actual external qualification remains pending. R4 operational rollout requires the real facts/access appropriate to the chosen deployment. A missing optional source import does not prevent launching with a fresh company dataset.

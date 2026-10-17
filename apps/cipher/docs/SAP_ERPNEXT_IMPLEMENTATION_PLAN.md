# Cipher — The AEC/CMS Pro: integrated product and implementation plan

**Superseded historical planning:** The latest owner direction requires a new product design independent of all prior Cipher/Odoo work. Odoo is interim operations only. Use [the new framework draft](framework/README.md); prior reuse, migration-dependency and workflow prescriptions below are not design inputs. Implementation awaits the owner’s framework approval.

**Latest planning boundary:** The owner requested a complete framework draft before authorizing implementation. Review [the framework package](framework/README.md). This worktree contains planning documentation and reserved module boundaries only; executable implementation awaits that approval.

Owner decision: October 15, 2026. Status: architecture selected; implementation and operational qualification remain to be completed.

This is the active implementation order. It supersedes framework-selection checkpoints and conflicting Fluent, Odoo-core, custom-engine and visual instructions in earlier plans. The owner has selected reuse of mature open-source foundations and autonomous delivery. Do not reopen a framework competition or require the owner to build, install or test the product. Engineering owns verification and presents working results.

## Product identity and scope — latest owner clarification

**Cipher — The AEC/CMS Pro** is the entire ERP/CMS product. Cipher CMS Pro is the short product name. It is not the old Python engine, an approval workflow, an ERPNext extension alone or a collection of separate practice applications. SAP UI5, ERPNext/Frappe and Ricky are implementation foundations inside one product experience. Internal package names such as `cipher_aec` do not define the product boundary.

The capability benchmark combines SAP S/4HANA-style enterprise operations with Trimble Construction One-style connected construction delivery, plus deeply embedded Ricky AEC intelligence. These are breadth and quality references, not claims of feature parity, licensed access, compatibility or endorsement. Use open-source foundations where they fit; implement and integrate the missing AEC capabilities. Do not clone proprietary code or build a general ERP from scratch.

The product spans pursuit and CRM, proposals, estimating and takeoff, design/engineering, project controls, procurement, supply chain, construction finance, field delivery, equipment/assets, workforce, document control, quality/safety, commissioning/closeout and portfolio management. Each module shares identity, company/project/WBS/cost-code context, documents, search, notifications and audit history. Users should not have to switch into ERPNext Desk or separate Ricky software to complete normal work. Restricted platform administration may use its underlying tools.

Existing Cipher code is a source of requirements and useful evidence, not an architectural constraint. Keep only what improves this product. Replace prototype plumbing, restrictive UI compositions and redundant data ownership. Preserve actual business history and validated controls through explicit migration, without requiring the new system to reproduce every old internal abstraction.

## Ricky: embedded AEC intelligence and controlled automation

Ricky is a first-class product subsystem from Stage 1, not a chat widget added after the ERP. Integrate the local model and AEC work already being developed in other sessions; do not train a replacement or assume the old deterministic `domain/ricky.py` is that model. This checkout exposes a prototype tool catalog and rule-based guidance, but does not establish the local model's weights, serving runtime, endpoint, adapters, hardware requirements or complete AEC tool inventory. Recover that existing deployment contract when connecting it. This is integration discovery, not a framework-selection exercise.

### Architecture and reusable components

| Component | Implementation direction | Responsibility |
|---|---|---|
| Local inference | Adapter to the existing Ricky serving runtime; preserve its model and adapters | Streaming inference, capability discovery, model version, health, cancellation and resource limits |
| Ricky orchestration | Dedicated server module/worker integrated with Frappe; use its existing job infrastructure initially | Plan tasks, retrieve context, invoke registered tools, persist runs and recover interruptions |
| Model/tool gateway | Typed, versioned tool schemas over Cipher business APIs and specialist adapters | Validate arguments, enforce actor permissions and policy, bind source versions and receipt every effect |
| Knowledge and retrieval | Frappe record/permission metadata plus versioned object storage and a replaceable search adapter | Project-scoped retrieval with document/page/revision citations and access filtering before model context |
| Semantic search | Qdrant when semantic retrieval is introduced, alongside exact metadata/text search | Reusable open-source vector indexing; never the source of business truth or sole permission boundary |
| Artifact storage | S3-compatible versioned storage abstraction, local filesystem adapter for development | Original drawings, PDFs, images, calculations, outputs and checksums independent of model memory |
| Specialist AEC execution | Reuse existing Ricky CAD/calculation/takeoff tools through bounded job adapters | Sandboxed workspaces, declared units/software versions, reproducible inputs and returned artifacts |
| Observability | Persist run/tool provenance; OpenTelemetry-compatible instrumentation | User-visible progress, diagnostics, cost/resource accounting and correlation to business changes |

Do not add a second general workflow engine or agent framework merely for AI branding. Start with Frappe transactions/jobs and a durable Ricky run model. Add a dedicated orchestration platform only if demonstrated long-running recovery requirements exceed that foundation. Keep inference replaceable; model weights have their own license and deployment conditions, independent of the ERP/UI licenses. Pin the actual component versions during implementation.

### Ricky capabilities inside the product

- **Commercial and estimating:** retrieve prior relevant work, draft scope/exclusions, extract quantities with evidence, propose assemblies/rates, compare revisions and surface missing assumptions. Deterministic services calculate accepted quantities and totals.
- **Engineering:** assist design exploration, calculations, drawing/CAD jobs, specifications, code/reference lookup, interdisciplinary coordination and checking packages. Preserve units, assumptions, input versions, citations and review status; a model response is not a checked or sealed deliverable.
- **Project/CMS:** prepare RFIs/submittals, compare drawing revisions, connect field evidence to changes, draft daily reports and identify schedule, procurement and cost exposure.
- **Finance:** prepare coding/matching recommendations, explain variances and reconciliation exceptions, assemble billing support and propose collections actions through the same governed APIs as human users.
- **Portfolio/operations:** answer cross-project questions within the user's permissions, prepare forecasts/scenarios, prioritize work queues and execute delegated routine operations within explicit policy.

Expose Ricky through the persistent application panel, contextual actions on records, task/run inbox and reviewable proposed changes. Show source links, affected records, planned effects, current status, failures and cancellation. A user can inspect the exact changes before a consequential action. Ordinary business functions continue working if the inference service is unavailable.

### Autonomy and control model

“Heavy AI control” means broad automation with enforceable operating authority, not forcing every action into a read-only chatbot or granting an LLM database-administrator access.

1. Read/explain/search within current company/project/document permissions.
2. Draft and perform reversible preparation under configured user delegation, including extraction and specialist jobs within resource limits.
3. Execute defined operational actions under explicit policy, scope, value limits, source versions and expiry; persist the authorization and operation receipt.
4. Route consequential financial, contractual, issued engineering and external-delivery actions through the required independent authorization. Execute granted actions through transactional services; Ricky cannot approve itself, assign its own permissions or bypass professional sign-off.

Treat documents, retrieved text and tool output as untrusted input rather than instructions. The gateway independently checks permissions and effect policy on each call. Do not allow arbitrary SQL/shell execution from model text. Apply tool allowlists, isolated job environments, secret boundaries, concurrency budgets, cancellation and durable original-operation recovery. Training on business records requires an explicit data policy; retrieval does not imply permission to fine-tune on or export those records. Cloud fallback is separately configurable, not a silent transmission of local model context.

### Integrate Ricky throughout delivery

- **Stage 1:** define the existing model connection contract; build the gateway, persistent run records and embedded panel. Deliver permission-filtered project questions with citations and one reviewed project/task draft against real ERPNext records. If the actual model endpoint is unavailable, label adapter fixtures honestly and continue backend/UI work; do not present a simulated response as live Ricky.
- **Stage 2:** attach prior local AEC tools to estimate/document services; deliver a cited scope draft and revision-linked takeoff/estimate assistance with reproducible calculations.
- **Stages 3–4:** enable AP/AR preparation, exception explanations and explicitly authorized execution with durable recovery and independent financial duties.
- **Stage 5:** connect CAD/engineering jobs, field capture and change/forecast assistance into the same task/run and artifact system.
- **Stage 6:** verify model upgrades, permission leakage, prompt injection, invalid units, unsupported engineering answers, tool misuse, interruption/replay and resource exhaustion. Use maintained AEC task fixtures and expected business outcomes, not only conversational benchmarks.

The first integrated demonstration is **project → source document → Ricky cited answer/proposed task → authorized save → visible project history**, in one persistent UI5 application. This demonstrates the shared product architecture before expanding all modules. Engineering owns the checks and produces actual running-browser evidence.

## 1. Committed architecture

| Layer | Decision | Responsibility |
|---|---|---|
| Product | Cipher — The AEC/CMS Pro, tailored to S&A | One working application across commercial, construction, engineering and finance |
| Interface | React/TypeScript/Vite with SAP UI5 Web Components for React | Official navigation pattern, modern Horizon theme and Fiori-derived business pages |
| ERP | ERPNext on Frappe | Standard business documents, masters, projects, procurement, inventory, operational accounting and administration |
| AEC domain implementation | Custom Frappe app `cipher_aec` | Construction contracts, takeoffs, controls, engineering and domain-specific approval services |
| Business API | Versioned methods in `cipher_aec`, consumed through the authenticated application boundary | Typed read models and transactional commands; no duplicate business database |
| Embedded intelligence | Existing local Ricky model plus governed tools and AEC job adapters | Contextual assistance and controlled automation across every module |
| Official accounting | QuickBooks initially | Official books, reconciled with ERPNext operational records and ledger |
| Payments | Preserve the established BILL/QuickBooks route | Governed payment handoff, authoritative status and reconciliation |
| Prior Odoo work | Controlled migration and adapters | Recover accepted data, configuration and external IDs; no parallel operational writer |

This is not an installation of SAP S/4HANA. SAP supplies the open-source UI components; ERPNext supplies the ERP backend. UI5 does not require a SAP ERP subscription or SAP sign-in. Application authentication remains a separate implementation task.

Use ERPNext's normal transactional accounting deliberately. Submitting Sales Invoices and Purchase Invoices creates ERPNext GL entries. ERPNext is the operational ledger; QuickBooks is the official accounting authority. Retire the overlapping native Cipher ledger for each migrated workflow after reconciliation. Do not hide accounting effects, keep all invoices permanently in draft, or maintain three writable representations of the same obligation.

## 2. Reuse and ownership

| Workflow | Reuse from ERPNext/Frappe | Cipher AEC implementation |
|---|---|---|
| Business masters | Company, Customer, Supplier, Contact, Address, Item, UOM, dimensions | External IDs, ownership mappings, construction cost codes, project duties |
| Commercial | Lead, Opportunity, Quotation, Sales Order, pricing | Scope/assumptions/exclusions, immutable proposal revisions, review, issue, award handoff |
| Estimating/takeoff | Rates, items, supplier quotes, units, project references | Calibrated revision-linked quantities, assemblies, labor/material/equipment build-ups, alternatives, contingency and accepted baseline |
| Projects | Project, Task, templates, Timesheet, Cost Center | WBS, baseline budgets, commitments, forecast, milestones, change exposure, construction closeout |
| Procurement | Material Request, RFQ, Supplier Quotation, PO, Purchase Receipt, stock | Project release, partial delivery/variance, service purchases, stored-material eligibility |
| Subcontracts/AP | Supplier, Purchase Invoice, credits, payment terms, PO/receipt links | Construction SOV, claimed/reviewed work, certification, retainage, intake/duplicate evidence, independent approval/posting |
| Owner billing/AR | Customer, Sales Invoice, credits, receivables and allocations | Prime SOV, progress/unit-price applications, retainage, permitted contract forms, approved issue/send, collections |
| Field/labor/equipment | Tasks, timesheets, assets, stock, expense records | Daily reports, crew classifications, T&M, installed quantities, equipment rates, photos, offline capture and payroll handoff |
| Engineering/CMS | DocTypes, Files, permissions, jobs, notifications | RFIs, submittals, drawing/spec revisions, checking, transmittals, CAD job provenance, QA/QC and closeout |
| Libraries | Document models, metadata, permissions and search | Authored revisions, clauses, rights/provenance, project adoption, redlines and issued/executed distinctions |
| Reporting | Standard reports, GL, dimensions | Job-cost/WIP interpretation, forecast, executive/project views, reconciliation and exceptions |
| Identity/automation | Users, roles, workflow, sessions/API mechanisms, background jobs | Canonical-person binding, duty separation, exact-fact approvals, recovery receipts and Ricky's policy-bound automation |

ERPNext manufacturing subcontracting is not construction subcontract management. Standard Project/Task records are a foundation, not complete AEC controls. Specialized takeoff, CAD and engineering tools attach through explicit APIs and versioned artifacts; do not rebuild a CAD engine inside the ERP.

## 3. Repository and migration boundaries

Keep new implementation under the Cipher project:

- `apps/cipher/platform/`: pinned deployment, environment examples, health checks, backup/restore and upgrade runbooks.
- `apps/cipher/platform/apps/cipher_aec/`: installable Frappe application, DocTypes, migrations, transactional services and integration workers.
- `apps/cipher/product/`: the single production-target React/UI5 client and generated API types.
- Existing `core/`, `domain/`, `tests/`, `web/` and practice servers remain historical/regression sources during migration. They are not the target runtime architecture.

The prototype's standard-library restriction continues to protect its existing engine. The owner-selected ERPNext/Frappe application uses its own pinned dependency environment; do not insert platform packages into the old engine. Preserve existing schemas, audit history, stored codes and qualified evidence. Introduce explicit migration mappings rather than rewriting historical databases.

Reuse exact-money rules, source lineage, independent approval/posting, immutable receipts, person separation and recovery cases as portable requirements and test oracles. Port necessary controls into the authoritative Frappe transaction, including generic submit/cancel routes. A UI button restriction or a standard Workflow configuration alone is insufficient.

Retire the old navy shell, Fluent frontend and separate practice product shells as migrated journeys become available. Preserve their historical evidence. Avoid an ERPNext core fork; use supported custom-app hooks, extensions and migrations. Recover Odoo data/configuration without restarting an Odoo-versus-ERPNext evaluation.

## 4. UI implementation contract

Start from SAP's actual [navigation-layout pattern](https://github.com/UI5/webcomponents-react/tree/c7f0f6eb891cad18fd776b77ea11eda123970052/patterns/navigation-layout) and [Vite/TypeScript example](https://github.com/UI5/webcomponents-react/tree/c7f0f6eb891cad18fd776b77ea11eda123970052/examples/vite-ts). Use the modern standard Horizon appearance first, with restrained S&A branding through supported theming.

Compose ShellBar, SideNavigation, FilterBar, VariantManagement, ObjectPage, ObjectStatus, MessageView and suitable tables into compact task-focused pages. Do not carry the rejected custom navy frame or long audit narratives into a new component library. Put evidence/history in contextual sections. Show business names, readable document numbers, server totals and clear actions.

One session, company/project selector, search, work queue and linked record context serve the whole product. Main areas are My Work, Commercial, Estimating, Projects, Procurement/AP, Billing/AR, Engineering/Documents, Field, Reports and Administration. Navigation is permission-aware; server authorization remains authoritative.

Registers support filtering, saved views, paging, selection and useful commands. Estimating needs deliberate editable-table behavior, keyboard entry, paste and exact calculations; AnalyticalTable alone is not a spreadsheet engine. Do not adopt the deprecated UI5 chart package as the reporting foundation. File views must display real stored artifacts and their revisions.

Verify loading, empty, error, stale, blocked and read-only states; keyboard/screen-reader behavior; WCAG 2.2 AA; desktop, tablet and phone layouts. Field capture has explicit offline/retry behavior. Financial approval and release require authoritative online checks. Actual running-browser screenshots and task recordings are delivery evidence; generated images are not.

## 5. Ordered delivery backlog

Each stage produces usable integrated workflows. Internal checks verify the implementation; they are not another technology-selection exercise or owner homework.

### Stage 1 — Install the foundation and deliver the real application frame

1. Resolve the container storage constraint, then provision isolated persistent database, Redis, ERPNext/Frappe, workers, scheduler and frontend services. Pin compatible versions and image digests, with health checks and restart behavior.
2. Install `cipher_aec`; create migrations, synthetic company/master fixtures, secrets handling and dependency/license inventory. Establish backup and restore procedures immediately.
3. Define record ownership, external-ID mappings, exact amounts/units, document versions and authoritative command contracts. Establish API schemas and generated client types.
4. Implement identity/session handling, company/project permissions and canonical-person duties. Start with synthetic accounts; configure operational identity separately when available.
5. Build the actual UI5 shell, project register, project overview and personal work queue against persistent ERPNext data. Deliver real browser captures and a reproducible launch command.

**Completion evidence:** A user signs in, opens and updates an authorized project through Cipher, restarts the stack and sees the same record. An unauthorized user cannot read or change it. Captures show the real UI5 application.

### Stage 2 — Commercial, estimating and project setup

6. Implement customer/opportunity → proposal/quotation, scope, revisions, review and controlled issue.
7. Implement drawing/spec upload and revision registers, calibrated quantity capture, assemblies, rate build-ups, alternatives and estimate comparison.
8. Bind acceptance to exact estimate/source revisions. Award into project, contract, WBS and budget without rekeying; preserve the accepted baseline.
9. Deliver procurement requests, supplier quotations, PO approval, partial receipts and construction commitment/SOV records.

**Completion evidence:** One representative synthetic opportunity becomes an awarded project and partial procurement receipt with traceable quantities, prices and revisions.

### Stage 3 — Supplier AP and accounting integration

10. Deliver invoice capture, duplicate handling, matching, service/no-PO exceptions, installed-work certification, stored materials and retainage.
11. Port exact-fact business approval and independent operational posting into transactional Frappe services. Implement credits, cancellation/reversal and separate replacement without history edits.
12. Implement durable outbox, mapping manifests, original logical-operation IDs, retry/readback and reconciliation for QuickBooks. Treat remote acceptance as separate from local posting.
13. Preserve BILL payment routing and reconcile payment status. Unknown remote outcomes remain unresolved until authoritative readback; do not blindly create another payment or invoice.
14. Reconcile migrated obligations/balances and retire their overlapping prototype-ledger writes.

**Completion evidence:** Supplier obligation through correction and accounting handoff, including interrupted-worker recovery and duplicate prevention. Sandbox evidence is explicitly labeled; real official-account delivery is claimed only after actual authorized integration succeeds.

### Stage 4 — Owner billing, AR and financial close

15. Implement prime contract/SOV, claimed/reviewed quantities, progress/unit-price billing, retainage and rights-cleared contract outputs.
16. Deliver independent approval/posting, issued snapshots, controlled distribution, credits, receipts/allocation and collections work queues.
17. Deliver job cost, WIP, cash exposure, aging, reconciliation exceptions and close procedures with clear operational-versus-official accounting labels.

**Completion evidence:** Awarded project through an owner application, receivable, allocation and reconciled close, including changed-fact and correction paths.

### Stage 5 — Full construction and engineering delivery

18. Implement daily reports, crews, time, equipment, T&M tickets, installed quantities, photos and offline field capture/recovery.
19. Complete changes, forecast-to-complete, commitments, schedule/lookahead, QA/QC, punch lists and closeout.
20. Implement connected RFI/submittal review and distribution, issued drawing/spec sets, transmittals and revision-aware references.
21. Implement engineering checking, calculation/deliverable lineage and controlled CAD/cloud-job integrations. Professional seals and licensed content retain their actual authorization boundaries.
22. Complete contract/specification libraries, clauses/templates, source rights, adoption, redlines and executed-record links.

**Completion evidence:** A project team carries a change from field evidence through engineering review, commercial impact and current forecast; issued records remain reproducible.

### Stage 6 — Internal rollout and enterprise development

23. Recover Odoo mappings/checkpoints, rehearse migration, compare source and destination totals, preserve original IDs and document exceptions. Cut over one authoritative writer per record class with rollback procedures.
24. Complete operational identity, authorized provider configuration, monitoring, backups, restore quarantine and runbooks. Use a controlled internal rollout rather than silently promoting synthetic workspaces.
25. Verify representative volumes, accessibility, concurrent approvals, worker interruption, upgrade/migration and disaster recovery. Record measured performance against declared workloads.
26. Expand multi-company isolation, delegation, SSO/SCIM where needed, retention/legal hold, exportability, integration contracts and administrative controls for enterprise use.
27. Use repeated internal operating cycles to close defects and gaps. Maintain an auditable requirements-to-delivery matrix, support practices and release evidence before claiming enterprise readiness.

**Completion evidence:** The required internal workflows operate with durable data, accountable users, reconciled books, recoverable services and documented support. Fortune 500 suitability remains a future evidence-based qualification, not a template or architecture claim.

## 6. Integration and financial rules

Approval, ERPNext operational posting, QuickBooks delivery/acknowledgment and payment are distinct states. No local success is represented as remote success. Each integration has one nominated writer, stable source IDs, mapping versions, durable receipts and conflict handling. Never allow bidirectional synchronization to create posting loops.

Financial policy, payee destinations and duties remain explicit. Ricky can read, draft and execute an already authorized scoped action; it cannot approve itself or change its own authority. Server-side permission checks, source/version binding and independent duties apply through every route, including background jobs and direct ERP APIs.

Build adapters and synthetic/sandbox exercises autonomously. Actual credentials and factual business settings may be necessary for live connections; request only those concrete missing inputs when they block the corresponding delivery step. Do not interpret a framework decision as approval to move real money.

## 7. Current evidence and immediate work

The prior ERPNext Docker trial failed twice with `failed to register layer: no space left on device` before application startup. The local daemon uses `vfs`; extraction exhausted available storage. No ERPNext runtime workflow passed. Provision adequate container storage through supported environment configuration, inspect capacity and retry once the cause is addressed. Do not repeatedly pull into the same insufficient setup, prune unrelated work or change protected daemon settings as a shortcut.

The UI5 source review identified Apache-2.0 components and usable patterns; it did not deliver the replacement UI. Existing screenshots show the rejected prototype. Existing native tests remain evidence for that prototype, not automatic ERPNext qualification.

The next implementation work is Stage 1: durable ERPNext deployment, `cipher_aec`, the UI5 project workflow, and the embedded Ricky gateway/run model. The initial connected journey includes a source document, cited Ricky assistance and an authorized saved change. Stop expanding the rejected native practice interfaces. Independent schema/API and UI work can proceed while environment provisioning is resolved.

## 8. Licensing, delivery and continuity

UI5 Web Components for React is Apache-2.0; Frappe is MIT; ERPNext is GPLv3. Commercial use is permitted, with applicable notices and source/distribution obligations. Track the actual packages and modifications; do not describe the whole stack as MIT or assume that a separate HTTP service removes obligations. Review concrete distribution packaging before external commercialization. Proprietary SAPUI5/Fiori Elements runtime is outside this selection.

Engineering owns automated and manual verification, dependency compatibility, screenshots and fixes. The owner receives usable delivery evidence and concise blocker explanations. No recurring framework approval or owner-run test exercise is part of this plan. Preserve repository-required checks before commits; maintain truthful completion status and resume from a durable handoff across sessions.

Use the existing single Astra ultra orchestration/escalation agent and explicitly configured GPT-6.1 Sol implementation agents. Do not create another Astra agent or resume agents with an unverified model assignment. Parallelize independent work behind agreed contracts; keep authoritative migrations and shared-file integration coordinated.

Reference audit and comparison history: [ERP foundation review](ERP_FOUNDATION_REVIEW.md). Full business requirements: [Product goal](PRODUCT_GOAL.md). Historical rejected-design diagnosis: [Fluent reset plan](FLUENT_ERP_RESET_PLAN.md). Those documents do not reopen this owner-approved architecture.

# Cipher: Fluent product reset and autonomous delivery plan

**Superseded historical planning:** The latest owner direction requires a new product design independent of all prior Cipher/Odoo work. Odoo is interim operations only. Use [the new framework draft](framework/README.md); prior reuse, migration-dependency and workflow prescriptions below are not design inputs. Implementation awaits the owner’s framework approval.

**Committed owner decision, October 15, 2026:** [SAP_ERPNEXT_IMPLEMENTATION_PLAN.md](SAP_ERPNEXT_IMPLEMENTATION_PLAN.md) is the active architecture and delivery plan: SAP UI5 Web Components for React, ERPNext/Frappe, Cipher AEC extensions, and QuickBooks as official accounting authority. The owner selected implementation, without further framework comparisons or owner-run trials. Conflicting options and checkpoints below are historical and superseded.

Owner direction: October 15, 2026. Status: reassessment complete; replacement UI not yet implemented or accepted.

**Foundation decision reopened by the owner:** [ERP_FOUNDATION_REVIEW.md](ERP_FOUNDATION_REVIEW.md) is the latest addendum. It recommends UI5 Web Components for React as the stronger ERP page-scaffold candidate, with Fluent 2 retained when Microsoft visual fidelity is mandatory. It also requires a bounded ERPNext/Frappe versus accepted Odoo/native-control proof before selecting the operational platform. The business scope and 30-step delivery sequence below remain; Fluent-specific implementation choices are provisional until that checkpoint. No UI or backend migration has been performed by the review.

This is the active delivery plan for Cipher. It supersedes the navy shell, locally invented T1–T10 visual compositions and practice-app expansion strategy in the earlier UI specification. It preserves the business scope in `PRODUCT_GOAL.md` and qualified domain behavior. The existing screenshots are a baseline of the rejected design, not an accepted design to extend.

## 1. Outcome and diagnosis

Build S&A's own ERP, using Microsoft's actual open-source Fluent React foundation and interaction patterns, tailored to the company's commercial, construction, engineering and financial work. Staff should use one application, one session, one project context and linked records from proposal through closeout. QuickBooks remains the official accounting system initially; Cipher owns its business workflows. Accepted Odoo work is reusable data, configuration and integration evidence, not a requirement to send staff to a second application.

The prior implementation used real Fluent components but did not deliver the requested product experience:

- The old specification explicitly required the navy frame and custom templates. These instructions propagated the rejected appearance.
- Custom CSS duplicated Fluent colors and recreated navigation, badges, notices and page compositions. Importing Fluent buttons did not make the whole application reference-faithful.
- The shared facts component made names, dates and technical facts large and bold. Repeated sections turned routine work into long audit narratives.
- Registers lacked the filtering, views, commands and editing behavior needed for daily office work. Three estimate lines occupied a 2,807-pixel-tall screenshot.
- Separate practice applications demonstrated backend slices, but did not establish a connected ERP with persistent shared work.
- Automated correctness and accessibility checks were treated as stronger product evidence than they are. They cannot establish visual fidelity, workflow fit or owner acceptance.

Preserve exact money, approval/posting separation, source and revision lineage, scoped authority, original-request recovery, audit history and migration compatibility. Replace the visual shell and page hierarchy. Adapt existing clients and presenters to business-facing read models. Keep old practice entries as regression harnesses while the unified application replaces them.

## 2. Microsoft foundation and design rules

The reference audit inspected official Microsoft source at Fluent repository commit `93e324f72f0e187ff6a7e5f70ebf929d9b2212a2`. This is a source-reference pin, not a demand to update every dependency. Existing pinned Fluent React `9.74.3` already exports the stable components needed for the first replacement.

| Cipher foundation | Actual Microsoft reference | Required use |
|---|---|---|
| React/Vite provider and theme | [Official Fluent v9/Vite starter](https://github.com/microsoft/fluentui/tree/93e324f72f0e187ff6a7e5f70ebf929d9b2212a2/starter-templates/src/react-components-vite) | Start with `FluentProvider` and unmodified `webLightTheme`; retain compatible pinned dependencies, CSP and focus behavior |
| Application navigation | [Contoso HR Nav example](https://github.com/microsoft/fluentui/blob/93e324f72f0e187ff6a7e5f70ebf929d9b2212a2/packages/react-components/react-nav/stories/src/Nav/Basic.stories.tsx) | Compose stable `NavDrawer`, `NavItem`, `NavCategory`, headers and regular/filled icons; do not recreate the control in CSS |
| Office navigation density | [Variable-density Nav example](https://github.com/microsoft/fluentui/blob/93e324f72f0e187ff6a7e5f70ebf929d9b2212a2/packages/react-components/react-nav/stories/src/Nav/VariableDensityItems.stories.tsx) | Compact desktop navigation; deliberate touch behavior |
| Working registers | [DataGrid example](https://github.com/microsoft/fluentui/blob/93e324f72f0e187ff6a7e5f70ebf929d9b2212a2/packages/react-components/react-table/stories/src/DataGrid/Default.stories.tsx) | Sorting, appropriate selection, keyboard navigation and cell layouts; implement domain filtering/paging/views explicitly |
| Commands and hierarchy | [Toolbar](https://github.com/microsoft/fluentui/tree/93e324f72f0e187ff6a7e5f70ebf929d9b2212a2/packages/react-components/react-toolbar/stories/src/Toolbar), [Breadcrumb](https://github.com/microsoft/fluentui/tree/93e324f72f0e187ff6a7e5f70ebf929d9b2212a2/packages/react-components/react-breadcrumb/stories/src/Breadcrumb) | Consistent command placement, overflow and location; all visible commands have truthful behavior |
| Forms, validation and contextual detail | [Field](https://github.com/microsoft/fluentui/tree/93e324f72f0e187ff6a7e5f70ebf929d9b2212a2/packages/react-components/react-field/stories/src/Field), [Drawer](https://github.com/microsoft/fluentui/tree/93e324f72f0e187ff6a7e5f70ebf929d9b2212a2/packages/react-components/react-drawer/stories/src/Drawer), [MessageBar](https://github.com/microsoft/fluentui/tree/93e324f72f0e187ff6a7e5f70ebf929d9b2212a2/packages/react-components/react-message-bar/stories/src/MessageBar) | Native label/error/focus patterns; contextual evidence; material blockers near the relevant action |
| Typography, spacing, surfaces and states | [Fluent 2](https://fluent2.microsoft.design/), [React documentation](https://react.fluentui.dev/), [tokens](https://github.com/microsoft/fluentui/tree/93e324f72f0e187ff6a7e5f70ebf929d9b2212a2/packages/tokens/src) | One token system; no duplicate hard-coded neutral palette or blanket cell/hover overrides |
| Icons | [Microsoft Fluent System Icons](https://github.com/microsoft/fluentui-system-icons) | Existing pinned React icon package and official icon conventions |

Microsoft's starter is a small scaffold, not a complete ERP, Dynamics, SharePoint or Teams application. Component examples are reusable source; product screenshots are design guidance, not evidence of an open-source product implementation. Fluent code uses the [MIT license](https://github.com/microsoft/fluentui/blob/93e324f72f0e187ff6a7e5f70ebf929d9b2212a2/LICENSE); preserve notices and separately check fonts, logos, assets and third-party packages. Do not redistribute Microsoft branding or assume Segoe font redistribution rights.

Design rules:

1. Establish the recognizable light-neutral Microsoft Fluent baseline first. Add restrained S&A identity through supported tokens after visual review. Do not reproduce the navy rail by default.
2. Use stable Fluent controls for navigation, grids, toolbars, fields, tabs, badges, messages, dialogs and drawers. Custom composition is necessary for AEC work; document its upstream patterns and intentional differences.
3. Build a single shared shell and reusable business surfaces, not another collection of domain entry applications.
4. A working register has a title, commands, useful filters/views, record count, grid, status/owner/due information and predictable return navigation. Saved views and server paging are features to implement, not capabilities assumed from importing DataGrid.
5. A record has compact identity/status/amount facts, focused work content and contextual documents/history. A decision surface shows the facts and consequences necessary to decide. Routine technical proof stays accessible in history/help/details.
6. Use dense, comparable estimate and SOV lines on desktop. Support deliberate line editing and source inspection. Do not render one large form per row.
7. Keep one clear environment indicator. Show additional warnings only when they affect the user's task. Preserve material restrictions and financial consequences.
8. Use useful company/project data and actual work queues. Unsupported metrics are absent or clearly unavailable; never invent revenue, margin, forecast or completion percentages.
9. Test default, selected, hover, focus, disabled and validation states against the same upstream reference at the same viewport. Automated accessibility results supplement visual and manual usability review.
10. Use appropriate specialist viewers/editors behind the Fluent application where Microsoft does not supply them, such as PDF/CAD viewing and calibrated measurement. Evaluate their licenses and integration separately; never invent a Fluent takeoff component.

Do not install the currently audited Contrib Azure theme as a shortcut: its React peer range excludes the project's React 19. Use a dependency change only for a concrete justified requirement. Add grid virtualization when representative volume warrants it.

## 3. S&A workspaces and shared records

This is the complete product map, not a claim that each area exists. Validate details against accepted company records and prior work; distinguish confirmed business requirements from synthetic examples.

| Workspace | Required business work | Cross-module connection |
|---|---|---|
| My work / Company | Assigned reviews, overdue work, deadlines, project exceptions and supported business summaries | A combined work queue across a person's actual duties |
| Business development | Customers/contacts, opportunities, bid dates, proposal revisions, scope, alternatives and award/loss | Accepted estimate and exact issued proposal become project/contract sources |
| Estimating and takeoffs | Drawing/spec revisions, calibrated measurements, quantities/units, assemblies, rates, labor/material/equipment, vendor quotes, contingency and bid comparisons | Accepted price/quantity baseline feeds proposal, budget and procurement |
| Projects | Project number/client/team/phase, WBS/cost codes, contract basis, budget, commitments, forecast, schedule, changes and closeout | Shared project context connects all work |
| Procurement / AP | Vendors/subs, POs, receipts, supplier invoices, subcontract pay apps, retainage, credits, approvals, posting and payment status | Source evidence and project costs reconcile to official books |
| Owner billing / AR | Contracts/SOV, progress/unit-price billing, forms, issue/send, receipts, credits, retainage, aging and collections | Billing sources, current balance and QuickBooks acknowledgment remain linked |
| Construction delivery | RFIs, submittals, daily reports, installed quantities, T&M, quality/safety, punch/closeout | Changes and field evidence feed cost, schedule and billing through reviewed actions |
| Engineering | Design tasks, calculation packages, design/check/review, drawing revisions, deliverables and transmittals | Reproducible specialist jobs return actual artifacts tied to project/source versions |
| Documents and libraries | File bytes, previews, metadata/search, revisions, specs, clauses/templates, rights, project adoption and issued packages | Same document/revision identity across estimating, AP, CMS and engineering |
| Labor and equipment | Time, crews, approvals/corrections, equipment allocation/use and job-cost/payroll handoff | Approved source records feed costs without duplicate payroll/accounting ownership |
| Finance / Reporting | Job cost, forecasts, WIP, AP/AR control accounts, reconciliation, close and exception resolution | QuickBooks official records and Cipher operational sources reconcile |
| Administration | People/duties, project access, policies, integrations, reference data, audit and recovery | Server-enforced authority and supportable operation |

Project-level navigation retains the selected project across tools. Company registers include project context and allow removing that filter. Related records link directly to the original source, successor, issued artifact and financial outcome where relevant. One person with multiple duties sees their combined work; the operational UI does not offer a role impersonation picker.

The linked record graph is: opportunity → estimate/takeoff revision → proposal revision → award/contract → project/WBS/budget → commitment/PO → field receipt/work → AP obligation and owner billing → official accounting acknowledgment → reconciliation/closeout. Documents, engineering deliverables, changes and approvals attach to the appropriate version along this graph.

## 4. Ordered implementation steps

Each step has a deliverable and completion evidence. Later independent foundations can proceed in parallel; module-wide UI conversion waits for the reference design gate. There is no percentage-complete claim or calendar promise based on test counts.

### Phase A — Correct the direction

**01. Preserve the baseline.** Record PR/branch, current source snapshots, actual screenshots, qualified behavior and pending checks. Preserve interrupted/failed evidence honestly. Stop extending the rejected shell. **Done when:** developers can distinguish current main, isolated candidates, durable behavior and disposable demonstrations.

**02. Supersede conflicting instructions.** Link this plan from the UI specification, product goal and backlog. Replace active navy/custom-template and Odoo-as-required-UI directives. Keep earlier documents as history. **Done when:** the next assignment cannot reasonably reproduce the rejected design by following an active specification.

**03. Publish a source-to-component register.** Pin the Microsoft references above; record adapted source paths, license notices, local components and intentional differences. **Done when:** the shell and every reusable interaction can be traced to a real reference or an explicitly justified AEC composition.

**04. Build the business traceability matrix.** For each workspace above, identify actor, trigger, input/output records, next step, exceptions, integration owner and acceptance walk. Recover existing forms, cost codes and Odoo mapping evidence without treating unknown details as confirmed. **Done when:** every supplied business requirement has an implementation owner and an observable acceptance scenario.

### Phase B — Prove the visual foundation before scaling

**05. Build the clean reference shell.** Derive provider/theme setup from the official starter and navigation from the official Nav example. Add company/project context, responsive navigation, profile/access state and functional command placement. Reuse compatible current packages. **Done when:** one running application shows real API-backed Home, Projects and project-detail navigation at desktop/tablet/phone widths.

**06. Implement the first operational register and record.** Use DataGrid, Toolbar, Breadcrumb, Field, Badge, TabList and Drawer where appropriate. Provide real sorting/filtering, meaningful record columns and preserved navigation context. Start with Projects and an existing AP or RFI register. **Done when:** a user finds overdue/assigned work, opens it and returns to the same view without switching ports or losing the project.

**07. Recompose one complete AP review flow.** Show invoice/pay-app source, comparable claimed/reviewed lines where supported, amount/status, relevant blockers and the next action. Retain independent approval and posting. **Done when:** the actual backend completes a representative review and separate posting through concise screens, with evidence/history accessible and original-request recovery preserved.

**08. Prove the difficult estimating/document composition.** Implement a compact line-item editing surface and real document viewing once actual file bytes are available. Show quantity, unit, rate and amount together; open source/line detail contextually. **Done when:** a small estimate is comparable in a practical desktop workspace and saved through the actual API. Manual entry is identified as manual; calibrated measurement is not claimed until step 15.

**09. Complete the visual/usability gate.** Capture the running shell, register, project, AP review and estimate/document work beside the pinned references at 1440, 1024 and 390 pixels. Review focus/hover/error states and ordinary task completion. Present one consolidated owner checkpoint before propagating the design across every module. **Done when:** the visual direction is accepted and observed usability defects are resolved. Continue independent backend/document/integration work while feedback is pending. Do not ask for another abstract framework choice.

### Phase C — Make one operational application

**10. Establish the shared API and routing model.** Consolidate typed reads/actions under one backend-for-frontend and one application route graph. Add consistent business-facing errors, record numbers, paging/filtering and cross-record links. Keep deterministic calculations and consequential controls on the server. **Done when:** supported modules share project context and records, and stale/concurrent requests cannot silently apply different facts.

**11. Complete real staff identity and access.** Finish Entra session integration, canonical-person mappings, project duties, onboarding/offboarding, CSRF/session lifecycle and server authorization. Isolate synthetic persona selection to test harnesses. **Done when:** one real authorized staff session can cross modules; forbidden project access, forged roles and account aliases cannot bypass controls. Actual tenant/app facts are needed for live qualification, not for building the Fluent UI.

**12. Complete durable records and operations.** Add the operational host, lifecycle/migration commands, persisted action/worker outcomes, restart recovery and support diagnostics. Evaluate the database against representative concurrent work; retain a deliberate database migration path instead of assuming prototype SQLite proves enterprise scale. **Done when:** restart/retry preserves records and original operations; restore/quarantine/reconciliation drills succeed on the selected pilot runtime.

**13. Complete the document service.** Store actual bytes with immutable revision identity, access controls, upload validation/scanning, previews, downloads, retention and issued snapshots. Connect evidence references to those artifacts. **Done when:** a permitted user can open the exact drawing/invoice/spec version another workflow cites; unauthorized reads and broken/missing artifacts are handled truthfully.

**14. Establish master-data and integration ownership.** Map customers/vendors, projects, cost codes, items, terms, chart/dimensions and external IDs. Reuse accepted Odoo/BILL configuration through explicit migration/adapter choices. **Done when:** reconciliation and deduplication prove one writer per record class; Cipher staff workflows do not depend on jumping between module UIs.

### Phase D — Deliver commercial work through project setup

**15. Finish real takeoff and estimating.** Add PDF scale calibration, linear/area/count measurements, units, revision overlays/change comparison, assemblies, labor/material/equipment detail, quotes, alternatives and contingency. Bind each saved measure to page/revision/scale. Use specialist CAD jobs for supported cases. **Done when:** checked example drawings reproduce expected quantities and a changed drawing creates a traceable estimate revision; no inferred geometry is labeled verified.

**16. Finish proposals and award handoff.** Add opportunity/bid context, proposal scope/exclusions/terms, revisions, independent review, actual issued document generation, authorized distribution and award/loss. **Done when:** one accepted estimate becomes an issued proposal and an awarded contract/project baseline without rekeying or losing original price/source lineage. An internal issue is not labeled customer acceptance or signature.

**17. Finish project setup and controls.** Build WBS/cost-code budgets, prime contracts, SOV, commitments/POs, change events/orders, forecasts and schedule links. **Done when:** the awarded baseline feeds procurement, costs, changes and billing through linked records, and later revisions preserve the original baseline.

### Phase E — Complete financial business workflows and official-book reconciliation

**18. Finish AP intake and matching.** Include invoice bytes, duplicate detection, quantity POs, partial receipts, non-PO invoices, subcontract claimed/reviewed pay apps, stored materials, retainage and coding. **Done when:** ordinary and mismatch/duplicate/partial-receipt scenarios produce the correct obligation or a clear hold, with no duplicate payable.

**19. Finish AP corrections and payment status.** Complete approval, independent posting, credits, reversals/replacements, holds, recorded payments and reconciliation to the established payment route. **Done when:** a supplier cycle and its correction/return cases reconcile; original decisions and payment history remain inspectable. Payment recording is distinct from moving money.

**20. Finish owner billing.** Complete reviewed quantities/SOV, unit-price/progress billing, authorized form templates, retainage, approval, actual issued snapshots and sending. **Done when:** a representative application/invoice preserves exactly what was issued, including reviewed adjustments and the right project/contract revision. Licensed forms require actual rights.

**21. Finish receipts and collections.** Complete partial/multiple allocations, fees, returns, deposits, credits/write-offs where authorized, retainage release, aging and collection work. **Done when:** balance/history and follow-up queues reflect actual supported events; reversals and duplicate attempts do not corrupt receivables.

**22. Qualify the QuickBooks/BILL adapters.** Build stable source/remote IDs, chart/dimension mappings, durable attempts/acknowledgments, reconciliation, credential refresh and recovery from timeouts/rate limits/version conflicts. **Done when:** representative AP/AR/credit/payment records match authoritative readback and control totals. Unknown outcomes recover the original request; no blind duplicate financial write. Live writes wait for the concrete integration and required authorization.

**23. Complete reporting and close.** Add reconciled project cost, forecast, WIP, AP/AR/control-account reports, period rules and close exceptions. **Done when:** the controller accepts policies and representative parallel closes agree with QuickBooks. Native replacement of official books remains an optional separate project, not a prerequisite for a working Cipher ERP.

### Phase F — Complete construction, engineering and field delivery

**24. Complete RFIs, submittals and document control.** Integrate registers, owners/due dates, reviewed responses/dispositions, package revisions, transmittals and closeout links into the shared project. **Done when:** ordinary and revise/resubmit cycles preserve exact issued sources and show actionable overdue work. A response does not imply a contract change or engineering certification.

**25. Complete engineering work and libraries.** Add design tasks, calculation packages, checking/review, drawing/deliverable revisions, specifications and contract/clause search/adoption. Implement bounded specialist jobs with reproducible inputs and returned artifact checks. **Done when:** a representative engineering package progresses from source through checking to an authorized issued artifact set; source rights, revisions and project adoption are preserved.

**26. Complete field, labor and equipment workflows.** Add daily reports, installed quantities, T&M, delivery evidence, time/crew approvals/corrections, equipment use and payroll handoff. Add offline capture only for suitable work. **Done when:** a representative crew week and field-change cycle reconcile to project cost; offline retries do not duplicate time, quantities or attachments; financial decisions retain required online checks.

**27. Complete quality, safety and closeout.** Add required inspections/issues, punch lists, completion documents, O&M/as-builts, warranties and retainage prerequisites for the confirmed business scope. **Done when:** a project reaches closeout with an owned checklist and complete linked deliverables; required evidence is retrievable.

### Phase G — Prove internal completion and prepare growth

**28. Migrate and rehearse a representative company workflow.** Validate master data and opening project balances, roles, document permissions and external identifiers. Run the entire proposal-to-project-to-billing path through one application. **Done when:** no required step relies on a disconnected practice entry, hidden manual database edit or fabricated integration result.

**29. Run the internal pilot.** Prepare live identity/integration facts, staff workflow training, support ownership and the agreed project. Run representative billing, supplier, change, engineering and close cycles. **Done when:** users complete their work, accounting reconciles, material exceptions have owners and the required acceptance scenarios pass.

**30. Qualify operation and growth.** Exercise backup/restore, deployment rollback, integration outage and recovery; measure performance and accessibility on representative data. Then qualify broader entity/isolation, scale, security review, retention, localization and support requirements for enterprise expansion. **Done when:** the internal system is supportable with measured evidence. Potential Arcadis/Fortune 500 interest is an ambition, not a readiness claim.

## 5. Autonomous execution and review

- **Orchestration and escalations:** exactly one explicitly configured `gpt-6-astra` agent at `ultra` effort for this reset. **Implementation and independent review:** explicitly configured `gpt-6.1-sol` agents. Previous inherited-model workers are paused; do not resume them under unknown model settings. Tool control covers spawned workers, not verification or switching of the parent conversation model.
- Assign bounded work by files and domain contracts. One owner controls shared navigation, schema integration and cross-module API changes. Reviewers work independently; do not copy whole stale clones over newer source.
- Build vertical business outcomes. Each work item records scope, source/reference, dependencies, actual implementation, validation, screenshot/demo where relevant, known gaps and next action.
- Fix the design foundation before converting all screens. Do not mechanically wrap the old long pages in a new header.
- Use regression, domain, integration and browser checks appropriate to the change. Preserve original schema text and historical evidence. Follow the repository's full-suite-before-commit rule, but never substitute a test count for user acceptance.
- Provide milestone evidence from the running container: real screenshots, short task walkthroughs, changed files and limitations. Never generate an image as proof of implemented UI or fake a successful backend response.
- Continue independent work when tenant details, accounting policy, licensed content or credentials block one lane. Ask concise, scoped questions when the answer is necessary. Do not repeatedly ask the owner to select Fluent, QuickBooks or the already stated ERP scope.
- Before external sending, live financial writes, deployment or a material accounting-policy change, make the proposed action and its evidence concrete, then obtain any required authorization. Local reversible implementation proceeds autonomously.
- Maintain resumable checkpoints and report actual errors with their impact and next action. Do not claim uninterrupted 24-hour background execution or an ability to override platform/session limits.

## 6. Completion definition and immediate work order

Internal completion means S&A's required workflows operate through **one accepted Fluent application**, with actual staff authority, durable shared records/documents/actions, reconciled accounting handoffs, usable accessible screens and rehearsed support/recovery. Every required workflow needs an acceptance scenario; a screen inventory or passing synthetic suite is insufficient.

The immediate execution order is **01–04 → 05–07 → first reference-screen checkpoint → 08–09**, while **10–14** progress where independent. Then deliver the linked commercial/project/financial journeys and required construction/engineering/field tracks. Some later capabilities can run in parallel once their shared contracts and dependencies are ready; none is removed from the scope by that sequencing.

Current reset status:

| Item | Status |
|---|---|
| Current UI/code and official Microsoft source audit | Complete, read-only |
| Active design/delivery reset | This document; linked from governing product documents |
| Model-specific reset team | One explicitly configured Astra ultra agent and Sol 6.1 audit workers; earlier workers paused |
| Replacement reference shell/screens | Next implementation deliverable; not yet built or visually accepted |
| Existing domain and isolated candidates | Preserved; pending test runs retain their own source/status evidence |
| Live operational ERP / enterprise readiness | Not complete |

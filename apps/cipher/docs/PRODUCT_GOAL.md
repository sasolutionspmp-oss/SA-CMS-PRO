# Cipher product goal and design contract

Owner direction recorded October 14, 2026. This goal extends the [UI overhaul specification](UI_OVERHAUL_SPEC.md) and [delivery backlog](DELIVERY_BACKLOG.md). It supersedes a narrower interpretation of Cipher as only a set of Odoo extensions. It defines the product to deliver; it is not a claim that these capabilities are implemented.

## Goal

Deliver Cipher as S&A's complete working ERP and construction/engineering management system: a tested backend linked to a consistent Microsoft Fluent 2 interface, covering proposal through project closeout and the full AP/AR business lifecycle. QuickBooks may supply authoritative accounting through an API. Cipher must remain usable as the business workflow owner with that accounting integration, and its architecture must permit a separately qualified native accounting system later.

Use S&A's internal work to prove the product over repeated operating cycles. Design the boundaries and quality controls so that, after further development and evidence from internal use, a large AEC firm could evaluate it. Arcadis is an example of the intended caliber of prospective customer, not an endorsement, known customer requirement or current readiness claim.

## Responsibilities and reusable work

| Area | Cipher responsibility | External boundary |
|---|---|---|
| Commercial development | Opportunities, proposal revisions, scope, assumptions, exclusions, pricing, review, issue and award handoff | Reuse current customer/opportunity records and correspondence through mapped integrations |
| Estimating and takeoffs | Drawing/spec revision references, measured quantities and units, assemblies, rates, quotes, alternatives, labor/equipment/material breakdowns, contingency and accepted estimate baseline | Licensed cost content and specialist takeoff/CAD jobs retain source, rights and checked result references |
| Projects and CMS | Project/WBS/cost-code structure, budgets, forecasts, commitments, procurement, changes, schedule, documents, field quantities, RFIs, submittals, quality, safety and closeout | Reuse accepted Odoo data, configuration and workflows through explicit import or adapter decisions |
| AP | Vendor/invoice intake, duplicate and matching checks, pay apps, stored materials, retainage, review, approval, posting handoff, credits/corrections, holds and payment status | QuickBooks owns official accounting initially; preserve the established BILL payment route while its current mappings are verified |
| AR | Customer terms, contract/SOV billing, progress and unit-price applications, issue/send approvals, retainage, credit memos, receipts, aging and collection work | Official invoices, receipts and balances reconcile through the selected accounting route; document preparation is distinct from posting and sending |
| Engineering delivery | Design tasks, calculations, checked deliverables, drawing revisions, technical review, transmittals and project links | CAD and other specialist execution runs as bounded jobs with reproducible inputs, versions, review and returned artifacts |
| Specifications and contracts library | Versioned source documents, metadata, search, clause/template provenance, access and content rights; project-specific adoption and revisions | No assumed right to ingest or redistribute licensed content; signatures and issued documents remain separately authorized acts |
| Labor and equipment | Time, crew/quantity/job cost, approvals and corrections, equipment allocation and payroll handoff | Payroll execution/filings and regulated outputs use the agreed qualified provider/process |
| Accounting and reporting | Working subledgers, journal proposals, job-cost/WIP reporting, reconciliation and exception workflows | QuickBooks is initially authoritative; a native ledger requires its own accounting, migration, close and recovery acceptance |

Earlier Odoo catch-up work is owner-confirmed. Recover its latest reconciliation checkpoint and retain accepted artifacts and stable source IDs. For each record class, choose adopt/import/adapter ownership explicitly. Cipher owns the requested user workflow; this does not authorize a competing writer to the same customer, invoice, journal or payment. Neither the presence of an adapter nor an exported file proves a successful remote posting.

## Backend and accounting design

Keep the deterministic domain engine independent of the UI, assistant and accounting provider. Organize it by commercial, estimating, project controls, AP/AR, engineering/document library and governance domains with explicit service contracts. Begin with a modular application; introduce separate services only when measured deployment, load or security needs justify them.

The authenticated backend-for-frontend described in UI spec section 11 supplies typed, versioned reads and actions, server-derived identity/duties, scoped permissions, structured errors, concurrency/version checks and idempotency. The backend calculates quantities, exact money, approval facts and accounting effects. A browser or language model does not decide financial truth. Microsoft Entra sessions are the initial identity direction; Fluent components need no account.

Put accounting behind a provider contract: capability discovery, chart/dimension mappings, counterparties, authorized invoice/bill/credit/journal handoffs, acknowledgements, status reads, balances and reconciliation. Every request carries the authoritative source/version, accounting entity, immutable approval/posting receipt and a stable logical operation reference. Persist delivery attempts and outcomes independently from domain approval. Handle retries, remote version conflicts, duplicate callbacks, rate limits, expired credentials, partial failures and unknown outcomes. Do not represent a working/shadow posting as an accepted QuickBooks posting, or a simulated payment as a completed BILL/bank payment, without authoritative acknowledgement and reconciliation evidence. An unknown timeout must not trigger a blind new payment.

Read-only connected company metadata now confirms QuickBooks Online Advanced. Use [the accounting adapter plan](QUICKBOOKS_ADAPTER_PLAN.md) for normalized sources, mappings, durable outcomes and reconciliation. Verify actual API capabilities, sandbox behavior and approval of the live route; the connector's company identifier and CompanyInfo singleton ID do not supply the OAuth realm ID. Secrets stay server-side. A simulated adapter proves local behavior only. A future native ledger uses the same business-facing contract but must prove controller-approved policies, control accounts, period locks, corrections, tax/currency/entity behavior, migration and parallel closes before replacing official books.

Preserve existing audit history, schema checksums, stored codes, approval manifests, restored-copy quarantine and governor behavior. Approval, posting, contract signature, external sending and payment release remain separate named acts. Ricky remains read/draft-only in the served application; approved external specialist jobs do not grant it accounting authority.

The connected [practice accounting handoff](ACCOUNTING_PRACTICE.md) implements the first normalized installed-work obligation through fixed simulated delivery and separate readback. It preserves original cost, AP and retainage, binds a versioned synthetic period-end date rule, and requires independent accountant authorization. Its disposable in-memory worker refuses file workspaces and preserves unknown-outcome recovery within the original process. It supplies local control evidence; production transport, persisted provider history, official posting policies and broader AP/AR/credit routes still need qualification.

## Fluent 2 design contract

Use the researched UI specification's React/TypeScript/Vite and Fluent UI React v9 direction. Follow its shell, company/job hierarchy, role home pages, T1–T10 page templates, record/lifecycle patterns, grid behavior, status vocabulary and responsive layouts. Extend those patterns to proposals, estimating/takeoffs, engineering and library screens rather than introducing a second visual system. Pin actual published package versions and retain the lockfile; verify compatibility and licensing instead of assuming the spec's version examples are available.

Use S&A navy, white surfaces, neutral grays, restrained lime on navy, the specified type/spacing/density tokens, Fluent System Icons and keyboard/focus patterns. The final lime/logo assets remain a branding dependency; placeholders are sufficient for reviewable practice work. Microsoft components supply the design system, not a complete ERP application template. The application templates are the ones defined in the existing spec.

Every screen must have truthful loading, error, empty, filtered, stale, blocked and read-only states. Use plain business words, readable record numbers, server totals and clear effects before consequential clicks. Never present a missing action as functional. Demonstrate 1440 px desktop, 1024 px tablet and 390 px phone layouts; meet WCAG 2.2 AA with keyboard, screen-reader and contrast review. Field workflows get deliberate offline/retry behavior; financial approval and release remain online.

## Internal completion gates

The backend plus UI is fully functional for the agreed internal scope only when each required workflow is usable and accepted through the actual interface/API, including its failure and recovery paths:

1. A proposal and revision-linked takeoff/estimate become an awarded project and governed budget/contract without rekeying or losing quantity, unit, price, source and revision lineage.
2. Supplier invoices and subcontract pay apps traverse intake, matching, review, independent approval/posting, credits/corrections, payment recording and reconciliation. Stored materials, retainage, partial receipts, duplicates, changed facts and held/unknown payments have accepted paths.
3. Owner billing traverses reviewed quantities/SOV, required forms, approval, issue/send, receipt/credit/retainage, aging and reconciled close. An issued snapshot remains traceable to what the customer received.
4. Project and field work changes forecast/job cost through governed records; schedules, changes, RFIs, submittals, drawing/spec revisions, labor/equipment and closeout agree with their sources.
5. Engineering and specification/contract libraries preserve provenance, revisions, review, permissions, content rights and issued-artifact traceability. A representative specialist design job returns checked artifacts linked to the correct project and source version.
6. Real staff identity and scoped reads/writes enforce duties and separation in the backend. Cross-project access, account aliases, forged roles, stale versions and concurrent retries cannot bypass controls.
7. QuickBooks/BILL acknowledgements, job cost and AP/AR/control-account totals reconcile across representative billing and close cycles. Exceptions have an owner and resolution history. The controller accepts posting/WIP policies and required exports.
8. Users complete representative work through the Fluent screens at all three sizes. Accessibility and performance targets are measured; the spec's p95 read/action targets of 2/3 seconds need an agreed dataset, load and hosting profile.
9. Backup/restore, quarantine, integration outages, deployment/migration and support drills pass with agreed operating responsibilities and measured recovery. No restored workspace sends money or external messages before controlled reconciliation.

The current synthetic, single-entity USD tests prove their listed scenarios only. A completed screen, test count or generated design is not acceptance of the whole product. Record each gate's implementation, evidence, exceptions and next work in [BUILD_STATUS.md](../BUILD_STATUS.md) and the delivery backlog. Calendar estimates follow scoped work and measured delivery, not an invented percentage complete.

## Enterprise quality path

Design and record these boundaries now, then qualify them before claiming enterprise suitability:

| Quality area | Required design and later evidence |
|---|---|
| Organization and isolation | Explicit tenant/entity/project identity, isolated data and documents, delegated administration, entity/currency/tax policies and consolidation boundaries; adversarial isolation tests |
| Identity and authority | Enterprise SSO lifecycle, canonical people, least privilege, project/company duties, controlled service identities, stronger verification for consequential acts and access reviews |
| Data and integrations | Versioned APIs, stable source IDs, migrations, schema compatibility, bulk import/export, reconciled idempotency and documented ownership for every integration |
| Reliability and scale | Database/storage chosen from measured concurrency and volume, worker leases/queues, capacity/load tests, observable failures, recoverable deployments and tested recovery objectives |
| Security and audit | Threat model, protected keys/secrets, document scanning, redaction, external history seals, retention/legal-hold controls, independent security review and tracked remediation |
| Engineering quality | Domain/contract/integration/UI acceptance, failure/concurrency tests, reproducible CI/builds, dependency/license inventory, upgrade policy and representative regression datasets |
| Operations and product support | Documented runbooks, support ownership, diagnostics, incident response, training, accessibility/localization strategy and evidence of stable internal operation |
| Commercial qualification | Requirements discovery with prospective AEC customers, agreed procurement/security/compliance needs and verified fit; no assumed certification or Arcadis-specific requirement |

Years of internal use should produce acceptance records, reconciliation history, performance/recovery measurements and user feedback. Those are the basis for a later enterprise evaluation, not a substitute for it. Enterprise expansion is a separate release gate; it must not block finishing useful S&A workflows.

## Immediate execution

The bill approval/posting engine (B01), bill-specific duties from B02, B04/B08's practice read contract and Fluent shell, and B03's immutable practice boundary are implemented. The separate AP practice entry has scoped synthetic sessions, installed-work bill preparation, invoice evidence selection, receipt, matching, independent match review, PM business approval and independent accountant posting through the shared Fluent templates. The installed-work exception slice adds invoice revision/rejection/duplicate review, original-approver withdrawal and independently approved bill reversal followed by separate replacement. Both practice servers own fresh in-memory data. Production identity, qualified accounting delivery and full workflow acceptance remain open.

Continue with the normalized synthetic accounting handoff, stored-material/PO paths, supplier credit screens and payment status. Preserve the accepted installed-work invoice exception and bill correction/replacement controls. Recover accepted Odoo checkpoints alongside these slices. Complete the scoped authenticated API and one reconciled internal pilot, then expand the required proposal/estimate/takeoff, AR, CMS and engineering/library workflows through accepted end-to-end slices. Preserve all unfinished gates and use each completed internal cycle to prioritize the next demonstrable capability.

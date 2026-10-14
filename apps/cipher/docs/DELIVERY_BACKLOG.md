# Cipher delivery backlog

Updated October 14, 2026. This is the delivery sequence from the synthetic Cipher prototype to S&A's usable ERP workflow across Odoo, Cipher and QuickBooks. It turns [HANDOFF.md](../HANDOFF.md) and [UI_OVERHAUL_SPEC.md](UI_OVERHAUL_SPEC.md) into milestones and a first build queue. [BUILD_STATUS.md](../BUILD_STATUS.md) remains the prototype verification record; this document does not replace it or treat the spec's older percentages and time estimates as current evidence.

The owner's expanded [product goal](PRODUCT_GOAL.md) makes Cipher the working system for proposals, estimating/takeoffs, the full AP/AR business lifecycle, projects/CMS and engineering/specification/contract libraries, linked to a Fluent 2 interface. QuickBooks is an acceptable accounting API; a true native accounting system remains a qualified option. The goal's internal completion and enterprise quality gates govern what may be called complete. The six milestones below are a delivery sequence, not the full feature inventory.

## Existing systems and prior work

The owner confirmed that QuickBooks is in use and that prior work has brought Odoo toward being fully caught up. The recovered September architecture assigned operations to Odoo and construction/engineering extensions to Cipher. The latest owner direction expands Cipher's workflow ownership while retaining QuickBooks as accounting authority until an agreed cutover. Reuse the prior Odoo work through explicit adopt/import/adapter mappings. The latest Odoo reconciliation checkpoint is not present in this checkout; Cipher's synthetic tests cannot establish its live state.

| System | Established responsibility | What the continuation must preserve |
|---|---|---|
| QuickBooks | Current accounting authority | Reconcile Cipher's working records to QuickBooks; no second writer or accounting cutover by default |
| Odoo | Existing operational work and data to recover/reuse; prior catch-up work confirmed by the owner | Recover the latest setup/reconciliation checkpoint; choose record ownership and import/adapter behavior explicitly |
| Cipher | Full commercial, AP/AR, estimating/takeoff, project/CMS and engineering/library workflows and interface | Deliver the owner's full scope; define one writer per record and reconcile authoritative accounting through its adapter |
| BILL | Established payment route in the recovered architecture | Preserve it while its current handoff is mapped and tested; simulator qualification does not prove that route |

Before an overlapping module or integration is implemented, recover the existing Odoo work's version, installed apps, configuration/import artifacts and last reconciliation result from available project records. Record the owning system, stable external IDs, permitted writer and reconciliation rule for each customer, vendor, project, commitment, invoice and payment. List completed, accepted and unresolved items separately. Start with an isolated one-job export/mapping fixture, including duplicate, retry and changed-record cases; retain a checkpoint and exceptions. Credentials become a dependency when testing the actual tenant, not when designing controls, mappings or screens. This is evidence recovery and reuse, not a request to redo the catch-up work.

## What to build next

The bill approval/posting split and immutable practice boundary are implemented. Put a complete practice purchase-to-pay workflow behind typed action contracts, side-effect-free presenters, server-controlled practice sessions and clear screens. Continue the read contract/Fluent shell, recover the Odoo checkpoint and map the accounting handoff. Expand to one pilot job while QuickBooks remains the official books, then complete the required commercial/estimating, AR, CMS and engineering/library tracks. Reuse accepted external work without forcing those user workflows out of Cipher. A future accounting replacement is a separate decision.

The installed-work [AP exception checkpoints](AP_EXCEPTIONS.md) are implemented and verified: 1867 full-suite tests pass, with the Fluent exception journeys checked at three widths. Scoped invoice revision, final rejection and documented possible-duplicate review preserve version history and honest evidence release. Draft cancellation and original-PM withdrawal retain the unposted bill's original history. Invoice changes attached to posted/paid bills wait for a genuine governed correction. An eligible unpaid bill is independently approved for an exact working-ledger reversal in an open period no earlier than its original actual posting, followed by separately certified, matched, reviewed and posted replacement work. The 17 fixed AP commands use the existing registered synthetic people, shared pure checks and original audited receipts. This installed-work slice does not close M1's PO/stored-material, claimed-versus-reviewed revision, credit, payment or owner-acceptance gates.

Next implement the normalized simulated accounting handoff in [QUICKBOOKS_ADAPTER_PLAN.md](QUICKBOOKS_ADAPTER_PLAN.md). Start with one posted AP bill and its immutable posting receipt: versioned audited account/dimension mappings, an immutable source-bound plan, distinct handoff authorization, leased delivery attempts, deterministic simulated acceptance/refusal/lookup and visible reconciliation. Test one effect across exact retry, concurrent claims, duplicate acknowledgements and unknown outcomes; changed mappings or sources require a fresh review. Keep payment providers outside this slice. Recover accepted Odoo/BILL checkpoints in parallel. QuickBooks remains authoritative, and a local simulated acceptance supplies no QuickBooks delivery evidence.

Fluent UI is the screen component library. It needs no Microsoft account or sign-in. Mockups, components, contract mocks, and a local practice build can proceed with synthetic data and server-controlled practice identities. Microsoft Entra ID supplies verified identity for people using the application; tenant setup is required before a live pilot, not before designing the UI. Practice identity stubs must be excluded from any build that can reach live data.

The current engine covers many ERP functions, but it is a synthetic, single-entity USD prototype with a simulator and a test-bench console. Passing its tests proves those tested controls and calculations. Real-user readiness also requires the new interface, authenticated identity, read permissions, domain gaps, operational recovery, approved accounting rules, and the acceptance gates below.

## Status and dependencies

**Checked** means verified in the current continuation record. **Designed** means a concrete proposal exists; implementation and acceptance remain open. **Open** means the required behavior has not been accepted. **Owner fact** means a named fact or source file is missing. **Owner decision** means the spec proposes a policy or scope that still needs agreement. These labels apply to the prototype or work item stated, not to the whole ERP.

| Area | Current status | Delivery implication |
|---|---|---|
| QuickBooks and prior Odoo catch-up | QuickBooks Online Advanced confirmed through read-only connected product metadata; prior Odoo work owner-confirmed, latest checkpoint not recovered in this checkout | Use [the adapter plan](QUICKBOOKS_ADAPTER_PLAN.md); qualify transport/realm/mappings and recover accepted Odoo work |
| Audit, approval lifecycle, ledger, AP/AR, procurement, labor, field, schedule, assets, close, and accountant hand-off | Checked prototype coverage; see verification record | Reuse the engine and tests, then accept each real workflow through its API and screens |
| Required governor loading; read-only grant preflight and atomic grant effects | Checked | Preserve startup failure and rollback behavior as new duties and APIs are added |
| Insurance/bond coverage at dispatch; depreciation chronology; audit lookup indexes; upgraded container and restart | Checked | Preserve these regressions; they do not qualify real payment or hosting integrations |
| Served Ricky read/draft restriction | Checked for the current HTTP adapter; authenticated session scope remains open | Carry the explicit allowlist and typed refusals into the new API |
| Separate bill business approval from posting | Implemented and verified: 1426 full-suite tests pass, including 65 lifecycle/duty/service/review cases | One journal-free business grant stays granted until an independent posting act consumes it. Schema 65 preserves historical records and adds audited grant history and immutable posting receipts; see [the split plan](BILL_POSTING_SPLIT_PLAN.md) |
| Fixed duties and person separation | Bill PM grant/independent posting, scoped accountant intake/match and exception duties implemented; match/correction reviewer differs from requester; approved withdrawal requires the original business approver | Global operation duties, authenticated API identity and Entra account binding remain open; no new approval thresholds or policy exceptions are adopted |
| Connected Fluent 2 practice read interface | Starter implemented; acceptance evidence in verification record | Fresh in-memory backend, allowlisted presenters and read-only screens; no live API, authentication or consequential actions |
| Connected Fluent AP preparation/intake interface | Installed-work preparation, owned evidence selection, receipt/matching, independent match review, PM business grant and accountant posting implemented in practice | PO/stored materials, claimed-versus-reviewed revisions, supplier credits, payments and real document storage remain open; see [AP_PRACTICE.md](AP_PRACTICE.md) |
| Connected Fluent AP exceptions/corrections | Invoice revision/rejection/duplicate review, draft cancellation, original-PM withdrawal and independently approved unpaid-bill reversal/separate replacement implemented and verified: 1867 full-suite tests pass, plus 30 Fluent views/3 journeys/27 retries/2 contract checks | Schema 69 preserves schemas 1–68 and original receipts; installed-work only, no payment-provider calls or external accounting acknowledgement; see [AP_EXCEPTIONS.md](AP_EXCEPTIONS.md) |
| Operational UI, authenticated sessions, replacement action API, live read permissions | Open | Required before real-user operation; the practice starter does not close these gates |
| Hold-aware expiry, governed labor corrections, aggregate split-spend policy, structural destination redaction, broader enforcing acceptance | Open | Assign to the milestones below; thresholds and windows need owner policy decisions |
| QuickBooks/BILL handoff, live Odoo integration, payroll compliance, multi-entity operation | Open in this prototype; existing external workflows are not evaluated here | Reuse and qualify the existing routes; current prototype coverage does not prove their integration |

Every schema change uses a new named entry. Preserve existing schema text and stored codes, and keep `service.PLUGIN_MODULES` in its existing order. New governed actions go through the approval/manifest contract. Changes begin with a failing acceptance or regression test; required checks and the full suite precede a commit.

## Milestones people can use

The order below follows usable workflows. It cuts across the spec's original phases: purchasing must work in practice before the pilot, and actual bank transfers stay behind their own qualification gate.

For every milestone, inspect the accepted Odoo and QuickBooks workflows before choosing configuration, integration or new Cipher code. Operational masters keep their agreed owner. Cipher journals remain working/shadow records; they are not proof of a posting in QuickBooks. An exported file is not an acknowledgement of a successful posting or payment. Map and test the established BILL route before changing payment behavior.

### M1. Practice purchase-to-pay

**Outcome:** a bookkeeper and PM can work through a synthetic purchase, receipt or subcontract pay app, business approval, posting, and simulated settlement in the new interface.

**Build:** the approval/posting split and fixed server-side duties; immutable practice mode; typed API actions, presenters, preflight and idempotency; scoped reads; readable record numbers; pay app claimed/reviewed lines and revisions; reuse accepted Odoo PO/receipt behavior and add only missing Cipher controls, invoice matching and handoff mappings; the Fluent shell, role home pages, job, commitment/PO, invoice/pay app, approvals, Post approved bills, and history screens. Start with the subcontract/pay-app path while Odoo purchasing coverage and the external record mappings are checked. Design at 1440, 1024 and 390 pixels. A release is always a separate act, with the practice simulator visibly labeled.

**Depends on:** owner mockup review and package decision for the production web stack; decisions on approval limits, exceptions, holds and expiry before those policies are finalized. Proposed policies can be exercised in clearly labeled practice scenarios. Final logo/color assets do not block engine or contract work.

**Accepted when:**

- Both a subcontract pay app and a quantity-PO supplier invoice complete the workflow through the new API and UI. Cases include stored materials and retainage, a partial receipt, a refused mismatch/duplicate, and a governed credit or correction.
- Approval creates no journal and moves no money. Only an authorized posting duty can post; the approver cannot post their own approval. Changed material facts require a new approval. Concurrent clicks and retries produce one record, journal and simulated transfer.
- The API derives identity and duties from its session or isolated practice identity service; body fields cannot choose them. Ricky cannot approve, post, release, sign, send, close, take over or co-sign.
- Every money total agrees with the domain calculation; approval facts and stale changes are understandable without program codes. Keyboard and screen-reader review pass on the review grid and approval page, with no serious or critical accessibility findings.
- On two years of synthetic data, the spec's targets are measured: reads below 2 seconds and actions below 3 seconds at the 95th percentile. Restored practice copies stay read-only and send nothing.

### M2. One-job pilot with shadow books

**Outcome:** the pilot PM and bookkeeper use the combined Odoo/Cipher workflow for every pay app and change on one job; QuickBooks keeps the official ledger and money moves through the established payment route.

**Build:** Entra sessions and many-accounts-to-one-person binding; enforcement and project-scoped read/write permissions; a live-safe deployment that cannot mount the old action API or practice routes; accountant-approved chart/posting rules and cost-code/type dimensions; governed budget and contract-value sources; vendor master and contact history; encrypted bank/tax data; documents with revision hashing, malware checks and framed previews; no-PO rental/trucking invoice routing, sales tax, credit notes and corrections; outside-payment recording and second-person confirmation; forecast approval and labor/equipment cost import; accountant package/download and omission checks. Add incoming documents, changes, forecast, payables, vendors, exceptions and controller-review screens. Complete the worker, structured destination redaction, history seal, backup high-water mark, restore takeover and recovery checklist.

Reuse the agreed Odoo customer/vendor/project/procurement masters with stable external references. Deliver the reviewed QuickBooks/BILL handoff with acknowledgement, duplicate prevention, reconciliation exceptions and omission checks alongside these screens.

**Depends on:** M1; the pilot job and participants; tenant/license and hosting facts; controller accounting files/sign-off; decisions 3–9, 11, 13–15 and 17 in the spec. Owner policy recommendations remain proposals until agreed.

**Accepted when:**

- At least 20 representative bills or a full billing cycle run on the agreed pilot job, with every source, adjustment, approval, posting and outside payment traceable. The accountant package has zero omissions, and a recorded baseline supports any claim of faster approvals or a better forecast.
- Odoo source references, Cipher approval/posting receipts and QuickBooks/BILL acknowledgements reconcile by record and total. Retries create no duplicate master, invoice or payment; conflicts and unresolved outcomes remain visible. The recovered Odoo catch-up checkpoint and new pilot acceptance are recorded separately.
- Nobody can record the same payment twice. Outside ACH recording refuses an unverified destination, and a second person confirms each outside payment. Cipher visibly identifies its ledger as the working ledger.
- Forged identity/role fields, cross-project reads and a person's second Entra account cannot bypass authority or separation. The live build fails startup if enforcement or required controls are absent.
- A restore drill covers a new path and rollback into the old path, catches the older audit head, requires controlled takeover and reconciliation, and sends no payment or email while quarantined. Practice email goes only to test destinations. Sensitive values are absent from plaintext manifests, replicas and exports; a keyed external history seal detects a rewritten and rehashed local chain.

### M3. Owner billing, receivables and a full close

**Outcome:** the team prepares owner billing and records receipts through the agreed system owners, reconciles the handoff to QuickBooks, and completes a monthly close alongside the accountant.

**Build:** the missing construction billing and reconciliation behavior after checking Odoo and QuickBooks coverage: one governed prime-contract value and owner SOV; lump-sum/unit-price billing; required AIA/EJCDC forms; separately approved document sends; receipts, fees, returns, deposits and retainage; statement imports and bank reconciliation; journal reads, governed working-ledger entries, reversals and accruals; WIP and close checklist; lien waivers and requirement severity. Add receivables, billing, bank, ledger, payments/holds and close screens. Official entries remain in QuickBooks through the agreed route. Exercise release runs, step-up, co-signatures, split-spend aggregation and hold-aware expiry on the simulator; any new live payment adapter has a separate qualification gate.

**Depends on:** M2; owner/customer form requirements; controller WIP and posting policies; decisions 7, 8, 16 and 17. Aggregate-spend thresholds and the grouping period require explicit policy terms.

**Accepted when:** a full parallel monthly close agrees with the accountant's AP, AR, retainage, stored materials, bank, deposits, payroll accruals, clearing, WIP and job-cost tie-outs; the client's required billing forms are correct; fees and late returns reconcile; close/reopen/correction paths remain governed; every payment hold is visible before release; simulator release, timeout, replay, return and restore-adoption cases complete without duplicate transfers.

### M4. Labor, field and project delivery

**Outcome:** crews and superintendents capture work in the field, PMs use quantities and time for cost/change decisions, and payroll information reaches the agreed payroll process.

**Build:** governed timesheet and posted-payroll corrections with reconciled accruals and rebilling; crew/classification and effective wage data; prevailing-wage/certified-payroll reporting; field duties; daily reports, installed quantities, T&M tickets, RFIs/submittals and photo revisions; calendar schedule and lookahead; equipment job charges; offline queue and resumable uploads. Extend enforcing-identity acceptance across labor, field, drawings, schedule and reimbursements. Decide which payroll calculations/filings remain with a provider before promising native payroll.

**Depends on:** M1 action idempotency and M2 identity/documents; the payroll export format, pilot field workflow, applicable wage determinations and certified-payroll requirements; decision 18. Field work can proceed in parallel after those foundations are accepted.

**Accepted when:** a representative crew week produces reconciled job cost and the required reviewed certified-payroll output; correcting approved time or posted payroll restores all affected subledgers and permits only valid rebilling; field entries survive loss of signal and retries without duplication; scoped identities complete the labor/field/drawings/schedule/reimbursement acceptance walk; reports and changed drawings remain traceable to revisions.

### M5. An operable hybrid platform; optional finance cutover

**Outcome:** the Odoo/Cipher/QuickBooks workflow operates under an agreed support and recovery model. QuickBooks stays authoritative unless the owner and accountant separately decide to replace it.

**Build:** qualify the Odoo and QuickBooks/BILL routes for concurrency, retries, outages and reconciliation; production secrets, backups, monitoring, incident ownership and deployment recovery; qualify the selected Cipher database/runtime for concurrency and scale; real step-up and co-sign flows wherever the agreed payment route requires them; stop-payment authority, unknown outcomes, returns and recovery reconciliation. A new payment-provider adapter or banking connection is added only if selected and after its data and security contracts are accepted. If a finance cutover is requested, evaluate the target against the accounting gates, reconcile migration/opening balances and fixed-asset acquisitions from AP without double-counting cost or cash. The historical native/ERPNext comparison is a possible later evaluation, not a reason to restart the established Odoo architecture.

**Depends on:** M2 and M3 financial acceptance; M4 wherever labor/payroll feeds the ledger; controller-approved policies, tenant controls and operating responsibilities. Any changed provider or accounting authority requires its own owner/accountant decision. The native core passes its prototype gates; those gates did not evaluate the existing Odoo tenant or prove its catch-up state.

**Accepted when:** three parallel closes agree with QuickBooks; the selected integrations and platform pass their applicable test/gate suite, concurrency checks, independent security review and restore/reconciliation tests. Payment-route qualification includes duplicate callbacks, timeouts, unknown outcomes, late returns and restored-history adoption with one transfer per authorized release. A rehearsed recovery plan and named operator are in place. Only if a cutover is selected: migration/opening balances reconcile, rollback is rehearsed, and the controller signs off official posting rules and cutover before accounting authority moves.

### M6. Complete the internal scope and qualify enterprise expansion

**Outcome:** all required commercial/estimating/takeoff, CMS and engineering/library workflows in [the product goal](PRODUCT_GOAL.md) work end to end under the same identity, evidence, audit and financial controls. Advanced expansion is qualified separately.

**Required:** proposal scope/pricing/revisions and award handoff; revision-linked takeoffs, quantities/units, assemblies/rates/quotes and accepted estimates; complete project/CMS work; checked engineering jobs/deliverables and transmittals; searchable versioned specifications and contract templates/clauses with rights and project adoption. Build these as parallel tracks after their identity/document/domain foundations, not as optional features waiting for an accounting cutover.

**Candidates to scope:** multi-entity/intercompany/consolidation; inventory and warehouse flows; equipment ownership/maintenance; estimating and bid hand-off; licensed cost content and CAD automation; customer/supplier portals; expanded HR/payroll integrations; cash planning and management reporting; Ricky with a language model reading and drafting through the same scoped API. Some are beyond the supplied UI spec and require workflow discovery before implementation tickets.

Check the existing Odoo apps and workflows first, then ticket configuration, integration or a Cipher extension for each actual gap. These candidates are not a mandate to rebuild general ERP modules already supplied by Odoo.

**Depends on:** the relevant earlier milestones and owner confirmation of entities, inventory practices, external systems, required reports and priorities. Complete ERP means the agreed business workflows are supported; it is not a claim that every candidate above is already required or built.

**Accepted when:** each agreed workflow has an owner, source/master-data rules, permissions, a usable screen/API, reconciled financial effects where applicable, migration/support ownership, and a representative acceptance walk including failure and retry cases. Licensed content and external integrations have their own access and retention decisions. Ricky remains read/draft-only in the served application.

## Immediate build queue

Each row should become one reviewable change or a short sequence with the same acceptance test. These are the first 15 work items, not an estimate of the entire ERP. Dependencies allow UI design and engine work to proceed together.

| ID | Work item and bounded acceptance | Dependencies / current state |
|---|---|---|
| B01 | One `bill.approve` grant records a journal-free approved state; separate `post_bill`/`bill.post` consumes that same authorization. Schema 65 adds immutable period/journal/person/reason receipts and complete audited grant history. The original authorized approver may withdraw an unposted bill, retaining history and restoring reservations. Altered source facts, extended expiry and false legacy records fail closed; exact retries replay once. | Implemented and verified: full suite 1426/1426; core gates 9/9, hard checks 127/127; console 20/20; Fluent actual API 18 views + 7 checks. See [the split record](BILL_POSTING_SPLIT_PLAN.md) |
| B02 | Fix grant, posting and payment duties per operation and enforce person separation. Bill PM approval and independent accountant/controller posting are implemented; owner role cannot waive separation. Carry served Ricky refusals forward. | Bill duties implemented. Global duties, payment separation, authenticated identity and Entra account binding remain open; decisions 3, 4 and 6 still govern policy exceptions |
| B03 | Immutable audited practice mode and startup/route/provider guards. Unknown or valid live files refuse before writable initialization; practice cannot be promoted. Known pre-mode copies defer declaration until an attested standalone claim; diagnostic opens preserve quarantine. Only initialized registered simulators and matching callback secrets are admitted. | Implemented and verified as schema 66: full suite 1471/1471 including 45 new cases; console 20/20; Fluent API 18 views + 7 checks; gates 9/9, checks 127/127. Live admission remains unavailable until identity/integration qualification |
| B04 | Define the first API/read contracts for jobs, commitments, pay apps, approvals and posting queues, including system ownership and stable Odoo/QuickBooks references. Include readable numbers, scoped paging/filtering, integer-cent totals, record version tags and typed actions/errors. Contract tests compare totals and permissions to domain truth. | Scoped AP practice contracts implemented: exact cents, source-backed preparation/invoice/evidence/match and exception/correction reads, signed cursors/versions and 17 fixed typed actions. Production OpenAPI, staff identity, external mappings and document numbers remain open |
| B05 | Implement presenters and side-effect-free preflight for the first approval/post actions, with a grant-time fingerprint check. Unsupported presenters fail closed; preview never creates audit, journal, provider or outbox effects; stale facts show what changed. | Original AP reviews plus invoice exceptions, withdrawal and correction reviews implemented with shared pure source/duty checks and fingerprints. Correction preview binds exact reversal journals and eligible periods; audited birth inventories, lifecycle, derived invoice terms and typed source plans fail closed. Unapproved stored-material presenters and broader operations remain open |
| B06 | Add operation-specific decide/apply expiry and hold-aware release windows. Test policy and approval clocks together; queues show decide-by/expiry; deployment cannot silently stale every open approval. | Decisions 5 and 16; new schema entries; no production thresholds assumed |
| B07 | Add pay app number/revision, claimed vs approved lines and reviewer reasons. Bind billed lines and caps; unrelated added SOV lines do not stale a prior app, changed billed lines do. Allow next intake after approval but before posting. | B01; decisions 3 and 7; new schema entries |
| B08 | Build clickable Fluent mockups: shell, PM home, job, subcontract, review grid and approval page at three widths. Exercise ordinary, stale, refused and restored-copy states with practice data. | Read-only starter and separate AP preparation/intake/match/request/approval/posting screens connected to genuine practice backends at three widths. Exception and correction screens use the same templates. Full claimed/reviewed grid, restored-copy product flow and owner visual acceptance remain open; Fluent needs no sign-in |
| B09 | Implement the first new API slice with server-controlled practice identities, scoped reads, CSRF/session handling and repeatable create/request/post actions. Repeated requests replay the original result; the old generic action API is not used by the new UI. | Disposable installed-work AP slice implemented: the same registered accountant/reviewer/PM, scoped duties, opaque cookie/CSRF, typed bounded inputs and atomic audited 17-action receipts. Schema 69 preserves schemas 1–68, original receipt contents and copied-workspace quarantine. Document upload, PO/stored-material exceptions, payments and operational identity remain open |
| B10 | Integrate Entra sign-in and canonical-person binding. Tokens stay server-side; two accounts for one person share separation rules; request bodies cannot choose actor/duties; live startup requires enforcement. | B02, B03, B09; tenant/app-registration owner and license fact (decision 10); does not block B08 |
| B11 | Connect the accepted home/job/pay-app/approval/post screens to the new API. Complete the first subcontract-to-simulated-payment journey and accessibility checks; each step states whether it approves, posts or releases. | Original installed-work journey plus invoice revision/rejection/duplicate review, unposted withdrawal and independently approved working reversal→separate fresh replacement/match/PM grant/post implemented, with visible consequences and exact retries. Claimed-versus-reviewed revisions, PO/stored-material paths, supplier credits, payment, final owner acceptance and manual screen-reader checks remain open; B10 before real-user use |
| B12 | Reuse Odoo quantity/unit-price PO and receipt behavior where already accepted; add only the missing Cipher control or integration. Remaining quantities and amounts reconcile after multiple receipts; revision/duplicate receipts are handled deliberately. | Recovered Odoo checkpoint and record ownership; M1 purchasing model; governed PO actions and cost coding |
| B13 | Carry a matched quantity-PO invoice through the agreed Odoo/Cipher/QuickBooks route exactly once. Test quantity/amount variance, duplicate external/source IDs and approved tolerance; a failed match creates no payable. Queue the no-PO rental/trucking path as a follow-on. | B12, B01; agreed writer/handoff mapping; decision 9; no automatic approval until its policy is agreed |
| B14 | Record and independently confirm payments from the established BILL/QuickBooks route. Cipher's working AP/cash agrees with official records, duplicate recording is refused, unverified ACH destinations fail, and pending confirmations appear in the accountant omission report. | B01, B02; current route mapping, reviewed posting rules and verified vendor model before M2; live access is a separate dependency |
| B15 | Turn M1 into an automated UI/API acceptance walk with enforcing duties: ordinary invoice, pay app revision, refused/stale approval, separate posting, simulated release, concurrent retry and restored copy. Keep all existing golden/corpus/control checks. | B01–B14 as relevant; complete before declaring M1 accepted |

## Owner facts and decisions to resolve at the right gate

The [18 decisions in the spec](UI_OVERHAUL_SPEC.md#a6-decisions-we-need-from-you) remain the source for proposed policies. Resolve dependencies before the affected behavior is accepted; keep independent engine, contract and practice-design work moving.

| Input | Type | Needed for |
|---|---|---|
| Exact lime value, logo files and mockup feedback | Owner facts/design decision 12 | Final visual theme and screen sign-off; placeholders support mockups now |
| Entra tenant/app-registration owner, canonical people and Microsoft 365 license tier | Owner facts, decision 10 | Real identity and stronger step-up controls; not Fluent components or mockups |
| Pilot job, PM/bookkeeper/controller participants and current process baseline | Owner facts, decision 15 | M2 pilot and measurable acceptance |
| Latest Odoo setup/import/reconciliation checkpoint and current QuickBooks/BILL mappings | Prior-work evidence to recover; QuickBooks use and earlier Odoo work already confirmed | Reuse accepted work, bind external IDs and settle writer ownership before overlapping integration changes; do not ask the owner to reselect their systems |
| QuickBooks chart, posting/WIP rules, cost-code/type master and payroll/export examples | Owner/controller facts and accounting decision 8 | M2 accurate job cost and M3/M5 finance acceptance |
| Approval limits, self-approval review, expiry, holds, match tolerance and aggregate-spend terms | Owner policy decisions 3–9 and 16 | B02, B06, B07, B13 and governed releases; spec recommendations are not adopted policy |
| Web packages, hosting, old-console removal and recovery process | Owner delivery decisions 2, 11, 13 and 14 | New web stack and M2 operational gate |
| Billing scope/forms, prevailing-wage requirements and advanced workflows; any proposed change of provider or accounting authority | Owner/customer/controller decisions 17–18 and later qualification | M3–M6; reuse current systems and split actual gaps into concrete tickets; cutover is optional |

At each milestone, update the verification record with the checks actually run, demonstrate the usable workflow, and retain the unfinished gate as open until its acceptance evidence exists.

The enterprise quality path in [PRODUCT_GOAL.md](PRODUCT_GOAL.md#enterprise-quality-path) records isolation, identity, integration, scale, audit, recovery and support qualification. Internal use supplies evidence for a later large-AEC evaluation; it does not establish suitability for Arcadis or any other prospective customer.

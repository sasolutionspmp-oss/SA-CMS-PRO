# Cipher delivery backlog

Updated October 14, 2026. This is the delivery sequence from the synthetic Cipher prototype to S&A's usable ERP workflow across Odoo, Cipher and QuickBooks. It turns [HANDOFF.md](../HANDOFF.md) and [UI_OVERHAUL_SPEC.md](UI_OVERHAUL_SPEC.md) into milestones and a first build queue. [BUILD_STATUS.md](../BUILD_STATUS.md) remains the prototype verification record; this document does not replace it or treat the spec's older percentages and time estimates as current evidence.

## Existing systems and prior work

The owner confirmed that QuickBooks is in use and that prior work has brought Odoo toward being fully caught up. The recovered September architecture assigns operations to Odoo, construction and engineering extensions to Cipher, and official accounting to QuickBooks until an agreed cutover. Continue from that work; do not treat these systems as a new selection exercise. The latest Odoo reconciliation checkpoint is not present in this checkout. That missing evidence does not mean the catch-up work did not happen, and Cipher's synthetic tests cannot establish Odoo's live state.

| System | Established responsibility | What the continuation must preserve |
|---|---|---|
| QuickBooks | Current accounting authority | Reconcile Cipher's working records to QuickBooks; no second writer or accounting cutover by default |
| Odoo | Planned operational source for customers, opportunities, projects and procurement; prior catch-up work confirmed by the owner | Recover the latest setup/reconciliation checkpoint and reuse existing records and workflows before building overlapping modules |
| Cipher | Construction and engineering extensions, commercial controls and the working interface | Add missing controls and screens; define which records it owns and which it reads from Odoo |
| BILL | Established payment route in the recovered architecture | Preserve it while its current handoff is mapped and tested; simulator qualification does not prove that route |

Before an overlapping module or integration is implemented, recover the existing Odoo work's version, installed apps, configuration/import artifacts and last reconciliation result from available project records. Record the owning system, stable external IDs, permitted writer and reconciliation rule for each customer, vendor, project, commitment, invoice and payment. List completed, accepted and unresolved items separately. Start with an isolated one-job export/mapping fixture, including duplicate, retry and changed-record cases; retain a checkpoint and exceptions. Credentials become a dependency when testing the actual tenant, not when designing controls, mappings or screens. This is evidence recovery and reuse, not a request to redo the catch-up work.

## What to build next

Implement the designed approval/posting split, then put a complete practice purchase-to-pay workflow behind a new API and clear screens. In parallel, recover the Odoo checkpoint and map the one-job Odoo/Cipher/QuickBooks handoff. Expand that workflow to one pilot job while QuickBooks remains the official books. Add missing billing, reconciliation, labor and field workflows after checking what Odoo already supplies. A future accounting replacement is a separate decision, not the default finish line.

Fluent UI is the screen component library. It needs no Microsoft account or sign-in. Mockups, components, contract mocks, and a local practice build can proceed with synthetic data and server-controlled practice identities. Microsoft Entra ID supplies verified identity for people using the application; tenant setup is required before a live pilot, not before designing the UI. Practice identity stubs must be excluded from any build that can reach live data.

The current engine covers many ERP functions, but it is a synthetic, single-entity USD prototype with a simulator and a test-bench console. Passing its tests proves those tested controls and calculations. Real-user readiness also requires the new interface, authenticated identity, read permissions, domain gaps, operational recovery, approved accounting rules, and the acceptance gates below.

## Status and dependencies

**Checked** means verified in the current continuation record. **Designed** means a concrete proposal exists; implementation and acceptance remain open. **Open** means the required behavior has not been accepted. **Owner fact** means a named fact or source file is missing. **Owner decision** means the spec proposes a policy or scope that still needs agreement. These labels apply to the prototype or work item stated, not to the whole ERP.

| Area | Current status | Delivery implication |
|---|---|---|
| QuickBooks and prior Odoo catch-up | QuickBooks use and prior Odoo work confirmed by the owner; latest Odoo checkpoint not verified in this checkout | Preserve the hybrid boundary; recover and reconcile prior work before duplicating operational modules |
| Audit, approval lifecycle, ledger, AP/AR, procurement, labor, field, schedule, assets, close, and accountant hand-off | Checked prototype coverage; see verification record | Reuse the engine and tests, then accept each real workflow through its API and screens |
| Required governor loading; read-only grant preflight and atomic grant effects | Checked | Preserve startup failure and rollback behavior as new duties and APIs are added |
| Insurance/bond coverage at dispatch; depreciation chronology; audit lookup indexes; upgraded container and restart | Checked | Preserve these regressions; they do not qualify real payment or hosting integrations |
| Served Ricky read/draft restriction | Checked for the current HTTP adapter; authenticated session scope remains open | Carry the explicit allowlist and typed refusals into the new API |
| Separate business approval from posting | Designed; next coding milestone | One business grant records approval without a journal; an independent human posts using that authorization. See [the split plan](BILL_POSTING_SPLIT_PLAN.md); the blocker remains open |
| Real UI, authenticated sessions, replacement action API, live read permissions | Open | Required before real-user operation; mockups and practice UI can proceed now |
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

### M6. Advanced ERP scope agreed for S&A

**Outcome:** the remaining company workflows work end to end under the same identity, evidence, audit and financial controls.

**Candidates to scope:** multi-entity/intercompany/consolidation; inventory and warehouse flows; equipment ownership/maintenance; estimating and bid hand-off; licensed cost content and CAD automation; customer/supplier portals; expanded HR/payroll integrations; cash planning and management reporting; Ricky with a language model reading and drafting through the same scoped API. Some are beyond the supplied UI spec and require workflow discovery before implementation tickets.

Check the existing Odoo apps and workflows first, then ticket configuration, integration or a Cipher extension for each actual gap. These candidates are not a mandate to rebuild general ERP modules already supplied by Odoo.

**Depends on:** the relevant earlier milestones and owner confirmation of entities, inventory practices, external systems, required reports and priorities. Complete ERP means the agreed business workflows are supported; it is not a claim that every candidate above is already required or built.

**Accepted when:** each agreed workflow has an owner, source/master-data rules, permissions, a usable screen/API, reconciled financial effects where applicable, migration/support ownership, and a representative acceptance walk including failure and retry cases. Licensed content and external integrations have their own access and retention decisions. Ricky remains read/draft-only in the served application.

## Immediate build queue

Each row should become one reviewable change or a short sequence with the same acceptance test. These are the first 15 work items, not an estimate of the entire ERP. Dependencies allow UI design and engine work to proceed together.

| ID | Work item and bounded acceptance | Dependencies / current state |
|---|---|---|
| B01 | Implement [the bill split](BILL_POSTING_SPLIT_PLAN.md): one `bill.approve` business grant records a journal-free approved state; a separate `post_bill`/`bill.post` human command consumes that authorization and records the exact period, journal and reason in an immutable posting receipt. No second posting approval is added. Preserve stored codes/history and refuse duplicate posting. | Designed; next coding milestone; implementation and targeted/full verification remain open |
| B02 | Split grant and execute duties, fixed per operation on the server. A PM can approve but cannot post; the approving person cannot post/pay their own approval; forged role fields fail. Carry the served Ricky refusals forward. | B01; policy exceptions need decisions 3, 4 and 6 |
| B03 | Add immutable audited practice/live workspace mode and startup/route guards. Copied workspaces keep their authority quarantine; practice providers/stubs cannot run against live data. | New named schema entry; can start alongside B01 |
| B04 | Define the first API/read contracts for jobs, commitments, pay apps, approvals and posting queues, including system ownership and stable Odoo/QuickBooks references. Include readable numbers, scoped paging/filtering, integer-cent totals, record version tags and typed actions/errors. Contract tests compare totals and permissions to domain truth. | Contract mocks can start now; implementation follows B01–B03; reconcile the Odoo checkpoint before overlapping writes; package decision 2 |
| B05 | Implement presenters and side-effect-free preflight for the first approval/post actions, with a grant-time fingerprint check. Unsupported presenters fail closed; preview never creates audit, journal, provider or outbox effects; stale facts show what changed. | B01, B04; preserve checked grant-preflight behavior |
| B06 | Add operation-specific decide/apply expiry and hold-aware release windows. Test policy and approval clocks together; queues show decide-by/expiry; deployment cannot silently stale every open approval. | Decisions 5 and 16; new schema entries; no production thresholds assumed |
| B07 | Add pay app number/revision, claimed vs approved lines and reviewer reasons. Bind billed lines and caps; unrelated added SOV lines do not stale a prior app, changed billed lines do. Allow next intake after approval but before posting. | B01; decisions 3 and 7; new schema entries |
| B08 | Build clickable Fluent mockups: shell, PM home, job, subcontract, review grid and approval page at three widths. Exercise ordinary, stale, refused and restored-copy states with practice data. | Can start now, no sign-in required; final brand files and owner mockup review are decision 12 |
| B09 | Implement the first new API slice with server-controlled practice identities, scoped reads, CSRF/session handling and repeatable create/request/post actions. Repeated requests replay the original result; the old generic action API is not used by the new UI. | B01–B05; package decision 2; practice-only build isolation |
| B10 | Integrate Entra sign-in and canonical-person binding. Tokens stay server-side; two accounts for one person share separation rules; request bodies cannot choose actor/duties; live startup requires enforcement. | B02, B03, B09; tenant/app-registration owner and license fact (decision 10); does not block B08 |
| B11 | Connect the accepted home/job/pay-app/approval/post screens to the new API. Complete the first subcontract-to-simulated-payment journey and accessibility checks; each step states whether it approves, posts or releases. | B07–B09 and mockup review; B10 before real-user pilot use |
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

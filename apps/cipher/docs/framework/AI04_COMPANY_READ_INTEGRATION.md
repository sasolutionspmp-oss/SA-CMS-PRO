# Company Ricky deterministic-read integration

Stage A Company read orchestration and embedded SAP UI5 source are implemented. The [native checkpoint](evidence/r1/company-ricky-native-r10/README.md) records 774 passing backend cases, eight native workflows, actual authenticated deterministic reads, ordinary RQ delivery, receipt/permission/session checks and final preservation. The [connected screenshots](evidence/r1/company-ricky-native-r10/ui/README.md) show the real isolated backend at desktop, tablet and phone widths.

The [corrected concurrency fixture](evidence/r1/company-ricky-native-r11/README.md) now has actual bounded fresh-transaction qualification: one winner and one native 1020 refusal followed by rollback, full ordinary reauthorization and no second lease. All 736 unit cases passed; the unchanged 52 integration cases produce a composed 788 backend total. The [R12 checkpoint](evidence/r1/company-ricky-native-r12/README.md) adds actual committed-checkpoint interruption, natural lease expiry, current-authority refusal and execution-quarantine/restoration proofs. Current composed backend coverage is 812 (760 fresh unit + 52 unchanged integration), with 190 fresh complete browser cases. Stage A remains incomplete; OS-kill, Redis-loss and restored-site recovery are not claimed. The [R13 prospective history checkpoint](evidence/r1/company-ricky-native-r13/README.md) adds canonical Start/Stop command events with actual owner/source filtering, source-free terminal Stop and replay qualification. R13 passes 782 fresh complete unit cases; 52 unchanged integration cases give 834 composed backend cases. Main deployment, a Company history interface, live model connectivity and Stages B/C remain separate. This source checkpoint is based on `7248171c14584deeaa308f850646ef5d7aeec891`; publication does not install it into the running main site.

The AEC contracts, tools and canonical readers implement deterministic reads. Nonpersistent draft values are not durable Proposed Changes. Generated-dependent inputs remain refused while `GENERATED_INPUTS_QUALIFIED` is false. No read invokes the local Ricky model or acquires domain-write authority.

## Implemented codec

`CompanyAuthority` is deliberately distinct from the existing Project `Authority`. Its `binding()` contains exactly:

```text
schema: cipher.ricky.authority.company.v1
scope_type: Company
project: null
user: original authenticated User name
person: original canonical Person name (native Frappe hash names are valid)
company: exact Company name
run_id: canonical UUID v4/v5
session_reference: original hashed session reference, not a bearer token
authority_version: exact authority fingerprint
selection_digest: digest of the original typed read request
```

Decoding checks structural integrity only. It performs no database query, verifies no live session, and grants no permission. A matching fingerprint cannot replace current identity, duty, native permission, or source authorization. It cannot establish that a caller is the stored User.

`DeterministicReadRequest` binds `cipher.ricky.company.read-request.v1`, exact Pursuit UUID, one fixed read action and its closed typed arguments, selected source references, and selected measurement UUIDs. Sources and measurements each retain the existing maximum of eight. Sources pin citation ID, exact revision/page, excerpt SHA, and original-byte SHA. These are selections; canonical readers must still verify all of them. A conversion from a measurement requires that measurement to be explicitly selected. Source/model text has no input field that can become a qualified numeric amount.

The four permitted actions are:

| Action | Arguments | Canonical behavior |
| --- | --- | --- |
| `aec.pursuit.lookup` | empty object | Read the selected same-Company Pursuit with current commercial rights. |
| `aec.estimate.recompute` | `revision_id` | Read the authorized stored revision/snapshot, run the pure calculator, compare exact original result and digests. No calculate mutation command. |
| `aec.estimate.compare` | `left_revision_id`, `right_revision_id` | Read both exact revisions; compare compatible currency and exact decimal values. |
| `aec.quantity.convert` | `source_kind`, `source_id`, `target_unit_id` | Resolve an authorized estimate line or selected measurement, then use exact rational same-dimension conversion and explicit quantity/waste basis. |

`model_standing()` explicitly returns `mode=deterministic-read-v1`, `model_invoked=false`, `live_model_qualified=false`. These are user-selected deterministic actions, with no inference claim. Manual measurements remain manual; calibrated geometry retains independent verification/current-use status. Original estimate snapshots do not acquire a later geometry provenance claim.

`decode_authority()` dispatches only the literal Company schema or the exact original Project Authority fields. Project decoding returns the original class, with its original optional session value and opaque Project version strings. It inserts no scope keys into historical JSON. Pure/fake-store tests use the existing FixtureBackend authority and FixtureStore/RickyService run to check identical bytes/body hashes; the authority's golden SHA is `ffe116fff7996674d7ad92b159697fe28057b3eaab6a7396f5a0d5706032aea8`.

`decode_run_authority()` checks run headers against the original binding. Company runs require the exact run UUID, User, Person, Company/null Project, original session reference, deterministic request kind and selection digest. A new login, alias, edited selection or another run cannot be substituted merely by changing a header. This is a codec check, not proof that an actual stored run or session exists.

## Stage A: durable read-only runs and bounded native qualification

The source uses the existing Ricky orchestration engine, lease/cancellation/recovery behavior and six orchestration DocTypes. `CompanyReadService`, `CompanyBackend`, the persisted-run reader and `CompanyStore` specialize this boundary; they do not introduce another engine, artifact authority or free-form planner. The implemented source includes:

1. Backend-owned Company `ricky.run`, Company command/receipt authorization and explicit fail-closed API catalog/schema entries. Company `estimate.read` or `commercial.read`, or an aggregate Project capability, cannot imply Company orchestration permission. Company history access dispatch is prepared, but no canonical Company Ricky history-event producer exists; there is no genuine run-history coverage claim.
2. Additive scope metadata on `Cipher Ricky Run`, `Cipher Ricky Step`, `Cipher Tool Invocation`, `Cipher Run Artifact`, `Cipher Proposed Change`, and `Cipher Delegation`: literal scope type defaulting to Project, nullable Project and exclusive validation. Project requires a real same-Company Project; Company requires null Project. No null-Project inference is permitted. The isolated additive migration/preservation check passed for 40 actual preexisting Project rows across all six tables, with the source catalog unchanged. This result does not replace exact runtime receipt/read proofs.
3. Scope, original User/Person/authority and parent-linkage guards in record/storage/hooks code. Company children retain their exact parent run ID; the parent's original authority run ID must agree. A Company delegation, step, invocation or artifact cannot link to another Company or a Project run. Ordinary resource writes remain protected, and a Stage A Company run produces no Proposed Change.
4. The separately registered `cipher_aec.ricky.company_api` methods below. The server supplies authenticated actor/session, authority fingerprint, limits, registry and request kind. Clients cannot submit authority, a registry, model configuration or arbitrary method names. Actual Company cookie/CSRF transport and stored read execution passed in the isolated fixture.
5. A fixed read registry containing exactly the four actions above, one explicit action per request. Durable Run/Step/Invocation/Delegation/Artifact storage and deterministic worker dispatch are implemented in source. The actual isolated fixture persisted and executed the four selected reads; their retained standing is no-model.
6. Literal scope/request-kind dispatch in the existing service factory, API and worker before model-adapter resolution or default Project registry construction. Recovery must not resolve a model just to locate deterministic work. The persisted-run `RunAECReader` checks the original actor/session/current Company authority before passing a verified actor into canonical readers. Worker user switching must execute as that original User, restore worker identity in `finally`, and never inherit Administrator rights. The interactive reader continues to check the actual current actor.
7. Original typed selection, hashed session reference and selection digest binding across run/delegation. Every tool access and consequential resume must recheck the original session, current User/Person mapping, Company duties, native permissions, selected Pursuit scope and exact source access. Fingerprint equality supplements those checks. An expired original session cannot be replaced by a new login or reconstructed session.

| Company method | HTTP method | Typed request | Response boundary |
| --- | --- | --- | --- |
| `start_read(company, request, operation_id)` | POST | `CompanyRickyStartReadRequest` | Exact immutable queued admission plus canonical operation receipt. |
| `get_run(company, run_id)` | GET | `CompanyRickyGetRunRequest` | Authorized original selection and original tool observation. |
| `run_events(company, run_id)` | GET | `CompanyRickyRunEventsRequest` | Authorized same-run deterministic Step inventory; not a Company history register. |
| `cancel_run(company, run_id, operation_id)` | POST | `CompanyRickyCancelRunRequest` | Narrow source-free terminal Stop receipt. |

Admission uses the canonical Company lock/receipt boundary and Person budgets. The request hash binds the authenticated original scope/selection and operation UUID. The durable run UUID is created only after an authorized receipt miss and is retained exactly once in the original authority and parent rows. Receipt replay returns the original queued admission even after execution has become terminal; a terminal source-bearing result cannot substitute for admission. Recovery retains lease tokens, deadlines, cancellation, tool savepoint rollback, quarantine and successful-step linkage. An ordinary isolated RQ burst completed one new target with one invocation and consumed 11 older hints without changing their run payloads or invocation counts. Simultaneous fresh-transaction claim qualification passed in the separate R11 fixture.

An original result exposes only its selected result/source dependencies under current access. A later private or unselected binding must not enter a completed result's authorization requirements. Fresh/current-use draft checks belong to later stages; pinned historical read results do not silently follow newer working heads.

Canonical readers remain the authority for Company scope, native UOM/Currency/party rights, exact source hashes, full producer dependency unions and bytes. The persisted-run citation reader uses `documents.service.get_company_citation(company, revision_id, page, excerpt_sha256, actor=verified_actor)`, then compares the exact selected scope, locator, original-byte SHA, excerpt SHA and canonical ID. It retains the canonical Company citation `id` unchanged as `SourceReference.citation_id`: the SHA of the canonical JSON array `[revision_id, page, excerpt_sha256]`. The Project backend's dictionary-based citation ID is not substituted. `search_company_documents` is a separate user-selection flow outside the four read actions. Raw-only admission still checks generated dependencies and performs the canonical source read. Discovery or codec success cannot replace original-source authorization. No CAD/OCR/model geometry service is introduced.

## Embedded UI and generated contracts

One embedded Ricky panel selects literal Company scope or the existing Project panel. Company mode offers only the four deterministic actions, explicit Pursuit/source/revision/measurement selection, truthful no-model standing, original result details and a separate Stop action. It has no Company-to-Project/model fallback, proposal review or domain-save action.

The last confirmed run pointer is keyed by exact original User + canonical Person + Company. It is a browser-session pointer, not a server run register or durable recovery journal. In the mounted view, an uncertain Start or Stop retains the original operation UUID and payload for recovery. Start accepts only the exact queued admission. The first fully validated terminal Run observation pins status, completion, result/digest, error and cancellation flag; later substitutions fail closed. A narrow Stop cannot establish that full observation. Unknown Stop recovery remains reachable independently of a later terminal full read. Mounted expectations and uncertain-operation recovery do not survive a remount; a reopened pointer requires fresh server authorization.

The UI integration adds the Company Ricky client/schema output, runtime validation, embedded view and necessary Company takeoff generated types. All 11 generated clients, typechecking and four offline API/catalog/OpenAPI mappings passed. Existing main SVG/notices, their static-asset contract test and normal Vite configuration were preserved. The browser-test-only integration delta sends the three responsive screenshots to `testInfo.outputPath(...)`; it leaves original draft evidence unchanged.

## Original read/UI checkpoint

| Evidence | Result | Practical limit |
| --- | --- | --- |
| Backend unit/integration | 774 passed, no failures/errors/skips | 722 unit + 52 integration; exact frozen R9 backend. |
| Native workflow procedures | Eight passed | Existing product workflow acceptance, separate from Company HTTP fixture. |
| Additive migration | 40 existing Project rows preserved across six tables | Isolated site only; no main migration. |
| Company HTTP/native reads | Lookup, recompute, compare and corrected conversion passed | Original failed conversion stays failed; corrected request has its own declared operation. |
| Authority and receipts | Original-session expiry, alias/outsider denial, source/capability revocation and fencing passed; eight exact receipt cases and 18 projection pairs passed | Source-free Stop is separate from result access; original duties restored. |
| Ordinary RQ delivery | 12 jobs finished; target had exactly one invocation; 11 older results unchanged | Own short queue only; worker exited; scheduler and other queues untouched. |
| Connected UI | 13 actual screenshots; 19 API GETs; no browser/resource errors or writes | Synthetic records, original session, no model invocation. |
| Frontend suite | Complete confirmation passed all 190 cases, with no failures/skips/retries; 11 generated clients and build passed | First full 190 run had one checkbox-action failure; unchanged targeted retry and complete confirmation passed; original failure retained. |
| Direct concurrent claim fixture | Corrected R11 passed: one claim, one observed 1020 rollback/retry, no second lease | Two original failed cases remain unchanged; separate declared request and final Stop preserved. |
| Final preservation | Original business/config rows, duties, identities and Company Project set preserved | Readback only; no production-readiness claim. |

The [native report](evidence/r1/company-ricky-native-r10/native-qualification.json), [source catalog](evidence/r1/company-ricky-native-r10/source-snapshot.json), [backend report](evidence/r1/company-ricky-native-r10/backend-qualification.json) and [UI evidence](evidence/r1/company-ricky-native-r10/ui/README.md) bind the exact results. Earlier source-only reviews and failed execution phases retain their original status and hashes.

Native testing found two corrected implementation defects: Frappe validates Run Links before insert, so exact initial Run admission now precedes child Delegation creation and fills the optional self-Link through a supported save; conversion source verification now keeps the canonical estimate-line/parent closure without sending a line to the revision/snapshot citation collector. Neither correction disables native Link validation, authorization or generated-input refusal. The responsive estimate title now uses official `ToolbarButton` children so SAP's toolbar can move actions into its overflow menu.

## Stage B: persisted reviewable proposals (deferred design only)

Add the two reviewed draft contracts to a separately reviewed registry only after Company read runs qualify. Store the result in the existing `Cipher Proposed Change`, with a literal action kind/schema, typed proposed fields, exact source and domain-record manifests, version/digest, expiry and successful run/step/invocation linkage. Current nonpersistent draft values must not be relabeled as stored proposals or assigned fictional IDs/status. No writer is needed to provide a legitimate review screen at this stage.

## Stage C: human draft-save commands (deferred design only)

Use a static typed dispatcher: a scope draft may call the canonical commercial proposal-revision save command; an estimate draft may call the canonical estimate-revision calculation command. This is a new explicit human command, requiring current domain write permission. Read/delegation permission does not confer it. No tool may accept a baseline, verify calibration, issue/distribute a proposal, award a project, post finance, or create native masters.

Add internal-only guards to those canonical command services; never accept callbacks through RPC. Under canonical Person/Company/domain locks, check the original run's User/Person/session, current Company `ricky.run` and domain write rights, authority fingerprint, cancellation/fencing/expiry, successful preparation linkage and exact target revision. Preserve consistent Run/Proposal lock order. Then discover the complete own/generated source union before sorted UOM, Currency and global native-reference locks. Reauthorize the exact canonical quantity/citation/record dependencies under that complete union immediately before the draft effect; no new UOM lock after Currency/native locks.

Construct final saved fields from authorized source references and deterministic quantities. Unverified model/authored suggestions remain labeled text; a proposed numeric amount cannot be promoted to measured or accepted fact. Preserve the explicit net-versus-after-waste policy and reject double waste. Save the canonical revision, immutable command receipt, proposal-applied linkage and history atomically. Receipt replay authorizes the original saved sources; new effects must still recheck current heads/rights under locks. Acceptance remains a separate independent-human approval action.

## Remaining qualification

The native concurrent-claim correction is qualified and both original failed attempts remain unchanged. The three bounded R12 recovery/quarantine cases now passed; preserve their scope separately from OS-kill, Redis-loss or restored-site qualification. R13 now supplies prospective canonical Company command history and actual native evidence. Prepare the separately scoped Stage B contracts next; broader crash/restore and operational qualification remain distinct. The actual cookie/CSRF, deterministic result, session expiry, native projection, receipt-byte and ordinary queued-delivery proofs listed above have passed and must not be relabeled as pending or repeated without cause.

New Start/Stop commands now produce canonical Company history events through the existing Company history API; replay creates none, and original User/Person/current source/native authorization still filters items, totals and cursors. There is no history backfill or worker lifecycle producer. `run_events` still returns only authorized Steps. A Company activity interface remains to build. The local model adapter is not connected. Main release needs its own supported backup, additive migration and source/asset deployment checks. Stage B/C cannot inherit write authority from the read registry.

Stages B/C additionally require proposal linkage/integrity, explicit human write authorization, fresh source/target guards inside canonical locks, concurrent revocation/cancellation/staleness refusal, no duplicate business effect under crash/retry, and historical receipt readability after unrelated working changes. Neither source tests, synthetic UI contracts nor additive migration preservation establish these runtime properties. Nonpersistent draft contracts cannot be relabeled as persisted proposals. Baseline acceptance, calibration verification, issuance/distribution, awards, finance posting and native-master creation remain outside this integration.

Runtime slots, isolated identity provisioning, migration/HUP and queue-consumer attestation remain root-coordinated. This document supplies no credentials, model/provider endpoints or runtime-release authorization. The latest owner preference is GPT-6.1 Sol Ultra for agent work; historical Astra review assignments are superseded.

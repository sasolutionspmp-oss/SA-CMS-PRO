# Company Ricky saved suggestions — Stage B

Stage B now provides deterministic, persisted scope and estimate suggestions in the existing SAP UI5 Company assistant. Isolated R14 native qualification passed for three stored suggestions and one request cancelled before persistence. Final reconciliation and [nine connected screens](evidence/r1/company-ricky-native-r14/ui/README.md) passed. This extends [Stage A](AI04_COMPANY_READ_INTEGRATION.md); it does not deploy the candidate to main.

The original Stage B suggestion requires human review and does not itself save a commercial/estimate revision, accept a baseline or grant approval. [Stage C reviewed draft saves](AI04_COMPANY_DRAFT_SAVES.md) subsequently qualified the separate explicit human save command. The local Ricky model and QuickBooks remain unconnected; deterministic qualification does not establish those connections.

## Implemented boundary

The separate proposal registry permits only `aec.scope.draft` and `aec.estimate.draft`, version `1`. Existing Company reads and Project behavior retain their contracts. One new Run binds request kind `deterministic-proposal-v1`, request schema `cipher.ricky.company.proposal-request.v1`, selected Pursuit, action arguments and exact source/measurement references. No model, registry, limits or authority override is accepted.

The existing six orchestration DocTypes remain authoritative. Start atomically persists Run/Delegation linkage, canonical accepted history and the immutable queued receipt; dispatch is postcommit. Ordinary execution commits its successful Step/Invocation preparation checkpoint. Fresh guarded finalization atomically inserts one immutable `Cipher Proposed Change` and terminal `waiting-for-review` Run. The original draft output, including `persistent:false`, remains unchanged inside the genuinely persisted wrapper (`cipher.ricky.company.proposal.v1`). This wrapper is distinct from a canonical commercial `Cipher Proposal`.

Complete commercial/estimate/takeoff/native discovery precedes sorted UOM, Currency and native-reference locks. Actual canonical citation fields and exact dependency sets are verified before output acceptance and finalization. Quantities, units, provenance and net/after-waste basis reconcile against authorized original records through existing rational helpers. Generated-dependent inputs remain refused. No browser/model number becomes a measured fact.

Execution/finalization checks original User/Person/session, current Company/domain/source/native rights, delegation, deadline, lease token, cancellation and exact selected head/resource plan. Recovery reuses the committed successful Invocation and Step. It cannot silently choose successor inputs. Failed finalization leaves no orphan proposal/terminal pair.

Worker wall authority and human review expiry have separate meanings. Existing policy retains a 300-second wall deadline and 180-second lease; suggestion expiry follows that existing deadline. No extended worker or review TTL was introduced. Authorized historical review survives expiry and later working heads, without claiming current eligibility for Stage C.

## API, receipts and privacy

The new module is `cipher_aec.ricky.company_proposal_api`, with closed schema `cipher.ricky.company-proposal-api.v1`:

| Method | HTTP | Boundary |
| --- | --- | --- |
| `start_proposal` | POST | Exact queued admission and original operation receipt. |
| `get_run` | GET | Authorized original selection, Run and result reference. |
| `run_events` | GET | Authorized same-Run Step inventory. |
| `get_proposal` | GET | Immutable stored suggestion under current original-source rights. |
| `cancel_run` | POST | Narrow source-free Stop receipt. |

Full reads require the actual original User and Person plus current Company/domain/source/native access. A same-Person alias cannot acquire ownership. Historical reads verify retained originals without rerunning a fresh-head draft tool.

Stop before finalization cancels/fences the active request. Stop accepted on an already terminal Run preserves its payload and is not a cancellation claim. Its receipt cannot establish a full Run or grant source/history rights. Current rights filter history items, totals and cursors. The accepted events are `ricky.company.proposal.start.accepted` and `ricky.company.proposal.stop.accepted`; workers invent no lifecycle history. Replay preserves the original queued/Stop body and appends no event or queue hint.

A narrow native wire correction excludes Frappe's internal `_server_messages` decoration from the closed canonical response, including denials. DTOs/routes were not expanded. Existing Project/read compatibility remains covered.

## Official UI5 authoring and review

**Saved suggestions** is an explicit Company mode beside the unchanged four **Company reads**. Scope preparation uses authored sections, selected evidence and separately labeled unverified statements. Estimate preparation selects existing canonical lines or eligible saved measurements, original units and authored notes; the browser generates no quantities.

Authorized selectors use their actual paging contracts; citation search is bounded and followed by exact citation re-read. Parent changes clear dependent choices. Requests retain the selected working revision. Review shows readable fields, exact rational quantity strings/units, original source navigation, version and expiry standing, with optional integrity details. It states deterministic preparation, unverified author suggestion and review required. These R14 screens had no Apply, Accept or draft-save control; the separately qualified R15 Stage C adds explicit reviewed draft saves.

Pointers bind original User, Person and Company. Source denial removes source-bearing content. Unknown Start/Stop retains the mounted UUID/payload and locks mode return, close and fresh submission, including the shell toggle. Recovery validates the original admission/receipt; terminal observations cannot change across refresh. This is mounted-view recovery, not durable recovery of an unknown command across reload.

## Qualification

The frozen R14 snapshot has **679 source paths and 44 changed paths** against R13 commit `947bab33d19fd7bc6fb2bba9b223034c2bc6121c`.

| Check | Result and limit |
| --- | --- |
| Backend | 907 composed cases: 851 units + 56 integration. This is composed source qualification, not one new invocation of all 907 cases. |
| Native-helper source checks | 41 passed: 16 new continuation +25 existing helper tests, distinct from actual native execution. |
| Product generation/type/build | Passed on the exact composed source. |
| Playwright | 220 distinct cases qualified: 219 full-run passes plus the unchanged-source crash case passing separately. Original Chromium failure retained; not a fresh single 220/220 run. |
| Scope and estimate | Ordinary author HTTP/RQ each persisted one immutable linked suggestion; no worker history events. |
| Successor heads | New manually authored target revisions preserved original suggestions, historical reads and receipt bytes. |
| Finalization recovery | Actual post-insert savepoint rollback left no orphan; natural lease expiry and ordinary recovery/RQ reused the original successful Step/Invocation. Committed-checkpoint interruption, not OS-kill/Redis-loss. |
| Cancellation | Distinct Stop after preparation preserved the cancelled Run/preparation, inserted no suggestion and refused the old token. |
| Finish/reconciliation | Passed: three suggestions, one cancelled request, source outage/restoration, terminal Stop, alias/outsider privacy, mixed history/cursors and exact receipt replay. |
| Connected UI | Nine actual screens at 1440/900/390: scope selection, saved scope and saved estimate. 23 API GETs, 15 font HTTP 200 responses, no browser errors/blocked requests/business commands; existing authenticated cookies, no login/model call. |
| Independent preservation | Original business/configuration/cookies and duty semantics preserved with exact attributed setup, duty audit and bounded original-User heartbeat changes. Fourteen financial tables remained empty; three existing Projects unchanged; workers/queue empty. |

The source qualification report predates native execution and retains `native_scenarios_qualified:false`; subsequent native phase records establish those results. Earlier workflow/recovery reports retain their own source epochs. Connected screenshots are actual-backend evidence; mocked browser captures remain separate.

## Retained failures and next boundary

The first manual-commercial POST403 correctly refused missing native Account select permission and created no receipt/business target. Its failed journal/wire refusal remains unchanged. A separately reviewed select-only synthetic prerequisite and explicit continuation preserved the exact original operation UUID, payload, identities and copied cookies; the old failed phase was never reset or rerun.

Normal session maintenance was attributed, never undone: only the relevant original User's `last_active` may advance within independently observed request bounds. Other User fields, including `last_ip` and `modified`, remain strict. The fixture pins actual Session source and the stored SQL-NULL timezone/effective Asia/Kolkata fallback. Native-naive timestamp bytes stay unchanged; comparisons convert to UTC. Supported duty audit timestamps are also explicitly attributed; whole-row byte equality is not claimed for those exact changes.

A later wrapper called the success-only verifier on the cancelled case. It refused before phase entry, after the distinct cancellation verifier had passed; no product/native mutation occurred. That failed record remains preserved.

[Stage C explicit human draft-save](AI04_COMPANY_DRAFT_SAVES.md) is now qualified separately. The Company history interface, live model/QuickBooks qualification and broader operational recovery remain separate. Award execution/recovery, downstream finance and main deployment retain their own gates; this slice does not reconstruct or enable the blocked award driver.

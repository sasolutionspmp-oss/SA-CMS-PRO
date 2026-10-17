# Running Cipher build: implemented journeys

These screenshots were captured from the actual containerized SAP UI5/Horizon
client connected to the persistent ERPNext/Frappe development site. They show
synthetic business records. They are not generated images or design mockups.
The private development service listens at `http://127.0.0.1:18880` in the
execution environment; this address does not make it publicly reachable.

The latest [Company drawing takeoff gallery](evidence/r1/company-takeoff-r17/ui/README.md) shows the actual register, authorized stored PDF, reviewed manual entry and saved measurement at desktop, tablet and phone widths. It uses the real isolated backend and preserves the original OCR dependency failure separately from its successful corrected continuation.

The latest [Company saved-suggestion gallery](evidence/r1/company-ricky-native-r14/ui/README.md) shows actual scope selection, saved scope and saved estimate review at 1440, 900 and 390 pixels. These nine screens use the isolated backend and original authenticated cookies: 23 actual API GETs, 15 successful font responses, no browser errors/blocked requests/business commands and no login/model call. Root visually reviewed all nine. The [Stage B checkpoint](AI04_COMPANY_PROPOSALS.md) records the four native cases and preservation. R10 screenshots retain their original read-workspace source; mocked browser captures are separate. No human draft-save/apply or main deployment is claimed.

The earlier [Company read-workspace screenshots](evidence/r1/company-ricky-native-r10/ui/README.md) show actual Pursuits, a saved estimate, stored source text and the embedded deterministic Ricky selector at 1440, 900 and 390 pixels. They come from the separate Company integration site on ports5196/18886, with synthetic records and no mocked API responses. The corrected phone title and action overflow use official SAP UI5 components. These captures do not imply that this source has been deployed to the main site or that a model was invoked.

The latest [main-site capture](evidence/r1/cost-planning-main-ui-v4/README.md) shows the corrected deployed build at desktop, tablet and phone widths: Project register, original Project/Tasks and Ricky's current connection state. These nine screenshots passed normal keyboard sign-in, settled layout and exact served-asset checks on October 16, 2026.

An earlier isolated checkpoint adds [cost-code/type setup](evidence/r1/prj02-ui-connected/cost-setup-v2/README.md) and [saved award-plan review](evidence/r1/prj02-ui-connected/saved-plan-v2/README.md), with desktop, tablet and phone captures from the real backend. Its isolated site is retained; its disposable web container is stopped after full verification and the separate main UI deployment completed. Award execution is still disabled in the main product. The earlier journeys below retain their original capture dates and source versions.

| Step | What the running product does | Actual capture |
|---|---|---|
| 1. Sign in | Uses the site's real session and CSRF protection | [Sign-in screen](evidence/r0/browser/connected-sign-in.png) |
| 2. Open the project register | Lists projects accessible to the signed-in person | [Project register](evidence/r0/browser/connected-project-register.png) |
| 3. Enter a project | Shows the native Project, Tasks and project context inside the unified shell | [Project workspace](evidence/r0/browser/connected-project-object-page.png) |
| 4. Work with documents | Lists stored originals and immutable revisions with authorized source access | [Document register](evidence/r0/browser/connected-document-register.png), [source view](evidence/r0/browser/connected-document-source.png) |
| 5. Review a consequential change | A separate person reviews the bound Project-status approval | [Independent review](evidence/r0/approvals-browser/connected-approval-independent-review.png) |
| 6. Execute the approved change | The requester executes the unchanged approved packet; the captured journey restored the project to Open and preserved all 14 Tasks | [Executed approval](evidence/r0/approvals-browser/connected-approval-executed.png) |
| 7. Use a smaller screen | The same connected product adapts to tablet and phone widths | [Tablet](evidence/r0/browser/connected-project-register-tablet.png), [phone](evidence/r0/browser/connected-project-register-mobile.png) |

The real access check also verifies that a reviewer can use approvals while
document access is denied: [reviewer screen](evidence/r0/access-browser/connected-reviewer-access-state.png).
Ricky's panel currently reports the missing model connection accurately:
[current Ricky state](evidence/r0/browser/connected-ricky-unavailable.png).
The existing local model has not yet been connected or qualified in this site.

Each screenshot directory contains verification, artifact hashes and the exact
served bundle/source provenance. Earlier captures retain their original source
snapshot when later UI changes occur. Browser tests with explicit API fixtures
are recorded separately and do not replace these connected captures.

## Estimating in the running product

These captures use actual stored estimate records and the same live session/API.
The created estimate calculated to 279.23; a later revision calculated to 306.23.
The predecessor remains available for comparison.

| Step | What the running product does | Actual capture |
|---|---|---|
| 1. Open the estimate register | Lists accessible project estimates | [Estimate register](evidence/r1/estimating-draft-workspace/connected-estimate-register.png) |
| 2. Edit and calculate | Edits exact decimal quantities, units, rates and allowances; saves a new immutable calculation revision | [Desktop editor](evidence/r1/estimating-draft-workspace/connected-estimate-editor-desktop.png) |
| 3. Inspect provenance | Opens the stored rate, assembly and underlying document source | [Rate](evidence/r1/estimating-draft-workspace/connected-estimate-rate-source.png), [assembly](evidence/r1/estimating-draft-workspace/connected-estimate-assembly-source.png), [source page](evidence/r1/estimating-draft-workspace/connected-estimate-source-page.png) |
| 4. Compare revisions | Shows the saved predecessor beside the current revision | [Revision comparison](evidence/r1/estimating-draft-workspace/connected-estimate-revision-comparison.png) |
| 5. Inspect the calculation | Displays the saved calculation snapshot | [Snapshot](evidence/r1/estimating-draft-workspace/connected-estimate-snapshot.png) |
| 6. Work on a phone | Keeps Add/Paste controls usable and numeric editing focused | [Phone editor](evidence/r1/estimating-responsive-correction/connected-estimate-editor-phone.png), [numeric focus](evidence/r1/estimating-responsive-correction/connected-estimate-numeric-focus-phone.png) |

The normal estimating journey and responsive correction each retain their exact
served-source provenance. Browser fixture scenarios independently exercise
clipboard validation, stale-version recovery and error contracts.

A separate connected recovery journey deliberately interrupted delivery after
the real backend had created an estimate. The screen kept the original inputs
and request ID, retained them through an injected retry denial, and recovered
the same persisted estimate. Independent readback found exactly one matching
draft. Captures: [result unknown](evidence/r1/estimating-create-recovery-final/actual-create-result-unknown.png),
[retry denied while still unknown](evidence/r1/estimating-create-recovery-final/actual-create-still-unknown-after-injected-denial.png),
and [original operation recovered](evidence/r1/estimating-create-recovery-final/actual-create-original-operation-recovered.png).
The injected faults are explicitly recorded; actual permissions were unchanged.
This recovery is qualified while the view remains mounted, not across browser restarts.

## PDF takeoff in the running product

The connected Project journey uses actual authorized PDF bytes and pointer
coordinates in the local PDF.js viewer. A second person reviewed the scale;
the backend calculated 200 square feet, which was attached to an exact saved
estimate line. Replacing the drawing made the old measurement stale for new
use while preserving its saved quantity and the original estimate result.
The proof checks pointer picks within a one-point PDF-space bound, then enters
the known exact coordinates before calculating the 200-square-foot fixture.
It does not claim perfect pointer snapping.

| Step | Actual capture |
|---|---|
| Independently review the drawing scale | [Calibration review](evidence/r1/project-pdf-workspace/actual-independent-calibration-review.png) |
| Attach the measured quantity to a saved estimate line | [Measurement and binding](evidence/r1/project-pdf-workspace/actual-pdf-measurement-and-estimate-binding.png) |
| Inspect changed-drawing impact without repricing history | [Drawing change impact](evidence/r1/project-pdf-workspace/actual-drawing-change-impact-preserves-estimate.png) |
| Reopen the original drawing revision | [Historical drawing](evidence/r1/project-pdf-workspace/actual-historical-drawing-revision.png) |
| Use the same viewer at smaller widths | [Tablet](evidence/r1/project-pdf-workspace/actual-pdf-takeoff-tablet.png), [phone](evidence/r1/project-pdf-workspace/actual-pdf-takeoff-phone.png) |

The [verification record](evidence/r1/project-pdf-workspace/verification.json)
records all eleven mutation IDs and payload hashes, exact before/after results,
served assets and zero unexpected browser/network errors. Private raw requests
were journaled before sending. Prior blocked fixture/MIME attempts remain
separate. These captures precede the targeted density and source-label cleanup;
technical fixture names shown here are actual stored values.

A subsequent read-only pass improves the measurement summary and saved-line
selection, displays the saved rectangle, and prevents attaching a stale source
to a new line. It also corrects the navigation panel covering content when an
already mounted desktop view shrinks to phone width. These new captures show
the same persisted records: [desktop](evidence/r1/project-pdf-polish/actual-measurement-binding-desktop.png),
[tablet](evidence/r1/project-pdf-polish/actual-measurement-binding-tablet.png),
[phone](evidence/r1/project-pdf-polish/actual-measurement-binding-phone.png), and
[drawing impact](evidence/r1/project-pdf-polish/actual-readable-drawing-impact.png).
The [read-only verification](evidence/r1/project-pdf-polish/verification.json)
records no business writes and preserves the actual stored unit labels. Its
served UI sources are bound separately; it does not repeat the original mutation
proof or claim that all backend sources were frozen during this later capture.

## Company commercial work and accepted estimates

This connected journey stays in Company scope before a Project exists. It
created a pursuit and proposal, saved a successor proposal totaling 2,589.12,
uploaded a source document and calculated an estimate of 154.25. A second
person reviewed the exact estimate, then the requester executed its acceptance.

| Step | Actual capture |
|---|---|
| Open the pursuit | [Pursuit](evidence/r1/company-workspace/actual-company-pursuit.png) |
| Edit proposal pricing and alternatives | [Desktop proposal](evidence/r1/company-workspace/actual-company-proposal-desktop.png) |
| Compare the saved proposal revisions | [Proposal comparison](evidence/r1/company-workspace/actual-company-proposal-comparison.png) |
| Inspect an uploaded Company source | [Source document](evidence/r1/company-workspace/actual-company-source.png) |
| Calculate the estimate | [Company estimate](evidence/r1/company-workspace/actual-company-estimate.png) |
| Review as an independent person | [Estimate review](evidence/r1/company-workspace/actual-company-independent-estimate-review.png) |
| Inspect the accepted estimate | [Accepted baseline](evidence/r1/company-workspace/actual-company-accepted-estimate.png) |
| Use smaller screens | [Tablet proposal](evidence/r1/company-workspace/actual-company-proposal-tablet.png), [phone proposal](evidence/r1/company-workspace/actual-company-proposal-phone.png) |

The [verification record](evidence/r1/company-workspace/verification.json) records
no placeholder Project, no Project API calls, exact persisted results and zero
unexpected browser/network errors. It identifies continuation of the same saved
records after correcting keyboard and packet-label assumptions in the proof
script. An actual precision refusal for an unrepresentable proposal rate is
preserved separately. The [backend source window](evidence/r1/connected-browser-backend-freeze.json)
confirms all 337 captured app/test/metadata files stayed unchanged through both
connected journeys. These screens precede the targeted wording and density
cleanup; they do not imply proposal issuance or external delivery.

The later wording and responsive correction has a separate read-only capture
of those same records: [desktop proposal](evidence/r1/company-polish/actual-company-proposal-desktop.png),
[tablet proposal](evidence/r1/company-polish/actual-company-proposal-tablet.png),
[phone proposal](evidence/r1/company-polish/actual-company-proposal-phone.png),
[accepted estimate](evidence/r1/company-polish/actual-company-accepted-estimate.png),
and [source document](evidence/r1/company-polish/actual-company-source.png).
Its [verification](evidence/r1/company-polish/verification.json) records zero
business writes and unexpected errors, with the navigation geometry checked
after resizing the mounted application. Prior timeout attempts do not qualify
these views; the successful capture followed restored permissions and the
coherent runtime reload.

Construction contract/SOV baselines have actual backend acceptance. Award,
procurement, AP/AR and later AEC workflows remain in the approved sequence. See
[current status](IMPLEMENTATION_STATUS.md) and the [66-package backlog](EXECUTION_BACKLOG.md).

## Exact proposal PDF, Issue and fixture distribution

This Company-only journey prepared the proposal PDF with fixed intended
recipients and cover text. An independent person viewed that exact stored PDF
and granted its Issue. The requester later executed the preserved grant once;
the original preparation, request and Grant were not repeated. The resulting
Issue retains the same PDF and a native Quotation draft snapshot. Issue did not
send it.

| Step | Actual capture |
|---|---|
| Inspect the prepared PDF | [Desktop](evidence/r1/com02-browser/prepared-review-predecessor/actual-prepared-proposal-desktop.png), [tablet](evidence/r1/com02-browser/prepared-review-predecessor/actual-prepared-proposal-tablet.png), [phone](evidence/r1/com02-browser/prepared-review-predecessor/actual-prepared-proposal-phone.png) |
| Independently review the PDF, recipient and cover | [Desktop](evidence/r1/com02-browser/prepared-review-predecessor/actual-independent-issue-pdf-review-desktop.png), [phone](evidence/r1/com02-browser/prepared-review-predecessor/actual-independent-issue-pdf-review-phone.png) |
| Reopen the exact Company-bound grant | [Desktop](evidence/r1/com02-browser/exact-issue/actual-granted-exact-issue-desktop.png), [tablet](evidence/r1/com02-browser/exact-issue/actual-granted-exact-issue-tablet.png), [phone](evidence/r1/com02-browser/exact-issue/actual-granted-exact-issue-phone.png) |
| Execute that grant separately | [Executed Issue](evidence/r1/com02-browser/exact-issue/actual-original-issue-executed.png) |

The [exact execution verification](evidence/r1/com02-browser/exact-issue/verification.json)
records its one execution UUID, the original packet and PDF identities, actual
stored-byte hash verification, native draft status and no unexpected browser or
HTTP errors. The exact review URL carries a Company parameter, validated against
the signed-in session before reading the packet; sign-in preserves that context.
The [earlier incomplete capture](evidence/r1/com02-browser/prepared-review-predecessor/failed-capture-summary.json)
preserves the normal inbox's 30-second loading failure after the successful
request and Grant. It is not a failed or repeated execution.

A separate existing Issue had two fixed recipients. The author selected one
original recipient using its server-issued identity, saved an immutable fixture
instruction, rediscovered it in the saved register, and requested independent
review. The second person reviewed its exact message, subset and issued PDF.
The requester separately executed that grant to queue one local fixture
delivery. The runtime owner then observed the actual worker process that same
operation once, with one independent local sink acknowledgment.

| Step | Actual capture |
|---|---|
| Select an exact original recipient subset | [Desktop](evidence/r1/com02-browser/subset-instruction-review/actual-fixture-recipient-subset-desktop.png), [tablet](evidence/r1/com02-browser/subset-instruction-review/actual-fixture-recipient-subset-tablet.png), [phone](evidence/r1/com02-browser/subset-instruction-review/actual-fixture-recipient-subset-phone.png) |
| Independently review the instruction and fixed issued PDF | [Desktop](evidence/r1/com02-browser/subset-instruction-review/actual-independent-fixture-review-desktop.png), [tablet](evidence/r1/com02-browser/subset-instruction-review/actual-independent-fixture-review-tablet.png), [phone](evidence/r1/com02-browser/subset-instruction-review/actual-independent-fixture-review-phone.png) |
| Read the same operation's verified fixture acknowledgment | [Desktop](evidence/r1/com02-browser/fixture-readback/actual-fixture-readback-desktop.png), [tablet](evidence/r1/com02-browser/fixture-readback/actual-fixture-readback-tablet.png), [phone](evidence/r1/com02-browser/fixture-readback/actual-fixture-readback-phone.png) |

The [instruction verification](evidence/r1/com02-browser/subset-instruction-review/verification.json)
records its four journaled commands and actual Queued API state. Its three
original status screenshots were taken while the UI still loaded, so they remain
[explicitly unqualified](evidence/r1/com02-browser/failures/queued-loading/qualification-finding.json).
The final [read-only acknowledgment verification](evidence/r1/com02-browser/fixture-readback/verification.json)
waited for the rendered recipient count, loaded registers and no loading
indicators before every image. It made no business writes and matched the
server's expected logical key, payload hash and original PDF. The separate
[worker observation](evidence/r1/distribution-ui-automatic-delivery.json)
records the real queue/process and sink evidence. This is synthetic local
receipt evidence; no external delivery occurred.

The ordinary Company approval inbox now uses ten-row cursor pages without an
exact total. Official UI5 pop-ins keep Subject, Action, State and Review
accessible at smaller widths, including a copyable exact-review link:
[desktop](evidence/r1/com02-browser/inbox-responsive/actual-inbox-responsive-desktop.png),
[tablet](evidence/r1/com02-browser/inbox-responsive/actual-inbox-responsive-tablet.png),
[phone](evidence/r1/com02-browser/inbox-responsive/actual-inbox-responsive-phone.png).
The [read-only verification](evidence/r1/com02-browser/inbox-responsive/verification.json)
checks nested workspace width, full first-row content bounds and keyboard focus
from Review to its exact link. The phone workspace measured 390/390 pixels with
zero horizontal scroll offset. The [earlier clipped phone capture](evidence/r1/com02-browser/failures/inbox-clipped/qualification-finding.json)
is retained as a failed visual check.

The [bundle provenance](evidence/r1/com02-browser/provenance.json) distinguishes
each UI build, its served assets, the later inbox-only amendment and the
unchanged 350-file backend source window. Raw before-send journals remain
private; public evidence includes operation UUIDs and payload hashes. Recovery
in the application remains limited to the mounted view. These automated focus
checks do not establish full manual accessibility qualification.

## PRJ02 interface checkpoint — local fixture qualification only

The [award and normal Company cost setup package](evidence/r1/prj02-ui-contracts/README.md)
records82 unique passing browser cases,116 unchanged source hashes, nine generated
clients and the isolated build inventory. It preserves the first81+1 run, red
receipt/recovery cases and failed phone layouts with their exact limits. These
are synthetic contract/visual checks; actual isolated ERP award execution and
connected presentation remain a separate runtime gate. Main served `dist` was
preserved. No new actual award result is claimed by this checkpoint.


### Qualified Company cost setup on the isolated award epoch

[Cost setup variant 2](evidence/r1/prj02-ui-connected/cost-setup-v2/README.md) now contains actual desktop/tablet/phone code/type registers, one exact remaining successor save, and independent readback of all four original cost revisions. The three earlier successful commands were preserved. The new118-source/907-file UI variant bundles the official settings icon and licensed SAP72 fonts locally;19 focused fixture cases and actual settled keyboard/hit-test capture checks pass. Original incomplete attempts remain linked separately. This cost checkpoint does not claim award or accounting execution.


### Exact saved award plan successor, before approval

[Saved plan variant 2](evidence/r1/prj02-ui-connected/saved-plan-v2/README.md) records one normal UI save on the original handoff and independent exact readback. Only the Project name changed; frozen selling USD30.85, accepted cost USD15.00, original Issue/PDF/team/WBS/allocations and explicit dates remain unchanged. Three actual images show scrolled saved-plan/keyboard interaction; original PDF byte parity is separately qualified, and no full-visible-PDF-page image claim is made. The initial zero-command overflow attempt remains separate. No award request, Grant, Execute, Project creation or financial effect ran.

## Company Activity and reviewed draft saves

[Reviewed draft saves](evidence/r1/company-ricky-native-r15/ui/README.md) show selecting original suggestions, saved scope/estimate revisions, acknowledged eligible review and natural expiry. [Company Activity](evidence/r1/company-activity-r16/ui/README.md) shows those recorded changes, expanded details and the next authorized page at desktop, tablet and phone widths. These are actual container captures using explicitly synthetic business records and the real isolated ERPNext backend.

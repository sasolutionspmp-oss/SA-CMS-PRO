# Running Cipher build: implemented journeys

These screenshots were captured from the actual containerized SAP UI5/Horizon
client connected to the persistent ERPNext/Frappe development site. They show
synthetic business records. They are not generated images or design mockups.
The private development service listens at `http://127.0.0.1:18880` in the
execution environment; this address does not make it publicly reachable.

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

Company pursuits/proposals, PDF takeoff calculations and construction contract/SOV
baselines also have actual backend acceptance. Their complete user journeys,
accepted estimates, award, procurement, AP/AR and later AEC workflows remain in
the approved sequence. See [current status](IMPLEMENTATION_STATUS.md) and the
[66-package backlog](EXECUTION_BACKLOG.md).

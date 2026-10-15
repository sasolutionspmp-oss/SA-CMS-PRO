# Running Cipher build: first implemented journey

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

The exact estimating backend is implemented and verified through native records
and actual HTTP calls. Its functional editing screens are the next UI package.
Commercial, takeoff, contract/SOV, procurement, AP/AR and later AEC workflows
remain in the approved implementation sequence; this walkthrough is not a claim
that the entire ERP is complete. See [current status](IMPLEMENTATION_STATUS.md)
and the [66-package backlog](EXECUTION_BACKLOG.md).

# Saved Company scope and estimate suggestions

Cipher now stores scope and estimate suggestions and opens their original contents in the embedded SAP UI5 assistant. This is the Stage B implementation in [AI04_COMPANY_PROPOSALS.md](../../../AI04_COMPANY_PROPOSALS.md). The [actual running-screen gallery](ui/README.md) shows the connected implementation.

The real isolated ERPNext/Frappe backend passed four distinct cases: ordinary saved scope, ordinary saved estimate, interrupted finalization recovered after natural lease expiry, and cancellation after preparation. Ordinary RQ consumed each original job. Three immutable suggestions remain reviewable; the cancelled Run has none. Recovery reused the original successful Invocation and Step without executing the tool again.

Later working revisions preserve the original saved review. Source revocation hides the Run, suggestion, source-bearing receipt and history; restoring the exact duty restores access. A same-Person alias and outsider cannot read the owner's suggestion, and the alias cannot reuse the owner's history cursor. Source-free terminal Stop acknowledges the original terminal state without cancelling the suggestion. Replays preserve original receipts and add no history events.

Verification covers **907 distinct backend cases** (851 unit and 56 integration, composed across recorded runs), **220 distinct browser cases** (219 complete-suite passes plus the unchanged isolated case after a Chromium crash), twelve generated contracts and the 905-file production build. Eight earlier native workflow procedures retain their own qualification. Nine actual screenshots used 23 API GETs, fifteen successful font responses, zero browser/resource errors and no business command. Browser fixture tests and connected captures are separate evidence.

The original failed request and prerequisite attempts remain retained. A separate continuation reused the original commercial UUID/payload and copied sessions after an explicit synthetic Account select permission. The response boundary now removes native auxiliary fields from Cipher's closed canonical envelope. Native session maintenance is attributed only to the exact original User's time-bounded `last_active`; no identity timestamps or client IPs were reset. Supported source-duty restoration retains its normal audit timestamps.

Independent readback confirms all fourteen financial table inventories and the three existing Projects are unchanged, with no active Run, queue job, started job or worker left. Main remains on its separately qualified release. The live Ricky model and QuickBooks are unconnected; explicit human draft-save commands are the next stage. No business application, acceptance, issuance, distribution, award or accounting effect is enabled here.

The [fresh hosted CI](https://github.com/sasolutionspmp-oss/SA-CMS-PRO/actions/runs/38882030414) subsequently passed all 25 stages, including complete backend/browser suites and eight native workflows. This later run is recorded in [hosted-ci.json](hosted-ci.json); earlier local composed results and failures remain unchanged.

- [Qualification, native phase hashes and retained failures](qualification.json)
- [Backend qualification](backend-qualification.json)
- [Browser qualification](browser-qualification.json)
- [Complete source snapshot](source-snapshot.json) and [review](source-review.json)
- [Actual desktop, tablet and phone screenshots](ui/README.md)

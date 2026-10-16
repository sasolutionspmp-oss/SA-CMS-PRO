# Company Ricky recovery and execution isolation

Three new cases passed on the existing isolated Frappe/ERPNext site, using actual cookie/CSRF admission, native storage and the ordinary worker. Original failed cases and original operation UUIDs remain intact.

| Case | Verified result |
| --- | --- |
| Interrupted deterministic read | After its actual 180-second lease expired, ordinary recovery and RQ delivery completed the same Run. The already committed Step, Invocation and artifact bytes remained exact; one invocation, no repeated tool result, and the old worker token was refused. |
| Permission loss before recovery | After actual lease expiry, the ordinary worker refused the read with `stale_authority`, no invocation and no result. The exact original duty was restored. This case used direct worker callthrough. |
| Execution quarantine | Worker, recovery and direct service guards refused execution. A new HTTP Start returned 503 and created no Run or receipt. Existing reads and the original queued receipt remained available. After exact configuration restoration, ordinary RQ delivery completed the queued Run once. A new Stop on that succeeded Run, replay and operation read proved restored web admission without changing the result. |

Both RQ bursts drained three queue entries representing two unique jobs, including retained hints for older terminal Runs. Their payloads and invocation counts stayed unchanged. Final checks found no active worker or started job, and preserved earlier Company/Project orchestration bytes, source records, duties and the Company Project set. All three new Start receipts and the separate Stop receipt passed the shared byte/schema verifier.

This qualifies interruption at a committed checkpoint, current-authority refusal and an operator execution flag. It does not qualify an OS kill, Redis loss or restored-site recovery. The live Ricky model and QuickBooks remain unconnected. Canonical Company Ricky command history and persisted suggestions/human draft saves remain subsequent work. The main site retains its separately qualified release.

The change contains four backend fixture/test paths and one browser assertion correction; production backend, schema and UI source are unchanged. All 760 unit tests passed together. The unchanged 52 integration cases give 812 composed backend cases, alongside eight unchanged native workflows. All 190 browser cases passed in a fresh complete confirmation with no failures, skips or retries. The exact existing 905-file UI build was verified and reused.

The preceding [hosted CI run](https://github.com/sasolutionspmp-oss/SA-CMS-PRO/actions/runs/38855102825) passed backend and workflow checks but failed one of 190 browser cases. UI5 updated the checkbox asynchronously after Playwright's immediate `check()` assertion. The corrected test clicks once and waits for the checked state before releasing the delayed newer register head; its initial and successor reset assertions remain. Original local/hosted failures and two separate runner-setup failures are retained in the evidence. A new hosted result is separate from the passing local confirmation.

- [Native qualification and phase hashes](qualification.json)
- [Complete source snapshot](source-snapshot.json)
- [Unit qualification](unit-qualification.json)
- [Browser correction, failures and confirmation](browser-qualification.json)
- [Existing actual desktop, tablet and phone screenshots](../company-ricky-native-r10/ui/README.md)

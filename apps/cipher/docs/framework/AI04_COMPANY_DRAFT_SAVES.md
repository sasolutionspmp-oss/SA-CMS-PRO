# Company Ricky reviewed draft saves — Stage C

Stage C connects a reviewed saved suggestion to a real new commercial proposal or Company estimate revision. Cipher uses the existing canonical writers, native Quotation persistence and exact estimate calculation. The embedded SAP UI5 assistant presents a separate draft preview, explicit review acknowledgment and save command. [Stage B](AI04_COMPANY_PROPOSALS.md) remains the immutable original suggestion.

The R15 source is frozen and source-qualified. Real scope and estimate saves, eight distinct boundary cases, independent concurrency reconciliation and the final native preservation audit passed in the isolated ERPNext runtime. [Thirteen actual running screens](evidence/r1/company-ricky-native-r15/ui/README.md) show the connected workflow. Original failed concurrency expectations remain retained. Main remains on its separately qualified release. Ricky model inference and QuickBooks are not connected.

## Human workflow

1. Open Company **Saved suggestions** and select the original scope or estimate suggestion.
2. Choose **Review draft save**. The server derives the exact proposed working revision from the retained preparation and original canonical source records.
3. Review appended scope sections, retained prices and terms, or the proposed quantities, original basis and labeled notes. The interface shows current eligibility and the original review deadline.
4. Select **I reviewed the proposed draft and its original sources**, then save. The server checks authority, session, source closure and the current working revision again within the transaction.
5. Read the confirmed saved revision and open its commercial proposal or exact estimate revision. The original suggestion remains available separately.

Scope mapping appends sections labeled **Unverified author suggestion** and retains original pricing, terms and citations. Estimate mapping clones the original calculation inputs and replaces only the selected exact quantities, preserving conversions, adjustments and citation provenance. Human authored notes remain labeled. The system does not convert an authored statement into a verified engineering measurement.

## Closed API and canonical persistence

The new module is `cipher_aec.ricky.company_draft_save_api`, with published contract file `ricky/schemas/company-draft-save-api-v1.schema.json`:

| Method | HTTP | Boundary |
| --- | --- | --- |
| `draft_save_subject` | GET | Original suggestion, derived payload, current eligibility and any retained application. |
| `save_draft` | POST | Company, original proposal ID/version/digest, mapping version `1`, reviewed payload digest and operation UUID. |

The client sends binding fields only. It cannot supply a replacement composition, quantity, target, authority, session or callback. Dispatch is fixed to the existing canonical commercial proposal revision service or Company estimate calculation service.

One immutable `Cipher Ricky Draft Save` binds original Run, Step, Invocation, preparation, manifest and payload digests to the saved revision and receipt. Unique indexes on source proposal and receipt enforce one application. The deterministic application ID, native linkage headers, immutable core and private receipt envelope are independently checked when reading the application.

The canonical domain effect, command receipt, application and two linked Company history events commit in one savepoint. The history sequence is the existing domain revision event followed by `ricky.company.proposal.draft-saved`. A later failure rolls that transaction back. Generic insert/update/delete/rename paths confer no application authority.

## Fresh authority and historical receipts

A new save requires the actual original User, canonical Person and live original session; current Company and native read/write rights; original source access; an unexpired review; an unchanged current target and native fingerprint; and the original successful terminal preparation without cancellation or fencing changes. A same-Person alias does not become the original author.

The complete original and saved source graph, including snapshot-pinned conversions, is discovered before sorted source/master/native admission. Both canonical source readers and the writer reuse that admitted closure. The original Stage B manifest and preparation bytes are not rewritten.

After a successful save, current authorized historical reads and exact operation replay return the retained application and revision even after a later working revision or expiry. Replay does not require fresh write authority, a live original session, a current head or an unexpired review. It still requires the actual original User/Person and current read/source/native rights; a receipt cannot bypass revoked access.

## UI recovery and verification

An uncertain save retains its exact mounted operation UUID and reviewed payload. **Recover original draft save** uses that command. Company/Project navigation, mode changes, close, sign-out, Stop and fresh submission are locked while the outcome is unknown. This is mounted-view recovery; durable recovery across browser reload is not claimed.

The client independently validates the published response shape, original revision/snapshot bindings, exact scope append or rational estimate mapping, and application/receipt/saved-result linkage. A source denial hides source-bearing content while preserving an uncertain request for recovery. Official SAP controls are used without an alternate design system.

The frozen candidate contains 697 source files, including 33 changed paths against R14. Full backend qualification passed **942/942** cases: 886 unit and 56 actual Frappe integration checks. Thirteen generated client contracts, TypeScript and the 905-file production build passed. Browser qualification covers **239 distinct cases**: 238 full-run passes and the unchanged case passing separately after a Chromium target crash. The original failed browser report remains retained.

The supported additive sync created one empty DocType table and its metadata, preserving all 820 old table definitions/indexes and 25,279 original rows exactly. Database, site-file and runtime-source backups were read and verified before sync; a restored-site rehearsal has not been performed. Only the isolated web workers were reloaded.

Real author HTTP/RQ flows saved and independently verified both a scope revision and an estimate revision. Later separately authored revisions and natural expiry preserved original historical reads and exact receipt replay. Eight further cases passed: cancellation before RQ, source-duty loss, native Quotation write loss, Company estimate-write loss, stale target, alias/outsider denial, unsaved natural expiry and rollback after actual canonical persistence. The rollback uses a separately labeled one-shot loopback fixture with genuine original Frappe cookie/CSRF authentication and an instance-only failure after receipt/application/history insertion; it is not a production HTTP failure hook or OS-kill rehearsal.

Two overlapping original author requests produced one canonical winner and one retryable `503 concurrent_change`. The original checker expected a `409 draft_already_saved` and remains failed. After independently proving the winner and no loser effect, one explicit retry of the same losing UUID returned `409 draft_save_expired`: its original deadline had passed while the additional verifier was prepared. That checker also remains failed; no third request or replacement UUID was created. The separate final read-only audit verifies these exact recorded outcomes, the one saved application, both original intents, actual time bounds and absence of any losing receipt/history effect. It does not rewrite either failed phase, the original batch or the original case.

The final audit preserves all inventoried original rows and all 53 rows added by the already-audited positive epoch, plus exact configuration/source/index/cookie/R14 evidence. Only three supported permission/duty restoration audit deltas and 141 bounded original User/Session observations are attributed. It derives exactly 31 command receipts, 34 history events and three draft-save applications across the complete fixture. Financial tables and the three existing Projects remain unchanged; no active Run, queue job, started job or worker remains. [Native evidence and retained failures](evidence/r1/company-ricky-native-r15/README.md) record the distinctions.

Thirteen actual captures used 48 API GETs with no browser errors, mocked responses, login, business command or model invocation. The initial nine show selection and saved scope/estimate at 1440/900/390; four additional desktop/phone captures show an acknowledged eligible draft and the same unsaved draft after natural expiry. The browser selected the acknowledgment checkbox but never clicked Save. Production build bytes remained unchanged.

This increment saves working drafts. Baseline acceptance, issuance, contractual execution, award, distribution, accounting and external-provider effects retain their separately defined commands and gates.

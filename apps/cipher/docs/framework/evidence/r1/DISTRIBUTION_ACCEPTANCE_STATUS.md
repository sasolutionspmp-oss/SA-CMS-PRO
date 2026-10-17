# Distribution acceptance status

The local manual controls, registered consumer, queued-job restart, actual Redis
publication failure recovery and operator quarantine gates below passed. The
[operational report](distribution-operational-acceptance.json) records their exact
source and runtime boundaries.
There is no live email/provider qualification. The immutable Issue still records
`distribution: not-sent`; observed acknowledgments identify only the synthetic
durable SQLite sink.

| Boundary | Actual evidence |
| --- | --- |
| Independent mandate | [Cookie/CSRF instruction, grant and consumption](distribution-http-mandate.json): alias self-review denied, independent human granted, original instruction UUID resumed after the preserved schema defect, canonical retry produced one dispatch. |
| Lost acknowledgment | [Real worker and independent sink](distribution-worker-lost-ack.json): sink accepted original PDF, injected response loss produced Unknown, independent database connection acquired all ten probed rows during the adapter boundary, and sink receipt survived Frappe rollback. |
| Recovery and fencing | [New-process readback](distribution-worker-readback.json) used the same key and no accept call after controlled synthetic lease expiry. [Old fence](distribution-worker-stale-fence.json) could not change success or attempt history. |
| Partial recipients | [Two recipients were independently issued](distribution-two-recipient-issue.json). [One accepted-but-unconfirmed recipient](distribution-partial-lost-ack.json) coexisted with [a succeeded recipient](distribution-partial-second-success.json); [duplicate success did not resend](distribution-partial-completed-no-resend.json). |
| Stop and authority | [Actual cancellation and alias replay](distribution-cancel-http.json) led to [worker refusal](distribution-cancel-worker-refused.json). [Revoked distribution duty](distribution-revoked-worker-refused.json) prevented new acceptance and was [restored](distribution-duty-restored.json). |
| Expiry | [Native worker refusal](distribution-expired-worker-refused.json) used an explicit fixture clock after the immutable mandate deadline. This is not an actual elapsed-time or persistent-worker restart proof. |
| Source privacy | [Bounded cookie/CSRF proof](distribution-source-privacy-bounded.json): document.read outage denied instruction/dispatch/packet/receipts/retries/PDF. Internal same-key acknowledgment reconciliation remained observational and did not restore public access. Original receipts/PDF recovered after restoration. History was explicitly excluded. |
| Restoration | [Independent post-refresh native readback](distribution-restoration-resume-readback.json) confirms document.read and commercial.distribute active, and all six manual operations terminal. The Unknown was not recreated or rerun. |
| First automatic consumer | [Actual registered RQ publication](distribution-registered-publication-first.json) preceded [supervised startup](distribution-pair-start-first.json). [Read-only observation](distribution-automatic-consumer-first.json) found canonical success, one worker attempt, finished RQ job and exactly one sink acknowledgment/PDF, with no manual deliver/publish. Root then [stopped the exact pair](distribution-pair-stop-first.json); no child process remained. |
| Read models and subset | [Actual existing-record HTTP](distribution-read-model-http.json) validates canonical recipient order/digest, instruction/version register, exact Issue count/filter, bounded pages, cursor filter mismatch and foreign/denied scope. [A reviewed subset](distribution-queued-restart-stage.json) selected exactly the first server-issued recipient of the existing two-recipient Issue. |
| Already queued restart | [Real queued job](distribution-queued-restart-queued.json) preceded pair startup; [same-ID completion](distribution-queued-restart-succeeded.json) has one attempt, finished RQ job and exactly one independent sink receipt. The supervised pair was then stopped. Outer supervisor restart is operator managed. |
| Real publication failure | With the pair stopped and only the site queue endpoint set to unavailable port1, actual cookie/CSRF consumption committed [Queued/attempt0 with no exact job on original healthy Redis and no sink receipt](distribution-redis-publication-failure-publication_absent.json). After exact restoration, normal pair startup discovered and republished [the same ID automatically](distribution-redis-publication-failure-succeeded.json), with one acknowledgment. No manual deliver/schedule/publish substituted for recovery. |
| Operator quarantine | [Actual RQ Finished Quarantined NoOp](distribution-operator-quarantine-quarantined_noop.json) left the canonical operation Queued/attempt0/sink0; [a second observation](distribution-operator-quarantine-second-noop.json) spans the automatic publisher interval. After exact flag restoration and a new process lifetime, [the same finished job ID was requeued and completed](distribution-operator-quarantine-succeeded.json) once. This qualifies an operator flag, not an actual restored-site rehearsal. |
| Final restoration | [Independent fresh native readback](distribution-operational-independent-restoration.json) confirms exact original queue/quarantine key presence/value and complete site/common configurations, general scheduler disabled, pair off, rights restored, Company still without Projects/financial effects, original Project hash controls preserved, and all 347 Python/JSON hashes unchanged. |
| Current acknowledgment delta | After the joint reload, [17 read-only cookie/CSRF observations/schema samples](distribution-current-ack-http-delta.json) require logical_key/payload_hash on the same three successful operations and match the original independent sink acknowledgments. All six original command receipts and the retained cancellation receipt remain unchanged; current cancellation is readable. [Raw native preservation](distribution-current-ack-native-preservation.json) and separate 348-source captures confirm no operation/receipt/sink changes. No fault, worker or approval sequence was repeated. |
| Normal Company approval inbox | After the reviewed reload, [actual none-count pages and exact original Granted packet](company-approval-inbox-http.json) passed: author pages of ten took 1.19s and 1.46s; exact packet read took 0.37s. Reviewer cursor/execution isolation and outsider/Project-only denials passed. Eleven observations/six schema samples sent no decision, execution or other business command. [Original operation/receipt preservation](company-approval-inbox-native-preservation.json) and separate 350-source captures remain intact. Full exact-count and history performance are unqualified. |
| Actual UI automatic delivery | The UI independently selected one of two original recipients and queued a new approved dispatch. [QA observed real RQ membership before startup and the same operation's automatic success](distribution-ui-automatic-delivery.json), with one exact original PDF/sink acknowledgment and one native recipient operation. Root stopped the pair; known supervisor/session absence is independently checked. The 350-source window is unchanged. No fault, command, config or rights change was performed by QA for this observation. |

The initial [native document ID schema mismatch](distribution-http-initial-schema-failure.json)
and [40-second first history page timeout](distribution-source-privacy-initial-history-timeout.json)
remain preserved. The latter occurred before any duty change, with
[150 native Company history rows](distribution-history-timeout-row-bound.json).
History privacy/performance is unqualified pending its focused post-fix proof.

[Publication inspection](distribution-publication-before-registration.json)
found six committed operations but no namespaced RQ jobs; the
[fresh queue catalog](distribution-queue-registration-observation.json) lacked
the dedicated queue. A database Queued state did not prove RQ publication. This
is a real queue-configuration failure, distinct from the later actual Redis
publication-failure/recovery case above. Root subsequently registered the queue; that
configuration does not retroactively qualify earlier publication.

[The evidence inventory](distribution-evidence-progress.json) records raw report
hashes and source/reload boundaries. HTTP observations, schema samples and native
probes are separate evidence, not an added behavioral test count. Earlier reports
are not rewritten to claim later source changes, queue setup or automatic delivery.

The first [quarantine restoration failure](distribution-quarantine-restoration-initial-mismatch.json)
is preserved: the private helper used parsed Python `None`, which this pinned
installer stored as JSON `null` rather than deleting the originally absent key.
Only that owned flag differed; unrelated site/common settings were unchanged.
The corrected supported command passed unparsed string `None`; [exact restoration](distribution-quarantine-restoration.json)
was independently verified before automatic recovery of the original intent.
[Helper invocations and hashes](distribution-operational-invocations.json), the
[corrected continuation](distribution-operational-resume-invocations.json), and
[final cleanup](distribution-operational-resume-finally.json) retain the sequence.
Broader in-flight host failure, unattended outer-supervisor restart, actual
restored-site/sink-ledger rehearsal and live transport remain unqualified.

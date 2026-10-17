# FLD02 independent source review

Reviewer: existing GPT-6.1 Sol Ultra backend lane; no extra agents. Read-only review of the five requested new core files, FLD01 source/command/receipt behavior, and the new API/privacy-install boundaries. No product source edits, tests, builds, provider/runtime/native calls or publication performed. Base commit: `0147603655624c3ad66ef73f6921a06805abff9a`. This receipt records observed source hashes, not a final combined qualification or native completion.

## Concrete findings and observed corrections

1. **Superseded payload redaction:** service discard retained `superseded` and emitted `redacted`, but the controller originally admitted retained redaction only for committed captures. The controller now permits the exact `superseded -> superseded / redacted` privacy transition while retaining immutable replacement lineage. Addressed by source review.
2. **Participant identity race/order:** apply discovered superintendent people before locking but did not recheck those user-to-Person bindings before taking Project/capture/source locks. A binding moved before the old-Person binding query could otherwise make the inner canonical field command acquire a newly discovered Person after those locks. Apply now captures the participant map and rechecks every mapping after ordered Person/Identity locks and before Project/source admission. Changed identity fails explicitly. Addressed by source review.

Root also added a refusal for a fresh stage operation against an already terminal capture and rechecks current new-use source eligibility when admitting a duplicate staged capture into a new operation receipt. Those changes are coherent with immutable envelopes; the original same-operation receipt path remains distinct from new staging eligibility. No further blocking authority/transaction/control gap was identified in this bounded review.

## Verified design boundaries

Device ownership is an exact Company/Project canonical Person. Same-Person aliases can perform current authorized sync while envelope attribution remains bound to the original device registration user/person. Declared device/capture timestamp attribution is evidence, not hardware attestation or a trusted capture-time authority grant. JSON shape/depth/node/text and serialized size are bounded; the capture envelope is immutable and capped at256KiB.

Stage/discard/resolve use separate canonical offline command UUIDs. Apply requires the original capture UUID, checks an existing exact canonical FLD01 receipt before current base/new-work eligibility, then rechecks receipt after Person/Project admission. Exact command/request hash/scope and original source/read rights prevent rebinding a conflicting receipt. An already committed original can be read without creating a new field command or moving to a later record head. Current identity/Project/source permissions remain required to reveal its actual content.

New use checks the original Project sources' exact bytes/SHA/page/locator, current working source eligibility and explicit ingest rights through FLD01 sources.resolve, plus explicit current read rights. Exact base revision/digest and current header/version are distinguished. Conflict resolution requires a fresh capture UUID and explicit current base/source review of the same action/family/record; it does not merge or apply automatically.

Apply establishes one uniquely named outer savepoint, invokes the existing FLD01 canonical writer once, then writes the offline event/commit pointer in the same caller transaction. A late offline failure rolls back the canonical field facts, history and command receipt through that outer savepoint. There is no outer nested run_command, extra field writer, commit, worker, network or financial/acceptance effect. Native savepoint/locking/concurrency behavior still requires qualification; host doubles are not that evidence.

Discard clears only the offline envelope and keeps immutable capture/event identity and any canonical business receipt. Committed and superseded redactions preserve standing/lineage. Privacy cleanup deliberately avoids reading revoked source text or invoking the field writer, but still requires current Project field.write and the supported open-Project write lifecycle. It is not business-record erasure or a bypass of current write authority. Browser encrypted device storage, reconnect UX and local purge are contract-only at this stage, not an implemented or native-qualified vault.

## Explicit remaining composition/qualification limits

- There is **no global governance reservation of every staged capture UUID**. An unrelated command by the same canonical Person can consume that UUID before apply. Offline original-receipt admission detects mismatched command/request hash and refuses operation_conflict before a new FLD01 effect; it does not rebind, merge, silently allocate another UUID or claim namespace-wide prevention. Root deliberately leaves global governance unchanged; coordinator composition must retain this distinction.
- Shared API/catalog/schema/generated registration, offline canonical receipt dispatch and all native permission/query-denial hooks remain local composition work. Generic native access must not reveal the private plaintext envelope. Local DocType/index installation and actual Frappe controller/transaction tests remain unexecuted by this reviewer.
- The earlier `02-offline-fixture-corrected.log` records13 passing host service cases after an initial missing-context fixture failure retained in `01-offline-service.log`. Earlier `05-fld01-fld02-combined.log` records73 passed host checks:29 FLD01 and44 FLD02. Final `08-fld01-fld02-final-host.log` records74 passed host checks:29 FLD01 and45 FLD02, including11 checks exercising the actual repository/controller implementation against explicit host persistence/session doubles. The reviewer read the log and test boundaries but executed none of those checks. This is not native Frappe/MariaDB persistence or concurrency evidence.
- No browser storage, device hardware, native Frappe instance, concurrency/locking, restore/reconnect, full product workflow or operational privacy acceptance is qualified by this source review.

## Final source/policy addendum

The new `authorize_history_subject` admits only the exact offline Device subject type, requires current Project field.read, and reads the current exact owner/Company/Project device before exposing historical device-event metadata. It grants neither another Person's device history nor new use of a revoked device. Current same-Person aliases can read their original owned history; the historical event is not a permanent authority grant. The shared history callback remains a composition fragment.

`device-policy.json` explicitly declares `contract_only_no_browser_vault_or_service_worker`. It requires encrypted opt-in client storage, exact site/Company/Project/Person/device partitioning, no persisted session/provider credentials, finite expiry, truthful save/quota failures, selected explicit reconnect, original-UUID recovery and local discard without server authorization. These requirements are not delivered browser features. Source attachments reference existing canonical revisions; unuploaded camera/binary drafts cannot be sealed by replacing temporary IDs later. Server plaintext, current-write discard limits, retained business records/backups and absence of secure-erasure/hardware attestation are disclosed.

`FLD02_OFFLINE_CAPTURE.md` and `fragments/fld02/{COMPOSITION.md,shared-additions.json}` consistently present a host-qualified source candidate. They retain all native list/read/export denial hooks, module/index installation, exact summary-receipt dispatch, device-history dispatch, eight route/schema registrations and generated shared output as explicit coordinator composition. They reuse existing duties without automatic grants and add no worker/scheduler or background business apply. Capture UUID reservation is a **protocol convention**, not global namespace prevention; the unrelated-command conflict behavior and uninstalled reservation limitation remain explicit. No further blocking guarantee/control mismatch was found.

The prior addendum observed the combined73-case log pass. The final staged-participant addendum below records74 passed host checks on the changed source; neither result was executed by this reviewer or establishes browser/nativeSQL/transaction/concurrency/operational-trust acceptance. No product source was edited during independent review.

## Final staged-participant correction

Root identified and reproduced one additional meaningful identity defect: resolving the superintendent login afresh at apply could silently use another canonical Person after the capture had already been staged. `06-staged-participant-failing-first.log` captures the actual old-code regression failure (expected refusal did not occur); `07-staged-participant-fixed.log` captures the corrected refusal. `08-fld01-fld02-final-host.log` records74 passed host checks:29 FLD01 and45 FLD02. The reviewer read these artifacts and the exact code/test/doc correction without running tests.

Captures now store a private immutable `participant_people` map. The closed record validator binds its user key to the sealed daily superintendent field; controller updates cannot replace that map. First staging resolves and freezes the current canonical participant with current Project field.read, rejecting the original registration login when it would now imply another Person as that participant. Before staging, offline participant attribution remains unverified. Duplicate staging and inspection recheck the persisted participant binding and read duty. Apply accepts that staged map, checks it before ordered locks and again after Identity Binding locks, then passes unchanged original business request bytes to the existing FLD01 writer. A changed/revoked participant requires explicit discard/new sealing rather than silent alias replacement.

The original canonical receipt read deliberately remains before these new-effect participant guards, so a later binding change does not turn a readable already-committed receipt into a new application or force a new UUID. The new private persisted field changes no public schema/wire. The earlier global namespace-reservation limitation remains: this guards the offline new-effect path, not arbitrary other canonical calls intentionally occupying the same capture UUID. No further product change was requested in this final bounded review.

## Observed source hashes

Final staged-participant review observed UTC: 2026-10-17T14:24:37.904395+00:00

| Path relative to cipher_aec | SHA256 |
| --- | --- |
| field_offline/contracts.py | `01629128b4af32a94b2e494ec2a12adf54d6f7f1e69d5c19edb5c36c6c65f72b` |
| field_offline/spec.py | `b29ad8c93dfc6194c1ae67c3c97684dcbcd382fabc388e3a1b2b515bf17ed4ec` |
| field_offline/repository.py | `2ca1e061d501e2a24f56bb2ed9e7bb54fd780ac16d79f3cd66626f06a797659f` |
| field_offline/records.py | `026c78321e9e08bf30598aa6ada5310ebc8aaacaa2898208562c61d71c999f40` |
| field_offline/service.py | `fc2cd0ba235535e1635a9932750e76a7b574aa22a498654cde552634b4d795d6` |
| field_offline/api.py | `c9376b03144b68368c8e654f14372804358ce14bb7118c062ba8317c592dffab` |
| field_offline/install.py | `e3e5a1b4e65a4687437b078e53edd9665549011699d8189f1cabe28ffe1f26db` |
| field/service.py | `ef862b28a23fa4cb268005b0490fc8d8d7d53262de0890fed0d6b5bf4d5c73a7` |
| field/sources.py | `410d05940e34b09318b8471d1667ab9902abe7a93570bbe1ee7e1cda63465fad` |
| governance/commands.py | `dad6d3b966ebcb2ca9ba5ad7ccbb0d0eaec5fa69736810465ca0160ee6b66bc1` |

| Reviewed supporting artifact | SHA256 |
| --- | --- |
| workspace/apps/cipher/platform/apps/cipher_aec/cipher_aec/field_offline/device-policy.json | `275598cf44a22fe09133a4addb61a82ede4917416e4e031623e4e99dd44042d3` |
| workspace/apps/cipher/docs/framework/FLD02_OFFLINE_CAPTURE.md | `e8e81780c369342d743998326fd64a1897dc339341c5a00ddb92873c86218777` |
| workspace/apps/cipher/docs/framework/fragments/fld02/shared-additions.json | `008cc5f1daa3c3f983ce2847f0d325f41e65be114efca7626a97829df46d0686` |
| workspace/apps/cipher/docs/framework/fragments/fld02/COMPOSITION.md | `b4efba5f1364f9d05e658881ade465e0aa23c3f45551f10b3d2046d40ced672e` |
| workspace/apps/cipher/platform/apps/cipher_aec/cipher_aec/tests/test_field_offline.py | `581a91f714f2fd6b6040d6efa49c91d97d749778fb6bdc0d6e3205b5f765ffed` |
| workspace/apps/cipher/platform/apps/cipher_aec/cipher_aec/tests/test_field_offline_contracts.py | `1f6c4a615b389bb75714a3f5137e772f3b91cf8f75f46f86442f1ac8f170624a` |
| workspace/apps/cipher/platform/apps/cipher_aec/cipher_aec/tests/test_field_offline_persistence.py | `5b47ea60683171468b4966fb6794b482c377e9c948da63c23b3c51a5ea56f6d2` |
| 05-fld01-fld02-combined.log | `30c5912cc6f46b69e2497270ee1d7efaa67b67bdb3646b36eff81b17ad84eec1` |
| 06-staged-participant-failing-first.log | `fe6d4fee8330a8b4cbb733956d3901a68efbf049a3937cf3b50c031069a1959d` |
| 07-staged-participant-fixed.log | `2268633952e13010309305a96d060b7a28b4637a82bffada310484e96a55814e` |
| 08-fld01-fld02-final-host.log | `db59373c9c5ea4e9f92767eab17324853a6e08b1959f418e04cd2e65ef8bf00c` |

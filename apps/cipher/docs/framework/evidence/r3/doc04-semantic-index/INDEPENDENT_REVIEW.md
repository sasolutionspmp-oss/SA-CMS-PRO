# DOC04 independent review

Reviewer: GPT-6.1 Sol Ultra, existing backend/provider lane. Reviewed the root-owned service/persistence/controller/configuration/API/worker and the canonical SourceAdapter read-only. No source edits, test executions, runtime/native actions or provider calls were made during this review. The note records observed source, not a combined source freeze or deployment approval.

## Findings and resolutions

| Finding | Resolution observed in source | Status |
| --- | --- | --- |
| Concurrent reconcilers could both delete the same captured batch, then advance the latest cleanup cursor twice. | service.reconcile retains captured cleanup_next and refuses checkpoint advancement if that exact cursor changed. CAS still protects the subsequent save. | Addressed |
| A stale scroll payload could classify an existing live point ID as orphan and delete a worker-corrected point. | Orphan deletion now selects only IDs absent from every active/pending/running/retryable ledger; payload drift is not permission to delete a live ID. | Addressed |
| Query source snapshot joined only its token, unlike preparation. | Query checks returned scope, exact selected source and original token before canonical reconstruction; final authority/generation checks also follow source rechecks. | Addressed |
| Native read omitted the profile_id index-to-JSON comparison. | FrappeStore.load checks native profile_id together with scope, version, corpus key and record digest. | Addressed |
| Checkpoint validation accepted arbitrary jobs; zip could omit unmatched source tokens. | Closed checkpoint validation now checks selector/token lengths, job identities/request/generation, point/source/hash joins, bounds, offsets, leases and the unique active-generation relationship. Both load and controller writes validate it. | Addressed |
| Provider model tag allowed256 characters while the shared identity allowed140. | Shared identity now matches the256-character provider bound. SHA256 scope/profile IDs, UUID generation/point IDs, batch16 and metadata-only payload fields agree. | Addressed |
| Plain repeated DB reads could reuse a repeatable snapshot across provider calls, defeating final current-state admission despite write CAS. | require_fresh_reads precedes every persisted load/save, inspects MariaDB @@session.tx_isolation, and refuses unverifiable/non-READ-COMMITTED sessions with503. It neither changes isolation nor commits an unrelated caller transaction. | Supported-config fail-closed gate added; actual native isolation/concurrent revocation qualification remains open |

The READ-COMMITTED gate is a condition for this implementation, not evidence that a site currently satisfies it. Freshness still depends on the supported MariaDB/Frappe transaction behavior; host doubles do not establish native concurrency. Unsupported/malformed SQL result shapes now also refuse with semantic_unavailable. No isolation statement or caller commit is used to bypass admission.

## Other reviewed boundaries

Configuration accepts only server-owned model/endpoints/dimensions/protocol/collection/limits and optional Qdrant key. No RPC can select endpoint, model, actor or worker identity. RPC fields are closed; prepare/cancel require effects enabled. Worker requested_user comes from the original server actor; run checks exact original current user/person and current duties. Enqueue after request commit and same-operation resumption preserve a stable job when a queue/provider reply is uncertain. No authority is inferred from a source token or vector payload.

SourceAdapter validates actual origin plus target scope, canonical working/issued/adopted selection, exact adoption/issue evidence, current source and evidence read/ingest permissions, byte length/SHA and canonical page/excerpt facts. Supporting evidence policies remain bounded and independently authorized; Company and foreign-Project sources require both target and original current authority. Snapshot tokens exclude actor authority and remain actor-independent; every snapshot/recheck calls current canonical readers. No-text/OCR-unavailable sources refuse semantic extraction rather than inventing OCR. No material additional contract/control gap was identified in this bounded review.

The Corpus controller requires the private exact checkpoint write plan and trusted writer, validates native indexes and rejects native delete/rename. Durable store construction and each durable save additionally require the private dedicated_worker context and zero recorded preexisting transaction writes; both worker entries establish this context after selecting the original server-captured user. Ordinary request stores never commit the caller transaction. Existing-row saves revalidate original native scope/profile/version/digest under the row lock before updating. These source checks do not qualify actual Frappe transaction-counter/queue behavior. Permission-denial hooks (`deny_native_access`, `no_native_rows`) remain **pending until the coordinator composes their hook fragment**; the reviewed global hooks.py has no semantic entry. The DocType's System Manager read declaration does not replace those hooks.

## Final composition and inherited native-name gap

The reviewed `apps/cipher/docs/framework/fragments/doc04/COMPOSITION.md` and `shared-additions.json` are explicit local-coordinator additions, not shared-file replacements or already-installed capabilities. They declare both Corpus permission hooks, exact Company/Project manage duties with no automatic grants, module/DocType installation, four closed v1 transport registrations, dedicated after-commit worker use, READ-COMMITTED admission, provider provisioning/configuration, bounded source-change reconciliation and later Ricky integration. These remain composition/qualification work until actually applied. Existing Task/trial/global source is not replaced by this candidate.

The additional actual-name source regression uses DOC02's real `DOC-...` Document and `REV-...` Revision names. It proves **initial internal issued SourceAdapter reads succeed**, but the inherited DOC03 lifecycle preparation and retained-reference verifier refuse those names with `invalid_engineering` before any documentary row/history/receipt effect. The separate withdrawal/supersession source tests deliberately use UUID metadata identities while retaining real DOC02 bytes/extraction; they do not prove actual-native-name lifecycle mutation works.

`source-work/DOC03_NATIVE_NAME_COMPATIBILITY.patch` is an **unapplied proposal**, limited to using existing bounded native-name text validation for `lifecycle.request(document_id)` and `_reference(revision_id)`. Issue/request/event IDs and all exact hashes/authority/approval checks remain unchanged in that proposal. Actual DOC03 source is unchanged. The current DOC03 wire schema also still constrains native-name fields to UUID, including `DcIssuedStandingRequest.document_id`, `DcRequestLifecycleRequest.document_id`, `DcIssuedStandingBody.document_id` and `DcIssueReference.revision_id`, with inherited/propagated fact fields. Therefore the two-line service proposal alone is **not** complete public wire compatibility: coordinated schema/OpenAPI/generated contract corrections and actual-name preparation, independent approval, withdrawal/supersession and replay qualification remain required in the local composition workspace. Internal initial issued reads must not be described as successful public lifecycle mutation qualification.

Observed evidence: source-work/source-actual-native-names.log captures26 passing source host cases; source-work/store-focused.log captures17 passing store/controller host cases. source-work/VERIFICATION.md truthfully distinguishes earlier25/76-case tool-output transcriptions, earlier fixture failures, and the subsequent captured actual-name result. These were read, not rerun by this reviewer. Root's final85-case affected gate is pending at this note update; no final-gate pass is inferred.

## Qualification and limits

Provider lane separately records19 passed host protocol checks using injected transports and one loopback stub in providers-work/MANIFEST.json. Root logs reviewed report19 service cases, then22 with concurrency/closed-checkpoint cases; these are successive host runs, not additive distinct counts or native proof. The reviewer did not rerun them. SourceAdapter tests were read, not executed by this reviewer.

No connected Ollama/Qdrant/model, native installation, worker execution or production performance is qualified. Model digest verification is provider-reported identity, not remote attestation or an atomic tag fence. Cancellation/lease expiry do not terminate an in-flight provider call; late cancelled writes remain derived orphans for bounded reconciliation and cannot activate via a stale CAS. Reconciliation is a bounded sweep, not immediate proof of global emptiness. Canonical byte/page reads and source rechecks can multiply I/O substantially at configured maxima; admission bounds do not imply a latency/load result. Native READ-COMMITTED behavior, concurrent revocation and later actual provider/reconciliation/permission-hook qualification remain local-owner work.

## Observed source hashes

Final bounded review update UTC: 2026-10-17T13:22:32.795632+00:00

These9 current source hashes replace the earlier observation. Root owns the eventual final source freeze.

| Path relative to cipher_aec | SHA256 |
| --- | --- |
| semantic_index/contracts.py | `f7914a19fdd3e69171bcab53b76fe5d68834d6231f03f8fb84b1a2e921d34f7f` |
| semantic_index/service.py | `649111e5265aaba61eea2218c701246ce851937fa05cd79fadfbac915cf52f17` |
| semantic_index/store.py | `94986abf978cb7be077cd5b00e865a74d1c38941150a4f85063bb21f68d51a9a` |
| semantic_index/configuration.py | `617307983bb6a7a5ca143da1e4af69d7afee72e96ede34d494eee3279d38a49d` |
| semantic_index/api.py | `dcaac7bc98e2af53d168889cd6afd1534b17ec6a640ff7923196abfa8f286d1e` |
| semantic_index/worker.py | `614ca8f3d7836294e8fd1876acd818d320452ad545abc4c6aa644dd6f2e6dbd9` |
| cipher_semantic_index/doctype/cipher_semantic_corpus/cipher_semantic_corpus.py | `fc7f60633bf1437d7f60192d0bafc0c9f761c547b8c6669da60dcfcaa63fff7f` |
| cipher_semantic_index/doctype/cipher_semantic_corpus/cipher_semantic_corpus.json | `0d2c75e5b960ed51d7a3afb81fd778813919d91a834c2222e0b64ab288d9d572` |
| document_control/semantic_source.py | `f1f959095471a3f70895253b7e070748c464fcaa27ba1d9b35241162b7541e66` |

| Supporting artifact | SHA256 |
| --- | --- |
| workspace/apps/cipher/docs/framework/fragments/doc04/COMPOSITION.md | `cfe4b3bdd135bdebd4f9692fa636e576945dd31de4f9da394637c7f1f01e6141` |
| workspace/apps/cipher/docs/framework/fragments/doc04/shared-additions.json | `080da573ff6acb8e79ed7b4a7446614ee03ca16cc86299cbc19bfbfaacf1f194` |
| source-work/DOC03_NATIVE_NAME_COMPATIBILITY.patch | `bf93fb71ef384cb14e364d8df921f567c129af098d783ef5554828467beddb29` |
| source-work/source-actual-native-names.log | `4fef8ec59077f0418b01a4769fa095dabe4b4dccd90872a6d72393ad07ebc154` |
| source-work/store-focused.log | `308f6480e23f5d03182356a6ac540aef6f6b6d4aeb14fd2934608ad5f76e65a6` |
| source-work/VERIFICATION.md | `d2a84eb908d2bb322cd3e810cbce0c5cdfc20e4c382f1eeac5653983a22d2b4f` |
| workspace/apps/cipher/platform/apps/cipher_aec/cipher_aec/tests/test_semantic_source.py | `f4405b1d6bbf5627882c3bc4ad8b483ba9a76ff0bf48900d08d3a6f9504304dd` |

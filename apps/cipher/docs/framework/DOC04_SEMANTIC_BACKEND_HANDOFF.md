# DOC-04 bounded semantic backend source handoff

Base: `9d937ae1e0c10bb989e8c59f494e2998e41a8a43` (immutable DOC03 backend).
Repository: https://github.com/sasolutionspmp-oss/SA-CMS-PRO
Publication branch: `cipher/doc04-semantic-backend-20261017`.

This is a host-qualified source candidate for local composition. It is not
connected Ollama/Qdrant, native Frappe/worker, HTTP/UI or production acceptance.
The exact published SHA and Git tree are recorded by remote readback outside
this commit to avoid a self-referential commit hash.

## Implemented

- Real optional Ollama `/api/tags`, `/api/show`, `/api/embed` and Qdrant REST
  collection/query/upsert/delete/scroll clients. Pinned model manifest, capability,
  dimensions, protocol, finite vectors, closed metadata and bounded HTTP checks.
  No model pull, collection creation, retries hidden inside clients or fallback.
- Explicit Company or Project corpus. Canonical working-head, current issued,
  and independently approved exact adopted sources. One owning Company; current
  original and target ACLs remain separate. Adoption retains original revisions.
- Actual DOC02 bytes, SHA, scan/quarantine, extraction and page citations checked
  through canonical readers. Selected roots need explicit current DOC03 read and
  ingest rights. Existing permission-evidence policies must allow both; no-policy
  evidence follows DOC03 admission. Current recursive policy digests are retained.
- Deterministic Unicode chunks and generation/point IDs. Qdrant stores metadata
  and vectors, never snippets. Fresh canonical text supplies every returned chunk;
  exact ledger/source/revision/page/hash joins reject untrusted candidates.
- Frappe compare-and-swap corpus checkpoint and guarded DocType. Dedicated-worker
  clean transaction checks, soft leases, before/after authorization, checkpointed
  batches, atomic generation activation and stable uncertain-write replay.
- Query rechecks after external calls and before return. Revoked, superseded,
  changed, quarantined or inaccessible sources cannot supply text. A failed cleanup
  retains exact IDs. Bounded reconciliation retires stale corpora, retries deletes
  and removes late orphan writes without deleting IDs owned by live generations.
- Closed opt-in API dispatcher, isolated schema and queue-worker entry points.
  Global registration/abilities/hooks/schema/deployment remain separate fragments.
  No existing baseline file, Task API, product UI or Ricky adapter is modified.

## Bounds and recovery

Full explicit rebuilds, not incremental/global discovery: at most 16 sources,
128 pages/source by default, 200,000 serialized extraction characters/source,
20,000 characters/page, 10 MiB/source bytes and 1,024 total chunks. Chunks are
1,024 Unicode codepoints with 128 overlap; provider batches are at most 16.
Questions are at most 4,000 characters; results at most 16. One reconciliation
call deletes at most 100 known IDs plus at most 50 orphan hints. Follow its cursor.
Checkpoint admission is 32 rebuild receipts and 8 MiB; archival beyond that bound
is not implemented. A new profile has a separate corpus and requires separate
cleanup of the prior profile. Limits are admission rules, not throughput claims.

Pending/running/retryable jobs block another rebuild until resumed or cancelled.
The original current user/person resumes the same operation UUID. Unknown upsert
replies repeat exact point IDs. Source or authority changes reject staging work;
the prior generation remains usable only while its own current checks pass.
Cancelling or retiring a generation removes it from query admission immediately;
provider deletion may remain pending. Expired workers are not forcibly terminated;
late writes remain nonauthoritative hints and reconciliation removes them.

Every native checkpoint read/write requires verified MariaDB session
READ-COMMITTED. Unsupported or unverified isolation refuses semantic work; the
code never changes isolation or commits another request's writes. Durable mode
requires the private dedicated-worker context and zero prior transaction writes.

## Verification and evidence

`evidence/r3/doc04-semantic-index/05-doc04-final-host.log`: **85 tests passed**
in one final combined run: 19 provider protocol, 23 service/recovery, 26 canonical
source and 17 actual store/controller logic tests using explicit host doubles.
Tests cover uncertain writes/restart, revoked rights before/after provider calls,
changed authority, exact canonical source joins, supersession, cleanup failure,
parallel cleanup, stale provider payloads, lease recovery and native projection
tampering. Original/intermediate results and fixture corrections are preserved.
Source-work verification also records 76 earlier composed source/regression cases;
that is a transcribed prior run, not an additional fresh final suite.

SOURCE_SHA256.json binds all owned source/fragments and this handoff.
QUALIFIED_SOURCE_INVENTORY.json binds the 918-file composed DOC03 baseline plus
the new owned runtime/tests. BASELINE.json identifies that baseline: its DOC03
shared fragments were composed for host tests; the local Task/trial overlay was
not applied. No baseline source hash changed. EVIDENCE_SHA256.json hashes retained
logs/review/reference material, excluding its own inventory and manifest.

## Remaining local integration and known dependency gap

1. Compose `fragments/doc04/COMPOSITION.md` and both permission hooks before making
   the new DocType/API available. Compose DOC03 shared fragments first, then merge
   local Task/trial changes once and regenerate global contracts once. There is
   no enabled scheduler, API whitelist or automatic cross-scope event fanout here.
2. **Inherited DOC03 naming gap:** actual DOC02 uploads mint `DOC-`/`REV-` names.
   Initial issued-source reads work with those names. DOC03 lifecycle withdrawal
   preparation and retained lifecycle-reference validation currently demand UUID
   document/revision names and refuse them safely. The new regression preserves
   this exact gap; its temporary UUID lifecycle fixtures are not claimed as native
   compatibility. `DOC03_NATIVE_NAME_COMPATIBILITY.patch` is an unapplied two-line
   local proposal; documentary issue/event UUID checks stay strict. Existing
   public DOC03 standing/lifecycle schema fields also require UUID native names;
   DOC03_NATIVE_NAME_SCHEMA_FOLLOWUP.json identifies the schema/generated follow-up.
   The two-line internal patch alone does not qualify the wire path. The local
   writer must compose/review and qualify actual upload→issue→withdraw/supersede→
   query refusal/deletion. Frozen DOC03 implementation is unchanged in this ref.
3. Qualify real Frappe migration, permissions/export denial, after-commit enqueue,
   clean worker transactions, CAS/restart and concurrent revocation visibility.
4. Verify the local model tag, actual digest, embedding capability/dimension,
   Ollama version/protocol and Qdrant version/collection before enabling config.
   `nomic-embed-text:latest` and 768 dimensions are context, not verified settings.
   Run actual embeddings, search, revocation, deletion and restart recovery locally.
5. Add the opt-in Ricky retrieval integration after native/provider acceptance;
   keep canonical page citation hashes distinct from chunk hashes/spans. No local
   Ricky adapter changes or AI-produced engineering/commercial authority are added.

Provider-reported manifest identity is not remote attestation; mutable tags cannot
be atomically fenced through these HTTP endpoints. Socket/read bounds do not prove
a hard DNS/process wall-clock deadline. Ranking quality, performance, event fanout,
retention/archival, backups and operational deployment remain local qualification.

Cloud actions were limited to source, host tests, review and Git preservation.
No containers/runtimes restarted, providers written, deployment performed or award,
procurement or finance work executed. The prior blocked award boundary remains.

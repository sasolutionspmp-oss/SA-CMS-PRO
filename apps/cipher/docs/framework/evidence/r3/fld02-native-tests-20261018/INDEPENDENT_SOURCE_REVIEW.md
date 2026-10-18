# Independent source review — prepared FLD-02 native/HTTP probes

Status: source review completed; no unresolved blocking source issue identified
in the reviewed candidate hashes below. All native, HTTP, database, site, runtime,
provider, model and network cases are **UNRUN**. No application modules were
imported and no dependency was installed for this review.

## Bound sources

- Runtime composition baseline: `repository/`, source
  `310a946bd34d06c9f7c1a3d96ab7274733142cd9`.
- Offline contract implementation: `contract-source/`, source
  `392a19f8c01b4253a5aaeaa99878408d394dc9cb`.
- Frappe reference: public `v16.52.0` IntegrationTestCase source retained as
  `frappe16-integration-test-case-reference.py`; SHA-256
  `ad0922ab07d0fbac1efd16d875979e72850272e097d0fb0a26be3a46878fa0a8`.
  This is a source reference, not proof of the installed image.

## Fixture and transaction findings

Frappe 16.52 IntegrationTestCase.setUpClass calls its superclass, initializes the
site, constructs test dependencies, commits, and registers class rollback and
local-context cleanup. Its per-case setUp/tearDown does not provide an explicit
per-case rollback. Candidate tests therefore need their own per-case savepoint
and unconditional cleanup, including cleanup on setUp failure. They must call
super().setUpClass/setUp/tearDown and leave the IntegrationTestCase class and its
methods unmocked.

The existing FLD-01 test seeds synthetic fixtures after its case savepoint. Do not
copy that pattern. seed_synthetic creates users/company and can run the ERPNext
fresh-site fixture installer; it does not directly call after_migrate. Seeding,
migration, indexes, setup and dependency preparation belong before any per-case
savepoint. No DDL, full commit/rollback, migrations, site configuration writes or
password reset belongs inside a case. Generic rollback may erase all savepoints;
normal error probes should call domain services rather than endpoint wrappers,
whose POST error path deliberately calls a full rollback.

Use dedicated synthetic.example identities with explicit Project/field/document
duties. The stock seed deliberately excludes FIELD_ABILITIES and
DOCUMENT_CONTROL_ABILITIES from blanket primary grants. An alias must bind to the
same canonical Person. A separate reviewer/superintendent must be another Person
with the needed current project.read/field.read duties. The actual source rejects
unknown abilities; a role title or Administrator does not replace duties.

Uploads use real Frappe private File storage. Savepoint database rollback alone
does not establish disk-byte cleanup. Candidate code must track paths before
rollback and delete only bytes created by that case; it must never remove a
preexisting deduplicated File path. Guard paths inside the site's private files
directory, avoid symlinks, preserve original bytes and do not bypass source guards
by deleting canonical records through normal application APIs.

## Canonical protocol checks

Device registration UUID and capture UUID are distinct concepts. The capture UUID
is reserved for the original field business command; metadata stage/discard/
resolve operation UUIDs must be distinct, and apply operation_id must equal the
capture UUID. Shared command receipt name is the digest of canonical Person plus
operation UUID. Exact command, request hash, company/project/scope, state and
result digest must agree. Counts alone do not establish identity or idempotency.

FLD-02 business_request produces exactly FLD-01 create/revise payloads. Successful
apply must compare the full original canonical receipt/result and raw native
header/revision/quantity facts, with operation metadata normalized only where
replayed flags intentionally differ. Retry after a successful but unknown HTTP
response must reuse the durable original UUID, not invent a replacement.

Staged daily captures freeze superintendent user-to-Person attribution in
participant_people. Rebinding this login to a different Person must fail with
field_identity_changed before new business effects. Same-Person aliases can read
or apply the same owned capture using current duties. A different Person cannot
access it, even with equivalent scope abilities. Current field.read is required
for every receipt path; new writes additionally require field.write and an open
Project. Original committed field receipts remain reads after field.write loss,
device revocation or Project closure if current source/read duties remain valid.

Current exact source bytes/hash/lineage and rights are independently checked.
rights.require returns source_rights_denied for denied read/ingest, and
source_rights_required when no current authored rights revision exists. Permission
evidence must be a separate retained authored artifact. New use of a non-head
source gives stale_field_source; inspect projects this as source_changed conflict.
An exact revise base must bind record, immutable revision and original digest;
head/status drift projects base_changed or record_state_changed. Resolution uses
a fresh capture UUID linked bidirectionally to the superseded original and does
not overwrite original business facts.

Explicit discard clears only the offline envelope. Staged becomes discarded;
committed and superseded retain their statuses, receipt pointers and lineage and
record a redacted event. Summary metadata receipts remain their original result;
get/inspect return the current projection. Summary receipt authorization does not
read revoked source text. Full original receipt/read paths still require current
read/source rights. Canonical business records and physical source Files are not
deleted by discard.

Atomicity requires exact before/after snapshots of field tables, shared receipts,
history and offline projections/events around a deliberately late failure. A
fault injection may wrap one late offline write while delegating prior real
writes; it must not mock IntegrationTestCase, Frappe DB, repositories, source
rights, identity or the shared receipt writer. Outer rollback and nested command
savepoints must retain their intended scope.

## HTTP source contract

Routes must be the existing /api/method/cipher_aec.field_offline.api.* RPCs.
Any shared receipt lookup uses the existing cipher_aec.api.v1.operation route and
its composed authorization dispatch. Auth comes from operator
provided session/token credentials, never fixture passwords or secrets in CLI
arguments, receipts or logs. Interactive cookie POST needs actual CSRF; do not
claim a domain envelope proves Frappe authentication/CSRF middleware behavior.
Idempotency-Key and payload operation_id must agree. Responses are double-wrapped
by Frappe message plus Cipher envelope. Persist UUID/request material with strict
filesystem permissions before network work, and persist an unknown-response
barrier before each mutation. Ambiguous/in-flight writes prohibit any new UUID
until readback/retry of the same request resolves them. Never follow redirects
with credentials or log response/source payloads, cookies, tokens or CSRF values.

## Candidate review outcome

Directly reviewed the complete dedicated fixture, 18 native test methods, native
coverage notes, optional HTTP driver and its frozen schema/example/source pins.
Independent AST parsing succeeded for the three candidate Python files; JSON
parsing succeeded for the bundled JSON artifacts. Every HTTP source-input hash
matched the pinned local source, and the bundled schema was byte-identical to the
frozen FLD02 schema. This reviewer did not import or execute candidate/application
modules, native tests, a driver command, a DNS lookup, an HTTP request or a site/DB
operation. AST validity is not a passed native or HTTP case.

The fixture is a separate Administrator pre-suite preparation operation and grants
no duties. Cases call only its read-only verifier. The suite derives directly from
the real IntegrationTestCase without mocks or patches, establishes its own
savepoint after superclass setup, registers cleanup before its first write,
restores the complete prior session/user/request context, and asserts owned
Projects/revisions/File rows and duty/binding changes rolled back. Byte cleanup
uses per-attempt random filenames, exact content hash/size, a private-directory
boundary, no symlink deletion and no surviving File reference. N18 prepares a
separate still-referenced sentinel before a nested savepoint and checks that its
bytes survive owned-row/orphan cleanup.

All 18 cases were checked against actual field/offline/governance/document-control
source. The canonical-success helper independently reconstructs the FLD01 request
hash and compares exact native result_json/result hash, receipt identity/scope,
retained Field revision/header/quantity facts, photo/source metadata and offline
commit pointer. N14 distinguishes the historical receipt from actual subsequent
review/acceptance/amendment and redaction. Negative cases cover original login
disable/rebinding, another Person/scope, revoked device/rights, stale capture token,
changed source/current base, UUID collision, duplicate original quantity and native
writer bypass. No replacement production writer or runtime configuration is added.

The driver uses the actual session route and exact existing RPC signatures,
verifies the session Person/user/synthetic mode and current CSRF, sends the saved
UUID as both Idempotency-Key and operation_id, and admits exactly one Frappe
message wrapper. It validates frozen response shapes including false no_effects
values, then compares the original header/revision/Person, authored definitions,
photos, exact source references, quantity decimal strings/lineage, predecessor and
amendment reason with the sealed command. The clean original result hash excludes
only operation replay metadata and remains a tombstone after local discard.

The journal uses owner-only files/directories, a process lock, atomic replace and
file/directory fsync. Every POST's exact body/hash/UUID and unknown state persist
before network transmission. An unknown outcome blocks fresh commands; successful
matching get/inspect observations permit only one explicit unchanged-request retry
or prove an original committed receipt/effect. Error, denied access, missing
capture and unavailable bytes never establish noncommit. Local discard erases
payload copies while retaining UUID/hash tombstones and unknown barriers.

The final transport supports loopback IPs and restricted localhost names,
including the designated cipher-trial.localhost trial origin. Each connection
resolves once, rejects any nonloopback answer, connects directly to a returned
numeric sockaddr and checks the connected peer. Original Host, cookie origin and
HTTPS SNI/trust behavior are retained. Proxies, redirects and tunnels are refused.
Malformed/truncated HTTP exceptions and other failures emit fixed diagnostics;
credentials, CSRF, cookies and raw payload/response text are not logged or put in
the journal.

## Review findings resolved before this snapshot

1. The first HTTP receipt check hashed structurally loose results. It now validates
   the frozen full response and independently compares sealed documentary facts,
   quantity/source/record lineage and original clean result hash.
2. HTTPException variants from open/read could escape fixed diagnostics. Both
   transport boundaries and the final diagnostic boundary now handle them.
3. Frozen schema format uuid was initially unsupported. Canonical UUID format
   support is now separate from envelope/capture UUIDv4 enforcement.
4. The native owner get_list assertion initially expected an empty list despite
   having no System Manager DocType role. N11 now explicitly expects the native
   PermissionError; exact private hook installation remains a prerequisite.
5. Local discard initially removed the prior clean original-result comparison.
   A permanent hash-only tombstone now detects a changed later original receipt.
6. HTTPS handler portability was checked; the final handler passes only context,
   with no removed check_hostname constructor argument or private attribute.

## Limits that remain UNRUN

Native/site/DB/HTTP/authentication/CSRF/locking/isolation/restart behavior and
filesystem durability remain **UNRUN**. Hook presence is source admission, not
executed elevated-user read/export-denial qualification. N16 exercises a native
business refusal after a preliminary header write when eventually run; a naturally
occurring late failure after canonical receipt creation, independent-connection
concurrency/deadlocks and process restart require the separate local proof plan.
N17 snapshots row identities plus native modified/docstatus for finance/integration
effects; it does not audit every historical financial field or detect arbitrary
unversioned SQL changes. All actual File callback/rollback behavior remains local
qualification work.

The optional driver intentionally requires the original registration login, has
no alias-profile switch, register/revoke/resolve workflow, document-byte fetch or
encrypted browser vault. Inaccessible recovery stays blocked rather than being
called uncommitted. Its private plaintext artifacts and later operator execution
are explicitly distinguished from product acceptance. No provider/model/award or
dependent procurement/finance action was performed or routed elsewhere.

## Reviewed candidate SHA-256

| Candidate | SHA-256 |
| --- | --- |
| native_tests/fld02_native_fixture.py | 0896c86523cbda509115b5aa134fcb78f9a0ea1ec3173c61d3279ee24352bf95 |
| native_tests/test_field_offline_native.py | 123343684cc5d44294f15db875338785451f16e884d549c4f19624a715515905 |
| native_tests/COVERAGE.md | 8c0d216cb50024853048194663345d9eed9b12122bedb72c3e260f4649de3546 |
| http_driver/fld02_http_driver.py | 7eb65e0f1f28ed9eda7d41b9c7346dfe282de763268b4eba9a4655bd0740b600 |
| http_driver/frozen-api-v1.schema.json | 99e32521ba518224b327cdeb0643e5d91342406a41ee8e24ec617953d4602d84 |
| http_driver/README.md | 536fea627783ad204c2aae957851137abd7d90f5ad4df47e1e9024ef1e19df7e |
| http_driver/example-envelope.json | e3dcc080cf09e511cbe07359b47254ebc64a44383196835ea1075e8043d59681 |
| http_driver/SOURCE_PINS.json | 2eea6bdde1f5b9587c6cd636ee17f321aefb04f8a847c432a7e82a05d87c26c2 |

Review disposition: suitable as prepared source for the declared local
qualification workflow; no native/site/HTTP pass or execution permission is
claimed by this review. Any candidate byte change requires rebinding this table
and reviewing that change before publication of the bound evidence package.

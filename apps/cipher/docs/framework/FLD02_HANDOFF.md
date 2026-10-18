# FLD-02 source handoff

Repository: https://github.com/sasolutionspmp-oss/SA-CMS-PRO
Exact base: `0147603655624c3ad66ef73f6921a06805abff9a`.
Dedicated publication ref: `cipher/fld02-offline-backend-20261017`.
The published full SHA/tree and readback proof are returned separately to avoid a
self-referential commit hash. Earlier DOC03/04 handoff refs remain unchanged.

## Source readiness

Implemented: closed immutable offline envelopes; owned device registration and
revocation; explicit staging/inspection/application; durable private Frappe capture
and event projections; original canonical-person FLD-01 receipt lookup; source/base/
standing conflicts; fresh linked replacement UUIDs; explicit payload discard;
same-Person alias handling; frozen superintendent Person bindings; exact decimal,
quantity capture and canonical document lineage; atomic late-failure rollback;
and eight owned API/schema contracts with private native controllers.

No reconnect scheduler, background business replay or financial action exists.
The source changes only new field_offline/cipher_field_offline files, three tests
and new documentation/fragments. Existing FLD-01, shared governance/API/schema,
Task, product App.tsx/generator, Ricky and deployment source are unchanged.

`FLD02_OFFLINE_CAPTURE.md` defines the behavior, privacy/retention boundaries and
reconnect/discard paths. `field_offline/device-policy.json` is a future client
adapter contract, not implemented browser persistence or encryption. Server
envelopes are private plaintext JSON. Only exact existing canonical source refs
are admitted; new offline binary attachments remain unsealed/unimplemented.

## Verification

Final combined host run: **74 passed** (29 existing FLD-01 plus 45 FLD-02:
16 closed-contract/schema, 18 service/recovery, 11 actual persistence/controller
logic checks). Exact command/stdout are retained in
`evidence/r3/fld02-offline/08-fld01-fld02-final-host.log`.

These execute real FLD-01/02 service/controller/repository code with explicit
Frappe database/session/source/trust doubles. They are not native locking,
transaction, restart, permission-hook, HTTP, browser-vault or human-trial evidence.
Canonical duplicate receipt behavior is reused rather than reimplemented.

The first root service fixture omitted a mocked effects guard; its failure is
retained. A persistence-fixture update-call mismatch is retained separately.
Independent review found and resolved superseded-copy redaction and ordered
participant-lock recheck defects. A later root regression proved that the earlier
source silently re-resolved a staged superintendent login to a different Person;
the failing-first/fixed logs are retained as 06/07. Server-staged Person snapshots
now reject that change before new field effects. Final review is source-hashed.

## Local composition and unresolved limits

Apply the fragments in `fragments/fld02/COMPOSITION.md`: module/index installation,
all native read/query/export-denial hooks, offline summary receipt and device
history dispatch, eight route/schema additions and one shared type generation.
Do not overlay this lane's files onto unrelated active runtime/shared files.

Before acceptance, the local lane must prove actual migration/native controllers,
concurrent duplicates and current source/identity revocation, outer savepoint/
shared receipt rollback, restart and unknown-response recovery, authenticated
CSRF/idempotency/alias HTTP behavior, and the browser privacy/persistence journeys.
Actual native/provider/READ-COMMITTED qualification remains separate and local.

The capture UUID is reserved by this protocol, not by a new global namespace lock.
An unrelated same-Person canonical command using it is detected as a conflict
before field effects. Committed original receipts remain distinguishable and
readable under current read access even when a new write is forbidden. Device
hardware attestation, cross-device queue transfer, global retention/secure erasure,
and browser storage/crypto/performance are not implemented or claimed.

Explicit server discard requires current Project write access and can redact its
private offline copy without reading a content-rights-revoked source. It creates
no field/domain effect and does not delete canonical business records or backups.
Original metadata receipts retain their original status; get/inspect report the
current capture projection. Client UI must label that distinction.

The cloud lane performed source/host checks and Git publication only. No runtime,
database, dependency install, provider, deployment or production action occurred.
Automatic approval review previously rejected award execution for cybersecurity
risk. No retry on another route/host occurred; dependent procurement/finance
rollout remains blocked.

## Evidence binding

SOURCE_SHA256.json lists the exact new code/tests/docs/fragments.
QUALIFIED_SOURCE_INVENTORY.json binds the unchanged checked-out custom-app baseline
plus this package. BASE.json pins the fetched checkpoint. EVIDENCE_SHA256.json
hashes retained logs/review/context records, excluding itself and MANIFEST.json.
MANIFEST.json records qualifications and inventory hashes. The final remote
readback verifies parent, full tree, changed-path set and every published byte.

# FLD-02 — Offline capture source contract

This package adds durable server-side capture envelopes, device registration,
explicit apply/conflict resolution and receipt recovery on the reviewed FLD-01
source. It is a host-qualified backend candidate. Browser IndexedDB/encrypted
vault/service worker, native migration/concurrency, HTTP/session and human trial
qualification remain with the local integration lane.

## Identity and effects

A device registration is owned by one canonical Person in one Company/Project.
Its UUID identifies a registration, not physical hardware or a bearer credential.
Every server request needs a fresh current identity and Project duty. A current
alias bound to the same Person can synchronize; the envelope retains the original
registration user, while FLD-01 records the actual signed-in author of the apply.
Another Person cannot adopt a registration or replay its capture. Device
revocation blocks new staging/application; readable original committed receipts
remain separately authorized by current Project/source read rights.

Staging freezes the canonical superintendent Person resolved from the declared
login, with current field-read duties. Inspection/apply refuse a changed binding
or revoked participant access; participant IDs are rechecked before Project/source
locks and never silently re-resolved to a different Person. Before first staging,
offline participant attribution is unverified. A changed/revoked declared login
requires explicit discard and a newly sealed capture; no alias substitution edits
the original payload. Historical committed receipt reads remain separate.

Each sealed envelope has an immutable UUID and SHA-256, declared offset timestamp,
original actor attribution, device, exact scope, and a closed FLD-01 create/revise
payload. It admits no review/accept/acknowledge/award/financial command. Times and
device identity are authored observations, not attested offline authentication.
Exact positive decimal strings and canonical document source references pass
unchanged to FLD-01. No float conversion, source URL or queued binary upload is
accepted. A revision includes the exact original immutable base ID/digest and
expected header digest, preserving both content and standing conflicts.

The capture UUID is reserved for that original FLD-01 business command. Staging,
device, discard and resolution operations use separate canonical-person operation
UUIDs. Changed payloads under either an original operation UUID or capture UUID
conflict. The stored capture identity is Person/capture UUID, so changing devices
does not evade capture duplicate checks.

## Reconnect and explicit resolution

Reconnect never applies a business command automatically. The client signs in,
selects the exact profile/scope, reads or stages its chosen envelope, then inspects
the capture. Inspection returns ready, conflict, committed, discarded or superseded.
It does not create a field event. Ready is an observation, not a cached grant.
Explicit apply reacquires canonical people/identity/Project locks and current
source/rights checks, then invokes FLD-01 with the original capture UUID.

New field writes require current `field.write` plus `field.read`, an open Project,
an active owned device and exact source read/ingest rights. Current revoked duties,
source permissions or unavailable/quarantined bytes block the effect. Historic
base/source content does not authorize new use. The unique outer savepoint covers
the canonical field command, its shared receipt and the offline projection/event;
no nested offline command wraps the field writer and no service commits occur.

An unknown response is recovered by inspecting/retrying the original capture UUID.
A readable original canonical receipt is returned before checking prospective
current base versions; it is explicitly marked replayed and is not a new business
command. Later field successors never rewrite that original result. A canonical
receipt already committed through the same exact field request is authoritative
even if a staging projection has not linked it; inspection reports committed and
apply returns the original without writing a repair or another business record.
An unrelated canonical command occupying that UUID causes a conflict.

A stale base, changed standing or superseded source requires an explicit replacement
envelope with a fresh UUID and a reason. The original remains linked as superseded;
the replacement must target the same family/action/record, declare the current
base and current sources, and is only staged. It needs its own explicit apply.
There is no merge, automatic last-writer-wins, payload edit or silent fresh UUID.
Rights denial remains a denial rather than a conflict permitting source access.

## Persistence, privacy and discard

Three private Frappe DocTypes store device registrations, capture projections and
immutable capture events. Controllers require exact write plans and an admitted
service context; generic native writes, trusted-write alone, delete and rename are
denied. Envelopes are at most 256 KiB; existing FLD-01 source/count bounds apply.
The server stores private plaintext JSON under current access controls, not an
encrypted-at-rest browser vault. Native permission-denial hooks must be composed
before exposing this module. Retention/export/backup administration is unqualified.

`device-policy.json` is the required future client adapter contract: separate vault
partitions by site/Company/Project/Person/registration, explicit encrypted persistence
opt-in, no plaintext localStorage or stored auth/provider credentials, finite profile
expiry, and truthful quota/storage failure. Logout/profile changes or revoked access
must lock/purge decrypted views and keys; another account never inherits a queue.
These are requirements, not claims that browser storage or encryption is implemented.

Local discard must remove local payload/key material without requiring a server
request. Server discard is an explicit current-Project `field.write` command with
an expected capture version. It may remove an offline copy without reading a source
whose content rights were revoked; it never invokes a field/domain writer. It does
not bypass revoked Project/write rights. It keeps the original envelope hash, actor,
audit lineage and any business receipt. A committed record stays committed; a
superseded capture stays superseded. Redaction cannot restore or edit a payload and
does not erase backups, original field records or other retained evidence.

Sealed captures reference existing canonical document revisions only. New offline
camera/binary drafts remain unsealed until a future client explicitly uploads through
DOC-02 and creates a newly sealed capture. Replacing temporary attachment references
under an existing capture UUID is forbidden. Device loss/revocation currently requires
an explicit readable/discarded old queue and new registration/capture; transfer or
hardware attestation is not implemented.

## Local composition and acceptance

Use the separately identified FLD-02 fragments. Register the module and private hooks,
add indexes, dispatch `offline.field.*` summary receipts before generic field handling,
merge the eight route/schema entries and regenerate shared contracts once. Existing
five FLD-01 duties are reused; no automatic duty grant or worker/scheduler is added.

Required local evidence: native migrations/constraints and native JSON denial;
two concurrent reconnects with one canonical field result; real transaction rollback
and restart/unknown-response recovery; independent actual aliases/identity revocation;
source/base/current-rights races; authenticated CSRF/Idempotency-Key handling; original
receipt vs new-command UI; and browser vault persistence, quota failure, discard,
profile switching and revoked-access cleanup. Host doubles do not establish these.

The package imports no financial/commercial/award writer and changes no online field
implementation. No runtime/dependency/provider action was performed by this lane.
The prior rejected award execution remains blocked on every host/route, along with
dependent procurement/finance rollout.

# Optional FLD02 loopback HTTP diagnostic — PREPARED, UNRUN

Source preparation only. This driver has **not** been executed, imported, connected
to HTTP, authenticated, or tested against a native site. No application, site,
database, middleware, credentials, provider, model or dependency configuration was
changed. Static parsing/compilation is the only driver verification permitted in
this preparation lane. The root evidence package owns further review/publication.

The source is bound to the actual `310a946b` transport/session sources and frozen
`392a19f8` FLD02 contract. `SOURCE_PINS.json` lists exact source-file hashes. The
bundled schema is byte-identical to the frozen source, and the driver rejects schema
hash drift. It imports Python standard-library modules only, never Cipher/Frappe
application code. Python on Unix with `fcntl`, `O_NOFOLLOW` and directory fsync is
required; actual filesystem durability remains unqualified until a separate trial.

## Deliberate scope

The journal is for one loopback origin, Company, Project, canonical Person,
original registration user, already registered device UUID and finite expiry. `init`
only creates that local profile. Device registration must already exist through an
authorized workflow; this driver does not register/revoke devices or resolve capture
conflicts. `ROUTES` pins all eight exact `cipher_aec.field_offline.api.*` signatures;
only `stage_capture`, `get_capture`, `inspect_capture`, `apply_capture` and
`discard_capture` are callable. It also calls the actual read-only
`cipher_aec.api.v1.session` route. No token API, login, custom identity header,
password, financial command, server configuration, background task or automatic
replay/apply exists.

A conflict is a stop. This driver cannot properly guide original-target/current-base
resolution, so it offers no resolve command. Never edit a sealed capture or reuse
its UUID for different content; use a qualified resolution workflow with a separate
replacement UUID and explicit lineage. Aliases supported by the server are narrower
here: this diagnostic requires the exact original registration login and Person.

## Existing session inputs

Arrange a separately authorized **existing synthetic** session on a local reverse
proxy/site that accepts the exact loopback origin. No acquisition steps execute
here. Literal loopback IPs, `localhost` and explicit `*.localhost` names such as
the existing `cipher-trial.localhost:18890` origin are allowed. Every connection
resolves the admitted host once, requires **all** answers to be loopback, and
connects directly to a checked numeric socket address without resolving again.
The requested hostname, Host header, cookie domain and HTTPS SNI/certificate checks
remain intact. External hosts, mixed loopback/external DNS answers, URL
user/password, redirects and HTTP proxies are refused. This source preparation
performed no DNS lookup. Secure cookies need HTTPS; no TLS-verification bypass is
provided. These restrictions are an operator diagnostic boundary, not production
SSRF qualification.

Use an operator-owned private Mozilla/Netscape cookie jar (0600 or stricter), with
an ordinary existing `sid` session cookie scoped to that origin. Prepare a separate
private credentials file (0600 or stricter), exactly two unquoted settings:

```text
COOKIE_JAR=/absolute/private/session.cookies.txt
CSRF_TOKEN=<current value from that same authorized session>
```

This is parsed as data, never sourced as shell code. The driver reads the actual
session GET before every network command, checks `authenticated`, the exact user
and Person, `site_mode=synthetic`, and compares the supplied CSRF token to the
current session response. It then sends that in-memory current token as
`X-Frappe-CSRF-Token` and sends `Idempotency-Key` equal to the immutable
`operation_id`. Cookies stay in memory and are never saved back. Credentials and
session responses never enter the journal or stdout. Do not paste either input
into evidence, chat, source, examples or terminal arguments.

Successful HTTP responses must use exactly one Frappe `message` wrapper around the
pinned Cipher `schema/data/meta/request_id` envelope. Redirects, HTML, recursively
wrapped/bare envelopes, nonfinite/duplicate-key JSON, oversized responses and
malformed/truncated transport responses fail closed. Error output uses fixed
metadata, never raw response bodies or exception tracebacks.

## Prepared operator commands (NOT RUN)

These commands describe a later explicitly authorized trial. Names, UUIDs and
scope values in `example-envelope.json` are synthetic, syntactically valid inputs,
not actual registration/authority claims. Replace them with exact existing
synthetic scope/identity/device details and a new capture UUID **before sealing**.
An empty weather observation, no photo and no quantity need no invented document
reference. The server still checks real current identity, duties and registration.

Create a 0700 private directory whose parent already exists, then initialize:

```bash
python fld02_http_driver.py --journal /absolute/private-fld02/journal.json init \
  --origin http://cipher-trial.localhost:18890 \
  --company 'SYNTHETIC TEST COMPANY' --project 'SYNTHETIC TEST PROJECT' \
  --person SYNTHETIC-OPERATOR --user operator@synthetic.example \
  --device 123e4567-e89b-42d3-a456-426614174000 \
  --expires-at 2026-10-19T00:00:00Z --ack-private-plaintext
```

Choose a finite future expiry at actual trial time. There is no expiry-extension or
profile-rebinding command. Protect the envelope input file with mode 0600 before
staging. Every command below uses the same `--journal` and, except local discard,
`--credentials /absolute/private/session.env` options before its command name:

```text
stage --envelope /absolute/private/capture.json
inspect --capture 123e4567-e89b-42d3-a456-426614174001
apply --capture 123e4567-e89b-42d3-a456-426614174001 --confirm-original-uuid
recover --capture 123e4567-e89b-42d3-a456-426614174001
recover --capture <capture UUID> --retry-operation <saved original operation UUID> --confirm-exact-retry
discard --capture <capture UUID> --server --expected-version <last exact capture_version> --reason 'Synthetic retention trial' --confirm-redaction
discard --capture <capture UUID> --local
```

`stage` canonicalizes once with the actual server's `sort_keys=True`, compact
separators, UTF-8/unescaped Unicode, finite-JSON encoding. The exact canonical
sealed JSON and SHA-256 are stored, then the stage operation gets its own persistent
UUID. The capture UUID remains reserved for the original FLD01 apply. `apply` does
fresh GET get/inspect first and needs explicit confirmation. Ready is an
observation; the server reacquires all current rights/base/source locks on apply.

Server discard accepts the exact version supplied by the operator instead of
requiring a new source-bearing GET. This preserves the server's ability to redact
the offline copy when source read rights were revoked but Project `field.write`
remains valid. It preserves committed business records and original receipts.

## Unknown responses and immutable original receipts

Before each POST, the driver atomically replaces/fsyncs its private 0600 journal,
including exact request JSON/hash/UUID and state `unknown`, then fsyncs the parent
directory. Only after that succeeds can it send the POST. A process lock spans
both journal transitions and network requests. An uncertain outcome, error,
malformed response, or interrupted acknowledgment retains that barrier durably.
Fresh stage/apply/server-discard commands are blocked across process restarts.

`recover` performs successful exact get/inspect reads. Both must match the owned
capture/hash/scope/version and agree on its original canonical receipt. Errors,
404s, revoked rights, changed state during readback and unavailable bytes never
prove noncommitment or clear the barrier. A staged capture found after unknown
stage proves the identical staging effect is present; it is labeled
`effect_observed`, never called the original stage-operation receipt. A redacted
payload similarly proves the irreversible discard effect.

After an unknown apply, an original canonical receipt establishes commitment even
if the current offline projection still says staged. The original header/revision,
Person, sealed definition/photos, exact source references, exact decimal quantity
facts and lineage are checked. A full result SHA-256 excludes only mutable
`operation` replay metadata; that original result hash is immutable. Current
projection standing is printed separately. Expanded source metadata is schema
validated; the driver does not independently fetch document bytes or replace the
server's current source authorization checks.

Only a matching authorized read pair with no original receipt, still-ready staged
capture and the **original** expected version allows an explicit same-UUID apply
retry. A still-retained payload and original version can allow an explicit
same-UUID discard retry. There is at most one resend; no new UUID/version/payload
is generated. The retry itself first durably returns to `unknown`. A second
uncertain outcome stays blocked until a later authoritative commitment/effect
read; it is never reset to obtain more resends. A missing staged capture cannot be
retried based on an opaque 404. A never-sent durable `prepared` request with zero
attempts can be explicitly resumed using the same recovery flags; it had no
uncertain POST to resolve. Nothing is sent automatically.

## Privacy and local discard

This diagnostic is an explicit opt-in **private plaintext test artifact**, not an
encrypted browser vault and not qualification of `device-policy.json`. It cannot
claim authenticated encryption, browser profile/key purging, encrypted offline
capture, quota/restart reliability, hardware attestation, native acceptance or
secure device erasure. Protect the containing directory, host account and backups.
The journal persists canonical documentary content and operation reasons before
local discard; use synthetic inputs only. It never persists auth/provider secrets.

`discard --local` works without credentials, session, expiry check or any HTTP. It
removes all sealed capture and request-body copies from this journal, removes
cached views, and retains only UUID/hash tombstones plus unknown barriers. It does
not mark an unknown server request uncommitted or allow resealing its UUID. A
hash-only original-result tombstone can still detect a changed later original
receipt. Local removal cannot revoke a request already sent. No key material is
created by this driver. Deletion/atomic replacement is not secure erasure; old
filesystem blocks, operator-provided input files, credentials files, backups,
server audit records and committed business records can remain. Manage those
separate source/session artifacts through their existing authorized retention
process. Do not copy this private journal into a public evidence bundle.

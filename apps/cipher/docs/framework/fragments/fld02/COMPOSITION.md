# FLD-02 local composition

Exact source base: `0147603655624c3ad66ef73f6921a06805abff9a`.
Own only the new `field_offline`, `cipher_field_offline`, tests and documentation.
Do not replace existing Task, field, document, Ricky, product or deployment sources.

1. Add the module, migrate three owned DocTypes and install additive indexes.
2. Compose all native list/read/export-denial hooks **before exposure**. System
   Manager DocType read metadata is not a substitute for private native hooks.
3. Dispatch `offline.field.*` shared receipt authorization to the owned callback.
   It must precede any generic fallback. Canonical FLD-01 business receipts continue
   to use their existing `field.*` callback. Add the device history callback.
4. Merge the eight owned route definitions and Fo schema definitions; regenerate
   shared OpenAPI/types once in the integration lane. Preserve normal identity,
   CSRF and Idempotency-Key transport. Apply's key/operation_id is the original
   capture UUID. Other mutation operations use fresh IDs distinct from capture IDs.
5. Reuse existing explicit field.read/write duties; grant none automatically.
   There is no background job, scheduler, alternate field writer or automatic apply.
6. Qualify Frappe transaction/restart and concurrent duplicates/revocation with
   actual people/aliases and canonical source rights, then real HTTP contracts.
7. Implement/qualify the browser adapter separately under device-policy.json:
   encrypted opt-in vault, profile isolation/expiry, truthful save/quota failures,
   selected reconnect review, original receipt display and explicit discard.
   No IndexedDB, service worker or offline binary upload exists in this source.

The unique apply savepoint encloses FLD-01 and its offline receipt projection.
No code commits another request's transaction. Namespace-wide capture reservation
is not installed: an unrelated use of that UUID is detected as a conflict, never
rebound. Native locking/isolation/exactly-once and browser durability remain local
acceptance work. Preserve the blocked award and procurement/finance boundary.

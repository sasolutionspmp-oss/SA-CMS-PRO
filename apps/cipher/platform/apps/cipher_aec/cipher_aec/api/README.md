# api: planned module boundary

Status: planning skeleton only. Do not interpret this directory as an implemented Frappe module.

## Ownership

Same-origin route adapter, session/capabilities, OpenAPI schemas, error envelopes and generated-client contract.

## Interfaces to implement

CommandContext, typed read presenters, route policy table.

## Required invariant

No arbitrary DocType dispatcher; no business rules duplicated in transport.

## Implementation sequence

1. Read the master framework and the `API-01` work package family.
2. Verify standard ERPNext/Frappe fields and hooks on the locked runtime.
3. Add only the custom DocTypes, fields and indexes needed by the current slice.
4. Implement server invariants and transactional commands, then scoped reads/API schemas.
5. Connect the unified UI and Ricky tools to those same services.
6. Exercise positive, denied, stale and recovery cases appropriate to this module; record actual evidence.

Source of truth: [backend framework](../../../../../docs/framework/BACKEND_FRAMEWORK.md), [backlog](../../../../../docs/framework/EXECUTION_BACKLOG.md).

No runtime dependency, controller, schema, route or database has been created in this planning stage.

The explicit product route catalog is `catalog.py`; the ordinary-user HTTP boundary and OpenAPI generator import that same catalog. `python -m cipher_aec.api.openapi` regenerates `openapi.json`, an OpenAPI 3.1 document with per-route HTTP methods, parsed function signatures, typed request fields, Frappe message envelopes, current-rights errors, CSRF/session and command idempotency headers. `--check` rejects drift without writing. `test_openapi` verifies every fixed route and resolves every local schema reference. The canonical interchange schema is embedded from the current migrations schema, and its definitions remain scoped inside that component. Upstream login/logout use their Frappe contracts rather than the Cipher domain envelope. The attachment route returns bytes on success and the domain error envelope on failure.

Approval inbox methods live in `cipher_aec.api.approvals`; packet reads are bare packet data and list items are packets. Request/review/withdraw commands return `{packet,operation}`; execution returns `{packet,effect:{project},operation}`. See governance/APPROVALS.md for the bounded qualified action and explicitly unavailable financial effects. Canonical validation/preview/export methods live in migrations.api, are POST reads with CSRF, perform zero writes, and expose no import-application endpoint.

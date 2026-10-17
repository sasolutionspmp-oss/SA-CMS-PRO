# governance: planned module boundary

Status: planning skeleton only. Do not interpret this directory as an implemented Frappe module.

## Ownership

Person bindings, project duties, policy revisions, approvals, command receipts and audit events.

## Interfaces to implement

authorize_read, authorize_command, reserve_operation, validate_manifest.

## Required invariant

All document/API/job paths enforce current permissions; aliases are one person.

## Implementation sequence

1. Read the master framework and the `GOV-01` work package family.
2. Verify standard ERPNext/Frappe fields and hooks on the locked runtime.
3. Add only the custom DocTypes, fields and indexes needed by the current slice.
4. Implement server invariants and transactional commands, then scoped reads/API schemas.
5. Connect the unified UI and Ricky tools to those same services.
6. Exercise positive, denied, stale and recovery cases appropriate to this module; record actual evidence.

Source of truth: [backend framework](../../../../../docs/framework/BACKEND_FRAMEWORK.md), [backlog](../../../../../docs/framework/EXECUTION_BACKLOG.md).

No runtime dependency, controller, schema, route or database has been created in this planning stage.

# ERPNext Project and Task services

ERPNext Project and Task remain authoritative. `service.py` supplies scoped reads, bounded Task/history lists, and idempotent Task creation. `tasks.py` adds canonical-person assignment/unassignment and ordinary native status, completion, and reopen commands. `task_rules.py` contains the bounded native-status/version/assignment invariants; `install.py` installs additive Task Link metadata through supported Custom Fields.

Current Project duties and native read permission precede every read and effect. New Task effects use separate `task.assign` and `task.update` duties. Receipts retain the canonical-person UUID namespace and current authorization on replay. Native document/assignment bypasses remain blocked by `guards.py`; unrelated personal ToDos retain native behavior.

[Task control contract and qualification status](../../../../../docs/framework/PRJ01_TASK_CONTROLS.md) records the supported status vocabulary, native callback limits, metadata readback, and pending native evidence. Host contract checks are separate from actual Frappe/MariaDB, HTTP, and browser qualification.

WBS, accepted budgets, and award orchestration live in their explicit modules. Task completion changes no accepted budget, commercial award, financial record, or governed Project lifecycle. Project/status approval and future schedule-baseline contracts remain separate.

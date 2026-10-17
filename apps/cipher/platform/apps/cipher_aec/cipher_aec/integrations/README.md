# Integration operations and governed local distribution

`outbox.py` implements the previously qualified local Project Task effect: durable operation, Redis publication/recovery, claim/fence and transactional Task/receipt/result. That path remains on `short`. It is trusted internal-only and does not qualify generic browser delegation or a financial/provider adapter.

The `distribution*` modules implement a separate Company-only proposal delivery path under controlled synthetic qualification. An immutable instruction pins an existing Issue, its exact original PDF/recipients, message and fixed local fixture profile. Independent review and consumption create one dispatch plus per-recipient canonical operations atomically. After-commit publication and scheduler recovery both use the fixed `cipher_distribution` queue. Persistent consumer/restart readiness is a separate runtime qualification.

The worker commits a bounded current-authorized attempt before calling an independent SQLite sink process outside Frappe locks. Original-key readback reconciles uncertain outcomes, including after mandate expiry, cancellation or revocation. No SMTP, external HTTP provider, email delivery or recipient acknowledgment is implemented. Every acknowledgment is labeled `fixture`.

The sink has eleven separate-process/contract checks on pinned Python, including concurrent idempotency, lost acknowledgment, original-byte integrity and readback serialization with an acceptance that passed its deadline before committing. Actual Frappe grant/intent/fence/cancellation and HTTP evidence must be reported separately. See the [distribution contract](../../../../../docs/framework/COM02_DISTRIBUTION_CONTRACT.md) and [sink evidence](../../../../../docs/framework/evidence/r1/distribution-sink-acceptance.json).

Ordinary browser/Ricky sessions retain their expiry/revocation rules. Only the separately reviewed and consumed distribution mandate may outlive logout, within its exact expiry, cancellation and current actor/source/policy rules. No caller chooses an arbitrary handler, transport URL, queue or sink path. Restored-site quarantine prevents new effects.

QuickBooks remains the official books integration target under the [backend framework](../../../../../docs/framework/BACKEND_FRAMEWORK.md). No live QuickBooks/BILL/provider adapter is qualified here.

`distribution_recovery.publish_pending()` separately republishes only existing literal Company fixture operations in fixed batches of 100; `run_forever()` is its five-second supervisor entry. It clears the read transaction per sweep, checks fresh quarantine, and never invokes the sink or general Task recovery. The eight executable query/guard/configuration tests do not replace actual DB-only publication-failure, persistent consumer or restart qualification.

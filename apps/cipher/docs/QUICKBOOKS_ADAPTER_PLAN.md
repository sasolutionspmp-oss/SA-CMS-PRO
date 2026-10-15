# QuickBooks accounting adapter plan

Design checkpoint, October 14, 2026. The connected company's read-only product metadata confirms **QuickBooks Online Advanced**, with an active subscription. Entity metadata declares Bill, Invoice and JournalEntry operations; those declarations are not sandbox delivery or reconciliation evidence. No financial records or write operations were used to recover this product fact.

This plan implements the boundary in [PRODUCT_GOAL.md](PRODUCT_GOAL.md). Cipher owns proposals, estimates/takeoffs, AP/AR business work, projects, CMS and engineering/library workflows. QuickBooks remains the official accounting authority. Preserve the established BILL payment route and reuse the owner-confirmed Odoo catch-up work through recovered checkpoints and explicit record mappings.

## One source and one accounting effect

| Record | Cipher source | Accounting boundary |
|---|---|---|
| Vendor/customer | Governed master and adopted external references | Choose master ownership before any create/update; record stable QuickBooks references and current remote version |
| Project and cost dimensions | Project/WBS, cost codes/types, contract and estimate lineage | Map supported remote dimensions explicitly; preserve unmapped detail in Cipher and expose an exception rather than dropping it |
| AP obligation | Received invoice, approved match, certified bill, independent posting receipt | Plan one agreed Bill or JournalEntry route for the obligation; sending both would duplicate expense/payable |
| AR obligation | Approved issued billing snapshot, source quantities/SOV and posting receipt | Map to one official invoice route; track the issued customer document independently from accounting acknowledgement |
| Credits/corrections | Governed source correction and original obligation link | Use a qualified remote correction operation and reconcile its effect; retain original snapshots |
| Payment/receipt | Approved release or verified outside transaction, provider reference and allocation | Observe the established BILL/bank route and map authoritative settlement evidence; reconcile clearing and AP/AR |
| Close and reporting | Working subledgers, job cost, WIP and reconciliation exceptions | Compare official control-account and record totals; controller-approved policies govern any official entries |

Account, tax, retainage, currency, customer/project and cost-dimension mappings are versioned audited records. Bind their version into the accounting plan and approval. An unmapped required value blocks delivery. A working-ledger journal remains a Cipher record until authoritative acceptance and reconciliation are recorded.

Remote entity identifiers, source IDs and connector identifiers have distinct types. The connector's company identifier and CompanyInfo's singleton ID are not the OAuth realm ID. Recover the actual realm and selected transport before tenant qualification; keep credentials and tokens in server-managed secret storage.

## Governed handoff and durable outcomes

The normalized provider contract exposes declared capabilities, plan validation, authorized delivery, lookup by logical operation, authoritative record reads and reconciliation. Provider-specific payloads are built server-side from an immutable plan containing:

- accounting entity and currency;
- source type, ID, revision/hash and original approval/posting receipt;
- selected route, exact amounts and mapped accounts/dimensions;
- mapping and adapter versions, remote entity/version when updating;
- one stable logical operation UUID and canonical payload hash.

A separately named accounting handoff binds this plan to current authority. Queueing and remote execution are separate events. Persist the approved plan and delivery intent atomically; a worker claims an intent using a lease and records every attempt without changing the approved facts. Restored copies remain quarantined until controlled reconciliation and authority recovery.

| Outcome | Meaning and next behavior |
|---|---|
| Prepared | Local validated plan awaiting governed authorization |
| Authorized/queued | Approved immutable intent ready for a qualified adapter |
| Delivering | One leased attempt is in progress |
| Accepted | Authoritative remote reference and returned version/content recorded |
| Rejected | Definite remote refusal; expose a safe exception and retain the attempt |
| Unknown | A request may have succeeded but no reliable acknowledgement arrived; perform bounded lookup/readback before another delivery |
| Reconciled | Source, accepted remote record and relevant totals agree for the recorded checkpoint |

The stable logical operation survives retries. A revised source or mapping creates a new reviewed plan linked to the superseded one. Remote updates need the current SyncToken and a reviewed response to conflicts. The chosen transport must prove its idempotency and lookup behavior in a sandbox; metadata declarations alone do not establish those guarantees. Apply bounded rate-limit backoff, expired-credential recovery and duplicate acknowledgement handling. Persist sanitized diagnostics and correlation references, excluding secrets and raw sensitive payloads.

Reconciliation checks records as well as totals: missing/extra obligations, amount or dimension differences, duplicate external references, stale remote versions, credits, partial payments, retainage and clearing. Each exception has a named owner, source evidence and resolution history. A timeout stays unknown until evidence resolves it; no blind new obligation or payment is created.

## Implemented first synthetic slice and next qualification

The standard-library [practice accounting module](ACCOUNTING_PRACTICE.md) implements a normalized immutable accounting plan and deterministic simulated adapter for a modern posted installed-work AP bill. Schema 70 appends audited mapping versions, source-bound plans, independently authorized intents, leases, attempts, simulated acceptances and readback checkpoints. Schema 71 adds audited API invocation recovery and expands fixed action receipts to 24 commands. Schemas 1–69 retain their exact statement text and catalog positions. Close and exports verify original audited inventories and report unresolved obligations.

The fixed route is `practice.simulated-journal-entry.v1`, adapter `simulated-journal-entry/1`. It preserves the original posting receipt's exact aggregate entry: this-period installed cost in account 5000, net AP in 2000 and withheld-retainage liability in 2050. Net AP plus this-period retainage equals this-period installed cost. It never substitutes cumulative gross or current open AP. The original entry lacks complete cost-code/type and tax dimensions, so this route cannot promise those dimensions or a QuickBooks Bill. Its payload binds the posting receipt/hash, original journal, business grant/record, original matched-invoice source or explicit null, local vendor/project/entity, USD, actual posting period and mapping/adapter versions. PostingReceipt records an actual period and technical timestamp, not an accounting-effective transaction date. The explicitly labeled `synthetic.period-end.v1` rule uses the audited actual posting period's end date; live date and posting policies remain controller qualification choices.

Corrections, payments or material mapping/source changes refuse a new submission of the original plan. Historical original lookup and readback can still resolve a prior contact without resending or netting its obligation. A future correction route needs a reviewed source bundle preserving both original and reversal period lineage; current AP netting to zero does not erase an earlier period's cost/liability. A separately governed inverse must link any accepted original remote reference. Unknown outcomes must be resolved before choosing the next route. The first single-posting simulator provides no inverse, credit or implicit replacement handoff. The existing period handoff package and manual acknowledgement remain useful exports, but do not prove acceptance of a particular QuickBooks obligation.

The actual practice API and Fluent interface show original cost/AP/retainage, the governed queue, simulated delivery result and separate reconciliation. Tests cover exact retry, concurrent claims, timeout before and after acceptance, duplicate acknowledgement, changed source/mapping, version conflicts, missing mapping, denied scope, tampered source and copied-workspace refusal. API reservations commit before the simulator call; subsequent observation and completion preserve original retry outcomes even when a receipt fails. All 24 AP actions share the per-person repeatability namespace, including pending invocations. Every outcome preserves one simulated effect and zero payment-provider calls. The worker and its separate retained simulator store are owned by the fresh in-memory practice process; file delivery, process-restart recovery and persisted provider history remain unqualified. See [the verification record](../BUILD_STATUS.md) for completed checks and their limits.

Then qualify the actual QuickBooks sandbox route using agreed chart/cost dimensions, tax/retainage treatment, credentials and the real realm ID. Test representative AP/AR/credit/payment/close cycles and recover the Odoo/BILL checkpoints before an internal live pilot. Controller policy and operational acceptance remain gates for official accounting; the synthetic adapter does not close them.

# Decisions, external dependencies and owner involvement

## Settled defaults

The stack is SAP UI5 React + ERPNext/Frappe + the custom AEC domain app + the existing local Ricky model. QuickBooks remains official accounting. One tenant/site, one company/USD synthetic baseline, company/project scope in every relevant contract, same-origin authenticated session, transactional commands/outbox, versioned document authority, typed tools and explicit independent consequential-action authority are selected. Engineering chooses compatible versions, indexes, supported extension hooks, naming, fixtures and UI compositions within these contracts.

The public money format is decimal string plus currency, not alternating formats. One canonical person shares one site-wide idempotency namespace; command/company/payload is hash-bound. Document Revision is canonical; File/storage references are adapters. Ordinary Frappe records remain authoritative where reused. The product is independently designed on the selected open-source foundations. Prior Cipher/Odoo code, schemas, workflows and tests are excluded as design inputs. The existing Ricky model remains an explicitly requested external integration.

## External prerequisites and their limited blocking scope

| Prerequisite | Evidence to recover | Blocks | Work that continues |
|---|---|---|---|
| Supported deployment capacity — resolved for development | Persistent runtime started using the digest-pinned merged image; actual install, migrate, restart and restore evidence recorded | Production capacity remains separate | All locally ready implementation and verification |
| Existing Ricky deployment | Endpoint/protocol/model-adapter IDs/auth reference/limits/tool inventory | Actual-model and tool-connected acceptance | Gateway, UI, persistence, labeled fixtures and deterministic services |
| Optional interim-system business-data transfer | Owner-selected records and validated export when rollout requires them | Only that optional onboarding operation | All architecture, schema, implementation and fresh-fixture acceptance work |
| Identity configuration | Entra tenant/app/issuer/redirect facts and approved secret path | Operational federation | Authenticated synthetic users, session and permission checks |
| QuickBooks/BILL access | Authorized environment, OAuth realm/connection and sandbox capabilities | Actual provider acceptance and payment-route confirmation | Durable adapters, recovery contracts and synthetic scenarios |
| Accounting policy | Chart/dimensions, tax/date/rounding/WIP/retainage/approval rules | Corresponding live posting category | Configurable policy engine and clearly labeled synthetic examples |
| Licensed documents/tools | Content rights, form entitlements, CAD capability/license | Specific ingestion/output or job | General document/library/engineering workflows and rights controls |
| Operational hosting/storage | Approved deployment target, artifact durability and secrets access | R4 rollout/recovery qualification | R0–R3 local/container integration and runbooks |
| Real pilot participants | Named duties and rollout window | Actual operational acceptance | Internal engineering acceptance and training material |

These are not a questionnaire to complete now. Inspect existing authorized configuration/handoffs first without exposing secrets. Ask only for a concrete missing fact when its dependent work cannot proceed; keep all ready work moving. Do not guess live policy from fixtures.

## What framework approval means

Approval starts source implementation, reversible configuration, development builds, verification and reviewable PR work under this plan. It does not transfer authority for payments, signatures, outside communications, production cutover, paid services or company-data model training. Ask for such actions only when actually required, with a concrete reviewable result and exact scope. A business workflow's built-in approval is part of the product, not a request for the owner to supervise coding.

## Scope-change rule

Routine implementation discoveries are resolved by engineering and recorded in the decision log. Escalate only a material cost/license/provider replacement, irreconcilable business requirement or authority-sensitive real-world action. Missing upstream APIs require a bounded alternative/recovery design; they do not justify claiming unsupported behavior works.

## Session continuity

Maintain task status, changed contracts, commits, checks, artifacts, active processes and the next ready task in the handoff. Sessions can resume the work without repeated owner instruction. A document cannot guarantee continuous multi-day runtime; honest persisted progress is required.

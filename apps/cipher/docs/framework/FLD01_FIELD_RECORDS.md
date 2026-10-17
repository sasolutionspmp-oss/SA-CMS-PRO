# FLD-01 — Documentary field records

## Implemented scope and qualification

The new `cipher_aec.field` backend implements online daily reports, photo references, delivered/installed quantity observations and T&M documentary tickets. It uses supported Frappe custom DocTypes and existing canonical Project command/history/source services. It derives from the approved framework and current new-stack conventions; the old Cipher engine and Odoo are not design inputs.

**Qualification:** host service/controller fixtures are locally verified. A host fixture is not an ERPNext/MariaDB transaction, connected provider, native session, production record or package acceptance. Native migration/index/controller behavior, authenticated HTTP/session behavior and connected unified UI evidence must be recorded by the integration writer. No container, database or external-provider mutation was performed by this source lane. No award or financial writer is invoked by the field domain.

## Persistence and lifecycle

| Kind | Native DocType | Behavior |
|---|---|---|
| `daily` | Cipher Field Daily Report | Stable identity/number, current revision and standing |
| `daily_revision` | Cipher Field Daily Revision | Immutable local date, canonical superintendent, weather/source, crew/activity/delay/visitor observations, photos and exact quantity references |
| `quantity` | Cipher Field Quantity Event | Immutable installed/delivered observation, exact decimal quantity/unit, authored WBS/cost-code labels, location, exact source evidence and original capture lineage |
| `ticket` | Cipher Field TM Ticket | Stable documentary ticket identity/current standing |
| `ticket_revision` | Cipher Field TM Revision | Immutable labor/equipment/material quantity lines, exact source evidence, customer/location/work observation, potential-change label and photos |
| `decision` | Cipher Field Decision | Immutable exact revision/digest, previous decision, documentary transition, canonical recorder, comments and acknowledgment evidence |

A draft is explicitly submitted, independently reviewed, then independently accepted. A submitted or reviewed record can be returned; revising a draft/returned record creates a successor. Accepted records and acknowledged tickets require an explicit amendment reason. A successor retains its predecessor, prior decision and latest accepted original; originals and decisions remain unchanged. Later acceptance applies only to the successor. Supplied header digests protect every update and transition against stale versions.

Only an accepted T&M ticket can acquire documentary acknowledgment. Acknowledgment requires exact evidence, the authored name of the acknowledging representative and an independent canonical recorder. It does not establish legal authority, authenticated customer signature, entitlement to payment or accepted commercial value. Contract changes require their separately governed workflow.

`field.read`, `field.write`, `field.review`, `field.accept` and `field.acknowledge` are explicit ordinary Project duties. General Project administration does not imply them, and generic synthetic fixture setup must not auto-grant them. A content author and daily superintendent cannot review, accept or acknowledge their own record through another login bound to the same Person. Server identity determines authorship; clients cannot supply an acting person or override permissions.

## Exact evidence, dates and quantities

Source inputs identify an exact canonical document revision, SHA-256, page and authored locator. The server stores exact original document/revision IDs, revision number, MIME type, byte length, page count and source digest, and rehashes actual canonical bytes. It does not accept arbitrary file URLs or client-supplied canonical metadata. Source data remains in canonical document storage; field JSON contains no duplicated original bytes.

New capture and new review/acceptance/acknowledgment effects require the referenced revision to remain current, with current Project document access and an effective authored content-ingest rights basis. Each package is bounded to 32 exact revisions and 64 MiB of source bytes. The complete bounded source/rights-evidence parent union is prelocked before locked source resolution. Exact bytes are resolved once per revision within that bounded call; no source entitlement is cached between operations. Superseded sources remain readable as original historical evidence where current access/content policy permits. A reviewer can return such a historical record so the author can explicitly revise it onto current sources; any newly attached return evidence still requires current ingest permission. Missing, quarantined, inaccessible, expired or denied source evidence fails closed.

Original JPEG/PNG photos use their exact admitted single-image source, page 1 and image MIME. A separately declared `photo_on_pdf_page` is an exact PDF page and authored locator. The server never describes a PDF as original camera-image bytes. Captions and offset-bearing capture timestamps are authored observations; there is no EXIF authenticity, OCR, image interpretation or automated quantity extraction claim. Daily local dates are exact ISO calendar dates.

Installed/delivered and T&M line quantities are positive decimal strings with at most six decimal places and no floating-point conversion. Documentary unit labels retain the user's exact authored unit. No implicit conversion, unit equivalence, adoption into financial WBS/cost-code masters, installed-work certification, payroll approval or billing eligibility is inferred. Those integrations remain outside this bounded slice. Original quantity capture UUIDs prevent duplicate reuse under another field record. Corrections retain that original capture UUID and identify the exact immediately preceding immutable quantity event.

T&M definitions admit quantities and unit labels; rates, prices, amounts and commercial authorization fields are rejected. All immutable field facts carry explicit false values for contract, budget, procurement, invoice, financial-posting, payroll-release, quality-certification and external-transmission effects. The field module imports no commercial, procurement, invoice, accounting or payroll writer.

## Transaction, access and read boundaries

Each command uses the shared canonical-person operation UUID, request digest and Project transaction. The same operation/payload returns its original immutable result; changed payloads conflict. Current duty/source/content-rights checks apply before replayed facts are exposed. Replay authorizes its original header snapshot and exact original revision/decision, allowing later independently authored sources to be inaccessible without rewriting an earlier receipt.

An exact per-record writer plan and admitted field command context are both required by native controllers. Generic native writes, `trusted_write` by itself, changed identity/index/digest metadata, updates to immutable facts, deletion and rename are denied. The capture context admits mutually linked new revision/quantity facts; native controllers verify that exact plan and current source rights. Header updates must correspond to the exact successor revision or immutable documentary decision.

Read/list/history calls reauthorize each exact record and source closure. A header authorizes its current package; the accepted original's pointer retains its same-parent metadata identity, and that original's source details are separately authorized when read. This keeps two individually bounded packages readable after an accepted amendment. Lists use signed authority-bound keyset cursors, no unfiltered totals, optional child-record parent filters and bounded authorization scans. Generic native query/read hooks deny direct field JSON exposure.

## API and integration

Routes under `cipher_aec.field.api`: `create_record`, `revise_record`, `transition`, `get_record`, `list_records`. The first three are commands with the existing session/CSRF/idempotency transport. Each command declares a `daily` or `ticket` family; definitions are closed and family-specific. The module's JSON Schema and route map describe requests, immutable facts and results.

The source lane supplies exact composition fragments outside tracked source. The integration writer must register the module and five Project duties, exclude field duties from generic synthetic grants, install additive indexes, deny generic native reads, dispatch `field.*` receipt checks, authorize exact immutable history subjects, register the five RPC routes, and include the field schema/typed OpenAPI requests. Shared scope, permission, schema and API files remain the integration writer's responsibility. Field decisions do not use the commercial approval or award execution path.

## Verification and remaining gates

Run the focused host checks from the packaging root with `PYTHONPATH=apps/cipher/platform/apps/cipher_aec` and `python -m unittest cipher_aec.tests.test_field cipher_aec.tests.test_field_contracts`. The fixtures call the actual field service, repository serialization, source validation and native controller classes while replacing Frappe persistence, source storage and current rights with explicit deterministic fixtures.

The 29 focused host tests cover accepted original/decision preservation; amendment/capture lineage; independent aliases and superintendent denial; T&M acknowledgment with unchanged contract/budget/PO/invoice/GL fixture rows; exact photo representations and quantity strings; forbidden commercial fields; cross-Project sources/records; revoked identity, duties, document access and rights; stale source/version and UUID payload conflict; original replay after successors; controller bypass/tamper refusal; bounded lists/history; compound accepted/current source bounds; absent header SQL filter refusal; and atomic rollback on late receipt failure. A composed host run with engineering/document-control service and contract tests passed 93 cases.

`tests/test_field_native.py` prepares eight rollback-isolated Frappe IntegrationTestCase methods for the integration writer: retained canonical TXT/PNG evidence and distinct permission evidence, ordinary independent acceptance/acknowledgment, immutable amendments, shared receipt revocation, generic-native bypass refusal and injected late-receipt rollback. The source lane performed static AST checks and validated the embedded PNG only; those native tests were not run by this lane.

Open gates are real Frappe/MariaDB migration/index/restart and transaction/concurrency proof, actual authenticated HTTP/CSRF/retry/revocation behavior, current-authorized original photo download/preview through the connected document pipeline, and the complete unified UI journey. Offline drafts and explicit conflict resolution remain FLD-02; independent QA/QC/safety and formal installed-work/billing certification are separate packages. Qualified UOM conversions and operational WBS/cost-code adoption are not implemented by documentary labels. The package must retain those limits until corresponding source and native evidence exists.

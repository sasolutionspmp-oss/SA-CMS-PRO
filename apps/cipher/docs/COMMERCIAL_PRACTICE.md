# Connected manual estimating and draft subcontract workflow

The commercial entry connects the existing estimate and commitment engine to
Fluent 2. It owns a fresh synthetic memory workspace, separate from the read and
AP entries. Its registered estimator, independent reviewer and PM have audited
project memberships and their own actual duties. Selecting a practice person is
not employee authentication.

```bash
npm run build:commercial --prefix apps/cipher/web
python -m apps.cipher commercial-practice-web --port 8768
# Open http://127.0.0.1:8768
```

The interface follows the original T3 list, T4 record/history, T5 review, T6 line
entry and T7 setup patterns. The server uses `/api/commercial-practice/v1` and
mounts no general console, file-workspace, provider or commitment-execution route.

## The connected work

| Fixed action | Current project duty | Effect |
| --- | --- | --- |
| `estimate.create` | Estimator | Create an exact priced manual-source revision |
| `estimate.revise` | Estimator | Create a successor and preserve original line lineage |
| `estimate.request` | Estimator | Request acceptance of the exact current source |
| `estimate.accept` | A different estimator | Grant the original authorization; estimate remains draft |
| `estimate.apply` | Estimator | Consume that grant and record the accepted baseline |
| `estimate.prepareHandoff` | Estimator | Preserve the complete accepted source and fixed package |
| `estimate.createCommitment` | PM | Create a source-preserving subcontract draft |

Request and review require different canonical people. An authorized current
estimator may apply the intact grant; the original reviewer must still hold the
required project duty. Owner wildcard authority, another role label or a
delegation cannot supply these bounded duties. The separate PM draft does not
sign or execute a subcontract. Existing agreement/signature/commitment execution
remain separate engine acts.

The seven local actions create no ledger journal, AP/AR balance, provider call,
customer proposal delivery, customer award or project budget adoption.

## Exact quantities and source preservation

An estimator selects a current owned drawing revision and records manual quantity,
registered unit, price in integer cents, source locator, cost code and measurement
basis for every line. Quantities remain exact decimal strings. The engine computes
rounded amounts and totals; the browser does not calculate prices.

Every revision preserves its entire priced baseline, inclusions, exclusions,
price reference and manual source. A successor explicitly names the immediate
predecessor line or declares a new line. Comparison shows changed, added, removed
and unchanged lines, quantities, prices, locators and scope. Drawing and source
birth inventories detect missing revisions and altered lineage.

The initial fixed synthetic package copies the complete accepted zero-contingency
estimate. Its supplier, title and retainage come from an audited explicit PM
declaration. The request cannot substitute terms or select an unrelated SOV.
Every source line, including zero-quantity/zero-amount lines, retains its exact
corresponding subcontract SOV line and source IDs.

Historical accepted estimates and original draft outcomes remain readable after
genuine later revisions or separate commitment execution. Current commitment
status is displayed separately from original `creationStatus: draft`. The current
proof supports the unchanged complete SOV; separately amended SOV correspondence
is a subsequent implementation step. Legacy commitments without these sidecars
retain their existing support without claiming exact estimate-to-SOV mapping.

These are manually entered drawing quantities. Source locators do not establish
calibrated geometry, automated measurement, licensed CAD access or engineer
certification. Positive contingency allocation, mixed/partial packages, geometric
takeoff, customer proposal issue/award and budget adoption need their own controls.

## Reviews, retries and scope

Pure reviews bind the exact typed input, original source inventory, current person
and project duties, governance, approval clock and record version. They create no
ID, audit, financial or provider effect. A bounded action request carries its
fingerprint, UUID repeatability key, quoted `If-Match` and CSRF token.

The domain effect, approval lifecycle, command bookkeeping, source sidecars and
immutable original API receipt share one transaction/savepoint. Unexpected
resource/schema/financial effects or false original results roll back. Exact
canonical JSON proofs distinguish integers, booleans and floating-point values.
Actual original request/grant/consume/execution events and timestamps must match.

Commercial receipts share the same per-person repeatability namespace as all
24 AP actions and unfinished accounting invocations. Current caller duty and
scope are checked before cross-domain metadata or original outcomes. The shared
metadata guard initializes no domain adapter, simulator or worker.

An unresolved browser request retains its original UUID/body/version through
edits and navigation. Its original outcome must be retrieved before a fresh
edited-source review. A late response to an older input review is discarded.
Completed original outcomes remain unchanged after later genuine lifecycle steps.
Loss of current authority clears cached facts and action memory. A strictly validated definitive 412 refusal can be explicitly
retained in session history before a fresh review uses a new UUID. Historical
refused requests remain available for exact retry; transport loss, 5xx and 423
source-integrity holds retain the unresolved original request.

## Schema, history and verification

Schemas 1–71 retain their exact SQL, order and checksums. Deferred module import
registers no SQL. The required loader explicitly appends:

| Version | Name | Checksum |
| --- | --- | --- |
| 72 | `commercial_manual_sources_and_handoffs` | `f6cf329361ced5bfc78bb96b57f81bff7d4d74acd14ccb3d2556883163d1d3f7` |
| 73 | `commercial_practice_action_receipts` | `a7f97fa4c298fa5ef13a632b38c3ab7bcfb9e158fd5c392844a8957256857ca9` |

An empty module is inert in genuine earlier workspaces. Missing admission with
surviving commercial tables, receipt admission or audited source births fails
closed. Original receipts, journals and accepted/unfinished accounting histories
survive upgrade. A failed later migration restores the original complete history;
physical copies retain read-only authority and initialize no delivery worker.

Current backend, migration, browser and source-freeze evidence is recorded in
[BUILD_STATUS.md](../BUILD_STATUS.md). Browser checks do not replace owner visual
acceptance, manual screen-reader review, production performance/recovery testing,
authenticated staff identity, durable operational storage or live integration.
The full [product goal](PRODUCT_GOAL.md) and [delivery backlog](DELIVERY_BACKLOG.md)
continue beyond this connected workflow.

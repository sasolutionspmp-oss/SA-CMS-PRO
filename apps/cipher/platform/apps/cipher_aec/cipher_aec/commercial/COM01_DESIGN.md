# COM-01 implementation contract proposal

Status: authored draft implementation active after checkpoint `294d06d7`. Targeted native ERPNext acceptance is qualified; actual HTTP qualification is recorded separately. COM-02 issue/distribution and company document/estimate references remain explicit prerequisites.

## Native record reuse verified on ERPNext 16.51.0

- Opportunity has required `opportunity_from`/`party_name`, `company`, lifecycle status, currency, expected closing and optional source items. Customer/Lead remain native records; no customer or opportunity clone is introduced.
- Quotation has `quotation_to`/`party_name`, `company`, `opportunity`, `currency`, `conversion_rate`, `valid_till`, native items, taxes, terms, totals, status and amendment lineage. Quotation remains the commercial pricing document.
- Neither Opportunity nor Quotation has a native Project field in the pinned JSON schema. Pre-award authorization must be company-scoped; a placeholder Project is not created.
- Quotation Item has native quantity/UOM/conversion/rate/amount fields and `is_alternative`/`has_alternative_item`. Native taxes-and-totals filters alternative rows out of effective totals. Native before-submit alternative grouping uses row adjacency. The adapter must project explicit AEC alternate groups into that supported ordering while retaining independent stable line UUIDs; list position cannot become business identity.

## Shared governance prerequisite

Backend owns `require_company`, `run_company_command`, company history/receipt readback and `append_company_event`. Exact company duties are `company.read`, `commercial.read` and `commercial.write`. Empty Project on a company duty is company scope, never a wildcard Project entitlement. Existing Project hashes, histories, receipt replay and permissions remain intact.

No pre-award action requires or fabricates a Project. An optional actual Project link is populated only by the later authorized award/handoff flow. COM-01 creates reversible drafts and immutable evidence. Proposal review/issue needs a registered company-scope action under COM-02; it cannot borrow the existing Project-status approval handler or create a second approval engine.

## Proposed data ownership

`Cipher Pursuit` is a unique sidecar of one standard Opportunity. It holds company, opaque identity, display number, current business revision, commercial owner, sector/delivery/geography, due date/time-zone basis, source references and pursuit stage. Party identity is the explicit native party type/ID. No automatic matching or creation of a party from a display name occurs. Existing Opportunity native status remains distinct from AEC pursuit stage.

`Cipher Proposal` uniquely links one standard Quotation and its Pursuit. It holds company, native party reference, display number, responsible person and the current immutable revision head. The standard Quotation and Opportunity companies/parties must agree with the authorized sidecar scope.

`Cipher Proposal Revision` is append-only. It binds predecessor, revision number, canonical creator, exact native Quotation version/fingerprint, sections, assumptions, exclusions, schedule basis, validity, selected alternates, commercial terms and exact pricing snapshot. Estimate revision/source references are explicit and are only wired when their actual EST contracts are qualified. A new working edit creates a new revision; it cannot rewrite an old or issued revision.

`Cipher Proposal Section` and `Cipher Proposal Price Line` carry independent UUIDs. Sections are authored plain text with explicit purpose/order. Price lines bind native Quotation Item rows through a namespaced stable line UUID, qualified unit identity/revision, exact decimal quantity/rate/amount/currency, alternate group/base line and inclusion state. Native child names and indices are storage references. Comparison joins UUIDs, reports moved/added/removed/changed sections and prices, and preserves alternate/terms lineage.

Pricing input and output uses exact decimal strings and the shared qualified unit/rational conversion contracts. Native Float/Currency values are verified through an exact database adapter and reconciled against the declared calculation policy after native validation. A mismatch fails the command. No unqualified FX/tax/discount behavior or financial posting is inferred. Drafts expose unresolved policy rather than pretending they are issued contractual prices.

## Proposed company-scoped API

Read RPCs under `commercial.api` are `pursuits`, `pursuit`, `proposals`, `proposal`, `proposal_revision` and `compare_revisions`. Lists use the shared cursor/count contract. Reads recheck current company duty plus native source/party permission before metadata, counts or revision content.

Draft POSTs are `create_pursuit`, `update_pursuit`, `create_proposal` and `save_proposal_revision`. Each uses the shared session, CSRF, person-scoped UUID receipt namespace and company transaction. Updates bind expected business revision and exact native source versions. The commands run normal ERPNext validation and atomic sidecar/revision/history/receipt persistence. Linked native Opportunity/Quotation/Item changes and custom writes have controller/hooks so generic imports, Desk and direct REST cannot silently bypass the revision service. Unsupported native transitions remain unavailable through the product API.

No issue/send/award/Sales Order/project/budget/procurement effect is in this slice. Those routes appear only when their declared COM-02/PRJ-02 dependencies and approval manifests are implemented.

## Qualification and UI handoff

Actual ERPNext acceptance must create one existing native party, one Opportunity and one Quotation, save at least two scope/alternate/terms revisions, compare by stable UUID and show unchanged Customer count. Verify append-only revision enforcement, stale head/source conflicts, same-operation replay, changed-payload conflict, exact totals, unit/type mismatch, current company/source revocation, native generic-write denial and no Project requirement. Source-specific import is absent.

UX-03 can plan a company-level Commercial list and pursuit detail, a Proposal object page with authored sections/terms and exact price-line/alternate table, and revision selector/comparison. Only implemented draft capabilities are enabled. No award/procurement/issue UI is implied by this design. Backend/API/UI contracts are shared before implementation; actual field/schema names are finalized against the shared company helper and migrated native metadata.

# FIN-01 construction contract foundation

The native Customer or Supplier remains the counterparty master. Prime contracts
are receivable/Customer; construction subcontracts are payable/Supplier.
Consultant and service contracts declare their direction explicitly. This module
does not use manufacturing Subcontracting Order.

The mutable `Cipher Construction Contract` preserves its original company,
Project, number, native party, currency and exact original cap. Authoring creates
immutable `Cipher Contract Revision`, `Cipher Retainage Policy Revision`,
`Cipher SOV Version`, and `Cipher SOV Line` records. Draft and accepted pointers
advance with an expected opaque aggregate version and monotonic business revision.
Every SOV line has its own stable UUID and unique item code per version; row
order is not identity. Exact amounts use decimal strings and native currency
precision. Exact quantities bind qualified native UOM identity and precision.
Original cap changes, legal execution evidence, award/source-line mappings,
certification, commitments and accounting posting need their later qualified
workflows. `source_line_id` is reserved/null in this slice; a client cannot claim
an unverified estimate award link.

Terms include billing basis and business dates. Retainage revisions specify an
earned-value basis, explicit fraction tiers, optional monetary cap, effective date,
HALF_UP currency rounding, and reduction/release/approval conditions. A newly
selected policy cannot reprice an older SOV snapshot. This foundation stores
policy; it computes no certified work, withholding movement, payable or tax.

`contract.baseline.activate.v1` is a statically registered shared GOV action.
Its human review binds the current aggregate version, exact terms/SOV/policy
hashes, accepted predecessor, original cap/currency, current native counterparty,
cited source documents and floor/admission watermark. An independent canonical
person grants; the requester consumes that exact grant once. A new draft makes
an earlier unconsumed packet stale. Baseline acceptance does not imply legal
execution, certification, business posting, or a submitted ERPNext transaction.

An initial baseline requires server-created provenance and a repeated conservative
scan of all supported native obligation/activity channels. Ambiguous company/party
or Project activity fails with `activity_unqualified`; absent contract linkage
never establishes an authoritative zero balance. User-visible admission snapshots
contain status, provider/version, bounded channel count and an opaque watermark.
They contain no native document IDs, statuses or versions from unrelated rows.
The shared static native writer catalog currently rejects unqualified draft and
submitted financial/activity writes. A future supported writer must acquire the
same declared admission aggregate lock through its exact reviewed server effect;
it cannot silently become an authority by adding another table. Host/root SQL
and unsupported database tools are outside the application writer guarantee.

FIN-01 has no qualified FIN-03 certified/billed floor reader. An accepted SOV
therefore cannot decrease amounts or quantities, delete lines, change UOM,
currency, stable item/source identity, cost basis or stored-material eligibility.
Appends and increases preserve all prior caps and stay within the original
contract cap. Accepted billing terms/retainage changes require later qualified
contract change control. Draft successors before acceptance remain editable.
The typed `FloorSnapshot` contract binds contract/terms/SOV revisions, currency,
exact line floors, provider version, source watermark and correction authority.
Injected test snapshots prove validator behavior only; no production API accepts
a caller-supplied floor or fictitious certificate.

Effects acquire the sorted union of relevant UOMs, then Currency, then native
party, matching EST's shared-master order. New effects require enabled sources.
Historical reads and completed receipts preserve disabled-source access while
rechecking current native read/company rights, Project duties and exact source
citations. Packet reads, decisions, consumption and receipt replay authorize the
stored historical domain manifest, rather than trusting a newer draft.

Only explicit scoped APIs serve immutable JSON snapshots; generic native Frappe
list/get/export fails closed. `list_contracts` establishes visibility of the
complete distinct native-party set before pagination or exact counts. An
unavailable party anywhere in the collection denies the collection; more than
200 distinct parties returns `collection_scope_unqualified`. This bounded
fail-closed behavior prevents off-page records from leaking through totals,
`has_more`, or cursors. Single-record reads remain individually scoped.

# Canonical cost controls and initial award adoption

Company cost code/type masters preserve immutable, effective revisions. The first
fixed mapping profile selects existing same-Company leaf Cost Centers and expense
Accounts. An Account is an accounting target; configured Accounting Dimensions,
posting, cost certification and financial floors are not qualified by this module.
Production commands never create/default native accounting masters. The dated
selector returns the exact latest effective revision (including disabled/expired
facts) and separately authorizes the current head exposed by its master header.
That read selector never implies new award-use admission.

`masters.plan_resources` discovers bounded revision identities/native resources.
It grants no native access, locks, admission or cost-use eligibility. The caller
must acquire the complete outer UOM → Currency → sorted native union first.
`resolve_revision(..., for_new=True)` rechecks current scope, native read rights,
exact effectivity and eligibility. The historical `for_new=False` path keeps the
exact original revision readable under current rights after a successor or
disablement. The full original/current currency union is retained; detected
locked Account/Company-currency drift fails before any late currency acquisition.

`core.validate_wbs_plan` accepts explicit acyclic bounded trees with unique stable
codes and exact leaf/summary classification. `core.plan_initial_budget` preserves
accepted included component amounts by parent-line/component identity and keeps
indirect/contingency adjustment IDs separate. It excludes unfunded alternatives,
preserves canonical rational source quantities and adopts each source exactly
once. Split allocations, repricing and revenue-based budget substitution are
unavailable. The total must exactly equal the original accepted cost total.

`adoption.create_initial_adoption` is private and requires the exact registered
`award.project.create.v1` context, full award plan digest, reviewed controls digest,
real new Project and reviewed team. WBS accountability must name an approved team
participant. The requester need not be a Project team member. The factory creates
no access grants, native accounting entries or commits. Controllers independently
bind scope, author, deterministic budget identity, reviewed child identities and
parent membership. Generic trusted writes cannot manufacture an adoption.

Adopted Project reads require `project.read` and current native rights. A WBS
record requires `wbs.read` and checks exact parent membership without opening
financial sources; an exact budget line requires `budget.read` without
expanding WBS facts. The complete budget record embeds WBS paths/accountability
and requires both `budget.read` and `wbs.read`, including list/count access. Opening original Company estimate/master/document sources
still requires their original Company rights; adoption grants none of those.
Native JSON projections are closed to ordinary direct queries. Canonical lists
establish the full bounded visible set before count/cursor derivation, use SQL
keyset comparisons and signed actor/authority/filter/count-mode-bound cursors.

The focused pure/schema suite is `test_project_controls`. The self-contained
`test_project_controls_acceptance.run_acceptance` is synthetic native master
storage/authority qualification, after coordinated metadata installation. Actual
composed award/WBS/budget adoption, rollback and HTTP qualification remain separate;
no enabled award writer or live provider is implied by the source contract.

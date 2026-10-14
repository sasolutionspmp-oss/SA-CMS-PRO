# Connected estimating and subcontract handoff

Next delivery checkpoint after the [practice accounting handoff](ACCOUNTING_PRACTICE.md).
This is a build plan; the commercial interface is not yet complete.

The first connected workflow uses owned drawing revisions, explicitly manual
quantities, exact estimate lines, independent estimator acceptance and a
source-preserving subcontract draft. It feeds the existing commitment and AP
workflow. Customer proposals, external issue/send, customer award, adopted project
budgets and contract signatures need their own later named acts.

## Existing work to reuse

The estimate engine already calculates decimal quantities against registered units
and cent-rounded prices, preserves immutable revisions, binds a drawing revision,
and records approval-bound acceptance. Commitments can reference an estimate, but
their independent schedule of values does not yet preserve its priced line source.
Reuse evidence, people, approval, contract, commitment and AP controls. Retain
accepted Odoo ownership and stable source IDs when its checkpoint is recovered.

Direct commitment execution needs stronger accepted-estimate provenance checks.
A valid downstream approval must not make an unaccepted source valid. An accepted
status or row-local hash must not conceal a missing acceptance, altered consumed
approval, duplicate creation event or deleted audited successor. Fix shared domain
proof before exposing the new handoff.

## First usable result

1. A registered estimator selects an owned current drawing revision and enters
   labeled manual line facts: page locator, method or basis, exact decimal quantity,
   unit, cent-rounded rate and scope.
2. The estimator compares a successor with the prior revision. Drawing, quantities,
   rates, inclusions, exclusions, price source and total changes stay visible. A
   successor requires fresh review and cannot silently revise a commitment.
3. A different registered estimator grants acceptance. The server requires each
   person's own current project estimator duty and membership. Role text, an AP
   duty or a practice persona name cannot supply it. Explicit application consumes
   the original authorization under current domain policy.
4. A PM reviews one immutable handoff from that accepted baseline. Each resulting
   SOV line retains its source estimate line, quantity, unit, rate, amount, mapped
   cost code and owned drawing/manual source. No unrelated SOV or silent price
   overwrite can be represented as the estimate's handoff.
5. The explicit handoff creates a draft subcontract only. Approval, agreement
   review/signature and commitment execution remain separate existing acts.

Use a short single-package, zero-contingency fixture initially. Existing estimate
contingency stays visible, but allocating it requires explicit reviewed semantics
before admission. Retainage comes from explicit synthetic terms, not an inferred
owner default. Manual facts do not claim geometric takeoff or calibrated CAD work.

## Backend and Fluent contract

Use a separate fixed commercial practice entry and authority resolver. Broadening
the AP resolver would weaken its duty boundary. The new entry owns a fresh practice
workspace and actual audited synthetic estimator, reviewer and PM records. It has
no actor, role, file, provider, send or signature selector in request bodies. The
separate read application stays read-only.

Pure reviews bind source/revision inventory, exact effects, current person and
duties into an opaque fingerprint. Quantities remain decimal strings; money uses
exact integer cents in DTOs. The browser displays server calculations. Scope before
counts, facets, totals, links or source details. Original receipts replay after
current authority and original audited source proof. New schemas append after 71;
historical SQL and stored codes stay unchanged.

Follow Fluent 2 T3 lists, T4 records/history, T5 reviews, T6 line entry and T7 setup.
Show old/new quantities, units, prices, scope and totals in business terms. Exercise
the actual API at 1440, 1024 and 390 pixels, including stale sources, revoked duties,
tampering, exact retries and copy refusal. Preserve AP/read interfaces, golden
business results and the full schema prefix; pass the full suite before publishing.

The larger [product goal](PRODUCT_GOAL.md) still includes opportunities/customer
proposals, geometric takeoffs, assemblies/rates/quotes, award-to-project/budget
conversion, full AP/AR, project/CMS work, engineering and specification/contract
libraries. Build those connected tracks after their shared source, identity and
document foundations. A successful subcontract draft is one step in that ERP.

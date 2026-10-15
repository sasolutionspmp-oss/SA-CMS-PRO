# Planned Company/Pursuit integration acceptance

This is a next-wave acceptance plan, not executed evidence. Implementation stays
on hold until the current combined checkpoint is complete and root releases it.
Domain owners retain the canonical DOC, EST, GOV and COM services; this QA lane
will own independent integration qualification after their contracts are agreed.
No live model or external provider is required.

Use two explicitly authorized synthetic Company scopes and existing identities
where possible. Prepare one author and alias sharing a canonical person, an
independent reviewer, and an outsider. The primary Company has two Pursuits and
no Project. Keep an existing Project scope as an independent regression control.
Native customers, qualified units and rates belong to their explicitly selected
Company; fixture setup must not infer Company authority from Project duties.
Temporary role/duty changes must be restored and recorded.

| Boundary | Intended independent proof |
| --- | --- |
| Company-only operation | DOC upload/citation, EST authoring/acceptance and COM linkage require no fake Project; native Project count and Project references remain unchanged. |
| Source identity | Actual stored bytes, page/excerpt/source hashes, immutable revision IDs, native party/unit/rate identity and exact values survive each boundary. |
| Pursuit linkage | Owners must declare whether sources are Company-reusable or Pursuit-restricted. Validate that explicit policy; reject a mismatched claimed binding rather than invent an unstated Pursuit ACL. |
| Approval manifest | Review binds exact scope, source revisions, calculation snapshot, stable line identities, current predecessor and policy. A changed relevant source makes an unconsumed approval stale; it cannot silently slide to a newer revision. |
| Independent people | A canonical alias cannot approve its own request. Independent current human review and one atomic consumption remain mandatory. |
| Retry | Same person, UUID and payload replay one effect across aliases; changed payload or Company/Project scope cannot reuse that UUID. Unknown outcomes retain the original request. |
| Current access | Revoke Company document/estimate/commercial/native-party rights separately while preserving unrelated access. Source-bearing reads, packet/receipt readback and replay deny access to the exact old source. |
| Aggregate privacy | An inaccessible source outside the first page cannot leak through items, exact totals, cursors or history details. Restore rights and recover the same immutable IDs. |
| Scope isolation | Wrong Company, wrong declared Pursuit binding, outsider identity, and forged person/scope fields fail before any effect. Company and Project duties never imply each other. |
| Historical Project control | Original Project Task/document/estimate receipts remain unchanged and readable under their original Project permissions after Company functionality is added. Company-only revocation must not revoke Project duties. |
| Financial limits | Accepted estimate/proposal linkage creates no Sales Order, payable, invoice, certificate, retainage movement, GL, issue/send, award or Project until its separately qualified workflow is invoked. |

Record actual cookie/CSRF HTTP separately from authenticated bench fixture setup
and independent native readback. Preserve request IDs and payload-bound operation
UUIDs without credentials/cookies. Validate actual responses against the agreed
schemas. Report reconstructed request shapes explicitly when no original request
capture exists. Do not combine repeated schema samples or overlapping runs into
a behavioral test count.

The current R1 native/HTTP artifacts remain historical controls. The future
Company/Pursuit report must bind its own final source inventory and qualification
limits; it must not rewrite earlier Project evidence to imply a capability that
was unavailable at capture time.

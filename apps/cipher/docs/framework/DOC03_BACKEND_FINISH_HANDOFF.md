# DOC-03 backend contract handoff

Local integration base: `d03bce8d0116ad39a505f4bb3a57cdec672b9e47`. Audited successor: `142faec7d9b3f78374761b9e735a6fc08721550b`. Fetch `cipher/doc03-backend-contract-20261017`; use the full SHA returned after remote readback.

## Delivered

- Company-owned library/rights routes and exact adoption into an authorized Project. Reuse stays within one owning Company. Original Company/Project access and current content permissions are checked independently from target Project access.
- Clause Use, redline revisions and independently approved documentary relationships. Original text, proposed text, target revision and digests remain distinct. Approval never edits a proposal, contract or document target.
- Append-only independent withdrawal/supersession and a bounded current-issued projection for documents owned by the Project. Working uploads and alternate issued records do not silently change that projection. New transmittals reject withdrawn or superseded content; historical records and receipts retain their original sources under current rights.
- Original receipt source selection before documentary lock planning, complete source/evidence/scope plans and fresh recipient authorization. Company paging now binds Company duties.

There are 16 Project RPCs and five explicit Company RPCs, described by the owned `route-contracts.json`, `company-route-contracts.json` and closed domain schema. The two new lifecycle endpoints are `issued_standing` and `request_lifecycle`. Five literal approval actions have six wire variants because original and shared adoption use distinct packet shapes.

## Ownership and composition

The commit directly changes only `document_control/`, `cipher_document_control/`, `tests/test_document_control*` and this handoff/evidence. It does **not** replace Task APIs, shared catalogs/core schemas/ability definitions, generated clients, product UI, deployment or local trial fixtures.

Required shared changes are in [integration-fragments/MANIFEST.json](evidence/r3/doc03-backend-completion/integration-fragments/MANIFEST.json). They include:

1. Route/approval/history registration, explicit Company duties and default-grant exclusions, native permission hooks.
2. Company source-rights admission before bytes/text and ordered documentary command/approval/receipt contexts.
3. Documentary core schema definitions, including statically paired shared-adoption and lifecycle packets.
4. Two existing producer/scope test-fixture updates declaring a no-authored-policy adapter. Actual rights denial remains covered by DOC-03 tests.

Merge these fragments with Task work, preserving unrelated local additions. `core-schema-definitions.json` carries only changed documentary definitions and their base-definition hashes. Inspect a mismatch rather than replacing a local definition blindly. Other patches are against the stated Project base and may need manual composition. No patch is a command to overwrite the local overlay.

After composition, regenerate OpenAPI and clients once:

```sh
python -m cipher_aec.api.openapi
# From apps/cipher/product:
node scripts/generate-api.mjs
```

Then run the focused checks, typecheck and native workflow declarations in a disposable integration copy. Preserve the healthy stable trial and its data. New Company/clause/lifecycle UI actions and approval routing still belong to the product lane; generated types alone do not make those flows available to a person.

## Evidence and limits

[Qualification](evidence/r3/doc03-backend-completion/QUALIFICATION.json) records 106 distinct host cases: 66 DOC-03 cases and 40 Company-document/provenance compatibility cases. These are composed outcomes with original failed attempts retained, not a single fresh 106-case all-pass run. OpenAPI/signatures and all generated client checks pass. Persistence, identity and lock instrumentation use explicit host doubles.

Native Company adoption, clause lineage and lifecycle workflows are declared in `test_document_control_native.py` but were not executed in the cloud. Actual migrations, database locking/concurrency, native API/UI integration and human acceptance remain local qualification. Full DOC-03/C20 is not marked accepted by this backend handoff.

The [917-file qualified source inventory](evidence/r3/doc03-backend-completion/QUALIFIED_SOURCE_INVENTORY.json) and [archive manifest](evidence/r3/doc03-backend-completion/QUALIFIED_ARCHIVE_MANIFEST.json) reproduce the isolated composition. The archive includes shared-file snapshots for inspection only; **do not extract it over local Task/trial work**. Primary feature sources and fragments are the integration inputs.

Withdrawal has no implicit reopening transition. Company/shared-origin artifacts remain rights-controlled package references, with no invented target-Project publication status. Cross-Company reuse, external delivery, electronic signing, professional sealing and commercial execution are excluded.

No runtime, award, procurement/finance rollout or live provider action occurred. The award boundary remains blocked on every machine. The next backend candidate is original DOC-04, subject to its AI-03 dependency and coordinator path ownership; this handoff claims no new package paths.

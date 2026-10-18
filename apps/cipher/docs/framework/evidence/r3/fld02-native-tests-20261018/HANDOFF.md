# FLD02 native test preparation

Status: **prepared, UNRUN**. No native module was imported, no Frappe test or
HTTP driver was executed, and no site/database/runtime/provider/model/award
operation occurred. Production sources are unchanged. This is a separate test
artifact bundle for the local integration owner.

Backend reference: `310a946bd34d06c9f7c1a3d96ab7274733142cd9`.
Frozen FLD02 contract: `392a19f8c01b4253a5aaeaa99878408d394dc9cb`.
Repository: https://github.com/sasolutionspmp-oss/SA-CMS-PRO.

## What is prepared

`native_tests/test_field_offline_native.py` declares 18 real Frappe
`IntegrationTestCase` methods. They use native services, controllers, canonical
identity/authority and private File storage, with no mocks, null contexts,
substitute authorities or alternative Field writers. `native_tests/COVERAGE.md`
maps N01–N18 and states the limits.

The cases cover device ownership and aliases, disabled/reassigned identity,
stage/inspect/apply, current source rights/head changes, duplicate UUID recovery,
operation collisions, immutable envelopes, base conflicts, linked replacements,
discard, exact quantity/source lineage, and original receipts after real Field
acceptance/amendment/redaction. Success assertions compare canonical native Field
records and exact command receipt JSON/hashes; counts are supplemental. Daily
and T&M cases also compare bounded Task/Project/finance side-effect snapshots.

`native_tests/fld02_native_fixture.py` is a separate Administrator-only pre-suite
preparer. It requires the installed synthetic Company/Admin, creates dedicated
`synthetic.example` identities and aliases using supported native helpers, grants
no duties and commits nothing. The local fixture runner must commit preparation
before the suite. Each case creates its own Projects and explicit duties after
its savepoint; it never seeds, migrates or changes schema. Cleanup is registered
before writes and restricts orphan-file removal to individually owned UUID names
with matching bytes and no surviving File reference.

The optional `http_driver/` is a standalone POSIX operator tool, also UNRUN. It
uses an existing private cookie jar and current session/CSRF readback, supports
the actual localhost trial origin, persists sealed UUID/request bytes before
POST, and retains unknown-response barriers. It never automatically applies or
creates a fresh business command to escape an unknown result. It supports
stage/inspect/apply/recover and explicit local/server discard for an already
registered device. Register/revoke/resolve remain outside its command UI.
Its private plaintext journal is a diagnostic artifact, not a qualified encrypted
browser vault. See its README for exact input, recovery and privacy contracts.

## Local composition and execution

1. Finish the independently owned FLD02/FLD03 service/raw-guard/hooks/schema
   composition and migration first. This bundle changes none of those files.
2. Compare `SOURCE_CONTRACTS.json` with the selected image and record approved
   local functional deltas. It binds 48 source-contract files at the exact refs.
   The included Frappe 16.52 public source is an API reference, not installed-image
   proof. The preserved semantic worker/CAS composition is independent.
3. Use `COMPOSE_MAP.json` to copy exactly the two new native test/helper files.
   Both paths are absent at the backend reference; verify local path ownership
   before copying. Keep the optional HTTP driver outside application routes.
4. Prepare and commit the dedicated fixture before suite execution through the
   existing local fixture runner. Run the declared module with the local native
   runner on the admitted isolated synthetic RC profile. Preserve stable/RR data.
5. Fill `NATIVE_TEST_RECEIPT.template.json` only from actual local observations.
   Attach source/image hashes, runner reports, original/recovered receipt JSON,
   canonical Field records and exact DB/File rollback evidence.

`NATIVE_PROOF_PLAN.md` defines independent-connection duplicate/revocation/base
races, unknown-response/restart and native late-failure work. Those are pending
separate local proofs; a second connection cannot see the rollback-only case
fixtures. Browser vault/privacy, production performance and provider/model
acceptance are also outside this preparation.

## Static evidence and preservation

`STATIC_PREPARATION_RECEIPT.json` and `static-preparation-final.log` report only
syntax, source-guard and pinned-source hash checks. All 18 native cases and all
HTTP journeys remain UNRUN. No native pass count is claimed. To repeat these
static checks after fetching the bundle, set `CIPHER_CONTRACT_CHECKOUT` to a Git
checkout containing both pinned refs and run `python check_prepared_bundle.py`.
The script compiles without importing the prepared probes.

Independent source review is included. The receipt template contains no invented
runtime IDs, SQL results, image hashes or passed assertions. Hash manifests bind
the final files and the new destination paths.

The cloud restart removed the prior unpublished `/tmp` and `/dev/shm` drafts.
This unfinished bundle was reconstructed from the immutable refs; no completed
package was restarted or replaced. Published DOC03/DOC04/FLD02/worker refs remain
preserved. The prior award rejection remains in force with no retry on any host
or route; dependent procurement/finance rollout stays blocked.

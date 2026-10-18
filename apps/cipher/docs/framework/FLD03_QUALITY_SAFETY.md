# FLD-03 source handoff

Source base: `0147603655624c3ad66ef73f6921a06805abff9a`. Working directory: external `cipher-local/lane-work/field-quality-safety-narrow`. The initial broad archive completed before the narrow-archive correction; it is preserved untouched at `field-quality-safety` and was excluded as a design input. No shared Windows source, live Linux source, product UI, Docker/database/provider, cloud VM, runtime installation, push, award command or financial writer was used.

## Implemented documentary scope

| Record | Authored facts | Independent decision |
|---|---|---|
| Inspection | Source-backed observation, date/location and required closure items | Check and evidence-bound closure |
| Deficiency | Source-backed finding and specified correction/evidence requirements | Check and evidence-bound closure |
| Safety observation | Documentary observation and specified follow-up evidence | Check and evidence-bound closure |
| Restricted incident | Restricted involved-person/account/response fields; exact private or explicitly non-sensitive shared evidence | Separate incident duties, independent check/closure and private history |
| Permit record | Authored issuer/identifier, offset-bearing period and recorded conditions | Documentary check/closure only |

Stable headers point to immutable revisions and decisions. Expected header digests reject stale commands. Closed originals amend by successor with predecessor, prior-decision and last-closed-original lineage. Checking excludes the revision's canonical author; closure excludes both author and checker, including alias logins. Closure requires current readable/ingest-authorized exact evidence for every authored closure item. No lifecycle transition has commercial, payment, payroll, award, professional, regulatory, hazardous-work or medical effect.

## Privacy and integration

Ordinary and incident native storage is separated. All seven new native types have empty generic role permissions and explicit deny hooks. Incident lists/count attempts require restricted duty before storage/cursor work. Cursor identity includes canonical person, login, scope, filters and current authority fingerprint. Incidents/private uploads emit no ordinary Project history events.

Private evidence is registered before original canonical bytes are created, through one separate upload command requiring explicit incident evidence management plus current document write/rights authority. Existing ordinary sources are never reclassified. Known ordinary duplicate bytes are refused; declared exact non-sensitive ordinary revisions remain reusable. Current document-rights policy must separately permit ingestion. Native privacy/provenance guards and SQL prefilters protect direct documents, File linkage, previews, citations, search, document-control rights/lifecycle derivatives and source history. Generic command receipt reads must dispatch to the domain authorizer.

All shared changes remain reviewable external fragments. The integration writer must apply them together, regenerate OpenAPI and perform native qualification before release. Native File guards already block direct download/zip; the added source privacy guard must remain in the canonical provenance path rather than being applied only in the UI.

## Verification evidence

26 focused host tests passed, including actual FLD-03 services/controllers and canonical `DocumentService` derivative access. Cases cover author/checker aliases, third-person closure, missing/wrong/duplicate item evidence, exact original metadata/bytes, revoked read/ingest duty, private-source admission, current permission proof, historical return, amendment originals, operation payload conflicts, replay original facts, cursor identity and late receipt rollback. Closed request/response schemas were checked against all five actual category lifecycles and the private upload result. All native controller source files parse successfully.

The WSL host composition ran 104 cases. The unchanged original baseline failed one stale test at `tests/test_engineering_contracts.py:89`: it asserted the historical string `sorted(PROJECT_ABILITIES - ENGINEERING_ABILITIES - DOCUMENT_CONTROL_ABILITIES)` even though source deliberately also subtracts `FIELD_ABILITIES` and `SEMANTIC_ABILITIES`. The separate test-only patch evaluates the actual default-grant AST using actual capability sets, checks the exact safe grant set and absence of all special groups, and retains an ordinary `project.write` check. No production grant was widened and the original shared test is unchanged.

Replacing only that test module with its external corrected successor produced **104 passed in 15.232 seconds** using the existing `/home/travisstaib/cipher-host-validation-venv/bin/python`, without installs or bench Python. The exact output is `fragments/fld03-quality-safety/host-successor-104.txt`. Windows broad document tests additionally encountered existing PDF-helper availability and symlink privilege limitations; WSL resolved those environment-specific failures. The initial Windows compileall cache write hit long-path cache limits; all 27 relevant Python sources were subsequently parsed without cache writes.

An independent read-only reviewer approved the final source/fragments and independently reran the 26 focused cases. The review caught malformed selectors, a document-control private rights/lifecycle derivative bypass, omitted exact permission metadata verification and a potential native Int normalization issue. All were corrected; the native regression ordinary actor has document-control access and lacks incident access.

## Qualification still required

Four prepared native cases cover actual migration/index/controller persistence, three-Person closure/amendment, private source/derivative/native query and File denial, revoked generic receipt reads, late native transaction rollback and documentary permits. They have not been run. Native HTTP/session/CSRF, restart/concurrency, File deduplication and orphan cleanup, simultaneous ordinary/private duplicate-hash admission, browser/UI, accessibility and operational/enterprise acceptance remain unqualified. Do not enable private uploads until native transaction/File/duplicate-admission proof is recorded. Existing-source migration/declassification and semantic validation of a user's non-sensitive statement are unsupported. No final native acceptance or package-completion claim is made.

# DOC04 canonical source host verification

These records transcribe terminal output already observed during the source
adapter work. The source files were frozen after the successful composed run;
the unchanged tests were not rerun solely to obtain a log file. No provider,
native Frappe runtime, embedding, ranking, or connected qualification is claimed.

Working directory for every command:
`/dev/shm/cipher-doc04-semantic-20261017/workspace`

## Focused successful source run

Command:
```sh
PYTHONPATH=apps/cipher/platform/apps/cipher_aec python -m unittest cipher_aec.tests.test_semantic_source -q
```
Observed output (transcribed from tool result):
```text
Ran 25 tests in 0.239s

OK
```
Tool exit code: 0. The original stdout was only returned in the tool transcript;
this file is a later transcription, not the original terminal capture.

## Composed successful source/regression run

Command:
```sh
PYTHONPATH=apps/cipher/platform/apps/cipher_aec python -m unittest cipher_aec.tests.test_semantic_source cipher_aec.tests.test_documents cipher_aec.tests.test_documents_source_scope cipher_aec.tests.test_document_control_shared cipher_aec.tests.test_document_control_lifecycle -q
```
Observed output (transcribed from tool result):
```text
Ran 76 tests in 0.988s

OK
```
Tool exit code: 0. The original stdout was only returned in the tool transcript;
this file is a later transcription, not the original terminal capture.

## Preserved initial failures and corrections

The initial focused command above ran 24 cases and failed with 1 failure and 26
errors. The host source fixture had three issues: importing the adapter at test
collection created a document-control package that an existing nested fixture's
teardown did not handle; issue authorization lacked distribute permission in the
fixture; and an assertion incorrectly prohibited loading authorized permission
evidence when ingest was denied on the selected source. The fixture now isolates
its document-control module lifetime, grants issue prerequisites, and asserts the
selected revision remains unread while allowing independently authorized evidence.

An intermediate focused run had 23 passing cases and one lifecycle-fixture error:
DOC03 lifecycle exact references require UUID identifiers, whereas DOC02 upload
mints `DOC-`/`REV-` names. The lifecycle host fixture now explicitly supplies UUID
metadata identities while preserving real DOC02 extraction, immutable filesystem
bytes, and source/citation readers. Production source naming was not changed.
The separately added supersession case brings the focused total to 25.

The first composed command above ran 76 cases and failed with 24 teardown errors.
A top-level adapter import retained the document-control package during collection
and exposed the same existing nested-fixture teardown assumption in later DOC03
tests. The source test module now imports the adapter lazily inside its isolated
fixture. The exact same composed command subsequently passed all 76 cases as
recorded above. No shared test fixture was modified.

## Actual checkpoint persistence/controller host tests

Command (with actual stdout/stderr capture):
```sh
PYTHONPATH=apps/cipher/platform/apps/cipher_aec python -m unittest cipher_aec.tests.test_semantic_index_store -q > /dev/shm/cipher-doc04-semantic-20261017/source-work/store-focused.log 2>&1
```
The saved `store-focused.log` contains the final focused result: 17 cases passed,
0.023 seconds, exit code 0. This run followed a test-only package-attribute cleanup
improvement, so it was a changed-fixture verification rather than an unchanged
rerun solely for logging.

The initial store command ran 17 cases and all 17 errored in fixture setup because
the restoration helper attempted to split the root module name `frappe` into a
parent/attribute pair. The helper now skips root module names and separately
retains package ancestors. No persistence implementation was changed by this
agent. An intermediate fixed-fixture run passed all 17 in 0.026 seconds before
the final ancestor-restoration improvement.

The host double executes the actual `semantic_index.store.FrappeStore` and
`CipherSemanticCorpus` controller, including private write-plan validation,
READ-COMMITTED admission, CAS, exact native profile/scope/hash/version matching,
and the new dedicated-worker transaction admission. Request stores never commit;
durable stores require the explicit private worker context and zero known prior
transaction writes at construction and each save. Actual Frappe/MariaDB/worker
isolation and queue qualification remain pending; no native/provider claim is
made by these tests.

## Actual DOC02 names: precise DOC03 lifecycle dependency regression

After root review, one additional regression was authorized in the source test
file. Focused source coverage is now **26 tests**, not 25. The initial 25-case
and composed 76-case results above remain historical results for their earlier
file versions; the changed 26-case source result is captured directly in
`source-actual-native-names.log`.

Command:
```sh
PYTHONPATH=apps/cipher/platform/apps/cipher_aec python -m unittest cipher_aec.tests.test_semantic_source -q > /dev/shm/cipher-doc04-semantic-20261017/source-work/source-actual-native-names.log 2>&1
```
Observed result: 26 tests passed in 0.252 seconds, exit code 0.

The new regression uses actual DOC02-uploaded `DOC-...` and `REV-...` identities,
without the UUID metadata substitution used in the separate lifecycle fixtures.
It proves that the initial canonical `issued` selector read succeeds and remains
unchanged, while DOC03 withdrawal preparation refuses its Document name safely
before any documentary state/evidence/receipt mutation. The same retained issued
reference is refused by the lifecycle replay validator because its Revision name
is not a UUID. Both refusals are `DomainError('invalid_engineering', ...)`.

The distinction matters: `lifecycle.issue_ref` itself does not enforce UUIDs, so
an initial issued selector is not blocked. `lifecycle.request` checks its native
Document name with the documentary UUID validator, and `_reference` applies that
validator to native Revision names during lifecycle verification. This is an
existing shared local composition dependency gap, not a provider qualification
result and not a claim that actual-name lifecycle mutations work.

`DOC03_NATIVE_NAME_COMPATIBILITY.patch` contains an unapplied two-line proposal:
use the existing bounded 140-character native-name text validation for Document
and Revision identifiers in those two checks. Documentary issue IDs, lifecycle
event IDs, request IDs and all hash/current-authority/approval checks retain their
existing validators. No actual DOC03 implementation file was modified. The local
coordinator must review/apply the proposal in its shared composition workspace
and qualify actual-name lifecycle preparation, independent approval, withdrawal,
supersession and subsequent canonical issued reads there.

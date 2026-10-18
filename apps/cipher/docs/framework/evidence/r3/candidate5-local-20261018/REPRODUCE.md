# Candidate5 host gate reproduction

The published application contains 523 of the recorded host tests. This folder
adds the exact 16 worker-transaction and five CAS-composition host regressions,
giving the recorded **544 tests**, followed by OpenAPI verification. Neither test
module has been changed. Three captured Frappe reference sources and their MIT
license are the only extra runtime inputs those 21 tests require.

From the repository root, using the host Python environment described in
`HOST_ENVIRONMENT.json`, run:

```sh
python -B apps/cipher/docs/framework/evidence/r3/candidate5-local-20261018/run_host_gate.py --repo-root .
```

The runner creates a new temporary output folder and prints its reproduction
receipt path. An optional `--output-dir PATH` selects a new external result
folder. The folder must not already exist. The runner installs no dependencies,
rewrites no source and starts no services.

It verifies all 914 frozen application file hashes, allows only equivalent UTF-8
LF/CRLF checkout bytes, checks the exact bundled regression/reference hashes,
and invokes the unchanged module/flag arguments in `HOST_GATE.json` using the
current Python executable. It sets `PYTHONPATH` to the published app and this
folder's `semantic-host` directory and sets `CIPHER_SEMANTIC_SOURCE_ROOT` to the
chosen repository root. All 544 tests run in one process. It then checks OpenAPI
and verifies application source hashes again. New evidence files may coexist
with the original 914 application files; they are not added to that source freeze.

`HOST_GATE.json` and the adjacent two logs preserve the original recorded argv,
result and log hashes. Its original Python path is historical; the runner uses
the selected interpreter without changing the remaining arguments. The source
archive is intentionally omitted; `SOURCE_FREEZE.json` records its exact hash,
and `SOURCE_MANIFEST.json` binds the 914 published source files.

These tests execute Cipher code with explicit host projections for persistence,
identity and providers and AST-extracted Frappe callback/transaction/job methods.
They do not execute an installed Frappe site or connect to embedding/vector
providers. Candidate5 native/provider/browser qualification remains unrun. A
future source/image admission must remain separate from the original inert v3
executor receipt. QuickBooks remains official; awards and dependent rollout stay
held. No credentials, runtime inspection dumps, private configuration or source
archives are included in this evidence folder.

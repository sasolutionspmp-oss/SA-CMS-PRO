# Semantic worker transaction repair — source candidate

Base: `a3577803e09e72b9af22178bdd9c4d1225536485`.
Repository: https://github.com/sasolutionspmp-oss/SA-CMS-PRO.

This is an external functional patch and host evidence, ready for local source
composition. It has **not** been installed or natively qualified. The published
ref adds artifacts only; its application tree remains the pinned base. Earlier
DOC03, DOC04, FLD02 and independent DOC03 review refs remain unchanged.

## Problem and repair

Frappe `execute_job` commits ordinary return values. Returning `blocked` after a
caught domain error could therefore commit a partial semantic checkpoint and its
callbacks. `SemanticService.run` can also attempt a recovery checkpoint before
the outer worker catches the original persistence failure.

The patch admits only a matching semantic background job/site with no request
object, an unopened actual Frappe database wrapper, integer-zero write/control
counters, and four empty, supported callback managers. Existing connections,
reads/savepoints, dirty work, callbacks and nested ownership refuse before any
user change or transaction control. Admission failures propagate; the worker
does not turn them into a normal successful job return. Frappe's surrounding job
runner retains its own exception policy.

After admission, the worker opens that fresh connection and verifies actual
READ-COMMITTED. It never changes isolation, site configuration or server settings.
An RR or unverifiable connection refuses before provider work. The lease binds
the actual database, physical connection, job object and its method/site, and the
transaction lifecycle. External transaction control, unsupported administrative
SQL, batches and executable SQL comments invalidate/refuse the lease. Ordinary
read/write/meta queries and quoted document semicolons remain supported.

Only a successful owned checkpoint commit renews the lease. Native cache/realtime
callbacks acquired within the exact checkpoint write may run; preexisting or
pre-save foreign callbacks and added precommit/rollback callbacks refuse. Every
durable load/save checks ownership. A failed durable save performs a full owned
rollback before service recovery can read/save through the stale store. Prior
committed checkpoints survive; their original operation and point IDs are reused.

Owned domain errors return a safe code only after rollback. Unverifiable or failed
rollback/cleanup raises `UnsafeWorkerTransaction`, rather than returning blocked.
Cleanup targets the exact owned connection/managers and restores private contexts,
wrapped methods and the original user/SID/session/cache fields on every path.

## Apply and dependencies

`SEMANTIC_WORKER_TRANSACTION_REPAIR.patch` changes exactly these paths below
`apps/cipher/platform/apps/cipher_aec/cipher_aec/`:

| Path | Change |
| --- | --- |
| `semantic_index/transactions.py` | New exclusive ownership and transaction boundary |
| `semantic_index/worker.py` | Admit before identity changes; rollback before blocked return |
| `semantic_index/store.py` | Bind durable stores; abort native save faults before recovery |
| `tests/test_semantic_index_store.py` | Reject obsolete counter-only admission; isolate the new module |

`PATCH_SOURCE_MANIFEST.json` pins every preimage and candidate hash. The patch
passed `git apply --cached --check` against a separate index of the exact base.
Check these preimages on the local repair checkpoint before composition; no
cloud rebase/reset or native change is required.

The local first-insert `DuplicateEntryError` → `semantic_conflict` patch remains
independently owned and is **not included**. Compose its narrow insertion handler
inside the new `FrappeStore._save`; preserve the outer durable `save` abort fence.
The native insert branch, checkpoint validation, controller/private plan and
trusted-write rules remain intact. The service, source adapter, provider clients,
configuration schema, API catalog, deployment and other feature lanes are unchanged.

The older store fixture lacks actual job/connection/callback evidence, so its
former Boolean-only positive case now explicitly refuses. Stronger positive,
denied, fault and recovery paths live in the external transaction suite.

## Host evidence

- `final-combined-56-host.log`: 56 passing tests in one process, including the
  existing 40 service/store cases and 16 transaction cases. This also exercises
  fixture/module restoration with the bundled native reference files.
- `host-regression-frozen-final-baseline-fail-first.log`: the identical 16-test
  transaction suite produces 76 expected failing subcases on the pinned baseline.
- `host-regression-frozen-final-green.log`: all 16 transaction cases pass against
  the candidate. Coverage includes both workers, post-write and commit faults,
  callback/savepoint contamination, prior-job/connection refusal, session recovery,
  CAS winner preservation and repeatable operation/point IDs.
- Independent source and final confirmation are included. The reviewer did not
  claim independent native execution.

The host harness executes actual Cipher worker/store/controller/service code.
CallbackManager, native transaction methods and `execute_job` are AST-extracted
from the bundled Frappe reference source. SQL, persistence, identity and providers
are explicit host projections. Captured Frappe source hashes are references, not
proof of the current local image. Initial diagnostic logs remain in
`INITIAL_LOGS.tar.gz` with their hash inventory. One retained old-fixture failure
was corrected by the explicit admission/fixture change described above.

After applying the patch to a selected checkout, run the standalone suite with:

```sh
export CIPHER_SEMANTIC_SOURCE_ROOT=/absolute/path/to/checkout
PYTHONDONTWRITEBYTECODE=1 python /path/to/test_worker_transactions_host.py -v
```

For the intentionally red baseline, run `python /path/to/run_pinned_baseline.py -v`
with the same checkout variable. Its import loader reads the exact base worker
and store with `git show`; it does not reset or edit the checkout. No runtime or
dependencies are installed by the harness. Native proof is defined in
`NATIVE_PROOF_PLAN.md`.

Provider/site schema remains disabled. No cloud site/database/runtime/provider,
award or dependent procurement/finance action was performed. The prior automatic
award rejection remains in force; it was not retried by another host or route.

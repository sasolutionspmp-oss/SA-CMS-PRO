# Local native qualification — pending

The local integration owner alone performs these steps. This is a proof plan,
not a report that native acceptance passed. Keep the stable/RR environment and
all unrelated work preserved. No award or dependent finance/procurement route
is part of this qualification.

1. **Compose exact source.** Verify `PATCH_SOURCE_MANIFEST.json` preimages against
   the local checkpoint. Apply the four-path patch and separately reviewed native
   first-insert conflict handler. Hash the resulting app/image and record both
   patch sources. Keep semantic provider configuration/schema disabled. Verify
   the actual installed Frappe CallbackManager, database transaction methods,
   `set_user` and `execute_job` against the recorded API assumptions; host source
   captures alone do not establish image compatibility.

2. **Prove fresh connection admission.** Use the already authorized isolated
   READ-COMMITTED profile with isolation effective from physical connection birth.
   Do not issue `SET TRANSACTION`, alter an existing connection or change global
   server defaults to make this worker pass. Record the new physical connection,
   actual `@@session.tx_isolation`, actual local database object and exact job/site.
   Frappe must present an unopened wrapper at semantic entry. If a before-job hook
   has already opened it, expect refusal; do not relax the boundary. Record
   default RR refusal separately with no provider or checkpoint effects.

3. **Prove caller preservation.** Directly invoke both worker functions with a
   request object (including a falsy object), dirty work, pending callbacks,
   a prior read/savepoint or a previously used wrapper. Compare original SQL rows,
   callback queues, user/SID/session data and connection before/after. The worker
   must refuse without user mutation, commit, rollback, close or replacement.
   Test this outside the outer job runner: Frappe's own exception handling may
   otherwise control its surrounding transaction independently of this worker.

4. **Qualify successful checkpoint renewal.** On a fresh admitted RC wrapper,
   exercise real FrappeStore/controller writes with synthetic sources and bounded
   provider doubles. Verify several committed checkpoints, canonical actor/source
   checks, native cache callbacks and stable operation/generation/point IDs. Check
   actual RC before and after each commit, unchanged connection and clean callback
   queues. Confirm the final Frappe ordinary-return commit has no pending semantic
   effects and all user/session/private context fields are restored.

5. **Inject partial-write faults.** Raise after a real native insert/update but
   before store commit, then before SQL commit. Run both actual worker entrypoints
   under actual `execute_job`. Verify full current-transaction SQL rollback before
   any blocked result and no partial commit when Frappe commits that result.
   Native after-commit work must not fire; appropriate owned rollback cache cleanup
   may fire. Verify the original error survives the service's attempted recovery
   read and cannot produce a new recovery checkpoint through the aborted lease.
   Earlier successfully committed checkpoints must remain unchanged.

6. **Qualify invalidation and cleanup faults.** Test transaction APIs, raw control
   SQL, comments/batches, administrative/procedure SQL, savepoint rollback,
   callback-manager replacement, disabled transaction control, mutated/replaced
   job/site/database/physical connection and completed prior-job stores. No stale
   store may read/write or acquire a new job's transaction. Inject before/after
   rollback callback failure and physical-close/cleanup failure. These must raise
   an unsafe exception, never return a safe blocked receipt. Confirm only the
   exact owned connection is disposed and unknown replacement managers/caller
   connections remain untouched. Verify server-side rollback on physical close;
   host projections do not prove that behavior.

7. **Qualify conflicts and retry.** In two genuinely independent RC connections,
   force first-insert CAS and progress-update conflicts using the separately owned
   duplicate handler. Preserve the winner exactly; the losing worker must not
   reject or overwrite it during recovery. Resume with a fresh wrapper after lease
   expiry and verify the original operation/generation/point IDs and bounded
   checkpoints. A commit exception can have an unknown outcome: inspect durable
   status before retrying and never promise SQL rollback undoes an acknowledged
   earlier commit or a provider write.

8. **Record the boundary.** Attach exact source/image/reference hashes, isolation
   receipts, per-case SQL/callback/session diffs, original and resumed receipts,
   and actual local command/test logs. Run relevant composed host/native checks
   once after integration. Actual Ollama/Qdrant behavior and connected acceptance
   require a separate locally authorized provider qualification; source/host
   doubles here establish neither. Keep providers disabled until that step is
   explicitly part of the local qualification plan.

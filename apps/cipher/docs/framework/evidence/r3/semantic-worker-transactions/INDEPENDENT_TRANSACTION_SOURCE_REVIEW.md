# Independent semantic transaction source review

Final follow-up: `INDEPENDENT_TRANSACTION_FINAL_CONFIRMATION.md` records the frozen four-file hashes and resolves the provisional findings below.

Read-only review on October 17, 2026, against candidate base `a3577803e09e72b9af22178bdd9c4d1225536485`. No application edits, database or runtime operations, provider calls, installations, or external effects were performed. This review does not qualify a native execution.

Inspected `semantic_index/worker.py`, `store.py`, `service.py`, `configuration.py`, the native-store host tests, and existing disk copies of Frappe source. Native source observations are limited to those captured copies:

| Source | SHA-256 |
| --- | --- |
| `/tmp/cipher-company-proposals-r14/native-controller-review/database.py` | `dc9fe0620ab7ceb300bee2b5da5c247d8979727139c785bb591e0a54e3bebf15` |
| `/tmp/cipher-company-proposals-r14/native-controller-review/frappe_init.py` | `933561c566fe4bac7455554f018dd05395f6125111d733ee0a3f3720918c65a4` |
| `/tmp/cipher-ai04-stage-a/pinned-runtime-source/background_jobs.py` | `45d721dbb4efb0b609831f2e578c219aba4d1010faa35a9672d41e4e978568bc` |

## Source findings

1. `execute_job` commits any ordinary returned value in its `else` branch (lines 300–306). A returned blocked dictionary therefore does not request rollback. The current worker's caught `DomainError` can be followed by native commit of partial persistence and pending callbacks.
2. `transaction_writes == 0` proves neither ownership nor freshness. The native database initializes it to zero and resets it on SQL commit/rollback. Plain reads, a changed connection, commit, rollback, and an existing callback-bearing transaction can all retain zero. The current context Boolean can authorize an unrelated database object and remains true after transaction replacement.
3. Native `commit` resets rollback callbacks, runs `before_commit`, commits, starts a new transaction unless chaining, clears `value_cache`, then runs `after_commit` (database.py 1176–1194). Full `rollback` resets commit callbacks, runs rollback callbacks, rolls back and starts/chains a fresh transaction, clears the cache, then runs `after_rollback` (1196–1215). Savepoint rollback preserves commit callbacks. There is no native generation counter in this inspected implementation.
4. Native `begin()` emits `START TRANSACTION`; it must never be used to establish ownership before excluding foreign work because starting a transaction can implicitly commit an existing one. `close()` only closes and clears `_conn` and `_cursor`; it does not reset callback managers or the write counter.
5. `frappe.db` is a local proxy. Bind the actual `frappe.local.db`, its physical `_conn`, the ownership record, and a controlled transaction generation. `frappe.connect(set_admin_as_user=False)` constructs and assigns a fresh native database object using configured connection fields without changing the current user (frappe_init.py 230–281). The captured files do not establish the MariaDB-specific connector's default isolation behavior.
6. Native `frappe.set_user()` changes session user, SID, session data, caches, form data, user permissions, role permissions, and templates (382–395). Calling it before rejecting HTTP/request entry changes caller context even if the username is later reset. Calling `set_user(previous)` does not restore the original session SID/data.
7. `SemanticService.run` catches persistence exceptions and attempts a recovery checkpoint through the same store. A failed native save can have partial SQL/hook effects before it raises. The durable save boundary must roll those effects back before any recovery read/write, or invalidate that store and prevent recovery from committing them. A later outer worker rollback is insufficient if the recovery checkpoint itself commits first.

## Conservative acceptance conditions

- Reject HTTP/request entry, nested semantic ownership, dirty foreign transactions, unknown counter/callback state, and pending callbacks before changing user, issuing transaction control, replacing a connection, or rolling anything back.
- Establish an explicitly fresh worker database/physical connection and transaction, verify actual READ-COMMITTED without changing server/session/configuration isolation, and refuse unverified/REPEATABLE-READ defaults before providers or checkpoint writes.
- Bind every durable constructor/load/save to the current ownership record, actual database/connection and live transaction generation. A public/foreign commit, rollback, close/reconnect or local database replacement must invalidate existing proof; a durable store must not revive merely because the write count returns to zero.
- Renew proof only through controlled successful semantic checkpoint commits. Support multiple checkpoint commits in one service run while preserving committed progress and stable point IDs. Failed partial checkpoints roll back only owned current work; previously committed checkpoints remain durable.
- Roll back owned DomainError work before returning `blocked`; preserve pending callback cleanup, private plan, trusted-write and user/session restoration on every exit path. Do not roll back denied foreign work.
- Treat commit failures as potentially unknown outcomes, invalidate the affected generation, and avoid an unguarded recovery checkpoint. Reject stale stores on reads as well as writes.
- Exercise host tests with realistic callback/write-counter/connection lifecycle doubles. Native proof remains required and separate. The independently owned first-insert duplicate-to-conflict patch is outside this review's edit scope.

## Proposed direction review

Root proposed refusing admission unless the actual `frappe.local.db` is unopened (`_conn is None`), has no observed query history, has integer-zero write/control counters, has empty callback-manager deques, matches the exact Frappe semantic job and site, and has no request attribute. This avoids replacing or controlling any foreign connection and is conservative: native `frappe.connect()` constructs a database wrapper without opening the physical connection. A `before_job` hook that opens it intentionally causes refusal. Root would then open that fresh connection, verify READ-COMMITTED, begin the owned transaction and bind database/connection/job/site/epoch proof. This is source-feasible subject to actual-image API verification.

Two additional constraints were sent to root:

1. Refusing every callback added after admission would prevent ordinary native saves. `Document.run_post_save_methods` calls `clear_cache` (document.py 1467–1468); native `clear_document_cache` registers a cache-clear callback in both `after_commit` and `after_rollback` (2333–2335). `notify_update` also schedules after-commit realtime work by default. Foreign callbacks must be absent at admission and before the owned save, while callbacks legitimately created inside that exact owned native-save bracket require deliberate handling. A supported `notify_update=False` document flag avoids realtime but does not eliminate cache callbacks.
2. A precommit lifecycle guard must refuse unauthorized commits before SQL commit, not merely mark the lease stale after committing. Failed rollback callbacks can prevent native SQL rollback; disabled transaction control can silently make rollback a no-op. Do not return a safe blocked result without an owned abort/physical-close guarantee. Any failure fallback must invalidate the lease and clean only owned callbacks/context.

The inspected base Database mentions a lazy `last_query` attribute in a comment but does not assign it; its absence alone is not proof of an unopened wrapper.

## Candidate code review

Reviewed the initial candidate `transactions.py`, `store.py`, and `worker.py` under the task root. The main control flow separates caller admission from owned rollback, catches durable save failures before service recovery, preserves completed checkpoint commits, and restores worker user/session fields. The native lifecycle calls and controlled multi-checkpoint renewal are consistent with the captured Database implementation.

Required findings sent to root:

- Whitespace token splitting let `COMMIT/*comment*/` and `ROLLBACK/*comment*/` bypass the SQL control fence. MariaDB executable `/*M!...*/` comments were also stripped as ordinary comments. Root reported fixing both with a leading-identifier match and explicit executable-comment refusal.
- Failed-abort cleanup used unguarded callback-manager resets and release operations. A replaced/malformed manager could mask `UnsafeWorkerTransaction`, skip later cleanup, and cause a second close on an already closed physical connection. Disposal must be best effort for each manager/method while preserving the unsafe error. Replaced manager identities should cause physical owned-connection disposal rather than running unknown rollback managers.
- Admission should establish callable callback-manager `add/run/reset` APIs before opening the connection, in addition to inspecting an empty deque. Unknown callback-manager shape should fail before mutation.
- The literal initial request-presence proposal was stronger than `getattr(request, None) is not None`. Final review accepts absent/`None` as no active request because no inspected source establishes HTTP work represented by `None`; every actual request object, including falsy objects, is rejected. Job identity checks now revalidate the bound job's exact method/site fields, in addition to object identity.

No candidate files or application files were edited by this reviewer. Actual-image source matching, host test completion, and native proof remain owned by root and pending this review.

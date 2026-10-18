# FLD02 native qualification — prepared, unrun

No native case or HTTP journey in this bundle has run. Compile and source checks
are preparation evidence only. The local integration owner executes the cases
after composing FLD02/FLD03, private native guards, hooks and schema joins.

## Source and fixture admission

1. Compare `SOURCE_CONTRACTS.json` with the selected local image. The reference
   backend is `310a946bd34d06c9f7c1a3d96ab7274733142cd9`; FLD02 contracts are pinned
   to `392a19f8c01b4253a5aaeaa99878408d394dc9cb`. Local functional fixes remain
   independently owned. Record their exact source/image hashes rather than
   overwriting them with this reference source.
2. Confirm Frappe 16.52, the three offline DocTypes and additive indexes, the
   offline summary-receipt/history dispatch, canonical Field receipt dispatch,
   private read/list/export guards, and all eight API/schema joins. Run migrations
   before the test suite. The included public Frappe source is an API reference,
   not evidence that the current local image matches it.
3. Use the authorized isolated synthetic RC profile. Verify actual connection
   isolation and preserve the stable/RR environments. These tests do not change
   server defaults, connection isolation, site policy, award authority or providers.
4. Complete the existing base Company/Admin fixtures before suite setup. Invoke
   the separate FLD02 fixture preparer as Administrator through the local fixture
   runner and commit that preparation before tests. It prepares only dedicated
   `synthetic.example` users/Persons and their alias bindings. It grants no Project
   duties. Per-case tests use fresh Projects and explicit abilities; no setup
   wizard, migration, DDL, seed or commit belongs inside a case savepoint.
5. Copy only the new test files listed by `COMPOSE_MAP.json`. Execute the declared
   IntegrationTestCase module with the existing local native test runner. Capture
   individual case results, exceptions and exact DB/File rollback verification.
   A test that fails import/setup is not a passed denial test.

## Evidence to retain

- Original and replayed canonical command receipts, their request/result hashes,
  and the exact native Field header/revision/quantity/decision records referenced
  by those receipts. Store the original before amendments/redaction. Compare
  canonical JSON and retained source-byte hashes, exact decimal strings, actor
  Person, operation UUID, scope and source lineage; counts alone are insufficient.
- Current capture projection, immutable envelope digest, offline event lineage,
  device owner and original user, replacement pointers and explicit discard state.
  A historical summary receipt can retain its original status while the current
  capture reports superseded/redacted state. Neither permits a fresh write after
  current duties, identity, device or source rights are revoked.
- Negative-case absence of a new canonical business receipt, unchanged retained
  Field originals and no unrelated Task/financial/quantity effects. Record actual
  Project status and the before/after side-effect snapshots used by the tests.
- Case savepoint rollback, restoration of user/session context, absence of owned
  File rows and removal only of proven owned orphan upload bytes. Never delete
  global file-set differences or unrelated paths. Frappe file callbacks/savepoint
  behavior needs actual local verification.
- Source/image/contract hashes and installed Frappe/connector versions. Fill the
  receipt template's observed values after execution; keep untouched cases UNRUN.

## Separate-connection proof

The rollback-only case fixtures are uncommitted. Another connection cannot see
them, so switching one global `frappe.local.db` or launching threads inside that
case cannot establish concurrent acceptance. The following remain separate local
proof tasks, not implemented or passed concurrent cases in this bundle.

Use a separately admitted isolated fixture phase with a committed, uniquely owned
Project/device/envelope and two independent native processes/connections. The
local owner must define fixture teardown/backup boundaries first: do not commit
the rollback-only tests or reset an active shared database to make this work.
Both processes use current synthetic users, actual RC connections and canonical
services, with synchronization around requests/observations rather than authority
or repository mocks.

| Proof | Synchronization and required observation |
| --- | --- |
| CC01 duplicate capture/apply | Two aliases of one Person stage identical bytes and race the same capture UUID. Accept a single canonical Field effect and original receipt; a loser may replay or receive a retryable conflict. Recover the original before any fresh command. |
| CC02 UUID collision | Race a different canonical command under the same Person/UUID. Exactly one original request owns the receipt. The other must refuse without rebinding the UUID or writing another Field record. |
| CC03 current authority | Revoke a duty, disable/reassign a participant binding or revoke the device in the other committed connection before apply's current-authority check. Demonstrate denial under actual locks and RC visibility. After an already committed effect, distinguish historical read from permission for a new write. |
| CC04 source/current base | Commit a source head/rights change or canonical Field amendment between stage/inspection and apply. Require fresh checks, no silent rebase, an unchanged original envelope and an explicit new replacement UUID where supported. |
| CC05 unknown response/restart | Let an apply response be lost after commit, preserve its UUID/payload journal, restart the client and read get/inspect plus the canonical original receipt. Never infer noncommit from a timeout or inaccessible 404. |
| CC06 native late failure | Use an independently reviewed native fault mechanism in the isolated runner, not authority mocks or a stubbed repository. Compare every affected canonical/receipt/offline row and owned File before/after the real shared savepoint rollback. Deadlock/full rollback must not be mistaken for survival of the case's savepoint. |

Deadlock/timeout results require reacquiring a fresh transaction and current
access before retrying the original operation. Do not retry a changed payload
under the original UUID. Parallelism/performance/exactly-once locking acceptance
remains pending until these independent-connection observations are attached.

## HTTP and client limits

The optional driver is a local operator tool, not an implemented browser vault.
Execute it only after the local endpoints, current session/CSRF, native tests and
fixture setup are admitted. Its private plaintext journal is an explicit test
artifact; browser encryption, profile isolation, expiry, storage quota behavior
and secure erasure remain separate client work.

An unknown POST result must remain unknown until current authenticated get/inspect
recovers the original receipt or the operator performs the specified exact-request
recovery. Network failure, denied access or 404 alone proves no noncommit. Keep
the same capture UUID and sealed payload; do not automatically apply, replay or
mint a replacement business command. Local payload discard preserves the recovery
barrier and UUID/hash tombstones, and makes no backup-erasure claim.

No provider/model/deployment/award operation is included. The prior award rejection
and dependent procurement/finance boundary remain unchanged on every host/route.

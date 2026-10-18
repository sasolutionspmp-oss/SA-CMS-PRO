# FLD02 native concurrency driver — prepared, UNRUN

This is a source-only handoff for the local integration owner. It adds no application code, API registration, runtime configuration, migration, fixture or deployment. The original backlog remains FLD-02: offline capture envelopes and explicit conflict resolution, after FLD-01 and GOV-02.

The artifact is based on published Candidate 5 `4b884afa21ca1618bd47e2107d8212d261ecc1e9`. `SOURCE_CONTRACTS.json` pins 52 relevant source files. The original FLD02 reference is `392a19f8c01b4253a5aaeaa99878408d394dc9cb`. Its direct service, contracts, records, repository and controllers are unchanged in Candidate 5; the API wrapper has changed. This harness calls the actual services and existing native document controllers, bypassing neither their authority checks nor their command guards. It does not exercise HTTP.

## What is prepared

| Scenario | Processes and intended observation | Native status |
|---|---|---|
| `stage_race` | Two existing logins for one canonical Person submit the same exact stage operation and sealed envelope | UNRUN |
| `apply_race` | Two aliases apply the same staged capture, original capture UUID and exact version | UNRUN |
| `change_before_apply` | Existing Administrator commits one declared binding/duty change before the other process starts apply | UNRUN |
| `binding_race` | Exact existing binding disable/reassignment and original apply released together | UNRUN |
| `duty_race` | Exact existing Project duty disable and original apply released together | UNRUN |

Each process opens its own fresh Frappe/MariaDB connection and checks actual site, database, Frappe 16.52.0, MariaDB, connection ID and READ-COMMITTED. The program never changes isolation. Session statement/lock timeouts affect only its fresh child connection. Reconnection, epoch drift or changed copied source refuses continuation. The parent releases the barrier only after both before-inventories and preconditions are complete and distinct physical connection IDs agree. Baseline reads do not prelock authority rows. Actual service/controller locks determine race ordering.

`inventory.py` captures full selected Field/offline/documentary/receipt/history/Project/Task/identity/duty documents, their canonical JSON facts, exact linked private File bytes, hashes and all four ordered transaction callback queues. It compares canonical command result bytes, hashes, request, scope, Field header/revision/quantity facts and the offline commit pointer. Original historical header evidence remains separate from the current header. Unsupported callbacks, external/public/missing Files, excessive inventories or other incomplete evidence withhold a claimed result.

The driver makes no automatic acceptance decision. A completed process is an observation for root review, not qualification. `PROOF_PLAN.md` defines the required comparison and failure classifications.

## Admission and use by the local owner

The default command prints `DISABLED` and opens no native connection:

```sh
python -B native_driver.py
```

The local root must prepare a private directory and manually supply an enabled lease, the exact request, current runtime/build/epoch receipts and a manifest of the actual copied sources. `GUARD_SCHEMA_EXAMPLES.json` is intentionally disabled and contains invalid placeholders. It cannot authorize a run.

Control files must be owned regular files with mode 0600 and private mode 0700 parents; symlink components, duplicate JSON keys and unexpected fields are refused. The manifest must cover every file under the actual copied app root (including existing bytecode, excluding only `.git`), the four driver sources, selected installed Frappe runtime files and any existing driver bytecode. Loaded native origins/caches must match those pins. Driver helpers are explicitly compiled from source rather than imported from cached bytecode. Launch uses `-B`; it does not delete caches. Use the physical, nonsymlink Python executable path. Root attestation is an input; actual runtime and connection checks remain separate evidence.

Use one stable, persistent private `artifact_dir` for all attempts in this qualification lane. Never rotate that directory or remove a reservation to evade an uncertain result. A root lease authorizes only its explicit synthetic users/People, Company, Project, request, change target, existing extra Person (if any), finite limits and current epoch. The driver has no authority to create/reseed users, duties, devices or captures. Stage needs an already registered active device. Apply needs a separately staged capture whose original business UUID has no receipt. Change scenarios require the existing Administrator as B; changing an existing record is deliberate and durable, without automatic restoration.

The root alone may use the following on its admitted isolated profile:

```sh
/physical/python -B native_driver.py --execute --lease /private/controls/lease.json --request /private/controls/request.json
```

No such command has been run for this bundle. No cloud runtime, native site, database, provider, model, image or HTTP call was used.

## Uncertainty and preservation

An fsynced exclusive reservation uses the native Person+operation UUID namespace across Companies, Projects, aliases and run IDs. Each child also consumes a separate exclusive start slot before loading native code. Original admission/deadline is retained for children. An existing empty, partial, unknown or completed reservation refuses another mutation attempt. Use the same stable artifact parent: this is a local-root preservation contract, not a protection against an administrator moving the journal.

`commit_started` is durable before calling native commit. An error/timeout/disconnect after that marker is uncertain; no rollback, replay, cleanup or replacement UUID follows. A precommit DomainError can roll back only the fresh child-owned transaction and records before/after evidence. Other native faults remain uncertain. The watchdog terminates only its owned child processes at the finite deadline; process teardown is not proof that a transaction did not commit. All run folders, partial inventories and reservations remain.

The root can obtain a new current lease and explicitly use `--reconcile` with the same original request and run ID. This starts one new process and reads the original UUID and capture through current-rights service paths. These reads may take native `FOR UPDATE` locks; this is no-write reconciliation, not database-enforced READ ONLY. It verifies a zero write counter and unchanged callback queues after the reads and canonical checks. Reconciliation never clears the original uncertain reservation or automatically runs another business command. Current-rights refusal remains a refusal, including when an underlying receipt exists.

## Evidence and boundaries

The guard and parent tests are pure standard-library checks. The retained fail-first log uses an explicitly permissive test-only scaffold; its failures are not a captured defect in an installed native runtime. AST/compile and pure guards do not qualify SQL concurrency, native rollback, browser offline behavior or provider integration.

`RUNTIME_REFERENCES.json` records public Frappe 16.52.0 API source references used to prepare this driver. They do not attest to any installed runtime. `PRIOR_BUNDLE_HASH_READBACK.json` preserves the resolved earlier artifact discrepancy: raw Git LF bytes hash `275b00e9…`; an LF-to-CRLF transport copy hashes `38b59f0d…`. The original `a9912688…` commit is unchanged and local admission has reconciled the transport difference.

Award execution and dependent procurement/finance rollout remain blocked by the earlier review rejection. This artifact contains no award retry, provider connection, production action or authority override. The local coordinator remains the sole native integration writer. No next package is included.

# Cipher accounting-core comparison: executable decision gates

Status: synthetic-prototype evidence, 2026-10-12, scorecard version `cipher-core-gates/2`. This is not an approval to execute anything, and it does not select an accounting foundation.

Plan reference: `CIPHER-PLAN-v1.0.md`, section 3 ("Accounting foundation decision") and section 13, decision 4 ("Choose the two serious accounting candidates and accept the hard gates/weighted scorecard"). The harness is `apps/cipher/tools/core_gates.py` and its tests are in `apps/cipher/tests/test_core_gates.py`.

**Headline:** the native core is **disqualified**. It fails 4 of the 9 hard gates (G1, G3, G4, G8) on 8 of 102 hard checks, so it is not scored. ERPNext was not evaluated. No foundation can be selected yet. Section 4 lists the 8 native-core gaps and the fix each one needs.

## 1. What was run

```
$env:PYTHONPATH = "C:\Users\TravisStaib\Claude\Projects\SA-CMS-PRO"
python -m apps.cipher.tools.core_gates --out <file>     # exit 0 only if the native core passes every hard gate
python -m unittest apps.cipher.tests.test_core_gates -v # 33 tests, OK
python -m apps.cipher test                              # full suite, 404 tests, OK
```

- **Run used for this document:** the scorecard was generated at `2026-10-12T05:35:08Z` and the CLI exited with code **1**. The environment was Windows 11 and Python 3.12.10, standard library only, on the `cipher/synthetic-prototype` working tree. The branch name comes from the assignment; git was not used to confirm it.
- **Candidates:**
  - `native_cipher` runs in-process through `apps.cipher.service.Cipher`. Every gate gets a fresh synthetic SQLite workspace. G8 uses temporary files and removes them afterwards.
  - `erpnext` reports itself unavailable: *"not provisioned: requires an isolated container stack (database, cache, Frappe/ERPNext images) and separate execution authorization"*. Every gate is therefore `not_run`. Nothing was installed, pulled or started.
- **Plugins registered at run time:** asset, banking, close, drawing, field, labor, procurement, reimbursement and schedule. The schema had 13 catalog entries. Sibling modules were changing during the session, so the numbers below belong to this run only. Re-run the CLI to refresh them.
- **How a gate reports:** each gate returns `{gate, title, status, evidence, checks, failed_checks, advisories}`. Every evidence line is prefixed PASS, FAIL or INFO and carries the numbers it observed. `failed_checks` lists stable check keys such as `g8.older_backup_no_resubmission`. A gate passes only when every one of its hard checks passes.

### What changed from the first version of this harness

The first version reported 9/9 gates passing. An adversarial review showed that this held only because failing scenarios had been downgraded to non-gating advisories, and because some checks could pass without testing anything. This version follows four rules.

1. **A failing scenario is a hard FAIL.** All five former open advisories are now hard checks. Two new hard checks were added: a raw INSERT onto a posted journal, and a raw unlock of a locked period.
2. **A refusal counts only when the expected control caused it.** The adapter declares a reason pattern for each control (immutability, period lock, write authority, release quarantine, approval reference). An error that does not match it is reported as *"not refused by the expected control"* and fails the check. Examples are malformed SQL, an unknown subject, a foreign-key error or a programming error. Patterns that match empty or generic errors are rejected.
3. **Positive controls.** Each plugin path first posts a twin subject in an open period, then the same path is driven into the closed period. The governed reopen and the governed authority claim must succeed with a recorded approval, while a fabricated reference must be refused.
4. **Nothing passes untested:**
   - A registered plugin whose probe cannot be prepared fails G4.
   - A broken employee-reimbursement scenario fails G9 instead of reconciling 0.00 = 0.00.
   - G7 compares the export against the stored audit-row count, not only against the export's own count.

The tests prove that the gates are not rigged in either direction:

- **No hidden failures:** each documented native gap is probed directly against the core, and the gate must fail exactly those checks for which the gap is present.
- **Passable:** a test-only adapter that closes the gaps (`SimulatedCoreFixes`) passes all 9 gates.
- **Broken candidates fail:** malformed tamper SQL, a dropped trigger plus a malformed INSERT, a missing subject, crashing plugin paths, failed probe setup, a truncated export, wildcard markers and a broken reimbursement scenario all fail.

## 2. Results

### Hard gates

| Gate | What it executes | Native Cipher | ERPNext |
|---|---|---|---|
| G1 Exact decimal arithmetic and rounding | Float and bool money refused. `0.1 + 0.2 = 0.30` exactly; binary float gives `0.30000000000000004`. Half-up to cents (`2.675 -> 2.68`, where float `round()` gives 2.67; `-0.005 -> -0.01`). Six allocations sum exactly to the cent. Exact string storage. Float and `NaN` journals are refused with nothing posted. **Failing:** non-finite money is accepted, and one allocation produces a negative part (section 4). | **fail** (20/22) | not_run |
| G2 Balanced and atomic posting | Refused with nothing posted: unbalanced (100.00 vs 99.99), a line with both a debit and a credit, an unknown account, a zero-value journal and a journal with no lines. A command posting 2 journals that faults after the first leaves 0 journals and no idempotency record; a rerun posts both. Every stored journal balances. | **pass** (10/10) | not_run |
| G3 Immutable corrections | Raw `UPDATE`/`DELETE` on `journals` and `journal_lines` is refused by the immutability triggers, with the reason verified, and the fingerprint is unchanged. The correction is a linked reversal with sides swapped, nets to 0.00 and leaves the original intact. A second reversal and a raw unlink are refused. **Failing:** a raw `INSERT` of a line onto a posted journal is accepted and unbalances the ledger. | **fail** (10/11) | not_run |
| G4 Period locks on every path | A closed period refuses, each with a period-lock reason: the service path (granted `bill.approve`, 18000.00), a direct ledger post, a raw header `INSERT` and a raw line `INSERT`. A locked period refuses posting, a raw `INSERT` and a governed reopen with a recorded approval. Reopening without a reference is refused. A governed reopen (`close.reopen_period`, recorded approval) works and the period accepts posting again. Plugin paths post in an open period and are refused in the closed one: `asset.post_depreciation` 1000.00, `reimbursement.approve` 412.50, `labor.approve_timesheet` 8.00 h / 680.00. **Failing:** a fabricated reopen reference and a raw unlock of a locked period are both accepted. | **fail** (17/19) | not_run |
| G5 Idempotency | Replaying an operation id returns the stored result with one journal. The same id with a 260.00 payload conflicts. Replaying the payment-release execution returns the same intent (18000.00). A second worker's op id cannot consume the approval again. Dispatching twice gives 1 transfer and 1 submission. | **pass** (5/5) | not_run |
| G6 Approval binding | A one-cent change (27000.00 -> 27000.01) invalidates. A +10000.00 change order approved at a resulting commitment of 110000.00 is refused after another change moves the base from 100000.00 to 105000.00. A re-verified payee destination and a raw destination edit after grant both invalidate the release. Control cases execute. | **pass** (6/6) | not_run |
| G7 Audit export completeness | After the golden fixture plus a linked correction: all 9 sections are present and 10/10 journals are exported with source, rule and lines. The exported journals sum to the trial balance (283500.00). Every journal has a `journal.posted` entry. The 84-entry chain verifies, including when recomputed from the exported rows, and 84 exported = 84 chain count = 84 stored audit rows. A one-character edit is detected. A raw audit `UPDATE` is refused (append-only reason). The schema manifest lists all 8 required triggers (183 in total), with 13 entries applied and all checksums matching. | **pass** (14/14) | not_run |
| G8 Restore safety | The live workspace dispatches 18000.00; the provider accepts it but the response is lost. Restoring the after-dispatch backup: the copy opens without write authority and replaying the execution is refused (`WriteAuthorityError`). After a claim backed by a recorded approval, the quarantine refuses dispatch and new releases (`ReleaseQuarantined`). Recovery finds `sim_000001` by logical op id with transfers 1 -> 1 and submissions 1 -> 1, nothing is sent afterwards, and AP reconciles. **Failing:** on a copy without authority, mutations post; a fabricated claim reference grants authority; and restoring the *before*-dispatch backup resubmits the payment. | **fail** (8/11) | not_run |
| G9 Subledger-to-GL reconciliation | After the golden fixture plus an employee claim (1234.56 approved, 234.56 payment released): AP 18000.00 = GL 2000, AR 54000.00 = GL 1100, and employee payable 1234.56 = GL 2100 across 1 claim (234.56 of it still in flight). Trial balance 283234.56 = 283234.56 over 9 journals. | **pass** (4/4) | not_run |

Totals for native: 5 gates pass and 4 fail; 94 of 102 hard checks pass.

### Weighted scorecard

The plan's weights are applied only to a candidate that passes every hard gate. **The native core is disqualified and is not scored.** No computed control-fit score and no weighted total is published for it in this run.

When the native core passes every gate, the adapter supplies these four inputs. They are labelled ASSUMPTION and are not measured:

| Criterion | Weight | Native input | Basis |
|---|---|---|---|
| Accounting/control fit | 35 | computed from the executed checks: 5 x passed / executed | Computed only when every hard gate passes |
| AEC fit | 20 | 4 | **ASSUMPTION**: the schema models commitments, SOV lines, change orders, stored materials, retainage and prime billing. Held below 5 while labor, WIP/close and field modules are being built. |
| Maintainability/upgrades | 20 | 3 | **ASSUMPTION**: standard library and SQLite only, with an append-only checksummed schema catalog. One owner-maintainer carries the whole posting, close, reporting and recovery burden (plan section 3). |
| Ownership/licensing | 15 | 4 | **ASSUMPTION**: owner-written code with no third-party runtime dependency or copyleft obligation. Held below 5 until repository ownership and licence are confirmed (plan section 2: the PRO root has no licence file). |
| Delivery cost | 10 | 2 | **ASSUMPTION**: plan section 12's native-ledger premium is 20-40 person-months ($400,000-$1.2 million) and 4-9 months. Not validated here. |

- **ERPNext:** `not_evaluated`, with no scores.
- **Comparison:** none is possible. Even after the native gaps are fixed, a native score with nothing to compare against does not select the native core.

### Advisory (non-gating, beyond a gate's specification text)

| Gate | Check | Result | Observed |
|---|---|---|---|
| G5 | A bill already in flight cannot be released a second time under a new approval | pass | A second, independently approved release of the 9000.00 bill was refused: "payment intent ... is still in progress". There was 1 intent on the bill. Dispatch then added 1 provider transfer, which is the bill's first, legitimate release. |

## 3. What the native gates do and do not prove

**On synthetic data, in this repository, at this time, the native core passes these controls:**

- exact decimal arithmetic and half-up rounding for finite amounts;
- balanced, atomic journals;
- triggers that refuse UPDATE/DELETE of posted journals, with reversal-only correction;
- period locks on the service, ledger, raw-INSERT and three plugin paths;
- logical-operation idempotency;
- version- and destination-bound approvals;
- a self-verifying, complete audit export with a schema manifest;
- restore quarantine for a backup taken *after* dispatch;
- AP, AR and employee-payable agreement after the golden fixture.

**These controls fail and are the reason for disqualification:**

- non-finite money is accepted;
- allocation is unbounded;
- a raw INSERT onto a posted journal is accepted;
- an approval reference is checked only for being non-empty, both for reopening a period and for claiming write authority;
- a locked period can be unlocked by raw UPDATE;
- write authority is enforced only at `Commands.run`;
- recovery from a backup taken *before* dispatch resubmits the payment.

`apps/cipher/BUILD_STATUS.md` describes restore quarantine as finding the pre-restore transfer without a second one. That holds only for the after-dispatch backup. The plan section 10 step 11 scenario (an older backup) fails.

**They do not prove:**

- Accounting-policy correctness. Revenue recognition, WIP, retainage classification and accruals have no controller-approved policies yet; the fixture's posting rules are fixture-only (plan sections 6 and 10).
- Financial statements, tax, multi-entity or multi-currency behaviour.
- Migration of real data, or parallel closes against the incumbent books (plan section 9).
- Production readiness: security, isolation, performance, backup operations, provider contracts, or concurrency across processes. The gates use one SQLite connection in one process.
- That every plugin path respects locks. Only asset, reimbursement and labor are driven, each with a positive control. Banking, close, drawing, field, procurement and schedule rely on the period-open triggers on every journal `INSERT`, which G4 shows firing, but their own flows are not exercised.
- Anything about ERPNext or Odoo.

A zero-failure run is evidence, not a guarantee (plan section 7).

## 4. Native-core gaps (failed hard checks in this run)

All of these need changes in files this harness does not own (`core/`, `domain/`, `service.py`). Each is pinned by a direct probe in the tests, so the gate's result tracks the core. When a gap is fixed, the gate passes that check without any change to the harness or the tests.

| Check key | Observed in this run | Fix needed (core) |
|---|---|---|
| `g1.nonfinite_refused` | `money('NaN')` returns NaN; `add_money('1.00','NaN')`, `total(['1.00','NaN'])` and `allocate('NaN',[1,1])` accept it. `sNaN` and `±Infinity` are refused, but only incidentally (`InvalidOperation`). A NaN journal is refused, also incidentally. | `core/money.D()` should reject non-finite decimals with `MoneyError`. |
| `g1.allocation_bounded` | `allocate("0.05", [1]*7)` gives `-0.01, 0.01, 0.01, 0.01, 0.01, 0.01, 0.01` against an exact share of 0.0071. The sum is exact, but the whole residual lands on one part. | Largest-remainder allocation in `core/money.allocate` (spread the residual cent by cent). |
| `g3.insert_line_on_posted_refused` | A raw `INSERT` of a 1.00 debit line onto a posted 100.00/100.00 journal in an open period was accepted. The journal became Dr 101.00 / Cr 100.00 over 3 lines with a changed fingerprint, and the trial balance went to Dr 3101.00 / Cr 3100.00 (`balanced=False`). | A schema control that seals a journal's lines once it is posted. One option is a header-held line count and total, enforced by a `journal_lines` insert trigger, added as a new catalog entry because applied entries are append-only. |
| `g4.raw_unlock_refused` | `UPDATE periods SET status='open'` on locked period G4-SVC was accepted. The period then accepted a 10.00 post (journals 1 -> 2). | A `periods` trigger refusing any change to a locked row. Optionally, also refuse a closed -> open change without a matching consumed reopen approval. |
| `g4.reopen_requires_recorded_approval` | `Ledger.reopen_period` accepted the fabricated reference `apr_gate_unrecorded_reopen`, which is not a recorded approval, and reopened the period. The governed `close.reopen_period` path works, but the ledger API below it does not check what it is given. | `Ledger.reopen_period` should resolve the reference to a consumed `close.reopen_period` approval for that period. |
| `g8.restored_copy_refuses_mutations` | On a restored copy with `effective_write_authority=False`, the console/HTTP `record_collection` action posted 4500.00 (journals 2 -> 3) and a direct `Ledger.post` posted (3 -> 4). | Enforce write authority on every mutation: in `Database.transaction()`, or in the ledger and service write paths, not only in `Commands.run`. |
| `g8.claim_requires_recorded_approval` | `claim_write_authority` accepted the fabricated `apr_gate_unrecorded_claim` and granted write authority. The same call is exposed as the console/HTTP `claim_authority` action. | Resolve the reference to a recorded, consumed `workspace.claim_write_authority` approval. Today no such operation exists, so one must be defined. |
| `g8.older_backup_no_resubmission` | Restoring the backup taken *before* dispatch: recovery reconciled 0 intents and lifted the quarantine. Dispatch then resubmitted the queued intent (submissions 1 -> 2). Transfers stayed at 1 only because the simulator honours the idempotency key; plan section 4 says the reviewed provider docs do not establish that. | Recovery reconciliation must query the provider for every intent that could have been dispatched (including `queued` intents and pending outbox rows from before the backup watermark) before any outbox replay or quarantine release. |

## 5. Plan hard gates and weights, as implemented

| Plan section 3 hard gate | Executable gate(s) | Note |
|---|---|---|
| Exact arithmetic | G1 | Includes non-finite inputs and bounded allocation. |
| Atomic posting / idempotency | G2, G5 | |
| Immutable corrections; "reject direct ledger-row edits" | G3 | Covers raw UPDATE/DELETE and a raw INSERT onto a posted journal. A raw INSERT of a new header-only journal into an open period cannot be blocked by SQLite triggers alone. G7's check that every journal has a `journal.posted` audit entry would flag one present at export time. That follows from how the check is built; it was not run as a scenario. |
| Locked-period enforcement | G4 | Service, ledger, raw INSERT, raw UPDATE of the period row, reopen and plugin paths. |
| Complete audit export | G7 | |
| Restore safety | G8 | After-dispatch and before-dispatch backups. Write authority on every mutation path, not only the command boundary. |
| Correct accounting semantics | G9 (control-balance agreement) | Semantic and policy correctness is **not** executable here; it needs controller-approved policies and an independent oracle. |
| Legally usable packaging | none | Manual licence review (section 6). |
| Approval binding (plan section 6, "Distinct authority states") | G6 | Not in the section 3 list, but treated as a hard gate because payment safety depends on it. |
| "Reject permanent QBO dependence and pervasive core patches" | none | Architectural review items, not runtime checks. |

**Weights (plan section 3):** accounting/control fit 35%, AEC fit 20%, maintainability/upgrades 20%, ownership/licensing 15%, delivery cost 10%. They sum to 100, and the harness refuses to score if they do not.

**Scoring rules:**
- A candidate that fails any hard gate is `disqualified` and not scored.
- An unavailable candidate is `not_evaluated`.
- Control fit is 5 x passed / executed over the hard and advisory checks.
- The other four criteria must be labelled `ASSUMPTION` with a rationale, or the harness raises. Non-finite or out-of-range scores are rejected.

## 6. What an ERPNext evaluation needs

1. **Authorization and isolation.** Separate execution authorization and an isolated environment: a dedicated development VM or subscription, synthetic data only, no production routes or credentials, and no host-socket or privileged containers (plan sections 3 and 8). A folder or branch is not isolation.
2. **A container stack.** ERPNext's database, cache, and Frappe/ERPNext application and worker images, pinned to exact versions. Nothing about this stack was installed, sized or verified here.
3. **An adapter.** An `ERPNextAdapter` that implements the `LedgerAdapter` operations through ERPNext's supported interfaces and returns the same shapes. It must also declare `refusal_markers` for its own controls, so a refusal is attributed to the right control. Plan section 5: where a mature core needs a separate service, the complete financial command must execute atomically inside that core, so several CRUD calls do not satisfy G2.
4. **The same synthetic corpus.** The plan section 10 golden fixture plus the G1-G9 scenarios, including the before-dispatch restore.
5. **A licensing review.** ERPNext is GPLv3 and Frappe is MIT (plan section 3). Commercial packaging and distribution need module-level review; service separation alone does not settle derivative-work obligations. This review is the "legally usable packaging" gate.
6. **Privileged-path tests.** Plan section 6 notes that ERPNext's documented reversal behaviour is useful evidence, but its supported reposting paths still need governance. The candidate must pass the same privileged-path and period-lock tests as G3/G4, including direct database writes, reposting and administrative paths.
7. **Scoring.** Score only if every hard gate passes. Odoo Community stays the plan's comparator and would need its own adapter.

Everything in this section about ERPNext's behaviour is **unverified** here. The only vendor facts used are those the plan already cites.

## 7. Local constraint: storage

- **Free space:** drive C: had about 8.7 GB free early on 2026-10-12 (8,723,419,136 bytes at the start of the first harness session). At 05:36Z the same day it had **3.4 GB** free (3,669,958,656 bytes). The owner's standing target is 250 GB free.
- **Docker:** Docker Desktop was reachable earlier the same day (client and server 29.8.2, Linux engine, read with `docker version` and `docker system df` only). It was not queried again for this revision.
- **Implication:** Docker being live does not remove the storage constraint. A multi-GB ERP stack (database, cache, application images and volumes) must not be pulled onto this machine at 3-9 GB free. Its exact size was not measured (unverified).
- **Before starting:** estimate the peak storage of an evaluation first, including images, volumes, logs and the backups for the restore drill. Run it on a host with headroom, preferably the isolated environment in section 6.

## 8. Recommended next decision

1. **Accept G1-G9 and the weights** as the Phase 0 hard-gate harness for plan section 13 decision 4. Make this CLI the single pass/fail record for any candidate.
2. **Fix the eight native-core gaps in section 4, then re-run the CLI.** They touch `core/money.py`, `core/db.py` (new append-only catalog entries for the journal-seal and locked-period triggers, plus a write-authority guard), `domain/ledger.py` (reopen reference validation), `domain/payments.py` (recovery reconciliation of queued and outbox intents) and `service.py` (a governed authority-claim operation). The harness and its tests need no change: each gap's check passes once its direct probe shows the gap closed.
3. **Authorize, or explicitly defer, the ERPNext evaluation.** If it is authorized, provision it on an isolated host with storage headroom, not this machine at 3.4 GB free. Implement `ERPNextAdapter` and run the same gates and corpus. Until then, record "no foundation selected". The native core is currently disqualified, and even a passing native scorecard would be a baseline, not a win.

## 9. Limitations of this harness

- The probes are scenario-based. A pass shows the scenarios behaved; it does not exhaustively prove each control.
- **Refusal markers** are declared by the adapter. The harness rejects markers that match empty or generic errors, but an adapter could still declare an over-broad pattern. Review each new adapter's markers. The native approval-reference marker is simply `approval`.
- **Plugin coverage in G4** is limited to plugins with a probe (asset, reimbursement, labor). A registered plugin whose probe cannot be prepared now fails the gate, so a sibling module's API change shows up as a G4 failure until its probe is updated.
- **G9** asserts the golden fixture's AP (18000.00) and AR (54000.00) totals. For the employee payable, it asserts subledger = GL with a balance above 0.00 and at most the 1234.56 claim.
- **The control-fit formula**, 5 x passed / executed, is this harness's own rule. Treat it as a mechanics score, not an accounting-quality score.
- **The payment provider** is the in-memory simulator. Every result about provider idempotency is about the simulator, not a real rail.
- **`SimulatedCoreFixes`** in the tests closes the gaps inside a test adapter, to show the gates can pass. It is not evidence about the native core.

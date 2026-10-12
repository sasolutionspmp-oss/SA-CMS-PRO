# Cipher accounting-core comparison: executable decision gates

Status: synthetic-prototype evidence, 2026-10-12, scorecard version `cipher-core-gates/3`. This is not an approval to execute anything, and it does not select an accounting foundation.

Plan reference: `CIPHER-PLAN-v1.0.md`, section 3 ("Accounting foundation decision") and section 13, decision 4 ("Choose the two serious accounting candidates and accept the hard gates/weighted scorecard"). The harness is `apps/cipher/tools/core_gates.py` and its tests are in `apps/cipher/tests/test_core_gates.py`.

**Headline:** the native core now **passes all 9 hard gates (110 of 110 hard checks)**, so it is scored. Its weighted total is **3.92 of 5 (78.37%)**. Only the control-fit input (4.91) is computed; the other four inputs are labelled ASSUMPTION. Two advisories are open. Both concern the write-authority claim on a restored copy (section 2). ERPNext was not evaluated. **No foundation can be selected:** a native score with nothing to compare it against is a baseline, not a selection.

## 1. What was run

```
$env:PYTHONPATH = "C:\Users\TravisStaib\Claude\Projects\SA-CMS-PRO"
python -m apps.cipher.tools.core_gates --out <file>     # exit 0 only if the native core passes every hard gate
python -m unittest apps.cipher.tests.test_core_gates -v # 36 tests, OK
python -m apps.cipher test                              # full suite: 841 tests, OK (expected failures=1)
```

- **Run used for this document:** the scorecard was generated at `2026-10-12T14:28:34Z` and the CLI exited with code **0**.
  - Environment: Windows 11, Python 3.12.10, standard library only.
  - Source: the `cipher/synthetic-prototype` working tree. The branch name comes from the assignment; git was not used to confirm it.
- **Candidates:**
  - `native_cipher` runs in-process through `apps.cipher.service.Cipher`. Every gate gets a fresh synthetic SQLite workspace. G8 uses temporary files and removes them afterwards.
  - `erpnext` reports itself unavailable: *"not provisioned: requires an isolated container stack (database, cache, Frappe/ERPNext images) and separate execution authorization"*. Every gate is therefore `not_run`. Nothing was installed, pulled or started.
- **Registered at run time:**
  - Plugins: asset, banking, close, drawing, field, handoff, labor, procurement, reimbursement, rights and schedule, plus the core_reconciliation pseudo-module.
  - Schema: 42 catalog entries applied, every checksum matching, 348 triggers.
  - Eight other agents were changing sibling modules during the session, so these numbers belong to this run only. Re-run the CLI to refresh them.
- **How a gate reports:** each gate returns `{gate, title, status, evidence, checks, failed_checks, advisories}`.
  - Every evidence line starts with PASS, FAIL or INFO and carries the numbers it observed.
  - `failed_checks` lists stable check keys.
  - A gate passes only when every one of its hard checks passes.

## 2. Results

### Hard gates

| Gate | What it executes (this run) | Native Cipher | ERPNext |
|---|---|---|---|
| G1 Exact decimal arithmetic and rounding | **Refused by the money control (`MoneyError`):** floats, bools, `NaN`, `sNaN` and `±Infinity` through every entry point (7 of 7 non-finite cases). **Exact arithmetic:** `0.1 + 0.2 = 0.30`, where binary float gives `0.30000000000000004`. **Half-up to cents:** `2.675 -> 2.68`, where float `round()` gives 2.67, and `-0.005 -> -0.01`. **Allocation:** six cases sum exactly, and every part is non-negative and within one cent of its share (`0.05` over 7 gives `0.01 x5 + 0.00 x2`). **Storage:** exact string storage. **Journals:** float and NaN journals are refused by the money control with nothing posted. | **pass** (22/22) | not_run |
| G2 Balanced and atomic posting | **Posting path, refused with nothing posted:** an unbalanced journal (100.00 vs 99.99), a line with both a debit and a credit, an unknown account, a zero-value journal and a journal with no lines. **Command atomicity:** a 2-journal command that faults after the first leaves 0 journals and no idempotency record; a rerun posts both. **Privileged path, refused by the journal seal:** a raw header with no declared line count; a raw journal declaring 2 lines that commits with 1 (*"holds fewer lines than its sealed line count"*); a raw 2-line journal with Dr 100.00 / Cr 99.99 (*"journal does not balance"*). **Result:** every stored journal balances (TB 1200.00 = 1200.00). | **pass** (13/13) | not_run |
| G3 Immutable corrections | **Raw tampering:** `UPDATE`/`DELETE` on `journals` and `journal_lines` is refused as immutable, and the fingerprint is unchanged. **Governed correction (`journal.reverse`):** the correction is a linked reversal with sides swapped, carrying a consumed approval. It nets to 0.00 and leaves the original intact. **Refused:** a second reversal and a raw unlink. **Raw line INSERT onto a posted journal:** refused (*"the journal already holds its sealed line count"*); the journal stays Dr 100.00 / Cr 100.00 over 2 lines and the TB stays balanced. | **pass** (12/12) | not_run |
| G4 Period locks on every path | **Closed period, each refused with a period-lock reason:** the service path (granted `bill.approve`, 18000.00), a direct ledger post, a raw header `INSERT`, and a raw line `INSERT` (refused by the seal). **Locked period, refused:** posting, a raw `INSERT`, a governed reopen and a raw unlock (*"locked periods are immutable"*). **Reopen without a valid approval, refused:** no reference, a fabricated reference, and a raw `UPDATE` citing the fabricated reference. **Positive control:** a governed reopen (`close.reopen_period`) works, and the period accepts posting again. **Single use:** that consumed approval cannot reopen the period again (ledger path or raw `UPDATE`) or reopen another closed period; the period still has exactly 1 recorded reopen. **Plugin paths:** each posts in an open period and is refused in the closed one: `asset.post_depreciation` 1000.00, `reimbursement.approve` 412.50, `labor.approve_timesheet` 8.00 h / 680.00. | **pass** (21/21) | not_run |
| G5 Idempotency | **Replay:** replaying an operation id returns the stored result with one journal, and the same id with a 260.00 payload conflicts. **Payment release:** replaying the execution returns the same 18000.00 intent, and a second worker's op id cannot consume the approval again. **Dispatch:** dispatching twice gives 1 transfer and 1 submission. | **pass** (5/5) | not_run |
| G6 Approval binding | **Invalidated:** a one-cent change (27000.00 -> 27000.01). **Refused:** a +10000.00 change order approved at a resulting commitment of 110000.00, after another change moves the base from 100000.00 to 105000.00. **Destination:** a re-verified payee destination and a raw destination edit after grant both invalidate the release. **Control cases** execute. | **pass** (6/6) | not_run |
| G7 Audit export completeness | **Setup:** the golden fixture plus a governed correction. **Contents:** all 9 sections, and 10/10 journals with source, rule and lines. The exported journals sum to the trial balance (283500.00), and every journal has a `journal.posted` entry. **Chain:** the 101-entry chain verifies, including when recomputed from the exported rows (101 exported = 101 chain count = 101 stored rows). A one-character edit is detected, and a raw audit `UPDATE` is refused. **Schema manifest:** all **15** required control triggers are listed, with 42 entries applied and all checksums matching. | **pass** (14/14) | not_run |
| G8 Restore safety | **Live workspace:** dispatches 18000.00; the provider accepts it but the response is lost. **Restored after-dispatch copy:** it opens without write authority, and replaying the execution is refused (`WriteAuthorityError`). **Refused on an unclaimed copy, all by SQLite's read-only guard:** the console/HTTP `record_collection` (otherwise valid, with an ACH mandate on file), a direct ledger post, a raw `INSERT`, and `PRAGMA query_only = OFF`. **Claims:** a claim with a fabricated or blank credential is refused. An attested claim (approver, reason, verified owner claim code) grants authority in quarantine; replaying its code is refused. **Quarantine:** it refuses dispatch and new releases. **Recovery:** it finds `sim_000001` by logical op id (transfers 1 -> 1, submissions 1 -> 1); nothing is sent afterwards, and AP reconciles (0.00 = 0.00, the bill paid once). **Before-dispatch backup:** recovery looks the queued intent up at the provider and records it as accepted. Dispatch then sends nothing (0 resubmissions). | **pass** (13/13) | not_run |
| G9 Subledger-to-GL reconciliation | **Setup:** the golden fixture plus an employee claim (1234.56 approved, 234.56 payment released). **AP:** 18000.00 = GL 2000. **AR:** 54000.00 = GL 1100. **Employee payable:** 1234.56 = GL 2100 across 1 claim (234.56 of it still in flight). **Trial balance:** 283234.56 = 283234.56 over 9 journals. | **pass** (4/4) | not_run |

Totals for native: 9 gates pass and 0 fail; 110 of 110 hard checks pass.

### Weighted scorecard

The native core passes every hard gate, so the plan's weights apply:

| Criterion | Weight | Native score | Weighted | Basis |
|---|---|---|---|---|
| Accounting/control fit | 35 | **4.91** | 1.72 | **COMPUTED:** 111 of 113 executed checks passed: 110/110 hard and 1/3 advisory. Score = 5 x 111/113. |
| AEC fit | 20 | 4 | 0.80 | **ASSUMPTION:** the schema models commitments, SOV lines, change orders, stored materials, retainage and prime billing. Held below 5 while labor, WIP/close and field modules mature. |
| Maintainability/upgrades | 20 | 3 | 0.60 | **ASSUMPTION:** standard library and SQLite only, with an append-only, checksummed schema catalog. One owner-maintainer carries the whole posting, close, reporting and recovery burden (plan section 3). |
| Ownership/licensing | 15 | 4 | 0.60 | **ASSUMPTION:** owner-written code with no third-party runtime dependency or copyleft obligation. Held below 5 until repository ownership and licence are confirmed (plan section 2: the PRO root has no licence file). |
| Delivery cost | 10 | 2 | 0.20 | **ASSUMPTION:** plan section 12's native-ledger premium is 20-40 person-months ($400,000-$1.2 million) and 4-9 months. Not validated here. |
| **Total** | 100 | | **3.92 / 5 (78.37%)** | |

- **ERPNext:** `not_evaluated`, with no scores.
- **Comparison:** none is possible. The decision note says: *"No comparative decision is possible yet: only native_cipher was scored. Non-control scores are ASSUMPTIONS."* Only 1.72 of the 3.92 is measured. The other 2.20 comes from assumed inputs.

### Advisories (non-gating; beyond a gate's specification text)

| Gate | Check | Result | Observed |
|---|---|---|---|
| G5 | A bill already in flight cannot be released a second time under a new approval | pass | A second, independently approved release of the 9000.00 bill was refused (*"payment intent ... is still in progress"*). 1 intent on the bill. Dispatch then added 1 provider transfer, which is the bill's first, legitimate release. |
| G8 | A restored copy cannot gain write authority without an attestation it cannot mint, even in the default configuration | **open** | With no `CIPHER_OWNER_SECRET` configured, a claim presenting the fabricated credential `apr_gate_unrecorded_claim` was **accepted**. In that configuration the claim is self-attested: an approver name and a reason. |
| G8 | A claim credential used on one restored copy cannot authorise a sibling copy of the same workspace | **open** | The owner claim code already used to claim the after-dispatch copy was **accepted** on the older, before-dispatch copy. The code is `HMAC(secret, workspace_id:authority_epoch)`, and every copy taken before a claim shares both values. One disclosed code therefore opens every such copy. Each copy still starts in release quarantine, so the drill shows no duplicate payment. |

Both open advisories are confirmed by direct probes of the core in `test_core_gates` (`test_g8_advisories_match_direct_probes_of_the_claim`). They are advisories, not hard checks, for two reasons:
- The core's design makes the owner secret optional. Its own docstring says a claim code is required only *"when `CIPHER_OWNER_SECRET` is configured"*.
- Neither case produces a duplicate external effect in the drill. That is the plan's restore-safety condition: section 6 requires quarantine and reconciliation after a restore, and section 7's release gates require *"no duplicate external effect in retry/restore cases"*.

Section 9 recommends closing both and promoting them to hard checks. If either were a hard check today, the native core would fail G8.

## 3. What changed in this revision (`cipher-core-gates/2` -> `/3`) and why

The round-two agents changed the core's controls. A check changed only where the design it tests changed. **No check was removed, and none was relaxed.** One check moved to a different credential, for a stated reason (G8, below). Every refusal is still attributed to the expected control by its reason pattern (`refusal_markers`).

| Gate | Check(s) | Before (v2) | Now (v3) | Design change that required it |
|---|---|---|---|---|
| G1 | `g1.float_refused`, `g1.bool_refused`, `g1.nonfinite_refused`, `g1.float_journal_refused`, `g1.nonfinite_journal_refused` | Any exception counted as a refusal. `sNaN`, `±Infinity` and the NaN journal were refused only incidentally (`InvalidOperation`). | **Stricter:** each refusal must carry the new `exact_money` control marker (`MoneyError` / non-finite / floating point / boolean). An incidental error now fails the check. | `core/money.D()` refuses non-finite values with `MoneyError`. |
| G2 | new `g2.raw_header_only_refused`, `g2.raw_incomplete_refused`, `g2.raw_unbalanced_refused` | Balance was tested on the posting path only. A raw header-only journal was documented as unblockable by triggers. | Raw journals written straight to the tables must be refused by the new `journal_seal` control, with nothing stored. | The journal seal: declared line count, a balance check on the completing line, and a deferred completion marker. See the note on attribution below. |
| G3 | `g3.linked_reversal` and friends; new `g3.correction_approved` | The correction ran through the low-level `Ledger.reverse`. | The adapter corrects through the governed `journal.reverse` (reversal request, bound approval, execution). The reversal must carry a recorded, consumed approval. | `journal.reverse` became a core approval-bound operation (plan section 6: correction is a distinct authority). |
| G4 | new `g4.raw_reopen_refused`, `g4.reopen_approval_single_use` | Reopen was tested through `Ledger.reopen_period` only. | A raw `UPDATE` reopening a closed period with a fabricated approval must be refused. A consumed reopen approval must not reopen the period again (ledger or raw path) or reopen another closed period, and the reopen log must still hold exactly 1 row. | Reopen is enforced by a period trigger and logged in an append-only `period_reopens`. |
| G4 | the adapter's `reopen_period_approved` | A fallback minted a `period.reopen` approval directly through `Approvals` when the close module was absent. | The fallback is removed. Without the close module, there is no governed reopen and the gate fails. | Minting approvals through `Approvals` bypasses the role check, and the new trigger requires `*.reopen_period`. |
| G7 | `g7.triggers` | 8 required triggers. | **15:** the original 8, plus the seal (`journals_declare_line_count`, `journal_lines_sealed`, `journal_unsealed_guard`), period integrity (`periods_locked_immutable`, `periods_reopen_requires_approval`) and append-only approvals (`approvals_lifecycle`, `approvals_no_delete`). | These triggers now carry the controls that G2-G4 rely on. |
| G8 | setup | The prime bill was sent with `receivables.send`, and the collection was attempted with no ACH mandate. | Sent through the `prime_bill.send` approval, with the customer's evidence-backed ACH mandate recorded. | Direct sending is refused, because sending is its own authority, and an ACH receipt needs a mandate. Without these, the collection probe would be refused by the mandate rule, not by write authority. |
| G8 | new `g8.restored_copy_refuses_privileged_writes` | Only service-level mutations were tested. | A raw `INSERT` on an unclaimed copy, an attempt to run `PRAGMA query_only = OFF`, and the raw `INSERT` again must all be refused by write authority. The copy must stay read-only. | Read-only is now enforced by SQLite (`query_only` plus an authorizer that guards the pragma). |
| G8 | `g8.claim_requires_recorded_approval` -> **`g8.claim_requires_attestation`** | A claim with a fabricated approval reference had to be refused. The positive control minted a "recorded approval" on the copy itself. | With a synthetic `CIPHER_OWNER_SECRET` configured for the drill, a claim presenting a fabricated or blank credential must be refused. No claim may be recorded, and the copy keeps no authority. | A read-only copy cannot record an approval of its own, so the claim became an attested owner action: approver and reason, plus an HMAC claim code when the secret is set. The old positive control was circular, because a copy minting its own approval proves nothing. The new credential comes from outside the copy. |
| G8 | `g8.claim_with_recorded_approval` -> **`g8.claim_with_attestation`**; new `g8.claim_credential_single_use` | The claim had to cite a recorded approval. | The stored claim record must show an approver, a reason and a verified code, and the copy must be quarantined with recovery epoch > reconciled epoch. Replaying the same code on that copy must be refused, with the claim count and authority epoch unchanged. | The claim code is bound to the workspace and its authority epoch, and each claim moves the epoch on. |
| G8 | two new advisories | none | Section 2. | The same attestation design. |

**The one configuration-dependent check.** `g8.claim_requires_attestation` is the only check that needs a configuration setting. The adapter sets `CIPHER_OWNER_SECRET` around each claim and restores the environment afterwards; the tests assert this. In the core's default configuration (secret unset), the v2 reading of this check would still fail. The gate reports that case as the first open G8 advisory rather than hiding it. If the owner wants the v2 reading, promote that advisory to a hard check. The native core would then fail G8.

**Attribution in the G2 raw-journal checks.** In a bare sqlite3 session, an incomplete journal fails its `COMMIT` with a generic *"FOREIGN KEY constraint failed"* (the seal's deferred completion marker). The harness cannot attribute that message to a control, and its marker validator rejects patterns that match it. The adapter therefore runs the raw statements inside the core's transaction wrapper, which names the unsealed journal. No posting-path code runs.

**Test changes.**
- **`SimulatedCoreFixes` is removed.** It closed the v2 gaps inside a test adapter to show the gates *can* pass. The native core now shows that directly.
- **`ReintroducedGapTests` replaces it.** Each of the 8 former gaps is re-opened in a test adapter. The gate must fail exactly the checks that gap breaks, with the documented evidence, which shows the gates still fail when a control is missing.
- **Per-gate check counts are pinned,** so no check can silently disappear.
- **Broken-adapter test 1:** `SkipsBalanceCheck` now also drops the seal triggers. The native schema refuses an unbalanced journal by itself, so a candidate "without a balance check" must lack both layers.
- **Broken-adapter test 2:** in `MalformedInsertWithoutPeriodTriggers`, the raw line `INSERT` onto the closed period's journal now passes. It is refused by the journal seal, an immutability control, even with the period triggers dropped. The test asserts that.
- **The other broken-adapter tests** are unchanged and still fail as intended.

## 4. What the native gates do and do not prove

**On synthetic data, in this repository, at this time, the native core passes these controls:**

- exact decimal money, refusing floats, bools and non-finite values, with half-up rounding and bounded largest-remainder allocation;
- balanced, atomic journals on the posting path and, through the journal seal, on the raw-SQL path (header-only, incomplete and unbalanced journals refused);
- immutable posted journals: raw UPDATE/DELETE/INSERT refused, with governed, approval-bound reversal-only correction;
- period locks on the service, ledger, raw-INSERT and three plugin paths. A locked period is immutable. A closed period reopens only with a consumed, period-scoped, single-use reopen approval, on the ledger path and the raw path;
- logical-operation idempotency;
- version- and destination-bound approvals;
- a self-verifying, complete audit export with a schema manifest listing the control triggers;
- restore safety for both an after-dispatch and a before-dispatch backup:
  - the copy is read-only at the SQLite level;
  - the claim is attested, with the owner secret configured;
  - releases are quarantined;
  - recovery looks up queued and in-doubt intents at the provider, with no resubmission;
- AP, AR and employee-payable agreement after the golden fixture.

`apps/cipher/BUILD_STATUS.md` said restore quarantine finds the pre-restore transfer without a second one. The previous revision found that true only for the after-dispatch backup. It now also holds for the before-dispatch backup: plan section 10, step 11.

**They do not prove:**

- **Accounting-policy correctness.** Revenue recognition, WIP, retainage classification and accruals have no controller-approved policies yet, and the fixture's posting rules are fixture-only (plan sections 6 and 10).
- **Statements and scope.** Financial statements, tax, multi-entity or multi-currency behaviour.
- **Migration.** Migration of real data, or parallel closes against the incumbent books (plan section 9).
- **Production readiness.** Security, isolation, performance, backup operations, provider contracts, and concurrency across processes. Each gate drives one workspace per connection in one process.
- **Every plugin path respects locks.** Only asset, reimbursement and labor are driven, each with a positive control. Banking, close, drawing, field, handoff, procurement, rights and schedule rely on the period-open triggers and the journal seal on every journal `INSERT`. G4 shows those firing, but their own flows are not exercised.
- **Restore safety in the default configuration.** With `CIPHER_OWNER_SECRET` unset, a restored copy accepts a self-attested claim. A claim code also opens sibling copies at the same epoch (the two open advisories).
- **The payment kill switch and signed provider callbacks.** No gate drives them; their module tests do.
- **Anything about ERPNext or Odoo.**

A zero-failure run is evidence, not a guarantee (plan section 7).

## 5. Former native-core gaps (all closed in round two)

Each gap is still probed directly against the core (`test_each_former_gap_is_closed_in_the_core`) and re-opened in a test adapter (`ReintroducedGapTests`). If a later change re-opens a gap, the probe and the gate both report it.

| Check key | v2 observation | Now (this run) | How the core closed it |
|---|---|---|---|
| `g1.nonfinite_refused` | `money('NaN')` returned NaN; `sNaN`/`±Infinity` were refused only incidentally. | All 7 non-finite cases are refused with `MoneyError`. | `core/money.D()` refuses non-finite values and values of 10**13 or more. |
| `g1.allocation_bounded` | `allocate("0.05", [1]*7)` gave a part of -0.01. | `0.01 x5 + 0.00 x2`; 0 violations over 6 cases. | Largest-remainder allocation with exact `Fraction` shares. |
| `g3.insert_line_on_posted_refused` | A raw line INSERT made a posted journal Dr 101.00 / Cr 100.00 and unbalanced the ledger. | Refused: *"the journal already holds its sealed line count"*. | Header-held line count, sealed by triggers, with a deferred completion check. |
| `g4.raw_unlock_refused` | `UPDATE periods SET status='open'` on a locked period was accepted. | Refused: *"locked periods are immutable"*. | `periods_locked_immutable`. |
| `g4.reopen_requires_recorded_approval` | `Ledger.reopen_period` accepted a fabricated reference. | Refused: *"is not a recorded approval"*. The raw path and replays are refused too. | `Ledger.reopen_period` resolves the reference to a consumed, period-scoped, unused `*.reopen_period` approval. A trigger and the `period_reopens` log enforce the same rule on the row. |
| `g8.restored_copy_refuses_mutations` | On a restored copy, `record_collection` and a direct ledger post both posted. | Both are refused by `WriteAuthorityError`, and so are raw SQL and the pragma lift. | The connection runs `PRAGMA query_only=ON` without effective authority, and the authorizer guards the pragma. |
| `g8.claim_requires_attestation` (v2: `g8.claim_requires_recorded_approval`) | A fabricated reference granted write authority. | With the owner secret configured, fabricated and blank credentials are refused (default configuration: open advisory). | An attested claim: approver and reason, plus an HMAC owner claim code when `CIPHER_OWNER_SECRET` is set. |
| `g8.older_backup_no_resubmission` | The before-dispatch backup resubmitted its queued intent (submissions 1 -> 2). | The queued intent is found at the provider and recorded as accepted; 0 resubmissions. | Recovery looks every queued intent up at the provider before lifting the quarantine. It also lists provider transfers this copy never recorded, which keeps the quarantine in place. |

## 6. Plan hard gates and weights, as implemented

| Plan section 3 hard gate | Executable gate(s) | Note |
|---|---|---|
| Exact arithmetic | G1 | Includes non-finite inputs, refusal attribution and bounded allocation. |
| Atomic posting / idempotency | G2, G5 | G2 now covers privileged raw journals too: header-only, incomplete and unbalanced. |
| Immutable corrections; "reject direct ledger-row edits" | G2, G3 | Raw UPDATE/DELETE/INSERT on posted journals, raw new journals that are incomplete or unbalanced, and governed, approval-bound reversal. |
| Locked-period enforcement | G4 | Service, ledger, raw INSERT, raw UPDATE of the period row (unlock and reopen), single-use reopen approvals and plugin paths. |
| Complete audit export | G7 | |
| Restore safety | G8 | After-dispatch and before-dispatch backups, write authority on every path (including raw SQL), and the attested claim. Two open advisories. |
| Correct accounting semantics | G9 (control-balance agreement) | Semantic and policy correctness is **not** executable here; it needs controller-approved policies and an independent oracle. |
| Legally usable packaging | none | Manual licence review (section 7). |
| Approval binding (plan section 6, "Distinct authority states") | G6 (and G3's governed correction) | Not in the section 3 list, but treated as a hard gate because payment safety depends on it. |
| "Reject permanent QBO dependence and pervasive core patches" | none | Architectural review items, not runtime checks. |

**Weights (plan section 3):** accounting/control fit 35%, AEC fit 20%, maintainability/upgrades 20%, ownership/licensing 15%, delivery cost 10%. They sum to 100, and the harness refuses to score if they do not.

**Scoring rules:**
- A candidate that fails any hard gate is `disqualified` and not scored.
- An unavailable candidate is `not_evaluated`.
- Control fit is 5 x passed / executed, over the hard and advisory checks.
- The other four criteria must be labelled `ASSUMPTION` with a rationale, or the harness raises. Non-finite or out-of-range scores are rejected.

## 7. What an ERPNext evaluation needs

1. **Authorization and isolation.** Separate execution authorization and an isolated environment: a dedicated development VM or subscription, synthetic data only, no production routes or credentials, and no host-socket or privileged containers (plan sections 3 and 8). A folder or branch is not isolation.
2. **A container stack.** ERPNext's database and cache, plus the Frappe/ERPNext application and worker images, pinned to exact versions. Nothing about this stack was installed, sized or verified here.
3. **An adapter.** An `ERPNextAdapter` must implement every `LedgerAdapter` operation through ERPNext's supported interfaces and return the same shapes.
   - **New in v3:** the privileged-path operations (`privileged_insert_raw_journal`, `privileged_reopen_period`, `privileged_lift_write_guard`) and the claim operations (`claim_write_authority`, `claim_write_authority_approved`, `claim_write_authority_default_config`, `authority_claims`, `period_reopen_count`).
   - **Refusal markers:** it must declare `refusal_markers` for all seven controls, including the new `exact_money` and `journal_seal`.
   - **Atomicity:** plan section 5 says that where a mature core needs a separate service, the complete financial command must execute atomically inside that core. Several CRUD calls do not satisfy G2.
4. **The same synthetic corpus.** The plan section 10 golden fixture plus the G1-G9 scenarios, including the before-dispatch restore.
5. **A licensing review.** ERPNext is GPLv3 and Frappe is MIT (plan section 3). Commercial packaging and distribution need module-level review; service separation alone does not settle derivative-work obligations. This review is the "legally usable packaging" gate.
6. **Privileged-path tests.** Plan section 6 notes that ERPNext's documented reversal behaviour is useful evidence, but its supported reposting paths still need governance. The candidate must pass the same privileged-path and period-lock tests as G2-G4, including direct database writes, reposting and administrative paths.
7. **Scoring.** Score only if every hard gate passes. Odoo Community stays the plan's comparator and would need its own adapter.

Everything in this section about ERPNext's behaviour is **unverified** here. The only vendor facts used are the ones the plan already cites.

**Why ERPNext is still `not_evaluated`:** none of items 1-3 exists. No execution authorization or isolated host has been granted, no stack is provisioned, and no adapter is written. This machine also lacks the storage headroom for the stack (section 8).

## 8. Local constraint: storage

- **Free space on drive C: on 2026-10-12:**

  | Time | Free space | Bytes |
  |---|---|---|
  | Start of the first harness session | about 8.7 GB | 8,723,419,136 |
  | 05:36Z | 3.4 GB | 3,669,958,656 |
  | 14:28Z (this run) | **4.36 GB** | 4,681,596,928 |

  The owner's standing target is 250 GB free.
- **Docker:** Docker Desktop was reachable earlier the same day (client and server 29.8.2, Linux engine, read with `docker version` and `docker system df` only). It was not queried again for this revision.
- **Implication:** a multi-GB ERP stack must not be pulled onto this machine at 3-9 GB free. That covers the database, cache, application images and volumes. Its exact size was not measured (unverified).
- **Before starting:** estimate the evaluation's peak storage first, including images, volumes, logs and the backups for the restore drill. Run it on a host with headroom, preferably the isolated environment in section 7.

## 9. Recommended next decision

1. **Accept G1-G9 (`cipher-core-gates/3`) and the weights** as the Phase 0 hard-gate harness for plan section 13, decision 4. Make this CLI the single pass/fail record for any candidate.
2. **Decide the two open G8 advisories, then promote them to hard checks.** Both need changes in `core/db.py`, which this harness does not own:
   - **(a) No secret, no claim:** refuse a claim on a file-backed restored copy unless `CIPHER_OWNER_SECRET` is configured. A self-attested claim should not be possible outside tests.
   - **(b) Bind the claim code to the copy:** for example, the copy generates a random challenge when it opens, and the code becomes `HMAC(secret, workspace_id:authority_epoch:challenge)`. A code issued for one copy then cannot open a sibling.
   - **Until then:** treat the native pass as conditional on the secret being configured and claim codes never being reused across copies.
3. **Authorize, or explicitly defer, the ERPNext evaluation.** If it is authorized:
   - provision it on an isolated host with storage headroom, not this machine at 4.36 GB free;
   - implement `ERPNextAdapter`;
   - run the same gates and corpus.

   Until then, record "no foundation selected". The native core is now a passing baseline (3.92 of 5, of which 2.20 is assumed), not a win.
4. **Optional, to widen coverage:** add G4 probes for the banking, close, field and procurement posting paths, and decide whether the payment kill switch and signed provider callbacks should become gate checks (today only their module tests cover them).

## 10. Limitations of this harness

- **Scenario-based probes.** A pass shows the scenarios behaved. It does not exhaustively prove each control.
- **Refusal markers** are declared by the adapter. The harness rejects markers that match empty or generic errors, but an adapter could still declare an over-broad pattern. Review each new adapter's markers. The native approval-reference marker is simply `approval`.
- **The G8 claim checks configure the owner secret.** The adapter sets `CIPHER_OWNER_SECRET` to a synthetic per-run value and restores the environment afterwards. The default configuration is reported only as an advisory.
- **Attribution of the G2 raw-journal checks** depends on the core's transaction wrapper naming the unsealed journal (section 3).
- **Plugin coverage in G4** is limited to plugins with a probe (asset, reimbursement, labor). A registered plugin whose probe cannot be prepared fails the gate, so a sibling module's API change shows up as a G4 failure until its probe is updated.
- **G9** asserts the golden fixture's AP (18000.00) and AR (54000.00) totals. For the employee payable, it asserts subledger = GL with a balance above 0.00 and at most the 1234.56 claim.
- **The control-fit formula** (5 x passed / executed) is this harness's own rule. Treat it as a mechanics score, not an accounting-quality score.
- **The payment provider** is the in-memory simulator. Every result about provider idempotency, transfer listing and lookup is about the simulator, not a real rail.
- **The re-opened gaps** in `ReintroducedGapTests` use test-only adapters that drop triggers for one statement or reach into private `Database` state. They prove the gates detect each gap. They are not evidence about the native core.

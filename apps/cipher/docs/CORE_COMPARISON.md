# Cipher accounting-core comparison: executable decision gates

Status: synthetic-prototype evidence, 2026-10-12, scorecard version `cipher-core-gates/4`. This is not an approval to execute anything, and it does not select an accounting foundation.

Plan reference: `CIPHER-PLAN-v1.0.md`, section 3 ("Accounting foundation decision") and section 13, decision 4 ("Choose the two serious accounting candidates and accept the hard gates/weighted scorecard"). The harness is `apps/cipher/tools/core_gates.py` and its tests are in `apps/cipher/tests/test_core_gates.py`.

**Headline:** the native core **passes all 9 hard gates (127 of 127 hard checks)**, so it is scored. Its weighted total is **3.91 of 5 (78.23%)**. Only the control-fit input (4.89) is computed; the other four inputs are labeled ASSUMPTION. Three of five advisories are open:
- the write-authority claim in the default configuration (G8);
- a credited supplier bill cannot be released for its open payable (G9, new; the known payments defect);
- the period-close checklist does not reconcile customer deposits 2400 (G9, new).

ERPNext was not evaluated. **No foundation can be selected:** a native score with nothing to compare it against is a baseline, not a selection.

Round three added 17 hard checks: 8 in G6 (supplier-invoice binding and governed payee changes) and 9 in G9 (supplier credit notes, credit memos, customer deposits and write-offs). Every earlier check still runs unchanged (section 3).

## 1. What was run

```
$env:PYTHONPATH = "C:\Users\TravisStaib\Claude\Projects\SA-CMS-PRO"
python -m apps.cipher.tools.core_gates --out <file>      # exit 0 only if the native core passes every hard gate
python -m unittest apps.cipher.tests.test_core_gates -v  # 52 tests, OK
python -m apps.cipher test                               # full suite: 997 tests, OK (expected failures=1)
```

- **Run used for this document:** the scorecard was generated at `2026-10-12T16:52:44Z` and the CLI exited with code **0**.
  - Environment: Windows 11, Python 3.12.10, standard library only.
  - Source: the `cipher/synthetic-prototype` working tree. The branch name comes from the assignment; git was not used to confirm it.
- **The one expected failure** in the full suite is `test_vertical_v1.VerticalV1KnownDefectTests.test_a_credited_bill_is_paid_exactly_its_open_payable_through_payment_release`, the same payments defect the new G9 advisory reports.
- **Candidates:**
  - `native_cipher` runs in-process through `apps.cipher.service.Cipher`. Every gate gets a fresh synthetic SQLite workspace. G8 uses temporary files and removes them afterwards.
  - `erpnext` reports itself unavailable: *"not provisioned: requires an isolated container stack (database, cache, Frappe/ERPNext images) and separate execution authorization"*. Every gate is therefore `not_run`. Nothing was installed, pulled or started.
- **Registered at run time:**
  - Plugins: ap_intake, asset, banking, close, drawing, field, handoff, labor, procurement, reimbursement, rights and schedule, plus the core_reconciliation and ricky_sdk pseudo-modules.
  - Schema: 59 catalog entries applied, every checksum matching, 451 triggers.
  - Three other agents were changing sibling modules during the session, so these numbers belong to this run only. Re-run the CLI to refresh them.
- **How a gate reports:** each gate returns `{gate, title, status, evidence, checks, failed_checks, check_keys, advisories}`.
  - Every evidence line starts with PASS, FAIL or INFO and carries the numbers it observed.
  - `failed_checks` lists stable check keys; `check_keys` (new in v4) lists every hard check the gate recorded, in order, so a check that silently stopped running is visible.
  - A gate passes only when every one of its hard checks passes.

## 2. Results

### Hard gates

| Gate | What it executes (this run) | Native Cipher | ERPNext |
|---|---|---|---|
| G1 Exact decimal arithmetic and rounding | **Refused by the money control (`MoneyError`):** floats, bools, `NaN`, `sNaN` and `±Infinity` through every entry point (7 of 7 non-finite cases). **Exact arithmetic:** `0.1 + 0.2 = 0.30`, where binary float gives `0.30000000000000004`. **Half-up to cents:** `2.675 -> 2.68`, where float `round()` gives 2.67, and `-0.005 -> -0.01`. **Allocation:** six cases sum exactly, and every part is non-negative and within one cent of its share (`0.05` over 7 gives `0.01 x5 + 0.00 x2`). **Storage:** exact string storage. **Journals:** float and NaN journals are refused by the money control with nothing posted. | **pass** (22/22) | not_run |
| G2 Balanced and atomic posting | **Posting path, refused with nothing posted:** an unbalanced journal (100.00 vs 99.99), a line with both a debit and a credit, an unknown account, a zero-value journal and a journal with no lines. **Command atomicity:** a 2-journal command that faults after the first leaves 0 journals and no idempotency record; a rerun posts both. **Privileged path, refused by the journal seal:** a raw header with no declared line count; a raw journal declaring 2 lines that commits with 1; a raw 2-line journal with Dr 100.00 / Cr 99.99. **Result:** every stored journal balances (TB 1200.00 = 1200.00). | **pass** (13/13) | not_run |
| G3 Immutable corrections | **Raw tampering:** `UPDATE`/`DELETE` on `journals` and `journal_lines` is refused as immutable, and the fingerprint is unchanged. **Governed correction (`journal.reverse`):** a linked reversal with sides swapped, carrying a consumed approval; it nets to 0.00 and leaves the original intact. **Refused:** a second reversal and a raw unlink. **Raw line INSERT onto a posted journal:** refused (*"the journal already holds its sealed line count"*). | **pass** (12/12) | not_run |
| G4 Period locks on every path | **Closed period, each refused with a period-lock reason:** the service path (granted `bill.approve`, 18000.00), a direct ledger post, a raw header `INSERT`, and a raw line `INSERT` (refused by the seal). **Locked period, refused:** posting, a raw `INSERT`, a governed reopen and a raw unlock. **Reopen without a valid approval, refused:** no reference, a fabricated reference, and a raw `UPDATE` citing it. **Positive control:** a governed reopen (`close.reopen_period`) works. **Single use:** the consumed reopen approval cannot reopen the period again or another period; exactly 1 recorded reopen. **Plugin paths:** each posts in an open period and is refused in the closed one: `asset.post_depreciation` 1000.00, `reimbursement.approve` 412.50, `labor.approve_timesheet` 8.00 h / 680.00. | **pass** (21/21) | not_run |
| G5 Idempotency | **Replay:** replaying an operation id returns the stored result with one journal, and the same id with a 260.00 payload conflicts. **Payment release:** replaying the execution returns the same 18000.00 intent, and a second worker's op id cannot consume the approval again. **Dispatch:** dispatching twice gives 1 transfer and 1 submission. | **pass** (5/5) | not_run |
| G6 Approval binding | **Earlier checks:** a one-cent change (27000.00 -> 27000.01) invalidates; a +10000.00 change order approved at 110000.00 is refused after another change moves the base from 100000.00 to 105000.00; a re-verified and a raw destination change after grant both invalidate the 18000.00 release; a fresh approval releases to the new destination. **New, supplier invoice:** invoice GATE-SI-0001 for 9000.00 (due 2026-11-14) is matched to its bill through `ap_intake.match_invoice` and `bill.approve` is granted; the supplier reissues it (version 2, due 2026-12-15) and the earlier approval is refused (`BillIneligible`, a `StaleApprovalError`), status invalidated, bill still draft, journals 1 -> 1. Control: re-matching and a fresh approval post the bill carrying version 2. **New, payee change (two people):** a change requested by `gate-site-pm` and recorded by login `gate-ap-clerk` cannot be verified by either (`' Gate-Site-PM '` and `'GATE-AP-CLERK'` both refused by the two-person rule); a raw `UPDATE` self-verification is refused by the `destination_changes_lifecycle` trigger; `party.verify_destination` cannot be requested before verification exists (0 approvals recorded); a granted approval goes stale when its verification record gains a newer revision (`DestinationChangeStale`). Control: a change verified by `gate-external-accountant` executes (destination v5 -> v6), the 9000.00 release granted before it is refused (invalidated, 0 intents), and a fresh release goes to the new destination at v6. | **pass** (14/14) | not_run |
| G7 Audit export completeness | **Setup:** the golden fixture plus a governed correction. **Contents:** all 9 sections, 10/10 journals with source, rule and lines; exported journals sum to the trial balance (283500.00); every journal has a `journal.posted` entry. **Chain:** the 102-entry chain verifies, including when recomputed from the exported rows (102 = 102 = 102 stored rows). A one-character edit is detected, and a raw audit `UPDATE` is refused. **Schema manifest:** all **15** required control triggers listed (451 triggers in total); 59 entries applied, all checksums matching. | **pass** (14/14) | not_run |
| G8 Restore safety | **Live workspace:** dispatches 18000.00; the provider accepts it but the response is lost. **Restored after-dispatch copy:** opens without write authority; replaying the execution is refused (`WriteAuthorityError`). **Refused on an unclaimed copy by SQLite's read-only guard:** `record_collection` for 4500.00, a direct ledger post, a raw `INSERT`, and `PRAGMA query_only = OFF`. **Claims:** fabricated and blank credentials refused; an attested claim (approver, reason, verified owner claim code) grants authority in quarantine; replaying its code is refused. **Quarantine** refuses dispatch and new releases. **Recovery** finds `sim_000001` by logical op id (transfers 1 -> 1, submissions 1 -> 1); AP reconciles (0.00 = 0.00). **Before-dispatch backup:** the queued intent is found at the provider and recorded as accepted; 0 resubmissions. | **pass** (13/13) | not_run |
| G9 Subledger-to-GL reconciliation | **Earlier checks:** after the golden fixture plus an employee claim (1234.56, 234.56 in flight): AP 18000.00 = GL 2000, AR 54000.00 = GL 1100, employee payable 1234.56 = GL 2100, TB 283234.56 over 9 journals. **New:** a 1500.00 supplier credit note posts Dr 2000 / Cr 5000 and AP becomes 16500.00 = GL 2000; a further 16500.01 credit is refused (*"exceeds what is open"*). A 1000.00 credit memo posts Dr 4000 / Cr 1100: AR 53000.00 = GL 1100. A 5000.00 customer deposit: deposit subledger 5000.00 = GL 2400. Applying 2000.00 posts Dr 2400 / Cr 1100: deposits 3000.00 = GL 2400, AR 51000.00 = GL 1100; applying 3000.01 is refused. Writing off the golden bill (0 days past due) is refused; on a 9000.00 bill 100 days past due a 4000.00 write-off posts Dr 6100 / Cr 1100: AR 5000.00 = GL 1100 on its project, 6100 = 4000.00. **Workspace:** AP 16500.00, AR 56000.00 and deposits 3000.00 all equal their control accounts; TB 306734.56 over 15 journals. | **pass** (13/13) | not_run |

Totals for native: 9 gates pass and 0 fail; 127 of 127 hard checks pass.

### Weighted scorecard

The native core passes every hard gate, so the plan's weights apply:

| Criterion | Weight | Native score | Weighted | Basis |
|---|---|---|---|---|
| Accounting/control fit | 35 | **4.89** | 1.71 | **COMPUTED:** 129 of 132 executed checks passed: 127/127 hard and 2/5 advisory. Score = 5 x 129/132. |
| AEC fit | 20 | 4 | 0.80 | **ASSUMPTION:** the schema models commitments, SOV lines, change orders, stored materials, retainage and prime billing. The rationale string still says labor, WIP/close and field are "being built"; those modules now exist, but the score is the owner's assumption and was not changed by this harness. |
| Maintainability/upgrades | 20 | 3 | 0.60 | **ASSUMPTION:** standard library and SQLite only, with an append-only, checksummed schema catalog. One owner-maintainer carries the whole posting, close, reporting and recovery burden (plan section 3). |
| Ownership/licensing | 15 | 4 | 0.60 | **ASSUMPTION:** owner-written code with no third-party runtime dependency or copyleft obligation. Held below 5 until repository ownership and license are confirmed (plan section 2: the PRO root has no license file). |
| Delivery cost | 10 | 2 | 0.20 | **ASSUMPTION:** plan section 12's native-ledger premium is 20-40 person-months ($400,000-$1.2 million) and 4-9 months. Not validated here. |
| **Total** | 100 | | **3.91 / 5 (78.23%)** | |

- **ERPNext:** `not_evaluated`, with no scores.
- **Comparison:** none is possible. The decision note says: *"No comparative decision is possible yet: only native_cipher was scored. Non-control scores are ASSUMPTIONS."* Only 1.71 of the 3.91 is measured. The other 2.20 comes from assumed inputs.
- **Movement since the previous run (3.94, control fit 4.96 from 112 of 113):** the two new G9 advisories are open, so control fit is now 129 of 132. All hard checks pass.

### Advisories (non-gating; beyond a gate's specification text)

| Gate | Check | Result | Observed |
|---|---|---|---|
| G5 | A bill already in flight cannot be released a second time under a new approval | pass | A second, independently approved release of the 9000.00 bill was refused (*"payment intent ... is still in progress"*). 1 intent on the bill; dispatch then added 1 provider transfer, the bill's first, legitimate release. |
| G8 | A restored copy cannot gain write authority without an attestation it cannot mint, even in the default configuration | **open** | With no `CIPHER_OWNER_SECRET` configured, a claim presenting the fabricated credential `apr_gate_unrecorded_claim` was **accepted**. In that configuration the claim is self-attested: an approver name and a reason. |
| G8 | A claim credential used on one restored copy cannot authorize a sibling copy of the same workspace | pass (was open in the 14:28Z revision of this document) | The code already used on the after-dispatch copy was **refused** on the older copy (`WriteAuthorityError`: *"... the code is bound to this workspace and its current authority epoch"*). `core/db.py` now also binds the code to a random challenge kept beside each physical copy (`claim_challenge`), so copies restored from the same backup get different codes. |
| G9 (new) | A credited supplier bill is released for exactly its open payable through `payment.release` | **open** | After the 1500.00 credit note, releasing the bill (amount due 18000.00, open payable 16500.00) was **refused** (`IntegrityError`: *"a payment release for a bill carrying a posted supplier credit note must be for exactly its open payable ..."*); 0 intents. `payments.manifest_for_bill` still binds the amount due, and the bills storage guard refuses it, so the supplier is never overpaid but the bill cannot be paid through the service. |
| G9 (new) | The period-close checklist reconciles customer deposits (2400) | **open** | None of the 44 checks the close checklist runs for 2026-11 names customer deposits or account 2400. The deposit subledger reconciles (3000.00 = GL 2400) when asked, but a period can close while 2400 is unreconciled. `CoreReconciliationChecks` covers 2050, 1300, 1150 and 1200, and the close module computes AP and AR itself; nothing asks for 2400. |

Every advisory is confirmed by a direct probe of the core in `test_core_gates` (`test_g8_advisories_match_direct_probes_of_the_claim`, `test_g9_credited_bill_advisory_matches_a_direct_probe_of_the_release`, `test_g9_advisory_matches_a_direct_probe_of_the_close_checklist`). They are advisories rather than hard checks for these reasons:
- **G8 default configuration:** the core makes the owner secret optional. Its docstring says a claim code is required only *"when `CIPHER_OWNER_SECRET` is configured"*, and the drill shows no duplicate external effect, which is the plan's restore-safety condition (sections 6 and 7).
- **G9 credited bill:** G9's specification is subledger-to-GL agreement, which holds (AP 16500.00 = GL 2000, and nothing was overpaid). Paying the credited bill is the next step in plan section 6, invariant 6 ("partial payments"). The defect is already tracked by an expected-failure test owned elsewhere, and it is a payments change, not a gate.
- **G9 close checklist:** 2400 agrees with its subledger. The plan's "at a common cutoff" (section 6, invariant 5) is where the close checklist comes in, so the gap is reported here and recommended for a hard check in section 9.

## 3. What changed in this revision (`cipher-core-gates/3` -> `/4`) and why

Round three added supplier invoice intake and matching, supplier credit notes, posted-bill correction, credit memos, write-offs, customer deposits (account 2400), versioned budgets and governed payee changes. The gates cover the parts that are approval binding (G6) and control-account reconciliation (G9). **No check was removed, relaxed or reworded; every v3 check runs first, in its v3 order** (`test_every_hard_check_ran` pins this through `check_keys`).

| Gate | New check key | What it requires | Plan basis |
|---|---|---|---|
| G6 | `g6.supplier_invoice_change` | A `bill.approve` granted while the bill carries a matched supplier invoice is refused, and invalidated, once the supplier reissues that invoice (here only the due date changes); the bill stays draft and nothing posts. | Section 6: the approval binds every attachment hash; section 11: supplier-bill intake/matching/approval. |
| G6 | `g6.supplier_invoice_fresh_approval` | Control case: re-matching the reissued invoice and a fresh approval post the bill, which then carries the reissued invoice's hash and due date. | Same. |
| G6 | `g6.payee_change_two_person` | Neither the named requester nor the login that recorded the request can verify a payee change (compared ignoring case and spaces); the change stays pending and the destination does not move. | Section 6: bank changes verified independently through a trusted channel. |
| G6 | `g6.payee_change_raw_self_verification` | A raw `UPDATE` marking the change verified by its requester, valid in every other respect, is refused by the schema. | Section 6, and the "privileged path" rule. |
| G6 | `g6.payee_change_requires_evidence` | `party.verify_destination` cannot be requested before the independent verification is recorded; no approval row is created. | Section 6: distinct authority states. |
| G6 | `g6.payee_change_evidence_bound` | A granted `party.verify_destination` is refused and invalidated once its verification record gains a newer revision. | Section 6: approvals bind object versions. |
| G6 | `g6.payee_change_independent_verifier` | Control case: a change verified by a third person executes and moves the destination version by one. | Section 6. |
| G6 | `g6.payee_change_invalidates_release` | A payment release granted before the governed change is refused (invalidated, no intent); a fresh release pays the new destination at its new version. | Section 6: the verified recipient and destination version are bound. |
| G9 | `g9.credit_note_ap` | A supplier credit note posts Dr 2000 / Cr 5000 and the AP subledger equals GL 2000 at 16500.00. | Section 6, invariant 6: credit notes stay traceable. |
| G9 | `g9.credit_note_bounded` | A further credit one cent above what is still open is refused by the open-amount bound, with nothing posted. | Section 6, invariants 5 and 6. |
| G9 | `g9.credit_memo_ar` | A credit memo posts Dr 4000 / Cr 1100 and AR equals GL 1100 at 53000.00. | Same. |
| G9 | `g9.deposit_recorded` | A customer deposit's unapplied subledger equals GL 2400, per project and workspace-wide. | Section 6, invariant 6: deposits. |
| G9 | `g9.deposit_application` | Applying a deposit posts Dr 2400 / Cr 1100; deposits 3000.00 = GL 2400 and AR 51000.00 = GL 1100. | Same. |
| G9 | `g9.deposit_application_bounded` | Applying one cent more than is unapplied is refused, by the service or by the database guard; nothing posts. | Same. |
| G9 | `g9.write_off_requires_age` | A write-off of a receivable that is not 90 days past due is refused. | The receivables write-off policy (fixture). |
| G9 | `g9.write_off_ar` | On a bill 100 days past due, a write-off posts Dr 6100 / Cr 1100 and the project's AR equals GL 1100. | Section 6, invariant 6: write-offs. |
| G9 | `g9.adjusted_totals` | Workspace-wide AP, AR and customer deposits equal their control accounts at the expected totals, and the trial balance balances. | Section 6, invariant 5. |
| G9 | advisory | A credited supplier bill is released through `payment.release` for exactly its open payable (one intent). | Section 6, invariant 6 ("partial payments"). |
| G9 | advisory | The period-close checklist reconciles customer deposits (2400). | Section 6, invariant 5 ("at a common cutoff"). |

**Harness changes.**
- **Three new refusal controls**, each attributed by its own marker: `independent_verification` (the service's two-person refusal, the schema trigger's message, and the refusal to approve an unverified change), `open_amount` (credits and applications beyond what is open, including the database's *"cannot exceed the unapplied balance of its deposit"*), and `write_off_age`. A refusal for any other reason still fails the check; `test_a_refusal_for_an_unrelated_reason_is_not_the_open_amount_bound` proves it.
- **Scenarios cannot be skipped.** The new G6 and G9 scenarios run inside a guard: if a step raises (a missing module, a moved API), every check not yet recorded fails as "not exercised", with the reason. A candidate without supplier-invoice intake fails the two invoice checks; a broken deposit flow fails the six checks from the deposit onwards.
- **New adapter operations** (`LedgerAdapter`): `approvals_on`; supplier invoices (`receive_supplier_invoice`, `match_supplier_invoice`, `revise_supplier_invoice`, `supplier_invoice`, `bill_supplier_invoice`); payee changes (`request_destination_change`, `record_destination_verification`, `revise_destination_evidence`, `privileged_self_verify_destination_change`, `destination_change_status`, `party_destination`); credits and deposits (`ap_open_bills`, `ar_open_bills`, `post_supplier_credit_note`, `post_credit_memo`, `record_customer_deposit`, `apply_customer_deposit`, `setup_aged_prime_bill`, `post_write_off`, `deposits_reconciliation`, `workspace_reconciliation`, `close_checklist`).
- **Result shape:** every gate result now carries `check_keys`.

**Test changes.**
- Pinned counts: G6 6 -> 14, G9 4 -> 13; the test also asserts that every v3 key of G6 and G9 still runs, first.
- `RoundThreeReopenedTests` re-opens each new control in a test adapter, and the gate must then fail exactly the checks that control guards, printing the evidence:

  | Re-opened control | Failed checks |
  |---|---|
  | `bill.approve` ignores the attached supplier invoice | `g6.supplier_invoice_change`, `g6.supplier_invoice_fresh_approval` |
  | No two-person rule (service and trigger) | `g6.payee_change_two_person`, `g6.payee_change_raw_self_verification` |
  | An unverified change can be approved | `g6.payee_change_requires_evidence` |
  | The AP subledger ignores credit notes | `g9.credit_note_ap`, `g9.credit_note_bounded`, `g9.adjusted_totals` |
  | The deposit subledger ignores applications | `g9.deposit_application`, `g9.adjusted_totals` (the database still refuses the over-application, so `g9.deposit_application_bounded` passes) |

- One control could not be re-opened by its Python check alone: with the evidence-currency check removed from `payments`, the `party.verify_destination` manifest still binds `evidence_is_current_revision`, so the stale approval is still invalidated and G6 still passes (`test_the_payee_approval_also_binds_evidence_currency_in_its_manifest`). That is defense in depth, not a gate weakness.
- `RoundThreeCoreProbeTests` reproduces each new control on `Cipher` directly, with exact money strings, the trial balance, the audit chain and every subledger reconciled.

### 3.1 Previous revision (`cipher-core-gates/2` -> `/3`), kept for the record

| Gate | Check(s) | Before (v2) | v3 | Design change that required it |
|---|---|---|---|---|
| G1 | `g1.float_refused`, `g1.bool_refused`, `g1.nonfinite_refused`, `g1.float_journal_refused`, `g1.nonfinite_journal_refused` | Any exception counted as a refusal. | Each refusal must carry the `exact_money` marker. | `core/money.D()` refuses non-finite values with `MoneyError`. |
| G2 | `g2.raw_header_only_refused`, `g2.raw_incomplete_refused`, `g2.raw_unbalanced_refused` | Balance tested on the posting path only. | Raw journals must be refused by the `journal_seal` control. | The journal seal. |
| G3 | `g3.correction_approved` and the linked-reversal checks | Correction through `Ledger.reverse`. | Correction through the governed `journal.reverse`, carrying a consumed approval. | `journal.reverse` became approval-bound. |
| G4 | `g4.raw_reopen_refused`, `g4.reopen_approval_single_use` | Reopen tested through `Ledger.reopen_period` only. | Raw reopen refused; a consumed reopen approval is single use. | Period trigger and `period_reopens`. |
| G4 | `reopen_period_approved` | A fallback minted approvals directly. | Removed; no close module means no governed reopen. | Minting bypasses the role check. |
| G7 | `g7.triggers` | 8 triggers. | 15 triggers. | The seal, period integrity and append-only approvals. |
| G8 | setup, `g8.restored_copy_refuses_privileged_writes`, `g8.claim_requires_attestation`, `g8.claim_with_attestation`, `g8.claim_credential_single_use` | Service-level mutations; a claim citing a self-minted approval. | SQLite-level read-only copy; an attested owner claim with an HMAC code bound to the copy. | Read-only enforced by SQLite; the claim became an attested owner action. |

**Configuration dependence.** `g8.claim_requires_attestation` is still the only check that needs a configuration setting: the adapter sets `CIPHER_OWNER_SECRET` around each claim and restores the environment (asserted by the tests). The default configuration is the open G8 advisory.

**Attribution of raw writes.** The G2 raw-journal checks run inside the core's transaction wrapper, which names the unsealed journal (a bare sqlite3 `COMMIT` reports only a generic foreign-key failure). The G6 raw self-verification is built valid in every other respect (trusted channel, current evidence used once), so the two-person rule is the only condition the trigger can refuse it for.

## 4. What the native gates do and do not prove

**On synthetic data, in this repository, at this time, the native core passes these controls:**

- exact decimal money, refusing floats, bools and non-finite values, with half-up rounding and bounded largest-remainder allocation;
- balanced, atomic journals on the posting path and, through the journal seal, on the raw-SQL path;
- immutable posted journals, with governed, approval-bound reversal-only correction;
- period locks on the service, ledger, raw-INSERT and three plugin paths, with single-use, period-scoped reopen approvals;
- logical-operation idempotency;
- approvals bound to amounts, versions and destinations, **to the supplier invoice a bill carries, and to a payee change's independent verification**; a governed payee change needs a second person, by the service and by the schema;
- a self-verifying, complete audit export with a schema manifest listing the control triggers;
- restore safety for an after-dispatch and a before-dispatch backup, with the claim code bound to each copy;
- AP, AR, employee payable and **customer deposits (2400)** agreeing with their control accounts after the golden fixture **and after a supplier credit note, a credit memo, a deposit and its application, and a write-off**, with credits and applications bounded by what is open.

**They do not prove:**

- **Accounting-policy correctness.** Revenue recognition, WIP, retainage classification, accruals, the credit-memo revenue reduction, the bad-debt treatment and the 90-day write-off rule are fixture policies with no controller approval (plan sections 6 and 10).
- **Supplier-invoice matching in general.** One progress-basis invoice is matched to one bill; purchase-order (three-way) matching, duplicate detection and exceptions are covered by the module's tests, not by a gate.
- **Payment of a credited bill.** It fails today (the open G9 advisory): `payments.manifest_for_bill` still binds the amount due, so a storage guard refuses the release until payments binds `Bills.open_payable`. The supplier is never overpaid, but the bill cannot be paid through the service.
- **Who the two people are.** The two-person rule compares names. Cipher has no production identity, and a privileged session can still name an outside verifier who never verified anything. Production identity is a later plan gate.
- **Close-time coverage of 2400** (the open G9 advisory).
- **Statements and scope.** Financial statements, tax, multi-entity or multi-currency behavior.
- **Migration.** Real data, or parallel closes against the incumbent books (plan section 9).
- **Production readiness.** Security, isolation, performance, backup operations, provider contracts, and concurrency across processes.
- **Every plugin path respects locks.** Only asset, reimbursement and labor are driven in G4; the others rely on the period-open triggers and the journal seal, which G4 shows firing.
- **Restore safety in the default configuration** (the open G8 advisory).
- **The payment kill switch and signed provider callbacks.** No gate drives them; their module tests do.
- **Anything about ERPNext or Odoo.**

A zero-failure run is evidence, not a guarantee (plan section 7).

## 5. Former native-core gaps (all closed in round two)

Each gap is still probed directly against the core (`test_each_former_gap_is_closed_in_the_core`) and re-opened in a test adapter (`ReintroducedGapTests`). If a later change re-opens a gap, the probe and the gate both report it.

| Check key | v2 observation | Now (this run) | How the core closed it |
|---|---|---|---|
| `g1.nonfinite_refused` | `money('NaN')` returned NaN; `sNaN`/`±Infinity` were refused only incidentally. | All 7 non-finite cases are refused with `MoneyError`. | `core/money.D()` refuses non-finite values and values of 10**13 or more. |
| `g1.allocation_bounded` | `allocate("0.05", [1]*7)` gave a part of -0.01. | `0.01 x5 + 0.00 x2`; 0 violations over 6 cases. | Largest-remainder allocation with exact `Fraction` shares. |
| `g3.insert_line_on_posted_refused` | A raw line INSERT made a posted journal Dr 101.00 / Cr 100.00. | Refused: *"the journal already holds its sealed line count"*. | Header-held line count, sealed by triggers. |
| `g4.raw_unlock_refused` | `UPDATE periods SET status='open'` on a locked period was accepted. | Refused: *"locked periods are immutable"*. | `periods_locked_immutable`. |
| `g4.reopen_requires_recorded_approval` | `Ledger.reopen_period` accepted a fabricated reference. | Refused; the raw path and replays are refused too. | A consumed, period-scoped, unused `*.reopen_period` approval, enforced in Python and on the row. |
| `g8.restored_copy_refuses_mutations` | On a restored copy, `record_collection` and a direct ledger post both posted. | Refused by `WriteAuthorityError`, and so are raw SQL and the pragma lift. | `PRAGMA query_only=ON` without effective authority; the authorizer guards the pragma. |
| `g8.claim_requires_attestation` (v2: `g8.claim_requires_recorded_approval`) | A fabricated reference granted write authority. | With the owner secret configured, fabricated and blank credentials are refused. | An attested claim with an HMAC owner claim code. |
| `g8.older_backup_no_resubmission` | The before-dispatch backup resubmitted its queued intent. | Found at the provider and recorded as accepted; 0 resubmissions. | Recovery looks every queued intent up before lifting the quarantine. |

## 6. Plan hard gates and weights, as implemented

| Plan section 3 hard gate | Executable gate(s) | Note |
|---|---|---|
| Exact arithmetic | G1 | Includes non-finite inputs, refusal attribution and bounded allocation. |
| Atomic posting / idempotency | G2, G5 | G2 also covers privileged raw journals. |
| Immutable corrections; "reject direct ledger-row edits" | G2, G3 | Raw UPDATE/DELETE/INSERT on posted journals, incomplete or unbalanced raw journals, governed reversal. |
| Locked-period enforcement | G4 | Service, ledger, raw INSERT, raw UPDATE of the period row, single-use reopen approvals and plugin paths. |
| Complete audit export | G7 | |
| Restore safety | G8 | After- and before-dispatch backups, write authority on every path, the attested claim. One open advisory. |
| Correct accounting semantics | G9 (control-balance agreement) | Now also after credit notes, credit memos, deposits and write-offs. Semantic and policy correctness is **not** executable here; it needs controller-approved policies and an independent oracle. |
| Legally usable packaging | none | Manual license review (section 7). |
| Approval binding (plan section 6, "Distinct authority states") | G6 (and G3's governed correction) | Now also supplier-invoice binding and the governed, two-person payee change. Treated as a hard gate because payment safety depends on it. |
| "Reject permanent QBO dependence and pervasive core patches" | none | Architectural review items, not runtime checks. |

**Weights (plan section 3):** accounting/control fit 35%, AEC fit 20%, maintainability/upgrades 20%, ownership/licensing 15%, delivery cost 10%. They sum to 100, and the harness refuses to score if they do not.

**Scoring rules:**
- A candidate that fails any hard gate is `disqualified` and not scored.
- An unavailable candidate is `not_evaluated`.
- Control fit is 5 x passed / executed, over the hard and advisory checks.
- The other four criteria must be labeled `ASSUMPTION` with a rationale, or the harness raises. Non-finite or out-of-range scores are rejected.

## 7. What an ERPNext evaluation needs

1. **Authorization and isolation.** Separate execution authorization and an isolated environment: a dedicated development VM or subscription, synthetic data only, no production routes or credentials, and no host-socket or privileged containers (plan sections 3 and 8). A folder or branch is not isolation.
2. **A container stack.** ERPNext's database and cache, plus the Frappe/ERPNext application and worker images, pinned to exact versions. Nothing about this stack was installed, sized or verified here.
3. **An adapter.** An `ERPNextAdapter` must implement every `LedgerAdapter` operation through ERPNext's supported interfaces and return the same shapes.
   - **New in v4:** the supplier-invoice, payee-change, credit, deposit and write-off operations listed in section 3 (for ERPNext: Purchase Invoice matching and its approval, supplier bank-account changes, Credit Notes/Debit Notes, customer advances and their allocation, and bad-debt journal workflows, all through supported interfaces).
   - **Refusal markers:** it must declare `refusal_markers` for all **ten** controls, including `independent_verification`, `open_amount` and `write_off_age`.
   - **Atomicity:** plan section 5 says that where a mature core needs a separate service, the complete financial command must execute atomically inside that core. Several CRUD calls do not satisfy G2.
4. **The same synthetic corpus.** The plan section 10 golden fixture plus the G1-G9 scenarios, including the before-dispatch restore and the round-three credit and deposit scenario.
5. **A licensing review.** ERPNext is GPLv3 and Frappe is MIT (plan section 3). Commercial packaging and distribution need module-level review; service separation alone does not settle derivative-work obligations.
6. **Privileged-path tests.** The candidate must pass the same privileged-path and period-lock tests as G2-G4 and the raw self-verification of G6, including direct database writes, reposting and administrative paths.
7. **Scoring.** Score only if every hard gate passes. Odoo Community stays the plan's comparator and would need its own adapter.

Everything in this section about ERPNext's behavior is **unverified** here. The only vendor facts used are the ones the plan already cites.

**Why ERPNext is still `not_evaluated`:** none of items 1-3 exists. No execution authorization or isolated host has been granted, no stack is provisioned, and no adapter is written. This machine also lacks the storage headroom for the stack (section 8).

## 8. Local constraint: storage

- **Free space on drive C: on 2026-10-12:**

  | Time | Free space | Bytes |
  |---|---|---|
  | Start of the first harness session | about 8.7 GB | 8,723,419,136 |
  | 05:36Z | 3.4 GB | 3,669,958,656 |
  | 14:28Z | 4.36 GB | 4,681,596,928 |
  | 16:53Z (this run) | **4.42 GB** | 4,423,815,168 |

  The owner's standing target is 250 GB free.
- **Docker:** not queried for this revision.
- **Implication:** a multi-GB ERP stack must not be pulled onto this machine at 3-9 GB free. Its exact size was not measured (unverified).
- **Before starting:** estimate the evaluation's peak storage first, including images, volumes, logs and the backups for the restore drill. Run it on a host with headroom, preferably the isolated environment in section 7.

## 9. Recommended next decision

1. **Accept G1-G9 (`cipher-core-gates/4`) and the weights** as the Phase 0 hard-gate harness for plan section 13, decision 4. Make this CLI the single pass/fail record for any candidate.
2. **Close the G9 advisory, then promote it to a hard check.** Add a customer-deposit reconciliation to the period-close checklist, for example the entry `("customer deposits reconciled (2400)", "receivables", "deposits_items")` in `service.CoreReconciliationChecks.CHECKS`. `deposits_items` already returns the shape that hook reads. This harness does not own `service.py`.
3. **Promote the passing G8 sibling-copy advisory to a hard check**, since the core now binds claim codes to each copy. **Decide the default-configuration advisory:** refuse a claim on a file-backed restored copy unless `CIPHER_OWNER_SECRET` is configured (in `core/db.py`), then promote it too. Until then, treat the native pass as conditional on the secret being configured.
4. **Bind the open payable in `payment.release`** (payments owner), so a credited bill can be paid through the ordinary release. That turns the credited-bill advisory to pass and the expected failure in `test_vertical_v1` into an unexpected success; then promote the advisory to a hard check.
5. **Authorize, or explicitly defer, the ERPNext evaluation.** If it is authorized, provision it on an isolated host with storage headroom (not this machine at 4.42 GB free), implement `ERPNextAdapter`, and run the same gates and corpus. Until then, record "no foundation selected". The native core is a passing baseline (3.91 of 5, of which 2.20 is assumed), not a win.
6. **Optional, to widen coverage:** G4 probes for the banking, close, field, procurement and ap_intake posting paths; a G6 purchase-order (three-way) match; and gate checks for the payment kill switch and signed provider callbacks.

## 10. Limitations of this harness

- **Scenario-based probes.** A pass shows the scenarios behaved. It does not exhaustively prove each control.
- **Refusal markers** are declared by the adapter. The harness rejects markers that match empty or generic errors, but an adapter could still declare an over-broad pattern. Review each new adapter's markers. The native approval-reference marker is simply `approval`; the new `open_amount` marker matches "exceeds what is open", "exceeds the X open/unapplied" and the database's "cannot exceed ...".
- **Binding checks are attributed by status.** The G6 binding checks (as in v3) count a refusal only when the approval ends `invalidated` and nothing took effect; they do not inspect the refusal's wording.
- **The G8 claim checks configure the owner secret** for the drill and restore the environment afterwards.
- **Plugin coverage in G4** is limited to plugins with a probe (asset, reimbursement, labor).
- **Fixed expectations.** G9 pins the golden fixture's AP (18000.00) and AR (54000.00) and the round-three totals derived from them (16500.00, 53000.00, 51000.00, 5000.00, 3000.00, 56000.00). A change to the fixture changes them.
- **Dates.** The supplier invoice uses fixed dates (invoiced 2026-10-15, reissued due 2026-12-15). The aged receivable is dated from the receivables clock (today), with its own period opened 30 days before its invoice date; the 0-days-past-due refusal relies on the golden bill being dated today.
- **The two-person rule compares names** (case- and space-insensitive). It is not identity.
- **The control-fit formula** (5 x passed / executed) is this harness's own rule. Treat it as a mechanics score, not an accounting-quality score.
- **The payment provider** is the in-memory simulator.
- **The re-opened gaps** in `ReintroducedGapTests` and `RoundThreeReopenedTests` use test-only adapters that drop triggers for one statement, patch a module function, or replace a domain method on one workspace. They prove the gates detect each gap. They are not evidence about the native core.

# Cipher — synthetic prototype

Cipher is S&A Solutions' owned AEC/EPC project-controls and accounting system, operated through explicit human approvals. Ricky is its role-aware assistant. Ricky previews and proposes, and through its SDK it can execute an approval only after a human has granted it; it can never grant one. This directory is the bounded **synthetic** build from the Cipher planning package (v1.0 plus the v1.1 solo-first correction): one owner, one USD entity, synthetic data, shadow finance and a simulated payment rail.

Nothing here touches production systems, real payment rails or live records. Standard library only; no package installation.

## Start

```bash
# from the repository root (set PYTHONPATH to the repo root when running elsewhere)
python -m apps.cipher test                                  # full suite
python -m apps.cipher demo                                  # golden fixture, prints the numbers
python -m apps.cipher serve --demo                          # console on http://127.0.0.1:8765 (loopback, no token)
python -m apps.cipher serve --db data/cipher.sqlite         # persistent workspace
python -m apps.cipher export --db data/cipher.sqlite --out audit-export.json
python -m apps.cipher schema --db data/cipher.sqlite
python -m apps.cipher.tools.core_gates                      # accounting-core decision gates (scorecard JSON)
python -m apps.cipher.tools.browser_check                   # headless Chrome/Edge drives the console journey
```

Restored or copied workspaces open read-only until the owner claims them:

```bash
python -m apps.cipher claim-challenge --db restored.sqlite
python -m apps.cipher claim-code --db restored.sqlite        # where CIPHER_OWNER_SECRET is set
python -m apps.cipher claim --db restored.sqlite --approver owner --reason "restore drill" --code <code>
```

Container (the build runs the full suite; the server refuses to start without a token):

```bash
docker build -f apps/cipher/Dockerfile -t cipher-prototype .
docker run --rm -e CIPHER_TOKEN=<16+ character secret> -p 127.0.0.1:8765:8765 -v cipher-data:/workspace/data cipher-prototype
# open http://127.0.0.1:8765/?token=<secret> once; it sets an HttpOnly session cookie
python -m apps.cipher.tools.browser_check --url http://127.0.0.1:8765 --token <secret>
```

Publish on 127.0.0.1 unless you mean to share the console. The image runs as a non-root user with a health check.

## What it does

Core workflow: owned evidence → structured estimate → approved commitment and executed changes → supplier progress bills with retainage and stored materials → payments through a durable outbox and simulated provider → prime contract billing, sending, ACH collection under a mandate, late return, prime retainage → project forecast → period close.

Modules (each registers its own schema entry and approval-bound operations):

| Area | Module | Highlights |
|---|---|---|
| Accounting | `ledger` (core) | immutable journals with sealed line counts, period locks and single-use reopen approvals enforced by triggers, governed `journal.reverse` |
| | `banking` | statement import with line fingerprints, matching, fees, in-transit items, locked reconciliations |
| | `close` | checklist across every module, governed close/reopen/lock, shadow statements, aging, WIP adjustments |
| | `assets` | capitalisation, monthly straight-line depreciation (never past the base), reversal, disposal |
| | `handoff` | shadow-finance package for the incumbent books with accountant receipt and omission checks |
| AP / AR | `bills`, `payments`, `receivables` (core) | stored-material evidence and per-line caps, retainage after closeout, kill switch, signed callbacks, recovery after restore, prime contracts, mandates, AR from every source |
| | `reimbursements` | staff expenses paid through the outbox, separate customer billing |
| AEC | `labor` | effective-dated rates, phases with fee budgets, timesheets, payroll without double cost, utilization, T&M billing |
| | `schedule` | CPM with float and critical path, deadlines, resource loading, approved baselines |
| EPC | `procurement` | equipment, requisitions, bid tabs, justified awards that create draft commitments, long-lead tracking, receiving |
| | `field` | RFIs bound to issued drawings, approved responses and distribution, submittals, hold points, punch list, closeout acceptance |
| | `drawings` | register with working, issued and superseded revisions bound to evidence |
| Governance | `rights` | content-rights registry consulted before AI retrieval of licensed documents |
| Ricky | `ricky` (core), `ricky_sdk.py` | read-only attention brief, manifest previews with abstention, typed versioned tool catalog with schema validation and append-only receipts |

## Controls

Enforced in code and covered by tests (see `BUILD_STATUS.md` for counts):

- exact decimal money; floats, non-finite and out-of-range values are rejected; allocation is largest-remainder;
- every consequential action binds a server-generated manifest (operation, subject, executing role, entity, currency, record versions and hashes, amounts, payee destination and version, journal preview where relevant, policy version, expiry, nonce); any material change invalidates the approval; expiry is recorded durably;
- the executing role and the approver's role must hold the operation's authority;
- commands are idempotent by logical operation id; a conflicting payload fails;
- posted journals cannot be edited, extended, deleted or moved by any SQL path; corrections append reversals; locked periods never change; a period reopens only with a consumed, single-use reopen approval;
- subledgers reconcile to control accounts: AP, AR (all sources), retainage payable and receivable, stored materials, provider clearing, employee payable, accrued payroll, bank;
- a payment leaves only through a committed outbox row with Cipher's idempotency key, after the payee is re-verified; a timeout is *outcome unknown* until reconciliation; callbacks must be signed; duplicates are ignored; a kill switch stops releases immediately and resuming needs an approval;
- a restored copy is read-only at the SQLite level until the owner claims it; claims bind to that copy's challenge when `CIPHER_OWNER_SECRET` is set (otherwise they are attestation only and Ricky flags it); releases stay quarantined until recovery reconciliation resolves every in-flight and queued payment;
- the HTTP boundary requires JSON with a same-origin Origin (no CSRF), rejects foreign Host headers in loopback mode (no DNS rebinding), and needs a token for any non-loopback bind; period close and commitment close go through their checklists.

## Golden fixture

| Step | Result |
|---|---|
| SOV 60,000 + 40,000; executed change +10,000 | commitment 110,000 |
| Period 1: 20,000 installed + 10,000 stored, 10% retainage | gross 30,000, retainage 3,000, due 27,000 |
| Period 2: 45,000 cumulative installed (10,000 from stored), 5,000 new stored | gross 50,000, retainage 5,000, net 45,000, due 18,000 |
| Pending 12,000 change | forecast 122,000 against 115,000 budget |
| Prime bill 60,000 certified, 10% retainage | 54,000 current AR |
| ACH collection 54,000 less 5 fee, then a late return after close | bank 53,995, then the receivable restored in the open period |
| Payment with provider timeout, reconciliation and replay | one transfer, one cash effect |

The fixture then executes the 12,000 alternative to exercise stale approvals, so `demo` reports an executed commitment of 122,000. `tests/test_vertical_v1.py` runs the plan's full section-10 acceptance test across every module.

## Layout

```
apps/cipher/
  core/          money, ids, db (schema catalog by name, triggers, write authority), audit, approvals, commands/outbox
  domain/        core: ledger, evidence, estimates, commitments, bills, receivables, payments, forecast, ricky
                 modules: assets, schedule, drawings, reimbursements, banking, labor, procurement, field, close, handoff, rights
  ricky_sdk.py   typed tool catalog for Ricky
  service.py     Cipher façade: request → approve → execute; core and module routing; golden fixture
  server.py      stdlib HTTP API and console host
  console/       owner console with a browser self-test
  tools/         browser_check.py, core_gates.py
  docs/          CORE_COMPARISON.md (accounting-core decision)
  tests/         unit, integrity, workflow, V1 acceptance, adversarial variants, HTTP and per-module tests
  Dockerfile
```

## Gates that remain closed

Authoritative accounting (the native-vs-ERPNext comparison, controller-approved policies, migration, parallel closes), production identity and authentication, real payment providers and bank connectivity, licensed-content ingestion, multi-entity and CAD automation are later gates in the plan. The fixture's posting rules (certified progress billed = earned, stored-material and disposal treatment) are labelled SHADOW assumptions awaiting controller approval.

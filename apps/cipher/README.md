# Cipher — synthetic prototype

Cipher is the prototype for S&A Solutions' full commercial, estimating/takeoff, AP/AR, project/CMS and engineering/library working system, operated through explicit human approvals. [The product goal](docs/PRODUCT_GOAL.md) defines its Fluent 2 interface, accounting adapter and internal/enterprise acceptance gates. QuickBooks is the current accounting authority; prior Odoo work is reused through explicit mappings. Its latest checkpoint and the live integrations are not verified by this prototype. Ricky is the role-aware assistant. Ricky previews and proposes, and through its SDK it can execute an approval only after a human has granted it; it can never grant one. This directory is the bounded **synthetic** build from the Cipher planning package (v1.0 plus the v1.1 solo-first correction): one owner, one USD entity, synthetic data, shadow finance and a simulated payment rail.

The HTTP Ricky surface exposes only reviewed read and draft tools. Approval requests, execution and payment reconciliation are human actions on that surface. The standalone SDK retains its execution tools for synthetic automation and acceptance tests.

Nothing here touches production systems, real payment rails or live records. Standard library only; no package installation.

Picking this up? Start with `HANDOFF.md` (where it stands and what to do next) and `AGENTS.md` (the rules that keep workspaces and controls intact).

The path to the usable Odoo/Cipher/QuickBooks workflow is tracked in [docs/DELIVERY_BACKLOG.md](docs/DELIVERY_BACKLOG.md), with system ownership, milestone acceptance gates and the next work items. The [bill approval/posting split](docs/BILL_POSTING_SPLIT_PLAN.md) works in the synthetic engine; immutable practice mode is implemented. The separate [AP practice workflow](docs/AP_PRACTICE.md) adds scoped synthetic sessions, bill preparation, invoice receipt/matching, independent match review and repeatable bill request/approval/posting actions. Read-only product metadata confirms QuickBooks Online Advanced; [the accounting adapter plan](docs/QUICKBOOKS_ADAPTER_PLAN.md) defines its handoff boundary. Recover and reuse the Odoo checkpoint and preserve the established BILL payment route until its handoff is mapped and tested. Fluent UI can be designed without sign-in; authenticated application identity is required before operational use by staff.

## Start

```bash
# from the repository root (set PYTHONPATH to the repo root when running elsewhere)
python -m apps.cipher test                                  # full suite
python -m apps.cipher demo                                  # golden fixture, prints the numbers
python -m apps.cipher serve --demo                          # console on http://127.0.0.1:8765 (loopback, no token)
python -m apps.cipher serve --db data/cipher.sqlite         # persistent workspace
python -m apps.cipher export --db data/cipher.sqlite --out audit-export.json
python -m apps.cipher schema --db data/cipher.sqlite
python -m apps.cipher practice-web --port 8766              # read-only Fluent practice backend, fresh in-memory fixture
python -m apps.cipher ap-practice-web --port 8767           # Fluent AP workflow, fresh synthetic people and records
python -m apps.cipher.tools.core_gates                      # accounting-core decision gates (scorecard JSON)
python -m apps.cipher.tools.corpus                          # 20-bill corpus: approval-time metrics (report JSON)
python -m apps.cipher.tools.browser_check                   # headless Chrome/Edge drives the console journey
```

The separate [Fluent practice app](web/README.md) reads versioned project, commitment, bill and approval presenters from `/api/practice/v1`. Build it with `npm ci` and `npm run build` in `apps/cipher/web`, then run `practice-web` and open `http://127.0.0.1:8766`. This local server always owns a fresh in-memory fixture, freezes it read-only, and has no file-workspace, action, identity or provider option. It mounts none of the old console routes. It is a design/development harness; the live backend-for-frontend remains open.

Build the separate AP entry with `npm run build:ap`, then start `ap-practice-web` and open `http://127.0.0.1:8767`. It uses `/api/ap-practice/v1` and its own disposable workspace. Select the synthetic accountant to request business approval, the separate PM to grant it without a journal, and the accountant to review and post the actual entry. Current audited project duties govern each request; no body can supply an actor or role. Exact authorized retries replay an immutable action receipt. These practice selectors do not authenticate staff, and this server has no external accounting or payment routes.

The accountant can also prepare installed work on Civil works subcontract, receive an invoice from its project-owned evidence and request a computed match. A separate synthetic reviewer accountant grants the match; an authorized accountant explicitly applies it before PM bill review and independent posting. Duplicate, amount-mismatch and changed-evidence states refuse safely. The [exception workflow](docs/AP_EXCEPTIONS.md) adds invoice revision/rejection/duplicate review, original-PM withdrawal and approved bill reversal followed by separately matched/reviewed/posted replacement. Evidence upload, PO/stored-material preparation and payment delivery remain later slices.

New workspaces receive an immutable audited practice declaration. Known historical Cipher files adopt practice while preserving original history; unrelated, empty, missing-identity or invalid-schema files are refused before initialization. This release refuses live files and unqualified payment providers. No flag or route promotes practice to live.

Restored or copied workspaces open read-only until the owner claims them. A known pre-mode copy defers declaration until that claim; diagnostics report its pending state. Claims must run outside any enclosing transaction. Payment recovery quarantine remains until reconciliation:

```bash
python -m apps.cipher claim-challenge --db restored.sqlite
python -m apps.cipher claim-code --db restored.sqlite        # where CIPHER_OWNER_SECRET is set
python -m apps.cipher claim --db restored.sqlite --approver owner --reason "restore drill" --code <code>
```

Container (the build runs the full suite; the server refuses to start without a token):

```bash
docker build -f apps/cipher/Dockerfile -t cipher-prototype .
docker run --rm --env-file cipher.env -p 127.0.0.1:8765:8765 -v cipher-data:/workspace/data cipher-prototype
# cipher.env holds CIPHER_TOKEN=<16+ character secret> and CIPHER_OWNER_SECRET=<secret for restored-copy claims>
# open http://127.0.0.1:8765/?token=<secret> once; it sets an HttpOnly session cookie
python -m apps.cipher.tools.browser_check --url http://127.0.0.1:8765 --token <secret>
```

Publish on 127.0.0.1 unless you mean to share the console. The image runs as a non-root user with a health check. A new image opens an existing workspace volume and applies its schema additions in place.

## What it does

Core workflow: owned evidence → structured estimate → approved commitment and executed changes → supplier invoice intake and match → supplier progress bills with retainage, stored materials and credit notes → payments through a durable outbox and simulated provider → prime contract billing, sending, ACH collection under a mandate, deposits, credit memos, late return, prime retainage → versioned budget and project forecast → period close.

Modules (each registers its own schema entry and approval-bound operations):

| Area | Module | Highlights |
|---|---|---|
| Accounting | `ledger` (core) | immutable journals with sealed line counts, period locks and single-use reopen approvals enforced by triggers, governed `journal.reverse` |
| | `banking` | statement import with line fingerprints, matching, fees, in-transit items, locked reconciliations |
| | `close` | checklist across every module, governed close/reopen/lock, shadow statements, aging, WIP adjustments |
| | `assets` | capitalization, monthly straight-line depreciation (never past the base), reversal, disposal |
| | `handoff` | shadow-finance package for the incumbent books with accountant receipt and omission checks |
| AP / AR | `bills`, `payments`, `receivables` (core) | stored-material evidence and per-line caps, retainage after closeout, supplier credit notes and corrections, kill switch, signed callbacks, governed payee changes, processing and bank-reconciled states, recovery after restore, prime contracts, terms and due dates, mandates, deposits (2400), credit memos, write-offs, AR from every source |
| | `ap_intake` | supplier invoices with number, dates and terms, duplicate refusal and near-duplicate review, approval-bound match to a certified bill or to received purchase-order lines |
| | `reimbursements` | staff expenses paid through the outbox, separate customer billing |
| Controls | `forecast` (core) | hash-chained budget versions by cost code through `budget.revise`, cost to date by source, estimate to complete, snapshots |
| AEC | `labor` | effective-dated rates, phases with fee budgets, timesheets, payroll without double cost, utilization, T&M billing |
| | `schedule` | CPM with float and critical path, deadlines, resource loading, approved baselines |
| EPC | `procurement` | equipment, requisitions, bid tabs, justified awards that create draft commitments, long-lead tracking, receiving |
| | `field` | RFIs bound to issued drawings, approved responses and distribution, submittals, hold points, punch list, closeout acceptance |
| | `drawings` | register with working, issued and superseded revisions bound to evidence |
| Governance | `rights` | content-rights registry consulted before AI retrieval of licensed documents |
| | `people` | identity registry, role grants scoped to the entity or a project, delegations, memberships and a hash-chained identity policy; no self-granting; records are checked against the audit log; enforcement is opt-in |
| | `payment_policy` | high-risk release rules: independent releaser, fresh step-up, co-signature by a named outside party and a cooling-off window after a new destination; weakening the rules needs that party's co-signature |
| | `contracts` | agreement approval and signature as separate authorities, required insurance and bond certificates checked at bill approval and at release |
| Ricky | `ricky` (core), `ricky_sdk.py` | read-only attention brief, manifest previews with abstention, typed versioned tool catalog with schema validation and append-only receipts; every approval-bound operation is reachable through it or excluded by name with a reason; callers resolve to registered identities while the people registry enforces |

## Controls

Enforced in code and covered by tests (see `BUILD_STATUS.md` for counts):

- exact decimal money; floats, non-finite and out-of-range values are rejected; allocation is largest-remainder;
- every consequential action binds a server-generated manifest (operation, subject, executing role, entity, currency, record versions and hashes, amounts, payee destination and version, journal preview where relevant, policy version, expiry, nonce); any material change invalidates the approval; expiry is recorded durably;
- the executing role and the approver's role must hold the operation's authority; while the people registry's identity policy enforces, a Ricky SDK caller must also be an active registered identity holding that role by grant or delegation, and Ricky never drafts, requests or executes a role, delegation or policy change;
- commands are idempotent by logical operation id; a conflicting payload fails;
- posted journals cannot be edited, extended, deleted or moved by any SQL path; corrections append reversals; locked periods never change; a period reopens only with a consumed, single-use reopen approval;
- subledgers reconcile to control accounts: AP, AR (all sources), retainage payable and receivable, stored materials, provider clearing, employee payable, accrued payroll, bank;
- a payment leaves only through a committed outbox row with Cipher's idempotency key, after the payee is re-verified and current audited insurance and bond coverage is checked; invalid coverage holds the same queued intent for retry without a provider attempt; a timeout is *outcome unknown* until reconciliation; callbacks must be signed; duplicates are ignored; one provider reference never pairs with two payments; a kill switch stops releases immediately and resuming needs an approval;
- a payee destination changes only through a request, independent evidence recorded by someone other than the requester, and a `party.verify_destination` approval;
- once configured, the governor modules hold approvals other modules own: the people registry checks every approver and executor, the payment policy holds high-risk releases for an independent releaser, step-up, co-signature and cooling-off, and contracts hold commitment execution for a signed agreement and bills and releases for certificates in force;
- configured modules must load successfully; startup fails on an import, schema or initialization failure. Grant preflight checks are read-only; the grant and its self-approval record commit together, including when a caller already has a transaction open;
- a bill business grant creates only an approved state. A distinct accountant/controller calls `post_bill` with an explicit actor and selected period; it consumes the original authorization and records the actual journals once. PM/owner authority alone cannot post, and `execute`/`approve_and_execute` refuse `bill.approve`. Immutable approved facts and posting receipts are checked against audit evidence before financial reads or payment;
- a restored copy is read-only at the SQLite level until the owner claims it; claims bind to that copy's challenge when `CIPHER_OWNER_SECRET` is set (otherwise they are attestation only and Ricky flags it); releases stay quarantined until recovery reconciliation resolves every in-flight and queued payment;
- the HTTP boundary requires JSON with a same-origin Origin (no CSRF), rejects foreign Host headers in loopback mode (no DNS rebinding), and needs a token for any non-loopback bind; the console escapes every server value before rendering it; period close and commitment close go through their checklists.

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

The fixture then executes the 12,000 alternative to exercise stale approvals, so `demo` reports an executed commitment of 122,000. `tests/test_vertical_v1.py` runs the plan's full section-10 acceptance test across every module; `tests/test_vertical_extended.py` walks one job through procurement, contracts, identity and payment-release governance, intake, assets, rights, the hand-off and the close.

## Layout

```
apps/cipher/
  core/          money, ids, db (schema catalog by name, triggers, write authority), audit, approvals, commands/outbox
  domain/        core: ledger, evidence, estimates, commitments, bills, receivables, payments, forecast, ricky
                 modules: assets, schedule, drawings, reimbursements, banking, labor, procurement, field, close, handoff, rights, ap_intake
                 governors: people, payment_policy, contracts
  ricky_sdk.py   typed tool catalog for Ricky
  ricky_served.py read and draft adapter for HTTP; standalone SDK remains a synthetic harness
  service.py     Cipher façade: request → approve → execute; core and module routing; golden fixture
  server.py      stdlib HTTP API and console host
  console/       owner console with a browser self-test
  tools/         browser_check.py, core_gates.py, corpus.py
  docs/          CORE_COMPARISON.md (accounting-core decision), UI_OVERHAUL_SPEC.md (UI overhaul spec awaiting owner decisions)
  tests/         unit, integrity, workflow, V1 and extended acceptance, corpus, adversarial variants, HTTP and per-module tests
  Dockerfile
```

## Gates that remain closed

Live Odoo and QuickBooks/BILL integration, production identity and authentication, real payment providers and bank connectivity, licensed-content ingestion, multi-entity and CAD automation require their own acceptance gates. QuickBooks remains authoritative; a finance cutover and any reopened core comparison require a separate decision, controller-approved policies, reconciled migration and parallel closes. The fixture's posting rules (certified progress billed = earned, stored-material and disposal treatment) are labeled SHADOW assumptions awaiting controller approval.

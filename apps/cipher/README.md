# Cipher — synthetic prototype

Cipher is S&A Solutions' owned project-controls and accounting core, operated through explicit human approvals with Ricky as a role-aware assistant that proposes but never executes. This directory is the bounded **synthetic first slice** from the Cipher planning package (v1.1, solo-first): one owner, one USD entity, one synthetic project, shadow finance and a simulated payment rail.

Nothing here touches production systems, real payment rails or live records. Standard library only: no package installation is needed.

## Start

```bash
# from the repository root
python -m apps.cipher test                     # run the suite
python -m apps.cipher demo                     # run the golden fixture, print the numbers
python -m apps.cipher serve --demo             # owner console on http://127.0.0.1:8765 with the fixture seeded
python -m apps.cipher serve --db data/cipher.sqlite --port 8765
python -m apps.cipher export --db data/cipher.sqlite --out audit-export.json
python -m apps.cipher schema --db data/cipher.sqlite
python -m apps.cipher.tools.browser_check --out evidence/browser.json   # headless Chrome drives the console's self-test
```

The browser check seeds the golden fixture, opens `/?selftest=1` in headless Chrome or Edge, and the console's own JavaScript runs a full journey through the real UI code path (refused execution before grant, commitment execution, bill certification, Ricky proposal, payment release with a provider timeout, reconciliation, duplicate-event handling, reconciliation checks). The page posts its outcome back to the server; the tool exits 0 only when every step passed and the books still balance.

Container (tests run during the build; the console serves on 8765):

```bash
docker build -f apps/cipher/Dockerfile -t cipher-prototype .
docker run --rm -p 8765:8765 -v cipher-data:/workspace/data cipher-prototype
```

Set `PYTHONPATH` to the repository root if you run modules from elsewhere.

## What the slice does

Workflow: owned evidence → estimate → approved commitment and executed change → supplier-bill certification with retainage and stored materials → payment through a durable outbox and simulated provider → prime billing, collection and late return → project forecast.

Controls enforced in code and covered by tests:

- exact decimal money; floats are rejected at the boundary;
- every consequential action binds a server-generated approval manifest (operation, subject, acting role, record versions and hashes, amounts, verified payee destination and version, policy version, expiry, nonce). A changed amount, SOV, commitment version or payee destination invalidates the approval instead of executing it;
- commands are idempotent by logical operation id: a replay returns the stored result, a conflicting payload fails;
- posted journals are immutable (SQLite triggers), corrections append reversals, and period locks apply to every posting path including raw inserts;
- AP and AR subledgers reconcile exactly to their control accounts;
- stored material is never billed twice: transfers reduce lot balances and appear inside cumulative installed value;
- a payment leaves only through a committed outbox row, is submitted with Cipher's idempotency key, and a timeout after submission is *outcome unknown* until reconciliation finds the transfer — never retried into a duplicate; duplicate provider events are ignored;
- a restored workspace copy has no write authority until a controller claims it, and payment release stays quarantined until recovery reconciliation completes;
- Ricky abstains on unknown roles, missing authority, stale evidence, unverified payees, closed periods and quarantine.

## Golden fixture

| Step | Result |
|---|---|
| Subcontract SOV 60,000 + 40,000, executed change +10,000 | commitment 110,000 (SOV 70,000 + 40,000) |
| Period 1: 20,000 installed + 10,000 eligible stored, 10% retainage | gross 30,000, retainage 3,000, due 27,000 |
| Period 2: 45,000 cumulative installed (10,000 transferred from stored), 5,000 new stored | gross 50,000, retainage 5,000, net 45,000, due 18,000 |
| Pending 12,000 change | forecast 122,000 against 115,000 budget, variance −7,000 |
| Prime bill 60,000 certified, 10% retainage | 54,000 current AR, 6,000 retainage receivable |
| ACH collection 54,000 with 5 fee, then late return after close | bank 53,995 then −5 net; receivable restored in the open period |
| Payment with provider timeout, reconciliation and replay | one transfer, one cash effect |

`python -m apps.cipher demo` prints these numbers; `tests/test_workflow.py` asserts them.

## Layout

```
apps/cipher/
  core/        money, ids, db (schema catalog, triggers, write authority), audit, approvals, commands/outbox
  domain/      ledger, evidence, estimates, commitments, bills, receivables, payments, forecast, ricky
  service.py   Cipher façade: request_approval → approve → execute; golden fixture
  server.py    stdlib HTTP API and console host
  console/     owner console (single page, vanilla JS)
  tests/       unit, workflow, adversarial and HTTP tests
  Dockerfile   container build that runs the suite
```

## Gates that remain closed

Authoritative accounting (separate core decision, accountant-approved policies, migration, parallel closes), production authentication, real payment providers, bank connectivity, licensed content, multi-entity and CAD automation are all later gates from the plan. The fixture's revenue policy (certified progress billed = earned) is an explicitly labelled SHADOW assumption, not an accounting rule.

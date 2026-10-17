# Cipher AEC Frappe application

Installable custom application for the selected ERPNext/Frappe 16 platform.
Standard ERPNext Project and Task remain the business masters. Namespaced Cipher
modules provide canonical identities, project duties, immutable command/history
receipts, document revisions, embedded Ricky orchestration, and a durable outbox.
There are no legacy Cipher or Odoo runtime imports.

This R0 release requires `cipher_site_mode = "synthetic"`; live financial delivery,
external payment/email, and silent model cloud fallback are unavailable.

## Installation

Add the editable app to the pinned bench environment, then run:

```sh
bench --site cipher.localhost install-app cipher_aec
bench --site cipher.localhost set-config cipher_site_mode synthetic
bench --site cipher.localhost execute cipher_aec.install.seed_synthetic
```

The synthetic bootstrap consumes an operator-supplied `CIPHER_FIXTURE_PASSWORD`
or per-user password mapping and never returns credentials. Without either, new
accounts get random nonreturned passwords and existing passwords are preserved.
It uses ERPNext's supported setup presets before creating company/project records.
Morgan's primary/alias accounts share one canonical person; Taylor has a separate
project. There is no unauthenticated fixture HTTP endpoint.

## Product API

Methods under `/api/method/cipher_aec.api.v1` are `session`, `projects`, `project`,
`tasks`, `history`, `operation`, and POST `create_task`. Company/project scope is
explicit. Frappe's `message` contains the `cipher.api.v1` envelope and versioned
`meta`. `cipher_aec/api/schema.json` supplies the checked-in JSON Schema contract.
Document and Ricky endpoint contracts live with their modules.

Authenticated commands require CSRF and an `Idempotency-Key` matching the UUID
operation ID. The canonical person's operation namespace is shared across aliases
and commands. Current identity and scope precede receipt readback; source/lifecycle
checks govern new effects under database locks. Task, receipt, history, and project
version changes commit atomically. A closed project retains readable historical
receipts while refusing new effects. Generic document and assignment routes cannot
bypass the services; ordinary users receive only the explicit R0 RPC catalog.

Set `cipher_execution_quarantined = 1` before starting a restored site. Reads and
authorized original receipts remain available; new commands and worker dispatch
are blocked until execution authority is separately reconciled. The outbox enables
only registered local effects in R0, with durable records and fenced claims; it
does not dispatch arbitrary import paths, provider URLs, or live payments.

## Verification

```sh
PYTHONPATH=. python -m unittest cipher_aec.tests.test_contracts
bench --site cipher.localhost run-tests --app cipher_aec --module cipher_aec.tests.test_governance_projects
```

The first command verifies the actual transport primitives without Frappe. The
second uses real Frappe/MariaDB and standard ERPNext records with per-test database
savepoints. These checks alone are not full R0 acceptance; the platform integration
owner records actual HTTP, browser, restart, and restore evidence.

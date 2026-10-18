# FLD02 native integration source — UNRUN

These proposed `cipher_aec/tests/` files target real Frappe 16.52 `IntegrationTestCase`, MariaDB, native controllers, governed services, private File storage, and canonical Person receipts. No native module has been imported or executed while preparing them. Only source reading, AST parsing, and in-memory compilation were performed.

| Case | Declared native proof |
| --- | --- |
| N01 | Owner/alias share one canonical Person; original device login cannot be substituted; alias synchronization preserves attribution; other Person/scope denied. |
| N02 | Revoked registration refuses new/staged effects and preserves readable original capture. |
| N03 | Disabled original binding blocks both original login and alias synchronization. |
| N04 | Reassigned superintendent binding fails closed; restored original binding permits the original staged capture. |
| N05 | Stage/read/inspect/stale-token refusal/apply; exact canonical header, revision, quantities, PNG bytes/photos, receipt hash, and commit event; unchanged Task/Project/finance snapshots. |
| N06 | Current ingestion rights rechecked before apply; retained-read rights permit committed receipt recovery after ingestion revocation. |
| N07 | Real source successor produces an inspected conflict; original source bytes and staged envelope remain exact. |
| N08 | Duplicate stage/same-operation recovery preserve one immutable envelope; changed content/operation reuse refused. |
| N09 | Same UUID recovers the exact original receipt through offline and native Field retry without another Field effect. |
| N10 | Shared Person UUID collision with another command is refused; original receipt remains its original command; UUID reservation enforced. |
| N11 | Native read permissions and unchanged/forged native/repository writes or deletion cannot bypass admitted commands. |
| N12 | A real intervening Field revision creates a base conflict; fresh linked replacement uses the exact current base/quantity predecessor; originals retained. |
| N13 | Explicit discard succeeds after source-read revocation, removes the payload, and retains exact disposition/event digests. |
| N14 | Real submit/independent review/acceptance/amendment, then payload redaction, device/write/ingest revocation: original header/revision/quantity/photo receipt remains distinct from current facts. |
| N15 | Current Field/document duties and source-read rights gate get/inspect/apply/operation readback of a historical receipt. |
| N16 | Exact extreme/small decimal strings, immediate quantity lineage, source byte hash; duplicate original quantity fails without partial Field persistence. |
| N17 | Actual T&M documentary line with exact decimal and canonical sources/receipt; one ticket; no Task, Project, finance, stock, or integration record effect. |
| N18 | Native savepoint rollback removes exact owned Field/offline/source/File rows; explicit orphan-byte cleanup preserves a separate still-referenced File. |

Each canonical-success helper compares full saved header/revision/quantity records and expanded photo/source metadata to native Field repository/service reads, exact `Cipher Command Receipt.result_json`, independently recomputed request/result hashes, and the offline commit pointer. Counts are supplemental. N14 compares the historical receipt with retained immutable originals and separately checks the amended current header/revision/quantity.

`fld02_native_fixture.prepare_fixture()` is a separate, explicit Administrator pre-suite operation. It requires the installed synthetic Company/Administrator, uses native `_person`/`_user`/`_binding` under `trusted_write`, creates four dedicated `@synthetic.example` logins with random nonreturned new-user passwords, and grants no duties. `verify_fixture()` is read only. No test lifecycle seeds, installs, migrates, changes schema, or commits. Frappe's supported base class itself performs its documented class-setup transaction; case isolation uses a savepoint established after `super().setUp()`. Cleanup is registered before writes, restores the prior user/session/request, verifies owned rows rolled back, and removes only individually attempted UUID-named files with matching byte hashes and no surviving File reference.

Local composition must first install the frozen FLD02 DocTypes/controllers, deny hooks and shared receipt dispatch; tests fail if prerequisites are absent. Actual application base: `310a946bd34d06c9f7c1a3d96ab7274733142cd9`. Frozen FLD02 contract source: `392a19f8c01b4253a5aaeaa99878408d394dc9cb`. The supported Frappe base-class reference is retained separately at `../frappe16-integration-test-case-reference.py`.

This source proves no runtime result yet. Independent concurrent connections/processes, deadlocks/restarts, a naturally occurring late-write failure, HTTP/CSRF transport, browser/device persistence, attachments larger than this fixture, full historical finance-content audits, and operational/provider/model qualification remain outside these cases. N05/N17's bounded finance/integration snapshots compare row identities plus native `modified`/`docstatus`; they detect inserts and ordinary native updates, not arbitrary unversioned SQL tampering. There are no mocks, patches, SQL authority bypasses, fabricated sessions, threads, fault injections, provider/model/network calls, or alternative writers.

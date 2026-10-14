# Fluent AP practice workflow

This slice connects Cipher's installed-work bill preparation, supplier invoice intake, matching and bill controls to the existing Fluent 2 design. It is a disposable local workflow for synthetic people and records. It advances B04, B05, B09 and B11 in [the delivery backlog](DELIVERY_BACKLOG.md); the full [product goal](PRODUCT_GOAL.md) remains open.

Build and start from the repository root:

```bash
npm --prefix apps/cipher/web run build:ap
python -m apps.cipher ap-practice-web --port 8767
```

Open `http://127.0.0.1:8767`. The server creates its own in-memory practice workspace. Restarting discards its sessions, records and action receipts. There is no workspace, provider or credential selector.

Select the synthetic accountant to request business approval for a draft bill. Select the separate synthetic PM to review and approve the request. Business approval creates no journal or payable. Select the accountant again to review the approved bill's posting period and post it under that original approval. The interface displays the posting outcome and refreshes the scoped records.

To start earlier in the process, open **Civil works subcontract** and **Prepare bill** as the accountant. Enter cumulative installed work for its two schedule-of-values lines and choose the certification period. Review the exact retainage and amount due, then prepare the certified draft. Receive a supplier invoice using a current project-owned synthetic evidence revision. Open **Invoices**, compute its match and request match approval. Change to Jordan Chen, the separate registered synthetic AP reviewer, to inspect the source packet and grant that match. Change back to the accountant and explicitly apply the approved match to link the invoice and certified bill. Continue through the separate PM business approval and accountant posting described above.

Preparation, receipt, computation and match approval/application create no journal or payable. Only the final independent bill posting does. Match review requires a different actual accountant from its requester. The current general policy permits an authorized accountant to apply a granted match; the demonstrated journey uses the original requester. Bill PM approval and accountant posting enforce their own strict person separation.

The selected practice persona maps to an existing registered person. The server derives the person, duty and project access from current audited records for each request. These selectors demonstrate the workflow; they do not authenticate an employee. Fluent components need no Microsoft sign-in. Microsoft Entra ID and deployment controls remain prerequisites for operational staff use.

Every review is read-only. Its opaque fingerprint binds the current record, person, authority, policy and proposed effects. A changed record or revoked duty requires another review. An action carries an independent repeatability UUID and its original reviewed facts. An exact authorized retry returns the original recorded outcome without applying the action again. The domain effect and audited API receipt commit together.

The first fixture covers installed work. Draft presenters reconstruct its original certified source hash. Unapproved stored-material claims need a complete historical lot snapshot before this action interface can present them; unsupported claims are refused. Approved bills can use their immutable audited business snapshot. The earlier read-only application and domain stored-material workflows retain their existing behavior.

The AP transport uses a host-only opaque session cookie, CSRF validation and exact local Host/Origin checks. It accepts nine fixed commands: prepare a bill, receive an invoice, compute a match, request/grant/apply match approval, and request/grant/post bill business approval. Typed inputs require exact integer cents, documented nested line fields and a current evidence revision. It exposes no generic module, role, provider, generic approval-execution or payment route. No request body can choose an actor or duty. Its loopback HTTP cookies and volatile session store are practice mechanisms, with no production identity or durability claim.

Safe error responses carry a code, message and target, with optional nullable remediation fields. No raw exception, manifest, database path or credential is serialized. A session is rechecked after body parsing and immediately before a review or action. A lost response leaves the committed receipt available to the same currently authorized person for an exact retry.

Invoice sources, lifecycle versions, match attempts, supplier terms and cumulative matched obligations are checked against their original audited history. Hidden project references stay undisclosed, including supplier duplicate information. Exact retries retain their original source/body proof through legitimate revisions and later posting, while unaudited state changes fail closed. Successful actions admit only the intended row and audit changes. Unexpected schema, accounting or unrelated approval changes roll back; verified stale/expired control transitions retain only their typed refusal receipt. These fixed actions do not call payment providers.

Schema 68 expands the fixed receipt-action allowlist without changing historical schema text or existing receipt bytes/hashes. A failed subsequent migration rolls back the whole upgrade. Structural migration does not grant write authority to a restored or copied workspace.

The earlier `practice-web` command still serves the separate read-only Fluent application. The AP entry has its own HTML, build output and API prefix. It shares the visual theme and presentation components without adding action imports to the read-only entry.

The invoice evidence selector uses preseeded owned synthetic revisions; document upload/storage is subsequent work. PO/stored-material preparation, claimed-versus-reviewed editing, governed invoice revision/rejection, corrections, payments and accounting handoffs remain open. QuickBooks Online Advanced is the recovered accounting product; [the adapter plan](QUICKBOOKS_ADAPTER_PLAN.md) defines the next synthetic handoff. This server has no QuickBooks, Odoo, BILL or bank connection.

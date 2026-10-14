# Fluent AP practice workflow

This slice connects Cipher's bill controls to the existing Fluent 2 design. It is a disposable local workflow for synthetic people and records. It advances B04, B05 and B09 in [the delivery backlog](DELIVERY_BACKLOG.md); the full [product goal](PRODUCT_GOAL.md) remains open.

Build and start from the repository root:

```bash
npm --prefix apps/cipher/web run build:ap
python -m apps.cipher ap-practice-web --port 8767
```

Open `http://127.0.0.1:8767`. The server creates its own in-memory practice workspace. Restarting discards its sessions, records and action receipts. There is no workspace, provider or credential selector.

Select the synthetic accountant to request business approval for a draft bill. Select the separate synthetic PM to review and approve the request. Business approval creates no journal or payable. Select the accountant again to review the approved bill's posting period and post it under that original approval. The interface displays the posting outcome and refreshes the scoped records.

The selected practice persona maps to an existing registered person. The server derives the person, duty and project access from current audited records for each request. These selectors demonstrate the workflow; they do not authenticate an employee. Fluent components need no Microsoft sign-in. Microsoft Entra ID and deployment controls remain prerequisites for operational staff use.

Every review is read-only. Its opaque fingerprint binds the current record, person, authority, policy and proposed effects. A changed record or revoked duty requires another review. An action carries an independent repeatability UUID and its original reviewed facts. An exact authorized retry returns the original recorded outcome without applying the action again. The domain effect and audited API receipt commit together.

The first fixture covers installed work. Draft presenters reconstruct its original certified source hash. Unapproved stored-material claims need a complete historical lot snapshot before this action interface can present them; unsupported claims are refused. Approved bills can use their immutable audited business snapshot. The earlier read-only application and domain stored-material workflows retain their existing behavior.

The AP transport uses a host-only opaque session cookie, CSRF validation and exact local Host/Origin checks. It accepts three fixed commands: request bill business approval, grant it, and post the approved bill. It exposes no generic module, role, provider, approval-execution or payment route. No request body can choose an actor or duty. Its loopback HTTP cookies and volatile session store are practice mechanisms, with no production identity or durability claim.

Safe error responses carry a code, message and target, with optional nullable remediation fields. No raw exception, manifest, database path or credential is serialized. A session is rechecked after body parsing and immediately before a review or action. A lost response leaves the committed receipt available to the same currently authorized person for an exact retry.

The earlier `practice-web` command still serves the separate read-only Fluent application. The AP entry has its own HTML, build output and API prefix. It shares the visual theme and presentation components without adding action imports to the read-only entry.

Subsequent AP work includes invoice intake, bill preparation/editing, governed rejection/withdrawal, corrections, payments and accounting handoffs. QuickBooks remains the accounting authority until an agreed cutover. This server has no QuickBooks, Odoo, BILL or bank connection.

# Cipher platform

Implementation of the approved independent ERP/CMS framework is active. The new `apps/cipher_aec` custom Frappe app extends ERPNext through supported APIs, hooks and namespaced DocTypes. It does not import the prior Cipher implementation or depend on Odoo.

- [Application](apps/cipher_aec/README.md): installed domains and API/service contracts.
- [Development deployment](deployment/README.md): pinned persistent MariaDB/Redis/Frappe runtime and same-origin SAP UI5 app.
- [Operations](operations/README.md): verification, evidence, backup and quarantined restore.
- [Implementation status](../docs/framework/IMPLEMENTATION_STATUS.md): actual evidence and remaining work.
- [Approved framework](../docs/framework/BACKEND_FRAMEWORK.md): product scope and dependency-ordered implementation contract.

The current runtime contains synthetic development data. Actual local-model and accounting connections are separate qualifications; their absence does not block independent implementation work.

# Cipher product interface

Fresh React/TypeScript/Vite application using SAP UI5 Web Components for React and the standard Horizon theme. It implements the initial project/document/Ricky workspace against the authenticated `cipher_aec` Frappe APIs. It imports no prior Cipher UI or engine code.

Run Node 22.12 or newer:

```sh
npm ci
npm run generate:api
npm run typecheck
npm run build
npm run test:contract
```

`npm run dev` starts port 5180. With `CIPHER_BACKEND_URL=http://127.0.0.1:18881`, the development server proxies `/api` to Frappe. Users sign in through the in-app UI5 form using the real Frappe `/api/method/login`; profile sign-out uses `/api/method/logout`. No credentials are embedded. Deploy `dist/` behind the same-origin application gateway with SPA fallback for `/projects`, `/documents`, `/work`, `/estimates` and `/connections` (including nested project estimate routes). The gateway must forward these native auth endpoints plus the explicit product methods, session cookies and CSRF/idempotency headers. Backend permissions remain authoritative.

The normal application never loads sample data or substitutes fixtures after connection failures. Tests intercept the documented RPC methods with **explicit synthetic contract fixtures**, kept exclusively under `tests/`. The table regression measures rendered header/body column boundaries at full width and after opening/closing Ricky; task and document tables use official UI5 `Table` composition with a shared column layout. Those tests verify client behavior, not a connected model, ERP persistence or provider acceptance. Screenshots named `synthetic-contract-*` are test evidence only.

For separately authorized read-only verification against the actual running Frappe site, `node scripts/connected-readonly.mjs` privately reads `CIPHER_RUNTIME_MANIFEST` (default `/tmp/cipher-r0-runtime/fixture.secret.json`) and uses `CIPHER_RUNTIME_URL` (default `http://127.0.0.1:18880`). It records screenshots under `test-results/connected-runtime`, signs in without logging credentials and performs no business writes. Run only once the shared synthetic site is ready; do not race database reset/migration tests. The separately coordinated `scripts/connected-approvals.mjs` uses private primary/reviewer fixture accounts in separate browser contexts to exercise real status-change requests, independent grants and execution, then restores Open through another independently approved packet. It performs business writes and must run only in the runtime owner’s assigned mutation slot.

Implemented: in-app sign-in/sign-out; company/project context; filtered sortable project register; signed server-cursor paging for projects, tasks and activity; project ObjectPage with Tasks, Documents and Activity; normal task creation with opaque source version and stable retry UUID; project approval inbox with exact status-change packets, independent review, separately authorized execution, withdrawal and decision history; original-byte document upload with SHA-256; revision/page-bound safe text preview and authorized original download; model availability, contextual questions, persisted run polling/reload, source citations and reviewed task proposals. Unavailable-model states preserve manual business work. Project-specific capabilities control visible actions; all effects use the same backend domain services. Client name/status filters apply to the loaded register page and say so when additional pages exist.

Estimating adds a scoped estimate register, explicit-currency draft creation, immutable revision/snapshot inspection, exact decimal text line editing, atomic tab-separated paste, qualified source/unit selection, indirect/contingency inputs, server calculation, same-operation unknown-result recovery, preserved stale-source inputs with explicit reviewed rebasing, and predecessor comparison by stable line ID. Sources open their actual cited revision text without leaving the editor. All totals and rounding results come from saved server snapshots. Rate/assembly creation, calibrated takeoff, baseline acceptance, proposal issue and award are not exposed by this slice.

Create and calculate recovery retain the exact original payload and operation UUID after connection loss, server errors, or malformed successful responses. A definitive first-attempt rejection unlocks correction. Once an outcome is unknown, later failures (including receipt-access denial) retain the snapshot and edit lock until an authoritative successful receipt resolves it; the create dialog also prevents cancel and Escape dismissal. These pending snapshots live only in the mounted dialog/workspace. Navigation, remount, page reload or browser restart loses the client snapshot; recovery across those boundaries is not implemented. Server operation receipts persist independently.

The core API types are generated from `../platform/apps/cipher_aec/cipher_aec/api/schema.json`; the generated file records its schema digest. Estimating types are separately generated from `estimating/schemas/api-v1.schema.json`; `npm run generate:api -- --check` verifies every generated artifact without modifying files. Adjacent document/Ricky interfaces follow those module owners' explicit R0 contracts. Every dependency and the lockfile are pinned. Framework assets remain provided by UI5; no SAP logo is used.

Official composition references, reviewed at source snapshot `c7f0f6eb891cad18fd776b77ea11eda123970052`:

- [Navigation layout pattern](https://github.com/UI5/webcomponents-react/tree/c7f0f6eb891cad18fd776b77ea11eda123970052/patterns/navigation-layout)
- [Vite/TypeScript example](https://github.com/UI5/webcomponents-react/tree/c7f0f6eb891cad18fd776b77ea11eda123970052/examples/vite-ts)
- [ObjectPage, FilterBar and AnalyticalTable implementations](https://github.com/UI5/webcomponents-react/tree/c7f0f6eb891cad18fd776b77ea11eda123970052/packages/main/src/components)
- [UI5 Table composition and column sizing](https://ui5.github.io/webcomponents/components/Table/)
- [UI5 React Apache-2.0 license](https://github.com/UI5/webcomponents-react/blob/c7f0f6eb891cad18fd776b77ea11eda123970052/LICENSE)

Limits: this is the R0 workspace, not the full ERP/CMS completion. Later commercial, finance, field and engineering flows are not displayed as working modules. It does not claim SAP S/4HANA functionality, a connected existing Ricky model, antivirus/OCR, live accounting or offline financial authority. Document extraction/scan status comes from the server. No trained model, calibrated takeoff, CAD tool, payment provider or external delivery is simulated in the normal UI.

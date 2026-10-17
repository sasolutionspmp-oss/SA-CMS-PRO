# Cipher foundation review: UI, ERP platform and integration ownership

**Superseded historical planning:** The latest owner direction requires a new product design independent of all prior Cipher/Odoo work. Odoo is interim operations only. Use [the new framework draft](framework/README.md); prior reuse, migration-dependency and workflow prescriptions below are not design inputs. Implementation awaits the owner’s framework approval.

**Committed owner decision, October 15, 2026:** [SAP_ERPNEXT_IMPLEMENTATION_PLAN.md](SAP_ERPNEXT_IMPLEMENTATION_PLAN.md) is the active architecture and delivery plan: SAP UI5 Web Components for React, ERPNext/Frappe, Cipher AEC extensions, and QuickBooks as official accounting authority. The owner selected implementation, without further framework comparisons or owner-run trials. Conflicting options and checkpoints below are historical and superseded.

October 15, 2026. This addendum responds to the owner's request to verify Fluent, Fluent 2, ERPNext and stronger open-source foundations before continuing the reset. It supersedes the assumption that Fluent is automatically the best presentation base. No replacement framework or ERP migration has been implemented by this review.

## Recommendation

**For the strongest ready-made open-source ERP page structure, prefer a bounded reference implementation using UI5 Web Components for React.** It provides more ERP-oriented composition than Microsoft's Fluent starter while retaining React and independent backend choice. This means SAP/Fiori-derived interaction patterns, not a Microsoft Fluent application.

**If recognizable Microsoft appearance is the controlling requirement, use Fluent 2 through Fluent UI React v9.** It remains a good maintained, permissively licensed choice, but requires more application composition. The earlier screens failed because of custom shell/composition choices, not because Fluent 2 was absent.

**Evaluate ERPNext/Frappe first as the new reusable business-platform candidate.** Compare its demonstrated reuse and extension effort with the accepted Odoo implementation once recovered, and with Cipher's current control baseline. ERPNext has not yet won a runtime comparison. Do not choose the custom engine merely because code has already been written, and do not migrate on feature lists alone.

Keep QuickBooks as official accounting authority and preserve the established BILL route. Whichever operational platform is selected must be the sole writer of its nominated business records and working ledger. There must not be competing writable Cipher, Odoo and ERPNext copies of the same obligation.

## Fluent 2: the naming matters

- **Fluent 2** is Microsoft's modern design system: visual rules, tokens and interaction guidance.
- **Fluent UI React v9**, distributed as `@fluentui/react-components`, is its modern React implementation.
- **Fluent UI React v8**, generally `@fluentui/react`, is the older generation.
- Fluent 2 is neither an ERP engine nor a separate ready-made ERP template that was overlooked.

Cipher already pins React components v9.74.3, which exports the stable navigation/grid/form components needed for a proper Fluent baseline. A version upgrade alone will not fix its appearance or business usability.

Official references: [Fluent 2](https://fluent2.microsoft.design/), [React components](https://react.fluentui.dev/), and the actual [Microsoft Vite starter](https://github.com/microsoft/fluentui/tree/93e324f72f0e187ff6a7e5f70ebf929d9b2212a2/starter-templates/src/react-components-vite). The starter is a themed scaffold with a title/button example, not Dynamics source or a complete ERP shell.

## Presentation foundations compared

This is a best-fit shortlist based on actual official source, licenses and package metadata, not an exhaustive claim that no other template exists. Maintenance observations describe the inspected versions, not guaranteed future support.

| Foundation | Concrete advantage | Main limitation for Cipher | Assessment |
|---|---|---|---|
| **UI5 Web Components for React** | Apache-2.0; actual navigation-layout app, ObjectPage, FilterBar, VariantManagement and AnalyticalTable with grouping/aggregation/virtualization | Fiori appearance; theming/web-component integration changes; estimate editing and document interactions still need validation | Strongest identified ERP presentation scaffold; preferred first reference candidate under the reopened decision |
| **Fluent 2 / React v9** | MIT code; authentic Microsoft controls/tokens, accessible interaction patterns, compatible existing React work | Thin starter; application floorplans, saved views and rich business compositions remain ours | Preferred if Microsoft UX identity is mandatory |
| **Ant Design Pro / ProComponents** | MIT; substantial list/form/profile/dashboard templates, ProLayout/ProTable/ProForm | Different visual language; full scaffold uses Umi; current major/prerelease peer compatibility needs careful pinning | Strong general enterprise-template alternative |
| **Material UI** | MIT core and useful free dashboard/CRUD templates | Material appearance; advanced MUI X features have commercial Pro/Premium terms | Good general UI; less attractive where advanced open-source grid coverage is a priority |
| **React-admin / Refine** | MIT core; substantial CRUD, routing and data/auth-provider infrastructure | Generic CRUD is not a governed AEC workflow; some React-admin advanced packages are commercial; no turnkey Fluent adapter established | Useful administrative infrastructure, not a complete ERP foundation |
| **AWS Cloudscape** | Apache-2.0 components, MIT-0 demo pages, strong filtering/resource lists/split views | Console-oriented visual language and no ERP domain behavior | Strong structured-console alternative; does not displace UI5 for ERP floorplans |
| **Carbon / PatternFly** | Credible enterprise components and layouts; Apache-2.0 / MIT respectively | IBM/operations-console patterns; AEC composition still required | Worth knowing; no decisive advantage under the present requirements |
| **Frappe UI / ERPNext Desk** | Frappe UI has MIT Vue components and screen recipes; Desk provides framework-driven forms/lists/admin | Frappe UI is Vue, not React; Desk and ERPNext business modules are different products/layers | Stronger when adopting the Frappe application ecosystem, not interchangeable React templates |

Do not select **Toolpad** for a new foundation: its official README states it is no longer actively maintained and directs users to Material UI's free CRUD dashboard template.

### Why UI5 React deserves the first proof

The inspected official source at `c7f0f6eb891cad18fd776b77ea11eda123970052` includes:

- A real [navigation-layout application pattern](https://github.com/UI5/webcomponents-react/tree/c7f0f6eb891cad18fd776b77ea11eda123970052/patterns/navigation-layout): shell bar, side navigation, search, profile/settings and notifications.
- [Vite/React examples](https://github.com/UI5/webcomponents-react/tree/c7f0f6eb891cad18fd776b77ea11eda123970052/examples/vite-ts) and templates.
- [ObjectPage, FilterBar, VariantManagement and other business controls](https://github.com/UI5/webcomponents-react/tree/c7f0f6eb891cad18fd776b77ea11eda123970052/packages/main/src/components).
- An [AnalyticalTable implementation](https://github.com/UI5/webcomponents-react/blob/c7f0f6eb891cad18fd776b77ea11eda123970052/packages/main/src/components/AnalyticalTable/index.tsx) with free virtualization, grouping, aggregation, sorting and filtering.
- An [Apache-2.0 license](https://github.com/UI5/webcomponents-react/blob/c7f0f6eb891cad18fd776b77ea11eda123970052/LICENSE) and a currently inspected React 18/19-compatible release line.

The open-source UI5 React/Web Components libraries do not require adopting SAP's ERP backend. They can use Cipher's typed API, ERPNext or Odoo through the same application boundary.

Do not confuse these with **SAPUI5/Fiori-elements proprietary runtime licensing**. OpenUI5 is Apache-2.0 but is its own framework. An Apache-licensed Fiori sample does not make every SAPUI5 runtime dependency Apache-licensed. Keep the candidate limited to verified open-source UI5 React/Web Components packages. Its charts package is deprecated and is not the proposed reporting foundation.

An AnalyticalTable is not a complete spreadsheet, formula engine or takeoff tool. Demonstrate keyboard editing, paste, numeric behavior and document context before selecting it for estimating. ObjectPage must not become another long dump of audit facts. No UI library itself supplies calibrated takeoffs, CAD review, offline reliability or financial correctness.

## Business-platform foundations compared

| Candidate | What can be reused | Main tradeoff |
|---|---|---|
| **ERPNext on Frappe** | Customer/vendor/item masters, sales/purchasing lifecycles, stock/assets, project/tasks/timesheets, accounting and Frappe infrastructure | GPLv3 application; AEC-specific workflows and controls need extensions; submitted invoices create its own GL; full custom frontend still costs work |
| **Frappe without ERPNext** | MIT metadata/model framework, permissions, APIs, administration, jobs and application extension mechanisms | Does not include ERPNext's business modules under MIT; much ERP domain work remains |
| **Existing Odoo Community + extensions** | LGPLv3 core and potentially accepted company configuration, integrations and operating history | Must recover the actual edition/modules/checkpoint; AEC gaps and custom frontend remain; third-party modules have separate terms |
| **Odoo Enterprise** | Additional product features and potentially useful existing setup | Subscription and redistribution restrictions; not an entirely open-source product base |
| **Current native Cipher** | Direct control, exact-money/source/approval/recovery behavior and tests | General ERP product completeness, shared operation, identity, documents and integrations remain our responsibility |
| **Tryton / Dolibarr** | Genuine modular business applications with APIs and extensibility | No reviewed evidence that they remove S&A's AEC/UX work better than ERPNext or accepted Odoo; reserve candidates |

### What the earlier comparison did and did not prove

`CORE_COMPARISON.md` explicitly records ERPNext as not evaluated and says no foundation was selected. Its native score included assumed criteria. It compared an accounting-control prototype; it did not establish which platform would deliver the complete operational ERP most efficiently while QuickBooks remained official.

Native Cipher's useful controls are reusable requirements and evidence. They are not a reason to rebuild all commodity ERP behavior. Likewise, ERPNext's feature list is not proof that it satisfies construction retainage, SOV/pay apps, claimed/reviewed quantities, change orders, engineering checking or source-bound independent posting.

ERPNext's inspected subcontracting module concerns job workers, supplied raw materials and warehouses. It must not be presented as demonstrated construction subcontract management.

### Integration and future workflows

Frappe provides REST/RPC, document permissions, API/session/OAuth authentication, background jobs, signed webhooks and custom-app extension mechanisms. Odoo also provides model extensions, APIs and scheduled operations; Odoo 19 introduces JSON-2. These are credible infrastructure savings, not proof of exactly-once delivery or all required controls.

Keep one typed Cipher business API between the UI and the chosen platform. Expose operations such as review invoice, apply approved posting, issue proposal and record receipt—not arbitrary privileged browser CRUD. Enforce consequential rules inside the authoritative transaction, including through generic ERP submit/API paths. An external precheck alone cannot prevent bypasses.

Future Microsoft 365, QuickBooks/BILL, document, CAD and automation integrations should use explicit record ownership, stable IDs, versioned contracts and durable events/outcomes. Frontend choice does not require a Microsoft or SAP backend. Every integration must state its authorization, retries, unknown-outcome recovery and reconciliation behavior.

### QuickBooks and one operational ledger

Official ERPNext Purchase Invoice and Sales Invoice source calls `make_gl_entries()` on submission. Full ERPNext AP/AR cannot be assumed to operate without its ledger.

If ERPNext is selected for these workflows:

1. ERPNext owns their operational records and working ledger.
2. The Cipher custom application enforces the required AEC behavior and controls.
3. QuickBooks remains official, with mapped, acknowledged and reconciled effects.
4. BILL retains its established payment responsibility.
5. Cipher's overlapping working ledger is retired for migrated records; historical evidence is retained.

Using only ERP masters/procurement while retaining financial ownership elsewhere is a different boundary to evaluate explicitly. Keeping invoices permanently draft to avoid ERPNext GL sacrifices lifecycle behavior; do not call that full ERPNext reuse. Never create three independent invoice/payment writers.

### Licensing and future commercialization

ERPNext GPLv3 permits commercial use. Distribution of covered software/modifications creates license/source obligations that must fit the intended packaging. Frappe's MIT license does not change ERPNext's GPL license, and an HTTP boundary alone does not determine derivative-work obligations. Odoo Community, Enterprise and individual addons need their own inventory. Neither open-source licensing nor use of a mature platform establishes Fortune 500 readiness.

## Bounded implementation proof, then close the decision

This is one defined foundation checkpoint, not another indefinite planning cycle:

1. **Presentation proof:** adapt the real UI5 React navigation pattern; build a Projects register, project/AP record and estimate-line/document surface against existing typed APIs. Capture actual desktop/tablet/phone behavior. Reject this candidate if core interactions require extensive replacement or Microsoft visual identity remains mandatory; use Fluent 2 in that case. Do not mix two primary design systems.
2. **Platform proof:** create one isolated synthetic customer/vendor/project/quotation and PO/receipt/invoice path on a pinned ERPNext stack. Record what is built in, configured, extended, core-patched or missing.
3. **Control proof:** enforce independent business approval/posting and source-change refusal through both the custom operation and generic submit/API paths. Verify rounding, exact totals and representative retainage/adjustment rules.
4. **Durability proof:** persist a QBO-shaped outbox with simulated acknowledgment; restart the app and worker; repeat the original request; verify one effect and reconciliation. Include a credit/correction.
5. **Extension proof:** package required changes in a custom application, avoid core patches and rehearse a supported update on a copy. Inspect the existing Odoo checkpoint against the same requirements and account for migration cost.
6. **Decision:** choose one presentation system and one owner per operational record class. Prefer ERPNext if meaningful reuse survives the control/upgrade/license gates; prefer accepted Odoo if it demonstrably offers the better route. Frappe-only or native Cipher remains justified if the alternatives require pervasive overrides or duplication that erases their benefit. Continue the existing 30-step business delivery plan using that decision.

There is no need to port every historical accounting-core test before this checkpoint. There is also no basis to call a project/quotation CRUD demonstration proof of safe accounting or complete AEC fit.

## Evidence, limitations and source links

Live official raw GitHub source and package metadata were reviewed. Some vendor documentation/GitHub API hosts returned proxy 403; this review used available official source rather than inventing inaccessible documentation. Observed branch version files reported ERPNext 16.51.0, Frappe 16.52.0 and Odoo 19.0 FINAL; these are source observations, not a tested compatible deployment or a latest-release guarantee.

An isolated trial used the official `frappe_docker` demo compose with ERPNext image `frappe/erpnext:v16.51.0`, a separate project name/volumes and frontend binding restricted to `127.0.0.1:18880`. Image extraction failed with **`failed to register layer: no space left on device`**, both during Compose pull and one serial image-pull retry. The local Docker daemon uses VFS; observed filesystem headroom dropped during extraction and recovered after failure. No storage-driver change or policy bypass was attempted. **No ERPNext site or application started; no runtime workflow, worker recovery or performance gate passed.** This is a provisioning limitation, not a product verdict. Do not rerun the same extraction repeatedly in this environment.

Primary sources:

- [ERPNext source and features](https://github.com/frappe/erpnext), [GPLv3 license](https://github.com/frappe/erpnext/blob/version-16/license.txt), [Frappe MIT license](https://github.com/frappe/frappe/blob/version-16/LICENSE).
- [ERPNext Project model](https://github.com/frappe/erpnext/blob/version-16/erpnext/projects/doctype/project/project.json), [Purchase Order](https://github.com/frappe/erpnext/blob/version-16/erpnext/buying/doctype/purchase_order/purchase_order.json), [Purchase Invoice](https://github.com/frappe/erpnext/blob/version-16/erpnext/accounts/doctype/purchase_invoice/purchase_invoice.py), [Sales Invoice](https://github.com/frappe/erpnext/blob/version-16/erpnext/accounts/doctype/sales_invoice/sales_invoice.py), [Subcontracting Order](https://github.com/frappe/erpnext/blob/version-16/erpnext/subcontracting/doctype/subcontracting_order/subcontracting_order.json).
- [Frappe API](https://github.com/frappe/frappe/blob/version-16/frappe/api/v2.py), [background jobs](https://github.com/frappe/frappe/blob/version-16/frappe/utils/background_jobs.py), [webhooks](https://github.com/frappe/frappe/blob/version-16/frappe/integrations/doctype/webhook/webhook.py), [official Docker setup](https://github.com/frappe/frappe_docker).
- [Odoo Community](https://github.com/odoo/odoo/tree/19.0), [licensing distinctions](https://github.com/odoo/documentation/blob/19.0/content/legal/licenses.rst), [JSON-2 documentation source](https://github.com/odoo/documentation/blob/19.0/content/developer/reference/external_api.rst).
- [Ant Design Pro](https://github.com/ant-design/ant-design-pro), [ProComponents](https://github.com/ant-design/pro-components), [MUI X licensing](https://github.com/mui/mui-x), [Toolpad maintenance notice](https://github.com/mui/toolpad), [React-admin](https://github.com/marmelab/react-admin), [Refine](https://github.com/refinedev/refine).
- [Frappe UI](https://github.com/frappe/frappe-ui), [Cloudscape](https://github.com/cloudscape-design/components), [Cloudscape demo source](https://github.com/cloudscape-design/demos), [Carbon](https://github.com/carbon-design-system/carbon), [PatternFly](https://github.com/patternfly/patternfly-react).

Detailed UI source/compatibility research and the exact trial logs are retained in the local evidence workspace. The evidence supports the recommendations above; it does not claim an exhaustive market search, successful ERPNext installation or completed platform selection.

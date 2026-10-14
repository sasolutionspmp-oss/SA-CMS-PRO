# Cipher practice web

A Fluent 2 read interface for Cipher's isolated synthetic practice workspace. It includes a project home, searchable lists, project records, subcontract records, pay apps, and review requests. Approval, editing, posting, payment, sign-in, and identity impersonation controls are absent.

This starter follows `../docs/UI_OVERHAUL_SPEC.md` page templates and theme. It lives in `apps/cipher/web/` instead of the spec's proposed sibling `apps/cipher-web/` so Cipher's source and agent rules stay together. The Python engine still uses only the standard library. Node builds static files; it is not a production application server.

## Run the practice application

From the repository root, with Python 3.12+ and Node 22.12+:

```bash
npm ci --prefix apps/cipher/web
npm run build --prefix apps/cipher/web
python -m apps.cipher practice-web --port 8766
```

Open `http://127.0.0.1:8766`. The separate Python server creates a fresh synthetic in-memory workspace, serves `dist/`, and exposes only the versioned practice read endpoints. Its workspace is disposable. It cannot select an existing database or mount the old console/action API.

For frontend development, start that practice server and then run `npm run dev --prefix apps/cipher/web`. Vite listens on loopback port 5173 and proxies `/api` to loopback port 8766. For standalone sample layout review, use `npm run dev:fixture --prefix apps/cipher/web` or `npm run build:fixture --prefix apps/cipher/web`. Fixture mode is explicit; a failed API read never substitutes sample data silently.

## Contract and safety

The client reads fixed same-origin `/api/practice/v1/projects`, `/commitments`, `/bills`, and `/approvals` endpoints. It accepts only `cipher.practice-read.v1` envelopes marked `mode: practice`, `synthetic: true`, and `currency: USD`. Amounts are safe integer cents; retainage rates are integer millionths. Formatting and sums use BigInt arithmetic, and displayed project aggregates are range-checked before records are published to React. Internal record IDs appear only in addresses and the Technical details disclosure. There are no arbitrary server URLs, token inputs, live credentials, write requests, or simulated sign-in.

The engine separates supplier-bill business approval from posting. A distinct authorized person posts a currently approved bill through the human service path; this read-only client exposes neither action. Project filters are browsing aids; this milestone does not provide authenticated read permissions or a live application.

`index.html` contains the exact `__CIPHER_STYLE_NONCE__` marker. The practice server replaces it with each response's CSP nonce. Griffel's official `createDOMRenderer` and `RendererProvider` pass that nonce to generated Fluent styles. Authored components use CSS classes rather than inline style attributes or injected HTML. No fonts or scripts are downloaded at runtime. The optional React StrictMode development wrapper is omitted because this pinned Fluent/Tabster combination logs duplicate Keyborg disposal during StrictMode remounts; browser error assertions remain enabled, and normal development and built practice views are checked.

Navy is `#0B2341`. Lime `#9FD93A` is a placeholder used only on navy; the owner still needs to confirm the logo and final lime. The theme uses an official Fluent Theme Designer brand ramp with named roles set to the exact S&A navy.

## Checks

```bash
npm run typecheck --prefix apps/cipher/web
npm run build --prefix apps/cipher/web
npm run smoke --prefix apps/cipher/web
CIPHER_WEB_BASE_URL=http://127.0.0.1:8766 npm run smoke --prefix apps/cipher/web
```

Smoke checks use installed `/usr/bin/chromium` by default (`CIPHER_CHROME` can select another installed Chromium). They exercise six read pages at 1440, 1024, and 390 pixels, search, keyboard dismissal/focus return, mobile navigation, scoped scrolling, no write requests, and axe WCAG checks. API-mode checks also verify Fluent style nonces and browser CSP errors. Reports and screenshots go to `/tmp/cipher-web-review` unless `CIPHER_WEB_ARTIFACTS` selects an artifact directory. Hidden Tabster focus-sentinel nodes are narrowly excluded from axe after keyboard traversal confirmed focus skips them; no accessibility rule is disabled globally. Automated checks do not replace manual screen reader testing or owner review.

## AP practice actions

The separate AP entry adds a complete synthetic bill workflow while the original read application and its GET-only checks keep their existing behavior:

```bash
npm run build:ap --prefix apps/cipher/web
python -m apps.cipher ap-practice-web --port 8767
```

Open `http://127.0.0.1:8767`. Start as the listed accountant to review a certified draft bill and request business approval. Change practice person to the listed project manager, open Business reviews, read the decision packet and grant approval. Approval creates no journal or payable. Change back to the accountant and open Post approved bills; select an open posting period, supply a reason for a different period, review the exact entry, and explicitly post to the practice working ledger.

This entry uses the existing Fluent 2 theme, frame and record templates, with its own `ap-practice.html`, `src/ap-main.tsx`, `src/ap/` and ignored `dist-ap/`. The fixed same-origin `/api/ap-practice/v1` API derives current project scope and duties from a registered synthetic person. Persona selection is a transparent practice tool; it does not establish real human identity or Microsoft authentication. The opaque HttpOnly, SameSite=Strict cookie is for this loopback HTTP application. Sessions expire after 30 minutes idle or 8 hours total, and every unsafe request includes the current CSRF token. Restarting the server discards its sessions and in-memory records.

The same AP entry also connects installed-work bill preparation and supplier invoice intake. Open the Civil works subcontract, choose **Prepare a bill**, select an actual open certification period and enter installed work to date on the server's schedule of values. Dollar inputs use BigInt parsing, refuse fractional cents and values outside the exact integer range, and send integer cents. The server computes the certified draft and retainage during a read-only review; preparing the draft creates no journal or payable.

Choose **Receive a supplier invoice** on the subcontract, supply its invoice number, date and amount, and select an existing available supplier invoice evidence revision in the project. The server derives supplier, project, source hash and due date from its owned records and audited supplier terms. No document is uploaded or invented by the form. **Invoices** lists current receipt, source revision, duplicate checks and match results. The accountant explicitly computes the match and requests independent approval. Change to Jordan Chen, the registered synthetic AP reviewer, to review and approve the match; an authorized accountant then separately applies the approved invoice link. These steps create no journal or payable. The project manager's bill approval and the accountant's independent posting then follow the existing flow.

Each action requires a read-only preflight and current record version. Changing the posting period or reason clears the review. The client retains the exact action body and repeatability UUID in memory for an explicit **Retry same action**, including navigation within the current person’s scope. A retry retrieves the original recorded outcome; a fresh read shows current state. Starting a new review, changing person/scope, losing the session, or reloading the browser discards that client memory. No cookies or CSRF tokens are persisted by the action cache. Safe changed/expired/blocked responses require refreshed facts and a new review; the client never resubmits automatically or substitutes fixture data.

Certification lines show actual installed work and period totals. Preparation supports installed work without stored materials; source revision, duplicate and amount-mismatch exceptions keep match approval unavailable until resolved. Claimed-versus-reviewed editing and evidence-upload workflows remain later work, along with payment, official provider acknowledgement, production identity and live-workspace admission. It displays grounded names and **Bill {sequence}**; supplier invoice numbers are the supplied source numbers. Live QuickBooks and Odoo handoffs remain later work.

### Resolve AP exceptions

Open **Review invoice revision, duplicate or rejection** from an invoice. An authorized accountant can review revised supplied facts and current source evidence, record why a flagged invoice represents a distinct obligation, or finally reject a received invoice with a reason. Changed duplicate facts require review again; revised invoices require fresh matching approval. Final rejection reserves the old invoice number and releases its source evidence for another received invoice. The interface keeps the original body and UUID available for an exact retry, and each revised body requires a new review.

Open **Review bill cancellation or correction** from a bill. An authorized accountant can cancel a draft; its original business approver can withdraw an approved, unposted bill while still authorized. Both actions keep history and create no journal. Posted bills require a correction: record its reason, request independent accountant approval, then open **Correction reviews** as a different accountant to read and grant the packet. An authorized accountant separately selects an eligible open period, reviews the exact reversal entry and explicitly executes the correction. The original bill stays in history as corrected. Prepare a replacement from the current subcontract, revise and freshly match its source invoice as needed, and complete its separate PM business approval and accountant posting. Paid, credited or otherwise ineligible bills remain blocked by the server’s current checks.

Final invoice rejection, bill cancellation/withdrawal and correction execution use Fluent dialogs that start on the option to keep the record. These are practice workflow confirmations after server review; they do not establish production identity, change financial policies or call an external provider.

```bash
npm run typecheck --prefix apps/cipher/web
npm run build:ap --prefix apps/cipher/web
npm run smoke:ap --prefix apps/cipher/web
npm run smoke:ap-intake --prefix apps/cipher/web
npm run smoke:ap-exception --prefix apps/cipher/web
npm run smoke:ap-accounting --prefix apps/cipher/web
```

The AP smoke test launches a fresh isolated backend for each of 1440, 1024 and 390 pixels, exercises the same-accountant request/post with a different project manager, verifies journal-free approval and an actual later-period post, and retries each action using the same body/UUID/receipt, including a retry after navigation. It checks a genuine competing-post refusal, a backend rejection of changed review inputs, session loss, eight malformed-contract/precision cases, keyboard focus, the posting dialog’s safe initial focus, scoped reads, style nonces, CSP/application errors and axe WCAG findings. Expected HTTP refusals are bound to the tested request’s method, path and status when it begins; their actual response evidence is retained for matching browser network messages. Every unexpected HTTP response and application/CSP error fails the check. Its screenshots and report go to `/tmp/cipher-completion/ap-browser`; `CIPHER_AP_ARTIFACTS` may choose a different artifact directory and `CIPHER_AP_PORT` an unused local test port. The accessibility run uses reduced motion so transient color animations have settled. Automated checks still leave manual screen reader and owner design review open.

The separate intake smoke launches the actual AP server factory with fresh records at the same three widths. It prepares a two-line bill, receives owned source evidence, computes and approves the invoice match using distinct accountant/reviewer people, applies the match as its requester, and completes PM business approval plus accountant posting. Exact retries include navigation back to the preparation form. It checks genuine duplicate and amount-mismatch holds, exact-money malformed contracts, style nonces, keyboard help dismissal, mobile navigation, CSP errors and axe findings. A bounded test-only stdin command advances one owned synthetic evidence document through the normal Evidence API after browser review, verifying that the actual receipt action refuses the stale source without creating an invoice. There is no test HTTP endpoint or runtime app backdoor. Reports go to `/tmp/cipher-completion/ap-intake-browser`; `CIPHER_INTAKE_ARTIFACTS` and `CIPHER_INTAKE_PORT` select test output and an unused loopback port.

The exception smoke uses a fresh actual backend at 1440, 1024 and 390 pixels. It documents and re-reviews changed duplicate facts, finally rejects an invoice and reuses its released source evidence, cancels a draft, withdraws an approved bill as its original PM, and corrects a matched posted unpaid bill through a distinct accountant grant and an actual later-period reversal. It then reissues and freshly matches the invoice to a separately approved and posted replacement. It verifies exact retries, safe dialog focus/keyboard dismissal, current scoped reads, style nonces, CSP/application errors and axe findings. Reports go to `/tmp/cipher-completion/ap-exception-browser`; `CIPHER_EXCEPTION_ARTIFACTS` and `CIPHER_EXCEPTION_PORT` select test output and an unused loopback port.

### Practice accounting handoffs

From an eligible posted, unpaid installed-work bill, open **Prepare practice accounting handoff**. The server selects its fixed synthetic mapping. The immutable plan shows the original certified cost, AP liability and retained liability from the original posting receipt, plus its balanced practice entry. The exact date-only transaction date follows `synthetic.period-end.v1`: the end of the original posting period. A bill certified in October and actually posted in November therefore uses November 30. This is explicitly a synthetic policy; live date, cost-type and tax qualifications remain unavailable. The practice mapping carries aggregate project and supplier dimensions only.

The accountant prepares the plan and requests handoff approval. A different registered accountant grants the unchanged packet. An authorized accountant explicitly queues it. These four human actions create no additional working journal, AP change, simulator call or payment. **Accounting handoffs** lists current plans, independent reviews and delivery records within the person's existing project scope.

Delivery is a separate explicit **Run practice delivery** step using the owned simulator and current accountant. An uncertain original outcome offers **Look up original outcome**, which uses the same original logical operation rather than submitting another entry. A confirmed Missing outcome requires **Review next practice step** before any later delivery; its provider logical operation remains unchanged. A simulator acknowledgment requires separate **Reconcile simulation** readback. If readback is unavailable or conflicting, the original acknowledgment is retained and a permitted **Review next practice step** can review another readback. The old outcome and its exact retry remain available until the person explicitly chooses that new review. An unfinished invocation offers only refresh or the same exact request. Simulator acknowledgment and simulation reconciliation do not mean QuickBooks accepted anything: official QuickBooks books and payments remain untouched and unavailable.

The accounting smoke starts a fresh owned backend at 1440, 1024 and 390 pixels. It verifies the complete seven-action flow with separate accountants, original exact cost/AP/retainage, October and later-November period-end dates in an Eastern browser timezone, zero human simulator calls, and unchanged working journals/native payment counters. Fixed test-only stdin commands inject timeout-before/after-acceptance and unavailable/malformed readback faults. The genuine UI looks up confirmed Missing, explicitly reviews a later delivery using the same provider logical operation, preserves uncertain original outcomes, and explicitly reviews later readbacks while retaining the original acknowledgment. Each source creates exactly one simulator effect. A bounded transport-response test presents an unfinished response after a genuine owned invocation, then verifies that its exact retry retrieves the original backend receipt without another simulator call. It also checks original retries after explicit later reviews, navigation and reconciliation, person-change cache clearing, malformed refreshed packets and action results, amount/date/capability/provenance/private-field responses, keyboard review, mobile focus return, Fluent style nonces, CSP/application errors and axe findings. No fault selector or test endpoint is added to the application. Reports go to `/tmp/cipher-completion/ap-accounting-browser`; `CIPHER_ACCOUNTING_ARTIFACTS` and `CIPHER_ACCOUNTING_PORT` select test output and an unused loopback port.

## Exact direct dependencies

Publication dates were verified against the npm registry on Oct 14, 2026. Each selected release was published more than two weeks earlier. `package-lock.json` pins the complete resolved dependency graph.

| Package | Version | Published |
| --- | --- | --- |
| React / React DOM | 19.3.0 | Sep 9, 2026 |
| `@fluentui/react-components` | 9.74.3 | Jun 29, 2026 |
| `@fluentui/react-icons` | 2.0.331 | Jun 26, 2026 |
| `@griffel/react` | 1.7.8 | Sep 23, 2026 |
| Vite | 8.3.1 | Sep 24, 2026 |
| TypeScript | 6.0.3 | Apr 16, 2026 |
| `@vitejs/plugin-react` | 6.0.0 | Mar 12, 2026 |
| `@types/react` / `@types/react-dom` | 19.3.0 | Sep 9, 2026 |
| Playwright | 1.63.0 | Sep 4, 2026 |
| `@axe-core/playwright` | 4.10.2 | Jun 3, 2025 |

Fluent, Griffel, React, TypeScript, and Vite use MIT licenses; Playwright uses Apache-2.0 and axe-core uses MPL-2.0. Their package license files remain available in the development install.

The original bounded read contract does not include schedule-of-values grids, documents, governed approval packets, forecasts, history seals, person-specific home queues, saved views, or server-side exports. The separate AP entry adds certified bill lines, business packets and person-scoped workflow queues as described above. No mock checks, approval thresholds, numbering, or business facts are invented for API records. The explicit read-app sample fixture supplies synthetic examples solely for layout review. `node_modules/`, `dist/`, `dist-ap/`, local environment overrides, and test reports are ignored and must not be committed.

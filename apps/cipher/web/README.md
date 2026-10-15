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

## Current main qualification

The main backend passes 2703 unique tests in 1703.859 seconds with zero failures, errors or skips; all 266 Python source/test hashes remain unchanged. The four main Fluent workflows and the separate nine-case recovery-remount check also pass on their captured runtime/UI/configuration/served-JavaScript snapshots. The two test expectation corrections retain exact original-to-current provenance.

| Entry | Fixed actions | Practice result | Port |
|---|---:|---|---:|
| AP, intake, exceptions and accounting |24| Installed-work/invoice matching, business grant and independent posting, governed correction, separate simulated accounting delivery/readback |8767|
| Commercial |7| Manual source-priced estimate revisions, independent estimator acceptance and source-preserving PM subcontract draft |8768|
| Owner billing / AR |7| Claimed/reviewed owner pay app, journal-free grant, independent same-grant posting and separately approved synthetic send |8769|
| Authored library |6| Exact UTF-8 revisions and independently reviewed project reference copy |8770|
| RFI |9| Issued drawing/supporting citations, draft response, independent official answer and separate synthetic distribution |8771|

| Main entry | Views / journeys | Exact retries | Recovery / contract checks | Seconds | Source files |
|---|---:|---:|---:|---:|---:|
| Commercial | 72 / 3 | 60 | 24 / 24 | 181.881 | 385 |
| Owner billing / AR | 78 / 3 | 57 | 27 / 34 | 455.711 | 385 |
| Authored library | 75 / 3 | 64 | 25 / 43 | 297.311 | 385 |
| RFI | 81 / 3 | 79 | 20 / 59 | 203.007 | 385 |
| Cross-entry SPA recovery remount | 9 cases at 1440/1024/390 | Original request preserved | Commercial / AR / library | 38.990 | 385 |

Fluent 2 requires no Microsoft sign-in. These synthetic personas are scoped practice sessions, not authenticated operational identities. The owner's direction authorizes continued implementation while financial-policy/tenant facts are recovered.

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

The original bounded read contract does not include schedule-of-values grids, documents, governed approval packets, forecasts, history seals, person-specific home queues, saved views, or server-side exports. The separate AP entry adds certified bill lines, business packets and person-scoped workflow queues as described above. No mock checks, approval thresholds, numbering, or business facts are invented for API records. The explicit read-app sample fixture supplies synthetic examples solely for layout review. `node_modules/`, `dist/`, `dist-ap/`, `dist-commercial/`, `dist-ar/`, `dist-library/`, `dist-rfi/`, local environment overrides, and test reports are ignored and must not be committed.

## Connected manual estimating

```bash
npm run build:commercial --prefix apps/cipher/web
python -m apps.cipher commercial-practice-web --port 8768
npm run smoke:commercial --prefix apps/cipher/web
```

The separate entry follows T3/T4/T5/T6/T7 with the same pinned Fluent 2 theme.
It connects owned drawing/manual quantities, exact revision comparison,
independent estimator acceptance and a PM-created source-preserving subcontract
draft. Quantities remain decimal strings, prices are integer cents, and the server
computes amounts. Every line, including zero-valued lines, remains in the draft.
Current commitment state stays separate from original draft creation status.

The [workflow reference](../docs/COMMERCIAL_PRACTICE.md) describes the seven actions,
scope, original receipts and remaining geometric/award/signature boundaries.
Unresolved requests keep their original UUID/body/version through input edits and
navigation; the original outcome is retrieved before a fresh edited-source review.
Late old-input reviews are discarded. Current person/access loss and malformed
refreshed records clear rendered facts.

The integrated actual-API browser passes 72 views, three fresh journeys,
60 exact retries, 24 recovery cases and 24 strict contract checks at
1440/1024/390, with zero unexpected HTTP/application/CSP or axe findings.
It covers source and duty loss, expiry, changed input reviews, dropped responses,
contingency holds and original outcomes after genuine later commitment execution.
No action creates journals, AP/AR balances, an outbox item or provider effect.
`CIPHER_COMMERCIAL_ARTIFACTS` and `CIPHER_COMMERCIAL_PORT` select local test output
and an unused loopback port.

Strict typecheck/build pass; the commercial chunk is 578.34 kB minified and
159.71 kB gzip. Vite's existing size advisory remains. Full saved views, exports,
notes, complete approval split panes and other template controls remain in the
backlog, alongside manual screen-reader/owner acceptance and production performance.


## Connected owner billing and AR

```bash
npm run build:ar --prefix apps/cipher/web
python -m apps.cipher ar-practice-web --port 8769
npm run smoke:ar --prefix apps/cipher/web
```

This separate Fluent entry follows the same templates and pinned theme. A PM
prepares exact cumulative claimed/reviewed lines from declared owner-contract/SOV
and distinct owned sources. A different accountant grants business approval without
a journal; an actual accountant/controller distinct from that reviewer posts under
the original grant. A separate independent request/grant/send workflow writes one
synthetic mail-sink record. Original outcomes and current lifecycle/balances remain
separate. See [OWNER_BILLING_PRACTICE.md](../docs/OWNER_BILLING_PRACTICE.md).

Current standing AR is aged at the chosen date; the screen does not claim a
historical cutoff snapshot. Native check/wire collection and return evidence is
proved before current balances are shown. Unsupported adjustment sources hold the
entry. Retainage has an aggregate balance without an invented due date.
`CIPHER_AR_ARTIFACTS` and `CIPHER_AR_PORT` select browser evidence output and an
unused loopback port. Static build passes with unchanged dependency pins and lock;
the AR chunk is 576.47 kB minified and 159.98 kB gzip. Existing bundle-size and manual
screen-reader/owner acceptance work remains.


## Authored project library

```bash
npm run build:library --prefix apps/cipher/web
python -m apps.cipher library-practice-web --port 8770
npm run smoke:library --prefix apps/cipher/web
```

The [six-action workflow](../docs/LIBRARY_PRACTICE.md) stores exact authored UTF-8 text up to 65,536 bytes, immutable predecessors and source locators. A different actual project PM grants an internal reference copy; application consumes that same grant. Original adopted text and the current revision/rights remain separate. License-tag history, including a genuine untag, holds this authored-only entry; no ownership checkbox or hash-only artifact preview substitutes for a qualified ingestion workflow.

## Governed RFI responses and synthetic distribution

```bash
npm run build:rfi --prefix apps/cipher/web
python -m apps.cipher rfi-practice-web --port 8771
npm run smoke:rfi --prefix apps/cipher/web
```

The [nine-action workflow](../docs/RFI_PRACTICE.md) preserves original issued drawing/supporting citations beside current source/rights disclosures. Registered project staff draft; an actual project PM requests, a different PM reviews, and an eligible PM applies that original grant. A separate independent review permits fixed local synthetic distribution. Grant alone does not answer or distribute. Cost/schedule impacts remain informational; no engineering stamp, change adoption or outside delivery is implied.

## Original-request recovery across form remounts

```bash
cd apps/cipher/web
CIPHER_RECOVERY_WIDTHS=1440,1024,390 node tests/recovery-remount-smoke.mjs
```

This dedicated check uses real commercial, owner-billing and library effects, drops their successful response, advances the selected source and navigates away/back through a SPA remount. All nine app/width cases must expose and retrieve the original unresolved request with the same UUID/body/version/fingerprint and receipt; a changed current source cannot silently discard it or authorize a duplicate effect. Main workflow smokes separately cover source-integrity holds, independent decisions, malformed records and accessibility.

All new entries retain the pinned React/Fluent/Griffel dependencies and shared template/theme. Vite's existing bundle-size advisory remains; production loading, manual screen-reader review and final owner visual acceptance remain unqualified. Source snapshots must include the served JavaScript bundles as well as Python/UI/configuration/test harnesses. Licensed-content distribution, PDF/CAD bytes, operational identity, live providers and durable workers remain separate work.

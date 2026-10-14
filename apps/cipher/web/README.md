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

Each action requires a read-only preflight and current record version. Changing the posting period or reason clears the review. The client retains the exact action body and repeatability UUID in memory for an explicit **Retry same action**, including navigation within the current person’s scope. A retry retrieves the original recorded outcome; a fresh read shows current state. Starting a new review, changing person/scope, losing the session, or reloading the browser discards that client memory. No cookies or CSRF tokens are persisted by the action cache. Safe changed/expired/blocked responses require refreshed facts and a new review; the client never resubmits automatically or substitutes fixture data.

Certification lines show actual installed work and period totals. There are no claimed-versus-reviewed editing fields, invoice upload, payment, provider acknowledgement, production identity or live-workspace controls in this entry. It displays grounded names and **Bill {sequence}**; it does not invent business record numbers. QuickBooks and Odoo handoffs remain later work.

```bash
npm run typecheck --prefix apps/cipher/web
npm run build:ap --prefix apps/cipher/web
npm run smoke:ap --prefix apps/cipher/web
```

The AP smoke test launches a fresh isolated backend for each of 1440, 1024 and 390 pixels, exercises the same-accountant request/post with a different project manager, verifies journal-free approval and an actual later-period post, and retries each action using the same body/UUID/receipt, including a retry after navigation. It checks a genuine competing-post refusal, a backend rejection of changed review inputs, session loss, eight malformed-contract/precision cases, keyboard focus, the posting dialog’s safe initial focus, scoped reads, style nonces, CSP/application errors and axe WCAG findings. Expected HTTP refusals are bound to the tested request’s method, path and status when it begins; their actual response evidence is retained for matching browser network messages. Every unexpected HTTP response and application/CSP error fails the check. Its screenshots and report go to `/tmp/cipher-completion/ap-browser`; `CIPHER_AP_ARTIFACTS` may choose a different artifact directory and `CIPHER_AP_PORT` an unused local test port. The accessibility run uses reduced motion so transient color animations have settled. Automated checks still leave manual screen reader and owner design review open.

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

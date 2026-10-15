# Cipher UI overhaul specification

**Superseded historical planning:** The latest owner direction requires a new product design independent of all prior Cipher/Odoo work. Odoo is interim operations only. Use [the new framework draft](framework/README.md); prior reuse, migration-dependency and workflow prescriptions below are not design inputs. Implementation awaits the owner’s framework approval.

**Committed owner decision, October 15, 2026:** [SAP_ERPNEXT_IMPLEMENTATION_PLAN.md](SAP_ERPNEXT_IMPLEMENTATION_PLAN.md) is the active architecture and delivery plan: SAP UI5 Web Components for React, ERPNext/Frappe, Cipher AEC extensions, and QuickBooks as official accounting authority. The owner selected implementation, without further framework comparisons or owner-run trials. Conflicting options and checkpoints below are historical and superseded.

Draft 2, Oct 12, 2026.

**Latest foundation review, October 15:** [ERP_FOUNDATION_REVIEW.md](ERP_FOUNDATION_REVIEW.md) reopens the presentation and ERP platform decisions at the owner's request. UI5 Web Components for React is the preferred ERP floorplan candidate; Fluent 2 remains preferred for a mandatory Microsoft appearance. ERPNext/Frappe requires an actual bounded platform proof against accepted Odoo and the Cipher control baseline. This addendum takes precedence over framework-specific prescriptions below until the foundation checkpoint is closed.

**Superseding owner direction, October 15:** The owner rejected the actual navy-shell screenshots and requested a native Cipher ERP built from Microsoft's real open-source Fluent UI/UX foundation. [FLUENT_ERP_RESET_PLAN.md](FLUENT_ERP_RESET_PLAN.md) is now the active visual and delivery contract. It supersedes this document's navy-frame/color mandates, custom T1–T10 visual compositions and extension through separate practice applications. Preserve the business scope, consequential-action boundaries and source/authority controls below; treat conflicting visual prescriptions and earlier phase estimates as historical. Use the official Microsoft starter/component references, one shared application, compact business workflows and the concrete reference-screen review gate in the reset plan.

**Owner direction update, October 14:** [PRODUCT_GOAL.md](PRODUCT_GOAL.md) defines the full Cipher scope: proposals, estimating/takeoffs, all AP/AR business work, projects/CMS, engineering and specification/contract libraries. Use this specification's Fluent 2/React v9 direction, page templates and initial design guidelines across that scope. QuickBooks may supply accounting through an API; moving official books into Cipher is optional and separately qualified. Preserve prior Odoo work through explicit mappings. The owner's instruction authorizes the design direction and its web packages; it does not adopt the proposed financial thresholds, exceptions, hosting choices or final mockups. The original phase estimates and native-cutover assumptions below are historical proposals; use the delivery backlog and product goal for current scope and acceptance.

The first connected Fluent build is an isolated, read-only practice slice under `apps/cipher/web`, colocated with this prototype rather than the proposed `apps/cipher-web` path. It uses the versioned `/api/practice/v1` read contract and a fresh in-memory backend. The synthetic engine now implements journal-free bill approval and independent posting with immutable receipts (B01); section 11.2's original blocker list remains historical. Consequential Fluent screens still require the authenticated action API, real read permissions and mockup acceptance before operational use. The read slice does not implement the production architecture in section 11.6.

Part A is the owner's brief: about four pages on what people will see, what arrives when, and the decisions we need. Part B is the build specification. It holds the detail the team needs, and nobody else has to read it.

---

## Part A. Owner brief

### A1. What changes

The current console was built as a test bench for the engine, and it looks like one. It is a single page about nine screens tall, with 25 sections, 22 tables, 54 buttons and 79 text boxes. Most areas are automatic dumps that ask for a program method name. Program codes and test switches sit next to real payment buttons, and a supplier's name could carry code that runs on the page that approves payments. Restyling wouldn't fix any of that.

We are replacing it with a new application on top of the engine underneath, which is solid and well tested. Nothing from the old GitHub screens or from earlier builds is reused. The layout follows what NetSuite, SAP and Dynamics 365 have in common: a home page for each person, a page for each job, a page for each record, and one place for approvals. Like Procore, Cipher treats the job as the place where most work happens.

### A2. What each person sees

Everyone signs in with their Microsoft 365 account and lands on their own home page. A home page has one list of what is waiting on you, at most four numbers and at most two short lists. Everything else has a page of its own.

- **You (owner):** the Company page. Pay apps and change orders over the PMs' limits, new subcontracts, monthly forecasts, and anything that needs your approval again. Below that, one line per job: contract, cost to date, projected final cost and margin. You can open any job and see what its PM sees.
- **Project managers:** My projects. Sub pay apps to review, change orders to sign, change events to price, and the monthly forecast. Every job page has the same row of tools in the same order: overview, budget and forecast, commitments, change events, sub pay apps, supplier invoices, documents.
- **Bookkeeper:** Books. PDFs that arrived in the AP mailbox, bills to enter and post, payments to record, possible duplicate invoices, and the checks that Cipher's numbers agree with each other.
- **Outside controller:** Books as well, with the monthly accountant package, call-backs on vendor bank changes, and your own approvals to review.
- **Superintendents:** in phase 1, the same pages on a tablet with bigger buttons. A field mode that works without signal comes in phase 3.
- **Estimator:** estimating comes in phase 3.

Cipher refers to people by their Microsoft 365 names, the way you would, and never by a system role.

### A3. How approvals work

- Each approval has its own page. A sentence at the top says what you are agreeing to, then come five or six facts and a short list of checks. The documents, earlier pay apps and accounting entry are one click away.
- If a fact changes after you approve, the item comes back marked "Needs approval again", with the old and new values side by side. Before anyone does something that would send approvals back, Cipher shows them which ones.
- Approving a bill, posting it to the books and paying it are separate steps. Whoever approves a bill can't post it.
- Small supplier invoices that match the purchase order and the delivery tickets can be approved by the match itself, if you want that (decision 9).
- When you're away, you can hand your approvals to someone with the same authority. The page then says who approved for whom.
- Ricky, the built-in assistant, checks every approval and points out anything that looks wrong. It never approves, posts or pays. Phase 1 has no Ricky chat box; that waits until a language model is connected.

### A4. Mockups come first

Before any screen is built, the team makes clickable mockups with practice data: the frame around every page, a PM's home page, a job overview, a subcontract, the pay app review and the approval page, each at desktop, tablet and phone size. You approve them or send them back before building starts (decision 12). The approval page will be laid out roughly like this:

```
+--------------------------------------------------------------------+
| Approve pay app #4 from Northgate Piling Co.                       |
| SC-03 Sheet piling and walers on 24-031. Period ending Sep 30.     |
|                                                                    |
| Northgate Piling Co. is owed $48,240.00 for September work and     |
| stored materials, after $5,360.00 retainage.                       |
|                                                                    |
|   Current payment due    $48,240.00                                |
|   This period            $41,200.00 of work, $12,400.00 stored     |
|   PM's review            Line 3 cut to $28,500.00 (field count)    |
|   Retainage              $5,360.00 at 10%                          |
|   Against                SC-03 as revised by CO-02                 |
|   Charged to             31 41 16 Sheet piling                     |
|                                                                    |
| Checks                   Ricky's check: Looks right                |
|   ok  Matches the schedule of values                               |
|   ok  No line over its scheduled value                             |
|   !   Conditional waiver not in yet: holds payment, not approval   |
|                                                                    |
| > Documents (4)    > Earlier pay apps (3)    > Accounting entry    |
+--------------------------------------------------------------------+
| Approving doesn't post or pay anything. The bookkeeper posts it    |
| next.                           [Send back]  [Approve $48,240.00]  |
+--------------------------------------------------------------------+
```

On the real page, people's names appear where the sketch says "the PM" and "the bookkeeper".

### A5. What arrives when

These are planning estimates for two developers working with an AI assistant, not quotes.

| Stage | Done by | What you get | Data |
|---|---|---|---|
| Mockups | Week 3 | Clickable mockups for your sign-off | Practice |
| Phase 1a | Month 2 to 2.5 | Microsoft 365 sign-in, home pages, approvals, subcontracts, entering and reviewing sub pay apps, posting approved bills | Practice only |
| Phase 1b | Month 4 to 6 | Supplier invoices with matching, an inbox for incoming PDFs, budget and forecast, change events and change orders, vendors and bank detail changes, documents, the morning email, recording payments made through your current process, the accountant package | Live, on one pilot job |
| Phase 2 | Month 7 to 11 | Paying vendors from Cipher, owner billing on AIA and EJCDC forms, receivables, bank reconciliation, month-end close, WIP, lien waivers that hold payment, RFIs and submittals, daily reports | Live |
| Phase 3 | Month 10 to 16 | Field mode that works offline, crews and certified payroll, schedule, estimating, Ricky with a language model, a larger database, a real payment provider, and moving the official books into Cipher | Live |

During phase 1, money moves the way it does today. S&A pays vendors through its current process, the bookkeeper records each payment in Cipher, and the outside accountant keeps the official books. Billing figures such as billed to date and over or under billing stay out of Cipher until owner billing arrives in phase 2 (decision 17).

### A6. Decisions we need from you

| # | Decision | Our recommendation |
|---|---|---|
| 1 | The direction: a home page per person, a page per job with fixed tools, one approvals page, and posting and paying kept apart from approving | Yes |
| 2 | Let the web layer use outside software packages, and the screens use a build tool | Yes. The engine itself stays free of outside packages, and every package is pinned to an exact version and listed |
| 3 | Who approves sub pay apps | The PM, when the work and stored materials billed for the period come to $50,000.00 or less, counting whichever is larger: what the sub claimed or what the PM approves. You approve anything above that. The bookkeeper posts |
| 4 | Who approves sub change orders and budget transfers | The PM drafts and approves in one step, within $25,000.00 per change order or within the job's contingency for a transfer, and each one shows on your Company page for a week. Above that, you approve. A change order is executed only after the sub signs it. The alternative, having someone else draft every change order, would send most of them to you |
| 5 | How long approvals stay open | 10 days for pay apps, invoices and change orders, 7 for forecasts and bank changes, 14 for new subcontracts (Part B, 7.4) |
| 6 | When you may approve your own request | When nobody else who could approve it is available, or with a written reason. The outside controller reviews each one within 7 days. Never for a bank change you asked for, releasing a payment you approved, or loosening the payment rules |
| 7 | What holds an approval and what holds payment | An unsigned subcontract holds approval. Expired insurance, a missing W-9, or a missing conditional waiver for the pay app being paid holds payment. A missing unconditional waiver for the previous payment is a warning only |
| 8 | Chart of accounts and posting rules | Load the outside accountant's chart of accounts, and have the controller sign the posting rules for stored materials and retainage before anything posts |
| 9 | Small supplier invoices | An invoice under $5,000.00 that matches its purchase order and delivery tickets within 2% or $100.00, whichever is less, is approved by the match. Anything else goes to the PM |
| 10 | Microsoft 365 license | Tell us whether the company has Business Premium. If it does, the sign-in check before releasing payments can use its stronger controls |
| 11 | Where the pilot runs | One Azure Linux server per environment, with about a minute of downtime for each update. Move to a larger database before the official books come into Cipher |
| 12 | Look and feel | Send the exact lime color and the logo files. Approve the mockups before any screen is built |
| 13 | The old console | Delete it before the pilot starts. It never runs against live data |
| 14 | Taking over a restored backup | You sign in again with Microsoft 365, Cipher checks a recovery key it keeps in Azure Key Vault, and the outside controller is told. A recovery code you keep offline is the fallback |
| 15 | The pilot job | A new job starting in the phase 1b window, run by a PM willing to put every pay app and change order on it through Cipher |
| 16 | Paying vendors from Cipher (phase 2) | Payments of $25,000.00 or more and first payments to a new account are high risk; a second signer at $100,000.00; a 3-day wait after any bank change. The bookkeeper prepares each run and you release ordinary payments. For high-risk payments you approve and the outside controller releases, so three people touch every large payment. One fresh sign-in per high-risk payment, and one covering only the ticked ordinary payments for 10 minutes |
| 17 | Billing figures during phase 1 | Leave them out until owner billing arrives in phase 2. The outside accountant's WIP schedule stays the source |
| 18 | Certified payroll and prevailing wage | Phase 3, since S&A likely bids public water, wastewater and DOT work under prevailing wage |

---

## Part B. Build specification

This part is for the build team. The code is `apps/cipher` on branch `cipher/synthetic-prototype`, and the plan that specifies the system is `CIPHER-PLAN-v1.0.md`. This part replaces `apps/cipher/console/index.html` with a new application and says what the backend must add. Section numbers refer to Part B unless they start with A.

**Conventions in the examples**

- On screen, people always appear by their Microsoft 365 display name. The examples put a role in braces where the name goes: {owner}, {PM}, {PM 2}, {bookkeeper}, {controller}, {superintendent}. A role word never appears on screen in place of a name.
- "Owner" alone means S&A's owner. The client is named ("Ashford") or appears inside the trade terms owner billing, owner pay app and owner change order.
- Companies, jobs and amounts are invented. Every example is from Tuesday, Oct 13, 2026, and the figures tie out across screens.
- Anything marked (phase 2) or (phase 3) is not built in phase 1. Untagged elements are phase 1, and section 5 says whether they land in 1a or 1b.
- The products each pattern comes from are listed in Appendix B, not in the text.

### 1. Design principles

1. **One job per screen.** Each page is a home page, a list, a record, a decision or a focused task. No module dumps, stacked panels, or pages that show a whole job at once.
2. **Your work first.** You land on what is waiting on you, based on who signed in. No shared dashboard, no role dropdown, no viewing the screen "as" someone else.
3. **The approver sees what the server will execute.** The server writes every approval page from the facts it binds, and the Approve click carries a fingerprint of what was shown. No summaries written by the browser, no raw JSON, no Approve buttons on list rows, home pages, notifications or email.
4. **Approve, post and pay are separate acts.** Each has its own screen, verb and person, and the backend enforces it. No "approve and pay" buttons, no releasing money from a bill, no step that quietly triggers the next.
5. **Nothing is hidden.** Stale, blocked and expiring items say so in words, with the reason, the fix and who can act. An action that will send other approvals back says so before the click. No buttons that vanish without explanation, no color-only status, no reasons that live only in a tooltip.
6. **Speak the trade.** Labels use the words S&A's PMs, superintendents and bookkeepers use. Operation names, database statuses, IDs, hashes and internal version numbers stay under Technical details.
7. **Dense at the desk, big in the field.** Office pages default to compact rows. Any touch screen gets targets of at least 44 px. Densities are never mixed on a page.
8. **Plain and finished.** A navy frame, a white work surface, one small accent, and only tools that work. No gradients, glows, card walls, emoji, lime text on white, or empty screens for features the backend can't support yet.

### 2. Users and duties

S&A is a small owner-led team, and one person often holds several duties. Backend roles are those in `ROLE_AUTHORITY` (`domain/ricky.py`), except the field role, which doesn't exist yet.

| Person | Backend role today | Main device | How often | Top jobs in Cipher |
|---|---|---|---|---|
| Owner | `owner` (every duty) | Desktop; phone for approvals | Daily | Approve pay apps and change orders over PM limits, new subcontracts, forecasts and (phase 2) high-risk payments; watch margin and cost |
| Project manager | `pm` | Desktop in the office or trailer; tablet on site | Daily | Review sub pay apps and approve those within the limit, draft and sign change orders, price change events, update the monthly forecast; (phase 2) prepare owner pay apps, answer RFIs |
| Superintendent or foreman | none yet; a `field` role arrives in 1b for delivery receipts and notes | Tablet or phone, gloves, sun, weak signal | Several times a day | Phase 1: confirm deliveries and add notes and photos on a tablet. Later: daily reports, crew time, quantities, T&M tickets |
| Estimator | `estimator` | Desktop | Weekly, heavy around bids | Phase 3: estimates tied to drawing revisions, bids, quotes |
| Bookkeeper, who also handles payables | `accountant`; often `reconciler` | Desktop | Daily | Work the Incoming inbox, enter sub pay apps and supplier invoices, post approved bills, record outside payments; (phase 2) prepare payment runs |
| Outside controller | `controller`; often `bank_admin` | Desktop, remote | Weekly and at month-end | Review postings and tie-outs, confirm outside payments, verify bank changes, review the owner's own approvals, receive the accountant package |
| Whoever releases payments (phase 2) | `treasury` | Desktop | Once or twice a week | Check each payment line and release it after a fresh sign-in |

On screen, duties are described as abilities ("Can verify bank changes", "Can release payments", "Can reconcile bank accounts"), never as job titles.

Rules for a team this size:

- **Separation is checked by person.** One person may have more than one Microsoft 365 account (an admin account, for example), and all of them count as that person. Today `people_persons` allows one login per person, so identity binding has to become many-to-one (11.3).
- **Several duties merge home pages.** The owner lands on Company and sees money items from every duty first.
- **Gaps are visible.** Settings > People shows who can do each step and warns when a rule leaves nobody (6.15).
- The solo-owner rule is in 7.9.

### 3. Information architecture

#### 3.1 The shell

```
+-- Top bar: navy, 48 px (56 px on touch) ------------------------------------------------+
| [S&A] Cipher | 24-031 Lift Station 4 Cofferdam v | Search (Ctrl+K) | + New | Bell | Profile |
+-- Strip: 32 px, only on practice or restored copies, a history mismatch, ---------------+
|   or (phase 2) stopped payments                                                         |
| Left rail       | Page content                                 | Side panel (optional)   |
| navy, 232 px;   | job header and tool bar when inside a job    | 400 to 480 px, one at a |
| 56 px of icons  |                                              | time: quick look, quick |
| when collapsed  |                                              | create, help            |
|  Home           |                                              |                         |
|  Approvals  5   |                                              |                         |
|  Projects       |                                              |                         |
|  Books ...      |                                              |                         |
+-----------------------------------------------------------------------------------------+
```

- **Job picker:** All jobs, then Pinned, Recent and All active jobs, job number first. Switching jobs keeps you on the same tool, so 24-031 Sub pay apps becomes 25-012 Sub pay apps. Pinned jobs live only here.
- **Rail:** Home, Approvals, Projects, Payments (phase 2), Books, Vendors and subs, Reports, Settings. Areas a person can never use are hidden. Approvals carries the number of items waiting on you as a lime badge with navy text. There is no second Approvals button in the top bar.
- **Profile:** your name, your duties in words ("Project manager on 24-031 and 25-012"), Out of office, density, single-key shortcuts on or off, Sign out. No role switcher.
- **Tablet top bar** (600 to 1023 px, and any touch screen whatever its width): the S&A mark, the job number only (it opens the picker), a search icon, the bell, and More for + New and Profile.
- **Strips** mark a copy or a state that changes what you may do:
  - Practice copy: "Practice data. Nothing here is real money and nothing is sent."
  - Restored copy: "This is the Oct 9 backup. It's read-only until {owner} confirms it's the copy to keep." {owner} also sees [Make this the live copy] (7.10).
  - History mismatch, in red: "History doesn't match the sealed copy from Oct 12. Approvals and posting are stopped until {controller} checks it."
  - Payments stopped (phase 2), in red: "Payments were stopped by {owner} at 3:10 pm: "bank called about a suspicious change". Restarting needs someone else's approval."
  - When more than one applies, the most serious shows with "1 more", which opens the rest.
  - Normal live books get no strip, so a strip always means something. "Working ledger" is a label in the Books page header, not a strip (6.10).

#### 3.2 Company level and job level

- The left rail is always company level.
- Inside a job, the page gets a job header (number and name, status, client, state, contract type, billing form, then key facts with revenue and cost in separate groups) and a fixed tool bar.
- Company lists always have a Project column. Jumping from a job to a company list arrives filtered, with a removable chip: "Project: 24-031 ×".

**The job tool bar.** Each person sees at most 8 tools in a fixed order, and the rest sit under More. A tool whose backend isn't ready is hidden. When it arrives it takes its reserved place, and the tools already there keep their order.

| Tool | What it holds | Ships in |
|---|---|---|
| Overview | Needs attention, cost by month, this month's pay app cycle, key dates, recent activity | 1a |
| Budget and forecast | Budget by cost code and cost type, the monthly forecast, budget transfers, snapshots | 1b |
| Commitments | Subcontracts and purchase orders | 1a (subcontracts), 1b (purchase orders) |
| Change events | Change log with cost and revenue sides, sub change orders, owner change orders | 1b |
| Sub pay apps | Pay apps from subs across all commitments, by period | 1a |
| Supplier invoices | Material, rental and trucking invoices, with or without a PO | 1b |
| RFIs and submittals | Logs and responses | 2 |
| Documents | Drawings and specs with revisions, contracts, certificates, waivers, photos | 1a on the practice copy's disk, 1b on Azure Blob |
| Owner billing | Prime contract terms, owner pay apps (AIA G702/G703, EJCDC C-620, unit-price estimates), payments received | 2 |
| Daily reports, Closeout | Office review of field records; closeout requirements and retainage release | 2 |
| Schedule | Activities and a 3-week lookahead | 3 |
| History | Every decision on the job, as sentences | 1a |

The order for each person:

- **PM:** Overview, Budget and forecast, Commitments, Change events, Sub pay apps, Supplier invoices, RFIs and submittals (phase 2), Documents. More: Owner billing (phase 2), Daily reports (phase 2), Closeout (phase 2), History.
- **Owner:** Overview, Budget and forecast, Commitments, Change events, Sub pay apps, Supplier invoices, Owner billing (phase 2), Documents. More: RFIs and submittals, Daily reports, Closeout, History.
- **Bookkeeper:** Overview, Commitments, Sub pay apps, Supplier invoices, Owner billing (phase 2), Documents. More: Budget and forecast, Change events, History.
- **Controller:** Overview, Budget and forecast, Commitments, Sub pay apps, Supplier invoices, Owner billing (phase 2), Documents. More: Change events, History.
- **Superintendent:** Overview, Supplier invoices (to confirm deliveries), Daily reports (phase 2), RFIs and submittals (phase 2), Documents. More: History.

#### 3.3 Sitemap

```
Sign in with Microsoft 365
Home: Company, My projects, Books; Payments (phase 2); Estimating and Today (phase 3)
Approvals: Waiting on you, Needs approval again, Sent by you, Done
  Approval page                    /approvals/A-26-0418
Projects
  All projects
  Job hub                          /p/24-031
    Overview
    Budget and forecast: Budget, Forecast for September 2026, Budget transfers, Snapshots
    Commitments -> Subcontract or PO record
        tabs: Schedule of values, Change orders, Pay apps, Payments, Compliance, Documents, History
    Change events -> Change event -> Sub change order, Owner change order
    Sub pay apps -> Entry beside the PDF -> Review -> Approval page
    Supplier invoices -> Invoice record with match
    Documents, History
    Phase 2: Owner billing, RFIs and submittals, Daily reports, Closeout.  Phase 3: Schedule
Books
  Incoming, Post approved bills, Payables (all bills, AP aging, outside payments),
  Accountant package, Controller review, Exceptions
  Phase 2: Receivables, Bank reconciliation, General ledger and journal entries,
           Month-end close, WIP schedule, Retainage, Equipment, 1099 and W-9
Payments (phase 2): Ready to release, Not ready, On hold, Waiting for bank, Returned, Sent
Vendors and subs: vendor record (compliance, waivers, bank details, contacts, bills, payments),
  bank detail changes
Reports: job cost, AP aging, audit export; phase 2 adds WIP, AR aging, retainage, cash
Settings: people and duties, approval and payment policy, cost codes, chart of accounts,
  numbering, compliance requirements
Help: glossary, practice copy
Field mode (phase 3)
Practice tools (practice copies only)
```

#### 3.4 Home pages

A home page is the landing page for an area. Home shows the one for your main duty, with tabs for the others you hold.

Every home page has the same limits: one "Waiting on you" table, at most 4 count tiles, at most 2 short lists, 4 to 6 pinned actions and a "Coming up" list of 3 to 5 dated items. Anything more belongs on a list page, and the limits apply to the owner's page too.

| Home | Waiting on you | Tiles (4 at most) | Short lists | Phase 2 adds |
|---|---|---|---|---|
| Company (owner) | Pay apps and change orders over PM limits, new subcontracts, forecasts, anything needing approval again, overdue reviews of the owner's own approvals | Due to vendors in 14 days; Bills waiting to post; Pay apps waiting on PMs; Projects projected over budget | Projects at a glance; Approved within PM limits, last 7 days | High-risk payments in the table; a cash tile from the reconciled bank balance; billed to date and billing position columns |
| My projects (PM) | Sub pay apps to review, change orders to sign, change events to price, forecasts due, invoices without a PO to confirm | Pay apps to review; Open change events; Cost codes over budget; Certificates expiring in 30 days | My projects; Change events not priced | RFIs and submittals due; billed to date and billing position columns |
| Books (bookkeeper, controller) | Incoming documents, bills to post, outside payments to record or confirm, possible duplicates, bank changes to call back, the owner's own approvals to review, the accountant package, exceptions | Bills to post; Documents in Incoming; Tie-outs off; Due to vendors in 14 days | Ties to the general ledger; Accountant package for the month | Bank lines to match; close checks; owner billings over 30 days |
| Payments (phase 2) | Ready to release, needing approval again, waiting for the bank, returned, exceptions | Ready to release; On hold; Waiting for bank; Returned | This week's runs | |

Bank changes to call back appear on the Books page of whoever can verify bank changes. Estimating and the field "Today" page come in phase 3.

**Waiting on you** is a table, not a stack of sentences:

| Column | Content |
|---|---|
| Title | Verb first, 12 words at most: "Review pay app #4, Northgate Piling Co." |
| Job | 24-031 |
| Amount | Right-aligned, with cents, blank when there is none |
| Waiting | "5 days" |
| Expires | "Oct 18"; on the last day "Today, 4:00 pm" in the warning color |
| Marker | At most one chip: Over your limit, Needs approval again, Waiver missing |

Rows are grouped by the action needed, money items first, and empty groups are hidden. Full sentences are kept for reasons (why something is blocked or needs approval again) and for empty states. An empty table says what comes next: "Nothing is waiting on you. Northgate's next pay app is due Oct 30."

A status sentence under the page title is optional and carries only a fact the page doesn't show elsewhere. Each tile opens the list behind its number. Counts come from a cached read model and show "Updated 2 min ago" (11.3).

#### 3.5 Addresses and record numbers

Every list, filter, record and tab has a URL that can be pasted into Teams, for example `/p/24-031/commitments/SC-03?tab=sov`, `/p/24-031/pay-apps?status=under-review`, `/approvals/A-26-0418` and `/books/payables?view=outside`. URLs may carry machine dates; screens never do. If a job is renumbered, the old number keeps working as an alias, so pasted links don't break.

Screens never show internal IDs like `cmt_001a1327f727...`. They sit under a "Technical details" disclosure with a Copy button. An approval's number lives only in its URL and Technical details; on screen an approval is named by its subject ("Approve pay app #4 from Northgate Piling Co."). Record numbers are scoped to the job, the way contractors talk, and carry the job number outside it.

| Record | Inside its job | Elsewhere |
|---|---|---|
| Job | 24-031 | 24-031 Lift Station 4 Cofferdam |
| Subcontract, purchase order | SC-03, PO-06 | 24-031 SC-03 |
| Sub change order | SC-03 CO-03 | 24-031 SC-03 CO-03 |
| Sub pay app | SC-03 pay app #4 (the sub's own application number) | Pay app #4 from Northgate Piling Co. (24-031 SC-03) |
| Change event | CE-021 | 24-031 CE-021 |
| Potential change order to the client | PCO-06 | 24-031 PCO-06 |
| Owner change order | Owner CO #3 | 24-031 Owner CO #3 |
| Owner pay app (phase 2) | Owner pay app #8 | 24-031 owner pay app #8 |
| Supplier invoice | The supplier's number: invoice 88530 | Keel Ready-Mix invoice 88530 |
| Vendor; payment (phase 2) | V-0142; PMT-1043 | Same |
| Approval | URL and Technical details only | A-26-0418 |

#### 3.6 Search and the command palette

One palette opens from the search box, Ctrl+K or "/", grouped into Records, Pages and Actions on this page. Recent items show before you type.

- **Prefixes:** `job:`, `sc:`, `po:`, `pay:`, `ce:`, `co:`, `inv:`, `v:`, and `rfi:` in phase 2. Example: `pay: northgate 4`.
- **Trade synonyms:** "pay app", "pay application", "progress bill" and "requisition" find sub pay apps; "sub", "SOV", "CO", "PCO", "AIA", "G702", "C-620", "COI" and "waiver" all work.
- **Typed filters in list search**, kept in the URL: `amount>10000 status:"needs approval"`.
- Search can open any page. It can never approve, post or release.

**+ New** shows only what you create. PM: change event, subcontract, purchase order. Bookkeeper: sub pay app, supplier invoice, vendor. Owner: job.

**Keyboard:** "?" lists every shortcut; G then H, A or P jumps to Home, Approvals or Projects; J and K move through lists. Single-key shortcuts can be switched off. The A key approves only timecards (phase 3). Nothing involving money, and nothing that goes outside the company, is approved from a single key or in a batch.

#### 3.7 Notifications

- **The bell** holds background results and mentions: "Pay app #4 from Northgate Piling Co. needs approval again", "{PM} mentioned you on SC-03", "Granite's waiting period ends Oct 16 at 9:00 am". Each links to its record and expires after 30 days.
- **A 7:00 am email** lists what is waiting and what is expiring. It is sent through Microsoft Graph from a shared mailbox and holds links only; nothing can be approved from email.
- **Teams** comes later, through Teams Workflows.
- Nothing goes out from a restored copy that hasn't been made live, and practice copies send only to the test mailbox. Email from a copy in recovery starts with the restored-copy sentence.

#### 3.8 Where approvals live

You decide only where the full approval page is shown, and two places show the same server-built page:

1. **The Approvals page:** a list on the left, the approval page on the right. Most decisions happen here.
2. **The record's Approval panel:** a PM who has just reviewed a pay app can decide from the panel on that pay app.

Home rows, notifications and the email only link to it. Posting and payment release aren't approvals: posting lives in Books > Post approved bills, and release in Payments > Ready to release (phase 2).

#### 3.9 Ricky

- **Ricky's check** heads the Checks list on every approval page and on the pay app review: a label (Looks right, Worth a look, Don't approve yet), plus lines only for what Ricky finds beyond the rule checks (7.11).
- **Explain** links sit beside warnings and problem messages. They open the rule in plain words and the records it looked at.
- Ricky can fill in a Send back reason from its findings, marked "Draft by Ricky. Nothing has been saved." A person edits it and presses the button.
- There is no Ask Ricky button and no chat panel until a language model is connected (phase 3). A chat box that can't chat would break principle 8.
- Ricky never has an Approve, Post, Sign, Send or Release button, has no section on home pages, and every page works without it.
- On the server, Ricky can read and draft as the signed-in person and do nothing more (11.2).

#### 3.10 Tablets and phones

- **Tablet, 600 to 1023 px, and any touch screen:** the rail goes behind a menu button, the tool bar scrolls with More, side panes drop below the content, and every target is at least 44 px.
- **Pay app review on a tablet:** the grid shows Line, Description, Sub claimed, Approved, % and Why it differs. Tapping a row opens a line sheet with a number pad and the other G703 columns. The G702 summary becomes a sticky bottom bar showing Current payment due, and tapping it opens the full summary as a drawer.
- **Phone, under 600 px:** a bottom bar with Home, Approvals, Search and More. One pane at a time.
- **Approving on a tablet or phone:** the approval page is one column with every fact above a pinned footer, so the button is always in the same place. For $25,000.00 or more, Approve turns on only after the facts have scrolled into view, and until then the line under it reads "Scroll through the facts to approve."
- **Field mode** (`/field/...`, phase 3) is a separate stripped layout (T10).

### 4. Page templates

Pages are built by hand from shared components (RecordGrid, PageHeader, KeyFacts, LifecycleRail, MessageBar, ApprovalPage, WhatChanged and the rest), so lists and records behave alike without a generic renderer. The server supplies the data and, for each record, the actions this person may take, with a reason when one is unavailable (`actions[]`, 11.4). It doesn't publish page layouts.

**Who owns which words.** The server owns approval-page sentences, unavailable-action reasons and problem messages, because they must match the facts it binds. The front end owns labels, navigation, column headers, help text and empty states, in typed page files under `src/features/` and `src/copy/`. The copy test (9.5) and a review by someone who does pay apps for a living cover both.

Rules for every template:

- One primary button per page. Record actions sit top right; finalizing actions (Approve, Post, Release, Save and send) sit bottom right in a footer.
- Business status (Draft, Under review, Approved, Posted, Paid) is separate from the editing marker (Draft saved 10:42 am, Being edited by {PM}, Needs approval again, Read-only copy).
- **Unavailable actions:** hidden if you can never take them (the lifecycle rail names who can); otherwise visible but disabled, with the reason written under the button as text, because tablets have no hover, and a link to fix it.
- Density is set once per device and never mixed on a page.
- **Help (?)** in every page header opens a panel with 3 to 5 sentences on what the page is for and the usual steps, a link to the glossary, and a "Practice on sample data" link that opens the practice copy.
- Abbreviations (SOV, PCO, COI, WIP, T&M, C-620) have a dotted underline and open a definition on click or tap.

**T1. Home page.** Title, tabs for the other home pages you hold, an optional status sentence. Left two-thirds: Waiting on you (3.4). Right third: tiles in a 2 by 2 grid, each a number, a label and a source line ("From 11 posted bills"). Below: one or two short lists (7 columns at most), pinned actions and Coming up. Tiles show whole dollars, with the exact amount on hover or tap. No charts in phase 1.

**T2. Job overview.** A sticky job header that shrinks to one line on scroll ("24-031 Lift Station 4 Cofferdam, Active, projected margin 14.0%"), key facts in Revenue and Cost groups in whole dollars, then the tool bar. Left: "Needs attention on this job" (5 message bars at most, one action each), "Cost by month" (a cost curve with a table toggle), "This month" (the pay app cycle). Right: open item counts, the next 3 key dates, the job team by name, the last 5 history entries.

**T3. List.**
1. Title with count and one primary button: "Sub pay apps (38)" [Enter pay app].
2. Saved views as tabs with counts: Under review (5), Revise and resubmit (1), Approved, not posted (2), Posted, not paid (7), Paid outside Cipher (23). A view can be personal or shared with the team, and each person can set their default.
3. Filter bar: search plus up to 4 chips with counts per value, More filters, Clear. Live filtering, no Go button. Two chips on phones.
4. RecordGrid: frozen first column with the record number and name as a link; a marker column (Needs approval again, Don't pay yet, On hold) with popovers; money right-aligned with tabular digits; a pinned totals row computed in integer cents on the server; sticky header; column picker; fewer than 15 columns.
5. **Export to Excel** exports the current view: its filters, columns, totals and Project column, with readable record numbers and no internal IDs. Each export is logged with who, when and how many rows.
6. A batch bar when rows are selected. Partial processing is stated first: "2 of 5 timecards can't be approved. Their cost codes are closed. Approve the other 3?" Money approvals, sends outside the company and payment release are never batch actions.
7. Server paging. A row click opens the record; Space opens a 480 px quick look.
8. Empty states for first use ("No change events on this job yet. [New change event]"), filtered ("No pay apps match these filters. [Clear filters]") and no access ("You don't have access to Payables. Ask {owner}.").

**T4. Record page.**
- Header: type label, number and name, a subtitle with counterparty, job and key terms, the status chip and marker. Actions top right: one primary, up to two secondary, More.
- Key facts: 5 to 8 figures; cost and revenue never share a group.
- Lifecycle rail on money records: each separate step in order, who can do it (by name), whether and when it was done, and who acts next.
- Message bars: 3 at most, blocked before warning before info, one action each, 25 words at most.
- Tabs: 7 at most, with counts, History last.
- Side pane (320 px): Approval, Ready to pay, Bank details, Related records, Notes. Read-only cards, except Notes. Below the content on phones.
- **Notes:** plain text with @mentions (bell and email; Teams later), kept apart from History, and never able to change a fact. Notes on an approval show to the next person in the chain.
- Opens read-only. Posted or executed records never become editable; their only path is Correct (credit note, correction or reversal, through approval).
- Edits send the record's version. If someone saved first: "{PM} changed this subcontract at 10:51 am. Your changes weren't saved. [Reload]".
- History: sentences grouped by day, a People or System filter, exact time with time zone, and [Download history (CSV)]. At the top sits a small tag, "Matches the sealed copy, Oct 12", whose popover reads "History matches the copy sealed in the locked archive on Oct 12 at 2:00 am." Internal version numbers appear only here and in Technical details.

**T5. Approvals inbox and approval page.**
- A 360 px list with tabs Waiting on you, Needs approval again, Sent by you and Done. Rows are grouped by type and show title, job, amount and expiry. Sent by you shows who holds each item and for how long, with [Withdraw] (reason required) until someone decides.
- The first item opens on load, with the approval page filling the right side and its footer pinned. On phones the list and the page show one at a time.
- Approval page order: title and a one-sentence summary; 5 or 6 key facts; one Checks list with Ricky's label at its head; collapsed sections for Documents, Earlier pay apps (or the record's history), Accounting entry and Who does what; a one-line consequence above the footer; the footer.
- **After a money decision** the toast confirms it, and clicks are ignored while it shows. On a desktop the next item opens with its footer disabled for about a second, under a header such as "Next: new subcontract SC-04 with Bluestone Dewatering LLC, $318,000.00". On phones the list comes back instead.
- **Forward** passes an item to a colleague who holds the same authority, with a note. **Out of office** (in Profile) sets dates and a delegate who already holds the authority. The policy is checked, separation still applies, and the page says "Approving for {PM} while they're out".
- **Co-sign** (phase 2) is its own item type: the same page, with [Co-sign $112,400.00] and the independence rule stated above the button.

**T6. Grid entry and the pay app flow.** Used for sub pay app entry and review, owner pay apps (phase 2), schedule of values setup, the monthly forecast and budget transfers.
- The rail collapses. A fixed context header names the record and period. The grid is full width with Line and Description frozen. A 320 px rail holds the G702 or C-620 summary with "Current payment due" in large type (on tablets, the sticky bottom bar in 3.10). A sticky footer holds the save state and the actions.
- **Entry mode** splits the screen: the sub's or supplier's PDF on the left, the grid or form on the right.
- Tab moves across, Enter moves down. A line accepts a quantity, a percent or dollars, with a small calculator. Paste from Excel works.
- Validation: a red outline and icon, the message beside the cell, a count in the footer, and a fix button when the right value is known. The server checks the business rules through preflight (11.3); the browser checks only the shape of what was typed.
- Review mode puts "Sub claimed" beside "Approved". Any difference needs a reason, which prints on the pay app PDF.
- Unit-price lines have separate quantity and value columns (bid quantity, unit, unit price, quantity this period, quantity to date, amount to date). A column never mixes percent, dollars and square feet.
- Drafts autosave every 20 seconds to the app-state database, not the books. They lock to their editor and offer Resume or Discard on return.
- **Signed out while working:** after 30 minutes idle the page stays as it is and shows "You were signed out after 30 minutes. Sign in to keep working." Signing in returns you to the same cell with the autosaved draft. Nothing typed is lost.

The pay app is not a wizard. It has three stages: the bookkeeper's entry beside the PDF, the PM's review, and the approval page. "Copy from last period" speeds entry, and once daily reports exist (phase 2) the grid suggests quantities from them ("Daily reports show 29 pumping days. Use 29?").

**T7. Forms and setup checklists.** Forms of 6 fields or fewer (add stored materials, record a payment made outside Cipher, add a vendor contact) open in a 400 px side panel. Longer forms are a record page in edit mode, 720 px wide at most, with labels above fields, help text under them, and focus on the first empty required field. Long one-off setups (Set up a job, Set up a subcontract, Onboard a vendor) use a numbered checklist you can do in any order, ending in a Review step.

**T8. Guided checklist.** Used for the accountant package, subcontract closeout, the recovery checklist and (phase 2) month-end close. Left: numbered steps with an icon and a word (Done, Open, Blocked), the preparer and reviewer, and sign-off times. Right: the selected step and the action that fixes it. Header: "4 of 6 parts ready". The final action sits in the footer, disabled until every required step is done, with the reason under it. Steps open in any order.

**T9. Reports and settings.** Reports have a parameter bar (As of, Period, Project, Snapshot), a printable layout with S&A letterhead, Export to Excel, Print, drill-down from every figure, and formulas on column headers. Until the books move over, anything printed from Cipher's ledger carries the watermark "Working ledger, not for issue". Settings have sections on the left and forms on the right. Duty grants, account bindings and policy changes are requests waiting for approval, never switches (6.15). Practice tools appear only on practice copies.

**T10. Field views (phase 3).** A navy header with the job, the date and the sync state ("Saved on this tablet. 2 waiting to send."). Today shows 4 to 6 large task tiles; one task per screen; 48 px targets; 16/24 body text; an outdoor high-contrast theme; a bottom bar of Today, Time, Quantities, Photos and More; "Copy yesterday" on daily reports and crews. Every queued entry carries an idempotency key, so a retry never duplicates. No money and no approvals offline.

**Side panels and dialogs** (all templates). Quick look (480 px), help and quick-create panels don't block the page. One is open at a time, Esc closes it, and focus returns to whatever opened it. Decision dialogs appear only when money moves, a step can't be undone, something leaves the company, or other approvals will be sent back: post, record an outside payment, execute a change order, void, lock a budget, make a restored copy live, send to a vendor or the client, send back or reject (to capture the reason), and (phase 2) release and stop payments. The title asks the question with the key fact ("Post pay app #4 for $48,240.00?"). The body repeats the bound facts and the consequence. Buttons name outcomes ("Post to September 2026", "Don't post"), and focus starts on the safe one. Never "Are you sure?", never OK.

**Effects before the click.** Any action that will send other approvals back lists them in its dialog, worked out by a server dry run (11.3): "Adding this revision sends 1 approved item back for approval: pay app #4 from Northgate Piling Co., $48,240.00, approved by {owner} at 9:10 am." When the person acting also holds the authority to approve those items, the dialog offers to approve them again right there. When nothing is affected but someone might expect it to be, the dialog says so: "Pay app #4 isn't affected. CO-03 first appears on pay app #5."

### 5. Screen inventory

**Release:** 1a, 1b, 2 or 3 (section 12). **Backend:** "Exists" means the domain logic exists, usually without a proper read API; "Build" means new work. Every screen also needs the 1a platform: sign-in, reads with read permissions, numbering, structured errors and preflight (11.3).

| Screen | Purpose and main content | Main actions | Who | Rel. | Backend |
|---|---|---|---|---|---|
| Sign in | Microsoft 365 sign-in with the S&A mark | Sign in | All | 1a | Build: Entra sign-in, sessions, many-to-one account binding |
| Shell and search | Top bar, rail, strips, palette, help | Switch job, search, New | All | 1a | Build: who-am-I, cached counts, search index |
| Home pages | Waiting on you, tiles, short lists, pinned actions, Coming up | Open items | Owner, PM, bookkeeper, controller | 1a, finished in 1b | Build: home read model with cached counts |
| Approvals inbox | Tabs, grouped rows with expiry, withdraw, forward, out of office | Open the approval page | Approvers | 1a | Exists: `approvals.list`. Build: inbox query with eligible approvers, decide-by and outcome columns, delegation, withdraw, forward |
| Approval page | Server-written summary, facts, checks, collapsed detail, footer | Approve, Send back, Reject | Approvers | 1a | Exists: request, grant, reject. Build: presenters that fail closed, fingerprint check at grant, structured stale reasons, re-check job |
| Controller review | The owner's own approvals | Mark reviewed, Raise a concern | Controller | 1a | Exists: `people.review_self_approval`. Build: list |
| Ricky's check | Label and extra findings on approval pages and reviews; Explain links | Explain | All | 1a | Exists: rule-based brief. Build: read-and-draft-only surface, page context. Phase 3: chat with a language model |
| Projects list and job overview | Jobs with contract, cost and projected margin; job header, needs attention, cost by month, key dates | New job, open tools | Owner, PM, bookkeeper | 1a | Exists: minimal projects. Build: job master fields, key dates, single-source contract value |
| Budget and forecast | Budget by cost code and cost type, monthly forecast with reasons, transfers, snapshots | Budget transfer, Send forecast to {owner} | PM, owner, controller | 1b | Exists: versioned budgets, `budget.revise`, snapshots. Build: cost code master, PM projections with reasons, forecast approval, labor cost import. Remove `set_budget` |
| Commitments and subcontract record | SOV, change orders, pay apps, payments, compliance, notes | Enter pay app, New change order, Close out | PM, bookkeeper, owner | 1a | Exists: commitments, SOV, retainage. Build: numbers, dates, scope, terms, draft edits, retainage step-down |
| Set up subcontract | Vendor and scope, SOV with cost codes, retainage, insurance and W-9, signed agreement | Send for approval | PM, bookkeeper | 1a | Exists: `create_commitment`, `contracts` (untracked). Build: commit it; a severity on each requirement |
| Change events, sub and owner change orders | One log with cost and revenue sides; PCOs; lines changed, old and new | New change event, Sign and execute, Send PCO | PM, owner | 1b | Exists: `propose_change`, `change.execute` (one line, no cost code). Build: register, multi-line changes with cost codes, owner change orders under approval, PM-limit policy, effects preview |
| Incoming | PDFs from the AP mailbox or dropped in | Enter as sub pay app, Enter as supplier invoice, Attach to a record, Not a bill | Bookkeeper | 1b | Build: Graph mailbox intake, file store, routing, reply matching |
| Sub pay apps: list, entry, review | Entry beside the PDF; G703 review grid with claimed and approved; G702 rail | Send for review, Save review, Send back, Approve or Send to {owner} | Bookkeeper enters; PM reviews | 1a | Exists: `certify_bill`, stored materials, retainage. Build: pay app records with application number and revision, intake and reviewer records, line-scoped binding, re-check, unit-price lines, limit basis |
| Supplier invoices | Match to PO and delivery tickets, duplicate check, coding, sales tax, invoices with no PO | Match, Send for approval, Reject | Bookkeeper, PM | 1b | Exists: `ap_intake` match (equipment POs, no tolerance) and duplicates. Build: quantity POs, partial receipts, tolerance, non-PO path, payable created from a match, coding |
| Post approved bills | Approved bills with posting deadlines | Post to a period | Bookkeeper, controller | 1a | Exists: executing `bill.approve` posts. Build: a separate posting act that binds its own period and entry; the executor is never the approver |
| Payables and outside payments | All bills, AP aging, "Don't pay yet" flags, payments made outside Cipher | Record payment, Import check register, Confirm against the bank, Export | Bookkeeper, controller, owner | 1b | Exists: AP aging. Build: outside payment record and posting, CSV import, confirmation, double-recording guard |
| Reports | Job cost, AP aging, audit export | Export to Excel, Print | Bookkeeper, controller, owner | 1a (job cost), 1b | Exists: AP aging, audit export. Build: report reads, Excel writer |
| Accountant package | Journals, trial balance, AP aging, outside payments, changes since the last package; omissions check | Prepare, Record receipt | Controller | 1b | Exists: `handoff`. Build: download; outside payments in the omissions check |
| Vendors and vendor record | Directory; compliance, waivers, bank details, contacts, bills, payments | New vendor, Ask for documents, Change bank details | Bookkeeper, controller | 1b | Exists: parties, destinations, certificates. Build: number, address, encrypted tax ID, W-9 and 1099 flags, vendor type, governed contact numbers, waiver records |
| Bank detail change | Request, call-back with read-back check, approval, waiting period | Record call-back, Approve change | Bookkeeper, controller | 1b | Exists: request, evidence, approval, cooling-off. Build: read-back compare, contact number history, structured call-back record, encrypted storage |
| Documents and history | Revisions, certificates, waivers, photos; decisions as sentences | Upload, Add revision, Download history | All | 1a (practice disk), 1b (Blob) | Exists: hashed revisions, audit chain. Build: Blob storage, malware scan, framed viewer, history index, sealed-copy check |
| Notes | Notes and @mentions on any record | Add note | All | 1b | Build: notes store in the app-state database |
| Exceptions | Failed emails, scans and scheduled checks, each with an owner | The one allowed action | Bookkeeper, controller, owner | 1b | Build: exceptions list fed by the worker |
| Settings | People and duties, who can do each step, approval policy, cost codes, chart of accounts, numbering, compliance requirements | Ask {owner} to add this duty, Prepare policy change | Owner, controller | 1a (people), 1b | Exists: `people` (untracked), `payment_policy`. Build: account binding screens, co-sign flows, per-operation expiry, limits, masters |
| Restored copy and recovery | Make this the live copy; recovery checklist | Make this the live copy | Owner, controller | 1b | Exists: `claim_write_authority`, `complete_recovery_reconciliation`. Build: Key Vault claim flow, high-water mark, checklist |
| Help and glossary | Page help, glossary built from `terms.ts`, link to the practice copy | | All | 1b | None |
| Practice tools | Sample project, payment simulator, event replay | Load practice project | Practice copies | 1a | Exists: `run_demo`, simulator. Build: `workspace.mode`, practice-only routes |
| Payments home and payment run | Ready, not ready, on hold, waiting, returned; line drawers | Release, Hold | Releaser | 2 | Exists: intents, outbox, reconcile, cooling-off, co-sign. Build: runs table, worker, preparer can't release |
| Release dialog | Restated facts, fresh sign-in | Sign in and release | Releaser | 2 | Exists: `record_step_up`, one approval per step-up. Build: Entra step-up in a popup, one step-up for listed ordinary lines |
| Stop all payments | Kill switch with a reason | Stop, Restart (approval) | Owner, releaser | 2 | Exists in the domain with no role check. Build: role check, HTTP action |
| Co-sign | Second signature on large payments and loosened policies | Co-sign | An independent person | 2 | Exists: co-sign in `payment_policy`. Build: inbox item type |
| Payment exceptions | Unknown outcomes past the time limit, returns, held recoveries | The one allowed action | Releaser, owner | 2 | Build: payment exceptions |
| Prime contract and owner pay app grid | Contract terms; G703, C-620 or unit-price estimate | Send for approval, Send to the engineer | PM, bookkeeper | 2 | Exists: `set_prime_contract` (not on HTTP). Build: owner SOV and bid items, print templates |
| Receivables | Owner pay apps, payments received, deposits, AR aging | Record payment received | Bookkeeper, controller | 2 | Exists: AR, collections, deposits. Build: lists, forms |
| Bank reconciliation | Statement lines, cleared items, unmatched lines, adjustments | Match, Lock | Bookkeeper, controller | 2 | Exists: `banking`. Build: CSV, OFX and BAI2 parsing |
| General ledger and journal entries | Journals, trial balance, account activity; manual entries; reversals | Send for approval | Controller | 2 | Exists in the domain, not on HTTP. Build: manual entry workflow, reversals |
| Month-end close | Checklist by area with sign-offs | Close period | Controller | 2 | Exists: `close.checklist`. Build: presenters, sign-offs |
| WIP schedule | Cost-to-cost percent complete, earned revenue, over and under billing, WIP entry | Prepare WIP adjustment | Controller, owner | 2 | Exists: `close.wip`. Build: report |
| Retainage, and lien waivers as a payment gate | Payable and receivable retainage, release; waivers hold release | Ask for release, Ask for waiver | Bookkeeper, PM | 2 | Exists: retainage release; waiver records from 1b. Build: the release gate |
| RFIs, submittals, closeout | Logs, responses, closeout requirements | New RFI, Respond, Accept closeout | PM, superintendent | 2 | Exists: `field`. Build: reads, outside sends |
| Daily reports (online) | Weather, crews, equipment hours, quantities, delays, photos | Review | PM, superintendent | 2 | Build: daily reports, quantities; extend the `field` role |
| Equipment, 1099 and W-9 | Assets, depreciation, equipment rates; year-end vendor reporting | Add equipment, Export | Controller | 2 | Exists: `asset`. Build: equipment rates charged to job cost, 1099 flags |
| Field mode | Today, daily report, crew time, quantities, T&M, photos, offline | Send for PM review | Superintendent | 3 | Build: offline queue, resumable uploads |
| Crew time and certified payroll | Crews by cost code, trade classification, wage rate, WH-347 | Approve, Print WH-347 | PM, payroll | 3 | Exists: labor module (design-firm style). Build: crews, classifications, prevailing wage |
| Estimating, schedule | Estimates bound to drawings; lookahead with dates | Compare revisions, Update | Estimator, PM | 3 | Exists: estimating, CPM in day numbers. Build: price book, calendar dates |
| Ricky chat | Questions about the page you're on, drafts | Use draft | All | 3 | Build: language model behind the read-and-draft-only surface |

### 6. Key screens in detail

The main job is **24-031 Lift Station 4 Cofferdam** for Ashford Municipal Water Authority in Pennsylvania: lump sum, AIA billing, 5% retainage held by Ashford. The main sub is **Northgate Piling Co.** (V-0142) on SC-03, sheet piling and walers, with 10% retainage. The other jobs are 25-007 Mill Creek WWTP Clarifier Rehab (Ohio, EJCDC forms), 25-012 Route 30 Pier 3 Cofferdam (West Virginia, unit price) and 25-019 Riverside Intake Dewatering (Michigan). {PM} runs 24-031 and 25-012; {PM 2} runs 25-007 and 25-019. Cost codes use MasterFormat 2016 numbers until S&A's own list is loaded.

The example policy: a PM approves sub pay apps up to $50,000.00 of work and stored materials in the period, and sub change orders up to $25,000.00. Supplier invoices under $5,000.00 that match within 2% or $100.00 are approved by the match. Payments of $25,000.00 or more are high risk (phase 2).

The day runs in this order: 8:45 am, {PM} opens My projects (6.1). 9:05, {PM} finishes the review of pay app #4 and sends it to {owner} (6.5). 9:06, {owner}'s Company page (6.14). 9:10, {owner} approves (6.6). 9:30, {bookkeeper}'s Books page (6.10). 1:15 pm, {bookkeeper} adds the signed delivery ticket. 2:30 pm, {PM} executes CO-03 (6.8). 2:35 pm, {PM} confirms the ticket. 2:40 pm, {owner} sees pay app #4 needing approval again (6.7).

#### 6.1 My projects ({PM}'s home), 8:45 am

There is no status sentence, because everything worth saying is already in the table.

**Waiting on you (5)**

| | Job | Amount | Waiting | Expires | |
|---|---|---|---|---|---|
| **Review sub pay apps (2)** | | | | | |
| Review pay app #4, Northgate Piling Co. | 24-031 | $54,652.50 | 5 days | Oct 18 | Over your limit |
| Review pay app #3, Crestline Excavating Inc. | 25-012 | $32,040.00 | 4 days | Oct 19 | |
| **Change orders (1)** | | | | | |
| Sign and execute SC-03 CO-03, Northgate Piling Co. | 24-031 | $9,800.00 | 1 day | Oct 19 | |
| **Change events to price (1)** | | | | | |
| Price CE-024, south cell well point spacing | 25-012 | | 2 days | | |
| **Forecasts (1)** | | | | | |
| Send the September forecast for 24-031 | 24-031 | | | Due Oct 20 | |

On review rows the amount is what the sub asked for.

**Tiles:** Pay apps to review 2 ($86,693 asked); Open change events 4 ($61,300 rough cost); Cost codes over budget 1 (31 23 19 Dewatering on 24-031, $7,400 over); Certificates expiring in 30 days 2.

**My projects**

| Project | Contract | Cost to date | Projected final cost | Projected margin | Over (under) budget |
|---|---|---|---|---|---|
| 24-031 Lift Station 4 Cofferdam | $2,480,000 | $1,045,880 | $2,133,900 | 14.0% | $5,900 |
| 25-012 Route 30 Pier 3 Cofferdam | $1,742,000 (unit price) | $356,210 | $1,536,500 | 11.8% | ($3,500) |

Phase 2 adds Billed to date and Billing position. Billing position is cost-to-cost: cost to date over projected final cost, times the contract, compared with gross billed.

**Change events not priced:** CE-024 on 25-012, south cell well point spacing, opened Oct 11. CE-023 on 24-031, extra trench box days, opened Oct 9.

**Pinned actions:** New change event, Budget transfer, New subcontract, Job cost report, Documents.

**Coming up:** Oct 19, tremie seal pour on 24-031. Oct 20, September forecast due for 24-031. Oct 30, Northgate's pay app #5 due.

#### 6.2 Job overview: 24-031 Lift Station 4 Cofferdam

**Header:** "24-031 Lift Station 4 Cofferdam", Active. "Ashford Municipal Water Authority, Pennsylvania. Lump-sum prime contract, AIA G702/G703, 5% retainage."

| Revenue | | Cost | |
|---|---|---|---|
| Contract, with 3 owner change orders | $2,480,000 | Revised budget | $2,128,000 |
| Pending: PCO-06, not yet approved by Ashford | $14,950 | Committed | $1,690,300 |
| Projected margin | $346,100 (14.0%) | Cost to date | $1,045,880 |
| | | Projected final cost | $2,133,900 |
| | | Projected over budget | $5,900 |

Pending changes are never counted in the contract. Phase 2 adds Billed to date, Retainage held by Ashford and Billing position to the revenue group.

**Needs attention on this job**
- Warning: "Dewatering is projected $7,400 over budget: pump rental ran 9 extra days during the high river stage." [Open forecast]
- Info: "CO-03 is signed by Northgate and ready to execute. Ashford hasn't approved PCO-06 yet." [Open CE-021]
- Warning: "Northgate's conditional waiver for pay app #4 hasn't arrived. Payment waits for it." [Ask Northgate for it]
- Info: "2 subs have insurance certificates expiring in the next 30 days." [View]

**Cost by month:** cost to date (navy) through September and the forecast (navy, dotted) to completion, against the revised budget (slate). [Show as table]. Phase 2 adds billed and earned revenue and an over or under billing label.

**This month:** "September pay app cycle: 3 sub pay apps in, 1 under review, 2 approved. 1 supplier invoice to match."

**Right column:** open items (2 change events, 1 supplier invoice to match); key dates entered on the job ("Excavate inside the cofferdam to elevation 812.0, Oct 12 to 16", "Tremie seal pour, Oct 19", "Cofferdam dewatered for structure work, Nov 2"); the team by name; recent activity ("{PM} executed SC-03 CO-02 for $12,200.00. Oct 2, 2026 at 11:20 am EDT.").

#### 6.3 Subcontract record: 24-031 SC-03

**Header:** "Subcontract SC-03 Sheet piling and walers", Executed. "Northgate Piling Co. on 24-031 Lift Station 4 Cofferdam. Executed Jun 19, 2026, and revised by CO-02 on Oct 2. Retainage 10% on work and stored materials, no step-down." Actions: [Enter pay app] (primary), [New change order], More (Close out subcontract, Print, Export to Excel).

| Original | Approved changes | Revised | Pending changes | Billed to date | Retainage held | Paid | Left to bill |
|---|---|---|---|---|---|---|---|
| $412,500.00 | $38,200.00 | $450,700.00 | $9,800.00 (1) | $245,250.00 (54.4%) | $24,525.00 | $220,725.00 | $205,450.00 |

Pending changes are never counted in Revised.

**Lifecycle rail:** Drafted by {PM}, Jun 8 → Approved by {owner}, Jun 12 → Signed by Northgate, Jun 16 → Signed for S&A by {owner}, Jun 18 → Executed, Jun 19 → Closeout accepted (later) → Retainage released (later).

**Message bar:** "Ready to pay: 7 of 8 requirements met. The conditional waiver for pay app #4 is missing." [Ask Northgate for it]

**Tabs:** Schedule of values, Change orders (3), Pay apps (4), Payments (3), Compliance (7 of 8), Documents (11), History.

**Schedule of values tab:** the same seven lines as the grid in 6.5 (five original lines, then CO-01 and CO-02 as their own lines), with columns Line, Description, Cost code, Scheduled value, Billed to date, %, Balance to finish and Retainage held, and a totals row of $450,700.00 scheduled, $245,250.00 billed, $205,450.00 to finish and $24,525.00 held. Line 1 is coded 01 71 13 Mobilization and every other line 31 41 16 Sheet piling. Line 3, "Drive sheet pile, cofferdam walls", stands at $27,250.00 of $142,500.00 (19.1%). Pending CO-03 appears only in the Change orders tab until it is executed.

**Side pane:** Approval ("Pay app #4 is under your review."); Bank details ("Pays to checking ending 4471, verified by call-back Sep 30."); Compliance (general liability current to Mar 1, 2027; auto, workers' comp, umbrella and W-9 on file; conditional waiver for pay app #4 missing); Notes (1): "{superintendent}: 18 pieces of W14 waler at the east laydown yard, counted Sep 27. @{PM}".

#### 6.4 Entering a sub pay app from the PDF

Northgate's pay app came into the AP mailbox on Oct 7 at 4:12 pm and showed up in Books > Incoming: "From Northgate Piling Co. Pay application 4, period to 9/30/26. 3 pages." Cipher suggests "Looks like a sub pay app for 24-031 SC-03." [Enter as sub pay app]

The entry screen is T6 in entry mode. On the left is Northgate's PDF in a framed viewer labeled "Northgate Piling Co.'s document. Not a Cipher record." On the right is the SC-03 grid with From previous filled in from pay app #3. {bookkeeper} types Sub claimed this period and Materials presently stored for each line, then two control totals from Northgate's G702: total completed and stored to date ($305,975.00) and current payment due ($54,652.50). Line 4's stored materials get delivery ticket 30418 and a photo, attached from the PDF's pages.

The check under the grid: "Your lines add up to $305,975.00, which matches line 4 of Northgate's G702. Current payment due matches too: $54,652.50." When they don't: "Your lines add up to $305,375.00. Northgate's G702 says $305,975.00, which is $600.00 more."

**Footer:** [Save draft] [Send to {PM} for review] (primary). Sending starts the 10-day decision window, so pay app #4 must be decided by Oct 18, and records {bookkeeper} as the person who entered it, which is what separation checks.

#### 6.5 Reviewing a sub pay app: SC-03 pay app #4, 9:02 am

**Context header:** "Pay app #4 from Northgate Piling Co. Period ending Sep 30, 2026." "24-031 SC-03. Entered by {bookkeeper} Oct 8 from Northgate's PDF." Status Under review. Marker "Review saved 9:02 am".

| Line | Description | Scheduled value | From previous | Sub claimed this period | Approved this period | Materials presently stored | Total completed and stored to date | % | Balance to finish | Retainage | Why it differs |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Mobilization | $28,000.00 | $28,000.00 | $0.00 | $0.00 | $0.00 | $28,000.00 | 100.0% | $0.00 | $2,800.00 | |
| 2 | Furnish PZ 27 sheet pile | $164,000.00 | $164,000.00 | $0.00 | $0.00 | $0.00 | $164,000.00 | 100.0% | $0.00 | $16,400.00 | |
| 3 | Drive sheet pile, cofferdam walls | $142,500.00 | $27,250.00 | $35,625.00 | **$28,500.00** | $0.00 | $55,750.00 | 39.1% | $86,750.00 | $5,575.00 | Field count Sep 29: 58 of 290 pairs driven since pay app #3, so 20%, not 25% |
| 4 | Walers and bracing, two levels | $58,000.00 | $0.00 | $6,600.00 | $6,600.00 | $12,400.00 | $19,000.00 | 32.8% | $39,000.00 | $1,900.00 | |
| 5 | Pull and salvage sheet pile | $20,000.00 | $0.00 | $0.00 | $0.00 | $0.00 | $0.00 | 0.0% | $20,000.00 | $0.00 | |
| CO-01 | Obstruction removal at line B | $26,000.00 | $26,000.00 | $0.00 | $0.00 | $0.00 | $26,000.00 | 100.0% | $0.00 | $2,600.00 | |
| CO-02 | Third bracing level, north wall | $12,200.00 | $0.00 | $6,100.00 | $6,100.00 | $0.00 | $6,100.00 | 50.0% | $6,100.00 | $610.00 | |
| **Totals** | | **$450,700.00** | **$245,250.00** | **$48,325.00** | **$41,200.00** | **$12,400.00** | **$298,850.00** | **66.3%** | **$151,850.00** | **$29,885.00** | |

Line 4's stored materials: "W14 waler steel, 18 pieces, at the east laydown yard. Delivery ticket 30418 and a photo dated Sep 27." Both open in the framed viewer. The line 3 reason prints in the pay app PDF's "Reasons for difference" table.

**Summary rail, in G702 order**

| Line | Amount |
|---|---|
| Original contract sum | $412,500.00 |
| Net change by change orders | $38,200.00 |
| Contract sum to date | $450,700.00 |
| Total completed and stored to date | $298,850.00 |
| Retainage, 10% of completed work ($286,450.00) | $28,645.00 |
| Retainage, 10% of stored materials ($12,400.00) | $1,240.00 |
| Total earned less retainage | $268,965.00 |
| Less previous certificates for payment | $220,725.00 |
| **Current payment due** | **$48,240.00** |
| Balance to finish, including retainage | $181,735.00 |

"Northgate asked for $54,652.50. Your review brings it to $48,240.00, which is $6,412.50 less."

**Checks.** Ricky's check: Looks right. Then: matches SC-03's schedule of values as revised by CO-02; no line is over its scheduled value; stored materials have a delivery ticket and a photo; no other September pay app from Northgate on SC-03; and a warning, "The conditional waiver for pay app #4 hasn't arrived. That holds payment, not approval."

**Above the footer:** "Over your $50,000.00 limit: Northgate claimed $60,725.00 of work and stored materials this period. {owner} approves this one."

**Footer:** [Send back to {bookkeeper}] [Save review] [Send to {owner} for approval] (primary). Send back has a checkbox, "Also email Northgate the reasons" (7.8). At 9:05 am {PM} sends it. Within the limit, as with Crestline's pay app #3 ($35,600.00 of work and stored materials this period), the primary button is [Approve $32,040.00], one server command that records the review and the approval together.

A field problem reads: "Line 4 is over its scheduled value. Walers and bracing has $39,000.00 left. Enter $39,000.00 or less, or start a change event. [Set to $39,000.00] [Start change event]". Approving more than the sub claimed on any line is allowed but goes to the next approver up: "Line 3 is now $1,000.00 more than Northgate claimed, so {owner} approves this one."

#### 6.6 Approval page: pay app #4, 9:08 am

{owner} opens it from the Company page. The URL is `/approvals/A-26-0418`; the number appears nowhere else except Technical details.

**Title:** "Approve pay app #4 from Northgate Piling Co."
**Subtitle:** "SC-03 Sheet piling and walers on 24-031 Lift Station 4 Cofferdam, for S&A Solutions LLC. Period ending Sep 30, 2026."
**Status:** "Waiting on you. Sent by {PM} at 9:05 am. Expires Oct 18."

**Summary** (written by the server): "Northgate Piling Co. is owed $48,240.00 for September work and stored materials, after $5,360.00 retainage."

| Fact | Value |
|---|---|
| Current payment due | $48,240.00 |
| This period | $41,200.00 of work and $12,400.00 of stored materials (W14 waler steel at the east laydown yard) |
| {PM}'s review | Line 3 cut from $35,625.00 to $28,500.00: the Sep 29 field count shows 20% driven, not 25% |
| Retainage | $5,360.00 at 10%; $29,885.00 held after this pay app |
| Against | SC-03 as revised by CO-02, $450,700.00. CO-03 isn't included |
| Charged to | 31 41 16 Sheet piling, subcontract cost. Planned for September 2026; {bookkeeper} confirms the period when posting |

**Checks.** Ricky's check: Looks right. Then the four passed checks and the waiver warning, exactly as in 6.5. Ricky adds a line here only when it finds something the rule checks don't.

**Collapsed sections**
- **Documents (4):** Northgate's pay app PDF; the G703 continuation sheet; delivery ticket 30418 with its photo; conditional waiver for pay app #4, **missing**.
- **Earlier pay apps on SC-03 (3):** #1 $25,200.00, paid Jul 21. #2 $133,695.00, paid Aug 20. #3 $61,830.00, paid Sep 18, unconditional waiver on file.
- **Accounting entry** (closed for business approvers; open by default in the Post dialog). Account numbers are today's built-in chart until the accountant's chart is loaded (decision 8).

| Account | Debit | Credit |
|---|---|---|
| 5000 Project cost, subcontract: 24-031, 31 41 16 | $41,200.00 | |
| 1300 Stored materials | $12,400.00 | |
| 2000 Accounts payable: Northgate Piling Co. | | $48,240.00 |
| 2050 Retainage payable | | $5,360.00 |
| **Total** | **$53,600.00** | **$53,600.00** |

- **Who does what:** Entered by {bookkeeper}, Oct 8 → Reviewed by {PM}, Oct 13 at 9:05 am → Approved (you are here) → Posted by {bookkeeper} or {controller} → Paid outside Cipher, only to checking ending 4471, verified by call-back Sep 30 → Confirmed against the bank by someone other than whoever recorded the payment. "Once you approve, it has to be posted by Nov 12." In phase 2 the last two steps become: added to a payment run → payment approved by {owner} ($25,000.00 or more) → released after a fresh sign-in → confirmed by the bank → matched to the bank statement.

**Above the footer:** "Approving doesn't post or pay anything. {bookkeeper} posts it next."

**Footer (pinned):** [Send back to {PM}] (reason required) [Approve $48,240.00] (primary). More: Reject (reason required), Forward, Download packet (PDF). The PDF prints the approval number, a short fingerprint, the status and the time of download on every page, with "Check Cipher for the current status", and is watermarked "Not approved" or "No longer valid" when that applies.

**At 9:10 am, after approving:** the toast reads "Pay app #4 is approved. {bookkeeper} posts it next." History gains "{owner} approved pay app #4 for $48,240.00, as reviewed by {PM}. Oct 13, 2026 at 9:10 am EDT." Clicks are ignored while the toast shows, then the next item opens with its footer briefly disabled: "Next: new subcontract SC-04 with Bluestone Dewatering LLC, $318,000.00".

#### 6.7 Needs approval again, 2:40 pm

At 1:15 pm the copy of delivery ticket 30418 signed on receipt by {superintendent} came into the AP mailbox. The copy attached to pay app #4 was unsigned. {bookkeeper} attached the signed copy as revision 2 of the ticket, and before the click the dialog said:

> Add revision 2 of delivery ticket 30418? This sends 1 approved item back for approval: pay app #4 from Northgate Piling Co., $48,240.00, approved by {owner} at 9:10 am. [Add revision] [Don't add]

New evidence for stored materials has to be confirmed by a person before anything bills against it, so {PM} got a to-do: "Confirm the signed ticket 30418 still shows 18 pieces of W14 waler." {PM} confirmed at 2:35 pm. Until then, {owner}'s Approve again button was disabled with "Waiting for {PM} to confirm the signed ticket."

What {owner} sees at 2:40 pm:

- **List:** the item is under "Needs approval again (1)". When one change affects several items they are grouped: "Delivery ticket 30418 changed, so 1 item needs approval again."
- **Message bar:** "Delivery ticket 30418 was replaced with a signed copy at 1:15 pm. The amount due is the same. Approve it again to keep it moving."

| Fact | When you approved | Now | Changed by | When |
|---|---|---|---|---|
| Delivery ticket 30418 | Unsigned copy | Copy signed on receipt by {superintendent} | {bookkeeper}, from the AP mailbox | Oct 13, 1:15 pm |
| Stored materials, line 4 | 18 pieces of W14 waler, $12,400.00 | The same, checked against the signed copy | {PM} | Oct 13, 2:35 pm |
| Current payment due | $48,240.00 | $48,240.00, no change | | |

- **Unchanged** (collapsed, with Show): payee, every line amount, retainage at 10%, SC-03 as revised by CO-02, planned period September 2026.
- **History:** the old approval is struck through: "Approved Oct 13 at 9:10 am. No longer valid: delivery ticket 30418 was replaced."
- **Books:** Post is disabled with "The delivery ticket changed after {owner} approved this. It needs approval again before it can be posted."
- **Footer:** [Send back to {PM}] [Approve again: $48,240.00]. Nothing is approved again automatically.

**What didn't send it back.** At 2:30 pm {PM} executed CO-03 (6.8). Pay app #4 covers September and bills only lines CO-03 leaves alone, so its approval stood, and the execute dialog said so before the click. If a change order did change a line that a draft pay app bills, the server would re-check the pay app against the revised subcontract and show "Revision 2, checked against SC-03 as revised by CO-03 at 2:31 pm. No amounts changed." above Approve again (7.5).

#### 6.8 Change event CE-021 and change order CO-03

**Header:** "Change event CE-021 North wall extension", Priced. "24-031. Opened by {PM} Sep 29: the north wall needs 12 more pairs of PZ 27 to tie into the existing headwall."

| Cost side | | Revenue side | |
|---|---|---|---|
| SC-03 CO-03, Northgate Piling Co. | $9,800.00 | PCO-06 to Ashford, with 15% markup | $14,950.00 |
| S&A crew and 90-ton crane, 2 days | $3,200.00 | Status | Sent to Ashford's engineer Oct 6, not approved |
| Total cost | $13,000.00 | Margin on the change | $1,950.00 |

| Line | Cost code | Cost type | Amount | Becomes |
|---|---|---|---|---|
| 1 | 31 41 16 Sheet piling | Subcontract | $9,800.00 | SC-03 CO-03 |
| 2 | 31 41 16 Sheet piling | Labor and equipment | $3,200.00 | A budget revision when Ashford approves PCO-06 |

**Lifecycle rail:** Opened by {PM}, Sep 29 → Priced by {PM}, Oct 2 → PCO-06 sent to Ashford's engineer, Oct 6 → Approved by Ashford (waiting) → Owner CO #4, raising the contract to $2,494,950 → Closed when both sides are executed.

**Message bar:** "Ashford hasn't approved PCO-06. If you execute CO-03 now, S&A carries $9,800.00 until they do."

**CO-03** has its own record. Its rail: Drafted and approved by {PM}, within the PM limit, Oct 12 → Signed by Northgate, Oct 12 (the signed copy came in through Incoming) → Signed for S&A and executed (waiting on {PM}) → First billed on pay app #5.

**Sign and execute dialog, 2:30 pm:** "Sign and execute CO-03 for $9,800.00?"
- SC-03 goes from $450,700.00 to $460,500.00.
- This uses the copy Northgate signed on Oct 12.
- Pay app #4 isn't affected. CO-03 first appears on pay app #5.
- Ashford hasn't approved PCO-06.

[Sign and execute] [Not now] (has focus). History: "{PM} signed and executed SC-03 CO-03 for $9,800.00, within the PM limit. Oct 13, 2026 at 2:30 pm EDT." {owner} sees it on the Company page under "Approved within PM limits".

#### 6.9 Forecast for September 2026: 24-031

A T6 grid with cost to date through Sep 30 and commitments as of Oct 13 at 8:00 am. {PM} enters cost to complete, and Cipher works out projected final cost and over (under) budget. Figures are whole dollars.

| Cost code | Budget | Committed | Cost to date | Cost to complete | Projected final | Over (under) | Reason |
|---|---|---|---|---|---|---|---|
| 01 50 00 General conditions | $286,000 | $162,400 | $181,300 | $104,700 | $286,000 | $0 | |
| 31 41 16 Sheet piling and walers | $642,000 | $612,900 | $438,450 | $202,050 | $640,500 | ($1,500) | |
| 31 23 19 Dewatering | $214,000 | $146,000 | $162,400 | $59,000 | $221,400 | $7,400 | Pump rental ran 9 extra days during the high river stage |
| 31 23 16 Excavation inside the cofferdam | $318,000 | $286,000 | $161,730 | $156,270 | $318,000 | $0 | |
| 03 30 00 Cast-in-place concrete (tremie seal) | $402,000 | $395,000 | $62,000 | $340,000 | $402,000 | $0 | |
| 31 25 00 Erosion and sediment control | $96,000 | $88,000 | $40,000 | $56,000 | $96,000 | $0 | |
| Contingency | $170,000 | $0 | $0 | $170,000 | $170,000 | $0 | |
| **Total** | **$2,128,000** | **$1,690,300** | **$1,045,880** | **$1,088,020** | **$2,133,900** | **$5,900** | |

**Summary above the grid:** "Projected final cost $2,133,900, which is $5,900 over the $2,128,000 budget. Projected margin 14.0%, down from 14.2% in August."

A reason is required when a line ends up over budget, or its projected final cost has moved since last month, by $5,000 or 5% of its budget, whichever is less. Dewatering needs one; sheet piling's $1,500 doesn't. Labor and equipment in cost to date come from the monthly cost import (11.3), so general conditions and S&A's own crew costs aren't blank.

**Footer:** [Save draft] [Send forecast to {owner}] (primary). {owner} approves it like any other item, and the approved forecast becomes the September snapshot (in phase 2 it feeds the WIP schedule).

#### 6.10 Books home and posting a bill, 9:30 am

This is {bookkeeper}'s view. The page header reads "Books" with a "Working ledger" label, whose popover says "Working ledger. Statements still come from the outside accountant until we switch over." There is no strip.

**Waiting on you (4)**

| | Job | Amount | Waiting | Expires | |
|---|---|---|---|---|---|
| Post 4 approved bills | Several | $63,015.50 | | First deadline Nov 8 | |
| Enter 3 documents from Incoming | | | 1 day | | |
| Record the Oct 12 check run, 5 checks | Several | $38,915.40 | 1 day | | |
| Check a possible duplicate: Granite Aggregate Supply invoice 7710 | 25-007 | $2,184.60 | 1 day | | Looks like 7701 |

The duplicate row explains itself when opened: "Invoice 7710 for $2,184.60 looks like invoice 7701 for $2,184.60, posted Sep 22."

{controller}'s view of the same page adds: "Call back Granite Aggregate Supply about new bank details" (requested by {bookkeeper}, who therefore can't make the call); "Review {owner}'s own approval: 25-019 SC-02 CO-01, $6,500.00", entered and approved by {owner} on Oct 9 while {PM 2} was out, due Oct 16; and "Prepare the September accountant package", due Oct 15.

**Tiles:** Bills to post 4 ($63,016); Documents in Incoming 3; Tie-outs off 1 ($450); Due to vendors in 14 days $286,410 (11 bills).

**Ties to the general ledger:** "Vendor balances match the AP account: both $412,880.55." "Retainage payable is $450.00 off. The subcontract ledgers show $118,604.00 and the account shows $118,154.00. [See the difference]"

**Accountant package for September:** "4 of 6 parts ready. Due Oct 15." [Open]

**Pinned actions:** Incoming, Enter sub pay app, Enter supplier invoice, Record outside payments, Post approved bills, AP aging.

**Coming up:** Oct 15, September accountant package due. Nov 8, first posting deadline (Summit Traffic Control pay app #4).

**Post approved bills**

| Bill | Job | Approved by | Amount | Planned period | Post by |
|---|---|---|---|---|---|
| Pay app #4, Northgate Piling Co. | 24-031 SC-03 | {owner}, Oct 13 at 9:10 am | $48,240.00 | September 2026 | Nov 12 |
| Invoice 88530, Keel Ready-Mix | 25-007 PO-06 | {PM 2}, Oct 12 | $6,214.80 | September 2026 | Nov 11 |
| Pay app #4, Summit Traffic Control | 25-012 SC-02 | {PM}, Oct 9 | $4,600.70 | September 2026 | Nov 8 |
| Invoice 5604, Kestrel Pump Rental | 25-019 PO-03 | The match, within tolerance, Oct 12 | $3,960.00 | September 2026 | Nov 11 |
| **Total** | | | **$63,015.50** | | |

**Post dialog, first row:** "Post pay app #4 for $48,240.00?"
- Period: (•) September 2026, open, the period the work was done and the one {owner} saw as planned. ( ) October 2026, reason required.
- Coding, locked since the pay app was sent for approval: 31 41 16 Sheet piling, subcontract cost, account 5000 Project cost, subcontract. Pay app lines take their codes from the schedule of values. A coding change sends the item back for approval, with the old and new codes in What changed.
- The accounting entry from 6.6, open.
- [Post to September 2026] [Don't post] (has focus).

The posting rule, its version and who approved it sit under Technical details. If {bookkeeper} picks October, the entry is shown again with October's dates, and the posting record keeps its own period and reason; the business approval doesn't change. Messages that block: "September 2026 is locked. Post to October 2026 with a reason, or ask {controller} to reopen September." and "You approved this pay app, so someone else has to post it."

**Two entries when stored materials are installed.** Pay app #5 will install the 18 pieces of waler steel billed as stored on pay app #4. Its approval page and Post dialog split the period into "New work", "Installed from materials already billed as stored" and "Newly stored", and show two entries. The first moves $12,400.00 from 1300 Stored materials to 5000 Project cost, subcontract. The second records only new work and newly stored materials against accounts payable and retainage. Nothing is counted twice.

#### 6.11 Recording payments made outside Cipher

During phase 1, S&A pays through its current process. Cipher still has to know about each payment, or every posted bill stays "Posted, not paid" and AP aging, the tie-outs and the accountant package are all wrong.

**Record a payment** is a T7 side panel, opened from Payables or from a bill: "Record a payment for invoice 88412 from Keel Ready-Mix?"

| Field | Example |
|---|---|
| Bills | Invoice 88412, $9,322.20 (one or more open, posted bills from the same vendor) |
| Paid on | Oct 12, 2026 |
| Method | Check |
| Check number or ACH reference | 10452 |
| Paid from | Operating account ending 5521 |
| Amount | $9,322.20 |
| Paid to | Mailed to the remit address on file. For ACH, prefilled with the verified account: "checking ending 7714, verified Jun 12" |

- Recording posts the entry (debit 2000 Accounts payable, credit 1000 Operating bank) through the same posting check as a bill: only someone with the posting duty can do it.
- The amount can't exceed the bill's open balance, and retainage stays open.
- A bill can't be recorded as paid twice. The same bill and reference is refused, and so is any amount beyond the open balance: "Invoice 88412 was already recorded as paid by check 10452 on Oct 12."
- An ACH payment to an account other than the verified one is refused: "That isn't Keel Ready-Mix's verified account. Pay only to verified bank details, or start a bank detail change."
- The bill then shows "Paid outside Cipher, check 10452, Oct 12".
- Someone other than the recorder confirms each payment against the bank (online banking or the statement): "Confirmed against the bank by {controller}, Oct 14." A payment still unconfirmed after 7 days goes on {controller}'s Books page and is flagged in the accountant package.

**Import check register (CSV)** handles a whole run. Columns: date, check number, payee, amount, memo. Cipher proposes a match for each row against open posted bills by payee and amount and shows three groups: matched, not matched and already recorded. For the Oct 12 run: "5 checks, $38,915.40. 4 matched to open bills. Check 10454 for $2,310.00 to Tri-County Trucking matches no open bill." Nothing posts until {bookkeeper} records the matched rows.

In phase 1 the bill's lifecycle rail ends Posted → Paid outside Cipher → Confirmed against the bank. In phase 2 this panel stays for hand-written checks, and ACH moves to Payments.

#### 6.12 Supplier invoice with match: Keel Ready-Mix invoice 88530

**Header:** "Invoice 88530 from Keel Ready-Mix", Matched, approved, not posted. "25-007 PO-06, 4,000 psi concrete for clarifier wall repairs. Came in through Incoming on Oct 1." Key facts: $6,214.80; dated Sep 30, 2026; Net 30; due Oct 30, 2026; approved by {PM 2} Oct 12.

| | PO-06 line 1 | Delivery tickets 30511 to 30514 | Invoice 88530 |
|---|---|---|---|
| Item | 4,000 psi concrete | 4,000 psi concrete | 4,000 psi concrete |
| Quantity | 140 CY ordered; 80 CY open before this invoice | 4 loads of 10 CY on Sep 24 and 25, received by {superintendent}, 4 photos | 40 CY |
| Unit price | $155.37 | | $155.37 |
| Sales tax | | | None charged; the exemption certificate for Mill Creek WWTP is on file |
| Amount | | | $6,214.80 |

- "Matches PO-06 and the 4 delivery tickets. 40 CY stay open on the PO after this invoice."
- "No other Keel Ready-Mix invoice numbered 88530, or for $6,214.80, in the last 12 months."
- Tolerance (decision 9): within 2% or $100.00. It went to {PM 2} only because it is over $5,000.00.
- **Coding**, locked once sent for approval: 25-007, 03 30 00 Cast-in-place concrete, cost type Material, account Project cost, materials (the number comes from the accountant's chart; today's built-in chart has no materials account), $6,214.80.
- The right side shows the supplier's PDF in the framed viewer. More: Reject invoice, Mark as duplicate (both only before posting).

**Invoices with no PO.** Rentals and trucking often arrive without one. {bookkeeper} codes them to job, cost code and cost type, and the PM confirms receipt: "Confirm Tri-County Trucking ticket 7718: 14 loads of #57 stone delivered Oct 6 to 25-019." That confirmation is the approval.

Bills and purchase orders are where double payments and AP fraud happen, so this screen matters more than any dashboard.

#### 6.13 Bank detail change: Granite Aggregate Supply

**Header:** "Bank detail change for V-0217 Granite Aggregate Supply", Waiting for call-back.
- On file: checking ending 3390, verified Mar 3, 2026 by call-back.
- Requested: checking ending 8814, entered by {bookkeeper} Oct 12 from an email dated Oct 12 that claimed to come from Granite's billing contact.

**Steps**
1. Requested by {bookkeeper}, Oct 12. Done.
2. Call back on the number on file, by someone other than the requester. "Call 330-555-0142, on file since Mar 3, 2026. Don't use any number in the email." [Record call-back] captures who answered (name and title), the number dialed (filled in, not editable), the date and time, and the routing and account numbers Granite reads back. The person calling types those numbers without seeing the requested ones, and Cipher compares them. A mismatch stops the change: "The numbers Granite read back don't match the request. The change is stopped. Tell {owner}."
3. Approve the change: {controller}, who can verify bank changes, and never the requester.
4. Waiting period: payments to the new account wait 3 days after approval.

**Rules around the call-back**
- Changes to a vendor's phone numbers keep a history. Cipher won't accept a call-back to a number changed in the last 30 days, or changed by the person who asked for the bank change: "This number was changed Oct 10 by {bookkeeper}. Call the number from before that change, or ask {owner}."
- The person verifying is always whoever is signed in, never picked from a list.
- Full account and routing numbers are typed once. After that Cipher shows only "ending 8814", never in notifications, the morning email, History or exports.
- A new vendor's first bank details start as "Not verified. Payments can't go to this account until someone other than the requester calls back." and go through steps 2 to 4.

**Effect note.** Phase 1: "Payables will show 'Don't pay to ending 8814 before Oct 16' if this is approved today. No approvals are affected." Bill approvals no longer bind bank details (7.5), so a bank change doesn't send PMs' approvals back. Phase 2: the note lists every payment approval the change sends back, with counts and amounts, before {controller} approves.

{bookkeeper} sees this at step 2, because it blocks them: "You asked for this bank change, so someone else has to call Granite back."

#### 6.14 Company home ({owner}), 9:06 am

**Tabs:** Company, My projects, Books. No status sentence.

**Waiting on you (4)**

| | Job | Amount | Waiting | Expires | |
|---|---|---|---|---|---|
| Approve pay app #4, Northgate Piling Co. | 24-031 | $48,240.00 | 1 min | Oct 18 | |
| Approve new subcontract SC-04, Bluestone Dewatering LLC | 25-007 | $318,000.00 | 4 days | Oct 23 | |
| Approve the September forecast for 25-007 | 25-007 | | 1 day | Oct 19 | Margin down 2.7 points |
| Approve again: 25-012 SC-01 CO-02, Crestline Excavating Inc. | 25-012 | $29,150.00 | 2 hours | Oct 23 | Amount changed |

The CO-02 row opens to its reason: "Crestline's revised proposal raised it from $27,400.00 to $29,150.00 after you approved it."

**Tiles:** Due to vendors in the next 14 days $286,410; Bills waiting to post 3 ($14,776); Pay apps waiting on PMs 3 ($58,710); Projects projected over budget 2.

**Projects at a glance**

| Project | Contract | Cost to date | Projected final cost | Projected margin | Over (under) budget |
|---|---|---|---|---|---|
| 24-031 Lift Station 4 Cofferdam, PA | $2,480,000 | $1,045,880 | $2,133,900 | 14.0% | $5,900 |
| 25-007 Mill Creek WWTP Clarifier Rehab, OH | $6,915,400 | $1,912,450 | $6,265,000 | 9.4% proposed (12.1% in August) | $163,000 |
| 25-012 Route 30 Pier 3 Cofferdam, WV | $1,742,000 | $356,210 | $1,536,500 | 11.8% | ($3,500) |
| 25-019 Riverside Intake Dewatering, MI | $865,250 | $244,600 | $707,000 | 18.3% | ($5,000) |

**Approved within PM limits, last 7 days:** SC-03 CO-03, Northgate Piling Co., $9,800.00, {PM}, Oct 12. 25-019 budget transfer, $4,000 from contingency to 31 23 19 Dewatering, {PM 2}, Oct 8.

**Pinned actions:** New job, Projects, Job cost report, AP aging, Settings > People.

**Coming up:** Oct 15, September accountant package due. Oct 16, {controller}'s review of your Oct 9 approval due. Oct 20, PM forecasts due. Oct 23, the SC-04 approval expires.

Phase 2 adds high-risk payments to the table, a cash tile from the reconciled bank balance, and billed-to-date and billing position columns.

#### 6.15 Settings > People

**People:** name, duties in words, Microsoft 365 accounts and last sign-in. For example: "{owner}. Owner: every duty. 2 accounts (main and admin). Today, 8:58 am." Duties read as abilities: "Approves sub pay apps up to $50,000.00 on 24-031 and 25-012", "Posts bills", "Verifies bank changes".

**Adding a duty** starts with [Ask {owner} to add this duty]. The request reads "Let {bookkeeper} verify bank changes? Waiting for {owner}." Duties to release payments, verify bank changes or act as controller or owner, and every new Microsoft 365 account binding, also need {controller}'s co-signature, and everyone who holds a payment duty is told.

**Account bindings:** account, person, who approved it and when.

**Who can do each step** is generated from today's people and policy:

| Step | Who can do it today | Rule |
|---|---|---|
| Enter sub pay apps and invoices | {bookkeeper}, {owner} | |
| Approve sub pay apps up to $50,000.00 | {PM} on 24-031 and 25-012; {PM 2} on 25-007 and 25-019; {owner} | Not the person who entered it |
| Approve sub pay apps over $50,000.00 | {owner} | |
| Post bills | {bookkeeper}, {controller} | Not the approver |
| Record outside payments | {bookkeeper}, {controller} | |
| Confirm outside payments | {controller}, {owner} | Not the person who recorded it |
| Verify bank changes | {controller}, {owner} | Not the person who asked for the change |
| Release payments (phase 2) | Nobody yet | |

A warning appears under the table for each gap: "Only {owner} can approve pay apps over $50,000.00. While {owner} is out, they wait." In phase 2: "With today's people, nobody can release payments." and "Only a PM could co-sign payments of $100,000.00 or more, because {bookkeeper}, {owner} and {controller} already handle them."

**Policy changes** show their effect before anyone approves: "This raises the PM limit for sub pay apps from $50,000.00 to $75,000.00. {controller} must co-sign before it takes effect. Adopting it sends 3 open approvals back for approval." The co-sign request lands in {controller}'s Approvals.

#### 6.16 Other phase 1 screens in brief

- **Incoming (Books):** one row per PDF forwarded to the AP mailbox through Microsoft Graph, or dropped in. Columns: from, received, subject, a first-page preview and Cipher's guess ("Looks like a sub pay app from Northgate"). Actions: [Enter as sub pay app], [Enter as supplier invoice], [Attach to a record], [Not a bill]. Replies to Cipher's own requests land here already linked: "Reply to: request for the conditional waiver for pay app #4."
- **Projects list:** Job, Name, Client, State, PM, Contract, Projected margin, Status, with saved views (Active, Closing out, Closed) and Export to Excel.
- **Set up subcontract (T7 checklist):** vendor and scope; schedule of values with cost codes; retainage and terms; insurance and W-9; signed agreement; review. Steps in any order, then [Send to {owner} for approval].
- **Vendor record:** "V-0142 Northgate Piling Co.", subcontractor. Key facts: open balance, retainage held, paid this year, 1099 flag. Tabs: Compliance (certificates and waivers), Bank details, Contacts (with number history), Bills, Payments, Documents, History.
- **Accountant package (T8):** journals, trial balance, AP aging, outside payments, retainage, and what changed since the last package. The omissions check reads like this: "2 outside payments aren't confirmed yet. Confirm them, or list them as unconfirmed in the package." Actions: [Prepare package] and, after the outside accountant has it, [Record receipt].
- **Exceptions (Books):** what happened, who owns it, how old it is, and the one allowed action. Phase 1 kinds: an email or the morning email didn't send, a file didn't pass the malware scan, the history check found a mismatch, a scheduled check didn't run.
- **Make this the live copy and the recovery checklist:** 7.10.

### 7. The approval experience

#### 7.1 What an approval is

An approval binds exact facts. The server builds a manifest (operation, record versions, document hashes, amounts, payee, policy version, expiry), and the approval holds only while those facts still match. This is built and tested in `core/approvals.py`. Plan section 6 requires that "the interface shows those exact facts and the effects to the human".

So the screen never writes its own summary. For each operation a server-side presenter turns the manifest into labeled facts, a one-sentence summary, the accounting entry and, when stale, a What changed table. The browser only formats money and dates. Three rules make "what you saw is what you approved" hold:

- The presenter rebuilds the manifest when it renders the page, and flags any difference before Approve is shown.
- Approve sends a fingerprint of the manifest the person saw (If-Match). The server rebuilds the manifest at grant and refuses with a typed 412 if anything differs. The item moves to Needs approval again with its What changed table.
- Presenters fail closed. The server refuses to request or grant any operation that lacks a registered presenter and a passing page-to-manifest contract test. Every manifest key maps to a labeled fact or to a reviewed list of technical-only keys. An unmapped key disables Approve: "Cipher can't show everything this approval covers yet, so it can't be approved here. Ask {controller}."

#### 7.2 Who approves what

These are recommended defaults. The owner decides them (A6, decisions 3, 4, 6 and 9), and they live in the versioned approval policy. Today any PM can approve any amount.

| Item | Prepared by | Business approval | Then |
|---|---|---|---|
| Sub pay app | {bookkeeper} enters it; the PM reviews | The PM when work and stored materials this period are $50,000.00 or less; the owner above that | {bookkeeper} or {controller} posts it, never the approver |
| Supplier invoice with a PO | {bookkeeper} | The match, when under $5,000.00 and within 2% or $100.00; otherwise the PM | Same as above |
| Supplier invoice without a PO | {bookkeeper} codes it | The PM, by confirming receipt | Same as above |
| Sub change order | The PM drafts it | The PM within $25,000.00, drafting and approving in one act; the owner above that | The sub signs; S&A signs (the PM within the limit, the owner above); executing raises the subcontract |
| Owner change order | The PM, from a change event | The owner | Changes the contract value |
| New subcontract | The PM or {bookkeeper} | The owner | The sub signs, the owner signs, then it is executed |
| Budget transfer | The PM | The PM within the job's contingency, in one act; {controller} or the owner otherwise | Applies on approval |
| Monthly forecast | The PM | The owner | Becomes the month's snapshot |
| Payment made outside Cipher | {bookkeeper} records it | None; the posting check applies | Someone else confirms it against the bank |
| Bank detail change | {bookkeeper} | {controller}, never the requester | 3-day waiting period |
| Duty grant or account binding | The owner or {controller} | The owner, co-signed by {controller} for payment, bank-change and controller duties | Applies on approval |
| Payment policy change | {controller} or the owner | The owner, co-signed by the other when it loosens a control | Sends open approvals back |
| Owner pay app (phase 2) | The PM | {bookkeeper} or {controller} | Sending it to the engineer is a separate approval |
| Period close or reopen, reversal (phase 2) | {controller} | {controller} | Applies on approval |
| Payment (phase 2) | {bookkeeper} schedules it | Ordinary: the releaser approves and releases in one act. High risk: the owner approves first | The releaser signs in again |

- **Which amount the limit is tested on:** the larger of what the sub claimed and what is being approved, both measured as work and stored materials in the period, before retainage. A PM's own cuts never decide whether the owner sees an item, and the approval page prints the basis ("Over your $50,000.00 limit: Northgate claimed $60,725.00 of work and stored materials this period").
- Approving more than the sub claimed on any line needs the next approver up.
- Drafting and approving in one act is allowed only for sub change orders and budget transfers within PM limits (decision 4). It shows as "Entered and approved by {PM}, within the PM limit", and the owner sees these on the Company page for 7 days. Everything else needs a second person.
- A PM who reviews a pay app over their limit doesn't approve it; their review is recorded and shown on the owner's approval page.

#### 7.3 Deciding

- **Approve:** no "Are you sure?", because the page is the review. The toast says what happens next and History gains a sentence.
- **Send back** returns the item to the person before you in the chain as "Revise and resubmit", with your reason and a to-do. **Reject** asks "Reject pay app #4?" with a required reason the preparer sees. There is no stock reason like the old console's "rejected in console".
- **Withdraw:** whoever sent an item can pull it back, with a reason, until someone decides.
- **Forward** and **Out of office** are described in T5.
- **Separation rules are stated before the click, and only to the person they block:** "You entered this pay app, so someone else has to approve it." "You approved this pay app, so someone else has to post it." "You asked for this bank change, so someone else has to call Granite back."
- **Batch approval** applies to timecards only (phase 3). Everything involving money, or going outside the company, is decided one item at a time.

#### 7.4 Expiry

Today every approval expires 24 hours after it is requested, whether it's still waiting or already approved (`DEFAULT_EXPIRY_SECONDS` in `core/approvals.py`). A pay app entered on a Friday afternoon would expire on Saturday, and a weekly outside accountant would only ever see expired items. Expiry has to become a per-operation policy before the inbox ships (11.3 covers how).

| Operation | Time to decide | After approval, time to apply |
|---|---|---|
| Sub pay app, supplier invoice | 10 days from entry, covering review and approval | 30 days to post, never across a period lock without a reason |
| Change order, budget transfer | 10 days | 7 days to sign and execute, or to apply |
| New subcontract | 14 days | 14 days to collect the signatures |
| Forecast, bank detail change, duty grant | 7 days | Applies at once |
| Owner pay app (phase 2) | 5 days | 7 days to send |
| Payment approval (phase 2) | 3 days | Until the run date plus 1 day |
| Period close or reopen, reversal (phase 2) | 3 days | 1 day |

Every queue row and approval page shows the expiry. On the last day it turns into a warning ("Expires today at 4:00 pm"), and the bell and the morning email warn the day before. An expired item moves to Done as "Approval expired", with [Ask again] for the requester.

#### 7.5 When an approval goes stale

**Triggers:** a bound fact changes. That covers an amount or quantity, the lines a pay app bills, a document revision, the payee, the policy version, a period lock, the approver losing authority, and the expiry.

**What each approval binds.** A pay app binds the lines it bills and the subcontract as of its period, not the whole subcontract, so a change order that adds a line doesn't send last month's pay app back. A bill approval binds the payee's identity (vendor number, legal name, tax ID). The bank account is bound only by payment approvals and releases (phase 2), which is where plan section 6 puts it.

**What happens:** the server invalidates the approval and records a structured reason: field, old value, new value, the record that caused it, who and when. (Today the reason is a comma list such as `amounts,bindings`.) The record's marker becomes "Needs approval again", and the item lands in the approver's Needs approval again tab.

**What the approver sees** (6.7): one sentence of cause, 25 words at most; a What changed table; an Unchanged section collapsed under it; and "Approve again" with the amount. The old approval stays in History, struck through with its reason. Nothing is approved again automatically.

**When a change order touches billed lines,** the server re-checks the draft pay app against the revised subcontract. No amounts are typed; the re-check is credited to the system and the original preparer, and records a new revision: "Revision 2, checked against SC-03 as revised by CO-04. No amounts changed." If any line would have to change, the pay app goes back to {bookkeeper}.

**Grouping and downstream.** Items are grouped by cause, so one change that affects several items shows once. Post and Release stay visible but disabled, with the reason under them: "The delivery ticket changed after {owner} approved this. It needs approval again before it can be posted."

**Before the click.** The action that would cause a re-approval lists the affected items in its dialog (Effects before the click, section 4).

**Fatigue.** Every change to a bound fact sends the approval back and shows in What changed; there is no setting that hides "immaterial" changes, because that would quietly break plan section 6. Fatigue is handled by binding only what the approver actually decides (above), by grouping, and by warning before the action that would cause it. Changing what an operation binds is a versioned policy change, co-signed by {controller} when it weakens a control.

#### 7.6 Blocked actions explain themselves and route to the right person

- **Severity per requirement.** Each compliance requirement is set to block approval, block payment, or warn (decision 7). Today the contracts governor blocks approval and posting for every requirement, so this setting is backend work. Too many warnings teach people to ignore amber.
- **"Blocks payment" in phase 1** means Payables shows "Don't pay yet" with the reason, so whoever pays outside Cipher knows. In phase 2 the payment can't be released.
- **Shown early:** on the subcontract (message bar), on the approval page ("That holds payment, not approval"), in Payables, and as a PM to-do. Accounting should never find out on payment day.
- **Routed:** each blocker names the cause, the fix and who can act: [Ask Northgate for it], [Ask for an updated certificate], "Ask {controller}, who can reopen September".
- **Hidden or disabled:** hidden when you can never act, with the rail still saying who can ("Post: {bookkeeper} or {controller}"); disabled with a written reason when it could become possible. Permission messages speak to the person: "You can't post bills. Ask {bookkeeper}."

#### 7.7 Approve, post and release are separate

| Step | Where it happens | Who can't do it |
|---|---|---|
| Approve | The Approvals page, or the record's Approval panel | The person who entered it |
| Post | Books > Post approved bills | The approver; anyone without the posting duty |
| Record an outside payment | Payables | Anyone without the posting duty |
| Confirm an outside payment | Payables | The person who recorded it |
| Schedule (phase 2) | Payments | |
| Approve a high-risk payment (phase 2) | Approvals | The person who scheduled it |
| Release (phase 2) | Payments > Ready to release, only | The run's preparer; for high risk, also the payment approver. A co-signer must be a fourth person |

Today the backend doesn't separate these. Executing a `bill.approve` approval posts the bill. A PM holds the same authority used to post. The person requesting an approval chooses which role will execute it, and nothing stops an approver from executing their own approval. Section 11.2 fixes all of this before any screen depends on it, so the separation is a backend rule and not only a screen rule.

#### 7.8 Messages to vendors and the client

Every message that leaves S&A follows one pattern: [Ask Northgate for it], [Ask for an updated certificate], [Ask for new bank details], "Also email Northgate the reasons", and (phase 2) RFI answers and owner pay apps.

- It goes through Microsoft Graph from the shared AP mailbox, never from someone's own mailbox.
- The dialog shows the email as it will go (to, copy, subject, and a body from a template) and is a decision dialog: "Email Northgate about the missing waiver?" [Send email] [Don't send].
- The PM on the job is copied.
- Replies land in Books > Incoming, already linked to the request.
- History gets a sentence: "{bookkeeper} asked Northgate for the conditional waiver for pay app #4. Oct 13 at 9:41 am."
- A message never contains bank details, internal record IDs or links that do anything but open a page.

#### 7.9 Small-team rules

- **The solo-owner rule.** The owner may approve their own request when nobody else who could approve it is available (out of office, or nobody holds the authority), or with a written reason. The page shows who else could: "Others who could approve this: {PM}. To approve it yourself, say why." After that comes: "You're approving your own request. {controller} reviews it within 7 days." This is the documented owner and outside-accountant control the plan asks for, not a hidden administrator bypass.
- **What it never covers:** calling back on a bank change you asked for, releasing a payment you approved, co-signing, loosening the payment rules, and granting payment, bank-change or controller duties. Each limit is stated before the click: "You asked for this bank change, so {controller} has to make the call-back."
- **Reviews:** {controller}'s Books page lists them with due dates. An overdue review shows on the owner's Company page and (phase 2) fails the month-end close check.
- **Sensitive grants:** duties to release payments, verify bank changes, or act as controller or owner, and every new Microsoft 365 account binding, need the owner's approval and {controller}'s co-signature. Everyone with a payment duty is told.

#### 7.10 Restored copies

- The strip shows on every page. Every Approve, Post, Release and Edit button is disabled with "This is the Oct 9 backup. It's read-only until {owner} confirms it's the copy to keep." Pages stay readable.
- **[Make this the live copy]** opens "Make the Oct 9 backup the live copy? Anything approved, posted or sent after Oct 9 at 2:00 am isn't in it." {owner} signs in again with Microsoft 365, the server computes the claim code from the owner secret held in Key Vault and claims write authority, and {controller} is told and reviews it (decision 14). Buttons: [Make it the live copy] [Keep it read-only]. A restored copy can't be made live unless the owner secret is configured.
- **Recovery checklist (T8),** required before payments or outside email resume: approvals granted after the backup that this copy doesn't have, with their requesters told to ask again; documents and emails sent after the backup. In phase 2 it adds payments the bank shows after the backup, payments whose outcome is unknown, and transfers the bank holds that this copy never recorded, each adopted through its own approval.
- Until the checklist is done, payments and outside email stay paused: "Payments are paused while recent payments are checked against the bank."

#### 7.11 Ricky in approvals

- Ricky's check uses three labels, Looks right, Worth a look and Don't approve yet, and every claim links to its source.
- It adds lines to the Checks list only for what the rule checks don't catch. Once daily reports exist (phase 2): "Line 3 bills 31 pumping days. Daily reports show pumps running 29 days."
- If someone approves after "Don't approve yet", History records it: "Approved after Ricky flagged pumping days on line 3."
- Ricky treats every document's text as data. A lookalike gets flagged: "This PDF contains the words "Approved for payment". Cipher doesn't use stamps in documents. Check the approval page." Instructions addressed to Cipher inside a document are ignored and flagged: "This document has instructions addressed to Cipher. They were ignored."
- The popover on the label says, once: "Ricky checks and drafts. Only a person can approve." Asked to approve, Ricky gives the same answer and links to the page.

#### 7.12 Documents from outside S&A

Supplier and sub documents open in a framed viewer labeled with their source ("Northgate Piling Co.'s document. Not a Cipher record."). Approval status, stamps and amounts on screen come only from Cipher's own approval page, never from a document.

### 8. Visual design system

#### 8.1 Character

An established business tool from the Microsoft 365 family, wearing S&A's colors: a navy frame, a white work surface, neutral grays and one small lime accent. Sections are separated by headings and hairlines rather than boxes. It should sit comfortably beside Outlook and Teams and shouldn't look like SAP (no SAP blue, no 72 font, no tile walls).

#### 8.2 Color tokens

CSS variables named by role and mapped into Fluent UI's theme, with a 16-step brand ramp generated from navy. The contrast ratios were calculated for this document.

| Token | Value | Use | Contrast |
|---|---|---|---|
| `brand` | #0B2341 S&A navy | Top bar, left rail, primary buttons, selected tab underline, main chart series | White on navy 15.8:1 |
| `brand-hover` | #13325A | Primary button hover | White on it 12.9:1 |
| `brand-tint` | #E8EDF4 | Selected row, current step | Navy on it 13.4:1 |
| `rail-text` | #B9C6D6 | Unselected rail items | 9.1:1 on navy |
| `accent` | S&A lime; #9FD93A is a placeholder until the brand file confirms it | On navy only: the 4 px selected bar in the rail, the focus ring on navy, the count badge with navy text, the logo mark | 9.4:1 against navy. Lime on white is 1.7:1, so it is never text, icons or bars on white, and never means "good" |
| `bg-app` | #F5F6F7 | Page background | |
| `surface` | #FFFFFF | Tables, forms, panels | |
| `divider` | #E3E6EA | Decorative hairlines | |
| `border-input` | #7A8794 | Inputs, checkboxes, editable cells | 3.7:1 (the old console's #D9DFE6 was 1.3:1) |
| `text` | #131E29 | Body text and figures | 16.9:1 |
| `text-secondary` | #556B82 | Labels, subtitles, source lines | 5.5:1 on white, 5.1:1 on the page |
| `link` | #1A56A8 | Links in prose, always underlined | 7.1:1 |
| `positive` | text #256F3A, tint #E8F3EC | Paid, approved, passed | 6.2:1; 5.4:1 on tint |
| `warning` | text #8A4B00, icon #E76500, tint #FFF4E5 | Needs approval again, on hold, expiring, restored copy | Text 6.8:1; icon 3.4:1 |
| `negative` | text #AA0808, tint #FDECEC | Don't pay yet, returned, over budget, history mismatch, payments stopped | 7.6:1; 6.7:1 on tint |
| `neutral` | text #3D4B5C, tint #EEF1F4 | Draft, waiting, practice strip (hatched edge) | 7.9:1 |

Status colors appear only where state matters, always with an icon and words. Blue is never a status color, because it reads as a link. Navy is never a large fill in the page body.

#### 8.3 Typography

- **Interface:** Segoe UI Variable, then Segoe UI, `-apple-system` (San Francisco on iPads), Roboto and `system-ui`. Segoe UI ships with Windows under Microsoft's license. We never redistribute font files, so the app downloads no fonts and needs no extra license.
- **Printed forms:** the same stack when printing from the browser. If server-generated PDFs come later, they embed Source Sans 3 (SIL Open Font License 1.1), because Segoe can't be embedded in documents we generate.
- **Numbers:** tabular figures (`font-variant-numeric: tabular-nums`), so money columns line up.
- **Sizes:** page title 20/28 semibold; section title 16/22 semibold; body and forms 14/20; compact grid cells 13/18; captions 12/16 (the minimum); key figures 20/28 semibold; "Current payment due" 28/36 semibold; field body 16/24.
- Sentence case everywhere. No all caps or letter-spaced labels. Column headers wrap to two lines rather than being abbreviated ("Total completed and stored to date", never "Cum. TCS").

#### 8.4 Spacing, grid, density

- A 4 px base, with steps of 4, 8, 12, 16, 24 and 32. Gutters are 24 px on desktop and 16 px on tablets and phones. A 12-column grid; forms 720 px at most; grids full width. Rail 232 px or 56 px; side pane 320 to 480 px.
- Breakpoints: phone under 600 px; tablet 600 to 1023; desktop 1024 to 1439 (rail collapsed by default); wide 1440 and up. A touch screen gets the tablet top bar and Touch targets at any width, so a landscape iPad at 1024 to 1180 px isn't treated as a desktop.
- Corners are 4 px on controls, 6 px on dialogs and panels, and square on page sections. Shadows only on floating layers.
- Sticky headers set `scroll-padding-top` so a focused field is never hidden behind them.

| Density | Grid rows | Controls | Smallest target | Used for |
|---|---|---|---|---|
| Compact | 32 px | 32 px | 24 x 24 px with 4 px gaps | Desktop with a mouse (the default) |
| Comfortable | 40 px | 40 px | 32 px | Desktop users who want more room |
| Touch | 48 px | 44 to 48 px | 44 x 44 px | Any touch screen, and field mode |

Density comes from the pointer type and the person's choice and is never mixed on a page. Office pages stay dense, because oversized components are one of the most common complaints about modern ERP themes.

#### 8.5 Icons, tables, forms, status chips

- **Icons:** Fluent System Icons (MIT), regular weight, 20 px (16 in grids, 24 in field mode), filled only for the selected nav item. Always with words, except in the collapsed rail and row markers, which get tooltips and accessible names. Fixed meanings: check circle for done or paid, clock for waiting, arrow sync for needs approval again, warning triangle for blocked, dismiss circle for returned, lock for read-only or sign-in required. No emoji, no illustrations.
- **Tables:** frozen first column with number and name as a link; money right-aligned (cents on transactions, whole dollars on summary figures, 9.2 rule 7); negatives as ($450.00) in reports; percentages to one decimal; units in headers or cells ("620 CY"); a sticky header the same height as the rows; pinned totals; no zebra striping; selected rows get the navy tint and a 3 px navy edge; arrow keys move between cells and Enter edits; skeleton rows only after 300 ms; one status chip per row at most; wide tables scroll inside their own region, never the page.
- **Forms:** labels above fields and always visible; help text under them; required fields say "Required"; problems at the field in `negative` with an icon, and a count in the footer; typed input kept; dates accept "Oct 13, 2026" or "10/13/2026"; money formats on blur; project, period and vendor filled in from context; attachments are uploads, never typed hashes.
- **Status chips:** text with an icon on a tint, in sentence case: Draft, Under review, Revise and resubmit, Approved, not posted, Needs approval again, Don't pay yet, Paid outside Cipher, Sent to the bank (phase 2), Paid, Returned.

#### 8.6 Charts

Few, and each answers a real question: the job cost curve, bullet bars of budget against projected cost by cost code, and AP aging as stacked bars (AR aging in phase 2). A 13-week cash forecast needs its own backend and isn't scheduled. Navy is the main series, #6B87B0 the second (3.7:1 on white, distinct from navy) and slate #7A8794 the comparison, with dash patterns as a second cue. Overruns use the negative color with a word label ("Over $7,400"). Lines are labeled directly. Every chart has "Show as table" and a text summary for screen readers. No pies, donuts, gauges, 3D or animated counters. Built with `@fluentui/react-charts`.

#### 8.7 States, motion, themes

- **Empty:** first use ("Set up your first job. Add the job number, the client you bill and the contract amount. [New job]"), no results, no access, and a cleared table ("Nothing is waiting on you.").
- **Loading:** skeleton rows after 300 ms; a spinner only for actions that take over 2 seconds.
- **Problem loading:** "This list didn't load. The server didn't respond. [Try again]", with the detail under Details.
- **Offline (field, phase 3):** "Saved on this tablet. It will send when you have signal (2 waiting)."
- **Read-only:** the strip, and disabled write actions with the reason.
- **Motion:** 150 ms fades and slides for panels and toasts, no bounce, nothing that animates on its own, and `prefers-reduced-motion` respected.
- **Themes:** light at launch; high contrast from Fluent's built-in theme; an outdoor theme for field mode. Dark mode isn't in phase 1; the tokens make it a later theme swap rather than a redesign.

#### 8.8 Accessibility to WCAG 2.2 AA

- Text 4.5:1; large text, input borders, icons and focus indicators 3:1 (1.4.3, 1.4.11). Status never by color alone (1.4.1).
- Targets 24 x 24 px or spaced (2.5.8), and 44 px on any touch screen. Focus is never hidden under sticky headers (2.4.11) and returns to the trigger when a panel closes.
- Confirmations, counts and problems are announced with `role=status` or `role=alert` (4.1.3).
- Single-key shortcuts can be turned off (2.1.4). Drag to reorder always has Move up and Move down (2.5.7). No re-entering known data (3.3.7). Sign-in through Microsoft 365 with paste allowed (3.3.8). Reflow at 320 px, with data tables scrolling in their own region (1.4.10).
- Every grid action works from the keyboard (Fluent's Tabster navigation). Headings in order. Every input labeled.
- Testing: axe checks in every Playwright test, plus manual keyboard and screen reader passes (NVDA with Edge, VoiceOver on iPad) on the key screens before each release.

#### 8.9 Things we never do

The look people associate with AI-generated apps: purple or teal gradients, glows, glass effects, hairline cards with wide shadows, small all-caps labels above headings, colored stripes down card sides, status dots without words, several primary buttons in one view, rounded hero panels, illustrated empty states, lime text on white, and every section in the same rounded box. This list is a release gate, alongside the copy test.

### 9. Voice and words

#### 9.1 How Cipher speaks

Like a sharp office manager who has run pay apps and month-end for a heavy-civil contractor for years: plain, specific and unhurried. Every message says what happened, why it matters and what to do next, in the same voice Microsoft 365 uses.

#### 9.2 Rules

1. Sentence case for titles, buttons, tabs, headers and statuses. Never all caps.
2. Trade words, never data-model words (9.3). Name a version by what produced it: "SC-03 as revised by CO-02", "checking ending 4471, verified by call-back Sep 30". Raw version numbers appear only in Technical details and History.
3. **Buttons** are verbs that name the outcome, with the amount when money moves: "Approve $48,240.00", "Post to September 2026". A dialog's buttons answer its title: "Close September 2026?" gets [Close September] [Keep open]. Submit, OK, Execute, Run, Call and Grant are never the whole label. "Execute subcontract" and "Sign and execute CO-03" are trade terms and are fine.
4. Messages are sentences, not fragments, and carry one idea. A message bar is 25 words at most and a queue row title 12 at most. No " · " chains, no "label: value" strings run together, no em-dash pileups.
5. **People by name.** Every reference to a person shows their Microsoft 365 display name, with the duty in words only when it helps: "Ask {controller}, who can reopen September". When several people share a duty, name up to two: "Ask {bookkeeper} or {controller}".
6. Name records the trade's way: "Pay app #4 from Northgate Piling Co.", "SC-03", "CO-03", "CE-021". Navigation always says "Sub pay apps" or "Owner pay apps"; "Supplier invoices" means material, rentals and trucking.
7. One format everywhere. Transactions, account balances and accounting entries show cents ("$48,240.00"). Tiles, job headers, forecasts and WIP show whole dollars ("$2,480,000"), with the exact amount on hover or tap. Reports show negatives as "($450.00)". Then "39.1%", "Oct 13, 2026", "September 2026", "2:05 pm", "Waiting 3 days", and in History "Oct 13, 2026 at 9:10 am EDT".
8. Give a problem its size: "Retainage payable is $450.00 off", never "NOT reconciled".
9. **Problems** say what, why and how to fix it, beside the field, and keep what was typed. Never "error", "invalid", "failed", "oops", "please" or "something went wrong". "Sorry" only when data was actually lost.
10. "You" is the reader; "we" is only what Cipher does on its own ("We'll check again at 11:15 am"). The app never says "I".
11. Explain consequences, not plumbing: "Payments are paused while this copy is checked against the bank".
12. No marketing words: seamless, effortless, powerful, unlock, supercharge, smart, intelligent, AI-powered, enterprise-grade.
13. **Empty states** say what will appear and the one next step, and differ for first use, no results, no access and a cleared table.

#### 9.3 Glossary and status words

| Internal name | On screen |
|---|---|
| commitment | Subcontract, or Purchase order |
| `commitment.execute` | Execute subcontract (after both signatures) |
| change, `change.execute` | Change order; Sign and execute change order |
| supplier progress bill, `certify_bill` | Sub pay app; Send to {PM} for review, Save review |
| `bill.approve` grant | Approve pay app, Approve invoice |
| bill posting (the new posting act) | Post bill |
| outside payment record (new) | Payment made outside Cipher |
| prime bill, `prime_bill.send` | Owner pay app; Send to the engineer (phase 2) |
| stored material lot, eligible amount | Materials stored on site; Amount eligible to bill |
| payment intent, `payment.release` | Payment; Release payment (phase 2) |
| dispatch outbox, reconcile payments | Sent to the bank (automatic); Check with the bank |
| destination, destination version | Bank account, shown as "checking ending 4471, verified by call-back Sep 30" |
| commitment version, SOV version | "SC-03 as revised by CO-02" |
| claim authority | Make this the live copy |
| epoch, workspace ID, manifest, hash, fingerprint | Technical details only |
| audit chain | History |
| AP subledger against control | Vendor balances and the AP account |
| forecast at completion, variance, pending exposure | Projected final cost; Over (under) budget; Pending changes (not approved yet) |
| kill switch, step-up | Stop all payments; Sign in again with Microsoft 365 |
| party | Vendor or sub, Client, Employee |
| `situations[]` | Needs attention |
| role grant | "Let {name} verify bank changes?" |
| SHADOW | Working ledger (a label in the Books header) |
| golden fixture, mail sink, simulator | Practice tools only |

| Backend state | On screen |
|---|---|
| draft / pending | Draft / Waiting for approval, or Waiting on you |
| granted | Approved, not posted (bills); Approved, not released (payments) |
| consumed, executed | The real outcome: Posted, Executed, Sent, Paid; in approval history, Approved and applied |
| outcome `stale`, `policy_changed` | Needs approval again, with the reason |
| outcome `expired` | Approval expired |
| outcome `rejected`, `sent_back`, `withdrawn` | Rejected, Sent back, Withdrawn, each with who, when and why |
| paid outside Cipher / confirmed | Paid outside Cipher, check 10452, Oct 12 / Confirmed against the bank |
| queued, submitted / outcome_unknown (phase 2) | Sent to the bank / Sent to the bank, not confirmed. Don't send it again. |
| settled / bank reconciled | Paid / Matched to the bank statement |
| returned, failed / release_quarantined | Returned by the bank, Didn't go through / Payments paused |
| stale evidence (estimate) | Priced from an older drawing |

#### 9.4 Before and after, from the current console's real text

| Today | Cipher |
|---|---|
| Cipher · Owner Console | Home (S&A Cipher in the top bar) |
| SHADOW · synthetic prototype | Practice data. Nothing here is real money and nothing is sent. |
| workspace ws_001a1327f7 · write authority held · epoch 0 | Nothing on a live copy. On a restored copy: This is the Oct 9 backup. It's read-only until {owner} confirms it's the copy to keep. |
| Ricky brief  what needs attention · role [owner] | Waiting on you (5) |
| Ricky  proposes · never executes | In the popover on Ricky's check: Ricky checks and drafts. Only a person can approve. |
| Module · ap_intake | Supplier invoices |
| Prime billing / Payments  simulated rail | Owner billing / Payments |
| Executed commitments / Forecast at completion / Variance to budget | Committed / Projected final cost / Over (under) budget |
| Stored material lots | Materials stored on site |
| Request execution approval | Send for approval |
| Execute | Post bill, Release payment, Execute subcontract, or Sign and execute CO-03 |
| Certify bill [cum. installed line 1] | Review pay app: Total completed and stored to date, line 1, Mobilization |
| Dispatch outbox (0) / Reconcile | Sent to the bank (automatic) / Check with the bank |
| Request send approval (mail sink) | Send to the engineer |
| Record ACH collection (fee 5) | Record payment received (amount, method, bank fee and date are fields) |
| Run golden fixture | Load practice project (practice copies only) |
| CONSUMED / OUTCOME_UNKNOWN / STALE EVIDENCE | Approved and applied / Sent to the bank, not confirmed. Don't send it again. / Priced from an older drawing |
| INVALIDATED (subject changed after approval: amounts,bindings) | Needs approval again. The amount changed from $18,450.00 to $19,100.00 when CO-04 was executed on Oct 13. |
| bill.approve on bill bill_001a1327f72870005d97a3 awaits a decision (amount_due 4500.00, cumulative_gross 55000.00, retainage_this_period 500.00). | Approve pay app #3 from the site piping sub. $4,500.00 due after $500.00 retainage. |
| Supplier bill 3 was certified before its commitment changed; void and re-certify it. | Pay app #3 was entered before CO-04 changed line 6. It needs approval again. |
| Forecast at completion 122000.00 exceeds the budget 115000.00 by 7000.00 (pending exposure 0.00). | Projected final cost is $122,000, which is $7,000 over the $115,000 budget. |
| 2026-11 · banking: bank reconciliation — bank account 1000 has activity in 2026-11 but no bank statement was imported | November: the operating account has activity but no bank statement is loaded. Load it before closing the month. |
| Payment release is quarantined after a restore; run recovery reconciliation before any release. | Payments are paused because this copy came from a backup. Recent payments are being checked against the bank. |
| role 'estimator' is not authorized for payment.release; route to a role that is | You can't release payments. Ask {name}, who releases payments. |
| create_project: 'name' (KeyError) | Enter a job name. |
| CHECK constraint failed: kind IN ('customer','supplier','employee','provider') | Choose a company type: client, subcontractor, supplier, employee or payment provider. |
| Plugin.create_rfi() missing 2 required positional arguments: 'subject' and 'question' | Add a subject and the question before saving the RFI. |
| Toast: request_approval: ok | Sent for approval. {PM} will see it on their Approvals page. |
| evidence revision content hash (signed authorization) | Attach the signed ACH authorization (PDF) |
| Module · fixed_assets [method] [kwargs JSON] [Call] | Equipment [Add equipment]: Description, Cost, In service on, Useful life in months |
| NOT reconciled / UNBALANCED | Retainage payable is $450.00 off. / Out of balance by $1,240.00. |

#### 9.5 Keeping it this way

- Words are owned as section 4 says: the server for approval-page sentences, unavailable-action reasons and problem messages; the front end for everything else, in typed page files and `src/copy/`.
- `src/copy/terms.ts` holds the glossary, the status words and the shared sentences (practice copy, restored copy, history mismatch), so each exists in exactly one place.
- Server problems carry stable codes, and each code maps to a sentence for people. About 1,150 developer-worded exception messages need codes; this is budgeted in phases 1 and 2.
- An automated copy test renders every page from the practice project and fails the build on: snake_case or dotted identifiers in visible text; raw ID patterns (`[a-z]{3}_[0-9a-f]{6,}`); uppercase status text; " · " separators; banned words; buttons whose whole label is Submit, OK, Execute, Run, Call or Grant; numeric-only dates; transaction amounts without cents; message bars over 25 words; queue titles over 12 words; "version" followed by a number outside Technical details and History; and role words such as "the project manager" or "the payment releaser" where a name belongs.
- Someone who does pay apps for a living reviews the words on every new screen before it ships.

### 10. Frontend stack decision

**Decision:** a new React and TypeScript app built with Vite on Microsoft's Fluent UI React v9, themed in S&A navy, and built to static files served from the same origin as the API. Node is only a build tool; nothing Node-based runs in production.

| Concern | Choice | Why |
|---|---|---|
| Language, build | TypeScript 6.x, Vite 8.3.1, React 19.3 | Type safety on money and approval facts; mainstream and fast. TypeScript 7 is the native compiler, and type-aware lint rules and the OpenAPI generator may lag behind it, so we move when they support it |
| Components | Fluent UI React v9, `@fluentui/react-components` 9.74.x as published Sep 23 (MIT) | The design system behind Dynamics 365 and Microsoft 365, which S&A uses daily; a large Microsoft maintainer team; brand ramp theming, dense tables, keyboard grid navigation, high contrast |
| Data grid | In-house RecordGrid on `@tanstack/react-table` 9.2.4 and TanStack Virtual (MIT), drawn with Fluent table parts | Fluent's DataGrid lacks filtering, a column picker and virtualization. TanStack Table 9 is a young major version, so RecordGrid wraps it behind our own API |
| Charts | `@fluentui/react-charts` 9.3.27 | Same tokens as the rest of the UI |
| Routing, data, forms | TanStack Router (filters in the URL), TanStack Query, React Hook Form with Zod schemas generated from the OpenAPI contract | Deep links and cached reads. Zod checks only the shape of a form; business rules are checked by the server's preflight |
| Tests | Vitest 5.0.2 in browser mode, Playwright 1.63.0 on the installed Edge, axe | No separate Chromium download (about 281 MB saved). Vitest 5 is also a young major version |
| Excel and PDF | Export to Excel: an .xlsx written on the server by a small in-house writer on Python's `zipfile` module, with money as numbers in currency format. PDF: browser print stylesheets | No library for either until phase 2's AIA and C-620 print templates. A real .xlsx keeps job numbers such as 24-031 from being reformatted and money from turning into text |

Every version is pinned exactly and was published at least two weeks before we adopt it.

**Alternatives considered.** SAP UI5 Web Components for React came second. It has the most ready-made ERP parts, but it looks unmistakably like SAP and its theming tool needs an SAP BTP account. Rejected: IBM Carbon (265 MB, an IBM look, install telemetry), Mantine (effectively one maintainer), shadcn with Tailwind (the look most associated with AI-generated apps), MUI X (key grid features are paid) and server-rendered htmx (a poor fit for spreadsheet-like grids). AG Grid Community stays a fallback, limited to its MIT features, since grouping, clipboard and range selection are paid.

```
apps/cipher-web/              new; node_modules stays here, never in the Python image
  package.json, package-lock.json, .npmrc (save-exact)
  vite.config.ts              builds to ../cipher/webroot; dev proxy /api -> local API
  playwright.config.ts        channel 'msedge'; starts the API in practice mode
  src/app/                    AppShell (top bar, rail, strips, panels), routes
  src/theme/                  brand ramp from #0B2341, lime accent, densities, high contrast
  src/ui/                     RecordGrid, FilterBar, SavedViews, PageHeader, KeyFacts,
                              LifecycleRail, MessageBar, StatusChip, ApprovalPage, WhatChanged,
                              MoneyCell, MoneyInput, DateField, EmptyState, HelpPanel, Notes
  src/api/                    client, generated OpenAPI types, problem-code mapping,
                              mock server for the contract (used from day 1)
  src/features/               home, approvals, projects, budget, commitments, change-events,
                              sub-pay-apps, supplier-invoices, incoming, books, payables,
                              vendors, settings, help; later payments, owner-billing,
                              close, field, estimating
  src/copy/                   terms.ts (glossary, statuses, shared sentences), format.ts
  tests/e2e/                  one spec per workflow on the practice project, with axe
apps/cipher/webroot/          build output, git-ignored, served by the API layer
```

**Serving and security.** The API layer serves `webroot` with an explicit MIME map (on Windows the registry can report `.js` as `text/plain`, which the existing `nosniff` header would block), long-lived caching for hashed assets, no caching for `index.html`, and `index.html` for every non-API path so deep links work. The Content-Security-Policy allows same-origin scripts only. Fluent's Griffel styles are extracted at build time so styles can be `style-src 'self'`; if extraction proves impractical, a per-response nonce is passed to Griffel instead. React escapes text by default, and a lint rule bans `dangerouslySetInnerHTML`, which closes the old console's HTML-injection hole. The old console and its action API are removed before the pilot (11.2).

**Disk.** The dev install is about 355 MB across 227 packages, mostly the Fluent icons package, which is about 2% of the 17 GB free. `npm cache clean` runs after install, and a multi-stage Docker build ships only the static files.

### 11. Backend feasibility

#### 11.1 Where the backend stands

The domain core is worth keeping. About 1,000 committed tests pass, and a further 234 (the three uncommitted modules plus the HTTP and Ricky SDK suites) pass too. A closer review for this draft found several areas thinner than the first draft said, mostly around authority, purchasing and the ledger.

| Area | Done | Missing for the UI |
|---|---|---|
| Approvals, commands, audit, restore safety | 70% | The approve and post split, outcome codes, decide-by, the re-check job, the fingerprint check, presenters, a restore high-water mark |
| Identity and duties (`people`, untracked) | 30% | Any sign-in at all; more than one account per person; actor and role still come from the request body; enforcement is off until a policy is approved |
| Projects and master data | 30% | Job numbers, location, dates, PM, status; cost code master; single-source contract value; vendor type |
| Documents and drawings | 35% | File storage (today users would paste hashes); the framed viewer |
| Commitments and changes | 60% | Numbers, dates, scope, draft edits, change event register, multi-line change orders with cost codes, owner change orders under approval |
| Sub pay apps and AP | 55% | Pay app records with application number and revision, claimed and approved per line, line-scoped binding, unit-price lines, lien waiver records, outside payments |
| Purchase orders and supplier invoices | 25% | POs cover tagged equipment only: no quantities, partial receipts, tolerance or path for invoices without a PO, and the match authority sits with the wrong role |
| Ledger | 45% | The accountant's chart of accounts, cost code and cost type on journal lines, posting rules by cost type, reads and reversals on HTTP, manual journals, statement parsers |
| Payments | 55% | Real provider, runs, worker, Microsoft 365 step-up, a role check on stopping payments |
| Owner billing and AR | 50% | Line-item owner SOV, C-620 |
| Budget and forecast | 55% | Remove `set_budget`; cost codes; PM projections; a forecast approval; the monthly labor and equipment cost import |
| Accountant hand-off | 65% | Download endpoint; outside payments in the omissions check |
| Field, schedule, labor, estimating | 35% to 55% | Daily reports, crews, quantities, field role, calendar dates, prevailing wage |
| Ricky | 35% | A read-and-draft-only surface; a language model; human wording |
| HTTP API for a UI | 20% | Everything in 11.3 |

Overall, about 50% of the backend for the plan's first production slice and about 30% of plan phases 1 to 4. There is no usable front end yet.

#### 11.2 Fix before anyone uses it

The first four are blockers: nothing goes in front of real people until they are done.

Implementation update, Oct 14, 2026: item 11 now fails startup for configured module failures, and item 13's grant preflight checks are read-only with atomic grant effects. Item 2 is partly addressed by a separate HTTP read/draft catalog and invocation adapter, including refusal of generic SDK calls; the standalone synthetic SDK retains its execution tools. Authenticated session identity and the new API remain open. Item 1 and the other blockers remain open. The numbered descriptions below record the original audit findings and required end state.

1. **Approving and posting aren't separated.** `ROLE_AUTHORITY` has one set per role, used both to grant and to execute, so `pm`, `accountant` and `controller` all hold `bill.approve`: a PM can post and an accountant can approve. The manifest's `actor_role` is chosen by the requester (HTTP takes it from the body and defaults to `owner`), and nothing stops an approver from executing their own approval. `bill.approve` also binds the period and the full journal preview at request time, so posting to another period is impossible. Fix: keep `bill.approve` as the business approval; add a separate posting act that binds the period and the entry at the moment of posting, held only by `accountant` and `controller`; store separate grant and execute authority sets (for example grant `bill.approve` for `pm`, `owner` and `controller`, execute `bill.post` for `accountant` and `controller`); fix the executing role per operation in a server-side table instead of accepting it from the caller; and refuse execution when the executor is the approver for every posting and payment operation. Executing a change order is the one exception: the PM who approved a change order within the limit also signs and executes it, because the second party is the sub's signature on the bound document. Add these to the plan section 10 acceptance and adversarial suites.
2. **Ricky can execute approved actions.** The SDK serves `execute_approved_action`, and `ROUTABLE_OPERATIONS` includes `bill.approve` (which posts), `payment.release`, `payment.release_retainage`, `retainage.release`, `prime_bill.send`, `contract.sign`, `close.close_period`, `close.reopen_period` and `journal.reverse`. `server.py`'s `ricky_tool` action takes actor and role from the body. Fix: the new layer serves Ricky's read and draft tools only. Remove `execute_approved_action` from the catalog it serves, and take `request_approval` for money operations off Ricky's route list. Keep `ROUTABLE_OPERATIONS` deny-by-default with an explicit never-from-Ricky list: every posting, release, signature, outside send, period close or reopen, takeover and co-sign. Ricky always acts as the session's person with a scope the API recognizes; any approve, post, release, send, sign, close, takeover or co-sign request with that scope gets a typed 403 ("Only a person can post this. Open Books > Post approved bills."). Add one adversarial test per verb and a contract test that fails if any Ricky tool reaches `Commands.run` or an apply that posts or releases. History marks anything Ricky prepared: "Prepared by {bookkeeper} with Ricky."
3. **The old action API undoes identity.** It takes actor and role from the body, has `module_call` (any public method of any module with raw keyword arguments) and the simulator hooks. Through it anyone could call `payment_policy.record_step_up` with any assertion hash, `cosign`, `people.bootstrap_owner` or `close.set_contract_value`. Fix: never mount the old API on a live workspace; delete the old console and its API before the pilot. The new layer refuses to start in live mode unless `people.enforcing()` is true and the policy segregates duties. `record_step_up` is called only by the layer's own sign-in callback, which derives the login from the validated token and hashes the token's `jti`, nonce and `auth_time`, so the caller supplies none of them. `check_request` requires the requester to hold a preparing role for the operation, not just be an active person. The development identity stub is excluded at build time from anything but a loopback-only development build.
4. **No identity.** During the audit an $18,000 payment release was requested as "intern" and approved and executed by a self-declared owner named "anyone-at-all". Sign-in must derive the actor on the server (11.3) before anything else ships.
5. **Bank details are stored in plain text** in `parties.destination`, copied into every approval manifest and payment intent, streamed to Azure Blob by Litestream and exported nightly. Fix: store bank details as structured fields (routing number, account type, last 4) plus a ciphertext under envelope encryption with a Key Vault key, or as a provider token. Manifests bind the bank details' version and an HMAC fingerprint, never the number. Decrypt only inside the payment dispatcher (phase 2). Treat tax IDs the same way. Confirm that replicas and audit exports hold only ciphertext.
6. **A restore into the same path gets full write access.** A restored copy is read-only only because its `<db>.authority` file doesn't match the token inside the database. A Litestream restore into the same path keeps the old authority file, so the older books get full write access, payment quarantine never starts and recovery is skipped; a deploy that loses the authority file turns live books read-only. Fix: restores always go to a new path, and the authority file is never copied with the database. At startup the layer compares the database's head audit sequence and entry hash with a high-water mark kept outside it (in the app-state database and Key Vault, updated after each batch of commits); if the database is behind, it starts read-only and quarantined. The authority file lives on the persistent disk beside the database and is checked in the deploy smoke test. The phase 1 restore drill rehearses both cases.
7. **Nothing marks a workspace as practice or live.** Add `workspace.mode` ('practice' or 'live'), set once at creation, recorded in the audit log and protected by a trigger. The layer mounts simulator and practice routes only in practice mode, and a live workspace refuses a simulated provider once real payments arrive. The strips and Ricky read this flag.
8. **`set_budget` changes the budget with no approval** (one call moved a baseline from $115,000 to $12,000). Remove it. After the original budget is locked, `set_initial_budget` must refuse, and changes go through budget transfers.
9. **Contract value is stored twice** (`receivables` and `close`) and `receivables.set_prime_contract` and `close.set_contract_value` change it with no approval. Make one the source, set at job setup under approval and changed only by approved owner change orders.
10. **Expiry is a flat 24 hours from the request** (7.4).
11. **The `people`, `payment_policy` and `contracts` modules are untracked**, and `service.py` silently skips a missing plugin module, so a clean checkout runs a different system. Commit them and make the loader fail loudly.
12. **"Subcontractor" is rejected** as a party type with a raw database error. Add a `vendor_type` column (subcontractor, supplier, rental, trucking) rather than rebuilding `parties` to change its CHECK constraint, which would mean rebuilding foreign keys and triggers.
13. **`people.check_grant` has side effects**: it invalidates approvals and writes `people_self_approvals`. Move those into `grant` itself so the check can run in preflight without changing anything.
14. **`engage_kill_switch` has no role check** (any actor string works). Enforce the owner and the releaser in the layer and in a payments-level check, and record the reason. This is phase 2 work but costs little now.
15. **Missing HTTP actions:** prime contract value and billing recipients, kill switch, cancel payment, cancel credit notes and corrections, journal reads and reversals, stored-material evidence, void owner pay app.

#### 11.3 New backend work for phase 1

**Sign-in and sessions.** Microsoft Entra ID, single tenant, authorization code flow with PKCE through MSAL Python, `response_mode=query`. Tokens stay on the server. The browser holds a `__Host-` cookie that is HttpOnly, Secure and SameSite=Lax (Strict would drop the cookie on the first request after Microsoft redirects back), plus a CSRF token on every unsafe method. `auth_time` is added as an optional claim in the app registration; multi-factor is required through Conditional Access with Business Premium, or security defaults without it, rather than by reading `amr`. Idle timeout 30 minutes, absolute 8 hours (T6 covers what the person sees). A governed binding maps each Entra `tid` and `oid` (never email) to a `people_persons.id`, many accounts to one person, and the layer always passes the person's canonical login as actor. One Entra app role only gates sign-in; business authority stays in the people registry, because Entra administrators can assign app roles to themselves. Add a test that one person's two Entra accounts can't request and approve the same item.

**Reads.** Paged lists with filter, sort, search and counts; one endpoint per record with a version tag; cached home counts with deep links; the approvals inbox; history from the audit chain. Reads use a small pool of read-only connections (`mode=ro`, WAL); writes keep the single locked connection. List reads come from SQL views or projection tables refreshed after each commit (watching `PRAGMA data_version`) or by the worker, never from domain list methods that call `get()` per row (`bills.list` does today, re-hashing the SOV each time). `audit.verify_chain()` comes off every request path; the worker runs it nightly and stores the result. Add indexes on `approvals(status, subject_type, subject_id)`, `audit_log(entity_type, entity_id, seq)`, `journal_lines(account_code, project_id)` and `journals(period_id, source_type)`.

**Money in reads.** Money is stored as TEXT, so SQL sorts "9000.00" after "10000.00", compares text in filters and returns floating point from SUM(). Add integer-cents generated columns (`CAST(ROUND(amount*100) AS INTEGER)`) or build list read models in projection tables with integer cents and indexes. Totals come from integer cents or Python Decimal, never REAL. A contract test compares every list's totals with the sum of the domain records.

**Read permissions:** the matrix in 11.5, enforced in the read model, with Ricky reading through the same layer.

**Numbering.** Readable numbers for jobs, subcontracts, POs, change orders and events, PCOs, owner change orders, pay apps, vendors, payments and approvals. `approvals.number` is assigned inside `Approvals.request()`'s transaction. The API uses fully qualified keys (11.4), and a number alias table keeps renumbered records reachable.

**Actions, errors and preflight.** Typed actions with structured errors (`{error: {code, message, target, details, fix}}`), the message written for people, and 401 (typed, for step-up), 403, 409, 412, 422 and 423 used consistently. A `Database.dry_run()` context runs the real domain method or governor check inside a transaction that always rolls back, with outbox dispatch, file and provider calls switched off, and maps the exception to `{code, target, message, fix}`. Each action gets `:validate` and `:preflight` endpoints, used on record pages and grid entry (never per row on lists), and `?preview=effects` returns the approvals the action would send back.

**Idempotency and drafts.** Today only approval execution goes through `Commands.run`, so a double-click on a creating action (`add_party`, `propose_change`, `receive_invoice`, `register_document`, `request_approval`, `record_deposit`) makes a duplicate. Store each `Repeatability-Request-ID` with its response in the app-state database and replay it, or wrap every creating action in `Commands.run` with the request ID as `op_id`. Grid drafts, edit locks and unsaved forms live in the app-state database; the governed database is written only on Save review, Send or another deliberate act, so autosave never writes audit entries every 20 seconds. Field mode's offline queue depends on this.

**Approvals.**
- Add `decide_by`, `outcome` (rejected, sent_back, stale, policy_changed, withdrawn, expired) and `invalidation_json` (field, old value, new value, cause record, who, when) with ALTER TABLE ADD COLUMN, not a table rebuild.
- The `approvals_request_immutable` trigger lets `expires_at` only move earlier, and there is one expiry column. So set `expires_at` at request to the outer limit (decide window plus apply window), bring it forward at grant to grant time plus the apply window, and check `decide_by` at grant.
- `POLICY_VERSION` is a material key, so changing the expiry policy would make every approval in flight stale at deploy. Either ship a migration that re-requests open approvals, or version the expiry policy separately from `POLICY_VERSION`.
- A re-check job rebuilds the manifest of every pending or granted approval every few minutes and invalidates differences with structured reasons. Today only `change.execute`, bank-detail verification, supplier-invoice attachment and policy changes invalidate at once; facts such as a renewed insurance certificate show up only at execution.
- A current-facts builder that doesn't raise, for the Now column of What changed.
- The fingerprint check at grant, and the presenter registry that fails closed (7.1). Phase 1 needs presenters for about 20 of the 48 operations.
- Delegation (out of office), withdraw and forward, all checked against policy and separation.
- A policy flag letting the preparer approve within limit, for sub change orders and budget transfers only, and PM limits tested on the basis in 7.2.
- Co-signature for loosened policies and sensitive grants. `payment_policy` already requires an independent co-signer when a change weakens a control; the inbox needs it as an item.

**Pay apps and bills.**
- A pay app record carrying the sub's application number and a revision, separate from the internal bill sequence (sequences are never reused, so a voided and re-entered bill can't keep its number today).
- An intake record holding the bookkeeper's claimed amounts and preparer; the PM's changes recorded as reviewer adjustments that the approval binds; segregation comparing the approver with the intake preparer; review and approval as one server command within the limit.
- Line-scoped binding: the bill binds the hash of the lines it bills and the executed-amount cap instead of the whole subcontract version, so `Bills.get` stops marking every draft stale on any change order. `bills.recheck` re-binds a draft to a revised subcontract when its line math is unchanged, writes a new revision with an audit entry, and links the new approval to the old with a `supersedes_approval_id` column.
- Today `certify` refuses while the previous bill is still a draft. With approve and post split, that would stop the bookkeeper entering October's pay app until September's is posted. Allow intake while the previous pay app is approved but not posted.
- `bill.approve` binds the payee's identity (vendor number, legal name, tax ID fingerprint) instead of the bank account.
- The outside payment record (6.11): AP debit and cash credit through the posting check, no double recording, confirmation by a second person, and the check-register import with proposed matches.
- Lien waiver records: type, pay app, amount, date received, document revision.
- A severity on each coverage requirement in `contracts`: block approval, block payment, or warn.

**Purchasing (1b).** Today POs are EPC equipment awards: one SOV line per tagged item, the quote split equally, no quantity or unit price; receipts cover awarded equipment only; the invoice must equal whole PO lines with zero tolerance; the match authority is held by `accountant` and `controller`; and an invoice needs a manually certified bill before it is payable. Phase 1b adds quantity PO lines (item, unit, unit price, quantity) approved like a subcontract; partial receipts by delivery ticket (quantity, date, received by, photo); a quantity and amount tolerance in the match; a payable bill created automatically from a matched invoice; a path for rental and trucking invoices with no PO, coded to job, cost code and cost type and approved by the PM's receipt confirmation; approval by the match within tolerance under the policy in decision 9; and a sales tax line.

**Ledger and masters.** The built-in chart has 5200 as Depreciation expense and 5100 as Reimbursable expense, and no materials, equipment rental or trucking cost accounts. Load the outside accountant's chart, maintained under a versioned approval, with posting rules mapping cost type to account. Add `cost_code` and `cost_type` to `journal_lines` with ALTER TABLE ADD COLUMN (the immutability triggers still hold); today cost codes come from SOV lines, and labor's are parsed from memo text. A cost code master. Job master fields. Multi-line change orders with a required cost code on each line (today change-order SOV lines get an empty cost code and the description "Change: <reason>", so the forecast puts them in UNMAPPED). A forecast approval operation (`forecast.snapshot` is a record method with no approval today). A monthly import of labor and equipment cost by job and cost code from the payroll provider's export, posted by the bookkeeper through the posting check, so phase 1 forecasts aren't missing S&A's own costs.

**Vendors and bank details.** Number, address, encrypted tax ID, W-9 and 1099 flags, `vendor_type`. Bank details per 11.2 item 5. Contact numbers governed with a history. The call-back record captures name and title, number dialed, time and the read-back numbers, compared on the server, and the verifier is always the session person (today `verified_by` is a free parameter).

**Documents.** Uploads to Azure Blob through short-lived user-delegation links. The server re-hashes the file and binds the revision only after a clean Defender malware scan. Previews render in the framed viewer.

**Notifications, notes and the worker.** A notification store; notes with mentions; the outbox for email, which sends nothing from a restored copy that hasn't been made live and only to the test mailbox from a practice copy; expiry sweeps and reminders; the 7:00 am email; the re-check job; and the nightly history seal. The seal writes the chain head to the WORM export and a keyed MAC (key in Key Vault), and every check compares against both, because an unkeyed chain checked against its own database proves nothing to someone who can rewrite the database. A mismatch raises the history-mismatch strip, stops approvals and posting, and goes to {controller} and the owner. Failures land in the Exceptions list with an owner. One process while on SQLite.

**Restore.** 11.2 item 6, plus the claim flow: the owner signs in again, the layer computes the claim code from the owner secret in Key Vault and calls `claim_write_authority`, {controller} is notified, and payments and outside email stay paused until `complete_recovery_reconciliation` finishes and the recovery checklist is done.

**App-state database.** Sessions, saved views, preferences, notifications, drafts and edit locks, notes, the export log, idempotency records and the high-water mark. It keeps the governed books clean and lets people sign in to a restored copy.

#### 11.4 API shape

Following Microsoft's REST guidelines:

- `GET /api/v1/projects/{job}/{collection}?filter=&orderby=&search=&top=&cursor=` returns `{value, nextLink, count, facets, totals}`. Company-level collections are at `/api/v1/{collection}`.
- `GET /api/v1/projects/{job}/{collection}/{number}`, for example `/api/v1/projects/24-031/commitments/SC-03`, returns the record with a version tag, header facts, `situations[]`, `lifecycle[]` and `actions[]` as `{id, label, enabled, reason}`.
- `PATCH` saves drafts with `If-Match`; a stale version returns 412. Actions are `POST .../{number}:send-for-review`, `:review-and-approve`, `:send-for-approval`, `:post`, `:record-outside-payment` and so on, each with a `Repeatability-Request-ID` header and matching `:validate` and `:preflight` endpoints (`?preview=effects`).
- `GET /api/v1/approvals?tab=waiting`, `GET /api/v1/approvals/{number}/page`, and `POST /api/v1/approvals/{number}:approve` (with the fingerprint in `If-Match`), `:send-back`, `:reject`, `:withdraw` and `:forward`.
- `GET /api/v1/home` returns cached counts and rows.
- A raw manifest is never returned to a client. Technical details shows IDs and hashes, never bank details.

#### 11.5 Read permissions

Hiding an area in the UI isn't access control. Today `GET /api/state` returns every approval and payment in the workspace whatever project is asked for, including raw bank details in `parties.destination`, `payment_intents.destination` and the manifests.

| Collection | Scope | Who may read | Masked |
|---|---|---|---|
| Jobs, budgets, forecasts, commitments, change events, pay apps, supplier invoices | The job | The job's team, the owner, {bookkeeper}, {controller} | |
| Approvals | Items the person requested, can decide, or that sit on a job they belong to | The same; the owner and {controller} see all | Manifests never leave the server; presenters only |
| Vendors | Company | Everyone signed in | Tax ID and bank account to last 4, with the verification date |
| Full bank details | None | Nobody through the API; decrypted only in the payment dispatcher (phase 2) | |
| Payables, ledger, accountant package | Company | {bookkeeper}, {controller}, the owner | |
| Payments (phase 2) | Company | Payment duties, the owner, {controller} | Account to last 4 |
| Wage rates and payroll (phase 3) | Company | Payroll duties, the owner, {controller} | |
| History | As its record | As its record | Bank details and tax IDs are never written in full |
| People and settings | Company | The owner and {controller}; everyone sees their own profile | |

Tests call every list endpoint as a PM on another job and as a person with read-only access.

#### 11.6 Recommended production architecture

**API layer:** a FastAPI backend-for-frontend in front of the domain core. It provides the OpenAPI contract (the UI gets generated types), validation, MSAL sign-in, sessions, reads, actions, uploads, the worker and static files. Plain synchronous endpoints run in a thread pool, so the core's single locked write connection works as it is. It adds roughly 25 to 35 pinned Python packages: FastAPI, Starlette, Pydantic and pydantic-core, uvicorn, h11, anyio, MSAL with requests, PyJWT and cryptography, azure-storage-blob and azure-identity, python-multipart, and their dependencies, all hash-pinned and listed in the software bill of materials. The standard-library server stays only as the local development and self-test harness: Python's documentation says `http.server` is not for production, and the standard library has no token signature checking or multipart parser. This ends "standard library only" for the web layer; the domain core stays standard-library only and importable without the API packages.

```
Browser (Edge on desktop, Safari on iPad)
   |  HTTPS, same origin, __Host- session cookie (SameSite=Lax) plus a CSRF token
Azure Linux VM per environment (dev, QA, production)
   FastAPI backend-for-frontend: MSAL sign-in, sessions, CSP, static files,
      reads (read-only connection pool), approval pages, actions, uploads,
      in-process worker; step-up in phase 2
   Cipher domain core (standard library only; about 1,000 tests)
   Books: SQLite on a persistent managed disk (WAL) --Litestream--> Azure Blob (about 1 s behind)
   App-state SQLite: sessions, views, drafts, notes, notifications, idempotency, high-water mark
Azure Blob for documents (Defender scan); Key Vault (owner recovery secret, history MAC key,
bank-detail encryption key); Graph mail; a locked WORM container for nightly audit exports
```

**Database now:** SQLite on a VM with a persistent disk, replicated by Litestream, meets the plan's 15-minute recovery point. It must not run on Azure Files or App Service storage, which are network file systems SQLite advises against, and Container Apps would briefly run two writers during each deploy. A deploy means about a minute of downtime. Losing the VM means a restore to a new path, a read-only copy, the owner making it live, and the recovery checklist. That is correct by design and must be rehearsed.

**Database later:** before finance cutover (plan phase 3), port to Azure Database for PostgreSQL Flexible Server and Container Apps for point-in-time restore, zero-downtime deploys and scheduled jobs. It is a real project, not a driver swap: 551 triggers and about 860 abort statements to rewrite, the read-only control redesigned on database roles, and the full suite run against both engines until they agree.

**Migration path:**
1. Weeks 1 to 3: mockups for the owner; API foundation (error contract, paging, OpenAPI, CI); a mock server for the OpenAPI contract so the shell starts on day 1; the four blockers in 11.2.
2. The rest of 1a: Entra sign-in, people enforcement, the approve and post split, approvals and the pay app slice, on practice copies. The old console and its action API are deleted.
3. 1b: purchasing, ledger masters, change events, Incoming, Blob, notifications and the worker, restore safety, VM hosting with Litestream, Key Vault and WORM exports; then the live pilot.
4. Phase 2: payments with step-up, owner billing, close, bank reconciliation and the ledger, still on SQLite.
5. Before finance cutover: the PostgreSQL port, with both engines in CI until they agree.

#### 11.7 Backend risks

- The four blockers come first. Until they are fixed, any client can claim to be the owner, and Ricky or the old action API can post.
- Single-host SQLite recovery depends on the owner being reachable to make a restored copy live. Rehearse it through the UI.
- Copy debt: about 1,150 messages and 48 presenters. Unbudgeted, the new screens would still read like machine output.
- The pay app grid is the hardest screen (frozen columns, paste from Excel, keyboard navigation, virtualization, the tablet line sheet). Budget 3 to 5 weeks for it.
- Phase 1 has grown by about a third since the first draft. Holding 1a to its thin slice is what keeps the owner seeing working screens early.
- Semantic drift in the PostgreSQL port (null handling, trigger order, deferred constraints, money as text). Only the dual-engine run catches it.
- Stronger step-up needs Entra ID P1; without it, step-up relies on forced re-login and time checks.
- Supply chain: hash-pinned installs, a software bill of materials and scheduled updates. TanStack Table 9 and Vitest 5 are young major versions.

### 12. Phased delivery plan

Effort is in person-days for capable developers working with an AI assistant. These are planning allowances, not quotes, and backend and frontend work overlap.

#### 12.1 Phase 1a: the thin slice, on practice data (8 to 10 weeks)

**Scope.**
- Weeks 1 to 3: mockups (shell, PM home, job overview, SC-03, the pay app review grid, the approval page) at 1440 px, 1024 px tablet and 390 px phone, on the Fluent theme with practice data, approved by the owner (decision 12). The API foundation and the contract mock run in parallel.
- Platform: Entra sign-in with many-to-one accounts; people enforcement on; executing roles fixed on the server; the four blockers and items 7, 8, 10, 11, 12 and 13 of 11.2; reads with read permissions for the 1a collections; the read path and indexes; numbering; structured errors and preflight; idempotent creates; the app-state database; per-operation expiry with decide-by and outcome codes; presenters for the 1a operations, failing closed; the fingerprint check.
- Backend: the approve and post split; pay app records with claimed and approved lines and reviewer adjustments; line-scoped binding and the re-check; PM limits; bill approvals bound to payee identity.
- Screens: sign-in, shell and search, the 1a parts of the Company, My projects and Books home pages, Approvals and the approval page, controller review, Projects and the job overview (cost side), subcontract records and setup, sub pay app entry beside the PDF (files on the practice copy's disk), the review grid, Post approved bills, History, Settings > People, Help.

**Acceptance.**
- Everyone signs in with Microsoft 365. No request body can set the actor or role. A PM can't post; an approver can't post their own approval. Ricky's scope can't approve, post, release, send or sign, with one test per verb. The old action API is gone from every build that can reach live data.
- The phase 1a rows of 12.6 pass through the new API and screens on practice data.
- The copy test and the "things we never do" review pass on every page; axe finds no serious or critical issues; keyboard and screen reader passes succeed on the approval page and the review grid.
- Reads under 2 seconds and actions under 3 seconds at the 95th percentile, on a practice copy loaded with two years of synthetic data.

**Effort: about 80 to 100 person-days.**

#### 12.2 Phase 1b: pilot readiness, live on one job

**Scope.**
- Platform: Blob documents with malware scanning; notifications and the 7:00 am email; the worker (re-check job, expiry sweeps, nightly history seal); Graph mail and the vendor message pattern; Books > Incoming; Exceptions; the restore high-water mark, the Key Vault claim flow and the recovery checklist; bank detail encryption; VM hosting with Litestream, Key Vault and WORM exports.
- Backend: chart of accounts and posting rules; cost code and cost type on journal lines; the cost code master; single-source contract value and owner change orders; the change event register with multi-line change orders; forecast approval; the labor and equipment cost import; quantity POs and receipts with tolerance and the no-PO path; severity per coverage requirement; lien waiver records; outside payment records; vendor master fields; governed contact numbers and the read-back call-back; notes; delegation, withdraw and forward; Excel export.
- Screens: Budget and forecast with transfers; Change events with sub and owner change orders; Supplier invoices with the match; Incoming; Payables with outside payments; the accountant package; Vendors and bank detail changes; Documents on Blob; Notes; Exceptions; the rest of Settings (policy, cost codes, chart of accounts, who can do each step); job cost, AP aging and audit export; the rest of the home pages; the glossary.
- Not in phase 1: paying from Cipher. S&A pays through its current process, and Cipher's ledger stays labeled the working ledger.

**Acceptance (phase 1, from plan section 11).**
- One new project runs through Cipher for at least 20 representative bills or a full billing cycle, with every record traceable, zero accountant-package omissions (outside payments included), and measurably faster approvals and a better forecast than today.
- No bill can be recorded as paid twice; an outside ACH payment to an unverified account is refused; every outside payment is confirmed by a second person.
- The separation rules in 7.7 hold over HTTP with real identities. No approval expires before its policy time, and every queue row shows its expiry.
- The phase 1b rows of 12.6 pass, through the UI wherever a screen exists.
- A restore drill: a restore to a new path; a restore into the old path caught by the high-water mark; the read-only strip and disabled actions; the takeover through the Key Vault claim flow with {controller} told; a held recovery with approvals to ask for again; and no email sent from the restored copy before it is made live.
- Copy, accessibility and performance as in 1a, on the pilot VM.

**Effort: about 85 to 160 person-days.**

#### 12.3 Phase 1 in total

Backend 95 to 150 (platform 55 to 85, controls and domain work 40 to 65); frontend 60 to 95 (mockups and foundation 15 to 20, the pay app grid 15 to 25, other screens 30 to 50); copy, accessibility and QA 10 to 15. **About 165 to 260 person-days**, roughly 4 to 6 months for two developers and about a third more than the first draft's 125 to 190. The extra comes from the controls this review found: separating approval from posting, pay app records and line-scoped binding, quantity purchasing, ledger dimensions, preflight, the re-check job, read permissions, encrypted bank details, the read path, idempotent creates, the workspace mode and restore safety.

#### 12.4 Phase 2: money out, owner billing and the full close

**Scope:** the Payments home page, a payment runs table, line-by-line release with Microsoft 365 step-up in a popup (a pending release stored on the server under the sign-in state, with nonce, `max_age` and `auth_time` checked on return and the step-up bound to exactly those lines), a `payment_policy` change so one step-up can cover up to N approvals listed when it starts, stop all payments with a role check, payment exceptions (an unknown outcome past the time limit becomes "Needs a decision: the bank can't tell us whether this went through", routed to the releaser and the owner; a return to a closed account makes that account unusable until a verified change), the co-sign item, and the simulator in a practice copy until a provider is chosen. Owner billing: the owner SOV with lump-sum and unit-price bid items, the owner pay app grid, AIA G702/G703, EJCDC C-620 and unit-price estimate print templates, and sending to the engineer as its own approval. Receivables. Bank reconciliation with CSV, OFX and BAI2 import. Ledger reads, manual journal entries, reversals and auto-reversing accruals. Month-end close, the WIP schedule and WIP entry, retainage with step-down terms and release. Lien waivers as a payment gate. RFIs and submittals. Online daily reports with quantities installed, so Ricky can check billed quantities. Equipment rates charged to job cost. 1099 and W-9 year-end.

**Acceptance:** a full monthly close in Cipher in parallel with the outside accountant's books, with the tie-outs matching; payment runs released on the simulator with step-up and every separation rule enforced; owner pay apps printed on the client's required form; no payment blocker that wasn't visible on the subcontract or pay app first; the phase 2 rows of 12.6; and a restore drill that includes adopting a transfer the restored copy never recorded.

**Effort: about 115 to 180 person-days.**

#### 12.5 Phase 3: field, payroll compliance and finance cutover

**Scope:** offline field mode (daily report, crew time, quantities, T&M tickets that become change events, photos with resumable upload); crews, trade classifications, prevailing wage and certified payroll (WH-347) for public water and DOT work; the schedule with calendar dates and a 3-week lookahead; Estimating; closeout polish; Ricky with a language model, still read-and-draft-only and acting as the signed-in person; the PostgreSQL and Container Apps port; a real payment provider; finance cutover qualification (three parallel closes, an independent security review, restore and return tests, accountant sign-off, per plan section 11).

**Acceptance:** field entries survive no signal and never duplicate; a crew week produces a correct certified payroll report; the full suite passes on both database engines; the phase 3 rows of 12.6 pass; the plan's phase 3 gate is met.

**Effort: about 135 to 215 person-days**, of which the PostgreSQL port is 39 to 60.

#### 12.6 Plan section 10, step by step

Each step and variant of the plan's acceptance test V1, with the phase it lands in, the API action, the screen and what the person sees.

| V1 item | Phase | API action | Screen | What the person sees |
|---|---|---|---|---|
| 1. Estimate, agreement, signature and execution | 3 (estimate), 1a (subcontract) | `estimates:approve`; `commitments:send-for-approval`, `:sign`, `:execute` | Estimating; Set up subcontract; subcontract record | "Approve new subcontract SC-01, $100,000.00." |
| 2. Drawing B, RFI, $10,000 change | 2 (RFI), 1b (change) | `rfis:send`; `change-orders:approve`, `:execute` | RFI; change event; execute dialog | "SC-01 goes from $100,000.00 to $110,000.00." |
| 3. Timesheets and labor allocation | 3 | `timesheets:approve` | Crew time | "2 of 5 timecards can't be approved. Their cost codes are closed." |
| 4. Period 1 certification, $27,000 due | 1a | `pay-apps:send-for-review`, `:review-and-approve` | Entry; review grid; approval page | "... is owed $27,000.00 for period 1 work and stored materials, after $3,000.00 retainage." |
| 5. Posting the period 1 entry | 1a | `bills:post` | Post dialog | The four-line entry, then [Post to {period}] |
| 6. Release, provider timeout, replay | 2 (1b records an outside payment instead) | `payments:release`, reconcile | Payment run; Waiting for bank | "Sent to the bank, not confirmed. Don't send it again." |
| 7. Period 2 with $10,000 moved from stored | 1a | `:review-and-approve`, `bills:post` | Review grid; Post dialog with two entries | "The first entry moves $10,000.00 from stored materials to project cost." |
| 8. Prime bill, $54,000 due | 2 | `owner-pay-apps:approve` | Owner pay app grid | "Ashford owes $54,000.00 on owner pay app #1, after $6,000.00 retainage." |
| 9. Send, ACH collection with a $5 fee, late return | 2 | `owner-pay-apps:send`; `receipts:record` | Receivables | "Ashford's $54,000.00 payment was returned on Nov 3. The receivable is open again." |
| 10. Final billing, retainage release, closeout | 2 | `retainage:release`; `closeout:accept` | Subcontract closeout checklist | "Release $11,000.00 of retainage on SC-01?" |
| 11. Close, late correction, restore | 2 (close), 1b (restore) | `close:close`; `bills:correct`; takeover | Month-end close; restored copy | "September is closed. Post the correction to October with a reason, or ask {controller} to reopen September." |
| Payee, bank or attachment changed after approval | 1a (attachment), 1b (payee), 2 (bank) | re-check job; `:approve` returns 412 | Needs approval again | "Delivery ticket 30418 was replaced with a signed copy at 1:15 pm." |
| Wrong entity | 1a | `:approve` and `:post` refuse | Approval page header shows the legal entity | "This bill names a different company than SC-03. Nothing was posted." |
| Changed tax or fee | 1b (sales tax), 2 (payment fees) | re-check job | Needs approval again | "Sales tax changed from $0.00 to $384.50 after you approved." |
| Expired or removed approver | 1a | `:post` refuses | Needs approval again | "{PM} no longer approves for 24-031, so this needs approval again." |
| Two concurrent releases | 2 | `payments:release` with `Repeatability-Request-ID` | Release dialog | "Already released by {name} at 11:12 am. Nothing else was sent." |
| Counterfeit approval text in a PDF | 1a | Ricky's check | Framed viewer; Checks | "This PDF contains the words "Approved for payment". Cipher doesn't use stamps in documents." |
| Malicious instructions in a document | 1a | Ricky's check | Checks | "This document has instructions addressed to Cipher. They were ignored." |
| Expired content license | 3 | `estimates` | Estimating | "The price book license ended Sep 30. Prices from it can't be used." |
| Unit or scale mismatch | 1a | `:validate` | Review grid | "Line 7 is billed in LF, but the bid item is in CY." |
| Duplicated or omitted events | 1a (creates), 1b (package), 2 (webhooks) | `Repeatability-Request-ID`; omissions check | Accountant package | "2 outside payments aren't confirmed yet." |
| Overbilling | 1a | `:validate` | Review grid | "Line 4 is over its scheduled value. Walers and bracing has $39,000.00 left." |
| Missing mandate | 2 | `receipts:collect` | Receivables | "Attach Ashford's signed ACH authorization before collecting." |
| Failed provider MFA | 2 | step-up | Release dialog | "Your sign-in didn't include a second step, so nothing was released." |
| Stale drawing | 3 (estimate), 2 (RFI) | | Estimating; RFI | "Priced from an older drawing." |
| Unresolved payment outcome | 2 | reconcile | Payment exceptions | "Needs a decision: the bank can't tell us whether this went through." |
| Restore followed by outbox replay | 1b (email), 2 (payments) | worker | Restored copy | Nothing is emailed or paid until the copy is made live and the recovery checklist is done. |

### Appendix A. Phase 2 screens

These are built in phase 2. They are kept here so the phase 1 components (lifecycle rail, decision dialogs, checklists) are designed with them in mind. Same day, same figures.

#### A.1 Month-end close: Close September 2026

**Header:** "Close September 2026", Open. 9 of 13 checks done; accountant package due Oct 15; last posting Oct 12. As of 10:00 am:

1. **Operating account ending 5521.** Done. "Reconciled to the Sep 30 statement. Locked Oct 9 by {bookkeeper}."
2. **Payroll account ending 8830.** Open. "The September statement isn't loaded." [Load statement]
3. **Supplier cutoff.** Open. "2 sub pay apps cover September work and aren't posted: Northgate pay app #4 ($48,240.00, approved) and Crestline pay app #3 ($32,040.00 asked, under review). Post them, or accrue them." [Prepare accrual]
4. **Vendor balances and the AP account.** Done. "Both are $412,880.55."
5. **Retainage payable.** Open. "$450.00 off." [See the difference]
6. **Customer balances and the AR account.** Done.
7. **Stored materials.** Done. "$18,600.00 on hand across 2 subcontracts, each with a delivery ticket and photo."
8. **WIP and over or under billing.** Open. [Review WIP schedule]
9. **Equipment depreciation.** Done.
10. **Labor and payroll posted.** Done.
11. **Payment provider clearing at $0.00.** Done.
12. **Trial balance and variance review.** Done. "Debits and credits are both $4,286,915.40. 3 accounts moved more than $5,000.00 and 10%, and all 3 are explained."
13. **The owner's own approvals reviewed.** Done. "The one approval from Oct 9 isn't due for review until Oct 16."

Each step shows its preparer and reviewer with times: "Prepared by {bookkeeper} Oct 9. Reviewed by {controller} Oct 10."

**Footer:** [Close September 2026], disabled, with "4 checks are still open" under it. When all are done it opens "Close September 2026? Nobody can post to September after this unless {controller} reopens it." [Close September] [Keep open]. After closing, [Prepare accountant package] becomes the primary action.

#### A.2 Payments to release: payment run for Oct 15

{owner}'s view at 11:00 am, as the person who releases ordinary payments (decision 16).

**Title:** "Payment run for Thursday, Oct 15, 2026". "Prepared by {bookkeeper} Oct 13 at 8:30 am. Paid from the operating account ending 5521. 3 payments ready, $43,417.70." {bookkeeper} sees this, because it blocks them: "You prepared this run, so someone else has to release it."

**Tabs:** Ready to release (3), Not ready (1), On hold (2), Waiting for bank (1), Returned (1), Sent this week (6).

| Checked | Payee | For | Project | Amount | Pays to | Bank details verified | Ready to pay |
|---|---|---|---|---|---|---|---|
| [ ] | Bluestone Dewatering LLC | Pay app #6, SC-02 | 25-019 | $22,615.50 | ACH, checking ending 0287 | Aug 4, by call-back | 8 of 8 |
| [ ] | Keel Ready-Mix | Invoice 88477, PO-06 | 25-007 | $9,322.20 | ACH, checking ending 7714 | Jun 12, by call-back | 3 of 3 |
| [ ] | Kestrel Pump Rental | Invoice 5512, PO-03 | 25-019 | $11,480.00 | ACH, checking ending 3306 | Sep 2, by call-back | 3 of 3 |

Each line opens a drawer with every fact (payee, amount, bank account and when it was verified, funding account, date, fees, the bill, who approved and who posted it, requirements met) and can be ticked only after its drawer has been opened. **Footer:** "1 of 3 checked." [Release 3 payments, $43,417.70], disabled, with "Open and check each payment first" under it. Unticked lines roll to the next run.

- **Not ready:** Northgate Piling Co., pay app #4, $48,240.00. A three-item checklist: Post it; {owner} approves the payment (over $25,000.00); Conditional waiver for pay app #4.
- **On hold:** Ironline Steel Supply, 24-031 PO-02, $14,906.00. "New bank account (ending 2293) approved Oct 13. Payable from Oct 16 at 8:40 am after re-approval." [Ask for approval]
- **On hold:** Harbor Crane Rental, 24-031 PO-04, $7,250.00. "Can't pay yet. Their general liability certificate expired Oct 1." [Ask for an updated certificate]
- **Waiting for bank:** Tri-County Trucking, $6,880.00. "Sent Oct 12 at 2:05 pm. The bank hasn't confirmed it. Don't send it again. We'll check again at 11:15 am." [Check now]. There is never a Retry button. The bill shows "Can't be added to a run until the bank confirms or returns the $6,880.00 payment." Past the policy's time limit it moves to Payment exceptions.
- **Returned:** Ridgeline Electric, $3,420.00. "Returned by the bank Oct 11: the account is closed. The invoice is open again." That bank account can't be used until a verified change. [Ask for new bank details]

**Release dialog:** "Release 3 payments for $43,417.70?" A table of the three lines (payee, amount, account ending, when it was verified, bill, project), then: "Paid from the operating account ending 5521 on Oct 15, 2026. No fees. The bank can't recall an ACH payment once it accepts it. You'll sign in again with Microsoft 365 before anything is sent, and that sign-in covers these 3 payments only." [Sign in and release] [Don't release] (has focus).

After the sign-in, the toast reads "3 payments sent to the bank. We'll let you know when the bank accepts them." History: "Released by {owner} after a fresh sign-in. Oct 13, 2026 at 11:12 am EDT." If a line changed while the dialog was open: "Bluestone Dewatering's payment changed after you checked it, so it was left out. 2 payments, $20,802.20, were sent."

**High-risk lines** ($25,000.00 or more, or the first payment to an account) are never released in a group. Each is approved by {owner}, then released on its own with its own sign-in by {controller}. Payments to an account changed in the last 3 days can't be released until the waiting period ends, and the first payment after that is high risk. At $100,000.00 or more a fourth person co-signs first, through the Co-sign item in their Approvals.

### Appendix B. Where the patterns come from

| Pattern in this spec | Seen in | Source |
|---|---|---|
| A home page per role | Business Central Role Centers; NetSuite role centers | [Microsoft](https://learn.microsoft.com/en-us/dynamics365/business-central/dev-itpro/developer/devenv-designing-role-centers), [Oracle](https://docs.oracle.com/en/cloud/saas/netsuite/ns-online-help/chapter_N131898.html) |
| The job as the working context; switching jobs keeps the tool | Procore | [Procore](https://v2.support.procore.com/product-manuals/login-and-account-management/tutorials/navigate-procores-tools/) |
| Controls that never move | Complaints about Oracle's Redwood rollout | [Shortways](https://shortways.com/blog/articles/redwood-migration/) |
| A clear cue for which copy you're in | Complaints about NetSuite's Redwood theme | [NetSuite Professionals](https://archive.netsuiteprofessionals.com/t/22796006/when-using-redwood-theme-i-can-t-change-the-colors-in-my-pre) |
| Fast home pages with cached counts | NetSuite reviews citing slow dashboards | [Capterra](https://www.capterra.com/p/135757/NetSuite/reviews/) |
| One page type per job | SAP Fiori floorplans | [SAP](https://www.sap.com/design-system/fiori-design-web/v1-151/page-types/floorplans/when-to-use-which-floorplan) |
| Finalizing actions bottom right | SAP Fiori action placement | [SAP](https://www.sap.com/design-system/fiori-design-web/v1-151/foundations/best-practices/global-patterns/action-placement) |
| Partial processing stated first | SAP Fiori | [SAP](https://www.sap.com/design-system/fiori-design-web/v1-151/foundations/best-practices/global-patterns/messaging/processing-multiple-items) |
| Approvals inbox in two columns | SAP My Inbox, flexible column layout | [SAP](https://www.sap.com/design-system/fiori-design-web/v1-151/page-types/page-layouts/flexible-column-layout) |
| No wizards for routine work | SAP Fiori wizard guidance | [SAP](https://www.sap.com/design-system/fiori-design-web/v1-151/ui-elements/wizard) |
| Few subtabs | NetSuite guidance | [Oracle](https://docs.oracle.com/en/cloud/saas/netsuite/ns-online-help/section_N2855162.html) |
| Trade synonyms in search | Business Central search | [Microsoft](https://learn.microsoft.com/en-us/dynamics365/business-central/ui-search) |
| Typed filters in the URL | Stripe dashboard | [Stripe](https://docs.stripe.com/dashboard/search) |
| Claimed and approved side by side, with reasons | Procore invoice review | [Procore](https://v2.support.procore.com/en-ca/product-manuals/invoicing-project/tutorials/review-a-subcontractor-invoice-as-an-invoice-administrator/) |
| Line-by-line payment review | NetSuite | [Oracle](https://docs.oracle.com/en/cloud/saas/netsuite/ns-online-help/section_1537056839.html) |
| Close checklist with sign-offs | Rillet | [Rillet](https://docs.rillet.com/EjmEP4KZ9BVp9j2ho4Mh/close-management/close-checklist/intro-to-the-close-checklist) |
| Checks with every claim cited | Ramp Policy Agent | [Ramp](https://support.ramp.com/hc/en-us/articles/44072387128979-Policy-Agent-Overview) |
| The assistant beside the work, never required | NetSuite's Ask Oracle | [SiliconANGLE](https://siliconangle.com/2025/10/07/oracle-netsuite-overhauls-user-experience-introduces-ai-driven-updates/) |
| Compliance holds found on payment day | Vista users | [Billy](https://billyforinsurance.com/resources/viewpoint-vista-coi-compliance-holds/) |
| Dense office pages | Oracle's declined compact Redwood theme | [Oracle](https://apexapps.oracle.com/pls/apex/apex_pm/fr/r/FR-2937) |
| Auto-approval within match tolerance | SAP invoice verification tolerances; NetSuite 3-way match; Dynamics 365 invoice matching | Vendor documentation |
| Export to Excel from every list; shared and personal views | NetSuite saved searches; Fiori Export to Spreadsheet and variants; Business Central Open in Excel and views | Vendor documentation |
| Notes and @mentions on records | Dynamics 365 timeline; Fiori notes; NetSuite user notes | Vendor documentation |
| Delegation, recall and forwarding of approvals | Fiori My Inbox substitutes; Dynamics 365 delegation and recall; NetSuite approval routing | Vendor documentation |
| An inbox for incoming documents | NetSuite Bill Capture; Business Central Incoming Documents; SAP inbound invoices | Vendor documentation |
| Fluent as the design system behind Dynamics 365 | Microsoft | [Microsoft](https://learn.microsoft.com/power-apps/user/modern-fluent-design) |
| Voice | Microsoft style guide | [Microsoft](https://learn.microsoft.com/en-us/style-guide/top-10-tips-style-voice) |
| Shared mailbox scoped to the app | Exchange RBAC for Applications | [Microsoft](https://learn.microsoft.com/en-us/exchange/permissions-exo/application-rbac) |
| Teams Workflows instead of connectors | Microsoft 365 connectors retirement | [Microsoft](https://learn.microsoft.com/en-us/microsoftteams/m365-custom-connectors) |
| Step-up with Conditional Access | Entra authentication context | [Microsoft](https://learn.microsoft.com/en-us/entra/identity-platform/developer-guide-conditional-access-authentication-context) |
| Tokens kept on the server, cookie in the browser | IETF guidance for browser-based apps | [IETF](https://datatracker.ietf.org/doc/draft-ietf-oauth-browser-based-apps/) |
| Malware scanning before binding a file | Defender for Storage | [Microsoft](https://learn.microsoft.com/en-us/azure/defender-for-cloud/introduction-malware-scanning) |
| API shape | Microsoft REST guidelines | [Microsoft](https://github.com/microsoft/api-guidelines/blob/vNext/azure/Guidelines.md) |
| No `http.server` in production | Python documentation | [Python](https://docs.python.org/3/library/http.server.html) |
| No SQLite on network file systems | SQLite documentation | [SQLite](https://www.sqlite.org/useovernet.html) |

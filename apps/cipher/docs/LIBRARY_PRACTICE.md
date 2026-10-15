# Authored project library practice

Cipher's bounded library workflow stores actual authored specification templates and contract clauses, retains every exact revision, and lets a different project PM authorize an internal reference copy. The separate Fluent 2 entry follows the shared page templates and action-review pattern. All people, projects and content in this entry are explicitly synthetic practice records.

Adoption creates a project reference containing the reviewed text. It does not execute a contract, accept legal terms, certify engineering, issue a document, collect a signature or change financial records. The effect is labeled `project-reference-only/1`; journal, AP, AR and provider-call deltas are zero.

## Run the separate entry

From the repository root, with the pinned web dependencies installed:

```bash
npm --prefix apps/cipher/web run build:library
python -m apps.cipher library-practice-web --port 8770
```

Open `http://127.0.0.1:8770`. The build writes `web/dist-library`; the entry document is `library-practice.html`. Backend tests use Python 3.12 or later and the standard library only. Useful focused checks are:

```bash
python -m unittest apps.cipher.tests.test_library
python -m unittest apps.cipher.tests.test_library_actions
python -m unittest apps.cipher.tests.test_library_history_upgrade
python -m unittest apps.cipher.tests.test_library_namespace
npm --prefix apps/cipher/web run smoke:library
```

Each server owns a fresh in-memory practice workspace. The fixture supplies two different registered project PMs, a hidden project, and inactive/accounting-only control identities. It starts with no authored entry, reference plan, reference or library approval. Stopping the process discards its records. The server accepts no file-workspace, actor, provider, credential or policy selector. Practice persona selection is synthetic session behavior; operational staff authentication remains separate work. Fluent components require no Microsoft sign-in.

## Six fixed actions

The API contract is `cipher.library-practice.v1`, under `/api/library-practice/v1/`. Every action requires the current person's own effective PM grant and membership in the same project.

| Action | Resource and route | Result |
|---|---|---|
| `library.create` | Project: `projects/{id}/create-entry` | One entry and its first exact text revision |
| `library.revise` | Entry: `library-entries/{id}/revise` | A successor revision and immutable head transition |
| `library.prepareReference` | Revision: `library-revisions/{id}/prepare-reference` | An immutable plan for that current revision and declared purpose |
| `library.requestAdoption` | Plan: `reference-plans/{id}/request-adoption` | A pending independent PM review |
| `library.approveAdoption` | Approval: `adoption-approvals/{id}/approve` | The original grant; no reference yet |
| `library.applyAdoption` | Approval: `adoption-approvals/{id}/apply` | One exact project reference under that same grant |

Append `:preflight` to an action route for its pure review. Review creates no source, approval, reference or receipt. Effects require the returned fingerprint, the reviewed `If-Match` version, the session's CSRF token and a `Repeatability-Request-ID` UUID. Duplicate JSON fields, extra fields and body-supplied people, roles, policies, ownership claims or delivery choices are refused.

Creation accepts exactly `{kind, title, text, sourceLocator}`, with `kind` equal to `specification_template` or `contract_clause`. Revision accepts exactly `{previousRevisionId, text, sourceLocator, changeReason}`. Reference preparation accepts exactly `{targetLocator, purpose}`. Request, grant and application have empty typed bodies; only the effect fingerprint is added. The JSON envelope is bounded to 512 KiB, allowing escaped text within the separate content limit.

The preparing PM requests adoption. A different actual project PM reviews it. A current actual PM then applies the original grant; the preparer or reviewer may do so. This requires two independent people and does not impose a third-person rule. Owner wildcard authority, entity roles, delegations, external/service/inactive identities and supplied role labels do not substitute for actual current project PM duty. The people policy must be intact, enforcing and segregated. Current duty is checked before private source, receipt or command-cache access and again within native effect checks.

## Exact text and revision lineage

The native library stores the actual text, its UTF-8 byte count and hash, source locator and original creator. Core Evidence separately attests document/revision hashes; it does not supply document bytes or a download capability.

Authored text has a **65,536-byte UTF-8 limit**, including multibyte characters. Whitespace, CRLF, Unicode and trailing newlines are preserved exactly. Empty/whitespace-only text, NUL and invalid Unicode are refused. The source is permanently labeled `practice-authored-editor-text/1`. There is no upload/import path or ownership checkbox to reinterpret licensed material.

One entry can have many revisions. A revision must name the proven current predecessor, and each head transition retains its previous head and exact revision. The system reconciles all original entry/revision/head rows with their audited births and native Evidence revisions. Missing original rows, same-ID substitutions, deleted heads or unexplained native revisions hold the source even after storage guards are restored.

Lists, search, preparation choices and detail views resolve project scope before private text, source proofs or counts. Search uses actual current stored text. An original revision and the separately proven current revision remain distinct in DTOs. An adopted reference keeps its original text, revision, locator, purpose and creator/reviewer/applicator provenance after a genuine later revision. A fresh adoption must prepare and independently review the current revision; an older pending or granted source becomes stale when material facts change.

## Current rights and original outcomes

Current text access and fresh adoption use complete original document-rights inventories and native `project_use` permission. License tags, terms, current heads, removals, purges and applicable processor settings are proved against their original audited histories. A missing original tag or terms row cannot turn licensed text into assumed company content.

This first slice admits practice editor-authored text only. Any original license-tag history holds current text access and new adoption, including after a genuine untag. Licensed-content ingestion needs a later qualified workflow. An original internal reference proof remains a historical record after a genuine rights change; it does not grant new permission to distribute content.

Native operation `library.adopt_reference`, subject type `library_reference_plan`, binds the exact source, purpose, current rights/head disclosure, project duties, policy and original deadline. Grant records no copy. Application consumes that same grant and creates one immutable copy. A posting period is refused. Original request, grant and consumption must match their complete manifests and audited chronological acts before the original deadline.

`original_reference_proof` proves the immutable original reference and authorization separately from current source/rights information. Completed command/API retries return their original outcome after genuine later revisions. They still require the caller's own current duty and prove original source, command, result and receipt integrity. A changed body/version/fingerprint under the original UUID conflicts; an uncertain response is recovered with the original reviewed request rather than a new UUID.

All source revisions, native Evidence, grant consumption, command bookkeeping, reference copy and API receipt share the effect transaction/savepoint. Late faults, commit faults and unexpected callback changes roll back the whole action, including when a caller catches the failure inside an outer transaction. Independently proved expiry/staleness controls may retain their terminal refusal. Deadline generation is server-owned and bound to the locked native review, including genuine clock-boundary generation; callers cannot extend or shorten it.

Receipt recording freezes the original canonical person, login, UUID, action, resource, body, fingerprint, version, result, source, outcome/status and workspace, then compares the returned receipt with the actual stored row and its complete original audit proof. Library, AP, AR, estimating and pending/completed accounting work share a UUID namespace per canonical person. A collision creates no second effect or worker/provider attempt. Namespace verification reads local metadata only and initializes no domain, worker or provider. Missing original receipt rows, births or admission hold new work.

## Schema and copied-workspace boundaries

The required deferred `library` governor imports without mutating the catalog. Canonical registration appends these actual entries after unchanged schemas 1–75:

| Registration | Named schema | SQL statements | Checksum |
|---|---|---:|---|
| 76 | `library_authored_text_and_reference_adoptions` | 20 | `98d61e45aaf6b1268601db402102114ed57e330da231e5ef1c8302786cb59a51` |
| 77 | `library_practice_action_receipts` | 4 | `7700ba794d37be58630fcc82931a3061f7e41f75f4a4c82e540a7fbafa086af6` |

The unchanged 1–75 raw catalog hash is `0b65915a8926593f21dbd2881166fb1ddff2684aac6ccdf955750fa5c5dac479`. Canonical registration order differs from a workspace's actual physical application sequence: native migration matches entries by name. Genuine pre-mode copied histories can admit source76 at physical75 and receipt77 at physical76, then append the missing mode declaration at physical77 during an attested claim. Admission proves the exact named checksum/count/storage and its own bounded positive contiguous physical prefix; it does not allocate memory from an untrusted version number or depend on a later schema tail.

Losing later API77 admission holds public library reads/effects while an intact original native76 reference remains provable. Losing76 with surviving source/receipt history fails closed. A genuinely older workspace with no library admission, tables or audited births stays inert; empty installed library state adds no close obligation. Activated source problems appear as a global integrity prerequisite, without assigning a fictional financial posting period.

Copied/restored files remain read-only until the native attested ownership transition. Genuine75 history upgrades preserve native source/post/send proofs, journals, partial collections, original receipts and pending accounting reservations. Reopening a current copied77 diagnostic file preserves its bytes and initializes no accounting adapter. These preservation checks do not enable file-workspace library edits; this first writer remains owned-memory-only.

## Verification and remaining work

Evidence is separated by the actual source snapshot:

- Original library scratch backend: **246 unique tests**, 212.104 seconds, all 208 Python files unchanged. This preceded the later bounded-admission and reciprocal integration changes.
- Original Fluent scratch runtime: **75 settled views** at 1440/1024/390 px, three complete six-action journeys, 64 exact retries, 25 recovery checks and 43 contract checks; zero browser errors or automated accessibility violations. All 159 source hashes remained unchanged. This qualifies the original scratch bundle `library-practice-DxWxgGYV.js`.
- Selective library integration candidate, based on the then-current main: **294 unique tests**, 267.637 seconds, all 240 Python files unchanged and the original 1–75 hash exact. This includes genuine history/copy/rollback, bounded admission, reciprocal namespaces, all library layers and existing AR/commercial/accounting/close compatibility. It includes the later guard and reciprocal namespace fixes.

The original 246-test and GUI evidence describes its captured scratch source; the 294-test run is a separate focused integration snapshot. The main backend passes 2703 unique tests in 1703.859 seconds with zero failures, errors or skips; all 266 Python source/test hashes remain unchanged. The four main Fluent workflows and the separate nine-case recovery-remount check also pass on their captured runtime/UI/configuration/served-JavaScript snapshots. The two test expectation corrections retain exact original-to-current provenance. The main qualification does not enable operational staff use, deployment, licensed ingestion or enterprise readiness. Earlier source artifacts remain historical evidence and their overlapping test counts are not summed.

Company-wide cross-project libraries, licensed-content ingestion/distribution, PDFs/CAD, uploads/downloads, embeddings, external publication, signatures and operational staff identity remain later work. Adopted references confer no external legal or engineering authority. The existing [product goal](PRODUCT_GOAL.md) and [Fluent page guidelines](UI_OVERHAUL_SPEC.md) continue to govern the broader ERP design.

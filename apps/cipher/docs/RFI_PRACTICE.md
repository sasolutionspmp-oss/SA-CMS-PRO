# RFI practice workflow

Cipher's separate RFI practice entry connects an authored question and exact source citations to a proposed response, independent PM review, an official response and a separately reviewed local synthetic distribution. It runs in a fresh owned in-memory workspace with registered synthetic people. The contract is `cipher.rfi-practice.v1`; the API prefix is `/api/rfi-practice/v1/` and the default server port is **8771**.

This reference describes the implemented bounded workflow. The main backend passes 2703 unique tests in 1703.859 seconds with zero failures, errors or skips; all 266 Python source/test hashes remain unchanged. The four main Fluent workflows and the separate nine-case recovery-remount check also pass on their captured runtime/UI/configuration/served-JavaScript snapshots. The two test expectation corrections retain exact original-to-current provenance. It does not qualify engineering certification, outside delivery or operational staff identity.

## Nine fixed actions

Every effect uses `POST` under the API prefix. The server derives the person and current project duty from its scoped session; action bodies cannot select an actor, role, provider or accounting period.

| Action | Resource and route | Current own duty | Effect |
|---|---|---|---|
| `rfi.create` | Project: `projects/{id}/rfis` | Project staff | Record one question and its exact issued drawing/supporting citations. |
| `rfi.draftResponse` | RFI: `rfis/{id}/draft-response` | Project staff | Record a proposed response and informational impacts while the RFI remains open. |
| `rfi.requestResponse` | RFI: `rfis/{id}/request-response` | PM | Request review of the response and source packet. |
| `rfi.approveResponse` | Approval: `rfi-response-approvals/{id}/approve` | Independent PM | Grant the response authorization; the RFI remains open. |
| `rfi.applyResponse` | Approval: `rfi-response-approvals/{id}/apply` | PM | Consume that original grant and record the official answer. |
| `rfi.setDistribution` | RFI: `rfis/{id}/distribution-list` | PM | Record an authored fixed recipient list for an answered RFI. |
| `rfi.requestDistribution` | RFI: `rfis/{id}/request-distribution` | PM | Request separate review of the exact response, sources and recipient list. |
| `rfi.approveDistribution` | Approval: `rfi-distribution-approvals/{id}/approve` | Independent PM | Grant distribution authorization without creating a distribution. |
| `rfi.distribute` | Approval: `rfi-distribution-approvals/{id}/distribute` | PM | Consume that distribution grant and record one local synthetic mail-sink distribution. |

Creation accepts only `{subject,question,drawingRevisionIds,documentRevisionIds}`. Response drafting accepts only `{responseText,costImpact,scheduleImpactDays}`; `costImpact` is an exact nonnegative two-place decimal string or `null`, and days are a nonnegative integer or `null`. Recipient preparation accepts only `{recipients}`, containing distinct entries from the fixed `.invalid` practice list. The other six bodies are `{}`. The effect body adds only the review `fingerprint` to its fixed body. The codecs and route definitions are in [rfi_wire.py](../rfi_wire.py).

The native consequential operations remain `field.respond_rfi` and `field.distribute_rfi`. Their original command payload stays `{approval_id,operation,subject_id}` and their command ID stays `exec:{approval_id}`. There is no generic module-operation route or combined grant-and-apply route in this entry.

## Actual people and separate decisions

Project staff means a current active internal canonical human with their own current project membership. PM steps additionally require that person's own effective audited project PM grant. A delegated, wildcard, external or service identity cannot substitute for that duty. Fixture setup ownership supplies no PM override.

The response reviewer must be a different canonical person from **both** the proposed response's author and the approval requester. Another login for the same person does not create independence. The distribution reviewer must differ from its requester. An eligible current PM may explicitly apply a granted response or distribution; the requester may apply, and there is no universal third-person requirement. Requester and reviewer eligibility is rechecked before a pending authorization is used.

Granting records independent review only. Response grant leaves the native RFI `open`; application consumes the same grant and changes it to `answered`. Distribution grant creates no message. Its separate application writes one local `mail-sink` record. The available synthetic destinations are `engineer@synthetic-rfi.invalid`, `owner@synthetic-rfi.invalid` and `project-team@synthetic-rfi.invalid`.

## Original citations and current source disclosure

A drawing citation uses an actual issued drawing-register revision and its original qualified issue. It is not an arbitrary drawing document revision. An issued A revision can remain the valid cited source while a later working B revision exists. The presenter separately discloses the cited revision, current issued/working register state and current evidence head; it does not silently replace the original citation or infer engineering verification from a file hash.

Supporting citations use owned source revision proofs. Drawing-kind evidence must be cited through the issued drawing register, rather than passed as a supporting-document shortcut. New creation requires eligible current sources. Later source heads remain visible alongside the exact original question and citations. A fresh review may retain an original historical citation while explicitly reviewing the current source disclosure. It does not rewrite that original citation.

Current `project_use` permission is required for question creation, response drafts and recipient-list drafts. Official response and distribution authorization checks require allowed `distribution` rights on every cited document. Permission decisions are shown separately from original citation facts. A saved recipient list is authored preparation only: when project use is allowed but distribution rights are held, preparing the list does not clear that hold or authorize distribution.

Genuine changes to cited-source heads, relevant rights or actual project duties make outstanding grants stale. Completed original responses and distributions remain source-proved historical outcomes. Their original receipt does not become a claim about today's permission, source head or recipient list.

## Response, distribution and current state

The question, citation source, response drafts, recipient-list revisions and approval review contexts have immutable original records and audit births. Drafting another response on an open RFI increments its native version and invalidates every verified pending or granted approval on that RFI. Changing an answered RFI's recipient list likewise increments its version and invalidates open authorizations. Pure review discloses these invalidations before the action.

The official answer preserves its exact approved response and original grant consumption. Each synthetic distribution preserves its original response version, recipients, independent grant and applicator. A later legitimate recipient list or source revision changes the current view, while an exact completed retry still returns the original result and original receipt ID.

Potential cost and schedule impacts are **informational**. None of the nine actions creates a journal, AP/AR balance, change draft or execution, commitment, contract-value adjustment, budget adoption or schedule-baseline change. A local distribution is not evidence of outside delivery, customer receipt or an engineering stamp. The API explicitly labels these limits, including `externalDelivery: "not_attempted"` for a completed synthetic distribution.

## Reviews, receipts and recovery

Reviews perform no write and bind the exact typed body, current resource version, complete native source plan, original authorization where applicable, current rights, actual person/project duty and server-side manifest/governance. Effects require the original fingerprint, quoted `If-Match`, a UUID `Repeatability-Request-ID`, the scoped session and CSRF protection.

The action's source effect, grant consumption, native command cache/audit and API receipt share one SQLite savepoint. Exact row, schema and audit boundaries reject extra resource effects or financial changes. Caught nested failures, unexpected callbacks, late receipt faults, response assembly failures and failed COMMIT roll back the whole action. Only an independently verified stale/expiry terminal control may commit a refused receipt, with no partial official response or distribution.

Receipt storage freezes the exact invocation before its callback, then compares the returned row, actual stored row and expected original person, workspace, UUID, action, resource, body, fingerprint, `If-Match`, result and source. Canonical JSON comparisons retain exact integer and boolean types. Replays prove the original audited sources and native command result; they do not rerun fresh action eligibility against legitimate later states. The current caller's own duty and scope are still checked before any original outcome or shared-key history is disclosed.

Within one workspace, all AP actions, pending accounting invocations, commercial, owner-billing, library and RFI actions share the per-person UUID namespace. A key cannot be reused for another action, body or reviewed version. Namespace checks use pure local metadata/audit inventories; they do not initialize a provider or execute another module's action. Separate practice servers still own separate fresh workspaces and sessions.

A definitive `412` for a changed reviewed version permits refreshing the current source and obtaining a new review. A genuine later selected-source head produces this definitive stale-review response even when the old prospect is no longer eligible. Raw source or admission tampering remains an integrity hold. A timeout, dropped connection or other uncertain response must retain the **same** original body, UUID, `If-Match` and fingerprint for recovery. Retry that original request to recover its original receipt; an uncertain response is not a reason to invent a new request key or repeat a distribution as a new action.

Approval deadlines come from the native server policy. New requests compare their actual original deadline with the locked reviewed deadline, allowing only the observed native generation precision window, including genuine fractional precision. The client cannot select, extend or shorten expiry. Expired or stale authorizations require fresh review; their original request, grant and any terminal refusal history remains intact.

## Admission and source integrity

Actual schema **78**, `rfi_sources_and_review_contexts`, contains the four immutable source families `rfi_sources`, `rfi_response_revisions`, `rfi_distribution_revisions` and `rfi_approval_sources`. Its exact 16 SQL statements and explicit deferred registrar are defined in [domain/rfi_controls.py](../domain/rfi_controls.py). Statement checksum:

```text
020acd75e597729ca10d546ca95cc88445cfecac739e954c88e45fd0dc0fc327
```

Actual schema **79**, `rfi_practice_action_receipts`, contains `rfi_action_receipts` and its immutable update/delete/original-birth guards. Its exact four SQL statements and explicit registrar are defined in [rfi_receipts.py](../rfi_receipts.py). Statement checksum:

```text
548334226a4e85fc6c86531bed5cecbe3df6542d6f100e9f474927c9d498a18f
```

Importing these definitions does not register a placeholder or apply SQL. Registration appends after the genuine admitted predecessor catalog, preserving the exact earlier schema text, audit history, receipts and original native records. Existing unqualified legacy RFIs are not automatically attested as new owned-source RFIs during upgrade.

Admission checks use each exact **named** applied entry, checksum, statement count and bounded contiguous positive physical prefix through that entry. Canonical catalog ordinals 78/79 are not substituted for a historical database's actual named application positions. Raw maximum/minimum version tampering is refused without allocating a range from the untrusted number. Original schema 78 proof remains independent of a later schema 79 admission loss; the qualified RFI API and receipts require their own schema 79 admission.

Original audited births must agree with surviving headers, every source/revision row, native field history, approvals and consumed effects. Deleting a source/header or a later audited revision cannot make an older packet silently current. Source-only scope/header/birth projections preserve own-project integrity holds (`423`) and opaque foreign/hidden denial (`404`) before private details are loaded. Copied or restored files do not acquire practice write authority or become this memory-only entry.

## Build and run

The Python engine uses Python 3.12+ and the standard library. From the repository root, after installing the pinned web dependencies:

```bash
cd apps/cipher/web
npm ci
node node_modules/typescript/bin/tsc --noEmit
node node_modules/vite/bin/vite.js build --config vite.rfi.config.ts
cd ../../..
python -m apps.cipher rfi-practice-web --port 8771
```

Open `http://127.0.0.1:8771`. The separate entry owns a new synthetic memory workspace and does not select an operational/file workspace. The browser harness entry point is `node tests/rfi-smoke.mjs` from `apps/cipher/web`; its current main qualification is recorded in `../BUILD_STATUS.md`. Node and the Fluent build dependencies remain web tools, not Python engine dependencies.

## Verification evidence and scope

The following are distinct captured runs. Their modules overlap, so these counts must **not** be added together as a unique-test total. Evidence is retained under `/tmp/cipher-completion/cms-planning/` for this isolated candidate.

| Captured run | Result | Evidence |
|---|---|---|
| Source/native compatibility | 267 passed, 132.383s; 13 owned and 2 library predecessor hashes unchanged | `rfi-domain-native-final.log` / `.json` |
| Additional native close/AP-accounting compatibility | 60 passed, 54.265s; four runtime hashes unchanged | `rfi-close-accounting-final.log` / `.json` |
| Fixed actions and receipts | 24 passed, 33.268s; all 15 captured source hashes unchanged | `rfi-actions-24-final.log`, `rfi-actions-freeze.json` |
| Actual sessions and pure preflight | 15 passed, 9.038s | `rfi-root-source-freeze.json` and root focused qualification |
| Reciprocal shared request-key namespace | 45 passed, 32.831s | Root RFI/AR/commercial namespace qualification |
| Wire, scoped contract and actual HTTP | 40 passed, 28.076s; all 223 Python hashes unchanged, no duplicate test IDs | `rfi-http-final.log`, `rfi-http-final-result.json` |
| Genuine historical upgrade/admission | 23 passed, 25.757s; all 107 Python hashes unchanged | `RFI_UPGRADE_QUALIFICATION.md` and upgrade result artifacts |

The original interrupted 430-case log is retained. The same frozen scratch suite subsequently passed 430 unique cases in 317.502 seconds with unchanged captured sources. The main backend passes 2703 unique tests in 1703.859 seconds with zero failures, errors or skips; all 266 Python source/test hashes remain unchanged. The four main Fluent workflows and the separate nine-case recovery-remount check also pass on their captured runtime/UI/configuration/served-JavaScript snapshots. The two test expectation corrections retain exact original-to-current provenance. Scratch, focused integration and final main evidence are separate; their counts are not summed. These results do not claim live identity, customer delivery, engineering certification or enterprise readiness.
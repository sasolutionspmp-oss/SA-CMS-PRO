# Independent confirmation — DOC03 reviewer revalidation

Reviewed source at `a3577803e09e72b9af22178bdd9c4d1225536485` and the external harness/results on October 17, 2026. This review did not rerun tests, contact a database/runtime/provider, apply a patch, or modify workspace source.

## Confirmed finding

The harness faithfully reproduces the identified source-level failure with otherwise authorized, distinct Morgan/Jordan identities:

- Company adoption: `document_control/service.py:185` → `_prelock:55–58` → `locking.DocumentContext.hold:169`. The nested locking read is evaluated as Jordan while the active context belongs to Morgan; it raises `document_prelock_required` (409).
- Project transmittal: `document_control/governance.py:34` → `locking.recipient_read:246–247`. The same executor/reviewer identity mismatch rejects the recipient read.
- The actual reviewer-loop AST from `governance/approvals.py:475–488` catches that DomainError and replaces the outcome with `reviewer_authority_revoked` (403). This finding does not establish missing duties.

The retained `03` log reports six diagnostic controls passing; `04` retains both intended-success regressions failing with the matching 403 fingerprint. The corrected `06` log reports one diagnostic-patch control passing across both scenarios. The earlier `05` diagnostic fixture failure remains retained; it is not a passing functional regression. I reviewed these results, rather than executing them independently.

## Diagnostic patch and functional-fix boundary

`DIAGNOSTIC_ONLY_UNMASK.patch` only propagates existing `document_prelock_required` / `source_prelock_required` errors instead of masking them. It still refuses both operations; it supplies no functional fix, permission, lock admission, or successful approval execution.

Do not remove the active identity check, rebind/reset either context, borrow Morgan's provenance token, or globally change shared approval revalidation to `lock=False`. The supported direction is explicit reviewer read admission inside a verified complete union, followed by independent canonical source/native/rights checks as the actual reviewer. Reviewer identity/User and required target/origin duty rows—including Company-origin duties—must be included before the first master/source locks. `locking.py:137–153` currently prelocks executor and declared-recipient duties, not nonrecipient reviewer Company duties. `commands.py:64–68` participant Person/identity locks do not alone establish duty-row serialization: `DutyDocument.validate` (`controllers.py:35–44`) does not acquire a Person lock.

The harness's nonlocking-read controls show actual reviewer authority calls still reject revoked Company duties, denied native permission, revoked distribution rights and nonindependence, while the requester contexts remain unchanged. This is evidence supporting a narrowly admitted read helper, not proof that a blanket nonlocking change is safe.

## Evidence limits

Real exercised code includes current actor/scope authorization, DocumentContext discovery/prelock/hold, provenance prelocked context, rights admission, service foreign-source prelock, recipient checks, domain dispatch and documentary review. SQL/session/native permission, persistence/source adapters and issued-state projection are explicit host doubles. Only the reviewer loop is AST-extracted; the complete canonical command/transaction is not executed. Source bytes are synthetic text, not generated Company producer graphs. Context-token preservation therefore does not qualify generated-source authorization, native lock ordering, concurrent revocation/snapshot freshness, persistence or successful native execution. Those remain for the local fix owner and subsequent native qualification. No shared scope or locking rule was relaxed here.

## Reviewed hashes

The following hashes pin the reviewed external evidence and relevant source, not a fresh full-workspace integrity gate.

Source paths below are relative to `workspace/apps/cipher/platform/apps/cipher_aec/cipher_aec/`; evidence paths are relative to this task directory.

| File | SHA-256 |
|---|---|
| `BASE.json` | `dd25d5aa435703f6624fcaf4724200ddba7a0bb81e4759b107846d10234b52a6` |
| `test_revalidation_host.py` | `7488e972094b5687a707115f5d4ea509e56deddfaca208b349e7306bb9eb4b71` |
| `DIAGNOSTIC_ONLY_UNMASK.patch` | `a809fae3ebe788ff2ff9f523f4b2fe10730e5bb263700bffaf9d7ace6a8048da` |
| `03-diagnostic-controls.log` | `4f0b2de94ed43d29ada9aaf7e2f7e80690ddecd1016f49c00cb5b523cc088dd0` |
| `04-fail-first-regression.log` | `99dc35e073193a2187667b895ede2bfde4cd9065822e9e67906da7c018711519` |
| `05-diagnostic-only-patch.log` | `714569e3abfeb77d9b513394046beffdbac275f4c547b876a03595e3de956b0a` |
| `06-diagnostic-patch-fixture-corrected.log` | `5035b89950e904080b36bdfcbcfd8756fff0ef05d66abd63fb38ba77481d6436` |
| `governance/approvals.py` | `ba310965e993ab0ed38a02f74ccb0a400f3140a7c149b3086441cae6459f32ed` |
| `governance/commands.py` | `dad6d3b966ebcb2ca9ba5ad7ccbb0d0eaec5fa69736810465ca0160ee6b66bc1` |
| `governance/context.py` | `9e03274ef6096c21989d0d789768cd6f3a4917851f82cca575102d8eeae14ff0` |
| `governance/controllers.py` | `5904474140b712626ccb1c6530aa6311114708a3588c627651b67d1168a83c2a` |
| `governance/domain_approvals.py` | `1bdc70f74fcca0cc2bbeead275426bc6897592927ee4f0adf86547a2e8aadded` |
| `document_control/locking.py` | `76a7517e4190d6107e86732365f1ffa022a1ecd697e13793eef594350c815dec` |
| `document_control/service.py` | `7ff4bcde5a5f1df2728a875522172bbf798ddb473a9d1955a76d0c4c5782b7ca` |
| `document_control/governance.py` | `5724adccaddfd45febdbc4aa39edad56021cdc3a4f4897b5169993015ff76bd0` |
| `document_control/rights.py` | `7b2652e58de6926ee8aefceb079edb3a3a388c6891e6ec7849c02142c2f8aafd` |
| `document_control/shared.py` | `daffe41fa7023561b583f065277fe49de3f3faf474716a201893232f9b51bb45` |
| `documents/provenance.py` | `eeb2eace0e7d3499ad56128bb82f9c153933abb8132649bcaa2e209a58a0f1d0` |


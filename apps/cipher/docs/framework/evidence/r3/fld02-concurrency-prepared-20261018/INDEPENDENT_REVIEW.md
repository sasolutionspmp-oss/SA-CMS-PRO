# Independent source review — 2026-10-18

Disposition: no remaining blocking source finding identified for this prepared, bounded driver. **Native execution is UNRUN and native acceptance remains UNREVIEWED.** This review authorizes no runtime action or change to an existing hold.

The following exact source bytes were reviewed. A later source change requires a new review binding.

| File | SHA-256 |
| --- | --- |
| native_driver.py | d7af2e46f27a705fa3db71e3203856d948549b089963f1d2cf76bec19f012085 |
| native_worker.py | 3a59e107876bbd85cdadeea8f3ac3904e23e4212d82a372e51e496110be58d01 |
| inventory.py | 2ba5268cd95ea2b8dc941236a44753c441d07f559cb44faa4f36e1aada3f5db0 |
| lease.py | 3ce8cac31d29cab52e2f50b5a0352f2603463b3efcf17ec314d388105f7701b0 |

Review used direct source inspection, standard-library AST parsing of these four files, and read-only Git object comparisons. The reviewer did not import these modules, import Frappe or the custom application, run a native test, connect to a site/database/provider/model, install dependencies, execute HTTP requests, or change production source. Retained root logs report 31 pure guard tests and 13 pure driver tests passing; the reviewer read those results without rerunning them. The intentionally permissive failing-first guard scaffold is test evidence, not a product-native failing baseline.

`SOURCE_CONTRACTS.json` has SHA-256 `6b0973191c689e8a9dc2ac21fa5d0569b43ee192aebee1b206f9c7d0fa9f72a3`. All 52 listed source hashes and byte lengths were independently checked against the named public Git objects at C5 `4b884afa21ca1618bd47e2107d8212d261ecc1e9`. The relevant offline service, contracts, spec, records, repository, and native offline controller sources retain the frozen FLD02 implementation from `392a19f8c01b4253a5aaeaa99878408d394dc9cb`. C5 changes the offline API wrappers to check original request fields and composes the shared offline receipt authorization dispatch. Its additional quality/safety capability branches do not alter the reviewed field command signatures. The driver calls the native services directly and claims no HTTP coverage.

The review identified and rechecked these resolved issues:

- Apply admission now requires the exact SHA-256 capture version and canonical UUIDv4, with the stage operation UUID distinct from the business capture UUID. Request, body, scope, source, runtime, build, and epoch pins are checked again throughout the bounded admission.
- Callback inventory now uses the referenced Frappe 16.52.0 `CallbackManager._functions` storage. Unsupported callback values make inventory incomplete. Existing application bytecode is included in the full source closure; native package source/cache origins are checked before import, and helper modules are loaded from their source bytes.
- Both workers must complete their before inventories and pristine scenario checks before the parent releases the prepared barrier. Existing business receipts are refused as new trials; apply requires the exact existing staged capture/version. The parent checks distinct observed physical connection IDs and READ COMMITTED metadata.
- Authority changes use one exact existing, digest-pinned binding/duty document through its native controller. Scope includes the declared reassignment Person, and staged participants outside the explicit identity closure are refused. No users, devices, default duties, seed/reset procedures, or alternate field writers are created by the driver.
- Stage and apply results are compared to stored canonical JSON, request/result hashes, native scope, immutable revision/quantity facts, and the committed capture pointer. Only operation metadata is removed from result comparison. New apply headers must equal their current canonical header; historical headers remain separately retained.
- Children retain the parent's original serialized admission and deadline. A durable Person-plus-operation-UUID reservation survives run-ID/scope changes, and each worker consumes an exclusive start slot before native imports. Direct child reentry cannot replace an earlier attempt's journal and execute again.
- Commit intent is persisted before commit. Unknown or incomplete outcomes retain the reservation and evidence, without command retry, cleanup, or a replacement UUID. Explicit reconciliation uses a fresh process/connection under the original request and UUID and does not clear the attempt.
- The observer calls supported current-rights readers, which can take transactional row locks. It checks zero native transaction writes and unchanged callback inventories through its final canonical comparison. This is a no-write observation, not a database-enforced READ ONLY transaction.

Material limits remain. Source and pure guard checks cannot establish actual lock contention, transaction atomicity, restart behavior, controller permissions, commit outcomes, or native database qualification. Barrier release records coordinated attempts; actual overlap and allowed semantic changes require review of the resulting native evidence. The driver deliberately reports outcomes pending local-root review and does not accept its own trial.

The local-root runtime/build/epoch receipts are trusted operator inputs. The 52 public source references are not an installed-runtime attestation: a live trial must additionally pin the complete actual copied application and selected installed runtime, including existing bytecode, and supply matching private current receipts. Its stable private journal parent must be retained across attempts; choosing another journal parent or removing evidence is outside this driver's reservation boundary.

Inventories cover the selected bounded native records, File bytes, receipts, and supported callbacks. Exceeding a bound or encountering an unsupported value leaves incomplete evidence. Canonical receipt absence cannot prove that an uncertain commit did not occur; revoked current rights can also leave receipt reads unavailable. Such cases remain retained for explicit reconciliation under the original UUID. No award or finance hold was changed or qualified by this work.

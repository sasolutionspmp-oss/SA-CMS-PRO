# Cloud preservation retrieval

This ref is incomplete WIP, not a sandbox release. Use the Project candidate for integration. No current-WIP test/type/build/native pass is claimed. Generated wire files are stale relative to later backend changes. Do not run lifecycle hooks as a completed feature.

## Source refs

- Repository: https://github.com/sasolutionspmp-oss/SA-CMS-PRO
- Base: `f79df23af5bdb1c8cccf538241452bef2c459672`.
- Reviewed Project candidate: `cipher/preserve-doc03-project-20261017`, commit `d03bce8d0116ad39a505f4bb3a57cdec672b9e47`.
- Paused successor: `cipher/preserve-doc03-successor-wip-20261017`, descends from that candidate. Its final remote SHA is supplied in the external publication receipt after readback.

The current WIP tree composes exactly the 55 successor changes onto the candidate; its 914-file inventory is `COMPOSED_WIP_SOURCE_INVENTORY.json`. The 9 newer CI/engineering-wire paths and 11 handwritten UI paths have no overlap with those changes. Original successor metadata in `successor-originals/` refers to its earlier 904-file source tree and 880-file parent, not to this composed tree. Historical nine clause and six Company passes precede later incomplete edits; they do not qualify this checkout.

## Retrieve original snapshots and evidence

Fetch the WIP ref into a sparse checkout that includes `apps/cipher/docs/framework/evidence/cloud-preservation-20261017`. Files under `archive-parts/` are exact binary chunks, not Git LFS pointers. `ARCHIVES.json` records each part's length/SHA256, concatenation order and complete archive SHA256. Check those hashes before extracting.

Concatenate an archive's parts in the order listed in `archive-parts/ARCHIVES.json`, without decoding or modifying them. For example:

```sh
cat archive-parts/doc03-original-backend-source.tar.gz.part-* > /path/to/empty-transfer/doc03-original-backend-source.tar.gz
sha256sum /path/to/empty-transfer/doc03-original-backend-source.tar.gz
```

Extract each archive into a different empty directory. `archive-manifests/*.manifest.json` pins every member's uncompressed bytes and SHA256. No absolute or parent-relative tar paths are used.

| Archive | Exact retained content |
| --- | --- |
| doc03-original-backend-source.tar.gz | Original 880-file Project backend workspace |
| doc03-project-candidate-source.tar.gz | Combined 890-file Project backend/UI candidate |
| doc03-successor-wip-source-and-handoff.tar.gz | Original paused 904-file successor plus boundaries, contracts, logs and hash inventories |
| doc03-project-dist.tar.gz | Original 931-file production build; application source unchanged during later test-only continuations |
| doc03-reports-traces-and-handoff.tar.gz | Original backend/UI reports, logs, raw browser traces/error contexts, handoffs, frozen metadata, both hosted engineering success logs and original active journal |

Browser evidence uses explicit RPC contract fixtures and is not native UI evidence. Hosted engineering receipts qualify only their exact engineering commits. No new native DOC-03 run is scheduled by preservation. Main and isolated runtimes were not changed or restarted.

`EVIDENCE_SHA256.json` pins all files in this evidence subtree except itself. `successor-originals/HANDOFF.md` describes incomplete work and `QUALIFICATION.json` ties historical results to their source phase. Absolute cloud paths in historical records identify their former locations; use these copied files/archive members after transfer. Helper scripts are preserved forensic records, may be non-idempotent, and must not be replayed blindly.

Excluded: live credentials, runtime configuration, database volumes, dependency caches, node_modules and model weights. Dependencies should be restored from pinned manifests. The local coordinator owns sandbox packaging/integration. Continue original dependencies and retain the blocked award boundary; this transfer performs no award or deployment action.

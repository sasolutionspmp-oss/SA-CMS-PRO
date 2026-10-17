# Cloud preservation handoff — October 17, 2026

Repository: https://github.com/sasolutionspmp-oss/SA-CMS-PRO

Base: `f79df23af5bdb1c8cccf538241452bef2c459672`.

Fetch `cipher/preserve-doc03-project-20261017` for the reviewed Project document-control candidate. This ref adds the 82 source changes, retained qualification, unpublished engineering native-CI receipts and [sandbox delivery plan](SANDBOX_ACCELERATION_PLAN.md). The existing framework/PR branch is deliberately not advanced during this preservation-only handoff, so preservation does not schedule another hosted suite.

Use [DOCUMENT_CONTROL_DOC03.md](DOCUMENT_CONTROL_DOC03.md) and [candidate evidence](evidence/r3/document-control-doc03-source/README.md). The 890-file source inventory and 931-file build inventory bind the candidate. All 30 distinct focused cases passed across the original run and named continuations; a fresh native DOC-03 installation, actual native UI and complete package acceptance remain open.

Fetch `cipher/preserve-doc03-successor-wip-20261017` only to recover unfinished work and archived evidence. It descends from the Project candidate and overlays the successor's 55 exact delta paths relative to the 880-file backend parent. This retains the newer engineering CI/wire correction and handwritten Project UI. Its generated wire files are stale relative to later backend edits. It is not a runnable release or sandbox baseline.

The WIP ref contains `apps/cipher/docs/framework/evidence/cloud-preservation-20261017/` with:

- The original 904-file successor inventory, 55-path delta, historical qualifications, approved boundary, intermediate clause contract and forensic helper scripts.
- Compressed exact source snapshots of the original backend, combined Project candidate and paused successor.
- The retained compiled Project UI and original backend/UI reports, browser traces, hosted engineering success logs and active cloud journal.
- Archive member SHA256 inventories, full evidence-file hashes and instructions for retrieving each snapshot. Originals are retained unchanged; historical absolute paths identify the former cloud locations.

The externally returned publication receipt supplies full remote commit SHAs after readback. Fetch the named ref, record its SHA, and verify the referenced manifests before copying any artifact. Extract each archive into a separate empty directory. Archived helper scripts are forensic records and may be non-idempotent; do not replay them blindly.

Continue the original dependency order. Local sandbox packaging and integration belong to the local coordinator. Cloud preservation performs no deployment, install, runtime restart, model/provider connection or award action. The blocked award boundary remains in force on every machine. Live credentials, runtime configuration, database volumes, dependency caches and executable model weights are excluded from these Git refs.

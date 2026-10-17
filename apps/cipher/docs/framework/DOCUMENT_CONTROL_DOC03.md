# Project document control — DOC-03

This candidate implements the Project portion of the original DOC-03/C20 package. It is ready for local integration and human trial preparation; it has not been installed or qualified through the native UI on the preserved cloud runtimes.

The unified SAP UI5 workspace supports content permissions with dated evidence, immutable library revisions, independently reviewed Project adoptions, issued sets, internal transmittals and reported acknowledgments. Existing Document Revision/File storage retains the actual source bytes. A newer library or working-document revision does not replace an earlier adoption's source.

Three independent approval actions authorize adoption, documentary issue and internal distribution. The client preserves the server's full approval hash and validates the exact subject, sources, effect, requester and prior decision history. Lost or mismatched replies retain the original actor and operation UUID for recovery. Access loss clears scoped records and authoring state. Rights declarations do not verify legal licensing; internal distribution and reported execution evidence do not perform external delivery, signing, sealing or commercial contract execution.

The API lives in `cipher_aec.document_control.api`; generated `Dc*` client types describe its requests and responses. The [original backend handoff](evidence/r3/document-control-doc03-source/originals/HANDOFF.md) records the detailed contracts, permissions, bounded reads and remaining scope. Its typecheck/UI status describes the earlier backend freeze; the [combined qualification](evidence/r3/document-control-doc03-source/QUALIFICATION.json) supersedes those pending UI markers.

Qualification retained from the implementation work:

- 183 affected backend host checks, including 31 new DOC-03 cases and 152 compatibility cases; 16 generated contract checks.
- Integrated typecheck and production build passed; the build contains 931 files.
- 30 distinct adapter/browser fixture checks passed across the initial run and targeted continuations. This is a composed result, not a fresh all-pass run. Original failures, reports and error contexts remain available.
- The declared native Frappe workflow is unexecuted locally. Hosted qualification for this new candidate and actual native UI screenshots remain pending. The preceding successful engineering CI does not qualify changed DOC-03 source.

The [source freeze](evidence/r3/document-control-doc03-source/MANIFEST.json) binds 890 source files and 82 changed paths beyond `f79df23af5bdb1c8cccf538241452bef2c459672`. [Evidence and limits](evidence/r3/document-control-doc03-source/README.md) identify the retained originals and source/build hash inventories.

Remaining original DOC-03 scope includes Company/global reuse, Clause Use/Redline lineage and withdrawal/supersession lifecycle projections. Its separate successor snapshot is unfinished WIP and must not be installed as the reviewed Project candidate. Continue the original dependency order. The blocked award boundary remains in force.

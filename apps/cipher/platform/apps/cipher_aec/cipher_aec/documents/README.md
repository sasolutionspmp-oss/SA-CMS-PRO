# Documents: R0 source evidence

The canonical Frappe `Cipher Document` has a company/project-scoped metadata head. Each `Cipher Document Revision` stores an immutable private `File` reference, SHA-256, byte length, MIME type, scan/quarantine state and bounded page text. Uploads persist real original bytes; extraction, previews and search never substitute metadata for a missing original. Revisions retain exact source/page/excerpt checksums. Current user identity and project duty are checked before page content, bytes or replay receipts are returned.

`documents.api` exposes `upload_document`, `list_documents`, `get_document`, `preview_revision`, `search_documents`, `get_citation` and `download_revision`. These are Frappe session RPCs using the shared versioned transport. Upload is POST with a UUID v4 operation ID, declared byte count, SHA-256 and base64 original; later revisions include `document_id` and integer `expected_revision`. Shared governance commands supply the person-scoped transactional replay receipt. Other calls are GET; download produces an attachment instead of a JSON envelope. Files are limited to 10 MiB UTF-8 text or PDF. Preview output is page-scoped plain text and must be rendered as a text node in the UI.

There is **no antivirus scanner, OCR, semantic index, remote object store or production storage qualification** in this slice. Default uploads are quarantined. Explicitly synthetic development sites can set both `cipher_site_mode=synthetic` and `cipher_allow_unscanned_documents=1` to permit structurally validated, safely extracted `not_scanned` sources; this never reports a clean scan. Turning the allowance off blocks previously allowed unscanned bytes and citations too. PDF parsing runs in a bounded subprocess and rejects encrypted/active PDFs. Image-only PDFs report `ocr_unavailable`. Original files always download as attachments; native private File URL and ZIP routes are closed for canonical sources because native Frappe owner shortcuts otherwise bypass current project duties.

Integration hooks required from the app are document/revision/File query and read permissions, File validate/delete guards, `extend_doctype_class` File mixin, the native ZIP RPC override and `documents.install.after_migrate` unique revision-sequence index. `documents.service` is the single current-scope source retrieval interface used by Ricky and HTTP. No model endpoint or embedding capability is assumed.

Verification from repository root:

```sh
PYTHONPATH=apps/cipher/platform/apps/cipher_aec python -m unittest cipher_aec.tests.test_documents -v
```

These independent invariant tests use real filesystem bytes and real PDF parser subprocesses, with test-only metadata doubles. They cover scope revocation, wrong company, quarantine/policy revocation, source/excerpt checksum failures, missing bytes, immutable revisions, stale heads, immutable/path-safe storage, PDF page facts and active-PDF rejection. They are not evidence of a running Frappe deployment; actual site HTTP/restart/browser evidence is tracked by the integration gate.

The internal `documents.service.source_reference(company, project, revision_id, page, actor=None, *, lock=False)` supplies exact validated original bytes and server-derived revision, page, checksum, length and current-head facts to takeoff. `lock=True` follows an existing governed command's Person/Project locks and locks the current Document before its immutable Revision. Historical revisions remain readable with `is_current=False`; a consumer creating current calibration must reject that standing explicitly. No geometry, company scope or new public byte endpoint is inferred by this helper.

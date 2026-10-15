"""Append-only source revision and its bounded extraction snapshot."""
import json
import re
import frappe
from frappe.model.document import Document
from cipher_aec.governance.context import require_trusted_write
from cipher_aec.documents.extraction import MAX_BYTES, MAX_PAGES, MAX_PAGE_CHARS, MAX_TEXT_CHARS
from cipher_aec.documents.storage import FrappeFileStorage


class CipherDocumentRevision(Document):
    def validate(self):
        require_trusted_write()
        if not self.is_new():
            frappe.throw("Document revisions are immutable; upload a new revision.")
        parent = frappe.db.get_value("Cipher Document", self.document,
                                     ["company", "project", "revision_number"], as_dict=True)
        if not parent or parent.company != self.company or parent.project != self.project or self.revision_number != parent.revision_number + 1:
            frappe.throw("Document revision must preserve its parent scope and sequence.")
        if self.mime_type not in {"text/plain", "application/pdf"} or not re.fullmatch(r"[a-f0-9]{64}", self.sha256 or "") or not 0 < self.byte_length <= MAX_BYTES:
            frappe.throw("Invalid source metadata.")
        file_doc = frappe.db.get_value("File", self.storage_reference,
                                      ["is_private", "attached_to_doctype", "attached_to_name"], as_dict=True)
        if not file_doc or not file_doc.is_private or file_doc.attached_to_doctype != self.doctype or file_doc.attached_to_name != self.name:
            frappe.throw("Source must identify a private File attached to this exact revision.")
        FrappeFileStorage().read(self.storage_reference, self.sha256, self.byte_length)
        try:
            pages = json.loads(self.pages_json)
            valid = (isinstance(pages, list) and len(pages) == self.page_count <= MAX_PAGES
                     and all(isinstance(p, str) and len(p) <= MAX_PAGE_CHARS for p in pages)
                     and sum(map(len, pages)) <= MAX_TEXT_CHARS)
        except (ValueError, TypeError):
            valid = False
        if not valid:
            frappe.throw("Invalid page extraction snapshot.")
        if self.retrieval_status == "available":
            unscanned_allowed = frappe.conf.get("cipher_site_mode") == "synthetic" and frappe.conf.get("cipher_allow_unscanned_documents") in (1, True, "1")
            if not (self.scan_status == "clean" or unscanned_allowed and self.scan_status == "not_scanned") or self.extraction_status not in {"ready", "ocr_unavailable"}:
                frappe.throw("Quarantined source cannot become available.")

    def on_trash(self):
        frappe.throw("Source revisions cannot be deleted through ordinary operations.")

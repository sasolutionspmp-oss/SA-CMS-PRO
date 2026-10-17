"""Append-only source revision and its bounded extraction snapshot."""
import json
import re
import frappe
from frappe.model.document import Document
from cipher_aec.governance.context import require_trusted_write
from cipher_aec.documents.extraction import (
    MAX_BYTES, MAX_PAGES, MAX_PAGE_CHARS, MAX_TEXT_CHARS,
    EXTRACTOR_VERSION, IMAGE_MIME_TYPES, IMAGE_VALIDATOR_VERSION, validate_source,
)
from cipher_aec.documents.storage import FrappeFileStorage
from cipher_aec.documents.scope import scope_of


class CipherDocumentRevision(Document):
    def validate(self):
        require_trusted_write()
        scope_of(self.as_dict())
        from cipher_aec.documents.provenance import binding
        binding(self.as_dict())
        from cipher_aec.documents.preparation import require_preparation
        require_preparation(self.as_dict(), revision=True)
        if not self.is_new():
            frappe.throw("Document revisions are immutable; upload a new revision.")
        parent_fields = ["company", "project", "scope_type", "revision_number"]
        parent_fields.extend(key for key in ("producer_kind", "producer_reference", "producer_input_digest", "producer_binding_json") if frappe.db.has_column("Cipher Document", key))
        parent = frappe.db.get_value("Cipher Document", self.document, parent_fields, as_dict=True)
        if not parent or parent.company != self.company or parent.project != self.project or parent.scope_type != self.scope_type or type(self.revision_number) is not int or self.revision_number != parent.revision_number + 1:
            frappe.throw("Document revision must preserve its parent scope and sequence.")
        if any((parent.get(key) or None) != (self.get(key) or None) for key in ("producer_kind", "producer_reference", "producer_input_digest", "producer_binding_json")):
            frappe.throw("Revision producer bindings must equal the immutable parent binding.")
        if parent.producer_kind and (self.revision_number != 1 or self.mime_type != "application/pdf"):
            frappe.throw("Prepared outputs require one immutable PDF revision.")
        if (type(self.mime_type) is not str or self.mime_type not in {"text/plain", "application/pdf"} | IMAGE_MIME_TYPES
                or type(self.sha256) is not str or not re.fullmatch(r"[a-f0-9]{64}", self.sha256)
                or type(self.byte_length) is not int or not 0 < self.byte_length <= MAX_BYTES):
            frappe.throw("Invalid source metadata.")
        file_doc = frappe.db.get_value("File", self.storage_reference,
                                      ["is_private", "attached_to_doctype", "attached_to_name"], as_dict=True)
        if not file_doc or not file_doc.is_private or file_doc.attached_to_doctype != self.doctype or file_doc.attached_to_name != self.name:
            frappe.throw("Source must identify a private File attached to this exact revision.")
        content = FrappeFileStorage().read(self.storage_reference, self.sha256, self.byte_length)
        if validate_source(content, self.filename, self.byte_length, self.sha256) != self.mime_type:
            frappe.throw("Source MIME type must match its original bytes and filename.")
        try:
            pages = json.loads(self.pages_json)
            valid = (type(self.page_count) is int and isinstance(pages, list) and len(pages) == self.page_count <= MAX_PAGES
                     and all(isinstance(p, str) and len(p) <= MAX_PAGE_CHARS for p in pages)
                     and sum(map(len, pages)) <= MAX_TEXT_CHARS)
        except (ValueError, TypeError):
            valid = False
        if not valid:
            frappe.throw("Invalid page extraction snapshot.")
        if (type(self.scan_status) is not str or self.scan_status not in {"not_scanned", "clean", "infected", "unavailable"}
                or type(self.retrieval_status) is not str or self.retrieval_status not in {"quarantined", "available"}
                or type(self.extraction_status) is not str or self.extraction_status not in {"ready", "ocr_unavailable", "unavailable", "limits_exceeded", "blocked", "image_text_unavailable"}):
            frappe.throw("Invalid source status.")
        if self.scan_status == "infected" or self.extraction_status == "blocked":
            valid_extraction = (self.scan_status == "infected" and self.extraction_status == "blocked"
                                and self.extractor_version == "none" and not pages and self.retrieval_status == "quarantined")
        elif self.mime_type in IMAGE_MIME_TYPES:
            # The one empty page locates the retained original; it is never OCR.
            valid_extraction = (self.extraction_status == "image_text_unavailable" and pages == [""]
                                and self.extractor_version == IMAGE_VALIDATOR_VERSION)
        else:
            valid_extraction = (self.extractor_version == EXTRACTOR_VERSION and (
                self.extraction_status == "ready" and bool(pages) and (self.mime_type == "text/plain" or any(p.strip() for p in pages))
                or self.extraction_status == "ocr_unavailable" and self.mime_type == "application/pdf" and bool(pages) and not any(p.strip() for p in pages)
                or self.extraction_status in {"unavailable", "limits_exceeded"} and not pages
                   and (self.mime_type == "application/pdf" or self.extraction_status == "limits_exceeded")))
        if not valid_extraction:
            frappe.throw("Extraction metadata must match the source format and scan status.")
        if self.retrieval_status == "available":
            unscanned_allowed = frappe.conf.get("cipher_site_mode") == "synthetic" and frappe.conf.get("cipher_allow_unscanned_documents") in (1, True, "1")
            if not (self.scan_status == "clean" or unscanned_allowed and self.scan_status == "not_scanned") or self.extraction_status not in {"ready", "ocr_unavailable", "image_text_unavailable"}:
                frappe.throw("Quarantined source cannot become available.")

    def on_trash(self):
        frappe.throw("Source revisions cannot be deleted through ordinary operations.")

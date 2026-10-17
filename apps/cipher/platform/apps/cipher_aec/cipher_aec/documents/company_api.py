"""Explicit Company document RPCs backed by the same canonical revisions/File bytes."""
import base64
import binascii
import frappe
from cipher_aec.api.contracts import text
from cipher_aec.api.errors import DomainError
from cipher_aec.api.transport import endpoint
from . import service
from .extraction import MAX_BYTES


def _integer(value, name, default=None):
    if value is None and default is not None:
        return default
    try:
        if isinstance(value, bool) or str(int(value)) != str(value):
            raise ValueError
        return int(value)
    except (ValueError, TypeError):
        raise DomainError("invalid_input", f"{name} must be an integer.") from None


def _company_request():
    # The endpoint namespace supplies ownership. An omitted Project on an old
    # Project route and a caller-supplied discriminator never become authority.
    if getattr(frappe.local, "request", None) and {"project", "scope_type"}.intersection(frappe.form_dict or {}):
        raise DomainError("invalid_scope", "Company document routes do not accept Project or scope overrides.", 422)


@endpoint(methods=["POST"])
def upload_document(company, title, filename, content_base64, sha256, byte_length, operation_id,
                    document_id=None, expected_revision=None):
    _company_request()
    if not isinstance(content_base64, str) or len(content_base64) > 4 * ((MAX_BYTES + 2) // 3):
        raise DomainError("artifact_too_large", "Source must contain no more than 10 MiB.", 413)
    try:
        content = base64.b64decode(content_base64, validate=True)
    except (binascii.Error, ValueError):
        raise DomainError("invalid_artifact", "Source must contain valid base64 bytes.") from None
    return service.upload_company_document(company=text(company, "Company"), title=title,
        filename=filename, content=content, byte_length=_integer(byte_length, "Byte length"), sha256=sha256,
        operation_id=operation_id, document_id=text(document_id, "Document", required=False) or None,
        expected_revision=_integer(expected_revision, "Expected revision") if expected_revision is not None else None)


@endpoint(methods=["GET"])
def list_documents(company):
    _company_request()
    return service.list_company_documents(text(company, "Company"))


@endpoint(methods=["GET"])
def get_document(company, document_id):
    _company_request()
    return service.get_company_document(text(company, "Company"), text(document_id, "Document"))


@endpoint(methods=["GET"])
def preview_revision(company, revision_id, page=1):
    _company_request()
    return service.preview_company_revision(text(company, "Company"), text(revision_id, "Revision"), _integer(page, "Page"))


@endpoint(methods=["GET"])
def search_documents(company, query, limit=8):
    _company_request()
    return {"items": service.search_company_documents(text(company, "Company"), query, _integer(limit, "Limit"))}


@endpoint(methods=["GET"])
def get_citation(company, revision_id, page, excerpt_sha256=None):
    _company_request()
    return service.get_company_citation(text(company, "Company"), text(revision_id, "Revision"), _integer(page, "Page"), excerpt_sha256)


@endpoint(methods=["GET"])
def download_revision(company, revision_id):
    _company_request()
    revision, content = service.download_company_revision(text(company, "Company"), text(revision_id, "Revision"))
    # Attachment only: all browser previews use page-scoped text, never active source HTML/PDF.
    frappe.local.response.update({"type": "download", "filename": revision["filename"], "filecontent": content,
                                  "content_type": revision["mime_type"], "display_content_as": "attachment"})
    frappe.local.response_headers.update({"X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store"})

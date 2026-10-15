"""Authenticated same-origin document RPCs; source bytes never cross model APIs."""
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


@endpoint(methods=["POST"])
def upload_document(company, project, title, filename, content_base64, sha256, byte_length, operation_id,
                    document_id=None, expected_revision=None):
    if not isinstance(content_base64, str) or len(content_base64) > 4 * ((MAX_BYTES + 2) // 3):
        raise DomainError("artifact_too_large", "Source must contain no more than 10 MiB.", 413)
    try:
        content = base64.b64decode(content_base64, validate=True)
    except (binascii.Error, ValueError):
        raise DomainError("invalid_artifact", "Source must contain valid base64 bytes.") from None
    return service.upload_document(company=text(company, "Company"), project=text(project, "Project"), title=title,
        filename=filename, content=content, byte_length=_integer(byte_length, "Byte length"), sha256=sha256,
        operation_id=operation_id, document_id=text(document_id, "Document", required=False) or None,
        expected_revision=_integer(expected_revision, "Expected revision") if expected_revision is not None else None)


@endpoint(methods=["GET"])
def list_documents(company, project):
    return service.list_documents(text(company, "Company"), text(project, "Project"))


@endpoint(methods=["GET"])
def get_document(company, document_id):
    return service.get_document(text(company, "Company"), text(document_id, "Document"))


@endpoint(methods=["GET"])
def preview_revision(company, revision_id, page=1):
    return service.preview_revision(text(company, "Company"), text(revision_id, "Revision"), _integer(page, "Page"))


@endpoint(methods=["GET"])
def search_documents(company, project, query, limit=8):
    return {"items": service.search_documents(text(company, "Company"), text(project, "Project"), query, _integer(limit, "Limit"))}


@endpoint(methods=["GET"])
def get_citation(company, revision_id, page, excerpt_sha256=None):
    return service.get_citation(text(company, "Company"), text(revision_id, "Revision"), _integer(page, "Page"), excerpt_sha256)


@endpoint(methods=["GET"])
def download_revision(company, revision_id):
    revision, content = service.download_revision(text(company, "Company"), text(revision_id, "Revision"))
    # Attachment only: all browser previews use page-scoped text, never active source HTML/PDF.
    frappe.local.response.update({"type": "download", "filename": revision["filename"], "filecontent": content,
                                  "content_type": revision["mime_type"], "display_content_as": "attachment"})
    frappe.local.response_headers.update({"X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store"})

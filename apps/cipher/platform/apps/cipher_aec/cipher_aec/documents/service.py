"""Shared permission boundary consumed by UI, workers and Ricky tools."""
from __future__ import annotations

from .core import DocumentService
from .extraction import ArtifactError, validate_source
from .repository import FrappeDocumentRepository
from .storage import FrappeFileStorage

CAPABILITIES = {"antivirus": False, "ocr": False, "formats": ["text/plain", "application/pdf"],
                "semantic_search": False, "storage": "frappe-private-file"}


def _service(actor=None):
    import frappe
    from cipher_aec.governance.context import current_actor, require_project
    actor = actor or current_actor()
    return DocumentService(FrappeDocumentRepository(), FrappeFileStorage(),
                           lambda company, project, ability: require_project(company, project, ability=ability, actor=actor),
                           allow_unscanned=frappe.conf.get("cipher_site_mode") == "synthetic" and frappe.conf.get("cipher_allow_unscanned_documents") in (1, True, "1"))


def _call(callback):
    from cipher_aec.api.errors import DomainError
    try:
        return callback()
    except ArtifactError as exc:
        if "outside the requested scope" in str(exc):
            raise DomainError("not_found", "This source is not available.", 404) from None
        code = "revision_conflict" if "revision changed" in str(exc) else "artifact_unavailable" if any(s in str(exc) for s in ("quarantined", "unavailable", "integrity", "checksum does not match this page")) else "invalid_artifact"
        status = 412 if code == "revision_conflict" else 409 if code == "artifact_unavailable" else 422
        raise DomainError(code, str(exc), status) from None


def upload_document(*, company, project, title, filename, content, byte_length, sha256, operation_id,
                    document_id=None, expected_revision=None):
    from cipher_aec.governance.commands import run_command
    # Cheap integrity validation precedes the transaction and subprocess extraction.
    _call(lambda: validate_source(content, filename, byte_length, sha256))
    payload = {"title": title, "filename": filename, "byte_length": byte_length, "sha256": sha256.lower(),
               "document_id": document_id, "expected_revision": expected_revision}
    def effect(actor, project_doc):
        result = _call(lambda: _service(actor).upload(company=company, project=project, title=title,
                    filename=filename, content=content, byte_length=byte_length, sha256=sha256,
                    document_id=document_id, expected_revision=expected_revision))
        from cipher_aec.governance.history import append_event
        result["history_id"] = append_event(actor=actor, company=company, project=project,
                    event="document.revision.created", subject_type="Cipher Document Revision",
                    subject_id=result["revision"]["id"], operation_id=operation_id,
                    details={"document_id": result["document"]["id"], "title": result["document"]["title"],
                             "revision_number": result["revision"]["revision_number"]})
        return result
    return run_command(company=company, project=project, operation_id=operation_id, command="document.upload.v1",
                       payload=payload, ability="document.write", effect=effect)


def list_documents(company, project, actor=None):
    return _call(lambda: {"items": _service(actor).list(company, project), "capabilities": CAPABILITIES})


def get_document(company, document_id, actor=None):
    return _call(lambda: _service(actor).detail(company, document_id))


def preview_revision(company, revision_id, page=1, actor=None):
    return _call(lambda: _service(actor).preview(company, revision_id, page))


def download_revision(company, revision_id, actor=None):
    return _call(lambda: _service(actor).download(company, revision_id))


def search_documents(company, project, query, limit=8, actor=None):
    return _call(lambda: _service(actor).search(company, project, query, limit))


def get_citation(company, revision_id, page, excerpt_sha256=None, actor=None):
    return _call(lambda: _service(actor).citation(company, revision_id, page, excerpt_sha256))



def source_reference(company, project, revision_id, page, actor=None, *, lock=False):
    """Internal canonical source bytes/facts, including explicit historical standing.

    Effects call with lock=True after the shared actor/Project command lock. No
    PDF geometry, OCR fact or current-calibration entitlement is inferred here.
    This function is deliberately not an HTTP/model tool endpoint.
    """
    from cipher_aec.governance.context import current_actor, require_project
    actor = actor or current_actor()
    require_project(company, project, ability="document.read", actor=actor, lock=lock)
    return _call(lambda: _service(actor).source_reference(company, project, revision_id, page, lock=lock))

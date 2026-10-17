"""Shared permission boundary consumed by UI, workers and Ricky tools."""
from __future__ import annotations

from .core import DocumentService
from .extraction import ArtifactError, validate_source
from .repository import FrappeDocumentRepository
from .storage import FrappeFileStorage

CAPABILITIES = {"antivirus": False, "ocr": False, "formats": ["text/plain", "application/pdf"],
                "semantic_search": False, "storage": "frappe-private-file"}


def _service(actor=None, *, scope_type="Project"):
    import frappe
    from cipher_aec.governance.context import current_actor, require_project, require_company
    actor = actor or current_actor()
    authorize = (lambda company, project, ability: require_project(company, project, ability=ability, actor=actor)) if scope_type == "Project" else (lambda company, project, ability: require_company(company, ability=ability, actor=actor))
    from .provenance import authorize as authorize_source
    return DocumentService(FrappeDocumentRepository(scope_type), FrappeFileStorage(), authorize, scope_type=scope_type, source_authorize=lambda row, lock=False: authorize_source(row, actor, lock=lock),
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
        if document_id:
            from cipher_aec.document_control.rights import require as require_rights
            from cipher_aec.document_control.rights import prelock as prelock_rights
            prelock_rights([document_id],company,project,actor)
            require_rights(document_id,company,project,'ingest',actor,lock=True,required=False)
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


def _company_call(callback):
    from cipher_aec.api.errors import DomainError
    try:
        return _call(callback)
    except DomainError as error:
        if error.status == 404:
            raise DomainError("not_found", "This source is not available.", 404) from None
        raise


def upload_company_document(*, company, title, filename, content, byte_length, sha256, operation_id,
                            document_id=None, expected_revision=None):
    from cipher_aec.governance.commands import run_company_command
    _company_call(lambda: validate_source(content, filename, byte_length, sha256))
    payload = {"title": title, "filename": filename, "byte_length": byte_length, "sha256": sha256.lower(),
               "document_id": document_id, "expected_revision": expected_revision}
    def effect(actor, company_doc):
        result = _company_call(lambda: _service(actor, scope_type="Company").upload(company=company, project=None, title=title,
                    filename=filename, content=content, byte_length=byte_length, sha256=sha256,
                    document_id=document_id, expected_revision=expected_revision))
        from cipher_aec.governance.history import append_company_event
        result["history_id"] = append_company_event(actor=actor, company=company,
                    event="document.revision.created", subject_type="Cipher Document Revision",
                    subject_id=result["revision"]["id"], operation_id=operation_id,
                    details={"document_id": result["document"]["id"], "title": result["document"]["title"],
                             "revision_number": result["revision"]["revision_number"]})
        return result
    return run_company_command(company=company, operation_id=operation_id, command="document.upload.v1",
                               payload=payload, ability="document.write", effect=effect)


def list_company_documents(company, actor=None):
    return _company_call(lambda: {"items": _service(actor, scope_type="Company").list(company, None), "capabilities": CAPABILITIES})


def get_company_document(company, document_id, actor=None):
    return _company_call(lambda: _service(actor, scope_type="Company").detail(company, document_id))


def preview_company_revision(company, revision_id, page=1, actor=None):
    return _company_call(lambda: _service(actor, scope_type="Company").preview(company, revision_id, page))


def download_company_revision(company, revision_id, actor=None):
    return _company_call(lambda: _service(actor, scope_type="Company").download(company, revision_id))


def search_company_documents(company, query, limit=8, actor=None):
    return _company_call(lambda: _service(actor, scope_type="Company").search(company, None, query, limit))


def get_company_citation(company, revision_id, page, excerpt_sha256=None, actor=None, *, lock=False):
    return _company_call(lambda: _service(actor, scope_type="Company").citation(company, revision_id, page, excerpt_sha256, lock=lock))


def company_source_reference(company, revision_id, page, actor=None, *, lock=False):
    """Exact Company source bytes/facts; never resolves a Project-owned revision."""
    from cipher_aec.governance.context import current_actor, require_company
    actor = actor or current_actor()
    require_company(company, ability="document.read", actor=actor, lock=lock)
    return _company_call(lambda: _service(actor, scope_type="Company").source_reference(company, None, revision_id, page, lock=lock))


def authorize_company_subject(actor, company, subject_type, subject_id, *, lock=False):
    """History/receipt metadata authorization; quarantine never grants byte access."""
    from cipher_aec.api.errors import DomainError
    from cipher_aec.governance.context import require_company
    require_company(company, ability="document.read", actor=actor, lock=lock)
    bound = _service(actor, scope_type="Company")
    def check():
        if subject_type == "Cipher Document":
            row = bound.repo.document(subject_id, lock=lock)
            bound._scope(row, company)
        elif subject_type == "Cipher Document Revision":
            locator = bound.repo.revision_locator(subject_id)
            bound._scope(locator, company)
            document = bound.repo.document(locator["document"], lock=lock)
            bound._scope(document, company)
            revision = bound.repo.revision(subject_id, lock=lock)
            bound._scope(revision, company)
            if revision["document"] != document["name"]:
                raise DomainError("source_integrity", "This source mapping cannot be verified.", 409)
        else:
            raise DomainError("not_found", "This source is not available.", 404)
    return _company_call(check)


def authorize_company_receipt(actor, company, result, *, lock=False):
    from cipher_aec.api.errors import DomainError
    document, revision = result.get("document"), result.get("revision")
    if type(document) is not dict or type(revision) is not dict or not document.get("id") or not revision.get("id"):
        raise DomainError("receipt_integrity", "This document receipt cannot be verified.", 409)
    authorize_company_subject(actor, company, "Cipher Document", document["id"], lock=lock)
    authorize_company_subject(actor, company, "Cipher Document Revision", revision["id"], lock=lock)
    locator = FrappeDocumentRepository("Company").revision_locator(revision["id"])
    if locator["document"] != document["id"]:
        raise DomainError("receipt_integrity", "This document receipt cannot be verified.", 409)

"""Fresh canonical DOC02/DOC03 sources for the optional semantic adapter.

Nothing here configures or contacts an embedding/vector provider. Every selected
source needs an explicit current DOC03 read AND ingest basis. Permission-evidence
sources retain DOC03's no-policy path; every policy that exists in that bounded
closure must currently allow both operations. Source tokens contain canonical
facts, never an actor's authority, and cannot themselves authorize a later read.
"""
from __future__ import annotations

import hashlib
import re
from uuid import UUID

from cipher_aec.api.contracts import digest
from cipher_aec.api.errors import DomainError

_SCOPE_KEYS = frozenset(("company", "scope_type", "project"))
_SELECTOR_KEYS = frozenset(("document_id", "revision_id", "source_sha256", "selection", "adoption_id", "adoption_digest"))
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_REVISION_FIELDS = ("name", "document", "company", "scope_type", "project", "sha256", "revision_number",
                    "page_count", "byte_length", "mime_type", "scan_status", "retrieval_status",
                    "extraction_status", "extractor_version")


def _invalid():
    raise DomainError("invalid_semantic_source", "Declare an exact supported semantic source and scope.", 422)


def _unavailable():
    raise DomainError("semantic_source_unavailable", "The exact canonical source is unavailable.", 409)


def _changed():
    raise DomainError("semantic_source_changed", "The canonical source changed. Refresh the selected source.", 412)


def _text(value):
    return type(value) is str and 1 <= len(value) <= 140 and value == value.strip() and all(ord(c) >= 32 and ord(c) != 127 for c in value)


def _scope(value):
    if type(value) is not dict or set(value) != _SCOPE_KEYS or not _text(value.get("company")):
        _invalid()
    if value["scope_type"] == "Company" and value["project"] is None:
        return dict(value)
    if value["scope_type"] == "Project" and _text(value["project"]):
        return dict(value)
    _invalid()


def _selector(value):
    if type(value) is not dict or set(value) != _SELECTOR_KEYS:
        _invalid()
    if not all(_text(value[k]) for k in ("document_id", "revision_id")) or type(value["source_sha256"]) is not str or not _HASH.fullmatch(value["source_sha256"]):
        _invalid()
    if value["selection"] not in ("working", "issued", "adopted"):
        _invalid()
    if value["selection"] == "adopted":
        try:
            if type(value["adoption_id"]) is not str or str(UUID(value["adoption_id"])) != value["adoption_id"]:
                _invalid()
        except (ValueError, AttributeError):
            _invalid()
        if type(value["adoption_digest"]) is not str or not _HASH.fullmatch(value["adoption_digest"]):
            _invalid()
    elif value["adoption_id"] is not None or value["adoption_digest"] is not None:
        _invalid()
    return dict(value)


def _row_scope(row):
    return _scope({"company": row.get("company"), "scope_type": row.get("scope_type") or "Project", "project": row.get("project") or None})


def _canonical_scope_matches(row, origin):
    # Historical DOC02 Project citations/source facts omit these wire fields.
    # Their actual scope was checked by the canonical Project reader and our
    # independent metadata pass. Company facts always carry explicit scope.
    if origin["scope_type"] == "Project" and not any(key in row for key in _SCOPE_KEYS):
        return True
    return all(row.get(key) == value for key, value in origin.items())


class SourceAdapter:
    """Read canonical sources; construct fresh citation snippets outside Qdrant.

    The serialized extraction budget is deliberately conservative: JSON syntax
    and escaped characters also consume it. This bounds a revision's Long Text
    before DOC02 loads it, in addition to the canonical extraction limits.
    """

    def __init__(self, *, max_pages=128, max_characters=200000, max_page_characters=20000):
        if (type(max_pages) is not int or not 1 <= max_pages <= 200
                or type(max_characters) is not int or not 1 <= max_characters <= 1000000
                or type(max_page_characters) is not int or not 1 <= max_page_characters <= 20000):
            raise ValueError("Use bounded canonical source limits.")
        self.max_pages, self.max_characters, self.max_page_characters = max_pages, max_characters, max_page_characters

    def authorize(self, scope, actor, manage=False):
        """Return current target-scope authority; manage never implies read."""
        from cipher_aec.governance import context
        from . import scopes
        scope = _scope(scope)
        if type(manage) is not bool:
            _invalid()
        if manage:
            scopes.require(scope["company"], scope["scope_type"], scope["project"], actor, "document.semantic.manage")
        scopes.require(scope["company"], scope["scope_type"], scope["project"], actor, "document.read")
        fingerprint = (context.company_authority_fingerprint(actor, scope["company"]) if scope["scope_type"] == "Company"
                       else context.authority_fingerprint(actor, scope["company"], scope["project"]))
        if type(fingerprint) is not str or not _HASH.fullmatch(fingerprint):
            _unavailable()
        return fingerprint

    def _revision_metadata(self, revision_id):
        """Metadata only: do not fetch pages_json before the authorization pass."""
        import frappe
        row = frappe.db.get_value("Cipher Document Revision", revision_id, list(_REVISION_FIELDS), as_dict=True)
        if not row:
            _unavailable()
        sizes = frappe.db.sql("SELECT CHAR_LENGTH(pages_json) AS characters FROM `tabCipher Document Revision` WHERE name=%s", (revision_id,), as_dict=True)
        if len(sizes) != 1:
            _unavailable()
        return {**dict(row), "extraction_characters": sizes[0]["characters"]}

    def _rights_state(self, document_id, company, actor):
        """Current rights digests include every recursively supporting document."""
        from cipher_aec.documents.repository import FrappeDocumentRepository
        from . import rights, scopes
        repo = FrappeDocumentRepository()
        planned = rights.document_plan([document_id])
        states = []
        for name in sorted(planned):
            origin = _row_scope(repo.document_scope(name))
            if origin["company"] != company:
                _unavailable()
            scopes.require(company, origin["scope_type"], origin["project"], actor, "document.read")
            before = rights.current(name)
            versions = []
            for operation in ("read", "ingest"):
                policy = rights.require(name, company, origin["project"], operation, actor,
                                        required=name == document_id, scope_type=origin["scope_type"])
                versions.append(digest(policy) if policy is not None else None)
            version = digest(before) if before is not None else None
            if versions != [version, version]:
                _changed()
            states.append({"document_id": name, "scope": origin, "rights_digest": version})
        if rights.document_plan([document_id]) != planned:
            _changed()
        for state in states:
            policy = rights.current(state["document_id"])
            if (digest(policy) if policy is not None else None) != state["rights_digest"]:
                _changed()
        return states

    def _state(self, scope, selector, actor):
        """Authorize metadata/selection before any selected-source plaintext."""
        from cipher_aec.documents.repository import FrappeDocumentRepository
        from . import scopes
        repo = FrappeDocumentRepository()
        locator = repo.revision_locator(selector["revision_id"])
        origin = _row_scope(locator)
        if (origin["company"] != scope["company"] or locator.get("name") != selector["revision_id"]
                or locator.get("document") != selector["document_id"]):
            _unavailable()
        scopes.require(origin["company"], origin["scope_type"], origin["project"], actor, "document.read")
        from cipher_aec.quality_safety.privacy import authorize_source as authorize_incident_source
        authorize_incident_source(locator, actor)
        parent = repo.document(selector["document_id"])
        if _row_scope(parent) != origin or parent.get("name") != selector["document_id"]:
            _unavailable()
        row = self._revision_metadata(selector["revision_id"])
        if (_row_scope(row) != origin or row.get("name") != selector["revision_id"]
                or row.get("document") != selector["document_id"] or row.get("sha256") != selector["source_sha256"]):
            _unavailable()
        if (type(row.get("page_count")) is not int or not 1 <= row["page_count"] <= self.max_pages
                or type(row.get("extraction_characters")) is not int or not 2 <= row["extraction_characters"] <= self.max_characters
                or type(row.get("byte_length")) is not int or not 1 <= row["byte_length"] <= 10 * 1024 * 1024):
            raise DomainError("semantic_source_limit", "The selected source exceeds the bounded semantic extraction budget.", 422)
        if row.get("extraction_status") != "ready":
            raise DomainError("semantic_text_unavailable", "This source has no available canonical embedded text.", 409)
        rights_state = self._rights_state(selector["document_id"], scope["company"], actor)
        selection = selector["selection"]
        if selection == "working":
            if origin != scope:
                _unavailable()
            if parent.get("current_revision") != selector["revision_id"]:
                _changed()
            proof = {"current_revision": parent["current_revision"], "revision_number": parent["revision_number"]}
        elif selection == "issued":
            if scope["scope_type"] != "Project" or origin != scope:
                _unavailable()
            from .lifecycle import standing
            proof = standing(scope["company"], scope["project"], selector["document_id"], actor)
            issued = proof.get("current_issued")
            if (proof.get("status") != "issued" or type(issued) is not dict
                    or issued.get("revision_id") != selector["revision_id"] or issued.get("source_sha256") != selector["source_sha256"]):
                _changed()
        else:
            if scope["scope_type"] != "Project":
                _unavailable()
            from .service import read
            adoption = read("adoption", selector["adoption_id"], scope["company"], scope["project"], actor)
            selected = [artifact for artifact in adoption["artifacts"] if artifact.get("document_id") == selector["document_id"]]
            if (digest(adoption) != selector["adoption_digest"] or len(selected) != 1
                    or selected[0].get("revision_id") != selector["revision_id"] or selected[0].get("source_sha256") != selector["source_sha256"]):
                _changed()
            proof = {"adoption_id": adoption["id"], "adoption_digest": digest(adoption), "artifact": selected[0]}
        return {"source_scope": origin, "metadata": {**{k: row[k] for k in _REVISION_FIELDS},
                "document_id": selector["document_id"], "revision_id": selector["revision_id"],
                "source_sha256": selector["source_sha256"], "document_title": parent.get("title"),
                "selection": selection, "adoption_id": selector["adoption_id"], "adoption_digest": selector["adoption_digest"]},
                "rights": rights_state, "selection_proof": proof}

    def _read(self, scope, selector, actor, *, include_pages):
        from cipher_aec.documents import service as sources
        authority = self.authorize(scope, actor)
        before = self._state(scope, selector, actor)
        origin = before["source_scope"]
        if origin["scope_type"] == "Company":
            source = sources.company_source_reference(origin["company"], selector["revision_id"], 1, actor=actor)
        else:
            source = sources.source_reference(origin["company"], origin["project"], selector["revision_id"], 1, actor=actor)
        content = source.pop("content", None)
        if (type(content) is not bytes or len(content) != before["metadata"]["byte_length"]
                or hashlib.sha256(content).hexdigest() != selector["source_sha256"]):
            _unavailable()
        if (any(source.get(k) != selector[k] for k in ("document_id", "revision_id", "source_sha256"))
                or any(source.get(key) != before["metadata"][key] for key in ("page_count", "byte_length", "mime_type", "revision_number"))
                or not _canonical_scope_matches(source, origin) or source.get("extraction_status") != "ready"):
            _unavailable()
        del content
        pages, manifest, characters = [], [], 0
        for page in range(1, before["metadata"]["page_count"] + 1):
            citation = (sources.get_company_citation(origin["company"], selector["revision_id"], page, actor=actor)
                        if origin["scope_type"] == "Company" else sources.get_citation(origin["company"], selector["revision_id"], page, actor=actor))
            text = citation.get("excerpt")
            if (type(text) is not str or len(text) > self.max_page_characters
                    or any(citation.get(k) != selector[k] for k in ("document_id", "revision_id", "source_sha256"))
                    or citation.get("page") != page or not _canonical_scope_matches(citation, origin)
                    or citation.get("excerpt_sha256") != hashlib.sha256(text.encode("utf-8")).hexdigest()):
                _unavailable()
            characters += len(text)
            if characters > self.max_characters:
                raise DomainError("semantic_source_limit", "The selected source exceeds the bounded semantic extraction budget.", 422)
            manifest.append({"page": page, "citation_digest": digest(citation)})
            if include_pages:
                pages.append(dict(citation))
        after = self._state(scope, selector, actor)
        if before != after or self.authorize(scope, actor) != authority:
            _changed()
        token = digest({"schema": "cipher.semantic.source.v1", "scope": scope, "selector": selector,
                        "canonical": after, "pages": manifest})
        return {"scope": dict(scope), "selector": dict(selector), **after, "authority": authority,
                "token": token, "pages": pages}

    def snapshot(self, scope, selector, actor):
        """Return bounded fresh canonical citations and an actor-independent token."""
        return self._safe_read(_scope(scope), _selector(selector), actor, include_pages=True)

    def _safe_read(self, scope, selector, actor, *, include_pages):
        from cipher_aec.documents.extraction import ArtifactError
        try:
            return self._read(scope, selector, actor, include_pages=include_pages)
        except DomainError:
            raise
        except ModuleNotFoundError:
            raise DomainError("semantic_source_unavailable", "The canonical source runtime is unavailable.", 503) from None
        except (ArtifactError, KeyError, ValueError, TypeError, AttributeError):
            raise DomainError("semantic_source_unavailable", "The exact canonical source cannot be verified.", 409) from None

    def recheck(self, scope, selector, token, actor):
        """Fresh authorization/bytes/rights/standing check; tokens grant no access."""
        if type(token) is not str or not _HASH.fullmatch(token):
            _invalid()
        return self._safe_read(_scope(scope), _selector(selector), actor, include_pages=False)["token"] == token

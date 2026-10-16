"""Document invariants independent of HTTP and the storage implementation."""
from __future__ import annotations

import json
import re
import uuid
from .extraction import ArtifactError, digest, extract_source, validate_source
from .scope import scope_of, company_fields


class DocumentService:
    def __init__(self, repository, storage, authorize, *, allow_unscanned=False, scanner=None, scope_type="Project", source_authorize=None):
        self.repo, self.storage, self.authorize = repository, storage, authorize
        self.source_authorize = source_authorize
        self.allow_unscanned, self.scanner = allow_unscanned, scanner
        if scope_type not in ("Project", "Company"):
            raise ValueError("Bind an explicit supported source scope")
        self.scope_type = scope_type

    def _authorize(self, company, project, ability):
        scope_of({"scope_type":self.scope_type,"company":company,"project":project})
        self.authorize(company, project, ability)

    def upload(self, *, company, project, title, filename, content, byte_length, sha256,
               document_id=None, expected_revision=None, producer=None, generation=None):
        self._authorize(company, project, "document.write")
        mime = validate_source(content, filename, byte_length, sha256)
        if not isinstance(title, str) or not title.strip() or len(title) > 200 or any(ord(c) < 32 for c in title):
            raise ArtifactError("Document title must contain 1 to 200 visible characters.")
        if document_id:
            document = self.repo.document(document_id, lock=True)
            self._scope(document, company, project)
            if document.get("producer_kind") or producer:
                raise ArtifactError("Generated documents cannot accept ordinary or successor uploads.")
            if type(expected_revision) is not int or expected_revision != document["revision_number"]:
                raise ArtifactError("Document revision changed; refresh before adding a revision.")
        else:
            if expected_revision not in (None, 0):
                raise ArtifactError("A new document must not specify a prior revision.")
            document = {"name": "DOC-" + uuid.uuid4().hex, "company": company, "project": project, "scope_type":self.scope_type,
                        "title": title.strip(), "revision_number": 0, "current_revision": None}
            if producer:
                if self.scope_type != "Company":
                    raise ArtifactError("Generated sources require exact Company scope.")
                from .provenance import producer_fields
                document.update(producer_fields(producer))
                if self.source_authorize:
                    self.source_authorize(document, lock=False)
                from .preparation import _bind_parent
                _bind_parent(document)
            self.repo.create_document(document)
        revision_id = "REV-" + uuid.uuid4().hex
        scan_status = self.scanner.scan(content, mime) if self.scanner else "not_scanned"
        if scan_status not in {"clean", "infected", "not_scanned", "unavailable"}:
            raise ArtifactError("Scanner returned an unsupported status.")
        extraction = extract_source(content, mime) if scan_status != "infected" else None
        retrievable = (scan_status == "clean" or self.allow_unscanned and scan_status == "not_scanned") and extraction is not None and extraction.status in {"ready", "ocr_unavailable"}
        if producer:
            from .preparation import _bind_revision
            _bind_revision(revision_id)
        reference = self.storage.put(revision_id, filename, content)
        revision = {"name": revision_id, "document": document["name"], "company": company, "project": project, "scope_type":self.scope_type,
                    "revision_number": document["revision_number"] + 1, "filename": filename,
                    "mime_type": mime, "byte_length": len(content), "sha256": digest(content),
                    "storage_reference": reference, "scan_status": scan_status,
                    "retrieval_status": "available" if retrievable else "quarantined",
                    "extraction_status": extraction.status if extraction else "blocked",
                    "extractor_version": extraction.extractor_version if extraction else "none",
                    "pages_json": json.dumps(list(extraction.pages) if extraction else [], ensure_ascii=False),
                    "page_count": len(extraction.pages) if extraction else 0,
                    "extraction_warning": extraction.warning if extraction else "Source flagged by scanner."}
        if producer:
            if type(generation) is not dict:
                raise ArtifactError("Generated source provenance is required.")
            revision["generation_json"] = json.dumps(generation, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            revision.update({key: document[key] for key in ("producer_kind", "producer_reference", "producer_input_digest", "producer_binding_json")})
        self.repo.create_revision(revision)
        self.repo.advance_document(document["name"], revision_id, revision["revision_number"])
        document.update(current_revision=revision_id, revision_number=revision["revision_number"])
        return {"document": present_document(document, revision), "revision": present_revision(revision)}

    def _check_scope(self, row, company, project=None):
        if scope_of(row) != self.scope_type or row["company"] != company or project is not None and row["project"] != project:
            raise ArtifactError("Document is outside the requested scope.")

    def _scope(self, row, company, project=None, *, lock=False):
        self._check_scope(row, company, project)
        self._authorize(row["company"], row["project"], "document.read")
        if self.source_authorize:
            self.source_authorize(row, lock=lock)

    def _company_revision_source(self, company, revision_id, *, lock=False):
        """One canonical read's Company duty; every source row stays checked.

        No authority survives this call. The parent producer is authorized
        before loading revision Long Text; the loaded revision must still
        match that exact parent/binding before any source bytes are read.
        """
        if self.scope_type != "Company":
            raise ArtifactError("Document is outside the requested scope.")
        locator = self.repo.revision_locator(revision_id)
        self._check_scope(locator, company)
        if locator["name"] != revision_id:
            raise ArtifactError("Document revision source mapping is invalid.")
        self._authorize(company, None, "document.read")
        document = self.repo.document(locator["document"], lock=lock)
        self._check_scope(document, company)
        if document["name"] != locator["document"]:
            raise ArtifactError("Document revision source mapping is invalid.")
        if self.source_authorize:
            self.source_authorize(document, lock=lock)
        revision = self.repo.revision(revision_id, lock=lock)
        self._check_scope(revision, company)
        if revision["name"] != revision_id or revision["document"] != document["name"]:
            raise ArtifactError("Document revision source mapping is invalid.")
        if any((revision.get(key) or None) != (document.get(key) or None) for key in
               ("producer_kind", "producer_reference", "producer_input_digest", "producer_binding_json")):
            raise ArtifactError("Document revision producer integrity cannot be verified.")
        if self.source_authorize:
            self.source_authorize(revision, lock=lock)
        return document, revision

    def revision(self, company, revision_id, *, lock=False):
        # Read only scope metadata before current authorization; never bytes or page text.
        scope = self.repo.revision_scope(revision_id)
        self._scope(scope, company, lock=lock)
        return self.repo.revision(revision_id, lock=lock)

    def _available(self, revision):
        scan_allowed = revision["scan_status"] == "clean" or (self.allow_unscanned and revision["scan_status"] == "not_scanned")
        if revision["retrieval_status"] != "available" or not scan_allowed:
            raise ArtifactError("Source is quarantined and cannot be retrieved.")

    def effective_metadata(self, revision):
        row = dict(revision)
        try:
            self._available(row)
        except ArtifactError:
            row["retrieval_status"] = "quarantined"
        return row

    def source_reference(self, company, project, revision_id, page, *, lock=False):
        # Resolve only scope/parent metadata first, then lock parent before revision
        # in the same order as the canonical upload command.
        if self.scope_type == "Company":
            if project is not None:
                raise ArtifactError("Document is outside the requested scope.")
            document, revision = self._company_revision_source(company, revision_id, lock=lock)
        else:
            locator = self.repo.revision_locator(revision_id)
            self._scope(locator, company, project, lock=lock)
            document = self.repo.document(locator["document"], lock=lock)
            self._scope(document, company, project, lock=lock)
            revision = self.repo.revision(revision_id, lock=lock)
            self._scope(revision, company, project, lock=lock)
        if revision["document"] != document["name"]:
            raise ArtifactError("Document revision source mapping is invalid.")
        self._available(revision)
        if type(page) is not int or not 1 <= page <= revision["page_count"]:
            raise ArtifactError("Source page is outside this revision.")
        content = self.storage.read(revision["storage_reference"], revision["sha256"], revision["byte_length"])
        return {"document_id": document["name"], "revision_id": revision["name"],
                "revision_number": revision["revision_number"], "current_revision": document["current_revision"],
                "current_revision_number": document["revision_number"],
                "is_current": document["current_revision"] == revision["name"],
                "page": page, "page_count": revision["page_count"], "mime_type": revision["mime_type"],
                "source_sha256": revision["sha256"], "byte_length": revision["byte_length"],
                "extraction_status": revision["extraction_status"], "content": content, **company_fields(revision)}

    def download(self, company, revision_id):
        revision = self.revision(company, revision_id)
        self._available(revision)
        return revision, self.storage.read(revision["storage_reference"], revision["sha256"], revision["byte_length"])

    def citation(self, company, revision_id, page, excerpt_sha256=None, *, lock=False):
        if self.scope_type == "Company":
            document, revision = self._company_revision_source(company, revision_id, lock=lock)
        else:
            revision = self.revision(company, revision_id, lock=lock)
        self._available(revision)
        # Extraction is not evidence if original bytes have disappeared or changed.
        self.storage.read(revision["storage_reference"], revision["sha256"], revision["byte_length"])
        if type(page) is not int or page < 1 or page > revision["page_count"]:
            raise ArtifactError("Citation page is outside this source revision.")
        if revision["extraction_status"] != "ready":
            raise ArtifactError("Source has no available embedded text; OCR is not configured.")
        text = json.loads(revision["pages_json"])[page - 1]
        checksum = digest(text.encode("utf-8"))
        if excerpt_sha256 is not None and excerpt_sha256 != checksum:
            raise ArtifactError("Citation excerpt checksum does not match this page.")
        if self.scope_type != "Company":
            document = self.repo.document(revision["document"], lock=lock)
            self._scope(document, company, lock=lock)
        citation = {"document_id": revision["document"], "revision_id": revision["name"],
                    "document_title": document["title"], "revision_number": revision["revision_number"],
                    "page": page, "page_label": str(page), "excerpt": text,
                    "excerpt_sha256": checksum, "source_sha256": revision["sha256"]}
        citation.update(company_fields(revision))
        citation["id"] = digest(json.dumps([revision["name"], page, checksum], separators=(",", ":")).encode())
        return citation

    def preview(self, company, revision_id, page=1):
        citation = self.citation(company, revision_id, page)
        revision = self.revision(company, revision_id)
        return {"document_id": citation["document_id"], "revision_id": revision_id,
                "page": page, "page_count": revision["page_count"], "text": citation["excerpt"],
                "content_type": "text/plain", "citation": citation, **company_fields(revision)}

    def list(self, company, project):
        self._authorize(company, project, "document.read")
        result = []
        for document in self.repo.documents(company, project):
            try:
                self._scope(document, company, project)
                revision = self.repo.revision(document["current_revision"])
                self._scope(revision, company, project)
            except Exception as error:
                if getattr(error, "status", None) in (403, 404):
                    continue
                raise
            result.append(present_document(document, self.effective_metadata(revision)))
        return result

    def detail(self, company, document_id):
        document = self.repo.document(document_id)
        self._scope(document, company)
        revisions = self.repo.revisions(document_id)
        for revision in revisions:
            self._scope(revision, company)
        current = next(r for r in revisions if r["name"] == document["current_revision"])
        return {"document": present_document(document, self.effective_metadata(current)), "revisions": [present_revision(self.effective_metadata(r)) for r in revisions]}

    def search(self, company, project, query, limit=8):
        self._authorize(company, project, "document.read")
        if not isinstance(query, str) or not query.strip() or len(query) > 500:
            raise ArtifactError("Search must contain 1 to 500 characters.")
        if type(limit) is not int or not 1 <= limit <= 20:
            raise ArtifactError("Search result limit must be between 1 and 20.")
        terms = [t.casefold() for t in re.findall(r"\w+", query) if len(t) > 1]
        if not terms:
            return []
        results = []
        # Scope is constrained in SQL, then every candidate is independently authorized.
        for row in self.repo.search_candidates(company, project):
            try:
                revision = self.revision(company, row["name"])
            except Exception as error:
                if getattr(error, "status", None) in (403, 404):
                    continue
                raise
            if revision["retrieval_status"] != "available" or revision["extraction_status"] != "ready":
                continue
            document = self.repo.document(revision["document"])
            title_match = all(term in document["title"].casefold() for term in terms)
            for page, text in enumerate(json.loads(revision["pages_json"]), 1):
                if all(term in text.casefold() for term in terms) or (title_match and page == 1):
                    results.append(self.citation(company, revision["name"], page))
                    if len(results) >= limit:
                        return results
        return results


def present_revision(row):
    fields = ("revision_number", "filename", "mime_type", "byte_length", "sha256", "scan_status",
              "retrieval_status", "extraction_status", "extractor_version", "page_count", "extraction_warning")
    return {"id": row["name"], **{key: row.get(key) for key in fields}, **company_fields(row)}


def present_document(document, revision):
    return {"id": document["name"], "title": document["title"], "company": document["company"],
            "project": document["project"], "current_revision": document["current_revision"], **company_fields(document),
            **{key: value for key, value in present_revision(revision).items() if key != "id"}}

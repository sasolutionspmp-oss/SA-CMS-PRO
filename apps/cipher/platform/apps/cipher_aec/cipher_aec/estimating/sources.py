"""Exact source revisions and current document access for authored pricing."""

import re

import frappe

from cipher_aec.api.errors import DomainError
from cipher_aec.documents.service import get_citation
from cipher_aec.governance.context import require_project

from .contracts import closed, fail, visible


def resolve(company, project, references, actor, *, lock=False):
    require_project(company, project, ability="document.read", actor=actor, lock=lock)
    if type(references) is not list or not 1 <= len(references) <= 8:
        fail("Use one through eight actual document source citations.", "source_citations")
    result, seen = [], set()
    for row in references:
        closed(row, {"revision_id", "page", "excerpt_sha256"}, {"source_sha256"}, "source_citations[]")
        visible(row["revision_id"], "source.revision_id", 140)
        if type(row["page"]) is not int or row["page"] < 1 or type(row["excerpt_sha256"]) is not str or not re.fullmatch("[a-f0-9]{64}", row["excerpt_sha256"]):
            fail("A source citation requires its exact page and excerpt checksum.", "source_citations")
        scope = frappe.db.get_value("Cipher Document Revision", row["revision_id"], ["company", "project"], as_dict=True)
        if not scope or scope.company != company or scope.project != project:
            raise DomainError("not_found", "This estimate source is not available in the current project.", 404)
        citation = get_citation(company, row["revision_id"], row["page"], excerpt_sha256=row["excerpt_sha256"], actor=actor)
        if "source_sha256" in row and row["source_sha256"] != citation["source_sha256"]:
            raise DomainError("stale_source", "The source bytes no longer match the authored citation.", 412)
        key = citation["id"]
        if key not in seen:
            result.append(citation)
            seen.add(key)
    return result


def verify(company, project, citations, actor, *, lock=False):
    if type(citations) is not list or not 1 <= len(citations) <= 64:
        fail("Use a bounded immutable source manifest.", "source_citations")
    references = [{key: row[key] for key in ("revision_id", "page", "excerpt_sha256", "source_sha256")} for row in citations]
    actual = [row for start in range(0, len(references), 8) for row in resolve(company, project, references[start:start + 8], actor, lock=lock)]
    expected = {row["id"]: row for row in actual}
    for row in citations:
        if row.get("id") not in expected or row != expected[row["id"]]:
            raise DomainError("source_integrity", "The authored source citation cannot be verified.", 409)
    return actual


def merge(*groups):
    result = list({row["id"]: row for group in groups for row in group}.values())
    if len(result) > 64:
        fail("The estimate exceeds the bounded 64-citation source manifest.", "source_citations", "calculation_limit")
    return result


def verify_native_rates(company, project, rates, actor, *, lock=False):
    """Reuse the canonical company association rules and native read boundary."""
    from cipher_aec.migrations.export import FrappeTargetReader
    references = set()
    for rate in rates:
        if rate.get("item"):
            references.add(("item", rate["item"]))
        if rate.get("party"):
            references.add((rate["party_type"].lower(), rate["party"]))
    reader = FrappeTargetReader(company, project, actor=actor)
    for kind, name in sorted(references):
        if reader.fetch(kind, name, lock=lock) is None:
            raise DomainError("not_found", "The referenced native source is not available in the current scope.", 404)

"""Exact source revisions and current document access for authored pricing."""

import re

import frappe

from cipher_aec.api.errors import DomainError
from cipher_aec.documents.service import get_citation
from .scopes import require as require_project
from . import scopes

from .contracts import closed, fail, visible

# Kept closed while the new complete-union path undergoes native qualification.
GENERATED_INPUTS_QUALIFIED = False


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
        scope = scopes.current(company, project)
        fields = ["company", "project", "scope_type"] if scope.scope_type == "Company" else ["company", "project"]
        record = frappe.db.get_value("Cipher Document Revision", row["revision_id"], fields, as_dict=True)
        if not record or record.company != company or record.project != project or scope.scope_type == "Company" and record.scope_type != "Company":
            raise DomainError("not_found", "This estimate source is not available in the current project.", 404)
        if scope.scope_type == "Company":
            if lock:
                require_raw_mutation_source(company, row["revision_id"], actor)
            from cipher_aec.documents.service import get_company_citation
            citation = get_company_citation(company, row["revision_id"], row["page"], excerpt_sha256=row["excerpt_sha256"], actor=actor, lock=lock)
        else:
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


def pursuit_plan(company, project, pursuit_id, actor, *, lock=False):
    if not pursuit_id:
        return None
    if scopes.current(company, project).scope_type != "Company":
        raise DomainError("invalid_scope", "Pursuit-linked estimates require explicit Company scope.", 422)
    from cipher_aec.commercial.service import pursuit_source_plan
    return pursuit_source_plan(company, pursuit_id, actor=actor, lock=lock)


def verify_native_rates(company, project, rates, actor, *, lock=False, pursuit_plans=(), extra_references=()):
    """Lock one complete native union, then recheck each exact source authority.

    Callers needing qualified units/currency acquire those first. Pursuit plans
    are internal discovery, never authorization to expose commercial content.
    """
    from cipher_aec.api.contracts import version_of
    from cipher_aec.commercial.native import require_native
    # Assemblies carry currencies inside pinned rates. Permission-only checks
    # add no row locks before the caller's complete unit/currency/native union.
    for currency in sorted({rate["currency"] for rate in rates}):
        require_native("Currency", currency, actor)
    from cipher_aec.migrations.export import FrappeTargetReader
    references = {}
    for rate in rates:
        if rate.get("item"):
            references[("Item", rate["item"])] = "item"
        if rate.get("party"):
            references[(rate["party_type"], rate["party"])] = rate["party_type"].lower()
    plans = [plan for plan in pursuit_plans if plan]
    for plan in plans:
        for ref in plan["native_refs"]:
            references.setdefault((ref["doctype"], ref["name"]), None)
    for ref in extra_references:
        references.setdefault((ref["doctype"], ref["name"]), None)
    if scopes.current(company, project).scope_type == "Company":
        from cipher_aec.migrations.export import FrappeCompanyTargetReader
        reader = FrappeCompanyTargetReader(company, actor=actor, ability="estimate.read")
    else:
        reader = FrappeTargetReader(company, project, actor=actor)
    if lock and scopes.current(company, project).scope_type == "Company":
        from .lockplan import require_resources
        require_resources({"native_refs": [{"doctype": doctype, "name": name} for doctype, name in references]}, actor, company)
    versions = []
    for (doctype, name), kind in sorted(references.items()):
        if kind is not None:
            if reader.fetch(kind, name, lock=lock) is None:
                raise DomainError("not_found", "The referenced native source is not available in the current scope.", 404)
            doc = frappe.get_doc(doctype, name, for_update=lock)
        else:
            from cipher_aec.commercial.native import require_native
            doc = require_native(doctype, name, actor, lock=lock)
            if doctype == "Opportunity" and doc.company != company or doctype == "Customer" and doc.get("accounts") and company not in {row.company for row in doc.accounts}:
                raise DomainError("not_found", "This native source is not available in the current Company.", 404)
        versions.append({"doctype": doctype, "name": name, "version": version_of(doc)})
    for plan in plans:
        from cipher_aec.commercial.service import recheck_pursuit_source
        value = recheck_pursuit_source(company, plan["pursuit_id"], actor=actor, lock=lock)
        from cipher_aec.api.contracts import digest
        if digest(value) != plan["record_digest"]:
            raise DomainError("stale_pursuit", "The selected Pursuit changed during source authorization.", 412)
    return versions


def require_raw_mutation_source(company, revision_id, actor):
    """Require exact actor-scoped whole-union admission before generated use.

    Discovery grants no source content. Final citation/byte readers still check
    every original source and producer permission after the complete locks.
    """
    from cipher_aec.documents.provenance import source_plan
    plan = source_plan(company, revision_id, actor, lock=True)
    from .lockplan import admitted
    if plan["generated_sources"] and (not GENERATED_INPUTS_QUALIFIED or not admitted(plan, actor, company)):
        raise DomainError("source_dependency_unqualified", "Generated proposal outputs are not yet qualified as new estimate/takeoff inputs. Use an authorized raw canonical source.", 409)

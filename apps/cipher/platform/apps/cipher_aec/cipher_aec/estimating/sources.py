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


def citation_groups(kind, record):
    """Literal citation collections for one acceptance fact builder.

    No arbitrary JSON traversal or general source deferral. Each group retains
    its original occurrences and its existing domain bound, including copies
    embedded in typed rates and calculation inputs.
    """
    if kind not in {"revision", "snapshot", "rate", "assembly", "conversion"}:
        raise DomainError("source_integrity", "This record cannot defer source verification.", 409)
    try:
        groups = [(record["source_citations"], 64)]
        if kind == "rate":
            groups.append((record["rate"]["source_citations"], 8))
        if kind in {"assembly", "snapshot"}:
            rates = record["rates"] if kind == "assembly" else record["inputs"]["rates"]
            if type(rates) is not dict or len(rates) > (50 if kind == "assembly" else 500):
                raise ValueError
            groups.extend((rate["source_citations"], 8) for rate in rates.values())
        if kind == "snapshot":
            groups.append((record["inputs"]["basis_citations"], 8))
        return groups
    except (KeyError, TypeError, ValueError):
        raise DomainError("source_integrity", "The typed source collections cannot be verified.", 409) from None


def _citation_key(row):
    if type(row) is not dict:
        raise DomainError("source_integrity", "An original citation requires its complete canonical fields.", 409)
    keys = ("revision_id", "page", "excerpt_sha256", "source_sha256")
    if (any(key not in row for key in keys) or type(row["revision_id"]) is not str or not row["revision_id"] or len(row["revision_id"]) > 140
            or type(row["page"]) is not int or row["page"] < 1
            or any(type(row[key]) is not str or not re.fullmatch("[a-f0-9]{64}", row[key]) for key in keys[2:])):
        raise DomainError("source_integrity", "An original citation requires its exact page and source checksums.", 409)
    return tuple(row[key] for key in keys)


def verify_groups(company, project, groups, actor, *, lock=False):
    """Verify every original citation copy with one canonical read per locator.

    Only the calling builder owns these local values. No identity, authority,
    current head, DTO or source bytes are cached across builders. Existing
    per-group bounds remain; independent valid groups gain no union-wide64 cap.
    """
    occurrences, references = [], {}
    for citations, limit in groups:
        if type(limit) is not int or limit not in (8, 64) or type(citations) is not list or len(citations) > limit:
            fail("Use the existing bounded typed source collection.", "source_citations")
        for row in citations:
            key = _citation_key(row)
            occurrences.append((key, row))
            if key not in references:
                references[key] = {name: row[name] for name in ("revision_id", "page", "excerpt_sha256", "source_sha256")}
    if not references:
        return []
    unique = list(references.values())
    actual = [row for start in range(0, len(unique), 8) for row in resolve(company, project, unique[start:start + 8], actor, lock=lock)]
    canonical = {_citation_key(row): row for row in actual}
    for key, original in occurrences:
        expected = canonical.get(key)
        # Citation DTO fields are typed scalar metadata/text. Python otherwise
        # considers True == 1 == 1.0; none is the same canonical stored value.
        if (expected is None or original.keys() != expected.keys()
                or any(type(original[field]) is not type(expected[field]) or original[field] != expected[field] for field in expected)):
            raise DomainError("source_integrity", "Every original source citation must match its complete canonical source.", 409)
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
    """Require exact actor-scoped node admission before canonical source use.

    This metadata preflight grants no resource or source authority. Every caller
    immediately enters its canonical citation/drawing reader, which still checks
    the complete resource subset, original rights and exact requested bytes.
    """
    from cipher_aec.documents.provenance import mutation_source_identity
    source = mutation_source_identity(company, revision_id, actor)
    from .lockplan import admitted
    node = {"generated_sources": [{"document_id": source["document_id"], "input_digest": source["input_digest"]}]} if source["generated"] else {}
    if source["generated"] and (not GENERATED_INPUTS_QUALIFIED or not admitted(node, actor, company)):
        raise DomainError("source_dependency_unqualified", "Generated proposal outputs are not yet qualified as new estimate/takeoff inputs. Use an authorized raw canonical source.", 409)

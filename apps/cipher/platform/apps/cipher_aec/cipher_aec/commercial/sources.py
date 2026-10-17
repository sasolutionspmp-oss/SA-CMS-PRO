"""Exact immutable Company inputs and complete source lock discovery.

Discovery returns internal lock IDs only. Call verify/revision authorization before
exposing any facts. Output documents are never traversed from a proposal revision.
"""
import json
from cipher_aec.api.contracts import digest
from cipher_aec.api.errors import DomainError
from . import contracts


def merge(*plans):
    units, currencies, refs, generated = set(), set(), set(), set()
    for value in plans:
        generated.update((row["document_id"], row["input_digest"]) for row in value.get("generated_sources", []))
        units.update(value.get("unit_ids", []))
        currencies.update(value.get("currencies", []))
        if value.get("currency"):
            currencies.add(value["currency"])
        refs.update((row["doctype"], row["name"]) for row in value.get("native_refs", []))
    from cipher_aec.documents.provenance import MAX_NODES
    if len(generated) > MAX_NODES:
        raise DomainError("source_limit", "Generated source dependencies exceed the bounded authorization limit.", 409)
    return {"generated_sources": [{"document_id": name, "input_digest": checksum} for name, checksum in sorted(generated)], "unit_ids": sorted(units), "currencies": sorted(currencies), "native_refs": [{"doctype": kind, "name": name} for kind, name in sorted(refs)]}


def plan(composition, company, actor, *, lock=False):
    from cipher_aec.documents.provenance import source_plan
    plans = [source_plan(company, row["revision_id"], actor, lock=lock) for row in composition.get("source_references", [])]
    baseline = composition.get("estimate_reference")
    if baseline:
        from cipher_aec.estimating.company_service import accepted_baseline_source_plan
        plans.append(accepted_baseline_source_plan(company, baseline["acceptance_id"], actor, lock=lock))
    return merge(*plans)


def verify(composition, company, pursuit_id, actor, *, lock=False, stored=None):
    from cipher_aec.documents.service import get_company_citation
    citations = []
    for row in composition.get("source_references", []):
        citation = get_company_citation(company, row["revision_id"], row["page"], row["excerpt_sha256"], actor, lock=lock)
        if citation["source_sha256"] != row["source_sha256"]:
            raise DomainError("source_integrity", "The exact proposal source checksum cannot be verified.", 409)
        citations.append({"citation": citation, "purpose": row["purpose"], "permission_basis": row["permission_basis"], "policy": "pinned-revision-page-v1"})
    baseline = None
    ref = composition.get("estimate_reference")
    if ref:
        from cipher_aec.estimating.company_service import accepted_baseline_reference
        baseline = accepted_baseline_reference(company, ref["acceptance_id"], actor, lock=lock)
        if any(baseline[key] != value for key, value in ref.items()):
            raise DomainError("stale_estimate_reference", "Bind the exact accepted estimate baseline and revision digests.", 412)
        if baseline.get("pursuit_id") != pursuit_id or baseline["currency"] != composition["currency"]:
            raise DomainError("estimate_scope_conflict", "The accepted baseline must belong to this exact Company pursuit and currency.", 409)
    result = {"source_citations": citations, "accepted_estimate": baseline}
    if stored is not None and (stored.get("source_citations", []) != citations or stored.get("accepted_estimate") != baseline):
        raise DomainError("commercial_integrity", "Stored commercial source bindings cannot be verified.", 409)
    return result


def revision_record(company, revision_id, actor, *, lock=False):
    import frappe
    from cipher_aec.governance.context import require_company
    require_company(company, ability="commercial.read", actor=actor, lock=lock)
    contracts.identifier(revision_id)
    try:
        doc = frappe.get_doc("Cipher Proposal Revision", revision_id, for_update=lock)
    except frappe.DoesNotExistError:
        raise DomainError("not_found", "This commercial source is not available.", 404) from None
    value = json.loads(doc.data_json)
    if doc.company != company or value.get("company") != company:
        raise DomainError("not_found", "This commercial source is not available.", 404)
    if value.get("id") != revision_id or digest(value) != doc.record_digest:
        raise DomainError("commercial_integrity", "Commercial source evidence cannot be verified.", 409)
    return value


def revision_plan(company, revision_id, actor, *, lock=False):
    from .service import _source_plan
    value = revision_record(company, revision_id, actor, lock=lock)
    party, refs = _source_plan("proposal", value["proposal"], company, lock=lock)
    refs.add(party)
    refs.add(("Price List", value["composition"]["price_list"]))
    refs.update(("Item", row["item_code"]) for row in value["composition"]["price_lines"] if row["item_code"])
    own = {"unit_ids": list(value["units"]), "currency": value["composition"]["currency"], "native_refs": [{"doctype": kind, "name": name} for kind, name in sorted(refs)]}
    return merge(own, plan(value["composition"], company, actor, lock=lock))

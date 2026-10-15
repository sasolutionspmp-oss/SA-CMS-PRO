"""Explicit Company entrypoints into the existing canonical domain."""
from cipher_aec.estimating import scopes
from . import service


def register_unit(company, operation_id, uom, dimension, quantity_precision):
    with scopes.activate("Company", company, None):
        return service.register_unit(company, None, operation_id, uom, dimension, quantity_precision)


def create_conversion(company, operation_id, definition, source_citations, permission_basis, predecessor=None):
    with scopes.activate("Company", company, None):
        return service.create_conversion(company, None, operation_id, definition, source_citations, permission_basis, predecessor)


def create_rate(company, operation_id, rate, predecessor=None):
    with scopes.activate("Company", company, None):
        return service.create_rate(company, None, operation_id, rate, predecessor)


def create_assembly(company, operation_id, title, basis_unit_id, components, author_basis, conversion_ids, predecessor=None):
    with scopes.activate("Company", company, None):
        return service.create_assembly(company, None, operation_id, title, basis_unit_id, components, author_basis, conversion_ids, predecessor)


def create_estimate(company, operation_id, title, currency, pricing_date, pursuit_id=None):
    with scopes.activate("Company", company, None):
        return service.create_estimate(company, None, operation_id, title, currency, pricing_date, pursuit_id=pursuit_id)


def calculate_revision(company, operation_id, estimate_id, expected_revision, lines, adjustments, conversion_ids, basis_description, basis_citations):
    with scopes.activate("Company", company, None):
        return service.calculate_revision(company, None, operation_id, estimate_id, expected_revision, lines, adjustments, conversion_ids, basis_description, basis_citations)


def get_record(company, kind, record_id):
    from contextlib import nullcontext
    from cipher_aec.governance.context import current_actor
    from cipher_aec.documents.provenance import read_graph, read_graph_eligible
    with scopes.activate("Company", company, None):
        actor = current_actor()
        scopes.require(company, None, ability="estimate.read", actor=actor)
        # One explicit public read, never an internal command/source reader.
        # Read-after-write falls back to the original uncached authority path.
        with read_graph(actor, company) if read_graph_eligible(actor, company) else nullcontext():
            return service.get_record(company, None, kind, record_id)


def list_records(company, kind, limit=20, cursor=None, count_mode='none'):
    with scopes.activate("Company", company, None):
        return service.list_records(company, None, kind, limit, cursor, count_mode)


def list_units(company):
    with scopes.activate("Company", company, None):
        return service.list_units(company, None)


def list_acceptances(company, estimate_id):
    with scopes.activate("Company", company, None):
        return service.list_acceptances(company, None, estimate_id)


def accepted_baseline_reference(company, acceptance_id, actor=None, *, lock=False):
    with scopes.activate("Company", company, None):
        return service.accepted_baseline_reference(company, None, acceptance_id, actor=actor, lock=lock)


def accepted_baseline_source_plan(company, acceptance_id, actor=None, *, lock=False):
    """Internal discovery for a caller's complete UOM/currency/native lock union.

    This plan authorizes no public content. Call accepted_baseline_reference after
    taking the complete union; it rechecks the exact original source authority.
    """
    from cipher_aec.governance.context import current_actor
    from cipher_aec.api.contracts import digest
    from cipher_aec.api.errors import DomainError
    from . import repository, sources
    actor = actor or current_actor()
    with scopes.activate("Company", company, None):
        scopes.require(company, None, ability="estimate.read", actor=actor, lock=lock)
        value = repository.read("acceptance", acceptance_id, lock=lock)
        if not scopes.current(company, None).matches(value):
            raise DomainError("not_found", "This accepted baseline is not available.", 404)
        from .lockplan import Discovery
        discovery = Discovery(company, actor, lock=lock)
        discovery.value("estimate", "acceptance", value)
        plan = discovery.finish()
        return {**plan, "acceptance_id": value["id"], "acceptance_digest": digest(value), "currency": value["currency"]}



def acceptance_subject(company, revision_id):
    with scopes.activate("Company", company, None):
        return service.acceptance_subject(company, None, revision_id)

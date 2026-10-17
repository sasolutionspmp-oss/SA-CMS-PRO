"""Company-scoped canonical API; Project contracts remain separate."""
from cipher_aec.api.transport import endpoint
from cipher_aec.estimating.scopes import company_request
from . import company_service as service


@endpoint(methods=["POST"])
def register_unit(company, operation_id, uom, dimension, quantity_precision):
    company_request()
    return service.register_unit(company, operation_id, uom, dimension, quantity_precision)


@endpoint(methods=["POST"])
def create_conversion(company, operation_id, definition, source_citations, permission_basis, predecessor=None):
    company_request()
    return service.create_conversion(company, operation_id, definition, source_citations, permission_basis, predecessor)


@endpoint(methods=["POST"])
def create_rate(company, operation_id, rate, predecessor=None):
    company_request()
    return service.create_rate(company, operation_id, rate, predecessor)


@endpoint(methods=["POST"])
def create_assembly(company, operation_id, title, basis_unit_id, components, author_basis, conversion_ids, predecessor=None):
    company_request()
    return service.create_assembly(company, operation_id, title, basis_unit_id, components, author_basis, conversion_ids, predecessor)


@endpoint(methods=["POST"])
def create_estimate(company, operation_id, title, currency, pricing_date, pursuit_id=None):
    company_request()
    return service.create_estimate(company, operation_id, title, currency, pricing_date, pursuit_id)


@endpoint(methods=["POST"])
def calculate_revision(company, operation_id, estimate_id, expected_revision, lines, adjustments, conversion_ids, basis_description, basis_citations):
    company_request()
    return service.calculate_revision(company, operation_id, estimate_id, expected_revision, lines, adjustments, conversion_ids, basis_description, basis_citations)


@endpoint()
def get_record(company, kind, record_id):
    company_request()
    return service.get_record(company, kind, record_id)


@endpoint()
def list_records(company, kind, limit=20, cursor=None, count_mode='none'):
    company_request()
    return service.list_records(company, kind, limit, cursor, count_mode)


@endpoint()
def list_units(company):
    company_request()
    return service.list_units(company)


@endpoint()
def list_acceptances(company, estimate_id):
    company_request()
    return service.list_acceptances(company, estimate_id)


@endpoint()
def acceptance_subject(company, revision_id):
    company_request()
    return service.acceptance_subject(company, revision_id)


@endpoint()
def accepted_baseline_reference(company, acceptance_id):
    company_request()
    return service.accepted_baseline_reference(company, acceptance_id)

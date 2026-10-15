"""Versioned session APIs for authored EST-01 drafts and source libraries."""

from cipher_aec.api.transport import endpoint

from . import service


@endpoint(methods=["POST"])
def register_unit(company, project, operation_id, uom, dimension, quantity_precision):
    return service.register_unit(company, project, operation_id, uom, dimension, quantity_precision)


@endpoint(methods=["POST"])
def create_conversion(company, project, operation_id, definition, source_citations, permission_basis, predecessor=None):
    return service.create_conversion(company, project, operation_id, definition, source_citations, permission_basis, predecessor)


@endpoint(methods=["POST"])
def create_rate(company, project, operation_id, rate, predecessor=None):
    return service.create_rate(company, project, operation_id, rate, predecessor)


@endpoint(methods=["POST"])
def create_assembly(company, project, operation_id, title, basis_unit_id, components, author_basis, conversion_ids, predecessor=None):
    return service.create_assembly(company, project, operation_id, title, basis_unit_id, components, author_basis, conversion_ids, predecessor)


@endpoint(methods=["POST"])
def create_estimate(company, project, operation_id, title, currency, pricing_date):
    return service.create_estimate(company, project, operation_id, title, currency, pricing_date)


@endpoint(methods=["POST"])
def calculate_revision(company, project, operation_id, estimate_id, expected_revision, lines, adjustments, conversion_ids, basis_description, basis_citations):
    return service.calculate_revision(company, project, operation_id, estimate_id, expected_revision, lines, adjustments, conversion_ids, basis_description, basis_citations)


@endpoint()
def get_record(company, project, kind, record_id):
    return service.get_record(company, project, kind, record_id)


@endpoint()
def list_records(company, project, kind, limit=20, cursor=None, count_mode="none"):
    return service.list_records(company, project, kind, limit, cursor, count_mode)


@endpoint()
def list_units(company, project):
    return service.list_units(company, project)

"""Company-scoped canonical API; Project contracts remain separate."""
from cipher_aec.api.transport import endpoint
from cipher_aec.estimating.scopes import company_request
from . import company_service as service


@endpoint(methods=["POST"])
def create_set(company, operation_id, title, discipline, drawing_package, basis):
    company_request()
    return service.create_set(company, operation_id, title, discipline, drawing_package, basis)


@endpoint(methods=["POST"])
def create_calibration(company, operation_id, takeoff_set, source, definition, conversion_ids, predecessor=None):
    company_request()
    return service.create_calibration(company, operation_id, takeoff_set, source, definition, conversion_ids, predecessor)


@endpoint(methods=["POST"])
def create_measurement(company, operation_id, takeoff_set, source, definition, conversion_ids, predecessor=None):
    company_request()
    return service.create_measurement(company, operation_id, takeoff_set, source, definition, conversion_ids, predecessor)


@endpoint(methods=["POST"])
def bind_line(company, operation_id, measurement_id, estimate_line_record, quantity_basis, reason):
    company_request()
    return service.bind_line(company, operation_id, measurement_id, estimate_line_record, quantity_basis, reason)


@endpoint()
def get_record(company, kind, record_id):
    company_request()
    return service.get_record(company, kind, record_id)


@endpoint()
def list_records(company, kind, takeoff_set=None, limit=20, cursor=None, count_mode='none'):
    company_request()
    return service.list_records(company, kind, takeoff_set, limit, cursor, count_mode)


@endpoint()
def drawing_impact(company, revision_id):
    company_request()
    return service.drawing_impact(company, revision_id)


@endpoint()
def compare_measurements(company, before_id, after_id):
    company_request()
    return service.compare_measurements(company, before_id, after_id)

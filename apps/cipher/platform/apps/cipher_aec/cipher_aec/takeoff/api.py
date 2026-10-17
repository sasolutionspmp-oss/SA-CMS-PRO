"""Additive source-bound takeoff APIs; no automatic model geometry."""
from cipher_aec.api.transport import endpoint
from . import service


@endpoint(methods=["POST"])
def create_set(company, project, operation_id, title, discipline, drawing_package, basis):
    return service.create_set(company, project, operation_id, title, discipline, drawing_package, basis)


@endpoint(methods=["POST"])
def create_calibration(company, project, operation_id, takeoff_set, source, definition, conversion_ids, predecessor=None):
    return service.create_calibration(company, project, operation_id, takeoff_set, source, definition, conversion_ids, predecessor)


@endpoint(methods=["POST"])
def create_measurement(company, project, operation_id, takeoff_set, source, definition, conversion_ids, predecessor=None):
    return service.create_measurement(company, project, operation_id, takeoff_set, source, definition, conversion_ids, predecessor)


@endpoint(methods=["POST"])
def bind_line(company, project, operation_id, measurement_id, estimate_line_record, quantity_basis, reason):
    return service.bind_line(company, project, operation_id, measurement_id, estimate_line_record, quantity_basis, reason)


@endpoint()
def get_record(company, project, kind, record_id):
    return service.get_record(company, project, kind, record_id)


@endpoint()
def list_records(company, project, kind, takeoff_set=None, limit=20, cursor=None, count_mode="none"):
    return service.list_records(company, project, kind, takeoff_set, limit, cursor, count_mode)


@endpoint()
def drawing_impact(company, project, revision_id):
    return service.drawing_impact(company, project, revision_id)


@endpoint()
def compare_measurements(company, project, before_id, after_id):
    return service.compare_measurements(company, project, before_id, after_id)

"""Explicit Company entrypoints into the existing canonical domain."""
from cipher_aec.estimating import scopes
from . import service


def create_set(company, operation_id, title, discipline, drawing_package, basis):
    with scopes.activate("Company", company, None):
        return service.create_set(company, None, operation_id, title, discipline, drawing_package, basis)


def create_calibration(company, operation_id, takeoff_set, source, definition, conversion_ids, predecessor=None):
    with scopes.activate("Company", company, None):
        return service.create_calibration(company, None, operation_id, takeoff_set, source, definition, conversion_ids, predecessor)


def create_measurement(company, operation_id, takeoff_set, source, definition, conversion_ids, predecessor=None):
    with scopes.activate("Company", company, None):
        return service.create_measurement(company, None, operation_id, takeoff_set, source, definition, conversion_ids, predecessor)


def bind_line(company, operation_id, measurement_id, estimate_line_record, quantity_basis, reason):
    with scopes.activate("Company", company, None):
        return service.bind_line(company, None, operation_id, measurement_id, estimate_line_record, quantity_basis, reason)


def get_record(company, kind, record_id):
    with scopes.activate("Company", company, None):
        return service.get_record(company, None, kind, record_id)


def list_records(company, kind, takeoff_set=None, limit=20, cursor=None, count_mode='none'):
    with scopes.activate("Company", company, None):
        return service.list_records(company, None, kind, takeoff_set, limit, cursor, count_mode)


def drawing_impact(company, revision_id):
    with scopes.activate("Company", company, None):
        return service.drawing_impact(company, None, revision_id)


def compare_measurements(company, before_id, after_id):
    with scopes.activate("Company", company, None):
        return service.compare_measurements(company, None, before_id, after_id)

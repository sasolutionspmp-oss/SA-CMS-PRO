"""Closed typed Project routes; native services own all effects."""
import frappe
from cipher_aec.api.errors import DomainError
from cipher_aec.api.transport import endpoint
from . import service

def _closed(operation, fields):
    if getattr(frappe.local, 'request', None) is not None:
        values = frappe.form_dict or {}
        if set(values) - set(fields) - {'cmd'} or ('cmd' in values and values['cmd'] != 'cipher_aec.closeout.api.' + operation):
            raise DomainError('invalid_closeout_request', 'Use the exact bounded closeout request contract.', 422)

@endpoint(methods=['POST'])
def create_package(company, project, operation_id, definition, requirements):
    _closed('create_package', ('company', 'project', 'operation_id', 'definition', 'requirements'))
    return service.create_package(company, project, operation_id, definition, requirements)

@endpoint(methods=['POST'])
def revise_package(company, project, operation_id, package_id, expected_version, definition, requirements, amendment_reason=''):
    _closed('revise_package', ('company', 'project', 'operation_id', 'package_id', 'expected_version', 'definition', 'requirements', 'amendment_reason'))
    return service.revise_package(company, project, operation_id, package_id, expected_version, definition, requirements, amendment_reason)

@endpoint(methods=['POST'])
def record_result(company, project, operation_id, package_id, expected_version, requirement_id, definition, evidence, links):
    _closed('record_result', ('company', 'project', 'operation_id', 'package_id', 'expected_version', 'requirement_id', 'definition', 'evidence', 'links'))
    return service.record_result(company, project, operation_id, package_id, expected_version, requirement_id, definition, evidence, links)

@endpoint(methods=['POST'])
def accept_result(company, project, operation_id, package_id, expected_version, result_id, result_digest, comment):
    _closed('accept_result', ('company', 'project', 'operation_id', 'package_id', 'expected_version', 'result_id', 'result_digest', 'comment'))
    return service.accept_result(company, project, operation_id, package_id, expected_version, result_id, result_digest, comment)

@endpoint(methods=['POST'])
def assemble_turnover(company, project, operation_id, package_id, expected_version, comment):
    _closed('assemble_turnover', ('company', 'project', 'operation_id', 'package_id', 'expected_version', 'comment'))
    return service.assemble_turnover(company, project, operation_id, package_id, expected_version, comment)

@endpoint(methods=['POST'])
def accept_turnover(company, project, operation_id, package_id, expected_version, turnover_id, turnover_digest, comment):
    _closed('accept_turnover', ('company', 'project', 'operation_id', 'package_id', 'expected_version', 'turnover_id', 'turnover_digest', 'comment'))
    return service.accept_turnover(company, project, operation_id, package_id, expected_version, turnover_id, turnover_digest, comment)

@endpoint()
def get_record(company, project, kind, record_id):
    _closed('get_record', ('company', 'project', 'kind', 'record_id'))
    return service.get_record(company, project, kind, record_id)

@endpoint()
def list_records(company, project, kind, parent_id=None, limit=25, cursor=None, count_mode='none'):
    _closed('list_records', ('company', 'project', 'kind', 'parent_id', 'limit', 'cursor', 'count_mode'))
    return service.list_records(company, project, kind, parent_id, limit, cursor, count_mode)


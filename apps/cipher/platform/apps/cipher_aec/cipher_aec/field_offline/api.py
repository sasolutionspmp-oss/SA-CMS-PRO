"""Owned opt-in routes; shared registration stays a composition fragment."""
from cipher_aec.api.transport import endpoint
from . import service

import frappe
from cipher_aec.api.errors import DomainError


def _closed_request(operation, fields):
    # Frappe filters kwargs before invocation; validate original field names
    # for reads as well as writes without changing the shared transport.
    if getattr(frappe.local, 'request', None) is not None:
        values = frappe.form_dict or {}
        if set(values) - set(fields) - {'cmd'} or ('cmd' in values and values['cmd'] != 'cipher_aec.field_offline.api.' + operation):
            raise DomainError('invalid_field_offline_request', 'Use the exact bounded field request contract.', 422)


@endpoint(methods=['POST'])
def register_device(company,project,operation_id,device_id,label):
    _closed_request('register_device', ('company', 'project', 'operation_id', 'device_id', 'label'))
    return service.register_device(company,project,operation_id,device_id,label)

@endpoint(methods=['POST'])
def revoke_device(company,project,operation_id,device_id,expected_version,reason):
    _closed_request('revoke_device', ('company', 'project', 'operation_id', 'device_id', 'expected_version', 'reason'))
    return service.revoke_device(company,project,operation_id,device_id,expected_version,reason)

@endpoint(methods=['POST'])
def stage_capture(company,project,operation_id,envelope):
    _closed_request('stage_capture', ('company', 'project', 'operation_id', 'envelope'))
    return service.stage_capture(company,project,operation_id,envelope)

@endpoint()
def get_capture(company,project,capture_id):
    _closed_request('get_capture', ('company', 'project', 'capture_id'))
    return service.get_capture(company,project,capture_id)

@endpoint()
def inspect_capture(company,project,capture_id):
    _closed_request('inspect_capture', ('company', 'project', 'capture_id'))
    return service.inspect_capture(company,project,capture_id)

@endpoint(methods=['POST'])
def apply_capture(company,project,operation_id,capture_id,expected_version):
    _closed_request('apply_capture', ('company', 'project', 'operation_id', 'capture_id', 'expected_version'))
    return service.apply_capture(company,project,operation_id,capture_id,expected_version)

@endpoint(methods=['POST'])
def discard_capture(company,project,operation_id,capture_id,expected_version,reason):
    _closed_request('discard_capture', ('company', 'project', 'operation_id', 'capture_id', 'expected_version', 'reason'))
    return service.discard_capture(company,project,operation_id,capture_id,expected_version,reason)

@endpoint(methods=['POST'])
def resolve_capture(company,project,operation_id,capture_id,expected_version,replacement_envelope,reason):
    _closed_request('resolve_capture', ('company', 'project', 'operation_id', 'capture_id', 'expected_version', 'replacement_envelope', 'reason'))
    return service.resolve_capture(company,project,operation_id,capture_id,expected_version,replacement_envelope,reason)

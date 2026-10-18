"""Typed Project routes; restricted incidents require their own current duties."""
from cipher_aec.api.transport import endpoint
from . import service

import frappe
from cipher_aec.api.errors import DomainError


def _closed_request(operation, fields):
    # Frappe filters kwargs before invocation; validate original field names
    # for reads as well as writes without changing the shared transport.
    if getattr(frappe.local, 'request', None) is not None:
        values = frappe.form_dict or {}
        if set(values) - set(fields) - {'cmd'} or ('cmd' in values and values['cmd'] != 'cipher_aec.quality_safety.api.' + operation):
            raise DomainError('invalid_quality_safety_request', 'Use the exact bounded field request contract.', 422)


@endpoint(methods=['POST'])
def upload_evidence(company,project,operation_id,title,filename,content_base64,byte_length,sha256,rights_basis,permission_evidence):
    _closed_request('upload_evidence', ('company', 'project', 'operation_id', 'title', 'filename', 'content_base64', 'byte_length', 'sha256', 'rights_basis', 'permission_evidence'))
    from .evidence import upload_evidence as upload
    return upload(company,project,operation_id,title,filename,content_base64,byte_length,sha256,rights_basis,permission_evidence)

@endpoint(methods=['POST'])
def create_record(company,project,operation_id,family,category,definition,evidence):
    _closed_request('create_record', ('company', 'project', 'operation_id', 'family', 'category', 'definition', 'evidence'))
    return service.create_record(company,project,operation_id,family,category,definition,evidence)

@endpoint(methods=['POST'])
def revise_record(company,project,operation_id,family,record_id,expected_version,definition,evidence,amendment_reason=''):
    _closed_request('revise_record', ('company', 'project', 'operation_id', 'family', 'record_id', 'expected_version', 'definition', 'evidence', 'amendment_reason'))
    return service.revise_record(company,project,operation_id,family,record_id,expected_version,definition,evidence,amendment_reason)

@endpoint(methods=['POST'])
def transition(company,project,operation_id,family,record_id,expected_version,action,comment,evidence,closure):
    _closed_request('transition', ('company', 'project', 'operation_id', 'family', 'record_id', 'expected_version', 'action', 'comment', 'evidence', 'closure'))
    return service.transition(company,project,operation_id,family,record_id,expected_version,action,comment,evidence,closure)

@endpoint()
def get_record(company,project,kind,record_id):
    _closed_request('get_record', ('company', 'project', 'kind', 'record_id'))
    return service.get_record(company,project,kind,record_id)

@endpoint()
def list_records(company,project,kind,parent_id=None,limit=25,cursor=None,count_mode='none'):
    _closed_request('list_records', ('company', 'project', 'kind', 'parent_id', 'limit', 'cursor', 'count_mode'))
    return service.list_records(company,project,kind,parent_id,limit,cursor,count_mode)

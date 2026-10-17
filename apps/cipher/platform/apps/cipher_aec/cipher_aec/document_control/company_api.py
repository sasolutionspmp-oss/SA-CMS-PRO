"""Explicit Company-owned reusable library endpoints; no Project inference."""
from cipher_aec.api.transport import endpoint
from . import shared

@endpoint(methods=['POST'])
def set_rights(company, operation_id, document_id, expected_version, definition):
    return shared.set_rights(company,operation_id,document_id,expected_version,definition)

@endpoint(methods=['POST'])
def create_library(company, operation_id, definition, artifact):
    return shared.library(company,operation_id,definition,artifact)

@endpoint(methods=['POST'])
def revise_library(company, operation_id, library_id, expected_version, definition, artifact):
    return shared.library(company,operation_id,definition,artifact,library_id,expected_version)

@endpoint()
def get_record(company, kind, record_id):
    return shared.get_record(company,kind,record_id)

@endpoint()
def list_records(company, kind, parent_id=None, limit=25, cursor=None, count_mode='none'):
    return shared.list_records(company,kind,parent_id,limit,cursor,count_mode)

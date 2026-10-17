"""Typed field routes use the same documentary services as native commands."""
from cipher_aec.api.transport import endpoint
from . import service

@endpoint(methods=['POST'])
def create_record(company,project,operation_id,family,definition,photos,quantities):
    return service.create_record(company,project,operation_id,family,definition,photos,quantities)

@endpoint(methods=['POST'])
def revise_record(company,project,operation_id,family,record_id,expected_version,definition,photos,quantities,amendment_reason=''):
    return service.revise_record(company,project,operation_id,family,record_id,expected_version,definition,photos,quantities,amendment_reason)

@endpoint(methods=['POST'])
def transition(company,project,operation_id,family,record_id,expected_version,action,comment,evidence,acknowledged_by=''):
    return service.transition(company,project,operation_id,family,record_id,expected_version,action,comment,evidence,acknowledged_by)

@endpoint()
def get_record(company,project,kind,record_id):return service.get_record(company,project,kind,record_id)

@endpoint()
def list_records(company,project,kind,parent_id=None,limit=25,cursor=None,count_mode='none'):
    return service.list_records(company,project,kind,parent_id,limit,cursor,count_mode)

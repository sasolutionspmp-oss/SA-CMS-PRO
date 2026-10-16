"""Adopted Project facts require explicit WBS/budget and Project access."""
from cipher_aec.api.transport import endpoint
from . import service

@endpoint()
def get_record(company,project,kind,record_id):return service.get_record(company,project,kind,record_id)
@endpoint()
def list_records(company,project,kind,limit=50,cursor=None,count_mode='none'):return service.list_records(company,project,kind,limit,cursor,count_mode)

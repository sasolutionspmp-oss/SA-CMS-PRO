"""Fixed Company cost-master namespace; no Project inference."""
from cipher_aec.api.transport import endpoint
from . import masters,service

@endpoint(methods=['POST'])
def create_master(company,operation_id,kind,code,definition):return masters.create_master(company,operation_id,kind,code,definition)
@endpoint(methods=['POST'])
def revise_master(company,operation_id,kind,master_id,expected_version,definition):return masters.revise_master(company,operation_id,kind,master_id,expected_version,definition)
@endpoint()
def get_revision(company,kind,revision_id,basis_date):return service.get_revision(company,kind,revision_id,basis_date)
@endpoint()
def list_masters(company,kind,basis_date,limit=50,cursor=None,count_mode='none'):return service.list_masters(company,kind,basis_date,limit,cursor,count_mode)

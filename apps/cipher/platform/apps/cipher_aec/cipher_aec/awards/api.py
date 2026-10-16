"""Fixed Company-origin full-award routes; execution uses the shared approval API."""
from cipher_aec.api.transport import endpoint
from . import service

@endpoint()
def list_handoffs(company,limit=50,cursor=None,count_mode='none'):return service.list_handoffs(company,limit,cursor,count_mode)
@endpoint()
def get_handoff(company,handoff_id):return service.get_handoff(company,handoff_id)
@endpoint()
def get_plan(company,revision_id):return service.get_plan(company,revision_id)
@endpoint()
def approval_subject(company,revision_id):return service.approval_subject(company,revision_id)
@endpoint()
def delegation_policy(company):return service.delegation_policy(company)
@endpoint()
def team_choices(company,query='',limit=50,cursor=None,count_mode='none'):return service.team_choices(company,query,limit,cursor,count_mode)
@endpoint()
def source_preview(company,issue_id):return service.source_preview(company,issue_id)
@endpoint(methods=['POST'])
def preview_plan(company,handoff_id,expected_version,definition):return service.preview_plan(company,handoff_id,expected_version,definition)
@endpoint(methods=['POST'])
def create_handoff(company,issue_id,operation_id):return service.create_handoff(company,issue_id,operation_id)
@endpoint(methods=['POST'])
def plan_handoff(company,handoff_id,expected_version,definition,operation_id):return service.plan_handoff(company,handoff_id,expected_version,definition,operation_id)

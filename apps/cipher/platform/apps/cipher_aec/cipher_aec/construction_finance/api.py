"""Versioned FIN01 authoring/read APIs. Approval is a separate GOV action."""
from cipher_aec.api.transport import endpoint
from . import service

@endpoint(methods=['POST'])
def create_contract(company, project, operation_id, definition):
    return service.create_contract(company, project, operation_id, definition)

@endpoint(methods=['POST'])
def author_revision(company, project, operation_id, contract_id, expected_version, terms, retainage_policy, lines, source_citations):
    return service.author_revision(company, project, operation_id, contract_id, expected_version, terms, retainage_policy, lines, source_citations)

@endpoint()
def get_record(company, project, kind, record_id):
    return service.get_record(company, project, kind, record_id)

@endpoint()
def list_contracts(company, project, limit=20, cursor=None, count_mode='none'):
    return service.list_contracts(company, project, limit, cursor, count_mode)

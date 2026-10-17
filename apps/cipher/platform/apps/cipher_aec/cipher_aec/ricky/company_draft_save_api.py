"""Explicit human review and save; no draft payload or callback from RPC."""
from cipher_aec.api.transport import endpoint
from .company_service import domain_errors
from . import company_draft_save as service

def _closed_request(fields):
    import frappe
    from cipher_aec.api.errors import DomainError
    if getattr(getattr(frappe,'local',None),'request',None) is not None:
        if set(frappe.form_dict or {}) - set(fields) - {'cmd'}:
            raise DomainError('invalid_draft_save','The draft-save request contains unsupported fields.',422)

@endpoint()
@domain_errors
def draft_save_subject(company, proposal_id):
    _closed_request({"company","proposal_id"})
    return service.draft_save_subject(company, proposal_id)

@endpoint(methods=['POST'])
@domain_errors
def save_draft(company, proposal_id, expected_version, expected_content_digest, mapping_version, expected_payload_digest, operation_id):
    _closed_request({'company','proposal_id','expected_version','expected_content_digest','mapping_version','expected_payload_digest','operation_id'})
    reviewed={'proposal_id':proposal_id,'expected_version':expected_version,'expected_content_digest':expected_content_digest,
        'mapping_version':mapping_version,'expected_payload_digest':expected_payload_digest}
    return service.save_draft(company, reviewed, operation_id)

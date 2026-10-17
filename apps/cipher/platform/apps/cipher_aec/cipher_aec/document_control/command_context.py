"""Choose immutable receipt sources before documentary scope locks.

The command owner holds the canonical actor lock before calling this helper.
This preview selects a lock plan only. The normal locked receipt lookup and
current source authorization must still run before returning a replay.
"""
import json
import frappe
from cipher_aec.api.contracts import digest
from cipher_aec.api.errors import DomainError

def original_or_new(context,actor,company,project,scope_type,operation_id,command,payload):
    request={'command':command,'company':company,'project':project,'payload':payload}
    if scope_type=='Company':request={'scope_type':'Company',**request}
    receipt_name=digest({'person':actor.person_id,'operation_id':operation_id})
    rows=frappe.db.sql('SELECT request_hash,result_json,result_hash,scope_type,company,project FROM `tabCipher Command Receipt` WHERE name=%s',(receipt_name,),as_dict=True)
    if not rows:return context
    if len(rows)!=1:raise DomainError('receipt_integrity','The original command receipt cannot be verified.',409)
    previous=rows[0]
    if previous.request_hash!=digest(request) or (previous.scope_type or 'Project')!=scope_type or previous.company!=company or (previous.project or None)!=(project or None):
        raise DomainError('operation_conflict','This operation ID already belongs to a different request.',409)
    try:result=json.loads(previous.result_json)
    except (ValueError,TypeError):raise DomainError('receipt_integrity','The original command receipt cannot be verified.',409) from None
    if type(result) is not dict or digest(result)!=previous.result_hash:raise DomainError('receipt_integrity','The original command receipt cannot be verified.',409)
    from .locking import for_result
    original=for_result(company,project,result,scope_type=scope_type)
    if original is None:raise DomainError('receipt_integrity','The original documentary source context is unavailable.',409)
    return original

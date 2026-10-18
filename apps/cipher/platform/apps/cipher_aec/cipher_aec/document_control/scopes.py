"""Explicit document-control source scope; null Project grants no Company authority."""
import frappe
from cipher_aec.api.errors import DomainError
from cipher_aec.governance.context import require_company,require_project

def require(company,scope_type,project,actor,ability,*,lock=False):
    if scope_type=='Project' and type(project) is str and project:return require_project(company,project,ability=ability,actor=actor,lock=lock)
    if scope_type=='Company' and project is None:return require_company(company,ability=ability,actor=actor,lock=lock)
    raise DomainError('invalid_document_scope','Declare an explicit Company or Project source scope.',422)

def document(name,company,scope_type,project,actor,*,lock=False):
    require(company,scope_type,project,actor,'document.read',lock=lock)
    row=frappe.get_doc('Cipher Document',name,for_update=lock)
    if row.company!=company or (row.scope_type or 'Project')!=scope_type or (row.project or None)!=(project or None):raise DomainError('not_found','This original source is unavailable.',404)
    from cipher_aec.quality_safety.privacy import authorize_source as authorize_incident_source
    authorize_incident_source(row.as_dict(), actor, lock=lock)
    return row

"""Atomic private canonical upload. No retrospective source reclassification."""
import base64
import hashlib
from cipher_aec.api.errors import DomainError
from cipher_aec.documents.extraction import validate_source,MAX_BYTES
from cipher_aec.documents.core import DocumentService
from cipher_aec.documents.repository import FrappeDocumentRepository
from cipher_aec.documents.storage import FrappeFileStorage
from . import contracts as rules,privacy,service,sources

def upload_evidence(company,project,operation_id,title,filename,content_base64,byte_length,sha256,rights_basis,permission_evidence):
    rules.text(title,'title',200);rules.text(filename,'filename',200);rules.checksum(sha256,'sha256');rules.text(rights_basis,'rights_basis',4000)
    rules.source_list(permission_evidence,'permission_evidence')
    if type(byte_length) is not int or not 1<=byte_length<=MAX_BYTES or type(content_base64) is not str or len(content_base64)>4*((MAX_BYTES+2)//3):
        rules.fail('Upload at most 10 MiB of original evidence bytes.','content_base64')
    try:content=base64.b64decode(content_base64,validate=True)
    except (ValueError,TypeError):rules.fail('Supply canonical base64 original bytes.','content_base64')
    if base64.b64encode(content).decode()!=content_base64 or len(content)!=byte_length or hashlib.sha256(content).hexdigest()!=sha256:
        rules.fail('The original bytes, length and SHA-256 must agree.','sha256')
    # Existing canonical validation admits supported formats and rejects bad
    # signatures; ArtifactError is translated through the same document helper.
    from cipher_aec.documents.service import _call
    _call(lambda:validate_source(content,filename,byte_length,sha256,decode_images=False))
    def effect(actor,_):
        privacy.require_private_upload(company,project,actor,lock=True);privacy.reject_shared_bytes(sha256)
        resolved=sources.resolve(company,project,permission_evidence,actor,lock=True,new_use=True)
        captured=[sources.mapped(s,resolved) for s in permission_evidence];registration=[]
        class PrivateRepository(FrappeDocumentRepository):
            def create_document(self,row):
                registration.append(privacy.register_new_document(row,company,project,actor,rights_basis,captured))
                super().create_document(row)
        from cipher_aec.documents.provenance import authorize
        import frappe
        documents=DocumentService(PrivateRepository('Project'),FrappeFileStorage(),
            lambda c,p,a:service.require_project(c,p,ability=a,actor=actor,lock=True),scope_type='Project',
            source_authorize=lambda row,lock=False:authorize(row,actor,lock=lock),
            allow_unscanned=frappe.conf.get('cipher_site_mode')=='synthetic' and frappe.conf.get('cipher_allow_unscanned_documents') in (1,True,'1'))
        result=_call(lambda:documents.upload(company=company,project=project,title=title,filename=filename,content=content,byte_length=byte_length,sha256=sha256))
        if len(registration)!=1:raise DomainError('incident_evidence_integrity','The exact private registration was not recorded.',409)
        return {'family':'incident','evidence_upload':True,'document':result['document'],'revision':result['revision'],'registration':registration[0],'history_id':None}
    payload={'title':title,'filename':filename,'byte_length':byte_length,'sha256':sha256,'rights_basis':rights_basis,'permission_evidence':permission_evidence}
    return service._command(company,project,operation_id,'incident','upload_evidence',payload,effect,duty='evidence.manage')

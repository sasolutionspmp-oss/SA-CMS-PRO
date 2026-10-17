"""Current authored content-use permission and exact supporting evidence admission."""
from contextvars import ContextVar
from datetime import datetime,timezone
import frappe
from cipher_aec.api.errors import DomainError
from cipher_aec.governance.context import current_actor,require_project
from . import repository as repo
_checking=ContextVar('document_rights_evidence_ancestry',default=())

def today():return datetime.now(timezone.utc).date().isoformat()

def current(document_id,*,lock=False):
    if not frappe.db.exists('DocType','Cipher Source Rights Revision'):return None
    return repo.latest('rights',document_id,lock=lock)

def document_plan(document_ids):
    """Metadata discovery only; no evidence/source authority is granted here."""
    result=set();active=set()
    def visit(name,depth=0):
        if name in active or depth>8:raise DomainError('source_rights_cycle','The bounded source-rights evidence graph is cyclic or too deep.',409)
        if name in result:return
        result.add(name)
        if len(result)>64:raise DomainError('source_rights_limit','The content-permission evidence closure exceeds its bound.',409)
        active.add(name);policy=current(name)
        if policy:visit(policy['evidence_artifact']['document_id'],depth+1)
        active.remove(name)
    for name in sorted(set(document_ids)):visit(name)
    return result

def prelock(document_ids,company,project,actor,*,scope_type='Project'):
    from . import scopes
    planned=document_plan(document_ids)
    for name in sorted(planned):
        if scope_type=='Project':
            from .service import _document
            _document(name,company,project,actor,lock=True)
        else:scopes.document(name,company,scope_type,project,actor,lock=True)
    if document_plan(document_ids)!=planned:raise DomainError('source_rights_changed','Content-permission evidence changed concurrently. Retry the original request.',503)

def verify_evidence(value,actor,*,lock=False):
    from cipher_aec.engineering.sources import artifact
    name=value['parent_id'];stack=_checking.get()
    if name in stack or len(stack)>=8:raise DomainError('source_rights_cycle','The original content-permission evidence is cyclic or too deep.',409)
    token=_checking.set((*stack,name))
    try:
        original=value['evidence_artifact']
        if value['scope_type']=='Company':
            from .shared import artifact as scoped_artifact
            actual=scoped_artifact(value['company'],'Company',None,{k:original[k] for k in ('revision_id','source_sha256')},actor,lock=lock)
        else:actual=artifact(value['company'],value['project'],{k:original[k] for k in ('revision_id','source_sha256')},actor,lock=lock)
        if actual!=original:raise DomainError('source_rights_evidence','The exact original permission evidence cannot be verified.',409)
    finally:_checking.reset(token)

def require(document_id,company,project,operation,actor,*,lock=False,required=True,scope_type='Project'):
    from . import scopes
    scopes.require(company,scope_type,project,actor,'document.read',lock=lock)
    value=current(document_id)
    if value is None:
        if required:raise DomainError('source_rights_required','Record the current authored rights basis before documentary ingestion or distribution.',409)
        return None
    if lock:
        prelock([document_id],company,project,actor,scope_type=scope_type);value=current(document_id,lock=True)
    if value['company']!=company or value['project']!=project or value['scope_type']!=scope_type:raise DomainError('document_control_integrity','The current rights policy has a different Project.',409)
    now=today()
    if value['valid_from'] and now<value['valid_from'] or value['valid_until'] and now>value['valid_until']:raise DomainError('source_rights_inactive','The current content-use permission is not effective on this UTC date.',403)
    if not value[operation+'_allowed']:raise DomainError('source_rights_denied','Current authored source rights do not permit this '+operation+'.',403)
    verify_evidence(value,actor,lock=lock)
    return value

def authorize(row,actor,*,lock=False):
    scope_type=row.get('scope_type') or 'Project'
    document_id=row.get('document') or row.get('name')
    if document_id:require(document_id,row['company'],row['project'],'read',actor,lock=lock,required=False,scope_type=scope_type)

def distribution(value,company,project,actor,*,lock=False):
    names={row['document_id'] for key in ('source_citations','drawing_references','artifacts') for row in value.get(key,[])}
    governed={name for name in names if current(name) is not None}
    if lock and governed:prelock(governed,company,project,actor)
    for name in sorted(governed):require(name,company,project,'distribute',actor,lock=lock,required=False)

def query(doctype,user=None):
    """Bounded evidence admission before generic native counts/Long Text reads."""
    if not frappe.db.exists('DocType','Cipher Source Rights Revision'):return '1=1'
    actor=current_actor(user)
    rows=frappe.db.sql('SELECT r.parent_id,r.company,r.project,r.scope_type FROM `tabCipher Source Rights Revision` r WHERE NOT EXISTS (SELECT 1 FROM `tabCipher Source Rights Revision` n WHERE n.parent_id=r.parent_id AND n.revision_number>r.revision_number) ORDER BY r.parent_id LIMIT 501',as_dict=True)
    if len(rows)>500:return '1=0'
    denied=[]
    for row in rows:
        try:require(row.parent_id,row.company,row.project,'read',actor,scope_type=row.scope_type)
        except DomainError:denied.append(row.parent_id)
    if not denied:return '1=1'
    identity='name' if doctype=='Cipher Document' else 'document'
    return '`tab'+doctype+'`.'+identity+' NOT IN ('+','.join(frappe.db.escape(name) for name in denied)+')'

"""Company-owned reusable library; original and target authority stay independent."""
from copy import deepcopy
import hashlib
from uuid import uuid4
from cipher_aec.api.contracts import digest
from cipher_aec.api.errors import DomainError
from cipher_aec.api.paging import page_options,decode_cursor,page_result,signing_secret
from cipher_aec.governance.context import current_actor,require_company,require_project,authority_fingerprint
from . import contracts as rules,repository as repo,rights,service,scopes
COMPANY_KINDS=frozenset(('rights','library','library_revision'))

def origin(value):
    rules.closed(value,{'scope_type','project'})
    if value['scope_type']=='Company' and value['project'] is None:return value
    if value['scope_type']=='Project' and type(value['project']) is str and value['project']:rules.text(value['project'],'library_scope.project',140);return value
    raise DomainError('invalid_document_scope','Choose an explicit original Company or Project library scope.',422)

def artifact(company,scope_type,project,reference,actor,*,lock=False):
    from cipher_aec.documents.service import source_reference,company_source_reference
    actual=(company_source_reference(company,reference['revision_id'],1,actor=actor,lock=lock) if scope_type=='Company' and project is None else source_reference(company,project,reference['revision_id'],1,actor=actor,lock=lock) if scope_type=='Project' and project else None)
    if actual is None:raise DomainError('invalid_document_scope','An explicit artifact source scope is required.',422)
    content=actual.pop('content')
    if type(content) is not bytes or len(content)!=actual['byte_length'] or hashlib.sha256(content).hexdigest()!=reference['source_sha256'] or actual['source_sha256']!=reference['source_sha256']:raise DomainError('document_control_integrity','The retained source bytes differ from their exact original.',409)
    return {k:actual[k] for k in ('document_id','revision_id','revision_number','source_sha256','byte_length','mime_type','page_count')}

def artifact_scope(company,reference):
    from cipher_aec.documents.repository import FrappeDocumentRepository
    row=FrappeDocumentRepository().revision_scope(reference['revision_id']);kind=row.scope_type or 'Project'
    if row.company!=company or kind not in ('Company','Project') or (kind=='Company' and row.project is not None) or (kind=='Project' and not row.project):raise DomainError('not_found','This exact original source is unavailable.',404)
    return kind,row.project

def verify_artifacts(value,company,actor,*,operation='read',lock=False):
    for row in value:
        scope,project=artifact_scope(company,row)
        rights.require(row['document_id'],company,project,operation,actor,lock=lock,scope_type=scope)
        if artifact(company,scope,project,{k:row[k] for k in ('revision_id','source_sha256')},actor,lock=lock)!=row:raise DomainError('document_control_integrity','The exact retained original source differs.',409)

def read_origin(kind,name,company,library_scope,actor,*,lock=False):
    origin(library_scope)
    if library_scope['scope_type']=='Project':return service.read(kind,name,company,library_scope['project'],actor,lock=lock)
    return read(kind,name,company,actor,lock=lock)

def raw(kind,name,company,*,lock=False):
    if kind not in COMPANY_KINDS:rules.fail('Choose a Company library or content-permission record.','kind')
    value=repo.raw(kind,name,lock=lock)
    if value['company']!=company or value['scope_type']!='Company' or value['project'] is not None:raise DomainError('not_found','This Company library record is unavailable.',404)
    return value

def read(kind,name,company,actor,*,lock=False):
    require_company(company,ability=rules.READ,actor=actor,lock=lock);value=raw(kind,name,company,lock=lock)
    if kind=='rights':
        scopes.document(value['parent_id'],company,'Company',None,actor,lock=lock);rights.verify_evidence(value,actor,lock=lock)
    elif kind=='library':
        revision=read('library_revision',value['current_revision'],company,actor,lock=lock)
        if revision['parent_id']!=value['id'] or revision['revision_number']!=value['revision_number']:raise DomainError('document_control_integrity','The current Company library family differs.',409)
    else:
        header=raw('library',value['parent_id'],company,lock=lock);previous=raw('library_revision',value['predecessor'],company,lock=lock) if value['predecessor'] else None
        if value['revision_number']>header['revision_number'] or previous and (previous['parent_id']!=value['parent_id'] or previous['revision_number']+1!=value['revision_number']) or not previous and value['revision_number']!=1:raise DomainError('document_control_integrity','The original Company library revision sequence differs.',409)
        verify_artifacts(value['artifacts'],company,actor,lock=lock)
        if any(artifact_scope(company,row)!=('Company',None) for row in value['artifacts']):raise DomainError('document_control_integrity','Company libraries retain explicit Company-owned source artifacts.',409)
    return value

def command(company,operation_id,name,payload,effect,*,ability=rules.WRITE):
    from .locking import DocumentContext
    from cipher_aec.governance.commands import run_company_command
    roots=[];artifacts=[];documents=[]
    if name=='rights.record':documents=[payload['document_id']];artifacts=[payload['definition']['evidence_artifact']]
    else:
        artifacts=[payload['artifact']]
        if payload.get('library_id'):roots=[('library',payload['library_id'])]
    context=DocumentContext(company,None,roots,artifacts=artifacts,documents=documents,scope_type='Company')
    def guard(actor,_):require_company(company,ability=rules.READ,actor=actor,lock=True)
    return run_company_command(company=company,operation_id=operation_id,command='document.control.'+name+'.v1',payload=payload,ability=ability,effect=effect,guard=guard,document_context=context)

def event(actor,value,operation_id,kind,verb):
    from cipher_aec.governance.history import append_company_event
    details={'record_digest':digest(value),'parent_id':value.get('parent_id')}
    return append_company_event(actor=actor,company=value['company'],operation_id=operation_id,event='document.control.'+verb,subject_type=rules.KINDS[kind],subject_id=value['id'],details=details)

def base(company,actor,**fields):return {**service.base(company,None,actor,**fields),'scope_type':'Company','project':None}

def set_rights(company,operation_id,document_id,expected_version,definition):
    rules.rights(definition)
    if expected_version is not None:rules.checksum(expected_version)
    def effect(actor,_):
        scopes.document(document_id,company,'Company',None,actor,lock=True);previous=rights.current(document_id,lock=True)
        if (digest(previous) if previous else None)!=expected_version:raise DomainError('stale_source_rights','Review the exact latest source-rights revision.',412)
        evidence=artifact(company,'Company',None,definition['evidence_artifact'],actor,lock=True)
        if evidence['document_id']==document_id or document_id in rights.document_plan([evidence['document_id']]):raise DomainError('source_rights_cycle','Permission evidence must be a distinct retained document without a circular rights dependency.',409)
        value=base(company,actor,parent_id=document_id,predecessor=previous['id'] if previous else None,revision_number=previous['revision_number']+1 if previous else 1,status='authored_rights_basis',**{**deepcopy(definition),'evidence_artifact':evidence});repo.write('rights',value)
        return {'rights':value,'history_id':event(actor,value,operation_id,'rights','rights.recorded')}
    return command(company,operation_id,'rights.record',{'document_id':document_id,'expected_version':expected_version,'definition':definition},effect,ability=rules.MANAGE)

def library(company,operation_id,definition,artifact_input,library_id=None,expected_version=None):
    rules.library_definition(definition);rules.artifacts([artifact_input])
    if library_id:rules.identifier(library_id);rules.checksum(expected_version)
    def effect(actor,_):
        if library_id:
            header=raw('library',library_id,company,lock=True)
            if digest(header)!=expected_version:raise DomainError('stale_library','Review the exact current Company library head.',412)
            previous=read('library_revision',header['current_revision'],company,actor,lock=True)
        else:header=base(company,actor,current_revision=None,revision_number=0);previous=None
        actual=artifact(company,'Company',None,artifact_input,actor,lock=True);rights.require(actual['document_id'],company,None,'ingest',actor,lock=True,scope_type='Company')
        if not library_id:repo.write('library',header)
        revision=base(company,actor,parent_id=header['id'],predecessor=previous['id'] if previous else None,revision_number=header['revision_number']+1,definition=deepcopy(definition),artifacts=[actual]);repo.write('library_revision',revision)
        final={**header,'current_revision':revision['id'],'revision_number':revision['revision_number']};repo.write('library',final,old=header)
        return {'library':final,'library_revision':revision,'history_id':event(actor,revision,operation_id,'library_revision','library.revised')}
    return command(company,operation_id,'library.revise' if library_id else 'library.create',{'definition':definition,'artifact':artifact_input,'library_id':library_id,'expected_version':expected_version},effect)

def create_adoption(company,project,operation_id,library_scope,library_revision,library_digest,definition):
    origin(library_scope);rules.identifier(library_revision);rules.checksum(library_digest);rules.adoption_definition(definition)
    def effect(actor,_):
        original=read_origin('library_revision',library_revision,company,library_scope,actor,lock=True)
        if digest(original)!=library_digest:raise DomainError('stale_library','Review the exact original reusable library revision.',412)
        verify_artifacts(original['artifacts'],company,actor,operation='ingest',lock=True)
        value=service.base(company,project,actor,parent_id=original['parent_id'],library_scope=deepcopy(library_scope),library_revision=library_revision,library_digest=library_digest,definition=deepcopy(definition),artifacts=deepcopy(original['artifacts']));repo.write('adoption_request',value)
        return {'adoption_request':value,'history_id':service.event(actor,value,operation_id,'adoption_request','adoption.prepared')}
    return service.command(company,project,operation_id,'shared.adoption.prepare',{'library_scope':library_scope,'library_revision':library_revision,'library_digest':library_digest,'definition':definition},effect,ability=rules.ADOPT)

def get_record(company,kind,record_id):
    actor=current_actor();value=read(kind,record_id,company,actor);current=None
    if kind=='library_revision':current=raw('library',value['parent_id'],company)['current_revision']==value['id'] and all(scopes.document(row['document_id'],company,'Company',None,actor).current_revision==row['revision_id'] for row in value['artifacts'])
    return {'record':value,'record_digest':digest(value),'library_current':current}

def list_records(company,kind,parent_id=None,limit=25,cursor=None,count_mode='none'):
    if kind not in COMPANY_KINDS:rules.fail('Choose a supported Company library record kind.','kind')
    limit,cursor,count_mode=page_options(limit,cursor,count_mode)
    if limit>100 or count_mode!='none':rules.fail('Use bounded pages without totals.','paging')
    actor=current_actor();require_company(company,ability=rules.READ,actor=actor)
    scope={'route':'document.control.company.records.v1','company':company,'scope_type':'Company','project':None,'kind':kind,'parent_id':parent_id,'limit':limit,'actor':actor.person_id,'user':actor.user,'authority':authority_fingerprint(actor,company,None)}
    last=decode_cursor(cursor,secret=signing_secret(),scope=scope) if cursor else None;items=[];last_visible=None;scanned=0
    while len(items)<=limit:
        rows=repo.candidates(kind,company,None,parent_id=parent_id,last=last,limit=25,scope_type='Company')
        if not rows:break
        for row in rows:
            scanned+=1
            if scanned>500:raise DomainError('document_list_limit','Narrow the Company library parent filter.',422)
            last=[str(row.creation),row.name]
            try:item=get_record(company,kind,row.name)
            except DomainError as error:
                if error.status in (403,404):continue
                raise
            items.append(item)
            if len(items)>limit:break
            last_visible=last
        if len(items)>limit or len(rows)<25:break
    return page_result(items[:limit],has_more=len(items)>limit,last=last_visible,scope=scope,limit=limit,count_mode='none',total=None)

def authorize_receipt(actor,company,result,*,lock=False):
    require_company(company,ability=rules.READ,actor=actor,lock=lock)
    for kind in COMPANY_KINDS:
        if kind not in result:continue
        original=result[kind]
        if kind=='library':
            current=raw(kind,original['id'],company,lock=lock)
            if any(current[k]!=original[k] for k in ('id','company','project','scope_type','author_person','author_user','created_at')):raise DomainError('document_receipt_integrity','The original Company library identity differs.',409)
            revision=read('library_revision',original['current_revision'],company,actor,lock=lock)
            if revision['parent_id']!=original['id'] or revision['revision_number']!=original['revision_number']:raise DomainError('document_receipt_integrity','The exact original Company library receipt differs.',409)
        elif read(kind,original['id'],company,actor,lock=lock)!=original:raise DomainError('document_receipt_integrity','The original immutable Company documentary result differs.',409)

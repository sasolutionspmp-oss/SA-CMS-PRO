"""Exact retained documentary sources, independent issue/adoption and internal delivery."""
from copy import deepcopy
from contextvars import ContextVar
from uuid import uuid4
import json
import frappe
from cipher_aec.api.contracts import digest,utc_timestamp
from cipher_aec.api.errors import DomainError
from cipher_aec.api.paging import page_options,decode_cursor,page_result,signing_secret
from cipher_aec.governance.context import current_actor,require_project,authority_fingerprint
from cipher_aec.governance.commands import run_command
from cipher_aec.governance.history import append_event
from cipher_aec.engineering import sources
from cipher_aec.documents.repository import FrappeDocumentRepository
from . import contracts as rules,repository as repo,rights
_people=ContextVar('document_control_people',default=None)

def base(company,project,actor,**fields):
    return {'id':str(uuid4()),'company':company,'project':project,'scope_type':'Project','author_person':actor.person_id,'author_user':actor.user,'created_at':utc_timestamp(),'status':'working','no_effects':dict(rules.NO_EFFECTS),**fields}

def raw(kind,name,company,project,*,lock=False):
    if kind not in rules.KINDS:rules.fail('Choose a documentary record kind.','kind')
    value=repo.raw(kind,name,lock=lock)
    if value['company']!=company or value['project']!=project or value['scope_type']!='Project':raise DomainError('not_found','This documentary record is unavailable.',404)
    return value

def event(actor,value,operation_id,kind,verb):
    details={'record_digest':digest(value),'parent_id':value.get('parent_id')}
    if kind=='library':details['header_snapshot']=deepcopy(value)
    return append_event(actor=actor,company=value['company'],project=value['project'],operation_id=operation_id,event='document.control.'+verb,subject_type=rules.KINDS[kind],subject_id=value['id'],details=details)

def command(company,project,operation_id,name,payload,effect,*,ability=rules.WRITE,users=()):
    plan={user:current_actor(user).person_id for user in users}
    def guard(actor,project_doc):
        require_project(company,project,ability=rules.READ,actor=actor,lock=True)
        if ability!=rules.MANAGE and project_doc.status in ('Completed','Cancelled'):raise DomainError('project_closed','This Project is closed for new documentary work.',409)
        if any(current_actor(user).person_id!=person for user,person in plan.items()):raise DomainError('document_people_changed','The exact recipient identities changed.',412)
    token=_people.set(plan)
    try:
        from .locking import for_payload
        context=for_payload(company,project,name,payload,recipient_people=plan)
        options={'document_context':context} if context is not None else {}
        return run_command(company=company,project=project,operation_id=operation_id,command='document.control.'+name+'.v1',payload=payload,ability=ability,guard=guard,effect=effect,participant_people=tuple(sorted(set(plan.values()))),**options)
    finally:_people.reset(token)

def _document(name,company,project,actor,*,lock=False):
    rules.text(name,'document_id',140);require_project(company,project,ability='document.read',actor=actor,lock=lock)
    value=frappe.get_doc('Cipher Document',name,for_update=lock)
    if value.company!=company or value.project!=project or (value.scope_type or 'Project')!='Project':raise DomainError('not_found','This original Project document is unavailable.',404)
    return value

def _prelock(artifacts,company,project,actor,*,lock=False,allow_foreign=False):
    # The full immutable closure is known before the first native Document lock.
    locators=[FrappeDocumentRepository().revision_scope(row['revision_id']) for row in artifacts]
    if allow_foreign and any(row.project!=project or (row.scope_type or 'Project')!='Project' for row in locators):
        if lock:
            from .locking import DocumentContext
            with DocumentContext(company,project,artifacts=artifacts).hold(actor):pass
        return
    if any(row.company!=company or row.project!=project or (row.scope_type or 'Project')!='Project' for row in locators):raise DomainError('not_found','This original Project source is unavailable.',404)
    if lock:rights.prelock({row.document for row in locators},company,project,actor)

def verify_artifacts(artifacts,company,project,actor,*,operation='read',lock=False):
    locators=[FrappeDocumentRepository().revision_scope(row['revision_id']) for row in artifacts]
    if any(row.company!=company or row.project!=project or (row.scope_type or 'Project')!='Project' for row in locators):
        from .shared import verify_artifacts as verify_originals
        return verify_originals(artifacts,company,actor,operation=operation,lock=lock)
    _prelock(artifacts,company,project,actor,lock=lock)
    for row in artifacts:rights.require(row['document_id'],company,project,operation,actor,lock=lock)
    actual=[]
    for offset in range(0,len(artifacts),8):actual.extend(sources.resolve_artifacts(company,project,[{k:row[k] for k in ('revision_id','source_sha256')} for row in artifacts[offset:offset+8]],actor,lock=lock))
    if actual!=artifacts:raise DomainError('document_control_integrity','The retained original artifact bytes or metadata differ.',409)

def resolve(artifacts,company,project,actor,*,lock=False):
    rules.artifacts(artifacts);_prelock(artifacts,company,project,actor,lock=lock)
    result=sources.resolve_artifacts(company,project,artifacts,actor,lock=lock)
    for row in result:rights.require(row['document_id'],company,project,'ingest',actor,lock=lock)
    return result

def set_rights(company,project,operation_id,document_id,expected_version,definition):
    rules.rights(definition)
    if expected_version is not None:rules.checksum(expected_version)
    def effect(actor,_):
        _prelock([definition['evidence_artifact']],company,project,actor,lock=False)
        locator=FrappeDocumentRepository().revision_scope(definition['evidence_artifact']['revision_id'])
        rights.prelock([document_id,locator.document],company,project,actor)
        _document(document_id,company,project,actor,lock=True);previous=rights.current(document_id,lock=True)
        if (digest(previous) if previous else None)!=expected_version:raise DomainError('stale_source_rights','Review the exact current source-rights revision.',412)
        evidence=sources.resolve_artifacts(company,project,[definition['evidence_artifact']],actor,lock=True)[0]
        if evidence['document_id']==document_id:rules.fail('Permission evidence must be a distinct retained original document.','evidence_artifact')
        if document_id in rights.document_plan([evidence['document_id']]):raise DomainError('source_rights_cycle','The permission evidence cannot depend on the governed source itself.',409)
        fields={**deepcopy(definition),'evidence_artifact':evidence}
        value=base(company,project,actor,parent_id=document_id,predecessor=previous['id'] if previous else None,revision_number=previous['revision_number']+1 if previous else 1,status='authored_rights_basis',**fields);repo.write('rights',value)
        return {'rights':value,'history_id':event(actor,value,operation_id,'rights','rights.recorded')}
    return command(company,project,operation_id,'rights.record',{'document_id':document_id,'expected_version':expected_version,'definition':definition},effect,ability=rules.MANAGE)

def _library(company,project,operation_id,definition,artifact,library_id=None,expected_version=None):
    rules.library_definition(definition);rules.artifacts([artifact])
    if library_id:rules.identifier(library_id);rules.checksum(expected_version)
    def effect(actor,_):
        if library_id:
            header=raw('library',library_id,company,project,lock=True)
            if digest(header)!=expected_version:raise DomainError('stale_library','Review the current exact library head.',412)
            prior=raw('library_revision',header['current_revision'],company,project)
            _prelock([artifact,*prior['artifacts']],company,project,actor,lock=True)
            previous=read('library_revision',header['current_revision'],company,project,actor,lock=True)
        else:header=base(company,project,actor,current_revision=None,revision_number=0);previous=None
        actual=resolve([artifact],company,project,actor,lock=True)[0]
        if not library_id:repo.write('library',header)
        value=base(company,project,actor,parent_id=header['id'],predecessor=previous['id'] if previous else None,revision_number=header['revision_number']+1,definition=deepcopy(definition),artifacts=[actual]);repo.write('library_revision',value)
        final={**header,'current_revision':value['id'],'revision_number':value['revision_number']};repo.write('library',final,old=header)
        return {'library':final,'library_revision':value,'history_id':event(actor,value,operation_id,'library_revision','library.revised')}
    return command(company,project,operation_id,'library.revise' if library_id else 'library.create',{'definition':definition,'artifact':artifact,'library_id':library_id,'expected_version':expected_version},effect)

def create_library(company,project,operation_id,definition,artifact):return _library(company,project,operation_id,definition,artifact)
def revise_library(company,project,operation_id,library_id,expected_version,definition,artifact):return _library(company,project,operation_id,definition,artifact,library_id,expected_version)

def create_adoption(company,project,operation_id,library_revision,library_digest,definition):
    rules.identifier(library_revision);rules.checksum(library_digest);rules.adoption_definition(definition)
    def effect(actor,_):
        original=read('library_revision',library_revision,company,project,actor,lock=True)
        if digest(original)!=library_digest:raise DomainError('stale_library','The exact retained library revision differs.',412)
        value=base(company,project,actor,parent_id=original['parent_id'],library_revision=library_revision,library_digest=library_digest,definition=deepcopy(definition),artifacts=deepcopy(original['artifacts']));repo.write('adoption_request',value)
        return {'adoption_request':value,'history_id':event(actor,value,operation_id,'adoption_request','adoption.prepared')}
    return command(company,project,operation_id,'adoption.prepare',{'library_revision':library_revision,'library_digest':library_digest,'definition':definition},effect,ability=rules.ADOPT)

def create_issue_set(company,project,operation_id,definition,artifacts,adoptions):
    rules.issue_definition(definition);rules.sequence(artifacts,'artifacts',8);rules.sequence(adoptions,'adoptions',8)
    for row in adoptions:rules.exact_ref(row)
    if not artifacts and not adoptions:rules.fail('Select an actual original source or adopted revision.','sources')
    if len({r['id'] for r in adoptions})!=len(adoptions):rules.fail('Choose each adoption once.','adoptions')
    def effect(actor,_):
        planned=[a for ref in adoptions for a in raw('adoption',ref['id'],company,project)['artifacts']]
        _prelock([*artifacts,*planned],company,project,actor,lock=True,allow_foreign=True)
        selected=[]
        for ref in adoptions:
            value=read('adoption',ref['id'],company,project,actor,lock=True)
            if digest(value)!=ref['record_digest']:raise DomainError('stale_adoption','The original adoption differs.',412)
            selected.extend(value['artifacts'])
        actual=resolve(artifacts,company,project,actor,lock=True) if artifacts else []
        actual=sources.merge(selected,actual)
        if len(actual)>8:rules.fail('Use at most eight original artifact revisions.','artifacts')
        verify_artifacts(actual,company,project,actor,operation='ingest',lock=True)
        value=base(company,project,actor,definition=deepcopy(definition),artifacts=actual,adoptions=deepcopy(adoptions));value['package_digest']=rules.package_digest(value);repo.write('issue_set',value)
        return {'issue_set':value,'history_id':event(actor,value,operation_id,'issue_set','issue.prepared')}
    return command(company,project,operation_id,'issue.prepare',{'definition':definition,'artifacts':artifacts,'adoptions':adoptions},effect,ability=rules.ISSUE)

def create_transmittal(company,project,operation_id,issue_id,issue_digest,recipients,purpose,required_response):
    rules.identifier(issue_id);rules.checksum(issue_digest);rules.users(recipients,'recipients',1);rules.text(purpose,'purpose',4000);rules.text(required_response,'required_response',4000,blank=True)
    def effect(actor,_):
        original=read('issue',issue_id,company,project,actor,lock=True)
        if digest(original)!=issue_digest:raise DomainError('stale_issue','Select the exact independently issued set.',412)
        from .lifecycle import require_current_issue
        require_current_issue(original,actor,lock=True)
        people=[];plan=_people.get() or {}
        for user in recipients:
            person=current_actor(user)
            if plan.get(user)!=person.person_id:raise DomainError('document_people_changed','The exact intended recipient changed.',412)
            from .locking import recipient_read
            declared={'user':person.user,'person':person.person_id}
            recipient_read({'company':company,'project':project,'issue_id':issue_id,'artifacts':original['artifacts']},declared,actor,lock=True);people.append(declared)
        if len({p['person'] for p in people})!=len(people):rules.fail('Select distinct canonical recipients.','recipients')
        value=base(company,project,actor,parent_id=issue_id,issue_id=issue_id,issue_digest=issue_digest,artifacts=deepcopy(original['artifacts']),recipients=people,purpose=purpose,required_response=required_response,channel='internal',package_digest=original['package_digest']);repo.write('transmittal',value)
        return {'transmittal':value,'history_id':event(actor,value,operation_id,'transmittal','transmittal.prepared')}
    return command(company,project,operation_id,'transmittal.prepare',{'issue_id':issue_id,'issue_digest':issue_digest,'recipients':recipients,'purpose':purpose,'required_response':required_response},effect,ability=rules.DISTRIBUTE,users=recipients)

def record_evidence(company,project,operation_id,subject_kind,subject_id,subject_digest,statement,artifacts):
    if subject_kind not in ('distribution','adoption'):rules.fail('Report receipt of an internal distribution or documentary execution evidence for an adoption.','subject_kind')
    rules.identifier(subject_id);rules.checksum(subject_digest);rules.text(statement,'statement',4000);rules.artifacts(artifacts)
    def effect(actor,_):
        planned=raw(subject_kind,subject_id,company,project)
        _prelock([*artifacts,*planned['artifacts']],company,project,actor,lock=True,allow_foreign=True)
        original=read(subject_kind,subject_id,company,project,actor,lock=True)
        if digest(original)!=subject_digest:raise DomainError('stale_documentary_subject','Select the exact original evidence subject.',412)
        if subject_kind=='distribution' and actor.person_id not in {p['person'] for p in original['recipients']}:raise DomainError('recipient_required','Only an intended canonical recipient may report their receipt.',403)
        value=base(company,project,actor,parent_id=subject_id,subject_kind=subject_kind,subject_id=subject_id,subject_digest=subject_digest,statement=statement,artifacts=resolve(artifacts,company,project,actor,lock=True),status='reported_received' if subject_kind=='distribution' else 'reported_execution',commercial_execution=False,electronic_signature=False);repo.write('evidence',value)
        return {'evidence':value,'history_id':event(actor,value,operation_id,'evidence','evidence.reported')}
    return command(company,project,operation_id,'evidence.report',{'subject_kind':subject_kind,'subject_id':subject_id,'subject_digest':subject_digest,'statement':statement,'artifacts':artifacts},effect)

def read(kind,name,company,project,actor,*,lock=False):
    require_project(company,project,ability=rules.READ,actor=actor,lock=lock);value=raw(kind,name,company,project,lock=lock)
    planned=value.get('artifacts',[])
    if kind=='library':planned=raw('library_revision',value['current_revision'],company,project)['artifacts']
    elif kind=='evidence':planned=[*planned,*raw(value['subject_kind'],value['subject_id'],company,project)['artifacts']]
    if planned:_prelock(planned,company,project,actor,lock=lock,allow_foreign=True)
    if kind=='rights':
        if lock:rights.prelock([value['parent_id'],value['evidence_artifact']['document_id']],company,project,actor)
        _document(value['parent_id'],company,project,actor,lock=lock);rights.verify_evidence(value,actor,lock=lock)
    elif kind=='library':
        current=read('library_revision',value['current_revision'],company,project,actor,lock=lock)
        if current['parent_id']!=value['id'] or current['revision_number']!=value['revision_number']:raise DomainError('document_control_integrity','The current library revision belongs to a different entry or sequence.',409)
    elif kind=='library_revision':
        header=raw('library',value['parent_id'],company,project,lock=lock)
        if value['revision_number']>header['revision_number']:raise DomainError('document_control_integrity','The library sequence differs.',409)
        if value['predecessor'] is None:
            if value['revision_number']!=1:raise DomainError('document_control_integrity','The initial library revision has an invalid sequence.',409)
        else:
            previous=raw('library_revision',value['predecessor'],company,project,lock=lock)
            if previous['parent_id']!=value['parent_id'] or previous['revision_number']+1!=value['revision_number']:raise DomainError('document_control_integrity','The retained library predecessor differs.',409)
        verify_artifacts(value['artifacts'],company,project,actor,lock=lock)
    elif kind=='adoption_request':
        if 'library_scope' in value:
            from .shared import read_origin
            original=read_origin('library_revision',value['library_revision'],company,value['library_scope'],actor,lock=lock)
        else:original=read('library_revision',value['library_revision'],company,project,actor,lock=lock)
        if digest(original)!=value['library_digest'] or original['parent_id']!=value['parent_id'] or original['artifacts']!=value['artifacts']:raise DomainError('document_control_integrity','The adopted original library source differs.',409)
    elif kind=='issue_set':
        if rules.package_digest(value)!=value['package_digest']:raise DomainError('document_control_integrity','The original issue package differs.',409)
        for ref in value['adoptions']:
            original=read('adoption',ref['id'],company,project,actor,lock=lock)
            if digest(original)!=ref['record_digest'] or any(a not in value['artifacts'] for a in original['artifacts']):raise DomainError('document_control_integrity','The original adopted issue dependency differs.',409)
        verify_artifacts(value['artifacts'],company,project,actor,lock=lock)
    elif kind=='transmittal':
        original=read('issue',value['issue_id'],company,project,actor,lock=lock)
        if digest(original)!=value['issue_digest'] or original['artifacts']!=value['artifacts'] or original['package_digest']!=value['package_digest'] or value['parent_id']!=original['id']:raise DomainError('document_control_integrity','The original issued transmittal source differs.',409)
    elif kind=='lifecycle_request':
        from .lifecycle import verify_request
        verify_request(value,actor,lock=lock)
    elif kind=='lifecycle':
        from .lifecycle import verify_event
        verify_event(value,actor,lock=lock)
    elif kind in ('clause_use','redline'):
        from .clauses import verify
        verify(kind,value,actor,lock=lock)
    elif kind in ('issue','adoption','distribution','clause_application'):
        subjectkind={'issue':'issue_set','adoption':'adoption_request','distribution':'transmittal','clause_application':'redline','lifecycle':'lifecycle_request'}[kind];original=read(subjectkind,value['subject_id'],company,project,actor,lock=lock)
        if digest(original)!=value['subject_digest'] or original['artifacts']!=value['artifacts'] or value['parent_id']!=(original['parent_id'] if kind=='lifecycle' else original['id']):raise DomainError('document_control_integrity','The independently authorized original differs.',409)
        if kind in ('issue','distribution') and original['package_digest']!=value['package_digest']:raise DomainError('document_control_integrity','The exact issued byte package differs.',409)
        if kind=='distribution' and original['recipients']!=value['recipients']:raise DomainError('document_control_integrity','The original distribution recipients differ.',409)
        _official_evidence(kind,value,actor,lock=lock)
        if kind=='clause_application' and any(value[k]!=original[k] for k in ('target','target_snapshot','original_text','proposed_text','proposed_sha256','target_changed')):raise DomainError('clause_integrity','The approved documentary relationship differs from its original proposed redline.',409)
        if kind=='distribution' and actor.person_id not in {p['person'] for p in original['recipients']} and actor.person_id!=original['author_person']:
            require_project(company,project,ability=rules.DISTRIBUTE,actor=actor,lock=lock)
    elif kind=='evidence':
        original=read(value['subject_kind'],value['subject_id'],company,project,actor,lock=lock)
        if digest(original)!=value['subject_digest'] or value['parent_id']!=original['id']:raise DomainError('document_control_integrity','The documentary report refers to a different original.',409)
        verify_artifacts(value['artifacts'],company,project,actor,lock=lock)
    return value

def _official_evidence(kind,value,actor,*,lock=False):
    packet=frappe.get_doc('Cipher Approval Packet',value['packet_id'],for_update=lock);decision=frappe.get_doc('Cipher Approval Decision',value['decision_id'],for_update=lock);outer=json.loads(packet.manifest_json);effect=outer.get('domain',{}).get('effect',{})
    subjectkind={'issue':'issue_set','adoption':'adoption_request','distribution':'transmittal','clause_application':'redline','lifecycle':'lifecycle_request'}[kind]
    consumed=frappe.db.sql('SELECT * FROM `tabCipher Approval Consumption` WHERE packet=%s'+(' FOR UPDATE' if lock else ''),(packet.name,),as_dict=True)
    if packet.company!=value['company'] or packet.project!=value['project'] or (packet.scope_type or 'Project')!='Project' or packet.action!=rules.ACTIONS[subjectkind] or packet.subject_type!=rules.KINDS[subjectkind] or packet.subject_id!=value['subject_id'] or digest(outer)!=packet.manifest_hash or digest(effect)!=value['effect_digest'] or effect.get('schema')!='cipher.document.authorization.v1' or effect.get('subject_digest')!=value['subject_digest'] or decision.packet!=packet.name or decision.manifest_hash!=packet.manifest_hash or decision.decision!='Grant' or decision.actor_person!=value['checked_by_person'] or decision.actor_person==packet.requester_person or len(consumed)!=1:raise DomainError('document_approval_integrity','The independent documentary authorization cannot be verified.',409)
    if kind=='lifecycle':
        original=raw('lifecycle_request',value['subject_id'],value['company'],value['project'],lock=lock)
        expected={'schema':'cipher.document.authorization.v1','action':rules.ACTIONS['lifecycle_request'],'subject_kind':'lifecycle_request','subject_id':original['id'],'subject_digest':digest(original),'artifacts':original['artifacts'],'no_effects':dict(rules.NO_EFFECTS),'electronic_signature':False,'professional_seal':False,'external_delivery':False,'commercial_execution':False,'document_id':original['parent_id'],'before':original['before'],'definition':original['definition'],'replacement':original['replacement'],'expected_version':original['expected_version']}
        if effect!=expected:raise DomainError('document_approval_integrity','The consumed lifecycle effect differs from its exact original request.',409)
    consumed=consumed[0]
    if consumed.decision!=decision.name or consumed.actor_person!=value['author_person'] or consumed.actor_person!=packet.requester_person or consumed.company!=value['company'] or consumed.project!=value['project'] or (consumed.scope_type or 'Project')!='Project' or consumed.result_hash!=digest({kind:value}):raise DomainError('document_approval_integrity','The exact consumed documentary effect differs.',409)

def get_record(company,project,kind,record_id):
    actor=current_actor();value=read(kind,record_id,company,project,actor);current=None
    if kind in ('library_revision','adoption_request','adoption'):
        source=value
        if kind=='adoption':source=read('adoption_request',value['subject_id'],company,project,actor)
        if 'library_scope' in source:
            from .shared import read_origin
            revision=read_origin('library_revision',source['library_revision'],company,source['library_scope'],actor)
            if source['library_scope']['scope_type']=='Company':
                from .shared import raw as raw_company
                header=raw_company('library',revision['parent_id'],company)
            else:header=raw('library',revision['parent_id'],company,source['library_scope']['project'])
            from .scopes import document
            current=header['current_revision']==revision['id'] and all(document(row['document_id'],company,source['library_scope']['scope_type'],source['library_scope']['project'],actor).current_revision==row['revision_id'] for row in revision['artifacts'])
        else:
            revision=source if kind=='library_revision' else read('library_revision',source['library_revision'],company,project,actor)
            current=raw('library',revision['parent_id'],company,project)['current_revision']==revision['id'] and all(_document(row['document_id'],company,project,actor).current_revision==row['revision_id'] for row in revision['artifacts'])
    return {'record':value,'record_digest':digest(value),'library_current':current}

def list_records(company,project,kind,parent_id=None,limit=25,cursor=None,count_mode='none'):
    if kind not in rules.KINDS:rules.fail('Choose a documentary record kind.','kind')
    limit,cursor,count_mode=page_options(limit,cursor,count_mode)
    if limit>100 or count_mode!='none':rules.fail('Use bounded pages with no total.','paging')
    actor=current_actor();require_project(company,project,ability=rules.READ,actor=actor)
    scope={'route':'document.control.records.v1','company':company,'project':project,'kind':kind,'parent_id':parent_id,'limit':limit,'actor':actor.person_id,'user':actor.user,'authority':authority_fingerprint(actor,company,project)}
    last=decode_cursor(cursor,secret=signing_secret(),scope=scope) if cursor else None;items=[];last_visible=None;scanned=0
    while len(items)<=limit:
        rows=repo.candidates(kind,company,project,parent_id=parent_id,last=last,limit=25)
        if not rows:break
        for row in rows:
            scanned+=1
            if scanned>500:raise DomainError('document_list_limit','Narrow the documentary parent filter.',422)
            last=[str(row.creation),row.name]
            try:item=get_record(company,project,kind,row.name)
            except DomainError as error:
                if error.status in (403,404):continue
                raise
            items.append(item)
            if len(items)>limit:break
            last_visible=last
        if len(items)>limit or len(rows)<25:break
    return page_result(items[:limit],has_more=len(items)>limit,last=last_visible,scope=scope,limit=limit,count_mode='none',total=None)

def authorize_receipt(actor,company,project,result,*,lock=False):
    require_project(company,project,ability=rules.READ,actor=actor,lock=lock)
    for kind in rules.KINDS:
        if kind not in result:continue
        value=result[kind]
        if kind=='library':
            current=raw(kind,value['id'],company,project,lock=lock)
            if any(current[k]!=value[k] for k in ('id','company','project','scope_type','author_person','author_user','created_at')):raise DomainError('document_receipt_integrity','The original library identity differs.',409)
            if value['current_revision']:
                original=read('library_revision',value['current_revision'],company,project,actor,lock=lock)
                if original['parent_id']!=value['id'] or original['revision_number']!=value['revision_number']:raise DomainError('document_receipt_integrity','The original library receipt has a different exact revision.',409)
        elif read(kind,value['id'],company,project,actor,lock=lock)!=value:raise DomainError('document_receipt_integrity','The original immutable documentary result differs.',409)

def list_people(company,project,limit=25,cursor=None,count_mode='none'):
    # Reuse the scoped selector implementation with the literal DOC03 read duty.
    from .selectors import people
    return people(company,project,limit,cursor,count_mode)

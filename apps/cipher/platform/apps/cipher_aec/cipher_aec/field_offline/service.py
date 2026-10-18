"""Explicit FLD-02 reconciliation on FLD-01's canonical Person receipts.

No scheduler, background replay, alternate field writer or financial effect.
All mutations share the caller's Frappe transaction; no commits or network calls.
"""
from copy import deepcopy
from uuid import uuid4
import frappe
from cipher_aec.api.contracts import digest,utc_timestamp
from cipher_aec.api.errors import DomainError
from cipher_aec.governance.context import current_actor,require_project,require_effects_enabled
from cipher_aec.governance.commands import run_command
from cipher_aec.governance.history import append_event
from cipher_aec.field import service as field,sources
from cipher_aec.field import contracts as f
from cipher_aec.document_control import rights
from . import contracts as c,repository as repo
from .spec import business_request

def _base(company,project,actor,**extra):
    return {'id':str(uuid4()),'company':company,'project':project,'scope_type':'Project','author_person':actor.person_id,
            'owner_person':actor.person_id,'author_user':actor.user,'created_at':utc_timestamp(),'status':'recorded',**extra}

def _authorize(company,project,actor,*,write=False,lock=False):
    c.scope(company,project);require_project(company,project,ability='field.read',actor=actor,lock=lock)
    if write:
        project_doc=require_project(company,project,ability='field.write',actor=actor,lock=lock)
        if project_doc.status in ('Completed','Cancelled'):raise DomainError('project_closed','This Project is closed for new offline writes.',409)

def _owned(value,company,project,actor):
    if (value['company'],value['project'],value['scope_type'],value['owner_person'])!=(company,project,'Project',actor.person_id):
        raise DomainError('not_found','This offline capture is not available.',404)
    return value

def _device(company,project,device_id,actor,*,active=False,lock=False):
    c.identifier(device_id)
    value=_owned(repo.raw('device',device_id,lock=lock),company,project,actor)
    if active and value['status']!='active':raise DomainError('field_device_revoked','This device registration is revoked. Register a new device before new capture.',403)
    return value

def _capture(company,project,capture_id,actor,*,lock=False):
    c.identifier(capture_id)
    return _owned(repo.raw('capture',digest({'person':actor.person_id,'capture_id':capture_id}),lock=lock),company,project,actor)

def _version(value,expected):
    c.checksum(expected)
    if digest(value)!=expected:raise DomainError('stale_offline_capture','This offline record changed. Refresh it before continuing.',412)

def _distinct(operation_id,capture_id):
    c.identifier(operation_id)
    if operation_id==capture_id:raise DomainError('field_capture_operation_reserved','The capture UUID is reserved for its original field command.',409)

def _admit(action,company,project,actor):
    return repo._operation.set({'action':action,'person':actor.person_id,'company':company,'project':project})

def _run(company,project,operation_id,action,payload,effect):
    actor=current_actor();_authorize(company,project,actor)
    def guard(actor,_):_authorize(company,project,actor,write=True,lock=True)
    def admitted(actor,project_doc):
        token=_admit(action,company,project,actor)
        try:return effect(actor,project_doc)
        finally:repo._operation.reset(token)
    result=run_command(company=company,project=project,operation_id=operation_id,command='offline.field.'+action+'.v1',payload=payload,ability='field.write',effect=admitted,guard=guard)
    authorize_receipt(current_actor(),company,project,result,lock=True)
    return result

def _device_result(value):
    return {'device':{k:value[k] for k in ('device_id','company','project','owner_person','registered_user','status','label')},'device_version':digest(value)}

def _capture_result(value):
    return {'capture':{**{k:value[k] for k in ('capture_id','device_id','company','project','actor_person','actor_user','envelope_digest','status','replaces_capture_id','replacement_capture_id')},'payload_retained':value['envelope'] is not None},'capture_version':digest(value)}

def register_device(company,project,operation_id,device_id,label):
    c.identifier(device_id);f.text(label,'label',140)
    def effect(actor,_):
        existing=repo.raw('device',device_id,lock=True,optional=True)
        if existing is not None:
            _owned(existing,company,project,actor)
            raise DomainError('field_device_exists','This device UUID is already registered. Read its original registration.',409)
        value=_base(company,project,actor,id=device_id,device_id=device_id,registered_user=actor.user,label=label,status='active',revoked_at=None,revocation_reason='')
        repo.write('device',value);return _device_result(value)
    return _run(company,project,operation_id,'register',{'device_id':device_id,'label':label},effect)

def revoke_device(company,project,operation_id,device_id,expected_version,reason):
    c.identifier(device_id);f.text(reason,'reason',2000)
    def effect(actor,_):
        value=_device(company,project,device_id,actor,active=True,lock=True);_version(value,expected_version)
        result={**value,'status':'revoked','revoked_at':utc_timestamp(),'revocation_reason':reason};repo.write('device',result,old=value)
        append_event(actor=actor,company=company,project=project,operation_id=operation_id,event='offline.field.device.revoked',subject_type=repo.KINDS['device'],subject_id=device_id,details={'record_digest':digest(result)})
        return _device_result(result)
    return _run(company,project,operation_id,'revoke',{'device_id':device_id,'expected_version':expected_version,'reason':reason},effect)

def _source_check(envelope,actor,*,lock=False,new_use=False):
    command=envelope['command'];family=command['family']
    refs=[*f.sources_in_definition(command['definition'],family+'_revision'),*[p['source'] for p in command['photos']],*[s for q in command['quantities'] for s in q['sources']]]
    resolved=sources.resolve(envelope['company'],envelope['project'],refs,actor,lock=lock,new_use=new_use)
    for document_id in sorted({r['document_id'] for r in resolved.values()}):
        rights.require(document_id,envelope['company'],envelope['project'],'read',actor,lock=lock,required=True)
    for photo in command['photos']:
        source=sources.mapped(photo['source'],resolved)
        if photo['representation']=='source_image':
            if source['mime_type'] not in ('image/jpeg','image/png') or source['page']!=1 or source['page_count']!=1:f.fail('An original photo needs exact single-image JPEG/PNG evidence.','photos')
        elif source['mime_type']!='application/pdf':f.fail('A PDF-page photo needs exact PDF evidence.','photos')

def _base_revision(envelope,actor,*,lock=False):
    command=envelope['command']
    if command['action']=='create':return None
    base=field.read(command['family']+'_revision',command['base_revision_id'],envelope['company'],envelope['project'],actor,lock=lock)
    if base['parent_id']!=command['record_id'] or digest(base)!=command['base_revision_digest']:
        raise DomainError('field_offline_base_integrity','Choose the exact original base revision and digest.',409)
    return base

def _new_capture(envelope,actor,*,replaces=None,lock=True):
    company,project=envelope['company'],envelope['project'];device=_device(company,project,envelope['device_id'],actor,active=True,lock=lock)
    if envelope['actor_person']!=device['owner_person'] or envelope['actor_user']!=device['registered_user']:
        raise DomainError('field_capture_actor','The original capture identity differs from this device registration.',403)
    name=digest({'person':actor.person_id,'capture_id':envelope['capture_id']});existing=repo.raw('capture',name,lock=lock,optional=True)
    if existing:
        _owned(existing,company,project,actor)
        if existing['envelope_digest']!=digest(envelope) or existing['replaces_capture_id']!=replaces:
            raise DomainError('field_capture_conflict','This capture UUID already has different immutable content or lineage.',409)
        if existing['status']!='staged':raise DomainError('field_capture_closed','This capture already has a final disposition. Read its original receipt.',409)
        _check_participants(existing)
        _source_check(envelope,actor,lock=lock,new_use=True)
        return existing
    participants={}
    if envelope['command']['family']=='daily':
        user=envelope['command']['definition']['superintendent_user'];participant=current_actor(user);person=participant.person_id
        require_project(company,project,ability='field.read',actor=participant)
        if user==envelope['actor_user'] and person!=envelope['actor_person']:
            raise DomainError('field_identity_changed','The original capture login now identifies another Person. Register and seal a new capture.',412)
        participants[user]=person
    _source_check(envelope,actor,lock=lock,new_use=True);_base_revision(envelope,actor,lock=lock)
    command,_,request_hash=business_request(envelope)
    value=_base(company,project,actor,id=name,device_id=envelope['device_id'],capture_id=envelope['capture_id'],actor_person=envelope['actor_person'],actor_user=envelope['actor_user'],envelope_digest=digest(envelope),envelope=deepcopy(envelope),business_command=command,business_request_hash=request_hash,participant_people=participants,revision_number=1,last_event=None,commit_receipt=None,status='staged',replaces_capture_id=replaces,replacement_capture_id=None)
    repo.write('capture',value);return value

def stage_capture(company,project,operation_id,envelope):
    c.envelope(envelope);_distinct(operation_id,envelope['capture_id'])
    if (company,project)!=(envelope['company'],envelope['project']):raise DomainError('not_found','The capture belongs to another scope.',404)
    return _run(company,project,operation_id,'stage',{'envelope':envelope},lambda actor,_:_capture_result(_new_capture(envelope,actor)))

def _original(value,actor,*,lock=False):
    receipt=repo.canonical_receipt(actor.person_id,value['capture_id'],lock=lock)
    if receipt is None:
        if value['status']=='committed':raise DomainError('receipt_integrity','The committed field receipt is missing.',409)
        return None
    if receipt['command']!=value['business_command'] or receipt['request_hash']!=value['business_request_hash'] or (receipt['company'],receipt['project'],receipt['scope_type'])!=(value['company'],value['project'],'Project'):
        raise DomainError('operation_conflict','This capture UUID already belongs to another canonical command.',409)
    result=receipt['result'];field.authorize_receipt(actor,value['company'],value['project'],result,lock=lock)
    # Explicit current policy read checks supplement canonical historical receipt checks.
    refs=[*sources.references(result['revision'],result['family']+'_revision'),*[s for q in result.get('quantities',[]) for s in sources.references(q,'quantity')]]
    resolved=sources.resolve(value['company'],value['project'],refs,actor,lock=lock,new_use=False)
    for docid in sorted({s['document_id'] for s in resolved.values()}):rights.require(docid,value['company'],value['project'],'read',actor,lock=lock,required=True)
    if value['commit_receipt'] and value['commit_receipt']!=_receipt_reference(value,result):raise DomainError('receipt_integrity','The offline pointer differs from its original field receipt.',409)
    return {**deepcopy(result),'operation':{'id':value['capture_id'],'status':'succeeded','replayed':True}}

def _receipt_reference(value,result):
    clean={k:v for k,v in result.items() if k!='operation'}
    return {'operation_id':value['capture_id'],'request_hash':value['business_request_hash'],'result_hash':digest(clean),'header_id':clean['header']['id'],'revision_id':clean['revision']['id']}

def get_capture(company,project,capture_id):
    actor=current_actor();_authorize(company,project,actor);value=_capture(company,project,capture_id,actor)
    if value['envelope'] is not None:_source_check(value['envelope'],actor)
    return {**_capture_result(value),'envelope':deepcopy(value['envelope']),'original_receipt':_original(value,actor)}

def _inspection(value,actor,*,lock=False):
    original=_original(value,actor,lock=lock)
    result={**_capture_result(value),'disposition':value['status'],'conflict':None,'original_receipt':original}
    if original is not None:result['disposition']='committed';return result
    if value['status']!='staged':return result
    _check_participants(value)
    _device(value['company'],value['project'],value['device_id'],actor,active=True,lock=lock)
    envelope=value['envelope'];command=envelope['command'];base=_base_revision(envelope,actor,lock=lock)
    current=None
    if base is not None:
        current=field.read(command['family'],command['record_id'],value['company'],value['project'],actor,lock=lock)
        if current['current_revision']!=command['base_revision_id'] or digest(current)!=command['expected_version'] or current['status'] not in ('draft','returned','accepted','acknowledged'):
            revision=field.read(command['family']+'_revision',current['current_revision'],value['company'],value['project'],actor,lock=lock)
            result.update(disposition='conflict',conflict={'code':'base_changed' if current['current_revision']!=command['base_revision_id'] or digest(current)!=command['expected_version'] else 'record_state_changed','current_header_version':digest(current),'current_revision_id':revision['id'],'current_revision_digest':digest(revision)})
    try:_source_check(envelope,actor,lock=lock,new_use=True)
    except DomainError as error:
        if error.code not in ('stale_field_source','field_source_changed','artifact_unavailable','revision_conflict'):raise
        result.update(disposition='conflict',conflict={'code':'source_changed','current_header_version':digest(current) if current else None,'current_revision_id':current['current_revision'] if current else None,'current_revision_digest':None})
    if result['conflict'] is None:result['disposition']='ready'
    return result

def inspect_capture(company,project,capture_id):
    actor=current_actor();_authorize(company,project,actor);return _inspection(_capture(company,project,capture_id,actor),actor)

def _change(value,actor,event_type,reason,*,related=None,**updates):
    event_id=str(uuid4());new={**value,**updates,'revision_number':value['revision_number']+1,'last_event':event_id}
    event=_base(value['company'],value['project'],actor,id=event_id,device_id=value['device_id'],capture_id=value['capture_id'],event_type=event_type,prior_digest=digest(value),next_digest=digest(new),reason=reason,related_capture_id=related)
    repo.write('event',event);repo.write('capture',new,old=value);return new

def _check_participants(value):
    for user,person in value['participant_people'].items():
        participant=current_actor(user)
        if participant.person_id!=person:
            raise DomainError('field_identity_changed','A staged participant now identifies another Person. Discard and seal a new capture explicitly.',412)
        require_project(value['company'],value['project'],ability='field.read',actor=participant)

def _lock_apply(company,project,envelope,actor,participants):
    # Same ordered Person-before-binding-before-Project order as canonical commands.
    users=[envelope['command']['definition']['superintendent_user']] if envelope['command']['family']=='daily' else []
    if set(participants)!=set(users) or any(current_actor(user).person_id!=person for user,person in participants.items()):
        raise DomainError('field_identity_changed','A staged participant identity changed. Reconnect again.',412)
    people=sorted({actor.person_id,*participants.values()})
    placeholders=','.join(['%s']*len(people))
    frappe.db.sql('SELECT name FROM `tabCipher Person` WHERE name IN ('+placeholders+') ORDER BY name FOR UPDATE',people)
    if users:frappe.db.sql('SELECT b.name,b.user,u.name FROM `tabCipher Identity Binding` b JOIN `tabUser` u ON u.name=b.user WHERE b.person IN ('+placeholders+') ORDER BY b.name FOR UPDATE',people)
    if any(current_actor(user).person_id!=person for user,person in participants.items()):
        raise DomainError('field_identity_changed','The declared superintendent identity changed. Reconnect again.',412)
    fresh=current_actor(actor.user,lock=True)
    if fresh.person_id!=actor.person_id:raise DomainError('identity_changed','Your identity changed. Reconnect again.',403)
    _authorize(company,project,fresh,write=True,lock=True)

def apply_capture(company,project,operation_id,capture_id,expected_version):
    c.identifier(operation_id);c.identifier(capture_id)
    if operation_id!=capture_id:raise DomainError('operation_conflict','Apply the original capture UUID; do not create another business command.',409)
    actor=current_actor();_authorize(company,project,actor);value=_capture(company,project,capture_id,actor)
    # A historical receipt is a read, distinct from permission for a new command.
    original=_original(value,actor)
    if original is not None:return {**_capture_result(value),'original_receipt':original,'replayed':True}
    _version(value,expected_version)
    if value['status']!='staged':raise DomainError('field_capture_closed','This capture cannot be applied. Read its disposition.',409)
    require_effects_enabled();_lock_apply(company,project,value['envelope'],actor,value['participant_people'])
    value=_capture(company,project,capture_id,actor,lock=True);_version(value,expected_version)
    _device(company,project,value['device_id'],actor,active=True,lock=True)
    inspection=_inspection(value,actor,lock=True)
    if inspection['original_receipt'] is not None:return {**_capture_result(value),'original_receipt':inspection['original_receipt'],'replayed':True}
    if inspection['disposition']!='ready':raise DomainError('field_offline_conflict','Review this capture and prepare a separate replacement UUID.',409,{'disposition':inspection['disposition'],'conflict':inspection['conflict']})
    savepoint='cipher_offline_'+uuid4().hex;frappe.db.savepoint(savepoint)
    token=_admit('apply',company,project,actor)
    try:
        command=value['envelope']['command'];_,payload,_=business_request(value['envelope'])
        result=(field.create_record if command['action']=='create' else field.revise_record)(company,project,capture_id,**payload)
        value=_change(value,actor,'committed','Explicit capture application.',status='committed',commit_receipt=_receipt_reference(value,result))
        return {**_capture_result(value),'original_receipt':result,'replayed':bool(result['operation']['replayed'])}
    except (frappe.QueryDeadlockError,frappe.QueryTimeoutError):frappe.db.rollback();raise
    except Exception:frappe.db.rollback(save_point=savepoint);raise
    finally:repo._operation.reset(token)

def discard_capture(company,project,operation_id,capture_id,expected_version,reason):
    _distinct(operation_id,capture_id);f.text(reason,'reason',2000)
    def effect(actor,_):
        value=_capture(company,project,capture_id,actor,lock=True);_version(value,expected_version)
        if value['envelope'] is None:return _capture_result(value)
        retained=value['status'] in ('committed','superseded');status=value['status'] if retained else 'discarded'
        value=_change(value,actor,'redacted' if retained else 'discarded',reason,status=status,envelope=None)
        return _capture_result(value)
    # Privacy cleanup never reads revoked source text or invokes a field writer.
    return _run(company,project,operation_id,'discard',{'capture_id':capture_id,'expected_version':expected_version,'reason':reason},effect)

def resolve_capture(company,project,operation_id,capture_id,expected_version,replacement_envelope,reason):
    c.envelope(replacement_envelope);_distinct(operation_id,capture_id);_distinct(operation_id,replacement_envelope['capture_id']);f.text(reason,'reason',2000)
    if replacement_envelope['capture_id']==capture_id:raise DomainError('field_capture_conflict','Resolution requires a fresh capture UUID.',409)
    if (replacement_envelope['company'],replacement_envelope['project'])!=(company,project):raise DomainError('not_found','The replacement belongs to another scope.',404)
    def effect(actor,_):
        old=_capture(company,project,capture_id,actor,lock=True);_version(old,expected_version)
        inspection=_inspection(old,actor,lock=True)
        if old['status']!='staged' or inspection['disposition']!='conflict':raise DomainError('field_resolution_required','Resolve an inspected conflict; committed commands require a new business revision.',409)
        oldcmd,newcmd=old['envelope']['command'],replacement_envelope['command']
        if (oldcmd['action'],oldcmd['family'],oldcmd.get('record_id'))!=(newcmd['action'],newcmd['family'],newcmd.get('record_id')):
            raise DomainError('field_resolution_target','Keep the original record/action/family when resolving this conflict.',409)
        new=_new_capture(replacement_envelope,actor,replaces=capture_id)
        if _inspection(new,actor,lock=True)['disposition']!='ready':raise DomainError('field_offline_conflict','The replacement must declare the current base and sources.',409)
        _change(old,actor,'superseded',reason,related=new['capture_id'],status='superseded',replacement_capture_id=new['capture_id'])
        return _capture_result(new)
    return _run(company,project,operation_id,'resolve',{'capture_id':capture_id,'expected_version':expected_version,'replacement_envelope':replacement_envelope,'reason':reason},effect)

def authorize_receipt(actor,company,project,result,*,lock=False):
    _authorize(company,project,actor,lock=lock)
    if 'device' in result:
        original=result['device'];device=_device(company,project,original['device_id'],actor,lock=lock)
        if any(device[k]!=original[k] for k in ('device_id','company','project','owner_person','registered_user','label')):raise DomainError('receipt_integrity','The original device identity differs.',409)
        return
    original=result.get('capture')
    if not isinstance(original,dict):raise DomainError('receipt_integrity','The original capture receipt is unavailable.',409)
    value=_capture(company,project,original['capture_id'],actor,lock=lock)
    if any(value[k]!=original[k] for k in ('capture_id','device_id','company','project','actor_person','actor_user','envelope_digest','replaces_capture_id')):raise DomainError('receipt_integrity','The original capture identity differs.',409)
    # Summary receipts contain no envelope/source text. Full payload and field
    # receipts are separately authorized through get/inspect/apply.

def authorize_history_subject(actor,company,project,subject_type,subject_id,*,lock=False):
    _authorize(company,project,actor,lock=lock)
    if subject_type!=repo.KINDS['device']:raise DomainError('not_found','This offline history subject is not available.',404)
    _device(company,project,subject_id,actor,lock=lock)

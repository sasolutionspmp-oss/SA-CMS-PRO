"""ENG-01 canonical Project commands; source rights apply before every replay."""
from copy import deepcopy
from contextvars import ContextVar
from uuid import uuid4
import frappe
from cipher_aec.api.contracts import digest,utc_timestamp
from cipher_aec.api.errors import DomainError
from cipher_aec.api.paging import page_options,decode_cursor,page_result,signing_secret
from cipher_aec.governance.context import current_actor,require_project,authority_fingerprint
from cipher_aec.governance.commands import run_command
from cipher_aec.governance.history import append_event
from . import contracts as rules,repository as repo,sources


_participant_plan=ContextVar("engineering_participant_plan",default=None)

def _base(company,project,actor,**fields):
    return {'id':str(uuid4()),'company':company,'project':project,'scope_type':'Project','author_person':actor.person_id,
            'author_user':actor.user,'created_at':utc_timestamp(),'status':'working',**fields}

def _scope(value,company,project):
    if value['company']!=company or value['project']!=project or value.get('scope_type')!='Project':
        raise DomainError('not_found','This engineering record is not available.',404)
    return value

def _raw(kind,identifier,company,project,*,lock=False):
    if kind not in rules.KINDS:rules.fail('Choose a registered engineering record kind.','kind')
    return _scope(repo.raw(kind,identifier,lock=lock),company,project)

def _parent(value,kind,company,project,*,lock=False):
    return _raw(kind,value['parent_id'],company,project,lock=lock)

def read(kind,identifier,company,project,actor,*,lock=False):
    require_project(company,project,ability='engineering.read',actor=actor,lock=lock)
    value=_raw(kind,identifier,company,project,lock=lock)
    if kind=='rfi':
        if value['current_revision']:read('rfi_revision',value['current_revision'],company,project,actor,lock=lock)
        if value['response_head']:read('response',value['response_head'],company,project,actor,lock=lock)
        if value['official_response']:read('official_response',value['official_response'],company,project,actor,lock=lock)
    elif kind=='submittal':
        if value['current_submission']:read('submission',value['current_submission'],company,project,actor,lock=lock)
        if value['disposition_head']:read('disposition',value['disposition_head'],company,project,actor,lock=lock)
        if value['official_disposition']:read('official_disposition',value['official_disposition'],company,project,actor,lock=lock)
    elif kind in ('rfi_revision','submission'):
        _parent(value,'rfi' if kind=='rfi_revision' else 'submittal',company,project,lock=lock)
        sources.verify(company,project,value,actor,lock=lock)
    elif kind in ('response','disposition'):
        parent=_parent(value,'rfi' if kind=='response' else 'submittal',company,project,lock=lock)
        original=read('rfi_revision' if kind=='response' else 'submission',value['source_revision'],company,project,actor,lock=lock)
        if original['parent_id']!=parent['id'] or digest(original)!=value['source_digest']:
            raise DomainError('engineering_integrity','This response/disposition has a different immutable source.',409)
        sources.verify(company,project,value,actor,lock=lock)
    elif kind in ('official_response','official_disposition'):
        original=read('response' if kind=='official_response' else 'disposition',value['subject_id'],company,project,actor,lock=lock)
        if original['parent_id']!=value['parent_id'] or digest(original)!=value['subject_digest']:
            raise DomainError('engineering_integrity','This official fact does not match its authorized revision.',409)
        _official_evidence(kind,value,actor,lock=lock)
    elif kind=='transmittal':
        original=read(value['subject']['kind'],value['subject']['id'],company,project,actor,lock=lock)
        if digest(original)!=value['subject_digest'] or rules.package_digest(value)!=value['package_digest']:
            raise DomainError('engineering_integrity','The exact internal transmittal package cannot be verified.',409)
        sources.verify(company,project,value,actor,lock=lock)
    elif kind=='distribution':
        original=read('transmittal',value['subject_id'],company,project,actor,lock=lock)
        if digest(original)!=value['subject_digest'] or original['package_digest']!=value['package_digest']:
            raise DomainError('engineering_integrity','The internal receipt has a different transmittal package.',409)
        _official_evidence(kind,value,actor,lock=lock)
        # Current intended recipient identity and source rights are still required
        # to read an internal inbox item. A record never grants source access.
        if actor.person_id not in {p['person'] for p in original['recipients']} and actor.person_id!=original['author_person']:
            require_project(company,project,ability='engineering.distribute',actor=actor,lock=lock)
    return value

def _users(names,company,project,*,lock=False):
    result=[]
    for user in names:
        observed=current_actor(user)
        plan=_participant_plan.get()
        if lock and (plan is None or plan.get(user)!=observed.person_id):
            raise DomainError('engineering_recipient_changed','A declared participant identity changed. Review the exact people again.',412)
        actor=current_actor(user,lock=lock)
        require_project(company,project,ability='engineering.read',actor=actor,lock=lock)
        result.append({'user':actor.user,'person':actor.person_id})
    if len({p['person'] for p in result})!=len(result):rules.fail('Recipient/responsible aliases must identify distinct canonical people.','recipients')
    return result

def _command(company,project,operation_id,action,payload,effect,*,recipients=(),ability='engineering.write'):
    # Discover the complete participant set before the canonical Person locks.
    # Compare identities before locking any recipient after Project admission.
    plan={user:current_actor(user).person_id for user in recipients}
    def guarded(actor,project_doc):
        for user,person in plan.items():
            if current_actor(user).person_id!=person:
                raise DomainError('engineering_recipient_changed','A declared participant identity changed. Review the exact people again.',412)
        require_project(company,project,ability='engineering.read',actor=actor,lock=True)
        if project_doc.status in ('Completed','Cancelled'):raise DomainError('project_closed','This Project is closed for new engineering work.',409)
    token=_participant_plan.set(plan)
    try:
        return run_command(company=company,project=project,operation_id=operation_id,command='engineering.'+action+'.v1',payload=payload,
            ability=ability,effect=effect,guard=guarded,participant_people=tuple(sorted(set(plan.values()))))
    finally:_participant_plan.reset(token)

def _event(actor,value,operation_id,event,kind):
    details={'record_digest':digest(value),'parent_id':value.get('parent_id'),'technical_only':True}
    if kind in repo.HEADERS:details['header_snapshot']=deepcopy(value)
    return append_event(actor=actor,company=value['company'],project=value['project'],operation_id=operation_id,event='engineering.'+event,
        subject_type=rules.KINDS[kind],subject_id=value['id'],details=details)

def _version(header,expected):
    rules.checksum(expected,'expected_version')
    if digest(header)!=expected:raise DomainError('stale_engineering','The current engineering revision changed. Review it before authoring a successor.',412)

def _revision(kind,header,actor,definition,source_citations,artifacts=None,*,predecessor=None,revision_number=1,drawing_references=None):
    return _base(header['company'],header['project'],actor,parent_id=header['id'],revision_number=revision_number,predecessor=predecessor,
        definition=deepcopy(definition),source_citations=source_citations,artifacts=artifacts or [],drawing_references=drawing_references or [],no_effects=dict(rules.NO_EFFECTS))

def create_rfi(company,project,operation_id,definition,source_citations,drawing_references):
    rules.rfi_definition(definition);rules.question_sources(source_citations,drawing_references)
    def effect(actor,_):
        cited=sources.resolve_citations(company,project,source_citations,actor,lock=True,required=False)
        drawings=sources.resolve_drawings(company,project,drawing_references,actor,lock=True)
        if not set(definition['contract_citation_ids'])<={c['id'] for c in cited}:rules.fail('Contract links must identify exact citations in this RFI.','contract_citation_ids')
        responsible=_users(definition['responsible_users'],company,project,lock=True)
        header=_base(company,project,actor,status='open',number=repo.number('rfi',company,project),revision_number=0,current_revision=None,response_head=None,official_response=None)
        repo.write('rfi',header);revision=_revision('rfi_revision',header,actor,definition,cited,drawing_references=drawings);revision['responsible_people']=responsible;repo.write('rfi_revision',revision)
        final={**header,'revision_number':1,'current_revision':revision['id']};repo.write('rfi',final,old=header)
        return {'rfi':final,'revision':revision,'history_id':_event(actor,revision,operation_id,'rfi.authored','rfi_revision')}
    return _command(company,project,operation_id,'rfi.create',{'definition':definition,'source_citations':source_citations,'drawing_references':drawing_references},effect,recipients=definition['responsible_users'])

def revise_rfi(company,project,operation_id,rfi_id,expected_version,definition,source_citations,drawing_references):
    rules.rfi_definition(definition);rules.question_sources(source_citations,drawing_references)
    def effect(actor,_):
        header=read('rfi',rfi_id,company,project,actor,lock=True);_version(header,expected_version)
        cited=sources.resolve_citations(company,project,source_citations,actor,lock=True,required=False)
        drawings=sources.resolve_drawings(company,project,drawing_references,actor,lock=True)
        if not set(definition['contract_citation_ids'])<={c['id'] for c in cited}:rules.fail('Contract links must identify exact citations in this revision.','contract_citation_ids')
        people=_users(definition['responsible_users'],company,project,lock=True)
        revision=_revision('rfi_revision',header,actor,definition,cited,predecessor=header['current_revision'],revision_number=header['revision_number']+1,drawing_references=drawings);revision['responsible_people']=people;repo.write('rfi_revision',revision)
        final={**header,'revision_number':revision['revision_number'],'current_revision':revision['id'],'response_head':None,'official_response':None,'status':'open'};repo.write('rfi',final,old=header)
        return {'rfi':final,'revision':revision,'history_id':_event(actor,revision,operation_id,'rfi.revised','rfi_revision')}
    return _command(company,project,operation_id,'rfi.revise',{'rfi_id':rfi_id,'expected_version':expected_version,'definition':definition,'source_citations':source_citations,'drawing_references':drawing_references},effect,recipients=definition['responsible_users'])

def create_response(company,project,operation_id,rfi_id,source_revision,expected_version,definition,source_citations,predecessor=None):
    rules.response_definition(definition);rules.citations(source_citations,required=False)
    def effect(actor,_):
        header=read('rfi',rfi_id,company,project,actor,lock=True);_version(header,expected_version)
        if header['status']!='open' or header['current_revision']!=source_revision or header['response_head']!=predecessor:raise DomainError('stale_engineering','Respond to the current exact question and response predecessor.',412)
        original=read('rfi_revision',source_revision,company,project,actor,lock=True)
        old=read('response',predecessor,company,project,actor,lock=True) if predecessor else None
        cited=sources.resolve_citations(company,project,source_citations,actor,lock=True,required=False)
        value=_revision('response',header,actor,definition,cited,predecessor=predecessor,revision_number=old['revision_number']+1 if old else 1);value.update(source_revision=source_revision,source_digest=digest(original));repo.write('response',value)
        final={**header,'response_head':value['id']};repo.write('rfi',final,old=header)
        return {'rfi':final,'response':value,'history_id':_event(actor,value,operation_id,'rfi.response.authored','response')}
    return _command(company,project,operation_id,'rfi.response.create',{'rfi_id':rfi_id,'source_revision':source_revision,'expected_version':expected_version,'definition':definition,'source_citations':source_citations,'predecessor':predecessor},effect)

def create_submittal(company,project,operation_id,definition,artifacts,source_citations):
    rules.submission_definition(definition);rules.artifacts(artifacts);rules.citations(source_citations,required=False)
    def effect(actor,_):
        package=sources.resolve_artifacts(company,project,artifacts,actor,lock=True);cited=sources.resolve_citations(company,project,source_citations,actor,lock=True,required=False)
        reviewer=_users([definition['reviewer_user']],company,project,lock=True)[0]
        header=_base(company,project,actor,status='open',number=repo.number('submittal',company,project),revision_number=0,current_submission=None,disposition_head=None,official_disposition=None)
        repo.write('submittal',header);value=_revision('submission',header,actor,definition,cited,package);value['reviewer']=reviewer;repo.write('submission',value)
        final={**header,'revision_number':1,'current_submission':value['id']};repo.write('submittal',final,old=header)
        return {'submittal':final,'submission':value,'history_id':_event(actor,value,operation_id,'submittal.submitted','submission')}
    return _command(company,project,operation_id,'submittal.create',{'definition':definition,'artifacts':artifacts,'source_citations':source_citations},effect,recipients=[definition['reviewer_user']])

def revise_submission(company,project,operation_id,submittal_id,expected_version,definition,artifacts,source_citations):
    rules.submission_definition(definition);rules.artifacts(artifacts);rules.citations(source_citations,required=False)
    def effect(actor,_):
        header=read('submittal',submittal_id,company,project,actor,lock=True);_version(header,expected_version)
        package=sources.resolve_artifacts(company,project,artifacts,actor,lock=True);cited=sources.resolve_citations(company,project,source_citations,actor,lock=True,required=False)
        reviewer=_users([definition['reviewer_user']],company,project,lock=True)[0]
        value=_revision('submission',header,actor,definition,cited,package,predecessor=header['current_submission'],revision_number=header['revision_number']+1);value['reviewer']=reviewer;repo.write('submission',value)
        final={**header,'revision_number':value['revision_number'],'current_submission':value['id'],'disposition_head':None,'official_disposition':None,'status':'open'};repo.write('submittal',final,old=header)
        return {'submittal':final,'submission':value,'history_id':_event(actor,value,operation_id,'submittal.resubmitted','submission')}
    return _command(company,project,operation_id,'submittal.revise',{'submittal_id':submittal_id,'expected_version':expected_version,'definition':definition,'artifacts':artifacts,'source_citations':source_citations},effect,recipients=[definition['reviewer_user']])

def create_disposition(company,project,operation_id,submittal_id,source_revision,expected_version,definition,source_citations,predecessor=None):
    rules.disposition_definition(definition);rules.citations(source_citations,required=False)
    def effect(actor,_):
        header=read('submittal',submittal_id,company,project,actor,lock=True);_version(header,expected_version)
        if header['current_submission']!=source_revision or header['disposition_head']!=predecessor:raise DomainError('stale_engineering','Review the current submission and disposition predecessor.',412)
        original=read('submission',source_revision,company,project,actor,lock=True)
        if actor.person_id!=original['reviewer']['person']:raise DomainError('designated_reviewer_required','Only the submission\'s designated canonical reviewer may author its disposition.',403)
        if actor.person_id==original['author_person']:raise DomainError('independent_review_required','A submitter cannot disposition their own package through an alias.',403)
        old=read('disposition',predecessor,company,project,actor,lock=True) if predecessor else None
        cited=sources.resolve_citations(company,project,source_citations,actor,lock=True,required=False)
        value=_revision('disposition',header,actor,definition,cited,predecessor=predecessor,revision_number=old['revision_number']+1 if old else 1);value.update(source_revision=source_revision,source_digest=digest(original));repo.write('disposition',value)
        final={**header,'disposition_head':value['id']};repo.write('submittal',final,old=header)
        return {'submittal':final,'disposition':value,'history_id':_event(actor,value,operation_id,'submittal.disposition.authored','disposition')}
    return _command(company,project,operation_id,'submittal.disposition.create',{'submittal_id':submittal_id,'source_revision':source_revision,'expected_version':expected_version,'definition':definition,'source_citations':source_citations,'predecessor':predecessor},effect)


def closure(kind,value,company,project,actor,*,lock=False):
    if kind in ('official_response','official_disposition'):
        sourcekind='response' if kind=='official_response' else 'disposition';return closure(sourcekind,read(sourcekind,value['subject_id'],company,project,actor,lock=lock),company,project,actor,lock=lock)
    if kind in ('response','disposition'):
        original=read('rfi_revision' if kind=='response' else 'submission',value['source_revision'],company,project,actor,lock=lock)
        return sources.merge(original['source_citations'],value['source_citations']),sources.merge(original['artifacts'],value['artifacts']),sources.merge(original['drawing_references'],value['drawing_references'])
    raise DomainError('engineering_distribution_subject','Only an official response or disposition can form an internal package.',422)


def create_transmittal(company,project,operation_id,subject_kind,subject_id,subject_digest,recipients,purpose,required_response):
    if subject_kind not in ('official_response','official_disposition'):rules.fail('Distribute an exact official technical fact.','subject_kind')
    rules.users(recipients,'recipients',minimum=1);rules.checksum(subject_digest);rules.text(purpose,'purpose',2000);rules.text(required_response,'required_response',2000,blank=True)
    def effect(actor,_):
        original=read(subject_kind,subject_id,company,project,actor,lock=True)
        if digest(original)!=subject_digest:raise DomainError('stale_engineering','Select the exact official technical fact.',412)
        selected=_users(recipients,company,project,lock=True)
        cited,package,drawings=closure(subject_kind,original,company,project,actor,lock=True)
        # Raw bytes accompany every cited document even for a textual RFI.
        by_revision={r['revision_id']:{'revision_id':r['revision_id'],'source_sha256':r['source_sha256']} for r in [*cited,*package,*drawings]}
        if len(by_revision)>8:rules.fail('Use a package with at most eight exact artifact revisions.','artifacts')
        package=sources.resolve_artifacts(company,project,list(by_revision.values()),actor,lock=True)
        value=_base(company,project,actor,status='awaiting_independent_authorization',subject={'kind':subject_kind,'id':subject_id},subject_digest=subject_digest,recipients=selected,purpose=purpose,required_response=required_response,channel='internal',source_citations=cited,artifacts=package,drawing_references=drawings,no_effects=dict(rules.NO_EFFECTS))
        value['package_digest']=rules.package_digest(value)
        for recipient in selected:
            target=current_actor(recipient['user'],lock=True)
            sources.verify(company,project,value,target,lock=True)
        repo.write('transmittal',value)
        return {'transmittal':value,'history_id':_event(actor,value,operation_id,'transmittal.prepared','transmittal')}
    return _command(company,project,operation_id,'transmittal.create',{'subject_kind':subject_kind,'subject_id':subject_id,'subject_digest':subject_digest,'recipients':recipients,'purpose':purpose,'required_response':required_response},effect,recipients=recipients,ability='engineering.distribute')


def close_rfi(company,project,operation_id,rfi_id,expected_version,official_response,reason):
    rules.text(reason,'reason',2000)
    def effect(actor,_):
        header=read('rfi',rfi_id,company,project,actor,lock=True);_version(header,expected_version)
        if header['status']!='open' or header['official_response']!=official_response:raise DomainError('official_response_required','Close only the current independently authorized response.',409)
        official=read('official_response',official_response,company,project,actor,lock=True);response=read('response',official['subject_id'],company,project,actor,lock=True)
        if response['source_revision']!=header['current_revision'] or response['id']!=header['response_head']:raise DomainError('stale_engineering','This official answer belongs to a historical question or response.',412)
        final={**header,'status':'closed','closure':{'official_response':official_response,'reason':reason,'person':actor.person_id,'at':utc_timestamp()}};repo.write('rfi',final,old=header)
        return {'rfi':final,'history_id':_event(actor,final,operation_id,'rfi.closed','rfi')}
    return _command(company,project,operation_id,'rfi.close',{'rfi_id':rfi_id,'expected_version':expected_version,'official_response':official_response,'reason':reason},effect)


def get_record(company,project,kind,record_id):
    value=read(kind,record_id,company,project,current_actor())
    return {'record':value,'record_digest':digest(value)}

def list_records(company,project,kind,parent_id=None,limit=25,cursor=None,count_mode='none',subject_id=None):
    if kind not in rules.KINDS:rules.fail('Choose a registered engineering kind.','kind')
    limit,cursor,count_mode=page_options(limit,cursor,count_mode)
    if limit>100 or count_mode!='none':rules.fail('Use a bounded engineering page with no total.','paging')
    actor=current_actor();require_project(company,project,ability='engineering.read',actor=actor)
    if parent_id is not None:rules.identifier(parent_id,'parent_id')
    if subject_id is not None:
        rules.identifier(subject_id,'subject_id')
        if kind not in ('official_response','official_disposition','distribution'):rules.fail('Use subject_id only for an official fact or internal receipt.','subject_id')
    scope={'route':'engineering.records.v1','company':company,'project':project,'kind':kind,'parent_id':parent_id,'subject_id':subject_id,'limit':limit,'actor':actor.person_id,'user':actor.user,'authority':authority_fingerprint(actor,company,project)}
    last=decode_cursor(cursor,secret=signing_secret(),scope=scope) if cursor else None;items=[];last_visible=None;scanned=0
    while len(items)<=limit:
        rows=repo.candidate_rows(kind,company,project,parent_id=parent_id,subject_id=subject_id,last=last,limit=25)
        if not rows:break
        for row in rows:
            scanned+=1
            if scanned>500:raise DomainError('engineering_list_limit','The bounded authorization scan exceeded its scope. Narrow the parent filter.',422)
            last=[str(row.creation),row.name]
            try:value=read(kind,row.name,company,project,actor)
            except DomainError as error:
                if error.status in (403,404):continue
                raise
            items.append({'record':value,'record_digest':digest(value)})
            if len(items)>limit:break
            last_visible=last
        if len(items)>limit or len(rows)<25:break
    return page_result(items[:limit],has_more=len(items)>limit,last=last_visible,scope=scope,limit=limit,count_mode='none',total=None)


def list_people(company,project,limit=25,cursor=None,count_mode='none'):
    """Current scoped identities, not an unfiltered native User directory."""
    limit,cursor,count_mode=page_options(limit,cursor,count_mode)
    if limit>100 or count_mode!='none':rules.fail('Use a bounded people page with no total.','paging')
    actor=current_actor();require_project(company,project,ability='engineering.read',actor=actor)
    scope={'route':'engineering.people.v1','company':company,'project':project,'limit':limit,'actor':actor.person_id,'user':actor.user,'authority':authority_fingerprint(actor,company,project)}
    last=decode_cursor(cursor,secret=signing_secret(),scope=scope) if cursor else None;items=[];last_visible=None;scanned=0
    while len(items)<=limit:
        where="b.active=1 AND p.active=1 AND u.enabled=1 AND EXISTS (SELECT 1 FROM `tabCipher Project Duty` d WHERE d.person=b.person AND d.company=%s AND d.project=%s AND d.scope_type='Project' AND d.ability='engineering.read' AND d.active=1)"
        args=[company,project]
        if last:where+=' AND (b.person>%s OR (b.person=%s AND b.user>%s))';args.extend([last[0],last[0],last[1]])
        rows=frappe.db.sql('SELECT b.user,b.person,p.display_name FROM `tabCipher Identity Binding` b JOIN `tabCipher Person` p ON p.name=b.person JOIN `tabUser` u ON u.name=b.user WHERE '+where+' ORDER BY b.person,b.user LIMIT 25',args,as_dict=True)
        if not rows:break
        for row in rows:
            scanned+=1
            if scanned>500:raise DomainError('engineering_list_limit','The bounded people authorization scan exceeded its scope.',422)
            last=[row.person,row.user]
            try:
                person=current_actor(row.user)
                if person.person_id!=row.person:continue
                require_project(company,project,ability='engineering.read',actor=person)
            except DomainError as error:
                if error.status in (401,403,404):continue
                raise
            items.append({'user':row.user,'person':row.person,'display_name':row.display_name})
            if len(items)>limit:break
            last_visible=last
        if len(items)>limit or len(rows)<25:break
    return page_result(items[:limit],has_more=len(items)>limit,last=last_visible,scope=scope,limit=limit,count_mode='none',total=None)

def _header_snapshot(kind,value,company,project,actor,*,lock=False):
    # Current scope/metadata admission only. A later header's source closure is
    # unrelated to replay of the original immutable command result.
    current=_raw(kind,value['id'],company,project,lock=lock)
    _scope(value,company,project)
    if any(current[k]!=value[k] for k in ('id','company','project','scope_type','author_person','author_user','number','created_at')):
        raise DomainError('engineering_receipt_integrity','Original header identity differs from its scoped record.',409)
    pointers=(('current_revision','rfi_revision'),('response_head','response'),('official_response','official_response')) if kind=='rfi' else (('current_submission','submission'),('disposition_head','disposition'),('official_disposition','official_disposition'))
    for key,sourcekind in pointers:
        if value[key]:
            exact=read(sourcekind,value[key],company,project,actor,lock=lock)
            if exact['parent_id']!=value['id']:raise DomainError('engineering_receipt_integrity','Original header sources belong to another record.',409)


def authorize_receipt(actor,company,project,result,*,lock=False):
    require_project(company,project,ability='engineering.read',actor=actor,lock=lock)
    for key,kind in [(k,k) for k in rules.KINDS]+[('revision','rfi_revision')]:
        if key not in result:continue
        value=result[key]
        if not isinstance(value,dict):raise DomainError('engineering_receipt_integrity','Invalid original engineering receipt.',409)
        if kind in repo.HEADERS:_header_snapshot(kind,value,company,project,actor,lock=lock)
        elif read(kind,value['id'],company,project,actor,lock=lock)!=value:
            raise DomainError('engineering_receipt_integrity','Original engineering receipt differs from its immutable source.',409)


def _official_evidence(kind,value,actor,*,lock=False):
    subjectkind={'official_response':'response','official_disposition':'disposition','distribution':'transmittal'}[kind]
    packet=frappe.get_doc('Cipher Approval Packet',value['packet_id'],for_update=lock)
    decision=frappe.get_doc('Cipher Approval Decision',value['decision_id'],for_update=lock)
    import json
    manifest=json.loads(packet.manifest_json)
    effect=manifest.get('domain',{}).get('effect',{})
    rows=frappe.db.sql('SELECT * FROM `tabCipher Approval Consumption` WHERE packet=%s'+(' FOR UPDATE' if lock else ''),(packet.name,),as_dict=True)
    if (packet.company!=value['company'] or packet.project!=value['project'] or (packet.scope_type or 'Project')!='Project'
        or packet.action!=rules.ACTIONS[subjectkind] or packet.subject_type!=rules.KINDS[subjectkind] or packet.subject_id!=value['subject_id']
        or digest(manifest)!=packet.manifest_hash or effect.get('schema')!='cipher.engineering.authorization.v1'
        or effect.get('subject_digest')!=value['subject_digest'] or effect.get('subject_id')!=value['subject_id'] or effect.get('subject_kind')!=subjectkind
        or effect.get('action')!=packet.action or decision.packet!=packet.name or decision.decision!='Grant'
        or decision.manifest_hash!=packet.manifest_hash or decision.actor_person!=value['checked_by_person']
        or decision.actor_person==packet.requester_person or len(rows)!=1):
        raise DomainError('engineering_approval_integrity','The exact independent engineering authorization cannot be verified.',409)
    consumed=rows[0]
    if (consumed.decision!=decision.name or consumed.actor_person!=value['author_person'] or consumed.actor_person!=packet.requester_person
        or consumed.company!=value['company'] or consumed.project!=value['project'] or (consumed.scope_type or 'Project')!='Project'
        or consumed.result_hash!=digest({kind:value})):
        raise DomainError('engineering_approval_integrity','The immutable engineering fact differs from its consumed grant.',409)


def authorize_history(kind,identifier,company,project,actor,*,event,details):
    if kind not in repo.HEADERS:return read(kind,identifier,company,project,actor)
    if kind!='rfi' or event!='engineering.rfi.closed':raise DomainError('engineering_integrity','Unsupported engineering header history.',409)
    snapshot=details.get('header_snapshot')
    if not isinstance(snapshot,dict) or snapshot.get('id')!=identifier or digest(snapshot)!=details.get('record_digest'):
        raise DomainError('engineering_integrity','The exact historical engineering header cannot be verified.',409)
    require_project(company,project,ability='engineering.read',actor=actor)
    _header_snapshot(kind,snapshot,company,project,actor)
    return snapshot

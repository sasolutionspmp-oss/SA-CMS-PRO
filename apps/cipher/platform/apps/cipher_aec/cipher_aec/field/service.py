"""FLD-01 documentary commands; a ticket acknowledgment has no commercial effect."""
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

_participants=ContextVar('cipher_field_participants',default=None)
_command_effect=ContextVar('cipher_field_command_effect',default=None)

def _base(company,project,actor,**fields):
    return {'id':str(uuid4()),'company':company,'project':project,'scope_type':'Project',
        'author_person':actor.person_id,'author_user':actor.user,'created_at':utc_timestamp(),'status':'recorded',**fields}

def _scope(value,company,project):
    if value['company']!=company or value['project']!=project or value['scope_type']!='Project':
        raise DomainError('not_found','This field record is not available.',404)
    return value

def _raw(kind,record_id,company,project,*,lock=False):return _scope(repo.raw(kind,record_id,lock=lock),company,project)

def _revision_kind(family):
    if family not in rules.HEADERS:rules.fail('Choose daily or ticket.','family')
    return family+'_revision'

def _version(header,expected):
    rules.checksum(expected,'expected_version')
    if digest(header)!=expected:raise DomainError('stale_field_record','The current field revision or standing changed. Review it before continuing.',412)

def _person(user,company,project,*,lock=False):
    observed=current_actor(user);plan=_participants.get()
    if lock and (plan is None or plan.get(user)!=observed.person_id):raise DomainError('field_identity_changed','The declared superintendent identity changed. Review it again.',412)
    person=current_actor(user,lock=lock);require_project(company,project,ability='field.read',actor=person,lock=lock)
    return {'user':person.user,'person':person.person_id}

def _collect(kind,record_id,company,project,*,lock=False):
    """Bounded exact fact closure; parents grant neither access nor source authority."""
    collected={}
    def add(kind,record_id):
        key=(kind,record_id)
        if key in collected:return collected[key]
        if len(collected)>=100:raise DomainError('field_lineage_limit','The field source closure exceeds its bound.',409)
        value=_raw(kind,record_id,company,project,lock=lock);collected[key]=value
        if kind in rules.HEADERS:
            # The current package and last accepted original are separate
            # bounded immutable packages. A header exposes the original's ID,
            # not its private source metadata; reading that original authorizes
            # its own exact source closure separately.
            if value['accepted_revision']:
                accepted=_raw(_revision_kind(kind),value['accepted_revision'],company,project,lock=lock)
                if accepted['parent_id']!=value['id']:raise DomainError('field_integrity','The accepted original belongs to a different field record.',409)
            for revision in (value['current_revision'],):
                if revision is None:continue
                child=add(_revision_kind(kind),revision)
                if child['parent_id']!=value['id']:raise DomainError('field_integrity','A field header points outside its own record.',409)
            if value['last_decision']:
                decision=add('decision',value['last_decision'])
                if decision['parent_id']!=value['id'] or decision['source_revision']!=value['current_revision'] or decision['to_status']!=value['status']:
                    raise DomainError('field_integrity','The field standing differs from its exact decision.',409)
            elif value['status']!='draft':raise DomainError('field_integrity','This standing requires its exact documentary decision.',409)
        elif kind in ('daily_revision','ticket_revision'):
            family='daily' if kind=='daily_revision' else 'ticket';parent=_raw(family,value['parent_id'],company,project,lock=lock)
            if value['predecessor']:
                old=_raw(kind,value['predecessor'],company,project,lock=lock)
                if old['parent_id']!=parent['id'] or old['revision_number']+1!=value['revision_number']:raise DomainError('field_integrity','The immutable revision predecessor differs.',409)
            elif value['revision_number']!=1:raise DomainError('field_integrity','A successor revision requires its predecessor.',409)
            if value['amendment_of']:
                amended=_raw(kind,value['amendment_of'],company,project,lock=lock)
                if amended['parent_id']!=parent['id'] or amended['revision_number']>=value['revision_number']:raise DomainError('field_integrity','The amendment identifies a different or later original.',409)
            if kind=='daily_revision':
                if value['superintendent']['user']!=value['definition']['superintendent_user']:raise DomainError('field_integrity','The superintendent identity differs from the authored record.',409)
                for qid in value['quantity_ids']:
                    q=add('quantity',qid)
                    if q['source_revision']!=value['id'] or q['parent_id']!=value['parent_id'] or q['revision_number']!=value['revision_number']:raise DomainError('field_integrity','An installed/delivered quantity belongs to another revision.',409)
        elif kind=='quantity':
            parent=_raw('daily',value['parent_id'],company,project,lock=lock)
            revision=_raw('daily_revision',value['source_revision'],company,project,lock=lock)
            if revision['parent_id']!=parent['id'] or value['id'] not in revision['quantity_ids'] or revision['revision_number']!=value['revision_number']:raise DomainError('field_integrity','The quantity does not belong to its exact daily revision.',409)
            if value['supersedes_event_id']:
                old=_raw('quantity',value['supersedes_event_id'],company,project,lock=lock)
                if old['parent_id']!=parent['id'] or old['original_event_id']!=value['original_event_id'] or old['revision_number']>=value['revision_number']:raise DomainError('field_integrity','The quantity correction has different original capture lineage.',409)
        elif kind=='decision':
            # Metadata discovers a family without permitting a cross-kind fallback.
            matches=[]
            for family in ('daily','ticket'):
                try:parent=_raw(family,value['parent_id'],company,project,lock=lock);matches.append((family,parent))
                except DomainError as error:
                    if error.status!=404:raise
            if len(matches)!=1:raise DomainError('field_integrity','The documentary decision parent cannot be verified.',409)
            family,parent=matches[0];revision=add(_revision_kind(family),value['source_revision'])
            if revision['parent_id']!=parent['id'] or digest(revision)!=value['source_digest']:raise DomainError('field_integrity','The documentary decision differs from its original revision.',409)
            if value['action']!='submit' and value['author_person'] in _authors(revision):raise DomainError('independent_field_review_required','A canonical author or superintendent cannot review their own record.',403)
            if value['action']=='acknowledge' and family!='ticket':raise DomainError('field_integrity','Only a T&M ticket has a customer acknowledgment.',409)
            if value['predecessor']:
                previous=_raw('decision',value['predecessor'],company,project,lock=lock)
                if previous['parent_id']!=value['parent_id'] or previous['source_revision']!=value['source_revision'] or previous['to_status']!=value['from_status']:raise DomainError('field_integrity','The documentary decision chain differs.',409)
            elif value['from_status']!='draft':raise DomainError('field_integrity','A later decision requires its predecessor.',409)
        return value
    result=add(kind,record_id)
    return result,[(k,v) for (k,_),v in collected.items()]

def _authors(revision):
    people={revision['author_person']}
    if 'superintendent' in revision:people.add(revision['superintendent']['person'])
    return people

def read(kind,record_id,company,project,actor,*,lock=False,new_use=False):
    require_project(company,project,ability='field.read',actor=actor,lock=lock)
    value,closure=_collect(kind,record_id,company,project,lock=lock)
    sources.verify(closure,company,project,actor,lock=lock,new_use=new_use)
    return value

def _command(company,project,operation_id,action,payload,effect,*,ability='field.write',participants=()):
    actor=current_actor();require_project(company,project,ability='field.read',actor=actor)
    plan={user:current_actor(user).person_id for user in participants}
    def guarded(actor,project_doc):
        require_project(company,project,ability='field.read',actor=actor,lock=True)
        if project_doc.status in ('Completed','Cancelled'):raise DomainError('project_closed','This Project is closed for new field work.',409)
        for user,person in plan.items():
            if current_actor(user).person_id!=person:raise DomainError('field_identity_changed','A declared superintendent identity changed.',412)
    def admitted(actor,project_doc):
        token=_command_effect.set({'action':action,'person':actor.person_id,'company':company,'project':project})
        try:return effect(actor,project_doc)
        finally:_command_effect.reset(token)
    token=_participants.set(plan)
    try:
        result=run_command(company=company,project=project,operation_id=operation_id,command='field.'+action+'.v1',payload=payload,
            ability=ability,effect=admitted,guard=guarded,participant_people=tuple(sorted(set(plan.values()))))
        # Direct domain retries also fail closed before the shared receipt reader
        # is composed. Shared read_operation requires the supplied dispatch hook.
        authorize_receipt(current_actor(),company,project,result,lock=True)
        return result
    finally:_participants.reset(token)

def _event(actor,value,operation_id,event,kind):
    return append_event(actor=actor,company=value['company'],project=value['project'],operation_id=operation_id,
        event='field.'+event,subject_type=rules.KINDS[kind],subject_id=value['id'],
        details={'record_digest':digest(value),'parent_id':value.get('parent_id'),'documentary_only':True})

def _capture(company,project,actor,family,header,definition,photos,quantities,predecessor=None,reason=''):
    revision_kind=_revision_kind(family)
    refs=[*rules.sources_in_definition(definition,revision_kind),*[p['source'] for p in photos],*[s for q in quantities for s in q['sources']]]
    resolved=sources.resolve(company,project,refs,actor,lock=True,new_use=True)
    authored=deepcopy(definition)
    if family=='daily':authored['weather_sources']=[sources.mapped(s,resolved) for s in definition['weather_sources']]
    else:authored['lines']=[{**line,'sources':[sources.mapped(s,resolved) for s in line['sources']]} for line in definition['lines']]
    value=_base(company,project,actor,parent_id=header['id'],revision_number=header['revision_number']+1,predecessor=predecessor,
        prior_decision=header['last_decision'],amendment_of=header['accepted_revision'],amendment_reason=reason,
        definition=authored,photos=[{**p,'source':sources.mapped(p['source'],resolved)} for p in photos],no_effects=dict(rules.NO_EFFECTS))
    events=[]
    if family=='daily':
        value['superintendent']=_person(definition['superintendent_user'],company,project,lock=True);value['quantity_ids']=[]
        for quantity in quantities:
            existing=repo.captured_events(company,project,quantity['original_event_id'],lock=True)
            previous=read('quantity',quantity['supersedes_event_id'],company,project,actor,lock=True) if quantity['supersedes_event_id'] else None
            if previous:
                oldrevision=_raw('daily_revision',predecessor,company,project,lock=True)
                if (previous['parent_id']!=header['id'] or previous['source_revision']!=predecessor or previous['id'] not in oldrevision['quantity_ids']
                    or previous['original_event_id']!=quantity['original_event_id']):raise DomainError('field_quantity_lineage','Correct the exact quantity from this record\'s immediate predecessor.',409)
                if {r.name for r in existing}!={r.name for r in existing if _raw('quantity',r.name,company,project,lock=True)['parent_id']==header['id']}:
                    raise DomainError('field_quantity_duplicate','This original capture belongs to another field record.',409)
            elif existing:raise DomainError('field_quantity_duplicate','An existing capture requires an explicit quantity correction.',409)
            qdefinition={**deepcopy(quantity),'sources':[sources.mapped(s,resolved) for s in quantity['sources']]}
            event=_base(company,project,actor,parent_id=header['id'],source_revision=value['id'],revision_number=value['revision_number'],
                original_event_id=quantity['original_event_id'],supersedes_event_id=quantity['supersedes_event_id'],definition=qdefinition,no_effects=dict(rules.NO_EFFECTS))
            value['quantity_ids'].append(event['id']);events.append(event)
    rules.record(revision_kind,value);sources.verify([(revision_kind,value),*[('quantity',q) for q in events]],company,project,actor,lock=True,new_use=True)
    # The controller allows mutually linked new immutable facts only inside the
    # exact capture context; neither can be inserted through generic native APIs.
    token=repo._capture.set({'revision_kind':revision_kind,'revision':value,'quantities':events})
    try:
        repo.write(revision_kind,value)
        for event in events:repo.write('quantity',event)
    finally:repo._capture.reset(token)
    return value,events

def _validate_capture(family,definition,photos,quantities):
    _revision_kind(family);(rules.daily_definition if family=='daily' else rules.ticket_definition)(definition);rules.photos(photos)
    rules.sequence(quantities,'quantities',40)
    if family=='ticket' and quantities:rules.fail('T&M quantities belong to its documentary lines.','quantities')
    for quantity in quantities:rules.quantity_definition(quantity)
    if len({q['original_event_id'] for q in quantities})!=len(quantities):rules.fail('Choose each original quantity capture once.','quantities')

def create_record(company,project,operation_id,family,definition,photos,quantities):
    _validate_capture(family,definition,photos,quantities)
    def effect(actor,_):
        header=_base(company,project,actor,status='draft',number=repo.number(family,company,project),revision_number=0,current_revision=None,last_decision=None,accepted_revision=None)
        repo.write(family,header);revision,events=_capture(company,project,actor,family,header,definition,photos,quantities)
        final={**header,'revision_number':1,'current_revision':revision['id']};repo.write(family,final,old=header)
        return {'family':family,'header':final,'revision':revision,'quantities':events,'history_id':_event(actor,revision,operation_id,family+'.created',_revision_kind(family))}
    return _command(company,project,operation_id,family+'.create',{'family':family,'definition':definition,'photos':photos,'quantities':quantities},effect,
        participants=[definition['superintendent_user']] if family=='daily' else [])

def revise_record(company,project,operation_id,family,record_id,expected_version,definition,photos,quantities,amendment_reason=''):
    _validate_capture(family,definition,photos,quantities);rules.text(amendment_reason,'amendment_reason',2000,blank=True)
    def effect(actor,_):
        header=read(family,record_id,company,project,actor,lock=True);_version(header,expected_version)
        if header['status'] not in ('draft','returned','accepted','acknowledged'):raise DomainError('field_revision_state','Return a submitted/reviewed field record before authoring a successor.',409)
        if bool(header['accepted_revision'])!=bool(amendment_reason.strip()):rules.fail('Every successor to an accepted original needs its explicit amendment reason.','amendment_reason')
        revision,events=_capture(company,project,actor,family,header,definition,photos,quantities,predecessor=header['current_revision'],reason=amendment_reason)
        final={**header,'revision_number':revision['revision_number'],'current_revision':revision['id'],'last_decision':None,'status':'draft'};repo.write(family,final,old=header)
        return {'family':family,'header':final,'revision':revision,'quantities':events,'history_id':_event(actor,revision,operation_id,family+'.amended' if revision['amendment_of'] else family+'.revised',_revision_kind(family))}
    return _command(company,project,operation_id,family+'.revise',{'family':family,'record_id':record_id,'expected_version':expected_version,'definition':definition,'photos':photos,'quantities':quantities,'amendment_reason':amendment_reason},effect,
        participants=[definition['superintendent_user']] if family=='daily' else [])

def transition(company,project,operation_id,family,record_id,expected_version,action,comment,evidence,acknowledged_by=''):
    _revision_kind(family)
    if action not in rules.TRANSITIONS:rules.fail('Choose a registered documentary transition.','action')
    rules.text(comment,'comment',2000);rules.source_list(evidence,'evidence',minimum=1 if action=='acknowledge' else 0)
    rules.text(acknowledged_by,'acknowledged_by',240,blank=action!='acknowledge')
    if action=='acknowledge' and family!='ticket':rules.fail('Only a T&M ticket can be acknowledged.','action')
    if action!='acknowledge' and acknowledged_by:rules.fail('Only acknowledgment records an acknowledgment name.','acknowledged_by')
    origin,target,ability=rules.TRANSITIONS[action]
    def effect(actor,_):
        header=read(family,record_id,company,project,actor,lock=True);_version(header,expected_version)
        if header['status'] not in ((origin,) if isinstance(origin,str) else origin):raise DomainError('field_transition_state','This field standing does not permit the requested transition.',409)
        # Returning historical observations enables their explicit correction;
        # it does not adopt superseded bytes as a new accepted observation.
        revision=read(_revision_kind(family),header['current_revision'],company,project,actor,lock=True,new_use=action!='return')
        if action!='submit' and actor.person_id in _authors(revision):raise DomainError('independent_field_review_required','A canonical author or superintendent cannot review, accept or acknowledge their own record.',403)
        _,closure=_collect(_revision_kind(family),revision['id'],company,project,lock=True)
        captured=sources.resolve(company,project,[*[s for k,v in closure for s in sources.references(v,k)],*evidence],actor,lock=True,new_use=action!='return')
        if action=='return' and evidence:
            # Newly supplied return evidence remains subject to current ingest
            # rights even though the original observation can be historical.
            captured.update(sources.resolve(company,project,evidence,actor,lock=True,new_use=True))
        decision=_base(company,project,actor,parent_id=header['id'],source_revision=revision['id'],source_digest=digest(revision),predecessor=header['last_decision'],action=action,
            from_status=header['status'],to_status=target,comment=comment,acknowledged_by=acknowledged_by,evidence=[sources.mapped(s,captured) for s in evidence],no_effects=dict(rules.NO_EFFECTS))
        repo.write('decision',decision)
        final={**header,'status':target,'last_decision':decision['id'],'accepted_revision':revision['id'] if action=='accept' else header['accepted_revision']};repo.write(family,final,old=header)
        return {'family':family,'header':final,'revision':revision,'decision':decision,'history_id':_event(actor,decision,operation_id,family+'.'+action,'decision')}
    return _command(company,project,operation_id,family+'.'+action,{'family':family,'record_id':record_id,'expected_version':expected_version,'action':action,'comment':comment,'evidence':evidence,'acknowledged_by':acknowledged_by},effect,ability=ability)

def authorize_receipt(actor,company,project,result,*,lock=False):
    require_project(company,project,ability='field.read',actor=actor,lock=lock)
    family=result.get('family');_revision_kind(family)
    header=result.get('header')
    if type(header) is not dict:raise DomainError('field_receipt_integrity','The exact field command result is unavailable.',409)
    rules.record(family,header);current=_raw(family,header['id'],company,project,lock=lock);_scope(header,company,project)
    if any(current[k]!=header[k] for k in rules.IMMUTABLE_FIELDS|{'number'}):raise DomainError('field_receipt_integrity','The original field header identity differs.',409)
    revision=result.get('revision');kind=_revision_kind(family)
    if type(revision) is not dict or revision.get('id')!=header['current_revision'] or read(kind,revision['id'],company,project,actor,lock=lock)!=revision:
        raise DomainError('field_receipt_integrity','The exact original field revision differs.',409)
    if revision['parent_id']!=header['id']:raise DomainError('field_receipt_integrity','The original field revision belongs to another record.',409)
    if header['accepted_revision'] and header['accepted_revision']!=revision['id']:read(kind,header['accepted_revision'],company,project,actor,lock=lock)
    for q in result.get('quantities',[]):
        # Reading this exact revision already authorized and locked its complete
        # quantity/source union. Compare receipt facts without reopening bytes.
        if q['source_revision']!=revision['id'] or q['id'] not in revision.get('quantity_ids',[]) or _raw('quantity',q['id'],company,project,lock=lock)!=q:raise DomainError('field_receipt_integrity','An original quantity result differs.',409)
    if header['last_decision']:
        decision=read('decision',header['last_decision'],company,project,actor,lock=lock)
        if decision['source_revision']!=revision['id'] or decision['to_status']!=header['status'] or result.get('decision')!=decision:raise DomainError('field_receipt_integrity','The original documentary decision differs.',409)
    elif result.get('decision') is not None or header['status']!='draft':raise DomainError('field_receipt_integrity','Unexpected documentary result standing.',409)

def get_record(company,project,kind,record_id):
    value=read(kind,record_id,company,project,current_actor());return {'record':value,'record_digest':digest(value)}

def list_records(company,project,kind,parent_id=None,limit=25,cursor=None,count_mode='none'):
    if kind not in rules.KINDS:rules.fail('Choose a registered field kind.','kind')
    limit,cursor,count_mode=page_options(limit,cursor,count_mode)
    if limit>100 or count_mode!='none':rules.fail('Use a bounded field page with no total.','paging')
    if parent_id is not None:rules.identifier(parent_id,'parent_id')
    if parent_id is not None and kind in rules.HEADERS:rules.fail('Header lists cannot use a child-record parent filter.','parent_id')
    actor=current_actor();require_project(company,project,ability='field.read',actor=actor)
    scope={'route':'field.records.v1','company':company,'project':project,'kind':kind,'parent_id':parent_id,'limit':limit,'actor':actor.person_id,'user':actor.user,'authority':authority_fingerprint(actor,company,project)}
    last=decode_cursor(cursor,secret=signing_secret(),scope=scope) if cursor else None;items=[];last_visible=None;scanned=0
    while len(items)<=limit:
        rows=repo.candidate_rows(kind,company,project,parent_id=parent_id,last=last,limit=25)
        if not rows:break
        for row in rows:
            scanned+=1
            if scanned>500:raise DomainError('field_list_limit','Narrow this bounded field authorization scan with a parent filter.',422)
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

def authorize_history(kind,record_id,company,project,actor,details):
    if kind in rules.HEADERS:raise DomainError('field_integrity','Field history records exact immutable facts, not mutable headers.',409)
    value=read(kind,record_id,company,project,actor)
    if digest(value)!=details.get('record_digest'):raise DomainError('field_integrity','The exact field history source differs.',409)
    return value

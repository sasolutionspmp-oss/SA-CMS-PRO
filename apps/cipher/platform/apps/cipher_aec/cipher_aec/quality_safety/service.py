"""FLD-03 online documentary commands; no operating permit or financial effect."""
from contextvars import ContextVar
from copy import deepcopy
from uuid import uuid4
from cipher_aec.api.contracts import digest,utc_timestamp
from cipher_aec.api.errors import DomainError
from cipher_aec.api.paging import page_options,decode_cursor,page_result,signing_secret
from cipher_aec.governance.context import current_actor,require_project,authority_fingerprint
from cipher_aec.governance.commands import run_command
from cipher_aec.governance.history import append_event
from . import contracts as rules,repository as repo,sources

_effect=ContextVar('cipher_quality_safety_effect',default=None)

def _base(company,project,actor,**fields):
    return {'id':str(uuid4()),'company':company,'project':project,'scope_type':'Project',
        'author_person':actor.person_id,'author_user':actor.user,'created_at':utc_timestamp(),'status':'recorded',**fields}

def _raw(kind,record_id,company,project,*,lock=False):
    value=repo.raw(kind,record_id,lock=lock)
    if (value['company'],value['project'],value['scope_type'])!=(company,project,'Project'):
        raise DomainError('not_found','This record is not available.',404)
    return value

def _collect(kind,record_id,company,project,*,lock=False):
    collected={}
    def add(kind,record_id):
        if (kind,record_id) in collected:return collected[kind,record_id]
        if len(collected)>=100:raise DomainError('quality_safety_lineage_limit','The evidence closure exceeds its bound.',409)
        family=rules.family_for(kind);value=_raw(kind,record_id,company,project,lock=lock);collected[kind,record_id]=value
        if kind in rules.HEADERS:
            rev=add(rules.child_kind(family,'revision'),value['current_revision']) if value['current_revision'] else None
            if rev and (rev['parent_id']!=value['id'] or rev['revision_number']!=value['revision_number'] or rev['category']!=value['category']):
                raise DomainError('quality_safety_integrity','The current revision belongs to a different record.',409)
            if value['closed_revision']:
                original=_raw(rules.child_kind(family,'revision'),value['closed_revision'],company,project,lock=lock)
                if original['parent_id']!=value['id'] or original['revision_number']>value['revision_number']:raise DomainError('quality_safety_integrity','The closed original differs.',409)
            if value['last_decision']:
                decision=add(rules.child_kind(family,'decision'),value['last_decision'])
                if decision['source_revision']!=value['current_revision'] or decision['parent_id']!=value['id'] or decision['to_status']!=value['status']:
                    raise DomainError('quality_safety_integrity','The current standing differs from its exact decision.',409)
                if value['status']=='closed' and value['closed_revision']!=value['current_revision']:raise DomainError('quality_safety_integrity','Closure differs from its current revision.',409)
            elif value['status']!='draft':raise DomainError('quality_safety_integrity','This standing requires its exact decision.',409)
        elif kind.endswith('revision'):
            parent=_raw(family,value['parent_id'],company,project,lock=lock)
            if parent['category']!=value['category']:raise DomainError('quality_safety_integrity','The documentary category differs from its original.',409)
            if value['predecessor']:
                old=_raw(kind,value['predecessor'],company,project,lock=lock)
                if old['parent_id']!=parent['id'] or old['revision_number']+1!=value['revision_number']:raise DomainError('quality_safety_integrity','The immediate revision predecessor differs.',409)
            elif value['revision_number']!=1:raise DomainError('quality_safety_integrity','A successor needs its immediate predecessor.',409)
            if value['prior_decision']:
                previous=_raw(rules.child_kind(family,'decision'),value['prior_decision'],company,project,lock=lock)
                if previous['parent_id']!=parent['id'] or previous['source_revision']!=value['predecessor'] or previous['to_status'] not in ('returned','closed'):
                    raise DomainError('quality_safety_integrity','The prior documentary decision differs.',409)
            if value['amendment_of']:
                amended=_raw(kind,value['amendment_of'],company,project,lock=lock)
                if amended['parent_id']!=parent['id'] or amended['revision_number']>=value['revision_number']:raise DomainError('quality_safety_integrity','The amendment identifies a different original.',409)
        else:
            revision=add(rules.child_kind(family,'revision'),value['source_revision'])
            if revision['parent_id']!=value['parent_id'] or revision['category']!=value['category'] or digest(revision)!=value['source_digest']:
                raise DomainError('quality_safety_integrity','The decision differs from its exact immutable revision.',409)
            if value['action']!='submit' and value['author_person']==revision['author_person']:
                raise DomainError('independent_quality_safety_required','Another canonical person must check or close this record.',403)
            previous=add(kind,value['predecessor']) if value['predecessor'] else None
            if previous:
                if previous['parent_id']!=value['parent_id'] or previous['source_revision']!=value['source_revision'] or previous['to_status']!=value['from_status']:
                    raise DomainError('quality_safety_integrity','The documentary decision predecessor differs.',409)
            elif value['from_status']!='draft':raise DomainError('quality_safety_integrity','The documentary decision predecessor is missing.',409)
            if value['action']=='close':_closure_check(value,revision,previous)
        return value
    value=add(kind,record_id)
    return value,list(collected.values())

def _closure_check(value,revision,previous):
    required={row['item_id'] for row in revision['definition']['required_closure_items']}
    if {row['item_id'] for row in value['closure']}!=required:
        raise DomainError('closure_evidence_required','Supply current exact evidence for every specified closure item.',422)
    if not previous or previous['action']!='check' or value['checked_by_person']!=previous['author_person']:
        raise DomainError('quality_safety_integrity','Closure requires the exact independent checking decision.',409)
    if value['author_person'] in {revision['author_person'],previous['author_person']}:
        raise DomainError('independent_quality_safety_required','A third canonical person must record closure after the author and checker.',403)

def read(kind,record_id,company,project,actor,*,lock=False,new_use=False):
    family=rules.family_for(kind)
    # Duty admission precedes storage, so unauthorized existence probes cannot
    # distinguish an incident ID, private source, category, or missing record.
    require_project(company,project,ability=rules.ability(family),actor=actor,lock=lock)
    value,closure=_collect(kind,record_id,company,project,lock=lock)
    if family=='incident':
        from .privacy import verify_incident_evidence
        for fact in closure:
            revision=fact if 'definition' in fact else _raw('incident_revision',fact['source_revision'],company,project,lock=lock) if 'source_revision' in fact else None
            if revision:verify_incident_evidence(sources.references(fact),revision['definition'],company,project,actor,lock=lock)
    sources.verify(closure,company,project,actor,lock=lock,new_use=new_use)
    return value

def _command(company,project,operation_id,family,action,payload,effect,*,duty='write'):
    actor=current_actor();require_project(company,project,ability=rules.ability(family),actor=actor)
    def guarded(actor,project_doc):
        require_project(company,project,ability=rules.ability(family),actor=actor,lock=True)
        if project_doc.status in ('Completed','Cancelled'):raise DomainError('project_closed','This Project is closed for new documentary work.',409)
    def admitted(actor,project_doc):
        token=_effect.set({'family':family,'action':action,'person':actor.person_id,'company':company,'project':project})
        try:return effect(actor,project_doc)
        finally:_effect.reset(token)
    result=run_command(company=company,project=project,operation_id=operation_id,
        command='quality_safety.'+family+'.'+action+'.v1',payload=payload,
        ability=rules.ability(family,duty),effect=admitted,guard=guarded)
    authorize_receipt(current_actor(),company,project,result,lock=True)
    return result

def _event(actor,value,operation_id,event,kind):
    # Incident revisions/decisions are their own restricted immutable history.
    # No event, subject ID, count, hash-chain position or private digest enters
    # the ordinary Project activity stream, even for authorized incident users.
    if rules.family_for(kind)=='incident':return None
    return append_event(actor=actor,company=value['company'],project=value['project'],operation_id=operation_id,
        event='quality_safety.'+event,subject_type=rules.KINDS[kind],subject_id=value['id'],
        details={'record_digest':digest(value),'documentary_only':True})

def _version(header,expected_version):
    rules.checksum(expected_version,'expected_version')
    if digest(header)!=expected_version:raise DomainError('stale_quality_safety','The current revision or standing changed. Review it before continuing.',412)

def _capture(company,project,actor,family,header,definition,evidence,reason=''):
    resolved=sources.resolve(company,project,evidence,actor,lock=True,new_use=True)
    if family=='incident':
        from .privacy import verify_incident_evidence
        verify_incident_evidence(list(resolved.values()),definition,company,project,actor,lock=True)
    value=_base(company,project,actor,parent_id=header['id'],category=header['category'],revision_number=header['revision_number']+1,
        predecessor=header['current_revision'],prior_decision=header['last_decision'],amendment_of=header['closed_revision'],
        amendment_reason=reason,definition=deepcopy(definition),evidence=[sources.mapped(s,resolved) for s in evidence],no_effects=dict(rules.NO_EFFECTS))
    repo.write(rules.child_kind(family,'revision'),value)
    return value

def create_record(company,project,operation_id,family,category,definition,evidence):
    rules.definition(definition,family,category);rules.source_list(evidence,'evidence')
    def effect(actor,_):
        header=_base(company,project,actor,status='draft',category=category,number=repo.number(family,company,project),revision_number=0,current_revision=None,last_decision=None,closed_revision=None)
        repo.write(family,header);revision=_capture(company,project,actor,family,header,definition,evidence)
        final={**header,'revision_number':1,'current_revision':revision['id']};repo.write(family,final,old=header)
        return {'family':family,'header':final,'revision':revision,'history_id':_event(actor,revision,operation_id,'created',rules.child_kind(family,'revision'))}
    return _command(company,project,operation_id,family,'create',{'family':family,'category':category,'definition':definition,'evidence':evidence},effect)

def revise_record(company,project,operation_id,family,record_id,expected_version,definition,evidence,amendment_reason=''):
    rules.child_kind(family,'revision');rules.source_list(evidence,'evidence');rules.text(amendment_reason,'amendment_reason',2000,blank=True)
    def effect(actor,_):
        header=read(family,record_id,company,project,actor,lock=True);_version(header,expected_version)
        rules.definition(definition,family,header['category'])
        if header['status'] not in ('draft','returned','closed'):raise DomainError('quality_safety_state','Return this submission before authoring a successor.',409)
        if bool(header['closed_revision'])!=bool(amendment_reason.strip()):rules.fail('A successor to a closed original requires its explicit amendment reason.','amendment_reason')
        revision=_capture(company,project,actor,family,header,definition,evidence,amendment_reason)
        final={**header,'revision_number':revision['revision_number'],'current_revision':revision['id'],'last_decision':None,'status':'draft'};repo.write(family,final,old=header)
        return {'family':family,'header':final,'revision':revision,'history_id':_event(actor,revision,operation_id,'amended' if header['closed_revision'] else 'revised',rules.child_kind(family,'revision'))}
    return _command(company,project,operation_id,family,'revise',{'family':family,'record_id':record_id,'expected_version':expected_version,'definition':definition,'evidence':evidence,'amendment_reason':amendment_reason},effect)

def transition(company,project,operation_id,family,record_id,expected_version,action,comment,evidence,closure):
    rules.child_kind(family,'decision')
    if type(action) is not str or action not in rules.TRANSITIONS:rules.fail('Choose a registered documentary transition.','action')
    rules.text(comment,'comment',2000);rules.source_list(evidence,'evidence',minimum=1 if action=='check' else 0);rules.closure(closure)
    if (action=='close')!=bool(closure):rules.fail('Closure requires item evidence; other decisions do not supply closure items.','closure')
    origins,target,duty=rules.TRANSITIONS[action]
    def effect(actor,_):
        header=read(family,record_id,company,project,actor,lock=True);_version(header,expected_version)
        if header['status'] not in origins:raise DomainError('quality_safety_state','The current standing does not permit this documentary decision.',409)
        revision,values=_collect(rules.child_kind(family,'revision'),header['current_revision'],company,project,lock=True)
        if action!='submit' and actor.person_id==revision['author_person']:raise DomainError('independent_quality_safety_required','Another canonical person must check or close this record.',403)
        previous=read(rules.child_kind(family,'decision'),header['last_decision'],company,project,actor,lock=True) if header['last_decision'] else None
        if previous:
            _,prior=_collect(rules.child_kind(family,'decision'),previous['id'],company,project,lock=True);values.extend(prior)
        own=[*evidence,*[s for row in closure for s in row['evidence']]]
        resolved=sources.resolve(company,project,[*[s for v in values for s in sources.references(v)],*own],actor,lock=True,new_use=action!='return')
        if action=='return' and own:resolved.update(sources.resolve(company,project,own,actor,lock=True,new_use=True))
        value=_base(company,project,actor,parent_id=header['id'],category=header['category'],source_revision=revision['id'],source_digest=digest(revision),predecessor=header['last_decision'],
            action=action,from_status=header['status'],to_status=target,comment=comment,evidence=[sources.mapped(s,resolved) for s in evidence],
            closure=[{**row,'evidence':[sources.mapped(s,resolved) for s in row['evidence']]} for row in closure],
            checked_by_person=previous['author_person'] if action=='close' and previous else None,no_effects=dict(rules.NO_EFFECTS))
        if action=='close':_closure_check(value,revision,previous)
        if family=='incident':
            from .privacy import verify_incident_evidence
            verify_incident_evidence(sources.references(value),revision['definition'],company,project,actor,lock=True)
        repo.write(rules.child_kind(family,'decision'),value)
        final={**header,'status':target,'last_decision':value['id'],'closed_revision':revision['id'] if action=='close' else header['closed_revision']};repo.write(family,final,old=header)
        return {'family':family,'header':final,'revision':revision,'decision':value,'history_id':_event(actor,value,operation_id,action,rules.child_kind(family,'decision'))}
    return _command(company,project,operation_id,family,action,{'family':family,'record_id':record_id,'expected_version':expected_version,'action':action,'comment':comment,'evidence':evidence,'closure':closure},effect,duty=duty)

def authorize_receipt(actor,company,project,result,*,lock=False):
    family=result.get('family');rules.child_kind(family,'revision')
    require_project(company,project,ability=rules.ability(family),actor=actor,lock=lock)
    if result.get('evidence_upload') is True:
        from .privacy import authorize_upload_result
        return authorize_upload_result(result,company,project,actor,lock=lock)
    header=result.get('header');revision=result.get('revision')
    if type(header) is not dict or type(revision) is not dict:raise DomainError('quality_safety_receipt_integrity','The exact result is unavailable.',409)
    rules.record(family,header);current=_raw(family,header['id'],company,project,lock=lock)
    if any(header[k]!=current[k] for k in (rules.BASE-{'status'})|{'number','category'}):raise DomainError('quality_safety_receipt_integrity','The original header identity differs.',409)
    actual=read(rules.child_kind(family,'revision'),revision['id'],company,project,actor,lock=lock)
    if revision!=actual or header['current_revision']!=revision['id'] or revision['parent_id']!=header['id'] or header['revision_number']!=revision['revision_number']:
        raise DomainError('quality_safety_receipt_integrity','The exact original revision differs.',409)
    if header['closed_revision']:read(rules.child_kind(family,'revision'),header['closed_revision'],company,project,actor,lock=lock)
    if header['last_decision']:
        decision=read(rules.child_kind(family,'decision'),header['last_decision'],company,project,actor,lock=lock)
        if result.get('decision')!=decision or decision['source_revision']!=revision['id'] or decision['to_status']!=header['status']:raise DomainError('quality_safety_receipt_integrity','The original decision differs.',409)
    elif result.get('decision') is not None or header['status']!='draft':raise DomainError('quality_safety_receipt_integrity','The original standing differs.',409)
    if family=='incident' and result.get('history_id') is not None:raise DomainError('quality_safety_receipt_integrity','Restricted incidents cannot enter ordinary activity.',409)

def authorize_command_receipt(actor,command,company,project,result,*,lock=False):
    parts=command.split('.') if type(command) is str else []
    if len(parts)!=4 or parts[0]!='quality_safety' or parts[3]!='v1' or parts[1] not in rules.HEADERS or parts[2] not in ('create','revise','submit','check','return','close','upload_evidence') or result.get('family')!=parts[1]:
        raise DomainError('quality_safety_receipt_integrity','The exact command and documentary result differ.',409)
    if (parts[2]=='upload_evidence')!=(result.get('evidence_upload') is True) or parts[2]=='upload_evidence' and parts[1]!='incident':
        raise DomainError('quality_safety_receipt_integrity','The private evidence command and result differ.',409)
    return authorize_receipt(actor,company,project,result,lock=lock)

def get_record(company,project,kind,record_id):
    value=read(kind,record_id,company,project,current_actor());return {'record':value,'record_digest':digest(value)}

def list_records(company,project,kind,parent_id=None,limit=25,cursor=None,count_mode='none'):
    family=rules.family_for(kind);actor=current_actor()
    require_project(company,project,ability=rules.ability(family),actor=actor)
    limit,cursor,count_mode=page_options(limit,cursor,count_mode)
    if limit>100 or count_mode!='none':rules.fail('Use a bounded page without a total.','paging')
    if parent_id is not None:
        rules.identifier(parent_id,'parent_id')
        if kind in rules.HEADERS:rules.fail('Header lists cannot use a parent filter.','parent_id')
        read(family,parent_id,company,project,actor)
    scope={'route':'quality_safety.records.v1','company':company,'project':project,'kind':kind,'parent_id':parent_id,'limit':limit,
        'actor':actor.person_id,'user':actor.user,'authority':authority_fingerprint(actor,company,project)}
    last=decode_cursor(cursor,secret=signing_secret(),scope=scope) if cursor else None;items=[];last_visible=None;scanned=0
    while len(items)<=limit:
        rows=repo.candidate_rows(kind,company,project,parent_id=parent_id,last=last,limit=25)
        if not rows:break
        for row in rows:
            scanned+=1
            if scanned>500:raise DomainError('quality_safety_list_limit','Narrow this bounded authorization scan with a parent filter.',422)
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
    if kind in rules.HEADERS or rules.family_for(kind)=='incident':raise DomainError('not_found','This activity is not available.',404)
    value=read(kind,record_id,company,project,actor)
    if digest(value)!=details.get('record_digest'):raise DomainError('quality_safety_integrity','The exact history source differs.',409)
    return value

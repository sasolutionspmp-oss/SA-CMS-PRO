"""Canonical Project work packages and manually authored engineering evidence."""
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
from cipher_aec.estimating import units
from cipher_aec.migrations.validation import parse_manifest,ManifestError
from . import contracts as rules,repository as repo
_people_plan=ContextVar('engineering_package_people_plan',default=None)


def base(company,project,actor,**fields):
    return {'id':str(uuid4()),'company':company,'project':project,'scope_type':'Project','author_person':actor.person_id,'author_user':actor.user,'created_at':utc_timestamp(),'status':'working','no_effects':dict(rules.NO_EFFECTS),**fields}

def raw(kind,identifier,company,project,*,lock=False):
    if kind not in rules.KINDS:rules.fail('Choose a registered package record kind.','kind')
    value=repo.raw(kind,identifier,lock=lock)
    if value['company']!=company or value['project']!=project or value['scope_type']!='Project':raise DomainError('not_found','This work package fact is not available.',404)
    return value

def _links(value,actor,*,lock=False):
    company,project=value['company'],value['project']
    for identifier in value['definition']['task_ids']:
        task=frappe.get_doc('Task',identifier,for_update=lock)
        if task.project!=project or not frappe.has_permission('Task','read',doc=task,user=actor.user):raise DomainError('not_found','This linked Project task is not available.',404)
    if value['definition']['wbs_ids']:
        from cipher_aec.project_controls.service import scoped
        for identifier in value['definition']['wbs_ids']:scoped('wbs',identifier,company,project,actor)

def verify_quantities(value):
    manifest=value['unit_manifest']
    if manifest.get('dataset_id')!=value['id'] or manifest.get('scope')!={'company':value['company'],'project':value['project']}:raise DomainError('package_integrity','The quantity manifest has a different exact dataset or Project.',409)
    try:parse_manifest(manifest)
    except ManifestError:raise DomainError('package_integrity','The canonical quantity/unit manifest cannot be verified.',409) from None
    for field in ('quantities','inputs','outputs'):
        if field not in value:continue
        rules.quantities(value[field],manifest,field)
        for row in value[field]:
            source=row['source'];matched=False
            for ref in [*value['source_citations'],*value['drawing_references'],*value['artifacts']]:
                if ref['revision_id']==source['revision_id'] and ref['source_sha256']==source['source_sha256'] and (ref.get('page')==source['page'] if 'page' in ref else 1<=source['page']<=ref['page_count']):matched=True
            if not matched:raise DomainError('package_quantity_source','Each authored quantity must identify a retained exact source page and locator.',422)

def _check_evidence(value,*,lock=False):
    packet=frappe.get_doc('Cipher Approval Packet',value['packet_id'],for_update=lock);decision=frappe.get_doc('Cipher Approval Decision',value['decision_id'],for_update=lock);manifest=json.loads(packet.manifest_json)
    consumed=frappe.db.sql('SELECT * FROM `tabCipher Approval Consumption` WHERE packet=%s'+(' FOR UPDATE' if lock else ''),(packet.name,),as_dict=True)
    if (packet.company!=value['company'] or packet.project!=value['project'] or (packet.scope_type or 'Project')!='Project' or packet.action!=rules.ACTIONS[value['subject_kind']]
        or packet.subject_id!=value['subject_id'] or packet.subject_type!=rules.KINDS[value['subject_kind']] or digest(manifest)!=packet.manifest_hash
        or manifest['domain']['effect']['subject_digest']!=value['subject_digest'] or decision.packet!=packet.name or decision.decision!='Grant' or decision.manifest_hash!=packet.manifest_hash
        or decision.actor_person!=value['checker']['person'] or (decision.reason or '')!=value['comments'] or len(consumed)!=1
        or consumed[0].decision!=decision.name or consumed[0].result_hash!=digest({'check':value}) or consumed[0].actor_person!=value['author_person']
        or consumed[0].actor_person!=packet.requester_person or consumed[0].company!=value['company'] or consumed[0].project!=value['project'] or (consumed[0].scope_type or 'Project')!='Project'
        or manifest['domain']['effect'].get('schema')!='cipher.engineering.package-check.v1' or manifest['domain']['effect'].get('action')!=packet.action
        or manifest['domain']['effect'].get('subject_kind')!=value['subject_kind'] or manifest['domain']['effect'].get('subject_id')!=value['subject_id']
        or manifest['domain']['effect'].get('package_revision')!=value['package_revision'] or manifest['domain']['effect'].get('package_digest')!=value['package_digest']):
        raise DomainError('package_check_integrity','The exact independent checking grant/fact cannot be verified.',409)

def read(kind,identifier,company,project,actor,*,lock=False):
    require_project(company,project,ability=rules.READ,actor=actor,lock=lock);value=raw(kind,identifier,company,project,lock=lock)
    if kind=='package':
        assignment=read('package_revision',value['current_revision'],company,project,actor,lock=lock)
        if assignment['parent_id']!=value['id'] or assignment['revision_number']!=value['revision_number']:raise DomainError('package_integrity','The exact package assignment head differs.',409)
    elif kind=='package_revision':
        raw('package',value['parent_id'],company,project,lock=lock);_links(value,actor,lock=lock)
        if value['responsible']['person']==value['checker']['person']:raise DomainError('independent_engineering_required','The engineer and required checker must be different canonical people.',403)
    elif kind in ('basis','calculation','deliverable'):
        assignment=read('package_revision',value['package_revision'],company,project,actor,lock=lock)
        if assignment['parent_id']!=value['parent_id'] or digest(assignment)!=value['package_digest'] or assignment['responsible']['person']!=value['author_person'] or assignment['checker']!=value['checker']:
            raise DomainError('package_integrity','The original package/preparer/checker lineage differs.',409)
        if kind in ('calculation','deliverable'):
            basis=read('basis',value['basis_revision'],company,project,actor,lock=lock)
            if digest(basis)!=value['basis_digest'] or basis['parent_id']!=value['parent_id'] or basis['package_revision']!=value['package_revision']:raise DomainError('package_integrity','The exact design basis lineage differs.',409)
            if kind=='calculation':
                if value['inputs']!=[next((r for r in basis['quantities'] if r['key']==key),None) for key in value['input_keys']]:raise DomainError('package_integrity','Calculation inputs differ from their immutable design basis quantities.',409)
                by_unit={r['id']:r for r in basis['unit_manifest']['records'] if r['kind']=='uom'}
                actual={r['id']:r for r in value['unit_manifest']['records'] if r['kind']=='uom'}
                if any(actual.get(row['quantity']['unit_id'])!=by_unit[row['quantity']['unit_id']] for row in value['inputs']):raise DomainError('package_integrity','The exact basis input unit revision changed.',409)
            else:
                for reference in value['calculations']:
                    calculated=read('calculation',reference['id'],company,project,actor,lock=lock)
                    if digest(calculated)!=reference['record_digest'] or calculated['basis_revision']!=basis['id'] or calculated['parent_id']!=value['parent_id']:raise DomainError('package_integrity','The deliverable has a different exact calculation/basis.',409)
        sources.verify(company,project,value,actor,lock=lock)
        if kind!='deliverable':verify_quantities(value);units.verify_manifest_access(value['unit_manifest'],None,actor)
    else:
        original=read(value['subject_kind'],value['subject_id'],company,project,actor,lock=lock)
        if digest(original)!=value['subject_digest'] or original['parent_id']!=value['parent_id'] or original['checker']!=value['checker'] or original['author_person']==value['checker']['person'] or value['package_revision']!=original['package_revision'] or value['package_digest']!=original['package_digest'] or value['preparer_person']!=original['author_person']:
            raise DomainError('package_check_integrity','The exact checked subject/preparer/checker differs.',409)
        _check_evidence(value,lock=lock)
    return value

def event(actor,value,operation_id,name,kind):
    return append_event(actor=actor,company=value['company'],project=value['project'],operation_id=operation_id,event='engineering.package.'+name,subject_type=rules.KINDS[kind],subject_id=value['id'],details={'record_digest':digest(value),'parent_id':value.get('parent_id'),'issued':False,'sealed':False})

def command(company,project,operation_id,name,payload,effect,*,users=()):
    plan={user:current_actor(user).person_id for user in users}
    def guard(actor,project_doc):
        require_project(company,project,ability=rules.READ,actor=actor,lock=True)
        if project_doc.status in ('Completed','Cancelled'):raise DomainError('project_closed','This Project is closed for new engineering work.',409)
        if any(current_actor(user).person_id!=person for user,person in plan.items()):raise DomainError('package_people_changed','The declared engineer/checker identities changed.',412)
    token=_people_plan.set(plan)
    try:return run_command(company=company,project=project,operation_id=operation_id,command='engineering.package.'+name+'.v1',payload=payload,ability=rules.WRITE,guard=guard,effect=effect,participant_people=tuple(sorted(set(plan.values()))))
    finally:_people_plan.reset(token)

def _people(company,project,definition):
    result=[];plan=_people_plan.get() or {}
    for key,ability in (('responsible_user',rules.WRITE),('checker_user',rules.CHECK)):
        user=definition[key];observed=current_actor(user)
        if plan.get(user)!=observed.person_id:raise DomainError('package_people_changed','The declared participant identity changed.',412)
        actor=current_actor(user,lock=True);require_project(company,project,ability=rules.READ,actor=actor,lock=True);require_project(company,project,ability=ability,actor=actor,lock=True)
        result.append({'user':actor.user,'person':actor.person_id})
    if result[0]['person']==result[1]['person']:raise DomainError('independent_engineering_required','Aliases of the same canonical person cannot prepare and check.',403)
    return result

def _expected(header,expected):
    rules.checksum(expected)
    if digest(header)!=expected:raise DomainError('stale_package','The package changed. Review the exact current work before authoring.',412)

def create_package(company,project,operation_id,definition):
    rules.package_definition(definition)
    def effect(actor,_):
        responsible,checker=_people(company,project,definition)
        from frappe.model.naming import make_autoname
        header=base(company,project,actor,number=make_autoname('ENG-WP-'+digest({'company':company,'project':project})[:8]+'-.#####'),revision_number=0,current_revision=None,basis_head=None,calculation_heads=[],deliverable_heads=[])
        repo.write('package',header)
        revision=base(company,project,actor,parent_id=header['id'],revision_number=1,predecessor=None,definition=deepcopy(definition),responsible=responsible,checker=checker);_links(revision,actor,lock=True);repo.write('package_revision',revision)
        final={**header,'revision_number':1,'current_revision':revision['id']};repo.write('package',final,old=header)
        return {'package':final,'revision':revision,'history_id':event(actor,revision,operation_id,'created','package_revision')}
    return command(company,project,operation_id,'create',{'definition':definition},effect,users=[definition['responsible_user'],definition['checker_user']])

def revise_package(company,project,operation_id,package_id,expected_version,definition):
    rules.package_definition(definition)
    def effect(actor,_):
        header=raw('package',package_id,company,project,lock=True);_expected(header,expected_version);responsible,checker=_people(company,project,definition)
        value=base(company,project,actor,parent_id=package_id,revision_number=header['revision_number']+1,predecessor=header['current_revision'],definition=deepcopy(definition),responsible=responsible,checker=checker);_links(value,actor,lock=True);repo.write('package_revision',value)
        final={**header,'current_revision':value['id'],'revision_number':value['revision_number']};repo.write('package',final,old=header)
        return {'package':final,'revision':value,'history_id':event(actor,value,operation_id,'revised','package_revision')}
    return command(company,project,operation_id,'revise',{'package_id':package_id,'expected_version':expected_version,'definition':definition},effect,users=[definition['responsible_user'],definition['checker_user']])

def _author(company,project,package_id,expected,actor):
    header=raw('package',package_id,company,project,lock=True);_expected(header,expected)
    assignment=read('package_revision',header['current_revision'],company,project,actor,lock=True)
    if actor.person_id!=assignment['responsible']['person']:raise DomainError('responsible_engineer_required','The designated canonical engineer must author this package work.',403)
    return header,assignment

def _sources(company,project,citations,drawings,artifacts,actor):
    rules.citations(citations,required=False);rules.drawings(drawings)
    if artifacts:rules.artifacts(artifacts)
    if not citations and not drawings and not artifacts:rules.fail('Retain at least one exact design source.','sources')
    return {'source_citations':sources.resolve_citations(company,project,citations,actor,lock=True,required=False),'drawing_references':sources.resolve_drawings(company,project,drawings,actor,lock=True),'artifacts':sources.resolve_artifacts(company,project,artifacts,actor,lock=True) if artifacts else []}

def _merge(*values):
    result={key:sources.merge(*(v[key] for v in values)) for key in ('source_citations','drawing_references','artifacts')}
    if any(len(result[key])>bound for key,bound in [('source_citations',64),('drawing_references',16),('artifacts',8)]):rules.fail('Use a bounded exact source/artifact closure.','sources')
    return result

def _revision(kind,header,assignment,actor,definition,source,*,previous=None,family_id=None):
    return base(header['company'],header['project'],actor,parent_id=header['id'],family_id=family_id or (previous['family_id'] if previous else str(uuid4())),revision_number=previous['revision_number']+1 if previous else 1,predecessor=previous['id'] if previous else None,package_revision=assignment['id'],package_digest=digest(assignment),checker=assignment['checker'],definition=deepcopy(definition),**source)

def create_basis(company,project,operation_id,package_id,expected_version,definition,quantities,source_citations,drawing_references,artifacts):
    rules.basis_definition(definition);ids=rules.quantity_refs(quantities)
    def effect(actor,_):
        header,assignment=_author(company,project,package_id,expected_version,actor)
        previous=read('basis',header['basis_head'],company,project,actor,lock=True) if header['basis_head'] else None
        source=_sources(company,project,source_citations,drawing_references,artifacts,actor);value=_revision('basis',header,assignment,actor,definition,source,previous=previous)
        value.update(quantities=deepcopy(quantities),unit_manifest=units.manifest(company,project,ids,[],lock=True,dataset_id=value['id']));verify_quantities(value);repo.write('basis',value)
        final={**header,'basis_head':value['id']};repo.write('package',final,old=header)
        return {'package':final,'basis':value,'history_id':event(actor,value,operation_id,'basis.authored','basis')}
    return command(company,project,operation_id,'basis.create',{'package_id':package_id,'expected_version':expected_version,'definition':definition,'quantities':quantities,'source_citations':source_citations,'drawing_references':drawing_references,'artifacts':artifacts},effect)

def _basis(header,identifier,expected,company,project,actor):
    value=read('basis',identifier,company,project,actor,lock=True)
    if digest(value)!=expected or value['id']!=header['basis_head'] or value['parent_id']!=header['id'] or value['package_revision']!=header['current_revision']:raise DomainError('stale_package_basis','Select the exact current package design basis.',412)
    return value

def _previous(kind,identifier,header,company,project,actor):
    if identifier is None:return None
    old=read(kind,identifier,company,project,actor,lock=True)
    if old['parent_id']!=header['id'] or old['id'] not in header[kind+'_heads']:raise DomainError('stale_package_family','Author a successor of the current exact family head.',412)
    return old

def _finish(kind,header,value,actor,operation_id):
    heads=[i for i in header[kind+'_heads'] if i!=value['predecessor']]+[value['id']]
    if len(heads)>20:rules.fail('Use at most twenty calculation/deliverable families per package.','families')
    repo.write(kind,value);final={**header,kind+'_heads':heads};repo.write('package',final,old=header)
    return {'package':final,kind:value,'history_id':event(actor,value,operation_id,kind+'.authored',kind)}

def create_calculation(company,project,operation_id,package_id,expected_version,basis_revision,basis_digest,definition,input_keys,outputs,artifacts,predecessor=None):
    rules.calculation_definition(definition);rules.sequence(input_keys,'input_keys',32,1);rules.artifacts(artifacts);ids=rules.quantity_refs(outputs)
    if len(set(input_keys))!=len(input_keys):rules.fail('Choose each basis input key once.','input_keys')
    def effect(actor,_):
        header,assignment=_author(company,project,package_id,expected_version,actor);basis=_basis(header,basis_revision,basis_digest,company,project,actor);previous=_previous('calculation',predecessor,header,company,project,actor)
        inputs=[next((r for r in basis['quantities'] if r['key']==key),None) for key in input_keys]
        if any(r is None for r in inputs):rules.fail('Select exact immutable design-basis quantity keys.','input_keys')
        source=_merge(basis,_sources(company,project,[],[],artifacts,actor));value=_revision('calculation',header,assignment,actor,definition,source,previous=previous)
        value.update(basis_revision=basis_revision,basis_digest=basis_digest,input_keys=list(input_keys),inputs=deepcopy(inputs),outputs=deepcopy(outputs),unit_manifest=units.manifest(company,project,ids|{r['quantity']['unit_id'] for r in inputs},[],lock=True,dataset_id=value['id']),execution={'kind':'manual-record','executed_by_cipher':False,'solver_qualified':False},issue_readiness='not_authorized_for_issue')
        oldunits={r['id']:r for r in basis['unit_manifest']['records'] if r['kind']=='uom'};newunits={r['id']:r for r in value['unit_manifest']['records'] if r['kind']=='uom'}
        if any(oldunits[r['quantity']['unit_id']]!=newunits[r['quantity']['unit_id']] for r in inputs):raise DomainError('stale_package_unit','A basis input unit revision changed. Author an explicit basis successor.',412)
        verify_quantities(value);return _finish('calculation',header,value,actor,operation_id)
    return command(company,project,operation_id,'calculation.create',{'package_id':package_id,'expected_version':expected_version,'basis_revision':basis_revision,'basis_digest':basis_digest,'definition':definition,'input_keys':input_keys,'outputs':outputs,'artifacts':artifacts,'predecessor':predecessor},effect)

def create_deliverable(company,project,operation_id,package_id,expected_version,basis_revision,basis_digest,definition,calculations,source_citations,drawing_references,artifacts,predecessor=None):
    rules.deliverable_definition(definition);rules.sequence(calculations,'calculations',8,1)
    for ref in calculations:rules.closed(ref,{'id','record_digest'});rules.identifier(ref['id']);rules.checksum(ref['record_digest'])
    if len({r['id'] for r in calculations})!=len(calculations):rules.fail('Choose each exact calculation once.','calculations')
    def effect(actor,_):
        header,assignment=_author(company,project,package_id,expected_version,actor);basis=_basis(header,basis_revision,basis_digest,company,project,actor);previous=_previous('deliverable',predecessor,header,company,project,actor);selected=[]
        for reference in calculations:
            value=read('calculation',reference['id'],company,project,actor,lock=True)
            if digest(value)!=reference['record_digest'] or value['parent_id']!=package_id or value['basis_revision']!=basis_revision or value['id'] not in header['calculation_heads']:raise DomainError('stale_package_calculation','Select an exact current calculation from this package and basis.',412)
            selected.append(value)
        source=_merge(basis,*selected,_sources(company,project,source_citations,drawing_references,artifacts,actor));value=_revision('deliverable',header,assignment,actor,definition,source,previous=previous)
        value.update(basis_revision=basis_revision,basis_digest=basis_digest,calculations=deepcopy(calculations),issue_readiness='not_authorized_for_issue')
        return _finish('deliverable',header,value,actor,operation_id)
    return command(company,project,operation_id,'deliverable.create',{'package_id':package_id,'expected_version':expected_version,'basis_revision':basis_revision,'basis_digest':basis_digest,'definition':definition,'calculations':calculations,'source_citations':source_citations,'drawing_references':drawing_references,'artifacts':artifacts,'predecessor':predecessor},effect)

def review_state(kind,value,actor):
    if kind not in rules.ACTIONS:return None
    checked=repo.checked(kind,value['id'])
    if checked:
        read('check',checked['id'],value['company'],value['project'],actor)
        return {'state':'checked','check_id':checked['id'],'packet_id':checked['packet_id'],'issue_authorized':False}
    rows=frappe.db.sql('SELECT name FROM `tabCipher Approval Packet` WHERE scope_type=\'Project\' AND company=%s AND project=%s AND action=%s AND subject_id=%s ORDER BY creation DESC,name DESC LIMIT 1',(value['company'],value['project'],rules.ACTIONS[kind],value['id']))
    if not rows:return {'state':'working','check_id':None,'packet_id':None,'issue_authorized':False}
    from cipher_aec.governance.approvals import read_packet
    packet=read_packet(value['company'],value['project'],rows[0][0]);state={'Pending':'in_check','Granted':'grant_awaiting_record','Rejected':'returned'}.get(packet['state'],'working')
    return {'state':state,'check_id':None,'packet_id':packet['id'],'issue_authorized':False}

def get_record(company,project,kind,record_id):
    actor=current_actor();value=read(kind,record_id,company,project,actor)
    return {'record':value,'record_digest':digest(value),'review':review_state(kind,value,actor)}

def list_records(company,project,kind,parent_id=None,limit=25,cursor=None,count_mode='none'):
    if kind not in rules.KINDS:rules.fail('Choose a registered package record kind.','kind')
    limit,cursor,count_mode=page_options(limit,cursor,count_mode)
    if limit>100 or count_mode!='none':rules.fail('Use a bounded package register with no total.','paging')
    actor=current_actor();require_project(company,project,ability=rules.READ,actor=actor)
    if parent_id:rules.identifier(parent_id)
    scope={'route':'engineering.packages.v1','company':company,'project':project,'kind':kind,'parent_id':parent_id,'limit':limit,'person':actor.person_id,'user':actor.user,'authority':authority_fingerprint(actor,company,project)}
    last=decode_cursor(cursor,secret=signing_secret(),scope=scope) if cursor else None;items=[];last_visible=None;scanned=0
    while len(items)<=limit:
        rows=repo.candidates(kind,company,project,parent_id=parent_id,last=last,limit=25)
        if not rows:break
        for row in rows:
            scanned+=1
            if scanned>500:raise DomainError('package_register_limit','The bounded authorization scan exceeded its scope. Filter one package.',422)
            last=[str(row.creation),row.name]
            try:value=read(kind,row.name,company,project,actor)
            except DomainError as error:
                if error.status in (401,403,404):continue
                raise
            items.append({'record':value,'record_digest':digest(value),'review':review_state(kind,value,actor)})
            if len(items)>limit:break
            last_visible=last
        if len(items)>limit or len(rows)<25:break
    return page_result(items[:limit],has_more=len(items)>limit,last=last_visible,scope=scope,limit=limit,count_mode='none',total=None)

def list_people(company,project,role,limit=25,cursor=None,count_mode='none'):
    if role not in ('engineer','checker'):rules.fail('Select engineer or checker choices.','role')
    ability=rules.WRITE if role=='engineer' else rules.CHECK
    return _choices(company,project,'people',role,ability,limit,cursor,count_mode)

def list_units(company,project,limit=25,cursor=None,count_mode='none'):
    return _choices(company,project,'units',None,None,limit,cursor,count_mode)

def _choices(company,project,kind,role,ability,limit,cursor,count_mode):
    limit,cursor,count_mode=page_options(limit,cursor,count_mode)
    if limit>100 or count_mode!='none':rules.fail('Use a bounded choice page with no total.','paging')
    actor=current_actor();require_project(company,project,ability=rules.READ,actor=actor)
    scope={'route':'engineering.packages.choices.v1','kind':kind,'company':company,'project':project,'role':role,'limit':limit,'person':actor.person_id,'user':actor.user,'authority':authority_fingerprint(actor,company,project)}
    last=decode_cursor(cursor,secret=signing_secret(),scope=scope) if cursor else None;items=[];last_visible=None;scanned=0
    while len(items)<=limit:
        if kind=='people':
            where="b.active=1 AND p.active=1 AND u.enabled=1 AND EXISTS (SELECT 1 FROM `tabCipher Project Duty` d WHERE d.scope_type='Project' AND d.company=%s AND d.project=%s AND d.person=b.person AND d.ability=%s AND d.active=1)";args=[company,project,ability]
            if last:where+=' AND (b.person>%s OR (b.person=%s AND b.user>%s))';args.extend([last[0],last[0],last[1]])
            rows=frappe.db.sql('SELECT b.person,b.user,p.display_name FROM `tabCipher Identity Binding` b JOIN `tabCipher Person` p ON p.name=b.person JOIN `tabUser` u ON u.name=b.user WHERE '+where+' ORDER BY b.person,b.user LIMIT 25',args,as_dict=True)
        else:
            where="enabled=1 AND cipher_unit_id IS NOT NULL AND cipher_unit_id<>''";args=[]
            if last:where+=' AND cipher_unit_id>%s';args.append(last[0])
            rows=frappe.db.sql('SELECT cipher_unit_id,name FROM `tabUOM` WHERE '+where+' ORDER BY cipher_unit_id LIMIT 25',args,as_dict=True)
        if not rows:break
        for row in rows:
            scanned+=1
            if scanned>500:raise DomainError('package_choices_limit','The bounded choice authorization scan exceeded its scope.',422)
            last=[row.person,row.user] if kind=='people' else [row.cipher_unit_id,row.name]
            try:
                if kind=='people':
                    person=current_actor(row.user)
                    if person.person_id!=row.person:continue
                    require_project(company,project,ability=rules.READ,actor=person);require_project(company,project,ability=ability,actor=person)
                    result={'user':row.user,'person':row.person,'display_name':row.display_name}
                else:result=units.qualified(row.cipher_unit_id,actor=actor)
            except DomainError as error:
                if error.status in (401,403,404) or kind=='units' and error.code=='unit_setup_required':continue
                raise
            items.append(result)
            if len(items)>limit:break
            last_visible=last
        if len(items)>limit or len(rows)<25:break
    return page_result(items[:limit],has_more=len(items)>limit,last=last_visible,scope=scope,limit=limit,count_mode='none',total=None)

def authorize_receipt(actor,company,project,result,*,lock=False):
    require_project(company,project,ability=rules.READ,actor=actor,lock=lock)
    for key,kind in [(k,k) for k in rules.KINDS]+[('revision','package_revision')]:
        if key not in result:continue
        value=result[key]
        if kind=='package':
            current=raw(kind,value['id'],company,project,lock=lock)
            if any(current[k]!=value[k] for k in ('id','company','project','scope_type','author_person','author_user','created_at','number')):raise DomainError('package_receipt_integrity','The original package receipt identity differs.',409)
            read('package_revision',value['current_revision'],company,project,actor,lock=lock)
            if value['basis_head']:read('basis',value['basis_head'],company,project,actor,lock=lock)
            for sourcekind in ('calculation','deliverable'):
                for identifier in value[sourcekind+'_heads']:read(sourcekind,identifier,company,project,actor,lock=lock)
        elif read(kind,value['id'],company,project,actor,lock=lock)!=value:raise DomainError('package_receipt_integrity','An original immutable package receipt differs.',409)

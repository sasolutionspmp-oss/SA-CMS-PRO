"""Closed documentary records. An incident never shares an ordinary field row."""
from cipher_aec.field.contracts import (closed, text, identifier, checksum, day,
    timestamp, sequence, source_list, captured_source, strip_source)
from cipher_aec.api.errors import DomainError

KINDS = {'record':'Cipher Quality Safety Record', 'revision':'Cipher Quality Safety Revision',
    'decision':'Cipher Quality Safety Decision', 'incident':'Cipher Safety Incident',
    'incident_revision':'Cipher Safety Incident Revision', 'incident_decision':'Cipher Safety Incident Decision'}
HEADERS = {'record','incident'}
CATEGORIES = ('inspection','deficiency','safety_observation','permit_record')
ABILITIES = frozenset(prefix+'.'+action for prefix in ('quality','safety.incident')
    for action in ('read','write','check','close')) | {'safety.incident.evidence.manage'}
NO_EFFECTS = {key:False for key in ('contract_change','budget_change','procurement_change',
    'invoice_change','financial_posting','payroll_release','award_execution',
    'engineering_approval','regulatory_approval','hazardous_work_authority','medical_advice',
    'compliance_certification','external_transmission')}
BASE = {'id','company','project','scope_type','author_person','author_user','created_at','status'}
HEADER_FIELDS = {'number','category','revision_number','current_revision','last_decision','closed_revision'}
REVISION_FIELDS = {'parent_id','category','revision_number','predecessor','prior_decision',
    'amendment_of','amendment_reason','definition','evidence','no_effects'}
DECISION_FIELDS = {'parent_id','category','source_revision','source_digest','predecessor',
    'action','from_status','to_status','comment','evidence','closure','checked_by_person','no_effects'}
TRANSITIONS = {'submit':(('draft',),'submitted','write'),
    'check':(('submitted',),'checked','check'),
    'return':(('submitted','checked'),'returned','check'),
    'close':(('checked',),'closed','close')}

def fail(message,field='record',code='invalid_quality_safety',status=422):
    raise DomainError(code,message,status,{'field':field})

def family_for(kind):
    if type(kind) is not str or kind not in KINDS:fail('Choose a declared quality or safety record kind.','kind')
    return 'incident' if kind.startswith('incident') else 'record'

def child_kind(family,child):
    if type(family) is not str or family not in HEADERS:fail('Choose record or incident.','family')
    return ('incident_' if family=='incident' else '')+child

def ability(family,action='read'):
    child_kind(family,'revision')
    return ('safety.incident' if family=='incident' else 'quality')+'.'+action

def definition(value,family,category):
    child_kind(family,'revision')
    if type(category) is not str or (family=='incident' and category!='incident') or (family=='record' and category not in CATEGORIES):
        fail('Choose the declared documentary category.','category')
    ordinary={'title','local_date','location','description','required_closure_items'}
    extra={'involved_people','restricted_account','immediate_response','shared_evidence_revisions','shared_evidence_statement'} if family=='incident' else set()
    if category=='permit_record':extra={'issuer_as_recorded','permit_identifier','valid_from','valid_until','conditions_as_recorded'}
    closed(value,ordinary|extra)
    for key in ('title','location'):text(value[key],key,240)
    text(value['description'],'description',10000);day(value['local_date'])
    sequence(value['required_closure_items'],'required_closure_items',12,1)
    for row in value['required_closure_items']:
        closed(row,{'item_id','description'});identifier(row['item_id'],'item_id');text(row['description'],'description',1000)
    if len({r['item_id'] for r in value['required_closure_items']})!=len(value['required_closure_items']):fail('Choose each required closure item once.')
    if family=='incident':
        sequence(value['involved_people'],'involved_people',20)
        for person in value['involved_people']:text(person,'involved_people',240)
        text(value['restricted_account'],'restricted_account',10000)
        text(value['immediate_response'],'immediate_response',4000)
        sequence(value['shared_evidence_revisions'],'shared_evidence_revisions',32)
        for revision in value['shared_evidence_revisions']:text(revision,'shared_evidence_revisions',140)
        if len(set(value['shared_evidence_revisions']))!=len(value['shared_evidence_revisions']):fail('Declare each shared revision once.')
        text(value['shared_evidence_statement'],'shared_evidence_statement',2000,blank=not value['shared_evidence_revisions'])
    if category=='permit_record':
        for key in ('issuer_as_recorded','permit_identifier'):text(value[key],key,240)
        text(value['conditions_as_recorded'],'conditions_as_recorded',10000)
        timestamp(value['valid_from'],'valid_from');timestamp(value['valid_until'],'valid_until')
        from datetime import datetime
        if datetime.fromisoformat(value['valid_until'])<=datetime.fromisoformat(value['valid_from']):fail('The recorded end must follow its start.','valid_until')
    return value

def closure(value,*,captured=False):
    sequence(value,'closure',12)
    for row in value:
        closed(row,{'item_id','evidence'});identifier(row['item_id'],'item_id')
        source_list([strip_source(s) for s in row['evidence']] if captured else row['evidence'],'evidence',minimum=1)
        if captured:
            for source in row['evidence']:captured_source(source)
    if len({r['item_id'] for r in value})!=len(value):fail('Choose each closure item once.','closure')
    return value

def record(kind,value,*,initial=False):
    family=family_for(kind)
    fields=HEADER_FIELDS if kind in HEADERS else REVISION_FIELDS if kind.endswith('revision') else DECISION_FIELDS
    closed(value,BASE|fields);identifier(value['id'])
    for key in ('company','project','author_person','author_user'):text(value[key],key,140)
    if value['scope_type']!='Project':fail('Choose an exact Project.','scope_type')
    timestamp(value['created_at'],'created_at')
    category=value['category']
    if (family=='incident' and category!='incident') or (family=='record' and category not in CATEGORIES):fail('The documentary category differs.','category')
    if kind in HEADERS:
        text(value['number'],'number',140)
        if value['status'] not in ('draft','submitted','checked','returned','closed'):fail('Unsupported documentary standing.','status')
        for key in ('current_revision','last_decision','closed_revision'):
            if value[key] is not None:identifier(value[key],key)
        if value['current_revision'] is None and not(initial and value['revision_number']==0):fail('The current immutable revision is required.')
    else:
        if value['status']!='recorded':fail('Original facts retain their recorded standing.','status')
        if value['no_effects']!=NO_EFFECTS or any(v is not False for v in value['no_effects'].values()):fail('Documentary records cannot authorize other effects.','no_effects')
        identifier(value['parent_id'],'parent_id')
        for source in value['evidence']:captured_source(source)
        source_list([strip_source(s) for s in value['evidence']],'evidence',minimum=1 if kind.endswith('revision') or value.get('action')=='check' else 0)
    if 'revision_number' in value and (type(value['revision_number']) is not int or value['revision_number']<(0 if initial and kind in HEADERS else 1)):fail('Use the exact revision number.')
    for key in ('predecessor','prior_decision','amendment_of'):
        if key in value and value[key] is not None:identifier(value[key],key)
    if kind.endswith('revision'):
        definition(value['definition'],family,category);text(value['amendment_reason'],'amendment_reason',2000,blank=True)
        if bool(value['amendment_of'])!=bool(value['amendment_reason'].strip()):fail('A closed original requires explicit amendment lineage and reason.')
    elif kind.endswith('decision'):
        identifier(value['source_revision'],'source_revision');checksum(value['source_digest'],'source_digest');text(value['comment'],'comment',2000)
        if type(value['action']) is not str or value['action'] not in TRANSITIONS:fail('Choose a registered documentary decision.','action')
        origins,target,_=TRANSITIONS[value['action']]
        if value['from_status'] not in origins or value['to_status']!=target:fail('The documentary transition differs.')
        closure(value['closure'],captured=True)
        if (value['action']=='close')!=bool(value['closure']):fail('Only closure records item evidence.','closure')
        if value['checked_by_person'] is not None:text(value['checked_by_person'],'checked_by_person',140)
        if (value['action']=='close')!=(value['checked_by_person'] is not None):fail('Closure retains the exact checking person.')
    return value

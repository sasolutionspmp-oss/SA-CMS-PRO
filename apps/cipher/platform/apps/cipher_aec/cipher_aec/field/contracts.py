"""Closed field capture contracts. Decimal strings are observations, never prices."""
from datetime import date, datetime
from decimal import Decimal
import re
from cipher_aec.api.errors import DomainError

KINDS = {'daily':'Cipher Field Daily Report', 'daily_revision':'Cipher Field Daily Revision',
         'quantity':'Cipher Field Quantity Event', 'ticket':'Cipher Field TM Ticket',
         'ticket_revision':'Cipher Field TM Revision', 'decision':'Cipher Field Decision'}
ABILITIES = frozenset({'field.read','field.write','field.review','field.accept','field.acknowledge'})
NO_EFFECTS = {key:False for key in ('contract_change','budget_change','procurement_change','invoice_change',
    'financial_posting','payroll_release','quality_certification','external_transmission')}
TRANSITIONS = {'submit':('draft','submitted','field.write'), 'review':('submitted','reviewed','field.review'),
    'return':(('submitted','reviewed'),'returned','field.review'), 'accept':('reviewed','accepted','field.accept'),
    'acknowledge':('accepted','acknowledged','field.acknowledge')}
BASE = {'id','company','project','scope_type','author_person','author_user','created_at','status'}
HEADERS = {'daily','ticket'}
IMMUTABLE_FIELDS = BASE - {'status'}

def fail(message,field='field',code='invalid_field_record',status=422):
    raise DomainError(code,message,status,{'field':field})

def closed(value,required,optional=(),field='field'):
    if type(value) is not dict or set(required)-set(value) or set(value)-set(required)-set(optional):
        fail('Supply the exact declared field record fields.',field)
    return value

def text(value,field,maximum=2000,*,blank=False):
    if type(value) is not str or len(value)>maximum or '\x00' in value or (not blank and not value.strip()):
        fail('Supply bounded authored text.',field)
    return value

def identifier(value,field='id'):
    if type(value) is not str or not re.fullmatch(r'[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}',value):
        fail('Use the immutable record UUID.',field)
    return value

def checksum(value,field='digest'):
    if type(value) is not str or not re.fullmatch('[a-f0-9]{64}',value):fail('Use the exact SHA-256 digest.',field)
    return value

def day(value,field='local_date'):
    try:
        if type(value) is not str or len(value)!=10 or date.fromisoformat(value).isoformat()!=value:raise ValueError
    except (TypeError,ValueError):fail('Use an exact ISO calendar date.',field)
    return value

def timestamp(value,field='captured_at'):
    try:
        if type(value) is not str or len(value)>40 or datetime.fromisoformat(value).tzinfo is None:raise ValueError
    except (ValueError,TypeError):fail('Use an ISO timestamp with an explicit UTC offset.',field)
    return value

def sequence(value,field,maximum=20,minimum=0):
    if type(value) is not list or not minimum<=len(value)<=maximum:fail('Use the bounded declared list.',field)
    return value

def quantity(value):
    if type(value) is not str or not re.fullmatch(r'(?:0|[1-9]\d{0,11})(?:\.\d{1,6})?',value) or Decimal(value)<=0:
        fail('Use a positive exact decimal string with at most six decimal places.','quantity')
    return value

def source(value):
    closed(value,{'revision_id','source_sha256','page','locator'},field='sources')
    text(value['revision_id'],'revision_id',140);checksum(value['source_sha256'],'source_sha256');text(value['locator'],'locator',1000)
    if type(value['page']) is not int or not 1<=value['page']<=200:fail('Use the exact source page.','page')
    return value

def source_list(value,field='sources',minimum=1):
    sequence(value,field,8,minimum)
    for row in value:source(row)
    if len({(r['revision_id'],r['page'],r['locator']) for r in value})!=len(value):fail('Choose each exact source locator once.',field)
    return value

def photos(value):
    sequence(value,'photos',12)
    for row in value:
        closed(row,{'source','caption','captured_at','representation'},field='photos');source(row['source']);text(row['caption'],'caption',1000);timestamp(row['captured_at'])
        if row['representation'] not in ('source_image','photo_on_pdf_page'):fail('Declare an image or an explicitly identified photo on a PDF page.','representation')
    return value

def quantity_definition(value):
    closed(value,{'original_event_id','supersedes_event_id','kind','description','wbs_code','cost_code','quantity','unit','location','sources'})
    identifier(value['original_event_id'],'original_event_id')
    if value['supersedes_event_id'] is not None:identifier(value['supersedes_event_id'],'supersedes_event_id')
    if value['kind'] not in ('installed','delivered'):fail('Declare installed or delivered.','kind')
    for key in ('description','location'):text(value[key],key,1000)
    for key in ('wbs_code','cost_code'):text(value[key],key,140,blank=True)
    quantity(value['quantity']);text(value['unit'],'unit',40);source_list(value['sources'])
    return value

def daily_definition(value):
    closed(value,{'local_date','superintendent_user','weather','weather_sources','crews','activities','delays','visitors'})
    day(value['local_date']);text(value['superintendent_user'],'superintendent_user',140)
    text(value['weather'],'weather',2000,blank=True);source_list(value['weather_sources'],'weather_sources',minimum=0)
    if value['weather'] and not value['weather_sources']:fail('Weather observations need their exact supporting source.','weather_sources')
    for key in ('crews','activities','delays','visitors'):
        sequence(value[key],key,20)
        for item in value[key]:text(item,key,2000)
    if not value['activities']:fail('Record at least one actual daily activity.','activities')
    return value

def ticket_definition(value):
    closed(value,{'local_date','title','customer_name','location','work_description','potential_change_reference','lines'})
    day(value['local_date'])
    for key in ('title','customer_name','location'):text(value[key],key,240)
    text(value['work_description'],'work_description',10000);text(value['potential_change_reference'],'potential_change_reference',240,blank=True)
    sequence(value['lines'],'lines',40,1)
    for line in value['lines']:
        closed(line,{'kind','description','quantity','unit','sources'},field='lines')
        if line['kind'] not in ('labor','equipment','material'):fail('Choose a documentary labor, equipment or material line.','kind')
        text(line['description'],'description',1000);quantity(line['quantity']);text(line['unit'],'unit',40);source_list(line['sources'])
    return value

def captured_source(value):
    closed(value,{'revision_id','source_sha256','page','locator','document_id','revision_number','byte_length','mime_type','page_count'})
    source({k:value[k] for k in ('revision_id','source_sha256','page','locator')})
    for key in ('document_id','mime_type'):text(value[key],key,140)
    for key in ('revision_number','byte_length','page_count'):
        if type(value[key]) is not int or value[key]<1:fail('Source metadata must be exact positive integers.',key)
    if value['page']>value['page_count']:fail('The source page exceeds the exact original.','page')

def strip_source(value):return {k:value[k] for k in ('revision_id','source_sha256','page','locator')}

def record(kind,value,*,initial=False):
    fields={
      'daily':{'number','revision_number','current_revision','last_decision','accepted_revision'},
      'ticket':{'number','revision_number','current_revision','last_decision','accepted_revision'},
      'daily_revision':{'parent_id','revision_number','predecessor','prior_decision','amendment_of','amendment_reason','definition','superintendent','photos','quantity_ids','no_effects'},
      'ticket_revision':{'parent_id','revision_number','predecessor','prior_decision','amendment_of','amendment_reason','definition','photos','no_effects'},
      'quantity':{'parent_id','source_revision','revision_number','original_event_id','supersedes_event_id','definition','no_effects'},
      'decision':{'parent_id','source_revision','source_digest','predecessor','action','from_status','to_status','comment','acknowledged_by','evidence','no_effects'}}
    if kind not in fields:fail('Choose a declared field record kind.','kind')
    closed(value,BASE|fields[kind]);identifier(value['id'])
    if value['scope_type']!='Project':fail('Field records require an exact Project.','scope_type')
    for key in ('company','project','author_person','author_user'):text(value[key],key,140)
    timestamp(value['created_at'],'created_at')
    if kind in HEADERS:
        if value['status'] not in ('draft','submitted','reviewed','returned','accepted','acknowledged'):fail('Unsupported field standing.','status')
        if kind=='daily' and value['status']=='acknowledged':fail('Only a T&M ticket has documentary acknowledgment.','status')
        text(value['number'],'number',140)
        for key in ('current_revision','last_decision','accepted_revision'):
            if value[key] is not None:identifier(value[key],key)
        if value['current_revision'] is None and not(initial and value['revision_number']==0):fail('A field header requires its exact current revision.')
    elif value['status']!='recorded':fail('Immutable field facts retain their original standing.','status')
    for key in ('parent_id','source_revision','predecessor','prior_decision','amendment_of','supersedes_event_id','original_event_id'):
        if key in value and value[key] is not None:identifier(value[key],key)
    if 'revision_number' in value and (type(value['revision_number']) is not int or value['revision_number']<(0 if initial and kind in HEADERS else 1)):fail('Use the exact positive revision number.','revision_number')
    if kind not in HEADERS:
        if value['no_effects']!=NO_EFFECTS or any(v is not False for v in value['no_effects'].values()):fail('Field records cannot authorize commercial or financial effects.','no_effects')
    if kind in ('daily_revision','ticket_revision'):
        definition={**value['definition']}
        if kind=='daily_revision':definition['weather_sources']=[strip_source(s) for s in definition['weather_sources']];daily_definition(definition)
        else:
            definition['lines']=[{**line,'sources':[strip_source(s) for s in line['sources']]} for line in definition['lines']];ticket_definition(definition)
        for row in sources_in_definition(value['definition'],kind):captured_source(row)
        text(value['amendment_reason'],'amendment_reason',2000,blank=True)
        if bool(value['amendment_of'])!=bool(value['amendment_reason'].strip()):fail('An accepted correction requires a reason and explicit amendment lineage.')
        photos([{**p,'source':strip_source(p['source'])} for p in value['photos']])
        for photo in value['photos']:captured_source(photo['source'])
        if kind=='daily_revision':
            closed(value['superintendent'],{'user','person'});text(value['superintendent']['user'],'user',140);text(value['superintendent']['person'],'person',140)
            sequence(value['quantity_ids'],'quantity_ids',40)
            for q in value['quantity_ids']:identifier(q,'quantity_ids')
            if len(set(value['quantity_ids']))!=len(value['quantity_ids']):fail('Choose each quantity fact once.')
    if kind=='quantity':
        quantity_definition({**value['definition'],'sources':[strip_source(s) for s in value['definition']['sources']]})
        for row in value['definition']['sources']:captured_source(row)
        if any(value[key]!=value['definition'][key] for key in ('original_event_id','supersedes_event_id')):fail('Quantity lineage indexes differ from their exact original.')
    if kind=='decision':
        checksum(value['source_digest'],'source_digest');text(value['comment'],'comment',2000)
        if value['action'] not in TRANSITIONS:fail('Choose a registered documentary transition.','action')
        origin,target,_=TRANSITIONS[value['action']]
        if value['from_status'] not in ((origin,) if isinstance(origin,str) else origin) or value['to_status']!=target:fail('The documentary transition is inconsistent.')
        text(value['acknowledged_by'],'acknowledged_by',240,blank=value['action']!='acknowledge')
        if value['action']!='acknowledge' and value['acknowledged_by']:fail('Only acknowledgment records a customer acknowledgment name.')
        sequence(value['evidence'],'evidence',8,1 if value['action']=='acknowledge' else 0)
        for row in value['evidence']:captured_source(row)
    return value

def sources_in_definition(definition,kind):
    if kind=='daily_revision':return definition['weather_sources']
    if kind=='ticket_revision':return [s for line in definition['lines'] for s in line['sources']]
    return definition['sources']

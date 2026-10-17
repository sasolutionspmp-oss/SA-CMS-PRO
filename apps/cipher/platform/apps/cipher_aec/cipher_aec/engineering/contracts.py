"""Closed ENG-01 authoring contracts; no pricing, acceptance or transport effects."""
from datetime import date
import re
from cipher_aec.api.contracts import digest
from cipher_aec.api.errors import DomainError

DISPOSITIONS = ('approved', 'approved_as_noted', 'revise_resubmit', 'rejected')
KINDS = {'rfi':'Cipher RFI', 'rfi_revision':'Cipher RFI Revision', 'response':'Cipher RFI Response Revision',
    'official_response':'Cipher Official RFI Response', 'submittal':'Cipher Submittal',
    'submission':'Cipher Submittal Submission Revision', 'disposition':'Cipher Submittal Disposition Revision',
    'official_disposition':'Cipher Official Submittal Disposition', 'transmittal':'Cipher Engineering Transmittal',
    'distribution':'Cipher Engineering Distribution Receipt'}
ACTIONS = {'response':'engineering.rfi.authorize.v1', 'disposition':'engineering.submittal.authorize.v1', 'transmittal':'engineering.distribute.v1'}
NO_EFFECTS = {'commercial_change':False, 'contract_change':False, 'budget_change':False, 'schedule_change':False,
              'quality_acceptance':False, 'professional_certification':False, 'external_transmission':False}

def fail(message, field='engineering', code='invalid_engineering', status=422):
    raise DomainError(code, message, status, {'field':field})

def closed(value, required, optional=(), field='engineering'):
    if type(value) is not dict or set(value)-set(required)-set(optional) or set(required)-set(value):
        fail('Supply the exact declared engineering fields.', field)
    return value

def text(value, field, maximum=2000, *, blank=False):
    if type(value) is not str or len(value)>maximum or '\x00' in value or (not blank and not value.strip()):
        fail('Supply bounded authored text.',field)
    # Empty disposition comments are a real authored fact, not a placeholder.
    return value

def identifier(value, field='id'):
    if type(value) is not str or not re.fullmatch(r'[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}',value):
        fail('Use the immutable record UUID.',field)
    return value

def checksum(value,field='digest'):
    if type(value) is not str or not re.fullmatch('[a-f0-9]{64}',value):fail('Use the exact SHA-256 digest.',field)
    return value

def day(value,field):
    if value is None:return None
    try:
        if type(value) is not str or len(value)!=10 or date.fromisoformat(value).isoformat()!=value:raise ValueError
    except ValueError:fail('Use an exact ISO calendar date or null.',field)
    return value

def sequence(value,field,maximum=8,minimum=0):
    if type(value) is not list or not minimum<=len(value)<=maximum:fail('Use the bounded declared list.',field)
    return value

def users(value,field='responsible_users',minimum=0):
    sequence(value,field,30 if field=='recipients' else 8,minimum)
    for user in value:text(user,field,140)
    if len(set(value))!=len(value):fail('Choose each exact user once.',field)
    return list(value)

def citations(value,*,required=True):
    sequence(value,'source_citations',8,1 if required else 0)
    for row in value:
        closed(row,{'revision_id','page','excerpt_sha256','source_sha256'},field='source_citations')
        text(row['revision_id'],'revision_id',140);checksum(row['source_sha256']);checksum(row['excerpt_sha256'])
        if type(row['page']) is not int or not 1<=row['page']<=200:fail('Use the exact source page.','source_citations')
    if len({(v['revision_id'],v['page'],v['excerpt_sha256']) for v in value})!=len(value):fail('Do not duplicate source citations.','source_citations')
    return value

def drawings(value):
    sequence(value,'drawing_references',8)
    for row in value:
        closed(row,{'revision_id','source_sha256','page','locator'},field='drawing_references')
        text(row['revision_id'],'revision_id',140);checksum(row['source_sha256']);text(row['locator'],'locator',1000)
        if type(row['page']) is not int or not 1<=row['page']<=200:fail('Use an exact raw drawing page.','page')
    if len({(r['revision_id'],r['page'],r['locator']) for r in value})!=len(value):fail('Do not duplicate drawing references.','drawing_references')
    return value

def question_sources(cited,raw):
    citations(cited,required=False);drawings(raw)
    if not cited and not raw:fail('Reference at least one exact source citation or original drawing page.','source_citations')

def artifacts(value):
    sequence(value,'artifacts',8,1)
    for row in value:
        closed(row,{'revision_id','source_sha256'},field='artifacts')
        text(row['revision_id'],'revision_id',140);checksum(row['source_sha256'])
    if len({r['revision_id'] for r in value})!=len(value):fail('Choose each exact artifact revision once.','artifacts')
    return value

def rfi_definition(value):
    closed(value,{'subject','question','responsible_users','due_date','location','contract_citation_ids'})
    text(value['subject'],'subject',240);text(value['question'],'question',20000);users(value['responsible_users']);day(value['due_date'],'due_date');text(value['location'],'location',500,blank=True)
    for cid in sequence(value['contract_citation_ids'],'contract_citation_ids') :checksum(cid,'contract_citation_ids')
    if len(set(value['contract_citation_ids']))!=len(value['contract_citation_ids']):fail('Choose each contract citation once.','contract_citation_ids')
    return value

def response_definition(value):
    closed(value,{'answer','potential_cost_impact','potential_schedule_impact'})
    text(value['answer'],'answer',20000)
    for key in ('potential_cost_impact','potential_schedule_impact'):text(value[key],key,2000,blank=True)
    return value

def submission_definition(value):
    closed(value,{'title','specification_section','equipment_tag','required_date','contractor','reviewer_user','submission_standing'})
    for key in ('title','specification_section','contractor','reviewer_user'):text(value[key],key,240 if key!='reviewer_user' else 140)
    text(value['equipment_tag'],'equipment_tag',200,blank=True);day(value['required_date'],'required_date')
    if value['submission_standing'] not in ('submitted','resubmitted'):fail('Declare submitted or resubmitted.','submission_standing')
    return value

def disposition_definition(value):
    closed(value,{'disposition','comments'})
    if value['disposition'] not in DISPOSITIONS:fail('Choose a registered submittal disposition.','disposition')
    text(value['comments'],'comments',20000,blank=True)
    return value

def package_digest(value):
    return digest({'schema':'cipher.engineering.package.v1','subject':value['subject'],'subject_digest':value['subject_digest'],
        'artifacts':value['artifacts'],'source_citations':value['source_citations'],'drawing_references':value['drawing_references'],'recipients':value['recipients'],
        'purpose':value['purpose'],'required_response':value['required_response'],'channel':'internal'})

RECORD_FIELDS={
 'rfi':({'number','revision_number','current_revision','response_head','official_response'},{'closure'}),
 'submittal':({'number','revision_number','current_submission','disposition_head','official_disposition'},set()),
 'rfi_revision':({'parent_id','revision_number','predecessor','definition','source_citations','artifacts','drawing_references','no_effects','responsible_people'},set()),
 'response':({'parent_id','revision_number','predecessor','definition','source_citations','artifacts','drawing_references','no_effects','source_revision','source_digest'},set()),
 'submission':({'parent_id','revision_number','predecessor','definition','source_citations','artifacts','drawing_references','no_effects','reviewer'},set()),
 'disposition':({'parent_id','revision_number','predecessor','definition','source_citations','artifacts','drawing_references','no_effects','source_revision','source_digest'},set()),
 'official_response':({'subject_id','subject_digest','packet_id','decision_id','checked_by_person','no_effects','authority','parent_id','source_revision','source_digest'},set()),
 'official_disposition':({'subject_id','subject_digest','packet_id','decision_id','checked_by_person','no_effects','authority','parent_id','source_revision','source_digest'},set()),
 'transmittal':({'subject','subject_digest','recipients','purpose','required_response','channel','source_citations','artifacts','drawing_references','no_effects','package_digest'},set()),
 'distribution':({'subject_id','subject_digest','packet_id','decision_id','checked_by_person','no_effects','authority','package_digest','recipients','channel','external_delivery'},set())}
BASE_FIELDS={'id','company','project','scope_type','author_person','author_user','created_at','status'}

def people(value,field,maximum=30,minimum=0):
    sequence(value,field,maximum,minimum)
    for row in value:
        closed(row,{'user','person'},field=field);text(row['user'],field,140);text(row['person'],field,140)
    if len({r['user'] for r in value})!=len(value) or len({r['person'] for r in value})!=len(value):fail('Use distinct canonical people.',field)

def record(kind,value,*,initial=False):
    if kind not in RECORD_FIELDS:fail('Unknown engineering kind.')
    required,optional=RECORD_FIELDS[kind];closed(value,BASE_FIELDS|required,optional)
    identifier(value['id']);text(value['company'],'company',140);text(value['project'],'project',140)
    if value['scope_type']!='Project':fail('Engineering requires an exact Project.','scope_type')
    for key in ('author_person','author_user'):text(value[key],key,140)
    from datetime import datetime
    try:
        if not value['created_at'].endswith('Z') or datetime.fromisoformat(value['created_at']).tzinfo is None:raise ValueError
    except (AttributeError,ValueError,TypeError):fail('Use the server timestamp.','created_at')
    statuses={'rfi':{'open','closed'},'submittal':{'open'},'official_response':{'official'},'official_disposition':{'official'},'transmittal':{'awaiting_independent_authorization'},'distribution':{'recorded_internally'}}
    if value['status'] not in statuses.get(kind,{'working'}):fail('Unexpected engineering standing.','status')
    for key in ('parent_id','subject_id','source_revision','predecessor','response_head','official_response','disposition_head','official_disposition'):
        if value.get(key) is not None:identifier(value[key],key)
    for key in ('current_revision','current_submission'):
        if key in value:
            if value[key] is None and initial and value['revision_number']==0:continue
            identifier(value[key],key)
    if 'revision_number' in value and (type(value['revision_number']) is not int or value['revision_number']<(0 if initial and kind in ('rfi','submittal') else 1)):fail('Use the exact positive revision number.','revision_number')
    for key in ('subject_digest','source_digest','package_digest'):
        if key in value:checksum(value[key],key)
    if 'no_effects' in value and (value['no_effects']!=NO_EFFECTS or any(v is not False for v in value['no_effects'].values())):fail('Engineering facts cannot authorize other domain effects.','no_effects')
    if 'definition' in value:{'rfi_revision':rfi_definition,'response':response_definition,'submission':submission_definition,'disposition':disposition_definition}[kind](value['definition'])
    if 'source_citations' in value:
        for row in sequence(value['source_citations'],'source_citations',64 if kind=='transmittal' else 8):
            closed(row,{'id','document_id','revision_id','document_title','revision_number','page','page_label','excerpt','excerpt_sha256','source_sha256'},field='source_citations')
            for key in ('id','excerpt_sha256','source_sha256'):checksum(row[key],key)
            citations([{k:row[k] for k in ('revision_id','page','excerpt_sha256','source_sha256')}])
    if 'artifacts' in value:
        for row in sequence(value['artifacts'],'artifacts',8):
            closed(row,{'document_id','revision_id','revision_number','source_sha256','byte_length','mime_type','page_count'},field='artifacts')
            checksum(row['source_sha256'])
    if 'drawing_references' in value:
        for row in sequence(value['drawing_references'],'drawing_references',16 if kind=='transmittal' else 8):
            closed(row,{'document_id','revision_id','revision_number','source_sha256','byte_length','mime_type','page_count','page','locator'},field='drawing_references')
            drawings([{k:row[k] for k in ('revision_id','source_sha256','page','locator')}])
    if 'responsible_people' in value:people(value['responsible_people'],'responsible_people',8)
    if 'reviewer' in value:people([value['reviewer']],'reviewer',1,1)
    if 'recipients' in value:people(value['recipients'],'recipients',30,1)
    if kind=='transmittal':
        closed(value['subject'],{'kind','id'});identifier(value['subject']['id'])
        if value['subject']['kind'] not in ('official_response','official_disposition'):fail('Select an exact official technical fact.')
        if package_digest(value)!=value['package_digest']:fail('The immutable package digest differs.')
        text(value['purpose'],'purpose');text(value['required_response'],'required_response',blank=True)
    if kind in ('transmittal','distribution') and value['channel']!='internal':fail('Only internal delivery is supported.')
    if kind in ('official_response','official_disposition','distribution'):
        if value['authority']!='internal-technical-only':fail('Unsupported technical authority.')
        for key in ('packet_id','decision_id','checked_by_person'):text(value[key],key,140)
    if kind=='distribution' and value['external_delivery'] is not False:fail('External delivery is unsupported.')
    if 'closure' in value:
        closed(value['closure'],{'official_response','reason','person','at'});identifier(value['closure']['official_response']);text(value['closure']['reason'],'reason')
    return value

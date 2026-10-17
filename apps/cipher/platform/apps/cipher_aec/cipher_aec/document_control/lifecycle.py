"""Append-only documentary withdrawal/supersession and exact current-issued projection."""
from copy import deepcopy
from cipher_aec.api.contracts import digest
from cipher_aec.api.errors import DomainError
from cipher_aec.governance.context import current_actor,require_project
from cipher_aec.engineering.sources import merge
from . import contracts as rules,repository as repo,service

def definition(value):
    rules.closed(value,{'action','issue_id','issue_digest','replacement_issue_id','replacement_issue_digest','reason'})
    if value['action'] not in ('withdraw','supersede'):rules.fail('Choose withdrawal or explicit supersession.','action')
    rules.identifier(value['issue_id']);rules.checksum(value['issue_digest']);rules.text(value['reason'],'reason',4000)
    if value['action']=='withdraw':
        if value['replacement_issue_id'] is not None or value['replacement_issue_digest'] is not None:rules.fail('Withdrawal has no replacement issue.','replacement_issue_id')
    else:
        rules.identifier(value['replacement_issue_id']);rules.checksum(value['replacement_issue_digest'])
        if value['replacement_issue_id']==value['issue_id']:rules.fail('Supersession requires a distinct exact replacement issue.','replacement_issue_id')

def issue_ref(issue,document_id):
    selected=[a for a in issue['artifacts'] if a['document_id']==document_id]
    if len(selected)!=1:raise DomainError('issue_document_conflict','An issued set must contain exactly one revision of this document for lifecycle use.',409)
    row=selected[0]
    return {'issue_id':issue['id'],'issue_digest':digest(issue),'revision_id':row['revision_id'],'source_sha256':row['source_sha256']}

def _body(company,project,document_id,baseline,current,last_event,status):
    return {'company':company,'project':project,'scope_type':'Project','document_id':document_id,'status':status,'original_issued':baseline,'current_issued':current,'last_event':last_event}

def _integrity(message):
    raise DomainError('issue_lifecycle_integrity',message,409)

def _initial(company,project,document_id,reference):
    return _body(company,project,document_id,reference,reference,None,'issued')

def _reference(value):
    rules.closed(value,{'issue_id','issue_digest','revision_id','source_sha256'})
    rules.identifier(value['issue_id']);rules.text(value['revision_id'],'revision_id',140)
    rules.checksum(value['issue_digest']);rules.checksum(value['source_sha256'])

def _sources(value,actor,*,lock=False):
    """Authorize exact original sources, without traversing a newer standing."""
    company,project=value['company'],value['project'];definition(value['definition'])
    service._document(value['parent_id'],company,project,actor,lock=lock)
    before=value['before']
    rules.closed(before,{'company','project','scope_type','document_id','status','original_issued','current_issued','last_event'})
    _reference(before['original_issued']);_reference(before['current_issued'])
    if before['last_event'] is not None:
        rules.closed(before['last_event'],{'id','record_digest'});rules.identifier(before['last_event']['id']);rules.checksum(before['last_event']['record_digest'])
    original=service.read('issue',value['definition']['issue_id'],company,project,actor,lock=lock)
    reference=issue_ref(original,value['parent_id']);replacement=None;artifacts=original['artifacts']
    if digest(original)!=value['definition']['issue_digest'] or value['expected_version']!=digest(before) or before['document_id']!=value['parent_id'] or before['company']!=company or before['project']!=project or before['scope_type']!='Project' or before['status']!='issued' or before['current_issued']!=reference:
        _integrity('The exact original issued standing differs.')
    if value['definition']['action']=='supersede':
        new=service.read('issue',value['definition']['replacement_issue_id'],company,project,actor,lock=lock);replacement=issue_ref(new,value['parent_id'])
        if digest(new)!=value['definition']['replacement_issue_digest'] or replacement['revision_id']==reference['revision_id']:
            _integrity('The exact authorized replacement differs.')
        artifacts=merge(artifacts,new['artifacts'])
    if len(artifacts)>16 or value['replacement']!=replacement or value['artifacts']!=artifacts or value['no_effects']!=rules.NO_EFFECTS:
        _integrity('The retained lifecycle source closure differs.')
    return reference

def _prefix(company,project,document_id,event_id,actor,*,lock=False):
    """Verify a bounded historical prefix iteratively, independent of later facts."""
    chain=[];seen=set();name=event_id
    while name is not None:
        if name in seen or len(seen)>=64:_integrity('The immutable lifecycle predecessor chain cycles or exceeds its bound.')
        seen.add(name);value=service.raw('lifecycle',name,company,project,lock=lock)
        if value['parent_id']!=document_id or value['document_id']!=document_id:_integrity('The lifecycle predecessor belongs to a different document.')
        chain.append(value);name=value['predecessor']
    body=None;previous=None
    for value in reversed(chain):
        request=service.raw('lifecycle_request',value['subject_id'],company,project,lock=lock)
        reference=_sources(request,actor,lock=lock)
        if body is None:body=_initial(company,project,document_id,reference)
        if request['parent_id']!=document_id or request['before']!=body or request['expected_version']!=digest(body):
            _integrity('An issued lifecycle event has a different original standing.')
        if value['subject_digest']!=digest(request) or value['author_person']!=request['author_person'] or value['artifacts']!=request['artifacts'] or value['before']!=request['before'] or value['replacement']!=request['replacement'] or any(value[k]!=request['definition'][k] for k in ('action','reason')) or value['revision_number']!=(previous['revision_number']+1 if previous else 1) or value['predecessor']!=(previous['id'] if previous else None) or value['status']!=('withdrawn' if value['action']=='withdraw' else 'superseded') or value['no_effects']!=rules.NO_EFFECTS or any(value[k] is not False for k in ('electronic_signature','professional_seal','external_delivery','commercial_execution')):
            _integrity('The exact lifecycle event differs from its independently approved request.')
        service._official_evidence('lifecycle',value,actor,lock=lock)
        current=request['replacement'];body=_body(company,project,document_id,body['original_issued'],current,{'id':value['id'],'record_digest':digest(value)},'issued' if current else 'withdrawn');previous=value
    return body

def standing(company,project,document_id,actor,*,lock=False):
    require_project(company,project,ability=rules.READ,actor=actor,lock=lock);service._document(document_id,company,project,actor,lock=lock)
    events=repo.lifecycle_chain(document_id,lock=lock)
    if events:
        # The complete projection also rejects orphan/duplicate sequence rows;
        # historical receipt verification only reads its own original prefix.
        previous=None
        for value in events:
            if value['company']!=company or value['project']!=project or value['scope_type']!='Project' or value['parent_id']!=document_id or value['predecessor']!=(previous['id'] if previous else None) or value['revision_number']!=(previous['revision_number']+1 if previous else 1):
                _integrity('The append-only issued lifecycle chain differs.')
            previous=value
        body=_prefix(company,project,document_id,events[-1]['id'],actor,lock=lock)
    else:
        candidates=repo.issue_candidates(company,project,document_id,lock=lock)
        reference=issue_ref(service.read('issue',candidates[0],company,project,actor,lock=lock),document_id) if candidates else None
        body=_initial(company,project,document_id,reference) if reference else _body(company,project,document_id,None,None,None,'not_issued')
    return {**body,'version':digest(body)}

def get_standing(company,project,document_id):return {'standing':standing(company,project,document_id,current_actor())}

def request(company,project,operation_id,document_id,expected_version,definition_value):
    rules.text(document_id,'document_id',140);rules.checksum(expected_version);definition(definition_value)
    def effect(actor,_):
        before=standing(company,project,document_id,actor,lock=True)
        if before['version']!=expected_version:raise DomainError('stale_issued_standing','Review the exact current issued standing before changing it.',412)
        previous=before['current_issued']
        if previous is None:raise DomainError('document_not_currently_issued','Only a currently issued document revision can be withdrawn or superseded.',409)
        if previous['issue_id']!=definition_value['issue_id'] or previous['issue_digest']!=definition_value['issue_digest']:raise DomainError('stale_issued_standing','The selected original issue is no longer current.',412)
        original=service.read('issue',definition_value['issue_id'],company,project,actor,lock=True);replacement=None;artifacts=original['artifacts']
        if definition_value['action']=='supersede':
            new=service.read('issue',definition_value['replacement_issue_id'],company,project,actor,lock=True)
            if digest(new)!=definition_value['replacement_issue_digest']:raise DomainError('stale_replacement_issue','Choose the exact authorized replacement issue.',412)
            replacement=issue_ref(new,document_id)
            if replacement['revision_id']==previous['revision_id']:rules.fail('Supersession selects a different immutable document revision.','replacement_issue_id')
            artifacts=merge(artifacts,new['artifacts'])
        body={k:v for k,v in before.items() if k!='version'}
        value=service.base(company,project,actor,parent_id=document_id,expected_version=expected_version,before=body,definition=deepcopy(definition_value),replacement=replacement,artifacts=deepcopy(artifacts));repo.write('lifecycle_request',value)
        return {'lifecycle_request':value,'history_id':service.event(actor,value,operation_id,'lifecycle_request','lifecycle.prepared')}
    return service.command(company,project,operation_id,'lifecycle.prepare',{'document_id':document_id,'expected_version':expected_version,'definition':definition_value},effect,ability=rules.ISSUE)

def verify_request(value,actor,*,lock=False):
    reference=_sources(value,actor,lock=lock);before=value['before'];last=before['last_event']
    if last is None:expected=_initial(value['company'],value['project'],value['parent_id'],reference)
    else:
        event=service.raw('lifecycle',last['id'],value['company'],value['project'],lock=lock)
        if digest(event)!=last['record_digest']:_integrity('The original lifecycle predecessor digest differs.')
        expected=_prefix(value['company'],value['project'],value['parent_id'],last['id'],actor,lock=lock)
    if before!=expected:_integrity('The retained request has a different original lifecycle prefix.')

def verify_event(value,actor,*,lock=False):
    _prefix(value['company'],value['project'],value['parent_id'],value['id'],actor,lock=lock)

def require_current_issue(value,actor,*,lock=False):
    """New delivery refuses withdrawn/superseded or not-current issued content."""
    company,project=value['company'],value['project']
    from .shared import artifact_scope
    for row in value['artifacts']:
        scope,source_project=artifact_scope(company,row)
        # Company/shared sources are exact package references. Project issue
        # standing does not create a global Company-library publication status.
        if scope!='Project' or source_project!=project:continue
        current=standing(company,project,row['document_id'],actor,lock=lock)
        if current['current_issued'] is None or current['current_issued']['revision_id']!=row['revision_id'] or current['current_issued']['source_sha256']!=row['source_sha256']:raise DomainError('issued_content_not_current','This issued package includes withdrawn, superseded or not-current document content.',409)

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

def standing(company,project,document_id,actor,*,lock=False):
    require_project(company,project,ability=rules.READ,actor=actor,lock=lock);service._document(document_id,company,project,actor,lock=lock)
    candidates=repo.issue_candidates(company,project,document_id,lock=lock)
    if not candidates:
        body=_body(company,project,document_id,None,None,None,'not_issued');return {**body,'version':digest(body)}
    first=service.read('issue',candidates[0],company,project,actor,lock=lock);baseline=issue_ref(first,document_id);current=baseline;event_ref=None;status='issued'
    events=repo.lifecycle_chain(document_id,lock=lock)
    previous=None
    for value in events:
        if value['company']!=company or value['project']!=project or value['parent_id']!=document_id or value['predecessor']!=(previous['id'] if previous else None) or value['revision_number']!=(previous['revision_number']+1 if previous else 1):raise DomainError('issue_lifecycle_integrity','The append-only issued lifecycle chain differs.',409)
        # Authorize only exact recorded facts, never later working revisions.
        service.read('lifecycle',value['id'],company,project,actor,lock=lock)
        before=_body(company,project,document_id,baseline,current,event_ref,status)
        request=service.raw('lifecycle_request',value['subject_id'],company,project,lock=lock)
        if request['before']!=before or request['expected_version']!=digest(before):raise DomainError('issue_lifecycle_integrity','An issued lifecycle event has a different original standing.',409)
        current=request['replacement'] if request['definition']['action']=='supersede' else None;status='issued' if current else 'withdrawn';event_ref={'id':value['id'],'record_digest':digest(value)};previous=value
    body=_body(company,project,document_id,baseline,current,event_ref,status)
    return {**body,'version':digest(body)}

def get_standing(company,project,document_id):return {'standing':standing(company,project,document_id,current_actor())}

def request(company,project,operation_id,document_id,expected_version,definition_value):
    rules.identifier(document_id);rules.checksum(expected_version);definition(definition_value)
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
    company,project=value['company'],value['project'];definition(value['definition']);service._document(value['parent_id'],company,project,actor,lock=lock)
    original=service.read('issue',value['definition']['issue_id'],company,project,actor,lock=lock);reference=issue_ref(original,value['parent_id']);before=value['before'];replacement=None;artifacts=original['artifacts']
    if digest(original)!=value['definition']['issue_digest'] or value['expected_version']!=digest(before) or before['document_id']!=value['parent_id'] or before['company']!=company or before['project']!=project or before['scope_type']!='Project' or before['status']!='issued' or before['current_issued']!=reference:raise DomainError('issue_lifecycle_integrity','The exact original issued standing differs.',409)
    if before['last_event']:
        previous=service.read('lifecycle',before['last_event']['id'],company,project,actor,lock=lock)
        if digest(previous)!=before['last_event']['record_digest'] or previous['parent_id']!=value['parent_id']:raise DomainError('issue_lifecycle_integrity','The original lifecycle predecessor differs.',409)
    if value['definition']['action']=='supersede':
        new=service.read('issue',value['definition']['replacement_issue_id'],company,project,actor,lock=lock);replacement=issue_ref(new,value['parent_id'])
        if digest(new)!=value['definition']['replacement_issue_digest'] or replacement['revision_id']==reference['revision_id']:raise DomainError('issue_lifecycle_integrity','The exact authorized replacement differs.',409)
        artifacts=merge(artifacts,new['artifacts'])
    if value['replacement']!=replacement or value['artifacts']!=artifacts:raise DomainError('issue_lifecycle_integrity','The retained lifecycle source closure differs.',409)

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

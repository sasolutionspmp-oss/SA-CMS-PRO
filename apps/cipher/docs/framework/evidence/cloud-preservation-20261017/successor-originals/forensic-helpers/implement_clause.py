from pathlib import Path
import json
root=Path('/dev/shm/cipher-documents-doc03-successor/workspace/apps/cipher/platform/apps/cipher_aec/cipher_aec')
def edit(rel,old,new):
 p=root/rel;s=p.read_text()
 if old not in s:raise RuntimeError(rel+' missing '+old[:60])
 p.write_text(s.replace(old,new))
p=root/'document_control/contracts.py';s=p.read_text().replace("'evidence':'Cipher Documentary Evidence'","'evidence':'Cipher Documentary Evidence','clause_use':'Cipher Clause Use','redline':'Cipher Redline Revision','clause_application':'Cipher Clause Application'").replace("'transmittal':'document.transmit.v1'","'transmittal':'document.transmit.v1','redline':'document.clause.apply.v1'").replace("'transmittal':'distribution'","'transmittal':'distribution','redline':'clause_application'").replace("'transmittal':DISTRIBUTE}","'transmittal':DISTRIBUTE,'redline':ADOPT}")
s+='''\n\ndef clause_source(value):
    closed(value,{'revision_id','source_sha256','page','excerpt_sha256','start','end'})
    identifier(value['revision_id']);checksum(value['source_sha256']);checksum(value['excerpt_sha256'])
    if type(value['page']) is not int or not 1<=value['page']<=10000:fail('Choose an exact source page.','page')
    if type(value['start']) is not int or type(value['end']) is not int or not 0<=value['start']<value['end']<=1000000:fail('Choose a nonempty exact text range.','source_clause')
\ndef clause_target(value):
    closed(value,{'kind','id','record_digest','locator'})
    if value['kind'] not in ('proposal_revision','contract_revision','document_revision'):fail('Choose an immutable proposal, contract or document revision.','target.kind')
    identifier(value['id']);checksum(value['record_digest']);text(value['locator'],'target.locator',2000)
'''
p.write_text(s)
(root/'document_control/clauses.py').write_text('''"""Exact clause lineage and proposed redlines; approval never edits the target."""
from copy import deepcopy
import hashlib
from cipher_aec.api.contracts import digest
from cipher_aec.api.errors import DomainError
from . import contracts as rules,repository as repo,service

def target_record(company,project,kind,name,actor,*,lock=False):
    if kind=='proposal_revision':
        from cipher_aec.commercial.service import _read
        value=_read('revision',name,company,actor,lock=lock)[1]
        parent=value['proposal'];scope='Company';source_project=None
    elif kind=='contract_revision':
        from cipher_aec.construction_finance.service import scoped
        value=scoped('revision',name,company,project,actor,lock=lock)
        parent=value['contract'];scope='Project';source_project=project
    elif kind=='document_revision':
        from cipher_aec.engineering.sources import artifact
        from cipher_aec.documents.repository import FrappeDocumentRepository
        locator=FrappeDocumentRepository().revision_scope(name)
        if locator.company!=company or locator.project!=project or (locator.scope_type or 'Project')!='Project':raise DomainError('not_found','This exact clause target is unavailable.',404)
        revision=FrappeDocumentRepository().revision(name,lock=lock)
        value=artifact(company,project,{'revision_id':name,'source_sha256':revision['sha256']},actor,lock=lock)
        parent=value['document_id'];scope='Project';source_project=project
    else:rules.fail('Choose a supported exact clause target.','kind')
    if value.get('company',company)!=company or (scope=='Project' and value.get('project',project)!=project):raise DomainError('not_found','This exact clause target is unavailable.',404)
    return {'kind':kind,'id':name,'record_digest':digest(value),'parent_id':parent,'company':company,'project':source_project,'scope_type':scope}

def read_target(company,project,kind,record_id):
    from cipher_aec.governance.context import current_actor,require_project
    actor=current_actor();require_project(company,project,ability=rules.READ,actor=actor)
    return {'target':target_record(company,project,kind,record_id,actor)}

def quoted_source(company,project,reference,artifacts,actor,*,lock=False):
    rules.clause_source(reference)
    if not any(row['revision_id']==reference['revision_id'] and row['source_sha256']==reference['source_sha256'] for row in artifacts):raise DomainError('clause_source_mismatch','The exact clause must belong to the original adopted artifact.',409)
    from cipher_aec.documents.service import get_citation
    citation=get_citation(company,reference['revision_id'],reference['page'],reference['excerpt_sha256'],actor=actor)
    if citation['source_sha256']!=reference['source_sha256'] or citation['revision_id']!=reference['revision_id'] or citation['page']!=reference['page']:raise DomainError('clause_source_mismatch','The original clause citation differs.',409)
    text=citation['excerpt'];start,end=reference['start'],reference['end']
    if end>len(text):rules.fail('The selected clause exceeds the exact original text.','source_clause')
    wording=text[start:end];rules.text(wording,'source_clause.text',12000)
    return {'reference':deepcopy(reference),'text':wording,'text_sha256':hashlib.sha256(wording.encode('utf-8')).hexdigest()}

def create_clause_use(company,project,operation_id,adoption_id,adoption_digest,source_clause,target,purpose):
    rules.identifier(adoption_id);rules.checksum(adoption_digest);rules.clause_source(source_clause);rules.clause_target(target);rules.text(purpose,'purpose',4000)
    def effect(actor,_):
        original=service.read('adoption',adoption_id,company,project,actor,lock=True)
        if digest(original)!=adoption_digest:raise DomainError('stale_clause_adoption','Choose the exact independently adopted original.',412)
        actual=target_record(company,project,target['kind'],target['id'],actor,lock=True)
        if actual['record_digest']!=target['record_digest']:raise DomainError('stale_clause_target','Choose the exact original target revision.',412)
        quoted=quoted_source(company,project,source_clause,original['artifacts'],actor,lock=True)
        value=service.base(company,project,actor,parent_id=adoption_id,adoption_id=adoption_id,adoption_digest=adoption_digest,source_clause=quoted,target=deepcopy(target),target_snapshot=actual,purpose=purpose,artifacts=deepcopy(original['artifacts']),status='referenced',target_changed=False)
        repo.write('clause_use',value)
        return {'clause_use':value,'history_id':service.event(actor,value,operation_id,'clause_use','clause.referenced')}
    return service.command(company,project,operation_id,'clause.reference',{'adoption_id':adoption_id,'adoption_digest':adoption_digest,'source_clause':source_clause,'target':target,'purpose':purpose},effect)

def create_redline(company,project,operation_id,clause_use_id,clause_use_digest,expected_version,proposed_text,reason):
    rules.identifier(clause_use_id);rules.checksum(clause_use_digest)
    if expected_version is not None:rules.checksum(expected_version)
    rules.text(proposed_text,'proposed_text',12000);rules.text(reason,'reason',4000)
    def effect(actor,_):
        original=service.read('clause_use',clause_use_id,company,project,actor,lock=True);previous=repo.latest('redline',clause_use_id,lock=True)
        if digest(original)!=clause_use_digest or (digest(previous) if previous else None)!=expected_version:raise DomainError('stale_redline','Review the exact clause use and latest proposed redline.',412)
        if proposed_text==original['source_clause']['text']:rules.fail('A redline must propose a change to the original clause.','proposed_text')
        value=service.base(company,project,actor,parent_id=clause_use_id,clause_use_id=clause_use_id,clause_use_digest=clause_use_digest,predecessor=previous['id'] if previous else None,revision_number=previous['revision_number']+1 if previous else 1,original_text=original['source_clause']['text'],proposed_text=proposed_text,proposed_sha256=hashlib.sha256(proposed_text.encode('utf-8')).hexdigest(),reason=reason,target=deepcopy(original['target']),target_snapshot=deepcopy(original['target_snapshot']),artifacts=deepcopy(original['artifacts']),status='proposed',target_changed=False)
        repo.write('redline',value)
        return {'redline':value,'history_id':service.event(actor,value,operation_id,'redline','redline.proposed')}
    return service.command(company,project,operation_id,'redline.propose',{'clause_use_id':clause_use_id,'clause_use_digest':clause_use_digest,'expected_version':expected_version,'proposed_text':proposed_text,'reason':reason},effect)

def verify(kind,value,actor,*,lock=False):
    company,project=value['company'],value['project']
    if kind=='clause_use':
        original=service.read('adoption',value['adoption_id'],company,project,actor,lock=lock)
        if digest(original)!=value['adoption_digest'] or original['artifacts']!=value['artifacts'] or value['parent_id']!=original['id'] or quoted_source(company,project,value['source_clause']['reference'],original['artifacts'],actor,lock=lock)!=value['source_clause']:raise DomainError('clause_integrity','The exact adopted clause lineage differs.',409)
    elif kind=='redline':
        original=service.read('clause_use',value['clause_use_id'],company,project,actor,lock=lock)
        previous=service.raw('redline',value['predecessor'],company,project,lock=lock) if value['predecessor'] else None
        if digest(original)!=value['clause_use_digest'] or value['parent_id']!=original['id'] or value['original_text']!=original['source_clause']['text'] or value['artifacts']!=original['artifacts'] or value['target']!=original['target'] or value['target_snapshot']!=original['target_snapshot'] or value['proposed_sha256']!=hashlib.sha256(value['proposed_text'].encode('utf-8')).hexdigest() or (previous and (previous['parent_id']!=value['parent_id'] or previous['revision_number']+1!=value['revision_number'])) or (not previous and value['revision_number']!=1):raise DomainError('clause_integrity','The original redline family or text differs.',409)
    actual=target_record(company,project,value['target']['kind'],value['target']['id'],actor,lock=lock)
    if actual!=value['target_snapshot'] or actual['record_digest']!=value['target']['record_digest'] or value['target_changed'] is not False:raise DomainError('clause_integrity','The immutable clause target differs.',409)
''')
# Native records use the same exact private command guard and immutable controllers.
p=root/'document_control/records.py';s=p.read_text().replace("'evidence':{'parent_id'", "'clause_use':{'parent_id','adoption_id','adoption_digest','source_clause','target','target_snapshot','purpose','artifacts','target_changed'},'redline':{'parent_id','clause_use_id','clause_use_digest','predecessor','revision_number','original_text','proposed_text','proposed_sha256','reason','target','target_snapshot','artifacts','target_changed'},'clause_application':FACT|{'target','target_snapshot','original_text','proposed_text','proposed_sha256','target_changed'},'evidence':{'parent_id'")
p.write_text(s)
p=root/'document_control/service.py';s=p.read_text().replace("elif kind in ('issue','adoption','distribution'):","elif kind in ('clause_use','redline'):\n        from .clauses import verify\n        verify(kind,value,actor,lock=lock)\n    elif kind in ('issue','adoption','distribution','clause_application'):").replace("{'issue':'issue_set','adoption':'adoption_request','distribution':'transmittal'}", "{'issue':'issue_set','adoption':'adoption_request','distribution':'transmittal','clause_application':'redline'}")
s=s.replace("_official_evidence(kind,value,actor,lock=lock)","_official_evidence(kind,value,actor,lock=lock)\n        if kind=='clause_application' and any(value[k]!=original[k] for k in ('target','target_snapshot','original_text','proposed_text','proposed_sha256','target_changed')):raise DomainError('clause_integrity','The approved documentary relationship differs from its original proposed redline.',409)")
p.write_text(s)
p=root/'document_control/governance.py';s=p.read_text().replace("company,project=value['company'],value['project']", "company,project=value['company'],value['project']\n    if kind=='redline':\n        latest=repo.latest('redline',value['parent_id'],lock=lock)\n        if latest is None or latest['id']!=value['id']:raise DomainError('redline_superseded','Only the latest proposed redline may receive a new documentary authorization.',409)")
s=s.replace("if kind=='adoption_request':authors.add", "if kind=='redline':authors.add(service.read('clause_use',value['clause_use_id'],company,project,actor,lock=lock)['author_person'])\n        if kind=='adoption_request':authors.add")
s=s.replace("else:effect.update(library_revision=", "elif kind=='redline':effect.update(target=value['target'],target_snapshot=value['target_snapshot'],original_text=value['original_text'],proposed_text=value['proposed_text'],proposed_sha256=value['proposed_sha256'],target_changed=False)\n    else:effect.update(library_revision=")
s=s.replace("value['purpose'] if kind=='transmittal' else value['definition'].get('title',value['definition'].get('purpose'))", "value['purpose'] if kind=='transmittal' else value['reason'] if kind=='redline' else value['definition'].get('title',value['definition'].get('purpose'))")
s=s.replace("'distribution':'recorded_internally'", "'distribution':'recorded_internally','clause_application':'approved_relationship'")
s=s.replace("repo.write(factkind,value)","if kind=='redline':value.update({k:deepcopy(original[k]) for k in ('target','target_snapshot','original_text','proposed_text','proposed_sha256','target_changed')})\n    repo.write(factkind,value)").replace('from functools import partial','from functools import partial\nfrom copy import deepcopy')
p.write_text(s)
# Exactly static new action, no old action/subject pairing changes.
p=root/'governance/domain_approvals.py';s=p.read_text().replace('("document.issue.v1",','("document.clause.apply.v1","Cipher Redline Revision","Independent exact documentary clause relationship","document.adopt","CIPHER-DOCUMENT-CLAUSE-APPLY-POLICY-V1"),\n      ("document.issue.v1",',1).replace('{"document.issue.v1","document.library.adopt.v1","document.transmit.v1"}', '{"document.issue.v1","document.library.adopt.v1","document.transmit.v1","document.clause.apply.v1"}')
p.write_text(s)
p=root/'governance/approvals.py';s=p.read_text().replace('{"document.issue.v1","document.library.adopt.v1","document.transmit.v1"}', '{"document.issue.v1","document.library.adopt.v1","document.transmit.v1","document.clause.apply.v1"}')
p.write_text(s)
p=root/'document_control/records.py';s=p.read_text().replace("'distribution':'transmittal'}[kind]", "'distribution':'transmittal','clause_application':'redline'}[kind]")
p.write_text(s)
# New immutable records use unchanged conventional DocType fields.
template=json.loads((root/'cipher_document_control/doctype/cipher_adoption_request/cipher_adoption_request.json').read_text())
for name in ['Cipher Clause Use','Cipher Redline Revision','Cipher Clause Application']:
 slug=name.lower().replace(' ','_');d=root/'cipher_document_control/doctype'/slug;d.mkdir();(d/'__init__.py').write_text('');(d/(slug+'.py')).write_text('from cipher_aec.document_control.records import DocumentaryRecord\n\nclass '+name.replace(' ','')+'(DocumentaryRecord):\n    pass\n');v={**template,'name':name};(d/(slug+'.json')).write_text(json.dumps(v,indent=2)+'\n')
p=root/'document_control/install.py';s=p.read_text().replace("('rights','library_revision')", "('rights','library_revision','redline')").replace("('issue','adoption','distribution')", "('issue','adoption','distribution','clause_application')")
p.write_text(s)
# Closed native access for all three new record kinds.
p=root/'hooks.py';s=p.read_text();needle='permission_query_conditions = {';pos=s.index(needle)+len(needle);s=s[:pos]+''.join('\n    "'+name+'": "cipher_aec.document_control.install.query_denied",' for name in ['Cipher Clause Use','Cipher Redline Revision','Cipher Clause Application'])+s[pos:];needle='has_permission = {';pos=s.index(needle)+len(needle);s=s[:pos]+''.join('\n    "'+name+'": "cipher_aec.document_control.install.permission_denied",' for name in ['Cipher Clause Use','Cipher Redline Revision','Cipher Clause Application'])+s[pos:];p.write_text(s)

"""Exact clause lineage and proposed redlines; approval never edits the target."""
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
        value=scoped('revision',name,company,project,actor,lock=False)
        if lock:
            from cipher_aec.estimating.units import qualified
            from cipher_aec.engineering.sources import verify
            from cipher_aec.construction_finance import repository as contracts,sources as contract_sources
            from cipher_aec.commercial.native import require_native
            header=contracts.read('contract',value['contract'],lock=True)
            original=contracts.read('revision',name,lock=True)
            if original!=value:raise DomainError('clause_integrity','The immutable contract target changed.',409)
            for unit in value['units']:
                if qualified(unit['id'],actor=actor,lock=True,allow_disabled=True)!=unit:raise DomainError('stale_unit','The exact original contract unit differs.',412)
            require_native('Currency',value['currency'],actor,lock=True)
            contract_sources.party_snapshot(company,project,header['definition'],actor,lock=True,allow_disabled=True)
            verify(company,project,value,actor,lock=True)
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
    from .shared import artifact_scope
    scope,source_project=artifact_scope(company,reference)
    if scope=='Company':
        from cipher_aec.documents.service import get_company_citation
        citation=get_company_citation(company,reference['revision_id'],reference['page'],reference['excerpt_sha256'],actor=actor)
    else:
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

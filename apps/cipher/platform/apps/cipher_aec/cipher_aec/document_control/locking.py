"""Bounded metadata discovery and complete source union before source/native locks.

Discovery grants no content authority. Canonical readers still authorize each
original record and byte source under current actor duties and rights.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from cipher_aec.api.errors import DomainError
from cipher_aec.governance.context import require_project,require_company
from . import repository as repo,contracts as rules
_active=ContextVar('document_control_complete_union',default=None)
NEW_KINDS=frozenset(('clause_use','redline','clause_application'))

def _merge(*plans):
    from cipher_aec.commercial.sources import merge
    return merge(*plans)

def target_plan(company,project,target,actor):
    kind,name=target['kind'],target['id']
    if kind=='proposal_revision':
        from cipher_aec.commercial.sources import revision_plan
        return revision_plan(company,name,actor)
    if kind=='contract_revision':
        from cipher_aec.construction_finance.repository import read
        value=read('revision',name);header=read('contract',value['contract'])
        if value['company']!=company or value['project']!=project or header['company']!=company or header['project']!=project:raise DomainError('not_found','This exact clause target is unavailable.',404)
        return {'unit_ids':[u['id'] for u in value['units']],'currencies':[value['currency']],'native_refs':[{'doctype':header['definition']['party_type'],'name':header['definition']['party']}]}
    return {}

def proposal_revisions(company,name,actor):
    from cipher_aec.commercial.sources import revision_record
    value=revision_record(company,name,actor)
    revisions={row['revision_id'] for row in value['composition'].get('source_references',[])}
    baseline=value['composition'].get('estimate_reference')
    if baseline:
        from cipher_aec.estimating import scopes
        from cipher_aec.estimating.lockplan import Discovery
        with scopes.activate('Company',company,None):
            discovery=Discovery(company,actor)
            discovery.record('estimate','acceptance',baseline['acceptance_id'])
            revisions.update(discovery.revisions)
    if len(revisions)>128:raise DomainError('document_source_limit','The original proposal sources exceed their bound.',409)
    return revisions

class DocumentContext:
    def __init__(self,company,project,roots=(),targets=(),artifacts=(),documents=(),scope_type='Project'):
        self.company,self.project,self.scope_type=company,project,scope_type
        self.roots=tuple(roots);self.targets=deepcopy(list(targets));self.artifacts=deepcopy(list(artifacts));self.documents=set(documents);self.initial=None
    def discover(self,actor):
        from cipher_aec.documents.repository import FrappeDocumentRepository
        from cipher_aec.documents.provenance import source_plan
        from . import rights
        todo=list(self.roots);seen=set();artifacts=list(self.artifacts);targets=list(self.targets)
        while todo:
            kind,name=todo.pop()
            if (kind,name) in seen:continue
            seen.add((kind,name))
            if len(seen)>128:raise DomainError('document_source_limit','The original documentary closure exceeds its bound.',409)
            value=repo.raw(kind,name)
            if value['company']!=self.company:raise DomainError('not_found','This original source is unavailable.',404)
            artifacts.extend(value.get('artifacts',[]))
            if kind=='rights':artifacts.append(value['evidence_artifact'])
            for adoption in value.get('adoptions',[]):todo.append(('adoption',adoption['id']))
            if value.get('target'):targets.append(value['target'])
            for k,field in [('adoption','adoption_id'),('clause_use','clause_use_id'),('library_revision','library_revision')]:
                if value.get(field):todo.append((k,value[field]))
            if kind in rules.FACTS.values():todo.append((next(k for k,v in rules.FACTS.items() if v==kind),value['subject_id']))
            if kind=='library' and value.get('current_revision'):todo.append(('library_revision',value['current_revision']))
        # Include pinned Company proposal/estimate sources, including raw
        # inputs nested behind a generated source. No current head traversal.
        proposal_ids={target['id'] for target in targets if target['kind']=='proposal_revision'}
        proposals_seen=set()
        while proposal_ids:
            name=proposal_ids.pop()
            if name in proposals_seen:continue
            proposals_seen.add(name)
            if len(proposals_seen)>64:raise DomainError('document_source_limit','The proposal source closure exceeds its bound.',409)
            for revision in proposal_revisions(self.company,name,actor):artifacts.append({'revision_id':revision})
        # Include all Project target source citations before any master lock.
        for target in targets:
            if target['kind']=='contract_revision':
                from cipher_aec.construction_finance.repository import read
                value=read('revision',target['id']);artifacts.extend(value.get('source_citations',[]))
            elif target['kind']=='document_revision':artifacts.append({'revision_id':target['id']})
        metadata_documents=set(self.documents)
        for kind,name in seen:
            if kind=='rights':metadata_documents.add(repo.raw(kind,name)['parent_id'])
        # Only byte-bearing sources traverse current content permission. A
        # historical rights record's governed parent is metadata, not a new
        # entitlement to its current permission evidence or later source head.
        from cipher_aec.documents.provenance import binding
        revisions={ref['revision_id'] for ref in artifacts};pending=list(revisions);source_documents=set();visited=set();plans=[]
        while pending:
            revision=pending.pop()
            if revision in visited:continue
            visited.add(revision)
            if len(visited)>128:raise DomainError('document_source_limit','The original source/evidence revision closure exceeds its bound.',409)
            locator=FrappeDocumentRepository().revision_scope(revision)
            if locator.company!=self.company:raise DomainError('not_found','This original source is unavailable.',404)
            scope=locator.scope_type or 'Project';source_documents.add(locator.document)
            policy=rights.current(locator.document)
            if policy:pending.append(policy['evidence_artifact']['revision_id'])
            if scope=='Company':
                plans.append(source_plan(self.company,revision,actor))
                generated=binding(FrappeDocumentRepository('Company').document(locator.document))
                if generated:pending.extend(proposal_revisions(self.company,generated['proposal_revision_id'],actor))
        documents=metadata_documents|rights.document_plan(source_documents)
        scopes={(self.scope_type,self.project)};locations={}
        for name in sorted(documents):
            row=FrappeDocumentRepository().document_scope(name)
            scope=row.scope_type or 'Project'
            if row.company!=self.company or scope not in ('Project','Company') or (scope=='Company' and row.project is not None) or (scope=='Project' and not row.project):raise DomainError('not_found','This original source scope is unavailable.',404)
            locations[name]=(scope,row.project);scopes.add((scope,row.project))
        for target in targets:
            if target['kind']=='proposal_revision':scopes.add(('Company',None))
            plans.append(target_plan(self.company,self.project,target,actor))
        native=_merge(*plans)
        if len(native.get('unit_ids',[]))>500 or len(native.get('currencies',[]))>20 or len(native.get('native_refs',[]))>1000:raise DomainError('document_source_limit','The complete documentary master union exceeds its bound.',409)
        return {'scopes':sorted(scopes,key=lambda v:(v[0],v[1] or '')),'documents':locations,'native':native}
    def prelock(self,actor):
        planned=self.discover(actor)
        for kind,name in planned['scopes']:
            if kind=='Company':require_company(self.company,ability='document.read',actor=actor,lock=True)
            else:require_project(self.company,name,ability='document.read',actor=actor,lock=True)
        self.initial=planned
    @contextmanager
    def hold(self,actor,result=None):
        if result is not None:
            original=for_result(self.company,self.project,result,scope_type=self.scope_type)
            if original is not None:
                with original.hold(actor):yield
                return
        from cipher_aec.documents.provenance import prelocked
        from cipher_aec.estimating.units import qualified
        from cipher_aec.commercial.native import require_native
        from . import scopes
        current=_active.get()
        if current is not None:
            observed=self.discover(actor)
            if current['company']!=self.company or not set(map(tuple,observed['scopes']))<=set(map(tuple,current['plan']['scopes'])) or not set(observed['documents'])<=set(current['plan']['documents']) or _merge(observed['native'],current['plan']['native'])!=current['plan']['native']:raise DomainError('document_prelock_required','The outer documentary command must hold its complete original source union.',409)
            yield;return
        if self.initial is None:self.prelock(actor)
        if self.discover(actor)!=self.initial:raise DomainError('document_sources_changed','Original source dependencies changed concurrently. Retry the original operation.',503)
        plan=self.initial;native=plan['native']
        for unit in native.get('unit_ids',[]):qualified(unit,actor=actor,lock=True,allow_disabled=True)
        for currency in native.get('currencies',[]):require_native('Currency',currency,actor,lock=True)
        for row in native.get('native_refs',[]):require_native(row['doctype'],row['name'],actor,lock=True)
        for name,(scope,project) in sorted(plan['documents'].items()):scopes.document(name,self.company,scope,project,actor,lock=True)
        if self.discover(actor)!=plan:raise DomainError('document_sources_changed','Original source dependencies changed concurrently. Retry the original operation.',503)
        token=_active.set({'company':self.company,'plan':plan})
        try:
            with prelocked(native,actor,self.company):yield
        finally:_active.reset(token)

def for_payload(company,project,name,payload):
    if name=='clause.reference':return DocumentContext(company,project,[('adoption',payload['adoption_id'])],[payload['target']])
    if name=='redline.propose':return DocumentContext(company,project,[('clause_use',payload['clause_use_id'])])
    if name in ('shared.adoption.prepare','adoption.prepare'):return DocumentContext(company,project,[('library_revision',payload['library_revision'])])
    if name=='issue.prepare':return DocumentContext(company,project,[('adoption',r['id']) for r in payload['adoptions']],artifacts=payload['artifacts'])
    if name=='transmittal.prepare':return DocumentContext(company,project,[('issue',payload['issue_id'])])
    if name=='evidence.report':return DocumentContext(company,project,[(payload['subject_kind'],payload['subject_id'])],artifacts=payload['artifacts'])
    if name=='rights.record':return DocumentContext(company,project,artifacts=[payload['definition']['evidence_artifact']],documents=[payload['document_id']])
    if name in ('library.create','library.revise'):return DocumentContext(company,project,[('library',payload['library_id'])] if payload.get('library_id') else (),artifacts=[payload['artifact']])
    return None

def for_approval(company,project,payload):
    import frappe
    action=payload.get('action');subject=payload.get('subject_id')
    if payload.get('packet_id'):
        packet=frappe.get_doc('Cipher Approval Packet',payload['packet_id'])
        if packet.company!=company or packet.project!=project:return None
        action,subject=packet.action,packet.subject_id
    if action in rules.ACTIONS.values():return DocumentContext(company,project,[(next(k for k,v in rules.ACTIONS.items() if v==action),subject)])
    return None

def for_result(company,project,result,*,scope_type='Project'):
    roots=[]
    def visit(value):
        if type(value) is not dict:return
        for kind in rules.KINDS:
            row=value.get(kind)
            if type(row) is dict and row.get('id') and kind!='library':roots.append((kind,row['id']))
        if value.get('schema')=='cipher.document.approval.v1' and value.get('action') in rules.ACTIONS.values():roots.append((next(k for k,v in rules.ACTIONS.items() if v==value['action']),value['subject']['id']))
        for child in value.values():
            if type(child) is dict:visit(child)
    visit(result)
    return DocumentContext(company,project,roots,scope_type=scope_type) if roots else None

"""Explicit human save context for the two existing canonical Company writers."""
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
import hashlib
import json

from cipher_aec.api.contracts import canonical_json, digest
from cipher_aec.api.errors import DomainError
from .company_contracts import decode_run_authority
from .company_proposal_contracts import DeterministicProposalRequest
from .company_proposal_records import validate_proposal, successful_invocation
from .contracts import canonical, iso, parse_time, utcnow, RickyError
from .company_draft_save_contracts import (SCHEMA, CLASSIFICATION, MAPPING_VERSION, COMMANDS, application_id,
    derive, binding, check_binding, refuse)

DOCTYPE = 'Cipher Ricky Draft Save'
_active_insert = ContextVar('cipher_company_draft_save_insert', default=None)


def has_permission(doc=None, user=None, ptype=None):
    return False


def query(user=None):
    return '1=0'


def _conversion_originals(service, run, originals, *, lock=False):
    """Authorize manifest-pinned canonical conversions without expanding heads.

    Stage B can pin a definition inside its immutable base snapshot without a
    separate conversion entry. This ephemeral Stage C closure never rewrites
    the retained preparation manifest or its successful output.
    """
    if run['request']['action']!='aec.estimate.draft': return originals
    values=dict(originals)
    revision=values['estimate','revision',run['request']['arguments']['base_revision_id']]
    snapshot=values['estimate','snapshot',revision['calculation_snapshot']]
    definitions=snapshot['inputs']['unit_manifest']['unit_conversions']
    if len(definitions)>64: refuse('The original conversion union exceeds the canonical write bound.')
    reader=service.backend.reader(decode_run_authority(run),DeterministicProposalRequest.from_value(run['request']),lock=lock,execution=False)
    actor=reader.actor(reader.context,'estimate.read')
    for definition in definitions:
        value=reader.record(reader.context,'conversion',definition['id'],actor)
        key='estimate','conversion',definition['id']
        if (value.get('id')!=definition['id'] or value.get('scope_type')!='Company' or value.get('project') is not None
                or value.get('company')!=run['company'] or value.get('definition')!=definition
                or key in values and canonical(values[key])!=canonical(value)):
            refuse('The original canonical conversion definition or scope changed.', 'source_integrity')
        values[key]=value
    return values


def _load_records(company, proposal_id, *, lock=False, service=None):
    from .company_proposal_service import build_service
    service = service or build_service()
    proposal = service.store.get('proposal', proposal_id)
    if lock:
        service.backend.lock_original(service.store.get('run',proposal['run_id']),execution=False)
    run = service._load(company, proposal['run_id'], lock=lock)
    if lock: proposal = service.store.get('proposal', proposal_id, lock=True)
    service._check(run, lock=lock)
    validate_proposal(proposal, run, service.store)
    return service, run, proposal


def _closure_plan(run, actor, *, saved_core=None):
    """Discover Stage C's pinned conversions and retained saved graph only.

    This private closure adds no Stage B manifest entries or current heads.
    Canonical conversion citations can carry dependencies absent from a
    snapshot's embedded definition, so read their exact records before masters.
    """
    from cipher_aec.estimating.lockplan import Discovery
    from cipher_aec.commercial import sources

    class DraftSaveDiscovery(Discovery):
        def value(self, domain, kind, value, *, current_bindings=False):
            key = domain, kind, value['id'], current_bindings if kind == 'revision' else False
            if key in self.visited: return
            super().value(domain,kind,value,current_bindings=current_bindings)
            if domain=='estimate' and kind=='snapshot':
                self.citations(value['inputs'].get('basis_citations',[]))
            manifest = value.get('unit_manifest') or value.get('inputs',{}).get('unit_manifest') or {}
            definitions = manifest.get('unit_conversions',[])
            if len(definitions)>64: refuse('The original conversion union exceeds the canonical write bound.')
            for definition in definitions:
                record=self.record('estimate','conversion',definition['id'])
                if record.get('definition')!=definition:
                    refuse('The pinned canonical conversion definition changed.', 'source_integrity')

    discovery=DraftSaveDiscovery(run['company'],actor,lock=True)
    plans=[]
    def commercial_revision(name):
        value=sources.revision_record(run['company'],name,actor,lock=True)
        plans.append(sources.revision_plan(run['company'],name,actor,lock=True))
        reference=value['composition'].get('estimate_reference')
        if reference: discovery.record('estimate','acceptance',reference['acceptance_id'])
    for row in run['original_manifest']['records']:
        if row['domain']=='commercial': commercial_revision(row['id'])
        else: discovery.record(row['domain'],row['kind'],row['id'])
    if saved_core is not None:
        if saved_core['action']=='aec.scope.draft': commercial_revision(saved_core['saved_revision_id'])
        elif saved_core['action']=='aec.estimate.draft': discovery.record('estimate','revision',saved_core['saved_revision_id'])
        else: refuse('Unsupported draft-save action.', 'draft_save_integrity')
    return sources.merge(discovery.finish(),*plans)


@contextmanager
def _original_scope(service, run, *, lock=False, saved_core=None):
    if not lock:
        originals=service.backend.authorize_result(run,execution=False,lock=False)
        yield _conversion_originals(service,run,originals)
        return
    from cipher_aec.estimating.scopes import activate
    from .company_proposal_contracts import validate_manifest,validate_resource_plan
    authority=decode_run_authority(run)
    request=DeterministicProposalRequest.from_value(run['request'])
    validate_manifest(run['original_manifest'],request);validate_resource_plan(run['resource_plan'])
    if digest(run['original_manifest'])!=run['original_manifest_digest'] or digest(run['resource_plan'])!=run['resource_plan_digest']:
        refuse('Original proposal source bindings changed.', 'source_integrity')
    actor=service.backend.authorize(authority,execution=False,lock=True)
    with activate('Company',run['company'],None):
        extra=_closure_plan(run,actor,saved_core=saved_core)
        with service.backend.source_scope(authority,request,run['original_manifest'],lock=True,execution=False,_extra_plan=extra):
            reader=service.backend.reader(authority,request,lock=True,execution=False)
            originals=reader.verify_original(run['original_manifest'])
            yield _conversion_originals(service,run,originals,lock=True)


def load(company, proposal_id, *, lock=False, service=None):
    service,run,proposal=_load_records(company,proposal_id,lock=lock,service=service)
    with _original_scope(service,run,lock=lock) as originals:
        # Every public Source field remains bound at this semantic boundary.
        successful_invocation(service.store,run,originals=originals,require_citations=True)
        return service,run,proposal,originals


def _application(proposal_id, *, lock=False):
    import frappe
    fields=('name','company','scope_type','project','requested_by','person','source_proposal','run','step','invocation','receipt','saved_doctype','saved_revision')
    rows = frappe.db.sql('SELECT data_json,record_digest,'+','.join(fields)+' FROM `tabCipher Ricky Draft Save` WHERE name=%s' + (' FOR UPDATE' if lock else ''),
        (application_id(proposal_id),))
    if not rows: return None
    record = json.loads(rows[0][0])
    if type(record) is not dict or set(record) != {'core','receipt_result_hash'} or digest(record) != rows[0][1]:
        refuse('The immutable draft-save record cannot be verified.', 'draft_save_integrity')
    core = record['core']
    if type(core) is not dict or core.get('schema')!=SCHEMA or core.get('id') != application_id(proposal_id) or core.get('proposal_id') != proposal_id or core.get('core_digest') != digest({k:v for k,v in core.items() if k!='core_digest'}):
        refuse('The draft-save core binding changed.', 'draft_save_integrity')
    headers={'name':core['id'],'company':core['company'],'scope_type':'Company','project':None,'requested_by':core['user'],'person':core['person'],
        'source_proposal':core['proposal_id'],'run':core['run_id'],'step':core['step_id'],'invocation':core['invocation_id'],
        'receipt':core['receipt_id'],'saved_doctype':core['saved_doctype'],'saved_revision':core['saved_revision_id']}
    if any(actual!=headers[field] for field,actual in zip(fields,rows[0][2:])) or len(rows[0])!=len(fields)+2:
        refuse('Application native headers differ from canonical JSON.', 'draft_save_integrity')
    return record


def _receipt(record):
    import frappe
    core = record['core']
    rows = frappe.db.sql('SELECT person,operation_id,company,scope_type,project,command,request_hash,result_json,result_hash,state FROM `tabCipher Command Receipt` WHERE name=%s', (core['receipt_id'],), as_dict=True)
    if len(rows)!=1: refuse('The original draft-save receipt is unavailable.', 'draft_save_integrity')
    row = rows[0]; result = json.loads(row.result_json)
    if (row.person!=core['person'] or row.operation_id!=core['operation_id'] or row.company!=core['company'] or row.scope_type!='Company'
            or row.project not in (None,'') or row.command!=core['command'] or row.state!='Succeeded'
            or digest(result)!=row.result_hash or row.result_hash!=record['receipt_result_hash'] or result.get('application')!=core):
        refuse('The original draft-save receipt has different linkage.', 'draft_save_integrity')
    return row, result


@contextmanager
def _saved_scope(core, actor, lock):
    if core['action']!='aec.estimate.draft':
        yield
        return
    from cipher_aec.estimating.scopes import activate
    from cipher_aec.estimating.lockplan import prepared,result_plan
    with activate('Company',core['company'],None):
        if lock:
            plan=result_plan(core['company'],actor,{'revision':{'id':core['saved_revision_id']}},lock=True)
            with prepared(plan,actor,core['company']): yield
        else: yield


def _saved_revision(core, actor, *, lock=False, saved=None, current=False):
    with _saved_scope(core,actor,lock):
        if core['action']=='aec.scope.draft':
            from cipher_aec.commercial.service import _read
            revision = _read('revision',core['saved_revision_id'],core['company'],actor,lock=lock)[1]
            if revision['proposal']!=core['target_id'] or revision['predecessor']!=core['base_revision_id']:
                refuse('The saved commercial successor has different ownership.', 'draft_save_integrity')
        elif core['action']=='aec.estimate.draft':
            from cipher_aec.estimating.scopes import activate
            from cipher_aec.estimating.service import _scoped_original
            with activate('Company',core['company'],None):
                revision = _scoped_original('revision',core['saved_revision_id'],core['company'],None,actor,lock=lock)
            if revision['estimate']!=core['target_id'] or revision['predecessor']!=core['base_revision_id']:
                refuse('The saved estimate successor has different ownership.', 'draft_save_integrity')
        else: refuse('Unsupported draft-save action.', 'draft_save_integrity')
        if digest(revision)!=core['saved_revision_digest']: refuse('The saved immutable revision changed.', 'draft_save_integrity')
        if saved is not None:
            if saved.get('revision')!=revision: refuse('The receipt revision differs from its canonical immutable row.', 'draft_save_integrity')
            if core['action']=='aec.scope.draft':
                parent=_read('proposal',core['target_id'],core['company'],actor,lock=lock)[1]
                original=saved.get('proposal',{})
                stable=('id','company','pursuit','quotation','party_type','party_id')
            else:
                from cipher_aec.estimating.service import _scoped
                with activate('Company',core['company'],None):
                    snapshot=_scoped_original('snapshot',revision['calculation_snapshot'],core['company'],None,actor,lock=lock)
                    parent=_scoped('estimate',core['target_id'],core['company'],None,actor,lock=lock)
                if saved.get('calculation')!=snapshot: refuse('The saved calculation differs from its actual immutable snapshot.', 'draft_save_integrity')
                original=saved.get('estimate',{})
                stable=('id','scope_type','project','company','pursuit_id','currency','pricing_date')
            if any(key not in original or original[key]!=parent[key] for key in stable) or current and original!=parent:
                refuse('The saved target identity or new head differs from its canonical parent.', 'draft_save_integrity')
        return revision


def authorize_receipt(actor, company, result, *, command=None, lock=False):
    """Historical authorization; no current head, deadline, write or SID gate."""
    from cipher_aec.governance.context import require_company
    if type(result) is not dict or set(result)!={'application','saved'}: refuse('Invalid draft-save receipt.', 'draft_save_integrity')
    core = result['application']
    if (type(core) is not dict or core.get('company')!=company or core.get('user')!=actor.user or core.get('person')!=actor.person_id
            or core.get('command')!=command or core.get('action') not in COMMANDS):
        refuse('This draft save is not available.', 'not_found', 404)
    require_company(company,ability=COMMANDS[core['action']][2]+'.read',actor=actor,lock=lock)
    service,run,proposal = _load_records(company,core['proposal_id'],lock=lock)
    record = _application(proposal['id'],lock=lock)
    if record is None or record['core']!=core: refuse('The draft-save application is unavailable.', 'draft_save_integrity')
    row, retained = _receipt(record)
    # Keep original and saved readers inside one complete admission. Independent
    # admissions would restart UOM locking after original Currency/native locks.
    with _original_scope(service,run,lock=lock,saved_core=core) as originals:
        successful_invocation(service.store,run,originals=originals,require_citations=True)
        payload = derive(proposal,run,originals)
        context = DraftSaveContext(company,proposal['id'],binding(proposal,payload),service=service)
        context.run,context.proposal,context.payload = run,proposal,payload
        expected_hash = digest({'scope_type':'Company','command':command,'company':company,'project':None,'payload':context.envelope(payload)})
        if row.request_hash!=expected_hash or retained!=result: refuse('The exact draft-save request/result changed.', 'draft_save_integrity')
        context.verify_core(core,actor,result['saved'])
        _saved_revision(core,actor,lock=lock,saved=result['saved'])


def authorize_history(actor, company, identifier):
    import frappe
    row = frappe.db.get_value(DOCTYPE,identifier,['source_proposal','company'],as_dict=True)
    if not row or row.company!=company: refuse('This draft save is not available.', 'not_found',404)
    record = _application(row.source_proposal)
    if record is None or record['core']['id']!=identifier: refuse('The history application changed.', 'draft_save_integrity')
    _,result = _receipt(record)
    authorize_receipt(actor,company,result,command=record['core']['command'])


class DraftSaveContext:
    """Concrete server-owned lifecycle; RPC cannot supply a context or callback."""
    def __init__(self, company, proposal_id, reviewed, *, service=None, clock=utcnow):
        from .company_proposal_service import build_service
        self.company,self.proposal_id,self.reviewed = company,proposal_id,deepcopy(reviewed)
        self.service,self.clock = service or build_service(),clock
        self.run=self.proposal=self.payload=None
        self._prelocked=None
        self._reserved=None

    def prepare(self):
        service,run,proposal,originals = load(self.company,self.proposal_id,service=self.service)
        self.run,self.proposal = run,proposal
        self.payload = derive(proposal,run,originals)
        check_binding(self.reviewed,proposal,self.payload)
        return self

    @property
    def spec(self): return COMMANDS[self.proposal['action']]

    def envelope(self, payload):
        return {'reviewed':deepcopy(self.reviewed),'canonical_command':self.spec[1],'canonical_payload':deepcopy(payload)}

    def command(self, canonical_command, ability, payload):
        if canonical_command!=self.spec[1] or ability!=self.spec[2]+'.write' or payload!=self.payload:
            refuse('The canonical writer differs from the reviewed draft save.')
        return self.spec[0], self.envelope(payload), self.spec[2]+'.read'

    def prelock(self, actor):
        import frappe
        authority = decode_run_authority(self.run)
        if authority.user!=actor.user or authority.person!=actor.person_id or authority.company!=self.company:
            refuse('This suggestion belongs to another original identity.', 'not_found',404)
        # No expiry predicate: replay never requires the original session to live.
        frappe.db.sql('SELECT sessiondata FROM `tabSessions` WHERE user=%s AND SHA2(sid,256)=%s FOR UPDATE',
            (authority.user,authority.session_reference))
        self._prelocked = (actor.user,actor.person_id,authority.session_reference)

    def authority(self, actor):
        import frappe
        from cipher_aec.governance.context import require_company,require_session_authority,company_authority_fingerprint
        authority = decode_run_authority(self.run)
        if self._prelocked!=(actor.user,actor.person_id,authority.session_reference): refuse('The original Session must precede Company locking.')
        sid = getattr(frappe.session,'sid',None)
        if (frappe.session.user!=actor.user or not sid or sid=='Guest' or hashlib.sha256(sid.encode()).hexdigest()!=authority.session_reference):
            refuse('Save from the original active author session.', 'session_revoked',403)
        require_session_authority(actor,authority.session_reference,lock=False)
        require_company(self.company,ability='ricky.run',actor=actor,lock=True)
        for ability in (self.spec[2]+'.read',self.spec[2]+'.write'):
            require_company(self.company,ability=ability,actor=actor,lock=True)
        if company_authority_fingerprint(actor,self.company,lock=True)!=authority.authority_version:
            refuse('Company authority changed since preparation.', 'stale_authority',403)
        if self.run['status']!='waiting-for-review' or self.run['cancel_requested'] or self.clock()>=parse_time(self.proposal['expires_at']):
            refuse('The completed suggestion is cancelled, unavailable or expired.', 'draft_save_expired')

    @contextmanager
    def new_effect(self, actor):
        from cipher_aec.estimating.scopes import activate
        from cipher_aec.commercial.sources import merge
        self.authority(actor)
        preview = self.service.store.get('run',self.run['id'])
        self.service.backend.lock_original(preview,execution=False)
        self.run = self.service._load(self.company,preview['id'],lock=True)
        self.proposal = self.service.store.get('proposal',self.proposal_id,lock=True)
        if self.proposal['run_id']!=self.run['id']: refuse('The locked suggestion changed Run.')
        validate_proposal(self.proposal,self.run,self.service.store)
        if _application(self.proposal_id,lock=True) is not None: refuse('This suggestion already has an immutable draft save.', 'draft_already_saved')
        self.authority(actor)
        request=DeterministicProposalRequest.from_value(self.run['request'])
        with activate('Company',self.company,None):
            if self.spec[2]=='commercial':
                from cipher_aec.commercial import service,sources
                party,refs=service._source_plan('proposal',self.payload['proposal_id'],self.company)
                extra=sources.plan(self.payload['composition'],self.company,actor,lock=True)
                # Include the writer's own native masters before proposal admission.
                units=[row['unit_id'] for row in self.payload['composition']['price_lines']]
                extra=sources.merge(extra,{'unit_ids':sorted(set(units)),'currencies':[self.payload['composition']['currency']],
                    'native_refs':[{'doctype':d,'name':n} for d,n in sorted(set(refs)|{party,('Price List',self.payload['composition']['price_list'])}|{('Item',row['item_code']) for row in self.payload['composition']['price_lines'] if row['item_code']})], 'generated_sources':[]})
            else:
                from cipher_aec.estimating.lockplan import command_plan
                extra=command_plan(self.company,actor,self.spec[1],self.payload)
            extra=merge(extra,_closure_plan(self.run,actor))
            with self.service.backend.source_scope(decode_run_authority(self.run),request,self.run['original_manifest'],
                    lock=True,execution=False,expected_plan=self.run['resource_plan'],_extra_plan=extra):
                reader=self.service.backend.reader(decode_run_authority(self.run),request,lock=True,execution=True)
                originals=reader.verify_original(self.run['original_manifest'])
                reader.prepare_selected()
                if canonical(reader.manifest(action_complete=True))!=canonical(self.run['original_manifest']):
                    refuse('A current selected source or working head changed.', 'stale_source',412)
                originals=_conversion_originals(self.service,self.run,originals,lock=True)
                current=derive(self.proposal,self.run,originals)
                check_binding(self.reviewed,self.proposal,current)
                if current!=self.payload: refuse('The locked canonical payload changed.')
                self._terminal_bytes=canonical(self.run)
                yield

    def verify_core(self,core,actor,saved):
        proposal,run=self.proposal,self.run
        invocation=successful_invocation(self.service.store,run)
        revision=saved['revision']
        target=self.payload['proposal_id' if self.spec[2]=='commercial' else 'estimate_id']
        base = run['request']['arguments']['proposal_revision_id' if self.spec[2]=='commercial' else 'base_revision_id']
        expected={'schema':SCHEMA,'id':application_id(proposal['id']),'scope_type':'Company','project':None,'company':self.company,
            'user':actor.user,'person':actor.person_id,'proposal_id':proposal['id'],'proposal_version':proposal['version'],
            'proposal_digest':proposal['content_digest'],'run_id':run['id'],'step_id':invocation['step_id'],'invocation_id':invocation['id'],
            'preparation_digest':invocation['output_digest'],'manifest_digest':run['original_manifest_digest'],
            'action':proposal['action'],'classification':CLASSIFICATION,'mapping_version':MAPPING_VERSION,'payload_digest':digest(self.payload),
            'command':self.spec[0],'canonical_command':self.spec[1],
            'target_doctype':'Cipher Proposal' if self.spec[2]=='commercial' else 'Cipher Estimate','target_id':target,
            'base_revision_id':base,'saved_doctype':'Cipher Proposal Revision' if self.spec[2]=='commercial' else 'Cipher Estimate Revision',
            'saved_revision_id':revision['id'],'saved_revision_digest':digest(revision)}
        if set(core)!=set(expected)|{'created_at','operation_id','receipt_id','core_digest'} or any(type(core[k]) is not type(v) or core[k]!=v for k,v in expected.items()):
            refuse('The application core differs from its actual canonical preparation/effect.', 'draft_save_integrity')
        if core['receipt_id']!=digest({'person':actor.person_id,'operation_id':core['operation_id']}) or core['core_digest']!=digest({k:v for k,v in core.items() if k!='core_digest'}):
            refuse('The application receipt identity/core hash changed.', 'draft_save_integrity')
        parse_time(core['created_at'])
        if revision.get('predecessor')!=base or revision.get('proposal' if self.spec[2]=='commercial' else 'estimate')!=target:
            refuse('The canonical revision is not the original target successor.', 'draft_save_integrity')
        if self.spec[2]=='commercial':
            if revision['composition']!=self.payload['composition']: refuse('Saved scope composition differs from the authorized mapping.', 'draft_save_integrity')
        else:
            inputs=saved['calculation']['inputs']
            if revision['calculation_snapshot']!=saved['calculation']['id'] or any(inputs[k]!=self.payload[k] for k in ('lines','adjustments','basis_description')):
                refuse('Saved estimate inputs differ from the authorized mapping.', 'draft_save_integrity')

    def reserve(self,actor,saved,operation_id,receipt_id):
        self.authority(actor)
        current=self.service.store.get('run',self.run['id'],lock=True)
        if canonical(current)!=self._terminal_bytes: refuse('The finalized preparation changed during save.')
        self.run=current
        request=DeterministicProposalRequest.from_value(self.run['request'])
        reader=self.service.backend.reader(decode_run_authority(self.run),request,lock=True,execution=False)
        originals=reader.verify_original(self.run['original_manifest'])
        originals=_conversion_originals(self.service,self.run,originals,lock=True)
        successful_invocation(self.service.store,self.run,originals=originals,require_citations=True)
        check_binding(self.reviewed,self.proposal,derive(self.proposal,self.run,originals))
        revision=saved['revision']
        core={'created_at':iso(self.clock()),'operation_id':operation_id,'receipt_id':receipt_id}
        # Build only known canonical fields; verify_core independently checks them.
        inv=successful_invocation(self.service.store,self.run)
        core.update(schema=SCHEMA,id=application_id(self.proposal_id),scope_type='Company',project=None,company=self.company,
            user=actor.user,person=actor.person_id,proposal_id=self.proposal_id,proposal_version=self.proposal['version'],
            proposal_digest=self.proposal['content_digest'],run_id=self.run['id'],step_id=inv['step_id'],invocation_id=inv['id'],
            preparation_digest=inv['output_digest'],manifest_digest=self.run['original_manifest_digest'],action=self.proposal['action'],
            classification=CLASSIFICATION,mapping_version=MAPPING_VERSION,payload_digest=digest(self.payload),command=self.spec[0],canonical_command=self.spec[1],
            target_doctype='Cipher Proposal' if self.spec[2]=='commercial' else 'Cipher Estimate',target_id=self.payload['proposal_id' if self.spec[2]=='commercial' else 'estimate_id'],
            base_revision_id=self.run['request']['arguments']['proposal_revision_id' if self.spec[2]=='commercial' else 'base_revision_id'],
            saved_doctype='Cipher Proposal Revision' if self.spec[2]=='commercial' else 'Cipher Estimate Revision',saved_revision_id=revision['id'],saved_revision_digest=digest(revision))
        core['core_digest']=digest(core)
        self.verify_core(core,actor,saved)
        _saved_revision(core,actor,lock=True,saved=saved,current=True)
        self._reserved={'application':core,'saved':deepcopy(saved)}
        return deepcopy(self._reserved)

    def persist(self,actor,result):
        import frappe
        from cipher_aec.governance.history import append_company_event
        self.authority(actor)
        if result!=self._reserved: refuse('The reserved canonical result changed.', 'draft_save_integrity')
        record={'core':result['application'],'receipt_result_hash':digest(result)}
        _,actual=_receipt(record)
        if actual!=result: refuse('The newly inserted receipt differs from the actual result.', 'draft_save_integrity')
        token=_active_insert.set((self,actor,deepcopy(record)))
        try:
            core=record['core']
            doc=frappe.get_doc({'doctype':DOCTYPE,'name':core['id'],'company':self.company,'scope_type':'Company','project':None,
                'requested_by':actor.user,'person':actor.person_id,'source_proposal':self.proposal_id,'run':core['run_id'],
                'step':core['step_id'],'invocation':core['invocation_id'],'receipt':core['receipt_id'],
                'saved_doctype':core['saved_doctype'],'saved_revision':core['saved_revision_id'],'data_json':canonical_json(record),'record_digest':digest(record)})
            doc.insert(ignore_permissions=True,set_name=core['id'])
        finally:_active_insert.reset(token)
        append_company_event(actor=actor,company=self.company,event='ricky.company.proposal.draft-saved',subject_type=DOCTYPE,
            subject_id=core['id'],operation_id=core['operation_id'],details={'action':core['action'],'classification':CLASSIFICATION,
            'target_type':core['target_doctype'],'target_id':core['target_id'],'revision_id':core['saved_revision_id'],'application_digest':core['core_digest']})
        self.authority(actor)
        if canonical(self.service.store.get('run',self.run['id'],lock=True))!=self._terminal_bytes:
            refuse('The finalized preparation changed before completion.')


def validate_document(doc):
    from cipher_aec.governance.context import require_trusted_write
    require_trusted_write()
    active=_active_insert.get()
    if not doc.is_new() or active is None: refuse('Draft-save application records are insert-only.', 'immutable_record')
    context,actor,expected=active
    context.authority(actor)
    record=json.loads(doc.data_json)
    if record!=expected or doc.record_digest!=digest(record): refuse('Application data differs from its live canonical boundary.', 'draft_save_integrity')
    core=record['core']
    headers={'name':core['id'],'company':core['company'],'scope_type':'Company','project':None,'requested_by':core['user'],'person':core['person'],
        'source_proposal':core['proposal_id'],'run':core['run_id'],'step':core['step_id'],'invocation':core['invocation_id'],
        'receipt':core['receipt_id'],'saved_doctype':core['saved_doctype'],'saved_revision':core['saved_revision_id']}
    if any(doc.get(k)!=v for k,v in headers.items()): refuse('Application native headers differ from canonical JSON.', 'draft_save_integrity')
    _,result=_receipt(record)
    context.verify_core(core,actor,result['saved'])
    _saved_revision(core,actor,lock=True,saved=result['saved'],current=True)


def draft_save_subject(company, proposal_id):
    from cipher_aec.governance.context import current_actor
    service,run,proposal,originals=load(company,proposal_id)
    payload=derive(proposal,run,originals); reviewed=binding(proposal,payload)
    context=DraftSaveContext(company,proposal_id,reviewed,service=service).prepare()
    record=_application(proposal_id)
    result=None; reason=None
    if record is not None:
        _,result=_receipt(record); authorize_receipt(current_actor(),company,result,command=context.spec[0])
        reason={'code':'draft_already_saved','message':'This suggestion already has a saved canonical draft.'}
    else:
        try:
            import frappe
            actor=current_actor()
            frappe.db.sql('SELECT name FROM `tabCipher Person` WHERE name=%s FOR UPDATE',(actor.person_id,))
            actor=current_actor(lock=True);context.prelock(actor)
            with context.new_effect(actor): pass
        except (DomainError,RickyError) as error:
            reason={'code':error.code,'message':error.message}
    return {'proposal_id':proposal_id,'proposal_version':proposal['version'],'proposal_digest':proposal['content_digest'],
        'action':proposal['action'],'mapping_version':MAPPING_VERSION,'payload':payload,'payload_digest':digest(payload),'expires_at':proposal['expires_at'],
        'eligible':reason is None,'reason':reason,'application':record['core'] if record else None,'saved':result['saved'] if result else None}


def save_draft(company, reviewed, operation_id):
    context=DraftSaveContext(company,reviewed['proposal_id'],reviewed).prepare()
    if context.spec[2]=='commercial':
        from cipher_aec.commercial.service import save_proposal_revision
        return save_proposal_revision(company=company,operation_id=operation_id,**context.payload,_draft_save=context)
    from cipher_aec.estimating.company_service import calculate_revision
    return calculate_revision(company=company,operation_id=operation_id,**context.payload,_draft_save=context)

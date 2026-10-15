"""Audited RFI source controls over the existing native field operations.

Schema78 is explicitly deferred until the genuine library76/77 catalog exists.
The module has no import-time SQL/catalog registration or UI authority imports.
"""
from __future__ import annotations

import json
import re
from contextlib import contextmanager

from ..core.approvals import ApprovalError, StaleApprovalError, material_hash, material_part
from ..core.db import SCHEMA_CATALOG, catalog_checksum, register_schema_version
from ..core.ids import canonical_json, hash_json, new_id, parse_iso, utcnow, utcnow_iso
from .drawing_sources import consumed_approval_proof, issued_drawing_proof
from .owned_sources import OwnedSourceError, _event_ref, _intact, _near_time, _one, _payload, _same, document_rights_proof, owned_revision_proof

PLUGIN_NAME='rfi_controls'
SCHEMA_NAME='rfi_sources_and_review_contexts'
DEFER_SCHEMA_REGISTRATION=True
RESPONSE='field.respond_rfi'
DISTRIBUTE='field.distribute_rfi'
OPERATIONS=(RESPONSE,DISTRIBUTE)
SOURCE_KIND='practice-owned-rfi-citations/1'
RECIPIENTS=('engineer@synthetic-rfi.invalid','owner@synthetic-rfi.invalid','project-team@synthetic-rfi.invalid')
_SPECS={
    'sources':('rfi_id TEXT NOT NULL UNIQUE REFERENCES field_rfis(id)',('rfi_id',),''),
    'response_revisions':('rfi_id TEXT NOT NULL REFERENCES field_rfis(id), native_version INTEGER NOT NULL CHECK(native_version>1)',('rfi_id','native_version'),', UNIQUE(rfi_id,native_version)'),
    'distribution_revisions':('rfi_id TEXT NOT NULL REFERENCES field_rfis(id), native_version INTEGER NOT NULL CHECK(native_version>1)',('rfi_id','native_version'),', UNIQUE(rfi_id,native_version)'),
    'approval_sources':("rfi_id TEXT NOT NULL REFERENCES field_rfis(id), approval_id TEXT NOT NULL UNIQUE REFERENCES approvals(id), operation TEXT NOT NULL CHECK(operation IN ('field.respond_rfi','field.distribute_rfi'))",('rfi_id','approval_id','operation'),'')
}
SCHEMA_STATEMENTS=[]
for _kind,(_fields,_keys,_unique) in _SPECS.items():
    _checks=', '.join(f"CHECK(json_extract(body_json,'$.{key}') IS {key})" for key in ('id','project_id',*_keys))
    SCHEMA_STATEMENTS.append(f'CREATE TABLE rfi_{_kind} (id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id), {_fields}, body_json TEXT NOT NULL CHECK(json_valid(body_json)), row_hash TEXT NOT NULL, {_checks}{_unique})')
for _kind in _SPECS:
    _table=f'rfi_{_kind}'
    SCHEMA_STATEMENTS.extend((
        f"CREATE TRIGGER {_table}_no_update BEFORE UPDATE ON {_table} BEGIN SELECT RAISE(ABORT,'RFI originals are immutable'); END",
        f"CREATE TRIGGER {_table}_no_delete BEFORE DELETE ON {_table} BEGIN SELECT RAISE(ABORT,'RFI history is append-only'); END",
        f"CREATE TRIGGER {_table}_birth BEFORE INSERT ON {_table} BEGIN SELECT CASE WHEN EXISTS(SELECT 1 FROM {_table} WHERE id=NEW.id) THEN RAISE(ABORT,'RFI original cannot be replaced') END; SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM audit_log WHERE action='rfi.{_kind}_recorded' AND entity_type='{_table}' AND entity_id=NEW.id AND json_extract(payload_json,'$.rowHash')=NEW.row_hash) THEN RAISE(ABORT,'RFI original needs its audited birth') END; END",
    ))


class RFIError(ApprovalError):
    pass


def register_rfi_controls_schema():
    existing=next((e for e in SCHEMA_CATALOG if e[1]==SCHEMA_NAME),None)
    if existing is not None:
        if existing[0]!=78:raise RFIError('RFI source controls must retain schema78')
        return register_schema_version(SCHEMA_NAME,SCHEMA_STATEMENTS)
    if (len(SCHEMA_CATALOG)!=77 or SCHEMA_CATALOG[-1][1]!='library_practice_action_receipts'
            or SCHEMA_CATALOG[75][1]!='library_authored_text_and_reference_adoptions'):
        raise RFIError('RFI sources require the genuine unchanged77-entry library catalog')
    return register_schema_version(SCHEMA_NAME,SCHEMA_STATEMENTS)


def require_rfi_duty(cipher,actor,project_id,duty):
    """Actual own membership permits drafts; own project PM grants permit decisions."""
    if duty not in ('staff','pm'):raise RFIError('The requested RFI duty is unsupported')
    cipher.db.require_practice_mode()
    people=cipher.plugin('people');people._require_intact();policy=people.current_policy()
    if not policy or not policy['intact'] or not policy['enforce'] or not policy['segregate'] or policy['solo_owner_self_approval']:
        raise RFIError('RFI work requires intact enforcing segregated project people')
    person=people._person_row(actor)
    if (not person or person['kind']!='person' or person['status']!='active' or person.get('external')
            or not people._membership(person['id'],project_id)):
        raise RFIError('RFI work requires an active internal person with their own project membership')
    grants=[g for g in people._live_grants(person['id'],people._today())
            if g['role']=='pm' and g['scope']=='project' and g['project_id']==project_id]
    if duty=='pm' and not grants:raise RFIError('This RFI act requires the person’s own current project PM grant')
    return {'personId':person['id'],'login':person['login'],'projectId':project_id,'role':duty,
            'membershipId':people._membership(person['id'],project_id)['id'],'grantIds':sorted(g['id'] for g in grants) if duty=='pm' else [],
            'peoplePolicy':people._binding()}


def _body(body,fields):
    if type(body) is not dict or set(body)!=set(fields):raise RFIError('The RFI body must contain exactly '+', '.join(fields))
    return body


def _text(value,label,limit):
    if not isinstance(value,str) or not value.strip() or len(value)>limit:raise RFIError(f'{label} must be nonempty text within {limit} characters')
    return value.strip()


def _citations(value,label):
    if type(value) is not list or not 1<=len(value)<=12:raise RFIError(f'{label} requires one to twelve exact citations')
    cleaned=[_text(v,label,128) for v in value]
    if len(set(cleaned))!=len(cleaned):raise RFIError(f'{label} contains duplicate citations')
    return cleaned


class Plugin:
    GOVERNOR=True

    def __init__(self,cipher):
        self.c=cipher;self.db=cipher.db;self.audit=cipher.audit;self.approvals=cipher.approvals

    def _schema_installed(self):
        entry=self.db.one('SELECT version,statement_count,checksum FROM schema_version WHERE name=?',(SCHEMA_NAME,))
        tables=self.db.query("SELECT name FROM sqlite_master WHERE type='table' AND name IN ('rfi_sources','rfi_response_revisions','rfi_distribution_revisions','rfi_approval_sources')")
        births=self.db.scalar("SELECT COUNT(*) FROM audit_log WHERE action IN ('rfi.sources_recorded','rfi.response_revisions_recorded','rfi.distribution_revisions_recorded','rfi.approval_sources_recorded')")
        if entry is None:
            receipts=(self.db.one("SELECT version FROM schema_version WHERE name='rfi_practice_action_receipts'") or
                      self.db.one("SELECT name FROM sqlite_master WHERE type='table' AND name='rfi_action_receipts'") or
                      self.db.one("SELECT seq FROM audit_log WHERE action='rfi.practice_action_recorded' LIMIT 1"))
            if tables or births or receipts:raise RFIError('RFI source or receipt history exists without its admitted source schema')
            return False
        physical=[r['version'] for r in self.db.query('SELECT version FROM schema_version WHERE version<=? ORDER BY version',(entry['version'],))]
        if (entry['version']<1 or entry['version']!=len(physical)
                or any(value!=index for index,value in enumerate(physical,1)) or len(tables)!=4
                or entry['statement_count']!=len(SCHEMA_STATEMENTS) or entry['checksum']!=catalog_checksum(SCHEMA_STATEMENTS)):
            raise RFIError('Admitted RFI source tables or original prefix differ from their admission')
        return True

    def is_modern(self,rfi_id):
        if not self._schema_installed():return False
        return bool(self.db.one('SELECT id FROM rfi_sources WHERE rfi_id=?',(rfi_id,)) or self.db.one("SELECT seq FROM audit_log WHERE action='rfi.sources_recorded' AND json_extract(payload_json,'$.rfiId')=?",(rfi_id,)))

    def source_scope(self,rfi_id):
        row=self.db.one('SELECT project_id FROM field_rfis WHERE id=?',(rfi_id,))
        if row is None and self.db.one("SELECT name FROM sqlite_master WHERE type='table' AND name='rfi_sources'"):
            row=self.db.one('SELECT project_id FROM rfi_sources WHERE rfi_id=?',(rfi_id,))
        if row is None:
            # Scope-only metadata lets an own-project caller reach the original
            # integrity hold after deletion, without loading source bodies first.
            row=self.db.one("SELECT json_extract(payload_json,'$.projectId') AS project_id FROM audit_log WHERE action='rfi.sources_recorded' AND json_extract(payload_json,'$.rfiId')=? ORDER BY seq LIMIT 1",(rfi_id,))
        if row is None or not row['project_id']:raise RFIError('The RFI is unavailable')
        return {'projectId':row['project_id']}

    def approval_scope(self,approval_id):
        row=self.db.one("SELECT r.project_id FROM approvals a JOIN field_rfis r ON r.id=a.subject_id WHERE a.id=? AND a.subject_type='field_rfi' AND a.operation IN ('field.respond_rfi','field.distribute_rfi')",(approval_id,))
        if row is None and self.db.one("SELECT name FROM sqlite_master WHERE type='table' AND name='rfi_approval_sources'"):
            row=self.db.one('SELECT project_id FROM rfi_approval_sources WHERE approval_id=?',(approval_id,))
        if row is None:
            original=self.db.one("SELECT json_extract(payload_json,'$.subject.id') AS rfi_id FROM audit_log WHERE action='approval.requested' AND entity_type='approval' AND entity_id=? AND json_extract(payload_json,'$.subject.type')='field_rfi' AND json_extract(payload_json,'$.operation') IN ('field.respond_rfi','field.distribute_rfi') ORDER BY seq LIMIT 1",(approval_id,))
            if original:return self.source_scope(original['rfi_id'])
        if row is None or not row['project_id']:raise RFIError('The RFI approval is unavailable')
        return {'projectId':row['project_id']}

    def _person(self,actor,project_id,duty):return require_rfi_duty(self.c,actor,project_id,duty)

    def _historical_person(self,recorded,event,project_id,duty):
        """Prove actual original owned duty without requiring a former staff member today."""
        people=self.c.plugin('people');people._require_intact()
        person=people._person_by_id(recorded.get('personId'))
        if (person is None or person['login']!=recorded.get('login') or person['kind']!='person' or person['external']
                or recorded.get('projectId')!=project_id or recorded.get('role')!=duty):raise RFIError('The original RFI actor is not the recorded canonical project person')
        registered=_one([e for e in self.audit.entries(entity_type='people_person',entity_id=person['id']) if e['action']=='people.person_registered'],'Original RFI person registration')
        if registered['seq']>=event['seq'] or any(e['action']=='people.person_deactivated' and e['seq']<event['seq'] for e in self.audit.entries(entity_type='people_person',entity_id=person['id'])):
            raise RFIError('The original RFI actor was not an active original internal person')
        membership=self.db.one('SELECT * FROM people_memberships WHERE id=?',(recorded.get('membershipId'),))
        if membership is None or membership['person_id']!=person['id'] or membership['project_id']!=project_id:raise RFIError('The original RFI actor lost their owned membership provenance')
        membership_events=self.audit.entries(entity_type='people_membership',entity_id=membership['id'])
        added=_one([e for e in membership_events if e['action']=='people.membership_added'],'Original RFI membership')
        if added['seq']>=event['seq'] or any(e['action']=='people.membership_ended' and e['seq']<event['seq'] for e in membership_events):raise RFIError('The original RFI act had no active owned project membership')
        policy_events=self.db.query("SELECT * FROM audit_log WHERE action='people.policy_adopted' AND seq<? ORDER BY seq",(event['seq'],))
        policy_event=policy_events[-1] if policy_events else None
        policy=self.db.one('SELECT * FROM people_policy_versions WHERE id=?',(policy_event['entity_id'],)) if policy_event else None
        if (policy is None or not policy['enforce'] or not policy['segregate'] or policy['solo_owner_self_approval']
                or recorded.get('peoplePolicy')!={'policy_version':policy['version'],'policy_hash':policy['content_hash']}):
            raise RFIError('The original RFI actor did not act under the recorded segregated people policy')
        grant_ids=recorded.get('grantIds')
        if not isinstance(grant_ids,list) or len(set(grant_ids))!=len(grant_ids) or duty=='pm' and not grant_ids:raise RFIError('The original RFI PM grant inventory is unavailable')
        if duty=='staff' and grant_ids:raise RFIError('A staff preparation must not invent PM decision authority')
        day=event['ts'][:10]
        for identifier in grant_ids:
            grant=self.db.one('SELECT * FROM people_grants WHERE id=?',(identifier,))
            if (grant is None or grant['person_id']!=person['id'] or grant['role']!='pm' or grant['scope']!='project' or grant['project_id']!=project_id
                    or grant['effective_from']>day or grant['effective_to'] is not None and grant['effective_to']<day):raise RFIError('The original RFI PM grant was not actual effective owned project authority')
            grant_events=self.audit.entries(entity_type='people_grant',entity_id=identifier)
            granted=_one([e for e in grant_events if e['action']=='people.role_granted'],'Original RFI PM grant')
            if granted['seq']>=event['seq'] or any(e['action']=='people.role_revoked' and e['seq']<event['seq'] for e in grant_events):raise RFIError('The original RFI PM grant was not active at the original act')
        return recorded

    def _actor_at(self,actor,event,project_id,duty):
        people=self.c.plugin('people');people._require_intact();person=people._person_row(actor)
        if person is None:raise RFIError('The original RFI applicator has no canonical registered person')
        memberships=[]
        for row in self.db.query('SELECT * FROM people_memberships WHERE person_id=? AND project_id=?',(person['id'],project_id)):
            events=self.audit.entries(entity_type='people_membership',entity_id=row['id'])
            if any(e['action']=='people.membership_added' and e['seq']<event['seq'] for e in events) and not any(e['action']=='people.membership_ended' and e['seq']<event['seq'] for e in events):memberships.append(row)
        membership=_one(memberships,'Original RFI applicator membership');grant_ids=[];day=event['ts'][:10]
        if duty=='pm':
            for grant in self.db.query("SELECT * FROM people_grants WHERE person_id=? AND scope='project' AND project_id=? AND role='pm'",(person['id'],project_id)):
                events=self.audit.entries(entity_type='people_grant',entity_id=grant['id'])
                if (grant['effective_from']<=day and (grant['effective_to'] is None or day<=grant['effective_to'])
                        and any(e['action']=='people.role_granted' and e['seq']<event['seq'] for e in events)
                        and not any(e['action']=='people.role_revoked' and e['seq']<event['seq'] for e in events)):grant_ids.append(grant['id'])
        policies=self.db.query("SELECT entity_id FROM audit_log WHERE action='people.policy_adopted' AND seq<? ORDER BY seq",(event['seq'],))
        policy=self.db.one('SELECT version,content_hash FROM people_policy_versions WHERE id=?',(policies[-1]['entity_id'],)) if policies else None
        recorded={'personId':person['id'],'login':person['login'],'projectId':project_id,'role':duty,'membershipId':membership['id'],
                  'grantIds':sorted(grant_ids),'peoplePolicy':{'policy_version':policy['version'],'policy_hash':policy['content_hash']} if policy else None}
        return self._historical_person(recorded,event,project_id,duty)

    @contextmanager
    def _act(self):
        self.db.require_practice_mode();self.db.require_write_authority()
        with self.db.transaction() as conn:
            savepoint=new_id('rfi_control_act');conn.execute(f'SAVEPOINT {savepoint}')
            try:yield
            except BaseException:
                if conn.in_transaction:conn.execute(f'ROLLBACK TO {savepoint}')
                raise
            finally:
                if conn.in_transaction:conn.execute(f'RELEASE {savepoint}')

    def _put(self,kind,body,actor):
        if not self._schema_installed():raise RFIError('RFI source schema is not admitted')
        table=f'rfi_{kind}';payload=canonical_json(body);row_hash=hash_json(body)
        self.audit.record(actor,f'rfi.{kind}_recorded',table,body['id'],{'rowHash':row_hash,'rfiId':body['rfi_id'],'projectId':body['project_id']})
        keys=('id','project_id',*_SPECS[kind][1]);row={k:body[k] for k in keys};row.update(body_json=payload,row_hash=row_hash)
        self.db.execute(f"INSERT INTO {table} ({','.join(row)}) VALUES ({','.join('?' for _ in row)})",tuple(row.values()))
        return body

    def _proof(self,kind,identifier):
        if not self._schema_installed():raise RFIError('RFI source schema is not admitted')
        table=f'rfi_{kind}';row=self.db.one(f'SELECT * FROM {table} WHERE id=?',(identifier,))
        if row is None:raise RFIError('An original audited RFI source disappeared')
        events=self.db.query('SELECT * FROM audit_log WHERE action=? AND entity_type=? AND entity_id=?',(f'rfi.{kind}_recorded',table,identifier))
        try:
            event=_one(events,'RFI source birth');body=json.loads(row['body_json'])
            _same(row['body_json'],canonical_json(body),'Canonical RFI source');_same(row['row_hash'],hash_json(body),'RFI source row hash')
            _same(_payload(event),{'rowHash':row['row_hash'],'rfiId':body['rfi_id'],'projectId':body['project_id']},'RFI source original birth')
            for key in ('id','project_id',*_SPECS[kind][1]):_same(row[key],body[key],'RFI source indexed identity')
            _same(body['created_by'],event['actor'],'RFI source author');_near_time(body['created_at'],event,'RFI source creation')
        except (OwnedSourceError,ValueError,KeyError,TypeError) as exc:raise RFIError(str(exc)) from exc
        return {'record':body,'event':_event_ref(event),'rowHash':row['row_hash']}

    def _inventory(self,kind,project_ids=None):
        if not self._schema_installed():return []
        _intact(self.c)
        table=f'rfi_{kind}';row_filter='';audit_filter='';params=()
        if project_ids is not None:
            project_ids=tuple(project_ids)
            if not project_ids:return []
            marks=','.join('?' for _ in project_ids);row_filter=f' WHERE project_id IN ({marks})';audit_filter=f" AND json_extract(payload_json,'$.projectId') IN ({marks})";params=project_ids
        rows=self.db.query(f'SELECT id FROM {table}'+row_filter+' ORDER BY rowid',params)
        events=self.db.query('SELECT entity_id FROM audit_log WHERE action=? AND entity_type=?'+audit_filter+' ORDER BY seq',(f'rfi.{kind}_recorded',table,*params))
        if len(rows)!=len(events) or {r['id'] for r in rows}!={e['entity_id'] for e in events}:raise RFIError('RFI source inventory differs from its original audited births')
        return [self._proof(kind,row['id']) for row in rows]

    def create_preflight(self,project_id,body,*,actor):
        with self.db._lock:
            person=self._person(actor,project_id,'staff')
            body=_body(body,('subject','question','drawingRevisionIds','documentRevisionIds'))
            subject=_text(body['subject'],'RFI subject',200);question=_text(body['question'],'RFI question',12000)
            drawing_ids=_citations(body['drawingRevisionIds'],'Drawing citations');document_ids=_citations(body['documentRevisionIds'],'Supporting citations')
            try:
                drawings=[issued_drawing_proof(self.c,project_id,rid,current=True) for rid in drawing_ids]
                documents=[owned_revision_proof(self.c,project_id,rid,current=True) for rid in document_ids]
                if any(p['document']['kind'].strip().casefold()=='drawing' for p in documents):
                    raise RFIError('Cite drawing evidence through its issued drawing register revision, not as a supporting document')
                document_ids_all={proof['document']['id'] for proof in documents}|{proof['evidence']['document']['id'] for proof in drawings}
                rights=[document_rights_proof(self.c,project_id,did,'project_use') for did in sorted(document_ids_all)]
                if any(not r['allowed'] for r in rights):raise RFIError('A cited source does not permit current project use')
            except OwnedSourceError as exc:raise RFIError(str(exc)) from exc
            if self.db.one('SELECT id FROM field_rfis WHERE project_id=? AND lower(subject)=lower(?) AND lower(question)=lower(?)',(project_id,subject,question)):
                raise RFIError('This project already has an RFI asking the same question')
            return {'person':person,'source':{'projectId':project_id,'sourceKind':SOURCE_KIND,'drawings':drawings,'documents':documents,'rights':rights},
                    'nativeInput':{'subject':subject,'question':question,'drawing_revision_ids':drawing_ids,'document_revision_ids':document_ids}}

    def preparation_sources(self,project_id,*,actor):
        with self.db._lock:
            self._person(actor,project_id,'staff');_intact(self.c)
            registered=self.db.query("SELECT entity_id FROM audit_log WHERE action='drawing.registered' AND entity_type='drawing' AND json_extract(payload_json,'$.project_id')=?",(project_id,))
            native=self.db.query('SELECT id FROM drawing_register WHERE project_id=?',(project_id,))
            if len(registered)!=len(native) or {e['entity_id'] for e in registered}!={r['id'] for r in native}:raise RFIError('Project drawing inventory differs from its original registrations')
            drawings=[]
            for drawing in native:
                issued=self.db.query("SELECT entity_id FROM audit_log WHERE action='drawing.issued' AND entity_type='drawing_revision' AND json_extract(payload_json,'$.drawing_id')=? ORDER BY seq",(drawing['id'],))
                current=self.db.one("SELECT id FROM drawing_revisions WHERE drawing_id=? AND status='issued'",(drawing['id'],))
                if issued:
                    checked=issued_drawing_proof(self.c,project_id,issued[0]['entity_id'])
                    if current:drawings.append(issued_drawing_proof(self.c,project_id,current['id'],current=True))
                elif current:
                    raise RFIError('A claimed issued drawing has no original issue')
            births=self.db.query("SELECT entity_id FROM audit_log WHERE action='document.registered' AND entity_type='document' AND json_extract(payload_json,'$.project_id')=?",(project_id,))
            documents_native=self.db.query('SELECT id FROM documents WHERE project_id=?',(project_id,))
            if len(births)!=len(documents_native) or {e['entity_id'] for e in births}!={r['id'] for r in documents_native}:raise RFIError('Project document inventory differs from its original registrations')
            documents=[]
            for document in documents_native:
                current=self.c.evidence.current_revision(document['id'])
                revised=self.db.scalar("SELECT COUNT(*) FROM audit_log WHERE action='document.revised' AND entity_type='document' AND entity_id=?",(document['id'],))
                if current is None:
                    if revised:raise RFIError('A project document lost its original revision inventory')
                    continue
                documents.append(owned_revision_proof(self.c,project_id,current['id'],current=True))
            ids={p['document']['id'] for p in documents}|{p['evidence']['document']['id'] for p in drawings}
            rights=[document_rights_proof(self.c,project_id,did,'project_use') for did in sorted(ids)]
            by_document={p['documentId']:p for p in rights}
            for proof in documents:
                is_drawing=proof['document']['kind'].strip().casefold()=='drawing';permitted=by_document[proof['document']['id']]['allowed']
                proof['citable']=not is_drawing and permitted
                proof['citationHold']=({'code':'issued_drawing_required','message':'Cite drawings through their issued drawing register revision.'} if is_drawing else
                    {'code':'project_use_required','message':'This source does not permit current project use.'} if not permitted else None)
            return {'projectId':project_id,'drawings':drawings,'documents':documents,'rights':rights}

    @staticmethod
    def _evidence_origin(proof):
        return {k:proof[k] for k in ('projectId','document','revision','documentBirth','revisionBirth')}

    @classmethod
    def _drawing_origin(cls,proof):
        revision=proof['revision']
        return {'drawingId':proof['drawing']['id'],'projectId':proof['projectId'],'number':proof['drawing']['number'],
                'revision':{k:revision[k] for k in ('id','drawing_id','sequence','label','document_revision_id','content_hash','note','created_at')},
                'evidence':cls._evidence_origin(proof['evidence']),'issuedAtBirth':proof['issuedAtBirth'],'reference':proof['reference']}

    def create(self,project_id,body,*,actor):
        with self._act():
            if not self._schema_installed():raise RFIError('RFI source schema is not admitted')
            checked=self.create_preflight(project_id,body,actor=actor);person=checked['person'];native=checked['nativeInput']
            result=self.c.plugin('field').create_rfi(project_id,**native,actor=person['login'])
            row=self.db.one('SELECT * FROM field_rfis WHERE id=?',(result['id'],))
            links=self.db.query('SELECT * FROM field_rfi_links WHERE rfi_id=? ORDER BY created_at,id',(result['id'],))
            birth=_one([e for e in self.audit.entries(entity_type='field_rfi',entity_id=result['id']) if e['action']=='field.rfi_created'],'Native RFI creation')
            drawings=[]
            for rid in native['drawing_revision_ids']:
                link=_one([l for l in links if l['link_type']=='drawing_revision' and l['target_id']==rid],'Native drawing citation')
                drawings.append(self._drawing_origin(issued_drawing_proof(self.c,project_id,rid,current=True,reference_id=link['reference_id'],referenced_by_id=result['id'])))
            source={'id':new_id('rfis'),'project_id':project_id,'rfi_id':result['id'],'sourceKind':SOURCE_KIND,
                    'created_by':person['login'],'created_at':utcnow_iso(),'person':person,
                    'native':{k:row[k] for k in ('id','project_id','sequence','number','subject','question','content_hash','created_by','created_at')},
                    'creationEvent':_event_ref(birth),'links':links,'drawings':drawings,
                    'documents':[self._evidence_origin(p) for p in checked['source']['documents']],
                    'rightsAtCreation':checked['source']['rights']}
            self._put('sources',source,person['login']);self.source_proof(result['id'])
            return result

    def _source_record(self,rfi_id):
        if not self._schema_installed():raise RFIError('RFI source schema is not admitted')
        row=self.db.one('SELECT id FROM rfi_sources WHERE rfi_id=?',(rfi_id,))
        if row is None:raise RFIError('This RFI has no original admitted source')
        return self._proof('sources',row['id'])

    def _native_source(self,initial):
        body=initial['record'];rid=body['rfi_id'];project_id=body['project_id']
        row=self.db.one('SELECT * FROM field_rfis WHERE id=?',(rid,))
        if row is None:raise RFIError('An original native RFI disappeared')
        try:
            _same({k:row[k] for k in body['native']},body['native'],'Original native RFI question')
            _same(body['person']['login'],row['created_by'],'Original RFI author')
            birth=_one([e for e in self.audit.entries(entity_type='field_rfi',entity_id=rid) if e['action']=='field.rfi_created'],'Native RFI birth')
            self._historical_person(body['person'],birth,project_id,'staff')
            _same(_event_ref(birth),body['creationEvent'],'Original RFI creation event');_near_time(row['created_at'],birth,'Original RFI creation')
            if initial['event']['seq']<=birth['seq']:raise RFIError('RFI source predates its native question')
            links=self.db.query('SELECT * FROM field_rfi_links WHERE rfi_id=? ORDER BY created_at,id',(rid,))
            _same(links,body['links'],'Original RFI citation link inventory')
            drawings=[];documents=[]
            for original in body['drawings']:
                reference=original['reference']['record']
                proof=issued_drawing_proof(self.c,project_id,original['revision']['id'],reference_id=reference['id'],referenced_by_id=rid)
                _same(self._drawing_origin(proof),original,'Original RFI drawing citation');drawings.append(proof)
            for original in body['documents']:
                proof=owned_revision_proof(self.c,project_id,original['revision']['id'])
                _same(self._evidence_origin(proof),original,'Original RFI supporting citation');documents.append(proof)
            content={'project_id':project_id,'subject':row['subject'],'question':row['question'],
                     'drawing_revisions':[{'id':p['revision']['id'],'content_hash':p['revision']['content_hash']} for p in drawings],
                     'document_revisions':[{'id':p['revision']['id'],'content_hash':p['revision']['content_hash']} for p in documents]}
            _same(row['content_hash'],hash_json(content),'RFI question and ordered citation content')
            expected_birth={'project_id':project_id,'number':row['number'],'subject':row['subject'],'content_hash':row['content_hash'],'version':1,
                            'drawing_revisions':[{'id':p['revision']['id'],'drawing':p['drawing']['number'],'label':p['revision']['label'],'content_hash':p['revision']['content_hash']} for p in drawings],
                            'document_revisions':content['document_revisions']}
            _same(_payload(birth),expected_birth,'Native RFI original creation facts')
        except OwnedSourceError as exc:raise RFIError(str(exc)) from exc
        return row,drawings,documents,birth

    def _response_body(self,body):
        body=_body(body,('responseText','costImpact','scheduleImpactDays'))
        text=_text(body['responseText'],'Response text',12000);cost=body['costImpact'];days=body['scheduleImpactDays']
        if cost is not None and (not isinstance(cost,str) or re.fullmatch(r'(?:0|[1-9][0-9]{0,11})\.[0-9]{2}',cost) is None):raise RFIError('Cost impact requires a nonnegative exact two-place decimal or null')
        if days is not None and (type(days) is not int or days<0):raise RFIError('Schedule impact requires a nonnegative whole number of days or null')
        return {'response_text':text,'cost_impact':cost,'schedule_impact_days':days}

    def response_preflight(self,rfi_id,body,*,actor):
        project_id=self.source_scope(rfi_id)['projectId'];person=self._person(actor,project_id,'staff')
        source=self.source_proof(rfi_id,current=True);native=self._response_body(body)
        if source['native']['status']!='open':raise RFIError('Only an open RFI takes a response draft')
        from .field import _response_hash,_cost
        digest=_response_hash(native['response_text'],_cost(native['cost_impact']),native['schedule_impact_days'])
        if source['native']['draft_response_hash']==digest:raise RFIError('The RFI already carries this exact response draft')
        return {'source':source,'nativeInput':native,'person':person}

    def draft_response(self,rfi_id,body,*,actor):
        with self.db.transaction():
            checked=self.response_preflight(rfi_id,body,actor=actor)
            return self.c.plugin('field').draft_response(rfi_id,**checked['nativeInput'],actor=checked['person']['login'])

    def before_native_response(self,rfi_id,response_text,cost_impact,schedule_impact_days,actor):
        return self.response_preflight(rfi_id,{'responseText':response_text,'costImpact':cost_impact,'scheduleImpactDays':schedule_impact_days},actor=actor)

    def record_response_revision(self,rfi_id,actor):
        initial=self._source_record(rfi_id);project_id=initial['record']['project_id'];person=self._person(actor,project_id,'staff')
        row=self.db.one('SELECT * FROM field_rfis WHERE id=?',(rfi_id,))
        event=_one([e for e in self.audit.entries(entity_type='field_rfi',entity_id=rfi_id) if e['action']=='field.rfi_response_drafted' and _payload(e).get('version')==row['version']],'Native response draft')
        body={'id':new_id('rfir'),'project_id':project_id,'rfi_id':rfi_id,'native_version':row['version'],'created_by':person['login'],'created_at':utcnow_iso(),
              'person':person,'sourceId':initial['record']['id'],'sourceHash':initial['rowHash'],'nativeEvent':_event_ref(event),
              'response':row['draft_response'],'costImpact':row['draft_cost_impact'],'scheduleImpactDays':row['draft_schedule_impact_days'],'responseHash':row['draft_response_hash']}
        self._put('response_revisions',body,person['login'])

    def distribution_list_preflight(self,rfi_id,body,*,actor):
        project_id=self.source_scope(rfi_id)['projectId'];person=self._person(actor,project_id,'pm');source=self.source_proof(rfi_id,current=True)
        body=_body(body,('recipients',));recipients=body['recipients']
        if (type(recipients) is not list or not recipients or len(set(recipients))!=len(recipients)
                or any(type(r) is not str or r not in RECIPIENTS for r in recipients)):
            raise RFIError('Distribution recipients must be distinct fixed synthetic .invalid destinations')
        if source['native']['status']!='answered':raise RFIError('An official response is required before its distribution list')
        from .field import _recipients
        clean,digest=_recipients(recipients)
        if digest==source['native']['distribution_recipients_hash']:raise RFIError('The RFI already has this recipient set')
        if any(p['record']['recipients_hash']==digest for p in source['distributions']):raise RFIError('This original response was already distributed to that recipient set')
        # Saving fixed recipients is an authored draft. Distribution permission
        # remains a separately disclosed hold until request/grant/application.
        return {'source':source,'nativeInput':{'recipients':clean},'person':person,
                'distributionRights':self._rights_inventory(source,'distribution')}

    def set_distribution_list(self,rfi_id,body,*,actor):
        with self.db.transaction():
            checked=self.distribution_list_preflight(rfi_id,body,actor=actor)
            return self.c.plugin('field').set_distribution_list(rfi_id,checked['nativeInput']['recipients'],checked['person']['login'])

    def before_native_distribution_list(self,rfi_id,recipients,actor):
        return self.distribution_list_preflight(rfi_id,{'recipients':recipients},actor=actor)

    def record_distribution_revision(self,rfi_id,actor):
        initial=self._source_record(rfi_id);project_id=initial['record']['project_id'];person=self._person(actor,project_id,'pm')
        row=self.db.one('SELECT * FROM field_rfis WHERE id=?',(rfi_id,))
        event=_one([e for e in self.audit.entries(entity_type='field_rfi',entity_id=rfi_id) if e['action']=='field.rfi_distribution_list_set' and _payload(e).get('version')==row['version']],'Native distribution list')
        body={'id':new_id('rfidv'),'project_id':project_id,'rfi_id':rfi_id,'native_version':row['version'],'created_by':person['login'],'created_at':utcnow_iso(),
              'person':person,'sourceId':initial['record']['id'],'sourceHash':initial['rowHash'],'nativeEvent':_event_ref(event),
              'recipients':json.loads(row['distribution_recipients_json']),'recipientsHash':row['distribution_recipients_hash']}
        self._put('distribution_revisions',body,person['login'])

    def _approval_source(self,approval_id):
        row=self.db.one('SELECT id FROM rfi_approval_sources WHERE approval_id=?',(approval_id,))
        if row is None:raise RFIError('The original RFI approval source is unavailable')
        return self._proof('approval_sources',row['id'])

    def source_proof(self,rfi_id,*,current=False):
        return self._source_proof(rfi_id,current=current)

    def _source_proof(self,rfi_id,*,current=False,allow_consumed=None):
        with self.db._lock:
            try:
                _intact(self.c);initial=self._source_record(rfi_id);body=initial['record'];project_id=body['project_id']
                row,drawings,documents,birth=self._native_source(initial)
                responses=[p for p in self._inventory('response_revisions',(project_id,)) if p['record']['rfi_id']==rfi_id]
                lists=[p for p in self._inventory('distribution_revisions',(project_id,)) if p['record']['rfi_id']==rfi_id]
                response_by_version={p['record']['native_version']:p for p in responses};list_by_version={p['record']['native_version']:p for p in lists}
                if len(response_by_version)!=len(responses) or len(list_by_version)!=len(lists):raise RFIError('RFI native version sources are ambiguous')
                expected={'status':'open','version':1,'draft_response':None,'draft_cost_impact':None,'draft_schedule_impact_days':None,'draft_response_hash':None,
                          'response':None,'cost_impact':None,'schedule_impact_days':None,'response_hash':None,'approval_id':None,'answered_by':None,'answered_at':None,
                          'distribution_recipients_json':None,'distribution_recipients_hash':None}
                answer=None;distributions=[];seen_responses=set();seen_lists=set();last=birth;latest_response=None;latest_list=None
                native_events=self.audit.entries(entity_type='field_rfi',entity_id=rfi_id)
                native_distributions=self.db.query('SELECT * FROM field_rfi_distributions WHERE rfi_id=? ORDER BY distributed_at,id',(rfi_id,))
                distribution_rows={d['id']:d for d in native_distributions}
                for event in native_events:
                    action=event['action'];data=_payload(event)
                    if action=='field.rfi_created':continue
                    if action=='field.rfi_response_drafted':
                        version=data.get('version');proof=response_by_version.get(version)
                        if expected['status']!='open' or type(version) is not int or version!=expected['version']+1 or proof is None:
                            raise RFIError('RFI response history differs from its original native version inventory')
                        revision=proof['record'];seen_responses.add(version);latest_response=proof
                        self._historical_person(revision['person'],event,project_id,'staff')
                        _same({'id':revision['sourceId'],'hash':revision['sourceHash']},{'id':body['id'],'hash':initial['rowHash']},'RFI response original source')
                        _same(revision['nativeEvent'],_event_ref(event),'RFI response original event')
                        _same(revision['created_by'],event['actor'],'RFI response native author');_same(revision['person']['login'],event['actor'],'RFI response canonical author')
                        if proof['event']['seq']<=event['seq']:raise RFIError('RFI response proof predates its native draft')
                        from .field import _response_hash,_cost
                        digest=_response_hash(revision['response'],_cost(revision['costImpact']),revision['scheduleImpactDays'])
                        _same(digest,revision['responseHash'],'RFI response exact content')
                        _same({k:data.get(k) for k in ('number','version','draft_response_hash','cost_impact','schedule_impact_days')},
                              {'number':row['number'],'version':version,'draft_response_hash':digest,'cost_impact':revision['costImpact'],'schedule_impact_days':revision['scheduleImpactDays']},'Native RFI response draft facts')
                        expected.update(version=version,draft_response=revision['response'],draft_cost_impact=revision['costImpact'],
                                        draft_schedule_impact_days=revision['scheduleImpactDays'],draft_response_hash=digest);last=event
                    elif action=='field.rfi_answered':
                        if expected['status']!='open' or latest_response is None or data.get('version')!=expected['version']+1 or answer is not None:
                            raise RFIError('RFI official response has an unexplained native transition')
                        approval_id=data.get('approval_id');approval=consumed_approval_proof(self.c,approval_id,RESPONSE,'field_rfi',rfi_id)
                        sealed=self._approval_source(approval_id)
                        _same(sealed['record']['responseRevisionId'],latest_response['record']['id'],'Original official response revision')
                        _same(sealed['record']['sourceHash'],initial['rowHash'],'Original official response source')
                        _same({k:data.get(k) for k in ('number','response_hash','cost_impact','schedule_impact_days')},
                              {'number':row['number'],'response_hash':expected['draft_response_hash'],'cost_impact':expected['draft_cost_impact'],'schedule_impact_days':expected['draft_schedule_impact_days']},'Native official response facts')
                        _same(approval['record']['consumed_by'],event['actor'],'Original official response applicator')
                        applicator=self._actor_at(event['actor'],event,project_id,'pm')
                        if approval['consumption']['seq']>=event['seq']:raise RFIError('Official RFI response predates its consumed grant')
                        _near_time(row['answered_at'],event,'Official RFI response')
                        expected.update(status='answered',version=data['version'],response=expected['draft_response'],cost_impact=expected['draft_cost_impact'],
                                        schedule_impact_days=expected['draft_schedule_impact_days'],response_hash=expected['draft_response_hash'],
                                        approval_id=approval_id,answered_by=event['actor'],answered_at=row['answered_at']);last=event
                        original={'rfi':rfi_id,'number':row['number'],'status':'answered','version':data['version'],'response_hash':expected['response_hash'],
                                  'cost_impact':expected['cost_impact'],'schedule_impact_days':expected['schedule_impact_days'],'answered_at':row['answered_at']}
                        answer={'result':original,'event':_event_ref(event),'approval':approval,'source':sealed,'applicator':applicator}
                    elif action=='field.rfi_distribution_list_set':
                        version=data.get('version');proof=list_by_version.get(version)
                        if expected['status']!='answered' or type(version) is not int or version!=expected['version']+1 or proof is None:
                            raise RFIError('RFI distribution-list history has an unexplained native version')
                        revision=proof['record'];seen_lists.add(version);latest_list=proof
                        self._historical_person(revision['person'],event,project_id,'pm')
                        _same({'id':revision['sourceId'],'hash':revision['sourceHash']},{'id':body['id'],'hash':initial['rowHash']},'RFI recipient original source')
                        _same(revision['nativeEvent'],_event_ref(event),'RFI recipient original event')
                        _same(revision['created_by'],event['actor'],'RFI recipient native author');_same(revision['person']['login'],event['actor'],'RFI recipient canonical author')
                        from .field import _recipients
                        clean,digest=_recipients(revision['recipients'])
                        _same(digest,revision['recipientsHash'],'RFI recipient set content')
                        _same({k:data.get(k) for k in ('number','version','recipients','recipients_hash')},
                              {'number':row['number'],'version':version,'recipients':clean,'recipients_hash':digest},'Native RFI recipient facts')
                        if proof['event']['seq']<=event['seq']:raise RFIError('RFI recipient proof predates its native list')
                        expected.update(version=version,distribution_recipients_json=json.dumps(clean),distribution_recipients_hash=digest);last=event
                    elif action=='field.rfi_distributed':
                        identifier=data.get('distribution_id');distribution=distribution_rows.get(identifier)
                        if expected['status']!='answered' or latest_list is None or distribution is None or any(d['record']['id']==identifier for d in distributions):
                            raise RFIError('RFI original distribution is missing or duplicated')
                        _same({k:data.get(k) for k in ('number','rfi_version','response_hash','recipients_hash','recipients','channel')},
                              {'number':row['number'],'rfi_version':expected['version'],'response_hash':expected['response_hash'],
                               'recipients_hash':expected['distribution_recipients_hash'],'recipients':latest_list['record']['recipients'],'channel':'mail-sink'},'Native RFI distribution facts')
                        approval_id=data.get('approval_id');approval=consumed_approval_proof(self.c,approval_id,DISTRIBUTE,'field_rfi',rfi_id)
                        sealed=self._approval_source(approval_id)
                        _same(sealed['record']['distributionRevisionId'],latest_list['record']['id'],'Original distribution recipient revision')
                        _same({k:distribution[k] for k in ('rfi_id','rfi_version','response_hash','recipients_json','recipients_hash','channel','distributed_by','approval_id')},
                              {'rfi_id':rfi_id,'rfi_version':expected['version'],'response_hash':expected['response_hash'],'recipients_json':expected['distribution_recipients_json'],
                               'recipients_hash':expected['distribution_recipients_hash'],'channel':'mail-sink','distributed_by':event['actor'],'approval_id':approval_id},'Original distribution row')
                        _same(approval['record']['consumed_by'],event['actor'],'Original distribution applicator');_near_time(distribution['distributed_at'],event,'Original synthetic distribution')
                        applicator=self._actor_at(event['actor'],event,project_id,'pm')
                        if approval['consumption']['seq']>=event['seq']:raise RFIError('RFI distribution predates its consumed grant')
                        distributions.append({'record':distribution,'event':_event_ref(event),'approval':approval,'source':sealed,'applicator':applicator})
                    else:raise RFIError('The RFI has an unsupported native lifecycle act')
                if seen_responses!=set(response_by_version) or seen_lists!=set(list_by_version) or len(distributions)!=len(native_distributions):
                    raise RFIError('An original RFI version or distribution disappeared from its native history')
                _same({k:row[k] for k in expected},expected,'RFI current native state');_near_time(row['updated_at'],last,'RFI current version')
                approval_sources=[p for p in self._inventory('approval_sources',(project_id,)) if p['record']['rfi_id']==rfi_id]
                native_approvals=self.db.query("SELECT id FROM approvals WHERE subject_type='field_rfi' AND subject_id=? AND operation IN ('field.respond_rfi','field.distribute_rfi')",(rfi_id,))
                native_requests=self.db.query("SELECT entity_id FROM audit_log WHERE action='approval.requested' AND entity_type='approval' AND json_extract(payload_json,'$.subject.type')='field_rfi' AND json_extract(payload_json,'$.subject.id')=? AND json_extract(payload_json,'$.operation') IN ('field.respond_rfi','field.distribute_rfi')",(rfi_id,))
                expected_ids={p['record']['approval_id'] for p in approval_sources}
                if expected_ids!={a['id'] for a in native_approvals} or expected_ids!={a['entity_id'] for a in native_requests} or len(expected_ids)!=len(native_requests):
                    raise RFIError('RFI original approval inventory lost its reviewed source')
                approvals=[self.approval_proof(p['record']['approval_id']) for p in approval_sources]
                effect_ids={d['record']['approval_id'] for d in distributions}
                if answer is not None:effect_ids.add(answer['approval']['record']['id'])
                for approval in approvals:
                    if approval['record']['status']=='consumed' and approval['record']['id'] not in effect_ids|{allow_consumed}:
                        raise RFIError('A consumed RFI approval lost its exact original native effect')
                result={'record':body,'sourceHash':initial['rowHash'],'native':row,'projectId':project_id,'drawings':drawings,'documents':documents,
                        'responseRevisions':responses,'distributionRevisions':lists,'latestResponse':latest_response,'latestDistribution':latest_list,
                        'answer':answer,'distributions':distributions,'approvals':approvals}
                if current:result['currentRights']=self._current_rights(result,'project_use')
                return result
            except OwnedSourceError as exc:raise RFIError(str(exc)) from exc

    def _rights_inventory(self,source,use):
        ids={p['document']['id'] for p in source['documents']}|{p['evidence']['document']['id'] for p in source['drawings']}
        return [document_rights_proof(self.c,source['projectId'],did,use) for did in sorted(ids)]

    def _current_rights(self,source,use):
        rights=self._rights_inventory(source,use)
        if any(not p['allowed'] for p in rights):raise RFIError('A cited source does not permit this current RFI use')
        return rights

    @staticmethod
    def _stable_rights(value):
        # Clock/date explanations are disclosed in the sealed original review.
        # Material permission binds actual terms/tags/purges/allowed/valid-until;
        # UTC midnight alone is not a new independently invented expiry policy.
        if isinstance(value,dict):return {k:Plugin._stable_rights(v) for k,v in value.items() if k not in ('onDate','on_date','reason','proofHash')}
        if isinstance(value,list):return [Plugin._stable_rights(v) for v in value]
        return value

    def _review_context(self,source,operation):
        if operation not in OPERATIONS:raise RFIError('The RFI operation is unsupported')
        if operation==RESPONSE and (source['native']['status']!='open' or source['latestResponse'] is None):raise RFIError('An open RFI with a drafted response is required')
        if operation==DISTRIBUTE and (source['native']['status']!='answered' or source['latestDistribution'] is None):raise RFIError('An answered RFI and recorded recipients are required')
        rights=self._current_rights(source,'distribution' if operation==DISTRIBUTE else 'project_use')
        if operation==DISTRIBUTE and any(d['record']['recipients_hash']==source['native']['distribution_recipients_hash'] for d in source['distributions']):
            raise RFIError('This original response already reached that synthetic recipient set')
        context={'sourceId':source['record']['id'],'sourceHash':source['sourceHash'],'nativeVersion':source['native']['version'],
                 'status':source['native']['status'],'responseRevisionId':source['latestResponse']['record']['id'] if source['latestResponse'] else None,
                 'distributionRevisionId':source['latestDistribution']['record']['id'] if operation==DISTRIBUTE else None,
                 'drawings':source['drawings'],'documents':source['documents'],'rights':rights,'peoplePolicy':self.c.plugin('people')._binding()}
        stable={**context,'rights':self._stable_rights(rights)}
        return context,hash_json(stable)

    def _binding(self,source,operation):
        context,digest=self._review_context(source,operation)
        return {'sourceId':source['record']['id'],'sourceHash':source['sourceHash'],'nativeVersion':source['native']['version'],
                'responseRevisionId':context['responseRevisionId'],'distributionRevisionId':context['distributionRevisionId'],'contextHash':digest}

    def approval_policy(self,operation,manifest):
        rfi_id=(manifest.get('subject') or {}).get('id')
        if operation not in OPERATIONS or not self.is_modern(rfi_id):return None
        return self._binding(self.source_proof(rfi_id),operation)

    def check_request(self,operation,manifest,*,actor_role,requested_by):
        rfi_id=(manifest.get('subject') or {}).get('id')
        if operation not in OPERATIONS or not self.is_modern(rfi_id):return
        self._person(requested_by,self.source_scope(rfi_id)['projectId'],'pm')
        if actor_role!='pm' or manifest.get('actor_role')!='pm':raise RFIError('RFI approvals use only the actual PM role')
        source=self.source_proof(rfi_id);expected=self._binding(source,operation)
        if (manifest.get('governance') or {}).get(PLUGIN_NAME)!=expected:raise StaleApprovalError('The RFI current source review changed')
        if any(p['record']['status'] in ('pending','granted') and parse_iso(p['record']['expires_at'])>utcnow()
               and material_hash(p['record']['manifest'])==material_hash(manifest)
               and p['record']['manifest'].get('governance')==manifest.get('governance') for p in source['approvals']):
            raise RFIError('This exact RFI source already has an active approval request')

    def request_preflight(self,rfi_id,operation,*,actor):
        person=self._person(actor,self.source_scope(rfi_id)['projectId'],'pm');source=self.source_proof(rfi_id)
        self._review_context(source,operation)
        manifest=self.c._manifest(operation,rfi_id,'pm')
        for name,governor in self.c._governors():
            check=getattr(governor,'check_request',None)
            if check is not None:check(operation,manifest,actor_role='pm',requested_by=person['login'])
        return {'person':person,'source':source,'manifest':manifest}

    def response_request_preflight(self,rfi_id,*,actor):return self.request_preflight(rfi_id,RESPONSE,actor=actor)
    def distribution_request_preflight(self,rfi_id,*,actor):return self.request_preflight(rfi_id,DISTRIBUTE,actor=actor)

    def record_approval_source(self,approval_id,checked):
        approval=self.approvals.get(approval_id);source=checked['source'];person=checked['person'];operation=approval['operation']
        if approval['status']!='pending' or approval['subject_id']!=source['native']['id'] or approval['requested_by']!=person['login']:
            raise RFIError('The RFI request does not match its actual reviewed source')
        context,digest=self._review_context(source,operation)
        _same((approval['manifest'].get('governance') or {}).get(PLUGIN_NAME),self._binding(source,operation),'Original RFI request source binding')
        body={'id':new_id('rfias'),'project_id':source['projectId'],'rfi_id':source['native']['id'],'approval_id':approval_id,'operation':operation,
              'created_by':person['login'],'created_at':utcnow_iso(),'person':person,'sourceId':source['record']['id'],'sourceHash':source['sourceHash'],
              'responseRevisionId':context['responseRevisionId'],'distributionRevisionId':context['distributionRevisionId'],
              'context':context,'contextHash':digest,'nativeManifest':approval['manifest']}
        return self._put('approval_sources',body,person['login'])

    def approval_proof(self,approval_id):
        try:
            _intact(self.c);row=self.approvals.get(approval_id);sealed=self._approval_source(approval_id);body=sealed['record']
            _same(row['manifest'],body['nativeManifest'],'RFI original approval manifest')
            _same(row['manifest_hash'],hash_json(row['manifest']),'RFI original manifest hash');_same(row['material_hash'],material_hash(row['manifest']),'RFI original material hash')
            _same({k:row[k] for k in ('operation','subject_type','subject_id','actor_role','policy_version','nonce','expires_at')},
                  {'operation':body['operation'],'subject_type':'field_rfi','subject_id':body['rfi_id'],'actor_role':'pm',
                   **{k:row['manifest'].get(k) for k in ('policy_version','nonce','expires_at')}},'RFI original approval columns')
            initial=self._source_record(body['rfi_id']);_same(body['sourceHash'],initial['rowHash'],'RFI approval original source hash')
            _same(body['sourceId'],initial['record']['id'],'RFI approval original source identity')
            context={**body['context'],'rights':self._stable_rights(body['context']['rights'])}
            _same(body['contextHash'],hash_json(context),'RFI sealed current-source disclosure')
            events=self.audit.entries(entity_type='approval',entity_id=approval_id)
            request=_one([e for e in events if e['action']=='approval.requested'],'RFI original approval request')
            _same(_payload(request),{'operation':body['operation'],'subject':{'type':'field_rfi','id':body['rfi_id']},'manifest_hash':row['manifest_hash']},'RFI approval original request')
            _same(row['requested_by'],request['actor'],'RFI original requester');_same(body['person']['login'],request['actor'],'RFI canonical original requester')
            _near_time(row['requested_at'],request,'RFI approval request')
            self._historical_person(body['person'],request,body['project_id'],'pm')
            if sealed['event']['seq']<=request['seq']:raise RFIError('RFI approval source predates its native request')
            status='pending';grant=None;consume=None;terminal=None
            for event in events:
                if event['action']=='approval.requested':continue
                data=_payload(event)
                if event['action']=='approval.granted' and status=='pending':
                    status='granted';grant=event;_same(data,{'operation':row['operation'],'material_hash':row['material_hash']},'RFI native grant')
                elif event['action']=='rfi.review_granted' and status=='granted':
                    continue  # Its complete source/authority proof is checked below.
                elif event['action']=='approval.consumed' and status=='granted':
                    status='consumed';consume=event;_same(data,{'operation':row['operation'],'material_hash':row['material_hash']},'RFI native consumption')
                elif event['action']=='approval.invalidated' and status in ('pending','granted'):
                    status='invalidated';terminal=event
                elif event['action']=='approval.expired' and status in ('pending','granted'):
                    status='expired';terminal=event
                else:raise RFIError('RFI approval has an unexplained native lifecycle act')
            _same(row['status'],status,'RFI current approval status')
            if grant:
                _same(row['approver'],grant['actor'],'RFI original PM reviewer');_near_time(row['granted_at'],grant,'RFI original grant')
                if parse_iso(row['granted_at'])>=parse_iso(row['expires_at']):raise RFIError('The original RFI grant missed its original deadline')
                marker=_one([e for e in events if e['action']=='rfi.review_granted'],'Original RFI qualified review')
                reviewed=_payload(marker)
                _same({k:reviewed.get(k) for k in ('approvalId','sourceId','sourceHash','contextHash')},
                      {'approvalId':approval_id,'sourceId':body['sourceId'],'sourceHash':body['sourceHash'],'contextHash':body['contextHash']},'Original RFI qualified review source')
                reviewer=self._historical_person(reviewed['reviewer'],grant,body['project_id'],'pm')
                actual=self.c.plugin('people')._person_row(row['approver'])
                if actual is None or actual['id']!=reviewer['personId'] or marker['actor']!=reviewer['login'] or marker['seq']<=grant['seq']:
                    raise RFIError('The native RFI review differs from its canonical qualified reviewer')
                if reviewer['personId']==body['person']['personId']:raise RFIError('The original RFI reviewer was its own requester')
                if body['operation']==RESPONSE:
                    authored=self._proof('response_revisions',body['responseRevisionId'])['record']['person']
                    if reviewer['personId']==authored['personId']:raise RFIError('The original RFI reviewer was the response author')
            elif row['approver'] is not None or row['granted_at'] is not None:raise RFIError('RFI approval has an unaudited grant')
            if consume:
                _same(row['consumed_by'],consume['actor'],'RFI original PM applicator');_near_time(row['consumed_at'],consume,'RFI original consumption')
                if parse_iso(row['consumed_at'])>=parse_iso(row['expires_at']):raise RFIError('The original RFI application missed its original deadline')
            elif row['consumed_by'] is not None or row['consumed_at'] is not None:raise RFIError('RFI approval has an unaudited consumption')
            if status=='invalidated':_same(row['invalidated_reason'],_payload(terminal).get('reason'),'RFI original invalidation')
            return {'record':row,'source':sealed,'request':_event_ref(request),'grant':_event_ref(grant) if grant else None,'consumption':_event_ref(consume) if consume else None}
        except OwnedSourceError as exc:raise RFIError(str(exc)) from exc

    def _decision_preflight(self,approval_id,*,actor,phase,allow_consumed=False):
        project_id=self.approval_scope(approval_id)['projectId'];person=self._person(actor,project_id,'pm');proof=self.approval_proof(approval_id)
        approval=proof['record'];sealed=proof['source']['record'];operation=approval['operation']
        expected_status='pending' if phase=='grant' else 'consumed' if allow_consumed else 'granted'
        if approval['status']!=expected_status:raise RFIError('The RFI approval is not available for this step')
        if not allow_consumed and parse_iso(approval['expires_at'])<=utcnow():raise RFIError('The original RFI approval deadline has passed')
        try:requester=self._person(approval['requested_by'],project_id,'pm')
        except RFIError as exc:raise StaleApprovalError('The original RFI requester no longer has current own PM duty') from exc
        source=self._source_proof(approval['subject_id'],allow_consumed=approval_id if allow_consumed else None)
        binding=self._binding(source,operation)
        if (approval['manifest'].get('governance') or {}).get(PLUGIN_NAME)!=binding:raise StaleApprovalError('The RFI cited source/current head/rights review changed; request a fresh review')
        try:reviewer=person if phase=='grant' else self._person(approval['approver'],project_id,'pm')
        except RFIError as exc:raise StaleApprovalError('The original RFI reviewer no longer has current own PM duty') from exc
        if reviewer['personId']==requester['personId']:raise RFIError('The RFI reviewer must be a different canonical person from its requester')
        if operation==RESPONSE:
            author=source['latestResponse']['record']['person']
            if reviewer['personId']==author['personId']:raise RFIError('The official response reviewer must differ from the response author')
        manifest=self._manifest_for_source(source,operation)
        if material_hash(manifest)!=approval['material_hash'] or manifest.get('governance')!=approval['manifest'].get('governance'):
            raise StaleApprovalError('The RFI native facts or configured governance changed after review')
        return {'person':person,'source':source,'approval':proof,'manifest':manifest,'requester':requester,'reviewer':reviewer}

    def _manifest_for_source(self,source,operation):
        manifest=self.c._base_manifest(operation,source['native']['id'],'pm');bound={}
        for name,governor in self.c._governors():
            if name==PLUGIN_NAME:facts=self._binding(source,operation)
            else:
                policy=getattr(governor,'approval_policy',None);facts=policy(operation,manifest) if policy is not None else None
            if facts:bound[name]=facts
        if bound:manifest['governance']=bound
        return manifest

    def grant_preflight(self,approval_id,*,actor):
        checked=self._decision_preflight(approval_id,actor=actor,phase='grant')
        for name,governor in self.c._governors():
            if name==PLUGIN_NAME:continue
            check=getattr(governor,'check_grant',None)
            if check is not None:check(checked['approval']['record'],approver=checked['person']['login'],approver_role='pm')
        return checked

    def execution_preflight(self,approval_id,*,actor):
        checked=self._decision_preflight(approval_id,actor=actor,phase='execute')
        for name,governor in self.c._governors():
            if name==PLUGIN_NAME or getattr(governor,'check_execute',None) is None:continue
            check=getattr(governor,'check_execute',None) if name=='people' else getattr(governor,'check_execute_preflight',None)
            if check is None:raise RFIError('A configured governor cannot supply a pure RFI execution review')
            check(checked['approval']['record'],checked['manifest'],actor=checked['person']['login'])
        return checked

    def check_grant(self,approval,*,approver,approver_role):
        if approval['operation'] not in OPERATIONS or not self.is_modern(approval['subject_id']):return
        if approver_role!='pm':raise RFIError('RFI decisions require only the actual PM role')
        self.grant_preflight(approval['id'],actor=approver)

    def on_grant(self,approval,*,approver,approver_role):
        if approval['operation'] not in OPERATIONS or not self.is_modern(approval['subject_id']):return
        source=self._approval_source(approval['id'])['record'];reviewer=self._person(approver,source['project_id'],'pm')
        if approver_role!='pm' or reviewer['personId']==source['person']['personId']:raise RFIError('RFI qualified review requires an independent actual PM')
        if approval['operation']==RESPONSE:
            author=self._proof('response_revisions',source['responseRevisionId'])['record']['person']
            if reviewer['personId']==author['personId']:raise RFIError('The RFI response author cannot grant its official response')
        self.audit.record(reviewer['login'],'rfi.review_granted','approval',approval['id'],
            {'approvalId':approval['id'],'sourceId':source['sourceId'],'sourceHash':source['sourceHash'],'contextHash':source['contextHash'],'reviewer':reviewer})

    def check_execute(self,approval,manifest,*,actor):
        if approval['operation'] not in OPERATIONS or not self.is_modern(approval['subject_id']):return
        self.execution_preflight(approval['id'],actor=actor)

    def check_execute_preflight(self,approval,manifest,*,actor):
        return self.check_execute(approval,manifest,actor=actor)

    def check_native_application(self,approval_id,*,actor):
        checked=self._decision_preflight(approval_id,actor=actor,phase='execute',allow_consumed=True)
        for name,governor in self.c._governors():
            if name==PLUGIN_NAME:continue
            check=getattr(governor,'check_execute',None)
            if check is not None:check(checked['approval']['record'],checked['manifest'],actor=checked['person']['login'])
        return checked

    def source_inventory(self,project_ids=None):return [self.source_proof(p['record']['rfi_id']) for p in self._inventory('sources',project_ids)]
    def approval_inventory(self,project_ids=None):return [self.approval_proof(p['record']['approval_id']) for p in self._inventory('approval_sources',project_ids)]

    def effect_proof(self,approval_id):
        approval=self.approval_proof(approval_id);source=self.source_proof(approval['record']['subject_id'])
        if approval['record']['operation']==RESPONSE:
            answer=source['answer'];return answer if answer and answer['approval']['record']['id']==approval_id else None
        return next((d for d in source['distributions'] if d['record']['approval_id']==approval_id),None)

    def close_checks(self,period_id):
        """A global source-integrity prerequisite; no RFI impact is attributed to a period."""
        try:
            if not self._schema_installed():return []
            inventories={kind:self._inventory(kind) for kind in _SPECS}
            if not any(inventories.values()):return []
            ids={p['record']['rfi_id'] for p in inventories['sources']}
            if any(p['record']['rfi_id'] not in ids for kind,items in inventories.items() for p in items):raise RFIError('RFI version history has no original source')
            for source in inventories['sources']:self.source_proof(source['record']['rfi_id'])
            return [{'check':'RFI source integrity','ok':True,'detail':'Global RFI source, response and synthetic distribution histories retain their original proofs; no financial impact is adopted.'}]
        except Exception:
            return [{'check':'RFI source integrity','ok':False,'detail':'Global RFI source history could not be verified; this is not a period financial adjustment.'}]

    def manifest_for(self,operation,subject_id,*,actor_role):raise RFIError('RFI controls preserve native field operation ownership')
    def apply(self,operation,subject_id,*,approval_id,manifest,actor,period_id):raise RFIError('RFI controls preserve native field operation ownership')
    def state(self,project_id=None):return {'sources':[p['record'] for p in self._inventory('sources') if project_id is None or p['record']['project_id']==project_id]}

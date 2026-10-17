"""Host FLD02 evidence: real FLD01/02 services, serialization and controllers.

Database/session/source doubles are explicit. No native/offline browser claim.
"""
from contextlib import contextmanager
from copy import deepcopy
import importlib,json,sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from cipher_aec.api.contracts import digest
from cipher_aec.api.errors import DomainError
from cipher_aec.tests.test_field import fixtures,uid,daily,ticket,quantity,add_source,add_person

@contextmanager
def fixture():
    with fixtures() as (s,f,frepo,fsources,field,frecords):
        sys.modules['cipher_aec.governance.context'].require_effects_enabled=lambda:None
        sys.modules['frappe'].QueryDeadlockError=type('HostDeadlock',(Exception,),{})
        sys.modules['frappe'].QueryTimeoutError=type('HostTimeout',(Exception,),{})
        names=['cipher_aec.field_offline.'+n for n in ('repository','records','service')]
        old={n:sys.modules.pop(n) for n in names if n in sys.modules}
        repo,records,service=[importlib.import_module(n) for n in names]
        db=sys.modules['frappe'].db;db.savepoints={}
        def savepoint(name):db.savepoints[name]=deepcopy((s.native,s.events,s.receipts))
        def rollback(save_point=None):
            if save_point is not None:s.native,s.events,s.receipts=deepcopy(db.savepoints[save_point])
        db.savepoint=savepoint;db.rollback=rollback
        original_validate=s.FakeDocument._validate
        def validate(doc):
            if doc.doctype in repo.KINDS.values():records.OfflineRecord.validate(doc)
            else:original_validate(doc)
        def run(**kw):
            actor=service.current_actor();service._authorize(kw['company'],kw['project'],actor,write=True)
            key=(actor.person_id,kw['operation_id']);request=digest({k:kw[k] for k in ('command','company','project','payload')})
            if key in s.receipts:
                checksum,result=s.receipts[key]
                if checksum!=request:raise DomainError('operation_conflict','different request',409)
                service.authorize_receipt(actor,kw['company'],kw['project'],result,lock=True)
                return {**deepcopy(result),'operation':{'id':key[1],'status':'succeeded','replayed':True}}
            before=deepcopy((s.native,s.events,s.receipts))
            try:
                if kw.get('guard'):kw['guard'](actor,s.require('C','P'))
                result=kw['effect'](actor,s.require('C','P'))
                if s.failed_receipt:raise RuntimeError('late offline receipt failure')
                s.receipts[key]=(request,deepcopy(result))
                return {**result,'operation':{'id':key[1],'status':'succeeded','replayed':False}}
            except Exception:s.native,s.events,s.receipts=before;raise
        def canonical(person,capture_id,lock=False):
            entry=s.receipts.get((person,capture_id))
            if not entry:return None
            checksum,result=entry
            family=result.get('family','daily')
            # The real command hash is independently compared by _original.
            return {'command':s.business_names.get(capture_id,'field.'+family+'.create.v1'),'company':'C','project':'P','scope_type':'Project','request_hash':checksum,'result_hash':digest(result),'result':deepcopy(result),'state':'Succeeded'}
        s.business_names={};s.effects=True;s.failed_capture_write=False
        def enabled():
            if not s.effects:raise DomainError('execution_quarantined','restored read only',503)
        lock_calls=[]
        original_sql=db.sql
        def sql(query,args=(),**kw):
            if 'tabCipher Person' in query or 'tabCipher Identity Binding' in query:lock_calls.append(query);return []
            return original_sql(query,args,**kw)
        with patch.object(s.FakeDocument,'_validate',validate),patch.object(service,'run_command',run),patch.object(service,'require_effects_enabled',enabled),patch.object(repo,'canonical_receipt',canonical),patch.object(db,'sql',sql):
            s.lock_calls=lock_calls
            try:yield s,f,frepo,field,repo,records,service
            finally:
                for n in names:
                    removed=sys.modules.pop(n,None);parentname,attribute=n.rsplit('.',1);parent=sys.modules.get(parentname)
                    if parent is not None and getattr(parent,attribute,None) is removed:delattr(parent,attribute)
                sys.modules.update(old)
                for n,value in old.items():setattr(sys.modules[n.rsplit('.',1)[0]],n.rsplit('.',1)[1],value)

def device(s,service):return service.register_device('C','P',uid(),uid(),'Dedicated field tablet')
def envelope(s,device,family='daily',capture_id=None):
    ref=add_source(s)
    return {'schema':'cipher.field.offline.v1','device_id':device['device']['device_id'],'capture_id':capture_id or uid(),'company':'C','project':'P','actor_person':device['device']['owner_person'],'actor_user':device['device']['registered_user'],'captured_at':'2026-10-17T09:30:00-04:00','command':{'action':'create','family':family,'definition':daily(s) if family=='daily' else ticket(ref),'photos':[],'quantities':[quantity(ref)] if family=='daily' else []}}
def stage(s,service,family='daily'):
    dev=device(s,service);e=envelope(s,dev,family);result=service.stage_capture('C','P',uid(),e)
    return dev,e,result
def apply(service,e,result):return service.apply_capture('C','P',e['capture_id'],e['capture_id'],result['capture_version'])

class OfflineFieldTests(unittest.TestCase):
    def test_explicit_stage_inspect_apply_duplicate_and_restart_receipt(self):
        with fixture() as (s,f,fr,field,repo,records,service):
            dev,e,staged=stage(s,service);self.assertFalse(any(dt in f.KINDS.values() for dt,_ in s.native))
            before=deepcopy((s.native,s.receipts));inspection=service.inspect_capture('C','P',e['capture_id'])
            self.assertEqual(inspection['disposition'],'ready');self.assertEqual((s.native,s.receipts),before)
            result=apply(service,e,staged);count=len(s.native);self.assertFalse(result['replayed'])
            again=apply(service,e,staged)
            self.assertTrue(again['replayed']);self.assertEqual(len(s.native),count)
            self.assertEqual(again['original_receipt']['revision'],result['original_receipt']['revision'])
            self.assertEqual(again['capture']['status'],'committed');self.assertTrue(s.lock_calls)
            self.assertEqual(service.get_capture('C','P',e['capture_id'])['original_receipt']['revision'],result['original_receipt']['revision'])
    def test_changed_payload_same_capture_or_original_stage_operation_conflicts(self):
        with fixture() as (s,f,fr,field,repo,records,service):
            dev=device(s,service);e=envelope(s,dev);op=uid();first=service.stage_capture('C','P',op,e)
            self.assertTrue(service.stage_capture('C','P',op,e)['operation']['replayed'])
            changed=deepcopy(e);changed['command']['quantities'][0]['quantity']='99.000000'
            for operation in (op,uid()):
                with self.assertRaises(DomainError) as error:service.stage_capture('C','P',operation,changed)
                self.assertIn(error.exception.code,('operation_conflict','field_capture_conflict'))
            self.assertEqual(service.get_capture('C','P',e['capture_id'])['envelope'],e)
    def test_same_person_alias_sync_keeps_original_capture_attribution(self):
        with fixture() as (s,f,fr,field,repo,records,service):
            dev,e,staged=stage(s,service);original=s.actor
            alias=SimpleNamespace(user='field-alias@example.invalid',person_id=original.person_id);s.users[alias.user]=alias;s.actor=alias
            result=apply(service,e,staged)
            self.assertEqual(result['capture']['actor_user'],original.user)
            self.assertEqual(result['original_receipt']['revision']['author_user'],alias.user)
            self.assertEqual(result['original_receipt']['revision']['author_person'],original.person_id)
            self.assertTrue(apply(service,e,staged)['replayed'])
    def test_other_person_scope_and_forged_actor_never_sync(self):
        with fixture() as (s,f,fr,field,repo,records,service):
            dev,e,staged=stage(s,service);other=add_person(s,'other');original=s.actor;s.actor=other
            with self.assertRaises(DomainError):service.get_capture('C','P',e['capture_id'])
            with self.assertRaises(DomainError):apply(service,e,staged)
            s.actor=original
            for change in ({'actor_person':other.person_id},{'actor_user':other.user},{'company':'D'},{'project':'OTHER'}):
                forged={**envelope(s,dev),**change}
                with self.assertRaises(DomainError):service.stage_capture('C','P',uid(),forged)
            self.assertFalse(any(dt in f.KINDS.values() for dt,_ in s.native))
    def test_project_duty_identity_and_content_right_revocation_block_new_effects(self):
        for revoke in ('write','project','identity','read','ingest'):
            with self.subTest(revoke=revoke),fixture() as (s,f,fr,field,repo,records,service):
                dev,e,staged=stage(s,service);before=deepcopy((s.native,s.receipts))
                if revoke=='write':s.duties[s.actor.person_id]={'project.read','field.read','document.read'}
                elif revoke=='project':s.duties[s.actor.person_id]=set()
                elif revoke=='identity':s.users.pop(s.actor.user)
                else:
                    revision=e['command']['quantities'][0]['sources'][0]['revision_id'];s.rights[s.documents[revision]['document_id']]=revoke+'_denied'
                with self.assertRaises(DomainError):apply(service,e,staged)
                self.assertEqual((s.native,s.receipts),before)
    def test_device_revocation_blocks_drafts_but_not_current_authorized_original_receipt(self):
        with fixture() as (s,f,fr,field,repo,records,service):
            dev,e,staged=stage(s,service);committed=apply(service,e,staged)
            service.revoke_device('C','P',uid(),dev['device']['device_id'],dev['device_version'],'Lost device; revoke future use.')
            self.assertTrue(apply(service,e,staged)['replayed'])
            with self.assertRaises(DomainError):service.stage_capture('C','P',uid(),envelope(s,dev))
        with fixture() as (s,f,fr,field,repo,records,service):
            dev,e,staged=stage(s,service);service.revoke_device('C','P',uid(),dev['device']['device_id'],dev['device_version'],'Lost device.')
            with self.assertRaises(DomainError):apply(service,e,staged)
            self.assertFalse(any(dt in f.KINDS.values() for dt,_ in s.native))
    def test_unknown_response_original_receipt_survives_later_revision(self):
        with fixture() as (s,f,fr,field,repo,records,service):
            dev,e,staged=stage(s,service);first=apply(service,e,staged);original=deepcopy(first['original_receipt'])
            oldq=original['quantities'][0];q=quantity(add_source(s),oldq['original_event_id'],oldq['id'])
            field.revise_record('C','P',uid(),'daily',original['header']['id'],digest(original['header']),daily(s),[],[q])
            again=apply(service,e,staged);self.assertEqual(again['original_receipt']['revision'],original['revision'])
            self.assertNotEqual(fr.raw('daily',original['header']['id'])['current_revision'],original['revision']['id'])
    def test_base_conflict_requires_distinct_explicit_replacement_and_no_autoapply(self):
        with fixture() as (s,f,fr,field,repo,records,service):
            dev,e,first_stage=stage(s,service);first=apply(service,e,first_stage)['original_receipt']
            correction=envelope(s,dev);q=quantity(add_source(s),first['quantities'][0]['original_event_id'],first['quantities'][0]['id'])
            correction['command'].update(action='revise',record_id=first['header']['id'],expected_version=digest(first['header']),base_revision_id=first['revision']['id'],base_revision_digest=digest(first['revision']),amendment_reason='',quantities=[q])
            staged=service.stage_capture('C','P',uid(),correction)
            latest=field.revise_record('C','P',uid(),'daily',first['header']['id'],digest(first['header']),daily(s),[],[q])
            self.assertEqual(service.inspect_capture('C','P',correction['capture_id'])['disposition'],'conflict')
            before=deepcopy((s.native,s.receipts))
            with self.assertRaises(DomainError):apply(service,correction,staged)
            self.assertEqual((s.native,s.receipts),before)
            replacement=deepcopy(correction);replacement['capture_id']=uid();replacement['command'].update(expected_version=digest(latest['header']),base_revision_id=latest['revision']['id'],base_revision_digest=digest(latest['revision']))
            replacement['command']['quantities'][0]['supersedes_event_id']=latest['quantities'][0]['id']
            resolved=service.resolve_capture('C','P',uid(),correction['capture_id'],staged['capture_version'],replacement,'Keep explicit current base and corrected source lineage.')
            self.assertEqual(fr.raw('daily',first['header']['id'])['current_revision'],latest['revision']['id'])
            self.assertEqual(service.inspect_capture('C','P',correction['capture_id'])['disposition'],'superseded')
            self.assertEqual(resolved['capture']['replaces_capture_id'],correction['capture_id'])
            s.business_names[replacement['capture_id']]='field.daily.revise.v1'
            result=apply(service,replacement,resolved)
            self.assertEqual(result['original_receipt']['revision']['predecessor'],latest['revision']['id'])
    def test_discard_redacts_only_offline_payload_and_preserves_committed_business_receipt(self):
        with fixture() as (s,f,fr,field,repo,records,service):
            dev,e,staged=stage(s,service);first=apply(service,e,staged);old=deepcopy(first['original_receipt'])
            discarded=service.discard_capture('C','P',uid(),e['capture_id'],first['capture_version'],'Remove the offline copy from this profile.')
            self.assertEqual(discarded['capture']['status'],'committed');self.assertFalse(discarded['capture']['payload_retained'])
            current=service.get_capture('C','P',e['capture_id']);self.assertIsNone(current['envelope']);self.assertEqual(current['original_receipt']['revision'],old['revision'])
            self.assertEqual(fr.raw('daily_revision',old['revision']['id']),old['revision'])
    def test_discard_staged_capture_never_calls_field_writer_and_uuid_cannot_reopen(self):
        with fixture() as (s,f,fr,field,repo,records,service):
            dev,e,staged=stage(s,service)
            discarded=service.discard_capture('C','P',uid(),e['capture_id'],staged['capture_version'],'Discard this unsubmitted capture.')
            self.assertEqual(discarded['capture']['status'],'discarded')
            with self.assertRaises(DomainError):apply(service,e,discarded)
            with self.assertRaises(DomainError):service.stage_capture('C','P',uid(),e)
            original_stage=service.stage_capture('C','P',staged['operation']['id'],e)
            self.assertEqual(original_stage['capture']['status'],'staged')
            self.assertTrue(original_stage['operation']['replayed'])
            self.assertEqual(service.get_capture('C','P',e['capture_id'])['capture']['status'],'discarded')
            self.assertFalse(any(dt in f.KINDS.values() for dt,_ in s.native))
    def test_apply_late_offline_failure_rolls_back_business_receipt_and_field_facts(self):
        with fixture() as (s,f,fr,field,repo,records,service):
            dev,e,staged=stage(s,service);before=deepcopy((s.native,s.events,s.receipts));original=repo.write
            def failing(kind,value,**kw):
                if kind=='capture' and value['status']=='committed':raise RuntimeError('late capture projection failure')
                return original(kind,value,**kw)
            with patch.object(repo,'write',failing),self.assertRaises(RuntimeError):apply(service,e,staged)
            self.assertEqual((s.native,s.events,s.receipts),before)
            self.assertFalse(apply(service,e,staged)['replayed'])
    def test_ticket_sync_is_documentary_and_decimal_sources_unchanged(self):
        with fixture() as (s,f,fr,field,repo,records,service):
            dev,e,staged=stage(s,service,'ticket');result=apply(service,e,staged)['original_receipt']
            self.assertEqual(result['revision']['definition']['lines'][0]['quantity'],'3.25')
            self.assertTrue(all(v is False for v in result['revision']['no_effects'].values()))
    def test_reserved_uuid_mismatched_base_and_canonical_receipt_collision(self):
        with fixture() as (s,f,fr,field,repo,records,service):
            dev=device(s,service);e=envelope(s,dev)
            with self.assertRaises(DomainError):service.stage_capture('C','P',e['capture_id'],e)
            staged=service.stage_capture('C','P',uid(),e)
            with self.assertRaises(DomainError):service.apply_capture('C','P',uid(),e['capture_id'],staged['capture_version'])
            s.receipts[s.actor.person_id,e['capture_id']]=('f'*64,{'unrelated':'original command'})
            with self.assertRaises(DomainError) as error:apply(service,e,staged)
            self.assertEqual(error.exception.code,'operation_conflict')

    def test_source_supersession_conflict_links_fresh_uuid_without_silent_replay(self):
        with fixture() as (s,f,fr,field,repo,records,service):
            dev,e,staged=stage(s,service);revision=e['command']['quantities'][0]['sources'][0]['revision_id']
            s.documents[revision]['is_current']=False
            self.assertEqual(service.inspect_capture('C','P',e['capture_id'])['conflict']['code'],'source_changed')
            with self.assertRaises(DomainError):apply(service,e,staged)
            replacement=deepcopy(e);replacement['capture_id']=uid();replacement['command']['quantities'][0]['sources']=[add_source(s)]
            resolved=service.resolve_capture('C','P',uid(),e['capture_id'],staged['capture_version'],replacement,'Use newly reviewed current source bytes.')
            self.assertFalse(any(dt in f.KINDS.values() for dt,_ in s.native))
            result=apply(service,replacement,resolved)
            self.assertEqual(result['original_receipt']['quantities'][0]['original_event_id'],e['command']['quantities'][0]['original_event_id'])
            old=service.get_capture('C','P',e['capture_id'])
            redacted=service.discard_capture('C','P',uid(),e['capture_id'],old['capture_version'],'Purge the superseded offline copy.')
            self.assertEqual(redacted['capture']['status'],'superseded');self.assertFalse(redacted['capture']['payload_retained'])

    def test_new_stage_receipt_cannot_write_after_rights_revocation(self):
        with fixture() as (s,f,fr,field,repo,records,service):
            dev,e,staged=stage(s,service);revision=e['command']['quantities'][0]['sources'][0]['revision_id']
            s.rights[s.documents[revision]['document_id']]='ingest_denied';before=deepcopy((s.native,s.receipts))
            with self.assertRaises(DomainError):service.stage_capture('C','P',uid(),e)
            self.assertEqual((s.native,s.receipts),before)
            # Metadata-only privacy deletion requires current Project write,
            # reads no denied source, and creates no FLD01/domain fact.
            discarded=service.discard_capture('C','P',uid(),e['capture_id'],staged['capture_version'],'Purge unsubmitted copy after source rights changed.')
            self.assertFalse(discarded['capture']['payload_retained']);self.assertFalse(any(dt in f.KINDS.values() for dt,_ in s.native))

    def test_participant_rebinding_refuses_before_project_or_field_locks(self):
        with fixture() as (s,f,fr,field,repo,records,service):
            dev,e,staged=stage(s,service);replacement=SimpleNamespace(user=s.actor.user,person_id=uid());original_sql=sys.modules['frappe'].db.sql
            def changed(query,args=(),**kwargs):
                result=original_sql(query,args,**kwargs)
                if 'tabCipher Identity Binding' in query:s.users[replacement.user]=replacement
                return result
            with patch.object(sys.modules['frappe'].db,'sql',changed),self.assertRaises(DomainError) as error:apply(service,e,staged)
            self.assertEqual(error.exception.code,'field_identity_changed')
            self.assertFalse(any(dt in f.KINDS.values() for dt,_ in s.native))

    def test_quarantined_execution_and_closed_project_block_drafts_but_receipt_reads_remain_distinct(self):
        with fixture() as (s,f,fr,field,repo,records,service):
            dev,e,staged=stage(s,service);s.effects=False
            with self.assertRaises(DomainError):apply(service,e,staged)
            s.effects=True;first=apply(service,e,staged);s.effects=False;s.project_status='Completed'
            self.assertEqual(apply(service,e,staged)['original_receipt']['revision'],first['original_receipt']['revision'])
            self.assertTrue(apply(service,e,staged)['replayed'])

    def test_staged_superintendent_cannot_silently_become_another_person_before_apply(self):
        with fixture() as (s,f,fr,field,repo,records,service):
            superintendent=add_person(s,'superintendent');dev=device(s,service);e=envelope(s,dev)
            e['command']['definition']['superintendent_user']=superintendent.user
            staged=service.stage_capture('C','P',uid(),e);before=deepcopy((s.native,s.receipts))
            s.users[superintendent.user]=SimpleNamespace(user=superintendent.user,person_id=uid())
            with self.assertRaises(DomainError) as error:apply(service,e,staged)
            self.assertEqual(error.exception.code,'field_identity_changed');self.assertEqual((s.native,s.receipts),before)

if __name__=='__main__':unittest.main()

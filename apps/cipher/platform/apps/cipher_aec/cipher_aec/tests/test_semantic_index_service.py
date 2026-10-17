"""Host state-machine evidence with explicit source/store/provider doubles.

Not native Frappe, actual embeddings, Qdrant ranking, or connected acceptance.
"""
from copy import deepcopy
import hashlib
from types import SimpleNamespace
import unittest
from uuid import uuid4
from cipher_aec.api.contracts import digest
from cipher_aec.api.errors import DomainError
from cipher_aec.semantic_index import contracts as c
from cipher_aec.semantic_index.service import SemanticService
from cipher_aec.semantic_index.configuration import clients,configuration_status

SCOPE={'company':'C','scope_type':'Project','project':'P'}
ACTOR=SimpleNamespace(user='author@example.test',person_id='person-a')
OTHER=SimpleNamespace(user='reader@example.test',person_id='person-b')
SELECTOR={'document_id':'document','revision_id':'revision','source_sha256':'a'*64,
          'selection':'working','adoption_id':None,'adoption_digest':None}

class MemoryStore:
    durable=True
    def __init__(self): self.rows={}; self.checkpoints=[]
    def load(self,key): return deepcopy(self.rows.get(key))
    def save(self,key,expected,value):
        if (self.rows.get(key) or {}).get('version',0)!=expected:
            raise DomainError('semantic_conflict','changed',409)
        self.rows[key]=deepcopy(value); self.checkpoints.append(deepcopy(value))

class Sources:
    def __init__(self,text='Original retained specification. Concrete strength is 4000 psi.'):
        self.text=text; self.revoked=False; self.head='revision'; self.authority='b'*64
        self.allowed={'person-a','person-b'}; self.manage={'person-a'}; self.on_recheck=None
    def authorize(self,scope,actor,manage=False):
        if scope!=SCOPE or actor.person_id not in self.allowed or (manage and actor.person_id not in self.manage):
            raise DomainError('capability_denied','denied',403)
        return digest([self.authority,actor.user,actor.person_id])
    def snapshot(self,scope,selector,actor):
        authority=self.authorize(scope,actor)
        if self.revoked: raise DomainError('source_rights_denied','revoked',403)
        if selector!=SELECTOR or self.head!=selector['revision_id']:
            raise DomainError('semantic_source_changed','superseded',409)
        page={'page':1,'id':'canonical-citation','document_id':selector['document_id'],
              'revision_id':selector['revision_id'],'source_sha256':selector['source_sha256'],
              'excerpt':self.text,'excerpt_sha256':hashlib.sha256(self.text.encode()).hexdigest()}
        token=digest([selector,self.text,'current-rights-graph'])
        return {'scope':deepcopy(scope),'selector':deepcopy(selector),'authority':authority,'token':token,'pages':[page]}
    def recheck(self,scope,selector,token,actor):
        if self.on_recheck: self.on_recheck()
        return self.snapshot(scope,selector,actor)['token']==token

class Embedder:
    identity={'provider':'ollama','protocol':'ollama-embed-v1','model':'pinned:test',
              'model_digest':'sha256:'+'c'*64,'dimensions':3}
    def __init__(self): self.calls=[]; self.after=None; self.error=None
    def embed(self,texts):
        self.calls.append(list(texts))
        if self.error: raise self.error
        if self.after: self.after()
        return [[0.1,0.2,0.3] for _ in texts]

class Index:
    def __init__(self): self.points={}; self.upserts=[]; self.deletes=[]; self.unknown=False; self.after_upsert=None; self.after_query=None; self.extra=[]; self.delete_error=False
    def upsert(self,points):
        self.upserts.append(deepcopy(points)); self.points.update({p['id']:deepcopy(p) for p in points})
        if self.after_upsert: self.after_upsert()
        if self.unknown: self.unknown=False; raise OSError('private endpoint and token')
    def query(self,vector,scope_key,profile_id,generation,limit):
        result=[{'id':p['id'],'payload':deepcopy(p['payload']),'score':0.8} for p in self.points.values()
                if p['payload']['scope_key']==scope_key and p['payload']['profile_id']==profile_id and p['payload']['generation']==generation]
        if self.after_query: self.after_query()
        return (self.extra+result)[:limit]
    def delete(self,ids):
        self.deletes.append(list(ids))
        if self.delete_error: raise DomainError('semantic_unavailable','not available',503)
        for id in ids: self.points.pop(id,None)
    def scroll(self,scope_key,profile_id,offset=None,limit=50):
        return {'points':[{'id':p['id'],'payload':deepcopy(p['payload'])} for p in self.points.values()
                          if p['payload']['scope_key']==scope_key and p['payload']['profile_id']==profile_id][:limit], 'next_offset':None}

def fixture(text=None):
    store=MemoryStore(); source=Sources() if text is None else Sources(text); embedder=Embedder(); index=Index()
    backend=SemanticService(store,source,embedder,index)
    return backend,store,source,embedder,index

def ready(backend):
    operation=str(uuid4()); backend.prepare(SCOPE,[SELECTOR],operation,ACTOR); backend.run(SCOPE,operation,ACTOR)
    return operation

class SemanticGenerationTests(unittest.TestCase):
    def test_real_generation_metadata_only_and_current_canonical_query_for_another_reader(self):
        backend,store,source,embedder,index=fixture(); operation=ready(backend)
        self.assertEqual(backend.status(SCOPE,operation,ACTOR)['status'],'active')
        point=next(iter(index.points.values()))
        self.assertEqual(set(point['payload']),c.PAYLOAD_FIELDS)
        self.assertNotIn(source.text,str(store.rows)); self.assertNotIn('excerpt',point['payload'])
        answer=backend.query(SCOPE,'Concrete strength?',OTHER)
        self.assertEqual(answer['results'][0]['excerpt'],source.text)
        self.assertEqual(answer['results'][0]['citation']['id'],'canonical-citation')
        self.assertFalse(answer['connected_qualification'])
    def test_unknown_upsert_reply_replays_same_point_ids_and_activates_only_after_ack(self):
        backend,store,source,embedder,index=fixture(); operation=str(uuid4())
        backend.prepare(SCOPE,[SELECTOR],operation,ACTOR); index.unknown=True
        with self.assertRaises(DomainError) as error: backend.run(SCOPE,operation,ACTOR)
        self.assertEqual(error.exception.code,'semantic_unavailable'); self.assertNotIn('private',str(error.exception))
        self.assertEqual(backend.status(SCOPE,operation,ACTOR)['status'],'retryable')
        with self.assertRaises(DomainError): backend.query(SCOPE,'Question',ACTOR)
        # A new service using retained checkpoints simulates process restart.
        restored=SemanticService(store,source,embedder,index); restored.run(SCOPE,operation,ACTOR)
        self.assertEqual([p['id'] for p in index.upserts[0]],[p['id'] for p in index.upserts[1]])
        self.assertEqual(len(index.points),1)
    def test_revocation_during_embedding_prevents_any_upsert_and_rejects_generation(self):
        backend,store,source,embedder,index=fixture(); operation=str(uuid4())
        backend.prepare(SCOPE,[SELECTOR],operation,ACTOR); embedder.after=lambda:setattr(source,'revoked',True)
        with self.assertRaises(DomainError): backend.run(SCOPE,operation,ACTOR)
        self.assertEqual(index.upserts,[]); self.assertEqual(backend.status(SCOPE,operation,ACTOR)['status'],'rejected')
    def test_revocation_after_upsert_never_activates_and_reconciliation_deletes(self):
        backend,store,source,embedder,index=fixture(); operation=str(uuid4())
        backend.prepare(SCOPE,[SELECTOR],operation,ACTOR); index.after_upsert=lambda:setattr(source,'revoked',True)
        with self.assertRaises(DomainError): backend.run(SCOPE,operation,ACTOR)
        self.assertTrue(index.points); result=backend.reconcile(SCOPE,ACTOR)
        self.assertEqual(result['deleted_points'],1); self.assertFalse(index.points)
    def test_query_revocation_during_provider_search_returns_no_text(self):
        backend,store,source,embedder,index=fixture(); ready(backend)
        index.after_query=lambda:setattr(source,'revoked',True)
        self.assertEqual(backend.query(SCOPE,'Question',OTHER)['results'],[])
    def test_query_revocation_on_final_recheck_returns_no_text(self):
        backend,store,source,embedder,index=fixture(); ready(backend)
        source.on_recheck=lambda:setattr(source,'revoked',True)
        self.assertEqual(backend.query(SCOPE,'Question',OTHER)['results'],[])
    def test_scope_authority_change_during_embedding_refuses(self):
        backend,store,source,embedder,index=fixture(); ready(backend)
        embedder.after=lambda:setattr(source,'authority','d'*64)
        with self.assertRaises(DomainError) as error: backend.query(SCOPE,'Question',OTHER)
        self.assertEqual(error.exception.code,'semantic_authority_changed')
    def test_superseded_working_revision_is_unsearchable_and_delete_failure_is_recoverable(self):
        backend,store,source,embedder,index=fixture(); operation=ready(backend); source.head='new-revision'
        self.assertEqual(backend.query(SCOPE,'Question',ACTOR)['results'],[])
        index.delete_error=True
        with self.assertRaises(DomainError): backend.reconcile(SCOPE,ACTOR)
        self.assertEqual(backend.status(SCOPE,operation,ACTOR)['status'],'retired')
        self.assertTrue(index.points); index.delete_error=False
        backend.reconcile(SCOPE,ACTOR); self.assertFalse(index.points)
        self.assertEqual(index.deletes[0],index.deletes[1])
    def test_exact_ledger_join_refuses_forged_cross_scope_unknown_or_duplicate_hits(self):
        backend,store,source,embedder,index=fixture(); ready(backend)
        point=next(iter(index.points.values())); forged=deepcopy(point['payload']); forged['scope_key']='f'*64
        index.extra=[{'id':point['id'],'payload':forged,'score':1},
                     {'id':str(uuid4()),'payload':point['payload'],'score':1}]
        self.assertEqual(len(backend.query(SCOPE,'Question',ACTOR)['results']),1)
        index.extra=[{'id':point['id'],'payload':point['payload'],'score':1}]*2
        self.assertEqual(len(backend.query(SCOPE,'Question',ACTOR)['results']),1)
    def test_changed_canonical_text_with_same_index_hashes_is_refused(self):
        backend,store,source,embedder,index=fixture(); ready(backend); source.text='Changed plaintext'
        self.assertEqual(backend.query(SCOPE,'Question',ACTOR)['results'],[])
    def test_new_generation_retires_original_without_rewriting_original_ids(self):
        backend,store,source,embedder,index=fixture(); first=ready(backend); old=set(index.points); second=ready(backend)
        self.assertEqual(backend.status(SCOPE,first,ACTOR)['status'],'retired')
        self.assertTrue(old.issubset(index.points)); self.assertNotEqual(backend.status(SCOPE,first,ACTOR)['generation'],backend.status(SCOPE,second,ACTOR)['generation'])
        backend.reconcile(SCOPE,ACTOR); self.assertFalse(old.intersection(index.points))
        self.assertEqual(len(backend.query(SCOPE,'Question',OTHER)['results']),1)
    def test_cancel_then_late_orphan_write_is_not_readable_and_sweep_removes_it(self):
        backend,store,source,embedder,index=fixture(); operation=ready(backend); point=deepcopy(next(iter(index.points.values())))
        backend.cancel(SCOPE,operation,ACTOR); backend.reconcile(SCOPE,ACTOR)
        index.points[point['id']]=point  # stale network completion after cleanup
        with self.assertRaises(DomainError): backend.query(SCOPE,'Question',ACTOR)
        self.assertEqual(backend.reconcile(SCOPE,ACTOR)['deleted_points'],1); self.assertFalse(index.points)
    def test_prepare_replay_conflict_busy_and_original_person_recovery(self):
        backend,store,source,embedder,index=fixture(); operation=str(uuid4())
        first=backend.prepare(SCOPE,[SELECTOR],operation,ACTOR)
        self.assertTrue(backend.prepare(SCOPE,[SELECTOR],operation,ACTOR)['replayed'])
        altered={**SELECTOR,'revision_id':'other'}
        with self.assertRaises(DomainError) as error: backend.prepare(SCOPE,[altered],operation,ACTOR)
        self.assertEqual(error.exception.code,'semantic_operation_conflict')
        with self.assertRaises(DomainError): backend.prepare(SCOPE,[SELECTOR],str(uuid4()),ACTOR)
        source.manage.add(OTHER.person_id)
        with self.assertRaises(DomainError) as error: backend.run(SCOPE,operation,OTHER)
        self.assertEqual(error.exception.code,'semantic_job_actor'); self.assertFalse(index.upserts)
    def test_provider_unavailable_retains_checkpoint_without_fallback(self):
        backend,store,source,embedder,index=fixture(); operation=str(uuid4()); backend.prepare(SCOPE,[SELECTOR],operation,ACTOR)
        embedder.error=DomainError('semantic_unavailable','Provider unavailable',503)
        with self.assertRaises(DomainError): backend.run(SCOPE,operation,ACTOR)
        self.assertEqual(backend.status(SCOPE,operation,ACTOR)['indexed_chunks'],0); self.assertFalse(index.points)
    def test_chunk_boundaries_unicode_and_batch_limits_are_deterministic(self):
        backend,store,source,embedder,index=fixture('Concrete 界😀 '*2000); operation=ready(backend)
        self.assertGreater(len(index.points),16); self.assertTrue(all(len(b)<=16 for b in embedder.calls))
        for point in index.points.values(): self.assertEqual(set(point['payload']),c.PAYLOAD_FIELDS)
        result=backend.query(SCOPE,'Question',ACTOR,limit=16)['results']
        self.assertTrue(all(len(r['excerpt'])<=1024 for r in result))
        self.assertEqual(backend.status(SCOPE,operation,ACTOR)['indexed_chunks'],len(index.points))
    def test_closed_scope_selector_query_and_capacity_refusals_have_no_provider_calls(self):
        backend,store,source,embedder,index=fixture()
        for scope in [{**SCOPE,'project':None},{**SCOPE,'scope_type':'Company'},{**SCOPE,'extra':True}]:
            with self.assertRaises(DomainError): backend.prepare(scope,[SELECTOR],str(uuid4()),ACTOR)
        for sources in [[],[SELECTOR]*17,[{**SELECTOR,'url':'http://bad'}]]:
            with self.assertRaises(DomainError): backend.prepare(SCOPE,sources,str(uuid4()),ACTOR)
        self.assertFalse(embedder.calls); self.assertFalse(index.upserts)
        for question,limit in [('',8),('x'*4001,8),('question',True),('question',17)]:
            with self.assertRaises(DomainError): backend.query(SCOPE,question,ACTOR,limit=limit)
    def test_request_store_cannot_run_external_writes(self):
        backend,store,source,embedder,index=fixture(); operation=str(uuid4()); backend.prepare(SCOPE,[SELECTOR],operation,ACTOR); store.durable=False
        with self.assertRaises(DomainError): backend.run(SCOPE,operation,ACTOR)
        with self.assertRaises(DomainError): backend.reconcile(SCOPE,ACTOR)
        self.assertFalse(embedder.calls); self.assertFalse(index.upserts)
    def test_lease_blocks_parallel_worker_then_expired_same_ids_can_resume(self):
        backend,store,source,embedder,index=fixture(); operation=str(uuid4()); backend.prepare(SCOPE,[SELECTOR],operation,ACTOR)
        key=next(iter(store.rows)); job=store.rows[key]['jobs'][operation]; job.update(status='running',lease=str(uuid4()),lease_until=200)
        backend.clock=lambda:100
        with self.assertRaises(DomainError): backend.run(SCOPE,operation,ACTOR)
        backend.clock=lambda:201; backend.run(SCOPE,operation,ACTOR)
        self.assertEqual(backend.status(SCOPE,operation,ACTOR)['status'],'active')

    def test_parallel_cleanup_cannot_skip_a_batch_or_mark_undeleted_points_deleted(self):
        backend,store,source,embedder,index=fixture('bounded concrete source '*9000)
        operation=ready(backend); backend.cancel(SCOPE,operation,ACTOR)
        original=index.delete; nested=[False]
        def racing_delete(ids):
            if not nested[0]:
                nested[0]=True
                backend.reconcile(SCOPE,ACTOR)
            original(ids)
        index.delete=racing_delete
        with self.assertRaises(DomainError) as error: backend.reconcile(SCOPE,ACTOR)
        self.assertEqual(error.exception.code,'semantic_conflict')
        state=next(iter(store.rows.values())); job=state['jobs'][operation]
        self.assertEqual(job['cleanup_next'],100); self.assertNotEqual(job['status'],'deleted')
        self.assertEqual(len(index.points),job['chunk_count']-100)
        while index.points: backend.reconcile(SCOPE,ACTOR)
        self.assertEqual(backend.status(SCOPE,operation,ACTOR)['status'],'deleted')

    def test_stale_scroll_payload_does_not_delete_a_live_ledger_point(self):
        backend,store,source,embedder,index=fixture(); ready(backend)
        point=deepcopy(next(iter(index.points.values()))); point['payload']['chunk_sha256']='f'*64
        index.scroll=lambda *args,**kwargs:{'points':[{'id':point['id'],'payload':point['payload']}],'next_offset':None}
        result=backend.reconcile(SCOPE,ACTOR)
        self.assertEqual(result['deleted_points'],0); self.assertTrue(index.points)

    def test_authority_change_during_final_source_check_still_refuses_query(self):
        backend,store,source,embedder,index=fixture(); ready(backend)
        source.on_recheck=lambda:setattr(source,'authority','d'*64)
        with self.assertRaises(DomainError) as error: backend.query(SCOPE,'Question',OTHER)
        self.assertEqual(error.exception.code,'semantic_authority_changed')

    def test_persisted_token_payload_and_active_state_drift_fail_closed(self):
        backend,store,source,embedder,index=fixture(); operation=ready(backend)
        key=next(iter(store.rows)); original=deepcopy(store.rows[key])
        changes=[lambda v:v['jobs'][operation].update(source_tokens=[]),
                 lambda v:v.update(active_generation=None),
                 lambda v:v['jobs'][operation]['chunks'][0]['payload'].update(profile_id='e'*64),
                 lambda v:v['jobs'][operation]['chunks'][0].update(end=999999),
                 lambda v:v['jobs'][operation].update(next_chunk=0)]
        for change in changes:
            with self.subTest(change=change):
                value=deepcopy(original); change(value); store.rows[key]=value
                with self.assertRaises(DomainError) as error: backend.query(SCOPE,'Question',OTHER)
                self.assertEqual(error.exception.code,'semantic_integrity')
        store.rows[key]=original
        self.assertTrue(backend.query(SCOPE,'Question',OTHER)['results'])

class ConfigurationTests(unittest.TestCase):
    def test_disabled_and_incomplete_configuration_truthfully_unavailable_without_defaults(self):
        for config in [None,{}, {'enabled':False},{'enabled':True}, {'enabled':True,'dimensions':768}]:
            self.assertEqual(configuration_status(config),{'status':'unavailable','connected_qualification':False})
            with self.assertRaises(DomainError): clients(config)
        self.assertEqual(configuration_status({'enabled':True,'model_digest':'guess'} )['status'],'unavailable')

if __name__=='__main__': unittest.main()

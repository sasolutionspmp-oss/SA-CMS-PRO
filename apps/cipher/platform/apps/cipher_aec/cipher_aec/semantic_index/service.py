"""Bounded generation rebuilds and canonical-source search.

The vector store is an untrusted candidate index. No snippet is stored there,
and no hit reaches callers without current canonical source authorization.
"""
from copy import deepcopy
import math
import time
import uuid
from cipher_aec.api.contracts import digest
from cipher_aec.api.errors import DomainError
from . import contracts as c

LEASE_SECONDS=120

class SemanticService:
    def __init__(self,store,sources,embedder,index,*,clock=time.time):
        self.store,self.sources,self.embedder,self.index=store,sources,embedder,index
        self.clock=clock
        self.profile=c.profile(embedder.identity)
        self.profile_id=digest(self.profile)

    def _keys(self,scope):
        scope=c.scope(scope)
        return scope,digest(scope),c.corpus_key(scope,self.profile_id)

    def _load(self,key,scope):
        value=self.store.load(key)
        if value is not None:
            try: c.checkpoint(value)
            except (DomainError,TypeError,KeyError,ValueError,OverflowError):
                raise DomainError('semantic_integrity','The semantic checkpoint cannot be verified.',409) from None
        if value is not None and (value['scope']!=scope or value['profile']!=self.profile or value['profile_id']!=self.profile_id):
            raise DomainError('semantic_integrity','The semantic checkpoint belongs to another profile.',409)
        return value

    def _save(self,key,value,expected):
        value['version']=expected+1
        self.store.save(key,expected,value)
        return value

    @staticmethod
    def _person(actor): return {'user':actor.user,'person_id':actor.person_id}

    def _snapshots(self,scope,selectors,actor,tokens=None):
        snapshots=[]
        for i,selector in enumerate(selectors):
            snapshot=self.sources.snapshot(scope,selector,actor)
            if snapshot['selector']!=selector or snapshot['scope']!=scope or (tokens is not None and snapshot['token']!=tokens[i]):
                raise DomainError('semantic_source_changed','A source changed. Prepare a new index generation.',409)
            c.sha(snapshot['token']); snapshots.append(snapshot)
        return snapshots

    def _recheck(self,scope,job,actor,authority):
        if self.sources.authorize(scope,actor,manage=True)!=authority:
            raise DomainError('semantic_authority_changed','Your current duties changed. Refresh this job.',403)
        for selected,token in zip(job['selectors'],job['source_tokens']):
            if not self.sources.recheck(scope,selected,token,actor):
                raise DomainError('semantic_source_changed','A source changed. Prepare a new index generation.',409)

    def prepare(self,scope,selectors,operation_id,actor):
        scope,scope_key,key=self._keys(scope); c.uid(operation_id)
        authority=self.sources.authorize(scope,actor,manage=True)
        if not isinstance(selectors,list) or not 1<=len(selectors)<=c.MAX_SOURCES: c.invalid()
        selectors=[c.selector(s) for s in selectors]
        if len({digest(s) for s in selectors})!=len(selectors): c.invalid()
        request=digest({'scope':scope,'selectors':selectors,'profile':self.profile,'actor':self._person(actor)})
        value=self._load(key,scope)
        if value and operation_id in value['jobs']:
            job=value['jobs'][operation_id]
            if job['request_digest']!=request:
                raise DomainError('semantic_operation_conflict','This operation ID already belongs to another rebuild.',409)
            # Current authorization precedes historical receipt/status access.
            self._snapshots(scope,selectors,actor)
            return self._summary(job,replayed=True)
        if value and any(j['status'] in ('pending','running','retryable') for j in value['jobs'].values()):
            raise DomainError('semantic_busy','Resume or cancel the existing rebuild first.',409)
        if value and len(value['jobs'])>=c.MAX_JOBS:
            raise DomainError('semantic_capacity','This bounded corpus requires archival before more rebuilds.',409)
        snapshots=self._snapshots(scope,selectors,actor)
        generation=str(uuid.uuid5(uuid.UUID(operation_id),digest([scope,self.profile_id,self._person(actor)])))
        chunks=[]
        for i,snapshot in enumerate(snapshots): chunks.extend(c.chunks(snapshot,scope_key,self.profile_id,generation,i))
        if not chunks or len(chunks)>c.MAX_CHUNKS:
            raise DomainError('semantic_capacity','Choose sources with 1 to 1024 extracted chunks.',422)
        job={'id':operation_id,'generation':generation,'request_digest':request,'actor':self._person(actor),
             'selectors':selectors,'source_tokens':[s['token'] for s in snapshots],
             'chunks':chunks,'chunk_count':len(chunks),'next_chunk':0,'cleanup_next':0,
             'status':'pending','lease':None,'lease_until':0,'error_code':None}
        self._recheck(scope,job,actor,authority)
        expected=value['version'] if value else 0
        value=value or {'scope':scope,'profile_id':self.profile_id,'profile':self.profile,'version':0,'active_generation':None,'jobs':{}}
        value['jobs'][operation_id]=job
        self._save(key,value,expected)
        return self._summary(job)

    @staticmethod
    def _summary(job,*,replayed=False):
        return {'operation_id':job['id'],'generation':job['generation'],'status':job['status'],
                'chunks':job['chunk_count'],'indexed_chunks':job['next_chunk'],
                'error_code':job['error_code'],'replayed':replayed,
                'connected_qualification':False}

    def status(self,scope,operation_id,actor):
        scope,_,key=self._keys(scope); c.uid(operation_id)
        self.sources.authorize(scope,actor)
        value=self._load(key,scope)
        if not value or operation_id not in value['jobs']:
            raise DomainError('not_found','This semantic job is not available.',404)
        job=value['jobs'][operation_id]
        self._snapshots(scope,job['selectors'],actor)
        return self._summary(job)

    def _durable(self):
        if not self.store.durable:
            raise DomainError('semantic_worker_required','Run provider work in the dedicated checkpointing worker.',409)

    def _owned(self,key,scope,operation_id,lease):
        value=self._load(key,scope); job=value['jobs'][operation_id]
        if job['lease']!=lease or job['status']!='running' or job['lease_until']<=self.clock():
            raise DomainError('semantic_lease_lost','Another worker owns this semantic job.',409)
        return value,job

    def run(self,scope,operation_id,actor):
        """Resume stable point IDs after a crash or unknown provider reply."""
        self._durable(); scope,_,key=self._keys(scope); c.uid(operation_id)
        authority=self.sources.authorize(scope,actor,manage=True)
        value=self._load(key,scope)
        if not value or operation_id not in value['jobs']:
            raise DomainError('not_found','This semantic job is not available.',404)
        job=value['jobs'][operation_id]
        if job['actor']!=self._person(actor):
            raise DomainError('semantic_job_actor','Only the original current person can resume this job.',403)
        if job['status'] not in ('pending','retryable','running'): return self._summary(job)
        if job['status']=='running' and job['lease_until']>self.clock():
            raise DomainError('semantic_busy','This semantic job is already running.',409)
        expected=value['version']; lease=str(uuid.uuid4())
        job.update(status='running',lease=lease,lease_until=self.clock()+LEASE_SECONDS,error_code=None)
        self._save(key,value,expected)  # persisted before any external write
        try:
            snapshots=self._snapshots(scope,job['selectors'],actor,job['source_tokens'])
            while job['next_chunk']<job['chunk_count']:
                self._recheck(scope,job,actor,authority)
                value,job=self._owned(key,scope,operation_id,lease)
                batch=job['chunks'][job['next_chunk']:job['next_chunk']+c.BATCH_SIZE]
                texts=[c.canonical_chunk(snapshots[p['source_index']],p)[0] for p in batch]
                vectors=self.embedder.embed(texts)
                if len(vectors)!=len(batch):
                    raise DomainError('semantic_protocol_error','The embedding response does not match the batch.',503)
                self._recheck(scope,job,actor,authority)
                self._owned(key,scope,operation_id,lease)
                self.index.upsert([{'id':p['id'],'vector':vector,'payload':p['payload']} for p,vector in zip(batch,vectors)])
                # Acknowledgment alone never activates a generation.
                self._recheck(scope,job,actor,authority)
                value,job=self._owned(key,scope,operation_id,lease); expected=value['version']
                job['next_chunk']+=len(batch); job['lease_until']=self.clock()+LEASE_SECONDS
                self._save(key,value,expected)
            self._recheck(scope,job,actor,authority)
            value,job=self._owned(key,scope,operation_id,lease); expected=value['version']
            for old in value['jobs'].values():
                if old['status']=='active': old.update(status='retired',cleanup_next=0)
            value['active_generation']=job['generation']
            job.update(status='active',lease=None,lease_until=0)
            self._save(key,value,expected)
            return self._summary(job)
        except Exception as error:
            # A stale worker must never overwrite its successor's checkpoint.
            value=self._load(key,scope); current=value['jobs'][operation_id]
            if current['lease']==lease and current['status']=='running':
                expected=value['version']
                code=error.code if isinstance(error,DomainError) else 'semantic_unavailable'
                retryable=code in ('semantic_unavailable','semantic_protocol_error','semantic_lease_lost')
                current.update(status='retryable' if retryable else 'rejected',error_code=code,lease=None,lease_until=0)
                self._save(key,value,expected)
            if isinstance(error,DomainError): raise
            raise DomainError('semantic_unavailable','The semantic provider is unavailable. Resume the saved job later.',503) from None

    def cancel(self,scope,operation_id,actor):
        scope,_,key=self._keys(scope); c.uid(operation_id)
        self.sources.authorize(scope,actor,manage=True)
        value=self._load(key,scope)
        if not value or operation_id not in value['jobs']:
            raise DomainError('not_found','This semantic job is not available.',404)
        expected=value['version']; job=value['jobs'][operation_id]
        self._snapshots(scope,job['selectors'],actor)
        if job['status']!='deleted': job.update(status='cancelled',lease=None,lease_until=0)
        if value['active_generation']==job['generation']: value['active_generation']=None
        self._save(key,value,expected)
        return self._summary(job)

    def query(self,scope,question,actor,*,limit=8):
        scope,scope_key,key=self._keys(scope)
        if not isinstance(question,str) or not question.strip() or len(question)>4000 or '\x00' in question or type(limit) is not int or not 1<=limit<=16: c.invalid()
        authority=self.sources.authorize(scope,actor)
        value=self._load(key,scope)
        active=next((j for j in (value or {}).get('jobs',{}).values() if j['status']=='active' and j['generation']==value['active_generation']),None)
        if not active:
            raise DomainError('semantic_not_ready','This scope has no active semantic index.',503)
        generation=active['generation']
        vector=self.embedder.embed([question])[0]
        if self.sources.authorize(scope,actor)!=authority:
            raise DomainError('semantic_authority_changed','Your current duties changed. Search again.',403)
        hits=self.index.query(vector,scope_key,self.profile_id,generation,min(100,limit*4))
        if not isinstance(hits,list) or len(hits)>min(100,limit*4):
            raise DomainError('semantic_protocol_error','The vector search response is invalid.',503)
        ledger={p['id']:p for p in active['chunks']}; snapshots={}; rejected=set(); result=[]; seen=set()
        for hit in hits:
            if not isinstance(hit,dict) or set(hit)!={'id','payload','score'} or type(hit['score']) not in (int,float) or not math.isfinite(hit['score']):
                raise DomainError('semantic_protocol_error','The vector search response is invalid.',503)
            point=ledger.get(hit['id'])
            if not point or hit['id'] in seen or hit['payload']!=point['payload']: continue
            seen.add(hit['id']); i=point['source_index']
            if i in rejected: continue
            if i not in snapshots:
                try:
                    snapshots[i]=self.sources.snapshot(scope,active['selectors'][i],actor)
                    if snapshots[i]['scope']!=scope or snapshots[i]['selector']!=active['selectors'][i] or snapshots[i]['token']!=active['source_tokens'][i]: rejected.add(i); continue
                except DomainError: rejected.add(i); continue
            text,page=c.canonical_chunk(snapshots[i],point)
            result.append({'id':point['id'],'score':hit['score'],'excerpt':text,
                           'chunk_sha256':point['payload']['chunk_sha256'],'start':point['start'],'end':point['end'],
                           'citation':{k:v for k,v in page.items() if k not in ('excerpt','citation')},
                           'source':active['selectors'][i]})
            if len(result)>=limit: break
        # Recheck after all provider calls and all source reads; no cached grant.
        current=self._load(key,scope)
        if not current or current['active_generation']!=generation:
            raise DomainError('semantic_source_changed','The active index changed. Search again.',409)
        if self.sources.authorize(scope,actor)!=authority:
            raise DomainError('semantic_authority_changed','Your current duties changed. Search again.',403)
        allowed=set()
        for i,snapshot in snapshots.items():
            if i in rejected: continue
            try:
                if self.sources.recheck(scope,active['selectors'][i],snapshot['token'],actor): allowed.add(digest(active['selectors'][i]))
            except DomainError: pass
        result=[r for r in result if digest(r['source']) in allowed]
        if self.sources.authorize(scope,actor)!=authority:
            raise DomainError('semantic_authority_changed','Your current duties changed. Search again.',403)
        if self._load(key,scope)['active_generation']!=generation:
            raise DomainError('semantic_source_changed','The active index changed. Search again.',409)
        return {'status':'ready','generation':generation,'profile_id':self.profile_id,
                'results':result,'connected_qualification':False}

    def reconcile(self,scope,actor,*,offset=None):
        """One bounded sweep: revoke stale generations, delete <=100 known IDs,
        then scan <=50 hints for orphan cleanup. Cursor is explicit and scoped.
        A failed delete retains metadata so the same exact IDs can be retried.
        """
        self._durable(); scope,scope_key,key=self._keys(scope)
        authority=self.sources.authorize(scope,actor,manage=True)
        if offset is not None: c.uid(offset)
        value=self._load(key,scope)
        if not value: return {'deleted_points':0,'next_offset':None,'status':'empty'}
        active=next((j for j in value['jobs'].values() if j['status']=='active'),None)
        if active:
            try: self._snapshots(scope,active['selectors'],actor,active['source_tokens'])
            except DomainError:
                expected=value['version']; active.update(status='retired',cleanup_next=0)
                value['active_generation']=None; self._save(key,value,expected)
        if self.sources.authorize(scope,actor,manage=True)!=authority:
            raise DomainError('semantic_authority_changed','Your current duties changed. Resume reconciliation.',403)
        deleted=0
        for operation_id in list(value['jobs']):
            value=self._load(key,scope); job=value['jobs'][operation_id]
            if job['status'] not in ('retired','rejected','cancelled'): continue
            ids=[p['id'] for p in job['chunks'][job['cleanup_next']:job['cleanup_next']+100-deleted]]
            if ids:
                captured_next=job['cleanup_next']
                self.index.delete(ids)  # unknown reply: checkpoint unchanged, retry exact IDs
                latest=self._load(key,scope)
                if latest['jobs'][operation_id]['status'] not in ('retired','rejected','cancelled'):
                    raise DomainError('semantic_conflict','The cleanup job changed.',409)
                expected=latest['version']; target=latest['jobs'][operation_id]
                if target['cleanup_next']!=captured_next:
                    raise DomainError('semantic_conflict','Another reconciler advanced this cleanup batch. Resume it.',409)
                target['cleanup_next']+=len(ids); deleted+=len(ids)
                if target['cleanup_next']>=target['chunk_count']:
                    target.update(status='deleted',chunks=[],lease=None,lease_until=0)
                self._save(key,latest,expected)
            if deleted>=100: return {'deleted_points':deleted,'next_offset':offset,'status':'more'}
        if self.sources.authorize(scope,actor,manage=True)!=authority:
            raise DomainError('semantic_authority_changed','Your current duties changed. Resume reconciliation.',403)
        scan=self.index.scroll(scope_key,self.profile_id,offset=offset,limit=50)
        if not isinstance(scan,dict) or set(scan)!={'points','next_offset'} or not isinstance(scan['points'],list) or len(scan['points'])>50:
            raise DomainError('semantic_protocol_error','The vector reconciliation response is invalid.',503)
        if scan['next_offset'] is not None: c.uid(scan['next_offset'])
        current=self._load(key,scope)
        # Keep staging/retryable IDs too: an active worker may still upsert them.
        keep={p['id']:p['payload'] for j in current['jobs'].values() if j['status'] in ('active','pending','running','retryable') for p in j['chunks']}
        orphan=[]
        for point in scan['points']:
            if not isinstance(point,dict) or set(point)!={'id','payload'}: c.invalid()
            c.uid(point['id']); payload=point['payload']
            if not isinstance(payload,dict) or set(payload)!=c.PAYLOAD_FIELDS or payload['scope_key']!=scope_key or payload['profile_id']!=self.profile_id:
                raise DomainError('semantic_protocol_error','The reconciliation scope differs.',503)
            # A concurrent worker may have corrected a stale provider payload.
            # Never delete an ID owned by a live generation based on that hint.
            if point['id'] not in keep: orphan.append(point['id'])
        if orphan:
            if self.sources.authorize(scope,actor,manage=True)!=authority:
                raise DomainError('semantic_authority_changed','Your current duties changed. Resume reconciliation.',403)
            self.index.delete(orphan); deleted+=len(orphan)
        return {'deleted_points':deleted,'next_offset':scan['next_offset'],
                'status':'more' if scan['next_offset'] else 'complete'}

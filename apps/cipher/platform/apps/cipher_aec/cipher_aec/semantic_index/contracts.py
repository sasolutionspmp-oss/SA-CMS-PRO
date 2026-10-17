"""Closed, bounded DOC-04 contracts; no provider is enabled by these defaults."""
import hashlib
import math
import re
import uuid
from cipher_aec.api.contracts import canonical_json, digest
from cipher_aec.api.errors import DomainError

MAX_SOURCES = 16
MAX_CHUNKS = 1024
MAX_JOBS = 32
CHUNK_CHARACTERS = 1024
CHUNK_OVERLAP = 128
BATCH_SIZE = 16
PAYLOAD_FIELDS = frozenset({'scope_key','profile_id','generation','document_id','revision_id',
                            'source_sha256','chunk_id','page','excerpt_sha256','chunk_sha256'})

def invalid():
    raise DomainError('semantic_invalid_input', 'Use the exact bounded semantic search contract.', 422)

def closed(value, keys):
    if not isinstance(value, dict) or set(value) != set(keys): invalid()
    return value

def identifier(value):
    if not isinstance(value, str) or not value or value.strip() != value or len(value)>140 or '\x00' in value: invalid()
    return value

def sha(value):
    if not isinstance(value,str) or not re.fullmatch('[0-9a-f]{64}',value): invalid()
    return value

def uid(value):
    try:
        if not isinstance(value,str) or str(uuid.UUID(value)) != value: invalid()
    except (ValueError,AttributeError): invalid()
    return value

def scope(value):
    closed(value, {'company','scope_type','project'})
    identifier(value['company'])
    if value['scope_type']=='Project': identifier(value['project'])
    elif value['scope_type']!='Company' or value['project'] is not None: invalid()
    return dict(value)

def selector(value):
    closed(value, {'document_id','revision_id','source_sha256','selection','adoption_id','adoption_digest'})
    identifier(value['document_id']); identifier(value['revision_id']); sha(value['source_sha256'])
    if value['selection']=='adopted': uid(value['adoption_id']); sha(value['adoption_digest'])
    elif value['selection'] not in ('working','issued') or value['adoption_id'] is not None or value['adoption_digest'] is not None: invalid()
    return dict(value)

def identity(value):
    closed(value, {'provider','protocol','model','model_digest','dimensions'})
    if value['provider']!='ollama' or value['protocol']!='ollama-embed-v1': invalid()
    if not isinstance(value['model'],str) or not 1<=len(value['model'])<=256 or any(ord(char)<33 or ord(char)==127 for char in value['model']): invalid()
    if not isinstance(value['model_digest'],str) or not value['model_digest'].startswith('sha256:'): invalid()
    sha(value['model_digest'][7:])
    if type(value['dimensions']) is not int or not 1<=value['dimensions']<=8192: invalid()
    return dict(value)

def profile(value):
    return {'embedding':identity(value),'chunk_policy':'unicode-codepoints-v1',
            'chunk_characters':CHUNK_CHARACTERS,'chunk_overlap':CHUNK_OVERLAP}

def corpus_key(source_scope, profile_id):
    return digest({'scope':scope(source_scope),'profile_id':sha(profile_id)})

def chunks(snapshot, scope_key, profile_id, generation, source_index):
    """Metadata only. Text is reconstructed from a fresh canonical page at use."""
    result=[]
    selected=snapshot['selector']
    for page in snapshot['pages']:
        content=page['excerpt']
        if not isinstance(content,str) or not content: continue
        if type(page['page']) is not int or page['page']<1 or hashlib.sha256(content.encode()).hexdigest()!=page['excerpt_sha256']: invalid()
        for start in range(0,len(content),CHUNK_CHARACTERS-CHUNK_OVERLAP):
            end=min(start+CHUNK_CHARACTERS,len(content))
            text=content[start:end]
            if not text.strip():
                if end==len(content): break
                continue
            chunk_id=digest({'page':page['page'],'start':start,'end':end,'sha256':hashlib.sha256(text.encode()).hexdigest()})
            point_id=str(uuid.uuid5(uuid.UUID(generation),canonical_json([source_index,selected,chunk_id])))
            payload={'scope_key':scope_key,'profile_id':profile_id,'generation':generation,
                     'document_id':selected['document_id'],'revision_id':selected['revision_id'],
                     'source_sha256':selected['source_sha256'],'chunk_id':chunk_id,'page':page['page'],
                     'excerpt_sha256':page['excerpt_sha256'],'chunk_sha256':hashlib.sha256(text.encode()).hexdigest()}
            result.append({'id':point_id,'source_index':source_index,'start':start,'end':end,'payload':payload})
            if len(result)>MAX_CHUNKS: invalid()
            if end==len(content): break
    return result

def canonical_chunk(snapshot, chunk):
    payload=chunk['payload']
    page=next((p for p in snapshot['pages'] if p['page']==payload['page']),None)
    if not page or page['excerpt_sha256']!=payload['excerpt_sha256']:
        raise DomainError('semantic_source_changed','The canonical source changed. Rebuild this index.',409)
    text=page['excerpt'][chunk['start']:chunk['end']]
    if hashlib.sha256(text.encode()).hexdigest()!=payload['chunk_sha256']:
        raise DomainError('semantic_integrity','The canonical chunk cannot be verified.',409)
    return text,page

def checkpoint(value):
    """Closed persisted state, including every source/point/active-state join."""
    closed(value,{'scope','profile_id','profile','version','active_generation','jobs'})
    source_scope=scope(value['scope']); profile_id=sha(value['profile_id'])
    closed(value['profile'],{'embedding','chunk_policy','chunk_characters','chunk_overlap'})
    if value['profile']!=profile(value['profile']['embedding']) or digest(value['profile'])!=profile_id: invalid()
    if type(value['version']) is not int or value['version']<1 or not isinstance(value['jobs'],dict) or not 1<=len(value['jobs'])<=MAX_JOBS: invalid()
    active=[]
    for operation_id,job in value['jobs'].items():
        uid(operation_id)
        closed(job,{'id','generation','request_digest','actor','selectors','source_tokens','chunks',
                    'chunk_count','next_chunk','cleanup_next','status','lease','lease_until','error_code'})
        if job['id']!=operation_id: invalid()
        generation=uid(job['generation']); sha(job['request_digest'])
        closed(job['actor'],{'user','person_id'}); identifier(job['actor']['user']); identifier(job['actor']['person_id'])
        if not isinstance(job['selectors'],list) or not 1<=len(job['selectors'])<=MAX_SOURCES: invalid()
        selectors=[selector(s) for s in job['selectors']]
        if len({digest(s) for s in selectors})!=len(selectors): invalid()
        if not isinstance(job['source_tokens'],list) or len(job['source_tokens'])!=len(selectors): invalid()
        for token in job['source_tokens']: sha(token)
        if job['request_digest']!=digest({'scope':source_scope,'selectors':selectors,'profile':value['profile'],'actor':job['actor']}): invalid()
        if generation!=str(uuid.uuid5(uuid.UUID(operation_id),digest([source_scope,profile_id,job['actor']]))): invalid()
        if job['status'] not in ('pending','running','retryable','rejected','active','retired','cancelled','deleted'): invalid()
        if any(type(job[k]) is not int for k in ('chunk_count','next_chunk','cleanup_next')) or not 1<=job['chunk_count']<=MAX_CHUNKS or not 0<=job['next_chunk']<=job['chunk_count'] or not 0<=job['cleanup_next']<=job['chunk_count']: invalid()
        if type(job['lease_until']) not in (int,float) or not math.isfinite(job['lease_until']) or job['lease_until']<0: invalid()
        if job['status']=='running': uid(job['lease'])
        elif job['lease'] is not None or job['lease_until']!=0: invalid()
        if job['error_code'] is not None: identifier(job['error_code'])
        if not isinstance(job['chunks'],list): invalid()
        if job['status']=='deleted':
            if job['chunks'] or job['cleanup_next']!=job['chunk_count']: invalid()
        elif len(job['chunks'])!=job['chunk_count']: invalid()
        ids=set()
        for point in job['chunks']:
            closed(point,{'id','source_index','start','end','payload'})
            point_id=uid(point['id']); payload=closed(point['payload'],PAYLOAD_FIELDS)
            if point_id in ids: invalid()
            ids.add(point_id)
            i=point['source_index']
            if type(i) is not int or not 0<=i<len(selectors): invalid()
            if type(point['start']) is not int or type(point['end']) is not int or not 0<=point['start']<point['end'] or point['end']-point['start']>CHUNK_CHARACTERS: invalid()
            for key in ('scope_key','profile_id','source_sha256','chunk_id','excerpt_sha256','chunk_sha256'): sha(payload[key])
            if type(payload['page']) is not int or not 1<=payload['page']<=10000: invalid()
            if payload['scope_key']!=digest(source_scope) or payload['profile_id']!=profile_id or payload['generation']!=generation or any(payload[k]!=selectors[i][k] for k in ('document_id','revision_id','source_sha256')): invalid()
            if payload['chunk_id']!=digest({'page':payload['page'],'start':point['start'],'end':point['end'],'sha256':payload['chunk_sha256']}): invalid()
            if point_id!=str(uuid.uuid5(uuid.UUID(generation),canonical_json([i,selectors[i],payload['chunk_id']]))): invalid()
        if job['status']=='active':
            if job['next_chunk']!=job['chunk_count']: invalid()
            active.append(generation)
    if active!=([value['active_generation']] if value['active_generation'] is not None else []): invalid()
    return value

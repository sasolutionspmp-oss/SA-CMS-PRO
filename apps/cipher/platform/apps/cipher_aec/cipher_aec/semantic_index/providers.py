"""Optional real Ollama/Qdrant REST adapters, without fixtures or fallback.

Protocol references: Ollama v0.12.6 and Qdrant v1.15.5. The protocol labels
identify this adapter contract; they are not claims about a connected server.
Configuration belongs to trusted server configuration, never RPC payloads.
"""
from copy import deepcopy
import math
import re
from uuid import UUID
from cipher_aec.api.errors import DomainError
from .http import JsonHttpClient,endpoint_url,unavailable,protocol_error,invalid_input

OLLAMA_PROTOCOL='ollama-embed-v1'
QDRANT_PROTOCOL='qdrant-rest-v1'
MAX_BATCH=16
MAX_TEXT_BYTES=16384
MAX_DIMENSIONS=8192
PAYLOAD_KEYS=('scope_key','profile_id','generation','document_id','revision_id','source_sha256','chunk_id','page','excerpt_sha256','chunk_sha256')
_SHA=re.compile(r'[0-9a-f]{64}\Z')

def _text(value,limit=140):
    return type(value) is str and 1<=len(value)<=limit and not any(ord(c)<32 or ord(c)==127 for c in value)

def _uuid(value):
    try:return type(value) is str and str(UUID(value))==value
    except (ValueError,TypeError,AttributeError):return False

def _dimension(value):return type(value) is int and 1<=value<=MAX_DIMENSIONS

def _checksum(value):return type(value) is str and _SHA.fullmatch(value) is not None

def _digest(value):
    if type(value) is not str:return None
    raw=value[7:] if value.startswith('sha256:') else value
    return 'sha256:'+raw if _checksum(raw) else None

def _vector(value,dimensions,fail):
    if type(value) is not list or len(value)!=dimensions:fail()
    result=[]
    for number in value:
        try:
            if type(number) not in (int,float) or not math.isfinite(number):fail()
            result.append(float(number))
        except (OverflowError,ValueError):fail()
    return result

def _metadata(value,fail):
    if type(value) is not dict or set(value)!=set(PAYLOAD_KEYS):fail()
    if any(not _text(value[key]) for key in ('document_id','revision_id','chunk_id')) or not _uuid(value['generation']) or any(not _checksum(value[key]) for key in ('scope_key','profile_id','source_sha256','excerpt_sha256','chunk_sha256')) or type(value['page']) is not int or not 1<=value['page']<=10000:fail()
    return deepcopy(value)

class _Provider:
    def _call(self,method,path,payload=None):
        try:
            result=self._http.request(method,path,payload)
        except DomainError as error:
            # Only safe adapter errors cross the boundary. An injected transport
            # cannot expose an upstream error message or response body.
            if error.code=='semantic_protocol_error':protocol_error()
            if error.code=='semantic_invalid_input':invalid_input()
            unavailable()
        except Exception:unavailable()
        if type(result) is not dict:protocol_error()
        return result

class OllamaEmbedder(_Provider):
    def __init__(self,endpoint,model_tag,model_digest,dimensions,*,protocol=OLLAMA_PROTOCOL,timeout=10,max_body=4*1024*1024,transport=None):
        endpoint_url(endpoint)
        # Explicit tags, including the server's mutable tag name and its exact
        # observed manifest digest. No pull/create/model-selection operation.
        if not _text(model_tag,256) or ':' not in model_tag.rsplit('/',1)[-1] or any(c.isspace() for c in model_tag) or _digest(model_digest) is None or not _dimension(dimensions) or protocol!=OLLAMA_PROTOCOL:unavailable()
        self._model=model_tag;self._digest=_digest(model_digest);self._dimensions=dimensions
        self._http=transport if transport is not None else JsonHttpClient(endpoint,timeout=timeout,max_body=max_body)

    @property
    def identity(self):
        return {'provider':'ollama','protocol':OLLAMA_PROTOCOL,'model':self._model,'model_digest':self._digest,'dimensions':self._dimensions}

    def verify(self):
        tags=self._call('GET','/api/tags');models=tags.get('models')
        if type(models) is not list or len(models)>1000:protocol_error()
        selected=[row for row in models if type(row) is dict and row.get('name')==self._model]
        if len(selected)!=1 or _digest(selected[0].get('digest'))!=self._digest or ('model' in selected[0] and selected[0]['model']!=self._model):protocol_error()
        shown=self._call('POST','/api/show',{'model':self._model,'verbose':False});capabilities=shown.get('capabilities');info=shown.get('model_info')
        if type(capabilities) is not list or not 1<=len(capabilities)<=32 or any(not _text(v,64) for v in capabilities) or 'embedding' not in capabilities or type(info) is not dict:protocol_error()
        architecture=info.get('general.architecture')
        if not _text(architecture,100) or type(info.get(architecture+'.embedding_length')) is not int or info[architecture+'.embedding_length']!=self._dimensions or shown.get('remote_host') or shown.get('remote_model'):protocol_error()
        return self.identity

    def embed(self,texts):
        if type(texts) is not list or not 1<=len(texts)<=MAX_BATCH:invalid_input()
        try:
            if any(type(text) is not str or not text.strip() or len(text.encode('utf-8'))>MAX_TEXT_BYTES for text in texts):invalid_input()
        except UnicodeError:invalid_input()
        self.verify()
        result=self._call('POST','/api/embed',{'model':self._model,'input':list(texts),'truncate':False})
        vectors=result.get('embeddings')
        if result.get('model')!=self._model or type(vectors) is not list or len(vectors)!=len(texts):protocol_error()
        return [_vector(vector,self._dimensions,protocol_error) for vector in vectors]

class QdrantIndex(_Provider):
    def __init__(self,endpoint,collection,dimensions,*,protocol=QDRANT_PROTOCOL,timeout=10,max_body=4*1024*1024,api_key=None,transport=None):
        endpoint_url(endpoint)
        if type(collection) is not str or re.fullmatch(r'[A-Za-z0-9_.-]{1,128}',collection) is None or collection in ('.','..') or not _dimension(dimensions) or protocol!=QDRANT_PROTOCOL:unavailable()
        self._collection=collection;self._dimensions=dimensions;self._path='/collections/'+collection
        self._http=transport if transport is not None else JsonHttpClient(endpoint,timeout=timeout,max_body=max_body,headers={'api-key':api_key} if api_key is not None else None)

    def _result(self,method,path,payload=None):
        response=self._call(method,path,payload)
        if response.get('status')!='ok' or type(response.get('result')) is not dict:protocol_error()
        return response['result']

    def verify(self):
        result=self._result('GET',self._path)
        try:vectors=result['config']['params']['vectors']
        except (KeyError,TypeError):protocol_error()
        if type(vectors) is not dict or type(vectors.get('size')) is not int or vectors['size']!=self._dimensions or vectors.get('distance')!='Cosine' or vectors.get('multivector_config') is not None or vectors.get('datatype') not in (None,'float32'):protocol_error()
        return None

    def _completed(self,method,path,payload):
        result=self._result(method,path,payload)
        if result.get('status')!='completed' or (result.get('operation_id') is not None and (type(result['operation_id']) is not int or result['operation_id']<0)):protocol_error()

    def upsert(self,points):
        if type(points) is not list or not 1<=len(points)<=MAX_BATCH:invalid_input()
        clean=[];ids=set()
        for point in points:
            if type(point) is not dict or set(point)!={'id','vector','payload'} or not _uuid(point['id']) or point['id'] in ids:invalid_input()
            ids.add(point['id']);clean.append({'id':point['id'],'vector':_vector(point['vector'],self._dimensions,invalid_input),'payload':_metadata(point['payload'],invalid_input)})
        self.verify();self._completed('PUT',self._path+'/points?wait=true',{'points':clean})

    def delete(self,ids):
        if type(ids) is not list or not 1<=len(ids)<=100 or any(not _uuid(value) for value in ids) or len(set(ids))!=len(ids):invalid_input()
        self.verify();self._completed('POST',self._path+'/points/delete?wait=true',{'points':list(ids)})

    @staticmethod
    def _filter(scope_key,profile_id,generation=None):
        if not _checksum(scope_key) or not _checksum(profile_id) or (generation is not None and not _uuid(generation)):invalid_input()
        values={'scope_key':scope_key,'profile_id':profile_id}
        if generation is not None:values['generation']=generation
        return {'must':[{'key':key,'match':{'value':value}} for key,value in values.items()]}

    def query(self,vector,scope_key,profile_id,generation,limit):
        if generation is None or type(limit) is not int or not 1<=limit<=100:invalid_input()
        payload={'query':_vector(vector,self._dimensions,invalid_input),'filter':self._filter(scope_key,profile_id,generation),'limit':limit,'with_payload':list(PAYLOAD_KEYS),'with_vector':False}
        self.verify();result=self._result('POST',self._path+'/points/query',payload);points=result.get('points')
        if type(points) is not list or len(points)>limit:protocol_error()
        clean=[];seen=set()
        for point in points:
            if type(point) is not dict or not _uuid(point.get('id')) or point['id'] in seen:protocol_error()
            metadata=_metadata(point.get('payload'),protocol_error)
            if metadata['scope_key']!=scope_key or metadata['profile_id']!=profile_id or metadata['generation']!=generation:protocol_error()
            score=point.get('score')
            if type(score) not in (int,float):protocol_error()
            try:
                if not math.isfinite(score):protocol_error()
                score=float(score)
            except (OverflowError,ValueError):protocol_error()
            seen.add(point['id']);clean.append({'id':point['id'],'score':score,'payload':metadata})
        return clean

    def scroll(self,scope_key,profile_id,offset=None,limit=50):
        if type(limit) is not int or not 1<=limit<=50 or (offset is not None and not _uuid(offset)):invalid_input()
        payload={'filter':self._filter(scope_key,profile_id),'limit':limit,'with_payload':list(PAYLOAD_KEYS),'with_vector':False}
        if offset is not None:payload['offset']=offset
        self.verify();result=self._result('POST',self._path+'/points/scroll',payload);points=result.get('points');next_offset=result.get('next_page_offset')
        if type(points) is not list or len(points)>limit or (next_offset is not None and (not _uuid(next_offset) or next_offset==offset)):protocol_error()
        clean=[];seen=set()
        for point in points:
            if type(point) is not dict or not _uuid(point.get('id')) or point['id'] in seen:protocol_error()
            metadata=_metadata(point.get('payload'),protocol_error)
            if metadata['scope_key']!=scope_key or metadata['profile_id']!=profile_id:protocol_error()
            seen.add(point['id']);clean.append({'id':point['id'],'payload':metadata})
        return {'points':clean,'next_offset':next_offset}

class Unavailable:
    @property
    def identity(self):unavailable()
    def verify(self,*args,**kwargs):unavailable()
    def embed(self,*args,**kwargs):unavailable()
    def upsert(self,*args,**kwargs):unavailable()
    def delete(self,*args,**kwargs):unavailable()
    def query(self,*args,**kwargs):unavailable()
    def scroll(self,*args,**kwargs):unavailable()

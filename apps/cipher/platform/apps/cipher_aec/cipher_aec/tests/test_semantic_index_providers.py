"""Host protocol qualification: injected JSON transports and loopback stub only.

No Ollama/Qdrant service, provider/model, embedding quality or native worker is
connected or qualified by these checks.
"""
from contextlib import contextmanager
from copy import deepcopy
from http.server import BaseHTTPRequestHandler,HTTPServer
import io
import json
import threading
import time
import unittest
from unittest.mock import patch
from urllib.request import build_opener,ProxyHandler
from uuid import uuid4
from cipher_aec.api.errors import DomainError
from cipher_aec.semantic_index.http import JsonHttpClient,_NoRedirect
from cipher_aec.semantic_index.providers import OllamaEmbedder,QdrantIndex,Unavailable,PAYLOAD_KEYS

MODEL='embedding-model:qualification';DIGEST='a'*64;SCOPE='b'*64;PROFILE='c'*64;GENERATION=str(uuid4());POINT=str(uuid4())

def metadata(**overrides):
    return {'scope_key':SCOPE,'profile_id':PROFILE,'generation':GENERATION,'document_id':'source-document','revision_id':'original-revision','source_sha256':'d'*64,'chunk_id':'chunk-1','page':1,'excerpt_sha256':'e'*64,'chunk_sha256':'f'*64,**overrides}

class Scripted:
    def __init__(self,replies):self.replies=[reply if isinstance(reply,Exception) else deepcopy(reply) for reply in replies];self.calls=[]
    def request(self,method,path,payload=None):
        self.calls.append((method,path,deepcopy(payload)))
        reply=self.replies.pop(0)
        if isinstance(reply,Exception):raise reply
        return deepcopy(reply)

def tags():return {'models':[{'name':MODEL,'model':MODEL,'digest':DIGEST}]}
def show():return {'capabilities':['embedding'],'model_info':{'general.architecture':'bert','bert.embedding_length':3}}
def embeddings():return {'model':MODEL,'embeddings':[[0.25,-0.5,0.75]]}
def collection():return {'status':'ok','result':{'config':{'params':{'vectors':{'size':3,'distance':'Cosine'}}}}}
def completed():return {'status':'ok','result':{'status':'completed','operation_id':7}}
def embedder(transport,**kw):return OllamaEmbedder('http://provider.invalid:11434',MODEL,DIGEST,3,transport=transport,**kw)
def index(transport,**kw):return QdrantIndex('http://provider.invalid:6333','preprovisioned',3,transport=transport,**kw)

class OllamaProtocolTests(unittest.TestCase):
    def test_identity_is_pinned_and_reverified_before_each_embedding_batch(self):
        transport=Scripted([tags(),show(),embeddings(),tags(),show(),embeddings()]);provider=embedder(transport)
        self.assertEqual(provider.identity,{'provider':'ollama','protocol':'ollama-embed-v1','model':MODEL,'model_digest':'sha256:'+DIGEST,'dimensions':3})
        identity=provider.identity;identity['dimensions']=9;self.assertEqual(provider.identity['dimensions'],3)
        self.assertEqual(provider.embed(['Original source text']),[[0.25,-0.5,0.75]]);provider.embed(['Second source chunk'])
        self.assertEqual([row[:2] for row in transport.calls],[('GET','/api/tags'),('POST','/api/show'),('POST','/api/embed')]*2)
        self.assertEqual(transport.calls[2][2],{'model':MODEL,'input':['Original source text'],'truncate':False})
        self.assertFalse(any('pull' in row[1] or 'create' in row[1] for row in transport.calls))
    def test_tag_digest_missing_duplicate_or_changed_model_refuses_before_embed(self):
        for reply in [{'models':[]},{'models':[{'name':MODEL,'digest':'0'*64}]},{'models':[tags()['models'][0]]*2},{'models':[{'name':MODEL,'model':'different:tag','digest':DIGEST}]}]:
            with self.subTest(reply=reply):
                transport=Scripted([reply]);provider=embedder(transport)
                with self.assertRaises(DomainError) as error:provider.embed(['Text'])
                self.assertEqual(error.exception.code,'semantic_protocol_error');self.assertEqual(len(transport.calls),1)
    def test_missing_embedding_capability_wrong_dimensions_and_remote_models_refuse(self):
        for reply in [{'capabilities':['completion'],'model_info':show()['model_info']},{**show(),'model_info':{'general.architecture':'bert','other.embedding_length':3}},{**show(),'model_info':{'general.architecture':'bert','bert.embedding_length':4}},{**show(),'model_info':{'general.architecture':'bert','bert.embedding_length':True}},{**show(),'remote_host':'https://remote.invalid'}]:
            with self.subTest(reply=reply):
                transport=Scripted([tags(),reply]);provider=embedder(transport)
                with self.assertRaises(DomainError):provider.embed(['Text'])
                self.assertEqual(len(transport.calls),2)
    def test_vectors_require_exact_batch_dimensions_and_finite_nonboolean_numbers(self):
        for vectors in [[],[[1,2]],[[1,2,3],[4,5,6]],[[True,2,3]],[[1,float('nan'),3]],[[1,float('inf'),3]],[[1,'2',3]],[[1,10**400,3]]]:
            with self.subTest(vectors=vectors):
                provider=embedder(Scripted([tags(),show(),{'model':MODEL,'embeddings':vectors}]))
                with self.assertRaises(DomainError):provider.embed(['Text'])
        provider=embedder(Scripted([tags(),show(),{'model':'different:tag','embeddings':[[1,2,3]]}]))
        with self.assertRaises(DomainError):provider.embed(['Text'])
    def test_text_batch_bounds_and_invalid_configuration_make_no_provider_call(self):
        transport=Scripted([]);provider=embedder(transport)
        for value in [[],['Text']*17,[''],['  '],['界'*6000],['\ud800'],('Text',),[None]]:
            with self.subTest(value_type=type(value).__name__),self.assertRaises(DomainError):provider.embed(value)
        self.assertEqual(transport.calls,[])
        for kwargs in [{'model_tag':'untagged'},{'model_digest':'no-digest'},{'dimensions':True},{'protocol':'guessed-protocol'}]:
            with self.subTest(kwargs=kwargs),self.assertRaises(DomainError):OllamaEmbedder('http://provider.invalid',**{'model_tag':MODEL,'model_digest':DIGEST,'dimensions':3,**kwargs},transport=transport)
    def test_transport_errors_are_safe_and_there_is_no_fixture_fallback(self):
        for exception in [OSError('secret endpoint/token'),DomainError('upstream','raw source text',500)]:
            provider=embedder(Scripted([exception]))
            with self.assertRaises(DomainError) as error:provider.embed(['Private text'])
            self.assertEqual(error.exception.code,'semantic_unavailable');self.assertNotIn('secret',str(error.exception));self.assertNotIn('raw source',str(error.exception));self.assertEqual(error.exception.details,{})

class QdrantProtocolTests(unittest.TestCase):
    def test_preprovisioned_collection_is_verified_without_creating_or_migrating(self):
        transport=Scripted([collection()]);self.assertIsNone(index(transport).verify());self.assertEqual(transport.calls,[('GET','/collections/preprovisioned',None)])
        for vectors in [{'size':4,'distance':'Cosine'},{'size':3,'distance':'Dot'},{'named':{'size':3,'distance':'Cosine'}},{'size':3,'distance':'Cosine','multivector_config':{}},{'size':3,'distance':'Cosine','datatype':'uint8'},{'size':True,'distance':'Cosine'}]:
            with self.subTest(vectors=vectors),self.assertRaises(DomainError):index(Scripted([{'status':'ok','result':{'config':{'params':{'vectors':vectors}}}}])).verify()
    def test_upsert_and_delete_wait_for_confirmed_completion(self):
        transport=Scripted([collection(),completed(),collection(),completed()]);provider=index(transport);point={'id':POINT,'vector':[0.1,0.2,0.3],'payload':metadata()}
        self.assertIsNone(provider.upsert([point]));self.assertEqual(transport.calls[1],('PUT','/collections/preprovisioned/points?wait=true',{'points':[point]}))
        self.assertIsNone(provider.delete([POINT]));self.assertEqual(transport.calls[3],('POST','/collections/preprovisioned/points/delete?wait=true',{'points':[POINT]}))
        with self.assertRaises(DomainError):index(Scripted([collection(),{'status':'ok','result':{'status':'acknowledged','operation_id':8}}])).delete([POINT])
    def test_metadata_only_exact_keys_and_input_ids_are_enforced_before_writes(self):
        transport=Scripted([]);provider=index(transport)
        bad_metadata=[{**metadata(),'text':'Private source snippet'},{**metadata(),'vector':[1,2,3]},metadata(profile_id='other'),metadata(generation='not-uuid'),metadata(page=True),metadata(source_sha256='bad')]
        for payload in bad_metadata:
            with self.subTest(keys=list(payload)),self.assertRaises(DomainError):provider.upsert([{'id':POINT,'vector':[1,2,3],'payload':payload}])
        for ids in [[],[1],['not-uuid'],[POINT,POINT],[POINT]*101]:
            with self.subTest(ids=ids),self.assertRaises(DomainError):provider.delete(ids)
        self.assertEqual(transport.calls,[])
    def test_query_requires_all_three_filters_and_returns_only_verified_metadata(self):
        result={'status':'ok','result':{'points':[{'id':POINT,'score':0.8,'payload':metadata(),'version':5}]}};transport=Scripted([collection(),result]);provider=index(transport)
        self.assertEqual(provider.query([1,2,3],SCOPE,PROFILE,GENERATION,5),[{'id':POINT,'score':0.8,'payload':metadata()}])
        request=transport.calls[1][2];self.assertEqual(request['filter'],{'must':[{'key':key,'match':{'value':value}} for key,value in [('scope_key',SCOPE),('profile_id',PROFILE),('generation',GENERATION)]]});self.assertEqual(set(request['with_payload']),set(PAYLOAD_KEYS));self.assertIs(request['with_vector'],False);self.assertNotIn('lookup_from',request);self.assertNotIn('prefetch',request)
    def test_wrong_scope_profile_generation_or_snippet_from_query_is_refused(self):
        for payload in [metadata(scope_key='0'*64),metadata(profile_id='0'*64),metadata(generation=str(uuid4())),{**metadata(),'snippet':'Unauthorized text'}]:
            with self.subTest(payload=payload),self.assertRaises(DomainError):index(Scripted([collection(),{'status':'ok','result':{'points':[{'id':POINT,'score':0.8,'payload':payload}]}}])).query([1,2,3],SCOPE,PROFILE,GENERATION,5)
    def test_query_invalid_bounds_duplicates_scores_and_overlong_results_fail_closed(self):
        transport=Scripted([]);provider=index(transport)
        for args in [([1,2,3],SCOPE,PROFILE,None,5),([1,2,3],SCOPE,PROFILE,GENERATION,True),([1,2],SCOPE,PROFILE,GENERATION,5),([1,2,3],'',PROFILE,GENERATION,5),([1,2,3],SCOPE,PROFILE,GENERATION,101)]:
            with self.subTest(args=args),self.assertRaises(DomainError):provider.query(*args)
        self.assertEqual(transport.calls,[])
        point={'id':POINT,'score':0.8,'payload':metadata()}
        for points in [[point,point],[{**point,'score':float('inf')}],[{**point,'score':True}],[{**point,'id':4}]]:
            with self.subTest(points=points),self.assertRaises(DomainError):index(Scripted([collection(),{'status':'ok','result':{'points':points}}])).query([1,2,3],SCOPE,PROFILE,GENERATION,1)
    def test_scroll_is_bounded_to_scope_profile_and_allows_old_generations_for_reconciliation(self):
        offset=str(uuid4());other=str(uuid4());transport=Scripted([collection(),{'status':'ok','result':{'points':[{'id':POINT,'payload':metadata(generation=other),'vector':[1,2,3]}],'next_page_offset':offset}}]);provider=index(transport)
        result=provider.scroll(SCOPE,PROFILE,limit=50);self.assertEqual(result,{'points':[{'id':POINT,'payload':metadata(generation=other)}],'next_offset':offset});request=transport.calls[1][2];self.assertEqual([row['key'] for row in request['filter']['must']],['scope_key','profile_id']);self.assertNotIn('offset',request);self.assertIs(request['with_vector'],False)
    def test_scroll_refuses_cross_scope_nonuuid_offset_and_cursor_cycle(self):
        for result in [{'points':[],'next_page_offset':17},{'points':[{'id':POINT,'payload':metadata(scope_key='0'*64)}]},{'points':[],'next_page_offset':POINT}]:
            with self.subTest(result=result),self.assertRaises(DomainError):index(Scripted([collection(),{'status':'ok','result':result}])).scroll(SCOPE,PROFILE,offset=POINT)
        transport=Scripted([])
        with self.assertRaises(DomainError):index(transport).scroll(SCOPE,PROFILE,limit=51)
        self.assertEqual(transport.calls,[])
    def test_unavailable_provider_explicitly_refuses_every_operation(self):
        provider=Unavailable()
        for method,args in [('verify',()),('embed',(['Text'],)),('upsert',([],)),('delete',([],)),('query',([],SCOPE,PROFILE,GENERATION,1)),('scroll',(SCOPE,PROFILE))]:
            with self.subTest(method=method),self.assertRaises(DomainError) as error:getattr(provider,method)(*args)
            self.assertEqual(error.exception.code,'semantic_unavailable')
        with self.assertRaises(DomainError):provider.identity

class Response:
    def __init__(self,body,headers=None,status=200):self.status=status;self.headers={'Content-Type':'application/json',**(headers or {})};self.stream=io.BytesIO(body)
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def read(self,size):return self.stream.read(size)
    def read1(self,size):return self.stream.read(size)
class Opener:
    def __init__(self,response):self.response=response;self.requests=[]
    def open(self,request,timeout):self.requests.append((request,timeout));return self.response

class BoundedHttpTests(unittest.TestCase):
    def test_real_json_encoding_timeout_and_response_bounds(self):
        opener=Opener(Response(b'{"ok":true}',{'Content-Length':'11'}));client=JsonHttpClient('https://provider.invalid/prefix',timeout=2,max_body=1024,opener=opener);self.assertEqual(client.request('POST','/api/embed',{'input':'α'}),{'ok':True});request,timeout=opener.requests[0];self.assertEqual(request.full_url,'https://provider.invalid/prefix/api/embed');self.assertEqual(json.loads(request.data),{'input':'α'});self.assertEqual(timeout,2)
        for body,headers in [(b' '*1025,{}),(b'{}',{'Content-Length':'1025'}),(b'{}',{'Content-Length':'3'}),(b'{}',{'Content-Encoding':'gzip'}),(b'{}',{'Content-Type':'text/html'}),(b'{"secret":"x","secret":"y"}',{}),(b'{"v":NaN}',{}),(b'{"v":1e999}',{}),(b'[]',{}),(b'not json',{})]:
            with self.subTest(headers=headers),self.assertRaises(DomainError):JsonHttpClient('http://provider.invalid',max_body=1024,opener=Opener(Response(body,headers))).request('GET','/api/tags')
    def test_bad_urls_paths_headers_and_payloads_never_reach_opener(self):
        for endpoint in ['file:///etc/passwd','https://user:password@provider.invalid','http://provider.invalid/?token=secret','http://provider.invalid/#fragment','http://provider.invalid/../other','http://provider.invalid\n/','http://provider.invalid:bad']:
            with self.subTest(endpoint=endpoint),self.assertRaises(DomainError):JsonHttpClient(endpoint)
        for kw in [{'timeout':True},{'timeout':31},{'max_body':True},{'headers':{'Authorization':'secret'}},{'headers':{'api-key':'secret\nheader'}}]:
            with self.subTest(kw=kw),self.assertRaises(DomainError):JsonHttpClient('http://provider.invalid',**kw)
        opener=Opener(Response(b'{}'));client=JsonHttpClient('http://provider.invalid',max_body=1024,opener=opener)
        for method,path,payload in [('GET','https://other.invalid',None),('GET','//other.invalid',None),('GET','/../other',None),('POST','/api/embed',{'text':'x'*1025}),('POST','/api/embed',{'v':float('nan')})]:
            with self.subTest(path=path),self.assertRaises(DomainError):client.request(method,path,payload)
        self.assertEqual(opener.requests,[])
    def test_read_deadline_is_checked_and_raw_transport_errors_are_hidden(self):
        client=JsonHttpClient('http://provider.invalid',timeout=1,opener=Opener(Response(b'{}')))
        with patch('cipher_aec.semantic_index.http.time.monotonic',side_effect=[0,2]),self.assertRaises(DomainError) as error:client.request('GET','/api/tags')
        self.assertEqual(error.exception.code,'semantic_unavailable')
        with patch.object(client._opener,'open',side_effect=OSError('secret source text/endpoint')),self.assertRaises(DomainError) as error:client.request('GET','/api/tags')
        self.assertNotIn('secret',str(error.exception));self.assertEqual(error.exception.details,{})
    def test_loopback_stub_receives_actual_json_and_redirect_is_never_followed(self):
        seen=[]
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):
                seen.append(self.path)
                if self.path=='/redirect':self.send_response(302);self.send_header('Location','/redirect-target');self.end_headers();return
                self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(b'{"ok":true}')
            def do_POST(self):
                seen.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))));self.do_GET()
        server=HTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=lambda:server.serve_forever(poll_interval=0.01),daemon=True);thread.start()
        try:
            # This explicit host-only loopback stub is not a provider endpoint.
            opener=build_opener(ProxyHandler({}),_NoRedirect());client=JsonHttpClient('http://127.0.0.1:'+str(server.server_port),timeout=1,opener=opener)
            self.assertEqual(client.request('POST','/json',{'value':'exact α'}),{'ok':True})
            with self.assertRaises(DomainError) as error:client.request('GET','/redirect')
            self.assertEqual(error.exception.code,'semantic_unavailable');self.assertNotIn('/redirect-target',seen);self.assertIn({'value':'exact α'},seen)
        finally:server.shutdown();server.server_close();thread.join(timeout=2)

if __name__=='__main__':unittest.main()

"""Bounded JSON HTTP for server-configured optional semantic providers.

No redirects, response logging, retries, credential discovery or URL selection
from a document/query is supported. The platform's normal proxy/TLS trust remains
in effect. Socket timeouts and a response-read deadline bound stalled reads;
process-level DNS/connect cancellation remains a deployment responsibility.
"""
import json
import math
import time
from urllib.parse import urlsplit
from urllib.request import Request,build_opener,HTTPRedirectHandler
from cipher_aec.api.errors import DomainError

MAX_BODY=8*1024*1024

def unavailable():
    raise DomainError('semantic_unavailable','The semantic provider is unavailable.',503) from None

def protocol_error():
    raise DomainError('semantic_protocol_error','The semantic provider response could not be verified.',502) from None

def invalid_input():
    raise DomainError('semantic_invalid_input','The semantic provider request is invalid.',422) from None

class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):return None

def endpoint_url(endpoint):
    if type(endpoint) is not str or not endpoint or len(endpoint)>2048 or any(ord(c)<33 or ord(c)==127 or c=='\\' for c in endpoint):unavailable()
    try:
        value=urlsplit(endpoint)
        if value.scheme not in ('http','https') or not value.hostname or value.username is not None or value.password is not None or value.query or value.fragment or value.port==0 or any(part in ('.','..') for part in value.path.split('/')):unavailable()
        # Force validation of malformed ports and IPv6 syntax at configuration.
        value.port
    except (ValueError,UnicodeError):unavailable()
    return endpoint.rstrip('/')

def _pairs(pairs):
    result={}
    for key,value in pairs:
        if key in result:raise ValueError('duplicate JSON key')
        result[key]=value
    return result

def _float(value):
    result=float(value)
    if not math.isfinite(result):raise ValueError('nonfinite JSON number')
    return result

def _constant(value):raise ValueError('invalid JSON constant')

class JsonHttpClient:
    def __init__(self,endpoint,*,timeout=10,max_body=4*1024*1024,headers=None,opener=None):
        self._endpoint=endpoint_url(endpoint)
        if type(timeout) not in (int,float) or not math.isfinite(timeout) or not 0<timeout<=30 or type(max_body) is not int or not 1024<=max_body<=MAX_BODY:unavailable()
        if headers is not None and (type(headers) is not dict or set(headers)-{'api-key'}):unavailable()
        self._headers={'Accept':'application/json','Content-Type':'application/json','Accept-Encoding':'identity'}
        for key,value in (headers or {}).items():
            if type(value) is not str or not 1<=len(value)<=4096 or any(ord(c)<33 or ord(c)>126 for c in value):unavailable()
            self._headers[key]=value
        self._timeout=float(timeout);self._max_body=max_body;self._opener=opener or build_opener(_NoRedirect())

    def request(self,method,path,payload=None):
        if method not in ('GET','POST','PUT') or type(path) is not str or not path.startswith('/') or path.startswith('//') or any(ord(c)<33 or ord(c)==127 or c in '#\\' for c in path):invalid_input()
        try:
            parsed=urlsplit(path)
            if parsed.scheme or parsed.netloc or any(part in ('.','..') for part in parsed.path.split('/')):invalid_input()
            if method=='GET' and payload is not None:invalid_input()
            body=None if payload is None else json.dumps(payload,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode('utf-8')
        except (ValueError,TypeError,UnicodeError,RecursionError):invalid_input()
        if body is not None and len(body)>self._max_body:invalid_input()
        request=Request(self._endpoint+path,data=body,headers=self._headers,method=method)
        deadline=time.monotonic()+self._timeout
        try:
            with self._opener.open(request,timeout=self._timeout) as response:
                if response.status!=200:unavailable()
                content_type=response.headers.get('Content-Type','').split(';',1)[0].strip().lower()
                if content_type!='application/json' or response.headers.get('Content-Encoding','identity').lower() not in ('identity',''):protocol_error()
                length=response.headers.get('Content-Length')
                if length is not None and (not length.isascii() or not length.isdigit() or int(length)>self._max_body):protocol_error()
                raw=bytearray();reader=getattr(response,'read1',response.read)
                while True:
                    if time.monotonic()>deadline:unavailable()
                    chunk=reader(min(65536,self._max_body+1-len(raw)))
                    if time.monotonic()>deadline:unavailable()
                    if not chunk:break
                    raw.extend(chunk)
                    if len(raw)>self._max_body:protocol_error()
                if length is not None and len(raw)!=int(length):protocol_error()
        except DomainError:raise
        except Exception:unavailable()
        try:
            result=json.loads(bytes(raw).decode('utf-8'),object_pairs_hook=_pairs,parse_float=_float,parse_constant=_constant)
        except (ValueError,TypeError,UnicodeError,RecursionError):protocol_error()
        if type(result) is not dict:protocol_error()
        return result

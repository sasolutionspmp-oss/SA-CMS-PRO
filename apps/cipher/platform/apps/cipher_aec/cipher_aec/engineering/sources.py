"""Exact Project citations and byte packages; historical sources stay original."""
import hashlib
from cipher_aec.api.errors import DomainError
from cipher_aec.api.contracts import digest
from cipher_aec.documents.service import source_reference,get_citation
from . import contracts as rules

def artifact(company,project,reference,actor,*,lock=False):
    actual=source_reference(company,project,reference['revision_id'],1,actor=actor,lock=lock)
    content=actual.pop('content')
    if not isinstance(content,bytes) or len(content)!=actual['byte_length'] or hashlib.sha256(content).hexdigest()!=reference['source_sha256'] or actual['source_sha256']!=reference['source_sha256']:
        raise DomainError('engineering_source_changed','The exact original source bytes cannot be verified.',412)
    return {k:actual[k] for k in ('document_id','revision_id','revision_number','source_sha256','byte_length','mime_type','page_count')}

def resolve_artifacts(company,project,references,actor,*,lock=False):
    rules.artifacts(references)
    return [artifact(company,project,row,actor,lock=lock) for row in references]

def resolve_citations(company,project,references,actor,*,lock=False,required=True):
    rules.citations(references,required=required);result=[]
    for ref in references:
        scoped=source_reference(company,project,ref['revision_id'],ref['page'],actor=actor,lock=lock)
        if scoped['source_sha256']!=ref['source_sha256']:
            raise DomainError('engineering_source_changed','The exact cited source changed.',412)
        value=get_citation(company,ref['revision_id'],ref['page'],excerpt_sha256=ref['excerpt_sha256'],actor=actor)
        if value['source_sha256']!=ref['source_sha256'] or value['revision_id']!=ref['revision_id'] or value['page']!=ref['page']:
            raise DomainError('engineering_source_integrity','The canonical citation differs from its declared original.',409)
        result.append(value)
    return result

def resolve_drawings(company,project,references,actor,*,lock=False):
    rules.drawings(references);result=[]
    for reference in references:
        actual=source_reference(company,project,reference['revision_id'],reference['page'],actor=actor,lock=lock)
        content=actual.pop('content')
        if (not isinstance(content,bytes) or actual['mime_type']!='application/pdf' or len(content)!=actual['byte_length']
            or hashlib.sha256(content).hexdigest()!=reference['source_sha256'] or actual['source_sha256']!=reference['source_sha256']
            or actual['page']!=reference['page'] or not 1<=reference['page']<=actual['page_count']):
            raise DomainError('engineering_source_changed','The exact original drawing page/bytes cannot be verified.',412)
        result.append({**{k:actual[k] for k in ('document_id','revision_id','revision_number','source_sha256','byte_length','mime_type','page_count')},'page':reference['page'],'locator':reference['locator']})
    return result

def verify(company,project,value,actor,*,lock=False):
    citations=value.get('source_citations',[])
    refs=[{k:c[k] for k in ('revision_id','page','excerpt_sha256','source_sha256')} for c in citations]
    if len(refs)>64:raise DomainError('engineering_source_integrity','The source closure exceeds its bound.',409)
    actual=[]
    for offset in range(0,len(refs),8):actual.extend(resolve_citations(company,project,refs[offset:offset+8],actor,lock=lock,required=False))
    if actual!=citations:raise DomainError('engineering_source_integrity','Original engineering citations cannot be verified.',409)
    stored_drawings=value.get('drawing_references',[])
    actual_drawings=[]
    for offset in range(0,len(stored_drawings),8):
        actual_drawings.extend(resolve_drawings(company,project,[{k:r[k] for k in ('revision_id','source_sha256','page','locator')} for r in stored_drawings[offset:offset+8]],actor,lock=lock))
    if actual_drawings!=stored_drawings:raise DomainError('engineering_source_integrity','The original drawing references differ.',409)
    stored=value.get('artifacts',[])
    if stored:
        actual=resolve_artifacts(company,project,[{k:v[k] for k in ('revision_id','source_sha256')} for v in stored],actor,lock=lock)
        if actual!=stored:raise DomainError('engineering_source_integrity','Original engineering package bytes cannot be verified.',409)

def merge(*groups):
    result={}
    for group in groups:
        for row in group:
            key=row.get('id') or (row['revision_id']+'|'+str(row['page'])+'|'+row['locator'] if 'locator' in row else row['revision_id'])
            if key in result and result[key]!=row:raise DomainError('engineering_source_integrity','A source identity has conflicting facts.',409)
            result[key]=row
    return [result[key] for key in sorted(result)]

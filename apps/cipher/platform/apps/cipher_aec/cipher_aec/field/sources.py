"""Exact canonical bytes and current rights; original metadata never follows a head."""
import hashlib
from cipher_aec.api.errors import DomainError
from cipher_aec.documents.service import source_reference
from cipher_aec.document_control import rights
from . import contracts as rules

def references(value,kind):
    if kind in ('daily_revision','ticket_revision'):
        return [*rules.sources_in_definition(value['definition'],kind),*[p['source'] for p in value['photos']]]
    if kind=='quantity':return value['definition']['sources']
    if kind=='decision':return value['evidence']
    return []

def resolve(company,project,references,actor,*,lock=False,new_use=False):
    """One bounded source union, sorted parents before exact revision locks."""
    if len(references)>400:rules.fail('The source closure exceeds its bounded size.','sources')
    unique={}
    for row in references:
        rules.source(rules.strip_source(row));key=(row['revision_id'],row['page'],row['locator'])
        if key in unique and unique[key]['source_sha256']!=row['source_sha256']:rules.fail('An exact source identity has conflicting hashes.','sources')
        unique[key]=row
    if len({row['revision_id'] for row in unique.values()})>32:rules.fail('Use at most 32 exact source revisions in one field package.','sources')
    revisions={}
    for row in unique.values():
        previous=revisions.get(row['revision_id'])
        if previous and previous['source_sha256']!=row['source_sha256']:rules.fail('An exact revision has conflicting source hashes.','sources')
        if previous is None or row['page']<previous['page']:revisions[row['revision_id']]=row
    discovered={}
    for revision,row in sorted(revisions.items()):
        metadata=source_reference(company,project,revision,row['page'],actor=actor)
        metadata.pop('content',None);discovered[revision]=metadata
    if sum(r['byte_length'] for r in discovered.values())>64*1024*1024:
        raise DomainError('field_source_limit','Use a field evidence package of at most 64 MiB of exact source bytes.',422)
    if lock and discovered:rights.prelock({r['document_id'] for r in discovered.values()},company,project,actor)
    by_revision={}
    for revision in sorted(revisions,key=lambda name:(discovered[name]['document_id'],name)):
        row=revisions[revision];actual=source_reference(company,project,revision,row['page'],actor=actor,lock=lock)
        if actual['document_id']!=discovered[revision]['document_id']:raise DomainError('field_source_changed','The canonical source parent changed.',412)
        content=actual['content']
        if (type(content) is not bytes or len(content)!=actual['byte_length'] or hashlib.sha256(content).hexdigest()!=row['source_sha256']
            or actual['source_sha256']!=row['source_sha256'] or actual['revision_id']!=row['revision_id'] or actual['page']!=row['page']):
            raise DomainError('field_source_changed','The exact original field source bytes cannot be verified.',412)
        if new_use:
            if actual.get('is_current') is not True:raise DomainError('stale_field_source','Review the current source revision before a new field effect.',412)
            rights.require(actual['document_id'],company,project,'ingest',actor,lock=lock,required=True)
        by_revision[revision]={k:actual[k] for k in ('document_id','revision_id','revision_number','source_sha256','byte_length','mime_type','page_count')}
    result={}
    for key,row in unique.items():
        actual=by_revision[row['revision_id']]
        if row['page']>actual['page_count']:rules.fail('The selected page exceeds the exact source revision.','page')
        result[key]={**actual,'page':row['page'],'locator':row['locator']}
    return result

def mapped(row,resolved):return resolved[row['revision_id'],row['page'],row['locator']]

def verify(values,company,project,actor,*,lock=False,new_use=False):
    refs=[row for kind,value in values for row in references(value,kind)]
    resolved=resolve(company,project,refs,actor,lock=lock,new_use=new_use)
    for row in refs:
        if row!=mapped(row,resolved):raise DomainError('field_source_integrity','The original field source metadata differs from its canonical bytes.',409)
    for kind,value in values:
        if kind not in ('daily_revision','ticket_revision'):continue
        for photo in value['photos']:
            source=photo['source']
            if photo['representation']=='source_image':
                if source['mime_type'] not in ('image/jpeg','image/png') or source['page']!=1 or source['page_count']!=1:
                    rules.fail('An original photo must be an admitted single-image JPEG or PNG.','photos')
            elif source['mime_type']!='application/pdf':rules.fail('An identified PDF photo must reference an actual PDF page.','photos')
    return resolved

from pathlib import Path
import json
r=Path('/dev/shm/cipher-documents-doc03-successor/workspace/apps/cipher/platform/apps/cipher_aec/cipher_aec')
def edit(rel,old,new):
 p=r/rel;s=p.read_text();assert old in s,(rel,old[:50]);p.write_text(s.replace(old,new))
# Existing record identities are reused; Company nullability is explicit and guarded.
for slug in ['cipher_source_rights_revision','cipher_library_entry','cipher_library_revision']:
 p=r/'cipher_document_control/doctype'/slug/(slug+'.json');s=json.loads(p.read_text())
 for f in s['fields']:
  if f['fieldname']=='scope_type':f['options']='Project\nCompany'
  if f['fieldname']=='project':f['reqd']=0
 p.write_text(json.dumps(s,indent=2)+'\n')
edit('document_control/repository.py',"fields.update(scope_type='Project',company=", "fields.update(scope_type=value['scope_type'],company=")
edit('document_control/repository.py',"def candidates(kind,company,project,*,parent_id=None,last=None,limit=25):\n    where=['company=%s','project=%s'];args=[company,project]", "def candidates(kind,company,project,*,parent_id=None,last=None,limit=25,scope_type='Project'):\n    where=['company=%s',\"scope_type=%s\"];args=[company,scope_type]\n    if scope_type=='Company' and project is None:where.append('project IS NULL')\n    elif scope_type=='Project' and project:where.append('project=%s');args.append(project)\n    else:raise DomainError('invalid_document_scope','Choose an exact documentary scope.',422)")
p=r/'document_control/records.py';s=p.read_text().replace('from . import contracts as rules,repository as repo','from . import contracts as rules,repository as repo,scopes')
s=s.replace('rules.closed(value,BASE|EXTRA[kind])',"rules.closed(value,BASE|EXTRA[kind]|({'library_scope'} if kind=='adoption_request' and 'library_scope' in value else set()))")
s=s.replace("value['scope_type']!='Project'", "(value['scope_type']!='Project' and not(kind in ('rights','library','library_revision') and value['scope_type']=='Company' and value['project'] is None))")
s=s.replace("require_project(self.company,self.project,ability=ability,actor=actor,lock=True);require_project(self.company,self.project,ability=rules.READ,actor=actor,lock=True)","scopes.require(self.company,value['scope_type'],value['project'],actor,ability,lock=True);scopes.require(self.company,value['scope_type'],value['project'],actor,rules.READ,lock=True)")
p.write_text(s)
# Add only the three literal reusable-library Company duties; never default-grant them.
edit('governance/context.py','COMPANY_ABILITIES = frozenset({','COMPANY_ABILITIES = frozenset({"document.control.read", "document.control.write", "document.rights.manage", ',)
edit('install.py','abilities = abilities or sorted(COMPANY_ABILITIES)','abilities = abilities or sorted(COMPANY_ABILITIES - DOCUMENT_CONTROL_ABILITIES)')
# Current per-source permissions apply to both explicit source scopes.
p=r/'document_control/rights.py';s=p.read_text();s=s.replace('def prelock(document_ids,company,project,actor):','def prelock(document_ids,company,project,actor,*,scope_type=\'Project\'):').replace('    from .service import _document\n    planned=', '    from . import scopes\n    planned=').replace('for name in sorted(planned):_document(name,company,project,actor,lock=True)',"for name in sorted(planned):\n        if scope_type=='Project':\n            from .service import _document\n            _document(name,company,project,actor,lock=True)\n        else:scopes.document(name,company,scope_type,project,actor,lock=True)")
s=s.replace("original=value['evidence_artifact'];actual=artifact(value['company'],value['project'],{k:original[k] for k in ('revision_id','source_sha256')},actor,lock=lock)","""original=value['evidence_artifact']
        if value['scope_type']=='Company':
            from .shared import artifact as scoped_artifact
            actual=scoped_artifact(value['company'],'Company',None,{k:original[k] for k in ('revision_id','source_sha256')},actor,lock=lock)
        else:actual=artifact(value['company'],value['project'],{k:original[k] for k in ('revision_id','source_sha256')},actor,lock=lock)""")
s=s.replace('actor,*,lock=False,required=True):\n    require_project(company,project,ability=\'document.read\',actor=actor,lock=lock)',"actor,*,lock=False,required=True,scope_type='Project'):\n    from . import scopes\n    scopes.require(company,scope_type,project,actor,'document.read',lock=lock)")
s=s.replace('prelock([document_id],company,project,actor);value=', 'prelock([document_id],company,project,actor,scope_type=scope_type);value=')
s=s.replace("value['scope_type']!='Project'", "value['scope_type']!=scope_type")
s=s.replace("    if (row.get('scope_type') or 'Project')!='Project':return\n    document_id=", "    scope_type=row.get('scope_type') or 'Project'\n    document_id=")
s=s.replace("'read',actor,lock=lock,required=False)","'read',actor,lock=lock,required=False,scope_type=scope_type)",1)
s=s.replace('SELECT r.parent_id,r.company,r.project FROM', 'SELECT r.parent_id,r.company,r.project,r.scope_type FROM').replace("require(row.parent_id,row.company,row.project,'read',actor)","require(row.parent_id,row.company,row.project,'read',actor,scope_type=row.scope_type)")
p.write_text(s)
p=r/'documents/provenance.py';s=p.read_text();s=s.replace("    if (row.get('scope_type') or 'Project') == 'Project':\n        from cipher_aec.document_control.rights import authorize as authorize_rights\n        authorize_rights(row,actor,lock=lock)\n        return", "    from cipher_aec.document_control.rights import authorize as authorize_rights\n    authorize_rights(row,actor,lock=lock)\n    if (row.get('scope_type') or 'Project') == 'Project':\n        return",1);p.write_text(s)
p=r/'documents/service.py';s=p.read_text();needle='''    def effect(actor, native_company):'''
# Locate the Company upload body without assuming another function's effect name.
start=s.index('def upload_company_document(');end=s.index('\ndef ',start+5);section=s[start:end];needle='    def effect(actor, company_doc):'
if needle not in section:
 import re
 needle=re.search(r'    def effect\(actor, [^)]+\):',section).group(0)
section=section.replace(needle,needle+"\n        if document_id:\n            from cipher_aec.document_control.rights import require as require_rights,prelock as prelock_rights\n            prelock_rights([document_id],company,None,actor,scope_type='Company')\n            require_rights(document_id,company,None,'ingest',actor,lock=True,required=False,scope_type='Company')",1);s=s[:start]+section+s[end:];p.write_text(s)
# Canonical stored origins can cross Project boundaries; raw old Project input remains strict.
p=r/'document_control/service.py';s=p.read_text().replace('def _prelock(artifacts,company,project,actor,*,lock=False):','def _prelock(artifacts,company,project,actor,*,lock=False,allow_foreign=False):')
s=s.replace("    if any(row.company!=company or row.project!=project or (row.scope_type or 'Project')!='Project' for row in locators):raise", "    if allow_foreign and any(row.project!=project or (row.scope_type or 'Project')!='Project' for row in locators):\n        if lock:\n            from .locking import DocumentContext\n            with DocumentContext(company,project,artifacts=artifacts).hold(actor):pass\n        return\n    if any(row.company!=company or row.project!=project or (row.scope_type or 'Project')!='Project' for row in locators):raise")
s=s.replace("def verify_artifacts(artifacts,company,project,actor,*,operation='read',lock=False):\n    _prelock", "def verify_artifacts(artifacts,company,project,actor,*,operation='read',lock=False):\n    locators=[FrappeDocumentRepository().revision_scope(row['revision_id']) for row in artifacts]\n    if any(row.company!=company or row.project!=project or (row.scope_type or 'Project')!='Project' for row in locators):\n        from .shared import verify_artifacts as verify_originals\n        return verify_originals(artifacts,company,actor,operation=operation,lock=lock)\n    _prelock")
s=s.replace("_prelock([*artifacts,*planned],company,project,actor,lock=True)","_prelock([*artifacts,*planned],company,project,actor,lock=True,allow_foreign=True)")
s=s.replace("if planned:_prelock(planned,company,project,actor,lock=lock)","if planned:_prelock(planned,company,project,actor,lock=lock,allow_foreign=True)")
s=s.replace("original=read('library_revision',value['library_revision'],company,project,actor,lock=lock)","if 'library_scope' in value:\n            from .shared import read_origin\n            original=read_origin('library_revision',value['library_revision'],company,value['library_scope'],actor,lock=lock)\n        else:original=read('library_revision',value['library_revision'],company,project,actor,lock=lock)")
old="revision=source if kind=='library_revision' else read('library_revision',source['library_revision'],company,project,actor)\n        current=raw('library',revision['parent_id'],company,project)['current_revision']==revision['id'] and all(_document(row['document_id'],company,project,actor).current_revision==row['revision_id'] for row in revision['artifacts'])"
new="""if 'library_scope' in source:
            from .shared import read_origin
            revision=read_origin('library_revision',source['library_revision'],company,source['library_scope'],actor)
            header=read_origin('library',revision['parent_id'],company,source['library_scope'],actor)
            from .scopes import document
            current=header['current_revision']==revision['id'] and all(document(row['document_id'],company,source['library_scope']['scope_type'],source['library_scope']['project'],actor).current_revision==row['revision_id'] for row in revision['artifacts'])
        else:
            revision=source if kind=='library_revision' else read('library_revision',source['library_revision'],company,project,actor)
            current=raw('library',revision['parent_id'],company,project)['current_revision']==revision['id'] and all(_document(row['document_id'],company,project,actor).current_revision==row['revision_id'] for row in revision['artifacts'])"""
assert old in s;s=s.replace(old,new);p.write_text(s)
# Origin rights become literal approval sources, retaining full outer hash semantics.
p=r/'document_control/governance.py';s=p.read_text();s=s.replace("if kind=='adoption_request':authors.add(service.read('library_revision',value['library_revision'],company,project,actor,lock=lock)['author_person'])", """if kind=='adoption_request':
            if 'library_scope' in value:
                from .shared import read_origin
                authors.add(read_origin('library_revision',value['library_revision'],company,value['library_scope'],actor,lock=lock)['author_person'])
            else:authors.add(service.read('library_revision',value['library_revision'],company,project,actor,lock=lock)['author_person'])""")
s=s.replace("policies=[rights.require(name,company,project,'read',actor,lock=lock) for name in sorted({r['document_id'] for r in value['artifacts']})]", """from .shared import artifact_scope
    policies=[]
    for row in sorted({r['document_id']:r for r in value['artifacts']}.values(),key=lambda r:r['document_id']):
        scope,source_project=artifact_scope(company,row)
        policies.append(rights.require(row['document_id'],company,source_project,'read',actor,lock=lock,scope_type=scope))""")
s=s.replace("    return {'subject':", "    if kind=='adoption_request' and 'library_scope' in value:effect['library_scope']=value['library_scope']\n    return {'subject':",1)
s=s.replace("service.verify_artifacts(value['artifacts'],company,project,recipient,lock=lock)","service.verify_artifacts(value['artifacts'],company,project,recipient,lock=lock)\n            service.read('issue',value['issue_id'],company,project,recipient,lock=lock)")
p.write_text(s)

from pathlib import Path
from copy import deepcopy
import json
r=Path('/dev/shm/cipher-documents-doc03-successor/workspace/apps/cipher/platform/apps/cipher_aec/cipher_aec')
p=r/'document_control/api.py';p.write_text(p.read_text()+'''\n@endpoint(methods=["POST"])
def create_shared_adoption(company, project, operation_id, library_scope, library_revision, library_digest, definition):
    from .shared import create_adoption
    return create_adoption(company,project,operation_id,library_scope,library_revision,library_digest,definition)
''')
ref=lambda n:{'$ref':'#/$defs/'+n}
obj=lambda props:{'type':'object','properties':props,'required':list(props),'additionalProperties':False}
text=lambda n:{'type':'string','minLength':1,'maxLength':n}
p=r/'document_control/schemas/api-v1.schema.json';s=json.loads(p.read_text());d=s['$defs'];company_records=[]
for name in ['Rights','Library','LibraryRevision']:
 v=deepcopy(d['Dc'+name]);v['properties']['scope_type']={'const':'Company'};v['properties']['project']={'type':'null'};d['DcCompany'+name]=v;company_records.append(ref('DcCompany'+name))
d['DcCompanyRecord']={'anyOf':company_records};d['DcCompanyGetResponse']=deepcopy(d['DcGetResponse']);d['DcCompanyGetResponse']['properties']['record']=ref('DcCompanyRecord')
d['DcCompanyListResponse']=deepcopy(d['DcListResponse']);d['DcCompanyListResponse']['properties']['items']['items']=ref('DcCompanyGetResponse')
for name in ['SetRightsRequest','CreateLibraryRequest','ReviseLibraryRequest','GetRecordRequest','ListRecordsRequest']:
 v=deepcopy(d['Dc'+name]);v['properties'].pop('project');v['required'].remove('project')
 if 'kind' in v['properties']:v['properties']['kind']['enum']=['rights','library','library_revision']
 d['DcCompany'+name]=v
for name in ['SetRightsResponse','CreateLibraryResponse','ReviseLibraryResponse']:
 v=deepcopy(d['Dc'+name])
 for key in ['rights','library','library_revision']:
  if key in v['properties']:v['properties'][key]=ref({'rights':'DcCompanyRights','library':'DcCompanyLibrary','library_revision':'DcCompanyLibraryRevision'}[key])
 d['DcCompany'+name]=v
d['DcLibraryScope']={'oneOf':[obj({'scope_type':{'const':'Company'},'project':{'type':'null'}}),obj({'scope_type':{'const':'Project'},'project':text(140)})]}
v=deepcopy(d['DcAdoptionRequest']);v['properties']['library_scope']=ref('DcLibraryScope');v['required'].append('library_scope');d['DcSharedAdoptionRequest']=v;d['DcRecord']['anyOf'].append(ref('DcSharedAdoptionRequest'))
v=deepcopy(d['DcCreateAdoptionRequest']);v['properties']['library_scope']=ref('DcLibraryScope');v['required'].append('library_scope');d['DcCreateSharedAdoptionRequest']=v
v=deepcopy(d['DcCreateAdoptionResponse']);v['properties']['adoption_request']=ref('DcSharedAdoptionRequest');d['DcCreateSharedAdoptionResponse']=v
p.write_text(json.dumps(s,indent=2)+'\n')
# Project request map remains explicit; a distinct Company map prevents scope aliases.
p=r/'document_control/route-contracts.json';v=json.loads(p.read_text());v['requests']['create_shared_adoption']='DcCreateSharedAdoptionRequest';v['responses']['create_shared_adoption']='DcCreateSharedAdoptionResponse';p.write_text(json.dumps(v,indent=2)+'\n')
company={'set_rights':('DcCompanySetRightsRequest','DcCompanySetRightsResponse'),'create_library':('DcCompanyCreateLibraryRequest','DcCompanyCreateLibraryResponse'),'revise_library':('DcCompanyReviseLibraryRequest','DcCompanyReviseLibraryResponse'),'get_record':('DcCompanyGetRecordRequest','DcCompanyGetResponse'),'list_records':('DcCompanyListRecordsRequest','DcCompanyListResponse')}
(r/'document_control/company-route-contracts.json').write_text(json.dumps({'requests':{k:v[0] for k,v in company.items()},'responses':{k:v[1] for k,v in company.items()}},indent=2)+'\n')
p=r/'api/catalog.py';v=p.read_text().replace('_module("cipher_aec.document_control.api", {','_module("cipher_aec.document_control.api", {\n    "create_shared_adoption": ("POST", "DcCreateSharedAdoptionResponse", True),',1);needle='RPC_ROUTES =';idx=v.index(needle);v=v[:idx]+'''_module("cipher_aec.document_control.company_api", {
'''+''.join('    '+repr(k)+': ('+repr('GET' if k in ['get_record','list_records'] else 'POST')+', '+repr(t[1])+(', True' if k not in ['get_record','list_records'] else '')+'),\n' for k,t in company.items())+'})\n\n'+v[idx:];p.write_text(v)
p=r/'api/openapi.py';v=p.read_text().replace("'read_clause_target': 'DcReadClauseTargetRequest'}", "'read_clause_target': 'DcReadClauseTargetRequest', 'create_shared_adoption':'DcCreateSharedAdoptionRequest'}",1);needle='        ("cipher_aec.document_control.api",';i=v.index(needle);v=v[:i]+'        ("cipher_aec.document_control.company_api", "document_control/schemas/api-v1.schema.json", '+repr({k:t[0] for k,t in company.items()})+'),\n'+v[i:];p.write_text(v)
p=r/'api/schema.json';v=json.loads(p.read_text());core=v['$defs'];core.update(deepcopy(d))
# All documentary packet source policies can truthfully carry current explicit Company or Project rights.
for name,packet in core.items():
 if name.startswith('Document') and name.endswith('ApprovalPacket') and 'properties' in packet:
  source=packet['properties']['review_manifest']['properties']['sources']['items']['properties'];source['rights']['items']={'oneOf':[ref('DcRights'),ref('DcCompanyRights')]}
packet=deepcopy(core['DocumentAdoptionRequestApprovalPacket']);effect=packet['properties']['review_manifest']['properties']['effect'];effect['properties']['library_scope']=ref('DcLibraryScope');effect['required'].append('library_scope');core['DocumentSharedAdoptionRequestApprovalPacket']=packet;core['DocumentApprovalPacket']['oneOf'].append(ref('DocumentSharedAdoptionRequestApprovalPacket'));core['DocumentApprovalExecutionResponse']['oneOf'].append(obj({'packet':ref('DocumentSharedAdoptionRequestApprovalPacket'),'effect':obj({'adoption':ref('DcAdoption')}),'operation':ref('Operation')}))
p.write_text(json.dumps(v,indent=2)+'\n')

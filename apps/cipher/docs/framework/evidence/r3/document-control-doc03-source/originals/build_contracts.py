from pathlib import Path
import json,copy
r=Path(__file__).parent/'workspace/apps/cipher/platform/apps/cipher_aec/cipher_aec'
eng=json.loads((r/'engineering/schemas/api-v1.schema.json').read_text())['$defs']
core=json.loads((r/'api/schema.json').read_text())
def obj(p,required=None):return {'type':'object','properties':p,'required':list(p) if required is None else required,'additionalProperties':False}
def ref(n):return {'$ref':'#/$defs/'+n}
def text(n=2000):return {'type':'string','maxLength':n}
def arr(s,n=8,minimum=0):return {'type':'array','items':s,'minItems':minimum,'maxItems':n}
def null(s):return {'anyOf':[s,{'type':'null'}]}
id={'type':'string','format':'uuid'};sha={'type':'string','pattern':'^[a-f0-9]{64}$'};integer={'type':'integer','minimum':1};stamp={'type':'string','format':'date-time'}
d={k.replace('Eg','Dc',1):copy.deepcopy(eng[k]) for k in ('EgNoEffects','EgArtifact','EgArtifactInput','EgPerson','EgOperation')}
d['DcRightsDefinition']=obj({'ingest_allowed':{'type':'boolean'},'read_allowed':{'type':'boolean'},'distribute_allowed':{'type':'boolean'},'rights_basis':text(4000)})
d['DcLibraryDefinition']=obj({'title':text(240),'category':{'enum':['specification','contract_clause','reference']},'discipline':text(),'ownership':text(),'tags':arr(text(80),20),'change_reason':text()})
d['DcAdoptionDefinition']=obj({'purpose':text(4000),'target_locator':text(4000),'change_reason':text(4000)})
d['DcIssueDefinition']=obj({'title':text(240),'purpose':text(4000),'issue_purpose':{'enum':['coordination','information','review','contract_reference']}})
d['DcExactReference']=obj({'id':id,'record_digest':sha})
base={'id':id,'company':text(140),'project':text(140),'scope_type':{'const':'Project'},'author_person':text(140),'author_user':text(140),'created_at':stamp,'status':{'const':'working'},'no_effects':ref('DcNoEffects')}
artifacts={'artifacts':arr(ref('DcArtifact'),8,1)}
d['DcRights']=obj({**base,'status':{'const':'authored_rights_basis'},'parent_id':text(140),'predecessor':null(id),'revision_number':integer,**d['DcRightsDefinition']['properties']})
d['DcLibrary']=obj({**base,'current_revision':id,'revision_number':integer})
d['DcLibraryRevision']=obj({**base,'parent_id':id,'predecessor':null(id),'revision_number':integer,'definition':ref('DcLibraryDefinition'),'artifacts':arr(ref('DcArtifact'),1,1)})
d['DcAdoptionRequest']=obj({**base,'parent_id':id,'library_revision':id,'library_digest':sha,'definition':ref('DcAdoptionDefinition'),'artifacts':arr(ref('DcArtifact'),1,1)})
d['DcIssueSet']=obj({**base,'definition':ref('DcIssueDefinition'),**artifacts,'adoptions':arr(ref('DcExactReference')),'package_digest':sha})
d['DcTransmittal']=obj({**base,'parent_id':id,'issue_id':id,'issue_digest':sha,**artifacts,'recipients':arr(ref('DcPerson'),30,1),'purpose':text(4000),'required_response':text(4000),'channel':{'const':'internal'},'package_digest':sha})
fact={**base,'parent_id':id,'subject_id':id,'subject_digest':sha,'packet_id':text(140),'decision_id':text(140),'checked_by_person':text(140),'effect_digest':sha,**artifacts,'electronic_signature':{'const':False},'professional_seal':{'const':False},'external_delivery':{'const':False},'commercial_execution':{'const':False}}
d['DcIssue']=obj({**fact,'status':{'const':'issued'},'package_digest':sha})
d['DcAdoption']=obj({**fact,'status':{'const':'adopted'},'artifacts':arr(ref('DcArtifact'),1,1)})
d['DcDistribution']=obj({**fact,'status':{'const':'recorded_internally'},'package_digest':sha,'recipients':arr(ref('DcPerson'),30,1),'channel':{'const':'internal'}})
d['DcEvidence']=obj({**base,'parent_id':id,'subject_kind':{'enum':['distribution','adoption']},'subject_id':id,'subject_digest':sha,'statement':text(4000),**artifacts,'status':{'enum':['reported_received','reported_execution']},'commercial_execution':{'const':False},'electronic_signature':{'const':False}})
names={'rights':'DcRights','library':'DcLibrary','library_revision':'DcLibraryRevision','adoption_request':'DcAdoptionRequest','adoption':'DcAdoption','issue_set':'DcIssueSet','issue':'DcIssue','transmittal':'DcTransmittal','distribution':'DcDistribution','evidence':'DcEvidence'}
d['DcRecord']={'anyOf':[ref(n) for n in names.values()]}
d['DcGetResponse']=obj({'record':ref('DcRecord'),'record_digest':sha,'library_current':null({'type':'boolean'})})
page={'next_cursor':null(text(4096)),'limit':{'type':'integer','minimum':1,'maximum':100},'count_mode':{'const':'none'},'total':{'type':'null'}}
d['DcListResponse']=obj({'items':arr(ref('DcGetResponse'),100),**page});d['DcPeopleResponse']=obj({'items':arr(obj({'user':text(140),'person':text(140),'display_name':text(140)}),100),**page})
cb={'company':text(140),'project':text(140),'operation_id':id}
commands={
'set_rights':({'document_id':text(140),'expected_version':null(sha),'definition':ref('DcRightsDefinition')},{'rights':ref('DcRights')}),
'create_library':({'definition':ref('DcLibraryDefinition'),'artifact':ref('DcArtifactInput')},{'library':ref('DcLibrary'),'library_revision':ref('DcLibraryRevision')}),
'revise_library':({'library_id':id,'expected_version':sha,'definition':ref('DcLibraryDefinition'),'artifact':ref('DcArtifactInput')},{'library':ref('DcLibrary'),'library_revision':ref('DcLibraryRevision')}),
'create_adoption':({'library_revision':id,'library_digest':sha,'definition':ref('DcAdoptionDefinition')},{'adoption_request':ref('DcAdoptionRequest')}),
'create_issue_set':({'definition':ref('DcIssueDefinition'),'artifacts':arr(ref('DcArtifactInput')),'adoptions':arr(ref('DcExactReference'))},{'issue_set':ref('DcIssueSet')}),
'create_transmittal':({'issue_id':id,'issue_digest':sha,'recipients':arr(text(140),30,1),'purpose':text(4000),'required_response':text(4000)},{'transmittal':ref('DcTransmittal')}),
'record_evidence':({'subject_kind':{'enum':['distribution','adoption']},'subject_id':id,'subject_digest':sha,'statement':text(4000),'artifacts':arr(ref('DcArtifactInput'),8,1)},{'evidence':ref('DcEvidence')})}
requests={};responses={};lines=['"""Typed canonical Project document-control endpoints."""','from cipher_aec.api.transport import endpoint','from . import service','']
for name,(inputs,outputs) in commands.items():
 title='Dc'+''.join(w.title() for w in name.split('_'));requests[name]=title+'Request';responses[name]=title+'Response';d[title+'Request']=obj({**cb,**inputs});d[title+'Response']=obj({**outputs,'history_id':text(140),'operation':ref('DcOperation')})
 keys=list(cb)+list(inputs);lines.extend(['@endpoint(methods=["POST"])','def '+name+'('+', '.join(keys)+'):','    return service.'+name+'('+','.join(keys)+')',''])
reads={'get_record':({'kind':{'enum':list(names)},'record_id':id},'DcGetResponse'), 'list_records':({'kind':{'enum':list(names)},'parent_id':null(text(140)),'limit':page['limit'],'cursor':null(text(4096)),'count_mode':{'const':'none'}},'DcListResponse'),'list_people':({'limit':page['limit'],'cursor':null(text(4096)),'count_mode':{'const':'none'}},'DcPeopleResponse')}
for name,(inputs,response) in reads.items():
 title='Dc'+''.join(w.title() for w in name.split('_'));requests[name]=title+'Request';responses[name]=response;required=['company','project']+(['kind','record_id'] if name=='get_record' else ['kind'] if name=='list_records' else []);d[title+'Request']=obj({'company':text(140),'project':text(140),**inputs},required)
 defaults={'parent_id':'None','limit':'25','cursor':'None','count_mode':"'none'"};args=['company','project']+[k+('='+defaults[k] if k in defaults else '') for k in inputs];keys=['company','project']+list(inputs);lines.extend(['@endpoint()','def '+name+'('+', '.join(args)+'):','    return service.'+name+'('+','.join(keys)+')',''])
(r/'document_control/api.py').write_text('\n'.join(lines));(r/'document_control/route-contracts.json').write_text(json.dumps({'requests':requests,'responses':responses},indent=2)+'\n')
schema={'$schema':'https://json-schema.org/draft/2020-12/schema','$id':'urn:cipher:document-control:api:v1','$defs':d,'anyOf':[ref(n) for n in list(requests.values())+list(responses.values())]};(r/'document_control/schemas/api-v1.schema.json').write_text(json.dumps(schema,indent=2)+'\n')
# Literal, separately discriminated packet family; existing approval pairings unchanged.
packets=[];executions=[]
for kind,action,doctype in [('issue_set','document.issue.v1','Cipher Document Issue Set'),('adoption_request','document.library.adopt.v1','Cipher Adoption Request'),('transmittal','document.transmit.v1','Cipher Transmittal')]:
 packet=copy.deepcopy(core['$defs']['DomainApprovalPacket']);p=packet['properties'];p['schema']={'const':'cipher.document.approval.v1'};packet['required'].append('schema');p['action']={'const':action};p['subject']['properties']['type']={'const':doctype}
 effect={'schema':{'const':'cipher.document.authorization.v1'},'action':{'const':action},'subject_kind':{'const':kind},'subject_id':id,'subject_digest':sha,**artifacts,'no_effects':ref('DcNoEffects'),'electronic_signature':{'const':False},'professional_seal':{'const':False},'external_delivery':{'const':False},'commercial_execution':{'const':False}}
 if kind=='transmittal':effect.update(package_digest=sha,recipients=arr(ref('DcPerson'),30,1),channel={'const':'internal'})
 elif kind=='issue_set':effect.update(package_digest=sha,adoptions=arr(ref('DcExactReference')))
 else:effect.update(library_revision=id,library_digest=sha,target_locator=text(4000))
 p['review_manifest']=obj({'subject':obj({'doctype':{'const':doctype},'name':id,'label':text(4000)}),'sources':arr(obj({**artifacts,'rights':arr(ref('DcRights'),8,1)}),1,1),'effect':obj(effect),'summary':obj({'definition':ref('DcIssueDefinition' if kind=='issue_set' else 'DcAdoptionDefinition') if kind!='transmittal' else {'type':'null'},'purpose':text(4000) if kind=='transmittal' else {'type':'null'},'required_response':text(4000) if kind=='transmittal' else {'type':'null'},'no_effects':ref('DcNoEffects'),'rights_basis':{'const':'authored-declaration'},'external_delivery':{'const':False},'commercial_execution':{'const':False}})})
 title='Document'+''.join(x.title() for x in kind.split('_'));name=title+'ApprovalPacket';core['$defs'][name]=packet;packets.append(ref(name));factkind={'issue_set':'issue','adoption_request':'adoption','transmittal':'distribution'}[kind];executions.append(obj({'packet':ref(name),'effect':obj({factkind:ref(names[factkind])}),'operation':ref('Operation')}))
core['$defs']['DocumentApprovalPacket']={'oneOf':packets};core['$defs']['DocumentApprovalExecutionResponse']={'oneOf':executions};core['$defs']['ApprovalPacket']['oneOf'].append(ref('DocumentApprovalPacket'));core['$defs']['ApprovalExecutionResponse']['oneOf'].append(ref('DocumentApprovalExecutionResponse'))
def include(value):
 if isinstance(value,dict):
  if '$ref' in value:
   name=value['$ref'].split('/')[-1]
   if name.startswith('Dc') and name not in core['$defs']:core['$defs'][name]=copy.deepcopy(d[name]);include(d[name])
  for child in value.values():include(child)
 elif isinstance(value,list):
  for child in value:include(child)
for p in packets:include(core['$defs'][p['$ref'].split('/')[-1]])
for p in executions:include(p)
(r/'api/schema.json').write_text(json.dumps(core,indent=2)+'\n')
# Register signatures and typed response/request schema source.
p=r/'api/catalog.py';s=p.read_text()+'\n_module("cipher_aec.document_control.api", '+repr({k:('POST' if k in commands else 'GET',responses[k],True) if k in commands else ('GET',responses[k]) for k in requests})+')\n';p.write_text(s)
p=r/'api/openapi.py';s=p.read_text().replace('    for module,path,requests in (','    for module,path,requests in (')
needle='        ("cipher_aec.engineering_packages.api",';assert needle in s;s=s.replace(needle,'        ("cipher_aec.document_control.api", "document_control/schemas/api-v1.schema.json", '+repr(requests)+'),\n'+needle,1);p.write_text(s)
# Supported DocTypes have exact command-only controllers, normal install metadata, no grants.
native={'rights':'Cipher Source Rights Revision','library':'Cipher Library Entry','library_revision':'Cipher Library Revision','adoption_request':'Cipher Adoption Request','adoption':'Cipher Project Adoption','issue_set':'Cipher Document Issue Set','issue':'Cipher Document Issue','transmittal':'Cipher Transmittal','distribution':'Cipher Document Distribution','evidence':'Cipher Documentary Evidence'}
module=r/'cipher_document_control';(module/'doctype').mkdir(parents=True,exist_ok=True)
for folder in (module,module/'doctype'):(folder/'__init__.py').write_text('')
template=json.loads((r/'cipher_engineering_packages/doctype/cipher_design_basis_revision/cipher_design_basis_revision.json').read_text());template['module']='Cipher Document Control';template['field_order']=[k for k in template['field_order'] if k not in ('number','family_id')]+['read_allowed'];template['fields']=[f for f in template['fields'] if f['fieldname'] not in ('number','family_id')]+[{'fieldname':'read_allowed','fieldtype':'Check','label':'Read Allowed'}]
for kind,doctype in native.items():
 slug=doctype.lower().replace(' ','_');folder=module/'doctype'/slug;folder.mkdir();(folder/'__init__.py').write_text('');value=copy.deepcopy(template);value['name']=doctype;(folder/(slug+'.json')).write_text(json.dumps(value,indent=2)+'\n');cls=''.join(doctype.split());(folder/(slug+'.py')).write_text('from cipher_aec.document_control.records import DocumentaryRecord\n\nclass '+cls+'(DocumentaryRecord):\n    pass\n')
print('DOC03 schema, ten API routes, ten DocTypes and three separate approval branches written')

from pathlib import Path
from copy import deepcopy
import json
r=Path('/dev/shm/cipher-documents-doc03-successor/workspace/apps/cipher/platform/apps/cipher_aec/cipher_aec')
p=r/'document_control/api.py';p.write_text(p.read_text()+'''\n@endpoint(methods=["POST"])
def create_clause_use(company, project, operation_id, adoption_id, adoption_digest, source_clause, target, purpose):
    from .clauses import create_clause_use as create
    return create(company,project,operation_id,adoption_id,adoption_digest,source_clause,target,purpose)

@endpoint(methods=["POST"])
def create_redline(company, project, operation_id, clause_use_id, clause_use_digest, expected_version, proposed_text, reason):
    from .clauses import create_redline as create
    return create(company,project,operation_id,clause_use_id,clause_use_digest,expected_version,proposed_text,reason)

@endpoint()
def read_clause_target(company, project, kind, record_id):
    from .clauses import read_target
    return read_target(company,project,kind,record_id)
''')
p=r/'document_control/route-contracts.json';routes=json.loads(p.read_text());new={'create_clause_use':('DcCreateClauseUseRequest','DcCreateClauseUseResponse'),'create_redline':('DcCreateRedlineRequest','DcCreateRedlineResponse'),'read_clause_target':('DcReadClauseTargetRequest','DcClauseTargetResponse')}
for name,(req,res) in new.items():routes['requests'][name]=req;routes['responses'][name]=res
p.write_text(json.dumps(routes,indent=2)+'\n')
p=r/'api/catalog.py';s=p.read_text();needle='_module("cipher_aec.document_control.api", {';s=s.replace(needle,needle+''.join('\n    "'+n+'": ("'+('GET' if n=='read_clause_target' else 'POST')+'", "'+v[1]+'"'+(', True' if n!='read_clause_target' else '')+'),' for n,v in new.items()));p.write_text(s)
p=r/'api/openapi.py';s=p.read_text();old="'list_people': 'DcListPeopleRequest'}";s=s.replace(old,"'list_people': 'DcListPeopleRequest', "+', '.join(repr(n)+': '+repr(v[0]) for n,v in new.items())+'}');p.write_text(s)
ref=lambda n:{'$ref':'#/$defs/'+n}
obj=lambda props,req=None:{'type':'object','properties':props,'required':list(props) if req is None else req,'additionalProperties':False}
text=lambda n:{'type':'string','maxLength':n,'minLength':1}
sha={'type':'string','pattern':'^[a-f0-9]{64}$'};ident={'type':'string','format':'uuid'};nullable=lambda v:{'anyOf':[v,{'type':'null'}]}
p=r/'document_control/schemas/api-v1.schema.json';schema=json.loads(p.read_text());d=schema['$defs'];base={k:deepcopy(v) for k,v in d['DcAdoptionRequest']['properties'].items() if k in ['id','company','project','scope_type','author_person','author_user','created_at','status','no_effects']};arts=deepcopy(d['DcAdoptionRequest']['properties']['artifacts'])
d['DcClauseSourceReference']=obj({'revision_id':ident,'source_sha256':sha,'page':{'type':'integer','minimum':1,'maximum':10000},'excerpt_sha256':sha,'start':{'type':'integer','minimum':0,'maximum':1000000},'end':{'type':'integer','minimum':1,'maximum':1000000}})
d['DcClauseTargetKind']={'enum':['proposal_revision','contract_revision','document_revision']}
d['DcClauseTarget']=obj({'kind':ref('DcClauseTargetKind'),'id':ident,'record_digest':sha,'locator':text(2000)})
d['DcClauseTargetSnapshot']={'oneOf':[obj({'kind':{'const':kind},'id':ident,'record_digest':sha,'parent_id':text(140),'company':text(140),'project':{'type':'null'} if scope=='Company' else text(140),'scope_type':{'const':scope}}) for kind,scope in [('proposal_revision','Company'),('contract_revision','Project'),('document_revision','Project')]]}
d['DcQuotedClause']=obj({'reference':ref('DcClauseSourceReference'),'text':text(12000),'text_sha256':sha})
d['DcClauseUse']=obj({**base,'status':{'const':'referenced'},'parent_id':ident,'adoption_id':ident,'adoption_digest':sha,'source_clause':ref('DcQuotedClause'),'target':ref('DcClauseTarget'),'target_snapshot':ref('DcClauseTargetSnapshot'),'purpose':text(4000),'artifacts':arts,'target_changed':{'const':False}})
d['DcRedline']=obj({**base,'status':{'const':'proposed'},'parent_id':ident,'clause_use_id':ident,'clause_use_digest':sha,'predecessor':nullable(ident),'revision_number':{'type':'integer','minimum':1},'original_text':text(12000),'proposed_text':text(12000),'proposed_sha256':sha,'reason':text(4000),'target':ref('DcClauseTarget'),'target_snapshot':ref('DcClauseTargetSnapshot'),'artifacts':arts,'target_changed':{'const':False}})
app=deepcopy(d['DcAdoption']['properties']);app.update(status={'const':'approved_relationship'},target=ref('DcClauseTarget'),target_snapshot=ref('DcClauseTargetSnapshot'),original_text=text(12000),proposed_text=text(12000),proposed_sha256=sha,target_changed={'const':False});d['DcClauseApplication']=obj(app)
for n in ['DcClauseUse','DcRedline','DcClauseApplication']:d['DcRecord']['anyOf'].append(ref(n))
for v in ['clause_use','redline','clause_application']:
 d['DcGetRecordRequest']['properties']['kind']['enum'].append(v);d['DcListRecordsRequest']['properties']['kind']['enum'].append(v)
reqbase={k:deepcopy(v) for k,v in d['DcCreateAdoptionRequest']['properties'].items() if k in ['company','project','operation_id']}
d['DcCreateClauseUseRequest']=obj({**reqbase,'adoption_id':ident,'adoption_digest':sha,'source_clause':ref('DcClauseSourceReference'),'target':ref('DcClauseTarget'),'purpose':text(4000)})
d['DcCreateRedlineRequest']=obj({**reqbase,'clause_use_id':ident,'clause_use_digest':sha,'expected_version':nullable(sha),'proposed_text':text(12000),'reason':text(4000)})
d['DcReadClauseTargetRequest']=obj({'company':text(140),'project':text(140),'kind':ref('DcClauseTargetKind'),'record_id':ident})
for n,k,t in [('DcCreateClauseUseResponse','clause_use','DcClauseUse'),('DcCreateRedlineResponse','redline','DcRedline')]:d[n]=obj({k:ref(t),'history_id':text(140),'operation':ref('DcOperation')})
d['DcClauseTargetResponse']=obj({'target':ref('DcClauseTargetSnapshot')})
p.write_text(json.dumps(schema,indent=2)+'\n')
# Keep old packets byte-identical; add one statically paired documentary branch.
p=r/'api/schema.json';s=json.loads(p.read_text());core=s['$defs'];core.update(deepcopy(d));packet=deepcopy(core['DocumentAdoptionRequestApprovalPacket']);props=packet['properties'];props['action']={'const':'document.clause.apply.v1'};props['subject']['properties']['type']={'const':'Cipher Redline Revision'};review=props['review_manifest']['properties'];review['subject']['properties']['doctype']={'const':'Cipher Redline Revision'};effect=review['effect']['properties'];
for k in ['library_revision','library_digest','target_locator']:effect.pop(k)
effect.update(action={'const':'document.clause.apply.v1'},subject_kind={'const':'redline'},target=ref('DcClauseTarget'),target_snapshot=ref('DcClauseTargetSnapshot'),original_text=text(12000),proposed_text=text(12000),proposed_sha256=sha,target_changed={'const':False});review['effect']['required']=list(effect)
review['summary']['properties']['definition']={'type':'null'}
core['DocumentRedlineApprovalPacket']=packet;core['DocumentApprovalPacket']['oneOf'].append(ref('DocumentRedlineApprovalPacket'));core['DocumentApprovalExecutionResponse']['oneOf'].append(obj({'packet':ref('DocumentRedlineApprovalPacket'),'effect':obj({'clause_application':ref('DcClauseApplication')}),'operation':ref('Operation')}))
p.write_text(json.dumps(s,indent=2)+'\n')

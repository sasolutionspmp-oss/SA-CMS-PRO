"""DOC-03 closed exact-source records; manual evidence never executes a contract."""
from cipher_aec.engineering.contracts import closed,text,identifier,checksum,sequence,users,fail,NO_EFFECTS,artifacts,day
KINDS={'rights':'Cipher Source Rights Revision','library':'Cipher Library Entry','library_revision':'Cipher Library Revision','adoption_request':'Cipher Adoption Request','adoption':'Cipher Project Adoption','issue_set':'Cipher Document Issue Set','issue':'Cipher Document Issue','transmittal':'Cipher Transmittal','distribution':'Cipher Document Distribution','evidence':'Cipher Documentary Evidence','clause_use':'Cipher Clause Use','redline':'Cipher Redline Revision','clause_application':'Cipher Clause Application','lifecycle_request':'Cipher Document Lifecycle Request','lifecycle':'Cipher Document Lifecycle Event'}
READ='document.control.read';WRITE='document.control.write';MANAGE='document.rights.manage';ISSUE='document.issue';ADOPT='document.adopt';DISTRIBUTE='document.distribute';REVIEW='document.control.review'
ABILITIES=frozenset((READ,WRITE,MANAGE,ISSUE,ADOPT,DISTRIBUTE,REVIEW))
ACTIONS={'issue_set':'document.issue.v1','adoption_request':'document.library.adopt.v1','transmittal':'document.transmit.v1','redline':'document.clause.apply.v1','lifecycle_request':'document.lifecycle.v1'}
FACTS={'issue_set':'issue','adoption_request':'adoption','transmittal':'distribution','redline':'clause_application','lifecycle_request':'lifecycle'}
ACTION_ABILITY={'issue_set':ISSUE,'adoption_request':ADOPT,'transmittal':DISTRIBUTE,'redline':ADOPT,'lifecycle_request':ISSUE}

def rights(value):
    closed(value,{'ingest_allowed','read_allowed','distribute_allowed','rights_basis','rights_holder','allowed_purpose','restriction','valid_from','valid_until','evidence_artifact'})
    if any(type(value[k]) is not bool for k in ('ingest_allowed','read_allowed','distribute_allowed')):fail('Declare exact source rights flags.','rights')
    text(value['rights_basis'],'rights_basis',4000)
    text(value['rights_holder'],'rights_holder',500);text(value['allowed_purpose'],'allowed_purpose',4000);text(value['restriction'],'restriction',4000,blank=True)
    day(value['valid_from'],'valid_from');day(value['valid_until'],'valid_until');artifacts([value['evidence_artifact']])
    if value['valid_from'] and value['valid_until'] and value['valid_from']>value['valid_until']:fail('The permission end date precedes its start date.','valid_until')
    return value

def library_definition(value):
    closed(value,{'title','category','discipline','ownership','tags','change_reason'})
    if value['category'] not in ('specification','contract_clause','reference'):fail('Choose specification, contract clause or reference.','category')
    for key in ('title','discipline','ownership','change_reason'):text(value[key],key,240 if key=='title' else 2000)
    sequence(value['tags'],'tags',20)
    for tag in value['tags']:text(tag,'tags',80)
    if len(set(value['tags']))!=len(value['tags']):fail('Choose each library tag once.','tags')

def adoption_definition(value):
    closed(value,{'purpose','target_locator','change_reason'})
    for key in value:text(value[key],key,4000)

def issue_definition(value):
    closed(value,{'title','purpose','issue_purpose'})
    text(value['title'],'title',240);text(value['purpose'],'purpose',4000)
    if value['issue_purpose'] not in ('coordination','information','review','contract_reference'):fail('Choose the documentary issue purpose.','issue_purpose')

def exact_ref(value):
    closed(value,{'id','record_digest'});identifier(value['id']);checksum(value['record_digest'])

def package_digest(value):
    from cipher_aec.api.contracts import digest
    return digest({key:value[key] for key in ('artifacts','adoptions','definition')})


def clause_source(value):
    closed(value,{'revision_id','source_sha256','page','excerpt_sha256','start','end'})
    text(value['revision_id'],'revision_id',140);checksum(value['source_sha256']);checksum(value['excerpt_sha256'])
    if type(value['page']) is not int or not 1<=value['page']<=10000:fail('Choose an exact source page.','page')
    if type(value['start']) is not int or type(value['end']) is not int or not 0<=value['start']<value['end']<=1000000:fail('Choose a nonempty exact text range.','source_clause')

def clause_target(value):
    closed(value,{'kind','id','record_digest','locator'})
    if value['kind'] not in ('proposal_revision','contract_revision','document_revision'):fail('Choose an immutable proposal, contract or document revision.','target.kind')
    if value['kind']=='document_revision':text(value['id'],'target.id',140)
    else:identifier(value['id'])
    checksum(value['record_digest']);text(value['locator'],'target.locator',2000)

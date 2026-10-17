"""ENG-02 closed manual-authored contracts, without formula/tool execution."""
from cipher_aec.engineering.contracts import closed,text,identifier,checksum,sequence,day,fail,NO_EFFECTS,drawings,citations,artifacts
from cipher_aec.estimating.contracts import quantity
KINDS={'package':'Cipher Engineering Work Package','package_revision':'Cipher Engineering Package Revision','basis':'Cipher Design Basis Revision','calculation':'Cipher Calculation Revision','deliverable':'Cipher Deliverable Revision','check':'Cipher Engineering Check Revision'}
ACTIONS={'basis':'engineering.basis.check.v1','calculation':'engineering.calculation.check.v1','deliverable':'engineering.deliverable.check.v1'}
READ='engineering.package.read';WRITE='engineering.package.write';CHECK='engineering.package.check'

def package_definition(value):
    closed(value,{'title','discipline','scope','responsible_user','checker_user','due_date','task_ids','wbs_ids'})
    for key,maximum in [('title',240),('discipline',140),('scope',20000),('responsible_user',140),('checker_user',140)]:text(value[key],key,maximum)
    day(value['due_date'],'due_date')
    if value['responsible_user']==value['checker_user']:fail('Select a different responsible engineer and checker.','checker_user')
    for key in ('task_ids','wbs_ids'):
        for item in sequence(value[key],key):text(item,key,140)
        if len(set(value[key]))!=len(value[key]):fail('Choose each exact task/WBS once.',key)
    return value

def codes(rows):
    for row in sequence(rows,'design_codes',8):
        closed(row,{'code','edition','clause'})
        for key in row:text(row[key],key,500,blank=key=='clause')
    return rows

def basis_definition(value):
    closed(value,{'title','criteria','assumptions','design_codes','change_reason'})
    text(value['title'],'title',240);text(value['criteria'],'criteria',20000);text(value['assumptions'],'assumptions',20000,blank=True);text(value['change_reason'],'change_reason',2000);codes(value['design_codes']);return value

def calculation_definition(value):
    closed(value,{'title','method','algorithm_reference','tool_name','tool_version','model_version','design_codes','explanation','change_reason'})
    if value['method']!='human-authored-results-v1':fail('This slice records human-authored results without executing formulas or tools.','method')
    for key in ('title','algorithm_reference','tool_name','tool_version','change_reason'):text(value[key],key,2000)
    text(value['model_version'],'model_version',500,blank=True);text(value['explanation'],'explanation',20000);codes(value['design_codes']);return value

def deliverable_definition(value):
    closed(value,{'title','deliverable_type','description','checking_notes','change_reason'})
    for key in ('title','deliverable_type','change_reason'):text(value[key],key,2000)
    text(value['description'],'description',20000);text(value['checking_notes'],'checking_notes',20000,blank=True);return value

def quantities(rows,manifest,field):
    sequence(rows,field,32)
    by_id={r['id']:r for r in manifest['records'] if r['kind']=='uom'}
    for row in rows:
        closed(row,{'key','label','quantity','source'})
        text(row['key'],field+'.key',140);text(row['label'],field+'.label',240);quantity(row['quantity'],by_id,field+'.quantity')
        closed(row['source'],{'revision_id','source_sha256','page','locator'})
        text(row['source']['revision_id'],'revision_id',140);checksum(row['source']['source_sha256']);text(row['source']['locator'],'locator',1000)
        if type(row['source']['page']) is not int or not 1<=row['source']['page']<=200:fail('Use an exact source page.','page')
    if len({r['key'] for r in rows})!=len(rows):fail('Use distinct quantity keys.',field)
    return rows

def quantity_refs(rows):
    sequence(rows,'quantities',32);result=set()
    for row in rows:
        closed(row,{'key','label','quantity','source'});closed(row['quantity'],{'amount','unit_id','precision'});identifier(row['quantity']['unit_id'],'unit_id');result.add(row['quantity']['unit_id'])
    return result

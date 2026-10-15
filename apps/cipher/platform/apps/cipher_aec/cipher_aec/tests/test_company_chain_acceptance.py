"""Independent opt-in Company/Pursuit integration fixtures.

Domain APIs remain owned by DOC/EST/GOV/COM. Setup is synthetic Administrator
only and must run in the root-coordinated serial User/Auth slot. Credentials are
written to a mode0600 private manifest, never returned or included in evidence.
"""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import secrets
from uuid import uuid4

REQUIRED_ABILITIES = frozenset({'company.read','commercial.read','commercial.write','document.read','document.write',
                                'estimate.read','estimate.write','approval.request','approval.decide','approval.execute'})


def _save_private_fixture(value):
    import frappe
    private_dir=Path(frappe.get_site_path('private','cipher-fixtures'));private_dir.mkdir(parents=True,exist_ok=True);private_dir.chmod(0o700)
    path=private_dir/(value['fixture_id']+'.secret.json');temporary=path.with_name(path.name+'.'+uuid4().hex+'.pending')
    descriptor=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(descriptor,'w') as stream:
        json.dump(value,stream,indent=2,sort_keys=True);stream.write('\n');stream.flush();os.fsync(stream.fileno())
    os.replace(temporary,path)
    descriptor=os.open(private_dir,os.O_RDONLY|getattr(os,'O_DIRECTORY',0))
    try:os.fsync(descriptor)
    finally:os.close(descriptor)
    return path.resolve()


def _administrator():
    import frappe
    from cipher_aec.governance.context import assert_synthetic_site
    assert_synthetic_site()
    if frappe.session.user != 'Administrator':
        raise RuntimeError('An explicit synthetic bench Administrator fixture context is required.')


def historical_project_controls():
    """Bind immutable existing Project rows, without returning their payloads."""
    import frappe
    _administrator()
    project=frappe.db.get_value('Project',{'company':'Cipher Synthetic Company','project_name':'Synthetic bridge rehabilitation'},'name')
    if not project:
        raise RuntimeError('The existing historical Project control is missing; do not seed from this fixture.')
    return _capture_project_controls(project)


def _capture_project_controls(project):
    import frappe
    _administrator()
    controls={}
    selections={
        'Cipher Command Receipt':['name','person','operation_id','company','project','scope_type','request_hash','result_hash','result_json'],
        'Cipher History Event':['name','company','project','scope_type','event_hash','event_payload','details_json'],
    }
    for table,fields in selections.items():
        rows=frappe.db.sql('SELECT '+','.join('`'+field+'`' for field in fields)+' FROM `tab'+table+'` WHERE project=%s ORDER BY creation,name LIMIT 16',(project,),as_dict=True)
        if not rows:
            raise RuntimeError('Historical Project control rows are missing; populate through the separate existing qualification.')
        controls[table]=[{'id':row.name,'sha256':hashlib.sha256(json.dumps(dict(row),sort_keys=True,separators=(',',':'),default=str).encode()).hexdigest()} for row in rows]
    return {'project':project,'records':controls,'qualification':'Hashes of fixed immutable historical rows; later unrelated appends are allowed.'}


def verify_historical_project_controls(control):
    import frappe
    _administrator()
    selections={
        'Cipher Command Receipt':['name','person','operation_id','company','project','scope_type','request_hash','result_hash','result_json'],
        'Cipher History Event':['name','company','project','scope_type','event_hash','event_payload','details_json'],
    }
    verified={}
    for table,records in control['records'].items():
        if table not in selections:
            raise RuntimeError('Unsupported historical control table.')
        fields=selections[table]
        for record in records:
            rows=frappe.db.sql('SELECT '+','.join('`'+field+'`' for field in fields)+' FROM `tab'+table+'` WHERE name=%s AND project=%s',(record['id'],control['project']),as_dict=True)
            if len(rows)!=1:
                raise AssertionError('An original Project control row disappeared.')
            current=hashlib.sha256(json.dumps(dict(rows[0]),sort_keys=True,separators=(',',':'),default=str).encode()).hexdigest()
            if current!=record['sha256']:
                raise AssertionError('An original Project receipt/event payload or hash changed.')
        verified[table]=len(records)
    return {'status':'passed','project':control['project'],'unchanged_original_rows':verified}


def prepare_fixture(require_historical=True):
    """Create native masters and scoped identities, never a preaward fake Project.

    A separate Project-only identity/control is created BEFORE measuring the
    Company journey; Company author/reviewer/alias have no Project duties.
    """
    import frappe
    from frappe.permissions import add_permission, update_permission_property
    from cipher_aec.governance.context import COMPANY_ABILITIES, trusted_write, current_actor, duty_rows
    from cipher_aec.install import _person,_user,_binding,_grant,_grant_company
    _administrator()
    missing=REQUIRED_ABILITIES-set(COMPANY_ABILITIES)
    if missing:
        raise RuntimeError('Company integration prerequisites are not ready: '+','.join(sorted(missing)))
    if not frappe.db.exists('Warehouse Type','Transit'):
        raise RuntimeError('Supported base synthetic setup must be completed separately; this fixture does not reseed.')
    marker=uuid4().hex[:12]
    company_a='Company chain A '+marker;company_b='Company chain B '+marker
    people={key:'CHAIN-'+key.upper()+'-'+marker for key in ('author','reviewer','outsider','project_only')}
    users={};role='Company chain native read '+marker;reviewer_role='Company chain reviewer read '+marker
    historical=historical_project_controls() if require_historical else None
    with trusted_write():
        for index,company in enumerate((company_a,company_b)):
            frappe.get_doc({'doctype':'Company','company_name':company,'abbr':'Q'+str(index)+marker[:6],'default_currency':'USD','country':'United States'}).insert(ignore_permissions=True)
            frappe.get_doc({'doctype':'Fiscal Year','year':'Company chain 2026 '+str(index)+' '+marker,'year_start_date':'2026-01-01','year_end_date':'2026-12-31','companies':[{'company':company}]}).insert(ignore_permissions=True)
        for key in ('author','alias','reviewer','outsider','project_only'):
            person=people['author' if key=='alias' else key]
            _person(person,'Explicit Company chain '+('author alias' if key=='alias' else key))
            email='company.chain.'+key+'.'+marker+'@cipher.example';password=secrets.token_urlsafe(32)
            _user(email,'Company chain '+key,password);_binding(email,person)
            users[key]={'user':email,'person':person,'password':password}
        admin=current_actor().person_id
        for company in (company_a,company_b):
            for ability in sorted(COMPANY_ABILITIES):_grant_company(admin,company,ability)
        for ability in sorted(COMPANY_ABILITIES):
            _grant_company(people['author'],company_a,ability)
            _grant_company(people['outsider'],company_b,ability)
        for ability in ('company.read','commercial.read','document.read','estimate.read','approval.decide'):
            _grant_company(people['reviewer'],company_a,ability)
        for native_role in (role,reviewer_role):
            frappe.get_doc({'doctype':'Role','role_name':native_role}).insert(ignore_permissions=True)
            for doctype in ('Company','Customer','Supplier','Item','UOM','Currency','Price List','Account','Opportunity','Quotation'):
                add_permission(doctype,native_role,0)
                for permission in ('read','select'):update_permission_property(doctype,native_role,0,permission,1)
                if native_role==role and doctype in ('Opportunity','Quotation'):
                    for permission in ('create','write'):update_permission_property(doctype,native_role,0,permission,1)
        for actor_role,credentials in users.items():
            doc=frappe.get_doc('User',credentials['user']);doc.append('roles',{'role':reviewer_role if actor_role=='reviewer' else role});doc.save(ignore_permissions=True)
        customer_group=frappe.get_doc({'doctype':'Customer Group','customer_group_name':'Company chain '+marker,'parent_customer_group':'All Customer Groups','is_group':0}).insert(ignore_permissions=True)
        supplier_group=frappe.get_doc({'doctype':'Supplier Group','supplier_group_name':'Company chain '+marker,'parent_supplier_group':'All Supplier Groups','is_group':0}).insert(ignore_permissions=True)
        territory=frappe.get_doc({'doctype':'Territory','territory_name':'Company chain '+marker,'parent_territory':'All Territories','is_group':0}).insert(ignore_permissions=True)
        native={}
        for key,company in (('a',company_a),('b',company_b)):
            company_doc=frappe.get_doc('Company',company)
            customer=frappe.get_doc({'doctype':'Customer','customer_name':'Company chain customer '+key+' '+marker,'customer_type':'Company','customer_group':customer_group.name,'territory':territory.name,
                                     'accounts':[{'company':company,'account':company_doc.default_receivable_account}]}).insert(ignore_permissions=True)
            supplier=frappe.get_doc({'doctype':'Supplier','supplier_name':'Company chain supplier '+key+' '+marker,'supplier_type':'Company','supplier_group':supplier_group.name,
                                     'accounts':[{'company':company,'account':company_doc.default_payable_account}]}).insert(ignore_permissions=True)
            price_list=frappe.get_doc({'doctype':'Price List','price_list_name':'Company chain selling '+key+' '+marker,'currency':'USD','enabled':1,'selling':1,'buying':0}).insert(ignore_permissions=True)
            native[key]={'customer':customer.name,'supplier':supplier.name,'price_list':price_list.name}
        project=frappe.get_doc({'doctype':'Project','company':company_b,'project_name':'Independent Project-only chain control '+marker,'status':'Open'}).insert(ignore_permissions=True)
        for ability in ('project.read','task.create'):_grant(people['project_only'],company_b,project.name,ability)
        for ability in ('project.read','task.create'):_grant(admin,company_b,project.name,ability)
        item_group=frappe.get_doc({'doctype':'Item Group','item_group_name':'Company chain materials '+marker,'parent_item_group':'All Item Groups','is_group':0}).insert(ignore_permissions=True)
        # Metadata qualification is performed later through the Company's public
        # registration service; this fixture creates ordinary native UOM masters.
        uom=frappe.get_doc({'doctype':'UOM','uom_name':'Company chain quantity '+marker,'symbol':'chain'+marker,'enabled':1,'must_be_whole_number':0}).insert(ignore_permissions=True)
        for key,company in (('a',company_a),('b',company_b)):
            item=frappe.get_doc({'doctype':'Item','item_code':'CHAIN-'+key+'-'+marker,'item_name':'Company chain authored material '+key+' '+marker,
                                 'item_group':item_group.name,'stock_uom':uom.name,'is_stock_item':0,'item_defaults':[{'company':company}]}).insert(ignore_permissions=True)
            native[key]['item']=item.name
        for key in ('author','alias','reviewer'):
            if duty_rows(current_actor(users[key]['user'])):
                raise AssertionError('A Company-only fixture identity acquired Project duties.')
    # Persist credentials privately before the first commit. If a later domain
    # prerequisite fails, this unique fixture is recoverable without resetting
    # User/Auth rows or losing the identities already committed by setup.
    _save_private_fixture({'fixture_id':'company-chain-'+marker,'site':frappe.local.site,'company':company_a,'other_company':company_b,
                           'users':users,'native':native,'native_unit':uom.name,'native_role':role,'reviewer_native_role':reviewer_role,'setup_status':'prerequisites_created'})
    frappe.db.commit()
    from cipher_aec.estimating.company_service import register_unit
    qualified_unit=register_unit(company_a,str(uuid4()),uom.name,'count',6)['unit']
    frappe.db.commit()
    # This is a separate explicitly Project-only control, never a stand-in for
    # the preaward Company workflow. It also makes fresh-site control evidence
    # meaningful when earlier checkpoint rows do not exist on a new CI site.
    from cipher_aec.projects.service import create_task
    from cipher_aec.api.contracts import version_of
    frappe.set_user(users['project_only']['user'])
    operation=str(uuid4())
    task=create_task(company=company_b,project=project.name,operation_id=operation,expected_version=version_of(frappe.get_doc('Project',project.name)),subject='Independent Project control '+marker)
    frappe.db.commit()
    frappe.set_user('Administrator')
    project_control={'project':project.name,'operation_id':operation,'task_id':task['task']['id'],'immutable_rows':_capture_project_controls(project.name)}
    value={'fixture_id':'company-chain-'+marker,'created_at':datetime.now(timezone.utc).isoformat(),'site':frappe.local.site,'company':company_a,'other_company':company_b,
           'users':users,'native':native,'native_unit':uom.name,'qualified_unit':qualified_unit,'native_role':role,'reviewer_native_role':reviewer_role,'project_only_control':project.name,'project_receipt_control':project_control,'historical_project_control':historical,
           'native_financial_before':_native_financial_inventory(company_a),
           'project_count_before_company_journey':frappe.db.count('Project'),'qualification':'Fixture setup only; no DOC/estimate/approval/proposal outcome qualified yet.'}
    value['setup_status']='ready';private_path=_save_private_fixture(value)
    return {**{key:item for key,item in value.items() if key!='users'},'users':{key:{'user':user['user'],'person':user['person']} for key,user in users.items()},
            'private_manifest':str(private_path.resolve())}


def _load_fixture(private_manifest):
    import frappe
    _administrator()
    base=Path(frappe.get_site_path('private','cipher-fixtures')).resolve()
    path=Path(private_manifest).resolve()
    if not path.is_relative_to(base) or not path.name.startswith('company-chain-') or not path.name.endswith('.secret.json'):
        raise RuntimeError('Only this fixture namespace may be loaded.')
    value=json.loads(path.read_text())
    marker=value['fixture_id'].removeprefix('company-chain-')
    if value['site']!=frappe.local.site or value['company']!='Company chain A '+marker or value['other_company']!='Company chain B '+marker:
        raise RuntimeError('Fixture scope and site do not match.')
    if any(not actor['user'].startswith('company.chain.') or not actor['user'].endswith('.'+marker+'@cipher.example') for actor in value['users'].values()):
        raise RuntimeError('Refusing any non-fixture identity.')
    return value


def set_fixture_duty(private_manifest, role, ability, active):
    """Reversible one-scope revocation, never a global reseed or new grant."""
    import frappe
    from cipher_aec.governance.context import COMPANY_ABILITIES, trusted_write
    fixture=_load_fixture(private_manifest)
    if role not in ('author','reviewer','outsider') or ability not in COMPANY_ABILITIES or type(active) is not int or active not in (0,1):
        raise RuntimeError('Declare one fixture role, Company ability and integer active flag.')
    company=fixture['other_company'] if role=='outsider' else fixture['company']
    person=fixture['users'][role]['person']
    rows=frappe.db.sql("SELECT name FROM `tabCipher Project Duty` WHERE person=%s AND company=%s AND scope_type='Company' AND (project IS NULL OR project='') AND ability=%s",(person,company,ability))
    if len(rows)!=1:
        raise RuntimeError('Only an existing exact Company duty may be toggled.')
    with trusted_write():
        duty=frappe.get_doc('Cipher Project Duty',rows[0][0]);duty.active=active;duty.save(ignore_permissions=True)
    frappe.db.commit()
    return {'fixture_id':fixture['fixture_id'],'scope_type':'Company','company':company,'role':role,'ability':ability,'active':active}


def set_fixture_party_association(private_manifest, active):
    """Move only the owned Customer's account association between fixture Companies.

    Native read role remains granted, so this tests Company association separately
    from native-read permission. Restoring it changes the native version; a stale
    unconsumed review must not be silently revived by the restoration.
    """
    import frappe
    from cipher_aec.governance.context import trusted_write
    fixture=_load_fixture(private_manifest)
    if type(active) is not int or active not in (0,1):
        raise RuntimeError('Declare an integer active flag.')
    company=fixture['company'] if active else fixture['other_company']
    native=frappe.get_doc('Company',company)
    with trusted_write():
        customer=frappe.get_doc('Customer',fixture['native']['a']['customer'])
        customer.set('accounts',[{'company':company,'account':native.default_receivable_account}]);customer.save(ignore_permissions=True)
    frappe.db.commit()
    return {'fixture_id':fixture['fixture_id'],'native_company_association_available':bool(active),'native_read_role_unchanged':True}


def set_fixture_reviewer_native_permission(private_manifest, doctype, active):
    """Toggle only owned reviewer's native role; no User/Auth writes or bypasses."""
    import frappe
    from frappe.permissions import update_permission_property
    fixture=_load_fixture(private_manifest)
    if doctype not in ('UOM','Currency','Customer','Item') or type(active) is not int or active not in (0,1):
        raise RuntimeError('Declare one supported native read master and integer flag.')
    role=fixture['reviewer_native_role'];user=fixture['users']['reviewer']['user']
    if not role.endswith(fixture['fixture_id'].removeprefix('company-chain-')) or role not in frappe.get_roles(user):
        raise RuntimeError('The owned reviewer native role no longer matches this fixture.')
    for permission in ('read','select'):update_permission_property(doctype,role,0,permission,active)
    frappe.db.commit();frappe.clear_cache(user=user)
    target={'UOM':fixture['native_unit'],'Currency':'USD','Customer':fixture['native']['a']['customer'],'Item':fixture['native']['a']['item']}[doctype]
    actual=bool(frappe.has_permission(doctype,'read',doc=target,user=user))
    if actual!=bool(active):raise AssertionError('The fixture did not establish the intended real native permission.')
    if not frappe.has_permission(doctype,'read',doc=target,user=fixture['users']['author']['user']):
        raise AssertionError('Reviewer-only native revocation also removed executor authority.')
    return {'fixture_id':fixture['fixture_id'],'role':'reviewer','doctype':doctype,'native_read_available':actual,'executor_native_read_retained':True}


def fixture_readback(private_manifest):
    import frappe
    from cipher_aec.governance.context import current_actor, duty_rows, company_duty_rows
    fixture=_load_fixture(private_manifest)
    actors={}
    for role,credentials in fixture['users'].items():
        actor=current_actor(credentials['user'])
        actors[role]={'person':actor.person_id,'project_duty_count':len(duty_rows(actor)),
                      'company_duties':[{'company':row.company,'ability':row.ability} for row in company_duty_rows(actor)]}
    if any(actors[role]['project_duty_count'] for role in ('author','alias','reviewer','outsider')):
        raise AssertionError('A Company-only actor acquired Project authority.')
    if actors['project_only']['company_duties']:
        raise AssertionError('Project duties acquired Company authority.')
    control=verify_historical_project_controls(fixture['historical_project_control']) if fixture['historical_project_control'] else {'status':'not_qualified','reason':'Fresh site has no earlier checkpoint records; separate Project-only fixture control applies.'}
    own_control=verify_historical_project_controls(fixture['project_receipt_control']['immutable_rows'])
    if frappe.db.count('Project',{'company':fixture['company']}):
        raise AssertionError('The preaward Company acquired a fake Project.')
    financial=_native_financial_inventory(fixture['company'])
    if financial!=fixture['native_financial_before'] or any(financial.values()):
        raise AssertionError('The Company preaward journey created an unsupported native financial effect.')
    return {'fixture_id':fixture['fixture_id'],'project_count':frappe.db.count('Project'),'primary_company_project_count':0,
            'project_count_before_company_journey':fixture['project_count_before_company_journey'],
            'actors':actors,'historical_project_control':control,'project_only_receipt_control':own_control,'scope_types_explicit':True,
            'native_financial_unchanged':financial,'global_project_count_is_observational':'Other isolated fixture owners may append unrelated Projects; primary Company must have exactly zero.'}


def _native_financial_inventory(company):
    """Company-local absence proof; native COM drafts are checked separately."""
    import frappe
    result={}
    for doctype in ('Sales Order','Sales Invoice','Delivery Note','Purchase Order','Purchase Invoice','Purchase Receipt',
                    'Payment Entry','Journal Entry','Stock Entry','Expense Claim','Timesheet','Material Request','GL Entry','Stock Ledger Entry'):
        if not frappe.db.exists('DocType',doctype):continue
        if not frappe.get_meta(doctype).has_field('company'):
            raise RuntimeError('A supported native financial inventory no longer exposes Company scope: '+doctype)
        result[doctype]=frappe.db.count(doctype,{'company':company})
    return result


def fixture_private_source(private_manifest, revision_id):
    """Bench-only locator for exact native File download probes, no metadata RPC."""
    import frappe
    fixture=_load_fixture(private_manifest)
    revision=frappe.get_doc('Cipher Document Revision',revision_id)
    if revision.company!=fixture['company'] or revision.scope_type!='Company' or revision.project:
        raise RuntimeError('Only the owned no-Project Company source may be inspected.')
    document=frappe.get_doc('Cipher Document',revision.document)
    if fixture['fixture_id'].removeprefix('company-chain-') not in document.title:
        raise RuntimeError('Only the explicitly authored fixture source may be inspected.')
    source=frappe.get_doc('File',revision.storage_reference)
    if not source.is_private or source.attached_to_doctype!='Cipher Document Revision' or source.attached_to_name!=revision_id or not source.file_url.startswith('/private/files/'):
        raise AssertionError('Canonical Company source has no exact private File attachment.')
    return {'company':fixture['company'],'revision_id':revision_id,'private_file_url':source.file_url,'sha256':revision.sha256,'byte_length':revision.byte_length}


def fixture_generated_projection(private_manifest, document_id, role, denied):
    """Native SQL count/Long Text proof under the HTTP phase's current actor."""
    import frappe
    from cipher_aec.governance.context import require_company
    fixture=_load_fixture(private_manifest)
    if role not in ('author','reviewer') or type(denied) is not bool:
        raise RuntimeError('Declare one owned source reader and boolean denied expectation.')
    parent=frappe.get_doc('Cipher Document',document_id)
    if parent.company!=fixture['company'] or parent.scope_type!='Company' or parent.project or parent.producer_kind!='commercial.proposal.output.v1':
        raise RuntimeError('Only the exact owned generated Company output may be inspected.')
    revision=frappe.get_doc('Cipher Document Revision',parent.current_revision)
    user=fixture['users'][role]['user'];frappe.set_user(user)
    try:
        require_company(fixture['company'],ability='document.read')
        result={}
        for doctype,name,fields in (('Cipher Document',parent.name,['name','producer_binding_json']),
                                    ('Cipher Document Revision',revision.name,['name','pages_json','generation_json']),
                                    ('File',revision.storage_reference,['name','file_url'])):
            rows=frappe.get_list(doctype,filters={'name':name},fields=fields,limit_page_length=2)
            counted=frappe.get_list(doctype,filters={'name':name},fields=[{'COUNT':'name','as':'count'}])
            count=int(counted[0]['count']) if counted else 0
            expected=0 if denied else 1
            if len(rows)!=expected or count!=expected:
                raise AssertionError('Native generated-source row/Long Text/count authorization disagreed: '+doctype)
            result[doctype]={'visible_rows':len(rows),'exact_count':count,'long_text_returned':bool(rows) and doctype!='File'}
        return {'status':'passed','role':role,'document_read_retained':True,'source_denied':denied,'projections':result}
    finally:
        frappe.set_user('Administrator')


class NativeCompanyRPC:
    """Real domain/API integration via explicit synthetic Session fixtures.

    Invokes each API's undecorated business function so native errors remain
    visible. It does not claim HTTP/CSRF coverage; the separate HTTP procedure
    exercises the decorated wire boundary and actual authenticated cookies.
    """
    def __init__(self, fixture):
        import frappe
        self.fixture=fixture
        self.saved_request=getattr(frappe.local,'request',None)
        self.saved_sid=getattr(frappe.session,'sid',None)
        self.calls=[]

    def login(self, role):
        import frappe
        from frappe.utils import now_datetime
        from werkzeug.test import EnvironBuilder
        from werkzeug.wrappers import Request
        from cipher_aec.api.contracts import canonical_json
        user=self.fixture['users'][role]['user']
        frappe.set_user(user)
        sid='explicit-company-chain-session-'+uuid4().hex
        frappe.session.sid=sid
        frappe.local.request=Request(EnvironBuilder(method='POST',base_url='http://cipher.localhost',headers={'Cookie':'sid='+sid}).get_environ())
        frappe.db.sql("INSERT INTO tabSessions(user,sid,sessiondata,lastupdate,status) VALUES(%s,%s,%s,%s,'Active')",(user,sid,canonical_json({'user':user}),now_datetime()))
        frappe.db.commit()
        self.role=role

    def invoke(self, method, values=None, expected_codes=()):
        import frappe
        import importlib
        import inspect
        from cipher_aec.api.errors import DomainError
        namespace,name=method.rsplit('.',1)
        if namespace not in {'cipher_aec.documents.api','cipher_aec.estimating.api','cipher_aec.documents.company_api','cipher_aec.estimating.company_api','cipher_aec.takeoff.company_api',
                             'cipher_aec.commercial.api','cipher_aec.api.masters','cipher_aec.api.company_approvals','cipher_aec.api.company','cipher_aec.api.v1'}:
            raise RuntimeError('Only the explicit integration route namespaces may be invoked.')
        function=inspect.unwrap(getattr(importlib.import_module(namespace),name))
        try:
            result=function(**(values or {}))
        except DomainError as error:
            self.calls.append({'role':self.role,'method':method,'status':'denied','error_code':error.code})
            frappe.db.rollback()
            if error.code not in expected_codes:
                raise
            return {'error_code':error.code}
        if expected_codes:
            raise AssertionError('An expected native domain denial succeeded: '+method)
        self.calls.append({'role':self.role,'method':method,'status':'passed'})
        frappe.db.commit()
        return result

    def close(self):
        import frappe
        frappe.db.rollback()
        frappe.set_user('Administrator')
        frappe.local.request=self.saved_request
        frappe.session.sid=self.saved_sid


def authored_company_inputs(fixture, source, unit_id):
    """Exact authored/manual data; no drawing calibration or provider claim."""
    marker=fixture['fixture_id'].removeprefix('company-chain-')
    citation={key:source[key] for key in ('revision_id','page','excerpt_sha256','source_sha256')}
    rate={'title':'Explicit Company chain native material '+marker,'cost_type':'material','unit_id':unit_id,'rate_amount':'12.34','rate_precision':6,
          'currency':'USD','quote_reference':'Explicit authored Company chain '+marker,'quote_date':'2026-10-15','expiry_date':None,
          'geography':'Explicit synthetic fixture','inclusions':'Authored fixture material','exclusions':'No tax or freight','freight_tax_assumptions':'No tax or freight in this fixture',
          'permission_basis':'Source authored explicitly for synthetic integration qualification','source_citations':[citation],'item':fixture['native']['a']['item']}
    line={'line_id':str(uuid4()),'description':'Explicit manual authored quantity','quantity':{'amount':'2.500000','unit_id':unit_id,'precision':6},
          'cost_code':'CHAIN-01','notes':'Manual authored amount; no calibrated geometry claim','alternate':'','included':True,
          'material_factor':'1','waste_fraction':'0'}
    return {'citation':citation,'rate':rate,'line':line,'expected_direct':'30.85','qualification':'Authored manual quantity and exact rate only; no calibrated takeoff/model/provider qualification.'}


def drive_manual_estimate(rpc, fixture, label):
    """Independent Company DOC→Pursuit→manual estimate→human acceptance spine.

    The caller chooses native Session fixtures or actual HTTP. All operations
    retain their original UUID/payload for replay; no provider is involved.
    """
    import base64
    from copy import deepcopy
    from cipher_aec.api.contracts import digest
    company=fixture['company'];marker=fixture['fixture_id'].removeprefix('company-chain-')
    docs='cipher_aec.documents.company_api.';est='cipher_aec.estimating.company_api.';gov='cipher_aec.api.company_approvals.'
    checks=[];operations={};payloads={}
    def command(name, body):
        values={'company':company,'operation_id':str(uuid4()),**body}
        payloads[values['operation_id']]={'method':name,'values':deepcopy(values)}
        return values,rpc.invoke(name,values)
    def scoped(value, legacy_company=False):
        if value.get('company')!=company or value.get('project') is not None or value.get('scope_type','Company')!='Company':
            raise AssertionError('A Company record did not preserve its no-Project scope.')
        if not legacy_company and (value.get('scope_type')!='Company' or 'project' not in value):
            raise AssertionError('The declared explicit Company DTO scope fields are missing.')
    rpc.login('author')
    content=('Explicit synthetic Company chain '+marker+' '+label+'\nAuthored material rate USD12.34 per fixture quantity.\f'
             'Explicit manual quantity2.500000; exact direct amount USD30.85. No calibrated geometry or external quote authority.').encode()
    upload,uploaded=command(docs+'upload_document',{'title':'Company chain source '+label+' '+marker,'filename':'company-chain-source.txt',
        'content_base64':base64.b64encode(content).decode(),'byte_length':len(content),'sha256':hashlib.sha256(content).hexdigest()})
    operations['upload']=upload['operation_id']
    scoped(uploaded['document']);scoped(uploaded['revision'])
    if uploaded['revision']['sha256']!=hashlib.sha256(content).hexdigest() or uploaded['revision']['page_count']!=2:
        raise AssertionError('Actual stored Company bytes/page extraction did not match the authored source.')
    rpc.login('alias');again=rpc.invoke(docs+'upload_document',upload)
    if not again['operation']['replayed'] or again['revision']['id']!=uploaded['revision']['id']:
        raise AssertionError('Canonical-person Company upload retry duplicated its immutable source.')
    changed=deepcopy(upload);changed['title']+=' changed'
    rpc.invoke(docs+'upload_document',changed,expected_codes={'operation_conflict'})
    rpc.login('author')
    citation=rpc.invoke(docs+'get_citation',{'company':company,'revision_id':uploaded['revision']['id'],'page':1})
    scoped(citation)
    preview=rpc.invoke(docs+'preview_revision',{'company':company,'revision_id':uploaded['revision']['id'],'page':2})
    search=rpc.invoke(docs+'search_documents',{'company':company,'query':'12.34','limit':8})
    if not search['items']:
        raise AssertionError('Company source search did not return the known authored excerpt.')
    checks.append('actual_company_bytes_pages_citations_search_and_canonical_alias_replay')
    for role in ('outsider','project_only'):
        rpc.login(role)
        rpc.invoke(docs+'get_document',{'company':company,'document_id':uploaded['document']['id']},expected_codes={'not_found','capability_denied'})
        rpc.invoke(docs+'list_documents',{'company':company},expected_codes={'not_found','capability_denied'})
    rpc.login('author')
    rpc.invoke(docs+'get_document',{'company':fixture['other_company'],'document_id':uploaded['document']['id']},expected_codes={'not_found','capability_denied'})
    rpc.invoke('cipher_aec.documents.api.get_document',{'company':company,'document_id':uploaded['document']['id']},expected_codes={'not_found','capability_denied'})
    checks.append('company_project_namespaces_and_foreign_company_authority_are_isolated')
    pursuit_args,pursuit=command('cipher_aec.commercial.api.create_pursuit',{'party_type':'Customer','party_id':fixture['native']['a']['customer'],
        'fields':{'title':'Company chain '+label+' '+marker,'sector':'Explicit synthetic infrastructure'}})
    pursuit=pursuit['pursuit'];scoped(pursuit,legacy_company=True)
    inputs=authored_company_inputs(fixture,citation,fixture['qualified_unit']['id'])
    rate_args,rate=command(est+'create_rate',{'rate':inputs['rate']});rate=rate['rate_source'];scoped(rate)
    rate_foreign=deepcopy(rate_args);rate_foreign['operation_id']=str(uuid4());rate_foreign['rate']['item']=fixture['native']['b']['item']
    rpc.invoke(est+'create_rate',rate_foreign,expected_codes={'not_found'})
    estimate_args,estimate=command(est+'create_estimate',{'title':'Company manual estimate '+label+' '+marker,'currency':'USD','pricing_date':'2026-10-15','pursuit_id':pursuit['id']})
    estimate=estimate['estimate'];scoped(estimate)
    if estimate['pursuit_id']!=pursuit['id']:
        raise AssertionError('The exact same-Company Pursuit source link was not preserved.')
    line={**inputs['line'],'rate_source_id':rate['id']}
    calculate,calculated=command(est+'calculate_revision',{'estimate_id':estimate['id'],'expected_revision':None,'lines':[line],'adjustments':[],
        'conversion_ids':[],'basis_description':'Explicit manual Company estimate; no calibrated geometry claim','basis_citations':[inputs['citation']]})
    operations['calculate']=calculate['operation_id']
    for name in ('estimate','revision','calculation'):scoped(calculated[name])
    if calculated['revision']['total']['amount']!=inputs['expected_direct'] or calculated['revision']['direct']['amount']!=inputs['expected_direct']:
        raise AssertionError('The exact authored Company quantity/rate calculation changed.')
    rpc.login('alias');again=rpc.invoke(est+'calculate_revision',calculate)
    if not again['operation']['replayed'] or again['revision']['id']!=calculated['revision']['id']:
        raise AssertionError('The Company estimate retry duplicated its immutable calculation.')
    rpc.login('author')
    original=rpc.invoke(est+'get_record',{'company':company,'kind':'revision','record_id':calculated['revision']['id']})
    if original!=calculated['revision']:
        raise AssertionError('Immutable Company revision readback changed before review.')
    checks.append('pursuit_linked_company_manual_estimate_exact30_85_and_single_calculation_retry')
    request,packet=command(gov+'request_action',{'action':'estimate.accept.v1','subject_id':original['id'],'expected_version':digest(original)})
    packet=packet['packet'];scoped(packet)
    decision={'company':company,'packet_id':packet['id'],'manifest_hash':packet['manifest_hash'],'decision':'Grant','reason':'Independent synthetic Company estimate review','operation_id':str(uuid4())}
    rpc.login('alias');rpc.invoke(gov+'decide_packet',decision,expected_codes={'independent_review_required','independent_estimate_required'})
    rpc.login('reviewer');decision['operation_id']=str(uuid4());granted=rpc.invoke(gov+'decide_packet',decision)
    if granted['packet']['state']!='Granted':raise AssertionError('Independent Company review was not granted.')
    rpc.login('author')
    # The canonical engine exposes requester's execution, separate from review.
    execute,accepted=command(gov+'execute_packet',{'packet_id':packet['id'],'manifest_hash':packet['manifest_hash']})
    operations['accept']=execute['operation_id']
    if accepted['packet']['state']!='Consumed':raise AssertionError('Company acceptance did not consume the exact grant.')
    rpc.login('alias');retry=rpc.invoke(gov+'execute_packet',execute)
    if not retry['operation']['replayed'] or retry['effect']!=accepted['effect']:
        raise AssertionError('Consumed Company estimate acceptance did not replay its original effect.')
    checks.append('independent_company_human_review_and_one_accepted_baseline_consumption')
    rpc.login('author')
    return {'label':label,'company':company,'document':uploaded['document'],'source_revision':uploaded['revision'],'citation':citation,
            'pursuit':pursuit,'rate':rate,'estimate':estimate,'calculated':calculated,'acceptance_packet':packet,'accepted':accepted,
            'operations':operations,'payloads':payloads,'reviewer_decision':decision,'checks':checks,'preview_checked':bool(preview),
            'manual_quantity_qualified':True,'calibrated_company_takeoff_qualified':False,'live_model_qualified':False,'external_provider_qualified':False}


def company_history_inventory(rpc, company):
    """Read actual authorized pages and compare the exact count to those pages."""
    values={'company':company,'limit':200,'count_mode':'exact'}
    events=[];seen=set();total=None
    for _ in range(20):
        page=rpc.invoke('cipher_aec.api.company.history',values)
        if total is None:total=page['total']
        if page['total']!=total:raise AssertionError('The isolated Company history changed while paging.')
        for event in page['items']:
            if event['id'] in seen:raise AssertionError('Company history paging duplicated an event.')
            seen.add(event['id']);events.append(event)
        cursor=page.get('next_cursor')
        if cursor is None:
            if len(events)!=total:raise AssertionError('Company exact count exposed a different set from its authorized pages.')
            return {'items':events,'total':total}
        if not cursor:raise AssertionError('Company history omitted its next cursor.')
        values={**values,'cursor':cursor}
    raise AssertionError('The bounded isolated Company history unexpectedly exceeded4000 events.')


def assert_current_chain_access(rpc, context):
    """Read original immutable sources, consumed packet and completed receipts."""
    from cipher_aec.api.contracts import digest
    company=context['company'];est='cipher_aec.estimating.company_api.'
    rpc.login('author')
    actual=rpc.invoke(est+'get_record',{'company':company,'kind':'revision','record_id':context['calculated']['revision']['id']})
    if actual!=context['calculated']['revision']:raise AssertionError('Historical Company calculation changed.')
    acceptance=context['accepted']['effect']['acceptance']
    actual=rpc.invoke(est+'get_record',{'company':company,'kind':'acceptance','record_id':acceptance['id']})
    if actual!=acceptance:raise AssertionError('The original accepted Company baseline changed.')
    packet=rpc.invoke('cipher_aec.api.company_approvals.read_packet',{'company':company,'packet_id':context['acceptance_packet']['id']})
    if packet['state']!='Consumed':raise AssertionError('Historical Company grant consumption disappeared.')
    for name in ('upload','calculate','accept'):
        result=rpc.invoke('cipher_aec.api.company.operation',{'company':company,'operation_id':context['operations'][name]})
        if not result['operation']['replayed']:raise AssertionError('An original Company receipt lost replay identity.')
    history=company_history_inventory(rpc,company)
    targets={context['calculated']['revision']['id'],acceptance['id'],context['acceptance_packet']['id']}
    if not targets.issubset({row['subject_id'] for row in history['items']}):
        raise AssertionError('Authorized Company history omitted a known revision/baseline/packet event.')
    return {'history':history,'acceptance_id':acceptance['id'],'acceptance_digest':digest(acceptance),'revision_digest':digest(context['calculated']['revision'])}


def assert_company_document_revoked(rpc, context, before):
    """Call only while document.read is revoked but company.read remains active.

    Mutation/restore belongs to the explicit native fixture helper or the root
    operator. This procedure never grants itself authority through an HTTP API.
    """
    company=context['company'];docs='cipher_aec.documents.company_api.';est='cipher_aec.estimating.company_api.'
    denied={'not_found','capability_denied'}
    rpc.login('author')
    probes=[(docs+'get_document',{'company':company,'document_id':context['document']['id']}),
            (docs+'preview_revision',{'company':company,'revision_id':context['source_revision']['id'],'page':1}),
            (docs+'get_citation',{'company':company,'revision_id':context['source_revision']['id'],'page':1}),
            (docs+'download_revision',{'company':company,'revision_id':context['source_revision']['id']}),
            (docs+'search_documents',{'company':company,'query':'12.34','limit':8}),
            (est+'get_record',{'company':company,'kind':'revision','record_id':context['calculated']['revision']['id']}),
            (est+'get_record',{'company':company,'kind':'acceptance','record_id':context['accepted']['effect']['acceptance']['id']}),
            ('cipher_aec.api.company_approvals.read_packet',{'company':company,'packet_id':context['acceptance_packet']['id']})]
    for method,values in probes:rpc.invoke(method,values,expected_codes=denied)
    for name in ('upload','calculate','accept'):
        operation=context['operations'][name]
        rpc.invoke('cipher_aec.api.company.operation',{'company':company,'operation_id':operation},expected_codes=denied)
        original=context['payloads'][operation]
        rpc.invoke(original['method'],original['values'],expected_codes=denied)
    history=company_history_inventory(rpc,company)
    source_subjects={context['document']['id'],context['source_revision']['id'],context['rate']['id'],context['calculated']['revision']['id'],
                     context['accepted']['effect']['acceptance']['id'],context['acceptance_packet']['id']}
    if source_subjects.intersection(row['subject_id'] for row in history['items']):
        raise AssertionError('Revoked Company source identity remained visible through history.')
    if not history['total']<before['history']['total']:
        raise AssertionError('Company exact history count retained the revoked source inventory.')
    return {'status':'passed','denied_read_and_completed_receipt_probes':len(probes)+6,
            'visible_history_before':before['history']['total'],'visible_history_after':history['total'],
            'company_read_retained':True,'source_subjects_absent':True}


def drive_stale_successor(rpc, context):
    """A granted revision cannot be accepted after a new calculation is current.

    No unrelated quote upload is treated as a pinned-rate change. This mutates
    the declared current estimate pointer through its supported public command.
    """
    from copy import deepcopy
    from cipher_aec.api.contracts import digest
    company=context['company'];est='cipher_aec.estimating.company_api.';gov='cipher_aec.api.company_approvals.'
    rpc.login('author')
    baseline=context['accepted']['effect']['acceptance'];baseline_digest=digest(baseline)
    payload=deepcopy(context['payloads'][context['operations']['calculate']]['values'])
    payload.update(operation_id=str(uuid4()),expected_revision=context['calculated']['revision']['id'])
    payload['lines'][0]['quantity']['amount']='3.000000'
    second=rpc.invoke(est+'calculate_revision',payload)
    if second['revision']['total']['amount']!='37.02':raise AssertionError('The explicit successor calculation was not exactly37.02.')
    requested={'company':company,'operation_id':str(uuid4()),'action':'estimate.accept.v1','subject_id':second['revision']['id'],'expected_version':digest(second['revision'])}
    packet=rpc.invoke(gov+'request_action',requested)['packet']
    rpc.login('reviewer')
    rpc.invoke(gov+'decide_packet',{'company':company,'packet_id':packet['id'],'manifest_hash':packet['manifest_hash'],
        'decision':'Grant','reason':'Independent review before supported successor calculation','operation_id':str(uuid4())})
    rpc.login('author')
    payload.update(operation_id=str(uuid4()),expected_revision=second['revision']['id'])
    payload['lines'][0]['quantity']['amount']='4.000000'
    third=rpc.invoke(est+'calculate_revision',payload)
    if third['revision']['total']['amount']!='49.36':raise AssertionError('The next explicit calculation was not exactly49.36.')
    stale=rpc.invoke(gov+'read_packet',{'company':company,'packet_id':packet['id']})
    if stale['state']!='Stale':raise AssertionError('A changed estimate head left an old grant executable.')
    attempt={'company':company,'operation_id':str(uuid4()),'packet_id':packet['id'],'manifest_hash':packet['manifest_hash']}
    rpc.invoke(gov+'execute_packet',attempt,expected_codes={'approval_not_executable','stale_estimate','stale_estimate_acceptance'})
    old=rpc.invoke(est+'get_record',{'company':company,'kind':'acceptance','record_id':baseline['id']})
    accepted=rpc.invoke(est+'list_acceptances',{'company':company,'estimate_id':context['estimate']['id']})
    if digest(old)!=baseline_digest or accepted['items']!=[baseline]:
        raise AssertionError('A stale grant created a baseline or rewrote the original accepted facts.')
    return {'status':'passed','stale_packet':packet['id'],'reviewed_revision':second['revision']['id'],
            'current_revision':third['revision']['id'],'original_acceptance':baseline['id'],'original_baseline_sha256':baseline_digest,
            'accepted_baseline_count':1,'source_policy':'Explicit supported current-estimate successor; pinned rates remain unchanged.'}


def run_native_manual_acceptance(private_manifest):
    """Explicit coordinated entry point; no implicit identity provisioning.

    This is deliberately not the final chain's canonical run_acceptance: COM02
    artifact/issue and Company calibrated geometry remain separately unqualified.
    """
    import frappe
    fixture=_load_fixture(private_manifest);rpc=NativeCompanyRPC(fixture)
    report={'schema':'cipher.r1.company-manual-native-acceptance.v1','status':'failed','fixture_id':fixture['fixture_id'],
            'company':fixture['company'],'started_at':datetime.now(timezone.utc).isoformat(),
            'http_cookie_csrf_qualified':False,'calibrated_company_takeoff_qualified':False,'commercial_issue_qualified':False,
            'live_model_qualified':False,'external_provider_qualified':False}
    try:
        context=drive_manual_estimate(rpc,fixture,'native')
        fixture['native_manual_context']=context;_save_private_fixture(fixture)
        report['checks']=context['checks']
        report['stale_successor']=drive_stale_successor(rpc,context)
        report['master_selectors']=assert_fixture_master_selectors(rpc,fixture)
        review=prepare_reviewer_native_revocation(rpc,context,report['stale_successor']['current_revision'])
        try:
            frappe.set_user('Administrator');set_fixture_reviewer_native_permission(private_manifest,'UOM',0)
            report['reviewer_native_revoked']=assert_reviewer_native_revoked(rpc,fixture,context,review)
        finally:
            frappe.set_user('Administrator');set_fixture_reviewer_native_permission(private_manifest,'UOM',1)
        rpc.login('author')
        restored_review=rpc.invoke('cipher_aec.api.company_approvals.execute_packet',review['execute'])
        if restored_review['packet']['state']!='Consumed':raise AssertionError('Restored reviewer native rights did not permit the exact original grant.')
        report['reviewer_native_restored']={'packet_id':review['packet']['id'],'original_operation_id':review['execute']['operation_id'],'state':'Consumed'}
        before=assert_current_chain_access(rpc,context)
        try:
            frappe.set_user('Administrator');set_fixture_duty(private_manifest,'author','document.read',0)
            report['source_revoked']=assert_company_document_revoked(rpc,context,before)
        finally:
            frappe.set_user('Administrator');set_fixture_duty(private_manifest,'author','document.read',1)
        restored=assert_current_chain_access(rpc,context)
        if restored['history']!=before['history']:
            raise AssertionError('Restored Company source rights did not recover the exact historical authorized set.')
        report['restored']={'history_exact_count':restored['history']['total'],'original_acceptance_sha256':restored['acceptance_digest']}
        frappe.set_user('Administrator')
        report['readback']=fixture_readback(private_manifest)
        report['status']='passed'
        # The next HTTP/source phases can read this private context without
        # reconstructing any command from an evidence summary.
        fixture['native_manual_context']=context;_save_private_fixture(fixture)
        return report
    except Exception as error:
        report['failure_type']=type(error).__name__
        raise
    finally:
        rpc.close()
        report['calls']=rpc.calls
        report['completed_at']=datetime.now(timezone.utc).isoformat()
        # Preserve an initial failed attempt separately; caller can inventory it
        # without claiming the unfinished manual or future COM chain passed.
        path=Path(private_manifest).with_name(fixture['fixture_id']+'.native-'+uuid4().hex+'.result.json')
        descriptor=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(descriptor,'w') as stream:json.dump(report,stream,indent=2,sort_keys=True);stream.write('\n')


def assert_fixture_master_selectors(rpc, fixture):
    """All five real selectors resolve explicit native choices in one Company."""
    rpc.login('author');company=fixture['company'];marker=fixture['fixture_id'].removeprefix('company-chain-')
    choices={'parties':({'party_type':'Customer','query':marker},fixture['native']['a']['customer']),
             'price_lists':({'query':fixture['native']['a']['price_list'],'currency':'USD'},fixture['native']['a']['price_list']),
             'units':({'query':fixture['native_unit'],'dimension':'count'},fixture['native_unit']),
             'currencies':({'query':'USD'},'USD'),
             'items':({'query':marker,'unit_id':fixture['qualified_unit']['id']},fixture['native']['a']['item'])}
    result={}
    for selector,(filters,target) in choices.items():
        page=rpc.invoke('cipher_aec.api.masters.'+selector,{'company':company,'count_mode':'exact','limit':50,**filters})
        if target not in {row['id'] for row in page['items']} or page['next_cursor'] is not None or page['total']!=len(page['items']):
            raise AssertionError('The explicit bounded native '+selector+' selector did not return its authorized fixture choice.')
        if selector in ('parties','items'):
            foreign=fixture['native']['b']['customer' if selector=='parties' else 'item']
            if foreign in {row['id'] for row in page['items']}:raise AssertionError('A native selector disclosed the other Company fixture.')
        result[selector]={'returned_target':target,'exact_count':page['total']}
    return result


def prepare_reviewer_native_revocation(rpc, context, revision_id):
    from cipher_aec.api.contracts import digest
    company=context['company'];gov='cipher_aec.api.company_approvals.'
    rpc.login('author')
    revision=rpc.invoke('cipher_aec.estimating.company_api.get_record',{'company':company,'kind':'revision','record_id':revision_id})
    packet=rpc.invoke(gov+'request_action',{'company':company,'operation_id':str(uuid4()),'action':'estimate.accept.v1',
        'subject_id':revision_id,'expected_version':digest(revision)})['packet']
    rpc.login('reviewer')
    rpc.invoke(gov+'decide_packet',{'company':company,'packet_id':packet['id'],'manifest_hash':packet['manifest_hash'],'decision':'Grant',
        'reason':'Independent review before reviewer-only native permission revocation','operation_id':str(uuid4())})
    history=company_history_inventory(rpc,company)
    original_receipt=rpc.invoke('cipher_aec.api.company.operation',{'company':company,'operation_id':context['reviewer_decision']['operation_id']})
    if original_receipt['packet']['id']!=context['acceptance_packet']['id'] or not original_receipt['operation']['replayed']:
        raise AssertionError('The reviewer historical decision receipt did not bind the accepted original source.')
    return {'packet':packet,'revision':revision,'reviewer_history_before':history,
            'execute':{'company':company,'packet_id':packet['id'],'manifest_hash':packet['manifest_hash'],'operation_id':str(uuid4())}}


def assert_reviewer_native_revoked(rpc, fixture, context, review):
    """Reviewer native rights are independent of the executor's native rights."""
    company=context['company'];est='cipher_aec.estimating.company_api.';gov='cipher_aec.api.company_approvals.'
    rpc.login('reviewer')
    units=rpc.invoke(est+'list_units',{'company':company})
    if fixture['qualified_unit']['id'] in {row['id'] for row in units['items']}:
        raise AssertionError('The Company unit catalog retained a native-denied UOM.')
    for kind,name in (('revision',review['revision']['id']),('acceptance',context['accepted']['effect']['acceptance']['id'])):
        rpc.invoke(est+'get_record',{'company':company,'kind':kind,'record_id':name},expected_codes={'not_found'})
    for packet_id in (review['packet']['id'],context['acceptance_packet']['id']):
        rpc.invoke(gov+'read_packet',{'company':company,'packet_id':packet_id},expected_codes={'not_found'})
    rpc.invoke('cipher_aec.api.company.operation',{'company':company,'operation_id':context['reviewer_decision']['operation_id']},expected_codes={'not_found'})
    rpc.invoke(gov+'decide_packet',context['reviewer_decision'],expected_codes={'not_found'})
    history=company_history_inventory(rpc,company)
    targets={review['revision']['id'],review['packet']['id'],context['accepted']['effect']['acceptance']['id'],context['acceptance_packet']['id']}
    if targets.intersection(row['subject_id'] for row in history['items']) or not history['total']<review['reviewer_history_before']['total']:
        raise AssertionError('Native-denied Company facts remained in reviewer history/counts.')
    rpc.login('author')
    actual=rpc.invoke(est+'get_record',{'company':company,'kind':'revision','record_id':review['revision']['id']})
    if actual!=review['revision']:raise AssertionError('Reviewer-only native denial removed executor access.')
    rpc.invoke(gov+'execute_packet',review['execute'],expected_codes={'reviewer_authority_revoked'})
    return {'status':'passed','reviewer_native_unit_omitted':True,'source_reads_and_packets_denied':True,
            'history_before':review['reviewer_history_before']['total'],'history_after':history['total'],'executor_read_retained':True,
            'grant_consumption_denied':'reviewer_authority_revoked'}

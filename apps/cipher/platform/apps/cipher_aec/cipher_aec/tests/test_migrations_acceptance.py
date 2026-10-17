"""Opt-in isolated actual ERPNext master export/preview acceptance; no import apply.

bench --site cipher.localhost execute cipher_aec.tests.test_migrations_acceptance.run_acceptance
"""
import copy
import json
import secrets
from uuid import uuid4


def run_acceptance():
    import frappe
    from cipher_aec.api.errors import DomainError
    from cipher_aec.governance.context import assert_synthetic_site, current_actor, trusted_write
    from cipher_aec.install import _binding, _grant, _person, _user
    from cipher_aec.migrations.export import FrappeTargetReader, export_records
    from cipher_aec.migrations.preview import preview_manifest
    from cipher_aec.migrations.validation import manifest_digest, parse_manifest, quantity_previews
    assert_synthetic_site()
    if frappe.session.user != "Administrator":
        raise RuntimeError("Explicit master fixture acceptance requires bench Administrator context")
    marker = uuid4().hex[:10]
    company = "Cipher Synthetic Company"
    administrator = current_actor()
    company_doc = frappe.get_doc("Company", company)
    user, person = f"migration.fixture.{marker}@cipher.example", "MIG-FIXTURE-" + marker
    with trusted_write():
        _person(person, "Explicit MIG-01 acceptance fixture")
        _user(user, "Explicit MIG-01 fixture", secrets.token_urlsafe(32))
        _binding(user, person)
        customer_group = frappe.get_doc({"doctype":"Customer Group","customer_group_name":"MIG-01 customers " + marker,
            "parent_customer_group":"All Customer Groups","is_group":0}).insert(ignore_permissions=True)
        supplier_group = frappe.get_doc({"doctype":"Supplier Group","supplier_group_name":"MIG-01 suppliers " + marker,
            "parent_supplier_group":"All Supplier Groups","is_group":0}).insert(ignore_permissions=True)
        territory = frappe.get_doc({"doctype":"Territory","territory_name":"MIG-01 territory " + marker,
            "parent_territory":"All Territories","is_group":0}).insert(ignore_permissions=True)
        customer = frappe.get_doc({"doctype":"Customer", "customer_name":"Synthetic MIG customer " + marker,
            "customer_type":"Company", "customer_group":customer_group.name, "territory":territory.name}).insert(ignore_permissions=True)
        supplier = frappe.get_doc({"doctype":"Supplier", "supplier_name":"Synthetic MIG supplier " + marker,
            "supplier_group":supplier_group.name, "supplier_type":"Company",
            "accounts":[{"company":company,"account":company_doc.default_payable_account}]}).insert(ignore_permissions=True)
        units = {}
        for key, whole in (("count",1),("inch",0),("foot",0)):
            unit = frappe.get_doc({"doctype":"UOM","uom_name":"MIG-01 " + key + " " + marker,"must_be_whole_number":whole}).insert(ignore_permissions=True)
            units[key] = unit
        group = frappe.get_doc({"doctype":"Item Group","item_group_name":"MIG-01 supplies " + marker,
            "parent_item_group":"All Item Groups","is_group":0}).insert(ignore_permissions=True)
        item = frappe.get_doc({"doctype":"Item","item_code":"MIG-01-" + marker,"item_name":"Synthetic MIG material " + marker,
            "item_group":group.name,"stock_uom":units["count"].name,"is_stock_item":0,
            "item_defaults":[{"company":company}]}).insert(ignore_permissions=True)
        parent = frappe.db.get_value("Cost Center",{"company":company,"is_group":1},"name")
        cost_center = frappe.get_doc({"doctype":"Cost Center","cost_center_name":"MIG-01 work " + marker,
            "cost_center_number":"MIG-" + marker,"company":company,"parent_cost_center":parent,"is_group":0}).insert(ignore_permissions=True)
        project = frappe.get_doc({"doctype":"Project","project_name":"MIG-01 export fixture " + marker,
            "company":company,"customer":customer.name,"status":"On hold"}).insert(ignore_permissions=True)
        for actor_person in (person,administrator.person_id):
            _grant(actor_person,company,project.name,"project.read")
    frappe.db.commit()
    ids = {key:str(uuid4()) for key in ("company","project","customer","supplier","item","count","inch","foot","cost_center")}
    references = [{"id":ids[key],"kind":kind,"name":name} for key,kind,name in (
        ("company","company",company),("project","project",project.name),("customer","customer",customer.name),
        ("supplier","supplier",supplier.name),("item","item",item.name),("cost_center","cost_center",cost_center.name))]
    for key in ("count","inch","foot"):
        references.append({"id":ids[key],"kind":"uom","name":units[key].name,
            "unit_definition":{"dimension":"count" if key=="count" else "length","precision":0 if key=="count" else 6}})
    conversions=[{"id":str(uuid4()),"revision":1,"from_unit_id":ids["inch"],"to_unit_id":ids["foot"],
                  "dimension":"length","numerator":"1","denominator":"12","source":"Synthetic declared exact example: 12 fixture inches = 1 fixture foot."}]
    quantities=[{"id":str(uuid4()),"amount":"12","unit_id":ids["inch"],"convert_to_unit_id":ids["foot"]}]
    dataset_id=str(uuid4())
    try:
        reader=FrappeTargetReader(company,project.name)
        before={d:frappe.db.count(d) for d in ("Company","Project","Customer","Supplier","Item","UOM","Cost Center")}
        exported=export_records(company=company,project=project.name,dataset_id=dataset_id,references=references,
            reader=reader,unit_conversions=conversions,quantities=quantities)
        manifest=parse_manifest(exported["manifest"])
        assert next(row for row in manifest["records"] if row["kind"]=="project")["fields"]["status"]=="On hold"
        again=export_records(company=company,project=project.name,dataset_id=dataset_id,references=list(reversed(references)),
            reader=reader,unit_conversions=conversions,quantities=quantities)
        assert exported["manifest_sha256"]==again["manifest_sha256"]
        preview=preview_manifest(manifest,reader.snapshot)
        assert all(row["action"]==("declaration_candidate" if row["kind"]=="uom" else "matches") for row in preview["records"]),preview
        assert all(row.get("warnings") for row in preview["records"] if row["kind"]=="uom")
        assert quantity_previews(manifest)[0]["exact_numerator"]=="1"
        assert quantity_previews(manifest)[0]["exact_denominator"]=="1"
        assert before=={d:frappe.db.count(d) for d in before}
        assert not exported["apply_available"] and exported["writes_performed"]==0

        stale=copy.deepcopy(manifest)
        next(row for row in stale["records"] if row["kind"]=="project")["target"]["version"]="unavailable-old-version"
        stale_preview=preview_manifest(stale,reader.snapshot)
        assert next(row for row in stale_preview["records"] if row["kind"]=="project")["action"]=="stale"

        frappe.set_user(user)
        private_reader=FrappeTargetReader(company,project.name)
        target=copy.deepcopy(manifest)
        supplier_row=next(row for row in target["records"] if row["kind"]=="supplier")
        denied=preview_manifest(target,private_reader.snapshot)
        supplier_row["target"]["name"]="MIG-01-missing-" + marker
        missing=preview_manifest(target,private_reader.snapshot)
        denied_row=next(row for row in denied["records"] if row["kind"]=="supplier")
        missing_row=next(row for row in missing["records"] if row["kind"]=="supplier")
        assert denied_row==missing_row and denied_row["action"]=="unavailable"
        assert not frappe.has_permission("Supplier","read",doc=supplier,user=user)
        failures=[]
        for refs in (references,[{**ref,"name":"MIG-01-missing-"+marker} if ref["kind"]=="supplier" else ref for ref in references]):
            try:
                export_records(company=company,project=project.name,dataset_id=dataset_id,references=refs,
                    reader=private_reader,unit_conversions=conversions,quantities=quantities)
                raise AssertionError("Native private master read bypass was accepted")
            except DomainError as error:
                failures.append((error.code,error.message,error.status))
        assert failures[0]==failures[1] and failures[0][0]=="target_unavailable"
        # Native read does not imply bulk export permission. This fixture role
        # changes only this isolated user; no normal application role is edited.
        frappe.set_user("Administrator")
        role="MIG-01 read-only " + marker
        frappe.get_doc({"doctype":"Role","role_name":role}).insert(ignore_permissions=True)
        from frappe.permissions import add_permission, update_permission_property
        for doctype in ("Company","Project","Customer","Supplier","Item","UOM","Cost Center"):
            add_permission(doctype,role,0)
            update_permission_property(doctype,role,0,"read",1)
            update_permission_property(doctype,role,0,"export",0)
        account=frappe.get_doc("User",user)
        account.append("roles",{"role":role})
        account.save(ignore_permissions=True)
        frappe.db.commit()
        frappe.clear_cache(user=user)
        frappe.set_user(user)
        read_only=FrappeTargetReader(company,project.name)
        assert read_only.fetch("supplier",supplier.name) is not None
        assert frappe.has_permission("Supplier","read",doc=supplier,user=user)
        assert not frappe.has_permission("Supplier","export",doc=supplier,user=user)
        assert read_only.fetch("supplier",supplier.name,for_export=True) is None
        try:
            export_records(company=company,project=project.name,dataset_id=dataset_id,references=references,
                reader=read_only,unit_conversions=conversions,quantities=quantities)
            raise AssertionError("Native read was incorrectly accepted as export authority")
        except DomainError as error:
            assert error.code=="target_unavailable"
        return {"schema":"cipher.r0.migration-acceptance.v1","status":"passed","label":"fresh-native-master-fixtures-real-frappe-read-only-export",
            "project":project.name,"user":user,"record_count":len(manifest["records"]),"manifest_sha256":manifest_digest(manifest),
            "kinds":sorted({row["kind"] for row in manifest["records"]}),
            "stable_uuid_reordered_export":True,"roundtrip_native_fields_match":True,"unregistered_uom_authority_not_inferred":True,"exact_rational_12_to_1":True,
            "stale_target_detected":True,"native_on_hold_roundtrip":True,"native_master_permission_enforced":True,"native_read_without_export_denied":True,
            "private_target_existence_indistinguishable":True,"export_preview_writes":0,"apply_import_available":False,
            "warnings":exported["warnings"],"fixture_native_names":{"customer":customer.name,"supplier":supplier.name,"item":item.name,"cost_center":cost_center.name,"units":{k:v.name for k,v in units.items()}},
            "qualification_limits":["No external source import or applied cutover.","UOM dimension/precision declarations are explicit synthetic inputs; no native-name dimensional inference or standards approval.","Source UUID bindings supplied explicitly; no persistent external-reference mapping created."]}
    finally:
        frappe.db.rollback()
        frappe.set_user("Administrator")


def prepare_http_fixture(project, user, native_export=0, supplier_read=1):
    """Own-fixture setup only; credentials enter by environment and never return."""
    import os
    from uuid import NAMESPACE_URL, uuid5
    import frappe
    from frappe.permissions import update_permission_property
    from cipher_aec.governance.context import assert_synthetic_site, trusted_write
    from cipher_aec.migrations.export import FrappeTargetReader, export_records
    assert_synthetic_site()
    if frappe.session.user != 'Administrator' or native_export not in (0,1) or supplier_read not in (0,1):
        raise RuntimeError('Explicit synthetic fixture administrator and boolean permission flags required')
    record=frappe.get_doc('Project',project)
    if not record.project_name.startswith('MIG-01 export fixture '):
        raise RuntimeError('This helper only accepts an isolated MIG-01 fixture project')
    marker=record.project_name.rsplit(' ',1)[1]
    if user != f'migration.fixture.{marker}@cipher.example':
        raise RuntimeError('This helper only accepts the matching isolated fixture user')
    role='MIG-01 read-only '+marker
    if not frappe.db.exists('Has Role',{'parent':user,'role':role}):
        raise RuntimeError('This isolated fixture must have its own existing native read-only role')
    for doctype in ('Company','Project','Customer','Supplier','Item','UOM','Cost Center'):
        update_permission_property(doctype,role,0,'read',supplier_read if doctype=='Supplier' else 1)
        update_permission_property(doctype,role,0,'export',native_export)
    password=os.environ.get('CIPHER_MIG_HTTP_PASSWORD')
    if password:
        from frappe.utils.password import update_password
        update_password(user,password,logout_all_sessions=True)
    frappe.clear_cache(user=user)
    frappe.db.commit()
    ids={key:str(uuid5(NAMESPACE_URL,'cipher:mig-http:'+project+':'+key)) for key in ('company','project','customer','supplier','item','cost_center','count','inch','foot')}
    refs=[{'id':ids[key],'kind':kind,'name':name} for key,kind,name in (
        ('company','company',record.company),('project','project',project),('customer','customer',record.customer),
        ('supplier','supplier','Synthetic MIG supplier '+marker),('item','item','MIG-01-'+marker),
        ('cost_center','cost_center',frappe.db.get_value('Cost Center',{'cost_center_number':'MIG-'+marker,'company':record.company},'name')))]
    for key in ('count','inch','foot'):
        refs.append({'id':ids[key],'kind':'uom','name':'MIG-01 '+key+' '+marker,
            'unit_definition':{'dimension':'count' if key=='count' else 'length','precision':0 if key=='count' else 6}})
    conversions=[{'id':str(uuid5(NAMESPACE_URL,'cipher:mig-http:'+project+':inch-foot')),'revision':1,
        'from_unit_id':ids['inch'],'to_unit_id':ids['foot'],'dimension':'length','numerator':'1','denominator':'12',
        'source':'Explicit synthetic HTTP qualification fixture: 12 fixture inches = 1 fixture foot.'}]
    quantities=[{'id':str(uuid5(NAMESPACE_URL,'cipher:mig-http:'+project+':quantity')),'amount':'12','unit_id':ids['inch'],'convert_to_unit_id':ids['foot']}]
    dataset_id=str(uuid5(NAMESPACE_URL,'cipher:mig-http:'+project+':dataset'))
    exported=export_records(company=record.company,project=project,dataset_id=dataset_id,references=refs,
        reader=FrappeTargetReader(record.company,project),unit_conversions=conversions,quantities=quantities)
    return {'company':record.company,'project':project,'user':user,'dataset_id':dataset_id,'references':refs,
        'unit_conversions':conversions,'quantities':quantities,'manifest':exported['manifest'],
        'source_versions':[{'doctype':ref['kind'],'name':ref['name'],'version':row['target']['version']} for ref,row in zip(refs,exported['manifest']['records'])]}

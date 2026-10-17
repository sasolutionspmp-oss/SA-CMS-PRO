"""Opt-in additive R14 synthetic prerequisites. Importing never touches a site.

Root invokes these phases explicitly as Administrator, after reviewing the plan.
No original identity, duty, source, configured selling default or master is edited.
"""
from copy import deepcopy
from datetime import date, datetime
from pathlib import Path

from .ricky_company_acceptance_support import load_private, sha, timestamp, typed_equal, write_private
from . import test_ricky_company_native as native
from .ricky_company_history_acceptance import _digest_bytes

EXTRA_TABLES = ("Price List", "Price List Country", "Item Price", "Fiscal Year", "Fiscal Year Company",
    "Quotation", "Quotation Item", "Comment", "Communication")
FLAGS = ("amend", "cancel", "create", "delete", "email", "export", "if_owner", "import", "mask", "print", "read",
    "report", "select", "share", "submit", "write")
GRANTS = {"Quotation": {"read", "create", "write", "select"}, "Price List": {"read", "select"}}
SCHEMA = "cipher.fixture.ricky.company.proposal-prerequisites.v1"
DEFAULT_KEYS=("cust_master_name","customer_group","territory","maintain_same_sales_rate","editable_price_list_rate","selling_price_list")
AUDIT_FIELDS={"creation","modified","owner","modified_by"}


def operator_plan(value):
    required={"price_list", "fiscal_year", "year_start", "year_end", "pricing_date"}
    if type(value) is not dict or not required<=set(value) or set(value)-required!={"allow_native_selling_default"} and set(value)!=required:
        raise ValueError("Supply the exact separately reviewed synthetic prerequisite plan.")
    if "allow_native_selling_default" in value and type(value["allow_native_selling_default"]) is not bool:
        raise ValueError("Explicitly opt in with a boolean to the finite supported selling-default callback.")
    for field in ("price_list", "fiscal_year"):
        if type(value[field]) is not str or not value[field].strip() or len(value[field]) > 140:
            raise ValueError("Use bounded explicit new synthetic master names.")
    try:
        start, end, priced = (date.fromisoformat(value[key]) for key in ("year_start", "year_end", "pricing_date"))
        if (start.month, start.day, end.month, end.day) != (1, 1, 12, 31) or start.year != end.year or not start <= priced <= end:
            raise ValueError
    except (ValueError, TypeError):raise ValueError("Use a calendar fiscal year containing the recorded draft date.") from None
    return deepcopy(value)


def inventory():
    import frappe
    result = native._inventory()
    for table in EXTRA_TABLES:
        if not frappe.db.exists("DocType", table):raise RuntimeError("Missing required R14 native metadata: " + table)
        result[table] = {row["name"]:{key:sha(native._native_scalar(value)) for key,value in row.items()}
            for row in frappe.db.sql("SELECT * FROM `tab" + table + "` ORDER BY name", as_dict=True)}
    for row in frappe.db.sql("SELECT doctype,field,value FROM tabSingles WHERE doctype='CRM Settings' ORDER BY field", as_dict=True):
        result["Singles"][row.doctype + ":" + row.field] = {"value":sha(native._native_scalar(row.value))}
    return result


def controller_preconditions(facts,*,allow_empty_default=False):
    if ((not facts.get("selling_default") and not allow_empty_default) or facts.get("price_list_exists") is not False
            or any(facts.get(key) != [] for key in ("item_price_references", "comments", "communications"))):
        raise RuntimeError("Require a configured selling default, an unused Price List and no prior Pursuit communications/comments.")


def _facts(value, plan):
    import frappe
    opportunity = value["inputs"]["pursuit"]["opportunity"]
    facts = {"selling_default":frappe.db.get_single_value("Selling Settings", "selling_price_list"),
        "price_list_exists":bool(frappe.db.exists("Price List", plan["price_list"])),
        "item_price_references":frappe.get_all("Item Price", filters={"price_list":plan["price_list"]}, pluck="name"),
        "comments":frappe.get_all("Comment", filters={"reference_doctype":"Opportunity", "reference_name":opportunity}, pluck="name"),
        "communications":frappe.get_all("Communication", filters={"reference_doctype":"Opportunity", "reference_name":opportunity}, pluck="name")}
    # Frappe's cached Link getter can represent the exact raw empty Singles
    # value as None. Inventory/effect-plan keep the original raw NULL/'' bytes.
    if facts["selling_default"] is None:facts["selling_default"]=""
    controller_preconditions(facts,allow_empty_default=plan.get("allow_native_selling_default") is True and facts["selling_default"]=="")
    years = frappe.db.sql("SELECT DISTINCT fy.name FROM `tabFiscal Year` fy LEFT JOIN `tabFiscal Year Company` c ON c.parent=fy.name "
        "WHERE fy.disabled=0 AND fy.year_start_date<=%s AND fy.year_end_date>=%s AND "
        "(c.company=%s OR NOT EXISTS(SELECT 1 FROM `tabFiscal Year Company` x WHERE x.parent=fy.name)) ORDER BY fy.name",
        (plan["pricing_date"],plan["pricing_date"],value["company"]), as_dict=True)
    facts["usable_fiscal_years"] = [row.name for row in years]
    if not years and frappe.db.exists("Fiscal Year", plan["fiscal_year"]):
        raise RuntimeError("Never adopt or overwrite an existing unqualified Fiscal Year.")
    role = value["native"]["role"]
    for doctype in GRANTS:
        for table in ("DocPerm", "Custom DocPerm"):
            if frappe.db.exists(table, {"parent":doctype,"role":role}):
                raise RuntimeError("The additive prerequisite must not modify an existing role permission.")
    facts["role"] = role
    return facts


def permission_additions(before, after, defaults, role):
    """Allow only supported exact default copies plus the two explicit new rules."""
    if any(name not in after or not typed_equal(row,after[name]) for name,row in before.items()):
        raise AssertionError("An existing Custom DocPerm changed.")
    additions = {name:row for name,row in after.items() if name not in before}
    for doctype, grants in GRANTS.items():
        target = [row for row in additions.values() if row.get("parent")==doctype and row.get("role")==role]
        if len(target)!=1 or target[0].get("permlevel")!=0 or any(int(target[0].get(flag) or 0)!=int(flag in grants) for flag in FLAGS):
            raise AssertionError("Only the exact new role/permission boundary is admitted.")
        copied = [row for row in additions.values() if row.get("parent")==doctype and row.get("role")!=role]
        expected = [] if any(row.get("parent")==doctype for row in before.values()) else [row for row in defaults if row.get("parent")==doctype]
        fields = ("parent", "role", "permlevel", *FLAGS)
        signature = lambda row: tuple(row.get(field) if field in ("parent","role") else int(row.get(field) or 0) for field in fields)
        if sorted(map(signature,copied))!=sorted(map(signature,expected)):
            raise AssertionError("Supported Custom DocPerm default copies do not match original DocPerm bytes.")
    if any(row.get("parent") not in GRANTS for row in additions.values()):
        raise AssertionError("Unrelated permission additions are outside this prerequisite.")
    return additions


def permission_rows(rows):
    """JSON-safe typed full observations plus separate raw semantic signatures."""
    rows=[dict(row) for row in rows]
    return {"typed":{row["name"]:{key:native._native_scalar(value) for key,value in row.items()} for row in rows},
        "semantic":{row["name"]:{"parent":row["parent"],"role":row["role"],"permlevel":int(row.get("permlevel") or 0),
            **{flag:int(row.get(flag) or 0) for flag in FLAGS}} for row in rows}}


def new_row_attribution(before,after,expected):
    actual={table:sorted(set(rows)-set(before.get(table,{}))) for table,rows in after.items()
        if set(rows)-set(before.get(table,{}))}
    wanted={table:sorted(names) for table,names in expected.items() if names}
    if actual!=wanted:raise AssertionError("The prerequisite added an unrelated or unrecorded native row.")
    return actual


def selling_property_specs(settings):
    """The complete finite non-Naming-Series callback; no Customer updates."""
    if settings.get("cust_master_name")=="Naming Series":raise RuntimeError("The supported Naming Series branch would update existing Customers.")
    result={}
    def add(doctype,field,prop,value,kind="Check"):
        name="-".join((doctype,field,prop))
        result[name]={"name":name,"doctype_or_field":"DocField","doc_type":doctype,"field_name":field,
            "property":prop,"value":str(value),"property_type":kind,"is_system_generated":1}
    add("Customer","naming_series","reqd",0);add("Customer","naming_series","hidden",1)
    for doctype in ("Sales Order","Sales Invoice","Delivery Note"):
        for prop in ("hidden","print_hide"):add(doctype,"tax_id",prop,int(settings.get("hide_tax_id") or 0))
    add("Packed Item","rate","read_only",int(not int(settings.get("editable_bundle_item_rates") or 0)))
    enabled=int(settings.get("enable_discount_accounting") or 0)
    for doctype,field in (("Sales Invoice Item","discount_account"),("Sales Invoice","additional_discount_account")):
        add(doctype,field,"hidden",int(not enabled))
        add(doctype,field,"mandatory_depends_on","eval: doc.discount_amount" if enabled else "","Code")
    return result


def _selling_plan(plan):
    import frappe
    from frappe.utils import cstr
    if frappe.db.get_single_value("Selling Settings","selling_price_list"):
        return {"enabled":False}
    if plan.get("allow_native_selling_default") is not True:raise RuntimeError("Explicitly review/opt in to the native empty-default callback.")
    doc=frappe.get_doc("Selling Settings","Selling Settings")
    projection=dict(doc.get_valid_dict());projection["selling_price_list"]=plan["price_list"]
    settings={key:doc.get(key) for key in (*DEFAULT_KEYS,"hide_tax_id","editable_bundle_item_rates","enable_discount_accounting",
        "enable_tracking_sales_commissions","enable_utm")};settings["selling_price_list"]=plan["price_list"]
    specs=selling_property_specs(settings)
    # Read-only native coercion pins the exact VARCHAR bytes update_single will
    # persist, rather than guessing int/float/date/string conversions in Python.
    singles={key:frappe.db.sql("SELECT CAST(%s AS CHAR)",(value,))[0][0] for key,value in projection.items() if key!="doctype" and key not in {"modified","modified_by"}}
    before_singles={row.field:row.value for row in frappe.db.sql("SELECT field,value FROM tabSingles WHERE doctype='Selling Settings' ORDER BY field",as_dict=True)}
    if set(before_singles)-set(singles)-{"modified","modified_by"}:raise RuntimeError("An unprojected existing Selling Settings field needs separate source review.")
    defaults={}
    for key in DEFAULT_KEYS:
        rows=[dict(row) for row in frappe.get_all("DefaultValue",filters={"parent":"__default","defkey":key},fields=["*"])]
        if len(rows)>1:raise RuntimeError("The finite default transition requires unique existing global keys.")
        value=settings[key];retain=bool(rows and rows[0]["defvalue"]==cstr(value))
        defaults[key]={"value":None if value is None else cstr(value),"retain":retain,
            "before":{row["name"]:{field:native._native_scalar(item) for field,item in row.items()} for row in rows}}
    properties={}
    for name,spec in specs.items():
        rows=[dict(row) for row in frappe.get_all("Property Setter",filters={"doc_type":spec["doc_type"],"field_name":spec["field_name"],"property":spec["property"]},fields=["*"])]
        if len(rows)>1 or any(row["name"]!=name for row in rows):raise RuntimeError("Require unique canonical names for exact Property Setter replacement.")
        properties[name]={"expected":spec,"before":{row["name"]:{field:native._native_scalar(item) for field,item in row.items()} for row in rows}}
    return {"enabled":True,"settings":{key:native._native_scalar(value) for key,value in settings.items()},"singles":singles,"before_singles":before_singles,
        "defaults":defaults,"properties":properties,"standing":"PriceList.insert invokes the supported callback; no manual setter/reset."}


def _audit(row,start,end):
    if row.get("owner")!="Administrator" or row.get("modified_by")!="Administrator":raise AssertionError("Controller-created row attribution changed.")
    for key in ("creation","modified"):
        value=row.get(key)
        if not isinstance(value,datetime) or not start<=value<=end:raise AssertionError("Controller audit timestamp is outside the actual native transaction.")


def verify_selling_transition(plan,after,*,start,end):
    """Verify raw native callback rows and return exact attributable identities."""
    if not plan["enabled"]:return {"changed_old":{},"new_rows":{},"observed":{}}
    singles=after["singles"]
    expected={**plan["singles"],"modified":singles.get("modified"),"modified_by":"Administrator"}
    if singles!=expected:raise AssertionError("Selling Settings differs from the pinned finite native projection.")
    if not start<=datetime.fromisoformat(singles["modified"])<=end:raise AssertionError("Single audit time is outside the native transaction.")
    changed={"Singles":set("Selling Settings:"+key for key in plan["before_singles"])}
    new={"DefaultValue":[],"Property Setter":[],"Singles":["Selling Settings:"+key for key in singles if key not in plan["before_singles"]]}
    observed={"singles":{key:native._native_scalar(value) for key,value in singles.items()},"defaults":{},"properties":{}}
    for key,item in plan["defaults"].items():
        rows=after["defaults"][key];before=item["before"]
        typed={row["name"]:{field:native._native_scalar(value) for field,value in row.items()} for row in rows}
        if item["retain"]:
            if typed!=before:raise AssertionError("An already identical default row was rewritten.")
        else:
            if len(rows)!=(0 if item["value"] is None else 1):raise AssertionError("Default replacement/delete cardinality changed.")
            for row in rows:
                if (row["name"] in before or row.get("parent")!="__default" or row.get("parenttype")!="__default"
                        or row.get("parentfield")!="system_defaults" or row.get("defkey")!=key or row.get("defvalue")!=item["value"]):
                    raise AssertionError("The supported default replacement has foreign metadata or value.")
                _audit(row,start,end)
                if any(value not in (None,0,"") for field,value in row.items() if field not in {*AUDIT_FIELDS,"name","parent","parenttype","parentfield","defkey","defvalue"}):
                    raise AssertionError("An unrelated default column was populated.")
                new["DefaultValue"].append(row["name"])
            changed.setdefault("DefaultValue",set()).update(before)
        observed["defaults"][key]=typed
    if set(after["properties"])!=set(plan["properties"]):raise AssertionError("The finite Property Setter identity set changed.")
    for name,item in plan["properties"].items():
        row=after["properties"][name];spec=item["expected"]
        if any(row.get(field)!=value for field,value in spec.items()):raise AssertionError("A controller Property Setter semantic value changed.")
        _audit(row,start,end)
        if any(value not in (None,0,"") for field,value in row.items() if field not in set(spec)|AUDIT_FIELDS):
            raise AssertionError("An unrelated Property Setter column was populated.")
        changed.setdefault("Property Setter",set()).update(item["before"])
        if not item["before"]:new["Property Setter"].append(name)
        observed["properties"][name]={field:native._native_scalar(value) for field,value in row.items()}
    return {"changed_old":{table:sorted(names) for table,names in changed.items()},"new_rows":new,"observed":observed}


def _selling_after(plan):
    import frappe
    if not plan["enabled"]:return {}
    return {"singles":{row.field:row.value for row in frappe.db.sql("SELECT field,value FROM tabSingles WHERE doctype='Selling Settings' ORDER BY field",as_dict=True)},
        "defaults":{key:[dict(row) for row in frappe.get_all("DefaultValue",filters={"parent":"__default","defkey":key},fields=["*"])] for key in DEFAULT_KEYS},
        "properties":{row["name"]:dict(row) for row in frappe.get_all("Property Setter",filters={"name":["in",list(plan["properties"])]},fields=["*"])}}


def verify_property_deletion_comments(plan,rows,*,start,end):
    """Exact normal delete_doc.insert_feed output for the replaced setters."""
    subjects=["Property Setter "+name for name,item in plan.get("properties",{}).items() if item["before"]]
    if len(rows)!=len(subjects) or sorted(row.get("subject","") for row in rows)!=sorted(subjects):
        raise AssertionError("Require exactly one native deletion feed for each replaced Property Setter.")
    fixed={"docstatus":0,"idx":0,"comment_type":"Deleted","comment_email":"Administrator",
        "comment_by":None,"published":0,"seen":0,"reference_doctype":"Property Setter",
        "reference_name":None,"reference_owner":None,"content":None,"ip_address":None,
        "_user_tags":None,"_comments":None,"_assign":None,"_liked_by":None}
    names=set()
    for row in rows:
        if (set(row)!=set(fixed)|AUDIT_FIELDS|{"name","subject"}
                or any(type(row[key]) is not type(value) or row[key]!=value for key,value in fixed.items())
                or type(row["name"]) is not str or not row["name"] or row["name"] in names
                or row["creation"]!=row["modified"]):
            raise AssertionError("A native Property Setter deletion feed contains unrelated columns or content.")
        _audit(row,start,end);names.add(row["name"])
    return sorted(names)


def _prepare_prerequisite_record(original_manifest, private_record, plan,*,predecessor=None):
    import frappe
    from cipher_aec.governance.context import require_effects_enabled
    from .ricky_company_recovery_acceptance import _only_active
    value = native._fixture(original_manifest);require_effects_enabled();_only_active();plan=operator_plan(plan)
    path=Path(private_record).resolve();base=Path(frappe.get_site_path("private","cipher-fixtures")).resolve()
    if not path.is_relative_to(base) or path.exists() or not path.parent.is_dir():
        raise ValueError("Use a new private prerequisite record in the isolated fixture directory.")
    if not value["inputs"].get("ready"):raise RuntimeError("Original qualified manual inputs are required.")
    facts=_facts(value,plan);before=inventory()
    proof={"schema":SCHEMA,"status":"prepared","at":timestamp(),"original_manifest":str(Path(original_manifest).resolve()),
        "original_manifest_sha256":_digest_bytes(original_manifest),"fixture_id":value["fixture_id"],"site":value["site"],
        "company":value["company"],"plan":plan,"facts":facts,"before":before,"selling_effect_plan":_selling_plan(plan),
        "custom_permissions":permission_rows(frappe.get_all("Custom DocPerm",fields=["*"])),
        "default_permissions":permission_rows(frappe.get_all("DocPerm",filters={"parent":["in",list(GRANTS)]},fields=["*"]))}
    if predecessor is not None:proof["predecessor"]=deepcopy(predecessor)
    write_private(path,proof);frappe.db.rollback()
    return {"status":"prepared","private_record":str(path),"record_sha256":_digest_bytes(path),"effects":"NOT RUN"}


def prepare_company_proposal_prerequisites(original_manifest,private_record,plan):
    return _prepare_prerequisite_record(original_manifest,private_record,plan)


def correction_preconditions(failed,reconciled,current,reference,plan,*,expected_error="Only the exact new role/permission boundary is admitted."):
    expected={"recorded_status","old_row_changes","matches_recorded_after","price_list","fiscal_year","permissions","at"}
    if (set(reconciled)!=expected or reconciled["recorded_status"]!="failed" or reconciled["old_row_changes"]!=[]
            or reconciled["matches_recorded_after"] is not False or reconciled["price_list"]!={} or reconciled["fiscal_year"]!={}):
        raise ValueError("Bind the authentic first failed-attempt reconciliation, not a fabricated/missing snapshot.")
    if (type(reconciled["permissions"]) is not dict or set(reconciled["permissions"])!=set(GRANTS)
            or any(set(reconciled["permissions"][doctype])!=grants or any(type(item) is not bool for item in reconciled["permissions"][doctype].values()) for doctype,grants in GRANTS.items())):
        raise ValueError("Preserve the authentic six effective permission observations; role absence is checked independently.")
    if (failed.get("schema")!=SCHEMA or failed.get("status")!="failed" or failed.get("after") is not None
            or failed.get("error",{}).get("error_type")!="AssertionError"
            or failed["error"].get("error_message")!=expected_error):
        raise ValueError("This explicit correction applies only to its retained native refusal.")
    if any(not typed_equal(failed.get(key),value) for key,value in reference.items()) or not typed_equal(failed["plan"],plan):
        raise AssertionError("The failed attempt's original source/Company/site/plan binding changed.")
    if not typed_equal(current,failed["before"]):raise AssertionError("The entire exact failed-before inventory must be restored, including absence of new rows.")


def prepare_corrected_company_proposal_prerequisites(failed_record,first_reconcile,private_record,plan,*,failed_sha256,first_reconcile_sha256):
    """New declaration only, linked to immutable failure and restored inventory."""
    return _prepare_correction(failed_record,first_reconcile,private_record,plan,failed_sha256=failed_sha256,
        first_reconcile_sha256=first_reconcile_sha256,directory="company-proposal-prerequisites-r14-corrected",
        expected_error="Only the exact new role/permission boundary is admitted.",
        cause="Native Custom DocPerm export default=1; new supported grants explicitly set every flag.")


def prepare_audited_company_proposal_prerequisites(failed_record,first_reconcile,private_record,plan,*,failed_sha256,first_reconcile_sha256):
    """Separate declaration for the traced native Property Setter deletion feed."""
    return _prepare_correction(failed_record,first_reconcile,private_record,plan,failed_sha256=failed_sha256,
        first_reconcile_sha256=first_reconcile_sha256,directory="company-proposal-prerequisites-r14-audited",
        expected_error="The prerequisite added an unrelated or unrecorded native row.",
        cause="Normal Property Setter replacement creates one exact Deleted Comment per replaced setter.")


def _prepare_correction(failed_record,first_reconcile,private_record,plan,*,failed_sha256,first_reconcile_sha256,directory,expected_error,cause):
    failed,value=_record(failed_record);reconciled=load_private(first_reconcile);plan=operator_plan(plan)
    if _digest_bytes(failed_record)!=failed_sha256 or _digest_bytes(first_reconcile)!=first_reconcile_sha256:
        raise AssertionError("Use root's exact immutable failed record and first reconciliation bytes.")
    failed_path=Path(failed_record).resolve();first_path=Path(first_reconcile).resolve();destination=Path(private_record).resolve()
    expected_first=failed_path.with_name(failed_path.stem+".reconciled.secret.json")
    if (first_path!=expected_first or destination.parent.name!=directory
            or destination.parent==failed_path.parent or destination.exists()):
        raise ValueError("Use the authentic first reconcile and the separately declared new corrected directory/record.")
    reference={key:failed[key] for key in ("original_manifest","original_manifest_sha256","fixture_id","company","site")}
    # _record already verifies the original manifest bytes and current native site.
    reference.update(fixture_id=value["fixture_id"],company=value["company"],site=value["site"])
    correction_preconditions(failed,reconciled,inventory(),reference,plan,expected_error=expected_error)
    predecessor={"failed_record":str(failed_path),"failed_sha256":failed_sha256,"first_reconcile":str(first_path),
        "first_reconcile_sha256":first_reconcile_sha256,"restored_full_inventory_sha256":sha(failed["before"]),
        "cause":cause}
    return _prepare_prerequisite_record(failed["original_manifest"],private_record,plan,predecessor=predecessor)


def exact_permission_grants(role,add_permission,update_permission_property):
    """Do not inherit permissive native field defaults (observed export=1)."""
    for doctype,grants in GRANTS.items():
        add_permission(doctype,role,permlevel=0,ptype="read")
        # Disable dependent rights before write/create, then grant exact rights.
        denied=[flag for flag in ("amend","cancel","submit","import") if flag not in grants]
        denied+=sorted(set(FLAGS)-grants-set(denied))
        allowed=[flag for flag in ("read","write","create","select") if flag in grants]
        for flag in denied+allowed:update_permission_property(doctype,role,0,flag,int(flag in grants))


def _record(path):
    proof=load_private(path)
    if proof.get("schema")!=SCHEMA:raise ValueError("Use the exact prepared R14 prerequisite record.")
    value=native._fixture(proof["original_manifest"])
    if (_digest_bytes(proof["original_manifest"])!=proof["original_manifest_sha256"] or value["company"]!=proof["company"]
            or value["fixture_id"]!=proof["fixture_id"] or value["site"]!=proof["site"]):
        raise AssertionError("The original fixture reference changed.")
    predecessor=proof.get("predecessor")
    if predecessor and (_digest_bytes(predecessor["failed_record"])!=predecessor["failed_sha256"]
            or _digest_bytes(predecessor["first_reconcile"])!=predecessor["first_reconcile_sha256"]):
        raise AssertionError("The corrected declaration's original failed/reconciled evidence changed.")
    return proof,value


def apply_company_proposal_prerequisites(private_record):
    """One explicit additive transaction; a failed/unknown attempt is never reset."""
    import frappe
    from frappe.permissions import add_permission, update_permission_property
    from cipher_aec.governance.context import require_effects_enabled
    from .ricky_company_recovery_acceptance import _only_active
    proof,value=_record(private_record);require_effects_enabled();_only_active()
    if proof["status"]!="prepared":raise RuntimeError("Prerequisite application is one-shot; reconcile the original attempt.")
    if (not typed_equal(_facts(value,proof["plan"]),proof["facts"]) or inventory()!=proof["before"]
            or not typed_equal(_selling_plan(proof["plan"]),proof["selling_effect_plan"])):
        raise AssertionError("Native prerequisite standing changed before the first write.")
    proof.update(status="entered",entered_at=timestamp());write_private(private_record,proof)
    try:
        plan=proof["plan"]
        from frappe.utils import now_datetime
        transaction_start=now_datetime()
        frappe.get_doc({"doctype":"Price List","price_list_name":plan["price_list"],"enabled":1,"selling":1,"buying":0,"currency":"USD"}).insert()
        created_year=None
        if not proof["facts"]["usable_fiscal_years"]:
            created_year=frappe.get_doc({"doctype":"Fiscal Year","year":plan["fiscal_year"],"year_start_date":plan["year_start"],
                "year_end_date":plan["year_end"],"disabled":0,"is_short_year":0,"companies":[{"company":value["company"]}]}).insert().name
        exact_permission_grants(proof["facts"]["role"],add_permission,update_permission_property)
        current=permission_rows(frappe.get_all("Custom DocPerm",fields=["*"]))
        proof["observed_permissions_before_assertions"]=current;write_private(private_record,proof)
        additions=permission_additions(proof["custom_permissions"]["semantic"],current["semantic"],
            list(proof["default_permissions"]["semantic"].values()),proof["facts"]["role"])
        after=inventory()
        transaction_end=now_datetime()
        controller=verify_selling_transition(proof["selling_effect_plan"],_selling_after(proof["selling_effect_plan"]),start=transaction_start,end=transaction_end)
        comments=sorted(set(after["Comment"])-set(proof["before"]["Comment"]))
        comment_rows=[dict(row) for row in frappe.get_all("Comment",filters={"name":["in",comments]},fields=["*"])] if comments else []
        # Retain actual observations before assertions; a refusal must be diagnosable.
        proof["observed_after_before_assertions"]=after
        proof["observed_new_comments"]={row["name"]:{key:native._native_scalar(item) for key,item in row.items()} for row in comment_rows}
        write_private(private_record,proof)
        controller["new_rows"]["Comment"]=verify_property_deletion_comments(proof["selling_effect_plan"],comment_rows,start=transaction_start,end=transaction_end)
        controller["observed"]["deletion_comments"]=proof["observed_new_comments"]
        changes=native._old_row_changes(proof["before"],after)
        unexpected=[row for row in changes if row["name"] not in controller["changed_old"].get(row["doctype"],[])]
        if unexpected:raise AssertionError("A prerequisite controller changed an unrelated old native row/column.")
        expected_default=plan["price_list"] if proof["selling_effect_plan"]["enabled"] else proof["facts"]["selling_default"]
        if frappe.db.get_single_value("Selling Settings","selling_price_list")!=expected_default:
            raise AssertionError("The original selling default changed.")
        children=frappe.get_all("Fiscal Year Company",filters={"parent":created_year},fields=["name","parent","parenttype","parentfield","company"]) if created_year else []
        if created_year and (len(children)!=1 or children[0].company!=value["company"] or children[0].parenttype!="Fiscal Year" or children[0].parentfield!="companies"):
            raise AssertionError("The new Fiscal Year must bind only this explicit existing Company.")
        attributed=new_row_attribution(proof["before"],after,{"Price List":[plan["price_list"]],"Fiscal Year":[created_year] if created_year else [],
            "Fiscal Year Company":[row.name for row in children],"Custom DocPerm":list(additions),**controller["new_rows"]})
        proof.update(status="commit_pending",created_fiscal_year=created_year,added_custom_permissions=additions,
            typed_permissions_after=current["typed"],new_rows=attributed,after=after,controller_transition=controller,
            attributed_old_row_changes=changes,transaction_time={"start":native._native_scalar(transaction_start),"end":native._native_scalar(transaction_end)},
            prepared_at=timestamp());write_private(private_record,proof)
        frappe.db.commit()
        proof.update(status="committed",committed_at=timestamp());write_private(private_record,proof)
    except Exception as error:
        frappe.db.rollback();proof.update(status="failed",error=native._claim_failure(error),failed_at=timestamp());write_private(private_record,proof);raise
    return {"status":"committed","price_list":proof["plan"]["price_list"],"created_fiscal_year":proof["created_fiscal_year"],
        "new_permissions":len(proof["added_custom_permissions"]),"model_invoked":False}


def reconcile_company_proposal_prerequisites(private_record):
    """Read-only original attempt reconciliation; does not retry or relabel failure."""
    import frappe
    proof,value=_record(private_record);after=inventory()
    changes=native._old_row_changes(proof["before"],after)
    result={"recorded_status":proof["status"],"old_row_changes":changes,
        "matches_recorded_after":after==proof.get("after"),
        "price_list":frappe.db.get_value("Price List",proof["plan"]["price_list"],["name","currency","selling","buying","enabled"],as_dict=True),
        "fiscal_year":frappe.db.get_value("Fiscal Year",proof["plan"]["fiscal_year"],["name","disabled","year_start_date","year_end_date"],as_dict=True),
        "permissions":{doctype:{flag:bool(frappe.has_permission(doctype,ptype=flag,user=value["users"]["author"]["user"])) for flag in sorted(grants)}
            for doctype,grants in GRANTS.items()},"at":timestamp()}
    # Serialize native date/Decimal values through the existing typed observer.
    result["price_list"]={key:native._native_scalar(item) for key,item in (result["price_list"] or {}).items()}
    result["fiscal_year"]={key:native._native_scalar(item) for key,item in (result["fiscal_year"] or {}).items()}
    path=Path(private_record).with_name(Path(private_record).stem+".reconciled.secret.json")
    if path.exists():raise RuntimeError("Preserve the first independent prerequisite reconciliation.")
    write_private(path,result);frappe.db.rollback()
    return {"private_record":str(path),"recorded_status":proof["status"],"old_rows_unchanged":not changes,
        "matches_exact_recorded_transition":result["matches_recorded_after"] and changes==proof.get("attributed_old_row_changes",[])}

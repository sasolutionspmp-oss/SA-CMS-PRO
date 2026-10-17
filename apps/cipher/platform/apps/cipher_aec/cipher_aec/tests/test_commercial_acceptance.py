"""Opt-in real ERPNext COM-01 acceptance with isolated company-only identities.

bench --site cipher.localhost execute cipher_aec.tests.test_commercial_acceptance.run_acceptance
"""
import copy
import secrets
from uuid import uuid4


def setup_fixture():
    import frappe
    from frappe.permissions import add_permission, update_permission_property
    from cipher_aec.governance.context import assert_synthetic_site, trusted_write
    from cipher_aec.install import _person, _user, _binding, _grant_company
    assert_synthetic_site()
    if frappe.session.user != "Administrator":
        raise RuntimeError("Explicit fixture creation requires bench Administrator")
    marker = uuid4().hex[:10]
    company = "COM-01 isolated company " + marker
    person = "COM-FIXTURE-" + marker
    user, alias = "commercial.fixture." + marker + "@cipher.example", "commercial.alias." + marker + "@cipher.example"
    role = "COM-01 fixture " + marker
    with trusted_write():
        _ensure_company(company, marker)
        _person(person, "Isolated COM-01 synthetic author")
        for account in (user, alias):
            _user(account, "COM-01 isolated fixture", secrets.token_urlsafe(32))
            _binding(account, person)
        for ability in ("company.read", "commercial.read", "commercial.write"):
            _grant_company(person, company, ability)
        customer_group = frappe.get_doc({"doctype":"Customer Group", "customer_group_name":"COM-01 isolated " + marker, "parent_customer_group":"All Customer Groups", "is_group":0}).insert(ignore_permissions=True)
        territory = frappe.get_doc({"doctype":"Territory", "territory_name":"COM-01 isolated " + marker, "parent_territory":"All Territories", "is_group":0}).insert(ignore_permissions=True)
        customer = frappe.get_doc({"doctype":"Customer", "customer_name":"COM-01 isolated customer " + marker, "customer_type":"Company", "customer_group":customer_group.name, "territory":territory.name}).insert(ignore_permissions=True)
        unit_id = str(uuid4())
        unit = frappe.get_doc({"doctype":"UOM", "uom_name":"COM-01 qualified unit " + marker, "enabled":1, "must_be_whole_number":0, "cipher_unit_id":unit_id, "cipher_dimension":"count", "cipher_quantity_precision":6, "cipher_unit_revision":1}).insert(ignore_permissions=True)
        frappe.get_doc({"doctype":"Role", "role_name":role}).insert(ignore_permissions=True)
        for doctype in ("Opportunity", "Quotation", "Customer", "Lead", "UOM", "Currency", "Item", "Company", "Account", "Price List"):
            add_permission(doctype, role, 0)
            for permission in ("read", "select", "create", "write"):
                update_permission_property(doctype, role, 0, permission, int(permission in ("read", "select") or doctype in ("Opportunity", "Quotation")))
        for account in (user, alias):
            doc = frappe.get_doc("User", account); doc.append("roles", {"role":role}); doc.save(ignore_permissions=True)
    frappe.db.commit()
    for account in (user, alias): frappe.clear_cache(user=account)
    from cipher_aec.tests.test_commercial import sample
    composition = sample()
    composition["price_list"]="COM-01 selling list " + marker
    for row in composition["price_lines"]:
        row["unit_id"] = unit_id
    return {"company":company,"person":person,"user":user,"alias":alias,"role":role,"customer":customer.name,"unit":unit.name,"unit_id":unit_id,"composition":composition,"marker":marker}


def run_acceptance(reuse_latest=False):
    import frappe
    from cipher_aec.api.contracts import digest
    from cipher_aec.api.errors import DomainError
    from cipher_aec.governance.commands import read_company_operation
    from cipher_aec.governance.context import trusted_write, duty_rows, current_actor
    from cipher_aec.commercial import service, native
    fixture = existing_fixture() if reuse_latest else setup_fixture()
    company, user = fixture["company"], fixture["user"]
    frappe.set_user(user)
    before = {doctype:frappe.db.count(doctype) for doctype in ("Customer", "Project", "Opportunity", "Quotation")}
    checks = []
    def denial(name, callback, codes):
        try:
            callback()
            raise AssertionError("Expected rejection: " + name)
        except DomainError as error:
            assert error.code in codes, (name, error.code)
            checks.append({"check":name,"result":"passed","code":error.code})
    try:
        assert not duty_rows(current_actor())
        operation = str(uuid4()); fields = {"title":"Synthetic COM-01 pursuit", "sector":"Synthetic infrastructure"}
        pursuit = service.create_pursuit(company, "Customer", fixture["customer"], fields, operation)["pursuit"]
        original_operation = str(uuid4())
        result = service.create_proposal(company, pursuit["id"], fixture["composition"], original_operation)
        proposal, first = result["proposal"], result["revision"]
        assert first["pricing"]["total"] == "20.50"
        assert digest(native.persisted(proposal["quotation"])) == first["native_fingerprint"]
        assert frappe.db.count("Customer") == before["Customer"] and frappe.db.count("Project") == before["Project"]
        checks.append({"check":"company_only_preaward_native_masters_no_duplicate_party_or_project","result":"passed"})
        frappe.set_user(fixture["alias"])
        replay = service.create_proposal(company, pursuit["id"], fixture["composition"], original_operation)
        assert replay["operation"]["replayed"] and replay["revision"]["id"] == first["id"]
        assert read_company_operation(company, original_operation)["proposal"]["id"] == proposal["id"]
        assert frappe.db.count("Opportunity") == before["Opportunity"] + 1
        assert frappe.db.count("Quotation") == before["Quotation"] + 1
        changed = copy.deepcopy(fixture["composition"])
        changed["terms"] = "Second immutable authored commercial terms"
        changed["price_lines"].reverse()
        for row in changed["price_lines"]: row["selected"] = not row["selected"]
        changed["sections"].append({"id":str(uuid4()),"kind":"exclusion","title":"Exclusion","text":"No issued contract or tax treatment is implied."})
        denial("changed_operation_payload", lambda: service.create_proposal(company,pursuit["id"],changed,original_operation), {"operation_conflict"})
        second_result = service.save_proposal_revision(company, proposal["id"], 1, first["native_fingerprint"], changed, str(uuid4()))
        second = second_result["revision"]
        assert frappe.db.count("Quotation") == before["Quotation"] + 1
        assert second["pricing"]["total"] == "25.50" and second["predecessor"] == first["id"]
        compared = service.compare_revisions(company, proposal["id"], first["id"], second["id"])
        assert compared["changes"]["terms"]["changed"] and len(compared["changes"]["price_lines"]["changed"]) == 2
        assert compared["changes"]["price_lines"]["added"] == []
        assert service.get_revision(company, first["id"])["composition"]["terms"] == fixture["composition"]["terms"]
        checks.append({"check":"immutable_successor_comparison_and_selected_alternate_exact_once","result":"passed"})
        denial("stale_revision",lambda:service.save_proposal_revision(company,proposal["id"],1,first["native_fingerprint"],changed,str(uuid4())),{"stale_commercial"})
        denial("stale_native_fingerprint",lambda:service.save_proposal_revision(company,proposal["id"],2,"0"*64,changed,str(uuid4())),{"stale_native_source"})
        quote = frappe.get_doc("Quotation", proposal["quotation"])
        quote.terms = "Bypass attempted"
        denial("native_generic_save_denied",lambda:quote.save(ignore_permissions=True),{"governed_write_required"})
        old = frappe.get_doc("Cipher Proposal Revision", first["id"])
        with trusted_write():
            denial("revision_immutable_even_trusted",lambda:old.save(ignore_permissions=True),{"immutable_proposal_revision"})
        unsupported = copy.deepcopy(changed)
        for row in unsupported["price_lines"]: row.update(quantity="1",rate="1.123456789")
        count = frappe.db.count("Cipher Proposal Revision",{"proposal":proposal["id"]})
        denial("unsupported_persisted_native_precision_atomic",lambda:service.save_proposal_revision(company,proposal["id"],2,second["native_fingerprint"],unsupported,str(uuid4())),{"unsupported_native_precision"})
        assert frappe.db.count("Cipher Proposal Revision",{"proposal":proposal["id"]}) == count
        assert digest(native.persisted(proposal["quotation"])) == second["native_fingerprint"]
        with trusted_write():
            unit = frappe.get_doc("UOM",fixture["unit"]);unit.enabled=0;unit.save(ignore_permissions=True)
        assert service.get_revision(company,first["id"])["id"] == first["id"]
        assert service.compare_revisions(company,proposal["id"],first["id"],second["id"])["changes"]["terms"]["changed"]
        assert read_company_operation(company,original_operation)["revision"]["id"] == first["id"]
        denial("disabled_unit_blocks_new_draft_preserves_authorized_history",lambda:service.create_proposal(company,pursuit["id"],changed,str(uuid4())),{"unit_setup_required"})
        with trusted_write():unit.enabled=1;unit.save(ignore_permissions=True)
        with trusted_write():
            duty = frappe.get_doc("Cipher Project Duty",frappe.db.get_value("Cipher Project Duty",{"person":fixture["person"],"company":company,"scope_type":"Company","ability":"commercial.read"},"name")); duty.active=0; duty.save(ignore_permissions=True)
        denial("current_read_revocation_receipt",lambda:read_company_operation(company,original_operation),{"not_found","capability_denied"})
        denial("current_read_revocation_replay",lambda:service.create_proposal(company,pursuit["id"],fixture["composition"],original_operation),{"not_found","capability_denied"})
        with trusted_write(): duty.active=1; duty.save(ignore_permissions=True)
        frappe.db.commit()
        return {"schema":"cipher.com01.native-acceptance.v1","status":"passed","fixture":fixture,"pursuit_id":pursuit["id"],"proposal_id":proposal["id"],"first_revision":first["id"],"current_revision":second["id"],"native_quotation":proposal["quotation"],"checks":checks,"qualification_limits":["Draft only; no issue, send, award or posting.","Base currency, no tax/discount/FX; unsupported native precision is rejected.","Company document/estimate references explicitly unavailable pending canonical shared extension."]}
    finally:
        frappe.db.rollback()
        frappe.set_user("Administrator")


def prepare_http_fixture(user, alias, source_read=1, commercial_read=1, setup_password=False):
    """Explicit private fixture grants; never changes a normal product role or user."""
    import os
    import frappe
    from frappe.permissions import update_permission_property
    from frappe.utils.password import update_password
    from cipher_aec.governance.context import assert_synthetic_site, trusted_write
    assert_synthetic_site()
    if frappe.session.user != "Administrator" or not user.startswith("commercial.fixture.") or not alias.startswith("commercial.alias."):
        raise RuntimeError("Only isolated COM fixture accounts are accepted")
    person = frappe.db.get_value("Cipher Identity Binding", {"user":user,"active":1}, "person")
    if not person or not person.startswith("COM-FIXTURE-") or frappe.db.get_value("Cipher Identity Binding",{"user":alias,"active":1},"person") != person:
        raise RuntimeError("The explicit fixture aliases must share their isolated canonical person")
    roles = [row.role for row in frappe.get_doc("User", user).roles if row.role.startswith("COM-01 fixture ")]
    if len(roles) != 1:
        raise RuntimeError("Only the isolated fixture role may be adjusted")
    with trusted_write():
        update_permission_property("Customer", roles[0], 0, "read", int(source_read))
        duty_id = frappe.db.get_value("Cipher Project Duty",{"person":person,"company":"COM-01 isolated company " + user.split("@")[0].rsplit(".",1)[1],"scope_type":"Company","ability":"commercial.read"},"name")
        duty = frappe.get_doc("Cipher Project Duty",duty_id);duty.active=int(commercial_read);duty.save(ignore_permissions=True)
        if setup_password:
            password=os.environ["CIPHER_COM_HTTP_PASSWORD"]
            for account in (user,alias):update_password(account,password,logout_all_sessions=True)
    frappe.db.commit()
    for account in (user,alias):frappe.clear_cache(user=account)
    return {"prepared":True,"person":person,"company":duty.company,"source_read":bool(source_read),"commercial_read":bool(commercial_read)}


def existing_fixture():
    """Reuse only this suite's last fully committed isolated fixture."""
    import frappe
    from cipher_aec.governance.context import assert_synthetic_site
    from cipher_aec.tests.test_commercial import sample
    assert_synthetic_site()
    if frappe.session.user != "Administrator":raise RuntimeError("Bench Administrator fixture context is required")
    rows=frappe.get_all("User",filters={"name":["like","commercial.fixture.%@cipher.example"]},fields=["name"],order_by="creation desc")
    for row in rows:
        fixture_user=row.name
        marker=fixture_user.split("@")[0].rsplit(".",1)[1]
        unit=frappe.db.get_value("UOM",{"name":"COM-01 qualified unit " + marker},["name","cipher_unit_id"],as_dict=True)
        customer=frappe.db.get_value("Customer",{"customer_name":"COM-01 isolated customer " + marker},"name")
        if not unit or not customer:continue
        value=sample()
        value["price_list"]="COM-01 selling list " + marker
        for line in value["price_lines"]:line["unit_id"]=unit.cipher_unit_id
        company = "COM-01 isolated company " + marker
        from cipher_aec.governance.context import trusted_write
        from cipher_aec.install import _grant_company
        with trusted_write():
            _ensure_company(company, marker)
            for row in frappe.get_all("Cipher Project Duty", filters={"person":"COM-FIXTURE-"+marker,"scope_type":"Company","company":["!=",company]}, fields=["name"]):
                old=frappe.get_doc("Cipher Project Duty",row.name);old.active=0;old.save(ignore_permissions=True)
            for ability in ("company.read", "commercial.read", "commercial.write"):
                _grant_company("COM-FIXTURE-"+marker, company, ability)
        from frappe.permissions import add_permission, update_permission_property
        role="COM-01 fixture " + marker
        add_permission("Account",role,0)
        update_permission_property("Account",role,0,"select",1)
        add_permission("Price List",role,0)
        update_permission_property("Price List",role,0,"read",1)
        frappe.db.commit()
        for account in (fixture_user,"commercial.alias."+marker+"@cipher.example"):frappe.clear_cache(user=account)
        return {"company":company,"person":"COM-FIXTURE-"+marker,"user":fixture_user,"alias":"commercial.alias."+marker+"@cipher.example","role":"COM-01 fixture "+marker,"customer":customer,"unit":unit.name,"unit_id":unit.cipher_unit_id,"composition":value,"marker":marker}
    raise RuntimeError("No fully committed isolated COM fixture exists")


def _ensure_company(company, marker):
    """Own native Company/calendar fixture only; no main-company policy inferred."""
    import frappe
    if not frappe.db.exists("Company",company):
        frappe.get_doc({"doctype":"Company","company_name":company,"abbr":"C"+marker[:7],"default_currency":"USD","country":"United States"}).insert(ignore_permissions=True)
    price_list="COM-01 selling list " + marker
    if not frappe.db.exists("Price List",price_list):
        frappe.get_doc({"doctype":"Price List","price_list_name":price_list,"currency":"USD","enabled":1,"selling":1,"buying":0}).insert(ignore_permissions=True)
    year="COM-01 synthetic 2026 " + marker
    if not frappe.db.exists("Fiscal Year",year):
        frappe.get_doc({"doctype":"Fiscal Year","year":year,"year_start_date":"2026-01-01","year_end_date":"2026-12-31","companies":[{"company":company}]}).insert(ignore_permissions=True)

"""Actual native permissions, scoped counts and signed-filter cursor checks."""
import uuid
import frappe
from frappe.tests import IntegrationTestCase
from frappe.permissions import add_permission, update_permission_property
from cipher_aec.api.errors import DomainError
from cipher_aec.api.masters import _choose
from cipher_aec.governance.context import trusted_write
from cipher_aec.install import _binding, _grant, _grant_company, _person, _user


class TestMasterSelectors(IntegrationTestCase):
    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        self.savepoint="company_test_"+uuid.uuid4().hex
        frappe.db.savepoint(self.savepoint)
        self.company="Cipher Synthetic Company"
        if not frappe.db.exists("Company",self.company):raise RuntimeError("Synthetic Company fixture prerequisite is missing; do not reseed inside this suite")
        self.prefix=uuid.uuid4().hex[:12]
        with trusted_write():
            self.person=_person("COMPANY-TEST-"+self.prefix,"Company-only synthetic author")
            self.primary="company-"+self.prefix+"@cipher.example"
            self.alias="company-alias-"+self.prefix+"@cipher.example"
            self.project_user="project-only-"+self.prefix+"@cipher.example"
            self.project_person=_person("PROJECT-TEST-"+self.prefix,"Project-only synthetic author")
            for email,person in ((self.primary,self.person),(self.alias,self.person),(self.project_user,self.project_person)):
                _user(email,"Synthetic",None);_binding(email,person)
            self.project=frappe.get_doc({"doctype":"Project","company":self.company,"project_name":"Synthetic company scope test "+self.prefix,"status":"Open","percent_complete_method":"Manual"}).insert(ignore_permissions=True).name
            for ability in ("company.read","commercial.read","commercial.write"):_grant_company(self.person,self.company,ability)
            for ability in ("project.read","task.create"):_grant(self.project_person,self.company,self.project,ability)
        frappe.set_user(self.primary)
    def tearDown(self):
        frappe.set_user("Administrator")
        frappe.db.rollback(save_point=self.savepoint)
        super().tearDown()

    def grant_native(self, *doctypes):
        current = frappe.session.user
        frappe.set_user("Administrator")
        role = "Master Selector " + self.prefix
        if not frappe.db.exists("Role", role):
            frappe.get_doc({"doctype":"Role","role_name":role}).insert(ignore_permissions=True)
        for doctype in doctypes:
            add_permission(doctype,role,0)
            update_permission_property(doctype,role,0,"read",1)
        user=frappe.get_doc("User",self.primary)
        if role not in {row.role for row in user.roles}:
            user.append("roles",{"role":role});user.save(ignore_permissions=True)
        frappe.clear_cache(user=self.primary)
        frappe.set_user(current)

    def make_units(self, count=1):
        current=frappe.session.user;frappe.set_user("Administrator")
        names=[]
        with trusted_write():
            for n in range(count):
                name="Selector "+self.prefix+" "+str(n)
                doc=frappe.get_doc({"doctype":"UOM","uom_name":name,"enabled":1,"cipher_unit_id":str(uuid.uuid4()),"cipher_dimension":"area","cipher_quantity_precision":4,"cipher_unit_revision":1}).insert(ignore_permissions=True)
                names.append((doc.name,doc.cipher_unit_id))
        frappe.set_user(current)
        return names

    def test_currency_choices_use_native_fraction_units(self):
        self.grant_native("Currency")
        value=_choose(self.company,"currencies",query="USD",count_mode="exact")
        self.assertEqual(value["company_currency"],frappe.db.get_value("Company",self.company,"default_currency"))
        usd=next(item for item in value["items"] if item["id"]=="USD")
        self.assertEqual(usd["exponent"],2)
        self.assertEqual(usd["kind"],"Currency")

    def test_private_unit_filter_denied_even_with_no_item_candidates(self):
        units=self.make_units()
        self.assertFalse(frappe.has_permission("UOM","read",doc=units[0][0],user=self.primary))
        with self.assertRaises(DomainError) as error:
            _choose(self.company,"items",query="no-such-item-"+self.prefix,unit_id=units[0][1])
        self.assertEqual(error.exception.status,404)

    def test_counts_and_cursor_only_use_visible_native_choices(self):
        self.make_units(2)
        hidden=_choose(self.company,"units",query=self.prefix,limit=1,count_mode="exact")
        self.assertEqual((hidden["items"],hidden["total"],hidden["next_cursor"]),([],0,None))
        self.grant_native("UOM")
        visible=_choose(self.company,"units",query=self.prefix,limit=1,count_mode="exact")
        self.assertEqual(visible["total"],2);self.assertEqual(len(visible["items"]),1)
        self.assertIsNotNone(visible["next_cursor"])
        following=_choose(self.company,"units",query=self.prefix,limit=1,count_mode="exact",cursor=visible["next_cursor"])
        self.assertNotEqual(visible["items"][0]["id"],following["items"][0]["id"])
        self.assertIsNone(following["next_cursor"])

    def test_cursor_binds_effective_currency_filters_mode_and_identity(self):
        self.make_units(2);self.grant_native("UOM")
        cursor=_choose(self.company,"units",query=self.prefix,limit=1,count_mode="exact")["next_cursor"]
        for changes in ({"query":"other"},{"count_mode":"none"},{"dimension":"length"}):
            args={"query":self.prefix,"limit":1,"count_mode":"exact","cursor":cursor,**changes}
            with self.assertRaises(DomainError) as error:_choose(self.company,"units",**args)
            self.assertEqual(error.exception.code,"invalid_cursor")
        frappe.set_user("Administrator")
        frappe.db.set_value("Company",self.company,"default_currency","EUR",update_modified=False)
        frappe.set_user(self.primary)
        with self.assertRaises(DomainError) as error:_choose(self.company,"units",query=self.prefix,limit=1,count_mode="exact",cursor=cursor)
        self.assertEqual(error.exception.code,"invalid_cursor")

    def test_project_duties_do_not_grant_company_master_access(self):
        frappe.set_user(self.project_user)
        with self.assertRaises(DomainError) as error:_choose(self.company,"currencies")
        self.assertEqual(error.exception.status,404)

    def test_price_list_filter_cannot_imply_unqualified_foreign_exchange(self):
        other="EUR" if frappe.db.get_value("Company",self.company,"default_currency")!="EUR" else "USD"
        with self.assertRaises(DomainError) as error:_choose(self.company,"price_lists",currency=other)
        self.assertEqual(error.exception.code,"currency_unsupported")
        self.grant_native("Currency")
        currency=frappe.db.get_value("Company",self.company,"default_currency")
        frappe.set_user("Administrator")
        frappe.db.set_value("Currency",currency,"fraction_units",3,update_modified=False)
        frappe.set_user(self.primary)
        with self.assertRaises(DomainError) as error:_choose(self.company,"price_lists",query="no-matching-price-list-"+self.prefix)
        self.assertEqual(error.exception.code,"currency_setup_required")

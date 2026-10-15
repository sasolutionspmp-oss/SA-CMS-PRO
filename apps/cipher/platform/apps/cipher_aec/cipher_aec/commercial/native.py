"""Supported ERPNext draft controllers plus persisted exact-decimal reconciliation."""
from decimal import Decimal
import frappe
from cipher_aec.api.contracts import digest, version_of
from cipher_aec.api.errors import DomainError
from cipher_aec.estimating.units import qualified, currency_policy
from .contracts import native_order


def require_native(doctype, name, actor, *, lock=False):
    try:
        doc = frappe.get_doc(doctype, name, for_update=lock)
        if not frappe.has_permission(doctype, ptype="read", doc=doc, user=actor.user):
            raise frappe.PermissionError
        return doc
    except (frappe.DoesNotExistError, frappe.PermissionError):
        raise DomainError("not_found", "This commercial source is not available.", 404) from None


def party(party_type, party_id, company, actor, *, lock=False):
    if party_type not in ("Customer", "Lead"):
        raise DomainError("invalid_commercial", "Select an existing native Customer or Lead.")
    doc = require_native(party_type, party_id, actor, lock=lock)
    if party_type == "Customer" and doc.get("accounts") and company not in {row.company for row in doc.accounts}:
        raise DomainError("not_found", "This commercial source is not available.", 404)
    return doc


def can_create(doctype, actor):
    if not frappe.has_permission(doctype, ptype="create", user=actor.user):
        raise DomainError("native_permission_denied", "Native create permission is required for this draft.", 403)


def sources(value, company, actor, *, lock=False, for_new=True, party_ref=None, native_refs=()):
    units = {}
    for unit_id in sorted({line["unit_id"] for line in value["price_lines"]}):
        units[unit_id] = qualified(unit_id, lock=lock, allow_disabled=not for_new)
        require_native("UOM", units[unit_id]["target"]["name"], actor, lock=lock)
    policy = currency_policy(value["currency"], lock=lock) if for_new else None
    require_native("Currency", value["currency"], actor, lock=lock)
    references = set(native_refs)
    references.add(("Price List", value["price_list"]))
    references.update(("Item", line["item_code"]) for line in value["price_lines"] if line["item_code"])
    if party_ref:
        references.add(tuple(party_ref))
    # One order across COM Company commands and EST Project commands. Nested
    # permission checks below may re-read only after this complete set is held.
    for doctype, name in sorted(references):
        record = require_native(doctype, name, actor, lock=lock)
        if doctype == "Item" and (for_new and record.disabled or company not in {row.company for row in record.item_defaults}):
            raise DomainError("not_found", "This commercial source is not available.", 404)
        if doctype == "Price List" and for_new:
            if not record.enabled or not record.selling or record.currency != value["currency"]:
                raise DomainError("price_list_setup_required", "Select an enabled native selling price list in the proposal currency.", 409)
            policy["price_list"] = {"name":record.name,"version":version_of(record),"currency":record.currency}
        if doctype == "Customer" and record.get("accounts") and company not in {row.company for row in record.accounts}:
            raise DomainError("not_found", "This commercial source is not available.", 404)
    for line in value["price_lines"]:
        unit = units[line["unit_id"]]
        if unit["revision"] != line["unit_revision"]:
            raise DomainError("stale_unit", "Refresh the qualified unit revision.", 412)
        q = Decimal(line["quantity"])
        if q != q.quantize(Decimal(1).scaleb(-unit["fields"]["precision"])):
            raise DomainError("unsupported_native_precision", "Line quantity exceeds the qualified unit precision.")
    return units, policy


def persisted(quotation_id):
    # Database strings are authoritative: a Python float round-trip is insufficient.
    fields = ("total", "net_total", "grand_total", "base_total", "base_net_total", "base_grand_total", "conversion_rate", "plc_conversion_rate", "discount_amount", "additional_discount_percentage", "total_taxes_and_charges")
    totals = frappe.db.sql("SELECT " + ",".join("CAST(`" + f + "` AS CHAR) AS `" + f + "`" for f in fields) + " FROM `tabQuotation` WHERE name=%s", (quotation_id,), as_dict=True)[0]
    rows = frappe.db.sql("SELECT name,cipher_line_id,cipher_alternate_group,item_code,item_name,description,uom,stock_uom,is_alternative,has_alternative_item,idx," + ",".join("CAST(`" + f + "` AS CHAR) AS `" + f + "`" for f in ("qty", "rate", "amount", "base_rate", "base_amount", "conversion_factor", "discount_percentage", "discount_amount")) + " FROM `tabQuotation Item` WHERE parent=%s ORDER BY idx", (quotation_id,), as_dict=True)
    doc = frappe.get_doc("Quotation", quotation_id)
    result = {"id": doc.name, "version": version_of(doc), "company": doc.company, "quotation_to": doc.quotation_to, "party_name": doc.party_name, "opportunity": doc.opportunity, "currency": doc.currency, "selling_price_list": doc.selling_price_list, "price_list_currency": doc.price_list_currency, "valid_till": str(doc.valid_till), "terms": doc.terms or "", "docstatus": doc.docstatus, "totals": dict(totals), "items": [dict(row) for row in rows], "taxes": [row.as_dict() for row in doc.taxes]}
    return result


def reconcile(actual, authored, priced, units):
    from frappe.utils import escape_html
    rows = {row["cipher_line_id"]: row for row in actual["items"]}
    if len(rows) != len(priced["lines"]) or actual["taxes"] or actual["docstatus"] != 0:
        raise DomainError("native_reconciliation", "The native draft does not preserve the declared proposal structure.", 409)
    for line in priced["lines"]:
        row = rows.get(line["id"])
        if row is None or row["is_alternative"] != int(not line["selected"]) or (row["cipher_alternate_group"] or None) != line["alternate_group"]:
            raise DomainError("native_reconciliation", "The native draft does not preserve alternate selection.", 409)
        expected_uom = units[line["unit_id"]]["target"]["name"]
        if row["uom"] != expected_uom or row["stock_uom"] != expected_uom or (row["item_code"] or None) != line["item_code"] or row["description"] != escape_html(line["description"]) or row["item_name"] != line["description"][:140]:
            raise DomainError("native_reconciliation", "The persisted ERPNext item or unit differs from the authored line.", 409)
        expected = {"qty": line["quantity"], "rate": line["rate"], "amount": line["amount"], "base_rate": line["rate"], "base_amount": line["amount"], "conversion_factor": "1", "discount_percentage": "0", "discount_amount": "0"}
        if any(Decimal(row[key]) != Decimal(value) for key, value in expected.items()):
            raise DomainError("unsupported_native_precision", "The persisted ERPNext line cannot exactly represent the authored quantity, price or amount.", 422)
    expected = {key: priced["total"] for key in ("total", "net_total", "grand_total", "base_total", "base_net_total", "base_grand_total")}
    expected.update(conversion_rate="1", plc_conversion_rate="1", discount_amount="0", additional_discount_percentage="0", total_taxes_and_charges="0")
    if any(Decimal(actual["totals"][key]) != Decimal(value) for key, value in expected.items()):
        raise DomainError("unsupported_native_precision", "The persisted ERPNext totals differ from the declared exact calculation.", 422)
    if actual["terms"] != escape_html(authored["terms"]).replace("\n", "<br>"):
        raise DomainError("native_reconciliation", "The native terms differ from the authored plain-text proposal.", 409)
    if actual["selling_price_list"] != authored["price_list"] or actual["price_list_currency"] != authored["currency"]:
        raise DomainError("native_reconciliation", "The native selling price list differs from the explicit proposal source.", 409)
    if actual["currency"] != authored["currency"] or actual["valid_till"] != authored["valid_till"]:
        raise DomainError("native_reconciliation", "The native currency or validity differs from the authored proposal.", 409)
    return digest(actual)


def materialize(quotation, value, priced, units):
    from frappe.utils import escape_html
    quotation.currency = value["currency"]
    quotation.conversion_rate = 1
    quotation.valid_till = value["valid_till"]
    quotation.terms = escape_html(value["terms"]).replace("\n", "<br>")
    quotation.apply_discount_on = "Grand Total"
    quotation.additional_discount_percentage = 0
    quotation.discount_amount = 0
    quotation.disable_rounded_total = 1
    quotation.selling_price_list = value["price_list"]
    quotation.price_list_currency = value["currency"]
    quotation.plc_conversion_rate = 1
    quotation.ignore_pricing_rule = 1
    quotation.set("taxes", [])
    quotation.set("items", [])
    for line in native_order(priced["lines"]):
        unit = units[line["unit_id"]]["target"]["name"]
        quotation.append("items", {"cipher_line_id": line["id"], "cipher_alternate_group": line["alternate_group"], "item_code": line["item_code"], "item_name": line["description"][:140], "description": escape_html(line["description"]), "qty": line["quantity"], "rate": line["rate"], "price_list_rate": line["rate"], "uom": unit, "stock_uom": unit, "conversion_factor": 1, "is_alternative": int(not line["selected"]), "has_alternative_item": int(bool(line["alternate_group"]) and line["selected"]), "discount_percentage": 0, "discount_amount": 0})
    from erpnext.accounts.utils import FiscalYearError
    try:
        if not quotation.name or quotation.is_new():
            quotation.insert(ignore_permissions=True)
        else:
            quotation.save(ignore_permissions=True)
    except FiscalYearError:
        raise DomainError("commercial_setup_required", "Configure an active native fiscal year for this company and draft date.", 409) from None
    except frappe.PermissionError:
        raise DomainError("native_permission_denied", "Current native source permissions do not permit this quotation draft.", 403) from None
    except frappe.ValidationError as error:
        raise DomainError("native_validation_failed", "ERPNext could not validate this draft against the current native master setup.", 422) from error
    actual = persisted(quotation.name)
    return actual, reconcile(actual, value, priced, units)

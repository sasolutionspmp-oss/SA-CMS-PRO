"""Independent target contract; no source-specific importer or second ERP master."""
SCHEMA = "cipher.canonical.v1"
COMPANY_SCHEMA = "cipher.canonical.v2"
PROJECT_STATUSES = frozenset({"Open", "On hold", "Completed", "Cancelled"})
DIMENSIONS = frozenset({"length", "area", "volume", "mass", "count", "time", "labor_time", "equipment_time"})
# Values describe the canonical format, not unrestricted native Frappe fields.
SPECS = {
    "company": {"required": {"name": "text", "currency": "currency", "timezone": "timezone"}, "optional": {}},
    "project": {"required": {"title": "text", "company_id": "ref:company", "status": "status"}, "optional": {"customer_id": "ref:customer"}},
    "customer": {"required": {"name": "text", "company_id": "ref:company", "active": "bool"}, "optional": {}},
    "supplier": {"required": {"name": "text", "company_id": "ref:company", "active": "bool"}, "optional": {}},
    "item": {"required": {"code": "code", "name": "text", "company_id": "ref:company", "stock_uom_id": "ref:uom", "is_stock_item": "bool"}, "optional": {}},
    "uom": {"required": {"symbol": "text", "dimension": "dimension", "precision": "precision"}, "optional": {}},
    "cost_center": {"required": {"code": "code", "name": "text", "company_id": "ref:company", "is_group": "bool"}, "optional": {"parent_id": "ref:cost_center"}},
    "cost_code": {"required": {"code": "code", "title": "text", "company_id": "ref:company"}, "optional": {}},
    "cost_type": {"required": {"code": "code", "title": "text", "company_id": "ref:company"}, "optional": {}},
    "accounting_dimension": {"required": {"code": "code", "title": "text", "company_id": "ref:company", "value_kind": "dimension_kind"}, "optional": {}},
}
NATIVE_DOCTYPES = {"company": "Company", "project": "Project", "customer": "Customer", "supplier": "Supplier",
                    "item": "Item", "uom": "UOM", "cost_center": "Cost Center"}
MAX_RECORDS, MAX_CONVERSIONS, MAX_QUANTITIES, MAX_JSON_BYTES = 500, 1000, 500, 2 * 1024 * 1024

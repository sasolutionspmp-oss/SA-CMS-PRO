"""Qualified native UOM adapters and explicit canonical rational manifests."""

from uuid import NAMESPACE_URL, uuid5

import frappe

from cipher_aec.api.errors import DomainError
from cipher_aec.migrations.contracts import SCHEMA
from cipher_aec.migrations.validation import ManifestError, parse_manifest

from .contracts import identifier
from . import scopes


def qualified(unit_id, *, lock=False, allow_disabled=False, actor=None):
    identifier(unit_id, "unit.id")
    if lock and scopes.active() and scopes.active().scope_type == "Company":
        from .lockplan import require_resources
        from cipher_aec.governance.context import current_actor
        require_resources({"unit_ids": [unit_id]}, actor or current_actor(), scopes.active().company)
    rows = frappe.db.sql("SELECT name,symbol,enabled,must_be_whole_number,cipher_unit_id,cipher_dimension,cipher_quantity_precision,cipher_unit_revision FROM `tabUOM` WHERE cipher_unit_id=%s" + (" FOR UPDATE" if lock else ""), (unit_id,), as_dict=True)
    if len(rows) == 1:
        from cipher_aec.commercial.native import require_native
        from cipher_aec.governance.context import current_actor
        require_native("UOM", rows[0].name, actor or current_actor(), lock=lock)
    if len(rows) != 1 or not allow_disabled and not rows[0].enabled:
        raise DomainError("unit_setup_required", "This unit is not qualified and enabled for exact estimating.", 409)
    row = rows[0]
    return {"id": row.cipher_unit_id, "kind": "uom", "revision": row.cipher_unit_revision,
            "fields": {"symbol": row.symbol or row.name, "dimension": row.cipher_dimension, "precision": row.cipher_quantity_precision},
            "target": {"doctype": "UOM", "name": row.name}}


def company_record(company, *, lock=False):
    from frappe.utils import get_system_timezone
    record = frappe.get_doc("Company", company, for_update=True) if lock else frappe.get_doc("Company", company)
    return {"id": str(uuid5(NAMESPACE_URL, "cipher:" + frappe.local.site + ":Company:" + company)), "kind": "company", "revision": 1,
            "fields": {"name": record.name, "currency": record.default_currency, "timezone": get_system_timezone()},
            "target": {"doctype": "Company", "name": record.name}}


def manifest(company, project, unit_ids, conversions, *, lock=False, dataset_id):
    unit_ids = set(unit_ids)
    for row in conversions:
        unit_ids.update((row["definition"]["from_unit_id"], row["definition"]["to_unit_id"]))
    if len(unit_ids) > 200 or len(conversions) > 64:
        raise DomainError("calculation_limit", "Use a bounded unit/conversion source manifest.")
    records = [qualified(unit_id, lock=lock) for unit_id in sorted(unit_ids)]
    scope = scopes.current(company, project)
    value = {"schema": "cipher.canonical.v2" if scope.scope_type == "Company" else SCHEMA, "dataset_id": dataset_id, "scope": scope.manifest_scope(),
             "records": [company_record(company, lock=lock and scope.scope_type == "Company"), *records], "unit_conversions": [row["definition"] for row in sorted(conversions, key=lambda row: row["id"])]}
    try:
        return parse_manifest(value)
    except ManifestError as error:
        raise DomainError("invalid_dimension", error.message, 422, {"field": error.path}) from None


def currency_policy(currency, *, lock=False, actor=None):
    if type(currency) is not str or len(currency) != 3 or not currency.isascii() or not currency.isalpha() or currency.upper() != currency:
        raise DomainError("invalid_currency", "Use an uppercase three-letter currency code.")
    from cipher_aec.commercial.native import require_native
    from cipher_aec.governance.context import current_actor
    if lock and scopes.active() and scopes.active().scope_type == "Company":
        from .lockplan import require_resources
        require_resources({"currencies": [currency]}, actor or current_actor(), scopes.active().company)
    require_native("Currency", currency, actor or current_actor(), lock=lock)
    rows = frappe.db.sql("SELECT name,enabled,fraction_units,modified FROM `tabCurrency` WHERE name=%s" + (" FOR UPDATE" if lock else ""), (currency,), as_dict=True)
    if not rows or not rows[0].enabled:
        raise DomainError("currency_setup_required", "The native currency must be explicitly enabled.", 409)
    value = rows[0].fraction_units
    exponents = {10**exponent: exponent for exponent in range(7)}
    if type(value) is not int or value not in exponents:
        raise DomainError("currency_setup_required", "Configure an exact power-of-ten native currency fraction before estimating.", 409)
    return {"currency": currency, "currency_exponent": exponents[value], "fraction_units": value, "native_currency_version": str(rows[0].modified)}


def verify_manifest_access(manifest, currency, actor):
    """Historical metadata still requires current native master read rights.

    Authorization does not add row locks out of the global native lock order;
    mutation manifests acquire their complete sorted UOM set separately.
    """
    from cipher_aec.commercial.native import require_native
    for row in sorted((manifest or {}).get("records", []), key=lambda row: row["id"]):
        if row["kind"] == "uom":
            require_native("UOM", row["target"]["name"], actor)
    if currency:
        require_native("Currency", currency, actor)

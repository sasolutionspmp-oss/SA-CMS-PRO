"""Qualified native UOM adapters and explicit canonical rational manifests."""

from uuid import NAMESPACE_URL, uuid5

import frappe

from cipher_aec.api.errors import DomainError
from cipher_aec.migrations.contracts import SCHEMA
from cipher_aec.migrations.validation import ManifestError, parse_manifest

from .contracts import identifier


def qualified(unit_id, *, lock=False, allow_disabled=False):
    identifier(unit_id, "unit.id")
    rows = frappe.db.sql("SELECT name,symbol,enabled,must_be_whole_number,cipher_unit_id,cipher_dimension,cipher_quantity_precision,cipher_unit_revision FROM `tabUOM` WHERE cipher_unit_id=%s" + (" FOR UPDATE" if lock else ""), (unit_id,), as_dict=True)
    if len(rows) != 1 or not allow_disabled and not rows[0].enabled:
        raise DomainError("unit_setup_required", "This unit is not qualified and enabled for exact estimating.", 409)
    row = rows[0]
    return {"id": row.cipher_unit_id, "kind": "uom", "revision": row.cipher_unit_revision,
            "fields": {"symbol": row.symbol or row.name, "dimension": row.cipher_dimension, "precision": row.cipher_quantity_precision},
            "target": {"doctype": "UOM", "name": row.name}}


def company_record(company):
    from frappe.utils import get_system_timezone
    record = frappe.get_doc("Company", company)
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
    value = {"schema": SCHEMA, "dataset_id": dataset_id, "scope": {"company": company, "project": project},
             "records": [company_record(company), *records], "unit_conversions": [row["definition"] for row in sorted(conversions, key=lambda row: row["id"])]}
    try:
        return parse_manifest(value)
    except ManifestError as error:
        raise DomainError("invalid_dimension", error.message, 422, {"field": error.path}) from None


def currency_policy(currency, *, lock=False):
    if type(currency) is not str or len(currency) != 3 or not currency.isascii() or not currency.isalpha() or currency.upper() != currency:
        raise DomainError("invalid_currency", "Use an uppercase three-letter currency code.")
    rows = frappe.db.sql("SELECT name,enabled,fraction_units,modified FROM `tabCurrency` WHERE name=%s" + (" FOR UPDATE" if lock else ""), (currency,), as_dict=True)
    if not rows or not rows[0].enabled:
        raise DomainError("currency_setup_required", "The native currency must be explicitly enabled.", 409)
    value = rows[0].fraction_units
    exponents = {10**exponent: exponent for exponent in range(7)}
    if type(value) is not int or value not in exponents:
        raise DomainError("currency_setup_required", "Configure an exact power-of-ten native currency fraction before estimating.", 409)
    return {"currency": currency, "currency_exponent": exponents[value], "fraction_units": value, "native_currency_version": str(rows[0].modified)}

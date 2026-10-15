"""Persistent estimating records with current locking reads on MariaDB."""

import json

import frappe

from cipher_aec.api.contracts import canonical_json, digest
from cipher_aec.api.errors import DomainError
from cipher_aec.governance.context import trusted_write

from .contracts import identifier

DOCTYPES = {
    "conversion": "Cipher Unit Conversion", "rate": "Cipher Rate Source", "assembly": "Cipher Assembly Revision",
    "estimate": "Cipher Estimate", "revision": "Cipher Estimate Revision", "line": "Cipher Estimate Line",
    "snapshot": "Cipher Calculation Snapshot",
}


def read(kind, record_id, *, lock=False):
    identifier(record_id, kind + ".id")
    suffix = " FOR UPDATE" if lock else ""
    rows = frappe.db.sql(f"SELECT data_json,record_digest FROM `tab{DOCTYPES[kind]}` WHERE name=%s" + suffix, (record_id,))
    if not rows:
        raise DomainError("not_found", "This estimating record is not available.", 404)
    value = json.loads(rows[0][0])
    if digest(value) != rows[0][1]:
        raise DomainError("estimate_integrity", "The stored estimate source cannot be verified.", 409)
    return value


def insert(kind, value, **fields):
    with trusted_write():
        doc = frappe.get_doc({"doctype": DOCTYPES[kind], "name": value["id"], "company": value["company"], "project": value["project"],
                             "author_person": value["author_person"], "status": value["status"], "data_json": canonical_json(value), "record_digest": digest(value), **fields})
        doc.insert(ignore_permissions=True, set_name=value["id"])
    return doc


def update_estimate(value):
    with trusted_write():
        doc = frappe.get_doc("Cipher Estimate", value["id"], for_update=True)
        doc.update({"data_json": canonical_json(value), "record_digest": digest(value), "current_revision": value["current_revision"],
                    "revision_number": value["revision_number"], "pricing_date": value["pricing_date"], "status": value["status"]})
        doc.save(ignore_permissions=True)
    return doc


def latest(kind, field, group_id):
    # Both table and field names are server-owned, never request/model paths.
    if (kind, field) not in {("rate", "source_id"), ("assembly", "assembly_id"), ("revision", "estimate")}:
        raise ValueError("Unsupported immutable revision chain")
    rows = frappe.db.sql(f"SELECT data_json FROM `tab{DOCTYPES[kind]}` WHERE `{field}`=%s ORDER BY revision_number DESC LIMIT 1 FOR UPDATE", (group_id,))
    return json.loads(rows[0][0]) if rows else None

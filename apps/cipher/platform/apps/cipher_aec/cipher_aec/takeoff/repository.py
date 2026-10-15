"""Canonical immutable takeoff DocTypes; JSON is the exact persisted fact."""
import json
import frappe
from cipher_aec.api.contracts import canonical_json, digest
from cipher_aec.api.errors import DomainError
from cipher_aec.estimating.contracts import identifier
from cipher_aec.governance.context import trusted_write

DOCTYPES = {"set": "Cipher Takeoff Set", "calibration": "Cipher Calibration", "verification": "Cipher Calibration Verification",
            "measurement": "Cipher Takeoff Measurement", "binding": "Cipher Takeoff Line Binding"}


def read(kind, record_id, *, lock=False):
    identifier(record_id, "takeoff.id")
    rows = frappe.db.sql(f"SELECT data_json,record_digest FROM `tab{DOCTYPES[kind]}` WHERE name=%s" + (" FOR UPDATE" if lock else ""), (record_id,))
    if not rows:
        raise DomainError("not_found", "This takeoff record is not available.", 404)
    value = json.loads(rows[0][0])
    if digest(value) != rows[0][1]:
        raise DomainError("takeoff_integrity", "The stored immutable takeoff fact cannot be verified.", 409)
    return value


def insert(kind, value, **fields):
    with trusted_write():
        doc = frappe.get_doc({"doctype": DOCTYPES[kind], "name": value["id"], "company": value["company"], "project": value["project"],
                              "scope_type": value.get("scope_type", "Project"), "author_person": value["author_person"], "status": value["status"], "data_json": canonical_json(value), "record_digest": digest(value), **fields})
        doc.insert(ignore_permissions=True, set_name=value["id"])
    return value


def latest(kind, family_id, *, lock=False):
    if kind not in {"measurement", "calibration"}:
        raise ValueError("Only measurement and calibration have immutable revision families")
    rows = frappe.db.sql(f"SELECT name FROM `tab{DOCTYPES[kind]}` WHERE family_id=%s ORDER BY revision_number DESC LIMIT 1" + (" FOR UPDATE" if lock else ""), (family_id,))
    return rows[0][0] if rows else None


def verification(calibration_id, *, lock=False):
    rows = frappe.db.sql("SELECT name FROM `tabCipher Calibration Verification` WHERE calibration=%s" + (" FOR UPDATE" if lock else ""), (calibration_id,))
    return read("verification", rows[0][0], lock=lock) if rows else None

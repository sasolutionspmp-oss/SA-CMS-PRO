"""Durable Frappe records; Redis is used only as a dispatch hint."""

from __future__ import annotations

import json
from contextlib import contextmanager
from typing import Any
from uuid import UUID

from .contracts import Authority, RickyError, canonical


DOCTYPES = {
    "run": "Cipher Ricky Run", "step": "Cipher Ricky Step",
    "invocation": "Cipher Tool Invocation", "proposal": "Cipher Proposed Change",
    "delegation": "Cipher Delegation", "artifact": "Cipher Run Artifact",
}


class FrappeStore:
    def __init__(self, *, worker: bool = False):
        import frappe
        self.frappe = frappe
        self.worker = worker

    @contextmanager
    def _trusted(self):
        from cipher_aec.governance.context import trusted_write
        with trusted_write():
            yield

    def insert(self, kind: str, value: dict) -> dict:
        with self._trusted():
            doc = self.frappe.get_doc({"doctype": DOCTYPES[kind], "name": value["id"], **self._fields(value)})
            doc.insert(ignore_permissions=True, set_name=value["id"])
        return value

    def get(self, kind: str, identifier: str, *, lock: bool = False) -> dict:
        try:
            if type(identifier) is not str or str(UUID(identifier)) != identifier:
                raise ValueError
        except (ValueError, AttributeError):
            raise RickyError("validation_error", "A Ricky record ID must be a canonical UUID.") from None
        if lock:
            # Table names come exclusively from the closed server-side map above.
            rows = self.frappe.db.sql(f"SELECT data_json FROM `tab{DOCTYPES[kind]}` WHERE name=%s FOR UPDATE", (identifier,))
            if not rows:
                raise RickyError("not_found", "The requested Ricky record is not accessible.")
            # Return the current locking read itself. A subsequent ordinary
            # get_doc can still read a pre-lock REPEATABLE-READ snapshot.
            return json.loads(rows[0][0])
        if not self.frappe.db.exists(DOCTYPES[kind], identifier):
            raise RickyError("not_found", "The requested Ricky record is not accessible.")
        return json.loads(self.frappe.get_doc(DOCTYPES[kind], identifier).data_json)

    def get_scoped(self, kind, identifier, *, lock=False):
        """Validate current native metadata before any scope/adapter dispatch."""
        try:
            if type(identifier) is not str or str(UUID(identifier)) != identifier:
                raise ValueError
        except (ValueError, AttributeError):
            raise RickyError("validation_error", "A Ricky record ID must be a canonical UUID.") from None
        rows = self.frappe.db.sql(f"SELECT name,scope_type,company,project,requested_by,person_id,run_id,data_json "
            f"FROM `tab{DOCTYPES[kind]}` WHERE name=%s" + (" FOR UPDATE" if lock else ""), (identifier,), as_dict=True)
        if len(rows) != 1:
            raise RickyError("not_found", "The requested Ricky record is not accessible.")
        row = rows[0]
        value = json.loads(row.data_json)
        if type(value) is not dict:
            raise RickyError("source_integrity", "The Ricky payload must be an object.")
        scope = value.get("scope_type", "Project")
        if (any(type(value.get(key)) is not str or not value[key] for key in ("company", "user", "person"))
                or type(scope) is not str or (row.scope_type or "Project") != scope or scope not in {"Company", "Project"}
                or any(row.get(field) != value.get(key) for field, key in
                    (("name", "id"), ("company", "company"), ("requested_by", "user"), ("person_id", "person")))
                or (row.project or None) != (value.get("project") or None)
                or (row.run_id or None) != (value.get("run_id") or None)):
            raise RickyError("source_integrity", "The native Ricky metadata differs from its original payload.")
        if scope == "Company":
            from .company_contracts import CompanyAuthority, decode_run_authority, decode_authority
            if row.project not in (None, "") or value.get("project") is not None:
                raise RickyError("source_integrity", "Company Ricky requires a null Project.")
            if kind == "run":
                decode_run_authority(value)
            else:
                authority = decode_authority(value.get("authority"))
                if type(authority) is not CompanyAuthority or authority.run_id != value.get("run_id"):
                    raise RickyError("source_integrity", "The child has a different original run authority.")
        elif type(value.get("project")) is not str or not value["project"]:
            raise RickyError("source_integrity", "Project Ricky requires its original Project.")
        elif kind == "run":
            try:
                # Use the original constructor, including its optional session
                # default, without rewriting the historical Project JSON.
                authority = Authority(**value["authority"])
            except (KeyError, TypeError):
                raise RickyError("source_integrity", "The original Project authority is invalid.") from None
            if any(getattr(authority, key) != value[key] for key in ("company", "project", "user", "person")):
                raise RickyError("source_integrity", "The original Project authority has a different native scope.")
        return value

    def save(self, kind: str, value: dict) -> None:
        with self._trusted():
            doc = self.frappe.get_doc(DOCTYPES[kind], value["id"], for_update=True)
            doc.update(self._fields(value))
            doc.save(ignore_permissions=True)

    def find(self, kind: str, filters: dict, *, limit: int = 100) -> list[dict]:
        rows = self.frappe.get_all(DOCTYPES[kind], filters=filters, fields=["data_json"], limit_page_length=limit, order_by="creation asc")
        return [json.loads(row.data_json) for row in rows]

    def count(self, kind: str, filters: dict) -> int:
        return self.frappe.db.count(DOCTYPES[kind], filters=filters)

    def admission_lock(self, person: str) -> None:
        # A site-wide policy row serializes admission, including the bounded queue.
        self.frappe.db.sql("SELECT name FROM `tabDocType` WHERE name='Cipher Ricky Run' FOR UPDATE")

    def checkpoint(self) -> None:
        if self.worker:
            self.frappe.db.commit()

    def savepoint(self, name: str) -> None:
        self.frappe.db.savepoint(name)

    def rollback_to(self, name: str) -> None:
        self.frappe.db.rollback(save_point=name)

    @staticmethod
    def _fields(value: dict) -> dict[str, Any]:
        fields = {
            "company": value.get("company"), "project": value.get("project"),
            "requested_by": value.get("user"), "person_id": value.get("person"),
            "run_id": value.get("run_id"), "status": value.get("status"),
            "operation_key": value.get("operation_key"), "data_json": canonical(value),
        }
        if value.get("scope_type") == "Company":
            fields["scope_type"] = "Company"
        return fields


class CompanyStore(FrappeStore):
    def insert(self, kind, value):
        if kind != "run" or value.get("scope_type") != "Company":
            return super().insert(kind, value)
        from .company_records import initial_run_admission
        if not initial_run_admission(value):
            raise RickyError("source_integrity", "A new Company Run requires its exact initial admission.")
        with self._trusted():
            # Frappe validates Links before inserting even a self-referenced
            # root. Its optional native self-Link is filled by a normal save
            # once the Run exists, before any child or receipt is inserted.
            fields = self._fields(value)
            fields["run_id"] = None
            doc = self.frappe.get_doc({"doctype": DOCTYPES[kind], "name": value["id"], **fields})
            doc.insert(ignore_permissions=True, set_name=value["id"])
            doc.run_id = value["run_id"]
            doc.save(ignore_permissions=True)
        self.get("run", value["id"])
        return value

    def get(self, kind, identifier, *, lock=False):
        return self.get_scoped(kind, identifier, lock=lock)

    def read_original(self, domain, kind, identifier):
        # Controller-only immutable integrity read, never a permission grant or
        # replacement for service authorization. No new master/domain locks.
        if domain != "estimate" or kind not in {"revision", "snapshot"}:
            raise RickyError("source_integrity", "Unsupported original calculation linkage.")
        from cipher_aec.estimating.repository import read
        return read(kind, identifier)

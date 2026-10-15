"""Durable Frappe records; Redis is used only as a dispatch hint."""

from __future__ import annotations

import json
from contextlib import contextmanager
from typing import Any
from uuid import UUID

from .contracts import RickyError, canonical


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
        return {
            "company": value.get("company"), "project": value.get("project"),
            "requested_by": value.get("user"), "person_id": value.get("person"),
            "run_id": value.get("run_id"), "status": value.get("status"),
            "operation_key": value.get("operation_key"), "data_json": canonical(value),
        }

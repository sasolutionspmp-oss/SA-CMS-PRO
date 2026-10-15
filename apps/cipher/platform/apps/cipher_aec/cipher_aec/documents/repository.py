"""Canonical Frappe DocTypes; indexes/extractions are not separate business truth."""
from __future__ import annotations


class FrappeDocumentRepository:
    def document(self, name, lock=False):
        import frappe
        if lock:
            frappe.db.sql("select name from `tabCipher Document` where name=%s for update", (name,))
        try:
            return frappe.get_doc("Cipher Document", name).as_dict()
        except frappe.DoesNotExistError:
            from cipher_aec.api.errors import DomainError
            raise DomainError("not_found", "Document was not found.", 404) from None

    def revision_scope(self, name):
        import frappe
        from cipher_aec.api.errors import DomainError
        row = frappe.db.get_value("Cipher Document Revision", name, ["name", "company", "project"], as_dict=True)
        if not row:
            raise DomainError("not_found", "Document revision was not found.", 404)
        return row

    def revision(self, name):
        import frappe
        return frappe.get_doc("Cipher Document Revision", name).as_dict()

    def documents(self, company, project):
        import frappe
        return frappe.get_all("Cipher Document", filters={"company": company, "project": project},
                              fields=["name", "title", "company", "project", "current_revision", "revision_number"],
                              order_by="modified desc", limit_page_length=100)

    def revisions(self, document_id):
        import frappe
        rows = frappe.get_all("Cipher Document Revision", filters={"document": document_id}, fields=["name"],
                              order_by="revision_number desc", limit_page_length=1000)
        return [self.revision(row.name) for row in rows]

    def search_candidates(self, company, project):
        # Current revisions only. A citation to any retained historical revision can still be reopened.
        return [{"name": doc["current_revision"]} for doc in self.documents(company, project) if doc["current_revision"]]

    def create_document(self, row):
        import frappe
        from cipher_aec.governance.context import trusted_write
        with trusted_write():
            frappe.get_doc({"doctype": "Cipher Document", **row}).insert(ignore_permissions=True, set_name=row["name"])

    def create_revision(self, row):
        import frappe
        from cipher_aec.governance.context import trusted_write
        with trusted_write():
            frappe.get_doc({"doctype": "Cipher Document Revision", **row}).insert(ignore_permissions=True, set_name=row["name"])

    def advance_document(self, name, revision_id, number):
        import frappe
        from cipher_aec.governance.context import trusted_write
        with trusted_write():
            doc = frappe.get_doc("Cipher Document", name)
            doc.current_revision, doc.revision_number = revision_id, number
            doc.save(ignore_permissions=True)

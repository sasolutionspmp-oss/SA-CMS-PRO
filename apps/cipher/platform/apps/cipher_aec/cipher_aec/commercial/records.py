"""Protected sidecars and append-only proposal evidence."""
import json
from frappe.model.document import Document
from cipher_aec.api.contracts import digest
from cipher_aec.api.errors import DomainError
from cipher_aec.governance.context import require_trusted_write, current_actor, require_company


class CommercialRecord(Document):
    def validate(self):
        require_trusted_write()
        try:
            value = json.loads(self.data_json)
        except (ValueError, TypeError):
            raise DomainError("commercial_integrity", "Commercial records require exact canonical JSON.", 409) from None
        if type(value) is not dict or value.get("id") != self.name or digest(value) != self.record_digest:
            raise DomainError("commercial_integrity", "Commercial evidence does not match its immutable fingerprint.", 409)
        for key in ("company", "author_person"):
            if self.get(key) != value.get(key):
                raise DomainError("commercial_integrity", "Commercial record scope does not match its payload.", 409)
        actor = current_actor()
        require_company(self.company, ability="commercial.write", actor=actor, lock=True)
        if self.is_new() and self.author_person != actor.person_id:
            raise DomainError("forged_authority", "Commercial authorship must be the current canonical person.", 403)
        before = self.get_doc_before_save()
        if before:
            if self.doctype == "Cipher Proposal Revision":
                raise DomainError("immutable_proposal_revision", "Create a successor proposal revision.", 409)
            old = json.loads(before.data_json)
            for key in ("id", "company", "author_person", "party_type", "party_id", "opportunity", "quotation", "pursuit"):
                if old.get(key) != value.get(key):
                    raise DomainError("immutable_commercial_scope", "Commercial scope and native master links cannot change.", 409)
            if value["revision_number"] != old["revision_number"] + 1:
                raise DomainError("stale_commercial", "Advance the commercial revision exactly once.", 412)
        for key in ("opportunity", "quotation", "pursuit", "revision_number", "current_revision", "party_type", "party_id", "title", "proposal", "predecessor", "native_fingerprint"):
            if key in value and self.get(key) != value[key]:
                raise DomainError("commercial_integrity", "Commercial index fields do not match the exact payload.", 409)
        if self.doctype == "Cipher Proposal Revision":
            sections = [{"id": r.stable_id, "kind": r.section_kind, "title": r.title, "text": r.content or ""} for r in self.sections]
            lines = [{"id": r.stable_id, "description": r.description, "quantity": r.quantity, "unit_id": r.unit_id, "unit_revision": r.unit_revision, "rate": r.rate, "amount": r.amount, "alternate_group": r.alternate_group or None, "selected": bool(r.selected)} for r in self.price_lines]
            expected_lines = [{key: row[key] for key in ("id", "description", "quantity", "unit_id", "unit_revision", "rate", "amount", "alternate_group", "selected")} for row in value["pricing"]["lines"]]
            if sections != value["composition"]["sections"] or lines != expected_lines:
                raise DomainError("commercial_integrity", "Proposal child rows do not match their immutable snapshot.", 409)

    def on_trash(self):
        raise DomainError("immutable_commercial_history", "Commercial identity and revision evidence cannot be deleted.", 403)

    def before_rename(self, *args, **kwargs):
        raise DomainError("immutable_commercial_history", "Commercial identities cannot be renamed.", 403)


class CommercialChild(Document):
    def validate(self):
        require_trusted_write()
        if not self.is_new():
            raise DomainError("immutable_proposal_revision", "Proposal revision child rows cannot be rewritten independently.", 409)

    def on_trash(self):
        raise DomainError("immutable_proposal_revision", "Proposal revision child rows cannot be deleted independently.", 403)

    def before_rename(self, *args, **kwargs):
        raise DomainError("immutable_proposal_revision", "Proposal revision line identities cannot be renamed.", 403)

"""Controllers protect immutable pricing facts through every write route."""

import json

from frappe.model.document import Document

from cipher_aec.api.contracts import digest
from cipher_aec.api.errors import DomainError
from cipher_aec.governance.context import current_actor, require_project, require_trusted_write
from cipher_aec.migrations.validation import ManifestError, parse_manifest

from .calculation import calculate, validate_assembly
from .contracts import business_date, identifier, rate_source, visible


class EstimatingRecord(Document):
    def validate(self):
        require_trusted_write()
        try:
            value = json.loads(self.data_json)
        except (ValueError, TypeError):
            raise DomainError("invalid_estimate", "An exact estimating record requires canonical JSON.") from None
        identifier(self.name, "record.id")
        if type(value) is not dict or value.get("id") != self.name or self.record_digest != digest(value):
            raise DomainError("estimate_integrity", "The estimating record digest does not match its exact payload.", 409)
        for field in ("company", "project", "author_person", "status"):
            if self.get(field) != value.get(field):
                raise DomainError("estimate_integrity", "The estimating scope does not match its payload.", 409)
        if not self.is_new() and self.doctype != "Cipher Estimate":
            raise DomainError("immutable_estimate_source", "Create a successor revision; authored sources and calculation snapshots are immutable.", 409)
        actor = current_actor()
        require_project(self.company, self.project, ability="estimate.write", actor=actor, lock=True)
        if self.is_new() and actor.person_id != value["author_person"]:
            raise DomainError("forged_authority", "An authored estimate record must use the current canonical person.", 403)
        if self.doctype == "Cipher Estimate":
            self._estimate(value)
        elif self.doctype == "Cipher Calculation Snapshot":
            if value["result"] != calculate(value["inputs"]) or value["input_digest"] != value["result"]["input_digest"] or value["output_digest"] != value["result"]["output_digest"]:
                raise DomainError("calculation_integrity", "A calculation snapshot must match its exact recomputed result.", 409)
        elif self.doctype in {"Cipher Rate Source", "Cipher Assembly Revision", "Cipher Unit Conversion"}:
            try:
                manifest = parse_manifest(value["unit_manifest"])
            except ManifestError as error:
                raise DomainError("invalid_dimension", error.message) from None
            if manifest["scope"] != {"company": self.company, "project": self.project}:
                raise DomainError("estimate_integrity", "Unit manifests must preserve the record scope.", 409)
            if self.doctype == "Cipher Rate Source":
                rate_source(value["rate"], {row["id"]: row for row in manifest["records"] if row["kind"] == "uom"})
            elif self.doctype == "Cipher Assembly Revision":
                validate_assembly(value["assembly"], manifest, value["rates"])
            from .sources import verify
            verify(self.company, self.project, value["source_citations"], actor, lock=True)
        elif self.doctype == "Cipher Estimate Line":
            from .repository import read
            revision = read("revision", value["estimate_revision"])
            snapshot = read("snapshot", revision["calculation_snapshot"])
            source = next((row for row in snapshot["inputs"]["lines"] if row["line_id"] == value["line_id"]), None)
            result = next((row for row in snapshot["result"]["lines"] if row["line_id"] == value["line_id"]), None)
            if source != value["authored"] or result != value["calculated"]:
                raise DomainError("calculation_integrity", "A stored estimate line must match its immutable calculation snapshot.", 409)

        from .sources import verify_native_rates
        linked_rates = ([value["rate"]] if self.doctype == "Cipher Rate Source" else
                        list(value["rates"].values()) if self.doctype == "Cipher Assembly Revision" else
                        list(value["inputs"]["rates"].values()) if self.doctype == "Cipher Calculation Snapshot" else [])
        if linked_rates:
            verify_native_rates(self.company, self.project, linked_rates, actor, lock=True)

    def _estimate(self, value):
        visible(value["title"], "estimate.title")
        business_date(value["pricing_date"], "estimate.pricing_date")
        if value["status"] != "draft" or self.current_revision != value["current_revision"] or self.revision_number != value["revision_number"]:
            raise DomainError("unsupported_estimate_transition", "EST-01 supports authored draft calculation only.", 409)
        before = self.get_doc_before_save()
        if before:
            old = json.loads(before.data_json)
            if any(old[key] != value[key] for key in ("id", "company", "project", "author_person", "title", "currency")):
                raise DomainError("immutable_estimate_scope", "An estimate cannot change its original scope or currency.", 409)
            if value["revision_number"] != old["revision_number"] + 1:
                raise DomainError("stale_estimate", "A new calculated revision must advance its predecessor exactly once.", 412)

    def on_trash(self):
        raise DomainError("immutable_estimate_source", "Estimating sources and calculation history cannot be deleted through document actions.", 403)

    def before_rename(self, *args, **kwargs):
        raise DomainError("immutable_estimate_source", "Estimating identities cannot be renamed.", 403)

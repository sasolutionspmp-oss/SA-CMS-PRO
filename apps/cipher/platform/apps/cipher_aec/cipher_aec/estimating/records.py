"""Controllers protect immutable pricing facts through every write route."""

import json

from frappe.model.document import Document

from cipher_aec.api.contracts import digest
from cipher_aec.api.errors import DomainError
from cipher_aec.governance.context import current_actor, require_trusted_write
from cipher_aec.estimating.scopes import require as require_project, record_scope
from cipher_aec.estimating import scopes
from cipher_aec.migrations.validation import ManifestError, parse_manifest

from .calculation import calculate, validate_assembly
from .contracts import business_date, identifier, rate_source, visible


class EstimatingRecord(Document):
    @record_scope
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
        if self.doctype == "Cipher Estimate Acceptance":
            self._acceptance(value, actor)
        elif self.doctype == "Cipher Estimate":
            self._estimate(value)
        elif self.doctype == "Cipher Calculation Snapshot":
            if value["result"] != calculate(value["inputs"]) or value["input_digest"] != value["result"]["input_digest"] or value["output_digest"] != value["result"]["output_digest"]:
                raise DomainError("calculation_integrity", "A calculation snapshot must match its exact recomputed result.", 409)
        elif self.doctype in {"Cipher Rate Source", "Cipher Assembly Revision", "Cipher Unit Conversion"}:
            try:
                manifest = parse_manifest(value["unit_manifest"])
            except ManifestError as error:
                raise DomainError("invalid_dimension", error.message) from None
            if manifest["scope"] != scopes.current(self.company, self.project).manifest_scope():
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
        owner = value if self.doctype == "Cipher Estimate" else None
        if self.doctype in {"Cipher Calculation Snapshot", "Cipher Estimate Revision", "Cipher Estimate Line"} and value.get("estimate"):
            from . import repository
            owner = repository.read("estimate", value["estimate"], lock=True)
            if not scopes.current(self.company, self.project).matches(owner):
                raise DomainError("estimate_integrity", "Estimate lineage must retain its exact original scope.", 409)
        from .sources import pursuit_plan
        plan = pursuit_plan(self.company, self.project, owner.get("pursuit_id"), actor, lock=True) if owner else None
        if linked_rates or plan:
            verify_native_rates(self.company, self.project, linked_rates, actor, lock=True, pursuit_plans=[plan])

    def _acceptance(self, value, actor):
        from . import governance, repository
        scopes.approval_effect(action=governance.ACTION, subject_id=value["estimate_revision"], packet_id=value["packet_id"])
        revision = repository.read("revision", value["estimate_revision"], lock=True)
        snapshot = repository.read("snapshot", value["calculation_snapshot"], lock=True)
        expected = governance.approval_manifest(actor=actor, company=self.company, project=self.project,
            subject_id=value["estimate_revision"], expected_version=digest(revision), lock=True,
            scope_type=scopes.current(self.company, self.project).scope_type)
        import frappe
        decision = frappe.get_doc("Cipher Approval Decision", value["decision_id"], for_update=True)
        previous = repository.latest_acceptance(value["estimate"], lock=True)
        if value["status"] != "accepted" or value["manifest"] != expected or value["manifest_digest"] != digest(expected) or value["accepted_result"] != snapshot["result"] or value["estimate"] != revision["estimate"] or value["calculation_snapshot"] != revision["calculation_snapshot"] or value["total"] != revision["total"] or value["currency"] != revision["currency"]:
            raise DomainError("acceptance_integrity", "An accepted baseline must preserve the exact independently approved original calculation.", 409)
        if decision.packet != value["packet_id"] or decision.decision != "Grant" or decision.actor_person != value["accepted_by_person"] or decision.actor_person == revision["author_person"]:
            raise DomainError("independent_estimate_required", "This baseline requires its exact independent human grant.", 403)
        if value["predecessor"] != (previous["id"] if previous else None) or value["baseline_number"] != (previous["baseline_number"] + 1 if previous else 1):
            raise DomainError("acceptance_integrity", "Accepted baseline history must advance its immutable predecessor exactly once.", 409)
        metadata = {key: value[key] for key in ("estimate", "estimate_revision", "calculation_snapshot", "baseline_number", "predecessor", "packet_id", "decision_id", "accepted_by_person", "manifest_digest", "currency")}
        metadata["total_amount"] = value["total"]["amount"]
        if any(self.get(key) != expected and not (self.get(key) in (None, "") and expected is None) for key, expected in metadata.items()):
            raise DomainError("acceptance_integrity", "Accepted baseline indexes must match the immutable original facts.", 409)

    def _estimate(self, value):
        visible(value["title"], "estimate.title")
        business_date(value["pricing_date"], "estimate.pricing_date")
        if value["status"] != "draft" or self.current_revision != value["current_revision"] or self.revision_number != value["revision_number"]:
            raise DomainError("unsupported_estimate_transition", "EST-01 supports authored draft calculation only.", 409)
        if scopes.current(self.company, self.project).scope_type == "Company":
            if (self.get("pursuit") or None) != value.get("pursuit_id"):
                raise DomainError("estimate_integrity", "The Pursuit index must match the immutable Company estimate link.", 409)
        elif value.get("pursuit_id") or self.get("pursuit"):
            raise DomainError("invalid_scope", "Pursuit linkage is explicit Company authority.", 422)
        before = self.get_doc_before_save()
        if before:
            old = json.loads(before.data_json)
            if any(old[key] != value[key] for key in ("id", "company", "project", "author_person", "title", "currency", "pricing_date")):
                raise DomainError("immutable_estimate_scope", "An estimate cannot change its original scope or currency.", 409)
            if old.get("scope_type", "Project") != value.get("scope_type", "Project") or old.get("pursuit_id") != value.get("pursuit_id"):
                raise DomainError("immutable_estimate_scope", "An estimate retains its original explicit scope and Pursuit.", 409)
            if value["revision_number"] != old["revision_number"] + 1:
                raise DomainError("stale_estimate", "A new calculated revision must advance its predecessor exactly once.", 412)

    def on_trash(self):
        raise DomainError("immutable_estimate_source", "Estimating sources and calculation history cannot be deleted through document actions.", 403)

    def before_rename(self, *args, **kwargs):
        raise DomainError("immutable_estimate_source", "Estimating identities cannot be renamed.", 403)

"""Immutable takeoff controllers protect every generic Frappe write route."""
import json
from frappe.model.document import Document
from cipher_aec.api.contracts import digest
from cipher_aec.api.errors import DomainError
from cipher_aec.governance.context import current_actor, require_project, require_trusted_write
from . import geometry, repository


class TakeoffRecord(Document):
    def validate(self):
        require_trusted_write()
        if not self.is_new():
            raise DomainError("immutable_takeoff", "Create an explicit successor; original takeoff facts cannot change.", 409)
        try:
            value = json.loads(self.data_json)
        except (TypeError, ValueError):
            raise DomainError("takeoff_integrity", "An immutable takeoff record requires canonical exact JSON.", 422) from None
        if type(value) is not dict or value.get("id") != self.name or self.record_digest != digest(value):
            raise DomainError("takeoff_integrity", "The takeoff payload digest does not agree with its identity.", 409)
        for field in ("company", "project", "author_person", "status"):
            if value.get(field) != self.get(field):
                raise DomainError("takeoff_integrity", "The canonical takeoff scope does not match its payload.", 409)
        actor = current_actor()
        require_project(self.company, self.project, ability="estimate.write", actor=actor, lock=True)
        if value["author_person"] != actor.person_id or value.get("author_user") != actor.user:
            raise DomainError("forged_authority", "Takeoff authorship comes from the current canonical person.", 403)
        from . import service
        metadata = {}
        if self.doctype == "Cipher Takeoff Set":
            metadata = {key: value[key] for key in ("title", "discipline")}
        elif self.doctype in {"Cipher Calibration", "Cipher Takeoff Measurement"}:
            metadata = {key: value[key] for key in ("takeoff_set", "family_id", "revision_number", "predecessor")}
            metadata.update(source_revision=value["source"]["revision_id"], source_sha256=value["source"]["source_sha256"], page=value["source"]["page"])
            if self.doctype == "Cipher Takeoff Measurement":
                metadata.update(method=value["definition"]["method"], calibration=value["calibration_id"], unit=value["result"]["quantity"]["unit_id"], quantity_amount=value["result"]["quantity"]["amount"])
        elif self.doctype == "Cipher Calibration Verification":
            metadata = {"calibration": value["calibration_id"], **{key: value[key] for key in ("packet_id", "decision_id", "verified_by_person")}}
        elif self.doctype == "Cipher Takeoff Line Binding":
            metadata = {"measurement": value["measurement_id"], **{key: value[key] for key in ("estimate", "estimate_revision", "estimate_line_record", "line_id")}}
        if any(self.get(key) != expected and not (self.get(key) in (None, "") and expected is None) for key, expected in metadata.items()):
            raise DomainError("takeoff_integrity", "Takeoff index metadata must match its exact immutable fact.", 409)
        if self.doctype == "Cipher Calibration":
            actual, content = service._source(self.company, self.project, service.source_input(value), actor, lock=True, new_use=True, calibrated=True)
            from .pdf import page_geometry
            if actual != value["source"] or page_geometry(content, actual["page"]) != value["page_geometry"]:
                raise DomainError("calibration_source_mismatch", "The calibration frame must come from these exact stored PDF bytes.", 412)
            geometry.calibration(value["definition"], value["unit_manifest"], value["page_geometry"])
            from cipher_aec.estimating.sources import verify
            if value["source_citations"]:
                verify(self.company, self.project, value["source_citations"], actor, lock=True)
        elif self.doctype == "Cipher Calibration Verification":
            from cipher_aec.governance.approvals import require_approval_effect
            require_approval_effect(action="calibration.verify.v1", subject_id=value["calibration_id"], packet_id=value["packet_id"])
            calibrated = service._read("calibration", value["calibration_id"], self.company, self.project, actor, lock=True, new_use=True)
            import frappe
            decision = frappe.get_doc("Cipher Approval Decision", value["decision_id"], for_update=True)
            if decision.packet != value["packet_id"] or decision.decision != "Grant" or decision.actor_person != value["verified_by_person"]:
                raise DomainError("approval_integrity", "This verification must identify the exact granted independent decision.", 409)
            if digest(calibrated) != value["calibration_digest"] or calibrated["author_person"] == value["verified_by_person"]:
                raise DomainError("independent_calibration_required", "This exact calibration needs an independent canonical person's verification.", 403)
        elif self.doctype == "Cipher Takeoff Measurement":
            calibrated = service._read("calibration", value["calibration_id"], self.company, self.project, actor, lock=True, new_use=True) if value["calibration_id"] else None
            service._source(self.company, self.project, service.source_input(value), actor, lock=True, new_use=True, calibrated=calibrated is not None)
            if calibrated:
                verified = repository.verification(calibrated["id"], lock=True)
                if not verified or verified["id"] != value["verification_id"] or verified["calibration_digest"] != digest(calibrated) or value["calibration_digest"] != digest(calibrated) or value["page_geometry"] != calibrated["page_geometry"] or service.source_input(calibrated) != service.source_input(value):
                    raise DomainError("calibration_unverified", "The measurement needs its exact verified source/page calibration.", 409)
            from cipher_aec.estimating import sources as estimate_sources, service as estimate_service
            conversions = estimate_service._conversion_records(self.company, self.project, value["conversion_ids"], actor, lock=True)
            expected_citations = estimate_sources.merge(calibrated["source_citations"] if calibrated else [], *(row["source_citations"] for row in conversions))
            if value["source_citations"] != expected_citations:
                raise DomainError("takeoff_integrity", "A measurement must retain every exact conversion/calibration source citation.", 409)
            service._verify_measurement_sources(value, actor, lock=True)
            result = geometry.measurement(value["definition"], value["unit_manifest"], calibrated["definition"] if calibrated else None, value["page_geometry"])
            if result != value["result"]:
                raise DomainError("takeoff_integrity", "The measurement must reproduce its exact geometry and result bounds.", 409)
        elif self.doctype == "Cipher Takeoff Line Binding":
            measured, line = service._binding_basis(self.company, self.project, value["measurement_id"], value["estimate_line_record"], value["quantity_basis"], actor, lock=True)
            if value["provenance"] != "subsequently-attached-takeoff-evidence-v1" or value["original_snapshot_claim"] != "authored-quantity-not-recomputed":
                raise DomainError("takeoff_integrity", "A later binding cannot claim the original snapshot was recomputed.", 409)
            if value["quantity"] != measured["result"]["quantity"] or value["estimate_revision"] != line["estimate_revision"] or value["line_id"] != line["line_id"] or value["estimate"] != line["estimate"] or value["measurement_digest"] != digest(measured) or value["estimate_line_digest"] != digest(line):
                raise DomainError("takeoff_integrity", "Line evidence must bind the exact original measurement and estimate line.", 409)

    def on_trash(self):
        raise DomainError("immutable_takeoff", "Original takeoff and calibration facts cannot be deleted.", 403)

    def before_rename(self, *args, **kwargs):
        raise DomainError("immutable_takeoff", "Takeoff identities cannot be renamed.", 403)

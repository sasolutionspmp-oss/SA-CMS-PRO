"""Explicit fixture-only fresh binding traversal and master acquisition order."""
from contextlib import ExitStack
from copy import deepcopy
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from cipher_aec.api.contracts import digest
from cipher_aec.api.errors import DomainError
from cipher_aec.estimating import scopes
from cipher_aec.takeoff import service


class VerifiedBindingBundleTests(unittest.TestCase):
    def setUp(self):
        self.actor = SimpleNamespace(user="fixture-author", person_id="fixture-person")
        self.scope = {"company": "Fixture Company", "project": "Fixture Project"}
        source = {"document_id": "drawing", "revision_id": "revision", "source_sha256": "a" * 64, "page": 1}
        self.calibration = {**self.scope, "id": "calibration", "family_id": "cal-family", "source": source,
            "definition": {}, "unit_manifest": {}, "source_citations": []}
        self.measurement = {**self.scope, "id": "measurement", "family_id": "measurement-family", "source": source,
            "definition": {"method": "calibrated", "waste_fraction": "0"}, "unit_manifest": {}, "source_citations": [],
            "calibration_id": "calibration", "verification_id": "verification",
            "result": {"quantity": {"amount": "200.000000", "unit_id": "area", "precision": 6}}}
        self.line = {**self.scope, "id": "line", "estimate": "estimate", "estimate_revision": "estimate-revision", "line_id": "stable-line",
            "authored": {"quantity": {"amount": "200", "unit_id": "area", "precision": 6}}, "calculated": {"components": []}}
        self.binding = {**self.scope, "id": "binding", "measurement_id": "measurement", "measurement_digest": digest(self.measurement),
            "estimate_line_record": "line", "estimate_line_digest": digest(self.line), "estimate": "estimate", "estimate_revision": "estimate-revision", "line_id": "stable-line",
            "quantity": self.measurement["result"]["quantity"], "quantity_basis": "net-quantity-v1",
            "provenance": "subsequently-attached-takeoff-evidence-v1", "original_snapshot_claim": "authored-quantity-not-recomputed"}
        self.verification = {"id": "verification", "calibration_digest": digest(self.calibration), "verified_by_person": "independent-person"}
        self.records = {"binding": self.binding, "measurement": self.measurement, "calibration": self.calibration}
        self.reads, self.sources = [], []
        self.stack = ExitStack(); self.addCleanup(self.stack.close)
        self.stack.enter_context(scopes.activate("Project", **self.scope))
        self.stack.enter_context(patch.object(service, "require_project"))
        self.stack.enter_context(patch.object(service.repository, "read", side_effect=self.read))
        self.stack.enter_context(patch.object(service.repository, "latest", side_effect=lambda kind, family, **kw: kind))
        self.stack.enter_context(patch.object(service.repository, "verification", side_effect=lambda *a, **kw: deepcopy(self.verification)))
        self.stack.enter_context(patch.object(service, "_source", side_effect=self.source))
        self.stack.enter_context(patch.object(service.estimates, "_scoped", return_value=self.line))

    def read(self, kind, name, **kwargs):
        self.reads.append((kind, name, kwargs))
        return deepcopy(self.records[kind])

    def source(self, company, project, value, actor, **kwargs):
        self.assertIs(actor, self.actor)
        self.assertTrue(kwargs["new_use"])
        self.sources.append((value, kwargs))
        return {**value, "document_id": "drawing", "current_revision": "revision", "is_current": True}, b"explicit-fixture-bytes"

    def run_bundle(self):
        return service.verified_binding_bundle("binding", actor=self.actor, lock=True, **self.scope)

    def test_calibrated_bundle_matches_current_use_shape_with_one_recursive_traversal(self):
        result = self.run_bundle()
        self.assertEqual([row[0] for row in self.reads], ["binding", "measurement", "calibration"])
        self.assertEqual(len(self.sources), 2)
        self.assertEqual(result["current_use"], {"eligible": True, "reasons": [], "current_working_revision": "revision", "head_policy": service.HEAD_POLICY,
            "original_record_preserved": True, "verification": {"id": "verification", "verified_by_person": "independent-person"}})
        self.assertEqual(result["measurement"], self.measurement)
        self.assertEqual(result["calibration"], self.calibration)
        # A second consequential builder performs every source/head check again.
        self.run_bundle()
        self.assertEqual(len(self.sources), 4)
        self.assertEqual(len(self.reads), 6)

    def test_manual_bundle_preserves_manual_identity_without_calibration_claim(self):
        self.measurement["definition"]["method"] = "manual"
        self.measurement["calibration_id"] = None
        self.measurement["verification_id"] = None
        self.binding["measurement_digest"] = digest(self.measurement)
        result = self.run_bundle()
        self.assertIsNone(result["calibration"])
        self.assertIsNone(result["current_use"]["verification"])
        self.assertEqual([row[0] for row in self.reads], ["binding", "measurement"])
        self.assertEqual(len(self.sources), 1)

    def test_stale_heads_and_current_source_denial_are_not_reused(self):
        self.run_bundle()
        with patch.object(service.repository, "latest", return_value="successor"):
            with self.assertRaises(DomainError) as caught:
                self.run_bundle()
            self.assertEqual(caught.exception.code, "superseded_takeoff")
        for code in ("not_found", "stale_drawing"):
            with patch.object(service, "_source", side_effect=DomainError(code, "Explicit fixture refusal", 404)):
                with self.assertRaises(DomainError) as caught:
                    self.run_bundle()
                self.assertEqual(caught.exception.code, code)

    def test_exact_verification_and_native_line_rights_still_required(self):
        self.verification["calibration_digest"] = "f" * 64
        with self.assertRaises(DomainError) as caught:
            self.run_bundle()
        self.assertEqual(caught.exception.code, "calibration_unverified")
        self.verification["calibration_digest"] = digest(self.calibration)
        with patch.object(service.estimates, "_scoped", side_effect=DomainError("not_found", "Native source denied", 404)):
            with self.assertRaises(DomainError) as caught:
                self.run_bundle()
            self.assertEqual(caught.exception.code, "not_found")

    def test_quantity_waste_and_immutable_binding_lineage_are_not_weakened(self):
        self.binding["estimate_line_digest"] = "f" * 64
        with self.assertRaises(DomainError) as caught:
            self.run_bundle()
        self.assertEqual(caught.exception.code, "takeoff_integrity")
        self.binding["estimate_line_digest"] = digest(self.line)
        self.line["authored"]["quantity"]["amount"] = "201"
        with self.assertRaises(DomainError) as caught:
            self.run_bundle()
        self.assertEqual(caught.exception.code, "quantity_mismatch")
        self.line["authored"]["quantity"]["amount"] = "200"
        self.measurement["definition"]["waste_fraction"] = "0.1"
        with self.assertRaises(DomainError) as caught:
            self.run_bundle()
        self.assertEqual(caught.exception.code, "quantity_basis_mismatch")


class AcceptanceBindingOrderTests(unittest.TestCase):
    def test_metadata_then_sorted_masters_then_one_bundle_in_both_scopes(self):
        from cipher_aec.estimating import governance
        from cipher_aec.takeoff import repository
        actor = SimpleNamespace(user="fixture-author", person_id="fixture-person")
        for scope_type, project in (("Project", "Fixture Project"), ("Company", None)):
            with self.subTest(scope=scope_type), ExitStack() as stack:
                company = "Fixture Company"; trace = []
                stack.enter_context(scopes.activate(scope_type, company, project))
                scope = scopes.current(company, project).fields()
                revision = {"id": "revision", "estimate": "estimate", "calculation_snapshot": "snapshot", "currency": "EUR", "policy_version": "fixed-policy", "source_citations": []}
                master = {"id": "estimate", "current_revision": "revision"}
                units = {key: {"id": key, "kind": "uom", "revision": 1, "fields": {"dimension": "area", "precision": 6}} for key in ("unit-a", "unit-z")}
                snapshot = {"inputs": {"unit_manifest": {"records": [units["unit-z"]]}, "currency_exponent": 2, "rates": {}, "basis_citations": []}, "id": "snapshot", "input_digest": "a", "output_digest": "b", "source_citations": []}
                measurement = {**scope, "company": company, "project": project, "id": "measurement", "calibration_id": "calibration", "unit_manifest": {"records": [units["unit-z"]]}}
                calibration = {**scope, "company": company, "project": project, "id": "calibration", "unit_manifest": {"records": [units["unit-a"]]}}
                binding = {**scope, "company": company, "project": project, "id": "binding", "measurement_id": "measurement"}
                state = {"eligible": True, "reasons": [], "current_working_revision": "drawing-revision", "head_policy": service.HEAD_POLICY,
                    "original_record_preserved": True, "verification": {"id": "verification", "verified_by_person": "independent-person"}}
                def read(kind, name, **kwargs):
                    trace.append(("metadata", kind))
                    return {"measurement": measurement, "calibration": calibration}[kind]
                def unit(name, **kwargs):
                    trace.append(("UOM", name)); return units[name]
                def currency(name, **kwargs):
                    trace.append(("Currency", name)); return {"currency_exponent": 2}
                def native(*args, **kwargs):
                    trace.append(("native", "union")); return []
                def bundle(*args, **kwargs):
                    trace.append(("verified", "binding"))
                    return {"binding": binding, "measurement": measurement, "calibration": calibration, "current_use": state}
                records = {"revision": revision, "estimate": master, "snapshot": snapshot}
                stack.enter_context(patch.object(governance.service, "_scoped", side_effect=lambda kind, *a, **kw: records[kind]))
                stack.enter_context(patch.object(governance, "_pinned", return_value=[]))
                stack.enter_context(patch.object(governance, "_binding_rows", return_value=[binding]))
                stack.enter_context(patch.object(repository, "read", side_effect=read))
                stack.enter_context(patch.object(governance.units, "qualified", side_effect=unit))
                stack.enter_context(patch.object(governance.units, "currency_policy", side_effect=currency))
                stack.enter_context(patch.object(governance.sources, "pursuit_plan", return_value=None))
                stack.enter_context(patch.object(governance.sources, "verify_native_rates", side_effect=native))
                stack.enter_context(patch.object(service, "_read", side_effect=AssertionError("Eager source authorization before full masters")))
                stack.enter_context(patch.object(service, "verified_binding_bundle", side_effect=bundle))
                stack.enter_context(patch("cipher_aec.estimating.lockplan.revision_plan", return_value={"generated_sources": []}))
                _, _, facts = governance._facts(actor=actor, company=company, project=project, subject_id="revision", lock=True)
                self.assertEqual(trace, [("metadata", "measurement"), ("metadata", "calibration"), ("UOM", "unit-a"), ("UOM", "unit-z"), ("Currency", "EUR"), ("native", "union"), ("verified", "binding")])
                self.assertEqual(facts["bindings"], [{"id": "binding", "digest": digest(binding), "measurement_id": "measurement", "measurement_digest": digest(measurement), "current_use": state}])


if __name__ == "__main__":
    unittest.main()

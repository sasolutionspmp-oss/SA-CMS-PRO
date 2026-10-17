"""Fixture-only original estimate authority with the generated-input gate closed."""
from contextlib import ExitStack
from copy import deepcopy
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from cipher_aec.api.contracts import digest
from cipher_aec.api.errors import DomainError
from cipher_aec.documents import provenance
from cipher_aec.estimating import governance, lockplan, scopes, service, sources
from cipher_aec.tests.test_estimating_citation_groups import citation


class HistoricalGeneratedSourceTests(unittest.TestCase):
    def setUp(self):
        self.assertIs(sources.GENERATED_INPUTS_QUALIFIED, False)
        self.actor = SimpleNamespace(user="fixture-original-user", person_id="fixture-original-person")
        self.company = "Fixture Company"
        scope = {"scope_type": "Company", "company": self.company, "project": None}
        self.cite = citation()
        total = {"amount": "250.00", "currency": "EUR"}
        revision = {**scope, "id": "revision", "estimate": "estimate", "calculation_snapshot": "snapshot", "currency": "EUR",
            "policy_version": "fixed-policy", "total": total, "source_citations": [deepcopy(self.cite)]}
        snapshot = {**scope, "id": "snapshot", "estimate": "estimate", "currency": "EUR", "source_citations": [deepcopy(self.cite)],
            "inputs": {"rates": {}, "assemblies": {}, "basis_citations": [deepcopy(self.cite)], "currency": "EUR", "unit_manifest": {"records": [], "unit_conversions": []}},
            "result": {"total": total}, "input_digest": "input", "output_digest": "output"}
        self.nodes = [{"document_id": self.cite["document_id"], "input_digest": "c" * 64}]
        facts = {"policy": governance.MANIFEST_POLICY, "scope": scope, "revision": {"id": "revision", "digest": digest(revision)},
            "snapshot": {"id": "snapshot", "digest": digest(snapshot), "input_digest": "input", "output_digest": "output"}, "pinned_records": [],
            "qualified_units": [], "native_references": [], "bindings": [], "generated_sources": deepcopy(self.nodes), "rounding_policy": "fixed-policy", "pursuit": None}
        self.manifest = {"subject": {"doctype": "Cipher Estimate Revision", "name": "revision"}, "effect": {"action": governance.ACTION, "revision_id": "revision", "facts": facts}, "sources": [deepcopy(self.cite)]}
        acceptance = {**scope, "id": "acceptance", "status": "accepted", "estimate": "estimate", "estimate_revision": "revision", "calculation_snapshot": "snapshot",
            "manifest": deepcopy(self.manifest), "manifest_digest": digest(self.manifest), "accepted_result": deepcopy(snapshot["result"]), "currency": "EUR", "total": total, "source_citations": [deepcopy(self.cite)]}
        self.records = {"revision": revision, "snapshot": snapshot, "acceptance": acceptance,
            "estimate": {**scope, "id": "estimate", "currency": "EUR", "current_revision": "later-working-revision", "pursuit_id": None}}
        self.stack = ExitStack(); self.addCleanup(self.stack.close)
        self.stack.enter_context(scopes.activate("Company", self.company, None))
        self.stack.enter_context(patch.object(service, "require_project", side_effect=self.require_current_actor))
        self.stack.enter_context(patch.object(sources, "require_project", side_effect=self.require_current_actor))
        self.stack.enter_context(patch.object(scopes, "require", side_effect=self.require_current_actor))
        self.stack.enter_context(patch.object(service.repository, "read", side_effect=lambda kind, *a, **kw: deepcopy(self.records[kind])))
        self.stack.enter_context(patch.object(governance, "_binding_rows", return_value=[]))
        self.stack.enter_context(patch.object(sources, "pursuit_plan", return_value=None))
        self.native = self.stack.enter_context(patch.object(sources, "verify_native_rates", return_value=[]))
        self.stack.enter_context(patch.object(service.units, "verify_manifest_access"))
        self.stack.enter_context(patch.object(provenance, "has_read_graph", return_value=False))
        self.stack.enter_context(patch.object(lockplan, "active_for", return_value=True))
        self.stack.enter_context(patch.object(lockplan, "revision_plan", return_value={"generated_sources": deepcopy(self.nodes)}))
        self.node_manifest = self.stack.enter_context(patch.object(provenance, "node_manifest", side_effect=lambda *a, **kw: deepcopy(self.nodes)))
        self.identity = self.stack.enter_context(patch.object(provenance, "mutation_source_identity", return_value={"generated": True, "document_id": self.cite["document_id"], "input_digest": "c" * 64}))
        self.stack.enter_context(patch.object(lockplan, "admitted", return_value=True))
        db = SimpleNamespace(get_value=lambda *a, **kw: SimpleNamespace(company=self.company, project=None, scope_type="Company"), sql=lambda *a, **kw: [])
        self.stack.enter_context(patch.object(sources.frappe, "db", db, create=True))
        self.canonical = self.stack.enter_context(patch("cipher_aec.documents.service.get_company_citation", side_effect=self.canonical_citation))

    def require_current_actor(self, company, project, *, actor, **kwargs):
        if (actor.user, actor.person_id) != (self.actor.user, self.actor.person_id):
            raise DomainError("not_found", "Fixture current identity unavailable", 404)

    def canonical_citation(self, company, revision, page, *, actor, **kwargs):
        self.require_current_actor(company, None, actor=actor)
        return deepcopy(self.cite)

    def historical(self, *, lock, phase="receipt", actor=None):
        return governance.authorize_subject(actor=actor or self.actor, company=self.company, project=None, subject_id="revision", phase=phase,
            manifest=deepcopy(self.manifest), lock=lock, scope_type="Company")

    def test_original_receipt_and_baseline_keep_locking_and_current_canonical_authority(self):
        for lock in (False, True):
            for phase in ("receipt", "baseline"):
                with self.subTest(lock=lock, phase=phase):
                    self.assertEqual(self.historical(lock=lock, phase=phase), self.records["revision"])
                    self.assertEqual(self.canonical.call_args.kwargs["lock"], lock)
        self.identity.assert_not_called()
        self.assertEqual(self.node_manifest.call_count, 4)
        self.assertEqual(self.native.call_count, 4)

    def test_accepted_baseline_checks_its_own_exact_citations_with_gate_closed(self):
        for lock in (False, True):
            self.assertEqual(service._scoped("acceptance", "acceptance", self.company, None, self.actor, lock=lock), self.records["acceptance"])
        self.identity.assert_not_called()

    def test_new_locked_source_use_remains_denied_after_historical_read(self):
        self.historical(lock=False)
        ref = {name: self.cite[name] for name in ("revision_id", "page", "excerpt_sha256", "source_sha256")}
        with self.assertRaises(DomainError) as caught:
            sources.resolve(self.company, None, [ref], self.actor, lock=True)
        self.assertEqual(caught.exception.code, "source_dependency_unqualified")

    def test_fresh_acceptance_manifest_still_requires_new_input_admission(self):
        with self.assertRaises(DomainError) as caught:
            governance.approval_manifest(actor=self.actor, company=self.company, project=None, subject_id="revision",
                expected_version=digest(self.records["revision"]), lock=True, scope_type="Company")
        self.assertEqual(caught.exception.code, "source_dependency_unqualified")
        self.canonical.assert_not_called()

    def test_exact_original_source_checksum_cannot_be_replaced(self):
        self.canonical.side_effect = None
        self.canonical.return_value = {**self.cite, "source_sha256": "d" * 64}
        with self.assertRaises(DomainError) as caught:
            self.historical(lock=True)
        self.assertEqual(caught.exception.code, "stale_source")

    def test_original_source_bytes_and_current_source_rights_remain_required(self):
        for code in ("not_found", "source_integrity", "source_prelock_required"):
            self.canonical.side_effect = DomainError(code, "Fixture canonical source denied", 404 if code == "not_found" else 409)
            with self.assertRaises(DomainError) as caught:
                self.historical(lock=True)
            self.assertEqual(caught.exception.code, code)

    def test_current_native_rights_and_original_generated_closure_remain_required(self):
        self.native.side_effect = DomainError("not_found", "Fixture current native authority revoked", 404)
        with self.assertRaises(DomainError) as caught:
            self.historical(lock=True)
        self.assertEqual(caught.exception.code, "not_found")
        self.native.side_effect = None
        self.nodes[0]["input_digest"] = "d" * 64
        with self.assertRaises(DomainError) as caught:
            self.historical(lock=True)
        self.assertEqual(caught.exception.code, "approval_integrity")

    def test_original_record_lineage_and_complete_citation_copies_remain_bound(self):
        self.records["revision"]["source_citations"][0]["document_title"] = "altered fixture copy"
        with self.assertRaises(DomainError) as caught:
            self.historical(lock=True)
        self.assertEqual(caught.exception.code, "approval_integrity")
        # Even a consistent stored-record digest cannot authorize a changed copy.
        self.manifest["effect"]["facts"]["revision"]["digest"] = digest(self.records["revision"])
        with self.assertRaises(DomainError) as caught:
            self.historical(lock=True)
        self.assertEqual(caught.exception.code, "source_integrity")

    def test_accepted_manifest_and_result_cannot_drift_before_original_source_use(self):
        for key in ("manifest_digest", "accepted_result", "source_citations"):
            with self.subTest(field=key):
                original = deepcopy(self.records["acceptance"])
                self.records["acceptance"][key] = "altered fixture value"
                with self.assertRaises(DomainError) as caught:
                    service._scoped("acceptance", "acceptance", self.company, None, self.actor, lock=True)
                self.assertEqual(caught.exception.code, "approval_integrity")
                self.records["acceptance"] = original

    def test_user_and_person_current_identity_cannot_change(self):
        for user, person in (("fixture-alias", self.actor.person_id), (self.actor.user, "different-person")):
            with self.assertRaises(DomainError) as caught:
                self.historical(lock=True, actor=SimpleNamespace(user=user, person_id=person))
            self.assertEqual(caught.exception.code, "not_found")


class BoundHistoricalGeneratedSourceTests(unittest.TestCase):
    require_current_actor = HistoricalGeneratedSourceTests.require_current_actor
    canonical_citation = HistoricalGeneratedSourceTests.canonical_citation
    historical = HistoricalGeneratedSourceTests.historical

    def setUp(self):
        HistoricalGeneratedSourceTests.setUp(self)
        from cipher_aec.takeoff import service as takeoff
        self.takeoff = takeoff
        scope = {"scope_type": "Company", "company": self.company, "project": None}
        source = {name: self.cite[name] for name in ("document_id", "revision_id", "source_sha256", "page")}
        calibration = {**scope, "id": "calibration", "family_id": "calibration-family", "source": deepcopy(source),
            "source_citations": [deepcopy(self.cite)], "unit_manifest": {"records": []}}
        measurement = {**scope, "id": "measurement", "family_id": "measurement-family", "source": deepcopy(source),
            "definition": {"method": "calibrated"}, "calibration_id": "calibration", "verification_id": "verification",
            "conversion_ids": ["11111111-1111-4111-8111-111111111111"], "unit_manifest": {"records": []}}
        binding = {**scope, "id": "binding", "measurement_id": "measurement", "estimate_line_record": "line", "estimate_revision": "revision"}
        verification = {**scope, "id": "verification", "calibration_digest": digest(calibration)}
        self.takeoff_records = {"binding": binding, "measurement": measurement, "calibration": calibration, "verification": verification}
        self.records["line"] = {**scope, "id": "line", "estimate": "estimate", "estimate_revision": "revision", "source_citations": [deepcopy(self.cite)]}
        self.records["conversion"] = {**scope, "id": "11111111-1111-4111-8111-111111111111", "source_citations": [deepcopy(self.cite)]}
        self.manifest["effect"]["facts"]["bindings"] = [{"id": "binding", "digest": digest(binding), "measurement_id": "measurement", "measurement_digest": digest(measurement)}]
        self.records["acceptance"]["manifest"] = deepcopy(self.manifest)
        self.records["acceptance"]["manifest_digest"] = digest(self.manifest)
        self.stack.enter_context(patch.object(takeoff, "require_project", side_effect=self.require_current_actor))
        self.takeoff_read = self.stack.enter_context(patch.object(takeoff.repository, "read", side_effect=lambda kind, *a, **kw: deepcopy(self.takeoff_records[kind])))
        self.verification = self.stack.enter_context(patch.object(takeoff.repository, "verification", side_effect=lambda *a, **kw: deepcopy(self.takeoff_records["verification"])))
        self.latest = self.stack.enter_context(patch.object(takeoff.repository, "latest", return_value="later-working-successor"))
        self.drawing = {**source, "is_current": False, "mime_type": "application/pdf", "content": b"explicit original PDF fixture"}
        self.drawing_read = self.stack.enter_context(patch("cipher_aec.documents.service.company_source_reference", side_effect=self.drawing_source))

    def drawing_source(self, company, revision, page, *, actor, **kwargs):
        self.require_current_actor(company, None, actor=actor)
        return deepcopy(self.drawing)

    def test_exact_bound_originals_allow_old_heads_with_lock_and_without_lock(self):
        for lock in (False, True):
            for phase in ("receipt", "baseline"):
                self.historical(lock=lock, phase=phase)
                self.assertEqual(self.drawing_read.call_args.kwargs["lock"], lock)
        self.latest.assert_not_called()
        self.identity.assert_not_called()
        kinds = {call.args[0] for call in self.takeoff_read.call_args_list}
        self.assertTrue({"binding", "measurement", "calibration"} <= kinds)
        self.assertTrue({"line", "conversion", "revision", "snapshot"} <= {call.args[0] for call in service.repository.read.call_args_list})

    def test_accepted_baseline_retains_original_bound_recursion(self):
        result = service._scoped("acceptance", "acceptance", self.company, None, self.actor, lock=True)
        self.assertEqual(result, self.records["acceptance"])
        self.assertTrue(self.drawing_read.called)
        self.identity.assert_not_called()

    def test_fresh_bound_use_stays_denied_after_original_read(self):
        self.historical(lock=False)
        previous = self.drawing_read.call_count
        for new_use in (False, True):
            with self.assertRaises(DomainError) as caught:
                self.takeoff._read("binding", "binding", self.company, None, self.actor, lock=True, new_use=new_use)
            self.assertEqual(caught.exception.code, "source_dependency_unqualified")
        self.assertEqual(self.drawing_read.call_count, previous)

    def test_bound_original_drawing_authority_bytes_and_identity_stay_checked(self):
        for code in ("not_found", "source_integrity", "source_prelock_required"):
            self.drawing_read.side_effect = DomainError(code, "Fixture original drawing denied", 404 if code == "not_found" else 409)
            with self.assertRaises(DomainError) as caught:
                self.historical(lock=True)
            self.assertEqual(caught.exception.code, code)
        self.drawing_read.side_effect = self.drawing_source
        self.drawing["source_sha256"] = "d" * 64
        with self.assertRaises(DomainError) as caught:
            self.historical(lock=True)
        self.assertEqual(caught.exception.code, "source_mismatch")

    def test_calibration_verification_and_original_binding_digests_remain_bound(self):
        self.takeoff_records["verification"]["calibration_digest"] = "changed-fixture-digest"
        with self.assertRaises(DomainError) as caught:
            self.historical(lock=True)
        self.assertEqual(caught.exception.code, "calibration_unverified")
        self.takeoff_records["verification"]["calibration_digest"] = digest(self.takeoff_records["calibration"])
        self.takeoff_records["binding"]["estimate_revision"] = "another-revision"
        with self.assertRaises(DomainError) as caught:
            self.historical(lock=True)
        self.assertEqual(caught.exception.code, "approval_integrity")

    def test_conversion_fallback_and_estimate_line_keep_scope_and_canonical_citations(self):
        for kind in ("conversion", "line"):
            original = deepcopy(self.records[kind])
            self.records[kind]["source_citations"][0]["document_title"] = "changed-fixture-copy"
            with self.assertRaises(DomainError) as caught:
                self.historical(lock=True)
            self.assertEqual(caught.exception.code, "source_integrity")
            self.records[kind] = deepcopy(original)
            self.records[kind]["company"] = "Different Company"
            with self.assertRaises(DomainError) as caught:
                self.historical(lock=True)
            self.assertEqual(caught.exception.code, "not_found")
            self.records[kind] = original

    def test_nested_estimate_snapshot_still_requires_current_native_rights(self):
        self.records["snapshot"]["inputs"]["rates"] = {"rate": {"currency": "EUR", "source_citations": [deepcopy(self.cite)]}}
        self.manifest["effect"]["facts"]["snapshot"]["digest"] = digest(self.records["snapshot"])
        self.native.side_effect = [[], DomainError("not_found", "Fixture linked snapshot native source revoked", 404)]
        with self.assertRaises(DomainError) as caught:
            self.historical(lock=True)
        self.assertEqual(caught.exception.code, "not_found")
        self.assertEqual(self.native.call_count, 2)


if __name__ == "__main__":
    unittest.main()

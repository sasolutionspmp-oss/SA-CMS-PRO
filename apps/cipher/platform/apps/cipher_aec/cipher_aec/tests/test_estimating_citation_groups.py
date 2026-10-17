"""Explicit fixtures for one-builder full-citation canonical comparisons."""
from contextlib import ExitStack
from copy import deepcopy
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from cipher_aec.api.contracts import digest
from cipher_aec.api.errors import DomainError
from cipher_aec.documents import provenance
from cipher_aec.estimating import governance, scopes, sources


def citation(index=0):
    return {"id": "canonical-citation-" + str(index), "revision_id": "revision-" + str(index), "document_id": "document-" + str(index),
        "page": 1, "page_label": "1", "document_title": "Explicit source fixture", "revision_number": 1,
        "excerpt_sha256": "a" * 64, "source_sha256": "b" * 64, "excerpt": "Explicit fixture text"}


class BuilderCitationGroupsTests(unittest.TestCase):
    def setUp(self):
        self.actor = SimpleNamespace(user="fixture-author", person_id="fixture-person")
        self.canonical = {"revision-" + str(index): citation(index) for index in range(128)}
        self.allowed = True
        self.calls = []
        self.patch = patch.object(sources, "resolve", side_effect=self.resolve)
        self.patch.start(); self.addCleanup(self.patch.stop)

    def resolve(self, company, project, refs, actor, **kwargs):
        self.calls.append((deepcopy(refs), actor, kwargs))
        if not self.allowed or actor.user != self.actor.user:
            raise DomainError("not_found", "Explicit fixture original-source refusal", 404)
        return [deepcopy(self.canonical[row["revision_id"]]) for row in refs]

    def verify(self, groups, actor=None):
        return sources.verify_groups("Fixture Company", "Fixture Project", groups, actor or self.actor, lock=True)

    def integrity(self, groups):
        with self.assertRaises(DomainError) as caught:
            self.verify(groups)
        self.assertEqual(caught.exception.code, "source_integrity")

    def test_duplicate_copies_resolve_once_but_each_full_object_is_required(self):
        row = citation()
        result = self.verify([([row, deepcopy(row)], 64), ([deepcopy(row)], 8)])
        self.assertEqual(result, [row])
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(len(self.calls[0][0]), 1)
        self.assertIs(self.calls[0][1], self.actor)
        self.assertTrue(self.calls[0][2]["lock"])

    def test_altered_duplicate_cannot_be_overwritten_by_later_correct_copy(self):
        for field in ("document_id", "document_title", "revision_number", "page_label", "excerpt", "id"):
            with self.subTest(field=field):
                bad = citation(); bad[field] = "altered-fixture-value"
                self.integrity([([citation(), bad, citation()], 64)])

    def test_missing_and_extra_metadata_refused_for_every_duplicate_copy(self):
        missing, extra = citation(), citation()
        missing.pop("document_title"); extra["unregistered_field"] = "explicit fixture"
        for bad in (missing, extra):
            self.integrity([([citation(), bad, citation()], 64)])

    def test_numeric_metadata_cannot_change_type_through_python_equality(self):
        for value in (True, 1.0, "1"):
            bad = citation(); bad["revision_number"] = value
            self.integrity([([citation(), bad, citation()], 64)])

    def test_source_checksum_is_part_of_distinct_locator_and_never_id_only(self):
        bad = citation(); bad["source_sha256"] = "c" * 64
        self.integrity([([bad, citation()], 64)])
        self.assertEqual(len(self.calls[-1][0]), 2)

    def test_malformed_locator_types_refused_before_lookup(self):
        for key, value in (("page", True), ("page", []), ("revision_id", {}), ("excerpt_sha256", "wrong"), ("source_sha256", None)):
            with self.subTest(field=key):
                row = citation(); row[key] = value
                self.integrity([([row], 64)])
        row = citation(); row.pop("source_sha256")
        self.integrity([([row], 64)])
        self.assertEqual(self.calls, [])

    def test_empty_batch_does_not_add_document_duty(self):
        with patch.object(sources, "require_project", side_effect=AssertionError("Empty batch must not demand source rights")):
            self.assertEqual(self.verify([]), [])
            self.assertEqual(self.verify([([], 64), ([], 8)]), [])
        self.assertEqual(self.calls, [])

    def test_current_source_denial_new_builder_and_different_actor_not_reused(self):
        groups = [([citation()], 64)]
        self.verify(groups); self.verify(groups)
        self.assertEqual(len(self.calls), 2)
        self.allowed = False
        with self.assertRaises(DomainError) as caught:
            self.verify(groups)
        self.assertEqual(caught.exception.code, "not_found")
        self.allowed = True
        alias = SimpleNamespace(user="fixture-alias", person_id=self.actor.person_id)
        with self.assertRaises(DomainError) as caught:
            self.verify(groups, alias)
        self.assertEqual(caught.exception.code, "not_found")
        self.assertEqual(len(self.calls), 4)

    def test_per_group_bounds_preserved_without_union_wide64_cap(self):
        self.verify([([citation(i) for i in range(64)], 64), ([citation(i) for i in range(64, 128)], 64)])
        self.assertEqual(len(self.calls), 16)
        for groups in ([([citation()] * 65, 64)], [([citation()] * 9, 8)]):
            with self.assertRaises(DomainError):
                self.verify(groups)

    def test_literal_typed_collector_covers_all_original_embedded_occurrences(self):
        row = citation()
        cases = {
            "revision": ({"source_citations": [row]}, [64]),
            "conversion": ({"source_citations": [row]}, [64]),
            "rate": ({"source_citations": [row], "rate": {"source_citations": [row]}}, [64, 8]),
            "assembly": ({"source_citations": [row], "rates": {"rate": {"source_citations": [row]}}}, [64, 8]),
            "snapshot": ({"source_citations": [row], "inputs": {"basis_citations": [row], "rates": {"rate": {"source_citations": [row]}}}}, [64, 8, 8]),
        }
        for kind, (record, limits) in cases.items():
            with self.subTest(kind=kind):
                groups = sources.citation_groups(kind, record)
                self.assertEqual([bound for _, bound in groups], limits)
                self.assertTrue(all(values[0] is row for values, _ in groups))
                self.verify(groups)
        for kind in ("line", "acceptance", "estimate"):
            with self.assertRaises(DomainError):
                sources.citation_groups(kind, {"source_citations": [row]})

    def test_collector_preserves_existing_assembly_and_snapshot_rate_bounds(self):
        for kind, limit in (("assembly", 50), ("snapshot", 500)):
            rates = {str(i): {"source_citations": []} for i in range(limit + 1)}
            record = {"source_citations": [], **({"rates": rates} if kind == "assembly" else {"inputs": {"rates": rates, "basis_citations": []}})}
            with self.assertRaises(DomainError) as caught:
                sources.citation_groups(kind, record)
            self.assertEqual(caught.exception.code, "source_integrity")


class AcceptanceBuilderBoundariesTests(unittest.TestCase):
    def setUp(self):
        self.actor = SimpleNamespace(user="fixture-author", person_id="fixture-person")
        self.company, self.project = "Fixture Company", "Fixture Project"
        scope = {"company": self.company, "project": self.project}
        cite = citation()
        rate = {"id": "rate", "currency": "EUR", "source_citations": [cite]}
        self.records = {
            "revision": {**scope, "id": "revision", "estimate": "estimate", "calculation_snapshot": "snapshot", "currency": "EUR", "policy_version": "fixed-policy", "source_citations": [cite]},
            "estimate": {**scope, "id": "estimate", "current_revision": "revision"},
            "snapshot": {**scope, "id": "snapshot", "input_digest": "input", "output_digest": "output", "source_citations": [cite],
                "inputs": {"unit_manifest": {"records": [], "unit_conversions": []}, "currency_exponent": 2, "rates": {"rate": deepcopy(rate)}, "assemblies": {}, "basis_citations": [cite]}},
            "rate": {**scope, "id": "rate", "rate": deepcopy(rate), "source_citations": [cite]},
        }
        self.allowed, self.resolved, self.reads = True, [], []
        self.stack = ExitStack(); self.addCleanup(self.stack.close)
        self.stack.enter_context(scopes.activate("Project", self.company, self.project))
        self.stack.enter_context(patch.object(governance.service, "_scoped", side_effect=self.read))
        self.stack.enter_context(patch.object(sources, "resolve", side_effect=self.resolve))
        self.stack.enter_context(patch.object(governance, "_binding_rows", return_value=[]))
        self.stack.enter_context(patch.object(sources, "pursuit_plan", return_value=None))
        self.stack.enter_context(patch.object(sources, "verify_native_rates", return_value=[]))
        self.stack.enter_context(patch.object(governance.units, "verify_manifest_access"))
        self.stack.enter_context(patch.object(governance.units, "currency_policy", return_value={"currency_exponent": 2}))

    def read(self, kind, name, company, project, actor, **kwargs):
        self.reads.append((kind, kwargs))
        return deepcopy(self.records[kind])

    def resolve(self, company, project, refs, actor, **kwargs):
        self.resolved.append((deepcopy(refs), actor))
        if not self.allowed or actor.user != self.actor.user:
            raise DomainError("not_found", "Explicit fixture source authority revoked", 404)
        return [citation() for ref in refs]

    def facts(self, actor=None):
        return governance._facts(actor=actor or self.actor, company=self.company, project=self.project, subject_id="revision", lock=False)

    def historical(self, manifest, actor=None):
        return governance._historical(actor=actor or self.actor, company=self.company, project=self.project, subject_id="revision", manifest=manifest, lock=False)

    def test_each_fresh_and_historical_builder_verifies_its_own_complete_batch(self):
        revision, snapshot, facts = self.facts()
        manifest = {"effect": {"facts": facts}}
        self.assertEqual(self.historical(manifest), revision)
        self.assertEqual(self.facts()[2], facts)
        self.assertEqual(len(self.resolved), 3)
        self.assertTrue(all(len(refs) == 1 for refs, _ in self.resolved))
        for kind, kwargs in self.reads:
            if kind in {"revision", "snapshot", "rate"}:
                self.assertIs(kwargs["verify"], False)
                self.assertIs(kwargs["verify_links"], False)
            else:
                self.assertEqual(kind, "estimate")
                self.assertNotIn("verify", kwargs)
        self.assertEqual(facts["pinned_records"], [{"kind": "rate", "id": "rate", "digest": digest(self.records["rate"])}])
        self.assertEqual(facts["revision"]["digest"], digest(revision))
        self.assertEqual(facts["snapshot"]["digest"], digest(snapshot))

    def test_current_authority_is_not_reused_by_later_builder_or_alias(self):
        facts = self.facts()[2]
        self.allowed = False
        for callback in (self.facts, lambda: self.historical({"effect": {"facts": facts}})):
            with self.assertRaises(DomainError) as caught:
                callback()
            self.assertEqual(caught.exception.code, "not_found")
        self.allowed = True
        alias = SimpleNamespace(user="fixture-alias", person_id=self.actor.person_id)
        with self.assertRaises(DomainError) as caught:
            self.facts(alias)
        self.assertEqual(caught.exception.code, "not_found")

    def test_pinned_definition_and_historical_record_digests_stay_required(self):
        facts = self.facts()[2]
        self.records["rate"]["rate"]["rate_amount"] = "different-fixture-value"
        with self.assertRaises(DomainError) as caught:
            self.facts()
        self.assertEqual(caught.exception.code, "estimate_integrity")
        with self.assertRaises(DomainError) as caught:
            self.historical({"effect": {"facts": facts}})
        self.assertEqual(caught.exception.code, "approval_integrity")

    def test_current_head_remains_fresh_after_the_batch(self):
        self.facts()
        self.records["estimate"]["current_revision"] = "successor"
        with self.assertRaises(DomainError) as caught:
            self.facts()
        self.assertEqual(caught.exception.code, "stale_estimate")
        self.allowed = False
        with self.assertRaises(DomainError) as caught:
            self.facts()
        self.assertEqual(caught.exception.code, "not_found")

    def test_no_general_line_or_acceptance_deferral(self):
        for kind in ("line", "acceptance", "estimate"):
            with self.assertRaises(DomainError) as caught:
                governance._citation_record(kind, "fixture-id", self.company, self.project, self.actor, [], lock=False)
            self.assertEqual(caught.exception.code, "approval_integrity")
        self.assertEqual(self.reads, [])


class MutationCitationPreflightTests(unittest.TestCase):
    def setUp(self):
        self.actor = SimpleNamespace(user="fixture-author", person_id="fixture-person")
        self.company = "Fixture Company"
        self.row = citation()
        self.reference = {name: self.row[name] for name in ("revision_id", "page", "excerpt_sha256", "source_sha256")}
        self.node = {"generated": True, "document_id": self.row["document_id"], "revision_id": self.row["revision_id"], "input_digest": "c" * 64}
        self.trace = []
        self.stack = ExitStack(); self.addCleanup(self.stack.close)
        self.stack.enter_context(scopes.activate("Company", self.company, None))
        self.stack.enter_context(patch.object(sources, "require_project"))
        db = SimpleNamespace(get_value=lambda *a, **kw: SimpleNamespace(company=self.company, project=None, scope_type="Company"))
        self.stack.enter_context(patch.object(sources.frappe, "db", db))
        self.stack.enter_context(patch.object(sources, "GENERATED_INPUTS_QUALIFIED", True))
        self.preflight = self.stack.enter_context(patch.object(provenance, "mutation_source_identity", side_effect=self.identity))
        self.stack.enter_context(patch("cipher_aec.estimating.lockplan.admitted", return_value=True))
        self.canonical = self.stack.enter_context(patch("cipher_aec.documents.service.get_company_citation", side_effect=self.citation))

    def identity(self, company, revision, actor):
        self.assertEqual((company, revision), (self.company, self.row["revision_id"]))
        self.assertIs(actor, self.actor)
        self.trace.append("node-metadata")
        return self.node

    def citation(self, company, revision, page, **kwargs):
        self.assertIs(kwargs["actor"], self.actor)
        self.assertTrue(kwargs["lock"])
        self.trace.append("canonical-rights-and-bytes")
        return self.row

    def resolve(self):
        return sources.resolve(self.company, None, [self.reference], self.actor, lock=True)

    def test_metadata_is_immediately_followed_by_canonical_rights_and_bytes(self):
        self.assertEqual(self.resolve(), [self.row])
        self.assertEqual(self.trace, ["node-metadata", "canonical-rights-and-bytes"])

    def test_node_preflight_does_not_substitute_for_complete_resource_authority(self):
        self.canonical.side_effect = DomainError("source_prelock_required", "Fixture missing producer-only UOM", 409)
        with self.assertRaises(DomainError) as caught:
            self.resolve()
        self.assertEqual(caught.exception.code, "source_prelock_required")
        self.assertEqual(self.preflight.call_count, 1)
        self.assertEqual(self.canonical.call_count, 1)

    def test_public_gate_stays_closed_even_with_admitted_node(self):
        with patch.object(sources, "GENERATED_INPUTS_QUALIFIED", False):
            with self.assertRaises(DomainError) as caught:
                self.resolve()
        self.assertEqual(caught.exception.code, "source_dependency_unqualified")
        self.canonical.assert_not_called()

    def test_raw_source_still_requires_the_canonical_reader(self):
        self.node.update(generated=False, input_digest=None)
        self.canonical.side_effect = DomainError("not_found", "Fixture raw original source unavailable", 404)
        with self.assertRaises(DomainError) as caught:
            self.resolve()
        self.assertEqual(caught.exception.code, "not_found")
        self.assertEqual(self.canonical.call_count, 1)

    def test_takeoff_source_keeps_canonical_source_reference_after_same_preflight(self):
        from cipher_aec.takeoff import service as takeoff
        source = {name: self.row[name] for name in ("revision_id", "page", "source_sha256")}
        def reference(company, revision, page, **kwargs):
            self.assertIs(kwargs["actor"], self.actor)
            self.assertTrue(kwargs["lock"])
            self.trace.append("canonical-drawing-rights-and-bytes")
            return {**self.node, "document_id": self.row["document_id"], "revision_id": revision, "source_sha256": source["source_sha256"], "is_current": True, "mime_type": "application/pdf", "content": b"explicit fixture"}
        with patch("cipher_aec.documents.service.company_source_reference", side_effect=reference):
            value, content = takeoff._source(self.company, None, source, self.actor, lock=True, new_use=True, calibrated=True)
        self.assertEqual(content, b"explicit fixture")
        self.assertEqual(self.trace, ["node-metadata", "canonical-drawing-rights-and-bytes"])


if __name__ == "__main__":
    unittest.main()

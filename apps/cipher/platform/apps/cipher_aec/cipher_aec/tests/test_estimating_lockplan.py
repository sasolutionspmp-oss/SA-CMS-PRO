"""Explicit fixture-only union contracts; no native or provider qualification."""
from copy import deepcopy
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from cipher_aec.api.errors import DomainError
from cipher_aec.estimating import lockplan, scopes
from cipher_aec.documents import provenance
from cipher_aec.commercial.sources import merge


class CompleteSourceUnionTests(unittest.TestCase):
    def setUp(self):
        self.actor = SimpleNamespace(user="explicit-author", person_id="explicit-person")
        self.alias = SimpleNamespace(user="explicit-alias", person_id="explicit-person")
        self.company = "Explicit source-union fixture"
        self.plan = {"unit_ids": ["unit-b", "unit-a"], "currencies": ["USD", "EUR"],
            "native_refs": [{"doctype": "Item", "name": "item"}, {"doctype": "Customer", "name": "party"}],
            "generated_sources": [{"document_id": "output", "input_digest": "f" * 64}]}
        self.trace = []
        self.stack = __import__("contextlib").ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(scopes.activate("Company", self.company, None))
        self.stack.enter_context(patch("cipher_aec.estimating.units.qualified", side_effect=self.unit))
        self.stack.enter_context(patch("cipher_aec.commercial.native.require_native", side_effect=self.native))

    def unit(self, name, **kwargs):
        self.assertIs(kwargs["actor"], self.actor)
        self.assertTrue(kwargs["lock"] and kwargs["allow_disabled"])
        self.trace.append(("UOM", name))

    def native(self, kind, name, actor, **kwargs):
        self.assertIs(actor, self.actor)
        self.assertTrue(kwargs["lock"])
        self.trace.append((kind, name))

    def denied(self, callback, code="source_prelock_required"):
        with self.assertRaises(DomainError) as caught:
            callback()
        self.assertEqual(caught.exception.code, code)

    def enter(self, plan, actor=None):
        with lockplan.prepared(plan, actor or self.actor, self.company):
            pass

    def test_complete_union_sorted_and_nested_subset_does_not_relock(self):
        with lockplan.prepared(self.plan, self.actor, self.company):
            self.assertTrue(lockplan.admitted(self.plan, self.actor, self.company))
            self.enter({"unit_ids": ["unit-a"]})
            self.assertEqual(len(self.trace), 6)
        self.assertEqual(self.trace, [("UOM", "unit-a"), ("UOM", "unit-b"), ("Currency", "EUR"),
            ("Currency", "USD"), ("Customer", "party"), ("Item", "item")])
        self.assertFalse(lockplan.admitted(self.plan, self.actor, self.company))
        self.assertFalse(provenance.has_prelocked())

    def test_same_person_wrong_user_and_missing_node_digest_cannot_reuse_plan(self):
        with lockplan.prepared(self.plan, self.actor, self.company):
            self.denied(lambda: self.enter(self.plan, self.alias))
            altered = deepcopy(self.plan)
            altered["generated_sources"][0]["input_digest"] = "e" * 64
            self.denied(lambda: self.enter(altered))
            self.denied(lambda: self.enter({"unit_ids": ["missing-unit"]}))
            self.assertFalse(lockplan.admitted(self.plan, self.actor, "Another Company"))

    def test_returned_plan_mutation_never_expands_admission_and_exception_resets(self):
        with self.assertRaisesRegex(RuntimeError, "synthetic failure"):
            with lockplan.prepared(self.plan, self.actor, self.company) as exposed:
                exposed["unit_ids"].append("injected")
                self.plan["native_refs"].append({"doctype": "Item", "name": "injected"})
                self.assertFalse(lockplan.admitted({"unit_ids": ["injected"]}, self.actor, self.company))
                self.assertFalse(lockplan.admitted(self.plan, self.actor, self.company))
                raise RuntimeError("synthetic failure")
        self.assertFalse(provenance.has_prelocked())
        self.assertFalse(lockplan.active_for(self.actor, self.company))

    def test_complete_external_admission_adopted_without_acquiring_masters(self):
        with provenance.prelocked(merge(self.plan), self.actor, self.company):
            self.enter(self.plan)
        self.assertEqual(self.trace, [])

    def test_incomplete_or_wrong_actor_external_admission_refuses_before_locking(self):
        for held, actor in (({"unit_ids": ["unit-a"]}, self.actor), (self.plan, self.alias)):
            with provenance.prelocked(merge(held), actor, self.company):
                self.denied(lambda: self.enter(self.plan))
        self.assertEqual(self.trace, [])

    def test_aggregate_shared_dag_deduplicates_and_129_unique_nodes_refused(self):
        node = {"document_id": "shared", "input_digest": "a" * 64}
        self.assertEqual(len(merge({"generated_sources": [node]}, {"generated_sources": [node]})["generated_sources"]), 1)
        branches = [{"generated_sources": [{"document_id": str(i), "input_digest": "a" * 64}]} for i in range(129)]
        self.denied(lambda: merge(*branches), "source_limit")

    def test_effect_callback_retains_admission_without_a_public_lock_parameter(self):
        @lockplan.approval_union("takeoff")
        def apply_verification(*, actor, company, project, manifest):
            self.assertTrue(lockplan.active_for(actor, company))
            lockplan.require_resources(self.plan, actor, company)
            return "controller-insert-within-admission"
        with patch.object(scopes, "require"), patch.object(lockplan.Discovery, "record"), patch.object(lockplan.Discovery, "finish", return_value=merge(self.plan)):
            result = apply_verification(actor=self.actor, company=self.company, project=None, manifest={"effect": {"calibration_id": "explicit-calibration"}})
        self.assertEqual(result, "controller-insert-within-admission")
        self.assertFalse(lockplan.active_for(self.actor, self.company))

    def test_receipt_plans_originals_while_pending_rebuild_plans_current_union(self):
        @lockplan.approval_union("estimate")
        def authorize_subject(**kwargs):
            return kwargs["phase"]
        with patch.object(scopes, "require"), patch.object(lockplan, "revision_plan", return_value=merge(self.plan)) as discover:
            for phase, current in (("receipt", False), ("baseline", False), ("read", True), ("review", True), ("execute", True)):
                authorize_subject(actor=self.actor, company=self.company, project=None, subject_id="original", phase=phase, manifest={}, lock=True)
                self.assertIs(discover.call_args.kwargs["current_bindings"], current)

    def test_nested_callback_skips_discovery_but_runs_its_current_authorization(self):
        visits = []
        @lockplan.approval_union("estimate")
        def authorize_subject(**kwargs):
            visits.append(kwargs["phase"])
            lockplan.require_resources(self.plan, kwargs["actor"], kwargs["company"])
        with patch.object(lockplan, "revision_plan") as discovery:
            with lockplan.prepared(self.plan, self.actor, self.company):
                authorize_subject(actor=self.actor, company=self.company, project=None, subject_id="original", phase="execute", lock=True)
        discovery.assert_not_called()
        self.assertEqual(visits, ["execute"])

    def test_nested_callback_cannot_reuse_another_identitys_union(self):
        visits = []
        @lockplan.approval_union("estimate")
        def authorize_subject(**kwargs):
            visits.append(kwargs["phase"])
        with patch.object(scopes, "require"), patch.object(lockplan, "revision_plan", return_value=merge(self.plan)) as discovery:
            with lockplan.prepared(self.plan, self.actor, self.company):
                self.denied(lambda: authorize_subject(actor=self.alias, company=self.company, project=None, subject_id="original", phase="execute", lock=True))
        discovery.assert_called_once()
        self.assertEqual(visits, [])

    def test_generated_gate_stays_closed_and_admission_is_required_when_enabled(self):
        from cipher_aec.estimating import sources
        node = self.plan["generated_sources"][0]
        source = {"generated": True, "document_id": node["document_id"], "revision_id": "revision", "input_digest": node["input_digest"]}
        with patch.object(provenance, "mutation_source_identity", return_value=source):
            with patch.object(sources, "GENERATED_INPUTS_QUALIFIED", False):
                with lockplan.prepared(self.plan, self.actor, self.company):
                    self.denied(lambda: sources.require_raw_mutation_source(self.company, "revision", self.actor), "source_dependency_unqualified")
            with patch.object(sources, "GENERATED_INPUTS_QUALIFIED", True):
                self.denied(lambda: sources.require_raw_mutation_source(self.company, "revision", self.actor), "source_dependency_unqualified")
                with lockplan.prepared(self.plan, self.actor, self.company):
                    sources.require_raw_mutation_source(self.company, "revision", self.actor)
                    self.denied(lambda: sources.require_raw_mutation_source(self.company, "revision", self.alias), "source_dependency_unqualified")

    def test_metadata_discovery_merges_all_citations_before_any_acquisition(self):
        discovery = lockplan.Discovery(self.company, self.actor)
        discovery.units.add("outer-unit")
        discovery.currency("EUR")
        discovery.citations([{"revision_id": "first"}, {"revision_id": "second"}])
        shared = {"unit_ids": ["producer-unit"], "currencies": ["USD"],
            "native_refs": [{"doctype": "Quotation", "name": "original-draft"}],
            "generated_sources": [{"document_id": "shared-output", "input_digest": "b" * 64}]}
        with patch.object(provenance, "source_plan", return_value=shared) as source_plan:
            plan = discovery.finish()
        self.assertEqual(source_plan.call_count, 2)
        self.assertEqual(plan["currencies"], ["EUR", "USD"])
        self.assertEqual(plan["unit_ids"], ["outer-unit", "producer-unit"])
        self.assertEqual(len(plan["generated_sources"]), 1)
        self.assertEqual(self.trace, [])


class ExactBindingQuantityTests(unittest.TestCase):
    def test_equivalent_text_binds_without_rewriting_quantity(self):
        from cipher_aec.takeoff import service
        measured = {"result": {"quantity": {"amount": "200.000000", "unit_id": "same-unit", "precision": 6}}, "definition": {"waste_fraction": "0"}}
        line = {"authored": {"quantity": {"amount": "200", "unit_id": "same-unit", "precision": 6}}, "calculated": {"components": []}}
        original = deepcopy((measured, line))
        with patch.object(service, "_read", return_value=measured), patch.object(service.estimates, "_scoped", return_value=line):
            self.assertEqual(service._binding_basis("C", "P", "M", "L", "net-quantity-v1", object()), (measured, line))
        self.assertEqual((measured, line), original)

    def test_different_value_precision_or_unit_refused(self):
        from cipher_aec.takeoff import service
        measured = {"result": {"quantity": {"amount": "200.000000", "unit_id": "same-unit", "precision": 6}}, "definition": {"waste_fraction": "0"}}
        for change in ({"amount": "200.000001"}, {"precision": 5}, {"unit_id": "different-unit"}):
            line = {"authored": {"quantity": {"amount": "200", "unit_id": "same-unit", "precision": 6, **change}}, "calculated": {"components": []}}
            with patch.object(service, "_read", return_value=measured), patch.object(service.estimates, "_scoped", return_value=line):
                with self.assertRaises(DomainError) as caught:
                    service._binding_basis("C", "P", "M", "L", "net-quantity-v1", object())
                self.assertEqual(caught.exception.code, "quantity_mismatch")


if __name__ == "__main__":
    unittest.main()

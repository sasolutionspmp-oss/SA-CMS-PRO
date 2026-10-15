"""Independent exact-response and immutable-source proof checks, scratch only."""
import copy
import unittest
from unittest.mock import patch

from apps.cipher.ap_contract import APRefusal
from apps.cipher.tests import test_commercial_actions as _harness_module


class CommercialActionDomainReview(unittest.TestCase):
    def setUp(self):
        self.h = _harness_module.CommercialActionTests("runTest")
        self.h.setUp()
        self.addCleanup(self.h.doCleanups)

    def test_effect_result_rejects_float_alias_for_exact_zero_labels(self):
        args, kwargs = self.h.prepared(self.h.person, "estimate.create", self.h.r["project_id"], self.h.input())
        apply = self.h.runner._apply
        def aliased_result(*values):
            result, source = apply(*values)
            result["providerCallsDelta"] = 0.0
            return result, source
        before = self.h.state()
        with patch.object(self.h.runner, "_apply", side_effect=aliased_result), self.assertRaises(APRefusal):
            self.h.runner.run(*args, **kwargs)
        self.assertEqual(before, self.h.state())

    def test_receipt_source_rejects_float_alias_for_original_engine_line_number(self):
        args, kwargs = self.h.prepared(self.h.person, "estimate.create", self.h.r["project_id"], self.h.input())
        apply = self.h.runner._apply
        def aliased_source(*values):
            result, source = apply(*values)
            source = copy.deepcopy(source)
            source["lines"][0]["engine_line"]["line_no"] = 1.0
            return result, source
        before = self.h.state()
        with patch.object(self.h.runner, "_apply", side_effect=aliased_source), self.assertRaises(APRefusal):
            self.h.runner.run(*args, **kwargs)
        self.assertEqual(before, self.h.state())


    def test_original_grant_and_acceptance_events_require_exact_integer_reference(self):
        # SQLite admits 53.0 for seq=53. The receipt must retain the actual
        # integer audit identity and its exact shape, not a coercible alias.
        for action in ("estimate.accept", "estimate.apply"):
            for mutation in ("float_sequence", "extra_field"):
                with self.subTest(action=action, mutation=mutation):
                    h = _harness_module.CommercialActionTests("runTest")
                    h.setUp()
                    try:
                        created, _ = h.act(h.person, "estimate.create", h.r["project_id"], h.input())
                        requested, _ = h.act(h.person, "estimate.request", created["result"]["estimateId"])
                        approval = requested["result"]["approvalId"]
                        if action == "estimate.apply":
                            h.act(h.reviewer, "estimate.accept", approval)
                        actor = h.reviewer if action == "estimate.accept" else h.person
                        args, kwargs = h.prepared(actor, action, approval)
                        apply = h.runner._apply
                        def altered_reference(*values):
                            result, source = apply(*values)
                            source = copy.deepcopy(source)
                            if mutation == "float_sequence":
                                source["event"]["auditSeq"] = float(source["event"]["auditSeq"])
                            else:
                                source["event"]["unprovedAttribution"] = "pretend-original-fact"
                            return result, source
                        before = h.state()
                        with patch.object(h.runner, "_apply", side_effect=altered_reference), self.assertRaises(APRefusal):
                            h.runner.run(*args, **kwargs)
                        self.assertEqual(before, h.state())
                        completed = h.runner.run(*args, **kwargs)
                        self.assertEqual(completed["result"]["status"], "granted" if action == "estimate.accept" else "approved")
                        h.replay(completed, (args, kwargs))
                    finally:
                        h.doCleanups()


if __name__ == "__main__":
    unittest.main()

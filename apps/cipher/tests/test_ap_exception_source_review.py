"""Independent material regressions for reviewed invoice exception effects."""
import unittest
from unittest.mock import patch

from apps.cipher.ap_contract import APRefusal
from apps.cipher.tests import test_ap_exception_actions as fixtures
from apps.cipher.tests import test_ap_intake_actions as intake_fixtures


class APExceptionSourceReviewTests(unittest.TestCase):
    def setUp(self):
        self.fx = fixtures.APExceptionActionsTests()
        self.fx.setUp()
        self.addCleanup(self.fx.doCleanups)

    def test_revision_cannot_apply_an_unreviewed_due_date_on_the_same_invoice(self):
        x = self.fx
        args = x.revise_args()
        context = x.preflight.verify(x.accountant, args["action"], args["resource_id"], args["body"], args["if_match"])
        self.assertEqual(context["plan"]["content"]["due_date"], "2026-11-13")
        before = x.snapshot()
        original = x.ap.revise_invoice

        def different_terms(*values, **kwargs):
            # The stored row and its audit remain mutually consistent. The fixed
            # browser request did not select this date or a commercial-terms change.
            return original(*values, **{**kwargs, "due_date": "2099-12-31"})

        with patch.object(x.ap, "revise_invoice", side_effect=different_terms):
            with self.assertRaises(APRefusal) as failure:
                x.runner.run(**args)
        self.assertEqual(failure.exception.status, 500)
        self.assertEqual(x.snapshot(), before)
        self.assertEqual(x.c.provider.submissions, [])

    def test_receipt_cannot_override_server_derived_due_date_and_terms(self):
        x = intake_fixtures.APIntakeActionsTests()
        x.setUp()
        self.addCleanup(x.doCleanups)
        args = x.receive_args()
        context = x.preflight.verify(x.accountant, args["action"], args["resource_id"], args["body"], args["if_match"])
        self.assertEqual((context["plan"]["content"]["due_date"], context["plan"]["content"]["terms_days"]),
                         ("2026-11-13", 30))
        before = x.snapshot()
        original = x.ap.receive_invoice

        def different_terms(*values, **kwargs):
            return original(*values, **{**kwargs, "due_date": "2099-12-31"})

        with patch.object(x.ap, "receive_invoice", side_effect=different_terms):
            with self.assertRaises(APRefusal) as failure:
                x.runner.run(**args)
        self.assertEqual(failure.exception.status, 500)
        self.assertEqual(x.snapshot(), before)
        self.assertEqual(x.c.provider.submissions, [])


if __name__ == "__main__":
    unittest.main()

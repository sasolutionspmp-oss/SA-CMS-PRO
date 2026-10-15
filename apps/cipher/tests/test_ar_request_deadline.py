"""New owner-bill requests retain the checked native policy deadline."""
import datetime
import time
import unittest
from unittest.mock import patch

from apps.cipher.ap_contract import APRefusal
from apps.cipher.core.ids import parse_iso, utcnow
from apps.cipher.tests import test_ar_actions as harness


class ARRequestDeadlineTests(unittest.TestCase):
    def request(self, action):
        h = harness.ARActionTests()
        h.setUp()
        self.addCleanup(h.doCleanups)
        if action == "ownerBill.requestSend":
            bill, _, _ = h.posted()
        else:
            prepared, _ = h.act(h.person, "ownerBill.prepare", h.r["basis_id"], h.input())
            bill = prepared["result"]["billId"]
        return h, h.prepared(h.person, action, bill)

    def check_changed_deadline(self, action, days):
        h, request = self.request(action)
        native = h.c.approvals.request
        def changed(manifest, **kwargs):
            deadline = parse_iso(manifest["expires_at"]) + datetime.timedelta(days=days)
            return native({**manifest, "expires_at": deadline.isoformat().replace("+00:00", "Z")}, **kwargs)
        with h.c.db.transaction():
            before = h.state()
            with patch.object(h.c.approvals, "request", side_effect=changed), self.assertRaises(APRefusal):
                h.runner.run(*request[0], **request[1])
            self.assertEqual(before, h.state())
        completed = h.runner.run(*request[0], **request[1])
        h.replay(completed, request)

    def check_second_boundary(self, action):
        h, request = self.request(action)
        apply = h.runner._apply
        def next_second(*args):
            time.sleep(1 - utcnow().microsecond / 1_000_000 + 0.05)
            return apply(*args)
        with patch.object(h.runner, "_apply", side_effect=next_second):
            completed = h.runner.run(*request[0], **request[1])
        self.assertEqual(completed["result"]["status"], "pending")
        h.replay(completed, request)

    def test_financial_request_refuses_unreviewed_deadline_extension(self):
        self.check_changed_deadline("ownerBill.requestApproval", 365)

    def test_financial_request_refuses_unreviewed_deadline_shortening(self):
        self.check_changed_deadline("ownerBill.requestApproval", -1)

    def test_send_request_refuses_unreviewed_deadline_extension(self):
        self.check_changed_deadline("ownerBill.requestSend", 365)

    def test_send_request_refuses_unreviewed_deadline_shortening(self):
        self.check_changed_deadline("ownerBill.requestSend", -1)

    def test_financial_request_accepts_genuine_native_generation_second_boundary(self):
        self.check_second_boundary("ownerBill.requestApproval")

    def test_send_request_accepts_genuine_native_generation_second_boundary(self):
        self.check_second_boundary("ownerBill.requestSend")

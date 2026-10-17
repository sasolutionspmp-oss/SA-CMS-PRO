"""Historical packet rights do not depend on current action/presentation state."""
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from cipher_aec.api.errors import DomainError
from cipher_aec.governance import approvals, history_access


class HistoryPacketAuthorizationTests(unittest.TestCase):
    def setUp(self):
        self.actor=SimpleNamespace(user="author@cipher.example",person_id="person")
        self.packet=SimpleNamespace(action="estimate.accept.v1")
        self.patches=[patch.object(approvals,"_scope"),patch.object(approvals,"_load",return_value=self.packet),
            patch.object(approvals.domain_approvals,"authorize"),
            patch.object(approvals,"present",side_effect=AssertionError("History must not build a public packet DTO")),
            patch.object(approvals,"_state",side_effect=AssertionError("History must not reconstruct current eligibility"))]
        self.mocks=[p.start() for p in self.patches]
        self.addCleanup(lambda:[p.stop() for p in reversed(self.patches)])
        self.event=SimpleNamespace(subject_type="Cipher Approval Packet",subject_id="packet-exact")

    def test_literal_reader_authorizes_exact_stored_manifest_with_passed_actor(self):
        self.assertTrue(history_access.readable(self.event,self.actor,"Company A",None))
        self.mocks[0].assert_called_once_with("Company A",None,"Company",actor=self.actor)
        self.mocks[1].assert_called_once_with("Company A",None,"packet-exact",scope_type="Company")
        self.mocks[2].assert_called_once_with(self.packet,self.actor,phase="read",lock=False)
        self.mocks[3].assert_not_called();self.mocks[4].assert_not_called()

    def test_revoked_original_source_hides_history_event(self):
        self.mocks[2].side_effect=DomainError("capability_denied","Original source right revoked",403)
        self.assertFalse(history_access.readable(self.event,self.actor,"Company A",None))

    def test_corrupt_packet_or_original_manifest_aborts_history(self):
        for target in (self.mocks[1],self.mocks[2]):
            with self.subTest(target=target):
                target.side_effect=DomainError("approval_integrity","Stored manifest cannot be verified",409)
                with self.assertRaises(DomainError) as error:history_access.readable(self.event,self.actor,"Company A",None)
                self.assertEqual(error.exception.code,"approval_integrity")
                target.side_effect=None

    def test_project_status_history_preserves_project_scope_without_domain_callback(self):
        self.packet.action=approvals.ACTION
        self.assertTrue(history_access.readable(self.event,self.actor,"Company A","real-project"))
        self.mocks[0].assert_called_once_with("Company A","real-project","Project",actor=self.actor)
        self.mocks[2].assert_not_called()

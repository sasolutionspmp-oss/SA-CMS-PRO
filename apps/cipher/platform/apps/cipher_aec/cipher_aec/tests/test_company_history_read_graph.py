"""Explicit Company read-root lifetime and signed cursor wiring; no native writes."""
from contextlib import contextmanager
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from cipher_aec.api.errors import DomainError
from cipher_aec.api.paging import encode_cursor
from cipher_aec.documents import provenance
from cipher_aec.governance import company, history_listing


class CompanyHistoryReadGraphTests(unittest.TestCase):
    def setUp(self):
        self.actor=SimpleNamespace(user="author@cipher.example",person_id="PERSON-EXACT")
        self.events=[];self.active=False
        self.scope={"scope_type":"Company","company":"Company A","user":self.actor.user,"person":self.actor.person_id,
            "collection":"company_history","authority":"current-authority"}
        self.patches=[patch.object(company,"current_actor",return_value=self.actor),
            patch.object(company,"require_company",side_effect=lambda *a,**k:self.events.append("authorized-scope")),
            patch.object(company,"company_authority_fingerprint",return_value="current-authority"),
            patch.object(company,"signing_secret",return_value="private-test-signing-key"),
            patch.object(provenance,"read_graph_eligible",return_value=True),
            patch.object(provenance,"read_graph",side_effect=self.graph),
            patch.object(history_listing,"list_visible",side_effect=self.listing)]
        self.started=[item.start() for item in self.patches]
        self.addCleanup(lambda:[item.stop() for item in reversed(self.patches)])
        self.reader=self.started[-1];self.graph_mock=self.started[-2];self.eligible=self.started[-3]

    @contextmanager
    def graph(self,actor,scope_company):
        self.assertEqual(self.events,["authorized-scope"])
        self.assertIs(actor,self.actor);self.assertEqual(scope_company,"Company A")
        self.events.append("read-root-enter");self.active=True
        try:yield
        finally:self.active=False;self.events.append("read-root-exit")

    def listing(self,**kwargs):
        self.events.append("listing")
        return {"active_read_root":self.active,"arguments":kwargs}

    def test_one_root_wraps_whole_scan_after_current_scope_and_signed_cursor(self):
        last=["2026-10-15 12:34:56.123456","event-tie"]
        cursor=encode_cursor(secret="private-test-signing-key",scope=self.scope,last=last)
        result=company.history("Company A",limit=200,cursor=cursor,count_mode="exact")
        self.assertTrue(result["active_read_root"])
        self.assertEqual(result["arguments"]["scope"],self.scope)
        self.assertEqual(result["arguments"]["last"],last)
        self.assertEqual(result["arguments"]["scope_type"],"Company")
        self.assertIsNone(result["arguments"]["project"])
        self.assertEqual(self.events,["authorized-scope","read-root-enter","listing","read-root-exit"])
        self.reader.assert_called_once();self.graph_mock.assert_called_once_with(self.actor,"Company A")
        self.eligible.assert_called_once_with(self.actor,"Company A")

    def test_ineligible_read_after_write_uses_original_slow_reader(self):
        self.eligible.return_value=False
        result=company.history("Company A",count_mode="exact")
        self.assertFalse(result["active_read_root"])
        self.graph_mock.assert_not_called();self.reader.assert_called_once()
        self.assertEqual(self.events,["authorized-scope","listing"])

    def test_denied_scope_never_enters_graph_or_subject_scan(self):
        self.started[1].side_effect=DomainError("not_found","Unavailable Company",404)
        with self.assertRaises(DomainError):company.history("Company A")
        self.graph_mock.assert_not_called();self.eligible.assert_not_called();self.reader.assert_not_called()

    def test_wrong_company_actor_or_authority_cursor_refuses_before_graph(self):
        for changed in ({"company":"Company B"},{"user":"alias@cipher.example"},{"person":"OTHER-PERSON"},{"authority":"old-authority"}):
            with self.subTest(changed=changed):
                cursor=encode_cursor(secret="private-test-signing-key",scope={**self.scope,**changed},last=["2026-10-15 12:34:56","event"])
                with self.assertRaises(DomainError) as error:company.history("Company A",cursor=cursor)
                self.assertEqual(error.exception.code,"invalid_cursor")
        self.graph_mock.assert_not_called();self.eligible.assert_not_called();self.reader.assert_not_called()

    def test_subject_integrity_failure_closes_read_root_before_propagating(self):
        def fail(**kwargs):
            self.assertTrue(self.active)
            raise DomainError("source_integrity","Original source is inconsistent",409)
        self.reader.side_effect=fail
        with self.assertRaises(DomainError) as error:company.history("Company A",count_mode="exact")
        self.assertEqual(error.exception.code,"source_integrity")
        self.assertFalse(self.active)
        self.assertEqual(self.events,["authorized-scope","read-root-enter","read-root-exit"])

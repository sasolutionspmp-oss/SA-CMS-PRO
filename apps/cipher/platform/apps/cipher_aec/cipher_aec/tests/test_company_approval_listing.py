"""Company inbox SQL/privacy and explicit graph orchestration; no native writes."""
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
import sqlite3
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from cipher_aec.api.contracts import digest
from cipher_aec.api.errors import DomainError
from cipher_aec.api.paging import encode_cursor
from cipher_aec.documents import provenance
from cipher_aec.governance import approval_listing as listing, approvals


class CompanyApprovalListingTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:"); self.db.row_factory = sqlite3.Row
        self.addCleanup(self.db.close)
        self.db.execute("CREATE TABLE `tabCipher Approval Packet` (name TEXT,creation TEXT,company TEXT,scope_type TEXT,project TEXT,action TEXT)")
        self.calls = Counter(); self.denied = set(); self.corrupt = set()
        def sql(query, parameters, **kwargs):
            return [SimpleNamespace(**dict(row)) for row in self.db.execute(query.replace("%s", "?"), parameters).fetchall()]
        def present(packet, record, actor):
            self.calls[packet.name] += 1
            if packet.name in self.denied: raise DomainError("not_found", "Unavailable", 404)
            if packet.name in self.corrupt: raise DomainError("approval_integrity", "Invalid original", 409)
            return {"id": packet.name}
        self.patches = [patch.object(listing, "frappe", SimpleNamespace(db=SimpleNamespace(sql=Mock(side_effect=sql)))), patch.object(approvals, "_load", side_effect=lambda c,p,n,**kw:SimpleNamespace(name=n)),
            patch.object(approvals, "present", side_effect=present), patch.object(listing, "CHUNK_SIZE", 2),
            patch.object(listing, "page_result", side_effect=lambda items,**kw:{"items":items,**kw})]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)

    def row(self, name, creation="2026-10-15 12:00:00.123456", company="Company A", scope="Company", project=None, action="proposal.issue.v1"):
        self.db.execute("INSERT INTO `tabCipher Approval Packet` VALUES (?,?,?,?,?,?)", (name,creation,company,scope,project,action))

    def page(self, limit=2, last=None, count_mode="exact"):
        return listing.list_company_packets(company="Company A", actor=object(), record=object(), allowed_actions=["proposal.issue.v1"],
            scope={"signed":"context"}, limit=limit,last=last,count_mode=count_mode)

    def test_exact_count_and_page_present_each_candidate_once(self):
        for n in "abcde": self.row(n)
        self.denied={"d"}; r=self.page()
        self.assertEqual(r["items"],[{"id":"e"},{"id":"c"}]);self.assertEqual(r["total"],4)
        self.assertTrue(r["has_more"]);self.assertEqual(self.calls,Counter({n:1 for n in "abcde"}))

    def test_exact_cursor_uses_sql_precision_ties_and_global_private_count(self):
        for n in "abcde":self.row(n)
        self.row("newer","2026-10-15 12:00:00.123457");self.row("older","2026-10-15 12:00:00.123455")
        self.denied={"b"};r=self.page(last=["2026-10-15 12:00:00.123456","d"])
        self.assertEqual(r["items"],[{"id":"c"},{"id":"a"}]);self.assertEqual(r["total"],6)
        self.assertTrue(r["has_more"]);self.assertTrue(all(v==1 for v in self.calls.values()))

    def test_none_seek_and_private_lookahead_stop_without_total(self):
        for n in "abcdefgh":self.row(n)
        self.denied={"f"};r=self.page(last=["2026-10-15 12:00:00.123456","h"],count_mode="none")
        self.assertEqual(r["items"],[{"id":"g"},{"id":"e"}]);self.assertIsNone(r["total"])
        self.assertEqual(set(self.calls),set("gfed"));self.assertTrue(r["has_more"])

    def test_exact_off_page_integrity_and_scan_overflow_abort(self):
        for n in "abcde":self.row(n)
        self.corrupt={"a"}
        with self.assertRaises(DomainError) as e:self.page(limit=1)
        self.assertEqual(e.exception.code,"approval_integrity")
        self.corrupt.clear();self.denied=set("abcde")
        with patch.object(listing,"MAX_SCAN",3),self.assertRaises(DomainError) as e:self.page(limit=1)
        self.assertEqual(e.exception.code,"authorization_scan_limit")

    def test_scope_action_and_null_project_inventory_is_exact(self):
        self.row("own");self.row("other",company="Company B");self.row("project",scope="Project",project="real")
        self.row("bad-null",project="real");self.row("unqualified",action="unregistered")
        r=self.page();self.assertEqual(r["items"],[{"id":"own"}]);self.assertEqual(r["total"],1)
        self.assertEqual(set(self.calls),{"own"})

    def test_current_denial_changes_next_request_count_and_cursor(self):
        for n in "abc":self.row(n)
        self.assertEqual(self.page()["total"],3)
        self.denied=set("abc");self.calls.clear();r=self.page()
        self.assertEqual(r["items"],[]);self.assertEqual(r["total"],0);self.assertIsNone(r["last"])
        self.assertFalse(r["has_more"]);self.assertEqual(self.calls,Counter({n:1 for n in "abc"}))


class CompanyApprovalReadRootTests(unittest.TestCase):
    def setUp(self):
        self.actor=SimpleNamespace(user="author@cipher.example",person_id="person")
        self.packet=SimpleNamespace(name="packet");self.active=False;self.events=[]
        self.scope={"selector":"company_approval_packets","count_mode":"exact","company":"Company A","person":"person","user":self.actor.user,"authority":"authority"}
        self.patches=[patch.object(approvals,"current_actor",return_value=self.actor),
            patch.object(approvals,"_scope",side_effect=lambda *a,**kw:self.events.append("scope") or object()),
            patch.object(approvals,"company_authority_fingerprint",return_value="authority"),
            patch.object(approvals,"signing_secret",return_value="secret"),
            patch.object(approvals,"_duties",return_value=[SimpleNamespace(ability="commercial.read")]),
            patch.object(approvals,"_load",side_effect=lambda *a,**kw:self.events.append("load") or self.packet),
            patch.object(provenance,"read_graph_eligible",return_value=True),patch.object(provenance,"read_graph",side_effect=self.graph),
            patch.object(listing,"list_company_packets",side_effect=lambda **kw:{"active":self.active,"last":kw["last"]}),
            patch.object(approvals,"present",side_effect=lambda *a,**kw:{"active":self.active})]
        self.mocks=[]
        for p in self.patches:
            self.mocks.append(p.start())
            self.addCleanup(p.stop)

    @contextmanager
    def graph(self,actor,company):
        self.assertIs(actor,self.actor);self.assertEqual(company,"Company A");self.events.append("enter");self.active=True
        try:yield
        finally:self.active=False;self.events.append("exit")

    def test_signed_cursor_scope_and_authority_precede_one_list_root(self):
        last=["2026-10-15 12:00:00.123456","p"]
        cursor=encode_cursor(secret="secret",scope=self.scope,last=last)
        r=approvals.list_packets("Company A",None,cursor=cursor,count_mode="exact",scope_type="Company")
        self.assertTrue(r["active"]);self.assertEqual(r["last"],last);self.assertEqual(self.events,["scope","enter","exit"])
        self.mocks[7].assert_called_once();self.mocks[8].assert_called_once()

    def test_wrong_cursor_denies_before_graph_or_listing(self):
        cursor=encode_cursor(secret="secret",scope={**self.scope,"person":"other"},last=["date","p"])
        with self.assertRaises(DomainError):approvals.list_packets("Company A",None,cursor=cursor,count_mode="exact",scope_type="Company")
        self.mocks[6].assert_not_called();self.mocks[7].assert_not_called();self.mocks[8].assert_not_called()

    def test_prior_write_fallback_keeps_uncached_list_and_exact_read(self):
        self.mocks[6].return_value=False
        self.assertFalse(approvals.list_packets("Company A",None,scope_type="Company")["active"])
        self.assertFalse(approvals.read_packet("Company A",None,"packet",scope_type="Company")["active"])
        self.mocks[7].assert_not_called()

    def test_exact_read_load_integrity_before_root_and_next_root_denial(self):
        self.assertTrue(approvals.read_packet("Company A",None,"packet",scope_type="Company")["active"])
        self.assertEqual(self.events,["scope","load","enter","exit"])
        self.mocks[9].side_effect=DomainError("not_found","Original source revoked",404)
        with self.assertRaises(DomainError):approvals.read_packet("Company A",None,"packet",scope_type="Company")
        self.assertFalse(self.active)
        self.mocks[5].side_effect=DomainError("approval_integrity","Corrupt stored packet",409)
        calls=self.mocks[7].call_count
        with self.assertRaises(DomainError):approvals.read_packet("Company A",None,"packet",scope_type="Company")
        self.assertEqual(self.mocks[7].call_count,calls)

    def test_project_read_keeps_original_lifetime_and_present_path(self):
        result=approvals.read_packet("Company A","real-project","packet")
        self.assertFalse(result["active"]);self.mocks[6].assert_not_called();self.mocks[7].assert_not_called()
        self.mocks[5].assert_called_once_with("Company A","real-project","packet",scope_type="Project")

    def test_project_list_keeps_existing_query_and_no_company_graph(self):
        with patch.object(approvals,"_page_scope",return_value={"project":"real-project"}),patch.object(approvals,"_query_page",return_value=[]) as query:
            result=approvals.list_packets("Company A","real-project")
        self.assertEqual(result["items"],[])
        self.assertEqual(query.call_args.kwargs["filters"]["project"],"real-project")
        self.mocks[6].assert_not_called();self.mocks[7].assert_not_called();self.mocks[8].assert_not_called()

    def test_invalid_existing_graph_refuses_before_scan(self):
        self.mocks[6].side_effect=DomainError("source_read_context_invalid","Read context changed",409)
        with self.assertRaises(DomainError) as error:approvals.list_packets("Company A",None,scope_type="Company")
        self.assertEqual(error.exception.code,"source_read_context_invalid")
        self.mocks[7].assert_not_called();self.mocks[8].assert_not_called()


class CompanyApprovalFreshStateTests(unittest.TestCase):
    def test_reused_original_authority_does_not_reuse_current_manifest_or_actions(self):
        actor=SimpleNamespace(user="author",person_id="requester")
        domain={"subject":{"doctype":"Cipher Proposal Revision","name":"revision","label":"Exact proposal"}}
        definition={"independent":True};outer={"domain":domain,"policy_hash":digest(definition)}
        packet=SimpleNamespace(action="proposal.issue.v1",name="packet",company="Company A",project=None,scope_type="Company",
            requester_person="requester",manifest_json=json.dumps(outer),policy_revision="policy",created_at="now",
            expires_at=(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat(),manifest_hash="hash",source_version="version",subject_id="revision",subject_type="Cipher Proposal Revision")
        decision=SimpleNamespace(name="decision",decision="Grant",actor_person="independent",decided_at="now",reason="Reviewed")
        policy=SimpleNamespace(name="policy",definition_json=json.dumps(definition))
        with patch.object(approvals.domain_approvals,"authorize",return_value=None) as original, \
            patch.object(approvals.domain_approvals,"current_manifest",side_effect=[domain,{**domain,"changed":True}]) as current, \
            patch.object(approvals,"_decisions",return_value=[decision]),patch.object(approvals,"_consumption",return_value=None), \
            patch.object(approvals,"_policy",return_value=policy),patch.object(approvals,"_duties",return_value=[SimpleNamespace(ability=a) for a in ("approval.execute","commercial.write")]), \
            patch.object(approvals,"_person",side_effect=lambda p:{"id":p,"display_name":p}),patch.object(approvals,"frappe",SimpleNamespace(db=SimpleNamespace(get_value=Mock(return_value="Policy")))):
            first=approvals.present(packet,object(),actor);second=approvals.present(packet,object(),actor)
        self.assertEqual(first["state"],"Granted");self.assertTrue(first["actions"]["can_execute"])
        self.assertEqual(second["state"],"Stale");self.assertFalse(second["actions"]["can_execute"])
        self.assertEqual(current.call_count,2);self.assertEqual(original.call_count,2)

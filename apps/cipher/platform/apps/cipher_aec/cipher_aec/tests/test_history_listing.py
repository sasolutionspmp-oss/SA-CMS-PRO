"""Executable keyset-query and authorization-count contract; no native writes."""
from collections import Counter
from types import SimpleNamespace
import sqlite3
import unittest
from unittest.mock import Mock, patch

from cipher_aec.api.errors import DomainError
from cipher_aec.governance import history_listing as listing


class HistoryListingTests(unittest.TestCase):
    def setUp(self):
        self.database=sqlite3.connect(":memory:")
        self.database.row_factory=sqlite3.Row
        self.addCleanup(self.database.close)
        self.database.execute("CREATE TABLE `tabCipher History Event` (name TEXT,creation TEXT,company TEXT,scope_type TEXT,project TEXT)")
        self.events={};self.calls=Counter();self.denied=set();self.corrupt=set()
        def sql(query,parameters,**kwargs):
            return [SimpleNamespace(**dict(row)) for row in self.database.execute(query.replace("%s","?"),parameters).fetchall()]
        def readable(event,*args):
            self.calls[event.name]+=1
            if event.name in self.corrupt:raise DomainError("history_integrity","Original source is inconsistent",409)
            return event.name not in self.denied
        self.patches=[patch.object(listing,"frappe",SimpleNamespace(db=SimpleNamespace(sql=Mock(side_effect=sql)),
            get_doc=Mock(side_effect=lambda doctype,name:self.events[name]))),
            patch.object(listing,"readable",side_effect=readable),
            patch.object(listing,"present_event",side_effect=lambda event:{"id":event.name}),
            patch.object(listing,"page_result",side_effect=lambda items,**kwargs:{"items":items,**kwargs}),
            patch.object(listing,"CHUNK_SIZE",2)]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)

    def row(self,name,creation="2026-10-15 12:00:00.123456",*,company="Company A",scope_type="Company",project=None):
        self.database.execute("INSERT INTO `tabCipher History Event` VALUES (?,?,?,?,?)",(name,creation,company,scope_type,project))
        self.events[name]=SimpleNamespace(name=name,creation=creation)

    def page(self,*,limit=2,last=None,count_mode="exact",project=None):
        return listing.list_visible(company="Company A",project=project,scope_type="Project" if project else "Company",
            actor=object(),scope={"scope":"signed-exact-context"},limit=limit,last=last,count_mode=count_mode)

    def test_exact_page_counts_and_authorizes_every_event_once(self):
        for name in ("a","b","c","d","e"):self.row(name)
        self.denied={"d"}
        result=self.page()
        self.assertEqual(result["items"],[{"id":"e"},{"id":"c"}])
        self.assertEqual(result["total"],4);self.assertTrue(result["has_more"])
        self.assertEqual(result["last"],["2026-10-15 12:00:00.123456","c"])
        self.assertEqual(self.calls,Counter({name:1 for name in "abcde"}))

    def test_exact_cursor_retains_sql_tie_order_and_global_visible_total(self):
        for name in ("a","b","c","d","e"):self.row(name)
        self.row("newer","2026-10-15 12:00:00.123457")
        self.row("older","2026-10-15 12:00:00.123455")
        self.denied={"b"}
        result=self.page(last=["2026-10-15 12:00:00.123456","d"])
        self.assertEqual(result["items"],[{"id":"c"},{"id":"a"}])
        self.assertEqual(result["total"],6);self.assertTrue(result["has_more"])
        self.assertEqual(self.calls,Counter({name:1 for name in ["a","b","c","d","e","newer","older"]}))

    def test_none_mode_still_seeks_and_stops_at_one_extra_visible_row(self):
        for name in "abcdefgh":self.row(name)
        self.denied={"f"}
        result=self.page(last=["2026-10-15 12:00:00.123456","h"],count_mode="none")
        self.assertEqual(result["items"],[{"id":"g"},{"id":"e"}])
        self.assertIsNone(result["total"]);self.assertTrue(result["has_more"])
        self.assertEqual(set(self.calls),{"g","f","e","d"})
        self.assertTrue(all(count==1 for count in self.calls.values()))

    def test_off_page_integrity_failure_aborts_exact_count_without_partial_result(self):
        for name in "abcde":self.row(name)
        self.corrupt={"a"}
        with self.assertRaises(DomainError) as error:self.page(limit=1)
        self.assertEqual(error.exception.code,"history_integrity")

    def test_scan_bound_counts_denied_rows_and_exposes_no_partial_page(self):
        for name in "abcde":self.row(name)
        self.denied={"d","c"}
        with patch.object(listing,"MAX_SCAN",3),self.assertRaises(DomainError) as error:self.page(limit=1)
        self.assertEqual(error.exception.code,"history_authorization_limit")
        self.assertLessEqual(sum(self.calls.values()),3)

    def test_current_denials_rechecked_between_calls_before_counts_and_cursor(self):
        for name in "abc":self.row(name)
        first=self.page();self.assertEqual(first["total"],3)
        self.denied=set("abc");self.calls.clear()
        hidden=self.page()
        self.assertEqual(hidden["items"],[]);self.assertEqual(hidden["total"],0)
        self.assertFalse(hidden["has_more"]);self.assertIsNone(hidden["last"])
        self.assertEqual(self.calls,Counter({name:1 for name in "abc"}))

    def test_explicit_scope_never_counts_other_company_or_project(self):
        self.row("company")
        self.row("project",scope_type="Project",project="real-project")
        self.row("other-company",company="Company B")
        self.row("malformed-company-project",project="real-project")
        self.assertEqual(self.page()["items"],[{"id":"company"}])
        self.assertEqual(set(self.calls),{"company"});self.calls.clear()
        self.assertEqual(self.page(project="real-project")["items"],[{"id":"project"}])
        self.assertEqual(set(self.calls),{"project"})

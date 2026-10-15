"""Executable query/guard contract; real Redis outage is a separate acceptance."""
from datetime import datetime, timedelta
import sqlite3
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from cipher_aec.api.errors import DomainError
from cipher_aec.integrations import distribution_recovery as recovery
from cipher_aec.integrations.distribution_install import _worker_configuration


class DistributionRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.database=sqlite3.connect(":memory:")
        self.addCleanup(self.database.close)
        self.database.execute("CREATE TABLE `tabCipher Integration Operation` (name TEXT,scope_type TEXT,project TEXT,kind TEXT,state TEXT,lease_until TIMESTAMP)")
        self.now=datetime(2026,10,15,12)
        self.calls=[]
        self.rollback=Mock()
        self.db=SimpleNamespace(transaction_writes=0,rollback=self.rollback,sql=self.query)
        self.frappe=ModuleType("frappe");self.frappe.db=self.db
        self.utils=ModuleType("frappe.utils");self.utils.now_datetime=lambda:self.now
        self.service=ModuleType("cipher_aec.integrations.distribution")
        self.service.require_current_effects_enabled=Mock()
        self.outbox=ModuleType("cipher_aec.integrations.outbox");self.outbox._schedule=self.calls.append
        self.addCleanup(patch.stopall)
        patch.dict(sys.modules,{"frappe":self.frappe,"frappe.utils":self.utils,
            "cipher_aec.integrations.distribution":self.service,"cipher_aec.integrations.outbox":self.outbox}).start()

    def query(self,sql,params):
        parameters=tuple(value.isoformat(sep=" ") if isinstance(value,datetime) else value for value in params)
        return self.database.execute(sql.replace("%s","?"),parameters).fetchall()

    def row(self,name,state="Queued",*,scope="Company",project=None,kind="company.proposal.fixture.v1",lease=None):
        self.database.execute("INSERT INTO `tabCipher Integration Operation` VALUES (?,?,?,?,?,?)",(name,scope,project,kind,state,lease.isoformat(sep=" ") if isinstance(lease,datetime) else lease))

    def test_literal_existing_company_states_only_no_task_or_sink_execution(self):
        past=self.now-timedelta(seconds=1);future=self.now+timedelta(seconds=1)
        self.row("a-queued");self.row("b-expired-claim","Claimed",lease=past)
        self.row("c-expired-unknown","Unknown",lease=past)
        self.row("d-null-unknown","Unknown")
        self.row("future-claim","Claimed",lease=future);self.row("future-unknown","Unknown",lease=future)
        for state in ("Succeeded","Failed","Cancelled"):self.row("terminal-"+state,state)
        self.row("task",scope="Project",project="real-project",kind="project.task.create")
        self.row("wrong-kind",kind="project.task.create")
        self.row("wrong-project",project="real-project")
        self.row("wrong-scope",scope="Project")
        before=self.database.execute("SELECT * FROM `tabCipher Integration Operation` ORDER BY name").fetchall()
        result=recovery.publish_pending()
        self.assertEqual(self.calls,["a-queued","b-expired-claim","c-expired-unknown","d-null-unknown"])
        self.assertEqual(result,{"status":"sweep_complete","eligible":4,"publication_attempts":4})
        self.assertEqual(self.database.execute("SELECT * FROM `tabCipher Integration Operation` ORDER BY name").fetchall(),before)
        self.assertEqual(self.rollback.call_count,2)
        self.assertEqual(self.service.require_current_effects_enabled.call_count,5)

    def test_batch_bound_and_original_names_are_stable_on_repeat(self):
        for number in range(105):self.row(f"operation-{number:03d}")
        self.assertEqual(recovery.publish_pending()["eligible"],100)
        first=list(self.calls);self.calls.clear()
        self.assertEqual(recovery.publish_pending()["publication_attempts"],100)
        self.assertEqual(self.calls,first)
        self.assertEqual(first[0],"operation-000");self.assertEqual(first[-1],"operation-099")

    def test_restored_quarantine_suppresses_query_and_all_publication(self):
        self.service.require_current_effects_enabled.side_effect=DomainError("execution_quarantined","Restored site is read only",503)
        self.db.sql=Mock(side_effect=AssertionError("Quarantined sweep queried operations"))
        self.assertEqual(recovery.publish_pending(),{"status":"quarantined","publication_attempts":0})
        self.assertEqual(self.calls,[])
        self.assertEqual(self.rollback.call_count,2)

    def test_quarantine_changed_during_sweep_stops_remaining_names(self):
        self.row("first");self.row("second")
        self.service.require_current_effects_enabled.side_effect=[None,None,DomainError("execution_quarantined","Operator quarantine",503)]
        self.assertEqual(recovery.publish_pending(),{"status":"quarantined","publication_attempts":1})
        self.assertEqual(self.calls,["first"])

    def test_existing_business_writes_refuse_before_rollback_or_queue(self):
        self.db.transaction_writes=1
        with self.assertRaisesRegex(RuntimeError,"isolated"):recovery.publish_pending()
        self.rollback.assert_not_called();self.assertEqual(self.calls,[])

    def test_query_failure_closes_transaction_without_discarding_intents(self):
        self.db.sql=Mock(side_effect=RuntimeError("Database unavailable"))
        with self.assertRaisesRegex(RuntimeError,"Database unavailable"):recovery.publish_pending()
        self.assertEqual(self.rollback.call_count,2)
        self.assertEqual(self.calls,[])

    def test_queue_configuration_preserves_other_workers_and_is_idempotent(self):
        previous={"other-project":{"timeout":900,"background_workers":2},
            "cipher_distribution":{"timeout":600,"background_workers":1}}
        updated=_worker_configuration(previous)
        self.assertEqual(updated["other-project"],previous["other-project"])
        self.assertEqual(updated["cipher_distribution"],{"timeout":120,"background_workers":1})
        self.assertEqual(previous["cipher_distribution"]["timeout"],600)
        self.assertEqual(_worker_configuration(updated),updated)
        self.assertEqual(_worker_configuration({}),{"cipher_distribution":{"timeout":120}})

    def test_invalid_existing_queue_configuration_fails_without_overwrite(self):
        for value in (None,[],"workers",{"cipher_distribution":None},{"cipher_distribution":[]}):
            with self.subTest(value=value),self.assertRaises(DomainError):_worker_configuration(value)

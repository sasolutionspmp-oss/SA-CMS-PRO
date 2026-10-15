"""Project schedule plugin: CPM golden case, resource loading, baselines and adversarial inputs."""
import json
import sqlite3
import unittest

from apps.cipher.core.approvals import ApprovalNotGranted, StaleApprovalError
from apps.cipher.domain.ledger import PeriodNotOpen
from apps.cipher.domain.people import IdentityRefused
from apps.cipher.domain.schedule import ScheduleError
from apps.cipher.service import Cipher


class Base(unittest.TestCase):
    """Fresh in-memory Cipher, a customer, a project and one open period per test."""

    def setUp(self):
        self.c = Cipher()
        self.customer = self.c.add_party(kind="customer", name="Cust")
        self.project = self.c.create_project(name="P", entity="E", budget="100000", customer_id=self.customer["id"])
        self.pid = self.project["id"]
        self.c.open_period("P1", "P1", "2026-10-01", "2026-10-31")
        self.s = self.c.plugin("schedule")

    def golden(self):
        """A(3) B(2) C(5) D(4) with A->B, A->C, B->D, C->D.  Returns {name: activity}."""
        acts = {name: self.s.add_activity(self.pid, name, dur, "o") for name, dur in (("A", 3), ("B", 2), ("C", 5), ("D", 4))}
        for p, q in (("A", "B"), ("A", "C"), ("B", "D"), ("C", "D")):
            self.s.add_dependency(acts[p]["id"], acts[q]["id"], "o")
        return acts

    @staticmethod
    def by_id(schedule):
        return {a["id"]: a for a in schedule["activities"]}


class CriticalPathTests(Base):
    def test_golden_network(self):
        acts = self.golden()
        sch = self.s.compute(self.pid)
        self.assertEqual(sch["duration_days"], 12)
        self.assertEqual(sch["critical_path"], [acts["A"]["id"], acts["C"]["id"], acts["D"]["id"]])
        self.assertEqual(sch["critical_activities"], [acts["A"]["id"], acts["C"]["id"], acts["D"]["id"]])
        a = self.by_id(sch)
        self.assertEqual(a[acts["B"]["id"]]["total_float"], 3)
        self.assertFalse(a[acts["B"]["id"]]["is_critical"])
        self.assertEqual((a[acts["A"]["id"]]["early_start"], a[acts["A"]["id"]]["early_finish"]), (0, 3))
        self.assertEqual((a[acts["B"]["id"]]["early_start"], a[acts["B"]["id"]]["early_finish"]), (3, 5))
        self.assertEqual((a[acts["B"]["id"]]["late_start"], a[acts["B"]["id"]]["late_finish"]), (6, 8))
        self.assertEqual((a[acts["C"]["id"]]["early_start"], a[acts["C"]["id"]]["early_finish"]), (3, 8))
        self.assertEqual((a[acts["D"]["id"]]["early_start"], a[acts["D"]["id"]]["early_finish"]), (8, 12))
        self.assertEqual((a[acts["D"]["id"]]["late_start"], a[acts["D"]["id"]]["late_finish"]), (8, 12))
        self.assertTrue(all(a[acts[n]["id"]]["is_critical"] for n in "ACD"))
        self.assertEqual(sch["order"][0], acts["A"]["id"])
        self.assertEqual(sch["order"][-1], acts["D"]["id"])
        self.assertEqual(sch["deadline_violations"], [])
        self.assertEqual(sch["over_allocations"], [])

    def test_lag_shifts_successor(self):
        a = self.s.add_activity(self.pid, "A", 3, "o")
        b = self.s.add_activity(self.pid, "B", 2, "o")
        self.s.add_dependency(a["id"], b["id"], "o", lag_days=4)
        sch = self.s.compute(self.pid)
        self.assertEqual(self.by_id(sch)[b["id"]]["early_start"], 7)
        self.assertEqual(sch["duration_days"], 9)
        self.assertEqual(sch["critical_path"], [a["id"], b["id"]])

    def test_deadline_violation(self):
        acts = self.golden()
        self.s.update_activity(acts["D"]["id"], "o", deadline_day=10)
        sch = self.s.compute(self.pid)
        self.assertEqual(sch["deadline_violations"], [{"activity_id": acts["D"]["id"], "name": "D", "deadline_day": 10, "early_finish": 12, "days_late": 2}])
        self.s.update_activity(acts["D"]["id"], "o", deadline_day=12)
        self.assertEqual(self.s.compute(self.pid)["deadline_violations"], [])

    def test_resource_over_allocation(self):
        crew = self.s.add_resource(self.pid, "Crew", 3, "o")
        x = self.s.add_activity(self.pid, "X", 3, "o", resource_id=crew["id"], resource_units=2)
        y = self.s.add_activity(self.pid, "Y", 2, "o", resource_id=crew["id"], resource_units=2)
        sch = self.s.compute(self.pid)
        self.assertEqual(sch["over_allocations"], [
            {"resource_id": crew["id"], "day": 0, "demand": 4, "capacity": 3},
            {"resource_id": crew["id"], "day": 1, "demand": 4, "capacity": 3},
        ])
        self.assertEqual(sch["resource_loading"][0]["demand_by_day"], [4, 4, 2])
        self.assertEqual(sch["resource_loading"][0]["peak_demand"], 4)
        # serialize Y after X and the conflict disappears
        self.s.add_dependency(x["id"], y["id"], "o")
        sch = self.s.compute(self.pid)
        self.assertEqual(sch["over_allocations"], [])
        self.assertEqual(sch["resource_loading"][0]["demand_by_day"], [2, 2, 2, 2, 2])

    def test_zero_duration_milestone(self):
        a = self.s.add_activity(self.pid, "A", 3, "o")
        m = self.s.add_activity(self.pid, "Milestone", 0, "o")
        self.s.add_dependency(a["id"], m["id"], "o")
        sch = self.s.compute(self.pid)
        ms = self.by_id(sch)[m["id"]]
        self.assertEqual((ms["early_start"], ms["early_finish"], ms["total_float"], ms["is_critical"]), (3, 3, 0, True))
        self.assertEqual(sch["duration_days"], 3)
        self.assertEqual(sch["critical_path"], [a["id"], m["id"]])
        crew = self.s.add_resource(self.pid, "Crew", 1, "o")
        self.s.update_activity(m["id"], "o", resource_id=crew["id"], resource_units=5)
        self.assertEqual(self.s.compute(self.pid)["over_allocations"], [])  # a milestone occupies no day

    def test_parallel_critical_chains_are_all_reported(self):
        a = self.s.add_activity(self.pid, "A", 4, "o")
        b = self.s.add_activity(self.pid, "B", 4, "o")
        sch = self.s.compute(self.pid)
        self.assertEqual(sch["duration_days"], 4)
        self.assertEqual(sch["critical_activities"], [a["id"], b["id"]])
        self.assertEqual(sch["critical_path"], [a["id"]])  # one chain, chosen by creation order

    def test_update_activity_bumps_version_and_recomputes(self):
        acts = self.golden()
        self.assertEqual(acts["B"]["version"], 1)
        b = self.s.update_activity(acts["B"]["id"], "o", duration_days=6)
        self.assertEqual(b["version"], 2)
        self.assertEqual(b["duration_days"], 6)
        sch = self.s.compute(self.pid)
        self.assertEqual(sch["duration_days"], 13)
        self.assertEqual(sch["critical_path"], [acts["A"]["id"], acts["B"]["id"], acts["D"]["id"]])
        self.assertEqual(self.by_id(sch)[acts["C"]["id"]]["total_float"], 1)
        with self.assertRaises(ScheduleError):
            self.s.update_activity(acts["B"]["id"], "o")  # nothing to update
        self.assertEqual(self.s.activity(acts["B"]["id"])["version"], 2)

    def test_remove_dependency(self):
        acts = self.golden()
        dep = next(d for d in self.s.dependencies(self.pid) if d["predecessor_id"] == acts["A"]["id"] and d["successor_id"] == acts["C"]["id"])
        self.s.remove_dependency(dep["id"], "o")
        sch = self.s.compute(self.pid)
        self.assertEqual(sch["dependency_count"], 3)
        self.assertEqual(self.by_id(sch)[acts["C"]["id"]]["early_start"], 0)
        self.assertEqual(sch["duration_days"], 9)
        self.assertEqual(sch["critical_path"], [acts["A"]["id"], acts["B"]["id"], acts["D"]["id"]])
        with self.assertRaises(ScheduleError):
            self.s.remove_dependency(dep["id"], "o")

    def test_compute_is_deterministic_and_hash_tracks_content(self):
        acts = self.golden()
        first = self.s.compute(self.pid)
        second = self.s.compute(self.pid)
        self.assertEqual(json.dumps(first, sort_keys=True), json.dumps(second, sort_keys=True))
        self.assertEqual(first["content_hash"], self.s.content_hash(self.pid))
        self.s.update_activity(acts["A"]["id"], "o", name="A renamed")
        self.assertNotEqual(self.s.compute(self.pid)["content_hash"], first["content_hash"])


class ValidationTests(Base):
    def test_cycle_rejected(self):
        acts = self.golden()
        with self.assertRaises(ScheduleError):
            self.s.add_dependency(acts["D"]["id"], acts["A"]["id"], "o")
        with self.assertRaises(ScheduleError):
            self.s.add_dependency(acts["D"]["id"], acts["B"]["id"], "o")  # indirect: B -> D -> B
        self.assertEqual(self.s.compute(self.pid)["dependency_count"], 4)
        self.assertEqual(self.s.compute(self.pid)["duration_days"], 12)

    def test_self_dependency_rejected(self):
        a = self.s.add_activity(self.pid, "A", 3, "o")
        with self.assertRaises(ScheduleError):
            self.s.add_dependency(a["id"], a["id"], "o")

    def test_duplicates_rejected(self):
        a = self.s.add_activity(self.pid, "A", 3, "o")
        b = self.s.add_activity(self.pid, "B", 2, "o")
        self.s.add_dependency(a["id"], b["id"], "o")
        with self.assertRaises(ScheduleError):
            self.s.add_dependency(a["id"], b["id"], "o", lag_days=2)
        with self.assertRaises(ScheduleError):
            self.s.add_activity(self.pid, "A", 1, "o")
        self.s.add_resource(self.pid, "Crew", 2, "o")
        with self.assertRaises(ScheduleError):
            self.s.add_resource(self.pid, "Crew", 5, "o")
        with self.assertRaises(ScheduleError):
            self.s.update_activity(b["id"], "o", name="A")
        self.assertEqual(len(self.s.activities(self.pid)), 2)
        self.assertEqual(len(self.s.dependencies(self.pid)), 1)
        self.assertEqual(len(self.s.resources(self.pid)), 1)

    def test_invalid_inputs_rejected(self):
        with self.assertRaises(ScheduleError):
            self.s.add_activity(self.pid, "A", -1, "o")
        with self.assertRaises(ScheduleError):
            self.s.add_activity(self.pid, "A", 2.5, "o")
        with self.assertRaises(ScheduleError):
            self.s.add_activity(self.pid, "A", True, "o")
        with self.assertRaises(ScheduleError):
            self.s.add_activity(self.pid, "A", "3", "o")
        with self.assertRaises(ScheduleError):
            self.s.add_activity(self.pid, "", 3, "o")
        with self.assertRaises(ScheduleError):
            self.s.add_activity(self.pid, "A", 3, "o", deadline_day=-1)
        with self.assertRaises(ScheduleError):
            self.s.add_activity(self.pid, "A", 3, "o", resource_id="res_missing")
        with self.assertRaises(ScheduleError):
            self.s.add_activity(self.pid, "A", 3, "o", resource_units=0)
        with self.assertRaises(ScheduleError):
            self.s.add_activity("prj_missing", "A", 3, "o")
        with self.assertRaises(ScheduleError):
            self.s.add_resource(self.pid, "Crew", 0, "o")
        a = self.s.add_activity(self.pid, "A", 3, "o")
        b = self.s.add_activity(self.pid, "B", 2, "o")
        with self.assertRaises(ScheduleError):
            self.s.add_dependency(a["id"], b["id"], "o", lag_days=-1)
        with self.assertRaises(ScheduleError):
            self.s.add_dependency(a["id"], "act_missing", "o")
        other = self.c.create_project(name="Q", entity="E", budget="1")
        crew_other = self.s.add_resource(other["id"], "Crew", 2, "o")
        z = self.s.add_activity(other["id"], "Z", 1, "o")
        with self.assertRaises(ScheduleError):
            self.s.add_dependency(a["id"], z["id"], "o")  # cross-project
        with self.assertRaises(ScheduleError):
            self.s.update_activity(a["id"], "o", resource_id=crew_other["id"])  # resource on another project
        with self.assertRaises(ScheduleError):
            self.s.compute("prj_missing")
        self.assertEqual(len(self.s.activities(self.pid)), 2)
        self.assertEqual(self.s.dependencies(self.pid), [])
        self.assertTrue(self.c.audit.verify_chain()["ok"])


class BaselineTests(Base):
    def test_baseline_operation(self):
        acts = self.golden()
        before = self.s.compute(self.pid)
        r = self.c.approve_and_execute("schedule.baseline", self.pid, period_id="P1")
        self.assertFalse(r.replayed)
        bl = r.result
        self.assertEqual(bl["sequence"], 1)
        self.assertEqual(bl["project_id"], self.pid)
        self.assertEqual(bl["period_id"], "P1")
        self.assertEqual(bl["duration_days"], 12)
        self.assertEqual(bl["content_hash"], before["content_hash"])
        self.assertEqual(bl["snapshot"]["critical_path"], [acts["A"]["id"], acts["C"]["id"], acts["D"]["id"]])
        self.assertEqual(bl["snapshot"]["duration_days"], 12)
        self.assertEqual(self.c.approvals.get(bl["approval_id"])["status"], "consumed")
        state = self.s.state(self.pid)
        self.assertEqual([b["id"] for b in state["baselines"]], [bl["id"]])
        second = self.c.approve_and_execute("schedule.baseline", self.pid, period_id="P1").result
        self.assertEqual(second["sequence"], 2)
        self.assertEqual(second["content_hash"], bl["content_hash"])
        self.assertEqual(len(self.s.baselines(self.pid)), 2)
        self.assertTrue(self.c.ledger.trial_balance()["balanced"])
        self.assertTrue(self.c.audit.verify_chain()["ok"])
        actions = [e["action"] for e in self.c.audit.entries(entity_type="schedule_baseline")]
        self.assertEqual(actions, ["schedule.baselined", "schedule.baselined"])

    def test_baseline_uses_current_period_when_none_given(self):
        self.golden()
        bl = self.c.approve_and_execute("schedule.baseline", self.pid).result
        self.assertEqual(bl["period_id"], "P1")

    def test_baseline_approval_stale_after_activity_edit(self):
        acts = self.golden()
        ap = self.c.request_approval("schedule.baseline", self.pid)
        self.c.approve(ap["id"])
        self.assertEqual(self.c.approvals.get(ap["id"])["status"], "granted")
        self.s.update_activity(acts["B"]["id"], "o", duration_days=6)
        with self.assertRaises((StaleApprovalError, ApprovalNotGranted)):
            self.c.execute(ap["id"])
        self.assertEqual(self.c.approvals.get(ap["id"])["status"], "invalidated")
        self.assertEqual(self.s.baselines(self.pid), [])
        self.assertTrue(self.c.audit.verify_chain()["ok"])

    def test_baseline_approval_stale_after_dependency_or_resource_change(self):
        acts = self.golden()
        ap = self.c.request_approval("schedule.baseline", self.pid)
        self.c.approve(ap["id"])
        dep = next(d for d in self.s.dependencies(self.pid) if d["predecessor_id"] == acts["A"]["id"] and d["successor_id"] == acts["B"]["id"])
        self.s.remove_dependency(dep["id"], "o")
        with self.assertRaises((StaleApprovalError, ApprovalNotGranted)):
            self.c.execute(ap["id"])
        self.assertEqual(self.c.approvals.get(ap["id"])["status"], "invalidated")
        ap2 = self.c.request_approval("schedule.baseline", self.pid)
        self.c.approve(ap2["id"])
        self.s.add_dependency(acts["A"]["id"], acts["B"]["id"], "o", lag_days=1)  # re-add the removed edge, now with lag
        with self.assertRaises((StaleApprovalError, ApprovalNotGranted)):
            self.c.execute(ap2["id"])
        self.assertEqual(self.c.approvals.get(ap2["id"])["status"], "invalidated")
        ap3 = self.c.request_approval("schedule.baseline", self.pid)
        self.c.approve(ap3["id"])
        self.s.add_resource(self.pid, "Crew", 2, "o")  # capacity feeds resource loading, so it is bound too
        with self.assertRaises((StaleApprovalError, ApprovalNotGranted)):
            self.c.execute(ap3["id"])
        self.assertEqual(self.c.approvals.get(ap3["id"])["status"], "invalidated")
        self.assertEqual(self.s.baselines(self.pid), [])

    def test_baseline_approval_stale_when_another_baseline_intervenes(self):
        self.golden()
        ap = self.c.request_approval("schedule.baseline", self.pid)
        self.c.approve(ap["id"])
        self.c.approve_and_execute("schedule.baseline", self.pid, period_id="P1")
        with self.assertRaises((StaleApprovalError, ApprovalNotGranted)):
            self.c.execute(ap["id"])
        self.assertEqual(self.c.approvals.get(ap["id"])["status"], "invalidated")
        self.assertEqual(len(self.s.baselines(self.pid)), 1)

    def test_baseline_rejected_in_closed_period(self):
        self.golden()
        self.c.close_period("P1")
        with self.assertRaises(PeriodNotOpen):
            self.c.approve_and_execute("schedule.baseline", self.pid, period_id="P1")
        self.assertEqual(self.s.baselines(self.pid), [])
        self.c.open_period("P2", "P2", "2026-11-01", "2026-11-30")
        bl = self.c.approve_and_execute("schedule.baseline", self.pid, period_id="P2").result
        self.assertEqual(bl["period_id"], "P2")
        self.assertEqual(bl["sequence"], 1)
        self.assertTrue(self.c.audit.verify_chain()["ok"])

    def test_baseline_requires_activities_and_known_operation(self):
        with self.assertRaises(ScheduleError):
            self.c.request_approval("schedule.baseline", self.pid)
        self.golden()
        with self.assertRaises(ScheduleError):
            self.c.request_approval("schedule.freeze", self.pid)
        self.assertEqual(self.c.approvals.list(), [])

    def test_baselines_are_immutable(self):
        self.golden()
        bl = self.c.approve_and_execute("schedule.baseline", self.pid, period_id="P1").result
        with self.assertRaises(sqlite3.IntegrityError):
            self.c.db.execute("UPDATE schedule_baselines SET duration_days=1 WHERE id=?", (bl["id"],))
        with self.assertRaises(sqlite3.IntegrityError):
            self.c.db.execute("DELETE FROM schedule_baselines WHERE id=?", (bl["id"],))
        self.assertEqual(self.s.baseline(bl["id"])["duration_days"], 12)

    def test_period_open_trigger_guards_direct_inserts(self):
        """The BEFORE INSERT trigger, not just ledger.require_open(), refuses a
        baseline row in a closed or unknown period even when the plugin is bypassed."""
        self.golden()
        bl = self.c.approve_and_execute("schedule.baseline", self.pid, period_id="P1").result
        self.c.close_period("P1")
        insert = """INSERT INTO schedule_baselines (id, project_id, period_id, sequence, content_hash, duration_days,
                    snapshot_json, snapshot_hash, approval_id, created_by, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)"""
        row = ["bsl_direct", self.pid, "P1", 2, bl["content_hash"], 12, "{}", "x", bl["approval_id"], "o", "2026-10-31T00:00:00Z"]
        with self.assertRaises(sqlite3.IntegrityError) as cm:
            self.c.db.execute(insert, tuple(row))
        self.assertIn("period is not open for baselining", str(cm.exception))
        row[2] = "P-missing"
        with self.assertRaises(sqlite3.IntegrityError) as cm:
            self.c.db.execute(insert, tuple(row))
        self.assertIn("period is not open for baselining", str(cm.exception))
        self.assertEqual([b["id"] for b in self.s.baselines(self.pid)], [bl["id"]])

    def test_apply_rejects_manifest_that_no_longer_matches(self):
        """apply() re-checks the manifest it is handed, so a direct caller with an
        old manifest (bypassing Cipher.execute) cannot baseline an unapproved schedule."""
        acts = self.golden()
        manifest = self.s.manifest_for("schedule.baseline", self.pid, actor_role="owner")
        self.s.update_activity(acts["A"]["id"], "o", duration_days=4)
        with self.assertRaises(ScheduleError):
            self.s.apply("schedule.baseline", self.pid, approval_id="apr_none", manifest=manifest, actor="o", period_id="P1")
        fresh = self.s.manifest_for("schedule.baseline", self.pid, actor_role="owner")
        self.c.approve_and_execute("schedule.baseline", self.pid, period_id="P1")  # sequence 1 is now taken
        with self.assertRaises(ScheduleError):
            self.s.apply("schedule.baseline", self.pid, approval_id="apr_none", manifest=fresh, actor="o", period_id="P1")
        self.assertEqual(len(self.s.baselines(self.pid)), 1)
        self.assertTrue(self.c.audit.verify_chain()["ok"])

    def test_a_project_scoped_pm_baselines_its_own_project_only(self):
        """The manifest binds the project, so under an enforcing identity policy the people
        governor checks a PM's authority on that project, not at entity scope."""
        self.golden()
        other = self.c.create_project(name="Q", entity="E", budget="100000", customer_id=self.customer["id"])
        people = self.c.plugin("people")
        people.bootstrap_owner("owner", "Synthetic owner")
        for login, project_id in (("pm.lee", self.pid), ("pm.sue", self.pid), ("pm.bo", other["id"])):
            people.register_person(login, "Synthetic PM", actor="owner")
            people.add_membership(login, project_id, actor="owner")
            req = people.request_grant(login, "pm", reason="PM on one project", actor="owner", project_id=project_id)
            self.c.approve_and_execute("people.grant_role", req["id"], actor="owner")
        people.register_person("clerk", "Synthetic clerk", actor="owner")
        draft = people.prepare_policy(enforce=True, segregate=True, reason="enforce", actor="owner")
        ap = self.c.request_approval("people.set_policy", draft["id"], actor_role="owner", requested_by="owner")
        self.c.approve(ap["id"], approver="owner", approver_role="owner")
        self.c.execute(ap["id"], actor="owner")
        self.assertTrue(people.enforcing())
        ap = self.c.request_approval("schedule.baseline", self.pid, actor_role="pm", requested_by="clerk")
        self.assertEqual(ap["manifest"]["bindings"]["project_id"], self.pid)
        with self.assertRaises(IdentityRefused):  # another project's PM
            self.c.approve(ap["id"], approver="pm.bo", approver_role="pm")
        self.c.approve(ap["id"], approver="pm.sue", approver_role="pm")
        with self.assertRaises(IdentityRefused):
            self.c.execute(ap["id"], actor="pm.bo")
        bl = self.c.execute(ap["id"], actor="pm.lee").result
        self.assertEqual((bl["project_id"], bl["sequence"], bl["created_by"]), (self.pid, 1, "pm.lee"))

    def test_state_shape_and_serializable(self):
        empty = self.s.state(self.pid)
        self.assertEqual(set(empty), {"schedule", "baselines"})
        self.assertEqual(empty["schedule"]["duration_days"], 0)
        self.assertEqual(empty["schedule"]["critical_path"], [])
        self.assertEqual(empty["baselines"], [])
        acts = self.golden()
        crew = self.s.add_resource(self.pid, "Crew", 3, "o")
        self.s.update_activity(acts["D"]["id"], "o", deadline_day=10, resource_id=crew["id"], resource_units=2)
        self.c.approve_and_execute("schedule.baseline", self.pid, period_id="P1")
        state = self.c.project_state(self.pid)
        sch = state["schedule"]["schedule"]
        for key in ("project_id", "content_hash", "activity_count", "dependency_count", "resource_count", "duration_days", "order",
                    "activities", "dependencies", "resources", "critical_path", "critical_activities", "deadline_violations",
                    "resource_loading", "over_allocations"):
            self.assertIn(key, sch)
        self.assertEqual(sch["activity_count"], 4)
        self.assertEqual(len(sch["deadline_violations"]), 1)
        self.assertEqual(len(state["schedule"]["baselines"]), 1)
        json.dumps(state["schedule"])  # must be plain JSON
        self.assertTrue(state["audit_chain"]["ok"])


if __name__ == "__main__":
    unittest.main()

"""Project schedule with critical-path analysis and resource loading.

Everything is in whole days measured from project day 0.  An activity with
early start ``s`` and duration ``d`` occupies the half-open day range
``[s, s + d)`` and is finished at the start of day ``s + d``; a zero-duration
milestone occupies no day at all.  Dependencies are finish-to-start with a
non-negative integer lag.

``compute()`` is a pure, deterministic function of the stored rows:

* topological order (Kahn's algorithm, ties broken by creation order);
* forward pass  -> early start / early finish, with lag;
* backward pass -> late start / late finish;
* total float = late start - early start; ``is_critical`` when the float is 0;
* ``critical_path``: one ordered zero-float chain from project start to the
  project finish (every zero-float activity is also listed in
  ``critical_activities``, so parallel critical chains are not hidden);
* deadline violations where early finish > deadline_day;
* resource loading: for each resource and each day, the sum of the units
  demanded by activities scheduled on that day by their early dates;
  ``over_allocations`` lists every day where demand exceeds capacity.

The only approval-bound operation is ``schedule.baseline``: it freezes the
computed schedule into an immutable ``schedule_baselines`` row.  The manifest
binds a content hash of every activity, dependency and resource plus the
computed duration, so any edit between approval and execution makes the
approval stale.  No money moves in this module, so no journals are posted;
a baseline is still recorded against an open accounting period.
"""
from __future__ import annotations

import json
from typing import Any

from ..core.approvals import build_manifest
from ..core.ids import canonical_json, hash_json, new_id, utcnow_iso

SCHEMA_NAME = "schedule"
PLUGIN_NAME = "schedule"
SUBJECT_TYPE = "project_schedule"
BASELINE_OPERATION = "schedule.baseline"

SCHEMA_STATEMENTS = [
    """CREATE TABLE schedule_resources (
        id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES projects(id),
        name TEXT NOT NULL,
        capacity_units INTEGER NOT NULL CHECK (capacity_units >= 1),
        created_at TEXT NOT NULL,
        UNIQUE (project_id, name)
    )""",
    """CREATE TABLE schedule_activities (
        id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES projects(id),
        name TEXT NOT NULL,
        duration_days INTEGER NOT NULL CHECK (duration_days >= 0),
        deadline_day INTEGER CHECK (deadline_day IS NULL OR deadline_day >= 0),
        resource_id TEXT REFERENCES schedule_resources(id),
        resource_units INTEGER NOT NULL DEFAULT 1 CHECK (resource_units >= 1),
        version INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE (project_id, name)
    )""",
    """CREATE TABLE schedule_dependencies (
        id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES projects(id),
        predecessor_id TEXT NOT NULL REFERENCES schedule_activities(id),
        successor_id TEXT NOT NULL REFERENCES schedule_activities(id),
        lag_days INTEGER NOT NULL DEFAULT 0 CHECK (lag_days >= 0),
        created_at TEXT NOT NULL,
        UNIQUE (predecessor_id, successor_id),
        CHECK (predecessor_id <> successor_id)
    )""",
    """CREATE TABLE schedule_baselines (
        id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES projects(id),
        period_id TEXT NOT NULL REFERENCES periods(id),
        sequence INTEGER NOT NULL,
        content_hash TEXT NOT NULL,
        duration_days INTEGER NOT NULL,
        snapshot_json TEXT NOT NULL,
        snapshot_hash TEXT NOT NULL,
        approval_id TEXT NOT NULL REFERENCES approvals(id),
        created_by TEXT NOT NULL,
        created_at TEXT NOT NULL,
        UNIQUE (project_id, sequence)
    )""",
    "CREATE TRIGGER schedule_baselines_no_update BEFORE UPDATE ON schedule_baselines BEGIN SELECT RAISE(ABORT, 'schedule baselines are immutable'); END",
    "CREATE TRIGGER schedule_baselines_no_delete BEFORE DELETE ON schedule_baselines BEGIN SELECT RAISE(ABORT, 'schedule baselines are immutable'); END",
    """CREATE TRIGGER schedule_baselines_period_open BEFORE INSERT ON schedule_baselines
        BEGIN
            SELECT CASE
                WHEN (SELECT status FROM periods WHERE id = NEW.period_id) IS NOT 'open'
                THEN RAISE(ABORT, 'period is not open for baselining')
            END;
        END""",
]


class ScheduleError(RuntimeError):
    """Invalid schedule input, duplicate record, or a dependency that would form a cycle."""


_UNSET = object()


def _require_int(value: Any, label: str, *, minimum: int | None = None) -> int:
    """Whole-day quantities are integers; bools, floats and strings are rejected."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise ScheduleError(f"{label} must be an integer number of days/units, got {type(value).__name__}")
    if minimum is not None and value < minimum:
        raise ScheduleError(f"{label} must be >= {minimum}, got {value}")
    return value


def _require_name(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ScheduleError(f"{label} must be a non-empty string")
    return value.strip()


class Plugin:
    def __init__(self, cipher):
        self.c = cipher
        self.db = cipher.db
        self.audit = cipher.audit
        self.ledger = cipher.ledger
        self.approvals = cipher.approvals

    # ---- lookups ------------------------------------------------------------ #

    def _project(self, project_id: str) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM projects WHERE id=?", (project_id,))
        if row is None:
            raise ScheduleError(f"unknown project {project_id}")
        return row

    def resource(self, resource_id: str) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM schedule_resources WHERE id=?", (resource_id,))
        if row is None:
            raise ScheduleError(f"unknown schedule resource {resource_id}")
        return row

    def resources(self, project_id: str) -> list[dict[str, Any]]:
        return self.db.query("SELECT * FROM schedule_resources WHERE project_id=? ORDER BY created_at, id", (project_id,))

    def activity(self, activity_id: str) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM schedule_activities WHERE id=?", (activity_id,))
        if row is None:
            raise ScheduleError(f"unknown schedule activity {activity_id}")
        return row

    def activities(self, project_id: str) -> list[dict[str, Any]]:
        return self.db.query("SELECT * FROM schedule_activities WHERE project_id=? ORDER BY created_at, id", (project_id,))

    def dependency(self, dependency_id: str) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM schedule_dependencies WHERE id=?", (dependency_id,))
        if row is None:
            raise ScheduleError(f"unknown schedule dependency {dependency_id}")
        return row

    def dependencies(self, project_id: str) -> list[dict[str, Any]]:
        return self.db.query("SELECT * FROM schedule_dependencies WHERE project_id=? ORDER BY created_at, id", (project_id,))

    def baseline(self, baseline_id: str) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM schedule_baselines WHERE id=?", (baseline_id,))
        if row is None:
            raise ScheduleError(f"unknown schedule baseline {baseline_id}")
        row["snapshot"] = json.loads(row.pop("snapshot_json"))
        return row

    def baselines(self, project_id: str) -> list[dict[str, Any]]:
        rows = self.db.query("SELECT * FROM schedule_baselines WHERE project_id=? ORDER BY sequence", (project_id,))
        for r in rows:
            r["snapshot"] = json.loads(r.pop("snapshot_json"))
        return rows

    # ---- records ------------------------------------------------------------ #

    def add_resource(self, project_id: str, name: str, capacity_units: int, actor: str) -> dict[str, Any]:
        name = _require_name(name, "resource name")
        capacity = _require_int(capacity_units, "capacity_units", minimum=1)
        rid = new_id("res")
        with self.db.transaction() as conn:
            self._project(project_id)
            if conn.execute("SELECT id FROM schedule_resources WHERE project_id=? AND name=?", (project_id, name)).fetchone():
                raise ScheduleError(f"resource {name!r} already exists on this project")
            conn.execute(
                "INSERT INTO schedule_resources (id, project_id, name, capacity_units, created_at) VALUES (?,?,?,?,?)",
                (rid, project_id, name, capacity, utcnow_iso()),
            )
            self.audit.record(actor, "schedule.resource_added", "schedule_resource", rid, {"project_id": project_id, "name": name, "capacity_units": capacity})
        return self.resource(rid)

    def add_activity(
        self,
        project_id: str,
        name: str,
        duration_days: int,
        actor: str,
        *,
        deadline_day: int | None = None,
        resource_id: str | None = None,
        resource_units: int = 1,
    ) -> dict[str, Any]:
        name = _require_name(name, "activity name")
        duration = _require_int(duration_days, "duration_days", minimum=0)
        deadline = None if deadline_day is None else _require_int(deadline_day, "deadline_day", minimum=0)
        units = _require_int(resource_units, "resource_units", minimum=1)
        aid = new_id("act")
        now = utcnow_iso()
        with self.db.transaction() as conn:
            self._project(project_id)
            if resource_id is not None:
                res = self.resource(resource_id)
                if res["project_id"] != project_id:
                    raise ScheduleError("resource belongs to a different project")
            if conn.execute("SELECT id FROM schedule_activities WHERE project_id=? AND name=?", (project_id, name)).fetchone():
                raise ScheduleError(f"activity {name!r} already exists on this project")
            conn.execute(
                """INSERT INTO schedule_activities (id, project_id, name, duration_days, deadline_day, resource_id, resource_units, version, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,1,?,?)""",
                (aid, project_id, name, duration, deadline, resource_id, units, now, now),
            )
            self.audit.record(actor, "schedule.activity_added", "schedule_activity", aid, {
                "project_id": project_id, "name": name, "duration_days": duration, "deadline_day": deadline,
                "resource_id": resource_id, "resource_units": units, "version": 1,
            })
        return self.activity(aid)

    def update_activity(
        self,
        activity_id: str,
        actor: str,
        *,
        name: Any = _UNSET,
        duration_days: Any = _UNSET,
        deadline_day: Any = _UNSET,
        resource_id: Any = _UNSET,
        resource_units: Any = _UNSET,
    ) -> dict[str, Any]:
        """Edit an activity.  Every edit bumps ``version`` so an approval bound to the
        previous content is invalidated when it is executed."""
        with self.db.transaction() as conn:
            a = self.activity(activity_id)
            changes: dict[str, Any] = {}
            if name is not _UNSET:
                new_name = _require_name(name, "activity name")
                dup = conn.execute("SELECT id FROM schedule_activities WHERE project_id=? AND name=? AND id<>?", (a["project_id"], new_name, activity_id)).fetchone()
                if dup:
                    raise ScheduleError(f"activity {new_name!r} already exists on this project")
                changes["name"] = new_name
            if duration_days is not _UNSET:
                changes["duration_days"] = _require_int(duration_days, "duration_days", minimum=0)
            if deadline_day is not _UNSET:
                changes["deadline_day"] = None if deadline_day is None else _require_int(deadline_day, "deadline_day", minimum=0)
            if resource_id is not _UNSET:
                if resource_id is not None:
                    res = self.resource(resource_id)
                    if res["project_id"] != a["project_id"]:
                        raise ScheduleError("resource belongs to a different project")
                changes["resource_id"] = resource_id
            if resource_units is not _UNSET:
                changes["resource_units"] = _require_int(resource_units, "resource_units", minimum=1)
            if not changes:
                raise ScheduleError("nothing to update")
            new_version = a["version"] + 1
            sets = ", ".join(f"{k}=?" for k in changes)
            conn.execute(
                f"UPDATE schedule_activities SET {sets}, version=?, updated_at=? WHERE id=?",
                (*changes.values(), new_version, utcnow_iso(), activity_id),
            )
            self.audit.record(actor, "schedule.activity_updated", "schedule_activity", activity_id, {
                "project_id": a["project_id"], "changes": changes, "version": new_version,
            })
        return self.activity(activity_id)

    def add_dependency(self, predecessor_id: str, successor_id: str, actor: str, *, lag_days: int = 0) -> dict[str, Any]:
        """Finish-to-start dependency.  Rejects self-dependency, duplicates,
        cross-project links and anything that would close a cycle."""
        lag = _require_int(lag_days, "lag_days", minimum=0)
        if predecessor_id == successor_id:
            raise ScheduleError("an activity cannot depend on itself")
        did = new_id("dep")
        with self.db.transaction() as conn:
            pred = self.activity(predecessor_id)
            succ = self.activity(successor_id)
            if pred["project_id"] != succ["project_id"]:
                raise ScheduleError("dependencies must link activities on the same project")
            project_id = pred["project_id"]
            if conn.execute("SELECT id FROM schedule_dependencies WHERE predecessor_id=? AND successor_id=?", (predecessor_id, successor_id)).fetchone():
                raise ScheduleError(f"dependency {pred['name']} -> {succ['name']} already exists")
            successors = self._successor_map(project_id)
            if self._reaches(successors, start=successor_id, target=predecessor_id):
                raise ScheduleError(f"dependency {pred['name']} -> {succ['name']} would create a cycle")
            conn.execute(
                "INSERT INTO schedule_dependencies (id, project_id, predecessor_id, successor_id, lag_days, created_at) VALUES (?,?,?,?,?,?)",
                (did, project_id, predecessor_id, successor_id, lag, utcnow_iso()),
            )
            self.audit.record(actor, "schedule.dependency_added", "schedule_dependency", did, {
                "project_id": project_id, "predecessor_id": predecessor_id, "successor_id": successor_id, "lag_days": lag,
            })
        return self.dependency(did)

    def remove_dependency(self, dependency_id: str, actor: str) -> dict[str, Any]:
        with self.db.transaction() as conn:
            d = self.dependency(dependency_id)
            conn.execute("DELETE FROM schedule_dependencies WHERE id=?", (dependency_id,))
            self.audit.record(actor, "schedule.dependency_removed", "schedule_dependency", dependency_id, {
                "project_id": d["project_id"], "predecessor_id": d["predecessor_id"], "successor_id": d["successor_id"],
            })
        return {"id": dependency_id, "removed": True}

    # ---- graph helpers ---------------------------------------------------------- #

    def _successor_map(self, project_id: str) -> dict[str, list[tuple[str, int]]]:
        succ: dict[str, list[tuple[str, int]]] = {}
        for d in self.dependencies(project_id):
            succ.setdefault(d["predecessor_id"], []).append((d["successor_id"], d["lag_days"]))
        return succ

    @staticmethod
    def _reaches(successors: dict[str, list[tuple[str, int]]], *, start: str, target: str) -> bool:
        """Iterative depth-first walk: can ``target`` be reached from ``start``?"""
        seen = {start}
        stack = [start]
        while stack:
            node = stack.pop()
            if node == target:
                return True
            for nxt, _lag in successors.get(node, ()):
                if nxt not in seen:
                    seen.add(nxt)
                    stack.append(nxt)
        return False

    # ---- critical path ------------------------------------------------------------ #

    def content_hash(self, project_id: str) -> str:
        return hash_json(self._content(project_id))

    def _content(self, project_id: str) -> dict[str, Any]:
        """The material facts a baseline approval binds: every activity (with its
        version), every dependency and every resource."""
        return {
            "project_id": project_id,
            "activities": [
                {k: a[k] for k in ("id", "name", "duration_days", "deadline_day", "resource_id", "resource_units", "version")}
                for a in self.activities(project_id)
            ],
            "dependencies": [
                {k: d[k] for k in ("id", "predecessor_id", "successor_id", "lag_days")}
                for d in self.dependencies(project_id)
            ],
            "resources": [
                {k: r[k] for k in ("id", "name", "capacity_units")}
                for r in self.resources(project_id)
            ],
        }

    def compute(self, project_id: str) -> dict[str, Any]:
        """Deterministic CPM in integer days.  See the module docstring."""
        self._project(project_id)
        content = self._content(project_id)
        acts = {a["id"]: dict(a) for a in self.activities(project_id)}
        order_key = {a["id"]: (a["created_at"], a["id"]) for a in acts.values()}
        deps = content["dependencies"]
        resources = content["resources"]

        preds: dict[str, list[tuple[str, int]]] = {aid: [] for aid in acts}
        succs: dict[str, list[tuple[str, int]]] = {aid: [] for aid in acts}
        for d in deps:
            preds[d["successor_id"]].append((d["predecessor_id"], d["lag_days"]))
            succs[d["predecessor_id"]].append((d["successor_id"], d["lag_days"]))

        # topological order (Kahn), ties broken by creation order
        indegree = {aid: len(preds[aid]) for aid in acts}
        ready = sorted((aid for aid, n in indegree.items() if n == 0), key=order_key.__getitem__)
        order: list[str] = []
        while ready:
            node = ready.pop(0)
            order.append(node)
            released = []
            for s, _lag in succs[node]:
                indegree[s] -= 1
                if indegree[s] == 0:
                    released.append(s)
            if released:
                ready = sorted(ready + released, key=order_key.__getitem__)
        if len(order) != len(acts):
            # add_dependency prevents this; a direct database edit could not.
            raise ScheduleError("the dependency graph contains a cycle; the schedule cannot be computed")

        # forward pass
        es: dict[str, int] = {}
        ef: dict[str, int] = {}
        for aid in order:
            start = 0
            for p, lag in preds[aid]:
                start = max(start, ef[p] + lag)
            es[aid] = start
            ef[aid] = start + acts[aid]["duration_days"]
        duration = max(ef.values()) if ef else 0

        # backward pass
        lf: dict[str, int] = {}
        ls: dict[str, int] = {}
        for aid in reversed(order):
            finish = duration
            for s, lag in succs[aid]:
                finish = min(finish, ls[s] - lag)
            lf[aid] = finish
            ls[aid] = finish - acts[aid]["duration_days"]

        float_of = {aid: ls[aid] - es[aid] for aid in order}
        critical = {aid for aid in order if float_of[aid] == 0}

        # one zero-float chain from a critical start to the project finish
        critical_path: list[str] = []
        starts = [aid for aid in order if aid in critical and es[aid] == 0 and not any(p in critical and ef[p] + lag == es[aid] for p, lag in preds[aid])]
        if starts:
            node = min(starts, key=order_key.__getitem__)
            seen = set()
            while node is not None and node not in seen:
                seen.add(node)
                critical_path.append(node)
                nxt = [s for s, lag in succs[node] if s in critical and es[s] == ef[node] + lag]
                node = min(nxt, key=order_key.__getitem__) if nxt else None

        deadline_violations = []
        for aid in order:
            dl = acts[aid]["deadline_day"]
            if dl is not None and ef[aid] > dl:
                deadline_violations.append({"activity_id": aid, "name": acts[aid]["name"], "deadline_day": dl, "early_finish": ef[aid], "days_late": ef[aid] - dl})

        # resource loading by early dates: activity occupies days [es, ef)
        loading = []
        over_allocations = []
        for r in resources:
            demand = [0] * duration
            for aid in order:
                if acts[aid]["resource_id"] != r["id"]:
                    continue
                for day in range(es[aid], ef[aid]):
                    demand[day] += acts[aid]["resource_units"]
            for day, units in enumerate(demand):
                if units > r["capacity_units"]:
                    over_allocations.append({"resource_id": r["id"], "day": day, "demand": units, "capacity": r["capacity_units"]})
            loading.append({"resource_id": r["id"], "name": r["name"], "capacity_units": r["capacity_units"], "demand_by_day": demand, "peak_demand": max(demand) if demand else 0})

        activities_out = []
        for aid in order:
            a = acts[aid]
            activities_out.append({
                "id": aid, "name": a["name"], "duration_days": a["duration_days"], "deadline_day": a["deadline_day"],
                "resource_id": a["resource_id"], "resource_units": a["resource_units"], "version": a["version"],
                "early_start": es[aid], "early_finish": ef[aid], "late_start": ls[aid], "late_finish": lf[aid],
                "total_float": float_of[aid], "is_critical": aid in critical,
                "predecessors": [{"activity_id": p, "lag_days": lag} for p, lag in sorted(preds[aid], key=lambda t: order_key[t[0]])],
                "successors": [{"activity_id": s, "lag_days": lag} for s, lag in sorted(succs[aid], key=lambda t: order_key[t[0]])],
            })

        return {
            "project_id": project_id,
            "content_hash": hash_json(content),
            "activity_count": len(acts),
            "dependency_count": len(deps),
            "resource_count": len(resources),
            "duration_days": duration,
            "order": order,
            "activities": activities_out,
            "dependencies": deps,
            "resources": resources,
            "critical_path": critical_path,
            "critical_activities": [aid for aid in order if aid in critical],
            "deadline_violations": deadline_violations,
            "resource_loading": loading,
            "over_allocations": over_allocations,
        }

    # ---- approval-bound operation ---------------------------------------------------- #

    def _next_sequence(self, project_id: str) -> int:
        last = self.db.scalar("SELECT MAX(sequence) FROM schedule_baselines WHERE project_id=?", (project_id,))
        return (last or 0) + 1

    def manifest_for(self, operation: str, subject_id: str, *, actor_role: str) -> dict[str, Any]:
        if operation != BASELINE_OPERATION:
            raise ScheduleError(f"unknown schedule operation {operation}")
        schedule = self.compute(subject_id)
        if schedule["activity_count"] == 0:
            raise ScheduleError("the schedule has no activities; nothing to baseline")
        return build_manifest(
            operation=operation,
            subject_type=SUBJECT_TYPE,
            subject_id=subject_id,
            actor_role=actor_role,
            amounts={},
            bindings={
                "content_hash": schedule["content_hash"],
                "duration_days": schedule["duration_days"],
                "activity_count": schedule["activity_count"],
                "dependency_count": schedule["dependency_count"],
                "critical_path": schedule["critical_path"],
                "baseline_sequence": self._next_sequence(subject_id),
            },
        )

    def apply(self, operation: str, subject_id: str, *, approval_id: str, manifest: dict[str, Any], actor: str, period_id: str | None) -> dict[str, Any]:
        """Freeze the current schedule as a baseline.  The caller has consumed ``approval_id``."""
        if operation != BASELINE_OPERATION:
            raise ScheduleError(f"unknown schedule operation {operation}")
        pid = period_id or self.c.current_period()["id"]
        bid = new_id("bsl")
        with self.db.transaction() as conn:
            self.ledger.require_open(pid)
            schedule = self.compute(subject_id)
            if schedule["content_hash"] != manifest["bindings"]["content_hash"]:
                raise ScheduleError("the schedule changed after approval; request a new baseline approval")
            sequence = self._next_sequence(subject_id)
            if sequence != manifest["bindings"]["baseline_sequence"]:
                raise ScheduleError("another baseline was taken after approval; request a new baseline approval")
            snapshot_json = canonical_json(schedule)
            snapshot_hash = hash_json(schedule)
            conn.execute(
                """INSERT INTO schedule_baselines (id, project_id, period_id, sequence, content_hash, duration_days, snapshot_json, snapshot_hash, approval_id, created_by, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (bid, subject_id, pid, sequence, schedule["content_hash"], schedule["duration_days"], snapshot_json, snapshot_hash, approval_id, actor, utcnow_iso()),
            )
            self.audit.record(actor, "schedule.baselined", "schedule_baseline", bid, {
                "project_id": subject_id, "period_id": pid, "sequence": sequence, "content_hash": schedule["content_hash"],
                "snapshot_hash": snapshot_hash, "duration_days": schedule["duration_days"], "approval_id": approval_id,
                "critical_path": schedule["critical_path"],
            })
        return self.baseline(bid)

    # ---- console / API ------------------------------------------------------------------ #

    def state(self, project_id: str) -> dict[str, Any]:
        return {
            "schedule": self.compute(project_id),
            "baselines": self.baselines(project_id),
        }

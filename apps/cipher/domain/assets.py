"""Asset register with straight-line depreciation (v2 plugin, operation prefix ``asset``).

Posting rules (fixture policy ``cipher-posting-rules/1``, synthetic prototype only):

* ``asset.capitalize``           Dr 1500 Fixed assets / Cr 1000 Operating bank (synthetic purchase)
* ``asset.post_depreciation``    Dr 5200 Depreciation expense / Cr 1590 Accumulated depreciation
* ``asset.reverse_depreciation`` the run's journal reversed through ``Ledger.reverse``
                                 (default: into the run's period)
* ``asset.dispose``              Dr 1590 accumulated to date, Dr 5200 remaining book value, Cr 1500 cost
                                 (default: into the latest open period)

A reversal or disposal is never dated in a period starting before the journals it
reverses or settles (the rule ``journal.reverse`` applies): a reversal not before its
run's journal, a disposal not before the asset's capitalization journal or any of its
depreciation journals and their reversals.  The manifests bind that rule (``target_rule``).

Schedule: straight-line monthly charge = (cost - salvage) / useful_life_months
quantised to cents; the FINAL month absorbs the rounding residual so the schedule
sums to cost - salvage exactly (1,000 over 3 months is 333.33, 333.33, 333.34).

Runs are monthly: the period must lie within one calendar month, the run is
charged to that month (``charge_month``), and the in-service month is charged in
full whatever the day.  A period before the in-service month, or one for which
the asset is already fully depreciated (accumulated posted depreciation has
reached cost - salvage) or whose month lies past the end of the schedule,
yields a ``no_charge`` run with amount 0.00 that can never carry a journal
(SQLite triggers enforce it).  One live run per asset per calendar month, not
per period id: several period rows may cover the same month (an adjustment
period, a split month) and none of them may charge the month twice.  A
duplicate is rejected unless the earlier run for that month was reversed (or
canceled), in which case the replacement links ``replaced_run_id``.  The
register can never exceed the depreciable base: a run's amount is clamped to
what remains when it is scheduled and checked again when it is posted.
Editing an asset bumps its version, which invalidates any open approval bound
to the old version, and cancels its unposted runs because their amounts derive
from the old parameters; an asset with posted depreciation cannot be edited
until those runs are reversed.
"""
from __future__ import annotations

import datetime as _dt
from decimal import Decimal, ROUND_DOWN
from typing import Any

from ..core.approvals import build_manifest
from ..core.ids import hash_json, new_id, utcnow_iso
from ..core.money import CENTS, MoneyError, ZERO, fmt, money, total

SCHEMA_NAME = "assets"
PLUGIN_NAME = "asset"
POSTING_RULE = "cipher-posting-rules/1"
METHODS = ("straight_line",)
MAX_LIFE_MONTHS = 1200

ASSET_FIELDS = ("project_id", "description", "cost", "salvage_value", "in_service_date", "useful_life_months", "method")
EDITABLE_FIELDS = ("description", "cost", "salvage_value", "in_service_date", "useful_life_months", "method")
LIVE_RUN_STATUSES = ("draft", "no_charge", "posted")

SCHEMA_STATEMENTS = [
    """CREATE TABLE asset_register (
        id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES projects(id),
        description TEXT NOT NULL,
        cost TEXT NOT NULL,
        salvage_value TEXT NOT NULL,
        in_service_date TEXT NOT NULL,
        useful_life_months INTEGER NOT NULL CHECK (useful_life_months >= 1),
        method TEXT NOT NULL CHECK (method IN ('straight_line')),
        status TEXT NOT NULL CHECK (status IN ('registered','active','disposed')),
        version INTEGER NOT NULL DEFAULT 1,
        content_hash TEXT NOT NULL,
        capitalisation_journal_id TEXT REFERENCES journals(id),
        capitalisation_approval_id TEXT REFERENCES approvals(id),
        disposal_journal_id TEXT REFERENCES journals(id),
        disposal_approval_id TEXT REFERENCES approvals(id),
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        capitalised_at TEXT,
        disposed_at TEXT
    )""",
    "CREATE TRIGGER asset_register_no_delete BEFORE DELETE ON asset_register BEGIN SELECT RAISE(ABORT, 'assets are never deleted; dispose them'); END",
    """CREATE TRIGGER asset_register_disposed_immutable BEFORE UPDATE ON asset_register
        WHEN OLD.status = 'disposed'
        BEGIN SELECT RAISE(ABORT, 'a disposed asset is immutable'); END""",
    """CREATE TABLE asset_depreciation_runs (
        id TEXT PRIMARY KEY,
        asset_id TEXT NOT NULL REFERENCES asset_register(id),
        period_id TEXT NOT NULL REFERENCES periods(id),
        charge_month TEXT NOT NULL CHECK (length(charge_month) = 7 AND substr(charge_month, 5, 1) = '-'),
        sequence INTEGER NOT NULL,
        amount TEXT NOT NULL,
        asset_version INTEGER NOT NULL,
        status TEXT NOT NULL CHECK (status IN ('draft','no_charge','posted','reversed','cancelled')),
        note TEXT NOT NULL DEFAULT '',
        content_hash TEXT NOT NULL,
        approval_id TEXT REFERENCES approvals(id),
        journal_id TEXT REFERENCES journals(id),
        reversal_approval_id TEXT REFERENCES approvals(id),
        reversal_journal_id TEXT REFERENCES journals(id),
        replaced_run_id TEXT REFERENCES asset_depreciation_runs(id),
        created_at TEXT NOT NULL,
        posted_at TEXT,
        reversed_at TEXT,
        cancelled_at TEXT
    )""",
    # One live run per asset per calendar MONTH.  Several period rows may cover the
    # same month; keying the guard on the month (not the period id) is what stops
    # the same monthly charge posting once per period row.
    "CREATE UNIQUE INDEX asset_runs_one_live_per_month ON asset_depreciation_runs (asset_id, charge_month) WHERE status IN ('draft','no_charge','posted')",
    "CREATE TRIGGER asset_runs_no_delete BEFORE DELETE ON asset_depreciation_runs BEGIN SELECT RAISE(ABORT, 'depreciation runs are never deleted'); END",
    """CREATE TRIGGER asset_runs_charge_month_matches_period BEFORE INSERT ON asset_depreciation_runs
        WHEN NEW.charge_month IS NOT (SELECT substr(start_date, 1, 7) FROM periods WHERE id = NEW.period_id)
          OR (SELECT substr(start_date, 1, 7) IS NOT substr(end_date, 1, 7) FROM periods WHERE id = NEW.period_id)
        BEGIN SELECT RAISE(ABORT, 'a depreciation run is charged to the calendar month of its period, which must lie within one month'); END""",
    """CREATE TRIGGER asset_runs_identity_immutable BEFORE UPDATE ON asset_depreciation_runs
        WHEN NEW.asset_id IS NOT OLD.asset_id OR NEW.period_id IS NOT OLD.period_id OR NEW.charge_month IS NOT OLD.charge_month OR NEW.sequence IS NOT OLD.sequence
        BEGIN SELECT RAISE(ABORT, 'a depreciation run keeps its asset, period, month and sequence; schedule a new run instead'); END""",
    """CREATE TRIGGER asset_runs_no_charge_insert BEFORE INSERT ON asset_depreciation_runs
        WHEN NEW.status = 'no_charge' AND (NEW.amount != '0.00' OR NEW.journal_id IS NOT NULL OR NEW.reversal_journal_id IS NOT NULL)
        BEGIN SELECT RAISE(ABORT, 'a no-charge depreciation run has amount 0.00 and never carries a journal'); END""",
    """CREATE TRIGGER asset_runs_no_charge_update BEFORE UPDATE ON asset_depreciation_runs
        WHEN OLD.status = 'no_charge' AND (NEW.amount != '0.00' OR NEW.journal_id IS NOT NULL OR NEW.reversal_journal_id IS NOT NULL OR NEW.status NOT IN ('no_charge','cancelled'))
        BEGIN SELECT RAISE(ABORT, 'a no-charge depreciation run never carries a journal'); END""",
    """CREATE TRIGGER asset_runs_posted_only_reversed BEFORE UPDATE ON asset_depreciation_runs
        WHEN OLD.status = 'posted' AND (NEW.status NOT IN ('posted','reversed') OR NEW.amount != OLD.amount OR NEW.journal_id IS NOT OLD.journal_id)
        BEGIN SELECT RAISE(ABORT, 'a posted depreciation run is corrected by reversal only'); END""",
    """CREATE TRIGGER asset_runs_final_immutable BEFORE UPDATE ON asset_depreciation_runs
        WHEN OLD.status IN ('reversed','cancelled')
        BEGIN SELECT RAISE(ABORT, 'reversed and cancelled depreciation runs are immutable'); END""",
]


class AssetError(RuntimeError):
    """Invalid asset register input or an operation the register's state does not allow."""


# --------------------------------------------------------------------------- #
# Pure helpers                                                                 #
# --------------------------------------------------------------------------- #

def straight_line_schedule(cost, salvage_value, useful_life_months) -> list[Decimal]:
    """Monthly charges: equal cents each month, the final month absorbing the
    rounding residual so that ``sum == cost - salvage`` exactly."""
    n = _life(useful_life_months)
    base = money(cost) - money(salvage_value)
    if base < 0:
        raise AssetError("salvage value cannot exceed cost")
    monthly = money(base / n)
    if monthly * (n - 1) > base:
        # A depreciable base of only a few cents: half-up would overshoot, so round down instead.
        monthly = (base / n).quantize(CENTS, rounding=ROUND_DOWN)
    amounts = [monthly] * (n - 1)
    amounts.append(money(base - monthly * (n - 1)))
    return amounts


def _life(value) -> int:
    if isinstance(value, bool):
        raise AssetError("useful life must be a whole number of months")
    if isinstance(value, int):
        n = value
    elif isinstance(value, str) and value.strip().isdigit():
        n = int(value.strip())
    else:
        raise AssetError(f"useful life must be a whole number of months, got {value!r}")
    if n < 1 or n > MAX_LIFE_MONTHS:
        raise AssetError(f"useful life must be between 1 and {MAX_LIFE_MONTHS} months, got {n}")
    return n


def _parse_date(text, label: str = "date") -> _dt.date:
    if not isinstance(text, str) or len(text) != 10 or text[4] != "-" or text[7] != "-":
        raise AssetError(f"{label} must be YYYY-MM-DD, got {text!r}")
    try:
        return _dt.date.fromisoformat(text)
    except ValueError as exc:
        raise AssetError(f"{label} is not a valid calendar date: {text!r}") from exc


def _month_index(d: _dt.date) -> int:
    return d.year * 12 + d.month


def _month_key(d: _dt.date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def _money(value, label: str, *, allow_zero: bool) -> Decimal:
    try:
        m = money(value)
    except MoneyError as exc:
        raise AssetError(f"{label}: {exc}") from exc
    if m < 0:
        raise AssetError(f"{label} cannot be negative: {fmt(m)}")
    if m == 0 and not allow_zero:
        raise AssetError(f"{label} must be positive")
    return m


# --------------------------------------------------------------------------- #
# Plugin                                                                       #
# --------------------------------------------------------------------------- #

class Plugin:
    def __init__(self, cipher):
        self.c = cipher
        self.db = cipher.db
        self.audit = cipher.audit
        self.ledger = cipher.ledger
        self.approvals = cipher.approvals

    # ---- validation --------------------------------------------------------- #

    def _validate(self, *, project_id, description, cost, salvage_value, in_service_date, useful_life_months, method) -> dict[str, Any]:
        if self.db.one("SELECT id FROM projects WHERE id=?", (project_id,)) is None:
            raise AssetError(f"unknown project {project_id}")
        desc = description.strip() if isinstance(description, str) else ""
        if not desc:
            raise AssetError("asset description is required")
        cost_m = _money(cost, "cost", allow_zero=False)
        salvage_m = _money(salvage_value, "salvage value", allow_zero=True)
        if salvage_m > cost_m:
            raise AssetError(f"salvage value {fmt(salvage_m)} cannot exceed cost {fmt(cost_m)}")
        _parse_date(in_service_date, "in-service date")
        life = _life(useful_life_months)
        if method not in METHODS:
            raise AssetError(f"unsupported depreciation method {method!r}; supported: {', '.join(METHODS)}")
        rec = {
            "project_id": project_id,
            "description": desc,
            "cost": fmt(cost_m),
            "salvage_value": fmt(salvage_m),
            "in_service_date": in_service_date,
            "useful_life_months": life,
            "method": method,
        }
        straight_line_schedule(rec["cost"], rec["salvage_value"], life)  # proves the schedule quantises cleanly
        return rec

    def _period(self, period_id: str) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM periods WHERE id=?", (period_id,))
        if row is None:
            raise AssetError(f"unknown period {period_id}")
        return row

    def _require_open(self, period_id: str) -> dict[str, Any]:
        self._period(period_id)
        return self.ledger.require_open(period_id)  # raises PeriodNotOpen

    def _resolve_period(self, period_id: str | None) -> str:
        return period_id or self.c.current_period()["id"]

    def _latest_journal_period(self, journal_ids) -> dict[str, Any] | None:
        """The latest-starting period holding any of ``journal_ids`` (with the journal), or None."""
        ids = [j for j in journal_ids if j]
        if not ids:
            return None
        return self.db.one(
            f"""SELECT p.id, p.start_date, j.id AS journal_id FROM journals j JOIN periods p ON p.id = j.period_id
                WHERE j.id IN ({','.join('?' * len(ids))}) ORDER BY p.start_date DESC, p.id DESC LIMIT 1""",
            tuple(ids),
        )

    @staticmethod
    def _asset_journals(a: dict[str, Any]) -> list[str]:
        """Every journal on the asset: its capitalization and each run's journal and reversal."""
        return [a["capitalisation_journal_id"], *(r["journal_id"] for r in a["runs"]), *(r["reversal_journal_id"] for r in a["runs"])]

    def _require_not_before(self, target_id: str, journal_ids, what: str) -> None:
        """The ledger's rule for reversals (``journal.reverse``): ``what`` cannot be dated in a
        period starting before the period of any journal it reverses or settles."""
        source = self._latest_journal_period(journal_ids)
        target = self._period(target_id)
        if source is not None and target["start_date"] < source["start_date"]:
            raise AssetError(
                f"{what} cannot be dated before journal {source['journal_id']}: period {target_id} starts {target['start_date']}, "
                f"the journal is in {source['id']} starting {source['start_date']}; use an open period starting on or after {source['start_date']}"
            )

    # ---- register ------------------------------------------------------------ #

    def register_asset(
        self,
        project_id: str,
        description: str,
        cost,
        in_service_date: str,
        useful_life_months,
        salvage_value="0",
        method: str = "straight_line",
        *,
        actor: str,
    ) -> dict[str, Any]:
        rec = self._validate(project_id=project_id, description=description, cost=cost, salvage_value=salvage_value,
                             in_service_date=in_service_date, useful_life_months=useful_life_months, method=method)
        asset_id = new_id("ast")
        now = utcnow_iso()
        content_hash = hash_json(rec)
        with self.db.transaction() as conn:
            self._reject_duplicate_description(conn, rec["project_id"], rec["description"], exclude_id=None)
            conn.execute(
                """INSERT INTO asset_register (id, project_id, description, cost, salvage_value, in_service_date, useful_life_months, method,
                   status, version, content_hash, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,'registered',1,?,?,?)""",
                (asset_id, rec["project_id"], rec["description"], rec["cost"], rec["salvage_value"], rec["in_service_date"],
                 rec["useful_life_months"], rec["method"], content_hash, now, now),
            )
            self.audit.record(actor, "asset.registered", "asset", asset_id, {**rec, "content_hash": content_hash, "version": 1})
        return self.get_asset(asset_id)

    def _reject_duplicate_description(self, conn, project_id: str, description: str, *, exclude_id: str | None) -> None:
        sql = "SELECT id FROM asset_register WHERE project_id=? AND lower(description)=lower(?) AND status != 'disposed'"
        params: list[Any] = [project_id, description]
        if exclude_id:
            sql += " AND id != ?"
            params.append(exclude_id)
        dup = conn.execute(sql, tuple(params)).fetchone()
        if dup is not None:
            raise AssetError(f"an asset described {description!r} is already registered on this project ({dup['id']})")

    def update_asset(self, asset_id: str, actor: str, **fields) -> dict[str, Any]:
        """Edit a registered or active asset.  Bumps the version (invalidating open
        approvals bound to the old one) and cancels unposted runs, whose amounts
        derived from the old parameters.  Blocked while any run is posted; cost is
        frozen once the asset is capitalized."""
        unknown = sorted(set(fields) - set(EDITABLE_FIELDS))
        if unknown:
            raise AssetError(f"unknown asset field(s): {', '.join(unknown)}; editable: {', '.join(EDITABLE_FIELDS)}")
        if not fields:
            raise AssetError("no fields to update")
        with self.db.transaction() as conn:
            a = self.get_asset(asset_id)
            if a["status"] == "disposed":
                raise AssetError(f"asset {asset_id} is disposed and cannot be edited")
            posted = [r["id"] for r in a["runs"] if r["status"] == "posted"]
            if posted:
                raise AssetError(f"asset {asset_id} has posted depreciation ({len(posted)} run(s)); reverse those runs before editing the asset")
            merged = {k: a[k] for k in ASSET_FIELDS}
            merged.update(fields)
            rec = self._validate(**merged)
            changed = {k: rec[k] for k in EDITABLE_FIELDS if rec[k] != a[k]}
            if not changed:
                return a
            if "cost" in changed and a["status"] == "active":
                raise AssetError("cost cannot change after capitalization; dispose the asset and register the correct one")
            if "description" in changed:
                self._reject_duplicate_description(conn, a["project_id"], rec["description"], exclude_id=asset_id)
            version = a["version"] + 1
            content_hash = hash_json(rec)
            now = utcnow_iso()
            conn.execute(
                "UPDATE asset_register SET description=?, cost=?, salvage_value=?, in_service_date=?, useful_life_months=?, method=?, version=?, content_hash=?, updated_at=? WHERE id=?",
                (rec["description"], rec["cost"], rec["salvage_value"], rec["in_service_date"], rec["useful_life_months"], rec["method"], version, content_hash, now, asset_id),
            )
            canceled = []
            for r in a["runs"]:
                if r["status"] in ("draft", "no_charge"):
                    conn.execute(
                        "UPDATE asset_depreciation_runs SET status='cancelled', cancelled_at=?, note=? WHERE id=?",
                        (now, f"canceled: asset changed to version {version}", r["id"]),
                    )
                    self.audit.record(actor, "asset.run_cancelled", "asset_run", r["id"], {"asset_id": asset_id, "reason": "asset changed", "asset_version": version, "previous_status": r["status"]})
                    canceled.append(r["id"])
            self.audit.record(actor, "asset.updated", "asset", asset_id, {"changes": changed, "version": version, "content_hash": content_hash, "cancelled_runs": canceled})
        return self.get_asset(asset_id)

    # ---- reading -------------------------------------------------------------- #

    def get_asset(self, asset_id: str) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM asset_register WHERE id=?", (asset_id,))
        if row is None:
            raise AssetError(f"unknown asset {asset_id}")
        runs = self.db.query("SELECT * FROM asset_depreciation_runs WHERE asset_id=? ORDER BY created_at, id", (asset_id,))
        for r in runs:
            r["stale"] = r["asset_version"] != row["version"]
        cost = money(row["cost"])
        base = cost - money(row["salvage_value"])
        accumulated = total(r["amount"] for r in runs if r["status"] == "posted")
        schedule = straight_line_schedule(row["cost"], row["salvage_value"], row["useful_life_months"])
        row["depreciable_base"] = fmt(base)
        row["monthly_amount"] = fmt(schedule[0])
        row["final_month_amount"] = fmt(schedule[-1])
        row["accumulated_depreciation"] = fmt(accumulated)
        row["remaining_depreciable"] = fmt(max(base - accumulated, ZERO))
        row["net_book_value"] = fmt(ZERO if row["status"] == "disposed" else cost - accumulated)
        row["months_posted"] = sum(1 for r in runs if r["status"] == "posted")
        row["fully_depreciated"] = accumulated >= base
        row["over_depreciated"] = accumulated > base  # must never be True; guarded at scheduling and posting
        row["runs"] = runs
        return row

    def list_assets(self, project_id: str) -> list[dict[str, Any]]:
        rows = self.db.query("SELECT id FROM asset_register WHERE project_id=? ORDER BY created_at, id", (project_id,))
        return [self.get_asset(r["id"]) for r in rows]

    def get_run(self, run_id: str) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM asset_depreciation_runs WHERE id=?", (run_id,))
        if row is None:
            raise AssetError(f"unknown depreciation run {run_id}")
        a = self.db.one("SELECT version, project_id, status FROM asset_register WHERE id=?", (row["asset_id"],))
        row["project_id"] = a["project_id"]
        row["asset_status"] = a["status"]
        row["asset_current_version"] = a["version"]
        row["stale"] = a["version"] != row["asset_version"]
        return row

    def runs(self, asset_id: str) -> list[dict[str, Any]]:
        return self.get_asset(asset_id)["runs"]

    # ---- depreciation runs ------------------------------------------------------ #

    def schedule_run(self, asset_id: str, period_id: str, actor: str) -> dict[str, Any]:
        """Create the run for ``period_id``: a draft carrying its calendar month's charge,
        or a ``no_charge`` run (amount 0.00, never journaled) when the month precedes the
        in-service month, the asset is already fully depreciated, or the schedule has
        ended.  The charge never exceeds what remains of the depreciable base."""
        with self.db.transaction() as conn:
            a = self.get_asset(asset_id)
            if a["status"] != "active":
                raise AssetError(f"asset {asset_id} is {a['status']}; depreciation applies to active (capitalized) assets only")
            period = self._require_open(period_id)
            start = _parse_date(period["start_date"], "period start date")
            end = _parse_date(period["end_date"], "period end date")
            if (start.year, start.month) != (end.year, end.month):
                raise AssetError(f"depreciation runs are monthly; period {period_id} ({period['start_date']}..{period['end_date']}) spans more than one calendar month")
            charge_month = _month_key(start)
            live = conn.execute(
                "SELECT id, status, period_id FROM asset_depreciation_runs WHERE asset_id=? AND charge_month=? AND status IN ('draft','no_charge','posted')",
                (asset_id, charge_month),
            ).fetchone()
            if live is not None:
                where = f"period {live['period_id']}" if live["period_id"] == period_id else f"period {live['period_id']}, which also covers {charge_month}"
                raise AssetError(f"a {live['status']} depreciation run already exists for asset {asset_id} in {charge_month} ({live['id']}, {where}); reverse or cancel it before scheduling another")
            prior = conn.execute(
                "SELECT id FROM asset_depreciation_runs WHERE asset_id=? AND charge_month=? AND status IN ('reversed','cancelled') ORDER BY created_at DESC, id DESC LIMIT 1",
                (asset_id, charge_month),
            ).fetchone()
            replaced_run_id = prior["id"] if prior else None
            in_service = _parse_date(a["in_service_date"], "in-service date")
            sequence = _month_index(start) - _month_index(in_service) + 1
            life = a["useful_life_months"]
            schedule = straight_line_schedule(a["cost"], a["salvage_value"], life)
            base = money(a["depreciable_base"])
            accumulated = money(a["accumulated_depreciation"])
            remaining = base - accumulated
            if sequence < 1:
                amount, status, note = ZERO, "no_charge", "period precedes the in-service month"
            elif remaining <= 0:
                amount, status, note = ZERO, "no_charge", f"asset is fully depreciated ({fmt(accumulated)} of {fmt(base)} posted)"
            elif sequence > life:
                amount, status, note = ZERO, "no_charge", f"schedule ended after month {life}; {fmt(remaining)} remains undepreciated, schedule the missed month instead"
            else:
                amount = schedule[sequence - 1]
                note = ""
                if amount > remaining:
                    note = f"charge clamped from {fmt(amount)} to the remaining depreciable base {fmt(remaining)}"
                    amount = remaining
                if amount <= 0:
                    status, note = "no_charge", "nothing to depreciate this month"
                else:
                    status = "draft"
            content = {
                "asset_id": asset_id, "asset_version": a["version"], "period_id": period_id, "charge_month": charge_month,
                "sequence": sequence, "amount": fmt(amount), "replaced_run_id": replaced_run_id,
            }
            content_hash = hash_json(content)
            run_id = new_id("dep")
            conn.execute(
                """INSERT INTO asset_depreciation_runs (id, asset_id, period_id, charge_month, sequence, amount, asset_version, status, note, content_hash, replaced_run_id, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (run_id, asset_id, period_id, charge_month, sequence, fmt(amount), a["version"], status, note, content_hash, replaced_run_id, utcnow_iso()),
            )
            self.audit.record(actor, "asset.run_scheduled", "asset_run", run_id, {**content, "status": status, "note": note, "content_hash": content_hash})
        return self.get_run(run_id)

    def cancel_run(self, run_id: str, actor: str, reason: str = "") -> dict[str, Any]:
        """Withdraw a draft or no-charge run (posted runs are corrected by reversal)."""
        with self.db.transaction() as conn:
            run = self.get_run(run_id)
            if run["status"] not in ("draft", "no_charge"):
                raise AssetError(f"only draft or no-charge runs can be canceled; run {run_id} is {run['status']}")
            now = utcnow_iso()
            conn.execute("UPDATE asset_depreciation_runs SET status='cancelled', cancelled_at=?, note=? WHERE id=?", (now, f"cancelled: {reason}" if reason else "cancelled", run_id))
            self.audit.record(actor, "asset.run_cancelled", "asset_run", run_id, {"asset_id": run["asset_id"], "reason": reason, "previous_status": run["status"]})
        return self.get_run(run_id)

    # ---- manifests --------------------------------------------------------------- #

    def manifest_for(self, operation: str, subject_id: str, *, actor_role: str) -> dict[str, Any]:
        if operation == "asset.capitalise":
            a = self.get_asset(subject_id)
            return build_manifest(
                operation=operation, subject_type="asset", subject_id=subject_id, actor_role=actor_role,
                amounts={"cost": a["cost"]},
                bindings={**self._asset_bindings(a), "in_service_date": a["in_service_date"], "debit_account": "1500", "credit_account": "1000"},
            )
        if operation == "asset.dispose":
            a = self.get_asset(subject_id)
            posted = [{"run_id": r["id"], "amount": r["amount"], "period_id": r["period_id"], "sequence": r["sequence"]} for r in a["runs"] if r["status"] == "posted"]
            return build_manifest(
                operation=operation, subject_type="asset", subject_id=subject_id, actor_role=actor_role,
                amounts={"cost": a["cost"], "accumulated_depreciation": a["accumulated_depreciation"], "net_book_value": a["net_book_value"]},
                bindings={**self._asset_bindings(a), "posted_runs": len(posted), "runs_hash": hash_json(posted), "open_runs": sum(1 for r in a["runs"] if r["status"] == "draft"),
                          "target_rule": self._target_rule(self._asset_journals(a), "the latest open period")},
            )
        if operation in ("asset.post_depreciation", "asset.reverse_depreciation"):
            run = self.get_run(subject_id)
            a = self.get_asset(run["asset_id"])
            bindings = {
                **self._asset_bindings(a),
                "asset_id": a["id"],
                "run_asset_version": run["asset_version"],
                "run_hash": run["content_hash"],
                "run_status": run["status"],
                "period_id": run["period_id"],
                "charge_month": run["charge_month"],
                "sequence": run["sequence"],
                "journal_id": run["journal_id"],
                "debit_account": "5200",
                "credit_account": "1590",
            }
            if operation == "asset.reverse_depreciation":
                bindings["target_rule"] = self._target_rule([run["journal_id"]], f"the run's period {run['period_id']}")
            return build_manifest(
                operation=operation, subject_type="asset_run", subject_id=subject_id, actor_role=actor_role,
                amounts={"amount": run["amount"]},
                bindings=bindings,
            )
        raise AssetError(f"unknown asset operation {operation}")

    def _target_rule(self, journal_ids, default: str) -> str:
        source = self._latest_journal_period(journal_ids)
        earliest = f" starting on or after {source['start_date']}" if source else ""
        return f"execute with period_id of an open period{earliest} (default: {default})"

    @staticmethod
    def _asset_bindings(a: dict[str, Any]) -> dict[str, Any]:
        return {
            "project_id": a["project_id"],
            "asset_version": a["version"],
            "asset_hash": a["content_hash"],
            "asset_status": a["status"],
            "posting_rule": POSTING_RULE,
        }

    # ---- apply -------------------------------------------------------------------- #

    def apply(self, operation: str, subject_id: str, *, approval_id: str, manifest: dict[str, Any], actor: str, period_id: str | None) -> dict[str, Any]:
        if operation == "asset.capitalise":
            return self._capitalize(subject_id, approval_id=approval_id, actor=actor, period_id=period_id)
        if operation == "asset.post_depreciation":
            return self._post_depreciation(subject_id, approval_id=approval_id, actor=actor, period_id=period_id)
        if operation == "asset.reverse_depreciation":
            return self._reverse_depreciation(subject_id, approval_id=approval_id, actor=actor, period_id=period_id)
        if operation == "asset.dispose":
            return self._dispose(subject_id, approval_id=approval_id, actor=actor, period_id=period_id)
        raise AssetError(f"unknown asset operation {operation}")

    def _capitalize(self, asset_id: str, *, approval_id: str, actor: str, period_id: str | None) -> dict[str, Any]:
        with self.db.transaction() as conn:
            a = self.get_asset(asset_id)
            if a["status"] != "registered":
                raise AssetError(f"asset {asset_id} is {a['status']}; only a registered asset can be capitalized")
            pid = self._resolve_period(period_id)
            self._require_open(pid)
            j = self.ledger.post(
                period_id=pid,
                description=f"Capitalize asset: {a['description']}",
                lines=[
                    {"account": "1500", "debit": a["cost"], "project_id": a["project_id"], "memo": f"asset {asset_id}"},
                    {"account": "1000", "credit": a["cost"], "project_id": a["project_id"], "memo": f"synthetic purchase of asset {asset_id}"},
                ],
                source_type="asset", source_id=asset_id, source_version=str(a["version"]), posted_by=actor, approval_id=approval_id,
            )
            now = utcnow_iso()
            conn.execute(
                "UPDATE asset_register SET status='active', capitalisation_journal_id=?, capitalisation_approval_id=?, capitalised_at=?, updated_at=? WHERE id=?",
                (j["id"], approval_id, now, now, asset_id),
            )
            self.audit.record(actor, "asset.capitalised", "asset", asset_id, {"journal_id": j["id"], "approval_id": approval_id, "cost": a["cost"], "period_id": pid, "asset_version": a["version"]})
        return {"asset": asset_id, "status": "active", "journal_id": j["id"], "cost": a["cost"], "period_id": pid}

    def _post_depreciation(self, run_id: str, *, approval_id: str, actor: str, period_id: str | None) -> dict[str, Any]:
        with self.db.transaction() as conn:
            run = self.get_run(run_id)
            a = self.get_asset(run["asset_id"])
            if run["status"] == "no_charge":
                raise AssetError(f"run {run_id} is a no-charge run ({run['note']}); there is nothing to post")
            if run["status"] != "draft":
                raise AssetError(f"run {run_id} is {run['status']}; only a draft run can be posted")
            if run["stale"]:
                raise AssetError(f"asset {a['id']} changed (version {run['asset_version']} -> {a['version']}) after run {run_id} was scheduled; cancel and reschedule it")
            if a["status"] != "active":
                raise AssetError(f"asset {a['id']} is {a['status']}; depreciation applies to active assets only")
            if period_id and period_id != run["period_id"]:
                raise AssetError(f"run {run_id} belongs to period {run['period_id']}, not {period_id}")
            self._require_open(run["period_id"])
            amount = money(run["amount"])
            if amount <= 0:
                raise AssetError(f"run {run_id} has no positive amount to post")
            # Re-check against the register at posting time: whatever the draft says, the
            # posted total can never exceed cost - salvage.
            base = money(a["depreciable_base"])
            accumulated = money(a["accumulated_depreciation"])
            if accumulated + amount > base:
                raise AssetError(
                    f"posting run {run_id} for {fmt(amount)} would over-depreciate asset {a['id']}: "
                    f"{fmt(accumulated)} already posted of a {fmt(base)} depreciable base ({fmt(base - accumulated)} remaining); cancel and reschedule the run"
                )
            j = self.ledger.post(
                period_id=run["period_id"],
                description=f"Depreciation month {run['sequence']} of {a['useful_life_months']}: {a['description']}",
                lines=[
                    {"account": "5200", "debit": amount, "project_id": a["project_id"], "memo": f"asset {a['id']} run {run_id}"},
                    {"account": "1590", "credit": amount, "project_id": a["project_id"], "memo": f"asset {a['id']} run {run_id}"},
                ],
                source_type="asset_run", source_id=run_id, source_version=str(run["asset_version"]), posted_by=actor, approval_id=approval_id,
            )
            conn.execute(
                "UPDATE asset_depreciation_runs SET status='posted', journal_id=?, approval_id=?, posted_at=? WHERE id=?",
                (j["id"], approval_id, utcnow_iso(), run_id),
            )
            self.audit.record(actor, "asset.depreciation_posted", "asset_run", run_id, {"asset_id": a["id"], "journal_id": j["id"], "approval_id": approval_id, "amount": fmt(amount), "period_id": run["period_id"], "sequence": run["sequence"]})
        return {"run": run_id, "asset": a["id"], "status": "posted", "journal_id": j["id"], "amount": fmt(amount), "period_id": run["period_id"], "sequence": run["sequence"]}

    def _reverse_depreciation(self, run_id: str, *, approval_id: str, actor: str, period_id: str | None) -> dict[str, Any]:
        with self.db.transaction() as conn:
            run = self.get_run(run_id)
            a = self.get_asset(run["asset_id"])
            if run["status"] != "posted":
                raise AssetError(f"run {run_id} is {run['status']}; only a posted run can be reversed")
            if a["status"] == "disposed":
                raise AssetError(f"asset {a['id']} is disposed; its depreciation was settled by the disposal journal and cannot be reversed")
            pid = period_id or run["period_id"]
            self._require_open(pid)
            self._require_not_before(pid, [run["journal_id"]], f"the reversal of depreciation run {run_id}")
            j = self.ledger.reverse(run["journal_id"], period_id=pid, posted_by=actor, reason=f"depreciation run {run_id} reversed", approval_id=approval_id)
            conn.execute(
                "UPDATE asset_depreciation_runs SET status='reversed', reversal_journal_id=?, reversal_approval_id=?, reversed_at=? WHERE id=?",
                (j["id"], approval_id, utcnow_iso(), run_id),
            )
            self.audit.record(actor, "asset.depreciation_reversed", "asset_run", run_id, {"asset_id": a["id"], "journal_id": run["journal_id"], "reversal_journal_id": j["id"], "approval_id": approval_id, "amount": run["amount"], "period_id": pid})
        return {"run": run_id, "asset": a["id"], "status": "reversed", "journal_id": run["journal_id"], "reversal_journal_id": j["id"], "amount": run["amount"], "period_id": pid}

    def _dispose(self, asset_id: str, *, approval_id: str, actor: str, period_id: str | None) -> dict[str, Any]:
        with self.db.transaction() as conn:
            a = self.get_asset(asset_id)
            if a["status"] != "active":
                raise AssetError(f"asset {asset_id} is {a['status']}; only an active asset can be disposed")
            drafts = [r["id"] for r in a["runs"] if r["status"] == "draft"]
            if drafts:
                raise AssetError(f"cancel the outstanding draft depreciation run(s) before disposal: {', '.join(drafts)}")
            pid = self._resolve_period(period_id)
            self._require_open(pid)
            self._require_not_before(pid, self._asset_journals(a), f"the disposal of asset {asset_id}")
            cost = money(a["cost"])
            accumulated = money(a["accumulated_depreciation"])
            if accumulated > cost:
                raise AssetError(f"asset {asset_id} is over-depreciated ({fmt(accumulated)} against cost {fmt(cost)}); reverse the excess depreciation before disposal")
            book_value = cost - accumulated
            lines = []
            if accumulated > 0:
                lines.append({"account": "1590", "debit": accumulated, "project_id": a["project_id"], "memo": f"asset {asset_id} accumulated depreciation written off"})
            if book_value > 0:
                lines.append({"account": "5200", "debit": book_value, "project_id": a["project_id"], "memo": f"asset {asset_id} remaining book value expensed"})
            lines.append({"account": "1500", "credit": cost, "project_id": a["project_id"], "memo": f"asset {asset_id} cost derecognized"})
            j = self.ledger.post(
                period_id=pid,
                description=f"Dispose asset: {a['description']}",
                lines=lines,
                source_type="asset", source_id=asset_id, source_version=str(a["version"]), posted_by=actor, approval_id=approval_id,
            )
            now = utcnow_iso()
            conn.execute(
                "UPDATE asset_register SET status='disposed', disposal_journal_id=?, disposal_approval_id=?, disposed_at=?, updated_at=? WHERE id=?",
                (j["id"], approval_id, now, now, asset_id),
            )
            self.audit.record(actor, "asset.disposed", "asset", asset_id, {"journal_id": j["id"], "approval_id": approval_id, "cost": fmt(cost), "accumulated_depreciation": fmt(accumulated), "net_book_value": fmt(book_value), "period_id": pid, "asset_version": a["version"]})
        return {"asset": asset_id, "status": "disposed", "journal_id": j["id"], "cost": fmt(cost), "accumulated_depreciation": fmt(accumulated), "net_book_value": fmt(book_value), "period_id": pid}

    # ---- state ---------------------------------------------------------------------- #

    def state(self, project_id: str) -> dict[str, Any]:
        assets = self.list_assets(project_id)
        active = [a for a in assets if a["status"] == "active"]
        cost_total = total(a["cost"] for a in active)
        accumulated_total = total(a["accumulated_depreciation"] for a in active)
        fixed_assets = self.ledger.balance("1500", project_id=project_id)
        contra = self.ledger.account_activity("1590", project_id=project_id)
        accumulated_ledger = money(contra["credit"] - contra["debit"])
        return {
            "assets": assets,
            "totals": {
                "cost": fmt(cost_total),
                "accumulated_depreciation": fmt(accumulated_total),
                "net_book_value": fmt(cost_total - accumulated_total),
                "registered": sum(1 for a in assets if a["status"] == "registered"),
                "active": len(active),
                "disposed": sum(1 for a in assets if a["status"] == "disposed"),
            },
            "ledger": {"fixed_assets": fmt(fixed_assets), "accumulated_depreciation": fmt(accumulated_ledger)},
            # register agrees with the ledger AND is internally sound (no asset depreciated past its base)
            "reconciled": cost_total == fixed_assets and accumulated_total == accumulated_ledger and not any(a["over_depreciated"] for a in assets),
            "posting_rule": POSTING_RULE,
        }

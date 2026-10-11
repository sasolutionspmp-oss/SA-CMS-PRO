"""Project cost forecast: budget, authorised commitments, pending exposure, billed and paid."""
from __future__ import annotations

from typing import Any

from ..core.db import Database
from ..core.money import ZERO, fmt, money, total
from .commitments import Commitments
from .ledger import Ledger


class Forecast:
    def __init__(self, db: Database, commitments: Commitments, ledger: Ledger):
        self.db = db
        self.commitments = commitments
        self.ledger = ledger

    def project(self, project_id: str) -> dict[str, Any]:
        project = self.db.one("SELECT * FROM projects WHERE id=?", (project_id,))
        if project is None:
            raise KeyError(project_id)
        budget = money(project["budget"])
        executed = self.commitments.executed_total(project_id)
        pending = self.commitments.pending_exposure(project_id)
        forecast = executed + pending
        bills = self.db.query(
            "SELECT b.commitment_id, MAX(b.sequence) AS seq FROM bills b JOIN commitments c ON c.id=b.commitment_id WHERE c.project_id=? AND b.status IN ('posted','paid') GROUP BY b.commitment_id",
            (project_id,),
        )
        billed_net = ZERO
        billed_gross = ZERO
        retainage_held = ZERO
        for row in bills:
            b = self.db.one("SELECT cumulative_net, cumulative_gross, cumulative_retainage FROM bills WHERE commitment_id=? AND sequence=?", (row["commitment_id"], row["seq"]))
            billed_net += money(b["cumulative_net"])
            billed_gross += money(b["cumulative_gross"])
            retainage_held += money(b["cumulative_retainage"])
        paid = self.db.query(
            "SELECT p.amount FROM payment_intents p LEFT JOIN bills b ON b.id=p.bill_id LEFT JOIN commitments c ON c.id=b.commitment_id WHERE p.status IN ('accepted','settled') AND (c.project_id=? OR p.bill_id IS NULL)",
            (project_id,),
        )
        paid_total = total(p["amount"] for p in paid) if paid else ZERO
        ar = self.db.one("SELECT COALESCE(MAX(certified_cumulative),'0.00') AS certified FROM prime_bills WHERE project_id=? AND status IN ('posted','sent','collected')", (project_id,))
        return {
            "project_id": project_id,
            "budget": fmt(budget),
            "executed_commitments": fmt(executed),
            "pending_exposure": fmt(pending),
            "forecast_at_completion": fmt(forecast),
            "variance_to_budget": fmt(budget - forecast),
            "over_budget": forecast > budget,
            "billed_gross_to_date": fmt(billed_gross),
            "billed_net_to_date": fmt(billed_net),
            "retainage_held": fmt(retainage_held),
            "paid_to_date": fmt(paid_total),
            "cost_posted_to_date": fmt(self.ledger.balance("5000", project_id=project_id)),
            "stored_materials_asset": fmt(self.ledger.balance("1300", project_id=project_id)),
            "prime_certified_to_date": fmt(money(ar["certified"])),
            "label": "SHADOW - synthetic prototype, not authoritative",
        }

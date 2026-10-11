"""Supplier progress bills: cumulative certification, retainage, stored materials.

Posting rule (fixture policy ``cipher-posting-rules/1``, controller-approved
for the synthetic prototype only):

* transfer of stored material to installed:  Dr project cost / Cr stored asset
* new installed cost this period:            Dr project cost
* newly stored eligible material:            Dr stored asset
* amount currently payable:                  Cr accounts payable
* retainage withheld this period:            Cr retainage payable

Stored material is never billed twice: a lot's remaining balance is reduced by
every transfer and the transferred value appears inside cumulative installed.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from ..core.approvals import build_manifest
from ..core.audit import Audit
from ..core.db import Database
from ..core.ids import hash_json, new_id, utcnow_iso
from ..core.money import ZERO, fmt, money, pct, total
from .commitments import Commitments
from .ledger import Ledger


class BillError(RuntimeError):
    pass


class Bills:
    def __init__(self, db: Database, audit: Audit, commitments: Commitments, ledger: Ledger):
        self.db = db
        self.audit = audit
        self.commitments = commitments
        self.ledger = ledger

    # ---- stored materials ------------------------------------------------- #

    def add_stored_material(self, *, commitment_id: str, sov_line_id: str, description: str, eligible_amount: str | Decimal, evidence_hash: str, location: str = "", actor: str) -> dict[str, Any]:
        amt = money(eligible_amount)
        if amt <= 0:
            raise BillError("stored material must have a positive eligible amount")
        if not evidence_hash:
            raise BillError("stored material requires title/control/location evidence (hash)")
        c = self.commitments.get(commitment_id)
        if c["status"] != "executed":
            raise BillError("stored material applies to executed commitments only")
        if not any(s["id"] == sov_line_id for s in c["sov"]):
            raise BillError("SOV line does not belong to this commitment")
        lot_id = new_id("lot")
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT INTO stored_material_lots (id, commitment_id, sov_line_id, description, eligible_amount, remaining_amount, evidence_hash, location, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (lot_id, commitment_id, sov_line_id, description, fmt(amt), fmt(amt), evidence_hash, location, utcnow_iso()),
            )
            self.audit.record(actor, "stored_material.added", "stored_material_lot", lot_id, {"commitment_id": commitment_id, "sov_line_id": sov_line_id, "eligible_amount": fmt(amt), "evidence_hash": evidence_hash})
        return self.lot(lot_id)

    def lot(self, lot_id: str) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM stored_material_lots WHERE id=?", (lot_id,))
        if row is None:
            raise BillError(f"unknown stored material lot {lot_id}")
        return row

    def lots(self, commitment_id: str) -> list[dict[str, Any]]:
        return self.db.query("SELECT * FROM stored_material_lots WHERE commitment_id=? ORDER BY created_at", (commitment_id,))

    # ---- certification ------------------------------------------------------ #

    def latest(self, commitment_id: str) -> dict[str, Any] | None:
        row = self.db.one("SELECT * FROM bills WHERE commitment_id=? AND status != 'void' ORDER BY sequence DESC LIMIT 1", (commitment_id,))
        return self.get(row["id"]) if row else None

    def certify(
        self,
        *,
        commitment_id: str,
        period_id: str,
        installed: list[dict[str, Any]],
        transfers: list[dict[str, Any]] | None = None,
        actor: str,
    ) -> dict[str, Any]:
        """Create a draft bill.

        ``installed``: ``[{"sov_line_id", "cumulative_installed"}]`` cumulative value installed per line,
        including any stored material transferred to installed this period.
        ``transfers``: ``[{"lot_id", "amount"}]`` stored-material value moved to installed this period.
        Lots added since the previous bill are counted as stored material automatically.
        """
        transfers = transfers or []
        c = self.commitments.get(commitment_id)
        if c["status"] != "executed":
            raise BillError("bills apply to executed commitments only")
        self.ledger.require_open(period_id)
        prior = self.latest(commitment_id)
        if prior and prior["status"] == "draft":
            raise BillError("the previous bill is still a draft; approve, post or void it first")
        prior_lines = {ln["sov_line_id"]: ln for ln in (prior["lines"] if prior else [])}
        sov = {s["id"]: s for s in c["sov"]}

        rate = Decimal(c["retainage_rate"])
        # transfers
        transfer_total = ZERO
        lot_updates: list[tuple[str, Decimal]] = []
        lots = {l["id"]: l for l in self.lots(commitment_id)}
        for t in transfers:
            lot = lots.get(t["lot_id"])
            if lot is None:
                raise BillError(f"lot {t['lot_id']} does not belong to this commitment")
            amt = money(t["amount"])
            if amt <= 0 or amt > money(lot["remaining_amount"]):
                raise BillError(f"transfer {fmt(amt)} exceeds remaining stored value {lot['remaining_amount']} on lot {lot['id']}")
            lot_updates.append((lot["id"], money(lot["remaining_amount"]) - amt))
            lots[lot["id"]] = {**lot, "remaining_amount": fmt(money(lot["remaining_amount"]) - amt)}
            transfer_total += amt

        # installed per line
        lines_out = []
        cumulative_installed = ZERO
        prior_cum_installed = ZERO
        seen = set()
        for item in installed:
            sid = item["sov_line_id"]
            if sid not in sov:
                raise BillError(f"SOV line {sid} does not belong to this commitment")
            if sid in seen:
                raise BillError(f"SOV line {sid} listed twice")
            seen.add(sid)
            cum = money(item["cumulative_installed"])
            prev = money(prior_lines[sid]["cumulative_installed"]) if sid in prior_lines else ZERO
            if cum < prev:
                raise BillError(f"cumulative installed on line {sov[sid]['line_no']} cannot decrease ({fmt(prev)} -> {fmt(cum)})")
            if cum > money(sov[sid]["amount"]):
                raise BillError(f"cumulative installed {fmt(cum)} exceeds SOV line {sov[sid]['line_no']} value {sov[sid]['amount']}")
            lines_out.append({"sov_line_id": sid, "cumulative_installed": cum, "prior_installed": prev, "installed_this_period": cum - prev})
            cumulative_installed += cum
            prior_cum_installed += prev
        for sid, pl in prior_lines.items():
            if sid not in seen:
                prev = money(pl["cumulative_installed"])
                lines_out.append({"sov_line_id": sid, "cumulative_installed": prev, "prior_installed": prev, "installed_this_period": ZERO})
                cumulative_installed += prev
                prior_cum_installed += prev
        installed_this_period = cumulative_installed - prior_cum_installed
        if installed_this_period < transfer_total:
            raise BillError("installed value this period must include every stored-material transfer")

        # stored
        cumulative_stored = total(l["remaining_amount"] for l in lots.values()) if lots else ZERO
        prior_stored = money(prior["cumulative_stored"]) if prior else ZERO
        stored_added = cumulative_stored - prior_stored + transfer_total
        if stored_added < 0:
            raise BillError("stored material cannot decrease without a transfer")

        cumulative_gross = cumulative_installed + cumulative_stored
        cumulative_retainage = pct(cumulative_gross, rate)
        cumulative_net = cumulative_gross - cumulative_retainage
        prior_net = money(prior["cumulative_net"]) if prior else ZERO
        prior_ret = money(prior["cumulative_retainage"]) if prior else ZERO
        amount_due = cumulative_net - prior_net
        retainage_this_period = cumulative_retainage - prior_ret
        if amount_due < 0:
            raise BillError("amount due would be negative; use a credit workflow instead")
        if cumulative_gross > money(c["executed_amount"]):
            raise BillError(f"cumulative gross {fmt(cumulative_gross)} exceeds executed commitment {c['executed_amount']}")

        sequence = (prior["sequence"] + 1) if prior else 1
        content = {
            "commitment_id": commitment_id, "commitment_version": c["version"], "period_id": period_id, "sequence": sequence,
            "lines": [{k: (fmt(v) if isinstance(v, Decimal) else v) for k, v in ln.items()} for ln in lines_out],
            "transfers": [{"lot_id": t["lot_id"], "amount": fmt(money(t["amount"]))} for t in transfers],
            "cumulative_installed": fmt(cumulative_installed), "cumulative_stored": fmt(cumulative_stored),
            "cumulative_gross": fmt(cumulative_gross), "cumulative_retainage": fmt(cumulative_retainage),
            "cumulative_net": fmt(cumulative_net), "prior_net": fmt(prior_net), "amount_due": fmt(amount_due),
        }
        content_hash = hash_json(content)
        bill_id = new_id("bill")
        with self.db.transaction() as conn:
            conn.execute(
                """INSERT INTO bills (id, commitment_id, period_id, sequence, status, cumulative_installed, cumulative_stored, cumulative_gross,
                   cumulative_retainage, cumulative_net, prior_net, amount_due, retainage_this_period, installed_this_period,
                   stored_added_this_period, stored_transferred_this_period, commitment_version, content_hash, created_at)
                   VALUES (?,?,?,?,'draft',?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    bill_id, commitment_id, period_id, sequence, fmt(cumulative_installed), fmt(cumulative_stored), fmt(cumulative_gross),
                    fmt(cumulative_retainage), fmt(cumulative_net), fmt(prior_net), fmt(amount_due), fmt(retainage_this_period),
                    fmt(installed_this_period), fmt(stored_added), fmt(transfer_total), c["version"], content_hash, utcnow_iso(),
                ),
            )
            for ln in lines_out:
                conn.execute(
                    "INSERT INTO bill_lines (id, bill_id, sov_line_id, cumulative_installed, prior_installed, installed_this_period, stored_added, stored_transferred) VALUES (?,?,?,?,?,?,?,?)",
                    (new_id("bln"), bill_id, ln["sov_line_id"], fmt(ln["cumulative_installed"]), fmt(ln["prior_installed"]), fmt(ln["installed_this_period"]), "0.00", "0.00"),
                )
            for lot_id, remaining in lot_updates:
                conn.execute("UPDATE stored_material_lots SET remaining_amount=? WHERE id=?", (fmt(remaining), lot_id))
            for t in transfers:
                conn.execute("INSERT INTO bill_transfers (id, bill_id, lot_id, amount) VALUES (?,?,?,?)", (new_id("btr"), bill_id, t["lot_id"], fmt(money(t["amount"]))))
            self.audit.record(actor, "bill.certified", "bill", bill_id, {"commitment_id": commitment_id, "sequence": sequence, "amount_due": fmt(amount_due), "retainage_this_period": fmt(retainage_this_period), "content_hash": content_hash})
        return self.get(bill_id)

    def get(self, bill_id: str) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM bills WHERE id=?", (bill_id,))
        if row is None:
            raise BillError(f"unknown bill {bill_id}")
        row["lines"] = self.db.query("SELECT * FROM bill_lines WHERE bill_id=? ORDER BY id", (bill_id,))
        row["transfers"] = self.db.query("SELECT lot_id, amount FROM bill_transfers WHERE bill_id=?", (bill_id,))
        c = self.db.one("SELECT version, supplier_id, project_id FROM commitments WHERE id=?", (row["commitment_id"],))
        row["commitment_current_version"] = c["version"]
        row["supplier_id"] = c["supplier_id"]
        row["project_id"] = c["project_id"]
        row["stale"] = c["version"] != row["commitment_version"]
        return row

    def list(self, commitment_id: str | None = None, project_id: str | None = None) -> list[dict[str, Any]]:
        if commitment_id:
            rows = self.db.query("SELECT id FROM bills WHERE commitment_id=? ORDER BY sequence", (commitment_id,))
        elif project_id:
            rows = self.db.query("SELECT b.id FROM bills b JOIN commitments c ON c.id=b.commitment_id WHERE c.project_id=? ORDER BY b.created_at", (project_id,))
        else:
            rows = self.db.query("SELECT id FROM bills ORDER BY created_at")
        return [self.get(r["id"]) for r in rows]

    def void(self, bill_id: str, *, actor: str, reason: str) -> dict[str, Any]:
        with self.db.transaction() as conn:
            b = self.get(bill_id)
            if b["status"] != "draft":
                raise BillError("only draft bills can be voided; posted bills are corrected by reversal")
            # restore lot balances consumed by this draft's transfers
            for t in conn.execute("SELECT lot_id, amount FROM bill_transfers WHERE bill_id=?", (bill_id,)).fetchall():
                lot = self.lot(t["lot_id"])
                conn.execute("UPDATE stored_material_lots SET remaining_amount=? WHERE id=?", (fmt(money(lot["remaining_amount"]) + money(t["amount"])), t["lot_id"]))
            conn.execute("UPDATE bills SET status='void' WHERE id=?", (bill_id,))
            self.audit.record(actor, "bill.voided", "bill", bill_id, {"reason": reason})
        return self.get(bill_id)

    # ---- approval and posting ---------------------------------------------- #

    def manifest(self, bill_id: str, *, actor_role: str) -> dict[str, Any]:
        b = self.get(bill_id)
        supplier = self.db.one("SELECT * FROM parties WHERE id=?", (b["supplier_id"],))
        return build_manifest(
            operation="bill.approve",
            subject_type="bill",
            subject_id=bill_id,
            actor_role=actor_role,
            amounts={"amount_due": b["amount_due"], "retainage_this_period": b["retainage_this_period"], "cumulative_gross": b["cumulative_gross"]},
            bindings={
                "commitment_id": b["commitment_id"],
                "commitment_version": b["commitment_current_version"],
                "bill_version": b["commitment_version"],
                "bill_hash": b["content_hash"],
                "period_id": b["period_id"],
                "sequence": b["sequence"],
                "posting_rule": "cipher-posting-rules/1",
            },
            destination={"party_id": supplier["id"], "destination": supplier["destination"], "destination_version": supplier["destination_version"]},
        )

    def post(self, bill_id: str, *, approval_id: str, actor: str) -> dict[str, Any]:
        """Approve and post the bill's journal(s).  The caller has consumed ``approval_id``."""
        with self.db.transaction() as conn:
            b = self.get(bill_id)
            if b["status"] != "draft":
                raise BillError(f"bill {bill_id} is {b['status']}")
            if b["stale"]:
                raise BillError("the commitment changed after this bill was certified; re-certify it")
            self.ledger.require_open(b["period_id"])
            journal_ids = []
            transferred = money(b["stored_transferred_this_period"])
            if transferred > 0:
                j = self.ledger.post(
                    period_id=b["period_id"],
                    description=f"Stored material transferred to installed, bill {b['sequence']}",
                    lines=[
                        {"account": "5000", "debit": transferred, "project_id": b["project_id"], "party_id": b["supplier_id"], "memo": "stored -> installed"},
                        {"account": "1300", "credit": transferred, "project_id": b["project_id"], "party_id": b["supplier_id"], "memo": "stored -> installed"},
                    ],
                    source_type="bill", source_id=bill_id, source_version=str(b["commitment_version"]), posted_by=actor, approval_id=approval_id,
                )
                journal_ids.append(j["id"])
            new_cost = money(b["installed_this_period"]) - transferred
            stored_added = money(b["stored_added_this_period"])
            lines = []
            if new_cost > 0:
                lines.append({"account": "5000", "debit": new_cost, "project_id": b["project_id"], "party_id": b["supplier_id"], "memo": "installed work"})
            if stored_added > 0:
                lines.append({"account": "1300", "debit": stored_added, "project_id": b["project_id"], "party_id": b["supplier_id"], "memo": "eligible stored material"})
            if money(b["amount_due"]) > 0:
                lines.append({"account": "2000", "credit": b["amount_due"], "project_id": b["project_id"], "party_id": b["supplier_id"], "memo": f"bill {b['sequence']}"})
            if money(b["retainage_this_period"]) > 0:
                lines.append({"account": "2050", "credit": b["retainage_this_period"], "project_id": b["project_id"], "party_id": b["supplier_id"], "memo": "retainage withheld"})
            journal = self.ledger.post(
                period_id=b["period_id"],
                description=f"Supplier bill {b['sequence']} on commitment {b['commitment_id']}",
                lines=lines,
                source_type="bill", source_id=bill_id, source_version=str(b["commitment_version"]), posted_by=actor, approval_id=approval_id,
            )
            journal_ids.append(journal["id"])
            conn.execute("UPDATE bills SET status='posted', approval_id=?, journal_id=? WHERE id=?", (approval_id, journal["id"], bill_id))
            self.audit.record(actor, "bill.posted", "bill", bill_id, {"approval_id": approval_id, "journals": journal_ids, "amount_due": b["amount_due"]})
        return self.get(bill_id)

    def mark_paid(self, bill_id: str, *, actor: str, intent_id: str) -> None:
        with self.db.transaction() as conn:
            conn.execute("UPDATE bills SET status='paid' WHERE id=? AND status='posted'", (bill_id,))
            self.audit.record(actor, "bill.paid", "bill", bill_id, {"intent_id": intent_id})

    # ---- retainage release --------------------------------------------------- #

    def release_retainage(self, *, commitment_id: str, period_id: str, approval_id: str, actor: str) -> dict[str, Any]:
        """After closeout acceptance, move withheld retainage into ordinary payables."""
        c = self.commitments.get(commitment_id)
        held = self.ledger.balance("2050", party_id=c["supplier_id"], project_id=c["project_id"])
        if held <= 0:
            raise BillError("no retainage is held for this commitment")
        j = self.ledger.post(
            period_id=period_id,
            description=f"Retainage release on commitment {commitment_id}",
            lines=[
                {"account": "2050", "debit": held, "project_id": c["project_id"], "party_id": c["supplier_id"], "memo": "retainage released"},
                {"account": "2000", "credit": held, "project_id": c["project_id"], "party_id": c["supplier_id"], "memo": "retainage now payable"},
            ],
            source_type="retainage_release", source_id=commitment_id, source_version=str(c["version"]), posted_by=actor, approval_id=approval_id,
        )
        self.audit.record(actor, "retainage.released", "commitment", commitment_id, {"amount": fmt(held), "journal_id": j["id"], "approval_id": approval_id})
        return {"commitment_id": commitment_id, "amount": fmt(held), "journal_id": j["id"]}

    def retainage_manifest(self, commitment_id: str, *, actor_role: str) -> dict[str, Any]:
        c = self.commitments.get(commitment_id)
        held = self.ledger.balance("2050", party_id=c["supplier_id"], project_id=c["project_id"])
        return build_manifest(
            operation="retainage.release",
            subject_type="commitment",
            subject_id=commitment_id,
            actor_role=actor_role,
            amounts={"retainage_held": held},
            bindings={"commitment_version": c["version"], "closeout_required": True},
            destination={"party_id": c["supplier_id"], "destination": c["supplier"]["destination"], "destination_version": c["supplier"]["destination_version"]},
        )

    # ---- subledger ------------------------------------------------------------- #

    def ap_open_items(self, project_id: str | None = None) -> dict[str, Any]:
        """Open AP derived from posted bills less settled payments, reconciled to the AP control account."""
        sql = "SELECT b.*, c.project_id AS pid, c.supplier_id AS sid FROM bills b JOIN commitments c ON c.id=b.commitment_id WHERE b.status IN ('posted','paid')"
        params: tuple = ()
        if project_id:
            sql += " AND c.project_id=?"
            params = (project_id,)
        items = []
        open_total = ZERO
        for b in self.db.query(sql, params):
            paid = self.db.query("SELECT amount FROM payment_intents WHERE bill_id=? AND status IN ('accepted','settled')", (b["id"],))
            paid_total = total(p["amount"] for p in paid) if paid else ZERO
            open_amt = money(b["amount_due"]) - paid_total
            items.append({"bill_id": b["id"], "supplier_id": b["sid"], "sequence": b["sequence"], "amount_due": b["amount_due"], "paid": fmt(paid_total), "open": fmt(open_amt)})
            open_total += open_amt
        released = self.db.query("SELECT source_id FROM journals WHERE source_type='retainage_release'")
        release_total = ZERO
        for r in released:
            c = self.db.one("SELECT project_id, supplier_id FROM commitments WHERE id=?", (r["source_id"],))
            if project_id and c["project_id"] != project_id:
                continue
            amt = self.ledger.account_activity("2050", party_id=c["supplier_id"], project_id=c["project_id"])["debit"]
            paid = self.db.query("SELECT amount FROM payment_intents WHERE bill_id IS NULL AND party_id=? AND status IN ('accepted','settled') AND note LIKE 'retainage%'", (c["supplier_id"],))
            paid_total = total(p["amount"] for p in paid) if paid else ZERO
            release_total += amt - paid_total
            items.append({"bill_id": None, "supplier_id": c["supplier_id"], "sequence": None, "amount_due": fmt(amt), "paid": fmt(paid_total), "open": fmt(amt - paid_total), "kind": "retainage_release"})
        control = self.ledger.control_balance("ap", project_id=project_id) if project_id else self.ledger.control_balance("ap")
        subledger = money(open_total + release_total)
        return {"items": items, "subledger_total": fmt(subledger), "control_balance": fmt(control), "reconciled": subledger == control}

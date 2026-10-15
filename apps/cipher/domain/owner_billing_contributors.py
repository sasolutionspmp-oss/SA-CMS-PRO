"""Pure proofs for bounded native synthetic AR collections and returns.

These historical records prove Cipher's local bookkeeping. They do not prove an
external settlement or authorize a new receipt. Other contributor classes are
held explicitly by the owner-billing facade until their source routes qualify.
No imports register schema or select a provider.
"""
from decimal import Decimal

from ..core.ids import canonical_json, loads, parse_iso
from ..core.money import fmt


def _same(left, right):
    return canonical_json(left) == canonical_json(right)


def prove_collections(owner, source):
    from .owner_billing import OwnerBillingError
    error = OwnerBillingError
    db, bill = owner.db, source["bill"]
    rows = db.query("SELECT * FROM collections WHERE prime_bill_id=? ORDER BY received_at,id", (bill["id"],))
    births = db.query("SELECT * FROM audit_log WHERE action='collection.recorded' AND entity_type='collection' AND json_extract(payload_json,'$.prime_bill_id')=? ORDER BY seq", (bill["id"],))
    events = {event["entity_id"]: event for event in births}
    if len(events) != len(births) or {row["id"] for row in rows} != set(events):
        raise error("owner collection inventory lost an original record or gained an unaudited allocation")
    ids = set(events)
    if any(any(record["id"] in ids and record["table"] == "collections" for record in group["records"])
           for group in owner.c.receivables.receipt_reference_conflicts()):
        raise error("owner collection reference conflicts with another original receipt")

    def journal_proof(identifier, *, source_type, reference, period_id, actor, description, expected_lines):
        journal = owner.c.ledger.journal(identifier)
        original = owner._event("journal.posted", "journal", identifier)
        expected_payload = {"period_id": period_id, "source_type": source_type, "source_id": reference,
                            "source_version": "1", "total": fmt(sum(Decimal(row["debit"]) for row in expected_lines)),
                            "approval_id": None, "reversal_of": None, "line_count": len(expected_lines)}
        actual_lines = [{key: line[key] for key in ("account_code", "debit", "credit", "project_id", "party_id", "memo")} for line in journal["lines"]]
        if (not _same(actual_lines, expected_lines) or not _same(loads(original["payload_json"]), expected_payload)
                or journal["source_type"] != source_type or journal["source_id"] != reference or journal["source_version"] != "1"
                or journal["rule_version"] != "cipher-posting-rules/1" or journal["description"] != description
                or journal["period_id"] != period_id or journal["posted_by"] != actor or original["actor"] != actor
                or journal["approval_id"] is not None or journal["reversal_of"] is not None
                or type(journal["line_count"]) is not int or journal["line_count"] != len(expected_lines)
                or not 0 <= (parse_iso(original["ts"]) - parse_iso(journal["posted_at"])).total_seconds() <= 1):
            raise error("owner historical collection journal differs from its original exact source")
        actual_ids = {row["id"] for row in db.query("SELECT id FROM journals WHERE source_type=? AND source_id=? AND reversal_of IS NULL", (source_type, reference))}
        birth_ids = [row["entity_id"] for row in db.query("SELECT entity_id FROM audit_log WHERE action='journal.posted' AND entity_type='journal' AND json_extract(payload_json,'$.source_type')=? AND json_extract(payload_json,'$.source_id')=? AND json_extract(payload_json,'$.reversal_of') IS NULL ORDER BY seq", (source_type, reference))]
        if actual_ids != {identifier} or birth_ids != [identifier]:
            raise error("owner historical collection journal inventory changed")
        # A governed inverse route is a separate current qualification. Preserve
        # original receipts while explicitly holding these current variants.
        inverse = db.one("SELECT id FROM journals WHERE reversal_of=?", (identifier,))
        inverse_birth = db.one("SELECT seq FROM audit_log WHERE action='journal.reversed' AND entity_type='journal' AND entity_id=?", (identifier,))
        if inverse is not None or inverse_birth is not None:
            raise error("owner collection journal reversals need a separately qualified current contributor route")
        return {"header": {key: value for key, value in journal.items() if key not in ("lines", "reversed_by")},
                "lines": journal["lines"], "event": {"seq": original["seq"], "hash": original["entry_hash"]}}

    def line(account, debit, credit, memo):
        return {"account_code": account, "debit": fmt(debit), "credit": fmt(credit),
                "project_id": bill["project_id"], "party_id": bill["customer_id"], "memo": memo}

    proved, received = [], Decimal("0")
    for row in rows:
        event = events[row["id"]]
        payload = loads(event["payload_json"])
        amount, fee = Decimal(row["amount"]), Decimal(row["fee"])
        if row["method"] not in ("check", "wire") or row["mandate_id"] is not None:
            raise error("this bounded owner standing route admits historical synthetic check/wire receipts; ACH mandate qualification remains separate")
        expected = {"prime_bill_id": bill["id"], "retainage_invoice_id": None, "amount": row["amount"], "fee": row["fee"],
                    "journal_id": row["journal_id"], "method": row["method"], "mandate_ref": None,
                    "provider_ref": row["provider_ref"], "period_id": payload.get("period_id"), "settlement_date": row["settlement_date"]}
        if (not _same(payload, expected) or amount <= 0 or fee < 0 or fee >= amount
                or fmt(amount) != row["amount"] or fmt(fee) != row["fee"]
                or row["settlement_date"] < bill["invoice_date"]
                or not 0 <= (parse_iso(event["ts"]) - parse_iso(row["received_at"])).total_seconds() <= 1):
            raise error("owner historical collection differs from its original audited allocation")
        period = owner._period(payload["period_id"])
        if period["startDate"] < source["record"]["period"]["startDate"]:
            raise error("owner historical collection period predates the original bill")
        memo = "check deposit (simulated)" if row["method"] == "check" else "wire receipt (simulated)"
        lines = [line("1000", amount-fee, 0, memo)]
        if fee:
            lines.append(line("6000", fee, 0, "processing fee"))
        lines.append(line("1100", 0, amount, f"prime bill {bill['sequence']} collected"))
        original = journal_proof(row["journal_id"], source_type="collection", reference=row["provider_ref"], period_id=period["id"],
                                 actor=event["actor"], description=f"Collection on prime bill {bill['sequence']}", expected_lines=lines)
        returns = db.query("SELECT * FROM audit_log WHERE action='collection.returned' AND entity_type='collection' AND entity_id=? ORDER BY seq", (row["id"],))
        returned = None
        if returns:
            if len(returns) != 1 or row["status"] != "returned" or row["return_journal_id"] is None or row["returned_at"] is None:
                raise error("owner return history differs from its original collection lifecycle")
            returned_event = returns[0]
            returned_payload = loads(returned_event["payload_json"])
            expected_return = {"reason": returned_payload.get("reason"), "journal_id": row["return_journal_id"],
                               "original_journal_id": row["journal_id"], "period_id": returned_payload.get("period_id")}
            if (not _same(returned_payload, expected_return) or type(returned_payload.get("reason")) is not str
                    or not returned_payload["reason"].strip() or returned_event["seq"] <= event["seq"]
                    or not 0 <= (parse_iso(returned_event["ts"]) - parse_iso(row["returned_at"])).total_seconds() <= 1):
                raise error("owner collection return differs from its original audited act")
            return_period = owner._period(returned_payload["period_id"])
            if return_period["startDate"] < period["startDate"]:
                raise error("owner return period predates its original collection")
            returned = journal_proof(row["return_journal_id"], source_type="collection_return", reference=row["provider_ref"],
                period_id=return_period["id"], actor=returned_event["actor"],
                description=f"Returned collection {row['provider_ref']}: {returned_payload['reason']}",
                expected_lines=[line("1100", amount, 0, "receivable restored"), line("1000", 0, amount, "bank return")])
        elif row["status"] != "received" or row["return_journal_id"] is not None or row["returned_at"] is not None:
            raise error("owner collection has an unaudited returned status")
        if returned is None:
            received += amount
        proved.append({"record": row, "birth": {"seq": event["seq"], "hash": event["entry_hash"]},
                       "journal": original, "return": returned, "qualification": "historical_synthetic_native_record"})
    if fmt(received) != bill["received"]:
        raise error("owner current received total differs from its original proven contributor history")
    return {"records": proved, "received": fmt(received)}

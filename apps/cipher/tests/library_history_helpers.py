"""Build genuine shipped75 histories from the unchanged catalog and native APIs."""
import json
from pathlib import Path
import sqlite3
from unittest.mock import patch
from uuid import uuid4

from apps.cipher.core import db as core_db
from apps.cipher.core.ids import hash_json
from apps.cipher.domain import owner_billing
from apps.cipher import ar_receipts
from apps.cipher.accounting_worker import WorkerHeld
from apps.cipher.service import Cipher
from apps.cipher.tests.ar_history_helpers import inventory, original73_catalog
from apps.cipher.tests import test_ar_namespace as ar_tests

ORIGINAL75_HASH = "0b65915a8926593f21dbd2881166fb1ddff2684aac6ccdf955750fa5c5dac479"


def original75_catalog():
    catalog = [*original73_catalog(), (74, owner_billing.SCHEMA_NAME, owner_billing.SCHEMA_STATEMENTS),
               (75, ar_receipts.SCHEMA_NAME, ar_receipts.SCHEMA_STATEMENTS)]
    assert hash_json(catalog) == ORIGINAL75_HASH
    return catalog


def produce_genuine75_history(path, output):
    with patch.object(core_db, "SCHEMA_CATALOG", original75_catalog()):
        return _produce(path, output)


def _produce(path, output):
    assert hash_json(core_db.SCHEMA_CATALOG) == ORIGINAL75_HASH
    world = ar_tests.ARNamespaceTests("runTest")
    world.setUp()
    c = world.c
    try:
        people = c.plugin("people")
        for login in ("practice.accountant", "practice.reviewer"):
            if login == "practice.reviewer":
                people.add_membership(login, world.ar_project, actor="practice.bootstrap")
            draft = people.request_grant(login, "accountant", project_id=world.ar_project,
                reason="Synthetic original75 independent AR review and posting", actor="practice.bootstrap")
            requester = "practice.reviewer" if login == "practice.accountant" else "practice.accountant"
            approval = c.request_approval("people.grant_role", draft["id"], actor_role="owner", requested_by=requester)
            c.approve(approval["id"], approver="practice.bootstrap", approver_role="owner")
            c.execute(approval["id"], actor="practice.bootstrap")
        reviewer = people.person_for("practice.reviewer")["id"]
        originals = []
        def act(person, action, resource, body=None):
            body = {} if body is None else body
            review = world.ar_preflight.review(person, action, resource, body)
            assert review["allowed"], review
            request = {"person_id": person, "action": action, "resource_id": resource,
                "body": {**body, "fingerprint": review["fingerprint"]}, "repeatability_key": str(uuid4()),
                "if_match": review["resourceVersion"]}
            result = world.ar.run(**request)
            originals.append((result, request))
            return result["result"]
        bill = act(world.person, "ownerBill.prepare", world.basis, world.ar_input)["billId"]
        financial = act(world.person, "ownerBill.requestApproval", bill)["approvalId"]
        act(reviewer, "ownerBill.approve", financial)
        assert c.approvals.get(financial)["status"] == "granted"
        act(world.person, "ownerBill.post", bill)
        send = act(world.person, "ownerBill.requestSend", bill)["approvalId"]
        act(reviewer, "ownerBill.approveSend", send)
        act(world.person, "ownerBill.send", send)
        collection = c.receivables.record_collection(prime_bill_id=bill, period_id="2026-10", amount="100.00", fee="0",
            method="check", provider_ref="SIM-GENUINE75-LIBRARY-UPGRADE", actor="practice.accountant")
        for result, request in originals:
            assert world.ar.run(**request) == {**result, "replayed": True, "effectApplied": False}
        world.ap.run(**world.ap_request())
        world.runner.run(**world.commercial_request())
        worker = world.accounting_request()
        with patch("apps.cipher.accounting_worker.invoke_bound_worker", side_effect=WorkerHeld("Synthetic original75 pending reservation")):
            pending = world.accounting.run(**worker)
        assert pending["state"] == "reserved"
        assert world.worker._adapter.calls == {"submit": 0, "lookup": 0, "read_record": 0}
        assert c.provider.submissions == []
        assert c.audit.verify_chain()["ok"]
        with sqlite3.connect(path) as destination:
            c.db.conn.backup(destination)
        world.doCleanups()
        c = Cipher(str(path))
        assert c.db.read_only and not c.db.has_write_authority()
        c.db.claim_write_authority(approver="synthetic.library.upgrade.owner",
            reason="Attested owned original75 library upgrade qualification",
            approval_ref="SYNTHETIC-GENUINE75-LIBRARY-UPGRADE")
        billing = c.plugin("owner_billing")
        baseline = {"catalogHash": hash_json(core_db.SCHEMA_CATALOG), "schemaCount": len(core_db.SCHEMA_CATALOG),
            "billId": bill, "collectionId": collection["id"], "nativeBill": c.receivables.get(bill),
            "ownerSource": billing.source_proof(bill), "posting": billing.posting_receipt(bill),
            "send": billing.send_proof(bill), "workerReservation": c.db.query("SELECT * FROM ap_accounting_invocations"),
            "tables": inventory(c), "objects": c.db.query("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name")}
        Path(output).write_text(json.dumps(baseline, sort_keys=True, indent=2) + "\n")
    finally:
        c.db.close()
        world.doCleanups()

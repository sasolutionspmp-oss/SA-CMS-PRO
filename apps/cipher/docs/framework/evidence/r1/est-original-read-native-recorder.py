"""Opt-in isolated CompanyC original-baseline read/rights qualification.

Run inside the qualified Frappe runtime, from bench/sites, with three arguments:
site, private est-generated identity fixture, private prior continuation capture.
No new acceptance/command intent, User/Auth/Role/native-master changes or HTTP
claims. Only the isolated reviewer's supported native UOM restrictions change
temporarily, with restoration in finally and independent native readback.
"""
from contextlib import contextmanager
import hashlib
import inspect
import json
from pathlib import Path
import sys
from unittest.mock import patch
from uuid import uuid4

import frappe


def main(site, private_fixture, private_continuation):
    from cipher_aec.api.contracts import digest
    from cipher_aec.api.errors import DomainError
    from cipher_aec.documents import provenance
    from cipher_aec.estimating import company_api
    from cipher_aec.tests.test_estimating_generated_acceptance import (
        _load, _save, _source_snapshot, _timed_rpc, set_generated_unit_visibility,
    )
    fixture, prior = _load(private_fixture), _load(private_continuation)
    company = fixture["company"]
    assert prior["company"] == company and fixture.get("identity_marker")
    baseline = prior["baseline"]
    before_count = frappe.db.count("Cipher Estimate Acceptance", {"estimate_revision": baseline["estimate_revision"]})
    rpc = _timed_rpc(fixture)
    observed, graph_counts = [], []
    actual_graph = provenance.read_graph
    restricted = False

    @contextmanager
    def graph(actor, scope):
        with actual_graph(actor, scope):
            try:
                yield
            finally:
                graph_counts.append(provenance.read_graph_stats())

    def read(role, denied=False):
        frappe.set_user(fixture["users"][role]["user"])
        rpc.role = role
        status = "returned"
        try:
            with patch.object(provenance, "read_graph", graph):
                value = rpc.observe_read("native-public-Company-get_record." + role,
                    lambda: inspect.unwrap(company_api.get_record)(company=company, kind="acceptance", record_id=baseline["id"]))
            assert not denied
            assert value == baseline and digest(value) == digest(baseline)
        except DomainError as error:
            if not denied or error.code != "not_found":
                raise
            status = "denied:not_found"
        finally:
            frappe.db.rollback()
        observed.append({"role": role, "status": status, "exact_original_digest": digest(baseline) if not denied else None,
            "metrics": rpc.timings[-1], "graph_counts": graph_counts[-1]})

    try:
        read("author")
        assert graph_counts[-1].get("original_proof_hits", 0) > 0
        assert graph_counts[-1]["prelocked_scopes"] == 0
        read("reviewer")
        frappe.set_user("Administrator")
        isolation = set_generated_unit_visibility(private_fixture, True)
        restricted = True
        read("reviewer", denied=True)
        read("author")
        frappe.set_user("Administrator")
        restoration = set_generated_unit_visibility(private_fixture, False)
        restricted = False
        read("reviewer")
        frappe.set_user("Administrator")
        assert frappe.db.count("Cipher Estimate Acceptance", {"estimate_revision": baseline["estimate_revision"]}) == before_count == 1
        assert not frappe.db.exists("User Permission", {"user": fixture["users"]["reviewer"]["user"], "allow": "UOM"})
        assert all(frappe.has_permission("UOM", "read", doc=frappe.get_doc("UOM", fixture["native_units"][name]), user=fixture["users"]["reviewer"]["user"]) for name in ("count", "sf"))
        assert rpc.source_snapshot == _source_snapshot()
        assert all(row["source_generation_stable"] for row in rpc.timings)
        result = {"schema": "cipher.est.original-read.native.v1", "status": "passed", "company": company,
            "qualification": "Actual native Frappe/ERPNext/MariaDB public business get_record, canonical fixture identities; not cookie/CSRF HTTP, new acceptance timing or p95/workload qualification.",
            "baseline_id": baseline["id"], "baseline_digest": digest(baseline), "exact_original_body_unchanged": True,
            "new_acceptance_intent_or_effect_created": False, "read_profiles": observed,
            "mandatory_isolation": isolation, "restoration": restoration,
            "independent_native_permission_readback": {"reviewer_uom_restriction_rows": 0, "count_read": True, "area_read": True},
            "source_snapshot_start": rpc.source_snapshot, "source_snapshot_end": _source_snapshot(),
            "recorder_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "generated_public_gate_enabled": False, "live_model_qualified": False, "external_provider_qualified": False}
        target = _save("est-generated-original-read-native-" + uuid4().hex + ".json", result)
        print(json.dumps({"status": "passed", "private_result": target, "read_profiles": observed, "native_permission_restored": True}))
    finally:
        if restricted:
            frappe.set_user("Administrator")
            set_generated_unit_visibility(private_fixture, False)
        rpc.close()


if __name__ == "__main__":
    frappe.init(site=sys.argv[1])
    frappe.connect()
    frappe.set_user("Administrator")
    try:
        main(*sys.argv[1:])
    finally:
        frappe.db.rollback()
        frappe.destroy()

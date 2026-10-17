"""Opt-in existing-effect native replay/read observation; never a fresh consume.

Run from bench/sites with site, isolated identity fixture and the preserved
est-generated-memo-qualified result. No new business intent, rights or master
mutation. Receipt replay retains the existing command's ordinary transaction.
Read phases refuse FOR UPDATE and use the existing 8s/10k instrumentation cap.
"""
from contextlib import contextmanager
import hashlib
import inspect
import json
import os
from pathlib import Path
import sys
from unittest.mock import patch
from uuid import uuid4

import frappe


def main(site, private_fixture, private_prior):
    from cipher_aec.api.contracts import digest
    from cipher_aec.api.errors import DomainError
    from cipher_aec.api import company as company_history
    from cipher_aec.documents import provenance
    from cipher_aec.estimating import company_api, sources
    from cipher_aec.governance import context as authority, permissions as company_permissions
    from cipher_aec.tests.test_estimating_generated_acceptance import _load, _source_snapshot, _timed_rpc

    fixture, prior = _load(private_fixture), _load(private_prior)
    company, baseline = fixture["company"], prior["baseline"]
    assert prior["company"] == company and fixture.get("identity_marker")
    entry, = [row for row in prior["operations"] if row["method"] == "cipher_aec.api.company_approvals.execute_packet"]
    assert entry["role"] == "author" and entry["payload"]["company"] == company
    assert entry["payload"]["operation_id"] == "184271b9-d705-4951-8a4e-9d54d23db886"
    assert baseline["id"] == "cf2065ff-37e6-4bac-be56-02ed7d047c8a"
    receipt_id = digest({"person": fixture["users"]["author"]["person"], "operation_id": entry["payload"]["operation_id"]})

    def inventory():
        # Administrator readback is an invariant observation, not a public
        # authorization result; retain exact private event identity inventory.
        frappe.set_user("Administrator")
        rows = frappe.db.sql("SELECT name,event,subject_type,subject_id,event_hash FROM `tabCipher History Event` WHERE company=%s AND scope_type='Company' AND (project IS NULL OR project='') ORDER BY name", (company,), as_dict=True)
        original = frappe.db.get_value("Cipher Estimate Acceptance", baseline["id"], ["data_json", "record_digest"], as_dict=True)
        assert original and json.loads(original.data_json) == baseline and original.record_digest == digest(baseline)
        value = {"events": [dict(row) for row in rows], "acceptance_digest": original.record_digest,
            "acceptance_count": frappe.db.count("Cipher Estimate Acceptance", {"estimate_revision": baseline["estimate_revision"]}),
            "consumption_count": frappe.db.count("Cipher Approval Consumption", {"packet": baseline["packet_id"]}),
            "receipt_count": frappe.db.count("Cipher Command Receipt", {"name": receipt_id}),
            "company_project_count": frappe.db.count("Project", {"company": company})}
        frappe.db.rollback()
        return value

    before = inventory()
    assert before["acceptance_count"] == before["consumption_count"] == before["receipt_count"] == 1
    assert before["company_project_count"] == 0
    assert not frappe.db.exists("User Permission", {"user": fixture["users"]["reviewer"]["user"], "allow": "UOM"})
    frappe.db.rollback()
    rpc = _timed_rpc(fixture, phase_profile=True)
    observations, graphs = [], []
    original_graph = provenance.read_graph
    marker = uuid4().hex
    journal_paths = []

    def durable_save(name, value):
        target = Path(frappe.get_site_path("private", "cipher-fixtures", name)).resolve()
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as stream:
            json.dump(value, stream, indent=2, default=str)
            stream.flush()
            os.fsync(stream.fileno())
        return str(target)

    @contextmanager
    def graph(*args, **kwargs):
        with original_graph(*args, **kwargs):
            try:
                yield
            finally:
                graphs.append(provenance.read_graph_stats())

    def checkpoint():
        target = durable_save("est-recorded-performance-stage-" + marker + "-" + str(len(journal_paths)) + ".json", {
            "status": "bounded-observations-in-progress", "company": company,
            "original_execute": entry, "baseline_id": baseline["id"],
            "timing_journal_path": rpc.timing_path,
            "observations": observations, "profiles": rpc.timings, "graph_counters": graphs,
            "source_snapshot_start": rpc.source_snapshot, "source_snapshot_current": _source_snapshot()})
        journal_paths.append(target)
        return target

    def read(label, callback):
        rpc.login("author")
        status, value = "returned", None
        try:
            with patch.object(provenance, "read_graph", graph):
                value = rpc.observe_read(label, callback)
        except DomainError as error:
            if error.code != "fixture_profile_budget":
                raise
            status = "fixed-budget-exceeded-no-complete-result"
        finally:
            frappe.db.rollback()
        observations.append({"phase": label, "status": status, "complete_result": value,
            "metrics": rpc.timings[-1], "not_fresh_consume": True})
        checkpoint()
        return value

    try:
        checkpoint()  # Persist the already-successful exact UUID before send.

        def native_guard_parity():
            # Observe the actual Frappe engine and installed hook. Wrappers
            # count and call through; no permission decision is overridden.
            counts = {"guard_authority": 0, "direct_hook_authority": 0, "bridge_success": 0, "bridge_fallback": 0}
            actual_authority = authority.read_company_authority
            actual_consume = company_permissions._consume_company_native_read
            def guard_authority(*args, **kwargs):
                counts["guard_authority"] += 1
                return actual_authority(*args, **kwargs)
            def hook_authority(*args, **kwargs):
                counts["direct_hook_authority"] += 1
                return actual_authority(*args, **kwargs)
            def consume(*args, **kwargs):
                value = actual_consume(*args, **kwargs)
                counts["bridge_success" if value is True else "bridge_fallback"] += 1
                return value
            actor = authority.current_actor()
            assert actor.user == fixture["users"]["author"]["user"] and actor.user != "Administrator"
            with patch.object(authority, "read_company_authority", guard_authority), patch.object(company_permissions, "read_company_authority", hook_authority), patch.object(company_permissions, "_consume_company_native_read", consume):
                record = authority.require_company(company, ability="document.read", actor=actor)
                assert counts == {"guard_authority": 1, "direct_hook_authority": 0, "bridge_success": 1, "bridge_fallback": 0}, counts
                assert authority._company_native_read.get() is None
                assert frappe.has_permission("Company", ptype="read", doc=record, user=actor.user)
                assert counts == {"guard_authority": 1, "direct_hook_authority": 1, "bridge_success": 1, "bridge_fallback": 1}, counts
            return {"actual_native_engine_and_installed_hook": True, "fresh_authority_counts": counts,
                "direct_native_permission_after_guard_still_rechecks_sql": True,
                "native_engine_decisions_overridden": False}

        read("actual-Frappe-Company-native-hook-parity.lockFalse", native_guard_parity)
        rpc.login("author")
        # Fixture-only admission; the product gate remains false. Completed
        # receipt authorization must still check exact originals/current rights.
        with patch.object(sources, "GENERATED_INPUTS_QUALIFIED", True):
            replay = rpc.invoke(entry["method"], entry["payload"])
        assert replay["operation"]["replayed"] and replay["effect"]["acceptance"] == baseline
        observations.append({"phase": "locked-original-only-successful-receipt-replay", "status": "returned",
            "exact_operation_id": entry["payload"]["operation_id"], "metrics": rpc.timings[-1], "not_fresh_consume": True})
        checkpoint()
        read_value = read("public-Company-baseline-GET.lockFalse", lambda: inspect.unwrap(company_api.get_record)(company=company, kind="acceptance", record_id=baseline["id"]))
        if read_value is not None:
            assert read_value == baseline and digest(read_value) == digest(baseline)

        def full_history():
            page = inspect.unwrap(company_history.history)(company=company, limit=200, count_mode="exact")
            items, cursor, total = list(page["items"]), page["next_cursor"], page["total"]
            seen = set()
            while cursor:
                assert cursor not in seen and len(seen) < 50
                seen.add(cursor)
                page = inspect.unwrap(company_history.history)(company=company, limit=200, cursor=cursor, count_mode="none")
                items.extend(page["items"])
                cursor = page["next_cursor"]
            assert len(items) == total
            return {"items": items, "exact_visible_total": total, "native_candidate_inventory_count": len(before["events"])}

        read("full-Company-history.lockFalse.exact-visible-count", full_history)
        after = inventory()
        assert after == before
        assert rpc.source_snapshot == _source_snapshot()
        result = {"schema": "cipher.est.recorded-performance.native.v1", "status": "observations-recorded",
            "qualification": "Native synthetic Sessions; existing exact-UUID locked receipt replay and separate nonlocking public business reads. No fresh consume, HTTP, workload or p95 qualification.",
            "new_acceptance_intent_or_effect_created": False, "permissions_or_native_masters_changed": False,
            "company": company, "baseline_id": baseline["id"], "baseline_digest": digest(baseline),
            "original_execute": entry, "inventory_before": before, "inventory_after": after,
            "observations": observations, "profiles": rpc.timings, "graph_counters": graphs,
            "durable_stage_journals": journal_paths,
            "source_snapshot_start": rpc.source_snapshot, "source_snapshot_end": _source_snapshot(),
            "recorder_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "generated_public_gate_enabled": False, "live_model_qualified": False, "external_provider_qualified": False}
        target = durable_save("est-recorded-performance-native-" + marker + ".json", result)
        print(json.dumps({"status": result["status"], "private_result": target, "profiles": rpc.timings}))
    finally:
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

"""Pure rejection tests for ordinary acceptance fact checks; no native calls."""
from copy import deepcopy
from datetime import datetime, timezone
import unittest

from cipher_aec.api.contracts import canonical_json, digest
from cipher_aec.ricky.company_contracts import DeterministicReadRequest
from cipher_aec.ricky.company_service import CompanyReadService
from cipher_aec.ricky.contracts import canonical
from cipher_aec.tests.test_estimating_core import identity
from cipher_aec.tests.test_ricky_company_service import CompanyFixtureBoundary, CompanyFixtureStore
from cipher_aec.tests.ricky_company_central_acceptance import (
    TYPES, START, CANCEL, verify_metadata_preservation, verify_native_projections, verify_shared_receipts)


class CompanyAcceptanceFactTests(unittest.TestCase):
    def metadata(self):
        control = {"schema": "cipher.ricky.metadata-preservation.v1", "site": "isolated.invalid", "before": {}, "after": {}, "installed": {}}
        for dt in TYPES:
            row = {"name": dt + "-old", "project": "Actual Project", "data_json": '{"preserve": true}', "counter": 1}
            columns = list(row)
            control["before"][dt] = {"columns": columns, "rows": [row]}
            control["after"][dt] = {"columns": columns + ["scope_type"], "rows": [{**row, "scope_type": "Project"}]}
            control["installed"][dt] = {"scope_type": {"fieldtype": "Select", "options": "Project\nCompany", "default": "Project", "reqd": 1, "read_only": 1},
                "project": {"reqd": 0, "mandatory_depends_on": "eval:doc.scope_type == 'Project'"}}
        return control
    def manifest(self):
        return {"company": "Explicit EST fixture", "users": {"author": {"user": "fixture@example.invalid", "person": "native-person"}}}
    def projection(self):
        m = self.manifest();m["native_projection_observations"] = [{"user": "fixture@example.invalid", "person": "native-person", "company": "Explicit EST fixture", "doctype": TYPES[0],
            "known_company_ids": ["private-run"], "before": {"ids": ["old-project-run"], "count": 1}, "after": {"ids": ["old-project-run"], "count": 1},
            "company_query_ids": [], "company_query_count": 0, "company_read_permissions": [{"id": "private-run", "allowed": False}]}]
        return m
    def receipt(self, cancel=False):
        backend = CompanyFixtureBoundary();store = CompanyFixtureStore(backend.events)
        service = CompanyReadService(store, backend, clock=lambda: datetime(2026, 10, 16, tzinfo=timezone.utc))
        request = DeterministicReadRequest(identity("pursuit"), "aec.pursuit.lookup", canonical({}))
        initial = service.start_read("Explicit EST fixture", request.binding(), identity("company-operation"))
        run = store.get("run", initial["id"]);backend.receipts[run["start_receipt"]] = run["id"]
        if cancel:initial = service.cancel(run["company"], run["id"])
        operation = {"id": identity("cancel-operation" if cancel else "company-operation"), "status": "succeeded", "replayed": False}
        replay = {**deepcopy(initial), "operation": {**operation, "replayed": True}}
        stored = {"result_json": canonical_json(initial), "result_hash": digest(initial)}
        m = {"company": run["company"], "users": {"author": {"user": backend.actor.user, "person": backend.actor.person_id}}}
        m["shared_receipt_observations"] = [{"user": backend.actor.user, "person": backend.actor.person_id, "company": run["company"], "run_id": run["id"], "operation_id": operation["id"],
            "command": CANCEL if cancel else START, "initial": {**initial, "operation": operation}, "replay": replay, "operation_read": deepcopy(replay),
            "stored_receipt": {"before": stored, "after": deepcopy(stored)}}]
        return m
    def test_six_metadata_old_columns_json_and_project_defaults(self):
        self.assertEqual(verify_metadata_preservation(self.metadata())["original_rows_preserved"], 6)
    def test_metadata_rejects_type_change_json_rewrite_default_omission_and_row_loss(self):
        for change in (lambda c:c["after"][TYPES[0]]["rows"][0].update(counter=True),
                lambda c:c["after"][TYPES[0]]["rows"][0].update(data_json='{"preserve":true}'),
                lambda c:c["after"][TYPES[0]]["rows"][0].update(scope_type=""),
                lambda c:c["after"][TYPES[0]].update(rows=[]),
                lambda c:c["installed"][TYPES[0]]["scope_type"].update(reqd=True)):
            c = self.metadata();change(c)
            with self.assertRaises(AssertionError):verify_metadata_preservation(c)
    def test_native_legacy_projection_and_company_zero_count(self):
        self.assertEqual(verify_native_projections(self.projection())["observations"], 1)
    def test_native_leaks_unknown_actor_missing_read_or_legacy_change_refuse(self):
        for change in (lambda r:r.update(user="other"), lambda r:r.update(company_query_count=1),
                lambda r:r.update(company_query_count=False), lambda r:r.update(company_read_permissions=[]),
                lambda r:r["company_read_permissions"][0].update(allowed=True),
                lambda r:r["after"].update(ids=[], count=0)):
            m = self.projection();change(m["native_projection_observations"][0])
            with self.assertRaises(AssertionError):verify_native_projections(m)
    def test_start_and_narrow_stop_replays_match_exact_saved_bytes(self):
        for cancel in (False, True):
            self.assertEqual(verify_shared_receipts(self.receipt(cancel))["receipts"], 1)
    def test_receipt_identity_body_type_and_stored_bytes_are_independent_controls(self):
        from jsonschema import ValidationError
        for change in (lambda r:r["operation_read"].update(id=identity("other-run")),
                lambda r:r["replay"]["operation"].update(replayed=1),
                lambda r:r["stored_receipt"]["after"].update(result_json=r["stored_receipt"]["after"]["result_json"] + " "),
                lambda r:r["stored_receipt"]["after"].update(result_hash="0"*64)):
            m = self.receipt();change(m["shared_receipt_observations"][0])
            with self.assertRaises((AssertionError, ValidationError)):verify_shared_receipts(m)
    def test_stop_rejects_source_or_result_fields(self):
        from jsonschema import ValidationError
        m = self.receipt(True);m["shared_receipt_observations"][0]["replay"]["result"] = {"private": True}
        with self.assertRaises(ValidationError):verify_shared_receipts(m)

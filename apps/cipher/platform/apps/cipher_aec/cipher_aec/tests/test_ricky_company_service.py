"""Explicit host fixtures for Company strategy; no native DB/runtime claim."""
import ast
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from cipher_aec.ricky.aec_backend import AECBackend
from cipher_aec.ricky.aec_contracts import SourceReference
from cipher_aec.api.errors import DomainError
from cipher_aec.ricky.company_backend import (CompanyBackend, RunAECReader, validate_manifest,
    validate_resource_plan)
from cipher_aec.ricky.company_contracts import CompanyAuthority, DeterministicReadRequest, REQUEST_SCHEMA
from cipher_aec.ricky.company_records import admission_pair, validate_company_record
from cipher_aec.ricky.company_service import CompanyReadService, CompanyExecution, read_registry, validate_start_receipt
from cipher_aec.ricky.contracts import RickyError, canonical, digest
from cipher_aec.ricky.engine import RickyService
from cipher_aec.ricky.storage import CompanyStore, DOCTYPES
from cipher_aec.ricky.tools import default_registry
from cipher_aec.tests.test_ricky import FixtureStore, FixtureBackend, FixtureAdapter
from cipher_aec.tests.test_ricky_aec_tools import FixtureReader
from cipher_aec.tests.test_estimating_core import identity


class CompanyFixtureStore(FixtureStore):
    def __init__(self, events):
        super().__init__(); self.events = events

    def get(self, kind, identifier, lock=False):
        if lock and kind == "run": self.events.append("Run")
        return super().get(kind, identifier, lock)

    def insert(self, kind, value):
        validate_company_record(kind, value, self)
        return super().insert(kind, value)

    def save(self, kind, value):
        validate_company_record(kind, value, self, before=self.get(kind, value["id"]))
        return super().save(kind, value)

    def read_original(self, domain, kind, identifier):
        return deepcopy(self.originals[kind, identifier])


class NativeLinkError(Exception):
    pass


class NativeRow(dict):
    __getattr__ = dict.__getitem__
    __setattr__ = dict.__setitem__


class NativeLinkCompanyStore(CompanyStore):
    """Actual storage methods with schema-driven, pre-controller native Links.

    This models Frappe's insert/save Link checks without a site or mock import.
    In particular, a new document cannot link to its own unpersisted name.
    """
    find, count = FixtureStore.find, FixtureStore.count
    read_original = CompanyFixtureStore.read_original

    def __init__(self, events):
        self.events, self.rows, self.native = events, {}, {}
        self.after_insert = None
        self.worker = False
        self.frappe = SimpleNamespace(get_doc=self.document, db=SimpleNamespace(sql=self.sql))
        path = Path(__file__).parents[1] / "ricky" / "records.py"
        controller = next(node for node in ast.parse(path.read_text()).body
            if isinstance(node, ast.ClassDef) and node.name == "RickyRecord")
        method = next(node for node in controller.body if isinstance(node, ast.FunctionDef) and node.name == "validate")
        namespace = {"__package__": "cipher_aec.ricky", "json": json,
            "require_trusted_write": lambda: None, "DomainError": DomainError}
        exec(compile(ast.Module(body=[method], type_ignores=[]), str(path), "exec"), namespace)
        self.validate_controller = namespace["validate"]

    @contextmanager
    def _trusted(self):
        yield

    def admission_lock(self, person):
        pass

    def sql(self, query, parameters, *, as_dict=False):
        doctype = next(name for name in DOCTYPES.values() if "`tab" + name + "`" in query)
        value = self.native.get((doctype, parameters[0]))
        return [NativeRow(deepcopy(value))] if value is not None else []

    def document(self, value, identifier=None, **kwargs):
        fields = deepcopy(value if type(value) is dict else self.native[value, identifier])
        store = self

        class Document(NativeRow):
            def persist(self, *, inserting):
                metadata = Path(__file__).parents[1] / "cipher_ricky" / "doctype"
                name = self.doctype.lower().replace(" ", "_")
                schema = json.loads((metadata / name / (name + ".json")).read_text())
                for field in schema["fields"]:
                    target = self.get(field["fieldname"])
                    if field["fieldtype"] != "Link" or not target:
                        continue
                    exists = (field["options"], target) in store.native
                    if field["options"] == "Company": exists = target == "Explicit EST fixture"
                    if field["options"] == "User": exists = target == "author@example.test"
                    if not exists:
                        raise NativeLinkError((self.doctype, field["fieldname"], target))
                kind = next(kind for kind, name in DOCTYPES.items() if name == self.doctype)
                row = json.loads(self.data_json)
                self.validate_record()
                store.native[self.doctype, self.name] = deepcopy(dict(self))
                store.rows[kind, self.name] = row
                store.events.append(("insert" if inserting else "save", kind, self.name, self.run_id))

            def insert(self, *, ignore_permissions, set_name):
                if self.name != set_name or (self.doctype, self.name) in store.native:
                    raise AssertionError("A native insert requires its distinct exact name")
                self.persist(inserting=True)
                if store.after_insert: store.after_insert(self)

            def save(self, *, ignore_permissions):
                self.persist(inserting=False)

            def get_doc_before_save(self):
                old = store.native.get((self.doctype, self.name))
                return SimpleNamespace(data_json=old["data_json"]) if old else None

            def validate_record(self):
                from cipher_aec.ricky import storage
                with patch.object(storage, "CompanyStore", return_value=store):
                    store.validate_controller(self)

        return Document(fields)


class CompanyFixtureReader(RunAECReader):
    def actor(self, context, ability):
        actor = self.boundary.authorize(self.authority, execution=self.execution, lock=self.lock)
        self.boundary.require_ability(ability)
        if context != self.context: raise RickyError("not_found", "Fixture context mismatch")
        return actor

    def pursuit(self, context, actor):
        value = self.boundary.fixture.pursuit(context, actor)
        self.pursuit_observation = {"id": value["id"], "digest": digest(value),
            "party_type": value["party_type"], "party_id": value["party_id"], "opportunity": value["opportunity"],
            "native_refs": [{"doctype": "Customer", "name": value["party_id"]}, {"doctype": "Opportunity", "name": value["opportunity"]}]}
        return value

    def record(self, context, kind, record_id, actor):
        value = self.boundary.fixture.record(context, kind, record_id, actor)
        if kind == "estimate": self.owners[value["id"]] = {"id": value["id"], "pursuit_id": value["pursuit_id"]}
        else: self._observe("estimate", kind, value)
        return value

    def _measurement(self, record_id, actor):
        value, _ = self.boundary.fixture.measurement(self.context, record_id, actor)
        self._observe("takeoff", "measurement", value)
        return value

    def raw_sources(self, context, revision_ids, actor):
        return self.boundary.fixture.raw_sources(context, revision_ids, actor)

    def raw_records(self, context, records, actor):
        return self.boundary.fixture.raw_records(context, records, actor)

    def citation(self, context, reference, actor):
        return self.boundary.fixture.citation(context, reference, actor)

    def current_units(self, context, records, actor):
        return self.boundary.fixture.current_units(context, records, actor)

    def verify_original(self, manifest):
        validate_manifest(manifest, self.request)
        self.boundary.authorize(self.authority, execution=self.execution, lock=self.lock)
        self.boundary.require_ability("commercial.read")
        if not self.boundary.fixture.native_allowed:
            raise RickyError("not_found", "Explicit original native source denied")
        verified = {}
        for item in manifest["records"]:
            value = self.boundary.fixture.records[item["kind"], item["id"]] if item["domain"] == "estimate" else self._measurement(item["id"], self.boundary.actor)
            if digest(value) != item["digest"]: raise RickyError("source_integrity", "Explicit immutable record mismatch")
            verified[item["domain"], item["kind"], item["id"]] = value
        if canonical(self._selected(self.boundary.actor)) != canonical(manifest["citations"]):
            raise RickyError("source_integrity", "Explicit selected citation mismatch")
        return verified


class CompanyFixtureBoundary(CompanyBackend):
    """Fixture-only authority/lock protocol; never imported by runtime code."""
    def __init__(self):
        self.fixture = FixtureReader()
        self.fixture.pursuit_value.update(party_type="Customer", party_id="Fixture Customer", opportunity="Fixture Opportunity")
        self.actor = self.fixture.actor_value
        self.user = self.actor.user
        self.session = True; self.allowed = True; self.effects = True
        self.events = []; self.receipts = {}; self.permission = {"ricky.run", "commercial.read", "estimate.read", "document.read"}
        self.growing_plan = False

    def require_effects_enabled(self):
        if not self.effects: raise RickyError("execution_quarantined", "Explicit fixture quarantine")

    def bind(self, company, request, run_id):
        return CompanyAuthority(self.actor.user, self.actor.person_id, company, run_id, "a" * 64, "b" * 64, request.selection_digest())

    def authorize(self, authority, execution=False, lock=False):
        if not self.allowed or authority.user != self.user or authority.person != self.actor.person_id:
            raise RickyError("not_found", "Explicit owner/current permission denied")
        self.require_ability("ricky.run")
        if execution and not self.session: raise RickyError("session_revoked", "Explicit original session revoked")
        return self.actor

    def require_ability(self, ability):
        if ability not in self.permission: raise RickyError("not_found", "Explicit ability denied")

    def require_permission(self, authority, ability):
        self.authorize(authority, execution=True)
        self.require_ability(ability)

    def observe_session(self, authority, actor):
        if not self.session:
            raise RickyError("session_revoked", "Explicit original session no longer live for active observation")

    def lock_original(self, run, execution=False):
        self.events.extend(["Person", "IdentitySession", "Company", "Receipt"])
        self.authorize(CompanyAuthority(**{key: run["authority"][key] for key in CompanyAuthority.__dataclass_fields__}), execution=execution)
        if self.receipts.get(run["start_receipt"]) != run["id"]:
            raise RickyError("receipt_integrity", "Explicit missing original admission receipt")

    @contextmanager
    def original_user(self, authority):
        before = self.user; self.user = authority.user
        try: yield
        finally: self.user = before

    @contextmanager
    def source_scope(self, authority, request, manifest=None, lock=False, execution=False, expected_plan=None):
        self.authorize(authority, execution=execution, lock=lock)
        self.events.append("Discovery")
        plan = {"unit_ids": [], "currencies": [], "native_refs": [], "generated_sources": []}
        if self.growing_plan and expected_plan is not None:
            raise RickyError("stale_source", "Explicit plan growth refused before native locks")
        if lock: self.events.extend(["UOM", "Currency", "Native"])
        yield plan

    def reader(self, authority, request, lock=False, execution=True):
        return CompanyFixtureReader(self, authority, request, lock=lock, execution=execution)


class CompanyStrategyTests(unittest.TestCase):
    def setUp(self):
        self.boundary = CompanyFixtureBoundary()
        self.store = CompanyFixtureStore(self.boundary.events)
        self.store.originals = self.boundary.fixture.records
        self.now = datetime(2026, 10, 16, tzinfo=timezone.utc)
        self.service = CompanyReadService(self.store, self.boundary, clock=lambda: self.now)

    def request(self, action="aec.pursuit.lookup", arguments=None, **extra):
        return DeterministicReadRequest(identity("pursuit"), action, canonical(arguments or {}), **extra)

    def start(self, request=None):
        presented = self.service.start_read("Explicit EST fixture", (request or self.request()).binding(), identity("company-operation"))
        run = self.store.get("run", presented["id"])
        self.boundary.receipts[run["start_receipt"]] = run["id"]
        return run

    def test_fixed_read_registry_and_no_model_adapter(self):
        self.assertEqual({row["name"] for row in read_registry().schemas()}, {
            "aec.pursuit.lookup", "aec.estimate.recompute", "aec.estimate.compare", "aec.quantity.convert"})
        self.assertTrue(all(row["effect_class"] == "read" for row in read_registry().schemas()))
        self.assertFalse(hasattr(self.service, "adapter"))
        self.assertFalse(hasattr(self.service, "profile"))
        self.assertFalse(any(row["name"].startswith("aec.") for row in default_registry().schemas()))

    def test_shared_engine_journal_persists_fixture_read_with_no_proposal_or_model(self):
        run = self.start(); self.service.process(run["id"])
        result = self.service.get_run(run["company"], run["id"])
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(result["result"]["title"], "Explicit pursuit")
        self.assertFalse(result["standing"]["model_invoked"])
        self.assertEqual(self.store.count("step", {}), 1)
        self.assertEqual(self.store.count("invocation", {}), 1)
        self.assertEqual(self.store.count("proposal", {}), 0)
        self.assertEqual(self.store.get("run", run["id"])["generations"], 0)

    def test_recompute_uses_pure_canonical_calculation_fixture(self):
        run = self.start(self.request("aec.estimate.recompute", {"revision_id": self.boundary.fixture.revision_id}))
        self.service.process(run["id"])
        result = self.service.get_run(run["company"], run["id"])
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(result["result"]["total"], {"amount": "1025.41", "currency": "USD"})

    def test_ordered_original_boundary_precedes_run_and_union(self):
        run = self.start(); self.boundary.events.clear()
        self.service.claim(run["id"])
        self.assertEqual(self.boundary.events[:9], ["Person", "IdentitySession", "Company", "Receipt", "Run", "Discovery", "UOM", "Currency", "Native"])

    def test_plan_growth_refused_before_new_master_acquisition(self):
        run = self.start(); self.boundary.growing_plan = True; self.boundary.events.clear()
        with self.assertRaises(RickyError): self.service.claim(run["id"])
        self.assertNotIn("Native", self.boundary.events)
        self.assertEqual(self.store.count("invocation", {}), 0)

    def test_original_receipt_required_before_claim(self):
        run = self.start(); self.boundary.receipts.clear()
        with self.assertRaises(RickyError): self.service.claim(run["id"])
        self.assertEqual(self.store.get("run", run["id"])["status"], "queued")

    def test_active_lease_does_not_create_second_attempt(self):
        run = self.start(); self.service.claim(run["id"])
        self.assertIsNone(self.service.claim(run["id"]))
        self.assertEqual(self.store.get("run", run["id"])["lease_token"], 1)

    def test_expired_original_session_cannot_work_or_read_active_output(self):
        run = self.start(); self.boundary.session = False
        with self.assertRaises(RickyError): self.service.get_run(run["company"], run["id"])
        self.service.process(run["id"])
        self.assertEqual(self.store.count("invocation", {}), 0)
        failed = self.service.get_run(run["company"], run["id"])
        self.assertEqual(failed["status"], "failed")
        self.assertIsNone(failed["result"])

    def test_unclaimed_permanent_refusal_cannot_overwrite_new_lease_cancel_or_completion(self):
        for transition in ("claim", "cancel", "complete", "changed-preview"):
            with self.subTest(transition=transition):
                self.setUp(); observed = self.start()
                if transition == "claim": self.service.claim(observed["id"])
                elif transition == "cancel": self.service.cancel(observed["company"], observed["id"])
                elif transition == "complete": self.service.process(observed["id"])
                else: observed["tool_calls"] = 4
                before = digest(self.store.get("run", observed["id"]))
                self.assertFalse(self.service._settle_unclaimed(observed, RickyError("session_revoked", "Must not be stored")))
                self.assertEqual(digest(self.store.get("run", observed["id"])), before)

    def test_transient_preclaim_errors_stay_recoverable_and_never_store_their_message(self):
        for refusal in (RickyError("not_found", "Transient source detail", retryable=True),
                        RickyError("concurrent_change", "DB timeout"), RickyError("internal_error", "Unexpected exception")):
            observed = self.start()
            before = digest(self.store.get("run", observed["id"]))
            self.assertFalse(self.service._settle_unclaimed(observed, refusal))
            self.assertEqual(digest(self.store.get("run", observed["id"])), before)
            self.setUp()

    def test_unclaimed_settlement_uses_bounded_reason_and_has_no_late_scope_locks(self):
        observed = self.start(); self.boundary.events.clear()
        self.assertTrue(self.service._settle_unclaimed(observed, RickyError("session_revoked", "Do not expose this source detail")))
        self.assertEqual(self.boundary.events, ["Run"])
        current = self.store.get("run", observed["id"])
        self.assertNotIn("source detail", current["error"]["message"])
        self.assertIsNone(current["result"])

    def test_fresh_original_owner_session_can_read_completed_exact_result(self):
        run = self.start(); self.service.process(run["id"])
        before = canonical(self.service.get_run(run["company"], run["id"]))
        self.boundary.session = False
        self.boundary.fixture.pursuit_value["title"] = "Later title"
        after = self.service.get_run(run["company"], run["id"])
        self.assertEqual(canonical(after), before)
        self.assertEqual(self.store.get("run", run["id"])["original_session_reference"], "a" * 64)

    def test_alias_same_person_cannot_read_original_user_result(self):
        run = self.start(); self.service.process(run["id"])
        self.boundary.user = "alias@example.invalid"
        with self.assertRaises(RickyError): self.service.get_run(run["company"], run["id"])

    def test_native_revocation_hides_completed_original_result(self):
        run = self.start(); self.service.process(run["id"])
        self.boundary.fixture.native_allowed = False
        with self.assertRaises(RickyError): self.service.get_run(run["company"], run["id"])

    def test_source_free_cancel_survives_source_and_original_session_revocation(self):
        source = self.boundary.fixture.citation_value
        reference = SourceReference(source["id"], source["revision_id"], source["page"], source["excerpt_sha256"], source["source_sha256"])
        run = self.start(self.request(sources=(reference,)))
        self.boundary.fixture.source_allowed = False
        with self.assertRaises((RickyError, DomainError)): self.service.get_run(run["company"], run["id"])
        self.boundary.session = False
        receipt = self.service.cancel(run["company"], run["id"])
        self.assertEqual(receipt["status"], "cancelled")
        self.assertEqual(set(receipt), {"id", "company", "scope_type", "project", "request_kind", "status", "cancel_requested"})
        self.assertFalse({"result", "error", "sources", "request", "arguments"} & set(receipt))

    def test_unused_selected_citation_is_reauthorized_on_completed_read(self):
        source = self.boundary.fixture.citation_value
        reference = SourceReference(source["id"], source["revision_id"], source["page"], source["excerpt_sha256"], source["source_sha256"])
        run = self.start(self.request(sources=(reference,))); self.service.process(run["id"])
        self.assertEqual(self.store.count("artifact", {}), 1)
        self.boundary.fixture.source_allowed = False
        with self.assertRaises((RickyError, DomainError)): self.service.get_run(run["company"], run["id"])

    def test_unused_selected_measurement_is_reauthorized_on_completed_read(self):
        run = self.start(self.request(measurement_ids=(self.boundary.fixture.measurement_id,)))
        self.service.process(run["id"])
        self.assertEqual(self.service.get_run(run["company"], run["id"])["status"], "succeeded")
        self.boundary.fixture.source_allowed = False
        with self.assertRaises((RickyError, DomainError)): self.service.get_run(run["company"], run["id"])

    def test_closed_manifest_rejects_omitted_changed_and_extra_original_entries(self):
        run = self.start(self.request(measurement_ids=(self.boundary.fixture.measurement_id,)))
        request = DeterministicReadRequest.from_value(run["request"])
        for edit in (lambda value: value["records"].clear(),
                     lambda value: value["records"][0].update(digest="bad"),
                     lambda value: value["pursuit"]["native_refs"].clear(),
                     lambda value: value.update(extra=True)):
            manifest = deepcopy(run["original_manifest"]); edit(manifest)
            with self.assertRaises(RickyError): validate_manifest(manifest, request)

    def test_closed_resource_plan_rejects_alias_shapes_duplicates_and_generated_nodes(self):
        clean = {"unit_ids": [], "currencies": [], "native_refs": [], "generated_sources": []}
        validate_resource_plan(clean)
        for change in ({"unit_ids": [True]}, {"currencies": ["USD", "USD"]}, {"currencies": ["usd"]},
                       {"native_refs": [{"doctype": "User", "name": "Administrator"}]},
                       {"generated_sources": [{"document_id": "generated", "input_digest": "a" * 64}]}, {"extra": True}):
            with self.subTest(change=change), self.assertRaises(RickyError): validate_resource_plan({**clean, **change})

    def test_original_queued_start_receipt_binds_scope_action_selection_and_survives_completion(self):
        run = self.start(); original = self.service._present(run)
        validate_start_receipt(run, original)
        for field, value in (("company", "Other Company"), ("scope_type", "Project"), ("project", "Project"),
                ("request_kind", "model"), ("action", "aec.estimate.recompute"), ("selection_digest", "f" * 64),
                ("result", {}), ("status", "succeeded"), ("standing", {"model_invoked": True})):
            changed = deepcopy(original); changed[field] = value
            with self.subTest(field=field), self.assertRaises(RickyError): validate_start_receipt(run, changed)
        for edit in (lambda value: value["selection"].update(action="aec.estimate.compare"),
                     lambda value: value["selection"]["sources"].append({"revision_id": "another-source"})):
            changed = deepcopy(original); edit(changed)
            with self.assertRaises(RickyError): validate_start_receipt(run, changed)
        self.service.process(run["id"])
        completed = self.store.get("run", run["id"])
        validate_start_receipt(completed, original)
        self.assertEqual(original["status"], "queued")
        self.assertEqual(completed["status"], "succeeded")

    def test_cancel_of_completed_run_preserves_body(self):
        run = self.start(); self.service.process(run["id"])
        before = digest(self.store.get("run", run["id"]))
        self.assertEqual(self.service.cancel(run["company"], run["id"])["status"], "succeeded")
        self.assertEqual(digest(self.store.get("run", run["id"])), before)

    def test_stale_token_cannot_persist_output(self):
        run = self.start(); _, token = self.service.claim(run["id"])
        self.service.cancel(run["company"], run["id"])
        with self.assertRaises(RickyError): CompanyExecution(self.service, run["id"], token).invoke("aec.pursuit.lookup", {}, "selected-deterministic-read")
        self.assertEqual(self.store.count("invocation", {}), 0)

    def test_revocation_after_handler_before_acceptance_rolls_back_output(self):
        run = self.start()
        execute = self.service.registry.execute
        def revoke(*args):
            output = execute(*args); self.boundary.fixture.native_allowed = False
            return output
        with patch.object(self.service.registry, "execute", side_effect=revoke): self.service.process(run["id"])
        self.assertEqual(self.store.count("invocation", {}), 0)
        self.assertIsNone(self.store.get("run", run["id"])["result"])
        self.assertEqual(self.store.get("run", run["id"])["status"], "failed")

    def test_successful_invocation_replay_rechecks_source_authority(self):
        run = self.start(); self.service.process(run["id"])
        completed = self.store.get("run", run["id"])
        # Explicit fixture recovery seam: retain an immutable invocation while
        # resetting only the run to its pre-final journal state, as a crash.
        pending = deepcopy(completed); pending.update(status="executing", result=None, result_digest=None, completed_at=None)
        self.store.rows["run", run["id"]] = pending
        self.boundary.fixture.native_allowed = False
        with self.assertRaises(RickyError): CompanyExecution(self.service, run["id"], pending["lease_token"]).invoke("aec.pursuit.lookup", {}, "selected-deterministic-read")
        self.assertEqual(self.store.count("invocation", {}), 1)

    def test_preclaim_failure_never_overwrites_completed_or_foreign_lease(self):
        run = self.start(); self.service.process(run["id"])
        before = digest(self.store.get("run", run["id"]))
        self.service._fail(run["id"], None, RickyError("not_found", "Explicit preclaim failure"))
        self.service._fail(run["id"], 900, RickyError("not_found", "Explicit stale worker"))
        self.assertEqual(digest(self.store.get("run", run["id"])), before)

    def test_malformed_stored_standing_refuses_controller_read_and_presentation(self):
        run = self.start(); self.service.process(run["id"])
        completed = self.store.get("run", run["id"])
        # Retain the real successful Step/Invocation so standing is the sole
        # malformed fact, rather than relying on a missing result journal.
        changes = [
            {"status": status, "cancel_requested": status == "cancelled"}
            for status in ("queued", "retrieving", "executing", "failed", "cancelled")]
        changes += [{"result": None}, {"result_digest": None}, {"completed_at": None},
            {"error": {"code": "failed", "message": "Conflicting standing"}},
            {"cancel_requested": True}, {"cancel_requested": 0}]
        changes += [{"status": status, "cancel_requested": status == "cancelled", "result": None,
            "result_digest": None, "completed_at": None} for status in ("failed", "cancelled")]
        for change in changes:
            with self.subTest(change=change):
                changed = {**deepcopy(completed), **change}
                with self.assertRaises(RickyError): validate_company_record("run", changed, self.store)
                self.store.rows["run", run["id"]] = changed
                with patch.object(self.service.registry, "execute", side_effect=AssertionError("Must not rerun")):
                    with self.assertRaises(RickyError): self.service.get_run(run["company"], run["id"])
                    with self.assertRaises(RickyError): self.service._present(changed)
        self.store.rows["run", run["id"]] = completed
        self.assertEqual(self.service.get_run(run["company"], run["id"])["result"], completed["result"])

    def test_active_completion_or_cancellation_flag_refuses_without_a_result(self):
        run = self.start()
        for change in ({"completed_at": self.now.isoformat()}, {"cancel_requested": True},
                {"result_digest": "f" * 64}, {"status": "unknown"}):
            with self.subTest(change=change):
                changed = {**deepcopy(run), **change}
                with self.assertRaises(RickyError): validate_company_record("run", changed, self.store)
                self.store.rows["run", run["id"]] = changed
                with self.assertRaises(RickyError): self.service.get_run(run["company"], run["id"])
        self.store.rows["run", run["id"]] = run
        self.assertEqual(self.service.get_run(run["company"], run["id"])["status"], "queued")

    def test_result_requires_successful_exact_journal_linkage(self):
        run = self.start(); self.service.process(run["id"])
        invocation = next(value for (kind, _), value in self.store.rows.items() if kind == "invocation")
        invocation["output"]["title"] = "Forged output"
        with self.assertRaises(RickyError): self.service.get_run(run["company"], run["id"])

    def test_wrong_tool_version_step_key_and_step_id_refuse_read_without_rerunning_tool(self):
        for kind, field, value in (("step", "tool_name", "aec.estimate.recompute"),
                ("invocation", "tool_name", "aec.estimate.recompute"), ("step", "tool_version", "2"),
                ("invocation", "tool_version", "2"), ("step", "operation_key", "f" * 64),
                ("step", "id", identity("swapped-step"))):
            with self.subTest(kind=kind, field=field):
                self.setUp(); run = self.start(); self.service.process(run["id"])
                record = next(item for (row_kind, _), item in self.store.rows.items() if row_kind == kind)
                record[field] = value
                with patch.object(self.service.registry, "execute", side_effect=AssertionError("Must not rerun")), self.assertRaises(RickyError):
                    self.service.get_run(run["company"], run["id"])

    def test_successful_invocation_replay_checks_exact_step_tool_key_and_version(self):
        run = self.start(); self.service.process(run["id"])
        pending = self.store.get("run", run["id"]); pending.update(status="executing", result=None, result_digest=None, completed_at=None)
        self.store.rows["run", run["id"]] = pending
        step = next(item for (kind, _), item in self.store.rows.items() if kind == "step")
        step["tool_version"] = "unreviewed"
        with patch.object(self.service.registry, "execute", side_effect=AssertionError("Must not rerun")), self.assertRaises(RickyError):
            CompanyExecution(self.service, run["id"], pending["lease_token"]).invoke("aec.pursuit.lookup", {}, "selected-deterministic-read")

    def test_stage_a_controller_refuses_proposals_and_scope_retarget(self):
        run = self.start()
        with self.assertRaises(RickyError): self.store.insert("proposal", self.service._new(CompanyAuthority(**{key: run["authority"][key] for key in CompanyAuthority.__dataclass_fields__}), status="proposed"))
        changed = deepcopy(run); changed["request"]["action"] = "aec.scope.draft"
        with self.assertRaises(RickyError): self.store.save("run", changed)

    def test_delegation_orphan_requires_exact_lexical_pair_and_expires(self):
        run = self.start()
        delegation = self.store.get("delegation", run["delegation_id"])
        other = deepcopy(delegation); other["id"] = identity("orphan-delegation")
        with self.assertRaises(RickyError): validate_company_record("delegation", other, FixtureStore())

    def test_start_respects_native_links_and_finishes_exact_pair(self):
        store = NativeLinkCompanyStore([])
        service = CompanyReadService(store, self.boundary, clock=lambda: self.now)
        run = service.start_read("Explicit EST fixture", self.request().binding(), identity("native-link-start"))
        saved = store.get("run", run["id"])
        delegation = store.get("delegation", saved["delegation_id"])
        self.assertEqual(store.events[:3], [
            ("insert", "run", saved["id"], None),
            ("save", "run", saved["id"], saved["id"]),
            ("insert", "delegation", delegation["id"], saved["id"])])
        validate_company_record("run", saved, store)
        validate_company_record("delegation", delegation, store)
        self.assertEqual(delegation["allowed_tools"], ["aec.pursuit.lookup"])
        self.assertEqual(delegation["effect_classes"], ["read"])

    def test_native_provisional_run_is_never_readable_even_during_admission(self):
        store = NativeLinkCompanyStore([])
        observed = []
        def observe(doc):
            if doc.doctype == DOCTYPES["run"]:
                with self.assertRaises(RickyError) as error: store.get("run", doc.name)
                self.assertEqual(error.exception.code, "source_integrity")
                observed.append(doc.run_id)
        store.after_insert = observe
        CompanyReadService(store, self.boundary, clock=lambda: self.now).start_read(
            "Explicit EST fixture", self.request().binding(), identity("native-provisional-start"))
        self.assertEqual(observed, [None])

    def test_native_run_insert_outside_admission_cannot_clear_its_link(self):
        saved = self.start()
        store = NativeLinkCompanyStore([])
        with self.assertRaises(RickyError): store.insert("run", saved)
        self.assertEqual(store.native, {})

    def test_native_controller_refuses_provisional_header_outside_admission(self):
        store = NativeLinkCompanyStore([])
        result = CompanyReadService(store, self.boundary, clock=lambda: self.now).start_read(
            "Explicit EST fixture", self.request().binding(), identity("native-controller-start"))
        doc = store.document(DOCTYPES["run"], result["id"])
        doc.run_id = None
        with self.assertRaises(DomainError) as error: doc.validate_record()
        self.assertEqual(error.exception.code, "source_integrity")

    def test_interrupted_native_root_is_unreadable_after_admission_exits(self):
        store = NativeLinkCompanyStore([])
        class InterruptedSave(Exception): pass
        def interrupt(doc):
            if doc.doctype == DOCTYPES["run"]: raise InterruptedSave
        store.after_insert = interrupt
        with self.assertRaises(InterruptedSave):
            CompanyReadService(store, self.boundary, clock=lambda: self.now).start_read(
                "Explicit EST fixture", self.request().binding(), identity("native-interrupted-start"))
        # The real canonical command rolls its transaction back. Even before
        # that rollback, an interrupted provisional root is not readable.
        self.assertEqual([kind for kind, _ in store.rows], ["run"])
        run = next(iter(store.rows.values()))
        with self.assertRaises(RickyError) as error: store.get("run", run["id"])
        self.assertEqual(error.exception.code, "source_integrity")
        with self.assertRaises(RickyError): validate_company_record("run", run, FixtureStore())

    def test_missing_delegation_allowance_is_exact_initial_and_retains_invariants(self):
        run = self.start()
        authority = CompanyAuthority(**{key: run["authority"][key] for key in CompanyAuthority.__dataclass_fields__})
        empty = FixtureStore()
        with admission_pair(authority, identity("wrong-pair")), self.assertRaises(RickyError):
            validate_company_record("run", run, empty)
        with admission_pair(authority, run["delegation_id"]):
            validate_company_record("run", run, empty)
            validate_company_record("run", run, empty, before=deepcopy(run))
            for changes in ({"status": "retrieving"}, {"tool_calls": 1},
                            {"original_manifest_digest": "0" * 64}, {"generations": 1}):
                changed = {**deepcopy(run), **changes}
                with self.subTest(changes=changes), self.assertRaises(RickyError):
                    validate_company_record("run", changed, empty, before=deepcopy(run))
            delegation = self.store.get("delegation", run["delegation_id"])
            with self.assertRaises(RickyError): validate_company_record("delegation", delegation, empty)
        with self.assertRaises(RickyError): validate_company_record("run", run, empty)

    def test_admission_revalidates_persisted_pair_before_returning(self):
        store = NativeLinkCompanyStore([])
        def corrupt(doc):
            if doc.doctype == DOCTYPES["delegation"]:
                value = store.rows["delegation", doc.name]
                value["allowed_tools"].append("ungranted-tool")
                store.native[doc.doctype, doc.name]["data_json"] = canonical(value)
        store.after_insert = corrupt
        with self.assertRaises(RickyError) as error:
            CompanyReadService(store, self.boundary, clock=lambda: self.now).start_read(
                "Explicit EST fixture", self.request().binding(), identity("native-corrupt-pair"))
        self.assertEqual(error.exception.code, "source_integrity")

    def test_project_fast_guards_remain_before_authority(self):
        for updates in ({"status": "succeeded"}, {"cancel_requested": True}, {"lease_expires_at": (self.now + timedelta(seconds=100)).isoformat()}):
            store, backend = FixtureStore(), FixtureBackend()
            project = RickyService(store, backend, FixtureAdapter(), clock=lambda: self.now)
            view = project.start("Fixture Company", "Fixture Project", "Explicit Project question", identity("old-project-op"))
            row = store.get("run", view["id"]); row.update(updates); store.save("run", row)
            backend.access = False
            self.assertIsNone(project.claim(view["id"]))

    def test_company_entry_never_mutates_legacy_project_run_or_exposes_proposal_writer(self):
        store, backend = FixtureStore(), FixtureBackend()
        project = RickyService(store, backend, FixtureAdapter(), clock=lambda: self.now)
        view = project.start("Fixture Company", "Fixture Project", "Explicit Project question", identity("cross-mode-project"))
        before = digest(store.get("run", view["id"]))
        company = CompanyReadService(store, self.boundary, clock=lambda: self.now)
        for call in (lambda: company.process(view["id"]), lambda: company.claim(view["id"]),
                     lambda: company.get_run("Fixture Company", view["id"]),
                     lambda: company.cancel("Fixture Company", view["id"]),
                     lambda: company.commit_proposal(identity("proposal"), 1, identity("op")),
                     lambda: company.start("C", None, "Question", identity("op"))):
            with self.assertRaises(RickyError): call()
        self.assertEqual(digest(store.get("run", view["id"])), before)


if __name__ == "__main__": unittest.main()

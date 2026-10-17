"""Pure boundary call-through tests; native qualification remains pending."""
import ast
from contextlib import ExitStack, nullcontext
from copy import deepcopy
import hashlib
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from cipher_aec.api.errors import DomainError
from cipher_aec.ricky.company_backend import CompanyBackend, RunAECReader, start_session_binding
from cipher_aec.ricky.company_contracts import CompanyAuthority, decode_run_authority
from cipher_aec.ricky.aec_backend import FrappeAECReader
from cipher_aec.ricky.aec_contracts import SourceReference
from cipher_aec.ricky.contracts import RickyError, canonical, digest
from cipher_aec.ricky.storage import FrappeStore
from cipher_aec.ricky import permissions
from cipher_aec.tests import test_ricky_company_service as strategy_fixtures
from cipher_aec.tests.test_ricky import FixtureStore, FixtureBackend, FixtureAdapter
from cipher_aec.ricky.engine import RickyService
from cipher_aec.tests.test_estimating_core import identity


class Row(dict):
    __getattr__ = dict.get


class CanonicalOriginalReader(strategy_fixtures.CompanyFixtureReader):
    """Keep real retained-source verification and its closed typed collector."""
    verify_original = RunAECReader.verify_original
    raw_records = FrappeAECReader.raw_records
    raw_sources = RunAECReader.raw_sources


class CompanyConversionOriginalSources(unittest.TestCase):
    def setUp(self):
        self.fixture = strategy_fixtures.CompanyStrategyTests()
        self.fixture.setUp()
        self.boundary = self.fixture.boundary
        self.boundary.reader = lambda authority, request, **kwargs: CanonicalOriginalReader(
            self.boundary, authority, request, **kwargs)
        self.stack = ExitStack(); self.addCleanup(self.stack.close)
        root = Path(__file__).parents[1]
        source_path = root / "estimating" / "sources.py"
        tree = ast.parse(source_path.read_text())
        collector = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "citation_groups")
        source_module = ModuleType("cipher_aec.estimating.sources")
        source_module.DomainError = DomainError
        exec(compile(ast.Module(body=[collector], type_ignores=[]), str(source_path), "exec"), vars(source_module))
        gate = next(node for node in tree.body if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "GENERATED_INPUTS_QUALIFIED" for target in node.targets))
        self.assertIs(ast.literal_eval(gate.value), False)
        self.generated = set()
        self.source_allowed = True
        self.source_reads = []
        def source_plan(company, revision, actor, **kwargs):
            self.source_reads.append((company, revision, actor.user, kwargs.get("lock")))
            if not self.source_allowed:
                raise DomainError("not_found", "Explicit current source authority denied", 404)
            return {"generated_sources": [{"document_id": "generated"}] if revision in self.generated else []}
        native = ModuleType("cipher_aec.commercial.native")
        native.require_native = Mock(return_value=SimpleNamespace(company="Explicit EST fixture"))
        native.party = Mock()
        from cipher_aec import commercial
        self.stack.enter_context(patch.object(commercial, "native", native, create=True))
        self.stack.enter_context(patch.dict(sys.modules, {
            "cipher_aec.estimating.sources": source_module,
            "cipher_aec.estimating.lockplan": SimpleNamespace(active_for=lambda *args: True),
            "cipher_aec.documents.provenance": SimpleNamespace(source_plan=source_plan),
            "cipher_aec.governance.context": SimpleNamespace(require_company=Mock()),
            "cipher_aec.commercial.native": native}))
        citation = self.boundary.fixture.citation_value
        self.reference = SourceReference(citation["id"], citation["revision_id"], citation["page"],
            citation["excerpt_sha256"], citation["source_sha256"])
        self.request = self.fixture.request("aec.quantity.convert", {
            "source_kind": "estimate-line", "source_id": self.boundary.fixture.line_id,
            "target_unit_id": identity("sy")}, sources=(self.reference,))

    def completed(self):
        run = self.fixture.start(self.request)
        self.fixture.service.process(run["id"])
        current = self.fixture.store.get("run", run["id"])
        self.assertEqual((current["status"], current["error"]), ("succeeded", None))
        return current

    def test_conversion_verifies_line_through_its_retained_revision_and_snapshot_sources(self):
        run = self.completed()
        self.assertEqual((run["result"]["numerator"], run["result"]["denominator"]), ("100", "9"))
        self.assertEqual(self.fixture.store.count("invocation", {}), 1)
        self.assertEqual({row["kind"] for row in run["original_manifest"]["records"]}, {"line", "revision", "snapshot"})
        self.assertTrue(self.source_reads)
        self.assertTrue(any(row[3] is True for row in self.source_reads))
        self.assertTrue(all(row[0] == run["company"] and row[2] == run["user"] for row in self.source_reads))
        observed = self.fixture.service.get_run(run["company"], run["id"])
        self.assertEqual(observed["result"], run["result"])

    def test_missing_line_parent_or_snapshot_cannot_skip_original_source_verification(self):
        run = self.completed()
        authority = decode_run_authority(run)
        for kind in ("revision", "snapshot"):
            manifest = deepcopy(run["original_manifest"])
            manifest["records"] = [row for row in manifest["records"] if row["kind"] != kind]
            reader = self.boundary.reader(authority, self.request, lock=False, execution=False)
            with self.subTest(kind=kind), self.assertRaises(RickyError) as error:
                reader.verify_original(manifest)
            self.assertEqual(error.exception.code, "source_integrity")

    def test_current_source_denial_and_generated_dependency_still_refuse_completed_conversion(self):
        run = self.completed()
        self.generated.add(self.reference.revision_id)
        with self.assertRaises(RickyError) as error:
            self.fixture.service.get_run(run["company"], run["id"])
        self.assertEqual(error.exception.code, "source_dependency_unqualified")
        self.generated.clear()
        self.source_allowed = False
        with self.assertRaises(DomainError) as denied: self.fixture.service.get_run(run["company"], run["id"])
        self.assertEqual(denied.exception.code, "not_found")

    def test_retained_snapshot_embedded_rate_sources_keep_generated_gate(self):
        run = self.completed()
        manifest = deepcopy(run["original_manifest"])
        snapshot = self.boundary.fixture.records["snapshot", self.boundary.fixture.snapshot_id]
        rates = snapshot["inputs"]["rates"]
        extra = deepcopy(self.boundary.fixture.citation_value)
        extra["revision_id"] = "fixture-extra-rate-source"
        next(iter(rates.values()))["source_citations"] = [extra]
        for item in manifest["records"]:
            if item["kind"] == "snapshot": item["digest"] = digest(snapshot)
        self.generated.add(extra["revision_id"])
        reader = self.boundary.reader(decode_run_authority(run), self.request, lock=False, execution=False)
        with self.assertRaises(RickyError) as error: reader.verify_original(manifest)
        self.assertEqual(error.exception.code, "source_dependency_unqualified")
        self.assertTrue(any(row[1] == extra["revision_id"] for row in self.source_reads))


class CompanyBoundaries(unittest.TestCase):
    def setUp(self):
        self.harness = strategy_fixtures.CompanyStrategyTests(); self.harness.setUp()
        self.run = self.harness.start()
        self.authority = decode_run_authority(self.run)
        self.actor = SimpleNamespace(user=self.authority.user, person_id=self.authority.person)
        self.context = SimpleNamespace(current_actor=Mock(return_value=self.actor),
            require_company=Mock(return_value=SimpleNamespace(name=self.authority.company)),
            require_session_authority=Mock(), company_authority_fingerprint=Mock(return_value="b" * 64))

    def test_work_boundary_checks_original_session_and_current_fingerprint(self):
        with patch.dict(sys.modules, {"cipher_aec.governance.context": self.context}):
            self.assertIs(CompanyBackend().authorize(self.authority, execution=True, lock=True), self.actor)
        self.context.current_actor.assert_called_once_with(lock=True)
        self.context.require_session_authority.assert_called_once_with(self.actor, "a" * 64, lock=True)
        self.context.require_company.assert_called_once_with(self.authority.company, ability="ricky.run", actor=self.actor, lock=True)
        self.context.company_authority_fingerprint.assert_called_once_with(self.actor, self.authority.company, lock=True)

    def test_completed_read_keeps_current_owner_rights_without_rebinding_session(self):
        with patch.dict(sys.modules, {"cipher_aec.governance.context": self.context}):
            CompanyBackend().authorize(self.authority, execution=False)
        self.context.require_company.assert_called_once()
        self.context.require_session_authority.assert_not_called()
        self.context.company_authority_fingerprint.assert_not_called()

    def test_alias_does_not_inherit_original_user_boundary(self):
        self.context.current_actor.return_value = SimpleNamespace(user="alias@example.invalid", person_id=self.authority.person)
        with patch.dict(sys.modules, {"cipher_aec.governance.context": self.context}), self.assertRaises(RickyError):
            CompanyBackend().authorize(self.authority)
        self.context.require_company.assert_not_called()

    def test_old_fingerprint_is_not_a_permission_grant(self):
        self.context.require_company.side_effect = RickyError("not_found", "Explicit current duty denial")
        with patch.dict(sys.modules, {"cipher_aec.governance.context": self.context}), self.assertRaises(RickyError):
            CompanyBackend().authorize(self.authority, execution=True, lock=True)

    def test_work_refuses_current_authority_drift(self):
        self.context.company_authority_fingerprint.return_value = "c" * 64
        with patch.dict(sys.modules, {"cipher_aec.governance.context": self.context}), self.assertRaises(RickyError):
            CompanyBackend().authorize(self.authority, execution=True, lock=True)

    def test_worker_switch_restores_actual_user_on_exception(self):
        frappe = SimpleNamespace(session=SimpleNamespace(user="Administrator"))
        frappe.set_user = lambda user: setattr(frappe.session, "user", user)
        with patch.dict(sys.modules, {"frappe": frappe}):
            with self.assertRaisesRegex(ValueError, "fixture"):
                with CompanyBackend().original_user(self.authority):
                    self.assertEqual(frappe.session.user, self.authority.user)
                    raise ValueError("fixture")
        self.assertEqual(frappe.session.user, "Administrator")

    def test_new_start_binds_only_prelocked_captured_session_and_finally_expires(self):
        from cipher_aec.ricky.company_contracts import DeterministicReadRequest
        self.context.company_authority_fingerprint.return_value = "b" * 64
        reference = hashlib.sha256(b"fixture-original-session").hexdigest()
        frappe = SimpleNamespace(session=SimpleNamespace(user=self.actor.user, sid="fixture-original-session"))
        provenance = SimpleNamespace(has_prelocked=lambda: False)
        request = DeterministicReadRequest.from_value(self.run["request"])
        backend = CompanyBackend()
        with patch.dict(sys.modules, {"frappe": frappe, "cipher_aec.governance.context": self.context,
                                    "cipher_aec.documents.provenance": provenance}):
            with start_session_binding(actor=self.actor, company=self.authority.company, reference=reference):
                bound = backend.bind(self.authority.company, request, identity("new-bound-run"))
                self.assertEqual(bound.session_reference, reference)
                with self.assertRaises(RickyError):
                    with start_session_binding(actor=self.actor, company=self.authority.company, reference=reference): pass
            with self.assertRaises(RickyError): backend.bind(self.authority.company, request, identity("orphan"))
            with self.assertRaises(ValueError):
                with start_session_binding(actor=self.actor, company=self.authority.company, reference=reference):
                    raise ValueError("Explicit throwing effect")
            with self.assertRaises(RickyError): backend.bind(self.authority.company, request, identity("orphan"))

    def test_new_start_refuses_renewed_sid_actor_and_company_without_late_session_locks(self):
        from cipher_aec.ricky.company_contracts import DeterministicReadRequest
        reference = hashlib.sha256(b"fixture-original-session").hexdigest()
        request = DeterministicReadRequest.from_value(self.run["request"])
        for change in ("sid-before-entry", "sid-at-bind", "actor", "company"):
            with self.subTest(change=change):
                self.context.current_actor.return_value = self.actor
                self.context.require_session_authority.reset_mock()
                frappe = SimpleNamespace(session=SimpleNamespace(user=self.actor.user,
                    sid="renewed" if change == "sid-before-entry" else "fixture-original-session"))
                provenance = SimpleNamespace(has_prelocked=lambda: False)
                with patch.dict(sys.modules, {"frappe": frappe, "cipher_aec.governance.context": self.context,
                                            "cipher_aec.documents.provenance": provenance}), self.assertRaises(RickyError):
                    with start_session_binding(actor=self.actor, company=self.authority.company, reference=reference):
                        if change == "sid-at-bind": frappe.session.sid = "renewed"
                        if change == "actor": self.context.current_actor.return_value = SimpleNamespace(user="alias", person_id=self.actor.person_id)
                        CompanyBackend().bind("Other Company" if change == "company" else self.authority.company,
                            request, identity("new-bound-run"))
                self.context.require_session_authority.assert_not_called()

    def test_active_receipt_observation_keeps_sources_locked_without_late_session_lock(self):
        backend = CompanyBackend()
        backend.authorize = Mock(return_value=self.actor)
        backend.source_scope = Mock(side_effect=lambda *args, **kwargs: nullcontext())
        reader = Mock(); reader.verify_original.return_value = {}
        backend.reader = Mock(return_value=reader)
        with patch.dict(sys.modules, {"cipher_aec.governance.context": self.context}):
            backend.authorize_result(self.run, lock=True, observation=True)
        self.context.require_session_authority.assert_called_once_with(self.actor, self.authority.session_reference, lock=False)
        self.assertTrue(backend.source_scope.call_args.kwargs["lock"])
        self.assertFalse(backend.source_scope.call_args.kwargs["execution"])
        self.assertTrue(backend.reader.call_args.kwargs["lock"])
        self.assertFalse(backend.reader.call_args.kwargs["execution"])

    def loader(self, value, **changed):
        row = Row(name=value["id"], scope_type=value.get("scope_type", "Project"), company=value["company"], project=value["project"],
            requested_by=value["user"], person_id=value["person"], run_id=value.get("run_id"), data_json=canonical(value))
        row.update(changed)
        store = object.__new__(FrappeStore)
        store.frappe = SimpleNamespace(db=SimpleNamespace(sql=Mock(return_value=[row])))
        return store

    def test_native_header_company_codec_before_dispatch(self):
        store = self.loader(self.run)
        self.assertEqual(store.get_scoped("run", self.run["id"], lock=True), self.run)
        self.assertIn("FOR UPDATE", store.frappe.db.sql.call_args.args[0])

    def test_mismatched_native_headers_fail_closed(self):
        for field, value in (("scope_type", "Project"), ("company", "Another"), ("project", "Project"),
                             ("requested_by", "alias"), ("person_id", "different"), ("run_id", identity("other"))):
            with self.subTest(field=field), self.assertRaises(RickyError):
                self.loader(self.run, **{field: value}).get_scoped("run", self.run["id"])
        forged = deepcopy(self.run)
        forged.update(scope_type="Project", project="Project")
        with self.assertRaises(RickyError): self.loader(forged).get_scoped("run", forged["id"])

    def test_legacy_project_header_loader_preserves_original_body_hash(self):
        store = FixtureStore(); backend = FixtureBackend()
        service = RickyService(store, backend, FixtureAdapter())
        view = service.start("Fixture Company", "Fixture Project", "Explicit old Project", identity("old-op"))
        original = store.get("run", view["id"])
        current = self.loader(original).get_scoped("run", original["id"])
        self.assertEqual(canonical(current), canonical(original))
        self.assertEqual(digest(current), digest(original))

    def test_scope_dispatch_never_constructs_model_for_company_or_bad_header(self):
        source = Path(__file__).parents[1] / "ricky" / "api.py"
        function = next(node for node in ast.parse(source.read_text()).body if isinstance(node, ast.FunctionDef) and node.name == "build_run_service")
        module = ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[]))
        model = Mock(side_effect=AssertionError("Model construction is forbidden"))
        loader = Mock(); loader.get_scoped.return_value = self.run
        namespace = {"__name__": "cipher_aec.ricky.api", "__package__": "cipher_aec.ricky",
            "FrappeStore": Mock(return_value=loader), "build_service": model}
        exec(compile(module, str(source), "exec"), namespace)
        with patch("cipher_aec.ricky.company_service.build_service", return_value="explicit-company-strategy") as company:
            self.assertEqual(namespace["build_run_service"](self.run["id"], worker=True), "explicit-company-strategy")
            company.assert_called_once_with(worker=True)
        model.assert_not_called()
        loader.get_scoped.side_effect = RickyError("source_integrity", "Native/JSON mismatch")
        with self.assertRaises(RickyError): namespace["build_run_service"](self.run["id"])
        model.assert_not_called()

    def test_native_generic_company_reads_and_counts_are_closed(self):
        self.assertIs(permissions.has_permission(Row(scope_type="Company"), self.actor.user, "read"), False)
        self.assertIsNone(permissions.has_permission(Row(scope_type="Project"), self.actor.user, "read"))
        for function in (permissions.run_query, permissions.step_query, permissions.invocation_query,
                         permissions.delegation_query, permissions.artifact_query, permissions.proposal_query):
            clause = function(self.actor.user)
            self.assertIn("='Project'", clause)
            self.assertNotIn(self.actor.user, clause)

    def test_production_source_scope_rejects_growth_alias_generated_and_foreign_context_before_union(self):
        from cipher_aec.estimating import lockplan
        from contextlib import nullcontext
        from cipher_aec.ricky.company_contracts import DeterministicReadRequest
        request = DeterministicReadRequest.from_value(self.run["request"])
        clean = {"unit_ids": [], "currencies": ["USD"], "native_refs": [{"doctype": "Customer", "name": "Exact Customer"}], "generated_sources": []}
        for failure in ("growth", "alias", "generated", "foreign", None):
            with self.subTest(failure=failure):
                plan = deepcopy(clean)
                if failure == "generated": plan["generated_sources"] = [{"document_id": "generated", "input_digest": "a" * 64}]
                discovery = Mock(); discovery.finish.return_value = plan
                prepared = Mock(side_effect=lambda *args, **kwargs: nullcontext())
                frappe = SimpleNamespace(db=SimpleNamespace(get_value=lambda doctype, name, field: "Canonical Other Case" if failure == "alias" else name))
                provenance = SimpleNamespace(has_prelocked=lambda: failure == "foreign")
                boundary = CompanyBackend(); boundary.authorize = Mock(return_value=self.actor)
                expected = {"unit_ids": [], "currencies": [], "native_refs": [], "generated_sources": []} if failure == "growth" else clean
                with patch.dict(sys.modules, {"frappe": frappe, "cipher_aec.documents.provenance": provenance}), \
                        patch.object(lockplan, "Discovery", return_value=discovery), patch.object(lockplan, "prepared", prepared):
                    if failure:
                        with self.assertRaises(RickyError):
                            with boundary.source_scope(self.authority, request, lock=True, execution=True, expected_plan=expected): pass
                        prepared.assert_not_called()
                    else:
                        with boundary.source_scope(self.authority, request, lock=True, execution=True, expected_plan=expected) as actual:
                            self.assertEqual(actual, clean)
                        prepared.assert_called_once_with(clean, self.actor, self.authority.company)

    def test_locking_reader_requires_matching_complete_scope(self):
        from cipher_aec.estimating import lockplan
        from cipher_aec.ricky.company_contracts import DeterministicReadRequest
        reader = RunAECReader(CompanyBackend(), self.authority, DeterministicReadRequest.from_value(self.run["request"]), lock=True)
        with patch.object(lockplan, "active_for", return_value=False), self.assertRaises(RickyError):
            reader.citation(reader.context, None, self.actor)


if __name__ == "__main__": unittest.main()

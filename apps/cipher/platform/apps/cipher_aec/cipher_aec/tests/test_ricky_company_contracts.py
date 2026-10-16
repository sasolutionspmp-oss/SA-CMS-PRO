"""Host-only inactive codec tests; fixtures do not establish live authority."""
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
import unittest

from cipher_aec.ricky.aec_contracts import CompanyReadContext, SourceReference
from cipher_aec.ricky.company_contracts import (
    AUTHORITY_SCHEMA, REQUEST_SCHEMA, READ_ACTIONS, READ_KIND, CompanyAuthority,
    DeterministicReadRequest, decode_authority, decode_run_authority,
)
from cipher_aec.ricky.contracts import Authority, RickyError, canonical, digest
from cipher_aec.ricky.engine import RickyService
from cipher_aec.tests.test_ricky import FixtureAdapter, FixtureBackend, FixtureStore


PURSUIT = "00000000-0000-4000-8000-000000000001"
REVISION = "00000000-0000-4000-8000-000000000002"
RUN = "00000000-0000-4000-8000-000000000003"
MEASUREMENT = "00000000-0000-4000-8000-000000000004"
UNIT = "00000000-0000-4000-8000-000000000005"
OPERATION = "00000000-0000-4000-8000-000000000006"


class CompanyCodecTests(unittest.TestCase):
    def request(self, action="aec.estimate.recompute", arguments=None, **extra):
        return DeterministicReadRequest(PURSUIT, action,
            canonical({"revision_id": REVISION} if arguments is None else arguments), **extra)

    def authority(self, request=None, **extra):
        request = request or self.request()
        fields = dict(user="reader@example.invalid", person="4p9x7fj1qa", company="Fixture Company",
            run_id=RUN, session_reference="a" * 64, authority_version="b" * 64,
            selection_digest=request.selection_digest())
        fields.update(extra)
        return CompanyAuthority(**fields)

    def stored_run(self):
        request = self.request()
        authority = self.authority(request)
        return dict(id=RUN, scope_type="Company", project=None, company=authority.company,
            user=authority.user, person=authority.person, authority=authority.binding(),
            original_session_reference=authority.session_reference, request_kind=READ_KIND,
            request=request.binding())

    def test_native_person_hash_roundtrip_without_uuid_coercion(self):
        authority = self.authority()
        self.assertEqual(authority.person, "4p9x7fj1qa")
        self.assertEqual(decode_authority(authority.binding()), authority)
        self.assertEqual(authority.binding()["schema"], AUTHORITY_SCHEMA)
        self.assertIsNone(authority.binding()["project"])
        self.assertFalse(hasattr(authority, "project_revision"))

    def test_company_identity_is_immutable(self):
        with self.assertRaises(FrozenInstanceError):
            self.authority().person = "another-person"

    def test_company_cannot_reuse_project_shape(self):
        for key, value in (("project", "Real Project"), ("project", ""),
                           ("scope_type", "Project"), ("schema", "unknown")):
            binding = self.authority().binding()
            binding[key] = value
            with self.subTest(key=key, value=value), self.assertRaises(RickyError):
                decode_authority(binding)

    def test_missing_extra_company_fields_are_rejected(self):
        for field in self.authority().binding():
            binding = self.authority().binding()
            del binding[field]
            with self.subTest(field=field), self.assertRaises(RickyError):
                decode_authority(binding)
        binding = self.authority().binding()
        binding["grant"] = True
        with self.assertRaises(RickyError):
            decode_authority(binding)

    def test_session_and_integrity_hashes_are_mandatory_exact_hashes(self):
        for field in ("session_reference", "authority_version", "selection_digest"):
            for value in (None, "bearer-value", "A" * 64, True, "a" * 63):
                with self.subTest(field=field, value=value), self.assertRaises(RickyError):
                    self.authority(**{field: value})

    def test_no_implicit_or_malformed_native_identity(self):
        for field in ("company", "user", "person"):
            for value in (None, "", " padded ", "bad\nname", 12, True):
                with self.subTest(field=field, value=value), self.assertRaises(RickyError):
                    self.authority(**{field: value})

    def test_run_id_requires_canonical_uuid(self):
        for value in (None, "native-hash", RUN.upper(), "00000000-0000-1000-8000-000000000003"):
            if value == RUN:  # The numeric-only fixture has no upper-case spelling.
                continue
            with self.subTest(value=value), self.assertRaises(RickyError):
                self.authority(run_id=value)

    def test_explicit_request_roundtrip_and_no_model_standing(self):
        request = self.request()
        self.assertEqual(DeterministicReadRequest.from_value(request.binding()), request)
        self.assertEqual(request.model_standing(), {"mode": READ_KIND,
            "model_invoked": False, "live_model_qualified": False})

    def test_fixed_read_actions_accept_only_typed_arguments(self):
        examples = {"aec.pursuit.lookup": {}, "aec.estimate.recompute": {"revision_id": REVISION},
            "aec.estimate.compare": {"left_revision_id": REVISION, "right_revision_id": REVISION},
            "aec.quantity.convert": {"source_kind": "estimate-line", "source_id": REVISION,
                                     "target_unit_id": UNIT}}
        self.assertEqual(set(examples), READ_ACTIONS)
        for action, arguments in examples.items():
            with self.subTest(action=action):
                self.request(action, arguments)
                with self.assertRaises(RickyError):
                    self.request(action, {**arguments, "amount": "9000"})

    def test_draft_effect_and_model_actions_are_refused(self):
        for action in ("aec.scope.draft", "aec.estimate.draft", "estimate.accept.v1",
                       "task.create", "model.generate", None, []):
            with self.subTest(action=action), self.assertRaises(RickyError):
                self.request(action, {})

    def test_selection_digest_covers_action_arguments_and_all_selected_sources(self):
        request = self.request()
        other_source = SourceReference("c" * 64, "native-revision", 2, "d" * 64, "e" * 64)
        changed = [self.request("aec.pursuit.lookup", {}), self.request(arguments={"revision_id": UNIT}),
            replace(request, sources=(other_source,)), replace(request, measurement_ids=(MEASUREMENT,))]
        for candidate in changed:
            self.assertNotEqual(candidate.selection_digest(), request.selection_digest())

    def test_request_has_no_mutable_argument_alias(self):
        value = self.request().binding()
        decoded = DeterministicReadRequest.from_value(value)
        value["arguments"]["revision_id"] = UNIT
        output = decoded.binding()
        output["arguments"]["revision_id"] = UNIT
        self.assertEqual(decoded.binding()["arguments"]["revision_id"], REVISION)

    def test_noncanonical_or_nonjson_arguments_refused(self):
        for value in ('{ "revision_id": "' + REVISION + '"}', '{"revision_id":NaN}', '[]', '{}'):
            with self.subTest(value=value), self.assertRaises(RickyError):
                DeterministicReadRequest(PURSUIT, "aec.estimate.recompute", value)
        value = self.request().binding()
        value["arguments"] = {"revision_id": object()}
        with self.assertRaises(RickyError):
            DeterministicReadRequest.from_value(value)

    def test_exact_request_fields_and_explicit_selection_arrays(self):
        for key in self.request().binding():
            value = self.request().binding()
            del value[key]
            with self.subTest(key=key), self.assertRaises(RickyError):
                DeterministicReadRequest.from_value(value)
        for key, replacement in (("project", None), ("sources", ()), ("measurement_ids", ())):
            value = self.request().binding()
            value[key] = replacement
            with self.subTest(key=key), self.assertRaises(RickyError):
                DeterministicReadRequest.from_value(value)

    def test_selected_measurement_required_for_conversion(self):
        arguments = {"source_kind": "measurement", "source_id": MEASUREMENT, "target_unit_id": UNIT}
        with self.assertRaises(RickyError):
            self.request("aec.quantity.convert", arguments)
        request = self.request("aec.quantity.convert", arguments, measurement_ids=(MEASUREMENT,))
        self.assertEqual(request.measurement_ids, (MEASUREMENT,))

    def test_selection_bounds_duplicates_and_strict_source_types(self):
        source = SourceReference("c" * 64, "revision", 1, "d" * 64, "e" * 64)
        for extra in ({"sources": (source, source)}, {"sources": [source]},
                      {"measurement_ids": (MEASUREMENT, MEASUREMENT)},
                      {"measurement_ids": tuple(str(i) for i in range(9))}):
            with self.subTest(extra=extra), self.assertRaises(RickyError):
                self.request(**extra)
        value = self.request(sources=(source,)).binding()
        for field, replacement in (("page", True), ("excerpt_sha256", "short"), ("extra", 1)):
            changed = deepcopy(value)
            changed["sources"][0][field] = replacement
            with self.subTest(field=field), self.assertRaises(RickyError):
                DeterministicReadRequest.from_value(changed)

    def test_eight_selections_allowed_ninth_refused(self):
        sources = tuple(SourceReference(f"{index:064x}", "revision", 1, "d" * 64, "e" * 64)
            for index in range(9))
        measurements = tuple(f"00000000-0000-4000-8000-{index:012d}" for index in range(9))
        self.request(sources=sources[:8], measurement_ids=measurements[:8])
        for extra in ({"sources": sources}, {"measurement_ids": measurements}):
            with self.subTest(extra=extra), self.assertRaises(RickyError):
                self.request(**extra)

    def test_missing_source_field_and_noncanonical_record_refs_refused(self):
        source = SourceReference("c" * 64, "native-revision", 1, "d" * 64, "e" * 64)
        value = self.request(sources=(source,)).binding()
        del value["sources"][0]["source_sha256"]
        with self.assertRaises(RickyError):
            DeterministicReadRequest.from_value(value)
        for reference in ("native-record", None, True):
            with self.subTest(reference=reference), self.assertRaises(RickyError):
                self.request(arguments={"revision_id": reference})

    def test_company_run_roundtrip_preserves_original_body(self):
        run = self.stored_run()
        before = canonical(run)
        self.assertEqual(decode_run_authority(run), self.authority())
        self.assertEqual(canonical(run), before)

    def test_run_header_cannot_rebind_original_identity_scope_or_session(self):
        replacements = {"id": UNIT, "person": "another-native-person", "user": "alias@example.invalid",
            "company": "Other Company", "project": "Project", "scope_type": "Project",
            "request_kind": "model-run", "original_session_reference": "c" * 64}
        for key, value in replacements.items():
            changed = self.stored_run()
            changed[key] = value
            with self.subTest(key=key), self.assertRaises(RickyError):
                decode_run_authority(changed)

    def test_run_request_cannot_be_reselected_after_binding(self):
        changed = self.stored_run()
        changed["request"]["arguments"]["revision_id"] = UNIT
        with self.assertRaises(RickyError):
            decode_run_authority(changed)

    def test_read_context_is_distinct_and_integrity_only(self):
        request = self.request()
        context = request.read_context(self.authority(request))
        self.assertIs(type(context), CompanyReadContext)
        self.assertFalse(isinstance(context, Authority))
        self.assertFalse(hasattr(context, "project"))
        self.assertFalse(hasattr(context, "require_permission"))
        with self.assertRaises(RickyError):
            request.read_context(self.authority(selection_digest="f" * 64))

    def test_actual_original_project_fixture_golden_bytes(self):
        original = FixtureBackend().actor
        decoded = decode_authority(original.binding())
        self.assertIs(type(decoded), Authority)
        self.assertEqual(canonical(decoded.binding()), canonical(original.binding()))
        self.assertEqual(digest(decoded.binding()), "ffe116fff7996674d7ad92b159697fe28057b3eaab6a7396f5a0d5706032aea8")
        self.assertIsNone(decoded.session_reference)

    def test_actual_existing_project_engine_run_body_and_hash_unchanged(self):
        store = FixtureStore()
        service = RickyService(store, FixtureBackend(), FixtureAdapter())
        presented = service.start("Fixture Company", "Fixture Project", "Fixture read?", OPERATION)
        run = store.get("run", presented["id"])
        before = canonical(run), digest(run)
        self.assertEqual(decode_run_authority(run), FixtureBackend().actor)
        self.assertEqual((canonical(run), digest(run)), before)

    def test_project_binding_never_implicitly_becomes_company(self):
        original = FixtureBackend().actor.binding()
        for key, value in (("project", None), ("scope_type", "Company"), ("schema", AUTHORITY_SCHEMA)):
            changed = dict(original, **{key: value})
            with self.subTest(key=key), self.assertRaises(RickyError):
                decode_authority(changed)


if __name__ == "__main__":
    unittest.main()

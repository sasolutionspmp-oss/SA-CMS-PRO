"""Strict authored-text admission and the six fixed local routes."""
import json
import unittest

from apps.cipher import library_wire as wire


class LibraryWireTests(unittest.TestCase):
    def create(self, **changes):
        return {"kind": "contract_clause", "title": "Synthetic quality clause", "text": "Original authored synthetic clause.\nSecond paragraph.",
                "sourceLocator": "Author editor / clause 1", **changes}

    def decode(self, body, action="library.create", **options):
        return wire.decode_action_body(action, json.dumps(body).encode(), **options)

    def test_all_six_fixed_routes_have_their_exact_resource_and_action(self):
        self.assertEqual(len(wire.ACTION_ROUTES), 6)
        for route in wire.ACTION_ROUTES:
            path = route.template.replace("{id}", "synthetic_reference")
            self.assertEqual(wire.resolve_action_route(path), (route, "synthetic_reference", False))
            self.assertEqual(wire.resolve_action_route(path + ":preflight"), (route, "synthetic_reference", True))
        for route in ("execute", "library-entries/a/delete", "adoption-approvals/a/send", "projects/a/create-entry/extra",
                      "projects/a%2Fb/create-entry", "projects/../create-entry"):
            with self.subTest(route=route), self.assertRaises(wire.WireRefusal):
                wire.resolve_action_route(route)

    def test_actual_text_byte_limit_accepts_escape_expansion_and_preserves_exact_text(self):
        text = "x" + "\x01" * 65535
        self.assertGreater(len(json.dumps(self.create(text=text)).encode()), 384000)
        self.assertEqual(self.decode(self.create(text=text))["text"], text)
        for text in ("x" * 65537, "é" * 32769, "😀" * 16385):
            with self.subTest(length=len(text)), self.assertRaises(wire.WireRefusal):
                self.decode(self.create(text=text))
        self.assertEqual(self.decode(self.create(text="é" * 32768))["text"], "é" * 32768)

    def test_text_rejects_null_empty_invalid_utf8_and_nontext_without_normalization(self):
        for text in (None, 5, True, [], {}, "", " \n\t ", "Contains\x00NUL", "\ud800"):
            with self.subTest(text=repr(text)), self.assertRaises(wire.WireRefusal):
                self.decode(self.create(text=text))
        text = "  Exact authored text.\r\n\tKeep whitespace.  "
        self.assertEqual(self.decode(self.create(text=text))["text"], text)

    def test_exact_native_bodies_reject_actor_policy_source_and_delivery_selectors(self):
        for field in ("actor", "personId", "role", "projectId", "rightsUse", "processor", "filePath", "provider", "recipient", "execute"):
            with self.subTest(field=field), self.assertRaises(wire.WireRefusal):
                self.decode(self.create(**{field: "caller-selected"}))
        for field in self.create():
            body = self.create(); del body[field]
            with self.subTest(field=field), self.assertRaises(wire.WireRefusal):
                self.decode(body)

    def test_revise_and_reference_bodies_keep_exact_original_revision_and_intent(self):
        revise = {"previousRevisionId": "librev_original", "text": "New authored text", "sourceLocator": "Editor / section 2", "changeReason": "Synthetic wording correction"}
        self.assertEqual(self.decode(revise, "library.revise"), revise)
        reference = {"targetLocator": "Project specification / section 01", "purpose": "Internal project reference"}
        self.assertEqual(self.decode(reference, "library.prepareReference"), reference)
        for field, value in (("previousRevisionId", "../foreign"), ("changeReason", ""), ("sourceLocator", "\ud800")):
            with self.subTest(field=field), self.assertRaises(wire.WireRefusal):
                self.decode({**revise, field: value}, "library.revise")

    def test_effect_fingerprint_is_required_once_and_not_accepted_in_review_body(self):
        for action in ("library.requestAdoption", "library.approveAdoption", "library.applyAdoption"):
            self.assertEqual(self.decode({}, action), {})
            self.assertEqual(self.decode({"fingerprint": "reviewed_private_fp"}, action, effect=True), {"fingerprint": "reviewed_private_fp"})
            with self.assertRaises(wire.WireRefusal): self.decode({}, action, effect=True)
            with self.assertRaises(wire.WireRefusal): self.decode({"fingerprint": "reviewed_private_fp"}, action)

    def test_duplicate_fields_nonobjects_floats_and_incomplete_json_are_refused(self):
        for raw in (b'{"title":"first","title":"second"}', b'[]', b'null', b'{"value":1.0}', b'{"value":NaN}', b'{', b'\xff', b'{}{}'):
            with self.subTest(raw=raw), self.assertRaises(wire.WireRefusal): wire.parse_json(raw)

    def test_plain_metadata_remains_bounded_and_control_free(self):
        for field, value in (("title", "x" * 201), ("title", "\nTitle"), ("kind", "licensed_standard"),
                             ("sourceLocator", "x" * 1001), ("sourceLocator", "")):
            with self.subTest(field=field), self.assertRaises(wire.WireRefusal):
                self.decode(self.create(**{field: value}))

    def test_collection_filters_are_fixed_and_duplicate_or_oversized_queries_refuse(self):
        self.assertEqual(wire.collection_query("library-entries", "kind=contract_clause&top=1&search=authored"),
                         {"kind": "contract_clause", "top": "1", "search": "authored"})
        for query in ("projectId=a&projectId=b", "provider=x", "top=0", "top=51", "top=1.0", "top=١", "search=", "search=" + "x" * 201):
            with self.subTest(query=query), self.assertRaises(wire.WireRefusal): wire.collection_query("library-entries", query)
        with self.assertRaises(wire.WireRefusal): wire.collection_query("projects", "projectId=a")


if __name__ == "__main__":
    unittest.main()

"""Exact nine-action RFI bodies, ordered citations and synthetic recipients."""
import json
import unittest

from apps.cipher import rfi_wire as wire


class RFIWireTests(unittest.TestCase):
    def create(self, **changes):
        return {"subject": "Synthetic drainage alignment", "question": "Which reviewed drainage alignment applies?\nGrid C4.",
                "drawingRevisionIds": ["dwr_issued_B", "dwr_issued_A"], "documentRevisionIds": ["rev_note_2", "rev_note_1"], **changes}

    def draft(self, **changes):
        return {"responseText": "Synthetic reviewed response.\nUse the east alignment.", "costImpact": "1250.00", "scheduleImpactDays": 3, **changes}

    def decode(self, body, action="rfi.create", **options):
        return wire.decode_action_body(action, json.dumps(body).encode(), **options)

    def test_nine_fixed_routes_keep_native_resource_and_duty_boundaries(self):
        self.assertEqual(len(wire.ACTION_ROUTES), 9)
        self.assertEqual([route.duty for route in wire.ACTION_ROUTES], ["staff", "staff"] + ["pm"] * 7)
        for definition in wire.ACTION_ROUTES:
            route = definition.template.replace("{id}", "synthetic_original")
            self.assertEqual(wire.resolve_action_route(route), (definition, "synthetic_original", False))
            self.assertEqual(wire.resolve_action_route(route + ":preflight"), (definition, "synthetic_original", True))
        for route in ("execute", "rfis/a/link-change", "rfis/a/approve", "rfis/a/distribute", "rfis/../draft-response", "projects/a%2Fb/rfis"):
            with self.subTest(route=route), self.assertRaises(wire.WireRefusal): wire.resolve_action_route(route)

    def test_12000_unicode_codepoints_fit_even_with_json_surrogate_escape_expansion(self):
        body = self.create(question="😀" * 12000)
        self.assertGreater(len(json.dumps(body).encode()), 131072)
        self.assertEqual(self.decode(body), body)
        for text in ("x" * 12001, "😀" * 12001):
            with self.subTest(length=len(text)), self.assertRaises(wire.WireRefusal): self.decode(self.create(question=text))
        for text in ("", " \n\t ", "Question\x00NUL", "\ud800", None, 1):
            with self.subTest(text=repr(text)), self.assertRaises(wire.WireRefusal): self.decode(self.create(question=text))

    def test_citation_order_is_retained_and_missing_duplicate_or_foreign_shape_ids_refuse(self):
        body = self.create()
        result = self.decode(body)
        self.assertEqual(result["drawingRevisionIds"], ["dwr_issued_B", "dwr_issued_A"])
        self.assertEqual(result["documentRevisionIds"], ["rev_note_2", "rev_note_1"])
        for value in ([], ["rev_a"] * 2, ["rev_" + str(n) for n in range(13)], ["../foreign"], [{"id": "rev_a"}], "rev_a"):
            for field in ("drawingRevisionIds", "documentRevisionIds"):
                with self.subTest(field=field, value=value), self.assertRaises(wire.WireRefusal): self.decode(self.create(**{field: value}))

    def test_optional_cost_and_days_remain_exact_distinct_null_zero_and_nonbool(self):
        for cost, days in ((None, None), ("0.00", 0), ("999999999999.99", 9007199254740991), ("1250.25", 365)):
            body = self.draft(costImpact=cost, scheduleImpactDays=days)
            self.assertEqual(self.decode(body, "rfi.draftResponse"), body)
        for cost in (True, 1, 1.25, "1", "1.0", "+1.00", "01.00", "-1.00", "1e2", "1000000000000.00"):
            with self.subTest(cost=cost), self.assertRaises(wire.WireRefusal): self.decode(self.draft(costImpact=cost), "rfi.draftResponse")
        for days in (True, False, -1, "3", 1.5, 9007199254740992):
            with self.subTest(days=days), self.assertRaises(wire.WireRefusal): self.decode(self.draft(scheduleImpactDays=days), "rfi.draftResponse")

    def test_recipients_are_only_the_fixed_distinct_synthetic_subset_in_selected_order(self):
        recipients = [wire.RECIPIENTS[2], wire.RECIPIENTS[0]]
        self.assertEqual(self.decode({"recipients": recipients}, "rfi.setDistribution"), {"recipients": recipients})
        for value in ([], [wire.RECIPIENTS[0]] * 2, ["actual@example.com"], ["OWNER@SYNTHETIC-RFI.INVALID"], [None], [{}], "mail-sink"):
            with self.subTest(value=value), self.assertRaises(wire.WireRefusal): self.decode({"recipients": value}, "rfi.setDistribution")

    def test_actor_role_provider_channel_dates_and_change_selectors_never_enter_body(self):
        for field in ("actor", "personId", "role", "provider", "channel", "filePath", "rightsUse", "processor", "periodId", "changeId", "adoptImpact"):
            with self.subTest(field=field), self.assertRaises(wire.WireRefusal): self.decode(self.create(**{field: "caller-selected"}))
        for field in self.create():
            body = self.create(); del body[field]
            with self.subTest(field=field), self.assertRaises(wire.WireRefusal): self.decode(body)

    def test_empty_review_bodies_and_effect_fingerprints_are_separate(self):
        for action in ("rfi.requestResponse", "rfi.approveResponse", "rfi.applyResponse", "rfi.requestDistribution", "rfi.approveDistribution", "rfi.distribute"):
            self.assertEqual(self.decode({}, action), {})
            self.assertEqual(self.decode({"fingerprint": "rfipf1.original"}, action, effect=True), {"fingerprint": "rfipf1.original"})
            with self.assertRaises(wire.WireRefusal): self.decode({"fingerprint": "rfipf1.original"}, action)
            with self.assertRaises(wire.WireRefusal): self.decode({}, action, effect=True)

    def test_duplicate_json_fields_and_unbounded_or_nonobject_json_are_refused(self):
        for raw in (b'{"subject":"a","subject":"b"}', b'{"costImpact":NaN}', b'{"scheduleImpactDays":1.0}', b'[]', b'null', b'{', b'\xff', b'{}{}', b' ' * (wire.MAX_BODY_BYTES + 1)):
            with self.subTest(raw=raw[:100]), self.assertRaises(wire.WireRefusal): wire.parse_json(raw)

    def test_fixed_collection_filters_reject_unknown_duplicates_and_unscoped_projection_selectors(self):
        self.assertEqual(wire.collection_query("rfis", "projectId=prj_owned&status=open&top=1&search=drainage"),
            {"projectId": "prj_owned", "status": "open", "top": "1", "search": "drainage"})
        for query in ("actor=pm", "projectId=a&projectId=b", "top=0", "top=51", "top=1.0", "status=approved", "asOf=2026-10-15", "search=", "projectId=../hidden"):
            with self.subTest(query=query), self.assertRaises(wire.WireRefusal): wire.collection_query("rfis", query)
        with self.assertRaises(wire.WireRefusal): wire.collection_query("projects", "projectId=hidden")


if __name__ == "__main__":
    unittest.main()

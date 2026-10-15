"""Scratch wire integration checks against genuine registered commercial fixture.

These do not qualify acceptance/source provenance; that prerequisite has its
own independent red-first reproductions. No repository implementation changes.
"""
import copy
import json
import unittest
from unittest.mock import patch

from apps.cipher.ap_contract import APRefusal
from apps.cipher.ap_sessions import authority_for as ap_authority_for
from apps.cipher.core.money import money

from apps.cipher.commercial_practice_fixture import make_commercial_practice_fixture
from apps.cipher.commercial_sessions import authority_for
from apps.cipher.commercial_wire import (
    ACTION_ROUTES, MAX_LINES, WireRefusal, collection_query, decode_action_body,
    normalized_economics, resolve_action_route, scoped_estimate_inventory,
    scoped_estimate_row, scoped_previous_lines, scoped_revision_row,
)


class CommercialWireDraftTests(unittest.TestCase):
    def setUp(self):
        self.c = make_commercial_practice_fixture()
        self.addCleanup(self.c.db.close)
        self.records = self.c.commercial_practice_records
        self.preparer_id = self.c.commercial_practice_persona_people["preparer"]["person_id"]
        self.authority = authority_for(self.c, self.preparer_id)

    def input(self, *, revise=False):
        result = {"documentRevisionId": self.records["current_drawing_revision_id"],
                  "lines": [{"description": "Manual exact measured scope", "quantity": "0.005", "unit": "LF",
                             "unitPriceCents": 100, "sourceLocator": "A-101, detail 2", "costCode": "33-110"}],
                  "priceBookRef": "Synthetic manual rates v1", "inclusions": ["Manual scope"],
                  "exclusions": ["Excavation"], "contingencyRate": "0.05",
                  "measurementBasis": "Manually entered synthetic quantity; geometry unverified"}
        if revise:
            estimate = self.c.estimates.get(self.records["current_estimate_id"])
            result["lines"][0]["previousLineId"] = estimate["lines"][0]["id"]
            result["removedExclusions"] = []
        return result

    def decode(self, action, body, *, effect=False):
        return decode_action_body(action, json.dumps(body).encode(), effect=effect)

    def snapshot(self):
        with self.c.db._lock:
            return (tuple(self.c.db.conn.iterdump()), self.c.db.conn.total_changes,
                    tuple(self.c.provider.submissions), dict(self.c.provider.transfers))

    def test_manual_preview_matches_actual_engine_once_rounded_money_without_writes(self):
        body = self.decode("estimate.create", self.input())
        before = self.snapshot()
        projected = normalized_economics(body)
        self.assertEqual(projected["lines"][0]["amountCents"], 1)
        self.assertEqual(projected["totalCents"], 1)
        self.assertEqual(projected["lines"][0]["measurementMethod"], "manual_entry")
        self.assertFalse(projected["lines"][0]["verifiedGeometry"])
        self.assertEqual(self.snapshot(), before)
        estimate = self.c.estimates.create(
            self.records["project_id"], body["documentRevisionId"], [{
                "description": body["lines"][0]["description"], "quantity": body["lines"][0]["quantity"],
                "unit": body["lines"][0]["unit"], "unit_price": "1.00"}], self.authority.login,
            price_book_ref=body["priceBookRef"], inclusions=body["inclusions"], exclusions=body["exclusions"],
            contingency_rate=body["contingencyRate"], measurement_basis=body["measurementBasis"])
        self.assertEqual(projected["subtotalCents"], int(money(estimate["subtotal"]) * 100))
        self.assertEqual(projected["contingencyCents"], int(money(estimate["contingency"]) * 100))
        self.assertEqual(projected["totalCents"], int(money(estimate["total"]) * 100))

    def test_exact_original_quantity_is_retained_before_server_normalization(self):
        body = self.input()
        body["lines"][0]["quantity"] = "12.0000"
        body["lines"][0]["costCode"] = "  div 33  pipe "
        decoded = self.decode("estimate.create", body)
        self.assertEqual(decoded["lines"][0]["quantity"], "12.0000")
        self.assertEqual(normalized_economics(decoded)["lines"][0]["quantity"], "12")
        self.assertEqual(normalized_economics(decoded)["lines"][0]["costCode"], "DIV 33 PIPE")
        self.assertEqual(decoded, body)  # Original wire body remains the receipt request identity.

    def test_duplicate_top_and_nested_fields_are_refused_without_writes(self):
        body = json.dumps(self.input())
        duplicate_line = body.replace('"quantity": "0.005"', '"quantity": "0.005", "quantity": "1"')
        duplicate_top = body.replace('"contingencyRate": "0.05"', '"contingencyRate": "0.05", "contingencyRate": "0"')
        before = self.snapshot()
        for raw in (duplicate_line, duplicate_top):
            with self.assertRaises(WireRefusal) as caught:
                decode_action_body("estimate.create", raw.encode())
            self.assertEqual(caught.exception.status, 422)
        self.assertEqual(self.snapshot(), before)

    def test_floats_bools_nonfinite_and_unsafe_or_string_cents_are_refused(self):
        before = self.snapshot()
        for field, bad in (("quantity", 0.5), ("quantity", True), ("quantity", "NaN"),
                           ("quantity", "1e3"), ("quantity", "-1"), ("quantity", "$1.00"),
                           ("unitPriceCents", True), ("unitPriceCents", 1.0), ("unitPriceCents", "100"),
                           ("unitPriceCents", 9_007_199_254_740_992), ("unitPriceCents", -1)):
            body = self.input()
            body["lines"][0][field] = bad
            with self.assertRaises(WireRefusal):
                self.decode("estimate.create", body)
        raw = json.dumps(self.input()).replace('"unitPriceCents": 100', '"unitPriceCents": Infinity')
        with self.assertRaises(WireRefusal):
            decode_action_body("estimate.create", raw.encode())
        self.assertEqual(self.snapshot(), before)

    def test_precision_units_and_engine_money_range_are_checked_by_server_arithmetic(self):
        for field, bad in (("quantity", "1.234567890123456"), ("quantity", "10000000000000"),
                           ("unit", "FURL"), ("unitPriceCents", 999_999_999_999_999)):
            body = self.input()
            body["lines"][0][field] = bad
            if field == "unitPriceCents":
                body["lines"][0]["quantity"] = "2"
            decoded = self.decode("estimate.create", body)
            with self.assertRaises(WireRefusal):
                normalized_economics(decoded)

    def test_visible_scope_conflicts_and_out_of_engine_rate_are_refused(self):
        body = self.input()
        body["inclusions"] = ["SCOPE"]
        body["exclusions"] = ["ｓｃｏｐｅ"]  # Engine key normalization, not simple case folding.
        with self.assertRaises(WireRefusal):
            normalized_economics(self.decode("estimate.create", body))
        for value in ("0.500001", "0.0500001", "0.05e0", True, 0.05):
            body = self.input()
            body["contingencyRate"] = value
            with self.assertRaises(WireRefusal):
                self.decode("estimate.create", body)

    def test_extra_source_price_actor_and_package_fields_are_refused_for_all_seven(self):
        before = self.snapshot()
        for definition in ACTION_ROUTES:
            baseline = self.input(revise=definition.action == "estimate.revise") if definition.action in (
                "estimate.create", "estimate.revise") else {}
            self.decode(definition.action, baseline)
            self.decode(definition.action, {**baseline, "fingerprint": "server-review"}, effect=True)
            for field in ("actor", "personId", "role", "provider", "supplierId", "packageId", "retainageRate", "sovLines"):
                with self.assertRaises(WireRefusal):
                    self.decode(definition.action, {**baseline, field: "forged"})
        body = self.input()
        body["lines"][0]["amountCents"] = 500
        with self.assertRaises(WireRefusal):
            self.decode("estimate.create", body)
        self.assertEqual(self.snapshot(), before)

    def test_bounded_json_lines_and_text_never_create_records(self):
        before = self.snapshot()
        body = self.input()
        body["lines"] *= MAX_LINES + 1
        with self.assertRaises(WireRefusal):
            self.decode("estimate.create", body)
        body = self.input()
        body["measurementBasis"] = "X" * 401
        with self.assertRaises(WireRefusal):
            self.decode("estimate.create", body)
        body["measurementBasis"] = "\u200b"
        with self.assertRaises(WireRefusal):
            self.decode("estimate.create", body)
        with self.assertRaises(WireRefusal):
            decode_action_body("estimate.request", b" " * 16_385)
        self.assertEqual(self.snapshot(), before)

    def test_fixed_action_routes_include_only_same_path_preflight(self):
        for definition in ACTION_ROUTES:
            path = definition.template.replace("{id}", "record-id")
            self.assertEqual(resolve_action_route(path), (definition, "record-id", False))
            self.assertEqual(resolve_action_route(path + ":preflight"), (definition, "record-id", True))
        for path in ("module/estimate.approve", "estimates/id/send", "estimates/id/sign", "workspace/open",
                     "estimates/id/execute", "estimate-handoffs/id/provider", "projects/../create-estimate"):
            with self.assertRaises(WireRefusal) as caught:
                resolve_action_route(path)
            self.assertEqual(caught.exception.status, 404)

    def test_queries_refuse_identity_duplicate_and_unbounded_filters(self):
        for query in ("actor=owner", "projectId=one&projectId=two", "top=0", "top=51", "top=1.0", "search=", "bad"):
            with self.assertRaises(WireRefusal):
                collection_query("estimates", query)
        self.assertEqual(collection_query("estimates", "search=manual&top=20"), {"search": "manual", "top": "20"})
        with self.assertRaises(WireRefusal):
            collection_query("projects", "projectId=hidden")

    def test_scope_first_inventory_and_details_do_not_touch_hidden_estimate_presenter(self):
        before = self.snapshot()
        with patch.object(self.c.estimates, "get", side_effect=AssertionError("Must scope before the presenter")):
            candidates = scoped_estimate_inventory(self.c, self.authority)
            self.assertEqual({row["id"] for row in candidates}, {
                self.records["superseded_estimate_id"], self.records["current_estimate_id"]})
            with self.assertRaises(WireRefusal) as caught:
                scoped_estimate_row(self.c, self.authority, self.records["hidden_estimate_id"])
            self.assertEqual(caught.exception.status, 404)
            self.assertNotIn(self.records["hidden_estimate_id"], str(caught.exception))
            with self.assertRaises(WireRefusal):
                scoped_estimate_inventory(self.c, self.authority, project_id=self.records["hidden_project_id"])
        self.assertEqual(self.snapshot(), before)

    def test_previous_line_identity_and_source_revision_must_belong_to_exact_scope(self):
        body = self.decode("estimate.revise", self.input(revise=True))
        scoped_previous_lines(self.c, self.authority, self.records["current_estimate_id"], body["lines"])
        scoped_revision_row(self.c, self.authority, body["documentRevisionId"], project_id=self.records["project_id"])
        hidden = self.c.estimates.get(self.records["hidden_estimate_id"])
        foreign = copy.deepcopy(body)
        foreign["lines"][0]["previousLineId"] = hidden["lines"][0]["id"]
        with self.assertRaises(WireRefusal) as caught:
            scoped_previous_lines(self.c, self.authority, self.records["current_estimate_id"], foreign["lines"])
        self.assertEqual(caught.exception.status, 404)
        with self.assertRaises(WireRefusal):
            scoped_revision_row(self.c, self.authority, hidden["document_revision_id"], project_id=self.records["project_id"])
        duplicate = copy.deepcopy(body)
        duplicate["lines"].append(copy.deepcopy(duplicate["lines"][0]))
        with self.assertRaises(WireRefusal):
            self.decode("estimate.revise", duplicate)

    def test_real_estimator_authority_does_not_broaden_original_ap_resolver(self):
        self.assertEqual(self.authority.duties, ("estimator",))
        self.assertTrue(self.authority.allows(self.records["project_id"], "estimator"))
        self.assertNotIn(self.records["hidden_project_id"], self.authority.project_ids)
        original_ap = ap_authority_for(self.c, self.preparer_id)
        self.assertEqual(original_ap.duties, ())
        self.assertEqual(original_ap.project_ids, ())
        pm = authority_for(self.c, self.c.commercial_practice_persona_people["pm"]["person_id"])
        with self.assertRaises(APRefusal) as caught:
            pm.require(self.records["project_id"], "estimator")
        self.assertEqual(caught.exception.status, 403)


if __name__ == "__main__":
    unittest.main()

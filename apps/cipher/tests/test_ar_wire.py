"""Strict fixed AR routes and exact claimed/reviewed source wire values."""
import copy
import json
import unittest

from apps.cipher.ar_wire import (
    ACTION_ROUTES, ACTIONS, CONTRACT_VERSION, MAX_BODY_BYTES, WireRefusal,
    collection_query, dated_query, decode_action_body, parse_json, resolve_action_route,
)


def preparation():
    return {"claimRevisionId": "rev_claim", "reviewRevisionId": "rev_review", "periodId": "period_october",
            "lines": [{"lineId": "U1", "claimedCumulative": "35.125", "reviewedCumulative": "30.125",
                       "differenceReason": "Five claimed items were not verified in the review.",
                       "claimSourceLocator": "Owner claim, page 2, item U1", "reviewSourceLocator": "Certification, page 3, item U1"},
                      {"lineId": "L2", "claimedCumulative": "60000.00", "reviewedCumulative": "50000.00",
                       "differenceReason": "Testing remains incomplete.",
                       "claimSourceLocator": "Owner claim, page 2, item L2", "reviewSourceLocator": "Certification, page 3, item L2"}]}


def decode(body, action="ownerBill.prepare", *, effect=False):
    return decode_action_body(action, json.dumps(body).encode(), effect=effect)


class ARWireTests(unittest.TestCase):
    def test_fixed_seven_actions_resources_and_actual_duty_groups(self):
        self.assertEqual(CONTRACT_VERSION, "cipher.ar-practice.v1")
        self.assertEqual(len(ACTIONS), 7)
        self.assertEqual([(route.resource_type, route.duty) for route in ACTION_ROUTES], [
            ("basis", "pm"), ("bill", "pm"), ("businessApproval", "accounting"), ("bill", "accounting"),
            ("bill", "send"), ("sendApproval", "send"), ("sendApproval", "send")])
        for route in ACTION_ROUTES:
            path = route.template.replace("{id}", "record_1")
            self.assertEqual(resolve_action_route(path), (route, "record_1", False))
            self.assertEqual(resolve_action_route(path + ":preflight"), (route, "record_1", True))
        for path in ("actions", "owner-bills/x/execute", "owner-bills/x/send", "owner-bases/../prepare-bill",
                     "owner-bills/x/post/extra", "owner-bills/x/post?actor=owner"):
            with self.subTest(path=path), self.assertRaises(WireRefusal) as caught:
                resolve_action_route(path)
            self.assertEqual(caught.exception.status, 404)

    def test_complete_preparation_retains_exact_original_values_without_mutation(self):
        body = preparation()
        before = copy.deepcopy(body)
        result = decode(body)
        self.assertEqual(result, before)
        self.assertEqual(body, before)
        self.assertEqual(result["lines"][1]["claimedCumulative"], "60000.00")
        self.assertNotEqual(result["claimRevisionId"], result["reviewRevisionId"])

    def test_other_actions_only_admit_the_fingerprint_at_effect_time(self):
        for action in ACTIONS - {"ownerBill.prepare"}:
            self.assertEqual(decode({}, action), {})
            self.assertEqual(decode({"fingerprint": "arpf1.reviewed"}, action, effect=True), {"fingerprint": "arpf1.reviewed"})
            for body in ({"actor": "owner"}, {"periodId": "period_other"}, {"approvalId": "other"},
                         {"provider": "live"}, {"fingerprint": "preflight-cannot-supply-proof"}):
                with self.subTest(action=action, body=body), self.assertRaises(WireRefusal):
                    decode(body, action)
        with self.assertRaises(WireRefusal):
            decode({}, "ownerBill.post", effect=True)

    def test_body_cannot_supply_previous_rates_dates_recipients_or_actor_authority(self):
        for field, value in (("actor", "owner"), ("actorRole", "accountant"), ("mode", "live"), ("path", "live.sqlite"),
                             ("provider", {}), ("invoiceDate", "2026-10-01"), ("dueDate", "2026-10-31"),
                             ("retainageRate", "0"), ("previousCertifiedCents", 0), ("recipients", ["outside@example.invalid"])):
            body = preparation()
            body[field] = value
            with self.subTest(field=field), self.assertRaises(WireRefusal):
                decode(body)
        for field, value in (("previousCumulative", "0"), ("unitPriceCents", 1), ("basis", "unitPrice"),
                             ("sourceLocator", "combined evidence"), ("verified", True)):
            body = preparation()
            body["lines"][0][field] = value
            with self.subTest(field=field), self.assertRaises(WireRefusal):
                decode(body)

    def test_measure_fields_refuse_floats_booleans_exponents_signs_and_localized_values(self):
        for field in ("claimedCumulative", "reviewedCumulative"):
            for value in (1, 1.0, True, None, "1e3", "+1", "-1", "01", "1,000", "$1", "NaN", "1.0000001", "1000000000000"):
                body = preparation()
                body["lines"][0][field] = value
                with self.subTest(field=field, value=value), self.assertRaises(WireRefusal):
                    decode(body)

    def test_exact_fields_separate_evidence_and_unique_complete_line_entries(self):
        invalid = []
        same = preparation()
        same["reviewRevisionId"] = same["claimRevisionId"]
        invalid.append(same)
        missing_claim = preparation()
        del missing_claim["claimRevisionId"]
        invalid.append(missing_claim)
        duplicate = preparation()
        duplicate["lines"].append(copy.deepcopy(duplicate["lines"][0]))
        invalid.append(duplicate)
        empty = preparation()
        empty["lines"] = []
        invalid.append(empty)
        incomplete = preparation()
        del incomplete["lines"][0]["reviewSourceLocator"]
        invalid.append(incomplete)
        for body in invalid:
            with self.subTest(body=body), self.assertRaises(WireRefusal):
                decode(body)

    def test_bounded_text_references_and_fingerprints(self):
        for field, value in (("claimRevisionId", "../foreign"), ("periodId", True), ("reviewRevisionId", "x" * 129)):
            body = preparation()
            body[field] = value
            with self.subTest(field=field), self.assertRaises(WireRefusal):
                decode(body)
        for field, value in (("lineId", "x" * 65), ("differenceReason", "x" * 501),
                             ("claimSourceLocator", ""), ("reviewSourceLocator", "x" * 241),
                             ("differenceReason", "Hidden\nfield")):
            body = preparation()
            body["lines"][0][field] = value
            with self.subTest(field=field), self.assertRaises(WireRefusal):
                decode(body)
        body = preparation()
        body["lines"][0]["differenceReason"] = ""
        self.assertEqual(decode(body)["lines"][0]["differenceReason"], "")  # Domain checks the actual difference.
        for fingerprint in (None, True, "", "x" * 257):
            with self.subTest(fingerprint=fingerprint), self.assertRaises(WireRefusal):
                decode({"fingerprint": fingerprint}, "ownerBill.post", effect=True)

    def test_strict_json_refuses_duplicate_keys_at_every_depth_and_nonfinite_values(self):
        for raw in (b'{"a":1,"a":2}', b'{"lines":[{"lineId":"U1","lineId":"L2"}]}',
                    b'{"value":NaN}', b'{"value":Infinity}', b'{"value":1.0}', b'[]', b'null', b'{}\xff'):
            with self.subTest(raw=raw), self.assertRaises(WireRefusal):
                parse_json(raw)
        self.assertEqual(parse_json(b'{}'), {})

    def test_json_body_size_and_line_inventory_are_bounded(self):
        for raw in (b"", b" " * (MAX_BODY_BYTES + 1)):
            with self.assertRaises(WireRefusal):
                parse_json(raw)
        body = preparation()
        template = body["lines"][0]
        body["lines"] = [{**template, "lineId": "L" + str(index)} for index in range(101)]
        with self.assertRaises(WireRefusal):
            decode(body)

    def test_dated_aging_query_preserves_calendar_dates(self):
        self.assertEqual(dated_query("2026-10-31"), "2026-10-31")
        self.assertEqual(dated_query("2024-02-29"), "2024-02-29")
        result = collection_query("ar-aging", "projectId=project_1&asOf=2026-10-31&top=10")
        self.assertEqual(result, {"projectId": "project_1", "asOf": "2026-10-31", "top": "10"})
        for value in ("2026-02-29", "2026-11-31", "20261031", "10/31/2026", "2026-10-31T00:00:00Z", "0000-01-01", None):
            with self.subTest(value=value), self.assertRaises(WireRefusal):
                dated_query(value)

    def test_fixed_collection_filters_refuse_duplicates_authority_and_ambiguous_dates(self):
        for collection, query in (("owner-bills", "actor=owner"), ("owner-bills", "top=1&top=2"),
                                  ("owner-bills", "search="), ("owner-bills", "top=0"), ("owner-bills", "top=51"),
                                  ("owner-bills", "asOf=2026-10-31"), ("projects", "projectId=other"),
                                  ("owner-bases", "status=approved"), ("ar-aging", "asOf=2026-10-31&asOf=2026-11-30")):
            with self.subTest(collection=collection, query=query), self.assertRaises(WireRefusal):
                collection_query(collection, query)


if __name__ == "__main__":
    unittest.main()

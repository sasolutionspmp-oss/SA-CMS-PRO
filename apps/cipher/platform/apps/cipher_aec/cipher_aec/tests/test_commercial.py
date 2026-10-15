"""Pure authored draft and exact native-boundary contract checks."""
import copy
from decimal import Decimal
import unittest
from uuid import uuid4
from cipher_aec.api.errors import DomainError
from cipher_aec.commercial.contracts import composition, compare, native_order, pricing


def sample():
    group, unit = str(uuid4()), str(uuid4())
    return {"currency": "USD", "price_list": "Synthetic native selling list", "valid_till": "2026-12-31", "terms": "Payment follows a future agreed contract.", "sections": [{"id": str(uuid4()), "kind": "scope", "title": "Scope", "text": "Synthetic authored scope"}], "price_lines": [
        {"id": str(uuid4()), "description": "Base", "quantity": "2", "unit_id": unit, "unit_revision": 1, "rate": "10.25", "alternate_group": group, "selected": True},
        {"id": str(uuid4()), "description": "Alternate", "quantity": "3", "unit_id": unit, "unit_revision": 1, "rate": "8.50", "alternate_group": group, "selected": False}]}


class CommercialContracts(unittest.TestCase):
    def test_selection_exactly_once_and_native_order_preserves_identity(self):
        first = composition(sample())
        self.assertEqual(pricing(first, 2)["total"], "20.50")
        changed = copy.deepcopy(first)
        changed["price_lines"].reverse()
        for line in changed["price_lines"]:
            line["selected"] = not line["selected"]
        self.assertEqual(pricing(changed, 2)["total"], "25.50")
        ordered = native_order(changed["price_lines"])
        self.assertTrue(ordered[0]["selected"])
        self.assertEqual({r["id"] for r in ordered}, {r["id"] for r in first["price_lines"]})
        comparison = compare(first, changed)
        self.assertEqual(len(comparison["price_lines"]["changed"]), 2)
        self.assertEqual(comparison["price_lines"]["added"], [])
        self.assertTrue(comparison["price_lines"]["order_changed"])

    def test_alternate_selection_ambiguous_or_untyped_rejected(self):
        for selected in (True, "false", 1):
            value = sample()
            value["price_lines"][1]["selected"] = selected
            with self.assertRaises(DomainError): composition(value)

    def test_exact_half_up_and_no_binary_input(self):
        value = sample()
        value["price_lines"][0].update(quantity="1", rate="1.005")
        self.assertEqual(pricing(composition(value), 2)["total"], "1.01")
        for bad in (1.005, "1e2", "-0", "01", "1.1234567890", None, {}):
            value["price_lines"][0]["rate"] = bad
            with self.assertRaises(DomainError): composition(value)

    def test_plain_text_and_stable_ids_and_deferred_source(self):
        value = sample()
        value["sections"][0]["text"] = "<script>untrusted authored text</script>"
        self.assertEqual(composition(value)["sections"][0]["text"], value["sections"][0]["text"])
        value["source_references"] = [{"document": "private"}]
        with self.assertRaises(DomainError) as error: composition(value)
        self.assertEqual(error.exception.code, "company_reference_unavailable")
        value.pop("source_references")
        value["price_lines"][1]["id"] = value["price_lines"][0]["id"]
        with self.assertRaises(DomainError): composition(value)

    def test_comparison_preserves_terms_sections_and_removed_lines(self):
        value = composition(sample()); changed = copy.deepcopy(value)
        changed["terms"] = "New terms"
        changed["sections"].append({"id": str(uuid4()), "kind": "exclusion", "title": "Excluded", "text": "No tax assumption"})
        changed["price_lines"].pop()
        result = compare(value, changed)
        self.assertTrue(result["terms"]["changed"])
        self.assertEqual(len(result["sections"]["added"]), 1)
        self.assertEqual(len(result["price_lines"]["removed"]), 1)

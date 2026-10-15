"""Explicit authored examples for exact EST-01 arithmetic; no provider/model."""

from copy import deepcopy
import hashlib
import unittest
from uuid import NAMESPACE_URL, uuid5

from cipher_aec.api.errors import DomainError
from cipher_aec.estimating.calculation import SCHEMA, calculate
from cipher_aec.estimating.contracts import POLICY_VERSION
from cipher_aec.migrations.contracts import SCHEMA as UNIT_SCHEMA


def identity(name):
    return str(uuid5(NAMESPACE_URL, "cipher-explicit-est01-fixture:" + name))


def fixture():
    definitions = {"sf": ("area", 6), "sy": ("area", 6), "cf": ("volume", 6), "cy": ("volume", 6),
                   "lh": ("labor_time", 6), "eh": ("equipment_time", 6), "time": ("time", 6), "each": ("count", 0)}
    units = [{"id": identity(name), "kind": "uom", "revision": 1, "fields": {"symbol": name, "dimension": dimension, "precision": precision}}
             for name, (dimension, precision) in definitions.items()]
    company = {"id": identity("company"), "kind": "company", "revision": 1,
               "fields": {"name": "Explicit EST fixture", "currency": "USD", "timezone": "UTC"}}
    manifest = {"schema": UNIT_SCHEMA, "dataset_id": identity("units"), "scope": {"company": "Explicit EST fixture", "project": "Explicit project"},
                "records": [company, *units], "unit_conversions": [
                    {"id": identity("sy-sf"), "revision": 1, "from_unit_id": identity("sy"), "to_unit_id": identity("sf"), "dimension": "area", "numerator": "9", "denominator": "1", "source": "Explicit square-yard definition fixture"},
                    {"id": identity("cf-cy"), "revision": 1, "from_unit_id": identity("cf"), "to_unit_id": identity("cy"), "dimension": "volume", "numerator": "1", "denominator": "27", "source": "Explicit cubic-yard definition fixture"},
                ]}
    excerpt = "Explicit authored fixture rates: concrete $27 per cubic yard; labor $25 per labor hour; equipment $40 per equipment hour."
    citation = {"id": hashlib.sha256(("citation:" + excerpt).encode()).hexdigest(), "document_id": "DOC-explicit-fixture", "revision_id": "REV-explicit-fixture", "document_title": "Explicit authored rate fixture", "revision_number": 1, "page": 1, "page_label": "1", "excerpt": excerpt,
                "source_sha256": hashlib.sha256(excerpt.encode()).hexdigest(), "excerpt_sha256": hashlib.sha256(excerpt.encode()).hexdigest()}
    rates = {}
    for name, kind, unit, amount in (("material", "material", "cy", "27"), ("labor", "labor", "lh", "25"), ("equipment", "equipment", "eh", "40"), ("tiny", "material", "each", "0.005")):
        key = identity("rate-" + name)
        rates[key] = {"id": key, "source_id": identity("rate-source-" + name), "revision": 1, "predecessor": None,
            "title": "Explicit fixture " + name, "cost_type": kind, "unit_id": identity(unit), "rate_amount": amount,
            "rate_precision": 6, "currency": "USD", "quote_reference": "EXPLICIT-TEST-QUOTE", "quote_date": "2026-10-01", "expiry_date": "2026-10-31",
            "geography": "Explicit synthetic region", "inclusions": "Explicit authored fixture only", "exclusions": "", "freight_tax_assumptions": "No freight or taxes in this explicit fixture",
            "permission_basis": "Explicit synthetic test content", "source_citations": [citation], "item": None, "party_type": None, "party": None}
    def q(amount, unit):
        return {"amount": amount, "unit_id": identity(unit), "precision": definitions[unit][1]}
    assembly = {"id": identity("assembly-r1"), "assembly_id": identity("assembly"), "revision": 1, "predecessor": None,
                "title": "Explicit authored material/labor/equipment assembly", "basis_unit_id": identity("sf"), "author_basis": "Explicit test productivity and material factors", "components": []}
    for name, kind, resource, amount, factor, waste in (("material", "material", "cf", "2", "1.1", "0.05"), ("labor", "labor", "lh", "2", "1", "0"), ("equipment", "equipment", "eh", "1", "1", "0")):
        assembly["components"].append({"line_id": identity("component-" + name), "rate_source_id": identity("rate-" + name), "kind": kind,
                                      "work_quantity": q("10", "sf"), "resource_quantity": q(amount, resource), "material_factor": factor, "waste_fraction": waste})
    line = {"line_id": identity("estimate-line"), "description": "Explicit estimate assembly", "quantity": q("100", "sf"),
            "cost_code": "EXPLICIT-01", "notes": "Authored test quantity, no geometry claim", "alternate": "", "included": True, "assembly_revision_id": assembly["id"]}
    inputs = {"schema": SCHEMA, "unit_manifest": manifest, "currency": "USD", "currency_exponent": 2, "pricing_date": "2026-10-15", "policy_version": POLICY_VERSION,
              "basis_description": "Explicit authored fixture quantities without a geometry/calibration claim", "basis_citations": [],
              "rates": rates, "assemblies": {assembly["id"]: assembly}, "lines": [line], "adjustments": [
                  {"line_id": identity("indirect"), "kind": "indirect", "label": "Explicit overhead", "method": "fraction_of_direct", "value": "0.10", "basis_description": "Ten percent of rounded direct lines"},
                  {"line_id": identity("contingency"), "kind": "contingency", "label": "Explicit contingency", "method": "fixed", "value": "10.00", "basis_description": "Authored fixed synthetic allowance"},
              ]}
    return inputs


class ExactEstimatingTests(unittest.TestCase):
    def setUp(self):
        self.inputs = fixture()

    def denied(self, change, code=None):
        change(self.inputs)
        with self.assertRaises(DomainError) as raised:
            calculate(self.inputs)
        if code:
            self.assertEqual(code, raised.exception.code)

    def test_known_material_waste_labor_productivity_equipment_duration(self):
        result = calculate(self.inputs)
        amounts = {component["cost_type"]: component["allocated_amount"]["amount"] for component in result["lines"][0]["components"]}
        self.assertEqual({"material": "23.10", "labor": "500.00", "equipment": "400.00"}, amounts)
        self.assertEqual("923.10", result["direct"]["amount"])
        self.assertEqual("92.31", result["indirect"]["amount"])
        self.assertEqual("10.00", result["contingency"]["amount"])
        self.assertEqual("1025.41", result["total"]["amount"])
        self.assertEqual("exact-rational", result["policy"]["intermediate"])

    def test_repeating_rational_conversion_is_not_rounded_before_rate(self):
        line = self.inputs["lines"][0]
        line.pop("assembly_revision_id")
        line.update(rate_source_id=identity("rate-material"), material_factor="1", waste_fraction="0", quantity={"amount": "1", "unit_id": identity("cf"), "precision": 6})
        self.inputs["adjustments"] = []
        result = calculate(self.inputs)
        self.assertEqual("1.00", result["total"]["amount"])
        self.assertEqual({"numerator": "1", "denominator": "27"}, result["lines"][0]["components"][0]["priced_quantity_exact"])

    def test_nonnegative_residual_allocation_reconciles_and_is_stable(self):
        assembly = next(iter(self.inputs["assemblies"].values()))
        assembly["basis_unit_id"] = identity("each")
        assembly["components"] = [{"line_id": identity(name), "rate_source_id": identity("rate-tiny"), "kind": "material",
            "work_quantity": {"amount": "1", "unit_id": identity("each"), "precision": 0}, "resource_quantity": {"amount": "1", "unit_id": identity("each"), "precision": 0}, "material_factor": "1", "waste_fraction": "0"} for name in ("residual-a", "residual-b")]
        self.inputs["lines"][0]["quantity"] = {"amount": "1", "unit_id": identity("each"), "precision": 0}
        self.inputs["adjustments"] = []
        first = calculate(self.inputs)
        allocated = {row["component_id"]: row["allocated_amount"]["amount"] for row in first["lines"][0]["components"]}
        self.assertEqual(["0.00", "0.01"], sorted(allocated.values()))
        self.assertEqual("0.01", first["total"]["amount"])
        assembly["components"].reverse()
        self.assertEqual(allocated, {row["component_id"]: row["allocated_amount"]["amount"] for row in calculate(self.inputs)["lines"][0]["components"]})

    def test_invalid_dimensions_and_generic_hour_for_labor_are_refused(self):
        self.denied(lambda data: data["lines"][0]["quantity"].update(unit_id=identity("cf")), "invalid_dimension")
        self.inputs = fixture()
        self.denied(lambda data: data["rates"][identity("rate-labor")].update(unit_id=identity("time")), "invalid_dimension")

    def test_float_boolean_exponent_negativezero_and_precision_are_refused(self):
        for value in (1.2, True, "1e3", "NaN", "-0", "1.0000000000001"):
            self.inputs = fixture()
            self.denied(lambda data: data["lines"][0]["quantity"].update(amount=value))

    def test_client_total_and_duplicate_line_ids_are_refused(self):
        self.denied(lambda data: data.update(total={"amount": "0.01", "currency": "USD"}))
        self.inputs = fixture()
        self.denied(lambda data: data["lines"].append(deepcopy(data["lines"][0])))

    def test_expired_rate_cross_currency_and_unknown_policy_are_refused(self):
        self.denied(lambda data: data.update(pricing_date="2026-11-01"), "expired_rate")
        self.inputs = fixture()
        self.denied(lambda data: data["rates"][identity("rate-material")].update(currency="EUR"))
        self.inputs = fixture()
        self.denied(lambda data: data.update(policy_version="invented-rounding-policy"))

    def test_alternates_are_priced_but_excluded_from_direct_total(self):
        self.inputs["lines"][0].update(included=False, alternate="Explicit excluded alternate")
        self.inputs["adjustments"] = []
        result = calculate(self.inputs)
        self.assertEqual("923.10", result["lines"][0]["extension"]["amount"])
        self.assertEqual("0.00", result["total"]["amount"])

    def test_large_exact_strings_survive_without_javascript_or_float_rounding(self):
        self.inputs["lines"][0]["quantity"]["amount"] = "999999999999.123456"
        self.inputs["rates"][identity("rate-material")]["rate_amount"] = "0.000001"
        self.inputs["rates"][identity("rate-labor")]["rate_amount"] = "0.000001"
        self.inputs["rates"][identity("rate-equipment")]["rate_amount"] = "0.000001"
        result = calculate(self.inputs)
        self.assertEqual("308555.56", result["direct"]["amount"])
        self.assertEqual("339421.12", result["total"]["amount"])
        self.assertEqual("999999999999.123456", result["lines"][0]["quantity"]["amount"])

    def test_output_and_input_digest_are_deterministic(self):
        self.assertEqual(calculate(self.inputs), calculate(deepcopy(self.inputs)))
        first = calculate(self.inputs)
        self.inputs["lines"][0]["notes"] = "Changed authored basis"
        second = calculate(self.inputs)
        self.assertNotEqual(first["input_digest"], second["input_digest"])
        self.assertEqual(first["output_digest"], second["output_digest"])

    def test_overflow_and_zero_quantity_are_explicit(self):
        self.denied(lambda data: data["lines"][0]["quantity"].update(amount="999999999999999999"), "amount_overflow")
        self.inputs = fixture()
        self.inputs["lines"][0]["quantity"]["amount"] = "0"
        self.inputs["adjustments"] = []
        self.assertEqual("0.00", calculate(self.inputs)["total"]["amount"])

    def test_malformed_resource_reference_is_a_validation_error(self):
        for key in ("rate_source_id", "assembly_revision_id"):
            self.inputs = fixture()
            line = self.inputs["lines"][0]
            line.pop("assembly_revision_id")
            line[key] = {"unexpected": "selector"}
            if key == "rate_source_id":
                line.update(material_factor="1", waste_fraction="0")
            with self.assertRaises(DomainError):
                calculate(self.inputs)


if __name__ == "__main__":
    unittest.main()

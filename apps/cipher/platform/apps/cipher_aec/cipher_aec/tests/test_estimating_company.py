"""Explicit synthetic Company contract examples; no native/provider claims."""
from copy import deepcopy
import json
from pathlib import Path
import unittest

from jsonschema import Draft202012Validator
from cipher_aec.api.errors import DomainError
from cipher_aec.estimating.calculation import COMPANY_SCHEMA, calculate
from cipher_aec.estimating import scopes
from cipher_aec.tests.test_estimating_core import fixture

ROOT = Path(__file__).parents[1]


def company_fixture():
    value = deepcopy(fixture())
    value["schema"] = COMPANY_SCHEMA
    value["unit_manifest"]["schema"] = "cipher.canonical.v2"
    value["unit_manifest"]["scope"] = {"scope_type": "Company", "company": "Explicit EST fixture", "project": None}
    for rate in value["rates"].values():
        for citation in rate["source_citations"]:
            citation.update(scope_type="Company", company="Explicit EST fixture", project=None)
    return value


class CompanyEstimatingContractTests(unittest.TestCase):
    def test_project_input_and_result_golden_hashes_preserved(self):
        value = calculate(fixture())
        self.assertEqual(value["input_digest"], "02d506921b438e7295cae18f681dfac4e3bece8e85bcd8a8439e2eff6e8a53b5")
        self.assertEqual(value["output_digest"], "0695edcc1551cec4046c0a298159f8f0af78b7b359b4d9fa6f644472af21a53e")

    def test_company_scope_reuses_exact_arithmetic_without_project(self):
        original, company = calculate(fixture()), calculate(company_fixture())
        for field in ("direct", "indirect", "contingency", "total", "lines", "adjustments", "policy"):
            self.assertEqual(original[field], company[field])
        self.assertNotEqual(original["input_digest"], company["input_digest"])
        self.assertEqual(company["total"]["amount"], "1025.41")

    def test_manifest_and_input_scope_versions_cannot_be_crossed(self):
        for value in (fixture(), company_fixture()):
            value["schema"] = COMPANY_SCHEMA if value["schema"] != COMPANY_SCHEMA else "cipher.estimate.inputs.v1"
            with self.assertRaises(DomainError) as caught:
                calculate(value)
            self.assertEqual(caught.exception.code, "invalid_scope")

    def test_null_project_does_not_activate_company(self):
        with self.assertRaises(DomainError):
            scopes.current("Explicit EST fixture", None)
        with scopes.activate("Company", "Explicit EST fixture", None):
            self.assertEqual(scopes.current("Explicit EST fixture", None).manifest_scope(), {"scope_type": "Company", "company": "Explicit EST fixture", "project": None})
        with self.assertRaises(DomainError):
            scopes.current("Explicit EST fixture", None)

    def test_context_restores_after_error_and_refuses_cross_scope_nesting(self):
        with self.assertRaises(RuntimeError):
            with scopes.activate("Company", "Explicit EST fixture", None):
                with scopes.activate("Company", "Explicit EST fixture", None):
                    with self.assertRaises(DomainError):
                        with scopes.activate("Project", "Explicit EST fixture", "P"):
                            self.fail("Cross-scope nesting was admitted")
                raise RuntimeError("Explicit synthetic failure")
        self.assertEqual(scopes.current("Explicit EST fixture", "P").scope_type, "Project")
        with self.assertRaises(DomainError):
            scopes.current("Explicit EST fixture", None)

    def test_company_schema_and_project_schema_are_distinct(self):
        company = json.loads((ROOT / "estimating/schemas/api-company-v2.schema.json").read_text())
        Draft202012Validator({"$defs": company["$defs"], "$ref": "#/$defs/CompanyEstCalculationInputs"}).validate(company_fixture())
        old = json.loads((ROOT / "estimating/schemas/api-v1.schema.json").read_text())
        validator = Draft202012Validator({"$defs": old["$defs"], "$ref": "#/$defs/EstCalculationInputs"})
        self.assertFalse(validator.is_valid(company_fixture()))
        Draft202012Validator({"$defs": company["$defs"], "$ref": "#/$defs/CompanyCreateEstimateRequest"}).validate({"company": "Explicit EST fixture", "operation_id": "c558771b-94df-45cd-b61b-908450a56b33", "title": "Synthetic", "currency": "USD", "pricing_date": "2026-10-15", "pursuit_id": None})

    def test_company_request_fields_match_literal_entrypoints(self):
        import ast
        names = {"register_unit": "RegisterUnitRequest", "create_conversion": "CreateConversionRequest", "create_rate": "CreateRateRequest", "create_assembly": "CreateAssemblyRequest", "create_estimate": "CreateEstimateRequest", "calculate_revision": "CalculateRevisionRequest", "get_record": "GetEstimateRecordRequest", "list_records": "ListEstimateRecordsRequest", "list_units": "ListEstimateUnitsRequest", "list_acceptances": "ListEstimateAcceptancesRequest", "acceptance_subject": "EstimateAcceptanceSubjectRequest", "accepted_baseline_reference": "AcceptedBaselineReferenceRequest"}
        for domain in ("estimating", "takeoff"):
            defs = json.loads((ROOT / domain / "schemas/api-company-v2.schema.json").read_text())["$defs"]
            if domain == "takeoff":
                names = {"create_set": "TakeoffCreateSetRequest", "create_calibration": "TakeoffCreateCalibrationRequest", "create_measurement": "TakeoffCreateMeasurementRequest", "bind_line": "TakeoffBindLineRequest", "get_record": "TakeoffGetRequest", "list_records": "TakeoffListRequest", "drawing_impact": "TakeoffImpactRequest", "compare_measurements": "TakeoffCompareRequest"}
            for node in ast.parse((ROOT / domain / "company_api.py").read_text()).body:
                if isinstance(node, ast.FunctionDef):
                    fields = set(defs["Company" + names[node.name]]["properties"])
                    self.assertEqual(fields, {arg.arg for arg in node.args.args + node.args.kwonlyargs})
                    self.assertNotIn("project", fields)
                    self.assertNotIn("scope_type", fields)

    def test_all_authoritative_schema_references_resolve(self):
        for relative in ("estimating/schemas/api-v1.schema.json", "estimating/schemas/api-company-v2.schema.json", "takeoff/schemas/api-company-v2.schema.json"):
            value = json.loads((ROOT / relative).read_text())
            Draft202012Validator.check_schema(value)
            def walk(node):
                if type(node) is dict:
                    if "$ref" in node:
                        self.assertIn(node["$ref"].removeprefix("#/$defs/"), value["$defs"])
                    for child in node.values(): walk(child)
                elif type(node) is list:
                    for child in node: walk(child)
            walk(value)


if __name__ == "__main__":
    unittest.main()

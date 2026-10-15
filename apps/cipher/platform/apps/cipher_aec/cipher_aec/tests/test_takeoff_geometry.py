"""Explicit known-geometry fixtures, never model-derived geometry."""
from copy import deepcopy
from fractions import Fraction
import unittest

from cipher_aec.api.errors import DomainError
from cipher_aec.takeoff.geometry import FORMULA, calibration, measurement, sqrt_interval
from cipher_aec.tests.test_estimating_core import identity


def fixture():
    units = [{"id": identity(key), "kind": "uom", "revision": 1,
              "fields": {"symbol": key, "dimension": dimension, "precision": 6}}
             for key, dimension in (("ft", "length"), ("in", "length"), ("sf", "area"), ("sy", "area"), ("cf", "volume"))]
    manifest = {"schema": "cipher.canonical.v1", "dataset_id": identity("takeoff-units"), "scope": {"company": "Explicit fixture", "project": "Explicit fixture"}, "records": [{"id": identity("takeoff-company"), "kind": "company", "revision": 1, "fields": {"name": "Explicit fixture", "currency": "USD", "timezone": "UTC"}}, *units],
                "unit_conversions": [{"id": identity("inch-foot"), "revision": 1, "from_unit_id": identity("in"), "to_unit_id": identity("ft"), "dimension": "length", "numerator": "1", "denominator": "12", "source": "Authored test definition"},
                                     {"id": identity("sf-sy"), "revision": 1, "from_unit_id": identity("sf"), "to_unit_id": identity("sy"), "dimension": "area", "numerator": "1", "denominator": "9", "source": "Authored test definition"}]}
    frame = {"coordinate_system": "pdf-user-space-v1", "media_box": ["0", "0", "612", "792"], "crop_box": ["0", "0", "612", "792"], "rotate": 0, "user_unit": "1", "parser": "explicit-test-page-frame"}
    definition = {"title": "Explicit 10 feet per100 PDF units", "coordinate_system": "pdf-user-space-v1", "anchors": [["0", "0"], ["100", "0"]],
                  "known_distance": {"amount": "10", "unit_id": identity("ft"), "precision": 6}, "relative_numeric_tolerance": "0.000000000001", "derived_units": [], "basis": "Explicit authored calibration fixture", "formula_version": FORMULA}
    for key, power, n, d in (("sf", 2, "1", "1"), ("sy", 2, "1", "9"), ("cf", 3, "1", "1")):
        definition["derived_units"].append({"output_unit_id": identity(key), "power": power, "numerator": n, "denominator": d, "basis": "Explicit squared/cubed foot definition", "source_citations": [{"revision_id": "Explicit fixture"}]})
    return manifest, frame, definition


def authored(kind="area", shape="rectangle", points=None):
    return {"method": "calibrated", "kind": kind, "locator": "Page1 explicit coordinate selection", "reason": "Known synthetic geometry fixture",
            "result_unit_id": identity({"area": "sf", "volume": "cf", "length": "ft"}[kind]), "result_precision": 6,
            "tolerance": "0.000001", "waste_fraction": "0", "formula_version": FORMULA, "calibration_id": identity("calibration"),
            "geometry": {"type": shape, "points": points or [["0", "0"], ["100", "200"]]}, "depth": None}


class TakeoffGeometryTests(unittest.TestCase):
    def test_known_length_area_extrusion_and_waste(self):
        manifest, frame, definition = fixture()
        area = measurement(authored(), manifest, definition, frame)
        self.assertEqual(area["quantity"]["amount"], "200.000000")
        length = measurement(authored("length", "segment", [["0", "0"], ["30", "40"]]), manifest, definition, frame)
        self.assertEqual(length["quantity"]["amount"], "5.000000")
        volume = authored("volume")
        volume["depth"] = {"amount": "24", "unit_id": identity("in"), "precision": 6}
        volume["waste_fraction"] = "0.05"
        self.assertEqual(measurement(volume, manifest, definition, frame)["quantity"]["amount"], "420.000000")

    def test_polygon_and_orientation(self):
        manifest, frame, definition = fixture()
        value = authored(points=[["0", "0"], ["100", "0"], ["100", "100"], ["0", "100"]], shape="polygon")
        self.assertEqual(measurement(value, manifest, definition, frame)["quantity"]["amount"], "100.000000")
        value["geometry"]["points"].reverse()
        self.assertEqual(measurement(value, manifest, definition, frame)["quantity"]["amount"], "100.000000")

    def test_irrational_length_has_certified_bounds(self):
        manifest, frame, definition = fixture()
        result = measurement(authored("length", "segment", [["0", "0"], ["10", "10"]]), manifest, definition, frame)
        self.assertEqual(result["quantity"]["amount"], "1.414214")
        lo, hi = (Fraction(int(result["raw_interval"][side]["numerator"]), int(result["raw_interval"][side]["denominator"])) for side in ("lower", "upper"))
        self.assertLess(lo * lo, 2)
        self.assertGreater(hi * hi, 2)
        self.assertLess(hi - lo, Fraction(1, 10**30))
        self.assertEqual(sqrt_interval(Fraction(25, 4), 36), (Fraction(5, 2), Fraction(5, 2)))

    def test_calibration_irrational_anchor_is_not_approximated_to_float(self):
        manifest, frame, definition = fixture()
        definition["anchors"] = [["0", "0"], ["100", "100"]]
        result = measurement(authored("length", "segment", [["0", "0"], ["100", "0"]]), manifest, definition, frame)
        self.assertEqual(result["quantity"]["amount"], "7.071068")
        self.assertEqual(measurement(authored(), manifest, definition, frame)["quantity"]["amount"], "100.000000")

    def test_manual_retains_no_calibration_claim(self):
        manifest, _, _ = fixture()
        value = {k: v for k, v in authored().items() if k not in {"geometry", "depth", "calibration_id"}}
        value.update(method="manual", manual_quantity={"amount": "12.345678", "unit_id": identity("sf"), "precision": 6})
        result = measurement(value, manifest)
        self.assertEqual(result["quantity"]["amount"], "12.345678")
        self.assertEqual(result["calibration_claim"], "none-manual")
        value["calibration_id"] = identity("not-allowed")
        with self.assertRaises(DomainError): measurement(value, manifest)

    def test_rejects_self_intersection_degeneracy_outside_and_unsupported(self):
        manifest, frame, definition = fixture()
        cases = [("polygon", [["0", "0"], ["100", "100"], ["100", "0"], ["0", "100"]]),
                 ("polygon", [["0", "0"], ["50", "0"], ["100", "0"]]),
                 ("rectangle", [["0", "0"], ["613", "100"]]), ("rectangle", [["0", "0"], ["0", "100"]]),
                 ("circle", [["0", "0"], ["100", "100"]])]
        for shape, points in cases:
            with self.subTest(shape=shape, points=points), self.assertRaises(DomainError):
                measurement(authored(shape=shape, points=points), manifest, definition, frame)

    def test_rejects_floats_wrong_dimensions_depth_and_bad_page_units(self):
        manifest, frame, definition = fixture()
        for changed in (authored(), authored("volume"), authored("length", "segment")):
            if changed["kind"] == "area": changed["geometry"]["points"][0][0] = 0.0
            elif changed["kind"] == "volume": changed["depth"] = {"amount": "2", "unit_id": identity("sf"), "precision": 6}
            else: changed["result_unit_id"] = identity("sf")
            with self.assertRaises(DomainError): measurement(changed, manifest, definition, frame)
        frame["user_unit"] = "2"
        with self.assertRaises(DomainError): measurement(authored(), manifest, definition, frame)

    def test_conflicting_derived_unit_relation_and_degenerate_anchor(self):
        manifest, frame, definition = fixture()
        definition["derived_units"][1]["denominator"] = "8"
        with self.assertRaises(DomainError) as error: calibration(definition, manifest, frame)
        self.assertEqual(error.exception.code, "conversion_conflict")
        _, _, definition = fixture()
        definition["anchors"][1] = ["0", "0"]
        with self.assertRaises(DomainError): calibration(definition, manifest, frame)

    def test_no_caller_total_formula_or_overbudget_geometry(self):
        manifest, frame, definition = fixture()
        for mutate in (lambda v: v.update(result="100"), lambda v: v.update(formula_version="unqualified"), lambda v: v["geometry"].update(points=[["0", "0"]] * 129)):
            value = authored()
            mutate(value)
            with self.assertRaises(DomainError): measurement(value, manifest, definition, frame)

"""Bounded rational planar geometry with certified irrational result intervals.

No binary floating point participates in quantities. A rounded quantity is emitted
only when every value in the stored arithmetic interval rounds identically.
These are arithmetic error bounds, not a field-survey accuracy certification.
"""
from decimal import Decimal, localcontext
from fractions import Fraction
from math import isqrt, gcd
import re

from cipher_aec.api.contracts import digest
from cipher_aec.api.errors import DomainError
from cipher_aec.estimating.contracts import closed, exact, identifier, quantity, visible
from cipher_aec.estimating.calculation import ratio, rounded_units
from cipher_aec.migrations.validation import ManifestError, conversion_fraction, parse_manifest

FORMULA = "cipher.takeoff.planar.v1"
COORDINATES = "pdf-user-space-v1"
MAX_POINTS = 128


def fail(message, path="takeoff", code="invalid_takeoff"):
    raise DomainError(code, message, 422, {"field": path})


def bounded(value):
    value = Fraction(value)
    if max(value.numerator.bit_length(), value.denominator.bit_length()) > 4096:
        fail("The geometric calculation exceeds the rational resource budget.", code="geometry_limit")
    return value


def coordinate(value, path="coordinate"):
    if type(value) is not str or not re.fullmatch(r"-?(0|[1-9][0-9]*)(\.[0-9]{1,6})?", value) or len(value) > 15:
        fail("Use a finite PDF coordinate string with at most six decimal places.", path)
    number = Decimal(value)
    if abs(number) > 1000000 or number.is_zero() and value.startswith("-"):
        fail("PDF coordinates must fit the declared finite coordinate range.", path)
    return Fraction(number)


def page_frame(frame):
    closed(frame, {"coordinate_system", "media_box", "crop_box", "rotate", "user_unit", "parser"}, path="page_geometry")
    if frame["coordinate_system"] != COORDINATES or frame["user_unit"] != "1" or type(frame["rotate"]) is not int or frame["rotate"] not in (0, 90, 180, 270):
        fail("Only PDF user space with UserUnit=1 and orthogonal page rotation is supported.", "page_geometry")
    boxes = []
    for key in ("media_box", "crop_box"):
        values = frame[key]
        if type(values) is not list or len(values) != 4:
            fail("A page requires a finite rectangular source boundary.", "page_geometry." + key)
        box = list(map(coordinate, values))
        if box[0] >= box[2] or box[1] >= box[3]:
            fail("The PDF page boundary must have positive width and height.", "page_geometry." + key)
        boxes.append(box)
    media, crop = boxes
    if crop[0] < media[0] or crop[1] < media[1] or crop[2] > media[2] or crop[3] > media[3]:
        fail("CropBox outside MediaBox is unsupported.", "page_geometry.crop_box")
    return crop


def point(value, frame):
    if type(value) is not list or len(value) != 2:
        fail("A geometry point has exactly two PDF coordinate strings.", "points")
    x, y = map(coordinate, value)
    x0, y0, x1, y1 = frame
    if not (x0 <= x <= x1 and y0 <= y <= y1):
        fail("A geometry point falls outside the stored PDF CropBox.", "points", "geometry_outside_page")
    return x, y


def squared(a, b):
    return bounded((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2)


def sqrt_interval(value, digits):
    value = bounded(value)
    if value < 0:
        fail("A geometric square root cannot be negative.")
    scale = 10 ** digits
    numerator = value.numerator * scale * scale
    root = isqrt(numerator // value.denominator)
    lower = Fraction(root, scale)
    upper = lower if root * root * value.denominator == numerator else Fraction(root + 1, scale)
    return bounded(lower), bounded(upper)


def _units(manifest):
    try:
        canonical = parse_manifest(manifest)
    except ManifestError as error:
        fail(error.message, error.path, "invalid_dimension")
    return canonical, {row["id"]: row for row in canonical["records"] if row["kind"] == "uom"}


def conversion(manifest, source, target):
    try:
        return bounded(conversion_fraction(manifest, source, target))
    except ManifestError as error:
        fail(error.message, error.path, "invalid_dimension")


def calibration(definition, manifest, frame):
    closed(definition, {"title", "coordinate_system", "anchors", "known_distance", "relative_numeric_tolerance", "derived_units", "basis", "formula_version"}, path="calibration")
    if definition["formula_version"] != FORMULA or definition["coordinate_system"] != COORDINATES:
        fail("Use the qualified planar formula and PDF user coordinate policy.", "calibration.formula_version")
    visible(definition["title"], "calibration.title")
    visible(definition["basis"], "calibration.basis", 2000)
    canonical, units = _units(manifest)
    bounds = page_frame(frame)
    anchors = definition["anchors"]
    if type(anchors) is not list or len(anchors) != 2:
        fail("A uniform calibration requires two distinct known-distance anchors.", "calibration.anchors")
    a, b = (point(value, bounds) for value in anchors)
    distance2 = squared(a, b)
    if not distance2:
        fail("Calibration anchors must have nonzero separation.", "calibration.anchors")
    known = quantity(definition["known_distance"], units, "calibration.known_distance", positive=True)
    length_unit = units[definition["known_distance"]["unit_id"]]
    if length_unit["fields"]["dimension"] != "length" or known > 1000000000:
        fail("A known distance requires an explicitly qualified length unit within range.", "calibration.known_distance", "invalid_dimension")
    tolerance = exact(definition["relative_numeric_tolerance"], "calibration.relative_numeric_tolerance", positive=True)
    if tolerance > Fraction(1, 100):
        fail("The declared arithmetic tolerance must not exceed 0.01.", "calibration.relative_numeric_tolerance")
    relations = definition["derived_units"]
    if type(relations) is not list or len(relations) > 16:
        fail("Use up to 16 explicit reviewed output-unit power relations.", "calibration.derived_units")
    derived = {}
    for relation in relations:
        closed(relation, {"output_unit_id", "power", "numerator", "denominator", "basis", "source_citations"}, path="calibration.derived_units[]")
        identifier(relation["output_unit_id"], "derived.output_unit_id")
        power = relation["power"]
        unit = units.get(relation["output_unit_id"])
        if type(power) is not int or power not in (2, 3) or not unit or unit["fields"]["dimension"] != {2: "area", 3: "volume"}[power]:
            fail("A derived output must explicitly match its squared/cubed unit dimension.", "derived.power", "invalid_dimension")
        numbers = [relation[key] for key in ("numerator", "denominator")]
        if any(type(n) is not str or not re.fullmatch(r"[1-9][0-9]{0,17}", n) for n in numbers) or gcd(*map(int, numbers)) != 1:
            fail("Derived unit factors require positive reduced integers of at most 18 digits.", "derived")
        if relation["output_unit_id"] in derived:
            fail("Each derived output unit occurs exactly once.", "derived.output_unit_id")
        visible(relation["basis"], "derived.basis", 2000)
        if type(relation["source_citations"]) is not list or not 1 <= len(relation["source_citations"]) <= 8:
            fail("A reviewed derived relation requires its explicit source citations.", "derived.source_citations")
        derived[relation["output_unit_id"]] = (power, Fraction(*map(int, numbers)))
    for left, (power, factor) in derived.items():
        for right, (other_power, other_factor) in derived.items():
            if left >= right or power != other_power:
                continue
            try:
                expected = conversion_fraction(canonical, left, right)
            except ManifestError as error:
                if "path" in error.message.lower() or "conversion" in error.message.lower():
                    continue
                raise
            if factor * expected != other_factor:
                fail("Reviewed derived factors conflict with canonical same-dimension conversion.", "calibration.derived_units", "conversion_conflict")
    return {"manifest": canonical, "units": units, "known": known, "anchor_squared": distance2,
            "length_unit_id": length_unit["id"], "scale_squared": bounded(known * known / distance2),
            "derived": derived, "bounds": bounds, "relative_numeric_tolerance": tolerance}


def _cross(a, b, c):
    return bounded((b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]))


def _on_segment(a, b, c):
    return _cross(a, b, c) == 0 and min(a[0], b[0]) <= c[0] <= max(a[0], b[0]) and min(a[1], b[1]) <= c[1] <= max(a[1], b[1])


def _intersects(a, b, c, d):
    x, y, u, v = _cross(a, b, c), _cross(a, b, d), _cross(c, d, a), _cross(c, d, b)
    return (x * y < 0 and u * v < 0) or any((_on_segment(a, b, c), _on_segment(a, b, d), _on_segment(c, d, a), _on_segment(c, d, b)))


def polygon_area(points):
    count = len(points)
    if count < 3 or len(set(points)) != count:
        fail("A simple polygon requires at least three distinct vertices without a repeated closing point.", "geometry.points")
    edges = [(points[i], points[(i + 1) % count]) for i in range(count)]
    for i, (a, b) in enumerate(edges):
        if _cross(points[i - 1], a, b) == 0:
            fail("Adjacent collinear polygon vertices are unsupported.", "geometry.points")
        for j, (c, d) in enumerate(edges):
            if j <= i or j == i + 1 or i == 0 and j == count - 1:
                continue
            if _intersects(a, b, c, d):
                fail("Intersecting or touching polygon edges are unsupported.", "geometry.points", "non_simple_geometry")
    area = abs(sum((a[0] * b[1] - b[0] * a[1] for a, b in edges), Fraction(0))) / 2
    if not area:
        fail("A polygon must have positive area.", "geometry.points")
    return bounded(area)


def _decimal(integer, precision):
    with localcontext() as context:
        context.prec = 80
        return format(Decimal(integer).scaleb(-precision), f".{precision}f")


def measurement(definition, manifest, calibration_definition=None, frame=None):
    common = {"method", "kind", "locator", "reason", "result_unit_id", "result_precision", "tolerance", "waste_fraction", "formula_version"}
    if type(definition) is not dict or definition.get("method") not in ("manual", "calibrated"):
        fail("Choose an explicitly manual or calibrated measurement.", "measurement.method")
    manual = definition["method"] == "manual"
    closed(definition, common | ({"manual_quantity"} if manual else {"geometry", "calibration_id", "depth"}), path="measurement")
    if definition["formula_version"] != FORMULA:
        fail("Use the qualified versioned takeoff formula.", "measurement.formula_version")
    visible(definition["locator"], "measurement.locator", 2000)
    visible(definition["reason"], "measurement.reason", 2000)
    canonical, units = _units(manifest)
    identifier(definition["result_unit_id"], "measurement.result_unit_id")
    unit = units.get(definition["result_unit_id"])
    if not unit or definition["kind"] != unit["fields"]["dimension"]:
        fail("Measurement kind must match its explicitly qualified result unit.", "measurement.kind", "invalid_dimension")
    precision = definition["result_precision"]
    if type(precision) is not int or precision != unit["fields"]["precision"]:
        fail("Result precision must match the qualified unit revision.", "measurement.result_precision")
    tolerance = exact(definition["tolerance"], "measurement.tolerance", positive=True)
    if tolerance > 1:
        fail("Arithmetic tolerance must be at most one output unit.", "measurement.tolerance")
    waste = exact(definition["waste_fraction"], "measurement.waste_fraction")
    if waste > 10:
        fail("Waste must be an explicit fraction from zero through ten.", "measurement.waste_fraction")
    interval = None
    if manual:
        raw = quantity(definition["manual_quantity"], units, "measurement.manual_quantity")
        if definition["manual_quantity"]["unit_id"] != unit["id"]:
            fail("Manual quantity uses its declared result unit; no implicit conversion.", "manual_quantity")
        interval = (raw, raw)
        geometry_kind = "manual"
    else:
        if calibration_definition is None or frame is None:
            fail("Calibrated geometry requires the exact independently verified calibration.", code="calibration_required")
        identifier(definition["calibration_id"], "measurement.calibration_id")
        calibrated = calibration(calibration_definition, canonical, frame)
        geometry = definition["geometry"]
        closed(geometry, {"type", "points"}, path="geometry")
        geometry_kind = geometry["type"]
        if type(geometry_kind) is not str or geometry_kind not in ("segment", "polyline", "rectangle", "polygon"):
            fail("Supported geometry is segment, polyline, axis-aligned rectangle or simple polygon.", "geometry.type")
        values = geometry["points"]
        if type(values) is not list or not 2 <= len(values) <= MAX_POINTS:
            fail("Use two through 128 bounded PDF points.", "geometry.points")
        points = [point(value, calibrated["bounds"]) for value in values]
        if geometry_kind in ("segment", "polyline"):
            if definition["kind"] != "length" or definition["depth"] is not None or geometry_kind == "segment" and len(points) != 2:
                fail("Length geometry requires length units, supported points and no extrusion depth.", "geometry", "invalid_dimension")
            terms = [squared(a, b) for a, b in zip(points, points[1:])]
            if not all(terms):
                fail("Adjacent length vertices must be distinct.", "geometry.points")
            multiplier = bounded(calibrated["known"] * conversion(canonical, calibrated["length_unit_id"], unit["id"]))
            for digits in (36, 54, 72):
                roots = [sqrt_interval(value / calibrated["anchor_squared"], digits) for value in terms]
                candidate = tuple(bounded(sum((root[i] for root in roots), Fraction(0)) * multiplier) for i in (0, 1))
                if candidate[1] - candidate[0] <= tolerance and candidate[1] - candidate[0] <= calibrated["relative_numeric_tolerance"] * candidate[1] and rounded_units(candidate[0] * (1 + waste), precision) == rounded_units(candidate[1] * (1 + waste), precision):
                    interval = candidate
                    break
            if interval is None:
                fail("Irrational geometry cannot meet the declared precision and arithmetic tolerance without ambiguous rounding.", code="ambiguous_geometry")
        else:
            if definition["kind"] not in ("area", "volume"):
                fail("Area/extruded geometry requires a qualified area or volume unit.", "geometry", "invalid_dimension")
            if geometry_kind == "rectangle":
                if len(points) != 2:
                    fail("An axis-aligned rectangle uses two opposite corners.", "geometry.points")
                area = abs((points[1][0] - points[0][0]) * (points[1][1] - points[0][1]))
                if not area:
                    fail("A rectangle must have positive area.", "geometry.points")
            else:
                area = polygon_area(points)
            relation = calibrated["derived"].get(unit["id"])
            power = 2 if definition["kind"] == "area" else 3
            if not relation or relation[0] != power:
                fail("This calibration lacks the reviewed squared/cubed output unit relation.", "result_unit_id", "invalid_dimension")
            raw = bounded(area * calibrated["scale_squared"])
            if power == 3:
                depth = quantity(definition["depth"], units, "measurement.depth", positive=True)
                depth_unit = units[definition["depth"]["unit_id"]]
                if depth_unit["fields"]["dimension"] != "length":
                    fail("Extrusion depth requires an explicitly qualified length unit.", "depth", "invalid_dimension")
                raw = bounded(raw * depth * conversion(canonical, depth_unit["id"], calibrated["length_unit_id"]))
            elif definition["depth"] is not None:
                fail("Area measurements have no extrusion depth.", "depth")
            raw = bounded(raw * relation[1])
            interval = raw, raw
    used = tuple(bounded(value * (1 + waste)) for value in interval)
    low, high = (rounded_units(value, precision) for value in used)
    if low != high or used[1] - used[0] > tolerance:
        fail("The result cannot resolve rounding within the declared arithmetic tolerance.", code="ambiguous_geometry")
    amount = _decimal(low, precision)
    if len(amount.replace(".", "")) > 30 or Decimal(amount) > 1000000000000:
        fail("The measured quantity exceeds the bounded quantity contract.", code="geometry_limit")
    result = {"formula_version": FORMULA, "method": definition["method"], "geometry_kind": geometry_kind,
              "quantity": {"amount": amount, "unit_id": unit["id"], "precision": precision},
              "raw_interval": {"lower": ratio(interval[0]), "upper": ratio(interval[1])},
              "result_interval": {"lower": ratio(used[0]), "upper": ratio(used[1])},
              "tolerance": definition["tolerance"], "rounding": "half_up_unique_interval", "waste_fraction": definition["waste_fraction"],
              "calibration_claim": "none-manual" if manual else "independently-verified-source-bound-planar"}
    return {**result, "result_digest": digest(result)}

"""Exact-rational build-ups with Decimal money and explicit currency rounding.

Input decimals remain exact. Rational conversions/productivity are never rounded
into display quantities. Only final priced lines and declared adjustments round;
nonnegative component allocations reconcile each rounded line exactly.
"""

from decimal import Decimal, localcontext
from fractions import Fraction

from cipher_aec.api.contracts import digest
from cipher_aec.migrations.validation import ManifestError, conversion_fraction, parse_manifest

from .contracts import (MAX_ADJUSTMENTS, MAX_LINES, MAX_MONEY, POLICY_VERSION, assembly,
                        business_date, closed, exact, fail, identifier, quantity, rate_source, visible)

SCHEMA = "cipher.estimate.inputs.v1"
COMPANY_SCHEMA = "cipher.estimate.inputs.v2"


def bounded(value):
    if value.numerator.bit_length() > 8192 or value.denominator.bit_length() > 8192:
        fail("The exact calculation exceeds its bounded rational resource limit.", "calculation", "calculation_limit")
    return value


def ratio(value):
    return {"numerator": str(value.numerator), "denominator": str(value.denominator)}


def rounded_units(value, exponent):
    scaled = bounded(value * 10**exponent)
    whole, remainder = divmod(scaled.numerator, scaled.denominator)
    return whole + int(remainder * 2 >= scaled.denominator)


def money_units(units, currency, exponent):
    with localcontext() as context:
        context.prec = 80
        amount = Decimal(units).scaleb(-exponent)
        if amount < 0 or amount >= MAX_MONEY:
            fail("The calculated amount exceeds the exact money contract.", "calculation.amount", "amount_overflow")
        return {"amount": format(amount, f".{exponent}f"), "currency": currency}


def _convert(manifest, amount, from_unit, to_unit):
    try:
        return bounded(amount * conversion_fraction(manifest, from_unit, to_unit))
    except ManifestError as error:
        fail(error.message, error.path, "invalid_dimension")


def validate_assembly(value, manifest, rates):
    units = {row["id"]: row for row in manifest["records"] if row["kind"] == "uom"}
    assembly(value, units, rates)
    for component in value["components"]:
        source = rates[component["rate_source_id"]]
        _convert(manifest, Fraction(1), component["work_quantity"]["unit_id"], value["basis_unit_id"])
        _convert(manifest, Fraction(1), component["resource_quantity"]["unit_id"], source["unit_id"])


def _priced_component(manifest, units, source, amount, unit_id, component_id, factor, waste):
    converted = _convert(manifest, amount, unit_id, source["unit_id"])
    used = bounded(converted * factor * (1 + waste))
    cost = bounded(used * exact(source["rate_amount"], "rate.rate_amount", precision=source["rate_precision"]))
    return {"component_id": component_id, "rate_source_id": source["id"], "rate_revision": source["revision"],
            "cost_type": source["cost_type"], "source_unit_id": source["unit_id"],
            "resource_quantity_exact": ratio(converted), "priced_quantity_exact": ratio(used),
            "material_factor": ratio(factor), "waste_fraction": ratio(waste), "unrounded_cost": ratio(cost)}, cost


def _allocate(components, exponent, currency):
    total = bounded(sum((cost for _, cost in components), Fraction(0)))
    target = rounded_units(total, exponent)
    floors, remainders = {}, []
    for result, cost in components:
        scaled = bounded(cost * 10**exponent)
        floor, remainder = divmod(scaled.numerator, scaled.denominator)
        floors[result["component_id"]] = floor
        remainders.append((Fraction(remainder, scaled.denominator), result["component_id"]))
    residual = target - sum(floors.values())
    if not 0 <= residual <= len(components):
        fail("Component allocation cannot reconcile the rounded line.", "calculation.allocation")
    recipients = {component_id for _, component_id in sorted(remainders, key=lambda row: (-row[0], row[1]))[:residual]}
    output = []
    for result, _ in components:
        increment = int(result["component_id"] in recipients)
        output.append({**result, "allocated_amount": money_units(floors[result["component_id"]] + increment, currency, exponent),
                       "rounding_increment": money_units(increment, currency, exponent)})
    return output, total, target


def calculate(inputs):
    closed(inputs, {"schema", "unit_manifest", "currency", "currency_exponent", "pricing_date", "policy_version", "basis_description", "basis_citations", "rates", "assemblies", "lines", "adjustments"})
    visible(inputs["basis_description"], "basis_description", 2000)
    if type(inputs["basis_citations"]) is not list or len(inputs["basis_citations"]) > 8:
        fail("Use up to eight explicit drawing/specification basis citations.", "basis_citations")
    if inputs["schema"] not in (SCHEMA, COMPANY_SCHEMA) or inputs["policy_version"] != POLICY_VERSION:
        fail("Use the supported versioned exact estimate calculation policy.", "policy_version")
    exponent, currency = inputs["currency_exponent"], inputs["currency"]
    if type(exponent) is not int or not 0 <= exponent <= 6:
        fail("Currency exponent must be an explicit integer from 0 through 6.", "currency_exponent")
    if type(currency) is not str or len(currency) != 3 or not currency.isascii() or not currency.isalpha() or currency != currency.upper():
        fail("Use an explicit uppercase currency code.", "currency")
    business_date(inputs["pricing_date"], "pricing_date")
    try:
        manifest = parse_manifest(inputs["unit_manifest"])
    except ManifestError as error:
        fail(error.message, error.path, "invalid_dimension")
    if (inputs["schema"] == COMPANY_SCHEMA) != (manifest["schema"] == "cipher.canonical.v2"):
        fail("Calculation schema and explicit canonical scope must agree.", "schema", "invalid_scope")
    units = {row["id"]: row for row in manifest["records"] if row["kind"] == "uom"}
    rates, assemblies = inputs["rates"], inputs["assemblies"]
    if type(rates) is not dict or len(rates) > 500 or type(assemblies) is not dict or len(assemblies) > 100:
        fail("Use a bounded immutable rate and assembly manifest.", "sources")
    for key, source in rates.items():
        rate_source(source, units)
        if key != source["id"] or source["currency"] != currency:
            fail("Rate identity and currency must match the estimate.", "rates")
        if inputs["pricing_date"] < source["quote_date"] or source["expiry_date"] and inputs["pricing_date"] > source["expiry_date"]:
            fail("The pricing date is outside a source quote's declared validity.", "pricing_date", "expired_rate")
    for key, value in assemblies.items():
        validate_assembly(value, manifest, rates)
        if key != value["id"]:
            fail("The assembly manifest key must match its immutable revision.", "assemblies")
    if type(inputs["lines"]) is not list or not 1 <= len(inputs["lines"]) <= MAX_LINES:
        fail("Use one through 100 authored estimate lines.", "lines")
    output, seen, direct_units = [], set(), 0
    for index, line in enumerate(inputs["lines"]):
        path = f"lines[{index}]"
        closed(line, {"line_id", "description", "quantity", "cost_code", "notes", "alternate", "included"},
               {"rate_source_id", "assembly_revision_id", "material_factor", "waste_fraction"}, path)
        identifier(line["line_id"], path + ".line_id")
        if line["line_id"] in seen:
            fail("Stable estimate line IDs must be unique within a revision.", path + ".line_id")
        seen.add(line["line_id"])
        for key in ("description", "cost_code", "notes", "alternate"):
            visible(line[key], path + "." + key, 2000 if key == "notes" else 200, empty=key != "description")
        if type(line["included"]) is not bool:
            fail("Line inclusion must be an explicit boolean.", path + ".included")
        amount = quantity(line["quantity"], units, path + ".quantity")
        if ("rate_source_id" in line) == ("assembly_revision_id" in line):
            fail("Each line binds exactly one source rate or assembly revision.", path)
        components = []
        if "rate_source_id" in line:
            identifier(line["rate_source_id"], path + ".rate_source_id")
            if not {"material_factor", "waste_fraction"}.issubset(line) or line["rate_source_id"] not in rates:
                fail("A direct line requires its immutable source and explicit factor/waste.", path)
            source = rates[line["rate_source_id"]]
            factor, waste = exact(line["material_factor"], path + ".material_factor", positive=True), exact(line["waste_fraction"], path + ".waste_fraction")
            if source["cost_type"] != "material" and (factor != 1 or waste != 0):
                fail("Material factors and waste apply only to material rates.", path)
            components.append(_priced_component(manifest, units, source, amount, line["quantity"]["unit_id"], line["line_id"], factor, waste))
        else:
            identifier(line["assembly_revision_id"], path + ".assembly_revision_id")
            if "material_factor" in line or "waste_fraction" in line or line["assembly_revision_id"] not in assemblies:
                fail("An assembly line uses its immutable component factors and waste.", path)
            value = assemblies[line["assembly_revision_id"]]
            work = _convert(manifest, amount, line["quantity"]["unit_id"], value["basis_unit_id"])
            for component in value["components"]:
                basis = _convert(manifest, quantity(component["work_quantity"], units, "component.work_quantity", positive=True),
                                 component["work_quantity"]["unit_id"], value["basis_unit_id"])
                resource = bounded(work / basis * quantity(component["resource_quantity"], units, "component.resource_quantity"))
                source = rates[component["rate_source_id"]]
                components.append(_priced_component(manifest, units, source, resource, component["resource_quantity"]["unit_id"],
                                                     component["line_id"], exact(component["material_factor"], "component.material_factor", positive=True),
                                                     exact(component["waste_fraction"], "component.waste_fraction")))
        allocated, unrounded, line_units = _allocate(components, exponent, currency)
        output.append({"line_id": line["line_id"], "description": line["description"], "quantity": line["quantity"],
                       "quantity_method": "authored",
                       "included": line["included"], "alternate": line["alternate"], "cost_code": line["cost_code"],
                       "components": allocated, "unrounded_extension": ratio(unrounded), "extension": money_units(line_units, currency, exponent)})
        if line["included"]:
            direct_units += line_units
    if type(inputs["adjustments"]) is not list or len(inputs["adjustments"]) > MAX_ADJUSTMENTS:
        fail("Use up to 30 explicit indirect/contingency adjustments.", "adjustments")
    adjustments, indirect, contingency, adjustment_ids = [], 0, 0, set()
    for index, adjustment in enumerate(inputs["adjustments"]):
        path = f"adjustments[{index}]"
        closed(adjustment, {"line_id", "kind", "label", "method", "value", "basis_description"}, path=path)
        identifier(adjustment["line_id"], path + ".line_id")
        if adjustment["line_id"] in seen or adjustment["line_id"] in adjustment_ids:
            fail("Adjustment line IDs must be unique.", path + ".line_id")
        adjustment_ids.add(adjustment["line_id"])
        visible(adjustment["label"], path + ".label")
        visible(adjustment["basis_description"], path + ".basis_description", 2000)
        if type(adjustment["kind"]) is not str or type(adjustment["method"]) is not str or adjustment["kind"] not in {"indirect", "contingency"} or adjustment["method"] not in {"fixed", "fraction_of_direct"}:
            fail("Use an explicit supported adjustment kind and basis.", path)
        value = exact(adjustment["value"], path + ".value", precision=exponent if adjustment["method"] == "fixed" else 12)
        unrounded = value if adjustment["method"] == "fixed" else bounded(Fraction(direct_units, 10**exponent) * value)
        allocated = rounded_units(unrounded, exponent)
        adjustments.append({**adjustment, "unrounded_amount": ratio(unrounded), "amount": money_units(allocated, currency, exponent)})
        if adjustment["kind"] == "indirect":
            indirect += allocated
        else:
            contingency += allocated
    result = {"schema": "cipher.estimate.result.v1", "policy": {"version": POLICY_VERSION, "rounding_mode": "ROUND_HALF_UP",
              "currency_exponent": exponent, "intermediate": "exact-rational", "line_rounding": "sum-exact-components-then-round",
              "component_allocation": "nonnegative-largest-remainder-tie-by-stable-component-id", "header_rounding": "sum-rounded-lines"},
              "lines": output, "adjustments": adjustments, "direct": money_units(direct_units, currency, exponent),
              "indirect": money_units(indirect, currency, exponent), "contingency": money_units(contingency, currency, exponent),
              "total": money_units(direct_units + indirect + contingency, currency, exponent),
              "conversion_references": [{"id": row["id"], "revision": row["revision"], "source": row["source"],
                                         "numerator": row["numerator"], "denominator": row["denominator"]} for row in manifest["unit_conversions"]]}
    return {**result, "input_digest": digest(inputs), "output_digest": digest(result)}

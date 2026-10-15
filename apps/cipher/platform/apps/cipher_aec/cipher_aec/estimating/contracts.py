"""Closed EST-01 authored-input contracts, using canonical unit primitives."""

from datetime import date
from decimal import Decimal
from fractions import Fraction

from cipher_aec.api.errors import DomainError
from cipher_aec.migrations.validation import ManifestError, decimal_quantity, text, uuid

KINDS = frozenset({"material", "labor", "equipment", "subcontract", "other"})
POLICY_VERSION = "cipher.estimate.line-half-up.v1"
MAX_LINES, MAX_COMPONENTS, MAX_ADJUSTMENTS = 100, 50, 30
MAX_MONEY = Decimal("10000000000000")


def fail(message, path="input", code="invalid_estimate"):
    raise DomainError(code, message, 422, {"field": path})


def closed(value, required, optional=(), path="input"):
    if type(value) is not dict or set(value) - set(required) - set(optional) or set(required) - set(value):
        fail("Use exactly the required and supported estimate fields.", path)
    return value


def visible(value, path, maximum=200, *, empty=False):
    if empty and value == "":
        return value
    try:
        return text(value, path, maximum)
    except ManifestError as error:
        fail(error.message, error.path)


def identifier(value, path):
    try:
        return uuid(value, path)
    except ManifestError as error:
        fail(error.message, error.path)


def exact(value, path, *, positive=False, precision=12):
    try:
        amount = decimal_quantity(value, path)
    except ManifestError as error:
        fail(error.message, error.path)
    if amount < 0 or positive and amount == 0 or max(0, -amount.as_tuple().exponent) > precision:
        fail("Use a nonnegative exact decimal within its declared precision." if not positive else "Use a positive exact decimal within its declared precision.", path)
    return Fraction(amount)


def precision(value, path):
    if type(value) is not int or not 0 <= value <= 12:
        fail("Use an integer precision from 0 through 12.", path)
    return value


def business_date(value, path):
    try:
        if type(value) is not str or date.fromisoformat(value).isoformat() != value:
            raise ValueError
    except ValueError:
        fail("Use a date in YYYY-MM-DD format.", path)
    return value


def quantity(value, units, path, *, positive=False):
    closed(value, {"amount", "unit_id", "precision"}, path=path)
    identifier(value["unit_id"], path + ".unit_id")
    unit = units.get(value["unit_id"])
    if not unit:
        fail("The quantity must reference an explicit qualified unit.", path + ".unit_id", "invalid_dimension")
    if precision(value["precision"], path + ".precision") != unit["fields"]["precision"]:
        fail("Quantity precision must match its qualified unit revision.", path + ".precision")
    return exact(value["amount"], path + ".amount", positive=positive, precision=value["precision"])


def rate_source(value, units):
    closed(value, {"id", "source_id", "revision", "predecessor", "title", "cost_type", "unit_id", "rate_amount", "rate_precision", "currency", "quote_reference", "quote_date", "expiry_date", "geography", "inclusions", "exclusions", "freight_tax_assumptions", "permission_basis", "source_citations", "item", "party_type", "party"}, path="rate")
    identifier(value["id"], "rate.id")
    identifier(value["source_id"], "rate.source_id")
    if type(value["revision"]) is not int or value["revision"] < 1:
        fail("Rate sources require a positive revision.", "rate.revision")
    if value["predecessor"] is not None:
        identifier(value["predecessor"], "rate.predecessor")
    if type(value["cost_type"]) is not str or value["cost_type"] not in KINDS:
        fail("Use an explicit supported cost type.", "rate.cost_type")
    identifier(value["unit_id"], "rate.unit_id")
    if value["unit_id"] not in units:
        fail("A rate requires a qualified unit.", "rate.unit_id", "invalid_dimension")
    dimension = units[value["unit_id"]]["fields"]["dimension"]
    expected = {"labor": "labor_time", "equipment": "equipment_time"}.get(value["cost_type"])
    if expected and dimension != expected:
        fail("Labor and equipment rates require their explicit typed time units.", "rate.unit_id", "invalid_dimension")
    exact(value["rate_amount"], "rate.rate_amount", precision=precision(value["rate_precision"], "rate.rate_precision"))
    if type(value["currency"]) is not str or len(value["currency"]) != 3 or not value["currency"].isascii() or not value["currency"].isalpha() or value["currency"] != value["currency"].upper():
        fail("Use an uppercase three-letter currency code.", "rate.currency")
    for key in ("title", "quote_reference", "geography", "inclusions", "exclusions", "freight_tax_assumptions", "permission_basis"):
        visible(value[key], "rate." + key, 2000 if key in {"inclusions", "exclusions", "freight_tax_assumptions", "permission_basis"} else 200, empty=key in {"geography", "inclusions", "exclusions"})
    business_date(value["quote_date"], "rate.quote_date")
    if value["expiry_date"] is not None:
        business_date(value["expiry_date"], "rate.expiry_date")
        if value["expiry_date"] < value["quote_date"]:
            fail("A source expiry cannot precede its quote date.", "rate.expiry_date")
    if value["party_type"] not in (None, "Supplier", "Customer") or bool(value["party_type"]) != bool(value["party"]):
        fail("Party type and native party reference must be supplied together.", "rate.party")
    for key in ("item", "party"):
        if value[key] is not None:
            visible(value[key], "rate." + key, 140)
    if type(value["source_citations"]) is not list or not 1 <= len(value["source_citations"]) <= 8:
        fail("An authored rate requires one through eight actual source citations.", "rate.source_citations")


def assembly(value, units, rates):
    closed(value, {"id", "assembly_id", "revision", "predecessor", "title", "basis_unit_id", "components", "author_basis"}, path="assembly")
    identifier(value["id"], "assembly.id")
    identifier(value["assembly_id"], "assembly.assembly_id")
    if type(value["revision"]) is not int or value["revision"] < 1:
        fail("Assembly revisions require a positive revision.", "assembly.revision")
    if value["predecessor"] is not None:
        identifier(value["predecessor"], "assembly.predecessor")
    visible(value["title"], "assembly.title")
    visible(value["author_basis"], "assembly.author_basis", 2000)
    identifier(value["basis_unit_id"], "assembly.basis_unit_id")
    if value["basis_unit_id"] not in units:
        fail("The assembly requires an explicit qualified basis unit.", "assembly.basis_unit_id", "invalid_dimension")
    if type(value["components"]) is not list or not 1 <= len(value["components"]) <= MAX_COMPONENTS:
        fail("An assembly requires one through 50 priced components.", "assembly.components")
    seen = set()
    for index, component in enumerate(value["components"]):
        path = f"assembly.components[{index}]"
        closed(component, {"line_id", "rate_source_id", "kind", "work_quantity", "resource_quantity", "material_factor", "waste_fraction"}, path=path)
        identifier(component["line_id"], path + ".line_id")
        if component["line_id"] in seen:
            fail("Assembly component line IDs must be unique.", path + ".line_id")
        seen.add(component["line_id"])
        identifier(component["rate_source_id"], path + ".rate_source_id")
        source = rates.get(component["rate_source_id"])
        if not source or component["kind"] != source["cost_type"]:
            fail("The component must bind a source of its declared cost type.", path + ".rate_source_id")
        quantity(component["work_quantity"], units, path + ".work_quantity", positive=True)
        quantity(component["resource_quantity"], units, path + ".resource_quantity")
        factor = exact(component["material_factor"], path + ".material_factor", positive=True)
        waste = exact(component["waste_fraction"], path + ".waste_fraction")
        if component["kind"] != "material" and (factor != 1 or waste != 0):
            fail("Material factors and material waste apply only to material components.", path)

"""Governed authored estimate preparation; no acceptance or financial posting."""

from copy import deepcopy
from datetime import datetime, timezone
from uuid import uuid4

import frappe

from cipher_aec.api.contracts import digest
from cipher_aec.api.errors import DomainError
from cipher_aec.governance.commands import run_command
from cipher_aec.governance.context import current_actor, require_project, trusted_write
from cipher_aec.governance.history import append_event

from . import repository, sources, units
from .calculation import SCHEMA, calculate, validate_assembly
from .contracts import POLICY_VERSION, assembly, business_date, closed, fail, identifier, precision, rate_source, visible


def _new(company, project, actor, *, status="authored", record_id=None, **values):
    return {"id": record_id or str(uuid4()), "company": company, "project": project, "author_person": actor.person_id,
            "author_user": actor.user, "created_at": datetime.now(timezone.utc).isoformat(), "status": status, **values}


def _no_floats(value):
    if isinstance(value, float):
        fail("Estimation inputs use exact decimal strings, never JSON floating-point numbers.")
    if type(value) is dict:
        for item in value.values():
            _no_floats(item)
    elif type(value) is list:
        for item in value:
            _no_floats(item)


def _event(actor, company, project, operation_id, event, kind, record):
    return append_event(actor=actor, company=company, project=project, event=event,
                        subject_type=repository.DOCTYPES[kind], subject_id=record["id"], operation_id=operation_id,
                        details={"record_digest": digest(record), "status": record["status"]})


def _scoped(kind, record_id, company, project, actor, *, lock=False, verify=True, verify_links=True):
    require_project(company, project, ability="estimate.read", actor=actor, lock=lock)
    record = repository.read(kind, record_id, lock=lock)
    if record["company"] != company or record["project"] != project:
        raise DomainError("not_found", "This estimating record is not available.", 404)
    if verify and record.get("source_citations"):
        sources.verify(company, project, record["source_citations"], actor, lock=lock)
    if verify and kind == "line":
        _scoped("revision", record["estimate_revision"], company, project, actor, lock=lock, verify_links=verify_links)
    if verify and kind == "revision" and verify_links:
        _scoped("snapshot", record["calculation_snapshot"], company, project, actor, lock=lock)
    if verify_links:
        linked_rates = [record["rate"]] if kind == "rate" else list(record["rates"].values()) if kind == "assembly" else list(record["inputs"]["rates"].values()) if kind == "snapshot" else []
        if linked_rates:
            sources.verify_native_rates(company, project, linked_rates, actor, lock=lock)
    return record


def _conversion_records(company, project, identifiers, actor, *, lock=True):
    if type(identifiers) is not list or len(identifiers) > 64:
        fail("Supply up to 64 distinct immutable conversion revision IDs.", "conversion_ids")
    for value in identifiers:
        identifier(value, "conversion_ids[]")
    if len(set(identifiers)) != len(identifiers):
        fail("Supply distinct conversion revision IDs.", "conversion_ids")
    return [_scoped("conversion", value, company, project, actor, lock=lock) for value in sorted(identifiers)]


def _unit_ids_from_assembly(value):
    result = {value["basis_unit_id"]}
    for component in value["components"]:
        result.update((component["work_quantity"]["unit_id"], component["resource_quantity"]["unit_id"]))
    return result


def register_unit(company, project, operation_id, uom, dimension, quantity_precision):
    from cipher_aec.migrations.contracts import DIMENSIONS
    visible(uom, "uom", 140)
    if type(dimension) is not str or dimension not in DIMENSIONS:
        fail("Declare an explicit supported unit dimension.", "dimension", "invalid_dimension")
    precision(quantity_precision, "quantity_precision")
    def effect(actor, project_doc):
        if actor.user != "Administrator" and "System Manager" not in frappe.get_roles(actor.user):
            raise DomainError("unit_administrator_required", "A site administrator must qualify native UOM metadata.", 403)
        doc = frappe.get_doc("UOM", uom, for_update=True)
        if doc.get("cipher_unit_id"):
            raise DomainError("immutable_unit", "This native UOM already has immutable qualified metadata.", 409)
        doc.update({"cipher_unit_id": str(uuid4()), "cipher_dimension": dimension,
                    "cipher_quantity_precision": quantity_precision, "cipher_unit_revision": 1})
        doc.save(ignore_permissions=True)
        return {"unit": units.qualified(doc.cipher_unit_id, lock=True)}
    return run_command(company=company, project=project, operation_id=operation_id, command="estimate.unit.register.v1",
                       payload={"uom": uom, "dimension": dimension, "quantity_precision": quantity_precision}, ability="estimate.write", effect=effect)


def create_conversion(company, project, operation_id, definition, source_citations, permission_basis, predecessor=None):
    closed(definition, {"from_unit_id", "to_unit_id", "dimension", "numerator", "denominator", "source"}, path="definition")
    for key in ("from_unit_id", "to_unit_id"):
        identifier(definition[key], "definition." + key)
    visible(permission_basis, "permission_basis", 2000)
    _no_floats(definition)
    def effect(actor, project_doc):
        citations = sources.resolve(company, project, source_citations, actor, lock=True)
        previous = _scoped("conversion", predecessor, company, project, actor, lock=True) if predecessor else None
        rows = frappe.db.sql("SELECT name FROM `tabCipher Unit Conversion` WHERE company=%s AND project=%s AND from_unit_id=%s AND to_unit_id=%s ORDER BY revision_number DESC LIMIT 1 FOR UPDATE",
                             (company, project, definition["from_unit_id"], definition["to_unit_id"]))
        if (rows and (not previous or rows[0][0] != previous["id"])) or previous and any(previous["definition"][key] != definition[key] for key in ("from_unit_id", "to_unit_id")):
            raise DomainError("stale_conversion", "Revise the current immutable conversion for this exact unit pair.", 412)
        record_id = str(uuid4())
        canonical = {"id": record_id, "revision": previous["definition"]["revision"] + 1 if previous else 1, **definition}
        value = _new(company, project, actor, record_id=record_id, definition=canonical, predecessor=predecessor,
                     source_citations=citations, permission_basis=permission_basis)
        value["unit_manifest"] = units.manifest(company, project, {definition["from_unit_id"], definition["to_unit_id"]}, [value], lock=True, dataset_id=record_id)
        by_id = {row["id"]: row for row in value["unit_manifest"]["records"]}
        repository.insert("conversion", value, from_unit_id=definition["from_unit_id"], to_unit_id=definition["to_unit_id"],
                          from_uom=by_id[definition["from_unit_id"]]["target"]["name"], to_uom=by_id[definition["to_unit_id"]]["target"]["name"],
                          revision_number=canonical["revision"], predecessor=predecessor)
        return {"conversion": value, "history_id": _event(actor, company, project, operation_id, "estimate.conversion.authored", "conversion", value)}
    return run_command(company=company, project=project, operation_id=operation_id, command="estimate.conversion.create.v1",
                       payload={"definition": definition, "source_citations": source_citations, "permission_basis": permission_basis, "predecessor": predecessor}, ability="estimate.write", effect=effect)


def create_rate(company, project, operation_id, rate, predecessor=None):
    required = {"title", "cost_type", "unit_id", "rate_amount", "rate_precision", "currency", "quote_reference", "quote_date", "expiry_date", "geography", "inclusions", "exclusions", "freight_tax_assumptions", "permission_basis", "source_citations"}
    closed(rate, required, {"item", "party_type", "party"}, "rate")
    _no_floats(rate)
    identifier(rate["unit_id"], "rate.unit_id")
    def effect(actor, project_doc):
        citations = sources.resolve(company, project, rate["source_citations"], actor, lock=True)
        previous = _scoped("rate", predecessor, company, project, actor, lock=True, verify_links=False) if predecessor else None
        if previous and repository.latest("rate", "source_id", previous["rate"]["source_id"])["id"] != previous["id"]:
            raise DomainError("stale_rate", "Create the successor from the current rate source revision.", 412)
        record_id = str(uuid4())
        authored = {**deepcopy(rate), "id": record_id, "source_id": previous["rate"]["source_id"] if previous else str(uuid4()),
                    "revision": previous["rate"]["revision"] + 1 if previous else 1, "predecessor": predecessor, "source_citations": citations,
                    "item": rate.get("item"), "party_type": rate.get("party_type"), "party": rate.get("party")}
        manifest = units.manifest(company, project, {authored["unit_id"]}, [], lock=True, dataset_id=record_id)
        rate_source(authored, {row["id"]: row for row in manifest["records"] if row["kind"] == "uom"})
        units.currency_policy(authored["currency"], lock=True)
        sources.verify_native_rates(company, project, [authored, *([previous["rate"]] if previous else [])], actor, lock=True)
        value = _new(company, project, actor, record_id=record_id, rate=authored, unit_manifest=manifest, source_citations=citations)
        native = next(row["target"]["name"] for row in manifest["records"] if row["id"] == authored["unit_id"])
        repository.insert("rate", value, source_id=authored["source_id"], revision_number=authored["revision"], predecessor=predecessor,
                          title=authored["title"], currency=authored["currency"], unit=native, rate_amount=authored["rate_amount"], rate_precision=authored["rate_precision"],
                          item=authored["item"], party_type=authored["party_type"], party=authored["party"], quote_date=authored["quote_date"], expiry_date=authored["expiry_date"])
        return {"rate_source": value, "history_id": _event(actor, company, project, operation_id, "estimate.rate.authored", "rate", value)}
    return run_command(company=company, project=project, operation_id=operation_id, command="estimate.rate.create.v1", payload={"rate": rate, "predecessor": predecessor}, ability="estimate.write", effect=effect)


def create_assembly(company, project, operation_id, title, basis_unit_id, components, author_basis, conversion_ids, predecessor=None):
    visible(title, "title")
    visible(author_basis, "author_basis", 2000)
    identifier(basis_unit_id, "basis_unit_id")
    if type(components) is not list or not 1 <= len(components) <= 50:
        fail("Use one through 50 authored assembly components.", "components")
    _no_floats(components)
    def effect(actor, project_doc):
        require_project(company, project, ability="document.read", actor=actor, lock=True)
        previous = _scoped("assembly", predecessor, company, project, actor, lock=True, verify_links=False) if predecessor else None
        if previous and repository.latest("assembly", "assembly_id", previous["assembly"]["assembly_id"])["id"] != previous["id"]:
            raise DomainError("stale_assembly", "Create the successor from the current assembly revision.", 412)
        rate_ids = set()
        for component in components:
            if type(component) is not dict or "rate_source_id" not in component:
                fail("Each component requires an immutable rate source.", "components")
            identifier(component["rate_source_id"], "component.rate_source_id")
            rate_ids.add(component["rate_source_id"])
        rate_records = [_scoped("rate", key, company, project, actor, lock=True, verify_links=False) for key in sorted(rate_ids)]
        rates = {row["id"]: row["rate"] for row in rate_records}
        record_id = str(uuid4())
        authored = {"id": record_id, "assembly_id": previous["assembly"]["assembly_id"] if previous else str(uuid4()),
                    "revision": previous["assembly"]["revision"] + 1 if previous else 1, "predecessor": predecessor,
                    "title": title, "basis_unit_id": basis_unit_id, "components": deepcopy(components), "author_basis": author_basis}
        conversions = _conversion_records(company, project, conversion_ids, actor)
        try:
            unit_ids = _unit_ids_from_assembly(authored) | {rate["unit_id"] for rate in rates.values()}
        except (KeyError, TypeError):
            fail("Assembly resource and work quantities require explicit qualified units.", "components")
        manifest = units.manifest(company, project, unit_ids, conversions, lock=True, dataset_id=record_id)
        validate_assembly(authored, manifest, rates)
        sources.verify_native_rates(company, project, [*rates.values(), *(previous["rates"].values() if previous else [])], actor, lock=True)
        citations = sources.merge(*(row["source_citations"] for row in [*rate_records, *conversions]))
        value = _new(company, project, actor, record_id=record_id, assembly=authored, rates=rates,
                     conversion_ids=conversion_ids, unit_manifest=manifest, source_citations=citations)
        native = next(row["target"]["name"] for row in manifest["records"] if row["id"] == basis_unit_id)
        repository.insert("assembly", value, assembly_id=authored["assembly_id"], revision_number=authored["revision"], predecessor=predecessor, title=title, basis_uom=native)
        return {"assembly_revision": value, "history_id": _event(actor, company, project, operation_id, "estimate.assembly.authored", "assembly", value)}
    return run_command(company=company, project=project, operation_id=operation_id, command="estimate.assembly.create.v1",
                       payload={"title": title, "basis_unit_id": basis_unit_id, "components": components, "author_basis": author_basis, "conversion_ids": conversion_ids, "predecessor": predecessor}, ability="estimate.write", effect=effect)


def create_estimate(company, project, operation_id, title, currency, pricing_date):
    visible(title, "title")
    business_date(pricing_date, "pricing_date")
    def effect(actor, project_doc):
        units.currency_policy(currency, lock=True)
        value = _new(company, project, actor, status="draft", title=title, currency=currency, pricing_date=pricing_date, revision_number=0, current_revision=None)
        repository.insert("estimate", value, title=title, currency=currency, pricing_date=pricing_date, revision_number=0)
        return {"estimate": value, "history_id": _event(actor, company, project, operation_id, "estimate.created", "estimate", value)}
    return run_command(company=company, project=project, operation_id=operation_id, command="estimate.create.v1", payload={"title": title, "currency": currency, "pricing_date": pricing_date}, ability="estimate.write", effect=effect)


def calculate_revision(company, project, operation_id, estimate_id, expected_revision, lines, adjustments, conversion_ids, basis_description, basis_citations):
    identifier(estimate_id, "estimate_id")
    if expected_revision is not None:
        identifier(expected_revision, "expected_revision")
    if type(lines) is not list or not 1 <= len(lines) <= 100:
        fail("Use one through 100 authored estimate lines.", "lines")
    visible(basis_description, "basis_description", 2000)
    if type(conversion_ids) is not list or len(conversion_ids) > 64:
        fail("Supply up to 64 exact conversion revision IDs.", "conversion_ids")
    for value in conversion_ids:
        identifier(value, "conversion_ids[]")
    _no_floats({"lines": lines, "adjustments": adjustments})
    def effect(actor, project_doc):
        require_project(company, project, ability="document.read", actor=actor, lock=True)
        estimate = _scoped("estimate", estimate_id, company, project, actor, lock=True)
        if estimate["current_revision"] != expected_revision:
            raise DomainError("stale_estimate", "The estimate changed. Calculate against its current revision.", 412)
        assemblies, rate_ids, unit_ids, inherited_conversions = {}, set(), set(), set(conversion_ids)
        for line in lines:
            if type(line) is not dict or type(line.get("quantity")) is not dict:
                fail("Each line requires an authored typed quantity.", "lines")
            try:
                identifier(line["quantity"]["unit_id"], "line.quantity.unit_id")
                unit_ids.add(line["quantity"]["unit_id"])
                if "assembly_revision_id" in line:
                    record = _scoped("assembly", line["assembly_revision_id"], company, project, actor, lock=True, verify_links=False)
                    assemblies[record["id"]] = record["assembly"]
                    unit_ids.update(_unit_ids_from_assembly(record["assembly"]))
                    rate_ids.update(component["rate_source_id"] for component in record["assembly"]["components"])
                    inherited_conversions.update(record["conversion_ids"])
                elif "rate_source_id" in line:
                    identifier(line["rate_source_id"], "line.rate_source_id")
                    rate_ids.add(line["rate_source_id"])
            except KeyError:
                fail("Each line requires explicit quantity and source identities.", "lines")
        rate_records = [_scoped("rate", key, company, project, actor, lock=True, verify_links=False) for key in sorted(rate_ids)]
        rates = {row["id"]: row["rate"] for row in rate_records}
        unit_ids.update(value["unit_id"] for value in rates.values())
        conversions = _conversion_records(company, project, sorted(inherited_conversions), actor)
        revision_id, snapshot_id = str(uuid4()), str(uuid4())
        manifest = units.manifest(company, project, unit_ids, conversions, lock=True, dataset_id=snapshot_id)
        currency = units.currency_policy(estimate["currency"], lock=True)
        sources.verify_native_rates(company, project, list(rates.values()), actor, lock=True)
        basis = sources.resolve(company, project, basis_citations, actor, lock=True) if basis_citations else []
        inputs = {"schema": SCHEMA, "unit_manifest": manifest, "currency": estimate["currency"], "currency_exponent": currency["currency_exponent"],
                  "pricing_date": estimate["pricing_date"], "policy_version": POLICY_VERSION, "basis_description": basis_description, "basis_citations": basis,
                  "rates": rates, "assemblies": assemblies, "lines": deepcopy(lines), "adjustments": deepcopy(adjustments)}
        result = calculate(inputs)
        citations = sources.merge(basis, *(row["source_citations"] for row in [*rate_records, *conversions]))
        snapshot = _new(company, project, actor, status="calculated", record_id=snapshot_id, subject_type="Cipher Estimate Revision", subject_id=revision_id,
                        inputs=inputs, result=result, currency_policy=currency, input_digest=result["input_digest"], output_digest=result["output_digest"], source_citations=citations)
        repository.insert("snapshot", snapshot, subject_type="Cipher Estimate Revision", subject_id=revision_id, policy_version=POLICY_VERSION, input_digest=result["input_digest"], output_digest=result["output_digest"])
        line_ids = [str(uuid4()) for _ in lines]
        revision = _new(company, project, actor, status="draft-calculated", record_id=revision_id, estimate=estimate_id,
                        revision_number=estimate["revision_number"] + 1, predecessor=expected_revision, calculation_snapshot=snapshot_id,
                        currency=estimate["currency"], pricing_date=estimate["pricing_date"], policy_version=POLICY_VERSION,
                        line_record_ids=line_ids, source_citations=citations, basis_description=basis_description,
                        direct=result["direct"], indirect=result["indirect"], contingency=result["contingency"], total=result["total"])
        repository.insert("revision", revision, estimate=estimate_id, revision_number=revision["revision_number"], predecessor=expected_revision,
                          calculation_snapshot=snapshot_id, currency=estimate["currency"], pricing_date=estimate["pricing_date"], policy_version=POLICY_VERSION,
                          direct_amount=result["direct"]["amount"], indirect_amount=result["indirect"]["amount"], contingency_amount=result["contingency"]["amount"], total_amount=result["total"]["amount"])
        native_units = {row["id"]: row["target"]["name"] for row in manifest["records"] if row["kind"] == "uom"}
        for row_id, authored, calculated in zip(line_ids, lines, result["lines"]):
            value = _new(company, project, actor, status="draft-calculated", record_id=row_id, estimate=estimate_id, estimate_revision=revision_id,
                         line_id=authored["line_id"], authored=deepcopy(authored), calculated=calculated)
            repository.insert("line", value, estimate=estimate_id, estimate_revision=revision_id, line_id=authored["line_id"],
                              quantity_amount=authored["quantity"]["amount"], unit=native_units[authored["quantity"]["unit_id"]], currency=estimate["currency"], extension_amount=calculated["extension"]["amount"],
                              cost_code=authored["cost_code"], rate_source=authored.get("rate_source_id"), assembly_revision=authored.get("assembly_revision_id"))
        estimate.update(current_revision=revision_id, revision_number=revision["revision_number"])
        repository.update_estimate(estimate)
        return {"estimate": estimate, "revision": revision, "calculation": snapshot,
                "history_id": _event(actor, company, project, operation_id, "estimate.revision.calculated", "revision", revision)}
    return run_command(company=company, project=project, operation_id=operation_id, command="estimate.calculate.v1",
                       payload={"estimate_id": estimate_id, "expected_revision": expected_revision, "lines": lines, "adjustments": adjustments,
                                "conversion_ids": conversion_ids, "basis_description": basis_description, "basis_citations": basis_citations}, ability="estimate.write", effect=effect)


def get_record(company, project, kind, record_id):
    if type(kind) is not str or kind not in repository.DOCTYPES:
        fail("This estimating record kind is not supported.", "kind")
    return _scoped(kind, record_id, company, project, current_actor())


def list_records(company, project, kind, limit=20, cursor=None, count_mode="none"):
    from cipher_aec.api.paging import page_options, decode_cursor, signing_secret, page_result
    from cipher_aec.governance.context import authority_fingerprint
    if type(kind) is not str or kind not in {"estimate", "rate", "assembly", "conversion"}:
        fail("This estimating catalog kind is not supported.", "kind")
    limit, cursor, count_mode = page_options(limit, cursor, count_mode)
    actor = current_actor()
    require_project(company, project, ability="estimate.read", actor=actor)
    if kind != "estimate":
        require_project(company, project, ability="document.read", actor=actor)
    scope = {"route": "estimate.catalog", "kind": kind, "user": actor.user, "person": actor.person_id, "company": company,
             "project": project, "authority": authority_fingerprint(actor, company, project)}
    last = decode_cursor(cursor, secret=signing_secret(), scope=scope) if cursor else None
    # Catalog visibility, count and cursor existence share one authorized set.
    # Returning only an authorized page could expose private off-page native
    # sources through total/has_more. Fail this bounded collection closed before
    # computing either rather than disclosing its hidden inventory.
    candidates = frappe.db.sql(f"SELECT name FROM `tab{repository.DOCTYPES[kind]}` WHERE company=%s AND project=%s ORDER BY name LIMIT 501", (company, project))
    if len(candidates) > 500:
        raise DomainError("catalog_scope_limit", "This catalog exceeds the bounded authorization scope.", 503)
    for candidate in candidates:
        _scoped(kind, candidate[0], company, project, actor)
    where, arguments = "company=%s AND project=%s", [company, project]
    if last:
        where += " AND (creation<%s OR (creation=%s AND name<%s))"
        arguments.extend((last[0], last[0], last[1]))
    rows = frappe.db.sql(f"SELECT name,creation FROM `tab{repository.DOCTYPES[kind]}` WHERE " + where + " ORDER BY creation DESC,name DESC LIMIT %s", (*arguments, limit + 1), as_dict=True)
    page = rows[:limit]
    items = [_scoped(kind, row.name, company, project, actor) for row in page]
    total = frappe.db.count(repository.DOCTYPES[kind], {"company": company, "project": project}) if count_mode == "exact" else None
    return page_result(items, has_more=len(rows) > limit, last=[str(page[-1].creation), page[-1].name] if page else None,
                       scope=scope, limit=limit, count_mode=count_mode, total=total)


def list_units(company, project):
    require_project(company, project, ability="estimate.read")
    rows = frappe.get_all("UOM", filters={"enabled": 1, "cipher_unit_id": ["is", "set"]}, fields=["cipher_unit_id"], order_by="name asc", limit_page_length=200)
    return {"items": [units.qualified(row.cipher_unit_id) for row in rows]}


def authorize_receipt(actor, company, project, result):
    require_project(company, project, ability="estimate.read", actor=actor, lock=True)
    for key, kind in (("conversion", "conversion"), ("rate_source", "rate"), ("assembly_revision", "assembly"), ("estimate", "estimate"), ("revision", "revision"), ("calculation", "snapshot")):
        if key in result:
            _scoped(kind, result[key]["id"], company, project, actor, lock=True)

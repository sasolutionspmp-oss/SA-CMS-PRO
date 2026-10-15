"""Explicit standard-record exports with current scope and native read permission."""
from __future__ import annotations

from .contracts import MAX_RECORDS, NATIVE_DOCTYPES, SCHEMA
from .preview import TargetSnapshot
from .validation import fail, manifest_digest, parse_manifest, strict_object, text, uuid


class FrappeTargetReader:
    def __init__(self, company, project, actor=None):
        from cipher_aec.governance.context import current_actor, require_project
        self.actor = actor or current_actor()
        self.company, self.project, self.scope_type = company, project, "Project"
        self.project_doc = require_project(company, project, ability="project.read", actor=self.actor)

    def _refresh_scope(self, lock=False):
        from cipher_aec.governance.context import require_project
        self.project_doc = require_project(self.company, self.project, ability="project.read", actor=self.actor, lock=lock)

    def fetch(self, kind, name, *, for_export=False, lock=False):
        import frappe
        # Refresh identity/duties for each explicit target; an Actor is not an entitlement cache.
        self._refresh_scope(lock)
        if kind == "project" and self.scope_type == "Company":
            return None
        doctype = NATIVE_DOCTYPES.get(kind)
        if not doctype:
            return None
        try:
            record = frappe.get_doc(doctype, name, for_update=lock)
            if not frappe.has_permission(doctype, "read", doc=record, user=self.actor.user):
                return None
            if for_export and not frappe.has_permission(doctype, "export", doc=record, user=self.actor.user):
                return None
            if kind == "company" and record.name != self.company:
                return None
            if kind == "project" and (record.name != self.project or record.company != self.company):
                return None
            if kind == "cost_center" and record.company != self.company:
                return None
            if kind == "item" and not any(row.company == self.company for row in record.get("item_defaults", [])):
                return None
            if kind in {"customer", "supplier"}:
                linked = self.scope_type == "Project" and kind == "customer" and self.project_doc.get("customer") == record.name
                scoped_account = any(row.company == self.company for row in record.get("accounts", []))
                if not linked and not scoped_account:
                    return None
            return record
        except (frappe.DoesNotExistError, frappe.PermissionError):
            frappe.clear_messages()
            return None

    def snapshot(self, row, manifest):
        record = self.fetch(row["kind"], row["target"]["name"])
        if record is None:
            return None
        from cipher_aec.api.contracts import version_of
        version = version_of(record)
        if row["kind"] == "uom" and not record.get("cipher_unit_id"):
            return TargetSnapshot({"symbol": record.get("symbol") or record.uom_name, "dimension": None,
                                   "precision": 0 if record.must_be_whole_number else None}, version,
                authority="operator_declaration_required",
                warnings=("Proposed UOM dimension/precision is an operator declaration; native UOM metadata does not verify it.",))
        identity_matches = row["kind"] != "uom" or row["id"] == record.get("cipher_unit_id")
        revision_matches = row["kind"] != "uom" or row["revision"] == record.get("cipher_unit_revision")
        if not identity_matches or not revision_matches:
            return TargetSnapshot({}, version, authority="registered_unit",
                                  identity_matches=identity_matches, revision_matches=revision_matches)
        try:
            fields, warnings = _fields(row["kind"], record, manifest["records"])
        except ValueError:
            # Missing authorized reference bindings have the same opaque unavailable result.
            return None
        return TargetSnapshot(fields, version, authority="registered_unit" if row["kind"] == "uom" else "native",
                              warnings=tuple(warnings))


class FrappeCompanyTargetReader(FrappeTargetReader):
    """Same native resolver, with exact Company authority and no Project exception.

    An effect precollects every native reference after its sorted UOM/Currency
    locks, then calls fetch(lock=True) to recheck only those held source rows.
    Native eligibility (enabled/disabled) remains the consuming domain's policy;
    this resolver establishes current read, Company association and export rights.
    """
    def __init__(self, company, actor=None, *, ability="company.read"):
        from cipher_aec.governance.context import current_actor
        self.actor = actor or current_actor()
        self.company, self.project, self.scope_type = company, None, "Company"
        self.ability = ability
        self._refresh_scope()

    def _refresh_scope(self, lock=False):
        from cipher_aec.governance.context import require_company
        self.company_doc = require_company(self.company, ability=self.ability, actor=self.actor, lock=lock)


def _fields(kind, record, records, unit_definition=None):
    warnings = []
    def reference(expected_kind, name, required=True):
        found = next((r["id"] for r in records if r["kind"] == expected_kind and r.get("target", {}).get("name") == name), None)
        if required and not found:
            fail("references", f"Include an explicit {expected_kind} identity for the selected native record's required link.")
        return found
    company_id = next(r["id"] for r in records if r["kind"] == "company")
    if kind == "company":
        import frappe
        timezone = frappe.db.get_single_value("System Settings", "time_zone") or None
        if not timezone:
            warnings.append("Company time zone is unconfigured: exported null; no operational company policy was inferred.")
        else:
            warnings.append("Company time zone is the installed site time_zone; no per-company time-zone extension is configured.")
        return {"name": record.company_name, "currency": record.default_currency, "timezone": timezone}, warnings
    if kind == "project":
        fields = {"title": record.project_name, "company_id": company_id, "status": record.status}
        if record.get("customer"):
            customer_id = reference("customer", record.customer, required=False)
            if customer_id:
                fields["customer_id"] = customer_id
            else:
                warnings.append("The Project customer link was omitted because that explicit target was not requested.")
        return fields, warnings
    if kind in {"customer", "supplier"}:
        return {"name": record.customer_name if kind == "customer" else record.supplier_name,
                "company_id": company_id, "active": not bool(record.get("disabled"))}, warnings
    if kind == "item":
        return {"code": record.item_code, "name": record.item_name, "company_id": company_id,
                "stock_uom_id": reference("uom", record.stock_uom), "is_stock_item": bool(record.is_stock_item)}, warnings
    if kind == "uom":
        if record.get("cipher_unit_id"):
            authority = {"dimension": record.get("cipher_dimension"), "precision": record.get("cipher_quantity_precision")}
            if unit_definition and any(unit_definition[k] != authority[k] for k in authority):
                fail("unit_definition", "Declared unit metadata differs from the registered native unit revision.")
            unit_definition = authority
        if not unit_definition:
            fail("unit_definition", "Native UOM names do not establish dimension or precision; supply explicit declarations.")
        if record.must_be_whole_number and unit_definition["precision"] != 0:
            fail("unit_definition.precision", "Native whole-number UOM requires precision zero.")
        if not record.get("cipher_unit_id"):
            warnings.append("UOM dimension and precision are explicit operator declarations; the native UOM name does not prove dimensional equivalence.")
        return {"symbol": record.get("symbol") or record.uom_name, "dimension": unit_definition["dimension"], "precision": unit_definition["precision"]}, warnings
    if kind == "cost_center":
        fields = {"code": record.get("cost_center_number") or record.name, "name": record.cost_center_name,
                  "company_id": company_id, "is_group": bool(record.is_group)}
        if record.get("parent_cost_center"):
            parent = reference("cost_center", record.parent_cost_center, required=False)
            if parent:
                fields["parent_id"] = parent
            else:
                warnings.append("The cost-center parent link was omitted because that explicit target was not requested.")
        return fields, warnings
    fail("kind", "This canonical kind has no native export adapter in R0.")


def export_records(*, company, project, dataset_id, references, reader, unit_conversions=None, quantities=None):
    from cipher_aec.api.errors import DomainError
    uuid(dataset_id, "dataset_id")
    if not isinstance(references, list) or not 1 <= len(references) <= MAX_RECORDS:
        fail("references", "Use 1 through 500 explicit native record references.")
    records, definitions, identity_set, target_set = [], {}, set(), set()
    for index, ref in enumerate(references):
        path = f"references[{index}]"
        strict_object(ref, {"id", "kind", "name"}, {"unit_definition"}, path)
        uuid(ref["id"], path + ".id")
        if not isinstance(ref["kind"], str) or ref["kind"] not in NATIVE_DOCTYPES:
            fail(path + ".kind", "Use a supported native export kind.")
        text(ref["name"], path + ".name", 140)
        if ref["id"] in identity_set or (ref["kind"], ref["name"]) in target_set:
            fail(path, "Export identities and target bindings must be unique.")
        identity_set.add(ref["id"]); target_set.add((ref["kind"], ref["name"]))
        if ref["kind"] == "uom" and "unit_definition" in ref:
            strict_object(ref.get("unit_definition"), {"dimension", "precision"}, set(), path + ".unit_definition")
            # Reuse the same strict unit definition rules as manifests.
            from .validation import _typed
            _typed(ref["unit_definition"]["dimension"], "dimension", path + ".unit_definition.dimension")
            _typed(ref["unit_definition"]["precision"], "precision", path + ".unit_definition.precision")
            definitions[ref["id"]] = ref["unit_definition"]
        elif ref["kind"] != "uom" and "unit_definition" in ref:
            fail(path + ".unit_definition", "Unit declarations apply only to UOM records.")
        records.append({"id": ref["id"], "kind": ref["kind"], "revision": 1,
                        "target": {"doctype": NATIVE_DOCTYPES[ref["kind"]], "name": ref["name"]}, "fields": {}})
    companies = [r for r in records if r["kind"] == "company"]
    if len(companies) != 1:
        fail("references", "Include exactly one explicit company identity.")
    # One opaque failure shape for absent, denied, and wrong-company records.
    native = []
    for row in records:
        record = reader.fetch(row["kind"], row["target"]["name"], for_export=True)
        if record is None:
            raise DomainError("target_unavailable", "One or more selected targets are not available in your current scope.", 404)
        native.append(record)
    warnings = []
    from cipher_aec.api.contracts import version_of
    for row, record in zip(records, native):
        if row["kind"] == "uom" and record.get("cipher_unit_id"):
            if row["id"] != record.cipher_unit_id:
                fail("references.id", "Qualified UOM identity must match the registered immutable unit UUID.")
            row["revision"] = record.get("cipher_unit_revision")
        fields, notices = _fields(row["kind"], record, records, definitions.get(row["id"]))
        row["fields"], row["target"]["version"] = fields, version_of(record)
        row["source"] = {"system": "frappe:" + row["target"]["doctype"], "record_id": record.name}
        warnings.extend(notices)
    manifest = parse_manifest({"schema": SCHEMA, "dataset_id": dataset_id, "scope": {"company": company, "project": project},
        "records": records, "unit_conversions": unit_conversions or [], "quantities": quantities or []})
    return {"manifest": manifest, "manifest_sha256": manifest_digest(manifest), "warnings": sorted(set(warnings)),
            "identity_policy": "Source UUIDs are explicit caller bindings; target identity remains the canonical Frappe DocType/name. No automatic name matching or persistent mapping is claimed.",
            "apply_available": False, "writes_performed": 0}

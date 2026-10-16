"""Inactive read-only canonical AEC adapters and nonpersistent draft values.

There are no commands, provider calls, persisted proposal identifiers or grants.
Concrete Frappe reads always reauthorize the actual actor and exact Company.
"""
from copy import deepcopy
from decimal import Decimal, localcontext

from cipher_aec.api.contracts import digest
from cipher_aec.api.errors import DomainError
from cipher_aec.estimating.calculation import bounded, calculate
from cipher_aec.estimating.contracts import exact, quantity
from cipher_aec.migrations.validation import ManifestError, conversion_fraction, parse_manifest

from .aec_contracts import CompanyReadContext, identifier, inputs
from .contracts import RickyError


class FrappeAECReader:
    """Only canonical reads; never routes a read through a mutation command."""
    def actor(self, context, ability):
        from cipher_aec.governance.context import current_actor, require_company
        actor = current_actor()
        if actor.user != context.user or actor.person_id != context.person:
            raise RickyError("not_found", "This Company read context is not accessible.")
        require_company(context.company, ability=ability, actor=actor)
        return actor

    def pursuit(self, context, actor):
        from cipher_aec.commercial.service import get_pursuit
        return get_pursuit(context.company, context.pursuit_id, actor=actor)

    def proposal_revision(self, context, record_id, actor):
        from cipher_aec.commercial.service import get_revision
        return get_revision(context.company, record_id, actor=actor)

    def proposal(self, context, record_id, actor):
        from cipher_aec.commercial.service import get_proposal
        return get_proposal(context.company, record_id, actor=actor)

    def raw_proposal(self, context, revision, actor):
        from cipher_aec.commercial.sources import plan
        if plan(revision["composition"], context.company, actor)["generated_sources"]:
            raise RickyError("source_dependency_unqualified", "Generated-dependent scope inputs are not enabled for these inactive tools.")

    def record(self, context, kind, record_id, actor):
        from cipher_aec.estimating import scopes, service
        with scopes.activate("Company", context.company, None):
            return service._scoped(kind, record_id, context.company, None, actor)

    def measurement(self, context, record_id, actor):
        from cipher_aec.estimating import scopes
        from cipher_aec.takeoff import service
        with scopes.activate("Company", context.company, None):
            value = service._read("measurement", record_id, context.company, None, actor)
            return value, service.current_use(value, actor)

    def measurement_sources(self, context, value, actor):
        from cipher_aec.estimating import scopes
        from cipher_aec.takeoff.service import _verify_measurement_sources
        with scopes.activate("Company", context.company, None):
            # Preserves the canonical pinned-conversion fallback for retained
            # older immutable measurements that lack a merged citation field.
            return _verify_measurement_sources(value, actor)

    def raw_sources(self, context, revision_ids, actor):
        from cipher_aec.documents.provenance import source_plan
        for record_id in sorted(set(revision_ids)):
            if source_plan(context.company, record_id, actor)["generated_sources"]:
                raise RickyError("source_dependency_unqualified", "Generated-document inputs are not enabled for these inactive assistance tools.")

    def raw_records(self, context, records, actor):
        from cipher_aec.estimating.sources import citation_groups
        references = [source["revision_id"] for kind, record in records
            for group, _ in citation_groups(kind, record) for source in group]
        if references:
            self.raw_sources(context, references, actor)

    def citation(self, context, reference, actor):
        from cipher_aec.documents.service import get_company_citation
        return get_company_citation(context.company, reference.revision_id, reference.page,
            excerpt_sha256=reference.excerpt_sha256, actor=actor)

    def current_units(self, context, records, actor):
        from cipher_aec.estimating import scopes, units
        eligible = True
        with scopes.activate("Company", context.company, None):
            for original in records:
                try:
                    actual = units.qualified(original["id"], actor=actor)
                except DomainError as error:
                    if error.code != "unit_setup_required":
                        raise
                    eligible = False
                    continue
                eligible = eligible and actual == original
        return eligible


class AECBackend:
    def __init__(self, context, *, reader=None):
        if type(context) is not CompanyReadContext:
            raise RickyError("validation_error", "Use the explicit Company read context, not Project authority.")
        self.context, self.reader = context, reader or FrappeAECReader()

    def _scope(self):
        return {"scope_type": "Company", "company": self.context.company, "pursuit_id": self.context.pursuit_id}

    def _actor(self, ability):
        actor = self.reader.actor(self.context, ability)
        pursuit = self.reader.pursuit(self.context, actor)
        if pursuit["company"] != self.context.company or pursuit["id"] != self.context.pursuit_id:
            raise RickyError("not_found", "This pursuit is outside the selected Company context.")
        return actor, pursuit

    def _company(self, value):
        if (value.get("scope_type") != "Company" or value.get("company") != self.context.company
                or value.get("project") is not None):
            raise RickyError("not_found", "This record is outside the selected Company context.")
        return value

    def _raw(self, actor, *records):
        self.reader.raw_records(self.context, records, actor)

    def _bundle(self, record_id, actor):
        identifier(record_id)
        revision = self._company(self.reader.record(self.context, "revision", record_id, actor))
        if revision["id"] != record_id:
            raise RickyError("source_integrity", "The selected revision identity changed.")
        owner = self._company(self.reader.record(self.context, "estimate", revision["estimate"], actor))
        if owner["pursuit_id"] != self.context.pursuit_id or owner["id"] != revision["estimate"]:
            raise RickyError("not_found", "This estimate is outside the selected pursuit.")
        snapshot = self._company(self.reader.record(self.context, "snapshot", revision["calculation_snapshot"], actor))
        if snapshot["subject_id"] != record_id or snapshot["id"] != revision["calculation_snapshot"]:
            raise RickyError("source_integrity", "The calculation snapshot has a different revision.")
        manifest = parse_manifest(snapshot["inputs"]["unit_manifest"])
        if manifest["scope"] != {"scope_type": "Company", "company": self.context.company, "project": None}:
            raise RickyError("source_integrity", "The original quantity scope cannot be verified.")
        self._raw(actor, ("revision", revision), ("snapshot", snapshot))
        result = calculate(deepcopy(snapshot["inputs"]))
        if (result != snapshot["result"] or result["input_digest"] != snapshot["input_digest"]
                or result["output_digest"] != snapshot["output_digest"] or result["total"] != revision["total"]):
            raise RickyError("source_integrity", "The stored exact calculation cannot be reproduced.")
        return revision, owner, snapshot, result

    def pursuit_lookup(self, arguments):
        inputs("aec.pursuit.lookup", arguments)
        _, value = self._actor("commercial.read")
        return {**self._scope(), "record_digest": digest(value), "revision_number": value["revision_number"], "title": value["title"]}

    def recompute(self, arguments):
        inputs("aec.estimate.recompute", arguments)
        actor, _ = self._actor("estimate.read")
        revision, owner, snapshot, result = self._bundle(arguments["revision_id"], actor)
        return {**self._scope(), "revision_id": revision["id"], "revision_digest": digest(revision),
            "snapshot_id": snapshot["id"], "input_digest": result["input_digest"], "output_digest": result["output_digest"],
            "policy_version": snapshot["inputs"]["policy_version"], "total": result["total"],
            "quantity_basis": "authored-original-snapshot", "current_working_revision": owner["current_revision"] == revision["id"]}

    def compare(self, arguments):
        inputs("aec.estimate.compare", arguments)
        actor, _ = self._actor("estimate.read")
        left, owner, first, a = self._bundle(arguments["left_revision_id"], actor)
        right, second_owner, second, b = self._bundle(arguments["right_revision_id"], actor)
        if owner["id"] != second_owner["id"] or left["currency"] != right["currency"]:
            raise RickyError("not_found", "Compare revisions of the same estimate and currency.")
        rows = [{line["line_id"]: line for line in value["inputs"]["lines"]} for value in (first, second)]
        changed = sorted(key for key in rows[0].keys() | rows[1].keys() if rows[0].get(key) != rows[1].get(key))
        with localcontext() as decimal:
            decimal.prec = 80
            delta = format(Decimal(b["total"]["amount"]) - Decimal(a["total"]["amount"]), "f")
        return {**self._scope(), "left_revision_id": left["id"], "right_revision_id": right["id"],
            "left_digest": digest(left), "right_digest": digest(right), "currency": left["currency"],
            "total_delta": delta, "changed_line_ids": changed}

    def _quantity(self, arguments, actor):
        for field in ("source_id", "target_unit_id"):
            identifier(arguments[field])
        record_id = arguments["source_id"]
        verified, eligible = False, True
        if arguments["source_kind"] == "estimate-line":
            value = self._company(self.reader.record(self.context, "line", record_id, actor))
            revision, owner, snapshot, _ = self._bundle(value["estimate_revision"], actor)
            authored = next((line for line in snapshot["inputs"]["lines"] if line["line_id"] == value["line_id"]), None)
            if value["id"] != record_id or record_id not in revision["line_record_ids"] or authored != value["authored"]:
                raise RickyError("source_integrity", "The original authored line quantity cannot be verified.")
            amount, manifest = authored["quantity"], snapshot["inputs"]["unit_manifest"]
            provenance = "authored-estimate-line"
            basis = "authored-line-v1"
            eligible = owner["current_revision"] == revision["id"]
        else:
            if record_id not in self.context.measurement_ids:
                raise RickyError("not_found", "This measurement was not selected for this read context.")
            value, current = self.reader.measurement(self.context, record_id, actor)
            self._company(value)
            if value["id"] != record_id:
                raise RickyError("source_integrity", "The measurement identity changed.")
            self.reader.raw_sources(self.context, [value["source"]["revision_id"],
                *(source["revision_id"] for source in self.reader.measurement_sources(self.context, value, actor))], actor)
            amount, manifest = value["result"]["quantity"], value["unit_manifest"]
            method = value["definition"]["method"]
            if method not in ("manual", "calibrated"):
                raise RickyError("source_integrity", "The measurement method is unsupported.")
            provenance = method + "-measurement"
            basis = "after-takeoff-waste-v1" if exact(value["definition"]["waste_fraction"], "measurement.waste_fraction") > 0 else "net-quantity-v1"
            verified = method == "calibrated" and current.get("verification") is not None
            eligible = current["eligible"] and (method == "manual" or verified)
        manifest = parse_manifest(manifest)
        if manifest["scope"] != {"scope_type": "Company", "company": self.context.company, "project": None}:
            raise RickyError("source_integrity", "The quantity has a different exact scope.")
        units = {row["id"]: row for row in manifest["records"] if row["kind"] == "uom"}
        target = arguments["target_unit_id"]
        if target not in units:
            raise RickyError("invalid_dimension", "The target must exist in this exact canonical unit manifest.")
        try:
            converted = bounded(quantity(amount, units, "quantity") * conversion_fraction(manifest, amount["unit_id"], target))
        except ManifestError as error:
            raise RickyError("invalid_dimension", error.message) from None
        eligible = self.reader.current_units(self.context, [units[key] for key in sorted(units)], actor) and eligible
        return {"source_kind": arguments["source_kind"], "source_id": record_id, "source_digest": digest(value),
            "source_unit_id": amount["unit_id"], "target_unit_id": target,
            "numerator": str(converted.numerator), "denominator": str(converted.denominator),
            "provenance": provenance, "independently_verified": verified, "eligible_for_new_use": eligible,
            "quantity_basis": basis, "model_supplied_quantity": False}

    def convert(self, arguments):
        inputs("aec.quantity.convert", arguments)
        actor, _ = self._actor("estimate.read")
        return self._quantity(arguments, actor)

    def _citations(self, identifiers, actor):
        identifiers = list(dict.fromkeys(identifiers))
        if not identifiers or len(identifiers) > 8:
            raise RickyError("missing_evidence", "Draft values require selected exact source citations.")
        selected = {source.citation_id: source for source in self.context.sources}
        result = []
        for citation_id in dict.fromkeys(identifiers):
            if citation_id not in selected:
                raise RickyError("invalid_citation", "The draft cites an unselected source.")
            ref = selected[citation_id]
            self.reader.raw_sources(self.context, [ref.revision_id], actor)
            value = self.reader.citation(self.context, ref, actor)
            if (value.get("scope_type") != "Company" or value.get("company") != self.context.company or value.get("project") is not None
                    or type(value.get("page")) is not int
                    or value["id"] != ref.citation_id or value["revision_id"] != ref.revision_id or value["page"] != ref.page
                    or value["excerpt_sha256"] != ref.excerpt_sha256 or value["source_sha256"] != ref.source_sha256):
                raise RickyError("source_integrity", "The selected citation no longer matches its exact source.")
            result.append({"citation_id": citation_id, "document_id": value["document_id"], "revision_id": ref.revision_id,
                "page": ref.page, "excerpt_sha256": ref.excerpt_sha256, "source_sha256": ref.source_sha256, "canonical_digest": digest(value)})
        return result

    def _draft(self, kind, fields, sources, claims, dependencies):
        result = {**self._scope(), "kind": kind, "persistent": False, "review_required": True,
            "claim_classification": "unverified-author-suggestion", "proposed_fields": deepcopy(fields),
            "verified_source_references": sources, "unverified_claims": list(claims), "record_dependencies": dependencies}
        return {**result, "draft_digest": digest(result)}

    def scope_draft(self, arguments):
        inputs("aec.scope.draft", arguments)
        identifier(arguments["proposal_revision_id"])
        actor, pursuit = self._actor("commercial.read")
        revision = self.reader.proposal_revision(self.context, arguments["proposal_revision_id"], actor)
        proposal = self.reader.proposal(self.context, revision["proposal"], actor)
        if (revision["id"] != arguments["proposal_revision_id"] or revision["proposal"] != proposal["id"]
                or revision["company"] != self.context.company or proposal["company"] != self.context.company or proposal["pursuit"] != self.context.pursuit_id):
            raise RickyError("not_found", "This proposal is outside the selected pursuit.")
        if proposal["current_revision"] != revision["id"]:
            raise RickyError("stale_source", "Review the current proposal revision before preparing a new draft.")
        self.reader.raw_proposal(self.context, revision, actor)
        if not arguments["sections"] or any(not section["citation_ids"] for section in arguments["sections"]):
            raise RickyError("missing_evidence", "Every proposed scope section requires source evidence.")
        sources = self._citations([key for section in arguments["sections"] for key in section["citation_ids"]], actor)
        return self._draft("scope-draft.v1", {"sections": arguments["sections"]}, sources, arguments["unverified_claims"],
            [{"kind": "pursuit", "id": pursuit["id"], "digest": digest(pursuit)},
             {"kind": "proposal", "id": proposal["id"], "digest": digest(proposal)},
             {"kind": "proposal-revision", "id": revision["id"], "digest": digest(revision)}])

    def estimate_draft(self, arguments):
        inputs("aec.estimate.draft", arguments)
        actor, pursuit = self._actor("estimate.read")
        revision, owner, snapshot, _ = self._bundle(arguments["base_revision_id"], actor)
        if owner["current_revision"] != revision["id"]:
            raise RickyError("stale_source", "Review the current estimate revision before preparing a new draft.")
        if not arguments["selections"] or len({row["line_record_id"] for row in arguments["selections"]}) != len(arguments["selections"]):
            raise RickyError("validation_error", "Select distinct existing lines with exact quantity references.")
        selections = []
        for row in arguments["selections"]:
            identifier(row["line_record_id"])
            if row["line_record_id"] not in revision["line_record_ids"]:
                raise RickyError("not_found", "The selected line belongs to another revision.")
            line = self._company(self.reader.record(self.context, "line", row["line_record_id"], actor))
            if line["estimate_revision"] != revision["id"] or row["target_unit_id"] != line["authored"]["quantity"]["unit_id"]:
                raise RickyError("invalid_dimension", "A proposed line quantity must use its exact authored line unit.")
            converted = self._quantity({key: row[key] for key in ("source_kind", "source_id", "target_unit_id")}, actor)
            if not converted["eligible_for_new_use"]:
                raise RickyError("stale_source", "This quantity is historical or unverified and cannot support a new draft selection.")
            if converted["quantity_basis"] == "after-takeoff-waste-v1" and any(int(component["waste_fraction"]["numerator"]) for component in line["calculated"]["components"]):
                raise RickyError("ambiguous_double_waste", "A takeoff allowance cannot be combined with this line's component waste.")
            selections.append({"line_record_id": row["line_record_id"], "quantity": converted})
        sources = self._citations(arguments["citation_ids"], actor)
        return self._draft("estimate-draft.v1", {"quantity_selections": selections, "notes": arguments["notes"]}, sources,
            arguments["unverified_claims"], [{"kind": "estimate-revision", "id": revision["id"], "digest": digest(revision)},
                {"kind": "calculation-snapshot", "id": snapshot["id"], "digest": digest(snapshot)},
                {"kind": "estimate", "id": owner["id"], "digest": digest(owner)},
                {"kind": "pursuit", "id": pursuit["id"], "digest": digest(pursuit)}])

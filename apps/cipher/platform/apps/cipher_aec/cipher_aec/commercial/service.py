"""Company-scoped reversible drafts, native master reuse and immutable revision evidence."""
import json
from contextlib import nullcontext
from uuid import uuid4
import frappe
from cipher_aec.api.contracts import canonical_json, digest, version_of, text
from cipher_aec.api.errors import DomainError
from cipher_aec.governance.context import current_actor, require_company, company_authority_fingerprint
from cipher_aec.api.paging import page_options, decode_cursor, signing_secret, page_result
from cipher_aec.governance.commands import run_company_command
from cipher_aec.governance.history import append_company_event
from . import contracts, native, sources


TYPES = {"pursuit": "Cipher Pursuit", "proposal": "Cipher Proposal", "revision": "Cipher Proposal Revision", "issue": "Cipher Proposal Issue"}


def _actor(company, actor=None, *, lock=False):
    actor = actor or current_actor()
    require_company(company, ability="commercial.read", actor=actor, lock=lock)
    return actor


def _source_plan(kind, name, company, *, lock=True):
    """Discover only internal source IDs under the already-held Company lock."""
    contracts.identifier(name)
    try:
        row = frappe.get_doc(TYPES[kind], name, for_update=lock)
    except frappe.DoesNotExistError:
        raise DomainError("not_found", "This commercial record is not available.", 404) from None
    if row.company != company:
        raise DomainError("not_found", "This commercial record is not available.", 404)
    value = json.loads(row.data_json)
    if digest(value) != row.record_digest or value.get("company") != company or value.get("id") != name:
        raise DomainError("commercial_integrity", "Commercial evidence cannot be verified.", 409)
    refs = {("Opportunity", value["opportunity"])} if kind == "pursuit" else {("Quotation", value["quotation"])}
    if kind == "proposal":
        _, pursuit_refs = _source_plan("pursuit", value["pursuit"], company, lock=lock)
        refs.update(pursuit_refs)
    return (value["party_type"], value["party_id"]), refs


def _read(kind, name, company, actor, *, lock=False):
    contracts.identifier(name)
    row = frappe.db.get_value(TYPES[kind], name, "company")
    if row != company:
        raise DomainError("not_found", "This commercial record is not available.", 404)
    doc = frappe.get_doc(TYPES[kind], name, for_update=lock)
    value = json.loads(doc.data_json)
    if value.get("company") != company or value.get("id") != name or digest(value) != doc.record_digest:
        raise DomainError("commercial_integrity", "Commercial evidence cannot be verified.", 409)
    if kind == "issue":
        from cipher_aec.documents.provenance import has_read_graph, original_read_authority
        from .outputs import read_output, _output_identity
        if not lock and has_read_graph(actor, company):
            # Current ability and fresh immutable identity/linkage always precede
            # proof lookup. No DTO, mutable head, or requested bytes are cached.
            _actor(company, actor)
            original = sources.revision_record(company, value["proposal_revision"], actor)
            prepared = _output_identity(company, original, actor)
            if digest(original) != value["proposal_revision_digest"] or prepared != value["prepared_output"]:
                raise DomainError("commercial_integrity", "Issued source snapshots cannot be verified.", 409)
            with original_read_authority("Company Proposal Issue", name, digest(value), actor, company) as reused:
                if not reused:
                    authorized = _read("revision", value["proposal_revision"], company, actor)[1]
                    actual = read_output(company, authorized["id"], actor)
                    if digest(authorized) != value["proposal_revision_digest"] or actual != value["prepared_output"]:
                        raise DomainError("commercial_integrity", "Issued source snapshots cannot be verified.", 409)
        else:
            original = _read("revision", value["proposal_revision"], company, actor, lock=lock)[1]
            prepared = read_output(company, original["id"], actor, lock=lock)
            if digest(original) != value["proposal_revision_digest"] or prepared != value["prepared_output"]:
                raise DomainError("commercial_integrity", "Issued source snapshots cannot be verified.", 409)
    elif kind == "revision":
        party_ref, refs = _source_plan("proposal", value["proposal"], company, lock=lock)
        source_plan = sources.plan(value["composition"], company, actor, lock=lock)
        _, _, complete_plan = native.sources(value["composition"], company, actor, lock=lock, for_new=False, party_ref=party_ref, native_refs=refs, extra_plan=source_plan, include_plan=True)
        proposal = _read("proposal", value["proposal"], company, actor, lock=lock)[1]
        from cipher_aec.documents.provenance import prelocked
        with (prelocked(complete_plan, actor, company) if lock else nullcontext()):
            sources.verify(value["composition"], company, proposal["pursuit"], actor, lock=lock, stored=value)
    else:
        source_type = "Opportunity" if kind == "pursuit" else "Quotation"
        source = native.require_native(source_type, value["opportunity" if kind == "pursuit" else "quotation"], actor, lock=lock)
        if source.company != company or source.get("party_name") != value["party_id"] or source.get("opportunity_from" if kind == "pursuit" else "quotation_to") != value["party_type"]:
            raise DomainError("commercial_source_conflict", "The native company or party no longer matches this commercial record.", 409)
        native.party(value["party_type"], value["party_id"], company, actor, lock=lock)
        if kind == "proposal":
            _read("pursuit", value["pursuit"], company, actor, lock=lock)
    return doc, value


def _write(kind, value, doc=None):
    fields = {key: value[key] for key in ("company", "author_person", "opportunity", "quotation", "pursuit", "revision_number", "current_revision", "party_type", "party_id", "title", "proposal", "predecessor", "native_fingerprint", "proposal_revision", "packet_id", "decision_id", "output_revision") if key in value}
    fields.update(data_json=canonical_json(value), record_digest=digest(value))
    if kind == "revision":
        fields["sections"] = [{"stable_id": row["id"], "section_kind": row["kind"], "title": row["title"], "content": row["text"]} for row in value["composition"]["sections"]]
        fields["price_lines"] = [{"stable_id": row["id"], **{key: row[key] for key in ("description", "quantity", "unit_id", "unit_revision", "rate", "amount", "alternate_group", "selected")}} for row in value["pricing"]["lines"]]
    if doc:
        doc.update(fields)
        doc.save(ignore_permissions=True)
    else:
        doc = frappe.get_doc({"doctype": TYPES[kind], "name": value["id"], **fields})
        doc.insert(ignore_permissions=True, set_name=value["id"])
    return doc


def _event(actor, company, operation_id, event, kind, value):
    append_company_event(actor=actor, company=company, event=event, subject_type=TYPES[kind], subject_id=value["id"], operation_id=operation_id, details={"revision_number": value["revision_number"]})


def get_pursuit(company, pursuit_id, actor=None):
    return _read("pursuit", pursuit_id, company, _actor(company, actor))[1]


def get_proposal(company, proposal_id, actor=None):
    actor = _actor(company, actor)
    value = _read("proposal", proposal_id, company, actor)[1]
    revision = _read("revision", value["current_revision"], company, actor)[1]
    return {**value, "revision": revision}


def get_revision(company, revision_id, actor=None):
    return _read("revision", revision_id, company, _actor(company, actor))[1]


def compare_revisions(company, proposal_id, left_revision, right_revision):
    actor = _actor(company)
    _read("proposal", proposal_id, company, actor)
    left, right = (_read("revision", name, company, actor)[1] for name in (left_revision, right_revision))
    if left["proposal"] != proposal_id or right["proposal"] != proposal_id:
        raise DomainError("not_found", "These revisions are not available for this proposal.", 404)
    return {"proposal_id": proposal_id, "left_revision": left_revision, "right_revision": right_revision, "changes": contracts.compare(left["composition"], right["composition"])}


def list_records(company, kind, limit=30, cursor=None, count_mode="none"):
    actor = _actor(company)
    limit, cursor, count_mode = page_options(limit, cursor, count_mode)
    scope = {"scope_type": "Company", "company": company, "user": actor.user, "person": actor.person_id,
        "collection": "commercial_" + kind, "authority": company_authority_fingerprint(actor, company)}
    last = decode_cursor(cursor, secret=signing_secret(), scope=scope) if cursor else None
    rows = frappe.get_all(TYPES[kind], filters={"company": company}, fields=["name", "creation"], order_by="creation desc,name desc")
    eligible = []
    for row in rows:
        # Resolve current native permissions before metadata, counts or pagination.
        try:
            value = _read(kind, row.name, company, actor)[1]
        except DomainError as error:
            if error.status not in (403, 404):
                raise
            continue
        eligible.append((row, value))
    total = len(eligible) if count_mode == "exact" else None
    eligible = [(row, value) for row, value in eligible if not last or (str(row.creation), row.name) < tuple(last)]
    page = eligible[:limit]
    return page_result([value for row, value in page], has_more=len(eligible)>limit,
        last=[str(page[-1][0].creation),page[-1][0].name] if page else None, scope=scope, limit=limit, count_mode=count_mode, total=total)


def create_pursuit(company, party_type, party_id, fields, operation_id):
    fields = contracts.pursuit_fields(fields)
    party_id = text(party_id, "Party")
    if party_type not in ("Customer", "Lead"):
        raise DomainError("invalid_commercial", "Select an existing Customer or Lead.")
    payload = {"party_type": party_type, "party_id": party_id, "fields": fields}
    def effect(actor, native_company):
        native.can_create("Opportunity", actor)
        native.party(party_type, party_id, company, actor, lock=True)
        opportunity = frappe.get_doc({"doctype": "Opportunity", "opportunity_from": party_type, "party_name": party_id, "company": company, "status": "Open", "currency": native_company.default_currency, "opportunity_type": "Sales"})
        opportunity.insert(ignore_permissions=True)
        value = {"id": str(uuid4()), "company": company, "author_person": actor.person_id, "opportunity": opportunity.name, "native_version": version_of(opportunity), "party_type": party_type, "party_id": party_id, "title": fields["title"], "fields": fields, "stage": "identified", "revision_number": 1}
        _write("pursuit", value)
        _event(actor, company, operation_id, "commercial.pursuit.created", "pursuit", value)
        return {"pursuit": value}
    return run_company_command(company=company, operation_id=operation_id, command="commercial.pursuit.create", payload=payload, ability="commercial.write", effect=effect)


def update_pursuit(company, pursuit_id, expected_revision, fields, operation_id):
    fields = contracts.pursuit_fields(fields)
    payload = {"pursuit_id": pursuit_id, "expected_revision": expected_revision, "fields": fields}
    def effect(actor, _):
        doc, value = _read("pursuit", pursuit_id, company, actor, lock=True)
        if type(expected_revision) is not int or value["revision_number"] != expected_revision:
            raise DomainError("stale_commercial", "Refresh the pursuit revision before saving.", 412)
        source = native.require_native("Opportunity", value["opportunity"], actor, lock=True)
        if version_of(source) != value["native_version"] or source.docstatus != 0:
            raise DomainError("stale_native_source", "Refresh the native opportunity before saving.", 412)
        value = {**value, "fields": fields, "title": fields["title"], "revision_number": expected_revision + 1}
        _write("pursuit", value, doc)
        _event(actor, company, operation_id, "commercial.pursuit.updated", "pursuit", value)
        return {"pursuit": value}
    return run_company_command(company=company, operation_id=operation_id, command="commercial.pursuit.update", payload=payload, ability="commercial.write", effect=effect)


def _save_revision(actor, company, proposal, quotation, authored, operation_id, native_company, *, proposal_doc=None):
    party_ref, refs = (proposal["party_type"], proposal["party_id"]), {("Opportunity", quotation.opportunity)}
    if quotation.name and not quotation.is_new():
        refs.add(("Quotation", quotation.name))
    source_plan = sources.plan(authored, company, actor, lock=True)
    units, policy, complete_plan = native.sources(authored, company, actor, lock=True, party_ref=party_ref, native_refs=refs, extra_plan=source_plan, include_plan=True)
    from cipher_aec.documents.provenance import prelocked
    with prelocked(complete_plan, actor, company):
        source_facts = sources.verify(authored, company, proposal["pursuit"], actor, lock=True)
    if authored["currency"] != native_company.default_currency:
        raise DomainError("currency_policy_unavailable", "COM-01 supports company-base-currency drafts; FX policy is not qualified.", 409)
    priced = contracts.pricing(authored, policy["currency_exponent"])
    actual, fingerprint = native.materialize(quotation, authored, priced, units)
    revision_id = str(uuid4())
    predecessor = proposal.get("current_revision")
    number = proposal["revision_number"] + 1
    revision = {"id": revision_id, "company": company, "author_person": actor.person_id, "proposal": proposal["id"], "revision_number": number, "predecessor": predecessor, "status": "draft", "composition": authored, "pricing": priced, "currency_policy": policy, "company_policy": {"base_currency": native_company.default_currency, "native_company_version": version_of(native_company)}, "units": units, "native": actual, "native_fingerprint": fingerprint}
    if source_facts["source_citations"] or source_facts["accepted_estimate"] is not None:
        revision.update(source_facts)
    # Parent exists before its first child; circular head is populated afterwards.
    if proposal_doc is None:
        proposal["quotation"] = quotation.name
        proposal["native_fingerprint"] = fingerprint
        proposal["native_version"] = actual["version"]
        proposal["revision_number"] = 1
        proposal["current_revision"] = None
        proposal_doc = _write("proposal", proposal)
    _write("revision", revision)
    proposal.update(revision_number=number, current_revision=revision_id, native_fingerprint=fingerprint, native_version=actual["version"])
    if number == 1:
        # First head completes one creation, not a second business revision.
        proposal_doc.db_set({"current_revision": revision_id, "data_json": canonical_json(proposal), "record_digest": digest(proposal)}, update_modified=False)
    else:
        _write("proposal", proposal, proposal_doc)
    _event(actor, company, operation_id, "commercial.proposal.revision.created", "revision", revision)
    return {"proposal": proposal, "revision": revision}


def create_proposal(company, pursuit_id, composition, operation_id):
    authored = contracts.composition(composition)
    payload = {"pursuit_id": pursuit_id, "composition": authored}
    def effect(actor, native_company):
        native.can_create("Quotation", actor)
        party_ref, refs = _source_plan("pursuit", pursuit_id, company)
        source_plan = sources.plan(authored, company, actor, lock=True)
        native.sources(authored, company, actor, lock=True, party_ref=party_ref, native_refs=refs, extra_plan=source_plan)
        pursuit = _read("pursuit", pursuit_id, company, actor, lock=True)[1]
        quotation = frappe.get_doc({"doctype": "Quotation", "quotation_to": pursuit["party_type"], "party_name": pursuit["party_id"], "company": company, "opportunity": pursuit["opportunity"], "order_type": "Sales"})
        proposal = {"id": str(uuid4()), "company": company, "author_person": actor.person_id, "pursuit": pursuit_id, "party_type": pursuit["party_type"], "party_id": pursuit["party_id"], "title": pursuit["title"], "revision_number": 0, "current_revision": None, "quotation": None}
        return _save_revision(actor, company, proposal, quotation, authored, operation_id, native_company)
    return run_company_command(company=company, operation_id=operation_id, command="commercial.proposal.create", payload=payload, ability="commercial.write", effect=effect)


def save_proposal_revision(company, proposal_id, expected_revision, expected_native_fingerprint, composition, operation_id):
    authored = contracts.composition(composition)
    payload = {"proposal_id": proposal_id, "expected_revision": expected_revision, "expected_native_fingerprint": expected_native_fingerprint, "composition": authored}
    def effect(actor, native_company):
        party_ref, refs = _source_plan("proposal", proposal_id, company)
        source_plan = sources.plan(authored, company, actor, lock=True)
        native.sources(authored, company, actor, lock=True, party_ref=party_ref, native_refs=refs, extra_plan=source_plan)
        doc, proposal = _read("proposal", proposal_id, company, actor, lock=True)
        if type(expected_revision) is not int or proposal["revision_number"] != expected_revision:
            raise DomainError("stale_commercial", "Refresh the proposal head before saving.", 412)
        quotation = native.require_native("Quotation", proposal["quotation"], actor, lock=True)
        if not frappe.has_permission("Quotation", ptype="write", doc=quotation, user=actor.user):
            raise DomainError("native_permission_denied", "Native write permission is required for this draft.", 403)
        actual = native.persisted(quotation.name)
        if quotation.docstatus != 0 or digest(actual) != expected_native_fingerprint or expected_native_fingerprint != proposal["native_fingerprint"]:
            raise DomainError("stale_native_source", "Refresh the native quotation before saving.", 412)
        return _save_revision(actor, company, proposal, quotation, authored, operation_id, native_company, proposal_doc=doc)
    return run_company_command(company=company, operation_id=operation_id, command="commercial.proposal.revise", payload=payload, ability="commercial.write", effect=effect)


def authorize_receipt(actor, company, result, *, lock=False):
    _actor(company, actor, lock=lock)
    if type(result.get("prepared_output")) is dict:
        from .outputs import read_output
        value = result["prepared_output"]
        actual = read_output(company, value["proposal_revision_id"], actor, lock=lock)
        if actual != value:
            raise DomainError("receipt_integrity", "Prepared output receipt cannot be verified.", 409)
    for key, kind in (("issue", "issue"), ("revision", "revision"), ("proposal", "proposal"), ("pursuit", "pursuit")):
        value = result.get(key)
        if type(value) is dict and value.get("id"):
            _read(kind, value["id"], company, actor, lock=lock)


def pursuit_source_plan(company, pursuit_id, actor=None, *, lock=False):
    """Internal lock discovery only; callers must recheck before exposing content."""
    actor = _actor(company, actor, lock=lock)
    party_ref, refs = _source_plan("pursuit", pursuit_id, company, lock=lock)
    doc = frappe.get_doc("Cipher Pursuit", pursuit_id, for_update=lock)
    return {"company":company,"pursuit_id":pursuit_id,"record_digest":doc.record_digest,
            "revision_number":doc.revision_number,"party_type":party_ref[0],"party_id":party_ref[1],
            "native_refs":[{"doctype":doctype,"name":name} for doctype,name in sorted(refs | {party_ref})]}


def recheck_pursuit_source(company, pursuit_id, actor=None, *, lock=False):
    actor = _actor(company, actor, lock=lock)
    return _read("pursuit", pursuit_id, company, actor, lock=lock)[1]


def list_issues(company, proposal_id, limit=30, cursor=None, count_mode="none"):
    actor = _actor(company)
    _read("proposal", proposal_id, company, actor)
    limit, cursor, count_mode = page_options(limit, cursor, count_mode)
    scope = {"scope_type":"Company", "company":company, "user":actor.user, "person":actor.person_id,
        "collection":"commercial_issues", "proposal":proposal_id, "authority":company_authority_fingerprint(actor,company)}
    last = decode_cursor(cursor,secret=signing_secret(),scope=scope) if cursor else None
    rows = frappe.get_all("Cipher Proposal Issue",filters={"company":company,"proposal":proposal_id},fields=["name","creation"],order_by="creation desc,name desc",limit_page_length=501)
    if len(rows)>500:
        raise DomainError("commercial_limit","This proposal exceeds the bounded issue inventory.",409)
    allowed=[]
    for row in rows:
        try:
            value = _read("issue",row.name,company,actor)[1]
        except DomainError as error:
            if error.status in (403,404):continue
            raise
        allowed.append((row,value))
    total=len(allowed) if count_mode=="exact" else None
    allowed=[(row,value) for row,value in allowed if not last or (str(row.creation),row.name)<tuple(last)]
    page=allowed[:limit]
    return page_result([value for row,value in page],has_more=len(allowed)>limit,last=[str(page[-1][0].creation),page[-1][0].name] if page else None,scope=scope,limit=limit,count_mode=count_mode,total=total)

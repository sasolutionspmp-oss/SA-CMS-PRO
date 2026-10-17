"""Prepare actual canonical PDF bytes before review; no issue or distribution."""
import json
from contextlib import nullcontext
import frappe
from cipher_aec.api.contracts import digest, text
from cipher_aec.api.errors import DomainError
from cipher_aec.governance.commands import run_company_command
from cipher_aec.governance.context import require_company
from cipher_aec.governance.history import append_company_event
from cipher_aec.documents import provenance
from . import sources, output_sources, rendering, contracts, native


def _parent(company, revision_id, *, lock=False):
    if not frappe.db.has_column("Cipher Document Revision", "generation_json"):
        raise DomainError("output_unavailable", "Prepared proposal output metadata is not installed.", 503)
    rows = frappe.db.sql("""SELECT name FROM `tabCipher Document` WHERE company=%s AND scope_type='Company'
        AND project IS NULL AND producer_kind=%s AND producer_reference=%s ORDER BY name LIMIT 2""" + (" FOR UPDATE" if lock else ""),
        (company,provenance.PRODUCER,revision_id),as_dict=True)
    if len(rows)>1:
        raise DomainError("source_integrity","Prepared output identity is ambiguous.",409)
    if not rows:
        return None
    return frappe.get_doc("Cipher Document", rows[0].name, for_update=lock)


def read_output(company, proposal_revision_id, actor=None, *, lock=False):
    from .service import _actor, _read
    from cipher_aec.documents.service import _service, _company_call
    actor = _actor(company, actor, lock=lock)
    require_company(company, ability="document.read", actor=actor, lock=lock)
    plan = sources.revision_plan(company, proposal_revision_id, actor, lock=True) if lock else None
    # Revision reader acquires the complete source union before nested readers.
    revision = _read("revision", proposal_revision_id, company, actor, lock=lock)[1]
    parent = _parent(company, proposal_revision_id, lock=lock)
    if parent is None:
        raise DomainError("not_found", "This prepared proposal output is not available.", 404)
    binding = provenance.binding(parent.as_dict())
    # This exact verified output adds an admission node, not new native source
    # dependencies: revision_plan already acquired its full immutable input union.
    if lock:
        plan = sources.merge(plan, {"generated_sources":[{"document_id":parent.name,"input_digest":parent.producer_input_digest}]})
    with (provenance.prelocked(plan, actor, company) if lock else nullcontext()):
        bound = _service(actor, scope_type="Company")
        source = _company_call(lambda: bound.source_reference(company, None, parent.current_revision, 1, lock=lock))
    stored = bound.repo.revision(parent.current_revision, lock=lock)
    return _output_snapshot(company, proposal_revision_id, revision, parent, binding, stored, source)


def _output_snapshot(company, proposal_revision_id, revision, parent, binding, stored, source):
    """One exact comparison for full byte reads and internal metadata identity."""
    try:
        generated = json.loads(stored["generation_json"])
        if (generated["input_digest"] != parent.producer_input_digest
                or generated["output_sha256"] != source["source_sha256"]
                or generated["output_byte_length"] != source["byte_length"]
                or generated["proposal_revision_digest"] != digest(revision)
                or generated["fingerprint"] != binding["renderer"]["fingerprint"]
                or generated["cover_digest"] != digest(binding["cover"])
                or generated["recipients_digest"] != digest(binding["recipients"])):
            raise ValueError
    except (KeyError,ValueError,TypeError):
        raise DomainError("source_integrity","Prepared output provenance cannot be verified.",409) from None
    result = {"company":company,"proposal_id":revision["proposal"],"proposal_revision_id":proposal_revision_id,
        "proposal_revision_digest":digest(revision),"document_id":parent.name,"revision_id":source["revision_id"],
        "source_sha256":source["source_sha256"],"byte_length":source["byte_length"],"page_count":source["page_count"],
        "input_digest":parent.producer_input_digest,"binding":binding,"rendering":generated}
    result["review_version"] = digest({key:result[key] for key in ("proposal_revision_digest","revision_id","source_sha256","input_digest")})
    return result


def _output_identity(company, revision, actor):
    """Internal fresh linkage for an existing original-authority read proof.

    This reader authorizes no recursive source or bytes and is never a public
    entrypoint. Callers must complete original authorization on a proof miss.
    Actual output requests still use the mandatory canonical byte reader.
    """
    from cipher_aec.documents.service import _service, _company_call
    require_company(company, ability="document.read", actor=actor)
    parent = _parent(company, revision["id"])
    if parent is None:
        raise DomainError("not_found", "This prepared proposal output is not available.", 404)
    binding = provenance.binding(parent.as_dict())
    bound = _service(actor, scope_type="Company")
    stored = bound.repo.revision(parent.current_revision)
    fields = ("producer_kind", "producer_reference", "producer_input_digest", "producer_binding_json")
    if (parent.company != company or parent.scope_type != "Company" or parent.project is not None
            or stored.get("company") != company or stored.get("scope_type") != "Company" or stored.get("project") is not None
            or stored.get("document") != parent.name or stored.get("name") != parent.current_revision
            or parent.revision_number != 1 or stored.get("revision_number") != 1
            or stored.get("mime_type") != "application/pdf"
            or any((stored.get(field) or None) != (parent.get(field) or None) for field in fields)):
        raise DomainError("source_integrity", "Prepared output identity cannot be verified.", 409)
    _company_call(lambda: bound._available(stored))
    source = {"revision_id":stored["name"], "source_sha256":stored["sha256"],
              "byte_length":stored["byte_length"], "page_count":stored["page_count"]}
    return _output_snapshot(company, revision["id"], revision, parent, binding, stored, source)


def prepare_output(company, proposal_id, revision_id, expected_revision_digest, recipients, cover, operation_id):
    from .service import _actor, _read
    from cipher_aec.documents.service import _service, _company_call
    to = output_sources.recipients(recipients)
    cover = text(cover,"Cover text",12000,required=False)
    expected_revision_digest = contracts.checksum(expected_revision_digest)
    payload = {"proposal_id":proposal_id,"revision_id":revision_id,"expected_revision_digest":expected_revision_digest,"recipients":to,"cover":cover}
    def effect(actor, company_doc):
        require_company(company,ability="document.write",actor=actor,lock=True)
        require_company(company,ability="document.read",actor=actor,lock=True)
        revision = _read("revision",revision_id,company,actor,lock=True)[1]
        proposal = _read("proposal",proposal_id,company,actor,lock=True)[1]
        if revision["proposal"] != proposal_id:
            raise DomainError("not_found","This proposal revision is not available.",404)
        if digest(revision) != expected_revision_digest or proposal["current_revision"] != revision_id:
            raise DomainError("stale_commercial","Prepare the exact current proposal revision.",412)
        actual = native.persisted(proposal["quotation"],lock=True)
        if digest(actual) != revision["native_fingerprint"] or actual["docstatus"] != 0:
            raise DomainError("stale_native_source","Refresh the native quotation before preparing output.",412)
        binding = output_sources.build_binding(revision,revision.get("accepted_estimate"),to,cover,rendering.policy())
        old = _parent(company,revision_id,lock=True)
        if old:
            if old.producer_input_digest != digest(binding):
                raise DomainError("output_already_prepared","Create a successor proposal revision to change prepared recipients, cover or rendering inputs.",409)
        else:
            content,generated = rendering.render(revision,revision["accepted_estimate"],cover,to)
            generated["input_digest"] = digest(binding)
            plan = sources.revision_plan(company,revision_id,actor,lock=True)
            from cipher_aec.documents.preparation import _writing_output
            with provenance.prelocked(plan,actor,company), _writing_output(company=company,proposal_revision=revision_id,
                    input_digest=digest(binding),renderer_fingerprint=generated["fingerprint"],source_sha256=generated["output_sha256"],
                    byte_length=generated["output_byte_length"],generation_digest=digest(generated)):
                _company_call(lambda: _service(actor,scope_type="Company").upload(company=company,project=None,
                    title="Prepared proposal " + revision_id,filename="proposal-" + revision_id + ".pdf",content=content,
                    byte_length=len(content),sha256=generated["output_sha256"],producer=binding,generation=generated))
        prepared = read_output(company,revision_id,actor,lock=True)
        append_company_event(actor=actor,company=company,event="commercial.proposal.output.prepared",subject_type="Cipher Document Revision",
            subject_id=prepared["revision_id"],operation_id=operation_id,details={"proposal_id":proposal_id,"proposal_revision_id":revision_id})
        return {"prepared_output":prepared}
    return run_company_command(company=company,operation_id=operation_id,command="commercial.proposal.prepare_output",payload=payload,ability="commercial.write",effect=effect)


def output_subject(company, proposal_id, actor=None):
    """Server-authored version for preparation; browsers never hash canonical JSON."""
    from .service import _actor, _read
    actor=_actor(company,actor)
    proposal=_read('proposal',proposal_id,company,actor)[1]
    revision=_read('revision',proposal['current_revision'],company,actor)[1]
    prepared=read_output(company,revision['id'],actor) if _parent(company,revision['id']) else None
    return {'company':company,'proposal_id':proposal_id,'revision_id':revision['id'],'revision_digest':digest(revision),
        'native_fingerprint':revision['native_fingerprint'],'is_current':True,'prepared_output':prepared}


def issue_source_reference(company, issue_id, actor=None, *, lock=False):
    """Exact issued original bytes/current rights for governed distribution.

    No rendering, latest draft substitution, or external transmission occurs.
    Locking calls acquire the entire Issue source union; callers with additional
    source masters must merge their discovery plan before entering this reader.
    Ordinary reads retain canonical authorization without unused lock discovery.
    """
    from .service import _actor, _read
    from cipher_aec.documents.service import company_source_reference
    actor=_actor(company,actor,lock=lock)
    issue=_read('issue',issue_id,company,actor,lock=lock)[1]
    prepared=issue['prepared_output']
    plan=provenance.source_plan(company,prepared['revision_id'],actor,lock=True) if lock else None
    with (provenance.prelocked(plan,actor,company) if lock else nullcontext()):
        source=company_source_reference(company,prepared['revision_id'],1,actor,lock=lock)
    if source['source_sha256']!=prepared['source_sha256'] or source['byte_length']!=prepared['byte_length']:
        raise DomainError('source_integrity','The exact issued PDF cannot be verified.',409)
    return {'issue':issue,'source':source}

"""Company proposal dispatch over immutable Issue sources and exact recipients."""
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import timedelta
import json
from pathlib import Path
from uuid import uuid4

import frappe

from cipher_aec.api.contracts import canonical_json, digest, text, utc_timestamp
from cipher_aec.api.errors import DomainError
from cipher_aec.governance.commands import run_company_command
from cipher_aec.governance.context import current_actor, require_company, assert_synthetic_site, session_authority_reference, require_effects_enabled
from cipher_aec.governance.history import append_company_event
from . import distribution_contracts as rules

TYPES = {"instruction": "Cipher Distribution Instruction", "dispatch": "Cipher Distribution Dispatch", "cancellation": "Cipher Distribution Cancellation"}
_writing = ContextVar("cipher_exact_distribution_write", default=None)


@contextmanager
def _write(kind, identifier, value):
    token = _writing.set((kind, identifier, digest(value)))
    try:
        yield
    finally:
        _writing.reset(token)


def profile(*, require_enabled=True):
    assert_synthetic_site()
    from frappe.config import get_site_config
    enabled = rules.fixture_enabled(get_site_config(cached=False).get("cipher_distribution_fixture_enabled", False))
    if require_enabled and not enabled:
        raise DomainError("distribution_unavailable", "The synthetic delivery profile is not enabled.", 503)
    value = {"id": rules.PROFILE, "version": 1, "mode": "fixture", "enabled": enabled,
        "max_recipients": rules.MAX_RECIPIENTS, "mandate_seconds": rules.MANDATE_SECONDS,
        "attempt_seconds": rules.ATTEMPT_SECONDS}
    return value


def require_current_effects_enabled():
    """Read operator flags afresh after a potentially blocked sink readback."""
    from frappe.config import get_site_config
    require_effects_enabled()
    config = get_site_config(cached=False)
    if config.get("cipher_site_mode") != "synthetic" or config.get("cipher_execution_quarantined", False) not in (False, None, 0, "0", "false"):
        raise DomainError("execution_quarantined", "This workspace is read only for distribution.", 503)


def sink_path():
    # Profile revocation must not prevent observational recovery. This literal
    # path cannot be redirected by a caller or a changed profile configuration.
    assert_synthetic_site()
    return str(Path(frappe.get_site_path("private", "distribution-fixture", "receipts.sqlite3")).resolve())


def raw(kind, identifier, company, *, lock=False):
    identifier = text(identifier, "Distribution record", 140)
    rows = frappe.db.sql("SELECT data_json,record_digest FROM `tab" + TYPES[kind] + "` WHERE name=%s AND company=%s AND scope_type='Company' AND (project IS NULL OR project='')" + (" FOR UPDATE" if lock else ""), (identifier, company))
    if not rows:
        raise DomainError("not_found", "This distribution record is not available.", 404)
    value = json.loads(rows[0][0])
    if digest(value) != rows[0][1] or value.get("id") != identifier or value.get("company") != company or value.get("scope_type") != "Company" or value.get("project") is not None:
        raise DomainError("distribution_integrity", "The immutable distribution source cannot be verified.", 409)
    return value


def issue_source(company, issue_id, actor, *, lock=False):
    from cipher_aec.commercial.outputs import issue_source_reference
    require_company(company, ability="commercial.read", actor=actor, lock=lock)
    require_company(company, ability="document.read", actor=actor, lock=lock)
    return issue_source_reference(company, issue_id, actor, lock=lock)["issue"]


def authorize_instruction(value, actor, *, lock=False):
    issue = issue_source(value["company"], value["issue_id"], actor, lock=lock)
    prepared = issue["prepared_output"]
    attachment = {"revision_id": prepared["revision_id"], "document_id": prepared["document_id"],
        "sha256": prepared["source_sha256"], "byte_length": prepared["byte_length"], "media_type": "application/pdf"}
    expected_recipients = rules.chosen_recipients(prepared["binding"]["recipients"], [r["id"] for r in value["recipients"]])
    if (value["issue_digest"] != digest(issue) or value["attachment"] != attachment or
            value["recipients"] != expected_recipients or value["cover_digest"] != digest(prepared["binding"]["cover"]) or
            value["message_digest"] != digest(value["message"])):
        raise DomainError("distribution_integrity", "The exact issued recipients, message or PDF differ from the instruction.", 409)
    return issue


def read(kind, identifier, company, actor=None, *, lock=False):
    actor = actor or current_actor()
    require_company(company, ability="commercial.read", actor=actor, lock=lock)
    value = raw(kind, identifier, company, lock=lock)
    instruction = value if kind == "instruction" else raw("instruction", value["instruction_id"], company, lock=lock)
    authorize_instruction(instruction, actor, lock=lock)
    return value


def insert(kind, value):
    from cipher_aec.governance.context import trusted_write
    with _write(kind, value["id"], value), trusted_write():
        fields = {"doctype": TYPES[kind], "scope_type": "Company", "company": value["company"], "project": None,
            "data_json": canonical_json(value), "record_digest": digest(value)}
        if kind == "instruction":
            fields["issue_id"] = value["issue_id"]
        else:
            fields["instruction_id"] = value["instruction_id"]
            if kind == "dispatch":
                fields["issue_id"] = value["issue_id"]
            if kind == "cancellation":
                fields["dispatch_id"] = value["dispatch_id"]
        return frappe.get_doc(fields).insert(ignore_permissions=True, set_name=value["id"])


def event(actor, value, operation_id, event_name, kind):
    append_company_event(actor=actor, company=value["company"], operation_id=operation_id, event=event_name,
        subject_type=TYPES[kind], subject_id=value["id"], details={"record_digest": digest(value)})


def create_instruction(company, issue_id, recipient_ids, subject, body, profile_id, operation_id):
    issue_id = text(issue_id, "Issue", 140)
    if profile_id != rules.PROFILE:
        raise DomainError("distribution_unavailable", "Choose the configured synthetic delivery profile.", 503)
    message = rules.message(subject, body)
    payload = {"issue_id": issue_id, "recipient_ids": recipient_ids, "message": message, "profile_id": profile_id}
    def effect(actor, company_doc):
        require_company(company, ability="document.read", actor=actor, lock=True)
        selected_profile = profile()
        issue = issue_source(company, issue_id, actor, lock=True)
        prepared = issue["prepared_output"]
        recipients = rules.chosen_recipients(prepared["binding"]["recipients"], recipient_ids)
        now = rules.utc_now()
        value = {"id": str(uuid4()), "scope_type": "Company", "company": company, "project": None,
            "author_person": actor.person_id, "author_user": actor.user, "session_reference": session_authority_reference(actor),
            "created_at": utc_timestamp(now), "valid_until": utc_timestamp(now + timedelta(seconds=rules.MANDATE_SECONDS)),
            "issue_id": issue_id, "issue_digest": digest(issue), "recipients": recipients,
            "attachment": {"revision_id": prepared["revision_id"], "document_id": prepared["document_id"],
                "sha256": prepared["source_sha256"], "byte_length": prepared["byte_length"], "media_type": "application/pdf"},
            "cover_digest": digest(prepared["binding"]["cover"]), "message": message, "message_digest": digest(message),
            "profile": selected_profile, "mode": "fixture"}
        insert("instruction", value)
        event(actor, value, operation_id, "distribution.instruction.created", "instruction")
        return {"instruction": value, "version": digest(value)}
    return run_company_command(company=company, operation_id=operation_id, command="distribution.instruction.create.v1",
        payload=payload, ability="commercial.write", effect=effect)


def cancellation(dispatch_id, company, *, lock=False):
    rows = frappe.db.sql("SELECT name FROM `tabCipher Distribution Cancellation` WHERE dispatch_id=%s AND company=%s" + (" FOR UPDATE" if lock else ""), (dispatch_id, company))
    return raw("cancellation", rows[0][0], company, lock=lock) if rows else None


def cancel_dispatch(company, dispatch_id, reason, operation_id):
    reason = text(reason, "Cancellation reason", 2000)
    def effect(actor, company_doc):
        dispatch = read("dispatch", dispatch_id, company, actor, lock=True)
        if dispatch["requester_person"] != actor.person_id:
            raise DomainError("distribution_cancel_denied", "Only the original requester can stop the remaining dispatch.", 403)
        existing = cancellation(dispatch_id, company, lock=True)
        if existing:
            return {"cancellation": existing, "dispatch": get_dispatch(company, dispatch_id, actor)}
        value = {"id": str(uuid4()), "scope_type": "Company", "company": company, "project": None,
            "dispatch_id": dispatch_id, "instruction_id": dispatch["instruction_id"], "actor_person": actor.person_id,
            "reason": reason, "cancelled_at": utc_timestamp(rules.utc_now()), "in_flight_may_complete": True}
        insert("cancellation", value)
        event(actor, value, operation_id, "distribution.dispatch.cancelled", "cancellation")
        return {"cancellation": value, "dispatch": get_dispatch(company, dispatch_id, actor)}
    return run_company_command(company=company, operation_id=operation_id, command="distribution.dispatch.cancel.v1",
        payload={"dispatch_id": dispatch_id, "reason": reason}, ability="commercial.distribute", effect=effect)


def get_dispatch(company, dispatch_id, actor=None):
    actor = actor or current_actor()
    value = read("dispatch", dispatch_id, company, actor)
    instruction = raw("instruction", value["instruction_id"], company)
    if value["instruction_digest"] != digest(instruction) or value["issue_id"] != instruction["issue_id"]:
        raise DomainError("distribution_integrity", "The original dispatch instruction cannot be verified.", 409)
    rows = frappe.db.sql("SELECT name,state,result_json,last_error_code,payload_json,logical_id,payload_hash,recipient_id FROM `tabCipher Integration Operation` WHERE scope_type='Company' AND (project IS NULL OR project='') AND company=%s AND kind=%s AND distribution_dispatch=%s ORDER BY name LIMIT 31", (company, rules.KIND, dispatch_id), as_dict=True)
    if len(rows) > rules.MAX_RECIPIENTS:
        raise DomainError("distribution_limit", "This delivery inventory exceeds the bounded read limit.", 409)
    deliveries = []
    for row in rows:
        deliveries.append(_delivery_readback(row, value, instruction))
    recipients = [row["recipient_id"] for row in deliveries]
    if len(recipients) != len(set(recipients)) or set(recipients) != {r["id"] for r in instruction["recipients"]}:
        raise DomainError("distribution_integrity", "The dispatch recipient operation inventory is incomplete or inconsistent.", 409)
    states = {r["state"] for r in deliveries}
    state = "Unknown" if "Unknown" in states else "SucceededFixture" if states == {"Succeeded"} else "PartiallySucceeded" if "Succeeded" in states else "Cancelled" if states == {"Cancelled"} else "Failed" if states and states <= {"Failed", "Cancelled"} else "Queued"
    return {"dispatch": value, "state": state, "mode": "fixture", "deliveries": deliveries,
        "cancellation": cancellation(dispatch_id, company)}


def _delivery_readback(row, dispatch, instruction):
    """Bind a public acknowledgment to its exact immutable recipient intent."""
    def invalid():
        raise DomainError("distribution_integrity", "The recipient delivery evidence differs from its exact authorized intent.", 409)
    try:
        payload = json.loads(row.payload_json)
        result = json.loads(row.result_json) if row.result_json else None
    except (ValueError, TypeError):
        invalid()
    recipient = next((r for r in instruction["recipients"] if r["id"] == row.recipient_id), None)
    if recipient is None:
        invalid()
    expected = {"schema": "cipher.distribution.payload.v1", "company": dispatch["company"], "dispatch_id": dispatch["id"],
        "instruction_id": instruction["id"], "instruction_digest": digest(instruction), "issue_id": instruction["issue_id"],
        "recipient": recipient, "attachment": instruction["attachment"], "message": instruction["message"],
        "profile": instruction["profile"], "mode": "fixture"}
    if (payload != expected or digest(payload) != row.payload_hash or
            row.logical_id != rules.logical_key(dispatch["id"], recipient["id"]) or
            row.state not in {"Queued", "Claimed", "Unknown", "Succeeded", "Failed", "Cancelled"}):
        invalid()
    if type(result) is dict and set(result) == {"attempt_not_after", "mode"}:
        # This is the worker's durable authorized-attempt marker. Lost-ack
        # recovery and terminal refusals retain it; it is never a sink receipt.
        if result["mode"] != "fixture" or row.state not in {"Unknown", "Claimed", "Failed", "Cancelled"}:
            invalid()
        try:
            rules.moment(result["attempt_not_after"])
        except (ValueError, TypeError, AttributeError):
            invalid()
    elif result is not None:
        if type(result) is not dict or set(result) != {"mode", "receipt"} or result["mode"] != "fixture":
            invalid()
        ack = result["receipt"]
        fields = {"mode", "logical_key", "payload_hash", "attachment_sha256", "byte_length", "acknowledgment_id", "accepted_at"}
        if (type(ack) is not dict or set(ack) != fields or ack["mode"] != "fixture" or
                ack["logical_key"] != row.logical_id or ack["payload_hash"] != row.payload_hash or
                ack["attachment_sha256"] != instruction["attachment"]["sha256"] or
                ack["byte_length"] != instruction["attachment"]["byte_length"]):
            invalid()
        from uuid import UUID
        try:
            if str(UUID(ack["acknowledgment_id"])) != ack["acknowledgment_id"]:
                invalid()
            rules.moment(ack["accepted_at"])
        except (ValueError, TypeError, AttributeError):
            invalid()
    elif row.state == "Succeeded":
        invalid()
    return {"operation_id": row.name, "recipient_id": recipient["id"], "state": row.state,
        "logical_key": row.logical_id, "payload_hash": row.payload_hash,
        "mode": "fixture", "receipt": result, "error_code": row.last_error_code or None}


def authorize_receipt(actor, company, result, *, lock=False):
    for key, kind in (("instruction", "instruction"), ("cancellation", "cancellation")):
        value = result.get(key)
        if value:
            read(kind, value["id"], company, actor, lock=lock)
    if result.get("dispatch"):
        value = result["dispatch"]
        read("dispatch", value.get("dispatch", value)["id"], company, actor, lock=lock)


def list_dispatches(company, issue_id, limit=50, cursor=None, count_mode="none"):
    from cipher_aec.api.paging import page_options, decode_cursor, signing_secret, page_result
    from cipher_aec.governance.context import company_authority_fingerprint
    actor = current_actor()
    issue_source(company, issue_id, actor)
    limit, cursor, count_mode = page_options(limit, cursor, count_mode)
    scope = {"scope_type": "Company", "company": company, "selector": "proposal_dispatches", "issue_id": issue_id,
        "person": actor.person_id, "user": actor.user, "count_mode": count_mode, "authority": company_authority_fingerprint(actor, company)}
    last = decode_cursor(cursor, secret=signing_secret(), scope=scope) if cursor else None
    rows = frappe.db.sql("SELECT name,creation FROM `tabCipher Distribution Dispatch` WHERE company=%s AND issue_id=%s ORDER BY creation DESC,name DESC LIMIT 501", (company, issue_id), as_dict=True)
    if len(rows) > 500:
        raise DomainError("distribution_limit", "This Company exceeds the bounded dispatch inventory.", 409)
    allowed = []
    for row in rows:
        try:
            value = read("dispatch", row.name, company, actor)
        except DomainError as error:
            if error.status in {403, 404}:
                continue
            raise
        if value["issue_id"] == issue_id:
            allowed.append((row, value))
    total = len(allowed) if count_mode == "exact" else None
    selected = [(row, value) for row, value in allowed if not last or (str(row.creation), row.name) < tuple(last)]
    page = selected[:limit]
    return page_result([value for row, value in page], has_more=len(selected) > limit,
        last=[str(page[-1][0].creation), page[-1][0].name] if page else None,
        scope=scope, limit=limit, count_mode=count_mode, total=total)


def recipient_choices(company, issue_id):
    actor = current_actor()
    issue_id = text(issue_id, "Issue", 140)
    issue = issue_source(company, issue_id, actor)
    return {"issue_id": issue["id"], "issue_digest": digest(issue),
        "recipients": rules.chosen_recipients(issue["prepared_output"]["binding"]["recipients"], None)}


def list_instructions(company, issue_id=None, limit=50, cursor=None, count_mode="none"):
    """Current authorized saved drafts, without inferring approval/delivery state."""
    from contextlib import nullcontext
    from cipher_aec.api.paging import page_options, decode_cursor, signing_secret, page_result
    from cipher_aec.governance.context import company_authority_fingerprint
    from cipher_aec.documents.provenance import read_graph, read_graph_eligible
    actor = current_actor()
    require_company(company, ability="commercial.read", actor=actor)
    if issue_id is not None:
        issue_id = text(issue_id, "Issue", 140)
        issue_source(company, issue_id, actor)
    limit, cursor, count_mode = page_options(limit, cursor, count_mode)
    scope = {"scope_type": "Company", "company": company, "selector": "proposal_instructions",
        "issue_id": issue_id, "person": actor.person_id, "user": actor.user, "count_mode": count_mode,
        "authority": company_authority_fingerprint(actor, company)}
    last = decode_cursor(cursor, secret=signing_secret(), scope=scope) if cursor else None
    fields, values = "name,creation,issue_id", []
    if last:
        fields += ", (creation<%s OR (creation=%s AND name<%s)) AS after_cursor"
        values.extend((last[0],last[0],last[1]))
    where = "company=%s AND scope_type='Company' AND (project IS NULL OR project='')"
    values.append(company)
    if issue_id is not None:
        where += " AND issue_id=%s"
        values.append(issue_id)
    # Every candidate is authorized before even a has_more bit or total. The
    # fixed overflow sentinel prevents a partial authorized inventory claim.
    with read_graph(actor, company) if read_graph_eligible(actor, company) else nullcontext():
        rows = frappe.db.sql("SELECT " + fields + " FROM `tabCipher Distribution Instruction` WHERE " + where +
            " ORDER BY creation DESC,name DESC LIMIT 501", tuple(values), as_dict=True)
        if len(rows) > 500:
            raise DomainError("distribution_limit", "This Company exceeds the bounded instruction inventory.", 409)
        selected, total = [], 0
        for row in rows:
            try:
                value = read("instruction", row.name, company, actor)
            except DomainError as error:
                if error.status in {403, 404}:
                    continue
                raise
            if value["issue_id"] != row.issue_id:
                raise DomainError("distribution_integrity", "The saved instruction index differs from its immutable source.", 409)
            total += 1
            if len(selected) <= limit and (not last or row.after_cursor):
                selected.append((row,value))
        page = selected[:limit]
        return page_result([{"instruction": value, "version": digest(value)} for row,value in page],
            has_more=len(selected)>limit, last=[str(page[-1][0].creation),page[-1][0].name] if page else None,
            scope=scope, limit=limit, count_mode=count_mode, total=total if count_mode=="exact" else None)


def query_denied(user=None):
    return "1=0"


def permission_denied(doc, ptype=None, user=None, **kwargs):
    return False

"""Closed semantic RPCs; providers remain disabled until explicitly configured."""
import frappe
from cipher_aec.api.errors import DomainError
from cipher_aec.api.transport import endpoint
from cipher_aec.semantic_index import api


def _closed_request(operation, fields):
    # Frappe filters kwargs before calling a whitelisted function. Check the
    # original field names so discarded extras cannot widen the closed schema.
    request = getattr(frappe.local, "request", None)
    if request and request.method == "POST":
        values = frappe.form_dict or {}
        if set(values) - set(fields) - {"cmd"} or ("cmd" in values and values["cmd"] != "cipher_aec.api.semantic." + operation):
            raise DomainError("semantic_invalid_input", "Use the exact bounded semantic search contract.", 422)


@endpoint(methods=["POST"])
def prepare(scope, sources, operation_id):
    _closed_request("prepare", {"scope", "sources", "operation_id"})
    return api.call("prepare", {"scope": scope, "sources": sources, "operation_id": operation_id})


@endpoint(methods=["POST"])
def cancel(scope, operation_id):
    _closed_request("cancel", {"scope", "operation_id"})
    return api.call("cancel", {"scope": scope, "operation_id": operation_id})


@endpoint(methods=["POST"])
def status(scope, job_operation_id):
    # Read an existing job without turning its reference into a new command key.
    _closed_request("status", {"scope", "job_operation_id"})
    return api.call("status", {"scope": scope, "operation_id": job_operation_id})


@endpoint(methods=["POST"])
def query(scope, question, limit):
    _closed_request("query", {"scope", "question", "limit"})
    return api.call("query", {"scope": scope, "question": question, "limit": limit})

from functools import wraps
import inspect
import uuid

import frappe

from .contracts import SCHEMA, utc_timestamp
from .errors import DomainError


def envelope(data=None, error=None, request_id=None):
    request_id = request_id or str(uuid.uuid4())
    body = {"schema": SCHEMA, "request_id": request_id,
        "meta": {"request_id": request_id, "api_version": "v1", "server_time": utc_timestamp()}}
    if error:
        body["error"] = {**error.as_dict(), "retryable": error.status in {429, 503}}
    else:
        body["data"] = data
    return body


def endpoint(methods=None):
    methods = methods or ["GET"]

    def decorate(function):
        signature = inspect.signature(function)

        @wraps(function)
        def wrapped(*args, **kwargs):
            request_id = str(uuid.uuid4())
            try:
                from cipher_aec.governance.context import assert_synthetic_site, current_actor
                assert_synthetic_site()
                current_actor()
                # Frappe invokes whitelisted functions with filtered kwargs; reject extras
                # on direct JSON calls as well instead of silently trusting actor fields.
                request = getattr(frappe.local, "request", None)
                if request and request.method == "POST":
                    values = frappe.form_dict or {}
                    forbidden = {"actor", "person", "person_id", "user", "role", "duties", "ignore_permissions"}
                    if forbidden.intersection(values):
                        raise DomainError("forged_authority", "Identity and duties come from your session.", 422)
                    if "operation_id" in signature.parameters:
                        header = frappe.get_request_header("Idempotency-Key")
                        if not header:
                            raise DomainError("idempotency_key_required", "Send an Idempotency-Key for this command.", 428)
                        if kwargs.get("operation_id") and kwargs["operation_id"] != header:
                            raise DomainError("operation_conflict", "Operation ID and Idempotency-Key must agree.", 409)
                        kwargs["operation_id"] = header
                result = function(*args, **kwargs)
                if frappe.local.response.get("type") == "download":
                    return result
                return envelope(result, request_id=request_id)
            except DomainError as error:
                if "POST" in methods:
                    frappe.db.rollback()
                frappe.local.response["http_status_code"] = error.status
                return envelope(error=error, request_id=request_id)
            except (frappe.QueryDeadlockError, frappe.QueryTimeoutError):
                frappe.db.rollback()
                frappe.local.response["http_status_code"] = 503
                frappe.local.response_headers["Retry-After"] = "1"
                return envelope(error=DomainError("concurrent_change", "Records changed concurrently. Retry the original operation after refreshing current access.", 503), request_id=request_id)
            except Exception:
                if "POST" in methods:
                    frappe.db.rollback()
                frappe.log_error(title="Cipher request " + request_id)
                frappe.local.response["http_status_code"] = 500
                return envelope(error=DomainError("request_failed", "The request could not be completed. Retry or contact support with the request ID.", 500), request_id=request_id)
        return frappe.whitelist(allow_guest=True, methods=methods)(wrapped)
    return decorate

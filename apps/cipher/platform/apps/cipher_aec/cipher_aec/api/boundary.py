"""Fail-closed R0 HTTP catalog for ordinary application users.

ERPNext Desk remains administrator tooling. Upstream whitelisted mappers can
accept ignore_permissions independently of document hooks; product users do not
receive arbitrary RPC access just because their Frappe account can authenticate.
"""

import json

import frappe

from .errors import DomainError
from .transport import envelope

from .catalog import RPC
RESOURCE_READS = frozenset({"Project", "Task", "Cipher Document", "Cipher Document Revision"})


def allowed_request(path, method, legacy_cmd=None):
    from urllib.parse import unquote
    # app.py dispatches form_dict.cmd before matching /api routes. A caller may
    # not smuggle a different RPC through '/' or an otherwise allowed URL.
    if legacy_cmd is not None:
        return False
    if path.startswith("/api/method/"):
        return unquote(path[len("/api/method/"):]) in RPC
    if path.startswith("/api/resource/") and method == "GET":
        doctype = unquote(path[len("/api/resource/"):].split("/")[0])
        return doctype in RESOURCE_READS
    return not (path.startswith("/api/") or path == "/api" or path == "/app" or path.startswith("/app/"))


def before_request():
    user = frappe.session.user
    if user == "Guest" or user == "Administrator" or "System Manager" in frappe.get_roles(user):
        return
    request = frappe.request
    if not allowed_request(request.path, request.method, (frappe.form_dict or {}).get("cmd")):
        frappe.local.cipher_boundary_denied = True
        raise frappe.PermissionError("This route is not available to Cipher application users.")


def after_request(response, request):
    product_route = request.path.startswith("/api/method/cipher_aec.")
    denied = bool(getattr(frappe.local, "cipher_boundary_denied", False))
    if not (product_route or denied):
        return
    original = response.get_json(silent=True) or {}
    if isinstance(original, dict) and isinstance(original.get("message"), dict) and original["message"].get("schema") == "cipher.api.v1":
        # Frappe serializes native msgprint/error metadata after our endpoint
        # returns. Keep the published canonical envelope as the only wire body;
        # internal native messages must not bypass its disclosure policy.
        response.set_data(json.dumps({"message": original["message"]}))
        response.content_type = "application/json"
        response.headers["Cache-Control"] = "private, no-store"
        return
    if response.status_code < 400:
        return
    if denied:
        error = DomainError("route_unavailable", "Use Cipher's authorized application actions for this work.", 403)
        response.status_code = 403
    elif response.status_code in (401, 403):
        error = DomainError("authentication_required" if frappe.session.user == "Guest" else "request_denied",
            "Sign in to continue." if frappe.session.user == "Guest" else "This request is not permitted. Refresh your session and try again.", response.status_code)
    else:
        error = DomainError("request_rejected", "The request could not be accepted. Check the input or contact support.", response.status_code)
    response.set_data(json.dumps({"message": envelope(error=error)}))
    response.content_type = "application/json"
    response.headers["Cache-Control"] = "private, no-store"

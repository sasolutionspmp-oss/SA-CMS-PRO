"""Actual Frappe response serialization followed by Cipher's HTTP boundary."""
from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from jsonschema import Draft202012Validator, FormatChecker
from werkzeug.wrappers import Response

from cipher_aec.api.boundary import after_request
from cipher_aec.api.errors import DomainError
from cipher_aec.api.openapi import generate
from cipher_aec.api.transport import envelope


class TestCanonicalWire(IntegrationTestCase):
    def setUp(self):
        super().setUp()
        self.previous = {name: getattr(frappe.local, name, None) for name in (
            "response", "message_log", "error_log", "debug_log", "cipher_boundary_denied")}
        self.previous_error = frappe.flags.error_message
        frappe.local.response = frappe._dict()
        frappe.local.message_log = []
        frappe.local.error_log = []
        frappe.local.debug_log = []
        frappe.local.cipher_boundary_denied = False
        frappe.flags.error_message = None
        self.request = SimpleNamespace(path="/api/method/cipher_aec.commercial.api.create_proposal")

    def tearDown(self):
        for name, value in self.previous.items():
            setattr(frappe.local, name, value)
        frappe.flags.error_message = self.previous_error
        super().tearDown()

    def native_response(self, body, status):
        from frappe.api import ApiVersion
        from frappe.utils.response import build_response
        frappe.local.response.update(message=body, http_status_code=status)
        with patch("frappe.api.get_api_version", return_value=ApiVersion.V1), \
                patch("frappe.utils.response.is_traceback_allowed", return_value=True):
            return build_response("json")

    def test_native_permission_message_is_excluded_from_canonical_error_wire(self):
        with self.assertRaises(frappe.PermissionError):
            frappe.throw("Private native account diagnostic", exc=frappe.PermissionError)
        frappe.flags.error_message = "Private native failure flag"
        frappe.local.debug_log = ["Private native debug detail"]
        frappe.local.response["exc"] = "Private previously attached traceback"
        body = envelope(error=DomainError("native_permission_denied", "Current native source permissions do not permit this quotation draft.", 403))
        response = self.native_response(body, 403)
        self.assertIn("_server_messages", response.get_json())
        self.assertIn("_debug_messages", response.get_json())
        self.assertIn("_error_message", response.get_json())
        response.headers["X-Request-Proof"] = "retained"
        after_request(response, self.request)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.get_json(), {"message": body})
        self.assertNotIn(b"Private", response.data)
        self.assertEqual(response.headers["X-Request-Proof"], "retained")
        self.assertEqual(response.headers["Cache-Control"], "private, no-store")
        schema = generate()["paths"][self.request.path]["post"]["responses"]["403"]["content"]["application/json"]["schema"]
        Draft202012Validator({"components": generate()["components"], **schema}, format_checker=FormatChecker()).validate(response.get_json())
        self.assertTrue(frappe.local.message_log, "The wire boundary does not erase server-side diagnostics.")

    def test_canonical_success_keeps_exact_data_and_excludes_native_auxiliary_payloads(self):
        frappe.msgprint("Internal native warning")
        frappe.local.response.update(docs=[{"private": "native document"}], docinfo={"private": "native metadata"})
        body = envelope(data={"immutable": {"id": "original", "version": 1}})
        response = self.native_response(body, 200)
        self.assertIn("_server_messages", response.get_json())
        after_request(response, self.request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"message": body})

    def test_document_download_remains_exact_binary_with_headers(self):
        response = Response(b"%PDF-1.7\nactual-test-bytes", mimetype="application/pdf")
        response.headers["Content-Disposition"] = 'attachment; filename="source.pdf"'
        before = response.data, list(response.headers.items())
        after_request(response, SimpleNamespace(path="/api/method/cipher_aec.documents.company_api.content"))
        self.assertEqual((response.data, list(response.headers.items())), before)

    def test_other_application_routes_keep_their_original_response(self):
        response = Response('{"_server_messages":"native tooling message"}', status=403, mimetype="application/json")
        before = response.data, list(response.headers.items()), response.status_code
        after_request(response, SimpleNamespace(path="/api/method/frappe.client.get"))
        self.assertEqual((response.data, list(response.headers.items()), response.status_code), before)

"""Contract drift checks independent of Frappe or a running site."""
import json
import unittest
from pathlib import Path

from cipher_aec.api.catalog import ROUTES, RPC
from cipher_aec.api.openapi import API, generate


class OpenAPITests(unittest.TestCase):
    def test_clause_target_get_exposes_complete_kind_specific_request_schema(self):
        from jsonschema import Draft202012Validator,FormatChecker,ValidationError
        document=generate()
        path=document["paths"]["/api/method/cipher_aec.document_control.api.read_clause_target"]
        self.assertEqual(set(path),{"get"})
        operation=path["get"]
        self.assertEqual([p["name"] for p in operation["parameters"]],["company","project","kind","record_id"])
        request=operation["x-request-schema"]
        self.assertEqual(request,document["components"]["schemas"]["DcReadClauseTargetRequest"])
        current=Draft202012Validator({"components":document["components"],**request},format_checker=FormatChecker())
        current.validate({"company":"C","project":"P","kind":"document_revision","record_id":"REV-00001"})
        for kind in ("proposal_revision","contract_revision"):
            current.validate({"company":"C","project":"P","kind":kind,"record_id":"11111111-1111-4111-8111-111111111111"})
            with self.subTest(kind=kind),self.assertRaises(ValidationError):
                current.validate({"company":"C","project":"P","kind":kind,"record_id":"REV-00001"})
        for record_id in ("","R"*141):
            with self.subTest(record_id=record_id),self.assertRaises(ValidationError):
                current.validate({"company":"C","project":"P","kind":"document_revision","record_id":record_id})

    def test_field_post_bodies_preserve_exact_declared_request_refinements(self):
        document=generate()
        requests={"create_record":"FdCreateRecordRequest","revise_record":"FdReviseRecordRequest","transition":"FdTransitionRequest"}
        for method,request in requests.items():
            with self.subTest(method=method):
                body=document["paths"]["/api/method/cipher_aec.field.api."+method]["post"]["requestBody"]["content"]["application/json"]["schema"]
                self.assertEqual(body,document["components"]["schemas"][request])

    def test_generated_field_requests_reject_cross_family_and_acknowledgment_mismatches(self):
        from jsonschema import Draft202012Validator,FormatChecker,ValidationError
        from types import SimpleNamespace
        from cipher_aec.tests.test_field import daily,ticket,quantity,uid
        document=generate()
        def validator(method):
            body=document["paths"]["/api/method/cipher_aec.field.api."+method]["post"]["requestBody"]["content"]["application/json"]["schema"]
            return Draft202012Validator({"components":document["components"],**body},format_checker=FormatChecker())
        source={"revision_id":uid(),"source_sha256":"a"*64,"page":1,"locator":"Exact source observation"}
        base={"company":"C","project":"P","operation_id":uid(),"family":"daily","definition":daily(SimpleNamespace(actor=SimpleNamespace(user="superintendent@example.invalid"))),"photos":[],"quantities":[quantity(source)]}
        ticket_request={**base,"family":"ticket","definition":ticket(source),"quantities":[]}
        for method in ("create_record","revise_record"):
            additional={"record_id":uid(),"expected_version":"b"*64} if method=="revise_record" else {}
            current=validator(method)
            for valid in (base,ticket_request):current.validate({**valid,**additional})
            for invalid in ({**base,"family":"ticket"},{**ticket_request,"family":"daily"},{**ticket_request,"quantities":[quantity(source)]}):
                with self.subTest(method=method,invalid=invalid),self.assertRaises(ValidationError):current.validate({**invalid,**additional})
        submitted={"company":"C","project":"P","operation_id":uid(),"family":"daily","record_id":uid(),"expected_version":"b"*64,"action":"submit","comment":"Observed facts submitted.","evidence":[]}
        acknowledged={**submitted,"family":"ticket","action":"acknowledge","evidence":[source],"acknowledged_by":"Synthetic customer representative"}
        current=validator("transition")
        current.validate(submitted);current.validate(acknowledged)
        for invalid in ({**acknowledged,"family":"daily"},{**acknowledged,"evidence":[]},{key:value for key,value in acknowledged.items() if key!="acknowledged_by"},{**submitted,"acknowledged_by":"Unrelated name"}):
            with self.subTest(invalid=invalid),self.assertRaises(ValidationError):current.validate(invalid)

    def test_every_catalog_route_has_typed_method_body_and_envelope(self):
        document=generate()
        self.assertEqual(document["openapi"],"3.1.0")
        self.assertEqual(len(document["paths"]),len(ROUTES))
        for name,route in ROUTES.items():
            with self.subTest(route=name):
                path=document["paths"]["/api/method/"+name]
                self.assertEqual(set(path),{route.method.lower()})
                operation=path[route.method.lower()]
                self.assertEqual(operation["operationId"],name)
                if route.method=="POST":
                    body=operation["requestBody"]["content"]["application/json"]["schema"]
                    self.assertFalse(body["additionalProperties"])
                    headers={p["name"] for p in operation["parameters"]}
                    self.assertEqual("Idempotency-Key" in headers,route.command)
                if not route.binary:
                    response=operation["responses"]["200"]["content"]["application/json"]["schema"]
                    self.assertIn("message",response["required"])
                self.assertIn("503",operation["responses"])
                self.assertIn(name,RPC)

    def test_local_schema_references_all_resolve(self):
        document=generate()
        def walk(value):
            if isinstance(value,dict):
                for key,item in value.items():
                    if key=="$ref":
                        self.assertTrue(item.startswith("#/"),item)
                        target=document
                        for part in item[2:].split("/"):
                            target=target[part.replace("~1","/").replace("~0","~")]
                    else:walk(item)
            elif isinstance(value,list):
                for item in value:walk(item)
        walk(document)

    def test_embedded_canonical_manifest_references_validate_real_fixture(self):
        from jsonschema import Draft202012Validator, ValidationError
        document=generate()
        schema={"$schema":"https://json-schema.org/draft/2020-12/schema","components":document["components"],"$ref":"#/components/schemas/CanonicalManifest"}
        manifest=json.loads((API.parent/"migrations/fixtures/canonical-masters-v1.json").read_text())
        validator=Draft202012Validator(schema)
        validator.validate(manifest)
        manifest["records"][0]["id"]="not-a-uuid"
        with self.assertRaises(ValidationError):validator.validate(manifest)

    def test_generated_artifact_matches_fixed_catalog_and_current_canonical_schema(self):
        self.assertEqual(json.loads((API/"openapi.json").read_text()),generate())
        expected=json.loads((API.parent/"migrations/schemas/canonical-v1.schema.json").read_text())
        actual=generate()["components"]["schemas"]["CanonicalManifest"]
        self.assertEqual(actual["properties"]["schema"],expected["properties"]["schema"])
        self.assertEqual(actual["properties"]["records"]["maxItems"],500)


if __name__=="__main__":unittest.main()

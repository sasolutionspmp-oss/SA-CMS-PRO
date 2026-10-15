"""Contract drift checks independent of Frappe or a running site."""
import json
import unittest
from pathlib import Path

from cipher_aec.api.catalog import ROUTES, RPC
from cipher_aec.api.openapi import API, generate


class OpenAPITests(unittest.TestCase):
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

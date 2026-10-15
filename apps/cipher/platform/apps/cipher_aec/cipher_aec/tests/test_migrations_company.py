"""Versioned Company manifests preserve existing Project bytes and exact units."""
import copy
import hashlib
import json
from pathlib import Path
import unittest

from jsonschema import Draft202012Validator
from cipher_aec.migrations.contracts import COMPANY_SCHEMA
from cipher_aec.migrations.validation import ManifestError, conversion_fraction, manifest_digest, parse_manifest, quantity_previews

ROOT=Path(__file__).parents[1]/'migrations'


class CompanyManifestTests(unittest.TestCase):
    def setUp(self):
        self.original=json.loads((ROOT/'fixtures/canonical-masters-v1.json').read_text())
        self.company=copy.deepcopy(self.original)
        self.company['schema']=COMPANY_SCHEMA
        self.company['scope']={'scope_type':'Company','company':self.original['scope']['company'],'project':None}
        self.company['records']=[row for row in self.company['records'] if row['kind']!='project']

    def test_v1_fixture_digest_and_schema_bytes_remain_unchanged(self):
        self.assertEqual(manifest_digest(parse_manifest(self.original)),'ab485b55db46e6ac85747158ceac36b1f382b0278ec5b0760008115481b9466f')
        self.assertEqual(hashlib.sha256((ROOT/'schemas/canonical-v1.schema.json').read_bytes()).hexdigest(),'03a6c857ee3c8189b16242ebd87746b2820a4e12b3a815bc4b4fea776e83c1f9')
        self.assertEqual(self.original['scope'],{'company':'Cipher MIG-01 Synthetic Design Company','project':'MIG01-FIXTURE-PROJECT'})

    def test_company_exact_rational_quantities_use_same_unit_authority(self):
        parsed=parse_manifest(self.company)
        self.assertEqual(quantity_previews(parsed)[0]['exact_numerator'],'1')
        self.assertEqual(quantity_previews(parsed)[0]['exact_denominator'],'1')
        schema=json.loads((ROOT/'schemas/canonical-v2.schema.json').read_text())
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(parsed)
        original=manifest_digest(parsed)
        parsed['records'].reverse()
        self.assertEqual(manifest_digest(parse_manifest(parsed)),original)

    def test_project_absence_or_string_never_implicitly_grants_company_scope(self):
        scopes=({'company':'A','project':None},{'scope_type':'Project','company':'A','project':None},{'scope_type':'Company','company':'A','project':''},{'scope_type':'Company','company':'A','project':'P'},{'scope_type':'Company','company':'A'})
        for scope in scopes:
            value=copy.deepcopy(self.company);value['scope']=scope
            with self.assertRaises(ManifestError):parse_manifest(value)
        value=copy.deepcopy(self.original);value['scope']['project']=None
        with self.assertRaises(ManifestError):parse_manifest(value)

    def test_company_cannot_bind_project_or_foreign_company_target(self):
        value=copy.deepcopy(self.company)
        value['records'].append(next(row for row in self.original['records'] if row['kind']=='project'))
        with self.assertRaises(ManifestError):parse_manifest(value)
        company=next(row for row in self.company['records'] if row['kind']=='company')
        company['target']={'doctype':'Company','name':'Different Company'}
        with self.assertRaises(ManifestError):parse_manifest(self.company)

"""Independent canonical master/dimension contracts, exact units and opaque previews."""
import copy
from fractions import Fraction
import json
from pathlib import Path
from uuid import uuid4
import unittest

from cipher_aec.migrations.preview import TargetSnapshot, preview_manifest
from cipher_aec.migrations.validation import (ManifestError, conversion_fraction, decimal_quantity,
                                              manifest_digest, parse_manifest, quantity_previews)

FIXTURE = Path(__file__).parents[1] / 'migrations/fixtures/canonical-masters-v1.json'


class CanonicalManifestTests(unittest.TestCase):
    def setUp(self):
        self.manifest = json.loads(FIXTURE.read_text())
        self.rows = {r['source']['record_id']: r for r in self.manifest['records']}

    def invalid(self, mutation):
        candidate = copy.deepcopy(self.manifest)
        mutation(candidate)
        with self.assertRaises(ManifestError):
            parse_manifest(candidate)

    def test_fresh_standalone_fixture_has_all_target_master_and_typed_dimension_kinds(self):
        result = parse_manifest(self.manifest)
        self.assertEqual({r['kind'] for r in result['records']}, {'company','project','customer','supplier','item','uom','cost_center','cost_code','cost_type','accounting_dimension'})
        self.assertTrue(all(r['source']['system'] == 'fresh-synthetic-target-design' for r in result['records']))
        self.assertEqual(quantity_previews(result)[0]['exact_numerator'], '1')
        self.assertEqual(quantity_previews(result)[0]['exact_denominator'], '1')

    def test_stable_uuid_identity_survives_reordering_and_labels_are_not_master_keys(self):
        original = manifest_digest(parse_manifest(self.manifest))
        self.manifest['records'].reverse()
        self.assertEqual(original, manifest_digest(parse_manifest(self.manifest)))
        duplicates = [r for r in self.manifest['records'] if r['kind'] == 'cost_type']
        duplicates[1]['fields']['title'] = duplicates[0]['fields']['title']
        self.assertNotEqual(duplicates[0]['id'], duplicates[1]['id'])
        parse_manifest(self.manifest)
        self.invalid(lambda m: m['records'][1].update(id=m['records'][0]['id']))

    def test_unconfigured_timezone_is_explicit_and_blocks_operational_readiness(self):
        from cipher_aec.migrations.validation import manifest_requirements
        self.rows['company']['fields']['timezone'] = None
        parsed = parse_manifest(self.manifest)
        self.assertEqual(manifest_requirements(parsed)[0]['code'], 'company_timezone_unconfigured')
        self.assertFalse(preview_manifest(parsed, lambda *args: None)['apply_available'])

    def test_pinned_native_on_hold_project_exports_and_previews_without_translation(self):
        row = self.rows['project']
        row['fields']['status'] = 'On hold'
        row['target'] = {'doctype':'Project','name':'bound-project'}
        parsed = parse_manifest(self.manifest)
        result = preview_manifest(parsed, lambda current, manifest: TargetSnapshot(dict(current['fields']), 'current'))
        self.assertEqual(next(r for r in result['records'] if r['id']==row['id'])['action'], 'matches')

    def test_unknown_fields_and_arbitrary_target_doctypes_are_rejected(self):
        self.invalid(lambda m: m.update(ignore_permissions=True))
        self.invalid(lambda m: m['records'][0]['fields'].update(secret='arbitrary native field'))
        self.invalid(lambda m: m['records'][0].update(target={'doctype':'User','name':'Administrator'}))

    def test_json_duplicate_keys_and_numeric_decimals_are_rejected(self):
        with self.assertRaises(ManifestError):
            parse_manifest('{"schema":"cipher.canonical.v1","schema":"replacement"}')
        for value in (1.1, True, '1e2', 'NaN', 'Infinity', '-0', '-0.00', '01', '0.1234567890123'):
            with self.assertRaises(ManifestError):
                decimal_quantity(value, 'quantity')

    def test_company_and_reference_type_must_resolve_in_same_manifest(self):
        self.invalid(lambda m: m['records'][1]['fields'].update(company_id=str(uuid4())))
        self.invalid(lambda m: m['records'][3]['fields'].update(customer_id=m['records'][2]['id']))
        self.invalid(lambda m: m['records'][3]['fields'].update(customer_id=str(uuid4())))

    def test_cost_center_parent_cycles_are_rejected(self):
        root, child = self.rows['root-cost-center'], self.rows['cost-center']
        root['fields']['parent_id'] = child['id']
        with self.assertRaisesRegex(ManifestError, 'cycle'):
            parse_manifest(self.manifest)

    def test_exact_rational_paths_and_reciprocals_do_not_round(self):
        parsed = parse_manifest(self.manifest)
        inch, foot = self.rows['inch']['id'], self.rows['foot']['id']
        self.assertEqual(conversion_fraction(parsed, inch, foot), Fraction(1, 12))
        self.assertEqual(conversion_fraction(parsed, foot, inch), Fraction(12))
        parsed['quantities'][0]['amount'] = '1'
        preview = quantity_previews(parsed)[0]
        self.assertEqual((preview['exact_numerator'], preview['exact_denominator']), ('1', '12'))
        self.assertFalse(preview['rounding_applied'])

    def test_dimension_labels_are_not_inferred_from_similar_names(self):
        labor, equipment = self.rows['labor-hour'], self.rows['equipment-hour']
        equipment['fields']['symbol'] = labor['fields']['symbol']
        self.manifest['quantities'] = [{'id':str(uuid4()),'amount':'1','unit_id':labor['id'],'convert_to_unit_id':equipment['id']}]
        with self.assertRaisesRegex(ManifestError, 'compatible'):
            parse_manifest(self.manifest)
        conversion = self.manifest['unit_conversions'][0]
        conversion['to_unit_id'] = self.rows['square-foot']['id']
        with self.assertRaisesRegex(ManifestError, 'dimension'):
            parse_manifest(self.manifest)

    def test_factors_reject_zero_float_negative_unreduced_and_inconsistent_cycles(self):
        for numerator, denominator in [('0','1'),('1','0'),('-1','12'),(1,'12'),('2','24'),('1.0','12')]:
            candidate=copy.deepcopy(self.manifest)
            candidate['unit_conversions'][0].update(numerator=numerator,denominator=denominator)
            with self.assertRaises(ManifestError):
                parse_manifest(candidate)
        conversion=self.manifest['unit_conversions'][0]
        self.manifest['unit_conversions'].append({**conversion,'id':str(uuid4()),'from_unit_id':conversion['to_unit_id'],'to_unit_id':conversion['from_unit_id'],'numerator':'10','denominator':'1'})
        with self.assertRaisesRegex(ManifestError, 'disagree'):
            parse_manifest(self.manifest)

    def test_precision_and_malformed_reference_types_fail_cleanly(self):
        for mutation in (lambda m:m['quantities'][0].update(unit_id={}),
                         lambda m:m['unit_conversions'][0].update(from_unit_id=[]),
                         lambda m:m['records'][4]['fields'].update(dimension=[]),
                         lambda m:m['quantities'][0].update(amount='0.0000001')):
            self.invalid(mutation)
        count=self.rows['each']
        self.manifest['quantities']=[{'id':str(uuid4()),'amount':'1.5','unit_id':count['id']}]
        with self.assertRaisesRegex(ManifestError, 'precision'):
            parse_manifest(self.manifest)

    def test_preview_never_auto_matches_unbound_display_names_or_writes(self):
        calls=[]
        result=preview_manifest(self.manifest,lambda *args:calls.append(args))
        self.assertFalse(calls)
        self.assertTrue(all(r['action']=='create_candidate' for r in result['records']))
        self.assertFalse(result['apply_available'])
        self.assertEqual(result['writes_performed'],0)

    def test_private_missing_and_wrong_scope_targets_have_identical_preview_rows(self):
        company=self.rows['company']
        company['target']={'doctype':'Company','name':'private-or-missing'}
        first=preview_manifest(self.manifest,lambda row,manifest:None)
        company['target']['name']='different-denied-or-missing'
        second=preview_manifest(self.manifest,lambda row,manifest:None)
        self.assertEqual(first['records'],second['records'])
        self.assertNotIn('target_name',str(first['records']))

    def test_accessible_preview_shows_only_whitelisted_changes_and_stale_versions(self):
        row=self.rows['company'];row['target']={'doctype':'Company','name':'bound','version':'old'}
        result=preview_manifest(self.manifest,lambda r,m:TargetSnapshot({**r['fields'],'currency':'EUR'},'new'))
        self.assertEqual(result['records'][0]['action'],'stale')
        row['target']['version']='new'
        result=preview_manifest(self.manifest,lambda r,m:TargetSnapshot({**r['fields'],'currency':'EUR'},'new'))
        self.assertEqual(result['records'][0]['changes'],[{'field':'currency','current':'EUR','proposed':'USD'}])

    def test_two_source_uuids_cannot_alias_one_native_target(self):
        centers=[r for r in self.manifest['records'] if r['kind']=='cost_center']
        for row in centers:
            row['target']={'doctype':'Cost Center','name':'same-target'}
        with self.assertRaisesRegex(ManifestError,'Two source identities'):
            parse_manifest(self.manifest)


class UnitPreviewAuthorityTests(unittest.TestCase):
    setUp = CanonicalManifestTests.setUp
    def native_snapshot(self, row, **native):
        from cipher_aec.migrations.export import FrappeTargetReader
        class Record(dict):
            __getattr__ = dict.__getitem__
        reader = object.__new__(FrappeTargetReader)
        reader.fetch = lambda *args: Record(uom_name='native unit', must_be_whole_number=0, modified='current', **native)
        return reader.snapshot(row, self.manifest)

    def test_unregistered_uom_proposals_never_establish_native_authority(self):
        row = self.rows['inch']
        row['target'] = {'doctype':'UOM','name':'native unit'}
        row['fields']['dimension'] = 'mass'
        self.manifest['unit_conversions']=[]
        self.manifest['quantities']=[]
        result = preview_manifest(self.manifest, lambda current, manifest: self.native_snapshot(current))
        displayed = next(r for r in result['records'] if r['id'] == row['id'])
        self.assertEqual(displayed['action'],'declaration_candidate')
        self.assertTrue(displayed['warnings'])
        self.assertEqual(displayed['proposed_declaration']['dimension'],'mass')

    def test_registered_uuid_revision_and_immutable_fields_are_checked(self):
        row = self.rows['inch']; row['target']={'doctype':'UOM','name':'native unit'}
        authoritative={'cipher_unit_id':row['id'],'cipher_unit_revision':row['revision'],
                       'cipher_dimension':row['fields']['dimension'],'cipher_quantity_precision':row['fields']['precision'],'symbol':'registered-symbol'}
        snapshot = lambda current, manifest: self.native_snapshot(current,**authoritative)
        matching=preview_manifest(self.manifest,snapshot)
        # Symbol is independently native and cannot be fabricated from proposed fields.
        displayed=next(r for r in matching['records'] if r['id']==row['id'])
        self.assertEqual(displayed['action'],'immutable_unit_conflict')
        row['fields']['symbol']='registered-symbol'
        result=preview_manifest(self.manifest,snapshot)
        self.assertEqual(next(r for r in result['records'] if r['id']==row['id'])['action'],'matches')
        row['revision']=2
        result=preview_manifest(self.manifest,snapshot)
        self.assertEqual(next(r for r in result['records'] if r['id']==row['id'])['action'],'stale_unit_revision')
        row['revision']=1
        authoritative['cipher_unit_id']=str(uuid4())
        result=preview_manifest(self.manifest,snapshot)
        self.assertEqual(next(r for r in result['records'] if r['id']==row['id'])['action'],'identity_conflict')

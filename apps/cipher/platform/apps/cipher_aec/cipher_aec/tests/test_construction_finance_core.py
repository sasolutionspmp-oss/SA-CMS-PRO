"""Meaningful exact arithmetic and accepted-cap protection, without fake certificates."""
from copy import deepcopy
from dataclasses import replace
from uuid import uuid4
import unittest

from cipher_aec.api.errors import DomainError
from cipher_aec.construction_finance import core


class ConstructionFinanceCoreTests(unittest.TestCase):
    def setUp(self):
        self.unit = str(uuid4())
        self.units = {self.unit: {'fields': {'precision': 6}}}
        self.contract, self.revision, self.sov = (str(uuid4()) for _ in range(3))
        self.policy = {'basis': 'installed_plus_eligible_stored', 'tiers': [{'up_to': None, 'rate': '0.05'}], 'cap': {'amount': '100.00', 'currency': 'USD'},
                       'effective_date': '2026-10-15', 'rounding': 'HALF_UP', 'reduction_conditions': 'Explicit fixture reduction conditions',
                       'release_conditions': 'Independent fixture review required', 'approval_basis': 'Authored synthetic policy, no executed agreement'}
        self.line = {'line_id': str(uuid4()), 'item_code': 'SOV-001', 'description': 'Authored foundation work',
                     'quantity': {'amount': '10.000001', 'unit_id': self.unit, 'precision': 6}, 'scheduled_amount': {'amount': '100.01', 'currency': 'USD'},
                     'cost_code': 'FOUND', 'stored_material_eligible': True, 'source_line_id': None}
        self.cap = {'amount': '1000.00', 'currency': 'USD'}

    def preserved(self, lines, floor=None):
        return core.preserve_accepted([self.line], lines, contract_id=self.contract, revision_id=self.revision, sov_id=self.sov, currency='USD', floor=floor)

    def test_money_never_accepts_float_exponent_negative_or_currency_substitution(self):
        for value in (1.2, True, '-1.00', '1e2', 'NaN', '01.00', '1.001'):
            with self.subTest(value=value), self.assertRaises(DomainError):
                core.money({'amount': value, 'currency': 'USD'}, 'USD', 2)
        with self.assertRaises(DomainError):
            core.money({'amount': '1.00', 'currency': 'EUR'}, 'USD', 2)

    def test_exact_sov_aggregate_caps_and_unique_line_identity(self):
        another = deepcopy(self.line); another.update(line_id=str(uuid4()), item_code='SOV-002')
        result = core.sov([self.line, another], 'USD', 2, self.cap, self.units, self.policy)
        self.assertEqual(result['amount'], '200.02')
        with self.assertRaises(DomainError) as caught:
            core.sov([self.line, another], 'USD', 2, {'amount': '200.01', 'currency': 'USD'}, self.units, self.policy)
        self.assertEqual(caught.exception.code, 'contract_cap_exceeded')
        for field in ('line_id', 'item_code'):
            invalid = deepcopy(another); invalid[field] = self.line[field]
            with self.subTest(field=field), self.assertRaises(DomainError):
                core.sov([self.line, invalid], 'USD', 2, self.cap, self.units, self.policy)

    def test_quantity_must_bind_registered_unit_and_precision(self):
        for field, value in (('precision', 2), ('precision', True), ('unit_id', str(uuid4())), ('amount', '1.0000001'), ('amount', '0')):
            invalid = deepcopy(self.line); invalid['quantity'][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(DomainError):
                core.sov([invalid], 'USD', 2, self.cap, self.units, self.policy)

    def test_retainage_has_explicit_increasing_tiers_and_open_final_bound(self):
        self.assertEqual(core.retainage(self.policy, 'USD', 2), self.policy)
        for tiers in ([{'up_to': None, 'rate': '1.01'}], [{'up_to': {'amount': '10.00', 'currency': 'USD'}, 'rate': '0.05'}],
                      [{'up_to': None, 'rate': '0.05'}, {'up_to': None, 'rate': '0.01'}]):
            invalid = deepcopy(self.policy); invalid['tiers'] = tiers
            with self.subTest(tiers=tiers), self.assertRaises(DomainError):
                core.retainage(invalid, 'USD', 2)
        self.policy['basis'] = 'installed_work'
        with self.assertRaises(DomainError):
            core.sov([self.line], 'USD', 2, self.cap, self.units, self.policy)

    def test_prime_and_subcontract_native_party_direction_is_explicit(self):
        value = {'number': 'CON-001', 'kind': 'prime', 'direction': 'receivable', 'party_type': 'Customer', 'party': 'Native customer', 'currency': 'USD', 'original_value': self.cap}
        core.definition(value, 2)
        for changes in ({'kind':'subcontract'}, {'party_type':'Supplier'}, {'direction':'payable'}, {'kind': []}):
            invalid = {**value, **changes}
            with self.subTest(changes=changes), self.assertRaises(DomainError):
                core.definition(invalid, 2)
        core.definition({**value, 'kind':'consultant', 'direction':'payable', 'party_type':'Supplier'}, 2)

    def test_without_floor_reader_accepted_caps_cannot_decrease_or_disappear(self):
        for change in ('amount', 'quantity', 'deletion'):
            line = deepcopy(self.line)
            if change == 'amount': line['scheduled_amount']['amount'] = '100.00'
            if change == 'quantity': line['quantity']['amount'] = '10.000000'
            with self.subTest(change=change), self.assertRaises(DomainError):
                self.preserved([] if change == 'deletion' else [line])

    def test_accepted_line_basis_and_identity_cannot_be_rewritten(self):
        for key, value in (('item_code', 'OTHER'), ('cost_code', 'OTHER'), ('source_line_id', str(uuid4())), ('stored_material_eligible', False)):
            line = deepcopy(self.line); line[key] = value
            with self.subTest(key=key), self.assertRaises(DomainError):
                self.preserved([line])
        line = deepcopy(self.line); line['quantity']['unit_id'] = str(uuid4())
        with self.assertRaises(DomainError): self.preserved([line])
        line = deepcopy(self.line); line['quantity']['precision'] = 4
        with self.assertRaises(DomainError): self.preserved([line])

    def test_appends_increases_and_reorder_preserve_old_caps_and_line_ids(self):
        increased = deepcopy(self.line)
        increased['scheduled_amount']['amount'] = '200.00'; increased['quantity']['amount'] = '20.000000'
        append = deepcopy(self.line); append.update(line_id=str(uuid4()), item_code='SOV-NEW')
        self.assertTrue(self.preserved([append, increased]))
        self.assertEqual(self.line['scheduled_amount']['amount'], '100.01')

    def fixture_floor(self, **changes):
        return core.FloorSnapshot(contract_id=self.contract, contract_revision=self.revision, sov_revision=self.sov,
            provider='explicit_validator_fixture_not_production_provider', provider_version='fixture-v1', source_watermark='fixture-watermark',
            currency='USD', lines=({'line_id': self.line['line_id'], 'amount': '90.00', 'quantity': '9.000000', 'unit_id': self.unit},), **changes)

    def test_fixture_floor_binds_exact_contract_revision_watermark_and_all_lines(self):
        floor = self.fixture_floor()
        for invalid in (replace(floor, contract_revision=str(uuid4())), replace(floor, source_watermark=''), replace(floor, currency='EUR'), replace(floor, lines=()), {'amount':'0'}):
            with self.subTest(invalid=invalid), self.assertRaises(DomainError):
                self.preserved([self.line], floor=invalid)

    def test_fixture_floor_still_requires_correction_and_rejects_below_floor(self):
        line = deepcopy(self.line); line['scheduled_amount']['amount'] = '95.00'; line['quantity']['amount'] = '9.500000'
        with self.assertRaises(DomainError): self.preserved([line], floor=self.fixture_floor())
        floor = self.fixture_floor(correction_authority='explicit-fixture-review-reference-not-live-grant')
        self.assertTrue(self.preserved([line], floor=floor))
        line['scheduled_amount']['amount'] = '89.99'
        with self.assertRaises(DomainError) as caught: self.preserved([line], floor=floor)
        self.assertEqual(caught.exception.code, 'certified_floor_required')

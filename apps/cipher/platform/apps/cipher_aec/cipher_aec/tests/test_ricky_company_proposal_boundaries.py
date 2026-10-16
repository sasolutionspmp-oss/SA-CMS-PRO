"""Real storage/controller and discovery methods with explicit host collaborators."""
from contextlib import contextmanager, ExitStack
from copy import deepcopy
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

from cipher_aec.ricky.company_proposal_backend import CompanyProposalBackend
from cipher_aec.ricky.company_proposal_backend import ProposalAECReader
from cipher_aec.ricky.company_proposal_contracts import validate_resource_plan, validate_preparation
from cipher_aec.ricky.company_proposal_service import CompanyProposalService
from cipher_aec.ricky.company_backend import validate_resource_plan as read_plan
from cipher_aec.ricky.contracts import canonical, digest, RickyError
from cipher_aec.tests.test_estimating_core import identity
from cipher_aec.tests.test_ricky_company_service import NativeLinkCompanyStore, NativeLinkError
from cipher_aec.tests import test_ricky_company_proposals as fixtures
from cipher_aec.tests.test_ricky_company_proposals import ProposalBoundary, scope_request, estimate_request


class NativeProposalStore(NativeLinkCompanyStore):
    def __init__(self, events):
        super().__init__(events)
        self.savepoints = {}; self.commits = 0

    def checkpoint(self): self.commits += 1

    def savepoint(self, name): self.savepoints[name] = deepcopy((self.rows, self.native))

    def rollback_to(self, name): self.rows, self.native = deepcopy(self.savepoints[name])


class ProposalNativeLinkTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.ProposalServiceTests(); self.fixture.setUp(); self.addCleanup(self.fixture.doCleanups)
        f = self.fixture
        self.store = NativeProposalStore(f.boundary.events)
        self.store.originals = f.boundary.fixture.records
        self.service = CompanyProposalService(self.store, f.boundary, clock=lambda: f.now)

    def test_native_run_self_link_and_children_only_follow_actual_persisted_parents(self):
        f = self.fixture
        started = self.service.start_proposal('Explicit EST fixture', scope_request(f.boundary).binding(), identity('native-r14'))
        run = self.store.get('run', started['id'])
        f.boundary.receipts[run['start_receipt']] = run['id']
        writes = [row for row in f.boundary.events if type(row) is tuple]
        self.assertEqual([(row[0], row[1]) for row in writes[:3]], [('insert', 'run'), ('save', 'run'), ('insert', 'delegation')])
        def insert(doc):
            if doc.doctype == 'Cipher Proposed Change':
                self.assertEqual(self.store.count('invocation', {}), 1)
                self.assertEqual(self.store.find('step', {})[0]['status'], 'succeeded')
                self.assertIn(('Cipher Ricky Run', run['id']), self.store.native)
        self.store.after_insert = insert
        self.service.process(run['id'])
        self.assertEqual(self.store.get('run', run['id'])['status'], 'waiting-for-review')
        proposal = self.store.find('proposal', {})[0]
        self.assertEqual(proposal['preparation'], self.store.find('invocation', {})[0]['output'])
        changed = deepcopy(proposal); changed['version'] = 2
        with self.assertRaises(Exception): self.store.save('proposal', changed)

    def test_native_missing_run_link_is_never_bypassed(self):
        f = self.fixture
        request = scope_request(f.boundary)
        authority = f.boundary.bind('Explicit EST fixture', request, identity('absent-native-run'))
        child = self.service._new(authority, status='active', allowed_tools=[request.action], effect_classes=['proposal'])
        with self.assertRaises(NativeLinkError): self.store.insert('delegation', child)


class ProposalDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.boundary = ProposalBoundary()
        self.boundary.source_scope = CompanyProposalBackend.source_scope.__get__(self.boundary)
        self.request = scope_request(self.boundary)
        self.authority = self.boundary.bind('Explicit EST fixture', self.request, identity('discovery-r14'))
        self.events = []; self.generated = False
        self.stack = ExitStack(); self.addCleanup(self.stack.close)
        from cipher_aec import commercial, estimating, documents
        from cipher_aec.estimating import lockplan
        from cipher_aec.commercial import sources
        self.canonical_sources = sources
        self.native_refs = [{'doctype': kind, 'name': name} for kind, name in sorted([
            ('Customer', 'Fixture Customer'), ('Opportunity', 'Fixture Opportunity'),
            ('Quotation', 'Fixture Quotation'), ('Price List', 'Fixture Selling'), ('Item', 'Fixture Item')])]
        self.plan = {'unit_ids': [identity('sf'), identity('sy')], 'currencies': ['USD'], 'native_refs': self.native_refs,
            'generated_sources': []}
        self.plan['unit_ids'].sort()
        self.revision = {**self.boundary.fixture.proposal_revision_value, 'composition': {}, 'units': self.plan['unit_ids']}
        @contextmanager
        def prelocked(*args): yield
        provenance = ModuleType('cipher_aec.documents.provenance')
        provenance.MAX_NODES = 128; provenance.has_prelocked = lambda: False
        provenance.is_prelocked = lambda *args: False; provenance.prelocked = prelocked
        def source_plan(*args, **kwargs):
            self.events.append('discover-original-bytes')
            return {'unit_ids': [], 'currencies': [], 'native_refs': [], 'generated_sources':
                [{'document_id': 'generated', 'input_digest': 'a' * 64}] if self.generated else []}
        provenance.source_plan = source_plan
        units = ModuleType('cipher_aec.estimating.units')
        units.qualified = lambda name, **kwargs: self.events.append(('UOM', name))
        native = ModuleType('cipher_aec.commercial.native')
        native.require_native = lambda kind, name, *args, **kwargs: self.events.append((kind, name))
        estsources = ModuleType('cipher_aec.estimating.sources')
        estsources.pursuit_plan = lambda *args, **kwargs: {'native_refs': self.native_refs[:1]}
        estrepo = ModuleType('cipher_aec.estimating.repository')
        estrepo.read = lambda kind, name, **kwargs: deepcopy(self.boundary.fixture.records[kind, name])
        takeoffrepo = ModuleType('cipher_aec.takeoff.repository')
        takeoffrepo.read = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError('Unexpected takeoff source'))
        self.modules = {'frappe': SimpleNamespace(db=SimpleNamespace(get_value=lambda kind, name, field: name)),
            'cipher_aec.documents.provenance': provenance, 'cipher_aec.estimating.units': units,
            'cipher_aec.estimating.sources': estsources, 'cipher_aec.estimating.repository': estrepo,
            'cipher_aec.takeoff.repository': takeoffrepo, 'cipher_aec.commercial.native': native}
        self.stack.enter_context(patch.dict(sys.modules, self.modules))
        for package, name, module in [(commercial, 'native', native), (estimating, 'units', units), (estimating, 'sources', estsources),
                (estimating, 'repository', estrepo), (documents, 'provenance', provenance)]:
            self.stack.enter_context(patch.object(package, name, module, create=True))
        self.stack.enter_context(patch.object(sources, 'revision_record', side_effect=lambda *args, **kwargs: deepcopy(self.revision)))
        self.revision_plan = self.stack.enter_context(patch.object(sources, 'revision_plan', side_effect=lambda *args, **kwargs: deepcopy(self.plan)))

    def test_complete_commercial_union_before_actual_prepared_sorted_locks(self):
        with self.boundary.source_scope(self.authority, self.request, lock=True, execution=True) as plan:
            self.assertEqual(plan['native_refs'], self.native_refs)
        self.revision_plan.assert_called_once()
        first = next(index for index, row in enumerate(self.events) if type(row) is tuple)
        self.assertTrue(all(row == 'discover-original-bytes' for row in self.events[:first]))
        self.assertEqual(self.events[first:], [('UOM', name) for name in self.plan['unit_ids']] + [('Currency', 'USD')] + [(row['doctype'], row['name']) for row in self.native_refs])
        validate_resource_plan(self.plan)
        with self.assertRaises(RickyError): read_plan(self.plan)

    def test_generated_or_expanded_union_refuses_before_any_master_lock(self):
        self.generated = True
        with self.assertRaises(RickyError):
            with self.boundary.source_scope(self.authority, self.request, lock=True, execution=True): pass
        self.assertFalse(any(type(row) is tuple for row in self.events))
        self.generated = False; self.events.clear()
        original = deepcopy(self.plan); original['native_refs'] = []
        with self.assertRaises(RickyError):
            with self.boundary.source_scope(self.authority, self.request, lock=True, execution=True, expected_plan=original): pass
        self.assertFalse(any(type(row) is tuple for row in self.events))

    def test_quotation_price_list_are_only_two_additional_native_kinds(self):
        for kind in ('Sales Invoice', 'User', 'Project', 'DocType'):
            bad = deepcopy(self.plan); bad['native_refs'] = [{'doctype': kind, 'name': 'Foreign'}]
            with self.assertRaises(RickyError): validate_resource_plan(bad)


class ProposalReferenceTamperingTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.ProposalServiceTests(); self.fixture.setUp(); self.addCleanup(self.fixture.doCleanups)

    def test_every_public_source_field_is_bound_to_real_authorized_citation(self):
        f = self.fixture
        run, _, output, _ = f.prepare()
        for key, replacement in [('citation_id', 'f' * 64), ('document_id', identity('wrong-document')), ('revision_id', 'wrong-revision'),
                ('page', 2), ('excerpt_sha256', 'e' * 64), ('source_sha256', 'e' * 64), ('canonical_digest', 'e' * 64)]:
            with self.subTest(field=key):
                bad = deepcopy(output); bad['verified_source_references'][0][key] = replacement
                bad['draft_digest'] = digest({name: value for name, value in bad.items() if name != 'draft_digest'})
                with self.assertRaises(RickyError): validate_preparation(run, bad, originals=f.boundary.originals())

    def test_old_read_and_project_codecs_and_schema_bytes_remain_separate(self):
        from cipher_aec.ricky.company_contracts import DeterministicReadRequest, decode_run_authority
        from cipher_aec.ricky.contracts import Authority
        authority = Authority('u', 'p', 'c', 'P', 'v', 'a')
        self.assertEqual(canonical(authority.binding()), '{"authority_version":"a","company":"c","person":"p","project":"P","project_revision":"v","session_reference":null,"user":"u"}')
        original = {'authority': authority.binding(), 'user': 'u', 'person': 'p', 'company': 'c', 'project': 'P'}
        self.assertEqual(decode_run_authority(original), authority)
        read = DeterministicReadRequest(identity('pursuit'), 'aec.pursuit.lookup', '{}')
        self.assertEqual(read.binding()['schema'], 'cipher.ricky.company.read-request.v1')
        with self.assertRaises(RickyError): DeterministicReadRequest.from_value(scope_request(self.fixture.boundary).binding())


class CanonicalHistoricalClosureTests(unittest.TestCase):
    def setUp(self):
        self.fixture = f = fixtures.ProposalServiceTests(); f.setUp(); self.addCleanup(f.doCleanups)
        self.run, _ = f.start(estimate_request(f.boundary)); f.service.process(self.run['id'])
        self.proposal_id = f.store.get('run', self.run['id'])['proposal_ids'][0]
        self.calls = []
        self.stack = ExitStack(); self.addCleanup(self.stack.close)
        from cipher_aec import estimating, commercial
        service = ModuleType('cipher_aec.estimating.service')
        def read(kind, name, *args, **kwargs):
            self.calls.append((kind, name))
            return f.boundary.fixture.record(None, kind, name, f.boundary.actor)
        service._scoped = read; service._scoped_original = read
        context = ModuleType('cipher_aec.governance.context')
        context.require_company = lambda company, ability, **kwargs: f.boundary.require_ability(ability)
        native = ModuleType('cipher_aec.commercial.native')
        def require_native(*args, **kwargs):
            if not f.boundary.fixture.native_allowed: raise RickyError('not_found', 'Explicit native denial')
            return SimpleNamespace(company=self.run['company'])
        native.require_native = require_native; native.party = require_native
        commercial_service = ModuleType('cipher_aec.commercial.service')
        commercial_service._read = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError('No commercial/current-head expansion'))
        self.stack.enter_context(patch.dict(sys.modules, {'cipher_aec.estimating.service': service,
            'cipher_aec.governance.context': context, 'cipher_aec.commercial.native': native, 'cipher_aec.commercial.service': commercial_service}))
        for package, name, value in ((estimating, 'service', service), (commercial, 'native', native), (commercial, 'service', commercial_service)):
            self.stack.enter_context(patch.object(package, name, value, create=True))
        class Reader(fixtures.ProposalFixtureReader):
            verify_original = ProposalAECReader.verify_original
            record = ProposalAECReader.record
            dependency = ProposalAECReader.dependency
        f.boundary.reader = lambda authority, request, **kwargs: Reader(f.boundary, authority, request, **kwargs)

    def test_actual_historical_verifier_reconstructs_line_revision_snapshot_closure(self):
        f = self.fixture
        owner = f.boundary.fixture.records['estimate', f.boundary.fixture.records['revision', f.boundary.fixture.revision_id]['estimate']]
        owner['current_revision'] = identity('unreadable-successor')
        f.boundary.fixture.unit_enabled = False; f.boundary.session = False
        f.service.get_proposal(self.run['company'], self.proposal_id)
        self.assertNotIn(('revision', owner['current_revision']), self.calls)
        current = f.store.rows['run', self.run['id']]
        current['original_manifest']['records'] = [row for row in current['original_manifest']['records'] if row['kind'] != 'snapshot']
        current['original_manifest_digest'] = digest(current['original_manifest'])
        with self.assertRaises(RickyError) as error: f.service.get_proposal(self.run['company'], self.proposal_id)
        self.assertEqual(error.exception.code, 'source_integrity')

    def test_actual_historical_verifier_honors_current_source_and_native_permissions(self):
        f = self.fixture
        for field in ('source_allowed', 'native_allowed'):
            setattr(f.boundary.fixture, field, False)
            with self.assertRaises((RickyError, fixtures.DomainError)):
                f.service.get_proposal(self.run['company'], self.proposal_id)
            setattr(f.boundary.fixture, field, True)

"""Exact mapping and application integrity; host tests are not native proof."""
from copy import deepcopy
from fractions import Fraction
import unittest
from cipher_aec.api.errors import DomainError
from cipher_aec.ricky.company_draft_save_contracts import decimal_amount, scope_composition, application_id
from cipher_aec.tests.test_estimating_core import identity

class MappingTests(unittest.TestCase):
    def test_exact_decimal_only_without_rounding(self):
        self.assertEqual(decimal_amount('3','8',3),'0.375')
        for n,d,p in [('1','3',12),('1','8',2),('-1','2',6),('1','0',6)]:
            with self.subTest((n,d,p)), self.assertRaises(DomainError):decimal_amount(n,d,p)

    def test_scope_is_visibly_unverified_and_financial_fields_preserved(self):
        from cipher_aec.tests.test_commercial import sample
        from cipher_aec.commercial.contracts import composition
        original=composition(sample()); before=deepcopy(original)
        source={'revision_id':'REV-'+'a'*32,'page':1,'excerpt_sha256':'b'*64,'source_sha256':'c'*64}
        prepared={'proposed_fields':{'sections':[{'heading':'Walls','text':'Exact prepared body.','citation_ids':['c']}]},
            'unverified_claims':['Check access.'],'verified_source_references':[source]}
        result=scope_composition(identity('suggestion'),original,prepared)
        self.assertEqual(original,before)
        self.assertEqual(result['sections'][:len(original['sections'])],original['sections'])
        self.assertEqual(result['sections'][-2]['title'],'Unverified author suggestion: Walls')
        self.assertEqual(result['sections'][-2]['text'],'Exact prepared body.')
        self.assertEqual(result['sections'][-1]['kind'],'assumption')
        for key in ('price_lines','terms','currency','price_list','valid_till'):self.assertEqual(result[key],original[key])
        prepared['proposed_fields']['sections'][0]['heading']='x'*140
        with self.assertRaises(DomainError):scope_composition(identity('suggestion'),original,prepared)

    def test_application_slot_is_suggestion_specific(self):
        self.assertEqual(application_id(identity('s')),application_id(identity('s')))
        self.assertNotEqual(application_id(identity('s')),application_id(identity('other')))


def ready_scope(test, *, recover=False):
    from cipher_aec.tests import test_ricky_company_proposals as fixtures
    from cipher_aec.tests.test_commercial import sample
    from cipher_aec.commercial.contracts import composition
    from cipher_aec.ricky.company_draft_save import DraftSaveContext
    from cipher_aec.ricky.company_draft_save_contracts import derive,binding
    f=fixtures.ProposalServiceTests();f.setUp();test.addCleanup(f.doCleanups)
    from dataclasses import replace
    from hashlib import sha256
    bind=f.boundary.bind
    f.boundary.bind=lambda *args:replace(bind(*args),session_reference=sha256(b'fixture-original-sid').hexdigest())
    # Commercial save requires the actual canonical document revision locator.
    f.boundary.fixture.citation_value['revision_id']='REV-'+'a'*32
    revision=f.boundary.fixture.proposal_revision_value
    revision.update(composition=composition(sample()),revision_number=1,native_fingerprint='f'*64)
    if recover:
        from datetime import timedelta
        run,_,_,_=f.prepare();f.now+=timedelta(seconds=181)
    else:run,_=f.start()
    f.service.process(run['id'])
    run=f.store.get('run',run['id']);proposal=f.store.get('proposal',run['proposal_ids'][0])
    payload=derive(proposal,run,f.boundary.originals())
    context=DraftSaveContext(run['company'],proposal['id'],binding(proposal,payload),service=f.service,clock=lambda:f.now).prepare()
    return f,context


class DerivedMappingTests(unittest.TestCase):
    def test_full_canonical_preparation_rejects_rehashed_source_document_tampering(self):
        from cipher_aec.ricky.company_draft_save_contracts import derive
        from cipher_aec.ricky.contracts import RickyError,digest
        f,ctx=ready_scope(self)
        before=deepcopy(ctx.proposal['preparation'])
        original=f.boundary.originals()
        ref=ctx.proposal['preparation']['verified_source_references'][0]
        ref['document_id']=identity('foreign-document')
        with self.assertRaises(RickyError):derive(ctx.proposal,ctx.run,original)
        ctx.proposal['preparation']=before
        self.assertEqual(derive(ctx.proposal,ctx.run,original),ctx.payload)

    def test_estimate_keeps_original_inputs_and_binds_exact_line_identity(self):
        from cipher_aec.tests import test_ricky_company_proposals as fixtures
        from cipher_aec.ricky.company_draft_save_contracts import derive
        f=fixtures.ProposalServiceTests();f.setUp();self.addCleanup(f.doCleanups)
        # Supply the actual immutable conversion records required by the base manifest.
        snap=f.boundary.fixture.records['snapshot',f.boundary.fixture.snapshot_id]
        for definition in snap['inputs']['unit_manifest']['unit_conversions']:
            f.boundary.fixture.records['conversion',definition['id']]={'id':definition['id'],'scope_type':'Company','company':'Explicit EST fixture',
                'project':None,'definition':definition,'source_citations':[]}
        run,_=f.start(fixtures.estimate_request(f.boundary));f.service.process(run['id'])
        run=f.store.get('run',run['id']);proposal=f.store.get('proposal',run['proposal_ids'][0]);original=f.boundary.originals()
        payload=derive(proposal,run,original)
        self.assertEqual(payload['lines'],snap['inputs']['lines'])
        self.assertEqual(payload['adjustments'],snap['inputs']['adjustments'])
        self.assertTrue(payload['basis_description'].startswith(snap['inputs']['basis_description']))
        line=original['estimate','line',f.boundary.fixture.line_id];line['line_id']=identity('other-line')
        with self.assertRaises(Exception):derive(proposal,run,original)

    def test_exact_review_digest_and_version_are_mandatory(self):
        from cipher_aec.ricky.company_draft_save_contracts import check_binding
        _,ctx=ready_scope(self)
        for key,value in [('expected_version',True),('mapping_version','2'),('expected_payload_digest','0'*64),('proposal_id',identity('foreign'))]:
            reviewed={**ctx.reviewed,key:value}
            with self.subTest(key=key),self.assertRaises(DomainError):check_binding(reviewed,ctx.proposal,ctx.payload)

    def test_full_original_basis_citation_projects_to_closed_authored_reference(self):
        from cipher_aec.ricky.company_draft_save_contracts import citation_union
        from cipher_aec.tests.test_estimating_company import company_fixture
        from jsonschema import Draft202012Validator
        from pathlib import Path
        import json
        inputs=company_fixture();full=deepcopy(next(iter(inputs['rates'].values()))['source_citations'][0])
        full.update(document_id=identity('document'),id='d'*64,excerpt='Actual canonical citation text')
        result=citation_union([full],[full])
        self.assertEqual(set(result[0]),{'revision_id','page','excerpt_sha256','source_sha256'})
        defs=json.loads((Path(__file__).parents[1]/'estimating/schemas/api-v1.schema.json').read_text())['$defs']
        Draft202012Validator({'$defs':defs,'$ref':'#/$defs/EstCitationReference'}).validate(result[0])

    def test_manifest_pinned_conversion_is_authorized_without_a_stage_b_record_entry(self):
        from cipher_aec.ricky.company_draft_save import _conversion_originals
        from cipher_aec.tests import test_ricky_company_proposals as fixtures
        from cipher_aec.ricky.company_draft_save_contracts import derive
        f=fixtures.ProposalServiceTests();f.setUp();self.addCleanup(f.doCleanups)
        run,_=f.start(fixtures.estimate_request(f.boundary));f.service.process(run['id'])
        run=f.store.get('run',run['id']);proposal=f.store.get('proposal',run['proposal_ids'][0]);before=deepcopy(run)
        snapshot=f.boundary.fixture.records['snapshot',f.boundary.fixture.snapshot_id]
        for definition in snapshot['inputs']['unit_manifest']['unit_conversions']:
            f.boundary.fixture.records['conversion',definition['id']]={'id':definition['id'],'scope_type':'Company','company':run['company'],
                'project':None,'definition':deepcopy(definition),'source_citations':[]}
        originals={k:v for k,v in f.boundary.originals().items() if k[1]!='conversion'}
        enriched=_conversion_originals(f.service,run,originals)
        self.assertEqual(run,before)
        self.assertTrue(derive(proposal,run,enriched)['conversion_ids'])
        self.assertFalse(any(k[1]=='conversion' for k in originals))
        row=f.boundary.fixture.records['conversion',snapshot['inputs']['unit_manifest']['unit_conversions'][0]['id']]
        row['definition']={**row['definition'],'numerator':'999'}
        with self.assertRaises(DomainError):_conversion_originals(f.service,run,originals)

    def test_unsavable_authored_notes_or_claim_controls_refuse_without_flattening(self):
        from dataclasses import replace
        import json
        from cipher_aec.tests import test_ricky_company_proposals as fixtures
        from cipher_aec.ricky.contracts import canonical
        from cipher_aec.ricky.company_draft_save_contracts import derive
        for field,value in [('notes','Preserved first line\nSecond line'),('unverified_claims',['Preserved claim\nSecond line'])]:
            with self.subTest(field=field):
                f=fixtures.ProposalServiceTests();f.setUp();self.addCleanup(f.doCleanups)
                snapshot=f.boundary.fixture.records['snapshot',f.boundary.fixture.snapshot_id]
                for definition in snapshot['inputs']['unit_manifest']['unit_conversions']:
                    f.boundary.fixture.records['conversion',definition['id']]={'id':definition['id'],'scope_type':'Company','company':'Explicit EST fixture',
                        'project':None,'definition':definition,'source_citations':[]}
                request=fixtures.estimate_request(f.boundary);arguments=json.loads(request.arguments_json);arguments[field]=value
                request=replace(request,arguments_json=canonical(arguments))
                run,_=f.start(request);f.service.process(run['id']);run=f.store.get('run',run['id']);proposal=f.store.get('proposal',run['proposal_ids'][0])
                before=canonical(proposal)
                with self.assertRaises(DomainError):derive(proposal,run,f.boundary.originals())
                self.assertEqual(canonical(proposal),before)

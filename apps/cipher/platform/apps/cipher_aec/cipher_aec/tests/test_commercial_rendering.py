"""Pinned local PDF renderer qualification; no issued artifact or source fixture claim."""
from io import BytesIO
import unittest
from uuid import uuid4

from cipher_aec.api.errors import DomainError
from cipher_aec.commercial import rendering
from cipher_aec.commercial.contracts import composition,pricing
from cipher_aec.documents.extraction import digest,extract_source
from cipher_aec.tests.test_commercial import sample


class ProposalRendering(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:rendering.policy()
        except DomainError as error:
            if error.code=='renderer_unqualified':raise unittest.SkipTest('Pinned renderer qualification runs in the approved Frappe image')
            raise

    def snapshot(self):
        authored=sample();authored['sections'][0]['text']='Résumé — café. Concrete strength 4500 psi. Literal <img src="https://unreachable.invalid/private">.'
        authored=composition(authored)
        return {'id':str(uuid4()),'company':'Explicit synthetic renderer fixture','composition':authored,'pricing':pricing(authored,2),'units':{row['unit_id']:{'fields':{'symbol':'ea'}} for row in authored['price_lines']}}

    def test_fresh_subprocesses_identical_pdf_and_safe_canonical_extraction(self):
        snapshot=self.snapshot()
        first,provenance=rendering.render(snapshot,cover='Reviewable authored cover')
        second,again=rendering.render(snapshot,cover='Reviewable authored cover')
        self.assertEqual(first,second)
        self.assertEqual(provenance,again)
        self.assertEqual(provenance['output_sha256'],digest(first))
        self.assertIn('fonts',provenance)
        extraction=extract_source(first,'application/pdf')
        self.assertEqual(extraction.status,'ready')
        text='\n'.join(extraction.pages)
        for value in ('4500','20.50','Résumé','unreachable.invalid'):
            self.assertIn(value,text)
        self.assertNotIn(b'/JavaScript',first)

    def test_unsupported_glyph_fails_before_any_artifact_write(self):
        snapshot=self.snapshot();snapshot['composition']['terms']='Unsupported Gothic letter \U00010348'
        with self.assertRaises(DomainError) as error:rendering.render(snapshot)
        self.assertEqual(error.exception.code,'unsupported_output_text')

    def test_material_input_changes_change_output_hash(self):
        snapshot=self.snapshot()
        first,before=rendering.render(snapshot)
        snapshot['composition']['terms']='Changed authored commercial terms'
        second,after=rendering.render(snapshot)
        self.assertNotEqual(before['output_sha256'],after['output_sha256'])
        self.assertNotEqual(before['proposal_revision_digest'],after['proposal_revision_digest'])

    def test_recipients_are_reviewable_and_change_exact_output_hash(self):
        snapshot=self.snapshot()
        to=[{'name':'Synthetic reviewer','email':'reviewer@example.test','organization':'Explicit fixture'}]
        first,before=rendering.render(snapshot,cover='Exact cover',recipients=to)
        self.assertIn('reviewer@example.test','\n'.join(extract_source(first,'application/pdf').pages))
        changed=[{**to[0],'email':'successor@example.test'}]
        second,after=rendering.render(snapshot,cover='Exact cover',recipients=changed)
        self.assertNotEqual(before['output_sha256'],after['output_sha256'])
        self.assertNotEqual(before['recipients_digest'],after['recipients_digest'])

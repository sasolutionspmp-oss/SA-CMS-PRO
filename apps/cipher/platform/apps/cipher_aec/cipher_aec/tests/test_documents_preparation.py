"""Exact rendered capability is required for generated parent/revision writes."""
import copy
import json
import unittest
from cipher_aec.api.contracts import digest
from cipher_aec.api.errors import DomainError
from cipher_aec.documents import preparation as p
from cipher_aec.tests.test_documents_provenance import document


class ExactPreparation(unittest.TestCase):
    def setUp(self):
        self.parent={**document('DOC-preparation-probe'),'revision_number':0,'current_revision':None}
        self.generation={'output_sha256':'d'*64,'output_byte_length':100,'input_digest':self.parent['producer_input_digest'],'fingerprint':'c'*64}
        self.args=dict(company=self.parent['company'],proposal_revision=self.parent['producer_reference'],input_digest=self.parent['producer_input_digest'],renderer_fingerprint='c'*64,source_sha256='d'*64,byte_length=100,generation_digest=digest(self.generation))

    def assert_refused(self, callback):
        with self.assertRaises(DomainError) as error:callback()
        self.assertEqual(error.exception.code,'preparation_required')

    def test_exact_parent_head_bytes_and_generation_admitted_only_inside_context(self):
        self.assert_refused(lambda:p.require_preparation(self.parent))
        with p._writing_output(**self.args):
            p._bind_parent(self.parent);p.require_preparation(self.parent)
            p._bind_revision('REV-probe')
            p.require_preparation({**self.parent,'revision_number':1,'current_revision':'REV-probe'})
            row={**self.parent,'name':'REV-probe','document':self.parent['name'],'sha256':'d'*64,'byte_length':100,'generation_json':json.dumps(self.generation)}
            p.require_preparation(row,revision=True)
            for changes in ({'sha256':'e'*64},{'byte_length':101},{'name':'REV-forged'},{'document':'DOC-other'},{'generation_json':'{}'}):
                self.assert_refused(lambda:p.require_preparation({**row,**changes},revision=True))
        self.assert_refused(lambda:p.require_preparation(self.parent))

    def test_wrong_input_parent_double_binding_and_exception_reset(self):
        with p._writing_output(**{**self.args,'renderer_fingerprint':'e'*64}):
            self.assert_refused(lambda:p._bind_parent(self.parent))
        with p._writing_output(**self.args):
            p._bind_parent(self.parent)
            self.assert_refused(lambda:p._bind_parent(self.parent))
            self.assert_refused(lambda:p.require_preparation({**self.parent,'name':'DOC-other'}))
            def nested():
                with p._writing_output(**self.args):pass
            self.assert_refused(nested)
        with self.assertRaises(RuntimeError):
            with p._writing_output(**self.args):
                p._bind_parent(self.parent)
                raise RuntimeError('simulated failed artifact write')
        self.assert_refused(lambda:p.require_preparation(self.parent))

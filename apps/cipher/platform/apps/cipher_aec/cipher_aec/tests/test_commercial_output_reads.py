"""Discarded read-only lock plans must not replace source or byte checks."""
from contextlib import ExitStack
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from cipher_aec.api.contracts import digest
from cipher_aec.api.errors import DomainError
from cipher_aec.commercial import outputs, service
from cipher_aec.documents import provenance, service as documents
from cipher_aec.tests.test_documents_provenance import ACTOR, document


class CanonicalOutputReads(unittest.TestCase):
    def setUp(self):
        self.parent = document("root")
        self.binding = provenance.binding(self.parent)
        self.revision = {"id":"revision-a","proposal":"proposal-a"}
        self.source = {"revision_id":"REV-original","source_sha256":"d"*64,"byte_length":7,"page_count":1}
        self.plan = {"unit_ids":["unit-a"],"currencies":["USD"],"native_refs":[{"doctype":"Customer","name":"customer-a"}],
            "generated_sources":[{"document_id":"nested","input_digest":"e"*64}]}
        self.generated = {"input_digest":self.parent["producer_input_digest"],"output_sha256":self.source["source_sha256"],
            "output_byte_length":7,"proposal_revision_digest":digest(self.revision),"fingerprint":self.binding["renderer"]["fingerprint"],
            "cover_digest":digest(self.binding["cover"]),"recipients_digest":digest(self.binding["recipients"])}
        self.output_parent = SimpleNamespace(name="root",current_revision="REV-original",producer_input_digest=self.parent["producer_input_digest"],as_dict=lambda:self.parent)

    def test_nonlocking_issued_bytes_never_discover_mutation_locks_and_keep_failures(self):
        issue={"prepared_output":self.source}
        with (patch.object(service,"_actor",return_value=ACTOR),patch.object(service,"_read",return_value=(None,issue)) as original,
             patch.object(provenance,"source_plan",side_effect=AssertionError("Nonlocking read discovered unused mutation locks")),
             patch.object(documents,"company_source_reference",return_value=self.source) as canonical):
            result=outputs.issue_source_reference("Company A","issue-a")
            self.assertEqual(result,{"issue":issue,"source":self.source})
            original.assert_called_once_with("issue","issue-a","Company A",ACTOR,lock=False)
            canonical.assert_called_once_with("Company A","REV-original",1,ACTOR,lock=False)
            canonical.side_effect=DomainError("artifact_unavailable","Original bytes unavailable",409)
            with self.assertRaises(DomainError):outputs.issue_source_reference("Company A","issue-a")
            canonical.side_effect=None;canonical.return_value={**self.source,"source_sha256":"0"*64}
            with self.assertRaises(DomainError):outputs.issue_source_reference("Company A","issue-a")

    def test_locking_issued_bytes_keep_complete_discovery_and_admission(self):
        def canonical(company,revision,page,actor,lock=False):
            self.assertTrue(lock)
            self.assertTrue(provenance.is_prelocked(self.plan,ACTOR,"Company A"))
            return self.source
        with (patch.object(service,"_actor",return_value=ACTOR),patch.object(service,"_read",return_value=(None,{"prepared_output":self.source})),
             patch.object(provenance,"source_plan",return_value=self.plan) as discovery,
             patch.object(documents,"company_source_reference",side_effect=canonical)):
            outputs.issue_source_reference("Company A","issue-a",lock=True)
            discovery.assert_called_once_with("Company A","REV-original",ACTOR,lock=True)
        self.assertFalse(provenance.has_prelocked())

    def prepared_stack(self,locking,source_reader):
        stack=ExitStack()
        stack.enter_context(patch.object(service,"_actor",return_value=ACTOR))
        stack.enter_context(patch.object(service,"_read",return_value=(None,self.revision)))
        stack.enter_context(patch.object(outputs,"require_company"))
        stack.enter_context(patch.object(outputs,"_parent",return_value=self.output_parent))
        repo=SimpleNamespace(revision=lambda *a,**k:{"generation_json":json.dumps(self.generated)})
        stack.enter_context(patch.object(documents,"_service",return_value=SimpleNamespace(repo=repo,source_reference=source_reader)))
        if locking:
            discovery=stack.enter_context(patch.object(outputs.sources,"revision_plan",return_value=self.plan))
        else:
            discovery=stack.enter_context(patch.object(outputs.sources,"revision_plan",side_effect=AssertionError("Nonlocking output discovered unused mutation locks")))
        return stack,discovery

    def test_nonlocking_prepared_output_skips_unused_plan_but_checks_canonical_provenance(self):
        reader=SimpleNamespace(error=None)
        def canonical(*args,**kwargs):
            if reader.error:raise reader.error
            return self.source
        stack,discovery=self.prepared_stack(False,canonical)
        with stack:
            result=outputs.read_output("Company A","revision-a")
            self.assertEqual(result["source_sha256"],self.source["source_sha256"])
            discovery.assert_not_called()
            reader.error=DomainError("not_found","Source rights revoked",404)
            with self.assertRaises(DomainError):outputs.read_output("Company A","revision-a")
            reader.error=None;self.generated["output_sha256"]="0"*64
            with self.assertRaises(DomainError):outputs.read_output("Company A","revision-a")

    def test_locking_prepared_output_admits_its_own_node_and_all_dependency_resources(self):
        expected=outputs.sources.merge(self.plan,{"generated_sources":[{"document_id":"root","input_digest":self.parent["producer_input_digest"]}]})
        def canonical(*args,**kwargs):
            self.assertTrue(kwargs["lock"])
            self.assertTrue(provenance.is_prelocked(expected,ACTOR,"Company A"))
            return self.source
        stack,discovery=self.prepared_stack(True,canonical)
        with stack:
            outputs.read_output("Company A","revision-a",lock=True)
            discovery.assert_called_once_with("Company A","revision-a",ACTOR,lock=True)
        self.assertFalse(provenance.has_prelocked())


    def test_fresh_output_identity_checks_scope_bindings_scan_and_generation(self):
        from cipher_aec.documents.core import DocumentService
        parent=self.output_parent
        for key in ("company","scope_type","project"):setattr(parent,key,self.parent[key])
        parent.revision_number=1;parent.get=lambda key:self.parent.get(key)
        stored={**self.parent,"name":"REV-original","document":"root","revision_number":1,"mime_type":"application/pdf",
            "sha256":self.source["source_sha256"],"byte_length":7,"page_count":1,
            "scan_status":"not_scanned","retrieval_status":"available","generation_json":json.dumps(self.generated)}
        policy=DocumentService(None,None,lambda *a:None,allow_unscanned=True,scope_type="Company")
        bound=SimpleNamespace(repo=SimpleNamespace(revision=lambda *a,**k:dict(stored)),_available=policy._available)
        with patch.object(outputs,"require_company"),patch.object(outputs,"_parent",return_value=parent),patch.object(documents,"_service",return_value=bound):
            identity=outputs._output_identity("Company A",self.revision,ACTOR)
            self.assertEqual(identity["source_sha256"],self.source["source_sha256"])
            for field,value in (("document","other"),("company","other"),("scope_type","Project"),("producer_input_digest","0"*64),("scan_status","infected"),("generation_json",json.dumps({**self.generated,"output_sha256":"0"*64}))):
                original=stored[field];stored[field]=value
                with self.subTest(field=field),self.assertRaises(DomainError):outputs._output_identity("Company A",self.revision,ACTOR)
                stored[field]=original

    def test_issue_proof_keeps_fresh_linkage_and_requested_pdf_checks_outside(self):
        value={"id":"0d1af988-a235-468d-a87e-5b0634adbfd0","company":"Company A","proposal_revision":"revision-a",
            "proposal_revision_digest":digest(self.revision),"prepared_output":self.source}
        doc=SimpleNamespace(data_json=json.dumps(value),record_digest=digest(value))
        fake=SimpleNamespace(db=SimpleNamespace(get_value=lambda *a,**k:"Company A"),get_doc=lambda *a,**k:doc)
        original=service._read;authorized=[]
        def read(kind,*args,**kwargs):
            if kind=="issue":return original(kind,*args,**kwargs)
            self.assertEqual(kind,"revision");authorized.append(kind);return None,self.revision
        with (patch.object(service,"frappe",fake),patch.object(service,"_read",side_effect=read),
              patch.object(service,"_actor",return_value=ACTOR),patch.object(service.sources,"revision_record",return_value=self.revision),
              patch.object(outputs,"_output_identity",return_value=self.source) as identity,
              patch.object(outputs,"read_output",return_value=self.source),patch.object(documents,"company_source_reference",return_value=self.source) as canonical):
            with provenance.read_graph(ACTOR,"Company A"):
                service._read("issue","0d1af988-a235-468d-a87e-5b0634adbfd0","Company A",ACTOR)
                service._read("issue","0d1af988-a235-468d-a87e-5b0634adbfd0","Company A",ACTOR)
                self.assertEqual(len(authorized),1)
                self.assertEqual(identity.call_count,2)
                outputs.issue_source_reference("Company A","0d1af988-a235-468d-a87e-5b0634adbfd0",ACTOR)
                canonical.side_effect=DomainError("artifact_unavailable","Missing original bytes",409)
                with self.assertRaises(DomainError):outputs.issue_source_reference("Company A","0d1af988-a235-468d-a87e-5b0634adbfd0",ACTOR)
                self.assertEqual(canonical.call_count,2)
                self.assertEqual(len(authorized),1)
                identity.return_value={**self.source,"source_sha256":"0"*64}
                with self.assertRaises(DomainError):service._read("issue","0d1af988-a235-468d-a87e-5b0634adbfd0","Company A",ACTOR)
            # A later call reauthorizes; no graph takes the old full branch.
            identity.return_value=self.source
            service._read("issue","0d1af988-a235-468d-a87e-5b0634adbfd0","Company A",ACTOR)
            self.assertEqual(len(authorized),2)

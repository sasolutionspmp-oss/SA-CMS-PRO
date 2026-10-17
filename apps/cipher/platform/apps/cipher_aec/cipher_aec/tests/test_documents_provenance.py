"""Generated-source ancestry and current authorization admission, without Frappe."""
import copy
import json
import sys
import types
import unittest
from unittest.mock import patch
from cipher_aec.api.contracts import digest, canonical_json
from cipher_aec.api.errors import DomainError
from cipher_aec.documents import provenance as p

ACTOR = types.SimpleNamespace(user="author@example.test", person_id="person-a")


def document(name):
    value = {"schema":"cipher.proposal.output.input.v1","company":"Company A","proposal_id":"proposal-a",
        "proposal_revision_id":"revision-a","proposal_revision_digest":"a"*64,"native_fingerprint":"b"*64,
        "accepted_estimate":{},"source_citations":[],"recipients":[{"name":"Recipient","email":"recipient@example.test","organization":"Synthetic"}],
        "cover":"","renderer":{"fingerprint":"c"*64}}
    return {"name":name,"scope_type":"Company","company":"Company A","project":None,
        "producer_kind":p.PRODUCER,"producer_reference":"revision-a","producer_input_digest":digest(value),"producer_binding_json":canonical_json(value)}


class ProvenanceAuthority(unittest.TestCase):
    def setUp(self):
        # Explicit no-policy fixture: exercise producer ancestry separately from
        # DOC03's real current-policy/evidence admission host cases.
        self.enterContext(patch.dict(sys.modules, {'cipher_aec.document_control.rights':types.SimpleNamespace(authorize=lambda *a,**k:None)}))

    def adapter(self, authorize):
        return patch.dict(sys.modules, {"cipher_aec.commercial.output_sources":types.SimpleNamespace(authorize_binding=authorize,binding_plan=lambda binding,actor,lock=False:{})})

    def test_repeated_independent_source_branch_is_allowed_and_memoized(self):
        root, child = document("root"), document("child")
        calls=[]
        def authorize(binding,actor,lock=False):
            calls.append(binding["cover"])
            if binding["cover"] == "root":
                p.authorize(child,actor)
                p.authorize(child,actor)
        binding=json.loads(root["producer_binding_json"]);binding["cover"]="root"
        root.update(producer_input_digest=digest(binding),producer_binding_json=canonical_json(binding))
        with self.adapter(authorize): p.authorize(root,ACTOR)
        self.assertEqual(calls,["root",""])

    def test_active_ancestry_cycle_and_depth_limit_fail_closed(self):
        root=document("root")
        with self.adapter(lambda binding,actor,lock=False:p.authorize(root,actor)):
            with self.assertRaises(DomainError) as error:p.authorize(root,ACTOR)
            self.assertEqual(error.exception.code,"cyclic_source")
        counter=[0]
        def recurse(binding,actor,lock=False):
            counter[0]+=1;p.authorize(document(str(counter[0])),actor)
        with self.adapter(recurse):
            with self.assertRaises(DomainError) as error:p.authorize(root,ACTOR)
            self.assertEqual(error.exception.code,"source_limit")

    def test_locking_requires_explicit_complete_plan_admission(self):
        row=document("root");calls=[]
        with self.adapter(lambda binding,actor,lock=False:calls.append(lock)):
            with self.assertRaises(DomainError) as error:p.authorize(row,ACTOR,lock=True)
            self.assertEqual(error.exception.code,"source_prelock_required")
            wrong={"generated_sources":[{"document_id":"other","input_digest":row["producer_input_digest"]}]}
            with p.prelocked(wrong,ACTOR,"Company A"):
                with self.assertRaises(DomainError):p.authorize(row,ACTOR,lock=True)
            plan={"generated_sources":[{"document_id":"root","input_digest":row["producer_input_digest"]}]}
            with p.prelocked(plan,ACTOR,"Company A"):p.authorize(row,ACTOR,lock=True)
        self.assertEqual(calls,[True])

    def test_memo_never_survives_request_or_different_actor(self):
        row=document("root");allowed=[True]
        def authorize(binding,actor,lock=False):
            if not allowed[0]:raise DomainError("not_found","Unavailable",404)
        with self.adapter(authorize):
            p.authorize(row,ACTOR)
            allowed[0]=False
            with self.assertRaises(DomainError):p.authorize(row,ACTOR)

    def test_unknown_malformed_and_mismatched_binding_rejected(self):
        for changes in ({"producer_kind":"dynamic.import"},{"scope_type":"Project","project":"P"},{"producer_input_digest":"0"*64},{"producer_binding_json":"{}"},{"producer_kind":None}):
            with self.assertRaises(DomainError):p.binding({**document("root"),**changes})
        self.assertIsNone(p.binding({"producer_kind":None}))

    def test_aggregate_node_bound_covers_independent_branches_and_deduplicates_shared_sources(self):
        from cipher_aec.commercial.sources import merge
        one={"generated_sources":[{"document_id":str(i),"input_digest":"a"*64} for i in range(128)]}
        self.assertEqual(len(merge(one,one)["generated_sources"]),128)
        with self.assertRaises(DomainError) as error:
            merge(one,{"generated_sources":[{"document_id":"overflow","input_digest":"b"*64}]})
        self.assertEqual(error.exception.code,"source_limit")

    def test_complete_resource_admission_is_scoped_subset_and_preserved_when_nested(self):
        plan={"unit_ids":["unit-a"],"currencies":["USD"],"native_refs":[{"doctype":"Customer","name":"party-a"}],"generated_sources":[{"document_id":"doc-a","input_digest":"a"*64}]}
        self.assertFalse(p.is_prelocked(plan,ACTOR,"Company A"))
        with p.prelocked(plan,ACTOR,"Company A"):
            self.assertTrue(p.is_prelocked(plan,ACTOR,"Company A"))
            self.assertTrue(p.is_prelocked({"unit_ids":["unit-a"]},ACTOR,"Company A"))
            for extra in ({"unit_ids":["unit-b"]},{"currencies":["EUR"]},{"native_refs":[{"doctype":"Item","name":"item-b"}]},{"generated_sources":[{"document_id":"doc-a","input_digest":"b"*64}]}):
                self.assertFalse(p.is_prelocked(extra,ACTOR,"Company A"))
            self.assertFalse(p.is_prelocked(plan,ACTOR,"Company B"))
            self.assertFalse(p.is_prelocked(plan,types.SimpleNamespace(user="alias",person_id=ACTOR.person_id),"Company A"))
            with self.assertRaises(DomainError):
                with p.prelocked({"unit_ids":["unit-b"]},ACTOR,"Company A"):pass
            with self.assertRaises(DomainError):
                with p.prelocked({},types.SimpleNamespace(user="other",person_id=ACTOR.person_id),"Company A"):pass
            with p.prelocked({},ACTOR,"Company A"):
                self.assertTrue(p.is_prelocked(plan,ACTOR,"Company A"))
        self.assertFalse(p.is_prelocked(plan,ACTOR,"Company A"))


    def test_locked_original_memo_is_scoped_and_read_checks_never_reuse_it(self):
        row=document("root");calls=[]
        plan={"generated_sources":[{"document_id":"root","input_digest":row["producer_input_digest"]}]}
        with self.adapter(lambda binding,actor,lock=False:calls.append(lock)):
            with p.prelocked(plan,ACTOR,"Company A"):
                p.authorize(row,ACTOR,lock=True)
                with p.prelocked({},ACTOR,"Company A"):
                    p.authorize(row,ACTOR,lock=True)
                p.authorize(row,ACTOR,lock=False)
                p.authorize(row,ACTOR,lock=False)
            with p.prelocked(plan,ACTOR,"Company A"):
                p.authorize(row,ACTOR,lock=True)
            with self.assertRaises(RuntimeError):
                with p.prelocked(plan,ACTOR,"Company A"):
                    p.authorize(row,ACTOR,lock=True)
                    raise RuntimeError("stop")
            with p.prelocked(plan,ACTOR,"Company A"):
                p.authorize(row,ACTOR,lock=True)
        self.assertEqual(calls,[True,False,False,True,True,True])

    def test_locked_memo_never_caches_failure_or_skips_fresh_binding_and_cycle(self):
        row=document("root");calls=[];fail=[True]
        plan={"generated_sources":[{"document_id":"root","input_digest":row["producer_input_digest"]}]}
        def authorize(binding,actor,lock=False):
            calls.append(lock)
            if fail[0]:raise DomainError("not_found","Unavailable",404)
        with self.adapter(authorize),p.prelocked(plan,ACTOR,"Company A"):
            with self.assertRaises(DomainError):p.authorize(row,ACTOR,lock=True)
            fail[0]=False
            p.authorize(row,ACTOR,lock=True)
            p.authorize(row,ACTOR,lock=True)
            with self.assertRaises(DomainError) as error:
                p.authorize({**row,"producer_input_digest":"0"*64},ACTOR,lock=True)
            self.assertEqual(error.exception.code,"source_integrity")
            with p._visit("root",ACTOR,"Company A","authorize.locked-original-v1"):
                with self.assertRaises(DomainError) as error:p.authorize(row,ACTOR,lock=True)
                self.assertEqual(error.exception.code,"cyclic_source")
        self.assertEqual(calls,[True,True])

    def test_transaction_boundary_revokes_existing_locked_scope(self):
        row=document("root");plan={"generated_sources":[{"document_id":"root","input_digest":row["producer_input_digest"]}]}
        for boundary in ("before_commit","before_rollback"):
            callbacks=types.SimpleNamespace(before_commit=[],before_rollback=[])
            db=types.SimpleNamespace(**{name:types.SimpleNamespace(add=getattr(callbacks,name).append) for name in ("before_commit","before_rollback")})
            with patch.dict(sys.modules,{"frappe":types.SimpleNamespace(db=db)}),self.adapter(lambda *args,**kwargs:None):
                with p.prelocked(plan,ACTOR,"Company A"):
                    p.authorize(row,ACTOR,lock=True)
                    for callback in getattr(callbacks,boundary):callback()
                    self.assertFalse(p.is_prelocked(plan,ACTOR,"Company A"))
                    with self.assertRaises(DomainError) as error:p.authorize(row,ACTOR,lock=True)
                    self.assertEqual(error.exception.code,"source_prelock_required")


    def test_logical_operation_reuses_only_after_each_complete_callback_admission(self):
        row=document("root");calls=[]
        plan={"unit_ids":["u"],"generated_sources":[{"document_id":"root","input_digest":row["producer_input_digest"]}]}
        with self.adapter(lambda binding,actor,lock=False:calls.append(lock)):
            with p.logical_operation("Company A","estimate.accept","operation-a"):
                self.assertFalse(p.has_prelocked())
                with self.assertRaises(DomainError):p.authorize(row,ACTOR,lock=True)
                with p.prelocked(plan,ACTOR,"Company A"):p.authorize(row,ACTOR,lock=True)
                self.assertFalse(p.has_prelocked())
                with self.assertRaises(DomainError):p.authorize(row,ACTOR,lock=True)
                with p.prelocked(plan,ACTOR,"Company A"):p.authorize(row,ACTOR,lock=True)
                p.authorize(row,ACTOR,lock=False)
                with p.prelocked(plan,types.SimpleNamespace(user="alias",person_id=ACTOR.person_id),"Company A"):
                    p.authorize(row,types.SimpleNamespace(user="alias",person_id=ACTOR.person_id),lock=True)
                stats=p.logical_operation_stats()
                self.assertEqual(stats["producer_hits"],1)
                stats["producer_hits"]=999
                self.assertEqual(p.logical_operation_stats()["producer_hits"],1)
            with p.logical_operation("Company A","estimate.accept","operation-a"):
                with p.prelocked(plan,ACTOR,"Company A"):p.authorize(row,ACTOR,lock=True)
        self.assertEqual(calls,[True,False,True,True])
        self.assertIsNone(p.logical_operation_stats())

    def test_logical_lifetime_rejects_nested_other_operation_and_resets_exception(self):
        with self.assertRaisesRegex(RuntimeError,"stop"):
            with p.logical_operation("Company A","command","operation-a"):
                with p.logical_operation("Company A","command","operation-a"):
                    self.assertFalse(p.has_prelocked())
                for company,command,operation in (("Company B","command","operation-a"),("Company A","other","operation-a"),("Company A","command","operation-b")):
                    with self.assertRaises(DomainError):
                        with p.logical_operation(company,command,operation):pass
                raise RuntimeError("stop")
        self.assertIsNone(p.logical_operation_stats())
        with p.logical_operation("Company A","command","operation-b"):
            self.assertEqual(p.logical_operation_stats()["prelocked_scopes"],0)

    def test_logical_transaction_invalidation_cannot_be_replaced_by_new_callback(self):
        callbacks=[]
        db=types.SimpleNamespace(before_commit=types.SimpleNamespace(add=callbacks.append),before_rollback=types.SimpleNamespace(add=callbacks.append))
        with patch.dict(sys.modules,{"frappe":types.SimpleNamespace(db=db)}):
            with p.logical_operation("Company A","command","operation-a"):
                with p.prelocked({},ACTOR,"Company A"):pass
                callbacks[0]()
                with self.assertRaises(DomainError):
                    with p.prelocked({},ACTOR,"Company A"):pass
                with self.assertRaises(DomainError):
                    with p.logical_operation("Company A","command","operation-a"):pass
        self.assertFalse(p.has_prelocked())


    def test_logical_memo_requires_identical_complete_token_not_a_previous_subset(self):
        row=document("root");calls=[]
        plan={"unit_ids":["unit-a"],"currencies":["USD"],"generated_sources":[{"document_id":"root","input_digest":row["producer_input_digest"]}]}
        with self.adapter(lambda binding,actor,lock=False:calls.append(lock)),p.logical_operation("Company A","command","operation-a"):
            for next_plan in (plan,{**plan,"unit_ids":["unit-a","unit-b"]},{**plan,"currencies":["USD","EUR"]},{**plan,"generated_sources":plan["generated_sources"]+[{"document_id":"child","input_digest":"a"*64}]}):
                with p.prelocked(next_plan,ACTOR,"Company A"):
                    p.authorize(row,ACTOR,lock=True)
            self.assertEqual(p.logical_operation_stats()["producer_hits"],0)
        self.assertEqual(calls,[True,True,True,True])


    def test_optional_memo_saturation_never_rejects_a_valid_second_actor_graph(self):
        row=document("root");calls=[];deny=[False]
        alias=types.SimpleNamespace(user="alias",person_id="reviewer")
        plan={"generated_sources":[{"document_id":"root","input_digest":row["producer_input_digest"]}]}
        def authorize(binding,actor,lock=False):
            calls.append(actor.user)
            if deny[0]:raise DomainError("not_found","Unavailable",404)
        with patch.object(p,"MAX_NODES",1),self.adapter(authorize),p.logical_operation("Company A","command","operation-a"):
            with p.prelocked(plan,ACTOR,"Company A"):p.authorize(row,ACTOR,lock=True)
            for _ in range(2):
                with p.prelocked(plan,alias,"Company A"):p.authorize(row,alias,lock=True)
            deny[0]=True
            with p.prelocked(plan,alias,"Company A"):
                with self.assertRaises(DomainError):p.authorize(row,alias,lock=True)
        self.assertEqual(calls,[ACTOR.user,"alias","alias","alias"])


    def test_read_graph_is_one_snapshot_success_only_and_never_admits_locking(self):
        row=document("root");calls=[];allowed=[True]
        def authorize(binding,actor,lock=False):
            calls.append(lock)
            if not allowed[0]:raise DomainError("not_found","Unavailable",404)
        with self.adapter(authorize):
            with p.read_graph(ACTOR,"Company A"):
                self.assertFalse(p.has_prelocked())
                p.authorize(row,ACTOR)
                with p.read_graph(ACTOR,"Company A"):p.authorize(row,ACTOR)
                with self.assertRaises(DomainError):p.authorize(row,ACTOR,lock=True)
                with self.assertRaises(DomainError):
                    with p.logical_operation("Company A","command","operation-a"):pass
                self.assertEqual(p.read_graph_stats()["producer_hits"],1)
            allowed[0]=False
            with self.assertRaises(DomainError):
                with p.read_graph(ACTOR,"Company A"):p.authorize(row,ACTOR)
            allowed[0]=True
            with self.assertRaisesRegex(RuntimeError,"stop"):
                with p.read_graph(ACTOR,"Company A"):
                    p.authorize(row,ACTOR);raise RuntimeError("stop")
            with p.read_graph(ACTOR,"Company A"):p.authorize(row,ACTOR)
        self.assertEqual(calls,[False,False,False,False])
        self.assertIsNone(p.read_graph_stats())

    def test_read_graph_checks_binding_and_active_ancestry_even_on_hits(self):
        row=document("root")
        with self.adapter(lambda *a,**k:None),p.read_graph(ACTOR,"Company A"):
            p.authorize(row,ACTOR)
            with self.assertRaises(DomainError) as error:p.authorize({**row,"producer_input_digest":"0"*64},ACTOR)
            self.assertEqual(error.exception.code,"source_integrity")
            with p._visit("root",ACTOR,"Company A","authorize.read-v1"):
                with self.assertRaises(DomainError) as error:p.authorize(row,ACTOR)
                self.assertEqual(error.exception.code,"cyclic_source")

    def test_read_graph_write_counter_db_switch_identity_and_transactions_invalidate(self):
        def database():
            callbacks=[]
            return types.SimpleNamespace(transaction_writes=0,before_commit=types.SimpleNamespace(add=callbacks.append),before_rollback=types.SimpleNamespace(add=callbacks.append)),callbacks
        for change in ("write","database","actor","company","commit","rollback"):
            db,callbacks=database();frappe=types.SimpleNamespace(db=db)
            with self.subTest(change=change),patch.dict(sys.modules,{"frappe":frappe}),self.adapter(lambda *a,**k:None):
                with self.assertRaises(DomainError):
                    with p.read_graph(ACTOR,"Company A"):
                        p.authorize(document("root"),ACTOR)
                        actor=ACTOR;row=document("root")
                        if change=="write":db.transaction_writes=1
                        elif change=="database":frappe.db=database()[0]
                        elif change=="actor":actor=types.SimpleNamespace(user="other",person_id=ACTOR.person_id)
                        elif change=="company":row["company"]="Company B"
                        elif change=="commit":callbacks[0]()
                        else:callbacks[1]()
                        p.authorize(row,actor)
                self.assertIsNone(p.read_graph_stats())
        db,callbacks=database();db.transaction_writes=1
        with patch.dict(sys.modules,{"frappe":types.SimpleNamespace(db=db)}):
            self.assertFalse(p.read_graph_eligible(ACTOR,"Company A"))
            with self.assertRaises(DomainError):
                with p.read_graph(ACTOR,"Company A"):pass

    def test_read_graph_capacity_is_optional_and_requested_bytes_are_never_cached(self):
        from tempfile import TemporaryDirectory
        from pathlib import Path
        from cipher_aec.tests.test_documents import MemoryMetadata
        from cipher_aec.documents.core import DocumentService
        from cipher_aec.documents.storage import LocalArtifactStorage
        from cipher_aec.documents.extraction import digest as artifact_digest,ArtifactError
        calls=[]
        with TemporaryDirectory() as directory:
            service=DocumentService(MemoryMetadata(),LocalArtifactStorage(directory),lambda *a:None,scope_type="Company",allow_unscanned=True)
            content=b"Exact source text."
            uploaded=service.upload(company="Company A",project=None,title="Fixture",filename="source.txt",content=content,byte_length=len(content),sha256=artifact_digest(content))
            parent=document("root")
            service.source_authorize=lambda row,lock=False:p.authorize(parent,ACTOR,lock=lock)
            with self.adapter(lambda *a,**k:calls.append(True)),p.read_graph(ACTOR,"Company A"):
                service.citation("Company A",uploaded["revision"]["id"],1)
                (Path(directory)/uploaded["revision"]["id"]).unlink()
                with self.assertRaises(ArtifactError):service.citation("Company A",uploaded["revision"]["id"],1)
            self.assertEqual(len(calls),1)
        with patch.object(p,"MAX_NODES",1),self.adapter(lambda *a,**k:calls.append(True)),p.read_graph(ACTOR,"Company A"):
            p.authorize(document("root"),ACTOR)
            p.authorize(document("other"),ACTOR)
            p.authorize(document("other"),ACTOR)
        self.assertEqual(len(calls),4)


    def test_active_read_graph_eligibility_never_silently_falls_back(self):
        for change in ("actor","company","write","database"):
            db=types.SimpleNamespace(transaction_writes=0,before_commit=types.SimpleNamespace(add=lambda f:None),before_rollback=types.SimpleNamespace(add=lambda f:None))
            frappe=types.SimpleNamespace(db=db)
            with self.subTest(change=change),patch.dict(sys.modules,{"frappe":frappe}):
                with self.assertRaises(DomainError):
                    with p.read_graph(ACTOR,"Company A"):
                        actor,company=ACTOR,"Company A"
                        if change=="actor":actor=types.SimpleNamespace(user="other",person_id=ACTOR.person_id)
                        elif change=="company":company="Company B"
                        elif change=="write":db.transaction_writes=1
                        else:frappe.db=types.SimpleNamespace(transaction_writes=0)
                        with self.assertRaises(DomainError):p.read_graph_eligible(actor,company)


    def test_literal_original_proof_is_success_only_per_read_snapshot_and_not_a_dto(self):
        kind="Company Proposal Issue";seen=[]
        self.assertFalse(p.has_read_graph(ACTOR,"Company A"))
        with p.original_read_authority(kind,"issue","a"*64,ACTOR,"Company A") as reused:self.assertFalse(reused)
        with p.read_graph(ACTOR,"Company A"):
            self.assertTrue(p.has_read_graph(ACTOR,"Company A"))
            for expected in (False,True):
                with p.original_read_authority(kind,"issue","a"*64,ACTOR,"Company A") as reused:
                    self.assertIs(reused,expected);seen.append(reused)
            with p.original_read_authority(kind,"issue","b"*64,ACTOR,"Company A") as reused:self.assertFalse(reused)
            for arguments in ({"lock":True},{"scope_type":"Project"}):
                with p.original_read_authority(kind,"issue","a"*64,ACTOR,"Company A",**arguments) as reused:self.assertFalse(reused)
            with self.assertRaisesRegex(RuntimeError,"denied"):
                with p.original_read_authority(kind,"failed","a"*64,ACTOR,"Company A"):raise RuntimeError("denied")
            with p.original_read_authority(kind,"failed","a"*64,ACTOR,"Company A") as reused:self.assertFalse(reused)
        with p.read_graph(ACTOR,"Company A"):
            with p.original_read_authority(kind,"issue","a"*64,ACTOR,"Company A") as reused:self.assertFalse(reused)
        self.assertEqual(seen,[False,True])

    def test_original_proof_ancestry_uses_kind_and_id_before_digest_and_capacity_is_optional(self):
        with p.read_graph(ACTOR,"Company A"):
            with self.assertRaises(DomainError) as error:
                with p.original_read_authority("Company Proposal Issue","same","a"*64,ACTOR,"Company A"):
                    with p.original_read_authority("Company Proposal Issue","same","b"*64,ACTOR,"Company A"):pass
            self.assertEqual(error.exception.code,"cyclic_source")
            with self.assertRaises(DomainError):
                with p.original_read_authority("Unregistered Record","id","a"*64,ACTOR,"Company A"):pass
        with patch.object(p,"MAX_NODES",1),p.read_graph(ACTOR,"Company A"):
            for kind,name in (("Company Proposal Issue","one"),("Company Estimate Acceptance","two"),("Company Estimate Acceptance","two")):
                with p.original_read_authority(kind,name,"a"*64,ACTOR,"Company A") as reused:self.assertFalse(reused)

    def test_original_proof_checks_current_read_identity_and_invalidates_on_writes(self):
        db=types.SimpleNamespace(transaction_writes=0,before_commit=types.SimpleNamespace(add=lambda f:None),before_rollback=types.SimpleNamespace(add=lambda f:None))
        with patch.dict(sys.modules,{"frappe":types.SimpleNamespace(db=db)}):
            with self.assertRaises(DomainError):
                with p.read_graph(ACTOR,"Company A"):
                    with p.original_read_authority("Company Proposal Issue","one","a"*64,ACTOR,"Company A"):pass
                    db.transaction_writes=1
                    with p.original_read_authority("Company Proposal Issue","one","a"*64,ACTOR,"Company A"):pass
        alias=types.SimpleNamespace(user="alias",person_id=ACTOR.person_id)
        with self.assertRaises(DomainError):
            with p.read_graph(ACTOR,"Company A"):p.has_read_graph(alias,"Company A")

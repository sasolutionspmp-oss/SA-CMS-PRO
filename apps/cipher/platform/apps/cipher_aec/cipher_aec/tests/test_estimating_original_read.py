"""Fixture-only selected original authority, with fresh metadata and bytes."""
from contextlib import ExitStack
from copy import deepcopy
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from cipher_aec.api.contracts import digest
from cipher_aec.api.errors import DomainError
from cipher_aec.documents import provenance
from cipher_aec.estimating import governance, scopes, service


class AcceptanceOriginalReadTests(unittest.TestCase):
    def setUp(self):
        self.actor = SimpleNamespace(user="fixture-user", person_id="fixture-person")
        self.company = "Fixture Company"
        scope = {"scope_type": "Company", "company": self.company, "project": None}
        total = {"amount": "250.00", "currency": "EUR"}
        citations = [{"id": "explicit-fixture-citation"}]
        self.revision = {**scope, "id": "revision", "estimate": "estimate", "calculation_snapshot": "snapshot", "currency": "EUR", "policy_version": "fixed-policy", "total": total, "source_citations": citations}
        self.snapshot = {**scope, "id": "snapshot", "estimate": "estimate", "inputs": {"currency": "EUR"}, "result": {"total": total}, "input_digest": "input", "output_digest": "output", "source_citations": citations}
        self.owner = {**scope, "id": "estimate", "currency": "EUR", "current_revision": "later-working-revision", "pursuit_id": None}
        facts = {"policy": governance.MANIFEST_POLICY, "scope": scope, "revision": {"id": "revision", "digest": digest(self.revision)},
            "snapshot": {"id": "snapshot", "digest": digest(self.snapshot), "input_digest": "input", "output_digest": "output"}, "rounding_policy": "fixed-policy", "pursuit": None}
        manifest = {"subject": {"doctype": "Cipher Estimate Revision", "name": "revision"}, "effect": {"action": governance.ACTION, "revision_id": "revision", "facts": facts}, "sources": citations}
        self.acceptance = {**scope, "id": "acceptance", "status": "accepted", "estimate": "estimate", "estimate_revision": "revision", "calculation_snapshot": "snapshot",
            "manifest": manifest, "manifest_digest": digest(manifest), "accepted_result": self.snapshot["result"], "currency": "EUR", "total": total, "source_citations": citations}
        self.records = {"acceptance": self.acceptance, "revision": self.revision, "snapshot": self.snapshot, "estimate": self.owner}
        self.stack = ExitStack(); self.addCleanup(self.stack.close)
        self.stack.enter_context(scopes.activate("Company", self.company, None))
        self.stack.enter_context(patch.object(provenance, "_current_db", return_value=None))
        self.require = self.stack.enter_context(patch.object(service, "require_project"))
        self.read = self.stack.enter_context(patch.object(service.repository, "read", side_effect=lambda kind, *a, **kw: deepcopy(self.records[kind])))
        self.original = self.stack.enter_context(patch.object(governance, "authorize_subject"))
        self.bytes = self.stack.enter_context(patch.object(service.sources, "_verify_original"))
        self.stack.enter_context(patch.object(service.units, "verify_manifest_access"))

    def get(self, **kwargs):
        return service._scoped("acceptance", "acceptance", self.company, None, self.actor, **kwargs)

    def test_reuses_only_original_authority_and_rechecks_scope_metadata_and_bytes(self):
        with provenance.read_graph(self.actor, self.company):
            one = self.get()
            self.owner["current_revision"] = "another-later-working-revision"
            two = self.get()
        self.assertEqual(one, two)
        self.assertIsNot(one, two)
        self.assertEqual(self.original.call_count, 1)
        self.assertEqual(self.bytes.call_count, 2)
        self.assertEqual(self.require.call_count, 2)
        self.assertEqual(self.read.call_count, 8)

    def test_same_acceptance_proof_cannot_hide_changed_revision_or_result_linkage(self):
        with provenance.read_graph(self.actor, self.company):
            self.get()
            self.revision["currency"] = "USD"
            with self.assertRaises(DomainError) as caught:
                self.get()
            self.assertEqual(caught.exception.code, "approval_integrity")
        self.assertEqual(self.original.call_count, 1)

    def test_malformed_manifest_policy_refused_before_proof_lookup(self):
        self.acceptance["manifest"]["effect"]["facts"]["policy"] = "unregistered-policy"
        self.acceptance["manifest_digest"] = digest(self.acceptance["manifest"])
        with provenance.read_graph(self.actor, self.company):
            with self.assertRaises(DomainError) as caught:
                self.get()
            self.assertEqual(caught.exception.code, "approval_integrity")
        self.original.assert_not_called()

    def test_no_graph_and_locking_paths_bind_originals_and_retain_uncached_authorization(self):
        with patch.object(service, "_acceptance_original_linkage", wraps=service._acceptance_original_linkage) as linkage:
            self.get(); self.get(lock=True)
        self.assertEqual(linkage.call_count, 2)
        self.assertEqual([call.kwargs["lock"] for call in linkage.call_args_list], [False, True])
        self.assertEqual(self.original.call_count, 2)
        self.assertEqual(self.read.call_count, 8)

    def test_new_read_root_rechecks_revoked_original_rights(self):
        with provenance.read_graph(self.actor, self.company):
            self.get()
        self.original.side_effect = DomainError("not_found", "Fixture original authority revoked", 404)
        with provenance.read_graph(self.actor, self.company):
            with self.assertRaises(DomainError) as caught:
                self.get()
            self.assertEqual(caught.exception.code, "not_found")
        self.assertEqual(self.original.call_count, 2)

    def test_requested_bytes_remain_checked_even_after_same_read_proof_hit(self):
        with provenance.read_graph(self.actor, self.company):
            self.get()
            self.bytes.side_effect = DomainError("not_found", "Fixture original bytes unavailable", 404)
            with self.assertRaises(DomainError) as caught:
                self.get()
            self.assertEqual(caught.exception.code, "not_found")
        self.assertEqual(self.original.call_count, 1)
        self.assertEqual(self.bytes.call_count, 2)

    def test_alias_cannot_reuse_another_users_read_proof(self):
        with self.assertRaises(DomainError) as caught:
            with provenance.read_graph(self.actor, self.company):
                self.get()
                alias = SimpleNamespace(user="fixture-alias", person_id=self.actor.person_id)
                service._scoped("acceptance", "acceptance", self.company, None, alias)
        self.assertEqual(caught.exception.code, "source_read_context_invalid")
        self.assertEqual(self.original.call_count, 1)

    def test_project_acceptance_retains_its_original_path_and_payload(self):
        self.stack.close()
        record = deepcopy(self.acceptance)
        record.pop("scope_type"); record["project"] = "Fixture Project"
        with ExitStack() as stack:
            stack.enter_context(scopes.activate("Project", self.company, "Fixture Project"))
            stack.enter_context(patch.object(service, "require_project"))
            stack.enter_context(patch.object(service.repository, "read", return_value=record))
            original = stack.enter_context(patch.object(governance, "authorize_subject"))
            stack.enter_context(patch.object(service.sources, "verify"))
            stack.enter_context(patch.object(service.units, "verify_manifest_access"))
            stack.enter_context(patch.object(provenance, "has_read_graph", side_effect=AssertionError("Project cannot use Company proof")))
            stack.enter_context(patch.object(service, "_acceptance_original_linkage", side_effect=AssertionError("Project cannot use Company metadata branch")))
            result = service._scoped("acceptance", "acceptance", self.company, "Fixture Project", self.actor)
            self.assertEqual(result, record)
            self.assertEqual(original.call_args.kwargs["scope_type"], "Project")
            self.assertEqual(original.call_args.kwargs["phase"], "baseline")


if __name__ == "__main__":
    unittest.main()

"""Host-only regression for original shared-origin recipient evidence.

Actual persistence, HTTP and database locks require their separate native gate.
"""
from copy import deepcopy
import unittest
from cipher_aec.api.contracts import digest
from cipher_aec.api.errors import DomainError
from cipher_aec.tests.test_document_control import person, source, authorize
from cipher_aec.tests.test_document_control_shared import shared_fixture, company_library
from cipher_aec.tests.test_engineering import uid


class MixedOriginalEvidenceTests(unittest.TestCase):
    def prepared(self, values):
        state, rules, repo, rights, service, governance, shared = values
        created, company_ref, _, _ = company_library(state, shared)
        revision = created['library_revision']
        request = shared.create_adoption('C', 'P', uid(), {'scope_type': 'Company', 'project': None}, revision['id'], digest(revision),
            {'purpose': 'Retain exact same-Company source', 'target_locator': 'Project reference', 'change_reason': 'Independent selection'})['adoption_request']
        reviewer = person(state, rules, 'recipient')
        state.company_duties[reviewer.person_id] = {rules.READ, 'company.read', 'document.read'}
        adoption = authorize(state, rules, governance, 'adoption_request', request, reviewer)
        project_ref = source(state, service)
        issued_set = service.create_issue_set('C', 'P', uid(), {'title': 'Mixed original package', 'purpose': 'Internal review', 'issue_purpose': 'coordination'},
            [project_ref], [{'id': adoption['id'], 'record_digest': digest(adoption)}])['issue_set']
        issued = authorize(state, rules, governance, 'issue_set', issued_set, reviewer)
        transmittal = service.create_transmittal('C', 'P', uid(), issued['id'], digest(issued), [reviewer.user], 'Internal original package', '')['transmittal']
        distribution = authorize(state, rules, governance, 'transmittal', transmittal, reviewer)
        return reviewer, distribution, company_ref, project_ref

    def test_mixed_original_distribution_accepts_project_receipt_and_exact_replay(self):
        with shared_fixture() as values:
            state, rules, repo, rights, service, governance, shared = values
            reviewer, distribution, company_ref, project_ref = self.prepared(values)
            state.actor = reviewer
            original = deepcopy(distribution)
            operation = uid()
            result = service.record_evidence('C', 'P', operation, 'distribution', distribution['id'], digest(distribution), 'Recipient reports internal review only', [project_ref])
            self.assertEqual(result['evidence']['status'], 'reported_received')
            self.assertFalse(result['evidence']['commercial_execution'])
            self.assertFalse(result['evidence']['electronic_signature'])
            replay = service.record_evidence('C', 'P', operation, 'distribution', distribution['id'], digest(distribution), 'Recipient reports internal review only', [project_ref])
            self.assertTrue(replay['operation']['replayed'])
            self.assertEqual(replay['evidence'], result['evidence'])
            self.assertEqual(repo.raw('distribution', distribution['id']), original)
            state.company_duties[reviewer.person_id].remove('document.read')
            with self.assertRaises(DomainError):
                service.record_evidence('C', 'P', operation, 'distribution', distribution['id'], digest(distribution), 'Recipient reports internal review only', [project_ref])

    def test_shared_subject_does_not_allow_unselected_report_source_or_nonrecipient(self):
        with shared_fixture() as values:
            state, rules, repo, rights, service, governance, shared = values
            reviewer, distribution, company_ref, project_ref = self.prepared(values)
            original = deepcopy(state.rows)
            # Supplying a Company report artifact still uses Project-only resolve.
            state.actor = reviewer
            with self.assertRaises(DomainError):
                service.record_evidence('C', 'P', uid(), 'distribution', distribution['id'], digest(distribution), 'No implicit Company evidence authoring', [company_ref])
            self.assertEqual(state.rows, original)
            other = person(state, rules, 'nonrecipient')
            state.company_duties[other.person_id] = {rules.READ, 'company.read', 'document.read'}
            state.actor = other
            with self.assertRaises(DomainError) as failure:
                service.record_evidence('C', 'P', uid(), 'distribution', distribution['id'], digest(distribution), 'Not a selected recipient', [project_ref])
            self.assertEqual(failure.exception.code, 'recipient_required')
            self.assertEqual(state.rows, original)


if __name__ == '__main__':
    unittest.main()

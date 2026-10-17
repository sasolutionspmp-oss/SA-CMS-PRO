"""Every document write preserves exact data and immutable revision history."""
import json
from frappe.model.document import Document
from cipher_aec.api.contracts import digest
from cipher_aec.api.errors import DomainError
from cipher_aec.governance.context import current_actor, require_project, require_trusted_write
from . import core, repository


class FinanceRecord(Document):
    def validate(self):
        require_trusted_write()
        try:
            value = json.loads(self.data_json)
        except (ValueError, TypeError):
            core.fail('A construction finance record requires canonical JSON.')
        core.identifier(self.name)
        if type(value) is not dict or value.get('id') != self.name or self.record_digest != digest(value):
            raise DomainError('contract_integrity', 'The exact contract record digest does not match its payload.', 409)
        for field in ('company', 'project', 'author_person', 'status'):
            if self.get(field) != value.get(field):
                raise DomainError('contract_integrity', 'The contract record scope does not match its payload.', 409)
        actor = current_actor()
        if self.doctype=='Cipher Construction Contract' and self.is_new() and value.get('origin')=='governed_award_v1':
            from .award_factory import validate_new_contract
            validate_new_contract(value)
        else:
            require_project(self.company, self.project, ability='contract.write', actor=actor, lock=True)
            require_project(self.company, self.project, ability='contract.read', actor=actor, lock=True)
        if self.is_new() and value['author_person'] != actor.person_id:
            raise DomainError('forged_authority', 'The current canonical person must author this record.', 403)
        kind = next(key for key, name in repository.DOCTYPES.items() if name == self.doctype)
        if kind != 'contract' and not self.is_new():
            raise DomainError('immutable_contract_revision', 'Create an explicit successor; contract facts and policies are immutable.', 409)
        if kind == 'contract':
            self._contract(value)
            fields = {'contract_number': value['definition']['number'], 'kind': value['definition']['kind'], 'direction': value['definition']['direction'],
                      'party_type': value['definition']['party_type'], 'party': value['definition']['party'], 'currency': value['definition']['currency'],
                      'original_amount': value['definition']['original_value']['amount'], 'revision_number': value['revision_number'],
                      'draft_revision': value['draft_revision'], 'accepted_revision': value['accepted_revision']}
        else:
            contract = repository.read('contract', value['contract'], lock=True)
            if any(contract[key] != value[key] for key in ('company', 'project')):
                raise DomainError('contract_integrity', 'Revision and contract scope must agree.', 409)
            from cipher_aec.estimating.sources import verify
            verify(self.company, self.project, value['source_citations'], actor, lock=True)
            fields = {'contract': value['contract']}
            if kind == 'revision':
                core.terms(value['terms'])
                fields.update(revision_number=value['revision_number'], predecessor=value['predecessor'], policy_revision=value['policy_revision'],
                              currency=value['currency'], billing_method=value['terms']['billing_method'])
            elif kind == 'policy':
                core.retainage(value['policy'], value['currency'], contract['currency_policy']['currency_exponent'])
                fields.update(revision_number=value['revision_number'], predecessor=value['predecessor'], currency=value['currency'])
            elif kind == 'sov':
                policy = repository.read('policy', repository.read('revision', value['contract_revision'], lock=True)['policy_revision'], lock=True)
                total = core.sov(value['lines'], value['currency'], contract['currency_policy']['currency_exponent'], contract['definition']['original_value'],
                                 {unit['id']: unit for unit in value['units']}, policy['policy'])
                if total != value['scheduled_total']:
                    raise DomainError('contract_integrity', 'The exact SOV total is inconsistent.', 409)
                fields.update(contract_revision=value['contract_revision'], revision_number=value['revision_number'], predecessor=value['predecessor'], currency=value['currency'], scheduled_amount=total['amount'])
            else:
                sov = repository.read('sov', value['sov_version'], lock=True)
                if value['line'] not in sov['lines'] or value['line_id'] != value['line']['line_id']:
                    raise DomainError('contract_integrity', 'A stable SOV line must match its immutable version.', 409)
                unit = next(row for row in sov['units'] if row['id'] == value['line']['quantity']['unit_id'])
                fields.update(sov_version=value['sov_version'], line_id=value['line_id'], item_code=value['line']['item_code'], unit=unit['target']['name'],
                              quantity_amount=value['line']['quantity']['amount'], scheduled_amount=value['line']['scheduled_amount']['amount'], currency=sov['currency'])
        for field, expected in fields.items():
            actual = self.get(field)
            if actual != expected and not (actual in (None, '') and expected is None):
                raise DomainError('contract_integrity', 'The native contract projection does not match its exact payload.', 409, {'field': field})

    def _contract(self, value):
        core.definition(value['definition'], value['currency_policy']['currency_exponent'])
        if self.is_new():
            if value['origin'] not in {'server_created_fin01','governed_award_v1'} or value['draft_revision'] or value['accepted_revision'] or value['revision_number'] != 0 or value['status'] != 'draft':
                raise DomainError('invalid_contract_origin', 'New contracts begin with an unaccepted authored draft.', 409)
            return
        before = json.loads(self.get_doc_before_save().data_json)
        mutable = {'draft_revision', 'accepted_revision', 'revision_number', 'business_revision', 'status', 'activation'}
        if {k:v for k,v in before.items() if k not in mutable} != {k:v for k,v in value.items() if k not in mutable}:
            raise DomainError('immutable_contract_scope', 'Original contract scope, counterparty, currency, cap, and provenance cannot be rewritten.', 409)
        if value['business_revision'] != before['business_revision'] + 1:
            raise DomainError('stale_contract', 'Contract business revisions advance exactly once.', 412)
        if value['accepted_revision'] != before['accepted_revision']:
            from cipher_aec.governance.approvals import require_approval_effect
            require_approval_effect(action='contract.baseline.activate.v1', subject_id=value['id'], packet_id=value['activation']['packet_id'])
            revision = repository.read('revision', value['accepted_revision'], lock=True)
            if value['accepted_revision'] != before['draft_revision'] or revision['accepted_predecessor'] != before['accepted_revision'] or value['draft_revision'] != before['draft_revision'] or value['revision_number'] != before['revision_number'] or value['status'] != 'baseline_accepted':
                raise DomainError('stale_contract', 'Activation must consume the exact current draft and accepted predecessor.', 412)
        else:
            revision = repository.read('revision', value['draft_revision'], lock=True)
            if value['revision_number'] != before['revision_number'] + 1 or revision['predecessor'] != before['draft_revision'] or revision['revision_number'] != value['revision_number'] or value['status'] != before['status'] or value.get('activation') != before.get('activation'):
                raise DomainError('stale_contract', 'Authored successors must advance the current draft exactly once.', 412)

    def on_trash(self):
        raise DomainError('contract_history_preserved', 'Construction contract facts cannot be deleted.', 403)

    def before_rename(self, *args, **kwargs):
        raise DomainError('immutable_contract_identity', 'Construction contract identities cannot be renamed.', 403)

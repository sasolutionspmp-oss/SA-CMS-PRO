"""Native writers require exact private plans and current scoped authority."""
import json
from frappe.model.document import Document
from cipher_aec.api.contracts import digest
from cipher_aec.api.errors import DomainError
from cipher_aec.governance.context import current_actor, require_project
from . import contracts as rules, repository as repo, sources


def _ref(kind, record_id, value, plan):
    from . import service
    pending = plan['facts'].get((kind, record_id))
    return pending if pending is not None else service._raw(kind, record_id, value['company'], value['project'], lock=True)


class CloseoutRecord(Document):
    def validate(self):
        from . import service
        kind = next(k for k, v in rules.KINDS.items() if v == self.doctype)
        try: value = json.loads(self.data_json)
        except (TypeError, ValueError):
            raise DomainError('closeout_integrity', 'Supply exact canonical closeout JSON.', 422) from None
        rules.record(kind, value, initial=self.is_new() and kind == 'package')
        repo.require_write(self, kind, value); repo.check_indexes(self, value)
        actor, plan = current_actor(), service._effect.get()
        if (not plan or plan['person'] != actor.person_id
            or (plan['company'], plan['project']) != (value['company'], value['project'])
            or plan['facts'].get((kind, value['id'])) != value):
            raise DomainError('closeout_command_required', 'Use the exact admitted closeout command.', 403)
        action = plan['action']
        if action not in service.ACTION_DUTY:
            raise DomainError('closeout_command_required', 'Use a supported closeout command.', 403)
        require_project(self.company, self.project, ability=rules.READ, actor=actor, lock=True)
        project = require_project(self.company, self.project, ability=service.ACTION_DUTY[action], actor=actor, lock=True)
        if project.status in ('Completed', 'Cancelled'):
            raise DomainError('project_closed', 'This Project is closed for new closeout work.', 409)
        if self.is_new() and (value['author_person'], value['author_user']) != (actor.person_id, actor.user):
            raise DomainError('forged_authority', 'Authorship comes from the current canonical person.', 403)
        if kind == 'package':
            self._header(value, plan)
            return
        header = service._raw('package', value['parent_id'], self.company, self.project, lock=True)
        if kind in rules.REQUIREMENTS | {'package_revision'}:
            if action not in ('create_package', 'revise_package'):
                raise DomainError('closeout_command_required', 'Only an exact package revision may create requirements.', 403)
            if value['revision_number'] != header['revision_number'] + 1:
                raise DomainError('stale_closeout', 'The next package revision changed.', 412)
            if kind == 'package_revision':
                if value['predecessor'] != header['current_revision'] or value['amendment_of'] != header['accepted_turnover']:
                    raise DomainError('closeout_integrity', 'The package revision has a different exact original.', 409)
                for row in value['requirements']:
                    requirement = _ref(row['kind'], row['id'], value, plan)
                    if requirement['package_revision'] != value['id'] or requirement['parent_id'] != header['id'] or digest(requirement) != row['record_digest']:
                        raise DomainError('closeout_integrity', 'The exact requirement manifest differs.', 409)
            else:
                revision = _ref('package_revision', value['package_revision'], value, plan)
                if revision['parent_id'] != header['id'] or {'kind': kind, 'id': value['id'], 'record_digest': digest(value)} not in revision['requirements']:
                    raise DomainError('closeout_integrity', 'The requirement differs from its exact package plan.', 409)
            return
        if value['package_revision'] != header['current_revision']:
            raise DomainError('stale_closeout', 'The current exact package revision changed.', 412)
        if kind in rules.RESULTS:
            if action != 'record_result' or header['status'] == 'accepted':
                raise DomainError('closeout_command_required', 'Use an explicit result command on a working package.', 403)
            revision = service._raw('package_revision', value['package_revision'], self.company, self.project, lock=True)
            ref = next((r for r in revision['requirements'] if r['id'] == value['requirement_id']), None)
            if not ref: raise DomainError('closeout_integrity', 'The exact requirement is absent.', 409)
            requirement = service.read(ref['kind'], ref['id'], self.company, self.project, actor, lock=True)
            if digest(requirement) != value['requirement_digest'] or (kind == 'asset_handover') != (requirement['category'] == 'asset_handover'):
                raise DomainError('closeout_integrity', 'The exact result requirement differs.', 409)
            rules.result_definition(value['definition'], requirement['category']); rules.result_links(requirement['category'], value['links'])
            previous = next((r for r in header['result_heads'] if r['requirement_id'] == value['requirement_id']), None)
            if value['predecessor'] != (previous['result_id'] if previous else None):
                raise DomainError('stale_closeout_result', 'The exact result predecessor changed.', 412)
            sources.verify([value], self.company, self.project, actor, lock=True, new_use=True)
        elif kind == 'turnover':
            if action != 'assemble_turnover' or header['status'] != 'draft' or value['items'] != header['accepted_results']:
                raise DomainError('closeout_command_required', 'Use the exact current accepted evidence to assemble turnover.', 403)
            revision = service.read('package_revision', value['package_revision'], self.company, self.project, actor, lock=True)
            if value['package_digest'] != digest(revision): raise DomainError('closeout_integrity', 'The turnover package digest differs.', 409)
            required = {r['id'] for r in revision['requirements'] if service._raw(r['kind'], r['id'], self.company, self.project, lock=True)['required']}
            if not required <= {r['requirement_id'] for r in value['items']}:
                raise DomainError('closeout_evidence_required', 'Required independently accepted evidence is missing.', 422)
            for row in value['items']:
                service._accepted(row, revision, lambda k, i: service.read(k, i, self.company, self.project, actor, lock=True, new_use=True))
        else:
            if action != value['action']:
                raise DomainError('closeout_command_required', 'The exact acceptance command differs.', 403)
            original = service.read(value['subject_kind'], value['subject_id'], self.company, self.project, actor, lock=True, new_use=True)
            if digest(original) != value['subject_digest'] or original['parent_id'] != header['id']:
                raise DomainError('closeout_integrity', 'The exact acceptance subject differs.', 409)
            if actor.person_id == original['author_person']:
                raise DomainError('independent_closeout_required', 'Another canonical person must accept the exact original.', 403)
            if action == 'accept_result':
                if header['status'] == 'accepted' or original['definition']['outcome'] != 'pass' or not any(r['result_id'] == original['id'] and r['result_kind'] == value['subject_kind'] for r in header['result_heads']):
                    raise DomainError('stale_closeout_result', 'Select a current passing result for independent acceptance.', 412)
            else:
                revision = service.read('package_revision', value['package_revision'], self.company, self.project, actor, lock=True)
                if actor.person_id == revision['author_person']:
                    raise DomainError('independent_closeout_required', 'The package author cannot accept its own turnover.', 403)
                if header['status'] != 'assembled' or header['turnover_head'] != original['id']:
                    raise DomainError('stale_closeout_turnover', 'The current assembled turnover changed.', 412)

    def _header(self, value, plan):
        from . import service
        action = plan['action']
        if self.is_new():
            if action != 'create_package' or value['status'] != 'draft' or value['revision_number'] != 0 or value['result_heads'] or value['accepted_results'] or any(value[k] is not None for k in ('current_revision', 'turnover_head', 'accepted_turnover')):
                raise DomainError('closeout_command_required', 'A new package begins as an exact empty draft.', 403)
            return
        old = json.loads(self.get_doc_before_save().data_json)
        expected = deepcopy_record(old)
        facts = [v for (k, _), v in plan['facts'].items() if k != 'package' and v.get('parent_id') == value['id']]
        if action in ('create_package', 'revise_package'):
            revision = next((v for v in facts if 'requirements' in v), None)
            if not revision: raise DomainError('closeout_integrity', 'The exact successor revision plan is missing.', 409)
            expected.update(status='draft', revision_number=old['revision_number'] + 1, current_revision=revision['id'], result_heads=[], accepted_results=[], turnover_head=None)
        elif action == 'record_result':
            result = next((v for v in facts if 'requirement_digest' in v), None)
            if not result: raise DomainError('closeout_integrity', 'The exact result plan is missing.', 409)
            k = 'asset_handover' if ('asset_handover', result['id']) in plan['facts'] else 'test_result'
            heads = [r for r in old['result_heads'] if r['requirement_id'] != result['requirement_id']]
            heads.append({'requirement_id': result['requirement_id'], 'result_kind': k, 'result_id': result['id']})
            expected.update(status='draft', result_heads=heads, accepted_results=[r for r in old['accepted_results'] if r['requirement_id'] != result['requirement_id']], turnover_head=None)
        elif action == 'accept_result':
            decision = next((v for v in facts if v.get('action') == action), None)
            if not decision: raise DomainError('closeout_integrity', 'The exact independent result decision is missing.', 409)
            result = _ref(decision['subject_kind'], decision['subject_id'], value, plan)
            accepted = [r for r in old['accepted_results'] if r['requirement_id'] != result['requirement_id']]
            accepted.append({'requirement_id': result['requirement_id'], 'result_kind': decision['subject_kind'], 'result_id': result['id'], 'result_digest': digest(result), 'decision_id': decision['id'], 'decision_digest': digest(decision)})
            expected.update(status='draft', accepted_results=accepted, turnover_head=None)
        elif action == 'assemble_turnover':
            turnover = next((v for v in facts if 'items' in v), None)
            if not turnover: raise DomainError('closeout_integrity', 'The exact turnover snapshot is missing.', 409)
            expected.update(status='assembled', turnover_head=turnover['id'])
        else:
            decision = next((v for v in facts if v.get('action') == action), None)
            if not decision: raise DomainError('closeout_integrity', 'The exact turnover decision is missing.', 409)
            expected.update(status='accepted', accepted_turnover=decision['subject_id'])
        if value != expected:
            raise DomainError('closeout_integrity', 'The mutable header differs from its exact immutable command facts.', 409)

    def on_trash(self):
        raise DomainError('immutable_closeout', 'Original closeout records and history cannot be deleted.', 409)

    def before_rename(self, *args, **kwargs):
        raise DomainError('immutable_closeout', 'Closeout record identities cannot be renamed.', 409)


def deepcopy_record(value):
    from copy import deepcopy
    return deepcopy(value)

"""Actual Frappe/MariaDB Task controls. Root runs on its serialized integration DB."""

import uuid
import json
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from cipher_aec.api.contracts import digest, version_of
from cipher_aec.api.errors import DomainError
from cipher_aec.governance.commands import read_operation
from cipher_aec.governance.context import current_actor, trusted_write
from cipher_aec.install import seed_synthetic, set_synthetic_duty
from cipher_aec.projects import service, tasks


class TestTaskControlsNative(IntegrationTestCase):
    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        self.savepoint = "task_controls_" + uuid.uuid4().hex
        frappe.db.savepoint(self.savepoint)
        self.fixture = seed_synthetic()
        self.company, self.project = self.fixture["company"], self.fixture["project"]
        self.primary, self.alias, self.reviewer, self.outsider = [self.fixture["users"][key]["user"] for key in ("primary", "alias", "reviewer", "outsider")]
        self.person = self.fixture["users"]["primary"]["person"]
        frappe.set_user(self.primary)
        self.task = service.create_task(self.company, self.project, self.uid(),
            service.read_project(self.company, self.project)["version"], "Task controls " + self.uid())['task']

    def tearDown(self):
        frappe.set_user("Administrator")
        frappe.db.rollback(save_point=self.savepoint)
        super().tearDown()

    @staticmethod
    def uid():
        return str(uuid.uuid4())

    def assign_request(self, **changes):
        value = dict(company=self.company, project=self.project, task=self.task['id'], person=self.person,
            operation_id=self.uid(), expected_version=tasks.read_task(self.company, self.project, self.task['id'])['version'])
        value.update(changes)
        return value

    def assign(self, **changes):
        return tasks.assign_task(**self.assign_request(**changes))

    def status(self, status, **changes):
        value = dict(company=self.company, project=self.project, task=self.task['id'], status=status,
            operation_id=self.uid(), expected_version=tasks.read_task(self.company, self.project, self.task['id'])['version'])
        value.update(changes)
        return tasks.update_task_status(**value)

    def todos(self):
        return frappe.get_all("ToDo", filters={"reference_type": "Task", "reference_name": self.task['id']}, fields=['name','allocated_to','status'])

    def assert_code(self, code, call):
        with self.assertRaises(DomainError) as raised:
            call()
        self.assertEqual(raised.exception.code, code)

    def test_one_canonical_person_one_todo_and_alias_retry(self):
        request = self.assign_request()
        result = tasks.assign_task(**request)
        frappe.set_user(self.alias)
        replay = tasks.assign_task(**request)
        self.assertTrue(replay['operation']['replayed'])
        self.assertEqual(replay['task'], result['task'])
        self.assertEqual(result['task']['assignees'], [{'id': self.person, 'display_name': current_actor().display_name}])
        self.assertEqual(len(self.todos()), 1)
        self.assertEqual(json.loads(frappe.db.get_value('Task',self.task['id'],'_assign') or '[]'),[self.todos()[0].allocated_to])
        self.assertEqual(frappe.db.count('Cipher History Event', {'operation_id': request['operation_id']}), 1)
        self.assertEqual(read_operation(self.company,self.project,request['operation_id'])['task'], result['task'])

    def test_reused_operation_changed_person_conflicts(self):
        request = self.assign_request()
        tasks.assign_task(**request)
        request['person'] = self.fixture['users']['reviewer']['person']
        self.assert_code('operation_conflict', lambda: tasks.assign_task(**request))
        self.assertEqual(len(self.todos()), 1)

    def test_unassign_cancels_exact_todo_and_advances_versions(self):
        first = self.assign()
        result = tasks.assign_task(**self.assign_request(person=None))
        self.assertEqual(result['task']['assignees'], [])
        self.assertEqual(self.todos()[0].status, 'Cancelled')
        self.assertNotEqual(first['task']['version'], result['task']['version'])
        self.assertNotEqual(first['project_version'], result['project_version'])

    def test_reassignment_preserves_original_native_history(self):
        self.assign()
        person = self.fixture['users']['reviewer']['person']
        result = self.assign(person=person)
        self.assertEqual(result['task']['assignees'][0]['id'], person)
        self.assertEqual(sorted(row.status for row in self.todos()), ['Cancelled','Open'])

    def test_choices_deduplicate_aliases_and_exclude_other_project(self):
        choices = tasks.task_choices(self.company,self.project)
        self.assertEqual(sum(row['id'] == self.person for row in choices['people']), 1)
        self.assertNotIn(self.fixture['users']['outsider']['person'], {row['id'] for row in choices['people']})
        self.assertEqual(choices['capabilities'], ['task.assign','task.update'])

    def test_ineligible_person_is_refused_without_effect(self):
        before = tasks.read_task(self.company,self.project,self.task['id'])
        self.assert_code('assignee_unavailable', lambda: self.assign(person=self.fixture['users']['outsider']['person']))
        self.assertEqual(before,tasks.read_task(self.company,self.project,self.task['id']))
        self.assertEqual(self.todos(), [])

    def test_disabled_person_is_ineligible(self):
        person = self.fixture['users']['reviewer']['person']
        with trusted_write():
            doc=frappe.get_doc('Cipher Person',person);doc.active=0;doc.save(ignore_permissions=True)
        self.assert_code('assignee_unavailable', lambda: self.assign(person=person))
        self.assertNotIn(person, {row['id'] for row in tasks.task_choices(self.company,self.project)['people']})

    def test_revoked_target_project_duty_is_rechecked_at_assignment(self):
        person=self.fixture['users']['reviewer']['person']
        self.assertIn(person,{row['id'] for row in tasks.task_choices(self.company,self.project)['people']})
        frappe.set_user('Administrator');set_synthetic_duty(self.reviewer,self.project,'project.read',0);frappe.set_user(self.primary)
        self.assert_code('assignee_unavailable',lambda:self.assign(person=person))
        self.assertEqual(self.todos(),[])

    def test_current_update_duty_is_required_for_status_and_choices(self):
        frappe.set_user('Administrator')
        set_synthetic_duty(self.primary,self.project,'task.update',0)
        set_synthetic_duty(self.primary,self.project,'task.assign',0)
        frappe.set_user(self.primary)
        self.assert_code('capability_denied',lambda:self.status('Completed'))
        self.assert_code('capability_denied',lambda:tasks.task_choices(self.company,self.project))
        self.assert_code('capability_denied',lambda:self.assign(person='UNREGISTERED-PERSON'))

    def test_stale_task_version_refuses_assignment_and_status(self):
        stale=self.task['version']
        self.status('Working')
        self.assert_code('stale_version', lambda:self.assign(expected_version=stale))
        self.assert_code('stale_version', lambda:self.status('Completed',expected_version=stale))
        self.assertEqual(self.todos(), [])

    def test_native_overdue_change_without_modified_timestamp_is_stale(self):
        doc=frappe.get_doc('Task',self.task['id']);before=version_of(doc)
        doc.exp_end_date=frappe.utils.add_days(frappe.utils.nowdate(),-1)
        doc.flags.from_project=True
        doc.update_status()
        self.assertEqual(version_of(frappe.get_doc('Task',doc.name)),before)
        self.assert_code('stale_version',lambda:self.status('Working',expected_version=self.task['version']))

    def test_identity_alias_is_not_accepted_as_canonical_person(self):
        self.assert_code('assignee_unavailable',lambda:self.assign(person=self.primary))
        self.assertEqual(self.todos(),[])

    def test_complete_preserves_project_status_progress_and_financial_inventory(self):
        self.assign()
        # Native Task.save would otherwise derive Completed at 100% and write
        # Project directly, bypassing the separate Project approval contract.
        frappe.db.set_value('Project',self.project,{'percent_complete_method':'Task Completion','percent_complete':17})
        before = frappe.db.get_value('Project',self.project,['status','percent_complete'],as_dict=True)
        financial = {kind:frappe.db.count(kind) for kind in ('Sales Order','Sales Invoice','Purchase Order','Purchase Invoice','Journal Entry','Payment Entry','Cipher Award Handoff')}
        result=self.status('Completed')
        doc=frappe.get_doc('Task',self.task['id'])
        self.assertEqual((doc.status,doc.progress,doc.completed_by),('Completed',100,self.primary))
        self.assertTrue(doc.completed_on)
        self.assertEqual(result['task']['assignees'],[])
        self.assertEqual(self.todos()[0].status,'Closed')
        self.assertFalse(doc.get('_assign'))
        self.assertEqual(frappe.db.get_value('Project',self.project,['status','percent_complete'],as_dict=True),before)
        self.assertEqual({kind:frappe.db.count(kind) for kind in financial},financial)

    def test_reopen_clears_native_completion_and_does_not_reactivate_assignment(self):
        self.assign();self.status('Completed');result=self.status('Open')
        doc=frappe.get_doc('Task',self.task['id'])
        self.assertEqual((doc.status,doc.progress),('Open',0))
        self.assertFalse(doc.completed_by);self.assertFalse(doc.completed_on)
        self.assertEqual(result['task']['assignees'],[])
        self.assertEqual(self.todos()[0].status,'Closed')

    def test_completion_dependency_is_checked_before_closing_assignment(self):
        self.assign()
        other=service.create_task(self.company,self.project,self.uid(),service.read_project(self.company,self.project)['version'],'Dependency '+self.uid())['task']
        with trusted_write():
            doc=frappe.get_doc('Task',self.task['id']);doc.append('depends_on',{'task':other['id']});doc.flags.from_project=True;doc.flags.ignore_reschedule=True;doc.save(ignore_permissions=True)
        self.assert_code('task_dependency_open',lambda:self.status('Completed'))
        self.assertEqual(self.todos()[0].status,'Open')
        self.assertEqual(frappe.db.get_value('Task',self.task['id'],'status'),'Open')

    def test_status_and_completion_do_not_reschedule_native_dependent_tasks(self):
        end=frappe.utils.add_days(frappe.utils.nowdate(),10)
        dependent=service.create_task(self.company,self.project,self.uid(),service.read_project(self.company,self.project)['version'],'Dependent '+self.uid())['task']
        with trusted_write():
            target=frappe.get_doc('Task',self.task['id']);target.exp_end_date=end;target.flags.from_project=True;target.flags.ignore_reschedule=True;target.save(ignore_permissions=True)
            doc=frappe.get_doc('Task',dependent['id']);doc.exp_start_date=frappe.utils.add_days(end,-3);doc.exp_end_date=frappe.utils.add_days(end,-1);doc.append('depends_on',{'task':target.name});doc.flags.from_project=True;doc.flags.ignore_reschedule=True;doc.save(ignore_permissions=True)
        before=frappe.db.get_value('Task',dependent['id'],['exp_start_date','exp_end_date','modified'],as_dict=True)
        self.status('Working');self.status('Completed')
        self.assertEqual(frappe.db.get_value('Task',dependent['id'],['exp_start_date','exp_end_date','modified'],as_dict=True),before)

    def test_native_endpoint_target_does_not_collide_with_session_authority_protection(self):
        from cipher_aec.api import v1
        from werkzeug.wrappers import Request
        old_request=getattr(frappe.local,'request',None)
        old_form=getattr(frappe.local,'form_dict',None)
        request=self.assign_request();request['assignee_person']=request.pop('person')
        try:
            frappe.local.request=Request.from_values(method='POST',headers={'Idempotency-Key':request['operation_id']})
            frappe.local.form_dict=frappe._dict(request)
            result=v1.assign_task(**request)
            self.assertNotIn('error',result)
            self.assertEqual(result['data']['task']['assignees'][0]['id'],self.person)
            request.update(assignee_person=None,expected_version=result['data']['task']['version'],operation_id=self.uid())
            frappe.local.request=Request.from_values(method='POST',headers={'Idempotency-Key':request['operation_id']})
            frappe.local.form_dict=frappe._dict(request)
            result=v1.assign_task(**request)
            self.assertNotIn('error',result)
            self.assertEqual(result['data']['task']['assignees'],[])
        finally:
            frappe.local.request=old_request
            frappe.local.form_dict=old_form

    def test_unexplained_native_assignment_is_preserved_by_refusal(self):
        with trusted_write():
            todo=frappe.get_doc({'doctype':'ToDo','allocated_to':self.primary,'assigned_by':self.primary,'reference_type':'Task','reference_name':self.task['id'],'description':'Unmanaged native assignment','status':'Open'}).insert(ignore_permissions=True)
        self.assertTrue(tasks.read_task(self.company,self.project,self.task['id'])['assignment_conflict'])
        self.assert_code('assignment_conflict',lambda:self.assign())
        self.assert_code('assignment_conflict',lambda:self.status('Completed'))
        self.assertEqual(frappe.db.get_value('ToDo',todo.name,'status'),'Open')

    def test_native_assignment_save_cancel_and_reference_removal_cannot_bypass_governance(self):
        self.assign();identifier=self.todos()[0].name
        for fields in ({'status':'Closed'},{'status':'Cancelled'},{'reference_type':None,'reference_name':None}):
            todo=frappe.get_doc('ToDo',identifier)
            todo.update(fields)
            self.assert_code('governed_write_required',lambda:todo.save(ignore_permissions=True))
        self.assertEqual(frappe.db.get_value('ToDo',identifier,'status'),'Open')
        self.assert_code('governed_write_required',lambda:frappe.delete_doc('ToDo',identifier,ignore_permissions=True))

    def test_native_assignment_helper_cannot_bypass_and_unrelated_todo_still_works(self):
        from frappe.desk.form.assign_to import add
        self.assert_code('governed_write_required',lambda:add({'doctype':'Task','name':self.task['id'],'assign_to':[self.primary],'description':'Bypass'}))
        todo=frappe.get_doc({'doctype':'ToDo','allocated_to':self.primary,'assigned_by':self.primary,'description':'Unrelated personal reminder','status':'Open'}).insert(ignore_permissions=True)
        todo.status='Closed';todo.save(ignore_permissions=True)
        self.assertEqual(frappe.db.get_value('ToDo',todo.name,'status'),'Closed')

    def test_missing_task_duties_and_project_revocation_fail_current_access(self):
        request=self.assign_request();result=tasks.assign_task(**request)
        frappe.set_user('Administrator');set_synthetic_duty(self.primary,self.project,'task.assign',0);frappe.set_user(self.primary)
        self.assert_code('capability_denied',lambda:tasks.assign_task(**request))
        self.assertEqual(tasks.task_choices(self.company,self.project)['people'],[])
        frappe.set_user('Administrator');set_synthetic_duty(self.primary,self.project,'project.read',0);frappe.set_user(self.primary)
        self.assert_code('not_found',lambda:tasks.read_task(self.company,self.project,self.task['id']))
        self.assert_code('not_found',lambda:read_operation(self.company,self.project,result['operation']['id']))

    def test_native_task_resources_cannot_disclose_assignment_user_or_todo_to_product_callers(self):
        from cipher_aec.api.boundary import allowed_request
        self.assign()
        self.assertFalse(allowed_request('/api/resource/Task','GET'))
        self.assertFalse(allowed_request('/api/resource/Task/'+self.task['id'],'GET'))
        self.assertFalse(allowed_request('/api/resource/%54ask/'+self.task['id'],'GET'))
        self.assertTrue(allowed_request('/api/method/cipher_aec.api.v1.task','GET'))
        value=tasks.read_task(self.company,self.project,self.task['id'])
        self.assertNotIn('cipher_assignee_user',value)
        self.assertNotIn('cipher_assignment_todo',value)
        self.assertNotIn('_assign',value)
        self.assertEqual(set(value['assignees'][0]),{'id','display_name'})

    def test_other_project_task_is_not_disclosed(self):
        self.assert_code('not_found',lambda:tasks.read_task(self.company,self.fixture['other_project'],self.task['id']))
        frappe.set_user(self.outsider)
        self.assert_code('not_found',lambda:tasks.read_task(self.company,self.fixture['other_project'],self.task['id']))

    def test_closed_project_allows_original_retry_but_refuses_fresh_task_effects(self):
        request=self.assign_request();result=tasks.assign_task(**request)
        frappe.db.set_value('Project',self.project,'status','Cancelled')
        self.assertEqual(tasks.assign_task(**request)['task'],result['task'])
        self.assert_code('project_closed',lambda:self.status('Working'))
        new={**request,'operation_id':self.uid(),'person':None,'expected_version':result['task']['version']}
        self.assert_code('project_closed',lambda:tasks.assign_task(**new))

    def test_late_history_failure_rolls_back_native_todo_task_and_receipt(self):
        request=self.assign_request();before=tasks.read_task(self.company,self.project,self.task['id'])
        with patch.object(tasks,'append_event',side_effect=DomainError('fault','Injected post-save failure',409)):
            self.assert_code('fault',lambda:tasks.assign_task(**request))
        self.assertEqual(self.todos(),[])
        self.assertEqual(tasks.read_task(self.company,self.project,self.task['id']),before)
        receipt=digest({'person':self.person,'operation_id':request['operation_id']})
        self.assertFalse(frappe.db.exists('Cipher Command Receipt',receipt))

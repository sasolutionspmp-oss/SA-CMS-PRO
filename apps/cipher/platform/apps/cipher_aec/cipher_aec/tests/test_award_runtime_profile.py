"""Pinned loaded and fresh callback configurations must both be callback-free."""
from contextlib import ExitStack
import logging
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from cipher_aec.api.errors import DomainError
from cipher_aec.awards import runtime_profile as profile


class AwardRuntimeProfile(TestCase):
    def setUp(self):
        self.loaded={'cipher_award_native_profile':profile.PROFILE,'disable_global_search':True}
        self.fresh=dict(self.loaded);self.common={};self.safe_enabled=False
        self.active={};self.missing=set();self.missing_fields=set();self.follow_fresh=0;self.follow_cached=0;self.preference_calls=[];self.price_fresh=0;self.price_cached=0;self.stock_calls=[]
        self.webhooks={};self.scripts={'permission_query':{}}
        self.notifications={};self.assignments={};self.workflows={};self.automations={};self.milestones={};self.sla_targets=frozenset();self.user_types={};self.target_fields={target:[] for target in profile.TARGETS};self.track_changes={};self.calls=[]
        fields={dt:{field,*flags} for dt,field,flags in profile.CONFIGURATIONS}
        def exists(doctype,filters):
            self.calls.append(('exists',doctype,filters))
            if doctype=='DocType':return filters not in self.missing
            return bool(set(self.active.get(doctype,())) & set(profile.TARGETS))
        def cached(key,generator):
            self.calls.append(('catalog',key))
            if key=='webhooks':return self.webhooks
            self.assertTrue(key.startswith('notifications::'))
            target=key.removeprefix('notifications::')
            return self.notifications[target] if target in self.notifications else generator()
        fake=SimpleNamespace(conf=self.loaded,flags={},session=SimpleNamespace(user='exact-executor@example.test'),
            db=SimpleNamespace(exists=exists,get_value=lambda dt,user,field:self.user_preference('fresh',dt,user,field),
                get_single_value=lambda dt,field,**kwargs:self.stock_setting('fresh',dt,field,kwargs)),
            get_cached_doc=lambda dt:{'auto_insert_price_list_rate_if_missing':self.stock_setting('cached',dt,'auto_insert_price_list_rate_if_missing',{})},
            get_cached_value=lambda dt,user,field:self.user_preference('cached',dt,user,field),
            get_meta=lambda dt:SimpleNamespace(has_field=lambda field:field in fields.get(dt,set()) and (dt,field) not in self.missing_fields,
                get=lambda key:self.target_fields.get(dt,[]) if key=='fields' else self.track_changes.get(dt,0)),
            cache=SimpleNamespace(get_value=lambda key,generator:self.user_types),
            get_common_site_config=lambda *,cached:self.fresh_common(cached),
            get_all=lambda dt,**kwargs:self.native_get_all(dt,kwargs),client_cache=SimpleNamespace(get_value=cached))
        stack=ExitStack();self.addCleanup(stack.close)
        # Native safe_exec imports PDF logging; unit fixtures must not require a bench cwd/site.
        stack.enter_context(patch('frappe.logger',return_value=logging.getLogger('cipher-award-profile-unit')))
        stack.enter_context(patch.object(profile,'frappe',fake))
        stack.enter_context(patch('frappe.config.get_site_config',side_effect=lambda *,cached:self.fresh_site(cached)))
        stack.enter_context(patch('frappe.utils.safe_exec.is_safe_exec_enabled',side_effect=lambda:self.safe_enabled))
        stack.enter_context(patch('frappe.cache_manager.get_doctype_map',side_effect=lambda dt,name,**kwargs:self.map_lookup(dt,name,kwargs)))
        stack.enter_context(patch('frappe.model.workflow.get_workflow_name',side_effect=lambda dt:self.workflows.get(dt,'')))
        stack.enter_context(patch('frappe.integrations.doctype.webhook.get_all_webhooks',return_value={}))
        stack.enter_context(patch('frappe.core.doctype.server_script.server_script_utils.get_server_script_map',side_effect=lambda:self.scripts))
        stack.enter_context(patch('frappe.automation_engine.registry.get_automations_for',side_effect=lambda dt:self.automations.get(dt,[])))
        stack.enter_context(patch('frappe.automation.doctype.milestone_tracker.milestone_tracker.get_milestone_trackers',side_effect=lambda dt:self.milestones.get(dt,[])))
        stack.enter_context(patch('erpnext.support.doctype.service_level_agreement.service_level_agreement.get_documents_with_active_service_level_agreement',side_effect=lambda:self.sla_targets))
        stack.enter_context(patch('frappe.core.doctype.user_type.user_type.get_non_standard_user_types',return_value={}))

    def stock_setting(self,kind,doctype,field,kwargs):
        self.assertEqual((doctype,field),('Stock Settings','auto_insert_price_list_rate_if_missing'))
        self.assertEqual(kwargs,{'cache':False} if kind=='fresh' else {})
        self.stock_calls.append(kind)
        return self.price_fresh if kind=='fresh' else self.price_cached

    def user_preference(self,kind,doctype,user,field):
        self.assertEqual((doctype,user,field),('User','exact-executor@example.test','follow_created_documents'))
        self.preference_calls.append(kind)
        return self.follow_fresh if kind=='fresh' else self.follow_cached

    def fresh_common(self,cached):
        self.assertIs(cached,False);return self.common

    def fresh_site(self,cached):
        self.assertIs(cached,False);return self.fresh

    def native_get_all(self,doctype,kwargs):
        self.assertEqual(doctype,'Notification')
        self.assertEqual(kwargs['fields'],['name','event','method'])
        self.assertIn(kwargs['filters']['document_type'],profile.TARGETS)
        self.assertEqual(kwargs['filters']['enabled'],1)
        return []

    def map_lookup(self,doctype,name,kwargs):
        self.assertEqual(doctype,'Assignment Rule')
        self.assertIn(kwargs['filters']['document_type'],profile.TARGETS)
        self.assertEqual(kwargs['filters']['disabled'],0)
        if name.startswith('due_date_rules_for_'):self.assertEqual(kwargs['filters']['due_date_based_on'],['is','set'])
        else:self.assertEqual(kwargs['order_by'],'priority desc')
        return self.assignments.get(name,[])

    def denied(self):
        with self.assertRaises(DomainError) as error:profile.require_native_profile()
        self.assertEqual(error.exception.code,'award_native_profile_unqualified');self.assertEqual(error.exception.status,503)

    def test_selected_profile_returns_static_policy_without_writes_cleanup_or_authority(self):
        actual=profile.require_native_profile()
        self.assertEqual(actual,{'profile':profile.PROFILE,'disable_global_search':True,'native_notify_update':False,'external_callbacks':False})
        self.assertEqual(len([call for call in self.calls if call[0]=='catalog']),1+len(profile.TARGETS))
        self.assertEqual(len([call for call in self.calls if call[0]=='exists']),18)

    def test_loaded_and_fresh_indexing_profile_must_each_match_typed_selection(self):
        for config,key,value in ((self.loaded,'disable_global_search',False),(self.fresh,'disable_global_search',False),
            (self.loaded,'disable_global_search','1'),(self.fresh,'cipher_award_native_profile','caller-selected')):
            old=config[key];config[key]=value
            try:
                with self.subTest(key=key,value=value):self.denied()
            finally:config[key]=old

    def test_common_server_script_authority_cannot_be_hidden_by_false_site_override(self):
        self.loaded['server_script_enabled']=False;self.fresh['server_script_enabled']=False
        self.safe_enabled=True;self.denied()
        self.safe_enabled=False;self.common['server_script_enabled']=True;self.denied()
        self.common['server_script_enabled']='0';self.denied()  # native bool('0') also enables scripting
        self.common['server_script_enabled']=False;profile.require_native_profile()

    def test_install_migrate_and_import_flags_cannot_substitute_for_runtime_profile(self):
        for flag in ('in_install','in_migrate','in_patch','in_import','in_setup_wizard'):
            profile.frappe.flags[flag]=True
            try:
                with self.subTest(flag=flag):self.denied()
            finally:profile.frappe.flags.pop(flag)

    def test_each_fresh_target_callback_refuses_before_catalog_dispatch(self):
        for doctype,field,active in profile.CONFIGURATIONS:
            self.active[doctype]={'Project'};self.calls.clear()
            try:
                with self.subTest(doctype=doctype):self.denied()
                self.assertFalse(any(call[0]=='catalog' for call in self.calls))
            finally:self.active.clear()

    def test_other_doctype_callbacks_do_not_create_a_site_wide_callback_ban(self):
        self.active={doctype:{'Other Doctype'} for doctype,field,active in profile.CONFIGURATIONS}
        self.webhooks={'Other Doctype':[{'name':'other'}]};self.scripts={'Other Doctype':{'Before Insert':['other']}}
        profile.require_native_profile()

    def test_stale_notification_catalog_refuses_even_when_current_rows_disabled(self):
        for target in profile.TARGETS:
            self.notifications[target]=[{'name':'previously-enabled','event':'Method','method':'before_insert'}]
            try:
                with self.subTest(target=target):self.denied()
            finally:self.notifications.clear()

    def test_stale_assignment_and_due_date_catalogs_each_refuse(self):
        for key in ('Project','Sales Order','due_date_rules_for_Project','due_date_rules_for_Sales Order'):
            self.assignments[key]=[{'name':'previously-enabled'}]
            try:
                with self.subTest(key=key):self.denied()
            finally:self.assignments.clear()

    def test_stale_workflow_name_refuses_without_creating_any_workflow_action(self):
        self.workflows['Project']='Previous active workflow';self.denied()

    def test_stale_webhook_catalog_refuses_without_emitting_or_populating_local_queue(self):
        self.webhooks={'Sales Order':[{'name':'previously-enabled','webhook_docevent':'after_insert'}]};self.denied()

    def test_loaded_server_script_event_refuses_even_while_runtime_scripting_disabled(self):
        self.scripts={'permission_query':{},'Project':{'Before Insert':['previously-enabled']}};self.denied()

    def test_stale_document_automation_catalog_refuses_even_when_fresh_rows_disabled(self):
        self.automations['Project']=[{'name':'previously-enabled','trigger_type':'Doc Created'}];self.denied()

    def test_missing_schema_malformed_catalog_and_helper_failure_are_fail_closed(self):
        self.missing.add('Automation Flow');self.denied();self.missing.clear()
        self.missing_fields.add(('Server Script','script_type'));self.denied();self.missing_fields.clear()
        self.webhooks=[];self.denied();self.webhooks={}
        self.notifications['Project']=None;self.denied();self.notifications.clear()
        with patch('frappe.automation_engine.registry.get_automations_for',side_effect=RuntimeError('Catalog unavailable')):self.denied()

    def test_stale_milestone_tracker_refuses_before_inserting_cascaded_milestone(self):
        self.milestones['Project']=[{'name':'previously-enabled'}];self.denied()

    def test_effective_sla_catalog_including_disabled_rows_refuses_without_assuming_noop(self):
        self.sla_targets=frozenset({'Sales Order'});self.denied()
        self.sla_targets={'Other Doctype'};profile.require_native_profile()
        self.sla_targets='Project';self.denied()
        self.sla_targets=frozenset();self.active['Service Level Agreement']={'Project'};self.calls.clear();self.denied()
        query=next(call[2] for call in self.calls if call[:2]==('exists','Service Level Agreement'))
        self.assertNotIn('enabled',query)

    def test_fresh_and_stale_nonstandard_target_user_type_mappings_refuse_role_mutation(self):
        self.active['User Type']={'Project'};self.denied();self.active.clear()
        self.user_types={'Previously configured':['Sales Order','user_field']};self.denied()
        self.user_types={'Unrelated':['Other Doctype','user_field']};profile.require_native_profile()

    def test_effective_parent_attach_metadata_refuses_file_hook_before_insert(self):
        for target,fieldtype in (('Project','Attach'),('Sales Order','Attach Image')):
            self.target_fields[target]=[{'fieldname':'custom_native_attachment','fieldtype':fieldtype}]
            try:
                with self.subTest(target=target,fieldtype=fieldtype):self.denied()
            finally:self.target_fields[target]=[]
        self.target_fields['Other Doctype']=[{'fieldname':'unrelated','fieldtype':'Attach'}]
        profile.require_native_profile()

    def test_all_literal_transitive_writes_refuse_fresh_and_effective_callbacks(self):
        self.assertEqual(len(profile.TARGETS),14)
        for target in profile.CIPHER_TARGETS:
            for doctype,field,active in profile.CONFIGURATIONS:
                self.active[doctype]={target}
                try:
                    with self.subTest(target=target,doctype=doctype):self.denied()
                finally:self.active.clear()
            self.notifications[target]=[{'name':'synchronous callback','event':'Method','method':'before_insert'}]
            try:
                with self.subTest(target=target):self.denied()
            finally:self.notifications.clear()

    def test_each_cipher_target_refuses_transitive_version_or_attach_fields(self):
        for target in profile.CIPHER_TARGETS:
            self.track_changes[target]=1
            try:
                with self.subTest(target=target,kind='Version'):self.denied()
            finally:self.track_changes.clear()
            self.target_fields[target]=[{'fieldname':'custom_attachment','fieldtype':'Attach'}]
            try:
                with self.subTest(target=target,kind='Attach'):self.denied()
            finally:self.target_fields[target]=[]
        # The derived native SO save has its own narrow ignore_version boundary.
        self.track_changes['Sales Order']=1
        profile.require_native_profile()

    def test_exact_executor_fresh_and_actual_cached_follow_preference_must_both_be_false(self):
        for key in ('follow_fresh','follow_cached'):
            for value in (1,True,None,'0',[],{}):
                setattr(self,key,value)
                try:
                    with self.subTest(key=key,value=value):self.denied()
                finally:setattr(self,key,0)
        self.preference_calls.clear();profile.require_native_profile()
        self.assertEqual(self.preference_calls,['fresh','cached'])

    def test_automatic_item_price_insert_and_update_gate_fresh_and_cached_false(self):
        for key in ('price_fresh','price_cached'):
            for value in (1,True,None,'0',[],{}):
                setattr(self,key,value)
                try:
                    with self.subTest(key=key,value=value):self.denied()
                finally:setattr(self,key,0)
        self.stock_calls.clear();profile.require_native_profile()
        self.assertEqual(self.stock_calls,['fresh','cached'])

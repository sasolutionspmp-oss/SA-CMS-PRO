"""Fresh exact Company SQL, identity ambiguity and native boundary parity."""
import sqlite3
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
from cipher_aec.api.errors import DomainError
from cipher_aec.governance import context,permissions


class CompanyAuthoritySQLTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:');self.db.row_factory=sqlite3.Row;self.addCleanup(self.db.close)
        for sql in ('CREATE TABLE `tabCipher Person` (name TEXT,display_name TEXT,active INT)',
            'CREATE TABLE `tabUser` (name TEXT,enabled INT)',
            'CREATE TABLE `tabCipher Identity Binding` (name TEXT,person TEXT,user TEXT,active INT)',
            'CREATE TABLE `tabCipher Project Duty` (person TEXT,company TEXT,scope_type TEXT,project TEXT,active INT,valid_from TEXT,valid_until TEXT,ability TEXT)'):self.db.execute(sql)
        self.db.execute("INSERT INTO `tabCipher Person` VALUES ('person','Author',1)")
        for user in ('author','alias'):
            self.db.execute('INSERT INTO `tabUser` VALUES (?,1)',(user,));self.db.execute('INSERT INTO `tabCipher Identity Binding` VALUES (?,?,?,1)',(user,'person',user))
        self.duty('company.read');self.duty('commercial.read')
        self.queries=[];self.native=True
        def sql(statement,args,**kw):
            self.queries.append(statement)
            return [SimpleNamespace(**dict(r)) for r in self.db.execute(statement.replace('%s','?'),args).fetchall()]
        self.record=SimpleNamespace(doctype='Company',name='Company A');self.missing=type('Missing',(Exception,),{})
        self.fake=SimpleNamespace(db=SimpleNamespace(sql=Mock(side_effect=sql),transaction_writes=0),session=SimpleNamespace(user='author'),
            get_doc=Mock(return_value=self.record),DoesNotExistError=self.missing,
            has_permission=Mock(side_effect=lambda *a,**kw:self.native and permissions.company_permission(kw['doc'],user=kw['user'])))
        for p in (patch.object(context,'frappe',self.fake),patch.object(context,'nowdate',return_value='2026-10-15')):
            p.start();self.addCleanup(p.stop)

    def duty(self,ability,*,company='Company A',scope='Company',project=None,active=1,start=None,end=None):
        self.db.execute('INSERT INTO `tabCipher Project Duty` VALUES (?,?,?,?,?,?,?,?)',('person',company,scope,project,active,start,end,ability))

    def error(self,code,**kw):
        with self.assertRaises(DomainError) as e:context.require_company('Company A',**kw)
        self.assertEqual(e.exception.code,code);return e.exception

    def test_actor_none_and_alias_get_real_doc_with_one_fresh_authority_query_each(self):
        self.assertIs(context.require_company('Company A',ability='commercial.read'),self.record)
        self.assertEqual(len(self.queries),1);self.assertTrue(all('FOR UPDATE' not in q for q in self.queries))
        alias=context.Actor('alias','person','Alias')
        self.assertIs(context.require_company('Company A',ability='commercial.read',actor=alias),self.record)
        self.assertEqual(len(self.queries),2)
        self.fake.has_permission.assert_called_with('Company',ptype='read',doc=self.record,user='alias')

    def test_native_denial_is_not_overridden_by_cipher_duties(self):
        self.native=False;self.assertEqual(self.error('not_found').status,404)
        self.fake.has_permission.assert_called_once()

    def test_guest_and_unconfigured_identity_errors_precede_doc_access(self):
        self.fake.session.user='Guest';self.assertEqual(self.error('authentication_required').status,401)
        self.fake.session.user='unknown';self.assertEqual(self.error('identity_unavailable').status,403)
        self.fake.get_doc.assert_not_called()

    def test_inactive_person_binding_or_user_refuses_current_identity(self):
        for table,field,where in (('tabCipher Person','active',"name='person'"),('tabCipher Identity Binding','active',"user='author'"),('tabUser','enabled',"name='author'")):
            with self.subTest(table=table):
                self.db.execute(f'UPDATE `{table}` SET {field}=0 WHERE {where}');self.error('identity_unavailable')
                self.db.execute(f'UPDATE `{table}` SET {field}=1 WHERE {where}')

    def test_duplicate_active_binding_ambiguity_even_same_person_is_denied(self):
        self.db.execute("INSERT INTO `tabCipher Identity Binding` VALUES ('duplicate','person','author',1)")
        self.error('identity_unavailable');self.fake.get_doc.assert_not_called()

    def test_duplicate_duties_do_not_multiply_identity(self):
        self.duty('company.read');self.duty('commercial.read')
        actor,read,act=context.read_company_authority('author','Company A','commercial.read')
        self.assertEqual(actor.person_id,'person');self.assertTrue(read and act)

    def test_supplied_actor_person_mismatch_refuses_before_company(self):
        self.error('identity_changed',actor=context.Actor('author','someone-else','Forged'))
        self.fake.get_doc.assert_not_called()

    def test_absent_company_precedes_capability_error(self):
        self.db.execute('DELETE FROM `tabCipher Project Duty`');self.fake.get_doc.side_effect=self.missing()
        self.error('not_found');self.fake.has_permission.assert_not_called()

    def test_scope_and_date_predicates_never_inherit_other_duties(self):
        self.db.execute("DELETE FROM `tabCipher Project Duty` WHERE ability='commercial.read'")
        self.duty('commercial.read',scope='Project',project='real');self.duty('commercial.read',project='malformed')
        self.duty('commercial.read',company='Other');self.duty('commercial.read',active=0)
        self.duty('commercial.read',start='2026-10-16');self.duty('commercial.read',end='2026-10-14')
        self.error('capability_denied',ability='commercial.read')
        self.duty('commercial.read',start='2026-10-15',end='2026-10-15')
        self.assertIs(context.require_company('Company A',ability='commercial.read'),self.record)

    def test_current_duties_requeried_next_call_and_direct_native_hook_is_exact(self):
        self.assertTrue(permissions.company_permission(self.record,user='author'))
        self.db.execute("DELETE FROM `tabCipher Project Duty` WHERE company='Company A'")
        self.duty('company.read',company='Other')
        self.assertFalse(permissions.company_permission(self.record,user='alias'))
        self.error('not_found')
        self.assertFalse(permissions.company_permission(self.record,user='author',ptype='write'))

    def test_locking_company_branch_keeps_ordered_helpers_and_real_native_boundary(self):
        actor=context.Actor('author','person','Author');self.fake.has_permission.side_effect=None;self.fake.has_permission.return_value=True
        with patch.object(context,'current_actor',return_value=actor) as current,patch.object(context,'company_duty_rows',return_value=[SimpleNamespace(ability='company.read')]) as duties,patch.object(context,'read_company_authority',side_effect=AssertionError('No joined locking admission')):
            self.assertIs(context.require_company('Company A',actor=actor,lock=True),self.record)
        current.assert_called_once_with('author',lock=True);duties.assert_called_once_with(actor,'Company A',lock=True)
        self.fake.get_doc.assert_called_once_with('Company','Company A',for_update=True)

    def test_unknown_capability_and_database_fault_behavior_unchanged(self):
        self.error('unknown_capability',ability='unregistered')
        self.fake.db.sql.assert_not_called()
        self.fake.db.sql.side_effect=RuntimeError('database unavailable')
        with self.assertRaises(RuntimeError):permissions.company_permission(self.record,user='author')

    def test_hook_bridge_is_single_use_and_direct_hook_after_return_requeries(self):
        def native(*args,**kwargs):
            self.assertTrue(permissions.company_permission(kwargs['doc'],user=kwargs['user']))
            return permissions.company_permission(kwargs['doc'],user=kwargs['user'])
        self.fake.has_permission.side_effect=native
        context.require_company('Company A')
        self.assertEqual(len(self.queries),2) # One guard and second hook only.
        self.assertIsNone(context._company_native_read.get())
        self.assertTrue(permissions.company_permission(self.record,user='author'))
        self.assertEqual(len(self.queries),3)

    def test_wrong_doc_company_user_or_permission_spends_bridge_and_rechecks_sql(self):
        for altered in ({'doc':SimpleNamespace(doctype='Company',name='Company A')},
                        {'doc':SimpleNamespace(doctype='Company',name='Other')},
                        {'user':'alias'},{'user':None},{'ptype':'select'}):
            self.queries.clear()
            def native(*args,**kwargs):
                values={'doc':kwargs['doc'],'user':kwargs['user'],'ptype':'read',**altered}
                permissions.company_permission(**values)
                return permissions.company_permission(kwargs['doc'],user=kwargs['user'])
            self.fake.has_permission.side_effect=native
            with self.subTest(altered=altered):
                context.require_company('Company A')
                self.assertEqual(len(self.queries),3)
                self.assertIsNone(context._company_native_read.get())

    def test_mutated_person_or_doctype_cannot_consume_bridge(self):
        actor=SimpleNamespace(user='author',person_id='person',display_name='Author')
        def native(*args,**kwargs):
            actor.person_id='changed'
            return permissions.company_permission(kwargs['doc'],user=kwargs['user'])
        self.fake.has_permission.side_effect=native
        context.require_company('Company A',actor=actor)
        self.assertEqual(len(self.queries),2)
        self.queries.clear();actor.person_id='person'
        def changed_type(*args,**kwargs):
            kwargs['doc'].doctype='Other'
            return permissions.company_permission(kwargs['doc'],user=kwargs['user'])
        self.fake.has_permission.side_effect=changed_type
        context.require_company('Company A',actor=actor)
        self.assertEqual(len(self.queries),2)

    def test_native_engine_denial_after_successful_hook_is_authoritative(self):
        def native(*args,**kwargs):
            self.assertTrue(permissions.company_permission(kwargs['doc'],user=kwargs['user']))
            return False
        self.fake.has_permission.side_effect=native
        self.error('not_found')
        self.assertEqual(len(self.queries),1)
        self.assertIsNone(context._company_native_read.get())
        self.assertTrue(permissions.company_permission(self.record,user='author'))
        self.assertEqual(len(self.queries),2)

    def test_native_engine_exception_clears_unspent_bridge(self):
        self.fake.has_permission.side_effect=RuntimeError('Native engine failed')
        with self.assertRaisesRegex(RuntimeError,'Native engine failed'):
            context.require_company('Company A')
        self.assertIsNone(context._company_native_read.get())
        self.assertTrue(permissions.company_permission(self.record,user='author'))
        self.assertEqual(len(self.queries),2)

    def test_next_independent_guard_rechecks_revoked_identity_and_duty(self):
        context.require_company('Company A')
        self.db.execute("UPDATE `tabUser` SET enabled=0 WHERE name='author'")
        self.error('identity_unavailable')
        self.assertEqual(len(self.queries),2)
        self.db.execute("UPDATE `tabUser` SET enabled=1 WHERE name='author'")
        self.db.execute("DELETE FROM `tabCipher Project Duty` WHERE ability='company.read'")
        self.error('not_found')
        self.assertEqual(len(self.queries),3)
        self.fake.has_permission.assert_called_once()

    def test_business_date_rollover_uses_new_day_fresh_hook_sql(self):
        with patch.object(context,'nowdate',return_value='2026-10-15') as day:
            def native(*args,**kwargs):
                day.return_value='2026-10-16'
                return permissions.company_permission(kwargs['doc'],user=kwargs['user'])
            self.fake.has_permission.side_effect=native
            context.require_company('Company A')
        self.assertEqual(len(self.queries),2)
        self.assertEqual(self.fake.db.sql.call_args.args[1][1:3],('2026-10-16','2026-10-16'))

    def test_native_write_or_database_swap_forces_fresh_hook_sql(self):
        original_db=self.fake.db
        for change in ('write','swap'):
            self.fake.db=original_db;self.fake.db.transaction_writes=0;self.queries.clear()
            def native(*args,**kwargs):
                if change=='write':self.fake.db.transaction_writes+=1
                else:self.fake.db=SimpleNamespace(sql=original_db.sql,transaction_writes=0)
                return permissions.company_permission(kwargs['doc'],user=kwargs['user'])
            self.fake.has_permission.side_effect=native
            with self.subTest(change=change):
                context.require_company('Company A')
                self.assertEqual(len(self.queries),2)
                self.assertIsNone(context._company_native_read.get())
        self.fake.db=original_db

    def test_nested_native_write_revoking_duty_denies_the_same_guard(self):
        def native(*args,**kwargs):
            self.db.execute("DELETE FROM `tabCipher Project Duty` WHERE ability='company.read'")
            self.fake.db.transaction_writes+=1
            return permissions.company_permission(kwargs['doc'],user=kwargs['user'])
        self.fake.has_permission.side_effect=native
        self.error('not_found')
        self.assertEqual(len(self.queries),2)
        self.assertIsNone(context._company_native_read.get())

    def test_nested_guard_masks_parent_bridge_and_runs_its_own_sql(self):
        depth=0
        alias=context.Actor('alias','person','Alias')
        def native(*args,**kwargs):
            nonlocal depth
            if depth==0:
                depth+=1
                context.require_company('Company A',actor=alias)
                depth-=1
            return permissions.company_permission(kwargs['doc'],user=kwargs['user'])
        self.fake.has_permission.side_effect=native
        context.require_company('Company A')
        self.assertEqual(len(self.queries),2)
        self.assertEqual(self.fake.has_permission.call_count,2)
        self.assertIsNone(context._company_native_read.get())

    def test_stable_frappe_db_proxy_cannot_hide_changed_real_local_database(self):
        original=self.fake.db
        self.fake.local=SimpleNamespace(db=original)
        def native(*args,**kwargs):
            self.fake.local.db=SimpleNamespace(transaction_writes=0)
            return permissions.company_permission(kwargs['doc'],user=kwargs['user'])
        self.fake.has_permission.side_effect=native
        context.require_company('Company A')
        self.assertIs(self.fake.db,original)
        self.assertEqual(len(self.queries),2)
        self.assertIsNone(context._company_native_read.get())

    def test_nested_locked_guard_cannot_inherit_outer_nonlocking_bridge(self):
        depth=0;actor=context.Actor('author','person','Author')
        def native(*args,**kwargs):
            nonlocal depth
            if depth==0:
                depth+=1
                context.require_company('Company A',actor=actor,lock=True)
                depth-=1
            return permissions.company_permission(kwargs['doc'],user=kwargs['user'])
        self.fake.has_permission.side_effect=native
        with patch.object(context,'current_actor',return_value=actor),patch.object(context,'company_duty_rows',return_value=[SimpleNamespace(ability='company.read')]):
            context.require_company('Company A',actor=actor)
        self.assertEqual(len(self.queries),2) # Outer fresh guard + locked native hook.
        self.assertEqual(self.fake.has_permission.call_count,2)
        self.assertIsNone(context._company_native_read.get())

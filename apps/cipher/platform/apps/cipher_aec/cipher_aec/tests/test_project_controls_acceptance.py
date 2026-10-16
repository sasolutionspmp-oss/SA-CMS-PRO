"""Explicit synthetic native master qualification; no award writer or posting.

Canonical fresh-site entry has no fixture-path/default-user dependency. It uses
its own Company/identities and existing ERP-generated accounting masters.
"""
from copy import deepcopy
from uuid import uuid4


def run_acceptance():
    import frappe
    from frappe.permissions import add_permission, update_permission_property
    from cipher_aec.api.contracts import digest
    from cipher_aec.api.errors import DomainError
    from cipher_aec.governance.context import assert_synthetic_site,current_actor,trusted_write
    from cipher_aec.governance.commands import read_company_operation
    from cipher_aec.install import _grant_company,_grant,set_synthetic_duty
    from cipher_aec.tests.test_commercial_acceptance import setup_fixture
    from cipher_aec.project_controls import masters,service,repository
    from cipher_aec.project_controls.adoption import create_initial_adoption
    from cipher_aec.estimating import scopes
    from cipher_aec.estimating.lockplan import prepared
    from cipher_aec.documents.provenance import is_prelocked
    assert_synthetic_site()
    if frappe.session.user!='Administrator':raise RuntimeError('Start synthetic controls acceptance as bench Administrator.')
    fixture=setup_fixture();company=fixture['company'];checks=[]
    with trusted_write():
        for ability in ('project.cost.read','project.cost.write'):_grant_company(fixture['person'],company,ability)
        add_permission('Cost Center',fixture['role'],0)
        update_permission_property('Cost Center',fixture['role'],0,'read',1)
    costs=frappe.db.sql('SELECT name FROM `tabCost Center` WHERE company=%s AND is_group=0 AND disabled=0 ORDER BY name LIMIT 1',(company,))
    accounts=frappe.db.sql("SELECT name FROM `tabAccount` WHERE company=%s AND is_group=0 AND disabled=0 AND root_type='Expense' ORDER BY name LIMIT 2",(company,))
    assert costs and len(accounts)>=2,'Supported Company fixture must create actual leaf accounting targets.'
    cost,account=costs[0][0],accounts[0][0]
    frappe.db.commit();frappe.clear_cache(user=fixture['user']);frappe.clear_cache(user=fixture['alias'])
    native_before={name:frappe.db.count(name) for name in ('Cost Center','Account','Sales Order','Budget','GL Entry')}
    def denied(callback,codes):
        try:callback()
        except DomainError as error:
            assert error.code in codes,(error.code,codes)
            frappe.db.rollback();return error.code
        raise AssertionError('Expected exact controls denial')
    def resolve(kind,revision,day='2026-10-15',**kwargs):
        return masters.resolve_revision(actor=current_actor(),company=company,kind=kind,revision_id=revision,basis_date=day,purpose='award.initial-budget.v1',**kwargs)
    try:
        frappe.set_user(fixture['user'])
        definition={'title':'Exact existing leaf cost center','effective_from':'2026-10-15','effective_until':None,'enabled':True,'native_target':{'doctype':'Cost Center','name':cost}}
        operation=str(uuid4());created=masters.create_master(company,operation,'code','WORK',definition);frappe.db.commit()
        revision=created['revision']['id'];original=deepcopy(created)
        assert resolve('code',revision)['revision']==created['revision']
        frappe.set_user(fixture['alias'])
        replay=masters.create_master(company,operation,'code','WORK',definition)
        assert replay['operation']['replayed'] and replay['revision']==created['revision']
        assert read_company_operation(company,operation)['revision']==created['revision']
        changed={**definition,'title':'Changed payload'}
        denied(lambda:masters.create_master(company,operation,'code','WORK',changed),{'operation_conflict'})
        checks.append('company_canonical_master_person_alias_same_uuid_and_changed_payload_conflict')
        alias_target=cost.swapcase()
        if alias_target!=cost:
            denied(lambda:masters.create_master(company,str(uuid4()),'code','CASE-ALIAS',{**definition,'native_target':{'doctype':'Cost Center','name':alias_target}}),{'not_found'})

        denied(lambda:masters.create_master(company,str(uuid4()),'code','work',definition),{'cost_code_exists'})
        other=masters.create_master(company,str(uuid4()),'code','WORK-02',definition);frappe.db.commit()
        page=service.list_masters(company,'code','2026-10-15',limit=1,count_mode='exact')
        assert page['total']==2 and len(page['items'])==1 and page['next_cursor']
        next_page=service.list_masters(company,'code','2026-10-15',limit=1,cursor=page['next_cursor'],count_mode='exact')
        assert next_page['total']==2 and len(next_page['items'])==1 and next_page['items'][0]['master']['id']!=page['items'][0]['master']['id'] and next_page['next_cursor'] is None
        denied(lambda:service.list_masters(company,'code','2026-10-15',limit=1,cursor=page['next_cursor'],count_mode='none'),{'invalid_cursor'})
        denied(lambda:service.list_masters(company,'type','2026-10-15',limit=1,cursor=page['next_cursor'],count_mode='exact'),{'invalid_cursor'})
        checks.append('casefold_identity_uniqueness_sql_keyset_exact_visible_pages_and_signed_count_filter_binding')

        type_definition={**definition,'title':'Exact existing expense accounting target','native_target':{'doctype':'Account','name':account},'cost_category':'material','allocation_class':'component'}
        typed=masters.create_master(company,str(uuid4()),'type','MAT',type_definition);frappe.db.commit()
        prior_authority=run_prior_source_authority(fixture=fixture,typed=typed,other_account=accounts[1][0])
        checks.append('successor_rechecks_prior_authored_currency_and_foreign_company_target_under_complete_union')
        actor=current_actor();plan=masters.plan_resources(actor=actor,company=company,code_revision_ids=[revision],type_revision_ids=[typed['revision']['id']],basis_date='2026-10-15',purpose='award.initial-budget.v1')
        assert not is_prelocked(plan,actor,company)
        denied(lambda:resolve('code',revision,lock=True,resource_token=plan),{'source_prelock_required'})
        from unittest.mock import patch
        import re
        first_native,all_native=[],[]
        sql=frappe.db.sql
        def observed(query,values=(),*args,**kwargs):
            result=sql(query,values,*args,**kwargs)
            query=str(query)
            match=re.search(r'\bFROM\s+`tab(Currency|Account|Cost Center)`(?=\s|$)',query,re.I) if re.search(r'\bFOR\s+UPDATE\b',query,re.I) else None
            if match and result:
                columns=[v[0] for v in frappe.db._cursor.description]
                assert 'name' in columns,query
                for row in result:
                    name=row['name'] if isinstance(row,dict) else row[columns.index('name')]
                    identity=(match.group(1).casefold(),name)
                    all_native.append(identity)
                    if identity not in first_native:first_native.append(identity)
            return result
        with patch.object(frappe.db,'sql',side_effect=observed),scopes.activate('Company',company,None),prepared(plan,actor,company) as token:
            assert resolve('code',revision,lock=True,resource_token=token)['revision']['id']==revision
            assert resolve('type',typed['revision']['id'],lock=True,resource_token=token)['native']['root_type']=='Expense'
        assert first_native==[('currency','USD'),('account',account),('cost center',cost)],first_native
        assert len(all_native)>len(first_native),all_native

        frappe.db.commit()
        checks.append('metadata_plan_does_not_admit_and_complete_outer_native_union_resolves_exact_targets')
        drift=run_account_currency_current_read(company=company,account=account,revision_id=typed['revision']['id'])
        assert drift['status']=='passed' and drift['account_currency_restored']
        checks.append('separate_connection_old_rr_native_account_currency_change_fails_closed_without_late_currency_lock')

        successor={**definition,'effective_from':'2026-11-01','title':'Future successor'}
        revised=masters.revise_master(company,str(uuid4()),'code',created['master']['id'],created['version'],successor);frappe.db.commit()
        assert resolve('code',revision)['revision']==created['revision']
        dated_page=service.list_masters(company,'code','2026-10-15',count_mode='exact')
        dated=next(item for item in dated_page['items'] if item['master']['id']==created['master']['id'])
        assert dated['master']['current_revision']==revised['revision']['id'] and dated['revision']['revision']['id']==revision
        denied(lambda:resolve('code',revision,'2026-11-01'),{'stale_cost_revision'})
        assert resolve('code',revised['revision']['id'],'2026-11-01')['revision']==revised['revision']
        denied(lambda:masters.revise_master(company,str(uuid4()),'code',created['master']['id'],created['version'],successor),{'stale_cost_master'})
        assert service.get_revision(company,'code',revision,'2026-11-01')['revision']==created['revision']
        checks.append('effective_future_successor_stales_new_use_without_rewriting_exact_historical_revision')
        disabled={**definition,'effective_from':'2026-12-01','enabled':False}
        disabled_result=masters.revise_master(company,str(uuid4()),'code',created['master']['id'],revised['version'],disabled);frappe.db.commit()
        denied(lambda:resolve('code',disabled_result['revision']['id'],'2026-12-01'),{'stale_cost_revision'})
        assert read_company_operation(company,operation)['revision']==original['revision']
        checks.append('master_disable_blocks_new_adoption_preserves_original_completed_receipt')
        frappe.set_user('Administrator');native=frappe.get_doc('Cost Center',cost);native.disabled=1;native.save(ignore_permissions=True);frappe.db.commit()
        frappe.set_user(fixture['user'])
        assert service.get_revision(company,'code',revision,'2026-10-15')['revision']==original['revision']
        denied(lambda:resolve('code',revision),{'ineligible_cost_target'})
        assert read_company_operation(company,operation)['revision']==original['revision']
        frappe.set_user('Administrator');native=frappe.get_doc('Cost Center',cost);native.disabled=0;native.save(ignore_permissions=True);frappe.db.commit()
        update_permission_property('Cost Center',fixture['role'],0,'read',0);frappe.db.commit()
        for user in (fixture['user'],fixture['alias']):frappe.clear_cache(user=user)
        frappe.set_user(fixture['user'])
        assert not frappe.has_permission('Cost Center',ptype='read',doc=frappe.get_doc('Cost Center',cost),user=fixture['user'])
        denied(lambda:service.get_revision(company,'code',revision,'2026-10-15'),{'not_found'})
        denied(lambda:read_company_operation(company,operation),{'not_found'})
        assert service.list_masters(company,'code','2026-10-15',limit=1,count_mode='exact')['total']==0
        checks.append('disabled_native_original_history_is_readable_but_current_native_revoke_hides_read_receipt_and_counts')
        frappe.set_user('Administrator');update_permission_property('Cost Center',fixture['role'],0,'read',1);frappe.db.commit()
        for user in (fixture['user'],fixture['alias']):frappe.clear_cache(user=user)
        frappe.set_user(fixture['user']);assert read_company_operation(company,operation)['revision']==original['revision']
        exact=repository.read('code_revision',revision);doc=frappe.get_doc('Cipher Cost Code Revision',revision)
        with trusted_write():denied(lambda:doc.save(ignore_permissions=True),{'controls_effect_required'})
        denied(lambda:create_initial_adoption(actor=current_actor(),company=company,project='unallocated',award_id=str(uuid4()),award_revision_id=str(uuid4()),award_plan_digest='0'*64,reviewed_plan={},packet_id='none',decision_id='none',operation_id=str(uuid4()),resource_token={}),{'approval_required','award_effect_required'})
        assert repository.read('code_revision',revision)==exact
        assert {name:frappe.db.count(name) for name in native_before}==native_before
        checks.append('generic_trusted_write_and_unregistered_award_factory_refused_no_native_master_or_posting_effect')
        frappe.set_user('Administrator')
        with trusted_write():
            project=frappe.get_doc({'doctype':'Project','company':company,'project_name':'Controls permission split '+fixture['marker'],'status':'Open'}).insert(ignore_permissions=True)
            for ability in ('project.read','budget.read'):_grant(fixture['person'],company,project.name,ability)
        frappe.db.commit();frappe.set_user(fixture['user'])
        denied(lambda:service.get_record(company,project.name,'budget',str(uuid4())),{'capability_denied'})
        denied(lambda:service.list_records(company,project.name,'budget',count_mode='exact'),{'capability_denied'})
        denied(lambda:service.get_record(company,project.name,'budget_line',str(uuid4())),{'not_found'})
        frappe.set_user('Administrator')
        with trusted_write():_grant(fixture['person'],company,project.name,'wbs.read')
        set_synthetic_duty(fixture['user'],project.name,'budget.read',0);frappe.db.commit();frappe.set_user(fixture['user'])
        denied(lambda:service.get_record(company,project.name,'wbs',str(uuid4())),{'not_found'})
        denied(lambda:service.get_record(company,project.name,'budget',str(uuid4())),{'capability_denied'})
        denied(lambda:service.get_record(company,project.name,'budget_line',str(uuid4())),{'capability_denied'})
        checks.append('full_budget_requires_wbs_and_budget_before_get_list_count_wbs_only_and_exact_line_reference_stay_separate')

        return {'schema':'cipher.project-controls.native-acceptance.v1','status':'passed','company':company,'checks':checks,'checks_passed':len(checks),'native_first_acquisitions':first_native,'native_lock_acquisition_count':len(all_native),'native_all_acquisitions':all_native,'account_currency_current_read':drift,'prior_source_authority':prior_authority,'qualification':'canonical master storage/current-native/effective-history only; full composed award/WBS/budget adoption pending','native_counts_unchanged':native_before,'live_provider_qualified':False,'posting_qualified':False}
    finally:
        frappe.db.rollback();frappe.set_user('Administrator')
        update_permission_property('Cost Center',fixture['role'],0,'read',1)
        native=frappe.get_doc('Cost Center',cost)
        if native.disabled:native.disabled=0;native.save(ignore_permissions=True)
        frappe.db.commit()
        for user in (fixture['user'],fixture['alias']):frappe.clear_cache(user=user)


def run_account_currency_current_read(*,company,account,revision_id):
    """Own fixture scalar drift; not supported Account currency migration."""
    import threading
    import frappe
    from cipher_aec.governance.context import current_actor
    from cipher_aec.api.errors import DomainError
    from cipher_aec.project_controls import masters
    from cipher_aec.estimating import scopes
    from cipher_aec.estimating.lockplan import prepared
    frappe.db.commit();site=frappe.local.site
    isolation=frappe.db.sql('SELECT @@tx_isolation')[0][0]
    assert isolation=='REPEATABLE-READ'
    before=frappe.db.sql('SELECT account_currency FROM `tabAccount` WHERE name=%s',(account,))[0][0]
    changed='EUR' if before!='EUR' else 'USD'
    actor=current_actor()
    plan=masters.plan_resources(actor=actor,company=company,code_revision_ids=[],type_revision_ids=[revision_id],basis_date='2026-10-15',purpose='award.initial-budget.v1')
    reader=frappe.db.sql('SELECT CONNECTION_ID()')[0][0];writers=[];errors=[]
    def writer():
        try:
            frappe.init(site=site);frappe.connect()
            writers.append(frappe.db.sql('SELECT CONNECTION_ID()')[0][0])
            frappe.db.sql('UPDATE `tabAccount` SET account_currency=%s WHERE name=%s',(changed,account));frappe.db.commit()
        except BaseException as error:errors.append(type(error).__name__)
        finally:frappe.destroy()
    thread=threading.Thread(target=writer,daemon=True)
    refusal=None
    try:
        thread.start();thread.join(20)
        assert not thread.is_alive() and not errors and writers[0]!=reader
        assert frappe.db.sql('SELECT account_currency FROM `tabAccount` WHERE name=%s',(account,))[0][0]==before
        try:
            with scopes.activate('Company',company,None),prepared(plan,actor,company) as token:
                masters.resolve_revision(actor=actor,company=company,kind='type',revision_id=revision_id,basis_date='2026-10-15',purpose='award.initial-budget.v1',lock=True,resource_token=token)
        except DomainError as error:
            assert error.code in {'cost_source_drift','source_prelock_required'},error.code
            refusal={'code':error.code}
        except frappe.QueryDeadlockError as error:
            assert '1020' in str(error),str(error)
            refusal={'code':'native_snapshot_serialization_conflict','native_code':1020}
        assert refusal,'Old native currency snapshot must not silently admit the changed Account currency.'
    finally:
        frappe.db.rollback();thread.join(20)
        if thread.is_alive():raise RuntimeError('Fixture writer remains active; halt further fixture work.')
        frappe.db.sql('UPDATE `tabAccount` SET account_currency=%s WHERE name=%s',(before,account));frappe.db.commit()
    assert frappe.db.sql('SELECT account_currency FROM `tabAccount` WHERE name=%s',(account,))[0][0]==before
    # A fresh transaction must again resolve exactly the restored original source.
    with scopes.activate('Company',company,None):
        fresh=masters.plan_resources(actor=actor,company=company,code_revision_ids=[],type_revision_ids=[revision_id],basis_date='2026-10-15',purpose='award.initial-budget.v1')
        with prepared(fresh,actor,company) as token:
            masters.resolve_revision(actor=actor,company=company,kind='type',revision_id=revision_id,basis_date='2026-10-15',purpose='award.initial-budget.v1',lock=True,resource_token=token)
    frappe.db.commit()
    return {'status':'passed','qualification':'real MariaDB two-connection fixture scalar drift; no Account migration/posting claim','isolation':isolation,'different_connections':True,'refusal':refusal,'account_currency_restored':True,'fresh_original_source_resolved':True}


def run_prior_source_authority(*,fixture,typed,other_account):
    """Actual native Currency permission plus isolated prior-target scope drift."""
    import frappe
    import hashlib,json,re
    from cipher_aec.api.contracts import digest
    from cipher_aec.api.errors import DomainError
    from cipher_aec.governance.context import current_actor,require_company
    from cipher_aec.project_controls import masters,repository
    company=fixture['company'];user=fixture['user'];old=typed['revision']
    account=old['definition']['native_target']['name']
    assert account!=other_account
    assert frappe.db.get_value('Account',other_account,'company')==company
    assert frappe.db.exists('Company','Cipher Synthetic Company') and company!='Cipher Synthetic Company'
    original={name:frappe.db.sql('SELECT company,account_currency FROM `tabAccount` WHERE name=%s',(name,))[0] for name in (account,other_account)}
    alternate_rows=frappe.db.sql("SELECT name FROM `tabCurrency` WHERE name!='USD' AND enabled=1 AND fraction_units=100 ORDER BY (name='EUR') DESC,name LIMIT 1")
    alternate=alternate_rows[0][0] if alternate_rows else 'EUR'
    currency_before_rows=frappe.db.sql('SELECT * FROM `tabCurrency` WHERE name=%s',(alternate,),as_dict=True)
    assert len(currency_before_rows)==1,'Canonical ISO Currency fixture must already exist; no synthetic Currency is created.'
    currency_before=dict(currency_before_rows[0]);currency_after=dict(currency_before);currency_changed=[]
    def currency_hash(row):return hashlib.sha256(json.dumps(dict(row),sort_keys=True,default=str,separators=(',',':')).encode()).hexdigest()
    currency_before_hash=currency_hash(currency_before)
    permission_id=None;created_permissions=[];checks=[]
    before_counts={name:frappe.db.count(name,{'company':company}) for name in ('Cipher Cost Type Revision','Cipher Command Receipt','Cipher History Event')}
    def refusal(definition):
        try:masters.revise_master(company,str(uuid4()),'type',typed['master']['id'],typed['version'],definition)
        except DomainError as error:
            assert error.code=='not_found',error.code
            frappe.db.rollback();return error.code
        raise AssertionError('Prior immutable native source authority was bypassed by a new target')
    changed={**old['definition'],'effective_from':'2026-11-01','native_target':{'doctype':'Account','name':other_account}}
    try:
        frappe.set_user('Administrator')
        if not alternate_rows:
            # Self-contained isolated-site prerequisite, using the native
            # controller and recording every persisted setup change. This is
            # fixture qualification only, never a production fallback.
            native_currency=frappe.get_doc('Currency',alternate)
            native_currency.enabled=1;native_currency.fraction_units=100
            native_currency.save(ignore_permissions=True)
            currency_after=dict(frappe.db.sql('SELECT * FROM `tabCurrency` WHERE name=%s',(alternate,),as_dict=True)[0])
            currency_changed=[key for key in currency_before if currency_before[key]!=currency_after[key]]
            assert currency_after['enabled']==1 and currency_after['fraction_units']==100
            frappe.db.commit()
        for name in (account,other_account):frappe.db.sql('UPDATE `tabAccount` SET account_currency=%s WHERE name=%s',(alternate,name))
        permission=frappe.get_doc({'doctype':'User Permission','user':user,'allow':'Currency','for_value':alternate,'apply_to_all_doctypes':0,'applicable_for':'Currency'}).insert(ignore_permissions=True)
        permission_id=permission.name;created_permissions.append(permission_id);frappe.db.commit();frappe.clear_cache(user=user);frappe.set_user(user)
        actor=current_actor();require_company(company,ability='project.cost.write',actor=actor)
        assert frappe.has_permission('Currency',ptype='read',doc=frappe.get_doc('Currency',alternate),user=user)
        assert not frappe.has_permission('Currency',ptype='read',doc=frappe.get_doc('Currency','USD'),user=user)
        plan=masters.plan_resources(actor=actor,company=company,code_revision_ids=[],type_revision_ids=[old['id']],basis_date='2026-10-15',purpose='historical_read')
        assert plan['currencies']==sorted([alternate,'USD']),plan
        eligible=masters.authorize_native(actor=actor,company=company,kind='type',definition=changed,for_new=True)
        assert eligible['account_currency']==alternate and eligible['company']==company
        refusal(changed)
        assert repository.read('type',typed['master']['id'])==typed['master']
        checks.append('prior_authored_usd_in_current_alternate_union_and_actual_usd_denial_blocks_successor')
        frappe.set_user('Administrator');frappe.delete_doc('User Permission',permission_id,ignore_permissions=True);permission_id=None
        for name,(_,currency) in original.items():frappe.db.sql('UPDATE `tabAccount` SET account_currency=%s WHERE name=%s',(currency,name))
        frappe.db.commit();frappe.clear_cache(user=user)
        # A different new target is still valid in the own Company. Only the
        # immutable predecessor's native Account is moved, by fixture scalar.
        frappe.db.sql('UPDATE `tabAccount` SET company=%s WHERE name=%s',('Cipher Synthetic Company',account));frappe.db.commit()
        frappe.set_user(user)
        actor=current_actor();require_company(company,ability='project.cost.write',actor=actor)
        assert frappe.has_permission('Account',ptype='read',doc=frappe.get_doc('Account',other_account),user=user)
        refusal(changed)
        assert repository.read('type',typed['master']['id'])==typed['master']
        assert {name:frappe.db.count(name,{'company':company}) for name in before_counts}==before_counts
        checks.append('prior_native_foreign_company_refused_even_with_distinct_eligible_new_own_company_target')
    finally:
        frappe.db.rollback();frappe.set_user('Administrator')
        if permission_id and frappe.db.exists('User Permission',permission_id):frappe.delete_doc('User Permission',permission_id,ignore_permissions=True)
        for name,(native_company,currency) in original.items():frappe.db.sql('UPDATE `tabAccount` SET company=%s,account_currency=%s WHERE name=%s',(native_company,currency,name))
        frappe.db.commit();frappe.clear_cache(user=user)
        assert {name:frappe.db.sql('SELECT company,account_currency FROM `tabAccount` WHERE name=%s',(name,))[0] for name in original}==original
        current_currency=dict(frappe.db.sql('SELECT * FROM `tabCurrency` WHERE name=%s FOR UPDATE',(alternate,),as_dict=True)[0])
        if currency_changed:
            # Do not overwrite any competing change, even in this isolated
            # fixture. Restore only fields actually changed by native setup.
            if any(current_currency[key]!=currency_after[key] for key in currency_changed):
                raise RuntimeError('Currency fixture restoration conflict; preserve this invocation for reconciliation.')
            assert all(re.fullmatch(r'[A-Za-z0-9_]+',key) for key in currency_changed)
            assignments=','.join('`'+key+'`=%s' for key in currency_changed)
            frappe.db.sql('UPDATE `tabCurrency` SET '+assignments+' WHERE name=%s',tuple(currency_before[key] for key in currency_changed)+(alternate,))
        frappe.db.commit();frappe.clear_cache(doctype='Currency')
        restored_currency=dict(frappe.db.sql('SELECT * FROM `tabCurrency` WHERE name=%s',(alternate,),as_dict=True)[0])
        assert currency_hash(restored_currency)==currency_before_hash
        assert not any(frappe.db.exists('User Permission',name) for name in created_permissions)
        frappe.set_user(user)
    assert repository.read('type_revision',old['id'])==old
    return {'status':'passed','checks':checks,'old_revision_digest_unchanged':digest(old),'own_native_accounts_and_user_permission_restored':True,'allowed_current_currency':alternate,'denied_original_currency':'USD','before_counts':before_counts,'currency_fixture':{'name':alternate,'existing_eligible_alternate':bool(alternate_rows),'setup_changed_fields':currency_changed,'original_row_sha256':currency_before_hash,'restored_row_sha256':currency_hash(restored_currency),'no_owned_user_permissions_remain':True},'qualification':'real native Currency permission; Company/currency mutations are isolated fixture-only scalars, not supported Account migration'}

"""Explicit FIN01 native-storage acceptance, not financial or legal execution.

Creates an isolated synthetic Project and native parties; no accounting transaction,
certification, payable, or manufacturing subcontracting document is created.
"""
from copy import deepcopy
import hashlib
import secrets
from uuid import uuid4


def run_acceptance():
    import frappe
    from frappe.utils import now_datetime
    from werkzeug.test import EnvironBuilder
    from werkzeug.wrappers import Request
    from cipher_aec.api.contracts import canonical_json, digest
    from cipher_aec.api.errors import DomainError
    from cipher_aec.construction_finance import service, repository, governance
    from cipher_aec.documents.service import upload_document, get_citation
    from cipher_aec.estimating.service import register_unit
    from cipher_aec.governance import approvals, domain_approvals
    from cipher_aec.governance.commands import read_operation
    from cipher_aec.governance.context import ABILITIES, assert_synthetic_site, current_actor, trusted_write
    from cipher_aec.install import _binding, _grant, _person, _user, set_synthetic_duty

    assert_synthetic_site()
    if frappe.session.user != 'Administrator':
        raise RuntimeError('Use synthetic bench Administrator to start FIN01 acceptance.')
    company = 'Cipher Synthetic Company'
    marker = uuid4().hex[:12]
    initial_request = getattr(frappe.local, 'request', None)
    initial_sid = getattr(frappe.session, 'sid', None)
    administrator = current_actor().person_id
    participants, checks = {}, []
    company_doc = frappe.get_doc('Company', company)
    with trusted_write():
        for key in ('author', 'alias', 'reviewer', 'outsider'):
            user = f'fin.{key}.{marker}@cipher.example'
            person = 'FIN-AUTHOR-' + marker if key == 'alias' else 'FIN-' + key.upper() + '-' + marker
            _person(person, 'Explicit FIN01 ' + key)
            _user(user, 'Explicit FIN01 ' + key, secrets.token_urlsafe(32))
            _binding(user, person)
            participants[key] = {'user': user, 'person': person}
        customer_group = frappe.get_doc({'doctype':'Customer Group','customer_group_name':'FIN01 customers ' + marker,'parent_customer_group':'All Customer Groups','is_group':0}).insert(ignore_permissions=True)
        supplier_group = frappe.get_doc({'doctype':'Supplier Group','supplier_group_name':'FIN01 suppliers ' + marker,'parent_supplier_group':'All Supplier Groups','is_group':0}).insert(ignore_permissions=True)
        territory = frappe.get_doc({'doctype':'Territory','territory_name':'FIN01 territory ' + marker,'parent_territory':'All Territories','is_group':0}).insert(ignore_permissions=True)
        customer = frappe.get_doc({'doctype':'Customer', 'customer_name':'FIN01 native customer ' + marker, 'customer_type':'Company',
            'customer_group':customer_group.name, 'territory':territory.name,
            'accounts':[{'company':company,'account':company_doc.default_receivable_account}]}).insert(ignore_permissions=True)
        supplier = frappe.get_doc({'doctype':'Supplier', 'supplier_name':'FIN01 native supplier ' + marker, 'supplier_type':'Company',
            'supplier_group':supplier_group.name, 'accounts':[{'company':company,'account':company_doc.default_payable_account}]}).insert(ignore_permissions=True)
        project = frappe.get_doc({'doctype':'Project', 'company':company, 'project_name':'FIN01 explicit foundation ' + marker,
                                  'customer':customer.name, 'status':'Open'}).insert(ignore_permissions=True)
        for person in (administrator, participants['author']['person']):
            for ability in sorted(ABILITIES):
                if ability in {'contract.read','contract.write','project.read','project.write','document.read','document.write','estimate.read','estimate.write','approval.request','approval.decide','approval.execute'}:
                    _grant(person,company,project.name,ability)
        for ability in ('project.read','contract.read','document.read','approval.decide'):
            _grant(participants['reviewer']['person'],company,project.name,ability)
        # Native counterparty read rights are explicit; project duties alone are
        # deliberately insufficient to read a Customer/Supplier source.
        from frappe.permissions import add_permission, update_permission_property
        role = 'FIN01 native source reader ' + marker
        frappe.get_doc({'doctype':'Role','role_name':role}).insert(ignore_permissions=True)
        for doctype in ('Customer','Supplier','UOM','Currency'):
            add_permission(doctype,role,0)
            update_permission_property(doctype,role,0,'read',1)
        for key in ('author','alias','reviewer'):
            user_doc = frappe.get_doc('User',participants[key]['user']); user_doc.append('roles',{'role':role}); user_doc.save(ignore_permissions=True)
        native_unit = frappe.get_doc({'doctype':'UOM', 'uom_name':'FIN01 qualified quantity ' + marker, 'symbol':'fin' + marker,
                                      'enabled':1,'must_be_whole_number':0}).insert(ignore_permissions=True)
    unit = register_unit(company,project.name,str(uuid4()),native_unit.name,'count',6)['unit']
    frappe.db.commit()

    def login(key):
        user = participants[key]['user']
        frappe.set_user(user)
        sid = 'explicit-fin-session-' + uuid4().hex
        frappe.session.sid = sid
        frappe.local.request = Request(EnvironBuilder(method='POST',base_url='http://cipher.localhost',headers={'Cookie':'sid='+sid}).get_environ())
        frappe.db.sql("INSERT INTO tabSessions(user,sid,sessiondata,lastupdate,status) VALUES(%s,%s,%s,%s,'Active')", (user,sid,canonical_json({'user':user}),now_datetime()))
        frappe.db.commit()

    def denied(callback, codes):
        try:
            callback()
        except DomainError as error:
            assert error.code in codes, (error.code,codes)
            frappe.db.rollback()
            return error.code
        raise AssertionError('Unqualified contract action was accepted')

    def request(contract):
        return domain_approvals.request_action(company=company,project=project.name,action=governance.ACTION,subject_id=contract['id'],
                                        expected_version=service.version(contract),operation_id=str(uuid4()))['packet']

    def grant(packet):
        login('reviewer')
        result = approvals.decide_packet(company,project.name,packet['id'],packet['manifest_hash'],'Grant',str(uuid4()),'Independent explicit synthetic baseline review')
        frappe.db.commit()
        assert result['packet']['state'] == 'Granted'
        login('author')

    try:
        login('author')
        content = ('Explicit synthetic FIN01 source. Contract cap USD1000.00. First SOV line ten fixture quantities, USD100.00. '
                   'Five percent retainage with explicit fixture release conditions. No executed contract or financial authority.').encode()
        uploaded = upload_document(company=company,project=project.name,title='FIN01 authored source ' + marker,filename='fin01-explicit-source.txt',content=content,
                                   byte_length=len(content),sha256=hashlib.sha256(content).hexdigest(),operation_id=str(uuid4()))
        citation = get_citation(company,uploaded['revision']['id'],1)
        reference = {key:citation[key] for key in ('revision_id','page','excerpt_sha256','source_sha256')}
        definition = {'number':'FIN01-' + marker,'kind':'prime','direction':'receivable','party_type':'Customer','party':customer.name,
                      'currency':'USD','original_value':{'amount':'1000.00','currency':'USD'}}
        operation = str(uuid4())
        created = service.create_contract(company,project.name,operation,definition)
        frappe.db.commit()
        replay = service.create_contract(company,project.name,operation,definition)
        assert replay['operation']['replayed'] and replay['contract']['id'] == created['contract']['id']
        contract = created['contract']
        assert contract['creation_admission']['status'] == 'new_contract_without_supported_obligations'
        assert contract['creation_admission']['channel_count'] >= 12 and 'observed' not in contract['creation_admission']
        checks.append('native_party_contract_origin_and_exact_single_create_replay')
        terms = {'billing_method':'lump_sum','effective_date':'2026-10-15','end_date':None,'terms_text':'Explicit synthetic authored terms; not executed.'}
        policy = {'basis':'installed_plus_eligible_stored','tiers':[{'up_to':None,'rate':'0.05'}],'cap':None,'effective_date':'2026-10-15','rounding':'HALF_UP',
                  'reduction_conditions':'No reduction without independent governed change','release_conditions':'Future qualified release action required',
                  'approval_basis':'Explicit synthetic policy only; not counterparty legal execution'}
        line = {'line_id':str(uuid4()),'item_code':'FOUND-001','description':'Explicit authored work','quantity':{'amount':'10.000001','unit_id':unit['id'],'precision':6},
                'scheduled_amount':{'amount':'100.01','currency':'USD'},'cost_code':'FOUND','stored_material_eligible':True,'source_line_id':None}
        arguments = dict(company=company,project=project.name,operation_id=str(uuid4()),contract_id=contract['id'],expected_version=service.version(contract),
                         terms=terms,retainage_policy=policy,lines=[line],source_citations=[reference])
        from unittest.mock import patch
        import re
        native_locks=[]
        native_lock_queries=[]
        original_sql=frappe.db.sql
        def observed_sql(query, values=(), *args, **kwargs):
            rows=original_sql(query,values,*args,**kwargs)
            text=str(query)
            if re.search(r'\bFOR\s+UPDATE\b',text,re.IGNORECASE):
                # Match complete parent identifiers, never Customer Credit
                # Limit/Supplier Number child tables. A qualified UUID lookup
                # and the permission lookup by name lock the same physical row.
                match=re.search(r'\bFROM\s+(?:`tab(UOM|Currency|Customer|Supplier)`|tab(UOM|Currency|Customer|Supplier)\b)(?=\s|$)',text,re.IGNORECASE)
                if match:
                    kind=next(name for name in ('UOM','Currency','Customer','Supplier') if name.lower()==(match.group(1) or match.group(2)).lower())
                    columns=[column[0] for column in frappe.db._cursor.description]
                    parameters=tuple(str(value) for value in (values.values() if isinstance(values,dict) else values if isinstance(values,(list,tuple)) else (values,)))
                    for row in rows:
                        name=row['name'] if isinstance(row,dict) else row[columns.index('name')]
                        assert isinstance(name,str) and name, (kind,columns)
                        key=(kind,name)
                        first_acquisition=key not in native_locks
                        native_lock_queries.append({'kind':kind,'name':name,'parameters':parameters,'first_acquisition':first_acquisition})
                        if first_acquisition: native_locks.append(key)
            return rows
        with patch.object(frappe.db,'sql',side_effect=observed_sql):
            first = service.author_revision(**arguments)
        ranks={'UOM':0,'Currency':1,'Customer':2,'Supplier':2}
        first_kind=[]
        for kind,identity in native_locks:
            if kind not in first_kind: first_kind.append(kind)
        assert [ranks[kind] for kind,identity in native_locks] == sorted(ranks[kind] for kind,identity in native_locks), native_locks
        assert native_locks == [('UOM',native_unit.name),('Currency','USD'),('Customer',customer.name)],native_locks
        author_lock_queries=deepcopy(native_lock_queries)
        frappe.db.commit()
        first_sov = deepcopy(first['sov']); first_policy = deepcopy(first['policy'])
        again = service.author_revision(**arguments)
        assert again['operation']['replayed'] and again['revision']['id'] == first['revision']['id']
        assert frappe.db.count('Cipher SOV Line',{'sov_version':first['sov']['id']}) == 1
        for kind in ('revision','policy','sov'):
            denied(lambda kind=kind: frappe.get_doc(repository.DOCTYPES[kind],first[kind]['id']).save(ignore_permissions=True), {'governed_write_required'})
        checks.append('immutable_exact_terms_policy_sov_and_stable_line_replay')
        packet = request(first['contract']); frappe.db.commit()
        assert repository.read('contract',contract['id'])['accepted_revision'] is None
        login('alias')
        denied(lambda: approvals.decide_packet(company,project.name,packet['id'],packet['manifest_hash'],'Grant',str(uuid4()),'Alias self review'), {'independent_review_required'})
        grant(packet)
        # Independent grant is a prerequisite, not an effect.
        assert repository.read('contract',contract['id'])['accepted_revision'] is None
        execute_op = str(uuid4())
        accepted = approvals.execute_packet(company,project.name,packet['id'],packet['manifest_hash'],execute_op); frappe.db.commit()
        current = repository.read('contract',contract['id'])
        assert current['accepted_revision'] == first['revision']['id']
        assert current['activation']['legal_execution'] is False and current['activation']['posting'] is False
        retry = approvals.execute_packet(company,project.name,packet['id'],packet['manifest_hash'],execute_op)
        assert retry['operation']['replayed']
        assert frappe.db.count('Cipher Approval Consumption',{'packet':packet['id']}) == 1
        checks.append('independent_human_grant_and_one_atomic_baseline_consumption')
        # Native disabling is an eligibility change, not deletion of history.
        frappe.set_user('Administrator'); unit_doc=frappe.get_doc('UOM',native_unit.name); unit_doc.enabled=0; unit_doc.save(ignore_permissions=True); frappe.db.commit()
        login('author')
        assert service.get_record(company,project.name,'sov',first_sov['id'])['record'] == first_sov
        assert read_operation(company,project.name,arguments['operation_id'])['operation']['replayed']
        assert approvals.read_packet(company,project.name,packet['id'])['state'] == 'Consumed'
        disabled_unit_args=deepcopy(arguments); disabled_unit_args.update(operation_id=str(uuid4()),expected_version=service.version(current))
        denied(lambda: service.author_revision(**disabled_unit_args), {'unit_setup_required'})
        frappe.set_user('Administrator'); unit_doc=frappe.get_doc('UOM',native_unit.name); unit_doc.enabled=1; unit_doc.save(ignore_permissions=True); frappe.db.commit()
        login('author')
        checks.append('sorted_shared_master_locks_and_disabled_unit_historical_readback')
        # With no qualified FIN03 reader a reduction is not allowed, even when
        # an operator might claim this brand-new accepted contract is unbilled.
        reduction = deepcopy(arguments); reduction.update(operation_id=str(uuid4()),expected_version=service.version(current))
        reduction['lines'][0]['scheduled_amount']['amount'] = '100.00'
        denied(lambda: service.author_revision(**reduction), {'certified_floor_required'})
        assert frappe.db.count('Cipher Contract Revision',{'contract':contract['id']}) == 1
        increased = deepcopy(arguments); increased.update(operation_id=str(uuid4()),expected_version=service.version(current))
        increased['lines'][0]['scheduled_amount']['amount'] = '200.00'
        increased['lines'][0]['quantity']['amount'] = '20.000001'
        successor = service.author_revision(**increased); frappe.db.commit()
        assert successor['sov']['lines'][0]['line_id'] == line['line_id']
        assert repository.read('sov',first_sov['id']) == first_sov and repository.read('policy',first_policy['id']) == first_policy
        checks.append('accepted_cap_reduction_blocked_increase_preserves_historical_policy_and_line')
        # A packet against an exact predecessor becomes stale when a new draft
        # is authored; approval never slides to a more recent revision.
        stale_packet = request(successor['contract']); frappe.db.commit(); grant(stale_packet)
        newest_args = deepcopy(increased); newest_args.update(operation_id=str(uuid4()),expected_version=successor['version'])
        newest_args['lines'][0]['description'] = 'Explicit revised description, same stable identity and cap'
        newest = service.author_revision(**newest_args); frappe.db.commit()
        denied(lambda: approvals.execute_packet(company,project.name,stale_packet['id'],stale_packet['manifest_hash'],str(uuid4())), {'approval_not_executable','stale_contract'})
        assert repository.read('contract',contract['id'])['accepted_revision'] == first['revision']['id']
        checks.append('stale_manifest_cannot_advance_draft_or_accepted_predecessor')
        login('outsider')
        denied(lambda: service.get_record(company,project.name,'contract',contract['id']), {'not_found'})
        login('author')
        frappe.set_user('Administrator')
        set_synthetic_duty(participants['author']['user'],project.name,'document.read',0); frappe.db.commit()
        login('author')
        denied(lambda: service.get_record(company,project.name,'sov',first_sov['id']), {'capability_denied'})
        denied(lambda: read_operation(company,project.name,arguments['operation_id']), {'capability_denied'})
        denied(lambda: approvals.read_packet(company,project.name,packet['id']), {'capability_denied'})
        frappe.set_user('Administrator'); set_synthetic_duty(participants['author']['user'],project.name,'document.read',1); frappe.db.commit()
        login('author')
        checks.append('current_source_rights_rechecked_on_records_receipts_and_consumed_packets')
        # Disabling a source blocks new use while preserving authorized history.
        frappe.set_user('Administrator'); customer = frappe.get_doc('Customer',customer.name); customer.disabled=1; customer.save(ignore_permissions=True); frappe.db.commit()
        login('author')
        assert service.get_record(company,project.name,'contract',contract['id'])['record']['id'] == contract['id']
        assert read_operation(company,project.name,operation)['operation']['replayed']
        disabled_args = deepcopy(newest_args); disabled_args.update(operation_id=str(uuid4()),expected_version=newest['version'])
        denied(lambda: service.author_revision(**disabled_args), {'counterparty_disabled'})
        frappe.set_user('Administrator'); customer = frappe.get_doc('Customer',customer.name); customer.disabled=0; customer.save(ignore_permissions=True); frappe.db.commit()
        # Revoking native-party read rights affects historical reads and receipts.
        from frappe.permissions import update_permission_property
        update_permission_property('Customer',role,0,'read',0); frappe.db.commit()
        login('author')
        denied(lambda: service.get_record(company,project.name,'contract',contract['id']), {'not_found'})
        denied(lambda: read_operation(company,project.name,operation), {'not_found'})
        frappe.set_user('Administrator'); update_permission_property('Customer',role,0,'read',1); frappe.db.commit()
        login('author')
        checks.append('disabled_party_preserves_history_and_current_native_read_revocation_denies')
        # No arbitrary native financial draft can race the initial admission.
        native_denied = denied(lambda: frappe.get_doc({'doctype':'Purchase Order','company':company,'supplier':supplier.name}).insert(ignore_permissions=True), {'financial_action_unqualified'})
        assert native_denied == 'financial_action_unqualified'
        assert not frappe.has_permission('Cipher SOV Version','read',doc=frappe.get_doc('Cipher SOV Version',first_sov['id']))
        checks.append('unqualified_native_financial_drafts_and_generic_snapshot_reads_denied')
        payable={**definition,'number':'FIN01-PAYABLE-' + marker,'kind':'subcontract','direction':'payable','party_type':'Supplier','party':supplier.name}
        supplier_contract=service.create_contract(company,project.name,str(uuid4()),payable)['contract']; frappe.db.commit()
        newest_customer=service.create_contract(company,project.name,str(uuid4()),{**definition,'number':'FIN01-NEWEST-' + marker})['contract']; frappe.db.commit()
        listing=service.list_contracts(company,project.name,limit=1,count_mode='exact')
        assert listing['items'][0]['id'] == newest_customer['id']
        assert listing['total'] == 3 and listing['next_cursor']
        frappe.set_user('Administrator')
        from frappe.permissions import update_permission_property
        update_permission_property('Supplier',role,0,'read',0); frappe.db.commit()
        login('author')
        assert service.get_record(company,project.name,'contract',newest_customer['id'])['record']['id'] == newest_customer['id']
        denied(lambda: service.list_contracts(company,project.name,limit=1,count_mode='exact'), {'not_found'})
        denied(lambda: service.list_contracts(company,project.name,limit=1), {'not_found'})
        frappe.set_user('Administrator'); update_permission_property('Supplier',role,0,'read',1); frappe.db.commit()
        login('author')
        checks.append('native_supplier_contract_and_off_page_party_denial_before_pagination_counts')
        # Old unaccepted drafts may reference units absent from either current
        # head. Whole-receipt authorization must prelock that historical union.
        old_draft_args=deepcopy(arguments); old_draft_args.update(operation_id=str(uuid4()),contract_id=newest_customer['id'],expected_version=service.version(newest_customer))
        old_draft=service.author_revision(**old_draft_args); frappe.db.commit()
        frappe.set_user('Administrator')
        replacement_unit=frappe.get_doc({'doctype':'UOM','uom_name':'FIN01 replacement draft unit ' + marker,'symbol':'finnew' + marker,'enabled':1,'must_be_whole_number':0}).insert(ignore_permissions=True)
        replacement=register_unit(company,project.name,str(uuid4()),replacement_unit.name,'count',6)['unit']; frappe.db.commit()
        login('author')
        replacement_args=deepcopy(old_draft_args); replacement_args.update(operation_id=str(uuid4()),expected_version=old_draft['version'])
        replacement_args['lines'][0]['quantity']['unit_id']=replacement['id']
        service.author_revision(**replacement_args); frappe.db.commit()
        native_locks.clear()
        native_lock_queries.clear()
        with patch.object(frappe.db,'sql',side_effect=observed_sql):
            historic=read_operation(company,project.name,old_draft_args['operation_id'])
        assert historic['revision']['id'] == old_draft['revision']['id']
        assert [ranks[kind] for kind,identity in native_locks] == sorted(ranks[kind] for kind,identity in native_locks),native_locks
        assert sum(kind=='UOM' for kind,identity in native_locks)==2,native_locks
        expected_units={unit['id']:native_unit.name,replacement['id']:replacement_unit.name}
        assert native_locks == [('UOM',expected_units[identifier]) for identifier in sorted(expected_units)] + [('Currency','USD'),('Customer',customer.name)],native_locks
        checks.append('historical_receipt_prelocks_old_and_current_uom_union_before_party')
        result = {'schema':'cipher.finance.acceptance.v1','status':'passed','label':'explicit-synthetic-fin01-with-real-native-storage-and-governance',
                  'company':company,'project':project.name,'contract_id':contract['id'],'accepted_revision':first['revision']['id'],
                  'current_draft_revision':newest['revision']['id'],'native_customer':customer.name,'native_supplier':supplier.name,
                  'checks':checks,'shared_native_master_first_lock_order':first_kind,'legal_execution':False,'financial_posting':False,'certification':False,
                  'native_parent_lock_queries':{'author_revision':author_lock_queries,'historical_receipt':native_lock_queries},
                  'historical_receipt_first_native_acquisitions':native_locks,
                  'floor_provider_qualified':False,'live_model_qualified':False,'external_provider_qualified':False}
        frappe.db.commit()
        return result
    finally:
        frappe.set_user('Administrator')
        frappe.local.request=initial_request
        frappe.session.sid=initial_sid


def validate_schema_samples(project):
    """Read-only validation of actual responses plus reconstructed input shapes."""
    import json
    from pathlib import Path
    import frappe
    from jsonschema import Draft202012Validator, FormatChecker
    from cipher_aec.construction_finance import service, repository
    from cipher_aec.governance.context import assert_synthetic_site
    assert_synthetic_site()
    if frappe.session.user != 'Administrator' or not frappe.db.get_value('Project',project,'project_name').startswith('FIN01 explicit foundation '):
        raise RuntimeError('Use an existing isolated FIN01 fixture project as Administrator.')
    schema=json.loads((Path(__file__).resolve().parents[1]/'construction_finance/schemas/api-v1.schema.json').read_text())
    Draft202012Validator.check_schema(schema)
    definitions=schema['$defs']
    checked=[]
    def check(name, value):
        Draft202012Validator({'$defs':definitions, **definitions[name]},format_checker=FormatChecker()).validate(value)
        checked.append(name)
    rows=frappe.db.sql('SELECT command,operation_id,result_json FROM `tabCipher Command Receipt` WHERE project=%s AND command IN (%s,%s) ORDER BY creation,name',
                       (project,'contract.create.v1','contract.revision.author.v1'),as_dict=True)
    assert rows
    for row in rows:
        value=json.loads(row.result_json)
        value['operation']={'id':row.operation_id,'status':'succeeded','replayed':False}
        check('CreateContractResponse' if row.command=='contract.create.v1' else 'AuthorContractRevisionResponse',value)
        scoped={'company':value['contract']['company'],'project':project,'operation_id':row.operation_id}
        if row.command=='contract.create.v1':
            check('CreateContractRequest',{**scoped,'definition':value['contract']['definition']})
        else:
            revision=value['revision']; sov=value['sov']
            check('AuthorContractRevisionRequest',{**scoped,'contract_id':value['contract']['id'],'expected_version':'0'*64,'terms':revision['terms'],
                'retainage_policy':value['policy']['policy'],'lines':sov['lines'],'source_citations':[{key:citation[key] for key in ('revision_id','page','excerpt_sha256','source_sha256')} for citation in revision['source_citations']]})
        for kind in repository.DOCTYPES:
            if kind in value:
                check('GetContractRecordResponse',service.get_record(scoped['company'],project,kind,value[kind]['id']))
    company=frappe.db.get_value('Project',project,'company')
    check('ListContractsResponse',service.list_contracts(company,project,limit=1,count_mode='exact'))
    check('ListContractsRequest',{'company':company,'project':project,'limit':1,'count_mode':'exact'})
    return {'schema':'cipher.finance.schema-acceptance.v1','status':'passed','label':'read-only-actual-native-fixture-response-schema-validation',
            'project':project,'input_qualification':'Reconstructed request shapes; expected_version uses an explicit schema-only placeholder, not a claimed captured HTTP request.', 'validated_samples':len(checked),'definitions':sorted(set(checked)),'financial_posting':False,'certification':False}

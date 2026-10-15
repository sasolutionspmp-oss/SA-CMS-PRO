"""Focused real FIN native-master rights regression on a retained CI site.

Reuses that site's FIN identities and aggregate. It never provisions User/Auth,
modifies the shared main site, creates postings or infers financial floor facts.
"""
from datetime import datetime,timezone
from copy import deepcopy
from uuid import uuid4


def run_native_rights_acceptance():
    import frappe
    from frappe.permissions import add_permission,update_permission_property
    from frappe.utils import now_datetime
    from werkzeug.test import EnvironBuilder
    from werkzeug.wrappers import Request
    from cipher_aec.api.contracts import canonical_json,digest
    from cipher_aec.api.errors import DomainError
    from cipher_aec.construction_finance import service,repository,governance
    from cipher_aec.governance import approvals,domain_approvals
    from cipher_aec.governance.commands import read_operation
    from cipher_aec.governance.context import assert_synthetic_site,current_actor,require_project
    assert_synthetic_site()
    if frappe.session.user!='Administrator' or not frappe.local.site.startswith('cipher-ci-'):
        raise RuntimeError('Use an explicit retained isolated synthetic CI site as Administrator.')
    candidates=frappe.db.sql("SELECT name FROM `tabCipher Construction Contract` WHERE accepted_revision IS NOT NULL AND accepted_revision<>'' ORDER BY creation LIMIT 10")
    contract=next((value for row in candidates if (value:=repository.read('contract',row[0]))['author_user'].startswith('fin.author.')),None)
    if not contract:raise RuntimeError('The retained CI FIN acceptance aggregate is missing; do not reseed.')
    company=contract['company'];project=contract['project'];author=contract['author_user'];marker=author.split('@',1)[0].split('.')[2]
    reviewer='fin.reviewer.'+marker+'@cipher.example';role='FIN01 native source reader '+marker
    if not frappe.db.exists('User',reviewer) or role not in frappe.get_roles(author) or role not in frappe.get_roles(reviewer):
        raise RuntimeError('The retained isolated FIN fixture identities/roles no longer match.')
    revision=repository.read('revision',contract['draft_revision']);sov=repository.read('sov',revision['sov_version']);policy=repository.read('policy',revision['policy_revision'])
    line_id=frappe.db.get_value('Cipher SOV Line',{'sov_version':sov['id']},'name')
    unit=revision['units'][0];native_unit=unit['target']['name'];currency=contract['definition']['currency']
    alternate_unit=frappe.db.get_value('UOM',{'name':['!=',native_unit]},'name')
    alternate_currency=frappe.db.get_value('Currency',{'name':['!=',currency],'enabled':1},'name')
    if not alternate_unit or not alternate_currency:raise RuntimeError('Native permission counterexamples are missing.')
    saved_request=getattr(frappe.local,'request',None);saved_sid=getattr(frappe.session,'sid',None)
    originals={doctype:int(frappe.db.get_value('Custom DocPerm',{'parent':doctype,'role':role,'permlevel':0},'read') or 0) for doctype in ('UOM','Currency')}
    enabled={'UOM':frappe.db.get_value('UOM',native_unit,'enabled'),'Currency':frappe.db.get_value('Currency',currency,'enabled')}
    restrictions=[];checks=[];started=datetime.now(timezone.utc).isoformat()
    def login(user):
        frappe.set_user(user);sid='fin-native-rights-'+uuid4().hex;frappe.session.sid=sid
        frappe.local.request=Request(EnvironBuilder(method='POST',base_url='http://ci.localhost',headers={'Cookie':'sid='+sid}).get_environ())
        frappe.db.sql("INSERT INTO tabSessions(user,sid,sessiondata,lastupdate,status) VALUES(%s,%s,%s,%s,'Active')",(user,sid,canonical_json({'user':user}),now_datetime()));frappe.db.commit()
    def denied(function,codes):
        try:function()
        except DomainError as error:
            frappe.db.rollback()
            if error.code not in codes:raise AssertionError('Unexpected scoped native permission error: '+error.code) from None
            return error.code
        raise AssertionError('A native-denied FIN source or grant was accepted.')
    def restrict(doctype,name):
        frappe.set_user('Administrator')
        value=frappe.get_doc({'doctype':'User Permission','user':reviewer,'allow':doctype,'for_value':name,'apply_to_all_doctypes':0,'applicable_for':doctype}).insert(ignore_permissions=True)
        restrictions.append(value.name);frappe.db.commit();frappe.clear_cache(user=reviewer)
        target=native_unit if doctype=='UOM' else currency
        if frappe.has_permission(doctype,'read',doc=target,user=reviewer) or not frappe.has_permission(doctype,'read',doc=target,user=author):
            raise AssertionError('Actual native restriction did not isolate reviewer from executor.')
        return value.name
    def restore_restriction(name):
        frappe.set_user('Administrator');frappe.delete_doc('User Permission',name,ignore_permissions=True);restrictions.remove(name)
        frappe.db.commit();frappe.clear_cache(user=reviewer)
    try:
        for doctype in ('UOM','Currency'):
            add_permission(doctype,role,0);update_permission_property(doctype,role,0,'read',1)
        frappe.db.commit();frappe.clear_cache(user=author);frappe.clear_cache(user=reviewer)
        login(author)
        # Reuse identities/sources, not an old pending authority. Later suites
        # may have changed/restored native Currency.modified; creating a new
        # aggregate through the real service binds today's policy explicitly.
        definition=deepcopy(contract['definition']);definition['number']='FIN-NATIVE-RIGHTS-'+uuid4().hex[:12]
        contract=service.create_contract(company,project,str(uuid4()),definition)['contract'];frappe.db.commit()
        refs=[{key:row[key] for key in ('revision_id','page','excerpt_sha256','source_sha256')} for row in revision['source_citations']]
        authored=service.author_revision(company,project,str(uuid4()),contract['id'],service.version(contract),revision['terms'],policy['policy'],sov['lines'],refs);frappe.db.commit()
        contract=authored['contract'];revision=authored['revision'];sov=authored['sov'];policy=authored['policy']
        line_id=frappe.db.get_value('Cipher SOV Line',{'sov_version':sov['id']},'name')
        packet=domain_approvals.request_action(company=company,project=project,action=governance.ACTION,subject_id=contract['id'],
            expected_version=service.version(contract),operation_id=str(uuid4()))['packet'];frappe.db.commit()
        login(reviewer)
        approvals.decide_packet(company,project,packet['id'],packet['manifest_hash'],'Grant',str(uuid4()),'Independent retained CI native-rights regression');frappe.db.commit()
        reviewer_actor=current_actor();execute_id=str(uuid4())
        for doctype,allowed_name in (('UOM',alternate_unit),('Currency',alternate_currency)):
            restriction=restrict(doctype,allowed_name);login(author)
            require_project(company,project,ability='contract.read',actor=reviewer_actor)
            if not frappe.has_permission(contract['definition']['party_type'],'read',doc=contract['definition']['party'],user=reviewer):
                raise AssertionError('The native master test accidentally revoked counterparty access.')
            # Explicit actor differs from frappe.session.user in these checks.
            denied(lambda: governance.authorize_subject(actor=reviewer_actor,company=company,project=project,subject_id=contract['id'],phase='review',lock=True),{'not_found'})
            denied(lambda: governance.approval_manifest(actor=reviewer_actor,company=company,project=project,subject_id=contract['id'],expected_version=service.version(contract),lock=True),{'not_found'})
            kinds=(('revision',revision['id']),('sov',sov['id']),('line',line_id)) if doctype=='UOM' else (('contract',contract['id']),('policy',policy['id']),('revision',revision['id']),('sov',sov['id']),('line',line_id))
            for kind,name in kinds:
                denied(lambda kind=kind,name=name:service.scoped(kind,name,company,project,reviewer_actor),{'not_found'})
            denied(lambda:approvals.execute_packet(company,project,packet['id'],packet['manifest_hash'],execute_id),{'reviewer_authority_revoked'})
            if frappe.db.count('Cipher Approval Consumption',{'packet':packet['id']}):raise AssertionError('Denied reviewer authority consumed a FIN grant.')
            restore_restriction(restriction)
            checks.append({'native_master':doctype,'explicit_reviewer_actor_denied_under_executor_session':True,'historical_record_kinds_denied':[kind for kind,_ in kinds],'executor_native_read_retained':True,'grant_unconsumed':True})
        login(author)
        accepted=approvals.execute_packet(company,project,packet['id'],packet['manifest_hash'],execute_id);frappe.db.commit()
        if accepted['packet']['state']!='Consumed' or frappe.db.count('Cipher Approval Consumption',{'packet':packet['id']})!=1:
            raise AssertionError('Restored reviewer rights did not consume exactly one original operation.')
        # Disabling originals must preserve authorized historical identity reads.
        frappe.set_user('Administrator')
        for doctype,name in (('UOM',native_unit),('Currency',currency)):
            doc=frappe.get_doc(doctype,name);doc.enabled=0;doc.save(ignore_permissions=True)
        frappe.db.commit();login(author)
        for kind,name in (('contract',contract['id']),('revision',revision['id']),('sov',sov['id']),('policy',policy['id']),('line',line_id)):
            service.get_record(company,project,kind,name)
        original=read_operation(company,project,execute_id)
        if not original['operation']['replayed'] or original['effect']!=accepted['effect']:raise AssertionError('Disabled historical masters erased original FIN receipt.')
        actor=current_actor()
        denied(lambda:governance.approval_manifest(actor=actor,company=company,project=project,subject_id=contract['id'],expected_version=service.version(repository.read('contract',contract['id'])),lock=True),{'no_unaccepted_baseline','unit_setup_required','currency_setup_required'})
        report={'schema':'cipher.r1.fin-native-rights-acceptance.v1','status':'passed','site':frappe.local.site,'company':company,'project':project,
                'contract_id':contract['id'],'checks':checks,'original_operation_id':execute_id,'consumption_count':1,'disabled_original_history_and_receipt_preserved':True,
                'legal_execution':False,'financial_posting':False,'certification':False,'floor_provider_qualified':False,'live_model_qualified':False,'external_provider_qualified':False,
                'started_at':started,'completed_at':datetime.now(timezone.utc).isoformat()}
        return report
    finally:
        frappe.db.rollback();frappe.set_user('Administrator')
        for name in list(restrictions):restore_restriction(name)
        for doctype,name in (('UOM',native_unit),('Currency',currency)):
            doc=frappe.get_doc(doctype,name)
            if doc.enabled!=enabled[doctype]:doc.enabled=enabled[doctype];doc.save(ignore_permissions=True)
            update_permission_property(doctype,role,0,'read',originals[doctype])
        frappe.db.commit();frappe.clear_cache(user=author);frappe.clear_cache(user=reviewer)
        frappe.local.request=saved_request;frappe.session.sid=saved_sid


def read_native_rights_cleanup(contract_id):
    """Independent readback of the owned retained-CI permission fixture."""
    import frappe
    from cipher_aec.construction_finance import repository
    from cipher_aec.governance.context import assert_synthetic_site
    assert_synthetic_site()
    if frappe.session.user!='Administrator' or not frappe.local.site.startswith('cipher-ci-'):
        raise RuntimeError('Only the explicit isolated CI fixture may be inspected.')
    contract=repository.read('contract',contract_id);author=contract['author_user']
    if not author.startswith('fin.author.'):
        raise RuntimeError('Only the retained FIN fixture namespace may be inspected.')
    marker=author.split('@',1)[0].split('.')[2];reviewer='fin.reviewer.'+marker+'@cipher.example';role='FIN01 native source reader '+marker
    revision=repository.read('revision',contract['draft_revision']);native_unit=revision['units'][0]['target']['name']
    flags={doctype:int(frappe.db.get_value('Custom DocPerm',{'parent':doctype,'role':role,'permlevel':0},'read') or 0) for doctype in ('UOM','Currency')}
    restricted=frappe.get_all('User Permission',filters={'user':reviewer,'allow':['in',['UOM','Currency']]},pluck='name')
    enabled={'UOM':int(frappe.db.get_value('UOM',native_unit,'enabled')),'Currency':int(frappe.db.get_value('Currency',contract['definition']['currency'],'enabled'))}
    if restricted or flags!={'UOM':0,'Currency':0} or enabled!={'UOM':1,'Currency':1}:
        raise AssertionError('The retained CI native permission fixture was not restored.')
    return {'status':'passed','site':frappe.local.site,'contract_id':contract_id,'temporary_user_permissions_remaining':0,
            'native_master_enabled_restored':enabled,'owned_native_role_read_flags_restored':flags,'main_site_mutated':False,'user_auth_rows_written':False}

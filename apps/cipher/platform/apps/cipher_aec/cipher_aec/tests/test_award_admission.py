"""Pure exact lineage + SQL lock-boundary/overflow tests; not posting qualification."""
from copy import deepcopy
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
from cipher_aec.api.contracts import digest
from cipher_aec.api.errors import DomainError
from cipher_aec.construction_finance import award_admission as admission,sources
from cipher_aec.tests import test_award_native as native_fixture
identity=native_fixture.identity
fixtures=native_fixture.fixtures


def lineage():
    issue,lines,definition=fixtures()
    case=native_fixture.AwardNative()
    try:
        case.setUp();order=case.actual()
    finally:
        case.doCleanups()
    order['derived_digest']=order['digest']
    baseline={'id':identity('baseline'),'company':'Company A','scope_type':'Company','project':None,'status':'accepted'}
    reference={'acceptance_id':baseline['id'],'acceptance_digest':digest(baseline)}
    issue['accepted_estimate']=reference
    order['projection']['header']['cipher_issue_digest']=digest(issue)
    order['digest']=digest(order['projection']);order['derived_digest']=order['digest']
    plan={'id':identity('award-revision'),'handoff':identity('award'),'company':'Company A','author_person':'requester','issue':issue['id'],
        'issue_digest':digest(issue),'lines':lines,'definition':{'native_order_definition':definition,'contract_definition':{'party_type':'Customer','party':'Existing customer'}},
        'source_facts':{'accepted_estimate':reference},'ids':{'adoption_id':identity('adoption'),'contract_id':identity('contract'),'profile_id':identity('profile'),'line_ids':{row['proposal_line_id']:row['award_line_id'] for row in lines}}}
    a={'id':identity('adoption'),'schema':'cipher.award.adoption.v1','status':'adopted','scope_type':'Company','project':None,
        'company':'Company A','target_project':'Project A','handoff':plan['handoff'],'award_revision':plan['id'],'plan_digest':digest(plan),
        'author_person':'requester','author_user':'author','pursuit':identity('pursuit'),'opportunity':'OPP-native','issue':issue['id'],'issue_digest':digest(issue),
        'accepted_estimate':reference,'contract':identity('contract'),'sales_order':'SO-test','native_snapshot':order,'native_digest':order['digest'],
        'native_version':order['version'],'profile':identity('profile'),'line_adoptions':[r['award_line_id'] for r in lines],
        'packet_id':'packet-native','decision_id':'decision-native','operation_id':identity('operation')}
    origin={'schema':'cipher.contract.award-origin.v1','handoff':plan['handoff'],'award_revision':plan['id'],'plan_digest':digest(plan),'adoption_id':a['id'],
        'sales_order':a['sales_order'],'native_digest':a['native_digest'],'native_version':a['native_version'],'issue':a['issue'],'issue_digest':a['issue_digest'],
        'accepted_estimate':reference,'source_company':'Company A','project':'Project A','definition_digest':digest(plan['definition']['contract_definition']),
        'packet_id':a['packet_id'],'decision_id':a['decision_id'],'operation_id':a['operation_id']}
    contract={'id':a['contract'],'origin':admission.ORIGIN,'company':'Company A','project':'Project A','definition':plan['definition']['contract_definition'],
        'award_origin':origin,'creation_admission':{'provider':admission.INITIAL_PROVIDER}}
    profile={'id':a['profile'],'status':'adopted','company':'Company A','project':'Project A','handoff':plan['handoff'],'award_revision':plan['id'],
        'adoption':a['id'],'contract':contract['id'],'sales_order':a['sales_order']}
    adopted_lines=[{'id':line['award_line_id'],'source_line':line,'proposal_line_id':line['proposal_line_id'],'sales_order_item':order['projection']['rows'][index]['name'],
        'adoption':a['id'],**{key:a[key] for key in ('company','target_project','handoff','award_revision','pursuit','opportunity','issue','issue_digest','sales_order','contract','author_person')}} for index,line in enumerate(lines)]
    outer={'domain':{'effect':{'plan':plan}}}
    packet={'name':a['packet_id'],'manifest_json':json.dumps(outer),'manifest_hash':digest(outer),'action':'award.project.create.v1','scope_type':'Company',
        'company':'Company A','project':None,'subject_id':plan['id'],'subject_type':'Cipher Award Handoff Revision','source_version':digest(plan),'requester_person':'requester'}
    decision={'name':a['decision_id'],'decision':'Grant','packet':packet['name'],'manifest_hash':packet['manifest_hash'],'actor_person':'independent',
        'company':'Company A','scope_type':'Company','project':None}
    effect={'adoption':a,'version':digest(a)}
    consumed={'company':'Company A','scope_type':'Company','project':None,'packet':packet['name'],'decision':decision['name'],'actor_person':'requester',
        'operation_id':a['operation_id'],'result_hash':digest(effect)}
    result={'packet':{'id':packet['name'],'manifest_hash':packet['manifest_hash'],'state':'Consumed'},'effect':effect}
    receipt={'name':digest({'person':'requester','operation_id':a['operation_id']}),'person':'requester','operation_id':a['operation_id'],'scope_type':'Company','project':None,'company':'Company A',
        'command':'approval.execute','request_hash':digest({'scope_type':'Company','command':'approval.execute','company':'Company A','project':None,'payload':{'packet_id':packet['name'],'manifest_hash':packet['manifest_hash']}}),
        'result_json':json.dumps(result),'result_hash':digest(result)}
    return {'native_id':'SO-test','project':{'name':'Project A','company':'Company A','customer':'Existing customer'},'adoption':a,'plan':plan,
        'handoff':{'id':plan['handoff'],'company':'Company A','pursuit':a['pursuit'],'opportunity':'OPP-native','status':'adopted','adoption':a['id']},'contract':contract,'issue':issue,
        'baseline':baseline,'profile':profile,'lines':adopted_lines,'order':order,'packet':packet,'decision':decision,'consumption':consumed,'receipt':receipt}


class AwardLineageTests(unittest.TestCase):
    def setUp(self):self.value=lineage()
    def classify(self,v=None,own=True):return admission.classify(self.value if v is None else v,company='Company A',customer='Existing customer',own_contract_id=self.value['contract']['id'] if own else identity('other-contract'))
    def test_complete_exact_lineage_owns_or_foreign_and_ignores_later_mutable_heads(self):
        self.assertEqual(self.classify(),'recognized-own');self.assertEqual(self.classify(own=False),'recognized-other')
        self.value['contract'].update(draft_revision='later-private-revision',business_revision=30)
        self.value['handoff']['current_revision']='irrelevant-working-head'
        self.assertEqual(self.classify(),'recognized-own')
    def test_missing_or_wrong_real_project_never_inherits_profile_scope(self):
        for value in (None,{'name':'Project A','company':'foreign','customer':'Existing customer'}, {'name':'Project A','company':'Company A','customer':'other'}):
            changed=deepcopy(self.value);changed['project']=value
            with self.subTest(value=value):self.assertEqual(self.classify(changed),'unqualified')
    def test_grant_consumption_receipt_and_full_native_inventory_are_required(self):
        mutations=[lambda v:v.update(consumption=None),lambda v:v.update(lines=[]),lambda v:v['decision'].update(actor_person='requester'),
            lambda v:v['receipt'].update(result_hash='wrong'),lambda v:v['contract']['award_origin'].update(issue='different'),
            lambda v:v['order']['projection']['rows'][0].update(qty='2.000000001'),lambda v:v['baseline'].update(company='foreign'),
            lambda v:v['lines'][0].update(sales_order_item='other-row'),lambda v:v['handoff'].update(adoption='other'),lambda v:v['plan']['ids'].update(adoption_id='other'),
            lambda v:v['plan']['ids'].update(contract_id='other'),lambda v:v['plan']['ids'].update(profile_id='other'),
            lambda v:v['profile'].update(id='other-profile'),lambda v:v['profile'].update(adoption='other-adoption'),
            lambda v:v['receipt'].update(request_hash='wrong'),lambda v:v['order']['projection']['header'].update(project='other-project')]
        for mutate in mutations:
            changed=deepcopy(self.value);mutate(changed)
            with self.subTest(change=mutate):self.assertEqual(self.classify(changed),'unqualified')
        # An old RR snapshot may miss committed foreign immutable lineage. It
        # must refuse instead of inferring zero or following a mutable head.
        for key in ('adoption','plan','handoff','contract','issue','baseline','profile','decision','consumption','receipt'):
            changed=deepcopy(self.value);changed[key]=None
            with self.subTest(missing=key):self.assertEqual(self.classify(changed),'unqualified')
    def test_foreign_canonical_lineage_sql_never_acquires_late_row_locks(self):
        value=self.value
        canonical={'Cipher Award Adoption':value['adoption'],'Cipher Award Handoff Revision':value['plan'],'Cipher Award Handoff':value['handoff'],
            'Cipher Construction Contract':value['contract'],'Cipher Proposal Issue':value['issue'],'Cipher Estimate Acceptance':value['baseline'],'Cipher Project Profile':value['profile'],
            'Cipher Award Line Adoption':value['lines'][0]}
        regular={'Cipher Approval Packet':value['packet'],'Cipher Approval Decision':value['decision'],'Cipher Command Receipt':value['receipt']}
        calls=[]
        def sql(query,args,as_dict=False):
            calls.append(query);self.assertNotIn('FOR UPDATE',query)
            if 'SELECT name,record_digest' in query:return [(value['adoption']['id'],digest(value['adoption']))]
            if query.startswith('SELECT name FROM `tabCipher Award Line Adoption`'):return [(value['lines'][0]['id'],)]
            if 'SELECT name,company,customer' in query:return [('Project A','Company A','Existing customer')]
            if 'tabCipher Approval Consumption' in query:return [value['consumption']]
            for table,record in canonical.items():
                if '`tab'+table+'`' in query:return [(json.dumps(record),digest(record))]
            for table,record in regular.items():
                if '`tab'+table+'`' in query:return [record]
            self.fail(query)
        with patch.object(admission,'frappe',SimpleNamespace(db=SimpleNamespace(sql=sql),DoesNotExistError=type('Missing',(Exception,),{}))), \
            patch('cipher_aec.awards.native.snapshot',return_value=value['order']) as native:
            actual=admission.observe(company='Company A',customer='Existing customer',sales_order_id='SO-test',lock=True)
        native.assert_called_once_with(sales_order_id='SO-test',lock=True)
        self.assertEqual(self.classify(actual),'recognized-own');self.assertTrue(calls)
    def test_nonlocking_inspection_and_consequential_entry_share_predicate_without_mode_parameter(self):
        with patch.object(admission,'observe',return_value=self.value) as observe:
            read=admission.inspect_award_sales_order(company='Company A',customer='Existing customer',sales_order_id='SO-test',own_contract_id=self.value['contract']['id'])
            self.assertFalse(observe.call_args.kwargs['lock'])
            locked=admission.recognize_award_sales_order(company='Company A',customer='Existing customer',sales_order_id='SO-test',own_contract_id=self.value['contract']['id'])
            self.assertTrue(observe.call_args.kwargs['lock'])
        self.assertEqual(read,locked);self.assertEqual(set(read),{'classification','watermark'})


class AwardAdmissionScanTests(unittest.TestCase):
    def setUp(self):self.contract={'id':identity('contract'),'company':'Company A','project':'Project A','definition':{'party_type':'Customer','party':'Existing customer'}}
    def fake(self,rows):
        return SimpleNamespace(db=SimpleNamespace(sql=lambda q,args,**kw:rows if 'FROM `tabSales Order`' in q else [],exists=lambda kind,name:name=='Cipher Award Adoption'))
    def test_overflow_refuses_before_any_recognized_exemption(self):
        rows=[SimpleNamespace(name='SO-'+str(i),docstatus=0,modified='version') for i in range(201)]
        with patch.object(sources,'frappe',self.fake(rows)),patch.object(admission,'recognize_award_sales_order') as classify,self.assertRaises(DomainError) as error:
            sources.admission(self.contract,lock=True)
        self.assertEqual(error.exception.code,'admission_scan_limit');classify.assert_not_called()
    def test_read_scan_never_locks_classifier_and_foreign_obligation_is_not_relabelled_zero(self):
        rows=[SimpleNamespace(name='SO-private',docstatus=0,modified='version')]
        with patch.object(sources,'frappe',self.fake(rows)),patch.object(admission,'inspect_award_sales_order',return_value={'classification':'recognized-other','watermark':'opaque'}) as read, \
            patch.object(admission,'recognize_award_sales_order',side_effect=AssertionError('Read path cannot lock')):
            result=sources.admission(self.contract,lock=False)
        self.assertEqual(result['provider'],'cipher.contract.award-native-admission.v1');self.assertEqual(result['status'],'qualified_award_observations')
        self.assertNotIn('SO-private',json.dumps(result));self.assertEqual(read.call_count,1)
    def test_existing_no_activity_provider_and_watermark_stay_byte_equal(self):
        with patch.object(sources,'frappe',self.fake([])):actual=sources.admission(self.contract)
        channels=['Sales Order','Sales Invoice','Delivery Note','Payment Entry','Journal Entry']+[name+':not_installed' for name in ('Stock Entry','Expense Claim','Timesheet','Material Request',*sources.FUTURE_CHANNELS)]
        original={'provider':sources.ADMISSION_VERSION,'provider_version':1,'contract_id':self.contract['id'],'company':'Company A','project':'Project A','party_type':'Customer','party':'Existing customer',
            'channels':channels,'status':'new_contract_without_supported_obligations','observed':[]}
        self.assertEqual(actual,{'provider':sources.ADMISSION_VERSION,'provider_version':1,'contract_id':self.contract['id'],'status':'new_contract_without_supported_obligations',
            'channel_count':len(channels),'source_watermark':digest(original)})

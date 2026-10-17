"""Host-only case/probe tests. Native DB/HTTP/Redis/worker calls are mocked."""
from contextlib import ExitStack,contextmanager
from copy import deepcopy
import importlib.util
from pathlib import Path
import sys
import tempfile
from threading import get_ident
from types import ModuleType,SimpleNamespace,MethodType
import unittest
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('r15_boundaries_under_test',HERE/'r15_boundaries.py')
b=importlib.util.module_from_spec(spec);spec.loader.exec_module(b)
two=b.v2()
spec2=importlib.util.spec_from_file_location('r15_v2_test_support',HERE.parent/'native-execution-v2/test_r15_execution.py')
fixtures=importlib.util.module_from_spec(spec2);spec2.loader.exec_module(fixtures)
uid=fixtures.uid


def value():
    v=fixtures.value();two._proof(v)[b.KEY]={'schema':b.SCHEMA,'status':'declared','cases':{case:{'status':'declared','action':action,'ids':two.authored_ids()} for case,action in b.CASES.items()}}
    return v


def race_entries():
    entries=[]
    for index in range(2):
        operation=uid(80+index);payload={'company':'Synthetic Company','proposal_id':uid(1),'mapping_version':'1','operation_id':operation}
        entries.append({'operation_id':operation,'payload':payload,'status':200 if index==0 else 409,
            'started_at':'2026-10-17T00:00:00+00:00','completed_at':'2026-10-17T00:00:01+00:00',
            'envelope':{'data':{'operation':{'id':operation,'status':'succeeded','replayed':False}}} if index==0 else {'error':{'code':'draft_already_saved'}}})
    return entries


class FreshCaseRequests(unittest.TestCase):
    def test_each_boundary_request_pins_its_own_fresh_scope_head(self):
        v=value()
        for index,case in enumerate(b.CASES):
            if b.CASES[case]!='aec.scope.draft':continue
            target=uid(100+index);row=b._proof(v)['cases'][case]
            row['targets']={'commercial':{'proposal':{'id':uid(200+index)},'revision':{'id':target}}}
            request=b._request(v,case)
            self.assertEqual(request['arguments']['proposal_revision_id'],target)
            self.assertNotEqual(request['arguments']['proposal_revision_id'],two._proof(v)['targets']['commercial']['revision']['id'])
        self.assertEqual(len(b.CASES),9);self.assertNotIn('unsaved-expiry-r15',two.v1().CASES)

    def test_write_outage_estimate_request_keeps_distinct_line_records(self):
        v=value();case='duty-outage-r15';b._proof(v)['cases'][case]['targets']={'estimate':{'revision':{'id':uid(300),'line_record_ids':[uid(301),uid(302)]}}}
        request=b._request(v,case)
        self.assertEqual(request['arguments']['selections'][0]['line_record_id'],uid(301));self.assertEqual(request['arguments']['selections'][0]['source_id'],uid(302))


class RestorationAttribution(unittest.TestCase):
    def row(self):
        values={key:{'type':'str','value':item} for key,item in {'active':'one','company':'same','modified':'old','modified_by':'admin'}.items()}
        return {'table':'Cipher Project Duty','name':'original-duty','values':values,'columns':{key:two.sha(item) for key,item in values.items()}}

    def test_only_exact_semantic_restoration_and_supported_audit_delta_pass(self):
        before=self.row();after=deepcopy(before);after['values']['modified']['value']='new';after['columns']['modified']=two.sha(after['values']['modified'])
        result=b.restoration(before,after)
        self.assertTrue(result['semantic_restored']);self.assertEqual(result['changed_audit_columns'],['modified'])

    def test_semantic_identity_or_column_set_change_refuse(self):
        for mutate in [lambda x:x.update(name='foreign'),lambda x:x['columns'].update(active='zero'),
                lambda x:x['columns'].update(company='foreign'),lambda x:x['columns'].update(extra='added')]:
            after=self.row();mutate(after)
            with self.assertRaises(AssertionError):b.restoration(self.row(),after)


class RaceEvidence(unittest.TestCase):
    def test_two_real_intervals_one_winner_and_original_loser_are_bound(self):
        result=b.verify_race(race_entries())
        self.assertEqual(result['winner'],uid(80));self.assertEqual(result['loser'],uid(81))

    def test_no_overlap_duplicate_uuid_two_winners_or_uncertain_wire_refuse(self):
        for mutate in [lambda x:x[1].update(started_at='2026-10-17T00:00:02+00:00',completed_at='2026-10-17T00:00:03+00:00'),
                lambda x:x[1].update(operation_id=uid(80)),lambda x:x[1].update(status=200),lambda x:x[1].update(error={'type':'TimeoutError'}),
                lambda x:x[1]['payload'].update(mapping_version='2'),lambda x:x[1]['envelope']['error'].update(code='not_found')]:
            entries=race_entries();mutate(entries)
            with self.assertRaises(AssertionError):b.verify_race(entries)


class InstanceProbe(unittest.TestCase):
    def test_real_instance_persist_completes_before_failure_and_exact_method_restores(self):
        from cipher_aec.ricky.company_draft_save import DraftSaveContext
        context=object.__new__(DraftSaveContext);events=[]
        def persist(self,actor,result):events.append('real-persist')
        original=MethodType(persist,context);context.persist=original
        other=object.__new__(DraftSaveContext);other.persist=MethodType(persist,other)
        with self.assertRaises(b.RollbackProbe):
            with b.instance_persist_probe(context,lambda result:events.append('observed-real-effect')):
                self.assertEqual(other.persist.__func__,persist)
                context.persist('original-actor',{'application':'host-only-result'})
        self.assertEqual(context.persist,original);self.assertEqual(events,['real-persist','observed-real-effect'])

    def test_nonconcrete_context_is_refused(self):
        with self.assertRaises(TypeError):
            with b.instance_persist_probe(SimpleNamespace(persist=lambda *a:None),lambda *a:None):pass

    def test_bench_admin_or_missing_genuine_request_cannot_enter_probe(self):
        v=value();row=b._proof(v)['cases']['rollback-r15'];row.update(status='reviewed',terminal={'run':{'authority':{'session_reference':'a'*64}}})
        fake=ModuleType('frappe');fake.session=SimpleNamespace(sid='unrelated');fake.local=SimpleNamespace(request=None)
        context=ModuleType('cipher_aec.governance.context');context.current_actor=lambda:SimpleNamespace(user='Administrator',person_id='admin-person')
        with patch.object(b,'_value',return_value=v),patch.dict(sys.modules,{'frappe':fake,'cipher_aec.governance.context':context}):
            with self.assertRaises(RuntimeError):b.rollback_current_request('new-r15')


class SupportedDutyFinally(unittest.TestCase):
    def test_http_failure_still_restores_exact_existing_duty_via_supported_save(self):
        v=value();v['duties']={'document.read':'original-duty'};case='source-outage-r15';b._proof(v)['cases'][case]['status']='reviewed'
        values={'name':'original-duty','company':v['company'],'person':v['users']['author']['person'],'scope_type':'Company',
            'project':None,'ability':'document.read','active':1,'modified':0,'modified_by':'Administrator'}
        events=[]
        class Doc(SimpleNamespace):
            def get(self,key):return getattr(self,key,None)
            def save(self,**kwargs):
                self.modified+=1;values.update(self.__dict__);events.append(('save',self.active))
        def row(table,name):
            native={key:{'type':'int','value':str(item)} if type(item) is int else {'type':'str','value':item} for key,item in values.items()}
            return {'table':table,'name':name,'values':native,'columns':{key:two.sha(item) for key,item in native.items()}}
        fake=ModuleType('frappe');fake.get_doc=lambda *a:Doc(**values);fake.db=SimpleNamespace(commit=lambda:events.append('commit'))
        context=ModuleType('cipher_aec.governance.context')
        @contextmanager
        def trusted():yield
        context.trusted_write=trusted
        def update(path,case,**fields):b._proof(v)['cases'][case].update(deepcopy(fields));return v
        with patch.object(b,'_value',return_value=v),patch.object(b,'_case',side_effect=update),patch.object(b,'_row',side_effect=row),\
                patch.dict(sys.modules,{'frappe':fake,'cipher_aec.governance.context':context}):
            with self.assertRaisesRegex(OSError,'host-only'):
                with b.duty_outage('new-r15',case,'document.read'):
                    self.assertEqual(values['active'],0);raise OSError('host-only actual-wire failure')
        self.assertEqual(values['active'],1);self.assertEqual(events,[('save',0),'commit',('save',1),'commit'])
        self.assertEqual(b._proof(v)['cases'][case]['restoration']['changed_audit_columns'],['modified'])


class SerialRaceJournal(unittest.TestCase):
    def test_intents_fsync_serial_and_threads_never_write_shared_journal(self):
        v=value();case='two-operation-r15';row=b._proof(v)['cases'][case];row.update(status='reviewed',reviewed={'proposal_id':uid(1),'mapping_version':'1'},
            run_id=uid(2),terminal={'payloads':{'run':{'run':'exact'}}})
        auth={'users':{'original-user':'exact'},'timezone':'actual-policy'};sessions={'author':'exact'}
        two._proof(v)['wires']=[{'after':auth,'sessions_after':sessions}]
        operations=[];events=[];main=get_ident()
        class Journal:
            def __init__(self,directory):self.rows=[]
            def prepare(self,key,role,method,fields):
                self.rows.append({'key':key,'role':role,'method':method,'operation_id':uid(80+len(self.rows)),
                    'payload':{**fields,'operation_id':uid(80+len(self.rows))},'attempts':[]})
                events.append(('intent',get_ident()));return self.rows[-1]
            def response(self,intent,**kwargs):events.append(('response',get_ident()));intent['attempts'].append(kwargs)
            def uncertain(self,*args):events.append(('uncertain',get_ident()))
        support=SimpleNamespace(Journal=Journal,write_private=lambda p,item:None)
        continuation=SimpleNamespace(user_transition=lambda *a:[])
        def update(path,case,**fields):b._proof(v)['cases'][case].update(deepcopy(fields));v['stages'][two.v1().KEY]['cases'][case]=deepcopy(b._proof(v)['cases'][case]);return v
        def wire(rpc,intent,barrier):
            barrier.wait(timeout=2);entry=race_entries()[int(intent['operation_id'][-1])%2]
            entry['payload']=deepcopy(intent['payload']);entry['operation_id']=intent['operation_id']
            if entry['status']==200:entry['envelope']['data']={'operation':{'id':intent['operation_id'],'status':'succeeded','replayed':False},'application':{'id':'host-only'},'saved':{}}
            return entry
        v['journal_directory']='new-r15'
        openapi={'paths':{'/api/method/'+two.v1().SAVE+'save_draft':{'post':{'requestBody':{'content':{'application/json':{'schema':{'type':'object'}}}}}}},'components':{}}
        with patch.object(b,'v2',return_value=two),patch.object(b,'_value',return_value=v),patch.object(b,'_case',side_effect=update),\
                patch.object(b,'_race_wire',side_effect=wire),patch.object(two,'client',return_value=SimpleNamespace(openapi=openapi)),\
                patch.object(two,'_support',return_value=(support,None,None,continuation)),patch.object(two,'_observe_users',return_value=auth),\
                patch.object(two,'_observe_sessions',return_value=sessions),patch.object(two,'session_transition',return_value=[]),\
                patch.object(two,'observe_native',return_value={'actual':'independent'}),patch.object(two,'verify_saved_state',return_value={}),\
                patch.object(two,'_run',return_value=row['terminal']),patch.object(b,'_evidence',return_value={'path':'host-only','sha256':'a'*64,'bytes':1}):
            result=b.two_operation_posts('new-r15','http://unused','synthetic.localhost')
        self.assertEqual(result['status'],'passed');self.assertEqual([event for event,thread in events],['intent','intent','response','response'])
        self.assertTrue(all(thread==main for event,thread in events));self.assertEqual(two._proof(v)['wires'][-1]['status'],'verified-batch')
        self.assertEqual(len(two._proof(v)['wires'][-1]['entries']),2)


class OneShotStorage(unittest.TestCase):
    def test_inventory_sidecar_is_private_hashed_and_cannot_be_overwritten(self):
        with tempfile.TemporaryDirectory(prefix='cipher-r15-v3-host-only-') as directory:
            path=Path(directory)/'fixture.secret.json';payload={'rows':{'original':{'hash':'a'*64}}}
            reference=b._evidence(path,'baseline','baseline',payload)
            actual=Path(reference['path']);self.assertTrue(actual.is_file());self.assertFalse(actual.stat().st_mode&0o077)
            self.assertEqual(reference['bytes'],actual.stat().st_size)
            self.assertEqual(reference['sha256'],__import__('hashlib').sha256(actual.read_bytes()).hexdigest())
            with self.assertRaises(FileExistsError):b._evidence(path,'baseline','baseline',{'replacement':True})
            self.assertEqual(__import__('json').loads(actual.read_text()),payload)
            with self.assertRaises(ValueError):b._evidence(path,'../../old','baseline',{})


class ExactRestoreAudit(unittest.TestCase):
    def test_only_literal_original_duty_row_can_receive_audit_column_attribution(self):
        v=value();v['duties']={'document.read':'original-duty'}
        before=RestorationAttribution().row();after=deepcopy(before)
        after['values']['modified']['value']='new';after['columns']['modified']=two.sha(after['values']['modified'])
        note=b.restoration(before,after);b._proof(v)['cases']['source-outage-r15']['restoration']=note
        baseline={'inventory':{'Cipher Project Duty':{'original-duty':before['columns']}}}
        current={'inventory':{'Cipher Project Duty':{'original-duty':after['columns']}}}
        normalized,notes=b.restored_inventory(v,baseline,current)
        self.assertEqual(normalized,baseline);self.assertEqual(len(notes),1);self.assertEqual(current['inventory']['Cipher Project Duty']['original-duty'],after['columns'])
        v['duties']['document.read']='different-existing-duty'
        with self.assertRaises(AssertionError):b.restored_inventory(v,baseline,current)

    def test_other_case_cannot_invent_old_row_exception(self):
        v=value();before=RestorationAttribution().row();note=b.restoration(before,before)
        b._proof(v)['cases']['rollback-r15']['restoration']=note
        state={'inventory':{'Cipher Project Duty':{'original-duty':before['columns']}}}
        with self.assertRaises(AssertionError):b.restored_inventory(v,state,state)


class AggregateBatchAttribution(unittest.TestCase):
    def fixture(self):
        v=value();entries=race_entries();result=b.verify_race(entries);row=b._proof(v)['cases']['two-operation-r15']
        row['race_intents']=[{'operation_id':entry['operation_id'],'payload':deepcopy(entry['payload'])} for entry in entries];row['race']=result
        batch={'batch':'two-operation-r15','status':'verified-batch','threads_alive':[False,False],'entries':entries,
            'outcome':result,'started_at':result['started_at'],'completed_at':result['completed_at']}
        two._proof(v)['wires']=[batch];return v

    def test_one_explicit_batch_is_normalized_only_in_private_verifier_view(self):
        v=self.fixture();shadow=b._batch_ledger(v)
        self.assertEqual(two._proof(shadow)['wires'][0]['status'],'verified')
        self.assertEqual(two._proof(v)['wires'][0]['status'],'verified-batch')

    def test_broad_dispatch_window_or_changed_original_intent_refuses(self):
        for mutate in [lambda v:two._proof(v)['wires'][0].update(started_at='2026-10-16T23:59:00+00:00'),
                lambda v:b._proof(v)['cases']['two-operation-r15']['race_intents'][0]['payload'].update(mapping_version='2')]:
            v=self.fixture();mutate(v)
            with self.assertRaises(AssertionError):b._batch_ledger(v)


if __name__=='__main__':unittest.main()

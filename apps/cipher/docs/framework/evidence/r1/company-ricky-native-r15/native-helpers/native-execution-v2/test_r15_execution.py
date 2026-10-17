"""Host collaborators only; no HTTP, native DB, Redis or worker execution."""
from copy import deepcopy
from datetime import datetime,timezone
from zoneinfo import ZoneInfo
import ast
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('r15_execution_under_test',HERE/'r15_execution.py')
r=importlib.util.module_from_spec(spec);spec.loader.exec_module(r)


def uid(n): return '00000000-0000-4000-8000-'+str(n).zfill(12)


def value():
    old=r.v1()
    targets={'commercial':{'proposal':{'id':uid(8)},'revision':{'id':uid(9)}},
        'estimate':{'estimate':{'id':uid(10)},'revision':{'id':uid(11),'line_record_ids':[uid(12),uid(13)]}}}
    return {'company':'Synthetic Company','site':'synthetic.localhost','native':{},
        'users':{role:{'user':role+'@example.test','person':'author-person' if role!='outsider' else 'other-person'} for role in ('author','alias','outsider')},
        'inputs':{'citation':{'id':'d'*64,'revision_id':'REV-'+'a'*32,'page':1,'excerpt_sha256':'b'*64,'source_sha256':'c'*64},
            'pursuit':{'id':uid(1)},'units':[{'id':uid(2),'revision':1}],'rate':{'id':uid(3)},'conversion':{'id':uid(4)},
            'estimate':{'id':uid(5)},'proposal':{'id':uid(6)}},
        'stages':{old.KEY:{'baseline':{'path':'baseline'},'cases':{c:{'status':'declared','action':a} for c,a in old.CASES.items()},
            r.KEY:{'schema':r.SCHEMA,'status':'prepared','targets':targets,'ids':r.authored_ids(),'wires':[]}}}}


class AuthoredTargets(unittest.TestCase):
    def test_composition_is_exact_manual_source_and_stable_ids(self):
        v=value();before=deepcopy(v);ids=r._proof(v)['ids']
        result=r.target_composition(v,ids,{'price_list':'Original Selling','year_end':'2026-12-31'})
        self.assertEqual(v,before);self.assertEqual(result['price_lines'][0]['quantity'],'2.000000')
        self.assertEqual(result['sections'][0]['id'],ids['scope_section'])
        self.assertEqual(result['price_lines'][0]['id'],ids['scope_price_line'])
        self.assertIsNone(result['estimate_revision']);self.assertNotIn('estimate_reference',result)
        self.assertEqual(result['source_references'][0]['revision_id'],v['inputs']['citation']['revision_id'])
        self.assertIsNone(result['price_lines'][0]['item_code'])

    def test_estimate_target_and_source_are_distinct_and_no_waste(self):
        v=value();ids=r._proof(v)['ids'];before=deepcopy(v)
        result=r.target_estimate_fields(v,ids,uid(20))
        self.assertEqual([x['quantity']['amount'] for x in result['lines']],['2.000000','3.000000'])
        self.assertEqual(len({x['line_id'] for x in result['lines']}),2)
        self.assertTrue(all(x['waste_fraction']=='0' and x['material_factor']=='1' for x in result['lines']))
        self.assertEqual(result['conversion_ids'],[v['inputs']['conversion']['id']]);self.assertEqual(v,before)

    def test_request_uses_original_record_identity_and_exact_source(self):
        v=value();before=deepcopy(v)
        scope=r.exact_request(v,'scope-r15');estimate=r.exact_request(v,'estimate-r15')
        self.assertEqual(scope['arguments']['proposal_revision_id'],uid(9))
        self.assertEqual(estimate['arguments']['selections'][0],{'line_record_id':uid(12),'source_kind':'estimate-line',
            'source_id':uid(13),'target_unit_id':uid(2)})
        self.assertEqual(estimate,r.exact_request(v,'estimate-r15'));self.assertEqual(v,before)
        self.assertEqual(set(estimate['sources'][0]),{'citation_id','revision_id','page','excerpt_sha256','source_sha256'})
        self.assertEqual(estimate['measurement_ids'],[])
        with self.assertRaises(ValueError):r.exact_request(v,'estimate-r14')

    def test_missing_or_repeated_line_records_refuse_request(self):
        for lines in ([uid(12)],[uid(12),uid(12)]):
            v=value();r._proof(v)['targets']['estimate']['revision']['line_record_ids']=lines
            with self.assertRaises(AssertionError):r.exact_request(v,'estimate-r15')


class OrdinaryQueueEvidence(unittest.TestCase):
    def evidence(self):
        base={'site':'synthetic.localhost','queue':'isolated:short','workers':[],'started_jobs':[]}
        before={**base,'jobs':[{'id':'job-1','run_id':uid(30),'site':base['site'],'queue':base['queue'],
            'func_name':'frappe.utils.background_jobs.execute_job','method':'cipher_aec.ricky.worker.process_run',
            'kwargs':{'run_id':uid(30)},'status':'queued'}]}
        after={**base,'jobs':[],'completed':[{'id':'job-1','run_id':uid(30),'status':'finished','worker_name':'ordinary-worker',
            'started_at':'2026-10-17T00:00:00+00:00','ended_at':'2026-10-17T00:00:01+00:00'}]}
        return before,after

    def check(self,b,a):return r.verify_queue_evidence(b,a,site='synthetic.localhost',queue='isolated:short',run_id=uid(30))

    def test_original_job_and_actual_ordinary_worker_are_retained(self):
        b,a=self.evidence();self.assertEqual(self.check(b,a)['job_id'],'job-1')

    def test_foreign_queue_job_kwargs_and_incomplete_worker_refuse(self):
        for mutate in [lambda b,a:b.update(queue='foreign:short'),lambda b,a:b['jobs'][0].update(run_id=uid(31)),
                lambda b,a:b['jobs'][0].update(kwargs={'run_id':uid(30),'force':True}),lambda b,a:a.update(workers=['leftover']),
                lambda b,a:a['completed'][0].update(id='replacement'),lambda b,a:a['completed'][0].update(worker_name=None),
                lambda b,a:a['completed'][0].update(ended_at='2026-10-16T23:00:00+00:00')]:
            b,a=self.evidence();mutate(b,a)
            with self.assertRaises(AssertionError):self.check(b,a)


class TargetDriver(unittest.TestCase):
    def setUp(self):
        self.v=value();r._proof(self.v)['targets']={};self.calls=[]
        self.support=SimpleNamespace(load_private=lambda p:{'plan':{'price_list':'Original Selling','year_end':'2026-12-31','pricing_date':'2026-10-17'}})
        self.v['stages'][r.v1().KEY]['prerequisite']={'path':'retained-prerequisite'}
        self.stack=__import__('contextlib').ExitStack();self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(r,'_value',side_effect=lambda p:deepcopy(self.v)))
        self.stack.enter_context(patch.object(r,'_support',return_value=(self.support,None,None,None)))
        def save(path,**fields):r._proof(self.v).update(deepcopy(fields));return deepcopy(self.v)
        self.stack.enter_context(patch.object(r,'_save',side_effect=save))

    def rpc(self,method,values,**kwargs):
        self.calls.append((method,deepcopy(values),kwargs))
        old=r.v1()
        if method==old.COMMERCIAL+'create_proposal':data={'proposal':{'id':uid(40)},'revision':{'id':uid(41)}}
        elif method==old.EST+'create_estimate':data={'estimate':{'id':uid(42)}}
        else:data={'estimate':{'id':uid(42)},'revision':{'id':uid(43),'line_record_ids':[uid(44),uid(45)]}}
        return {'status':200,'envelope':{'data':data}}

    def test_three_fixed_commands_create_new_owners_before_any_start(self):
        self.stack.enter_context(patch.object(r,'client',return_value=SimpleNamespace(call=self.rpc)))
        result=r.create_targets('new-r15','http://unused','synthetic.localhost')
        self.assertEqual(result['status'],'targets-ready');self.assertEqual(len(self.calls),3)
        self.assertEqual([c[2]['key'] for c in self.calls],['r15-create-commercial','r15-create-estimate','r15-calculate-original'])
        self.assertEqual(self.calls[2][1]['estimate_id'],uid(42));self.assertIsNone(self.calls[2][1]['expected_revision'])
        with self.assertRaises(RuntimeError):r.create_targets('new-r15','http://unused','synthetic.localhost')

    def test_partial_failure_preserves_new_target_and_blocks_implicit_retry(self):
        def fail(method,values,**kwargs):
            if len(self.calls):raise OSError('host-only simulated transport failure')
            return self.rpc(method,values,**kwargs)
        self.stack.enter_context(patch.object(r,'client',return_value=SimpleNamespace(call=fail)))
        with self.assertRaises(OSError):r.create_targets('new-r15','http://unused','synthetic.localhost')
        self.assertEqual(r._proof(self.v)['status'],'targets-failed')
        self.assertEqual(r._proof(self.v)['targets']['commercial']['proposal']['id'],uid(40))
        with self.assertRaises(RuntimeError):r.create_targets('new-r15','http://unused','synthetic.localhost')


def saved_fixture(test,estimate=False):
    from cipher_aec.tests.test_ricky_company_draft_saves import ready_scope
    from cipher_aec.tests import test_ricky_company_proposals as proposals
    from cipher_aec.ricky.company_draft_save_contracts import derive,binding,application_id,COMMANDS
    from cipher_aec.estimating.calculation import calculate
    f,ctx=ready_scope(test)
    if estimate:
        snapshot=f.boundary.fixture.records['snapshot',f.boundary.fixture.snapshot_id]
        for definition in snapshot['inputs']['unit_manifest']['unit_conversions']:
            f.boundary.fixture.records['conversion',definition['id']]={'id':definition['id'],'scope_type':'Company','project':None,
                'company':ctx.company,'definition':deepcopy(definition),'source_citations':[]}
        started,_=f.start(proposals.estimate_request(f.boundary));f.service.process(started['id'])
        run=f.store.get('run',started['id']);proposal=f.store.get('proposal',run['proposal_ids'][0])
        payload=derive(proposal,run,f.boundary.originals());case='estimate-r15'
    else:run,proposal,payload=ctx.run,ctx.proposal,ctx.payload;case='scope-r15'
    invocation=f.store.find('invocation',{'run_id':run['id']})[0]
    action=proposal['action'];command,canonical_command,domain=COMMANDS[action];commercial=domain=='commercial'
    base=run['request']['arguments']['proposal_revision_id' if commercial else 'base_revision_id']
    target=payload['proposal_id' if commercial else 'estimate_id'];revision_id=uid(60)
    if commercial:
        native={'id':'R15-new-quotation','items':[{'name':'R15-item'}]}
        revision={'id':revision_id,'company':run['company'],'proposal':target,'predecessor':base,'revision_number':2,
            'composition':deepcopy(payload['composition']),'native':native,'native_fingerprint':r.sha(native)}
        parent={'id':target,'company':run['company'],'current_revision':revision_id,'quotation':native['id'],'native_fingerprint':r.sha(native),'revision_number':2}
        saved={'proposal':parent,'revision':revision}
    else:
        original=f.boundary.fixture.records['snapshot',f.boundary.fixture.snapshot_id]
        inputs=deepcopy(original['inputs'])
        for key in ('lines','adjustments','basis_description'):inputs[key]=deepcopy(payload[key])
        calculated=calculate(inputs);snapshot={'id':uid(61),'company':run['company'],'scope_type':'Company','project':None,
            'inputs':inputs,'result':calculated,'input_digest':calculated['input_digest'],'output_digest':calculated['output_digest']}
        revision={'id':revision_id,'company':run['company'],'estimate':target,'predecessor':base,'revision_number':2,
            'calculation_snapshot':snapshot['id'],'line_record_ids':[uid(70+i) for i in range(len(payload['lines']))],
            **{key:calculated[key] for key in ('direct','indirect','contingency','total')}}
        parent={'id':target,'company':run['company'],'current_revision':revision_id,'revision_number':2}
        saved={'estimate':parent,'revision':revision,'calculation':snapshot}
    person=f.boundary.actor.person_id;operation=uid(99)
    core={'schema':'cipher.ricky.company.draft-save.v1','id':application_id(proposal['id']),'scope_type':'Company','project':None,
        'company':run['company'],'user':f.boundary.actor.user,'person':person,'proposal_id':proposal['id'],'proposal_version':proposal['version'],
        'proposal_digest':proposal['content_digest'],'run_id':run['id'],'step_id':invocation['step_id'],'invocation_id':invocation['id'],
        'preparation_digest':invocation['output_digest'],'manifest_digest':run['original_manifest_digest'],'action':action,
        'classification':'unverified-author-suggestion','mapping_version':'1','payload_digest':r.sha(payload),'command':command,'canonical_command':canonical_command,
        'target_doctype':'Cipher Proposal' if commercial else 'Cipher Estimate','target_id':target,'base_revision_id':base,
        'saved_doctype':'Cipher Proposal Revision' if commercial else 'Cipher Estimate Revision','saved_revision_id':revision_id,'saved_revision_digest':r.sha(revision),
        'operation_id':operation,'receipt_id':r.sha({'person':person,'operation_id':operation}),'created_at':'2026-10-17T00:00:00+00:00'}
    core['core_digest']=r.sha(core);response={'application':core,'saved':saved,'operation':{'id':operation,'status':'succeeded','replayed':False}}
    v=value();v['company']=run['company'];v['inputs']['citation']=deepcopy(f.boundary.fixture.citation_value)
    v['users']['author']={'user':f.boundary.actor.user,'person':person}
    reviewed=binding(proposal,payload)
    row={'status':'saved','saved':response,'review':{'payload':payload,'payload_digest':r.sha(payload),'proposal_version':proposal['version'],'proposal_digest':proposal['content_digest']},
        'reviewed':reviewed,'proposal_id':proposal['id'],'run_id':run['id'],
        'terminal':{'run':run,'children':{'proposal':[proposal],'invocation':[invocation]}}}
    v['stages'][r.v1().KEY]['cases'][case]=row
    tables={('commercial','proposal-revision'):'Cipher Proposal Revision',('estimate','revision'):'Cipher Estimate Revision',
        ('estimate','snapshot'):'Cipher Calculation Snapshot',('estimate','line'):'Cipher Estimate Line',('estimate','conversion'):'Cipher Unit Conversion'}
    state={'records':{table:{} for table in ('Cipher Proposal','Cipher Proposal Revision','Cipher Estimate','Cipher Estimate Revision',
        'Cipher Calculation Snapshot','Cipher Estimate Line','Cipher Unit Conversion','Cipher Ricky Draft Save')},'applications':{},'receipts':{},'history':{},'quotations':{}}
    def add(table,item,name=None):
        name=name or item['id'];state['records'][table][name]={'value':deepcopy(item),'raw':r.canonical(item),'digest':r.sha(item)}
    for key,item in f.boundary.originals().items():
        if key[:2] in tables:add(tables[key[:2]],item)
    add(core['saved_doctype'],revision);add(core['target_doctype'],parent)
    if commercial:state['quotations'][native['id']]=native
    else:
        add('Cipher Calculation Snapshot',snapshot)
        for i,name in enumerate(revision['line_record_ids']):add('Cipher Estimate Line',{'id':name,'estimate_revision':revision_id,
            'authored':payload['lines'][i],'calculated':snapshot['result']['lines'][i]})
    retained={'application':core,'saved':saved};add('Cipher Ricky Draft Save',{'core':core,'receipt_result_hash':r.sha(retained)},core['id'])
    state['applications'][core['id']]={'name':core['id'],'company':core['company'],'scope_type':'Company','project':None,
        'requested_by':core['user'],'person':person,'source_proposal':core['proposal_id'],'run':run['id'],'step':core['step_id'],
        'invocation':core['invocation_id'],'receipt':core['receipt_id'],'saved_doctype':core['saved_doctype'],'saved_revision':revision_id}
    request={'scope_type':'Company','company':core['company'],'project':None,'command':command,
        'payload':{'reviewed':reviewed,'canonical_command':canonical_command,'canonical_payload':payload}}
    state['receipts'][core['receipt_id']]={'name':core['receipt_id'],'person':person,'operation_id':operation,'company':core['company'],
        'scope_type':'Company','project':None,'command':command,'request_hash':r.sha(request),'result_json':r.canonical(retained),'result_hash':r.sha(retained),'state':'Succeeded'}
    previous='old-head'
    for name,event,doctype,subject in [('domain-event','commercial.proposal.revision.created' if commercial else 'estimate.revision.calculated',core['saved_doctype'],revision_id),
            ('application-event','ricky.company.proposal.draft-saved','Cipher Ricky Draft Save',core['id'])]:
        body={'scope_type':'Company','company':core['company'],'project':None,'actor':person,'event':event,'subject_type':doctype,'subject_id':subject,
            'operation_id':operation,'details':{},'previous_hash':previous}
        item={**body,'name':name,'actor_person':person,'details_json':'{}','event_payload':r.canonical(body),'event_hash':r.sha(body)}
        del item['actor'];del item['details'];state['history'][name]=item;previous=item['event_hash']
    return v,case,state


class IndependentSavedReadback(unittest.TestCase):
    def test_scope_native_quote_and_original_mapping_are_verified(self):
        v,case,state=saved_fixture(self);self.assertEqual(r.verify_saved_state(v,case,state)['events'][1]['name'],'application-event')

    def test_estimate_recomputes_actual_snapshot_and_original_mapping(self):
        v,case,state=saved_fixture(self,True);self.assertEqual(r.verify_saved_state(v,case,state)['application']['action'],'aec.estimate.draft')

    def test_header_receipt_native_mapping_and_chain_tampering_refuse(self):
        for field in ('header','receipt','native','history','preparation'):
            with self.subTest(field=field):
                v,case,state=saved_fixture(self);row=v['stages'][r.v1().KEY]['cases'][case];core=row['saved']['application']
                if field=='header':state['applications'][core['id']]['requested_by']='alias@example.test'
                elif field=='receipt':state['receipts'][core['receipt_id']]['request_hash']='0'*64
                elif field=='native':state['quotations']['R15-new-quotation']['items'][0]['name']='foreign-item'
                elif field=='history':state['history']['application-event']['previous_hash']='wrong-head'
                else:row['terminal']['children']['invocation'][0]['output_digest']='0'*64
                with self.assertRaises(AssertionError):r.verify_saved_state(v,case,state)

    def test_historical_readback_accepts_later_head_but_retains_saved_immutable_rows(self):
        v,case,state=saved_fixture(self);core=v['stages'][r.v1().KEY]['cases'][case]['saved']['application']
        parent=state['records']['Cipher Proposal'][core['target_id']];parent['value']['current_revision']=uid(100)
        parent['raw']=r.canonical(parent['value']);parent['digest']=r.sha(parent['value'])
        state['quotations']['R15-new-quotation']={'id':'R15-new-quotation','items':[{'name':'later-item'}]}
        r.verify_saved_state(v,case,state,current=False)
        with self.assertRaises(AssertionError):r.verify_saved_state(v,case,state,current=True)


def actual_transition_functions():
    path=Path(importlib.util.find_spec('cipher_aec.tests.ricky_company_proposal_continuation').origin)
    tree=ast.parse(path.read_text());names={'_time','_active','user_transition'}
    pure=ast.Module(body=[node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name in names],type_ignores=[])
    policy={'configured':None,'effective':'Asia/Kolkata','native_timestamp':'naive-local','wire_timestamp':'UTC'}
    namespace={'datetime':datetime,'timezone':timezone,'ZoneInfo':ZoneInfo,'sha':r.sha,'ROLES':('author','alias','outsider'),'TIMEZONE_POLICY':policy}
    exec(compile(pure,str(path),'exec'),namespace)
    return SimpleNamespace(TIMEZONE_POLICY=policy,
        **{name:namespace[name] for name in names})


def auth_observations(v):
    policy=actual_transition_functions().TIMEZONE_POLICY
    users={};sessions={}
    for i,(role,owner) in enumerate(v['users'].items()):
        old={'type':'datetime','value':'2026-10-17T05:29:59'}
        users[owner['user']]={'columns':{'name':r.sha(owner['user']),'last_active':r.sha(old)},'last_active':old}
        sessions[role]={'reference':str(i)*64,'user':owner['user'],'columns':{'sid':r.sha('host-only-placeholder-'+role),
            'user':r.sha(owner['user']),'lastupdate':'old-update','sessiondata':'old-data'},
            'data':{'lang':r.sha('en'),'session_ip':r.sha('127.0.0.1'),'last_updated':r.sha(old['value'])},
            'lastupdate':old,'last_updated':old['value']}
    next_users=deepcopy(users);next_sessions=deepcopy(sessions)
    when='2026-10-17T05:30:00.500000';native_time={'type':'datetime','value':when};author=v['users']['author']['user']
    next_users[author]['last_active']=native_time;next_users[author]['columns']['last_active']=r.sha(native_time)
    next_sessions['author']['lastupdate']=native_time;next_sessions['author']['last_updated']=when
    next_sessions['author']['columns'].update(lastupdate='new-update',sessiondata='new-data')
    next_sessions['author']['data']['last_updated']=r.sha(when)
    before={'users':users,'timezone':policy};after={'users':next_users,'timezone':policy}
    return before,after,sessions,next_sessions


class WireHeartbeatEvidence(unittest.TestCase):
    def setUp(self):
        self.v=value();self.before,self.after,self.sessions,self.next_sessions=auth_observations(self.v)
        self.native_baseline={'auth_sessions':self.sessions}
        r._proof(self.v)['baseline']={'path':'v2-baseline'}
        self.stack=__import__('contextlib').ExitStack();self.addCleanup(self.stack.close)
        def save(path,v):self.v=deepcopy(v)
        support=SimpleNamespace(load_private=lambda p:self.native_baseline if p=='v2-baseline' else {'users':self.before},write_private=save)
        self.stack.enter_context(patch.object(r,'_support',return_value=(support,None,None,actual_transition_functions())))
        self.stack.enter_context(patch.object(r,'_value',side_effect=lambda p:deepcopy(self.v)))
        self.stack.enter_context(patch.object(r,'_observe_users',side_effect=lambda v:deepcopy(self.before if not getattr(self,'sent',False) else self.after)))
        self.stack.enter_context(patch.object(r,'_observe_sessions',side_effect=lambda v:deepcopy(self.sessions if not getattr(self,'sent',False) else self.next_sessions)))
        self.stack.enter_context(patch.object(r,'stamp',side_effect=['2026-10-17T00:00:00+00:00','2026-10-17T00:00:01+00:00']))
        self.rpc=SimpleNamespace(path='new-r15',role='author',last_wire_observation={'status':200})

    def send(self,*args,**kwargs):self.sent=True;return (200,{'message':{}},0.1)

    def test_actual_pinned_user_and_session_transition_is_wire_bounded(self):
        r.observed_wire(self.rpc,self.send,'GET','/bounded')
        entry=r._proof(self.v)['wires'][0]
        self.assertEqual(entry['status'],'verified');self.assertEqual(entry['started_at'],'2026-10-17T00:00:00+00:00')
        self.assertEqual(len(entry['changes']),1);self.assertEqual(len(entry['session_changes']),1)

    def test_transport_error_is_persisted_before_reraising(self):
        def fail(*args,**kwargs):self.sent=True;raise OSError('host-only wire failure')
        with self.assertRaises(OSError):r.observed_wire(self.rpc,fail,'GET','/bounded')
        entry=r._proof(self.v)['wires'][0];self.assertEqual(entry['wire_error'],{'type':'OSError'})
        self.assertIn('after',entry);self.assertNotIn('status',entry)

    def test_broad_observer_window_cannot_excuse_update_before_actual_wire(self):
        self.stack.enter_context(patch.object(r,'stamp',side_effect=['2026-10-17T00:00:01+00:00','2026-10-17T00:00:02+00:00']))
        with self.assertRaises(AssertionError):r.observed_wire(self.rpc,self.send,'GET','/bounded')
        self.assertEqual(len(r._proof(self.v)['wires']),1);self.assertNotIn('status',r._proof(self.v)['wires'][0])

    def test_unrelated_user_change_refuses_before_send(self):
        self.before['users'][self.v['users']['alias']['user']]['columns']['name']='foreign'
        self.native_baseline={**self.native_baseline}
        # Baseline must retain the real prior users, independent of observation.
        support=SimpleNamespace(load_private=lambda p:self.native_baseline if p=='v2-baseline' else {'users':auth_observations(self.v)[0]},write_private=lambda *a:None)
        self.stack.enter_context(patch.object(r,'_support',return_value=(support,None,None,actual_transition_functions())))
        with self.assertRaises(AssertionError):r.observed_wire(self.rpc,self.send,'GET','/bounded')
        self.assertFalse(getattr(self,'sent',False))

    def test_changed_lang_ip_or_other_session_refuses_exact_heartbeat_rule(self):
        for role,key in [('author','lang'),('author','session_ip'),('alias','lang')]:
            changed=deepcopy(self.next_sessions);changed[role]['data'][key]=r.sha('foreign')
            with self.assertRaises(AssertionError):r.session_transition(self.sessions,changed,'author',
                '2026-10-17T00:00:00+00:00','2026-10-17T00:00:01+00:00')


class FinalPreservation(unittest.TestCase):
    def setUp(self):
        self.v=value();r._proof(self.v)['targets']={}
        b,a,s,n=auth_observations(self.v)
        self.support=SimpleNamespace(load_private=lambda p:{'users':b})
        self.stack=__import__('contextlib').ExitStack();self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(r,'_support',return_value=(self.support,None,None,actual_transition_functions())))
        inventory={'User':{name:row['columns'] for name,row in b['users'].items()},
            'Sessions':{row['reference']:row['columns'] for row in s.values()},'Project':{'original-project':{'column':'unchanged'}},
            'Sales Invoice':{'original-invoice':{'amount':'unchanged'}},'Cipher History Event':{}}
        self.before={'inventory':inventory,'auth_sessions':s,'config':{'raw':'same'},'source':{'sha256':'same'},'indexes':['unique'],'company_head':'old-head'}
        self.after=deepcopy(self.before);self.after['receipts']={};self.after['history']={};self.after['quotations']={}
        self.after['inventory']['User']={name:row['columns'] for name,row in a['users'].items()}
        self.after['inventory']['Sessions']={row['reference']:row['columns'] for row in n.values()}
        cont=actual_transition_functions()
        wire={'status':'verified','role':'author','before':b,'after':a,'sessions_before':s,'sessions_after':n,
            'started_at':'2026-10-17T00:00:00+00:00','completed_at':'2026-10-17T00:00:01+00:00'}
        wire['changes']=cont.user_transition(b['users'],a['users'],self.v['users'],'author',wire['started_at'],wire['completed_at'])
        wire['session_changes']=r.session_transition(s,n,'author',wire['started_at'],wire['completed_at'])
        r._proof(self.v)['wires']=[wire]

    def test_only_exact_full_wire_chain_excuses_native_user_session_heartbeat(self):
        proof=r.verify_preservation(self.v,self.before,self.after,[])
        self.assertTrue(proof['old_rows_unchanged']);self.assertEqual(proof['wire_heartbeats'],1)

    def test_project_financial_source_config_and_new_unknown_rows_refuse(self):
        for mutate in [lambda x:x['inventory']['Project']['original-project'].update(column='changed'),
                lambda x:x['inventory']['Sales Invoice']['original-invoice'].update(amount='changed'),
                lambda x:x['inventory']['Project'].update({'foreign-new-project':{'column':'new'}}),
                lambda x:x['config'].update(raw='changed'),lambda x:x['source'].update(sha256='changed')]:
            changed=deepcopy(self.after);mutate(changed)
            with self.assertRaises(AssertionError):r.verify_preservation(self.v,self.before,changed,[])

    def test_unverified_wire_or_unobserved_user_drift_cannot_be_exempted(self):
        for field in ('unverified','unobserved'):
            v=deepcopy(self.v);after=deepcopy(self.after)
            if field=='unverified':del r._proof(v)['wires'][0]['status']
            else:after['inventory']['User'][v['users']['author']['user']]['name']='changed'
            with self.assertRaises(AssertionError):r.verify_preservation(v,self.before,after,[])


class ReplayDriver(unittest.TestCase):
    def exercise(self,change=False):
        v,case,state=saved_fixture(self);row=v['stages'][r.v1().KEY]['cases'][case]
        row['status']='verified';row['terminal']['payloads']={'run':{row['run_id']:'exact-terminal-bytes'}}
        for key in ('config','source','indexes'):state[key]={}
        after=deepcopy(state)
        if change:after['receipts']['foreign']={'result_hash':'changed'}
        replay=deepcopy(row['saved']);replay['operation']['replayed']=True;calls=[]
        def send(method,values,**kwargs):calls.append((method,values,kwargs));return {'status':200,'envelope':{'data':replay}}
        with patch.object(r,'_value',return_value=v),patch.object(r,'observe_native',side_effect=[state,after]),\
                patch.object(r,'_run',return_value=row['terminal']),patch.object(r,'client',return_value=SimpleNamespace(call=send)),patch.object(r,'_case') as update:
            if change:
                with self.assertRaises(AssertionError):r.replay_saved('new-r15',case,'http://unused','synthetic.localhost')
                update.assert_not_called()
            else:
                result=r.replay_saved('new-r15',case,'http://unused','synthetic.localhost')
                self.assertEqual(result['status'],'replay-verified');self.assertTrue(calls[0][2]['replay'])
                self.assertEqual(calls[0][2]['key'],'save-'+case)

    def test_exact_uuid_replay_preserves_independent_native_records(self):self.exercise()
    def test_replay_that_changes_a_receipt_is_refused(self):self.exercise(True)


class ExactAdditionAttribution(unittest.TestCase):
    def test_only_real_result_ids_and_exact_fsynced_save_receipt_are_attributed(self):
        v,case,state=saved_fixture(self);old=r.v1();row=v['stages'][old.KEY]['cases'][case];core=row['saved']['application']
        initial=deepcopy(row['saved']['saved']);initial['revision']=state['records']['Cipher Proposal Revision'][core['base_revision_id']]['value']
        r._proof(v)['targets']={'commercial':initial};row['terminal']['payloads']={'run':{row['run_id']:'exact'}}
        names=['Cipher Proposal','Cipher Proposal Revision','Quotation','Quotation Item','Cipher Ricky Run','Cipher Ricky Step','Cipher Tool Invocation',
            'Cipher Proposed Change','Cipher Delegation','Cipher Run Artifact','Cipher Ricky Draft Save','Cipher Command Receipt','Cipher History Event','Project']
        state['inventory']={table:{} for table in names}
        payload={'company':v['company'],**row['reviewed'],'operation_id':core['operation_id']}
        entry={'role':'author','method':old.SAVE+'save_draft','operation_id':core['operation_id'],'payload':payload,'payload_sha256':r.sha(payload),
            'attempts':[{'status':200,'envelope':{'data':row['saved']}}]}
        additions=r.allowed_additions(v,state,[entry])
        self.assertEqual(additions['Cipher Ricky Draft Save'],{core['id']})
        self.assertEqual(additions['Cipher Proposal Revision'],{core['base_revision_id'],core['saved_revision_id']})
        self.assertEqual(additions['Cipher History Event'],{'domain-event','application-event'});self.assertFalse(additions['Project'])
        changed=deepcopy(entry);changed['payload']['expected_version']+=1;changed['payload_sha256']=r.sha(changed['payload'])
        with self.assertRaises(AssertionError):r.allowed_additions(v,state,[changed])


if __name__=='__main__':unittest.main()

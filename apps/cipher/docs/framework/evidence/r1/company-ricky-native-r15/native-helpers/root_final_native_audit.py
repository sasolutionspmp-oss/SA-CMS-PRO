"""Read-only final audit of retained 200/503 and one same-UUID expired refusal.

No transport, command, retry, UUID, fixture mutation or frozen helper patch.
Original v3/v4 failures remain failures. This report records actual outcomes.
"""
from pathlib import Path
from datetime import datetime
from copy import deepcopy
import hashlib,sys
sys.path.insert(0,'/dev/shm/cipher-r15-code/native-execution-v4')
import r15_adjudication as four
assert hashlib.sha256(Path(four.__file__).read_bytes()).hexdigest()=='aff5a91342e52ae45f02fdba4851c0185fee8591a924b21e84d29f461d27686f'

def audit(path):
 three=four.v3();two=three.v2();support=two._support()[0];value=four._value(path);proof=four._proof(value)
 assert proof['status']=='same-uuid-retry-entered' and 'retry_evidence' not in proof and 'audit_evidence' not in proof
 original=four._read_reference(path,proof['original_failure']);four._original_retained(value,original)
 for case,row in three._proof(value)['cases'].items():
  assert row['status']==('reviewed' if case==four.CASE else 'passed'),case
 journal=support.Journal(value['journal_directory']).rows;intents=four._journal_originals(journal,original,retried=True)
 loser=intents[original['outcome']['loser']];attempt=loser['attempts'][1];assert attempt['status']==409
 envelope=attempt['envelope'];expected={'code':'draft_save_expired','details':{},'message':'The completed suggestion is cancelled, unavailable or expired.','retryable':False}
 four._envelope(envelope,error=expected)
 deadline=datetime.fromisoformat(original['case']['review']['expires_at'])
 assert deadline==datetime.fromisoformat(original['case']['terminal']['children']['proposal'][0]['expires_at'])
 server_time=four._time(envelope['meta']['server_time']);assert server_time>=deadline
 intent=proof['retry_intent'];assert intent['key']==loser['key'] and intent['operation_id']==loser['operation_id'] and intent['payload_sha256']==loser['payload_sha256']
 start=intent['wire_start_index'];wires=two._proof(value)['wires'];retry=wires[start:start+2];assert len(retry)==2
 auth,post=retry
 assert auth['role']=='author' and auth['method']=='GET' and auth['path']=='/api/method/cipher_aec.api.v1.session' and auth['operation_id'] is None and auth['status']=='verified' and auth['wire']['status']==200
 assert post['role']=='author' and post['method']=='POST' and post['path']=='/api/method/'+two.v1().SAVE+'save_draft' and post['status']=='verified'
 assert post['operation_id']==post['wire']['operation_id']==loser['operation_id'] and post['payload_sha256']==loser['payload_sha256'] and post['wire']['status']==409 and post['wire']['truncated'] is False
 assert four._time(post['started_at'])<=server_time<=four._time(post['completed_at'])
 assert len([wire for wire in wires if wire['method']=='POST' and wire.get('operation_id')==loser['operation_id']])==1
 state=two.observe_native(path);assert not state['active_runs'];winner=four.verify_native_outcome(value,original,state)
 queue=three.observe_queue(path,four.CASE);assert queue['site']==value['site'] and queue['queue']=='cipher-ai04-stage-a-20261016:short' and not queue['jobs'] and not queue['workers'] and not queue['started_jobs']
 before=support.load_private(two._proof(value)['baseline']['path']);positive=support.load_private(three._proof(value)['baseline']['path'])
 epoch=four.verify_positive_epoch(before,positive,state)
 positives={}
 for case in two.POSITIVE:
  checked=two.verify_saved_state(value,case,state,current=False);positives[case]={'application_digest':checked['application']['core_digest'],'receipt_id':checked['application']['receipt_id'],'events_sha256':two.sha(checked['events'])}
 adjusted,restorations=three.restored_inventory(value,before,state)
 for case,row in three._proof(value)['cases'].items():
  if row.get('run_id'):assert two._run(path,row['run_id'])['payloads']==row['terminal']['payloads'],case
  if case!=four.CASE and row.get('proposal_id'):assert not any(item['value']['core']['proposal_id']==row['proposal_id'] for item in state['records']['Cipher Ricky Draft Save'].values()),case
 shadow=four.adjudicated_ledger(value,original)
 for case,row in three._proof(value)['cases'].items():
  if case!=four.CASE:shadow['stages'][two.v1().KEY]['cases'][case]=deepcopy(row)
  for domain,target in row.get('targets',{}).items():two._proof(shadow)['targets'][case+'-'+domain]=deepcopy(target)
 preservation=two.verify_preservation(shadow,before,adjusted,journal)
 return {'schema':'cipher.r15.final-native-root-audit.v1','status':'passed_with_retained_concurrency_expectation_failures',
  'positive_cases':positives,'boundary_cases':{case:row['status'] for case,row in three._proof(value)['cases'].items()},
  'concurrency':{'original_outcomes':[200,503],'original_error':'concurrent_change','same_original_loser_uuid':loser['operation_id'],
   'explicit_retry_status':409,'explicit_retry_error':'draft_save_expired','original_deadline':deadline.isoformat(),'retry_server_time':server_time.isoformat(),
   'winner_application_digest':winner['application']['core_digest'],'winner_receipt_id':winner['receipt']['name'],'loser_effect_absent':True,
   'original_v3_batch_and_case_unchanged':True,'original_v4_proof_unchanged':True,'additional_retry_or_new_uuid':False},
  'original_failed_phase_results_superseded':False,'supported_restorations':restorations,'final_queue':queue,
  'positive_epoch':epoch,'preservation':preservation,'business_mutations':0,'main_changed':False}

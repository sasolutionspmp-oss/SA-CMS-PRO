"""Real command-boundary replay ordering with explicit native/session doubles."""
from contextlib import contextmanager,ExitStack
import importlib.util,json,sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import unittest
from cipher_aec.api.contracts import digest
from cipher_aec.api.errors import DomainError
from cipher_aec.tests.test_document_control import fixture
from cipher_aec.tests.test_engineering import uid

class OriginalReceiptContextTests(unittest.TestCase):
    def test_real_command_replay_selects_original_context_before_prospective_source_locks(self):
        with fixture() as (s,r,repo,rights,service,gov),ExitStack() as stack:
            context=sys.modules['cipher_aec.governance.context'];locking=__import__('cipher_aec.document_control.locking',fromlist=['DocumentContext']);events=[]
            class ProbeContext:
                company='C';project='P'
                def __init__(self,label):self.label=label
                def prelock(self,actor):
                    events.append(('prelock',self.label))
                    if self.label=='future':raise DomainError('not_found','An unrelated newer source is unavailable.',404)
                @contextmanager
                def hold(self,actor,result=None):events.append(('hold',self.label));yield
            result={'library_revision':{'id':uid(),'company':'C','project':'P','scope_type':'Project'}};payload={'unchanged':'original'};operation=uid();command='document.control.library.create.v1';request=digest({'command':command,'company':'C','project':'P','payload':payload});receipt=SimpleNamespace(request_hash=request,result_json=json.dumps(result),result_hash=digest(result),scope_type='Project',company='C',project='P')
            def sql(query,*args,**kwargs):
                if 'Command Receipt' in query:events.append(('receipt','locked' if 'FOR UPDATE' in query else 'preview'));return [receipt]
                return []
            for name,value in {'assert_synthetic_site':lambda:None,'require_effects_enabled':lambda:None,'session_authority_reference':lambda *a:None,'require_session_authority':lambda *a,**k:None}.items():stack.enter_context(patch.object(context,name,value,create=True))
            stack.enter_context(patch.object(locking,'DocumentContext',ProbeContext));stack.enter_context(patch.object(locking,'for_result',return_value=ProbeContext('original')));stack.enter_context(patch.object(sys.modules['frappe'].db,'sql',sql))
            path=Path(__file__).parents[1]/'governance/commands.py';spec=importlib.util.spec_from_file_location('cipher_aec.governance.doc03_command_boundary_probe',path);commands=importlib.util.module_from_spec(spec);spec.loader.exec_module(commands)
            stack.enter_context(patch.object(commands,'authorize_receipt',lambda *a,**k:events.append(('authorize','original'))))
            replay=commands.run_command(company='C',project='P',operation_id=operation,command=command,payload=payload,ability=r.WRITE,effect=lambda *a:self.fail('Replay must not execute a new effect'),document_context=ProbeContext('future'))
            self.assertTrue(replay['operation']['replayed']);self.assertNotIn(('prelock','future'),events);self.assertLess(events.index(('receipt','preview')),events.index(('prelock','original')));self.assertIn(('receipt','locked'),events)

    def test_conflicting_or_corrupt_receipt_never_selects_a_private_source_plan(self):
        with fixture() as (s,r,repo,rights,service,gov):
            from cipher_aec.document_control.command_context import original_or_new
            locking=__import__('cipher_aec.document_control.locking',fromlist=['for_result'])
            payload={'original':True};command='document.control.library.create.v1';result={'library_revision':{'id':uid()}}
            valid={'request_hash':digest({'command':command,'company':'C','project':'P','payload':payload}),'result_json':json.dumps(result),'result_hash':digest(result),'scope_type':'Project','company':'C','project':'P'}
            for changed,code in [({'request_hash':'0'*64},'operation_conflict'),({'scope_type':'Company','project':None},'operation_conflict'),({'result_hash':'0'*64},'receipt_integrity'),({'result_json':'invalid'},'receipt_integrity')]:
                row=SimpleNamespace(**{**valid,**changed})
                with self.subTest(changed=changed),patch.object(sys.modules['frappe'].db,'sql',return_value=[row]),patch.object(locking,'for_result') as discover:
                    with self.assertRaises(DomainError) as error:original_or_new(object(),s.actor,'C','P','Project',uid(),command,payload)
                    self.assertEqual(error.exception.code,code);discover.assert_not_called()

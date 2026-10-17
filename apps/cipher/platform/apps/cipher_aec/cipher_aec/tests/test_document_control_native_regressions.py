"""Narrow local-native findings reproduced against actual boundary functions.

Host doubles below are not a native persistence or approval qualification.
"""
import ast,json
from pathlib import Path
from types import SimpleNamespace
import unittest
from uuid import uuid4
from cipher_aec.api.contracts import digest
from cipher_aec.api.errors import DomainError
from cipher_aec.document_control.contracts import identifier,KINDS

ROOT=Path(__file__).parents[1]
def functions(path,names,environment):
    tree=ast.parse(path.read_text());selected=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in names]
    assert len(selected)==len(names)
    exec(compile(ast.Module(body=selected,type_ignores=[]),str(path),'exec'),environment)
    return environment

class NativeOptionalIntTests(unittest.TestCase):
    def test_omitted_revision_number_accepts_native_integer_zero_only(self):
        value={'id':str(uuid4()),'company':'C','project':'P','scope_type':'Project','author_person':'author','status':'working'}
        path=ROOT/'document_control/repository.py';tree=ast.parse(path.read_text());indexes=next(ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='INDEXES' for t in n.targets))
        fields={**value,'revision_number':0};doc=SimpleNamespace(name=value['id'],data_json=json.dumps(value),record_digest=digest(value),get=lambda key:fields.get(key))
        env=functions(path,['raw'],{'json':json,'digest':digest,'identifier':identifier,'KINDS':KINDS,'INDEXES':indexes,'DomainError':DomainError,'frappe':SimpleNamespace(get_doc=lambda *a,**k:doc)})
        self.assertEqual(env['raw']('issue_set',value['id']),value)
        for bad in [1,-1,'0',False,0.0,{},[]]:
            fields['revision_number']=bad
            with self.subTest(native_value=bad),self.assertRaises(DomainError):env['raw']('issue_set',value['id'])
        # A declared revision is exact; null is not an omitted field.
        value['revision_number']=2;doc.data_json=json.dumps(value);doc.record_digest=digest(value);fields['revision_number']=2;self.assertEqual(env['raw']('issue_set',value['id']),value)
        for declared in [2,None]:
            value['revision_number']=declared;doc.data_json=json.dumps(value);doc.record_digest=digest(value);fields['revision_number']=0
            with self.subTest(declared=declared),self.assertRaises(DomainError):env['raw']('issue_set',value['id'])

class DocumentaryPacketParticipantTests(unittest.TestCase):
    def boundary(self):
        state=SimpleNamespace(action='document.transmit.v1',recipients=('recipient-person',),captured=[])
        packet=SimpleNamespace(action=state.action,subject_id='subject',requester_person='preparer')
        domain={'DomainError':DomainError,'participant_people':lambda *a,**k:state.recipients}
        functions(ROOT/'governance/domain_approvals.py',['require_participants'],domain)
        registry=SimpleNamespace(participant_people=domain['participant_people'],require_participants=domain['require_participants'],authorize=lambda *a,**k:None)
        def command(**kw):
            state.captured.append(kw['participant_people']);actor=SimpleNamespace(person_id='reviewer' if kw['command']=='approval.decide' else 'preparer');return kw['effect'](actor,SimpleNamespace())
        env={'DomainError':DomainError,'domain_approvals':registry,'_scope':lambda *a:None,'_load':lambda *a,**k:packet,'text':lambda value,*a,**k:value,'_command':command,'_check_hash':lambda *a:None,'_human_review':lambda *a:None,'_state':lambda *a,**k:('Pending',None),'_decision':lambda *a:None,'_event':lambda *a:None,'present':lambda *a:{'id':'packet'},'ACTION':'project.status.change.v1','frappe':SimpleNamespace()}
        functions(ROOT/'governance/approvals.py',['_award_packet_people','decide_packet','withdraw_packet'],env)
        return state,packet,env,domain
    def test_documentary_decision_and_withdrawal_capture_original_recipients(self):
        state,packet,env,domain=self.boundary()
        self.assertEqual(env['_award_packet_people']('C','P','packet','Project'),state.recipients)
        env['decide_packet']('C','P','packet','hash','Grant',str(uuid4()),'Independent review')
        env['withdraw_packet']('C','P','packet','hash',str(uuid4()),'Original preparer withdrawal')
        self.assertEqual(state.captured,[state.recipients,state.recipients])
    def test_changed_or_nonrecipient_plan_is_refused_and_other_actions_have_no_recipients(self):
        state,packet,env,domain=self.boundary();known=env['_award_packet_people']('C','P','packet','Project')
        for wrong in [('nonrecipient-person',),()]:
            with self.subTest(known=wrong),self.assertRaises(DomainError) as error:domain['require_participants']('document.transmit.v1','C','subject',wrong)
            self.assertEqual(error.exception.code,'document_participants_changed')
        state.recipients=('rebound-recipient',)
        with self.assertRaises(DomainError):domain['require_participants']('document.transmit.v1','C','subject',known)
        packet.action='document.issue.v1';self.assertEqual(env['_award_packet_people']('C','P','packet','Project'),())

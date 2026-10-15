"""Native synthetic RFI test world; no production authority or session mixins."""
from apps.cipher.service import Cipher
from apps.cipher.tests.test_rfi_controls import admit_actual_rfi_sources

OWNER='practice.rfi.setup'
STAFF='practice.rfi.staff'
PM='practice.rfi.requester'
REVIEWER='practice.rfi.reviewer'
OTHER='practice.rfi.hidden.pm'


class RFIWorld:
    def __init__(self):
        admit_actual_rfi_sources();self.c=Cipher(':memory:');c=self.c;self.people=c.plugin('people')
        self.people.bootstrap_owner(OWNER,'RFI setup owner (synthetic)')
        for login in (STAFF,PM,REVIEWER,OTHER):self.people.register_person(login,login+' (synthetic)',actor=OWNER)
        self.pid=c.create_project(name='Synthetic drainage project',entity='Synthetic RFI entity',budget='0',actor=OWNER)['id']
        self.hidden=c.create_project(name='Hidden synthetic project',entity='Synthetic RFI entity',budget='0',actor=OWNER)['id']
        c.open_period('RFI1','RFI issue period','2026-10-01','2026-10-31',actor=OWNER)
        for login in (STAFF,PM,REVIEWER):self.people.add_membership(login,self.pid,actor=OWNER)
        self.people.add_membership(OTHER,self.hidden,actor=OWNER)
        def govern(operation,subject):
            ap=c.request_approval(operation,subject,actor_role='owner',requested_by=OWNER)
            c.approve(ap['id'],approver=OWNER,approver_role='owner');c.execute(ap['id'],actor=OWNER)
        for login,project in ((PM,self.pid),(REVIEWER,self.pid),(OTHER,self.hidden)):
            grant=self.people.request_grant(login,'pm',project_id=project,reason='Synthetic RFI assignment',actor=OWNER)
            govern('people.grant_role',grant['id'])
        policy=self.people.prepare_policy(enforce=True,segregate=True,solo_owner_self_approval=False,reason='Synthetic independent RFI decisions',actor=OWNER)
        govern('people.set_policy',policy['id'])
        drawing_doc=c.evidence.register_document(project_id=self.pid,kind='drawing',title='C-101 Drainage detail',actor=PM)
        self.drawing_doc=drawing_doc['id']
        drawing_ev=c.evidence.add_revision(document_id=drawing_doc['id'],content='Synthetic issued drawing A',actor=PM)
        drawings=c.plugin('drawing');header=drawings.register_drawing(self.pid,'C-101','Drainage detail','Civil',actor=PM)
        self.drawing_id=header['id'];self.drawing=drawings.add_revision(header['id'],'A',drawing_ev['id'],actor=PM)
        ap=c.request_approval('drawing.issue',self.drawing['id'],actor_role='pm',requested_by=PM)
        c.approve(ap['id'],approver=REVIEWER,approver_role='pm');c.execute(ap['id'],actor=PM,period_id='RFI1')
        support=c.evidence.register_document(project_id=self.pid,kind='specification',title='Authored drainage specification',actor=STAFF)
        self.support_doc=support['id'];self.support=c.evidence.add_revision(document_id=support['id'],content='Synthetic authored drainage note',actor=STAFF)
        self.module=c.plugin('rfi_controls')
        self.body={'subject':'Drain alignment clash','question':'Which alignment should be used at grid C4?',
                   'drawingRevisionIds':[self.drawing['id']],'documentRevisionIds':[self.support['id']]}
        self.rfi=self.module.create(self.pid,self.body,actor=STAFF)

    def draft(self,actor=STAFF,text='Use the east alignment per the reviewed drainage detail.'):
        return self.module.draft_response(self.rfi['id'],{'responseText':text,'costImpact':'1250.00','scheduleImpactDays':3},actor=actor)

    def request_response(self):
        return self.c.request_approval('field.respond_rfi',self.rfi['id'],actor_role='pm',requested_by=PM)

    def answer(self):
        self.draft();ap=self.request_response();self.c.approve(ap['id'],approver=REVIEWER,approver_role='pm')
        result=self.c.execute(ap['id'],actor=PM);return ap,result

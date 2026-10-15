"""Fresh synthetic RFI source choices and actual independently staffed project duties."""
from types import MappingProxyType

from .service import Cipher

BOOTSTRAP_LOGIN='practice.rfi.bootstrap'
STAFF_LOGIN='practice.rfi.staff'
PM_LOGIN='practice.rfi.pm'
REVIEWER_LOGIN='practice.rfi.reviewer'
HIDDEN_STAFF_LOGIN='practice.rfi.hidden.staff'
HIDDEN_PM_LOGIN='practice.rfi.hidden.pm'
HIDDEN_REVIEWER_LOGIN='practice.rfi.hidden.reviewer'
INACTIVE_LOGIN='practice.rfi.inactive'
EXTERNAL_LOGIN='practice.rfi.external'
SERVICE_LOGIN='practice.rfi.service'


def make_rfi_practice_fixture():
    """Always own a new memory workspace; source citations are not answered RFIs."""
    c=Cipher(':memory:')
    try:
        people=c.plugin('people');c.plugin('rfi_controls')  # Reuse the actual required instance.
        people.bootstrap_owner(BOOTSTRAP_LOGIN,'RFI setup owner (synthetic)')
        for login,label in ((STAFF_LOGIN,'Project staff author'),(PM_LOGIN,'Requesting project PM'),(REVIEWER_LOGIN,'Independent reviewing PM'),
                (HIDDEN_STAFF_LOGIN,'Hidden project staff'),(HIDDEN_PM_LOGIN,'Hidden project PM'),(HIDDEN_REVIEWER_LOGIN,'Hidden reviewing PM'),(INACTIVE_LOGIN,'Departed project PM')):
            people.register_person(login,label+' (synthetic)',actor=BOOTSTRAP_LOGIN)
        people.register_person(EXTERNAL_LOGIN,'External RFI control (synthetic)',actor=BOOTSTRAP_LOGIN,external=True)
        people.register_person(SERVICE_LOGIN,'Service RFI control (synthetic)',actor=BOOTSTRAP_LOGIN,kind='service')
        projects=[c.create_project(name=label,entity='Synthetic RFI entity',budget='0.00',actor=BOOTSTRAP_LOGIN)
                  for label in ('Synthetic drainage improvement','Hidden synthetic drainage project')]
        c.open_period('2026-10','October 2026','2026-10-01','2026-10-31',actor=BOOTSTRAP_LOGIN)
        assignments=((STAFF_LOGIN,None,0),(PM_LOGIN,'pm',0),(REVIEWER_LOGIN,'pm',0),(INACTIVE_LOGIN,'pm',0),
                     (EXTERNAL_LOGIN,None,0),(SERVICE_LOGIN,None,0),(HIDDEN_STAFF_LOGIN,None,1),(HIDDEN_PM_LOGIN,'pm',1),(HIDDEN_REVIEWER_LOGIN,'pm',1))
        def govern(operation,subject):
            approval=c.request_approval(operation,subject,actor_role='owner',requested_by=BOOTSTRAP_LOGIN)
            c.approve(approval['id'],approver=BOOTSTRAP_LOGIN,approver_role='owner');c.execute(approval['id'],actor=BOOTSTRAP_LOGIN)
        for login,role,index in assignments:
            project_id=projects[index]['id'];people.add_membership(login,project_id,actor=BOOTSTRAP_LOGIN)
            if role:
                request=people.request_grant(login,role,project_id=project_id,reason='Synthetic owned RFI project duty',actor=BOOTSTRAP_LOGIN)
                govern('people.grant_role',request['id'])
        policy=people.prepare_policy(enforce=True,segregate=True,solo_owner_self_approval=False,reason='Synthetic independent project RFI review',actor=BOOTSTRAP_LOGIN)
        govern('people.set_policy',policy['id'])
        people.deactivate_person(INACTIVE_LOGIN,reason='Synthetic departed person control',actor=BOOTSTRAP_LOGIN)
        sources=[]
        for index,project in enumerate(projects):
            pm=PM_LOGIN if not index else HIDDEN_PM_LOGIN;reviewer=REVIEWER_LOGIN if not index else HIDDEN_REVIEWER_LOGIN
            document=c.evidence.register_document(project_id=project['id'],kind='drawing',title='C-101 Drainage detail (synthetic)',actor=pm)
            evidence=c.evidence.add_revision(document_id=document['id'],content='Synthetic authored drawing C-101 revision A; no CAD geometry or engineering stamp is asserted.',actor=pm)
            drawings=c.plugin('drawing');drawing=drawings.register_drawing(project['id'],'C-101','Drainage alignment detail','Civil',actor=pm)
            revision=drawings.add_revision(drawing['id'],'A',evidence['id'],note='Synthetic issued source',actor=pm)
            approval=c.request_approval('drawing.issue',revision['id'],actor_role='pm',requested_by=pm)
            c.approve(approval['id'],approver=reviewer,approver_role='pm');c.execute(approval['id'],actor=pm,period_id='2026-10')
            working_evidence=c.evidence.add_revision(document_id=document['id'],content='Synthetic working drawing B; not issued and unavailable as a new RFI drawing citation.',actor=pm)
            working=drawings.add_revision(drawing['id'],'B',working_evidence['id'],note='Unissued synthetic working revision',actor=pm)
            support=c.evidence.register_document(project_id=project['id'],kind='specification',title='Authored drainage specification (synthetic)',actor=pm)
            support_revision=c.evidence.add_revision(document_id=support['id'],content='Synthetic authored supporting note: review drain alignment at grid C4. No licensed standard or contract adoption is asserted.',actor=pm)
            sources.append({'drawing_id':drawing['id'],'drawing_revision_id':revision['id'],'drawing_document_id':document['id'],
                            'working_drawing_revision_id':working['id'],'document_id':support['id'],'document_revision_id':support_revision['id']})
        personas=(('staff','Project staff author',STAFF_LOGIN),('pm','Requesting project PM',PM_LOGIN),('reviewer','Independent reviewing PM',REVIEWER_LOGIN))
        c.rfi_practice_persona_people=MappingProxyType({key:MappingProxyType({'person_id':people.person_for(login)['id'],'login':login}) for key,label,login in personas})
        c.rfi_practice_personas=tuple({'id':key,'name':label+' (synthetic)','login':login} for key,label,login in personas)
        from .domain.rfi_controls import RECIPIENTS
        c.rfi_practice_records=MappingProxyType({'project_id':projects[0]['id'],'visible_project_ids':(projects[0]['id'],),
            'hidden_project_id':projects[1]['id'],**sources[0],**{'hidden_'+key:value for key,value in sources[1].items()},
            'period_id':'2026-10','allowed_recipients':RECIPIENTS})
        return c
    except BaseException:
        c.db.close();raise

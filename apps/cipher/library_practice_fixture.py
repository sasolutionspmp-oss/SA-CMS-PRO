"""Owned memory practice authors and independent project PM reference review."""
from __future__ import annotations
from types import MappingProxyType
from .service import Cipher

BOOTSTRAP_LOGIN = 'practice.library.bootstrap'
PM_LOGIN = 'practice.library.pm'
REVIEWER_LOGIN = 'practice.library.reviewer'
POSTER_LOGIN = 'practice.library.accountant'
HIDDEN_PM_LOGIN = 'practice.library.hidden.pm'
INACTIVE_LOGIN = 'practice.library.inactive'


def make_library_practice_fixture() -> Cipher:
    c = Cipher(':memory:')
    try:
        people = c.plugin('people')
        people.bootstrap_owner(BOOTSTRAP_LOGIN, 'Library setup owner (synthetic)')
        for login, label in ((PM_LOGIN,'Authoring project PM'),(REVIEWER_LOGIN,'Independent reference-review PM'),
                             (POSTER_LOGIN,'Accounting-only control person'),(HIDDEN_PM_LOGIN,'Hidden project PM'),
                             (INACTIVE_LOGIN,'Departed project PM')):
            people.register_person(login,label+' (synthetic)',actor=BOOTSTRAP_LOGIN)
        visible = c.create_project(name='Synthetic authored specifications project',entity='Synthetic library entity',budget='1000',actor=BOOTSTRAP_LOGIN)
        hidden = c.create_project(name='Hidden synthetic authored clauses project',entity='Synthetic library entity',budget='1000',actor=BOOTSTRAP_LOGIN)
        def govern(operation, subject):
            request = c.request_approval(operation,subject,actor_role='owner',requested_by=BOOTSTRAP_LOGIN)
            c.approve(request['id'],approver=BOOTSTRAP_LOGIN,approver_role='owner')
            return c.execute(request['id'],actor=BOOTSTRAP_LOGIN)
        for login, role, project in ((PM_LOGIN,'pm',visible),(REVIEWER_LOGIN,'pm',visible),(POSTER_LOGIN,'accountant',visible),
                                     (INACTIVE_LOGIN,'pm',visible),(HIDDEN_PM_LOGIN,'pm',hidden)):
            people.add_membership(login,project['id'],actor=BOOTSTRAP_LOGIN)
            draft=people.request_grant(login,role,project_id=project['id'],reason='Synthetic authored library assignment',actor=BOOTSTRAP_LOGIN)
            govern('people.grant_role',draft['id'])
        policy=people.prepare_policy(enforce=True,segregate=True,solo_owner_self_approval=False,
            reason='Synthetic independent library PM review',actor=BOOTSTRAP_LOGIN)
        govern('people.set_policy',policy['id'])
        people.deactivate_person(INACTIVE_LOGIN,reason='Synthetic staff departure',actor=BOOTSTRAP_LOGIN)
        c.library_practice_records=MappingProxyType({'project_id':visible['id'],'visible_project_ids':(visible['id'],),
            'hidden_project_id':hidden['id']})
        persona_people = {key: MappingProxyType({'person_id':people.person_for(login)['id'],'login':login})
            for key, login in (('author',PM_LOGIN),('reviewer',REVIEWER_LOGIN))}
        c.library_practice_persona_people = MappingProxyType(persona_people)
        c.library_practice_personas = tuple(MappingProxyType({'personaId':key,
            'displayName':people.person_for(value['login'])['display_name'],'synthetic':True})
            for key,value in persona_people.items())
        return c
    except BaseException:
        c.db.close()
        raise

"""Literal ENG-02 independent human checking; no issue/seal authority."""
from functools import partial
import json
import frappe
from cipher_aec.api.contracts import digest
from cipher_aec.api.errors import DomainError
from cipher_aec.governance.context import require_project
from cipher_aec.governance.approvals import require_approval_effect
from . import contracts as rules,repository as repo,service
from cipher_aec.estimating import units

def _eligibility(kind,value,actor,*,lock=False):
    header=service.raw('package',value['parent_id'],value['company'],value['project'],lock=lock)
    current=header['basis_head']==value['id'] if kind=='basis' else value['id'] in header[kind+'_heads'] and value['basis_revision']==header['basis_head']
    if not current or value['package_revision']!=header['current_revision']:raise DomainError('stale_package','This exact package revision/basis/family is no longer current for new checking.',412)
    if repo.checked(kind,value['id'],lock=lock):raise DomainError('package_already_checked','This exact immutable revision already has its independent check fact.',409)
    records={}
    def gather(k,v):
        if k in ('basis','calculation'):
            for row in v['unit_manifest']['records']:
                if row['kind']=='uom':
                    if row['id'] in records and records[row['id']]!=row:raise DomainError('package_unit_conflict','This exact source graph pins conflicting unit revisions.',409)
                    records[row['id']]=row
        if k in ('calculation','deliverable'):gather('basis',service.read('basis',v['basis_revision'],v['company'],v['project'],actor,lock=lock))
        if k=='deliverable':
            for reference in v['calculations']:gather('calculation',service.read('calculation',reference['id'],v['company'],v['project'],actor,lock=lock))
    gather(kind,value)
    # Complete sorted native UOM union precedes the first UOM lock.
    for identifier in sorted(records):
        if units.qualified(identifier,actor=actor,lock=lock)!=records[identifier]:raise DomainError('stale_package_unit','The qualified unit changed. Review an explicit successor before checking.',412)


def authorize_subject(*,kind,actor,company,project,subject_id,phase,lock=False,manifest=None):
    value=service.read(kind,subject_id,company,project,actor,lock=lock)
    if manifest is not None:
        effect=manifest.get('effect',{})
        if effect.get('schema')!='cipher.engineering.package-check.v1' or effect.get('action')!=rules.ACTIONS[kind] or effect.get('subject_kind')!=kind or effect.get('subject_id')!=subject_id or effect.get('subject_digest')!=digest(value):raise DomainError('package_approval_integrity','The original checking manifest has a different exact package revision.',409)
    if phase in ('request','execute'):
        require_project(company,project,ability=rules.WRITE,actor=actor,lock=lock)
        if actor.person_id!=value['author_person']:raise DomainError('package_preparer_required','The original preparer must request and record their independently checked revision.',403)
    if phase=='review':
        require_project(company,project,ability=rules.CHECK,actor=actor,lock=lock)
        if actor.person_id!=value['checker']['person'] or actor.person_id==value['author_person']:raise DomainError('independent_package_checker','The designated independent canonical checker must review this exact work.',403)
    if phase in ('request','manifest','review','execute'):
        project_doc=require_project(company,project,ability=rules.READ,actor=actor,lock=lock)
        if project_doc.status in ('Completed','Cancelled'):raise DomainError('project_closed','This Project is closed for new checking work.',409)
        _eligibility(kind,value,actor,lock=lock)
    return value

def approval_manifest(*,kind,actor,company,project,subject_id,expected_version,lock=False):
    value=authorize_subject(kind=kind,actor=actor,company=company,project=project,subject_id=subject_id,phase='manifest',lock=lock)
    if digest(value)!=expected_version:raise DomainError('stale_package','Review this exact immutable package revision.',412)
    return {'subject':{'doctype':rules.KINDS[kind],'name':subject_id,'label':value['definition']['title']+' · Revision '+str(value['revision_number'])},
      'sources':[{'source_citations':value['source_citations'],'drawing_references':value['drawing_references'],'artifacts':value['artifacts'],'unit_manifest':value.get('unit_manifest')}],
      'effect':{'schema':'cipher.engineering.package-check.v1','action':rules.ACTIONS[kind],'subject_kind':kind,'subject_id':subject_id,'subject_digest':digest(value),'parent_id':value['parent_id'],'package_revision':value['package_revision'],'package_digest':value['package_digest'],'preparer_person':value['author_person'],'checker':value['checker'],'outcome':'checked','issue_authorized':False,'sealed':False},
      'summary':{'definition':value['definition'],'inputs':value.get('inputs',value.get('quantities',[])),'outputs':value.get('outputs',[]),'calculations':value.get('calculations',[]),'no_effects':dict(rules.NO_EFFECTS),'solver_executed':False,'issue_authorized':False,'sealed':False}}

def apply_check(*,kind,actor,company,project,manifest,packet_id,decision_id,operation_id):
    effect=manifest['effect'];require_approval_effect(action=rules.ACTIONS[kind],subject_id=effect['subject_id'],packet_id=packet_id)
    original=authorize_subject(kind=kind,actor=actor,company=company,project=project,subject_id=effect['subject_id'],phase='execute',lock=True,manifest=manifest)
    if approval_manifest(kind=kind,actor=actor,company=company,project=project,subject_id=original['id'],expected_version=digest(original),lock=True)!=manifest:raise DomainError('stale_package','The exact independently reviewed design work changed.',412)
    decision=frappe.get_doc('Cipher Approval Decision',decision_id,for_update=True);packet=frappe.get_doc('Cipher Approval Packet',packet_id,for_update=True)
    if decision.packet!=packet_id or decision.decision!='Grant' or decision.actor_person!=original['checker']['person'] or decision.actor_person==original['author_person'] or packet.action!=rules.ACTIONS[kind] or packet.subject_id!=original['id'] or decision.manifest_hash!=packet.manifest_hash:raise DomainError('independent_package_checker','The exact revision requires its designated independent human grant.',403)
    value=service.base(company,project,actor,status='checked',parent_id=original['parent_id'],subject_kind=kind,subject_id=original['id'],subject_digest=digest(original),package_revision=original['package_revision'],package_digest=original['package_digest'],checker=original['checker'],preparer_person=original['author_person'],packet_id=packet_id,decision_id=decision_id,comments=decision.reason or '',outcome='checked',issue_authorized=False,sealed=False)
    repo.write('check',value);service.event(actor,value,operation_id,'checked','check');return {'check':value}

CALLBACKS={action:(partial(approval_manifest,kind=kind),partial(authorize_subject,kind=kind),partial(apply_check,kind=kind)) for kind,action in rules.ACTIONS.items()}

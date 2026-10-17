"""Native offline projections are private and admit exact service write plans."""
import json
from frappe.model.document import Document
from cipher_aec.api.contracts import digest
from cipher_aec.api.errors import DomainError
from cipher_aec.governance.context import current_actor,require_project
from cipher_aec.field import contracts as f
from . import contracts as c,repository as repo
from .spec import business_request

BASE={'id','company','project','scope_type','author_person','author_user','created_at','status','owner_person','device_id'}
EXTRA={
 'device':{'registered_user','label','revoked_at','revocation_reason'},
 'capture':{'capture_id','actor_person','actor_user','envelope_digest','envelope','business_command','business_request_hash','participant_people','revision_number','last_event','commit_receipt','replaces_capture_id','replacement_capture_id'},
 'event':{'capture_id','event_type','prior_digest','next_digest','reason','related_capture_id'},
}

def integrity():raise DomainError('field_offline_integrity','The exact offline record cannot be verified.',409)

def validate_record(kind,value):
    if kind not in EXTRA:integrity()
    f.closed(value,BASE|EXTRA[kind]);c.scope(value['company'],value['project'])
    if value['scope_type']!='Project':integrity()
    for key in ('author_person','author_user','owner_person'):f.text(value[key],key,140)
    c.timestamp(value['created_at']);c.identifier(value['device_id'])
    if value['author_person']!=value['owner_person']:integrity()
    if kind=='device':
        c.identifier(value['id']);f.text(value['registered_user'],'registered_user',140);f.text(value['label'],'label',140)
        f.text(value['revocation_reason'],'reason',2000,blank=True)
        if value['id']!=value['device_id'] or value['author_user']!=value['registered_user'] or value['status'] not in ('active','revoked'):integrity()
        if value['status']=='active':
            if value['revoked_at'] is not None or value['revocation_reason']:integrity()
        else:
            c.timestamp(value['revoked_at'])
            if not value['revocation_reason'].strip():integrity()
    elif kind=='capture':
        c.identifier(value['capture_id']);c.checksum(value['id'])
        if value['id']!=digest({'person':value['owner_person'],'capture_id':value['capture_id']}):integrity()
        if value['actor_person']!=value['owner_person']:integrity()
        f.text(value['actor_user'],'actor_user',140);c.checksum(value['envelope_digest']);c.checksum(value['business_request_hash'])
        if type(value['participant_people']) is not dict or len(value['participant_people'])>1:integrity()
        for user,person in value['participant_people'].items():f.text(user,'participant_user',140);f.text(person,'participant_person',140)
        if value['status'] not in ('staged','committed','discarded','superseded'):integrity()
        if type(value['revision_number']) is not int or value['revision_number']<1:integrity()
        for key in ('last_event','replaces_capture_id','replacement_capture_id'):
            if value[key] is not None:c.identifier(value[key])
        if value['status']=='superseded' and value['replacement_capture_id'] is None:integrity()
        if value['status']!='superseded' and value['replacement_capture_id'] is not None:integrity()
        if value['envelope'] is not None:
            e=c.envelope(value['envelope'])
            if digest(e)!=value['envelope_digest'] or any(e[k]!=value[k] for k in ('company','project','device_id','capture_id','actor_person','actor_user')):integrity()
            command,_,request_hash=business_request(e)
            if command!=value['business_command'] or request_hash!=value['business_request_hash']:integrity()
            users={e['command']['definition']['superintendent_user']} if e['command']['family']=='daily' else set()
            if set(value['participant_people'])!=users:integrity()
        elif value['status']=='staged':integrity()
        if value['commit_receipt'] is not None:
            r=f.closed(value['commit_receipt'],{'operation_id','request_hash','result_hash','header_id','revision_id'})
            for key in ('operation_id','header_id','revision_id'):c.identifier(r[key])
            c.checksum(r['request_hash']);c.checksum(r['result_hash'])
            if r['operation_id']!=value['capture_id'] or r['request_hash']!=value['business_request_hash'] or value['status']!='committed':integrity()
        elif value['status']=='committed':integrity()
    else:
        c.identifier(value['id']);c.identifier(value['capture_id']);c.checksum(value['prior_digest']);c.checksum(value['next_digest'])
        if value['status']!='recorded' or value['event_type'] not in ('committed','discarded','redacted','superseded'):integrity()
        f.text(value['reason'],'reason',2000)
        if value['related_capture_id'] is not None:c.identifier(value['related_capture_id'])
    return value

class OfflineRecord(Document):
    def validate(self):
        kind=next(k for k,v in repo.KINDS.items() if v==self.doctype)
        try:value=json.loads(self.data_json)
        except (TypeError,ValueError):integrity()
        validate_record(kind,value);old=repo.require_write(self,kind,value)
        actor=current_actor();plan=repo._operation.get()
        if not plan or plan['person']!=actor.person_id or (plan['company'],plan['project'])!=(self.company,self.project) or actor.person_id!=value['owner_person']:
            raise DomainError('field_offline_command_required','Use an admitted offline capture command.',403)
        require_project(self.company,self.project,ability='field.read',actor=actor,lock=True)
        project=require_project(self.company,self.project,ability='field.write',actor=actor,lock=True)
        if project.status in ('Completed','Cancelled'):raise DomainError('project_closed','This Project is closed for new offline writes.',409)
        if self.name!=value['id'] or self.record_digest!=digest(value):integrity()
        for key in ('company','project','scope_type','author_person','status',*repo.INDEXES):
            a,b=self.get(key),value.get(key)
            if key=='revision_number' and key not in value and type(a) is int and a==0:a=None
            if a!=b and not(a in (None,'') and b is None):integrity()
        if self.is_new():
            if value['author_user']!=actor.user or value['author_person']!=actor.person_id:integrity()
            if kind=='device' and (plan['action']!='register' or value['status']!='active'):integrity()
            if kind=='capture' and (plan['action'] not in ('stage','resolve') or value['status']!='staged' or value['revision_number']!=1 or value['last_event'] is not None or value['commit_receipt'] is not None):integrity()
            if kind=='event':
                parent=repo.raw('capture',digest({'person':actor.person_id,'capture_id':value['capture_id']}),lock=True)
                if value['prior_digest']!=digest(parent) or value['device_id']!=parent['device_id']:integrity()
        elif kind=='event':integrity()
        elif kind=='device':
            if plan['action']!='revoke' or old['status']!='active' or value['status']!='revoked' or any(value[k]!=old[k] for k in value if k not in ('status','revoked_at','revocation_reason')):integrity()
        else:
            mutable={'status','envelope','revision_number','last_event','commit_receipt','replacement_capture_id'}
            if any(value[k]!=old[k] for k in value if k not in mutable) or value['revision_number']!=old['revision_number']+1:integrity()
            if value['envelope']!=old['envelope'] and value['envelope'] is not None:integrity()
            event=repo.raw('event',value['last_event'],lock=True)
            if event['prior_digest']!=digest(old) or event['next_digest']!=digest(value) or event['capture_id']!=value['capture_id']:integrity()
            retained=old['status'] in ('committed','superseded')
            allowed={'apply':('staged','committed','committed'),'discard':(old['status'],old['status'] if retained else 'discarded','redacted' if retained else 'discarded'),'resolve':('staged','superseded','superseded')}
            if plan['action'] not in allowed or (old['status'],value['status'],event['event_type'])!=allowed[plan['action']]:integrity()
    def on_trash(self):raise DomainError('field_offline_command_required','Use explicit payload discard; retain the audit record.',403)
    def before_rename(self,*args,**kwargs):raise DomainError('field_offline_command_required','Offline identities cannot be renamed.',403)

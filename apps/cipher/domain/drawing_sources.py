"""Pure native issued-drawing and exact-reference proofs; no schema registration."""
from __future__ import annotations

from ..core.approvals import material_hash
from ..core.ids import hash_json, parse_iso
from .owned_sources import OwnedSourceError, _event_ref, _intact, _near_time, _one, _payload, _same, owned_revision_proof


def consumed_approval_proof(cipher,approval_id,operation,subject_type,subject_id):
    """Verify original native request/grant/consume without current-duty substitution."""
    _intact(cipher)
    try:row=cipher.approvals.get(approval_id)
    except RuntimeError as exc:raise OwnedSourceError('The original source approval disappeared') from exc
    manifest=row['manifest'];events=cipher.audit.entries(entity_type='approval',entity_id=approval_id)
    request=_one([e for e in events if e['action']=='approval.requested'],'Original approval request')
    grant=_one([e for e in events if e['action']=='approval.granted'],'Original approval grant')
    consumed=_one([e for e in events if e['action']=='approval.consumed'],'Original approval consumption')
    if any(e['action'] in ('approval.expired','approval.invalidated') for e in events):
        raise OwnedSourceError('An issued source uses an expired or invalidated approval')
    _same({'operation':row['operation'],'subject':{'type':row['subject_type'],'id':row['subject_id']},'status':row['status']},
          {'operation':operation,'subject':{'type':subject_type,'id':subject_id},'status':'consumed'},'Original source approval subject')
    _same({k:row[k] for k in ('actor_role','policy_version','nonce','expires_at')},
          {k:manifest.get(k) for k in ('actor_role','policy_version','nonce','expires_at')},'Original approval columns')
    _same({'operation':manifest.get('operation'),'subject':manifest.get('subject')},
          {'operation':operation,'subject':{'type':subject_type,'id':subject_id}},'Original approval manifest subject')
    _same(row['manifest_hash'],hash_json(manifest),'Original approval manifest hash')
    _same(row['material_hash'],material_hash(manifest),'Original approval material hash')
    _same(_payload(request),{'operation':operation,'subject':{'type':subject_type,'id':subject_id},'manifest_hash':row['manifest_hash']},'Original approval request')
    _same(_payload(grant),{'operation':operation,'material_hash':row['material_hash']},'Original approval grant')
    _same(_payload(consumed),{'operation':operation,'material_hash':row['material_hash']},'Original approval consumption')
    _same(row['requested_by'],request['actor'],'Original approval requester')
    _same(row['approver'],grant['actor'],'Original approval reviewer')
    _same(row['consumed_by'],consumed['actor'],'Original approval applicator')
    _near_time(row['requested_at'],request,'Original approval request');_near_time(row['granted_at'],grant,'Original approval grant')
    _near_time(row['consumed_at'],consumed,'Original approval consumption')
    if not request['seq']<grant['seq']<consumed['seq'] or parse_iso(row['expires_at'])<=max(parse_iso(row['granted_at']),parse_iso(row['consumed_at'])):
        raise OwnedSourceError('Original approval order or deadline is invalid')
    return {'record':row,'request':_event_ref(request),'grant':_event_ref(grant),'consumption':_event_ref(consumed)}


def _period_at_issue(cipher,period_id,issued_event):
    row=cipher.db.one('SELECT * FROM periods WHERE id=?',(period_id,))
    events=cipher.audit.entries(entity_type='period',entity_id=period_id)
    opened=_one([e for e in events if e['action']=='period.opened'],'Drawing issue period')
    if row is None:raise OwnedSourceError('The original drawing issue period disappeared')
    _same({'name':row['name'],'start':row['start_date'],'end':row['end_date']},_payload(opened),'Drawing issue period identity')
    status='open';at_issue=None;closed=None
    for event in events:
        action=event['action']
        if action=='period.opened':
            if event['seq']!=opened['seq']:raise OwnedSourceError('Drawing period has duplicate opens')
        elif action=='period.closed':
            if status!='open':raise OwnedSourceError('Drawing period has an illegal close history')
            status='closed';closed=event
        elif action=='period.reopened':
            if status!='closed':raise OwnedSourceError('Drawing period has an illegal reopen history')
            status='open';closed=None
        elif action=='period.locked':
            if status!='closed':raise OwnedSourceError('Drawing period has an illegal lock history')
            status='locked'
        else:continue
        if event['seq']<issued_event['seq']:at_issue=status
    if at_issue!='open' or row['status']!=status:
        raise OwnedSourceError('Drawing issue period was not originally open or has unexplained current state')
    if closed:
        _same(row['closed_by'],closed['actor'],'Drawing period closer');_near_time(row['closed_at'],closed,'Drawing period close')
    else:_same({'closed_by':row['closed_by'],'closed_at':row['closed_at']},{'closed_by':None,'closed_at':None},'Open drawing period')
    return {'id':period_id,'name':row['name'],'startDate':row['start_date'],'endDate':row['end_date'],'openAtIssue':True,'birth':_event_ref(opened)}


def _reference_proof(cipher,drawing,revision,reference_id,referenced_by_id,issued_event,superseded_event):
    rows=cipher.db.query('SELECT * FROM drawing_references WHERE drawing_revision_id=? ORDER BY created_at,id',(revision['id'],))
    events=cipher.db.query("SELECT * FROM audit_log WHERE action='drawing.referenced' AND entity_type='drawing_reference' AND json_extract(payload_json,'$.drawing_revision_id')=? ORDER BY seq",(revision['id'],))
    if len(rows)!=len(events) or {r['id'] for r in rows}!={e['entity_id'] for e in events}:
        raise OwnedSourceError('Drawing reference inventory differs from its original births')
    by_id={e['entity_id']:e for e in events};selected=None
    for row in rows:
        event=by_id[row['id']]
        _same(_payload(event),{'drawing_id':drawing['id'],'number':drawing['number'],'drawing_revision_id':revision['id'],'label':revision['label'],
                'referenced_by_type':row['referenced_by_type'],'referenced_by_id':row['referenced_by_id'],'content_hash':revision['content_hash']},'Drawing reference')
        _same(row['drawing_id'],drawing['id'],'Drawing reference parent');_same(row['content_hash'],revision['content_hash'],'Drawing reference source hash')
        _near_time(row['created_at'],event,'Drawing reference')
        if event['seq']<=issued_event['seq'] or superseded_event is not None and event['seq']>=superseded_event['seq']:
            raise OwnedSourceError('The drawing was not the issued revision at the original citation')
        if row['id']==reference_id:
            _same({'type':row['referenced_by_type'],'id':row['referenced_by_id']},{'type':'rfi','id':referenced_by_id},'RFI drawing reference owner')
            selected={'record':row,'event':_event_ref(event),'actor':event['actor']}
    if reference_id is not None and selected is None:raise OwnedSourceError('The exact original RFI drawing reference disappeared')
    return selected


def issued_drawing_proof(cipher,project_id,revision_id,*,current=False,reference_id=None,referenced_by_id=None):
    """Prove original issue, entire current register lineage, and an optional RFI reference."""
    if type(current) is not bool or (reference_id is None)!=(referenced_by_id is None):
        raise OwnedSourceError('Drawing current/reference requirements must be explicit')
    with cipher.db._lock:
        minimal=cipher.db.one('SELECT r.drawing_id,d.project_id FROM drawing_revisions r JOIN drawing_register d ON d.id=r.drawing_id WHERE r.id=?',(revision_id,))
        if minimal is None or minimal['project_id']!=project_id:raise OwnedSourceError('The drawing source is outside this project or unavailable')
        _intact(cipher)
        drawing=cipher.db.one('SELECT * FROM drawing_register WHERE id=?',(minimal['drawing_id'],))
        rows=cipher.db.query('SELECT * FROM drawing_revisions WHERE drawing_id=? ORDER BY sequence',(drawing['id'],))
        events=cipher.db.query("SELECT * FROM audit_log WHERE (entity_type='drawing' AND entity_id=?) OR (entity_type='drawing_revision' AND json_extract(payload_json,'$.drawing_id')=?) ORDER BY seq",(drawing['id'],drawing['id']))
        registered=_one([e for e in events if e['action']=='drawing.registered'],'Drawing registration')
        born=_payload(registered)
        _same({k:drawing[k] for k in ('project_id','number')},{k:born.get(k) for k in ('project_id','number')},'Drawing identity')
        _near_time(drawing['created_at'],registered,'Drawing registration')
        expected_register={'project_id':project_id,'number':born.get('number'),'title':born.get('title'),'discipline':born.get('discipline'),'version':1}
        _same(born,expected_register,'Drawing registration')
        expected={};birth_events={};issue_events={};last_version_event=registered;withdraw_versions={};supersessions=[]
        for event in events:
            data=_payload(event);action=event['action'];rid=event['entity_id']
            if action=='drawing.registered':continue
            if action=='drawing.updated':
                changes=data.get('changes')
                if not isinstance(changes,dict) or not changes or not set(changes)<={'title','discipline'} or data.get('version')!=expected_register['version']+1:
                    raise OwnedSourceError('Drawing metadata update has unexplained facts')
                expected_register.update(changes);expected_register['version']+=1;last_version_event=event;continue
            if data.get('drawing_id')!=drawing['id'] or data.get('number')!=drawing['number']:
                raise OwnedSourceError('Drawing revision history has another identity')
            if action=='drawing.revision_added':
                if rid in expected:raise OwnedSourceError('Drawing revision has duplicate original births')
                replacement=data.get('replaces')
                if replacement is not None:
                    if withdraw_versions.get(replacement)!=data.get('drawing_version') or data.get('drawing_version')!=expected_register['version']:
                        raise OwnedSourceError('Drawing replacement is not tied to its original withdrawal')
                elif data.get('drawing_version')!=expected_register['version']+1:
                    raise OwnedSourceError('Drawing revision birth has an unexplained register version')
                expected_register['version']=data['drawing_version'];last_version_event=event
                expected[rid]={'id':rid,'drawing_id':drawing['id'],'sequence':len(expected)+1,'label':data.get('label'),
                    'document_revision_id':data.get('document_revision_id'),'content_hash':data.get('content_hash'),'note':data.get('note'),
                    'status':'working','approval_id':None,'issued_period_id':None,'issued_at':None,'superseded_at':None,'superseded_by':None,'withdrawn_at':None,'replaced_by':None}
                birth_events[rid]=event
            elif action=='drawing.revision_withdrawn':
                if rid not in expected or expected[rid]['status']!='working' or data.get('drawing_version')!=expected_register['version']+1:
                    raise OwnedSourceError('Drawing withdrawal has an unexplained state')
                expected_register['version']=data['drawing_version'];last_version_event=event;withdraw_versions[rid]=data['drawing_version']
                expected[rid].update(status='withdrawn',replaced_by=data.get('replaced_by'),withdrawn_at=event)
            elif action=='drawing.revision_superseded':
                if rid not in expected or expected[rid]['status']!='issued':raise OwnedSourceError('Drawing supersession has no issued predecessor')
                expected[rid].update(status='superseded',superseded_by=data.get('superseded_by'),superseded_at=event)
                supersessions.append((rid,data.get('superseded_by')))
            elif action=='drawing.issued':
                if rid not in expected or expected[rid]['status']!='working' or data.get('drawing_version')!=expected_register['version']+1:
                    raise OwnedSourceError('Drawing issue has an unexplained original state')
                row=expected[rid]
                _same({k:data.get(k) for k in ('label','document_revision_id','content_hash')},
                      {k:row[k] for k in ('label','document_revision_id','content_hash')},'Drawing issued source')
                superseded=[old for old,new in supersessions if new==rid]
                _same(data.get('superseded'),superseded,'Drawing issued predecessor inventory')
                if len(superseded)>1:raise OwnedSourceError('Drawing issue has multiple current predecessors')
                approval=consumed_approval_proof(cipher,data.get('approval_id'),'drawing.issue','drawing_revision',rid)
                binding=approval['record']['manifest'].get('bindings') or {}
                _same({key:binding.get(key) for key in ('project_id','drawing_id','drawing_number','drawing_version','revision_label','revision_status','document_revision_id','evidence_content_hash')},
                      {'project_id':project_id,'drawing_id':drawing['id'],'drawing_number':drawing['number'],'drawing_version':expected_register['version'],
                       'revision_label':row['label'],'revision_status':'working','document_revision_id':row['document_revision_id'],'evidence_content_hash':row['content_hash']},'Original drawing issue manifest')
                original_evidence=owned_revision_proof(cipher,project_id,row['document_revision_id'])
                original_heads=[p for p in original_evidence['revisions'] if p['event']['seq']<approval['consumption']['seq']]
                original_current=bool(original_heads and original_heads[-1]['record']['id']==row['document_revision_id'])
                _same({'revision':binding.get('evidence_document_revision'),'current':binding.get('evidence_is_current'),'issuedCurrent':data.get('evidence_is_current'),
                       'supersedes':binding.get('supersedes'),'supersedesLabel':binding.get('supersedes_label')},
                      {'revision':original_evidence['revision']['revision'],'current':original_current,'issuedCurrent':original_current,
                       'supersedes':superseded[0] if superseded else None,'supersedesLabel':expected[superseded[0]]['label'] if superseded else None},'Original drawing issue source disclosure')
                _same(approval['record']['consumed_by'],event['actor'],'Original drawing issuer')
                if approval['consumption']['seq']>=event['seq']:raise OwnedSourceError('Drawing issue predates its consumed authority')
                row.update(status='issued',approval_id=data['approval_id'],issued_period_id=data.get('period_id'),issued_at=event)
                issue_events[rid]={'event':event,'approval':approval,'period':_period_at_issue(cipher,data.get('period_id'),event)}
                expected_register['version']=data['drawing_version'];last_version_event=event
            else:raise OwnedSourceError('Drawing register has an unsupported native act')
        if {r['id'] for r in rows}!=set(expected) or len(rows)!=len(expected):raise OwnedSourceError('Drawing revision inventory differs from its original births')
        _same({k:drawing[k] for k in expected_register},expected_register,'Drawing current register')
        _near_time(drawing['updated_at'],last_version_event,'Drawing current register')
        revisions=[]
        for row in rows:
            wanted=dict(expected[row['id']])
            for key in ('issued_at','superseded_at','withdrawn_at'):
                if isinstance(wanted[key],dict):
                    _near_time(row[key],wanted[key],'Drawing '+key);wanted[key]=row[key]
            _same({k:row[k] for k in wanted},wanted,'Drawing revision lifecycle')
            _near_time(row['created_at'],birth_events[row['id']],'Drawing revision birth')
            evidence=owned_revision_proof(cipher,project_id,row['document_revision_id'])
            _same(row['content_hash'],evidence['revision']['content_hash'],'Drawing evidence source')
            revisions.append({'record':row,'birth':_event_ref(birth_events[row['id']]),'evidence':evidence})
        selected=_one([r for r in rows if r['id']==revision_id],'Selected drawing revision')
        issued=issue_events.get(revision_id)
        if issued is None:raise OwnedSourceError('The cited drawing revision has no original issued authority')
        if any(new not in issue_events for old,new in supersessions):raise OwnedSourceError('Drawing supersession lost its actual issued successor')
        current_issued=[r for r in rows if r['status']=='issued'];working=[r for r in rows if r['status']=='working']
        if len(current_issued)>1 or len(working)>1:raise OwnedSourceError('Drawing current heads are ambiguous')
        if current and (not current_issued or current_issued[0]['id']!=revision_id):raise OwnedSourceError('The cited drawing revision is no longer the issued current head')
        evidence=next(r['evidence'] for r in revisions if r['record']['id']==revision_id)
        original={'issuedAt':selected['issued_at'],'issuedBy':issued['event']['actor'],'event':_event_ref(issued['event']),
                  'approval':issued['approval'],'period':issued['period']}
        superseded_event=next((e for e in events if e['action']=='drawing.revision_superseded' and e['entity_id']==revision_id),None)
        reference=_reference_proof(cipher,drawing,selected,reference_id,referenced_by_id,issued['event'],superseded_event)
        body={'projectId':project_id,'drawing':drawing,'revision':selected,'evidence':evidence,'issuedAtBirth':original,
              'current':{'issuedRevisionId':current_issued[0]['id'] if current_issued else None,'workingRevisionId':working[0]['id'] if working else None,
                         'evidenceHeadRevisionId':evidence['currentRevision']['id']},
              'revisions':revisions,'events':[_event_ref(e) for e in events],'reference':reference}
        return {**body,'proofHash':hash_json(body)}

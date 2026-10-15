"""Pure proofs for native evidence and current content-rights correspondence.

This module registers no schema and imports no UI authority. Historical evidence
and the separately verified current head are different facts. Native rights
decisions describe current registry permission; they do not establish ownership.
"""
from __future__ import annotations

import json
from typing import Any

from ..core.ids import canonical_json, hash_json, parse_iso


class OwnedSourceError(RuntimeError):
    """A source cannot be proved against its original native audited history."""


def _same(actual, expected, what):
    if canonical_json(actual) != canonical_json(expected):
        raise OwnedSourceError(f'{what} differs from its original audited facts')


def _one(items, what):
    if len(items) != 1:
        raise OwnedSourceError(f'{what} requires exactly one original audited act')
    return items[0]


def _event_ref(event):
    return {'seq':event['seq'],'hash':event['entry_hash']}


def _payload(event):
    try:
        value=json.loads(event['payload_json'])
    except (TypeError,ValueError) as exc:
        raise OwnedSourceError('Source audit payload is malformed') from exc
    if not isinstance(value,dict):
        raise OwnedSourceError('Source audit payload must be an object')
    return value


def _near_time(value,event,what):
    try:
        stamp,recorded=parse_iso(value),parse_iso(event['ts'])
        if stamp.utcoffset() is None or recorded.utcoffset() is None or not 0 <= (recorded-stamp).total_seconds() <= 1:
            raise ValueError('not the original native act time')
    except (TypeError,ValueError,OverflowError) as exc:
        raise OwnedSourceError(f'{what} time differs from its original audited act') from exc


def _intact(cipher):
    if not cipher.audit.verify_chain()['ok']:
        raise OwnedSourceError('Source audit chain is broken')


def _document(cipher,project_id,document_id):
    row=cipher.db.one('SELECT * FROM documents WHERE id=?',(document_id,))
    if row is None or row['project_id'] != project_id:
        raise OwnedSourceError('The source document is outside this project or unavailable')
    return row


def _document_proof(cipher,project_id,document_id):
    document=_document(cipher,project_id,document_id)
    events=cipher.audit.entries(entity_type='document',entity_id=document_id)
    birth=_one([e for e in events if e['action']=='document.registered'],'Document registration')
    _same({k:document[k] for k in ('project_id','kind','title')},_payload(birth),'Document identity')
    _near_time(document['created_at'],birth,'Document registration')
    revised=[e for e in events if e['action']=='document.revised']
    revisions=cipher.db.query('SELECT * FROM document_revisions WHERE document_id=? ORDER BY revision',(document_id,))
    by_id={r['id']:r for r in revisions}
    if len(revisions)!=len(revised) or len(by_id)!=len(revisions):
        raise OwnedSourceError('Document revision inventory differs from its audited births')
    seen=set();proofs=[]
    for index,event in enumerate(revised,1):
        data=_payload(event);rid=data.get('revision_id');row=by_id.get(rid)
        if row is None or rid in seen or type(data.get('revision')) is not int or data['revision']!=index:
            raise OwnedSourceError('Document revision inventory is missing, duplicated or out of order')
        seen.add(rid)
        _same({'revision_id':row['id'],'revision':row['revision'],'content_hash':row['content_hash'],'note':row['note']},data,'Document revision')
        _near_time(row['created_at'],event,'Document revision')
        if event['seq']<=birth['seq']:
            raise OwnedSourceError('Document revision predates its document registration')
        proofs.append({'record':row,'event':_event_ref(event),'actor':event['actor']})
    return document,birth,proofs


def owned_revision_proof(cipher,project_id,revision_id,*,current=False):
    """Prove an exact owned revision and separately report its native current head."""
    if type(current) is not bool:
        raise OwnedSourceError('The current-source requirement must be explicit')
    with cipher.db._lock:
        minimal=cipher.db.one('SELECT r.document_id,d.project_id FROM document_revisions r JOIN documents d ON d.id=r.document_id WHERE r.id=?',(revision_id,))
        if minimal is None or minimal['project_id']!=project_id:
            raise OwnedSourceError('The source revision is outside this project or unavailable')
        _intact(cipher)
        document,birth,revisions=_document_proof(cipher,project_id,minimal['document_id'])
        selected=_one([p for p in revisions if p['record']['id']==revision_id],'Evidence revision')
        head=revisions[-1]['record'] if revisions else None
        if current and (head is None or head['id']!=revision_id):
            raise OwnedSourceError('The cited evidence revision is no longer current')
        body={'projectId':project_id,'document':document,'revision':selected['record'],
              'currentRevision':head,'documentBirth':_event_ref(birth),'revisionBirth':selected['event'],'revisions':revisions}
        return {**body,'proofHash':hash_json(body)}


def _version_terms(row):
    try:
        uses=json.loads(row['permitted_uses']);processors=json.loads(row['processors'])
    except (TypeError,ValueError) as exc:
        raise OwnedSourceError('Native rights terms are malformed') from exc
    if not isinstance(uses,list) or not isinstance(processors,list) or type(row['purge_on_expiry']) is not int or row['purge_on_expiry'] not in (0,1):
        raise OwnedSourceError('Native rights terms have invalid types')
    return {'permitted_uses':uses,'processors':processors,'expires_on':row['expires_on'],'purge_on_expiry':bool(row['purge_on_expiry'])}


def _license_proof(cipher,license_id):
    header=cipher.db.one('SELECT * FROM rights_licenses WHERE id=?',(license_id,))
    if header is None:
        raise OwnedSourceError('An originally tagged rights license disappeared')
    events=cipher.audit.entries(entity_type='rights_license',entity_id=license_id)
    registered=_one([e for e in events if e['action']=='rights.license_registered'],'Rights license registration')
    initial=_payload(registered)
    identity={k:header[k] for k in ('licensor','work','edition','holder')}
    _same(identity,{k:initial.get(k) for k in identity},'Rights license identity')
    _same(header['created_by'],registered['actor'],'Rights license preparer')
    _near_time(header['created_at'],registered,'Rights license registration')
    rows=cipher.db.query('SELECT * FROM rights_license_versions WHERE license_id=? ORDER BY version',(license_id,))
    by_version={row['version']:row for row in rows}
    retired=cipher.db.query('SELECT * FROM rights_unadopted_versions WHERE license_id=? ORDER BY version',(license_id,))
    terms={k:initial.get(k) for k in ('permitted_uses','processors','expires_on','purge_on_expiry')}
    expected={1:{'terms':terms,'note':initial.get('note'),'hash':initial.get('terms_hash'),'event':registered}}
    last=registered;version=1;retire_expect={}
    for event in events:
        if event['seq']<=registered['seq']:continue
        data=_payload(event)
        if event['action']=='rights.license_updated':
            if data.get('previous_version')!=version or data.get('version')!=version+1 or not isinstance(data.get('changes'),dict) or not data['changes']:
                raise OwnedSourceError('Rights license update has an unexplained version')
            changed=dict(terms)
            for key,delta in data['changes'].items():
                if key not in changed or not isinstance(delta,dict) or set(delta)!={'from','to'}:
                    raise OwnedSourceError('Rights license update has an unsupported change')
                _same(delta['from'],changed[key],'Rights license previous terms')
                changed[key]=delta['to']
            terms=changed;version+=1
            expected[version]={'terms':terms,'note':data.get('note'),'hash':data.get('terms_hash'),'event':event}
        elif event['action']=='rights.unadopted_version_superseded':
            stray=version+1;restored=version+2
            if data.get('restored_from_version')!=version or data.get('unadopted_version')!=stray or data.get('version')!=restored:
                raise OwnedSourceError('Rights repair has an unexplained version')
            expected[stray]={'terms':data.get('unadopted_terms'),'note':None,'hash':data.get('unadopted_terms_hash'),
                'id':data.get('unadopted_version_id'),'created_by':data.get('unadopted_created_by'),
                'created_at':data.get('unadopted_created_at'),'event':event,'unadopted':True}
            restore_note=data.get('note') or f'restores version {version} terms over unadopted version {stray}'
            expected[restored]={'terms':dict(terms),'note':restore_note,'hash':data.get('terms_hash'),'event':event}
            retire_expect[stray]={'license_id':license_id,'version':stray,'superseded_by':restored,
                'note':data.get('note'),'recorded_by':event['actor'],'event':event}
            version=restored
        else:
            raise OwnedSourceError('Rights license history contains an unsupported or duplicate act')
        last=event
    if set(by_version)!=set(expected) or len(rows)!=len(expected) or header['version']!=version:
        raise OwnedSourceError('Rights terms inventory or current head differs from its original audited history')
    _near_time(header['updated_at'],last,'Rights license current head')
    proofs=[]
    for number,item in expected.items():
        row=by_version[number];native_terms=_version_terms(row)
        _same(native_terms,item['terms'],'Rights license terms')
        if not item.get('unadopted'):_same(row['note'],item['note'],'Rights license note')
        _same(row['terms_hash'],item['hash'],'Rights terms hash')
        recomputed=cipher.plugin('rights')._terms_hash(identity,native_terms['permitted_uses'],native_terms['processors'],native_terms['expires_on'],native_terms['purge_on_expiry'])
        _same(row['terms_hash'],recomputed,'Rights terms content')
        if item.get('unadopted'):
            for key in ('id','created_by','created_at'):_same(row[key],item[key],'Retired unadopted rights version')
        else:
            _same(row['created_by'],item['event']['actor'],'Rights terms author')
            _near_time(row['created_at'],item['event'],'Rights terms adoption')
        proofs.append({'record':row,'event':_event_ref(item['event']),'unadopted':bool(item.get('unadopted'))})
    if {r['version'] for r in retired}!=set(retire_expect) or len(retired)!=len(retire_expect):
        raise OwnedSourceError('Retired rights inventory differs from its original audit')
    for row in retired:
        expected_retired=retire_expect[row['version']]
        _same({k:row[k] for k in ('license_id','version','superseded_by','note','recorded_by')},
              {k:v for k,v in expected_retired.items() if k!='event'},'Retired rights record')
        _near_time(row['recorded_at'],expected_retired['event'],'Rights version retirement')
    return {'record':header,'versions':proofs,'retired':retired,'events':[_event_ref(e) for e in events]}


def _processor_proof(cipher):
    rows=cipher.db.query('SELECT * FROM rights_ai_processor_settings ORDER BY version')
    events=cipher.audit.entries(entity_type='rights_setting',entity_id='default_ai_processor')
    if len(rows)!=len(events):raise OwnedSourceError('Rights processor setting inventory differs from its audit')
    previous=None
    for index,(row,event) in enumerate(zip(rows,events),1):
        if event['action']!='rights.default_processor_set':raise OwnedSourceError('Rights processor setting has an unsupported act')
        data=_payload(event)
        _same({'setting_id':row['id'],'version':row['version'],'previous_processor':previous,'processor':row['processor'],'note':row['note']},data,'Rights processor setting')
        if row['version']!=index:raise OwnedSourceError('Rights processor setting versions are not contiguous')
        _same(row['set_by'],event['actor'],'Rights processor setter');_near_time(row['set_at'],event,'Rights processor setting')
        previous=row['processor']
    return {'records':rows,'events':[_event_ref(e) for e in events]}


def document_rights_proof(cipher,project_id,document_id,use):
    """Prove current native permission and all original history relevant to a document."""
    with cipher.db._lock:
        _document(cipher,project_id,document_id)  # Minimal project scope before private audit.
        _intact(cipher)
        _document_proof(cipher,project_id,document_id)
        rights=cipher.plugin('rights')
        if use not in ('internal_reference','project_use','distribution','ai_retrieval','ai_embedding'):
            raise OwnedSourceError('The source rights use is unsupported')
        events=[e for e in cipher.audit.entries(entity_type='document',entity_id=document_id) if e['action'].startswith('rights.')]
        tags=cipher.db.query('SELECT * FROM rights_document_tags WHERE document_id=? ORDER BY tagged_at,id',(document_id,))
        purges=cipher.db.query('SELECT * FROM rights_purges WHERE document_id=? ORDER BY purged_at,id',(document_id,))
        born={};removed={};purge_events={};license_ids=set()
        for event in events:
            data=_payload(event);lid=data.get('license_id')
            if not isinstance(lid,str):raise OwnedSourceError('Document rights history has no exact license')
            license_ids.add(lid)
            if event['action']=='rights.document_tagged':
                identifier=data.get('tag_id')
                if identifier in born:raise OwnedSourceError('Rights tag has duplicate audited births')
                born[identifier]=event
            elif event['action']=='rights.document_untagged':
                identifier=data.get('tag_id')
                if identifier in removed:raise OwnedSourceError('Rights tag has duplicate audited removals')
                removed[identifier]=event
            elif event['action']=='rights.purge_recorded':
                identifier=data.get('purge_id')
                if identifier in purge_events:raise OwnedSourceError('Rights purge has duplicate audited births')
                purge_events[identifier]=event
            else:raise OwnedSourceError('Document rights history contains an unsupported act')
        if {t['id'] for t in tags}!=set(born) or len(tags)!=len(born) or not set(removed)<=set(born):
            raise OwnedSourceError('Rights tag inventory differs from its original audited births')
        license_ids.update(t['license_id'] for t in tags)
        license_ids.update(p['license_id'] for p in purges)
        licenses={lid:_license_proof(cipher,lid) for lid in sorted(license_ids)}
        for tag in tags:
            event=born[tag['id']];data=_payload(event)
            _same({'tag_id':tag['id'],'license_id':tag['license_id'],'license_version':tag['license_version']},
                  {k:data.get(k) for k in ('tag_id','license_id','license_version')},'Rights tag identity')
            lic=licenses[tag['license_id']];header=lic['record']
            bound=_one([v for v in lic['versions'] if v['record']['version']==tag['license_version']],'Tagged rights version')
            _same({k:data.get(k) for k in ('licensor','work','edition','terms_hash')},
                  {**{k:header[k] for k in ('licensor','work','edition')},'terms_hash':bound['record']['terms_hash']},'Rights tag original terms')
            _same(tag['tagged_by'],event['actor'],'Rights tag author');_near_time(tag['tagged_at'],event,'Rights tag')
            removal=removed.get(tag['id'])
            if removal is None:
                _same({k:tag[k] for k in ('status','removed_by','removed_at','removal_reason')},
                      {'status':'active','removed_by':None,'removed_at':None,'removal_reason':None},'Active rights tag')
            else:
                changed=_payload(removal)
                _same({'license_id':tag['license_id'],'reason':tag['removal_reason']},
                      {k:changed.get(k) for k in ('license_id','reason')},'Rights tag removal')
                _same(tag['status'],'removed','Rights tag status');_same(tag['removed_by'],removal['actor'],'Rights tag remover')
                _near_time(tag['removed_at'],removal,'Rights tag removal')
                if removal['seq']<=event['seq']:raise OwnedSourceError('Rights tag removal predates its birth')
        if {p['id'] for p in purges}!=set(purge_events) or len(purges)!=len(purge_events):
            raise OwnedSourceError('Rights purge inventory differs from its original audited births')
        for purge in purges:
            event=purge_events[purge['id']];data=_payload(event)
            _same({k:purge[k] for k in ('license_id','license_version','expires_on','purged_on','note')},
                  {k:data.get(k) for k in ('license_id','license_version','expires_on','purged_on','note')},'Rights purge')
            original_tag=born.get(data.get('tag_id'))
            if original_tag is None or original_tag['seq']>=event['seq']:
                raise OwnedSourceError('Rights purge has no original preceding source tag')
            _same(purge['purged_by'],event['actor'],'Rights purge author');_near_time(purge['purged_at'],event,'Rights purge')
        processor=_processor_proof(cipher) if use in ('ai_retrieval','ai_embedding') else None
        decision=rights.check_use(document_id,use)
        body={'projectId':project_id,'documentId':document_id,'use':use,'onDate':decision['on_date'],
              'hadLicenseHistory':bool(born),'allowed':decision['allowed'],'decision':decision,
              'tags':tags,'licenses':list(licenses.values()),'purges':purges,'events':[_event_ref(e) for e in events],
              'processorSettings':processor}
        return {**body,'proofHash':hash_json(body)}

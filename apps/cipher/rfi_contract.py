"""Scoped RFI facts, exact original citations and separately disclosed current heads."""
from __future__ import annotations

import base64
from decimal import Decimal
from functools import wraps
from hashlib import sha256
import hmac
import json

from .ap_contract import APRefusal
from .core.approvals import material_hash
from .core.ids import canonical_json, parse_iso, utcnow
from .domain.owned_sources import document_rights_proof
from .rfi_sessions import RFIIdentityRefusal, authority_for
from .rfi_wire import ACTION_ROUTES, COLLECTIONS, MAX_CITATIONS, MAX_SAFE_INTEGER, MAX_TEXT_CHARACTERS, PROVENANCE, RECIPIENTS

API_PREFIX = '/api/rfi-practice/v1/'
RESOURCE_TYPES = {route.action: route.resource_type for route in ACTION_ROUTES}


def _missing():
    raise APRefusal(404, 'not_found', 'The record is unavailable in this RFI session.', 'record')


def _read(method):
    @wraps(method)
    def wrapped(self, *args, **kwargs):
        with self.cipher.db._lock:
            try:
                return method(self, *args, **kwargs)
            except APRefusal:
                raise
            except RFIIdentityRefusal as exc:
                raise APRefusal(exc.status, exc.code, exc.message, exc.target) from None
            except Exception:
                raise APRefusal(423, 'rfi_source_unavailable', 'The original RFI source and current disclosure could not be verified.', 'record') from None
    return wrapped


class RFIContract:
    def __init__(self, cipher, *, secret):
        if type(secret) is not bytes or len(secret) < 32:
            raise ValueError('RFI contract requires an owned private signing key')
        self.cipher, self.secret = cipher, secret

    @property
    def domain(self):
        return self.cipher.plugin('rfi_controls')

    def _authority(self, person_id):
        self.cipher.db.require_practice_mode()
        authority = authority_for(self.cipher, person_id)
        if not authority.project_ids:
            raise APRefusal(403, 'rfi_duty_required', "This view requires the person's own current internal project membership.", 'duty')
        return authority

    def _scope(self, authority, identifier, kind, duty='staff'):
        from .domain.rfi_controls import RFIError
        if kind == 'project':
            record = {'projectId': identifier} if identifier in authority.project_ids else None
        elif kind in ('rfi', 'responseApproval', 'distributionApproval'):
            try:
                record = (self.domain.source_scope(identifier) if kind == 'rfi' else self.domain.approval_scope(identifier))
            except RFIError:
                _missing()
        else:
            raise APRefusal(422, 'unsupported_resource', 'Choose a fixed RFI resource.', 'record')
        if record is None or record['projectId'] not in authority.project_ids:
            _missing()
        authority.require(record['projectId'], duty)
        if kind != 'project':
            if kind == 'rfi':
                if not self.domain.is_modern(identifier):
                    _missing()
            else:
                operation = self.cipher.db.scalar('SELECT operation FROM approvals WHERE id=?', (identifier,))
                if operation is None:
                    # Own current scope is established. A surviving original birth
                    # now requires its full proof; deleted native rows are a hold.
                    operation = self.domain.approval_proof(identifier)['record']['operation']
                expected = 'field.respond_rfi' if kind == 'responseApproval' else 'field.distribute_rfi'
                if operation != expected:
                    _missing()
        return {'id': identifier, **record}

    @_read
    def authorize(self, person_id, action, resource_id):
        authority = self._authority(person_id)
        definition = next((route for route in ACTION_ROUTES if route.action == action), None)
        if definition is None:
            raise APRefusal(422, 'unsupported_action', 'Choose a fixed RFI action.', 'action')
        record = self._scope(authority, resource_id, definition.resource_type, definition.duty)
        return {'personId': authority.person_id, 'login': authority.login, 'duty': definition.duty,
                'operationRole': authority.operation_role(record['projectId'], definition.duty),
                'authority': authority, 'projectId': record['projectId'], 'record': record}

    def _project(self, identifier):
        row = self.cipher.project(identifier)
        return {'id': row['id'], 'name': row['name']}

    def _person(self, recorded):
        if recorded is None:
            return None
        login = recorded['login'] if type(recorded) is dict else recorded
        person = self.cipher.plugin('people').person_for(login)
        if person is None or type(recorded) is dict and person['id'] != recorded['personId']:
            raise ValueError('The original RFI person is unavailable')
        return {'id': person['id'], 'displayName': person['display_name']}

    @staticmethod
    def impact(cost, days):
        cents = None if cost is None else int(Decimal(cost) * 100)
        if (days is not None and (type(days) is not int or not 0 <= days <= MAX_SAFE_INTEGER)
                or cents is not None and not 0 <= cents <= MAX_SAFE_INTEGER):
            raise ValueError('The original potential impacts exceed exact public integer bounds')
        return {'costImpactCents': cents,
                'scheduleImpactDays': days, 'informationalOnly': True, 'adopted': False}

    @staticmethod
    def _right(proof):
        return {'use': proof['use'], 'allowed': proof['allowed'],
                'status': 'permitted' if proof['allowed'] else 'held',
                'reason': 'Current native permission permits this use.' if proof['allowed'] else 'Current native permission holds this use.',
                'onDate': proof['onDate'], 'sourceContentAvailable': False}

    def _rights(self, source):
        project = source.get('projectId', source.get('record', {}).get('project_id'))
        ids = {p['document']['id'] for p in source['documents']} | {p['evidence']['document']['id'] for p in source['drawings']}
        return {did: [document_rights_proof(self.cipher, project, did, use) for use in ('project_use', 'distribution')]
                for did in sorted(ids)}

    def source_disclosure(self, source, reviewed_context=None):
        """Only citation labels/heads/permission decisions; no source bytes/private proof hashes."""
        rights = self._rights(source)
        reviewed_context = reviewed_context or {}
        old_drawings = {p['revision']['id']: p for p in reviewed_context.get('drawings', ())}
        old_documents = {p['revision']['id']: p for p in reviewed_context.get('documents', ())}
        old_rights = {(p['documentId'], p['use']): p for p in reviewed_context.get('rights', ())}
        def rights_changed(document_id):
            return any((document_id, p['use']) in old_rights
                and self.domain._stable_rights(p) != self.domain._stable_rights(old_rights[(document_id, p['use'])])
                for p in rights[document_id])
        drawings, documents = [], []
        for proof in source['drawings']:
            row, rev, current = proof['drawing'], proof['revision'], proof['current']
            issued = next((p['record'] for p in proof['revisions'] if p['record']['id'] == current['issuedRevisionId']), None)
            previous = old_drawings.get(rev['id'])
            drawings.append({'drawingId': row['id'], 'drawingNumber': row['number'], 'title': row['title'],
                'revisionId': rev['id'], 'revisionLabel': rev['label'], 'documentRevisionId': rev['document_revision_id'],
                'issuedAtCitation': {'issuedAt': proof['issuedAtBirth']['issuedAt'], 'issuedBy': proof['issuedAtBirth']['issuedBy']},
                'current': {'status': rev['status'], 'issuedRevisionId': current['issuedRevisionId'],
                    'issuedRevisionLabel': issued['label'] if issued else None, 'workingRevisionId': current['workingRevisionId'],
                    'evidenceHeadRevisionId': current['evidenceHeadRevisionId']},
                'sourceChangedSinceReview': (previous != proof or rights_changed(proof['evidence']['document']['id'])) if previous else None,
                'rights': [self._right(p) for p in rights[proof['evidence']['document']['id']]], 'sourceContentAvailable': False})
        for proof in source['documents']:
            doc, rev, current = proof['document'], proof['revision'], proof['currentRevision']
            previous = old_documents.get(rev['id'])
            documents.append({'documentId': doc['id'], 'kind': doc['kind'], 'title': doc['title'],
                'revisionId': rev['id'], 'revisionNumber': rev['revision'],
                'currentRevisionId': current['id'], 'currentRevisionNumber': current['revision'],
                'sourceChangedSinceReview': (previous != proof or rights_changed(doc['id'])) if previous else None,
                'rights': [self._right(p) for p in rights[doc['id']]], 'sourceContentAvailable': False})
        return {'drawings': drawings, 'documents': documents, 'sourceContentAvailable': False}

    def _metadata(self):
        from .rfi_receipts import rfi_receipt_inventory_proof
        return rfi_receipt_inventory_proof(self.cipher.db, self.cipher.audit)

    def _materials(self, projects):
        projects = tuple(projects)
        sources = self.domain.source_inventory(project_ids=projects)
        approvals = self.domain.approval_inventory(project_ids=projects)
        return {'projectIds': projects, 'sources': sources, 'approvals': approvals,
                'rights': [{'rfiId': p['native']['id'], 'proofs': self._rights(p)} for p in sources],
                'currentAuthorizations': [{'id': p['record']['id'], 'authorizationStatus': self._authorization_status(p)} for p in approvals],
                'authorizationClock': [{'id': p['record']['id'], 'expired': p['record']['status'] in ('pending', 'granted')
                    and parse_iso(p['record']['expires_at']) <= utcnow()} for p in approvals], 'receipts': self._metadata()}

    def _token(self, value):
        return 'rfiv1:' + hmac.new(self.secret, canonical_json(value).encode(), sha256).hexdigest()

    def _version(self, authority, identifier, kind, materials):
        project = self._scope(authority, identifier, kind)['projectId']
        if tuple(materials['projectIds']) != (project,):
            materials = self._materials((project,))
        choices = self.domain.preparation_sources(project, actor=authority.login) if kind == 'project' else None
        return self._token({'personId': authority.person_id, 'scopeHash': authority.scope_hash, 'resourceId': identifier,
            'resourceType': kind, 'records': materials, 'preparation': choices, 'workspace': self.cipher.db.mode_status(),
            'authority': self.cipher.db.authority_status()})

    @_read
    def version(self, person_id, resource_id, resource_type):
        authority = self._authority(person_id)
        scope = self._scope(authority, resource_id, resource_type)
        return self._version(authority, resource_id, resource_type, self._materials((scope['projectId'],)))

    def _response(self, proof):
        if proof is None:
            return None
        body = proof['record']
        return {'id': body['id'], 'nativeVersion': body['native_version'], 'text': body['response'],
                **self.impact(body['costImpact'], body['scheduleImpactDays']), 'author': self._person(body['person']), 'createdAt': body['created_at']}

    def _list(self, proof):
        if proof is None:
            return None
        body = proof['record']
        return {'id': body['id'], 'nativeVersion': body['native_version'], 'recipients': body['recipients'],
                'preparedBy': self._person(body['person']), 'createdAt': body['created_at'], 'channel': 'mail-sink', 'externalDistribution': False}

    def _authorization_status(self, proof):
        ap = proof['record']; sealed = proof['source']['record']; status = ap['status']; effective = status
        if status in ('pending', 'granted'):
            if parse_iso(ap['expires_at']) <= utcnow():
                effective = 'expired'
            else:
                try:
                    from .domain.rfi_controls import require_rfi_duty
                    require_rfi_duty(self.cipher, ap['requested_by'], sealed['project_id'], 'pm')
                    if ap['status'] == 'granted':
                        require_rfi_duty(self.cipher, ap['approver'], sealed['project_id'], 'pm')
                    manifest = self.cipher._manifest(ap['operation'], ap['subject_id'], 'pm')
                    if material_hash(manifest) != ap['material_hash'] or manifest.get('governance') != ap['manifest'].get('governance'):
                        effective = 'stale'
                except Exception:
                    effective = 'stale'
        return effective

    def _approval(self, authority, proof, materials):
        ap = proof['record']; sealed = proof['source']['record']; status = ap['status']
        effective = self._authorization_status(proof)
        kind = 'responseApproval' if ap['operation'] == 'field.respond_rfi' else 'distributionApproval'
        return {**PROVENANCE, 'id': ap['id'], 'projectId': sealed['project_id'], 'rfiId': ap['subject_id'],
                'operation': ap['operation'], 'status': status, 'authorizationStatus': effective,
                'originalGrantStatus': 'granted' if proof['grant'] else None,
                'requester': self._person(ap['requested_by']), 'reviewer': self._person(ap['approver']),
                'appliedBy': self._person(ap['consumed_by']), 'requestedAt': ap['requested_at'], 'grantedAt': ap['granted_at'],
                'appliedAt': ap['consumed_at'], 'expiresAt': ap['expires_at'],
                'version': self._version(authority, ap['id'], kind, materials)}

    def _record(self, authority, source, materials, *, history=False):
        row = source['native']; approvals = source['approvals']
        response = [p for p in approvals if p['record']['operation'] == 'field.respond_rfi']
        distribution = [p for p in approvals if p['record']['operation'] == 'field.distribute_rfi']
        latest = approvals[-1]['source']['record']['context'] if approvals else None
        official = None
        if source['answer']:
            outcome = source['answer']; ap = outcome['approval']['record']
            revision = next(p for p in source['responseRevisions'] if p['record']['id'] == outcome['source']['record']['responseRevisionId'])
            official = {**self._response(revision), 'status': 'answered', 'approvalId': ap['id'],
                        'requester': self._person(ap['requested_by']), 'reviewer': self._person(ap['approver']),
                        'appliedBy': self._person(outcome['applicator']), 'answeredAt': row['answered_at'], 'engineeringCertification': False}
        deliveries = []
        for proof in source['distributions']:
            body = proof['record']; ap = proof['approval']['record']
            deliveries.append({'id': body['id'], 'approvalId': body['approval_id'], 'status': 'distributed',
                'recipients': json.loads(body['recipients_json']), 'channel': 'mail-sink', 'externalDistribution': False,
                'distributedAt': body['distributed_at'], 'distributedBy': self._person(proof['applicator']),
                'requester': self._person(ap['requested_by']), 'reviewer': self._person(ap['approver'])})
        value = {**PROVENANCE, 'id': row['id'], 'projectId': row['project_id'], 'project': self._project(row['project_id']),
            'number': row['number'], 'subject': row['subject'], 'question': row['question'], 'status': row['status'],
            'nativeVersion': row['version'], 'version': self._version(authority, row['id'], 'rfi', materials),
            'createdBy': self._person(source['record']['person']), 'createdAt': row['created_at'],
            'citations': self.source_disclosure(source, latest), 'draftResponse': self._response(source['latestResponse']),
            'officialResponse': official, 'responseApproval': self._approval(authority, response[-1], materials) if response else None,
            'distributionList': self._list(source['latestDistribution']),
            'distributionApproval': self._approval(authority, distribution[-1], materials) if distribution else None,
            'distributions': deliveries, 'actions': [{'action': route.action, 'resourceType': route.resource_type,
                'requiredDuty': route.duty, 'authorityAllowed': authority.allows(row['project_id'], route.duty), 'requiresReview': True}
                for route in ACTION_ROUTES if route.resource_type == 'rfi']}
        if history:
            value.update(responseHistory=[self._response(p) for p in source['responseRevisions']],
                         distributionHistory=[self._list(p) for p in source['distributionRevisions']])
        return value

    @_read
    def preparation(self, person_id, project_id):
        authority = self._authority(person_id); self._scope(authority, project_id, 'project')
        choices = self.domain.preparation_sources(project_id, actor=authority.login)
        materials = self._materials((project_id,)); disclosure = self.source_disclosure(choices)
        for public, proof in zip(disclosure['drawings'], choices['drawings']):
            allowed = next(p['allowed'] for p in public['rights'] if p['use'] == 'project_use')
            public.update(citable=allowed, citationHold=None if allowed else {'code': 'project_use_required', 'message': 'This source does not permit current project use.'})
        for public, proof in zip(disclosure['documents'], choices['documents']):
            public.update(citable=proof['citable'], citationHold=proof['citationHold'])
        return {**PROVENANCE, 'project': self._project(project_id), 'sources': disclosure,
                'maxTextCharacters': MAX_TEXT_CHARACTERS, 'maxCitationsPerKind': MAX_CITATIONS,
                'version': self._version(authority, project_id, 'project', materials)}

    @_read
    def rfi(self, person_id, rfi_id):
        authority = self._authority(person_id); scope = self._scope(authority, rfi_id, 'rfi')
        materials = self._materials((scope['projectId'],))
        source = next(p for p in materials['sources'] if p['native']['id'] == rfi_id)
        return self._record(authority, source, materials, history=True)

    def _packet(self, person_id, approval_id, kind):
        authority = self._authority(person_id); scope = self._scope(authority, approval_id, kind)
        materials = self._materials((scope['projectId'],)); proof = self.domain.approval_proof(approval_id)
        source = next(p for p in materials['sources'] if p['native']['id'] == proof['record']['subject_id'])
        sealed = proof['source']['record']; context = sealed['context']
        reviewed = {'projectId': scope['projectId'], 'drawings': context['drawings'], 'documents': context['documents']}
        # Reconstruct the public snapshot using its original current-head and rights facts, not today's permissions.
        snapshot = self.source_disclosure(reviewed)
        snapshot_rights = {p['documentId']: p for p in context['rights']}
        for item in snapshot['drawings']:
            raw = next(p for p in reviewed['drawings'] if p['revision']['id'] == item['revisionId'])
            item['rights'] = [self._right(snapshot_rights[raw['evidence']['document']['id']])]
        for item in snapshot['documents']:
            item['rights'] = [self._right(snapshot_rights[item['documentId']])]
        response = next((p for p in source['responseRevisions'] if p['record']['id'] == sealed['responseRevisionId']), None)
        recipients = next((p for p in source['distributionRevisions'] if p['record']['id'] == sealed['distributionRevisionId']), None)
        return {**self._approval(authority, proof, materials), 'rfi': self._record(authority, source, materials),
                'reviewedCitations': snapshot, 'currentCitations': self.source_disclosure(source, context),
                'reviewedResponse': self._response(response), 'reviewedDistributionList': self._list(recipients)}

    @_read
    def response_packet(self, person_id, approval_id):
        return self._packet(person_id, approval_id, 'responseApproval')

    @_read
    def distribution_packet(self, person_id, approval_id):
        return self._packet(person_id, approval_id, 'distributionApproval')

    @_read
    def distribution_preparation(self, person_id, rfi_id):
        authority = self._authority(person_id); scope = self._scope(authority, rfi_id, 'rfi', 'pm')
        materials = self._materials((scope['projectId'],)); source = next(p for p in materials['sources'] if p['native']['id'] == rfi_id)
        return {**PROVENANCE, 'rfi': self._record(authority, source, materials), 'recipientChoices': list(RECIPIENTS),
                'channel': 'mail-sink', 'externalDistribution': False,
                'version': self._version(authority, rfi_id, 'rfi', materials)}

    @_read
    def read(self, person_id, collection, *, project_id=None, status=None, search=None, top=50, cursor=None):
        authority = self._authority(person_id)
        if collection not in COLLECTIONS:
            raise APRefusal(404, 'route_not_found', 'This RFI view is unavailable.')
        if project_id is not None and project_id not in authority.project_ids:
            _missing()
        projects = (project_id,) if project_id else authority.project_ids
        for project in projects:
            authority.require(project, 'staff')
        materials = self._materials(projects)
        if collection == 'projects':
            items = [{**PROVENANCE, **self._project(project)} for project in projects]
        elif collection == 'rfis':
            items = [self._record(authority, p, materials) for p in materials['sources']]
        else:
            operation = 'field.respond_rfi' if collection == 'rfi-response-approvals' else 'field.distribute_rfi'
            items = [self._approval(authority, p, materials) for p in materials['approvals'] if p['record']['operation'] == operation]
        return self._page(authority, collection, items, materials, project_id=project_id, status=status, search=search, top=top, cursor=cursor)

    def _page(self, authority, collection, items, materials, *, project_id, status, search, top, cursor):
        if type(top) is not int or not 1 <= top <= 50:
            raise APRefusal(422, 'invalid_query', 'Choose a page size from one through fifty.', 'top')
        if search is not None and (type(search) is not str or not search.strip() or len(search) > 200 or any(ord(c) < 32 for c in search)):
            raise APRefusal(422, 'invalid_query', 'Use a plain search of at most 200 characters.', 'search')
        statuses = {'open', 'answered'} if collection == 'rfis' else {'pending', 'granted', 'consumed', 'expired', 'invalidated', 'stale'} if collection != 'projects' else set()
        if status is not None and status not in statuses:
            raise APRefusal(422, 'invalid_query', 'Choose a listed status.', 'status')
        facets = sorted({p.get('authorizationStatus', p.get('status')) for p in items} - {None})
        if status:
            items = [p for p in items if p.get('authorizationStatus', p.get('status')) == status]
        if search:
            items = [p for p in items if search.casefold() in '\n'.join(str(p.get(k, '')) for k in ('name', 'number', 'subject', 'question', 'operation', 'rfiId')).casefold()]
        items.sort(key=lambda p: (p.get('number', p.get('name', p.get('requestedAt', ''))), p['id']))
        binding = self._token({'personId': authority.person_id, 'scopeHash': authority.scope_hash, 'collection': collection,
            'projectId': project_id, 'status': status, 'search': search, 'top': top, 'records': materials})
        offset = 0
        if cursor is not None:
            try:
                encoded, signature = cursor.split('.')
                raw = base64.urlsafe_b64decode(encoded + '=' * (-len(encoded) % 4)); value = json.loads(raw)
                if not hmac.compare_digest(signature, hmac.new(self.secret, raw, sha256).hexdigest()) or value['binding'] != binding or type(value['offset']) is not int or value['offset'] < 0:
                    raise ValueError
                offset = value['offset']
            except (ValueError, TypeError, KeyError, UnicodeError):
                raise APRefusal(422, 'invalid_cursor', 'Refresh this RFI view before paging.', 'cursor') from None
        following = None
        if offset + top < len(items):
            raw = canonical_json({'binding': binding, 'offset': offset + top}).encode()
            following = base64.urlsafe_b64encode(raw).decode().rstrip('=') + '.' + hmac.new(self.secret, raw, sha256).hexdigest()
        return {**PROVENANCE, 'items': items[offset:offset + top], 'count': len(items), 'nextCursor': following, 'facets': {'statuses': facets}}

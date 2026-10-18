"""Closed FLD02 capture inputs; validation grants no device or source authority.

Capture attribution is declared evidence. The service must bind it to the
original device registration and independently recheck the current canonical
Person, Project duties, exact revision base and current source rights at sync.
"""
from __future__ import annotations

import math

from cipher_aec.api.contracts import canonical_json, operation_id
from cipher_aec.api.errors import DomainError
from cipher_aec.field import contracts as field

SCHEMA = 'cipher.field.offline.v1'
MAX_ENVELOPE_BYTES = 256 * 1024
MAX_JSON_DEPTH = 32
MAX_JSON_NODES = 20000
CREATE_FIELDS = frozenset({'action', 'family', 'definition', 'photos', 'quantities'})
REVISE_FIELDS = CREATE_FIELDS | {'record_id', 'expected_version', 'base_revision_id', 'base_revision_digest', 'amendment_reason'}
ENVELOPE_FIELDS = frozenset({'schema', 'device_id', 'capture_id', 'company', 'project', 'actor_person', 'actor_user', 'captured_at', 'command'})


def fail(message='Supply an exact supported offline field capture.', field_name='capture', *, code='invalid_field_offline'):
    raise DomainError(code, message, 422, {'field': field_name})


def closed(value, keys, field_name='capture'):
    if type(value) is not dict or set(value) != set(keys):
        fail(field_name=field_name)
    return value


def identifier(value, field_name='id'):
    """Canonical UUIDv4 input without the transport helper's whitespace trim."""
    if type(value) is not str or value != value.strip():
        fail('Use a canonical UUID version 4 identifier.', field_name)
    try:
        if operation_id(value) != value:
            fail('Use a canonical UUID version 4 identifier.', field_name)
    except DomainError:
        fail('Use a canonical UUID version 4 identifier.', field_name)
    return value


def scope(company, project):
    """Offline capture is explicitly Project-owned; null means no authority."""
    field.text(company, 'company', 140)
    field.text(project, 'project', 140)
    return {'company': company, 'scope_type': 'Project', 'project': project}


checksum = field.checksum
timestamp = field.timestamp


def json_input(value):
    """Reject Python-only/coerced values before canonical JSON size admission."""
    ancestors = set()
    nodes = 0
    text_bytes = 0

    def visit(item, depth):
        nonlocal nodes, text_bytes
        nodes += 1
        if nodes > MAX_JSON_NODES or depth > MAX_JSON_DEPTH:
            fail('The offline capture exceeds its bounded JSON structure.', code='field_offline_limit')
        kind = type(item)
        if kind is str:
            try:
                text_bytes += len(item.encode('utf-8'))
            except UnicodeEncodeError:
                fail('Use valid JSON text in the offline capture.')
            if text_bytes > MAX_ENVELOPE_BYTES:
                fail('The offline capture exceeds the 256 KiB JSON budget.', code='field_offline_limit')
        elif item is None or kind in (bool, int):
            return
        elif kind is float:
            if not math.isfinite(item):
                fail('Use finite JSON values in the offline capture.')
        elif kind in (dict, list):
            identity = id(item)
            if identity in ancestors:
                fail('Use an acyclic JSON offline capture.')
            ancestors.add(identity)
            try:
                if kind is dict:
                    for key, child in item.items():
                        if type(key) is not str:
                            fail('Offline capture JSON object keys must be text.')
                        visit(key, depth + 1)
                        visit(child, depth + 1)
                else:
                    for child in item:
                        visit(child, depth + 1)
            finally:
                ancestors.remove(identity)
        else:
            fail('Use only JSON values in the offline capture.')

    visit(value, 0)
    try:
        encoded = canonical_json(value).encode('utf-8')
    except (TypeError, ValueError, OverflowError, RecursionError, UnicodeEncodeError):
        fail('The offline capture cannot be represented as finite JSON.')
    if len(encoded) > MAX_ENVELOPE_BYTES:
        fail('The offline capture exceeds the 256 KiB JSON budget.', code='field_offline_limit')
    return value


def command(value):
    """Admit original FLD01 create/revise inputs only, without coercion."""
    json_input(value)
    if type(value) is not dict or value.get('action') not in ('create', 'revise'):
        fail('Offline captures support documentary create or revise only.', 'command')
    closed(value, CREATE_FIELDS if value['action'] == 'create' else REVISE_FIELDS, 'command')
    if value['family'] not in ('daily', 'ticket'):
        fail('Choose a daily report or documentary T&M ticket.', 'family')
    (field.daily_definition if value['family'] == 'daily' else field.ticket_definition)(value['definition'])
    field.photos(value['photos'])
    field.sequence(value['quantities'], 'quantities', 40)
    if value['family'] == 'ticket' and value['quantities']:
        field.fail('T&M quantities belong to its documentary lines.', 'quantities')
    for quantity in value['quantities']:
        field.quantity_definition(quantity)
    if len({row['original_event_id'] for row in value['quantities']}) != len(value['quantities']):
        field.fail('Choose each original quantity capture once.', 'quantities')
    if value['action'] == 'revise':
        # Native FLD01 immutable IDs keep their established UUID syntax. The
        # server verifies that these exact bases belong to the target record.
        field.identifier(value['record_id'], 'record_id')
        field.identifier(value['base_revision_id'], 'base_revision_id')
        checksum(value['expected_version'], 'expected_version')
        checksum(value['base_revision_digest'], 'base_revision_digest')
        field.text(value['amendment_reason'], 'amendment_reason', 2000, blank=True)
    return value


def envelope(value):
    """Validate the complete immutable capture envelope and return it unchanged."""
    json_input(value)
    closed(value, ENVELOPE_FIELDS)
    if value['schema'] != SCHEMA:
        fail('Use the supported offline field capture schema.', 'schema')
    identifier(value['device_id'], 'device_id')
    identifier(value['capture_id'], 'capture_id')
    scope(value['company'], value['project'])
    field.text(value['actor_person'], 'actor_person', 140)
    field.text(value['actor_user'], 'actor_user', 140)
    timestamp(value['captured_at'], 'captured_at')
    command(value['command'])
    return value

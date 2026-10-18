"""Actual privacy admission with explicit native registration metadata doubles.

The three production functions are compiled unchanged from their AST. Only their
native metadata and current-duty dependencies are supplied here; no framework,
service, provenance, document context or authorization function is replaced.
An empty table models ordinary legacy fixtures. Restricted duty is denied until
the fixture explicitly grants an exact user, Person, Company and Project tuple.
"""
import ast
from contextlib import contextmanager
from copy import deepcopy
import importlib
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

from cipher_aec.api.contracts import canonical_json, digest
from cipher_aec.api.errors import DomainError


class NativeRow(dict):
    def __getattr__(self, key):
        try:return self[key]
        except KeyError:raise AttributeError(key) from None


class NativePrivacyState:
    def __init__(self):
        self.installed = True
        self.registrations = {}
        self.revisions = {}
        self.bindings = {}
        self.grants = set()
        self.registration_reads = []
        self.document_reads = []
        self.locator_reads = []
        self.duty_reads = []

    def add_registration(self, value):
        value = deepcopy(value)
        native = {'name':value['id'], **{key:value[key] for key in ('company','project','document_id','author_person')},
            'record_digest':digest(value), 'data_json':canonical_json(value)}
        self.registrations[value['id']] = native
        return native

    def grant(self, actor, company, project):
        self.bindings[actor.user] = actor.person_id
        self.grants.add((actor.user, actor.person_id, company, project, 'safety.incident.read'))

    def require_project(self, company, project, *, ability, actor, lock=False):
        assert ability == 'safety.incident.read'
        self.duty_reads.append((company, project, ability, actor.user, actor.person_id, lock))
        key = (actor.user, actor.person_id, company, project, ability)
        if self.bindings.get(actor.user) != actor.person_id or key not in self.grants:
            raise DomainError('capability_denied', 'Current exact restricted-source duty is unavailable.', 403)
        return SimpleNamespace(company=company, name=project)

    def exists(self, doctype, name):
        assert (doctype, name) == ('DocType', self.privacy.DOCTYPE)
        return self.installed

    def sql(self, query, arguments, *, as_dict):
        prefix = 'SELECT name FROM `tab'+self.privacy.DOCTYPE+'` WHERE document_id=%s'
        assert query in (prefix, prefix+' FOR UPDATE') and as_dict is True and len(arguments) == 1
        self.registration_reads.append((arguments[0], query.endswith(' FOR UPDATE')))
        return [NativeRow(name=name) for name, value in self.registrations.items() if value['document_id'] == arguments[0]]

    def get_doc(self, doctype, name, *, for_update=False):
        assert doctype == self.privacy.DOCTYPE
        self.document_reads.append((name, for_update))
        return NativeRow(deepcopy(self.registrations[name]))

    def get_value(self, doctype, name, fields, *, as_dict):
        assert doctype == 'Cipher Document Revision' and fields == ['document','company','project','scope_type'] and as_dict is True
        self.locator_reads.append(name)
        value = self.revisions.get(name)
        return NativeRow(deepcopy(value)) if value is not None else None


def actual_privacy(state):
    path = Path(__file__).parents[1]/'quality_safety/privacy.py'
    tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
    names = {'validate_registration','registration','authorize_source'}
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    constants = [node for node in tree.body if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == 'DOCTYPE' for target in node.targets)]
    assert {node.name for node in functions} == names and len(functions) == 3 and len(constants) == 1
    module = ModuleType('cipher_aec.quality_safety.privacy')
    module.__file__ = str(path)
    module.__dict__.update(json=json, digest=digest, DomainError=DomainError,
        rules=importlib.import_module('cipher_aec.quality_safety.contracts'),
        frappe=SimpleNamespace(db=SimpleNamespace(exists=state.exists, sql=state.sql, get_value=state.get_value), get_doc=state.get_doc),
        require_project=state.require_project)
    exec(compile(ast.Module(body=[*constants, *functions], type_ignores=[]), str(path), 'exec'), module.__dict__)
    return module


@contextmanager
def incident_privacy_fixture():
    state = NativePrivacyState()
    state.privacy = actual_privacy(state)
    package = importlib.import_module('cipher_aec.quality_safety')
    with patch.dict(sys.modules, {'cipher_aec.quality_safety.privacy':state.privacy}), patch.object(package, 'privacy', state.privacy, create=True):
        yield state

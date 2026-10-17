"""Fixed dispatch/source admission; no native writes or deployed-site qualification."""
from contextlib import ExitStack
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from cipher_aec.api.errors import DomainError
from cipher_aec.awards import runtime_catalog as catalog


def controller(mro):
    parent = object
    for name in reversed(mro[:-1]):
        module, qualname = name.rsplit('.', 1)
        parent = type(qualname, (parent,), {'__module__': module})
    return parent


class AwardRuntimeCatalog(TestCase):
    def setUp(self):
        stack = ExitStack(); self.addCleanup(stack.close)
        self.directory = Path(stack.enter_context(TemporaryDirectory()))
        self.roots = {app: self.directory / app for app in catalog.EXPECTED_APPS}
        # Explicit incomplete-qualification fixture remains meaningful after a
        # later reviewed deployment fills the production source pins.
        self.original_pending = dict.fromkeys(catalog.CIPHER_SOURCE_SHA256)
        self.sources = {}
        for name in (*catalog.NATIVE_SOURCE_SHA256, *catalog.CIPHER_SOURCE_SHA256):
            app, relative = name.split('/', 1)
            path = self.roots[app] / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            data = ('test-only reviewed source: ' + name).encode()
            path.write_bytes(data)
            self.sources[name] = sha256(data).hexdigest()
        self.apps = list(catalog.EXPECTED_APPS); self.bench_apps = list(self.apps)
        self.hooks = {'doc_events': deepcopy(catalog.EXPECTED_EVENTS),
            'override_doctype_class': {}, 'extend_doctype_class': {},
            'sqlite_search': list(catalog.EXPECTED_SEARCH)}
        self.expanded = deepcopy(catalog.EXPECTED_EVENTS)
        self.controllers = {key: controller(value) for key, value in catalog.EXPECTED_MRO.items()}
        self.calls = []
        def hooks(name, default):
            self.calls.append(name); return self.hooks.get(name, default)
        fake = SimpleNamespace(get_hooks=hooks, get_doc_hooks=lambda: self.expanded,
            get_installed_apps=lambda **kw: self.bench_apps if kw.get('_ensure_on_bench') else self.apps)
        stack.enter_context(patch.object(catalog, 'frappe', fake))
        stack.enter_context(patch.object(catalog, '_source_roots', return_value=self.roots))
        stack.enter_context(patch.object(catalog, 'NATIVE_SOURCE_SHA256', {k:self.sources[k] for k in catalog.NATIVE_SOURCE_SHA256}))
        stack.enter_context(patch.object(catalog, 'CIPHER_SOURCE_SHA256', {k:self.sources[k] for k in catalog.CIPHER_SOURCE_SHA256}))
        stack.enter_context(patch('frappe.model.base_document.get_controller', side_effect=lambda name: self.controllers[name]))

    def denied(self):
        with self.assertRaises(DomainError) as error:
            catalog.require_catalog()
        self.assertEqual(error.exception.code, 'award_native_catalog_unqualified')
        self.assertEqual(error.exception.status, 503)

    def test_exact_reviewed_catalog_returns_only_static_policy(self):
        self.assertEqual(catalog.require_catalog(), {'catalog':catalog.CATALOG})
        self.assertIn('doc_events', self.calls)

    def test_unfinished_cipher_bodies_refuse_before_hook_import_or_lookup(self):
        with patch.object(catalog, 'CIPHER_SOURCE_SHA256', self.original_pending):
            self.denied()
        self.assertEqual(self.calls, [])
        self.assertTrue(all(value is None for value in self.original_pending.values()))

    def test_installed_and_on_bench_order_are_each_exact(self):
        for name in ('apps', 'bench_apps'):
            original = getattr(self, name)
            for changed in (list(reversed(original)), original+['unreviewed'], original[:-1]):
                setattr(self, name, changed)
                with self.subTest(name=name, changed=changed): self.denied()
            setattr(self, name, original)

    def test_extra_changed_and_reordered_wildcard_hook_refused(self):
        original = self.hooks['doc_events']['*']['on_update']
        for changed in (original+['unknown.callback'], ['changed.callback', *original[1:]], list(reversed(original))):
            self.hooks['doc_events']['*']['on_update'] = changed
            with self.subTest(changed=changed): self.denied()
        self.hooks['doc_events']['*']['on_update'] = original

    def test_added_target_event_refused(self):
        self.hooks['doc_events']['Project']['before_insert'] = ['unknown.callback']
        self.denied()

    def test_stale_effective_expanded_hook_refused_even_when_raw_matches(self):
        self.expanded['Sales Order']['validate'] += ['stale.callback']
        self.denied()

    def test_target_tuple_hook_expansion_cannot_hide_added_handler(self):
        self.hooks['doc_events'][('Unrelated', 'Sales Order')] = {'validate':['extra.callback']}
        self.denied()

    def test_target_override_mixin_or_wildcard_override_refused(self):
        for name in ('override_doctype_class', 'extend_doctype_class'):
            for target in ('Project', 'Sales Order', '*'):
                self.hooks[name][target] = ['unknown.Controller']
                with self.subTest(name=name,target=target): self.denied()
                self.hooks[name].clear()

    def test_actual_controller_or_mro_drift_refused(self):
        original = self.controllers['Project']
        self.controllers['Project'] = type('MixinProject', (original,), {'__module__':'unknown'})
        self.denied()
        self.controllers['Project'] = controller(['unknown.Project', *catalog.EXPECTED_MRO['Project'][1:]])
        self.denied()

    def test_search_dispatch_drift_refused(self):
        self.hooks['sqlite_search'].append('unknown.Search')
        self.denied()

    def test_unrelated_doctype_hooks_and_extensions_remain_allowed(self):
        self.hooks['doc_events']['Task'] = {'validate':['other.task.callback']}
        self.expanded['Task'] = self.hooks['doc_events']['Task']
        self.hooks['extend_doctype_class']['Task'] = ['other.task.Mixin']
        self.assertEqual(catalog.require_catalog(), {'catalog':catalog.CATALOG})

    def test_changed_missing_and_malformed_fixed_source_refused(self):
        name = 'frappe/model/document.py'; app, relative = name.split('/',1)
        path = self.roots[app]/relative
        path.write_bytes(b'drift'); self.denied()
        path.unlink(); self.denied()
        catalog.NATIVE_SOURCE_SHA256[name] = 'bad'; self.denied()

    def test_source_symlink_escape_refused_even_with_expected_bytes(self):
        name = 'frappe/model/document.py'; app, relative = name.split('/',1)
        path = self.roots[app]/relative
        outside = self.directory/'outside.py'; outside.write_bytes(path.read_bytes())
        path.unlink(); path.symlink_to(outside)
        self.denied()

    def test_malformed_native_catalog_fails_closed(self):
        for field, value in (('doc_events', []), ('override_doctype_class', []), ('sqlite_search', 'unknown')):
            old=self.hooks[field]; self.hooks[field]=value
            try:
                with self.subTest(field=field): self.denied()
            finally:self.hooks[field]=old

    def test_all_actual_cipher_writes_have_fixed_event_and_controller_coverage(self):
        from cipher_aec.awards import runtime_profile
        self.assertEqual(catalog.TARGETS,runtime_profile.TARGETS)
        for target in runtime_profile.CIPHER_TARGETS:
            self.assertEqual(catalog.EXPECTED_EVENTS[target],{})
            self.hooks['doc_events'][target]={'before_insert':['extra.callback']}
            try:
                with self.subTest(target=target,kind='hook'):self.denied()
            finally:self.hooks['doc_events'][target]={}
            original=self.controllers[target]
            self.controllers[target]=type('Changed',(original,),{'__module__':'unknown'})
            try:
                with self.subTest(target=target,kind='controller'):self.denied()
            finally:self.controllers[target]=original

    def test_all_fixed_cipher_controller_and_metadata_files_require_reviewed_pin(self):
        for target in catalog.TARGETS[2:]:
            cls=catalog.EXPECTED_MRO[target][0]
            controller_path=cls.rsplit('.',1)[0].replace('.','/')+'.py'
            metadata_path=controller_path.removesuffix('.py')+'.json'
            self.assertIn(controller_path,self.original_pending)
            self.assertIn(metadata_path,self.original_pending)
            self.assertIsNone(self.original_pending[controller_path])
            self.assertIsNone(self.original_pending[metadata_path])

    def test_literal_approval_and_callback_code_dependencies_require_reviewed_pins(self):
        for name in ('cipher_aec/awards/governance.py', 'cipher_aec/documents/provenance.py',
                'cipher_aec/governance/domain_approvals.py'):
            self.assertIn(name, self.original_pending)
            self.assertIsNone(self.original_pending[name])

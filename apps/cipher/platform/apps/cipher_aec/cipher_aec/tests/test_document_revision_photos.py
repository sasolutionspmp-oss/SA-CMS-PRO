"""Host regression for the actual revision controller; no native-site proof.

Frappe's Document/DB/File surfaces are bounded local doubles. The production
controller, trusted-write context, source admission/extraction, document service,
and FrappeFileStorage byte verification all execute without patched guards.
"""
from contextlib import ExitStack
import base64
from datetime import date
import importlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from PIL import Image

import cipher_aec
from cipher_aec.api.errors import DomainError
from cipher_aec.documents.core import DocumentService
from cipher_aec.documents.extraction import ArtifactError, digest, extract_source
from cipher_aec.documents.storage import FrappeFileStorage


class NativeValidationError(ValueError):
    pass


class NativeRow(dict):
    def __getattr__(self, key):
        return self.get(key)

    def __setattr__(self, key, value):
        self[key] = value

    def as_dict(self):
        return dict(self)

    def is_new(self):
        return self.get('_new', True)


class NativeMetadata:
    """Only the metadata operations used by DocumentService in this regression."""
    def __init__(self, validate):
        self.docs, self.revs, self.validate = {}, {}, validate

    def create_document(self, row):
        self.docs[row['name']] = dict(row)

    def create_revision(self, row):
        self.validate(row)
        self.revs[row['name']] = dict(row)

    def advance_document(self, name, revision_id, number):
        self.docs[name].update(current_revision=revision_id, revision_number=number)

    def document(self, name, lock=False):
        return self.docs[name]

    def revision_scope(self, name):
        return self.revs[name]

    def revision_locator(self, name):
        return self.revs[name]

    def revision(self, name, lock=False):
        return self.revs[name]


class DocumentRevisionPhotoControllerTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.directory = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.files = {}
        self.allowed = True
        self.frappe = types.ModuleType('frappe')
        self.frappe.conf = {'cipher_site_mode': 'synthetic', 'cipher_allow_unscanned_documents': 1}
        self.frappe.throw = self.throw
        self.frappe.get_doc = self.get_doc
        self.frappe.db = types.SimpleNamespace(get_value=self.get_value, has_column=lambda *args: True)
        utils = types.ModuleType('frappe.utils')
        utils.getdate, utils.nowdate = lambda *args: date(2026, 10, 17), lambda: '2026-10-17'
        model = types.ModuleType('frappe.model')
        document = types.ModuleType('frappe.model.document')
        document.Document = NativeRow
        self.stack.enter_context(patch.dict(sys.modules, {
            'frappe': self.frappe, 'frappe.utils': utils,
            'frappe.model': model, 'frappe.model.document': document,
        }))
        # Import the real context against the bounded Frappe surfaces, even if a
        # different host test had previously installed its own context double.
        governance = importlib.import_module('cipher_aec.governance')
        self.stack.enter_context(patch.object(governance, 'context', None, create=True))
        sys.modules.pop('cipher_aec.governance.context', None)
        self.context = importlib.import_module('cipher_aec.governance.context')
        default = Path(cipher_aec.__file__).parent / 'cipher_documents/doctype/cipher_document_revision/cipher_document_revision.py'
        path = Path(os.environ.get('CIPHER_REVISION_CONTROLLER_PATH', default))
        spec = importlib.util.spec_from_file_location('_revision_photo_controller_under_test', path)
        self.controller = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.controller)
        self.repo = NativeMetadata(self.validate)
        self.storage = FrappeFileStorage()
        self.service = DocumentService(self.repo, self.storage, self.authorize, allow_unscanned=True)

    @staticmethod
    def throw(message):
        raise NativeValidationError(message)

    def authorize(self, company, project, ability):
        if not self.allowed or company != 'Synthetic Company' or project != 'PROJECT-A':
            raise PermissionError('Exact current source duty denied')

    def get_value(self, doctype, name, fields, as_dict=False):
        rows = self.repo.docs if doctype == 'Cipher Document' else self.files if doctype == 'File' else {}
        row = rows.get(name)
        return NativeRow({key: row.get(key) for key in fields}) if row is not None else None

    def get_doc(self, doctype, name=None):
        if isinstance(doctype, dict):
            values = dict(doctype)
            self.assertEqual(values.pop('doctype'), 'File')
            name = 'FILE-' + str(len(self.files) + 1)
            path = self.directory / name
            row = NativeRow(values, name=name)
            def insert(**kwargs):
                path.write_bytes(values['content'])
                self.files[name] = row
                return row
            row.insert = insert
            row.validate_file_path = lambda: None
            row.validate_file_url = lambda: None
            row.get_full_path = lambda: str(path)
            return row
        self.assertEqual(doctype, 'File')
        return self.files[name]

    def validate(self, row):
        revision = self.controller.CipherDocumentRevision(doctype='Cipher Document Revision', **row)
        with self.context.trusted_write():
            revision.validate()

    def photo(self, kind='PNG'):
        output = io.BytesIO()
        Image.new('RGB', (2, 2), (41, 92, 137)).save(output, format=kind)
        return output.getvalue()

    def upload(self, content=None, filename='photo.png'):
        content = self.photo() if content is None else content
        return self.service.upload(company='Synthetic Company', project='PROJECT-A', title='Retained source image',
            filename=filename, content=content, byte_length=len(content), sha256=digest(content))

    def row(self, content=None, filename='photo.png', mime='image/png', **changes):
        content = self.photo() if content is None else content
        extracted = extract_source(content, mime)
        parent = dict(name='DOC-fixture', company='Synthetic Company', project='PROJECT-A',
            scope_type='Project', revision_number=0, current_revision=None)
        self.repo.create_document(parent)
        reference = self.storage.put('REV-fixture', filename, content)
        row = dict(name='REV-fixture', document=parent['name'], company=parent['company'], project=parent['project'],
            scope_type='Project', revision_number=1, filename=filename, mime_type=mime, byte_length=len(content),
            sha256=digest(content), storage_reference=reference, scan_status='not_scanned', retrieval_status='available',
            extraction_status=extracted.status, extractor_version=extracted.extractor_version,
            pages_json=json.dumps(list(extracted.pages)), page_count=len(extracted.pages), extraction_warning=extracted.warning)
        row.update(changes)
        return row

    def test_real_png_and_jpeg_pass_actual_controller_and_retain_exact_bytes(self):
        native_png = base64.b64decode(
            'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII='
        )
        for content, filename, mime in ((native_png, 'field-observation.png', 'image/png'),
                (self.photo(), 'photo.png', 'image/png'), (self.photo('JPEG'), 'photo.jpeg', 'image/jpeg')):
            with self.subTest(mime=mime):
                saved = self.upload(content, filename)
                revision_id = saved['revision']['id']
                stored = self.repo.revs[revision_id]
                self.assertEqual(stored['mime_type'], mime)
                self.assertEqual(stored['sha256'], digest(content))
                self.assertEqual(stored['byte_length'], len(content))
                self.assertEqual(stored['scan_status'], 'not_scanned')
                self.assertEqual(stored['extraction_status'], 'image_text_unavailable')
                self.assertEqual(stored['extractor_version'], 'cipher-safe-image-v1')
                self.assertEqual(json.loads(stored['pages_json']), [''])
                self.assertEqual(stored['page_count'], 1)
                self.assertEqual(self.service.download('Synthetic Company', revision_id)[1], content)
                source = self.service.source_reference('Synthetic Company', 'PROJECT-A', revision_id, 1)
                self.assertEqual(source['content'], content)
                with self.assertRaisesRegex(ArtifactError, 'no available extracted text'):
                    self.service.citation('Synthetic Company', revision_id, 1)

    def test_image_cannot_claim_text_or_ocr_or_multiple_pages(self):
        row = self.row()
        for changes in ({'extraction_status': 'ready'}, {'extraction_status': 'ocr_unavailable'},
                {'pages_json': '["invented OCR"]'}, {'pages_json': '["", ""]', 'page_count': 2},
                {'pages_json': '[]', 'page_count': 0}, {'extractor_version': 'cipher-safe-text-v1'}):
            with self.subTest(changes=changes), self.assertRaises(NativeValidationError):
                self.validate({**row, **changes})

    def test_image_status_is_not_valid_for_text_or_pdf(self):
        for mime, filename, content in (('text/plain', 'source.txt', b'Actual text'),
                ('application/pdf', 'source.pdf', b'%PDF-1.7\nfixture signature only')):
            row = self.row(content, filename, mime, extraction_status='image_text_unavailable',
                extractor_version='cipher-safe-image-v1', pages_json='[""]', page_count=1)
            with self.subTest(mime=mime), self.assertRaises(NativeValidationError):
                self.validate(row)

    def test_real_bytes_must_match_filename_mime_hash_and_size(self):
        row = self.row()
        for changes in ({'filename': 'photo.jpg'}, {'filename': '../photo.png'}, {'mime_type': 'image/jpeg'},
                {'sha256': '0' * 64}, {'byte_length': row['byte_length'] + 1}, {'mime_type': 'image/svg+xml'}):
            with self.subTest(changes=changes), self.assertRaises((NativeValidationError, ArtifactError)):
                self.validate({**row, **changes})

    def test_truncated_image_with_matching_hash_is_rejected(self):
        row = self.row(self.photo()[:-1])
        with self.assertRaises(ArtifactError):
            self.validate(row)

    def test_private_file_attachment_and_original_bytes_remain_required(self):
        row = self.row()
        file = self.files[row['storage_reference']]
        for key, value in (('is_private', 0), ('attached_to_doctype', 'Other'), ('attached_to_name', 'REV-other')):
            old = file[key]
            file[key] = value
            with self.subTest(key=key), self.assertRaises(NativeValidationError):
                self.validate(row)
            file[key] = old
        path = Path(file.get_full_path())
        path.write_bytes(b'altered original')
        with self.assertRaises(ArtifactError):
            self.validate(row)
        path.unlink()
        with self.assertRaises(ArtifactError):
            self.validate(row)

    def test_unscanned_image_availability_requires_exact_synthetic_configuration(self):
        row = self.row()
        for config in ({'cipher_site_mode': 'synthetic', 'cipher_allow_unscanned_documents': 0},
                {'cipher_site_mode': 'production', 'cipher_allow_unscanned_documents': 1}, {}):
            self.frappe.conf = config
            with self.subTest(config=config), self.assertRaises(NativeValidationError):
                self.validate(row)
            self.validate({**row, 'retrieval_status': 'quarantined'})
        self.validate({**row, 'scan_status': 'clean'})

    def test_scan_states_are_not_promoted_to_clean_or_available(self):
        row = self.row()
        self.validate({**row, 'scan_status': 'unavailable', 'retrieval_status': 'quarantined'})
        for scan in ('infected', 'unavailable'):
            with self.subTest(scan=scan), self.assertRaises(NativeValidationError):
                self.validate({**row, 'scan_status': scan})
        infected = {**row, 'scan_status': 'infected', 'retrieval_status': 'quarantined',
            'extraction_status': 'blocked', 'extractor_version': 'none', 'pages_json': '[]', 'page_count': 0}
        self.validate(infected)
        with self.assertRaises(NativeValidationError):
            self.validate({**infected, 'scan_status': 'not_scanned'})

    def test_status_and_numeric_types_are_closed(self):
        row = self.row()
        for changes in ({'scan_status': 'skipped'}, {'retrieval_status': 'public'}, {'extraction_status': 'success'},
                {'scan_status': []}, {'retrieval_status': {}}, {'extraction_status': None}, {'mime_type': []},
                {'page_count': True}, {'page_count': 1.0}, {'page_count': '1'}, {'revision_number': True},
                {'byte_length': True}, {'byte_length': float(row['byte_length'])}, {'sha256': 7}):
            with self.subTest(changes=changes), self.assertRaises(NativeValidationError):
                self.validate({**row, **changes})

    def test_snapshot_json_bounds_and_closed_page_types_remain_enforced(self):
        row = self.row()
        for changes in ({'pages_json': '{}'}, {'pages_json': '[null]'}, {'pages_json': '[42]'},
                {'pages_json': '[true]'}, {'pages_json': '['}, {'pages_json': '[""]', 'page_count': -1},
                {'pages_json': json.dumps(['x' * 20001])}):
            with self.subTest(changes=changes), self.assertRaises(NativeValidationError):
                self.validate({**row, **changes})

    def test_non_image_extraction_states_keep_existing_truthful_shapes(self):
        row = self.row(b'Actual text', 'source.txt', 'text/plain')
        self.validate(row)
        for changes in ({'extraction_status': 'ocr_unavailable'}, {'extractor_version': 'cipher-safe-image-v1'},
                {'extraction_status': 'ready', 'pages_json': '[]', 'page_count': 0},
                {'extraction_status': 'limits_exceeded'}, {'extraction_status': 'blocked'}):
            with self.subTest(changes=changes), self.assertRaises(NativeValidationError):
                self.validate({**row, **changes})
        self.validate({**row, 'extraction_status': 'limits_exceeded', 'pages_json': '[]', 'page_count': 0,
            'retrieval_status': 'quarantined'})
        pdf = self.row(b'%PDF-1.7\nfixture signature only', 'source.pdf', 'application/pdf')
        self.validate({**pdf, 'extraction_status': 'ready', 'pages_json': '["Actual embedded text"]', 'page_count': 1})
        self.validate({**pdf, 'extraction_status': 'ocr_unavailable', 'pages_json': '[""]', 'page_count': 1})
        for changes in ({'extraction_status': 'ready', 'pages_json': '[""]', 'page_count': 1},
                {'extraction_status': 'ocr_unavailable', 'pages_json': '["invented text"]', 'page_count': 1}):
            with self.subTest(changes=changes), self.assertRaises(NativeValidationError):
                self.validate({**pdf, **changes})

    def test_scope_sequence_immutability_and_trusted_write_are_still_enforced(self):
        row = self.row()
        revision = self.controller.CipherDocumentRevision(doctype='Cipher Document Revision', **row)
        with self.assertRaises(DomainError) as denied:
            revision.validate()
        self.assertEqual(denied.exception.code, 'governed_write_required')
        for changes in ({'project': 'PROJECT-B'}, {'revision_number': 2}, {'_new': False}):
            with self.subTest(changes=changes), self.assertRaises(NativeValidationError):
                self.validate({**row, **changes})

    def test_current_source_duty_denial_precedes_upload_decode(self):
        self.allowed = False
        with patch('cipher_aec.documents.extraction.subprocess.run') as decoder:
            with self.assertRaises(PermissionError):
                self.upload()
            decoder.assert_not_called()
        self.assertEqual(self.files, {})
        self.assertEqual(self.repo.docs, {})


if __name__ == '__main__':
    unittest.main()

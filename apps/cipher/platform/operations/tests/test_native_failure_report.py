"""Bounded native failure identity and frames, without raw diagnostic values."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location('cipher_native_reporter', Path(__file__).resolve().parents[1] / 'validate_new_stack.py')
reporter = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(reporter)

class NativeFailureReportTests(unittest.TestCase):
    def test_native_failure_reports_test_type_and_source_location_without_values(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'native.log'
            path.write_text('ERROR: test_exact_receipt (cipher_aec.tests.test_engineering_native.TestEngineeringNative.test_exact_receipt)\n'
                'Traceback (most recent call last):\n'
                '  File "/private/PATH_SECRET/apps/cipher_aec/cipher_aec/engineering/service.py", line 151, in create_response\n'
                '    private_value = "VALUE_SECRET"\n'
                'cipher_aec.api.errors.DomainError: password=PASSWORD_SECRET sid=SID_SECRET\n')
            result = reporter.native_failure_summary(path)
            self.assertEqual(result['status'], 'available')
            failure = result['failures'][0]
            self.assertEqual(failure['test'], 'test_exact_receipt')
            self.assertEqual(failure['exception_type'], 'cipher_aec.api.errors.DomainError')
            self.assertEqual(failure['frames'][-1], {'file': 'cipher_aec/engineering/service.py', 'line': 151, 'function': 'create_response'})
            serialized = json.dumps(result)
            for value in ['PATH_SECRET', 'VALUE_SECRET', 'PASSWORD_SECRET', 'SID_SECRET']:
                self.assertNotIn(value, serialized)
    def test_import_failure_has_a_bounded_category_without_private_message(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'native.log';path.write_text('ImportError: PRIVATE_IMPORT_MESSAGE\n')
            result = reporter.native_failure_summary(path)
            self.assertEqual(result['failures'][0]['exception_type'], 'ImportError')
            self.assertNotIn('PRIVATE_IMPORT_MESSAGE', json.dumps(result))
    def test_missing_and_oversized_log_preserve_original_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'missing.log'
            self.assertEqual(reporter.native_failure_summary(path)['status'], 'missing')
            with path.open('wb') as stream:stream.truncate(8 * 1024 * 1024 + 1)
            self.assertEqual(reporter.native_failure_summary(path)['status'], 'oversized')

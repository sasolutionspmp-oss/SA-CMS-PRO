"""Real bounded subprocess failures report status without echoing private output."""
from contextlib import redirect_stdout
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest

MODULE = Path(__file__).resolve().parents[1] / 'validate_new_stack.py'
SPEC = importlib.util.spec_from_file_location('cipher_stage_reporter', MODULE)
reporter = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(reporter)


class StageFailureMetadataTests(unittest.TestCase):
    def run_failure(self, code, budget=3):
        with tempfile.TemporaryDirectory() as directory:
            runner = reporter.Runner.__new__(reporter.Runner)
            runner.args = SimpleNamespace(overall_timeout=budget, stage_timeout=900)
            runner.work = Path(directory)
            runner.started = time.monotonic()
            runner.results = []
            output = io.StringIO()
            with redirect_stdout(output), self.assertRaises(reporter.ValidationFailure):
                runner.stage('frontend-browser-contracts', [sys.executable, '-c', code])
            text = output.getvalue()
            self.assertNotIn('private-fixture-marker', text)
            line = next(line for line in text.splitlines() if line.startswith('PROCESS_FAILURE '))
            diagnostic = json.loads(line.removeprefix('PROCESS_FAILURE '))
            self.assertEqual(set(diagnostic), {'name', 'exit_code', 'duration_seconds', 'timed_out'})
            self.assertEqual(diagnostic['name'], 'frontend-browser-contracts')
            self.assertEqual(runner.results[-1]['status'], 'failed')
            self.assertIn('private-fixture-marker', Path(runner.results[-1]['private_log']).read_text())
            return diagnostic

    def test_nonzero_exit_reports_code_without_private_output(self):
        result = self.run_failure("print('private-fixture-marker', flush=True); raise SystemExit(7)")
        self.assertEqual(result['exit_code'], 7)
        self.assertFalse(result['timed_out'])

    def test_timeout_retains_explicit_status_after_terminating_its_own_group(self):
        result = self.run_failure("import time; print('private-fixture-marker', flush=True); time.sleep(60)", 1)
        self.assertTrue(result['timed_out'])
        self.assertLess(result['exit_code'], 0)
        self.assertLess(result['duration_seconds'], 3)

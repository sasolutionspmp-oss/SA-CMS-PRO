"""Synthetic Playwright-report qualification; no runtime, browser or credentials."""
from contextlib import redirect_stdout
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

MODULE = Path(__file__).resolve().parents[1] / "validate_new_stack.py"
SPEC = importlib.util.spec_from_file_location("cipher_validation_reporter", MODULE)
reporter = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(reporter)


def failed_spec(title="phone prepared PDF keeps functional zoom", status="unexpected"):
    return {"title": title, "file": "proposal-output.spec.ts", "line": 48, "column": 1, "ok": False,
            "tests": [{"status": status, "expectedStatus": "passed", "results": [
                {"status": "timedOut", "duration": 45000, "retry": 0,
                 "errors": [{"message": "\x1b[31mError: expect(locator).toBeVisible() failed\x1b[39m\nLocator: getByRole('option')\nExpected: visible\nReceived: hidden\nCall log:\n  - private raw text",
                             "location": {"file": "/home/runner/work/private/secret-checkout/tests/proposal-output.spec.ts", "line": 49, "column": 17},
                             "snippet": "private source snippet", "stack": "private stack"}],
                 "stdout": ["private stdout"], "stderr": ["private stderr"],
                 "attachments": [{"name": "trace", "path": "/private/trace.zip"}]}]}]}


def report(specs):
    return {"config": {"webServer": {"url": "https://private.invalid"}},
            "suites": [{"title": "outer", "suites": [{"title": "file suite", "specs": specs}]}],
            "stats": {"expected": 99, "unexpected": 1, "flaky": 0, "skipped": 0, "duration": 300663}}


class BrowserFailureReportTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "browser-contracts.json"

    def write(self, value):
        self.path.write_text(json.dumps(value))
        return reporter.browser_failure_summary(self.path)

    def test_real_nested_report_preserves_failing_test_and_assertion_location(self):
        passing = {"title": "passing case", "tests": [{"status": "expected", "results": [{"status": "passed"}]}]}
        result = self.write(report([passing, failed_spec()]))
        self.assertEqual(result["report_status"], "available")
        self.assertEqual(result["stats"]["unexpected"], 1)
        self.assertEqual(len(result["failures"]), 1)
        failure = result["failures"][0]
        self.assertEqual((failure["file"], failure["line"], failure["column"]), ("proposal-output.spec.ts", 48, 1))
        self.assertEqual(failure["assertion_location"], {"file": "proposal-output.spec.ts", "line": 49, "column": 17})
        self.assertEqual(failure["status"], "unexpected")
        self.assertEqual(failure["result_status"], "timedOut")
        self.assertEqual(failure["assertion"], "expect(locator).toBeVisible failed; expected: visible; received: hidden")
        self.assertRegex(result["report_sha256"], "^[a-f0-9]{64}$")

    def test_raw_values_urls_credentials_and_attachments_never_leave_private_report(self):
        spec = failed_spec('case https://secret.invalid/signed?token=URL_SECRET password="PASSWORD_SECRET value" token=TOKEN_SECRET')
        error = spec["tests"][0]["results"][0]["errors"][0]
        error["message"] += '\nExpected: "EXPECTED_SECRET"\nReceived: "RECEIVED_SECRET"\nExpected: 976104\nReceived: 123456\nAuthorization: Bearer BEARER_SECRET\nCookie: COOKIE_SECRET\nhttps://secret.invalid/URL_SECRET'
        spec["tests"][0]["results"][0]["stdout"] = ["STDOUT_SECRET"]
        error["snippet"] = "SNIPPET_SECRET"
        error["stack"] = "STACK_SECRET"
        result = self.write(report([spec]))
        rendered = json.dumps(result)
        for forbidden in ["PASSWORD_SECRET", "TOKEN_SECRET", "URL_SECRET", "EXPECTED_SECRET", "RECEIVED_SECRET", "976104", "123456", "BEARER_SECRET", "COOKIE_SECRET", "STDOUT_SECRET", "SNIPPET_SECRET", "STACK_SECRET", "https://", "attachments", "secret-checkout"]:
            self.assertNotIn(forbidden, rendered)
        self.assertIn("toBeVisible", rendered)
        for title in ['Authorization: Bearer TITLE_BEARER_SECRET', 'Cookie: first=TITLE_COOKIE_SECRET; next=ANOTHER_SECRET', '"password": "MULTI_WORD_SECRET value"']:
            self.assertEqual(self.write(report([failed_spec(title)]))["failures"][0]["title"], "Redacted test title (sensitive assignment)")
        output = json.dumps(self.write(report([failed_spec(r"case /tmp/ABSOLUTE_SECRET wss://private.invalid/SOCKET_SECRET C:\Users\WINDOWS_SECRET")])))
        for private in ["ABSOLUTE_SECRET", "SOCKET_SECRET", "WINDOWS_SECRET", "/tmp/", "wss://", "C:\\Users"]:
            self.assertNotIn(private, output)

    def test_timeout_flaky_and_skip_are_diagnostics_without_retries_or_masking(self):
        flaky = failed_spec(status="flaky")
        flaky["tests"][0]["results"][0]["errors"] = [{"message": "Test timeout of 45000ms exceeded.\nprivate details"}]
        flaky["tests"][0]["results"].append({"status": "passed", "retry": 1})
        skipped = failed_spec("skipped case", "skipped")
        skipped["tests"][0]["results"] = []
        result = self.write(report([flaky, skipped]))
        self.assertEqual([row["status"] for row in result["failures"]], ["flaky", "skipped"])
        self.assertEqual(result["failures"][0]["assertion"], "Test timeout of 45000ms exceeded")
        self.assertEqual(result["failures"][1]["result_status"], "skipped")

    def test_missing_malformed_wrong_root_and_oversized_reports_are_bounded(self):
        self.assertEqual(reporter.browser_failure_summary(self.path)["report_status"], "missing")
        self.path.write_bytes(b'{"suites":')
        self.assertEqual(reporter.browser_failure_summary(self.path)["report_status"], "malformed")
        self.assertEqual(self.write([])["report_status"], "malformed")
        self.path.write_bytes(b"x" * (8 * 1024 * 1024 + 1))
        self.assertEqual(reporter.browser_failure_summary(self.path)["report_status"], "oversized")

    def test_failure_inventory_and_title_are_bounded(self):
        result = self.write(report([failed_spec("x" * 2000) for _ in range(25)]))
        self.assertEqual(len(result["failures"]), 20)
        self.assertEqual(result["failures_omitted"], 5)
        self.assertTrue(all(len(row["title"]) <= 240 for row in result["failures"]))

    def test_every_traversal_limit_is_explicit_and_unobserved_cases_are_not_counted(self):
        deep = {"specs": [failed_spec()]}
        for _ in range(18):
            deep = {"suites": [deep]}
        specimens = [
            {"suites": [deep]},
            {"suites": [{}] * 1001},
            {"suites": [{"specs": [{}] * 1000 + [failed_spec()]}]},
            {"suites": [{"specs": [{"tests": [{}] * 100 + [{"status": "unexpected"}]}]}]},
        ]
        for specimen in specimens:
            with self.subTest(shape=specimen.keys()):
                result = self.write(specimen)
                self.assertTrue(result["traversal_limited"])
                self.assertEqual(result["failures_omitted"], 0)

    def test_report_level_errors_are_bounded_normalized_and_have_no_raw_values(self):
        value = {"suites": [], "stats": {"expected": 0, "unexpected": 0}, "errors": [
            {"message": "Test timeout of 45000ms exceeded. PRIVATE_LAUNCH_SECRET https://secret.invalid", "location": {"file": "/private/global-setup.ts", "line": 5}},
            *[{"message": "PRIVATE_UNRECOGNIZED_SECRET"} for _ in range(6)],
        ]}
        result = self.write(value)
        self.assertEqual(result["failures"], [])
        self.assertEqual(result["report_error_count"], 7)
        self.assertEqual(len(result["report_errors"]), 5)
        self.assertEqual(result["report_errors_omitted"], 2)
        self.assertEqual(result["report_errors"][0], {"assertion": "Test timeout of 45000ms exceeded", "file": "global-setup.ts", "line": 5})
        self.assertNotIn("PRIVATE_", json.dumps(result))

    def test_unrecognized_error_text_and_malformed_shapes_are_not_echoed(self):
        spec = failed_spec()
        spec["file"] = "https://private.invalid/PRIVATE_FILE"
        spec["tests"][0]["results"][0]["errors"] = [{"message": "PRIVATE_UNRECOGNIZED_SECRET"}]
        value = report([None, spec, {"tests": "bad"}])
        value["stats"]["expected"] = "PRIVATE_STAT_SECRET"
        value["stats"]["duration"] = float("inf")
        result = self.write(value)
        self.assertEqual(result["failures"][0]["file"], "unavailable")
        self.assertEqual(result["failures"][0]["assertion"], "Browser test failed; details retained privately.")
        self.assertNotIn("PRIVATE_", json.dumps(result))
        self.assertNotIn("duration", result["stats"])

    def runner(self):
        runner = reporter.Runner.__new__(reporter.Runner)
        runner.results = [{"name": "frontend-browser-contracts", "status": "failed", "exit_code": 1}]
        return runner

    def test_failed_stage_retains_safe_report_and_original_failure_without_rerun(self):
        self.write(report([failed_spec()]))
        runner = self.runner()
        original = reporter.ValidationFailure("frontend-browser-contracts failed; inspect its private log")
        runner.stage = Mock(side_effect=original)
        stdout = io.StringIO()
        with redirect_stdout(stdout), self.assertRaises(reporter.ValidationFailure) as raised:
            runner.browser_contracts(Path(self.directory.name), {"CI": "1"}, self.path)
        self.assertIs(raised.exception, original)
        self.assertEqual(runner.stage.call_count, 1)
        self.assertEqual(runner.results[0]["status"], "failed")
        self.assertEqual(runner.results[0]["exit_code"], 1)
        self.assertEqual(runner.results[0]["browser_failure"]["failures"][0]["line"], 48)
        self.assertIn("BROWSER_FAILURE", stdout.getvalue())
        self.assertNotIn("private raw text", stdout.getvalue())

    def test_missing_or_broken_parser_never_masks_original_failure(self):
        for parser in [None, RuntimeError("PRIVATE_PARSER_SECRET")]:
            runner = self.runner()
            original = reporter.ValidationFailure("original stage failure")
            runner.stage = Mock(side_effect=original)
            stdout = io.StringIO()
            with patch.object(reporter, "browser_failure_summary", side_effect=parser) if parser else patch.object(reporter, "sha", wraps=reporter.sha):
                with redirect_stdout(stdout), self.assertRaises(reporter.ValidationFailure) as raised:
                    runner.browser_contracts(Path(self.directory.name), {}, self.path)
            self.assertIs(raised.exception, original)
            self.assertEqual(runner.stage.call_count, 1)
            self.assertNotIn("PRIVATE_PARSER_SECRET", stdout.getvalue())
            self.assertEqual(runner.results[0]["browser_failure"]["report_status"], "unreadable" if parser else "missing")

    def test_passing_stage_keeps_existing_stats_and_gate(self):
        self.path.write_text(json.dumps({"stats": {"expected": 100, "unexpected": 0, "flaky": 0, "skipped": 0}}))
        runner = self.runner()
        runner.results[0]["status"] = "passed"
        runner.stage = Mock(return_value="")
        runner.browser_contracts(Path(self.directory.name), {}, self.path)
        self.assertEqual(runner.results[0]["test_summary"]["expected"], 100)
        self.assertNotIn("browser_failure", runner.results[0])
        self.path.write_text(json.dumps({"stats": {"expected": 99, "unexpected": 0, "flaky": 1, "skipped": 0}}))
        with self.assertRaises(reporter.ValidationFailure):
            runner.browser_contracts(Path(self.directory.name), {}, self.path)


if __name__ == "__main__":
    unittest.main()

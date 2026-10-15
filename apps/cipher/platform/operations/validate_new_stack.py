#!/usr/bin/env python3
"""Fresh synthetic-site validation; entirely separate from the legacy Cipher suite.

Requires the pinned development bench/database/Redis already running. Creates a
unique isolated CI site without changing the default site or deleting anything.
Raw command logs remain private; the JSON report carries hashes and safe results.
"""
from __future__ import annotations

import argparse
import ast
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import uuid
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[4]
CIPHER = ROOT / "apps/cipher"
BENCH = "/home/frappe/frappe-bench"
MARKER = "CIPHER_VALIDATION_RESULT="


class ValidationFailure(Exception):
    pass


def require(value, message):
    if not value:
        raise ValidationFailure(message)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def source_inventory():
    path = Path(__file__).with_name("record-evidence.py")
    spec = importlib.util.spec_from_file_location("cipher_evidence_inventory", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    result = module.sources()
    workflow = ROOT / ".github/workflows/cipher-new-stack.yml"
    if workflow.is_file():
        result[str(workflow.relative_to(ROOT))] = sha(workflow)
    return result


class Runner:
    def __init__(self, args):
        self.args = args
        self.started = time.monotonic()
        self.work = Path(tempfile.mkdtemp(prefix="cipher-new-stack-"))
        self.work.chmod(0o700)
        self.results = []
        self.separate_acceptance_procedures = []
        self.source_before = source_inventory()
        self.runtime_matrix = {}

    def stage(self, name, command, *, cwd=ROOT, input_text=None, env=None, classification="build"):
        require(time.monotonic() - self.started < self.args.overall_timeout, "Overall validation budget exhausted")
        log = self.work / (name + ".log")
        started = time.monotonic()
        row = {"name": name, "classification": classification, "command": [str(item) for item in command], "status": "running"}
        self.results.append(row)
        print("RUN " + name, flush=True)
        with log.open("w") as stream:
            process = subprocess.Popen(command, cwd=cwd, env=env, stdin=subprocess.PIPE if input_text is not None else subprocess.DEVNULL,
                                       stdout=stream, stderr=subprocess.STDOUT, text=True, start_new_session=True)
            try:
                process.communicate(input=input_text, timeout=min(self.args.stage_timeout + 20,
                    self.args.overall_timeout - (time.monotonic() - self.started)))
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
                row["status"] = "timed_out"
            row.update(duration_seconds=round(time.monotonic() - started, 3), exit_code=process.returncode,
                       private_log=str(log), log_sha256=sha(log))
        if row["status"] == "timed_out" or process.returncode:
            row["status"] = "failed"
            raise ValidationFailure(name + " failed; inspect its private log")
        row["status"] = "passed"
        print("PASS " + name, flush=True)
        return log.read_text()

    def container(self, name, script, *, classification="actual-frappe", env=None):
        command = [str(self.args.docker), "exec", "-i", "--workdir", BENCH]
        for key, value in (env or {}).items():
            command += ["--env", key + "=" + value]
        command += [self.args.container, "timeout", str(self.args.stage_timeout), "bash", "-euo", "pipefail", "-c", script]
        return self.stage(name, command, input_text="", classification=classification)

    def bootstrap(self):
        # Credentials are inherited inside the existing synthetic runtime. No
        # --set-default, site removal, or new image copy. Register the editable
        # custom app once in the bench catalog, as the development installer does.
        script = r'''test "${CIPHER_SYNTHETIC:-}" = 1
test ! -e "sites/$CIPHER_VALIDATION_SITE"
env/bin/pip install -e 'apps/cipher_aec[validation]' 'unittest-xml-reporting==3.2.0'
env/bin/python - <<'PY'
from pathlib import Path
path = Path('sites/apps.txt')
apps = path.read_text().splitlines()
if 'cipher_aec' not in apps:
    path.write_text('\n'.join(apps + ['cipher_aec']) + '\n')
PY
bench new-site "$CIPHER_VALIDATION_SITE" --mariadb-user-host-login-scope='%' --admin-password "$CIPHER_ADMIN_PASSWORD" --db-root-username root --db-root-password "$CIPHER_DB_ROOT_PASSWORD" --install-app erpnext
bench --site "$CIPHER_VALIDATION_SITE" set-config cipher_site_mode synthetic
bench --site "$CIPHER_VALIDATION_SITE" set-config cipher_synthetic True --parse
bench --site "$CIPHER_VALIDATION_SITE" set-config cipher_allow_unscanned_documents True --parse
bench --site "$CIPHER_VALIDATION_SITE" set-config allow_tests True --parse
bench --site "$CIPHER_VALIDATION_SITE" set-config pause_scheduler True --parse
bench --site "$CIPHER_VALIDATION_SITE" install-app cipher_aec
bench --site "$CIPHER_VALIDATION_SITE" migrate
bench --site "$CIPHER_VALIDATION_SITE" execute cipher_aec.install.seed_synthetic
'''
        self.container("fresh-site-install", script, env={"CIPHER_VALIDATION_SITE": self.args.site})
        output = self.container("runtime-matrix", "env/bin/python - <<'PY'\nimport json,platform,subprocess,frappe,erpnext,cipher_aec\nprint(" + repr(MARKER) + "+json.dumps({'python':platform.python_version(),'frappe':frappe.__version__,'erpnext':erpnext.__version__,'cipher_aec':cipher_aec.__version__,'node':subprocess.check_output(['node','--version'],text=True).strip().removeprefix('v')}))\nPY")
        self.runtime_matrix = self.result_object(output)
        locked = json.loads((CIPHER / "platform/versions.lock.json").read_text())["runtime"]
        for name in ("python", "frappe", "erpnext", "node"):
            require(self.runtime_matrix[name] == locked[name], "Observed " + name + " differs from the locked runtime")
        image_format = '{"reference":{{json .Config.Image}},"image_id":{{json .Image}}}'
        image = json.loads(self.stage("runtime-image", [str(self.args.docker), "inspect", "--format", image_format,
                                                        self.args.container], classification="environment"))
        require(image["reference"] == locked["upstream_image"] or image["image_id"] == locked["development_flat_image_id"],
                "Runtime must use the locked upstream image or recorded flattened development image")
        self.runtime_matrix["image"] = image

    @staticmethod
    def result_object(output):
        values = [line[len(MARKER):] for line in output.splitlines() if line.startswith(MARKER)]
        require(len(values) == 1, "Expected exactly one safe structured stage result")
        value = json.loads(values[0])
        require(isinstance(value, dict), "Stage result must be an object")
        return value

    @staticmethod
    def acceptance_result(output):
        # bench execute pretty-prints its return value amid ordinary diagnostics.
        clean = re.sub(r"\x1b\[[0-9;]*m", "", output)
        decoder = json.JSONDecoder()
        candidates = []
        for match in re.finditer(r"\{", clean):
            try:
                value, length = decoder.raw_decode(clean[match.start():])
            except ValueError:
                continue
            if isinstance(value, dict) and ("label" in value or str(value.get("schema", "")).startswith("cipher.")):
                candidates.append((match.start(), match.start() + length, value))
        require(candidates, "Explicit fixture acceptance returned no structured result")
        outermost = [item for item in candidates if not any(
            other[0] < item[0] and other[1] >= item[1] for other in candidates)]
        result = outermost[-1][2]
        require(result.get("status", "passed") == "passed", "Explicit fixture reported a failed outcome")
        require(result.get("live_model_qualified") is not True and result.get("external_provider_qualified") is not True,
                "A fixture cannot qualify a live model/provider")
        return result

    def database_checks(self):
        cases, test_rows = [], []
        pure_classes = []
        for source in sorted((CIPHER / "platform/apps/cipher_aec/cipher_aec/tests").glob("test_*.py")):
            for node in ast.parse(source.read_text()).body:
                if not isinstance(node, ast.ClassDef):
                    continue
                if any(isinstance(base, ast.Attribute) and base.attr == "TestCase" or
                       isinstance(base, ast.Name) and base.id == "TestCase" for base in node.bases):
                    pure_classes.append("cipher_aec.tests." + source.stem + "." + node.name)
        require(pure_classes, "No ordinary unit-test classes were declared")
        for category in ("integration", "unit"):
            report = "/tmp/cipher-validation-" + self.args.site + "-" + category + ".xml"
            if category == "integration":
                command = 'bench --site "$CIPHER_VALIDATION_SITE" run-tests --app cipher_aec --test-category integration --skip-before-tests --junit-xml-output "$CIPHER_VALIDATION_XML"'
            else:
                command = "env/bin/python - <<'PY'\nimport os,sys,unittest,xmlrunner\nsuite=unittest.defaultTestLoader.loadTestsFromNames(" + repr(pure_classes) + ")\nwith open(os.environ['CIPHER_VALIDATION_XML'],'wb') as stream:\n result=xmlrunner.XMLTestRunner(output=stream).run(suite)\nsys.exit(0 if result.wasSuccessful() else 1)\nPY"
            self.container("frappe-" + category + "-tests", command,
                           env={"CIPHER_VALIDATION_SITE": self.args.site, "CIPHER_VALIDATION_XML": report,
                                "CIPHER_VALIDATION_CATEGORY": category})
            test_rows.append(self.results[-1])
            local = self.work / ("frappe-" + category + "-junit.xml")
            self.stage("collect-" + category + "-junit", [str(self.args.docker), "cp", self.args.container + ":" + report, str(local)], classification="evidence")
            collected = ET.parse(local).getroot().findall(".//testcase")
            require(collected, "The " + category + " runner collected no tests")
            test_rows[-1]["test_summary"] = {"collected": len(collected),
                "failures": sum(item.find("failure") is not None for item in collected),
                "errors": sum(item.find("error") is not None for item in collected),
                "skipped": sum(item.find("skipped") is not None for item in collected)}
            cases.extend(collected)
        require(cases, "The Frappe runner collected no tests")
        unique = {(item.get("classname"), item.get("name")) for item in cases}
        summary = {"collected": len(cases), "unique": len(unique),
                   "failures": sum(item.find("failure") is not None for item in cases),
                   "errors": sum(item.find("error") is not None for item in cases),
                   "skipped": sum(item.find("skipped") is not None for item in cases)}
        expected = []
        for source in sorted((CIPHER / "platform/apps/cipher_aec/cipher_aec/tests").glob("test_*.py")):
            for node in ast.parse(source.read_text()).body:
                if not isinstance(node, ast.ClassDef):
                    continue
                base_names = [base.id if isinstance(base, ast.Name) else base.attr if isinstance(base, ast.Attribute) else "" for base in node.bases]
                if not any(name.endswith("TestCase") for name in base_names):
                    continue
                expected.extend((node.name, method.name) for method in node.body
                                if isinstance(method, ast.FunctionDef) and method.name.startswith("test_"))
        missing = [cls + "." + name for cls, name in expected
                   if not any(item.get("name") == name and cls in (item.get("classname") or "").split(".") for item in cases)]
        summary["missing_declared_cases"] = missing
        self.database_summary = summary
        require(summary["collected"] == summary["unique"] and not any(summary[key] for key in ("failures", "errors", "skipped")),
                "Frappe tests must be nonempty, unique, and pass without skipped cases")
        require(not missing, "The app runner omitted declared test cases; inspect the JUnit collection")
        if self.args.extended_fixtures:
            tests = CIPHER / "platform/apps/cipher_aec/cipher_aec/tests"
            for source in sorted(tests.glob("test_*_acceptance.py")):
                functions = {node.name for node in ast.parse(source.read_text()).body if isinstance(node, ast.FunctionDef)}
                if "run_acceptance" not in functions:
                    self.separate_acceptance_procedures.append({"module": source.stem,
                        "entries": sorted(name for name in functions if name.startswith("run_")),
                        "qualification": "Separate host/HTTP procedure; no bench run_acceptance entry. Not executed or qualified by this runner."})
                    continue
                module = "cipher_aec.tests." + source.stem
                script = "bench --site \"$CIPHER_VALIDATION_SITE\" execute " + module + ".run_acceptance"
                output = self.container(source.stem, script, env={"CIPHER_VALIDATION_SITE": self.args.site},
                                        classification="explicit-synthetic-fixture-with-real-frappe")
                # Preserve the distinction in the overall report even if an
                # adapter fixture produces a cited answer inside these tests.
                self.results[-1]["qualification"] = "Synthetic test fixture; no live model/provider qualification."
                self.results[-1]["fixture_result"] = self.acceptance_result(output)

    def frontend_checks(self):
        copy_root = self.work / "workspace/apps/cipher"
        target = copy_root / "product"
        shutil.copytree(CIPHER / "product", target,
                        ignore=shutil.ignore_patterns("node_modules", "dist", "test-results", "playwright-report", ".git", ".env", ".env.*"))
        schema_source = CIPHER / "platform/apps/cipher_aec/cipher_aec/api/schema.json"
        schema_target = copy_root / "platform/apps/cipher_aec/cipher_aec/api/schema.json"
        schema_target.parent.mkdir(parents=True)
        shutil.copy2(schema_source, schema_target)
        env = {**os.environ, "CI": "1"}
        env.pop("CIPHER_BACKEND_URL", None)
        self.runtime_matrix["frontend_node"] = self.stage("frontend-runtime", ["node", "--version"], cwd=target, env=env).strip()
        self.runtime_matrix["frontend_npm"] = self.stage("frontend-npm", ["npm", "--version"], cwd=target, env=env).strip()
        self.stage("frontend-clean-install", ["npm", "ci", "--no-audit", "--no-fund"], cwd=target, env=env)
        self.stage("generate-api-client", ["npm", "run", "generate:api"], cwd=target, env=env)
        generated = "src/api/contracts.generated.ts"
        require(sha(target / generated) == sha(CIPHER / "product" / generated),
                "Tracked API client differs from a fresh generation of the current schema")
        self.stage("frontend-typecheck-build", ["npm", "run", "build"], cwd=target, env=env)
        if self.args.install_browser:
            self.stage("install-browser", ["npx", "playwright", "install", "--with-deps", "chromium"], cwd=target, env=env)
            executable = self.stage("browser-path", ["node", "--input-type=module", "-e", "import {chromium} from '@playwright/test'; console.log(chromium.executablePath())"], cwd=target, env=env).strip()
            env["CIPHER_CHROME"] = executable
        else:
            executable = env.get("CIPHER_CHROME") or shutil.which("chromium")
            require(executable and Path(executable).is_file(), "Supply CIPHER_CHROME or use --install-browser")
            env["CIPHER_CHROME"] = executable
        browser_report = self.work / "browser-contracts.json"
        env["PLAYWRIGHT_JSON_OUTPUT_FILE"] = str(browser_report)
        self.stage("frontend-browser-contracts", ["npm", "run", "test:contract", "--", "--reporter=json"], cwd=target, env=env,
                   classification="browser-with-explicit-http-fixtures")
        browser = json.loads(browser_report.read_text())["stats"]
        require(browser.get("expected", 0) > 0 and not any(browser.get(key, 0) for key in ("unexpected", "flaky", "skipped")),
                "Browser contract cases must pass without flaky/skipped cases")
        self.results[-1]["test_summary"] = browser

    def run(self):
        failure = None
        try:
            self.bootstrap()
            self.database_checks()
            self.frontend_checks()
        except Exception as exc:
            failure = str(exc) if isinstance(exc, ValidationFailure) else type(exc).__name__
            print("FAIL " + failure, flush=True)
        after = source_inventory()
        changed = sorted(set(self.source_before) ^ set(after) | {key for key in self.source_before.keys() & after.keys() if self.source_before[key] != after[key]})
        if changed:
            failure = failure or "Source changed during validation; repeat relevant checks on a frozen revision"
        result = {"schema": "cipher.new-stack.validation.v1", "executed_at": datetime.now(timezone.utc).isoformat(),
                  "status": "failed" if failure else "passed", "failure": failure,
                  "duration_seconds": round(time.monotonic() - self.started, 3),
                  "limits_seconds": {"stage": self.args.stage_timeout, "overall": self.args.overall_timeout},
                  "site": self.args.site, "site_disposition": "Fresh isolated synthetic site retained; default site unchanged; no site deleted.",
                  "runtime_versions": self.runtime_matrix, "source_sha256": self.source_before,
                  "test_summary": getattr(self, "database_summary", None),
                  "separate_acceptance_procedures": self.separate_acceptance_procedures,
                  "source_changed_during_run": changed, "stages": self.results,
                  "private_work_directory": str(self.work),
                  "qualification_limits": ["Build and tests only; connected browser journey, restart and restore use separate actual evidence.",
                      "Explicit adapter/worker fixtures do not qualify a real model or external provider.",
                      "Raw logs remain private and may contain installation diagnostics; publish only reviewed artifacts."],
                  "live_model_qualified": False, "external_provider_qualified": False}
        self.args.output.parent.mkdir(parents=True, exist_ok=True)
        self.args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
        return 1 if failure else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    default_site = "cipher-ci-" + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S") + "-" + uuid.uuid4().hex[:6] + ".localhost"
    parser.add_argument("--site", default=default_site)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--docker", type=Path, default=CIPHER / "platform/deployment/docker-local.sh")
    parser.add_argument("--container", default="cipher-r0-runtime-1")
    parser.add_argument("--stage-timeout", type=int, default=900)
    parser.add_argument("--overall-timeout", type=int, default=2400)
    parser.add_argument("--extended-fixtures", action="store_true")
    parser.add_argument("--install-browser", action="store_true")
    args = parser.parse_args()
    require(re.fullmatch(r"cipher-ci-[a-z0-9-]{6,60}\.localhost", args.site), "Use a unique cipher-ci-*.localhost site")
    require(30 <= args.stage_timeout <= 1800 and args.stage_timeout <= args.overall_timeout <= 7200,
            "Use bounded validation time limits")
    require(re.fullmatch(r"[a-zA-Z0-9_.-]+", args.container), "Container identifier is invalid")
    return Runner(args).run()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValidationFailure, OSError, ValueError) as exc:
        print("Validation configuration error: " + str(exc), file=sys.stderr)
        sys.exit(2)

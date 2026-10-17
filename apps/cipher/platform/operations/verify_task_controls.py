#!/usr/bin/env python3
"""Actual synthetic Task-control HTTP qualification; never provisions duties.

Credentials use CIPHER_FIXTURE_PASSWORD or CIPHER_TRIAL_<ROLE>_PASSWORD. Original
operation IDs and payloads are fsynced before requests. Resume only the original
origin/state after uncertainty. Readback performs no business POST or replay.
The revoked phase requires the operator to revoke one exact duty beforehand.
"""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from urllib.parse import quote, urlsplit
from uuid import uuid4

from verify_local_trial import digest, write_json
from verify_r0 import CheckFailure, Client, require


CORE = "cipher_aec.api.v1."
STATE_SCHEMA = "cipher.task-controls.http-state.v1"
STATUSES = ["Open", "Working", "Pending Review", "Completed"]
REQUIRED_AUTHOR_DUTIES = {"project.read", "task.create", "task.assign", "task.update"}
DEFAULT_SCHEMA = Path(__file__).resolve().parents[1] / "apps/cipher_aec/cipher_aec/api/schema.json"
REQUEST_SCHEMAS = {"create_task": "CreateTaskRequest", "assign_task": "AssignTaskRequest", "update_task_status": "UpdateTaskStatusRequest"}


class TaskVerifier:
    def __init__(self, args):
        from jsonschema import Draft202012Validator, FormatChecker
        self.args = args
        self.fixture = json.loads(args.fixture.read_text(encoding="utf-8"))
        require(self.fixture.get("schema") == "cipher.local-trial.v1" and self.fixture.get("site_mode") == "synthetic", "Use the explicit nonsecret synthetic trial fixture")
        parsed = urlsplit(args.base_url)
        require(parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost", "cipher-trial.localhost", "cipher-integration.localhost"}
            and not parsed.username and not parsed.password and parsed.path in {"", "/"} and not parsed.query and not parsed.fragment, "Use a loopback HTTP origin without credentials or a path")
        require(args.host_header in {"cipher.localhost", "cipher-trial.localhost", "cipher-integration.localhost"}, "Select the explicit local synthetic Host")
        schema_bytes = args.schema.read_bytes()
        self.schema = json.loads(schema_bytes)
        self.schema_hash = hashlib.sha256(schema_bytes).hexdigest()
        self.validators = {name: Draft202012Validator({"$ref": "#/$defs/" + name, "$defs": self.schema["$defs"]}, format_checker=FormatChecker())
            for name in ("CurrentTask", "Task", "TaskChoices", "TaskControlResponse", "CreateTaskResponse", "TaskList", *REQUEST_SCHEMAS.values())}
        self.scope = {"company": self.fixture["company"], "project": self.fixture["project"]}
        self.state_path = args.state or args.output.with_suffix(args.output.suffix + ".state.json")
        require(self.state_path.resolve() != args.output.resolve(), "State and report must have different paths")
        protected = {args.fixture.resolve(), args.schema.resolve(), Path(__file__).resolve(),
            Path(__file__).with_name("verify_local_trial.py").resolve(), Path(__file__).with_name("verify_r0.py").resolve()}
        if args.historical_state is not None:
            protected.add(args.historical_state.resolve())
        require(self.state_path.resolve() not in protected and args.output.resolve() not in protected, "Report/state must not replace an input or verifier source")
        require(not args.output.exists() or args.resume and args.phase == "journey", "Use a new report path for each qualification phase")
        if args.resume or args.phase != "journey":
            self.state = json.loads(self.state_path.read_text(encoding="utf-8"))
            require(self.state.get("schema") == STATE_SCHEMA and self.state.get("fixture_digest") == digest(self.fixture), "State belongs to a different fixture")
            require(self.state.get("origin") == args.base_url and self.state.get("host") == args.host_header, "Resume or read back the original origin and Host")
            require(self.state.get("schema_sha256") == self.schema_hash, "The original schema changed; retain the failed run and qualify changed source separately")
            if args.historical_state is not None:
                require(bool(self.state.get("historical")) and args.historical_state.resolve() == Path(self.state["historical"]["source"]).resolve(), "Resume the original historical qualification scope; do not attach another database's records")
        else:
            require(not self.state_path.exists() and not args.output.exists(), "Use a new report/state or explicitly resume the original run")
            historical = None
            if args.historical_state is not None:
                raw = args.historical_state.read_bytes()
                original = json.loads(raw)
                require(original.get("schema") == "cipher.local-trial.http-state.v1" and original.get("fixture_digest") == digest(self.fixture), "Historical source must match the original trial fixture")
                command = original.get("commands", {}).get("task-create", {})
                require(command.get("status") == "returned" and isinstance(command.get("result", {}).get("task"), dict), "Historical source must retain its successful original Task result")
                historical = {"source": str(args.historical_state.resolve()), "sha256": hashlib.sha256(raw).hexdigest(),
                    "operation_id": command["payload"]["operation_id"], "task": command["result"]["task"]}
            self.state = {"schema": STATE_SCHEMA, "fixture_digest": digest(self.fixture), "schema_sha256": self.schema_hash,
                "origin": args.base_url, "host": args.host_header, "run_id": str(uuid4()), "commands": {}, "probes": {}, "records": {}, "historical": historical}
        if self.state.get("historical"):
            require(Path(self.state["historical"]["source"]).resolve() not in {self.state_path.resolve(), args.output.resolve()}, "Report/state must preserve the original historical source journal")
            require(hashlib.sha256(Path(self.state["historical"]["source"]).read_bytes()).hexdigest() == self.state["historical"]["sha256"], "The original historical source bytes changed; retain the original proof")
        if args.phase == "revoked":
            require(args.revoked_ability in {"task.assign", "task.update"}, "The revoked phase requires an explicit task.assign or task.update ability")
            require("final_task" in self.state["records"], "Finish the original Task journey before the operator-staged revocation phase")
        self.initial_state_hash = hashlib.sha256(self.state_path.read_bytes()).hexdigest() if self.state_path.exists() else None
        self.clients = {}
        self.sessions = {}
        self.report = {"schema": "cipher.task-controls.http.v1", "phase": args.phase, "run_id": self.state["run_id"], "origin": args.base_url,
            "host": args.host_header, "scope": self.scope, "status": "running", "credentials_recorded": False, "checks": [],
            "schema_sha256": self.schema_hash, "source_files": self.source_files(),
            "historical_source": {key: self.state["historical"][key] for key in ("source", "sha256")} if self.state.get("historical") else None,
            "limits": ["Actual HTTP proof requires executing this procedure against the candidate; host tests do not qualify native behavior.",
                "Reconciled empty active-assignment projection is checked. Exact native ToDo Closed/Cancelled rows, completion fields and unchanged Project accounting facts require the independent native audit.",
                "No duty provisioning, provider, commercial, finance or award operation is invoked."]}
        if not self.state.get("historical"):
            self.report["qualification_scope"] = "Current Task controls only; pre-upgrade historical receipt qualification is not exercised."
        if args.phase != "readback":
            self.persist()

    @staticmethod
    def source_files():
        paths = (Path(__file__).resolve(), Path(__file__).with_name("verify_local_trial.py"), Path(__file__).with_name("verify_r0.py"))
        return [{"file": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()} for path in paths]

    def validate(self, name, value):
        errors = list(self.validators[name].iter_errors(value))
        require(not errors, "Response/request does not satisfy frozen " + name + " schema")
        return value

    def persist(self):
        require(self.args.phase != "readback", "Readback cannot rewrite the original command journal")
        write_json(self.state_path, self.state)

    def get(self, role, route, payload, schema=None, expected=(200,)):
        value = self.clients[role].api(CORE + route, payload, expected=expected)
        return self.validate(schema, value) if schema and expected == (200,) else value

    def command(self, label, role, route, payload, expected=(200,), error_code=None):
        require(self.args.phase in {"journey", "revoked"}, "Readback cannot send business commands or replays")
        require(route in REQUEST_SCHEMAS, "Only the three bounded Task commands are admitted")
        saved = self.state["commands"].get(label)
        if saved is None:
            saved = {"role": role, "route": route, "payload": {**deepcopy(payload), "operation_id": str(uuid4())}, "expected": list(expected), "error_code": error_code, "status": "intent"}
            self.validate(REQUEST_SCHEMAS[route], saved["payload"])
            self.state["commands"][label] = saved
            self.persist()
        require(saved["role"] == role and saved["route"] == route and saved["expected"] == list(expected) and saved["error_code"] == error_code, "Resume the original bounded command contract")
        if saved["status"] == "returned":
            return deepcopy(saved["result"])
        value = self.clients[role].api(CORE + route, saved["payload"], method="POST", expected=expected, operation=saved["payload"]["operation_id"])
        if expected == (200,):
            self.validate("CreateTaskResponse" if route == "create_task" else "TaskControlResponse", value)
            self.validate("CurrentTask", value["task"])
            require(value["operation"]["id"] == saved["payload"]["operation_id"], "The returned receipt must belong to its original operation")
        else:
            require(value.get("code") == error_code, "The Task refusal has an unexpected domain code")
        saved.update(status="returned", result=value)
        self.persist()
        return value

    def replay(self, label, original_label, role, expected=(200,), error_code=None):
        require(self.args.phase in {"journey", "revoked"}, "Readback cannot send business commands or replays")
        source = self.state["commands"][original_label]
        require(source["route"] in REQUEST_SCHEMAS and source.get("status") == "returned" and source.get("expected") == [200], "Only a successful original bounded Task command can be replayed")
        probe = self.state["probes"].get(label)
        if probe is None:
            probe = {"source_label": original_label, "role": role, "route": source["route"], "payload": deepcopy(source["payload"]),
                "expected": list(expected), "error_code": error_code, "status": "intent"}
            self.state["probes"][label] = probe
            self.persist()
        require(probe["payload"] == source["payload"] and probe["role"] == role and probe["expected"] == list(expected)
            and probe["route"] == source["route"] and probe["source_label"] == original_label and probe.get("error_code") == error_code, "Replay must preserve the original exact operation and payload")
        if probe["status"] == "returned":
            return deepcopy(probe["result"])
        result = self.clients[role].api(CORE + probe["route"], probe["payload"], method="POST", expected=expected, operation=probe["payload"]["operation_id"])
        if expected == (200,):
            self.validate("TaskControlResponse", result)
            require(result["operation"]["replayed"] is True and result["task"] == source["result"]["task"], "Replay must return its original immutable Task facts")
        else:
            require(result.get("code") == error_code, "Revoked replay must refuse the current missing duty")
        probe.update(status="returned", result=result)
        self.persist()
        return result

    def authenticate(self):
        for role in ("primary", "alias", "reviewer", "outsider"):
            password = os.environ.get("CIPHER_TRIAL_" + role.upper() + "_PASSWORD") or os.environ.get("CIPHER_FIXTURE_PASSWORD")
            require(bool(password), "Supply credentials privately through the process environment")
            user = self.fixture["users"][role]["user"]
            client = Client(self.args.base_url, self.args.host_header)
            client.login({"user": user, "password": password})
            session = client.api("session")
            require(session.get("site_mode") == "synthetic" and session.get("user") == user and session.get("person", {}).get("id") == self.fixture["users"][role]["person"], "Authenticate the exact seeded synthetic identity before any Task write")
            require(isinstance(session.get("csrf_token"), str) and session["csrf_token"], "Actual cookie/CSRF authentication is required")
            client.csrf = session["csrf_token"]
            self.clients[role], self.sessions[role] = client, session
        require(self.sessions["primary"]["person"]["id"] == self.sessions["alias"]["person"]["id"] != self.sessions["reviewer"]["person"]["id"], "Aliases must share one canonical Person; reviewer must remain separate")
        return "Four actual cookie/CSRF sessions with canonical Person checks."

    def preflight(self):
        project = self.get("primary", "project", self.scope)
        if self.args.phase == "journey":
            require(REQUIRED_AUTHOR_DUTIES <= set(project.get("capabilities", [])), "Provision primary project.read/task.create/task.assign/task.update separately before this run")
            choices = self.get("primary", "task_choices", self.scope, "TaskChoices")
            require(choices["statuses"] == STATUSES and {"task.assign", "task.update"} <= set(choices["capabilities"]), "Candidate Task metadata and both control duties are required")
            ids = [row["id"] for row in choices["people"]]
            primary, reviewer, outsider = (self.fixture["users"][key]["person"] for key in ("primary", "reviewer", "outsider"))
            require(len(ids) == len(set(ids)) and ids.count(primary) == 1 and reviewer in ids and outsider not in ids, "Choices must deduplicate aliases, admit reviewer and exclude the other-Project person")
            alias = self.get("alias", "task_choices", self.scope, "TaskChoices")
            require(alias == choices, "Alias choices must identify the same canonical people and control duties")
            reviewer_project = self.get("reviewer", "project", self.scope)
            require(not {"task.assign", "task.update"} & set(reviewer_project.get("capabilities", [])), "Reviewer negative tests require its read-only Project fixture")
            self.state["records"].setdefault("project_status_before", project["status"])
            self.state["records"].setdefault("assignee", self.fixture["users"][self.args.assignee_role]["person"])
            require(self.state["records"]["assignee"] in ids, "Select an eligible canonical trial Person")
            self.persist()
        elif self.args.phase == "revoked":
            require(self.args.revoked_ability not in project.get("capabilities", []), "The operator must first revoke the exact selected duty; this verifier never changes duties")
        return {"project": project["id"], "capabilities": project.get("capabilities", [])}

    def detail(self, role="primary"):
        return self.get(role, "task", {**self.scope, "task": self.state["records"]["task"]}, "CurrentTask")

    @staticmethod
    def facts(task, status, people):
        require(task["status"] == status and [row["id"] for row in task["assignees"]] == people and task["assignment_conflict"] is False, "Task status/active canonical assignment projection does not match the exact expected facts")
        require(bool(re.fullmatch("[0-9a-f]{64}", task["version"])), "Current Task version must be the opaque native fact token")

    def unchanged(self, before):
        require(self.detail() == before, "A refused command or exact replay changed the current Task")

    def controls(self):
        project = self.get("primary", "project", self.scope)
        created = self.command("create", "primary", "create_task", {**self.scope, "expected_version": project["version"],
            "subject": "Synthetic Task controls " + self.state["run_id"], "description": "Dedicated ordinary standalone synthetic Task for the candidate HTTP qualification."})
        self.state["records"]["task"] = created["task"]["id"]
        self.persist()
        self.facts(created["task"], "Open", [])
        # On resume use retained original command results; never create a second
        # Task or substitute a new version/UUID for an uncertain command.
        target = self.state["records"]["assignee"]
        assigned = self.command("assign-initial", "primary", "assign_task", {**self.scope, "task": created["task"]["id"], "assignee_person": target, "expected_version": created["task"]["version"]})
        self.facts(assigned["task"], "Open", [target])
        self.replay("assign-primary-replay", "assign-initial", "primary")
        self.replay("assign-alias-replay", "assign-initial", "alias")
        if "status-working" not in self.state["commands"]:
            self.unchanged(assigned["task"])
        self.command("stale-denial", "primary", "update_task_status", {**self.scope, "task": created["task"]["id"], "status": "Working", "expected_version": created["task"]["version"]}, (412,), "stale_version")
        if "status-working" not in self.state["commands"]:
            self.unchanged(assigned["task"])
        for role in ("reviewer", "outsider"):
            status, code = ((403, "capability_denied") if role == "reviewer" else (404, "not_found"))
            self.command(role + "-assign-denial", role, "assign_task", {**self.scope, "task": created["task"]["id"], "assignee_person": target, "expected_version": assigned["task"]["version"]}, (status,), code)
            self.command(role + "-status-denial", role, "update_task_status", {**self.scope, "task": created["task"]["id"], "status": "Working", "expected_version": assigned["task"]["version"]}, (status,), code)
        self.get("outsider", "task", {**self.scope, "task": created["task"]["id"]}, expected=(404,))
        self.get("outsider", "tasks", self.scope, expected=(404,))
        self.get("outsider", "task_choices", self.scope, expected=(404,))
        self.clients["primary"].request("GET", "/api/resource/Task/" + quote(created["task"]["id"], safe=""), expected=(403, 404))
        self.clients["primary"].request("GET", "/api/resource/Task", expected=(403, 404))
        current = assigned["task"]
        for label, status in (("status-working", "Working"), ("status-review", "Pending Review"), ("status-complete", "Completed")):
            current = self.command(label, "primary", "update_task_status", {**self.scope, "task": current["id"], "status": status, "expected_version": current["version"]})["task"]
            self.facts(current, status, [] if status == "Completed" else [target])
        if "status-reopen" not in self.state["commands"]:
            self.unchanged(current)
        self.command("completed-assign-denial", "primary", "assign_task", {**self.scope, "task": current["id"], "assignee_person": target, "expected_version": current["version"]}, (409,), "task_closed")
        reopened = self.command("status-reopen", "primary", "update_task_status", {**self.scope, "task": current["id"], "status": "Open", "expected_version": current["version"]})["task"]
        self.facts(reopened, "Open", [])
        if "assign-after-reopen" not in self.state["commands"]:
            self.unchanged(reopened)
        reassigned = self.command("assign-after-reopen", "primary", "assign_task", {**self.scope, "task": reopened["id"], "assignee_person": self.fixture["users"]["primary"]["person"], "expected_version": reopened["version"]})["task"]
        self.facts(reassigned, "Open", [self.fixture["users"]["primary"]["person"]])
        final = self.command("unassign-explicit", "primary", "assign_task", {**self.scope, "task": reassigned["id"], "assignee_person": None, "expected_version": reassigned["version"]})["task"]
        self.facts(final, "Open", [])
        self.state["records"]["final_task"] = final
        self.persist()
        return {"task": final["id"], "transition_sequence": STATUSES + ["Open"], "reopen_assignment_revived": False, "explicit_unassign": True}

    def receipts(self):
        count = 0
        for label, command in self.state["commands"].items():
            if command.get("status") != "returned" or command["expected"] != [200]:
                continue
            for role in ("primary", "alias"):
                receipt = self.get(role, "operation", {**self.scope, "operation_id": command["payload"]["operation_id"]}, "CreateTaskResponse" if command["route"] == "create_task" else "TaskControlResponse")
                require(receipt["task"] == command["result"]["task"] and receipt["operation"]["replayed"] is True, "Saved canonical-person receipt must retain its original Task facts after later controls")
                count += 1
        return {"new_receipt_reads": count}

    def historical_receipts(self):
        historical = self.state.get("historical")
        require(bool(historical), "No historical source was supplied; historical receipt qualification is not exercised")
        for role in ("primary", "alias"):
            receipt = self.get(role, "operation", {**self.scope, "operation_id": historical["operation_id"]}, "CreateTaskResponse")
            require(receipt["task"] == historical["task"], "Historical original Task receipt was rewritten or expanded")
        return {"historical_receipt": historical["operation_id"], "historical_assignment_fields_present": sorted(set(historical["task"]) & {"assignees", "assignment_conflict"})}

    def readback(self):
        expected = self.state["records"]["final_task"]
        for role in ("primary", "reviewer"):
            require(self.detail(role) == expected, "Canonical Task readback must reopen the exact final saved facts")
            cursor, found, pages = None, [], 0
            while True:
                page = self.get(role, "tasks", {**self.scope, "limit": 50, **({"cursor": cursor} if cursor else {})}, "TaskList")
                for row in page["items"]:
                    self.validate("CurrentTask", row)
                    if row["id"] == expected["id"]:
                        found.append(row)
                pages += 1
                cursor = page.get("next_cursor")
                require(pages <= 20, "Task-list verification exceeded its bounded 1,000-record scan")
                if not cursor:
                    break
            require(found == [expected], "Task list must contain exactly one original dedicated Task")
        project = self.get("primary", "project", self.scope)
        require(project["status"] == self.state["records"]["project_status_before"], "Task controls must preserve the governed Project status")
        return {"task": expected["id"], "status": expected["status"], "assignees": expected["assignees"]}

    def revoked(self):
        before = self.detail()
        ability = self.args.revoked_ability
        route, original = ("assign_task", "assign-initial") if ability == "task.assign" else ("update_task_status", "status-working")
        payload = {**self.scope, "task": before["id"], "expected_version": before["version"]}
        payload.update({"assignee_person": self.state["records"]["assignee"]} if ability == "task.assign" else {"status": "Working"})
        self.command("revoked-new-" + ability, "primary", route, payload, (403,), "capability_denied")
        self.replay("revoked-original-" + ability, original, "primary", (403,), "capability_denied")
        self.replay("revoked-alias-" + ability, original, "alias", (403,), "capability_denied")
        self.unchanged(before)
        return {"revoked_ability": ability, "new_effect": "denied", "original_replay": "denied", "alias_replay": "denied", "duty_changed_by_verifier": False}

    def check(self, name, callback):
        self.report["active_check"] = name
        write_json(self.args.output, self.report)
        result = callback()
        self.report["checks"].append({"check": name, "status": "passed", "detail": result})
        print("PASS " + name, flush=True)

    def run(self):
        try:
            self.check("real cookie/CSRF authentication and canonical people", self.authenticate)
            self.check("current exact Project authority and candidate metadata", self.preflight)
            if self.args.phase == "journey":
                self.check("assignment, replay, stale/refused writes, status sequence and explicit unassign", self.controls)
            elif self.args.phase == "revoked":
                self.check("operator-staged current duty revocation denies effects and original replays", self.revoked)
            self.check("canonical detail/list and Project-status readback", self.readback)
            self.check("current immutable Task receipt schemas", self.receipts)
            if self.state.get("historical"):
                self.check("pre-upgrade historical immutable Task receipt schema", self.historical_receipts)
            else:
                self.report["checks"].append({"check": "pre-upgrade historical immutable Task receipt schema", "status": "not_exercised",
                    "detail": "not exercised: no pre-upgrade records in this fresh integration site"})
            self.report["status"] = "passed"
        except Exception as error:
            message = str(error) if isinstance(error, CheckFailure) else type(error).__name__
            self.report["status"] = "failed"
            self.report["checks"].append({"check": self.report.get("active_check"), "status": "failed", "detail": message})
            print("FAIL " + str(self.report.get("active_check")) + ": " + message, flush=True)
        finally:
            if self.state.get("historical"):
                historical = Path(self.state["historical"]["source"])
                unchanged = historical.exists() and hashlib.sha256(historical.read_bytes()).hexdigest() == self.state["historical"]["sha256"]
                self.report["historical_source_unchanged"] = unchanged
                if not unchanged:
                    self.report["status"] = "failed"
            if self.args.phase == "readback":
                self.report["command_state_unchanged"] = hashlib.sha256(self.state_path.read_bytes()).hexdigest() == self.initial_state_hash
                if not self.report["command_state_unchanged"]:
                    self.report["status"] = "failed"
            self.report["records"] = self.state["records"]
            self.report["observations"] = {role: client.observations for role, client in self.clients.items()}
            self.report.pop("active_check", None)
            write_json(self.args.output, self.report)
        return 0 if self.report["status"] == "passed" else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--historical-state", type=Path, help="Optional pre-upgrade local-trial state from this same database; omit for a fresh site")
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    parser.add_argument("--base-url", default="http://127.0.0.1:18900")
    parser.add_argument("--host-header", default="cipher.localhost")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--state", type=Path, help="Original Task-control journal for resume/readback/operator-staged revocation")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--phase", choices=("journey", "readback", "revoked"), default="journey")
    parser.add_argument("--assignee-role", choices=("primary", "reviewer"), default="reviewer")
    parser.add_argument("--revoked-ability", choices=("task.assign", "task.update"))
    args = parser.parse_args(argv)
    try:
        return TaskVerifier(args).run()
    except Exception as error:
        print("Task-control qualification refused setup: " + (str(error) if isinstance(error, CheckFailure) else type(error).__name__), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

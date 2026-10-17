#!/usr/bin/env python3
"""Actual local HTTP trial; credentials/cookies/CSRF never enter its report.

Use the nonsecret seed manifest, private credential environment and an explicit
report path. Interrupted commands retain their original UUID/payload in the
adjacent state file; --resume continues that run. --phase readback makes no
business writes and can verify the same records after a restart.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import date, timedelta
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit
from uuid import uuid4

from verify_r0 import CheckFailure, Client, require


CORE = "cipher_aec.api.v1."
EST = "cipher_aec.estimating.api."
COM = "cipher_aec.commercial.api."
ENG = "cipher_aec.engineering.api."
APPROVAL = "cipher_aec.api.approvals."
DOC = "cipher_aec.documents.api."


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


class TrialVerifier:
    def __init__(self, args):
        self.args = args
        self.fixture = json.loads(args.fixture.read_text(encoding="utf-8"))
        require(self.fixture.get("schema") == "cipher.local-trial.v1" and self.fixture.get("site_mode") == "synthetic", "Use the explicit nonsecret local-trial seed manifest")
        parsed = urlsplit(args.base_url)
        require(parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost", "cipher-trial.localhost", "cipher-integration.localhost"}, "Only the loopback synthetic profile is admitted")
        require(not parsed.username and not parsed.password and not parsed.query and not parsed.fragment and parsed.path in {"", "/"}, "Use only the loopback origin without embedded credentials or a path")
        self.scope = {"company": self.fixture["company"], "project": self.fixture["project"]}
        self.state_path = args.output.with_suffix(args.output.suffix + ".state.json")
        recovery_source = getattr(args, "recovery_source_state", None)
        if recovery_source is not None:
            require(args.phase == "readback" and not args.resume, "Recovery-source state is admitted only for a new readback run")
            require(parsed.hostname in {"127.0.0.1", "localhost"} and bool(re.fullmatch(r"cipher-restore-[0-9]{14}\.localhost", args.host_header or "")), "Recovery readback requires a loopback target and an exact cipher-restore-YYYYMMDDhhmmss.localhost Host")
            require(not args.output.exists() and not self.state_path.exists(), "Use a new recovery report path")
            require(recovery_source.resolve() not in {args.output.resolve(), self.state_path.resolve()}, "Recovery output must not replace its original source state")
            original_bytes = recovery_source.read_bytes()
            original = json.loads(original_bytes)
            require(original.get("schema") == "cipher.local-trial.http-state.v1" and original.get("fixture_digest") == digest(self.fixture), "Recovery state must match the original trial fixture")
            records = original.get("records", {})
            require(isinstance(records, dict) and all(key in records for key in ("task", "estimate", "proposal", "engineering")), "Recovery requires the complete original saved-record set")
            provenance = {"source_state": str(recovery_source.resolve()), "source_state_sha256": hashlib.sha256(original_bytes).hexdigest(),
                "source_origin": original.get("origin"), "source_run_id": original.get("run_id"),
                "target_origin": args.base_url, "target_host": args.host_header, "record_policy": "read-original-records-only"}
            self.state = {"schema": "cipher.local-trial.http-state.v1", "fixture_digest": digest(self.fixture),
                "origin": args.base_url, "run_id": str(uuid4()), "commands": {}, "records": deepcopy(records), "recovery": provenance}
        elif args.resume or args.phase == "readback":
            self.state = json.loads(self.state_path.read_text(encoding="utf-8"))
            require(self.state.get("fixture_digest") == digest(self.fixture), "The original state belongs to another seed manifest")
            require(self.state.get("origin") == args.base_url, "Resume the original HTTP origin")
            if self.state.get("recovery"):
                require(args.phase == "readback" and bool(re.fullmatch(r"cipher-restore-[0-9]{14}\.localhost", args.host_header or ""))
                    and args.host_header == self.state["recovery"]["target_host"], "Derived recovery state remains readback-only on its exact restored Host")
        else:
            require(not args.output.exists() and not self.state_path.exists(), "Use a new report path or explicitly resume the original run")
            self.state = {"schema": "cipher.local-trial.http-state.v1", "fixture_digest": digest(self.fixture),
                "origin": args.base_url, "run_id": str(uuid4()), "commands": {}, "records": {}}
        self.clients = {}
        self.report = {"schema": "cipher.local-trial.http.v1", "phase": args.phase, "run_id": self.state["run_id"],
            "origin": args.base_url, "scope": self.scope, "status": "running", "credentials_recorded": False,
            "checks": [], "capability_gaps": self.fixture.get("capability_gaps", []),
            "limits": ["Actual HTTP/local synthetic qualification only; browser usability remains separate.",
                "No award, provider or external-delivery route is invoked; native table preservation needs its separate before/after audit."]}
        if self.state.get("recovery"):
            self.report["recovery"] = deepcopy(self.state["recovery"])
        self.persist()

    def persist(self):
        write_json(self.state_path, self.state)

    def check(self, name, callback):
        self.report["active_check"] = name
        write_json(self.args.output, self.report)
        detail = callback()
        self.report["checks"].append({"check": name, "status": "passed", "detail": detail})
        print("PASS " + name, flush=True)

    def command(self, label, role, route, payload, expected=(200,)):
        require(self.args.phase == "journey" and not self.state.get("recovery"), "Business commands and replays are forbidden during readback")
        saved = self.state["commands"].get(label)
        if saved is None:
            operation = str(uuid4())
            saved = {"role": role, "route": route, "payload": {**deepcopy(payload), "operation_id": operation},
                "expected": list(expected), "status": "intent"}
            self.state["commands"][label] = saved
            self.persist()  # Persist original intent before every business POST.
        require(saved["role"] == role and saved["route"] == route and saved["expected"] == list(expected), "Resume the original declared command")
        if saved["status"] == "returned":
            return deepcopy(saved["result"])
        result = self.clients[role].api(route, saved["payload"], method="POST", expected=expected, operation=saved["payload"]["operation_id"])
        saved.update(status="returned", result=result)
        self.persist()
        return result

    def authenticate(self):
        for role in ("primary", "alias", "reviewer", "outsider"):
            user = self.fixture["users"][role]["user"]
            password = os.environ.get("CIPHER_TRIAL_" + role.upper() + "_PASSWORD") or os.environ.get("CIPHER_FIXTURE_PASSWORD")
            require(bool(password), "Supply local credentials through the private process environment")
            client = Client(self.args.base_url, self.args.host_header)
            client.login({"user": user, "password": password})
            session = client.api("session")
            require(session.get("site_mode") == "synthetic" and session.get("user") == user, "Authenticate the exact synthetic trial identity before mutation")
            require(session.get("person", {}).get("id") == self.fixture["users"][role]["person"], "Canonical trial person does not match the seed manifest")
            require(isinstance(session.get("csrf_token"), str) and session["csrf_token"], "An actual cookie session and CSRF token are required")
            client.csrf = session["csrf_token"]
            self.clients[role] = client
        users = self.fixture["users"]
        require(users["primary"]["person"] == users["alias"]["person"] != users["reviewer"]["person"], "Independent review requires a different canonical person")
        return "Four actual cookie sessions; canonical-person separation and CSRF confirmed."

    def tasks_and_denials(self):
        primary, reviewer, outsider = (self.clients[key] for key in ("primary", "reviewer", "outsider"))
        project = primary.api("project", self.scope)
        require(project["id"] == self.scope["project"] and "task.create" in project["capabilities"], "The intended Project/task authority is unavailable")
        task = self.command("task-create", "primary", CORE + "create_task", {**self.scope, "expected_version": project["version"],
            "subject": "Synthetic local trial " + self.state["run_id"], "description": "Persistent task creation; no assignee or completion claim."})
        original = self.state["commands"]["task-create"]["payload"]
        replay = self.clients["alias"].api("create_task", original, method="POST", operation=original["operation_id"])
        require(replay["task"]["id"] == task["task"]["id"] and replay["operation"]["replayed"] is True, "Alias replay must preserve exactly one original Task")
        denied = self.command("reviewer-task-denial", "reviewer", CORE + "create_task", {**self.scope, "expected_version": project["version"], "subject": "Denied reviewer task"}, (403,))
        require(denied["code"] == "capability_denied", "Reviewer task authoring must fail for its missing duty")
        reviewer.api("project", self.scope)
        outsider.api("project", self.scope, expected=(404,))
        self.state["records"]["task"] = task["task"]["id"]
        self.persist()
        self.task_readback()
        return {"task": task["task"]["id"], "reviewer_write": "denied", "outsider_read": "denied"}

    def task_readback(self):
        identifier = self.state["records"]["task"]
        for role in ("primary", "reviewer"):
            cursor = None
            found = []
            while True:
                page = self.clients[role].api("tasks", {**self.scope, "limit": 50, **({"cursor": cursor} if cursor else {})})
                found.extend(row for row in page["items"] if row["id"] == identifier)
                cursor = page.get("next_cursor")
                if not cursor:
                    break
            require(len(found) == 1 and found[0]["status"] == "Open", "Saved Task must reopen exactly once with its original status")
        return {"task": identifier, "reopened_by": ["primary", "reviewer"]}

    def source_bytes(self):
        reference = self.fixture["source"]["citation"]
        for role in ("primary", "reviewer"):
            _, _, content, headers = self.clients[role].request("GET", "/api/method/" + DOC + "download_revision",
                {"company": self.scope["company"], "revision_id": reference["revision_id"]}, expected=(200,))
            require(hashlib.sha256(content).hexdigest() == reference["source_sha256"], "Stored original bytes must match the exact seed source checksum")
            require("attachment" in headers.get("Content-Disposition", ""), "Original source must download as an attachment")
        return {"revision": reference["revision_id"], "sha256": reference["source_sha256"]}

    def estimates(self):
        draft = self.command("estimate-create", "primary", EST + "create_estimate", {**self.scope, "title": "Synthetic trial cost " + self.state["run_id"], "currency": "USD", "pricing_date": date.today().isoformat()})["estimate"]
        line = {"line_id": str(uuid4()), "description": "Authored trial labor", "quantity": {"amount": "8", "unit_id": self.fixture["unit"]["id"], "precision": 6},
            "cost_code": "TRIAL-LABOR", "notes": "Manual synthetic quantity", "alternate": "", "included": True,
            "rate_source_id": self.fixture["rate_source"], "material_factor": "1", "waste_fraction": "0"}
        base = {**self.scope, "estimate_id": draft["id"], "expected_revision": None, "lines": [line], "adjustments": [], "conversion_ids": [],
            "basis_description": "Manually authored local trial labor quantity", "basis_citations": [self.fixture["source"]["citation"]]}
        first = self.command("estimate-revision-1", "primary", EST + "calculate_revision", base)
        require(first["revision"]["total"]["amount"] == "600.00", "Eight authored hours at USD75 must calculate USD600.00")
        second_payload = deepcopy(self.state["commands"]["estimate-revision-1"]["payload"])
        second_payload.pop("operation_id")
        second_payload["expected_revision"] = first["revision"]["id"]
        second_payload["lines"][0]["quantity"]["amount"] = "10"
        second = self.command("estimate-revision-2", "primary", EST + "calculate_revision", second_payload)
        require(second["revision"]["total"]["amount"] == "750.00" and second["revision"]["predecessor"] == first["revision"]["id"], "Successor must preserve lineage and calculate USD750.00")
        self.state["records"]["estimate"] = {"id": draft["id"], "first": first["revision"]["id"], "second": second["revision"]["id"]}
        self.persist()
        self.estimate_readback()
        return self.state["records"]["estimate"]

    def estimate_readback(self):
        records = self.state["records"]["estimate"]
        primary = self.clients["primary"]
        for key, expected in (("first", "600.00"), ("second", "750.00")):
            value = primary.api(EST + "get_record", {**self.scope, "kind": "revision", "record_id": records[key]})
            require(value["total"]["amount"] == expected, "Original saved estimate total changed")
        head = primary.api(EST + "get_record", {**self.scope, "kind": "estimate", "record_id": records["id"]})
        require(head["current_revision"] == records["second"], "Saved estimate head must reopen its successor")
        return records

    def proposals(self):
        company = {"company": self.scope["company"]}
        pursuit = self.command("pursuit-create", "primary", COM + "create_pursuit", {**company, "party_type": "Customer", "party_id": self.fixture["native"]["customer"], "fields": {"title": "Synthetic trial scope " + self.state["run_id"]}})["pursuit"]
        composition = {"currency": "USD", "price_list": self.fixture["native"]["price_list"], "valid_till": (date.today() + timedelta(days=30)).isoformat(),
            "terms": "Synthetic internal trial draft only.", "sections": [], "price_lines": [{"id": str(uuid4()), "description": "Authored internal coordination scope", "quantity": "8",
                "unit_id": self.fixture["unit"]["id"], "unit_revision": self.fixture["unit"]["revision"], "rate": "75.00", "selected": True}], "source_references": []}
        first = self.command("proposal-create", "primary", COM + "create_proposal", {**company, "pursuit_id": pursuit["id"], "composition": composition})
        composition = deepcopy(first["revision"]["composition"])
        composition.pop("estimate_revision", None)
        composition["price_lines"][0]["quantity"] = "10"
        second = self.command("proposal-revision-2", "primary", COM + "save_proposal_revision", {**company, "proposal_id": first["proposal"]["id"], "expected_revision": 1,
            "expected_native_fingerprint": first["revision"]["native_fingerprint"], "composition": composition})
        require(first["revision"]["pricing"]["total"] == "600.00" and second["revision"]["pricing"]["total"] == "750.00", "Saved proposal revisions must preserve the authored USD600/750 pricing")
        self.state["records"]["proposal"] = {"id": first["proposal"]["id"], "first": first["revision"]["id"], "second": second["revision"]["id"]}
        self.persist()
        self.proposal_readback()
        return self.state["records"]["proposal"]

    def proposal_readback(self):
        records = self.state["records"]["proposal"]
        for role in ("primary", "reviewer"):
            for key, total in (("first", "600.00"), ("second", "750.00")):
                value = self.clients[role].api(COM + "proposal_revision", {"company": self.scope["company"], "revision_id": records[key]})
                require(value["pricing"]["total"] == total and value["native"]["docstatus"] == 0, "Original proposal revision must reopen with its exact draft pricing")
        return records

    def engineering(self):
        reference = self.fixture["source"]["citation"]
        rfi = self.command("rfi-create", "primary", ENG + "create_rfi", {**self.scope, "definition": {
            "subject": "Synthetic trial basis " + self.state["run_id"], "question": "Confirm the exact cited basis for this internal trial.",
            "responsible_users": [self.fixture["users"]["reviewer"]["user"]], "due_date": None, "location": "Local trial", "contract_citation_ids": []}, "source_citations": [reference], "drawing_references": []})
        response = self.command("rfi-response", "primary", ENG + "create_response", {**self.scope, "rfi_id": rfi["rfi"]["id"], "source_revision": rfi["revision"]["id"],
            "expected_version": digest(rfi["rfi"]), "definition": {"answer": "Use this exact source for the synthetic internal trial only.", "potential_cost_impact": "Separate commercial decision required.", "potential_schedule_impact": ""}, "source_citations": []})["response"]
        official = self.authorize("rfi", "engineering.rfi.authorize.v1", response, "official_response", deny_alias=True)
        transmittal = self.command("transmittal-create", "primary", ENG + "create_transmittal", {**self.scope, "subject_kind": "official_response", "subject_id": official["id"], "subject_digest": digest(official),
            "recipients": [self.fixture["users"]["reviewer"]["user"]], "purpose": "Synthetic internal trial coordination", "required_response": "Review during the human trial"})["transmittal"]
        receipt = self.authorize("transmittal", "engineering.distribute.v1", transmittal, "distribution")
        require(receipt["external_delivery"] is False and receipt["channel"] == "internal", "Only a local internal distribution receipt is permitted")
        self.state["records"]["engineering"] = {"rfi": rfi["rfi"]["id"], "official_response": official["id"], "transmittal": transmittal["id"], "distribution": receipt["id"], "package_digest": transmittal["package_digest"]}
        self.persist()
        self.engineering_readback()
        return self.state["records"]["engineering"]

    def authorize(self, label, action, subject, effect_kind, deny_alias=False):
        packet = self.command(label + "-request", "primary", APPROVAL + "request_action", {**self.scope, "action": action, "subject_id": subject["id"], "expected_version": digest(subject)})["packet"]
        basis = {**self.scope, "packet_id": packet["id"], "manifest_hash": packet["manifest_hash"]}
        if deny_alias:
            denied = self.command(label + "-alias-denial", "alias", APPROVAL + "decide_packet", {**basis, "decision": "Grant", "reason": "Alias separation verification"}, (403,))
            require(denied["code"] in {"independent_review_required", "independent_engineering_required"}, "Alias must fail because it is the author/requester canonical person")
        self.clients["reviewer"].api(APPROVAL + "read_packet", {**self.scope, "packet_id": packet["id"]})
        self.command(label + "-grant", "reviewer", APPROVAL + "decide_packet", {**basis, "decision": "Grant", "reason": "Reviewed exact synthetic source and internal effect"})
        result = self.command(label + "-execute", "primary", APPROVAL + "execute_packet", basis)
        return result["effect"][effect_kind]

    def engineering_readback(self):
        records = self.state["records"]["engineering"]
        for role in ("primary", "reviewer"):
            receipt = self.clients[role].api(ENG + "get_record", {**self.scope, "kind": "distribution", "record_id": records["distribution"]})["record"]
            require(receipt["package_digest"] == records["package_digest"] and receipt["external_delivery"] is False, "Internal receipt must reopen against the exact original package")
        return records

    def run(self):
        try:
            self.check("actual cookie authentication and person separation", self.authenticate)
            if self.args.phase == "journey":
                for name, callback in (("Project/Task persistence, replay and denied access", self.tasks_and_denials),
                    ("original stored document bytes", self.source_bytes), ("estimate immutable USD600 to USD750 revisions", self.estimates),
                    ("proposal immutable USD600 to USD750 drafts", self.proposals), ("independent RFI authorization and internal transmittal receipt", self.engineering)):
                    self.check(name, callback)
            else:
                for name, callback in (("same Task after restart", self.task_readback), ("same source bytes after restart", self.source_bytes),
                    ("same estimate predecessors after restart", self.estimate_readback), ("same proposal predecessors after restart", self.proposal_readback),
                    ("same internal receipt after restart", self.engineering_readback)):
                    self.check(name, callback)
            self.report["status"] = "passed"
        except Exception as error:
            detail = str(error) if isinstance(error, CheckFailure) else type(error).__name__
            self.report["status"] = "failed"
            self.report["checks"].append({"check": self.report.get("active_check"), "status": "failed", "detail": detail})
            print("FAIL " + str(self.report.get("active_check")) + ": " + detail, flush=True)
        finally:
            self.report["records"] = self.state["records"]
            self.report["observations"] = {role: client.observations for role, client in self.clients.items()}
            self.report.pop("active_check", None)
            if self.state.get("recovery"):
                source = Path(self.state["recovery"]["source_state"])
                unchanged = source.exists() and hashlib.sha256(source.read_bytes()).hexdigest() == self.state["recovery"]["source_state_sha256"]
                self.report["recovery_source_unchanged"] = unchanged
                if not unchanged:
                    self.report["status"] = "failed"
                    self.report["checks"].append({"check": "original recovery-source preservation", "status": "failed", "detail": "Original source state changed during readback"})
            write_json(self.args.output, self.report)
        return 0 if self.report["status"] == "passed" else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, required=True, help="Nonsecret cipher-local-trial-v1.json seed manifest")
    parser.add_argument("--base-url", default="http://127.0.0.1:18890")
    parser.add_argument("--host-header", default="cipher.localhost")
    parser.add_argument("--output", type=Path, required=True, help="New local report path; adjacent state preserves original UUIDs")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--phase", choices=("journey", "readback"), default="journey")
    parser.add_argument("--recovery-source-state", type=Path, help="Read-only original trial state; new output and an exact restored Host are required")
    args = parser.parse_args(argv)
    try:
        return TrialVerifier(args).run()
    except Exception as error:
        print("Local trial verifier refused setup: " + (str(error) if isinstance(error, CheckFailure) else type(error).__name__), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

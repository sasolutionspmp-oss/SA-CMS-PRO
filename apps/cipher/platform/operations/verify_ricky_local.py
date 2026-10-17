#!/usr/bin/env python3
"""Opt-in real HTTP/Ollama journey on the explicitly synthetic local app.

No fixture model, site setup, worker startup or direct database access. The
adjacent state journals original UUIDs/payloads before POST; --resume never
substitutes a new logical run/proposal/Task after an uncertain result. Prepare
stops at the saved proposal packet. Save applies that exact draft through the
ordinary authenticated commit_proposal service. Readback makes no business POST.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import socket
import threading
import time
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPCookieProcessor, HTTPHandler, HTTPRedirectHandler, ProxyHandler, Request, build_opener
from uuid import uuid4

from verify_r0 import CheckFailure, Client, require
from verify_local_trial import digest, write_json


RICKY = "cipher_aec.ricky.api."
DOC = "cipher_aec.documents.api."
MAX_HTTP_BYTES = 524288
MAX_REPORT_BYTES = 2097152
HTTP_TIMEOUT_SECONDS = 15
POST_ROUTES = {RICKY + "start_run", RICKY + "commit_proposal"}
FINAL = {"succeeded", "waiting-for-review", "failed", "cancelled"}


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, newurl):
        return None


class DeadlineConnection(http.client.HTTPConnection):
    """Bound response headers and bodies even if a local server drips bytes."""
    def connect(self):
        super().connect()
        self._deadline_socket = self.sock
        def expire():
            try:
                self._deadline_socket.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        self._deadline_timer = threading.Timer(HTTP_TIMEOUT_SECONDS, expire)
        self._deadline_timer.daemon = True
        self._deadline_timer.start()

    def getresponse(self):
        try:
            response = super().getresponse()
        except BaseException:
            if hasattr(self, "_deadline_timer"):
                self._deadline_timer.cancel()
            raise
        response._cipher_deadline_timer = self._deadline_timer
        return response


class LocalHTTPHandler(HTTPHandler):
    def http_open(self, request):
        return self.do_open(DeadlineConnection, request)


class BoundedClient(Client):
    """Reuse the reviewed envelope/session client with bounded response reads."""
    def __init__(self, base_url, host_header=None):
        super().__init__(base_url, host_header)
        self.opener = build_opener(ProxyHandler({}), NoRedirect(), LocalHTTPHandler(), HTTPCookieProcessor(self.cookies))

    def request(self, method, path, values=None, *, operation=None, expected=None):
        headers = {"Accept": "application/json"}
        if self.host_header:
            headers["Host"] = self.host_header
        if self.csrf:
            headers["X-Frappe-CSRF-Token"] = self.csrf
        if operation:
            headers["Idempotency-Key"] = operation
        body = None
        if method == "GET" and values:
            path += "?" + urlencode(values)
        elif values is not None:
            body = json.dumps(values, allow_nan=False).encode()
            require(len(body) <= 65536, "HTTP command exceeds the verifier request limit")
            headers["Content-Type"] = "application/json"
        started = time.monotonic()
        try:
            response = self.opener.open(Request(self.base + path, data=body, method=method, headers=headers), timeout=HTTP_TIMEOUT_SECONDS)
        except HTTPError as error:
            response = error
        timer = getattr(response, "_cipher_deadline_timer", None) or getattr(getattr(response, "fp", None), "_cipher_deadline_timer", None)
        try:
            with response:
                length = response.headers.get("Content-Length")
                require(length is None or (len(length) <= 12 and length.isascii() and length.isdecimal()
                    and int(length) <= MAX_HTTP_BYTES), "HTTP response has invalid or oversized framing")
                raw = response.read(MAX_HTTP_BYTES + 1)
                require(len(raw) <= MAX_HTTP_BYTES, "HTTP response exceeds the verifier byte limit")
                require(length is None or len(raw) == int(length), "HTTP response ended before its declared byte length")
                status, response_headers = response.code, response.headers
                media = response.headers.get("Content-Type", "").split(";", 1)[0]
        finally:
            if timer is not None:
                timer.cancel()
        payload = None
        if media == "application/json":
            try:
                payload = json.loads(raw)
            except (ValueError, UnicodeError):
                raise CheckFailure("HTTP response declared JSON but was invalid") from None
        self.observations.append({"method": method, "route": path.split("?", 1)[0], "status": status,
                                  "media_type": media, "elapsed_ms": round((time.monotonic() - started) * 1000, 2)})
        if expected is not None:
            require(status in expected, f"{method} {path.split('?', 1)[0]}: expected {expected}, got {status}")
        return status, payload, raw, response_headers


def question_keywords(question):
    # This mirrors the current reviewed Project engine; a preflight must prove
    # retrieval from the real service before a costly model request is started.
    stops = frozenset("a an and are as at be been by can could did do does for from had has have how i in is it me my of on or our please should tell that the their them there these they this to us was we were what when where which who why will with would you your".split())
    intent = re.match(
        r"^\s*(?:please\s+|(?:can|could|would)\s+you\s+(?:please\s+)?)?"
        r"(?:(?:create|draft|propose)\s+(?:a\s+)?task\s+(?:to\s+(?:review|check|confirm|inspect)|about|for|regarding)\s+"
        r"|task\s+(?:about|for|regarding)\s+)(.*)$", question, flags=re.IGNORECASE | re.DOTALL)
    topic = intent.group(1) if intent else question
    words = [word for word in re.findall(r"[\w-]+", topic, flags=re.UNICODE) if word.casefold() not in stops]
    if intent and not words:
        words = [word for word in re.findall(r"[\w-]+", question, flags=re.UNICODE) if word.casefold() not in stops]
    return " ".join(dict.fromkeys(words))[:500] or question[:500]


class RickyVerifier:
    def __init__(self, args):
        self.args = args
        require(1 <= args.poll_seconds <= 10 and 30 <= args.poll_timeout <= 360, "Choose bounded polling (1-10 seconds, 30-360 seconds total)")
        self.fixture = json.loads(args.fixture.read_text(encoding="utf-8"))
        require(self.fixture.get("schema") == "cipher.local-trial.v1" and self.fixture.get("site_mode") == "synthetic", "Use the nonsecret synthetic local-trial manifest")
        parsed = urlsplit(args.base_url)
        allowed_hosts = {"127.0.0.1", "localhost", "cipher-trial.localhost", "cipher-integration.localhost"}
        require(parsed.scheme == "http" and parsed.hostname in allowed_hosts and parsed.port is not None,
                "Only the explicitly selected local synthetic HTTP origin is admitted")
        require(not parsed.username and not parsed.password and parsed.path in {"", "/"} and not parsed.query and not parsed.fragment,
                "Use a local origin without credentials, path, query or fragment")
        require(args.host_header in {"cipher.localhost", "cipher-trial.localhost", "cipher-integration.localhost"}, "Choose the explicit local synthetic site Host")
        self.scope = {"company": self.fixture["company"], "project": self.fixture["project"]}
        require(type(self.fixture.get("source", {}).get("citation")) is dict, "The manifest must pin the existing synthetic source citation")
        self.state_path = args.output.with_suffix(args.output.suffix + ".state.json")
        if args.resume or args.phase in {"save", "readback", "authority-denial"}:
            self.state = json.loads(self.state_path.read_text(encoding="utf-8"))
            require(self.state.get("schema") == "cipher.ricky-local.state.v1" and self.state.get("fixture_digest") == digest(self.fixture), "Resume the exact original fixture and Ricky journal")
            require(self.state.get("origin") == args.base_url and self.state.get("host") == args.host_header, "Resume the exact original HTTP origin and site Host")
        else:
            require(not args.output.exists() and not self.state_path.exists(), "Use a new report or explicitly resume the original journal")
            configuration = self.fixture.get("ricky", {})
            self.state = {"schema": "cipher.ricky-local.state.v1", "fixture_digest": digest(self.fixture),
                "origin": args.base_url, "host": args.host_header, "run_id": str(uuid4()), "commands": {}, "records": {},
                "questions": {"answer": args.answer_question or configuration.get("answer_question") or "What is trial labor rate?",
                    "proposal": args.proposal_question or configuration.get("proposal_question") or "Please propose a Task to review the trial labor rate."}}
        for key, override in (("answer", args.answer_question), ("proposal", args.proposal_question)):
            require(not override or override == self.state["questions"][key], "Resume original questions; never substitute a new run after an uncertain result")
            require(type(self.state["questions"][key]) is str and 1 <= len(self.state["questions"][key]) <= 2000, "Ricky questions must fit the reviewed request contract")
        self.clients = {}
        self.report = {"schema": "cipher.ricky-local.http.v1", "phase": args.phase, "run_id": self.state["run_id"],
            "scope": self.scope, "origin": args.base_url, "host": args.host_header, "status": "running",
            "credentials_recorded": False, "checks": [], "limits": ["Actual synthetic local HTTP/model qualification only.",
            "No site setup, dynamic adapter, model simulator, CAD, financial, award or external-delivery operation.",
            "Task draft saving uses the original authenticated person's ordinary service; no approval grant is automated."]}
        self.persist()

    def persist(self):
        require(len(json.dumps(self.state, ensure_ascii=False).encode()) <= MAX_REPORT_BYTES, "The operation journal exceeds its reviewed size limit")
        write_json(self.state_path, self.state)

    def check(self, name, callback):
        self.report["active_check"] = name
        write_json(self.args.output, self.report)
        detail = callback()
        self.report["checks"].append({"check": name, "status": "passed", "detail": detail})
        print("PASS " + name, flush=True)

    def intent(self, label, role, route, payload, expected=(200,)):
        require(self.args.phase in {"journey", "prepare", "save"} and route in POST_ROUTES, "This phase/route cannot issue business POSTs")
        saved = self.state["commands"].get(label)
        if saved is None:
            saved = {"role": role, "route": route, "payload": {**deepcopy(payload), "operation_id": str(uuid4())},
                     "expected": list(expected), "status": "intent"}
            self.state["commands"][label] = saved
            self.persist()  # UUID and exact payload become durable BEFORE POST.
        original = {key: value for key, value in saved["payload"].items() if key != "operation_id"}
        require(saved["role"] == role and saved["route"] == route and saved["expected"] == list(expected)
                and digest(original) == digest(payload), "Resume the original exact command intent")
        return saved

    def command(self, label, role, route, payload, *, replay=False):
        saved = self.intent(label, role, route, payload)
        if saved["status"] == "returned" and not replay:
            return deepcopy(saved["result"])
        result = self.clients[role].api(route, saved["payload"], method="POST", operation=saved["payload"]["operation_id"])
        if saved["status"] == "returned":
            require(digest(result) == digest(saved["result"]), "An exact proposal retry must return the original Task receipt")
        else:
            saved.update(status="returned", result=result)
            self.persist()
        return result

    def authenticate(self):
        for role in ("primary", "alias", "reviewer", "outsider"):
            details = self.fixture["users"][role]
            password = os.environ.get("CIPHER_TRIAL_" + role.upper() + "_PASSWORD") or os.environ.get("CIPHER_FIXTURE_PASSWORD")
            require(bool(password), "Supply credentials through the private process environment")
            client = BoundedClient(self.args.base_url, self.args.host_header)
            client.login({"user": details["user"], "password": password})
            session = client.api("session")
            require(session.get("site_mode") == "synthetic" and session.get("user") == details["user"]
                    and session.get("person", {}).get("id") == details["person"], "Authenticate the exact seeded synthetic person before any command")
            require(type(session.get("csrf_token")) is str and session["csrf_token"], "An actual session and CSRF token are required")
            client.csrf = session["csrf_token"]
            self.clients[role] = client
        users = self.fixture["users"]
        require(users["primary"]["person"] == users["alias"]["person"] != users["outsider"]["person"], "Verify alias person equivalence and outsider separation")
        return {"cookie_sessions": 4, "credentials_in_report": False}

    def source(self):
        reference = self.fixture["source"]["citation"]
        citation = self.clients["primary"].api(DOC + "get_citation", {"company": self.scope["company"],
            **{key: reference[key] for key in ("revision_id", "page", "excerpt_sha256")}})
        for key in ("revision_id", "page", "excerpt_sha256", "source_sha256"):
            require(citation.get(key) == reference[key], "The current source differs from the pinned synthetic fixture")
        require(citation.get("document_id") == self.fixture["source"]["document"], "The source belongs to a different fixture document")
        require(hashlib.sha256(citation["excerpt"].encode()).hexdigest() == citation["excerpt_sha256"], "The source excerpt checksum does not match")
        citation["citation_id"] = digest({key: citation[key] for key in ("revision_id", "page", "excerpt_sha256")})
        _, _, content, _ = self.clients["primary"].request("GET", "/api/method/" + DOC + "download_revision",
            {"company": self.scope["company"], "revision_id": reference["revision_id"]}, expected=(200,))
        require(hashlib.sha256(content).hexdigest() == reference["source_sha256"], "Original source bytes do not match the fixture")
        if "source" in self.state:
            require(digest(citation) == digest(self.state["source"]), "The original source packet changed during resume/readback")
        else:
            self.state["source"] = citation
            self.persist()
        return {"document_id": citation["document_id"], "revision_id": citation["revision_id"],
                "source_sha256": citation["source_sha256"], "citation_id": citation["citation_id"], "excerpt": citation["excerpt"]}

    def readiness(self):
        project = self.clients["primary"].api("project", self.scope)
        require({"ricky.run", "document.read", "task.create"} <= set(project.get("capabilities", [])), "The primary person requires current Project Ricky/document/Task duties")
        status = self.clients["primary"].api(RICKY + "connection_status")
        require(status.get("available") is True and status.get("adapter_kind") == "ollama-local-v1"
                and status.get("cloud_fallback") is False, "The real existing local Ollama adapter is unavailable; no fixture replacement is permitted")
        require(type(status.get("model")) is str and re.fullmatch(r"[0-9a-f]{64}", status.get("model_digest", "")), "The real connection must expose its pinned serving identity")
        model = {"name": status["model"], "digest": status["model_digest"]}
        if "model" in self.state:
            require(self.state["model"] == model, "The selected model identity changed during the original journey")
        else:
            self.state["model"] = model
        for kind, question in self.state["questions"].items():
            rows = self.clients["primary"].api(DOC + "search_documents", {**self.scope, "query": question_keywords(question), "limit": 8})["items"]
            require(any(row.get("revision_id") == self.state["source"]["revision_id"] and row.get("excerpt_sha256") == self.state["source"]["excerpt_sha256"] for row in rows),
                    "The actual " + kind + " question cannot retrieve the exact synthetic source; correct the reviewed retrieval/source setup before starting a run")
        if "tasks_before" not in self.state:
            self.state["tasks_before"] = sorted(self.task_ids())
        self.persist()
        return {"adapter_kind": status["adapter_kind"], "model": model, "source_preflight": "exact actual searches passed"}

    def task_ids(self):
        found, cursor, cursors = [], None, set()
        for _ in range(20):
            page = self.clients["primary"].api("tasks", {**self.scope, "limit": 100, **({"cursor": cursor} if cursor else {})})
            found.extend(row["id"] for row in page["items"])
            cursor = page.get("next_cursor")
            if not cursor:
                require(len(found) == len(set(found)), "Task pagination repeated a native record")
                return set(found)
            require(cursor not in cursors, "Task pagination repeated a cursor")
            cursors.add(cursor)
        raise CheckFailure("Task pagination exceeded its bounded verification budget")

    def complete_run(self, kind):
        started = self.command("start-" + kind, "primary", RICKY + "start_run", {**self.scope, "question": self.state["questions"][kind]})
        identifier = started["id"]
        existing = self.state["records"].get(kind + "_run")
        require(existing is None or existing == identifier, "The original operation resolved to a different run")
        self.state["records"][kind + "_run"] = identifier
        self.persist()
        deadline, polls = time.monotonic() + self.args.poll_timeout, 0
        while True:
            run = self.clients["primary"].api(RICKY + "get_run", {"run_id": identifier})
            polls += 1
            self.state["records"][kind + "_last_status"] = run["status"]
            self.persist()
            if polls == 1 or polls % 10 == 0 or run["status"] in FINAL:
                print(kind + " run " + identifier + ": " + run["status"], flush=True)
            if run["status"] in FINAL:
                break
            require(time.monotonic() < deadline and polls < 180, "Polling budget ended; resume this exact journal/run without starting a replacement")
            time.sleep(min(self.args.poll_seconds, max(0.01, deadline - time.monotonic())))
        self.validate_run(run)
        if kind == "answer":
            require(run["status"] == "succeeded" and not run["proposal_ids"], "The answer-only run must finish without a proposed change")
            if self.state["questions"][kind] == "What is trial labor rate?":
                match = re.search(r"Trial labor rate:\s*USD\s+([0-9]+\.[0-9]{2})", self.state["source"]["excerpt"])
                require(match is not None, "The known synthetic rate question requires its actual rate statement in the source")
                amounts = [Decimal(value.replace(",", "")) for value in re.findall(r"\b[0-9][0-9,]*(?:\.[0-9]+)?\b", run["answer"])]
                require(Decimal(match.group(1)) in amounts, "The actual cited answer does not contain the rate declared by its exact source")
        else:
            require(run["status"] == "waiting-for-review" and len(run["proposal_ids"]) == 1, "The separate model run must prepare exactly one reviewable Task proposal")
            self.state["records"]["proposal"] = run["proposal_ids"][0]
        events = self.clients["primary"].api(RICKY + "run_events", {"run_id": identifier})["items"]
        require(type(events) is list and len(events) <= 64 and all(any(event.get("tool_name") == tool and event.get("status") == "succeeded" for event in events)
            for tool in ("project.lookup", "document.search")), "The actual worker's persisted retrieval steps are missing")
        if kind == "proposal":
            require(sum(event.get("tool_name") == "task.propose" and event.get("status") == "succeeded" for event in events) == 1,
                    "The actual worker must record exactly one successful Task preparation step")
        self.state["records"][kind + "_events"] = events
        self.state["records"][kind + "_result"] = run
        self.persist()
        return run

    def validate_run(self, run):
        require(run.get("status") in {"succeeded", "waiting-for-review"}, "The actual model run did not succeed: " + str((run.get("error") or {}).get("code", run.get("status"))))
        require(run.get("company") == self.scope["company"] and run.get("project") == self.scope["project"], "The persisted run has a different scope")
        require(type(run.get("answer")) is str and 0 < len(run["answer"]) <= 12000, "The persisted model answer is missing or oversized")
        expected = self.state["model"]["name"] + "@sha256:" + self.state["model"]["digest"]
        metadata = run.get("model", {})
        require(metadata.get("version") == expected, "The persisted answer does not record the exact real serving identity")
        require(re.fullmatch(r"[0-9a-f]{64}", metadata.get("profile_fingerprint", "")) and metadata.get("prompt_version"), "The persisted model profile/prompt metadata is missing")
        sampling = metadata.get("sampling", run.get("sampling"))
        if sampling is None:
            self.report["sampling_readback"] = "not-exposed-http; separate root native read audit required"
        else:
            require(type(sampling) is dict and all(key in sampling for key in ("temperature", "num_ctx", "num_predict", "num_thread")), "Persisted sampling metadata is malformed")
            self.report.setdefault("sampling", {})[run["id"]] = sampling
        source = self.state["source"]
        citations = run.get("citations", [])
        require(1 <= len(citations) <= 8 and any(citation.get("citation_id") == source["citation_id"] for citation in citations), "The persisted answer must cite the exact source packet")
        for citation in citations:
            require(all(citation.get(key) == source.get(key) for key in ("citation_id", "document_id", "revision_id", "page", "source_sha256", "excerpt_sha256", "excerpt")),
                    "The model answer used a source outside the exact declared synthetic fixture")

    def proposal_packet(self):
        proposal = self.clients["primary"].api(RICKY + "get_proposal", {"proposal_id": self.state["records"]["proposal"]})
        require(proposal["run_id"] == self.state["records"]["proposal_run"] and proposal["version"] == 1
                and proposal["status"] in {"proposed", "applied"}, "The exact saved proposal is not reviewable")
        require(set(proposal["fields"]) == {"subject", "description"} and proposal["fields"]["subject"].strip(), "The proposal is not an ordinary Task draft")
        require(any(source.get("citation_id") == self.state["source"]["citation_id"] for source in proposal["sources"]), "Task proposal must bind the exact source")
        original = self.state["records"].get("proposal_packet")
        immutable = {key: proposal[key] for key in ("id", "run_id", "version", "fields", "sources", "content_digest", "expires_at")}
        require(original is None or digest(immutable) == digest(original), "The original reviewed proposal packet changed")
        self.state["records"]["proposal_packet"] = immutable
        self.persist()
        return {**immutable, "status": proposal["status"]}

    def identity_denials(self):
        run_id = self.state["records"]["proposal_run"]
        proposal_id = self.state["records"]["proposal"]
        for role in ("alias", "outsider"):
            for route, payload in ((RICKY + "get_run", {"run_id": run_id}), (RICKY + "get_proposal", {"proposal_id": proposal_id})):
                denied = self.clients[role].api(route, payload, expected=(403, 404))
                require(denied["code"] in {"not_found", "capability_denied"}, "A different login must not read the original private Ricky record")
        self.clients["outsider"].api("tasks", self.scope, expected=(404,))
        return {"alias_private_read": "denied despite same canonical person", "outsider_read": "denied"}

    def save_task(self):
        packet = self.proposal_packet()
        payload = {"proposal_id": packet["id"], "proposal_version": packet["version"]}
        saved = self.intent("save-task", "primary", RICKY + "commit_proposal", payload)
        # Reuse the original intended operation for the alias denial. It cannot
        # mint another Task or replace the requesting login's active session.
        denied = self.clients["alias"].api(RICKY + "commit_proposal", saved["payload"], method="POST",
            operation=saved["payload"]["operation_id"], expected=(404,))
        require(denied["code"] == "not_found", "The alias cannot save the requesting login's proposal")
        receipt = self.command("save-task", "primary", RICKY + "commit_proposal", payload)
        replay = self.command("save-task", "primary", RICKY + "commit_proposal", payload, replay=True)
        require(receipt["task"]["id"] == replay["task"]["id"], "Exact retry produced another native Task")
        self.state["records"]["task"] = receipt["task"]["id"]
        self.state["records"]["task_receipt"] = receipt
        self.persist()
        return self.task_readback()

    def task_readback(self):
        records = self.state["records"]
        task = self.clients["primary"].api("task", {**self.scope, "task": records["task"]})
        fields = records["proposal_packet"]["fields"]
        require(task["id"] == records["task"] and task["status"] == "Open" and all(task[key] == fields[key] for key in ("subject", "description")), "Native Task must reopen with the exact saved draft fields")
        created = self.task_ids() - set(self.state["tasks_before"])
        require(created == {records["task"]}, "Exactly one native Task must exist beyond the original bounded baseline")
        proposal = self.clients["primary"].api(RICKY + "get_proposal", {"proposal_id": records["proposal"]})
        require(proposal["status"] == "applied" and proposal["receipt"] == records["task_receipt"], "Saved proposal must retain its original Task effect receipt")
        return {"task": task["id"], "status": task["status"], "new_task_count": 1, "operation_id": records["task_receipt"]["operation"]["id"]}

    def readback(self):
        for kind in ("answer", "proposal"):
            run = self.clients["primary"].api(RICKY + "get_run", {"run_id": self.state["records"][kind + "_run"]})
            self.validate_run(run)
            original = self.state["records"][kind + "_result"]
            require(all(run[key] == original[key] for key in ("id", "answer", "citations", "model", "proposal_ids")), "Saved run content changed after restart")
        self.proposal_packet()
        return self.task_readback()

    def authority_denial(self):
        # Root may run this GET-only phase after independently revoking a duty.
        # This script never grants/revokes or fabricates a current authority.
        for route, payload in ((RICKY + "get_run", {"run_id": self.state["records"]["proposal_run"]}),
                               (RICKY + "get_proposal", {"proposal_id": self.state["records"]["proposal"]})):
            denied = self.clients["primary"].api(route, payload, expected=(403, 404, 412))
            require(denied["code"] in {"not_found", "capability_denied", "stale_authority"}, "Current revoked authority must deny the original Ricky record")
        return "Original records denied by current access; root owns any duty change and restoration."

    def run(self):
        try:
            self.check("actual authenticated synthetic sessions", self.authenticate)
            if self.args.phase == "authority-denial":
                self.check("current authority denial", self.authority_denial)
            else:
                self.check("exact current source and original bytes", self.source)
                if self.args.phase in {"journey", "prepare"}:
                    self.check("real adapter and exact-source retrieval preflight", self.readiness)
                    self.check("persisted real-model cited answer", lambda: self.complete_run("answer"))
                    self.check("separate real-model Task proposal", lambda: self.complete_run("proposal"))
                    self.check("exact reviewable proposal packet", self.proposal_packet)
                self.check("private alias/outsider record denials", self.identity_denials)
                if self.args.phase in {"journey", "save"}:
                    self.check("ordinary Task draft save and exact replay", self.save_task)
                elif self.args.phase == "readback":
                    self.check("same durable answer/proposal/Task after restart", self.readback)
            self.report["status"] = "prepared" if self.args.phase == "prepare" else "passed"
        except Exception as error:
            detail = str(error) if isinstance(error, CheckFailure) else type(error).__name__
            self.report["status"] = "failed"
            self.report["checks"].append({"check": self.report.get("active_check"), "status": "failed", "detail": detail})
            print("FAIL " + str(self.report.get("active_check")) + ": " + detail, flush=True)
        finally:
            self.report["records"] = self.state["records"]
            self.report["observations"] = {role: client.observations for role, client in self.clients.items()}
            self.report["finished_at"] = datetime.now(timezone.utc).isoformat()
            self.report.pop("active_check", None)
            require(len(json.dumps(self.report).encode()) <= MAX_REPORT_BYTES, "The evidence report exceeds its reviewed size limit")
            write_json(self.args.output, self.report)
        return 0 if self.report["status"] in {"passed", "prepared"} else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:18890")
    parser.add_argument("--host-header", default="cipher.localhost")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--phase", choices=("prepare", "journey", "save", "readback", "authority-denial"), default="prepare")
    parser.add_argument("--answer-question")
    parser.add_argument("--proposal-question")
    parser.add_argument("--poll-seconds", type=int, default=2)
    parser.add_argument("--poll-timeout", type=int, default=330)
    args = parser.parse_args(argv)
    try:
        return RickyVerifier(args).run()
    except Exception as error:
        print("Ricky verifier refused setup: " + (str(error) if isinstance(error, CheckFailure) else type(error).__name__))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

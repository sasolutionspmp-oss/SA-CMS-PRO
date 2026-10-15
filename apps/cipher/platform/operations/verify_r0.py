#!/usr/bin/env python3
"""Real HTTP acceptance for an explicitly synthetic Cipher Frappe site.

Credentials are read from --fixture and never written to the evidence. This is an
integration procedure, not a replacement server or a model simulator. See --help.
"""
from __future__ import annotations

import argparse
import base64
from concurrent.futures import ThreadPoolExecutor
import hashlib
import http.cookiejar
import json
import platform
import subprocess
import sys
import time
from threading import Barrier
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit
from urllib.parse import quote
from urllib.request import HTTPCookieProcessor, Request, build_opener


class CheckFailure(Exception):
    pass


def require(condition, message):
    if not condition:
        raise CheckFailure(message)


def sha256(value):
    return hashlib.sha256(value).hexdigest()


class Client:
    """One independent cookie jar per real account, with no logged secrets."""
    def __init__(self, base_url, host_header=None):
        self.base = base_url.rstrip("/")
        self.cookies = http.cookiejar.CookieJar()
        self.opener = build_opener(HTTPCookieProcessor(self.cookies))
        self.csrf = None
        self.observations = []
        self.host_header = host_header

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
            headers["Content-Type"] = "application/json"
        request = Request(self.base + path, data=body, method=method, headers=headers)
        started = time.monotonic()
        try:
            response = self.opener.open(request, timeout=40)
        except HTTPError as exc:
            response = exc
        raw = response.read()
        status = response.code
        media = response.headers.get("Content-Type", "").split(";", 1)[0]
        payload = None
        if media == "application/json":
            try:
                payload = json.loads(raw)
            except ValueError as exc:
                raise CheckFailure("HTTP response declared JSON but was invalid") from exc
        # Login body and cookies are deliberately absent from these observations.
        self.observations.append({"method": method, "route": path.split("?", 1)[0],
                                  "status": status, "media_type": media,
                                  "elapsed_ms": round((time.monotonic() - started) * 1000, 2)})
        if response.headers.get("Retry-After"):
            self.observations[-1]["retry_after"] = response.headers["Retry-After"]
        if expected is not None:
            require(status in expected, f"{method} {path.split('?', 1)[0]}: expected {expected}, got {status}")
        return status, payload, raw, response.headers

    def login(self, credentials):
        status, payload, _, _ = self.request("POST", "/api/method/login", {
            "usr": credentials["user"], "pwd": credentials["password"]}, expected=(200,))
        require(payload is not None, "Login did not return JSON")

    def api(self, name, values=None, *, method="GET", expected=(200,), operation=None):
        qualified = name if name.startswith("cipher_aec.") else "cipher_aec.api.v1." + name
        status, payload, _, _ = self.request(method, "/api/method/" + qualified,
                                             values, operation=operation, expected=expected)
        require(isinstance(payload, dict), f"{name}: response must be a JSON object")
        # Normalize the one Frappe transport wrapper; business envelopes stay intact.
        envelope = payload.get("message", payload)
        require(isinstance(envelope, dict), f"{name}: missing Cipher envelope")
        require(not any(key in payload for key in ("exc", "exception", "exc_type")),
                f"{name}: framework exception leaked through product API")
        if status < 400:
            require("data" in envelope, f"{name}: missing data")
        else:
            error = envelope.get("error")
            require(isinstance(error, dict) and isinstance(error.get("code"), str),
                    f"{name}: missing stable error code")
            require(isinstance(error.get("retryable"), bool), f"{name}: missing retryable")
        meta = envelope.get("meta", {})
        require(isinstance(meta, dict) and meta.get("api_version") == "v1",
                f"{name}: missing versioned response metadata")
        require(isinstance(meta.get("server_time"), str), f"{name}: missing server time")
        try:
            instant = datetime.fromisoformat(meta["server_time"].replace("Z", "+00:00"))
        except ValueError as exc:
            raise CheckFailure(f"{name}: server time must be ISO 8601") from exc
        require(instant.utcoffset() == timezone.utc.utcoffset(None), f"{name}: server time must be UTC")
        request_id = meta.get("request_id", envelope.get("request_id"))
        require(isinstance(request_id, str) and bool(request_id), f"{name}: missing request ID")
        self.observations[-1]["request_id"] = request_id
        self.observations[-1]["server_time"] = meta["server_time"]
        self.observations[-1]["envelope_meta"] = bool(meta)
        if status >= 400:
            self.observations[-1]["error_code"] = envelope["error"]["code"]
            return envelope["error"]
        return envelope["data"]


class Verifier:
    def __init__(self, fixture, previous=None, phase="journey"):
        self.fixture = fixture
        self.clients = {}
        self.results = []
        self.state = {}
        self.scope = {"company": fixture["company"], "project": fixture["project"]}
        self.previous = previous
        self.phase = phase

    def check(self, name, action):
        try:
            detail = action()
            self.results.append({"check": name, "status": "passed", "detail": detail})
            print("PASS " + name, flush=True)
        except Exception as exc:
            # Do not dump arbitrary provider/server response content or credentials.
            message = str(exc) if isinstance(exc, CheckFailure) else type(exc).__name__
            self.results.append({"check": name, "status": "failed", "detail": message})
            print("FAIL " + name + ": " + message, flush=True)

    def authenticate(self):
        for role in ("primary", "alias", "outsider"):
            client = Client(self.fixture["base_url"], self.fixture.get("host_header"))
            client.login(self.fixture["users"][role])
            self.clients[role] = client
            session = client.api("session")
            if isinstance(session.get("csrf_token"), str):
                client.csrf = session["csrf_token"]
            self.state[role + "_session"] = session
            mode = session.get("site_mode", session.get("mode"))
            require(mode == "synthetic", f"{role}: site must explicitly identify synthetic mode before mutation")
        primary = self.state["primary_session"]
        alias = self.state["alias_session"]
        def person(value):
            actor = value.get("person", value.get("actor", {}))
            if isinstance(actor, str):
                return actor
            return actor.get("id", actor.get("person_id"))
        require(person(primary) and person(primary) == person(alias),
                "Primary and alias sessions must resolve to one canonical person")
        require(person(primary) != person(self.state["outsider_session"]),
                "Denied user must be an independent person")
        if self.fixture.get("backend_base_url"):
            original = self.clients["outsider"]
            backend = Client(self.fixture["backend_base_url"], self.fixture.get("backend_host_header"))
            backend.cookies = original.cookies
            backend.opener = build_opener(HTTPCookieProcessor(backend.cookies))
            backend.csrf = original.csrf
            backend_session = backend.api("session")
            require(backend_session.get("site_mode") == "synthetic" and person(backend_session) == person(self.state["outsider_session"]),
                    "Direct backend regression route must resolve the same authenticated synthetic outsider")
            self.clients["outsider_backend"] = backend
        self.state["synthetic_verified"] = True
        return "Three authenticated synthetic accounts; two share one canonical person."

    def unauthenticated(self):
        client = Client(self.fixture["base_url"], self.fixture.get("host_header"))
        self.clients["guest"] = client
        client.api("session", expected=(401,))
        return "An unauthenticated session receives a safe, versioned 401 envelope."

    def authorized_project(self):
        data = self.clients["primary"].api("project", self.scope)
        project = data.get("project", data)
        version = project.get("version", project.get("resource_version"))
        require(isinstance(version, str) and version, "Project read must expose opaque version")
        self.state["project_version"] = version
        return {"project": self.scope["project"], "version": version}

    def independent_denial(self):
        listed = self.clients["outsider"].api("projects", {"company": self.scope["company"], "limit": 100, "count_mode": "exact"})
        require(not any(row.get("id") == self.scope["project"] for row in listed.get("items", [])),
                "Project list must not expose the inaccessible project")
        require(listed.get("total") == len(listed.get("items", [])),
                "Project list count must include only the outsider's visible fixture projects")
        for name in ("project", "tasks", "history"):
            self.clients["outsider"].api(name, self.scope, expected=(404,))
        # Native Frappe resources must obey the same record boundary.
        self.clients["outsider"].request("GET", "/api/resource/Project/" + quote(self.scope["project"], safe=""),
                                            expected=(403, 404))
        return "Project, Task list, and history are inaccessible to an independent person."

    def task_retry(self):
        require(self.state.get("synthetic_verified"), "Synthetic identity guard did not pass")
        operation = str(uuid.uuid4())
        subject = "SYNTHETIC R0 acceptance " + operation
        payload = {**self.scope, "operation_id": operation,
                   "expected_version": self.state["project_version"], "subject": subject,
                   "description": "Synthetic HTTP acceptance; no operational project data."}
        client = self.clients["primary"]
        first = client.api("create_task", payload, method="POST", operation=operation)
        retry = client.api("create_task", payload, method="POST", operation=operation)
        alias = self.clients["alias"].api("create_task", payload, method="POST", operation=operation)
        def task_id(data):
            task = data.get("task", {})
            return task.get("id", task.get("name"))
        identifier = task_id(first)
        require(identifier and identifier == task_id(retry) == task_id(alias),
                "Same request and canonical-person alias retry must resolve the same Task")
        require(retry.get("operation", {}).get("replayed") is True,
                "Retry must identify its original durable receipt")
        require(alias.get("operation", {}).get("replayed") is True,
                "Alias retry must replay the canonical person's receipt")
        conflict = {**payload, "subject": subject + " changed"}
        client.api("create_task", conflict, method="POST", operation=operation, expected=(409,))
        listing = client.api("tasks", self.scope)
        rows = listing if isinstance(listing, list) else listing.get("items", listing.get("tasks", []))
        require(sum(row.get("id", row.get("name")) == identifier for row in rows) == 1,
                "Task readback must contain exactly one saved Task after retries/conflict")
        require(sum(row.get("subject") == subject for row in rows) == 1,
                "Task retries must not create extra Tasks with different record IDs")
        require(not any(row.get("subject") == conflict["subject"] for row in rows),
                "Changed-payload conflict must not create a different Task")
        receipt = client.api("operation", {**self.scope, "operation_id": operation})
        require(task_id(receipt) == identifier, "Operation readback must preserve original Task")
        self.state["saved_task"] = {"id": identifier, "operation_id": operation, "subject": subject}
        self.state["retry_payload"] = payload
        self.clients["outsider"].api("operation", {**self.scope, "operation_id": operation}, expected=(404,))
        self.clients["outsider"].request("GET", "/api/resource/Task/" + quote(identifier, safe=""),
                                            expected=(403, 404))
        self.clients["outsider"].request("GET", "/api/method/erpnext.projects.doctype.task.task.make_timesheet",
            {"source_name": identifier, "ignore_permissions": "true"}, expected=(403, 404))
        mapper = {"cmd": "erpnext.projects.doctype.task.task.make_timesheet", "source_name": identifier,
                  "ignore_permissions": "true"}
        self.clients.get("outsider_backend", self.clients["outsider"]).request("GET", "/", mapper, expected=(403, 404))
        self.clients["outsider"].api("session", mapper, expected=(403, 404))
        return self.state["saved_task"]

    def version_checks(self):
        require(self.state.get("synthetic_verified"), "Synthetic identity guard did not pass")
        client = self.clients["primary"]
        base = {**self.scope, "subject": "SYNTHETIC rejected version precondition"}
        current = client.api("project", self.scope)
        require(current.get("version") != self.state["project_version"],
                "Task creation must advance the Project aggregate version")
        for version, expected in ((None, 428), (self.state["project_version"], 412)):
            operation = str(uuid.uuid4())
            payload = {**base, "operation_id": operation}
            if version is not None:
                payload["expected_version"] = version
            client.api("create_task", payload, method="POST", expected=(expected,), operation=operation)
            client.api("operation", {**self.scope, "operation_id": operation}, expected=(404,))
        listing = client.api("tasks", self.scope)
        rows = listing if isinstance(listing, list) else listing.get("items", listing.get("tasks", []))
        require(not any(row.get("subject") == base["subject"] for row in rows),
                "Rejected version preconditions must not create a Task")
        return "Missing/stale Project preconditions produce no committed command receipt."

    def capabilities(self):
        session = self.clients["primary"].api("session")
        capabilities = session.get("capabilities", {})
        model = self.clients["primary"].api("cipher_aec.ricky.api.connection_status")
        require(isinstance(model.get("available"), bool) and isinstance(model.get("status"), str),
                "Ricky must expose actual adapter availability/status")
        if model["available"] is False:
            require(model.get("status") == "unavailable", "Unavailable model must report unavailable status")
        prior_run = (self.previous or {}).get("saved_run")
        run_operation = prior_run["operation_id"] if prior_run else str(uuid.uuid4())
        run_payload = prior_run["payload"] if prior_run else {
            **self.scope, "question": "What is the synthetic concrete curing period? Cite the source.", "operation_id": run_operation}
        started = self.clients["primary"].api("cipher_aec.ricky.api.start_run", run_payload,
                                              method="POST", operation=run_operation)
        run_id = started.get("id")
        require(isinstance(run_id, str) and run_id, "Authorized Ricky request must persist a run ID")
        run = self.clients["primary"].api("cipher_aec.ricky.api.get_run", {"run_id": run_id})
        self.state["saved_run"] = {"id": run_id, "operation_id": run_operation,
                                    "payload": run_payload, "observed_status": run.get("status")}
        deadline = time.monotonic() + 10
        while run.get("status") in {"queued", "retrieving", "generating", "executing", "reconciling"} and time.monotonic() < deadline:
            time.sleep(0.5)
            run = self.clients["primary"].api("cipher_aec.ricky.api.get_run", {"run_id": run_id})
            self.state["saved_run"]["observed_status"] = run.get("status")
        require(run.get("status") in {"succeeded", "failed", "cancelled", "waiting-for-review"},
                "Actual model run did not reach a terminal/review state within 10 seconds; no successful inference can be claimed")
        receipt = self.clients["primary"].api("operation", {**self.scope, "operation_id": run_operation})
        require(receipt.get("id") == run_id, "Run receipt must resolve the original persisted run")
        if model["available"] is False:
            require(run.get("status") != "succeeded" and not run.get("answer"),
                    "An unavailable adapter must not fabricate a successful answer")
        self.state["saved_run"]["error"] = run.get("error")
        operation = str(uuid.uuid4())
        self.clients["outsider"].api("cipher_aec.ricky.api.start_run",
            {**self.scope, "question": "Synthetic denied project question", "operation_id": operation},
            method="POST", expected=(404,), operation=operation)
        return {"capabilities": capabilities, "model_status": model, "run": self.state["saved_run"],
                "qualification": "Status observation only; no model inference or provider connection claimed."}

    def command_boundary(self):
        client = self.clients["primary"]
        version = client.api("project", self.scope)["version"]
        for kind in ("missing-key", "mismatched-key", "forged-person"):
            operation = str(uuid.uuid4())
            payload = {**self.scope, "subject": "SYNTHETIC denied command boundary",
                       "expected_version": version, "operation_id": operation}
            header, status = operation, 422
            if kind == "missing-key":
                header, status = None, 428
            elif kind == "mismatched-key":
                header, status = str(uuid.uuid4()), 409
            else:
                payload["person_id"] = "CALLER-CANNOT-ASSERT-AUTHORITY"
            client.api("create_task", payload, method="POST", operation=header, expected=(status,))
            client.api("operation", {**self.scope, "operation_id": operation}, expected=(404,))
        return "Missing/mismatched idempotency headers and caller-asserted identity are rejected without receipts."

    def concurrent_commands(self):
        primary, alias = self.clients["primary"], self.clients["alias"]
        version = primary.api("project", self.scope)["version"]
        operation = str(uuid.uuid4())
        payload = {**self.scope, "operation_id": operation, "expected_version": version,
                   "subject": "SYNTHETIC simultaneous same operation " + operation}
        gate = Barrier(2)
        def submit(client, values):
            gate.wait(timeout=10)
            for attempt in range(3):
                result = client.api("create_task", values, method="POST", operation=values["operation_id"], expected=(200, 412, 503))
                if result.get("code") != "concurrent_change":
                    return result
                require(result.get("retryable") is True, "Concurrent transaction refusal must be explicitly retryable")
                retry_after = client.observations[-1].get("retry_after")
                require(retry_after is not None and retry_after.isdigit() and 0 < int(retry_after) <= 5,
                        "Concurrent transaction refusal must provide a bounded Retry-After")
                time.sleep(int(retry_after))
            raise CheckFailure("Concurrent transaction remained unavailable after bounded retries of the original operation")
        with ThreadPoolExecutor(max_workers=2) as pool:
            pending = [pool.submit(submit, client, payload) for client in (primary, alias)]
            same = [future.result() for future in pending]
        ids = [result.get("task", {}).get("id") for result in same]
        require(ids[0] and ids[0] == ids[1], "Concurrent alias submissions of one operation must return the same Task")
        require(sorted(result["operation"]["replayed"] for result in same) == [False, True],
                "Concurrent same operation must have one original effect and one replay")
        version = primary.api("project", self.scope)["version"]
        contenders = [{**self.scope, "operation_id": str(uuid.uuid4()), "expected_version": version,
                       "subject": "SYNTHETIC simultaneous competing operation " + str(uuid.uuid4())} for _ in range(2)]
        with ThreadPoolExecutor(max_workers=2) as pool:
            pending = [pool.submit(submit, client, values) for client, values in zip((primary, alias), contenders)]
            different = [future.result() for future in pending]
        require(sum("task" in result for result in different) == 1 and
                sum(result.get("code") == "stale_version" for result in different) == 1,
                "Concurrent distinct operations with one prior version must have one success and one stale refusal")
        rows = primary.api("tasks", {**self.scope, "limit": 100}).get("items", [])
        require(sum(row.get("subject") == payload["subject"] for row in rows) == 1,
                "Concurrent alias retry must create exactly one Task across distinct record IDs")
        subjects = {values["subject"] for values in contenders}
        require(sum(row.get("subject") in subjects for row in rows) == 1,
                "Concurrent competing versions must commit exactly one Task")
        for values, result in zip(contenders, different):
            if result.get("code") == "stale_version":
                primary.api("operation", {**self.scope, "operation_id": values["operation_id"]}, expected=(404,))
        return "Simultaneous alias retry commits one Task; simultaneous different IDs sharing a prior version commit one Task and reject the other."

    def cursor_boundaries(self):
        client = self.clients["primary"]
        for collection in ("tasks", "history"):
            first = client.api(collection, {**self.scope, "limit": 1})
            if collection == "history":
                at = datetime.fromisoformat(first["items"][0]["at"].replace("Z", "+00:00"))
                server_time = datetime.fromisoformat(client.observations[-1]["server_time"].replace("Z", "+00:00"))
                require(at.utcoffset() == timedelta(0) and at <= server_time + timedelta(seconds=60),
                        "Native Frappe history time must convert to UTC and must not be relabeled hours into the future")
            require(first.get("total") is None and first.get("count_mode") == "none",
                    "Default bounded reads must not silently compute/expose exact totals")
            require(len(first.get("items", [])) == 1 and first.get("next_cursor"),
                    "Known multi-record fixture must provide a bounded first page and continuation")
            cursor = first["next_cursor"]
            second = client.api(collection, {**self.scope, "limit": 1, "cursor": cursor})
            require(len(second.get("items", [])) == 1 and first["items"][0]["id"] != second["items"][0]["id"],
                    "Signed keyset continuation must return a different next record")
            tampered = ("A" if cursor[0] != "A" else "B") + cursor[1:]
            client.api(collection, {**self.scope, "limit": 1, "cursor": tampered}, expected=(422,))
            self.clients["alias"].api(collection, {**self.scope, "limit": 1, "cursor": cursor}, expected=(422,))
            other = "history" if collection == "tasks" else "tasks"
            client.api(other, {**self.scope, "limit": 1, "cursor": cursor}, expected=(422,))
            client.api(collection, {**self.scope, "limit": 201}, expected=(422,))
        return "Task/history pages are bounded, default totals omitted, and tampered/cross-user/cross-collection cursors rejected."

    def document_journey(self):
        client = self.clients["primary"]
        outsider = self.clients["outsider"]
        prefix = "cipher_aec.documents.api."
        operation = str(uuid.uuid4())
        first_page = "SYNTHETIC R0 source " + operation + "\nInspection station: 42+75.\n"
        second_page = "SYNTHETIC R0 second page\nConcrete curing period: 7 calendar days.\n"
        content = (first_page + "\f" + second_page).encode()
        payload = {**self.scope, "operation_id": operation, "title": "Synthetic acceptance source " + operation,
                   "filename": "synthetic-r0-source.txt", "content_base64": base64.b64encode(content).decode(),
                   "byte_length": len(content), "sha256": sha256(content)}
        uploaded = client.api(prefix + "upload_document", payload, method="POST", operation=operation)
        document, revision = uploaded["document"], uploaded["revision"]
        require(revision.get("sha256") == sha256(content) and revision.get("byte_length") == len(content),
                "Document revision must bind uploaded original bytes")
        require(revision.get("extraction_status") == "ready" and revision.get("page_count") == 2,
                "Known two-page UTF-8 source must provide two extracted pages")
        require(revision.get("retrieval_status") == "available",
                "Synthetic fixture must explicitly allow its unscanned test source or configure scanning")
        retried = client.api(prefix + "upload_document", payload, method="POST", operation=operation)
        require(retried["revision"]["id"] == revision["id"] and retried.get("operation", {}).get("replayed") is True,
                "Upload retry must not create another source revision")
        client.api(prefix + "upload_document", {**payload, "title": payload["title"] + " changed"},
                   method="POST", operation=operation, expected=(409,))
        detail = client.api(prefix + "get_document", {"company": self.scope["company"], "document_id": document["id"]})
        require(len(detail.get("revisions", [])) == 1, "Upload retry must preserve one registered revision")
        documents = client.api(prefix + "list_documents", self.scope)
        require(sum(row.get("title") == payload["title"] for row in documents.get("items", [])) == 1,
                "Upload retry must not create extra document records under different IDs")
        # Same UUID belongs to the person's Task command across command families.
        if self.state.get("saved_task"):
            conflict_id = self.state["saved_task"]["operation_id"]
            client.api(prefix + "upload_document", {**payload, "operation_id": conflict_id},
                       method="POST", operation=conflict_id, expected=(409,))
        query = {"company": self.scope["company"], "revision_id": revision["id"], "page": 2}
        preview = client.api(prefix + "preview_revision", query)
        require(preview.get("text") == second_page, "Page preview must equal exact extracted known source text")
        citation = client.api(prefix + "get_citation", query)
        require(citation.get("excerpt") == second_page and citation.get("excerpt_sha256") == sha256(second_page.encode())
                and citation.get("source_sha256") == sha256(content),
                "Citation must bind the exact source revision, page excerpt and hashes")
        matches = client.api(prefix + "search_documents", {**self.scope, "query": "curing period"})
        require(any(row.get("revision_id") == revision["id"] and row.get("page") == 2 for row in matches.get("items", [])),
                "Scoped source search must retrieve the known page")
        download_query = {"company": self.scope["company"], "revision_id": revision["id"]}
        _, _, downloaded, headers = client.request("GET", "/api/method/" + prefix + "download_revision",
                                                   download_query, expected=(200,))
        require(downloaded == content, "Downloaded artifact must match the exact uploaded original bytes")
        require("attachment" in headers.get("Content-Disposition", "").lower(),
                "Original source download must be an attachment")
        # Discover the private File through an authorized native read, then probe
        # Frappe's owner shortcuts directly; product-only denial is insufficient.
        _, native_revision, _, _ = client.request("GET", "/api/resource/Cipher%20Document%20Revision/" +
            quote(revision["id"], safe=""), expected=(200,))
        file_id = native_revision.get("data", {}).get("storage_reference")
        require(isinstance(file_id, str) and file_id, "Canonical revision must bind its native private File")
        for user_client in (client, outsider):
            user_client.request("GET", "/api/resource/File/" + quote(file_id, safe=""), expected=(403, 404))
            user_client.request("POST", "/api/method/frappe.core.api.file.zip_files",
                                {"files": json.dumps([file_id])}, expected=(403, 404))
        for route, args in (
            ("list_documents", self.scope),
            ("get_document", {"company": self.scope["company"], "document_id": document["id"]}),
            ("preview_revision", query), ("get_citation", query),
            ("search_documents", {**self.scope, "query": "curing period"}),
            ("download_revision", download_query),
        ):
            outsider.api(prefix + route, args, expected=(404,))
        outsider.request("GET", "/api/resource/Cipher%20Document%20Revision/" + quote(revision["id"], safe=""),
                         expected=(403, 404))
        self.state["saved_document"] = {"document_id": document["id"], "revision_id": revision["id"],
                                         "sha256": sha256(content), "byte_length": len(content),
                                         "scan_status": revision.get("scan_status"),
                                         "retrieval_status": revision.get("retrieval_status"),
                                         "extraction_status": revision.get("extraction_status"),
                                         "operation_id": operation, "page_2_excerpt_sha256": sha256(second_page.encode()),
                                         "upload_payload": payload, "native_file_id": file_id,
                                         "native_private_url_probe": "Actual URL requires separate administrator readback; File metadata RPC is denied."}
        return self.state["saved_document"]

    def persisted_readback(self):
        saved = self.previous["saved_task"]
        payload = self.previous["retry_payload"]
        client = self.clients["primary"]
        receipt = client.api("operation", {**self.scope, "operation_id": saved["operation_id"]})
        require(receipt.get("task", {}).get("id") == saved["id"],
                "Original Task/receipt must remain available after the external restart")
        replay = client.api("create_task", payload, method="POST", operation=saved["operation_id"])
        require(replay.get("task", {}).get("id") == saved["id"] and replay.get("operation", {}).get("replayed") is True,
                "Original logical operation must replay after restart")
        rows = client.api("tasks", self.scope).get("items", [])
        require(sum(row.get("id") == saved["id"] for row in rows) == 1,
                "Restart/retry must preserve exactly one original Task")
        require(sum(row.get("subject") == saved["subject"] for row in rows) == 1,
                "Restart/retry must not create extra Tasks under different record IDs")
        document = self.previous.get("saved_document")
        if document:
            prefix = "cipher_aec.documents.api."
            _, _, content, _ = client.request("GET", "/api/method/" + prefix + "download_revision",
                {"company": self.scope["company"], "revision_id": document["revision_id"]}, expected=(200,))
            require(sha256(content) == document["sha256"] and len(content) == document["byte_length"],
                    "Original artifact bytes must survive the external restart")
            citation = client.api(prefix + "get_citation", {"company": self.scope["company"],
                "revision_id": document["revision_id"], "page": 2})
            require(citation["excerpt_sha256"] == document["page_2_excerpt_sha256"],
                    "Citation/extraction must survive the external restart")
            self.state["saved_document"] = document
        run = self.previous.get("saved_run")
        if run:
            persisted = client.api("cipher_aec.ricky.api.get_run", {"run_id": run["id"]})
            run_receipt = client.api("operation", {**self.scope, "operation_id": run["operation_id"]})
            require(persisted.get("id") == run["id"] and run_receipt.get("id") == run["id"],
                    "The actual queued/failed model run and its receipt must persist across restart")
            self.state["saved_run"] = {**run, "observed_status": persisted.get("status")}
        self.state["saved_task"], self.state["retry_payload"] = saved, payload
        return {"task": saved["id"], "qualification": "Readback after externally performed restart; restart procedure requires separate evidence."}

    def revoked_readback(self):
        saved = self.previous["saved_task"]
        payload = self.previous["retry_payload"]
        for role in ("primary", "alias"):
            client = self.clients[role]
            for route in ("project", "tasks", "history"):
                client.api(route, self.scope, expected=(404,))
            client.api("operation", {**self.scope, "operation_id": saved["operation_id"]}, expected=(404,))
            client.api("create_task", payload, method="POST", operation=saved["operation_id"], expected=(404,))
            changed = {**payload, "operation_id": str(uuid.uuid4())}
            client.api("create_task", changed, method="POST", operation=changed["operation_id"], expected=(404,))
            document = self.previous.get("saved_document")
            if document:
                prefix = "cipher_aec.documents.api."
                arguments = {"company": self.scope["company"], "revision_id": document["revision_id"]}
                client.api(prefix + "get_document", {"company": self.scope["company"],
                           "document_id": document["document_id"]}, expected=(404,))
                client.api(prefix + "get_citation", {**arguments, "page": 2}, expected=(404,))
                client.api(prefix + "download_revision", arguments, expected=(404,))
        return "Current canonical-person duty revocation blocks both account aliases, private original receipts, retries, and new effects."

    def source_revoked(self):
        document = self.previous["saved_document"]
        run = self.previous["saved_run"]
        for role in ("primary", "alias"):
            client = self.clients[role]
            client.api("project", self.scope)
            client.api("tasks", self.scope)
            prefix = "cipher_aec.documents.api."
            args = {"company": self.scope["company"], "revision_id": document["revision_id"]}
            for route, values in (
                ("list_documents", self.scope),
                ("get_document", {"company": self.scope["company"], "document_id": document["document_id"]}),
                ("preview_revision", {**args, "page": 2}), ("get_citation", {**args, "page": 2}),
                ("search_documents", {**self.scope, "query": "curing period"}), ("download_revision", args),
            ):
                client.api(prefix + route, values, expected=(403, 404))
            client.api("operation", {**self.scope, "operation_id": document["operation_id"]}, expected=(403, 404))
            upload = document["upload_payload"]
            client.api(prefix + "upload_document", upload, method="POST", operation=document["operation_id"], expected=(403, 404))
            new_id = str(uuid.uuid4())
            client.api(prefix + "upload_document", {**upload, "operation_id": new_id}, method="POST", operation=new_id, expected=(403, 404))
            client.api("operation", {**self.scope, "operation_id": new_id}, expected=(404,))
            client.api("cipher_aec.ricky.api.get_run", {"run_id": run["id"]}, expected=(403, 404))
            client.api("cipher_aec.ricky.api.run_events", {"run_id": run["id"]}, expected=(403, 404))
            client.api("operation", {**self.scope, "operation_id": run["operation_id"]}, expected=(403, 404))
            client.api("cipher_aec.ricky.api.start_run", run["payload"], method="POST", operation=run["operation_id"], expected=(403, 404))
        return "Project/Task reads remain permitted while both account aliases lose document contents/receipt/replay/new upload and Ricky run/events/receipt/replay."

    def closed_project(self):
        saved, payload = self.previous["saved_task"], self.previous["retry_payload"]
        client = self.clients["primary"]
        project = client.api("project", self.scope)
        require(project.get("status") in ("Completed", "Cancelled"),
                "Closed phase requires an externally closed synthetic Project")
        original = client.api("operation", {**self.scope, "operation_id": saved["operation_id"]})
        require(original.get("task", {}).get("id") == saved["id"], "Closed Project must retain readable original history")
        for role in ("primary", "alias"):
            retry = self.clients[role].api("create_task", payload, method="POST", operation=saved["operation_id"])
            require(retry.get("task", {}).get("id") == saved["id"] and retry.get("operation", {}).get("replayed") is True,
                    "Closed Project retry must replay the original Task without a new effect")
        operation = str(uuid.uuid4())
        denied = client.api("create_task", {**payload, "operation_id": operation, "expected_version": project["version"]},
                            method="POST", operation=operation, expected=(409,))
        require(denied.get("code") == "project_closed", "Fresh command must be refused because the Project is closed")
        client.api("operation", {**self.scope, "operation_id": operation}, expected=(404,))
        rows = client.api("tasks", {**self.scope, "limit": 100}).get("items", [])
        require(sum(row.get("subject") == saved["subject"] for row in rows) == 1,
                "Closed-project retries/new refusal must retain exactly one original Task")
        return "Closed Project preserves original receipt/retry while refusing a fresh Task operation."

    def task_read_only(self):
        client = self.clients["primary"]
        task = self.previous["saved_task"]
        project = client.api("project", self.scope)
        require("task.create" not in project.get("capabilities", []) and "project.read" in project.get("capabilities", []),
                "Task read-only phase requires externally revoked task.create with project.read retained")
        task_path = "/api/resource/Task/" + quote(task["id"], safe="")
        _, before, _, _ = client.request("GET", task_path, expected=(200,))
        todo_args = {"filters": json.dumps([["reference_type", "=", "Task"], ["reference_name", "=", task["id"]]]),
                     "fields": json.dumps(["name", "allocated_to", "status"]), "limit_page_length": 1000}
        client.request("GET", "/api/resource/ToDo", todo_args, expected=(403, 404))
        client.request("POST", "/api/method/frappe.desk.form.assign_to.add",
                       {"doctype": "Task", "name": task["id"], "assign_to": json.dumps([self.fixture["users"]["primary"]["user"]]),
                        "notify": 0, "description": "SYNTHETIC forbidden native assignment"}, expected=(403, 404))
        client.request("GET", "/api/method/erpnext.projects.doctype.task.task.make_timesheet",
                       {"source_name": task["id"], "ignore_permissions": "true"}, expected=(403, 404))
        _, after, _, _ = client.request("GET", task_path, expected=(200,))
        client.request("GET", "/api/resource/ToDo", todo_args, expected=(403, 404))
        require(before["data"].get("_assign") == after["data"].get("_assign") and
                before["data"].get("modified") == after["data"].get("modified"),
                "Denied native assignment must not change Task assignments/version")
        operation = str(uuid.uuid4())
        client.api("create_task", {**self.scope, "operation_id": operation, "expected_version": project["version"],
                   "subject": "SYNTHETIC forbidden reader Task"}, method="POST", operation=operation, expected=(403,))
        client.api("operation", {**self.scope, "operation_id": operation}, expected=(404,))
        return {"observed": "Project reader cannot create Tasks, self-assign through native ToDo, invoke permission-bypassing ERPNext mapper, or enumerate ToDo. Task assignments/version remain unchanged.",
                "limit": "ToDo row-count comparison requires separate Administrator/bench evidence because ordinary users cannot enumerate ToDo."}

    def native_artifact(self):
        document = self.previous["saved_document"]
        artifact = self.fixture.get("native_artifact", {})
        require(artifact.get("revision_id") == document["revision_id"],
                "Native artifact phase requires administrator-supplied URL bound to the saved source revision")
        url = artifact.get("file_url")
        require(isinstance(url, str) and url.startswith("/private/files/") and "?" not in url,
                "Native artifact URL must be an actual private source path")
        for role in ("primary", "outsider"):
            self.clients[role].request("GET", url, expected=(403, 404))
        _, _, content, _ = self.clients["primary"].request("GET",
            "/api/method/cipher_aec.documents.api.download_revision",
            {"company": self.scope["company"], "revision_id": document["revision_id"]}, expected=(200,))
        require(sha256(content) == document["sha256"] and len(content) == document["byte_length"],
                "Governed original-byte download must still match the source while native private routes remain denied")
        return {"revision_id": document["revision_id"], "native_url": url,
                "result": "Actual native private File URL denies original uploader and independent outsider; governed original-byte download still matches its SHA-256."}

    def run(self):
        self.check("unauthenticated API boundary", self.unauthenticated)
        self.check("authenticated canonical-person synthetic boundary", self.authenticate)
        if not self.state.get("synthetic_verified"):
            return
        if self.phase == "readback":
            self.check("durable Task and operation readback", self.persisted_readback)
            return
        if self.phase == "revoked":
            self.check("current permissions before original receipt/retry", self.revoked_readback)
            return
        if self.phase == "source-revoked":
            self.check("source-specific current permissions before private receipts/replay", self.source_revoked)
            return
        if self.phase == "closed":
            self.check("closed-project original replay and fresh-effect refusal", self.closed_project)
            return
        if self.phase == "task-read-only":
            self.check("native assignment and mapper reader boundary", self.task_read_only)
            return
        if self.phase == "native-artifact":
            self.check("actual native private artifact path boundary", self.native_artifact)
            return
        if self.phase == "concurrency":
            self.check("simultaneous command serialization and original-operation recovery", self.concurrent_commands)
            return
        self.check("authorized Project version", self.authorized_project)
        self.check("independent-person scoped denial", self.independent_denial)
        if "project_version" in self.state:
            self.check("Task retry, alias replay, changed-payload conflict and receipt", self.task_retry)
            self.check("missing/stale source preconditions", self.version_checks)
            self.check("command transport and identity boundary", self.command_boundary)
            self.check("simultaneous command serialization", self.concurrent_commands)
            self.check("bounded permission-scoped cursor contract", self.cursor_boundaries)
        self.check("real document bytes, citations, retry and independent denial", self.document_journey)
        self.check("honest capability observation", self.capabilities)


def fingerprint():
    here = Path(__file__).resolve()
    repository = here.parents[4]
    try:
        revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repository, text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        revision = "unavailable"
    app = here.parents[1] / "apps" / "cipher_aec"
    sources = {str(path.relative_to(repository)): sha256(path.read_bytes())
               for path in sorted(app.rglob("*")) if path.is_file() and
               path.suffix in {".py", ".json", ".toml", ".txt"} and "__pycache__" not in path.parts
               and not any(part.endswith(".egg-info") for part in path.parts)}
    sources[str(here.relative_to(repository))] = sha256(here.read_bytes())
    return {"git_revision": revision, "source_sha256": sources, "client_python": platform.python_version()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", required=True, type=Path,
                        help="Local JSON: base_url, fixture_id, company, project, users.{primary,alias,outsider}.{user,password}")
    parser.add_argument("--output", required=True, type=Path, help="Credential-free JSON evidence output")
    parser.add_argument("--phase", choices=("journey", "readback", "revoked", "source-revoked", "closed", "task-read-only", "native-artifact", "concurrency"), default="journey")
    parser.add_argument("--previous", type=Path,
                        help="Successful journey evidence for readback after external restart or duty revocation")
    args = parser.parse_args()
    fixture = json.loads(args.fixture.read_text())
    require(fixture.get("fixture_id"), "Fixture identity is required")
    url = urlsplit(fixture["base_url"])
    require(url.scheme in ("http", "https") and url.hostname and not url.username and not url.password,
            "Use a credential-free HTTP(S) base URL")
    host_header = fixture.get("host_header")
    require(host_header is None or isinstance(host_header, str) and host_header and not any(c.isspace() for c in host_header),
            "Virtual-host routing override must be a plain hostname")
    previous = json.loads(args.previous.read_text()) if args.previous else None
    if args.phase != "journey":
        require(previous and previous.get("saved_task") and previous.get("retry_payload"),
                "Readback/revoked phase requires a successful prior journey evidence file")
        require(previous.get("fixture", {}).get("fixture_id") == fixture["fixture_id"],
                "Previous evidence belongs to another fixture")
        require(previous.get("fixture", {}).get("company") == fixture["company"] and
                previous.get("fixture", {}).get("project") == fixture["project"],
                "Previous evidence belongs to another scope")
        if args.phase == "source-revoked":
            require(previous.get("saved_document", {}).get("upload_payload") and previous.get("saved_run"),
                    "Source revocation requires a preceding saved document and actual persisted Ricky run")
    verifier = Verifier(fixture, previous, args.phase)
    verifier.run()
    evidence = {"executed_at": datetime.now(timezone.utc).isoformat(), **fingerprint(),
                "fixture": {key: fixture[key] for key in ("fixture_id", "base_url", "company", "project")},
                "runtime_versions": fixture.get("runtime_versions", {}),
                "host_header": host_header,
                "backend_regression_origin": fixture.get("backend_base_url"),
                "phase": args.phase, "results": verifier.results,
                "http": {name: client.observations for name, client in verifier.clients.items()},
                "saved_task": verifier.state.get("saved_task"),
                "saved_document": verifier.state.get("saved_document"),
                "saved_run": verifier.state.get("saved_run"),
                "retry_payload": verifier.state.get("retry_payload"),
                "limits": ["No connected-model inference qualified by this verifier.",
                           "Restart, restore, concurrent worker crash/fencing and browser behavior need separate evidence.",
                           "Mid-session duty revocation and source-document proposal invalidation require additional runtime scenarios."]}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n")
    return 0 if verifier.results and all(row["status"] == "passed" for row in verifier.results) else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (CheckFailure, KeyError, ValueError) as exc:
        print("Verifier configuration error: " + str(exc), file=sys.stderr)
        sys.exit(2)

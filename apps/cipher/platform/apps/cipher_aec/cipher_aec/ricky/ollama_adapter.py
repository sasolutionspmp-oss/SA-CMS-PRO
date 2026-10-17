"""Reviewed native Ollama boundary for the operator-selected existing local model.

No endpoint discovery, model download, dynamic imports, proxy, cloud fallback or
model tools from the independent Ricky runtime are admitted by this adapter.
"""

from __future__ import annotations

import http.client
import json
import re
import socket
import threading
import time
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from urllib.parse import urlsplit

from .contracts import ModelRequest, ModelResponse, RickyError, canonical, parse_time
from .tools import object_schema, validate


KIND = "ollama-local-v1"
MAX_RESPONSE_BYTES = 262144
MAX_REQUEST_BYTES = 196608
GENERATION_WALL_SECONDS = 150  # Below the orchestration's 180-second lease.
SAMPLING = {"temperature": 0, "num_ctx": 8192, "num_predict": 1024, "num_thread": 4}
PROTOCOL_VERSION = "native-selection-then-schema-v2"
ADAPTER_PROMPT_VERSION = "cipher-ollama-prompt-2"
ANSWER_SCHEMA = object_schema({
    "answer": {"type": "string", "maxLength": 12000},
    "citations": {"type": "array", "maxItems": 8, "items": {"type": "string", "minLength": 1, "maxLength": 160}},
}, ("answer", "citations"))


def _invalid(message="The local model returned an invalid response."):
    return RickyError("invalid_model_output", message)


def _json(raw: bytes | str):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate key")
            result[key] = value
        return result

    try:
        return json.loads(raw, object_pairs_hook=pairs,
                          parse_constant=lambda value: (_ for _ in ()).throw(ValueError("nonfinite")))
    except (ValueError, UnicodeError, RecursionError):
        raise _invalid("The local model returned malformed JSON.") from None


@dataclass(frozen=True)
class LocalEndpoint:
    """Resolved only from site-operator configuration, never an app request."""

    base_url: str
    model: str
    digest: str

    def __post_init__(self):
        if (type(self.base_url) is not str or len(self.base_url) > 200
                or any(ord(char) < 33 for char in self.base_url)):
            raise RickyError("invalid_configuration", "The local model endpoint is invalid.")
        try:
            parsed = urlsplit(self.base_url)
            port = parsed.port
        except ValueError:
            raise RickyError("invalid_configuration", "The local model endpoint is invalid.") from None
        if (parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1", "host.docker.internal"}
                or parsed.username is not None or parsed.password is not None or parsed.path not in {"", "/"}
                or parsed.query or parsed.fragment or port is None or not 1 <= port <= 65535):
            raise RickyError("invalid_configuration", "Choose an explicit local Ollama endpoint in operator configuration.")
        # The engine persists at most 200 characters: 128 + @sha256: + 64.
        if type(self.model) is not str or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:/-]{0,127}", self.model):
            raise RickyError("invalid_configuration", "The local model selection is invalid.")
        if type(self.digest) is not str or not re.fullmatch(r"[0-9a-f]{64}", self.digest):
            raise RickyError("invalid_configuration", "The local model requires its exact inventory digest.")


def configured_adapter(profile):
    from .adapter import UnavailableAdapter
    import frappe

    # A closed name resolves a fixed server-side record. A URL in the profile is
    # not a reference and cannot be supplied by the browser or by model output.
    if not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", profile.endpoint_reference or "") or profile.secret_reference is not None:
        raise RickyError("invalid_configuration", "This adapter requires a named local endpoint and no authentication secret.")
    records = frappe.conf.get("cipher_ricky_ollama_endpoints") or {}
    if type(records) is not dict:
        raise RickyError("invalid_configuration", "The local endpoint registry is invalid.")
    record = records.get(profile.endpoint_reference)
    if record is None:
        return UnavailableAdapter("The selected local model endpoint reference has not been configured by an operator.")
    if type(record) is not dict or set(record) != {"base_url", "model", "digest"}:
        raise RickyError("invalid_configuration", "The named local endpoint record is invalid.")
    endpoint = LocalEndpoint(**record)
    if endpoint.model != profile.model_selection:
        raise RickyError("invalid_configuration", "The local model selection differs from the pinned endpoint record.")
    return OllamaAdapter(profile, endpoint)


class HttpTransport:
    """Direct HTTP only: no environment proxy, redirects or unbounded reads."""

    def __init__(self, endpoint):
        self.endpoint = endpoint

    def request(self, path, payload, budget):
        parsed = urlsplit(self.endpoint.base_url)
        connection = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=budget.timeout(connect=True))
        budget.attach(connection)
        response, first_timer = None, None
        wall_timer = threading.Timer(budget.remaining(), budget.expire)
        wall_timer.daemon = True
        wall_timer.start()
        try:
            connection.connect()
            budget.check()
            connection.sock.settimeout(budget.timeout(first=True))
            # Socket inactivity timeouts alone cannot bound dripping headers or
            # chunk framing. Timers close the actual socket at both deadlines.
            first_timer = threading.Timer(budget.timeout(first=True), budget.expire)
            first_timer.daemon = True
            first_timer.start()
            body = None if payload is None else canonical(payload).encode("utf-8")
            if body is not None and len(body) > MAX_REQUEST_BYTES:
                raise RickyError("resource_limit", "The model request exceeds its reviewed size limit.")
            connection.request("GET" if payload is None else "POST", path, body=body,
                               headers={"Content-Type": "application/json", "Accept": "application/json", "Connection": "close"})
            response_socket = connection.sock
            budget.attach_socket(response_socket)
            response = connection.getresponse()
            first_timer.cancel()
            budget.check()
            if response.status != 200:
                # Never include raw provider bodies, URLs or configuration in an error.
                raise RickyError("upstream_unavailable", "The selected local model service is unavailable.",
                                 retryable=response.status in {429, 502, 503, 504})
            if response.getheader("Content-Encoding", "identity") != "identity":
                raise _invalid()
            content_type = response.getheader("Content-Type", "").split(";", 1)[0].strip().lower()
            if content_type != "application/json":
                raise _invalid()
            length = response.getheader("Content-Length")
            if length is not None and (len(length) > 12 or not length.isascii() or not length.isdecimal() or int(length) > MAX_RESPONSE_BYTES):
                raise _invalid("The local model response exceeds its reviewed size limit.")
            if length is not None and response.getheader("Transfer-Encoding") is not None:
                raise _invalid()
            chunks, size = [], 0
            while True:
                budget.check()
                if response.isclosed():
                    break
                if response_socket is not None:
                    response_socket.settimeout(budget.timeout())
                # read1 performs one socket read, allowing total-deadline checks
                # even if a provider continually sends a small amount of data.
                part = response.read1(min(16384, MAX_RESPONSE_BYTES + 1 - size))
                if not part:
                    break
                chunks.append(part)
                size += len(part)
                if size > MAX_RESPONSE_BYTES:
                    raise _invalid("The local model response exceeds its reviewed size limit.")
            budget.check()
            if length is not None and size != int(length):
                raise _invalid("The local model response ended before its declared size.")
            return _json(b"".join(chunks))
        except RickyError:
            raise
        except TimeoutError:
            budget.check()
            raise RickyError("upstream_timeout", "The local model exceeded its response time limit.", retryable=True) from None
        except (OSError, http.client.HTTPException):
            budget.check()
            raise RickyError("upstream_unavailable", "The selected local model service could not respond within its connection limits.", retryable=True) from None
        finally:
            wall_timer.cancel()
            if first_timer is not None:
                first_timer.cancel()
            if response is not None:
                response.close()
            connection.close()
            budget.detach(connection)


class _Budget:
    def __init__(self, profile, seconds):
        self.profile, self.end = profile, time.monotonic() + seconds
        self.cancelled = threading.Event()
        self.expired = threading.Event()
        self._lock, self._connection, self._socket = threading.Lock(), None, None

    def check(self):
        if self.cancelled.is_set():
            raise RickyError("cancelled", "The local model request was cancelled.")
        if self.expired.is_set() or time.monotonic() >= self.end:
            raise RickyError("upstream_timeout", "The local model exceeded this request's time budget.", retryable=True)

    def timeout(self, *, connect=False, first=False):
        self.check()
        ceiling = self.profile.connect_timeout_seconds if connect else self.profile.first_response_timeout_seconds if first else self.profile.wall_timeout_seconds
        return max(0.001, min(ceiling, self.end - time.monotonic()))

    def remaining(self):
        self.check()
        return max(0.001, self.end - time.monotonic())

    def attach(self, connection):
        with self._lock:
            self.check()
            self._connection = connection

    def detach(self, connection):
        with self._lock:
            if self._connection is connection:
                self._connection = None
                self._socket = None

    def attach_socket(self, response_socket):
        with self._lock:
            self.check()
            self._socket = response_socket

    def cancel(self):
        self.cancelled.set()
        self._interrupt_socket()

    def expire(self):
        self.expired.set()
        self._interrupt_socket()

    def _interrupt_socket(self):
        with self._lock:
            connection = self._connection
            active_socket = self._socket or (connection.sock if connection is not None else None)
            if active_socket is not None:
                try:
                    active_socket.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
            if connection is not None:
                connection.close()


class OllamaAdapter:
    def __init__(self, profile, endpoint: LocalEndpoint, *, transport=None):
        if profile.model_selection != endpoint.model or profile.secret_reference is not None:
            raise RickyError("invalid_configuration", "The selected local model does not match its endpoint contract.")
        self.profile, self.endpoint = profile, endpoint
        self.transport = transport or HttpTransport(endpoint)
        self._lock, self._active = threading.Lock(), {}
        self._structured_verified = self._native_verified = False

    def _identity(self, budget):
        inventory = self.transport.request("/api/tags", None, budget)
        if type(inventory) is not dict or type(inventory.get("models")) is not list:
            raise _invalid()
        matches = [item for item in inventory["models"] if type(item) is dict and item.get("name") == self.endpoint.model]
        if len(matches) != 1 or matches[0].get("digest") != self.endpoint.digest:
            raise RickyError("model_identity_changed", "The selected local model no longer matches its pinned inventory identity.")

    def status(self):
        capabilities = {name: {"status": "unverified", "value": None} for name in
                        ("structured_output", "native_tools", "image_input", "context_limit", "concurrency", "cancellation")}
        # Text-only adapter, bounded single-request semantics, no provider-wide
        # cancel API. A local socket close never proves server compute stopped.
        capabilities["image_input"] = {"status": "confirmed", "value": False, "basis": "adapter-text-only"}
        capabilities["cancellation"] = {"status": "confirmed", "value": False, "basis": "no-provider-cancel; durable-fencing-and-bounded-socket"}
        result = {"available": False, "status": "unavailable", "adapter_kind": KIND, "capabilities": capabilities,
                  "cloud_fallback": False, "model": self.endpoint.model, "model_digest": self.endpoint.digest,
                  "lineage_status": "unverified", "authentication": "operator-selected-local-http-no-auth"}
        try:
            budget = _Budget(self.profile, min(30, self.profile.wall_timeout_seconds))
            self._identity(budget)
            shown = self.transport.request("/api/show", {"model": self.endpoint.model, "verbose": False}, budget)
            if (type(shown) is not dict or type(shown.get("capabilities")) is not list
                    or not all(type(value) is str for value in shown["capabilities"]) or "completion" not in shown["capabilities"]):
                raise _invalid()
            info = shown.get("model_info", {})
            architecture = info.get("general.architecture") if type(info) is dict else None
            context_limit = info.get(str(architecture) + ".context_length") if type(info) is dict else None
            capabilities["native_tools"] = {"status": "confirmed" if self._native_verified else "unverified",
                                            "value": "tools" in shown["capabilities"], "basis": "validated-native-response" if self._native_verified else "provider-reported"}
            capabilities["structured_output"] = {"status": "confirmed" if self._structured_verified else "unverified",
                                                 "value": True if self._structured_verified else None,
                                                 "basis": "validated-answer-response" if self._structured_verified else "requires-live-schema-probe"}
            capabilities["context_limit"] = {"status": "unverified", "value": context_limit if type(context_limit) is int else None,
                                             "configured_tokens": SAMPLING["num_ctx"], "basis": "provider-reported; full-window-unqualified"}
            result.update(available=True, status="ready", health="inventory-and-show-verified")
        except RickyError as error:
            result.update(code=error.code, message=error.message)
        return result

    def generate(self, request: ModelRequest) -> ModelResponse:
        if not isinstance(request, ModelRequest):
            raise _invalid()
        try:
            remaining = (parse_time(request.deadline) - datetime.now(timezone.utc)).total_seconds()
        except (ValueError, TypeError, AttributeError):
            raise _invalid("The model request deadline is invalid.") from None
        if remaining <= 0:
            raise RickyError("upstream_timeout", "The local model request deadline has expired.")
        prepared = any(type(item) is dict and item.get("tool") == "task.propose"
                       and type(item.get("data")) is dict and item["data"].get("status") == "proposed"
                       and type(item["data"].get("proposal_id")) is str for item in request.context)
        body, schemas = self._request(request, final=prepared)
        budget = _Budget(self.profile, min(remaining, self.profile.wall_timeout_seconds, GENERATION_WALL_SECONDS))
        with self._lock:
            if self._active:
                raise RickyError("rate_limit", "This adapter already has an active local model request.", retryable=True)
            self._active[request.run_id] = budget
        try:
            self._identity(budget)
            result = self.transport.request("/api/chat", body, budget)
            budget.check()
            phases = ["native-tool-selection" if "tools" in body else "schema-final-answer"]
            if "tools" in body:
                # Native tool selection and grammar-constrained final content
                # are separate Ollama modes. Plain content in this phase is
                # provisional: do not deliver it, parse it into tool intents,
                # or include it in the next prompt as evidence.
                message, calls = self._message(result)
                if calls:
                    # Native-phase content is provisional even beside genuine
                    # calls. Discard it at this boundary; the unchanged strict
                    # parser below still validates every native call/argument.
                    # Final synthesis never enters this branch or gains tools.
                    result = {**result, "message": {**message, "content": ""}}
                else:
                    self._identity(budget)
                    body, schemas = self._request(request, final=True)
                    result = self.transport.request("/api/chat", body, budget)
                    budget.check()
                    phases.append("schema-final-answer")
            response = self._normalize(result, schemas)
            self._identity(budget)
            budget.check()
            if response.tool_requests:
                self._native_verified = True
            elif body.get("format") == ANSWER_SCHEMA:
                self._structured_verified = True
            return replace(response, sampling={**response.sampling,
                "response_protocol": PROTOCOL_VERSION, "adapter_prompt_version": ADAPTER_PROMPT_VERSION,
                "model_requests": len(phases), "phases": phases})
        finally:
            with self._lock:
                self._active.pop(request.run_id, None)

    def _request(self, request, *, final=False):
        if (type(request.run_id) is not str or not request.run_id or len(request.run_id) > 160
                or type(request.question) is not str or not 1 <= len(request.question) <= 4000
                or type(request.instruction) is not str or len(request.instruction) > 4000
                or type(request.tools) not in {tuple, list} or len(request.tools) > 8):
            raise _invalid("The model request exceeds its reviewed contract.")
        schemas, tools = {}, []
        for tool in request.tools:
            if (type(tool) is not dict or type(tool.get("name")) is not str
                    or not re.fullmatch(r"[a-z][a-z0-9_.]{0,99}", tool["name"])
                    or tool["name"] in schemas or type(tool.get("input_schema")) is not dict):
                raise _invalid("The model request contains an invalid tool schema.")
            schemas[tool["name"]] = tool["input_schema"]
            descriptions = {
                "project.lookup": "Read current Project metadata within the server-assigned scope.",
                "document.search": "Find accessible source excerpts in the current Project using literal source-topic words.",
                "task.propose": "Prepare one source-cited Task draft for human review when requested. It does not save a Task or approve anything.",
            }
            tools.append({"type": "function", "function": {"name": tool["name"],
                          "description": descriptions.get(tool["name"], "Registered Cipher " + tool.get("effect_class", "read") + " tool; scope is assigned by the server."),
                          "parameters": tool["input_schema"]}})
        # Tool results are data, rather than extra system/assistant messages.
        context = canonical(request.context)
        if len(context.encode()) > 131072:
            raise RickyError("resource_limit", "The model context exceeds its reviewed size limit.")
        instruction = request.instruction + (
            " Use only the supplied native tools if more preparation is needed. Tool requests only propose work; "
            "the server validates them independently. When finished, return exactly one JSON object with only "
            "answer (a string) and citations (an array of exact supplied citation IDs). No Markdown fences. "
            "If task.propose has already returned a proposal_id in tool results, do not propose it again; answer with citations. "
            "Never output another model version, actor, permission or connection setting."
        )
        if tools and not final:
            instruction += (
                " This is native tool selection. If the user asks to create, draft or propose a Task, "
                "request task.propose exactly once using exact supplied citation IDs. Its result will be "
                "a prepared draft for review, not a saved Task. Never emit tool-looking commands as prose."
            )
        else:
            instruction += (
                " This is final answer synthesis with no tools. Use only the original evidence and actual "
                "tool receipts below. A task.propose receipt means a draft was prepared; it does not mean "
                "a Task was saved. Return only JSON conforming to this exact schema: " + canonical(ANSWER_SCHEMA)
            )
        body = {"model": self.endpoint.model, "stream": False, "think": False, "keep_alive": "60s",
                "options": dict(SAMPLING), "messages": [{"role": "system", "content": instruction},
                    {"role": "user", "content": canonical({"question": request.question, "evidence_and_tool_results": request.context})}]}
        if tools and not final:
            body["tools"] = tools
        else:
            body["format"] = ANSWER_SCHEMA
            schemas = {}  # No tool can be dispatched from final synthesis.
        if len(canonical(body).encode()) > MAX_REQUEST_BYTES:
            raise RickyError("resource_limit", "The model request exceeds its reviewed size limit.")
        return body, schemas

    def _message(self, result):
        if (type(result) is not dict or result.get("model") != self.endpoint.model or result.get("done") is not True
                or result.get("done_reason") != "stop" or type(result.get("message")) is not dict):
            raise _invalid("The local model did not return a complete response for the selected model.")
        message = result["message"]
        if (set(message) - {"role", "content", "tool_calls", "thinking"} or message.get("role") != "assistant"
                or type(message.get("content")) is not str or len(message["content"]) > 65536
                or ("thinking" in message and type(message["thinking"]) is not str)):
            raise _invalid()
        calls = message.get("tool_calls", [])
        if type(calls) is not list or len(calls) > 8:
            raise _invalid("The local model exceeded its tool-request contract.")
        return message, calls

    def _normalize(self, result, schemas):
        message, calls = self._message(result)
        normalized = []
        for call in calls:
            if (type(call) is not dict or set(call) - {"function", "id", "type"}
                    or call.get("type", "function") != "function" or type(call.get("function")) is not dict):
                raise _invalid()
            function = call["function"]
            if (set(function) - {"name", "arguments", "index"} or {"name", "arguments"} - set(function)
                    or type(function.get("name")) is not str or function["name"] not in schemas
                    or type(function.get("arguments")) is not dict):
                raise _invalid("The local model requested an unregistered or malformed tool.")
            try:
                validate(schemas[function["name"]], function["arguments"])
            except (RickyError, ValueError, RecursionError):
                raise _invalid("The local model tool arguments do not match the registered schema.") from None
            normalized.append({"name": function["name"], "arguments": function["arguments"]})
        content = message["content"].strip()
        answer, citations = "", ()
        if content:
            envelope = _json(content)
            try:
                validate(ANSWER_SCHEMA, envelope)
            except (RickyError, ValueError, RecursionError):
                raise _invalid("The local model answer does not match the response schema.") from None
            answer, citations = envelope["answer"], tuple(envelope["citations"])
        if normalized and (answer.strip() or citations):
            raise _invalid("A local model response must request tools or return its final cited answer.")
        if not normalized and not answer.strip():
            raise _invalid("The local model returned no final answer or tool request.")
        return ModelResponse(answer, citations, tuple(normalized),
                             model_version=self.endpoint.model + "@sha256:" + self.endpoint.digest,
                             sampling=dict(SAMPLING))

    def cancel(self, run_id):
        with self._lock:
            budget = self._active.get(run_id)
        if budget is not None:
            budget.cancel()
        # No provider cancellation contract exists. Cross-process cancellation
        # is handled by durable run fencing; even a socket close is best effort.
        return False

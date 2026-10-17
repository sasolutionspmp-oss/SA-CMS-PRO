"""Reviewed typed tools. The registry has no arbitrary-code escape hatch."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .contracts import RickyError, canonical


def validate(schema: dict, value, path: str = "input") -> None:
    """Validate the deliberately small closed JSON-schema vocabulary used here."""
    kind = schema.get("type")
    valid = {
        "object": lambda x: type(x) is dict,
        "array": lambda x: type(x) in (list, tuple),
        "string": lambda x: type(x) is str,
        "integer": lambda x: type(x) is int,
        "boolean": lambda x: type(x) is bool,
    }
    if kind not in valid or not valid[kind](value):
        raise RickyError("validation_error", f"{path} must be {kind}.")
    if "enum" in schema and value not in schema["enum"]:
        raise RickyError("validation_error", f"{path} has an unsupported value.")
    if kind == "object":
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is not False:
            raise ValueError("Tool object schemas must be closed.")
        if set(value) - set(properties) or set(schema.get("required", ())) - set(value):
            raise RickyError("validation_error", f"{path} has missing or unsupported fields.")
        for key, item in value.items():
            validate(properties[key], item, f"{path}.{key}")
    elif kind == "string":
        if len(value) < schema.get("minLength", 0) or len(value) > schema.get("maxLength", 12000):
            raise RickyError("validation_error", f"{path} has an invalid length.")
        if "\x00" in value:
            raise RickyError("validation_error", f"{path} contains an invalid character.")
    elif kind == "integer":
        if value < schema.get("minimum", 0) or value > schema.get("maximum", 2**31 - 1):
            raise RickyError("validation_error", f"{path} is outside its allowed range.")
    elif kind == "array":
        if len(value) > schema.get("maxItems", 8):
            raise RickyError("validation_error", f"{path} contains too many items.")
        for item in value:
            validate(schema["items"], item, f"{path}[]")


def object_schema(properties: dict, required: tuple[str, ...]) -> dict:
    return {"type": "object", "properties": properties, "required": list(required), "additionalProperties": False}


@dataclass(frozen=True)
class Tool:
    name: str
    version: str
    effect_class: str
    required_permission: str
    input_schema: dict
    output_schema: dict
    maximum_result_bytes: int = 32768
    timeout_seconds: int = 15
    idempotency: str = "read"
    source_dependencies: tuple[str, ...] = ("project_revision", "authority_version")
    audit_redaction: str = "digests-and-source-references"
    execution_environment: str = "frappe-domain-service"
    scope_derivation: str = "persisted-run-authority"

    def public(self) -> dict:
        return {
            "name": self.name, "version": self.version, "effect_class": self.effect_class,
            "required_permission": self.required_permission, "input_schema": self.input_schema,
            "output_schema": self.output_schema, "maximum_result_bytes": self.maximum_result_bytes,
            "timeout_seconds": self.timeout_seconds, "idempotency": self.idempotency,
            "source_dependencies": list(self.source_dependencies), "audit_redaction": self.audit_redaction,
            "execution_environment": self.execution_environment, "scope_derivation": self.scope_derivation,
        }


TEXT = {"type": "string", "maxLength": 12000}
IDENTIFIER = {"type": "string", "minLength": 1, "maxLength": 160}
CITATION = object_schema({
    "citation_id": IDENTIFIER, "document_id": IDENTIFIER, "revision_id": IDENTIFIER,
    "document_title": {"type": "string", "maxLength": 500},
    "revision_number": {"type": "string", "maxLength": 100},
    "page": {"type": "integer", "minimum": 1, "maximum": 100000},
    "page_label": {"type": "string", "maxLength": 100}, "excerpt": {"type": "string", "maxLength": 24000},
    "excerpt_sha256": {"type": "string", "minLength": 64, "maxLength": 64},
    "source_sha256": {"type": "string", "minLength": 64, "maxLength": 64},
}, ("citation_id", "document_id", "revision_id", "page", "excerpt", "excerpt_sha256", "source_sha256"))


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, tuple[Tool, Callable]] = {}

    def register(self, tool: Tool, handler: Callable) -> None:
        if tool.name in self._tools:
            raise ValueError("Tool names are unique.")
        self._tools[tool.name] = tool, handler

    def schemas(self) -> tuple[dict, ...]:
        return tuple(tool.public() for tool, _ in self._tools.values())

    def definition(self, name: str) -> Tool:
        if name not in self._tools:
            raise RickyError("forbidden_tool", "This tool is not registered for this run.")
        return self._tools[name][0]

    def execute(self, name: str, arguments: dict, execution) -> dict:
        tool = self.definition(name)
        validate(tool.input_schema, arguments)
        result = self._tools[name][1](execution, arguments)
        validate(tool.output_schema, result, "output")
        if len(canonical(result).encode()) > tool.maximum_result_bytes:
            raise RickyError("resource_limit", "The tool result exceeds its reviewed size limit.")
        return result


def default_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(Tool(
        "project.lookup", "1", "read", "project.read", object_schema({}, ()),
        object_schema({"project": IDENTIFIER, "company": IDENTIFIER, "title": TEXT, "revision": IDENTIFIER}, ("project", "company", "title", "revision")),
    ), lambda execution, args: execution.project())
    registry.register(Tool(
        "document.search", "1", "read", "document.read",
        object_schema({"query": {"type": "string", "minLength": 1, "maxLength": 500}, "limit": {"type": "integer", "minimum": 1, "maximum": 8}}, ("query",)),
        object_schema({"citations": {"type": "array", "maxItems": 8, "items": CITATION}}, ("citations",)),
        source_dependencies=("project_revision", "authority_version", "document_revision", "excerpt_sha256"),
    ), lambda execution, args: execution.search(args["query"], args.get("limit", 4)))
    registry.register(Tool(
        "task.propose", "1", "proposal", "task.create",
        object_schema({"subject": {"type": "string", "minLength": 1, "maxLength": 140}, "description": TEXT,
                       "citation_ids": {"type": "array", "maxItems": 8, "items": IDENTIFIER}}, ("subject", "description", "citation_ids")),
        object_schema({"proposal_id": IDENTIFIER, "proposal_version": {"type": "integer", "minimum": 1}, "status": {"type": "string", "enum": ["proposed"]}}, ("proposal_id", "proposal_version", "status")),
        idempotency="run-and-tool-call-bound-proposal",
    ), lambda execution, args: execution.propose(args))
    return registry

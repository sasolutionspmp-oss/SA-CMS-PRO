"""Inactive AI-04 registry factory; never added to the default registry here."""
from .aec_contracts import SCHEMAS
from .tools import Tool, ToolRegistry


def aec_registry():
    registry = ToolRegistry()
    for name, handler, permission, effect in (
        ("aec.pursuit.lookup", "pursuit_lookup", "commercial.read", "read"),
        ("aec.estimate.recompute", "recompute", "estimate.read", "read"),
        ("aec.estimate.compare", "compare", "estimate.read", "read"),
        ("aec.quantity.convert", "convert", "estimate.read", "read"),
        ("aec.scope.draft", "scope_draft", "commercial.read", "proposal"),
        ("aec.estimate.draft", "estimate_draft", "estimate.read", "proposal"),
    ):
        request, response = SCHEMAS[name]
        registry.register(Tool(name, "1", effect, permission, request, response,
            idempotency="read-or-nonpersistent-draft-value", scope_derivation="explicit-company-read-context",
            source_dependencies=("current-actor-and-domain-access", "canonical-record-digests", "exact-original-source-bytes")),
            lambda execution, arguments, method=handler: getattr(execution, method)(arguments))
    return registry

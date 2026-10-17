"""Adapter selection is explicit. No serving protocol or endpoint is guessed."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .contracts import ModelAdapter, ModelRequest, ModelResponse, RickyError, digest


@dataclass(frozen=True)
class ConnectionProfile:
    adapter_kind: str = "unconfigured"
    endpoint_reference: str | None = None
    secret_reference: str | None = None
    model_selection: str | None = None
    connect_timeout_seconds: int = 30
    first_response_timeout_seconds: int = 120
    wall_timeout_seconds: int = 300

    def __post_init__(self):
        if type(self.adapter_kind) is not str or not self.adapter_kind or len(self.adapter_kind) > 100:
            raise RickyError("invalid_configuration", "The local adapter kind is invalid.")
        for reference in (self.endpoint_reference, self.secret_reference, self.model_selection):
            if reference is not None and (type(reference) is not str or not reference or len(reference) > 500 or "\x00" in reference):
                raise RickyError("invalid_configuration", "A local adapter reference is invalid.")
        for value, maximum in ((self.connect_timeout_seconds, 30), (self.first_response_timeout_seconds, 120), (self.wall_timeout_seconds, 300)):
            if type(value) is not int or not 1 <= value <= maximum:
                raise RickyError("invalid_configuration", "The local adapter timeout exceeds its interactive policy.")

    def fingerprint(self) -> str:
        # References are hashed; secrets are never loaded or exposed by this layer.
        return digest(self.__dict__)


class UnavailableAdapter:
    def __init__(self, reason: str = "The existing local Ricky connection has not been configured."):
        self.reason = reason

    def status(self) -> dict:
        return {
            "available": False,
            "status": "unavailable",
            "code": "upstream_unavailable",
            "message": self.reason,
            "adapter_kind": "unconfigured",
            "capabilities": {
                name: {"status": "unverified", "value": None}
                for name in ("structured_output", "native_tools", "image_input", "context_limit", "concurrency", "cancellation")
            },
            "requirements": ["serving_protocol", "endpoint_reference", "authentication_contract", "model_selection", "health_contract"],
            "cloud_fallback": False,
        }

    def generate(self, request: ModelRequest) -> ModelResponse:
        raise RickyError("upstream_unavailable", self.reason, retryable=True)

    def cancel(self, run_id: str) -> bool:
        return False


def _ollama_factory(profile: ConnectionProfile) -> ModelAdapter:
    from .ollama_adapter import configured_adapter
    return configured_adapter(profile)


# Registration is a reviewed Python integration, never a browser/model import path.
_factories: dict[str, Callable[[ConnectionProfile], ModelAdapter]] = {"ollama-local-v1": _ollama_factory}


def register_adapter(kind: str, factory: Callable[[ConnectionProfile], ModelAdapter]) -> None:
    if not kind or kind == "unconfigured" or kind in _factories:
        raise ValueError("Adapter kinds must be unique and explicitly named.")
    _factories[kind] = factory


def resolve_adapter(profile: ConnectionProfile) -> ModelAdapter:
    if profile.adapter_kind not in _factories:
        return UnavailableAdapter()
    if not profile.endpoint_reference or not profile.model_selection:
        return UnavailableAdapter("The selected local adapter requires an endpoint reference and model selection.")
    return _factories[profile.adapter_kind](profile)

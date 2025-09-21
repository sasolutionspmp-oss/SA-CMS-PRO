from __future__ import annotations

from typing import Any, Dict, Iterable, Mapping, MutableMapping, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class MetricValue(BaseModel):
    """Represents a single metric entry with optional delta copy."""

    value: Any = None
    delta: str | None = None

    @field_validator("delta", mode="before")
    @classmethod
    def _normalise_delta(cls, value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None


class MetricsEnvelope(BaseModel):
    """Normalised view of dashboard metrics responses."""

    model_config = ConfigDict(extra="allow")

    status: str = "ok"
    message: str | None = None
    summary: Dict[str, Any] = Field(default_factory=dict)
    metrics: Dict[str, MetricValue] = Field(default_factory=dict)
    records: list[Dict[str, Any]] = Field(default_factory=list)
    generated_at: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _default_root(cls, value: Any) -> Dict[str, Any]:
        if value is None:
            return {}
        if isinstance(value, Mapping):
            return dict(value)
        raise TypeError("Metrics payload must be a mapping")

    @field_validator("summary", mode="before")
    @classmethod
    def _coerce_summary(cls, value: Any) -> Dict[str, Any]:
        return dict(value or {}) if isinstance(value, Mapping) else {}

    @field_validator("metrics", mode="before")
    @classmethod
    def _coerce_metrics(cls, value: Any) -> Dict[str, Any]:
        if not isinstance(value, Mapping):
            return {}
        converted: Dict[str, Any] = {}
        for key, candidate in value.items():
            if isinstance(candidate, Mapping):
                converted[key] = dict(candidate)
            else:
                converted[key] = {"value": candidate}
        return converted

    @field_validator("records", mode="before")
    @classmethod
    def _coerce_records(cls, value: Any) -> list[Dict[str, Any]]:
        if not value:
            return []
        items: list[Dict[str, Any]] = []
        for item in value:
            if isinstance(item, Mapping):
                items.append(dict(item))
        return items

    @field_validator("generated_at", mode="before")
    @classmethod
    def _coerce_generated_at(cls, value: Any) -> str | None:
        if value is None:
            return None
        return str(value)

    def project_counts(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        raw_counts = {}
        if isinstance(self.summary, Mapping):
            raw_counts = self.summary.get("project_counts") or {}
        if isinstance(raw_counts, Mapping):
            for key, value in raw_counts.items():
                coerced = _coerce_int(value)
                if coerced is not None:
                    counts[key] = coerced
        return counts


def _coerce_int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def normalize_metrics_payload(stage: str, payload: Mapping[str, Any] | None) -> Dict[str, Any]:
    envelope = MetricsEnvelope.model_validate(payload or {})
    data = envelope.model_dump(mode="python")
    data.setdefault("status", "ok")
    data.setdefault("summary", {})
    data.setdefault("metrics", {})
    data.setdefault("records", [])
    data.setdefault("stage", stage)
    if stage.lower() == "summary":
        data["project_counts"] = envelope.project_counts()
    if not data.get("message") and data.get("status") != "ok":
        readable = stage.replace("_", " ").strip().title() or "Metrics"
        data["message"] = f"{readable} metrics degraded; showing latest available data."
    return data


def offline_metrics_payload(stage: str, *, message: str | None = None) -> Dict[str, Any]:
    readable = stage.replace("_", " ").strip().title() or "Metrics"
    offline_message = message or f"{readable} metrics unavailable; showing offline defaults."
    payload: Dict[str, Any] = {
        "status": "offline",
        "stage": stage,
        "message": offline_message,
        "summary": {},
        "metrics": {},
        "records": [],
    }
    return normalize_metrics_payload(stage, payload)


__all__ = [
    "MetricValue",
    "MetricsEnvelope",
    "normalize_metrics_payload",
    "offline_metrics_payload",
]

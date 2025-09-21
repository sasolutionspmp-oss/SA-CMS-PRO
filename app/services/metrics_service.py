from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import httpx

from app.core.config import MetricsConfig, load_config
from app.schemas.metrics import normalize_metrics_payload, offline_metrics_payload
from app.services.fallbacks import emit_fallback_event

LOGGER = logging.getLogger(__name__)
_PROJECT_ROOT = Path(__file__).resolve().parents[2]


class MetricsServiceError(RuntimeError):
    """Raised when metric retrieval fails after retries."""

    def __init__(self, stage: str, endpoint: str | None, cause: Exception | None = None) -> None:
        message = f"Failed to load metrics for '{stage}'"
        if endpoint:
            message += f" from {endpoint}"
        if cause:
            message += f": {cause}"
        super().__init__(message)
        self.stage = stage
        self.endpoint = endpoint
        self.cause = cause


@dataclass(frozen=True)
class MetricsSnapshot:
    stage: str
    data: Dict[str, Any]
    fetched_at: datetime
    source: str
    duration_ms: int
    from_cache: bool = False


@dataclass
class _CacheEntry:
    snapshot: MetricsSnapshot
    expires_at: float


def offline_payload(stage: str) -> Dict[str, Any]:
    """Return a normalised offline payload for the requested metrics stage."""

    return offline_metrics_payload(stage)


class MetricsService:
    """Fetches dashboard metrics with caching, retry, and offline fallback."""

    def __init__(
        self,
        config: Optional[MetricsConfig] = None,
        *,
        data_root: Optional[Path] = None,
        http_timeout: float = 6.0,
    ) -> None:
        app_config = load_config()
        self._config = config or app_config.metrics
        self._data_root = Path(data_root) if data_root else app_config.paths.data_root
        timeout = self._config.request_timeout_seconds or http_timeout
        self._http_timeout = float(timeout)
        self._retry_backoff = float(getattr(self._config, "retry_backoff_seconds", 0.5) or 0.5)
        flags = vars(self._config.feature_flags)
        self._allow_fallback = bool(flags.get("allow_offline_fallback", True))
        self._enabled = bool(getattr(self._config, "enabled", True))
        self._cache: Dict[str, _CacheEntry] = {}
        self._lock = threading.Lock()

    def fetch(self, stage: str, *, force: bool = False) -> MetricsSnapshot:
        if not self.enabled:
            LOGGER.debug("metrics disabled via configuration; returning offline snapshot for stage=%s", stage)
            return self._offline_snapshot(stage, source="disabled")

        now = time.time()
        with self._lock:
            entry = self._cache.get(stage)
            if entry and not force and entry.expires_at > now:
                LOGGER.debug("metrics cache hit for stage=%s", stage)
                return replace(entry.snapshot, from_cache=True)

        snapshot = self._retrieve(stage)
        with self._lock:
            self._cache[stage] = _CacheEntry(snapshot=snapshot, expires_at=time.time() + self._config.cache_ttl_seconds)
        return snapshot

    def refresh_interval(self, stage: str, default_seconds: int = 180) -> int:
        mapping = vars(self._config.refresh_intervals)
        try:
            return int(mapping.get(stage, default_seconds))
        except Exception:  # pragma: no cover - defensive guard
            return default_seconds

    @property
    def enabled(self) -> bool:
        return self._enabled

    def feature_enabled(self, flag: str, default: bool = True) -> bool:
        flags = vars(self._config.feature_flags)
        value = flags.get(flag, default)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)

    def clear_cache(self) -> None:
        with self._lock:
            self._cache.clear()

    def _retrieve(self, stage: str) -> MetricsSnapshot:
        cfg = self._config
        endpoints = vars(cfg.endpoints)
        endpoint = endpoints.get(stage)
        if not endpoint:
            raise MetricsServiceError(stage, None, ValueError("endpoint not configured"))

        attempts = 0
        last_error: Exception | None = None
        start_perf = time.perf_counter()

        while attempts < cfg.max_retries:
            attempts += 1
            try:
                payload, source = self._load_endpoint(stage, endpoint)
                data = normalize_metrics_payload(stage, payload)
                duration_ms = int((time.perf_counter() - start_perf) * 1000)
                snapshot = MetricsSnapshot(
                    stage=stage,
                    data=data,
                    fetched_at=datetime.now(timezone.utc),
                    source=source,
                    duration_ms=duration_ms,
                )
                LOGGER.debug("metrics fetch ok for stage=%s via %s in %sms", stage, source, duration_ms)
                return snapshot
            except Exception as exc:
                last_error = exc
                LOGGER.warning(
                    "metrics fetch failed for stage=%s (attempt %s/%s): %s",
                    stage,
                    attempts,
                    cfg.max_retries,
                    exc,
                )
                time.sleep(self._retry_backoff)

        if self._allow_fallback:
            try:
                data, source = self._load_fallback(stage)
                data = normalize_metrics_payload(stage, data)
            except Exception as exc:  # pragma: no cover - fallback failure is rare and asserted in tests
                raise MetricsServiceError(stage, endpoint, exc) from last_error
            duration_ms = int((time.perf_counter() - start_perf) * 1000)
            snapshot = MetricsSnapshot(
                stage=stage,
                data=data,
                fetched_at=datetime.now(timezone.utc),
                source=source,
                duration_ms=duration_ms,
            )
            reason = "offline_stub" if data.get("status") == "offline" else "fallback_used"
            emit_fallback_event(
                "metrics",
                stage,
                reason,
                detail={
                    "endpoint": endpoint,
                    "source": snapshot.source,
                    "attempts": attempts,
                },
            )
            LOGGER.info("metrics fallback used for stage=%s via %s", stage, snapshot.source)
            return snapshot

        raise MetricsServiceError(stage, endpoint, last_error)

    def _offline_snapshot(self, stage: str, *, source: str = "offline") -> MetricsSnapshot:
        data = offline_payload(stage)
        return MetricsSnapshot(
            stage=stage,
            data=data,
            fetched_at=datetime.now(timezone.utc),
            source=source,
            duration_ms=0,
        )

    def _load_endpoint(self, stage: str, endpoint: str) -> tuple[Dict[str, Any], str]:
        if endpoint.startswith("file://"):
            path = endpoint.replace("file://", "", 1)
            return self._load_local(stage, Path(path)), "local"
        if endpoint.startswith("http://") or endpoint.startswith("https://"):
            with httpx.Client(timeout=self._http_timeout, follow_redirects=True) as client:
                response = client.get(endpoint)
                response.raise_for_status()
                payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError("metrics response is not a JSON object")
            return payload, "remote"
        return self._load_local(stage, Path(endpoint)), "local"

    def _load_fallback(self, stage: str) -> tuple[Dict[str, Any], str]:
        fallback_path = self._data_root / "metrics" / f"{stage}.json"
        try:
            return self._load_local(stage, fallback_path), "fallback"
        except FileNotFoundError:
            LOGGER.warning(
                "Missing metrics fallback for stage=%s at %s; using offline defaults",
                stage,
                fallback_path,
            )
        except ValueError as exc:
            LOGGER.warning(
                "Invalid metrics fallback for stage=%s at %s: %s; using offline defaults",
                stage,
                fallback_path,
                exc,
            )
        LOGGER.info("metrics offline stub returned for stage=%s", stage)
        return offline_payload(stage), "fallback"

    def _load_local(self, stage: str, path: Path) -> Dict[str, Any]:
        candidates = self._candidate_paths(path)
        for candidate in candidates:
            try:
                text = candidate.read_text(encoding="utf-8")
            except FileNotFoundError:
                continue
            except OSError as exc:
                LOGGER.debug("unable to read metrics for stage=%s from %s: %s", stage, candidate, exc)
                continue
            try:
                data = json.loads(text or "{}")
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSON in {candidate}") from exc
            if not isinstance(data, dict):
                raise ValueError(f"metrics payload for {stage} must be a JSON object")
            return data
        raise FileNotFoundError(str(path))

    def _candidate_paths(self, path: Path) -> list[Path]:
        candidates: list[Path] = []
        if path.is_absolute():
            candidates.append(path)
        else:
            candidates.append(self._data_root / path)
            candidates.append(_PROJECT_ROOT / path)
        seen: set[Path] = set()
        ordered: list[Path] = []
        for candidate in candidates:
            try:
                resolved = candidate.resolve()
            except OSError:
                resolved = candidate
            if resolved in seen:
                continue
            seen.add(resolved)
            ordered.append(resolved)
        return ordered


__all__ = ["MetricsService", "MetricsServiceError", "MetricsSnapshot", "offline_payload"]

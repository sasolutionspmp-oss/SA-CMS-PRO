from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from app.core.config import load_config
from app.services import CopilotService, MetricsService, MetricsServiceError, offline_payload


def test_metrics_service_uses_cache() -> None:
    service = MetricsService()
    first = service.fetch("scope", force=True)
    second = service.fetch("scope")
    assert not first.from_cache
    assert second.from_cache
    assert first.data == second.data


def test_metrics_service_fetches_local_endpoint(tmp_path: Path) -> None:
    cfg = load_config()
    summary_file = tmp_path / "summary.json"
    summary_file.write_text(json.dumps({"totals": {"active_projects": 3}}), encoding="utf-8")

    custom_endpoints = replace(cfg.metrics.endpoints, summary=str(summary_file))
    custom_config = replace(
        cfg.metrics,
        endpoints=custom_endpoints,
        max_retries=1,
        request_timeout_seconds=0.1,
    )
    service = MetricsService(config=custom_config, data_root=tmp_path)

    snapshot = service.fetch("summary", force=True)

    assert snapshot.source == "local"
    assert snapshot.data["totals"]["active_projects"] == 3


def test_metrics_service_fallback_to_fixture() -> None:
    cfg = load_config()
    custom_endpoints = replace(cfg.metrics.endpoints, scope="missing_scope.json")
    custom_config = replace(
        cfg.metrics,
        endpoints=custom_endpoints,
        max_retries=1,
        request_timeout_seconds=0.1,
    )
    service = MetricsService(config=custom_config, data_root=cfg.paths.data_root)

    snapshot = service.fetch("scope", force=True)

    assert snapshot.source == "fallback"
    assert snapshot.data.get("summary", {}).get("packages")





def test_metrics_service_uses_local_fallback_payload(tmp_path: Path) -> None:
    cfg = load_config()
    fallback_dir = tmp_path / "metrics"
    fallback_dir.mkdir()
    fallback_payload = {"summary": {"active_projects": 7}}
    (fallback_dir / "summary.json").write_text(json.dumps(fallback_payload), encoding="utf-8")

    missing_path = tmp_path / "missing_summary.json"
    custom_endpoints = replace(cfg.metrics.endpoints, summary=str(missing_path))
    custom_config = replace(
        cfg.metrics,
        endpoints=custom_endpoints,
        max_retries=1,
        request_timeout_seconds=0.1,
    )
    service = MetricsService(config=custom_config, data_root=tmp_path)

    snapshot = service.fetch("summary", force=True)

    assert snapshot.source == "fallback"
    assert snapshot.data["summary"] == fallback_payload["summary"]
    assert snapshot.data["status"] == "ok"
def test_metrics_service_error_without_fallback(tmp_path: Path) -> None:
    cfg = load_config()
    missing_path = tmp_path / "nope.json"
    custom_endpoints = replace(cfg.metrics.endpoints, summary=str(missing_path))
    custom_flags = replace(cfg.metrics.feature_flags, allow_offline_fallback=False)
    custom_config = replace(
        cfg.metrics,
        endpoints=custom_endpoints,
        feature_flags=custom_flags,
        max_retries=1,
        request_timeout_seconds=0.1,
    )
    service = MetricsService(config=custom_config, data_root=tmp_path)

    with pytest.raises(MetricsServiceError):
        service.fetch("summary", force=True)


def test_copilot_offline_generation(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = load_config()
    monkeypatch.setattr("app.services.copilot.write_audit", lambda *args, **kwargs: None)
    copilot_cfg = replace(cfg.copilot, provider="none", offline_allowed=True)
    service = CopilotService(config=copilot_cfg)

    payload = json.dumps({"records": [], "summary": {"packages": 0}})
    result = service.generate("Scope", payload)

    assert result.offline is True
    assert result.provider == "offline"
    assert result.headline
    assert result.next_actions


def test_copilot_uses_stage_specific_pack(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    pack_dir = tmp_path / "packs"
    pack_dir.mkdir()
    default_yaml = '\n'.join([
        'offline_headline: Default insight',
        'offline_insights:',
        '  - Default insight entry',
        ''
    ])
    (pack_dir / "default.yaml").write_text(default_yaml, encoding="utf-8")
    scope_yaml = '\n'.join([
        'offline_headline: Scope offline headline',
        'offline_next_actions:',
        '  - Scope action',
        ''
    ])
    (pack_dir / "scope.yaml").write_text(scope_yaml, encoding="utf-8")

    cfg = load_config()
    monkeypatch.setattr("app.services.copilot.write_audit", lambda *args, **kwargs: None)
    copilot_cfg = replace(
        cfg.copilot,
        provider="none",
        prompt_packs_root=pack_dir,
        offline_allowed=True,
    )
    service = CopilotService(config=copilot_cfg)

    result = service.generate("Scope", json.dumps({"summary": {}}))

    assert result.offline is True
    assert result.headline == "Scope offline headline"
    assert result.next_actions == ["Scope action"]


def test_metrics_service_offline_stub_when_fallback_missing(tmp_path: Path) -> None:
    cfg = load_config()
    missing_path = tmp_path / "scope.json"
    custom_endpoints = replace(cfg.metrics.endpoints, scope=str(missing_path))
    custom_config = replace(
        cfg.metrics,
        endpoints=custom_endpoints,
        max_retries=1,
        request_timeout_seconds=0.1,
    )
    service = MetricsService(config=custom_config, data_root=tmp_path)

    snapshot = service.fetch("scope", force=True)

    assert snapshot.source == "fallback"
    expected = offline_payload("scope")
    data = snapshot.data
    for key, value in expected.items():
        assert data.get(key) == value
    project_counts = data.get("project_counts")
    assert project_counts in ({}, None)


def test_copilot_offline_defaults_when_pack_missing_values(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    pack_dir = tmp_path / "packs"
    pack_dir.mkdir()
    (pack_dir / "default.yaml").write_text(
        "\n".join(
            [
                "offline_headline: ' '",
                "offline_insights:",
                "  - ' '",
                "offline_next_actions:",
                "  - ' '",
            ]
        ),
        encoding="utf-8",
    )

    cfg = load_config()
    monkeypatch.setattr("app.services.copilot.write_audit", lambda *args, **kwargs: None)
    copilot_cfg = replace(
        cfg.copilot,
        provider="none",
        prompt_packs_root=pack_dir,
        offline_allowed=True,
    )
    service = CopilotService(config=copilot_cfg)

    payload = json.dumps({"summary": {"packages": 2}})
    result = service.generate("Scope", payload)

    assert result.offline is True
    assert result.headline == "Scope insight unavailable"
    assert any("offline" in insight.lower() for insight in result.insights)
    assert result.next_actions[0].startswith("Re-run Scope Copilot")


def test_metrics_service_normalises_summary_counts() -> None:
    service = MetricsService()

    snapshot = service.fetch("summary", force=True)

    counts = snapshot.data.get("project_counts")
    assert isinstance(counts, dict)
    assert counts.get("active") == 6
    assert counts.get("total") == 11

def test_metrics_service_handles_partial_payload(tmp_path: Path) -> None:
    cfg = load_config()
    fallback_dir = tmp_path / "metrics"
    fallback_dir.mkdir()
    partial_payload = {
        "status": "warning",
        "summary": None,
        "metrics": {
            "active_projects": 7,
            "backlog": {"value": 3, "delta": " +2 "},
        },
        "records": [
            {"name": "Main Plant", "status": "offline"},
            ["ignore-me"],
        ],
    }
    (fallback_dir / "summary.json").write_text(json.dumps(partial_payload), encoding="utf-8")

    missing_path = tmp_path / "missing_summary.json"
    custom_endpoints = replace(cfg.metrics.endpoints, summary=str(missing_path))
    custom_config = replace(
        cfg.metrics,
        endpoints=custom_endpoints,
        max_retries=1,
        request_timeout_seconds=0.1,
    )
    service = MetricsService(config=custom_config, data_root=tmp_path)

    snapshot = service.fetch("summary", force=True)

    data = snapshot.data
    assert data["status"] == "warning"
    # summary defaults to empty dict when source is null/invalid
    assert data.get("summary") == {}
    metrics = data.get("metrics") or {}
    assert metrics.get("active_projects", {}).get("value") == 7
    assert metrics.get("backlog", {}).get("delta") == "+2"
    # non-mapping records are filtered out
    assert len(data.get("records", [])) == 1
    assert data.get("stage") == "summary"

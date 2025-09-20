import pytest

from app.schemas.metrics import normalize_metrics_payload


def test_normalize_metrics_payload_injects_project_counts() -> None:
    payload = {
        "status": "ok",
        "summary": {
            "project_counts": {"awarded": "2", "bidding": 3, "invalid": "n/a"}
        },
        "metrics": {
            "backlog": {"value": "15.2M", "delta": " +5% "},
        },
    }

    result = normalize_metrics_payload("summary", payload)

    assert result["status"] == "ok"
    assert result["project_counts"] == {"awarded": 2, "bidding": 3}
    assert result["metrics"]["backlog"]["delta"] == "+5%"


def test_normalize_metrics_payload_non_summary_has_no_top_level_counts() -> None:
    payload = {"summary": {"project_counts": {"awarded": 1}}}
    result = normalize_metrics_payload("intake", payload)
    assert "project_counts" not in result


def test_normalize_metrics_payload_rejects_non_mapping() -> None:
    with pytest.raises(TypeError):
        normalize_metrics_payload("summary", ["not", "a", "mapping"])  # type: ignore[arg-type]

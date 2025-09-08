from fastapi.testclient import TestClient
from pathlib import Path
import pytest

from app.main import app
from app.services.rsmeans_import import import_rsmeans_csv
from app.services.export import export_csv, export_excel, export_docx

client = TestClient(app)


def test_orchestrator_run():
    resp = client.post("/api/orchestrator/run", json={"projectId": "p1"})
    assert resp.status_code == 200
    data = resp.json()
    assert "scope_summary" in data
    assert "draft_line_items" in data


def test_indices_calc_and_exports(tmp_path: Path):
    # Import new region index
    csv_content = "region,factor\ncustom,1.5\n"
    resp = client.post(
        "/api/indices/import",
        files={"file": ("regions.csv", csv_content, "text/csv")},
    )
    assert resp.status_code == 200

    # Import RSMeans-like dataset
    import_rsmeans_csv("code,desc,unit,base_cost\n0001,Item,ea,100\n")

    payload = {
        "lines": [{"desc": "Item", "qty": 2, "unit": "ea", "code": "0001"}],
        "overhead_pct": 10,
        "margin_pct": 5,
        "region": "custom",
        "vendorMultipliers": {"vendorA": 1.1},
    }
    resp = client.post("/api/estimate/calc", json=payload)
    assert resp.status_code == 200
    data = resp.json()

    expected_unit_cost = 100 * 1.5 * 1.1
    expected_line_total = expected_unit_cost * 2
    assert data["lines"][0]["unit_cost"] == expected_unit_cost
    assert data["lines"][0]["line_total"] == expected_line_total

    expected_overhead = expected_line_total * 0.10
    expected_margin = (expected_line_total + expected_overhead) * 0.05
    expected_total = expected_line_total + expected_overhead + expected_margin
    assert data["overhead"] == expected_overhead
    assert data["margin"] == pytest.approx(expected_margin)
    assert data["total"] == pytest.approx(expected_total)

    # Test exports
    lines = data["lines"]
    export_csv(lines, tmp_path / "est.csv")
    export_excel(lines, tmp_path / "est.xlsx")
    export_docx("Summary", tmp_path / "est.docx")
    assert (tmp_path / "est.csv").exists()
    assert (tmp_path / "est.xlsx").exists()
    assert (tmp_path / "est.docx").exists()

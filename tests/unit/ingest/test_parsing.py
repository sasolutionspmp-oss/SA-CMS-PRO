import math
from pathlib import Path

import pytest

from app.ingest.parsing import ParseOutcome, parse_document


def test_parse_text_file_snippet(tmp_path: Path) -> None:
    sample = tmp_path / "notes.txt"
    sample.write_text("First line\nSecond line\n", encoding="utf-8")

    outcome = parse_document(sample, "text/plain")

    assert outcome.status == "parsed"
    assert outcome.metadata["mime"] == "text/plain"
    assert outcome.error is None
    assert outcome.snippet == "First line Second line"


def test_parse_csv_captures_rows(tmp_path: Path) -> None:
    sample = tmp_path / "schedule.csv"
    sample.write_text("name,start\nElectrical,2025-01-01\n", encoding="utf-8")

    outcome = parse_document(sample, "text/csv")

    assert outcome.status == "parsed"
    assert "rows_sampled" in outcome.metadata
    assert "Electrical" in outcome.text


def test_parse_unknown_extension_fails(tmp_path: Path) -> None:
    sample = tmp_path / "model.rvt"
    sample.write_text("binary", encoding="utf-8")

    outcome = parse_document(sample, "application/octet-stream")

    assert outcome.status == "failed"
    assert outcome.error and "Unsupported" in outcome.error


def test_pdf_parser_uses_extract_hook(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    sample = tmp_path / "spec.pdf"
    sample.write_text("fake", encoding="utf-8")

    called = {"value": False}

    def fake_extract(path: Path) -> str:
        called["value"] = True
        assert path == sample
        return "Page one text"

    monkeypatch.setattr("app.ingest.parsing.extract_pdf_text", fake_extract)
    outcome = parse_document(sample, "application/pdf")

    assert called["value"] is True
    assert outcome.status == "parsed"
    assert outcome.text.startswith("Page one text")
    assert outcome.snippet == "Page one text"


def test_parse_outcome_snippet_truncates(tmp_path: Path) -> None:
    sample = tmp_path / "long.txt"
    sample.write_text("lorem ipsum " * 100, encoding="utf-8")

    outcome = parse_document(sample, "text/plain")

    assert outcome.status == "parsed"
    assert outcome.snippet is not None
    assert len(outcome.snippet) <= 500

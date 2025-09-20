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


def test_docx_parser_extracts_tables(tmp_path: Path) -> None:
    docx_module = pytest.importorskip("docx")
    document = docx_module.Document()
    if not hasattr(document, "add_table"):
        pytest.skip("python-docx lacks table API")
    document.add_paragraph("Scope Summary")
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "Section"
    table.cell(0, 1).text = "Value"
    table.cell(1, 0).text = "Division"
    table.cell(1, 1).text = "03 Concrete"
    sample = tmp_path / "sample.docx"
    document.save(sample)

    outcome = parse_document(
        sample,
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )

    assert outcome.status == "parsed"
    assert "Scope Summary" in outcome.text
    assert "R1C1" in outcome.text
    assert outcome.metadata.get("tables") == 1



def test_xlsx_parser_includes_coordinates(tmp_path: Path) -> None:
    openpyxl_module = pytest.importorskip("openpyxl")
    workbook = openpyxl_module.Workbook()
    if not hasattr(workbook, "active"):
        pytest.skip("openpyxl workbook missing active sheet")
    sheet = workbook.active
    sheet.title = "Costs"
    sheet["A1"] = "Code"
    sheet["B1"] = "Amount"
    sheet["A2"] = "033000"
    sheet["B2"] = 12500
    sample = tmp_path / "schedule.xlsx"
    workbook.save(sample)
    close_fn = getattr(workbook, "close", None)
    if callable(close_fn):
        close_fn()

    outcome = parse_document(
        sample,
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

    assert outcome.status == "parsed"
    assert "Costs!A1" in outcome.text
    assert "Costs!B2" in outcome.text
    assert outcome.metadata.get("cells_sampled", 0) >= 3



def test_pdf_ocr_fallback(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    sample = tmp_path / "image.pdf"
    sample.write_text("fake", encoding="utf-8")

    monkeypatch.setattr("app.ingest.pdf._extract_with_pypdf", lambda path: "")
    monkeypatch.setattr("app.ingest.pdf._extract_with_pdfminer", lambda path: "")
    monkeypatch.setattr("app.ingest.pdf._ocr_enabled", lambda: True)

    called = {"value": False}

    def fake_ocr(path: Path) -> str:
        called["value"] = True
        return "OCR recovered text"

    monkeypatch.setattr("app.ingest.pdf._run_ocrmypdf", fake_ocr)

    outcome = parse_document(sample, "application/pdf")

    assert called["value"] is True
    assert outcome.status == "parsed"
    assert outcome.text.startswith("OCR recovered text")

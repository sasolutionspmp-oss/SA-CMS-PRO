from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

try:  # pragma: no cover - optional at runtime
    from pypdf import PdfReader
except Exception:  # noqa: BLE001
    PdfReader = None  # type: ignore

try:  # pragma: no cover - optional at runtime
    from pdfminer.high_level import extract_text as pdfminer_extract
except Exception:  # noqa: BLE001
    pdfminer_extract = None  # type: ignore

from app.core.config import load_config


def extract_pdf_text(path: Path) -> str:
    """Return extracted text for the given PDF using pypdf with guarded OCR fallback."""
    text = _extract_with_pypdf(path)
    if not text.strip():
        text = _extract_with_pdfminer(path)
    if (not text.strip()) and _ocr_enabled():
        text = _run_ocrmypdf(path)
    return text.strip()


def _extract_with_pypdf(path: Path) -> str:
    if PdfReader is None:
        return ""
    try:
        reader = PdfReader(str(path))
    except Exception:  # noqa: BLE001 - degrade gracefully
        return ""
    pages: list[str] = []
    for page in reader.pages:
        try:
            pages.append(page.extract_text() or "")
        except Exception:  # noqa: BLE001 - tolerate individual page failures
            pages.append("")
    return "\n".join(pages)


def _extract_with_pdfminer(path: Path) -> str:
    if pdfminer_extract is None:
        return ""
    try:
        return pdfminer_extract(str(path))
    except Exception:  # noqa: BLE001
        return ""


def _ocr_enabled() -> bool:
    cfg = load_config()
    return bool(cfg.ingest.use_ocr and shutil.which("ocrmypdf"))


def _run_ocrmypdf(path: Path) -> str:
    tmp_dir = Path(tempfile.mkdtemp(prefix="sa_cms_ocr_"))
    output_pdf = tmp_dir / "ocr.pdf"
    sidecar = tmp_dir / "sidecar.txt"
    cfg = load_config()
    language = getattr(cfg.ingest, "ocr_language", None)
    cmd = [
        "ocrmypdf",
        "--sidecar",
        str(sidecar),
        "--quiet",
        "--skip-text",
    ]
    if language:
        cmd.extend(["-l", language])
    cmd.extend([str(path), str(output_pdf)])
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            check=False,
            text=True,
            timeout=300,
        )
        if result.returncode != 0 or not sidecar.exists():
            return ""
        return sidecar.read_text(encoding="utf-8", errors="ignore")
    except (OSError, subprocess.SubprocessError):
        return ""
    finally:
        for target in (output_pdf, sidecar):
            try:
                if target.exists():
                    target.unlink()
            except OSError:
                pass
        try:
            tmp_dir.rmdir()
        except OSError:
            pass

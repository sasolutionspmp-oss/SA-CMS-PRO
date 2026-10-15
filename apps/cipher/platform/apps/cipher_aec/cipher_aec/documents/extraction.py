"""Bounded, page-scoped plain-text extraction; never a PDF renderer or AV claim."""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from dataclasses import dataclass

MAX_BYTES = 10 * 1024 * 1024
MAX_PAGES = 200
MAX_PAGE_CHARS = 20000
MAX_TEXT_CHARS = 1000000
EXTRACTOR_VERSION = "cipher-safe-text-v1"


class ArtifactError(ValueError):
    pass


@dataclass(frozen=True)
class Extraction:
    status: str
    pages: tuple[str, ...]
    extractor_version: str = EXTRACTOR_VERSION
    warning: str | None = None


def digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def validate_source(content: bytes, filename: str, declared_size: int, declared_sha256: str) -> str:
    if not isinstance(content, bytes) or not content or len(content) > MAX_BYTES:
        raise ArtifactError("Source must contain 1 byte to 10 MiB.")
    if type(declared_size) is not int or declared_size != len(content):
        raise ArtifactError("Declared byte length does not match source bytes.")
    if not isinstance(declared_sha256, str) or not re.fullmatch(r"[a-fA-F0-9]{64}", declared_sha256):
        raise ArtifactError("A SHA-256 checksum is required.")
    if digest(content) != declared_sha256.lower():
        raise ArtifactError("Source checksum does not match uploaded bytes.")
    if not isinstance(filename, str) or len(filename) > 180 or not filename.strip() or re.search(r"[/\\\x00-\x1f\x7f]", filename):
        raise ArtifactError("Filename must be a plain filename with no path or control characters.")
    suffix = filename.lower().rsplit(".", 1)[-1]
    if suffix == "pdf":
        if not content.startswith(b"%PDF-"):
            raise ArtifactError("PDF extension does not match its file signature.")
        return "application/pdf"
    if suffix in {"txt", "text"}:
        if content.startswith(b"%PDF-") or b"\x00" in content:
            raise ArtifactError("Text extension does not match UTF-8 text bytes.")
        try:
            content.decode("utf-8-sig", errors="strict")
        except UnicodeDecodeError as exc:
            raise ArtifactError("Text sources must be UTF-8.") from exc
        return "text/plain"
    raise ArtifactError("Only UTF-8 .txt/.text and PDF sources are supported in R0.")


def safe_text(value: str) -> str:
    # No HTML is generated. Controls/bidi overrides have no place in evidence previews.
    return "".join(c for c in value if c in "\n\t" or (ord(c) >= 32 and ord(c) != 127 and not 0x202A <= ord(c) <= 0x202E and not 0x2066 <= ord(c) <= 0x2069))


def extract_source(content: bytes, mime_type: str) -> Extraction:
    if mime_type == "text/plain":
        pages = tuple(safe_text(part) for part in content.decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n").split("\f"))
        if len(pages) > MAX_PAGES or any(len(p) > MAX_PAGE_CHARS for p in pages) or sum(map(len, pages)) > MAX_TEXT_CHARS:
            return Extraction("limits_exceeded", (), warning="Text exceeds the page or extraction budget; original remains quarantined.")
        return Extraction("ready", pages)
    # Parse hostile PDF content in a separate process with wall-time, memory and CPU limits.
    try:
        result = subprocess.run([sys.executable, "-I", "-c", _PDF_WORKER], input=content, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=20, check=False)
        if result.returncode or len(result.stdout) > 6 * MAX_TEXT_CHARS:
            return Extraction("unavailable", (), warning="PDF extraction failed or exceeded its resource budget.")
        parsed = json.loads(result.stdout)
        pages = tuple(safe_text(str(p)) for p in parsed["pages"])
        if not pages or len(pages) > MAX_PAGES or any(len(p) > MAX_PAGE_CHARS for p in pages) or sum(map(len, pages)) > MAX_TEXT_CHARS:
            return Extraction("limits_exceeded", (), warning="PDF exceeds the extraction budget.")
        if not any(p.strip() for p in pages):
            return Extraction("ocr_unavailable", pages, warning="No embedded text; OCR is not configured.")
        return Extraction("ready", pages)
    except (subprocess.TimeoutExpired, OSError, ValueError, KeyError, TypeError):
        return Extraction("unavailable", (), warning="PDF text extraction is unavailable.")


_PDF_WORKER = r'''
import io, json, sys
try:
    import resource
    resource.setrlimit(resource.RLIMIT_AS, (384 * 1024 * 1024, 384 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_CPU, (12, 12))
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(sys.stdin.buffer.read(10 * 1024 * 1024 + 1)), strict=True)
    if reader.is_encrypted or len(reader.pages) > 200:
        raise ValueError("Encrypted or excessive PDF")
    root = reader.trailer["/Root"]
    names = root.get("/Names", {})
    if hasattr(names, "get_object"):
        names = names.get_object()
    if "/OpenAction" in root or "/AA" in root or "/JavaScript" in names or "/EmbeddedFiles" in names:
        raise ValueError("Active PDF features")
    pages, total = [], 0
    for page in reader.pages:
        if "/AA" in page:
            raise ValueError("Active page actions")
        for annotation in page.get("/Annots", []):
            action = annotation.get_object().get("/A", {})
            if hasattr(action, "get_object"):
                action = action.get_object()
            if action.get("/S") in {"/JavaScript", "/Launch", "/SubmitForm", "/ImportData"}:
                raise ValueError("Active annotation actions")
        text = page.extract_text() or ""
        total += len(text)
        if len(text) > 20000 or total > 1000000:
            raise ValueError("Text budget exceeded")
        pages.append(text)
    sys.stdout.write(json.dumps({"pages": pages}))
except Exception:
    sys.exit(2)
'''

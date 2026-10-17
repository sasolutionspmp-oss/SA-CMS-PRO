"""Bounded source admission and text extraction; never an OCR, vision or AV claim."""
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
IMAGE_VALIDATOR_VERSION = "cipher-safe-image-v1"
IMAGE_MIME_TYPES = frozenset({"image/jpeg", "image/png"})
MAX_IMAGE_PIXELS = 24_000_000
MAX_IMAGE_DIMENSION = 12_000


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


def validate_source(content: bytes, filename: str, declared_size: int, declared_sha256: str, *, decode_images=True) -> str:
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
    if suffix in {"jpg", "jpeg", "png"}:
        mime = "image/png" if suffix == "png" else "image/jpeg"
        signature = b"\x89PNG\r\n\x1a\n" if suffix == "png" else b"\xff\xd8\xff"
        if not content.startswith(signature):
            raise ArtifactError("Image extension does not match its file signature.")
        if decode_images:
            _validate_image(content, mime)
        return mime
    raise ArtifactError("Only UTF-8 .txt/.text, PDF, JPEG and PNG sources are supported.")


def _validate_image(content: bytes, mime_type: str) -> None:
    # Decode hostile compressed bytes only in a short-lived process. The worker
    # applies byte, frame, dimension and pixel ceilings on every platform; POSIX
    # address-space/CPU ceilings are additional limits, not a Windows dependency.
    try:
        result = subprocess.run([sys.executable, "-I", "-c", _IMAGE_WORKER, mime_type], input=content,
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=15, check=False)
        if result.returncode or result.stdout != b"validated":
            raise ArtifactError("Image is malformed, unsupported or exceeds the image resource budget.")
    except (subprocess.TimeoutExpired, OSError) as exc:
        raise ArtifactError("Image validation is unavailable or exceeded its resource budget.") from exc


def safe_text(value: str) -> str:
    # No HTML is generated. Controls/bidi overrides have no place in evidence previews.
    return "".join(c for c in value if c in "\n\t" or (ord(c) >= 32 and ord(c) != 127 and not 0x202A <= ord(c) <= 0x202E and not 0x2066 <= ord(c) <= 0x2069))


def extract_source(content: bytes, mime_type: str) -> Extraction:
    if mime_type == "text/plain":
        pages = tuple(safe_text(part) for part in content.decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n").split("\f"))
        if len(pages) > MAX_PAGES or any(len(p) > MAX_PAGE_CHARS for p in pages) or sum(map(len, pages)) > MAX_TEXT_CHARS:
            return Extraction("limits_exceeded", (), warning="Text exceeds the page or extraction budget; original remains quarantined.")
        return Extraction("ready", pages)
    if mime_type in IMAGE_MIME_TYPES:
        # Admission has already verified the actual format and decoded pixels.
        # This empty source page is an original-image locator, never text evidence.
        return Extraction("image_text_unavailable", ("",), extractor_version=IMAGE_VALIDATOR_VERSION,
                          warning="Original image only; OCR and image interpretation are not configured. No extracted text or excerpt citation is available.")
    if mime_type != "application/pdf":
        return Extraction("unavailable", (), warning="This source format has no configured extractor.")
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


_IMAGE_WORKER = r'''
import io, struct, sys, warnings, zlib
try:
    try:
        import resource
    except ImportError:
        resource = None
    if resource is not None:
        resource.setrlimit(resource.RLIMIT_AS, (384 * 1024 * 1024, 384 * 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_CPU, (10, 10))
    from PIL import Image, ImageFile
    Image.MAX_IMAGE_PIXELS = 24_000_000
    ImageFile.LOAD_TRUNCATED_IMAGES = False
    warnings.simplefilter("error", Image.DecompressionBombWarning)
    data = sys.stdin.buffer.read(10 * 1024 * 1024 + 1)
    if not data or len(data) > 10 * 1024 * 1024:
        raise ValueError("Byte budget exceeded")
    expected = {"image/jpeg": "JPEG", "image/png": "PNG"}[sys.argv[1]]
    if expected == "PNG":
        if data[:8] != b"\x89PNG\r\n\x1a\n":
            raise ValueError("PNG signature")
        offset, chunks, ended = 8, 0, False
        while offset < len(data):
            if offset + 12 > len(data):
                raise ValueError("Truncated PNG chunk")
            length = struct.unpack_from(">I", data, offset)[0]
            end = offset + 12 + length
            if end > len(data):
                raise ValueError("Truncated PNG data")
            kind = data[offset + 4:offset + 8]
            if chunks == 0 and (kind != b"IHDR" or length != 13):
                raise ValueError("PNG header")
            if zlib.crc32(data[offset + 4:end - 4]) & 0xffffffff != struct.unpack_from(">I", data, end - 4)[0]:
                raise ValueError("PNG checksum")
            if kind in {b"acTL", b"fcTL", b"fdAT"}:
                raise ValueError("Animated PNG is unsupported")
            chunks += 1
            if kind == b"IEND":
                if length or end != len(data):
                    raise ValueError("PNG trailing data")
                ended = True
                break
            offset = end
        if not ended:
            raise ValueError("Missing PNG end")
    else:
        # Walk JPEG segment/entropy framing so the decoder cannot silently accept
        # a missing end marker, a truncated segment or appended unrelated bytes.
        if data[:3] != b"\xff\xd8\xff":
            raise ValueError("JPEG signature")
        offset, ended = 2, False
        while offset < len(data):
            if data[offset] != 255:
                raise ValueError("JPEG marker")
            while offset < len(data) and data[offset] == 255:
                offset += 1
            if offset >= len(data):
                raise ValueError("Truncated JPEG marker")
            marker = data[offset]
            offset += 1
            if marker == 217:
                if offset != len(data):
                    raise ValueError("JPEG trailing data")
                ended = True
                break
            if marker in {0, 216, 1} or 208 <= marker <= 215 or offset + 2 > len(data):
                raise ValueError("Invalid JPEG segment")
            length = struct.unpack_from(">H", data, offset)[0]
            if length < 2 or offset + length > len(data):
                raise ValueError("Truncated JPEG segment")
            offset += length
            if marker == 218:
                while offset < len(data):
                    if data[offset] != 255:
                        offset += 1
                        continue
                    start = offset
                    while offset < len(data) and data[offset] == 255:
                        offset += 1
                    if offset >= len(data):
                        raise ValueError("Truncated JPEG entropy")
                    if data[offset] == 0 or 208 <= data[offset] <= 215:
                        offset += 1
                        continue
                    offset = start
                    break
        if not ended:
            raise ValueError("Missing JPEG end")
    def inspect(image):
        width, height = image.size
        if image.format != expected or getattr(image, "n_frames", 1) != 1:
            raise ValueError("Image format or frame mismatch")
        if not 1 <= width <= 12_000 or not 1 <= height <= 12_000 or width * height > 24_000_000:
            raise ValueError("Pixel budget exceeded")
    with Image.open(io.BytesIO(data), formats=[expected]) as image:
        inspect(image)
        image.verify()
    with Image.open(io.BytesIO(data), formats=[expected]) as image:
        inspect(image)
        image.load()
    sys.stdout.buffer.write(b"validated")
except Exception:
    sys.exit(2)
'''


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

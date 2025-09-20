from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Tuple

__all__ = [
    "NormalizedChunk",
    "normalize_chunks",
    "sanitize_text",
    "collapse_whitespace",
]

_EMAIL_RE = re.compile(
    r"\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[A-Za-z]{2,}\b"
)
_PHONE_RE = re.compile(
    r"""
    (?:
        (?:(?:\+|00)\d{1,3}[\s.-]?)?
        (?:\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4})
    )
    """,
    re.VERBOSE,
)

_DEFAULT_MIN = 1500
_DEFAULT_MAX = 2000


@dataclass(frozen=True)
class NormalizedChunk:
    text: str
    index: int
    redacted: bool
    document_text: str


def collapse_whitespace(value: str) -> str:
    if not value:
        return ""
    normalized = value.replace("\r\n", "\n").replace("\r", "\n")
    normalized = re.sub(r"[ \t\f\v]+", " ", normalized)
    normalized = re.sub(r" *\n *", "\n", normalized)
    normalized = re.sub(r"\n{2,}", "\n", normalized)
    return normalized.strip()


def _apply_redactions(value: str) -> Tuple[str, bool]:
    redacted = False

    def _email_replacer(match: re.Match[str]) -> str:
        nonlocal redacted
        redacted = True
        return "[REDACTED_EMAIL]"

    def _phone_replacer(match: re.Match[str]) -> str:
        nonlocal redacted
        redacted = True
        return "[REDACTED_PHONE]"

    result = _EMAIL_RE.sub(_email_replacer, value)
    result = _PHONE_RE.sub(_phone_replacer, result)
    return result, redacted


def sanitize_text(text: str, *, redact: bool = False) -> Tuple[str, bool]:
    collapsed = collapse_whitespace(text)
    if not collapsed:
        return "", False
    if not redact:
        return collapsed, False
    return _apply_redactions(collapsed)


def _chunk_by_words(text: str, *, min_chars: int, max_chars: int) -> List[str]:
    if len(text) <= max_chars:
        return [text]

    chunks: List[str] = []
    length = len(text)
    start = 0
    while start < length:
        window_end = min(start + max_chars, length)
        end = window_end
        search_start = min(length, start + max(min_chars, 1))
        if search_start < window_end:
            breakpoint = text.rfind(" ", search_start, window_end)
            if breakpoint > start:
                end = breakpoint
        chunk = text[start:end].strip()
        if not chunk:
            end = min(start + max_chars, length)
            chunk = text[start:end].strip()
        if not chunk:
            break
        chunks.append(chunk)
        start = end
        while start < length and text[start].isspace():
            start += 1
    if len(chunks) > 1 and len(chunks[-1]) < min_chars:
        prev = chunks[-2]
        remainder = chunks[-1]
        if len(prev) + 1 + len(remainder) <= max_chars:
            chunks[-2] = f"{prev} {remainder}".strip()
            chunks.pop()
    return chunks


def normalize_chunks(
    text: str,
    *,
    redact: bool = False,
    min_chars: int = _DEFAULT_MIN,
    max_chars: int = _DEFAULT_MAX,
) -> List[NormalizedChunk]:
    if max_chars < min_chars:
        max_chars = min_chars
    sanitized, redacted_flag = sanitize_text(text, redact=redact)
    if not sanitized:
        return []
    min_chars = max(1, min_chars)
    max_chars = max(min_chars, max_chars)
    flattened = sanitized.replace("\n", " ")
    raw_chunks = _chunk_by_words(flattened, min_chars=min_chars, max_chars=max_chars)
    return [
        NormalizedChunk(text=chunk, index=idx, redacted=redacted_flag, document_text=sanitized)
        for idx, chunk in enumerate(raw_chunks)
    ]

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Sequence, Tuple
import re

__all__ = ["RiskFlag", "detect_risk_flags"]


@dataclass(frozen=True)
class RiskFlag:
    """Structured representation of a contractual risk indicator."""

    code: str
    message: str
    line: int
    snippet: str


Pattern = Tuple[str, re.Pattern[str], str]


_PATTERNS: Sequence[Pattern] = (
    (
        "liquidated_damages",
        re.compile(r"liquidated\s+damages?[^\n]*", re.IGNORECASE),
        "Liquidated damages clause present",
    ),
    (
        "bonding",
        re.compile(r"(bid|performance|payment)\s+bond[^\n]*", re.IGNORECASE),
        "Bonding requirement detected",
    ),
    (
        "no_substitutions",
        re.compile(r"no\s+substitutions?[^\n]*", re.IGNORECASE),
        "No substitutions clause present",
    ),
    (
        "warranty_anomaly",
        re.compile(r"warranty[^\n]*(\d{1,2})[-\s]?(?:year|yr)", re.IGNORECASE),
        "Extended warranty obligation",
    ),
)


def _trim_snippet(text: str, limit: int = 180) -> str:
    snippet = text.strip()
    if len(snippet) <= limit:
        return snippet
    return snippet[: limit - 3].rstrip() + "..."


def detect_risk_flags(text: str) -> List[RiskFlag]:
    """Scan text for known contractual red flags.

    Returns a de-duplicated list of `RiskFlag` entries with 1-based line
    references so downstream dashboards can deep link into documents.
    """

    if not text:
        return []

    flags: List[RiskFlag] = []
    seen: set[Tuple[str, int, str]] = set()
    lines = text.splitlines()
    for index, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line:
            continue
        for code, pattern, message in _PATTERNS:
            match = pattern.search(line)
            if not match:
                continue
            description = message
            if code == "warranty_anomaly" and match.lastindex:
                term = match.group(match.lastindex)
                description = f"Extended warranty obligation ({term}-year)"
            key = (code, index, description)
            if key in seen:
                continue
            seen.add(key)
            flags.append(
                RiskFlag(
                    code=code,
                    message=description,
                    line=index,
                    snippet=_trim_snippet(line),
                )
            )
    return flags


def detect_risk_flags_in_documents(docs: Iterable[Tuple[str, str]]) -> List[RiskFlag]:
    """Helper to run detection across an iterable of (document_id, text).

    Currently the document identifier is unused but retained for future
    correlation when we persist outputs alongside chunk metadata.
    """

    flags: List[RiskFlag] = []
    for _doc_id, text in docs:
        flags.extend(detect_risk_flags(text))
    return flags

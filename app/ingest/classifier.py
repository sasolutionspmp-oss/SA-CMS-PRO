from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, Iterable, Optional

__all__ = [
    "classify_text",
    "classify_section",
    "detect_addendum",
    "detect_revision",
]


@dataclass(frozen=True)
class SectionRule:
    label: str
    weight: int
    keywords: tuple[str, ...] = ()
    regexes: tuple[re.Pattern[str], ...] = ()
    filename_hints: tuple[str, ...] = ()
    any_keywords: bool = False


_DISCIPLINE_KEYWORDS: Dict[str, tuple[str, ...]] = {
    "CIV": ("grading", "site", "civil", "excavation"),
    "STR": ("structural", "foundation", "steel", "concrete beam"),
    "ARC": ("finish", "architectural", "interior", "casework"),
    "MEP": ("mechanical", "hvac", "pump", "ductwork", "chiller"),
    "EL": ("electrical", "lighting", "panel", "breaker", "switchgear"),
}

_SECTION_RULES: tuple[SectionRule, ...] = (
    SectionRule(
        label="instructions_to_bidders",
        weight=6,
        keywords=(
            "instructions to bidders",
            "bid submission",
            "pre-bid",
            "bidder shall",
            "bid opening",
            "procurement schedule",
        ),
        regexes=(
            re.compile(r"bid\s+(security|bond|proposal)", re.IGNORECASE),
            re.compile(r"pre-?bid\s+meeting", re.IGNORECASE),
        ),
        filename_hints=("itb", "instructions", "bidders", "bid"),
    ),
    SectionRule(
        label="general_conditions",
        weight=5,
        keywords=(
            "general conditions",
            "supplementary conditions",
            "contract conditions",
            "terms and conditions",
            "article 1",
        ),
        regexes=(re.compile(r"AIA\s*A201", re.IGNORECASE),),
        filename_hints=("general", "conditions"),
    ),
    SectionRule(
        label="specifications",
        weight=5,
        keywords=(
            "technical specifications",
            "part 1 - general",
            "part 2 - products",
            "part 3 - execution",
        ),
        regexes=(
            re.compile(r"section\s+\d{2}\s+\d{2}\s+\d{2}", re.IGNORECASE),
            re.compile(r"division\s+\d{2}", re.IGNORECASE),
        ),
        filename_hints=("spec", "specification", "section"),
    ),
    SectionRule(
        label="plans",
        weight=4,
        keywords=(
            "plan view",
            "drawing number",
            "north arrow",
            "scale 1/",
            "elevation",
        ),
        regexes=(
            re.compile(r"sheet\s*(no\.|number)\s*\w+", re.IGNORECASE),
            re.compile(r"drawing\s*(no\.|number)\s*\w+", re.IGNORECASE),
        ),
        filename_hints=("plan", "drawing", "sheet", "plt", "dwg"),
    ),
    SectionRule(
        label="schedules",
        weight=4,
        keywords=(
            "project schedule",
            "construction schedule",
            "phasing schedule",
            "milestone",
            "timeline",
        ),
        regexes=(re.compile(r"(month|week|day)\s+\d{1,2}"),),
        filename_hints=("schedule", "milestone", "phase"),
    ),
    SectionRule(
        label="addenda",
        weight=5,
        keywords=(
            "addendum",
            "addenda",
            "bulletin",
            "clarification",
        ),
        regexes=(re.compile(r"add(end(a|um))\s*(no\.?|#)?\s*\w+", re.IGNORECASE),),
        filename_hints=("addenda", "addendum", "bulletin"),
    ),
    SectionRule(
        label="safety_requirements",
        weight=3,
        keywords=(
            "safety plan",
            "osha",
            "personal protective equipment",
            "hazard",
            "ppe",
        ),
        filename_hints=("safety", "hazard", "osha"),
    ),
    SectionRule(
        label="bonds_and_insurance",
        weight=4,
        keywords=(
            "performance bond",
            "payment bond",
            "bid bond",
            "insurance requirements",
            "surety",
        ),
        regexes=(re.compile(r"bond", re.IGNORECASE),),
        filename_hints=("bond", "insurance"),
    ),
    SectionRule(
        label="pricing_forms",
        weight=3,
        keywords=(
            "bid form",
            "proposal form",
            "unit price schedule",
            "alternate bid",
            "allowance",
        ),
        filename_hints=("bidform", "proposal", "pricing"),
    ),
    SectionRule(
        label="scope_of_work",
        weight=3,
        keywords=(
            "scope of work",
            "summary of work",
            "project scope",
            "work includes",
            "executive summary",
            "project overview",
        ),
        filename_hints=("scope", "summary", "overview"),
    ),
)

_REVISION_RE = re.compile(r"REV\s*(\w+)", re.IGNORECASE)
_ADDENDUM_RE = re.compile(r"ADD(?:ENDA|END)UM\s*(\w+)", re.IGNORECASE)
_SECTION_NUMBER_RE = re.compile(r"section\s+\d{2}\s+\d{2}\s+\d{2}", re.IGNORECASE)
_PART_PATTERN = re.compile(r"PART\s+[123]\s+-", re.IGNORECASE)


def _score_keywords(text_lower: str, keywords: Iterable[str]) -> int:
    return sum(1 for keyword in keywords if keyword and keyword in text_lower)


def _score_regex(text: str, patterns: Iterable[re.Pattern[str]]) -> int:
    return sum(1 for pattern in patterns if pattern.search(text))


def classify_text(text: str) -> Optional[str]:
    lowered = text.lower()
    for label, keywords in _DISCIPLINE_KEYWORDS.items():
        if any(keyword in lowered for keyword in keywords):
            return label
    return None


def classify_section(
    text: str,
    *,
    filename: Optional[str] = None,
) -> Optional[str]:
    if not text:
        return None
    text_lower = text.lower()
    filename_lower = filename.lower() if filename else ""
    scores: Dict[str, float] = {}
    for rule in _SECTION_RULES:
        score = 0.0
        keyword_hits = _score_keywords(text_lower, rule.keywords)
        regex_hits = _score_regex(text, rule.regexes)
        filename_hits = sum(
            1 for hint in rule.filename_hints if hint and hint in filename_lower
        )
        if keyword_hits:
            score += keyword_hits * rule.weight
        if regex_hits:
            score += regex_hits * (rule.weight + 1)
        if filename_hits:
            score += filename_hits * (rule.weight * 0.8)
        if score:
            scores[rule.label] = scores.get(rule.label, 0.0) + score
    # Spec fallback using numbering patterns
    if not scores and (_SECTION_NUMBER_RE.search(text) or _PART_PATTERN.search(text)):
        scores["specifications"] = scores.get("specifications", 0.0) + 3.0
    if not scores:
        return None
    best_label, best_score = max(scores.items(), key=lambda item: item[1])
    return best_label if best_score > 0 else None


def detect_revision(text: str) -> Optional[str]:
    match = _REVISION_RE.search(text)
    if match:
        return match.group(1).upper()
    return None


def detect_addendum(text: str) -> Optional[str]:
    match = _ADDENDUM_RE.search(text)
    if match:
        return match.group(1).upper()
    return None

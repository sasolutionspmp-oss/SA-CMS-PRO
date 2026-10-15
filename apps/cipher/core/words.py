"""American English for words that people read.

A few stored codes in early tables use British spellings (the stored status value
spelled with a double "l", and the asset operation code that ends in "-ise").  Stored values stay exactly as first
written: schema history is checksummed, so a workspace refuses edited schema text, and
audit entries are hash-chained.  Nothing shown to a person should carry those spellings,
so messages that include a stored code pass it through ``us`` and the HTTP boundary passes
error text through ``us_text``.
"""
from __future__ import annotations

import re

_US = {
    "cancelled": "canceled", "cancelling": "canceling",
    "authorised": "authorized", "authorise": "authorize", "authorises": "authorizes", "authorisation": "authorization",
    "unauthorised": "unauthorized",
    "capitalise": "capitalize", "capitalised": "capitalized", "capitalisation": "capitalization",
    "normalise": "normalize", "normalised": "normalized", "normalisation": "normalization",
    "recognise": "recognize", "recognised": "recognized", "unrecognised": "unrecognized", "derecognised": "derecognized",
    "serialise": "serialize", "serialised": "serialized", "serialisable": "serializable",
    "organise": "organize", "organised": "organized", "organisation": "organization",
    "behaviour": "behavior", "labour": "labor", "colour": "color", "centre": "center", "licence": "license",
    "licences": "licenses", "labelled": "labeled", "catalogue": "catalog", "judgement": "judgment", "cheque": "check",
}
_WORD = re.compile(r"[A-Za-z]+")


def _match_case(src: str, dst: str) -> str:
    if src.isupper() and len(src) > 1:
        return dst.upper()
    if src[:1].isupper():
        return dst[:1].upper() + dst[1:]
    return dst


def us_text(text: str) -> str:
    """``text`` with every British spelling in the table replaced by the American one."""
    if not text:
        return text
    return _WORD.sub(lambda m: _match_case(m.group(0), _US.get(m.group(0).lower(), m.group(0))) if m.group(0).lower() in _US else m.group(0), text)


def us(code: object) -> str:
    """A stored code (status, operation, action) as a person should read it."""
    return us_text(str(code))

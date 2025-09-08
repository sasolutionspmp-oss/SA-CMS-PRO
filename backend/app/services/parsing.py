"""Basic file parsing utilities."""
from typing import Iterable


def parse_bytes(data: bytes) -> str:
    """Return decoded UTF-8 text from given bytes."""
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:  # pragma: no cover
        return ""


def iter_lines(text: str) -> Iterable[str]:
    for line in text.splitlines():
        yield line

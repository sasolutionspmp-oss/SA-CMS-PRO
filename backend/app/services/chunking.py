"""Simple text chunking."""
from typing import List


def chunk_text(text: str, size: int = 100) -> List[str]:
    return [text[i : i + size] for i in range(0, len(text), size)]

"""Text embedding utilities."""
import hashlib
from typing import List


def embed_text(text: str) -> List[float]:
    try:  # pragma: no cover - heavy dependency
        from sentence_transformers import SentenceTransformer

        model = SentenceTransformer("all-MiniLM-L6-v2")
        return model.encode([text])[0].tolist()
    except Exception:
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        return [b / 255 for b in digest[:8]]

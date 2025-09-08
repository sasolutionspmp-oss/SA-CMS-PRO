import json
from pathlib import Path
from typing import List

CHUNK_SIZE = 2 * 1024 * 1024  # 2MB
OVERLAP = 384


def chunk_text(text: str, out_dir: Path) -> List[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    chunks: List[Path] = []
    start = 0
    idx = 0
    while start < len(text):
        end = min(len(text), start + CHUNK_SIZE)
        chunk = text[start:end]
        path = out_dir / f"chunk_{idx}.txt"
        path.write_text(chunk)
        chunks.append(path)
        if end == len(text):
            break
        start = max(0, end - OVERLAP)
        idx += 1
    manifest = out_dir / 'manifest.ndjson'
    with manifest.open('w') as f:
        for i, p in enumerate(chunks):
            f.write(json.dumps({'idx': i, 'path': str(p)}) + '\n')
    return chunks

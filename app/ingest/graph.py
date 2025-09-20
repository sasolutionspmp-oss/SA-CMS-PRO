from __future__ import annotations

from pathlib import Path
from typing import Iterable

from app.core.config import load_config
from app.core.utils import generate_id

from .classifier import (
    classify_section,
    classify_text,
    detect_addendum,
    detect_revision,
)
from .models import DocumentGraph, DocumentNode, IngestedFile
from .normalizer import normalize_chunks
from .pdf import extract_pdf_text


TEXT_EXTENSIONS = {".txt", ".md", ".csv"}


def build_graph(project_id: str, files: Iterable[IngestedFile]) -> DocumentGraph:
    graph = DocumentGraph(project_id=project_id)
    cfg = load_config().ingest
    min_chars = getattr(cfg, "chunk_min_chars", 1500)
    max_chars = getattr(cfg, "chunk_max_chars", getattr(cfg, "chunk_size", 2000))
    redact = getattr(cfg, "redact_sensitive", False)

    for ingest_file in files:
        text = _load_text(ingest_file)
        chunks = normalize_chunks(
            text,
            redact=redact,
            min_chars=min_chars,
            max_chars=max_chars,
        )
        if not chunks:
            continue

        chunk_count = len(chunks)
        for chunk in chunks:
            metadata = dict(ingest_file.metadata)
            metadata["chunk_index"] = str(chunk.index)
            metadata["chunk_count"] = str(chunk_count)
            if chunk.redacted:
                metadata["redacted"] = "true"
            if chunk.index == 0:
                metadata["raw_text"] = chunk.document_text

            section_tag = classify_section(chunk.text, filename=str(ingest_file.path.name))
            discipline = classify_text(chunk.text)
            revision = detect_revision(chunk.text) or ""
            addendum = detect_addendum(chunk.text) or ""

            if section_tag:
                metadata["section_tag"] = section_tag
            if discipline:
                metadata.setdefault("discipline", discipline)
            if revision:
                metadata["revision"] = revision
            if addendum:
                metadata["addendum"] = addendum

            chunk_file = IngestedFile(
                path=ingest_file.path,
                mime_type=ingest_file.mime_type,
                classification=discipline or section_tag,
                text=chunk.text,
                metadata=metadata,
            )

            node = DocumentNode(
                id=generate_id("doc"),
                project_id=project_id,
                file=chunk_file,
                division=metadata.get("division"),
                section=metadata.get("section_tag") or metadata.get("section"),
                page_reference=metadata.get("page") or str(chunk.index + 1),
                chunk_index=chunk.index,
                chunk_count=chunk_count,
            )
            graph.add_node(node)
    return graph


def _load_text(ingest_file: IngestedFile) -> str:
    path = ingest_file.path
    if ingest_file.mime_type == "application/pdf" or path.suffix.lower() == ".pdf":
        return extract_pdf_text(path)
    if path.suffix.lower() in TEXT_EXTENSIONS:
        try:
            return path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return ""
    return ""

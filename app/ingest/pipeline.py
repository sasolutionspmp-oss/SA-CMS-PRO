from __future__ import annotations

import json
import time
from pathlib import Path
from typing import List

from sqlalchemy import delete

from app.core.config import load_config
from app.core.database import DocumentChunkRecord, session_scope
from app.core.audit import write_audit
from app.core.logging import get_logger
from app.core.utils import extract_zip, generate_id
from app.core.vectorstore import VectorStore
from app.core.perf import StageTimer

from .files import load_files
from .graph import build_graph
from .models import DocumentGraph, IngestedFile
from .spec_parser import parse_spec_sections

LOGGER = get_logger(__name__)


def _emit_telemetry(event: dict[str, object], *, level: str, log_path: Path | None) -> None:
    payload = json.dumps(event, sort_keys=True)
    if level == "error":
        LOGGER.error("ingest_event %s", payload)
    else:
        LOGGER.info("ingest_event %s", payload)

    if log_path is not None:
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with log_path.open("a", encoding="utf-8") as handle:
                handle.write(payload + "\n")
        except OSError as exc:
            LOGGER.debug("Unable to write ingest telemetry to %s: %s", log_path, exc)

    try:
        write_audit("ingest.telemetry", detail=event)
    except Exception as exc:  # pragma: no cover - audit failures should not impact ingest
        LOGGER.debug("Audit write failed for ingest telemetry: %s", exc)


def process_zip(zip_path: Path, project_id: str | None = None, vector_store: VectorStore | None = None) -> DocumentGraph:
    cfg = load_config()
    telemetry_enabled = bool(getattr(cfg.ingest, "telemetry_enabled", True))
    telemetry_log_path = getattr(cfg.ingest, "telemetry_log_path", None)
    start = time.perf_counter()

    project = project_id or generate_id("project")
    workspace: Path | None = None
    files: List[IngestedFile] = []
    graph: DocumentGraph | None = None
    vector_payload: list[tuple[str, str, dict[str, str]]] = []

    try:
        workspace = extract_zip(zip_path)
        files = list(load_files(workspace, project))

        with StageTimer("ingest.build_graph", project_id=project):
            graph = build_graph(project, files)

        with StageTimer("ingest.persist", project_id=project):
            _persist_chunks(graph)

        vector_payload = [
            (
                node.id,
                node.file.text,
                {
                    "project_id": node.project_id,
                    "classification": node.file.classification or "unknown",
                    "path": str(node.file.path),
                    "section": node.section or "",
                    "chunk_index": str(node.chunk_index),
                    "chunk_count": str(node.chunk_count),
                    "redacted": node.file.metadata.get("redacted", "false"),
                },
            )
            for node in graph.nodes
            if node.file.text.strip()
        ]

        if vector_payload:
            with StageTimer("ingest.vector_index", project_id=project):
                vs = vector_store or VectorStore()
                vs.add(vector_payload)
                LOGGER.info("Indexed %s nodes for project %s", len(vector_payload), project)

        with StageTimer("ingest.parse_spec", project_id=project):
            _update_spec_metadata(graph)
        duration_ms = int((time.perf_counter() - start) * 1000)
        if telemetry_enabled:
            event = {
                "event": "ingest.complete",
                "project_id": project,
                "zip_path": str(zip_path),
                "files": len(files),
                "chunks": len(graph.nodes),
                "vector_records": len(vector_payload),
                "vector_indexed": bool(vector_payload),
                "duration_ms": duration_ms,
            }
            _emit_telemetry(event, level="info", log_path=telemetry_log_path)
        return graph
    except Exception as exc:
        if telemetry_enabled:
            duration_ms = int((time.perf_counter() - start) * 1000)
            event = {
                "event": "ingest.failed",
                "project_id": project,
                "zip_path": str(zip_path),
                "files": len(files),
                "duration_ms": duration_ms,
                "error": str(exc),
                "vector_indexed": False,
            }
            _emit_telemetry(event, level="error", log_path=telemetry_log_path)
        raise


def _persist_chunks(graph: DocumentGraph) -> None:
    with session_scope() as session:
        session.execute(delete(DocumentChunkRecord).where(DocumentChunkRecord.project_id == graph.project_id))
        for node in graph.nodes:
            session.add(
                DocumentChunkRecord(
                    project_id=node.project_id,
                    source_path=str(node.file.path),
                    classification=node.file.classification or "unknown",
                    sequence=node.chunk_index,
                    content=node.file.text,
                )
            )


def _update_spec_metadata(graph: DocumentGraph) -> None:
    for node in graph.nodes:
        source_text = node.file.metadata.get("raw_text", node.file.text)
        sections = parse_spec_sections(source_text)
        if sections:
            number, title = sections[0]
            node.section = number
            node.file.metadata["section_title"] = title

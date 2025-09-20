from __future__ import annotations

from pathlib import Path

from app.core.config import load_config
from app.core.database import DocumentChunkRecord, session_scope
from app.ingest.pipeline import process_zip


class RecordingVectorStore:
    """Test double that captures vector payloads without hitting the real backend."""

    def __init__(self) -> None:
        self.payloads: list[list[tuple[str, str, dict[str, str]]]] = []

    def add(self, payload: list[tuple[str, str, dict[str, str]]]) -> None:
        self.payloads.append(list(payload))


def test_process_zip_persists_chunks_and_metadata(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "ingest.sqlite"
    monkeypatch.setenv("SA_CMS_PRO_PATHS_DATABASE", str(db_path))

    load_config.cache_clear()
    vector_store = RecordingVectorStore()
    zip_path = Path("tests/data/sample_project.zip")

    graph = process_zip(zip_path, vector_store=vector_store)

    try:
        assert len(graph.nodes) == 3
        assert vector_store.payloads, "Vector store should capture persisted chunks"

        vector_payload = vector_store.payloads[-1]
        assert len(vector_payload) == len(graph.nodes)

        expected_names = {"drawing_title.txt", "notes.txt", "spec_section.txt"}
        assert {Path(meta["path"]).name for _, _, meta in vector_payload} == expected_names
        assert all(meta["project_id"] == graph.project_id for _, _, meta in vector_payload)

        spec_node = next(node for node in graph.nodes if node.file.path.name == "spec_section.txt")
        assert spec_node.section == "03 30 00"
        assert spec_node.file.metadata.get("section_title") == "CAST-IN-PLACE CONCRETE"

        with session_scope() as session:
            persisted = [
                {
                    "source_path": row.source_path,
                    "classification": row.classification,
                    "content": row.content,
                    "sequence": row.sequence,
                }
                for row in (
                    session.query(DocumentChunkRecord)
                    .filter_by(project_id=graph.project_id)
                    .all()
                )
            ]

        ingest_cfg = load_config().ingest
        max_chars = getattr(ingest_cfg, "chunk_max_chars", getattr(ingest_cfg, "chunk_size", 2000))
        min_chars = getattr(ingest_cfg, "chunk_min_chars", 0)

        assert len(persisted) == len(graph.nodes)
        assert {Path(row["source_path"]).name for row in persisted} == expected_names
        assert {row["classification"] for row in persisted} >= {"MEP", "STR"}

        by_source: dict[str, list[dict[str, object]]] = {}
        for record in persisted:
            by_source.setdefault(record["source_path"], []).append(record)
            assert record["content"].strip()
            assert len(record["content"]) <= max_chars

        for records in by_source.values():
            sequences = sorted(rec["sequence"] for rec in records)
            assert sequences == list(range(len(records)))
            if len(records) > 1 and min_chars:
                for rec in records:
                    assert len(rec["content"]) >= min_chars
    finally:
        load_config.cache_clear()

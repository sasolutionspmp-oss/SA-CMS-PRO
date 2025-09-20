from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class IngestedFile:
    path: Path
    mime_type: str
    classification: Optional[str] = None
    text: str = ""
    metadata: Dict[str, str] = field(default_factory=dict)


@dataclass
class DocumentNode:
    id: str
    project_id: str
    file: IngestedFile
    section: Optional[str] = None
    division: Optional[str] = None
    page_reference: Optional[str] = None
    chunk_index: int = 0
    chunk_count: int = 1


@dataclass
class DocumentGraph:
    project_id: str
    nodes: List[DocumentNode] = field(default_factory=list)

    def add_node(self, node: DocumentNode) -> None:
        self.nodes.append(node)

    def by_classification(self, label: str) -> List[DocumentNode]:
        return [node for node in self.nodes if node.file.classification == label]

    def to_records(self) -> List[Dict[str, str]]:
        records: List[Dict[str, str]] = []
        for node in self.nodes:
            records.append(
                {
                    "node_id": node.id,
                    "project_id": node.project_id,
                    "path": str(node.file.path),
                    "classification": node.file.classification or "",
                    "division": node.division or "",
                    "section": node.section or "",
                    "page_reference": node.page_reference or "",
                    "chunk_index": str(node.chunk_index),
                    "chunk_count": str(node.chunk_count),
                }
            )
        return records

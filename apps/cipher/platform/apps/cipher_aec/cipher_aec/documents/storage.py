"""Immutable byte adapters. Frappe private File is the runtime default."""
from __future__ import annotations

import os
import re
from pathlib import Path
from .extraction import ArtifactError, digest


class LocalArtifactStorage:
    """Development/test adapter; callers authorize before invoking read()."""

    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)

    def put(self, revision_id: str, filename: str, content: bytes) -> str:
        if not re.fullmatch(r"[a-zA-Z0-9_-]{1,140}", revision_id):
            raise ArtifactError("Invalid artifact revision identifier.")
        target = self.root / revision_id
        # O_EXCL prevents overwriting even when the exact revision is replayed.
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
        except BaseException:
            target.unlink(missing_ok=True)
            raise
        return revision_id

    def read(self, storage_reference: str, expected_sha256: str, expected_size: int) -> bytes:
        if not re.fullmatch(r"[a-zA-Z0-9_-]{1,140}", storage_reference):
            raise ArtifactError("Invalid artifact storage reference.")
        path = self.root / storage_reference
        try:
            fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
            with os.fdopen(fd, "rb") as stream:
                content = stream.read(expected_size + 1)
        except OSError as exc:
            raise ArtifactError("Original artifact bytes are unavailable.") from exc
        return verify_bytes(content, expected_sha256, expected_size)


class FrappeFileStorage:
    def put(self, revision_id: str, filename: str, content: bytes) -> str:
        import frappe
        from cipher_aec.governance.context import trusted_write
        with trusted_write():
            # Supply bytes directly: legacy file_manager.save_file reads them back
            # through lossy text decoding before File insertion for some PDFs.
            file_doc = frappe.get_doc({"doctype": "File", "file_name": filename, "content": content,
                "attached_to_doctype": "Cipher Document Revision", "attached_to_name": revision_id,
                "is_private": 1}).insert(ignore_permissions=True)
        return file_doc.name

    def read(self, storage_reference: str, expected_sha256: str, expected_size: int) -> bytes:
        import frappe
        try:
            file_doc = frappe.get_doc("File", storage_reference)
            if not file_doc.is_private or file_doc.attached_to_doctype != "Cipher Document Revision":
                raise ArtifactError("Artifact storage mapping is invalid.")
            # Bound the disk read and preserve original bytes including BOMs.
            file_doc.validate_file_path()
            file_doc.validate_file_url()
            fd = os.open(file_doc.get_full_path(), os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
            with os.fdopen(fd, "rb") as stream:
                content = stream.read(expected_size + 1)
        except ArtifactError:
            raise
        except Exception as exc:
            raise ArtifactError("Original artifact bytes are unavailable.") from exc
        return verify_bytes(content, expected_sha256, expected_size)


def verify_bytes(content: bytes, expected_sha256: str, expected_size: int) -> bytes:
    if len(content) != expected_size or digest(content) != expected_sha256:
        raise ArtifactError("Original artifact integrity check failed.")
    return content

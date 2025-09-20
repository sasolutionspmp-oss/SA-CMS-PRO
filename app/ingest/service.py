from __future__ import annotations

import hashlib

import json

import shutil

import threading

import time

from concurrent.futures import Future, ThreadPoolExecutor

from datetime import datetime, timezone

from pathlib import Path

from types import SimpleNamespace

from typing import Any, Dict, Iterable

from sqlalchemy import func, select

from app.core.config import load_config

from app.core.database import IntakeFileRecord, IntakeRunRecord, session_scope

from app.core.logging import get_logger

from app.core.utils import generate_id

from .parsing import ParseOutcome, parse_document
from .classifier import classify_section, classify_text
from .normalizer import sanitize_text

from .schemas import (
    IntakeFileStatus,
    IntakeRunStatus,
    RiskFlagStatus,
    SummaryHighlightStatus,
)

from .risk_flagger import detect_risk_flags
from .summarizer import (
    SummaryResult,
    SummarySource,
    render_summary_markdown,
    summarize_documents,
)

LOGGER = get_logger("app.ingest.service")

SUPPORTED_EXTENSIONS: Dict[str, str] = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".csv": "text/csv",
    ".txt": "text/plain",
    ".text": "text/plain",
    ".dwg": "application/acad",
    ".dxf": "image/vnd.dxf",
}

MAX_FILE_SIZE_BYTES = 25 * 1024 * 1024


class IntakeServiceError(Exception):

    def __init__(
        self, status_code: int, message: str, detail: str, hint: str | None = None
    ) -> None:

        super().__init__(detail)

        self.status_code = status_code

        self.message = message

        self.detail = detail

        self.hint = hint


class IntakeService:

    def __init__(self, *, max_workers: int = 4) -> None:

        self._executor = ThreadPoolExecutor(max_workers=max_workers)

        self._lock = threading.Lock()

        self._inflight: dict[str, Future[Any]] = {}

        repo_root = Path(__file__).resolve().parents[2]

        self._log_path = repo_root / "logs" / "intake.log"

        self._log_path.parent.mkdir(parents=True, exist_ok=True)

    def launch(
        self, project_id: str, zip_path: str, *, background: bool = True
    ) -> IntakeRunStatus:

        project_id = project_id.strip()

        if not project_id:

            raise IntakeServiceError(
                400,
                "Invalid project",
                "Project ID cannot be empty",
                "Provide a non-empty project_id",
            )

        resolved_zip = self._normalize_zip_path(zip_path)

        self._validate_zip(resolved_zip)

        zip_hash = self._hash_file(resolved_zip)

        with session_scope() as session:

            existing = (
                session.execute(
                    select(IntakeRunRecord)
                    .where(IntakeRunRecord.project_id == project_id)
                    .where(IntakeRunRecord.zip_hash == zip_hash)
                    .order_by(IntakeRunRecord.created_at.desc())
                )
                .scalars()
                .first()
            )

            if existing:

                self._refresh_counts(session, existing)

                summary = self._build_summary(existing, session)

                LOGGER.info(
                    "Reusing existing intake run %s for project %s",
                    existing.run_id,
                    project_id,
                )

                return summary

        cfg = load_config()

        data_root = Path(cfg.paths.data_root)

        staging_dir = data_root / "staging" / project_id

        staging_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")

        staged_zip = staging_dir / f"{timestamp}.zip"

        shutil.copy2(resolved_zip, staged_zip)

        extracted_root = data_root / "intake" / project_id / "extracted" / timestamp

        extracted_root.mkdir(parents=True, exist_ok=True)

        try:

            self._extract_zip(staged_zip, extracted_root)

        except IntakeServiceError:

            raise

        except Exception as exc:  # noqa: BLE001

            raise IntakeServiceError(
                400,
                "Extraction failed",
                str(exc),
                "Ensure the ZIP file is not corrupted",
            ) from exc

        artifacts_dir = data_root / "intake" / project_id / "artifacts"

        artifacts_dir.mkdir(parents=True, exist_ok=True)

        run_id = generate_id("run")

        run_record = IntakeRunRecord(
            run_id=run_id,
            project_id=project_id,
            source_zip=str(resolved_zip),
            staged_path=str(staged_zip),
            extracted_path=str(extracted_root),
            zip_hash=zip_hash,
            status="staging",
            total_files=0,
            pending_files=0,
            parsed_files=0,
            failed_files=0,
        )

        file_records = self._prepare_file_records(
            run_record, extracted_root, artifacts_dir
        )

        pending_files = sum(
            1 for record in file_records if record.parsed_status == "pending"
        )

        eager_failures = sum(
            1 for record in file_records if record.parsed_status == "failed"
        )

        eager_failure_payloads: list[dict[str, Any]] = []

        for record in file_records:

            if record.parsed_status != "pending":

                details = record.details if isinstance(record.details, dict) else {}

                metadata = details.get("metadata") if isinstance(details, dict) else {}

                if not isinstance(metadata, dict):

                    metadata = {}

                eager_failure_payloads.append(
                    {
                        "id": record.id,
                        "run_id": record.run_id,
                        "project_id": record.project_id,
                        "rel_path": record.rel_path,
                        "mime_type": record.mime_type,
                        "size": record.size,
                        "artifact_path": record.artifact_path,
                        "parsed_status": record.parsed_status,
                        "page_count": record.page_count,
                        "error": record.error,
                        "metadata": metadata,
                    }
                )

        with session_scope() as session:

            session.add(run_record)

            for record in file_records:

                session.add(record)

            session.flush()

            run_record.total_files = len(file_records)

            run_record.pending_files = pending_files

            run_record.parsed_files = 0

            run_record.failed_files = eager_failures

            if pending_files:

                run_record.status = "parsing"

            else:

                run_record.status = "failed" if eager_failures else "ready"

                run_record.completed_at = datetime.now(timezone.utc)

            session.add(run_record)

            summary = self._build_summary(run_record, session)

            event = {
                "event": "run_launch",
                "run_id": run_record.run_id,
                "project_id": project_id,
                "files": run_record.total_files,
                "pending": pending_files,
                "failed": eager_failures,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

            self._append_log(event)

        for payload in eager_failure_payloads:

            record_stub = SimpleNamespace(
                **{k: v for k, v in payload.items() if k != "metadata"}
            )

            metadata = (
                payload.get("metadata")
                if isinstance(payload.get("metadata"), dict)
                else {}
            )

            outcome = ParseOutcome(
                status=record_stub.parsed_status,
                text="",
                metadata=metadata,
                page_count=record_stub.page_count,
                error=record_stub.error,
            )

            self._write_artifact(record_stub, outcome)

        if pending_files and background:

            self._schedule(run_id)

            return summary

        if pending_files:

            self.process_run(run_id)

            return self.get_status(run_id)

        return summary

    def process_run(self, run_id: str) -> None:

        self._process_run(run_id)

    def get_status(self, run_id: str) -> IntakeRunStatus:

        with session_scope() as session:

            run = session.get(IntakeRunRecord, run_id)

            if run is None:

                raise IntakeServiceError(
                    404,
                    "Run not found",
                    f"No intake run matches id {run_id}",
                    "Verify run_id",
                )

            self._refresh_counts(session, run)

            summary = self._build_summary(run, session)

            return summary

    # Internal helpers -----------------------------------------------------

    def _normalize_zip_path(self, zip_path: str) -> Path:

        cleaned = zip_path.strip().strip('"')

        candidate = Path(cleaned)

        if not candidate.is_absolute():

            try:

                candidate = candidate.resolve()

            except FileNotFoundError:

                candidate = (Path.cwd() / candidate).resolve()

        else:

            candidate = candidate.resolve()

        return candidate

    def _validate_zip(self, path: Path) -> None:

        if not path.exists():

            raise IntakeServiceError(
                404,
                "ZIP not found",
                f"No file at {path}",
                "Check the path or share access",
            )

        if not path.is_file():

            raise IntakeServiceError(
                400, "Invalid ZIP", f"{path} is not a file", "Provide a .zip archive"
            )

        if path.suffix.lower() != ".zip":

            raise IntakeServiceError(
                400,
                "Unsupported archive",
                "Only .zip archives are supported",
                "Compress files into a ZIP before launching intake",
            )

    def _hash_file(self, path: Path) -> str:

        digest = hashlib.sha256()

        with path.open("rb") as handle:

            for chunk in iter(lambda: handle.read(1024 * 1024), b""):

                digest.update(chunk)

        return digest.hexdigest()

    def _extract_zip(self, zip_path: Path, target_dir: Path) -> None:

        import zipfile

        try:

            with zipfile.ZipFile(zip_path) as archive:

                archive.extractall(target_dir)

        except zipfile.BadZipFile as exc:

            raise IntakeServiceError(
                400,
                "Corrupt ZIP",
                "Unable to read archive contents",
                "Recreate the archive and retry",
            ) from exc

    def _prepare_file_records(
        self, run: IntakeRunRecord, extracted_root: Path, artifacts_dir: Path
    ) -> list[IntakeFileRecord]:

        records: list[IntakeFileRecord] = []

        for path in self._iter_supported_files(extracted_root):

            try:

                size = path.stat().st_size

            except OSError:

                continue

            rel_path = path.relative_to(extracted_root).as_posix()

            mime = SUPPORTED_EXTENSIONS[path.suffix.lower()]

            checksum = self._hash_file(path)

            file_id = generate_id("file")

            artifact_path = artifacts_dir / f"{file_id}.json"

            status = "pending"

            error: str | None = None

            metadata = {"mime": mime}

            if size > MAX_FILE_SIZE_BYTES:

                status = "failed"

                error = f"File exceeds {MAX_FILE_SIZE_BYTES // (1024 * 1024)}MB guard"

                metadata["skipped"] = True

            records.append(
                IntakeFileRecord(
                    id=file_id,
                    run_id=run.run_id,
                    project_id=run.project_id,
                    rel_path=rel_path,
                    mime_type=mime,
                    size=size,
                    checksum=checksum,
                    parsed_status=status,
                    error=error,
                    artifact_path=str(artifact_path),
                    details={"metadata": metadata, "snippet": None},
                )
            )

        return records

    def _iter_supported_files(self, root: Path) -> Iterable[Path]:

        for path in root.rglob("*"):

            if not path.is_file():

                continue

            suffix = path.suffix.lower()

            if suffix in SUPPORTED_EXTENSIONS:

                yield path

    def _schedule(self, run_id: str) -> None:

        with self._lock:

            if run_id in self._inflight:

                return

            future = self._executor.submit(self._process_run, run_id)

            self._inflight[run_id] = future

            future.add_done_callback(
                lambda _f, rid=run_id: self._inflight.pop(rid, None)
            )

    def _process_run(self, run_id: str) -> None:
        start = time.perf_counter()
        try:
            with session_scope() as session:
                run = session.get(IntakeRunRecord, run_id)
                if run is None:
                    return
                run.status = "parsing"
                session.add(run)

            file_ids = self._get_pending_file_ids(run_id)
            for file_id in file_ids:
                self._process_file(run_id, file_id)

            with session_scope() as session:
                run = session.get(IntakeRunRecord, run_id)
                if run is None:
                    return
                self._refresh_counts(session, run)
                generated_flags: list[RiskFlagStatus] | None = None
                risk_generated_at: datetime | None = None
                generated_highlights: list[SummaryHighlightStatus] | None = None
                summary_generated_at: datetime | None = None
                if run.pending_files == 0:
                    run.completed_at = run.completed_at or datetime.now(timezone.utc)
                    generated_flags, risk_generated_at = self._generate_risk_flags(
                        session, run
                    )
                    try:
                        generated_highlights, summary_generated_at = (
                            self._generate_summary_highlights(session, run)
                        )
                    except Exception as exc:  # noqa: BLE001
                        LOGGER.debug(
                            "Summary highlight generation failed for %s: %s",
                            run.run_id,
                            exc,
                        )
                        generated_highlights = []
                        summary_generated_at = None
                session.add(run)
                summary = self._build_summary(run, session)
                if generated_flags is not None:
                    summary.risk_flags = generated_flags
                    summary.risk_generated_at = risk_generated_at
                if generated_highlights is not None:
                    summary.summary_highlights = generated_highlights
                    summary.summary_generated_at = summary_generated_at

            duration_ms = int((time.perf_counter() - start) * 1000)
            event = {
                "event": "run_complete",
                "run_id": run_id,
                "project_id": summary.project_id,
                "status": summary.status,
                "duration_ms": duration_ms,
                "parsed": summary.parsed,
                "failed": summary.failed,
                "risk_flags": len(summary.risk_flags),
                "summary_highlights": len(summary.summary_highlights),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            self._append_log(event)
        except Exception as exc:  # noqa: BLE001
            LOGGER.exception("Intake run %s failed", run_id)
            with session_scope() as session:
                run = session.get(IntakeRunRecord, run_id)
                if run is not None:
                    run.status = "failed"
                    run.last_error = str(exc)
                    run.completed_at = datetime.now(timezone.utc)
                    session.add(run)
            duration_ms = int((time.perf_counter() - start) * 1000)
            event = {
                "event": "run_failed",
                "run_id": run_id,
                "error": str(exc),
                "duration_ms": duration_ms,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            self._append_log(event)

    def _get_pending_file_ids(self, run_id: str) -> list[str]:

        with session_scope() as session:

            rows = (
                session.execute(
                    select(IntakeFileRecord.id)
                    .where(IntakeFileRecord.run_id == run_id)
                    .where(IntakeFileRecord.parsed_status == "pending")
                    .order_by(IntakeFileRecord.rel_path)
                )
                .scalars()
                .all()
            )

            return list(rows)

    def _process_file(self, run_id: str, file_id: str) -> None:

        ingest_cfg = load_config().ingest
        redact_sensitive = getattr(ingest_cfg, "redact_sensitive", False)

        with session_scope() as session:

            record = session.get(IntakeFileRecord, file_id)

            run = session.get(IntakeRunRecord, run_id)

            if record is None or run is None:

                return

            if record.parsed_status != "pending":

                self._refresh_counts(session, run)

                return

            file_path = Path(run.extracted_path) / Path(record.rel_path)

            if not file_path.exists():

                record.parsed_status = "failed"

                record.error = "Extracted file not found"

                record.updated_at = datetime.now(timezone.utc)

                session.add(record)

                self._refresh_counts(session, run)

                return

            outcome = parse_document(file_path, record.mime_type)
            sanitized_text, redacted_flag = sanitize_text(
                outcome.text, redact=redact_sensitive
            )
            outcome.text = sanitized_text
            section_tag = classify_section(outcome.text, filename=record.rel_path)
            discipline = classify_text(outcome.text)
            metadata = outcome.metadata if isinstance(outcome.metadata, dict) else {}
            if redacted_flag:
                metadata["redacted"] = "true"
            if section_tag:
                metadata["section_tag"] = section_tag
            if discipline:
                metadata.setdefault("discipline", discipline)
            outcome.metadata = metadata

            record.parsed_status = (
                outcome.status if outcome.status in {"parsed", "failed"} else "parsed"
            )

            record.error = outcome.error

            record.page_count = outcome.page_count

            record.details = {"metadata": outcome.metadata, "snippet": outcome.snippet}

            record.updated_at = datetime.now(timezone.utc)

            session.add(record)

            session.flush()

            self._write_artifact(record, outcome)

            self._refresh_counts(session, run)

    def _write_artifact(self, record: IntakeFileRecord, outcome: ParseOutcome) -> None:

        artifact_path = Path(record.artifact_path)

        artifact_path.parent.mkdir(parents=True, exist_ok=True)

        payload = {
            "file_id": record.id,
            "run_id": record.run_id,
            "project_id": record.project_id,
            "rel_path": record.rel_path,
            "mime": record.mime_type,
            "size": record.size,
            "parsed_status": record.parsed_status,
            "page_count": record.page_count,
            "snippet": outcome.snippet,
            "metadata": outcome.metadata,
            "error": outcome.error,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "text": outcome.text,
        }

        try:

            artifact_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )

        except OSError as exc:

            LOGGER.debug("Failed to write artifact %s: %s", artifact_path, exc)

    def _refresh_counts(self, session, run: IntakeRunRecord) -> None:

        rows = session.execute(
            select(IntakeFileRecord.parsed_status, func.count(IntakeFileRecord.id))
            .where(IntakeFileRecord.run_id == run.run_id)
            .group_by(IntakeFileRecord.parsed_status)
        ).all()

        counts = {status: count for status, count in rows}

        total = sum(counts.values())

        run.total_files = total

        run.pending_files = counts.get("pending", 0)

        run.parsed_files = counts.get("parsed", 0)

        run.failed_files = counts.get("failed", 0)

        run.updated_at = datetime.now(timezone.utc)

        if run.pending_files == 0:

            if run.failed_files:

                run.status = "failed"

            else:

                run.status = "ready"

        else:

            run.status = "parsing"

        session.add(run)

    def _risk_flags_path(self, project_id: str, zip_hash: str) -> Path:

        cfg = load_config()

        data_root = Path(cfg.paths.data_root)

        return data_root / "uploads" / project_id / zip_hash / "risk_flags.json"

    def _generate_risk_flags(
        self, session, run: IntakeRunRecord
    ) -> tuple[list[RiskFlagStatus], datetime]:

        records = (
            session.execute(
                select(IntakeFileRecord)
                .where(IntakeFileRecord.run_id == run.run_id)
                .where(IntakeFileRecord.parsed_status == "parsed")
            )
            .scalars()
            .all()
        )

        flags: list[RiskFlagStatus] = []

        seen: set[tuple[str, str, int]] = set()

        for record in records:

            artifact_path = Path(record.artifact_path)

            try:

                raw_text = artifact_path.read_text(encoding="utf-8")

            except OSError as exc:

                LOGGER.debug("Artifact not available for %s: %s", record.id, exc)

                continue

            try:

                payload = json.loads(raw_text)

            except json.JSONDecodeError as exc:

                LOGGER.debug("Malformed artifact %s: %s", artifact_path, exc)

                continue

            text = payload.get("text") or ""

            if not text:

                continue

            for flag in detect_risk_flags(text):

                key = (record.id, flag.code, flag.line)

                if key in seen:

                    continue

                seen.add(key)

                flags.append(
                    RiskFlagStatus(
                        file_id=record.id,
                        rel_path=record.rel_path,
                        code=flag.code,
                        message=flag.message,
                        line=flag.line,
                        snippet=flag.snippet,
                        run_id=run.run_id,
                        project_id=run.project_id,
                    )
                )

        generated_at = datetime.now(timezone.utc)

        payload = {
            "run_id": run.run_id,
            "project_id": run.project_id,
            "zip_hash": run.zip_hash,
            "generated_at": generated_at.isoformat(),
            "flags": [flag.model_dump() for flag in flags],
        }

        path_out = self._risk_flags_path(run.project_id, run.zip_hash)

        path_out.parent.mkdir(parents=True, exist_ok=True)

        try:

            path_out.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )

        except OSError as exc:

            LOGGER.debug("Failed to persist risk flags for %s: %s", run.run_id, exc)

        return flags, generated_at

    def _summary_highlights_path(self, project_id: str, zip_hash: str) -> Path:

        cfg = load_config()

        data_root = Path(cfg.paths.data_root)

        return data_root / "uploads" / project_id / zip_hash / "summary_highlights.json"

    def _summary_markdown_path(self, project_id: str, zip_hash: str) -> Path:

        cfg = load_config()

        data_root = Path(cfg.paths.data_root)

        return data_root / "uploads" / project_id / zip_hash / "summary.md"

    def _generate_summary_highlights(
        self, session, run: IntakeRunRecord
    ) -> tuple[list[SummaryHighlightStatus], datetime]:

        records = (
            session.execute(
                select(IntakeFileRecord)
                .where(IntakeFileRecord.run_id == run.run_id)
                .where(IntakeFileRecord.parsed_status == "parsed")
            )
            .scalars()
            .all()
        )

        sources: list[SummarySource] = []

        for record in records:
            artifact_path = Path(record.artifact_path)

            try:
                raw_text = artifact_path.read_text(encoding="utf-8")
            except OSError as exc:
                LOGGER.debug("Artifact not available for %s: %s", record.id, exc)
                continue

            try:
                payload = json.loads(raw_text)
            except json.JSONDecodeError as exc:
                LOGGER.debug("Malformed artifact %s: %s", artifact_path, exc)
                continue

            text_value = payload.get("text") or ""
            if not text_value.strip():
                continue

            sources.append(
                SummarySource(
                    document_id=record.id,
                    rel_path=record.rel_path,
                    text=text_value,
                )
            )

        summary_result = summarize_documents(sources, max_sentences=8)

        highlights: list[SummaryHighlightStatus] = []
        for item in summary_result.highlights:
            highlights.append(
                SummaryHighlightStatus(
                    file_id=item.document_id,
                    rel_path=item.rel_path,
                    snippet=item.snippet,
                    score=item.score,
                    rank=item.rank,
                    run_id=run.run_id,
                    project_id=run.project_id,
                )
            )

        generated_at = datetime.now(timezone.utc)

        payload = {
            "run_id": run.run_id,
            "project_id": run.project_id,
            "zip_hash": run.zip_hash,
            "generated_at": generated_at.isoformat(),
            "highlights": [highlight.model_dump() for highlight in highlights],
            "overview": summary_result.overview,
            "word_count": summary_result.word_count,
            "documents": summary_result.document_count,
        }

        path_out = self._summary_highlights_path(run.project_id, run.zip_hash)
        summary_md_path = self._summary_markdown_path(run.project_id, run.zip_hash)

        summary_md_path.parent.mkdir(parents=True, exist_ok=True)
        path_out.parent.mkdir(parents=True, exist_ok=True)

        try:
            path_out.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except OSError as exc:
            LOGGER.debug(
                "Failed to persist summary highlights for %s: %s", run.run_id, exc
            )

        markdown = render_summary_markdown(
            summary_result, generated_at=generated_at.isoformat()
        )
        try:
            summary_md_path.write_text(markdown, encoding="utf-8")
        except OSError as exc:
            LOGGER.debug("Failed to write summary markdown for %s: %s", run.run_id, exc)

        return highlights, generated_at

    def _load_summary_highlights(
        self, project_id: str, zip_hash: str
    ) -> tuple[list[SummaryHighlightStatus], datetime | None]:

        path_out = self._summary_highlights_path(project_id, zip_hash)

        if not path_out.exists():
            return [], None

        try:
            payload = json.loads(path_out.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            LOGGER.debug(
                "Unable to read summary highlights for %s/%s: %s",
                project_id,
                zip_hash,
                exc,
            )
            return [], None

        generated_raw = payload.get("generated_at")

        generated_at: datetime | None = None
        if isinstance(generated_raw, str):
            try:
                generated_at = datetime.fromisoformat(generated_raw)
            except ValueError:
                LOGGER.debug(
                    "Invalid summary generated_at timestamp for %s/%s",
                    project_id,
                    zip_hash,
                )

        highlights: list[SummaryHighlightStatus] = []

        raw_highlights = payload.get("highlights")

        if isinstance(raw_highlights, list):
            for entry in raw_highlights:
                if not isinstance(entry, dict):
                    continue
                try:
                    highlights.append(SummaryHighlightStatus(**entry))
                except Exception as exc:  # noqa: BLE001
                    LOGGER.debug(
                        "Skipping malformed summary highlight entry for %s/%s: %s",
                        project_id,
                        zip_hash,
                        exc,
                    )

        return highlights, generated_at

    def _load_risk_flags(
        self, project_id: str, zip_hash: str
    ) -> tuple[list[RiskFlagStatus], datetime | None]:

        path_out = self._risk_flags_path(project_id, zip_hash)

        if not path_out.exists():

            return [], None

        try:

            payload = json.loads(path_out.read_text(encoding="utf-8"))

        except (OSError, json.JSONDecodeError) as exc:

            LOGGER.debug(
                "Unable to read risk flags for %s/%s: %s", project_id, zip_hash, exc
            )

            return [], None

        generated_raw = payload.get("generated_at")

        generated_at: datetime | None = None

        if isinstance(generated_raw, str):

            try:

                generated_at = datetime.fromisoformat(generated_raw)

            except ValueError:

                LOGGER.debug(
                    "Invalid generated_at timestamp for %s/%s", project_id, zip_hash
                )

        flags: list[RiskFlagStatus] = []

        raw_flags = payload.get("flags")

        if isinstance(raw_flags, list):

            for entry in raw_flags:

                if not isinstance(entry, dict):

                    continue

                try:

                    flags.append(RiskFlagStatus(**entry))

                except Exception as exc:  # noqa: BLE001

                    LOGGER.debug(
                        "Skipping malformed risk flag entry for %s/%s: %s",
                        project_id,
                        zip_hash,
                        exc,
                    )

        return flags, generated_at

    def _build_summary(self, run: IntakeRunRecord, session) -> IntakeRunStatus:

        files = (
            session.execute(
                select(IntakeFileRecord)
                .where(IntakeFileRecord.run_id == run.run_id)
                .order_by(IntakeFileRecord.rel_path)
            )
            .scalars()
            .all()
        )

        items: list[IntakeFileStatus] = []

        for record in files:

            details = record.details or {}

            metadata = details.get("metadata") if isinstance(details, dict) else {}

            snippet = details.get("snippet") if isinstance(details, dict) else None

            updated = record.updated_at or run.updated_at or run.created_at

            items.append(
                IntakeFileStatus(
                    id=record.id,
                    project_id=record.project_id,
                    rel_path=record.rel_path,
                    mime=record.mime_type,
                    size=record.size,
                    parsed_status=record.parsed_status,
                    updated_at=updated,
                    error=record.error,
                    page_count=record.page_count,
                    checksum=record.checksum,
                    artifact_path=record.artifact_path,
                    metadata=metadata if isinstance(metadata, dict) else {},
                    snippet=snippet if isinstance(snippet, str) else None,
                )
            )

        risk_flags, risk_generated_at = self._load_risk_flags(
            run.project_id, run.zip_hash
        )

        summary_highlights, summary_generated_at = self._load_summary_highlights(
            run.project_id, run.zip_hash
        )

        started_at = run.started_at or run.created_at

        updated_at = run.updated_at or run.created_at

        return IntakeRunStatus(
            run_id=run.run_id,
            project_id=run.project_id,
            status=run.status,
            total=run.total_files,
            pending=run.pending_files,
            parsed=run.parsed_files,
            failed=run.failed_files,
            started_at=started_at,
            updated_at=updated_at,
            completed_at=run.completed_at,
            items=items,
            risk_flags=risk_flags,
            risk_generated_at=risk_generated_at,
            summary_highlights=summary_highlights,
            summary_generated_at=summary_generated_at,
        )

    def _append_log(self, event: Dict[str, Any]) -> None:

        try:

            with self._log_path.open("a", encoding="utf-8") as handle:

                handle.write(json.dumps(event) + "\n")

        except OSError as exc:

            LOGGER.debug("Unable to append intake log: %s", exc)


intake_service = IntakeService()

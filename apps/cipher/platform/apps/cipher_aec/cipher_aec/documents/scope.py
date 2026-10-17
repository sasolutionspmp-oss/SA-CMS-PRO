"""Exact source ownership; an absent Project never selects Company implicitly."""
from .extraction import ArtifactError


def scope_of(row):
    # Historical Project rows predate the additive field. Runtime migration
    # backfills it; the fallback preserves existing in-process integrations.
    kind = row.get("scope_type") or "Project"
    project = row.get("project")
    if kind == "Project" and (type(project) is not str or not project):
        raise ArtifactError("Document is outside the requested scope.")
    if kind == "Company" and project is not None:
        raise ArtifactError("Document is outside the requested scope.")
    if kind not in ("Project", "Company"):
        raise ArtifactError("Document is outside the requested scope.")
    return kind


def company_fields(row):
    return {"scope_type":"Company", "company":row["company"], "project":None} if scope_of(row) == "Company" else {}

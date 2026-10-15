"""Read-only canonical format tools; no external import application endpoint."""
from cipher_aec.api.contracts import text
from cipher_aec.api.errors import DomainError
from cipher_aec.api.transport import endpoint
from . import export, preview
from .validation import ManifestError, manifest_digest, manifest_requirements, parse_manifest, quantity_previews


def _call(callback):
    try:
        return callback()
    except ManifestError as error:
        raise DomainError("invalid_manifest", error.message, 422, {"path": error.path}) from None


def _scope(manifest, company, project):
    parsed = parse_manifest(manifest)
    if parsed["scope"] != {"company": company, "project": project}:
        raise DomainError("manifest_scope_mismatch", "Manifest scope must match your current company and project.", 422)
    return parsed


@endpoint(methods=["POST"])
def validate_manifest(company, project, manifest):
    company, project = text(company, "Company"), text(project, "Project")
    export.FrappeTargetReader(company, project)  # Current identity and project scope before any response.
    def validate():
        parsed = _scope(manifest, company, project)
        return {"schema": "cipher.canonical.validation.v1", "valid": True,
            "manifest_sha256": manifest_digest(parsed), "record_count": len(parsed["records"]),
            "conversion_count": len(parsed["unit_conversions"]), "quantity_previews": quantity_previews(parsed),
            "target_existence_checked": False, "apply_available": False, "writes_performed": 0,
            "setup_requirements": manifest_requirements(parsed)}
    return _call(validate)


@endpoint(methods=["POST"])
def preview_manifest(company, project, manifest):
    company, project = text(company, "Company"), text(project, "Project")
    reader = export.FrappeTargetReader(company, project)
    return _call(lambda: preview.preview_manifest(_scope(manifest, company, project), reader.snapshot))


@endpoint(methods=["POST"])
def export_records(company, project, dataset_id, references, unit_conversions=None, quantities=None):
    company, project = text(company, "Company"), text(project, "Project")
    reader = export.FrappeTargetReader(company, project)
    return _call(lambda: export.export_records(company=company, project=project, dataset_id=dataset_id,
        references=references, reader=reader, unit_conversions=unit_conversions, quantities=quantities))

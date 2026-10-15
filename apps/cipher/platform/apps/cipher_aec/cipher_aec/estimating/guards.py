"""Native UOM qualification cannot change under an existing calculation."""

from cipher_aec.api.errors import DomainError
from cipher_aec.governance.context import require_trusted_write
from cipher_aec.migrations.contracts import DIMENSIONS

from .contracts import identifier, precision

FIELDS = ("cipher_unit_id", "cipher_dimension", "cipher_quantity_precision", "cipher_unit_revision")


def validate_uom(doc, method=None):
    before = doc.get_doc_before_save()
    # New ordinary ERPNext UOMs remain unqualified; no dimension is guessed.
    configured = bool(doc.get("cipher_unit_id") or doc.get("cipher_dimension") or doc.get("cipher_unit_revision"))
    old_configured = bool(before and before.get("cipher_unit_id"))
    changed = any(doc.get(key) != (before.get(key) if before else None) for key in FIELDS)
    if not configured and not old_configured:
        if doc.get("cipher_quantity_precision") not in (None, 0):
            raise DomainError("unit_setup_required", "Quantity precision requires an explicit qualified unit identity.")
        return
    if changed:
        require_trusted_write()
    if old_configured and (changed or any(doc.get(key) != before.get(key) for key in ("uom_name", "symbol", "must_be_whole_number"))):
        raise DomainError("immutable_unit", "A qualified unit's identity, dimension and precision are immutable. Register a distinct unit.", 409)
    identifier(doc.get("cipher_unit_id"), "unit.id")
    if doc.get("cipher_dimension") not in DIMENSIONS:
        raise DomainError("invalid_dimension", "Declare the unit's exact supported dimension.")
    precision(doc.get("cipher_quantity_precision"), "unit.precision")
    if doc.get("cipher_unit_revision") != 1:
        raise DomainError("invalid_unit_revision", "A qualified native unit starts at immutable revision one.")
    if doc.get("must_be_whole_number") and doc.get("cipher_quantity_precision") != 0:
        raise DomainError("invalid_unit_precision", "A whole-number UOM requires quantity precision zero.")


def prevent_qualified_uom_delete(doc, method=None):
    if doc.get("cipher_unit_id"):
        raise DomainError("immutable_unit", "A qualified unit cannot be deleted or renamed; disable it for future use.", 409)


def prevent_qualified_uom_rename(doc, method=None, *args, **kwargs):
    prevent_qualified_uom_delete(doc)

"""Inactive AI-04 read/draft contracts; none of these values grants authority."""
from dataclasses import dataclass
import re
from uuid import UUID

from .contracts import RickyError
from .tools import object_schema, validate


def identifier(value):
    if type(value) is not str:
        raise RickyError("validation_error", "Use a canonical record UUID.")
    try:
        parsed = UUID(value)
    except (ValueError, TypeError, AttributeError):
        raise RickyError("validation_error", "Use a canonical record UUID.") from None
    if str(parsed) != value or parsed.version not in (4, 5):
        raise RickyError("validation_error", "Use a canonical record UUID.")
    return value


@dataclass(frozen=True)
class SourceReference:
    citation_id: str
    revision_id: str
    page: int
    excerpt_sha256: str
    source_sha256: str

    def __post_init__(self):
        if (type(self.revision_id) is not str or not 1 <= len(self.revision_id) <= 160
                or type(self.page) is not int or not 1 <= self.page <= 100000
                or any(type(value) is not str or re.fullmatch("[a-f0-9]{64}", value) is None
                       for value in (self.citation_id, self.excerpt_sha256, self.source_sha256))):
            raise RickyError("validation_error", "Use an exact selected source reference.")


@dataclass(frozen=True)
class CompanyReadContext:
    """Explicit caller-selected scope, deliberately distinct from Authority.

    A future durable run adapter must bind this to its authenticated authority.
    The concrete reader reauthorizes the actual current actor on every access.
    """
    user: str
    person: str
    company: str
    pursuit_id: str
    sources: tuple[SourceReference, ...] = ()
    measurement_ids: tuple[str, ...] = ()

    def __post_init__(self):
        for value in (self.user, self.person, self.company):
            if type(value) is not str or not 1 <= len(value) <= 140 or any(ord(c) < 32 for c in value):
                raise RickyError("validation_error", "Use explicit Company read context identifiers.")
        identifier(self.pursuit_id)
        if (type(self.sources) is not tuple or len(self.sources) > 8
                or any(type(source) is not SourceReference for source in self.sources)
                or len({source.citation_id for source in self.sources}) != len(self.sources)
                or type(self.measurement_ids) is not tuple or len(self.measurement_ids) > 8):
            raise RickyError("validation_error", "Use bounded exact source and measurement selections.")
        for value in self.measurement_ids:
            identifier(value)
        if len(set(self.measurement_ids)) != len(self.measurement_ids):
            raise RickyError("validation_error", "Do not duplicate selected measurements.")


ID = {"type": "string", "minLength": 36, "maxLength": 36}
TEXT = {"type": "string", "maxLength": 2000}
HASH = {"type": "string", "minLength": 64, "maxLength": 64}
BOOL = {"type": "boolean"}
def array(items, maximum=8):
    return {"type": "array", "items": items, "maxItems": maximum}
def obj(fields):
    return object_schema(fields, tuple(fields))

SCOPE = {"scope_type": {"type": "string", "enum": ["Company"]}, "company": TEXT, "pursuit_id": ID}
MONEY = obj({"amount": {"type": "string", "maxLength": 80}, "currency": {"type": "string", "minLength": 3, "maxLength": 3}})
RECORD = obj({"kind": {"type": "string", "maxLength": 40}, "id": ID, "digest": HASH})
SOURCE = obj({"citation_id": HASH, "document_id": {"type": "string", "maxLength": 160},
    "revision_id": {"type": "string", "maxLength": 160}, "page": {"type": "integer", "minimum": 1, "maximum": 100000},
    "excerpt_sha256": HASH, "source_sha256": HASH, "canonical_digest": HASH})
QUANTITY_REQUEST = obj({"source_kind": {"type": "string", "enum": ["estimate-line", "measurement"]}, "source_id": ID, "target_unit_id": ID})
QUANTITY = obj({"source_kind": {"type": "string", "enum": ["estimate-line", "measurement"]}, "source_id": ID,
    "source_digest": HASH, "source_unit_id": ID, "target_unit_id": ID,
    "numerator": {"type": "string", "maxLength": 2600}, "denominator": {"type": "string", "maxLength": 2600},
    "provenance": {"type": "string", "enum": ["authored-estimate-line", "manual-measurement", "calibrated-measurement"]},
    "quantity_basis": {"type": "string", "enum": ["authored-line-v1", "net-quantity-v1", "after-takeoff-waste-v1"]},
    "independently_verified": BOOL, "eligible_for_new_use": BOOL, "model_supplied_quantity": {"type": "boolean", "enum": [False]}})
SECTION = obj({"heading": {"type": "string", "minLength": 1, "maxLength": 200}, "text": TEXT, "citation_ids": array(HASH)})
SELECTION = obj({"line_record_id": ID, **QUANTITY_REQUEST["properties"]})
DRAFT_COMMON = {**SCOPE, "persistent": {"type": "boolean", "enum": [False]}, "review_required": {"type": "boolean", "enum": [True]},
    "claim_classification": {"type": "string", "enum": ["unverified-author-suggestion"]},
    "verified_source_references": array(SOURCE), "unverified_claims": array(TEXT), "record_dependencies": array(RECORD, 32), "draft_digest": HASH}

SCHEMAS = {
    "aec.pursuit.lookup": (obj({}), obj({**SCOPE, "record_digest": HASH, "revision_number": {"type": "integer", "minimum": 1}, "title": TEXT})),
    "aec.estimate.recompute": (obj({"revision_id": ID}), obj({**SCOPE, "revision_id": ID, "revision_digest": HASH,
        "snapshot_id": ID, "input_digest": HASH, "output_digest": HASH, "policy_version": TEXT, "total": MONEY,
        "quantity_basis": {"type": "string", "enum": ["authored-original-snapshot"]}, "current_working_revision": BOOL})),
    "aec.estimate.compare": (obj({"left_revision_id": ID, "right_revision_id": ID}), obj({**SCOPE,
        "left_revision_id": ID, "right_revision_id": ID, "left_digest": HASH, "right_digest": HASH,
        "currency": {"type": "string", "minLength": 3, "maxLength": 3}, "total_delta": {"type": "string", "maxLength": 80},
        "changed_line_ids": array(ID, 200)})),
    "aec.quantity.convert": (QUANTITY_REQUEST, QUANTITY),
    "aec.scope.draft": (obj({"proposal_revision_id": ID, "sections": array(SECTION), "unverified_claims": array(TEXT)}),
        obj({**DRAFT_COMMON, "kind": {"type": "string", "enum": ["scope-draft.v1"]}, "proposed_fields": obj({"sections": array(SECTION)})})),
    "aec.estimate.draft": (obj({"base_revision_id": ID, "selections": array(SELECTION), "notes": TEXT,
        "citation_ids": array(HASH), "unverified_claims": array(TEXT)}),
        obj({**DRAFT_COMMON, "kind": {"type": "string", "enum": ["estimate-draft.v1"]},
            "proposed_fields": obj({"quantity_selections": array(obj({"line_record_id": ID, "quantity": QUANTITY})), "notes": TEXT})})),
}


def inputs(name, arguments):
    # Central ToolRegistry validation remains unchanged. Extra semantic/UUID
    # validation lives only in this inactive package and canonical readers.
    validate(SCHEMAS[name][0], arguments)
    return arguments

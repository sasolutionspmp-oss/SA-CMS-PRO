"""Source-only authority of generated output; never follows output references."""
from cipher_aec.api.contracts import digest, text
from cipher_aec.api.errors import DomainError
from . import sources

SCHEMA = "cipher.proposal.output.input.v1"


def recipients(value):
    from .contracts import keys
    if type(value) is not list or not 1 <= len(value) <= 30:
        raise DomainError("invalid_commercial", "Declare between one and thirty intended recipients.")
    result = []
    for row in value:
        keys(row, ("name", "email", "organization"), ("name", "email", "organization"))
        normalized = {"name": text(row["name"], "Recipient name"), "email": text(row["email"], "Recipient email", 254), "organization": text(row["organization"], "Recipient organization", 200, required=False)}
        import re
        if not re.fullmatch(r"[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+", normalized["email"]):
            raise DomainError("invalid_commercial", "Declare a plain recipient email address.")
        if normalized["email"].casefold() in {r["email"].casefold() for r in result}:
            raise DomainError("invalid_commercial", "Declare each recipient once.")
        result.append(normalized)
    return result


def build_binding(revision, baseline, to, cover, renderer):
    if baseline is None:
        raise DomainError("accepted_estimate_required", "Prepare issue output from an exact accepted estimate baseline.", 409)
    return {"schema": SCHEMA, "company": revision["company"], "proposal_id": revision["proposal"],
            "proposal_revision_id": revision["id"], "proposal_revision_digest": digest(revision),
            "native_fingerprint": revision["native_fingerprint"], "accepted_estimate": baseline,
            "source_citations": revision.get("source_citations", []),
            "recipients": recipients(to), "cover": text(cover, "Cover text", 12000, required=False),
            "renderer": renderer}


def binding_plan(binding, actor, *, lock=False):
    # Only immutable IDs/integrity and scoped duties here; content rights follow
    # after the caller takes the complete union of its own and these resources.
    return sources.revision_plan(binding["company"], binding["proposal_revision_id"], actor, lock=lock)


def authorize_binding(binding, actor, *, lock=False):
    from .service import _actor, _read
    company = binding["company"]
    _actor(company, actor, lock=lock)
    # Do not manufacture a lock admission here: outer mutation callers have
    # already merged this plan. Ordinary read-only checks take no source locks.
    revision = _read("revision", binding["proposal_revision_id"], company, actor, lock=lock)[1]
    expected = build_binding(revision, revision.get("accepted_estimate"), binding["recipients"], binding["cover"], binding["renderer"])
    if binding != expected:
        raise DomainError("source_integrity", "The generated output's immutable source binding cannot be verified.", 409)
    return revision

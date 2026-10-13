"""Contract approval, signature and insurance / bond evidence (governor plugin, prefix ``contract``).

Plan section 6 ("Distinct authority states"): draft, business approval, accounting approval,
contractual execution/signature, external sending, payment scheduling, release and correction
are separate actions, and a chat acknowledgment, a document approval or a posted bill never
silently grants the next authority.  Plan section 10 step 1: "PM/legal reviewer approves the
exact agreement; authorized signer executes it.  Commitment/SOV starts at $60,000 plus
$40,000."  Step 4: "Required title/control, location, insurance and delivery evidence is
attached."  Section 7: "a subcontract administrator checks obligations and insurance."  This
module turns those sentences into records, approvals and storage guards.

Flow::

    set_requirements (draft commitment)            -> versioned insurance / bond requirements
    register_agreement (draft commitment)          -> agreement record bound to the CURRENT
                                                      revision of an ``agreement`` document
    contract.approve_agreement (pm / legal)        -> agreement approved: binds the exact
                                                      document revision, commitment version,
                                                      SOV, amount and requirements
    prepare_signature (signed copy, signer, date)  -> signature prepared
    contract.sign (signer)                         -> agreement signed
    commitment.execute (core, governed here)       -> refused until signed and still current
    record_certificate / withdraw_certificate      -> insurance and bond evidence per supplier
    bill.approve, payment.release, payment.release_retainage (core, governed here)
                                                   -> refused while required coverage is
                                                      missing, stale, short or not in force
    contract.require_agreements (owner, once)      -> every commitment executed afterwards
                                                      needs a signed agreement

Agreements.  ``register_agreement(commitment_id, evidence_hash, actor)`` links a DRAFT
commitment to the current revision of an ``agreement`` document on the commitment's project
and snapshots what the agreement describes: the commitment's version, amount, SOV hash,
supplier and project.  One live (registered, approved or signed) agreement per commitment,
and one live agreement per agreement document.  Registering again -- typically a new revision
of the agreement document -- supersedes the live agreement while the commitment is still a
draft (its prepared signature is withdrawn, its open approvals are invalidated), so the new
revision is approved and signed afresh.  Once the commitment is executed its signed
agreement is final.

``contract.approve_agreement`` (roles pm, legal, or the owner; subject: the agreement).  The
manifest binds the commitment id, version, status, SOV lines and hash, amount, supplier,
retainage rate, the agreement document revision and its hash (which must still be the
document's current revision), and the insurance requirements with their hash and version.
A requirement change, a new revision of the agreement document or any change to the
commitment between request and execution invalidates the approval (the rebuilt manifest
differs, or the agreement is no longer eligible: ``AgreementIneligible`` is a
``StaleApprovalError``).

Requirements.  ``set_requirements(commitment_id, [{"kind", "min_limit"}], actor)`` records the
next version of the commitment's requirements (kinds: ``COVERAGE_KINDS``; each kind once; a
minimum limit in whole cents, zero meaning "any limit", e.g. statutory workers' comp).  They
are set while the commitment is a draft and before its agreement is approved; the approval
bound them, so afterwards they are fixed (an empty list clears them, before approval).

Signature.  ``prepare_signature(agreement_id, evidence_hash, signer, signing_date, actor)``
records the signed copy (the current revision of a ``signed_agreement`` document on the
project), the signer (a login) and the signing date, which may not precede the agreement's
approval or lie in the future.  ``contract.sign`` (role signer, or the owner; subject: the
agreement) requires the agreement approval to have executed and still match: the same
agreement revision (still current), commitment version, SOV, amount and requirements.  The
manifest binds the signed copy, the signer and the signing date, and only the named signer
can grant it -- a signature is a personal act, so nobody approves it on the signer's behalf.
When the people registry enforces identities, the signer must be active, hold the signer (or
owner) role on the project and not be an external party: an external accountant gives a sole
owner independent controls, but never signs the company's subcontracts.

Workspace switch.  ``contract.require_agreements`` (owner only, on both sides; subject:
``workspace``) makes every commitment executed afterwards need a signed agreement.  It is set
once and has no "off": a control that can be quietly relaxed is not one.  Commitments
executed before the switch are not affected.

Governor (``GOVERNOR = True``).  Nothing is bound or checked for a commitment with no
agreement and no requirements in a workspace that does not require agreements, so existing
flows and workspaces behave exactly as before.

* ``commitment.execute`` on a commitment with a live agreement (or any commitment once
  agreements are required): ``approval_policy`` binds the agreement id, status and hashes,
  the current hash of its document, the agreement approval id and material hash, and the
  signature id, hash, signed-copy hashes, signer and signing date (plus the requirements
  version and hash).  ``check_request`` and ``check_execute`` refuse until the agreement is
  signed and still current (document revisions current, commitment version, amount and SOV
  equal to what the agreement approval bound).  A database guard backs it: a commitment with
  a live agreement, or any commitment while agreements are required, leaves draft only with a
  signed agreement whose snapshot (version, amount, supplier, project) it still matches.
* ``bill.approve``, ``payment.release`` and ``payment.release_retainage`` on a commitment with
  requirements: ``approval_policy`` binds, per requirement, the certificates able to cover it
  -- the supplier's recorded certificates of that kind, not withdrawn, on the current revision
  of their document, intact, at or above the minimum limit -- with their ids, hashes, limits
  and dates.  The facts are state-derived (no clock), so recording, revising or withdrawing a
  certificate after the request invalidates the approval: the approver saw other evidence.
  ``check_request`` and ``check_execute`` refuse (``CoverageError``) unless every requirement
  has a bound certificate in force on that day (``now``, injectable); the refusal at
  execution leaves the approval granted, because a certificate that is not yet effective may
  become so.  At execution the certificates relied on are recorded in
  ``contract_coverage_checks`` inside the execution transaction (rolled back with it).  A
  retainage payment pays retainage released on any of the supplier's commitments on the
  project, so it must satisfy the requirements of all of them (the highest minimum per kind).

Certificates.  ``record_certificate(party_id, kind, carrier, policy_number, limit,
effective_date, expiry_date, evidence_hash, actor)`` records a supplier's insurance policy or
surety bond (kind ``performance_bond`` / ``payment_bond``: carrier is the surety, policy
number the bond number, limit the penal sum) bound to the current revision of an
``insurance_certificate`` document.  One document revision carries one certificate per kind
and belongs to one supplier.  A later revision of that document makes the certificate stale
(record it again from the new revision); ``withdraw_certificate`` records a cancellation.

Close checks and state.  ``close_checks`` reports (1) commitments with bills that need a
signed agreement and lack one, (2) certificates of suppliers with open commitments expiring
within 30 days with no later certificate recorded, and required coverage on executed open
commitments not in force today, and (3) the integrity of every contract record.  ``state``
lists agreements, requirements, coverage, certificates and the same findings.

Integrity.  SQLite triggers make every record append-only or move it only through its
lifecycle, each transition together with the audit entry this module writes first and, where
an approval decides it, only against that consumed approval: agreements are born registered
against a draft commitment and the current agreement revision, approved only by a consumed
``contract.approve_agreement`` carrying the current requirements hash, signed only by a signed
signature under a consumed ``contract.sign``, superseded only while the commitment is a draft;
signatures, certificates, requirement sets, the workspace policy and coverage checks are never
replaced or deleted.  ``close_checks`` re-hashes every record and cross-checks approvals and
audit entries, so tampering that drops a trigger is detected.
"""
from __future__ import annotations

import datetime as _dt
import unicodedata
from decimal import Decimal
from typing import Any

from ..core.approvals import StaleApprovalError, build_manifest
from ..core.ids import canonical_json, hash_json, loads, new_id, utcnow, utcnow_iso
from ..core.money import D, MoneyError, fmt, money

SCHEMA_NAME = "contracts"
PLUGIN_NAME = "contract"
OP_APPROVE = "contract.approve_agreement"
OP_SIGN = "contract.sign"
OP_REQUIRE = "contract.require_agreements"
OWN_OPERATIONS = (OP_APPROVE, OP_SIGN, OP_REQUIRE)
EXECUTE_OPERATION = "commitment.execute"
COVERAGE_OPERATIONS = ("bill.approve", "payment.release", "payment.release_retainage")
AGREEMENT_SUBJECT = "contract_agreement"
SIGNATURE_SUBJECT = "contract_signature"
CERTIFICATE_SUBJECT = "contract_certificate"
WORKSPACE_SUBJECT = "workspace"
WORKSPACE_SUBJECT_ID = "workspace"
AGREEMENT_KIND = "agreement"
SIGNED_AGREEMENT_KIND = "signed_agreement"
CERTIFICATE_KIND = "insurance_certificate"
COVERAGE_KINDS = ("general_liability", "workers_comp", "auto_liability", "umbrella", "professional", "performance_bond", "payment_bond")
EXPIRY_WARNING_DAYS = 30
MAX_TEXT_LENGTH = 200
LIVE_AGREEMENT = ("registered", "approved", "signed")

_KINDS_SQL = ", ".join(f"'{k}'" for k in COVERAGE_KINDS)
_DATE_GLOB = "'[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'"
_LIVE_SQL = "('registered','approved','signed')"


def _audited(action: str, entity_type: str, entity: str, *conditions: str) -> str:
    """SQL: an audit entry ``action`` on the entity whose payload carries the given facts."""
    where = " AND ".join(conditions)
    return (f"EXISTS (SELECT 1 FROM audit_log g WHERE g.entity_type = '{entity_type}' AND g.entity_id = {entity} AND g.action = '{action}'"
            + (f" AND {where}" if where else "") + ")")


def _payload(path: str, value: str) -> str:
    return f"json_extract(g.payload_json, '$.{path}') IS {value}"


def _consumed(approval: str, operation: str, subject: str) -> str:
    """SQL: ``approval`` is a consumed approval of ``operation`` on ``subject``."""
    return (f"EXISTS (SELECT 1 FROM approvals a WHERE a.id = {approval} AND a.status = 'consumed' "
            f"AND a.operation = '{operation}' AND a.subject_id = {subject})")


def _current_revision_sql(revision_id: str, document_id: str, revision: str, content_hash: str, kind: str, project_sql: str | None) -> str:
    """SQL: the revision is the current revision of a ``kind`` document carrying ``content_hash``."""
    project = f" AND d.project_id = {project_sql}" if project_sql else ""
    return (f"EXISTS (SELECT 1 FROM document_revisions r JOIN documents d ON d.id = r.document_id "
            f"WHERE r.id = {revision_id} AND r.document_id = {document_id} AND r.revision = {revision} AND r.content_hash = {content_hash} "
            f"AND d.kind = '{kind}'{project} "
            f"AND r.revision = (SELECT MAX(x.revision) FROM document_revisions x WHERE x.document_id = {document_id}))")


# Append-only schema entry: never edit these statements once applied; add a new uniquely named
# entry instead.  Every trigger names only foundation tables and this entry's own tables, so the
# entry is independent of plugin load order.
SCHEMA_STATEMENTS = [
    # ---- tables ------------------------------------------------------------------------------ #
    """CREATE TABLE contract_workspace_policy (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        agreements_required INTEGER NOT NULL CHECK (agreements_required = 1),
        workspace_id TEXT NOT NULL,
        approval_id TEXT NOT NULL UNIQUE REFERENCES approvals(id),
        set_by TEXT NOT NULL CHECK (length(trim(set_by)) > 0),
        set_at TEXT NOT NULL
    )""",
    """CREATE TABLE contract_requirement_sets (
        id TEXT PRIMARY KEY,
        commitment_id TEXT NOT NULL REFERENCES commitments(id),
        version INTEGER NOT NULL CHECK (version >= 1),
        requirements_json TEXT NOT NULL,
        requirements_hash TEXT NOT NULL CHECK (length(requirements_hash) = 64),
        requirement_count INTEGER NOT NULL CHECK (requirement_count >= 0),
        set_by TEXT NOT NULL CHECK (length(trim(set_by)) > 0),
        set_at TEXT NOT NULL,
        UNIQUE (commitment_id, version)
    )""",
    """CREATE TABLE contract_agreements (
        id TEXT PRIMARY KEY,
        commitment_id TEXT NOT NULL REFERENCES commitments(id),
        project_id TEXT NOT NULL REFERENCES projects(id),
        supplier_id TEXT NOT NULL REFERENCES parties(id),
        document_id TEXT NOT NULL REFERENCES documents(id),
        revision_id TEXT NOT NULL REFERENCES document_revisions(id),
        revision INTEGER NOT NULL,
        evidence_hash TEXT NOT NULL CHECK (length(trim(evidence_hash)) > 0),
        commitment_version INTEGER NOT NULL,
        commitment_amount TEXT NOT NULL,
        sov_hash TEXT NOT NULL,
        supersedes TEXT REFERENCES contract_agreements(id),
        content_hash TEXT NOT NULL CHECK (length(content_hash) = 64),
        status TEXT NOT NULL CHECK (status IN ('registered','approved','signed','superseded')),
        approval_id TEXT UNIQUE REFERENCES approvals(id),
        requirements_hash TEXT,
        approved_by TEXT,
        approved_at TEXT,
        approved_on TEXT,
        signature_id TEXT UNIQUE,
        signed_at TEXT,
        superseded_at TEXT,
        superseded_reason TEXT,
        registered_by TEXT NOT NULL CHECK (length(trim(registered_by)) > 0),
        registered_at TEXT NOT NULL
    )""",
    f"""CREATE TABLE contract_signatures (
        id TEXT PRIMARY KEY,
        agreement_id TEXT NOT NULL REFERENCES contract_agreements(id),
        document_id TEXT NOT NULL REFERENCES documents(id),
        revision_id TEXT NOT NULL REFERENCES document_revisions(id),
        revision INTEGER NOT NULL,
        signed_copy_hash TEXT NOT NULL CHECK (length(trim(signed_copy_hash)) > 0),
        signer TEXT NOT NULL CHECK (length(trim(signer)) > 0),
        signing_date TEXT NOT NULL CHECK (signing_date GLOB {_DATE_GLOB}),
        content_hash TEXT NOT NULL CHECK (length(content_hash) = 64),
        status TEXT NOT NULL CHECK (status IN ('prepared','signed','withdrawn')),
        approval_id TEXT UNIQUE REFERENCES approvals(id),
        signed_at TEXT,
        executed_by TEXT,
        withdrawn_at TEXT,
        withdrawn_reason TEXT,
        prepared_by TEXT NOT NULL CHECK (length(trim(prepared_by)) > 0),
        prepared_at TEXT NOT NULL
    )""",
    f"""CREATE TABLE contract_certificates (
        id TEXT PRIMARY KEY,
        party_id TEXT NOT NULL REFERENCES parties(id),
        kind TEXT NOT NULL CHECK (kind IN ({_KINDS_SQL})),
        carrier TEXT NOT NULL CHECK (length(trim(carrier)) > 0),
        policy_number TEXT NOT NULL CHECK (length(trim(policy_number)) > 0),
        limit_amount TEXT NOT NULL,
        effective_date TEXT NOT NULL CHECK (effective_date GLOB {_DATE_GLOB}),
        expiry_date TEXT NOT NULL CHECK (expiry_date GLOB {_DATE_GLOB} AND expiry_date >= effective_date),
        document_id TEXT NOT NULL REFERENCES documents(id),
        revision_id TEXT NOT NULL REFERENCES document_revisions(id),
        revision INTEGER NOT NULL,
        evidence_hash TEXT NOT NULL CHECK (length(trim(evidence_hash)) > 0),
        content_hash TEXT NOT NULL CHECK (length(content_hash) = 64),
        status TEXT NOT NULL CHECK (status IN ('recorded','withdrawn')),
        withdrawn_by TEXT,
        withdrawn_at TEXT,
        withdrawn_reason TEXT,
        recorded_by TEXT NOT NULL CHECK (length(trim(recorded_by)) > 0),
        recorded_at TEXT NOT NULL,
        UNIQUE (revision_id, kind)
    )""",
    """CREATE TABLE contract_coverage_checks (
        id TEXT PRIMARY KEY,
        approval_id TEXT NOT NULL UNIQUE REFERENCES approvals(id),
        operation TEXT NOT NULL CHECK (operation IN ('bill.approve','payment.release','payment.release_retainage')),
        subject_id TEXT NOT NULL,
        checked_on TEXT NOT NULL,
        coverage_json TEXT NOT NULL,
        coverage_hash TEXT NOT NULL CHECK (length(coverage_hash) = 64),
        checked_by TEXT NOT NULL CHECK (length(trim(checked_by)) > 0),
        checked_at TEXT NOT NULL
    )""",
    # ---- indexes ----------------------------------------------------------------------------- #
    f"CREATE UNIQUE INDEX contract_agreements_one_live ON contract_agreements (commitment_id) WHERE status IN {_LIVE_SQL}",
    f"CREATE UNIQUE INDEX contract_agreements_document_live ON contract_agreements (document_id) WHERE status IN {_LIVE_SQL}",
    "CREATE UNIQUE INDEX contract_agreements_supersedes_once ON contract_agreements (supersedes) WHERE supersedes IS NOT NULL",
    "CREATE UNIQUE INDEX contract_signatures_one_live ON contract_signatures (agreement_id) WHERE status IN ('prepared','signed')",
    "CREATE INDEX contract_certificates_by_party ON contract_certificates (party_id, kind)",
    "CREATE INDEX contract_requirement_sets_by_commitment ON contract_requirement_sets (commitment_id, version)",
    # ---- workspace policy -------------------------------------------------------------------- #
    f"""CREATE TRIGGER contract_workspace_policy_insert BEFORE INSERT ON contract_workspace_policy
        BEGIN SELECT CASE
          WHEN EXISTS (SELECT 1 FROM contract_workspace_policy)
            THEN RAISE(ABORT, 'agreements are already required in this workspace; the policy is set once')
          WHEN NOT {_consumed('NEW.approval_id', OP_REQUIRE, f"'{WORKSPACE_SUBJECT_ID}'")}
            THEN RAISE(ABORT, 'agreements become required only through a consumed contract.require_agreements approval')
          WHEN NOT {_audited('contract.agreements_required', WORKSPACE_SUBJECT, f"'{WORKSPACE_SUBJECT_ID}'", _payload('approval_id', 'NEW.approval_id'))}
            THEN RAISE(ABORT, 'the agreement requirement is recorded only by contract.require_agreements, which audits it')
        END; END""",
    "CREATE TRIGGER contract_workspace_policy_no_update BEFORE UPDATE ON contract_workspace_policy BEGIN SELECT RAISE(ABORT, 'the agreement requirement is permanent'); END",
    "CREATE TRIGGER contract_workspace_policy_no_delete BEFORE DELETE ON contract_workspace_policy BEGIN SELECT RAISE(ABORT, 'the agreement requirement is permanent'); END",
    # ---- requirement sets -------------------------------------------------------------------- #
    f"""CREATE TRIGGER contract_requirement_sets_insert BEFORE INSERT ON contract_requirement_sets
        BEGIN SELECT CASE
          WHEN EXISTS (SELECT 1 FROM contract_requirement_sets WHERE id = NEW.id OR (commitment_id = NEW.commitment_id AND version = NEW.version))
            THEN RAISE(ABORT, 'insurance requirement sets are append-only: an id or a version is never reused')
          WHEN NEW.version IS NOT (SELECT COALESCE(MAX(version), 0) + 1 FROM contract_requirement_sets WHERE commitment_id = NEW.commitment_id)
            THEN RAISE(ABORT, 'insurance requirements change only by their next version')
          WHEN (SELECT status FROM commitments WHERE id = NEW.commitment_id) IS NOT 'draft'
            THEN RAISE(ABORT, 'insurance requirements are set while the commitment is a draft')
          WHEN EXISTS (SELECT 1 FROM contract_agreements WHERE commitment_id = NEW.commitment_id AND status IN ('approved','signed'))
            THEN RAISE(ABORT, 'insurance requirements are fixed once the agreement is approved')
          WHEN NOT {_audited('contract.requirements_set', 'commitment', 'NEW.commitment_id', _payload('set_id', 'NEW.id'), _payload('version', 'NEW.version'),
                             _payload('requirements_hash', 'NEW.requirements_hash'))}
            THEN RAISE(ABORT, 'insurance requirements are recorded only by set_requirements, which audits them')
        END; END""",
    "CREATE TRIGGER contract_requirement_sets_no_update BEFORE UPDATE ON contract_requirement_sets BEGIN SELECT RAISE(ABORT, 'insurance requirement sets are append-only'); END",
    "CREATE TRIGGER contract_requirement_sets_no_delete BEFORE DELETE ON contract_requirement_sets BEGIN SELECT RAISE(ABORT, 'insurance requirement sets are append-only'); END",
    # ---- agreements -------------------------------------------------------------------------- #
    f"""CREATE TRIGGER contract_agreements_insert BEFORE INSERT ON contract_agreements
        BEGIN SELECT CASE
          WHEN EXISTS (SELECT 1 FROM contract_agreements WHERE id = NEW.id)
            THEN RAISE(ABORT, 'agreement records are never replaced')
          WHEN NEW.status IS NOT 'registered' OR NEW.approval_id IS NOT NULL OR NEW.approved_by IS NOT NULL OR NEW.approved_at IS NOT NULL
            OR NEW.approved_on IS NOT NULL OR NEW.requirements_hash IS NOT NULL OR NEW.signature_id IS NOT NULL OR NEW.signed_at IS NOT NULL
            OR NEW.superseded_at IS NOT NULL OR NEW.superseded_reason IS NOT NULL
            THEN RAISE(ABORT, 'an agreement is registered unapproved and unsigned')
          WHEN EXISTS (SELECT 1 FROM contract_agreements WHERE commitment_id = NEW.commitment_id AND status IN {_LIVE_SQL})
            THEN RAISE(ABORT, 'the commitment already has a live agreement; register_agreement supersedes it first')
          WHEN EXISTS (SELECT 1 FROM contract_agreements WHERE document_id = NEW.document_id AND status IN {_LIVE_SQL})
            THEN RAISE(ABORT, 'that agreement document already backs another live agreement')
          WHEN NOT EXISTS (SELECT 1 FROM commitments c WHERE c.id = NEW.commitment_id AND c.status = 'draft' AND c.project_id = NEW.project_id
                             AND c.supplier_id = NEW.supplier_id AND c.version = NEW.commitment_version AND c.original_amount = NEW.commitment_amount)
            THEN RAISE(ABORT, 'an agreement is registered against a draft commitment, with its project, supplier, version and amount')
          WHEN NOT {_current_revision_sql('NEW.revision_id', 'NEW.document_id', 'NEW.revision', 'NEW.evidence_hash', AGREEMENT_KIND, 'NEW.project_id')}
            THEN RAISE(ABORT, 'an agreement binds the current revision of an agreement document on the commitment''s project')
          WHEN NEW.supersedes IS NOT NULL AND NOT EXISTS (SELECT 1 FROM contract_agreements WHERE id = NEW.supersedes AND commitment_id = NEW.commitment_id AND status = 'superseded')
            THEN RAISE(ABORT, 'an agreement supersedes only a superseded agreement of the same commitment')
          WHEN NOT {_audited('contract.agreement_registered', AGREEMENT_SUBJECT, 'NEW.id', _payload('content_hash', 'NEW.content_hash'),
                             _payload('commitment_id', 'NEW.commitment_id'))}
            THEN RAISE(ABORT, 'an agreement is registered only through register_agreement, which audits its content hash')
        END; END""",
    """CREATE TRIGGER contract_agreements_binding_immutable BEFORE UPDATE ON contract_agreements
        WHEN NEW.id IS NOT OLD.id OR NEW.commitment_id IS NOT OLD.commitment_id OR NEW.project_id IS NOT OLD.project_id OR NEW.supplier_id IS NOT OLD.supplier_id
          OR NEW.document_id IS NOT OLD.document_id OR NEW.revision_id IS NOT OLD.revision_id OR NEW.revision IS NOT OLD.revision
          OR NEW.evidence_hash IS NOT OLD.evidence_hash OR NEW.commitment_version IS NOT OLD.commitment_version
          OR NEW.commitment_amount IS NOT OLD.commitment_amount OR NEW.sov_hash IS NOT OLD.sov_hash OR NEW.supersedes IS NOT OLD.supersedes
          OR NEW.content_hash IS NOT OLD.content_hash OR NEW.registered_by IS NOT OLD.registered_by OR NEW.registered_at IS NOT OLD.registered_at
        BEGIN SELECT RAISE(ABORT, 'an agreement''s binding to its commitment and document is immutable; register a new agreement instead'); END""",
    f"""CREATE TRIGGER contract_agreements_lifecycle BEFORE UPDATE ON contract_agreements
        WHEN NOT (
          (OLD.status = 'registered' AND NEW.status = 'approved'
            AND NEW.approval_id IS NOT NULL AND NEW.approved_by IS NOT NULL AND NEW.approved_at IS NOT NULL AND NEW.approved_on GLOB {_DATE_GLOB}
            AND NEW.signature_id IS NULL AND NEW.signed_at IS NULL AND NEW.superseded_at IS NULL AND NEW.superseded_reason IS NULL
            AND {_consumed('NEW.approval_id', OP_APPROVE, 'NEW.id')}
            AND NEW.requirements_hash IS (SELECT s.requirements_hash FROM contract_requirement_sets s WHERE s.commitment_id = NEW.commitment_id ORDER BY s.version DESC LIMIT 1)
            AND {_audited('contract.agreement_approved', AGREEMENT_SUBJECT, 'NEW.id', _payload('approval_id', 'NEW.approval_id'),
                          _payload('requirements_hash', 'NEW.requirements_hash'))})
          OR (OLD.status = 'approved' AND NEW.status = 'signed'
            AND NEW.approval_id IS OLD.approval_id AND NEW.approved_by IS OLD.approved_by AND NEW.approved_at IS OLD.approved_at
            AND NEW.approved_on IS OLD.approved_on AND NEW.requirements_hash IS OLD.requirements_hash
            AND NEW.signature_id IS NOT NULL AND NEW.signed_at IS NOT NULL AND NEW.superseded_at IS NULL AND NEW.superseded_reason IS NULL
            AND EXISTS (SELECT 1 FROM contract_signatures s WHERE s.id = NEW.signature_id AND s.agreement_id = NEW.id AND s.status = 'signed'
                          AND {_consumed('s.approval_id', OP_SIGN, 'NEW.id')}))
          OR (OLD.status IN {_LIVE_SQL} AND NEW.status = 'superseded'
            AND NEW.approval_id IS OLD.approval_id AND NEW.approved_by IS OLD.approved_by AND NEW.approved_at IS OLD.approved_at
            AND NEW.approved_on IS OLD.approved_on AND NEW.requirements_hash IS OLD.requirements_hash
            AND NEW.signature_id IS OLD.signature_id AND NEW.signed_at IS OLD.signed_at
            AND NEW.superseded_at IS NOT NULL AND length(trim(COALESCE(NEW.superseded_reason, ''))) > 0
            AND (SELECT status FROM commitments WHERE id = NEW.commitment_id) = 'draft'
            AND {_audited('contract.agreement_superseded', AGREEMENT_SUBJECT, 'NEW.id', _payload('superseded_at', 'NEW.superseded_at'))}))
        BEGIN SELECT RAISE(ABORT, 'an agreement moves registered -> approved (its consumed contract.approve_agreement) -> signed (its consumed contract.sign), or to superseded while its commitment is a draft; nothing else about it changes'); END""",
    "CREATE TRIGGER contract_agreements_no_delete BEFORE DELETE ON contract_agreements BEGIN SELECT RAISE(ABORT, 'agreement records are never deleted'); END",
    # ---- signatures -------------------------------------------------------------------------- #
    f"""CREATE TRIGGER contract_signatures_insert BEFORE INSERT ON contract_signatures
        BEGIN SELECT CASE
          WHEN EXISTS (SELECT 1 FROM contract_signatures WHERE id = NEW.id)
            THEN RAISE(ABORT, 'signature records are never replaced')
          WHEN NEW.status IS NOT 'prepared' OR NEW.approval_id IS NOT NULL OR NEW.signed_at IS NOT NULL OR NEW.executed_by IS NOT NULL
            OR NEW.withdrawn_at IS NOT NULL OR NEW.withdrawn_reason IS NOT NULL
            THEN RAISE(ABORT, 'a signature is prepared before it is signed')
          WHEN NOT EXISTS (SELECT 1 FROM contract_agreements a WHERE a.id = NEW.agreement_id AND a.status = 'approved' AND NEW.signing_date >= a.approved_on)
            THEN RAISE(ABORT, 'a signature is prepared for an approved agreement, dated on or after its approval')
          WHEN EXISTS (SELECT 1 FROM contract_signatures WHERE agreement_id = NEW.agreement_id AND status IN ('prepared','signed'))
            THEN RAISE(ABORT, 'the agreement already has a live signature; prepare_signature withdraws it first')
          WHEN EXISTS (SELECT 1 FROM contract_signatures s JOIN contract_agreements a ON a.id = s.agreement_id
                        WHERE s.document_id = NEW.document_id AND s.status IN ('prepared','signed') AND a.status IN {_LIVE_SQL})
            THEN RAISE(ABORT, 'that signed-agreement document already backs another live signature')
          WHEN NOT {_current_revision_sql('NEW.revision_id', 'NEW.document_id', 'NEW.revision', 'NEW.signed_copy_hash', SIGNED_AGREEMENT_KIND,
                                          '(SELECT project_id FROM contract_agreements WHERE id = NEW.agreement_id)')}
            THEN RAISE(ABORT, 'a signature binds the current revision of a signed_agreement document on the agreement''s project')
          WHEN NOT {_audited('contract.signature_prepared', SIGNATURE_SUBJECT, 'NEW.id', _payload('content_hash', 'NEW.content_hash'))}
            THEN RAISE(ABORT, 'a signature is prepared only through prepare_signature, which audits its content hash')
        END; END""",
    """CREATE TRIGGER contract_signatures_binding_immutable BEFORE UPDATE ON contract_signatures
        WHEN NEW.id IS NOT OLD.id OR NEW.agreement_id IS NOT OLD.agreement_id OR NEW.document_id IS NOT OLD.document_id
          OR NEW.revision_id IS NOT OLD.revision_id OR NEW.revision IS NOT OLD.revision OR NEW.signed_copy_hash IS NOT OLD.signed_copy_hash
          OR NEW.signer IS NOT OLD.signer OR NEW.signing_date IS NOT OLD.signing_date OR NEW.content_hash IS NOT OLD.content_hash
          OR NEW.prepared_by IS NOT OLD.prepared_by OR NEW.prepared_at IS NOT OLD.prepared_at
        BEGIN SELECT RAISE(ABORT, 'a signature''s signed copy, signer and date are immutable; prepare a new signature instead'); END""",
    f"""CREATE TRIGGER contract_signatures_lifecycle BEFORE UPDATE ON contract_signatures
        WHEN NOT (
          (OLD.status = 'prepared' AND NEW.status = 'signed' AND NEW.approval_id IS NOT NULL AND NEW.signed_at IS NOT NULL
            AND length(trim(COALESCE(NEW.executed_by, ''))) > 0 AND NEW.withdrawn_at IS NULL AND NEW.withdrawn_reason IS NULL
            AND {_consumed('NEW.approval_id', OP_SIGN, 'NEW.agreement_id')}
            AND (SELECT status FROM contract_agreements WHERE id = NEW.agreement_id) = 'approved'
            AND {_audited('contract.agreement_signed', SIGNATURE_SUBJECT, 'NEW.id', _payload('approval_id', 'NEW.approval_id'))})
          OR (OLD.status = 'prepared' AND NEW.status = 'withdrawn' AND NEW.approval_id IS NULL AND NEW.signed_at IS NULL AND NEW.executed_by IS NULL
            AND NEW.withdrawn_at IS NOT NULL AND length(trim(COALESCE(NEW.withdrawn_reason, ''))) > 0
            AND {_audited('contract.signature_withdrawn', SIGNATURE_SUBJECT, 'NEW.id', _payload('withdrawn_at', 'NEW.withdrawn_at'))}))
        BEGIN SELECT RAISE(ABORT, 'a signature moves prepared -> signed (its consumed contract.sign) or prepared -> withdrawn; a signed signature is final'); END""",
    "CREATE TRIGGER contract_signatures_no_delete BEFORE DELETE ON contract_signatures BEGIN SELECT RAISE(ABORT, 'signature records are never deleted'); END",
    # ---- certificates ------------------------------------------------------------------------ #
    f"""CREATE TRIGGER contract_certificates_insert BEFORE INSERT ON contract_certificates
        BEGIN SELECT CASE
          WHEN EXISTS (SELECT 1 FROM contract_certificates WHERE id = NEW.id OR (revision_id = NEW.revision_id AND kind = NEW.kind))
            THEN RAISE(ABORT, 'certificates are never replaced: one certificate per coverage kind per document revision')
          WHEN NEW.status IS NOT 'recorded' OR NEW.withdrawn_by IS NOT NULL OR NEW.withdrawn_at IS NOT NULL OR NEW.withdrawn_reason IS NOT NULL
            THEN RAISE(ABORT, 'a certificate is recorded before it can be withdrawn')
          WHEN (SELECT kind FROM parties WHERE id = NEW.party_id) IS NOT 'supplier'
            THEN RAISE(ABORT, 'insurance and bond certificates are recorded for supplier parties')
          WHEN NOT {_current_revision_sql('NEW.revision_id', 'NEW.document_id', 'NEW.revision', 'NEW.evidence_hash', CERTIFICATE_KIND, None)}
            THEN RAISE(ABORT, 'a certificate binds the current revision of an insurance_certificate document')
          WHEN EXISTS (SELECT 1 FROM contract_certificates WHERE document_id = NEW.document_id AND party_id IS NOT NEW.party_id)
            THEN RAISE(ABORT, 'an insurance certificate document belongs to one supplier')
          WHEN NOT {_audited('contract.certificate_recorded', CERTIFICATE_SUBJECT, 'NEW.id', _payload('content_hash', 'NEW.content_hash'))}
            THEN RAISE(ABORT, 'a certificate is recorded only through record_certificate, which audits its content hash')
        END; END""",
    """CREATE TRIGGER contract_certificates_binding_immutable BEFORE UPDATE ON contract_certificates
        WHEN NEW.id IS NOT OLD.id OR NEW.party_id IS NOT OLD.party_id OR NEW.kind IS NOT OLD.kind OR NEW.carrier IS NOT OLD.carrier
          OR NEW.policy_number IS NOT OLD.policy_number OR NEW.limit_amount IS NOT OLD.limit_amount OR NEW.effective_date IS NOT OLD.effective_date
          OR NEW.expiry_date IS NOT OLD.expiry_date OR NEW.document_id IS NOT OLD.document_id OR NEW.revision_id IS NOT OLD.revision_id
          OR NEW.revision IS NOT OLD.revision OR NEW.evidence_hash IS NOT OLD.evidence_hash OR NEW.content_hash IS NOT OLD.content_hash
          OR NEW.recorded_by IS NOT OLD.recorded_by OR NEW.recorded_at IS NOT OLD.recorded_at
        BEGIN SELECT RAISE(ABORT, 'a certificate''s policy, limit, dates and evidence are immutable; record the new certificate instead'); END""",
    f"""CREATE TRIGGER contract_certificates_lifecycle BEFORE UPDATE ON contract_certificates
        WHEN NOT (OLD.status = 'recorded' AND NEW.status = 'withdrawn' AND length(trim(COALESCE(NEW.withdrawn_by, ''))) > 0
                  AND NEW.withdrawn_at IS NOT NULL AND length(trim(COALESCE(NEW.withdrawn_reason, ''))) > 0
                  AND {_audited('contract.certificate_withdrawn', CERTIFICATE_SUBJECT, 'NEW.id', _payload('withdrawn_at', 'NEW.withdrawn_at'),
                                _payload('reason', 'NEW.withdrawn_reason'))})
        BEGIN SELECT RAISE(ABORT, 'a certificate is only ever withdrawn, once, with who and why'); END""",
    "CREATE TRIGGER contract_certificates_no_delete BEFORE DELETE ON contract_certificates BEGIN SELECT RAISE(ABORT, 'certificates are never deleted; withdraw one instead'); END",
    # ---- coverage checks --------------------------------------------------------------------- #
    f"""CREATE TRIGGER contract_coverage_checks_insert BEFORE INSERT ON contract_coverage_checks
        BEGIN SELECT CASE
          WHEN EXISTS (SELECT 1 FROM contract_coverage_checks WHERE id = NEW.id OR approval_id = NEW.approval_id)
            THEN RAISE(ABORT, 'coverage checks are append-only: one per executed approval')
          WHEN NOT EXISTS (SELECT 1 FROM approvals a WHERE a.id = NEW.approval_id AND a.status = 'granted' AND a.operation = NEW.operation AND a.subject_id = NEW.subject_id)
            THEN RAISE(ABORT, 'a coverage check is recorded while its granted approval executes')
          WHEN NOT {_audited('contract.coverage_verified', 'approval', 'NEW.approval_id', _payload('check_id', 'NEW.id'), _payload('coverage_hash', 'NEW.coverage_hash'))}
            THEN RAISE(ABORT, 'a coverage check is recorded only by the contract governor, which audits it')
        END; END""",
    "CREATE TRIGGER contract_coverage_checks_no_update BEFORE UPDATE ON contract_coverage_checks BEGIN SELECT RAISE(ABORT, 'coverage checks are append-only'); END",
    "CREATE TRIGGER contract_coverage_checks_no_delete BEFORE DELETE ON contract_coverage_checks BEGIN SELECT RAISE(ABORT, 'coverage checks are append-only'); END",
    # ---- commitments ------------------------------------------------------------------------- #
    # A commitment with a live agreement, or any commitment while agreements are required, leaves
    # draft only with a signed agreement whose snapshot it still matches -- whatever path writes it.
    f"""CREATE TRIGGER contract_commitment_needs_signed_agreement BEFORE UPDATE OF status ON commitments
        WHEN OLD.status = 'draft' AND NEW.status IS NOT 'draft'
          AND (EXISTS (SELECT 1 FROM contract_agreements a WHERE a.commitment_id = OLD.id AND a.status IN {_LIVE_SQL})
               OR EXISTS (SELECT 1 FROM contract_workspace_policy))
          AND NOT EXISTS (SELECT 1 FROM contract_agreements a JOIN contract_signatures s ON s.id = a.signature_id
                           WHERE a.commitment_id = OLD.id AND a.status = 'signed' AND s.agreement_id = a.id AND s.status = 'signed'
                             AND a.commitment_version = OLD.version AND a.commitment_amount = OLD.original_amount
                             AND a.supplier_id = OLD.supplier_id AND a.project_id = OLD.project_id)
        BEGIN SELECT RAISE(ABORT, 'this commitment leaves draft only with its signed agreement (contract.approve_agreement, then contract.sign)'); END""",
    """CREATE TRIGGER contract_commitments_not_replaced BEFORE INSERT ON commitments
        WHEN EXISTS (SELECT 1 FROM contract_agreements WHERE commitment_id = NEW.id)
          OR EXISTS (SELECT 1 FROM contract_requirement_sets WHERE commitment_id = NEW.id)
          OR (NEW.status IS NOT 'draft' AND EXISTS (SELECT 1 FROM contract_workspace_policy))
        BEGIN SELECT RAISE(ABORT, 'a commitment under a contract agreement or insurance requirements is never replaced, and while agreements are required a commitment is born a draft'); END""",
]


class ContractError(RuntimeError):
    """Invalid contract input, or an action the agreement's or certificate's state does not allow."""


class AgreementIneligible(ContractError, StaleApprovalError):
    """The agreement cannot be (or can no longer be) approved, signed or relied on as bound.
    At request time this refuses; at execution it is a ``StaleApprovalError``, so the service
    invalidates the approval durably (the agreement document, the commitment, the requirements
    or the signature moved on)."""


class CoverageError(ContractError):
    """Required insurance or bond coverage is missing, stale, below its minimum or not in force
    on the day.  At execution the approval is left granted: a certificate that is not yet
    effective may become so, and recording a new certificate invalidates the approval anyway."""


# --------------------------------------------------------------------------- #
# Validation helpers                                                           #
# --------------------------------------------------------------------------- #

def _text(value: Any, label: str, *, max_length: int = MAX_TEXT_LENGTH) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{label} is required")
    text = value.strip()
    if len(text) > max_length:
        raise ContractError(f"{label} is longer than {max_length} characters")
    if any(ord(ch) < 32 for ch in text):
        raise ContractError(f"{label} may not contain control characters")
    return text


def _date(value: Any, label: str) -> _dt.date:
    if not isinstance(value, str) or len(value) != 10 or value[4] != "-" or value[7] != "-":
        raise ContractError(f"{label} must be YYYY-MM-DD, got {value!r}")
    try:
        return _dt.date.fromisoformat(value)
    except ValueError as exc:
        raise ContractError(f"{label} is not a valid calendar date: {value!r}") from exc


def _amount(value: Any, label: str, *, allow_zero: bool = False) -> Decimal:
    """Whole cents; floats, non-finite and sub-cent values are refused, not rounded."""
    try:
        raw = D(value)
        amt = money(raw)
    except (MoneyError, ArithmeticError) as exc:
        raise ContractError(f"{label} is not exact money: {exc}") from exc
    if amt != raw:
        raise ContractError(f"{label} must be in whole cents, got {value!r}")
    if amt < 0 or (amt == 0 and not allow_zero):
        raise ContractError(f"{label} must be {'zero or more' if allow_zero else 'positive'}, got {fmt(amt)}")
    return amt


def _login_key(value: Any) -> str | None:
    """A login as an identity key (NFKC, trimmed, case-folded), as the people registry keys it."""
    if not isinstance(value, str):
        return None
    return unicodedata.normalize("NFKC", value).strip().casefold() or None


def _hash_of(row: dict[str, Any], keys: tuple[str, ...]) -> str:
    return hash_json({k: row.get(k) for k in keys})


_AGREEMENT_KEYS = ("id", "commitment_id", "project_id", "supplier_id", "document_id", "revision_id", "revision", "evidence_hash",
                   "commitment_version", "commitment_amount", "sov_hash", "supersedes", "registered_by", "registered_at")
_SIGNATURE_KEYS = ("id", "agreement_id", "document_id", "revision_id", "revision", "signed_copy_hash", "signer", "signing_date",
                   "prepared_by", "prepared_at")
_CERTIFICATE_KEYS = ("id", "party_id", "kind", "carrier", "policy_number", "limit_amount", "effective_date", "expiry_date",
                     "document_id", "revision_id", "revision", "evidence_hash", "recorded_by", "recorded_at")


# --------------------------------------------------------------------------- #
# Plugin                                                                       #
# --------------------------------------------------------------------------- #

class Plugin:
    """The ``contract`` plugin: owns ``contract.*`` approvals and governs commitment execution,
    bill approval and payment release (see the module docstring)."""

    GOVERNOR = True

    def __init__(self, cipher):
        self.c = cipher
        self.db = cipher.db
        self.audit = cipher.audit
        self.approvals = cipher.approvals
        # injectable clock: certificate validity, signing dates and expiry warnings use its date
        self.now = utcnow

    # ---- clock and identity ------------------------------------------------------------------ #

    def _today(self) -> _dt.date:
        return self.now().date()

    def _people(self) -> Any | None:
        """The people registry when it is registered and enforcing identities, else None."""
        people = self.c._plugins.get("people")
        if people is None:
            return None
        enforcing = getattr(people, "enforcing", None)
        return people if callable(enforcing) and enforcing() else None

    def _actor(self, actor: Any) -> str:
        who = _text(actor, "actor")
        people = self._people()
        if people is not None and not people.is_active(who):
            raise ContractError(f"{who!r} is not an active person in the people registry")
        return who

    def _signer_problem(self, signer: str, project_id: str | None) -> str | None:
        """Why ``signer`` cannot sign the company's agreements on ``project_id`` (people
        registry enforcing), or None.  Without an enforcing registry any named login may sign;
        the approval still has to be granted by that login."""
        people = self._people()
        if people is None:
            return None
        if not people.is_active(signer):
            return f"signer {signer!r} is not an active person in the people registry"
        if people.is_external(signer):
            return f"signer {signer!r} is an external party; only the company's authorized signer signs its agreements"
        if not (people.holds(signer, "signer", project_id=project_id) or people.holds(signer, "owner", project_id=project_id)):
            return f"signer {signer!r} does not hold the signer role on project {project_id}"
        return None

    # ---- lookups ----------------------------------------------------------------------------- #

    def _commitment(self, commitment_id: Any) -> dict[str, Any]:
        if not isinstance(commitment_id, str) or self.db.one("SELECT id FROM commitments WHERE id=?", (commitment_id,)) is None:
            raise ContractError(f"unknown commitment {commitment_id}")
        return self.c.commitments.get(commitment_id)

    def _project(self, project_id: str) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM projects WHERE id=?", (project_id,))
        if row is None:
            raise ContractError(f"unknown project {project_id}")
        return row

    def _current_revision(self, document_id: str | None) -> dict[str, Any] | None:
        if not document_id:
            return None
        return self.db.one("SELECT id, document_id, revision, content_hash FROM document_revisions WHERE document_id=? ORDER BY revision DESC LIMIT 1",
                           (document_id,))

    def _resolve_evidence(self, evidence_hash: Any, kind: str, *, project_id: str | None, label: str) -> dict[str, Any]:
        """The current revision of a ``kind`` document (on ``project_id`` when given) carrying
        ``evidence_hash``; superseded, foreign or ambiguous evidence is refused."""
        if not isinstance(evidence_hash, str) or not evidence_hash.strip():
            raise ContractError(f"{label} requires the content hash of its '{kind}' document")
        rows = self.db.query(
            """SELECT r.id, r.document_id, r.revision, r.content_hash, d.project_id, d.kind FROM document_revisions r
               JOIN documents d ON d.id = r.document_id WHERE r.content_hash=? ORDER BY r.created_at, r.id""",
            (evidence_hash.strip(),),
        )
        if not rows:
            raise ContractError(f"the evidence hash for {label} matches no stored document revision; register the document first")
        if project_id is not None:
            rows = [r for r in rows if r["project_id"] == project_id]
            if not rows:
                raise ContractError(f"the document for {label} belongs to another project; register it on project {project_id}")
        rows = [r for r in rows if r["kind"] == kind]
        if not rows:
            raise ContractError(f"{label} is backed only by a '{kind}' document")
        current = [r for r in rows if (self._current_revision(r["document_id"]) or {}).get("id") == r["id"]]
        if not current:
            raise ContractError(f"the evidence hash for {label} matches a superseded revision of document {rows[-1]['document_id']}; bind the current revision")
        if len(current) > 1:
            raise ContractError(f"the evidence hash for {label} matches the current revision of several documents; register distinct documents")
        return current[0]

    def _agreement_row(self, agreement_id: Any) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM contract_agreements WHERE id=?", (agreement_id,)) if isinstance(agreement_id, str) else None
        if row is None:
            raise ContractError(f"unknown agreement {agreement_id}")
        return row

    def _live_agreement(self, commitment_id: str) -> dict[str, Any] | None:
        return self.db.one(f"SELECT * FROM contract_agreements WHERE commitment_id=? AND status IN {_LIVE_SQL}", (commitment_id,))

    def _signature_row(self, signature_id: Any) -> dict[str, Any] | None:
        return self.db.one("SELECT * FROM contract_signatures WHERE id=?", (signature_id,)) if isinstance(signature_id, str) else None

    def _live_signature(self, agreement_id: str) -> dict[str, Any] | None:
        return self.db.one("SELECT * FROM contract_signatures WHERE agreement_id=? AND status IN ('prepared','signed')", (agreement_id,))

    def _approval(self, approval_id: Any) -> dict[str, Any] | None:
        if not isinstance(approval_id, str):
            return None
        row = self.db.one("SELECT * FROM approvals WHERE id=?", (approval_id,))
        if row is not None:
            row["manifest"] = loads(row.pop("manifest_json")) or {}
        return row

    def _requirement_set(self, commitment_id: str) -> dict[str, Any] | None:
        row = self.db.one("SELECT * FROM contract_requirement_sets WHERE commitment_id=? ORDER BY version DESC LIMIT 1", (commitment_id,))
        if row is not None:
            row["requirements"] = loads(row["requirements_json"]) or []
        return row

    def agreements_required(self) -> bool:
        """Whether ``contract.require_agreements`` has been executed in this workspace."""
        return self.db.one("SELECT 1 AS x FROM contract_workspace_policy WHERE id=1") is not None

    def policy(self) -> dict[str, Any] | None:
        return self.db.one("SELECT * FROM contract_workspace_policy WHERE id=1")

    # ---- requirements ------------------------------------------------------------------------ #

    @staticmethod
    def _normalize_requirements(requirements: Any) -> list[dict[str, str]]:
        if requirements is None:
            requirements = []
        if not isinstance(requirements, (list, tuple)):
            raise ContractError('requirements must be a list of {"kind", "min_limit"}')
        found: dict[str, str] = {}
        for n, req in enumerate(requirements, start=1):
            if not isinstance(req, dict):
                raise ContractError(f"requirement {n} must be a mapping with kind and min_limit")
            unknown = sorted(set(req) - {"kind", "min_limit"})
            if unknown:
                raise ContractError(f"requirement {n} has unknown field(s) {', '.join(unknown)}")
            kind = req.get("kind")
            if kind not in COVERAGE_KINDS:
                raise ContractError(f"requirement {n}: kind must be one of {', '.join(COVERAGE_KINDS)}, got {kind!r}")
            if kind in found:
                raise ContractError(f"requirement {n}: {kind} is required twice; give each kind once with its minimum limit")
            found[kind] = fmt(_amount(req.get("min_limit"), f"requirement {n} ({kind}) min_limit", allow_zero=True))
        return [{"kind": k, "min_limit": found[k]} for k in COVERAGE_KINDS if k in found]

    def set_requirements(self, commitment_id: str, requirements: Any, actor: str) -> dict[str, Any]:
        """Record the next version of a draft commitment's insurance and bond requirements
        (see the module docstring).  Open approvals that bound the previous version are
        invalidated: the agreement approver must see the requirements actually in force."""
        who = self._actor(actor)
        clean = self._normalize_requirements(requirements)
        req_hash = hash_json(clean)
        with self.db.transaction() as conn:
            c = self._commitment(commitment_id)
            if c["status"] != "draft":
                raise ContractError(f"commitment {commitment_id} is {c['status']}; insurance requirements are set while it is a draft")
            live = self._live_agreement(commitment_id)
            if live is not None and live["status"] in ("approved", "signed"):
                raise ContractError(f"agreement {live['id']} is {live['status']} with the current requirements; they are fixed now "
                                    "(register a new agreement revision to start over)")
            prev = self._requirement_set(commitment_id)
            if prev is not None and prev["requirements_hash"] == req_hash:
                raise ContractError(f"commitment {commitment_id} already carries exactly these requirements (version {prev['version']})")
            if prev is None and not clean:
                raise ContractError(f"commitment {commitment_id} has no requirements to clear")
            version = (prev["version"] if prev else 0) + 1
            set_id = new_id("creq")
            now = utcnow_iso()
            self.audit.record(who, "contract.requirements_set", "commitment", commitment_id, {
                "set_id": set_id, "version": version, "requirements": clean, "requirements_hash": req_hash,
                "previous_hash": prev["requirements_hash"] if prev else None,
            })
            conn.execute(
                """INSERT INTO contract_requirement_sets (id, commitment_id, version, requirements_json, requirements_hash, requirement_count, set_by, set_at)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (set_id, commitment_id, version, canonical_json(clean), req_hash, len(clean), who, now),
            )
            if live is not None:
                self.approvals.invalidate_for_subject(AGREEMENT_SUBJECT, live["id"], reason="the commitment's insurance requirements changed", actor=who)
        return self.requirements(commitment_id)

    def requirements(self, commitment_id: str) -> dict[str, Any]:
        """The commitment's current requirements (``requirements`` empty when none)."""
        self._commitment(commitment_id)
        rs = self._requirement_set(commitment_id)
        if rs is None:
            return {"commitment_id": commitment_id, "version": 0, "requirements": [], "requirements_hash": None, "set_id": None}
        return {"commitment_id": commitment_id, "version": rs["version"], "requirements": rs["requirements"],
                "requirements_hash": rs["requirements_hash"], "set_id": rs["id"], "set_by": rs["set_by"], "set_at": rs["set_at"]}

    # ---- agreements -------------------------------------------------------------------------- #

    def _supersede(self, agreement: dict[str, Any], who: str, reason: str) -> None:
        """Supersede a live agreement of a draft commitment (inside the caller's transaction)."""
        sig = self._live_signature(agreement["id"])
        if sig is not None and sig["status"] == "prepared":
            self._withdraw_signature(sig, who, f"agreement superseded: {reason}")
        now = utcnow_iso()
        self.audit.record(who, "contract.agreement_superseded", AGREEMENT_SUBJECT, agreement["id"], {
            "superseded_at": now, "reason": reason, "status_before": agreement["status"], "commitment_id": agreement["commitment_id"],
        })
        self.db.execute("UPDATE contract_agreements SET status='superseded', superseded_at=?, superseded_reason=? WHERE id=?",
                        (now, reason, agreement["id"]))
        self.approvals.invalidate_for_subject(AGREEMENT_SUBJECT, agreement["id"], reason=f"agreement superseded: {reason}", actor=who)

    def _invalidate_execution(self, commitment_id: str, who: str, reason: str) -> None:
        """Open ``commitment.execute`` approvals bound other contract facts; retire them now
        rather than leave them to fail at execution."""
        for row in self.db.query("SELECT id FROM approvals WHERE operation=? AND subject_id=? AND status IN ('pending','granted')",
                                 (EXECUTE_OPERATION, commitment_id)):
            self.approvals.invalidate(row["id"], reason=reason, actor=who)

    def register_agreement(self, commitment_id: str, evidence_hash: str, actor: str) -> dict[str, Any]:
        """Link a draft commitment to the current revision of an ``agreement`` document on its
        project.  A live agreement on the commitment is superseded (the commitment must still
        be a draft), so a revised agreement is approved and signed afresh."""
        who = self._actor(actor)
        with self.db.transaction() as conn:
            c = self._commitment(commitment_id)
            if c["status"] != "draft":
                raise ContractError(f"commitment {commitment_id} is {c['status']}; an agreement is registered against a draft commitment "
                                    "(an executed commitment changes through change.execute)")
            rev = self._resolve_evidence(evidence_hash, AGREEMENT_KIND, project_id=c["project_id"], label="an agreement")
            live = self._live_agreement(commitment_id)
            if live is not None and live["revision_id"] == rev["id"]:
                raise ContractError(f"agreement {live['id']} already binds revision {rev['revision']} of document {rev['document_id']}")
            taken = self.db.one(f"SELECT id, commitment_id FROM contract_agreements WHERE document_id=? AND status IN {_LIVE_SQL} AND commitment_id != ?",
                                (rev["document_id"], commitment_id))
            if taken is not None:
                raise ContractError(f"agreement document {rev['document_id']} already backs agreement {taken['id']} of commitment {taken['commitment_id']}")
            supersedes = None
            if live is not None:
                supersedes = live["id"]
                self._supersede(live, who, f"replaced by revision {rev['revision']} of agreement document {rev['document_id']}")
            agreement_id = new_id("cagr")
            row = {
                "id": agreement_id, "commitment_id": commitment_id, "project_id": c["project_id"], "supplier_id": c["supplier_id"],
                "document_id": rev["document_id"], "revision_id": rev["id"], "revision": rev["revision"], "evidence_hash": rev["content_hash"],
                "commitment_version": c["version"], "commitment_amount": c["original_amount"], "sov_hash": self.c.commitments.sov_hash(commitment_id),
                "supersedes": supersedes, "registered_by": who, "registered_at": utcnow_iso(),
            }
            row["content_hash"] = _hash_of(row, _AGREEMENT_KEYS)
            # audited first: the storage guard admits an agreement only with its audit entry
            self.audit.record(who, "contract.agreement_registered", AGREEMENT_SUBJECT, agreement_id, {
                "content_hash": row["content_hash"], "commitment_id": commitment_id, "document_id": rev["document_id"], "revision": rev["revision"],
                "evidence_hash": rev["content_hash"], "commitment_version": c["version"], "commitment_amount": c["original_amount"],
                "sov_hash": row["sov_hash"], "supersedes": supersedes,
            })
            conn.execute(
                """INSERT INTO contract_agreements (id, commitment_id, project_id, supplier_id, document_id, revision_id, revision, evidence_hash,
                   commitment_version, commitment_amount, sov_hash, supersedes, content_hash, status, registered_by, registered_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,'registered',?,?)""",
                (agreement_id, commitment_id, row["project_id"], row["supplier_id"], row["document_id"], row["revision_id"], row["revision"],
                 row["evidence_hash"], row["commitment_version"], row["commitment_amount"], row["sov_hash"], supersedes, row["content_hash"],
                 who, row["registered_at"]),
            )
            # an execution approval requested before this agreement bound other contract facts
            self._invalidate_execution(commitment_id, who, f"agreement {agreement_id} was registered for the commitment")
        return self.agreement(agreement_id)

    def agreement(self, agreement_id: str) -> dict[str, Any]:
        """The agreement record with its document currency, signature and open problems."""
        a = self._agreement_row(agreement_id)
        cur = self._current_revision(a["document_id"])
        a["document_current"] = cur is not None and cur["id"] == a["revision_id"]
        a["document_current_revision"] = cur["revision"] if cur else None
        sig = self._signature_row(a["signature_id"]) if a["signature_id"] else self._live_signature(a["id"])
        a["signature"] = self._signature_view(sig) if sig else None
        a["problems"] = self._agreement_problems(a) if a["status"] in LIVE_AGREEMENT else []
        return a

    def agreement_for(self, commitment_id: str) -> dict[str, Any] | None:
        """The commitment's live agreement (registered, approved or signed), or None."""
        live = self._live_agreement(commitment_id)
        return self.agreement(live["id"]) if live else None

    def agreements(self, project_id: str | None = None) -> list[dict[str, Any]]:
        if project_id:
            rows = self.db.query("SELECT id FROM contract_agreements WHERE project_id=? ORDER BY registered_at, id", (project_id,))
        else:
            rows = self.db.query("SELECT id FROM contract_agreements ORDER BY registered_at, id")
        return [self.agreement(r["id"]) for r in rows]

    # ---- agreement checks -------------------------------------------------------------------- #

    def _snapshot_problems(self, a: dict[str, Any]) -> list[str]:
        """The agreement record is intact and still describes its draft commitment and the
        current revision of its document."""
        problems: list[str] = []
        if _hash_of(a, _AGREEMENT_KEYS) != a["content_hash"]:
            problems.append(f"agreement {a['id']} no longer hashes to its recorded content hash")
        c = self.db.one("SELECT * FROM commitments WHERE id=?", (a["commitment_id"],))
        if c is None:
            return problems + [f"commitment {a['commitment_id']} is missing"]
        if c["status"] != "draft":
            problems.append(f"commitment {c['id']} is {c['status']}, not a draft")
        if (c["version"], c["original_amount"], c["supplier_id"], c["project_id"]) != (a["commitment_version"], a["commitment_amount"], a["supplier_id"], a["project_id"]):
            problems.append(f"commitment {c['id']} changed after the agreement was registered (version, amount, supplier or project)")
        elif self.c.commitments.sov_hash(c["id"]) != a["sov_hash"]:
            problems.append(f"the schedule of values of commitment {c['id']} changed after the agreement was registered")
        cur = self._current_revision(a["document_id"])
        if cur is None or cur["id"] != a["revision_id"]:
            problems.append(f"agreement document {a['document_id']} was revised after revision {a['revision']} was registered "
                            f"(now revision {cur['revision'] if cur else '?'}); register the current revision and approve it again")
        return problems

    def _approval_problems(self, a: dict[str, Any]) -> list[str]:
        """The executed agreement approval still matches the agreement, its commitment and the
        current requirements."""
        ap = self._approval(a["approval_id"])
        if ap is None or ap["status"] != "consumed" or ap["operation"] != OP_APPROVE or ap["subject_id"] != a["id"]:
            return [f"agreement {a['id']} does not rest on a consumed {OP_APPROVE} approval"]
        bound = ap["manifest"].get("bindings") or {}
        problems = []
        rs = self._requirement_set(a["commitment_id"])
        current_req_hash = rs["requirements_hash"] if rs else None
        if bound.get("requirements_hash") != current_req_hash or a["requirements_hash"] != current_req_hash:
            problems.append("the insurance requirements changed after the agreement was approved")
        if bound.get("agreement_revision_hash") != a["evidence_hash"] or bound.get("revision_id") != a["revision_id"]:
            problems.append("the approval bound another agreement revision")
        # the approval bound the commitment as the agreement snapshots it; _snapshot_problems
        # compares that snapshot with the live commitment
        if bound.get("commitment_version") != a["commitment_version"] or (ap["manifest"].get("amounts") or {}).get("commitment_total") != a["commitment_amount"]:
            problems.append("the approval bound another commitment version or amount")
        if bound.get("sov_hash") != a["sov_hash"]:
            problems.append("the approval bound another schedule of values")
        return problems

    def _signature_problems(self, sig: dict[str, Any] | None, a: dict[str, Any], *, signed: bool) -> list[str]:
        if sig is None:
            return [f"agreement {a['id']} has no {'signed' if signed else 'prepared'} signature"]
        problems = []
        if _hash_of(sig, _SIGNATURE_KEYS) != sig["content_hash"]:
            problems.append(f"signature {sig['id']} no longer hashes to its recorded content hash")
        if sig["agreement_id"] != a["id"]:
            problems.append(f"signature {sig['id']} belongs to another agreement")
        if signed:
            if sig["status"] != "signed":
                problems.append(f"signature {sig['id']} is {sig['status']}, not signed")
            ap = self._approval(sig["approval_id"])
            if ap is None or ap["status"] != "consumed" or ap["operation"] != OP_SIGN or ap["subject_id"] != a["id"]:
                problems.append(f"signature {sig['id']} does not rest on a consumed {OP_SIGN} approval")
        elif sig["status"] != "prepared":
            problems.append(f"signature {sig['id']} is {sig['status']}, not prepared")
        cur = self._current_revision(sig["document_id"])
        if cur is None or cur["id"] != sig["revision_id"]:
            problems.append(f"signed-agreement document {sig['document_id']} was revised after revision {sig['revision']} was bound "
                            f"(now revision {cur['revision'] if cur else '?'}); prepare the signature again from the current copy")
        return problems

    def _agreement_problems(self, a: dict[str, Any]) -> list[str]:
        """What stands between a live agreement and its next step (empty for a signed agreement
        whose commitment is already executed and intact)."""
        if a["status"] == "registered":
            return self._snapshot_problems(a)
        draft = (self.db.scalar("SELECT status FROM commitments WHERE id=?", (a["commitment_id"],)) == "draft")
        problems = self._snapshot_problems(a) if draft else ([] if _hash_of(a, _AGREEMENT_KEYS) == a["content_hash"]
                                                              else [f"agreement {a['id']} no longer hashes to its recorded content hash"])
        problems += self._approval_problems(a) if draft else []
        if a["status"] == "signed":
            sig = self._signature_row(a["signature_id"])
            problems += [p for p in self._signature_problems(sig, a, signed=True) if draft or "was revised" not in p]
        return problems

    # ---- signatures -------------------------------------------------------------------------- #

    @staticmethod
    def _signature_view(sig: dict[str, Any]) -> dict[str, Any]:
        return {k: sig[k] for k in ("id", "agreement_id", "status", "document_id", "revision_id", "revision", "signed_copy_hash", "signer",
                                    "signing_date", "content_hash", "approval_id", "signed_at", "executed_by", "prepared_by", "prepared_at",
                                    "withdrawn_at", "withdrawn_reason")}

    def signature(self, signature_id: str) -> dict[str, Any]:
        sig = self._signature_row(signature_id)
        if sig is None:
            raise ContractError(f"unknown signature {signature_id}")
        view = self._signature_view(sig)
        cur = self._current_revision(sig["document_id"])
        view["document_current"] = cur is not None and cur["id"] == sig["revision_id"]
        return view

    def _withdraw_signature(self, sig: dict[str, Any], who: str, reason: str) -> None:
        now = utcnow_iso()
        self.audit.record(who, "contract.signature_withdrawn", SIGNATURE_SUBJECT, sig["id"], {
            "withdrawn_at": now, "reason": reason, "agreement_id": sig["agreement_id"],
        })
        self.db.execute("UPDATE contract_signatures SET status='withdrawn', withdrawn_at=?, withdrawn_reason=? WHERE id=?", (now, reason, sig["id"]))
        for row in self.db.query("SELECT id FROM approvals WHERE operation=? AND subject_id=? AND status IN ('pending','granted')", (OP_SIGN, sig["agreement_id"])):
            self.approvals.invalidate(row["id"], reason=f"the prepared signature was withdrawn: {reason}", actor=who)

    def prepare_signature(self, agreement_id: str, evidence_hash: str, signer: str, signing_date: str, actor: str) -> dict[str, Any]:
        """Record the signed copy, the signer and the signing date of an APPROVED agreement whose
        approval still matches (see the module docstring).  A prepared signature not yet signed
        is replaced (withdrawn) by a new one."""
        who = self._actor(actor)
        signer = _text(signer, "signer")
        day = _date(signing_date, "signing_date")
        with self.db.transaction() as conn:
            a = self._agreement_row(agreement_id)
            if a["status"] != "approved":
                raise ContractError(f"agreement {agreement_id} is {a['status']}; a signature is prepared for an approved agreement"
                                    + (" (request contract.approve_agreement first)" if a["status"] == "registered" else ""))
            problems = self._snapshot_problems(a) + self._approval_problems(a)
            if problems:
                raise ContractError(f"agreement {agreement_id} cannot be signed: " + "; ".join(problems))
            if day.isoformat() < a["approved_on"]:
                raise ContractError(f"signing date {day.isoformat()} is before the agreement was approved ({a['approved_on']}); "
                                    "the signer signs the approved agreement")
            if day > self._today():
                raise ContractError(f"signing date {day.isoformat()} is in the future (today is {self._today().isoformat()})")
            why = self._signer_problem(signer, a["project_id"])
            if why:
                raise ContractError(why)
            rev = self._resolve_evidence(evidence_hash, SIGNED_AGREEMENT_KIND, project_id=a["project_id"], label="a signed agreement copy")
            taken = self.db.one(
                f"""SELECT s.id, s.agreement_id FROM contract_signatures s JOIN contract_agreements x ON x.id = s.agreement_id
                    WHERE s.document_id=? AND s.status IN ('prepared','signed') AND x.status IN {_LIVE_SQL} AND s.agreement_id != ?""",
                (rev["document_id"], agreement_id),
            )
            if taken is not None:
                raise ContractError(f"signed-agreement document {rev['document_id']} already backs signature {taken['id']} of agreement {taken['agreement_id']}")
            live = self._live_signature(agreement_id)
            if live is not None:
                self._withdraw_signature(live, who, "replaced by a newly prepared signature")
            signature_id = new_id("csig")
            row = {
                "id": signature_id, "agreement_id": agreement_id, "document_id": rev["document_id"], "revision_id": rev["id"],
                "revision": rev["revision"], "signed_copy_hash": rev["content_hash"], "signer": signer, "signing_date": day.isoformat(),
                "prepared_by": who, "prepared_at": utcnow_iso(),
            }
            row["content_hash"] = _hash_of(row, _SIGNATURE_KEYS)
            self.audit.record(who, "contract.signature_prepared", SIGNATURE_SUBJECT, signature_id, {
                "content_hash": row["content_hash"], "agreement_id": agreement_id, "signer": signer, "signing_date": row["signing_date"],
                "signed_copy_hash": rev["content_hash"], "document_id": rev["document_id"], "revision": rev["revision"],
            })
            conn.execute(
                """INSERT INTO contract_signatures (id, agreement_id, document_id, revision_id, revision, signed_copy_hash, signer, signing_date,
                   content_hash, status, prepared_by, prepared_at) VALUES (?,?,?,?,?,?,?,?,?,'prepared',?,?)""",
                (signature_id, agreement_id, rev["document_id"], rev["id"], rev["revision"], rev["content_hash"], signer, row["signing_date"],
                 row["content_hash"], who, row["prepared_at"]),
            )
        return self.signature(signature_id)

    # ---- certificates ------------------------------------------------------------------------ #

    def record_certificate(self, party_id: str, kind: str, carrier: str, policy_number: str, limit: Any, effective_date: str,
                           expiry_date: str, evidence_hash: str, actor: str) -> dict[str, Any]:
        """Record a supplier's insurance policy or surety bond from the current revision of an
        ``insurance_certificate`` document (see the module docstring)."""
        who = self._actor(actor)
        if kind not in COVERAGE_KINDS:
            raise ContractError(f"certificate kind must be one of {', '.join(COVERAGE_KINDS)}, got {kind!r}")
        carrier = _text(carrier, "carrier")
        policy_number = _text(policy_number, "policy number", max_length=64)
        amt = _amount(limit, "certificate limit")
        effective = _date(effective_date, "effective_date")
        expiry = _date(expiry_date, "expiry_date")
        if expiry < effective:
            raise ContractError(f"certificate expiry {expiry.isoformat()} is before its effective date {effective.isoformat()}")
        with self.db.transaction() as conn:
            party = self.db.one("SELECT id, kind FROM parties WHERE id=?", (party_id,)) if isinstance(party_id, str) else None
            if party is None:
                raise ContractError(f"unknown party {party_id}")
            if party["kind"] != "supplier":
                raise ContractError(f"insurance and bond certificates are recorded for suppliers; {party_id} is a {party['kind']}")
            rev = self._resolve_evidence(evidence_hash, CERTIFICATE_KIND, project_id=None, label="an insurance certificate")
            other = self.db.one("SELECT party_id FROM contract_certificates WHERE document_id=? AND party_id != ?", (rev["document_id"], party_id))
            if other is not None:
                raise ContractError(f"insurance certificate document {rev['document_id']} already belongs to supplier {other['party_id']}")
            dup = self.db.one("SELECT id FROM contract_certificates WHERE revision_id=? AND kind=?", (rev["id"], kind))
            if dup is not None:
                raise ContractError(f"revision {rev['revision']} of document {rev['document_id']} already carries {kind} certificate {dup['id']}")
            certificate_id = new_id("ccert")
            row = {
                "id": certificate_id, "party_id": party_id, "kind": kind, "carrier": carrier, "policy_number": policy_number,
                "limit_amount": fmt(amt), "effective_date": effective.isoformat(), "expiry_date": expiry.isoformat(),
                "document_id": rev["document_id"], "revision_id": rev["id"], "revision": rev["revision"], "evidence_hash": rev["content_hash"],
                "recorded_by": who, "recorded_at": utcnow_iso(),
            }
            row["content_hash"] = _hash_of(row, _CERTIFICATE_KEYS)
            self.audit.record(who, "contract.certificate_recorded", CERTIFICATE_SUBJECT, certificate_id, {
                "content_hash": row["content_hash"], "party_id": party_id, "kind": kind, "carrier": carrier, "policy_number": policy_number,
                "limit": row["limit_amount"], "effective_date": row["effective_date"], "expiry_date": row["expiry_date"],
                "evidence_hash": rev["content_hash"], "document_id": rev["document_id"], "revision": rev["revision"],
            })
            conn.execute(
                """INSERT INTO contract_certificates (id, party_id, kind, carrier, policy_number, limit_amount, effective_date, expiry_date,
                   document_id, revision_id, revision, evidence_hash, content_hash, status, recorded_by, recorded_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,'recorded',?,?)""",
                (certificate_id, party_id, kind, carrier, policy_number, row["limit_amount"], row["effective_date"], row["expiry_date"],
                 rev["document_id"], rev["id"], rev["revision"], rev["content_hash"], row["content_hash"], who, row["recorded_at"]),
            )
        return self.certificate(certificate_id)

    def withdraw_certificate(self, certificate_id: str, reason: str, actor: str) -> dict[str, Any]:
        """Record that a certificate no longer evidences coverage (a cancellation notice, a
        certificate recorded in error).  Approvals that bound it become stale."""
        who = self._actor(actor)
        why = _text(reason, "reason")
        with self.db.transaction() as conn:
            cert = self._certificate_row(certificate_id)
            if cert["status"] != "recorded":
                raise ContractError(f"certificate {certificate_id} was already withdrawn")
            now = utcnow_iso()
            self.audit.record(who, "contract.certificate_withdrawn", CERTIFICATE_SUBJECT, certificate_id, {
                "withdrawn_at": now, "reason": why, "party_id": cert["party_id"], "kind": cert["kind"],
            })
            conn.execute("UPDATE contract_certificates SET status='withdrawn', withdrawn_by=?, withdrawn_at=?, withdrawn_reason=? WHERE id=?",
                         (who, now, why, certificate_id))
        return self.certificate(certificate_id)

    def _certificate_row(self, certificate_id: Any) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM contract_certificates WHERE id=?", (certificate_id,)) if isinstance(certificate_id, str) else None
        if row is None:
            raise ContractError(f"unknown certificate {certificate_id}")
        return row

    def _certificate_state(self, cert: dict[str, Any], day: _dt.date | None = None) -> dict[str, Any]:
        day = day or self._today()
        cur = self._current_revision(cert["document_id"])
        intact = _hash_of(cert, _CERTIFICATE_KEYS) == cert["content_hash"]
        stale = cur is None or cur["id"] != cert["revision_id"]
        effective, expiry = _dt.date.fromisoformat(cert["effective_date"]), _dt.date.fromisoformat(cert["expiry_date"])
        valid = cert["status"] == "recorded" and intact and not stale
        return {"intact": intact, "stale": stale, "valid": valid, "in_force": valid and effective <= day <= expiry,
                "expired": day > expiry, "not_yet_effective": day < effective, "days_to_expiry": (expiry - day).days}

    def certificate(self, certificate_id: str) -> dict[str, Any]:
        cert = self._certificate_row(certificate_id)
        return {**cert, **self._certificate_state(cert)}

    def certificates(self, party_id: str | None = None) -> list[dict[str, Any]]:
        if party_id:
            rows = self.db.query("SELECT id FROM contract_certificates WHERE party_id=? ORDER BY kind, effective_date, id", (party_id,))
        else:
            rows = self.db.query("SELECT id FROM contract_certificates ORDER BY party_id, kind, effective_date, id")
        return [self.certificate(r["id"]) for r in rows]

    # ---- coverage ---------------------------------------------------------------------------- #

    def _eligible(self, party_id: str, kind: str, min_limit: str) -> list[dict[str, Any]]:
        """Certificates able to cover a requirement whatever the date: recorded, intact, on the
        current revision of their document and at or above the minimum limit."""
        out = []
        for cert in self.db.query("SELECT * FROM contract_certificates WHERE party_id=? AND kind=? AND status='recorded' ORDER BY effective_date, expiry_date, id",
                                  (party_id, kind)):
            st = self._certificate_state(cert)
            if st["valid"] and money(cert["limit_amount"]) >= money(min_limit):
                out.append(cert)
        return out

    def _coverage_scope(self, operation: str, subject_id: str) -> list[str]:
        """The commitments whose requirements a governed operation must satisfy."""
        if operation in ("bill.approve", "payment.release"):
            row = self.db.one("SELECT commitment_id FROM bills WHERE id=?", (subject_id,))
            return [row["commitment_id"]] if row else []
        if operation == "payment.release_retainage":
            c = self.db.one("SELECT supplier_id, project_id FROM commitments WHERE id=?", (subject_id,))
            if c is None:
                return []
            # released retainage is paid per supplier and project, whichever commitment is named
            rows = self.db.query("SELECT id FROM commitments WHERE supplier_id=? AND project_id=? ORDER BY created_at, id", (c["supplier_id"], c["project_id"]))
            return [r["id"] for r in rows]
        return []

    def _coverage_facts(self, commitment_ids: list[str]) -> dict[str, Any] | None:
        sets, minimum, supplier = [], {}, None
        for cid in commitment_ids:
            rs = self._requirement_set(cid)
            if rs is None or not rs["requirements"]:
                continue
            supplier = self.db.scalar("SELECT supplier_id FROM commitments WHERE id=?", (cid,))
            sets.append({"commitment_id": cid, "set_id": rs["id"], "version": rs["version"], "requirements_hash": rs["requirements_hash"]})
            for req in rs["requirements"]:
                if req["kind"] not in minimum or money(req["min_limit"]) > money(minimum[req["kind"]]):
                    minimum[req["kind"]] = req["min_limit"]
        if not sets:
            return None
        coverage = []
        for kind in COVERAGE_KINDS:
            if kind not in minimum:
                continue
            certs = self._eligible(supplier, kind, minimum[kind])
            coverage.append({"kind": kind, "min_limit": minimum[kind], "certificates": [
                {"id": x["id"], "content_hash": x["content_hash"], "limit": x["limit_amount"], "effective_date": x["effective_date"],
                 "expiry_date": x["expiry_date"], "carrier": x["carrier"], "policy_number": x["policy_number"]} for x in certs]})
        return {"supplier_id": supplier, "requirement_sets": sets, "coverage": coverage}

    def _certificate_problem(self, cert: dict[str, Any] | None, bound: dict[str, Any], min_limit: str, day: _dt.date) -> str | None:
        if cert is None:
            return f"certificate {bound['id']} is missing"
        st = self._certificate_state(cert, day)
        if cert["status"] != "recorded":
            return f"certificate {cert['id']} was withdrawn ({cert['withdrawn_reason']})"
        if not st["intact"] or cert["content_hash"] != bound["content_hash"]:
            return f"certificate {cert['id']} changed after the approval bound it"
        if st["stale"]:
            return f"certificate {cert['id']} is stale: its document was revised"
        if money(cert["limit_amount"]) < money(min_limit):
            return f"certificate {cert['id']} limit {cert['limit_amount']} is below the minimum {min_limit}"
        if st["not_yet_effective"]:
            return f"certificate {cert['id']} is not effective until {cert['effective_date']}"
        if st["expired"]:
            return f"certificate {cert['id']} expired on {cert['expiry_date']}"
        return None

    def _cover(self, facts: dict[str, Any], day: _dt.date) -> list[dict[str, Any]]:
        """For each bound requirement, the bound certificate in force on ``day`` (the one
        expiring last); raises ``CoverageError`` naming every requirement left uncovered."""
        chosen, missing = [], []
        for req in facts.get("coverage") or []:
            best, reasons = None, []
            for bound in req["certificates"]:
                cert = self.db.one("SELECT * FROM contract_certificates WHERE id=?", (bound["id"],))
                problem = self._certificate_problem(cert, bound, req["min_limit"], day)
                if problem:
                    reasons.append(problem)
                elif best is None or cert["expiry_date"] > best["expiry_date"]:
                    best = cert
            if best is None:
                missing.append(f"{req['kind']} (minimum {req['min_limit']}): " + ("; ".join(reasons) if reasons else
                               "no current certificate at or above the minimum is recorded for the supplier"))
            else:
                chosen.append({"kind": req["kind"], "min_limit": req["min_limit"], "certificate_id": best["id"], "certificate_hash": best["content_hash"],
                               "limit": best["limit_amount"], "effective_date": best["effective_date"], "expiry_date": best["expiry_date"]})
        if missing:
            raise CoverageError(f"required insurance or bond coverage of supplier {facts.get('supplier_id')} is not in force on {day.isoformat()}: "
                                + " | ".join(missing) + " (record a current certificate with record_certificate, then request a fresh approval)")
        return chosen

    def coverage(self, commitment_id: str, on: str | None = None) -> list[dict[str, Any]]:
        """Per requirement of the commitment: whether coverage is in force on ``on`` (default
        today) and which certificate provides it."""
        self._commitment(commitment_id)
        day = _date(on, "on") if on is not None else self._today()
        rs = self._requirement_set(commitment_id)
        out = []
        supplier = self.db.scalar("SELECT supplier_id FROM commitments WHERE id=?", (commitment_id,))
        for req in (rs["requirements"] if rs else []):
            certs = self.db.query("SELECT * FROM contract_certificates WHERE party_id=? AND kind=? ORDER BY effective_date, expiry_date, id", (supplier, req["kind"]))
            best, reasons = None, []
            for cert in certs:
                problem = self._certificate_problem(cert, {"id": cert["id"], "content_hash": cert["content_hash"]}, req["min_limit"], day)
                if problem:
                    reasons.append(problem)
                elif best is None or cert["expiry_date"] > best["expiry_date"]:
                    best = cert
            out.append({"kind": req["kind"], "min_limit": req["min_limit"], "in_force": best is not None,
                        "certificate_id": best["id"] if best else None, "expiry_date": best["expiry_date"] if best else None,
                        "reasons": [] if best else (reasons or ["no certificate recorded"])})
        return out

    def _record_coverage(self, approval: dict[str, Any], chosen: list[dict[str, Any]], day: _dt.date, actor: str) -> None:
        """Inside the execution transaction: which certificate covered each requirement."""
        coverage_hash = hash_json({"approval_id": approval["id"], "operation": approval["operation"], "subject_id": approval["subject_id"],
                                   "checked_on": day.isoformat(), "coverage": chosen})
        check_id = new_id("ccov")
        who = actor if isinstance(actor, str) and actor.strip() else "system"
        with self.db.transaction() as conn:
            self.audit.record(who, "contract.coverage_verified", "approval", approval["id"], {
                "check_id": check_id, "coverage_hash": coverage_hash, "operation": approval["operation"], "subject_id": approval["subject_id"],
                "checked_on": day.isoformat(), "certificates": [c["certificate_id"] for c in chosen],
            })
            conn.execute(
                """INSERT INTO contract_coverage_checks (id, approval_id, operation, subject_id, checked_on, coverage_json, coverage_hash, checked_by, checked_at)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (check_id, approval["id"], approval["operation"], approval["subject_id"], day.isoformat(), canonical_json(chosen), coverage_hash,
                 who, utcnow_iso()),
            )

    # ---- commitment execution facts ---------------------------------------------------------- #

    def _execution_facts(self, commitment_id: str) -> dict[str, Any] | None:
        required = self.agreements_required()
        a = self._live_agreement(commitment_id)
        rs = self._requirement_set(commitment_id)
        if not required and a is None and (rs is None or not rs["requirements"]):
            return None
        facts: dict[str, Any] = {"agreements_required": required, "agreement": None, "requirements": None}
        if rs is not None:
            facts["requirements"] = {"set_id": rs["id"], "version": rs["version"], "requirements_hash": rs["requirements_hash"]}
        if a is not None:
            cur = self._current_revision(a["document_id"])
            ap = self._approval(a["approval_id"])
            sig = self._signature_row(a["signature_id"]) if a["signature_id"] else None
            sig_cur = self._current_revision(sig["document_id"]) if sig else None
            facts["agreement"] = {
                "id": a["id"], "status": a["status"], "content_hash": a["content_hash"], "evidence_hash": a["evidence_hash"],
                "revision_id": a["revision_id"], "document_current_hash": cur["content_hash"] if cur else None,
                "approval_id": a["approval_id"], "approval_material_hash": ap["material_hash"] if ap else None,
                "signature_id": a["signature_id"], "signature_hash": sig["content_hash"] if sig else None,
                "signed_copy_hash": sig["signed_copy_hash"] if sig else None, "signed_copy_current_hash": sig_cur["content_hash"] if sig_cur else None,
                "signer": sig["signer"] if sig else None, "signing_date": sig["signing_date"] if sig else None,
            }
        return facts

    def _execution_problems(self, commitment_id: str, facts: dict[str, Any]) -> list[str]:
        """Why the commitment may not execute yet under its contract facts (empty when it may)."""
        if not facts.get("agreements_required") and facts.get("agreement") is None:
            return []  # requirements only: they are enforced on bills and payments
        a = self._live_agreement(commitment_id)
        if a is None:
            return ["agreements are required in this workspace: register the agreement (register_agreement), approve it "
                    f"({OP_APPROVE}) and sign it ({OP_SIGN}) before executing the commitment"]
        if a["status"] != "signed":
            step = OP_APPROVE if a["status"] == "registered" else OP_SIGN
            return [f"agreement {a['id']} is {a['status']}, not signed; {step} must execute before the commitment does"]
        problems = self._snapshot_problems(a) + self._approval_problems(a)
        problems += self._signature_problems(self._signature_row(a["signature_id"]), a, signed=True)
        return problems

    # ---- governor hooks ---------------------------------------------------------------------- #

    def approval_policy(self, operation: str, manifest: dict[str, Any]) -> dict[str, Any] | None:
        """State-derived contract facts bound into other modules' approvals (None when nothing
        is configured for the subject)."""
        if operation == EXECUTE_OPERATION:
            return self._execution_facts((manifest.get("subject") or {}).get("id"))
        if operation in COVERAGE_OPERATIONS:
            scope = self._coverage_scope(operation, (manifest.get("subject") or {}).get("id"))
            return self._coverage_facts(scope) if scope else None
        return None

    def check_request(self, operation: str, manifest: dict[str, Any], *, actor_role: str, requested_by: str) -> None:
        facts = (manifest.get("governance") or {}).get(PLUGIN_NAME)
        if operation == EXECUTE_OPERATION and facts:
            problems = self._execution_problems(manifest["subject"]["id"], facts)
            if problems:
                raise ContractError(f"commitment {manifest['subject']['id']} cannot be executed yet: " + "; ".join(problems))
        elif operation in COVERAGE_OPERATIONS and facts:
            self._cover(facts, self._today())
        elif operation == OP_REQUIRE and actor_role != "owner":
            raise ContractError(f"{OP_REQUIRE} is executed by the owner only, not {actor_role!r}")
        elif operation == OP_SIGN:
            bound = manifest.get("bindings") or {}
            why = self._signer_problem(bound.get("signer"), bound.get("project_id"))
            if why:
                raise ContractError(why)

    def check_grant(self, approval: dict[str, Any], *, approver: str, approver_role: str) -> None:
        operation = approval["operation"]
        if operation == OP_SIGN:
            bound = (approval.get("manifest") or {}).get("bindings") or {}
            if _login_key(approver) is None or _login_key(approver) != _login_key(bound.get("signer")):
                raise ContractError(f"only the named signer {bound.get('signer')!r} grants this signature; {approver!r} cannot sign on their behalf")
            why = self._signer_problem(approver, bound.get("project_id"))
            if why:
                raise ContractError(why)
        elif operation == OP_REQUIRE and approver_role != "owner":
            raise ContractError(f"{OP_REQUIRE} is granted by the owner only, not by role {approver_role!r}")

    def check_execute(self, approval: dict[str, Any], manifest: dict[str, Any], *, actor: str) -> None:
        operation = approval["operation"]
        facts = (manifest.get("governance") or {}).get(PLUGIN_NAME)
        if operation == EXECUTE_OPERATION and facts:
            problems = self._execution_problems(approval["subject_id"], facts)
            if problems:
                raise AgreementIneligible(f"commitment {approval['subject_id']} cannot be executed: " + "; ".join(problems))
        elif operation in COVERAGE_OPERATIONS and facts:
            day = self._today()
            chosen = self._cover(facts, day)
            self._record_coverage(approval, chosen, day, actor)
        elif operation == OP_SIGN:
            bound = (approval.get("manifest") or {}).get("bindings") or {}
            why = self._signer_problem(bound.get("signer"), bound.get("project_id"))
            if why:
                raise ContractError(why)

    # ---- manifests --------------------------------------------------------------------------- #

    def manifest_for(self, operation: str, subject_id: str, *, actor_role: str) -> dict[str, Any]:
        if operation == OP_REQUIRE:
            return self._require_manifest(subject_id, actor_role=actor_role)
        if operation == OP_APPROVE:
            return self._approve_manifest(subject_id, actor_role=actor_role)
        if operation == OP_SIGN:
            return self._sign_manifest(subject_id, actor_role=actor_role)
        raise ContractError(f"unknown contract operation {operation}")

    def _require_manifest(self, subject_id: str, *, actor_role: str) -> dict[str, Any]:
        if subject_id != WORKSPACE_SUBJECT_ID:
            raise ContractError(f"{OP_REQUIRE} applies to subject {WORKSPACE_SUBJECT_ID!r}, not {subject_id!r}")
        if actor_role != "owner":
            raise ContractError(f"{OP_REQUIRE} is executed by the owner only, not {actor_role!r}")
        if self.agreements_required():
            raise ContractError("agreements are already required in this workspace")
        return build_manifest(
            operation=OP_REQUIRE, subject_type=WORKSPACE_SUBJECT, subject_id=WORKSPACE_SUBJECT_ID, actor_role=actor_role,
            bindings={"workspace_id": self.db.workspace()["workspace_id"], "agreements_required": False,
                      "effect": "every commitment executed afterwards needs a signed agreement; the requirement cannot be lifted"},
        )

    def _manifest_scope(self, project_id: str) -> dict[str, str]:
        project = self._project(project_id)
        return {"entity": project["entity"], "currency": project["currency"] or "USD"}

    def _approve_manifest(self, agreement_id: str, *, actor_role: str) -> dict[str, Any]:
        a = self._agreement_row(agreement_id)
        if a["status"] != "registered":
            raise AgreementIneligible(f"agreement {agreement_id} is {a['status']}; only a registered agreement is approved")
        problems = self._snapshot_problems(a)
        if problems:
            raise AgreementIneligible(f"agreement {agreement_id} cannot be approved: " + "; ".join(problems))
        c = self.c.commitments.get(a["commitment_id"])
        rs = self._requirement_set(a["commitment_id"])
        return build_manifest(
            operation=OP_APPROVE, subject_type=AGREEMENT_SUBJECT, subject_id=agreement_id, actor_role=actor_role,
            amounts={"commitment_total": c["original_amount"]},
            bindings={
                "agreement_id": a["id"], "agreement_hash": a["content_hash"], "agreement_status": a["status"],
                "commitment_id": c["id"], "commitment_version": c["version"], "commitment_status": c["status"], "title": c["title"],
                "project_id": c["project_id"], "supplier_id": c["supplier_id"], "retainage_rate": c["retainage_rate"],
                "sov": [{"line_no": s["line_no"], "description": s["description"], "cost_code": s["cost_code"], "amount": s["amount"]} for s in c["sov"]],
                "sov_hash": self.c.commitments.sov_hash(c["id"]),
                "document_id": a["document_id"], "revision_id": a["revision_id"], "revision": a["revision"], "agreement_revision_hash": a["evidence_hash"],
                "requirements": rs["requirements"] if rs else [], "requirements_hash": rs["requirements_hash"] if rs else None,
                "requirements_version": rs["version"] if rs else 0,
                "effect": "approves this exact agreement revision for this commitment; signature (contract.sign) and execution (commitment.execute) remain separate",
            },
            **self._manifest_scope(a["project_id"]),
        )

    def _sign_manifest(self, agreement_id: str, *, actor_role: str) -> dict[str, Any]:
        a = self._agreement_row(agreement_id)
        if a["status"] != "approved":
            raise AgreementIneligible(f"agreement {agreement_id} is {a['status']}; only an approved agreement is signed"
                                      + (f" (request {OP_APPROVE} first)" if a["status"] == "registered" else ""))
        sig = self._live_signature(agreement_id)
        problems = self._snapshot_problems(a) + self._approval_problems(a) + self._signature_problems(sig, a, signed=False)
        if sig is not None and sig["signing_date"] > self._today().isoformat():
            problems.append(f"signing date {sig['signing_date']} is in the future")
        if problems:
            raise AgreementIneligible(f"agreement {agreement_id} cannot be signed: " + "; ".join(problems)
                                      + ("" if sig else " (prepare_signature records the signed copy, signer and date)"))
        ap = self._approval(a["approval_id"])
        c = self.c.commitments.get(a["commitment_id"])
        return build_manifest(
            operation=OP_SIGN, subject_type=AGREEMENT_SUBJECT, subject_id=agreement_id, actor_role=actor_role,
            amounts={"commitment_total": c["original_amount"]},
            bindings={
                "agreement_id": a["id"], "agreement_hash": a["content_hash"], "agreement_status": a["status"],
                "agreement_approval_id": a["approval_id"], "agreement_approval_material_hash": ap["material_hash"],
                "approved_by": a["approved_by"], "approved_on": a["approved_on"],
                "commitment_id": c["id"], "commitment_version": c["version"], "project_id": c["project_id"], "supplier_id": c["supplier_id"],
                "sov_hash": self.c.commitments.sov_hash(c["id"]), "agreement_revision_hash": a["evidence_hash"], "revision_id": a["revision_id"],
                "requirements_hash": a["requirements_hash"],
                "signature_id": sig["id"], "signature_hash": sig["content_hash"], "signed_copy_document_id": sig["document_id"],
                "signed_copy_revision_id": sig["revision_id"], "signed_copy_hash": sig["signed_copy_hash"],
                "signer": sig["signer"], "signing_date": sig["signing_date"],
                "effect": "records the signer's execution of the approved agreement; the commitment executes separately (commitment.execute)",
            },
            **self._manifest_scope(a["project_id"]),
        )

    # ---- apply ------------------------------------------------------------------------------- #

    def _own_consumed(self, approval_id: Any, operation: str, subject_id: str) -> dict[str, Any]:
        ap = self._approval(approval_id)
        if ap is None or ap["operation"] != operation or ap["subject_id"] != subject_id or ap["status"] != "consumed":
            raise ContractError(f"{operation} on {subject_id} runs only against its own consumed approval")
        return ap

    def apply(self, operation: str, subject_id: str, *, approval_id: str, manifest: dict[str, Any], actor: str, period_id: str | None) -> dict[str, Any]:
        """Apply an approved contract operation; the caller has consumed ``approval_id`` against
        ``manifest`` in this transaction."""
        if operation == OP_REQUIRE:
            return self._apply_require(subject_id, approval_id=approval_id, actor=actor)
        if operation == OP_APPROVE:
            return self._apply_approve(subject_id, approval_id=approval_id, manifest=manifest, actor=actor)
        if operation == OP_SIGN:
            return self._apply_sign(subject_id, approval_id=approval_id, manifest=manifest, actor=actor)
        raise ContractError(f"unknown contract operation {operation}")

    def _apply_require(self, subject_id: str, *, approval_id: str, actor: str) -> dict[str, Any]:
        with self.db.transaction() as conn:
            self._own_consumed(approval_id, OP_REQUIRE, subject_id)
            if self.agreements_required():
                raise ContractError("agreements are already required in this workspace")
            workspace_id = self.db.workspace()["workspace_id"]
            now = utcnow_iso()
            self.audit.record(actor, "contract.agreements_required", WORKSPACE_SUBJECT, WORKSPACE_SUBJECT_ID, {
                "approval_id": approval_id, "workspace_id": workspace_id, "set_at": now,
            })
            conn.execute("INSERT INTO contract_workspace_policy (id, agreements_required, workspace_id, approval_id, set_by, set_at) VALUES (1,1,?,?,?,?)",
                         (workspace_id, approval_id, actor, now))
        return {"agreements_required": True, "approval_id": approval_id, "set_at": now}

    def _apply_approve(self, agreement_id: str, *, approval_id: str, manifest: dict[str, Any], actor: str) -> dict[str, Any]:
        bound = manifest.get("bindings") or {}
        with self.db.transaction() as conn:
            a = self._agreement_row(agreement_id)
            if a["status"] != "registered":
                raise AgreementIneligible(f"agreement {agreement_id} is {a['status']}; it can no longer be approved")
            problems = self._snapshot_problems(a)
            rs = self._requirement_set(a["commitment_id"])
            req_hash = rs["requirements_hash"] if rs else None
            if bound.get("requirements_hash") != req_hash or bound.get("agreement_hash") != a["content_hash"] or bound.get("sov_hash") != a["sov_hash"]:
                problems.append("the agreement, its schedule of values or the requirements no longer match the approval")
            if problems:
                raise AgreementIneligible(f"agreement {agreement_id} can no longer be approved: " + "; ".join(problems))
            self._own_consumed(approval_id, OP_APPROVE, agreement_id)
            for row in self.db.query("SELECT id FROM approvals WHERE operation=? AND subject_id=? AND status IN ('pending','granted') AND id != ?",
                                     (OP_APPROVE, agreement_id, approval_id)):
                self.approvals.invalidate(row["id"], reason="the agreement was approved under another approval", actor=actor)
            now, day = utcnow_iso(), self._today().isoformat()
            self.audit.record(actor, "contract.agreement_approved", AGREEMENT_SUBJECT, agreement_id, {
                "approval_id": approval_id, "requirements_hash": req_hash, "commitment_id": a["commitment_id"], "commitment_version": a["commitment_version"],
                "sov_hash": a["sov_hash"], "evidence_hash": a["evidence_hash"], "approved_on": day,
            })
            conn.execute("UPDATE contract_agreements SET status='approved', approval_id=?, requirements_hash=?, approved_by=?, approved_at=?, approved_on=? WHERE id=?",
                         (approval_id, req_hash, actor, now, day, agreement_id))
            self._invalidate_execution(a["commitment_id"], actor, f"agreement {agreement_id} was approved; it still has to be signed")
        return {"agreement": agreement_id, "status": "approved", "commitment": a["commitment_id"], "approved_on": day, "requirements_hash": req_hash}

    def _apply_sign(self, agreement_id: str, *, approval_id: str, manifest: dict[str, Any], actor: str) -> dict[str, Any]:
        bound = manifest.get("bindings") or {}
        with self.db.transaction() as conn:
            a = self._agreement_row(agreement_id)
            if a["status"] != "approved":
                raise AgreementIneligible(f"agreement {agreement_id} is {a['status']}; it can no longer be signed")
            sig = self._live_signature(agreement_id)
            problems = self._snapshot_problems(a) + self._approval_problems(a) + self._signature_problems(sig, a, signed=False)
            if sig is not None and (bound.get("signature_id") != sig["id"] or bound.get("signature_hash") != sig["content_hash"]):
                problems.append("the prepared signature is not the one approved")
            if problems:
                raise AgreementIneligible(f"agreement {agreement_id} can no longer be signed: " + "; ".join(problems))
            self._own_consumed(approval_id, OP_SIGN, agreement_id)
            now = utcnow_iso()
            self.audit.record(actor, "contract.agreement_signed", SIGNATURE_SUBJECT, sig["id"], {
                "approval_id": approval_id, "agreement_id": agreement_id, "signer": sig["signer"], "signing_date": sig["signing_date"],
                "signed_copy_hash": sig["signed_copy_hash"], "commitment_id": a["commitment_id"],
            })
            conn.execute("UPDATE contract_signatures SET status='signed', approval_id=?, signed_at=?, executed_by=? WHERE id=?",
                         (approval_id, now, actor, sig["id"]))
            conn.execute("UPDATE contract_agreements SET status='signed', signature_id=?, signed_at=? WHERE id=?", (sig["id"], now, agreement_id))
            for row in self.db.query("SELECT id FROM approvals WHERE operation=? AND subject_id=? AND status IN ('pending','granted') AND id != ?",
                                     (OP_SIGN, agreement_id, approval_id)):
                self.approvals.invalidate(row["id"], reason="the agreement was signed under another approval", actor=actor)
            # an execution approval requested before the signature bound an unsigned agreement
            self._invalidate_execution(a["commitment_id"], actor, f"agreement {agreement_id} was signed; request commitment.execute against the signed agreement")
        return {"agreement": agreement_id, "status": "signed", "signature": sig["id"], "signer": sig["signer"], "signing_date": sig["signing_date"],
                "commitment": a["commitment_id"]}

    # ---- findings: unsigned billed commitments, expiring coverage, integrity ------------------ #

    def _policy_seq(self) -> int | None:
        """Audit sequence of the entry that made agreements required (None when not required)."""
        if not self.agreements_required():
            return None
        return self.db.scalar("SELECT MIN(seq) FROM audit_log WHERE action='contract.agreements_required'") or 0

    def _agreement_required_for(self, commitment: dict[str, Any], policy_seq: int | None) -> bool:
        """A commitment needs a signed agreement when one was registered for it, or when it is a
        draft or was executed after the workspace began requiring agreements (by audit order; an
        executed commitment with no audited execution counts as executed afterwards)."""
        if self.db.one("SELECT 1 AS x FROM contract_agreements WHERE commitment_id=? AND status != 'superseded'", (commitment["id"],)):
            return True
        if policy_seq is None:
            return False
        if commitment["status"] == "draft":
            return True
        executed = self.db.scalar("SELECT MAX(seq) FROM audit_log WHERE entity_type='commitment' AND entity_id=? AND action='commitment.executed'",
                                  (commitment["id"],))
        return executed is None or executed > policy_seq

    def unsigned_billed_commitments(self, project_id: str | None = None) -> list[dict[str, Any]]:
        """Commitments with bills (not void) that need a signed agreement and lack one."""
        policy_seq = self._policy_seq()
        if policy_seq is None and self.db.one("SELECT 1 AS x FROM contract_agreements LIMIT 1") is None:
            return []  # nothing configured: no commitment needs an agreement
        sql = "SELECT * FROM commitments WHERE status != 'draft'" + (" AND project_id=?" if project_id else "") + " ORDER BY created_at, id"
        out = []
        for c in self.db.query(sql, (project_id,) if project_id else ()):
            if not self._agreement_required_for(c, policy_seq):
                continue
            billed = self.db.scalar("SELECT COUNT(*) FROM bills WHERE commitment_id=? AND status != 'void'", (c["id"],)) or 0
            if not billed:
                continue
            signed = self.db.one(
                """SELECT a.id FROM contract_agreements a JOIN contract_signatures s ON s.id = a.signature_id
                   WHERE a.commitment_id=? AND a.status='signed' AND s.status='signed'""", (c["id"],))
            if signed is None:
                out.append({"commitment_id": c["id"], "title": c["title"], "status": c["status"], "bills": billed, "executed_at": c["executed_at"]})
        return out

    def coverage_findings(self, project_id: str | None = None) -> dict[str, list[dict[str, Any]]]:
        """``expiring``: certificates of suppliers with open commitments that expire within 30
        days with no later certificate of that kind recorded; ``lapsed``: requirements of
        executed open commitments with no certificate in force today."""
        expiring: list[dict[str, Any]] = []
        lapsed: list[dict[str, Any]] = []
        certified = {r["party_id"] for r in self.db.query("SELECT DISTINCT party_id FROM contract_certificates")}
        with_requirements = {r["commitment_id"] for r in self.db.query("SELECT DISTINCT commitment_id FROM contract_requirement_sets")}
        if not certified and not with_requirements:
            return {"expiring": expiring, "lapsed": lapsed}  # nothing configured
        today = self._today()
        horizon = today + _dt.timedelta(days=EXPIRY_WARNING_DAYS)
        sql = "SELECT * FROM commitments WHERE status IN ('draft','approved','executed')" + (" AND project_id=?" if project_id else "") + " ORDER BY created_at, id"
        open_commitments = self.db.query(sql, (project_id,) if project_id else ())
        for party_id in sorted({c["supplier_id"] for c in open_commitments} & certified):
            for kind in COVERAGE_KINDS:
                valid = [x for x in self.db.query("SELECT * FROM contract_certificates WHERE party_id=? AND kind=? AND status='recorded'", (party_id, kind))
                         if self._certificate_state(x, today)["valid"]]
                if not valid:
                    continue
                latest = max(valid, key=lambda x: (x["expiry_date"], x["effective_date"], x["id"]))
                expiry = _dt.date.fromisoformat(latest["expiry_date"])
                if today <= expiry <= horizon:
                    expiring.append({"certificate_id": latest["id"], "party_id": party_id, "kind": kind, "expiry_date": latest["expiry_date"],
                                     "carrier": latest["carrier"], "policy_number": latest["policy_number"]})
        for c in open_commitments:
            if c["status"] != "executed" or c["id"] not in with_requirements:
                continue
            for cov in self.coverage(c["id"], on=today.isoformat()):
                if not cov["in_force"]:
                    lapsed.append({"commitment_id": c["id"], "party_id": c["supplier_id"], "kind": cov["kind"], "min_limit": cov["min_limit"],
                                   "reasons": cov["reasons"]})
        return {"expiring": expiring, "lapsed": lapsed}

    def integrity_problems(self) -> list[str]:
        """Every contract record re-hashed and cross-checked against its approvals and audit
        entries; governed bills and payments on commitments with requirements carry a coverage
        check.  Detects tampering that went around the storage guards."""
        problems: list[str] = []

        def audited(action: str, entity_type: str, entity_id: str, key: str, value: Any) -> bool:
            for g in self.db.query("SELECT payload_json FROM audit_log WHERE entity_type=? AND entity_id=? AND action=?", (entity_type, entity_id, action)):
                if (loads(g["payload_json"]) or {}).get(key) == value:
                    return True
            return False

        for a in self.db.query("SELECT * FROM contract_agreements ORDER BY registered_at, id"):
            if _hash_of(a, _AGREEMENT_KEYS) != a["content_hash"] or not audited("contract.agreement_registered", AGREEMENT_SUBJECT, a["id"], "content_hash", a["content_hash"]):
                problems.append(f"agreement {a['id']} does not match its audited registration")
            if a["approval_id"] or a["status"] in ("approved", "signed"):
                ap = self._approval(a["approval_id"])
                if ap is None or ap["status"] != "consumed" or ap["operation"] != OP_APPROVE or ap["subject_id"] != a["id"]:
                    problems.append(f"agreement {a['id']} is {a['status']} without a consumed {OP_APPROVE} approval")
            if a["status"] == "signed" or a["signature_id"]:
                sig = self._signature_row(a["signature_id"])
                ap = self._approval(sig["approval_id"]) if sig else None
                if sig is None or sig["status"] != "signed" or ap is None or ap["status"] != "consumed" or ap["operation"] != OP_SIGN or ap["subject_id"] != a["id"]:
                    problems.append(f"agreement {a['id']} is signed without a signature executed under a consumed {OP_SIGN} approval")
        for s in self.db.query("SELECT * FROM contract_signatures ORDER BY prepared_at, id"):
            if _hash_of(s, _SIGNATURE_KEYS) != s["content_hash"] or not audited("contract.signature_prepared", SIGNATURE_SUBJECT, s["id"], "content_hash", s["content_hash"]):
                problems.append(f"signature {s['id']} does not match its audited preparation")
        for x in self.db.query("SELECT * FROM contract_certificates ORDER BY recorded_at, id"):
            if _hash_of(x, _CERTIFICATE_KEYS) != x["content_hash"] or not audited("contract.certificate_recorded", CERTIFICATE_SUBJECT, x["id"], "content_hash", x["content_hash"]):
                problems.append(f"certificate {x['id']} does not match its audited record")
        for r in self.db.query("SELECT * FROM contract_requirement_sets ORDER BY set_at, id"):
            if hash_json(loads(r["requirements_json"])) != r["requirements_hash"] or not audited("contract.requirements_set", "commitment", r["commitment_id"], "set_id", r["id"]):
                problems.append(f"requirement set {r['id']} (commitment {r['commitment_id']} version {r['version']}) does not match its audited record")
        policy = self.policy()
        if policy is None and self.db.one("SELECT 1 AS x FROM audit_log WHERE action='contract.agreements_required' LIMIT 1"):
            problems.append("the audit log records that agreements are required, but the workspace policy record is missing")
        if policy is not None:
            ap = self._approval(policy["approval_id"])
            if ap is None or ap["status"] != "consumed" or ap["operation"] != OP_REQUIRE:
                problems.append(f"the workspace policy does not rest on a consumed {OP_REQUIRE} approval")
        for chk in self.db.query("SELECT * FROM contract_coverage_checks ORDER BY checked_at, id"):
            expected = hash_json({"approval_id": chk["approval_id"], "operation": chk["operation"], "subject_id": chk["subject_id"],
                                  "checked_on": chk["checked_on"], "coverage": loads(chk["coverage_json"])})
            if expected != chk["coverage_hash"] or not audited("contract.coverage_verified", "approval", chk["approval_id"], "coverage_hash", chk["coverage_hash"]):
                problems.append(f"coverage check {chk['id']} (approval {chk['approval_id']}) does not match its audited record")
        # governed postings and payments on commitments with requirements rest on a coverage check
        with_requirements = {r["commitment_id"] for r in self.db.query(
            """SELECT s.commitment_id FROM contract_requirement_sets s
               WHERE s.version = (SELECT MAX(version) FROM contract_requirement_sets t WHERE t.commitment_id = s.commitment_id) AND s.requirement_count > 0""")}
        if with_requirements:
            checked = {r["approval_id"] for r in self.db.query("SELECT approval_id FROM contract_coverage_checks")}
            for b in self.db.query("""SELECT b.id, b.commitment_id, b.approval_id FROM bills b JOIN approvals a ON a.id = b.approval_id
                                      WHERE a.operation = 'bill.approve' AND b.status NOT IN ('draft','void') ORDER BY b.created_at, b.id"""):
                if b["commitment_id"] in with_requirements and b["approval_id"] not in checked:
                    problems.append(f"bill {b['id']} was posted under approval {b['approval_id']} without a recorded coverage check")
            for p in self.db.query("""SELECT i.id, i.bill_id, i.approval_id, a.operation, a.subject_id FROM payment_intents i JOIN approvals a ON a.id = i.approval_id
                                      WHERE a.operation IN ('payment.release','payment.release_retainage') ORDER BY i.created_at, i.id"""):
                scope = self._coverage_scope(p["operation"], p["subject_id"])
                if any(cid in with_requirements for cid in scope) and p["approval_id"] not in checked:
                    problems.append(f"payment {p['id']} was released under approval {p['approval_id']} without a recorded coverage check")
        return problems

    # ---- close checks, state and export ------------------------------------------------------ #

    def close_checks(self, period_id: str) -> list[dict[str, Any]]:
        """Contract findings for the close checklist and Ricky's brief (see the module
        docstring).  With nothing configured every check passes with a constant detail."""
        unsigned = self.unsigned_billed_commitments()
        findings = self.coverage_findings()
        integrity = self.integrity_problems()
        exp, lap = findings["expiring"], findings["lapsed"]
        cov_detail_parts = []
        if exp:
            cov_detail_parts.append(f"{len(exp)} certificate(s) expire within {EXPIRY_WARNING_DAYS} days with no renewal recorded: "
                                    + ", ".join(f"{e['kind']} {e['policy_number']} of {e['party_id']} (expires {e['expiry_date']})" for e in exp))
        if lap:
            cov_detail_parts.append(f"{len(lap)} required coverage(s) not in force on executed commitments: "
                                    + ", ".join(f"{x['kind']} on {x['commitment_id']} ({'; '.join(x['reasons'])})" for x in lap))
        checks = [
            ("contract signed agreements on billed commitments", not unsigned,
             (f"{len(unsigned)} billed commitment(s) need a signed agreement and have none: "
              + ", ".join(f"{u['title']} ({u['commitment_id']})" for u in unsigned)) if unsigned
             else "every billed commitment that needs a signed agreement has one"),
            (f"contract insurance certificates expiring within {EXPIRY_WARNING_DAYS} days", not exp and not lap,
             " | ".join(cov_detail_parts) if cov_detail_parts else
             f"no certificate on a supplier with open commitments expires within {EXPIRY_WARNING_DAYS} days without a renewal, and required coverage is in force"),
            ("contract records intact", not integrity, "; ".join(integrity) if integrity else
             "every agreement, signature, certificate and requirement set matches its audited record"),
        ]
        return [{"check": name, "name": name, "ok": ok, "detail": detail} for name, ok, detail in checks]

    def state(self, project_id: str) -> dict[str, Any]:
        """Agreements, requirements, coverage and certificates of the project, with findings."""
        if self.db.one("SELECT id FROM projects WHERE id=?", (project_id,)) is None:
            return {"agreements_required": self.agreements_required(), "agreements": [], "commitments": [], "certificates": [],
                    "expiring": [], "lapsed": [], "unsigned_billed_commitments": [], "integrity_problems": [], "summary": {}}
        policy = self.policy()
        policy_seq = self._policy_seq()
        commitments = []
        suppliers = set()
        for c in self.db.query("SELECT * FROM commitments WHERE project_id=? ORDER BY created_at, id", (project_id,)):
            suppliers.add(c["supplier_id"])
            live = self._live_agreement(c["id"])
            commitments.append({
                "commitment_id": c["id"], "title": c["title"], "status": c["status"],
                "agreement_required": self._agreement_required_for(c, policy_seq),
                "agreement": self.agreement(live["id"]) if live else None,
                "requirements": self.requirements(c["id"]),
                "coverage": self.coverage(c["id"]),
            })
        certificates = [x for p in sorted(suppliers) for x in self.certificates(p)]
        findings = self.coverage_findings(project_id)
        unsigned = self.unsigned_billed_commitments(project_id)
        integrity = self.integrity_problems()
        agreements = self.agreements(project_id)
        return {
            "agreements_required": policy is not None, "policy": policy,
            "agreements": agreements, "commitments": commitments, "certificates": certificates,
            "expiring": findings["expiring"], "lapsed": findings["lapsed"], "unsigned_billed_commitments": unsigned,
            "integrity_problems": integrity,
            "summary": {
                "agreements": len(agreements),
                "registered": sum(1 for a in agreements if a["status"] == "registered"),
                "approved": sum(1 for a in agreements if a["status"] == "approved"),
                "signed": sum(1 for a in agreements if a["status"] == "signed"),
                "superseded": sum(1 for a in agreements if a["status"] == "superseded"),
                "certificates": len(certificates),
                "certificates_in_force": sum(1 for x in certificates if x["in_force"]),
                "expiring": len(findings["expiring"]), "lapsed": len(findings["lapsed"]),
                "unsigned_billed_commitments": len(unsigned), "integrity_problems": len(integrity),
            },
        }

    def audit_export(self) -> dict[str, Any]:
        return {
            "workspace_policy": self.db.query("SELECT * FROM contract_workspace_policy"),
            "requirement_sets": self.db.query("SELECT * FROM contract_requirement_sets ORDER BY commitment_id, version"),
            "agreements": self.db.query("SELECT * FROM contract_agreements ORDER BY registered_at, id"),
            "signatures": self.db.query("SELECT * FROM contract_signatures ORDER BY prepared_at, id"),
            "certificates": self.db.query("SELECT * FROM contract_certificates ORDER BY recorded_at, id"),
            "coverage_checks": self.db.query("SELECT * FROM contract_coverage_checks ORDER BY checked_at, id"),
            "integrity_problems": self.integrity_problems(),
        }

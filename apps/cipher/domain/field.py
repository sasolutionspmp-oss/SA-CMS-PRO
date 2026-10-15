"""EPC field controls: RFIs, submittals, hold points, punch list and closeout.

Field records carry no money of their own and never post a journal.  They
feed the commercial core through its existing authority paths:

* **RFI** ``RFI-001``... per project.  An RFI cites exact evidence: drawing
  revisions must be the *issued* revision in the drawing register (recorded
  there as an exact, append-only reference with ``referenced_by_type`` "rfi")
  and document revisions must be core evidence revisions of the same project.
  Citations are fixed at creation and folded into the RFI content hash.
  ``draft_response`` records a proposed response (text, optional cost impact
  >= 0, optional schedule impact in whole days >= 0) and bumps the RFI
  version.  The official response is issued only by the approval-bound
  ``field.respond_rfi`` operation.  Distributing the answered RFI is its own
  authority: ``set_distribution_list`` records who receives it (bumping the RFI
  version) and the approval-bound ``field.distribute_rfi`` operation, whose
  manifest binds the RFI version, the response hash and the recipients hash,
  writes the mail-sink row (nothing is sent).  The same response never goes to
  the same recipient set twice; the old direct ``distribute_rfi`` refuses and
  points to the approval.  ``link_change`` turns an answered RFI's positive
  cost impact into one PENDING core change on an executed commitment of the
  same project; executing that change remains the core ``change.execute``
  approval.
* **Submittal** ``SUB-001``... per project with numbered revisions, each bound
  to a core evidence revision and its content hash.  Only one revision is
  under review at a time.  ``set_decision`` records the reviewer's proposed
  decision and comments and bumps the revision version; the approval-bound
  ``field.decide_submittal`` operation makes it official.  approved and
  approved_as_noted approve the submittal; revise_resubmit requires a new
  revision; rejected is final (a new submittal is required).  A submittal
  decision never posts a journal and never authorizes scope or payment.
* **Hold point**: field work held on a submittal; released only once that
  submittal is approved, recording the approving revision.
* **Punch list** ``PUNCH-001``... per project, against an executed commitment;
  closing an item requires an evidence hash.
* **Closeout** per commitment: a required item list (bumps the closeout
  version), item evidence submissions (also bump it) and the approval-bound
  ``field.accept_closeout`` operation, which needs every required item
  submitted, zero open punch items and no pending (unexecuted, unrejected)
  core change on the commitment, is recorded against an open period and
  closes the commitment through the core, which in turn lets the core Ricky
  ``retainage.release`` workflow propose a release.  ``closeout_accepted`` is
  what ``Cipher.close_commitment`` asks before it lets a commitment count as
  closed from an interactive surface.  The pending-change rule
  is stricter than the bare spec on purpose: a commitment closed with a
  pending change (for example one raised by ``link_change``) could still grow
  through ``change.execute`` after retainage is released.  ``link_change``
  invalidates open acceptance approvals of the commitment, and the manifest
  binds the pending changes so a core-proposed change also makes a granted
  acceptance stale.

Approval binding: every manifest binds the subject's record version and the
content hashes, amounts and counterparties whose change must invalidate the
approval.  Record methods bump a version and proactively invalidate open
approvals on the subject they change.  ``manifest_for`` builds a manifest only
for a subject the operation can run on; otherwise it raises
``FieldStateError`` (a ``FieldError`` and a ``StaleApprovalError``).  A
proposal (``request_approval``, Ricky) is therefore refused whatever the
caller's transaction state, and during consumption the core rolls the command
back and invalidates the approval durably.  ``apply`` re-checks the same
conditions under the write lock and raises the same error.

Database guards back the rules without the plugin: identity, binding and
lifecycle columns are immutable or written once on their own transition;
status machines admit only the documented transitions; an RFI is answered or
distributed, a submittal revision decided and a closeout accepted only against
a consumed approval of the matching operation for that subject (a distribution
also only to the recipients, response and RFI version that approval bound, and
once per approval); an answered RFI changes only by a new distribution list
with a version bump; hold point release needs
an approved submittal; closeout acceptance needs zero open punch items, every
required item submitted, no pending change on the commitment and an open
period; a closeout requirement row is written only at the closeout's current
version and every later write to it must ride on a closeout version bump (so
an existing approval, which binds that version, goes stale); nothing is ever
deleted.  Raw SQL cannot be forced to write an audit entry; the guards keep it
from changing what an approval saw without that showing up as a version change.
"""
from __future__ import annotations

from contextlib import contextmanager
import json
from decimal import Decimal
from typing import Any

from ..core.approvals import StaleApprovalError, build_manifest
from ..core.db import register_schema_version
from ..core.ids import hash_json, new_id, sha256_hex, utcnow_iso
from ..core.money import ZERO, D, MoneyError, fmt, money, total
from .commitments import CommitmentError
from .evidence import EvidenceError

SCHEMA_NAME = "field"
PLUGIN_NAME = "field"

OP_RESPOND_RFI = "field.respond_rfi"
OP_DECIDE_SUBMITTAL = "field.decide_submittal"
OP_ACCEPT_CLOSEOUT = "field.accept_closeout"
OP_DISTRIBUTE_RFI = "field.distribute_rfi"
OPERATIONS = (OP_RESPOND_RFI, OP_DECIDE_SUBMITTAL, OP_ACCEPT_CLOSEOUT, OP_DISTRIBUTE_RFI)

RFI_SUBJECT = "field_rfi"
SUBMITTAL_SUBJECT = "field_submittal"
REVISION_SUBJECT = "field_submittal_revision"
HOLD_POINT_SUBJECT = "field_hold_point"
PUNCH_SUBJECT = "field_punch_item"
CLOSEOUT_SUBJECT = "field_closeout"

DECISIONS = ("approved", "approved_as_noted", "revise_resubmit", "rejected")
SUBMITTAL_STATUS_FOR_DECISION = {
    "approved": "approved",
    "approved_as_noted": "approved",
    "revise_resubmit": "revise_resubmit",
    "rejected": "rejected",
}
CLOSEOUT_ITEMS = ("as_builts", "om_manuals", "warranties", "final_lien_release", "training", "attic_stock")
MAIL_SINK = "mail-sink"

SCHEMA_STATEMENTS = [
    # ---- RFIs ------------------------------------------------------------------------------ #
    """CREATE TABLE field_rfis (
        id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES projects(id),
        sequence INTEGER NOT NULL,
        number TEXT NOT NULL,
        subject TEXT NOT NULL,
        question TEXT NOT NULL,
        status TEXT NOT NULL CHECK (status IN ('open','answered')),
        version INTEGER NOT NULL DEFAULT 1,
        content_hash TEXT NOT NULL,
        draft_response TEXT,
        draft_cost_impact TEXT,
        draft_schedule_impact_days INTEGER CHECK (draft_schedule_impact_days IS NULL OR draft_schedule_impact_days >= 0),
        draft_response_hash TEXT,
        response TEXT,
        cost_impact TEXT,
        schedule_impact_days INTEGER CHECK (schedule_impact_days IS NULL OR schedule_impact_days >= 0),
        response_hash TEXT,
        approval_id TEXT REFERENCES approvals(id),
        created_by TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        answered_by TEXT,
        answered_at TEXT,
        UNIQUE (project_id, sequence),
        UNIQUE (project_id, number)
    )""",
    """CREATE TRIGGER field_rfis_born_open BEFORE INSERT ON field_rfis
        WHEN NEW.status != 'open' OR NEW.version != 1 OR NEW.response IS NOT NULL OR NEW.response_hash IS NOT NULL OR NEW.approval_id IS NOT NULL OR NEW.answered_at IS NOT NULL
        BEGIN SELECT RAISE(ABORT, 'an RFI is created open at version 1; it is answered only through field.respond_rfi'); END""",
    "CREATE TRIGGER field_rfis_no_delete BEFORE DELETE ON field_rfis BEGIN SELECT RAISE(ABORT, 'RFIs are never deleted'); END",
    """CREATE TRIGGER field_rfis_identity_immutable BEFORE UPDATE OF id, project_id, sequence, number, subject, question, content_hash, created_by, created_at ON field_rfis
        BEGIN SELECT RAISE(ABORT, 'RFI identity, question and cited evidence are immutable'); END""",
    """CREATE TRIGGER field_rfis_answered_immutable BEFORE UPDATE ON field_rfis WHEN OLD.status = 'answered'
        BEGIN SELECT RAISE(ABORT, 'an answered RFI is immutable; distribute it or link a change instead'); END""",
    """CREATE TRIGGER field_rfis_version_bumps BEFORE UPDATE ON field_rfis WHEN NEW.version <= OLD.version
        BEGIN SELECT RAISE(ABORT, 'every RFI change must bump the RFI version'); END""",
    """CREATE TRIGGER field_rfis_response_fields_once BEFORE UPDATE OF response, cost_impact, schedule_impact_days, response_hash, approval_id, answered_by, answered_at ON field_rfis
        WHEN NOT (OLD.status = 'open' AND NEW.status = 'answered')
        BEGIN SELECT RAISE(ABORT, 'the official RFI response is written once, when the RFI is answered'); END""",
    """CREATE TRIGGER field_rfis_answer_authorised BEFORE UPDATE OF status ON field_rfis
        WHEN NEW.status != OLD.status
        BEGIN
            SELECT CASE
                WHEN NOT (OLD.status = 'open' AND NEW.status = 'answered')
                THEN RAISE(ABORT, 'illegal RFI status transition')
                WHEN NEW.response IS NULL OR NEW.response_hash IS NULL OR NEW.answered_at IS NULL OR NEW.response_hash IS NOT OLD.draft_response_hash
                THEN RAISE(ABORT, 'an RFI is answered with exactly its drafted response')
                WHEN (SELECT status FROM approvals WHERE id = NEW.approval_id AND operation = 'field.respond_rfi' AND subject_type = 'field_rfi' AND subject_id = NEW.id) IS NOT 'consumed'
                THEN RAISE(ABORT, 'an RFI is answered only against a consumed field.respond_rfi approval for that RFI')
            END;
        END""",
    """CREATE TABLE field_rfi_links (
        id TEXT PRIMARY KEY,
        rfi_id TEXT NOT NULL REFERENCES field_rfis(id),
        link_type TEXT NOT NULL CHECK (link_type IN ('drawing_revision','document_revision','change')),
        target_id TEXT NOT NULL,
        target_hash TEXT NOT NULL,
        reference_id TEXT,
        created_by TEXT NOT NULL,
        created_at TEXT NOT NULL,
        UNIQUE (rfi_id, link_type, target_id)
    )""",
    "CREATE UNIQUE INDEX field_rfi_links_one_change_per_rfi ON field_rfi_links (rfi_id) WHERE link_type = 'change'",
    "CREATE UNIQUE INDEX field_rfi_links_change_once ON field_rfi_links (target_id) WHERE link_type = 'change'",
    """CREATE TRIGGER field_rfi_links_guard BEFORE INSERT ON field_rfi_links
        BEGIN
            SELECT CASE
                WHEN NEW.link_type != 'change' AND (SELECT version FROM field_rfis WHERE id = NEW.rfi_id) IS NOT 1
                THEN RAISE(ABORT, 'drawing and document citations are fixed when the RFI is created')
                WHEN NEW.link_type = 'document_revision' AND (SELECT content_hash FROM document_revisions WHERE id = NEW.target_id) IS NOT NEW.target_hash
                THEN RAISE(ABORT, 'an RFI document citation carries the exact content hash of the evidence revision')
                WHEN NEW.link_type = 'document_revision'
                     AND (SELECT d.project_id FROM document_revisions r JOIN documents d ON d.id = r.document_id WHERE r.id = NEW.target_id)
                     IS NOT (SELECT project_id FROM field_rfis WHERE id = NEW.rfi_id)
                THEN RAISE(ABORT, 'an RFI cites evidence of its own project only')
                WHEN NEW.link_type = 'change' AND (SELECT status FROM field_rfis WHERE id = NEW.rfi_id) IS NOT 'answered'
                THEN RAISE(ABORT, 'a change is linked only to an answered RFI')
                WHEN NEW.link_type = 'change'
                     AND (SELECT c.project_id FROM changes ch JOIN commitments c ON c.id = ch.commitment_id WHERE ch.id = NEW.target_id)
                     IS NOT (SELECT project_id FROM field_rfis WHERE id = NEW.rfi_id)
                THEN RAISE(ABORT, 'an RFI change belongs to a commitment of the same project')
            END;
        END""",
    "CREATE TRIGGER field_rfi_links_no_update BEFORE UPDATE ON field_rfi_links BEGIN SELECT RAISE(ABORT, 'RFI links are append-only'); END",
    "CREATE TRIGGER field_rfi_links_no_delete BEFORE DELETE ON field_rfi_links BEGIN SELECT RAISE(ABORT, 'RFI links are append-only'); END",
    """CREATE TABLE field_rfi_distributions (
        id TEXT PRIMARY KEY,
        rfi_id TEXT NOT NULL REFERENCES field_rfis(id),
        rfi_version INTEGER NOT NULL,
        response_hash TEXT NOT NULL,
        recipients_json TEXT NOT NULL,
        recipients_hash TEXT NOT NULL,
        channel TEXT NOT NULL CHECK (channel = 'mail-sink'),
        distributed_by TEXT NOT NULL,
        distributed_at TEXT NOT NULL,
        UNIQUE (rfi_id, response_hash, recipients_hash)
    )""",
    """CREATE TRIGGER field_rfi_distributions_answered_only BEFORE INSERT ON field_rfi_distributions
        BEGIN
            SELECT CASE
                WHEN (SELECT status FROM field_rfis WHERE id = NEW.rfi_id) IS NOT 'answered'
                THEN RAISE(ABORT, 'only an answered RFI is distributed')
                WHEN (SELECT response_hash FROM field_rfis WHERE id = NEW.rfi_id) IS NOT NEW.response_hash
                     OR (SELECT version FROM field_rfis WHERE id = NEW.rfi_id) IS NOT NEW.rfi_version
                THEN RAISE(ABORT, 'a distribution carries the official response of the RFI it distributes')
            END;
        END""",
    "CREATE TRIGGER field_rfi_distributions_no_update BEFORE UPDATE ON field_rfi_distributions BEGIN SELECT RAISE(ABORT, 'RFI distributions are append-only'); END",
    "CREATE TRIGGER field_rfi_distributions_no_delete BEFORE DELETE ON field_rfi_distributions BEGIN SELECT RAISE(ABORT, 'RFI distributions are append-only'); END",
    # ---- submittals ------------------------------------------------------------------------- #
    """CREATE TABLE field_submittals (
        id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES projects(id),
        sequence INTEGER NOT NULL,
        number TEXT NOT NULL,
        spec_section TEXT NOT NULL,
        title TEXT NOT NULL,
        equipment_tag TEXT,
        status TEXT NOT NULL CHECK (status IN ('open','under_review','approved','revise_resubmit','rejected')),
        version INTEGER NOT NULL DEFAULT 1,
        created_by TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE (project_id, sequence),
        UNIQUE (project_id, number)
    )""",
    """CREATE TRIGGER field_submittals_born_open BEFORE INSERT ON field_submittals WHEN NEW.status != 'open' OR NEW.version != 1
        BEGIN SELECT RAISE(ABORT, 'a submittal is created open at version 1'); END""",
    "CREATE TRIGGER field_submittals_no_delete BEFORE DELETE ON field_submittals BEGIN SELECT RAISE(ABORT, 'submittals are never deleted'); END",
    """CREATE TRIGGER field_submittals_identity_immutable BEFORE UPDATE OF id, project_id, sequence, number, spec_section, title, equipment_tag, created_by, created_at ON field_submittals
        BEGIN SELECT RAISE(ABORT, 'submittal identity is immutable'); END""",
    """CREATE TRIGGER field_submittals_final_immutable BEFORE UPDATE ON field_submittals WHEN OLD.status IN ('approved','rejected')
        BEGIN SELECT RAISE(ABORT, 'an approved or rejected submittal is final'); END""",
    """CREATE TRIGGER field_submittals_version_bumps BEFORE UPDATE ON field_submittals WHEN NEW.version <= OLD.version
        BEGIN SELECT RAISE(ABORT, 'every submittal change must bump the submittal version'); END""",
    """CREATE TRIGGER field_submittals_status_machine BEFORE UPDATE OF status ON field_submittals
        WHEN NEW.status != OLD.status
        BEGIN
            SELECT CASE
                WHEN NOT ((OLD.status IN ('open','revise_resubmit') AND NEW.status = 'under_review')
                          OR (OLD.status = 'under_review' AND NEW.status IN ('approved','revise_resubmit','rejected')))
                THEN RAISE(ABORT, 'illegal submittal status transition')
                WHEN NEW.status = 'under_review' AND NOT EXISTS (SELECT 1 FROM field_submittal_revisions WHERE submittal_id = NEW.id AND status = 'under_review')
                THEN RAISE(ABORT, 'a submittal is under review only while one of its revisions is')
                WHEN OLD.status = 'under_review' AND EXISTS (SELECT 1 FROM field_submittal_revisions WHERE submittal_id = NEW.id AND status = 'under_review')
                THEN RAISE(ABORT, 'a submittal leaves review only once its revision is decided')
                WHEN NEW.status = 'approved'
                     AND COALESCE((SELECT status FROM field_submittal_revisions WHERE submittal_id = NEW.id ORDER BY revision DESC LIMIT 1), '') NOT IN ('approved','approved_as_noted')
                THEN RAISE(ABORT, 'a submittal is approved only by an approved revision')
                WHEN NEW.status IN ('revise_resubmit','rejected')
                     AND (SELECT status FROM field_submittal_revisions WHERE submittal_id = NEW.id ORDER BY revision DESC LIMIT 1) IS NOT NEW.status
                THEN RAISE(ABORT, 'a submittal status follows the decision on its latest revision')
            END;
        END""",
    """CREATE TABLE field_submittal_revisions (
        id TEXT PRIMARY KEY,
        submittal_id TEXT NOT NULL REFERENCES field_submittals(id),
        revision INTEGER NOT NULL,
        document_revision_id TEXT NOT NULL REFERENCES document_revisions(id),
        document_hash TEXT NOT NULL,
        status TEXT NOT NULL CHECK (status IN ('under_review','approved','approved_as_noted','revise_resubmit','rejected')),
        version INTEGER NOT NULL DEFAULT 1,
        draft_decision TEXT CHECK (draft_decision IS NULL OR draft_decision IN ('approved','approved_as_noted','revise_resubmit','rejected')),
        draft_comments TEXT,
        draft_comments_hash TEXT,
        decision TEXT,
        comments TEXT,
        comments_hash TEXT,
        approval_id TEXT REFERENCES approvals(id),
        created_by TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        decided_by TEXT,
        decided_at TEXT,
        UNIQUE (submittal_id, revision),
        UNIQUE (submittal_id, document_revision_id)
    )""",
    "CREATE UNIQUE INDEX field_submittal_revisions_one_under_review ON field_submittal_revisions (submittal_id) WHERE status = 'under_review'",
    """CREATE TRIGGER field_submittal_revisions_born_under_review BEFORE INSERT ON field_submittal_revisions
        BEGIN
            SELECT CASE
                WHEN NEW.status != 'under_review' OR NEW.version != 1 OR NEW.decision IS NOT NULL OR NEW.approval_id IS NOT NULL OR NEW.decided_at IS NOT NULL
                THEN RAISE(ABORT, 'a submittal revision is created under review; it is decided only through field.decide_submittal')
                WHEN (SELECT content_hash FROM document_revisions WHERE id = NEW.document_revision_id) IS NOT NEW.document_hash
                THEN RAISE(ABORT, 'a submittal revision carries the exact content hash of its evidence revision')
                WHEN (SELECT d.project_id FROM document_revisions r JOIN documents d ON d.id = r.document_id WHERE r.id = NEW.document_revision_id)
                     IS NOT (SELECT project_id FROM field_submittals WHERE id = NEW.submittal_id)
                THEN RAISE(ABORT, 'a submittal revision binds evidence of its own project only')
                WHEN COALESCE((SELECT status FROM field_submittals WHERE id = NEW.submittal_id), '') NOT IN ('open','revise_resubmit')
                THEN RAISE(ABORT, 'a new submittal revision is accepted only for an open or revise-and-resubmit submittal')
            END;
        END""",
    "CREATE TRIGGER field_submittal_revisions_no_delete BEFORE DELETE ON field_submittal_revisions BEGIN SELECT RAISE(ABORT, 'submittal revisions are never deleted'); END",
    """CREATE TRIGGER field_submittal_revisions_binding_immutable BEFORE UPDATE OF id, submittal_id, revision, document_revision_id, document_hash, created_by, created_at ON field_submittal_revisions
        BEGIN SELECT RAISE(ABORT, 'a submittal revision binding is immutable; add a new revision instead'); END""",
    """CREATE TRIGGER field_submittal_revisions_decided_immutable BEFORE UPDATE ON field_submittal_revisions WHEN OLD.status != 'under_review'
        BEGIN SELECT RAISE(ABORT, 'a decided submittal revision is final'); END""",
    """CREATE TRIGGER field_submittal_revisions_version_bumps BEFORE UPDATE ON field_submittal_revisions WHEN NEW.version <= OLD.version
        BEGIN SELECT RAISE(ABORT, 'every submittal revision change must bump its version'); END""",
    """CREATE TRIGGER field_submittal_revisions_decision_fields_once BEFORE UPDATE OF decision, comments, comments_hash, approval_id, decided_by, decided_at ON field_submittal_revisions
        WHEN NOT (OLD.status = 'under_review' AND NEW.status != 'under_review')
        BEGIN SELECT RAISE(ABORT, 'the official submittal decision is written once, when the revision is decided'); END""",
    """CREATE TRIGGER field_submittal_revisions_decision_authorised BEFORE UPDATE OF status ON field_submittal_revisions
        WHEN NEW.status != OLD.status
        BEGIN
            SELECT CASE
                WHEN NEW.decision IS NOT NEW.status OR NEW.decision IS NOT OLD.draft_decision OR NEW.comments_hash IS NOT OLD.draft_comments_hash OR NEW.decided_at IS NULL
                THEN RAISE(ABORT, 'a submittal revision is decided with exactly its recorded decision and comments')
                WHEN (SELECT status FROM approvals WHERE id = NEW.approval_id AND operation = 'field.decide_submittal' AND subject_type = 'field_submittal_revision' AND subject_id = NEW.id) IS NOT 'consumed'
                THEN RAISE(ABORT, 'a submittal revision is decided only against a consumed field.decide_submittal approval for that revision')
            END;
        END""",
    # ---- hold points ------------------------------------------------------------------------ #
    """CREATE TABLE field_hold_points (
        id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES projects(id),
        submittal_id TEXT NOT NULL REFERENCES field_submittals(id),
        description TEXT NOT NULL,
        status TEXT NOT NULL CHECK (status IN ('held','released')),
        version INTEGER NOT NULL DEFAULT 1,
        released_revision_id TEXT REFERENCES field_submittal_revisions(id),
        created_by TEXT NOT NULL,
        created_at TEXT NOT NULL,
        released_by TEXT,
        released_at TEXT
    )""",
    """CREATE TRIGGER field_hold_points_born_held BEFORE INSERT ON field_hold_points
        BEGIN
            SELECT CASE
                WHEN NEW.status != 'held' OR NEW.version != 1 OR NEW.released_revision_id IS NOT NULL OR NEW.released_at IS NOT NULL
                THEN RAISE(ABORT, 'a hold point is created held')
                WHEN (SELECT project_id FROM field_submittals WHERE id = NEW.submittal_id) IS NOT NEW.project_id
                THEN RAISE(ABORT, 'a hold point waits on a submittal of its own project')
            END;
        END""",
    "CREATE TRIGGER field_hold_points_no_delete BEFORE DELETE ON field_hold_points BEGIN SELECT RAISE(ABORT, 'hold points are never deleted'); END",
    """CREATE TRIGGER field_hold_points_identity_immutable BEFORE UPDATE OF id, project_id, submittal_id, description, created_by, created_at ON field_hold_points
        BEGIN SELECT RAISE(ABORT, 'hold point identity is immutable'); END""",
    """CREATE TRIGGER field_hold_points_released_immutable BEFORE UPDATE ON field_hold_points WHEN OLD.status = 'released'
        BEGIN SELECT RAISE(ABORT, 'a released hold point is final'); END""",
    """CREATE TRIGGER field_hold_points_version_bumps BEFORE UPDATE ON field_hold_points WHEN NEW.version <= OLD.version
        BEGIN SELECT RAISE(ABORT, 'every hold point change must bump its version'); END""",
    """CREATE TRIGGER field_hold_points_release_guard BEFORE UPDATE ON field_hold_points
        WHEN NEW.status = 'released'
        BEGIN
            SELECT CASE
                WHEN (SELECT status FROM field_submittals WHERE id = OLD.submittal_id) IS NOT 'approved'
                THEN RAISE(ABORT, 'a hold point is released only once its submittal is approved')
                WHEN NEW.released_at IS NULL OR NEW.released_by IS NULL
                     OR COALESCE((SELECT status FROM field_submittal_revisions WHERE id = NEW.released_revision_id AND submittal_id = OLD.submittal_id), '') NOT IN ('approved','approved_as_noted')
                THEN RAISE(ABORT, 'a hold point release records the approved submittal revision that released it')
            END;
        END""",
    # ---- punch list ------------------------------------------------------------------------- #
    """CREATE TABLE field_punch_items (
        id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES projects(id),
        commitment_id TEXT NOT NULL REFERENCES commitments(id),
        sequence INTEGER NOT NULL,
        number TEXT NOT NULL,
        description TEXT NOT NULL,
        status TEXT NOT NULL CHECK (status IN ('open','closed')),
        version INTEGER NOT NULL DEFAULT 1,
        evidence_hash TEXT,
        created_by TEXT NOT NULL,
        created_at TEXT NOT NULL,
        closed_by TEXT,
        closed_at TEXT,
        UNIQUE (project_id, sequence),
        UNIQUE (project_id, number)
    )""",
    """CREATE TRIGGER field_punch_items_born_open BEFORE INSERT ON field_punch_items
        BEGIN
            SELECT CASE
                WHEN NEW.status != 'open' OR NEW.version != 1 OR NEW.evidence_hash IS NOT NULL OR NEW.closed_at IS NOT NULL
                THEN RAISE(ABORT, 'a punch item is created open')
                WHEN (SELECT project_id FROM commitments WHERE id = NEW.commitment_id) IS NOT NEW.project_id
                THEN RAISE(ABORT, 'a punch item belongs to a commitment of its own project')
            END;
        END""",
    "CREATE TRIGGER field_punch_items_no_delete BEFORE DELETE ON field_punch_items BEGIN SELECT RAISE(ABORT, 'punch items are never deleted'); END",
    """CREATE TRIGGER field_punch_items_identity_immutable BEFORE UPDATE OF id, project_id, commitment_id, sequence, number, description, created_by, created_at ON field_punch_items
        BEGIN SELECT RAISE(ABORT, 'punch item identity is immutable'); END""",
    """CREATE TRIGGER field_punch_items_closed_immutable BEFORE UPDATE ON field_punch_items WHEN OLD.status = 'closed'
        BEGIN SELECT RAISE(ABORT, 'a closed punch item is final'); END""",
    """CREATE TRIGGER field_punch_items_version_bumps BEFORE UPDATE ON field_punch_items WHEN NEW.version <= OLD.version
        BEGIN SELECT RAISE(ABORT, 'every punch item change must bump its version'); END""",
    """CREATE TRIGGER field_punch_items_close_needs_evidence BEFORE UPDATE ON field_punch_items
        WHEN NEW.status = 'closed' AND (NEW.evidence_hash IS NULL OR length(trim(NEW.evidence_hash)) = 0 OR NEW.closed_at IS NULL OR NEW.closed_by IS NULL)
        BEGIN SELECT RAISE(ABORT, 'a punch item is closed only with completion evidence'); END""",
    # ---- closeout --------------------------------------------------------------------------- #
    """CREATE TABLE field_closeouts (
        id TEXT PRIMARY KEY,
        commitment_id TEXT NOT NULL UNIQUE REFERENCES commitments(id),
        project_id TEXT NOT NULL REFERENCES projects(id),
        status TEXT NOT NULL CHECK (status IN ('open','accepted')),
        version INTEGER NOT NULL DEFAULT 1,
        approval_id TEXT REFERENCES approvals(id),
        accepted_period_id TEXT REFERENCES periods(id),
        acceptance_hash TEXT,
        created_by TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        accepted_by TEXT,
        accepted_at TEXT
    )""",
    """CREATE TRIGGER field_closeouts_born_open BEFORE INSERT ON field_closeouts
        BEGIN
            SELECT CASE
                WHEN NEW.status != 'open' OR NEW.version != 1 OR NEW.approval_id IS NOT NULL OR NEW.accepted_at IS NOT NULL
                THEN RAISE(ABORT, 'a closeout is created open at version 1')
                WHEN (SELECT project_id FROM commitments WHERE id = NEW.commitment_id) IS NOT NEW.project_id
                THEN RAISE(ABORT, 'a closeout belongs to the project of its commitment')
            END;
        END""",
    "CREATE TRIGGER field_closeouts_no_delete BEFORE DELETE ON field_closeouts BEGIN SELECT RAISE(ABORT, 'closeouts are never deleted'); END",
    """CREATE TRIGGER field_closeouts_identity_immutable BEFORE UPDATE OF id, commitment_id, project_id, created_by, created_at ON field_closeouts
        BEGIN SELECT RAISE(ABORT, 'closeout identity is immutable'); END""",
    """CREATE TRIGGER field_closeouts_accepted_immutable BEFORE UPDATE ON field_closeouts WHEN OLD.status = 'accepted'
        BEGIN SELECT RAISE(ABORT, 'an accepted closeout is final'); END""",
    """CREATE TRIGGER field_closeouts_version_bumps BEFORE UPDATE ON field_closeouts WHEN NEW.version <= OLD.version
        BEGIN SELECT RAISE(ABORT, 'every closeout change must bump the closeout version'); END""",
    """CREATE TRIGGER field_closeouts_acceptance_guard BEFORE UPDATE ON field_closeouts
        WHEN NEW.status = 'accepted'
        BEGIN
            SELECT CASE
                WHEN NEW.accepted_at IS NULL OR NEW.accepted_by IS NULL OR NEW.acceptance_hash IS NULL
                THEN RAISE(ABORT, 'a closeout acceptance records who accepted it, when, and what was accepted')
                WHEN (SELECT status FROM periods WHERE id = NEW.accepted_period_id) IS NOT 'open'
                THEN RAISE(ABORT, 'a closeout is accepted into an open period only')
                WHEN (SELECT COUNT(*) FROM field_punch_items WHERE commitment_id = NEW.commitment_id AND status = 'open') > 0
                THEN RAISE(ABORT, 'a closeout is accepted only with zero open punch items')
                WHEN (SELECT COUNT(*) FROM field_closeout_requirements WHERE closeout_id = NEW.id AND required = 1) = 0
                     OR (SELECT COUNT(*) FROM field_closeout_requirements WHERE closeout_id = NEW.id AND required = 1 AND status != 'submitted') > 0
                THEN RAISE(ABORT, 'a closeout is accepted only when every required item is submitted')
                WHEN EXISTS (SELECT 1 FROM changes WHERE commitment_id = NEW.commitment_id AND status IN ('pending','approved'))
                THEN RAISE(ABORT, 'a closeout is accepted only with no pending change on the commitment')
                WHEN (SELECT status FROM approvals WHERE id = NEW.approval_id AND operation = 'field.accept_closeout' AND subject_type = 'field_closeout' AND subject_id = NEW.commitment_id) IS NOT 'consumed'
                THEN RAISE(ABORT, 'a closeout is accepted only against a consumed field.accept_closeout approval for that commitment')
            END;
        END""",
    """CREATE TABLE field_closeout_requirements (
        id TEXT PRIMARY KEY,
        closeout_id TEXT NOT NULL REFERENCES field_closeouts(id),
        commitment_id TEXT NOT NULL REFERENCES commitments(id),
        item TEXT NOT NULL CHECK (item IN ('as_builts','om_manuals','warranties','final_lien_release','training','attic_stock')),
        required INTEGER NOT NULL CHECK (required IN (0, 1)),
        status TEXT NOT NULL CHECK (status IN ('pending','submitted')),
        evidence_hash TEXT,
        submitted_by TEXT,
        submitted_at TEXT,
        closeout_version INTEGER NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        CHECK (status = 'pending' OR (evidence_hash IS NOT NULL AND length(trim(evidence_hash)) > 0 AND submitted_at IS NOT NULL)),
        UNIQUE (commitment_id, item)
    )""",
    "CREATE UNIQUE INDEX field_closeout_requirements_evidence_once ON field_closeout_requirements (commitment_id, evidence_hash) WHERE evidence_hash IS NOT NULL",
    """CREATE TRIGGER field_closeout_requirements_insert_guard BEFORE INSERT ON field_closeout_requirements
        BEGIN
            SELECT CASE
                WHEN (SELECT status FROM field_closeouts WHERE id = NEW.closeout_id) IS NOT 'open'
                THEN RAISE(ABORT, 'closeout requirements change only while the closeout is open')
                WHEN (SELECT commitment_id FROM field_closeouts WHERE id = NEW.closeout_id) IS NOT NEW.commitment_id
                THEN RAISE(ABORT, 'a closeout requirement belongs to the commitment of its closeout')
                WHEN NEW.status != 'pending' OR NEW.evidence_hash IS NOT NULL
                THEN RAISE(ABORT, 'a closeout requirement is created pending')
                WHEN NEW.closeout_version IS NOT (SELECT version FROM field_closeouts WHERE id = NEW.closeout_id)
                THEN RAISE(ABORT, 'a closeout requirement is written at the current closeout version')
            END;
        END""",
    """CREATE TRIGGER field_closeout_requirements_ride_a_version_bump BEFORE UPDATE ON field_closeout_requirements
        WHEN NEW.closeout_version <= OLD.closeout_version
             OR NEW.closeout_version IS NOT (SELECT version FROM field_closeouts WHERE id = NEW.closeout_id)
        BEGIN SELECT RAISE(ABORT, 'every closeout requirement change rides on a closeout version bump'); END""",
    """CREATE TRIGGER field_closeout_requirements_frozen_after_acceptance BEFORE UPDATE ON field_closeout_requirements
        WHEN (SELECT status FROM field_closeouts WHERE id = OLD.closeout_id) IS NOT 'open'
        BEGIN SELECT RAISE(ABORT, 'closeout requirements are frozen once the closeout is accepted'); END""",
    """CREATE TRIGGER field_closeout_requirements_identity_immutable BEFORE UPDATE OF id, closeout_id, commitment_id, item, created_at ON field_closeout_requirements
        BEGIN SELECT RAISE(ABORT, 'closeout requirement identity is immutable'); END""",
    """CREATE TRIGGER field_closeout_requirements_submitted_stays BEFORE UPDATE OF status ON field_closeout_requirements
        WHEN OLD.status = 'submitted' AND NEW.status != 'submitted'
        BEGIN SELECT RAISE(ABORT, 'a submitted closeout item stays submitted; resubmit new evidence instead'); END""",
    "CREATE TRIGGER field_closeout_requirements_no_delete BEFORE DELETE ON field_closeout_requirements BEGIN SELECT RAISE(ABORT, 'closeout requirements are never deleted'); END",
]

# Approval-bound RFI distribution, as its own catalog entry so a workspace that already
# applied ``field`` upgrades in place (applied entries are append-only):
# * an answered RFI carries a distribution list; setting it is the only change an answered
#   RFI still accepts, and it must bump the RFI version (so a granted distribution approval,
#   which binds that version and the list hash, goes stale);
# * a new distribution row needs a consumed ``field.distribute_rfi`` approval for that RFI
#   whose manifest bound exactly this RFI version, response hash and recipients hash, and
#   goes to exactly the RFI's current list; one distribution per approval.
DISTRIBUTION_SCHEMA_NAME = "field_rfi_distribution_approvals"
DISTRIBUTION_SCHEMA_STATEMENTS = [
    "ALTER TABLE field_rfis ADD COLUMN distribution_recipients_json TEXT",
    "ALTER TABLE field_rfis ADD COLUMN distribution_recipients_hash TEXT",
    "ALTER TABLE field_rfi_distributions ADD COLUMN approval_id TEXT REFERENCES approvals(id)",
    "CREATE UNIQUE INDEX field_rfi_distributions_one_per_approval ON field_rfi_distributions (approval_id) WHERE approval_id IS NOT NULL",
    """CREATE TRIGGER field_rfis_born_without_distribution_list BEFORE INSERT ON field_rfis
        WHEN NEW.distribution_recipients_json IS NOT NULL OR NEW.distribution_recipients_hash IS NOT NULL
        BEGIN SELECT RAISE(ABORT, 'an RFI gets a distribution list only once it is answered'); END""",
    """CREATE TRIGGER field_rfis_distribution_list_answered_only BEFORE UPDATE OF distribution_recipients_json, distribution_recipients_hash ON field_rfis
        WHEN OLD.status != 'answered' OR NEW.status != 'answered'
          OR NEW.distribution_recipients_json IS NULL OR NEW.distribution_recipients_hash IS NULL
        BEGIN SELECT RAISE(ABORT, 'a distribution list is set only on an answered RFI, and never cleared'); END""",
    "DROP TRIGGER field_rfis_answered_immutable",
    """CREATE TRIGGER field_rfis_answered_immutable BEFORE UPDATE ON field_rfis
        WHEN OLD.status = 'answered' AND NOT (
            NEW.status = 'answered'
            AND NEW.distribution_recipients_json IS NOT NULL AND NEW.distribution_recipients_hash IS NOT NULL
            AND NEW.distribution_recipients_hash IS NOT OLD.distribution_recipients_hash
            AND NEW.draft_response IS OLD.draft_response AND NEW.draft_cost_impact IS OLD.draft_cost_impact
            AND NEW.draft_schedule_impact_days IS OLD.draft_schedule_impact_days AND NEW.draft_response_hash IS OLD.draft_response_hash
            AND NEW.response IS OLD.response AND NEW.cost_impact IS OLD.cost_impact AND NEW.schedule_impact_days IS OLD.schedule_impact_days
            AND NEW.response_hash IS OLD.response_hash AND NEW.approval_id IS OLD.approval_id
            AND NEW.answered_by IS OLD.answered_by AND NEW.answered_at IS OLD.answered_at
        )
        BEGIN SELECT RAISE(ABORT, 'an answered RFI is immutable except for a new distribution list; distribute it through field.distribute_rfi or link a change instead'); END""",
    "DROP TRIGGER field_rfi_distributions_answered_only",
    """CREATE TRIGGER field_rfi_distributions_answered_only BEFORE INSERT ON field_rfi_distributions
        BEGIN
            SELECT CASE
                WHEN (SELECT status FROM field_rfis WHERE id = NEW.rfi_id) IS NOT 'answered'
                THEN RAISE(ABORT, 'only an answered RFI is distributed')
                WHEN (SELECT response_hash FROM field_rfis WHERE id = NEW.rfi_id) IS NOT NEW.response_hash
                     OR (SELECT version FROM field_rfis WHERE id = NEW.rfi_id) IS NOT NEW.rfi_version
                THEN RAISE(ABORT, 'a distribution carries the official response of the RFI it distributes')
                WHEN (SELECT distribution_recipients_hash FROM field_rfis WHERE id = NEW.rfi_id) IS NOT NEW.recipients_hash
                     OR (SELECT distribution_recipients_json FROM field_rfis WHERE id = NEW.rfi_id) IS NOT NEW.recipients_json
                THEN RAISE(ABORT, 'a distribution goes to exactly the current distribution list of the RFI')
                WHEN (SELECT status FROM approvals WHERE id = NEW.approval_id AND operation = 'field.distribute_rfi' AND subject_type = 'field_rfi' AND subject_id = NEW.rfi_id) IS NOT 'consumed'
                THEN RAISE(ABORT, 'an RFI is distributed only against a consumed field.distribute_rfi approval for that RFI')
                WHEN (SELECT json_extract(manifest_json, '$.bindings.recipients_hash') FROM approvals WHERE id = NEW.approval_id) IS NOT NEW.recipients_hash
                     OR (SELECT json_extract(manifest_json, '$.bindings.response_hash') FROM approvals WHERE id = NEW.approval_id) IS NOT NEW.response_hash
                     OR (SELECT json_extract(manifest_json, '$.bindings.rfi_version') FROM approvals WHERE id = NEW.approval_id) IS NOT NEW.rfi_version
                THEN RAISE(ABORT, 'a distribution matches the RFI version, response and recipients its approval bound')
            END;
        END""",
]

# Registered here, in this order, so the follow-on entry always sits after the objects it
# changes; the plugin loader's own registration of SCHEMA_NAME is then a no-op.
register_schema_version(SCHEMA_NAME, SCHEMA_STATEMENTS)
register_schema_version(DISTRIBUTION_SCHEMA_NAME, DISTRIBUTION_SCHEMA_STATEMENTS)


class FieldError(RuntimeError):
    """Invalid field-control input or an action the record's state does not allow."""


class FieldStateError(FieldError, StaleApprovalError):
    """The subject is not in a state the operation can be proposed or executed in.

    It is a ``FieldError`` for callers of this module (a proposal is refused)
    and a ``StaleApprovalError`` for the core: when it is raised while an
    approval is being consumed, ``service.execute`` rolls the command back and
    invalidates the approval durably instead of leaving it granted."""


# ---- validation helpers ---------------------------------------------------------------------- #

def _text(value: Any, label: str, *, required: bool = True) -> str:
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise FieldError(f"{label} must be a string, not {type(value).__name__}")
    text = value.strip()
    if required and not text:
        raise FieldError(f"{label} is required")
    return text


def _id_list(values: Any, label: str) -> list[str]:
    if values is None:
        return []
    if isinstance(values, (str, bytes)) or not isinstance(values, (list, tuple)):
        raise FieldError(f"{label} must be a list of ids")
    out: list[str] = []
    for v in values:
        t = _text(v, f"{label} entry")
        if t in out:
            raise FieldError(f"{label} lists {t} twice")
        out.append(t)
    return out


def _cost(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        raw = D(value)
        negative = raw < 0  # judged before quantising: "-0.004" is a negative input, not a zero one
        amt = money(raw)
    except (MoneyError, ArithmeticError) as exc:
        raise FieldError(f"cost_impact is not exact money: {exc}") from exc
    if negative:
        raise FieldError(f"cost_impact cannot be negative, got {value!r}")
    return ZERO if amt == 0 else amt  # canonical zero: "-0" and Decimal("-0.00") are stored as "0.00"


def _days(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise FieldError(f"schedule_impact_days must be a whole number of days, not {type(value).__name__}")
    if value < 0:
        raise FieldError(f"schedule_impact_days cannot be negative, got {value}")
    return value


def _response_hash(text: str, cost: Decimal | None, days: int | None) -> str:
    return hash_json({"response": text, "cost_impact": fmt(cost) if cost is not None else None, "schedule_impact_days": days})


def _recipients(recipients: Any) -> tuple[list[str], str]:
    """A non-empty list of distinct (case-insensitively) recipient names, in the
    order given, and the order- and case-insensitive hash that identifies the set."""
    if isinstance(recipients, (str, bytes)) or not isinstance(recipients, (list, tuple)) or not recipients:
        raise FieldError("recipients must be a non-empty list of strings")
    clean: list[str] = []
    seen: set[str] = set()
    for raw in recipients:
        t = _text(raw, "recipient")
        if t.lower() in seen:
            raise FieldError(f"recipient {t} is listed twice")
        seen.add(t.lower())
        clean.append(t)
    return clean, hash_json(sorted(seen))


def _closeout_items(items: Any) -> list[str]:
    if isinstance(items, (str, bytes)) or not isinstance(items, (list, tuple)):
        raise FieldError(f"closeout items must be a non-empty list drawn from {', '.join(CLOSEOUT_ITEMS)}")
    if not items:
        raise FieldError("closeout items must be a non-empty list")
    out: list[str] = []
    for raw in items:
        item = _text(raw, "closeout item")
        if item not in CLOSEOUT_ITEMS:
            raise FieldError(f"unknown closeout item {item!r}; expected one of {', '.join(CLOSEOUT_ITEMS)}")
        if item in out:
            raise FieldError(f"closeout item {item} is listed twice")
        out.append(item)
    return [i for i in CLOSEOUT_ITEMS if i in out]  # canonical order


class Plugin:
    def __init__(self, cipher):
        self.c = cipher
        self.db = cipher.db
        self.audit = cipher.audit
        self.ledger = cipher.ledger
        self.approvals = cipher.approvals

    # ---- shared helpers ---------------------------------------------------------------------- #

    def _project(self, project_id: Any) -> dict[str, Any]:
        pid = _text(project_id, "project_id")
        row = self.db.one("SELECT * FROM projects WHERE id=?", (pid,))
        if row is None:
            raise FieldError(f"unknown project {pid}")
        return row

    def _drawing_plugin(self):
        try:
            return self.c.plugin("drawing")
        except KeyError:
            return None

    def _rfi_controls(self,rfi_id):
        controls=self.c._plugins.get('rfi_controls')
        return controls if controls is not None and controls.is_modern(rfi_id) else None

    @contextmanager
    def _rfi_transaction(self,rfi_id):
        """Keep a classified source mutation whole even in a caught outer transaction."""
        with self.db.transaction() as conn:
            controls=self._rfi_controls(rfi_id)
            if controls is None:
                yield conn,None
                return
            savepoint=new_id('rfi_source_act')
            conn.execute(f'SAVEPOINT {savepoint}')
            try:
                yield conn,controls
            except BaseException:
                if conn.in_transaction:conn.execute(f'ROLLBACK TO {savepoint}')
                raise
            finally:
                if conn.in_transaction:conn.execute(f'RELEASE {savepoint}')

    def _commitment(self, commitment_id: Any) -> dict[str, Any]:
        cid = _text(commitment_id, "commitment_id")
        row = self.db.one("SELECT * FROM commitments WHERE id=?", (cid,))
        if row is None:
            raise FieldError(f"unknown commitment {cid}")
        return row

    def _executed_commitment(self, commitment_id: Any, project_id: str | None = None) -> dict[str, Any]:
        c = self._commitment(commitment_id)
        if project_id is not None and c["project_id"] != project_id:
            raise FieldError(f"commitment {c['id']} belongs to another project")
        if c["status"] != "executed":
            raise FieldError(f"commitment {c['id']} is {c['status']}; field closeout controls apply to executed commitments only")
        return c

    @staticmethod
    def _next_sequence(conn, table: str, project_id: str) -> int:
        return conn.execute(f"SELECT COALESCE(MAX(sequence), 0) FROM {table} WHERE project_id=?", (project_id,)).fetchone()[0] + 1

    def _citable_document_revision(self, project_id: str, revision_id: str, what: str) -> dict[str, Any]:
        try:
            ev = self.c.evidence.revision(revision_id)
        except EvidenceError as exc:
            raise FieldError(f"{what} must bind an existing evidence revision: {exc}") from exc
        doc = self.db.one("SELECT project_id FROM documents WHERE id=?", (ev["document_id"],))
        if doc is None or doc["project_id"] != project_id:
            raise FieldError(f"evidence revision {revision_id} belongs to a different project")
        return ev

    def _citable_drawing_revision(self, drawings, project_id: str, revision_id: str) -> dict[str, Any]:
        try:
            rev = drawings.revision(revision_id)
            drawing = drawings.get(rev["drawing_id"])
        except RuntimeError as exc:
            raise FieldError(f"an RFI cites existing drawing revisions only: {exc}") from exc
        if drawing["project_id"] != project_id:
            raise FieldError(f"drawing {drawing['number']} revision {rev['label']} belongs to a different project")
        if rev["status"] != "issued":
            raise FieldError(f"drawing {drawing['number']} revision {rev['label']} is {rev['status']}; an RFI cites the issued revision only")
        rev["drawing_number"] = drawing["number"]
        return rev

    # ---- RFIs ------------------------------------------------------------------------------- #

    def create_rfi(self, project_id: str, subject: str, question: str, actor: str, drawing_revision_ids=(), document_revision_ids=()) -> dict[str, Any]:
        """Open an RFI (``RFI-001``... per project) citing exact issued drawing
        revisions and evidence revisions of the same project."""
        subject = _text(subject, "RFI subject")
        question = _text(question, "RFI question")
        actor = _text(actor, "actor")
        drawing_ids = _id_list(drawing_revision_ids, "drawing_revision_ids")
        document_ids = _id_list(document_revision_ids, "document_revision_ids")
        rfi_id = new_id("rfi")
        with self.db.transaction() as conn:
            project = self._project(project_id)
            pid = project["id"]
            dup = conn.execute(
                "SELECT number FROM field_rfis WHERE project_id=? AND lower(subject)=lower(?) AND lower(question)=lower(?)", (pid, subject, question)
            ).fetchone()
            if dup is not None:
                raise FieldError(f"{dup['number']} already asks this question on project {pid}")
            drawings = self._drawing_plugin()
            if drawing_ids and drawings is None:
                raise FieldError("the drawing register is not available, so an RFI cannot cite drawing revisions")
            cited_drawings = [self._citable_drawing_revision(drawings, pid, rid) for rid in drawing_ids]
            cited_documents = [self._citable_document_revision(pid, rid, "an RFI citation") for rid in document_ids]
            seq = self._next_sequence(conn, "field_rfis", pid)
            number = f"RFI-{seq:03d}"
            content_hash = hash_json({
                "project_id": pid, "subject": subject, "question": question,
                "drawing_revisions": [{"id": r["id"], "content_hash": r["content_hash"]} for r in cited_drawings],
                "document_revisions": [{"id": e["id"], "content_hash": e["content_hash"]} for e in cited_documents],
            })
            now = utcnow_iso()
            conn.execute(
                """INSERT INTO field_rfis (id, project_id, sequence, number, subject, question, status, version, content_hash, created_by, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,'open',1,?,?,?,?)""",
                (rfi_id, pid, seq, number, subject, question, content_hash, actor, now, now),
            )
            for rev in cited_drawings:
                try:
                    ref = drawings.reference(rev["id"], "rfi", rfi_id, actor=actor)
                except RuntimeError as exc:
                    raise FieldError(f"the drawing register refused the reference: {exc}") from exc
                self._insert_link(conn, rfi_id, "drawing_revision", rev["id"], rev["content_hash"], ref["id"], actor, now)
            for ev in cited_documents:
                self._insert_link(conn, rfi_id, "document_revision", ev["id"], ev["content_hash"], None, actor, now)
            self.audit.record(actor, "field.rfi_created", RFI_SUBJECT, rfi_id, {
                "project_id": pid, "number": number, "subject": subject, "content_hash": content_hash, "version": 1,
                "drawing_revisions": [{"id": r["id"], "drawing": r["drawing_number"], "label": r["label"], "content_hash": r["content_hash"]} for r in cited_drawings],
                "document_revisions": [{"id": e["id"], "content_hash": e["content_hash"]} for e in cited_documents],
            })
        return self.rfi(rfi_id)

    @staticmethod
    def _insert_link(conn, rfi_id: str, link_type: str, target_id: str, target_hash: str, reference_id: str | None, actor: str, now: str) -> str:
        link_id = new_id("rfil")
        conn.execute(
            "INSERT INTO field_rfi_links (id, rfi_id, link_type, target_id, target_hash, reference_id, created_by, created_at) VALUES (?,?,?,?,?,?,?,?)",
            (link_id, rfi_id, link_type, target_id, target_hash, reference_id, actor, now),
        )
        return link_id

    def draft_response(self, rfi_id: str, response_text: str, cost_impact=None, schedule_impact_days=None, actor: str | None = None) -> dict[str, Any]:
        """Record (or replace) the proposed response of an open RFI.  Bumps the
        RFI version and invalidates every open approval on the RFI."""
        text = _text(response_text, "response text")
        cost = _cost(cost_impact)
        days = _days(schedule_impact_days)
        actor = _text(actor, "actor")
        draft_hash = _response_hash(text, cost, days)
        with self._rfi_transaction(rfi_id) as (conn,controls):
            r = self._rfi_row(rfi_id)
            if controls is not None:
                checked=controls.before_native_response(rfi_id,text,fmt(cost) if cost is not None else None,days,actor)
                actor=checked['person']['login']
            if r["status"] != "open":
                raise FieldError(f"{r['number']} is {r['status']}; only an open RFI takes a draft response")
            if r["draft_response_hash"] == draft_hash:
                raise FieldError(f"{r['number']} already carries exactly this draft response")
            version = r["version"] + 1
            cur = conn.execute(
                """UPDATE field_rfis SET draft_response=?, draft_cost_impact=?, draft_schedule_impact_days=?, draft_response_hash=?, version=?, updated_at=?
                   WHERE id=? AND version=?""",
                (text, fmt(cost) if cost is not None else None, days, draft_hash, version, utcnow_iso(), r["id"], r["version"]),
            )
            if cur.rowcount != 1:
                raise FieldError(f"{r['number']} changed concurrently; retry")
            invalidated = self.approvals.invalidate_for_subject(RFI_SUBJECT, r["id"], reason=f"{r['number']} draft response changed (version {version})", actor=actor)
            self.audit.record(actor, "field.rfi_response_drafted", RFI_SUBJECT, r["id"], {
                "number": r["number"], "version": version, "draft_response_hash": draft_hash,
                "cost_impact": fmt(cost) if cost is not None else None, "schedule_impact_days": days, "approvals_invalidated": invalidated,
            })
            if controls is not None:controls.record_response_revision(rfi_id,actor)
        return self.rfi(r["id"])

    def set_distribution_list(self, rfi_id: str, recipients, actor: str) -> dict[str, Any]:
        """Record who receives an answered RFI's official response.  Bumps the RFI
        version and invalidates every open approval on the RFI; the distribution
        itself is the approval-bound ``field.distribute_rfi`` operation."""
        actor = _text(actor, "actor")
        clean, recipients_hash = _recipients(recipients)
        with self._rfi_transaction(rfi_id) as (conn,controls):
            r = self._rfi_row(rfi_id)
            if controls is not None:
                checked=controls.before_native_distribution_list(rfi_id,clean,actor)
                actor=checked['person']['login']
            if r["status"] != "answered":
                raise FieldError(f"{r['number']} is {r['status']}; its distribution list is set once the response is issued through {OP_RESPOND_RFI}")
            if r["distribution_recipients_hash"] == recipients_hash:
                try:
                    self._stored_distribution_list(r)
                except FieldStateError as exc:  # the stored list was tampered with and carries this list's hash
                    raise FieldError(f"{exc}; it already carries the hash of these recipients, so record a different list") from exc
                raise FieldError(f"{r['number']} already has exactly this distribution list")
            dup = self._existing_distribution(r["id"], r["response_hash"], recipients_hash)
            if dup is not None:
                raise FieldError(f"{r['number']} response was already distributed to these recipients ({dup['id']})")
            version = r["version"] + 1
            cur = conn.execute(
                "UPDATE field_rfis SET distribution_recipients_json=?, distribution_recipients_hash=?, version=?, updated_at=? WHERE id=? AND version=?",
                (json.dumps(clean), recipients_hash, version, utcnow_iso(), r["id"], r["version"]),
            )
            if cur.rowcount != 1:
                raise FieldError(f"{r['number']} changed concurrently; retry")
            invalidated = self.approvals.invalidate_for_subject(RFI_SUBJECT, r["id"], reason=f"{r['number']} distribution list changed (version {version})", actor=actor)
            self.audit.record(actor, "field.rfi_distribution_list_set", RFI_SUBJECT, r["id"], {
                "number": r["number"], "version": version, "recipients": clean, "recipients_hash": recipients_hash,
                "previous_recipients_hash": r["distribution_recipients_hash"], "approvals_invalidated": invalidated,
            })
            if controls is not None:controls.record_distribution_revision(rfi_id,actor)
        return self.rfi(r["id"])

    def distribute_rfi(self, rfi_id: str, recipients=None, actor: str | None = None) -> dict[str, Any]:
        """Retired direct path: distribution is approval-bound now."""
        raise FieldError(
            f"RFIs are no longer distributed directly: record the recipients with set_distribution_list(rfi_id, recipients, actor), "
            f"then request, grant and execute the {OP_DISTRIBUTE_RFI} approval for the RFI (it binds the RFI version, the response and the recipients)"
        )

    @staticmethod
    def _stored_distribution_list(r: dict[str, Any]) -> tuple[list[str], str]:
        """The RFI's stored distribution list, rebuilt and re-hashed from the stored JSON.

        The database cannot hash, so the once-only rule (one distribution per response
        and recipient set) is only as good as the stored hash: a list whose JSON is not
        a canonical recipient list, or whose hash is not the hash of that list, is
        refused here instead of being distributed (or distributed twice)."""
        raw, stored_hash = r.get("distribution_recipients_json"), r.get("distribution_recipients_hash")
        if raw is None or stored_hash is None:
            raise FieldStateError(f"{r['number']} has no distribution list; record one with set_distribution_list first")
        try:
            parsed = json.loads(raw)
            clean, recipients_hash = _recipients(parsed)
        except (TypeError, ValueError, FieldError) as exc:
            raise FieldStateError(f"{r['number']} stored distribution list is not a valid recipient list ({exc}); record it again with set_distribution_list") from exc
        if json.dumps(clean) != raw or recipients_hash != stored_hash:
            raise FieldStateError(
                f"{r['number']} stored distribution list does not match its recipients hash; it was changed outside set_distribution_list. "
                "Record the list again with set_distribution_list"
            )
        return clean, recipients_hash

    def _existing_distribution(self, rfi_id: str, response_hash: str | None, recipients_hash: str | None) -> dict[str, Any] | None:
        if response_hash is None or recipients_hash is None:
            return None
        return self.db.one(
            "SELECT id FROM field_rfi_distributions WHERE rfi_id=? AND response_hash=? AND recipients_hash=?", (rfi_id, response_hash, recipients_hash)
        )

    def link_change(self, rfi_id: str, commitment_id: str, actor: str, sov_line_id: str | None = None) -> dict[str, Any]:
        """Turn an answered RFI's positive cost impact into one PENDING core change
        on an executed commitment of the same project.  Executing the change
        remains the core ``change.execute`` approval."""
        actor = _text(actor, "actor")
        if sov_line_id is not None:
            sov_line_id = _text(sov_line_id, "sov_line_id")
        if self._rfi_controls(rfi_id) is not None:
            raise FieldError('A qualified RFI reports potential impacts; a separate change workflow must authorize any adoption')
        with self.db.transaction() as conn:
            r = self._rfi_row(rfi_id)
            if r["status"] != "answered":
                raise FieldError(f"{r['number']} is {r['status']}; only an answered RFI can raise a change")
            cost = money(r["cost_impact"]) if r["cost_impact"] is not None else ZERO
            if cost <= ZERO:
                raise FieldError(f"{r['number']} was answered without a cost impact; there is no change to propose")
            existing = conn.execute("SELECT target_id FROM field_rfi_links WHERE rfi_id=? AND link_type='change'", (r["id"],)).fetchone()
            if existing is not None:
                raise FieldError(f"{r['number']} is already linked to change {existing['target_id']}; one change per RFI")
            self._executed_commitment(commitment_id, project_id=r["project_id"])
            try:
                ch = self.c.commitments.propose_change(commitment_id, amount=cost, reason=f"{r['number']}: {r['subject']}", sov_line_id=sov_line_id, actor=actor)
            except CommitmentError as exc:
                raise FieldError(f"cannot propose the change for {r['number']}: {exc}") from exc
            target_hash = hash_json({
                "change_id": ch["id"], "commitment_id": ch["commitment_id"], "amount": ch["amount"], "reason": ch["reason"],
                "sov_line_id": ch["sov_line_id"], "rfi_response_hash": r["response_hash"],
            })
            link_id = self._insert_link(conn, r["id"], "change", ch["id"], target_hash, None, actor, utcnow_iso())
            # a pending change blocks closeout acceptance of its commitment; drop any open acceptance approval now
            closeout_invalidated = self.approvals.invalidate_for_subject(
                CLOSEOUT_SUBJECT, ch["commitment_id"], reason=f"{r['number']} raised pending change {ch['id']} of {ch['amount']}", actor=actor
            )
            self.audit.record(actor, "field.rfi_change_linked", RFI_SUBJECT, r["id"], {
                "number": r["number"], "change_id": ch["id"], "commitment_id": ch["commitment_id"], "amount": ch["amount"],
                "sov_line_id": ch["sov_line_id"], "link_id": link_id, "status": ch["status"], "closeout_approvals_invalidated": closeout_invalidated,
            })
        out = self.c.commitments.change(ch["id"])
        out.update({"rfi_id": r["id"], "rfi_number": r["number"], "link_id": link_id})
        return out

    def _rfi_row(self, rfi_id: Any) -> dict[str, Any]:
        rid = _text(rfi_id, "rfi_id")
        row = self.db.one("SELECT * FROM field_rfis WHERE id=?", (rid,))
        if row is None:
            raise FieldError(f"unknown RFI {rid}")
        return row

    def _distribution(self, dist_id: str) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM field_rfi_distributions WHERE id=?", (dist_id,))
        if row is None:
            raise FieldError(f"unknown RFI distribution {dist_id}")
        row["recipients"] = json.loads(row.pop("recipients_json"))
        return row

    def rfi(self, rfi_id: str) -> dict[str, Any]:
        row = self._rfi_row(rfi_id)
        links = self.db.query("SELECT * FROM field_rfi_links WHERE rfi_id=? ORDER BY created_at, id", (row["id"],))
        row["links"] = links
        row["drawing_revision_ids"] = [l["target_id"] for l in links if l["link_type"] == "drawing_revision"]
        row["document_revision_ids"] = [l["target_id"] for l in links if l["link_type"] == "document_revision"]
        change_link = next((l for l in links if l["link_type"] == "change"), None)
        row["change"] = self.c.commitments.change(change_link["target_id"]) if change_link else None
        row["distributions"] = [self._distribution(d["id"]) for d in self.db.query("SELECT id FROM field_rfi_distributions WHERE rfi_id=? ORDER BY distributed_at, id", (row["id"],))]
        row["has_draft_response"] = row["draft_response_hash"] is not None
        listed_hash = row.setdefault("distribution_recipients_hash", None)
        intact = None
        if listed_hash is not None:
            try:
                self._stored_distribution_list(row)
                intact = True
            except FieldStateError:
                intact = False
        listed = row.pop("distribution_recipients_json", None)
        try:
            row["distribution_list"] = json.loads(listed) if listed is not None else None
        except ValueError:  # not JSON at all: shown as stored, and flagged as not intact
            row["distribution_list"] = listed
        row["distribution_list_intact"] = intact
        row["distribution_pending"] = bool(intact) and self._existing_distribution(row["id"], row["response_hash"], listed_hash) is None
        return row

    def rfis(self, project_id: str) -> list[dict[str, Any]]:
        return [self.rfi(r["id"]) for r in self.db.query("SELECT id FROM field_rfis WHERE project_id=? ORDER BY sequence", (project_id,))]

    # ---- submittals ---------------------------------------------------------------------------- #

    def create_submittal(self, project_id: str, spec_section: str, title: str, actor: str, equipment_tag: str | None = None) -> dict[str, Any]:
        """Register a submittal (``SUB-001``... per project)."""
        spec_section = _text(spec_section, "spec_section")
        title = _text(title, "submittal title")
        actor = _text(actor, "actor")
        tag = _text(equipment_tag, "equipment_tag", required=False) or None
        sub_id = new_id("sub")
        with self.db.transaction() as conn:
            project = self._project(project_id)
            pid = project["id"]
            dup = conn.execute(
                "SELECT number FROM field_submittals WHERE project_id=? AND lower(spec_section)=lower(?) AND lower(title)=lower(?) AND lower(COALESCE(equipment_tag,''))=lower(?)",
                (pid, spec_section, title, tag or ""),
            ).fetchone()
            if dup is not None:
                raise FieldError(f"{dup['number']} already covers {spec_section} {title}{(' ' + tag) if tag else ''} on project {pid}")
            seq = self._next_sequence(conn, "field_submittals", pid)
            number = f"SUB-{seq:03d}"
            now = utcnow_iso()
            conn.execute(
                """INSERT INTO field_submittals (id, project_id, sequence, number, spec_section, title, equipment_tag, status, version, created_by, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,'open',1,?,?,?)""",
                (sub_id, pid, seq, number, spec_section, title, tag, actor, now, now),
            )
            self.audit.record(actor, "field.submittal_created", SUBMITTAL_SUBJECT, sub_id, {"project_id": pid, "number": number, "spec_section": spec_section, "title": title, "equipment_tag": tag})
        return self.submittal(sub_id)

    def add_submittal_revision(self, submittal_id: str, document_revision_id: str, actor: str) -> dict[str, Any]:
        """Submit a revision (1, 2, ...) bound to an evidence revision of the
        same project.  Only one revision is under review at a time."""
        actor = _text(actor, "actor")
        doc_rev_id = _text(document_revision_id, "document_revision_id")
        rev_id = new_id("subr")
        with self.db.transaction() as conn:
            s = self._submittal_row(submittal_id)
            if s["status"] == "under_review":
                current = conn.execute("SELECT revision FROM field_submittal_revisions WHERE submittal_id=? AND status='under_review'", (s["id"],)).fetchone()
                raise FieldError(f"{s['number']} already has revision {current['revision'] if current else '?'} under review; decide it first")
            if s["status"] in ("approved", "rejected"):
                raise FieldError(f"{s['number']} is {s['status']} and final; create a new submittal instead")
            ev = self._citable_document_revision(s["project_id"], doc_rev_id, "a submittal revision")
            dup = conn.execute("SELECT revision FROM field_submittal_revisions WHERE submittal_id=? AND document_revision_id=?", (s["id"], ev["id"])).fetchone()
            if dup is not None:
                raise FieldError(f"evidence revision {ev['id']} was already submitted as revision {dup['revision']} of {s['number']}")
            revision = conn.execute("SELECT COALESCE(MAX(revision), 0) FROM field_submittal_revisions WHERE submittal_id=?", (s["id"],)).fetchone()[0] + 1
            now = utcnow_iso()
            conn.execute(
                """INSERT INTO field_submittal_revisions (id, submittal_id, revision, document_revision_id, document_hash, status, version, created_by, created_at, updated_at)
                   VALUES (?,?,?,?,?,'under_review',1,?,?,?)""",
                (rev_id, s["id"], revision, ev["id"], ev["content_hash"], actor, now, now),
            )
            version = self._bump_submittal(conn, s, status="under_review")
            self.audit.record(actor, "field.submittal_revision_added", REVISION_SUBJECT, rev_id, {
                "submittal_id": s["id"], "number": s["number"], "revision": revision, "document_revision_id": ev["id"],
                "document_hash": ev["content_hash"], "submittal_version": version,
            })
        return self.submittal_revision(rev_id)

    def _bump_submittal(self, conn, s: dict[str, Any], *, status: str) -> int:
        version = s["version"] + 1
        cur = conn.execute(
            "UPDATE field_submittals SET status=?, version=?, updated_at=? WHERE id=? AND version=?", (status, version, utcnow_iso(), s["id"], s["version"])
        )
        if cur.rowcount != 1:
            raise FieldError(f"{s['number']} changed concurrently; retry")
        return version

    def set_decision(self, revision_id: str, decision: str, comments: str, actor: str) -> dict[str, Any]:
        """Record the reviewer's proposed decision on the revision under review.
        Comments are optional (a string, possibly empty) and are bound by hash.
        Bumps the revision version and invalidates open approvals on it."""
        decision = _text(decision, "decision")
        if decision not in DECISIONS:
            raise FieldError(f"unknown submittal decision {decision!r}; expected one of {', '.join(DECISIONS)}")
        comments = _text(comments, "comments", required=False)
        actor = _text(actor, "actor")
        comments_hash = sha256_hex(comments)
        with self.db.transaction() as conn:
            rev = self._revision_row(revision_id)
            s = self._submittal_row(rev["submittal_id"])
            if rev["status"] != "under_review":
                raise FieldError(f"{s['number']} revision {rev['revision']} is {rev['status']} and final")
            if rev["draft_decision"] == decision and rev["draft_comments_hash"] == comments_hash:
                raise FieldError(f"{s['number']} revision {rev['revision']} already carries exactly this decision")
            version = rev["version"] + 1
            cur = conn.execute(
                "UPDATE field_submittal_revisions SET draft_decision=?, draft_comments=?, draft_comments_hash=?, version=?, updated_at=? WHERE id=? AND version=?",
                (decision, comments, comments_hash, version, utcnow_iso(), rev["id"], rev["version"]),
            )
            if cur.rowcount != 1:
                raise FieldError(f"{s['number']} revision {rev['revision']} changed concurrently; retry")
            invalidated = self.approvals.invalidate_for_subject(REVISION_SUBJECT, rev["id"], reason=f"{s['number']} revision {rev['revision']} decision changed (version {version})", actor=actor)
            self.audit.record(actor, "field.submittal_decision_drafted", REVISION_SUBJECT, rev["id"], {
                "submittal_id": s["id"], "number": s["number"], "revision": rev["revision"], "decision": decision,
                "comments_hash": comments_hash, "version": version, "approvals_invalidated": invalidated,
            })
        return self.submittal_revision(rev["id"])

    def _submittal_row(self, submittal_id: Any) -> dict[str, Any]:
        sid = _text(submittal_id, "submittal_id")
        row = self.db.one("SELECT * FROM field_submittals WHERE id=?", (sid,))
        if row is None:
            raise FieldError(f"unknown submittal {sid}")
        return row

    def _revision_row(self, revision_id: Any) -> dict[str, Any]:
        rid = _text(revision_id, "submittal revision id")
        row = self.db.one("SELECT * FROM field_submittal_revisions WHERE id=?", (rid,))
        if row is None:
            raise FieldError(f"unknown submittal revision {rid}")
        return row

    def submittal_revision(self, revision_id: str) -> dict[str, Any]:
        row = self._revision_row(revision_id)
        row["submittal_number"] = self.db.scalar("SELECT number FROM field_submittals WHERE id=?", (row["submittal_id"],))
        return row

    def submittal(self, submittal_id: str) -> dict[str, Any]:
        row = self._submittal_row(submittal_id)
        row["revisions"] = self.db.query("SELECT * FROM field_submittal_revisions WHERE submittal_id=? ORDER BY revision", (row["id"],))
        under = [r for r in row["revisions"] if r["status"] == "under_review"]
        row["under_review_revision"] = under[0]["revision"] if under else None
        approving = [r for r in row["revisions"] if r["status"] in ("approved", "approved_as_noted")]
        row["approved_revision_id"] = approving[-1]["id"] if approving else None
        return row

    def submittals(self, project_id: str) -> list[dict[str, Any]]:
        return [self.submittal(r["id"]) for r in self.db.query("SELECT id FROM field_submittals WHERE project_id=? ORDER BY sequence", (project_id,))]

    # ---- hold points ----------------------------------------------------------------------------- #

    def add_hold_point(self, project_id: str, description: str, submittal_id: str, actor: str) -> dict[str, Any]:
        """Hold field work until ``submittal_id`` (same project) is approved."""
        description = _text(description, "hold point description")
        actor = _text(actor, "actor")
        hp_id = new_id("hold")
        with self.db.transaction() as conn:
            project = self._project(project_id)
            s = self._submittal_row(submittal_id)
            if s["project_id"] != project["id"]:
                raise FieldError(f"{s['number']} belongs to another project")
            if s["status"] == "rejected":
                raise FieldError(f"{s['number']} was rejected and can never release a hold point; hold on a new submittal")
            dup = conn.execute(
                "SELECT id FROM field_hold_points WHERE submittal_id=? AND lower(description)=lower(?) AND status='held'", (s["id"], description)
            ).fetchone()
            if dup is not None:
                raise FieldError(f"hold point {dup['id']} already holds this work on {s['number']}")
            conn.execute(
                "INSERT INTO field_hold_points (id, project_id, submittal_id, description, status, version, created_by, created_at) VALUES (?,?,?,?,'held',1,?,?)",
                (hp_id, project["id"], s["id"], description, actor, utcnow_iso()),
            )
            self.audit.record(actor, "field.hold_point_added", HOLD_POINT_SUBJECT, hp_id, {"project_id": project["id"], "submittal_id": s["id"], "number": s["number"], "description": description})
        return self.hold_point(hp_id)

    def release_hold_point(self, hold_point_id: str, actor: str) -> dict[str, Any]:
        """Release a hold point once its submittal is approved; records the approving revision."""
        actor = _text(actor, "actor")
        with self.db.transaction() as conn:
            hp = self.hold_point(hold_point_id)
            if hp["status"] != "held":
                raise FieldError(f"hold point {hp['id']} is already {hp['status']}")
            s = self.submittal(hp["submittal_id"])
            if s["status"] != "approved" or not s["approved_revision_id"]:
                raise FieldError(f"hold point {hp['id']} waits on {s['number']}, which is {s['status']}; it is released only once the submittal is approved")
            version = hp["version"] + 1
            now = utcnow_iso()
            cur = conn.execute(
                "UPDATE field_hold_points SET status='released', released_revision_id=?, released_by=?, released_at=?, version=? WHERE id=? AND version=?",
                (s["approved_revision_id"], actor, now, version, hp["id"], hp["version"]),
            )
            if cur.rowcount != 1:
                raise FieldError(f"hold point {hp['id']} changed concurrently; retry")
            self.audit.record(actor, "field.hold_point_released", HOLD_POINT_SUBJECT, hp["id"], {
                "submittal_id": s["id"], "number": s["number"], "released_revision_id": s["approved_revision_id"], "version": version,
            })
        return self.hold_point(hp["id"])

    def hold_point(self, hold_point_id: Any) -> dict[str, Any]:
        hid = _text(hold_point_id, "hold_point_id")
        row = self.db.one("SELECT * FROM field_hold_points WHERE id=?", (hid,))
        if row is None:
            raise FieldError(f"unknown hold point {hid}")
        row["submittal_number"] = self.db.scalar("SELECT number FROM field_submittals WHERE id=?", (row["submittal_id"],))
        row["submittal_status"] = self.db.scalar("SELECT status FROM field_submittals WHERE id=?", (row["submittal_id"],))
        return row

    def hold_points(self, project_id: str) -> list[dict[str, Any]]:
        return [self.hold_point(r["id"]) for r in self.db.query("SELECT id FROM field_hold_points WHERE project_id=? ORDER BY created_at, id", (project_id,))]

    # ---- punch list ------------------------------------------------------------------------------- #

    def add_punch_item(self, project_id: str, commitment_id: str, description: str, actor: str) -> dict[str, Any]:
        """Open a punch item (``PUNCH-001``... per project) against an executed
        commitment.  Invalidates open closeout approvals for that commitment."""
        description = _text(description, "punch item description")
        actor = _text(actor, "actor")
        item_id = new_id("pun")
        with self.db.transaction() as conn:
            project = self._project(project_id)
            c = self._executed_commitment(commitment_id, project_id=project["id"])
            dup = conn.execute(
                "SELECT number FROM field_punch_items WHERE commitment_id=? AND lower(description)=lower(?) AND status='open'", (c["id"], description)
            ).fetchone()
            if dup is not None:
                raise FieldError(f"{dup['number']} already lists this open item on commitment {c['id']}")
            seq = self._next_sequence(conn, "field_punch_items", project["id"])
            number = f"PUNCH-{seq:03d}"
            conn.execute(
                "INSERT INTO field_punch_items (id, project_id, commitment_id, sequence, number, description, status, version, created_by, created_at) VALUES (?,?,?,?,?,?,'open',1,?,?)",
                (item_id, project["id"], c["id"], seq, number, description, actor, utcnow_iso()),
            )
            invalidated = self.approvals.invalidate_for_subject(CLOSEOUT_SUBJECT, c["id"], reason=f"punch item {number} opened", actor=actor)
            self.audit.record(actor, "field.punch_item_added", PUNCH_SUBJECT, item_id, {
                "project_id": project["id"], "commitment_id": c["id"], "number": number, "description": description, "approvals_invalidated": invalidated,
            })
        return self.punch_item(item_id)

    def close_punch_item(self, item_id: str, evidence_hash: str, actor: str) -> dict[str, Any]:
        """Close a punch item with completion evidence (a content hash)."""
        evidence = _text(evidence_hash, "evidence_hash")
        actor = _text(actor, "actor")
        with self.db.transaction() as conn:
            p = self.punch_item(item_id)
            if p["status"] != "open":
                raise FieldError(f"{p['number']} is already {p['status']}")
            version = p["version"] + 1
            cur = conn.execute(
                "UPDATE field_punch_items SET status='closed', evidence_hash=?, closed_by=?, closed_at=?, version=? WHERE id=? AND version=?",
                (evidence, actor, utcnow_iso(), version, p["id"], p["version"]),
            )
            if cur.rowcount != 1:
                raise FieldError(f"{p['number']} changed concurrently; retry")
            invalidated = self.approvals.invalidate_for_subject(CLOSEOUT_SUBJECT, p["commitment_id"], reason=f"punch item {p['number']} closed", actor=actor)
            self.audit.record(actor, "field.punch_item_closed", PUNCH_SUBJECT, p["id"], {
                "commitment_id": p["commitment_id"], "number": p["number"], "evidence_hash": evidence, "version": version, "approvals_invalidated": invalidated,
            })
        return self.punch_item(p["id"])

    def punch_item(self, item_id: Any) -> dict[str, Any]:
        iid = _text(item_id, "punch item id")
        row = self.db.one("SELECT * FROM field_punch_items WHERE id=?", (iid,))
        if row is None:
            raise FieldError(f"unknown punch item {iid}")
        return row

    def punch_items(self, project_id: str, *, commitment_id: str | None = None) -> list[dict[str, Any]]:
        if commitment_id:
            return self.db.query("SELECT * FROM field_punch_items WHERE project_id=? AND commitment_id=? ORDER BY sequence", (project_id, commitment_id))
        return self.db.query("SELECT * FROM field_punch_items WHERE project_id=? ORDER BY sequence", (project_id,))

    # ---- closeout ----------------------------------------------------------------------------------- #

    def set_closeout_requirements(self, commitment_id: str, items, actor: str) -> dict[str, Any]:
        """Set the required closeout deliverables for an executed commitment.
        Creates the closeout at version 1 or bumps its version; items dropped
        from the list stop being required (their history is kept)."""
        wanted = _closeout_items(items)
        actor = _text(actor, "actor")
        with self.db.transaction() as conn:
            c = self._executed_commitment(commitment_id)
            co = self._closeout_row(c["id"])
            now = utcnow_iso()
            existing = {r["item"]: r for r in self._requirement_rows(c["id"])}
            current = [i for i in CLOSEOUT_ITEMS if i in existing and existing[i]["required"]]
            if co is None:
                co_id = new_id("fco")
                conn.execute(
                    "INSERT INTO field_closeouts (id, commitment_id, project_id, status, version, created_by, created_at, updated_at) VALUES (?,?,?,'open',1,?,?,?)",
                    (co_id, c["id"], c["project_id"], actor, now, now),
                )
                version = 1
            else:
                if co["status"] != "open":
                    raise FieldError(f"the closeout of commitment {c['id']} is {co['status']}; requirements are frozen")
                if current == wanted:
                    raise FieldError(f"commitment {c['id']} already requires exactly {', '.join(wanted)}")
                co_id = co["id"]
                version = self._bump_closeout(conn, co)
            # requirement rows are written at the (already bumped) closeout version; the database refuses any other write
            for item in CLOSEOUT_ITEMS:
                row = existing.get(item)
                if item in wanted:
                    if row is None:
                        conn.execute(
                            """INSERT INTO field_closeout_requirements (id, closeout_id, commitment_id, item, required, status, closeout_version, created_at, updated_at)
                               VALUES (?,?,?,?,1,'pending',?,?,?)""",
                            (new_id("fcr"), co_id, c["id"], item, version, now, now),
                        )
                    elif not row["required"]:
                        conn.execute("UPDATE field_closeout_requirements SET required=1, closeout_version=?, updated_at=? WHERE id=?", (version, now, row["id"]))
                elif row is not None and row["required"]:
                    conn.execute("UPDATE field_closeout_requirements SET required=0, closeout_version=?, updated_at=? WHERE id=?", (version, now, row["id"]))
            invalidated = self.approvals.invalidate_for_subject(CLOSEOUT_SUBJECT, c["id"], reason=f"closeout requirements changed (version {version})", actor=actor)
            self.audit.record(actor, "field.closeout_requirements_set", CLOSEOUT_SUBJECT, c["id"], {
                "closeout_id": co_id, "items": wanted, "added": [i for i in wanted if i not in current], "removed": [i for i in current if i not in wanted],
                "closeout_version": version, "approvals_invalidated": invalidated,
            })
        return self.closeout(c["id"])

    def submit_closeout_item(self, commitment_id: str, item: str, evidence_hash: str, actor: str) -> dict[str, Any]:
        """Submit (or resubmit with new) evidence for a required closeout item.
        Bumps the closeout version and invalidates open acceptance approvals."""
        item = _text(item, "closeout item")
        if item not in CLOSEOUT_ITEMS:
            raise FieldError(f"unknown closeout item {item!r}; expected one of {', '.join(CLOSEOUT_ITEMS)}")
        evidence = _text(evidence_hash, "evidence_hash")
        actor = _text(actor, "actor")
        with self.db.transaction() as conn:
            c = self._commitment(commitment_id)
            co = self._closeout_row(c["id"])
            if co is None:
                raise FieldError(f"commitment {c['id']} has no closeout requirements; set them first")
            if co["status"] != "open":
                raise FieldError(f"the closeout of commitment {c['id']} is {co['status']}; nothing more is submitted")
            req = next((r for r in self._requirement_rows(c["id"]) if r["item"] == item), None)
            if req is None or not req["required"]:
                raise FieldError(f"{item} is not a closeout requirement of commitment {c['id']}")
            if req["evidence_hash"] == evidence:
                raise FieldError(f"{item} was already submitted with this evidence")
            other = conn.execute(
                "SELECT item FROM field_closeout_requirements WHERE commitment_id=? AND evidence_hash=? AND item != ?", (c["id"], evidence, item)
            ).fetchone()
            if other is not None:
                raise FieldError(f"this evidence was already submitted for {other['item']}; each closeout item needs its own evidence")
            now = utcnow_iso()
            version = self._bump_closeout(conn, co)
            conn.execute(
                "UPDATE field_closeout_requirements SET status='submitted', evidence_hash=?, submitted_by=?, submitted_at=?, closeout_version=?, updated_at=? WHERE id=?",
                (evidence, actor, now, version, now, req["id"]),
            )
            invalidated = self.approvals.invalidate_for_subject(CLOSEOUT_SUBJECT, c["id"], reason=f"closeout item {item} submitted (version {version})", actor=actor)
            self.audit.record(actor, "field.closeout_item_submitted", CLOSEOUT_SUBJECT, c["id"], {
                "closeout_id": co["id"], "item": item, "evidence_hash": evidence, "previous_evidence_hash": req["evidence_hash"],
                "closeout_version": version, "approvals_invalidated": invalidated,
            })
        return self.closeout(c["id"])

    def _bump_closeout(self, conn, co: dict[str, Any]) -> int:
        version = co["version"] + 1
        cur = conn.execute("UPDATE field_closeouts SET version=?, updated_at=? WHERE id=? AND version=?", (version, utcnow_iso(), co["id"], co["version"]))
        if cur.rowcount != 1:
            raise FieldError(f"the closeout of commitment {co['commitment_id']} changed concurrently; retry")
        return version

    def _closeout_row(self, commitment_id: str) -> dict[str, Any] | None:
        return self.db.one("SELECT * FROM field_closeouts WHERE commitment_id=?", (commitment_id,))

    def _requirement_rows(self, commitment_id: str) -> list[dict[str, Any]]:
        rows = self.db.query("SELECT * FROM field_closeout_requirements WHERE commitment_id=?", (commitment_id,))
        order = {item: idx for idx, item in enumerate(CLOSEOUT_ITEMS)}
        return sorted(rows, key=lambda r: order[r["item"]])

    def _pending_changes(self, commitment_id: str) -> list[dict[str, Any]]:
        """Core changes on the commitment that are not yet executed or rejected
        (RFI-linked or not): they would grow the commitment after closeout."""
        return self.db.query(
            "SELECT id, amount, status, version, sov_line_id FROM changes WHERE commitment_id=? AND status IN ('pending','approved') ORDER BY created_at, id",
            (commitment_id,),
        )

    def _closeout_facts(self, commitment_id: str) -> dict[str, Any]:
        reqs = [r for r in self._requirement_rows(commitment_id) if r["required"]]
        punch = self.db.query("SELECT id, number, status, version, evidence_hash FROM field_punch_items WHERE commitment_id=? ORDER BY sequence", (commitment_id,))
        pending = self._pending_changes(commitment_id)
        return {
            "requirements": [r["item"] for r in reqs],
            "submitted": {r["item"]: r["evidence_hash"] for r in reqs if r["status"] == "submitted"},
            "missing": [r["item"] for r in reqs if r["status"] != "submitted"],
            "open_punch_count": sum(1 for p in punch if p["status"] == "open"),
            "punch_hash": hash_json(punch),
            "pending_changes": pending,
            "pending_change_exposure": fmt(total(ch["amount"] for ch in pending)),
        }

    @staticmethod
    def _closeout_problems(facts: dict[str, Any]) -> list[str]:
        """Why a closeout cannot be accepted now (empty when it can)."""
        problems = []
        if not facts["requirements"]:
            problems.append("no required items")
        if facts["missing"]:
            problems.append(f"missing {', '.join(facts['missing'])}")
        if facts["open_punch_count"]:
            problems.append(f"{facts['open_punch_count']} open punch item(s)")
        if facts["pending_changes"]:
            problems.append(
                f"{len(facts['pending_changes'])} pending change(s) totaling {facts['pending_change_exposure']} "
                "(execute or reject them first; the commitment must not grow after closeout)"
            )
        return problems

    def closeout(self, commitment_id: str) -> dict[str, Any]:
        """Closeout status for one commitment ("not_started" until requirements are set)."""
        c = self._commitment(commitment_id)
        co = self._closeout_row(c["id"])
        facts = self._closeout_facts(c["id"])
        requirements = [
            {"item": r["item"], "required": bool(r["required"]), "status": r["status"], "evidence_hash": r["evidence_hash"], "submitted_by": r["submitted_by"], "submitted_at": r["submitted_at"]}
            for r in self._requirement_rows(c["id"])
        ]
        status = co["status"] if co else "not_started"
        return {
            "commitment_id": c["id"],
            "commitment_title": c["title"],
            "commitment_status": c["status"],
            "closeout_id": co["id"] if co else None,
            "status": status,
            "version": co["version"] if co else 0,
            "requirements": requirements,
            "required_items": facts["requirements"],
            "missing": facts["missing"],
            "open_punch_count": facts["open_punch_count"],
            "pending_changes": facts["pending_changes"],
            "pending_change_exposure": facts["pending_change_exposure"],
            "blockers": self._closeout_problems(facts) if status != "accepted" else [],
            "ready_for_acceptance": bool(co) and status == "open" and c["status"] == "executed" and not self._closeout_problems(facts),
            "approval_id": co["approval_id"] if co else None,
            "accepted_period_id": co["accepted_period_id"] if co else None,
            "accepted_at": co["accepted_at"] if co else None,
            "acceptance_hash": co["acceptance_hash"] if co else None,
        }

    def closeout_accepted(self, commitment_id: Any) -> bool:
        """True only once ``field.accept_closeout`` executed for the commitment (the
        database admits an accepted closeout only against that consumed approval).
        ``Cipher.close_commitment`` asks this before treating a commitment as closed."""
        if not isinstance(commitment_id, str) or not commitment_id.strip():
            return False
        row = self.db.one("SELECT status, approval_id FROM field_closeouts WHERE commitment_id=?", (commitment_id.strip(),))
        if row is None or row["status"] != "accepted" or not row["approval_id"]:
            return False
        ap = self.db.one("SELECT status, operation FROM approvals WHERE id=?", (row["approval_id"],))
        return ap is not None and ap["status"] == "consumed" and ap["operation"] == OP_ACCEPT_CLOSEOUT

    # ---- approvals: manifests ------------------------------------------------------------------------ #

    def manifest_for(self, operation: str, subject_id: str, *, actor_role: str) -> dict[str, Any]:
        if operation == OP_RESPOND_RFI:
            return self._respond_manifest(subject_id, actor_role=actor_role)
        if operation == OP_DECIDE_SUBMITTAL:
            return self._decide_manifest(subject_id, actor_role=actor_role)
        if operation == OP_ACCEPT_CLOSEOUT:
            return self._closeout_manifest(subject_id, actor_role=actor_role)
        if operation == OP_DISTRIBUTE_RFI:
            return self._distribute_manifest(subject_id, actor_role=actor_role)
        raise FieldError(f"unknown field operation {operation}")

    def _distribute_manifest(self, rfi_id: str, *, actor_role: str) -> dict[str, Any]:
        r = self._rfi_row(rfi_id)
        if r["status"] != "answered":
            raise FieldStateError(f"{r['number']} is {r['status']}; only an answered RFI is distributed")
        # rebuilt from the stored list, so a hash that does not belong to it is refused
        recipients, recipients_hash = self._stored_distribution_list(r)
        dup = self._existing_distribution(r["id"], r["response_hash"], recipients_hash)
        if dup is not None:
            raise FieldStateError(f"{r['number']} response was already distributed to these recipients ({dup['id']})")
        project = self._project(r["project_id"])
        return build_manifest(
            operation=OP_DISTRIBUTE_RFI,
            subject_type=RFI_SUBJECT,
            subject_id=r["id"],
            actor_role=actor_role,
            amounts={},
            entity=project["entity"],
            bindings={
                "project_id": r["project_id"],
                "rfi_number": r["number"],
                "rfi_version": r["version"],
                "rfi_status": r["status"],
                "rfi_content_hash": r["content_hash"],
                "response_hash": r["response_hash"],
                "recipients_hash": recipients_hash,
                "recipients": recipients,
                "channel": MAIL_SINK,
                "leaves_the_prototype": False,
            },
        )

    def _respond_manifest(self, rfi_id: str, *, actor_role: str) -> dict[str, Any]:
        r = self._rfi_row(rfi_id)
        if r["status"] != "open":
            raise FieldStateError(f"{r['number']} is {r['status']}; only an open RFI can be answered")
        if r["draft_response_hash"] is None:
            raise FieldStateError(f"{r['number']} has no drafted response; draft one before requesting the official response")
        amounts = {"cost_impact": r["draft_cost_impact"]} if r["draft_cost_impact"] is not None else {}
        return build_manifest(
            operation=OP_RESPOND_RFI,
            subject_type=RFI_SUBJECT,
            subject_id=r["id"],
            actor_role=actor_role,
            amounts=amounts,
            bindings={
                "project_id": r["project_id"],
                "rfi_number": r["number"],
                "rfi_version": r["version"],
                "rfi_status": r["status"],
                "rfi_content_hash": r["content_hash"],
                "response_hash": r["draft_response_hash"],
                "cost_impact": r["draft_cost_impact"],
                "schedule_impact_days": r["draft_schedule_impact_days"],
            },
        )

    def _decide_manifest(self, revision_id: str, *, actor_role: str) -> dict[str, Any]:
        rev = self._revision_row(revision_id)
        s = self._submittal_row(rev["submittal_id"])
        if rev["status"] != "under_review":
            raise FieldStateError(f"{s['number']} revision {rev['revision']} is {rev['status']}; only a revision under review is decided")
        if rev["draft_decision"] is None:
            raise FieldStateError(f"{s['number']} revision {rev['revision']} has no recorded decision; set_decision first")
        ev =self.c.evidence.revision(rev["document_revision_id"])
        return build_manifest(
            operation=OP_DECIDE_SUBMITTAL,
            subject_type=REVISION_SUBJECT,
            subject_id=rev["id"],
            actor_role=actor_role,
            amounts={},
            bindings={
                "project_id": s["project_id"],
                "submittal_id": s["id"],
                "submittal_number": s["number"],
                "submittal_version": s["version"],
                "spec_section": s["spec_section"],
                "equipment_tag": s["equipment_tag"],
                "revision": rev["revision"],
                "revision_version": rev["version"],
                "revision_status": rev["status"],
                "document_revision_id": rev["document_revision_id"],
                "document_hash": rev["document_hash"],
                "evidence_content_hash": ev["content_hash"],
                "decision": rev["draft_decision"],
                "comments_hash": rev["draft_comments_hash"],
                "authorizes_scope_or_payment": False,
            },
        )

    def _closeout_manifest(self, commitment_id: str, *, actor_role: str) -> dict[str, Any]:
        c = self._commitment(commitment_id)
        co = self._closeout_row(c["id"])
        if co is None:
            raise FieldStateError(f"commitment {c['id']} has no closeout requirements")
        if co["status"] != "open":
            raise FieldStateError(f"the closeout of commitment {c['id']} is already {co['status']}")
        if c["status"] != "executed":
            raise FieldStateError(f"commitment {c['id']} is {c['status']}; only an executed commitment is closed out")
        facts = self._closeout_facts(c["id"])
        problems = self._closeout_problems(facts)
        if problems:
            raise FieldStateError(f"closeout of commitment {c['id']} cannot be accepted: {'; '.join(problems)}")
        return build_manifest(
            operation=OP_ACCEPT_CLOSEOUT,
            subject_type=CLOSEOUT_SUBJECT,
            subject_id=c["id"],
            actor_role=actor_role,
            amounts={"commitment_executed_amount": c["executed_amount"], "pending_change_exposure": facts["pending_change_exposure"]},
            bindings={
                "project_id": c["project_id"],
                "commitment_id": c["id"],
                "supplier_id": c["supplier_id"],
                "commitment_version": c["version"],
                "commitment_status": c["status"],
                "closeout_id": co["id"],
                "closeout_version": co["version"],
                "closeout_status": co["status"],
                "requirements": facts["requirements"],
                "submitted_evidence": facts["submitted"],
                "missing": facts["missing"],
                "open_punch_count": facts["open_punch_count"],
                "punch_hash": facts["punch_hash"],
                "pending_changes": facts["pending_changes"],
            },
        )

    # ---- approvals: execution ------------------------------------------------------------------------- #

    def apply(self, operation: str, subject_id: str, *, approval_id: str, manifest: dict[str, Any], actor: str, period_id: str | None) -> dict[str, Any]:
        if operation == OP_RESPOND_RFI:
            return self._apply_respond(subject_id, approval_id=approval_id, manifest=manifest, actor=actor)
        if operation == OP_DECIDE_SUBMITTAL:
            return self._apply_decide(subject_id, approval_id=approval_id, manifest=manifest, actor=actor)
        if operation == OP_ACCEPT_CLOSEOUT:
            return self._apply_accept(subject_id, approval_id=approval_id, manifest=manifest, actor=actor, period_id=period_id)
        if operation == OP_DISTRIBUTE_RFI:
            return self._apply_distribute(subject_id, approval_id=approval_id, manifest=manifest, actor=actor)
        raise FieldError(f"unknown field operation {operation}")

    def _apply_distribute(self, rfi_id: str, *, approval_id: str, manifest: dict[str, Any], actor: str) -> dict[str, Any]:
        """Write the mail-sink distribution row; nothing leaves the prototype."""
        with self._rfi_transaction(rfi_id) as (conn,controls):
            if controls is not None:
                checked=controls.check_native_application(approval_id,actor=actor)
                actor=checked['person']['login']
            r = self._rfi_row(rfi_id)
            if r["status"] != "answered":
                raise FieldStateError(f"{r['number']} is {r['status']}; the approval can no longer distribute it")
            # the list and its hash are rebuilt from the stored JSON, never taken on trust
            recipients, recipients_hash = self._stored_distribution_list(r)
            bound = manifest.get("bindings") or {}
            if (bound.get("recipients_hash") != recipients_hash or bound.get("recipients") != recipients
                    or bound.get("rfi_version") != r["version"] or bound.get("response_hash") != r["response_hash"]):
                raise FieldStateError(f"{r['number']} distribution list or response no longer matches the approved distribution")
            dup = self._existing_distribution(r["id"], r["response_hash"], recipients_hash)
            if dup is not None:
                raise FieldStateError(f"{r['number']} response was already distributed to these recipients ({dup['id']})")
            dist_id = new_id("rfid")
            conn.execute(
                """INSERT INTO field_rfi_distributions (id, rfi_id, rfi_version, response_hash, recipients_json, recipients_hash, channel, distributed_by, distributed_at, approval_id)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (dist_id, r["id"], r["version"], r["response_hash"], json.dumps(recipients), recipients_hash, MAIL_SINK, actor, utcnow_iso(), approval_id),
            )
            invalidated = self.approvals.invalidate_for_subject(RFI_SUBJECT, r["id"], reason=f"{r['number']} already distributed to this list", actor=actor)
            self.audit.record(actor, "field.rfi_distributed", RFI_SUBJECT, r["id"], {
                "number": r["number"], "distribution_id": dist_id, "channel": MAIL_SINK, "recipients": recipients,
                "recipients_hash": recipients_hash, "response_hash": r["response_hash"], "rfi_version": r["version"],
                "approval_id": approval_id, "approvals_invalidated": invalidated,
            })
        return self._distribution(dist_id)

    def _apply_respond(self, rfi_id: str, *, approval_id: str, manifest: dict[str, Any], actor: str) -> dict[str, Any]:
        with self._rfi_transaction(rfi_id) as (conn,controls):
            if controls is not None:
                checked=controls.check_native_application(approval_id,actor=actor)
                actor=checked['person']['login']
            r = self._rfi_row(rfi_id)
            if r["status"] != "open":
                raise FieldStateError(f"{r['number']} is {r['status']}; the approval can no longer answer it")
            bound = (manifest.get("bindings") or {}).get("response_hash")
            if r["draft_response_hash"] is None or bound != r["draft_response_hash"]:
                raise FieldStateError(f"{r['number']} draft response no longer matches the approved response")
            version = r["version"] + 1
            now = utcnow_iso()
            cur = conn.execute(
                """UPDATE field_rfis SET status='answered', response=?, cost_impact=?, schedule_impact_days=?, response_hash=?, approval_id=?,
                   answered_by=?, answered_at=?, version=?, updated_at=? WHERE id=? AND version=?""",
                (r["draft_response"], r["draft_cost_impact"], r["draft_schedule_impact_days"], r["draft_response_hash"], approval_id, actor, now, version, now, r["id"], r["version"]),
            )
            if cur.rowcount != 1:
                raise FieldStateError(f"{r['number']} changed concurrently")
            self.approvals.invalidate_for_subject(RFI_SUBJECT, r["id"], reason=f"{r['number']} already answered", actor=actor)
            self.audit.record(actor, "field.rfi_answered", RFI_SUBJECT, r["id"], {
                "number": r["number"], "approval_id": approval_id, "response_hash": r["draft_response_hash"], "cost_impact": r["draft_cost_impact"],
                "schedule_impact_days": r["draft_schedule_impact_days"], "version": version,
            })
        return {
            "rfi": r["id"], "number": r["number"], "status": "answered", "version": version, "response_hash": r["draft_response_hash"],
            "cost_impact": r["draft_cost_impact"], "schedule_impact_days": r["draft_schedule_impact_days"], "answered_at": now,
        }

    def _apply_decide(self, revision_id: str, *, approval_id: str, manifest: dict[str, Any], actor: str) -> dict[str, Any]:
        with self.db.transaction() as conn:
            rev = self._revision_row(revision_id)
            s = self._submittal_row(rev["submittal_id"])
            if rev["status"] != "under_review":
                raise FieldStateError(f"{s['number']} revision {rev['revision']} is {rev['status']}; the approval can no longer decide it")
            bindings = manifest.get("bindings") or {}
            decision = rev["draft_decision"]
            if decision is None or bindings.get("decision") != decision or bindings.get("comments_hash") != rev["draft_comments_hash"]:
                raise FieldStateError(f"{s['number']} revision {rev['revision']} decision no longer matches the approved decision")
            now = utcnow_iso()
            rev_version = rev["version"] + 1
            cur = conn.execute(
                """UPDATE field_submittal_revisions SET status=?, decision=?, comments=?, comments_hash=?, approval_id=?, decided_by=?, decided_at=?, version=?, updated_at=?
                   WHERE id=? AND version=?""",
                (decision, decision, rev["draft_comments"], rev["draft_comments_hash"], approval_id, actor, now, rev_version, now, rev["id"], rev["version"]),
            )
            if cur.rowcount != 1:
                raise FieldStateError(f"{s['number']} revision {rev['revision']} changed concurrently")
            submittal_status = SUBMITTAL_STATUS_FOR_DECISION[decision]
            submittal_version = self._bump_submittal(conn, s, status=submittal_status)
            self.approvals.invalidate_for_subject(REVISION_SUBJECT, rev["id"], reason=f"{s['number']} revision {rev['revision']} already decided", actor=actor)
            self.audit.record(actor, "field.submittal_decided", REVISION_SUBJECT, rev["id"], {
                "submittal_id": s["id"], "number": s["number"], "revision": rev["revision"], "decision": decision, "comments_hash": rev["draft_comments_hash"],
                "approval_id": approval_id, "submittal_status": submittal_status, "submittal_version": submittal_version, "journals_posted": 0,
            })
        return {
            "submittal": s["id"], "number": s["number"], "revision_id": rev["id"], "revision": rev["revision"], "decision": decision,
            "submittal_status": submittal_status, "submittal_version": submittal_version, "revision_version": rev_version,
            "journals_posted": 0, "authorizes_scope_or_payment": False,
        }

    def _apply_accept(self, commitment_id: str, *, approval_id: str, manifest: dict[str, Any], actor: str, period_id: str | None) -> dict[str, Any]:
        with self.db.transaction() as conn:
            c = self._commitment(commitment_id)
            co = self._closeout_row(c["id"])
            if co is None or co["status"] != "open":
                raise FieldStateError(f"the closeout of commitment {c['id']} is not open; the approval can no longer accept it")
            if c["status"] != "executed":
                raise FieldStateError(f"commitment {c['id']} is {c['status']}; only an executed commitment is closed out")
            facts = self._closeout_facts(c["id"])
            problems = self._closeout_problems(facts)
            if problems:
                raise FieldStateError(f"closeout of commitment {c['id']} can no longer be accepted: {'; '.join(problems)}")
            pid =period_id or self.c.current_period()["id"]
            self.ledger.require_open(pid)
            acceptance_hash = hash_json({"bindings": manifest.get("bindings"), "amounts": manifest.get("amounts")})
            now = utcnow_iso()
            version = co["version"] + 1
            cur = conn.execute(
                """UPDATE field_closeouts SET status='accepted', approval_id=?, accepted_period_id=?, acceptance_hash=?, accepted_by=?, accepted_at=?, version=?, updated_at=?
                   WHERE id=? AND version=?""",
                (approval_id, pid, acceptance_hash, actor, now, version, now, co["id"], co["version"]),
            )
            if cur.rowcount != 1:
                raise FieldStateError(f"the closeout of commitment {c['id']} changed concurrently")
            try:
                closed = self.c.commitments.close(c["id"], actor=actor)
            except CommitmentError as exc:
                raise FieldStateError(f"commitment {c['id']} could not be closed: {exc}") from exc
            self.approvals.invalidate_for_subject(CLOSEOUT_SUBJECT, c["id"], reason="closeout already accepted", actor=actor)
            self.audit.record(actor, "field.closeout_accepted", CLOSEOUT_SUBJECT, c["id"], {
                "closeout_id": co["id"], "approval_id": approval_id, "period_id": pid, "requirements": facts["requirements"],
                "submitted_evidence": facts["submitted"], "acceptance_hash": acceptance_hash, "closeout_version": version,
                "commitment_version": closed["version"],
            })
        return {
            "commitment": c["id"], "closeout": co["id"], "status": "accepted", "closeout_version": version, "commitment_status": closed["status"],
            "commitment_version": closed["version"], "period_id": pid, "requirements": facts["requirements"], "acceptance_hash": acceptance_hash,
        }

    # ---- period close and state ------------------------------------------------------------------------- #

    def close_checks(self, period_id: str) -> list[dict[str, Any]]:
        """Informational only: field records never block a period close."""
        open_rfis = self.db.scalar("SELECT COUNT(*) FROM field_rfis WHERE status='open'")
        under_review = self.db.scalar("SELECT COUNT(*) FROM field_submittal_revisions WHERE status='under_review'")
        held = self.db.scalar("SELECT COUNT(*) FROM field_hold_points WHERE status='held'")
        open_punch = self.db.scalar("SELECT COUNT(*) FROM field_punch_items WHERE status='open'")
        open_closeouts = self.db.scalar("SELECT COUNT(*) FROM field_closeouts WHERE status='open'")
        undistributed = self.db.scalar(
            "SELECT COUNT(*) FROM field_rfis r WHERE r.status='answered' AND NOT EXISTS "
            "(SELECT 1 FROM field_rfi_distributions d WHERE d.rfi_id = r.id AND d.response_hash = r.response_hash)"
        )
        return [
            {"check": "field.open_rfis", "ok": True, "detail": f"{open_rfis} open RFI(s) (informational; field records post no journals)"},
            {"check": "field.rfis_awaiting_distribution", "ok": True, "detail": f"{undistributed} answered RFI(s) not yet distributed (informational)"},
            {"check": "field.submittals_under_review", "ok": True, "detail": f"{under_review} submittal revision(s) under review (informational)"},
            {"check": "field.hold_points_held", "ok": True, "detail": f"{held} hold point(s) still held (informational)"},
            {"check": "field.open_punch_items", "ok": True, "detail": f"{open_punch} open punch item(s) (informational)"},
            {"check": "field.closeouts_pending", "ok": True, "detail": f"{open_closeouts} closeout(s) not yet accepted (informational)"},
        ]

    def audit_export(self) -> dict[str, Any]:
        """Every field record, workspace-wide, for an independent reviewer (JSON-serializable)."""
        q = self.db.query
        rfis = q("SELECT * FROM field_rfis ORDER BY project_id, sequence")
        for r in rfis:
            intact = None
            if r.get("distribution_recipients_hash") is not None:
                try:
                    self._stored_distribution_list(r)
                    intact = True
                except FieldStateError:
                    intact = False
            listed = r.pop("distribution_recipients_json", None)
            try:
                r["distribution_list"] = json.loads(listed) if listed is not None else None
            except ValueError:
                r["distribution_list"] = listed
            r["distribution_list_intact"] = intact
        distributions = q("SELECT * FROM field_rfi_distributions ORDER BY distributed_at, id")
        for d in distributions:
            d["recipients"] = json.loads(d.pop("recipients_json"))
        return {
            "rfis": rfis,
            "rfi_links": q("SELECT * FROM field_rfi_links ORDER BY created_at, id"),
            "rfi_distributions": distributions,
            "submittals": q("SELECT * FROM field_submittals ORDER BY project_id, sequence"),
            "submittal_revisions": q("SELECT * FROM field_submittal_revisions ORDER BY submittal_id, revision"),
            "hold_points": q("SELECT * FROM field_hold_points ORDER BY created_at, id"),
            "punch_items": q("SELECT * FROM field_punch_items ORDER BY project_id, sequence"),
            "closeouts": q("SELECT * FROM field_closeouts ORDER BY created_at, id"),
            "closeout_requirements": q("SELECT * FROM field_closeout_requirements ORDER BY commitment_id, item"),
        }

    def state(self, project_id: str) -> dict[str, Any]:
        """RFIs with links and distributions, submittals with revisions, hold
        points, punch items and closeout status per commitment."""
        project = self._project(project_id)
        pid = project["id"]
        rfis = self.rfis(pid)
        submittals = self.submittals(pid)
        hold_points = self.hold_points(pid)
        punch = self.punch_items(pid)
        closeouts = [self.closeout(r["id"]) for r in self.db.query("SELECT id FROM commitments WHERE project_id=? ORDER BY created_at, id", (pid,))]
        return {
            "rfis": rfis,
            "submittals": submittals,
            "hold_points": hold_points,
            "punch_items": punch,
            "closeouts": closeouts,
            "summary": {
                "rfis": len(rfis),
                "rfis_open": sum(1 for r in rfis if r["status"] == "open"),
                "rfis_answered": sum(1 for r in rfis if r["status"] == "answered"),
                "submittals": len(submittals),
                "submittals_under_review": sum(1 for s in submittals if s["status"] == "under_review"),
                "submittals_approved": sum(1 for s in submittals if s["status"] == "approved"),
                "hold_points_held": sum(1 for h in hold_points if h["status"] == "held"),
                "punch_open": sum(1 for p in punch if p["status"] == "open"),
                "closeouts_accepted": sum(1 for co in closeouts if co["status"] == "accepted"),
            },
        }

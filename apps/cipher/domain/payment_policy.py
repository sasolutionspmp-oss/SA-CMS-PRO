"""High-risk payment release policy (plan section 6, "Distinct authority states" and "Execution and recovery").

The plan asks for four things this module turns into enforced rules:

* "High-risk payments require independent release and fresh authentication."
* "Vendor bank changes require independent verification through a trusted channel" -- the
  payments module verifies the change itself; this module adds the *cooling-off* period after
  it, because a fraudulent change is usually discovered by the real payee only when an expected
  payment does not arrive.
* "Small-team staffing needs a documented owner/external-accountant control, not a hidden
  administrator bypass."  Cipher's first deployment has one owner (plan v1.1).  Two logins by
  one owner are not two-person separation, so a sole owner needs an outside party -- for
  example the external accountant -- for every independent control.  The policy *names* those
  parties, in a hash-chained version that only an owner approval can change, and a change that
  weakens it needs one of them to co-sign.  There is no override: the kill switch in the
  payments module stops releases, and the only way around this policy is a governed update.
* "Maintain a payment-release kill switch, dual-controlled emergency access": the kill switch
  stays in ``payments``; the dual control here is that loosening the release rules (the
  emergency lever an owner would reach for) needs an independent co-signature.

Governed operations
-------------------
Every operation that releases money creates a payment intent through
``Payments.create_intent``.  Its callers are the service (``payment.release`` for a posted bill,
``payment.release_retainage`` for released retainage) and the reimbursements module
(``reimbursement.pay``).  Those three are ``GOVERNED_OPERATIONS``; nothing else is governed
(``payment.adopt_transfer`` records a transfer the provider already made, and
``payment.resume_releases`` only lifts the kill switch).  The test module keeps a tripwire that
fails when a new ``create_intent`` caller appears, so a new release path cannot slip past.

Policy versions (``payment_policy.update``)
-------------------------------------------
``draft_policy`` records a pending draft of the full terms:

* ``high_risk_amount`` -- a release of at least this amount is high risk;
* ``cosign_amount`` (at least ``high_risk_amount``) -- a release of at least this amount also
  needs a co-signature;
* ``step_up_max_age_seconds`` (1 to 3600) -- how fresh the releaser's step-up must be;
* ``new_destination_cooling_days`` (0 to 90) -- the hold after an executed destination change;
* ``first_payment_to_destination_is_high_risk`` -- a destination version that has never
  received a settled payment makes the release high risk;
* ``cosign_all_high_risk`` -- every high-risk release needs a co-signature, whatever its amount;
* ``independent_parties`` -- logins of the outside parties for the solo-owner control (the
  external accountant).  When the people plugin exists and enforces identity,
  ``people.is_external(login)`` also qualifies a login (and an inactive login never qualifies).

The approval-bound operation ``payment_policy.update`` (subject: the draft; owner authority
only -- no other role holds it in ``ROLE_AUTHORITY``) binds the draft hash, the version it was
drafted against and the full terms.  Executing it appends the next version: the terms, their
hash, the previous version's hash, the draft, the approval, who adopted it, when and why, all
hashed into the version's own hash.  Adopting a version supersedes the other pending drafts and
invalidates every open release approval (each is bound to the policy version it was classified
under, so it would go stale at execution anyway) and every other open update approval.

A draft that *weakens* the current policy -- raises a threshold, lengthens the step-up age,
shortens the cooling-off, turns off the first-payment or co-sign-everything rule, adds an
independent party when the policy already names one, or removes the last one named -- needs a
co-signature (``cosign``) by an independent party of the *current* policy, distinct from the
requester, the approver and the executing login.  Without that an owner could lower the bar
alone and then release alone (or drop the outside party and name their own second login as the
"first" one).  The first version, and any change that only tightens the policy, need none.

Release rules (governor hooks)
------------------------------
With no policy recorded the plugin binds nothing and checks nothing: existing workspaces, the
golden fixture and every release made before a policy exists behave exactly as before.

Once a policy exists, ``approval_policy`` binds under ``manifest['governance']['payment_policy']``
the policy version and hash, the amount, the payee destination facts and the classification:

* ``standard`` or ``high_risk``, with its ``reasons``: ``amount_at_or_over_high_risk_amount``;
  ``first_payment_to_destination_version`` (the destination version has never received a
  settled payment, when the policy says so); ``new_destination_from_change`` (the destination
  version was set by an executed destination change and has not yet received a settled payment);
* ``cosign_required`` with ``cosign_reasons`` (``amount_at_or_over_cosign_amount``, or
  ``policy_cosigns_every_high_risk_release``);
* the destination facts: party, destination version, whether it has received a settled payment,
  and the executed change that set it (change id, executed-at and the end of its cooling-off
  window, ``executed_at + new_destination_cooling_days``).

Every fact is derived from recorded state, never from a clock reading, so an unchanged world
re-derives exactly the same facts at execution; any difference (a new policy version, a payment
that settled, a new destination change) invalidates the approval.  Whether a cooling-off window
is still running is a clock question, so it is evaluated at execution with the plugin's
injectable clock (``Plugin.now``, default ``core.ids.utcnow``).

For a high-risk release:

* ``check_grant``: the approver must be a different person from the requester (independent
  release).  A login that already co-signed the approval cannot also grant it.
* ``check_execute`` (inside the execution transaction, before the approval is consumed):
  the request and grant must be in the audit log as recorded (a raw-SQL rewrite of the
  approver is refused); the executing login (the releaser) must differ from the approver and the
  requester; when a co-signature is required, ``cosign(approval_id, cosigner, actor)`` must
  have been recorded by an independent party distinct from requester, approver and releaser,
  under the current policy version; and the releaser needs a fresh step-up authentication
  recorded with ``record_step_up(login, method, assertion_hash, actor)`` no more than
  ``step_up_max_age_seconds`` ago.  The step-up is used once: execution ties it to the approval,
  inside the same transaction, so a release that fails later (kill switch, quarantine) leaves
  it unused.
* For every governed release (standard or high risk): a destination set by an executed change
  is held until its cooling-off window has passed.  A co-signature does not override the hold;
  the approval simply stays granted until the window ends.

"Same person" compares logins without case or surrounding spaces and, when the people plugin
enforces identity, also the person each login belongs to: two logins of one owner are one
person.  Each passing execution records a clearance (classification, facts hash, the releaser,
the step-up and co-signature it used) and an audit entry.

Refusals raise ``PolicyRefused`` subclasses (``IndependenceRequired``, ``StepUpRequired``,
``CosignatureRequired``, ``CoolingOffHold``) and leave the approval granted, so the missing
piece can be supplied and the release retried.  A policy that moved since the approval raises
``StaleApprovalError`` and the approval is invalidated.

Integrity
---------
SQLite triggers keep the records honest against raw SQL: policy versions are append-only,
contiguous, chained to the previous hash and inserted only for a pending draft drafted against
the previous version, with a granted and consumed ``payment_policy.update`` approval bound to
that draft (its grant and consumption audited) and the audited adoption entry; drafts are
immutable and move only pending -> adopted / withdrawn / superseded; step-ups are recorded
unused, once per assertion, and used once by one granted release approval; co-signatures are
recorded once per approval, by the co-signer, for an open approval as requested, under the
current version; clearances only for a granted approval exactly as classified, with an
independent releaser using their own step-up and an independent co-signature when required; the
``payment_policy.update`` approvals themselves start pending, never change their manifest and
move only pending -> granted -> consumed (or expire or are invalidated); nothing is deleted or
replaced.

What a trigger cannot check -- SHA-256 -- ``verify_chain`` re-performs: every version's terms
hash, its own hash, the chain and the audited adoptions (one per version, same version and
hash, so dropping the triggers and deleting the versions is detected too).  A policy record that
fails verification refuses every governed request and execution (fail closed), and
``close_checks`` reports it, together with any governed release queued since the policy was
adopted that carries no clearance (a release that bypassed the governor).
"""
from __future__ import annotations

import datetime as _dt
import unicodedata
from decimal import Decimal
from typing import Any

from ..core.approvals import StaleApprovalError, build_manifest
from ..core.ids import canonical_json, hash_json, loads, new_id, parse_iso, sha256_hex, utcnow, utcnow_iso
from ..core.money import D, MoneyError, fmt, money

SCHEMA_NAME = "payment_policy"
PLUGIN_NAME = "payment_policy"
OP_UPDATE = "payment_policy.update"
DRAFT_SUBJECT = "payment_policy_draft"
GOVERNED_OPERATIONS = ("payment.release", "payment.release_retainage", "reimbursement.pay")
GENESIS_HASH = "0" * 64
ADOPTED_ACTION = "payment_policy.version_adopted"
COSIGNED_ACTION = "payment_policy.cosigned"
CLEARED_ACTION = "payment_policy.release_cleared"
# Phishing-resistant or possession factors only: SMS and e-mail codes are not step-up here.
STEP_UP_METHODS = ("webauthn", "security_key", "totp", "push_approval")
MAX_STEP_UP_AGE_SECONDS = 3600
MAX_COOLING_DAYS = 90
MAX_INDEPENDENT_PARTIES = 20
MAX_LOGIN_LENGTH = 128
MAX_TEXT_LENGTH = 500

REASON_AMOUNT = "amount_at_or_over_high_risk_amount"
REASON_FIRST_PAYMENT = "first_payment_to_destination_version"
REASON_CHANGED_DESTINATION = "new_destination_from_change"
COSIGN_AMOUNT = "amount_at_or_over_cosign_amount"
COSIGN_ALL = "policy_cosigns_every_high_risk_release"

TERM_KEYS = ("high_risk_amount", "cosign_amount", "step_up_max_age_seconds", "new_destination_cooling_days",
             "first_payment_to_destination_is_high_risk", "cosign_all_high_risk", "independent_parties")
VERSION_HASH_KEYS = ("version", "terms_hash", "prev_hash", "draft_id", "approval_id", "adopted_by", "adopted_at", "reason")

_GOV_SQL = "('payment.release','payment.release_retainage','reimbursement.pay')"


def _same_login_sql(a: str, b: str) -> str:
    return f"lower(trim({a})) = lower(trim({b}))"


SCHEMA_STATEMENTS = [
    # ---- tables ------------------------------------------------------------------------- #
    """CREATE TABLE payment_policy_drafts (
        id TEXT PRIMARY KEY,
        base_version INTEGER NOT NULL CHECK (base_version >= 0),
        terms_json TEXT NOT NULL CHECK (json_valid(terms_json)),
        content_hash TEXT NOT NULL CHECK (length(content_hash) = 64),
        reason TEXT NOT NULL CHECK (length(trim(reason)) > 0),
        drafted_by TEXT NOT NULL CHECK (length(trim(drafted_by)) > 0),
        drafted_at TEXT NOT NULL,
        status TEXT NOT NULL CHECK (status IN ('pending','adopted','withdrawn','superseded')),
        approval_id TEXT REFERENCES approvals(id),
        adopted_version INTEGER,
        closed_by TEXT,
        closed_at TEXT,
        closed_reason TEXT
    )""",
    "CREATE INDEX payment_policy_drafts_by_status ON payment_policy_drafts (status, drafted_at)",
    """CREATE TABLE payment_policy_versions (
        version INTEGER PRIMARY KEY CHECK (version >= 1),
        terms_json TEXT NOT NULL CHECK (json_valid(terms_json)),
        terms_hash TEXT NOT NULL CHECK (length(terms_hash) = 64),
        prev_hash TEXT NOT NULL CHECK (length(prev_hash) = 64),
        hash TEXT NOT NULL UNIQUE CHECK (length(hash) = 64),
        draft_id TEXT NOT NULL UNIQUE REFERENCES payment_policy_drafts(id),
        approval_id TEXT NOT NULL UNIQUE REFERENCES approvals(id),
        adopted_by TEXT NOT NULL CHECK (length(trim(adopted_by)) > 0),
        adopted_at TEXT NOT NULL,
        reason TEXT NOT NULL CHECK (length(trim(reason)) > 0)
    )""",
    """CREATE TABLE payment_policy_step_ups (
        id TEXT PRIMARY KEY,
        login TEXT NOT NULL CHECK (length(trim(login)) > 0),
        login_key TEXT NOT NULL CHECK (length(login_key) > 0),
        method TEXT NOT NULL CHECK (method IN ('webauthn','security_key','totp','push_approval')),
        assertion_hash TEXT NOT NULL UNIQUE CHECK (length(assertion_hash) = 64),
        recorded_by TEXT NOT NULL CHECK (length(trim(recorded_by)) > 0),
        recorded_at TEXT NOT NULL,
        approval_id TEXT UNIQUE REFERENCES approvals(id),
        used_at TEXT
    )""",
    "CREATE INDEX payment_policy_step_ups_by_login ON payment_policy_step_ups (login_key, recorded_at)",
    """CREATE TABLE payment_policy_cosignatures (
        id TEXT PRIMARY KEY,
        approval_id TEXT NOT NULL UNIQUE REFERENCES approvals(id),
        operation TEXT NOT NULL,
        approval_manifest_hash TEXT NOT NULL,
        policy_version INTEGER NOT NULL REFERENCES payment_policy_versions(version),
        cosigner TEXT NOT NULL CHECK (length(trim(cosigner)) > 0),
        recorded_by TEXT NOT NULL CHECK (length(trim(recorded_by)) > 0),
        cosigned_at TEXT NOT NULL
    )""",
    """CREATE TABLE payment_policy_clearances (
        approval_id TEXT PRIMARY KEY REFERENCES approvals(id),
        operation TEXT NOT NULL,
        classification TEXT NOT NULL CHECK (classification IN ('standard','high_risk')),
        facts_json TEXT NOT NULL CHECK (json_valid(facts_json)),
        facts_hash TEXT NOT NULL CHECK (length(facts_hash) = 64),
        policy_version INTEGER NOT NULL REFERENCES payment_policy_versions(version),
        requested_by TEXT NOT NULL,
        approver TEXT NOT NULL,
        releaser TEXT NOT NULL CHECK (length(trim(releaser)) > 0),
        step_up_id TEXT UNIQUE REFERENCES payment_policy_step_ups(id),
        cosignature_id TEXT UNIQUE REFERENCES payment_policy_cosignatures(id),
        cleared_at TEXT NOT NULL
    )""",
    # ---- drafts ------------------------------------------------------------------------- #
    """CREATE TRIGGER payment_policy_drafts_born_pending BEFORE INSERT ON payment_policy_drafts
        BEGIN SELECT CASE
          WHEN EXISTS (SELECT 1 FROM payment_policy_drafts WHERE id = NEW.id)
            THEN RAISE(ABORT, 'payment policy drafts are never replaced')
          WHEN NEW.status IS NOT 'pending' OR NEW.approval_id IS NOT NULL OR NEW.adopted_version IS NOT NULL
            OR NEW.closed_by IS NOT NULL OR NEW.closed_at IS NOT NULL OR NEW.closed_reason IS NOT NULL
            THEN RAISE(ABORT, 'a payment policy draft is recorded only as a pending proposal')
          WHEN NOT EXISTS (SELECT 1 FROM audit_log g WHERE g.entity_type = 'payment_policy_draft' AND g.entity_id = NEW.id
                             AND g.action = 'payment_policy.drafted' AND json_extract(g.payload_json, '$.content_hash') = NEW.content_hash)
            THEN RAISE(ABORT, 'a payment policy draft is recorded only through draft_policy, which audits its content hash')
        END; END""",
    """CREATE TRIGGER payment_policy_drafts_content_immutable
        BEFORE UPDATE OF id, base_version, terms_json, content_hash, reason, drafted_by, drafted_at ON payment_policy_drafts
        WHEN NEW.id IS NOT OLD.id OR NEW.base_version IS NOT OLD.base_version OR NEW.terms_json IS NOT OLD.terms_json
          OR NEW.content_hash IS NOT OLD.content_hash OR NEW.reason IS NOT OLD.reason OR NEW.drafted_by IS NOT OLD.drafted_by
          OR NEW.drafted_at IS NOT OLD.drafted_at
        BEGIN SELECT RAISE(ABORT, 'a payment policy draft is immutable; withdraw it and draft another'); END""",
    """CREATE TRIGGER payment_policy_drafts_lifecycle BEFORE UPDATE ON payment_policy_drafts
        WHEN NOT (
            (OLD.status = 'pending' AND NEW.status = 'adopted' AND NEW.approval_id IS NOT NULL AND NEW.adopted_version IS NOT NULL
             AND NEW.closed_by IS NULL AND NEW.closed_at IS NULL AND NEW.closed_reason IS NULL
             AND EXISTS (SELECT 1 FROM payment_policy_versions v WHERE v.draft_id = NEW.id AND v.approval_id = NEW.approval_id
                         AND v.version = NEW.adopted_version))
         OR (OLD.status = 'pending' AND NEW.status IN ('withdrawn','superseded') AND NEW.approval_id IS NULL AND NEW.adopted_version IS NULL
             AND length(trim(COALESCE(NEW.closed_by, ''))) > 0 AND NEW.closed_at IS NOT NULL
             AND length(trim(COALESCE(NEW.closed_reason, ''))) > 0))
        BEGIN SELECT RAISE(ABORT, 'a payment policy draft moves once, from pending to adopted (by the version its consumed approval adopted) or to withdrawn or superseded'); END""",
    "CREATE TRIGGER payment_policy_drafts_no_delete BEFORE DELETE ON payment_policy_drafts BEGIN SELECT RAISE(ABORT, 'payment policy drafts are never deleted'); END",
    # ---- versions ----------------------------------------------------------------------- #
    f"""CREATE TRIGGER payment_policy_versions_governed BEFORE INSERT ON payment_policy_versions
        BEGIN SELECT CASE
          WHEN EXISTS (SELECT 1 FROM payment_policy_versions v WHERE v.version = NEW.version OR v.hash = NEW.hash
                         OR v.draft_id = NEW.draft_id OR v.approval_id = NEW.approval_id)
            THEN RAISE(ABORT, 'payment policy versions are append-only: a stored version already has this number, hash, draft or approval')
          WHEN NEW.version IS NOT COALESCE((SELECT MAX(version) FROM payment_policy_versions), 0) + 1
            THEN RAISE(ABORT, 'a payment policy version appends the next version number only')
          WHEN NEW.prev_hash IS NOT COALESCE((SELECT hash FROM payment_policy_versions WHERE version = NEW.version - 1), '{GENESIS_HASH}')
            THEN RAISE(ABORT, 'a payment policy version chains to the hash of the version before it')
          WHEN NOT EXISTS (SELECT 1 FROM payment_policy_drafts d WHERE d.id = NEW.draft_id AND d.status = 'pending'
                             AND d.base_version = NEW.version - 1 AND d.terms_json = NEW.terms_json AND d.content_hash = NEW.terms_hash)
            THEN RAISE(ABORT, 'a payment policy version adopts exactly the terms of a pending draft prepared against the version before it')
          WHEN NOT EXISTS (SELECT 1 FROM approvals a WHERE a.id = NEW.approval_id AND a.operation = 'payment_policy.update'
                             AND a.status = 'consumed' AND a.subject_type = 'payment_policy_draft' AND a.subject_id = NEW.draft_id
                             AND a.approver IS NOT NULL AND a.granted_at IS NOT NULL AND a.consumed_at IS NOT NULL AND a.consumed_by IS NOT NULL
                             AND json_valid(a.manifest_json)
                             AND json_extract(a.manifest_json, '$.bindings.draft_hash') = NEW.terms_hash
                             AND json_extract(a.manifest_json, '$.bindings.base_version') = NEW.version - 1
                             AND (json_extract(a.manifest_json, '$.bindings.cosign_required') IS NOT 1
                                  OR EXISTS (SELECT 1 FROM payment_policy_cosignatures c WHERE c.approval_id = a.id
                                             AND NOT {_same_login_sql('c.cosigner', 'a.requested_by')}
                                             AND NOT {_same_login_sql('c.cosigner', 'a.approver')}
                                             AND NOT {_same_login_sql('c.cosigner', 'a.consumed_by')}))
                             AND EXISTS (SELECT 1 FROM audit_log g WHERE g.entity_type = 'approval' AND g.entity_id = a.id AND g.action = 'approval.granted')
                             AND EXISTS (SELECT 1 FROM audit_log g WHERE g.entity_type = 'approval' AND g.entity_id = a.id AND g.action = 'approval.consumed'))
            THEN RAISE(ABORT, 'a payment policy version is adopted only through a granted and consumed payment_policy.update approval bound to its draft (co-signed when it weakens the policy)')
          WHEN NOT EXISTS (SELECT 1 FROM audit_log g WHERE g.entity_type = 'payment_policy' AND g.entity_id = NEW.draft_id
                             AND g.action = '{ADOPTED_ACTION}' AND json_extract(g.payload_json, '$.version') = NEW.version
                             AND json_extract(g.payload_json, '$.hash') = NEW.hash)
            THEN RAISE(ABORT, 'a payment policy version is adopted only through payment_policy.update, which audits its version and hash')
        END; END""",
    "CREATE TRIGGER payment_policy_versions_no_update BEFORE UPDATE ON payment_policy_versions BEGIN SELECT RAISE(ABORT, 'payment policy versions are append-only'); END",
    "CREATE TRIGGER payment_policy_versions_no_delete BEFORE DELETE ON payment_policy_versions BEGIN SELECT RAISE(ABORT, 'payment policy versions are append-only'); END",
    # ---- step-ups ----------------------------------------------------------------------- #
    """CREATE TRIGGER payment_policy_step_ups_born_unused BEFORE INSERT ON payment_policy_step_ups
        BEGIN SELECT CASE
          WHEN EXISTS (SELECT 1 FROM payment_policy_step_ups s WHERE s.id = NEW.id OR s.assertion_hash = NEW.assertion_hash)
            THEN RAISE(ABORT, 'a step-up assertion is recorded once and never replaced')
          WHEN NEW.approval_id IS NOT NULL OR NEW.used_at IS NOT NULL
            THEN RAISE(ABORT, 'a step-up authentication is recorded unused')
        END; END""",
    f"""CREATE TRIGGER payment_policy_step_ups_used_once BEFORE UPDATE ON payment_policy_step_ups
        WHEN NOT (NEW.id IS OLD.id AND NEW.login IS OLD.login AND NEW.login_key IS OLD.login_key AND NEW.method IS OLD.method
                  AND NEW.assertion_hash IS OLD.assertion_hash AND NEW.recorded_by IS OLD.recorded_by AND NEW.recorded_at IS OLD.recorded_at
                  AND OLD.approval_id IS NULL AND OLD.used_at IS NULL AND NEW.approval_id IS NOT NULL AND NEW.used_at IS NOT NULL
                  AND EXISTS (SELECT 1 FROM approvals a WHERE a.id = NEW.approval_id AND a.status = 'granted' AND a.operation IN {_GOV_SQL}))
        BEGIN SELECT RAISE(ABORT, 'a step-up authentication is used once, by the execution of one granted release approval, and is otherwise immutable'); END""",
    "CREATE TRIGGER payment_policy_step_ups_no_delete BEFORE DELETE ON payment_policy_step_ups BEGIN SELECT RAISE(ABORT, 'step-up authentications are never deleted'); END",
    # ---- co-signatures ------------------------------------------------------------------ #
    f"""CREATE TRIGGER payment_policy_cosignatures_recorded BEFORE INSERT ON payment_policy_cosignatures
        BEGIN SELECT CASE
          WHEN EXISTS (SELECT 1 FROM payment_policy_cosignatures c WHERE c.id = NEW.id OR c.approval_id = NEW.approval_id)
            THEN RAISE(ABORT, 'an approval carries one co-signature, never replaced')
          WHEN NOT {_same_login_sql('NEW.cosigner', 'NEW.recorded_by')}
            THEN RAISE(ABORT, 'a co-signature is recorded by the co-signer themselves')
          WHEN NOT EXISTS (SELECT 1 FROM approvals a WHERE a.id = NEW.approval_id AND a.status IN ('pending','granted')
                             AND a.operation = NEW.operation AND a.manifest_hash = NEW.approval_manifest_hash
                             AND (a.operation IN {_GOV_SQL} OR a.operation = 'payment_policy.update')
                             AND NOT {_same_login_sql('a.requested_by', 'NEW.cosigner')}
                             AND (a.approver IS NULL OR NOT {_same_login_sql('a.approver', 'NEW.cosigner')}))
            THEN RAISE(ABORT, 'a co-signature names an open release or policy-update approval, as requested, by someone other than its requester and approver')
          WHEN NEW.policy_version IS NOT (SELECT MAX(version) FROM payment_policy_versions)
            THEN RAISE(ABORT, 'a co-signature is given under the current payment policy version')
          WHEN NOT EXISTS (SELECT 1 FROM audit_log g WHERE g.entity_type = 'approval' AND g.entity_id = NEW.approval_id
                             AND g.action = '{COSIGNED_ACTION}' AND json_extract(g.payload_json, '$.cosignature_id') = NEW.id)
            THEN RAISE(ABORT, 'a co-signature is recorded only through cosign, which audits it')
        END; END""",
    "CREATE TRIGGER payment_policy_cosignatures_no_update BEFORE UPDATE ON payment_policy_cosignatures BEGIN SELECT RAISE(ABORT, 'co-signatures are immutable'); END",
    "CREATE TRIGGER payment_policy_cosignatures_no_delete BEFORE DELETE ON payment_policy_cosignatures BEGIN SELECT RAISE(ABORT, 'co-signatures are never deleted'); END",
    # ---- clearances --------------------------------------------------------------------- #
    f"""CREATE TRIGGER payment_policy_clearances_recorded BEFORE INSERT ON payment_policy_clearances
        BEGIN SELECT CASE
          WHEN EXISTS (SELECT 1 FROM payment_policy_clearances k WHERE k.approval_id = NEW.approval_id
                         OR (NEW.step_up_id IS NOT NULL AND k.step_up_id = NEW.step_up_id)
                         OR (NEW.cosignature_id IS NOT NULL AND k.cosignature_id = NEW.cosignature_id))
            THEN RAISE(ABORT, 'a release is cleared once and its clearance is never replaced')
          WHEN NOT EXISTS (SELECT 1 FROM approvals a WHERE a.id = NEW.approval_id AND a.status = 'granted' AND a.operation = NEW.operation
                             AND a.operation IN {_GOV_SQL} AND a.requested_by IS NEW.requested_by AND a.approver IS NEW.approver
                             AND json_valid(a.manifest_json)
                             AND json_extract(a.manifest_json, '$.governance.payment_policy.classification') IS NEW.classification
                             AND json_extract(a.manifest_json, '$.governance.payment_policy.policy_version') IS NEW.policy_version)
            THEN RAISE(ABORT, 'a clearance names a granted release approval exactly as the payment policy classified it')
          WHEN NEW.classification = 'high_risk' AND (
                {_same_login_sql('NEW.releaser', 'NEW.approver')} OR {_same_login_sql('NEW.releaser', 'NEW.requested_by')}
                OR {_same_login_sql('NEW.approver', 'NEW.requested_by')}
                OR NOT EXISTS (SELECT 1 FROM payment_policy_step_ups s WHERE s.id = NEW.step_up_id AND s.approval_id = NEW.approval_id
                               AND {_same_login_sql('s.login', 'NEW.releaser')}))
            THEN RAISE(ABORT, 'a high-risk release is cleared only for an independent approver and releaser, with the releaser''s own step-up used for it')
          WHEN (SELECT json_extract(a.manifest_json, '$.governance.payment_policy.cosign_required') FROM approvals a WHERE a.id = NEW.approval_id) = 1
               AND NOT EXISTS (SELECT 1 FROM payment_policy_cosignatures c WHERE c.id = NEW.cosignature_id AND c.approval_id = NEW.approval_id
                               AND NOT {_same_login_sql('c.cosigner', 'NEW.releaser')} AND NOT {_same_login_sql('c.cosigner', 'NEW.approver')}
                               AND NOT {_same_login_sql('c.cosigner', 'NEW.requested_by')})
            THEN RAISE(ABORT, 'a release that needs a co-signature is cleared only with an independent co-signature on that approval')
          WHEN NOT EXISTS (SELECT 1 FROM audit_log g WHERE g.entity_type = 'approval' AND g.entity_id = NEW.approval_id
                             AND g.action = '{CLEARED_ACTION}' AND json_extract(g.payload_json, '$.facts_hash') = NEW.facts_hash
                             AND json_extract(g.payload_json, '$.releaser') = NEW.releaser)
            THEN RAISE(ABORT, 'a clearance is recorded only through the release check, which audits it')
        END; END""",
    "CREATE TRIGGER payment_policy_clearances_no_update BEFORE UPDATE ON payment_policy_clearances BEGIN SELECT RAISE(ABORT, 'release clearances are immutable'); END",
    "CREATE TRIGGER payment_policy_clearances_no_delete BEFORE DELETE ON payment_policy_clearances BEGIN SELECT RAISE(ABORT, 'release clearances are never deleted'); END",
    # ---- the payment_policy.update approvals themselves ----------------------------------- #
    """CREATE TRIGGER payment_policy_update_approval_starts_pending BEFORE INSERT ON approvals
        WHEN NEW.operation = 'payment_policy.update' AND (NEW.status IS NOT 'pending' OR NEW.approver IS NOT NULL OR NEW.granted_at IS NOT NULL
             OR NEW.consumed_at IS NOT NULL OR NEW.consumed_by IS NOT NULL)
        BEGIN SELECT RAISE(ABORT, 'a payment_policy.update approval is recorded only as a pending request'); END""",
    """CREATE TRIGGER payment_policy_update_approval_no_replace BEFORE INSERT ON approvals
        WHEN EXISTS (SELECT 1 FROM approvals a WHERE a.operation = 'payment_policy.update' AND (a.id = NEW.id OR a.nonce = NEW.nonce))
        BEGIN SELECT RAISE(ABORT, 'payment_policy.update approvals are never replaced'); END""",
    """CREATE TRIGGER payment_policy_update_approval_lifecycle BEFORE UPDATE ON approvals
        WHEN (OLD.operation = 'payment_policy.update' OR NEW.operation = 'payment_policy.update') AND (
            NEW.id IS NOT OLD.id OR NEW.operation IS NOT OLD.operation OR NEW.subject_type IS NOT OLD.subject_type OR NEW.subject_id IS NOT OLD.subject_id
            OR NEW.actor_role IS NOT OLD.actor_role OR NEW.manifest_json IS NOT OLD.manifest_json OR NEW.manifest_hash IS NOT OLD.manifest_hash
            OR NEW.material_hash IS NOT OLD.material_hash OR NEW.policy_version IS NOT OLD.policy_version OR NEW.nonce IS NOT OLD.nonce
            OR NEW.requested_by IS NOT OLD.requested_by OR NEW.requested_at IS NOT OLD.requested_at OR NEW.expires_at IS NOT OLD.expires_at
            OR NOT (
                (NEW.status = OLD.status AND OLD.status != 'consumed' AND NEW.approver IS OLD.approver AND NEW.granted_at IS OLD.granted_at
                    AND NEW.consumed_at IS OLD.consumed_at AND NEW.consumed_by IS OLD.consumed_by)
                OR (OLD.status = 'pending' AND NEW.status = 'granted' AND NEW.approver IS NOT NULL AND NEW.granted_at IS NOT NULL
                    AND NEW.consumed_at IS NULL AND NEW.consumed_by IS NULL)
                OR (OLD.status = 'granted' AND NEW.status = 'consumed' AND NEW.consumed_at IS NOT NULL AND NEW.consumed_by IS NOT NULL
                    AND NEW.approver IS OLD.approver AND NEW.granted_at IS OLD.granted_at)
                OR (OLD.status IN ('pending','granted') AND NEW.status = 'expired' AND NEW.approver IS OLD.approver
                    AND NEW.granted_at IS OLD.granted_at AND NEW.consumed_at IS NULL AND NEW.consumed_by IS NULL)
                OR (OLD.status IN ('pending','granted','expired','invalidated') AND NEW.status = 'invalidated' AND NEW.approver IS OLD.approver
                    AND NEW.granted_at IS OLD.granted_at AND NEW.consumed_at IS NULL AND NEW.consumed_by IS NULL)))
        BEGIN SELECT RAISE(ABORT, 'payment_policy.update approvals move only pending -> granted -> consumed (or expire or are invalidated) and their manifest never changes'); END""",
    """CREATE TRIGGER payment_policy_update_approval_no_delete BEFORE DELETE ON approvals
        WHEN OLD.operation = 'payment_policy.update'
        BEGIN SELECT RAISE(ABORT, 'payment_policy.update approvals are never deleted'); END""",
]


# --------------------------------------------------------------------------- #
# Errors                                                                       #
# --------------------------------------------------------------------------- #

class PaymentPolicyError(RuntimeError):
    """Invalid policy input, or an action the policy's records do not allow."""


class PolicyIntegrityError(PaymentPolicyError):
    """The policy record (or an approval it governs) fails verification: governed requests and
    executions are refused until it is restored."""


class DraftStale(PaymentPolicyError, StaleApprovalError):
    """The draft no longer applies (the policy moved, or the draft closed).  At execution this is
    a ``StaleApprovalError``, so the service invalidates the approval durably."""


class PolicyRefused(PaymentPolicyError, PermissionError):
    """The release policy refuses this grant, co-signature or execution.  The approval stays
    as it was, so the missing control can be supplied and the step retried."""


class IndependenceRequired(PolicyRefused):
    """Requester, approver, releaser and co-signer must be different people."""


class StepUpRequired(PolicyRefused):
    """The releaser has no fresh, unused step-up authentication."""


class CosignatureRequired(PolicyRefused):
    """The release (or policy update) needs a co-signature by an independent party."""


class CoolingOffHold(PolicyRefused):
    """The payee destination was changed within the cooling-off window."""


# --------------------------------------------------------------------------- #
# Validation helpers                                                           #
# --------------------------------------------------------------------------- #

def _norm(login: str) -> str:
    """Identity of a login for comparisons: Unicode-normalized, trimmed, case-folded."""
    return unicodedata.normalize("NFKC", str(login)).strip().casefold()


def _login(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PaymentPolicyError(f"{label} is required")
    text = value.strip()
    if len(text) > MAX_LOGIN_LENGTH:
        raise PaymentPolicyError(f"{label} is longer than {MAX_LOGIN_LENGTH} characters")
    if any(ord(ch) < 32 or ch in '"\\' for ch in text):
        raise PaymentPolicyError(f"{label} {text!r} may not contain quotes, backslashes or control characters")
    return text


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PaymentPolicyError(f"{label} is required")
    text = value.strip()
    if len(text) > MAX_TEXT_LENGTH:
        raise PaymentPolicyError(f"{label} is longer than {MAX_TEXT_LENGTH} characters")
    return text


def _threshold(value: Any, label: str) -> Decimal:
    """A positive amount in whole cents; floats, booleans, non-finite and sub-cent values are refused, not rounded."""
    try:
        raw = D(value)
        amount = money(raw)
    except (MoneyError, ArithmeticError) as exc:
        raise PaymentPolicyError(f"{label} is not exact money: {exc}") from exc
    if amount != raw:
        raise PaymentPolicyError(f"{label} must be in whole cents, got {value!r}")
    if amount <= 0:
        raise PaymentPolicyError(f"{label} must be positive, got {fmt(amount)}")
    return amount


def _whole(value: Any, label: str, low: int, high: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise PaymentPolicyError(f"{label} must be a whole number, got {value!r}")
    if value < low or value > high:
        raise PaymentPolicyError(f"{label} must be between {low} and {high}, got {value}")
    return value


def _flag(value: Any, label: str) -> bool:
    if not isinstance(value, bool):
        raise PaymentPolicyError(f"{label} must be true or false, got {value!r}")
    return value


def _parties(value: Any) -> list[str]:
    if isinstance(value, (str, bytes)) or not isinstance(value, (list, tuple)):
        raise PaymentPolicyError("independent_parties must be a list of logins")
    if len(value) > MAX_INDEPENDENT_PARTIES:
        raise PaymentPolicyError(f"independent_parties lists more than {MAX_INDEPENDENT_PARTIES} logins")
    out: dict[str, str] = {}
    for item in value:
        login = _login(item, "independent party")
        key = _norm(login)
        if key in out:
            raise PaymentPolicyError(f"independent party {login!r} is listed twice")
        out[key] = login
    return [out[k] for k in sorted(out)]


def build_terms(*, high_risk_amount: Any, cosign_amount: Any, step_up_max_age_seconds: Any, new_destination_cooling_days: Any,
                first_payment_to_destination_is_high_risk: Any, cosign_all_high_risk: Any, independent_parties: Any) -> dict[str, Any]:
    """Validate and canonicalise the policy terms (the dict a draft and a version store)."""
    high = _threshold(high_risk_amount, "high_risk_amount")
    cosign = _threshold(cosign_amount, "cosign_amount")
    if cosign < high:
        raise PaymentPolicyError(f"cosign_amount {fmt(cosign)} must be at least high_risk_amount {fmt(high)}")
    return {
        "high_risk_amount": fmt(high),
        "cosign_amount": fmt(cosign),
        "step_up_max_age_seconds": _whole(step_up_max_age_seconds, "step_up_max_age_seconds", 1, MAX_STEP_UP_AGE_SECONDS),
        "new_destination_cooling_days": _whole(new_destination_cooling_days, "new_destination_cooling_days", 0, MAX_COOLING_DAYS),
        "first_payment_to_destination_is_high_risk": _flag(first_payment_to_destination_is_high_risk, "first_payment_to_destination_is_high_risk"),
        "cosign_all_high_risk": _flag(cosign_all_high_risk, "cosign_all_high_risk"),
        "independent_parties": _parties(independent_parties),
    }


def weakenings(old: dict[str, Any] | None, new: dict[str, Any]) -> list[str]:
    """How ``new`` loosens ``old`` (empty when ``old`` is None or ``new`` only tightens it).
    Adding an independent party loosens the policy (one more login that can co-sign) only when
    the policy already names one; naming the first is how the control is set up.  Removing the
    last one loosens it too: otherwise the outside party could be dropped and a new "first" one
    named in its place, with nobody independent co-signing either step."""
    if old is None:
        return []
    out = []
    if D(new["high_risk_amount"]) > D(old["high_risk_amount"]):
        out.append("high_risk_amount_raised")
    if D(new["cosign_amount"]) > D(old["cosign_amount"]):
        out.append("cosign_amount_raised")
    if new["step_up_max_age_seconds"] > old["step_up_max_age_seconds"]:
        out.append("step_up_max_age_lengthened")
    if new["new_destination_cooling_days"] < old["new_destination_cooling_days"]:
        out.append("cooling_off_shortened")
    if old["first_payment_to_destination_is_high_risk"] and not new["first_payment_to_destination_is_high_risk"]:
        out.append("first_payment_rule_turned_off")
    if old["cosign_all_high_risk"] and not new["cosign_all_high_risk"]:
        out.append("cosign_all_high_risk_turned_off")
    old_parties = {_norm(p) for p in old["independent_parties"]}
    added = sorted(p for p in new["independent_parties"] if _norm(p) not in old_parties)
    if added and old_parties:
        out.append("independent_party_added:" + ",".join(added))
    if old_parties and not new["independent_parties"]:
        out.append("independent_parties_removed:" + ",".join(sorted(old["independent_parties"])))
    return out


def _version_hash(row: dict[str, Any]) -> str:
    return hash_json({k: row[k] for k in VERSION_HASH_KEYS})


def _iso(moment: _dt.datetime) -> str:
    return moment.astimezone(_dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _utc(moment: _dt.datetime) -> _dt.datetime:
    return moment.replace(tzinfo=_dt.timezone.utc) if moment.tzinfo is None or moment.utcoffset() is None else moment


def _check(name: str, ok: bool, detail: str) -> dict[str, Any]:
    """A close-checklist row: the close module and Ricky's brief read ``check``; ``name`` is the same label."""
    return {"check": name, "name": name, "ok": ok is True, "detail": detail}


# --------------------------------------------------------------------------- #
# Plugin                                                                       #
# --------------------------------------------------------------------------- #

class Plugin:
    GOVERNOR = True

    def __init__(self, cipher):
        self.c = cipher
        self.db = cipher.db
        self.audit = cipher.audit
        self.approvals = cipher.approvals
        # The clock windows and step-up freshness are evaluated with.  Tests move time by
        # replacing it; recorded facts (bound into approvals) never come from it.
        self.now = utcnow

    # ---- clock and identity ---------------------------------------------------------- #

    def _now(self) -> _dt.datetime:
        moment = self.now()
        if not isinstance(moment, _dt.datetime):
            raise PaymentPolicyError(f"the policy clock returned {type(moment).__name__}, not a datetime")
        return _utc(moment)

    def _people(self) -> Any | None:
        """The people plugin when it exists and enforces identity, else None."""
        people = self.c._plugins.get("people")
        enforcing = getattr(people, "enforcing", None)
        if not callable(enforcing):
            return None
        try:
            return people if enforcing() is True else None
        except Exception:
            return None

    @staticmethod
    def _person_key(person: Any) -> str | None:
        if isinstance(person, dict):
            for key in ("person_id", "id"):
                if person.get(key):
                    return str(person[key])
        return None

    def same_person(self, a: str | None, b: str | None) -> bool:
        """Whether two logins belong to one person: the same login (case and surrounding spaces
        ignored), or -- when the people plugin enforces identity -- logins of the same person."""
        if not a or not b:
            return False
        if _norm(a) == _norm(b):
            return True
        people = self._people()
        if people is None:
            return False
        try:
            ka, kb = self._person_key(people.person_for(a)), self._person_key(people.person_for(b))
        except Exception:
            return False
        return ka is not None and ka == kb

    def is_independent(self, login: str, policy: dict[str, Any] | None = None) -> bool:
        """Whether ``login`` is an independent party under ``policy`` (default: the current one):
        listed in its ``independent_parties``, or external per an enforcing people plugin.  With
        an enforcing people plugin an inactive login never qualifies."""
        policy = policy if policy is not None else self._policy()
        if policy is None:
            return False
        listed = _norm(login) in {_norm(p) for p in policy["terms"]["independent_parties"]}
        people = self._people()
        if people is not None:
            try:
                if people.is_active(login) is not True:
                    return False
                if not listed:
                    listed = people.is_external(login) is True
            except Exception:
                return False
        return listed

    # ---- policy record ------------------------------------------------------------------ #

    def _adoption_entries(self) -> list[dict[str, Any]]:
        return self.db.query("SELECT seq, entity_id, payload_json FROM audit_log WHERE action=? ORDER BY seq", (ADOPTED_ACTION,))

    def verify_chain(self) -> dict[str, Any]:
        """Re-perform what the triggers cannot: each version's terms hash and own hash, the chain
        from the genesis hash, contiguous numbering, well-formed terms, and one audited adoption
        per version with the same version and hash (so versions deleted with the triggers dropped
        are detected too)."""
        rows = self.db.query("SELECT * FROM payment_policy_versions ORDER BY version")
        problems: list[str] = []
        prev = GENESIS_HASH
        for expected, row in enumerate(rows, 1):
            label = f"version {row['version']}"
            if row["version"] != expected:
                problems.append(f"{label}: versions are not numbered contiguously from 1")
            try:
                terms = loads(row["terms_json"])
                if canonical_json(terms) != row["terms_json"] or sha256_hex(row["terms_json"]) != row["terms_hash"]:
                    problems.append(f"{label}: its terms do not match their hash")
                elif build_terms(**{k: terms[k] for k in TERM_KEYS}) != terms or set(terms) != set(TERM_KEYS):
                    problems.append(f"{label}: its terms are not a valid policy")
            except Exception as exc:  # unreadable terms are a verification failure, not a crash
                problems.append(f"{label}: its terms cannot be read ({type(exc).__name__}: {exc})")
            if row["prev_hash"] != prev:
                problems.append(f"{label}: does not chain to the hash of the version before it")
            if row["hash"] != _version_hash(row):
                problems.append(f"{label}: its stored hash does not match its contents")
            prev = row["hash"]
        adoptions = self._adoption_entries()
        if len(adoptions) != len(rows):
            problems.append(f"the audit log records {len(adoptions)} policy adoption(s) but {len(rows)} version(s) are stored")
        for row, entry in zip(rows, adoptions):
            payload = loads(entry["payload_json"]) or {}
            if payload.get("version") != row["version"] or payload.get("hash") != row["hash"]:
                problems.append(f"version {row['version']}: differs from its audited adoption")
        return {"ok": not problems, "versions": len(rows), "head": rows[-1]["hash"] if rows else None, "problems": problems}

    @staticmethod
    def _version_out(row: dict[str, Any]) -> dict[str, Any]:
        out = {k: row[k] for k in ("version", "hash", "prev_hash", "terms_hash", "draft_id", "approval_id", "adopted_by", "adopted_at", "reason")}
        out["terms"] = loads(row["terms_json"])
        return out

    def _policy(self) -> dict[str, Any] | None:
        """The current policy version, None when none was ever adopted.  A record that fails
        verification raises ``PolicyIntegrityError``: governed actions fail closed."""
        chain = self.verify_chain()
        if not chain["ok"]:
            raise PolicyIntegrityError("the payment release policy record fails verification, so governed releases are refused until it is "
                                       "restored: " + "; ".join(chain["problems"][:3]))
        if chain["versions"] == 0:
            return None
        return self._version_out(self.db.one("SELECT * FROM payment_policy_versions ORDER BY version DESC LIMIT 1"))

    def policy(self) -> dict[str, Any] | None:
        """The current policy version (terms, hashes, who adopted it, when and why), or None."""
        return self._policy()

    def versions(self) -> list[dict[str, Any]]:
        return [self._version_out(r) for r in self.db.query("SELECT * FROM payment_policy_versions ORDER BY version")]

    def _configured(self) -> bool:
        return bool(self.db.scalar("SELECT COUNT(*) FROM payment_policy_versions")) or bool(self._adoption_entries())

    # ---- drafts ------------------------------------------------------------------------- #

    def _draft_row(self, draft_id: Any) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM payment_policy_drafts WHERE id=?", (draft_id,)) if isinstance(draft_id, str) else None
        if row is None:
            raise PaymentPolicyError(f"unknown payment policy draft {draft_id}")
        return row

    def draft(self, draft_id: str) -> dict[str, Any]:
        row = dict(self._draft_row(draft_id))
        row["terms"] = loads(row.pop("terms_json"))
        return row

    def drafts(self, *, status: str | None = None) -> list[dict[str, Any]]:
        if status:
            rows = self.db.query("SELECT id FROM payment_policy_drafts WHERE status=? ORDER BY drafted_at, id", (status,))
        else:
            rows = self.db.query("SELECT id FROM payment_policy_drafts ORDER BY drafted_at, id")
        return [self.draft(r["id"]) for r in rows]

    def draft_policy(self, *, high_risk_amount: Any, cosign_amount: Any, step_up_max_age_seconds: Any, new_destination_cooling_days: Any,
                     first_payment_to_destination_is_high_risk: Any, independent_parties: Any, reason: str, actor: str,
                     cosign_all_high_risk: Any = False) -> dict[str, Any]:
        """Record a pending draft of the full policy terms against the current version.  Nothing
        changes until the owner executes ``payment_policy.update`` on it."""
        actor = _login(actor, "actor")
        reason = _text(reason, "reason")
        terms = build_terms(high_risk_amount=high_risk_amount, cosign_amount=cosign_amount, step_up_max_age_seconds=step_up_max_age_seconds,
                            new_destination_cooling_days=new_destination_cooling_days,
                            first_payment_to_destination_is_high_risk=first_payment_to_destination_is_high_risk,
                            cosign_all_high_risk=cosign_all_high_risk, independent_parties=independent_parties)
        terms_json = canonical_json(terms)
        content_hash = sha256_hex(terms_json)
        draft_id = new_id("ppd")
        with self.db.transaction() as conn:
            current = self._policy()
            if current is not None and current["terms_hash"] == content_hash:
                raise PaymentPolicyError(f"the draft repeats payment policy version {current['version']}; nothing would change")
            base = current["version"] if current else 0
            self.audit.record(actor, "payment_policy.drafted", DRAFT_SUBJECT, draft_id, {
                "base_version": base, "content_hash": content_hash, "terms": terms, "reason": reason,
                "weakens": weakenings(current["terms"] if current else None, terms),
            })
            conn.execute(
                "INSERT INTO payment_policy_drafts (id, base_version, terms_json, content_hash, reason, drafted_by, drafted_at, status) VALUES (?,?,?,?,?,?,?,'pending')",
                (draft_id, base, terms_json, content_hash, reason, actor, utcnow_iso()),
            )
        return self.draft(draft_id)

    def withdraw_draft(self, draft_id: str, reason: str, actor: str) -> dict[str, Any]:
        """Close a pending draft; any open approval on it is invalidated."""
        actor = _login(actor, "actor")
        reason = _text(reason, "reason")
        with self.db.transaction() as conn:
            row = self._draft_row(draft_id)
            if row["status"] != "pending":
                raise PaymentPolicyError(f"payment policy draft {draft_id} is {row['status']}, not pending")
            conn.execute("UPDATE payment_policy_drafts SET status='withdrawn', closed_by=?, closed_at=?, closed_reason=? WHERE id=?",
                         (actor, utcnow_iso(), reason, draft_id))
            invalidated = self.approvals.invalidate_for_subject(DRAFT_SUBJECT, draft_id, reason=f"payment policy draft withdrawn: {reason}", actor=actor)
            self.audit.record(actor, "payment_policy.draft_withdrawn", DRAFT_SUBJECT, draft_id, {"reason": reason, "approvals_invalidated": invalidated})
        return self.draft(draft_id)

    # ---- payment_policy.update ---------------------------------------------------------- #

    def manifest_for(self, operation: str, subject_id: str, *, actor_role: str) -> dict[str, Any]:
        if operation != OP_UPDATE:
            raise PaymentPolicyError(f"unknown payment policy operation {operation}")
        row = self._draft_row(subject_id)
        if row["status"] != "pending":
            raise DraftStale(f"payment policy draft {subject_id} is {row['status']}, not pending")
        current = self._policy()
        base = current["version"] if current else 0
        if row["base_version"] != base:
            raise DraftStale(f"payment policy draft {subject_id} was drafted against version {row['base_version']}, but the policy is now at "
                             f"version {base}; draft again against the current version")
        terms = loads(row["terms_json"])
        weak = weakenings(current["terms"] if current else None, terms)
        return build_manifest(
            operation=OP_UPDATE,
            subject_type=DRAFT_SUBJECT,
            subject_id=row["id"],
            actor_role=actor_role,
            bindings={
                "draft_id": row["id"], "draft_hash": row["content_hash"], "base_version": base,
                "base_hash": current["hash"] if current else GENESIS_HASH, "terms": terms, "reason": row["reason"],
                "drafted_by": row["drafted_by"], "weakens": weak, "cosign_required": bool(weak),
                "cosigners_allowed": current["terms"]["independent_parties"] if (current and weak) else [],
            },
        )

    def apply(self, operation: str, subject_id: str, *, approval_id: str, manifest: dict[str, Any], actor: str, period_id: str | None) -> dict[str, Any]:
        if operation != OP_UPDATE:
            raise PaymentPolicyError(f"unknown payment policy operation {operation}")
        bound = manifest.get("bindings") or {}
        with self.db.transaction() as conn:
            row = self._draft_row(subject_id)
            current = self._policy()
            base = current["version"] if current else 0
            if row["status"] != "pending" or row["base_version"] != base or bound.get("base_version") != base or row["content_hash"] != bound.get("draft_hash"):
                raise DraftStale(f"payment policy draft {subject_id} no longer matches the approved update")
            if bound.get("cosign_required"):
                self._require_update_cosignature(approval_id, current, actor)
            version = base + 1
            record = {
                "version": version, "terms_json": row["terms_json"], "terms_hash": row["content_hash"],
                "prev_hash": current["hash"] if current else GENESIS_HASH, "draft_id": row["id"], "approval_id": approval_id,
                "adopted_by": _login(actor, "actor"), "adopted_at": utcnow_iso(), "reason": row["reason"],
            }
            record["hash"] = _version_hash(record)
            self.audit.record(actor, ADOPTED_ACTION, "payment_policy", row["id"], {
                "version": version, "hash": record["hash"], "prev_hash": record["prev_hash"], "terms_hash": record["terms_hash"],
                "approval_id": approval_id, "weakens": bound.get("weakens") or [],
            })
            conn.execute(
                "INSERT INTO payment_policy_versions (version, terms_json, terms_hash, prev_hash, hash, draft_id, approval_id, adopted_by, adopted_at, reason) VALUES (?,?,?,?,?,?,?,?,?,?)",
                tuple(record[k] for k in ("version", "terms_json", "terms_hash", "prev_hash", "hash", "draft_id", "approval_id", "adopted_by", "adopted_at", "reason")),
            )
            conn.execute("UPDATE payment_policy_drafts SET status='adopted', approval_id=?, adopted_version=? WHERE id=?", (approval_id, version, row["id"]))
            superseded = []
            now = utcnow_iso()
            for other in self.db.query("SELECT id FROM payment_policy_drafts WHERE status='pending' ORDER BY drafted_at, id"):
                conn.execute("UPDATE payment_policy_drafts SET status='superseded', closed_by=?, closed_at=?, closed_reason=? WHERE id=?",
                             (actor, now, f"superseded by payment policy version {version}", other["id"]))
                superseded.append(other["id"])
            invalidated = []
            for ap in self.approvals.list(status="pending") + self.approvals.list(status="granted"):
                if ap["id"] != approval_id and (ap["operation"] in GOVERNED_OPERATIONS or ap["operation"] == OP_UPDATE):
                    self.approvals.invalidate(ap["id"], reason=f"payment release policy moved to version {version}; request a fresh approval", actor=actor)
                    invalidated.append(ap["id"])
            if superseded or invalidated:
                self.audit.record(actor, "payment_policy.open_items_closed", "payment_policy", row["id"], {
                    "version": version, "superseded_drafts": superseded, "invalidated_approvals": invalidated,
                })
        return {"payment_policy_version": version, "hash": record["hash"], "prev_hash": record["prev_hash"], "draft": row["id"],
                "weakens": bound.get("weakens") or [], "superseded_drafts": superseded, "invalidated_approvals": invalidated}

    def _require_update_cosignature(self, approval_id: str, current: dict[str, Any] | None, actor: str) -> None:
        ap = self.approvals.get(approval_id)
        sig = self.db.one("SELECT * FROM payment_policy_cosignatures WHERE approval_id=?", (approval_id,))
        if current is None or sig is None:
            allowed = ", ".join(current["terms"]["independent_parties"]) if current else "none"
            raise CosignatureRequired(f"this update weakens payment policy version {current['version'] if current else 0} "
                                      f"({', '.join((ap['manifest'].get('bindings') or {}).get('weakens') or [])}); it needs a co-signature by an "
                                      f"independent party of the current policy ({allowed}) before it is executed")
        if sig["approval_manifest_hash"] != ap["manifest_hash"] or sig["policy_version"] != current["version"]:
            raise PolicyIntegrityError(f"the co-signature on approval {approval_id} does not match the approval or the current policy version")
        if not self.is_independent(sig["cosigner"], current):
            raise CosignatureRequired(f"{sig['cosigner']!r} is no longer an independent party of payment policy version {current['version']}")
        for role, login in (("requester", ap["requested_by"]), ("approver", ap["approver"]), ("executing login", actor)):
            if self.same_person(sig["cosigner"], login):
                raise IndependenceRequired(f"the co-signer {sig['cosigner']!r} is also the {role} of this policy update")

    # ---- governor hooks ------------------------------------------------------------------ #

    def _has_table(self, name: str) -> bool:
        return self.db.one("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,)) is not None

    def _classify(self, policy: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any]:
        terms = policy["terms"]
        try:
            amount = money((manifest.get("amounts") or {})["amount"])
        except (KeyError, TypeError, MoneyError) as exc:
            raise PaymentPolicyError(f"a release manifest must carry its exact amount: {exc}") from exc
        dest = manifest.get("destination") or {}
        party_id, version = dest.get("party_id"), dest.get("destination_version")
        if not party_id or version is None:
            raise PaymentPolicyError("a release manifest must name its payee destination and version")
        settled = bool(self.db.scalar("SELECT COUNT(*) FROM payment_intents WHERE party_id=? AND destination_version=? AND status='settled'", (party_id, version)))
        change = None
        if self._has_table("destination_changes"):
            row = self.db.one(
                "SELECT id, executed_at FROM destination_changes WHERE party_id=? AND status='executed' AND new_destination_version=? ORDER BY executed_at DESC, id DESC LIMIT 1",
                (party_id, version),
            )
            if row is not None and row["executed_at"]:
                until = parse_iso(row["executed_at"]) + _dt.timedelta(days=terms["new_destination_cooling_days"])
                change = {"change_id": row["id"], "executed_at": row["executed_at"], "cooling_off_until": _iso(_utc(until))}
        reasons = []
        if amount >= D(terms["high_risk_amount"]):
            reasons.append(REASON_AMOUNT)
        if terms["first_payment_to_destination_is_high_risk"] and not settled:
            reasons.append(REASON_FIRST_PAYMENT)
        if change is not None and not settled:
            reasons.append(REASON_CHANGED_DESTINATION)
        high = bool(reasons)
        cosign_reasons = []
        if amount >= D(terms["cosign_amount"]):
            cosign_reasons.append(COSIGN_AMOUNT)
        if high and terms["cosign_all_high_risk"]:
            cosign_reasons.append(COSIGN_ALL)
        facts = {
            "policy_version": policy["version"], "policy_hash": policy["hash"],
            "classification": "high_risk" if high else "standard", "reasons": reasons,
            "cosign_required": bool(cosign_reasons), "cosign_reasons": cosign_reasons,
            "amount": fmt(amount),
            "destination": {"party_id": party_id, "destination_version": version, "has_settled_payment": settled, "change": change},
        }
        if high:
            facts["requires"] = ["independent_approval", "independent_release", "fresh_step_up"] + (["independent_cosignature"] if cosign_reasons else [])
        return facts

    def approval_policy(self, operation: str, manifest: dict[str, Any]) -> dict[str, Any] | None:
        """Facts bound under ``manifest['governance']['payment_policy']`` for a release; None (bind
        nothing) for other operations and while no policy has been adopted."""
        if operation not in GOVERNED_OPERATIONS:
            return None
        policy = self._policy()
        if policy is None:
            return None
        return self._classify(policy, manifest)

    @staticmethod
    def _facts(approval_or_manifest: dict[str, Any]) -> dict[str, Any] | None:
        manifest = approval_or_manifest.get("manifest", approval_or_manifest) if isinstance(approval_or_manifest, dict) else {}
        return ((manifest or {}).get("governance") or {}).get(PLUGIN_NAME)

    def check_request(self, operation: str, manifest: dict[str, Any], *, actor_role: str, requested_by: str) -> None:
        """Refuse a release that needs a co-signature nobody could give (no independent party
        named and no enforcing people registry to name external ones)."""
        if operation not in GOVERNED_OPERATIONS:
            return
        facts = self._facts(manifest)
        if not facts or not facts.get("cosign_required"):
            return
        policy = self._policy()
        if policy is not None and not policy["terms"]["independent_parties"] and self._people() is None:
            raise CosignatureRequired(f"this release needs an independent co-signature ({', '.join(facts['cosign_reasons'])}), but payment policy "
                                      f"version {policy['version']} names no independent party; adopt a policy that names the outside party first")

    def check_grant(self, approval: dict[str, Any], *, approver: str, approver_role: str) -> None:
        """Independent approval of a high-risk release: the approver is not the requester (nor a
        login of the same person), and not the approval's co-signer."""
        if approval.get("operation") not in GOVERNED_OPERATIONS:
            return
        facts = self._facts(approval)
        if not facts:
            return
        policy = self._policy()
        if policy is None or policy["version"] != facts.get("policy_version") or policy["hash"] != facts.get("policy_hash"):
            self.approvals.invalidate(approval["id"], reason="the payment release policy changed after the request", actor=approver)
            raise StaleApprovalError(f"approval {approval['id']} was classified under payment policy version {facts.get('policy_version')}; "
                                     "request a fresh approval")
        if facts.get("classification") != "high_risk":
            return
        if self.same_person(approver, approval.get("requested_by")):
            raise IndependenceRequired(
                f"a high-risk release ({', '.join(facts['reasons'])}) needs an approver other than its requester {approval.get('requested_by')!r}; "
                "two logins of one person are not two-person separation, so a sole owner needs an outside party")
        sig = self.db.one("SELECT cosigner FROM payment_policy_cosignatures WHERE approval_id=?", (approval["id"],))
        if sig is not None and self.same_person(approver, sig["cosigner"]):
            raise IndependenceRequired(f"{approver!r} co-signed this release and cannot also approve it")

    def _require_recorded(self, ap: dict[str, Any]) -> None:
        """The approval's requester and approver must be the ones the audit log recorded."""
        rows = self.db.query("SELECT action, actor FROM audit_log WHERE entity_type='approval' AND entity_id=? AND action IN ('approval.requested','approval.granted') ORDER BY seq",
                             (ap["id"],))
        requested = [r["actor"] for r in rows if r["action"] == "approval.requested"]
        granted = [r["actor"] for r in rows if r["action"] == "approval.granted"]
        if requested != [ap["requested_by"]] or granted != [ap["approver"]]:
            raise PolicyIntegrityError(f"approval {ap['id']}'s requester or approver does not match the audit log (requested by {requested}, granted by "
                                       f"{granted}); the release is refused")

    def _fresh_step_up(self, login: str, policy: dict[str, Any], now: _dt.datetime) -> dict[str, Any]:
        max_age = policy["terms"]["step_up_max_age_seconds"]
        unused = self.db.query("SELECT * FROM payment_policy_step_ups WHERE login_key=? AND approval_id IS NULL ORDER BY recorded_at DESC, id DESC", (_norm(login),))
        newest_age = None
        for row in unused:
            age = (now - _utc(parse_iso(row["recorded_at"]))).total_seconds()
            if age < 0:
                continue  # recorded "after" the clock's now: not evidence of a fresh authentication
            if age <= max_age:
                return row
            newest_age = age if newest_age is None else min(newest_age, age)
            break
        if newest_age is not None:
            raise StepUpRequired(f"the latest unused step-up for {login!r} is {int(newest_age)} seconds old; payment policy version {policy['version']} "
                                 f"accepts at most {max_age}; authenticate again (record_step_up) and retry")
        used = self.db.scalar("SELECT COUNT(*) FROM payment_policy_step_ups WHERE login_key=? AND approval_id IS NOT NULL", (_norm(login),))
        if used:
            raise StepUpRequired(f"every step-up recorded for {login!r} has already been used for a release; each release needs a fresh one")
        raise StepUpRequired(f"a high-risk release needs a fresh step-up authentication by the releaser {login!r} (record_step_up)")

    def _valid_cosignature(self, ap: dict[str, Any], policy: dict[str, Any], releaser: str, facts: dict[str, Any]) -> dict[str, Any]:
        sig = self.db.one("SELECT * FROM payment_policy_cosignatures WHERE approval_id=?", (ap["id"],))
        if sig is None:
            parties = ", ".join(policy["terms"]["independent_parties"]) or "none listed"
            raise CosignatureRequired(f"this release needs a co-signature by an independent party ({', '.join(facts['cosign_reasons'])}; "
                                      f"independent parties: {parties}) before it is released")
        if sig["approval_manifest_hash"] != ap["manifest_hash"] or sig["operation"] != ap["operation"]:
            raise PolicyIntegrityError(f"the co-signature on approval {ap['id']} does not match the approval as requested")
        if sig["policy_version"] != policy["version"]:
            raise CosignatureRequired(f"the co-signature on approval {ap['id']} was given under policy version {sig['policy_version']}; co-sign again")
        if not self.is_independent(sig["cosigner"], policy):
            raise CosignatureRequired(f"{sig['cosigner']!r} is not an independent party of payment policy version {policy['version']}")
        for role, login in (("requester", ap["requested_by"]), ("approver", ap["approver"]), ("releaser", releaser)):
            if self.same_person(sig["cosigner"], login):
                raise IndependenceRequired(f"the co-signer {sig['cosigner']!r} is also the {role} of this release")
        return sig

    def check_execute(self, approval: dict[str, Any], manifest: dict[str, Any], *, actor: str) -> None:
        """Enforce the release rules inside the execution transaction (see the module docstring).
        Writes (the step-up's use and the clearance) commit only with the release itself."""
        if approval.get("operation") not in GOVERNED_OPERATIONS:
            return
        facts = self._facts(manifest)
        if facts is None:
            return  # no policy: nothing to check (the service already compared the bound governance)
        if not self.db.in_transaction:
            raise PaymentPolicyError("the release check runs only inside the execution transaction")
        ap = self.approvals.get(approval["id"])
        if ap["status"] != "granted":
            return  # consuming it raises the precise error (consumed, expired, invalidated)
        if self._facts(ap) != facts:
            raise StaleApprovalError(f"approval {ap['id']} no longer matches the payment policy facts it was granted under")
        policy = self._policy()
        if policy is None or policy["version"] != facts["policy_version"] or policy["hash"] != facts["policy_hash"]:
            raise StaleApprovalError(f"approval {ap['id']} was classified under payment policy version {facts['policy_version']}; request a fresh approval")
        now = self._now()
        change = (facts.get("destination") or {}).get("change")
        if change and now < parse_iso(change["cooling_off_until"]):
            raise CoolingOffHold(f"payee {facts['destination']['party_id']}'s destination was changed by {change['change_id']} at {change['executed_at']}; "
                                 f"releases to it are held until {change['cooling_off_until']} (a co-signature does not lift the hold)")
        releaser = _login(actor, "releasing login")
        step = sig = None
        if facts["classification"] == "high_risk":
            self._require_recorded(ap)
            if self.same_person(ap["approver"], ap["requested_by"]):
                raise IndependenceRequired(f"approval {ap['id']} was granted by its own requester; a high-risk release needs an independent approver")
            for role, login in (("approver", ap["approver"]), ("requester", ap["requested_by"])):
                if self.same_person(releaser, login):
                    raise IndependenceRequired(f"the releasing login {releaser!r} is also the {role} of this high-risk release; "
                                               "release it from an independent login")
            if facts["cosign_required"]:
                sig = self._valid_cosignature(ap, policy, releaser, facts)
            step = self._fresh_step_up(releaser, policy, now)
            used = self.db.execute("UPDATE payment_policy_step_ups SET approval_id=?, used_at=? WHERE id=? AND approval_id IS NULL",
                                   (ap["id"], _iso(now), step["id"])).rowcount
            if used != 1:
                raise StepUpRequired(f"step-up {step['id']} was used concurrently; authenticate again")
        facts_hash = hash_json(facts)
        cleared_at = _iso(now)
        self.audit.record(releaser, CLEARED_ACTION, "approval", ap["id"], {
            "operation": ap["operation"], "classification": facts["classification"], "reasons": facts["reasons"], "facts_hash": facts_hash,
            "policy_version": policy["version"], "releaser": releaser, "step_up_id": step["id"] if step else None,
            "cosignature_id": sig["id"] if sig else None,
        })
        self.db.execute(
            """INSERT INTO payment_policy_clearances (approval_id, operation, classification, facts_json, facts_hash, policy_version, requested_by,
               approver, releaser, step_up_id, cosignature_id, cleared_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (ap["id"], ap["operation"], facts["classification"], canonical_json(facts), facts_hash, policy["version"], ap["requested_by"],
             ap["approver"], releaser, step["id"] if step else None, sig["id"] if sig else None, cleared_at),
        )

    # ---- step-up and co-signature ---------------------------------------------------------- #

    def record_step_up(self, login: str, method: str, assertion_hash: str, actor: str) -> dict[str, Any]:
        """Record that ``login`` just completed a step-up authentication (``method`` one of
        ``STEP_UP_METHODS``).  Only the SHA-256 of the authenticator's assertion is stored, and an
        assertion is accepted once (a replayed one is refused).  ``actor`` is whoever records it
        (the sign-in service).  The step-up is fresh for the policy's ``step_up_max_age_seconds``
        and is consumed by the first high-risk release that login executes."""
        login = _login(login, "login")
        actor = _login(actor, "actor")
        if method not in STEP_UP_METHODS:
            raise PaymentPolicyError(f"step-up method must be one of {', '.join(STEP_UP_METHODS)}, got {method!r}")
        if not isinstance(assertion_hash, str) or len(assertion_hash.strip()) != 64 or any(ch not in "0123456789abcdef" for ch in assertion_hash.strip().lower()):
            raise PaymentPolicyError("assertion_hash must be the 64-character hex SHA-256 of the authenticator assertion")
        assertion_hash = assertion_hash.strip().lower()
        people = self._people()
        if people is not None:
            try:
                active = people.is_active(login) is True
            except Exception:
                active = False
            if not active:
                raise PolicyRefused(f"{login!r} is not an active person in the people registry")
        step_id = new_id("psu")
        recorded_at = _iso(self._now())
        with self.db.transaction() as conn:
            if conn.execute("SELECT 1 FROM payment_policy_step_ups WHERE assertion_hash=?", (assertion_hash,)).fetchone():
                raise PolicyRefused("that step-up assertion was already recorded; a replayed assertion is not a fresh authentication")
            conn.execute(
                "INSERT INTO payment_policy_step_ups (id, login, login_key, method, assertion_hash, recorded_by, recorded_at) VALUES (?,?,?,?,?,?,?)",
                (step_id, login, _norm(login), method, assertion_hash, actor, recorded_at),
            )
            self.audit.record(actor, "payment_policy.step_up_recorded", "payment_policy_step_up", step_id, {"login": login, "method": method, "recorded_at": recorded_at})
        return self.db.one("SELECT * FROM payment_policy_step_ups WHERE id=?", (step_id,))

    def step_ups(self, login: str | None = None) -> list[dict[str, Any]]:
        if login:
            return self.db.query("SELECT * FROM payment_policy_step_ups WHERE login_key=? ORDER BY recorded_at, id", (_norm(login),))
        return self.db.query("SELECT * FROM payment_policy_step_ups ORDER BY recorded_at, id")

    def cosign(self, approval_id: str, cosigner: str, actor: str) -> dict[str, Any]:
        """Record an independent party's co-signature on an open approval that needs one (a
        release whose policy facts say ``cosign_required``, or a weakening policy update).  The
        co-signer records it themselves (``actor`` is the same login); they must be an independent
        party of the current policy and a different person from the requester and the approver.
        One co-signature per approval."""
        cosigner = _login(cosigner, "cosigner")
        actor = _login(actor, "actor")
        if _norm(actor) != _norm(cosigner):
            raise PolicyRefused(f"a co-signature is recorded by the co-signer themselves, not by {actor!r} on their behalf")
        with self.db.transaction() as conn:
            ap = self.approvals.get(approval_id)
            if ap["status"] not in ("pending", "granted"):
                raise PaymentPolicyError(f"approval {approval_id} is {ap['status']}; only an open approval can be co-signed")
            policy = self._policy()
            if policy is None:
                raise PaymentPolicyError("no payment release policy is recorded, so nothing needs a co-signature")
            if ap["operation"] in GOVERNED_OPERATIONS:
                facts = self._facts(ap)
                if not facts:
                    raise PaymentPolicyError(f"approval {approval_id} was requested before the payment policy existed; request a fresh approval")
                if facts.get("policy_version") != policy["version"]:
                    raise PaymentPolicyError(f"approval {approval_id} was classified under payment policy version {facts.get('policy_version')}; "
                                             "request a fresh approval")
                if not facts.get("cosign_required"):
                    raise PaymentPolicyError(f"approval {approval_id} does not need a co-signature under payment policy version {policy['version']}")
            elif ap["operation"] == OP_UPDATE:
                if not (ap["manifest"].get("bindings") or {}).get("cosign_required"):
                    raise PaymentPolicyError(f"policy update {approval_id} does not weaken the policy and needs no co-signature")
            else:
                raise PaymentPolicyError(f"{ap['operation']} is not governed by the payment release policy")
            if not self.is_independent(cosigner, policy):
                raise IndependenceRequired(f"{cosigner!r} is not an independent party of payment policy version {policy['version']} "
                                           f"(independent parties: {', '.join(policy['terms']['independent_parties']) or 'none listed'})")
            for role, login in (("requester", ap["requested_by"]), ("approver", ap.get("approver"))):
                if self.same_person(cosigner, login):
                    raise IndependenceRequired(f"{cosigner!r} is the {role} of approval {approval_id} and cannot also co-sign it")
            if conn.execute("SELECT 1 FROM payment_policy_cosignatures WHERE approval_id=?", (approval_id,)).fetchone():
                raise PaymentPolicyError(f"approval {approval_id} is already co-signed")
            sig_id = new_id("pcs")
            at = _iso(self._now())
            self.audit.record(actor, COSIGNED_ACTION, "approval", approval_id, {
                "cosignature_id": sig_id, "cosigner": cosigner, "operation": ap["operation"], "manifest_hash": ap["manifest_hash"], "policy_version": policy["version"],
            })
            conn.execute(
                "INSERT INTO payment_policy_cosignatures (id, approval_id, operation, approval_manifest_hash, policy_version, cosigner, recorded_by, cosigned_at) VALUES (?,?,?,?,?,?,?,?)",
                (sig_id, approval_id, ap["operation"], ap["manifest_hash"], policy["version"], cosigner, actor, at),
            )
        return self.db.one("SELECT * FROM payment_policy_cosignatures WHERE id=?", (sig_id,))

    def cosignatures(self) -> list[dict[str, Any]]:
        return self.db.query("SELECT * FROM payment_policy_cosignatures ORDER BY cosigned_at, id")

    def clearances(self) -> list[dict[str, Any]]:
        rows = self.db.query("SELECT * FROM payment_policy_clearances ORDER BY cleared_at, approval_id")
        for r in rows:
            r["facts"] = loads(r.pop("facts_json"))
        return rows

    # ---- reporting -------------------------------------------------------------------------- #

    def _open_governed(self, project_id: str | None = None) -> list[tuple[dict[str, Any], dict[str, Any]]]:
        out = []
        for ap in self.approvals.list(status="pending") + self.approvals.list(status="granted"):
            if ap["operation"] not in GOVERNED_OPERATIONS:
                continue
            facts = self._facts(ap)
            if not facts:
                continue
            if project_id is not None and (ap["manifest"].get("bindings") or {}).get("project_id") not in (None, project_id):
                continue
            out.append((ap, facts))
        return out

    def _open_items(self, project_id: str | None = None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """High-risk approvals still waiting for a control, and releases held in cooling-off."""
        try:
            now = self._now()
        except PaymentPolicyError:
            now = utcnow()
        cosigned = {r["approval_id"] for r in self.db.query("SELECT approval_id FROM payment_policy_cosignatures")}
        awaiting, holds = [], []
        for ap, facts in self._open_governed(project_id):
            base = {"approval_id": ap["id"], "operation": ap["operation"], "subject": ap["manifest"].get("subject"), "amount": facts.get("amount"),
                    "status": ap["status"], "classification": facts.get("classification"), "reasons": facts.get("reasons"),
                    "requested_by": ap["requested_by"], "approver": ap.get("approver")}
            if facts.get("classification") == "high_risk":
                waiting = []
                if ap["status"] == "pending":
                    waiting.append("independent approval")
                if facts.get("cosign_required") and ap["id"] not in cosigned:
                    waiting.append("independent co-signature")
                if ap["status"] == "granted":
                    waiting.append("fresh step-up and independent release")
                awaiting.append(dict(base, waiting_for=waiting))
            change = (facts.get("destination") or {}).get("change")
            if change and now < parse_iso(change["cooling_off_until"]):
                holds.append(dict(base, party_id=facts["destination"]["party_id"], change_id=change["change_id"], cooling_off_until=change["cooling_off_until"]))
        return awaiting, holds

    def _uncleared_releases(self) -> list[dict[str, Any]]:
        """Governed releases queued since the first policy adoption that carry no clearance: a
        payment intent created outside the governed execution path."""
        first = self.db.scalar("SELECT MIN(seq) FROM audit_log WHERE action=?", (ADOPTED_ACTION,))
        if first is None:
            return []
        queued = {r["entity_id"] for r in self.db.query("SELECT entity_id FROM audit_log WHERE action='payment.queued' AND entity_type='payment_intent' AND seq > ?", (first,))}
        if not queued:
            return []
        rows = self.db.query(
            f"""SELECT i.id AS intent_id, i.approval_id, i.amount, a.operation FROM payment_intents i JOIN approvals a ON a.id = i.approval_id
                WHERE a.operation IN {_GOV_SQL} AND NOT EXISTS (SELECT 1 FROM payment_policy_clearances k WHERE k.approval_id = i.approval_id)
                ORDER BY i.created_at, i.id""")
        return [r for r in rows if r["intent_id"] in queued]

    def close_checks(self, period_id: str) -> list[dict[str, Any]]:
        """Nothing while no policy was ever adopted.  Otherwise: the policy record and every
        release since adoption are intact (fails on tampering or an uncleared release), plus
        informational counts of high-risk approvals waiting for a control and of releases held
        in cooling-off (approvals are entity-wide, so they are not limited to ``period_id``)."""
        if not self._configured():
            return []
        chain = self.verify_chain()
        uncleared = self._uncleared_releases()
        problems = list(chain["problems"]) + [f"payment intent {u['intent_id']} ({u['operation']}, {u['amount']}) was queued without a payment-policy clearance"
                                              for u in uncleared]
        detail = ("; ".join(problems[:5]) if problems
                  else f"{chain['versions']} hash-chained policy version(s) verified; every governed release since adoption was cleared")
        awaiting, holds = self._open_items()
        cosign = sum(1 for a in awaiting if "independent co-signature" in a["waiting_for"])
        return [
            _check("payment_policy records intact", not problems, detail),
            _check("payment_policy high-risk releases awaiting a control (informational)", True,
                   f"{len(awaiting)} high-risk release approval(s) open, {cosign} awaiting an independent co-signature"),
            _check("payment_policy releases held in cooling-off (informational)", True,
                   f"{len(holds)} release approval(s) held after a payee destination change"
                   + (f" (earliest hold ends {min(h['cooling_off_until'] for h in holds)})" if holds else "")),
        ]

    def state(self, project_id: str | None) -> dict[str, Any]:
        out: dict[str, Any] = {"governed_operations": list(GOVERNED_OPERATIONS), "configured": self._configured()}
        chain = self.verify_chain()
        out["integrity"] = {"ok": chain["ok"], "versions": chain["versions"], "head": chain["head"], "problems": chain["problems"]}
        out["policy"] = self._version_out(self.db.one("SELECT * FROM payment_policy_versions ORDER BY version DESC LIMIT 1")) if chain["ok"] and chain["versions"] else None
        out["pending_drafts"] = self.drafts(status="pending")
        if not out["configured"]:
            out["note"] = "no payment release policy has been adopted; releases follow the approval rules alone"
            return out
        uncleared = self._uncleared_releases()
        out["integrity"]["uncleared_releases"] = uncleared
        out["integrity"]["ok"] = chain["ok"] and not uncleared
        awaiting, holds = self._open_items(project_id)
        out["awaiting_controls"] = awaiting
        out["cooling_off_holds"] = holds
        clearances = self.clearances()
        if project_id is not None:
            ids = {ap["id"] for ap in self.approvals.list(status="consumed") if (ap["manifest"].get("bindings") or {}).get("project_id") == project_id}
            clearances = [k for k in clearances if k["approval_id"] in ids]
        out["clearances"] = clearances
        return out

    def audit_export(self) -> dict[str, Any]:
        return {
            "governed_operations": list(GOVERNED_OPERATIONS),
            "integrity": self.verify_chain(),
            "uncleared_releases": self._uncleared_releases(),
            "versions": self.db.query("SELECT * FROM payment_policy_versions ORDER BY version"),
            "drafts": self.db.query("SELECT * FROM payment_policy_drafts ORDER BY drafted_at, id"),
            "step_ups": self.step_ups(),
            "cosignatures": self.cosignatures(),
            "clearances": self.clearances(),
        }

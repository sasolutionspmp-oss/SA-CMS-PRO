"""Identity and authority registry: people, service identities, role grants, delegations,
project membership and identity policy versions (plan section 5 "Identity and authority",
section 6 "Distinct authority states"; v1.1 solo-first correction).

Why it exists.  Until this module, a role was whatever the caller named: ``approve(approver=
"owner", approver_role="owner")`` was believed.  The plan separates preparer, project approver,
accountant/poster, bank-detail maintainer, treasury releaser and reconciler, and says a system
administrator can never silently grant themselves business approval rights.  The v1.1
correction adds that two logins by one owner are not two-person separation: a sole owner needs
an outside party (for example an external accountant) for independent controls.  This registry
records who exists, which roles each identity holds and why, and -- once an identity policy
that enforces is adopted -- makes every approval in Cipher answer to it.

Records (all append-only or forward-only, guarded by SQLite triggers)::

    people_persons            login (unique, normalized), display name, kind person|service,
                              external flag (an outside party), status active|inactive
    people_memberships        a person on one project (needed for project-scoped authority)
    people_grant_requests     a pending grant: person, role (a ROLE_AUTHORITY key), scope (the
                              entity or one project), effective from/to dates, reason
    people_grants             the grants themselves, hash-chained (seq, prev_hash, content_hash);
                              each names the consumed approval that created it, or is the single
                              owner bootstrap; revoked only by a consumed revocation approval
    people_revocation_requests  a pending revocation of one grant
    people_delegations        one role from one person to another, for a window and a scope
    people_policy_drafts      a proposed identity policy
    people_policy_versions    adopted identity policies, hash-chained, never changed
    people_self_approvals     each solo-owner self-approval, and its review by an outside party

Approval-bound operations (owner authority: only ROLE_AUTHORITY's ``'*'`` holds them)::

    people.grant_role   subject: a pending grant request      -> the grant is recorded
    people.revoke_role  subject: a pending revocation request -> the grant is revoked
    people.delegate     subject: a pending delegation         -> the delegation is active
    people.set_policy   subject: a pending policy draft       -> the next policy version

Record methods: ``register_person``, ``deactivate_person`` (reduces privilege, so it is
effective immediately and audited), ``add_membership`` / ``end_membership``,
``request_grant``, ``request_revocation``, ``request_delegation``, ``revoke_delegation``
(immediate), ``prepare_policy``, ``cancel_request``, ``review_self_approval`` and
``bootstrap_owner``.

Rules that always hold (they concern this module's own operations, so they apply whether or
not a policy enforces):

* No self-granting.  A person never decides their own authority: a grant, revocation or
  delegation whose subject is a person can be neither requested, approved nor executed by that
  person -- even by the owner.  The grant table's insert guard re-checks the approval row.
* Grants: the role must be a ROLE_AUTHORITY key; ``owner`` is granted at entity scope only and
  never to a service identity or an outside party; a project-scoped grant needs the person to be
  a member of the project (and stops counting when the membership ends); grants of one role in
  one scope never overlap in time.
* Delegations: never the owner role, never to a service identity, always for a window (an end
  date is required), and no re-delegation -- the delegator must hold the role by their own grant
  (an owner grant carries every role), never by another delegation.  A delegation counts only
  while its delegator still holds the role by grant and is active.
* ``bootstrap_owner`` runs exactly once, only while no active person holds owner and identity
  enforcement is off.
* Enabling enforcement needs at least one active owner whose owner grant has no end date; with
  segregation it also needs an active person other than the requester (for a sole owner: the
  outside party); with solo-owner self-approval it needs an active outside party to review the
  exceptions.
* While a policy enforces, deactivating or revoking the last active owner is refused (the
  workspace could not be governed afterwards), and so is removing the last active owner whose
  owner grant has no end date: an owner grant with an end date lapses on its own.

Authority.  ``holds(login, role, project_id=None)`` is true when the identity is active and
holds the role by a live grant (entity scope, or the project's scope while a member), or by an
active delegation in scope.  The owner role carries every role (ROLE_AUTHORITY gives it
``'*'``), so an active owner holds every role -- the solo-first reading of "a sole owner holds
every role".  Without a project, only entity-scoped authority counts.  Grant and delegation
dates are inclusive calendar dates read from the plugin's injectable clock ``now`` (default
``core.ids.utcnow``).

Governor (``GOVERNOR = True``).  While no policy is recorded, or the current policy does not
enforce, the governor binds nothing and checks nothing for other modules' approvals, so
existing flows and workspaces behave exactly as before.  While the current policy enforces:

* ``approval_policy`` binds the identity policy version and its hash into every approval
  (``manifest['governance']['people']``); adopting another policy invalidates in-flight
  approvals (at adoption, at grant and, through the service, at execution).
* ``check_request``: the requester must be an active registered identity.
* ``check_grant``: the approver must be an active person (service identities -- the payment
  worker, Ricky -- never approve) holding ``approver_role`` directly or by an active delegation
  in the manifest's scope (``bindings['project_id']`` when there is one); when the policy
  segregates the approver must differ from the requester.  In solo-owner mode (policy rule
  ``solo_owner_self_approval``) an active owner may approve their own request; each such
  self-approval is recorded and fails the close check until an outside party (an active
  external person other than the approver) reviews it.
* ``check_execute``: the executing identity must be active and hold ``manifest['actor_role']``
  in scope; an approval whose approver has since been deactivated or lost every role
  authorized for the operation is invalidated (``StaleApprovalError``).

Integrity.  Triggers refuse raw SQL that would forge, rewrite, delete or replace a grant or a
policy version (a grant must name its consumed ``people.grant_role`` approval and pending
request, which the grantee neither requested, approved nor executed; a policy version must name
its consumed ``people.set_policy`` approval and pending draft; both extend their hash chain at
its head).  What a trigger cannot see -- a row rewritten or deleted after its triggers were
dropped -- the hash chains and the cross-checks against approvals and the audit log detect: each
stored policy version matches one audited adoption, in order (so deleted versions never read as
a weaker policy or as none); a consumed revocation approval and each audited revocation revoked
their grant; and a membership, a delegation and a self-approval review agree with their audited
addition, end, revocation, cancellation or review.  ``integrity_problems`` and the close check
report it, and while enforcing every governor check (and the Ricky SDK) fails closed.  A broken
policy chain makes ``enforcing()`` true, so dependent governors fail closed too.
"""
from __future__ import annotations

import datetime as _dt
import re
import unicodedata
from typing import Any

from ..core.approvals import StaleApprovalError, build_manifest
from ..core.ids import canonical_json, hash_json, loads, new_id, utcnow
from .ricky import ROLE_AUTHORITY, Ricky

SCHEMA_NAME = "people"
PLUGIN_NAME = "people"
OP_GRANT = "people.grant_role"
OP_REVOKE = "people.revoke_role"
OP_DELEGATE = "people.delegate"
OP_POLICY = "people.set_policy"
SUBJECT_TYPES = {
    OP_GRANT: "people_grant_request",
    OP_REVOKE: "people_revocation_request",
    OP_DELEGATE: "people_delegation",
    OP_POLICY: "people_policy_draft",
}
OWNER_ROLE = "owner"
EXPIRY_WARNING_DAYS = 14
GENESIS = "0" * 64
MAX_TEXT_LENGTH = 500
MAX_NAME_LENGTH = 200
LOGIN_RE = re.compile(r"^[a-z0-9][a-z0-9._@-]{0,63}$")
POLICY_RULES = ("enforce", "segregate", "solo_owner_self_approval")


def _audited(entity_type: str, action: str, *conditions: str, entity: str = "NEW.id") -> str:
    """SQL: an audit entry ``action`` on the entity whose payload carries the given facts."""
    where = "".join(f" AND {c}" for c in conditions)
    return (f"EXISTS (SELECT 1 FROM audit_log g WHERE g.entity_type = '{entity_type}' AND g.entity_id = {entity} "
            f"AND g.action = '{action}'{where})")


def _payload(path: str, value: str) -> str:
    return f"json_extract(g.payload_json, '$.{path}') IS {value}"


def _not_by(column: str, login: str) -> str:
    """SQL: the actor string in ``column`` is not the identity ``login`` (compared normalized)."""
    return f"lower(trim(COALESCE({column}, ''))) <> {login}"


# an active person holding a live, entity-scoped owner grant (the storage guards' view; Python
# applies the same rule with the injectable clock)
_ACTIVE_OWNER_SQL = ("EXISTS (SELECT 1 FROM people_grants og JOIN people_persons op ON op.id = og.person_id "
                     "WHERE og.role = 'owner' AND og.scope = 'entity' AND og.revoked_at IS NULL AND op.status = 'active' "
                     "AND op.kind = 'person' AND (og.effective_to IS NULL OR og.effective_to >= date('now')))")

SCHEMA_STATEMENTS = [
    # ---- tables ------------------------------------------------------------------------------ #
    """CREATE TABLE people_persons (
        id TEXT PRIMARY KEY,
        login TEXT NOT NULL UNIQUE CHECK (length(login) BETWEEN 1 AND 64 AND login = lower(trim(login))
                                          AND login NOT GLOB '*[^a-z0-9._@-]*' AND substr(login, 1, 1) GLOB '[a-z0-9]'),
        display_name TEXT NOT NULL CHECK (length(trim(display_name)) > 0),
        kind TEXT NOT NULL CHECK (kind IN ('person','service')),
        external INTEGER NOT NULL DEFAULT 0 CHECK (external IN (0, 1)),
        status TEXT NOT NULL CHECK (status IN ('active','inactive')),
        content_hash TEXT NOT NULL,
        created_by TEXT NOT NULL CHECK (length(trim(created_by)) > 0),
        created_at TEXT NOT NULL,
        deactivated_by TEXT,
        deactivated_at TEXT,
        deactivation_reason TEXT,
        CHECK (kind = 'person' OR external = 0)
    )""",
    """CREATE TABLE people_memberships (
        id TEXT PRIMARY KEY,
        person_id TEXT NOT NULL REFERENCES people_persons(id),
        project_id TEXT NOT NULL REFERENCES projects(id),
        status TEXT NOT NULL CHECK (status IN ('active','ended')),
        added_by TEXT NOT NULL CHECK (length(trim(added_by)) > 0),
        added_at TEXT NOT NULL,
        ended_by TEXT,
        ended_at TEXT,
        end_reason TEXT
    )""",
    "CREATE UNIQUE INDEX people_memberships_one_active ON people_memberships (person_id, project_id) WHERE status = 'active'",
    """CREATE TABLE people_grant_requests (
        id TEXT PRIMARY KEY,
        person_id TEXT NOT NULL REFERENCES people_persons(id),
        role TEXT NOT NULL CHECK (length(trim(role)) > 0),
        scope TEXT NOT NULL CHECK (scope IN ('entity','project')),
        project_id TEXT REFERENCES projects(id),
        effective_from TEXT NOT NULL,
        effective_to TEXT,
        reason TEXT NOT NULL CHECK (length(trim(reason)) > 0),
        content_hash TEXT NOT NULL,
        status TEXT NOT NULL CHECK (status IN ('pending','granted','cancelled')),
        requested_by TEXT NOT NULL CHECK (length(trim(requested_by)) > 0),
        requested_at TEXT NOT NULL,
        grant_id TEXT,
        resolved_by TEXT,
        resolved_at TEXT,
        resolution_note TEXT,
        CHECK ((scope = 'project') = (project_id IS NOT NULL)),
        CHECK (effective_to IS NULL OR effective_to >= effective_from),
        CHECK (role <> 'owner' OR scope = 'entity')
    )""",
    "CREATE UNIQUE INDEX people_grant_requests_one_pending ON people_grant_requests (person_id, role, scope, COALESCE(project_id, '')) WHERE status = 'pending'",
    """CREATE TABLE people_policy_drafts (
        id TEXT PRIMARY KEY,
        rules_json TEXT NOT NULL,
        reason TEXT NOT NULL CHECK (length(trim(reason)) > 0),
        content_hash TEXT NOT NULL,
        status TEXT NOT NULL CHECK (status IN ('pending','adopted','cancelled')),
        prepared_by TEXT NOT NULL CHECK (length(trim(prepared_by)) > 0),
        prepared_at TEXT NOT NULL,
        version_id TEXT,
        resolved_by TEXT,
        resolved_at TEXT,
        resolution_note TEXT
    )""",
    """CREATE TABLE people_policy_versions (
        id TEXT PRIMARY KEY,
        version INTEGER NOT NULL UNIQUE CHECK (version >= 1),
        draft_id TEXT NOT NULL UNIQUE REFERENCES people_policy_drafts(id),
        rules_json TEXT NOT NULL,
        enforce INTEGER NOT NULL CHECK (enforce IN (0, 1)),
        segregate INTEGER NOT NULL CHECK (segregate IN (0, 1)),
        solo_owner_self_approval INTEGER NOT NULL CHECK (solo_owner_self_approval IN (0, 1)),
        approval_id TEXT NOT NULL UNIQUE REFERENCES approvals(id),
        approved_by TEXT NOT NULL,
        adopted_by TEXT NOT NULL,
        adopted_at TEXT NOT NULL,
        prev_hash TEXT NOT NULL,
        content_hash TEXT NOT NULL UNIQUE
    )""",
    """CREATE TABLE people_grants (
        id TEXT PRIMARY KEY,
        seq INTEGER NOT NULL UNIQUE CHECK (seq >= 1),
        request_id TEXT UNIQUE REFERENCES people_grant_requests(id),
        person_id TEXT NOT NULL REFERENCES people_persons(id),
        login TEXT NOT NULL,
        role TEXT NOT NULL CHECK (length(trim(role)) > 0),
        scope TEXT NOT NULL CHECK (scope IN ('entity','project')),
        project_id TEXT REFERENCES projects(id),
        effective_from TEXT NOT NULL,
        effective_to TEXT,
        origin TEXT NOT NULL CHECK (origin IN ('approval','bootstrap')),
        approval_id TEXT UNIQUE REFERENCES approvals(id),
        granted_by TEXT NOT NULL,
        created_at TEXT NOT NULL,
        prev_hash TEXT NOT NULL,
        content_hash TEXT NOT NULL UNIQUE,
        revoked_at TEXT,
        revoked_by TEXT,
        revocation_request_id TEXT,
        revocation_approval_id TEXT UNIQUE REFERENCES approvals(id),
        CHECK ((scope = 'project') = (project_id IS NOT NULL)),
        CHECK (effective_to IS NULL OR effective_to >= effective_from),
        CHECK (role <> 'owner' OR scope = 'entity'),
        CHECK ((origin = 'approval') = (approval_id IS NOT NULL AND request_id IS NOT NULL)),
        CHECK (origin <> 'bootstrap' OR (role = 'owner' AND scope = 'entity' AND effective_to IS NULL))
    )""",
    "CREATE INDEX people_grants_by_person ON people_grants (person_id, role)",
    """CREATE TABLE people_revocation_requests (
        id TEXT PRIMARY KEY,
        grant_id TEXT NOT NULL REFERENCES people_grants(id),
        reason TEXT NOT NULL CHECK (length(trim(reason)) > 0),
        status TEXT NOT NULL CHECK (status IN ('pending','executed','cancelled')),
        requested_by TEXT NOT NULL CHECK (length(trim(requested_by)) > 0),
        requested_at TEXT NOT NULL,
        approval_id TEXT UNIQUE REFERENCES approvals(id),
        resolved_by TEXT,
        resolved_at TEXT,
        resolution_note TEXT
    )""",
    "CREATE UNIQUE INDEX people_revocation_requests_one_pending ON people_revocation_requests (grant_id) WHERE status = 'pending'",
    """CREATE TABLE people_delegations (
        id TEXT PRIMARY KEY,
        from_person_id TEXT NOT NULL REFERENCES people_persons(id),
        to_person_id TEXT NOT NULL REFERENCES people_persons(id),
        from_login TEXT NOT NULL,
        to_login TEXT NOT NULL,
        role TEXT NOT NULL CHECK (length(trim(role)) > 0 AND role <> 'owner'),
        scope TEXT NOT NULL CHECK (scope IN ('entity','project')),
        project_id TEXT REFERENCES projects(id),
        effective_from TEXT NOT NULL,
        effective_to TEXT NOT NULL,
        reason TEXT NOT NULL CHECK (length(trim(reason)) > 0),
        content_hash TEXT NOT NULL,
        status TEXT NOT NULL CHECK (status IN ('pending','active','cancelled','revoked')),
        requested_by TEXT NOT NULL CHECK (length(trim(requested_by)) > 0),
        requested_at TEXT NOT NULL,
        approval_id TEXT UNIQUE REFERENCES approvals(id),
        activated_by TEXT,
        activated_at TEXT,
        ended_by TEXT,
        ended_at TEXT,
        end_reason TEXT,
        CHECK (from_person_id <> to_person_id),
        CHECK ((scope = 'project') = (project_id IS NOT NULL)),
        CHECK (effective_to >= effective_from)
    )""",
    "CREATE INDEX people_delegations_to ON people_delegations (to_person_id, role, status)",
    """CREATE TABLE people_self_approvals (
        id TEXT PRIMARY KEY,
        approval_id TEXT NOT NULL UNIQUE REFERENCES approvals(id),
        operation TEXT NOT NULL,
        login TEXT NOT NULL,
        approver_role TEXT NOT NULL,
        policy_version INTEGER NOT NULL,
        recorded_at TEXT NOT NULL,
        reviewed_by TEXT,
        reviewed_at TEXT,
        review_note TEXT
    )""",
    # ---- identities ------------------------------------------------------------------------- #
    f"""CREATE TRIGGER people_persons_insert_guard BEFORE INSERT ON people_persons
        BEGIN SELECT CASE
          WHEN EXISTS (SELECT 1 FROM people_persons WHERE id = NEW.id OR login = NEW.login)
            THEN RAISE(ABORT, 'identities are never replaced: that identity id or login already exists')
          WHEN NEW.status IS NOT 'active' OR NEW.deactivated_by IS NOT NULL OR NEW.deactivated_at IS NOT NULL OR NEW.deactivation_reason IS NOT NULL
            THEN RAISE(ABORT, 'an identity is registered active')
          WHEN NOT {_audited('people_person', 'people.person_registered', _payload('login', 'NEW.login'), _payload('content_hash', 'NEW.content_hash'),
                             _payload('kind', 'NEW.kind'), _payload('external', 'NEW.external'))}
            THEN RAISE(ABORT, 'an identity is registered only through register_person or bootstrap_owner, which audit it')
        END; END""",
    f"""CREATE TRIGGER people_persons_update_guard BEFORE UPDATE ON people_persons
        BEGIN SELECT CASE
          WHEN NEW.id IS NOT OLD.id OR NEW.login IS NOT OLD.login OR NEW.display_name IS NOT OLD.display_name OR NEW.kind IS NOT OLD.kind
            OR NEW.external IS NOT OLD.external OR NEW.content_hash IS NOT OLD.content_hash OR NEW.created_by IS NOT OLD.created_by
            OR NEW.created_at IS NOT OLD.created_at
            THEN RAISE(ABORT, 'an identity''s login, name, kind, outside-party flag and registration are immutable')
          WHEN OLD.status = 'inactive'
            THEN RAISE(ABORT, 'a deactivated identity is final; register a new identity instead')
          WHEN NEW.status = 'active' AND (NEW.deactivated_by IS NOT NULL OR NEW.deactivated_at IS NOT NULL OR NEW.deactivation_reason IS NOT NULL)
            THEN RAISE(ABORT, 'an identity records a deactivation only by being deactivated')
          WHEN NEW.status = 'inactive' AND (length(trim(COALESCE(NEW.deactivated_by, ''))) = 0 OR NEW.deactivated_at IS NULL
               OR length(trim(COALESCE(NEW.deactivation_reason, ''))) = 0
               OR NOT {_audited('people_person', 'people.person_deactivated', _payload('deactivated_at', 'NEW.deactivated_at'))})
            THEN RAISE(ABORT, 'an identity is deactivated only through deactivate_person, which records who, when and why and audits it')
        END; END""",
    "CREATE TRIGGER people_persons_no_delete BEFORE DELETE ON people_persons BEGIN SELECT RAISE(ABORT, 'identities are never deleted; deactivate one instead'); END",
    # ---- memberships ------------------------------------------------------------------------ #
    f"""CREATE TRIGGER people_memberships_insert_guard BEFORE INSERT ON people_memberships
        BEGIN SELECT CASE
          WHEN EXISTS (SELECT 1 FROM people_memberships WHERE id = NEW.id)
            THEN RAISE(ABORT, 'project memberships are never replaced')
          WHEN NEW.status IS NOT 'active' OR NEW.ended_by IS NOT NULL OR NEW.ended_at IS NOT NULL OR NEW.end_reason IS NOT NULL
            THEN RAISE(ABORT, 'a project membership is recorded active')
          WHEN NOT {_audited('people_membership', 'people.membership_added', _payload('person_id', 'NEW.person_id'), _payload('project_id', 'NEW.project_id'))}
            THEN RAISE(ABORT, 'a project membership is added only through add_membership, which audits it')
        END; END""",
    f"""CREATE TRIGGER people_memberships_update_guard BEFORE UPDATE ON people_memberships
        BEGIN SELECT CASE
          WHEN NEW.id IS NOT OLD.id OR NEW.person_id IS NOT OLD.person_id OR NEW.project_id IS NOT OLD.project_id
            OR NEW.added_by IS NOT OLD.added_by OR NEW.added_at IS NOT OLD.added_at
            THEN RAISE(ABORT, 'a project membership''s person, project and addition are immutable')
          WHEN OLD.status = 'ended'
            THEN RAISE(ABORT, 'an ended project membership is final')
          WHEN NEW.status = 'active' AND (NEW.ended_by IS NOT NULL OR NEW.ended_at IS NOT NULL OR NEW.end_reason IS NOT NULL)
            THEN RAISE(ABORT, 'a project membership records its end only by ending')
          WHEN NEW.status = 'ended' AND (length(trim(COALESCE(NEW.ended_by, ''))) = 0 OR NEW.ended_at IS NULL
               OR length(trim(COALESCE(NEW.end_reason, ''))) = 0
               OR NOT {_audited('people_membership', 'people.membership_ended', _payload('ended_at', 'NEW.ended_at'))})
            THEN RAISE(ABORT, 'a project membership ends only through end_membership, which audits it')
        END; END""",
    "CREATE TRIGGER people_memberships_no_delete BEFORE DELETE ON people_memberships BEGIN SELECT RAISE(ABORT, 'project memberships are never deleted; end one instead'); END",
    # ---- grant requests --------------------------------------------------------------------- #
    f"""CREATE TRIGGER people_grant_requests_insert_guard BEFORE INSERT ON people_grant_requests
        BEGIN SELECT CASE
          WHEN EXISTS (SELECT 1 FROM people_grant_requests WHERE id = NEW.id)
            THEN RAISE(ABORT, 'grant requests are never replaced')
          WHEN NEW.status IS NOT 'pending' OR NEW.grant_id IS NOT NULL OR NEW.resolved_by IS NOT NULL OR NEW.resolved_at IS NOT NULL
            THEN RAISE(ABORT, 'a grant request is recorded pending')
          WHEN NOT {_audited('people_grant_request', 'people.grant_requested', _payload('content_hash', 'NEW.content_hash'))}
            THEN RAISE(ABORT, 'a grant request is recorded only through request_grant, which audits it')
        END; END""",
    f"""CREATE TRIGGER people_grant_requests_update_guard BEFORE UPDATE ON people_grant_requests
        BEGIN SELECT CASE
          WHEN NEW.id IS NOT OLD.id OR NEW.person_id IS NOT OLD.person_id OR NEW.role IS NOT OLD.role OR NEW.scope IS NOT OLD.scope
            OR NEW.project_id IS NOT OLD.project_id OR NEW.effective_from IS NOT OLD.effective_from OR NEW.effective_to IS NOT OLD.effective_to
            OR NEW.reason IS NOT OLD.reason OR NEW.content_hash IS NOT OLD.content_hash OR NEW.requested_by IS NOT OLD.requested_by
            OR NEW.requested_at IS NOT OLD.requested_at
            THEN RAISE(ABORT, 'a grant request''s content is immutable')
          WHEN OLD.status <> 'pending'
            THEN RAISE(ABORT, 'a resolved grant request is final')
          WHEN NEW.status = 'pending'
            THEN RAISE(ABORT, 'a grant request changes only by being granted or cancelled')
          WHEN NEW.status = 'granted' AND NOT EXISTS (SELECT 1 FROM people_grants pg WHERE pg.id = NEW.grant_id AND pg.request_id = NEW.id)
            THEN RAISE(ABORT, 'a grant request is granted only by the grant its approval recorded')
          WHEN NEW.status = 'cancelled' AND (NEW.grant_id IS NOT NULL OR length(trim(COALESCE(NEW.resolved_by, ''))) = 0 OR NEW.resolved_at IS NULL
               OR NOT {_audited('people_grant_request', 'people.request_cancelled', _payload('resolved_at', 'NEW.resolved_at'))})
            THEN RAISE(ABORT, 'a grant request is cancelled only through cancel_request, which audits it')
        END; END""",
    "CREATE TRIGGER people_grant_requests_no_delete BEFORE DELETE ON people_grant_requests BEGIN SELECT RAISE(ABORT, 'grant requests are never deleted'); END",
    # ---- grants (hash-chained) -------------------------------------------------------------- #
    f"""CREATE TRIGGER people_grants_insert_guard BEFORE INSERT ON people_grants
        BEGIN SELECT CASE
          WHEN EXISTS (SELECT 1 FROM people_grants WHERE id = NEW.id)
            THEN RAISE(ABORT, 'role grants are append-only: a grant id is never reused or replaced')
          WHEN NEW.seq IS NOT (SELECT COALESCE(MAX(seq), 0) + 1 FROM people_grants)
            OR NEW.prev_hash IS NOT COALESCE((SELECT content_hash FROM people_grants ORDER BY seq DESC LIMIT 1), '{GENESIS}')
            THEN RAISE(ABORT, 'role grants are hash-chained: a grant extends the chain at its head')
          WHEN NEW.revoked_at IS NOT NULL OR NEW.revoked_by IS NOT NULL OR NEW.revocation_request_id IS NOT NULL OR NEW.revocation_approval_id IS NOT NULL
            THEN RAISE(ABORT, 'a role grant is recorded unrevoked')
          WHEN NEW.login IS NOT (SELECT login FROM people_persons WHERE id = NEW.person_id)
            OR (SELECT status FROM people_persons WHERE id = NEW.person_id) IS NOT 'active'
            THEN RAISE(ABORT, 'a role grant names an active registered identity by its login')
          WHEN NEW.origin = 'approval' AND NOT EXISTS (
                SELECT 1 FROM approvals a JOIN people_grant_requests r ON r.id = a.subject_id
                 WHERE a.id = NEW.approval_id AND a.status = 'consumed' AND a.operation = '{OP_GRANT}'
                   AND r.id = NEW.request_id AND r.status = 'pending' AND r.person_id = NEW.person_id AND r.role = NEW.role
                   AND r.scope = NEW.scope AND r.project_id IS NEW.project_id AND r.effective_from = NEW.effective_from
                   AND r.effective_to IS NEW.effective_to AND NEW.granted_by IS a.approver
                   AND json_extract(a.manifest_json, '$.bindings.request_hash') IS r.content_hash
                   AND {_not_by('a.requested_by', 'NEW.login')} AND {_not_by('a.approver', 'NEW.login')}
                   AND {_not_by('a.consumed_by', 'NEW.login')} AND {_not_by('r.requested_by', 'NEW.login')})
            THEN RAISE(ABORT, 'a role grant is recorded only by its consumed people.grant_role approval of a pending request, which the grantee neither requested, approved nor executed')
          WHEN NEW.origin = 'bootstrap' AND (EXISTS (SELECT 1 FROM people_grants WHERE origin = 'bootstrap')
                OR COALESCE((SELECT enforce FROM people_policy_versions ORDER BY version DESC LIMIT 1), 0) = 1
                OR {_ACTIVE_OWNER_SQL})
            THEN RAISE(ABORT, 'the owner is bootstrapped exactly once, while no active person holds owner and identity enforcement is off')
        END; END""",
    f"""CREATE TRIGGER people_grants_update_guard BEFORE UPDATE ON people_grants
        BEGIN SELECT CASE
          WHEN NEW.id IS NOT OLD.id OR NEW.seq IS NOT OLD.seq OR NEW.request_id IS NOT OLD.request_id OR NEW.person_id IS NOT OLD.person_id
            OR NEW.login IS NOT OLD.login OR NEW.role IS NOT OLD.role OR NEW.scope IS NOT OLD.scope OR NEW.project_id IS NOT OLD.project_id
            OR NEW.effective_from IS NOT OLD.effective_from OR NEW.effective_to IS NOT OLD.effective_to OR NEW.origin IS NOT OLD.origin
            OR NEW.approval_id IS NOT OLD.approval_id OR NEW.granted_by IS NOT OLD.granted_by OR NEW.created_at IS NOT OLD.created_at
            OR NEW.prev_hash IS NOT OLD.prev_hash OR NEW.content_hash IS NOT OLD.content_hash
            THEN RAISE(ABORT, 'a role grant''s facts are immutable; it changes only by its revocation')
          WHEN OLD.revoked_at IS NOT NULL
            THEN RAISE(ABORT, 'a revoked role grant is final')
          WHEN NEW.revoked_at IS NULL OR length(trim(COALESCE(NEW.revoked_by, ''))) = 0 OR NOT EXISTS (
                SELECT 1 FROM approvals a JOIN people_revocation_requests r ON r.id = a.subject_id
                 WHERE a.id = NEW.revocation_approval_id AND a.status = 'consumed' AND a.operation = '{OP_REVOKE}'
                   AND r.id = NEW.revocation_request_id AND r.grant_id = NEW.id AND r.status = 'pending')
            THEN RAISE(ABORT, 'a role grant is revoked only by its consumed people.revoke_role approval')
        END; END""",
    "CREATE TRIGGER people_grants_no_delete BEFORE DELETE ON people_grants BEGIN SELECT RAISE(ABORT, 'role grants are append-only; revoke one instead'); END",
    # ---- revocation requests ---------------------------------------------------------------- #
    f"""CREATE TRIGGER people_revocation_requests_insert_guard BEFORE INSERT ON people_revocation_requests
        BEGIN SELECT CASE
          WHEN EXISTS (SELECT 1 FROM people_revocation_requests WHERE id = NEW.id)
            THEN RAISE(ABORT, 'revocation requests are never replaced')
          WHEN NEW.status IS NOT 'pending' OR NEW.approval_id IS NOT NULL OR NEW.resolved_by IS NOT NULL OR NEW.resolved_at IS NOT NULL
            THEN RAISE(ABORT, 'a revocation request is recorded pending')
          WHEN NOT {_audited('people_revocation_request', 'people.revocation_requested', _payload('grant_id', 'NEW.grant_id'))}
            THEN RAISE(ABORT, 'a revocation request is recorded only through request_revocation, which audits it')
        END; END""",
    f"""CREATE TRIGGER people_revocation_requests_update_guard BEFORE UPDATE ON people_revocation_requests
        BEGIN SELECT CASE
          WHEN NEW.id IS NOT OLD.id OR NEW.grant_id IS NOT OLD.grant_id OR NEW.reason IS NOT OLD.reason
            OR NEW.requested_by IS NOT OLD.requested_by OR NEW.requested_at IS NOT OLD.requested_at
            THEN RAISE(ABORT, 'a revocation request''s content is immutable')
          WHEN OLD.status <> 'pending'
            THEN RAISE(ABORT, 'a resolved revocation request is final')
          WHEN NEW.status = 'pending'
            THEN RAISE(ABORT, 'a revocation request changes only by being executed or cancelled')
          WHEN NEW.status = 'executed' AND NOT EXISTS (SELECT 1 FROM people_grants pg WHERE pg.id = NEW.grant_id AND pg.revocation_request_id = NEW.id
                                                        AND pg.revocation_approval_id IS NEW.approval_id)
            THEN RAISE(ABORT, 'a revocation request is executed only by the revocation its approval recorded')
          WHEN NEW.status = 'cancelled' AND (NEW.approval_id IS NOT NULL OR length(trim(COALESCE(NEW.resolved_by, ''))) = 0 OR NEW.resolved_at IS NULL
               OR NOT {_audited('people_revocation_request', 'people.request_cancelled', _payload('resolved_at', 'NEW.resolved_at'))})
            THEN RAISE(ABORT, 'a revocation request is cancelled only through cancel_request, which audits it')
        END; END""",
    "CREATE TRIGGER people_revocation_requests_no_delete BEFORE DELETE ON people_revocation_requests BEGIN SELECT RAISE(ABORT, 'revocation requests are never deleted'); END",
    # ---- delegations ------------------------------------------------------------------------ #
    f"""CREATE TRIGGER people_delegations_insert_guard BEFORE INSERT ON people_delegations
        BEGIN SELECT CASE
          WHEN EXISTS (SELECT 1 FROM people_delegations WHERE id = NEW.id)
            THEN RAISE(ABORT, 'delegations are never replaced')
          WHEN NEW.status IS NOT 'pending' OR NEW.approval_id IS NOT NULL OR NEW.activated_at IS NOT NULL OR NEW.activated_by IS NOT NULL
            OR NEW.ended_at IS NOT NULL OR NEW.ended_by IS NOT NULL
            THEN RAISE(ABORT, 'a delegation is recorded pending')
          WHEN NEW.from_login IS NOT (SELECT login FROM people_persons WHERE id = NEW.from_person_id)
            OR NEW.to_login IS NOT (SELECT login FROM people_persons WHERE id = NEW.to_person_id)
            THEN RAISE(ABORT, 'a delegation names its registered identities by their logins')
          WHEN NOT {_audited('people_delegation', 'people.delegation_requested', _payload('content_hash', 'NEW.content_hash'))}
            THEN RAISE(ABORT, 'a delegation is recorded only through request_delegation, which audits it')
        END; END""",
    f"""CREATE TRIGGER people_delegations_update_guard BEFORE UPDATE ON people_delegations
        BEGIN SELECT CASE
          WHEN NEW.id IS NOT OLD.id OR NEW.from_person_id IS NOT OLD.from_person_id OR NEW.to_person_id IS NOT OLD.to_person_id
            OR NEW.from_login IS NOT OLD.from_login OR NEW.to_login IS NOT OLD.to_login OR NEW.role IS NOT OLD.role OR NEW.scope IS NOT OLD.scope
            OR NEW.project_id IS NOT OLD.project_id OR NEW.effective_from IS NOT OLD.effective_from OR NEW.effective_to IS NOT OLD.effective_to
            OR NEW.reason IS NOT OLD.reason OR NEW.content_hash IS NOT OLD.content_hash OR NEW.requested_by IS NOT OLD.requested_by
            OR NEW.requested_at IS NOT OLD.requested_at
            OR (OLD.status <> 'pending' AND (NEW.approval_id IS NOT OLD.approval_id OR NEW.activated_by IS NOT OLD.activated_by
                                             OR NEW.activated_at IS NOT OLD.activated_at))
            THEN RAISE(ABORT, 'a delegation''s parties, role, scope, window and activation are immutable')
          WHEN OLD.status IN ('cancelled', 'revoked')
            THEN RAISE(ABORT, 'a cancelled or revoked delegation is final')
          WHEN NOT ((OLD.status = 'pending' AND NEW.status IN ('active', 'cancelled')) OR (OLD.status = 'active' AND NEW.status = 'revoked'))
            THEN RAISE(ABORT, 'a delegation moves pending -> active or cancelled, and active -> revoked')
          WHEN NEW.status = 'active' AND (NEW.activated_at IS NULL OR length(trim(COALESCE(NEW.activated_by, ''))) = 0 OR NEW.ended_at IS NOT NULL
               OR NOT EXISTS (SELECT 1 FROM approvals a WHERE a.id = NEW.approval_id AND a.status = 'consumed' AND a.operation = '{OP_DELEGATE}'
                                AND a.subject_id = NEW.id AND json_extract(a.manifest_json, '$.bindings.delegation_hash') IS NEW.content_hash
                                AND {_not_by('a.requested_by', 'NEW.to_login')} AND {_not_by('a.approver', 'NEW.to_login')}
                                AND {_not_by('a.consumed_by', 'NEW.to_login')})
               OR NOT EXISTS (SELECT 1 FROM people_grants dg WHERE dg.person_id = NEW.from_person_id AND dg.revoked_at IS NULL
                                AND (dg.role = 'owner' OR (dg.role = NEW.role AND (dg.scope = 'entity' OR dg.project_id IS NEW.project_id)))))
            THEN RAISE(ABORT, 'a delegation becomes active only by its consumed people.delegate approval, which the delegate neither requested, approved nor executed, from a delegator holding the role by grant')
          WHEN NEW.status = 'cancelled' AND (NEW.approval_id IS NOT NULL OR length(trim(COALESCE(NEW.ended_by, ''))) = 0 OR NEW.ended_at IS NULL
               OR NOT {_audited('people_delegation', 'people.request_cancelled', _payload('resolved_at', 'NEW.ended_at'))})
            THEN RAISE(ABORT, 'a pending delegation is cancelled only through cancel_request, which audits it')
          WHEN NEW.status = 'revoked' AND (length(trim(COALESCE(NEW.ended_by, ''))) = 0 OR NEW.ended_at IS NULL
               OR NOT {_audited('people_delegation', 'people.delegation_revoked', _payload('ended_at', 'NEW.ended_at'))})
            THEN RAISE(ABORT, 'an active delegation is revoked only through revoke_delegation, which audits it')
        END; END""",
    "CREATE TRIGGER people_delegations_no_delete BEFORE DELETE ON people_delegations BEGIN SELECT RAISE(ABORT, 'delegations are never deleted'); END",
    # ---- policy drafts and versions (hash-chained) ------------------------------------------ #
    f"""CREATE TRIGGER people_policy_drafts_insert_guard BEFORE INSERT ON people_policy_drafts
        BEGIN SELECT CASE
          WHEN EXISTS (SELECT 1 FROM people_policy_drafts WHERE id = NEW.id)
            THEN RAISE(ABORT, 'policy drafts are never replaced')
          WHEN NEW.status IS NOT 'pending' OR NEW.version_id IS NOT NULL OR NEW.resolved_by IS NOT NULL OR NEW.resolved_at IS NOT NULL
            THEN RAISE(ABORT, 'a policy draft is recorded pending')
          WHEN NOT {_audited('people_policy_draft', 'people.policy_prepared', _payload('content_hash', 'NEW.content_hash'))}
            THEN RAISE(ABORT, 'a policy draft is recorded only through prepare_policy, which audits it')
        END; END""",
    f"""CREATE TRIGGER people_policy_drafts_update_guard BEFORE UPDATE ON people_policy_drafts
        BEGIN SELECT CASE
          WHEN NEW.id IS NOT OLD.id OR NEW.rules_json IS NOT OLD.rules_json OR NEW.reason IS NOT OLD.reason OR NEW.content_hash IS NOT OLD.content_hash
            OR NEW.prepared_by IS NOT OLD.prepared_by OR NEW.prepared_at IS NOT OLD.prepared_at
            THEN RAISE(ABORT, 'a policy draft''s content is immutable')
          WHEN OLD.status <> 'pending'
            THEN RAISE(ABORT, 'a resolved policy draft is final')
          WHEN NEW.status = 'pending'
            THEN RAISE(ABORT, 'a policy draft changes only by being adopted or cancelled')
          WHEN NEW.status = 'adopted' AND NOT EXISTS (SELECT 1 FROM people_policy_versions v WHERE v.id = NEW.version_id AND v.draft_id = NEW.id)
            THEN RAISE(ABORT, 'a policy draft is adopted only by the policy version its approval recorded')
          WHEN NEW.status = 'cancelled' AND (NEW.version_id IS NOT NULL OR length(trim(COALESCE(NEW.resolved_by, ''))) = 0 OR NEW.resolved_at IS NULL
               OR NOT {_audited('people_policy_draft', 'people.request_cancelled', _payload('resolved_at', 'NEW.resolved_at'))})
            THEN RAISE(ABORT, 'a policy draft is cancelled only through cancel_request, which audits it')
        END; END""",
    "CREATE TRIGGER people_policy_drafts_no_delete BEFORE DELETE ON people_policy_drafts BEGIN SELECT RAISE(ABORT, 'policy drafts are never deleted'); END",
    f"""CREATE TRIGGER people_policy_versions_insert_guard BEFORE INSERT ON people_policy_versions
        BEGIN SELECT CASE
          WHEN EXISTS (SELECT 1 FROM people_policy_versions WHERE id = NEW.id)
            THEN RAISE(ABORT, 'identity policy versions are append-only: a version is never reused or replaced')
          WHEN NEW.version IS NOT (SELECT COALESCE(MAX(version), 0) + 1 FROM people_policy_versions)
            OR NEW.prev_hash IS NOT COALESCE((SELECT content_hash FROM people_policy_versions ORDER BY version DESC LIMIT 1), '{GENESIS}')
            THEN RAISE(ABORT, 'identity policy versions are hash-chained: a version extends the chain at its head')
          WHEN NEW.enforce IS NOT json_extract(NEW.rules_json, '$.enforce') OR NEW.segregate IS NOT json_extract(NEW.rules_json, '$.segregate')
            OR NEW.solo_owner_self_approval IS NOT json_extract(NEW.rules_json, '$.solo_owner_self_approval')
            THEN RAISE(ABORT, 'an identity policy version''s columns are its rules')
          WHEN NOT EXISTS (
                SELECT 1 FROM approvals a JOIN people_policy_drafts d ON d.id = a.subject_id
                 WHERE a.id = NEW.approval_id AND a.status = 'consumed' AND a.operation = '{OP_POLICY}'
                   AND d.id = NEW.draft_id AND d.status = 'pending' AND d.rules_json = NEW.rules_json AND NEW.approved_by IS a.approver
                   AND json_extract(a.manifest_json, '$.bindings.draft_hash') IS d.content_hash)
            THEN RAISE(ABORT, 'an identity policy version is recorded only by its consumed people.set_policy approval of a pending draft')
          WHEN NEW.enforce = 1 AND NOT {_ACTIVE_OWNER_SQL}
            THEN RAISE(ABORT, 'identity enforcement needs at least one active owner')
        END; END""",
    "CREATE TRIGGER people_policy_versions_no_update BEFORE UPDATE ON people_policy_versions BEGIN SELECT RAISE(ABORT, 'identity policy versions are append-only'); END",
    "CREATE TRIGGER people_policy_versions_no_delete BEFORE DELETE ON people_policy_versions BEGIN SELECT RAISE(ABORT, 'identity policy versions are append-only'); END",
    # ---- self-approvals and their outside review -------------------------------------------- #
    f"""CREATE TRIGGER people_self_approvals_insert_guard BEFORE INSERT ON people_self_approvals
        BEGIN SELECT CASE
          WHEN EXISTS (SELECT 1 FROM people_self_approvals WHERE id = NEW.id OR approval_id = NEW.approval_id)
            THEN RAISE(ABORT, 'self-approval records are never replaced')
          WHEN NEW.reviewed_by IS NOT NULL OR NEW.reviewed_at IS NOT NULL OR NEW.review_note IS NOT NULL
            THEN RAISE(ABORT, 'a self-approval is recorded unreviewed')
          WHEN NOT EXISTS (SELECT 1 FROM approvals a WHERE a.id = NEW.approval_id AND lower(trim(a.requested_by)) = NEW.login)
            THEN RAISE(ABORT, 'a self-approval record names an approval its approver requested')
          WHEN NOT {_audited('people_self_approval', 'people.self_approval_recorded', _payload('approval_id', 'NEW.approval_id'))}
            THEN RAISE(ABORT, 'a self-approval is recorded only by the identity governor, which audits it')
        END; END""",
    f"""CREATE TRIGGER people_self_approvals_update_guard BEFORE UPDATE ON people_self_approvals
        BEGIN SELECT CASE
          WHEN NEW.id IS NOT OLD.id OR NEW.approval_id IS NOT OLD.approval_id OR NEW.operation IS NOT OLD.operation OR NEW.login IS NOT OLD.login
            OR NEW.approver_role IS NOT OLD.approver_role OR NEW.policy_version IS NOT OLD.policy_version OR NEW.recorded_at IS NOT OLD.recorded_at
            THEN RAISE(ABORT, 'a self-approval record is immutable')
          WHEN OLD.reviewed_at IS NOT NULL
            THEN RAISE(ABORT, 'a self-approval is reviewed once')
          WHEN NEW.reviewed_at IS NULL OR length(trim(COALESCE(NEW.review_note, ''))) = 0 OR NEW.reviewed_by IS NEW.login
            OR NOT EXISTS (SELECT 1 FROM people_persons rp WHERE rp.login = NEW.reviewed_by AND rp.status = 'active' AND rp.external = 1 AND rp.kind = 'person')
            OR NOT {_audited('people_self_approval', 'people.self_approval_reviewed', _payload('reviewed_by', 'NEW.reviewed_by'),
                             _payload('reviewed_at', 'NEW.reviewed_at'))}
            THEN RAISE(ABORT, 'a self-approval is reviewed only by an active outside party other than its approver, through review_self_approval')
        END; END""",
    "CREATE TRIGGER people_self_approvals_no_delete BEFORE DELETE ON people_self_approvals BEGIN SELECT RAISE(ABORT, 'self-approval records are never deleted'); END",
]


class PeopleError(RuntimeError):
    """Invalid identity input, or an action the registry's state does not allow."""


class IdentityRefused(PeopleError, PermissionError):
    """The identity registry refuses this request, grant or execution (no self-granting,
    an inactive or unknown identity, a role not held in scope, segregation)."""


class PeopleIneligible(PeopleError, StaleApprovalError):
    """The request, revocation, delegation or draft cannot be (or can no longer be) executed
    as approved.  At request time this refuses; at execution it is a ``StaleApprovalError``,
    so the service invalidates the approval durably."""


class IdentityIntegrityError(PeopleError, PermissionError):
    """The identity records are not intact (a grant or policy chain, or a record's backing
    approval, no longer verifies); while enforcing, every governor check fails closed."""


# --------------------------------------------------------------------------- #
# Validation helpers                                                           #
# --------------------------------------------------------------------------- #

def _norm(value: Any) -> str | None:
    """An actor string as an identity key: NFKC, trimmed, case-folded (None when empty)."""
    if not isinstance(value, str):
        return None
    key = unicodedata.normalize("NFKC", value).strip().casefold()
    return key or None


def normalize_login(value: Any) -> str:
    """The registry's login for ``value`` (" Travis.Staib " -> "travis.staib"); refuses
    anything that is not 1-64 of a-z, 0-9, '.', '_', '@', '-' starting with a letter or digit."""
    key = _norm(value)
    if key is None or not LOGIN_RE.match(key):
        raise PeopleError(f"login {value!r} must be 1-64 characters of a-z, 0-9, '.', '_', '@' or '-', starting with a letter or digit")
    return key


def _text(value: Any, label: str, *, max_length: int = MAX_TEXT_LENGTH) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PeopleError(f"{label} is required")
    text = value.strip()
    if len(text) > max_length:
        raise PeopleError(f"{label} is longer than {max_length} characters")
    return text


def _date(value: Any, label: str) -> _dt.date:
    if not isinstance(value, str) or len(value) != 10 or value[4] != "-" or value[7] != "-":
        raise PeopleError(f"{label} must be YYYY-MM-DD, got {value!r}")
    try:
        return _dt.date.fromisoformat(value)
    except ValueError as exc:
        raise PeopleError(f"{label} is not a valid calendar date: {value!r}") from exc


def _role(value: Any) -> str:
    if not isinstance(value, str) or value not in ROLE_AUTHORITY:
        raise PeopleError(f"role {value!r} is not a Cipher role; roles are {', '.join(sorted(ROLE_AUTHORITY))}")
    return value


def _flag(value: Any, label: str) -> bool:
    if not isinstance(value, bool):
        raise PeopleError(f"{label} must be true or false, got {value!r}")
    return value


def _overlaps(a_from: str, a_to: str | None, b_from: str, b_to: str | None) -> bool:
    """Inclusive date windows (None: open-ended) share at least one day."""
    return (b_to is None or a_from <= b_to) and (a_to is None or b_from <= a_to)


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
        # injectable clock (an aware UTC datetime): grant and delegation windows, expiry warnings
        # and the timestamps this registry records follow it, so tests can move time
        self.now = utcnow

    # ---- clock ----------------------------------------------------------------------------- #

    def _today(self) -> _dt.date:
        return self.now().date()

    def _stamp(self) -> str:
        return self.now().replace(microsecond=0).isoformat().replace("+00:00", "Z")

    # ---- hashes ---------------------------------------------------------------------------- #

    @staticmethod
    def _person_hash(row: dict[str, Any]) -> str:
        return hash_json({k: row.get(k) for k in ("id", "login", "display_name", "kind", "external", "created_by", "created_at")})

    @staticmethod
    def _request_hash(row: dict[str, Any]) -> str:
        return hash_json({k: row.get(k) for k in ("id", "person_id", "role", "scope", "project_id", "effective_from", "effective_to",
                                                   "reason", "requested_by", "requested_at")})

    @staticmethod
    def _grant_hash(row: dict[str, Any]) -> str:
        return hash_json({k: row.get(k) for k in ("seq", "id", "request_id", "person_id", "login", "role", "scope", "project_id", "effective_from",
                                                   "effective_to", "origin", "approval_id", "granted_by", "created_at", "prev_hash")})

    @staticmethod
    def _delegation_hash(row: dict[str, Any]) -> str:
        return hash_json({k: row.get(k) for k in ("id", "from_person_id", "to_person_id", "from_login", "to_login", "role", "scope", "project_id",
                                                   "effective_from", "effective_to", "reason", "requested_by", "requested_at")})

    @staticmethod
    def _draft_hash(row: dict[str, Any]) -> str:
        return hash_json({k: row.get(k) for k in ("id", "rules_json", "reason", "prepared_by", "prepared_at")})

    @staticmethod
    def _version_hash(row: dict[str, Any]) -> str:
        return hash_json({k: row.get(k) for k in ("version", "id", "draft_id", "rules_json", "approval_id", "approved_by", "adopted_by",
                                                   "adopted_at", "prev_hash")})

    # ---- lookups --------------------------------------------------------------------------- #

    def _person_row(self, login: Any) -> dict[str, Any] | None:
        key = _norm(login)
        if key is None:
            return None
        return self.db.one("SELECT * FROM people_persons WHERE login=?", (key,))

    def _person_by_id(self, person_id: Any) -> dict[str, Any] | None:
        if not isinstance(person_id, str):
            return None
        return self.db.one("SELECT * FROM people_persons WHERE id=?", (person_id,))

    def _person(self, ref: Any) -> dict[str, Any]:
        """A registered identity by id or login."""
        row = self._person_by_id(ref) or self._person_row(ref)
        if row is None:
            raise PeopleError(f"unknown identity {ref!r}; register it first")
        return row

    def _project_exists(self, project_id: Any) -> bool:
        return isinstance(project_id, str) and self.db.one("SELECT id FROM projects WHERE id=?", (project_id,)) is not None

    def _row(self, table: str, row_id: Any, label: str) -> dict[str, Any]:
        row = self.db.one(f"SELECT * FROM {table} WHERE id=?", (row_id,)) if isinstance(row_id, str) else None
        if row is None:
            raise PeopleError(f"unknown {label} {row_id!r}")
        return row

    def _membership(self, person_id: str, project_id: str) -> dict[str, Any] | None:
        return self.db.one("SELECT * FROM people_memberships WHERE person_id=? AND project_id=? AND status='active'", (person_id, project_id))

    @staticmethod
    def _effective(row: dict[str, Any], day: _dt.date) -> bool:
        d = day.isoformat()
        return row["effective_from"] <= d and (row["effective_to"] is None or d <= row["effective_to"])

    def _live_grants(self, person_id: str, day: _dt.date) -> list[dict[str, Any]]:
        rows = self.db.query("SELECT * FROM people_grants WHERE person_id=? AND revoked_at IS NULL ORDER BY seq", (person_id,))
        return [g for g in rows if self._effective(g, day)]

    # ---- authority ------------------------------------------------------------------------- #

    def _holds_by_grant(self, person: dict[str, Any] | None, role: str, project_id: str | None, day: _dt.date | None = None) -> bool:
        """The active identity holds ``role`` by its own live grant in scope.  An owner grant
        (entity scope, persons only) carries every role.  A project-scoped grant counts only for
        that project, while the person is a member."""
        if person is None or person["status"] != "active":
            return False
        day = day or self._today()
        for g in self._live_grants(person["id"], day):
            if g["role"] == OWNER_ROLE and g["scope"] == "entity" and person["kind"] == "person":
                return True
            if g["role"] != role:
                continue
            if g["scope"] == "entity":
                return True
            if project_id is not None and g["project_id"] == project_id and self._membership(person["id"], project_id) is not None:
                return True
        return False

    def _holds_by_delegation(self, person: dict[str, Any] | None, role: str, project_id: str | None, day: _dt.date | None = None) -> bool:
        """The active person holds ``role`` by an active delegation in its window and scope from
        a delegator who is still active and still holds the role by grant (never by delegation)."""
        if person is None or person["status"] != "active" or person["kind"] != "person" or role == OWNER_ROLE:
            return False
        day = day or self._today()
        for d in self.db.query("SELECT * FROM people_delegations WHERE to_person_id=? AND role=? AND status='active' ORDER BY requested_at, id",
                               (person["id"], role)):
            if not self._effective(d, day):
                continue
            if d["scope"] == "project" and (project_id != d["project_id"] or self._membership(person["id"], project_id) is None):
                continue
            if self._holds_by_grant(self._person_by_id(d["from_person_id"]), role, d["project_id"], day):
                return True
        return False

    def _authorized_for(self, login: Any, operation: str, project_id: str | None) -> bool:
        """The identity holds some role that carries ``operation`` (ROLE_AUTHORITY) in scope."""
        return any(Ricky.can(role, operation) and self.holds(login, role, project_id=project_id) for role in ROLE_AUTHORITY)

    def _active_owners(self, day: _dt.date | None = None, *, lasting: bool = False) -> list[dict[str, Any]]:
        """Active persons holding a live, entity-scoped owner grant (``lasting``: one with no end
        date, which never lapses on its own)."""
        day = day or self._today()
        out, seen = [], set()
        for g in self.db.query("SELECT * FROM people_grants WHERE role='owner' AND scope='entity' AND revoked_at IS NULL ORDER BY seq"):
            if lasting and g["effective_to"] is not None:
                continue
            p = self._person_by_id(g["person_id"])
            if p and p["status"] == "active" and p["kind"] == "person" and self._effective(g, day) and p["id"] not in seen:
                seen.add(p["id"])
                out.append(p)
        return out

    # ---- shared identity interface (used by other governors) --------------------------------- #

    def is_active(self, login: Any) -> bool:
        """The login names a registered identity that is active."""
        p = self._person_row(login)
        return p is not None and p["status"] == "active"

    def holds(self, login: Any, role: Any, *, project_id: str | None = None) -> bool:
        """The login is active and holds ``role`` (by grant, or by delegation) in scope: entity
        scope when ``project_id`` is None, else entity scope or that project's scope.  An owner
        holds every role."""
        if not isinstance(role, str) or role not in ROLE_AUTHORITY:
            return False
        if project_id is not None and not isinstance(project_id, str):
            return False
        p = self._person_row(login)
        return self._holds_by_grant(p, role, project_id) or self._holds_by_delegation(p, role, project_id)

    def is_external(self, login: Any) -> bool:
        """The login names an active outside party (for example the external accountant)."""
        p = self._person_row(login)
        return p is not None and p["status"] == "active" and bool(p["external"])

    def person_for(self, login: Any) -> dict[str, Any] | None:
        """The identity behind a login with what it currently holds, or None."""
        p = self._person_row(login)
        return self._person_summary(p) if p is not None else None

    def enforcing(self) -> bool:
        """The current identity policy enforces.  A policy chain that no longer verifies counts
        as enforcing, so every check fails closed instead of silently switching off."""
        policy, problems = self._policy()
        return bool(problems) or bool(policy and policy["enforce"])

    def authorities(self, login: Any) -> list[dict[str, Any]]:
        """What the identity holds today: each live grant and each delegation that counts."""
        p = self._person_row(login)
        if p is None or p["status"] != "active":
            return []
        day = self._today()
        out = []
        for g in self._live_grants(p["id"], day):
            if g["scope"] == "project" and self._membership(p["id"], g["project_id"]) is None:
                continue
            out.append({"role": g["role"], "scope": g["scope"], "project_id": g["project_id"], "via": "grant", "grant_id": g["id"],
                        "until": g["effective_to"]})
        if p["kind"] == "person":
            for d in self.db.query("SELECT * FROM people_delegations WHERE to_person_id=? AND status='active' ORDER BY requested_at, id", (p["id"],)):
                if not self._effective(d, day):
                    continue
                if d["scope"] == "project" and self._membership(p["id"], d["project_id"]) is None:
                    continue
                if self._holds_by_grant(self._person_by_id(d["from_person_id"]), d["role"], d["project_id"], day):
                    out.append({"role": d["role"], "scope": d["scope"], "project_id": d["project_id"], "via": "delegation",
                                "delegation_id": d["id"], "from": d["from_login"], "until": d["effective_to"]})
        return out

    def _person_summary(self, p: dict[str, Any]) -> dict[str, Any]:
        return {"id": p["id"], "login": p["login"], "display_name": p["display_name"], "kind": p["kind"], "external": bool(p["external"]),
                "status": p["status"], "created_at": p["created_at"], "deactivated_at": p["deactivated_at"],
                "authorities": self.authorities(p["login"])}

    # ---- policy ---------------------------------------------------------------------------- #

    def _policy(self) -> tuple[dict[str, Any] | None, list[str]]:
        """The current identity policy version (None: no policy recorded) and every problem
        found re-verifying the policy chain and each version's approval and draft.  The chain is
        anchored to the audit log -- one audited adoption per stored version, in order -- and to
        the adopted drafts, so versions deleted with the triggers dropped (every one, or only the
        newest) are problems too, and never read as no policy or as the weaker one before."""
        rows = self.db.query("SELECT * FROM people_policy_versions ORDER BY version")
        problems: list[str] = []
        adoptions = self.db.query("SELECT entity_id, payload_json FROM audit_log WHERE action='people.policy_adopted' ORDER BY seq")
        if len(adoptions) != len(rows):
            problems.append(f"the audit log records {len(adoptions)} identity policy adoption(s) but {len(rows)} version(s) are stored")
        for v, entry in zip(rows, adoptions):
            payload = loads(entry["payload_json"]) or {}
            if entry["entity_id"] != v["id"] or payload.get("version") != v["version"] or payload.get("content_hash") != v["content_hash"]:
                problems.append(f"identity policy version {v['version']} ({v['id']}) differs from its audited adoption")
        stored = {v["id"] for v in rows}
        for d in self.db.query("SELECT id, version_id FROM people_policy_drafts WHERE status='adopted' ORDER BY prepared_at, id"):
            if d["version_id"] not in stored:
                problems.append(f"identity policy draft {d['id']} is adopted, but its version {d['version_id']} is not stored")
        if not rows:
            return None, problems
        prev = GENESIS
        for n, v in enumerate(rows, start=1):
            label = f"identity policy version {v['version']} ({v['id']})"
            if v["version"] != n or v["prev_hash"] != prev:
                problems.append(f"{label} breaks the policy hash chain")
            if self._version_hash(v) != v["content_hash"]:
                problems.append(f"{label} does not hash to its recorded content hash")
            try:
                rules = loads(v["rules_json"]) or {}
            except ValueError:
                rules = {}
            if any(bool(v[k]) != rules.get(k) for k in POLICY_RULES):
                problems.append(f"{label} carries columns that disagree with its rules")
            draft = self.db.one("SELECT * FROM people_policy_drafts WHERE id=?", (v["draft_id"],))
            ap = self.db.one("SELECT * FROM approvals WHERE id=?", (v["approval_id"],))
            backed = (draft is not None and ap is not None and draft["status"] == "adopted" and draft["version_id"] == v["id"]
                      and draft["rules_json"] == v["rules_json"] and self._draft_hash(draft) == draft["content_hash"]
                      and ap["status"] == "consumed" and ap["operation"] == OP_POLICY and ap["subject_id"] == draft["id"]
                      and ap["approver"] == v["approved_by"]
                      and ((loads(ap["manifest_json"]) or {}).get("bindings") or {}).get("draft_hash") == draft["content_hash"])
            if not backed:
                problems.append(f"{label} is not backed by a consumed people.set_policy approval of its draft")
            prev = v["content_hash"]
        return rows[-1], problems

    def current_policy(self) -> dict[str, Any] | None:
        """The adopted identity policy now in force (None while no policy is recorded)."""
        policy, problems = self._policy()
        if policy is None:
            return None
        return {"version": policy["version"], "id": policy["id"], "rules": loads(policy["rules_json"]), "enforce": bool(policy["enforce"]),
                "segregate": bool(policy["segregate"]), "solo_owner_self_approval": bool(policy["solo_owner_self_approval"]),
                "content_hash": policy["content_hash"], "adopted_at": policy["adopted_at"], "adopted_by": policy["adopted_by"],
                "approved_by": policy["approved_by"], "intact": not problems}

    def policy_versions(self) -> list[dict[str, Any]]:
        return self.db.query("SELECT * FROM people_policy_versions ORDER BY version")

    def _binding(self) -> dict[str, Any] | None:
        policy, problems = self._policy()
        if problems:
            return {"integrity": "identity policy records are not intact"}
        if policy is None or not policy["enforce"]:
            return None
        return {"policy_version": policy["version"], "policy_hash": policy["content_hash"]}

    # ---- integrity ------------------------------------------------------------------------- #

    def _audit_trail(self, *actions: str) -> dict[tuple[str, str], list[dict[str, Any]]]:
        """The payloads of the audit log's ``actions`` entries by (action, entity id), oldest
        first: the evidence a record changed through a record method is checked against."""
        out: dict[tuple[str, str], list[dict[str, Any]]] = {}
        marks = ", ".join("?" for _ in actions)
        for e in self.db.query(f"SELECT action, entity_id, payload_json FROM audit_log WHERE action IN ({marks}) ORDER BY seq", actions):
            out.setdefault((e["action"], e["entity_id"]), []).append(loads(e["payload_json"]) or {})
        return out

    def _person_problems(self) -> list[str]:
        out = []
        for p in self.db.query("SELECT * FROM people_persons ORDER BY created_at, id"):
            if self._person_hash(p) != p["content_hash"]:
                out.append(f"identity {p['login']} ({p['id']}) does not hash to its recorded content hash")
            if p["status"] == "active" and self.db.one("SELECT seq FROM audit_log WHERE entity_type='people_person' AND entity_id=? "
                                                       "AND action='people.person_deactivated' LIMIT 1", (p["id"],)):
                out.append(f"identity {p['login']} ({p['id']}) is active although its deactivation was recorded")
        return out

    def _grant_problems(self) -> list[str]:
        out = []
        prev = GENESIS
        bootstraps = 0
        for n, g in enumerate(self.db.query("SELECT * FROM people_grants ORDER BY seq"), start=1):
            label = f"role grant {g['id']} ({g['login']}: {g['role']})"
            if g["seq"] != n or g["prev_hash"] != prev:
                out.append(f"{label} breaks the grant hash chain")
            if self._grant_hash(g) != g["content_hash"]:
                out.append(f"{label} does not hash to its recorded content hash")
            prev = g["content_hash"]
            person = self._person_by_id(g["person_id"])
            if person is None or person["login"] != g["login"]:
                out.append(f"{label} names an identity that is not registered under that login")
            if g["origin"] == "bootstrap":
                bootstraps += 1
                if bootstraps > 1 or g["role"] != OWNER_ROLE or g["scope"] != "entity" or g["request_id"] or g["approval_id"]:
                    out.append(f"{label} is not the single owner bootstrap")
            else:
                ap = self.db.one("SELECT * FROM approvals WHERE id=?", (g["approval_id"],))
                req = self.db.one("SELECT * FROM people_grant_requests WHERE id=?", (g["request_id"],))
                backed = (ap is not None and req is not None and ap["status"] == "consumed" and ap["operation"] == OP_GRANT
                          and ap["subject_id"] == req["id"] and req["status"] == "granted" and req["grant_id"] == g["id"]
                          and all(req[k] == g[k] for k in ("person_id", "role", "scope", "project_id", "effective_from", "effective_to"))
                          and self._request_hash(req) == req["content_hash"] and g["granted_by"] == ap["approver"]
                          and ((loads(ap["manifest_json"]) or {}).get("bindings") or {}).get("request_hash") == req["content_hash"]
                          and all(_norm(x) != g["login"] for x in (ap["requested_by"], ap["approver"], ap["consumed_by"], req["requested_by"])))
                if not backed:
                    out.append(f"{label} is not backed by a consumed people.grant_role approval of its request")
            if g["revoked_at"] is not None:
                ap = self.db.one("SELECT * FROM approvals WHERE id=?", (g["revocation_approval_id"],))
                rev = self.db.one("SELECT * FROM people_revocation_requests WHERE id=?", (g["revocation_request_id"],))
                if not (ap and rev and ap["status"] == "consumed" and ap["operation"] == OP_REVOKE and ap["subject_id"] == rev["id"]
                        and rev["grant_id"] == g["id"] and rev["status"] == "executed" and rev["approval_id"] == ap["id"]):
                    out.append(f"{label} is revoked without a consumed people.revoke_role approval")
        # a revocation recorded as executed must have revoked its grant
        for rev in self.db.query("SELECT * FROM people_revocation_requests WHERE status='executed'"):
            g = self.db.one("SELECT revoked_at, revocation_request_id FROM people_grants WHERE id=?", (rev["grant_id"],))
            if g is None or g["revoked_at"] is None or g["revocation_request_id"] != rev["id"]:
                out.append(f"revocation {rev['id']} is executed but grant {rev['grant_id']} is not revoked by it")
        # as must every consumed revocation approval and every audited revocation: a revocation
        # undone with the triggers dropped (its request deleted, the grant's columns cleared) shows
        for ap in self.db.query("SELECT id, subject_id FROM approvals WHERE operation=? AND status='consumed' ORDER BY id", (OP_REVOKE,)):
            rev = self.db.one("SELECT * FROM people_revocation_requests WHERE id=?", (ap["subject_id"],))
            g = self.db.one("SELECT * FROM people_grants WHERE id=?", (rev["grant_id"],)) if rev else None
            if not (rev and g and rev["status"] == "executed" and rev["approval_id"] == ap["id"] and g["revoked_at"] is not None
                    and g["revocation_request_id"] == rev["id"] and g["revocation_approval_id"] == ap["id"]):
                out.append(f"people.revoke_role approval {ap['id']} was consumed, but its revocation {ap['subject_id']} did not revoke its grant")
        for (_, grant_id), payloads in self._audit_trail("people.role_revoked").items():
            g = self.db.one("SELECT * FROM people_grants WHERE id=?", (grant_id,))
            for x in payloads:
                if not (g and g["revoked_at"] == x.get("revoked_at") and g["revocation_request_id"] == x.get("revocation_id")
                        and g["revocation_approval_id"] == x.get("approval_id")):
                    out.append(f"role grant {grant_id} is not revoked as its audited revocation {x.get('revocation_id')} recorded")
        for req in self.db.query("SELECT * FROM people_grant_requests ORDER BY requested_at, id"):
            if self._request_hash(req) != req["content_hash"]:
                out.append(f"grant request {req['id']} does not hash to its recorded content hash")
        return out

    def _delegation_problems(self) -> list[str]:
        out = []
        # a delegation's status is not in its hash, and a revoked one keeps its consumed approval:
        # its audited revocation or cancellation decides
        ends = self._audit_trail("people.delegation_revoked", "people.request_cancelled")
        for d in self.db.query("SELECT * FROM people_delegations ORDER BY requested_at, id"):
            label = f"delegation {d['id']} ({d['from_login']} -> {d['to_login']}: {d['role']})"
            if self._delegation_hash(d) != d["content_hash"]:
                out.append(f"{label} does not hash to its recorded content hash")
            if d["role"] == OWNER_ROLE:
                out.append(f"{label} delegates the owner role")
            if d["status"] in ("active", "revoked") or d["approval_id"]:
                ap = self.db.one("SELECT * FROM approvals WHERE id=?", (d["approval_id"],))
                if not (ap and ap["status"] == "consumed" and ap["operation"] == OP_DELEGATE and ap["subject_id"] == d["id"]
                        and ((loads(ap["manifest_json"]) or {}).get("bindings") or {}).get("delegation_hash") == d["content_hash"]
                        and all(_norm(x) != d["to_login"] for x in (ap["requested_by"], ap["approver"], ap["consumed_by"]))):
                    out.append(f"{label} is active without a consumed people.delegate approval")
            if ("people.delegation_revoked", d["id"]) in ends and d["status"] != "revoked":
                out.append(f"{label} is {d['status']} although its revocation was recorded")
            if ("people.request_cancelled", d["id"]) in ends and d["status"] != "cancelled":
                out.append(f"{label} is {d['status']} although its cancellation was recorded")
        return out

    def _membership_problems(self) -> list[str]:
        """Project memberships (what lets a project-scoped grant or delegation count) that their
        audit entries do not back: one added without add_membership, or active after its end."""
        out = []
        trail = self._audit_trail("people.membership_added", "people.membership_ended")
        for m in self.db.query("SELECT m.*, p.login FROM people_memberships m LEFT JOIN people_persons p ON p.id = m.person_id "
                               "ORDER BY m.added_at, m.id"):
            label = f"project membership {m['id']} ({m['login']} on {m['project_id']})"
            if not any(x.get("person_id") == m["person_id"] and x.get("project_id") == m["project_id"]
                       for x in trail.get(("people.membership_added", m["id"]), [])):
                out.append(f"{label} is not backed by its audited addition")
            if m["status"] != "ended" and ("people.membership_ended", m["id"]) in trail:
                out.append(f"{label} is {m['status']} although its end was recorded")
        return out

    def _authority_problems(self) -> list[str]:
        """Problems with the records that confer authority: identities, project memberships,
        grants and their revocations, delegations and the policy chain.  While enforcing, any of
        them makes every governor check refuse."""
        return (self._person_problems() + self._membership_problems() + self._grant_problems() + self._delegation_problems()
                + self._policy()[1])

    def _self_approval_problems(self) -> list[str]:
        """Self-approvals made under a segregating policy that were never recorded for review,
        and reviews the audit log does not record as made by an outside party other than the
        approver (written with the trigger dropped)."""
        out = []
        reviews = self._audit_trail("people.self_approval_reviewed")
        for s in self.db.query("SELECT * FROM people_self_approvals WHERE reviewed_at IS NOT NULL ORDER BY recorded_at, id"):
            reviewer = self._person_row(s["reviewed_by"])
            if not any(x.get("reviewed_by") == s["reviewed_by"] and x.get("reviewed_at") == s["reviewed_at"]
                       and x.get("approval_id") == s["approval_id"] for x in reviews.get(("people.self_approval_reviewed", s["id"]), [])):
                out.append(f"the self-approval of approval {s['approval_id']} reads as reviewed by {s['reviewed_by']} at {s['reviewed_at']}, "
                           "which the audit log does not record")
            elif not (reviewer and reviewer["kind"] == "person" and reviewer["external"] and reviewer["login"] != s["login"]):
                out.append(f"the self-approval of approval {s['approval_id']} reads as reviewed by {s['reviewed_by']}, who is not an outside "
                           "party other than its approver")
        rows = self.db.query("SELECT id, operation, requested_by, approver, manifest_json FROM approvals "
                             "WHERE approver IS NOT NULL AND json_extract(manifest_json, '$.governance.people.policy_version') IS NOT NULL")
        for a in rows:
            if _norm(a["approver"]) != _norm(a["requested_by"]):
                continue
            bound = ((loads(a["manifest_json"]) or {}).get("governance") or {}).get(PLUGIN_NAME) or {}
            seg = self.db.scalar("SELECT segregate FROM people_policy_versions WHERE version=?", (bound.get("policy_version"),))
            if seg and self.db.one("SELECT id FROM people_self_approvals WHERE approval_id=?", (a["id"],)) is None:
                out.append(f"approval {a['id']} ({a['operation']}) was approved by its own requester {a['approver']} under a segregating "
                           "identity policy without a self-approval record")
        return out

    def integrity_problems(self) -> list[str]:
        """Everything that no longer verifies, as readable sentences (empty when intact)."""
        return self._authority_problems() + self._self_approval_problems()

    def authority_problems(self) -> list[str]:
        """The problems that make every governor check fail closed while enforcing (identities,
        project memberships, grants and their revocations, delegations and the policy chain),
        for other surfaces that answer to the registry -- the Ricky SDK refuses every call on the
        same evidence."""
        return self._authority_problems()

    def _require_intact(self) -> None:
        problems = self._authority_problems()
        if problems:
            raise IdentityIntegrityError("identity records are not intact, so identity checks fail closed: " + "; ".join(problems[:5]))

    # ---- actor checks for record methods --------------------------------------------------- #

    @staticmethod
    def _actor(actor: Any) -> str:
        return _text(actor, "actor", max_length=MAX_NAME_LENGTH)

    def _require_active_actor(self, who: str, what: str) -> None:
        """While enforcing, the actor of a record method is an active registered identity."""
        if not self.enforcing():
            return
        self._require_intact()
        if not self.is_active(who):
            raise IdentityRefused(f"identity enforcement is on: {who!r} is not an active registered identity, so it cannot {what}")

    def _require_admin(self, who: str, what: str) -> None:
        """While enforcing, identity administration (registering identities, project membership)
        is done by an active owner."""
        if not self.enforcing():
            return
        self._require_active_actor(who, what)
        if not self._holds_by_grant(self._person_row(who), OWNER_ROLE, None):
            raise IdentityRefused(f"identity enforcement is on: only an active owner can {what}; {who!r} does not hold owner")

    # ---- identities ------------------------------------------------------------------------ #

    def _insert_person(self, login: str, display_name: str, kind: str, external: bool, who: str) -> dict[str, Any]:
        row = {"id": new_id("psn"), "login": login, "display_name": display_name, "kind": kind, "external": 1 if external else 0,
               "created_by": who, "created_at": self._stamp()}
        row["content_hash"] = self._person_hash(row)
        # audited first: the storage guard admits an identity only with its audit entry
        self.audit.record(who, "people.person_registered", "people_person", row["id"], {
            "login": login, "display_name": display_name, "kind": kind, "external": row["external"], "content_hash": row["content_hash"]})
        self.db.execute("INSERT INTO people_persons (id, login, display_name, kind, external, status, content_hash, created_by, created_at) "
                        "VALUES (?,?,?,?,?,'active',?,?,?)",
                        (row["id"], login, display_name, kind, row["external"], row["content_hash"], who, row["created_at"]))
        return self._person_row(login)

    def register_person(self, login: str, display_name: str, *, actor: str, kind: str = "person", external: bool = False) -> dict[str, Any]:
        """Register an identity: a person (``external=True`` for an outside party such as the
        external accountant) or a service identity (the payment worker, Ricky), which can
        request and execute but never approve.  The login is normalized and unique; while
        enforcing, only an active owner registers identities.  Registering grants nothing."""
        who = self._actor(actor)
        key = normalize_login(login)
        name = _text(display_name, "display name", max_length=MAX_NAME_LENGTH)
        if kind not in ("person", "service"):
            raise PeopleError(f"kind must be 'person' or 'service', got {kind!r}")
        _flag(external, "external")
        if kind == "service" and external:
            raise PeopleError("a service identity is never an outside party; outside parties are persons")
        with self.db.transaction():
            self._require_admin(who, "register an identity")
            if self._person_row(key) is not None:
                raise PeopleError(f"login {key!r} is already registered")
            self._insert_person(key, name, kind, external, who)
        return self.person_for(key)

    def bootstrap_owner(self, login: str, display_name: str | None = None, *, actor: str | None = None) -> dict[str, Any]:
        """Record the first owner: the identity (registered now when ``display_name`` is given)
        receives an open-ended, entity-scoped owner grant without an approval.  Exactly once per
        workspace, and only while no active person holds owner and identity enforcement is off --
        afterwards owners are granted only through ``people.grant_role``."""
        key = normalize_login(login)
        who = self._actor(actor) if actor is not None else key
        with self.db.transaction():
            if self.db.scalar("SELECT COUNT(*) FROM people_grants WHERE origin='bootstrap'"):
                raise PeopleError("the owner was already bootstrapped in this workspace; grant owner through people.grant_role")
            if self.enforcing():
                raise PeopleError("identity enforcement is on; the owner is bootstrapped only while it is off")
            owners = self._active_owners()
            if owners:
                raise PeopleError(f"an active person already holds owner ({', '.join(o['login'] for o in owners)}); bootstrap is for an empty registry")
            person = self._person_row(key)
            if person is None:
                person = self._insert_person(key, _text(display_name, "display name", max_length=MAX_NAME_LENGTH), "person", False, who)
            elif person["status"] != "active" or person["kind"] != "person" or person["external"]:
                raise PeopleError(f"{key} must be an active, internal person to be the owner")
            grant = self._insert_grant(person, role=OWNER_ROLE, scope="entity", project_id=None, effective_from=self._today().isoformat(),
                                       effective_to=None, origin="bootstrap", request_id=None, approval_id=None, granted_by=who)
        return {"person": self.person_for(key), "grant": grant}

    def deactivate_person(self, login: str, *, reason: str, actor: str) -> dict[str, Any]:
        """Deactivate an identity.  It reduces privilege, so it takes effect immediately (no
        approval) and is audited: the identity stops requesting, approving and executing, its
        grants and delegations stop counting, and approvals it granted can no longer execute
        while enforcing.  Final -- a returning person gets a new login.  While enforcing, an
        active owner (or the person themself) deactivates, and never the last active owner, nor
        the last one whose owner grant has no end date."""
        who = self._actor(actor)
        why = _text(reason, "a deactivation reason")
        with self.db.transaction() as conn:
            p = self._person(login)
            if p["status"] != "active":
                raise PeopleError(f"identity {p['login']} is already inactive")
            if self.enforcing():
                if _norm(who) == p["login"]:
                    self._require_active_actor(who, "deactivate an identity")
                else:
                    self._require_admin(who, "deactivate another identity")
                owners = self._active_owners()
                if owners and all(o["id"] == p["id"] for o in owners):
                    raise PeopleError(f"{p['login']} is the last active owner; while identity enforcement is on the workspace keeps one "
                                      "(grant owner to another person first, or turn enforcement off)")
                lasting = self._active_owners(lasting=True)
                if lasting and all(o["id"] == p["id"] for o in lasting):
                    raise PeopleError(f"{p['login']} is the last active owner whose owner grant has no end date; while identity enforcement "
                                      "is on the workspace keeps one, because an owner grant with an end date lapses on its own (grant owner "
                                      "without an end date to another person first, or turn enforcement off)")
            now = self._stamp()
            # audited first: the storage guard admits a deactivation only with its audit entry
            self.audit.record(who, "people.person_deactivated", "people_person", p["id"], {"login": p["login"], "deactivated_at": now, "reason": why})
            conn.execute("UPDATE people_persons SET status='inactive', deactivated_by=?, deactivated_at=?, deactivation_reason=? WHERE id=? AND status='active'",
                         (who, now, why, p["id"]))
        return self.person_for(p["login"])

    # ---- project membership ---------------------------------------------------------------- #

    def add_membership(self, login: str, project_id: str, *, actor: str) -> dict[str, Any]:
        """Put an active identity on a project.  Membership confers nothing by itself; it is
        what lets a project-scoped grant or delegation count.  While enforcing, an active owner
        adds members."""
        who = self._actor(actor)
        with self.db.transaction() as conn:
            self._require_admin(who, "add project members")
            p = self._person(login)
            if p["status"] != "active":
                raise PeopleError(f"identity {p['login']} is inactive")
            if not self._project_exists(project_id):
                raise PeopleError(f"unknown project {project_id!r}")
            if self._membership(p["id"], project_id) is not None:
                raise PeopleError(f"{p['login']} is already a member of project {project_id}")
            mid, now = new_id("pmb"), self._stamp()
            self.audit.record(who, "people.membership_added", "people_membership", mid, {"person_id": p["id"], "login": p["login"], "project_id": project_id})
            conn.execute("INSERT INTO people_memberships (id, person_id, project_id, status, added_by, added_at) VALUES (?,?,?,'active',?,?)",
                         (mid, p["id"], project_id, who, now))
        return self.db.one("SELECT * FROM people_memberships WHERE id=?", (mid,))

    def end_membership(self, login: str, project_id: str, *, reason: str, actor: str) -> dict[str, Any]:
        """Take an identity off a project (reduces privilege: immediate, audited).  Its
        project-scoped grants and delegations on that project stop counting."""
        who = self._actor(actor)
        why = _text(reason, "a reason")
        with self.db.transaction() as conn:
            p = self._person(login)
            if _norm(who) != p["login"]:
                self._require_admin(who, "end another identity's project membership")
            else:
                self._require_active_actor(who, "end a project membership")
            m = self._membership(p["id"], project_id)
            if m is None:
                raise PeopleError(f"{p['login']} is not a member of project {project_id}")
            now = self._stamp()
            self.audit.record(who, "people.membership_ended", "people_membership", m["id"], {"ended_at": now, "reason": why})
            conn.execute("UPDATE people_memberships SET status='ended', ended_by=?, ended_at=?, end_reason=? WHERE id=?", (who, now, why, m["id"]))
        return self.db.one("SELECT * FROM people_memberships WHERE id=?", (m["id"],))

    def memberships(self, project_id: str | None = None) -> list[dict[str, Any]]:
        if project_id:
            return self.db.query("SELECT * FROM people_memberships WHERE project_id=? ORDER BY added_at, id", (project_id,))
        return self.db.query("SELECT * FROM people_memberships ORDER BY added_at, id")

    # ---- grants ---------------------------------------------------------------------------- #

    def _grant_facts_problems(self, person: dict[str, Any], role: str, project_id: str | None, effective_from: str,
                              effective_to: str | None, *, day: _dt.date) -> list[str]:
        """Why this grant could not be recorded today (empty when it could)."""
        problems = []
        if person["status"] != "active":
            problems.append(f"identity {person['login']} is inactive")
        if role not in ROLE_AUTHORITY:
            problems.append(f"role {role!r} is no longer a Cipher role")
        if role == OWNER_ROLE:
            if project_id is not None:
                problems.append("the owner role is granted at entity scope only")
            if person["kind"] != "person" or person["external"]:
                problems.append("the owner role is held only by an internal person (never a service identity or an outside party)")
        if project_id is not None:
            if not self._project_exists(project_id):
                problems.append(f"unknown project {project_id!r}")
            elif self._membership(person["id"], project_id) is None:
                problems.append(f"{person['login']} is not a member of project {project_id}; add the membership first")
        if effective_to is not None and effective_to < day.isoformat():
            problems.append(f"the grant window ends {effective_to}, before today")
        for g in self.db.query("SELECT * FROM people_grants WHERE person_id=? AND role=? AND revoked_at IS NULL AND project_id IS ?",
                               (person["id"], role, project_id)):
            if _overlaps(effective_from, effective_to, g["effective_from"], g["effective_to"]):
                problems.append(f"{person['login']} already holds {role} in this scope from {g['effective_from']} to {g['effective_to'] or 'open-ended'} "
                                f"(grant {g['id']}); grants of one role in one scope never overlap")
        return problems

    def _insert_grant(self, person: dict[str, Any], *, role: str, scope: str, project_id: str | None, effective_from: str,
                      effective_to: str | None, origin: str, request_id: str | None, approval_id: str | None, granted_by: str) -> dict[str, Any]:
        head = self.db.one("SELECT seq, content_hash FROM people_grants ORDER BY seq DESC LIMIT 1")
        row = {"seq": (head["seq"] + 1) if head else 1, "id": new_id("pgr"), "request_id": request_id, "person_id": person["id"],
               "login": person["login"], "role": role, "scope": scope, "project_id": project_id, "effective_from": effective_from,
               "effective_to": effective_to, "origin": origin, "approval_id": approval_id, "granted_by": granted_by,
               "created_at": self._stamp(), "prev_hash": head["content_hash"] if head else GENESIS}
        row["content_hash"] = self._grant_hash(row)
        self.audit.record(granted_by, "people.role_granted", "people_grant", row["id"], {
            "seq": row["seq"], "login": row["login"], "role": role, "scope": scope, "project_id": project_id, "effective_from": effective_from,
            "effective_to": effective_to, "origin": origin, "approval_id": approval_id, "content_hash": row["content_hash"]})
        self.db.execute(
            """INSERT INTO people_grants (id, seq, request_id, person_id, login, role, scope, project_id, effective_from, effective_to, origin,
               approval_id, granted_by, created_at, prev_hash, content_hash) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (row["id"], row["seq"], request_id, person["id"], person["login"], role, scope, project_id, effective_from, effective_to, origin,
             approval_id, granted_by, row["created_at"], row["prev_hash"], row["content_hash"]))
        return self.db.one("SELECT * FROM people_grants WHERE id=?", (row["id"],))

    def request_grant(self, login: str, role: str, *, reason: str, actor: str, project_id: str | None = None,
                      effective_from: str | None = None, effective_to: str | None = None) -> dict[str, Any]:
        """Record a pending grant of ``role`` to an identity, at entity scope or on one project
        (``project_id``), effective from a date (default today) to an optional inclusive end
        date.  It takes effect only through a ``people.grant_role`` approval.  The grantee can
        never request their own grant (no self-granting, even an owner)."""
        who = self._actor(actor)
        why = _text(reason, "a reason")
        role = _role(role)
        start = _date(effective_from, "effective_from") if effective_from is not None else self._today()
        end = _date(effective_to, "effective_to") if effective_to is not None else None
        if end is not None and end < start:
            raise PeopleError(f"the grant window ends {end.isoformat()} before it starts {start.isoformat()}")
        if project_id is not None and not isinstance(project_id, str):
            raise PeopleError("project_id must be a project id")
        with self.db.transaction() as conn:
            self._require_active_actor(who, "request a role grant")
            p = self._person(login)
            if _norm(who) == p["login"]:
                raise IdentityRefused(f"no self-granting: {who!r} cannot request a role grant to themselves")
            problems = self._grant_facts_problems(p, role, project_id, start.isoformat(), end.isoformat() if end else None, day=self._today())
            if problems:
                raise PeopleError(f"cannot request {role} for {p['login']}: " + "; ".join(problems))
            scope = "project" if project_id is not None else "entity"
            pending = conn.execute("SELECT id FROM people_grant_requests WHERE person_id=? AND role=? AND scope=? AND project_id IS ? AND status='pending'",
                                   (p["id"], role, scope, project_id)).fetchone()
            if pending is not None:
                raise PeopleError(f"a grant of {role} to {p['login']} in this scope is already pending ({pending['id']})")
            row = {"id": new_id("pgq"), "person_id": p["id"], "role": role, "scope": scope, "project_id": project_id,
                   "effective_from": start.isoformat(), "effective_to": end.isoformat() if end else None, "reason": why,
                   "requested_by": who, "requested_at": self._stamp()}
            row["content_hash"] = self._request_hash(row)
            self.audit.record(who, "people.grant_requested", "people_grant_request", row["id"], {
                "login": p["login"], "role": role, "scope": scope, "project_id": project_id, "effective_from": row["effective_from"],
                "effective_to": row["effective_to"], "reason": why, "content_hash": row["content_hash"]})
            conn.execute(
                """INSERT INTO people_grant_requests (id, person_id, role, scope, project_id, effective_from, effective_to, reason, content_hash,
                   status, requested_by, requested_at) VALUES (?,?,?,?,?,?,?,?,?,'pending',?,?)""",
                (row["id"], p["id"], role, scope, project_id, row["effective_from"], row["effective_to"], why, row["content_hash"], who, row["requested_at"]))
        return self.db.one("SELECT * FROM people_grant_requests WHERE id=?", (row["id"],))

    def request_revocation(self, grant_id: str, *, reason: str, actor: str) -> dict[str, Any]:
        """Record a pending revocation of a live grant; it takes effect through a
        ``people.revoke_role`` approval.  A person never decides their own authority, so the
        holder cannot request it (to drop everything at once, deactivate the identity)."""
        who = self._actor(actor)
        why = _text(reason, "a reason")
        with self.db.transaction() as conn:
            self._require_active_actor(who, "request a revocation")
            g = self._row("people_grants", grant_id, "role grant")
            if g["revoked_at"] is not None:
                raise PeopleError(f"grant {grant_id} is already revoked")
            if _norm(who) == g["login"]:
                raise IdentityRefused(f"{who!r} cannot request the revocation of their own grant; a person never decides their own authority")
            problems = self._revocation_problems(g)
            if problems:
                raise PeopleError("; ".join(problems))
            pending = conn.execute("SELECT id FROM people_revocation_requests WHERE grant_id=? AND status='pending'", (grant_id,)).fetchone()
            if pending is not None:
                raise PeopleError(f"a revocation of grant {grant_id} is already pending ({pending['id']})")
            rid, now = new_id("prv"), self._stamp()
            self.audit.record(who, "people.revocation_requested", "people_revocation_request", rid, {"grant_id": grant_id, "login": g["login"],
                                                                                                     "role": g["role"], "reason": why})
            conn.execute("INSERT INTO people_revocation_requests (id, grant_id, reason, status, requested_by, requested_at) VALUES (?,?,?,'pending',?,?)",
                         (rid, grant_id, why, who, now))
        return self.db.one("SELECT * FROM people_revocation_requests WHERE id=?", (rid,))

    def _revocation_problems(self, g: dict[str, Any]) -> list[str]:
        problems = []
        if g["revoked_at"] is not None:
            problems.append(f"grant {g['id']} is already revoked")
        if g["role"] == OWNER_ROLE and self.enforcing():
            owners = self._active_owners()
            lasting = self._active_owners(lasting=True)
            if owners and all(o["id"] == g["person_id"] for o in owners):
                problems.append(f"grant {g['id']} makes {g['login']} the last active owner; while identity enforcement is on the workspace keeps one")
            elif g["effective_to"] is None and lasting and all(o["id"] == g["person_id"] for o in lasting):
                problems.append(f"grant {g['id']} makes {g['login']} the last active owner whose owner grant has no end date; while identity "
                                "enforcement is on the workspace keeps one, because an owner grant with an end date lapses on its own")
        return problems

    def grants(self, login: str | None = None) -> list[dict[str, Any]]:
        """Every grant (live, expired, revoked) with whether it counts today."""
        if login is not None:
            p = self._person(login)
            rows = self.db.query("SELECT * FROM people_grants WHERE person_id=? ORDER BY seq", (p["id"],))
        else:
            rows = self.db.query("SELECT * FROM people_grants ORDER BY seq")
        day = self._today()
        for g in rows:
            g["effective_today"] = g["revoked_at"] is None and self._effective(g, day)
        return rows

    def grant_requests(self, status: str | None = None) -> list[dict[str, Any]]:
        if status:
            return self.db.query("SELECT * FROM people_grant_requests WHERE status=? ORDER BY requested_at, id", (status,))
        return self.db.query("SELECT * FROM people_grant_requests ORDER BY requested_at, id")

    # ---- delegations ----------------------------------------------------------------------- #

    def _delegation_facts_problems(self, frm: dict[str, Any], to: dict[str, Any], role: str, project_id: str | None, effective_to: str,
                                   *, day: _dt.date) -> list[str]:
        problems = []
        if role == OWNER_ROLE:
            problems.append("the owner role is never delegated")
        if role not in ROLE_AUTHORITY:
            problems.append(f"role {role!r} is no longer a Cipher role")
        if frm["id"] == to["id"]:
            problems.append("a delegation goes from one person to another")
        if frm["status"] != "active":
            problems.append(f"delegator {frm['login']} is inactive")
        if to["status"] != "active":
            problems.append(f"delegate {to['login']} is inactive")
        if to["kind"] != "person":
            problems.append(f"{to['login']} is a service identity; authority is delegated only to persons (services never approve)")
        if project_id is not None:
            if not self._project_exists(project_id):
                problems.append(f"unknown project {project_id!r}")
            elif self._membership(to["id"], project_id) is None:
                problems.append(f"delegate {to['login']} is not a member of project {project_id}")
        if role != OWNER_ROLE and not self._holds_by_grant(frm, role, project_id, day):
            via_delegation = self._holds_by_delegation(frm, role, project_id, day)
            problems.append(f"{frm['login']} does not hold {role} by their own grant in this scope"
                            + ("; a delegated role is never delegated again" if via_delegation else ""))
        if effective_to < day.isoformat():
            problems.append(f"the delegation window ends {effective_to}, before today")
        if role != OWNER_ROLE and to["kind"] == "person" and self._holds_by_grant(to, role, project_id, day):
            problems.append(f"{to['login']} already holds {role} in this scope by grant")
        return problems

    def request_delegation(self, from_login: str, to_login: str, role: str, *, effective_to: str, reason: str, actor: str,
                           project_id: str | None = None, effective_from: str | None = None) -> dict[str, Any]:
        """Record a pending delegation of one role from one person to another, for a window
        (``effective_from``, default today, to the required inclusive ``effective_to``) at
        entity scope or on one project.  Never the owner role, never to a service identity,
        and no re-delegation: the delegator holds the role by their own grant.  It takes effect
        through a ``people.delegate`` approval; the delegate cannot request it."""
        who = self._actor(actor)
        why = _text(reason, "a reason")
        role = _role(role)
        if role == OWNER_ROLE:
            raise PeopleError("the owner role is never delegated; grant it through people.grant_role instead")
        start = _date(effective_from, "effective_from") if effective_from is not None else self._today()
        end = _date(effective_to, "effective_to")
        if end < start:
            raise PeopleError(f"the delegation window ends {end.isoformat()} before it starts {start.isoformat()}")
        if project_id is not None and not isinstance(project_id, str):
            raise PeopleError("project_id must be a project id")
        with self.db.transaction() as conn:
            self._require_active_actor(who, "request a delegation")
            frm, to = self._person(from_login), self._person(to_login)
            if _norm(who) == to["login"]:
                raise IdentityRefused(f"no self-granting: {who!r} cannot request a delegation to themselves")
            problems = self._delegation_facts_problems(frm, to, role, project_id, end.isoformat(), day=self._today())
            if problems:
                raise PeopleError(f"cannot delegate {role} from {frm['login']} to {to['login']}: " + "; ".join(problems))
            for d in self.db.query("SELECT * FROM people_delegations WHERE to_person_id=? AND role=? AND project_id IS ? AND status IN ('pending','active')",
                                   (to["id"], role, project_id)):
                if _overlaps(start.isoformat(), end.isoformat(), d["effective_from"], d["effective_to"]):
                    raise PeopleError(f"{to['login']} already has a {d['status']} delegation of {role} in this scope for an overlapping window ({d['id']})")
            scope = "project" if project_id is not None else "entity"
            row = {"id": new_id("pdl"), "from_person_id": frm["id"], "to_person_id": to["id"], "from_login": frm["login"], "to_login": to["login"],
                   "role": role, "scope": scope, "project_id": project_id, "effective_from": start.isoformat(), "effective_to": end.isoformat(),
                   "reason": why, "requested_by": who, "requested_at": self._stamp()}
            row["content_hash"] = self._delegation_hash(row)
            self.audit.record(who, "people.delegation_requested", "people_delegation", row["id"], {
                "from": frm["login"], "to": to["login"], "role": role, "scope": scope, "project_id": project_id,
                "effective_from": row["effective_from"], "effective_to": row["effective_to"], "reason": why, "content_hash": row["content_hash"]})
            conn.execute(
                """INSERT INTO people_delegations (id, from_person_id, to_person_id, from_login, to_login, role, scope, project_id, effective_from,
                   effective_to, reason, content_hash, status, requested_by, requested_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,'pending',?,?)""",
                (row["id"], frm["id"], to["id"], frm["login"], to["login"], role, scope, project_id, row["effective_from"], row["effective_to"],
                 why, row["content_hash"], who, row["requested_at"]))
        return self.db.one("SELECT * FROM people_delegations WHERE id=?", (row["id"],))

    def revoke_delegation(self, delegation_id: str, *, reason: str, actor: str) -> dict[str, Any]:
        """End an active delegation now (reduces privilege: immediate, audited).  While
        enforcing, the delegator, the delegate or an active owner ends it."""
        who = self._actor(actor)
        why = _text(reason, "a reason")
        with self.db.transaction() as conn:
            d = self._row("people_delegations", delegation_id, "delegation")
            if d["status"] != "active":
                raise PeopleError(f"delegation {delegation_id} is {d['status']}, not active")
            if _norm(who) in (d["from_login"], d["to_login"]):
                self._require_active_actor(who, "revoke a delegation")
            else:
                self._require_admin(who, "revoke another person's delegation")
            now = self._stamp()
            self.audit.record(who, "people.delegation_revoked", "people_delegation", d["id"], {"ended_at": now, "reason": why})
            conn.execute("UPDATE people_delegations SET status='revoked', ended_by=?, ended_at=?, end_reason=? WHERE id=? AND status='active'",
                         (who, now, why, d["id"]))
        return self.db.one("SELECT * FROM people_delegations WHERE id=?", (delegation_id,))

    def delegations(self, status: str | None = None) -> list[dict[str, Any]]:
        if status:
            return self.db.query("SELECT * FROM people_delegations WHERE status=? ORDER BY requested_at, id", (status,))
        return self.db.query("SELECT * FROM people_delegations ORDER BY requested_at, id")

    # ---- policy drafts --------------------------------------------------------------------- #

    def prepare_policy(self, *, enforce: bool, reason: str, actor: str, segregate: bool = True,
                       solo_owner_self_approval: bool = False) -> dict[str, Any]:
        """Draft an identity policy: ``enforce`` turns identity checks on for every approval;
        ``segregate`` makes the approver differ from the requester; ``solo_owner_self_approval``
        lets an active owner approve their own request as a recorded exception that an outside
        party reviews (it is an exception to segregation, so it needs ``segregate``).  Adopted
        only through a ``people.set_policy`` approval."""
        who = self._actor(actor)
        why = _text(reason, "a reason")
        rules = {"enforce": _flag(enforce, "enforce"), "segregate": _flag(segregate, "segregate"),
                 "solo_owner_self_approval": _flag(solo_owner_self_approval, "solo_owner_self_approval")}
        if rules["solo_owner_self_approval"] and not rules["segregate"]:
            raise PeopleError("solo-owner self-approval is an exception to segregation; it needs segregate=True")
        with self.db.transaction() as conn:
            self._require_active_actor(who, "prepare an identity policy")
            current = self._policy()[0]
            if current is not None and loads(current["rules_json"]) == rules:
                raise PeopleError(f"identity policy version {current['version']} already has these rules")
            row = {"id": new_id("ppd"), "rules_json": canonical_json(rules), "reason": why, "prepared_by": who, "prepared_at": self._stamp()}
            row["content_hash"] = self._draft_hash(row)
            self.audit.record(who, "people.policy_prepared", "people_policy_draft", row["id"], {"rules": rules, "reason": why, "content_hash": row["content_hash"]})
            conn.execute("INSERT INTO people_policy_drafts (id, rules_json, reason, content_hash, status, prepared_by, prepared_at) VALUES (?,?,?,?,'pending',?,?)",
                         (row["id"], row["rules_json"], why, row["content_hash"], who, row["prepared_at"]))
        return self._draft(row["id"])

    def _draft(self, draft_id: str) -> dict[str, Any]:
        d = self._row("people_policy_drafts", draft_id, "policy draft")
        d["rules"] = loads(d["rules_json"])
        return d

    def _policy_draft_problems(self, draft: dict[str, Any], *, requester: str | None = None) -> list[str]:
        """Why the draft could not be adopted now: enforcement needs an active owner whose owner
        grant has no end date; with segregation an active person other than the requester; with
        solo-owner self-approval an active outside party to review the exceptions."""
        problems = []
        rules = loads(draft["rules_json"]) or {}
        if rules.get("enforce"):
            if not self._active_owners():
                problems.append("identity enforcement needs at least one active owner (bootstrap_owner, or grant owner first)")
            elif not self._active_owners(lasting=True):
                problems.append("identity enforcement needs an active owner whose owner grant has no end date (an owner grant with an end "
                                "date lapses on its own, and the workspace could not be governed afterwards); grant owner without an end date first")
            if rules.get("segregate"):
                others = [p for p in self.db.query("SELECT login FROM people_persons WHERE status='active' AND kind='person'")
                          if requester is None or p["login"] != requester]
                if not others:
                    problems.append("segregated enforcement needs an active person other than the requester to approve "
                                    "(for a sole owner, the outside party such as the external accountant)")
            if rules.get("solo_owner_self_approval") and not self.db.one(
                    "SELECT id FROM people_persons WHERE status='active' AND kind='person' AND external=1 LIMIT 1"):
                problems.append("solo-owner self-approval needs an active outside party (an external person) to review each self-approval")
        return problems

    # ---- cancellation ---------------------------------------------------------------------- #

    def cancel_request(self, request_id: str, *, reason: str, actor: str) -> dict[str, Any]:
        """Cancel a pending grant request, revocation request, delegation or policy draft.  Open
        approvals on it are invalidated.  While enforcing, its requester or an active owner
        cancels it."""
        who = self._actor(actor)
        why = _text(reason, "a reason")
        tables = (("people_grant_requests", OP_GRANT, "requested_by"), ("people_revocation_requests", OP_REVOKE, "requested_by"),
                  ("people_delegations", OP_DELEGATE, "requested_by"), ("people_policy_drafts", OP_POLICY, "prepared_by"))
        with self.db.transaction() as conn:
            for table, operation, by_col in tables:
                row = self.db.one(f"SELECT * FROM {table} WHERE id=?", (request_id,)) if isinstance(request_id, str) else None
                if row is not None:
                    break
            else:
                raise PeopleError(f"unknown request {request_id!r}")
            if row["status"] != "pending":
                raise PeopleError(f"{request_id} is {row['status']}, not pending")
            if _norm(who) == _norm(row[by_col]):
                self._require_active_actor(who, "cancel a request")
            else:
                self._require_admin(who, "cancel another identity's request")
            now = self._stamp()
            invalidated = self.approvals.invalidate_for_subject(SUBJECT_TYPES[operation], request_id, reason=f"request canceled: {why}", actor=who)
            self.audit.record(who, "people.request_cancelled", SUBJECT_TYPES[operation], request_id,
                              {"resolved_at": now, "reason": why, "approvals_invalidated": invalidated})
            if table == "people_delegations":
                conn.execute("UPDATE people_delegations SET status='cancelled', ended_by=?, ended_at=?, end_reason=? WHERE id=?", (who, now, why, request_id))
            else:
                conn.execute(f"UPDATE {table} SET status='cancelled', resolved_by=?, resolved_at=?, resolution_note=? WHERE id=?", (who, now, why, request_id))
            return self.db.one(f"SELECT * FROM {table} WHERE id=?", (request_id,))

    # ---- self-approvals -------------------------------------------------------------------- #

    def _record_self_approval(self, approval: dict[str, Any], person: dict[str, Any], approver_role: str, policy: dict[str, Any]) -> None:
        if self.db.one("SELECT id FROM people_self_approvals WHERE approval_id=?", (approval["id"],)) is not None:
            return
        sid, now = new_id("psa"), self._stamp()
        with self.db.transaction() as conn:
            self.audit.record(person["login"], "people.self_approval_recorded", "people_self_approval", sid, {
                "approval_id": approval["id"], "operation": approval["operation"], "login": person["login"], "approver_role": approver_role,
                "policy_version": policy["version"]})
            conn.execute("INSERT INTO people_self_approvals (id, approval_id, operation, login, approver_role, policy_version, recorded_at) "
                         "VALUES (?,?,?,?,?,?,?)", (sid, approval["id"], approval["operation"], person["login"], approver_role, policy["version"], now))

    def self_approvals(self, *, awaiting_review: bool = False) -> list[dict[str, Any]]:
        """Recorded solo-owner self-approvals whose approval was granted, with their review.  The
        approver is compared as the registry keys a login (``_norm``), never by SQL's narrower
        ``lower(trim())``: an approver spelled with a tab or full-width letters is still the owner."""
        rows = self.db.query(
            """SELECT s.*, a.status AS approval_status, a.subject_type, a.subject_id, a.approver AS granted_by FROM people_self_approvals s
                 JOIN approvals a ON a.id = s.approval_id
                WHERE a.approver IS NOT NULL
                ORDER BY s.recorded_at, s.id""")
        out = []
        for r in rows:
            if _norm(r.pop("granted_by")) == r["login"] and (not awaiting_review or r["reviewed_at"] is None):
                out.append(r)
        return out

    def review_self_approval(self, approval_id: str, *, note: str, actor: str) -> dict[str, Any]:
        """The outside party (an active external person other than the approver, and never the
        person whose authority a people.* approval changed) records that it reviewed a
        solo-owner self-approval; the close check passes once every granted self-approval is
        reviewed.  Reviewed once."""
        who = self._actor(actor)
        text = _text(note, "a review note")
        with self.db.transaction() as conn:
            row = self.db.one("SELECT * FROM people_self_approvals WHERE approval_id=?", (approval_id,)) if isinstance(approval_id, str) else None
            if row is None:
                raise PeopleError(f"approval {approval_id!r} has no recorded self-approval")
            if row["reviewed_at"] is not None:
                raise PeopleError(f"the self-approval of {approval_id} was already reviewed by {row['reviewed_by']}")
            reviewer = self._person_row(who)
            if reviewer is None or reviewer["status"] != "active" or reviewer["kind"] != "person" or not reviewer["external"]:
                raise IdentityRefused(f"{who!r} is not an active outside party; self-approvals are reviewed by an external person")
            if reviewer["login"] == row["login"]:
                raise IdentityRefused("a self-approval is never reviewed by its own approver")
            ap = self.approvals.get(approval_id)
            if ap["operation"] in SUBJECT_TYPES and (ap["manifest"].get("bindings") or {}).get("subject_login") == reviewer["login"]:
                raise IdentityRefused(f"{reviewer['login']} is the subject of {ap['operation']}; an outside party never reviews the approval of their own authority")
            now = self._stamp()
            self.audit.record(who, "people.self_approval_reviewed", "people_self_approval", row["id"],
                              {"approval_id": approval_id, "reviewed_by": reviewer["login"], "reviewed_at": now, "note": text})
            conn.execute("UPDATE people_self_approvals SET reviewed_by=?, reviewed_at=?, review_note=? WHERE id=?", (reviewer["login"], now, text, row["id"]))
        return self.db.one("SELECT * FROM people_self_approvals WHERE id=?", (row["id"],))

    # ---- governor hooks -------------------------------------------------------------------- #

    @staticmethod
    def _scope_of(manifest: dict[str, Any]) -> str | None:
        pid = (manifest.get("bindings") or {}).get("project_id")
        return pid if isinstance(pid, str) and pid else None

    @staticmethod
    def _subject_login(manifest: dict[str, Any]) -> str | None:
        return (manifest.get("bindings") or {}).get("subject_login")

    def approval_policy(self, operation: str, manifest: dict[str, Any]) -> dict[str, Any] | None:
        """Bind the enforcing identity policy (version and hash) into every approval; nothing
        while no policy is recorded or the current one does not enforce."""
        return self._binding()

    def check_request(self, operation: str, manifest: dict[str, Any], *, actor_role: str, requested_by: str) -> None:
        who = _norm(requested_by)
        if operation in SUBJECT_TYPES:
            subject = self._subject_login(manifest)
            if subject and who == subject:
                raise IdentityRefused(f"no self-granting: {requested_by!r} cannot request {operation} on their own authority")
            if operation == OP_POLICY:
                draft = self._draft(manifest["subject"]["id"])
                problems = self._policy_draft_problems(draft, requester=who)
                if problems:
                    raise PeopleIneligible(f"identity policy draft {draft['id']} cannot be adopted: " + "; ".join(problems))
        if not self.enforcing():
            return
        self._require_intact()
        if not self.is_active(who):
            raise IdentityRefused(f"identity enforcement is on: {requested_by!r} is not an active registered identity, so it cannot request {operation}")

    def check_grant(self, approval: dict[str, Any], *, approver: str, approver_role: str) -> None:
        # decide on the stored approval, never on the caller's copy of it
        approval = self.approvals.get(approval["id"])
        if approval["status"] != "pending":
            return  # Approvals.grant refuses anything that is not pending
        operation, manifest = approval["operation"], approval["manifest"]
        who = _norm(approver)
        person = self._person_row(who)
        if operation in SUBJECT_TYPES:
            subject = self._subject_login(manifest)
            if subject and who == subject:
                raise IdentityRefused(f"no self-granting: {approver!r} cannot approve {operation} on their own authority")
            if person is not None and person["kind"] == "service":
                raise IdentityRefused(f"{person['login']} is a service identity; service identities never approve")
        bound = (manifest.get("governance") or {}).get(PLUGIN_NAME)
        current = self._binding()
        if bound != current:
            self.approvals.invalidate(approval["id"], reason="the identity policy changed after the approval was requested", actor=str(approver))
            raise StaleApprovalError(f"approval {approval['id']} was requested under another identity policy; request it again")
        if not self.enforcing():
            return
        self._require_intact()
        if person is None or person["status"] != "active":
            raise IdentityRefused(f"identity enforcement is on: {approver!r} is not an active registered identity, so it cannot approve {operation}")
        if person["kind"] != "person":
            raise IdentityRefused(f"{person['login']} is a service identity; service identities never approve")
        scope = self._scope_of(manifest)
        if not self.holds(who, approver_role, project_id=scope):
            raise IdentityRefused(f"{person['login']} does not hold role {approver_role!r}" + (f" on project {scope}" if scope else " at entity scope")
                                  + f", so cannot approve {operation}")
        policy = self._policy()[0]
        if policy["segregate"] and who == _norm(approval["requested_by"]):
            if not (policy["solo_owner_self_approval"] and self._holds_by_grant(person, OWNER_ROLE, None)):
                raise IdentityRefused(f"segregation: {person['login']} requested {operation} and cannot also approve it"
                                      + ("" if not policy["solo_owner_self_approval"] else "; only an owner may self-approve in solo-owner mode"))
            self._record_self_approval(approval, person, approver_role, policy)

    def check_execute(self, approval: dict[str, Any], manifest: dict[str, Any], *, actor: str) -> None:
        approval = self.approvals.get(approval["id"])
        operation = approval["operation"]
        who = _norm(actor)
        if operation in SUBJECT_TYPES:
            subject = self._subject_login(manifest)
            if subject and who == subject:
                raise IdentityRefused(f"no self-granting: {actor!r} cannot execute {operation} on their own authority")
        if not self.enforcing():
            return
        self._require_intact()
        if not self.is_active(who):
            raise IdentityRefused(f"identity enforcement is on: {actor!r} is not an active registered identity, so it cannot execute {operation}")
        scope = self._scope_of(manifest)
        role = manifest.get("actor_role")
        if not self.holds(who, role, project_id=scope):
            raise IdentityRefused(f"{who} does not hold the executing role {role!r}" + (f" on project {scope}" if scope else " at entity scope")
                                  + f", so cannot execute {operation}")
        approver = self._person_row(approval.get("approver"))
        if approver is None or approver["status"] != "active" or approver["kind"] != "person" or not self._authorized_for(approver["login"], operation, scope):
            raise StaleApprovalError(f"approval {approval['id']} was granted by {approval.get('approver')!r}, who is no longer an active identity "
                                     f"authorized for {operation}; request a fresh approval")

    # ---- approval-bound operations: manifests ---------------------------------------------- #

    def manifest_for(self, operation: str, subject_id: str, *, actor_role: str) -> dict[str, Any]:
        if operation == OP_GRANT:
            return self._grant_manifest(subject_id, actor_role)
        if operation == OP_REVOKE:
            return self._revoke_manifest(subject_id, actor_role)
        if operation == OP_DELEGATE:
            return self._delegate_manifest(subject_id, actor_role)
        if operation == OP_POLICY:
            return self._policy_manifest(subject_id, actor_role)
        raise PeopleError(f"unknown people operation {operation}")

    def _grant_eligibility(self, req: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
        person = self._person_by_id(req["person_id"])
        problems = []
        if req["status"] != "pending":
            problems.append(f"grant request {req['id']} is {req['status']}")
        if self._request_hash(req) != req["content_hash"]:
            problems.append(f"grant request {req['id']} does not hash to its recorded content hash")
        if person is None:
            problems.append(f"grant request {req['id']} names an unknown identity")
            return {}, problems
        problems += self._grant_facts_problems(person, req["role"], req["project_id"], req["effective_from"], req["effective_to"], day=self._today())
        if _norm(req["requested_by"]) == person["login"]:
            problems.append("the grantee requested it (no self-granting)")
        return person, problems

    def _grant_manifest(self, request_id: str, actor_role: str) -> dict[str, Any]:
        req = self._row("people_grant_requests", request_id, "grant request")
        person, problems = self._grant_eligibility(req)
        if problems:
            raise PeopleIneligible(f"grant request {request_id} cannot be granted: " + "; ".join(problems))
        membership = self._membership(person["id"], req["project_id"]) if req["project_id"] else None
        bindings = {
            "request_id": req["id"], "request_hash": req["content_hash"], "request_status": req["status"], "requested_by": req["requested_by"],
            "person_id": person["id"], "subject_login": person["login"], "person_hash": person["content_hash"], "person_status": person["status"],
            "person_kind": person["kind"], "person_external": bool(person["external"]),
            "role": req["role"], "role_authority": sorted(ROLE_AUTHORITY[req["role"]]), "scope": req["scope"],
            "effective_from": req["effective_from"], "effective_to": req["effective_to"],
            "membership_id": membership["id"] if membership else None,
            "effect": f"grants {req['role']} to {person['login']} ({req['scope']} scope) from {req['effective_from']} to {req['effective_to'] or 'open-ended'}",
        }
        if req["project_id"]:
            bindings["project_id"] = req["project_id"]
        return build_manifest(operation=OP_GRANT, subject_type=SUBJECT_TYPES[OP_GRANT], subject_id=request_id, actor_role=actor_role,
                              bindings=bindings, entity=self._entity(req["project_id"]))

    def _revoke_manifest(self, revocation_id: str, actor_role: str) -> dict[str, Any]:
        rev = self._row("people_revocation_requests", revocation_id, "revocation request")
        g = self.db.one("SELECT * FROM people_grants WHERE id=?", (rev["grant_id"],))
        problems = [] if rev["status"] == "pending" else [f"revocation request {revocation_id} is {rev['status']}"]
        problems += self._revocation_problems(g)
        if problems:
            raise PeopleIneligible(f"revocation {revocation_id} cannot be executed: " + "; ".join(problems))
        bindings = {
            "revocation_id": rev["id"], "revocation_status": rev["status"], "reason": rev["reason"], "requested_by": rev["requested_by"],
            "grant_id": g["id"], "grant_hash": g["content_hash"], "subject_login": g["login"], "person_id": g["person_id"], "role": g["role"],
            "scope": g["scope"], "effective_from": g["effective_from"], "effective_to": g["effective_to"],
            "effect": f"revokes {g['role']} from {g['login']} ({g['scope']} scope)",
        }
        if g["project_id"]:
            bindings["project_id"] = g["project_id"]
        return build_manifest(operation=OP_REVOKE, subject_type=SUBJECT_TYPES[OP_REVOKE], subject_id=revocation_id, actor_role=actor_role,
                              bindings=bindings, entity=self._entity(g["project_id"]))

    def _delegation_eligibility(self, d: dict[str, Any]) -> list[str]:
        problems = [] if d["status"] == "pending" else [f"delegation {d['id']} is {d['status']}"]
        if self._delegation_hash(d) != d["content_hash"]:
            problems.append(f"delegation {d['id']} does not hash to its recorded content hash")
        frm, to = self._person_by_id(d["from_person_id"]), self._person_by_id(d["to_person_id"])
        if frm is None or to is None:
            return problems + [f"delegation {d['id']} names an unknown identity"]
        problems += self._delegation_facts_problems(frm, to, d["role"], d["project_id"], d["effective_to"], day=self._today())
        if _norm(d["requested_by"]) == to["login"]:
            problems.append("the delegate requested it (no self-granting)")
        return problems

    def _delegate_manifest(self, delegation_id: str, actor_role: str) -> dict[str, Any]:
        d = self._row("people_delegations", delegation_id, "delegation")
        problems = self._delegation_eligibility(d)
        if problems:
            raise PeopleIneligible(f"delegation {delegation_id} cannot be activated: " + "; ".join(problems))
        bindings = {
            "delegation_id": d["id"], "delegation_hash": d["content_hash"], "delegation_status": d["status"], "requested_by": d["requested_by"],
            "from_login": d["from_login"], "subject_login": d["to_login"], "role": d["role"], "role_authority": sorted(ROLE_AUTHORITY[d["role"]]),
            "scope": d["scope"], "effective_from": d["effective_from"], "effective_to": d["effective_to"],
            "effect": f"delegates {d['role']} from {d['from_login']} to {d['to_login']} ({d['scope']} scope) from {d['effective_from']} to {d['effective_to']}",
        }
        if d["project_id"]:
            bindings["project_id"] = d["project_id"]
        return build_manifest(operation=OP_DELEGATE, subject_type=SUBJECT_TYPES[OP_DELEGATE], subject_id=delegation_id, actor_role=actor_role,
                              bindings=bindings, entity=self._entity(d["project_id"]))

    def _policy_manifest(self, draft_id: str, actor_role: str) -> dict[str, Any]:
        draft = self._draft(draft_id)
        problems = [] if draft["status"] == "pending" else [f"policy draft {draft_id} is {draft['status']}"]
        if self._draft_hash(draft) != draft["content_hash"]:
            problems.append(f"policy draft {draft_id} does not hash to its recorded content hash")
        problems += self._policy_draft_problems(draft)
        current, chain_problems = self._policy()
        if chain_problems:
            problems.append("the identity policy chain is not intact")
        if problems:
            raise PeopleIneligible(f"identity policy draft {draft_id} cannot be adopted: " + "; ".join(problems))
        bindings = {
            "draft_id": draft["id"], "draft_hash": draft["content_hash"], "draft_status": draft["status"], "rules": draft["rules"],
            "prepared_by": draft["prepared_by"], "subject_login": None,
            "current_version": current["version"] if current else None, "current_hash": current["content_hash"] if current else None,
            "effect": f"adopts identity policy version {(current['version'] + 1) if current else 1}: "
                      + ", ".join(f"{k}={'on' if draft['rules'][k] else 'off'}" for k in POLICY_RULES),
        }
        return build_manifest(operation=OP_POLICY, subject_type=SUBJECT_TYPES[OP_POLICY], subject_id=draft_id, actor_role=actor_role, bindings=bindings)

    def _entity(self, project_id: str | None) -> str | None:
        if not project_id:
            return None
        return self.db.scalar("SELECT entity FROM projects WHERE id=?", (project_id,))

    # ---- approval-bound operations: apply -------------------------------------------------- #

    def apply(self, operation: str, subject_id: str, *, approval_id: str, manifest: dict[str, Any], actor: str, period_id: str | None) -> dict[str, Any]:
        """Record the approved change; the caller has consumed ``approval_id`` against ``manifest``."""
        if operation not in SUBJECT_TYPES:
            raise PeopleError(f"unknown people operation {operation}")
        approval = self.db.one("SELECT * FROM approvals WHERE id=?", (approval_id,))
        if approval is None or approval["operation"] != operation or approval["subject_id"] != subject_id or approval["status"] != "consumed":
            raise PeopleError(f"{operation} on {subject_id} runs only against its own consumed approval")
        bound = manifest.get("bindings") or {}
        subject = bound.get("subject_login")
        if subject and any(_norm(x) == subject for x in (approval["requested_by"], approval["approver"], approval["consumed_by"], actor)):
            raise IdentityRefused(f"no self-granting: {subject} requested, approved or executed {operation} on their own authority")
        with self.db.transaction():
            if operation == OP_GRANT:
                return self._apply_grant(subject_id, approval, bound, actor)
            if operation == OP_REVOKE:
                return self._apply_revoke(subject_id, approval, bound, actor)
            if operation == OP_DELEGATE:
                return self._apply_delegate(subject_id, approval, bound, actor)
            return self._apply_policy(subject_id, approval, bound, actor)

    def _apply_grant(self, request_id: str, approval: dict[str, Any], bound: dict[str, Any], actor: str) -> dict[str, Any]:
        req = self._row("people_grant_requests", request_id, "grant request")
        person, problems = self._grant_eligibility(req)
        if problems:
            raise PeopleIneligible(f"grant request {request_id} can no longer be granted: " + "; ".join(problems))
        if bound.get("request_hash") != req["content_hash"]:
            raise PeopleIneligible(f"grant request {request_id} no longer matches the approved request")
        grant = self._insert_grant(person, role=req["role"], scope=req["scope"], project_id=req["project_id"], effective_from=req["effective_from"],
                                   effective_to=req["effective_to"], origin="approval", request_id=req["id"], approval_id=approval["id"],
                                   granted_by=approval["approver"])
        self.db.execute("UPDATE people_grant_requests SET status='granted', grant_id=?, resolved_by=?, resolved_at=? WHERE id=? AND status='pending'",
                        (grant["id"], actor, grant["created_at"], req["id"]))
        return {"grant": grant["id"], "seq": grant["seq"], "login": grant["login"], "role": grant["role"], "scope": grant["scope"],
                "project_id": grant["project_id"], "effective_from": grant["effective_from"], "effective_to": grant["effective_to"]}

    def _apply_revoke(self, revocation_id: str, approval: dict[str, Any], bound: dict[str, Any], actor: str) -> dict[str, Any]:
        rev = self._row("people_revocation_requests", revocation_id, "revocation request")
        g = self.db.one("SELECT * FROM people_grants WHERE id=?", (rev["grant_id"],))
        problems = ([] if rev["status"] == "pending" else [f"revocation request {revocation_id} is {rev['status']}"]) + self._revocation_problems(g)
        if problems or bound.get("grant_hash") != g["content_hash"]:
            raise PeopleIneligible(f"revocation {revocation_id} can no longer be executed: " + ("; ".join(problems) or "the grant changed"))
        now = self._stamp()
        self.audit.record(actor, "people.role_revoked", "people_grant", g["id"], {"revocation_id": rev["id"], "approval_id": approval["id"],
                                                                                   "login": g["login"], "role": g["role"], "revoked_at": now})
        self.db.execute("UPDATE people_grants SET revoked_at=?, revoked_by=?, revocation_request_id=?, revocation_approval_id=? WHERE id=? AND revoked_at IS NULL",
                        (now, actor, rev["id"], approval["id"], g["id"]))
        self.db.execute("UPDATE people_revocation_requests SET status='executed', approval_id=?, resolved_by=?, resolved_at=? WHERE id=? AND status='pending'",
                        (approval["id"], actor, now, rev["id"]))
        return {"revocation": rev["id"], "grant": g["id"], "login": g["login"], "role": g["role"], "revoked_at": now}

    def _apply_delegate(self, delegation_id: str, approval: dict[str, Any], bound: dict[str, Any], actor: str) -> dict[str, Any]:
        d = self._row("people_delegations", delegation_id, "delegation")
        problems = self._delegation_eligibility(d)
        if problems or bound.get("delegation_hash") != d["content_hash"]:
            raise PeopleIneligible(f"delegation {delegation_id} can no longer be activated: " + ("; ".join(problems) or "the delegation changed"))
        now = self._stamp()
        self.audit.record(actor, "people.delegation_activated", "people_delegation", d["id"], {"approval_id": approval["id"], "activated_at": now})
        self.db.execute("UPDATE people_delegations SET status='active', approval_id=?, activated_by=?, activated_at=? WHERE id=? AND status='pending'",
                        (approval["id"], actor, now, d["id"]))
        return {"delegation": d["id"], "from": d["from_login"], "to": d["to_login"], "role": d["role"], "scope": d["scope"],
                "project_id": d["project_id"], "effective_from": d["effective_from"], "effective_to": d["effective_to"], "status": "active"}

    def _apply_policy(self, draft_id: str, approval: dict[str, Any], bound: dict[str, Any], actor: str) -> dict[str, Any]:
        draft = self._draft(draft_id)
        problems = [] if draft["status"] == "pending" else [f"policy draft {draft_id} is {draft['status']}"]
        problems += self._policy_draft_problems(draft, requester=_norm(approval["requested_by"]))
        current, chain_problems = self._policy()
        if chain_problems:
            problems.append("the identity policy chain is not intact")
        if (current["version"] if current else None) != bound.get("current_version") or bound.get("draft_hash") != draft["content_hash"]:
            problems.append("another identity policy was adopted since this one was approved")
        if problems:
            raise PeopleIneligible(f"identity policy draft {draft_id} can no longer be adopted: " + "; ".join(problems))
        rules = draft["rules"]
        row = {"version": (current["version"] + 1) if current else 1, "id": new_id("ppv"), "draft_id": draft["id"], "rules_json": draft["rules_json"],
               "approval_id": approval["id"], "approved_by": approval["approver"], "adopted_by": actor, "adopted_at": self._stamp(),
               "prev_hash": current["content_hash"] if current else GENESIS}
        row["content_hash"] = self._version_hash(row)
        self.audit.record(actor, "people.policy_adopted", "people_policy_version", row["id"], {
            "version": row["version"], "rules": rules, "approval_id": approval["id"], "content_hash": row["content_hash"]})
        self.db.execute(
            """INSERT INTO people_policy_versions (id, version, draft_id, rules_json, enforce, segregate, solo_owner_self_approval, approval_id,
               approved_by, adopted_by, adopted_at, prev_hash, content_hash) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (row["id"], row["version"], draft["id"], draft["rules_json"], int(rules["enforce"]), int(rules["segregate"]),
             int(rules["solo_owner_self_approval"]), approval["id"], approval["approver"], actor, row["adopted_at"], row["prev_hash"], row["content_hash"]))
        self.db.execute("UPDATE people_policy_drafts SET status='adopted', version_id=?, resolved_by=?, resolved_at=? WHERE id=? AND status='pending'",
                        (row["id"], actor, row["adopted_at"], draft["id"]))
        # a policy change invalidates every in-flight approval bound to the previous one
        binding = self._binding()
        invalidated = []
        for ap in self.approvals.list(status="pending") + self.approvals.list(status="granted"):
            if ap["id"] != approval["id"] and (ap["manifest"].get("governance") or {}).get(PLUGIN_NAME) != binding:
                self.approvals.invalidate(ap["id"], reason=f"identity policy version {row['version']} was adopted after this approval was requested", actor=actor)
                invalidated.append(ap["id"])
        return {"policy_version": row["version"], "policy_id": row["id"], "rules": rules, "content_hash": row["content_hash"],
                "approvals_invalidated": invalidated}

    # ---- reading, state, close checks and export ------------------------------------------- #

    def _has_records(self) -> bool:
        """The registry recorded something: an identity, a policy version or an audited people.*
        action (so tables emptied with their triggers dropped are still verified)."""
        return bool(self.db.scalar("SELECT COUNT(*) FROM people_persons") or self.db.scalar("SELECT COUNT(*) FROM people_policy_versions")
                    or self.db.one("SELECT seq FROM audit_log WHERE action LIKE 'people.%' LIMIT 1"))

    def _expiring(self, day: _dt.date) -> list[dict[str, Any]]:
        """Live grants and active delegations whose window ends within EXPIRY_WARNING_DAYS."""
        start, end = day.isoformat(), (day + _dt.timedelta(days=EXPIRY_WARNING_DAYS)).isoformat()
        out = []
        for g in self.db.query("SELECT g.* FROM people_grants g JOIN people_persons p ON p.id = g.person_id WHERE g.revoked_at IS NULL "
                               "AND p.status='active' AND g.effective_to IS NOT NULL AND g.effective_to >= ? AND g.effective_to <= ? ORDER BY g.effective_to, g.seq",
                               (start, end)):
            out.append({"kind": "grant", "id": g["id"], "login": g["login"], "role": g["role"], "scope": g["scope"], "project_id": g["project_id"],
                        "effective_to": g["effective_to"]})
        for d in self.db.query("SELECT * FROM people_delegations WHERE status='active' AND effective_to >= ? AND effective_to <= ? "
                               "ORDER BY effective_to, id", (start, end)):
            out.append({"kind": "delegation", "id": d["id"], "login": d["to_login"], "from": d["from_login"], "role": d["role"], "scope": d["scope"],
                        "project_id": d["project_id"], "effective_to": d["effective_to"]})
        return out

    def state(self, project_id: str) -> dict[str, Any]:
        """The registry as the console shows it: the policy, every identity with what it holds
        today, this project's members, pending requests, expiring authority, self-approvals
        awaiting outside review and integrity."""
        persons = self.db.query("SELECT * FROM people_persons ORDER BY created_at, id")
        awaiting = self.self_approvals(awaiting_review=True)
        problems = self.integrity_problems() if self._has_records() else []
        expiring = self._expiring(self._today())
        return {
            "policy": self.current_policy(),
            "enforcing": self.enforcing(),
            "people": [self._person_summary(p) for p in persons],
            "members": self.memberships(project_id),
            "pending": {
                "grants": self.grant_requests("pending"),
                "revocations": self.db.query("SELECT * FROM people_revocation_requests WHERE status='pending' ORDER BY requested_at, id"),
                "delegations": self.delegations("pending"),
                "policy_drafts": self.db.query("SELECT * FROM people_policy_drafts WHERE status='pending' ORDER BY prepared_at, id"),
            },
            "expiring": expiring,
            "self_approvals_awaiting_review": awaiting,
            "integrity_problems": problems,
            "summary": {
                "people": len(persons),
                "active": sum(1 for p in persons if p["status"] == "active"),
                "services": sum(1 for p in persons if p["kind"] == "service"),
                "outside_parties": sum(1 for p in persons if p["external"] and p["status"] == "active"),
                "active_owners": len(self._active_owners()),
                "live_grants": sum(1 for g in self.grants() if g["effective_today"]),
                "active_delegations": len(self.delegations("active")),
                "expiring_within_14_days": len(expiring),
                "self_approvals_awaiting_review": len(awaiting),
                "integrity_failures": len(problems),
            },
        }

    def close_checks(self, period_id: str) -> list[dict[str, Any]]:
        """Identity checks for the close checklist and Ricky's brief:

        * enforcement status (informational, always ok);
        * grants and delegations ending within 14 days (informational, always ok: an expiry is
          scheduled, not an exception -- renew it or let it lapse);
        * an enforcing workspace keeps an owner without an end date (fails while no active owner
          holds an owner grant without one: once the dated grants lapse, nothing could approve an
          owner-only operation again);
        * solo-owner self-approvals awaiting the outside party's review (fails until reviewed);
        * identity records intact (fails on any grant or policy chain break, a policy version
          missing from the chain, unbacked grant, delegation or membership, a revocation, end or
          review the audit log does not back, or unrecorded self-approval)."""
        def check(name: str, ok: bool, detail: str) -> dict[str, Any]:
            return {"check": name, "name": name, "ok": ok, "detail": detail}

        policy = self.current_policy()
        enforcing = self.enforcing()
        if policy is None and enforcing:
            status = "no identity policy version is stored, but the identity records show one was adopted: identity checks fail closed"
        elif policy is None:
            status = "identity enforcement is off: no identity policy is recorded, so roles are named by the caller (informational)"
        elif not policy["enforce"]:
            status = f"identity enforcement is off under identity policy version {policy['version']}: roles are named by the caller (informational)"
        else:
            status = (f"identity policy version {policy['version']} enforces (segregation {'on' if policy['segregate'] else 'off'}, "
                      f"solo-owner self-approval {'on' if policy['solo_owner_self_approval'] else 'off'})")
        day = self._today()
        expiring = self._expiring(day)
        exp_detail = ("; ".join(f"{e['kind']} {e['id']}: {e['role']} for {e['login']} ends {e['effective_to']}" for e in expiring)
                      if expiring else f"no grant or delegation ends within {EXPIRY_WARNING_DAYS} days of {day.isoformat()}")
        awaiting = self.self_approvals(awaiting_review=True)
        sa_detail = ("; ".join(f"approval {s['approval_id']} ({s['operation']}) self-approved by {s['login']} at {s['recorded_at']}" for s in awaiting)
                     + " -- awaiting review by the outside party") if awaiting else "no self-approval awaits outside review"
        lasting = self._active_owners(day, lasting=True) if enforcing else []
        if not enforcing:
            owner_detail = "identity enforcement is off, so no owner is required (informational)"
        elif lasting:
            owner_detail = f"owner grant without an end date: {', '.join(o['login'] for o in lasting)}"
        else:
            ends = [f"{g['login']} until {g['effective_to']}" for o in self._active_owners(day) for g in self._live_grants(o["id"], day)
                    if g["role"] == OWNER_ROLE]
            owner_detail = (f"identity enforcement is on, but every owner grant ends ({', '.join(ends)}); after that no one could approve an "
                            "owner-only operation (people.*) again -- grant owner without an end date to another internal person first" if ends
                            else "identity enforcement is on, but no active person holds owner, so no owner-only operation (people.*) can be approved")
        problems = self.integrity_problems() if self._has_records() else []
        return [
            check("people identity enforcement (informational)", True, status),
            check(f"people grants and delegations ending within {EXPIRY_WARNING_DAYS} days (informational)", True, exp_detail),
            check("people enforcing workspace keeps an owner without an end date", not enforcing or bool(lasting), owner_detail),
            check("people self-approvals reviewed by an outside party", not awaiting, sa_detail),
            check("people identity records intact", not problems, "; ".join(problems) if problems else "identity, grant and policy records verify"),
        ]

    def audit_export(self) -> dict[str, Any]:
        return {
            "policy": self.current_policy(),
            "persons": self.db.query("SELECT * FROM people_persons ORDER BY created_at, id"),
            "memberships": self.memberships(),
            "grant_requests": self.grant_requests(),
            "grants": self.db.query("SELECT * FROM people_grants ORDER BY seq"),
            "revocation_requests": self.db.query("SELECT * FROM people_revocation_requests ORDER BY requested_at, id"),
            "delegations": self.delegations(),
            "policy_drafts": self.db.query("SELECT * FROM people_policy_drafts ORDER BY prepared_at, id"),
            "policy_versions": self.policy_versions(),
            "self_approvals": self.db.query("SELECT * FROM people_self_approvals ORDER BY recorded_at, id"),
            "integrity_problems": self.integrity_problems(),
        }

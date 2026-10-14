"""Volatile synthetic-person sessions and pure, current AP project authority.

The local persona picker is a practice tool.  It is not Microsoft sign-in and
does not establish a real person's identity.  No caller-provided duty is used.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
import hmac
import math
import secrets
import threading
import time

from .core.ids import hash_json


CONTRACT_VERSION = "cipher.ap-practice.v1"
IDLE_SECONDS = 30 * 60
ABSOLUTE_SECONDS = 8 * 60 * 60
MAX_SESSIONS = 512


class APIdentityRefusal(PermissionError):
    """Safe identity errors; internal integrity details never enter responses."""

    def __init__(self, code, message, *, status=401, target="session"):
        self.code, self.message, self.status, self.target = code, message, status, target
        super().__init__(message)


@dataclass(frozen=True)
class SessionAuthority:
    person_id: str
    login: str
    display_name: str
    persona_id: str
    duties: tuple[str, ...]
    project_ids: tuple[str, ...]
    scope_hash: str
    project_duties: tuple[tuple[str, tuple[str, ...]], ...]

    def allows(self, project_id: str, duty: str) -> bool:
        return any(project == project_id and duty in duties for project, duties in self.project_duties)


def authority_for(cipher, person_id: str, *, persona_id: str | None = None) -> SessionAuthority:
    """Read audited, explicit project duties without owner/delegation inheritance.

    Scope comes from current active membership plus an actual project grant.
    The hash binds the caller's complete current registry facts and the policy,
    so revoked/ended authority invalidates cursors and reviewed proposals.
    """
    with cipher.db._lock:
        cipher.db.require_practice_mode()
        people = cipher.plugin("people")
        if not cipher.audit.verify_chain()["ok"] or people.authority_problems():
            raise APIdentityRefusal("authority_unavailable", "Practice authority could not be verified.", status=423)
        policy = people.current_policy()
        if not policy or not policy["intact"] or not policy["enforce"] or not policy["segregate"] or policy["solo_owner_self_approval"]:
            raise APIdentityRefusal("authority_unavailable", "The segregated practice duty policy is required.", status=423)
        person = cipher.db.one("SELECT * FROM people_persons WHERE id=?", (person_id,)) if isinstance(person_id, str) else None
        if person is None or person["status"] != "active" or person["kind"] != "person":
            raise APIdentityRefusal("session_person_unavailable", "This practice person is no longer available.")
        mapping = getattr(cipher, "ap_practice_persona_people", {})
        known_persona = next((key for key, value in mapping.items() if value["person_id"] == person_id), "")
        if persona_id is not None and (persona_id != known_persona or not known_persona):
            raise APIdentityRefusal("session_person_unavailable", "This practice person is no longer available.")
        memberships = cipher.db.query("SELECT * FROM people_memberships WHERE person_id=? ORDER BY id", (person_id,))
        grants = people.grants(person["login"])
        active_projects = {membership["project_id"] for membership in memberships if membership["status"] == "active"}
        by_project = {}
        for grant in grants:
            if (grant["role"] in ("pm", "accountant") and grant["scope"] == "project" and grant["effective_today"]
                    and grant["project_id"] in active_projects):
                by_project.setdefault(grant["project_id"], set()).add(grant["role"])
        project_duties = tuple((project, tuple(sorted(duties))) for project, duties in sorted(by_project.items()))
        duties = tuple(sorted({duty for _, values in project_duties for duty in values}))
        scope_hash = hash_json({"person": person, "memberships": memberships, "grants": grants,
                                "policy": policy, "project_duties": project_duties})
        return SessionAuthority(person["id"], person["login"], person["display_name"], known_persona,
                                duties, tuple(project for project, _ in project_duties), scope_hash, project_duties)


@dataclass(frozen=True)
class APPracticeSession:
    cookie_token: str
    csrf_token: str
    created_at: float
    last_seen: float
    persona_id: str | None = None
    person_id: str | None = None


def _capabilities():
    return {"sessionIdentity": "registered_synthetic_person", "scopedReads": True, "microsoftSignIn": False,
            "liveAdmission": False, "externalAccounting": "unavailable",
            "commands": ["bill.requestApproval", "bill.approve", "bill.post"]}


class APPracticeSessions:
    """A bounded in-process repository; restart discards every cookie and record."""

    def __init__(self, cipher, *, clock=time.monotonic):
        self.cipher, self.clock = cipher, clock
        self._lock = threading.RLock()
        self._sessions: dict[str, APPracticeSession] = {}
        self._people = {key: dict(value) for key, value in cipher.ap_practice_persona_people.items()}
        self._personas = tuple(dict(value) for value in cipher.ap_practice_personas)

    def personas(self):
        return [dict(option) for option in self._personas]

    def _now(self):
        value = self.clock()
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise APIdentityRefusal("session_unavailable", "Restart this practice session.")
        return float(value)

    @staticmethod
    def _expired(session, now):
        return now < session.last_seen or now - session.last_seen >= IDLE_SECONDS or now - session.created_at >= ABSOLUTE_SECONDS

    def _current(self, session, now):
        if not isinstance(session, APPracticeSession):
            return False
        stored = self._sessions.get(session.cookie_token)
        # Concurrent requests may hold earlier last_seen snapshots of one cookie.
        # They remain valid until rotation; identity and credentials never change
        # in place, and expiry always uses the latest server-owned activity.
        return (stored is not None and session.csrf_token == stored.csrf_token
                and session.created_at == stored.created_at and session.persona_id == stored.persona_id
                and session.person_id == stored.person_id and not self._expired(stored, now))

    def _new(self, now, *, persona_id=None, person_id=None):
        for token, value in tuple(self._sessions.items()):
            if self._expired(value, now):
                del self._sessions[token]
        if len(self._sessions) >= MAX_SESSIONS:
            del self._sessions[min(self._sessions, key=lambda key: self._sessions[key].last_seen)]
        session = APPracticeSession(secrets.token_urlsafe(32), secrets.token_urlsafe(32), now, now, persona_id, person_id)
        self._sessions[session.cookie_token] = session
        return session

    def anonymous(self):
        with self._lock:
            return self._new(self._now())

    def get(self, cookie_token):
        """Resolve an opaque stored cookie; unknown and expired cookies are absent."""
        with self._lock:
            if not isinstance(cookie_token, str) or len(cookie_token) > 128:
                return None
            session = self._sessions.get(cookie_token)
            if session is None:
                return None
            now = self._now()
            if self._expired(session, now):
                del self._sessions[cookie_token]
                return None
            session = replace(session, last_seen=now)
            self._sessions[cookie_token] = session
            return session

    def _resolve(self, session_or_token):
        if isinstance(session_or_token, str):
            session_or_token = self.get(session_or_token)
        with self._lock:
            if not self._current(session_or_token, self._now()):
                raise APIdentityRefusal("session_expired", "Start a new practice session.")
            return self._sessions[session_or_token.cookie_token]

    def select(self, session_or_token, persona_id):
        session = self._resolve(session_or_token)
        if not isinstance(persona_id, str) or persona_id not in self._people:
            raise APIdentityRefusal("persona_refused", "Choose a listed synthetic practice person.", status=422, target="personaId")
        person = self._people[persona_id]
        authority_for(self.cipher, person["person_id"], persona_id=persona_id)
        with self._lock:
            now = self._now()
            if not self._current(session, now):
                raise APIdentityRefusal("session_expired", "Start a new practice session.")
            del self._sessions[session.cookie_token]
            return self._new(now, persona_id=persona_id, person_id=person["person_id"])

    def logout(self, session_or_token):
        session = self._resolve(session_or_token)
        with self._lock:
            now = self._now()
            if not self._current(session, now):
                raise APIdentityRefusal("session_expired", "Start a new practice session.")
            del self._sessions[session.cookie_token]
            return self._new(now)

    def require(self, session):
        session = self._resolve(session)
        if session.person_id is None or session.persona_id is None:
            raise APIdentityRefusal("session_required", "Start a synthetic practice session.")
        authority = authority_for(self.cipher, session.person_id, persona_id=session.persona_id)
        # A concurrent switch/logout must not leave an old authenticated object usable.
        self._resolve(session)
        return authority

    def validate_csrf(self, session, token):
        with self._lock:
            if (not self._current(session, self._now()) or not isinstance(token, str)
                    or len(token) > 128 or not token.isascii()):
                return False
            return hmac.compare_digest(session.csrf_token, token)

    def dto(self, session):
        session = self._resolve(session)
        authority = self.require(session) if session.person_id is not None else None
        with self._lock:
            now = self._now()
            if not self._current(session, now):
                raise APIdentityRefusal("session_expired", "Start a new practice session.")
            current = self._sessions[session.cookie_token]
            remaining = min(IDLE_SECONDS - (now - current.last_seen), ABSOLUTE_SECONDS - (now - current.created_at))
        expires = (datetime.now(timezone.utc) + timedelta(seconds=remaining)).isoformat().replace("+00:00", "Z")
        return {"contractVersion": CONTRACT_VERSION, "mode": "practice", "synthetic": True, "currency": "USD",
                "authenticated": authority is not None, "sessionExpiresAt": expires, "csrfToken": session.csrf_token,
                "person": {"id": authority.person_id, "displayName": authority.display_name, "personaId": authority.persona_id} if authority else None,
                "duties": list(authority.duties) if authority else [], "projectIds": list(authority.project_ids) if authority else [],
                "capabilities": _capabilities()}

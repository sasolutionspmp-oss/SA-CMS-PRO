"""Current internal Library project duties and volatile synthetic-person sessions.

Actual owned project PM grants supply scope. The local practice
picker does not authenticate staff or establish a real person's identity.
"""
from __future__ import annotations

from dataclasses import dataclass

from apps.cipher.ap_contract import APRefusal
from apps.cipher.core.ids import hash_json


@dataclass(frozen=True)
class LibraryAuthority:
    person_id: str
    login: str
    display_name: str
    persona_id: str
    duties: tuple[str, ...]
    project_ids: tuple[str, ...]
    scope_hash: str
    project_duties: tuple[tuple[str, tuple[str, ...]], ...]

    def allows(self, project_id, duty):
        return duty == "pm" and any(project == project_id and "pm" in duties for project, duties in self.project_duties)

    def operation_role(self, project_id, duty):
        self.require(project_id, duty)
        return "pm"

    def require(self, project_id, duty):
        if project_id not in self.project_ids:
            raise APRefusal(404, "not_found", "The record is unavailable in this library session.", "record")
        if not self.allows(project_id, duty):
            raise APRefusal(403, "library_duty_required", "This action requires the person's own current project PM duty.", "duty")


def authority_for(cipher, person_id, *, persona_id=None):
    with cipher.db._lock:
        cipher.db.require_practice_mode()
        people = cipher.plugin("people")
        if not cipher.audit.verify_chain()["ok"] or people.authority_problems():
            raise LibraryIdentityRefusal("library_authority_unavailable", "Library authority cannot be verified.", status=423)
        policy = people.current_policy()
        if not policy or not policy["intact"] or not policy["enforce"] or not policy["segregate"] or policy["solo_owner_self_approval"]:
            raise LibraryIdentityRefusal("library_authority_unavailable", "The segregated Library practice policy is required.", status=423)
        person = cipher.db.one("SELECT * FROM people_persons WHERE id=?", (person_id,)) if type(person_id) is str else None
        if not person or person["status"] != "active" or person["kind"] != "person" or person["external"]:
            raise LibraryIdentityRefusal("library_person_unavailable", "This Library person is no longer available.")
        mapping = getattr(cipher, "library_practice_persona_people", {})
        known = next((key for key, value in mapping.items() if value["person_id"] == person_id), "")
        if persona_id is not None and (persona_id != known or not known):
            raise LibraryIdentityRefusal("library_person_unavailable", "This Library person is no longer available.")
        memberships = cipher.db.query("SELECT * FROM people_memberships WHERE person_id=? ORDER BY id", (person_id,))
        grants = people.grants(person["login"])
        projects = {row["project_id"] for row in memberships if row["status"] == "active"}
        duties = {}
        for grant in grants:
            if (grant["role"] == "pm" and grant["scope"] == "project"
                    and grant["effective_today"] and grant["project_id"] in projects):
                duties.setdefault(grant["project_id"], set()).add(grant["role"])
        project_duties = tuple((project, tuple(sorted(values))) for project, values in sorted(duties.items()))
        scope_hash = hash_json({"person": person, "memberships": memberships, "grants": grants,
                                "policy": policy, "library_project_duties": project_duties})
        return LibraryAuthority(person["id"], person["login"], person["display_name"], known,
                                   tuple(sorted({duty for _, values in project_duties for duty in values})),
                                   tuple(project for project, _ in project_duties), scope_hash, project_duties)


# Independent volatile session store; no AP or AR authority/session inheritance.
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hmac
import math
import secrets
import threading
import time

CONTRACT_VERSION = "cipher.library-practice.v1"
IDLE_SECONDS = 30 * 60
ABSOLUTE_SECONDS = 8 * 60 * 60
MAX_SESSIONS = 512


class LibraryIdentityRefusal(PermissionError):
    def __init__(self, code, message, *, status=401, target="session"):
        self.code, self.message, self.status, self.target = code, message, status, target
        super().__init__(message)

@dataclass(frozen=True)
class LibraryPracticeSession:
    cookie_token: str
    csrf_token: str
    created_at: float
    last_seen: float
    persona_id: str | None = None
    person_id: str | None = None


def _capabilities():
    return {"sessionIdentity": "registered_synthetic_person", "scopedReads": True, "microsoftSignIn": False,
            "liveAdmission": False, "authoredTextStored": True, "projectReferenceOnly": True,
            "licensedContentIngestion": False, "externalDistribution": False, "contractExecution": False,
            "engineeringCertification": False, "financialEffects": False,
            "commands": ["library.create", "library.revise", "library.prepareReference", "library.requestAdoption",
                         "library.approveAdoption", "library.applyAdoption"]}


class LibraryPracticeSessions:
    """A bounded in-process repository; restart discards every cookie and record."""

    def __init__(self, cipher, *, clock=time.monotonic):
        self.cipher, self.clock = cipher, clock
        self._lock = threading.RLock()
        self._sessions: dict[str, LibraryPracticeSession] = {}
        self._people = {key: dict(value) for key, value in cipher.library_practice_persona_people.items()}
        self._personas = tuple(dict(value) for value in cipher.library_practice_personas)

    def personas(self):
        return [dict(option) for option in self._personas]

    def _now(self):
        value = self.clock()
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise LibraryIdentityRefusal("session_unavailable", "Restart this Library session.")
        return float(value)

    @staticmethod
    def _expired(session, now):
        return now < session.last_seen or now - session.last_seen >= IDLE_SECONDS or now - session.created_at >= ABSOLUTE_SECONDS

    def _current(self, session, now):
        if type(session) is not LibraryPracticeSession:
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
        session = LibraryPracticeSession(secrets.token_urlsafe(32), secrets.token_urlsafe(32), now, now, persona_id, person_id)
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
                raise LibraryIdentityRefusal("session_expired", "Start a new library session.")
            return self._sessions[session_or_token.cookie_token]

    def select(self, session_or_token, persona_id):
        session = self._resolve(session_or_token)
        if not isinstance(persona_id, str) or persona_id not in self._people:
            raise LibraryIdentityRefusal("persona_refused", "Choose a listed synthetic library person.", status=422, target="personaId")
        person = self._people[persona_id]
        authority_for(self.cipher, person["person_id"], persona_id=persona_id)
        with self._lock:
            now = self._now()
            if not self._current(session, now):
                raise LibraryIdentityRefusal("session_expired", "Start a new library session.")
            del self._sessions[session.cookie_token]
            return self._new(now, persona_id=persona_id, person_id=person["person_id"])

    def logout(self, session_or_token):
        session = self._resolve(session_or_token)
        with self._lock:
            now = self._now()
            if not self._current(session, now):
                raise LibraryIdentityRefusal("session_expired", "Start a new library session.")
            del self._sessions[session.cookie_token]
            return self._new(now)

    def require(self, session):
        session = self._resolve(session)
        if session.person_id is None or session.persona_id is None:
            raise LibraryIdentityRefusal("session_required", "Start a synthetic library session.")
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
                raise LibraryIdentityRefusal("session_expired", "Start a new library session.")
            current = self._sessions[session.cookie_token]
            remaining = min(IDLE_SECONDS - (now - current.last_seen), ABSOLUTE_SECONDS - (now - current.created_at))
        expires = (datetime.now(timezone.utc) + timedelta(seconds=remaining)).isoformat().replace("+00:00", "Z")
        return {"contractVersion": CONTRACT_VERSION, "mode": "practice", "synthetic": True, "currency": "USD",
                "authenticated": authority is not None, "sessionExpiresAt": expires, "csrfToken": session.csrf_token,
                "person": {"id": authority.person_id, "displayName": authority.display_name, "personaId": authority.persona_id} if authority else None,
                "duties": list(authority.duties) if authority else [], "projectIds": list(authority.project_ids) if authority else [],
                "capabilities": _capabilities()}

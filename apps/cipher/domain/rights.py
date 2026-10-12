"""Content-rights registry: which licensed works Cipher holds, on what terms,
and whether a document may be used for a given purpose on a given day.

Plan section 4: "Maintain a rights registry: licensor, work/edition, license
holder, permitted use/processors, AI permissions, expiration, distribution and
purge rules.  Retrieval must satisfy both user/project access and content
rights."

Model
-----

* A **license** is a registry entry identified by (licensor, work, edition,
  holder).  The identity is unique ignoring case (Unicode case folding with
  NFKC normalisation and runs of whitespace treated as one space, checked by
  this module; the database's own unique index and guards fold ASCII letters
  only, because SQLite's ``lower()`` does).  Identity never changes: a new
  edition or a different holder is a new license.  Its **terms** (permitted
  uses, permitted processors, expiry date, purge-on-expiry rule) live in
  immutable, numbered **versions**; ``update_license`` appends the next
  version and moves the license to it.  Nothing is ever edited in place or
  deleted.
* **Uses** are a closed vocabulary (``USES``): ``internal_reference``,
  ``project_use``, ``ai_retrieval``, ``ai_embedding`` and ``distribution``.
  The two ``ai_*`` uses are the AI permissions.  Unknown use names are
  refused everywhere, including in the database.
* **Processors** are the named systems a license allows to process the content
  (for example a local model host).  Names compare ignoring case.  A license
  permits an AI use (``AI_USES``) of its content only by a processor it lists,
  so an AI check always tests one processor: the one the caller names, or else
  the workspace's configured **default AI processor** (``set_default_processor``;
  versioned, audited), which is the processor Cipher's own assistant uses when
  it reads a document (``ricky_sdk`` calls ``check_use(document_id,
  "ai_retrieval")`` without naming one).  With neither, the AI use of licensed
  content is refused (fail closed) and the reason says how to configure it.
  For the other uses the processor test is made only when a processor is
  named.  Company-owned content has no processor restriction.
* A **document** (core evidence ``documents`` row) is *licensed content* while
  it carries at least one active tag, and *company-owned* (every use allowed)
  when it carries none and owes no purge.  Untagging keeps the tag row as
  history.
* **Expiry**: ``expires_on`` is the last day of validity.  A license is usable
  on its ``expires_on`` date and expired from the following day; ``None``
  means no expiry.  Dates are calendar dates (``YYYY-MM-DD``); the default
  "today" is the UTC date.
* **Most restrictive wins**: a use is allowed only when *every* license tagged
  on the document permits it and is unexpired on the date (and lists the
  processor tested), and no purge is owed on the document.
* **Purge**: a license with ``purge_on_expiry`` requires derived copies of its
  documents (indexes, embeddings, caches) to be purged after it expires.
  ``record_purge`` records the owner's attestation that it was done.  A
  renewal that moves the expiry past the purge date makes a later expiry
  require a new purge.  Untagging never discharges a purge: it is refused
  while the document's purge is outstanding, and a tag removed after its
  license expired (for example after a retroactive amendment of the expiry,
  or after the purge rule was switched off for the untag and back on) leaves
  the purge **owed**: the document stays listed by ``expired_items`` with
  ``tag_status`` ``removed``, and every use of it is refused, until
  ``record_purge`` answers that expiry.

Views of time
-------------

* ``check_use``, ``filter_retrievable``, ``state`` and ``expired_items`` (by
  default) judge the registry as it stands now - the document's current tags,
  each license's current terms and the purges recorded so far - and
  ``on_date`` moves only the expiry test ("do today's records still hold on
  that date?").  They are not reconstructions of the past.
* ``expired_items(on_date, as_recorded=True)`` and ``close_checks`` read the
  registry **as recorded at the end of** that UTC date: the terms version in
  force then (the latest adopted version recorded by that day), the tags
  active at the end of that day and the purges recorded by it; licenses
  registered later are absent.  For a date that has not ended yet this is the
  current registry.

No operation here needs an approval: registry changes are owner record
keeping, audited one by one.  ``manifest_for``/``apply`` exist only to satisfy
the plugin contract and refuse every operation.  Every mutation requires the
workspace's write authority, so a restored copy cannot change the registry.

``close_checks`` is informational and never blocks a close.  Its ``detail``
strings carry the counts, as recorded at the end of the period's end date (the
close checklist keeps only ``check``, ``ok`` and ``detail``; the same numbers
are also in each check's ``counts`` for direct callers).  A ``close.close_period``
approval binds a hash of every detail, so: closing a period that has ended is
never staled by registry activity after its end date or by a UTC midnight
(nothing recorded later changes the as-recorded view); closing a period that
has not ended yet binds the rights position recorded so far, and a registry
change before execution stales the approval like any other checklist change.

Database guards back the rules without this module: license identity is
immutable and unique (ASCII-folded, see above); a license is born at version 1
together with its version-1 terms, in one statement through the
``rights_license_registrations`` view, and moves only to the next,
already-recorded version; every terms row belongs to a registered license
(an immediate foreign key: a raw insert of an orphan row fails at once and
never leaves a transaction to fail at COMMIT); version rows, purge rows,
tag bindings and settings rows are immutable; a tag changes only once, from
active to removed, with a removal timestamp that is well formed, not before
the tag, not in the future and not backdated, and not while its purge is
outstanding; a purge is recorded only for a document that is or was tagged,
after its license's current version has expired, and at most once per expiry.
No rights row is ever *replaced*: SQLite's ``INSERT OR REPLACE`` deletes the
conflicting row without firing delete triggers (``recursive_triggers`` is
off), so every insert that collides with an existing id or unique key is
refused outright.
"""
from __future__ import annotations

import datetime as _dt
import json
import re
import unicodedata
from typing import Any, Iterable

from ..core.db import register_schema_version
from ..core.ids import hash_json, new_id, utcnow, utcnow_iso

SCHEMA_NAME = "rights"
PLUGIN_NAME = "rights"

USES = ("internal_reference", "project_use", "ai_retrieval", "ai_embedding", "distribution")
AI_USES = ("ai_retrieval", "ai_embedding")

_USES_SQL = ", ".join(f"'{u}'" for u in USES)

# --------------------------------------------------------------------------- #
# Schema.  Applied entries are append-only: ``rights`` and                     #
# ``rights_integrity_guards`` stay exactly as first released, and later       #
# changes are new, uniquely named entries.                                     #
# --------------------------------------------------------------------------- #

SCHEMA_STATEMENTS = [
    """CREATE TABLE rights_licenses (
        id TEXT PRIMARY KEY,
        licensor TEXT NOT NULL CHECK (length(trim(licensor)) > 0),
        work TEXT NOT NULL CHECK (length(trim(work)) > 0),
        edition TEXT NOT NULL CHECK (length(trim(edition)) > 0),
        holder TEXT NOT NULL CHECK (length(trim(holder)) > 0),
        version INTEGER NOT NULL CHECK (version >= 1),
        created_by TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )""",
    "CREATE UNIQUE INDEX rights_licenses_identity ON rights_licenses (lower(licensor), lower(work), lower(edition), lower(holder))",
    """CREATE TABLE rights_license_versions (
        id TEXT PRIMARY KEY,
        license_id TEXT NOT NULL REFERENCES rights_licenses(id) DEFERRABLE INITIALLY DEFERRED,
        version INTEGER NOT NULL CHECK (version >= 1),
        permitted_uses TEXT NOT NULL,
        processors TEXT NOT NULL,
        expires_on TEXT,
        purge_on_expiry INTEGER NOT NULL CHECK (purge_on_expiry IN (0, 1)),
        note TEXT NOT NULL DEFAULT '',
        terms_hash TEXT NOT NULL,
        created_by TEXT NOT NULL,
        created_at TEXT NOT NULL,
        UNIQUE (license_id, version)
    )""",
    """CREATE TRIGGER rights_license_versions_guard BEFORE INSERT ON rights_license_versions
        BEGIN
            SELECT CASE
                WHEN NEW.version IS NOT COALESCE((SELECT MAX(version) FROM rights_license_versions WHERE license_id = NEW.license_id), 0) + 1
                THEN RAISE(ABORT, 'license versions are contiguous: a new version is the next number')
                WHEN NEW.version IS NOT COALESCE((SELECT version FROM rights_licenses WHERE id = NEW.license_id), 0) + 1
                THEN RAISE(ABORT, 'a new license version follows the license''s current version')
                WHEN NEW.expires_on IS NOT NULL AND date(NEW.expires_on) IS NOT NEW.expires_on
                THEN RAISE(ABORT, 'expires_on must be a valid YYYY-MM-DD date')
                WHEN json_valid(NEW.permitted_uses) = 0 OR json_type(NEW.permitted_uses) IS NOT 'array'
                THEN RAISE(ABORT, 'permitted_uses must be a JSON array of use names')
                WHEN EXISTS (SELECT 1 FROM json_each(NEW.permitted_uses) WHERE type IS NOT 'text' OR value NOT IN (""" + _USES_SQL + """))
                THEN RAISE(ABORT, 'permitted_uses may hold only known use names')
                WHEN json_valid(NEW.processors) = 0 OR json_type(NEW.processors) IS NOT 'array'
                THEN RAISE(ABORT, 'processors must be a JSON array of processor names')
            END;
        END""",
    "CREATE TRIGGER rights_license_versions_no_update BEFORE UPDATE ON rights_license_versions BEGIN SELECT RAISE(ABORT, 'license versions are immutable; record the next version instead'); END",
    "CREATE TRIGGER rights_license_versions_no_delete BEFORE DELETE ON rights_license_versions BEGIN SELECT RAISE(ABORT, 'license versions are immutable history'); END",
    """CREATE TRIGGER rights_licenses_born_v1 BEFORE INSERT ON rights_licenses
        BEGIN
            SELECT CASE
                WHEN NEW.version IS NOT 1
                THEN RAISE(ABORT, 'a license is registered at version 1')
                WHEN NOT EXISTS (SELECT 1 FROM rights_license_versions WHERE license_id = NEW.id AND version = 1)
                THEN RAISE(ABORT, 'a license is registered together with its version-1 terms')
            END;
        END""",
    "CREATE TRIGGER rights_licenses_no_delete BEFORE DELETE ON rights_licenses BEGIN SELECT RAISE(ABORT, 'licenses are never deleted from the rights registry'); END",
    """CREATE TRIGGER rights_licenses_identity_immutable BEFORE UPDATE OF id, licensor, work, edition, holder, created_by, created_at ON rights_licenses
        BEGIN SELECT RAISE(ABORT, 'license identity (licensor, work, edition, holder) is immutable; register a new license instead'); END""",
    """CREATE TRIGGER rights_licenses_versioned_update BEFORE UPDATE ON rights_licenses
        BEGIN
            SELECT CASE
                WHEN NEW.version IS NOT OLD.version + 1
                THEN RAISE(ABORT, 'a license changes only by moving to its next version')
                WHEN NOT EXISTS (SELECT 1 FROM rights_license_versions WHERE license_id = NEW.id AND version = NEW.version)
                THEN RAISE(ABORT, 'a license version is recorded before the license moves to it')
            END;
        END""",
    """CREATE TABLE rights_document_tags (
        id TEXT PRIMARY KEY,
        document_id TEXT NOT NULL REFERENCES documents(id),
        license_id TEXT NOT NULL REFERENCES rights_licenses(id),
        license_version INTEGER NOT NULL,
        status TEXT NOT NULL CHECK (status IN ('active','removed')),
        tagged_by TEXT NOT NULL,
        tagged_at TEXT NOT NULL,
        removed_by TEXT,
        removed_at TEXT,
        removal_reason TEXT
    )""",
    "CREATE UNIQUE INDEX rights_document_tags_one_active ON rights_document_tags (document_id, license_id) WHERE status = 'active'",
    "CREATE INDEX rights_document_tags_license ON rights_document_tags (license_id, status)",
    """CREATE TRIGGER rights_document_tags_born_active BEFORE INSERT ON rights_document_tags
        BEGIN
            SELECT CASE
                WHEN NEW.status IS NOT 'active' OR NEW.removed_by IS NOT NULL OR NEW.removed_at IS NOT NULL OR NEW.removal_reason IS NOT NULL
                THEN RAISE(ABORT, 'a document tag is created active; it is removed only through untagging')
                WHEN NEW.license_version IS NOT (SELECT version FROM rights_licenses WHERE id = NEW.license_id)
                THEN RAISE(ABORT, 'a document tag records the license''s current version')
            END;
        END""",
    "CREATE TRIGGER rights_document_tags_no_delete BEFORE DELETE ON rights_document_tags BEGIN SELECT RAISE(ABORT, 'document tags are history and are never deleted'); END",
    """CREATE TRIGGER rights_document_tags_binding_immutable BEFORE UPDATE OF id, document_id, license_id, license_version, tagged_by, tagged_at ON rights_document_tags
        BEGIN SELECT RAISE(ABORT, 'a document tag binding is immutable; untag and tag again instead'); END""",
    """CREATE TRIGGER rights_document_tags_remove_once BEFORE UPDATE ON rights_document_tags
        WHEN NOT (OLD.status = 'active' AND NEW.status = 'removed' AND NEW.removed_by IS NOT NULL AND NEW.removed_at IS NOT NULL AND NEW.removal_reason IS NOT NULL)
        BEGIN SELECT RAISE(ABORT, 'a document tag changes only once, from active to removed'); END""",
    """CREATE TABLE rights_purges (
        id TEXT PRIMARY KEY,
        document_id TEXT NOT NULL REFERENCES documents(id),
        license_id TEXT NOT NULL REFERENCES rights_licenses(id),
        license_version INTEGER NOT NULL,
        expires_on TEXT NOT NULL,
        purged_on TEXT NOT NULL,
        note TEXT NOT NULL DEFAULT '',
        purged_by TEXT NOT NULL,
        purged_at TEXT NOT NULL,
        UNIQUE (document_id, license_id, license_version)
    )""",
    """CREATE TRIGGER rights_purges_guard BEFORE INSERT ON rights_purges
        BEGIN
            SELECT CASE
                WHEN NOT EXISTS (SELECT 1 FROM rights_document_tags WHERE document_id = NEW.document_id AND license_id = NEW.license_id AND status = 'active')
                THEN RAISE(ABORT, 'a purge is recorded only for a document tagged with the license')
                WHEN NEW.license_version IS NOT (SELECT version FROM rights_licenses WHERE id = NEW.license_id)
                THEN RAISE(ABORT, 'a purge binds the license''s current version')
                WHEN NEW.expires_on IS NOT (SELECT expires_on FROM rights_license_versions WHERE license_id = NEW.license_id AND version = NEW.license_version)
                THEN RAISE(ABORT, 'a purge records the expiry date of the license version it answers')
                WHEN date(NEW.purged_on) IS NOT NEW.purged_on OR NEW.purged_on > date('now')
                THEN RAISE(ABORT, 'purged_on must be a valid YYYY-MM-DD date that is not in the future')
                WHEN NEW.purged_on <= NEW.expires_on
                THEN RAISE(ABORT, 'a purge is recorded only after the license has expired')
            END;
        END""",
    "CREATE TRIGGER rights_purges_no_update BEFORE UPDATE ON rights_purges BEGIN SELECT RAISE(ABORT, 'purge records are immutable'); END",
    "CREATE TRIGGER rights_purges_no_delete BEFORE DELETE ON rights_purges BEGIN SELECT RAISE(ABORT, 'purge records are immutable'); END",
]

# Integrity guards, as their own catalog entry so a workspace that already applied
# ``rights`` upgrades in place (applied entries are append-only).
# * No row is ever replaced.  With recursive_triggers off, INSERT OR REPLACE (and REPLACE)
#   deletes the conflicting row without firing the no-delete triggers, so every insert
#   that collides with an existing id or unique key is refused before conflict resolution
#   (INSERT OR IGNORE is refused the same way).
# * Terms are well formed: processor names are distinct, trimmed, non-empty strings and
#   no use is listed twice.
# * A tag is not removed while the purge its expired license requires is outstanding.
# * A purge is recorded for a document that is or was tagged with the license (a tag
#   removed after expiry does not discharge the purge), and at most once per expiry.
#   This replaces ``rights_purges_guard``, which required an active tag.
# Several of these objects are superseded by ``rights_registry_hardening`` below.
GUARDS_SCHEMA_NAME = "rights_integrity_guards"
GUARDS_SCHEMA_STATEMENTS = [
    """CREATE TRIGGER rights_licenses_no_replace BEFORE INSERT ON rights_licenses
        WHEN EXISTS (SELECT 1 FROM rights_licenses WHERE id = NEW.id
                     OR (lower(licensor) = lower(NEW.licensor) AND lower(work) = lower(NEW.work)
                         AND lower(edition) = lower(NEW.edition) AND lower(holder) = lower(NEW.holder)))
        BEGIN SELECT RAISE(ABORT, 'that license id or identity (licensor, work, edition, holder) is already registered; rights rows are never replaced'); END""",
    """CREATE TRIGGER rights_license_versions_no_replace BEFORE INSERT ON rights_license_versions
        WHEN EXISTS (SELECT 1 FROM rights_license_versions WHERE id = NEW.id OR (license_id = NEW.license_id AND version = NEW.version))
        BEGIN SELECT RAISE(ABORT, 'license version rows are never replaced; record the next version instead'); END""",
    """CREATE TRIGGER rights_license_versions_terms_shape BEFORE INSERT ON rights_license_versions
        BEGIN
            SELECT CASE
                WHEN json_valid(NEW.permitted_uses) = 0 OR json_type(NEW.permitted_uses) IS NOT 'array'
                THEN RAISE(ABORT, 'permitted_uses must be a JSON array of use names')
                WHEN EXISTS (SELECT 1 FROM json_each(NEW.permitted_uses) GROUP BY value HAVING COUNT(*) > 1)
                THEN RAISE(ABORT, 'permitted_uses may not list a use twice')
                WHEN json_valid(NEW.processors) = 0 OR json_type(NEW.processors) IS NOT 'array'
                THEN RAISE(ABORT, 'processors must be a JSON array of processor names')
                WHEN EXISTS (SELECT 1 FROM json_each(NEW.processors) WHERE type IS NOT 'text' OR length(trim(value)) = 0 OR value IS NOT trim(value))
                THEN RAISE(ABORT, 'processors must be trimmed, non-empty processor name strings')
                WHEN EXISTS (SELECT 1 FROM json_each(NEW.processors) GROUP BY lower(value) HAVING COUNT(*) > 1)
                THEN RAISE(ABORT, 'processors may not list a processor twice')
            END;
        END""",
    """CREATE TRIGGER rights_document_tags_no_replace BEFORE INSERT ON rights_document_tags
        BEGIN
            SELECT CASE
                WHEN EXISTS (SELECT 1 FROM rights_document_tags WHERE id = NEW.id)
                THEN RAISE(ABORT, 'document tag rows are never replaced; tag the document again with a new tag')
                WHEN EXISTS (SELECT 1 FROM rights_document_tags WHERE document_id = NEW.document_id AND license_id = NEW.license_id AND status = 'active')
                THEN RAISE(ABORT, 'the document already carries an active tag for this license')
            END;
        END""",
    """CREATE TRIGGER rights_document_tags_purge_before_untag BEFORE UPDATE OF status ON rights_document_tags
        WHEN OLD.status = 'active' AND NEW.status = 'removed' AND EXISTS (
            SELECT 1 FROM rights_licenses l JOIN rights_license_versions v ON v.license_id = l.id AND v.version = l.version
            WHERE l.id = OLD.license_id AND v.purge_on_expiry = 1 AND v.expires_on IS NOT NULL AND v.expires_on < date('now')
              AND NOT EXISTS (SELECT 1 FROM rights_purges p WHERE p.document_id = OLD.document_id AND p.license_id = OLD.license_id AND p.purged_on > v.expires_on))
        BEGIN SELECT RAISE(ABORT, 'the expired license requires derived copies of this document to be purged; record the purge before untagging'); END""",
    "DROP TRIGGER IF EXISTS rights_purges_guard",
    """CREATE TRIGGER rights_purges_guard_v2 BEFORE INSERT ON rights_purges
        BEGIN
            SELECT CASE
                WHEN EXISTS (SELECT 1 FROM rights_purges WHERE id = NEW.id
                             OR (document_id = NEW.document_id AND license_id = NEW.license_id AND license_version = NEW.license_version))
                THEN RAISE(ABORT, 'purge records are never replaced')
                WHEN NOT EXISTS (SELECT 1 FROM rights_document_tags WHERE document_id = NEW.document_id AND license_id = NEW.license_id)
                THEN RAISE(ABORT, 'a purge is recorded only for a document that is or was tagged with the license')
                WHEN NEW.license_version IS NOT (SELECT version FROM rights_licenses WHERE id = NEW.license_id)
                THEN RAISE(ABORT, 'a purge binds the license''s current version')
                WHEN NEW.expires_on IS NOT (SELECT expires_on FROM rights_license_versions WHERE license_id = NEW.license_id AND version = NEW.license_version)
                THEN RAISE(ABORT, 'a purge records the expiry date of the license version it answers')
                WHEN date(NEW.purged_on) IS NOT NEW.purged_on OR NEW.purged_on > date('now')
                THEN RAISE(ABORT, 'purged_on must be a valid YYYY-MM-DD date that is not in the future')
                WHEN NEW.purged_on <= NEW.expires_on
                THEN RAISE(ABORT, 'a purge is recorded only after the license has expired')
                WHEN EXISTS (SELECT 1 FROM rights_purges WHERE document_id = NEW.document_id AND license_id = NEW.license_id AND purged_on > NEW.expires_on)
                THEN RAISE(ABORT, 'a purge of this document under this license already answers that expiry')
            END;
        END""",
]

_VERSION_COLUMNS = "id, license_id, version, permitted_uses, processors, expires_on, purge_on_expiry, note, terms_hash, created_by, created_at"

# Registry hardening, a third catalog entry (the two above are applied history).
# 1. ``rights_license_versions`` is rebuilt with an IMMEDIATE foreign key to its license.
#    The original DEFERRABLE INITIALLY DEFERRED key let a raw orphan insert fail only at
#    COMMIT, where SQLite keeps the failed transaction open (and the core transaction
#    helper does not roll back a failed COMMIT), leaving the shared connection stuck.  A
#    license and its version-1 terms are now inserted in ONE statement through the
#    ``rights_license_registrations`` view, so the immediate key is satisfied at the end
#    of that statement.  The rows are copied out to a holding table and back, never
#    renamed: ALTER TABLE ... RENAME re-parses every trigger in the whole schema and fails
#    on any trigger (of any module) that names a table created by a later entry.  Triggers
#    on other tables that name the versions table resolve it by name when they run, so they
#    stay; the two license insert triggers and the two tag removal triggers are merged so
#    their refusals come in a fixed order.
# 2. A tag removal records a well-formed UTC timestamp that is not before the tag, not in
#    the future and not backdated (a backdated removal would hide a purge that a later
#    retroactive expiry requires), and names who removed it.
# 3. ``rights_unadopted_versions`` records a terms row written outside the registry API
#    (never adopted) that ``supersede_unadopted_version`` retired; it never takes effect.
# 4. ``rights_ai_processor_settings`` holds the versioned default AI processor.
HARDENING_SCHEMA_NAME = "rights_registry_hardening"
HARDENING_SCHEMA_STATEMENTS = [
    "DROP TRIGGER IF EXISTS rights_licenses_born_v1",
    "DROP TRIGGER IF EXISTS rights_licenses_no_replace",
    "DROP TRIGGER IF EXISTS rights_document_tags_purge_before_untag",
    "CREATE TABLE rights_license_versions_hold AS SELECT " + _VERSION_COLUMNS + " FROM rights_license_versions",
    "DROP TABLE rights_license_versions",
    """CREATE TABLE rights_license_versions (
        id TEXT PRIMARY KEY,
        license_id TEXT NOT NULL REFERENCES rights_licenses(id),
        version INTEGER NOT NULL CHECK (version >= 1),
        permitted_uses TEXT NOT NULL,
        processors TEXT NOT NULL,
        expires_on TEXT,
        purge_on_expiry INTEGER NOT NULL CHECK (purge_on_expiry IN (0, 1)),
        note TEXT NOT NULL DEFAULT '',
        terms_hash TEXT NOT NULL,
        created_by TEXT NOT NULL,
        created_at TEXT NOT NULL,
        UNIQUE (license_id, version)
    )""",
    "INSERT INTO rights_license_versions (" + _VERSION_COLUMNS + ") SELECT " + _VERSION_COLUMNS
    + " FROM rights_license_versions_hold ORDER BY license_id, version",
    "DROP TABLE rights_license_versions_hold",
    """CREATE TRIGGER rights_license_versions_guard BEFORE INSERT ON rights_license_versions
        BEGIN
            SELECT CASE
                WHEN EXISTS (SELECT 1 FROM rights_license_versions WHERE id = NEW.id OR (license_id = NEW.license_id AND version = NEW.version))
                THEN RAISE(ABORT, 'license version rows are never replaced; record the next version instead')
                WHEN NEW.version IS NOT COALESCE((SELECT MAX(version) FROM rights_license_versions WHERE license_id = NEW.license_id), 0) + 1
                THEN RAISE(ABORT, 'license versions are contiguous: a new version is the next number')
                WHEN NEW.version IS NOT COALESCE((SELECT version FROM rights_licenses WHERE id = NEW.license_id), 0) + 1
                THEN RAISE(ABORT, 'a new license version follows the license''s current version')
                WHEN NEW.expires_on IS NOT NULL AND date(NEW.expires_on) IS NOT NEW.expires_on
                THEN RAISE(ABORT, 'expires_on must be a valid YYYY-MM-DD date')
                WHEN json_valid(NEW.permitted_uses) = 0 OR json_type(NEW.permitted_uses) IS NOT 'array'
                THEN RAISE(ABORT, 'permitted_uses must be a JSON array of use names')
                WHEN EXISTS (SELECT 1 FROM json_each(NEW.permitted_uses) WHERE type IS NOT 'text' OR value NOT IN (""" + _USES_SQL + """))
                THEN RAISE(ABORT, 'permitted_uses may hold only known use names')
                WHEN EXISTS (SELECT 1 FROM json_each(NEW.permitted_uses) GROUP BY value HAVING COUNT(*) > 1)
                THEN RAISE(ABORT, 'permitted_uses may not list a use twice')
                WHEN json_valid(NEW.processors) = 0 OR json_type(NEW.processors) IS NOT 'array'
                THEN RAISE(ABORT, 'processors must be a JSON array of processor names')
                WHEN EXISTS (SELECT 1 FROM json_each(NEW.processors) WHERE type IS NOT 'text' OR length(trim(value)) = 0 OR value IS NOT trim(value))
                THEN RAISE(ABORT, 'processors must be trimmed, non-empty processor name strings')
                WHEN EXISTS (SELECT 1 FROM json_each(NEW.processors) GROUP BY lower(value) HAVING COUNT(*) > 1)
                THEN RAISE(ABORT, 'processors may not list a processor twice')
            END;
        END""",
    "CREATE TRIGGER rights_license_versions_no_update BEFORE UPDATE ON rights_license_versions BEGIN SELECT RAISE(ABORT, 'license versions are immutable; record the next version instead'); END",
    "CREATE TRIGGER rights_license_versions_no_delete BEFORE DELETE ON rights_license_versions BEGIN SELECT RAISE(ABORT, 'license versions are immutable history'); END",
    """CREATE TRIGGER rights_licenses_insert_guard BEFORE INSERT ON rights_licenses
        BEGIN
            SELECT CASE
                WHEN EXISTS (SELECT 1 FROM rights_licenses WHERE id = NEW.id
                             OR (lower(licensor) = lower(NEW.licensor) AND lower(work) = lower(NEW.work)
                                 AND lower(edition) = lower(NEW.edition) AND lower(holder) = lower(NEW.holder)))
                THEN RAISE(ABORT, 'that license id or identity (licensor, work, edition, holder) is already registered; rights rows are never replaced')
                WHEN NEW.version IS NOT 1
                THEN RAISE(ABORT, 'a license is registered at version 1')
                WHEN NOT EXISTS (SELECT 1 FROM rights_license_versions WHERE license_id = NEW.id AND version = 1)
                THEN RAISE(ABORT, 'a license is registered together with its version-1 terms')
            END;
        END""",
    """CREATE TRIGGER rights_document_tags_removal_guard BEFORE UPDATE OF status ON rights_document_tags
        WHEN OLD.status = 'active' AND NEW.status = 'removed'
        BEGIN
            SELECT CASE
                WHEN NEW.removed_by IS NULL OR NEW.removed_at IS NULL OR NEW.removal_reason IS NULL
                THEN RAISE(ABORT, 'a document tag changes only once, from active to removed')
                WHEN EXISTS (
                    SELECT 1 FROM rights_licenses l JOIN rights_license_versions v ON v.license_id = l.id AND v.version = l.version
                    WHERE l.id = OLD.license_id AND v.purge_on_expiry = 1 AND v.expires_on IS NOT NULL AND v.expires_on < date('now')
                      AND NOT EXISTS (SELECT 1 FROM rights_purges p WHERE p.document_id = OLD.document_id AND p.license_id = OLD.license_id AND p.purged_on > v.expires_on))
                THEN RAISE(ABORT, 'the expired license requires derived copies of this document to be purged; record the purge before untagging')
                WHEN typeof(NEW.removed_by) IS NOT 'text' OR length(trim(NEW.removed_by)) = 0
                THEN RAISE(ABORT, 'removed_by must name who removed the tag')
                WHEN typeof(NEW.removed_at) IS NOT 'text' OR strftime('%Y-%m-%dT%H:%M:%SZ', NEW.removed_at) IS NOT NEW.removed_at
                THEN RAISE(ABORT, 'removed_at must be a UTC timestamp written YYYY-MM-DDTHH:MM:SSZ')
                WHEN NEW.removed_at < OLD.tagged_at
                THEN RAISE(ABORT, 'a document tag cannot be removed before it was tagged')
                WHEN NEW.removed_at > strftime('%Y-%m-%dT%H:%M:%SZ', 'now', '+1 minute')
                THEN RAISE(ABORT, 'removed_at may not be in the future')
                WHEN NEW.removed_at < strftime('%Y-%m-%dT%H:%M:%SZ', 'now', '-5 minutes')
                THEN RAISE(ABORT, 'removed_at records the moment of removal; it cannot be backdated')
            END;
        END""",
    """CREATE VIEW rights_license_registrations AS
        SELECT l.id AS license_id, l.licensor, l.work, l.edition, l.holder, v.id AS version_id, v.permitted_uses, v.processors,
               v.expires_on, v.purge_on_expiry, v.note, v.terms_hash, l.created_by, l.created_at
        FROM rights_licenses l JOIN rights_license_versions v ON v.license_id = l.id AND v.version = 1""",
    """CREATE TRIGGER rights_license_registrations_insert INSTEAD OF INSERT ON rights_license_registrations
        BEGIN
            INSERT INTO rights_license_versions (""" + _VERSION_COLUMNS + """)
            VALUES (NEW.version_id, NEW.license_id, 1, NEW.permitted_uses, NEW.processors, NEW.expires_on, NEW.purge_on_expiry,
                    COALESCE(NEW.note, ''), NEW.terms_hash, NEW.created_by, NEW.created_at);
            INSERT INTO rights_licenses (id, licensor, work, edition, holder, version, created_by, created_at, updated_at)
            VALUES (NEW.license_id, NEW.licensor, NEW.work, NEW.edition, NEW.holder, 1, NEW.created_by, NEW.created_at, NEW.created_at);
        END""",
    """CREATE TABLE rights_unadopted_versions (
        license_id TEXT NOT NULL REFERENCES rights_licenses(id),
        version INTEGER NOT NULL,
        superseded_by INTEGER NOT NULL,
        note TEXT NOT NULL DEFAULT '',
        recorded_by TEXT NOT NULL,
        recorded_at TEXT NOT NULL,
        PRIMARY KEY (license_id, version)
    )""",
    """CREATE TRIGGER rights_unadopted_versions_guard BEFORE INSERT ON rights_unadopted_versions
        BEGIN
            SELECT CASE
                WHEN EXISTS (SELECT 1 FROM rights_unadopted_versions WHERE license_id = NEW.license_id AND version = NEW.version)
                THEN RAISE(ABORT, 'unadopted-version records are never replaced')
                WHEN NOT EXISTS (SELECT 1 FROM rights_license_versions WHERE license_id = NEW.license_id AND version = NEW.version)
                THEN RAISE(ABORT, 'an unadopted-version record names a recorded license version')
                WHEN NEW.superseded_by IS NOT NEW.version + 1 OR NEW.superseded_by IS NOT (SELECT version FROM rights_licenses WHERE id = NEW.license_id)
                THEN RAISE(ABORT, 'an unadopted version is superseded by the next version, which the license has moved to')
                WHEN NOT EXISTS (
                    SELECT 1 FROM rights_license_versions s JOIN rights_license_versions p ON p.license_id = s.license_id AND p.version = NEW.version - 1
                    WHERE s.license_id = NEW.license_id AND s.version = NEW.superseded_by
                      AND json(s.permitted_uses) = json(p.permitted_uses) AND json(s.processors) = json(p.processors)
                      AND s.expires_on IS p.expires_on AND s.purge_on_expiry = p.purge_on_expiry)
                THEN RAISE(ABORT, 'the superseding version restores the terms in force before the unadopted version')
            END;
        END""",
    "CREATE TRIGGER rights_unadopted_versions_no_update BEFORE UPDATE ON rights_unadopted_versions BEGIN SELECT RAISE(ABORT, 'unadopted-version records are immutable'); END",
    "CREATE TRIGGER rights_unadopted_versions_no_delete BEFORE DELETE ON rights_unadopted_versions BEGIN SELECT RAISE(ABORT, 'unadopted-version records are immutable'); END",
    """CREATE TABLE rights_ai_processor_settings (
        id TEXT PRIMARY KEY,
        version INTEGER NOT NULL UNIQUE CHECK (version >= 1),
        processor TEXT,
        note TEXT NOT NULL DEFAULT '',
        set_by TEXT NOT NULL CHECK (length(trim(set_by)) > 0),
        set_at TEXT NOT NULL
    )""",
    """CREATE TRIGGER rights_ai_processor_settings_guard BEFORE INSERT ON rights_ai_processor_settings
        BEGIN
            SELECT CASE
                WHEN EXISTS (SELECT 1 FROM rights_ai_processor_settings WHERE id = NEW.id OR version = NEW.version)
                THEN RAISE(ABORT, 'default AI processor settings are never replaced; record the next setting instead')
                WHEN NEW.version IS NOT COALESCE((SELECT MAX(version) FROM rights_ai_processor_settings), 0) + 1
                THEN RAISE(ABORT, 'default AI processor settings are contiguous: a new setting is the next version')
                WHEN NEW.processor IS NOT NULL AND (typeof(NEW.processor) IS NOT 'text' OR length(trim(NEW.processor)) = 0 OR NEW.processor IS NOT trim(NEW.processor))
                THEN RAISE(ABORT, 'the default AI processor is a trimmed, non-empty processor name, or NULL for none')
            END;
        END""",
    "CREATE TRIGGER rights_ai_processor_settings_no_update BEFORE UPDATE ON rights_ai_processor_settings BEGIN SELECT RAISE(ABORT, 'default AI processor settings are immutable; record the next setting instead'); END",
    "CREATE TRIGGER rights_ai_processor_settings_no_delete BEFORE DELETE ON rights_ai_processor_settings BEGIN SELECT RAISE(ABORT, 'default AI processor settings are immutable history'); END",
]

# Registered here, in this order, so each follow-on entry sits after the objects it
# changes; the plugin loader's own registration of SCHEMA_NAME is then a no-op.
register_schema_version(SCHEMA_NAME, SCHEMA_STATEMENTS)
register_schema_version(GUARDS_SCHEMA_NAME, GUARDS_SCHEMA_STATEMENTS)
register_schema_version(HARDENING_SCHEMA_NAME, HARDENING_SCHEMA_STATEMENTS)


class RightsError(RuntimeError):
    """Invalid rights-registry input, an unknown record or a refused change."""


_KEEP: Any = type("_Keep", (), {"__repr__": lambda self: "<unchanged>"})()
_DATE_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
_INFO = "informational: content rights post no journals and never block a close"

_LICENSE_SELECT = """
    SELECT l.id, l.licensor, l.work, l.edition, l.holder, l.version, l.created_by, l.created_at, l.updated_at,
           v.id AS version_id, v.permitted_uses, v.processors, v.expires_on, v.purge_on_expiry, v.note, v.terms_hash,
           v.created_by AS version_created_by, v.created_at AS version_created_at
    FROM rights_licenses l
    JOIN rights_license_versions v ON v.license_id = l.id AND v.version = l.version
"""


def _fold(text: str) -> str:
    """Caseless form of a name: NFKC-normalised Unicode case folding."""
    return unicodedata.normalize("NFKC", unicodedata.normalize("NFKC", text).casefold())


def _identity_key(row: Any) -> tuple[str, ...]:
    """(licensor, work, edition, holder) compared ignoring case and runs of whitespace."""
    return tuple(" ".join(_fold(str(row[k])).split()) for k in ("licensor", "work", "edition", "holder"))


class Plugin:
    def __init__(self, cipher):
        self.c = cipher
        self.db = cipher.db
        self.audit = cipher.audit

    # ---- validation helpers ------------------------------------------------- #

    @staticmethod
    def _text(value: Any, label: str, *, required: bool = True) -> str:
        if value is None:
            value = ""
        if not isinstance(value, str):
            raise RightsError(f"{label} must be a string, not {type(value).__name__}")
        text = value.strip()
        if required and not text:
            raise RightsError(f"{label} is required")
        return text

    @staticmethod
    def _use(value: Any) -> str:
        if not isinstance(value, str) or value.strip() not in USES:
            raise RightsError(f"unknown use {value!r}; uses are {', '.join(USES)}")
        return value.strip()

    @classmethod
    def _uses(cls, value: Any) -> list[str]:
        if value is None or isinstance(value, (str, bytes, dict)):
            raise RightsError(f"permitted_uses must be a list of use names ({', '.join(USES)}), not {type(value).__name__}")
        try:
            items = list(value)
        except TypeError:
            raise RightsError(f"permitted_uses must be a list of use names, not {type(value).__name__}") from None
        out: list[str] = []
        for item in items:
            name = cls._use(item)
            if name in out:
                raise RightsError(f"use {name!r} is listed twice in permitted_uses")
            out.append(name)
        return sorted(out)

    @classmethod
    def _processors(cls, value: Any) -> list[str]:
        if value is None or isinstance(value, (str, bytes, dict)):
            raise RightsError(f"processors must be a list of processor names, not {type(value).__name__}")
        try:
            items = list(value)
        except TypeError:
            raise RightsError(f"processors must be a list of processor names, not {type(value).__name__}") from None
        out: list[str] = []
        for item in items:
            name = cls._text(item, "processor name")
            if _fold(name) in (_fold(p) for p in out):
                raise RightsError(f"processor {name!r} is listed twice (processor names compare ignoring case)")
            out.append(name)
        return sorted(out)

    @staticmethod
    def _day(value: Any, label: str = "date") -> _dt.date:
        if isinstance(value, _dt.datetime):
            raise RightsError(f"{label} must be a calendar date (YYYY-MM-DD), not a datetime")
        if isinstance(value, _dt.date):
            return value
        if isinstance(value, str):
            text = value.strip()
            if _DATE_RE.match(text):
                try:
                    return _dt.date.fromisoformat(text)
                except ValueError:
                    pass
            raise RightsError(f"{label} must be a valid YYYY-MM-DD date, got {value!r}")
        raise RightsError(f"{label} must be a YYYY-MM-DD string, not {type(value).__name__}")

    def _on(self, on_date: Any) -> _dt.date:
        return self._today() if on_date is None else self._day(on_date, "on_date")

    @staticmethod
    def _today() -> _dt.date:
        """The UTC calendar date, the default for every as-of question."""
        return utcnow().date()

    def _expiry(self, value: Any) -> str | None:
        return None if value is None else self._day(value, "expires_on").isoformat()

    @staticmethod
    def _purge_flag(value: Any) -> bool:
        if not isinstance(value, bool):
            raise RightsError(f"purge_on_expiry must be true or false, not {value!r}")
        return value

    @staticmethod
    def _expected_version(value: Any) -> int | None:
        if value is not None and (isinstance(value, bool) or not isinstance(value, int)):
            raise RightsError(f"expected_version must be an integer, not {value!r}")
        return value

    def _document(self, document_id: Any) -> dict[str, Any]:
        if not isinstance(document_id, str) or not document_id.strip():
            raise RightsError("document_id is required")
        row = self.db.one("SELECT id, project_id, kind, title, created_at FROM documents WHERE id=?", (document_id.strip(),))
        if row is None:
            raise RightsError(f"unknown document {document_id}")
        return row

    def _project(self, project_id: Any) -> dict[str, Any]:
        row = self.db.one("SELECT id, name FROM projects WHERE id=?", (project_id,)) if isinstance(project_id, str) else None
        if row is None:
            raise RightsError(f"unknown project {project_id}")
        return row

    @staticmethod
    def _terms_hash(identity: dict[str, Any], uses: list[str], processors: list[str], expires_on: str | None, purge: bool) -> str:
        return hash_json({**identity, "permitted_uses": uses, "processors": processors, "expires_on": expires_on, "purge_on_expiry": purge})

    @staticmethod
    def _expired(expires_on: str | None, day: _dt.date) -> bool:
        """Expired from the day after ``expires_on``; never when there is no expiry."""
        return expires_on is not None and day.isoformat() > expires_on

    @staticmethod
    def _decode(row: dict[str, Any]) -> dict[str, Any]:
        row["permitted_uses"] = json.loads(row["permitted_uses"])
        row["processors"] = json.loads(row["processors"])
        row["purge_on_expiry"] = bool(row["purge_on_expiry"])
        return row

    @staticmethod
    def _label(t: dict[str, Any]) -> str:
        return f"license {t['id']} ({t['licensor']}, {t['work']}, {t['edition']}, v{t['version']})"

    # ---- licenses ----------------------------------------------------------- #

    def register_license(self, licensor: str, work: str, edition: str, holder: str, permitted_uses: Iterable[str],
                         processors: Iterable[str] = (), expires_on: str | None = None, purge_on_expiry: bool = False,
                         actor: str = "owner", *, note: str = "") -> dict[str, Any]:
        """Register a license at version 1.  (licensor, work, edition, holder) is
        unique ignoring case (Unicode case folding) and runs of whitespace; a new
        edition or holder is a new license."""
        identity = {
            "licensor": self._text(licensor, "licensor"),
            "work": self._text(work, "work"),
            "edition": self._text(edition, "edition"),
            "holder": self._text(holder, "license holder"),
        }
        uses = self._uses(permitted_uses)
        procs = self._processors(processors)
        expiry = self._expiry(expires_on)
        purge = self._purge_flag(purge_on_expiry)
        note = self._text(note, "note", required=False)
        actor = self._text(actor, "actor")
        terms_hash = self._terms_hash(identity, uses, procs, expiry, purge)
        license_id = new_id("lic")
        now = utcnow_iso()
        key = _identity_key(identity)
        with self.db.transaction() as conn:
            self.db.require_write_authority()
            for row in conn.execute("SELECT id, licensor, work, edition, holder FROM rights_licenses ORDER BY created_at, id").fetchall():
                if _identity_key(row) == key:
                    raise RightsError(
                        f"{identity['work']} ({identity['edition']}) from {identity['licensor']} held by {identity['holder']} is already registered "
                        f"as license {row['id']} (identity compares ignoring case); use update_license to change its terms"
                    )
            # one statement inserts the version-1 terms and the license, so the immediate foreign key holds at its end
            conn.execute(
                "INSERT INTO rights_license_registrations (license_id, licensor, work, edition, holder, version_id, permitted_uses, processors, "
                "expires_on, purge_on_expiry, note, terms_hash, created_by, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (license_id, identity["licensor"], identity["work"], identity["edition"], identity["holder"], new_id("licv"),
                 json.dumps(uses), json.dumps(procs), expiry, int(purge), note, terms_hash, actor, now),
            )
            self.audit.record(actor, "rights.license_registered", "rights_license", license_id, {
                **identity, "version": 1, "permitted_uses": uses, "processors": procs, "expires_on": expiry,
                "purge_on_expiry": purge, "note": note, "terms_hash": terms_hash,
            })
        return self.license(license_id)

    def _pending_version(self, conn, lic: dict[str, Any]) -> int | None:
        top = conn.execute("SELECT MAX(version) FROM rights_license_versions WHERE license_id=?", (lic["id"],)).fetchone()[0]
        return top if top != lic["version"] else None

    def update_license(self, license_id: str, *, permitted_uses: Any = _KEEP, processors: Any = _KEEP, expires_on: Any = _KEEP,
                       purge_on_expiry: Any = _KEEP, note: str = "", expected_version: int | None = None, actor: str = "owner") -> dict[str, Any]:
        """Record the license's next terms version.  Omitted terms carry over;
        ``expires_on=None`` means the license no longer expires.  Identity
        (licensor, work, edition, holder) cannot change.  ``expected_version``,
        when given, must equal the current version (compare-and-set)."""
        actor = self._text(actor, "actor")
        note = self._text(note, "note", required=False)
        expected_version = self._expected_version(expected_version)
        new_uses = None if permitted_uses is _KEEP else self._uses(permitted_uses)
        new_procs = None if processors is _KEEP else self._processors(processors)
        new_expiry = _KEEP if expires_on is _KEEP else self._expiry(expires_on)
        new_purge = None if purge_on_expiry is _KEEP else self._purge_flag(purge_on_expiry)
        with self.db.transaction() as conn:
            self.db.require_write_authority()
            cur = self.license(license_id)
            if expected_version is not None and expected_version != cur["version"]:
                raise RightsError(f"license {cur['id']} is at version {cur['version']}, not {expected_version}; re-read it before updating")
            pending = self._pending_version(conn, cur)
            if pending is not None:
                raise RightsError(
                    f"license {cur['id']} is at version {cur['version']} but a version-{pending} terms row exists that it never moved to "
                    "(recorded outside the registry API); call supersede_unadopted_version to retire it, then update the license"
                )
            terms = {
                "permitted_uses": cur["permitted_uses"] if new_uses is None else new_uses,
                "processors": cur["processors"] if new_procs is None else new_procs,
                "expires_on": cur["expires_on"] if new_expiry is _KEEP else new_expiry,
                "purge_on_expiry": cur["purge_on_expiry"] if new_purge is None else new_purge,
            }
            changes = {k: {"from": cur[k], "to": v} for k, v in terms.items() if v != cur[k]}
            if not changes:
                raise RightsError(f"nothing to update on license {cur['id']}: the terms are unchanged")
            version, terms_hash = self._record_version(conn, cur, terms, note=note, actor=actor)
            self.audit.record(actor, "rights.license_updated", "rights_license", cur["id"], {
                "version": version, "previous_version": cur["version"], "changes": changes, "note": note, "terms_hash": terms_hash,
            })
        return self.license(license_id)

    def _record_version(self, conn, cur: dict[str, Any], terms: dict[str, Any], *, note: str, actor: str,
                        from_version: int | None = None) -> tuple[int, str]:
        """Insert the terms row after ``from_version`` (default: the license's current
        version) and move the license to it, inside the caller's transaction.
        Returns (new version, terms hash)."""
        identity = {k: cur[k] for k in ("licensor", "work", "edition", "holder")}
        terms_hash = self._terms_hash(identity, terms["permitted_uses"], terms["processors"], terms["expires_on"], terms["purge_on_expiry"])
        from_version = cur["version"] if from_version is None else from_version
        version = from_version + 1
        now = utcnow_iso()
        conn.execute(
            "INSERT INTO rights_license_versions (" + _VERSION_COLUMNS + ") VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (new_id("licv"), cur["id"], version, json.dumps(terms["permitted_uses"]), json.dumps(terms["processors"]), terms["expires_on"],
             int(terms["purge_on_expiry"]), note, terms_hash, actor, now),
        )
        moved = conn.execute("UPDATE rights_licenses SET version=?, updated_at=? WHERE id=? AND version=?", (version, now, cur["id"], from_version))
        if moved.rowcount != 1:
            raise RightsError(f"license {cur['id']} changed concurrently; retry")
        return version, terms_hash

    def supersede_unadopted_version(self, license_id: str, actor: str = "owner", *, note: str = "") -> dict[str, Any]:
        """Repair path for a terms row recorded outside the registry API that the
        license never moved to (version N+1 while the license is at N), which
        otherwise blocks every ``update_license``.  In one transaction the license
        passes over N+1 to a new version N+2 that restores the version-N terms,
        and the stray row is recorded in ``rights_unadopted_versions``: its terms
        are never in force at any committed point, are excluded from as-recorded
        views and stay visible in ``license_history`` and the audit export."""
        actor = self._text(actor, "actor")
        note = self._text(note, "note", required=False)
        with self.db.transaction() as conn:
            self.db.require_write_authority()
            cur = self.license(license_id)
            pending = self._pending_version(conn, cur)
            if pending is None:
                raise RightsError(f"license {cur['id']} has no unadopted terms version; nothing to supersede")
            stray = self._decode(dict(conn.execute("SELECT * FROM rights_license_versions WHERE license_id=? AND version=?", (cur["id"], pending)).fetchone()))
            now = utcnow_iso()
            moved = conn.execute("UPDATE rights_licenses SET version=?, updated_at=? WHERE id=? AND version=?", (pending, now, cur["id"], cur["version"]))
            if moved.rowcount != 1:
                raise RightsError(f"license {cur['id']} changed concurrently; retry")
            terms = {k: cur[k] for k in ("permitted_uses", "processors", "expires_on", "purge_on_expiry")}
            restore_note = note or f"restores version {cur['version']} terms over unadopted version {pending}"
            version, _ = self._record_version(conn, cur, terms, note=restore_note, actor=actor, from_version=pending)
            conn.execute(
                "INSERT INTO rights_unadopted_versions (license_id, version, superseded_by, note, recorded_by, recorded_at) VALUES (?,?,?,?,?,?)",
                (cur["id"], pending, version, note, actor, now),
            )
            self.audit.record(actor, "rights.unadopted_version_superseded", "rights_license", cur["id"], {
                "unadopted_version": pending, "unadopted_version_id": stray["id"], "unadopted_terms_hash": stray["terms_hash"],
                "unadopted_terms": {k: stray[k] for k in ("permitted_uses", "processors", "expires_on", "purge_on_expiry")},
                "unadopted_created_by": stray["created_by"], "unadopted_created_at": stray["created_at"],
                "restored_from_version": cur["version"], "version": version, "terms_hash": cur["terms_hash"], "note": note,
            })
        return self.license(license_id)

    def license(self, license_id: str) -> dict[str, Any]:
        """The license with its current terms."""
        if not isinstance(license_id, str) or not license_id.strip():
            raise RightsError("license_id is required")
        row = self.db.one(_LICENSE_SELECT + " WHERE l.id=?", (license_id.strip(),))
        if row is None:
            raise RightsError(f"unknown license {license_id}")
        return self._decode(row)

    get_license = license

    def licenses(self) -> list[dict[str, Any]]:
        """Every license with its current terms."""
        return [self._decode(r) for r in self.db.query(_LICENSE_SELECT + " ORDER BY lower(l.licensor), lower(l.work), lower(l.edition), l.created_at, l.id")]

    def license_history(self, license_id: str) -> list[dict[str, Any]]:
        """Every terms version of the license, oldest first, each with its
        ``status``: ``current``, ``superseded`` (once in force), ``unadopted``
        (recorded outside the API, retired by ``supersede_unadopted_version``,
        never in force) or ``pending_unadopted`` (recorded outside the API and
        not yet retired)."""
        lic = self.license(license_id)
        unadopted = {r["version"] for r in self.db.query("SELECT version FROM rights_unadopted_versions WHERE license_id=?", (lic["id"],))}
        rows = [self._decode(r) for r in self.db.query("SELECT * FROM rights_license_versions WHERE license_id=? ORDER BY version", (lic["id"],))]
        for r in rows:
            r["status"] = ("unadopted" if r["version"] in unadopted else "pending_unadopted" if r["version"] > lic["version"]
                           else "current" if r["version"] == lic["version"] else "superseded")
        return rows

    def _terms(self, as_of: str | None = None) -> dict[str, dict[str, Any]]:
        """Each license's terms: current (``as_of`` None), or as recorded at the end of
        the UTC date ``as_of`` - the latest adopted version recorded by that day
        (licenses registered later are absent)."""
        if as_of is None:
            return {r["id"]: self._decode(r) for r in self.db.query(_LICENSE_SELECT)}
        headers = {h["id"]: h for h in self.db.query("SELECT id, licensor, work, edition, holder, version, created_by, created_at, updated_at FROM rights_licenses")}
        skipped = {(r["license_id"], r["version"]) for r in self.db.query("SELECT license_id, version FROM rights_unadopted_versions")}
        chosen: dict[str, dict[str, Any]] = {}
        for v in self.db.query("SELECT * FROM rights_license_versions ORDER BY license_id, version"):
            h = headers.get(v["license_id"])
            if h is None or v["version"] > h["version"] or (v["license_id"], v["version"]) in skipped or str(v["created_at"])[:10] > as_of:
                continue
            chosen[v["license_id"]] = v
        out = {}
        for lid, v in chosen.items():
            out[lid] = self._decode({
                **headers[lid], "version": v["version"], "version_id": v["id"], "permitted_uses": v["permitted_uses"], "processors": v["processors"],
                "expires_on": v["expires_on"], "purge_on_expiry": v["purge_on_expiry"], "note": v["note"], "terms_hash": v["terms_hash"],
                "version_created_by": v["created_by"], "version_created_at": v["created_at"],
            })
        return out

    # ---- default AI processor -------------------------------------------------------- #

    def default_processor(self) -> dict[str, Any]:
        """The configured default AI processor (``processor`` None when none is set;
        ``version`` 0 when it was never set)."""
        row = self.db.one("SELECT * FROM rights_ai_processor_settings ORDER BY version DESC LIMIT 1")
        if row is None:
            return {"processor": None, "version": 0, "id": None, "note": "", "set_by": None, "set_at": None}
        return {"processor": row["processor"], "version": row["version"], "id": row["id"], "note": row["note"], "set_by": row["set_by"], "set_at": row["set_at"]}

    def default_processor_history(self) -> list[dict[str, Any]]:
        return self.db.query("SELECT * FROM rights_ai_processor_settings ORDER BY version")

    def set_default_processor(self, processor: str | None, actor: str = "owner", *, note: str = "", expected_version: int | None = None) -> dict[str, Any]:
        """Name the processor that AI checks test when the caller names none (the
        one Cipher's own assistant uses), or clear it with ``None``.  Versioned
        and audited; a license must still list the processor for its content to
        be used by it."""
        name = None if processor is None else self._text(processor, "processor")
        actor = self._text(actor, "actor")
        note = self._text(note, "note", required=False)
        expected_version = self._expected_version(expected_version)
        with self.db.transaction() as conn:
            self.db.require_write_authority()
            cur = self.default_processor()
            if expected_version is not None and expected_version != cur["version"]:
                raise RightsError(f"the default AI processor setting is at version {cur['version']}, not {expected_version}; re-read it before changing it")
            same = (name is None and cur["processor"] is None) or (
                name is not None and cur["processor"] is not None and _fold(name) == _fold(cur["processor"]))
            if same:
                raise RightsError("the default AI processor is already " + (repr(cur["processor"]) if cur["processor"] else "unset") + "; nothing to change")
            version = cur["version"] + 1
            setting_id = new_id("rset")
            conn.execute(
                "INSERT INTO rights_ai_processor_settings (id, version, processor, note, set_by, set_at) VALUES (?,?,?,?,?,?)",
                (setting_id, version, name, note, actor, utcnow_iso()),
            )
            self.audit.record(actor, "rights.default_processor_set", "rights_setting", "default_ai_processor", {
                "setting_id": setting_id, "version": version, "previous_processor": cur["processor"], "processor": name, "note": note,
            })
        return self.default_processor()

    def _resolve_processor(self, processor: Any, use: str) -> tuple[str | None, str | None]:
        """(processor tested, where it came from): the named one, else for an AI use
        the configured default, else none."""
        if processor is not None:
            return self._text(processor, "processor"), "named"
        if use in AI_USES:
            default = self.default_processor()["processor"]
            if default is not None:
                return default, "default"
        return None, None

    # ---- document tags ---------------------------------------------------------- #

    def tag_document(self, document_id: str, license_id: str, actor: str = "owner") -> dict[str, Any]:
        """Mark a document as content held under ``license_id``.  A document may
        carry several licenses; each may be tagged only once at a time."""
        actor = self._text(actor, "actor")
        with self.db.transaction() as conn:
            self.db.require_write_authority()
            doc = self._document(document_id)
            lic = self.license(license_id)
            dup = conn.execute("SELECT id FROM rights_document_tags WHERE document_id=? AND license_id=? AND status='active'", (doc["id"], lic["id"])).fetchone()
            if dup is not None:
                raise RightsError(f"document {doc['id']} is already tagged with license {lic['id']} (tag {dup['id']})")
            tag_id = new_id("rtag")
            conn.execute(
                "INSERT INTO rights_document_tags (id, document_id, license_id, license_version, status, tagged_by, tagged_at) VALUES (?,?,?,?,'active',?,?)",
                (tag_id, doc["id"], lic["id"], lic["version"], actor, utcnow_iso()),
            )
            self.audit.record(actor, "rights.document_tagged", "document", doc["id"], {
                "tag_id": tag_id, "license_id": lic["id"], "license_version": lic["version"], "terms_hash": lic["terms_hash"],
                "licensor": lic["licensor"], "work": lic["work"], "edition": lic["edition"],
            })
        return self._tag(tag_id)

    def untag_document(self, document_id: str, license_id: str, actor: str = "owner", *, reason: str = "") -> dict[str, Any]:
        """Remove the active tag.  The tag row stays as history; a document with no
        active tag and no owed purge is company-owned again.  Refused while the
        license has expired with a purge rule that no recorded purge answers yet
        (record_purge first).  A tag removed after its license expired with a
        purge rule - possible when the rule or the expiry is amended around the
        untag - leaves the purge owed, and every use of the document is refused
        until it is recorded."""
        actor = self._text(actor, "actor")
        reason = self._text(reason, "reason", required=False)
        today = self._today()
        with self.db.transaction() as conn:
            self.db.require_write_authority()
            doc = self._document(document_id)
            lic = self.license(license_id)
            tag = conn.execute("SELECT id FROM rights_document_tags WHERE document_id=? AND license_id=? AND status='active'", (doc["id"], lic["id"])).fetchone()
            if tag is None:
                raise RightsError(f"document {doc['id']} is not tagged with license {lic['id']}")
            if lic["purge_on_expiry"] and self._expired(lic["expires_on"], today) and self._answering_purge(doc["id"], lic) is None:
                raise RightsError(
                    f"{self._label(lic)} expired (valid through {lic['expires_on']}) and its purge rule requires derived copies of document {doc['id']} "
                    "to be purged; record_purge first, then untag"
                )
            conn.execute(
                "UPDATE rights_document_tags SET status='removed', removed_by=?, removed_at=?, removal_reason=? WHERE id=? AND status='active'",
                (actor, utcnow_iso(), reason, tag["id"]),
            )
            remaining = conn.execute("SELECT COUNT(*) FROM rights_document_tags WHERE document_id=? AND status='active'", (doc["id"],)).fetchone()[0]
            owed = self._owed_purges(doc["id"], today)
            self.audit.record(actor, "rights.document_untagged", "document", doc["id"], {
                "tag_id": tag["id"], "license_id": lic["id"], "license_version": lic["version"], "reason": reason,
                "remaining_tags": remaining, "purges_owed": [o["license_id"] for o in owed], "company_owned": remaining == 0 and not owed,
            })
        return self._tag(tag["id"])

    untag = untag_document

    def _tag(self, tag_id: str) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM rights_document_tags WHERE id=?", (tag_id,))
        if row is None:
            raise RightsError(f"unknown document tag {tag_id}")
        return row

    def _answering_purge(self, document_id: str, lic: dict[str, Any]) -> dict[str, Any] | None:
        """The latest purge of ``document_id`` recorded after the license's current
        expiry (one that answers it), or None."""
        if lic["expires_on"] is None:
            return None
        return self.db.one(
            "SELECT id, purged_on, purged_by FROM rights_purges WHERE document_id=? AND license_id=? AND purged_on > ? ORDER BY purged_at DESC, id DESC LIMIT 1",
            (document_id, lic["id"], lic["expires_on"]),
        )

    def document_tags(self, document_id: str, *, include_removed: bool = False) -> list[dict[str, Any]]:
        """The document's tags (active only unless ``include_removed``), oldest first."""
        doc = self._document(document_id)
        sql = "SELECT * FROM rights_document_tags WHERE document_id=?" + ("" if include_removed else " AND status='active'") + " ORDER BY tagged_at, id"
        return self.db.query(sql, (doc["id"],))

    def tagged_documents(self, license_id: str) -> list[dict[str, Any]]:
        """Documents currently tagged with the license."""
        lic = self.license(license_id)
        return self.db.query(
            "SELECT t.id AS tag_id, t.document_id, t.license_version AS tagged_at_version, t.tagged_by, t.tagged_at, d.project_id, d.kind, d.title "
            "FROM rights_document_tags t JOIN documents d ON d.id = t.document_id WHERE t.license_id=? AND t.status='active' ORDER BY t.tagged_at, t.id",
            (lic["id"],),
        )

    def _active_terms(self, document_id: str) -> list[dict[str, Any]]:
        rows = self.db.query(
            "SELECT t.id AS tag_id, t.tagged_at, lic.* FROM rights_document_tags t "
            "JOIN (" + _LICENSE_SELECT + ") lic ON lic.id = t.license_id "
            "WHERE t.document_id=? AND t.status='active' ORDER BY t.tagged_at, t.id",
            (document_id,),
        )
        return [self._decode(r) for r in rows]

    # ---- expired pairs (shared by use checks, expired_items and close_checks) ------ #

    def _expired_entries(self, day: str, *, as_recorded: bool, project_id: str | None = None,
                         document_id: str | None = None) -> list[dict[str, Any]]:
        """Every (document, license) pair whose license is expired on ``day`` and
        which is listed: the document is tagged with the license, or its tag was
        removed only after the license had expired with a purge rule and no purge
        answers that expiry yet (an owed purge).  ``as_recorded`` reads the
        registry as recorded at the end of ``day``; otherwise as it stands now."""
        terms = self._terms(day if as_recorded else None)
        where, params = [], []
        if project_id is not None:
            where.append("d.project_id = ?")
            params.append(project_id)
        if document_id is not None:
            where.append("t.document_id = ?")
            params.append(document_id)
        tags = self.db.query(
            "SELECT t.id, t.document_id, t.license_id, t.status, t.tagged_at, t.removed_at, d.project_id, d.kind, d.title, d.created_at AS document_created_at "
            "FROM rights_document_tags t JOIN documents d ON d.id = t.document_id" + (" WHERE " + " AND ".join(where) if where else ""),
            tuple(params),
        )
        purges: dict[tuple[str, str], list[dict[str, Any]]] = {}
        purge_sql = "SELECT id, document_id, license_id, purged_on, purged_by, purged_at FROM rights_purges" + (" WHERE document_id = ?" if document_id else "")
        for p in self.db.query(purge_sql, (document_id,) if document_id else ()):
            if as_recorded and p["purged_on"] > day:
                continue
            purges.setdefault((p["document_id"], p["license_id"]), []).append(p)
        pairs: dict[tuple[str, str], dict[str, Any]] = {}
        for t in tags:
            if as_recorded and str(t["tagged_at"])[:10] > day:
                continue  # tagged after the day
            if as_recorded:
                active = t["status"] == "active" or (t["removed_at"] is not None and str(t["removed_at"])[:10] > day)
            else:
                active = t["status"] == "active"
            pair = pairs.setdefault((t["document_id"], t["license_id"]), {"doc": t, "active": None, "removed": []})
            if active:
                pair["active"] = t
            else:
                pair["removed"].append(t)
        entries = []
        for (doc_id, lic_id), pair in pairs.items():
            lic = terms.get(lic_id)
            if lic is None or lic["expires_on"] is None or not lic["expires_on"] < day:
                continue
            answering = [p for p in purges.get((doc_id, lic_id), []) if p["purged_on"] > lic["expires_on"]]
            purge = max(answering, key=lambda p: (p["purged_at"], p["id"])) if answering else None
            if pair["active"] is not None:
                status, tag_id = "active", pair["active"]["id"]
            else:
                last = max(pair["removed"], key=lambda t: (str(t["removed_at"]), t["id"]))
                removed_after_expiry = str(last["removed_at"])[:10] > lic["expires_on"]
                if not (lic["purge_on_expiry"] and removed_after_expiry and purge is None):
                    continue  # removed while valid, or no purge rule, or already purged: nothing left behind
                status, tag_id = "removed", last["id"]
            d = pair["doc"]
            entries.append({
                "document_id": doc_id, "project_id": d["project_id"], "kind": d["kind"], "title": d["title"], "document_created_at": d["document_created_at"],
                "license_id": lic_id, "licensor": lic["licensor"], "work": lic["work"], "edition": lic["edition"], "holder": lic["holder"],
                "version": lic["version"], "terms_hash": lic["terms_hash"], "expires_on": lic["expires_on"], "purge_on_expiry": lic["purge_on_expiry"],
                "tag_status": status, "tag_id": tag_id, "purged": purge is not None,
                "purge_id": purge["id"] if purge else None, "purged_on": purge["purged_on"] if purge else None,
            })
        entries.sort(key=lambda e: (e["project_id"], e["document_created_at"], e["document_id"], e["expires_on"], e["license_id"]))
        return entries

    def _owed_purges(self, document_id: str, day: _dt.date) -> list[dict[str, Any]]:
        """Purges still owed on a document whose tag was removed after its license
        expired with a purge rule (current registry, expiry tested on ``day``)."""
        if self.db.one("SELECT 1 FROM rights_document_tags WHERE document_id=? AND status='removed' LIMIT 1", (document_id,)) is None:
            return []
        return [e for e in self._expired_entries(day.isoformat(), as_recorded=False, document_id=document_id) if e["tag_status"] == "removed"]

    # ---- use checks ------------------------------------------------------------- #

    def check_use(self, document_id: str, use: str, on_date: Any = None, *, processor: str | None = None) -> dict[str, Any]:
        """May ``document_id`` be used for ``use``, judged against the document's
        current tags, each license's current terms and the purges recorded so
        far, with expiry tested on ``on_date`` (UTC today by default)?
        ``on_date`` moves only the expiry test; this is not a reconstruction of
        what was allowed in the past.

        A document with no active tag and no owed purge is company-owned and
        allowed for every use.  Otherwise every tagged license must permit the
        use, be unexpired on the date and list the processor tested, and no
        purge may be owed.  The processor tested is ``processor`` when named;
        for an AI use with none named it is the configured default AI processor
        (``processor_source`` says which), and with neither the AI use of
        licensed content is refused.  For the other uses a processor is tested
        only when named.  The first refusing license is reported as
        ``license_id``.  When allowed, ``license_id`` is the governing license
        (the earliest expiry) and ``valid_until`` the last day the answer holds."""
        use = self._use(use)
        day = self._on(on_date)
        proc, source = self._resolve_processor(processor, use)
        doc = self._document(document_id)
        return self._evaluate(doc["id"], self._active_terms(doc["id"]), use, day, proc, source, self._owed_purges(doc["id"], day))

    @staticmethod
    def _names(processors: Any) -> list[str]:
        """A license's processor names (defensive against malformed stored terms)."""
        return [p for p in processors if isinstance(p, str)] if isinstance(processors, list) else []

    @classmethod
    def _common_processors(cls, terms: list[dict[str, Any]]) -> list[str]:
        """Processors listed by every license in ``terms`` (ignoring case), in the
        first license's spelling and order."""
        if not terms:
            return []
        rest = [{_fold(p) for p in cls._names(t["processors"])} for t in terms[1:]]
        out: list[str] = []
        for p in cls._names(terms[0]["processors"]):
            if all(_fold(p) in names for names in rest) and _fold(p) not in (_fold(o) for o in out):
                out.append(p)
        return out

    def _evaluate(self, document_id: str, terms: list[dict[str, Any]], use: str, day: _dt.date, processor: str | None,
                  source: str | None, owed: list[dict[str, Any]]) -> dict[str, Any]:
        base = {"document_id": document_id, "use": use, "on_date": day.isoformat(), "processor": processor, "processor_source": source}
        if not terms and not owed:
            return {**base, "allowed": True, "license_id": None, "license_ids": [], "licenses": [], "purges_owed": [], "valid_until": None,
                    "reason": "company-owned content: no license is tagged on this document and no purge is owed, so every use is allowed"}
        evaluated = []
        for t in terms:
            problems = []
            if self._expired(t["expires_on"], day):
                problems.append(f"expired (valid through {t['expires_on']})")
            if use not in t["permitted_uses"]:
                problems.append(f"does not permit {use}")
            listed = self._names(t["processors"])
            if processor is not None:
                if _fold(processor) not in (_fold(p) for p in listed):
                    problems.append(f"does not list processor {processor!r}" + (" (the default AI processor)" if source == "default" else ""))
            elif use in AI_USES:
                problems.append(f"permits {use} only by a processor it lists (" + (", ".join(listed) if listed else "no processor")
                                + "); none was named and no default AI processor is configured (set_default_processor)")
            reason = f"{self._label(t)} " + ("; ".join(problems) if problems else f"permits {use} on {day.isoformat()}"
                                             + (f" by {processor}" if processor is not None else ""))
            evaluated.append({"license_id": t["id"], "version": t["version"], "terms_hash": t["terms_hash"], "expires_on": t["expires_on"],
                              "allowed": not problems, "reason": reason})
        owed_entries = [{
            "license_id": o["license_id"], "version": o["version"], "terms_hash": o["terms_hash"], "expires_on": o["expires_on"], "allowed": False,
            "tag_id": o["tag_id"],
            "reason": (f"license {o['license_id']} ({o['licensor']}, {o['work']}, {o['edition']}, v{o['version']}) expired (valid through {o['expires_on']}) "
                       f"with a purge rule and its tag was removed after expiry; derived copies of this document still owe that purge, so no use is "
                       f"allowed until record_purge answers it"),
        } for o in owed]
        license_ids = [t["id"] for t in terms]
        denied = [e for e in evaluated if not e["allowed"]] + owed_entries
        if denied:
            return {**base, "allowed": False, "license_id": denied[0]["license_id"], "license_ids": license_ids, "licenses": evaluated,
                    "purges_owed": owed_entries, "valid_until": None, "reason": "refused: " + "; ".join(e["reason"] for e in denied)}
        governing = min(terms, key=lambda t: (t["expires_on"] is None, t["expires_on"] or "", t["id"]))
        until = governing["expires_on"]
        return {**base, "allowed": True, "license_id": governing["id"], "license_ids": license_ids, "licenses": evaluated, "purges_owed": [],
                "valid_until": until,
                "reason": f"permitted by every tagged license ({len(terms)})" + (f" for processor {processor}" if processor is not None else "")
                          + (f"; valid through {until}" if until else "; no expiry")}

    def filter_retrievable(self, document_ids: Iterable[str], use: str, *, project_id: str | None = None, on_date: Any = None,
                           processor: str | None = None) -> dict[str, Any]:
        """Retrieval gate: a document is retrievable only when it satisfies both
        access (it exists and, when ``project_id`` is given, belongs to that
        project) and content rights (``check_use``, with the same processor
        rule).  Read-only."""
        use = self._use(use)
        day = self._on(on_date)
        proc, source = self._resolve_processor(processor, use)
        if project_id is not None:
            self._project(project_id)
        if document_ids is None or isinstance(document_ids, (str, bytes, dict)):
            raise RightsError("document_ids must be a list of document ids")
        allowed: list[str] = []
        denied: list[dict[str, Any]] = []
        seen: set[str] = set()
        for raw in document_ids:
            # deduplicate on the id as it resolves (surrounding whitespace is ignored there too)
            key = raw.strip() if isinstance(raw, str) else repr(raw)
            if key in seen:
                continue
            seen.add(key)
            try:
                doc = self._document(raw)
            except RightsError as exc:
                denied.append({"document_id": raw, "reason": f"access: {exc}", "license_id": None})
                continue
            if project_id is not None and doc["project_id"] != project_id:
                denied.append({"document_id": doc["id"], "reason": f"access: document belongs to project {doc['project_id']}, not {project_id}", "license_id": None})
                continue
            result = self._evaluate(doc["id"], self._active_terms(doc["id"]), use, day, proc, source, self._owed_purges(doc["id"], day))
            if result["allowed"]:
                allowed.append(doc["id"])
            else:
                denied.append({"document_id": doc["id"], "reason": f"content rights: {result['reason']}", "license_id": result["license_id"]})
        return {"use": use, "on_date": day.isoformat(), "project_id": project_id, "processor": proc, "processor_source": source,
                "allowed": allowed, "denied": denied}

    # ---- expiry and purge ------------------------------------------------------ #

    def expired_items(self, on_date: Any = None, *, project_id: str | None = None, as_recorded: bool = False) -> list[dict[str, Any]]:
        """Documents with at least one license expired on ``on_date`` (UTC today by
        default), with each expired license, whether its purge rule requires
        derived copies to be purged and whether that purge is still outstanding.

        A document is listed for every license it is tagged with, and also for a
        license whose tag was removed only after that license had expired with a
        purge rule, until a purge answers the expiry: removing the tag does not
        discharge the purge (``tag_status`` says which).

        By default this reads the registry as it stands now - current tags,
        current terms and every purge recorded so far - and ``on_date`` moves
        only the expiry test, so a purge recorded today shows as done for an
        earlier date too.  ``as_recorded=True`` reads it as recorded at the end
        of ``on_date`` instead: the terms in force then, the tags active then
        and the purges recorded by then (``close_checks`` uses this view)."""
        day = self._on(on_date)
        if not isinstance(as_recorded, bool):
            raise RightsError(f"as_recorded must be true or false, not {as_recorded!r}")
        if project_id is not None:
            self._project(project_id)
        items: dict[str, dict[str, Any]] = {}
        for e in self._expired_entries(day.isoformat(), as_recorded=as_recorded, project_id=project_id):
            item = items.setdefault(e["document_id"], {
                "document_id": e["document_id"], "project_id": e["project_id"], "kind": e["kind"], "title": e["title"],
                "on_date": day.isoformat(), "as_recorded": as_recorded, "expired_licenses": [], "purge_required": False, "purge_outstanding": False,
            })
            item["expired_licenses"].append({k: e[k] for k in (
                "license_id", "licensor", "work", "edition", "holder", "version", "expires_on", "purge_on_expiry",
                "tag_status", "tag_id", "purged", "purge_id", "purged_on")})
            item["purge_required"] = item["purge_required"] or e["purge_on_expiry"]
            item["purge_outstanding"] = item["purge_outstanding"] or (e["purge_on_expiry"] and not e["purged"])
        return list(items.values())

    @staticmethod
    def _purge_counts(items: list[dict[str, Any]]) -> tuple[int, int]:
        """(outstanding purges, one per document and expired purge-on-expiry license;
        documents with at least one of them)."""
        pairs = [(i["document_id"], lic["license_id"]) for i in items for lic in i["expired_licenses"] if lic["purge_on_expiry"] and not lic["purged"]]
        return len(pairs), len({doc for doc, _ in pairs})

    def record_purge(self, document_id: str, license_id: str, actor: str = "owner", *, note: str = "") -> dict[str, Any]:
        """Attest that derived copies of ``document_id`` held under the expired
        ``license_id`` (indexes, embeddings, caches) were purged today (UTC).
        The document must be, or have been, tagged with the license: a removed
        tag does not discharge the purge.  Refused while the license is
        unexpired, for a document never tagged with it, and when a purge already
        answers the license's current expiry."""
        actor = self._text(actor, "actor")
        note = self._text(note, "note", required=False)
        today = self._today().isoformat()
        with self.db.transaction() as conn:
            self.db.require_write_authority()
            doc = self._document(document_id)
            lic = self.license(license_id)
            tag = conn.execute(
                "SELECT id, status FROM rights_document_tags WHERE document_id=? AND license_id=? ORDER BY status = 'active' DESC, tagged_at DESC, id DESC LIMIT 1",
                (doc["id"], lic["id"]),
            ).fetchone()
            if tag is None:
                raise RightsError(f"document {doc['id']} is not tagged (and never was) with license {lic['id']}; there is nothing to purge under it")
            if lic["expires_on"] is None or not today > lic["expires_on"]:
                until = lic["expires_on"] or "no expiry"
                raise RightsError(f"{self._label(lic)} has not expired (valid through {until}); a purge is recorded only after expiry")
            dup = conn.execute(
                "SELECT id, purged_on FROM rights_purges WHERE document_id=? AND license_id=? AND purged_on > ?", (doc["id"], lic["id"], lic["expires_on"])
            ).fetchone()
            if dup is not None:
                raise RightsError(f"a purge of document {doc['id']} under license {lic['id']} was already recorded on {dup['purged_on']} (purge {dup['id']})")
            purge_id = new_id("rprg")
            conn.execute(
                "INSERT INTO rights_purges (id, document_id, license_id, license_version, expires_on, purged_on, note, purged_by, purged_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (purge_id, doc["id"], lic["id"], lic["version"], lic["expires_on"], today, note, actor, utcnow_iso()),
            )
            self.audit.record(actor, "rights.purge_recorded", "document", doc["id"], {
                "purge_id": purge_id, "license_id": lic["id"], "license_version": lic["version"], "expires_on": lic["expires_on"],
                "purge_on_expiry": lic["purge_on_expiry"], "purged_on": today, "note": note,
                "tag_id": tag["id"], "tag_status": tag["status"],
            })
        return self.db.one("SELECT * FROM rights_purges WHERE id=?", (purge_id,))

    def purges(self, document_id: str | None = None) -> list[dict[str, Any]]:
        if document_id is None:
            return self.db.query("SELECT * FROM rights_purges ORDER BY purged_at, id")
        doc = self._document(document_id)
        return self.db.query("SELECT * FROM rights_purges WHERE document_id=? ORDER BY purged_at, id", (doc["id"],))

    # ---- approvals: none --------------------------------------------------------- #

    def manifest_for(self, operation: str, subject_id: str, *, actor_role: str) -> dict[str, Any]:
        raise RightsError(f"the rights registry has no approval-bound operations ({operation!r}); registry changes are audited record keeping")

    def apply(self, operation: str, subject_id: str, *, approval_id: str, manifest: dict[str, Any], actor: str, period_id: str | None) -> dict[str, Any]:
        raise RightsError(f"the rights registry has no approval-bound operations ({operation!r})")

    # ---- close checklist, export and state ---------------------------------------- #

    def close_checks(self, period_id: str) -> list[dict[str, Any]]:
        """Informational only: content rights post no journals, so nothing here
        blocks a close.

        Every count is judged as recorded at the end of the period's end date
        (UTC; the date of the check for a period that is not recorded) and is
        written into ``detail``, which is what the close checklist shows and
        hashes, and also into ``counts``.  Because nothing recorded after that
        date changes the as-recorded view, a period that has ended is never
        staled by later registry activity or by a UTC midnight; for a period that
        has not ended, the details move with the registry and a change between a
        close approval and its execution stales the approval."""
        period = self.db.one("SELECT start_date, end_date FROM periods WHERE id=?", (period_id,)) if isinstance(period_id, str) else None
        as_of = self._today() if period is None else self._day(period["end_date"], "period end_date")
        cutoff = as_of.isoformat()
        terms = self._terms(cutoff)
        tags = self.db.scalar(
            "SELECT COUNT(*) FROM rights_document_tags WHERE substr(tagged_at, 1, 10) <= ? AND (status = 'active' OR substr(removed_at, 1, 10) > ?)",
            (cutoff, cutoff),
        ) or 0
        expired = self.expired_items(as_of, as_recorded=True)
        expired_licenses = {lic["license_id"] for item in expired for lic in item["expired_licenses"]}
        outstanding, outstanding_documents = self._purge_counts(expired)
        when = f"as recorded at the end of {cutoff}" + (" (the UTC date of the check)" if period is None else "")
        scope = f"period {period_id!r} is not recorded; " if period is None else ""
        base = {"as_of": cutoff, "period_id": period_id}
        if period is None:
            expiring = None
            window_detail = f"{scope}no expiry window computed ({_INFO})"
        else:
            expiring = sum(1 for t in terms.values() if t["expires_on"] is not None and period["start_date"] <= t["expires_on"] <= period["end_date"])
            window_detail = (f"{expiring} license(s) whose terms {when} expire between {period['start_date']} and {period['end_date']} ({_INFO})")
        return [
            {"check": "rights.registry", "ok": True,
             "detail": f"{scope}{len(terms)} license(s) registered and {tags} active document tag(s) {when} ({_INFO})",
             "counts": {**base, "licenses": len(terms), "active_document_tags": tags}},
            {"check": "rights.expired_content", "ok": True,
             "detail": (f"{scope}{len(expired)} document(s) listed against {len(expired_licenses)} license(s) expired on {cutoff}, {when}; "
                        f"every use of them is refused ({_INFO})"),
             "counts": {**base, "documents": len(expired), "licenses": len(expired_licenses)}},
            {"check": "rights.purges_outstanding", "ok": True,
             "detail": (f"{scope}{outstanding} purge(s) outstanding (one per document and expired purge-on-expiry license) on "
                        f"{outstanding_documents} document(s), {when} ({_INFO})"),
             "counts": {**base, "purges_outstanding": outstanding, "documents_with_purges_outstanding": outstanding_documents}},
            {"check": "rights.licenses_expiring_in_period", "ok": True, "detail": window_detail,
             "counts": {**base, "licenses_expiring": expiring}},
        ]

    def audit_export(self) -> dict[str, Any]:
        """The whole registry, its history, the default-processor settings and
        today's expiry position."""
        today = self._today()
        pending = self.db.query(
            "SELECT v.license_id, v.version, v.id, v.created_by, v.created_at FROM rights_license_versions v JOIN rights_licenses l ON l.id = v.license_id "
            "WHERE v.version > l.version ORDER BY v.license_id, v.version"
        )
        return {
            "as_of": today.isoformat(),
            "uses": list(USES),
            "licenses": self.db.query("SELECT * FROM rights_licenses ORDER BY created_at, id"),
            "license_versions": [self._decode(r) for r in self.db.query("SELECT * FROM rights_license_versions ORDER BY license_id, version")],
            "unadopted_versions": self.db.query("SELECT * FROM rights_unadopted_versions ORDER BY license_id, version"),
            "pending_unadopted_versions": pending,
            "document_tags": self.db.query("SELECT * FROM rights_document_tags ORDER BY tagged_at, id"),
            "purges": self.db.query("SELECT * FROM rights_purges ORDER BY purged_at, id"),
            "default_processor_settings": self.default_processor_history(),
            "expired_items": self.expired_items(today),
        }

    def state(self, project_id: str) -> dict[str, Any]:
        """Entity-wide licenses plus the project's documents with their tags and
        the use each one permits today.  For a licensed document the AI uses in
        ``uses`` are reported for the processors every tagged license lists
        (``ai_processors``; with none in common they are refused), and
        ``default_processor_uses`` gives the AI uses for the configured default
        AI processor (what Cipher's assistant gets), None when none is set."""
        self._project(project_id)
        today = self._today()
        default = self.default_processor()["processor"]
        licenses = self.licenses()
        tag_counts = {r["license_id"]: r["n"] for r in self.db.query("SELECT license_id, COUNT(*) AS n FROM rights_document_tags WHERE status='active' GROUP BY license_id")}
        for lic in licenses:
            lic["expired"] = self._expired(lic["expires_on"], today)
            lic["tagged_documents"] = tag_counts.get(lic["id"], 0)
        documents = []
        for doc in self.db.query("SELECT id, kind, title, created_at FROM documents WHERE project_id=? ORDER BY created_at, id", (project_id,)):
            terms = self._active_terms(doc["id"])
            owed = self._owed_purges(doc["id"], today)
            common = self._common_processors(terms)

            def allowed(u: str) -> bool:
                if u in AI_USES and common:
                    return self._evaluate(doc["id"], terms, u, today, common[0], "common", owed)["allowed"]
                proc, source = (default, "default") if (u in AI_USES and default is not None) else (None, None)
                return self._evaluate(doc["id"], terms, u, today, proc, source, owed)["allowed"]

            documents.append({
                "document_id": doc["id"], "kind": doc["kind"], "title": doc["title"],
                "company_owned": not terms and not owed,
                "licenses": [{"license_id": t["id"], "version": t["version"], "licensor": t["licensor"], "work": t["work"], "edition": t["edition"],
                              "expires_on": t["expires_on"], "expired": self._expired(t["expires_on"], today)} for t in terms],
                "purges_owed": [o["license_id"] for o in owed],
                "ai_processors": None if not terms else common,
                "uses": {u: allowed(u) for u in USES},
                "default_processor_uses": None if default is None else
                {u: self._evaluate(doc["id"], terms, u, today, default, "default", owed)["allowed"] for u in AI_USES},
            })
        expired = self.expired_items(today, project_id=project_id)
        outstanding, outstanding_documents = self._purge_counts(expired)
        return {
            "as_of": today.isoformat(),
            "uses": list(USES),
            "default_ai_processor": default,
            "licenses": licenses,
            "documents": documents,
            "expired_items": expired,
            "summary": {
                "licenses": len(licenses),
                "licenses_expired": sum(1 for lic in licenses if lic["expired"]),
                "documents": len(documents),
                "licensed_documents": sum(1 for d in documents if d["licenses"]),
                "company_owned_documents": sum(1 for d in documents if d["company_owned"]),
                "expired_documents": len(expired),
                "purges_outstanding": outstanding,
                "documents_with_purges_outstanding": outstanding_documents,
            },
        }

"""Content-rights registry: versioned licenses, document tags, use checks, the
default AI processor, expiry and purge, as-recorded close counts and schema
upgrades.

Every licensor, work and edition here is fictional, and section numbers use
original placeholder codes ("XX 10 00"), never a real classification.
"""
import datetime as dt
import json
import os
import shutil
import sqlite3
import tempfile
import unittest
from unittest import mock

from apps.cipher.core import db as db_module
from apps.cipher.core.approvals import StaleApprovalError
from apps.cipher.core.db import WriteAuthorityError
from apps.cipher.domain import rights as rights_module
from apps.cipher.domain.rights import (
    AI_USES, GUARDS_SCHEMA_NAME, HARDENING_SCHEMA_NAME, PLUGIN_NAME, SCHEMA_NAME, USES, Plugin, RightsError,
)
from apps.cipher.ricky_sdk import RickySDK
from apps.cipher.service import Cipher

VERSION_INSERT = ("INSERT INTO rights_license_versions (id, license_id, version, permitted_uses, processors, expires_on, purge_on_expiry, note, terms_hash, created_by, created_at) "
                  "VALUES (?, ?, ?, ?, ?, NULL, 0, '', 'h', 'raw', 't')")
HEADER_INSERT = ("INSERT INTO rights_licenses (id, licensor, work, edition, holder, version, created_by, created_at, updated_at) "
                 "VALUES (?, ?, ?, ?, ?, 1, 'raw', 't', 't')")
REGISTRATION_INSERT = ("{verb} INTO rights_license_registrations (license_id, licensor, work, edition, holder, version_id, permitted_uses, processors, "
                       "expires_on, purge_on_expiry, note, terms_hash, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?, '[]', '[]', NULL, 0, '', 'h', 'raw', 't')")

HOLDER = "S&A Solutions LLC (synthetic)"
SPEC = {"licensor": "Halcyon Specification Society", "work": "Halcyon Guide Specifications", "edition": "2026 edition"}
FORMS = {"licensor": "Quarry Lane Forms Cooperative", "work": "Quarry Lane Subcontract Form Set", "edition": "Series B, 4th edition"}
HANDBOOK = {"licensor": "Bramblegate Technical Press", "work": "Bramblegate Pump Station Handbook", "edition": "3rd edition"}
LOCAL = "cipher-local-index"
INFO = "informational: content rights post no journals and never block a close"


def utc_today() -> dt.date:
    return dt.datetime.now(dt.timezone.utc).date()


def days(n: int) -> str:
    return (utc_today() + dt.timedelta(days=n)).isoformat()


def ts(n: int) -> str:
    """Noon UTC ``n`` days from today, in the registry's timestamp format."""
    return f"{days(n)}T12:00:00Z"


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def recorded_at(n: int):
    """Write the registry's own timestamps as noon UTC ``n`` days from today."""
    return mock.patch.object(rights_module, "utcnow_iso", return_value=ts(n))


def today_is(n: int):
    """Make the registry's UTC "today" ``n`` days from the real one."""
    return mock.patch.object(Plugin, "_today", return_value=utc_today() + dt.timedelta(days=n))


class Scene:
    """Two projects, one open period around today, a licensed specification and a company memo."""

    def __init__(self, path: str = ":memory:"):
        self.c = Cipher(path)
        self.p = self.c.plugin(PLUGIN_NAME)
        customer = self.c.add_party(kind="customer", name="Synthetic Owner Agency")
        self.project = self.c.create_project(name="Synthetic lift station", entity="S&A Solutions LLC (synthetic)", budget="250000", customer_id=customer["id"])
        self.other_project = self.c.create_project(name="Synthetic cofferdam", entity="S&A Solutions LLC (synthetic)", budget="90000", customer_id=customer["id"])
        self.period = self.c.open_period("P1", "Current period", days(-10), days(20))
        self.spec_doc = self.doc("Section XX 10 00 - pumping equipment (licensed guide text)")
        self.memo = self.doc("Company dewatering design memo", kind="memo")

    def doc(self, title: str, *, kind: str = "specification", project: dict | None = None) -> dict:
        d = self.c.evidence.register_document(project_id=(project or self.project)["id"], kind=kind, title=title, actor="owner")
        self.c.evidence.add_revision(document_id=d["id"], content=title.encode(), note="synthetic", actor="owner")
        return d

    def license(self, ident: dict, uses, *, processors=(LOCAL,), expires_on="2026-12-31", purge=False, holder=HOLDER) -> dict:
        return self.p.register_license(ident["licensor"], ident["work"], ident["edition"], holder, list(uses), list(processors), expires_on, purge, actor="owner")


class RightsTestCase(unittest.TestCase):
    def setUp(self):
        self.s = Scene()
        self.c = self.s.c
        self.p = self.s.p
        self.doc = self.s.spec_doc["id"]
        self.memo = self.s.memo["id"]

    def assertBooksIntact(self, c=None):
        c = c or self.c
        self.assertTrue(c.audit.verify_chain()["ok"])
        tb = c.ledger.trial_balance()
        self.assertTrue(tb["balanced"])
        self.assertEqual(c.db.scalar("SELECT COUNT(*) FROM journals"), 0)  # the registry never posts

    def rights_actions(self, entity_type: str, entity_id: str) -> list[str]:
        return [e["action"] for e in self.c.audit.entries(entity_type=entity_type, entity_id=entity_id) if e["action"].startswith("rights.")]

    def all_rights_actions(self) -> list[str]:
        return [e["action"] for e in self.c.audit.entries() if e["action"].startswith("rights.")]

    def payload(self, entity_type: str, entity_id: str, action: str) -> dict:
        return json.loads([e for e in self.c.audit.entries(entity_type=entity_type, entity_id=entity_id) if e["action"] == action][-1]["payload_json"])

    def assertRawRefused(self, sql: str, params: tuple, reason: str):
        with self.assertRaisesRegex(sqlite3.IntegrityError, reason):
            with self.c.db.transaction() as conn:
                conn.execute(sql, params)
        self.assertFalse(self.c.db.conn.in_transaction)

    def counts(self, period_id: str) -> dict:
        return {c["check"]: c["counts"] for c in self.p.close_checks(period_id)}

    def details(self, period_id: str) -> dict:
        return {c["check"]: c["detail"] for c in self.p.close_checks(period_id)}


# --------------------------------------------------------------------------- #
# Licenses and schema                                                          #
# --------------------------------------------------------------------------- #

class LicenseRegistryTests(RightsTestCase):
    def test_plugin_registered_and_schema_applied(self):
        status = self.c.db.schema_status()
        for name in (SCHEMA_NAME, GUARDS_SCHEMA_NAME, HARDENING_SCHEMA_NAME):
            with self.subTest(entry=name):
                entry = next(v for v in status["versions"] if v["name"] == name)
                self.assertTrue(entry["applied"])
                self.assertTrue(entry["checksum_matches"])
        names = [v["name"] for v in status["versions"]]
        self.assertLess(names.index(SCHEMA_NAME), names.index(GUARDS_SCHEMA_NAME))  # each follow-on entry sits after the objects it changes
        self.assertLess(names.index(GUARDS_SCHEMA_NAME), names.index(HARDENING_SCHEMA_NAME))
        self.assertEqual(status["pending"], [])
        triggers = {r["name"] for r in self.c.db.query("SELECT name FROM sqlite_master WHERE type='trigger' AND name LIKE 'rights_%'")}
        self.assertTrue({"rights_license_versions_guard", "rights_license_versions_no_update", "rights_license_versions_no_delete",
                         "rights_licenses_insert_guard", "rights_licenses_versioned_update", "rights_licenses_identity_immutable",
                         "rights_document_tags_removal_guard", "rights_document_tags_no_replace", "rights_purges_guard_v2",
                         "rights_license_registrations_insert", "rights_unadopted_versions_guard", "rights_ai_processor_settings_guard"} <= triggers)
        # superseded triggers are gone (merged so their refusals come in a fixed order)
        self.assertFalse({"rights_purges_guard", "rights_licenses_born_v1", "rights_licenses_no_replace", "rights_license_versions_no_replace",
                          "rights_license_versions_terms_shape", "rights_document_tags_purge_before_untag"} & triggers)
        # no deferred foreign key is left in the rights schema
        sql = " ".join(r["sql"] for r in self.c.db.query("SELECT sql FROM sqlite_master WHERE name LIKE 'rights_%' AND sql IS NOT NULL"))
        self.assertNotIn("DEFERRABLE", sql.upper())
        fks = self.c.db.query("SELECT * FROM pragma_foreign_key_list('rights_license_versions')")
        self.assertEqual([(f["table"], f["from"], f["to"]) for f in fks], [("rights_licenses", "license_id", "id")])
        self.assertIsInstance(self.p, Plugin)
        self.assertEqual(USES, ("internal_reference", "project_use", "ai_retrieval", "ai_embedding", "distribution"))
        self.assertEqual(AI_USES, ("ai_retrieval", "ai_embedding"))
        objects = {(r["type"], r["name"]) for r in self.c.db.query("SELECT type, name FROM sqlite_master WHERE name LIKE 'rights_%'")}
        self.assertTrue({("table", "rights_licenses"), ("table", "rights_license_versions"), ("table", "rights_document_tags"), ("table", "rights_purges"),
                         ("table", "rights_unadopted_versions"), ("table", "rights_ai_processor_settings"),
                         ("view", "rights_license_registrations")} <= objects)
        self.assertNotIn(("table", "rights_license_versions_hold"), objects)

    def test_register_license_is_version_one_normalised_and_audited(self):
        lic = self.s.license(SPEC, ["project_use", "ai_retrieval", " internal_reference "], processors=["local-model-host", LOCAL], purge=True)
        self.assertTrue(lic["id"].startswith("lic_"))
        self.assertEqual((lic["licensor"], lic["work"], lic["edition"], lic["holder"]), (SPEC["licensor"], SPEC["work"], SPEC["edition"], HOLDER))
        self.assertEqual(lic["version"], 1)
        self.assertEqual(lic["permitted_uses"], ["ai_retrieval", "internal_reference", "project_use"])
        self.assertEqual(lic["processors"], [LOCAL, "local-model-host"])
        self.assertEqual(lic["expires_on"], "2026-12-31")
        self.assertIs(lic["purge_on_expiry"], True)
        self.assertEqual(len(lic["terms_hash"]), 64)
        history = self.p.license_history(lic["id"])
        self.assertEqual([(h["version"], h["status"]) for h in history], [(1, "current")])
        self.assertEqual(history[0]["terms_hash"], lic["terms_hash"])
        self.assertEqual(self.p.licenses()[0]["id"], lic["id"])
        self.assertEqual(self.p.get_license(lic["id"])["id"], lic["id"])
        self.assertEqual(self.rights_actions("rights_license", lic["id"]), ["rights.license_registered"])
        payload = self.payload("rights_license", lic["id"], "rights.license_registered")
        self.assertEqual(payload["terms_hash"], lic["terms_hash"])
        self.assertEqual(payload["permitted_uses"], ["ai_retrieval", "internal_reference", "project_use"])
        self.assertBooksIntact()

    def test_register_accepts_date_objects_and_no_expiry(self):
        a = self.s.license(SPEC, ["project_use"], expires_on=dt.date(2027, 3, 31))
        self.assertEqual(a["expires_on"], "2027-03-31")
        b = self.s.license(FORMS, [], processors=[], expires_on=None)
        self.assertIsNone(b["expires_on"])
        self.assertEqual((b["permitted_uses"], b["processors"], b["purge_on_expiry"]), ([], [], False))

    def test_register_rejects_invalid_input(self):
        good = dict(licensor=SPEC["licensor"], work=SPEC["work"], edition=SPEC["edition"], holder=HOLDER,
                    permitted_uses=["project_use"], processors=[LOCAL], expires_on="2026-12-31", purge_on_expiry=False)
        bad_cases = [
            {"permitted_uses": ["ai_training"]},            # unknown use name
            {"permitted_uses": ["Project_Use"]},            # use names are exact
            {"permitted_uses": "ai_retrieval"},             # a bare string is not a list
            {"permitted_uses": None},
            {"permitted_uses": {"project_use": True}},
            {"permitted_uses": [1]},
            {"permitted_uses": ["project_use", "project_use"]},
            {"processors": LOCAL},
            {"processors": None},
            {"processors": [""]},
            {"processors": [42]},
            {"processors": ["Host-A", "host-a"]},
            {"processors": ["Émile-Host", "émile-host"]},  # processor names fold Unicode case too
            {"expires_on": "2026-02-30"},
            {"expires_on": "2026/12/31"},
            {"expires_on": "20261231"},
            {"expires_on": "2026-12-31T00:00:00"},
            {"expires_on": dt.datetime(2026, 12, 31, tzinfo=dt.timezone.utc)},
            {"expires_on": 20261231},
            {"purge_on_expiry": 1},
            {"purge_on_expiry": "yes"},
            {"purge_on_expiry": None},
            {"licensor": ""},
            {"licensor": "   "},
            {"work": None},
            {"edition": ""},
            {"holder": 5},
        ]
        for case in bad_cases:
            with self.subTest(case=case):
                with self.assertRaises(RightsError):
                    self.p.register_license(**{**good, **case}, actor="owner")
        with self.assertRaises(RightsError):
            self.p.register_license(**good, actor="")
        self.assertEqual(self.p.licenses(), [])
        self.assertEqual(self.all_rights_actions(), [])

    def test_duplicate_license_rejected_ignoring_case(self):
        lic = self.s.license(SPEC, ["project_use"])
        with self.assertRaisesRegex(RightsError, "already registered"):
            self.p.register_license(SPEC["licensor"].upper(), f"  {SPEC['work'].lower()} ", SPEC["edition"], HOLDER.lower(), ["ai_retrieval"], [], None, False, actor="owner")
        # identity folds Unicode case (not only ASCII letters) and treats runs of whitespace as one space
        unicode_lic = self.p.register_license("Émile Guild of Specifiers", "Straße Drainage Notes", "1st edition", HOLDER, ["project_use"], [], None, False, actor="owner")
        for variant in (("émile guild of specifiers", "STRASSE DRAINAGE NOTES", "1st  edition"),
                        ("ÉMILE GUILD OF SPECIFIERS", "straße drainage notes", "1ST EDITION")):
            with self.subTest(variant=variant):
                with self.assertRaisesRegex(RightsError, f"already registered as license {unicode_lic['id']}"):
                    self.p.register_license(*variant, HOLDER, ["project_use"], [], None, False, actor="owner")
        self.assertEqual(len(self.p.licenses()), 2)
        # the database agrees for ASCII case variants (its own guard folds ASCII letters only, as SQLite's lower() does)
        self.assertRawRefused(REGISTRATION_INSERT.format(verb="INSERT"),
                              ("lic_raw", SPEC["licensor"].lower(), SPEC["work"].upper(), SPEC["edition"], HOLDER, "licv_raw"), "already registered")
        self.assertIsNone(self.c.db.one("SELECT id FROM rights_license_versions WHERE id='licv_raw'"))  # the statement left nothing behind
        # a different edition or a different holder is a different license
        other_edition = self.p.register_license(SPEC["licensor"], SPEC["work"], "2027 edition", HOLDER, ["project_use"], [], None, False, actor="owner")
        other_holder = self.s.license(SPEC, ["project_use"], holder="Synthetic Joint Venture Partner")
        self.assertEqual(len({lic["id"], other_edition["id"], other_holder["id"]}), 3)
        self.assertEqual(len(self.p.licenses()), 4)
        self.assertEqual(self.all_rights_actions().count("rights.license_registered"), 4)

    def test_update_license_bumps_version_and_keeps_history(self):
        lic = self.s.license(SPEC, ["project_use", "ai_retrieval"], purge=False)
        v2 = self.p.update_license(lic["id"], permitted_uses=["project_use", "ai_retrieval", "ai_embedding"], note="embedding rights added by written amendment", actor="owner")
        self.assertEqual(v2["version"], 2)
        self.assertEqual(v2["permitted_uses"], ["ai_embedding", "ai_retrieval", "project_use"])
        self.assertEqual((v2["processors"], v2["expires_on"], v2["purge_on_expiry"]), ([LOCAL], "2026-12-31", False))  # untouched terms carry over
        self.assertNotEqual(v2["terms_hash"], lic["terms_hash"])
        self.assertEqual(v2["note"], "embedding rights added by written amendment")
        v3 = self.p.update_license(lic["id"], expires_on=None, purge_on_expiry=True, expected_version=2, actor="owner")
        self.assertEqual((v3["version"], v3["expires_on"], v3["purge_on_expiry"]), (3, None, True))
        history = self.p.license_history(lic["id"])
        self.assertEqual([(h["version"], h["status"]) for h in history], [(1, "superseded"), (2, "superseded"), (3, "current")])
        self.assertEqual(history[0]["permitted_uses"], ["ai_retrieval", "project_use"])  # v1 terms are untouched
        self.assertEqual(history[0]["expires_on"], "2026-12-31")
        self.assertEqual(history[0]["terms_hash"], lic["terms_hash"])
        self.assertEqual(self.rights_actions("rights_license", lic["id"]), ["rights.license_registered", "rights.license_updated", "rights.license_updated"])
        last = self.payload("rights_license", lic["id"], "rights.license_updated")
        self.assertEqual(last["changes"], {"expires_on": {"from": "2026-12-31", "to": None}, "purge_on_expiry": {"from": False, "to": True}})
        self.assertEqual((last["version"], last["previous_version"], last["terms_hash"]), (3, 2, v3["terms_hash"]))
        # refusals leave the license where it was
        with self.assertRaisesRegex(RightsError, "nothing to update"):
            self.p.update_license(lic["id"], permitted_uses=["project_use", "ai_embedding", "ai_retrieval"], actor="owner")
        with self.assertRaisesRegex(RightsError, "version 3, not 2"):
            self.p.update_license(lic["id"], expires_on="2027-01-31", expected_version=2, actor="owner")
        for bad in ({"permitted_uses": ["ai_training"]}, {"expires_on": "2027-02-29"}, {"purge_on_expiry": 0},
                    {"expected_version": "3", "expires_on": "2027-01-31"}, {"processors": ["Émile-Host", "émile-host"]}):
            with self.subTest(bad=bad):
                with self.assertRaises(RightsError):
                    self.p.update_license(lic["id"], actor="owner", **bad)
        with self.assertRaises(RightsError):
            self.p.update_license("lic_missing", expires_on="2027-01-31", actor="owner")
        self.assertEqual(self.p.license(lic["id"])["version"], 3)
        self.assertEqual(len(self.p.license_history(lic["id"])), 3)
        self.assertBooksIntact()

    def test_registry_rows_are_immutable_in_the_database(self):
        lic = self.s.license(SPEC, ["project_use"])
        db = self.c.db
        refusals = [
            ("UPDATE rights_license_versions SET permitted_uses='[\"distribution\"]' WHERE license_id=?", (lic["id"],), "immutable"),
            ("DELETE FROM rights_license_versions WHERE license_id=?", (lic["id"],), "immutable"),
            ("DELETE FROM rights_licenses WHERE id=?", (lic["id"],), "never deleted"),
            ("UPDATE rights_licenses SET licensor='Someone Else' WHERE id=?", (lic["id"],), "identity|next version"),
            ("UPDATE rights_licenses SET version=3 WHERE id=?", (lic["id"],), "next version"),
            ("UPDATE rights_licenses SET version=2 WHERE id=?", (lic["id"],), "recorded before"),
            ("UPDATE rights_licenses SET updated_at='t' WHERE id=?", (lic["id"],), "next version"),
            ("INSERT INTO rights_license_versions (id, license_id, version, permitted_uses, processors, expires_on, purge_on_expiry, note, terms_hash, created_by, created_at) "
             "VALUES ('licv_x', ?, 3, '[]', '[]', NULL, 0, '', 'h', 'raw', 't')", (lic["id"],), "contiguous"),
            ("INSERT INTO rights_license_versions (id, license_id, version, permitted_uses, processors, expires_on, purge_on_expiry, note, terms_hash, created_by, created_at) "
             "VALUES ('licv_x', ?, 2, '[\"ai_training\"]', '[]', NULL, 0, '', 'h', 'raw', 't')", (lic["id"],), "known use names"),
            ("INSERT INTO rights_license_versions (id, license_id, version, permitted_uses, processors, expires_on, purge_on_expiry, note, terms_hash, created_by, created_at) "
             "VALUES ('licv_x', ?, 2, '[]', '[]', '2026-02-30', 0, '', 'h', 'raw', 't')", (lic["id"],), "YYYY-MM-DD"),
            ("INSERT INTO rights_license_versions (id, license_id, version, permitted_uses, processors, expires_on, purge_on_expiry, note, terms_hash, created_by, created_at) "
             "VALUES ('licv_x', ?, 2, 'project_use', '[]', NULL, 0, '', 'h', 'raw', 't')", (lic["id"],), "JSON array"),
            ("UPDATE rights_license_registrations SET licensor='Someone Else' WHERE license_id=?", (lic["id"],), "view"),
        ]
        for sql, params, reason in refusals:
            with self.subTest(sql=sql[:60]):
                with self.assertRaisesRegex(sqlite3.Error, reason):
                    with db.transaction() as conn:
                        conn.execute(sql, params)
        # a license header cannot be born without its version-1 terms
        self.assertRawRefused(HEADER_INSERT, ("lic_raw", "L", "W", "E", "H"), "version-1 terms")
        # a terms row for a license that does not exist fails its immediate foreign key at once ...
        self.assertRawRefused(VERSION_INSERT, ("licv_orphan", "lic_orphan", 1, "[]", "[]"), "FOREIGN KEY")
        # ... including the two-statement registration the earlier schema deferred to COMMIT
        with self.assertRaisesRegex(sqlite3.IntegrityError, "FOREIGN KEY"):
            with db.transaction() as conn:
                conn.execute(VERSION_INSERT, ("licv_two", "lic_two", 1, "[]", "[]"))
                conn.execute(HEADER_INSERT, ("lic_two", "L2", "W2", "E2", "H2"))
        # no transaction is left open, so later writes commit normally
        self.assertFalse(db.conn.in_transaction)
        self.assertFalse(db.in_transaction)
        supplier = self.c.add_party(kind="supplier", name="Synthetic Supplier R")
        self.assertEqual(self.c.party(supplier["id"])["name"], "Synthetic Supplier R")
        forms = self.s.license(FORMS, ["project_use"])
        self.assertEqual(self.p.license(forms["id"])["version"], 1)
        self.assertIsNone(db.one("SELECT id FROM rights_license_versions WHERE id IN ('licv_orphan', 'licv_two')"))
        self.assertIsNone(db.one("SELECT id FROM rights_licenses WHERE id IN ('lic_raw', 'lic_two')"))
        self.assertEqual(self.p.license(lic["id"])["permitted_uses"], ["project_use"])
        self.assertEqual(self.p.license(lic["id"])["version"], 1)
        self.assertEqual(db.scalar("SELECT COUNT(*) FROM rights_license_versions"), 2)
        # a raw registration through the view is the one statement that can create a license
        with db.transaction() as conn:
            conn.execute(REGISTRATION_INSERT.format(verb="INSERT"), ("lic_view", "Raw Licensor", "Raw Work", "Raw edition", HOLDER, "licv_view"))
        self.assertEqual((self.p.license("lic_view")["version"], self.p.license("lic_view")["permitted_uses"]), (1, []))
        self.assertBooksIntact()

    def test_insert_or_replace_cannot_rewrite_licenses_or_versions(self):
        lic = self.s.license(SPEC, ["project_use", "ai_retrieval"])
        v2 = self.p.update_license(lic["id"], permitted_uses=["project_use", "ai_retrieval", "ai_embedding"], actor="owner")
        self.p.tag_document(self.doc, lic["id"], "owner")
        before_audit = self.all_rights_actions()
        v1_id = self.p.license_history(lic["id"])[0]["id"]
        header = ("{verb} INTO rights_licenses (id, licensor, work, edition, holder, version, created_by, created_at, updated_at) "
                  "VALUES (?, 'Other Licensor', 'Other Work', 'Other edition', 'H2', 1, 'raw', 't', 't')")
        for verb in ("INSERT OR REPLACE", "REPLACE", "INSERT OR IGNORE"):
            with self.subTest(verb=verb, table="rights_licenses"):
                self.assertRawRefused(header.format(verb=verb), (lic["id"],), "never replaced")
            # a case-variant identity under a new id collides with the identity index, which REPLACE would resolve by deleting the original
            with self.subTest(verb=verb, table="rights_license_registrations"):
                self.assertRawRefused(REGISTRATION_INSERT.format(verb=verb),
                                      ("lic_twin", SPEC["licensor"].upper(), SPEC["work"].lower(), SPEC["edition"], HOLDER, "licv_twin"), "already registered")
                self.assertRawRefused(REGISTRATION_INSERT.format(verb=verb), (lic["id"], "Other", "Other", "Other", "H2", "licv_twin"), "never replaced")
        self.assertIsNone(self.c.db.one("SELECT id FROM rights_license_versions WHERE id='licv_twin'"))
        # a version row reusing the version-1 id (with every use) cannot erase the history row
        all_uses = json.dumps(list(USES))
        for verb in ("INSERT OR REPLACE", "REPLACE"):
            with self.subTest(verb=verb, table="rights_license_versions"):
                self.assertRawRefused(VERSION_INSERT.replace("INSERT", verb, 1), (v1_id, lic["id"], 3, all_uses, "[]"), "never replaced")
                self.assertRawRefused(VERSION_INSERT.replace("INSERT", verb, 1), ("licv_new", lic["id"], 2, all_uses, "[]"), "never replaced")
        current = self.p.license(lic["id"])
        self.assertEqual((current["licensor"], current["work"], current["holder"], current["version"]), (SPEC["licensor"], SPEC["work"], HOLDER, 2))
        self.assertEqual(current["terms_hash"], v2["terms_hash"])
        self.assertEqual([h["version"] for h in self.p.license_history(lic["id"])], [1, 2])
        self.assertEqual(self.p.license_history(lic["id"])[0]["id"], v1_id)
        self.assertFalse(self.p.check_use(self.doc, "distribution", "2026-11-01")["allowed"])
        self.assertTrue(self.p.check_use(self.doc, "ai_embedding", "2026-11-01", processor=LOCAL)["allowed"])
        self.assertEqual(self.all_rights_actions(), before_audit)
        self.assertBooksIntact()

    def test_malformed_terms_rows_are_refused_by_the_database(self):
        lic = self.s.license(SPEC, ["project_use"])
        cases = [
            ('["project_use"]', "[1, null]", "processor name strings"),
            ('["project_use"]', '["host-a", ""]', "processor name strings"),
            ('["project_use"]', '[" host-a"]', "processor name strings"),
            ('["project_use"]', '["Host-A", "host-a"]', "processor twice"),
            ('["project_use", "project_use"]', "[]", "use twice"),
            ('["project_use"]', '{"host": "a"}', "JSON array"),
            ('["ai_training"]', "[]", "known use names"),
        ]
        for uses, procs, reason in cases:
            with self.subTest(processors=procs, uses=uses):
                self.assertRawRefused(VERSION_INSERT, ("licv_x", lic["id"], 2, uses, procs), reason)
        self.assertEqual([h["version"] for h in self.p.license_history(lic["id"])], [1])

    def test_unadopted_version_row_blocks_updates_until_superseded(self):
        with recorded_at(-3):
            lic = self.s.license(SPEC, ["project_use"], expires_on="2099-12-31")
            self.p.tag_document(self.doc, lic["id"], "owner")
        # a raw terms row the license never moved to (the database accepts the next version on its own)
        with self.c.db.transaction() as conn:
            conn.execute("INSERT INTO rights_license_versions (" + rights_module._VERSION_COLUMNS + ") VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                         ("licv_planted", lic["id"], 2, json.dumps(list(USES)), "[]", days(-2), 0, "", "h", "raw", ts(-2)))
        with self.assertRaisesRegex(RightsError, "never moved to.*supersede_unadopted_version"):
            self.p.update_license(lic["id"], expires_on="2098-06-30", actor="owner")
        self.assertEqual(self.p.license(lic["id"])["version"], 1)
        self.assertFalse(self.p.check_use(self.doc, "distribution", "2026-11-01")["allowed"])  # the planted terms never take effect
        self.assertEqual([h["status"] for h in self.p.license_history(lic["id"])], ["current", "pending_unadopted"])
        self.assertEqual([(r["license_id"], r["version"]) for r in self.p.audit_export()["pending_unadopted_versions"]], [(lic["id"], 2)])
        self.assertRawRefused(VERSION_INSERT, ("licv_stacked", lic["id"], 3, "[]", "[]"), "follows the license's current version")
        other = self.s.license(FORMS, ["project_use"])
        with self.assertRaisesRegex(RightsError, "no unadopted terms version"):
            self.p.supersede_unadopted_version(other["id"], "owner")
        with self.assertRaises(RightsError):
            self.p.supersede_unadopted_version(lic["id"], "")
        # the repair path: pass over the planted row to a version that restores the terms in force
        repaired = self.p.supersede_unadopted_version(lic["id"], "owner", note="planted row found in review")
        self.assertEqual((repaired["version"], repaired["permitted_uses"], repaired["expires_on"]), (3, ["project_use"], "2099-12-31"))
        self.assertEqual(repaired["terms_hash"], lic["terms_hash"])
        self.assertEqual([(h["version"], h["status"]) for h in self.p.license_history(lic["id"])], [(1, "superseded"), (2, "unadopted"), (3, "current")])
        self.assertFalse(self.p.check_use(self.doc, "distribution", "2026-11-01")["allowed"])
        # as-recorded views never apply the planted terms either (they would have expired the document from days(-2))
        self.assertEqual(self.p.expired_items(days(-1), as_recorded=True), [])
        self.assertEqual(self.p.expired_items(days(-1)), [])
        self.assertEqual(self.rights_actions("rights_license", lic["id"]), ["rights.license_registered", "rights.unadopted_version_superseded"])
        payload = self.payload("rights_license", lic["id"], "rights.unadopted_version_superseded")
        self.assertEqual((payload["unadopted_version"], payload["unadopted_version_id"], payload["restored_from_version"], payload["version"]),
                         (2, "licv_planted", 1, 3))
        self.assertEqual(payload["unadopted_terms"]["permitted_uses"], list(USES))  # recorded as the raw row has them
        export = self.p.audit_export()
        self.assertEqual(export["pending_unadopted_versions"], [])
        self.assertEqual([(r["license_id"], r["version"], r["superseded_by"]) for r in export["unadopted_versions"]], [(lic["id"], 2, 3)])
        # the record is guarded too
        for sql, params, reason in (
            ("UPDATE rights_unadopted_versions SET superseded_by=4 WHERE license_id=?", (lic["id"],), "immutable"),
            ("DELETE FROM rights_unadopted_versions WHERE license_id=?", (lic["id"],), "immutable"),
            ("INSERT OR REPLACE INTO rights_unadopted_versions (license_id, version, superseded_by, note, recorded_by, recorded_at) VALUES (?, 2, 3, '', 'raw', 't')",
             (lic["id"],), "never replaced"),
            ("INSERT INTO rights_unadopted_versions (license_id, version, superseded_by, note, recorded_by, recorded_at) VALUES (?, 1, 2, '', 'raw', 't')",
             (lic["id"],), "superseded by the next version"),
        ):
            with self.subTest(sql=sql[:50]):
                self.assertRawRefused(sql, params, reason)
        with self.assertRaisesRegex(RightsError, "no unadopted terms version"):
            self.p.supersede_unadopted_version(lic["id"], "owner")
        v4 = self.p.update_license(lic["id"], expires_on="2098-06-30", actor="owner")  # updates work again
        self.assertEqual(v4["version"], 4)
        self.assertBooksIntact()


# --------------------------------------------------------------------------- #
# Document tags                                                                #
# --------------------------------------------------------------------------- #

class DocumentTagTests(RightsTestCase):
    def test_untagged_company_content_allows_every_use(self):
        for use in USES:
            with self.subTest(use=use):
                r = self.p.check_use(self.memo, use)
                self.assertTrue(r["allowed"])
                self.assertIsNone(r["license_id"])
                self.assertEqual(r["license_ids"], [])
                self.assertIn("company-owned", r["reason"])
                self.assertEqual(r["on_date"], utc_today().isoformat())
        far = self.p.check_use(self.memo, "distribution", "2099-12-31", processor="any-hosted-model")
        self.assertTrue(far["allowed"])

    def test_tag_and_untag_keep_history(self):
        lic = self.s.license(SPEC, ["internal_reference", "project_use"])
        tag = self.p.tag_document(self.doc, lic["id"], "owner")
        self.assertEqual((tag["status"], tag["license_version"], tag["document_id"], tag["license_id"]), ("active", 1, self.doc, lic["id"]))
        self.assertFalse(self.p.check_use(self.doc, "distribution", "2026-11-01")["allowed"])
        with self.assertRaisesRegex(RightsError, "already tagged"):
            self.p.tag_document(self.doc, lic["id"], "owner")
        removed = self.p.untag_document(self.doc, lic["id"], "owner", reason="content replaced by a company-authored section")
        self.assertEqual((removed["status"], removed["removed_by"], removed["removal_reason"]), ("removed", "owner", "content replaced by a company-authored section"))
        self.assertGreaterEqual(removed["removed_at"], removed["tagged_at"])
        self.assertTrue(self.p.check_use(self.doc, "distribution", "2026-11-01")["allowed"])  # company-owned again
        with self.assertRaisesRegex(RightsError, "not tagged"):
            self.p.untag(self.doc, lic["id"], "owner")
        again = self.p.tag_document(self.doc, lic["id"], "owner")
        self.assertNotEqual(again["id"], tag["id"])
        self.assertEqual([t["id"] for t in self.p.document_tags(self.doc)], [again["id"]])
        self.assertEqual([t["status"] for t in self.p.document_tags(self.doc, include_removed=True)], ["removed", "active"])
        self.assertEqual([d["document_id"] for d in self.p.tagged_documents(lic["id"])], [self.doc])
        self.assertEqual(self.rights_actions("document", self.doc), ["rights.document_tagged", "rights.document_untagged", "rights.document_tagged"])
        untag_payload = self.payload("document", self.doc, "rights.document_untagged")
        self.assertEqual((untag_payload["remaining_tags"], untag_payload["purges_owed"], untag_payload["company_owned"]), (0, [], True))
        self.assertBooksIntact()

    def test_tag_records_the_license_version_but_checks_use_current_terms(self):
        lic = self.s.license(SPEC, ["project_use"])
        self.p.update_license(lic["id"], permitted_uses=["project_use", "ai_retrieval"], actor="owner")
        tag = self.p.tag_document(self.doc, lic["id"], "owner")
        self.assertEqual(tag["license_version"], 2)
        self.assertTrue(self.p.check_use(self.doc, "ai_retrieval", "2026-11-01", processor=LOCAL)["allowed"])
        self.p.update_license(lic["id"], permitted_uses=["project_use"], note="AI rights withdrawn by the licensor", actor="owner")
        r = self.p.check_use(self.doc, "ai_retrieval", "2026-11-01", processor=LOCAL)
        self.assertFalse(r["allowed"])
        self.assertEqual(r["licenses"][0]["version"], 3)
        # on_date moves only the expiry test: the answer uses today's tags and terms, even for an earlier date
        self.assertFalse(self.p.check_use(self.doc, "ai_retrieval", "2020-01-01", processor=LOCAL)["allowed"])

    def test_tag_rejects_unknown_records_and_bad_input(self):
        lic = self.s.license(SPEC, ["project_use"])
        for args in (("doc_missing", lic["id"]), (self.doc, "lic_missing"), ("", lic["id"]), (None, lic["id"]), (self.doc, None)):
            with self.subTest(args=args):
                with self.assertRaises(RightsError):
                    self.p.tag_document(*args, "owner")
        with self.assertRaises(RightsError):
            self.p.tag_document(self.doc, lic["id"], "")
        with self.assertRaises(RightsError):
            self.p.untag_document("doc_missing", lic["id"], "owner")
        self.assertEqual(self.p.document_tags(self.doc, include_removed=True), [])

    def test_tag_rows_are_guarded_in_the_database(self):
        lic = self.s.license(SPEC, ["project_use"])
        other = self.s.license(FORMS, ["project_use"])
        tag = self.p.tag_document(self.doc, lic["id"], "owner")
        db = self.c.db
        refusals = [
            ("DELETE FROM rights_document_tags WHERE id=?", (tag["id"],), "never deleted"),
            ("UPDATE rights_document_tags SET license_id=? WHERE id=?", (other["id"], tag["id"]), "binding is immutable|only once"),
            ("UPDATE rights_document_tags SET status='removed' WHERE id=?", (tag["id"],), "only once"),
            ("INSERT INTO rights_document_tags (id, document_id, license_id, license_version, status, tagged_by, tagged_at) VALUES ('rtag_x', ?, ?, 1, 'removed', 'raw', 't')",
             (self.memo, lic["id"]), "created active"),
            ("INSERT INTO rights_document_tags (id, document_id, license_id, license_version, status, tagged_by, tagged_at) VALUES ('rtag_x', ?, ?, 7, 'active', 'raw', 't')",
             (self.memo, lic["id"]), "current version"),
            ("INSERT INTO rights_document_tags (id, document_id, license_id, license_version, status, tagged_by, tagged_at) VALUES ('rtag_x', ?, ?, 1, 'active', 'raw', 't')",
             (self.doc, lic["id"]), "already carries an active tag"),
        ]
        for sql, params, reason in refusals:
            with self.subTest(sql=sql[:60]):
                with self.assertRaisesRegex(sqlite3.IntegrityError, reason):
                    with db.transaction() as conn:
                        conn.execute(sql, params)
        removed = self.p.untag_document(self.doc, lic["id"], "owner")
        with self.assertRaisesRegex(sqlite3.IntegrityError, "only once"):
            with db.transaction() as conn:
                conn.execute("UPDATE rights_document_tags SET status='active', removed_by=NULL, removed_at=NULL, removal_reason=NULL WHERE id=?", (removed["id"],))
        with self.assertRaisesRegex(sqlite3.IntegrityError, "only once"):
            with db.transaction() as conn:
                conn.execute("UPDATE rights_document_tags SET removal_reason='rewritten' WHERE id=?", (removed["id"],))
        self.assertEqual(self.p._tag(removed["id"])["removal_reason"], "")

    def test_tag_removal_fields_are_validated_by_the_database(self):
        lic = self.s.license(SPEC, ["project_use", "ai_embedding"], expires_on="2099-12-31", purge=True)
        with recorded_at(-2):
            tag = self.p.tag_document(self.doc, lic["id"], "owner")  # tagged two days ago
        self.assertEqual(tag["tagged_at"], ts(-2))
        sql = "UPDATE rights_document_tags SET status='removed', removed_by=?, removed_at=?, removal_reason='raw' WHERE id=?"
        cases = [
            ("raw", "1999-01-01T00:00:00Z", "before it was tagged"),  # the reviewer's backdated removal
            ("raw", ts(-3), "before it was tagged"),
            ("raw", ts(-1), "cannot be backdated"),                  # within the tag's life, but not the moment of removal
            ("raw", "", "UTC timestamp"),
            ("raw", "garbage", "UTC timestamp"),
            ("raw", days(0), "UTC timestamp"),
            ("raw", now_iso().replace("T", " "), "UTC timestamp"),
            ("raw", now_iso().replace("Z", ".5Z"), "UTC timestamp"),
            ("raw", 20261012, "UTC timestamp"),
            ("raw", ts(1), "future"),
            ("", now_iso(), "removed_by"),
            ("   ", now_iso(), "removed_by"),
        ]
        for removed_by, removed_at, reason in cases:
            with self.subTest(removed_by=removed_by, removed_at=removed_at):
                self.assertRawRefused(sql, (removed_by, removed_at, tag["id"]), reason)
        self.assertEqual([t["status"] for t in self.p.document_tags(self.doc, include_removed=True)], ["active"])
        # so a later retroactive expiry still finds the tag active and the purge owed
        self.p.update_license(lic["id"], expires_on=days(-3), note="terminated retroactively by the licensor", actor="owner")
        [item] = self.p.expired_items()
        self.assertEqual((item["document_id"], item["purge_outstanding"], item["expired_licenses"][0]["tag_status"]), (self.doc, True, "active"))
        # a raw removal stamped now passes these checks (the purge rule then refuses it)
        self.assertRawRefused(sql, ("raw", now_iso(), tag["id"]), "record the purge before untagging")
        self.p.record_purge(self.doc, lic["id"], "owner", note="local index purged")
        removed = self.p.untag_document(self.doc, lic["id"], "owner", reason="licensed text removed")
        self.assertEqual(removed["status"], "removed")
        self.assertEqual(self.p.expired_items(), [])

    def test_insert_or_replace_cannot_rewrite_tag_history(self):
        lic = self.s.license(SPEC, ["project_use"])
        first = self.p.tag_document(self.doc, lic["id"], "owner")
        self.p.untag_document(self.doc, lic["id"], "owner", reason="superseded")
        active = self.p.tag_document(self.doc, lic["id"], "owner")
        before_audit = self.all_rights_actions()
        raw = ("{verb} INTO rights_document_tags (id, document_id, license_id, license_version, status, tagged_by, tagged_at) "
               "VALUES (?, ?, ?, 1, 'active', 'raw', 't')")
        for verb in ("INSERT OR REPLACE", "REPLACE", "INSERT OR IGNORE"):
            with self.subTest(verb=verb):
                # reusing the removed tag's id would erase it and (through the active-tag index) the current tag too
                self.assertRawRefused(raw.format(verb=verb), (first["id"], self.doc, lic["id"]), "never replaced")
                self.assertRawRefused(raw.format(verb=verb), (active["id"], self.doc, lic["id"]), "never replaced")
                # a new id for the same document and license would replace the active tag
                self.assertRawRefused(raw.format(verb=verb), ("rtag_new", self.doc, lic["id"]), "already carries an active tag")
        history = self.p.document_tags(self.doc, include_removed=True)
        self.assertEqual([(t["id"], t["status"], t["tagged_by"]) for t in history],
                         [(first["id"], "removed", "owner"), (active["id"], "active", "owner")])
        self.assertEqual(self.all_rights_actions(), before_audit)
        self.assertBooksIntact()


# --------------------------------------------------------------------------- #
# Use checks and the default AI processor                                      #
# --------------------------------------------------------------------------- #

class UseCheckTests(RightsTestCase):
    def test_allowed_and_denied_by_use(self):
        lic = self.s.license(SPEC, ["internal_reference", "project_use", "ai_retrieval"])
        self.p.tag_document(self.doc, lic["id"], "owner")
        expected = {"internal_reference": True, "project_use": True, "ai_retrieval": True, "ai_embedding": False, "distribution": False}
        for use, allowed in expected.items():
            with self.subTest(use=use):
                r = self.p.check_use(self.doc, use, "2026-11-15", processor=LOCAL)
                self.assertIs(r["allowed"], allowed)
                self.assertEqual((r["processor"], r["processor_source"]), (LOCAL, "named"))
                self.assertEqual(r["license_id"], lic["id"])
                self.assertEqual(r["license_ids"], [lic["id"]])
                self.assertEqual(r["use"], use)
                if allowed:
                    self.assertEqual(r["valid_until"], "2026-12-31")
                    self.assertIn("permitted by every tagged license", r["reason"])
                else:
                    self.assertIsNone(r["valid_until"])
                    self.assertIn(f"does not permit {use}", r["reason"])
                    self.assertTrue(r["reason"].startswith("refused: "))
        # the non-AI uses need no processor; with none named and no default configured the permitted AI use is refused
        plain = self.p.check_use(self.doc, "project_use", "2026-11-15")
        self.assertTrue(plain["allowed"])
        self.assertEqual((plain["processor"], plain["processor_source"]), (None, None))
        unnamed = self.p.check_use(self.doc, "ai_retrieval", "2026-11-15")
        self.assertFalse(unnamed["allowed"])
        self.assertEqual((unnamed["license_id"], unnamed["processor"], unnamed["processor_source"]), (lic["id"], None, None))
        self.assertIn("no default AI processor is configured (set_default_processor)", unnamed["reason"])
        self.assertIn(LOCAL, unnamed["reason"])  # the reason names what the license lists

    def test_invalid_use_and_input_rejected(self):
        lic = self.s.license(SPEC, ["project_use"])
        self.p.tag_document(self.doc, lic["id"], "owner")
        for bad in ("ai_training", "", "Project_Use", None, 3, ["project_use"]):
            for doc in (self.doc, self.memo):  # also for company-owned content
                with self.subTest(use=bad, doc=doc):
                    with self.assertRaises(RightsError):
                        self.p.check_use(doc, bad, "2026-11-01")
        with self.assertRaises(RightsError):
            self.p.check_use("doc_missing", "project_use")
        for bad_date in ("2026-13-01", "2026-11-31", "11/01/2026", "", 20261101, dt.datetime(2026, 11, 1)):
            with self.subTest(on_date=bad_date):
                with self.assertRaises(RightsError):
                    self.p.check_use(self.doc, "project_use", bad_date)
        for bad_processor in ("", "   ", 7):
            with self.subTest(processor=bad_processor):
                with self.assertRaises(RightsError):
                    self.p.check_use(self.doc, "project_use", "2026-11-01", processor=bad_processor)

    def test_expiry_boundary_dates(self):
        lic = self.s.license(SPEC, ["project_use", "ai_retrieval"], expires_on="2026-12-31")
        self.p.tag_document(self.doc, lic["id"], "owner")
        self.assertTrue(self.p.check_use(self.doc, "project_use", "2026-12-30")["allowed"])
        last_day = self.p.check_use(self.doc, "project_use", "2026-12-31")
        self.assertTrue(last_day["allowed"])  # valid through its expires_on date
        self.assertEqual(last_day["valid_until"], "2026-12-31")
        day_after = self.p.check_use(self.doc, "project_use", "2027-01-01")
        self.assertFalse(day_after["allowed"])
        self.assertEqual(day_after["license_id"], lic["id"])
        self.assertIn("expired (valid through 2026-12-31)", day_after["reason"])
        self.assertFalse(self.p.check_use(self.doc, "project_use", dt.date(2027, 1, 1))["allowed"])
        self.assertTrue(self.p.check_use(self.doc, "project_use", dt.date(2026, 12, 31))["allowed"])
        # leap day
        self.p.update_license(lic["id"], expires_on="2028-02-29", actor="owner")
        self.assertTrue(self.p.check_use(self.doc, "ai_retrieval", "2028-02-29", processor=LOCAL)["allowed"])
        self.assertFalse(self.p.check_use(self.doc, "ai_retrieval", "2028-03-01", processor=LOCAL)["allowed"])
        # no expiry
        self.p.update_license(lic["id"], expires_on=None, actor="owner")
        perpetual = self.p.check_use(self.doc, "ai_retrieval", "2099-12-31", processor=LOCAL)
        self.assertTrue(perpetual["allowed"])
        self.assertIsNone(perpetual["valid_until"])
        self.assertIn("no expiry", perpetual["reason"])

    def test_default_date_is_the_utc_calendar_date(self):
        lapsed = self.s.license(SPEC, ["project_use"], expires_on=days(-1))
        current = self.s.license(FORMS, ["project_use"], expires_on=days(0))
        lapsed_doc = self.s.doc("Section XX 20 00 - sheet piling (licensed)")
        self.p.tag_document(lapsed_doc["id"], lapsed["id"], "owner")
        self.p.tag_document(self.doc, current["id"], "owner")
        self.assertFalse(self.p.check_use(lapsed_doc["id"], "project_use")["allowed"])
        today_answer = self.p.check_use(self.doc, "project_use")
        self.assertTrue(today_answer["allowed"])
        self.assertEqual(today_answer["on_date"], utc_today().isoformat())
        # the default comes from Plugin._today()
        with today_is(1):
            self.assertFalse(self.p.check_use(self.doc, "project_use")["allowed"])
        with today_is(-1):
            self.assertTrue(self.p.check_use(lapsed_doc["id"], "project_use")["allowed"])

    def test_multiple_tags_most_restrictive_wins(self):
        spec = self.s.license(SPEC, ["internal_reference", "project_use", "ai_retrieval"], expires_on="2027-06-30")
        forms = self.s.license(FORMS, ["internal_reference", "project_use"], expires_on="2026-12-31")
        self.p.tag_document(self.doc, spec["id"], "owner")
        self.p.tag_document(self.doc, forms["id"], "owner")
        both = self.p.check_use(self.doc, "project_use", "2026-11-01")
        self.assertTrue(both["allowed"])
        self.assertEqual(both["license_id"], forms["id"])  # the governing license is the one that expires first
        self.assertEqual(both["valid_until"], "2026-12-31")
        self.assertEqual(both["license_ids"], [spec["id"], forms["id"]])
        self.assertEqual([x["allowed"] for x in both["licenses"]], [True, True])
        ai = self.p.check_use(self.doc, "ai_retrieval", "2026-11-01", processor=LOCAL)
        self.assertFalse(ai["allowed"])  # one license permits it, the other does not
        self.assertEqual(ai["license_id"], forms["id"])
        self.assertEqual([(x["license_id"], x["allowed"]) for x in ai["licenses"]], [(spec["id"], True), (forms["id"], False)])
        lapsed = self.p.check_use(self.doc, "project_use", "2027-01-01")
        self.assertFalse(lapsed["allowed"])  # the shorter license has expired
        self.assertEqual(lapsed["license_id"], forms["id"])
        # a third, refusing license: every refusal is reported, the first tagged one is named
        handbook = self.s.license(HANDBOOK, ["internal_reference"], expires_on=None)
        self.p.tag_document(self.doc, handbook["id"], "owner")
        refused = self.p.check_use(self.doc, "ai_retrieval", "2026-11-01", processor=LOCAL)
        self.assertFalse(refused["allowed"])
        self.assertEqual(refused["license_id"], forms["id"])
        self.assertIn(forms["id"], refused["reason"])
        self.assertIn(handbook["id"], refused["reason"])
        self.assertNotIn(spec["id"], refused["reason"])
        # removing the restrictive tags leaves the permissive license in charge
        self.p.untag_document(self.doc, forms["id"], "owner")
        self.p.untag_document(self.doc, handbook["id"], "owner")
        after = self.p.check_use(self.doc, "ai_retrieval", "2027-01-01", processor=LOCAL)
        self.assertTrue(after["allowed"])
        self.assertEqual((after["license_id"], after["valid_until"]), (spec["id"], "2027-06-30"))

    def test_named_processor_must_be_listed_by_every_license(self):
        spec = self.s.license(SPEC, ["ai_retrieval"], processors=[LOCAL, "Hosted-Model-A"], expires_on="2027-06-30")
        forms = self.s.license(FORMS, ["ai_retrieval"], processors=[LOCAL], expires_on="2027-06-30")
        self.p.tag_document(self.doc, spec["id"], "owner")
        self.assertTrue(self.p.check_use(self.doc, "ai_retrieval", "2026-11-01", processor="hosted-model-a")["allowed"])
        self.assertFalse(self.p.check_use(self.doc, "ai_retrieval", "2026-11-01", processor="hosted-model-b")["allowed"])
        self.p.tag_document(self.doc, forms["id"], "owner")
        refused = self.p.check_use(self.doc, "ai_retrieval", "2026-11-01", processor="Hosted-Model-A")
        self.assertFalse(refused["allowed"])
        self.assertEqual(refused["license_id"], forms["id"])
        self.assertIn("does not list processor", refused["reason"])
        self.assertTrue(self.p.check_use(self.doc, "ai_retrieval", "2026-11-01", processor=LOCAL)["allowed"])
        # an AI use with no processor named and no default configured is refused for licensed content
        unnamed = self.p.check_use(self.doc, "ai_retrieval", "2026-11-01")
        self.assertFalse(unnamed["allowed"])
        self.assertEqual(unnamed["license_id"], spec["id"])
        self.assertIn("no default AI processor is configured", unnamed["reason"])
        self.assertTrue(self.p.check_use(self.memo, "ai_retrieval", "2026-11-01")["allowed"])  # company-owned content has no processor rule

    def test_processor_names_fold_unicode_case(self):
        lic = self.s.license(SPEC, ["ai_retrieval"], processors=["Émile-Host"], expires_on="2027-06-30")
        self.p.tag_document(self.doc, lic["id"], "owner")
        self.assertTrue(self.p.check_use(self.doc, "ai_retrieval", "2026-11-01", processor="ÉMILE-HOST")["allowed"])
        self.assertTrue(self.p.check_use(self.doc, "ai_retrieval", "2026-11-01", processor="émile-host")["allowed"])
        self.assertFalse(self.p.check_use(self.doc, "ai_retrieval", "2026-11-01", processor="emile-host")["allowed"])

    def test_empty_processor_list_refuses_every_ai_processor(self):
        lic = self.s.license(SPEC, ["project_use", "ai_embedding"], processors=[], expires_on="2027-06-30")
        self.p.tag_document(self.doc, lic["id"], "owner")
        self.assertTrue(self.p.check_use(self.doc, "project_use", "2026-11-01")["allowed"])  # non-AI use, no processor named: no processor test
        self.assertFalse(self.p.check_use(self.doc, "project_use", "2026-11-01", processor="any-host")["allowed"])  # a named one is tested
        for processor in (None, LOCAL, "any-host"):
            with self.subTest(processor=processor):
                r = self.p.check_use(self.doc, "ai_embedding", "2026-11-01", processor=processor)
                self.assertFalse(r["allowed"])
                self.assertIn("no processor" if processor is None else "does not list processor", r["reason"])
        self.p.set_default_processor(LOCAL, "owner")
        self.assertFalse(self.p.check_use(self.doc, "ai_embedding", "2026-11-01")["allowed"])  # the default is not listed either
        self.assertTrue(self.p.check_use(self.doc, "project_use", "2026-11-01")["allowed"])  # and is never tested for the non-AI uses
        docs = {d["document_id"]: d for d in self.p.state(self.s.project["id"])["documents"]}
        self.assertEqual(docs[self.doc]["ai_processors"], [])
        self.assertFalse(docs[self.doc]["uses"]["ai_embedding"])
        self.assertTrue(docs[self.doc]["uses"]["project_use"])
        self.assertEqual(docs[self.doc]["default_processor_uses"], {"ai_retrieval": False, "ai_embedding": False})
        self.assertIsNone(docs[self.memo]["ai_processors"])

    def test_default_ai_processor_is_versioned_audited_and_used_when_none_is_named(self):
        lic = self.s.license(SPEC, ["project_use", "ai_retrieval"], processors=[LOCAL, "Hosted-Model-A"], expires_on="2027-06-30")
        self.p.tag_document(self.doc, lic["id"], "owner")
        self.assertEqual(self.p.default_processor(), {"processor": None, "version": 0, "id": None, "note": "", "set_by": None, "set_at": None})
        first = self.p.set_default_processor(f"  {LOCAL} ", "owner", note="the assistant's local index host")
        self.assertEqual((first["processor"], first["version"], first["set_by"], first["note"]), (LOCAL, 1, "owner", "the assistant's local index host"))
        r = self.p.check_use(self.doc, "ai_retrieval", "2026-11-01")
        self.assertTrue(r["allowed"])
        self.assertEqual((r["processor"], r["processor_source"]), (LOCAL, "default"))
        self.assertIn(f"for processor {LOCAL}", r["reason"])
        # a named processor overrides the default; the default is not tested for the non-AI uses
        named = self.p.check_use(self.doc, "ai_retrieval", "2026-11-01", processor="hosted-model-a")
        self.assertEqual((named["allowed"], named["processor"], named["processor_source"]), (True, "hosted-model-a", "named"))
        self.assertEqual(self.p.check_use(self.doc, "project_use", "2026-11-01")["processor_source"], None)
        # refusals
        for bad in ({"processor": LOCAL.upper()}, {"processor": ""}, {"processor": "   "}, {"processor": 42}, {"processor": "other", "actor": ""},
                    {"processor": "other", "expected_version": 0}, {"processor": "other", "expected_version": "1"}):
            with self.subTest(bad=bad):
                with self.assertRaises(RightsError):
                    self.p.set_default_processor(**{"actor": "owner", **bad})
        # an unlisted default refuses, and clearing it falls back to refusing the unnamed AI use
        third_party = self.p.set_default_processor("hosted-model-b", "owner", expected_version=1)
        self.assertEqual(third_party["version"], 2)
        refused = self.p.check_use(self.doc, "ai_retrieval", "2026-11-01")
        self.assertFalse(refused["allowed"])
        self.assertIn("does not list processor 'hosted-model-b' (the default AI processor)", refused["reason"])
        cleared = self.p.set_default_processor(None, "owner")
        self.assertEqual((cleared["processor"], cleared["version"]), (None, 3))
        with self.assertRaisesRegex(RightsError, "already unset"):
            self.p.set_default_processor(None, "owner")
        self.assertIn("no default AI processor is configured", self.p.check_use(self.doc, "ai_retrieval", "2026-11-01")["reason"])
        self.p.set_default_processor(LOCAL, "owner")
        # filter_retrievable uses the same rule
        gate = self.p.filter_retrievable([self.doc, self.memo], "ai_retrieval", project_id=self.s.project["id"], on_date="2026-11-01")
        self.assertEqual((gate["allowed"], gate["processor"], gate["processor_source"]), ([self.doc, self.memo], LOCAL, "default"))
        # history and audit
        history = self.p.default_processor_history()
        self.assertEqual([(h["version"], h["processor"]) for h in history], [(1, LOCAL), (2, "hosted-model-b"), (3, None), (4, LOCAL)])
        actions = self.rights_actions("rights_setting", "default_ai_processor")
        self.assertEqual(actions, ["rights.default_processor_set"] * 4)
        last = self.payload("rights_setting", "default_ai_processor", "rights.default_processor_set")
        self.assertEqual((last["version"], last["previous_processor"], last["processor"]), (4, None, LOCAL))
        # the settings rows are guarded
        for sql, params, reason in (
            ("UPDATE rights_ai_processor_settings SET processor='x' WHERE version=1", (), "immutable"),
            ("DELETE FROM rights_ai_processor_settings WHERE version=1", (), "immutable"),
            ("INSERT OR REPLACE INTO rights_ai_processor_settings (id, version, processor, note, set_by, set_at) VALUES (?, 5, 'x', '', 'raw', 't')",
             (history[0]["id"],), "never replaced"),
            ("INSERT OR REPLACE INTO rights_ai_processor_settings (id, version, processor, note, set_by, set_at) VALUES ('rset_x', 4, 'x', '', 'raw', 't')", (), "never replaced"),
            ("INSERT INTO rights_ai_processor_settings (id, version, processor, note, set_by, set_at) VALUES ('rset_x', 7, 'x', '', 'raw', 't')", (), "contiguous"),
            ("INSERT INTO rights_ai_processor_settings (id, version, processor, note, set_by, set_at) VALUES ('rset_x', 5, ' x', '', 'raw', 't')", (), "trimmed"),
            ("INSERT INTO rights_ai_processor_settings (id, version, processor, note, set_by, set_at) VALUES ('rset_x', 5, '', '', 'raw', 't')", (), "trimmed"),
        ):
            with self.subTest(sql=sql[:50]):
                self.assertRawRefused(sql, params, reason)
        self.assertEqual(self.p.default_processor()["processor"], LOCAL)
        st = self.p.state(self.s.project["id"])
        self.assertEqual(st["default_ai_processor"], LOCAL)
        docs = {d["document_id"]: d for d in st["documents"]}
        self.assertEqual(docs[self.doc]["default_processor_uses"], {"ai_retrieval": True, "ai_embedding": False})
        self.assertEqual(docs[self.memo]["default_processor_uses"], {"ai_retrieval": True, "ai_embedding": True})
        self.assertEqual(self.p.audit_export()["default_processor_settings"], history)
        self.assertBooksIntact()

    def test_retrieval_requires_access_and_content_rights(self):
        spec = self.s.license(SPEC, ["ai_retrieval", "project_use"], expires_on="2027-06-30")
        forms = self.s.license(FORMS, ["project_use"], expires_on="2027-06-30")
        restricted = self.s.doc("Subcontract form text (licensed)", kind="contract_form")
        elsewhere = self.s.doc("Cofferdam dewatering memo", kind="memo", project=self.s.other_project)
        self.p.tag_document(self.doc, spec["id"], "owner")
        self.p.tag_document(restricted["id"], forms["id"], "owner")
        ids = [self.doc, self.memo, restricted["id"], elsewhere["id"], "doc_missing", self.doc, f" {self.doc}", f"{self.memo} ", " doc_missing"]
        r = self.p.filter_retrievable(ids, "ai_retrieval", project_id=self.s.project["id"], on_date="2026-11-01", processor=LOCAL)
        self.assertEqual(r["allowed"], [self.doc, self.memo])  # each document once, whatever whitespace surrounds its id
        self.assertEqual(len(r["denied"]), 3)
        # with no processor named and no default configured, the licensed document is refused for AI retrieval; company content is not
        unnamed = self.p.filter_retrievable([self.doc, self.memo], "ai_retrieval", project_id=self.s.project["id"], on_date="2026-11-01")
        self.assertEqual(unnamed["allowed"], [self.memo])
        self.assertEqual(unnamed["denied"][0]["license_id"], spec["id"])
        self.assertIn("no default AI processor is configured", unnamed["denied"][0]["reason"])
        denied = {d["document_id"]: d for d in r["denied"]}
        self.assertEqual(set(denied), {restricted["id"], elsewhere["id"], "doc_missing"})
        self.assertTrue(denied[restricted["id"]]["reason"].startswith("content rights:"))
        self.assertEqual(denied[restricted["id"]]["license_id"], forms["id"])
        self.assertTrue(denied[elsewhere["id"]]["reason"].startswith("access:"))
        self.assertTrue(denied["doc_missing"]["reason"].startswith("access:"))
        # without a project scope only content rights apply
        unscoped = self.p.filter_retrievable([self.doc, elsewhere["id"], restricted["id"]], "ai_retrieval", on_date="2026-11-01", processor=LOCAL)
        self.assertEqual(unscoped["allowed"], [self.doc, elsewhere["id"]])
        # after expiry nothing licensed is retrievable
        later = self.p.filter_retrievable([self.doc, self.memo], "ai_retrieval", project_id=self.s.project["id"], on_date="2027-07-01", processor=LOCAL)
        self.assertEqual(later["allowed"], [self.memo])
        with self.assertRaises(RightsError):
            self.p.filter_retrievable([self.doc], "ai_training")
        with self.assertRaises(RightsError):
            self.p.filter_retrievable(self.doc, "ai_retrieval")
        with self.assertRaises(RightsError):
            self.p.filter_retrievable([self.doc], "ai_retrieval", project_id="prj_missing")


class RickyRetrievalTests(RightsTestCase):
    """The plan's retrieval path end to end: Ricky's read_document against the real registry."""

    def read(self, sdk, document_id):
        return sdk.invoke("read_document", {"document_id": document_id}, actor="ricky-test", actor_role="owner")

    def test_ricky_reads_licensed_content_through_the_default_ai_processor(self):
        sdk = RickySDK(self.c)
        lic = self.s.license(SPEC, ["project_use", "ai_retrieval"], processors=[LOCAL], expires_on="2099-12-31")
        self.p.tag_document(self.doc, lic["id"], "owner")
        # licensed content needs a processor the license lists; Ricky names none, so the configured default is used
        before = self.read(sdk, self.doc)
        self.assertEqual(before["status"], "refused", before)
        self.assertIn("no default AI processor is configured", before["error"])
        self.assertNotIn("result", before)
        company = self.read(sdk, self.memo)
        self.assertEqual(company["status"], "ok", company)
        self.assertEqual(company["result"]["rights"]["checked"], True)
        self.assertIn("company-owned", company["result"]["rights"]["reason"])
        self.p.set_default_processor(LOCAL, "owner", note="the assistant reads through the local index")
        ok = self.read(sdk, self.doc)
        self.assertEqual(ok["status"], "ok", ok)
        self.assertEqual(ok["result"]["document"]["id"], self.doc)
        self.assertEqual((ok["result"]["rights"]["checked"], ok["result"]["rights"]["use"], ok["result"]["rights"]["allowed"]), (True, "ai_retrieval", True))
        self.assertIn(f"for processor {LOCAL}", ok["result"]["rights"]["reason"])
        # an unlisted default, a withdrawn AI right and an expiry each refuse the read
        self.p.set_default_processor("hosted-model-b", "owner")
        self.assertIn("does not list processor 'hosted-model-b'", self.read(sdk, self.doc)["error"])
        self.p.set_default_processor(LOCAL, "owner")
        self.p.update_license(lic["id"], permitted_uses=["project_use"], note="AI retrieval withdrawn", actor="owner")
        self.assertIn("does not permit ai_retrieval", self.read(sdk, self.doc)["error"])
        self.p.update_license(lic["id"], permitted_uses=["project_use", "ai_retrieval"], expires_on=days(-1), actor="owner")
        self.assertIn("expired", self.read(sdk, self.doc)["error"])
        self.assertEqual(self.read(sdk, self.memo)["status"], "ok")
        self.assertBooksIntact()


# --------------------------------------------------------------------------- #
# Expiry and purge                                                             #
# --------------------------------------------------------------------------- #

class ExpiryAndPurgeTests(RightsTestCase):
    def test_expired_items_list_documents_with_purge_flag(self):
        spec = self.s.license(SPEC, ["project_use", "ai_embedding"], expires_on="2026-12-31", purge=True)
        forms = self.s.license(FORMS, ["project_use"], expires_on="2026-11-30", purge=False)
        handbook = self.s.license(HANDBOOK, ["project_use"], expires_on=None, purge=True)
        form_doc = self.s.doc("Subcontract form text (licensed)", kind="contract_form")
        manual = self.s.doc("Pump station handbook excerpt", kind="reference")
        elsewhere = self.s.doc("Cofferdam guide section XX 30 00 (licensed)", project=self.s.other_project)
        self.p.tag_document(self.doc, spec["id"], "owner")
        self.p.tag_document(self.doc, forms["id"], "owner")
        self.p.tag_document(form_doc["id"], forms["id"], "owner")
        self.p.tag_document(manual["id"], handbook["id"], "owner")
        self.p.tag_document(elsewhere["id"], spec["id"], "owner")

        self.assertEqual(self.p.expired_items("2026-11-30"), [])  # last valid day of the shorter license
        mid = self.p.expired_items("2026-12-15")
        self.assertEqual([i["document_id"] for i in mid], [self.doc, form_doc["id"]])
        self.assertEqual([lic["license_id"] for lic in mid[0]["expired_licenses"]], [forms["id"]])
        self.assertEqual([(i["purge_required"], i["purge_outstanding"], i["as_recorded"]) for i in mid], [(False, False, False), (False, False, False)])

        later = {i["document_id"]: i for i in self.p.expired_items("2027-01-01")}
        self.assertEqual(set(later), {self.doc, form_doc["id"], elsewhere["id"]})  # never the perpetual handbook or company memo
        spec_doc = later[self.doc]
        self.assertEqual([lic["license_id"] for lic in spec_doc["expired_licenses"]], [forms["id"], spec["id"]])
        self.assertEqual([lic["purge_on_expiry"] for lic in spec_doc["expired_licenses"]], [False, True])
        self.assertEqual([lic["expires_on"] for lic in spec_doc["expired_licenses"]], ["2026-11-30", "2026-12-31"])
        self.assertTrue(spec_doc["purge_required"])
        self.assertTrue(spec_doc["purge_outstanding"])
        self.assertEqual(spec_doc["on_date"], "2027-01-01")
        self.assertFalse(later[form_doc["id"]]["purge_required"])
        self.assertTrue(later[elsewhere["id"]]["purge_required"])

        scoped = self.p.expired_items("2027-01-01", project_id=self.s.project["id"])
        self.assertEqual([i["document_id"] for i in scoped], [self.doc, form_doc["id"]])
        self.assertEqual(self.p.expired_items(dt.date(2027, 1, 1), project_id=self.s.other_project["id"])[0]["document_id"], elsewhere["id"])
        for bad in ({"on_date": "2027-02-30"}, {"project_id": "prj_missing"}, {"as_recorded": "yes"}):
            with self.subTest(bad=bad):
                with self.assertRaises(RightsError):
                    self.p.expired_items(**bad)
        self.assertEqual({lic["tag_status"] for i in later.values() for lic in i["expired_licenses"]}, {"active"})
        # untagging a license with no purge rule removes a document from the list; the history stays
        self.p.untag_document(form_doc["id"], forms["id"], "owner", reason="form text deleted from the project record")
        self.assertNotIn(form_doc["id"], {i["document_id"] for i in self.p.expired_items("2027-01-01")})

    def test_untag_is_refused_while_the_purge_is_outstanding(self):
        lic = self.s.license(SPEC, ["project_use"], expires_on=days(-5), purge=True)
        self.p.tag_document(self.doc, lic["id"], "owner")
        [item] = self.p.expired_items()
        self.assertTrue(item["purge_outstanding"])
        with self.assertRaisesRegex(RightsError, "record_purge first"):
            self.p.untag_document(self.doc, lic["id"], "owner", reason="content no longer needed")
        # the database refuses the same removal on its own
        self.assertRawRefused("UPDATE rights_document_tags SET status='removed', removed_by='raw', removed_at='t', removal_reason='raw' "
                              "WHERE document_id=? AND license_id=?", (self.doc, lic["id"]), "record the purge before untagging")
        self.assertEqual([t["status"] for t in self.p.document_tags(self.doc, include_removed=True)], ["active"])
        self.assertFalse(self.p.check_use(self.doc, "project_use")["allowed"])  # still licensed, still expired
        self.assertEqual([i["document_id"] for i in self.p.expired_items()], [self.doc])
        self.assertEqual(self.counts("P-unrecorded")["rights.purges_outstanding"]["purges_outstanding"], 1)
        self.assertEqual(self.rights_actions("document", self.doc), ["rights.document_tagged"])  # refusals are not audited
        # once the purge is recorded the tag can go, and nothing is left outstanding
        self.p.record_purge(self.doc, lic["id"], "owner", note="index and cache entries deleted")
        removed = self.p.untag_document(self.doc, lic["id"], "owner", reason="licensed text removed from the project record")
        self.assertEqual(removed["status"], "removed")
        self.assertEqual(self.p.expired_items(), [])
        self.assertTrue(self.p.check_use(self.doc, "project_use")["allowed"])
        self.assertEqual(self.rights_actions("document", self.doc), ["rights.document_tagged", "rights.purge_recorded", "rights.document_untagged"])
        # an expired license without a purge rule can be untagged at once
        plain = self.s.license(FORMS, ["project_use"], expires_on=days(-5), purge=False)
        self.p.tag_document(self.memo, plain["id"], "owner")
        self.assertEqual(self.p.untag_document(self.memo, plain["id"], "owner")["status"], "removed")
        self.assertBooksIntact()

    def test_tag_removed_before_a_retroactive_expiry_keeps_its_purge_owed(self):
        lic = self.s.license(SPEC, ["ai_embedding", "project_use"], expires_on="2099-12-31", purge=True)
        self.p.tag_document(self.doc, lic["id"], "owner")
        self.p.untag_document(self.doc, lic["id"], "owner", reason="licensed text replaced by company text")
        self.assertEqual(self.p.expired_items("2100-01-01"), [])  # removed while the license was valid: no purge is owed
        self.assertTrue(self.p.check_use(self.doc, "project_use", "2100-01-01")["allowed"])
        # the licensor terminates the license retroactively, before the day the tag was removed
        self.p.update_license(lic["id"], expires_on=days(-3), note="terminated retroactively by the licensor", actor="owner")
        [item] = self.p.expired_items()
        self.assertEqual((item["document_id"], item["purge_required"], item["purge_outstanding"]), (self.doc, True, True))
        [entry] = item["expired_licenses"]
        self.assertEqual((entry["license_id"], entry["tag_status"], entry["purged"], entry["expires_on"]), (lic["id"], "removed", False, days(-3)))
        # untagged, but its derived copies still owe the purge: the document is not usable until the purge is recorded
        owed = self.p.check_use(self.doc, "project_use")
        self.assertFalse(owed["allowed"])
        self.assertEqual((owed["license_id"], owed["license_ids"], [o["license_id"] for o in owed["purges_owed"]]), (lic["id"], [], [lic["id"]]))
        self.assertIn("still owe that purge", owed["reason"])
        summary = self.p.state(self.s.project["id"])["summary"]
        self.assertEqual((summary["purges_outstanding"], summary["documents_with_purges_outstanding"], summary["licensed_documents"]), (1, 1, 0))
        self.assertEqual(self.counts("P-unrecorded")["rights.purges_outstanding"]["purges_outstanding"], 1)
        purge = self.p.record_purge(self.doc, lic["id"], "owner", note="embeddings deleted from the local index")
        self.assertEqual((purge["license_version"], purge["expires_on"]), (2, days(-3)))
        self.assertEqual(self.payload("document", self.doc, "rights.purge_recorded")["tag_status"], "removed")
        self.assertEqual(self.p.expired_items(), [])
        self.assertTrue(self.p.check_use(self.doc, "project_use")["allowed"])  # company-owned once the purge is on record
        with self.assertRaisesRegex(RightsError, "already recorded"):
            self.p.record_purge(self.doc, lic["id"], "owner")
        self.assertBooksIntact()

    def test_amending_terms_around_an_untag_cannot_release_content_that_owes_a_purge(self):
        # route 1: switch the purge rule off, untag, switch it back on
        lic = self.s.license(SPEC, ["project_use", "ai_embedding"], expires_on=days(-5), purge=True)
        self.p.tag_document(self.doc, lic["id"], "owner")
        with self.assertRaisesRegex(RightsError, "record_purge first"):
            self.p.untag_document(self.doc, lic["id"], "owner")
        self.p.update_license(lic["id"], purge_on_expiry=False, note="licensor waived the purge", actor="owner")
        self.p.untag_document(self.doc, lic["id"], "owner", reason="licensed text removed")
        self.assertTrue(self.p.check_use(self.doc, "project_use")["allowed"])  # with the rule waived nothing is owed
        self.p.update_license(lic["id"], purge_on_expiry=True, note="waiver withdrawn", actor="owner")
        owed = self.p.check_use(self.doc, "project_use")
        self.assertFalse(owed["allowed"])
        self.assertEqual(owed["license_id"], lic["id"])
        [item] = self.p.expired_items()
        self.assertEqual((item["document_id"], item["purge_outstanding"], item["expired_licenses"][0]["tag_status"]), (self.doc, True, "removed"))
        gate = self.p.filter_retrievable([self.doc], "project_use", project_id=self.s.project["id"])
        self.assertEqual((gate["allowed"], gate["denied"][0]["license_id"]), ([], lic["id"]))
        docs = {d["document_id"]: d for d in self.p.state(self.s.project["id"])["documents"]}
        self.assertEqual((docs[self.doc]["company_owned"], docs[self.doc]["licenses"], docs[self.doc]["purges_owed"]), (False, [], [lic["id"]]))
        self.assertFalse(any(docs[self.doc]["uses"].values()))
        self.p.record_purge(self.doc, lic["id"], "owner", note="index purged")
        self.assertTrue(self.p.check_use(self.doc, "project_use")["allowed"])
        self.assertTrue({d["document_id"]: d for d in self.p.state(self.s.project["id"])["documents"]}[self.doc]["company_owned"])
        # route 2: renew the expiry, untag while valid, move the expiry back into the past
        other = self.s.license(FORMS, ["project_use"], expires_on=days(-5), purge=True)
        self.p.tag_document(self.memo, other["id"], "owner")
        self.p.update_license(other["id"], expires_on=days(1), note="renewed", actor="owner")
        self.p.untag_document(self.memo, other["id"], "owner", reason="memo rewritten")
        self.assertEqual(self.payload("document", self.memo, "rights.document_untagged")["company_owned"], True)
        self.assertTrue(self.p.check_use(self.memo, "project_use")["allowed"])
        self.p.update_license(other["id"], expires_on=days(-5), note="renewal reversed", actor="owner")
        refused = self.p.check_use(self.memo, "project_use")
        self.assertFalse(refused["allowed"])
        self.assertIn("still owe that purge", refused["reason"])
        self.assertEqual([i["document_id"] for i in self.p.expired_items()], [self.memo])
        self.p.record_purge(self.memo, other["id"], "owner")
        self.assertTrue(self.p.check_use(self.memo, "project_use")["allowed"])
        self.assertBooksIntact()

    def test_purge_rows_cannot_be_replaced_or_duplicated_for_one_expiry(self):
        lic = self.s.license(SPEC, ["ai_embedding"], expires_on=days(-10), purge=True)
        self.p.tag_document(self.doc, lic["id"], "owner")
        purge = self.p.record_purge(self.doc, lic["id"], "owner", note="index purged")
        before_audit = self.all_rights_actions()
        today = utc_today().isoformat()
        raw = ("{verb} INTO rights_purges (id, document_id, license_id, license_version, expires_on, purged_on, note, purged_by, purged_at) "
               "VALUES (?, ?, ?, ?, ?, ?, 'rewritten', 'mallory', 't')")
        for verb in ("INSERT OR REPLACE", "REPLACE", "INSERT OR IGNORE"):
            with self.subTest(verb=verb):
                self.assertRawRefused(raw.format(verb=verb), (purge["id"], self.doc, lic["id"], 1, days(-10), today), "never replaced")
                self.assertRawRefused(raw.format(verb=verb), ("rprg_new", self.doc, lic["id"], 1, days(-10), today), "never replaced")
        # a processors-only amendment keeps the expiry; a second purge for that same expiry is refused by the database too
        self.p.update_license(lic["id"], processors=[LOCAL, "local-model-host"], actor="owner")
        self.assertRawRefused(raw.format(verb="INSERT"), ("rprg_second", self.doc, lic["id"], 2, days(-10), today), "already answers that expiry")
        self.assertEqual([(p["id"], p["note"], p["purged_by"]) for p in self.p.purges()], [(purge["id"], "index purged", "owner")])
        self.assertEqual(self.all_rights_actions(), before_audit + ["rights.license_updated"])
        self.assertBooksIntact()

    def test_record_purge_after_expiry(self):
        lic = self.s.license(SPEC, ["ai_embedding"], expires_on=days(-10), purge=True)
        self.p.tag_document(self.doc, lic["id"], "owner")
        [item] = self.p.expired_items()
        self.assertEqual(item["document_id"], self.doc)
        self.assertEqual((item["purge_required"], item["purge_outstanding"]), (True, True))
        purge = self.p.record_purge(self.doc, lic["id"], "owner", note="embeddings and cache entries deleted from the local index")
        self.assertEqual((purge["license_version"], purge["expires_on"], purge["purged_on"]), (1, days(-10), utc_today().isoformat()))
        [after] = self.p.expired_items()
        self.assertEqual((after["purge_required"], after["purge_outstanding"]), (True, False))
        self.assertEqual(after["expired_licenses"][0]["purge_id"], purge["id"])
        self.assertEqual(after["expired_licenses"][0]["purged_on"], utc_today().isoformat())
        self.assertFalse(self.p.check_use(self.doc, "ai_embedding")["allowed"])  # purging does not restore any right
        with self.assertRaisesRegex(RightsError, "already recorded"):
            self.p.record_purge(self.doc, lic["id"], "owner")
        self.assertEqual(self.rights_actions("document", self.doc), ["rights.document_tagged", "rights.purge_recorded"])
        self.assertEqual([p["id"] for p in self.p.purges(self.doc)], [purge["id"]])
        for sql in ("UPDATE rights_purges SET note='edited' WHERE id=?", "DELETE FROM rights_purges WHERE id=?"):
            with self.subTest(sql=sql):
                self.assertRawRefused(sql, (purge["id"],), "immutable")
        # a later amendment that leaves the expiry alone does not reopen the purge
        self.p.update_license(lic["id"], processors=[LOCAL, "local-model-host"], actor="owner")
        [amended] = self.p.expired_items()
        self.assertFalse(amended["purge_outstanding"])
        with self.assertRaisesRegex(RightsError, "already recorded"):
            self.p.record_purge(self.doc, lic["id"], "owner")
        self.assertBooksIntact()

    def test_record_purge_refusals(self):
        live = self.s.license(SPEC, ["project_use"], expires_on=days(0), purge=True)  # valid through today
        perpetual = self.s.license(FORMS, ["project_use"], expires_on=None, purge=True)
        lapsed = self.s.license(HANDBOOK, ["project_use"], expires_on=days(-3), purge=True)
        self.p.tag_document(self.doc, live["id"], "owner")
        self.p.tag_document(self.doc, perpetual["id"], "owner")
        with self.assertRaisesRegex(RightsError, "has not expired"):
            self.p.record_purge(self.doc, live["id"], "owner")
        with self.assertRaisesRegex(RightsError, "has not expired"):
            self.p.record_purge(self.doc, perpetual["id"], "owner")
        with self.assertRaisesRegex(RightsError, "not tagged"):
            self.p.record_purge(self.doc, lapsed["id"], "owner")
        with self.assertRaises(RightsError):
            self.p.record_purge("doc_missing", lapsed["id"], "owner")
        with self.assertRaises(RightsError):
            self.p.record_purge(self.doc, lapsed["id"], "")
        self.assertEqual(self.p.purges(), [])
        # the database refuses the same things on its own
        self.p.tag_document(self.memo, lapsed["id"], "owner")
        raw = ("INSERT INTO rights_purges (id, document_id, license_id, license_version, expires_on, purged_on, note, purged_by, purged_at) "
               "VALUES ('rprg_x', ?, ?, 1, ?, ?, '', 'raw', 't')")
        cases = [
            ((self.doc, live["id"], days(0), days(0)), "only after the license has expired"),
            ((self.memo, lapsed["id"], days(-3), days(1)), "not in the future"),
            ((self.memo, lapsed["id"], days(-9), utc_today().isoformat()), "expiry date"),
            ((self.doc, lapsed["id"], days(-3), utc_today().isoformat()), "tagged with the license"),
        ]
        for params, reason in cases:
            with self.subTest(reason=reason):
                self.assertRawRefused(raw, params, reason)
        self.assertEqual(self.p.purges(), [])

    def test_renewal_after_purge_requires_a_new_purge_on_the_next_expiry(self):
        lic = self.s.license(SPEC, ["ai_embedding"], expires_on=days(-10), purge=True)
        self.p.tag_document(self.doc, lic["id"], "owner")
        self.p.record_purge(self.doc, lic["id"], "owner")
        renewed = self.p.update_license(lic["id"], expires_on=days(30), note="renewed for one more month", actor="owner")
        self.assertEqual(renewed["version"], 2)
        self.assertEqual(self.p.expired_items(), [])
        self.assertTrue(self.p.check_use(self.doc, "ai_embedding", processor=LOCAL)["allowed"])
        [next_expiry] = self.p.expired_items(days(31))
        self.assertTrue(next_expiry["purge_outstanding"])  # the earlier purge predates the renewed term
        self.assertFalse(next_expiry["expired_licenses"][0]["purged"])
        with self.assertRaisesRegex(RightsError, "has not expired"):
            self.p.record_purge(self.doc, lic["id"], "owner")

    def test_as_recorded_view_reads_the_registry_at_the_end_of_a_day(self):
        with recorded_at(-30):
            lic = self.s.license(SPEC, ["project_use"], expires_on=days(-15), purge=True)
            self.p.tag_document(self.doc, lic["id"], "owner")
        with recorded_at(-12), today_is(-12):
            self.p.record_purge(self.doc, lic["id"], "owner", note="index purged twelve days ago")
        # before the license was registered there is nothing; the current view knows no such boundary
        self.assertEqual(self.p.expired_items(days(-31), as_recorded=True), [])
        # a purge recorded on day -12 is not on record at the end of day -14 (the current view shows it as done)
        [then] = self.p.expired_items(days(-14), as_recorded=True)
        [now_view] = self.p.expired_items(days(-14))
        self.assertEqual((then["as_recorded"], then["purge_outstanding"], then["expired_licenses"][0]["purged"]), (True, True, False))
        self.assertEqual((now_view["as_recorded"], now_view["purge_outstanding"]), (False, False))
        self.assertFalse(self.p.expired_items(days(-12), as_recorded=True)[0]["purge_outstanding"])
        # today: the expiry is amended retroactively and the tag removed
        self.p.update_license(lic["id"], expires_on=days(-18), note="expiry corrected", actor="owner")
        self.p.untag_document(self.doc, lic["id"], "owner", reason="licensed text removed")
        # as recorded at the end of day -16 the terms then in force had not expired; the current view applies today's terms
        self.assertEqual(self.p.expired_items(days(-16), as_recorded=True), [])
        self.assertEqual([i["document_id"] for i in self.p.expired_items(days(-16))], [])  # removed, and the purge answers the new expiry
        [still_active] = self.p.expired_items(days(-14), as_recorded=True)
        self.assertEqual((still_active["expired_licenses"][0]["tag_status"], still_active["expired_licenses"][0]["expires_on"]), ("active", days(-15)))
        # close_checks read the same view at the period end
        self.c.open_period("P0", "Ended period", days(-40), days(-14))
        self.assertEqual(self.counts("P0")["rights.registry"], {"as_of": days(-14), "period_id": "P0", "licenses": 1, "active_document_tags": 1})
        self.assertEqual(self.counts("P0")["rights.purges_outstanding"]["purges_outstanding"], 1)
        self.assertEqual(self.counts("P0")["rights.licenses_expiring_in_period"]["licenses_expiring"], 1)


# --------------------------------------------------------------------------- #
# Integration: approvals, close, export, state, workspace                     #
# --------------------------------------------------------------------------- #

class IntegrationTests(RightsTestCase):
    def test_no_approval_bound_operations(self):
        lic = self.s.license(SPEC, ["project_use"])
        with self.assertRaisesRegex(RightsError, "no approval-bound operations"):
            self.c.request_approval("rights.tag_document", self.doc, actor_role="owner")
        with self.assertRaises(RightsError):
            self.p.manifest_for("rights.update_license", lic["id"], actor_role="owner")
        with self.assertRaises(RightsError):
            self.p.apply("rights.update_license", lic["id"], approval_id="apr_x", manifest={}, actor="owner", period_id="P1")
        self.assertEqual(self.c.approvals.list(), [])
        proposal = self.c.ricky.propose("rights.tag_document", actor_role="owner", context={"document_id": self.doc})
        self.assertEqual(proposal["decision"], "abstained")
        self.assertIsNone(proposal["manifest"])

    def test_close_checks_are_informational_and_the_close_checklist_shows_their_counts(self):
        end = self.s.period["end_date"]
        expiring = self.s.license(SPEC, ["project_use"], expires_on=days(5), purge=True)
        lapsed = self.s.license(FORMS, ["project_use"], expires_on=days(-5), purge=True)
        self.p.tag_document(self.doc, lapsed["id"], "owner")
        self.p.tag_document(self.memo, expiring["id"], "owner")
        checks = self.p.close_checks("P1")
        self.assertEqual([c["check"] for c in checks], ["rights.registry", "rights.expired_content", "rights.purges_outstanding", "rights.licenses_expiring_in_period"])
        self.assertTrue(all(c["ok"] is True for c in checks))
        counts = {c["check"]: c["counts"] for c in checks}
        self.assertTrue(all(c["as_of"] == end and c["period_id"] == "P1" for c in counts.values()))  # judged as recorded at the period end date
        self.assertEqual(counts["rights.registry"], {"as_of": end, "period_id": "P1", "licenses": 2, "active_document_tags": 2})
        self.assertEqual(counts["rights.expired_content"], {"as_of": end, "period_id": "P1", "documents": 2, "licenses": 2})  # both expire before the end
        self.assertEqual(counts["rights.purges_outstanding"],
                         {"as_of": end, "period_id": "P1", "purges_outstanding": 2, "documents_with_purges_outstanding": 2})
        self.assertEqual(counts["rights.licenses_expiring_in_period"], {"as_of": end, "period_id": "P1", "licenses_expiring": 2})
        when = f"as recorded at the end of {end}"
        self.assertEqual([c["detail"] for c in checks], [
            f"2 license(s) registered and 2 active document tag(s) {when} ({INFO})",
            f"2 document(s) listed against 2 license(s) expired on {end}, {when}; every use of them is refused ({INFO})",
            f"2 purge(s) outstanding (one per document and expired purge-on-expiry license) on 2 document(s), {when} ({INFO})",
            f"2 license(s) whose terms {when} expire between {self.s.period['start_date']} and {end} ({INFO})",
        ])
        json.dumps(checks)
        # the close checklist keeps only check, ok and detail: the counts reach it through the details
        close = self.c.plugin("close")
        shown = [c for c in close.checklist("P1") if c["source"] == "rights"]
        self.assertEqual([(c["check"], c["ok"], c["detail"]) for c in shown], [(c["check"], c["ok"], c["detail"]) for c in checks])
        report = close.checklist_report("P1")
        self.assertTrue(report["all_ok"], report["failing"])
        self.assertIn(checks[2]["detail"], [c["detail"] for c in report["checks"]])
        # a UTC midnight changes nothing for a recorded period; registry changes move the counts of a period not yet ended
        details = [c["detail"] for c in checks]
        with today_is(1):
            self.assertEqual([c["detail"] for c in self.p.close_checks("P1")], details)
        third = self.s.license(HANDBOOK, ["project_use"], expires_on=days(3), purge=True)
        self.p.tag_document(self.s.doc("Pump station handbook excerpt", kind="reference")["id"], third["id"], "owner")
        moved = self.counts("P1")
        self.assertEqual((moved["rights.registry"]["licenses"], moved["rights.licenses_expiring_in_period"]["licenses_expiring"]), (3, 3))
        self.assertNotEqual([c["detail"] for c in self.p.close_checks("P1")], details)
        # a period that is not recorded: still informational, judged as recorded at the end of the UTC date of the check
        unknown = self.p.close_checks("P-missing")
        self.assertTrue(all(c["ok"] is True for c in unknown))
        self.assertTrue(all("not recorded" in c["detail"] for c in unknown))
        self.assertEqual(unknown[0]["counts"]["as_of"], utc_today().isoformat())
        self.assertIsNone(unknown[-1]["counts"]["licenses_expiring"])
        # informational checks never surface as Ricky review items
        brief = self.c.ricky.brief(self.s.project["id"], actor_role="owner")
        self.assertFalse([i for i in brief["items"] if i["kind"] in ("close_check", "close_check_error") and "rights" in i["text"]])

    def test_purges_outstanding_has_one_unit_everywhere(self):
        first = self.s.license(SPEC, ["project_use"], expires_on=days(-3), purge=True)
        second = self.s.license(FORMS, ["project_use"], expires_on=days(-4), purge=True)
        self.p.tag_document(self.doc, first["id"], "owner")
        self.p.tag_document(self.doc, second["id"], "owner")  # one document, two expired purge-on-expiry licenses
        close = self.counts("P1")["rights.purges_outstanding"]
        summary = self.p.state(self.s.project["id"])["summary"]
        self.assertEqual((close["purges_outstanding"], close["documents_with_purges_outstanding"]), (2, 1))
        self.assertEqual((summary["purges_outstanding"], summary["documents_with_purges_outstanding"]), (2, 1))
        self.assertTrue(self.details("P1")["rights.purges_outstanding"].startswith("2 purge(s) outstanding (one per document and expired purge-on-expiry license) on 1 document(s)"))
        self.p.record_purge(self.doc, first["id"], "owner")
        self.assertEqual(self.p.state(self.s.project["id"])["summary"]["purges_outstanding"], 1)
        self.assertEqual(self.counts("P1")["rights.purges_outstanding"]["purges_outstanding"], 1)

    def test_close_of_an_ended_period_is_not_staled_by_later_registry_activity_or_midnight(self):
        self.c.open_period("P0", "Ended period", days(-40), days(-11))
        with recorded_at(-30):
            lic = self.s.license(SPEC, ["project_use"], expires_on=days(-25), purge=True)
            other = self.s.license(FORMS, ["project_use"], expires_on=days(-20), purge=True)
            self.p.tag_document(self.doc, lic["id"], "owner")
            self.p.tag_document(self.memo, other["id"], "owner")
        with recorded_at(-22), today_is(-22):
            self.p.record_purge(self.doc, lic["id"], "owner", note="index purged")
        close = self.c.plugin("close")
        report = close.checklist_report("P0")
        self.assertTrue(report["all_ok"], report["failing"])
        rights = {c["check"]: c["detail"] for c in report["checks"] if c["source"] == "rights"}
        when = f"as recorded at the end of {days(-11)}"
        self.assertEqual(rights["rights.registry"], f"2 license(s) registered and 2 active document tag(s) {when} ({INFO})")
        self.assertTrue(rights["rights.purges_outstanding"].startswith("1 purge(s) outstanding (one per document and expired purge-on-expiry license) on 1 document(s)"))
        self.assertTrue(rights["rights.licenses_expiring_in_period"].startswith("2 license(s) whose terms"))
        ap = self.c.request_approval("close.close_period", "P0")
        self.c.approve(ap["id"])
        # after the period's end: a purge, an amendment, a new license and tag, an untag, and the UTC date moves on
        self.p.record_purge(self.memo, other["id"], "owner", note="index purged")
        self.p.update_license(lic["id"], processors=[LOCAL, "local-model-host"], actor="owner")
        third = self.s.license(HANDBOOK, ["project_use"], expires_on=days(-20), purge=True)
        self.p.tag_document(self.s.doc("Pump station handbook excerpt", kind="reference")["id"], third["id"], "owner")
        self.p.untag_document(self.doc, lic["id"], "owner", reason="licensed text removed")
        self.p.set_default_processor(LOCAL, "owner")
        with today_is(1):
            self.assertEqual(close.checklist_report("P0")["hash"], report["hash"])
            res = self.c.execute(ap["id"])
        self.assertEqual(res.result["status"], "closed")
        self.assertEqual(self.c.ledger.period("P0")["status"], "closed")
        self.assertEqual(self.c.approvals.get(ap["id"])["status"], "consumed")
        self.assertTrue(self.c.audit.verify_chain()["ok"])

    def test_close_of_a_running_period_binds_the_rights_position_recorded_so_far(self):
        lic = self.s.license(SPEC, ["project_use"], expires_on=days(-2), purge=True)
        self.p.tag_document(self.doc, lic["id"], "owner")
        close = self.c.plugin("close")
        report = close.checklist_report("P1")
        self.assertTrue(report["all_ok"], report["failing"])
        ap = self.c.request_approval("close.close_period", "P1")
        self.c.approve(ap["id"])
        with today_is(1):  # a UTC midnight alone does not stale it
            self.assertEqual(close.checklist_report("P1")["hash"], report["hash"])
        # a purge recorded before the period ends changes the position the approver saw
        self.p.record_purge(self.doc, lic["id"], "owner", note="index purged")
        self.assertNotEqual(close.checklist_report("P1")["hash"], report["hash"])
        with self.assertRaises(StaleApprovalError):
            self.c.execute(ap["id"])
        self.assertEqual(self.c.approvals.get(ap["id"])["status"], "invalidated")
        self.assertEqual(self.c.ledger.period("P1")["status"], "open")
        fresh = self.c.request_approval("close.close_period", "P1")
        self.c.approve(fresh["id"])
        self.assertEqual(self.c.execute(fresh["id"]).result["status"], "closed")
        self.assertTrue(self.c.audit.verify_chain()["ok"])

    def test_audit_export_is_json_serialisable_and_complete(self):
        lic = self.s.license(SPEC, ["ai_embedding"], expires_on=days(-2), purge=True)
        self.p.update_license(lic["id"], processors=[LOCAL, "local-model-host"], actor="owner")
        self.p.tag_document(self.doc, lic["id"], "owner")
        self.p.record_purge(self.doc, lic["id"], "owner")
        other = self.s.license(FORMS, ["project_use"], expires_on=None)
        self.p.tag_document(self.memo, other["id"], "owner")
        self.p.untag_document(self.memo, other["id"], "owner", reason="memo is company-authored")
        self.p.set_default_processor(LOCAL, "owner")
        export = self.p.audit_export()
        json.dumps(export)
        self.assertEqual(export["as_of"], utc_today().isoformat())
        self.assertEqual(export["uses"], list(USES))
        self.assertEqual(len(export["licenses"]), 2)
        self.assertEqual([(v["license_id"], v["version"]) for v in export["license_versions"] if v["license_id"] == lic["id"]], [(lic["id"], 1), (lic["id"], 2)])
        self.assertEqual(sorted(t["status"] for t in export["document_tags"]), ["active", "removed"])
        self.assertEqual(len(export["purges"]), 1)
        self.assertEqual([i["document_id"] for i in export["expired_items"]], [self.doc])
        self.assertEqual((export["unadopted_versions"], export["pending_unadopted_versions"]), ([], []))
        self.assertEqual([s["processor"] for s in export["default_processor_settings"]], [LOCAL])
        full = self.c.audit_export()
        json.dumps(full, default=str)
        self.assertNotIn("error", full["modules"]["rights"])
        self.assertEqual(len(full["modules"]["rights"]["license_versions"]), 3)
        rights_entries = [e["action"] for e in full["audit"]["entries"] if e["action"].startswith("rights.")]
        self.assertEqual(rights_entries, ["rights.license_registered", "rights.license_updated", "rights.document_tagged", "rights.purge_recorded",
                                          "rights.license_registered", "rights.document_tagged", "rights.document_untagged", "rights.default_processor_set"])
        self.assertTrue(full["audit"]["chain"]["ok"])
        checks = full["open_period_close_checks"]["P1"]
        self.assertTrue(all(c["ok"] for c in checks if c["source"] == "rights"))

    def test_state_reports_licenses_documents_and_uses(self):
        spec = self.s.license(SPEC, ["internal_reference", "project_use", "ai_retrieval"], expires_on="2099-12-31")
        lapsed = self.s.license(FORMS, ["project_use"], expires_on=days(-1), purge=True)
        form_doc = self.s.doc("Subcontract form text (licensed)", kind="contract_form")
        self.s.doc("Cofferdam memo", kind="memo", project=self.s.other_project)
        self.p.tag_document(self.doc, spec["id"], "owner")
        self.p.tag_document(form_doc["id"], lapsed["id"], "owner")
        st = self.p.state(self.s.project["id"])
        self.assertEqual(st["summary"], {
            "licenses": 2, "licenses_expired": 1, "documents": 3, "licensed_documents": 2, "company_owned_documents": 1,
            "expired_documents": 1, "purges_outstanding": 1, "documents_with_purges_outstanding": 1,
        })
        self.assertIsNone(st["default_ai_processor"])
        docs = {d["document_id"]: d for d in st["documents"]}
        self.assertEqual(docs[self.doc]["uses"], {"internal_reference": True, "project_use": True, "ai_retrieval": True, "ai_embedding": False, "distribution": False})
        self.assertEqual(docs[self.doc]["ai_processors"], [LOCAL])  # the AI uses are reported for the processors every license lists
        self.assertIsNone(docs[self.doc]["default_processor_uses"])
        self.assertIsNone(docs[self.memo]["ai_processors"])
        self.assertTrue(all(docs[self.memo]["uses"].values()))
        self.assertTrue(docs[self.memo]["company_owned"])
        self.assertEqual(docs[self.memo]["purges_owed"], [])
        self.assertFalse(any(docs[form_doc["id"]]["uses"].values()))
        self.assertEqual({lic["id"]: (lic["expired"], lic["tagged_documents"]) for lic in st["licenses"]}, {spec["id"]: (False, 1), lapsed["id"]: (True, 1)})
        self.assertEqual([i["document_id"] for i in st["expired_items"]], [form_doc["id"]])
        self.assertEqual(self.c.project_state(self.s.project["id"])["rights"]["summary"], st["summary"])
        with self.assertRaises(RightsError):
            self.p.state("prj_missing")
        self.assertBooksIntact()

    def test_file_backed_registry_persists_and_restored_copy_cannot_change_it(self):
        workdir = tempfile.mkdtemp(prefix="cipher-rights-")
        self.addCleanup(shutil.rmtree, workdir, True)  # runs after every connection below is closed
        path = os.path.join(workdir, "rights.sqlite")
        s = Scene(path)
        lic = s.license(SPEC, ["project_use"], expires_on="2026-12-31", purge=True)
        s.p.tag_document(s.spec_doc["id"], lic["id"], "owner")
        s.p.update_license(lic["id"], permitted_uses=["project_use", "ai_retrieval"], actor="owner")
        lapsed = s.license(FORMS, ["project_use"], expires_on=days(-4), purge=True)
        s.p.tag_document(s.memo["id"], lapsed["id"], "owner")
        s.p.set_default_processor(LOCAL, "owner")
        snapshot = s.c.snapshot(os.path.join(workdir, "rights-copy.sqlite"))
        s.c.db.close()

        reopened = Cipher(path)
        try:
            rp = reopened.plugin(PLUGIN_NAME)
            self.assertEqual(reopened.db.schema_status()["pending"], [])
            self.assertEqual(rp.license(lic["id"])["version"], 2)
            self.assertTrue(rp.check_use(s.spec_doc["id"], "ai_retrieval", "2026-11-01")["allowed"])  # the default processor persists
            self.assertEqual(rp.default_processor()["processor"], LOCAL)
            self.assertTrue(reopened.audit.verify_chain()["ok"])
        finally:
            reopened.db.close()

        restored = Cipher.open_restored(snapshot)
        try:
            rp = restored.plugin(PLUGIN_NAME)
            self.assertFalse(restored.db.authority_status()["effective_write_authority"])
            self.assertTrue(rp.check_use(s.spec_doc["id"], "ai_retrieval", "2026-11-01", processor=LOCAL)["allowed"])  # reads still work
            for attempt in (
                lambda: rp.register_license(HANDBOOK["licensor"], HANDBOOK["work"], HANDBOOK["edition"], HOLDER, ["project_use"], [], None, False, actor="owner"),
                lambda: rp.update_license(lic["id"], expires_on="2030-12-31", actor="owner"),
                lambda: rp.tag_document(s.spec_doc["id"], lapsed["id"], "owner"),
                lambda: rp.untag_document(s.spec_doc["id"], lic["id"], "owner"),
                lambda: rp.record_purge(s.memo["id"], lapsed["id"], "owner"),
                lambda: rp.set_default_processor("hosted-model-b", "owner"),
                lambda: rp.supersede_unadopted_version(lic["id"], "owner"),
            ):
                with self.assertRaises(WriteAuthorityError):
                    attempt()
            self.assertEqual(rp.license(lic["id"])["version"], 2)
            self.assertEqual(len(rp.document_tags(s.spec_doc["id"])), 1)
            self.assertEqual(rp.purges(), [])
            self.assertEqual(rp.default_processor()["processor"], LOCAL)
            self.assertEqual([i["document_id"] for i in rp.expired_items()], [s.memo["id"]])
        finally:
            restored.db.close()

    def test_workspace_on_the_earlier_schema_upgrades_in_place(self):
        workdir = tempfile.mkdtemp(prefix="cipher-rights-upgrade-")
        self.addCleanup(shutil.rmtree, workdir, True)
        path = os.path.join(workdir, "earlier.sqlite")
        earlier = [entry for entry in db_module.SCHEMA_CATALOG if entry[1] != HARDENING_SCHEMA_NAME]
        stamp = now_iso()
        with mock.patch.object(db_module, "SCHEMA_CATALOG", earlier):
            old = Scene(path)
            try:
                applied = {r["name"] for r in old.c.db.query("SELECT name FROM schema_version")}
                self.assertTrue({SCHEMA_NAME, GUARDS_SCHEMA_NAME} <= applied)
                self.assertNotIn(HARDENING_SCHEMA_NAME, applied)
                self.assertIn("DEFERRABLE", old.c.db.scalar("SELECT sql FROM sqlite_master WHERE name='rights_license_versions'"))
                cols = rights_module._VERSION_COLUMNS
                with old.c.db.transaction() as conn:  # the earlier registration order: terms first, the deferred key checked at COMMIT
                    conn.execute("INSERT INTO rights_license_versions (" + cols + ") VALUES ('licv_legacy1', 'lic_legacy', 1, '[\"ai_retrieval\", \"project_use\"]', ?, '2099-12-31', 1, '', 'h1', 'owner', ?)",
                                 (json.dumps([LOCAL]), stamp))
                    conn.execute("INSERT INTO rights_licenses (id, licensor, work, edition, holder, version, created_by, created_at, updated_at) VALUES ('lic_legacy', ?, ?, ?, ?, 1, 'owner', ?, ?)",
                                 (SPEC["licensor"], SPEC["work"], SPEC["edition"], HOLDER, stamp, stamp))
                with old.c.db.transaction() as conn:
                    conn.execute("INSERT INTO rights_license_versions (" + cols + ") VALUES ('licv_legacy2', 'lic_legacy', 2, '[\"project_use\"]', ?, '2099-12-31', 1, 'AI withdrawn', 'h2', 'owner', ?)",
                                 (json.dumps([LOCAL]), stamp))
                    conn.execute("UPDATE rights_licenses SET version=2, updated_at=? WHERE id='lic_legacy'", (stamp,))
                    conn.execute("INSERT INTO rights_document_tags (id, document_id, license_id, license_version, status, tagged_by, tagged_at) VALUES ('rtag_legacy', ?, 'lic_legacy', 2, 'active', 'owner', ?)",
                                 (old.spec_doc["id"], stamp))
                    conn.execute("INSERT INTO rights_document_tags (id, document_id, license_id, license_version, status, tagged_by, tagged_at) VALUES ('rtag_gone', ?, 'lic_legacy', 2, 'active', 'owner', ?)",
                                 (old.memo["id"], stamp))
                    conn.execute("UPDATE rights_document_tags SET status='removed', removed_by='owner', removed_at=?, removal_reason='memo rewritten' WHERE id='rtag_gone'", (stamp,))
                    # a trigger elsewhere that names a table no entry has created yet (SQLite resolves trigger bodies when they run):
                    # the upgrade must not depend on re-parsing unrelated triggers, as ALTER TABLE ... RENAME would
                    conn.execute("CREATE TABLE zz_probe_forward (x)")
                    conn.execute("CREATE TRIGGER zz_probe_forward_ref BEFORE INSERT ON zz_probe_forward BEGIN SELECT * FROM zz_table_created_later; END")
            finally:
                old.c.db.close()

        new = Cipher(path)  # the full catalog: the hardening entry rebuilds the versions table in place
        try:
            status = new.db.schema_status()
            self.assertEqual(status["pending"], [])
            self.assertTrue(all(v["checksum_matches"] for v in status["versions"] if v["applied"]))
            self.assertNotIn("DEFERRABLE", new.db.scalar("SELECT sql FROM sqlite_master WHERE name='rights_license_versions'").upper())
            rp = new.plugin(PLUGIN_NAME)
            history = rp.license_history("lic_legacy")
            self.assertEqual([(h["id"], h["version"], h["status"], h["permitted_uses"], h["created_at"]) for h in history],
                             [("licv_legacy1", 1, "superseded", ["ai_retrieval", "project_use"], stamp), ("licv_legacy2", 2, "current", ["project_use"], stamp)])
            self.assertEqual([(t["id"], t["status"]) for t in rp.document_tags(old.memo["id"], include_removed=True)], [("rtag_gone", "removed")])
            self.assertFalse(rp.check_use(old.spec_doc["id"], "ai_retrieval", "2026-11-01", processor=LOCAL)["allowed"])
            self.assertTrue(rp.check_use(old.spec_doc["id"], "project_use", "2026-11-01")["allowed"])
            self.assertTrue(rp.check_use(old.memo["id"], "project_use", "2026-11-01")["allowed"])
            # a stray row over a legacy version (whose stored terms_hash is not the module's) can still be superseded
            with new.db.transaction() as conn:
                conn.execute(VERSION_INSERT, ("licv_stray", "lic_legacy", 3, json.dumps(list(USES)), "[]"))
            repaired = rp.supersede_unadopted_version("lic_legacy", "owner", note="stray row found after the upgrade")
            self.assertEqual((repaired["version"], repaired["permitted_uses"], repaired["expires_on"]), (4, ["project_use"], "2099-12-31"))
            v5 = rp.update_license("lic_legacy", permitted_uses=["project_use", "ai_retrieval"], note="AI retrieval restored", actor="owner")
            self.assertEqual(v5["version"], 5)
            self.assertEqual([h["status"] for h in rp.license_history("lic_legacy")], ["superseded", "superseded", "unadopted", "superseded", "current"])
            fresh = rp.register_license(FORMS["licensor"], FORMS["work"], FORMS["edition"], HOLDER, ["project_use"], [], None, False, actor="owner")
            self.assertEqual(fresh["version"], 1)
            with self.assertRaisesRegex(sqlite3.IntegrityError, "FOREIGN KEY"):
                with new.db.transaction() as conn:
                    conn.execute(VERSION_INSERT, ("licv_orphan", "lic_orphan", 1, "[]", "[]"))
            self.assertFalse(new.db.conn.in_transaction)
            self.assertTrue(new.audit.verify_chain()["ok"])
        finally:
            new.db.close()


if __name__ == "__main__":
    unittest.main()

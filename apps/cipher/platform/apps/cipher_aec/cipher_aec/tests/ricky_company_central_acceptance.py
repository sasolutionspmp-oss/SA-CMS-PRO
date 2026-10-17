"""Pure checks of captured ordinary Company acceptance facts; no site/HTTP calls.

The caller owns authentic observations, source attestation and transactions.
These assertions do not grant authority or establish that supplied facts are real.
"""
import json
from pathlib import Path

from cipher_aec.api.contracts import digest

TYPES = ("Cipher Ricky Run", "Cipher Ricky Step", "Cipher Tool Invocation",
         "Cipher Proposed Change", "Cipher Delegation", "Cipher Run Artifact")
START = "ricky.company.read.start.v1"
CANCEL = "ricky.company.read.cancel.v1"


def _closed(value, keys):
    assert type(value) is dict and set(value) == set(keys), "Unexpected acceptance fact shape"


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _equal(left, right):
    assert _canonical(left) == _canonical(right), "Captured original facts changed"


def _names(values):
    assert type(values) is list and all(type(x) is str and x for x in values)
    assert len(values) == len(set(values)), "Duplicate captured names"
    return set(values)


def _identity(manifest, row):
    assert row["company"] == manifest["company"]
    assert any(value["user"] == row["user"] and value["person"] == row["person"]
               for value in manifest["users"].values()), "Unbound observation actor"


def verify_metadata_preservation(control):
    """Compare independent pre/post migration captures, including raw data_json."""
    _closed(control, {"schema", "site", "before", "after", "installed"})
    assert control["schema"] == "cipher.ricky.metadata-preservation.v1"
    assert type(control["site"]) is str and control["site"]
    assert set(control["before"]) == set(control["after"]) == set(control["installed"]) == set(TYPES)
    total = 0
    for doctype in TYPES:
        old, new = control["before"][doctype], control["after"][doctype]
        for table in (old, new):
            _closed(table, {"columns", "rows"})
            _names(table["columns"])
            assert type(table["rows"]) is list
            assert all(type(row) is dict and set(row) == set(table["columns"]) for row in table["rows"])
        assert {"name", "project", "data_json"}.issubset(old["columns"])
        assert "scope_type" not in old["columns"]
        assert [x for x in new["columns"] if x != "scope_type"] == old["columns"]
        assert set(new["columns"]) == set(old["columns"]) | {"scope_type"}
        _names([row["name"] for row in old["rows"]]); _names([row["name"] for row in new["rows"]])
        before = {row["name"]: row for row in old["rows"]}
        after = {row["name"]: row for row in new["rows"]}
        assert len(before) == len(old["rows"]) and len(after) == len(new["rows"])
        assert set(before) == set(after), "Migration created or removed orchestration rows"
        for name, original in before.items():
            _equal(original, {key: after[name][key] for key in old["columns"]})
            assert type(original["data_json"]) is str
            assert after[name]["scope_type"] == "Project", "Existing row did not receive Project default"
        _equal(control["installed"][doctype], {
            "scope_type": {"fieldtype": "Select", "options": "Project\nCompany", "default": "Project", "reqd": 1, "read_only": 1},
            "project": {"reqd": 0, "mandatory_depends_on": "eval:doc.scope_type == 'Project'"}})
        total += len(before)
    return {"tables": len(TYPES), "original_rows_preserved": total, "runtime_observation_supplied_by_caller": True}


def verify_native_projections(manifest):
    """Validate actual-user query/count/read facts and the legacy baseline."""
    observations = manifest["native_projection_observations"]
    assert type(observations) is list and observations
    for row in observations:
        _closed(row, {"user", "person", "company", "doctype", "known_company_ids", "before", "after",
                      "company_query_ids", "company_query_count", "company_read_permissions"})
        _identity(manifest, row)
        assert row["doctype"] in TYPES
        known = _names(row["known_company_ids"])
        for key in ("before", "after"):
            _closed(row[key], {"ids", "count"})
            names = _names(row[key]["ids"])
            assert type(row[key]["count"]) is int and row[key]["count"] == len(names)
            assert not names & known, "Native projection exposed a Company row"
        _equal(sorted(row["before"]["ids"]), sorted(row["after"]["ids"]))
        assert row["before"]["count"] == row["after"]["count"]
        assert row["company_query_ids"] == []
        assert type(row["company_query_count"]) is int and row["company_query_count"] == 0
        assert type(row["company_read_permissions"]) is list
        permissions = {}
        for permission in row["company_read_permissions"]:
            _closed(permission, {"id", "allowed"})
            assert permission["id"] not in permissions
            assert permission["allowed"] is False, "Native direct read admitted a Company row"
            permissions[permission["id"]] = False
        assert set(permissions) == known, "Missing direct read observation"
    return {"observations": len(observations)}


def verify_shared_receipts(manifest):
    """Check captured data DTOs and exact saved canonical receipt bytes/hash."""
    from jsonschema import Draft202012Validator, FormatChecker
    schema = json.loads((Path(__file__).parents[1] / "ricky/schemas/company-api-v1.schema.json").read_text())
    observations = manifest["shared_receipt_observations"]
    assert type(observations) is list and observations
    for row in observations:
        _closed(row, {"user", "person", "company", "run_id", "operation_id", "command",
                      "initial", "replay", "operation_read", "stored_receipt"})
        _identity(manifest, row)
        assert row["command"] in {START, CANCEL}
        response = "CompanyRickyStartReadResponse" if row["command"] == START else "CompanyRickyStopResponse"
        validator = Draft202012Validator({"$defs": schema["$defs"], "$ref": "#/$defs/" + response}, format_checker=FormatChecker())
        for key, replayed in (("initial", False), ("replay", True), ("operation_read", True)):
            value = row[key]
            validator.validate(value)
            assert value["id"] == row["run_id"] and value["company"] == row["company"]
            _equal(value["operation"], {"id": row["operation_id"], "status": "succeeded", "replayed": replayed})
        body = {key: value for key, value in row["initial"].items() if key != "operation"}
        for key in ("replay", "operation_read"):
            _equal(body, {name: value for name, value in row[key].items() if name != "operation"})
        _closed(row["stored_receipt"], {"before", "after"})
        for key in ("before", "after"):
            stored = row["stored_receipt"][key]
            _closed(stored, {"result_json", "result_hash"})
            assert type(stored["result_json"]) is str and type(stored["result_hash"]) is str
            parsed = json.loads(stored["result_json"])
            _equal(parsed, body)
            assert digest(parsed) == stored["result_hash"]
        _equal(row["stored_receipt"]["before"], row["stored_receipt"]["after"])
    return {"receipts": len(observations), "runtime_observation_supplied_by_caller": True}

"""New packet labels cannot rewrite original domain facts or old grant hashes."""
from copy import deepcopy
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from cipher_aec.api.contracts import digest
from cipher_aec.governance import domain_approvals as service


class ApprovalPresentationTests(unittest.TestCase):
    def manifest(self):
        return {"action": "estimate.accept.v1", "domain": {"subject": {
            "doctype": "Cipher Estimate Revision", "name": "exact-revision",
            "label": "Original estimate baseline label"}, "sources": [],
            "effect": {"total": "30.85"}, "summary": "Original immutable facts"}}

    def test_new_snapshot_binds_exact_revision_and_server_authorized_title(self):
        reader = Mock(return_value={"estimate_title": "Drainage package", "revision_number": 3})
        with patch.dict("sys.modules", {"cipher_aec.estimating.governance": SimpleNamespace(approval_presentation=reader)}):
            snapshot = service.new_presentation(action="estimate.accept.v1", actor="trusted-actor",
                company="Company", project=None, subject_id="exact-revision", scope_type="Company", lock=True)
        reader.assert_called_once_with(actor="trusted-actor", company="Company", project=None,
            subject_id="exact-revision", scope_type="Company", lock=True)
        old = self.manifest()
        original, domain_digest = deepcopy(old), digest(old["domain"])
        new = {**old, "presentation": snapshot}
        self.assertEqual(service.subject_label(new), "Drainage package · Revision 3")
        self.assertEqual(digest(new["domain"]), domain_digest)
        self.assertNotEqual(digest(new), digest(old))
        self.assertEqual(old, original)
        self.assertEqual(service.subject_label(old), "Original estimate baseline label")

    def test_other_actions_keep_original_manifest_without_presentation(self):
        self.assertIsNone(service.new_presentation(action="calibration.verify.v1", actor=None,
            company="Company", project="Project", subject_id="calibration", scope_type="Project"))

    def test_stored_label_cannot_refer_to_another_revision_or_action(self):
        manifest = self.manifest()
        manifest["presentation"] = {"schema": "cipher.approval.presentation.v1",
            "subject": {"doctype": "Cipher Estimate Revision", "name": "another-revision"},
            "subject_label": "Unrelated title"}
        with self.assertRaises(RuntimeError):
            service.subject_label(manifest)
        manifest["presentation"]["subject"]["name"] = "exact-revision"
        manifest["action"] = "calibration.verify.v1"
        with self.assertRaises(RuntimeError):
            service.subject_label(manifest)


def run_native_acceptance(company):
    """Opt-in, existing synthetic Company fixture; every new row is rolled back."""
    import json
    from uuid import uuid4
    import frappe
    from cipher_aec.governance import approvals
    from cipher_aec.governance.context import assert_synthetic_site
    from cipher_aec.estimating import repository
    assert_synthetic_site()
    if frappe.session.user != "Administrator":
        raise RuntimeError("Use the coordinated synthetic Administrator bench context.")
    rows = frappe.db.sql("""SELECT r.name,r.author_person,e.data_json FROM `tabCipher Estimate Revision` r
        JOIN `tabCipher Estimate` e ON e.current_revision=r.name
        LEFT JOIN `tabCipher Estimate Acceptance` a ON a.estimate_revision=r.name
        WHERE r.scope_type='Company' AND r.company=%s AND a.name IS NULL ORDER BY r.creation DESC LIMIT 1""", (company,), as_dict=True)
    if not rows:
        raise RuntimeError("Use an existing qualified Company fixture with an unaccepted current revision; do not seed here.")
    row = rows[0]
    users = frappe.db.sql("SELECT user FROM `tabCipher Identity Binding` WHERE person=%s AND active=1 ORDER BY user", (row.author_person,))
    if not users:
        raise RuntimeError("The existing author has no current identity.")
    captured = frappe.db.sql("SELECT name,manifest_json,manifest_hash FROM `tabCipher Approval Packet` WHERE company=%s ORDER BY name", (company,))
    savepoint = "presentation_" + uuid4().hex
    frappe.db.savepoint(savepoint)
    try:
        frappe.set_user(users[0][0])
        revision = repository.read("revision", row.name)
        args = (company, None, "estimate.accept.v1", row.name, digest(revision))
        # A legacy-shaped packet exercises the original outer-manifest contract
        # without modifying any existing immutable packet or domain builder.
        with patch.object(service, "new_presentation", return_value=None):
            legacy = approvals.request_action(*args, str(uuid4()), scope_type="Company")["packet"]
        operation = str(uuid4())
        created = approvals.request_action(*args, operation, scope_type="Company")
        packet = created["packet"]
        stored = frappe.get_doc("Cipher Approval Packet", packet["id"])
        outer = json.loads(stored.manifest_json)
        legacy_stored = frappe.get_doc("Cipher Approval Packet", legacy["id"])
        legacy_outer = json.loads(legacy_stored.manifest_json)
        expected = f"{json.loads(row.data_json)['title']} · Revision {revision['revision_number']}"
        assert packet["subject"]["label"] == expected
        assert outer["domain"] == legacy_outer["domain"]
        assert "presentation" not in legacy_outer
        assert approvals.read_packet(company, None, legacy["id"], scope_type="Company")["state"] == "Pending"
        assert approvals.read_packet(company, None, legacy["id"], scope_type="Company")["subject"]["label"] == legacy_outer["domain"]["subject"]["label"]
        replay = approvals.request_action(*args, operation, scope_type="Company")
        assert replay["operation"]["replayed"] and replay["packet"] == packet
        assert digest(outer) == stored.manifest_hash and digest(legacy_outer) == legacy_stored.manifest_hash
        for name, body, checksum in captured:
            current = frappe.db.get_value("Cipher Approval Packet", name, ["manifest_json", "manifest_hash"])
            assert tuple(current) == (body, checksum)
        report = {"status": "passed", "company": company, "revision_id": row.name,
            "subject_label": expected, "original_packet_controls": len(captured),
            "checks": ["exact_title_and_revision_in_new_outer_manifest", "domain_manifest_unchanged",
                "legacy_pending_packet_remains_pending_with_original_label", "exact_receipt_replay",
                "original_packet_bytes_and_hashes_preserved"], "persistent_effects": False}
    finally:
        frappe.set_user("Administrator")
        frappe.db.rollback(save_point=savepoint)
    assert not frappe.db.exists("Cipher Approval Packet", packet["id"])
    report["checks"].append("all_new_rows_rolled_back")
    return report

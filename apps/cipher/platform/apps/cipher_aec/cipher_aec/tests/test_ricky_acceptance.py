"""Explicit opt-in real-Frappe acceptance; inference remains a labeled fixture.

Run on an installed, seeded synthetic site with:
bench --site <site> execute cipher_aec.tests.test_ricky_acceptance.run_acceptance
This is not a whitelisted endpoint or a runtime adapter registration.
"""

import hashlib
import secrets
import threading
from datetime import timedelta
from uuid import uuid4


def run_acceptance():
    import frappe
    from frappe.sessions import Session, delete_session
    from werkzeug.wrappers import Request
    from cipher_aec.api.errors import DomainError
    from cipher_aec.documents.service import upload_document
    from cipher_aec.governance.context import ABILITIES, assert_synthetic_site, trusted_write
    from cipher_aec.install import _binding, _grant, _person, _user
    from cipher_aec.ricky.backend import FrappeBackend
    from cipher_aec.ricky.api import _dispatch
    from cipher_aec.ricky.contracts import ModelResponse, RickyError, utcnow
    from cipher_aec.ricky.engine import RickyService
    from cipher_aec.ricky.storage import FrappeStore
    from cipher_aec.tests.test_ricky import FixtureAdapter

    assert_synthetic_site()
    if frappe.session.user != "Administrator":
        raise RuntimeError("Explicit fixture acceptance requires bench's synthetic Administrator context.")
    if frappe.conf.get("cipher_allow_unscanned_documents") not in (True, 1, "1"):
        raise RuntimeError("The synthetic acceptance site must explicitly allow labeled unscanned fixtures.")
    company = "Cipher Synthetic Company"
    if not frappe.db.exists("Company", company):
        raise RuntimeError("Seed the synthetic site before this explicit fixture acceptance.")

    marker = uuid4().hex[:12]
    user = f"ricky.fixture.{marker}@cipher.example"
    person = "RICKY-FIXTURE-" + marker
    with trusted_write():
        _person(person, "Explicit Ricky acceptance fixture")
        _user(user, "Explicit Ricky fixture", secrets.token_urlsafe(32))
        _binding(user, person)
        project = frappe.get_doc({"doctype": "Project", "company": company, "project_name": "Ricky explicit fixture " + marker, "status": "Open"})
        project.insert(ignore_permissions=True)
        for ability in sorted(ABILITIES):
            _grant(person, company, project.name, ability)
    frappe.db.commit()

    saved = {key: getattr(frappe.local, key, None) for key in ("session", "session_obj", "request", "request_ip", "form_dict")}
    sid = None
    try:
        frappe.local.request = Request.from_values(path="/explicit-ricky-fixture", method="POST")
        frappe.local.request_ip = "127.0.0.1"
        frappe.local.form_dict = frappe._dict()
        frappe.set_user(user)
        session = Session(user=user, full_name="Explicit Ricky fixture", user_type="System User")
        frappe.local.session_obj = session
        sid = session.sid
        content = f"Rickyfixture{marker}: the review meeting is Thursday.\n".encode()
        uploaded = upload_document(company=company, project=project.name, title="Explicit Ricky source " + marker,
                                   filename="explicit-ricky-fixture.txt", content=content, byte_length=len(content),
                                   sha256=hashlib.sha256(content).hexdigest(), operation_id=str(uuid4()))
        frappe.db.commit()

        def new_service(backend=None):
            adapter = FixtureAdapter()
            def respond(request):
                citation = request.context[1]["data"]["citations"][0]
                if not any(item["tool"] == "task.propose" for item in request.context):
                    return ModelResponse("", tool_requests=({"name": "task.propose", "arguments": {
                        "subject": "Explicit fixture: prepare review meeting", "description": "Review the cited Thursday meeting source.",
                        "citation_ids": [citation["citation_id"]]}},), model_version="explicit-test-fixture")
                return ModelResponse("The explicit fixture source states Thursday.", (citation["citation_id"],), model_version="explicit-test-fixture")
            adapter.response = respond
            return RickyService(FrappeStore(worker=True), backend or FrappeBackend(), adapter)

        def prepare(service):
            run = service.start(company, project.name, f"When is Rickyfixture{marker} review meeting?", str(uuid4()))
            frappe.db.commit()
            service.process(run["id"])
            return service.get_run(run["id"])

        # Establish a nonlocking RR snapshot, then update the run from an
        # independent connection. A locking read must return the newer JSON,
        # including the cancellation fencing token, rather than the old snapshot.
        snapshot_service = new_service()
        snapshot_run = snapshot_service.start(company, project.name, "Explicit current locking read fixture", str(uuid4()))
        frappe.db.commit()
        before = snapshot_service.store.get("run", snapshot_run["id"])
        assert before["status"] == "queued" and before["lease_token"] == 0
        site = frappe.local.site
        update_errors = []
        def cancel_from_other_connection():
            try:
                frappe.init(site=site)
                frappe.connect()
                store = FrappeStore()
                current = store.get("run", snapshot_run["id"], lock=True)
                current.update(status="cancelled", cancel_requested=True, lease_token=current["lease_token"] + 1)
                store.save("run", current)
                frappe.db.commit()
            except BaseException as error:
                update_errors.append(str(error))
            finally:
                frappe.destroy()
        updater = threading.Thread(target=cancel_from_other_connection, daemon=True)
        updater.start()
        updater.join(25)
        assert not updater.is_alive(), "Concurrent run update did not complete"
        assert not update_errors, update_errors
        locking_snapshot_conflict = False
        try:
            current = snapshot_service.store.get("run", snapshot_run["id"], lock=True)
        except frappe.QueryDeadlockError:
            # This pinned MariaDB build rejects upgrading a superseded RR
            # snapshot (1020). It must never return the old fencing state;
            # the fresh transaction reads the committed cancellation.
            locking_snapshot_conflict = True
            frappe.db.rollback()
            current = snapshot_service.store.get("run", snapshot_run["id"], lock=True)
        assert current["status"] == "cancelled" and current["cancel_requested"] and current["lease_token"] == 1, current
        frappe.db.rollback()

        service = new_service()
        run = prepare(service)
        assert run["status"] == "waiting-for-review", run
        assert run["citations"][0]["source_sha256"] == hashlib.sha256(content).hexdigest()
        # A fresh repository/service reads committed records, not process memory.
        restored = new_service().get_run(run["id"])
        assert restored["answer"] == run["answer"]
        operation = str(uuid4())
        receipt = service.commit_proposal(run["proposal_ids"][0], 1, operation)
        frappe.db.commit()
        replay = new_service().commit_proposal(run["proposal_ids"][0], 1, operation)
        assert receipt == replay
        assert frappe.db.count("Task", {"project": project.name}) == 1

        # Check generic-resource bypass even with ignore_permissions: controller
        # still requires the trusted command context.
        record = frappe.get_doc("Cipher Ricky Run", run["id"])
        try:
            record.save(ignore_permissions=True)
            raise AssertionError("Generic Ricky write bypass was accepted")
        except DomainError as error:
            assert error.code == "governed_write_required"
            frappe.db.rollback()

        timeout_service = new_service()
        fixture_clock = [utcnow()]
        timeout_service.clock = lambda: fixture_clock[0]
        definition, handler = timeout_service.registry._tools["task.propose"]
        def timeout_after_insert(execution, arguments):
            output = handler(execution, arguments)
            fixture_clock[0] += timedelta(seconds=16)
            return output
        timeout_service.registry._tools["task.propose"] = definition, timeout_after_insert
        timeout_run = timeout_service.start(company, project.name, f"When is Rickyfixture{marker} review meeting?", str(uuid4()))
        frappe.db.commit()
        timeout_service.process(timeout_run["id"])
        timeout_result = new_service().get_run(timeout_run["id"])
        assert timeout_result["status"] == "failed" and timeout_result["error"]["code"] == "resource_limit"
        assert frappe.db.count("Cipher Proposed Change", {"run_id": timeout_run["id"]}) == 0
        assert frappe.db.count("Cipher Tool Invocation", {"run_id": timeout_run["id"]}) == 2
        assert frappe.db.count("Cipher Ricky Step", {"run_id": timeout_run["id"], "status": "failed"}) == 1

        # The queue outage occurs in the actual after-commit callback. It must
        # leave a readable queued run for the DB-driven recovery dispatcher.
        from unittest.mock import patch
        queued_service = new_service()
        queued = queued_service.start(company, project.name, f"When is Rickyfixture{marker} review meeting?", str(uuid4()))
        with patch.object(frappe, "enqueue", side_effect=ConnectionError("explicit queue-outage fixture")) as enqueue:
            _dispatch(queued["id"])
            assert enqueue.call_count == 0
            frappe.db.commit()
            assert enqueue.call_count == 1
        assert new_service().get_run(queued["id"])["status"] == "queued"
        queued_service.process(queued["id"])
        assert new_service().get_run(queued["id"])["status"] == "waiting-for-review"

        second = prepare(new_service())
        duty = frappe.db.get_value("Cipher Project Duty", {"person": person, "project": project.name, "ability": "document.read"}, "name")
        site = frappe.local.site
        revocation_errors = []
        revoked = threading.Event()
        trigger = threading.Event()

        def revoke():
            try:
                frappe.init(site=site)
                frappe.connect()
                frappe.set_user("Administrator")
                if not trigger.wait(20):
                    raise RuntimeError("Acceptance did not reach the effect lock boundary")
                with trusted_write():
                    row = frappe.get_doc("Cipher Project Duty", duty)
                    row.active = 0
                    row.save(ignore_permissions=True)
                frappe.db.commit()
            except BaseException as error:
                revocation_errors.append(str(error))
            finally:
                frappe.destroy()
                revoked.set()

        thread = threading.Thread(target=revoke, daemon=True)
        thread.start()

        class RevocationBoundaryBackend(FrappeBackend):
            def lock_scope(self, authority, ability):
                # The engine has already read the old source/authority snapshot.
                # A separate DB transaction commits a revocation before locking.
                trigger.set()
                if not revoked.wait(25):
                    raise RuntimeError("Concurrent revocation did not complete")
                if revocation_errors:
                    raise RuntimeError(revocation_errors[0])
                super().lock_scope(authority, ability)

        race_service = new_service(RevocationBoundaryBackend())
        refused = None
        serialization_conflict = False
        try:
            race_service.commit_proposal(second["proposal_ids"][0], 1, str(uuid4()))
            raise AssertionError("Concurrent source-access revocation was ignored")
        except frappe.QueryDeadlockError:
            # MariaDB may reject upgrading the old RR snapshot with error 1020.
            # Start a fresh transaction and prove current authority refuses it.
            serialization_conflict = True
            frappe.db.rollback()
            try:
                new_service().commit_proposal(second["proposal_ids"][0], 1, str(uuid4()))
                raise AssertionError("Fresh retry ignored committed source-access revocation")
            except (DomainError, RickyError) as error:
                refused = error.code
                assert error.code in {"capability_denied", "not_found", "stale_authority"}, error.code
        except (DomainError, RickyError) as error:
            refused = error.code
            assert error.code in {"capability_denied", "not_found", "stale_authority"}, error.code
        finally:
            frappe.db.rollback()
            trigger.set()
            thread.join(30)
        assert frappe.db.count("Task", {"project": project.name}) == 1

        return {"label": "explicit-test-fixture-adapter-with-real-frappe-storage",
                "live_model_qualified": False, "project": project.name, "document": uploaded["document"]["id"],
                "run": run["id"], "task": receipt["task"]["id"], "cited_answer_persisted": True,
                "task_replay_single_effect": True, "generic_write_denied": True,
                "locking_read_preexisting_snapshot_safe": True,
                "locking_read_proof": {"before": {"status": before["status"], "lease_token": before["lease_token"]},
                                       "after": {"status": current["status"], "lease_token": current["lease_token"]},
                                       "serialization_conflict": locking_snapshot_conflict},
                "tool_failure_atomic_rollback": True,
                "deferred_queue_failure_preserves_run": True,
                "database_serialization_conflict": serialization_conflict,
                "concurrent_document_revocation_denied": refused}
    finally:
        frappe.db.rollback()
        if sid:
            delete_session(sid, user=user, reason="Explicit Ricky fixture acceptance ended")
            frappe.db.commit()
        for key, value in saved.items():
            setattr(frappe.local, key, value)
        frappe.set_user("Administrator")

"""Opt-in real MariaDB/Redis/worker acceptance of the local-only R0 outbox.

bench --site cipher.localhost execute cipher_aec.tests.test_outbox_acceptance.run_acceptance

Only this test module injects process interruption and delayed old workers. It is
not whitelisted and does not register any normal UI capability or provider.
"""
from datetime import timedelta
import json
import os
import secrets
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch
from uuid import uuid4


def _record_workhorse(operation, function):
    from frappe.utils.background_jobs import get_redis_conn
    get_redis_conn().hset("cipher:explicit-outbox:process:" + operation, mapping={
        "workhorse_pid": os.getpid(), "parent_pid": os.getppid(), "function": function})
    get_redis_conn().expire("cipher:explicit-outbox:process:" + operation, 600)


def run_isolated_worker(site, queue, name):
    """Dedicated test worker; no shared/default queue is consumed."""
    import frappe
    from frappe.utils.background_jobs import get_redis_conn
    from rq import Worker
    frappe.init(site=site)
    connection = get_redis_conn()
    frappe.destroy()
    Worker([queue], name=name, connection=connection).work(with_scheduler=False, logging_level="WARNING")


def interrupt_after_claim(operation):
    """Actual RQ workhorse exits after the outbox's first durable claim commit."""
    import frappe
    from cipher_aec.integrations.outbox import deliver
    _record_workhorse(operation, "interrupt_after_claim")
    commit = frappe.db.commit
    def interrupted_commit(*args, **kwargs):
        commit(*args, **kwargs)
        os._exit(73)
    with patch.object(frappe.db, "commit", interrupted_commit):
        deliver(operation)


def interrupt_after_local_effect(operation):
    """Lose the actual worker after Task insertion but before its DB commit."""
    from cipher_aec.integrations.outbox import deliver
    from cipher_aec.projects import service
    _record_workhorse(operation, "interrupt_after_local_effect")
    create_task = service.create_task
    def interrupted_effect(*args, **kwargs):
        create_task(*args, **kwargs)
        os._exit(74)
    with patch.object(service, "create_task", interrupted_effect):
        deliver(operation)


def pause_after_claim(operation, barrier):
    """Keep an old real worker alive while another worker acquires a new fence."""
    import frappe
    from frappe.utils.background_jobs import get_redis_conn
    from cipher_aec.integrations.outbox import deliver
    redis = get_redis_conn()
    _record_workhorse(operation, "pause_after_claim")
    commit, claimed = frappe.db.commit, [False]
    def pausing_commit(*args, **kwargs):
        commit(*args, **kwargs)
        if not claimed[0]:
            claimed[0] = True
            redis.set(barrier + ":ready", "1", ex=120)
            deadline = time.monotonic() + 90
            while not redis.get(barrier + ":release"):
                if time.monotonic() > deadline:
                    raise RuntimeError("Explicit old-worker barrier timed out")
                time.sleep(0.1)
    with patch.object(frappe.db, "commit", pausing_commit):
        return deliver(operation)


def run_acceptance():
    import frappe
    from frappe.utils import now_datetime
    from frappe.utils.background_jobs import get_job, get_redis_conn
    from cipher_aec.api.contracts import digest, version_of
    from cipher_aec.api.errors import DomainError
    from cipher_aec.governance.commands import run_command
    from cipher_aec.governance.context import assert_synthetic_site, current_actor, trusted_write
    from cipher_aec.install import _binding, _grant, _person, _user, set_synthetic_duty
    from cipher_aec.integrations import outbox

    assert_synthetic_site()
    if frappe.session.user != "Administrator":
        raise RuntimeError("Explicit outbox fixture requires bench synthetic Administrator context")
    if frappe.conf.get("cipher_execution_quarantined") not in (None, False, 0, "0", "false"):
        raise RuntimeError("The acceptance site is already execution-quarantined")
    company = "Cipher Synthetic Company"
    if not frappe.db.exists("Company", company):
        raise RuntimeError("Seed the synthetic site first")
    marker = uuid4().hex[:12]
    user, person = f"outbox.fixture.{marker}@cipher.example", "OUTBOX-FIXTURE-" + marker
    checks, operations, barriers = [], [], []
    result = {"schema": "cipher.r0.outbox-acceptance.v1", "status": "running",
              "label": "explicit-local-task-outbox-real-mariadb-redis-workers",
              "external_provider_qualified": False, "checks": checks, "operations": operations,
              "fault_injection": "Test-only RQ workhorse exits and Redis barriers; production delivery code unchanged."}
    with trusted_write():
        _person(person, "Explicit outbox acceptance fixture")
        _user(user, "Explicit outbox fixture", secrets.token_urlsafe(32))
        _binding(user, person)
        project = frappe.get_doc({"doctype": "Project", "company": company,
            "project_name": "Outbox acceptance fixture " + marker, "status": "Open"}).insert(ignore_permissions=True)
        for ability in ("project.read", "task.create"):
            _grant(person, company, project.name, ability)
    frappe.db.commit()
    result.update(project=project.name, user=user)
    frappe.set_user(user)
    redis = get_redis_conn()
    from rq import Queue
    from frappe.utils.background_jobs import create_job_id
    queues = {key: "cipher-explicit-outbox-" + marker + "-" + key for key in ("a", "b")}
    workers, logs = [], []
    owned = set()
    original_enqueue = frappe.enqueue
    for key, queue_name in queues.items():
        worker_name = "cipher-outbox-fixture-" + marker + "-" + key
        log = tempfile.TemporaryFile(mode="w+b")
        code = "from cipher_aec.tests.test_outbox_acceptance import run_isolated_worker;run_isolated_worker(*" + repr((frappe.local.site, queue_name, worker_name)) + ")"
        process = subprocess.Popen([sys.executable, "-c", code], cwd=os.getcwd(), stdout=log, stderr=log, start_new_session=True)
        workers.append((process, worker_name, queue_name))
        logs.append(log)
    result["isolated_workers"] = [{"pid": proc.pid, "name": name, "queue": queue} for proc, name, queue in workers]

    def isolated_enqueue(method, queue="short", job_id=None, deduplicate=False, timeout=120, **kwargs):
        operation = kwargs.get("operation")
        if operation not in owned:
            raise RuntimeError("Acceptance refuses to publish an unrelated operation")
        if deduplicate:
            existing = get_job(job_id)
            if existing and existing.get_status(refresh=True).value in ("queued", "started"):
                return None
            if existing:
                existing.delete()
        selected = queues["b" if queue == "acceptance-b" else "a"]
        return Queue(selected, connection=redis).enqueue_call("frappe.utils.background_jobs.execute_job",
            kwargs={"site": frappe.local.site, "user": frappe.session.user, "method": method,
                    "event": None, "job_name": method, "is_async": True, "kwargs": kwargs},
            timeout=timeout, result_ttl=300, failure_ttl=300, job_id=create_job_id(job_id))

    routing = patch.object(frappe, "enqueue", isolated_enqueue)
    routing.start()

    def wait(predicate, label, timeout=40):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            frappe.db.rollback()  # Fresh authoritative read, not an old RR snapshot.
            value = predicate()
            if value:
                return value
            time.sleep(0.15)
        raise AssertionError("Timed out waiting for " + label)

    def state(name):
        return frappe.db.get_value("Cipher Integration Operation", name,
            ["name", "state", "fencing_token", "attempt_count", "effect_operation_id", "result_json", "last_error_code"], as_dict=True)

    def job_finished(job_id, expected="finished"):
        job = get_job(job_id)
        if job and job.get_status(refresh=True).value == expected:
            return job
        return None

    def check(name, **details):
        checks.append({"name": name, "status": "passed", **details})

    def task_count(subject):
        return frappe.db.count("Task", {"project": project.name, "subject": subject})

    def enqueue(label, automatic=True):
        subject = f"Explicit outbox {label} {marker}"
        logical_id = "outbox-acceptance-" + uuid4().hex
        command_id = str(uuid4())
        payload = {"expected_version": version_of(frappe.get_doc("Project", project.name)),
                   "subject": subject, "description": "Explicit local-only R0 acceptance fixture."}
        def effect(actor, locked):
            name = outbox.enqueue_operation(actor=actor, company=company, project=project.name,
                logical_id=logical_id, kind="project.task.create", payload=payload)
            # The canonical logical ID must not create two durable deliveries.
            replay = outbox.enqueue_operation(actor=actor, company=company, project=project.name,
                logical_id=logical_id, kind="project.task.create", payload=payload)
            assert replay == name
            return {"integration_operation": name}
        response = run_command(company=company, project=project.name, operation_id=command_id,
            command="test.outbox.acceptance.enqueue.v1", payload={"logical_id": logical_id, "payload": payload},
            ability="task.create", effect=effect)
        name = response["integration_operation"]
        owned.add(name)
        assert task_count(subject) == 0
        if automatic:
            frappe.db.commit()
        else:
            # An explicit queue-publication outage after actual MariaDB commit.
            # The durable row remains real; only the queue boundary is faulted.
            with patch.object(frappe, "enqueue", side_effect=ConnectionError("explicit outbox publication interruption")):
                frappe.db.commit()
        operations.append({"name": name, "label": label, "logical_id": logical_id, "subject": subject})
        return name, subject

    def expire_claim(name):
        frappe.set_user("Administrator")
        with trusted_write():
            doc = frappe.get_doc("Cipher Integration Operation", name, for_update=True)
            assert doc.state == "Claimed"
            doc.lease_until = now_datetime() - timedelta(seconds=1)
            doc.save(ignore_permissions=True)
        frappe.db.commit()
        frappe.set_user(user)

    def publish_test_worker(function, name, **kwargs):
        job_id = "outbox-explicit-" + uuid4().hex
        frappe.enqueue("cipher_aec.tests.test_outbox_acceptance." + function, queue="acceptance-b",
                       operation=name, job_id=job_id, timeout=120, **kwargs)
        return job_id

    try:
        # Delivery occurs only in the actual Redis worker, never by a direct helper.
        name, subject = enqueue("normal")
        first = wait(lambda: state(name) if state(name).state == "Succeeded" else None, "normal Task delivery")
        canonical_job = wait(lambda: job_finished("cipher-outbox-" + name), "canonical Redis job finish")
        assert task_count(subject) == 1 and first.attempt_count == 1
        receipt = json.loads(first.result_json)
        assert frappe.db.count("Cipher Command Receipt", {"operation_id": first.effect_operation_id, "person": person}) == 1
        check("durable_enqueue_actual_redis_worker", operation=name, job_id=canonical_job.id,
              task=receipt["task"]["id"], task_count=1, delivery_attempts=1)

        repeated_id = "outbox-repeat-" + uuid4().hex
        frappe.enqueue("cipher_aec.integrations.outbox.deliver", queue="short", operation=name, job_id=repeated_id)
        wait(lambda: job_finished(repeated_id), "repeated Redis delivery")
        assert task_count(subject) == 1 and state(name).attempt_count == 1
        check("repeated_delivery_preserves_one_effect", operation=name, task_count=1, delivery_attempts=1)

        name, subject = enqueue("queue-publication-recovery", automatic=False)
        assert state(name).state == "Queued" and task_count(subject) == 0
        assert get_job("cipher-outbox-" + name) is None
        dispatched = outbox.dispatch_pending()
        assert dispatched >= 1
        recovered = wait(lambda: state(name) if state(name).state == "Succeeded" else None, "DB dispatch recovery")
        assert task_count(subject) == 1
        check("queue_publication_interruption_database_recovery", operation=name, dispatcher_selected=dispatched,
              final_state=recovered.state, task_count=1)

        for helper, label in (("interrupt_after_claim", "crash-after-claim"),
                              ("interrupt_after_local_effect", "crash-after-uncommitted-task")):
            name, subject = enqueue(label, automatic=False)
            fault_job = publish_test_worker(helper, name)
            wait(lambda: job_finished(fault_job, "failed"), "actual interrupted RQ workhorse")
            claimed = state(name)
            assert claimed.state == "Claimed" and claimed.fencing_token == 1 and task_count(subject) == 0
            assert frappe.db.count("Cipher Command Receipt", {"operation_id": claimed.effect_operation_id, "person": person}) == 0
            expire_claim(name)
            outbox.dispatch_pending()
            recovered = wait(lambda: state(name) if state(name).state == "Succeeded" else None, "expired claim recovery")
            assert task_count(subject) == 1 and recovered.fencing_token == 2 and recovered.attempt_count == 2
            assert frappe.db.count("Cipher Command Receipt", {"operation_id": recovered.effect_operation_id, "person": person}) == 1
            assert frappe.db.count("Cipher History Event", {"operation_id": recovered.effect_operation_id, "project": project.name}) == 1
            check(label + "_recovered_once", operation=name, fault_job=fault_job, pre_recovery_task_count=0,
                  final_task_count=1, final_fence=2, final_claim_count=2, effect_receipts=1, history_events=1)

        name, subject = enqueue("old-worker-fencing", automatic=False)
        barrier = "cipher:explicit-outbox:" + uuid4().hex
        barriers.append(barrier)
        old_job = publish_test_worker("pause_after_claim", name, barrier=barrier)
        wait(lambda: redis.get(barrier + ":ready"), "old claimant durable pause")
        assert state(name).fencing_token == 1 and task_count(subject) == 0
        expire_claim(name)
        outbox.dispatch_pending()
        recovered = wait(lambda: state(name) if state(name).state == "Succeeded" else None, "replacement claimant effect")
        assert recovered.fencing_token == 2 and task_count(subject) == 1
        redis.set(barrier + ":release", "1", ex=120)
        old_worker = wait(lambda: job_finished(old_job), "superseded old worker completion")
        old_result = old_worker.return_value()
        assert old_result == {"state": "superseded"}, old_result
        assert task_count(subject) == 1 and state(name).fencing_token == 2
        check("late_worker_rejected_by_actual_fence", operation=name, old_worker_result=old_result,
              final_fence=2, task_count=1)

        name, subject = enqueue("revoked-current-duty", automatic=False)
        frappe.set_user("Administrator")
        set_synthetic_duty(user, project.name, "task.create", 0)
        frappe.db.commit()
        frappe.set_user(user)
        outbox._schedule(name)
        refused = wait(lambda: state(name) if state(name).state == "Failed" else None, "current duty refusal")
        assert refused.last_error_code == "capability_denied" and task_count(subject) == 0
        assert frappe.db.count("Cipher Command Receipt", {"operation_id": refused.effect_operation_id, "person": person}) == 0
        check("current_permission_revocation_prevents_worker_effect", operation=name,
              final_state=refused.state, code=refused.last_error_code, task_count=0, effect_receipts=0)
        frappe.set_user("Administrator")
        set_synthetic_duty(user, project.name, "task.create", 1)
        frappe.db.commit()
        frappe.set_user(user)

        name, subject = enqueue("restore-quarantine", automatic=False)
        old_quarantine = frappe.conf.get("cipher_execution_quarantined")
        frappe.conf.cipher_execution_quarantined = 1
        try:
            assert outbox.dispatch_pending() == 0
            outbox._schedule(name)
            assert get_job("cipher-outbox-" + name) is None
            try:
                outbox.deliver(name)
                raise AssertionError("Quarantined restored deployment executed a delivery")
            except DomainError as error:
                assert error.code == "execution_quarantined"
            assert state(name).state == "Queued" and task_count(subject) == 0
            check("restore_quarantine_blocks_dispatch_publication_and_claim", operation=name,
                  final_state="Queued", redis_job_created=False, task_count=0,
                  scope="Actual site process configuration guard; no global site toggle or provider reconciliation claim.")
        finally:
            frappe.conf.cipher_execution_quarantined = old_quarantine
        outbox._schedule(name)
        wait(lambda: state(name) if state(name).state == "Succeeded" else None, "permitted local dispatch after quarantine fixture")
        assert task_count(subject) == 1
        check("explicit_local_resume_after_quarantine_guard", operation=name, task_count=1)

        result["status"] = "passed"
        result["qualified"] = {"database": "MariaDB canonical rows", "dispatch": "Redis RQ dedicated test workers using Frappe execute_job and unchanged outbox handler",
            "effect": "one local ERPNext Task per logical effect", "external_provider": False,
            "restore_policy": "guard only; real restored-volume reconciliation remains a separate operational gate"}
        result["final_task_count"] = frappe.db.count("Task", {"project": project.name})
        assert result["final_task_count"] == 6
    except Exception as error:
        result["status"] = "failed"
        result["failure"] = {"type": type(error).__name__, "message": str(error)[:500]}
        raise
    finally:
        frappe.db.rollback()
        for barrier in barriers:
            redis.set(barrier + ":release", "1", ex=120)
        result["workhorse_processes"] = []
        for operation in owned:
            info = redis.hgetall("cipher:explicit-outbox:process:" + operation)
            if info:
                decoded = {key.decode(): value.decode() for key, value in info.items()}
                decoded["operation"] = operation
                result["workhorse_processes"].append(decoded)
                assert int(decoded["parent_pid"]) in {proc.pid for proc, _, _ in workers}
        routing.stop()
        for process, _, _ in workers:
            process.terminate()
        for process, _, _ in workers:
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        result["isolated_workers_stopped"] = all(proc.poll() is not None for proc, _, _ in workers)
        for log in logs:
            log.close()
        frappe.set_user("Administrator")
    return result


def readback(project):
    """Read-only independent process evidence after dedicated workers have stopped."""
    import frappe
    import erpnext
    from frappe.utils.background_jobs import get_redis_conn
    from cipher_aec.governance.context import assert_synthetic_site
    assert_synthetic_site()
    if frappe.session.user != "Administrator":
        raise RuntimeError("Explicit fixture readback requires bench Administrator context")
    name = frappe.db.get_value("Project", project, "project_name")
    if not name or not name.startswith("Outbox acceptance fixture "):
        raise RuntimeError("Readback requires an isolated outbox fixture project")
    rows = frappe.get_all("Cipher Integration Operation", filters={"project": project},
        fields=["name", "state", "effect_operation_id", "fencing_token", "attempt_count", "last_error_code", "result_json"],
        order_by="creation asc")
    evidence = []
    for row in rows:
        result = json.loads(row.result_json) if row.result_json else {}
        evidence.append({"id": row.name, "state": row.state, "fencing_token": row.fencing_token,
            "claim_count": row.attempt_count, "last_error_code": row.last_error_code,
            "effect_operation_id": row.effect_operation_id, "task": result.get("task", {}).get("id"),
            "command_receipts": frappe.db.count("Cipher Command Receipt", {"operation_id": row.effect_operation_id}),
            "history_events": frappe.db.count("Cipher History Event", {"operation_id": row.effect_operation_id, "project": project}),
            "delivery_attempts": frappe.get_all("Cipher Delivery Attempt", filters={"operation": row.name},
                fields=["fencing_token", "outcome"], order_by="creation asc")})
    return {"project": project, "task_count": frappe.db.count("Task", {"project": project}),
            "operations": evidence, "versions": {"frappe": frappe.__version__, "erpnext": erpnext.__version__,
            "mariadb": frappe.db.sql("SELECT VERSION()")[0][0], "redis": get_redis_conn().info("server")["redis_version"]}}

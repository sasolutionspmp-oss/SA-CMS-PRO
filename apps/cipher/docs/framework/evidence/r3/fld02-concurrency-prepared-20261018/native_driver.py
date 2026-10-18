"""Default-disabled FLD02 two-process native trial; prepared, native UNRUN.

The local root supplies every business identifier and private attestation. This
program never seeds, retries a command, clears a reservation, or cleans a site.
Only --reconcile may read the original UUID after an uncertain attempt.
"""
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import time
import types


def _source_module(name):
    """Load our small pinned helpers from source, never pre-existing bytecode."""
    path = Path(__file__).absolute().parent / (name + ".py")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > 1024 * 1024:
            raise ValueError("bounded regular helper source required")
        with os.fdopen(fd, "rb", closefd=False) as handle:
            content = handle.read(1024 * 1024 + 1)
        if len(content) != info.st_size:
            raise ValueError("helper source changed")
    finally:
        os.close(fd)
    module = types.ModuleType(name)
    module.__file__ = str(path)
    sys.modules[name] = module
    exec(compile(content, str(path), "exec"), module.__dict__)
    return module


lease_guard = _source_module("lease")


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def identity(admission):
    lease, request = admission["lease"], admission["request"]
    return {"run_id": lease["run_id"], "epoch": lease["epoch"],
            "runtime_id": lease["runtime_id"], "operation_uuid": request["operation_uuid"],
            "body_sha256": request["body_sha256"], "request_sha256": lease_guard.sha_json(request),
            "scope": lease["scope"]}


def exclusive_json(path, value):
    """An fsynced O_EXCL reservation; existing/partial bytes remain evidence."""
    path = Path(path)
    lease_guard._private_parent(path)
    data = (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()
    _require(len(data) <= lease_guard.MAX_JSON, "reservation exceeds bound")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "wb", closefd=False) as handle:
            handle.write(data)
            handle.flush()
            os.fsync(fd)
    finally:
        os.close(fd)
    parent_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(parent_fd)
    finally:
        os.close(parent_fd)


def reservation_path(admission):
    lease = admission["lease"]
    # Native command UUIDs are scoped to Person, across projects/commands.
    key = {"person": lease["scope"]["users"][0]["person"],
           "operation_uuid": admission["request"]["operation_uuid"]}
    return Path(lease["artifact_dir"]) / ("operation-" + lease_guard.sha_json(key) + ".json")


def barrier(admission, ready, prepared):
    """Pure check: exact request/epoch plus distinct observed physical IDs."""
    expected = identity(admission)
    _require(set(ready) == set(prepared) == {"A", "B"}, "exact two worker roles required")
    ids = {}
    for role in ("A", "B"):
        row, prep = ready[role], prepared[role]
        for key in ("run_id", "epoch", "runtime_id", "operation_uuid", "body_sha256"):
            _require(row.get(key) == expected[key] and prep.get(key) == expected[key], "barrier identity differs")
        _require(row.get("schema") == "cipher.fld02.native.concurrent.ready.v1"
                 and prep.get("schema") == "cipher.fld02.native.concurrent.prepared.v1"
                 and row.get("role") == prep.get("role") == role, "barrier role/schema differs")
        actual_id = row.get("connection_id")
        _require(type(actual_id) is int and actual_id > 0
                 and type(prep.get("connection_id")) is int and prep.get("connection_id") == actual_id,
                 "observed ready/prepared physical connection ID required")
        _require(row.get("site") == admission["lease"]["site"]
                 and row.get("database_name") == admission["lease"]["database_name"]
                 and row.get("frappe_version") == "16.52.0"
                 and "MariaDB" in str(row.get("version"))
                 and str(row.get("isolation")).upper().replace("_", "-") == "READ-COMMITTED",
                 "observed native runtime differs")
        ids[role] = actual_id
    _require(ids["A"] != ids["B"], "two independent physical connections required")
    return {"schema": "cipher.fld02.native.concurrent.barrier.v1",
            **{k: expected[k] for k in ("run_id", "epoch", "operation_uuid", "body_sha256")},
            "connections": ids}


def _spawn(admission, role, directory):
    lease_guard.recheck(admission)
    command = [admission["lease"]["python_executable"], "-B", str(Path(__file__).absolute()),
               "--execute", "--lease", admission["lease_path"], "--request", admission["request_path"],
               "--worker", role, "--directory", str(directory)]
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONNOUSERSITE="1")
    # Capture only in the private run folder; never relay native exceptions/secrets.
    with open(directory / (role + "-stdout.log"), "xb", opener=_private_opener) as stdout:
        with open(directory / (role + "-stderr.log"), "xb", opener=_private_opener) as stderr:
            return subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr,
                                    env=env, close_fds=True, start_new_session=True)


def _private_opener(path, flags):
    return os.open(path, flags | os.O_NOFOLLOW, 0o600)


def _stop_owned(children):
    # Termination does not establish transaction outcome. Do not touch a DB/site.
    for process in children.values():
        if process.poll() is None:
            process.terminate()
    until = time.monotonic() + 2
    while any(process.poll() is None for process in children.values()) and time.monotonic() < until:
        time.sleep(0.05)
    for process in children.values():
        if process.poll() is None:
            process.kill()
    for process in children.values():
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            pass


def _wait_all(admission, children, tick=None):
    until = time.monotonic() + admission["lease"]["max_duration_seconds"]
    while True:
        lease_guard.recheck(admission)
        _require(time.monotonic() < until, "finite parent deadline elapsed")
        if tick:
            tick()
        if all(process.poll() is not None for process in children.values()):
            return
        time.sleep(0.1)


def execute(admission):
    lease_guard.recheck(admission)
    directory = Path(admission["lease"]["artifact_dir"]) / admission["lease"]["run_id"]
    directory.mkdir(mode=0o700, exist_ok=False)
    receipt = {"schema": "cipher.fld02.native.concurrent.parent.v1", **identity(admission),
               "state": "incomplete", "outcome": "unknown", "attempts": 1, "events": []}
    children = {}

    def record(phase, **extra):
        receipt["events"].append({"phase": phase, "monotonic_ns": time.monotonic_ns(), **extra})
        lease_guard.atomic_json(directory / "run.json", receipt)

    # Immutable, global across run IDs. A failed reservation does not start workers.
    exclusive_json(reservation_path(admission), {**receipt, "directory": str(directory)})
    try:
        exclusive_json(directory / "admission.json", admission)
        record("reserved")
        for role in ("A", "B"):
            children[role] = _spawn(admission, role, directory)
            record("spawned", role=role, pid=children[role].pid)
        released = False

        def release():
            nonlocal released
            if released:
                return
            paths = {role: {kind: directory / (kind + "-" + role + ".json")
                            for kind in ("ready", "prepared")} for role in ("A", "B")}
            if all(path.exists() for pair in paths.values() for path in pair.values()):
                ready = {role: lease_guard.private_json(str(paths[role]["ready"])) for role in paths}
                prepared = {role: lease_guard.private_json(str(paths[role]["prepared"])) for role in paths}
                go = barrier(admission, ready, prepared)
                lease_guard.recheck(admission)
                exclusive_json(directory / "go.json", go)
                released = True
                record("barrier_released", connections=go["connections"])
            elif any(process.poll() is not None for process in children.values()):
                raise ValueError("worker exited before complete barrier admission")

        _wait_all(admission, children, release)
        receipt["worker_results"] = {role: lease_guard.private_json(str(directory / ("result-" + role + ".json")))
                                     for role in children}
        receipt["state"] = "workers_finished_pending_root_review"
        # The driver records outcomes; only local qualification may accept proof.
        receipt["outcome"] = "reported_outcomes_require_review"
        record("workers_finished", exit_codes={r: p.returncode for r, p in children.items()})
    except Exception as error:
        receipt["error_type"] = type(error).__name__
        record("incomplete_unknown")
    finally:
        _stop_owned(children)
        record("retained_no_retry_no_cleanup")
    return receipt


def reconcile(admission):
    """A fresh lease may only observe the existing original operation."""
    lease_guard.recheck(admission)
    directory = Path(admission["lease"]["artifact_dir"]) / admission["lease"]["run_id"]
    original = lease_guard.private_json(str(directory / "run.json"))
    reserved = lease_guard.private_json(str(reservation_path(admission)))
    for key in ("run_id", "request_sha256", "operation_uuid", "body_sha256", "scope"):
        _require(original.get(key) == reserved.get(key) == identity(admission)[key], "original attempt request differs")
    observation = directory / ("reconcile-" + lease_guard.sha_json(admission["lease"])[:16])
    observation.mkdir(mode=0o700, exist_ok=False)
    exclusive_json(observation / "admission.json", admission)
    children = {}
    receipt = {"schema": "cipher.fld02.native.concurrent.parent-observation.v1", **identity(admission),
               "state": "incomplete", "outcome": "unknown_retained", "original_directory": str(directory)}
    try:
        children["OBSERVE"] = _spawn(admission, "OBSERVE", observation)
        _wait_all(admission, children)
        receipt["observation"] = lease_guard.private_json(str(observation / "result-OBSERVE.json"))
        receipt["state"] = "observed_pending_root_review"
    except Exception as error:
        receipt["error_type"] = type(error).__name__
    finally:
        _stop_owned(children)
        lease_guard.atomic_json(observation / "observation.json", receipt)
    return receipt


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="default disabled; requires private local-root lease")
    parser.add_argument("--lease")
    parser.add_argument("--request")
    parser.add_argument("--reconcile", action="store_true", help="observe original UUID only, never retry/clear reservation")
    parser.add_argument("--worker", choices=("A", "B", "OBSERVE"), help=argparse.SUPPRESS)
    parser.add_argument("--directory", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if not args.execute:
        print("DISABLED — prepared native concurrency checks are UNRUN")
        return 0
    try:
        if args.worker:
            _require(args.directory is not None, "private parent admission directory required")
            admission = lease_guard.private_json(str(Path(args.directory) / "admission.json"))
            lease_guard.recheck(admission)
            _require(admission["lease_path"] == args.lease and admission["request_path"] == args.request,
                     "child must retain original parent admission and deadline")
        else:
            admission = lease_guard.admit(args.lease, args.request, execute=True)
        _require(str(Path(sys.executable).resolve()) == admission["lease"]["python_executable"], "leased physical Python required")
        if args.worker:
            directory = Path(args.directory)
            root = Path(admission["lease"]["artifact_dir"]) / admission["lease"]["run_id"]
            _require(directory == root if args.worker != "OBSERVE" else directory.parent == root
                     and directory.name == "reconcile-" + lease_guard.sha_json(admission["lease"])[:16], "child directory differs")
            reserved = lease_guard.private_json(str(reservation_path(admission)))
            original = lease_guard.private_json(str(root / "run.json"))
            for key in ("run_id", "request_sha256", "operation_uuid", "body_sha256", "scope"):
                _require(original.get(key) == reserved.get(key) == identity(admission)[key], "child reservation request differs")
            exclusive_json(directory / ("started-" + args.worker + ".json"),
                           {**identity(admission), "state": "attempted", "outcome": "unknown"})
            _source_module("inventory")
            worker = _source_module("native_worker")
            result = worker.observe(admission, directory) if args.worker == "OBSERVE" else worker.run(admission, args.worker, directory)
        else:
            result = reconcile(admission) if args.reconcile else execute(admission)
        print(json.dumps({"state": result["state"], "outcome": result["outcome"], "native_acceptance": "UNREVIEWED"}))
        return 0 if result["state"] in ("workers_finished_pending_root_review", "observed_pending_root_review", "complete") else 2
    except Exception as error:
        print(json.dumps({"state": "refused_or_incomplete", "error_type": type(error).__name__}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

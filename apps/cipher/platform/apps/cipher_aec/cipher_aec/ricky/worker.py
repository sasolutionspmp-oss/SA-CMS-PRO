"""Restart-safe database-driven dispatch, independent of Redis delivery history."""

from .contracts import parse_time, utcnow
from .engine import ACTIVE


def process_run(run_id):
    if _quarantined():
        return {"status": "skipped", "code": "execution_quarantined"}
    from .api import build_service
    build_service(worker=True).process(run_id)


def recover_pending():
    if _quarantined():
        return {"status": "skipped", "code": "execution_quarantined"}
    from .api import _dispatch, build_service
    service = build_service(worker=True)
    for run in service.store.find("run", {"status": ["in", list(ACTIVE)]}, limit=100):
        lease = run.get("lease_expires_at")
        if not lease or parse_time(lease) <= utcnow():
            _dispatch(run["id"])


def _quarantined():
    from cipher_aec.governance.context import require_effects_enabled
    from cipher_aec.api.errors import DomainError
    try:
        require_effects_enabled()
        return False
    except DomainError as error:
        if error.code == "execution_quarantined":
            return True
        raise

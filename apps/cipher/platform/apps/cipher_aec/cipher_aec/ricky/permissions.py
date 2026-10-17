"""Company run data is exposed only through exact scoped service readers.

Native generic reads/counts are deliberately closed for Company orchestration
rows. Project native behavior is unchanged. This grants no API capability.
"""


def has_permission(doc=None, user=None, ptype=None):
    if doc is None:
        return None
    scope = doc.get("scope_type")
    return None if scope in (None, "", "Project") else False


def _project_only(doctype):
    # Every doctype here is a static server literal, never an RPC argument.
    return f"COALESCE(NULLIF(`tab{doctype}`.`scope_type`, ''), 'Project')='Project'"


def run_query(user=None):
    return _project_only("Cipher Ricky Run")


def step_query(user=None):
    return _project_only("Cipher Ricky Step")


def invocation_query(user=None):
    return _project_only("Cipher Tool Invocation")


def delegation_query(user=None):
    return _project_only("Cipher Delegation")


def artifact_query(user=None):
    return _project_only("Cipher Run Artifact")


def proposal_query(user=None):
    return _project_only("Cipher Proposed Change")

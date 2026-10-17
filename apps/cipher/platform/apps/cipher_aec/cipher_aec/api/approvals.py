from cipher_aec.governance import approvals as service
from .transport import endpoint


@endpoint()
def list_packets(company, project, limit=50, cursor=None, count_mode="none"):
    return service.list_packets(company, project, limit, cursor, count_mode)


@endpoint()
def read_packet(company, project, packet_id):
    return service.read_packet(company, project, packet_id)


@endpoint(methods=["POST"])
def request_project_status(company, project, status, operation_id, expected_version=None):
    return service.request_project_status(company, project, status, expected_version, operation_id)


@endpoint(methods=["POST"])
def decide_packet(company, project, packet_id, manifest_hash, decision, operation_id, reason=""):
    return service.decide_packet(company, project, packet_id, manifest_hash, decision, operation_id, reason)


@endpoint(methods=["POST"])
def execute_packet(company, project, packet_id, manifest_hash, operation_id):
    return service.execute_packet(company, project, packet_id, manifest_hash, operation_id)


@endpoint(methods=["POST"])
def withdraw_packet(company, project, packet_id, manifest_hash, operation_id, reason=""):
    return service.withdraw_packet(company, project, packet_id, manifest_hash, operation_id, reason)


@endpoint(methods=["POST"])
def request_action(company, project, action, subject_id, operation_id, expected_version=None):
    return service.request_action(company, project, action, subject_id, expected_version, operation_id)

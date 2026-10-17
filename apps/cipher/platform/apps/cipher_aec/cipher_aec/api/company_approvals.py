"""Company-only entry points into the canonical independent approval engine."""
from cipher_aec.governance import approvals as service
from .transport import endpoint

@endpoint()
def list_packets(company, limit=50, cursor=None, count_mode="none"):
    return service.list_packets(company, None, limit, cursor, count_mode, scope_type="Company")

@endpoint()
def read_packet(company, packet_id):
    return service.read_packet(company, None, packet_id, scope_type="Company")

@endpoint(methods=["POST"])
def request_action(company, action, subject_id, operation_id, expected_version=None):
    return service.request_action(company, None, action, subject_id, expected_version, operation_id, scope_type="Company")

@endpoint(methods=["POST"])
def decide_packet(company, packet_id, manifest_hash, decision, operation_id, reason=""):
    return service.decide_packet(company, None, packet_id, manifest_hash, decision, operation_id, reason, scope_type="Company")

@endpoint(methods=["POST"])
def execute_packet(company, packet_id, manifest_hash, operation_id):
    return service.execute_packet(company, None, packet_id, manifest_hash, operation_id, scope_type="Company")

@endpoint(methods=["POST"])
def withdraw_packet(company, packet_id, manifest_hash, operation_id, reason=""):
    return service.withdraw_packet(company, None, packet_id, manifest_hash, operation_id, reason, scope_type="Company")

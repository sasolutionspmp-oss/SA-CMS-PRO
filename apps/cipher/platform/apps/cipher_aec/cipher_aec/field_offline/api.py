"""Owned opt-in routes; shared registration stays a composition fragment."""
from cipher_aec.api.transport import endpoint
from . import service

@endpoint(methods=['POST'])
def register_device(company,project,operation_id,device_id,label):return service.register_device(company,project,operation_id,device_id,label)

@endpoint(methods=['POST'])
def revoke_device(company,project,operation_id,device_id,expected_version,reason):return service.revoke_device(company,project,operation_id,device_id,expected_version,reason)

@endpoint(methods=['POST'])
def stage_capture(company,project,operation_id,envelope):return service.stage_capture(company,project,operation_id,envelope)

@endpoint()
def get_capture(company,project,capture_id):return service.get_capture(company,project,capture_id)

@endpoint()
def inspect_capture(company,project,capture_id):return service.inspect_capture(company,project,capture_id)

@endpoint(methods=['POST'])
def apply_capture(company,project,operation_id,capture_id,expected_version):return service.apply_capture(company,project,operation_id,capture_id,expected_version)

@endpoint(methods=['POST'])
def discard_capture(company,project,operation_id,capture_id,expected_version,reason):return service.discard_capture(company,project,operation_id,capture_id,expected_version,reason)

@endpoint(methods=['POST'])
def resolve_capture(company,project,operation_id,capture_id,expected_version,replacement_envelope,reason):return service.resolve_capture(company,project,operation_id,capture_id,expected_version,replacement_envelope,reason)

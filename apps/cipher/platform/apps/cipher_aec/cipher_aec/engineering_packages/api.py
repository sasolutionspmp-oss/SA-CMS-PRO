"""Closed Project package endpoints; canonical services own all effects."""
from cipher_aec.api.transport import endpoint
from . import service

@endpoint(methods=["POST"])
def create_package(company, project, operation_id, definition):
    return service.create_package(company,project,operation_id,definition)

@endpoint(methods=["POST"])
def revise_package(company, project, operation_id, package_id, expected_version, definition):
    return service.revise_package(company,project,operation_id,package_id,expected_version,definition)

@endpoint(methods=["POST"])
def create_basis(company, project, operation_id, package_id, expected_version, definition, quantities, source_citations, drawing_references, artifacts):
    return service.create_basis(company,project,operation_id,package_id,expected_version,definition,quantities,source_citations,drawing_references,artifacts)

@endpoint(methods=["POST"])
def create_calculation(company, project, operation_id, package_id, expected_version, basis_revision, basis_digest, definition, input_keys, outputs, artifacts, predecessor=None):
    return service.create_calculation(company,project,operation_id,package_id,expected_version,basis_revision,basis_digest,definition,input_keys,outputs,artifacts,predecessor)

@endpoint(methods=["POST"])
def create_deliverable(company, project, operation_id, package_id, expected_version, basis_revision, basis_digest, definition, calculations, source_citations, drawing_references, artifacts, predecessor=None):
    return service.create_deliverable(company,project,operation_id,package_id,expected_version,basis_revision,basis_digest,definition,calculations,source_citations,drawing_references,artifacts,predecessor)

@endpoint()
def get_record(company, project, kind, record_id):
    return service.get_record(company,project,kind,record_id)

@endpoint()
def list_records(company, project, kind, parent_id=None, limit=25, cursor=None, count_mode='none'):
    return service.list_records(company,project,kind,parent_id,limit,cursor,count_mode)

@endpoint()
def list_people(company, project, role, limit=25, cursor=None, count_mode='none'):
    return service.list_people(company,project,role,limit,cursor,count_mode)

@endpoint()
def list_units(company, project, limit=25, cursor=None, count_mode='none'):
    return service.list_units(company,project,limit,cursor,count_mode)

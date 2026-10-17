"""Typed Project engineering endpoints; canonical writers own all effects."""
from cipher_aec.api.transport import endpoint
from . import service

@endpoint(methods=["POST"])
def create_rfi(company, project, operation_id, definition, source_citations, drawing_references):
    return service.create_rfi(company,project,operation_id,definition,source_citations,drawing_references)

@endpoint(methods=["POST"])
def revise_rfi(company, project, operation_id, rfi_id, expected_version, definition, source_citations, drawing_references):
    return service.revise_rfi(company,project,operation_id,rfi_id,expected_version,definition,source_citations,drawing_references)

@endpoint(methods=["POST"])
def create_response(company, project, operation_id, rfi_id, source_revision, expected_version, definition, source_citations, predecessor=None):
    return service.create_response(company,project,operation_id,rfi_id,source_revision,expected_version,definition,source_citations,predecessor)

@endpoint(methods=["POST"])
def create_submittal(company, project, operation_id, definition, artifacts, source_citations):
    return service.create_submittal(company,project,operation_id,definition,artifacts,source_citations)

@endpoint(methods=["POST"])
def revise_submission(company, project, operation_id, submittal_id, expected_version, definition, artifacts, source_citations):
    return service.revise_submission(company,project,operation_id,submittal_id,expected_version,definition,artifacts,source_citations)

@endpoint(methods=["POST"])
def create_disposition(company, project, operation_id, submittal_id, source_revision, expected_version, definition, source_citations, predecessor=None):
    return service.create_disposition(company,project,operation_id,submittal_id,source_revision,expected_version,definition,source_citations,predecessor)

@endpoint(methods=["POST"])
def create_transmittal(company, project, operation_id, subject_kind, subject_id, subject_digest, recipients, purpose, required_response):
    return service.create_transmittal(company,project,operation_id,subject_kind,subject_id,subject_digest,recipients,purpose,required_response)

@endpoint(methods=["POST"])
def close_rfi(company, project, operation_id, rfi_id, expected_version, official_response, reason):
    return service.close_rfi(company,project,operation_id,rfi_id,expected_version,official_response,reason)

@endpoint()
def get_record(company, project, kind, record_id):
    return service.get_record(company,project,kind,record_id)

@endpoint()
def list_records(company, project, kind, parent_id=None, limit=25, cursor=None, count_mode='none', subject_id=None):
    return service.list_records(company,project,kind,parent_id,limit,cursor,count_mode,subject_id)

@endpoint()
def list_people(company, project, limit=25, cursor=None, count_mode='none'):
    return service.list_people(company,project,limit,cursor,count_mode)

"""Typed canonical Project document-control endpoints."""
from cipher_aec.api.transport import endpoint
from . import service

@endpoint(methods=["POST"])
def set_rights(company, project, operation_id, document_id, expected_version, definition):
    return service.set_rights(company,project,operation_id,document_id,expected_version,definition)

@endpoint(methods=["POST"])
def create_library(company, project, operation_id, definition, artifact):
    return service.create_library(company,project,operation_id,definition,artifact)

@endpoint(methods=["POST"])
def revise_library(company, project, operation_id, library_id, expected_version, definition, artifact):
    return service.revise_library(company,project,operation_id,library_id,expected_version,definition,artifact)

@endpoint(methods=["POST"])
def create_adoption(company, project, operation_id, library_revision, library_digest, definition):
    return service.create_adoption(company,project,operation_id,library_revision,library_digest,definition)

@endpoint(methods=["POST"])
def create_issue_set(company, project, operation_id, definition, artifacts, adoptions):
    return service.create_issue_set(company,project,operation_id,definition,artifacts,adoptions)

@endpoint(methods=["POST"])
def create_transmittal(company, project, operation_id, issue_id, issue_digest, recipients, purpose, required_response):
    return service.create_transmittal(company,project,operation_id,issue_id,issue_digest,recipients,purpose,required_response)

@endpoint(methods=["POST"])
def record_evidence(company, project, operation_id, subject_kind, subject_id, subject_digest, statement, artifacts):
    return service.record_evidence(company,project,operation_id,subject_kind,subject_id,subject_digest,statement,artifacts)

@endpoint()
def get_record(company, project, kind, record_id):
    return service.get_record(company,project,kind,record_id)

@endpoint()
def list_records(company, project, kind, parent_id=None, limit=25, cursor=None, count_mode='none'):
    return service.list_records(company,project,kind,parent_id,limit,cursor,count_mode)

@endpoint()
def list_people(company, project, limit=25, cursor=None, count_mode='none'):
    return service.list_people(company,project,limit,cursor,count_mode)

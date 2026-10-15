"""Fixed authenticated company commercial draft RPCs."""
import json
from cipher_aec.api.transport import endpoint
from cipher_aec.api.errors import DomainError
from . import service


def _object(value):
    if isinstance(value, str):
        if len(value) > 500000:
            raise DomainError("invalid_commercial", "Commercial payload exceeds the supported limit.")
        try:
            value = json.loads(value)
        except ValueError:
            raise DomainError("invalid_commercial", "Use a JSON object.") from None
    if type(value) is not dict:
        raise DomainError("invalid_commercial", "Use a JSON object.")
    return value


def _integer(value):
    if type(value) is int:
        return value
    if type(value) is str and value.isdigit() and str(int(value)) == value:
        return int(value)
    raise DomainError("invalid_input", "Use an integer revision or limit.")


@endpoint(methods=["GET"])
def pursuits(company, limit=30, cursor=None, count_mode="none"):
    return service.list_records(company, "pursuit", _integer(limit), cursor, count_mode)


@endpoint(methods=["GET"])
def pursuit(company, pursuit_id):
    return service.get_pursuit(company, pursuit_id)


@endpoint(methods=["GET"])
def proposals(company, limit=30, cursor=None, count_mode="none"):
    return service.list_records(company, "proposal", _integer(limit), cursor, count_mode)


@endpoint(methods=["GET"])
def proposal(company, proposal_id):
    return service.get_proposal(company, proposal_id)


@endpoint(methods=["GET"])
def proposal_revision(company, revision_id):
    return service.get_revision(company, revision_id)


@endpoint(methods=["GET"])
def compare_revisions(company, proposal_id, left_revision, right_revision):
    return service.compare_revisions(company, proposal_id, left_revision, right_revision)


@endpoint(methods=["POST"])
def create_pursuit(company, party_type, party_id, fields, operation_id):
    return service.create_pursuit(company, party_type, party_id, _object(fields), operation_id)


@endpoint(methods=["POST"])
def update_pursuit(company, pursuit_id, expected_revision, fields, operation_id):
    return service.update_pursuit(company, pursuit_id, _integer(expected_revision), _object(fields), operation_id)


@endpoint(methods=["POST"])
def create_proposal(company, pursuit_id, composition, operation_id):
    return service.create_proposal(company, pursuit_id, _object(composition), operation_id)


@endpoint(methods=["POST"])
def save_proposal_revision(company, proposal_id, expected_revision, expected_native_fingerprint, composition, operation_id):
    return service.save_proposal_revision(company, proposal_id, _integer(expected_revision), expected_native_fingerprint, _object(composition), operation_id)

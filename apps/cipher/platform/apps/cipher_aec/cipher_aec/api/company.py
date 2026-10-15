from cipher_aec.governance.commands import read_company_operation
from cipher_aec.governance.company import history as read_history
from .transport import endpoint


@endpoint()
def operation(company, operation_id):
    return read_company_operation(company, operation_id)


@endpoint()
def history(company, limit=50, cursor=None, count_mode="none"):
    return read_history(company, limit, cursor, count_mode)

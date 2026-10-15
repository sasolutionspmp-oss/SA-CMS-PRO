"""Safe business errors shared by transport and domain services."""


class DomainError(Exception):
    def __init__(self, code, message, status=422, details=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.details = details or {}

    def as_dict(self):
        return {"code": self.code, "message": self.message, "details": self.details}

class AppError(Exception):
    """Base application error with an HTTP status for route handlers."""

    status_code = 400

    def __init__(self, message, status_code=None):
        super().__init__(message)
        self.message = message
        if status_code is not None:
            self.status_code = status_code


class ValidationError(AppError):
    status_code = 400


class UnauthorizedError(AppError):
    status_code = 401


class NotFoundError(AppError):
    status_code = 404


class ConflictError(AppError):
    status_code = 409


class TooManyRequestsError(AppError):
    status_code = 429


class ServiceUnavailableError(AppError):
    status_code = 503


class DatabaseBusyError(ServiceUnavailableError):
    def __init__(self, message="Database is busy. Try again."):
        super().__init__(message)

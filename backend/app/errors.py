"""API error model: every error response is {"error": {"code", "message", "details"}}."""
from __future__ import annotations


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, details: dict | list | None = None):
        super().__init__(message)
        self.status, self.code, self.message, self.details = status, code, message, details

    def to_dict(self) -> dict:
        body = {"code": self.code, "message": self.message}
        if self.details is not None:
            body["details"] = self.details
        return {"error": body}


def bad_request(msg: str, details=None) -> ApiError:
    return ApiError(400, "bad_request", msg, details)


def validation_error(details) -> ApiError:
    return ApiError(422, "validation_error", "request validation failed", details)


def unauthorized(msg: str = "authentication required") -> ApiError:
    return ApiError(401, "unauthorized", msg)


def forbidden(msg: str = "insufficient permissions") -> ApiError:
    return ApiError(403, "forbidden", msg)


def not_found(what: str) -> ApiError:
    return ApiError(404, "not_found", f"{what} not found")


def conflict(msg: str, details=None) -> ApiError:
    return ApiError(409, "conflict", msg, details)

"""Unified exception hierarchy and FastAPI global error handlers.

Provides:
- Custom exception classes with HTTP status codes and error codes
- Global exception handlers registered on the FastAPI app
- Standardized JSON error response format
"""
import logging
import traceback
from typing import Any, Optional

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exception hierarchy
# ---------------------------------------------------------------------------


class AppException(Exception):
    """Base application exception.

    All custom exceptions inherit from this class. Each subclass defines
    its own default status_code and error_code.
    """

    status_code: int = 500
    error_code: str = "INTERNAL_ERROR"

    def __init__(
        self,
        message: str = "An unexpected error occurred",
        detail: Any = None,
        status_code: Optional[int] = None,
        error_code: Optional[str] = None,
    ):
        self.message = message
        self.detail = detail
        if status_code is not None:
            self.status_code = status_code
        if error_code is not None:
            self.error_code = error_code
        super().__init__(message)


class NotFoundException(AppException):
    status_code = 404
    error_code = "NOT_FOUND"

    def __init__(self, resource: str = "Resource", detail: Any = None):
        super().__init__(message=f"{resource} not found", detail=detail)


class ValidationException(AppException):
    status_code = 400
    error_code = "VALIDATION_ERROR"

    def __init__(self, message: str = "Validation error", detail: Any = None):
        super().__init__(message=message, detail=detail)


class AuthenticationException(AppException):
    status_code = 401
    error_code = "AUTHENTICATION_ERROR"

    def __init__(self, message: str = "Authentication required", detail: Any = None):
        super().__init__(message=message, detail=detail)


class AuthorizationException(AppException):
    status_code = 403
    error_code = "AUTHORIZATION_ERROR"

    def __init__(self, message: str = "Permission denied", detail: Any = None):
        super().__init__(message=message, detail=detail)


class ExternalServiceException(AppException):
    status_code = 502
    error_code = "EXTERNAL_SERVICE_ERROR"

    def __init__(self, service: str = "External service", detail: Any = None):
        super().__init__(message=f"{service} error", detail=detail)


class DatabaseException(AppException):
    status_code = 500
    error_code = "DATABASE_ERROR"

    def __init__(self, message: str = "Database error", detail: Any = None):
        super().__init__(message=message, detail=detail)


# ---------------------------------------------------------------------------
# Standard error response format
# ---------------------------------------------------------------------------


def _error_response(
    status_code: int,
    error_code: str,
    message: str,
    detail: Any = None,
) -> JSONResponse:
    """Build a standardized error JSON response."""
    body = {
        "error": {
            "code": error_code,
            "message": message,
            "detail": detail,
        }
    }
    return JSONResponse(status_code=status_code, content=body)


# ---------------------------------------------------------------------------
# Global exception handlers
# ---------------------------------------------------------------------------


async def app_exception_handler(request: Request, exc: AppException) -> JSONResponse:
    """Handle all AppException subclasses."""
    logger.warning(
        f"AppException: {exc.error_code} - {exc.message}",
        extra={"error_code": exc.error_code, "path": request.url.path},
    )
    return _error_response(
        status_code=exc.status_code,
        error_code=exc.error_code,
        message=exc.message,
        detail=exc.detail,
    )


async def validation_error_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Handle FastAPI request validation errors with clean field-level output."""
    errors = []
    for err in exc.errors():
        field = ".".join(str(loc) for loc in err.get("loc", []))
        errors.append({
            "field": field,
            "message": err.get("msg", ""),
            "type": err.get("type", ""),
        })
    logger.warning(
        f"Validation error on {request.url.path}: {errors}",
        extra={"path": request.url.path},
    )
    return _error_response(
        status_code=422,
        error_code="VALIDATION_ERROR",
        message="Request validation failed",
        detail=errors,
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all handler for unexpected exceptions.

    Logs the full traceback but returns a generic message to avoid leaking internals.
    """
    logger.error(
        f"Unhandled exception on {request.url.path}: {exc}",
        exc_info=True,
        extra={"path": request.url.path},
    )
    return _error_response(
        status_code=500,
        error_code="INTERNAL_ERROR",
        message="An unexpected error occurred",
    )


# ---------------------------------------------------------------------------
# Registration helper
# ---------------------------------------------------------------------------


def register_exception_handlers(app) -> None:
    """Register all global exception handlers on a FastAPI app instance."""
    app.add_exception_handler(AppException, app_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)

import logging

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import DataError, OperationalError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError
from sqlalchemy.orm.exc import StaleDataError
from starlette.exceptions import HTTPException

logger = logging.getLogger(__name__)


class AppError(Exception):
    """A failure the client should see. Services raise these; handlers format them."""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


class NotFoundError(AppError):
    def __init__(self, resource: str, resource_id: int) -> None:
        message = f"{resource.capitalize()} {resource_id} not found"
        super().__init__(status.HTTP_404_NOT_FOUND, f"{resource}_not_found", message)


class ConflictError(AppError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(status.HTTP_409_CONFLICT, code, message)


class UnauthorizedError(AppError):
    def __init__(self) -> None:
        super().__init__(
            status.HTTP_401_UNAUTHORIZED, "invalid_api_key", "Missing or invalid X-API-Key header"
        )


def error_response(
    status_code: int, code: str, message: str, details: list[dict] | None = None
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message, "details": details}},
    )


def handle_app_error(_: Request, error: AppError) -> JSONResponse:
    return error_response(error.status_code, error.code, error.message)


def handle_validation_error(_: Request, error: RequestValidationError) -> JSONResponse:
    # Only these keys: "input" echoes client data and "ctx" can hold objects JSON cannot encode.
    details = [
        {"field": ".".join(str(part) for part in item["loc"]), "message": item["msg"]}
        for item in error.errors()
    ]
    return error_response(
        status.HTTP_422_UNPROCESSABLE_CONTENT, "validation_error", "Invalid request", details
    )


def handle_http_exception(_: Request, error: HTTPException) -> JSONResponse:
    codes = {404: "not_found", 405: "method_not_allowed"}
    code = codes.get(error.status_code, "http_error")
    return error_response(error.status_code, code, str(error.detail))


def handle_data_error(_: Request, error: DataError) -> JSONResponse:
    # Values Pydantic allows but Postgres refuses: NUL bytes in text, out-of-range numbers.
    logger.warning("Database rejected a value: %s", error.orig)
    return error_response(
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        "invalid_data",
        "A submitted value cannot be stored",
    )


def handle_database_unavailable(request: Request, error: Exception) -> JSONResponse:
    # A 503 tells clients to retry, unlike the 500 this would otherwise become.
    logger.error("Database unavailable on %s %s: %r", request.method, request.url.path, error)
    return error_response(
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "database_unavailable",
        "The database is temporarily unavailable",
    )


def handle_stale_data(request: Request, error: StaleDataError) -> JSONResponse:
    # Another request deleted the row between this request reading it and writing it.
    logger.warning("Concurrent change on %s %s: %s", request.method, request.url.path, error)
    return error_response(
        status.HTTP_409_CONFLICT,
        "concurrent_modification",
        "The record was changed or deleted by another request",
    )


def handle_unexpected_error(request: Request, error: Exception) -> JSONResponse:
    logger.error("Unexpected error on %s %s", request.method, request.url.path, exc_info=error)
    return error_response(
        status.HTTP_500_INTERNAL_SERVER_ERROR, "internal_error", "An unexpected error occurred"
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, handle_app_error)
    app.add_exception_handler(RequestValidationError, handle_validation_error)
    app.add_exception_handler(HTTPException, handle_http_exception)
    app.add_exception_handler(DataError, handle_data_error)
    app.add_exception_handler(OperationalError, handle_database_unavailable)
    app.add_exception_handler(PoolTimeoutError, handle_database_unavailable)
    app.add_exception_handler(StaleDataError, handle_stale_data)
    app.add_exception_handler(Exception, handle_unexpected_error)

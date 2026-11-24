"""Domain exceptions and the consistent error envelope returned by the API."""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel


class ErrorBody(BaseModel):
    code: str
    message: str
    details: dict | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody


class AppError(Exception):
    status_code = 400
    code = "bad_request"

    def __init__(self, message: str, details: dict | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"


class ValidationFailedError(AppError):
    status_code = 422
    code = "validation_failed"


class ConflictError(AppError):
    status_code = 409
    code = "conflict"


class UnauthorizedError(AppError):
    status_code = 401
    code = "unauthorized"


class ForbiddenError(AppError):
    status_code = 403
    code = "forbidden"


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        body = ErrorResponse(error=ErrorBody(code=exc.code, message=exc.message, details=exc.details))
        return JSONResponse(status_code=exc.status_code, content=body.model_dump())

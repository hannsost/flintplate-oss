"""Global exception handlers and custom exception types for palmscout."""

from __future__ import annotations

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from pydantic import ValidationError


class HireOSException(Exception):
    """Base exception for palmscout business logic errors."""

    def __init__(self, message: str, status_code: int = status.HTTP_400_BAD_REQUEST) -> None:
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def register_exception_handlers(app: FastAPI) -> None:
    """Attach all global exception handlers to the FastAPI app."""

    @app.exception_handler(HireOSException)
    async def hireos_exception_handler(request: Request, exc: HireOSException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.message},
        )

    @app.exception_handler(ValidationError)
    async def pydantic_validation_handler(request: Request, exc: ValidationError) -> JSONResponse:
        return JSONResponse(
            # This is an internal model error, not request validation (handled
            # by FastAPI). ORM objects and secrets must never enter a response.
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "Interner Validierungsfehler"},
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        import logging

        from app.sentry import capture_exception

        logging.getLogger(__name__).exception(
            "Unhandled exception on %s %s", request.method, request.url.path
        )
        capture_exception(exc)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "Internal server error"},
        )

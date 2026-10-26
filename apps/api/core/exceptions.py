from datetime import datetime, timezone
import uuid
from typing import Any, Dict, List, Optional
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class AppException(Exception):
    """Base application domain exception."""

    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR,
        details: Optional[List[Dict[str, Any]]] = None,
        title: Optional[str] = None,
    ):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or []
        self.title = title


def format_error_response(
    code: str,
    message: str,
    status_code: int,
    details: Optional[List[Dict[str, Any]]] = None,
    request_id: Optional[str] = None,
    instance: Optional[str] = None,
    title: Optional[str] = None,
    invalid_params: Optional[List[Dict[str, Any]]] = None,
) -> JSONResponse:
    """
    Formats standardized error responses compliant with RFC 7807 and RFC 9457 Problem Details.
    Maintains compatibility with legacy error payloads via nested 'error' block.
    """
    req_id = request_id or str(uuid.uuid4())
    ts = datetime.now(timezone.utc).isoformat()
    error_title = title or code.replace("_", " ").title()
    type_uri = f"https://api.scorva.io/errors/{code.lower().replace('_', '-')}"

    payload: Dict[str, Any] = {
        "type": type_uri,
        "title": error_title,
        "status": status_code,
        "detail": message,
        "code": code,
        "request_id": req_id,
        "timestamp": ts,
    }

    if instance:
        payload["instance"] = instance

    if invalid_params:
        payload["invalid_params"] = invalid_params
    elif details and code == "VALIDATION_ERROR":
        payload["invalid_params"] = [
            {"field": d.get("field"), "reason": d.get("issue")} for d in details
        ]

    # Legacy envelope compatibility for backwards-compatible consumers
    payload["error"] = {
        "code": code,
        "message": message,
        "details": details or [],
        "request_id": req_id,
        "timestamp": ts,
    }

    return JSONResponse(
        status_code=status_code,
        content=payload,
        media_type="application/problem+json",
    )


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppException)
    async def app_exception_handler(request: Request, exc: AppException) -> JSONResponse:
        request_id = getattr(request.state, "correlation_id", None)
        return format_error_response(
            code=exc.code,
            message=exc.message,
            status_code=exc.status_code,
            details=exc.details,
            request_id=request_id,
            instance=str(request.url.path),
            title=exc.title,
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        request_id = getattr(request.state, "correlation_id", None)
        code = "HTTP_ERROR"
        title = "HTTP Error"
        if exc.status_code == status.HTTP_404_NOT_FOUND:
            code = "NOT_FOUND"
            title = "Resource Not Found"
        elif exc.status_code == status.HTTP_401_UNAUTHORIZED:
            code = "UNAUTHORIZED"
            title = "Authentication Required"
        elif exc.status_code == status.HTTP_403_FORBIDDEN:
            code = "FORBIDDEN"
            title = "Access Forbidden"
        elif exc.status_code == status.HTTP_409_CONFLICT:
            code = "CONFLICT"
            title = "Resource Conflict"

        return format_error_response(
            code=code,
            message=str(exc.detail),
            status_code=exc.status_code,
            request_id=request_id,
            instance=str(request.url.path),
            title=title,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        request_id = getattr(request.state, "correlation_id", None)
        details = []
        invalid_params = []
        for error in exc.errors():
            field_name = ".".join(str(loc) for loc in error.get("loc", []))
            issue = error.get("msg", "Validation error")
            details.append(
                {
                    "field": field_name,
                    "issue": issue,
                    "type": error.get("type", "value_error"),
                }
            )
            invalid_params.append(
                {
                    "field": field_name,
                    "reason": issue,
                }
            )

        return format_error_response(
            code="VALIDATION_ERROR",
            message="Request input validation failed.",
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            details=details,
            invalid_params=invalid_params,
            request_id=request_id,
            instance=str(request.url.path),
            title="Unprocessable Entity",
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(
        request: Request, exc: Exception
    ) -> JSONResponse:
        request_id = getattr(request.state, "correlation_id", None)
        return format_error_response(
            code="INTERNAL_SERVER_ERROR",
            message="An unexpected server error occurred.",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            request_id=request_id,
            instance=str(request.url.path),
            title="Internal Server Error",
        )

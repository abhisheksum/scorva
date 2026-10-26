from urllib.parse import urlparse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from apps.api.config import settings
from apps.api.core.exceptions import format_error_response

_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


class CsrfOriginMiddleware(BaseHTTPMiddleware):
    """
    Guards state-mutating endpoints against Cross-Site Request Forgery (CSRF).
    Validates Origin and Referer headers against settings.CORS_ORIGINS for cookie-authenticated requests.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.method in _SAFE_METHODS:
            return await call_next(request)

        # Only apply strict CSRF checks if a session cookie is present on a protected mutation
        has_session_cookie = settings.SESSION_COOKIE_NAME in request.cookies
        is_auth_ceremony = (
            request.url.path.endswith("/auth/login")
            or request.url.path.endswith("/auth/mfa/setup")
            or request.url.path.endswith("/auth/mfa/verify")
        )

        origin = request.headers.get("origin")
        referer = request.headers.get("referer")

        allowed_origins = set(settings.CORS_ORIGINS)
        # In test environment, also allow test client host / base URL
        if settings.SCORVA_ENV == "test":
            allowed_origins.add("http://testserver")
            allowed_origins.add("http://localhost")
            allowed_origins.add("http://127.0.0.1")

        request_source = None
        if origin:
            request_source = origin.rstrip("/")
        elif referer:
            parsed = urlparse(referer)
            if parsed.scheme and parsed.netloc:
                request_source = f"{parsed.scheme}://{parsed.netloc}"

        # If mutation request has session cookie on a protected route (excluding initial login/mfa ceremonies),
        # Origin/Referer MUST be present and trusted
        if has_session_cookie and not is_auth_ceremony:
            if not request_source:
                return format_error_response(
                    code="CSRF_ORIGIN_MISSING",
                    message="Missing Origin or Referer header for cookie-authenticated mutation request.",
                    status_code=403,
                    instance=request.url.path,
                    title="CSRF Check Failed",
                )
            if request_source not in allowed_origins:
                return format_error_response(
                    code="CSRF_ORIGIN_INVALID",
                    message=f"Untrusted request origin '{request_source}'. Request blocked.",
                    status_code=403,
                    instance=request.url.path,
                    title="CSRF Check Failed",
                )
        elif request_source and request_source not in allowed_origins:
            # If Origin/Referer is supplied on any mutating request, it must be trusted
            return format_error_response(
                code="CSRF_ORIGIN_INVALID",
                message=f"Untrusted request origin '{request_source}'. Request blocked.",
                status_code=403,
                instance=request.url.path,
                title="CSRF Check Failed",
            )

        return await call_next(request)

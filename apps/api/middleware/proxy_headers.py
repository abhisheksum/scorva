from typing import Optional
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from apps.api.config import settings


def get_client_ip(request: Request) -> str:
    """
    Safely resolves the true client IP address.
    Trusts X-Forwarded-For only if the immediate peer is in settings.TRUSTED_PROXIES.
    """
    peer_ip = request.client.host if request.client else "127.0.0.1"
    
    trusted_proxies = settings.TRUSTED_PROXIES
    if isinstance(trusted_proxies, str):
        trusted_proxies = [p.strip() for p in trusted_proxies.split(",") if p.strip()]

    if peer_ip in trusted_proxies:
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            # First IP in X-Forwarded-For is client origin
            client_ip = forwarded_for.split(",")[0].strip()
            if client_ip:
                return client_ip

    return peer_ip


class ProxyHeadersMiddleware(BaseHTTPMiddleware):
    """Middleware attaching resolved trusted client_ip to request.state."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request.state.client_ip = get_client_ip(request)
        return await call_next(request)

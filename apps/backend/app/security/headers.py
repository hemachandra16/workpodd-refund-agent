"""HTTP security headers middleware.

Adds a conservative baseline of security headers to every response:
HSTS, X-Content-Type-Options, X-Frame-Options, Referrer-Policy, Permissions-Policy,
and a restrictive Content-Security-Policy. These are cheap, well-understood
controls that meaningfully raise the bar against common web attacks
(clickjacking, MIME sniffing, mixed-content downgrade, etc.).
"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        # Defense in depth — safe defaults, overridden only where genuinely needed.
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault(
            "Permissions-Policy",
            "geolocation=(), microphone=(self), camera=(), payment=()",
        )
        # HSTS only over https; harmless on localhost but signals intent in prod.
        response.headers.setdefault("Strict-Transport-Security", "max-age=63072000; includeSubDomains")
        # CSP: no inline scripts/styles by default, no remote origins, no plugins.
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; "
            "script-src 'self'; "
            "style-src 'self' 'unsafe-inline'; "
            # 'unsafe-inline' on style is the minimum needed for some framework
            # inline styles; tightened later if the frontend removes them.
            "img-src 'self' data:; "
            "font-src 'self'; "
            "connect-src 'self'; "
            "frame-ancestors 'none'; "
            "base-uri 'self'; "
            "form-action 'self'",
        )
        # Hide server fingerprint.
        response.headers.setdefault("Server", "worpodd")
        return response

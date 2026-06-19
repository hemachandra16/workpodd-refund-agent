"""WORPODD Refund Agent — FastAPI application factory.

This is the runnable entrypoint. Phase 1 wires only the app shell, security
headers, health check, and structured request logging. Agent routes, SSE,
auth, and voice land in later phases.
"""

from __future__ import annotations

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.security.headers import SecurityHeadersMiddleware
from app.security.logging import configure_logging

settings = get_settings()
configure_logging(environment=settings.environment)
log = structlog.get_logger()


def create_app() -> FastAPI:
    settings.production_safety_check()

    app = FastAPI(
        title="WORPODD Refund Agent",
        version="0.1.0",
        docs_url="/docs" if not settings.is_production else None,
        redoc_url=None,
        openapi_url="/openapi.json" if not settings.is_production else None,
    )

    # --- Allowed origins: strict allowlist, never "*" ---
    allowed_origins = [o.strip() for o in settings.frontend_origin.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "Authorization"],
    )

    # --- Security headers (HSTS, CSP, X-Content-Type-Options, etc.) ---
    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/health", tags=["meta"])
    async def health() -> dict[str, object]:
        return {
            "status": "ok",
            "environment": settings.environment,
            "groq_available": settings.groq_available,
            "llm_model": settings.groq_llm_model,
        }

    @app.exception_handler(Exception)
    async def unhandled(_, exc: Exception) -> JSONResponse:
        # Never leak internal tracebacks to clients.
        log.exception("unhandled_error", error=str(exc))
        return JSONResponse(status_code=500, content={"error": "internal_error"})

    log.info("app_started", env=settings.environment, port=settings.backend_port)
    return app


app = create_app()


if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.backend_host,
        port=settings.backend_port,
        reload=settings.environment == "development",
    )

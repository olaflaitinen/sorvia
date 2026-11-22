"""FastAPI application factory."""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from sorvia import __version__
from sorvia.api.deps import RateLimiter, Services
from sorvia.api.routes import router
from sorvia.config import Settings, get_settings
from sorvia.db import Database
from sorvia.executor import ScopedExecutor
from sorvia.nl2sql.embeddings import build_embedder
from sorvia.nl2sql.llm import build_client
from sorvia.nl2sql.pipeline import AskService

log = logging.getLogger("sorvia.api")


def build_services(settings: Settings) -> Services:
    db = Database.open(settings)
    embedder = build_embedder(
        settings.embedding_provider, settings.embedding_dim, settings.embedding_model,
        settings.embedding_base_url,
        settings.embedding_api_key.get_secret_value() if settings.embedding_api_key else None,
    )
    llm = build_client(settings)
    return Services(
        settings=settings,
        db=db,
        ask=AskService(settings, db, llm, embedder),
        embedder=embedder,
        executor=ScopedExecutor(db, settings),
        limiter=RateLimiter(settings.rate_limit_per_minute),
    )


def create_app(settings: Settings | None = None, services: Services | None = None) -> FastAPI:
    settings = settings or get_settings()
    settings.validate_for_production()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        owned = services is None
        app.state.services = services or build_services(settings)
        log.info("Sorvia %s started (llm=%s, strategy=%s)", __version__, settings.llm_provider, settings.strategy)
        try:
            yield
        finally:
            if owned:
                app.state.services.db.close()

    app = FastAPI(
        title="Sorvia API",
        version=__version__,
        description="Ask the pharmacy database in Azerbaijani. Every answer is produced by SQL that passed "
                    "three independent safety layers.",
        lifespan=lifespan,
    )

    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=False,
            allow_methods=["GET", "POST"],
            allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
        )

    @app.middleware("http")
    async def request_context(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
        start = time.perf_counter()
        response = await call_next(request)
        elapsed = (time.perf_counter() - start) * 1000
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        log.info("%s %s %s %.1fms rid=%s", request.method, request.url.path, response.status_code, elapsed, request_id)
        return response

    @app.exception_handler(HTTPException)
    async def http_error(_: Request, exc: HTTPException) -> JSONResponse:
        if isinstance(exc.detail, dict):
            body = exc.detail
        else:
            body = {"code": _code_for(exc.status_code), "message": str(exc.detail)}
        return JSONResponse(body, status_code=exc.status_code, headers=exc.headers)

    @app.exception_handler(Exception)
    async def unhandled(_: Request, exc: Exception) -> JSONResponse:
        log.exception("Unhandled error", exc_info=exc)
        return JSONResponse({"code": "internal_error", "message": "Internal server error"}, status_code=500)

    app.include_router(router)
    return app


def _code_for(status_code: int) -> str:
    return {
        400: "bad_request", 401: "unauthorized", 403: "forbidden", 404: "not_found", 409: "conflict",
        422: "validation_error", 429: "rate_limited", 503: "unavailable",
    }.get(status_code, "error")

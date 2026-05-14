from __future__ import annotations

import asyncio
import importlib.metadata
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Final, override

from fastapi import FastAPI, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError
from sqlalchemy.exc import TimeoutError as SQLTimeoutError
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.middleware.trustedhost import TrustedHostMiddleware

from ..core.config import (
    MAX_REQUEST_BYTES,
    SCHEMA_WAIT_INTERVAL_SECONDS,
    SCHEMA_WAIT_TIMEOUT_SECONDS,
    SEMANTIC_ADMIN_MAX_REQUEST_BYTES,
    allowed_hosts,
    cors_origins,
    is_production_env,
)
from ..core.db_init import INIT_MODE_API, init_db, wait_for_migration_ready
from ..core.logging_config import setup_loggers
from ._semantic_index import (
    get_semantic_index as get_semantic_index,  # noqa: F401 — re-exported for test monkeypatching
)
from .oracle_pool import apply_oracle_pools, load_oracle_pools, rotate_oracle_pools
from .routers.admin import router as admin_router
from .routers.search import router as search_router
from .routers.seo import router as seo_router

logger = logging.getLogger("ot_backend.api")

_SEMANTIC_ADMIN_PREFIX: Final[str] = "/admin/semantic-models"
_SEMANTIC_ADMIN_JOBS_PREFIX: Final[str] = "/admin/semantic-jobs"


def _get_api_version() -> str:
    try:
        return importlib.metadata.version("oracle-tutor-api")
    except importlib.metadata.PackageNotFoundError:
        return "1.2.0"


API_VERSION: Final[str] = _get_api_version()


class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    @override
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.method in {"POST", "PUT", "PATCH"}:
            _path = request.scope.get("path", request.url.path)
            limit_bytes = (
                SEMANTIC_ADMIN_MAX_REQUEST_BYTES
                if _path.startswith(_SEMANTIC_ADMIN_PREFIX)
                or _path.startswith(_SEMANTIC_ADMIN_JOBS_PREFIX)
                else MAX_REQUEST_BYTES
            )
            content_length = request.headers.get("content-length")
            if content_length is not None:
                try:
                    parsed_length = int(content_length)
                except ValueError:
                    parsed_length = limit_bytes + 1

                if parsed_length > limit_bytes:
                    logger.warning(
                        "Rejected oversized request by content-length: method=%s path=%s bytes=%s",
                        request.method,
                        request.url.path,
                        content_length,
                    )
                    return JSONResponse(
                        status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                        content={"detail": f"Request body exceeds the {limit_bytes}-byte limit."},
                    )

            body = await request.body()
            if len(body) > limit_bytes:
                logger.warning(
                    "Rejected oversized request by body read: method=%s path=%s bytes=%s",
                    request.method,
                    request.url.path,
                    len(body),
                )
                return JSONResponse(
                    status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                    content={"detail": f"Request body exceeds the {limit_bytes}-byte limit."},
                )

        return await call_next(request)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    setup_loggers()
    logger.info("API starting...")

    try:
        init_db(mode=INIT_MODE_API)
        if not wait_for_migration_ready(
            timeout_s=SCHEMA_WAIT_TIMEOUT_SECONDS,
            interval_s=SCHEMA_WAIT_INTERVAL_SECONDS,
        ):
            logger.warning(
                "Schema migration is not ready after %.1fs; API data endpoints will return 503 until ready.",
                SCHEMA_WAIT_TIMEOUT_SECONDS,
            )
    except Exception as exc:
        logger.error("DB init failed: %s", exc, exc_info=True)
        raise

    logger.info("Loading semantic model...")
    try:
        from . import _semantic_index as _sem_idx_mod
        index = _sem_idx_mod.get_semantic_index()
        if index is None:
            logger.warning("Semantic model unavailable — semantic endpoints will return 503")
        else:
            logger.info("Semantic model ready. model_id=%s", index.model_id)
    except Exception as exc:
        logger.error("Semantic model failed to load: %s", exc, exc_info=True)

    oracle_text_pool: list[str] = []
    home_term_pool: list[str] = []
    try:
        oracle_text_pool, home_term_pool = load_oracle_pools()
        logger.info("Oracle home pools loaded: %d texts, %d terms", len(oracle_text_pool), len(home_term_pool))
    except Exception as exc:
        logger.warning("Oracle home pools failed to load: %s", exc)

    apply_oracle_pools(_app, oracle_text_pool, home_term_pool)

    rotation_task = asyncio.create_task(rotate_oracle_pools(_app))

    try:
        yield
    finally:
        logger.info("API shutting down...")
        rotation_task.cancel()
        try:
            await rotation_task
        except asyncio.CancelledError:
            pass


_docs_disabled = is_production_env()
app = FastAPI(
    lifespan=lifespan,
    title="oracle-tutor api",
    version=API_VERSION,
    docs_url=None if _docs_disabled else "/docs",
    redoc_url=None if _docs_disabled else "/redoc",
    openapi_url=None if _docs_disabled else "/openapi.json",
)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts())
app.add_middleware(RequestSizeLimitMiddleware)

origins = cors_origins()
if origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.include_router(admin_router)
app.include_router(search_router)
app.include_router(seo_router)


@app.exception_handler(SQLTimeoutError)
@app.exception_handler(OperationalError)
async def database_connection_exception_handler(request: Request, exc: Exception):
    logger.warning(
        "Database connection error on %s %s: %s",
        request.method,
        request.url.path,
        exc,
        exc_info=True,
    )
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={
            "detail": "Service temporarily unavailable due to high load. Please try again in a moment.",
            "error": "database_connection_error",
        },
    )


@app.exception_handler(RequestValidationError)
async def request_validation_exception_handler(request: Request, exc: RequestValidationError):
    errors = exc.errors()
    for error in errors:
        context = error.get("ctx")
        if not isinstance(context, dict):
            continue
        if "error" in context:
            context["error"] = str(context["error"])

    logger.warning(
        "Request validation failed on %s %s from %s: %s",
        request.method,
        request.url.path,
        request.client.host if request.client else "unknown",
        errors,
    )
    return JSONResponse(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, content={"detail": errors})


@app.get("/", tags=["meta"])
def root() -> dict[str, str]:
    return {"service": "oracle-tutor-api"}


@app.get("/health", tags=["meta"])
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ready", tags=["meta"])
def ready() -> Response:
    # Returns 200 once a semantic model is materialised in memory, 503 otherwise.
    # The frontend polls this on load so it can mask cold-start latency with a
    # themed boot overlay instead of letting search hit 503s.
    from ._semantic_index import get_semantic_index

    index = get_semantic_index()
    if index is None or index.model_id is None:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"ready": False},
            headers={"Cache-Control": "no-store"},
        )
    return JSONResponse(
        content={"ready": True, "model_id": index.model_id},
        headers={"Cache-Control": "no-store"},
    )


@app.get("/version", tags=["meta"])
def version() -> dict[str, str]:
    return {"version": API_VERSION}


@app.get("/favicon.ico")
def favicon() -> Response:
    return Response(status_code=204)

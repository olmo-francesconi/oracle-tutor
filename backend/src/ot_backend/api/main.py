from __future__ import annotations

import importlib.metadata
import json
import logging
import os
import random
import re
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Final, Literal, Protocol, cast

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.exc import TimeoutError as SQLTimeoutError
from sqlalchemy.orm import Session, joinedload
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from ..core.config import (
    MAX_QUERY_LENGTH,
    MAX_REQUEST_BYTES,
    SCHEMA_WAIT_INTERVAL_SECONDS,
    SCHEMA_WAIT_TIMEOUT_SECONDS,
    SEMANTIC_ADMIN_MAX_REQUEST_BYTES,
    admin_jwt_secret,
    admin_password,
    allowed_hosts,
)
from ..core.database import get_db
from ..core.db_init import INIT_MODE_API, init_db, wait_for_migration_ready
from ..core.logging_config import log_performance, setup_loggers
from ..core.models import (
    AnalyticsEvent,
    Card,
    CardFace,
    CardRaw,
    ClientErrorEvent,
    SemanticDataset,
    SemanticModel,
)
from ..embed.artifacts import (
    SEMANTIC_DATASET_ARTIFACT_KIND_DATASET_JSON,
    SEMANTIC_MODEL_ARTIFACT_KIND_BUNDLE_ZIP,
    list_semantic_dataset_artifacts,
    list_semantic_model_artifacts,
)
from ..embed.base_models import get_semantic_base_model, list_semantic_base_models
from ..embed.dataset_registry import get_semantic_dataset, list_semantic_datasets
from ..embed.model_registry import (
    count_semantic_model_embeddings,
    get_semantic_model,
    list_semantic_models,
    parse_optional_json_header,
)
from ..embed.registration import register_model_bundle_bytes
from ..embed.semantic_jobs import (
    SEMANTIC_JOB_STATUS_PENDING,
    create_dataset_job,
    create_promote_job,
    create_train_job,
    get_semantic_job,
    list_semantic_jobs,
)
from ..embed.train_options import EMBED_BATCH_SIZE_OPTIONS, TRAIN_AUGMENTATION_OPTIONS, TRAIN_BATCH_SIZE_OPTIONS

try:
    from ..embed.index import get_semantic_index
except ImportError:
    get_semantic_index = None

from .admin_auth import (
    admin_token_ttl_seconds,
    create_admin_token,
    ensure_admin_ip_not_locked_out,
    get_admin_client_ip,
    register_admin_login_failure,
    require_admin_token,
    reset_admin_login_failures,
)
from .schemas import (
    AdminAuthTokenRequest,
    AdminAuthTokenResponse,
    AnalyticsEventIngest,
    CardMatch,
    ClientErrorEventIngest,
    OracleSamplesResponse,
    SemanticBaseModelOption,
    SemanticDatasetArtifactSummary,
    SemanticDatasetDetail,
    SemanticDatasetJobCreate,
    SemanticDatasetSummary,
    SemanticJobDetail,
    SemanticJobSummary,
    SemanticModelArtifactSummary,
    SemanticModelDetail,
    SemanticModelPromoteRequest,
    SemanticModelPromotionAccepted,
    SemanticModelSummary,
    SemanticPromoteJobCreate,
    SemanticTrainAugmentationOption,
    SemanticTrainJobCreate,
    SemanticTrainOptions,
    SimilarCard,
    SimilarCardsPage,
    TelemetryIngestResponse,
)

logger = logging.getLogger("ot_backend.api")


class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.method in {"POST", "PUT", "PATCH"}:
            # Use scope["path"] (ASGI path without root_path prefix) so this works
            # correctly behind a reverse proxy that sets root_path.
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


class SemanticIndexProtocol(Protocol):
    model_id: str | None

    def similar_to_face(
        self,
        face_key: tuple[str, int],
        limit: int,
        db: Session,
        card_type: list[str] | None = None,
        colors: str | None = None,
        cmc_min: float | None = None,
        cmc_max: float | None = None,
        format: list[str] | None = None,
        rarity: list[str] | None = None,
        color_feature: str = "identity",
        match_mode: str = "at_least",
    ) -> list[tuple[tuple[str, int], float]]: ...

    def search_oracle(
        self,
        query: str,
        limit: int,
        db: Session,
        card_type: list[str] | None = None,
        colors: str | None = None,
        cmc_min: float | None = None,
        cmc_max: float | None = None,
        format: list[str] | None = None,
        rarity: list[str] | None = None,
        color_feature: str = "identity",
        match_mode: str = "at_least",
    ) -> list[tuple[tuple[str, int], float]]: ...


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


def _get_api_version() -> str:
    try:
        return importlib.metadata.version("oracle-tutor-api")
    except importlib.metadata.PackageNotFoundError:
        return "1.2.0"


API_VERSION: Final[str] = _get_api_version()
MAX_SEARCH_LIMIT: Final[int] = 25
MAX_SIMILAR_CARDS_LIMIT: Final[int] = 100

DOUBLE_SIDED_LAYOUTS: Final[frozenset[str]] = frozenset(
    {
        "transform",
        "modal_dfc",
        "meld",
        "double_faced_token",
        "art_series",
    }
)
_RARITY_MAP: Final = {"c": "common", "u": "uncommon", "r": "rare", "m": "mythic"}
_CARD_TYPE_MAP: Final = {
    "c": "creature",
    "i": "instant",
    "s": "sorcery",
    "e": "enchantment",
    "a": "artifact",
    "p": "planeswalker",
    "l": "land",
}
_FORMAT_MAP: Final = {
    "s": "standard",
    "p": "pioneer",
    "m": "modern",
    "l": "legacy",
    "v": "vintage",
    "c": "commander",
    "u": "pauper",
}
ORACLE_TEXT_POOL_LIMIT: Final[int] = 300
HOME_TERM_POOL_LIMIT: Final[int] = 300
MAX_TELEMETRY_DETAILS_BYTES: Final[int] = 8_000
_SEMANTIC_ADMIN_PREFIX: Final[str] = "/admin/semantic-models"
_SEMANTIC_ADMIN_JOBS_PREFIX: Final[str] = "/admin/semantic-jobs"
ABILITY_WORD_PATTERN: Final[re.Pattern[str]] = re.compile(r"^\s*([A-Za-z][A-Za-z' -]{1,40}?)\s+[—-]\s+", re.MULTILINE)
_schema_ready: bool = False
_oracle_text_pool: list[str] = []
_home_term_pool: list[str] = []


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ensure_schema_ready() -> None:
    global _schema_ready
    if _schema_ready:
        return
    if wait_for_migration_ready(timeout_s=0.0, interval_s=SCHEMA_WAIT_INTERVAL_SECONDS):
        _schema_ready = True
        return
    raise HTTPException(status_code=503, detail="Schema migration in progress. Please retry shortly.")


def _get_semantic_index() -> SemanticIndexProtocol | None:
    if get_semantic_index is None:
        return None
    return cast(Callable[[], SemanticIndexProtocol | None], get_semantic_index)()


def _bundle_artifact_summary(model: SemanticModel) -> tuple[str, int] | None:
    for artifact in model.artifacts:
        if artifact.artifact_kind == SEMANTIC_MODEL_ARTIFACT_KIND_BUNDLE_ZIP:
            return artifact.sha256, artifact.size_bytes
    return None


def _dataset_artifact_summary(dataset: SemanticDataset) -> tuple[str, int] | None:
    for artifact in dataset.artifacts:
        if artifact.artifact_kind == SEMANTIC_DATASET_ARTIFACT_KIND_DATASET_JSON:
            return artifact.sha256, artifact.size_bytes
    return None


def _serialize_semantic_model(model: SemanticModel, *, embedding_count: int | None = None) -> SemanticModelDetail:
    count = embedding_count if embedding_count is not None else 0
    bundle = _bundle_artifact_summary(model)
    base_model_key = None
    config_json = model.config_json or {}
    raw_base_model_key = config_json.get("base_model_key")
    if isinstance(raw_base_model_key, str):
        base_model_key = raw_base_model_key
    return SemanticModelDetail(
        id=model.id,
        slug=model.slug,
        base_model_key=base_model_key,
        base_model=model.base_model,
        status=model.status,
        is_active=model.is_active,
        embedding_dim=model.embedding_dim,
        artifact_sha256=bundle[0] if bundle else "",
        artifact_size_bytes=bundle[1] if bundle else 0,
        created_at=model.created_at,
        activated_at=model.activated_at,
        error_message=model.error_message,
        config_json=model.config_json,
        metrics_json=model.metrics_json,
        embedding_count=count,
    )


def _serialize_semantic_model_summary(model: SemanticModel) -> SemanticModelSummary:
    bundle = _bundle_artifact_summary(model)
    base_model_key = None
    config_json = model.config_json or {}
    raw_base_model_key = config_json.get("base_model_key")
    if isinstance(raw_base_model_key, str):
        base_model_key = raw_base_model_key
    return SemanticModelSummary(
        id=model.id,
        slug=model.slug,
        base_model_key=base_model_key,
        base_model=model.base_model,
        status=model.status,
        is_active=model.is_active,
        embedding_dim=model.embedding_dim,
        artifact_sha256=bundle[0] if bundle else "",
        artifact_size_bytes=bundle[1] if bundle else 0,
        created_at=model.created_at,
        activated_at=model.activated_at,
        error_message=model.error_message,
    )


def _serialize_semantic_dataset(dataset: SemanticDataset) -> SemanticDatasetDetail:
    return SemanticDatasetDetail(
        id=dataset.id,
        slug=dataset.slug,
        status=dataset.status,
        augmentation_mode=dataset.augmentation_mode,
        created_at=dataset.created_at,
        source_semantic_data_version=dataset.source_semantic_data_version,
        error_message=dataset.error_message,
        config_json=dataset.config_json,
        metrics_json=dataset.metrics_json,
    )


def _serialize_semantic_dataset_summary(dataset: SemanticDataset) -> SemanticDatasetSummary:
    return SemanticDatasetSummary(
        id=dataset.id,
        slug=dataset.slug,
        status=dataset.status,
        augmentation_mode=dataset.augmentation_mode,
        created_at=dataset.created_at,
        source_semantic_data_version=dataset.source_semantic_data_version,
        error_message=dataset.error_message,
    )



def _image_side_for_face(layout: str | None, face_ix: int) -> Literal["front", "back"]:
    if layout in DOUBLE_SIDED_LAYOUTS and face_ix > 0:
        return "back"
    return "front"


def _normalize_home_term(term: str) -> str:
    return " ".join(term.split()).strip(" -\u2014")


def _extract_ability_words(text: str | None) -> list[str]:
    if not text or not text.strip():
        return []
    return [_normalize_home_term(match.group(1)) for match in ABILITY_WORD_PATTERN.finditer(text)]


def _build_home_term_pool(keyword_rows: list[tuple[list[str] | None]], oracle_rows: list[tuple[str | None]]) -> list[str]:
    deduped_terms: dict[str, str] = {}

    for keywords, in keyword_rows:
        for keyword in keywords or []:
            normalized = _normalize_home_term(keyword)
            if normalized:
                deduped_terms.setdefault(normalized.casefold(), normalized)

    for oracle_text, in oracle_rows:
        for ability_word in _extract_ability_words(oracle_text):
            if ability_word:
                deduped_terms.setdefault(ability_word.casefold(), ability_word)

    return list(deduped_terms.values())


def _normalize_client_timestamp(timestamp: datetime | None) -> datetime:
    if timestamp is None:
        return datetime.now(UTC).replace(tzinfo=None)
    if timestamp.tzinfo is not None:
        return timestamp.astimezone(UTC).replace(tzinfo=None)
    return timestamp


def _ensure_telemetry_details_size(payload: dict[str, object] | None, field_name: str) -> None:
    if payload is None:
        return

    encoded = json.dumps(payload, separators=(",", ":"))
    if len(encoded.encode("utf-8")) <= MAX_TELEMETRY_DETAILS_BYTES:
        return

    raise HTTPException(
        status_code=413,
        detail=f"{field_name} exceeds the {MAX_TELEMETRY_DETAILS_BYTES}-byte telemetry limit",
    )


def _to_similar_cards(results: list[tuple[tuple[str, int], float]], db: Session) -> list[SimilarCard]:
    if not results:
        return []

    from sqlalchemy import tuple_

    target_face_keys = [face_key for face_key, _ in results]
    key_to_score = {face_key: score for face_key, score in results}
    faces = (
        db.query(CardFace)
        .options(joinedload(CardFace.card).joinedload(Card.raw_printing))
        .filter(tuple_(CardFace.oracle_id, CardFace.face_ix).in_(target_face_keys))
        .all()
    )
    faces_map = {(face.oracle_id, face.face_ix): face for face in faces}

    similar_cards: list[SimilarCard] = []
    for face_key in target_face_keys:
        face = faces_map.get(face_key)
        if face is None:
            continue
        card = face.card
        similar_cards.append(
            SimilarCard(
                oracle_id=card.oracle_id,
                scryfall_id=card.scryfall_id,
                face_ix=face.face_ix,
                image_side=_image_side_for_face(card.layout, face.face_ix),
                name=face.name,
                card_name=card.name,
                similarity=float(key_to_score.get(face_key, 0.0)),
                rank=card.edhrec_rank,
                type_line=face.type_line,
                mana_cost=face.mana_cost,
                oracle_text=face.oracle_text,
                power=face.power,
                toughness=face.toughness,
                colors=face.colors,
                layout=card.layout,
                rarity=card.rarity,
                legalities=card.legalities,
                uniqueness=card.uniqueness,
                border_color=card.raw_printing.border_color,
                set_code=card.raw_printing.set_code,
            )
        )
    return similar_cards


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------


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
        index = _get_semantic_index()
        if index is None:
            logger.warning("Semantic model unavailable — semantic endpoints will return 503")
        else:
            logger.info("Semantic model ready. model_id=%s", index.model_id)
    except Exception as exc:
        logger.error("Semantic model failed to load: %s", exc, exc_info=True)

    global _home_term_pool, _oracle_text_pool
    try:
        db = next(get_db())
        try:
            oracle_rows = (
                db.query(CardFace.oracle_text)
                .filter(
                    CardFace.oracle_text.isnot(None),
                    CardFace.oracle_text != "",
                )
                .order_by(func.random())
                .limit(ORACLE_TEXT_POOL_LIMIT)
                .all()
            )
            _oracle_text_pool.extend(
                row[0] for row in oracle_rows if row[0] and row[0].strip()
            )
            keyword_rows = (
                db.query(CardRaw.keywords)
                .filter(CardRaw.keywords.isnot(None))
                .order_by(func.random())
                .limit(HOME_TERM_POOL_LIMIT)
                .all()
            )
            _home_term_pool.extend(_build_home_term_pool(keyword_rows, oracle_rows))
            logger.info("Oracle home pools loaded: %d texts, %d terms", len(_oracle_text_pool), len(_home_term_pool))
        finally:
            db.close()
    except Exception as exc:
        logger.warning("Oracle home pools failed to load: %s", exc)

    yield

    logger.info("API shutting down...")


app = FastAPI(lifespan=lifespan, title="oracle-tutor api", version=API_VERSION)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts())
app.add_middleware(RequestSizeLimitMiddleware)


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


cors_origins_env = os.getenv("ORACLE_TUTOR_API_CORS_ORIGINS", "").strip()
if cors_origins_env:
    origins = [origin.strip() for origin in cors_origins_env.split(",") if origin.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )


# ---------------------------------------------------------------------------
# Routes — meta
# ---------------------------------------------------------------------------


@app.get("/", tags=["meta"])
def root() -> dict[str, str]:
    return {"service": "oracle-tutor-api"}


@app.get("/health", tags=["meta"])
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/version", tags=["meta"])
def version() -> dict[str, str]:
    return {"version": API_VERSION}


@app.get("/favicon.ico")
def favicon() -> Response:
    return Response(status_code=204)


@app.get("/oracle-samples", response_model=OracleSamplesResponse, tags=["meta"])
def oracle_samples(
    n: int = Query(60, ge=1, le=100),
) -> OracleSamplesResponse:
    texts = random.sample(_oracle_text_pool, min(n, len(_oracle_text_pool))) if _oracle_text_pool else []
    terms = random.sample(_home_term_pool, min(n, len(_home_term_pool))) if _home_term_pool else []
    return OracleSamplesResponse(texts=texts, terms=terms)


# ---------------------------------------------------------------------------
# Routes — telemetry
# ---------------------------------------------------------------------------


@app.post("/telemetry/client-error", response_model=TelemetryIngestResponse, status_code=status.HTTP_202_ACCEPTED, tags=["telemetry"])
def ingest_client_error(
    payload: ClientErrorEventIngest,
    request: Request,
    db: Session = Depends(get_db),
) -> TelemetryIngestResponse:
    _ensure_telemetry_details_size(payload.context, "context")

    event = ClientErrorEvent(
        occurred_at=_normalize_client_timestamp(payload.timestamp),
        error_name=payload.name,
        message=payload.message,
        stack=payload.stack,
        page_url=payload.url,
        user_agent=payload.userAgent or request.headers.get("user-agent"),
        source=str(payload.context.get("source")) if payload.context and "source" in payload.context else None,
        context=payload.context,
    )
    db.add(event)
    db.commit()

    logger.info(
        "Telemetry client error accepted: name=%s source=%s url=%s",
        event.error_name,
        event.source,
        event.page_url,
    )
    return TelemetryIngestResponse()


@app.post("/telemetry/analytics", response_model=TelemetryIngestResponse, status_code=status.HTTP_202_ACCEPTED, tags=["telemetry"])
def ingest_analytics_event(
    payload: AnalyticsEventIngest,
    request: Request,
    db: Session = Depends(get_db),
) -> TelemetryIngestResponse:
    _ensure_telemetry_details_size(payload.props, "props")

    event = AnalyticsEvent(
        occurred_at=_normalize_client_timestamp(payload.timestamp),
        event_name=payload.event,
        page_url=payload.url,
        user_agent=payload.userAgent or request.headers.get("user-agent"),
        props=payload.props,
    )
    db.add(event)
    db.commit()

    logger.info("Telemetry analytics accepted: event=%s url=%s", event.event_name, event.page_url)
    return TelemetryIngestResponse()


# ---------------------------------------------------------------------------
# Routes — admin semantic models
# ---------------------------------------------------------------------------


@app.post("/admin/auth/token", response_model=AdminAuthTokenResponse, tags=["admin"])
def admin_auth_token(payload: AdminAuthTokenRequest, request: Request) -> AdminAuthTokenResponse:
    configured_password = admin_password()
    if not configured_password or not admin_jwt_secret():
        raise HTTPException(status_code=503, detail="Admin auth is not configured.")
    client_ip = get_admin_client_ip(request)
    ensure_admin_ip_not_locked_out(client_ip)
    if payload.password != configured_password:
        register_admin_login_failure(client_ip)
        raise HTTPException(status_code=401, detail="Invalid admin password.")
    reset_admin_login_failures(client_ip)
    return AdminAuthTokenResponse(
        access_token=create_admin_token(),
        expires_in=admin_token_ttl_seconds(),
    )


@app.get("/admin/semantic-models", response_model=list[SemanticModelSummary], tags=["admin"])
def admin_list_semantic_models(
    _: None = Depends(require_admin_token),
    db: Session = Depends(get_db),
) -> list[SemanticModelSummary]:
    return [_serialize_semantic_model_summary(model) for model in list_semantic_models(db)]


@app.get("/admin/semantic-datasets", response_model=list[SemanticDatasetSummary], tags=["admin"])
def admin_list_semantic_datasets(
    _: None = Depends(require_admin_token),
    db: Session = Depends(get_db),
) -> list[SemanticDatasetSummary]:
    return [_serialize_semantic_dataset_summary(dataset) for dataset in list_semantic_datasets(db)]


@app.get("/admin/semantic-base-models", response_model=list[SemanticBaseModelOption], tags=["admin"])
def admin_list_semantic_base_models(_: None = Depends(require_admin_token)) -> list[SemanticBaseModelOption]:
    return [
        SemanticBaseModelOption(
            key=spec.key,
            label=spec.label,
            base_model=spec.base_model,
            embedding_dim=spec.embedding_dim,
        )
        for spec in list_semantic_base_models()
    ]


@app.get("/admin/semantic-train-options", response_model=SemanticTrainOptions, tags=["admin"])
def admin_get_semantic_train_options(_: None = Depends(require_admin_token)) -> SemanticTrainOptions:
    return SemanticTrainOptions(
        batch_size_options=list(TRAIN_BATCH_SIZE_OPTIONS),
        embed_batch_size_options=list(EMBED_BATCH_SIZE_OPTIONS),
        augmentation_options=[
            SemanticTrainAugmentationOption(
                key=option.key,
                label=option.label,
                description=option.description,
                default_enabled=option.default_enabled,
            )
            for option in TRAIN_AUGMENTATION_OPTIONS
        ],
    )


@app.get("/admin/semantic-models/{model_id}", response_model=SemanticModelDetail, tags=["admin"])
def admin_get_semantic_model(
    model_id: str,
    _: None = Depends(require_admin_token),
    db: Session = Depends(get_db),
) -> SemanticModelDetail:
    model = get_semantic_model(db, model_id)
    if model is None:
        raise HTTPException(status_code=404, detail="Semantic model not found.")
    return _serialize_semantic_model(model, embedding_count=count_semantic_model_embeddings(db, model_id))


@app.get("/admin/semantic-models/{model_id}/artifacts", response_model=list[SemanticModelArtifactSummary], tags=["admin"])
def admin_list_semantic_model_artifacts(
    model_id: str,
    _: None = Depends(require_admin_token),
    db: Session = Depends(get_db),
) -> list[SemanticModelArtifactSummary]:
    model = get_semantic_model(db, model_id)
    if model is None:
        raise HTTPException(status_code=404, detail="Semantic model not found.")
    return [SemanticModelArtifactSummary.model_validate(artifact) for artifact in list_semantic_model_artifacts(db, model_id)]


@app.get("/admin/semantic-datasets/{dataset_id}", response_model=SemanticDatasetDetail, tags=["admin"])
def admin_get_semantic_dataset(
    dataset_id: str,
    _: None = Depends(require_admin_token),
    db: Session = Depends(get_db),
) -> SemanticDatasetDetail:
    dataset = get_semantic_dataset(db, dataset_id)
    if dataset is None:
        raise HTTPException(status_code=404, detail="Semantic dataset not found.")
    return _serialize_semantic_dataset(dataset)


@app.get("/admin/semantic-datasets/{dataset_id}/artifacts", response_model=list[SemanticDatasetArtifactSummary], tags=["admin"])
def admin_list_semantic_dataset_artifacts(
    dataset_id: str,
    _: None = Depends(require_admin_token),
    db: Session = Depends(get_db),
) -> list[SemanticDatasetArtifactSummary]:
    dataset = get_semantic_dataset(db, dataset_id)
    if dataset is None:
        raise HTTPException(status_code=404, detail="Semantic dataset not found.")
    return [SemanticDatasetArtifactSummary.model_validate(artifact) for artifact in list_semantic_dataset_artifacts(db, dataset_id)]


@app.post("/admin/semantic-models", response_model=SemanticModelDetail, status_code=status.HTTP_201_CREATED, tags=["admin"])
async def admin_register_semantic_model(
    request: Request,
    _: None = Depends(require_admin_token),
    slug: str = Query(..., min_length=1, max_length=120),
    base_model_key: str = Query(..., min_length=1, max_length=120),
    db: Session = Depends(get_db),
) -> SemanticModelDetail:
    bundle_bytes = await request.body()
    if not bundle_bytes:
        raise HTTPException(status_code=400, detail="Semantic model bundle body is required.")

    try:
        base_model_spec = get_semantic_base_model(base_model_key)
        config_json = parse_optional_json_header(request.headers.get("x-semantic-config-json"), "X-Semantic-Config-Json")
        metrics_json = parse_optional_json_header(
            request.headers.get("x-semantic-metrics-json"),
            "X-Semantic-Metrics-Json",
        )
        merged_config = dict(config_json or {})
        merged_config["base_model_key"] = base_model_spec.key
        model = register_model_bundle_bytes(
            db,
            slug=slug,
            base_model=base_model_spec.base_model,
            embedding_dim=base_model_spec.embedding_dim,
            artifact_bundle_bytes=bundle_bytes,
            dataset_bytes=None,
            source_semantic_data_version=None,
            augmentation_mode="none",
            config_json=merged_config,
            metrics_json=metrics_json,
        )
    except IntegrityError as exc:
        raise HTTPException(status_code=409, detail=f"Semantic model slug '{slug}' already exists.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    loaded_model = get_semantic_model(db, model.id)
    if loaded_model is None:
        raise HTTPException(status_code=500, detail="Model disappeared after registration.")
    return _serialize_semantic_model(loaded_model)


@app.get("/admin/semantic-jobs", response_model=list[SemanticJobSummary], tags=["admin"])
def admin_list_semantic_jobs(
    _: None = Depends(require_admin_token),
    db: Session = Depends(get_db),
) -> list[SemanticJobSummary]:
    return [SemanticJobSummary.model_validate(job) for job in list_semantic_jobs(db)]


@app.get("/admin/semantic-jobs/{job_id}", response_model=SemanticJobDetail, tags=["admin"])
def admin_get_semantic_job(
    job_id: str,
    _: None = Depends(require_admin_token),
    db: Session = Depends(get_db),
) -> SemanticJobDetail:
    job = get_semantic_job(db, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Semantic job not found.")
    return SemanticJobDetail.model_validate(job)


@app.post("/admin/semantic-jobs/train", response_model=SemanticJobDetail, status_code=status.HTTP_201_CREATED, tags=["admin"])
def admin_create_train_job(
    payload: SemanticTrainJobCreate,
    _: None = Depends(require_admin_token),
    db: Session = Depends(get_db),
) -> SemanticJobDetail:
    try:
        base_model_spec = get_semantic_base_model(payload.base_model_key)
        job = create_train_job(
            db,
            requested_by=payload.requested_by,
            dataset_id=payload.dataset_id,
            model_slug=payload.model_slug,
            base_model_key=payload.base_model_key,
            base_model=base_model_spec.base_model,
            embedding_dim=base_model_spec.embedding_dim,
            skip_fine_tune=payload.skip_fine_tune,
            epochs=payload.epochs,
            batch_size=payload.batch_size,
            promote_after_register=payload.promote_after_register,
            embed_batch_size=payload.embed_batch_size,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return SemanticJobDetail.model_validate(job)


@app.post("/admin/semantic-jobs/dataset", response_model=SemanticJobDetail, status_code=status.HTTP_201_CREATED, tags=["admin"])
def admin_create_dataset_job(
    payload: SemanticDatasetJobCreate,
    _: None = Depends(require_admin_token),
    db: Session = Depends(get_db),
) -> SemanticJobDetail:
    try:
        job = create_dataset_job(
            db,
            requested_by=payload.requested_by,
            dataset_slug=payload.dataset_slug,
            augmentation_mode=payload.augmentation_mode,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return SemanticJobDetail.model_validate(job)


@app.post("/admin/semantic-jobs/promote", response_model=SemanticJobDetail, status_code=status.HTTP_201_CREATED, tags=["admin"])
def admin_create_promote_job(
    payload: SemanticPromoteJobCreate,
    _: None = Depends(require_admin_token),
    db: Session = Depends(get_db),
) -> SemanticJobDetail:
    try:
        job = create_promote_job(
            db,
            requested_by=payload.requested_by,
            model_id=payload.model_id,
            embed_batch_size=payload.embed_batch_size,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return SemanticJobDetail.model_validate(job)


@app.post(
    "/admin/semantic-models/{model_id}/promote",
    response_model=SemanticModelPromotionAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["admin"],
)
def admin_promote_semantic_model(
    model_id: str,
    payload: SemanticModelPromoteRequest,
    _: None = Depends(require_admin_token),
    db: Session = Depends(get_db),
) -> SemanticModelPromotionAccepted:
    try:
        job = create_promote_job(
            db,
            requested_by=payload.requested_by,
            model_id=model_id,
            embed_batch_size=payload.embed_batch_size,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return SemanticModelPromotionAccepted(
        accepted=True,
        job_id=job.id,
        model_id=model_id,
        status=SEMANTIC_JOB_STATUS_PENDING,
    )


# ---------------------------------------------------------------------------
# Routes — search
# ---------------------------------------------------------------------------


@app.get("/search", response_model=list[CardMatch])
@log_performance(logger=logger)
def search_cards(
    q: str = Query(..., max_length=MAX_QUERY_LENGTH),
    db: Session = Depends(get_db),
    limit: int = Query(10, ge=1, le=MAX_SEARCH_LIMIT),
    offset: int = Query(0, ge=0),
) -> list[CardMatch]:
    _ensure_schema_ready()
    if not q.strip():
        return []

    q_like = f"%{q}%"
    faces = (
        db.query(CardFace)
        .options(joinedload(CardFace.card))
        .join(Card, Card.oracle_id == CardFace.oracle_id)
        .filter((CardFace.name.ilike(q_like)) | (Card.name.ilike(q_like)))
        .order_by(Card.edhrec_rank.asc().nulls_last(), Card.name.asc(), CardFace.face_ix.asc(), CardFace.name.asc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return [
        CardMatch(
            name=face.name,
            oracle_id=face.card.oracle_id,
            scryfall_id=face.card.scryfall_id,
            face_ix=face.face_ix,
            image_side=_image_side_for_face(face.card.layout, face.face_ix),
            rank=face.card.edhrec_rank,
        )
        for face in faces
    ]


@app.get("/card/{oracle_id}")
@log_performance(logger=logger)
def get_card_by_id(oracle_id: str, db: Session = Depends(get_db)) -> dict[str, object]:
    _ensure_schema_ready()
    card = db.query(Card).options(joinedload(Card.faces)).filter(Card.oracle_id == oracle_id).first()
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")
    return card.to_dict()


def _parse_rarity(rarity: str | None) -> list[str] | None:
    if rarity is None:
        return None
    chars = list(rarity.lower())
    invalid = [ch for ch in chars if ch not in _RARITY_MAP]
    if invalid:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid rarity characters: {', '.join(invalid)!r}. Use c, u, r, m.",
        )
    if len(chars) != len(set(chars)):
        raise HTTPException(status_code=422, detail="Duplicate rarity characters in rarity filter")
    return [_RARITY_MAP[ch] for ch in chars]


def _parse_code_filter(raw_value: str | None, value_map: dict[str, str], field_name: str) -> list[str] | None:
    if raw_value is None:
        return None

    codes = [value for value in raw_value.strip().lower() if value]
    if not codes:
        return None

    invalid = [code for code in codes if code not in value_map]
    if invalid:
        raise HTTPException(status_code=422, detail=f"Invalid {field_name} codes: {', '.join(invalid)}")
    if len(codes) != len(set(codes)):
        raise HTTPException(status_code=422, detail=f"Duplicate {field_name} codes in filter")

    return [value_map[code] for code in codes]


@app.get("/similar-cards", response_model=SimilarCardsPage)
@log_performance(logger=logger)
def get_similar_cards(
    db: Session = Depends(get_db),
    oracle_id: str | None = None,
    face_ix: int = Query(0, ge=0),
    q: str | None = Query(None, max_length=MAX_QUERY_LENGTH),
    limit: int = Query(20, ge=1, le=MAX_SIMILAR_CARDS_LIMIT),
    offset: int = Query(0, ge=0),
    card_type: str | None = None,
    colors: str | None = None,
    cmc_min: float | None = None,
    cmc_max: float | None = None,
    format: str | None = None,
    rarity: str | None = None,
    color_feature: str = "identity",
    match_mode: str = "at_least",
) -> SimilarCardsPage:
    _ensure_schema_ready()
    if oracle_id is None and not (q and q.strip()):
        raise HTTPException(status_code=422, detail="Provide either oracle_id or q")

    rarity_list = _parse_rarity(rarity)
    card_type_list = _parse_code_filter(card_type, _CARD_TYPE_MAP, "card type")
    format_list = _parse_code_filter(format, _FORMAT_MAP, "format")

    index = _get_semantic_index()
    if index is None:
        raise HTTPException(status_code=503, detail="Semantic index not available")

    if oracle_id is not None:
        results = index.similar_to_face(
            (oracle_id, face_ix),
            limit=limit + offset + 1,
            db=db,
            card_type=card_type_list,
            colors=colors,
            cmc_min=cmc_min,
            cmc_max=cmc_max,
            format=format_list,
            rarity=rarity_list,
            color_feature=color_feature,
            match_mode=match_mode,
        )
    else:
        assert q is not None  # guarded by the 422 check above
        results = index.search_oracle(
            q,
            limit=limit + offset + 1,
            db=db,
            card_type=card_type_list,
            colors=colors,
            cmc_min=cmc_min,
            cmc_max=cmc_max,
            format=format_list,
            rarity=rarity_list,
            color_feature=color_feature,
            match_mode=match_mode,
        )

    page_results = results[offset : offset + limit]
    has_more = len(results) > offset + limit
    return SimilarCardsPage(items=_to_similar_cards(page_results, db), has_more=has_more)

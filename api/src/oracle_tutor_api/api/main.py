from __future__ import annotations

import gc
import hmac
import importlib.metadata
import ipaddress
import logging
import os
import pickle
import resource
import socket
import subprocess
import sys
import tempfile
import threading
import time
from contextlib import asynccontextmanager
from typing import List, Optional

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import or_
from sqlalchemy.exc import OperationalError, TimeoutError as SQLTimeoutError
from sqlalchemy.orm import Session

from ..core.config import (
    SCHEMA_WAIT_INTERVAL_SECONDS,
    SCHEMA_WAIT_TIMEOUT_SECONDS,
    WORKER_REBUILD_PATH,
    WORKER_TRIGGER_ALLOWLIST,
    WORKER_TRIGGER_TOKEN,
    ensure_data_dir,
)
from ..core.database import SessionLocal, get_db
from ..core.db_init import INIT_MODE_API, init_db, wait_for_migration_ready
from ..core.logging_config import log_performance, setup_loggers
from ..core.models import Card, CardFace, SystemMetadata
from .schemas import CardMatch, CardNameMatch, SimilarCard
from .semantic_router import router as semantic_router
from .tfidf_index import TfidfIndex, build_tfidf_index

setup_loggers()
logger = logging.getLogger("oracle_tutor_api.api")

# Global in-memory TF-IDF index (rebuilt on startup)
_tfidf_index: TfidfIndex | None = None
_tfidf_lock = threading.Lock()
_tfidf_data_version: str | None = None
_tfidf_last_version_check: float = 0.0  # time.monotonic()
_schema_ready: bool = True
_tfidf_rebuild_state_lock = threading.Lock()
_tfidf_rebuild_in_progress: bool = False
_tfidf_rebuild_started_at: float | None = None
_tfidf_rebuild_reason: str | None = None


class RebuildInProgressError(RuntimeError):
    pass


def _rss_mb() -> float:
    """
    Return current process RSS in MiB.

    Prefer psutil for an accurate "current RSS" measurement. Fall back to Linux /proc,
    and lastly to ru_maxrss (peak RSS; monotonic, not suitable for "freed" deltas).
    """
    # 1) Best: psutil (cross-platform, current RSS).
    try:
        import psutil  # type: ignore

        return float(psutil.Process().memory_info().rss) / (1024 * 1024)
    except Exception:
        pass

    # 2) Linux fallback: /proc/self/statm (current RSS in pages).
    try:
        with open("/proc/self/statm", "r") as f:
            parts = f.read().strip().split()
        if len(parts) >= 2:
            rss_pages = int(parts[1])
            page_size = os.sysconf("SC_PAGE_SIZE")  # bytes
            return float(rss_pages * page_size) / (1024 * 1024)
    except Exception:
        pass

    # 3) Last resort: ru_maxrss (peak RSS; will not decrease).
    try:
        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        # Linux: KB, macOS: bytes
        if rss > 2**20:
            return float(rss) / (1024 * 1024)
        return float(rss) / 1024
    except Exception:
        return 0.0


def _gc_collect_and_log(context: str) -> None:
    """Run gc.collect() and log memory usage and objects collected."""
    before_mb = _rss_mb()
    collected = gc.collect()
    after_mb = _rss_mb()
    freed_mb = max(0.0, before_mb - after_mb)
    logger.info(
        "Memory: %.1f MiB (GC collected %d objects, %.1f MiB freed) [%s]",
        after_mb,
        collected,
        freed_mb,
        context,
    )


def _malloc_trim_best_effort(context: str) -> None:
    """
    Best-effort attempt to return freed heap pages back to the OS (Linux/glibc).

    This can help RSS drop after large temporary allocations, but is allocator- and
    platform-dependent. Guarded by env var to avoid surprising behavior.
    """
    if os.getenv("ORACLE_TUTOR_API_MALLOC_TRIM", "").strip() not in ("1", "true", "TRUE", "yes", "YES"):
        return
    try:
        import ctypes

        before_mb = _rss_mb()
        libc = ctypes.CDLL("libc.so.6")
        res = int(libc.malloc_trim(0))
        after_mb = _rss_mb()
        logger.info(
            "Memory: %.1f MiB (malloc_trim=%s, %.1f MiB freed) [%s]",
            after_mb,
            "ok" if res == 1 else "noop",
            max(0.0, before_mb - after_mb),
            context,
        )
    except Exception:
        # Best-effort only.
        return


def _get_db_data_version(db: Session) -> str | None:
    meta = db.get(SystemMetadata, "scryfall_data")
    if not meta:
        return None
    last_ing = ""
    try:
        last_ing = meta.last_ingestion.isoformat() if meta.last_ingestion else ""
    except Exception:
        last_ing = ""
    return f"{meta.schema_version or ''}|{meta.data_updated_at or ''}|{last_ing}"


def _mark_rebuild_start(reason: str) -> bool:
    global _tfidf_rebuild_in_progress, _tfidf_rebuild_reason, _tfidf_rebuild_started_at
    with _tfidf_rebuild_state_lock:
        if _tfidf_rebuild_in_progress:
            return False
        _tfidf_rebuild_in_progress = True
        _tfidf_rebuild_reason = reason
        _tfidf_rebuild_started_at = time.monotonic()
        return True


def _mark_rebuild_done() -> float | None:
    global _tfidf_rebuild_in_progress, _tfidf_rebuild_reason, _tfidf_rebuild_started_at
    with _tfidf_rebuild_state_lock:
        duration: float | None = None
        if _tfidf_rebuild_started_at is not None:
            duration = max(0.0, time.monotonic() - _tfidf_rebuild_started_at)
        _tfidf_rebuild_in_progress = False
        _tfidf_rebuild_reason = None
        _tfidf_rebuild_started_at = None
        return duration


def _is_rebuild_in_progress() -> bool:
    with _tfidf_rebuild_state_lock:
        return _tfidf_rebuild_in_progress


def _rebuild_tfidf_index(db: Session | None = None, *, reason: str) -> str | None:
    global _tfidf_data_version, _tfidf_index, _tfidf_last_version_check
    if not _mark_rebuild_start(reason):
        raise RebuildInProgressError("TF-IDF rebuild already in progress.")

    close_after = False
    if db is None:
        db = SessionLocal()
        close_after = True

    logger.info("Starting TF-IDF rebuild. reason=%s", reason)
    try:
        logger.info("TF-IDF rebuild memory before build: %.1f MiB", _rss_mb())
        use_subprocess = os.getenv("ORACLE_TUTOR_API_TFIDF_REBUILD_IN_SUBPROCESS", "").strip() in ("1", "true", "TRUE", "yes", "YES")
        if use_subprocess:
            try:
                with tempfile.NamedTemporaryFile(delete=False, suffix=".pkl") as tmp:
                    pkl_path = tmp.name
                proc = subprocess.run(
                    [sys.executable, "-m", "oracle_tutor_api.api.tfidf_build_standalone", pkl_path],
                    env=os.environ,
                    capture_output=True,
                    text=True,
                    timeout=300,
                )
                if proc.returncode == 0:
                    with open(pkl_path, "rb") as f:
                        new_index = pickle.load(f)
                    logger.info("TF-IDF index loaded from subprocess pickle")
                else:
                    logger.warning(
                        "Subprocess TF-IDF build failed (rc=%s), falling back to in-process build. stderr=%s",
                        proc.returncode,
                        proc.stderr[-500:] if proc.stderr else "",
                    )
                    new_index = build_tfidf_index(db)
                try:
                    os.unlink(pkl_path)
                except OSError:
                    pass
            except (subprocess.TimeoutExpired, OSError, pickle.PickleError) as e:
                logger.warning("Subprocess TF-IDF build failed (%s), falling back to in-process build", e)
                new_index = build_tfidf_index(db)
        else:
            new_index = build_tfidf_index(db)
        logger.info("TF-IDF rebuild memory after build (pre-swap): %.1f MiB", _rss_mb())
        new_version = _get_db_data_version(db)
        # Atomic swap after successful build.
        with _tfidf_lock:
            old_index = _tfidf_index
            _tfidf_index = new_index
            _tfidf_data_version = new_version
            _tfidf_last_version_check = time.monotonic()
        duration = _mark_rebuild_done()
        logger.info(
            "TF-IDF rebuild completed and swapped. reason=%s version=%s duration_s=%.3f",
            reason,
            new_version,
            duration or 0.0,
        )
        # Prompt GC to free the replaced index and reduce memory footprint.
        # On Linux/glibc, freeing the old index often does not return all memory to the OS
        # (fragmentation, thread arenas), so RSS can stay ~100 MiB above pre-rebuild baseline.
        # Set ORACLE_TUTOR_API_TFIDF_REBUILD_IN_SUBPROCESS=1 to build in a child process and
        # load from pickle so the build’s allocations are fully reclaimed when the child exits.
        del old_index
        _gc_collect_and_log("tfidf_rebuild_post_swap")
        _malloc_trim_best_effort("tfidf_rebuild_post_swap")
        return new_version
    except Exception:
        duration = _mark_rebuild_done()
        logger.warning(
            "TF-IDF rebuild aborted. reason=%s duration_s=%.3f",
            reason,
            duration or 0.0,
        )
        raise
    finally:
        if close_after:
            db.close()


def _extract_host_candidates(request: Request) -> list[str]:
    candidates: list[str] = []
    if request.client and request.client.host:
        candidates.append(request.client.host.strip().lower())

    forwarded_for = request.headers.get("x-forwarded-for", "").strip()
    if forwarded_for:
        first = forwarded_for.split(",")[0].strip().lower()
        if first:
            candidates.append(first)

    real_ip = request.headers.get("x-real-ip", "").strip().lower()
    if real_ip:
        candidates.append(real_ip)

    host = request.headers.get("host", "").split(":")[0].strip().lower()
    if host:
        candidates.append(host)

    out: list[str] = []
    seen: set[str] = set()
    for c in candidates:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out


_DNS_RESOLVE_CACHE: dict[str, tuple[float, list[str]]] = {}
_DNS_CACHE_TTL_SECONDS = 60.0


def _is_ip_address(s: str) -> bool:
    """Return True if s is a valid IPv4 or IPv6 address."""
    s = (s or "").strip()
    if not s:
        return False
    try:
        ipaddress.ip_address(s)
        return True
    except ValueError:
        return False


def _resolve_hostname_to_ips(hostname: str) -> list[str]:
    """
    Resolve hostname to list of IP addresses (IPv4 and IPv6).
    Uses in-memory cache to avoid hammering internal DNS on every request.
    """
    hostname = hostname.strip().lower()
    if not hostname or _is_ip_address(hostname):
        return []
    now = time.monotonic()
    if hostname in _DNS_RESOLVE_CACHE:
        cached_at, ips = _DNS_RESOLVE_CACHE[hostname]
        if now - cached_at < _DNS_CACHE_TTL_SECONDS:
            return ips
    try:
        # Get both IPv4 and IPv6 addresses
        results = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
        ips: list[str] = []
        seen: set[str] = set()
        for family, _, _, _, sockaddr in results:
            raw = sockaddr[0] if sockaddr else ""
            addr = str(raw) if isinstance(raw, str) else ""
            if addr and addr not in seen:
                seen.add(addr)
                ips.append(addr.lower() if ":" in addr else addr)
        _DNS_RESOLVE_CACHE[hostname] = (now, ips)
        return ips
    except (socket.gaierror, OSError) as e:
        logger.debug("DNS resolution failed for %s: %s", hostname, e)
        return []


def _host_matches_allowlist(host: str, allowlist: tuple[str, ...]) -> bool:
    host_norm = host.strip().lower()
    if not host_norm:
        return False
    for allowed in allowlist:
        allow = allowed.strip().lower()
        if not allow:
            continue
        # Direct string match (hostname or IP)
        if host_norm == allow:
            return True
        if host_norm.endswith(f".{allow}"):
            return True
        # Allowlist has hostname but request has IP: resolve hostname and check IP
        if not _is_ip_address(allow) and _is_ip_address(host_norm):
            resolved_ips = _resolve_hostname_to_ips(allow)
            for ip in resolved_ips:
                if host_norm == ip:
                    return True
                # Handle IPv6 variations (e.g. ::1 vs 0:0:0:0:0:0:0:1)
                try:
                    if ipaddress.ip_address(host_norm) == ipaddress.ip_address(ip):
                        return True
                except ValueError:
                    pass
    return False


def _require_internal_worker_auth(request: Request) -> None:
    candidates = _extract_host_candidates(request)
    if not WORKER_TRIGGER_TOKEN:
        logger.warning(
            "Rejected internal TF-IDF rebuild request: worker token not configured. source_candidates=%s",
            candidates,
        )
        raise HTTPException(status_code=503, detail="Worker trigger token is not configured.")
    if not WORKER_TRIGGER_ALLOWLIST:
        logger.warning(
            "Rejected internal TF-IDF rebuild request: allowlist not configured. source_candidates=%s",
            candidates,
        )
        raise HTTPException(status_code=503, detail="Worker trigger allowlist is not configured.")

    token = request.headers.get("x-worker-token", "")
    if not hmac.compare_digest(token, WORKER_TRIGGER_TOKEN):
        logger.warning(
            "Rejected internal TF-IDF rebuild request: invalid worker token. source_candidates=%s",
            candidates,
        )
        raise HTTPException(status_code=401, detail="Unauthorized worker token.")

    if not any(_host_matches_allowlist(host, WORKER_TRIGGER_ALLOWLIST) for host in candidates):
        logger.warning(
            "Rejected internal TF-IDF rebuild request: source not allowlisted. source_candidates=%s allowlist=%s",
            candidates,
            WORKER_TRIGGER_ALLOWLIST,
        )
        raise HTTPException(status_code=403, detail="Worker source is not allowlisted.")
    logger.info("Authorized internal TF-IDF rebuild request. source_candidates=%s", candidates)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _schema_ready, _tfidf_index
    logger.info("API starting...")

    ensure_data_dir()
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
            _schema_ready = False
        else:
            _schema_ready = True
    except Exception as e:
        logger.error("DB init failed: %s", e, exc_info=True)
        _schema_ready = False

    # Initial TF-IDF build (best-effort; API can still start and lazily build later).
    try:
        logger.info("Building TF-IDF index at startup...")
        startup_version = _rebuild_tfidf_index(reason="startup")
        logger.info("TF-IDF startup build completed. version=%s", startup_version)
    except Exception as e:
        logger.error("TF-IDF build failed (oracle search disabled until rebuild): %s", e, exc_info=True)
        _tfidf_index = None

    try:
        from ..semantic.index import get_semantic_index

        get_semantic_index()
    except ImportError:
        logger.info("Semantic runtime dependencies not installed; semantic endpoints remain unavailable.")
    except Exception as e:
        logger.warning("Semantic index startup load failed: %s", e, exc_info=True)

    # Reclaim memory after startup build.
    _gc_collect_and_log("startup")

    yield

    # Shutdown
    logger.info("API shutting down...")


app = FastAPI(lifespan=lifespan, title="oracle-tutor api")
app.include_router(semantic_router)


# ---- Exception Handlers ----

@app.exception_handler(SQLTimeoutError)
@app.exception_handler(OperationalError)
async def database_connection_exception_handler(request: Request, exc: Exception):
    """
    Handle database connection pool exhaustion and other database connection errors gracefully.
    Returns 503 Service Unavailable instead of crashing.
    """
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


# CORS:
# - For Railway + same-origin (recommended): do NOT enable CORS.
# - If you truly need cross-origin access, set ORACLE_TUTOR_API_CORS_ORIGINS to a
#   comma-separated list (e.g. "https://example.com,https://www.example.com").
cors_origins_env = os.getenv("ORACLE_TUTOR_API_CORS_ORIGINS", "").strip()
if cors_origins_env:
    origins = [o.strip() for o in cors_origins_env.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=False,  # public API; avoid CSRF footguns
        allow_methods=["*"],
        allow_headers=["*"],
    )


# ---- Meta ----

@app.get("/", tags=["meta"])
def root() -> dict[str, str]:
    return {"service": "oracle-tutor-api"}


@app.get("/health", tags=["meta"])
def health() -> dict[str, str]:
    return {"status": "ok"}


try:
    API_VERSION = importlib.metadata.version("oracle-tutor-api")
except importlib.metadata.PackageNotFoundError:
    API_VERSION = "1.2.0"  # Fallback if package not installed


@app.get("/version", tags=["meta"])
def version() -> dict[str, str]:
    return {"version": API_VERSION}


@app.get("/favicon.ico")
def favicon():
    return Response(status_code=204)


def _require_index(db: Session | None = None) -> TfidfIndex:
    """
    Ensure the global TF-IDF index is present and (eventually) consistent with DB updates.

    The worker updates `system_metadata(key='scryfall_data')` when ingestion completes.
    We poll that row (throttled) and rebuild this in-memory index when it changes.

    If a request DB session is provided, reuse it to avoid opening an extra connection
    for the version check/rebuild.
    """
    global _tfidf_index, _tfidf_data_version, _tfidf_last_version_check

    check_every_s = float(os.getenv("ORACLE_TUTOR_API_INDEX_VERSION_CHECK_SECONDS", "30"))
    now = time.monotonic()
    should_check = (_tfidf_index is None) or ((now - _tfidf_last_version_check) >= check_every_s)

    if should_check:
        # Lazy-build so the API can still function if DB wasn't ready at startup,
        # and so tests can seed data before first oracle query.
        try:
            if _is_rebuild_in_progress():
                raise HTTPException(status_code=503, detail="TF-IDF rebuild in progress. Please retry shortly.")

            _tfidf_last_version_check = now
            close_after = False
            if db is None:
                db = SessionLocal()
                close_after = True
            try:
                db_version = _get_db_data_version(db)
                if _tfidf_index is None:
                    _rebuild_tfidf_index(db, reason="lazy_initial")
                elif db_version and (_tfidf_data_version is None or db_version != _tfidf_data_version):
                    logger.info("DB data version changed; rebuilding TF-IDF index...")
                    _rebuild_tfidf_index(db, reason="lazy_version_change")
            finally:
                if close_after:
                    db.close()
        except RebuildInProgressError:
            raise HTTPException(status_code=503, detail="TF-IDF rebuild in progress. Please retry shortly.") from None
        except Exception as e:
            raise HTTPException(status_code=503, detail=f"TF-IDF index not loaded yet: {e}") from e

    # mypy/pydantic: at this point we should have an index unless build failed
    if _tfidf_index is None:
        raise HTTPException(status_code=503, detail="TF-IDF index not loaded yet.")
    return _tfidf_index


def _ensure_schema_ready() -> None:
    global _schema_ready
    if _schema_ready:
        return
    if wait_for_migration_ready(timeout_s=0.0, interval_s=SCHEMA_WAIT_INTERVAL_SECONDS):
        _schema_ready = True
        return
    raise HTTPException(status_code=503, detail="Schema migration in progress. Please retry shortly.")


def _ensure_tfidf_available_for_queries() -> None:
    if _is_rebuild_in_progress():
        raise HTTPException(status_code=503, detail="TF-IDF rebuild in progress. Please retry shortly.")


def _is_postgres(db: Session) -> bool:
    return bool(db.bind and db.bind.dialect.name == "postgresql")


def _results_to_similar_cards(
    results: list[tuple[int, float]],
    db: Session,
) -> List[SimilarCard]:
    """Convert TF-IDF results (face_id, score) to SimilarCard list."""
    if not results:
        return []
    target_face_ids = [r[0] for r in results]
    id_to_score = {r[0]: r[1] for r in results}
    cards_data = (
        db.query(CardFace, Card)
        .join(Card, CardFace.card_id == Card.id)
        .filter(CardFace.id.in_(target_face_ids))
        .all()
    )
    cards_map = {face.id: (face, card) for face, card in cards_data}
    out: List[SimilarCard] = []
    for face_id in target_face_ids:
        if face_id not in cards_map:
            continue
        face, card = cards_map[face_id]
        sim = float(id_to_score.get(face_id, 0.0))
        out.append(
            SimilarCard(
                id=card.id,
                name=face.name,
                card_name=card.name,
                similarity=sim,
                rank=card.edhrec_rank,
                type_line=face.type_line,
                mana_cost=face.mana_cost,
                oracle_text=face.oracle_text,
                power=face.power,
                toughness=face.toughness,
                layout=card.layout,
                rarity=card.rarity,
                colors=face.colors,
                legalities=card.legalities,
                uniqueness=card.uniqueness,
            )
        )
    return out


@app.post(WORKER_REBUILD_PATH, include_in_schema=False)
def internal_rebuild_tfidf(request: Request) -> dict[str, object]:
    source_candidates = _extract_host_candidates(request)
    logger.info(
        "Received internal TF-IDF rebuild request. path=%s source_candidates=%s",
        request.url.path,
        source_candidates,
    )
    _require_internal_worker_auth(request)
    _ensure_schema_ready()
    try:
        version = _rebuild_tfidf_index(reason="internal_worker_trigger")
        logger.info("Internal TF-IDF rebuild completed. version=%s", version)
    except RebuildInProgressError:
        logger.warning("Rejected overlapping internal TF-IDF rebuild request with 409.")
        raise HTTPException(status_code=409, detail="TF-IDF rebuild already in progress.") from None
    except Exception as e:
        logger.error("Internal TF-IDF rebuild failed: %s", e, exc_info=True)
        raise HTTPException(status_code=503, detail="TF-IDF rebuild failed.") from e
    return {"status": "ok", "rebuilt": True, "version": version}


# ---- Endpoints ----

@app.get("/search", response_model=List[CardMatch])
@log_performance(logger=logger)
def search_cards(q: str, limit: int = 5, db: Session = Depends(get_db)):
    _ensure_schema_ready()
    if not q.strip():
        return []
    limit = max(1, min(limit, 25))

    if _is_postgres(db):
        distance = Card.name.op("<->")(q)
        results = (
            db.query(Card, distance.label("dist"))
            .filter(or_(Card.name.op("%")(q), Card.name.ilike(f"%{q}%")))
            .order_by(distance, Card.edhrec_rank.asc().nulls_last())
            .limit(limit)
            .all()
        )
        return [
            CardMatch(name=c.name, id=c.id, rank=c.edhrec_rank, similarity=float(1.0 - dist))
            for c, dist in results
        ]

    # Non-Postgres fallback (tests): basic contains.
    cards = (
        db.query(Card)
        .filter(Card.name.ilike(f"%{q}%"))
        .order_by(Card.edhrec_rank.asc().nulls_last(), Card.name.asc())
        .limit(limit)
        .all()
    )
    return [CardMatch(name=c.name, id=c.id, rank=c.edhrec_rank, similarity=1.0) for c in cards]


@app.get("/suggest-names", response_model=List[CardNameMatch])
@log_performance(logger=logger)
def search_card_names(q: str, limit: int = 5, offset: int = 0, db: Session = Depends(get_db)):
    _ensure_schema_ready()
    if not q.strip():
        return []
    limit = max(1, min(limit, 25))
    offset = max(0, offset)

    if _is_postgres(db):
        distance = Card.name.op("<->")(q)
        cards = (
            db.query(Card.name, Card.id)
            .filter(or_(Card.name.op("%")(q), Card.name.ilike(f"%{q}%")))
            .order_by(distance, Card.edhrec_rank.asc().nulls_last())
            .offset(offset)
            .limit(limit)
            .all()
        )
        return [CardNameMatch(name=c.name, id=c.id) for c in cards]

    cards = (
        db.query(Card.name, Card.id)
        .filter(Card.name.ilike(f"%{q}%"))
        .order_by(Card.name.asc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return [CardNameMatch(name=c.name, id=c.id) for c in cards]


@app.get("/card/{card_id}")
@log_performance(logger=logger)
def get_card_by_id(card_id: str, db: Session = Depends(get_db)):
    _ensure_schema_ready()
    card = db.get(Card, card_id)
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")
    # Ensure faces are loaded (relationship might be lazy)
    _ = card.faces
    return card.to_dict()


@app.get("/similar-cards/{card_id}", response_model=List[SimilarCard])
@log_performance(logger=logger)
def get_similar_cards(
    card_id: str,
    face_index: int = 0,
    limit: int = 20,
    offset: int = 0,
    card_type: Optional[str] = Query(None),
    colors: Optional[str] = Query(None),
    format: Optional[str] = Query(None),
    cmc_min: Optional[float] = Query(None),
    cmc_max: Optional[float] = Query(None),
    rarity: Optional[str] = Query(None),
    match_mode: str = Query("at_least"),
    color_feature: str = Query("identity"),
    db: Session = Depends(get_db),
):
    _ensure_schema_ready()
    _ensure_tfidf_available_for_queries()
    index = _require_index(db)

    target_card = db.get(Card, card_id)
    if not target_card:
        raise HTTPException(status_code=404, detail="Card not found")

    faces = (
        db.query(CardFace)
        .filter(CardFace.card_id == target_card.id)
        .order_by(CardFace.id.asc())
        .all()
    )
    if not faces:
        raise HTTPException(status_code=404, detail="Card has no faces data")
    if face_index < 0 or face_index >= len(faces):
        raise HTTPException(status_code=400, detail="Invalid face_index")

    seed_face = faces[face_index]
    results = index.similar(
        seed_face_id=seed_face.id,
        exclude_card_id=target_card.id,
        limit=max(1, min(limit, 100)),
        offset=max(0, offset),
        card_type=card_type,
        colors=colors,
        format=format,
        cmc_min=cmc_min,
        cmc_max=cmc_max,
        rarity=rarity,
        match_mode=match_mode,
        color_feature=color_feature,
    )
    return _results_to_similar_cards(results, db)


@app.get("/search-oracle", response_model=List[SimilarCard])
@log_performance(logger=logger)
def search_oracle_text(
    q: str,
    limit: int = 20,
    offset: int = 0,
    card_type: Optional[str] = Query(None),
    colors: Optional[str] = Query(None),
    format: Optional[str] = Query(None),
    cmc_min: Optional[float] = Query(None),
    cmc_max: Optional[float] = Query(None),
    rarity: Optional[str] = Query(None),
    match_mode: str = Query("at_least"),
    color_feature: str = Query("identity"),
    db: Session = Depends(get_db),
):
    _ensure_schema_ready()
    _ensure_tfidf_available_for_queries()
    if not q.strip():
        return []

    index = _require_index(db)
    results = index.search(
        query=q,
        limit=max(1, min(limit, 100)),
        offset=max(0, offset),
        card_type=card_type,
        colors=colors,
        format=format,
        cmc_min=cmc_min,
        cmc_max=cmc_max,
        rarity=rarity,
        match_mode=match_mode,
        color_feature=color_feature,
    )
    return _results_to_similar_cards(results, db)

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass
from typing import Callable, Literal

CheckStatus = Literal["ok", "warn", "fail", "skipped", "pending"]


# Waking a scale-from-zero deploy takes tens of seconds; the frontend waits 30s
# before declaring the API down for the same reason. Overridable for operators
# on a warm deploy who want the boot screen to fail fast.
_API_WAKE_BUDGET_S = float(os.getenv("OT_TUI_API_WAKE_BUDGET", "90"))
_API_POLL_INTERVAL_S = float(os.getenv("OT_TUI_API_POLL_INTERVAL", "2"))
_API_REQUEST_TIMEOUT_S = 10.0


@dataclass
class CheckResult:
    name: str
    status: CheckStatus = "pending"
    detail: str = ""
    latency_ms: int = 0


async def _run_blocking(fn: Callable[[], None]) -> None:
    await asyncio.get_running_loop().run_in_executor(None, fn)


def _redact_db_url(url: str) -> str:
    """postgresql+psycopg://user:password@host:port/db → postgresql+psycopg://user:***@host:port/db"""
    try:
        scheme, rest = url.split("://", 1)
    except ValueError:
        return url
    if "@" not in rest:
        return url
    creds, host_and_path = rest.split("@", 1)
    if ":" in creds:
        user, _ = creds.split(":", 1)
        return f"{scheme}://{user}:***@{host_and_path}"
    return url


def _db_target() -> str:
    explicit = os.getenv("DATABASE_URL")
    if explicit:
        return _redact_db_url(explicit)
    user = os.getenv("DB_USER", "oracle")
    host = os.getenv("DB_HOST", "localhost")
    port = os.getenv("DB_PORT", "5432")
    name = os.getenv("DB_NAME", "mtg_search")
    return f"postgresql+psycopg://{user}:***@{host}:{port}/{name}"


async def check_db() -> CheckResult:
    name = "Database"
    start = time.perf_counter()
    target = _db_target()
    try:
        from sqlalchemy import text

        from ..core.database import SessionLocal

        def _probe() -> None:
            with SessionLocal() as db:
                db.execute(text("SELECT 1")).scalar()

        await _run_blocking(_probe)
        return CheckResult(name=name, status="ok", detail=target, latency_ms=int((time.perf_counter() - start) * 1000))
    except Exception as exc:  # noqa: BLE001
        return CheckResult(name=name, status="fail", detail=f"{target}  —  {type(exc).__name__}: {exc}", latency_ms=int((time.perf_counter() - start) * 1000))


async def check_storage() -> CheckResult:
    name = "Artifact storage"
    start = time.perf_counter()
    required = ("SEMANTIC_ARTIFACT_ENDPOINT", "SEMANTIC_ARTIFACT_ACCESS_KEY_ID", "SEMANTIC_ARTIFACT_SECRET_ACCESS_KEY", "SEMANTIC_ARTIFACT_BUCKET")
    missing = [k for k in required if not os.getenv(k)]
    if missing:
        return CheckResult(name=name, status="skipped", detail=f"missing env: {', '.join(missing)}", latency_ms=0)
    endpoint = os.getenv("SEMANTIC_ARTIFACT_ENDPOINT", "").rstrip("/")
    bucket = os.getenv("SEMANTIC_ARTIFACT_BUCKET", "")
    target = f"s3://{bucket} @ {endpoint}"
    try:
        from ..core.config import artifact_bucket_client, artifact_bucket_name

        def _probe() -> None:
            client = artifact_bucket_client()
            client.head_bucket(Bucket=artifact_bucket_name())

        await _run_blocking(_probe)
        return CheckResult(name=name, status="ok", detail=target, latency_ms=int((time.perf_counter() - start) * 1000))
    except Exception as exc:  # noqa: BLE001
        return CheckResult(name=name, status="fail", detail=f"{target}  —  {type(exc).__name__}: {exc}", latency_ms=int((time.perf_counter() - start) * 1000))


async def check_api() -> CheckResult:
    """Probe the API, waiting out a scale-from-zero cold start.

    The public deploy sleeps when idle. Waking it takes tens of seconds, during
    which the edge answers 502/503 or the connection times out — none of which
    mean the service is broken. So the public probe polls until the API answers
    or the budget runs out, rather than reporting a sleeping service as down.
    A 4xx is not a cold start (bad URL, bad route), so it fails fast.
    """
    name = "API"
    start = time.perf_counter()
    public = os.getenv("OT_PUBLIC_URL", "").strip().rstrip("/")
    try:
        import httpx

        # Every failure is reported, not just the last one. Reporting only the
        # final candidate made a failing remote invisible behind the localhost
        # fallback, which reads as "it never checked the remote at all".
        errors: list[str] = []
        async with httpx.AsyncClient() as client:
            if public:
                url = f"{public}/api/health"
                deadline = time.monotonic() + _API_WAKE_BUDGET_S
                attempts = 0
                pending = ""
                while True:
                    attempts += 1
                    try:
                        response = await client.get(url, timeout=_API_REQUEST_TIMEOUT_S)
                        if response.status_code == 200:
                            waited = int(time.perf_counter() - start)
                            detail = f"{url}  (200)"
                            if attempts > 1:
                                detail = f"{url}  (200, awake after {waited}s / {attempts} tries)"
                            return CheckResult(
                                name=name,
                                status="ok",
                                detail=detail,
                                latency_ms=int((time.perf_counter() - start) * 1000),
                            )
                        if response.status_code < 500:
                            errors.append(f"{url}  ({response.status_code})")
                            break
                        pending = f"{url}  ({response.status_code}, waking)"
                    except Exception as exc:  # noqa: BLE001
                        pending = f"{url}  —  {type(exc).__name__} (waking)"
                    if time.monotonic() >= deadline:
                        errors.append(f"{pending}; gave up after {_API_WAKE_BUDGET_S:.0f}s")
                        break
                    await asyncio.sleep(_API_POLL_INTERVAL_S)

            url = "http://localhost:8000/health"
            try:
                response = await client.get(url, timeout=_API_REQUEST_TIMEOUT_S)
                if response.status_code == 200:
                    return CheckResult(
                        name=name,
                        status="ok",
                        detail=f"{url}  (200)",
                        latency_ms=int((time.perf_counter() - start) * 1000),
                    )
                errors.append(f"{url}  ({response.status_code})")
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{url}  —  {type(exc).__name__}")
        return CheckResult(
            name=name,
            status="skipped",
            detail="   |   ".join(errors) or "no API reachable",
            latency_ms=int((time.perf_counter() - start) * 1000),
        )
    except Exception as exc:  # noqa: BLE001
        return CheckResult(name=name, status="fail", detail=f"{type(exc).__name__}: {exc}", latency_ms=int((time.perf_counter() - start) * 1000))


async def check_modal() -> CheckResult:
    name = "Modal"
    start = time.perf_counter()
    token_id = os.getenv("MODAL_TOKEN_ID", "").strip()
    token_secret = os.getenv("MODAL_TOKEN_SECRET", "").strip()
    if not token_id or not token_secret:
        return CheckResult(name=name, status="skipped", detail="MODAL_TOKEN_ID / MODAL_TOKEN_SECRET not set", latency_ms=0)

    environment = os.getenv("MODAL_ENVIRONMENT", "oracle-tutor")
    try:
        from modal import config as modal_config
        from modal.client import Client

        server_url = modal_config.config.get("server_url") or "https://api.modal.com"
        target = f"{server_url}  env:{environment}  token:{token_id[:8]}…"
        await Client.verify.aio(server_url, (token_id, token_secret))
        return CheckResult(name=name, status="ok", detail=target, latency_ms=int((time.perf_counter() - start) * 1000))
    except Exception as exc:  # noqa: BLE001
        target = f"{environment}  token:{token_id[:8]}…"
        return CheckResult(name=name, status="fail", detail=f"{target}  —  {type(exc).__name__}: {exc}", latency_ms=int((time.perf_counter() - start) * 1000))


async def check_cloudflare() -> CheckResult:
    name = "Cloudflare Access"
    start = time.perf_counter()
    team = os.getenv("CF_ACCESS_TEAM_DOMAIN", "").strip()
    aud = os.getenv("CF_ACCESS_AUD", "").strip()
    if not team or not aud:
        return CheckResult(name=name, status="skipped", detail="CF_ACCESS_TEAM_DOMAIN / CF_ACCESS_AUD not set", latency_ms=0)
    target = f"https://{team}  aud:{aud[:8]}…"
    try:
        import httpx

        certs_url = f"https://{team}/cdn-cgi/access/certs"
        async with httpx.AsyncClient(timeout=3.0) as client:
            response = await client.get(certs_url)
        if response.status_code != 200:
            return CheckResult(name=name, status="fail", detail=f"{target}  —  ({response.status_code})", latency_ms=int((time.perf_counter() - start) * 1000))
        keys = response.json().get("keys") or []
        if not keys:
            return CheckResult(name=name, status="fail", detail=f"{target}  —  no signing keys", latency_ms=int((time.perf_counter() - start) * 1000))
        return CheckResult(name=name, status="ok", detail=f"{target}  ({len(keys)} keys)", latency_ms=int((time.perf_counter() - start) * 1000))
    except Exception as exc:  # noqa: BLE001
        return CheckResult(name=name, status="fail", detail=f"{target}  —  {type(exc).__name__}: {exc}", latency_ms=int((time.perf_counter() - start) * 1000))


async def run_all_checks() -> list[CheckResult]:
    return list(await asyncio.gather(check_db(), check_storage(), check_api(), check_modal(), check_cloudflare()))


async def run_all_checks_streaming(on_result: Callable[[CheckResult], None]) -> None:
    """Same as run_all_checks() but invokes `on_result(r)` as each check finishes.

    Lets the TUI render partial results instead of waiting for the slowest probe.
    The callback runs on whichever thread is driving the event loop; the boot
    screen reads the shared list from a different thread, which is safe because
    list.append is GIL-atomic and the callback never mutates earlier entries.
    """
    coros = [check_db(), check_storage(), check_api(), check_modal(), check_cloudflare()]
    for coro in asyncio.as_completed(coros):
        on_result(await coro)

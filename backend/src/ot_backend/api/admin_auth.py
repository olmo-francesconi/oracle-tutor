from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from threading import Lock
from typing import Annotated, Any

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient
from sqlalchemy.orm import Session

from ..core.config import (
    admin_jwt_secret,
    admin_login_lockout_seconds,
    admin_login_max_failures,
    cloudflare_access_aud,
    cloudflare_access_team_domain,
    is_production_env,
)
from ..core.models import AdminIpState

logger = logging.getLogger("ot_backend.api.admin_auth")

_ADMIN_TOKEN_TTL_SECONDS = 8 * 60 * 60
_ALGORITHM = "HS256"
_CLOUDFLARE_ACCESS_ALGORITHMS = ["RS256"]
_security = HTTPBearer(auto_error=False)
_jwks_clients: dict[str, PyJWKClient] = {}
_jwks_lock = Lock()


def admin_token_ttl_seconds() -> int:
    return _ADMIN_TOKEN_TTL_SECONDS


def create_admin_token() -> str:
    secret = admin_jwt_secret()
    if not secret:
        raise RuntimeError("Admin auth is not configured.")

    now = datetime.now(UTC)
    payload = {
        "sub": "admin",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=_ADMIN_TOKEN_TTL_SECONDS)).timestamp()),
    }
    return str(jwt.encode(payload, secret, algorithm=_ALGORITHM))


def get_admin_client_ip(request: Request) -> str:
    real_ip = request.headers.get("x-real-ip", "").strip()
    if real_ip:
        return real_ip

    # Falling through to XFF or request.client.host means nginx isn't in the
    # proxy chain — in production this implies a config regression that would
    # collapse all lockout buckets to one. Log so it surfaces.
    forwarded_for = request.headers.get("x-forwarded-for", "").strip()
    if forwarded_for:
        first_hop = forwarded_for.split(",", 1)[0].strip()
        if first_hop:
            logger.warning("Admin client IP fell back to X-Forwarded-For; X-Real-IP was absent.")
            return first_hop

    if request.client and request.client.host:
        logger.warning("Admin client IP fell back to request.client.host; X-Real-IP was absent.")
        return request.client.host
    return "unknown"


def _utcnow_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def ensure_admin_ip_not_locked_out(db: Session, ip_address: str) -> None:
    current_time = _utcnow_naive()
    state = db.get(AdminIpState, ip_address)
    if state is None:
        return

    if state.banned:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This IP is banned from admin access.",
        )

    if state.locked_until is None:
        return
    if state.locked_until <= current_time:
        db.delete(state)
        db.commit()
        return

    retry_after_seconds = max(1, int((state.locked_until - current_time).total_seconds()))
    raise HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail=f"Too many failed admin login attempts. Try again in {retry_after_seconds} seconds.",
        headers={"Retry-After": str(retry_after_seconds)},
    )


def register_admin_login_failure(db: Session, ip_address: str) -> None:
    current_time = _utcnow_naive()
    state = db.get(AdminIpState, ip_address)
    if state is None:
        state = AdminIpState(ip_address=ip_address, failures=0)
        db.add(state)
    elif state.locked_until is not None and state.locked_until <= current_time:
        # Previous lockout window expired; reset the counter before re-counting.
        state.failures = 0
        state.locked_until = None

    state.failures += 1
    state.last_failure_at = current_time
    if state.failures >= admin_login_max_failures():
        state.locked_until = current_time + timedelta(seconds=admin_login_lockout_seconds())
    db.commit()


def reset_admin_login_failures(db: Session, ip_address: str) -> None:
    state = db.get(AdminIpState, ip_address)
    if state is None:
        return
    # A banned IP that somehow produces a valid login does NOT clear the ban.
    if state.banned:
        return
    db.delete(state)
    db.commit()


def clear_admin_login_attempts_for_tests(db: Session) -> None:
    db.query(AdminIpState).delete()
    db.commit()


def require_admin_token(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_security)],
) -> None:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing admin bearer token.")

    secret = admin_jwt_secret()
    if not secret:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Admin auth is not configured.")

    try:
        payload: dict[str, Any] = jwt.decode(credentials.credentials, secret, algorithms=[_ALGORITHM])
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired admin token.") from exc

    if payload.get("sub") != "admin":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid admin token subject.")


AdminTokenDep = Annotated[None, Depends(require_admin_token)]


def _get_jwks_client(team_domain: str) -> PyJWKClient:
    with _jwks_lock:
        client = _jwks_clients.get(team_domain)
        if client is None:
            client = PyJWKClient(f"https://{team_domain}/cdn-cgi/access/certs")
            _jwks_clients[team_domain] = client
        return client


def require_cloudflare_access(request: Request) -> None:
    team_domain = cloudflare_access_team_domain()
    expected_aud = cloudflare_access_aud()
    if not team_domain or not expected_aud:
        if is_production_env():
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Cloudflare Access is not configured. Set CF_ACCESS_TEAM_DOMAIN and CF_ACCESS_AUD.",
            )
        return

    token = request.headers.get("cf-access-jwt-assertion") or request.cookies.get("CF_Authorization")
    if not token:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Missing Cloudflare Access token.")

    try:
        signing_key = _get_jwks_client(team_domain).get_signing_key_from_jwt(token)
        jwt.decode(
            token,
            signing_key.key,
            algorithms=_CLOUDFLARE_ACCESS_ALGORITHMS,
            audience=expected_aud,
            issuer=f"https://{team_domain}",
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid Cloudflare Access token.") from exc

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ...core.database import get_db
from ...core.models import AnalyticsEvent, ClientErrorEvent
from ..schemas import AnalyticsEventIngest, ClientErrorEventIngest, TelemetryIngestResponse

logger = logging.getLogger("ot_backend.api")

router = APIRouter(prefix="/telemetry", tags=["telemetry"])

MAX_TELEMETRY_DETAILS_BYTES: int = 8_000


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


@router.post("/client-error", response_model=TelemetryIngestResponse, status_code=202)
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


@router.post("/analytics", response_model=TelemetryIngestResponse, status_code=202)
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

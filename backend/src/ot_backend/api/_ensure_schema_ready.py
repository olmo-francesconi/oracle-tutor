from __future__ import annotations

from fastapi import HTTPException

from ..core.config import SCHEMA_WAIT_INTERVAL_SECONDS
from ..core.db_init import wait_for_migration_ready

_schema_ready: bool = False


def ensure_schema_ready() -> None:
    global _schema_ready
    if _schema_ready:
        return
    if wait_for_migration_ready(timeout_s=0.0, interval_s=SCHEMA_WAIT_INTERVAL_SECONDS):
        _schema_ready = True
        return
    raise HTTPException(status_code=503, detail="Schema migration in progress. Please retry shortly.")

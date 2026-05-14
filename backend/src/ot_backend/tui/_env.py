from __future__ import annotations

import os
from pathlib import Path

_BACKEND_ROOT = Path(__file__).resolve().parents[3]


def _load_env_file(env_file: Path) -> None:
    if not env_file.exists():
        return
    try:
        from dotenv import load_dotenv  # type: ignore[import-not-found]

        load_dotenv(env_file, override=False)
        return
    except ImportError:
        pass
    for line in env_file.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def load_env(*, prod: bool) -> None:
    name = ".env.prod" if prod else ".env"
    _load_env_file(_BACKEND_ROOT / name)

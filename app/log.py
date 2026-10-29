"""One line per event on stdout: JSON when piped (Railway parses `level` and the fields), readable in a terminal."""

import json
import sys
import time
import traceback

TTY = sys.stdout.isatty()


def ms_since(start: float) -> int:
    return round((time.monotonic() - start) * 1000)


def log(msg: str, level: str = "info", exc: BaseException | None = None, **fields) -> None:
    if exc is not None:
        fields |= {"error": f"{type(exc).__name__}: {exc}", "traceback": "".join(traceback.format_exception(exc))}
    if not TTY:
        print(json.dumps({"level": level, "msg": msg, **fields}, default=str), flush=True)
        return
    tb = fields.pop("traceback", "").rstrip("\n")
    pairs = " ".join(f"{k}={json.dumps(v) if isinstance(v, str) and (' ' in v or not v) else v}"
                     for k, v in fields.items())
    print(f"{time.strftime('%H:%M:%S')} {level:<7} {msg} {pairs}".rstrip() + (f"\n{tb}" if tb else ""), flush=True)

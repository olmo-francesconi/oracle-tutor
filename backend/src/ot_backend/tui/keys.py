"""Raw-mode stdin keyboard reader.

Unix-only (uses stdlib termios/tty). Returns a small set of normalised tokens
so the TUI loop doesn't have to know about escape sequences.

Important: we read with `os.read(0, 1)` rather than `sys.stdin.read(1)`.
`sys.stdin` is a TextIOWrapper that buffers bytes from the OS — when the
terminal sends `\\x1b[A` as one burst, Python may slurp all 3 bytes into its
buffer on the first read, leaving `select()` to incorrectly report stdin as
empty when we look for the rest of the sequence. `os.read` is unbuffered.
"""
from __future__ import annotations

import os
import select
import sys
import termios
import tty
from types import TracebackType

# Tokens for non-printable keys. Printable keys are returned as the character.
KEY_UP = "UP"
KEY_DOWN = "DOWN"
KEY_LEFT = "LEFT"
KEY_RIGHT = "RIGHT"
KEY_ENTER = "ENTER"
KEY_SPACE = "SPACE"
KEY_ESC = "ESC"
KEY_BACKSPACE = "BACKSPACE"
KEY_TAB = "TAB"
KEY_CTRL_C = "CTRL_C"
KEY_UNKNOWN = "UNKNOWN"

_STDIN_FD = 0
_ESC_SEQ_TIMEOUT = 0.05


class RawTTY:
    """Put stdin into cbreak mode for the duration of the with-block."""

    def __init__(self) -> None:
        self._fd: int | None = None
        self._old: list[int | list[int | bytes]] | None = None

    def __enter__(self) -> "RawTTY":
        if not sys.stdin.isatty():
            return self
        fd = sys.stdin.fileno()
        self._fd = fd
        self._old = termios.tcgetattr(fd)
        # cbreak (not full raw) keeps signal handling — Ctrl-C still raises KeyboardInterrupt.
        tty.setcbreak(fd)
        return self

    def __exit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc: BaseException | None,
        _tb: TracebackType | None,
    ) -> None:
        if self._old is not None and self._fd is not None:
            termios.tcsetattr(self._fd, termios.TCSADRAIN, self._old)


def _read_byte(timeout: float | None) -> str | None:
    """Read exactly one byte from stdin fd. Return None on timeout."""
    if timeout is not None:
        ready, _, _ = select.select([_STDIN_FD], [], [], timeout)
        if not ready:
            return None
    data = os.read(_STDIN_FD, 1)
    if not data:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def read_key(timeout: float | None = None) -> str | None:
    """Read one keypress and return a normalised token.

    Returns None if `timeout` is set and no key was pressed in that window.
    Caller must already be inside a RawTTY() context.
    """
    ch = _read_byte(timeout)
    if ch is None:
        return None
    if ch == "\x1b":
        # Could be ESC alone, `\x1b[X` (cursor mode), or `\x1bOX` (application mode).
        ch2 = _read_byte(_ESC_SEQ_TIMEOUT)
        if ch2 is None:
            return KEY_ESC
        if ch2 not in ("[", "O"):
            return KEY_ESC
        ch3 = _read_byte(_ESC_SEQ_TIMEOUT)
        if ch3 is None:
            return KEY_ESC
        arrow = {"A": KEY_UP, "B": KEY_DOWN, "C": KEY_RIGHT, "D": KEY_LEFT}.get(ch3)
        if arrow is not None:
            return arrow
        # Drain the rest of an unrecognised CSI sequence (e.g. PageUp = `\x1b[5~`).
        while True:
            tail = _read_byte(0.005)
            if tail is None or tail == "~" or tail.isalpha():
                break
        return KEY_UNKNOWN
    if ch in ("\r", "\n"):
        return KEY_ENTER
    if ch == " ":
        return KEY_SPACE
    if ch in ("\x7f", "\b"):
        return KEY_BACKSPACE
    if ch == "\t":
        return KEY_TAB
    if ch == "\x03":
        return KEY_CTRL_C
    return ch

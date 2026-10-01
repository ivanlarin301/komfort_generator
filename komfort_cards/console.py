"""Console helpers: UTF-8 output on Windows and the machine-readable RESULT line for the agent."""

from __future__ import annotations

import json
import sys
from typing import Any


class CardsError(Exception):
    """An expected failure with a Russian message for the operator; exit code 2."""

    def __init__(self, message: str, *, hint: str | None = None, data: dict[str, Any] | None = None):
        super().__init__(message)
        self.message = message
        self.hint = hint
        self.data = data or {}


def setup_utf8() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def say(text: str = "") -> None:
    print(text, flush=True)


def result(payload: dict[str, Any]) -> None:
    """Last line of every command: `RESULT: {json}` so Codex can parse the outcome reliably."""
    print("RESULT: " + json.dumps(payload, ensure_ascii=False), flush=True)

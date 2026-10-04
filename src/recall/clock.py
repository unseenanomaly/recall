"""Clocks. Time is injected so memory aging is fully testable and simulatable."""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Optional

DAY = 86_400.0


class Clock:
    def now(self) -> float:  # pragma: no cover - interface
        raise NotImplementedError


class SystemClock(Clock):
    def now(self) -> float:
        return time.time()


class ManualClock(Clock):
    """A clock you control. Perfect for tests, demos and replaying history."""

    # 2025-01-06 00:00:00 UTC
    DEFAULT_START = 1_736_121_600.0

    def __init__(self, start: Optional[float] = None):
        self._t = float(start) if start is not None else self.DEFAULT_START

    def now(self) -> float:
        return self._t

    def advance(self, days: float = 0.0, hours: float = 0.0, seconds: float = 0.0) -> float:
        self._t += days * DAY + hours * 3600.0 + seconds
        return self._t

    def set(self, t: float) -> None:
        self._t = float(t)


def fmt_date(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")

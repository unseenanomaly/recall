"""The forgetting curve.

Retention follows exponential decay with a per-memory half-life::

    R(t) = 0.5 ** (t / H)

Every time a memory is recalled its half-life grows, and it grows *more* when
the memory was close to being forgotten (spaced-repetition style)::

    H' = H * (reinforce_base + reinforce_difficulty * (1 - R))
"""
from __future__ import annotations

from .clock import DAY
from .config import Config
from .models import Kind, Memory, Status


def initial_half_life(kind: Kind, importance: float, cfg: Config) -> float:
    importance = min(1.0, max(0.0, importance))
    return cfg.half_life_days[kind] * (0.5 + 1.5 * importance)


def retention(m: Memory, now: float, cfg: Config) -> float:
    if m.pinned:
        return 1.0
    dt_days = max(0.0, now - m.last_reinforced) / DAY
    return 0.5 ** (dt_days / m.half_life_days)


def reinforced_half_life(m: Memory, now: float, cfg: Config) -> float:
    r = retention(m, now, cfg)
    factor = cfg.reinforce_base + cfg.reinforce_difficulty * (1.0 - r)
    return min(m.half_life_days * factor, cfg.max_half_life_days)


def status_from_retention(r: float, cfg: Config) -> Status:
    if r >= cfg.active_threshold:
        return Status.ACTIVE
    if r >= cfg.forget_threshold:
        return Status.DORMANT
    return Status.FORGOTTEN

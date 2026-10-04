"""Where memory lives, and the user's saved settings.

One memory, every agent: by default all tools share ``~/.recall/memory.json``, so
something you tell Claude Code is known to Codex, Cursor and the rest. A project can
opt into its own memory with ``recall init`` (creates ``./.recall/``).

Lookup order for the memory file:

1. ``--db`` on the command line
2. ``$RECALL_DB``
3. the nearest ``.recall/memory.json`` in the current directory or a parent
4. ``~/.recall/memory.json`` (``$RECALL_HOME`` moves ``~/.recall``)

Settings are JSON (``~/.recall/config.json``, overridden by ``./.recall/config.json``)
and a few environment variables (``RECALL_CONFIRM=auto`` etc.).
"""
from __future__ import annotations

import json
import os
from contextlib import contextmanager
from typing import Any, Dict, Iterator, Optional, Tuple

from .config import Config
from .engine import Recall
from .store import FileLock, JSONStore

#: name -> (default, allowed values or type, help)
SETTINGS: Dict[str, Tuple[Any, Any, str]] = {
    "confirm": ("ask", ("ask", "auto"),
                "When you contradict something you said before: 'ask' = \"has that changed?\", "
                "'auto' = auto-yes, the newest statement wins"),
    "self_check": ("flag", ("flag", "newest", "off"),
                   "When the assistant contradicts itself: 'flag' it, let the 'newest' win, or 'off'"),
    "capture": ("personal", ("personal", "all", "off"),
                "What hooks remember from your prompts on their own: 'personal' facts (where you live, "
                "what you like...), 'all' statements, or 'off' (only /remember)"),
    "context_budget": (400, int, "Token budget for the memory block injected at session start"),
    "pending_ttl_days": (7.0, float, "Days before an unanswered question is settled automatically"),
    "pending_default": ("yes", ("yes", "no"), "How an unanswered question is settled"),
}
_ENV = {"confirm": "RECALL_CONFIRM", "self_check": "RECALL_SELF_CHECK", "capture": "RECALL_CAPTURE"}


def recall_home() -> str:
    return os.path.abspath(os.path.expanduser(os.environ.get("RECALL_HOME") or "~/.recall"))


def find_project_dir(start: Optional[str] = None) -> Optional[str]:
    """The nearest directory (cwd or a parent) that has a ``.recall/`` folder, if any."""
    d = os.path.abspath(start or os.getcwd())
    home = os.path.dirname(recall_home())
    while True:
        cand = os.path.join(d, ".recall")
        if os.path.isdir(cand) and os.path.abspath(cand) != recall_home() and d != home:
            return d
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent


def resolve_db(explicit: Optional[str] = None, cwd: Optional[str] = None) -> str:
    if explicit:
        return explicit
    if os.environ.get("RECALL_DB"):
        return os.environ["RECALL_DB"]
    proj = find_project_dir(cwd)
    if proj:
        return os.path.join(proj, ".recall", "memory.json")
    return os.path.join(recall_home(), "memory.json")


def _read(path: str) -> Dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def settings_path(project: bool = False, cwd: Optional[str] = None) -> str:
    if project:
        base = find_project_dir(cwd) or os.path.abspath(cwd or os.getcwd())
        return os.path.join(base, ".recall", "config.json")
    return os.path.join(recall_home(), "config.json")


def coerce(key: str, value: Any) -> Any:
    if key not in SETTINGS:
        raise KeyError(f"unknown setting '{key}' (known: {', '.join(SETTINGS)})")
    _, allowed, _ = SETTINGS[key]
    if isinstance(allowed, tuple):
        v = str(value).strip().lower()
        v = {"on": "auto", "yes": "auto", "true": "auto", "off": "ask", "no": "ask", "false": "ask"}.get(v, v) \
            if key == "confirm" else v
        if v not in allowed:
            raise ValueError(f"{key} must be one of: {', '.join(allowed)}")
        return v
    return allowed(value)


def load_settings(cwd: Optional[str] = None) -> Dict[str, Any]:
    out = {k: d for k, (d, _, _) in SETTINGS.items()}
    layers = [_read(settings_path(False))]
    if find_project_dir(cwd):
        layers.append(_read(settings_path(True, cwd)))
    for layer in layers:
        for k, v in layer.items():
            try:
                out[k] = coerce(k, v)
            except (KeyError, ValueError, TypeError):
                pass
    for k, env in _ENV.items():
        if os.environ.get(env):
            try:
                out[k] = coerce(k, os.environ[env])
            except ValueError:
                pass
    return out


def save_setting(key: str, value: Any, project: bool = False, cwd: Optional[str] = None) -> str:
    path = settings_path(project, cwd)
    data = _read(path)
    if value is None:
        data.pop(key, None)
    else:
        data[key] = coerce(key, value)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    return path


def config_from(settings: Dict[str, Any]) -> Config:
    cfg = Config()
    cfg.confirm_changes = settings["confirm"]
    cfg.self_contradiction = "newest" if settings["self_check"] == "newest" else "flag"
    cfg.pending_ttl_days = float(settings["pending_ttl_days"])
    cfg.pending_default = settings["pending_default"]
    return cfg


@contextmanager
def open_memory(db: Optional[str] = None, cwd: Optional[str] = None) -> Iterator[Recall]:
    """Open the shared memory for one operation, holding a lock so concurrent agents,
    hooks and MCP calls never lose each other's writes."""
    path = resolve_db(db, cwd)
    with FileLock(path + ".lock"):
        yield Recall(JSONStore(path), config=config_from(load_settings(cwd)))

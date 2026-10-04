"""Connect Recall to coding agents: ``recall install <agent>`` / ``recall uninstall <agent>``.

Supported: Claude Code, OpenAI Codex CLI, Gemini CLI, Gemini Code Assist, Cursor,
GitHub Copilot CLI, Pi, OpenCode, Antigravity CLI, Hermes Agent, Swival, OpenClaw,
Devin CLI and Grok Build. See ``recall agents`` for what each one gets.
"""
from __future__ import annotations

import json
import os
import shutil
import time
from typing import Dict, List, Optional, Sequence, Tuple

from ..settings import recall_home
from ._fs import Line, Tree, File
from .agents import AGENTS, BY_ID, Agent, Ctx, claude_plugin_files, default_launcher, find, gemini_extension_files

__all__ = ["AGENTS", "Agent", "Ctx", "find", "install", "uninstall", "status", "detected", "export",
           "make_ctx"]

STATE = "integrations.json"


def make_ctx(home: Optional[str] = None, launcher: Optional[Sequence[str]] = None,
             env: Optional[Dict[str, str]] = None) -> Ctx:
    if env is None:
        # An explicit home (tests, staging a setup elsewhere) must not leak into the real one
        # through CODEX_HOME, APPDATA, XDG_CONFIG_HOME and friends.
        env = {} if home else dict(os.environ)
    return Ctx(home=os.path.abspath(os.path.expanduser(home or "~")),
               launcher=list(launcher) if launcher else default_launcher(), env=env)


def _state_path() -> str:
    return os.path.join(recall_home(), STATE)


def _load_state() -> Dict[str, Dict]:
    try:
        with open(_state_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_state(state: Dict[str, Dict]) -> None:
    os.makedirs(recall_home(), exist_ok=True)
    with open(_state_path(), "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


def install(agent: Agent, ctx: Ctx, dry: bool = False, record: bool = True) -> List[Line]:
    lines: List[Line] = []
    for action in agent.plan(ctx):
        lines += action.apply(dry)
    if not dry and record:
        from .. import __version__
        state = _load_state()
        state[agent.id] = {"installed": time.strftime("%Y-%m-%d %H:%M:%S"), "version": __version__,
                           "home": ctx.home, "launcher": ctx.launcher}
        _save_state(state)
    return lines


def uninstall(agent: Agent, ctx: Ctx, dry: bool = False) -> List[Line]:
    lines: List[Line] = []
    for action in reversed(agent.plan(ctx)):
        lines += action.undo(dry)
    if not dry:
        state = _load_state()
        if state.pop(agent.id, None) is not None:
            _save_state(state)
    return lines


def status(agent: Agent, ctx: Ctx) -> str:
    """'installed', 'partial' or 'not installed'."""
    checks = [a.present() for a in agent.plan(ctx)]
    checks = [c for c in checks if c is not None]
    if checks and all(checks):
        return "installed"
    return "partial" if any(checks) else "not installed"


def detected(agent: Agent, ctx: Ctx) -> bool:
    if any(shutil.which(b) for b in agent.binaries):
        return True
    return any(os.path.isdir(ctx.path(*d.split("/"))) for d in agent.marker_dirs)


def export(target: str, launcher: Sequence[str] = ("recall",)) -> List[str]:
    """Write ready-to-copy integration files (for manual installs and the plugin marketplace)."""
    from .agents import plan_antigravity, plan_hermes, plan_openclaw, template
    from .content import COMMANDS, SKILL, body
    from .agents import markdown_commands
    ctx = Ctx(home="/HOME", launcher=list(launcher), windows=False)
    written: List[str] = []

    def put(rel: str, text: str) -> None:
        path = os.path.join(target, *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        written.append(rel)

    for rel, text in claude_plugin_files(ctx).items():
        put(f"claude-code/{rel}", text)
    for rel, text in gemini_extension_files(ctx).items():
        put(f"gemini-cli/{rel}", text)
    for plan, name in ((plan_antigravity, "antigravity"), (plan_hermes, "hermes"), (plan_openclaw, "openclaw")):
        for action in plan(ctx):
            if isinstance(action, Tree) and action.root.replace("\\", "/").split("/")[-2] in ("plugins", "extensions"):
                for rel, text in action.files.items():
                    put(f"{name}/{rel}", text)
    put("pi/recall.ts", template("pi.ts.tmpl", launcher))
    put("opencode/plugins/recall.js", template("opencode.js.tmpl", launcher))
    for rel, text in markdown_commands("$ARGUMENTS", "recall-", "").items():
        put(f"opencode/commands/{rel}", text)
    for rel, text in markdown_commands("the text the user typed after this command", "recall-", "").items():
        put(f"cursor/commands/{rel}", text)
    for c in COMMANDS:
        put(f"swival/commands/recall-{c.name}.md", body(c, "$1") + "\n")
    put("skills/recall/SKILL.md", SKILL)
    return written

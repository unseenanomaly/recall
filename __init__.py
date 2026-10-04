"""Recall for Hermes Agent: long-term memory that ages facts, asks before it overwrites
what you said, and catches contradictions (including the model's own).

Installed by `hermes plugins install <owner>/recall --enable` or `recall install hermes`.
Commands: /recall-remember /recall-search /recall-forget /recall-show /recall-auto /recall-answer
"""
import json
import os
import shutil
import subprocess
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.join(_HERE, "src")          # present when installed from the Recall repo itself


def _launcher():
    configured = ["recall"]
    if shutil.which(configured[0]) or os.path.isabs(configured[0]):
        return configured, None
    if os.path.isdir(os.path.join(_SRC, "recall")):  # no `recall` on PATH: run the bundled source
        env = dict(os.environ, PYTHONPATH=_SRC + os.pathsep + os.environ.get("PYTHONPATH", ""))
        return [sys.executable, "-m", "recall"], env
    return configured, None


def _run(args, timeout=20):
    cmd, env = _launcher()
    try:
        p = subprocess.run(cmd + list(args), capture_output=True, text=True, timeout=timeout,
                           encoding="utf-8", errors="replace", env=env)
        return p.returncode, (p.stdout or "").strip()
    except Exception as e:  # never break the agent
        return 1, f"recall failed: {e}"


def _hook(event, text):
    _, out = _run(["hook", event, "--agent", "generic", "--queue", "--text", (text or "")[:8000]])
    try:
        return json.loads(out or "{}")
    except ValueError:
        return {}


def _pre_llm_call(**kwargs):
    """Before each turn: what Recall remembers, open questions, and heads-ups."""
    parts = []
    if kwargs.get("is_first_turn"):
        parts.append(_hook("session-start", "").get("context"))
    parts.append(_hook("prompt", kwargs.get("user_message") or "").get("context"))
    text = "\n\n".join(p for p in parts if p)
    return {"context": text} if text else None


def _post_llm_call(**kwargs):
    """After each turn: check the reply for contradictions (raised on the next turn)."""
    text = kwargs.get("assistant_response") or ""
    if text:
        _hook("stop", text)


def _command(to_args):
    def handler(raw_args="", **_):
        code, out = _run(to_args((raw_args or "").strip()))
        return out or ("done" if code == 0 else "recall failed: is it installed and on PATH?")
    return handler


COMMANDS = {
    "recall-remember": ("Save something to long-term memory", lambda a: ["add", a]),
    "recall-search": ("Ask what Recall remembers about something", lambda a: ["ask", a]),
    "recall-forget": ("Forget a memory (id or description)", lambda a: ["forget", a]),
    "recall-show": ("Show what Recall currently believes", lambda a: ["context"]),
    "recall-auto": ('Auto-yes for "has that changed?": on | off', lambda a: ["auto"] + ([a] if a else [])),
    "recall-answer": ("Answer Recall's question: yes | no", lambda a: ["answer", a or "yes"]),
}


def register(ctx):
    ctx.register_hook("pre_llm_call", _pre_llm_call)
    ctx.register_hook("post_llm_call", _post_llm_call)
    for name, (description, to_args) in COMMANDS.items():
        try:
            ctx.register_command(name, handler=_command(to_args), description=description)
        except Exception:
            pass  # older Hermes without plugin commands: the recall skill still works
    skills = os.path.join(_HERE, "skills")
    if os.path.isdir(skills) and hasattr(ctx, "register_skill"):
        for name in sorted(os.listdir(skills)):
            path = os.path.join(skills, name, "SKILL.md")
            if os.path.isfile(path):
                try:
                    ctx.register_skill(name, path)
                except Exception:
                    pass

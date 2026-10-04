"""``recall hook <event> --agent <name>``: one adapter for every agent's hook system.

Agents call this at four moments. It reads the agent's JSON on stdin, does the memory
work, and answers in that agent's dialect:

=================  ============================================================
``session-start``  inject what Recall believes about the user (and age memory)
``prompt``         record personal facts from the user's message, record a yes/no
                   answer to a pending question, inject relevant memories,
                   questions to ask, and heads-ups
``response``       (record-only) check the assistant's reply for contradictions
``stop``           check the assistant's reply; if it contradicted itself or the
                   user, make the agent continue and fix it (or queue a heads-up)
=================  ============================================================

Hooks must never break the agent: every error is swallowed (and logged to
``~/.recall/hooks.log``) and the agent proceeds as if the hook weren't there.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from typing import Any, Dict, Iterable, List, Optional

from .claims import extract_claims, has_correction_cue, is_personal, render_claim
from .engine import Recall
from .settings import load_settings, open_memory, recall_home

EVENTS = ("session-start", "prompt", "response", "stop")
MAX_ASKS = 2           # a question is put to the model at most this many times
MAX_CONTEXT = 6000     # characters; every agent caps hook output somewhere

PROMPT_KEYS = ("prompt", "user_input", "userPrompt", "user_prompt", "user_message", "message", "input")
RESPONSE_KEYS = ("last_assistant_message", "lastAssistantMessage", "prompt_response", "assistant_response",
                 "response", "text", "output")


# ------------------------------------------------------------------ dialects
class Dialect:
    """How one agent wants hook output shaped."""

    inject_on_start = True    # can add context at session start
    inject_on_prompt = True   # can add context when the user submits a prompt
    block_on_stop = True      # can make the agent take another turn at stop

    def context(self, event: str, text: str) -> Dict[str, Any]:
        name = {"session-start": "SessionStart", "prompt": "UserPromptSubmit"}[event]
        return {"hookSpecificOutput": {"hookEventName": name, "additionalContext": text}}

    def block(self, text: str) -> Dict[str, Any]:
        return {"decision": "block", "reason": text}

    def empty(self, event: str) -> Dict[str, Any]:
        return {}


class Gemini(Dialect):
    def context(self, event: str, text: str) -> Dict[str, Any]:
        name = {"session-start": "SessionStart", "prompt": "BeforeAgent"}[event]
        return {"hookSpecificOutput": {"hookEventName": name, "additionalContext": text}}

    def block(self, text: str) -> Dict[str, Any]:
        return {"decision": "deny", "reason": text}   # AfterAgent: retry with `reason` as the prompt


class Cursor(Dialect):
    inject_on_prompt = False   # beforeSubmitPrompt can only allow/block

    def context(self, event: str, text: str) -> Dict[str, Any]:
        return {"additional_context": text}

    def block(self, text: str) -> Dict[str, Any]:
        return {"followup_message": text}

    def empty(self, event: str) -> Dict[str, Any]:
        return {"continue": True} if event == "prompt" else {}


class Copilot(Dialect):
    inject_on_prompt = False   # userPromptSubmitted output is dropped by the CLI

    def context(self, event: str, text: str) -> Dict[str, Any]:
        return {"additionalContext": text}


class Antigravity(Dialect):
    inject_on_start = inject_on_prompt = False

    def block(self, text: str) -> Dict[str, Any]:
        return {"decision": "continue", "reason": text}


class Generic(Dialect):
    """For the JS/TS/Python plugins Recall ships (OpenCode, Pi, OpenClaw, Hermes)."""

    def context(self, event: str, text: str) -> Dict[str, Any]:
        return {"context": text}

    def block(self, text: str) -> Dict[str, Any]:
        return {"followup": text}


DIALECTS: Dict[str, Dialect] = {
    "claude-code": Dialect(), "codex": Dialect(), "devin": Dialect(), "grok": Dialect(),
    "gemini-cli": Gemini(), "cursor": Cursor(), "copilot": Copilot(),
    "antigravity": Antigravity(), "generic": Generic(),
}


# ------------------------------------------------------------------ helpers
def _first(d: Dict[str, Any], keys: Iterable[str]) -> Any:
    for k in keys:
        v = d.get(k)
        if v:
            return v
    return None


def _cwd(payload: Dict[str, Any]) -> Optional[str]:
    v = _first(payload, ("cwd", "workspaceRoot", "workspace_root"))
    if not v:
        roots = _first(payload, ("workspace_roots", "workspacePaths", "workspaces"))
        v = roots[0] if isinstance(roots, list) and roots else None
    return v if isinstance(v, str) and os.path.isdir(v) else None


def _text(value: Any) -> str:
    """Flatten the many shapes a message's content can take into plain text."""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(t for t in (_text(v) for v in value) if t)
    if isinstance(value, dict):
        if value.get("type") in ("tool_use", "tool_result", "thinking", "reasoning", "image"):
            return ""
        for k in ("text", "content", "message", "data", "parts"):
            if k in value:
                return _text(value[k])
    return ""


def _role(entry: Dict[str, Any]) -> str:
    for k in ("role", "type", "author", "source"):
        v = entry.get(k)
        if isinstance(v, str):
            return v.lower()
    msg = entry.get("message")
    return _role(msg) if isinstance(msg, dict) else ""


def last_assistant_text(path: Optional[str]) -> str:
    """Best-effort: the last assistant message in a transcript (JSONL or JSON)."""
    if not path or not os.path.isfile(path):
        return ""
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - 2_000_000))
            raw = f.read().decode("utf-8", "replace")
    except OSError:
        return ""
    entries: List[Any] = []
    try:
        data = json.loads(raw)
        entries = data if isinstance(data, list) else data.get("messages") or data.get("steps") or []
    except ValueError:
        for line in raw.splitlines():
            line = line.strip()
            if line.startswith("{"):
                try:
                    entries.append(json.loads(line))
                except ValueError:
                    pass
    for e in reversed(entries):
        if isinstance(e, dict):
            role = _role(e)
            if "assistant" in role or role in ("model", "agent", "bot", "ai"):
                t = _text(e).strip()
                if t:
                    return t
    return ""


_YES = re.compile(r"^\s*(y|yes|yeah|yep|yup|ya|yah|correct|right|sure|indeed|affirmative|true|exactly|"
                  r"definitely|absolutely|it (?:has|did)|i (?:did|have|do)|that'?s right|ok(?:ay)?[, ]+ye(?:s|ah))\b", re.I)
_NO = re.compile(r"^\s*(n|no|nope|nah|not really|no way|negative|false|wrong|it (?:has not|hasn'?t|didn'?t)|"
                 r"i (?:didn'?t|did not|haven'?t)|hasn'?t|nothing changed|still)\b", re.I)


def parse_answer(text: str) -> Optional[bool]:
    """Read a short reply as yes / no to a "has that changed?" question (None = neither)."""
    t = (text or "").strip()
    if not t or len(t.split()) > 25:
        return None
    if _NO.match(t):
        return False
    if _YES.match(t):
        return True
    return None


_QUESTION = re.compile(r"^(what|where|when|why|how|who|which|whose|can|could|would|should|do|does|did|is|"
                       r"are|am|will|have|has|was|were|shall|may)\b", re.I)
_FENCE = re.compile(r"```.*?(?:```|$)", re.S)


def capture(mem: Recall, text: str, mode: str = "personal") -> list:
    """Remember facts the user states in passing. ``personal`` keeps only facts about the
    user ("I live in...", "I'm vegetarian", "my editor is..."), never task chatter."""
    if mode == "off" or not text:
        return []
    t = _FENCE.sub(" ", text).strip()
    if not t or len(t) > 1500 or t.endswith("?") or _QUESTION.match(t):
        return []
    claims = extract_claims(t)
    keep = claims if mode == "all" else [c for c in claims if c.subject == "user" and is_personal(c)]
    if not keep:
        return []
    if len(keep) == len(claims):
        res = mem.add(t)
        return [q for p in (res.parts or [res]) for q in p.questions]
    out = []
    cue = has_correction_cue(t)
    for c in keep:
        out += mem.add(render_claim(c), claims=[c], metadata={"source_text": t[:300]}, correction=cue).questions
    return out


def answer_reply(mem: Recall, text: str) -> List[str]:
    """If the previous turn asked the user a question and this message is a yes/no, record it."""
    if not mem.store.meta.pop("ask_fresh", False):
        return []
    yes = parse_answer(text)
    batch = mem.store.meta.get("ask_batch")
    if yes is None or batch is None:
        mem.store.flush()
        return []
    notes = []
    for q in mem.questions():
        if q.new.metadata.get("asked_at") == batch:
            mem.answer(q.id, yes)
            notes.append(f"Recorded the user's answer ({'yes, it changed' if yes else 'no, unchanged'}) "
                         f"to: {q.text}")
    mem.store.flush()
    return notes


def _mark_asked(mem: Recall, questions, fresh: bool = True) -> None:
    now = mem.clock.now()
    for q in questions:
        q.new.metadata["asked"] = int(q.new.metadata.get("asked", 0)) + 1
        q.new.metadata["asked_at"] = now
        mem.store.put(q.new)
    if questions and fresh:
        mem.store.meta["ask_batch"] = now
        mem.store.meta["ask_fresh"] = True
    mem.store.flush()


def render(mem: Recall, query: Optional[str] = None, budget: int = 400, *, questions: bool = True,
           extra: Iterable[str] = (), only_if_relevant: bool = False, fresh: bool = True) -> str:
    """The block injected into the model's context."""
    pack = mem.active_context(query, token_budget=budget, include_questions=False, include_notices=False)
    qs = [q for q in mem.questions() if int(q.new.metadata.get("asked", 0)) < MAX_ASKS] if questions else []
    notes = mem.notices() + list(extra)
    if only_if_relevant and not (pack.items or qs or notes):
        return ""
    if not (pack.items or qs or notes):
        return ""
    pack.questions, pack.notices = qs, notes
    header = "What Recall remembers that's relevant here" if query else "What Recall remembers about the user"
    body = pack.to_prompt(header=header) if pack.items else pack.to_prompt(header="").lstrip("\n")
    tips = []
    if qs:
        tips.append("Ask the question(s) above in one short sentence before relying on that fact. A plain "
                    "yes/no reply is recorded automatically (or call the recall `answer` tool).")
    if notes:
        tips.append("Address the heads-up items briefly and correct yourself if needed.")
    _mark_asked(mem, qs, fresh)
    mem.clear_notices()
    text = "<recall-memory>\n" + body.strip() + ("\n\n" + " ".join(tips) if tips else "") + "\n</recall-memory>"
    return text[:MAX_CONTEXT]


def _ask_block(mem: Recall) -> str:
    qs = [q for q in mem.questions() if int(q.new.metadata.get("asked", 0)) < MAX_ASKS]
    if not qs:
        return ""
    _mark_asked(mem, qs)
    lines = ["Recall needs the user to confirm a change before it updates their memory. "
             "Ask them, in one short sentence:"] + [f"- {q.text}" for q in qs]
    return "\n".join(lines)


# ------------------------------------------------------------------ the handler
def handle(event: str, agent: str, payload: Dict[str, Any], *, db: Optional[str] = None,
           queue_only: bool = False) -> Dict[str, Any]:
    if event not in EVENTS:
        raise ValueError(f"unknown hook event {event!r}; expected one of {', '.join(EVENTS)}")
    d = DIALECTS.get(agent, DIALECTS["generic"])
    cwd = _cwd(payload)
    settings = load_settings(cwd)
    with open_memory(db, cwd) as mem:
        if event == "session-start":
            mem.sweep()
            # questions shown at session start aren't "fresh": the user's first message is
            # usually a task, and a leading "yes, go ahead" must not be read as an answer
            text = render(mem, None, int(settings["context_budget"]), questions=d.inject_on_start, fresh=False)
            return d.context(event, text) if text and d.inject_on_start else d.empty(event)

        if event == "prompt":
            prompt = _first(payload, PROMPT_KEYS)
            prompt = prompt if isinstance(prompt, str) else ""
            notes = answer_reply(mem, prompt) if prompt else []
            if prompt:
                capture(mem, prompt, settings["capture"])
            if not d.inject_on_prompt:
                return d.empty(event)
            text = render(mem, prompt or None, 220, extra=notes, only_if_relevant=True)
            return d.context(event, text) if text else d.empty(event)

        response = _first(payload, RESPONSE_KEYS)
        if not isinstance(response, str) or not response.strip():
            response = last_assistant_text(_first(payload, ("transcript_path", "transcriptPath")))
        check = mem.observe(response) if response and settings["self_check"] != "off" else None

        if event == "response":
            if check and check.conflicts:
                mem.store.meta["followup"] = check.message()
                mem.store.flush()
            return d.empty(event)

        # stop
        again = bool(_first(payload, ("stop_hook_active", "stopHookActive"))) or \
            int(payload.get("loop_count") or 0) > 0
        parts = [check.message()] if check and check.conflicts else []
        pending = mem.store.meta.pop("followup", None)
        if pending and pending not in parts:
            parts.append(pending)
        mem.store.flush()
        can_block = d.block_on_stop and not again and not queue_only
        if can_block and not d.inject_on_prompt:
            ask = _ask_block(mem)   # this agent couldn't show the question when it was created
            if ask:
                parts.append(ask)
        if not parts:
            return d.empty(event)
        if can_block:
            return d.block("\n\n".join(parts))
        for p in parts:
            if not p.startswith("Recall needs the user"):
                mem.notify(p, "contradiction")   # delivered with the next prompt instead
        return d.empty(event)


def run(event: str, agent: str, *, text: Optional[str] = None, db: Optional[str] = None,
        queue_only: bool = False, stdin=None) -> int:
    """CLI entry point. Always exits 0 and prints valid JSON, whatever happens."""
    out: Dict[str, Any] = {}
    try:
        if text is not None:
            payload = {"prompt": text} if event == "prompt" else {"response": text}
        else:
            if stdin is not None:
                raw = stdin.read()
            else:  # agents send UTF-8; don't let a cp1252 console mangle "Zürich"
                buf = getattr(sys.stdin, "buffer", None)
                raw = buf.read().decode("utf-8", "replace") if buf else sys.stdin.read()
            payload = json.loads(raw) if raw.strip() else {}
            if not isinstance(payload, dict):
                payload = {}
        out = handle(event, agent, payload, db=db, queue_only=queue_only)
    except Exception as e:  # noqa: BLE001 - a hook must never take the agent down
        _log(f"{event} --agent {agent}: {type(e).__name__}: {e}")
        d = DIALECTS.get(agent, DIALECTS["generic"])
        out = d.empty(event) if event in EVENTS else {}
    sys.stdout.write(json.dumps(out))
    sys.stdout.write("\n")
    sys.stdout.flush()
    return 0


def _log(line: str) -> None:
    try:
        os.makedirs(recall_home(), exist_ok=True)
        with open(os.path.join(recall_home(), "hooks.log"), "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + line + "\n")
    except OSError:
        pass

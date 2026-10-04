"""``recall mcp``: a Model Context Protocol server over stdio, with zero dependencies.

Every MCP-capable agent (Claude Code, Codex, Gemini CLI, Cursor, Copilot CLI, OpenCode,
Antigravity, Devin, Grok Build, Swival, OpenClaw...) can register it and get these tools:

    remember  search  context  answer  check  forget  explain  settings

The memory file is reopened for every call, so the server always sees what hooks and
other agents wrote a moment ago.
"""
from __future__ import annotations

import json
import sys
from typing import Any, Callable, Dict, List, Optional

from . import __version__
from .clock import fmt_date
from .engine import Recall
from .models import Status
from .settings import load_settings, open_memory, save_setting

PROTOCOL_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")

INSTRUCTIONS = """\
Recall is the user's long-term memory, shared across all their AI tools. It ages facts,
detects contradictions, and asks before it overwrites what the user told you.

- When the user tells you something lasting about themselves or their project, call
  `remember` with their words. If the result contains a question ("You said before that
  ... Has that changed?"), ask the user exactly that, then call `answer` with yes or no.
- Before answering questions that depend on the user's details, call `search` (or
  `context` for an overview). Treat items marked unverified/disputed as uncertain.
- Before stating facts you asserted earlier (ports, versions, names, decisions), you can
  call `check` with your draft. If it reports a contradiction, fix it or say plainly
  "Correction: ..." so the record is updated.
- Never store secrets (passwords, keys, tokens) with `remember`.
"""

_STR = {"type": "string"}
TOOLS: List[Dict[str, Any]] = [
    {"name": "remember",
     "description": "Save something lasting the user said (about themselves or their project). Contradictions "
                    "are resolved automatically; if the user said something different before, the result "
                    "includes a question to ask them.",
     "inputSchema": {"type": "object", "properties": {
         "text": {"type": "string", "description": "The statement, in the user's words, e.g. 'I moved to Berlin'"},
         "pinned": {"type": "boolean", "description": "Never let it fade (allergies, safety rules)"},
         "source": {"type": "string", "description": "Who said it: user (default), tool, document, web..."}},
         "required": ["text"]}},
    {"name": "search",
     "description": "Find what Recall remembers about a topic. Results that are recalled get stronger.",
     "inputSchema": {"type": "object", "properties": {
         "query": _STR, "limit": {"type": "integer", "minimum": 1, "maximum": 20}}, "required": ["query"]}},
    {"name": "context",
     "description": "Everything Recall currently believes about the user (plus open questions and heads-ups), "
                    "packed to a token budget. Optionally focused on a query.",
     "inputSchema": {"type": "object", "properties": {
         "query": _STR, "budget": {"type": "integer", "minimum": 50, "maximum": 4000}}}},
    {"name": "answer",
     "description": "Record the user's answer to a 'has that changed?' question. yes = the new statement "
                    "replaces the old one; no = the old one stands. Omit question_id to answer the latest one.",
     "inputSchema": {"type": "object", "properties": {
         "answer": {"type": "string", "enum": ["yes", "no"]}, "question_id": _STR}, "required": ["answer"]}},
    {"name": "check",
     "description": "Check a draft reply (or your last reply) for contradictions with what you said before "
                    "and what the user told you. Nothing is stored.",
     "inputSchema": {"type": "object", "properties": {"text": _STR}, "required": ["text"]}},
    {"name": "forget",
     "description": "Forget a memory, by id (m_...) or by describing it.",
     "inputSchema": {"type": "object", "properties": {"target": _STR}, "required": ["target"]}},
    {"name": "explain",
     "description": "The audit trail of one memory: where it came from and why it looks the way it does.",
     "inputSchema": {"type": "object", "properties": {"id": _STR}, "required": ["id"]}},
    {"name": "settings",
     "description": "Read or change Recall settings. auto_confirm=true stops the 'has that changed?' "
                    "questions (newest statement wins, auto-yes); false turns them back on.",
     "inputSchema": {"type": "object", "properties": {"auto_confirm": {"type": "boolean"}}}},
]


def _hit(h) -> Dict[str, Any]:
    m = h.memory
    return {"id": m.id, "text": m.content, "status": h.status.value, "as_of": fmt_date(m.created_at),
            "source": m.source, "retention": round(h.retention, 2), "relevance": round(h.relevance, 2)}


def _remember(mem: Recall, a: Dict[str, Any]) -> Dict[str, Any]:
    res = mem.add(str(a["text"]), pinned=bool(a.get("pinned")), source=str(a.get("source") or "user"))
    out: Dict[str, Any] = {"stored": [], "questions": [], "replaced": [], "kept_old": []}
    for p in (res.parts or [res]):
        m = p.memory
        if p.merged:
            out["stored"].append({"id": m.id, "text": m.content, "note": "already known; reinforced"})
            continue
        out["stored"].append({"id": m.id, "text": m.content, "status": m.status.value})
        out["questions"] += [{"question_id": q.id, "ask_the_user": q.text} for q in p.questions]
        for r in p.resolutions:
            if r.action == "supersede_old" and not p.questions:
                out["replaced"].append({"id": r.old_id, "text": mem.get(r.old_id).content, "why": r.reason})
            elif r.action == "reject_new":
                out["kept_old"].append({"id": r.old_id, "text": mem.get(r.old_id).content, "why": r.reason})
    if out["questions"]:
        out["next_step"] = "Ask the user the question(s) verbatim, then call `answer`."
    return out


def _answer(mem: Recall, a: Dict[str, Any]) -> Dict[str, Any]:
    yes = str(a.get("answer", "")).strip().lower() in ("yes", "y", "true")
    qs = mem.questions()
    if not qs:
        return {"error": "there is no open question"}
    qid = a.get("question_id") or qs[-1].id
    q = next((x for x in qs if x.id == qid), None)
    if q is None:
        return {"error": f"no open question with id {qid}", "open": [x.id for x in qs]}
    m = mem.answer(q.id, yes)
    return {"question": q.text, "answer": "yes" if yes else "no",
            "now_believed": m.content if yes else [o.content for o in q.old]}


def _forget(mem: Recall, a: Dict[str, Any]) -> Dict[str, Any]:
    target = str(a["target"]).strip()
    m = mem.get(target)
    if m is None:
        hits = mem.recall(target, limit=1, reinforce=False)
        if not hits:
            return {"error": f"nothing matching {target!r}"}
        m = hits[0].memory
    mem.forget(m.id, "asked to forget")
    return {"forgotten": {"id": m.id, "text": m.content}}


def _settings(_: Recall, a: Dict[str, Any]) -> Dict[str, Any]:
    if "auto_confirm" in a and a["auto_confirm"] is not None:
        save_setting("confirm", "auto" if a["auto_confirm"] else "ask")
    s = load_settings()
    return {"confirm": s["confirm"], "auto_confirm": s["confirm"] == "auto",
            "self_check": s["self_check"], "capture": s["capture"]}


HANDLERS: Dict[str, Callable[[Recall, Dict[str, Any]], Any]] = {
    "remember": _remember,
    "search": lambda mem, a: {"results": [_hit(h) for h in mem.recall(str(a["query"]), limit=int(a.get("limit") or 5))]},
    "context": lambda mem, a: mem.active_context(a.get("query") or None,
                                                 token_budget=int(a.get("budget") or 400)).to_prompt(),
    "answer": _answer,
    "check": lambda mem, a: (lambda r: {"ok": r.ok, "conflicts": [
        {"kind": c.kind, "message": c.message()} for c in r.conflicts], "advice": r.message()})(mem.check(str(a["text"]))),
    "forget": _forget,
    "explain": lambda mem, a: mem.explain(str(a["id"])),
    "settings": _settings,
}


def call_tool(name: str, args: Dict[str, Any], db: Optional[str] = None) -> Dict[str, Any]:
    if name not in HANDLERS:
        return {"content": [{"type": "text", "text": f"unknown tool {name!r}"}], "isError": True}
    try:
        with open_memory(db) as mem:
            result = HANDLERS[name](mem, args or {})
    except (KeyError, ValueError) as e:
        return {"content": [{"type": "text", "text": f"error: {e}"}], "isError": True}
    text = result if isinstance(result, str) else json.dumps(result, indent=2, ensure_ascii=False)
    is_err = isinstance(result, dict) and "error" in result
    return {"content": [{"type": "text", "text": text}], "isError": is_err}


def handle(msg: Dict[str, Any], db: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """One JSON-RPC message in, at most one out (notifications get no reply)."""
    method, mid = msg.get("method"), msg.get("id")
    if mid is None:
        return None
    params = msg.get("params") or {}
    if method == "initialize":
        asked = params.get("protocolVersion")
        result: Any = {
            "protocolVersion": asked if asked in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0],
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "recall", "title": "Recall memory", "version": __version__},
            "instructions": INSTRUCTIONS,
        }
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "tools/call":
        result = call_tool(params.get("name", ""), params.get("arguments") or {}, db)
    elif method in ("resources/list", "prompts/list"):
        result = {method.split("/")[0]: []}
    else:
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"method not found: {method}"}}
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def serve(db: Optional[str] = None, stdin=None, stdout=None) -> int:
    inp = stdin or sys.stdin.buffer
    out = stdout or sys.stdout.buffer
    for raw in inp:
        line = raw.decode("utf-8", "replace").strip() if isinstance(raw, bytes) else raw.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            reply: Any = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}
        else:
            batch = msg if isinstance(msg, list) else [msg]
            replies = [r for r in (handle(m, db) for m in batch if isinstance(m, dict)) if r]
            reply = replies if isinstance(msg, list) else (replies[0] if replies else None)
        if reply:
            data = json.dumps(reply, ensure_ascii=False) + "\n"
            out.write(data.encode("utf-8") if not hasattr(out, "encoding") else data)
            out.flush()
    return 0

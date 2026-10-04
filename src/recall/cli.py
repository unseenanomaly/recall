"""Command line interface. Run ``recall --help`` for the full list."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from typing import List, Optional

from . import __version__
from ._term import c
from .clock import fmt_date
from .models import Kind, Status
from .settings import (SETTINGS, find_project_dir, load_settings, open_memory, recall_home, resolve_db,
                       save_setting, settings_path)


def _out(data) -> None:
    print(json.dumps(data, indent=2, ensure_ascii=False))


# ------------------------------------------------------------------ memory
def cmd_demo(_: argparse.Namespace) -> int:
    from .demo import run_demo
    run_demo()
    return 0


def cmd_add(a: argparse.Namespace) -> int:
    with open_memory(a.db) as mem:
        kind = Kind(a.kind) if a.kind else None
        res = mem.add(a.text, kind=kind, source=a.source, importance=a.importance,
                      confidence=a.confidence, pinned=a.pin)
        parts = res.parts or [res]
        if a.json:
            _out({"stored": [{"id": p.memory.id, "text": p.memory.content, "status": p.memory.status.value,
                              "merged": p.merged} for p in parts],
                  "questions": [{"id": q.id, "question": q.text} for q in res.questions],
                  "resolutions": [{"action": r.action, "old": r.old_id, "reason": r.reason}
                                  for r in res.resolutions]})
            return 0
        for p in parts:
            m = p.memory
            if p.merged:
                print(c(f"↻ already known; reinforced {m.id}", "dim"))
                continue
            print(c("+ stored ", "green", "bold") + f"{m.id}  {m.content}")
            for cl in m.claims:
                print(c(f"    claim: {cl}", "dim"))
            for q in p.questions:
                print(c("? ", "blue", "bold") + q.text)
                print(c(f"    answer with: recall answer yes   (or no)", "dim"))
            if not p.questions:
                for r in p.resolutions:
                    print(c(f"    {r.action}: {r.reason}", "yellow"))
    return 0


def cmd_ask(a: argparse.Namespace) -> int:
    with open_memory(a.db) as mem:
        hits = mem.recall(a.query, limit=a.limit)
        if a.json:
            _out([{"id": h.memory.id, "text": h.memory.content, "status": h.status.value,
                   "as_of": fmt_date(h.memory.created_at), "relevance": round(h.relevance, 2),
                   "retention": round(h.retention, 2)} for h in hits])
            return 0 if hits else 1
        if not hits:
            print(c("nothing relevant is remembered", "dim"))
            return 1
        for h in hits:
            flag = {Status.DISPUTED: c(" ⚠ disputed", "magenta"), Status.DORMANT: c(" ◐ faded", "yellow")}.get(h.status, "")
            print(f"{c(h.memory.id, 'gray')}  {h.memory.content}{flag}  "
                  + c(f"(relevance {h.relevance:.2f}, retention {h.retention:.2f})", "dim"))
    return 0


def cmd_context(a: argparse.Namespace) -> int:
    with open_memory(a.db) as mem:
        pack = mem.active_context(a.query, token_budget=a.budget)
    print(pack.to_prompt())
    print(c(f"\n# {len(pack)} memories, ~{pack.tokens} tokens, {pack.dropped} left out", "dim"), file=sys.stderr)
    return 0


def cmd_questions(a: argparse.Namespace) -> int:
    with open_memory(a.db) as mem:
        qs = mem.questions()
    if a.json:
        _out([{"id": q.id, "question": q.text, "new": q.new.content, "old": [o.content for o in q.old]} for q in qs])
        return 0
    if not qs:
        print(c("no open questions", "dim"))
    for q in qs:
        print(f"{c(q.id, 'gray')}  {q.text}")
    return 0


def cmd_answer(a: argparse.Namespace) -> int:
    words = list(a.args)
    reply = next((w for w in reversed(words) if w.lower() in ("yes", "no", "y", "n")), None)
    qid = next((w for w in words if w.startswith("m_")), None)
    if reply is None:
        print("usage: recall answer [ID] yes|no", file=sys.stderr)
        return 2
    with open_memory(a.db) as mem:
        qs = mem.questions()
        if not qs:
            print(c("no open questions", "dim"))
            return 1
        targets = [q for q in qs if q.id == qid] if qid else [qs[-1]]
        if not targets:
            print(f"error: no open question {qid}", file=sys.stderr)
            return 2
        for q in targets:
            yes = reply.lower().startswith("y")
            m = mem.answer(q.id, yes)
            print(c("✓ ", "green", "bold") + (f"updated: {m.content}" if yes else
                                               f"kept: {', '.join(o.content for o in q.old)}"))
    return 0


def cmd_check(a: argparse.Namespace) -> int:
    text = a.text if a.text != "-" else sys.stdin.read()
    with open_memory(a.db) as mem:
        res = mem.observe(text) if a.store else mem.check(text)
    if a.json:
        _out({"ok": res.ok, "conflicts": [{"kind": k.kind, "message": k.message()} for k in res.conflicts]})
    elif res.ok:
        print(c("✓ no contradictions found", "green"))
    else:
        print(res.message())
    return 0 if res.ok else 1


def cmd_forget(a: argparse.Namespace) -> int:
    with open_memory(a.db) as mem:
        m = mem.get(a.target)
        if m is None:
            hits = mem.recall(a.target, limit=1, reinforce=False)
            if not hits:
                print(f"nothing matching {a.target!r}", file=sys.stderr)
                return 1
            m = hits[0].memory
        mem.forget(m.id, a.reason)
    print(c("○ forgotten ", "gray") + f"{m.id}  {m.content}")
    return 0


def cmd_sweep(a: argparse.Namespace) -> int:
    with open_memory(a.db) as mem:
        print(mem.sweep())
        if a.purge:
            print(f"purged {mem.purge()} forgotten memories")
    return 0


def cmd_list(a: argparse.Namespace) -> int:
    with open_memory(a.db) as mem:
        for m in mem.memories():
            st = mem._live_status(m, mem.clock.now())
            if st in (Status.FORGOTTEN, Status.SUPERSEDED) and not a.all:
                continue
            if m.source == "assistant" and not a.all:
                continue
            print(f"{c(m.id, 'gray')}  {st.value:<10} {mem.retention_of(m.id):4.0%}  "
                  f"{fmt_date(m.created_at)}  {m.content}")
    return 0


def cmd_explain(a: argparse.Namespace) -> int:
    with open_memory(a.db) as mem:
        print(mem.explain(a.id))
    return 0


def cmd_stats(a: argparse.Namespace) -> int:
    with open_memory(a.db) as mem:
        for k, v in mem.stats().items():
            print(f"{k:<11}{v}")
    return 0


# ------------------------------------------------------------- settings
def cmd_auto(a: argparse.Namespace) -> int:
    if a.state in ("on", "off"):
        save_setting("confirm", "auto" if a.state == "on" else "ask", project=a.project)
    on = load_settings()["confirm"] == "auto"
    print(("auto-yes is ON: newer statements replace older ones without asking"
           if on else 'auto-yes is OFF: Recall asks "has that changed?" before replacing what you said'))
    return 0


def cmd_config(a: argparse.Namespace) -> int:
    if a.action in (None, "list"):
        s = load_settings()
        for k, (default, allowed, help_) in SETTINGS.items():
            mark = "" if s[k] == default else c("  (changed)", "yellow")
            choices = f" [{'|'.join(allowed)}]" if isinstance(allowed, tuple) else ""
            print(f"{c(k, 'bold'):<20} = {s[k]}{mark}\n    {c(help_ + choices, 'dim')}")
        print(c(f"\nsaved in {settings_path(False)}" + (f" and {settings_path(True)}" if find_project_dir() else ""),
                "dim"))
        return 0
    if a.action == "get":
        print(load_settings()[a.key])
        return 0
    if a.action == "set":
        if a.value is None:
            print("usage: recall config set KEY VALUE", file=sys.stderr)
            return 2
        path = save_setting(a.key, a.value, project=a.project)
        print(f"{a.key} = {load_settings()[a.key]}  ({path})")
        return 0
    if a.action == "unset":
        save_setting(a.key, None, project=a.project)
        print(f"{a.key} reset to {load_settings()[a.key]}")
        return 0
    return 2


def cmd_init(_: argparse.Namespace) -> int:
    path = os.path.join(os.getcwd(), ".recall")
    os.makedirs(path, exist_ok=True)
    print(f"project memory: {os.path.join(path, 'memory.json')}\n"
          "Agents started inside this folder now use it instead of your global memory.\n"
          "Add `.recall/` to .gitignore unless you want to share it.")
    return 0


def cmd_where(a: argparse.Namespace) -> int:
    print(resolve_db(a.db))
    return 0


# --------------------------------------------------------- integrations
def cmd_mcp(a: argparse.Namespace) -> int:
    from .mcp import serve
    return serve(db=a.db)


def cmd_hook(a: argparse.Namespace) -> int:
    from .hooks import run
    return run(a.event, a.agent, text=a.text, db=a.db, queue_only=a.queue)


def _agents_from(a: argparse.Namespace, ctx, verb: str):
    from .integrations import AGENTS, detected, find, status
    if a.all:
        return AGENTS if verb == "install" else [x for x in AGENTS if status(x, ctx) != "not installed"]
    if getattr(a, "detected", False):
        return [x for x in AGENTS if detected(x, ctx)]
    if not a.agents:
        return None
    out = []
    for name in a.agents:
        ag = find(name)
        if ag is None:
            print(f"unknown agent {name!r}. Known: {', '.join(x.id for x in AGENTS)}", file=sys.stderr)
            return []
        out.append(ag)
    return out


def cmd_install(a: argparse.Namespace) -> int:
    from .integrations import install, make_ctx
    ctx = make_ctx(a.home, a.launcher.split() if a.launcher else None)
    agents = _agents_from(a, ctx, "install")
    if agents is None:
        print("which agent? e.g. `recall install claude-code`, `recall install --detected`, "
              "`recall install --all`. See `recall agents`.", file=sys.stderr)
        return 2
    if not agents:
        return 2
    launcher_shown = " ".join(ctx.launcher)
    print(c(f"Recall {__version__} → {len(agents)} agent(s)", "bold") +
          c(f"   (agents will run: {launcher_shown})", "dim"))
    for ag in agents:
        print("\n" + c(f"{ag.name}", "bold", "cyan") + c(f"  [{ag.id}]{'  (dry run)' if a.dry_run else ''}", "dim"))
        for line in install(ag, ctx, dry=a.dry_run):
            print(line)
        print(c(f"  commands: {ag.commands} …   (see `recall agents`)", "dim"))
    if not a.dry_run:
        print("\n" + c("Restart the agent(s) to load Recall. Undo any time with `recall uninstall <agent>`.", "dim"))
    return 0


def cmd_uninstall(a: argparse.Namespace) -> int:
    from .integrations import make_ctx, uninstall
    ctx = make_ctx(a.home, a.launcher.split() if a.launcher else None)
    agents = _agents_from(a, ctx, "uninstall")
    if agents is None:
        print("which agent? e.g. `recall uninstall cursor` or `recall uninstall --all`.", file=sys.stderr)
        return 2
    for ag in agents:
        print(c(f"{ag.name}", "bold", "cyan") + c(f"  [{ag.id}]{'  (dry run)' if a.dry_run else ''}", "dim"))
        lines = uninstall(ag, ctx, dry=a.dry_run)
        for line in lines or []:
            print(line)
        if not lines:
            print(c("  nothing to remove", "dim"))
    if not agents:
        print(c("no integrations installed", "dim"))
    else:
        print(c("\nYour memory itself is untouched: " + resolve_db(None) + "\n(delete it with `recall forget-all`"
                " or by removing that file).", "dim"))
    return 0


def cmd_agents(a: argparse.Namespace) -> int:
    from .integrations import AGENTS, detected, make_ctx, status
    ctx = make_ctx(a.home)
    if a.json:
        _out([{"id": ag.id, "name": ag.name, "status": status(ag, ctx), "detected": detected(ag, ctx),
               "provides": list(ag.provides), "commands": ag.commands} for ag in AGENTS])
        return 0
    print(c(f"{'agent':<13} {'status':<15} {'found':<6} {'adds':<38} commands", "dim"))
    for ag in AGENTS:
        st = status(ag, ctx)
        col = {"installed": "green", "partial": "yellow"}.get(st, "gray")
        print(f"{ag.id:<13} {c(f'{st:<15}', col)} {'yes' if detected(ag, ctx) else '-':<6} "
              f"{', '.join(ag.provides):<38} {ag.commands}")
    print(c("\ninstall: recall install <agent>   (or --detected / --all)    "
            "remove: recall uninstall <agent>", "dim"))
    return 0


def cmd_doctor(a: argparse.Namespace) -> int:
    from .integrations import AGENTS, make_ctx, status
    ok = True
    exe = shutil.which("recall")
    print(f"{'✓' if exe else '!'} recall on PATH: {exe or 'no (agents will use python -m recall)'}")
    print(f"✓ python: {sys.executable}")
    db = resolve_db(a.db)
    print(f"✓ memory file: {db}{'' if os.path.exists(db) else '  (created on first write)'}")
    s = load_settings()
    print(f"✓ settings: confirm={s['confirm']} self_check={s['self_check']} capture={s['capture']}")
    log = os.path.join(recall_home(), "hooks.log")
    if os.path.exists(log):
        with open(log, encoding="utf-8", errors="replace") as f:
            tail = f.read().splitlines()[-3:]
        if tail:
            ok = False
            print("! recent hook errors (" + log + "):")
            for t in tail:
                print("    " + t)
    ctx = make_ctx()
    for ag in AGENTS:
        st = status(ag, ctx)
        if st != "not installed":
            print(f"{'✓' if st == 'installed' else '!'} {ag.name}: {st}")
            ok = ok and st == "installed"
    from .mcp import handle
    r = handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    print(f"✓ MCP server answers: {len(r['result']['tools'])} tools")
    return 0 if ok else 1


def cmd_export(a: argparse.Namespace) -> int:
    from .integrations import export
    files = export(a.dir)
    print(f"wrote {len(files)} files under {a.dir}")
    return 0


def cmd_forget_all(a: argparse.Namespace) -> int:
    path = resolve_db(a.db)
    if not a.yes:
        print(f"This permanently deletes {path}. Re-run with --yes to confirm.", file=sys.stderr)
        return 2
    for p in (path, path + ".lock"):
        if os.path.exists(p):
            os.remove(p)
    print(f"deleted {path}")
    return 0


# ---------------------------------------------------------------- parser
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="recall", description="AI memory that forgets on purpose.")
    p.add_argument("--version", action="version", version=f"recall {__version__}")
    p.add_argument("--db", default=None,
                   help="memory file (default: $RECALL_DB, else the nearest .recall/memory.json, "
                        "else ~/.recall/memory.json)")
    sub = p.add_subparsers(dest="cmd", required=True, metavar="<command>")

    sub.add_parser("demo", help="watch a 16-month story play out").set_defaults(fn=cmd_demo)

    s = sub.add_parser("add", help="store a memory")
    s.add_argument("text")
    s.add_argument("--kind", choices=[k.value for k in Kind])
    s.add_argument("--source", default="user")
    s.add_argument("--importance", type=float, default=0.5)
    s.add_argument("--confidence", type=float, default=0.8)
    s.add_argument("--pin", action="store_true", help="never forget")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_add)

    s = sub.add_parser("ask", help="recall memories relevant to a question")
    s.add_argument("query")
    s.add_argument("--limit", type=int, default=5)
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_ask)

    s = sub.add_parser("context", help="print the prompt-ready working set")
    s.add_argument("query", nargs="?")
    s.add_argument("--budget", type=int, default=400, help="token budget")
    s.set_defaults(fn=cmd_context)

    s = sub.add_parser("questions", help='list open "has that changed?" questions')
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_questions)

    s = sub.add_parser("answer", help="answer a question: recall answer [ID] yes|no (default: latest)")
    s.add_argument("args", nargs="+")
    s.set_defaults(fn=cmd_answer)

    s = sub.add_parser("check", help="check text (e.g. an AI reply) for contradictions; exit 1 if any")
    s.add_argument("text", help="the text, or - to read stdin")
    s.add_argument("--store", action="store_true", help="also remember its claims to check future replies")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_check)

    s = sub.add_parser("forget", help="forget a memory by id or description")
    s.add_argument("target")
    s.add_argument("--reason", default="manual")
    s.set_defaults(fn=cmd_forget)

    s = sub.add_parser("sweep", help="age memories: fade, forget, settle disputes and stale questions")
    s.add_argument("--purge", action="store_true", help="delete forgotten tombstones")
    s.set_defaults(fn=cmd_sweep)

    s = sub.add_parser("list", help="list memories")
    s.add_argument("--all", action="store_true", help="include superseded, forgotten and assistant claims")
    s.set_defaults(fn=cmd_list)

    s = sub.add_parser("explain", help="audit trail for one memory")
    s.add_argument("id")
    s.set_defaults(fn=cmd_explain)

    sub.add_parser("stats", help="counts by status").set_defaults(fn=cmd_stats)

    s = sub.add_parser("auto", help='auto-yes on|off: skip "has that changed?" questions')
    s.add_argument("state", nargs="?", choices=["on", "off", "status"], default="status")
    s.add_argument("--project", action="store_true", help="only for the current project")
    s.set_defaults(fn=cmd_auto)

    s = sub.add_parser("config", help="show or change settings: recall config [get|set|unset] KEY [VALUE]")
    s.add_argument("action", nargs="?", choices=["list", "get", "set", "unset"])
    s.add_argument("key", nargs="?", choices=list(SETTINGS))
    s.add_argument("value", nargs="?")
    s.add_argument("--project", action="store_true", help="write to ./.recall/config.json")
    s.set_defaults(fn=cmd_config)

    sub.add_parser("init", help="give the current project its own memory (./.recall)").set_defaults(fn=cmd_init)
    sub.add_parser("where", help="print which memory file is in use").set_defaults(fn=cmd_where)

    sub.add_parser("mcp", help="run the MCP server on stdio (agents start this)").set_defaults(fn=cmd_mcp)

    s = sub.add_parser("hook", help="agent hook entry point (agents call this)")
    s.add_argument("event", choices=["session-start", "prompt", "response", "stop"])
    s.add_argument("--agent", default="generic")
    s.add_argument("--text", help="pass the prompt/reply directly instead of JSON on stdin")
    s.add_argument("--queue", action="store_true", help="never block; queue findings for the next turn")
    s.set_defaults(fn=cmd_hook)

    for verb, fn, helptext in (("install", cmd_install, "connect Recall to coding agents"),
                               ("uninstall", cmd_uninstall, "remove Recall from coding agents")):
        s = sub.add_parser(verb, help=helptext)
        s.add_argument("agents", nargs="*", metavar="agent")
        s.add_argument("--all", action="store_true", help="every supported agent" if verb == "install"
                       else "every agent Recall is installed in")
        if verb == "install":
            s.add_argument("--detected", action="store_true", help="every agent found on this machine")
        s.add_argument("--dry-run", action="store_true", help="show what would change")
        s.add_argument("--home", help=argparse.SUPPRESS)
        s.add_argument("--launcher", help="how agents should start recall (default: absolute path)")
        s.set_defaults(fn=fn)

    for name in ("agents", "integrations"):
        s = sub.add_parser(name, help="list supported agents and what's installed")
        s.add_argument("--json", action="store_true")
        s.add_argument("--home", help=argparse.SUPPRESS)
        s.set_defaults(fn=cmd_agents)

    sub.add_parser("doctor", help="check the setup").set_defaults(fn=cmd_doctor)

    s = sub.add_parser("export-integrations", help="write ready-to-copy integration files to a folder")
    s.add_argument("dir")
    s.set_defaults(fn=cmd_export)

    s = sub.add_parser("forget-all", help="delete the whole memory file")
    s.add_argument("--yes", action="store_true")
    s.set_defaults(fn=cmd_forget_all)
    return p


def main(argv: Optional[List[str]] = None) -> None:
    for stream in (sys.stdout, sys.stderr):  # Windows consoles/pipes default to cp1252
        if (getattr(stream, "encoding", "") or "").lower().replace("-", "") != "utf8":
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (AttributeError, ValueError):
                pass
    args = build_parser().parse_args(argv)
    try:
        sys.exit(args.fn(args))
    except (KeyError, ValueError) as e:
        print(f"error: {e.args[0] if e.args else e}", file=sys.stderr)
        sys.exit(2)

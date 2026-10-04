"""A 16-month story: watch Recall age, question, contradict and curate memory."""
from __future__ import annotations

from ._term import c
from .clock import ManualClock, fmt_date
from .engine import AddResult, Recall
from .models import Status

STATUS_STYLE = {
    Status.ACTIVE: ("●", "green"), Status.DORMANT: ("◐", "yellow"), Status.DISPUTED: ("⚠", "magenta"),
    Status.PENDING: ("?", "blue"), Status.SUPERSEDED: ("✕", "red"), Status.FORGOTTEN: ("○", "gray"),
}
ACTION = {
    "supersede_old": ("⟳", "green", "SUPERSEDES old belief"),
    "reject_new": ("🛡", "red", "REJECTED, old belief holds"),
    "dispute": ("⚠", "magenta", "DISPUTED"),
}
PAD = " " * 14


def _bar(r: float, width: int = 14) -> str:
    n = round(r * width)
    return "█" * n + "░" * (width - n)


def run_demo() -> None:
    clock = ManualClock()
    mem = Recall(clock=clock)

    def day() -> str:
        return c(fmt_date(clock.now()), "gray")

    def title(text: str) -> None:
        print("\n" + c(f"━━ {text} ", "bold", "cyan") + c("━" * max(2, 62 - len(text)), "cyan"))

    def say(text: str, **kw) -> AddResult:
        res = mem.add(text, **kw)
        src = f" via {kw['source']}" if "source" in kw else ""
        print(f" {day()}  {c('+', 'bold')} “{text}”{c(src, 'dim')}")
        for p in (res.parts or [res]):
            m = p.memory
            if m.pinned:
                print(c(f"{PAD}├ 📌 pinned: exempt from forgetting", "dim"))
            if p.merged:
                print(c(f"{PAD}↻ already known, reinforced (half-life → {m.half_life_days:.0f}d)", "dim"))
                continue
            for cl in m.claims:
                print(c(f"{PAD}├ claim    {cl}", "dim"))
            for q in p.questions:
                print(f"{PAD}└ {c('? ASKS FIRST', 'bold', 'blue')} {c(q.text, 'blue')}")
            if p.questions:
                continue
            for r in p.resolutions:
                icon, col, label = ACTION[r.action]
                old = mem.get(r.old_id)
                print(f"{PAD}└ {c(icon + ' ' + label, 'bold', col)} {c('«' + old.content + '»', 'dim')}")
                print(c(f"{PAD}  {r.reason}", "dim"))
        return res

    def reply_yes(res: AddResult) -> None:
        q = res.question
        mem.answer(q.id, yes=True)
        old = ", ".join("«" + o.content + "»" for o in q.old)
        print(f" {day()}  {c('↳', 'bold')} user: “yes”  →  {c('✓ confirmed', 'bold', 'green')} "
              f"{c(old + ' replaced', 'dim')}")

    def assistant(text: str, note: str = "consistent; its claims are kept to check later replies against") -> None:
        res = mem.observe(text)
        print(f" {day()}  {c('✦', 'bold', 'magenta')} assistant: “{text}”")
        if res.ok:
            print(c(f"{PAD}└ {note}", "dim"))
        for k in res.conflicts:
            label = "SELF-CONTRADICTION" if k.kind == "self" else "CONTRADICTS THE USER"
            print(f"{PAD}└ {c('⚠ ' + label, 'bold', 'magenta')}")
            print(c(f"{PAD}  {k.message()}", "dim"))

    def ask(q: str) -> None:
        hits = mem.recall(q, limit=2)
        ans = hits[0].memory.content if hits else c("(nothing known)", "dim")
        print(f" {day()}  {c('?', 'bold', 'blue')} {q}  →  {c(ans, 'bold')}")

    def sweep() -> None:
        rep = mem.sweep()
        print(f" {day()}  {c('⏳ ' + str(rep), 'yellow')}")

    def table() -> None:
        print(c("\n   status      retention       memory", "dim"))
        for m in mem.memories():
            if m.source == "assistant":
                continue
            st = mem._live_status(m, clock.now())
            icon, col = STATUS_STYLE[st]
            if st in (Status.SUPERSEDED, Status.FORGOTTEN):
                bar, pct = c("··············", "gray"), "   —"
            else:
                r = mem.retention_of(m.id)
                bar, pct = _bar(r), f"{r:4.0%}"
            pin = "📌" if m.pinned else "  "
            print(f"   {c(icon, col)} {c(st.value.ljust(10), col)} {bar} {pct} {pin} {m.content[:42]}")

    print(c("\n  RECALL", "bold", "cyan") + c("  ·  AI memory that forgets on purpose", "dim"))

    title("Week 1: learning about the user")
    say("I live in Toronto and work at Shopify")
    say("I love hiking and coffee")
    say("I'm vegetarian", pinned=True)   # pin what must never fade
    say("My favorite editor is vim")
    say("Remind me to buy milk tomorrow", importance=0.2)
    say("Team offsite is next Thursday", importance=0.3)

    title("Day 3: retrieval is rehearsal")
    clock.advance(days=3)
    ask("where does the user live")
    ask("what editor do they use")

    title("Day 45: time passes, ephemera dissolve")
    clock.advance(days=42)
    sweep()

    title("Day 120: the user changes their mind")
    clock.advance(days=75)
    say("I moved to Berlin")
    say("Actually, I don't like hiking anymore")
    editor = say("My favorite editor is VS Code")
    reply_yes(editor)
    print(c(f"{PAD}(with confirm=auto, `recall auto on`, it would have been accepted without asking)", "dim"))
    ask("where does the user live")

    title("Day 130: an untrustworthy source tries to rewrite history")
    clock.advance(days=10)
    say("I live in Paris", source="web", confidence=0.5)
    ask("where does the user live")

    title("Day 140: two equally credible sources disagree")
    clock.advance(days=10)
    say("The standup is at 9am", source="calendar", source_trust=0.7)
    say("The standup is at 10am", source="slack", source_trust=0.7)

    title("Day 150: the assistant contradicts itself")
    clock.advance(days=10)
    assistant("The staging database port is 5432.")
    clock.advance(hours=2)
    assistant("The staging database port is 6543.")
    assistant("You live in Toronto, so the 9am standup is early for you.")
    assistant("Correction: the staging database port is 5432.",
              note="✓ it said which one was right, so the dispute is settled")

    print(c("\n   What the LLM is told right now:", "dim"))
    for line in mem.active_context(token_budget=300).to_prompt().splitlines():
        print("   " + line)

    title("Day 510: a year of silence")
    clock.advance(days=360)
    sweep()
    table()
    print()
    ask("where does the user live")
    ask("does the user like hiking")
    print(c("\n   Why does Recall believe the user lives in Berlin?", "dim"))
    berlin = next(m for m in mem.memories() if "Berlin" in m.content)
    for line in mem.explain(berlin.id).splitlines():
        print("   " + line)
    print()

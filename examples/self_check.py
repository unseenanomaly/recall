"""Catch a model contradicting itself (or you) before the user does.

`observe()` checks a reply against what was said before and remembers its claims, so
the next reply is checked against this one. `check()` is the same thing as a dry run.
Run: python examples/self_check.py
"""
from recall import ManualClock, Recall

clock = ManualClock()
mem = Recall(clock=clock)
mem.add("I moved to Berlin")                                   # something the user told us

replies = [
    "Use Postgres 16. The staging database port is 5432.",
    "Restart the service. The staging database port is 6543.",  # contradicts reply #1
    "You live in Toronto, so the 9am call is early for you.",   # contradicts the user
    "Correction: the staging database port is 5432.",           # an explicit fix settles it
]
for reply in replies:
    clock.advance(hours=1)
    result = mem.observe(reply)
    print(f"assistant> {reply}")
    print("   " + ("ok" if result.ok else result.message().replace("\n", "\n   ")) + "\n")

draft = "The staging database port is 6543."
print("dry run on a draft:", "ok" if mem.check(draft).ok else mem.check(draft).conflicts[0].message())

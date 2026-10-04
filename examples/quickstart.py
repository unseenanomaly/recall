"""Run: python examples/quickstart.py"""
from recall import ManualClock, Recall

clock = ManualClock()          # swap for SystemClock() in production (it's the default)
mem = Recall(clock=clock)

mem.add("I live in Toronto and work at Shopify")
mem.add("I'm vegetarian", pinned=True)             # pinned = never forgotten

clock.advance(days=120)
result = mem.add("Actually I moved to Berlin")      # contradicts "Lives in Toronto"

print("superseded:", [mem.get(i).content for i in result.superseded])
print("reason    :", result.resolutions[0].reason)

# Retrieval is rehearsal: whatever you recall gets stronger.
for hit in mem.recall("where does the user live?"):
    print(f"recalled  : {hit.memory.content!r} (relevance {hit.relevance:.2f})")

# What the LLM should see *right now*, packed into a token budget:
print()
print(mem.active_context(token_budget=200).to_prompt())

# Time passes. Let Recall tidy up.
clock.advance(days=400)
print()
print(mem.sweep())

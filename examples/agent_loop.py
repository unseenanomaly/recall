"""Drop Recall into any chat loop.

`fake_llm` stands in for your model call; the memory plumbing is the real thing.
Run: python examples/agent_loop.py
"""
from recall import ManualClock, Recall
from recall.hooks import parse_answer

clock = ManualClock()
memory = Recall(clock=clock)
asked = []                                                     # questions shown to the user last turn


def fake_llm(system: str, user: str) -> str:
    questions = [line[2:] for line in system.splitlines() if line.startswith("- ") and "Has that changed?" in line]
    if questions:
        return questions[0]                                    # a real model asks this in its own words
    if "weekend" in user:
        return "Since you live in Toronto, try the Bruce Trail."   # ...and sometimes gets things wrong
    return "Noted."


def chat(user_message: str) -> str:
    if asked and parse_answer(user_message) is not None:       # 1. "yes"/"no" answers last turn's question
        memory.answer(asked.pop().id, parse_answer(user_message))
    elif not user_message.rstrip().endswith("?"):              # 2. learn statements, not questions
        memory.add(user_message)                               #    (contradictions are resolved, or asked about)
    ctx = memory.active_context(token_budget=300, reinforce=True)   # 3. curate the working set
    asked[:] = ctx.questions
    reply = fake_llm("You are a helpful assistant.\n" + ctx.to_prompt(), user_message)
    check = memory.observe(reply)                              # 4. hold the model to what it said before
    if check.conflicts:
        reply += "\n   [recall] " + check.message().replace("\n", "\n   [recall] ")
    return reply


for turn in ["I live in Toronto and I love hiking",
             "I live in Berlin",                               # no "actually": Recall asks first
             "yes",
             "Where should I go this weekend?"]:
    clock.advance(days=10)
    print(f"user> {turn}\nbot > {chat(turn)}\n")

print(memory.active_context().to_prompt())

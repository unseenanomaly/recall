"""Plug any model in as a semantic contradiction judge.

The structured detector handles "lives in X vs Y" exactly; the judge handles
fuzzy cases ("we deploy on Fridays" vs "no deploys at the end of the week").
Replace `judge` with a real call to your model. Run: python examples/llm_judge.py
"""
from recall import LLMJudgeDetector, ManualClock, NegationDetector, Recall, StructuredDetector


def judge(new_statement: str, old_statement: str):
    """Return (is_contradiction, explanation). Swap in an LLM call here, e.g.:

        prompt = f"Do these contradict?\\nA: {old_statement}\\nB: {new_statement}\\nAnswer JSON."
    """
    flip = {("friday", "freeze"), ("monolith", "microservices")}
    n, o = new_statement.lower(), old_statement.lower()
    hit = any((a in n and b in o) or (b in n and a in o) for a, b in flip)
    return hit, "the two statements describe incompatible policies" if hit else ""


clock = ManualClock()
mem = Recall(clock=clock, detectors=[StructuredDetector(), NegationDetector(), LLMJudgeDetector(judge)])

mem.add("Deploys are allowed on Friday afternoons for the payments team")
clock.advance(days=14)
res = mem.add("The payments team now has a deploy freeze on Friday afternoons")
print(res.contradictions[0].kind, "contradiction ->", res.resolutions[0].action)
print("Recall asks:", res.question.text)        # the same person said both, so it checks first
mem.answer(res.question.id, yes=True)
print([(m.content, m.status.value) for m in mem.memories()])

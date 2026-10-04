from recall import (LLMJudgeDetector, ManualClock, NegationDetector, Recall, Status,
                    StructuredDetector)


def make():
    clock = ManualClock()
    return Recall(clock=clock), clock


def test_new_residence_supersedes_old():
    mem, clock = make()
    old = mem.add("I live in Toronto").memory
    clock.advance(days=90)
    res = mem.add("Actually I moved to Berlin")
    assert res.superseded == [old.id]
    assert old.status == Status.SUPERSEDED and old.superseded_by == res.memory.id
    assert res.memory.status == Status.ACTIVE
    assert old.id in res.memory.supersedes


def test_polarity_flip_is_a_contradiction():
    mem, clock = make()
    mem.add("I love hiking")
    clock.advance(days=10)
    res = mem.add("I don't like hiking anymore")
    assert res.contradictions and res.contradictions[0].kind == "negation"
    assert res.superseded


def test_multi_valued_predicates_coexist():
    mem, _ = make()
    mem.add("I love hiking")
    res = mem.add("I love coffee")
    assert not res.contradictions
    assert len(mem.memories(Status.ACTIVE)) == 2


def test_compound_statement_only_loses_the_conflicting_part():
    mem, clock = make()
    mem.add("I work at Shopify and I love hiking")
    clock.advance(days=30)
    mem.add("I don't like hiking anymore")
    live = {m.content for m in mem.memories(Status.ACTIVE)}
    assert "Works at Shopify" in live
    assert "Likes hiking" not in live


def test_untrusted_source_cannot_overwrite_trusted_belief():
    mem, clock = make()
    home = mem.add("I live in Berlin", confidence=0.9).memory
    clock.advance(days=20)
    res = mem.add("I live in Paris", source="web", confidence=0.5)
    assert res.rejected and res.memory.superseded_by == home.id
    assert home.status == Status.ACTIVE


def test_equally_credible_sources_become_disputed():
    mem, _ = make()
    a = mem.add("The standup is at 9am", source="calendar", source_trust=0.7).memory
    b = mem.add("The standup is at 10am", source="slack", source_trust=0.7).memory
    assert a.status == b.status == Status.DISPUTED
    assert a.disputes_with == [b.id] and b.disputes_with == [a.id]


def test_manual_dispute_resolution():
    mem, _ = make()
    a = mem.add("The standup is at 9am", source="calendar", source_trust=0.7).memory
    b = mem.add("The standup is at 10am", source="slack", source_trust=0.7).memory
    mem.resolve_dispute(b.id)
    assert b.status == Status.ACTIVE and a.status == Status.SUPERSEDED


def test_sweep_settles_dispute_when_evidence_shifts():
    mem, clock = make()
    a = mem.add("The standup is at 9am", source="calendar", source_trust=0.7).memory
    b = mem.add("The standup is at 10am", source="slack", source_trust=0.7).memory
    clock.advance(days=1)
    for _ in range(6):                       # the slack version keeps being confirmed elsewhere
        mem.reinforce(b.id)
    rep = mem.sweep()
    assert rep.resolved
    assert b.status == Status.ACTIVE and a.status == Status.SUPERSEDED


def test_repeating_a_fact_reinforces_instead_of_duplicating():
    mem, clock = make()
    first = mem.add("I live in Toronto").memory
    clock.advance(days=30)
    res = mem.add("I live in Toronto")
    assert res.merged and res.memory.id == first.id
    assert len(mem.store) == 1 and first.access_count == 1


def test_free_text_negation_detector():
    mem, clock = make()
    a = mem.add("The public API is rate limited per key").memory
    clock.advance(days=5)
    res = mem.add("The public API is not rate limited per key", source="user")
    assert res.contradictions and res.contradictions[0].kind == "negation"
    # the user said both, so Recall asks instead of picking one for them
    assert res.pending and a.status == Status.ACTIVE
    assert res.question.text.startswith('You said before: "The public API is rate limited per key"')


def test_llm_judge_detector_is_pluggable():
    calls = []

    def judge(new, old):
        calls.append((new, old))
        return ("monolith" in new and "microservices" in old, "architecture changed")

    clock = ManualClock()
    mem = Recall(clock=clock, detectors=[StructuredDetector(), LLMJudgeDetector(judge)])
    old = mem.add("We run on microservices architecture for the backend", claims=[]).memory
    clock.advance(days=10)
    res = mem.add("We are consolidating into a monolith architecture for the backend", claims=[])
    assert calls and res.contradictions[0].kind == "semantic"
    assert res.pending                        # same speaker, no "actually": ask first
    mem.answer(res.question.id, yes=True)
    assert old.status == Status.SUPERSEDED and res.memory.status == Status.ACTIVE


def test_detectors_can_be_disabled():
    mem = Recall(clock=ManualClock(), detectors=[])
    mem.add("I live in Toronto")
    res = mem.add("I live in Berlin")
    assert not res.contradictions
    assert len(mem.memories(Status.ACTIVE)) == 2

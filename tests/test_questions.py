"""'You said before that ... Has that changed?' and the auto-yes switch."""
from recall import Config, JSONStore, ManualClock, Recall, Status


def make(**cfg):
    clock = ManualClock()
    return Recall(clock=clock, config=Config(**cfg)), clock


def test_user_changing_their_mind_is_asked_not_rejected_or_overwritten():
    mem, clock = make()
    home = mem.add("I live in Toronto").memory
    clock.advance(days=30)
    res = mem.add("I live in Berlin")
    assert res.pending and not res.rejected
    assert res.question.text == "You said before that you live in Toronto (2025-01-06). Has that changed?"
    assert home.status == Status.ACTIVE                       # nothing changes until they answer
    assert [h.memory.content for h in mem.recall("where does the user live")] == ["I live in Toronto"]
    prompt = mem.active_context().to_prompt()
    assert "Has that changed?" in prompt and "may have changed" in prompt


def test_answer_yes_replaces_the_old_belief():
    mem, clock = make()
    home = mem.add("I live in Toronto").memory
    clock.advance(days=30)
    q = mem.add("I live in Berlin").question
    mem.answer(q.id, yes=True)
    assert q.new.status == Status.ACTIVE and home.status == Status.SUPERSEDED
    assert home.superseded_by == q.new.id and not mem.questions()
    assert "confirmed it changed" in mem.explain(q.new.id)


def test_answer_no_keeps_the_old_belief_and_strengthens_it():
    mem, clock = make()
    home = mem.add("I live in Toronto", confidence=0.7).memory
    clock.advance(days=30)
    q = mem.add("I live in Berlin").question
    mem.answer(q.id, yes=False)
    assert home.status == Status.ACTIVE and q.new.status == Status.SUPERSEDED
    assert home.confidence > 0.7


def test_auto_yes_accepts_the_newest_statement_without_asking():
    mem, clock = make(confirm_changes="auto")
    home = mem.add("I live in Toronto").memory
    clock.advance(days=30)
    res = mem.add("I live in Berlin")
    assert not res.questions and res.superseded == [home.id]
    assert "auto-confirmed" in res.resolutions[0].reason


def test_explicit_corrections_never_ask():
    mem, clock = make()
    mem.add("I live in Toronto")
    clock.advance(days=1)
    for text in ("Actually I live in Berlin", "I moved to Lisbon", "I was wrong, I live in Porto"):
        res = mem.add(text)
        assert not res.questions and res.superseded, text


def test_user_overrides_a_less_trusted_source_without_asking():
    mem, clock = make()
    web = mem.add("I live in Paris", source="web").memory
    clock.advance(days=1)
    res = mem.add("I live in Berlin")
    assert not res.questions and web.status == Status.SUPERSEDED


def test_a_newer_statement_replaces_an_unconfirmed_one():
    mem, clock = make()
    mem.add("I live in Toronto")
    clock.advance(days=1)
    paris = mem.add("I live in Paris").memory
    rome = mem.add("I live in Rome")
    assert paris.status == Status.SUPERSEDED
    assert [q.id for q in mem.questions()] == [rome.memory.id]


def test_unanswered_questions_settle_after_the_ttl():
    mem, clock = make(pending_ttl_days=7)
    home = mem.add("I live in Toronto").memory
    q = mem.add("I live in Berlin").question
    clock.advance(days=8)
    rep = mem.sweep()
    assert rep.answered == [q.id] and home.status == Status.SUPERSEDED

    mem, clock = make(pending_ttl_days=7, pending_default="no")
    home = mem.add("I live in Toronto").memory
    q = mem.add("I live in Berlin").question
    clock.advance(days=8)
    mem.sweep()
    assert home.status == Status.ACTIVE and q.new.status == Status.SUPERSEDED


def test_only_the_conflicting_part_of_a_compound_statement_waits():
    mem, clock = make()
    mem.add("I live in Toronto")
    clock.advance(days=1)
    res = mem.add("I live in Berlin and work at Shopify")
    assert len(res.questions) == 1
    assert {p.memory.content: p.memory.status for p in res.parts} == {
        "Lives in Berlin": Status.PENDING, "Works at Shopify": Status.ACTIVE}


def test_preferences_and_world_facts_are_phrased_naturally():
    mem, clock = make()
    mem.add("My favorite editor is vim")
    mem.add("The deploy window is Friday")
    clock.advance(days=1)
    assert mem.add("My favorite editor is VS Code").question.text.startswith(
        "You said before that your favorite editor is vim")
    assert mem.add("The deploy window is Monday").question.text.startswith(
        'You said before: "The deploy window is Friday"')


def test_pending_questions_survive_a_restart(tmp_path):
    path = str(tmp_path / "m.json")
    clock = ManualClock()
    mem = Recall(JSONStore(path), clock=clock)
    mem.add("I live in Toronto")
    q = mem.add("I live in Berlin").question
    again = Recall(JSONStore(path), clock=clock)
    assert [x.text for x in again.questions()] == [q.text]
    again.answer(q.id, True)
    assert [m.content for m in again.memories(Status.ACTIVE)] == ["I live in Berlin"]

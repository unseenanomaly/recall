"""The assistant contradicting itself, or contradicting the user."""
from recall import Config, ManualClock, Recall, Status, extract_claims
from recall.claims import swap_perspective


def make(**cfg):
    clock = ManualClock()
    return Recall(clock=clock, config=Config(**cfg)), clock


def test_assistant_contradicting_itself_is_flagged():
    mem, clock = make()
    assert mem.observe("The staging database port is 5432.").ok
    clock.advance(hours=1)
    res = mem.observe("The staging database port is 6543.")
    assert [c.kind for c in res.conflicts] == ["self"]
    msg = res.message()
    assert "5432" in msg and "6543" in msg and "Correction:" in msg
    olds = [m for m in mem.memories() if m.source == "assistant"]
    assert {m.status for m in olds} == {Status.DISPUTED}


def test_announced_corrections_are_not_contradictions():
    mem, clock = make()
    mem.observe("The default branch is main.")
    res = mem.observe("I was wrong earlier: the default branch is trunk.")
    assert res.ok
    live = [m.content for m in mem.memories(Status.ACTIVE)]
    assert live == ["The default branch is trunk"]


def test_a_correction_settles_the_dispute_it_started():
    mem, clock = make()
    mem.observe("The staging database port is 5432.")
    mem.observe("The staging database port is 6543.")
    mem.observe("Correction: the staging database port is 5432.")
    states = {m.claims[0].value: m.status for m in mem.memories() if m.source == "assistant"}
    assert states == {"5432": Status.ACTIVE, "6543": Status.SUPERSEDED}


def test_assistant_contradicting_the_user_is_caught_and_never_wins():
    mem, clock = make()
    home = mem.add("I moved to Berlin").memory
    res = mem.observe("You live in Toronto, so the 9am standup is early for you.")
    assert [c.kind for c in res.conflicts] == ["user"]
    assert "I moved to Berlin" in res.message()
    assert home.status == Status.ACTIVE
    # the model's guess about the user is checked but never stored
    assert not [m for m in mem.memories() if m.source == "assistant"]


def test_assistant_cannot_overwrite_a_world_fact_the_user_gave():
    mem, clock = make()
    standup = mem.add("The standup is at 9am").memory
    res = mem.observe("The standup is at 10am.")
    assert [c.kind for c in res.conflicts] == ["user"]
    assert standup.status == Status.ACTIVE


def test_check_is_a_dry_run():
    mem, clock = make()
    mem.observe("The API base URL is api.example.com.")
    before = len(mem.store)
    res = mem.check("The API base URL is api.example.org.")
    assert [c.kind for c in res.conflicts] == ["self"] and len(mem.store) == before


def test_hedges_questions_and_code_are_not_claims():
    mem, clock = make()
    mem.observe("The port is 8080.")
    text = ("If the port is 3000, restart it. The port might be 9000. Is the port 7000?\n"
            "```\nthe port is 1234\n```")
    assert mem.check(text).ok


def test_newest_mode_lets_the_assistant_update_quietly():
    mem, clock = make(self_contradiction="newest")
    mem.observe("The port is 8080.")
    assert mem.observe("The port is 3000.").ok


def test_assistant_claims_stay_out_of_the_prompt_by_default():
    mem, clock = make()
    mem.add("I'm vegetarian")
    mem.observe("The cache TTL is 60 seconds.")
    assert "cache" not in mem.active_context().to_prompt().lower()
    mem.config.context_includes_assistant = True
    assert "cache" in mem.active_context().to_prompt().lower()


def test_reading_text_from_the_assistant_side():
    assert swap_perspective("You live in Oslo and I'm happy") == "I live in Oslo and you're happy"
    claims = extract_claims("You work at Shopify. I live in Paris.", speaker="assistant")
    assert [(c.subject, c.predicate, c.value) for c in claims] == [("user", "works_at", "Shopify")]
    # conversational "the X is Y" is not a fact about the world
    assert extract_claims("The problem is that the loop never ends.", speaker="assistant") == []


def test_relaying_recalls_question_is_not_a_contradiction():
    mem, clock = make()
    mem.add("I live in Toronto")
    q = mem.add("I live in Berlin").question
    mem.answer(q.id, yes=True)
    assert mem.check("You said before that you live in Toronto (2025-01-06). Has that changed?").ok
    assert mem.check("Earlier I said you live in Toronto, but that's out of date.").ok
    assert not mem.check("Since you live in Toronto, try the Bruce Trail.").ok

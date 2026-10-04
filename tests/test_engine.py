from recall import JSONStore, ManualClock, Recall, Status


def test_recall_ranks_relevant_and_current_memories():
    mem = Recall(clock=ManualClock())
    mem.add("I live in Toronto")
    mem.add("I'm vegetarian")
    mem.add("My favorite editor is vim")
    hits = mem.recall("what editor does the user use?")
    assert hits[0].memory.content == "My favorite editor is vim"
    assert mem.recall("quantum chromodynamics") == []


def test_superseded_memories_are_never_served():
    clock = ManualClock()
    mem = Recall(clock=clock)
    mem.add("I live in Toronto")
    clock.advance(days=60)
    mem.add("I moved to Berlin")
    contents = [h.memory.content for h in mem.recall("where does the user live", limit=10)]
    assert contents == ["I moved to Berlin"]


def test_active_context_respects_token_budget():
    mem = Recall(clock=ManualClock())
    for i in range(30):
        mem.add(f"Project note number {i} about the {i}th microservice deployment", claims=[])
    pack = mem.active_context(token_budget=120)
    assert 0 < len(pack) < 30 and pack.tokens <= 120 and pack.dropped > 0
    assert pack.to_prompt().startswith("## ")


def test_disputed_memories_are_flagged_in_context():
    mem = Recall(clock=ManualClock())
    mem.add("The standup is at 9am", source="calendar", source_trust=0.7)
    mem.add("The standup is at 10am", source="slack", source_trust=0.7)
    assert "unverified" in mem.active_context().to_prompt()


def test_recall_does_not_reinforce_disputed_memories():
    mem = Recall(clock=ManualClock())
    a = mem.add("The standup is at 9am", source="calendar", source_trust=0.7).memory
    mem.add("The standup is at 10am", source="slack", source_trust=0.7)
    mem.recall("when is the standup")
    assert a.access_count == 0


def test_json_store_roundtrip(tmp_path):
    path = str(tmp_path / "mem.json")
    clock = ManualClock()
    mem = Recall(JSONStore(path), clock=clock)
    mem.add("I live in Toronto")
    clock.advance(days=30)
    mem.add("I moved to Berlin")
    mem.recall("where does the user live")

    again = Recall(JSONStore(path), clock=clock)
    assert again.stats() == mem.stats()
    assert [m.content for m in again.memories(Status.ACTIVE)] == ["I moved to Berlin"]
    toronto = [m for m in again.memories(Status.SUPERSEDED)][0]
    assert toronto.superseded_by is not None and toronto.history


def test_explain_has_an_audit_trail():
    clock = ManualClock()
    mem = Recall(clock=clock)
    old = mem.add("I live in Toronto").memory
    clock.advance(days=40)
    mem.add("I moved to Berlin")
    text = mem.explain(old.id)
    assert "superseded" in text and "Toronto" in text


def test_forget_and_pin():
    mem = Recall(clock=ManualClock())
    m = mem.add("My badge number is 4471").memory
    mem.forget(m.id, "user request")
    assert m.status == Status.FORGOTTEN
    assert mem.recall("badge number") == []


def test_empty_content_rejected():
    import pytest
    with pytest.raises(ValueError):
        Recall().add("   ")


def test_pluggable_relevance_function():
    # a stand-in for an embedding model: everything about places is "related" to travel
    def fake_embedding_relevance(query, memory):
        return 0.9 if "travel" in query and "live in" in memory.content.lower() else 0.0

    mem = Recall(clock=ManualClock(), relevance_fn=fake_embedding_relevance)
    mem.add("I live in Berlin")
    mem.add("I'm vegetarian")
    hits = mem.recall("plan my travel")
    assert [h.memory.content for h in hits] == ["I live in Berlin"]

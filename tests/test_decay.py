import pytest

from recall import Config, Kind, ManualClock, Recall, Status
from recall.decay import initial_half_life


def test_retention_halves_every_half_life():
    clock = ManualClock()
    mem = Recall(clock=clock)
    m = mem.add("Some standalone fact about the project", importance=0.5).memory
    h = m.half_life_days
    clock.advance(days=h)
    assert mem.retention_of(m.id) == pytest.approx(0.5, abs=1e-6)
    clock.advance(days=h)
    assert mem.retention_of(m.id) == pytest.approx(0.25, abs=1e-6)


def test_importance_extends_half_life():
    cfg = Config()
    assert initial_half_life(Kind.FACT, 1.0, cfg) > initial_half_life(Kind.FACT, 0.0, cfg)


def test_ephemeral_memories_vanish_fast_identity_stays():
    clock = ManualClock()
    mem = Recall(clock=clock)
    todo = mem.add("Remind me to buy milk tomorrow").memory
    home = mem.add("I live in Oslo").memory
    clock.advance(days=30)
    rep = mem.sweep()
    assert todo.id in rep.forgotten
    assert home.status == Status.ACTIVE


def test_lifecycle_active_dormant_forgotten():
    clock = ManualClock()
    mem = Recall(clock=clock)
    m = mem.add("The build uses a custom linker script", kind=Kind.EVENT, importance=0.5).memory
    seen = [m.status]
    for _ in range(12):
        clock.advance(days=15)
        mem.sweep()
        if m.status != seen[-1]:
            seen.append(m.status)
    assert seen == [Status.ACTIVE, Status.DORMANT, Status.FORGOTTEN]


def test_recall_strengthens_memory_more_when_nearly_forgotten():
    clock = ManualClock()
    mem = Recall(clock=clock)
    a = mem.add("Alpha service owns the billing queue", kind=Kind.EVENT).memory
    b = mem.add("Beta service owns the audit queue", kind=Kind.EVENT).memory
    h0 = a.half_life_days
    clock.advance(days=5)
    mem.reinforce(a.id)
    gain_early = a.half_life_days / h0
    clock.advance(days=60)
    h1 = b.half_life_days
    mem.reinforce(b.id)
    gain_late = b.half_life_days / h1
    assert gain_late > gain_early


def test_recalled_dormant_memory_is_revived():
    clock = ManualClock()
    mem = Recall(clock=clock)
    m = mem.add("The staging cluster lives in eu-west-1", kind=Kind.EVENT).memory
    clock.advance(days=60)
    mem.sweep()
    assert m.status == Status.DORMANT
    hits = mem.recall("where is the staging cluster")
    assert hits and hits[0].memory.id == m.id
    assert m.status == Status.ACTIVE
    assert mem.retention_of(m.id) == pytest.approx(1.0)


def test_pinned_never_fades():
    clock = ManualClock()
    mem = Recall(clock=clock)
    m = mem.add("I'm allergic to penicillin", pinned=True).memory
    clock.advance(days=5000)
    mem.sweep()
    assert m.status == Status.ACTIVE


def test_purge_removes_tombstones():
    clock = ManualClock()
    mem = Recall(clock=clock)
    mem.add("Remind me to buy milk tomorrow")
    clock.advance(days=60)
    mem.sweep()
    assert mem.purge() == 1
    assert len(mem.store) == 0

"""Every tunable knob in one place."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict

from .models import Kind


@dataclass
class Weights:
    """How much each signal contributes when two memories disagree."""

    recency: float = 0.30
    confidence: float = 0.25
    trust: float = 0.25
    reinforcement: float = 0.10
    retention: float = 0.10


@dataclass
class Config:
    # --- forgetting curve -------------------------------------------------
    #: Base half-life (days) per kind of knowledge, before importance scaling.
    half_life_days: Dict[Kind, float] = field(
        default_factory=lambda: {
            Kind.IDENTITY: 730.0,
            Kind.FACT: 180.0,
            Kind.PREFERENCE: 120.0,
            Kind.EVENT: 30.0,
            Kind.EPHEMERAL: 3.0,
        }
    )
    #: retention >= active_threshold  -> ACTIVE
    active_threshold: float = 0.35
    #: forget_threshold <= retention < active_threshold -> DORMANT, below -> FORGOTTEN
    forget_threshold: float = 0.08
    #: Each recall multiplies the half-life by (base + difficulty * (1 - retention)).
    #: Recalling something you were about to forget strengthens it more.
    reinforce_base: float = 1.4
    reinforce_difficulty: float = 1.0
    max_half_life_days: float = 3650.0

    # --- contradiction resolution ----------------------------------------
    weights: Weights = field(default_factory=Weights)
    #: Score difference below which neither side wins and both become DISPUTED.
    dispute_margin: float = 0.06
    #: Age (days) at which the recency signal of a memory halves.
    recency_half_life_days: float = 45.0
    #: Bonus when a statement is phrased as a correction ("actually", "no longer"...).
    correction_bonus: float = 0.15
    #: A later statement from the *same source* beats an earlier one.
    same_source_bonus: float = 0.10
    #: Superseded memories are kept this long (audit / undo) before being forgotten.
    superseded_ttl_days: float = 365.0

    # --- changes the user makes to their own facts ------------------------
    #: The user says something that conflicts with what *they* said before, and
    #: doesn't phrase it as a correction ("actually", "I moved", "no longer"...).
    #:   "ask"  -> hold the new statement as PENDING and ask
    #:             "You said before that you live in Berlin. Has that changed?"
    #:   "auto" -> auto-yes: the newest statement wins without asking
    #: Either way, a user's statement is never silently rejected.
    confirm_changes: str = "ask"
    #: An unanswered question is settled after this many days...
    pending_ttl_days: float = 7.0
    #: ...with this answer ("yes" keeps the newer statement, "no" keeps the old one).
    pending_default: str = "yes"

    # --- the assistant contradicting itself -------------------------------
    #: The assistant states something that conflicts with what *it* said earlier,
    #: without flagging it as a correction ("I was wrong", "correction:"...).
    #:   "flag"   -> both statements become DISPUTED and a heads-up is queued for the model
    #:   "newest" -> the newer statement quietly wins
    self_contradiction: str = "flag"
    #: Assistant statements are testimony, not truth: they fade faster than user facts...
    assistant_half_life_days: float = 30.0
    #: ...and are left out of active_context() unless this is True.
    context_includes_assistant: bool = False

    # --- source trust -----------------------------------------------------
    source_trust: Dict[str, float] = field(
        default_factory=lambda: {
            "user": 1.0,
            "system": 0.9,
            "tool": 0.8,
            "assistant": 0.7,
            "document": 0.7,
            "web": 0.45,
            "hearsay": 0.3,
        }
    )
    default_source_trust: float = 0.6

    # --- retrieval --------------------------------------------------------
    min_relevance: float = 0.15
    reinforce_on_recall: bool = True

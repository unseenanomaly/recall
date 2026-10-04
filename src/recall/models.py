"""Core data model."""
from __future__ import annotations

import enum
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


class Status(str, enum.Enum):
    ACTIVE = "active"          # believed and available to the model
    DORMANT = "dormant"        # faded: still believed, but only surfaced when relevant
    DISPUTED = "disputed"      # conflicting evidence, unresolved
    PENDING = "pending"        # the user said something new; waiting for "has that changed?"
    SUPERSEDED = "superseded"  # replaced by a newer / stronger memory
    FORGOTTEN = "forgotten"    # decayed away; kept only as a tombstone until purged


class Kind(str, enum.Enum):
    IDENTITY = "identity"      # name, home, age: decays very slowly
    FACT = "fact"
    PREFERENCE = "preference"
    EVENT = "event"
    EPHEMERAL = "ephemeral"    # todos, "today" context: decays in days


@dataclass
class Claim:
    """A structured assertion extracted from a memory: (subject, predicate, value)."""

    subject: str
    predicate: str
    value: str
    polarity: bool = True      # False => "does NOT ..."
    single: bool = True        # True => only one value can be true at a time

    def key(self) -> Tuple[str, str]:
        return (self.subject, self.predicate)

    def __str__(self) -> str:
        neg = "" if self.polarity else "not "
        return f"{self.subject}.{self.predicate} = {neg}{self.value}"

    def to_dict(self) -> Dict[str, Any]:
        return dict(subject=self.subject, predicate=self.predicate, value=self.value,
                    polarity=self.polarity, single=self.single)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Claim":
        return cls(**d)


def _new_id() -> str:
    return "m_" + uuid.uuid4().hex[:8]


@dataclass
class Memory:
    content: str
    kind: Kind = Kind.FACT
    claims: List[Claim] = field(default_factory=list)
    id: str = field(default_factory=_new_id)

    confidence: float = 0.8
    importance: float = 0.5
    source: str = "user"
    source_trust: float = 1.0
    correction_cue: bool = False
    pinned: bool = False
    tags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    created_at: float = 0.0
    last_reinforced: float = 0.0
    last_accessed: float = 0.0
    access_count: int = 0
    half_life_days: float = 180.0

    status: Status = Status.ACTIVE
    status_changed_at: float = 0.0
    superseded_by: Optional[str] = None
    supersedes: List[str] = field(default_factory=list)
    disputes_with: List[str] = field(default_factory=list)
    #: PENDING only: the beliefs this memory replaces once the user confirms the change.
    pending_against: List[str] = field(default_factory=list)
    #: PENDING only: what to ask ("You said before that ... Has that changed?").
    question: Optional[str] = None
    history: List[Dict[str, Any]] = field(default_factory=list)

    def log(self, ts: float, event: str, detail: str = "") -> None:
        self.history.append({"t": ts, "event": event, "detail": detail})

    def to_dict(self) -> Dict[str, Any]:
        return dict(
            id=self.id, content=self.content, kind=self.kind.value,
            claims=[c.to_dict() for c in self.claims],
            confidence=self.confidence, importance=self.importance,
            source=self.source, source_trust=self.source_trust,
            correction_cue=self.correction_cue, pinned=self.pinned,
            tags=list(self.tags), metadata=dict(self.metadata),
            created_at=self.created_at, last_reinforced=self.last_reinforced,
            last_accessed=self.last_accessed, access_count=self.access_count,
            half_life_days=self.half_life_days, status=self.status.value,
            status_changed_at=self.status_changed_at, superseded_by=self.superseded_by,
            supersedes=list(self.supersedes), disputes_with=list(self.disputes_with),
            pending_against=list(self.pending_against), question=self.question,
            history=list(self.history),
        )

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Memory":
        d = dict(d)
        d["kind"] = Kind(d["kind"])
        d["status"] = Status(d["status"])
        d["claims"] = [Claim.from_dict(c) for c in d.get("claims", [])]
        return cls(**d)

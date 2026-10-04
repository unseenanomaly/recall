"""Contradiction detection.

Detectors are small, composable and pluggable. Each one looks at a *new* memory
and the memories already held, and returns the conflicts it can prove.

* :class:`StructuredDetector` - exact, claim-level conflicts
  (``lives_in=toronto`` vs ``lives_in=berlin``; ``likes hiking`` vs ``does not like hiking``).
* :class:`NegationDetector`   - free-text near-duplicates whose polarity flipped.
* :class:`LLMJudgeDetector`   - delegate hard semantic cases to any model you like.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Iterable, List, Optional, Protocol, Tuple

from .models import Claim, Memory
from .retrieval import tokenize


@dataclass
class Contradiction:
    new_id: str
    old_id: str
    kind: str                       # "value_conflict" | "negation" | "semantic"
    reason: str
    claim_new: Optional[Claim] = None
    claim_old: Optional[Claim] = None
    confidence: float = 1.0


class Detector(Protocol):
    def detect(self, new: Memory, existing: Iterable[Memory]) -> List[Contradiction]: ...


def values_agree(a: str, b: str) -> bool:
    """True if two claim values denote the same thing ('berlin' ~ 'berlin germany')."""
    a, b = a.lower(), b.lower()
    if a == b:
        return True
    ta, tb = set(re.findall(r"[a-z0-9]+", a)), set(re.findall(r"[a-z0-9]+", b))
    if not ta or not tb:
        return False
    return ta <= tb or tb <= ta


class StructuredDetector:
    name = "structured"

    def detect(self, new: Memory, existing: Iterable[Memory]) -> List[Contradiction]:
        found: List[Contradiction] = []
        for old in existing:
            hit = self._compare(new, old)
            if hit:
                found.append(hit)
        return found

    @staticmethod
    def _compare(new: Memory, old: Memory) -> Optional[Contradiction]:
        for a in new.claims:
            for b in old.claims:
                if a.key() != b.key():
                    continue
                agree = values_agree(a.value, b.value)
                if a.polarity != b.polarity and agree:
                    return Contradiction(
                        new.id, old.id, "negation",
                        f"'{a}' directly negates '{b}'", a, b,
                    )
                if a.polarity and b.polarity and a.single and b.single and not agree:
                    return Contradiction(
                        new.id, old.id, "value_conflict",
                        f"{a.subject}.{a.predicate} can only have one value: "
                        f"'{b.value}' vs '{a.value}'", a, b,
                    )
        return None


_NEG_WORDS = {"not", "no", "never", "none", "neither", "nor", "cannot", "without", "nothing"}


def _is_negated(text: str) -> bool:
    words = re.findall(r"[a-z']+", text.lower().replace("\u2019", "'"))
    return any(w in _NEG_WORDS or w.endswith("n't") for w in words)


def _jaccard(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


class NegationDetector:
    """Catches 'The API is rate limited' vs 'The API is not rate limited' in free text."""

    name = "negation"

    def __init__(self, min_overlap: float = 0.6):
        self.min_overlap = min_overlap

    def detect(self, new: Memory, existing: Iterable[Memory]) -> List[Contradiction]:
        found: List[Contradiction] = []
        tn = set(tokenize(new.content))
        for old in existing:
            if new.claims and old.claims:
                continue  # structured detector owns those
            to = set(tokenize(old.content))
            overlap = _jaccard(tn, to)
            if overlap >= self.min_overlap and _is_negated(new.content) != _is_negated(old.content):
                found.append(Contradiction(
                    new.id, old.id, "negation",
                    f"near-identical statements ({overlap:.0%} overlap) with opposite polarity",
                    confidence=min(1.0, overlap),
                ))
        return found


Verdict = Tuple[bool, str]


class LLMJudgeDetector:
    """Ask any model whether two statements contradict.

    ``judge(new_text, old_text)`` must return ``(is_contradiction, explanation)``.
    Candidates are pre-filtered by lexical overlap so you only pay for plausible pairs.
    """

    name = "llm-judge"

    def __init__(self, judge: Callable[[str, str], Verdict], min_overlap: float = 0.15,
                 max_candidates: int = 5):
        self.judge = judge
        self.min_overlap = min_overlap
        self.max_candidates = max_candidates

    def detect(self, new: Memory, existing: Iterable[Memory]) -> List[Contradiction]:
        tn = set(tokenize(new.content))
        scored = []
        for old in existing:
            ov = _jaccard(tn, set(tokenize(old.content)))
            if ov >= self.min_overlap:
                scored.append((ov, old))
        scored.sort(key=lambda x: -x[0])
        found: List[Contradiction] = []
        for _, old in scored[: self.max_candidates]:
            is_c, why = self.judge(new.content, old.content)
            if is_c:
                found.append(Contradiction(new.id, old.id, "semantic", why, confidence=0.8))
        return found

"""Tiny, dependency-free lexical retrieval (IDF-weighted overlap with light stemming)."""
from __future__ import annotations

import math
import re
from collections import Counter
from typing import Dict, Iterable, List, Set

from .models import Memory

_STOP = frozenset(
    "a an the and or but if of to in on at for with by from is are was were be been am do does did "
    "i me my we you your it its this that these those what which who whom where when why how can "
    "could should would will not no about tell".split()
)


def stem(w: str) -> str:
    if len(w) > 3:
        for suf in ("ing", "ed", "es", "s", "ly"):
            if w.endswith(suf) and len(w) - len(suf) >= 3:
                w = w[: -len(suf)]
                break
    if len(w) > 3 and w.endswith("e"):
        w = w[:-1]
    return w


def tokenize(text: str) -> List[str]:
    out: List[str] = []
    for w in re.findall(r"[a-z0-9]+(?:'[a-z]+)?", text.lower().replace("\u2019", "'")):
        if w.endswith("n't"):
            continue
        w = w.split("'")[0]
        if not w or w in _STOP:
            continue
        out.append(stem(w))
    return out


def index_text(m: Memory) -> str:
    parts = [m.content]
    for c in m.claims:
        parts.append(c.predicate.replace("_", " "))
        parts.append(c.value)
        if c.subject not in ("user", "world"):
            parts.append(c.subject)
    return " ".join(parts)


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


class Index:
    def __init__(self, memories: Iterable[Memory]):
        self.docs: Dict[str, Set[str]] = {m.id: set(tokenize(index_text(m))) for m in memories}
        self.n = len(self.docs)
        df: Counter = Counter()
        for toks in self.docs.values():
            df.update(toks)
        self.df = df

    def idf(self, t: str) -> float:
        d = self.df.get(t, 0)
        return math.log(1.0 + (self.n - d + 0.5) / (d + 0.5))

    def relevance(self, q_tokens: List[str], mid: str) -> float:
        if not q_tokens:
            return 0.0
        doc = self.docs[mid]
        total = sum(self.idf(t) for t in q_tokens)
        hit = sum(self.idf(t) for t in q_tokens if t in doc)
        return hit / total if total else 0.0

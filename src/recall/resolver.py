"""Decides who wins when two memories disagree.

Each memory gets a *credibility score* built from five signals:

    recency        newer statements beat older ones (half-life: 45 days)
    confidence     how sure the memory was when stored
    trust          how reliable its source is (user > tool > assistant > web > hearsay)
    reinforcement  how often it has been successfully recalled
    retention      how strong it still is on the forgetting curve

plus bonuses for explicit corrections ("actually", "no longer") and for a later
statement from the same source. The margin between the two scores decides:

    margin >  +dispute_margin  -> the new memory supersedes the old one
    margin <  -dispute_margin  -> the new memory is rejected (the old one stays)
    otherwise                  -> both are marked DISPUTED until evidence arrives
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict

from .clock import DAY
from .config import Config
from .decay import retention
from .models import Memory

SUPERSEDE_OLD = "supersede_old"
REJECT_NEW = "reject_new"
DISPUTE = "dispute"
#: Not produced by the scores themselves: the engine's policy turns a user's change of
#: mind into a question ("has that changed?") instead of deciding on their behalf.
ASK = "ask"


@dataclass
class Resolution:
    action: str
    new_id: str
    old_id: str
    new_score: float
    old_score: float
    margin: float
    reason: str


class Resolver:
    def __init__(self, cfg: Config):
        self.cfg = cfg

    def components(self, m: Memory, now: float) -> Dict[str, float]:
        cfg, w = self.cfg, self.cfg.weights
        age_days = max(0.0, now - m.created_at) / DAY
        recency = 0.5 ** (age_days / cfg.recency_half_life_days)
        reinforcement = 1.0 - 1.0 / (1.0 + 0.5 * m.access_count)
        return {
            "recency": w.recency * recency,
            "confidence": w.confidence * m.confidence,
            "source trust": w.trust * m.source_trust,
            "reinforcement": w.reinforcement * reinforcement,
            "retention": w.retention * retention(m, now, cfg),
            "explicit correction": cfg.correction_bonus if m.correction_cue else 0.0,
        }

    def score(self, m: Memory, now: float) -> float:
        return sum(self.components(m, now).values())

    def resolve(self, new: Memory, old: Memory, now: float) -> Resolution:
        cn, co = self.components(new, now), self.components(old, now)
        if new.source == old.source and new.created_at >= old.created_at:
            cn["same-source follow-up"] = self.cfg.same_source_bonus
        ns, os_ = sum(cn.values()), sum(co.values())
        margin = ns - os_
        m = self.cfg.dispute_margin

        if margin > m:
            action, winner, w_c, l_c = SUPERSEDE_OLD, "new", cn, co
        elif margin < -m:
            action, winner, w_c, l_c = REJECT_NEW, "old", co, cn
        else:
            action, winner, w_c, l_c = DISPUTE, None, cn, co

        if winner:
            diffs = sorted(
                ((k, w_c.get(k, 0.0) - l_c.get(k, 0.0)) for k in set(w_c) | set(l_c)),
                key=lambda kv: -kv[1],
            )
            top = [k for k, d in diffs[:2] if d > 0.005]
            why = ("won on " + " + ".join(top)) if top else "won narrowly"
            reason = f"{winner} memory {why} ({ns:.2f} vs {os_:.2f})"
        else:
            reason = f"too close to call ({ns:.2f} vs {os_:.2f}); needs more evidence"
        return Resolution(action, new.id, old.id, round(ns, 3), round(os_, 3), round(margin, 3), reason)

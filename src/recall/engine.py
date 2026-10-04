"""The Recall engine: ingest -> detect contradictions -> resolve (or ask) -> age -> serve."""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Callable, Iterable, List, Optional, Sequence

from .claims import (describe_claim, extract_claims, has_correction_cue, infer_kind, render_claim,
                     split_sentences, assistant_sentences)
from .clock import DAY, Clock, SystemClock, fmt_date
from .config import Config
from .contradiction import Contradiction, Detector, NegationDetector, StructuredDetector, values_agree
from .decay import initial_half_life, reinforced_half_life, retention, status_from_retention
from .models import Claim, Kind, Memory, Status
from .resolver import ASK, DISPUTE, REJECT_NEW, SUPERSEDE_OLD, Resolution, Resolver
from .retrieval import Index, estimate_tokens, tokenize
from .store import Store

_LIVE = (Status.ACTIVE, Status.DORMANT, Status.DISPUTED)
_OPEN = _LIVE + (Status.PENDING,)


@dataclass
class Question:
    """Something Recall wants the user to confirm before it changes what it believes."""

    id: str                      # the id of the PENDING memory; pass it to Recall.answer()
    text: str                    # "You said before that you live in Berlin (2025-05-06). Has that changed?"
    new: Memory                  # the statement waiting for a yes
    old: List[Memory]            # the beliefs it would replace

    def __str__(self) -> str:
        return self.text


@dataclass
class AddResult:
    memory: Memory
    contradictions: List[Contradiction] = field(default_factory=list)
    resolutions: List[Resolution] = field(default_factory=list)
    merged: bool = False   # True if this repeated an existing memory (which was reinforced)
    parts: List["AddResult"] = field(default_factory=list)  # set when a compound statement was split
    questions: List[Question] = field(default_factory=list)  # "has that changed?" prompts to show the user

    @property
    def rejected(self) -> bool:
        return self.memory.status == Status.SUPERSEDED

    @property
    def superseded(self) -> List[str]:
        return [r.old_id for r in self.resolutions if r.action == SUPERSEDE_OLD]

    @property
    def disputed(self) -> bool:
        return self.memory.status == Status.DISPUTED

    @property
    def pending(self) -> bool:
        return self.memory.status == Status.PENDING

    @property
    def question(self) -> Optional[Question]:
        return self.questions[0] if self.questions else None


@dataclass
class Conflict:
    """A statement (usually from the assistant) that contradicts something already on record."""

    kind: str          # "self": the assistant contradicted itself | "user": it contradicted the user
                       # "memory": it contradicted another source (tool, document, web...)
    statement: str     # what was just said
    earlier: Memory    # what it contradicts
    reason: str

    def message(self) -> str:
        when = fmt_date(self.earlier.created_at)
        if self.kind == "self":
            return (f'Earlier ({when}) you said "{_said(self.earlier)}", but just now you said '
                    f'"{self.statement}". Those contradict each other.')
        if self.kind == "user":
            return f'You said "{self.statement}", but on {when} the user told you: "{_said(self.earlier)}".'
        return (f'You said "{self.statement}", but Recall has "{_said(self.earlier)}" '
                f"(from {self.earlier.source}, {when}).")


@dataclass
class CheckResult:
    """What :meth:`Recall.check` / :meth:`Recall.observe` found in a piece of assistant text."""

    conflicts: List[Conflict] = field(default_factory=list)
    stored: List[Memory] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.conflicts

    @property
    def self_contradictions(self) -> List[Conflict]:
        return [c for c in self.conflicts if c.kind == "self"]

    def message(self) -> str:
        """A short note to hand back to the model so it can fix its answer."""
        if self.ok:
            return ""
        lines = [f"Recall found {len(self.conflicts)} contradiction(s) in your last reply:"]
        lines += [f"- {c.message()}" for c in self.conflicts]
        tips = []
        if any(c.kind == "self" for c in self.conflicts):
            tips.append("Tell the user which statement is right. If the new one is a correction, "
                        "say so plainly (\"Correction: ...\") so it replaces the old one.")
        if any(c.kind == "user" for c in self.conflicts):
            tips.append("Trust what the user told you unless they say it has changed.")
        return "\n".join(lines + tips)

    def __bool__(self) -> bool:
        return not self.ok


def _said(m: Memory) -> str:
    return str(m.metadata.get("source_text") or m.content).strip().rstrip(".")


@dataclass
class Hit:
    memory: Memory
    relevance: float
    retention: float
    score: float
    status: Status


@dataclass
class ContextPack:
    """What the model should currently 'know', packed under a token budget."""

    items: List[Hit]
    dropped: int
    tokens: int
    query: Optional[str] = None
    questions: List[Question] = field(default_factory=list)
    notices: List[str] = field(default_factory=list)

    def to_prompt(self, header: str = "What I currently know about the user") -> str:
        lines = [f"## {header}"] if header else []
        challenged = {oid for q in self.questions for oid in q.new.pending_against}
        for h in self.items:
            m = h.memory
            note = ""
            if m.id in challenged:
                note = "  (may have changed: see the question below)"
            elif h.status == Status.DISPUTED:
                note = "  (unverified: conflicting evidence)"
            elif h.status == Status.DORMANT:
                note = "  (faded)"
            lines.append(f"- {m.content.strip()}  [as of {fmt_date(m.created_at)}]{note}")
        if self.questions:
            lines.append("")
            lines.append("## Ask the user before relying on this")
            lines += [f"- {q.text}" for q in self.questions]
        if self.notices:
            lines.append("")
            lines.append("## Heads-up from Recall")
            lines += [f"- {n}" for n in self.notices]
        return "\n".join(lines)

    def __iter__(self):
        return iter(self.items)

    def __len__(self) -> int:
        return len(self.items)


@dataclass
class SweepReport:
    demoted: List[str] = field(default_factory=list)       # ACTIVE -> DORMANT
    forgotten: List[str] = field(default_factory=list)     # decayed away
    expired: List[str] = field(default_factory=list)       # old superseded -> forgotten
    resolved: List[str] = field(default_factory=list)      # disputes settled
    answered: List[str] = field(default_factory=list)      # unanswered questions settled by default
    total: int = 0

    def __str__(self) -> str:
        extra = f", {len(self.answered)} questions timed out" if self.answered else ""
        return (f"sweep: {self.total} memories | {len(self.demoted)} faded, "
                f"{len(self.forgotten)} forgotten, {len(self.expired)} expired, "
                f"{len(self.resolved)} disputes settled{extra}")


class Recall:
    """An AI memory that ages information, detects contradictions, and curates what stays active."""

    def __init__(
        self,
        store: Optional[Store] = None,
        *,
        clock: Optional[Clock] = None,
        config: Optional[Config] = None,
        detectors: Optional[Sequence[Detector]] = None,
        extractor: Optional[Callable[..., List[Claim]]] = None,
        on_event: Optional[Callable[[str, Memory, str], None]] = None,
        relevance_fn: Optional[Callable[[str, Memory], float]] = None,
    ):
        self.store = store if store is not None else Store()
        self.clock = clock or SystemClock()
        self.config = config or Config()
        self.extractor = extractor or extract_claims
        self.detectors: List[Detector] = list(detectors) if detectors is not None else [
            StructuredDetector(), NegationDetector(),
        ]
        self.resolver = Resolver(self.config)
        self.on_event = on_event
        #: Optional ``(query, memory) -> 0..1`` scorer. Plug in embeddings / a reranker here;
        #: the built-in default is dependency-free lexical IDF overlap.
        self.relevance_fn = relevance_fn

    # ------------------------------------------------------------------ add
    def add(
        self,
        content: str,
        *,
        kind: Optional[Kind] = None,
        importance: float = 0.5,
        confidence: float = 0.8,
        source: str = "user",
        source_trust: Optional[float] = None,
        pinned: bool = False,
        claims: Optional[List[Claim]] = None,
        tags: Iterable[str] = (),
        metadata: Optional[dict] = None,
        subject: str = "user",
        correction: Optional[bool] = None,
    ) -> AddResult:
        """Store a statement. ``correction`` forces (or disables) explicit-correction handling;
        by default it is detected from the wording ("actually", "I moved", "I was wrong"...)."""
        text = content.strip()
        if not text:
            raise ValueError("memory content is empty")
        now = self.clock.now()
        cl = list(claims) if claims is not None else self._extract(text, subject, source)
        if claims is None and len(cl) > 1:
            return self._add_compound(text, cl, kind=kind, importance=importance,
                                      confidence=confidence, source=source,
                                      source_trust=source_trust, pinned=pinned, tags=tags,
                                      metadata=metadata,
                                      correction=has_correction_cue(text) if correction is None else correction)
        kind = kind or infer_kind(text, cl)
        trust = source_trust if source_trust is not None else self.config.source_trust.get(
            source, self.config.default_source_trust)
        cue = has_correction_cue(text) if correction is None else correction
        half_life = initial_half_life(kind, importance, self.config)
        if source == "assistant":
            half_life = min(half_life, self.config.assistant_half_life_days)

        new = Memory(
            content=text, kind=kind, claims=cl, confidence=confidence, importance=importance,
            source=source, source_trust=trust, correction_cue=cue,
            pinned=pinned, tags=list(tags), metadata=dict(metadata or {}),
            created_at=now, last_reinforced=now, last_accessed=now,
            half_life_days=half_life, status=Status.ACTIVE, status_changed_at=now,
        )

        dup = self._find_duplicate(new, now)
        if dup is not None:
            if source == "assistant":
                # The assistant repeating something isn't new evidence, but a repeat phrased as a
                # correction ("Correction: it's 8080") settles a dispute it started.
                if cue and dup.status == Status.DISPUTED:
                    self.resolve_dispute(dup.id, why="the assistant confirmed this version")
                return AddResult(dup, merged=True)
            dup.confidence = min(1.0, dup.confidence + (1.0 - dup.confidence) * 0.3)
            self._reinforce(dup, now, "confirmed again by a repeated statement")
            self.store.put(dup)
            self.store.flush()
            return AddResult(dup, merged=True)

        new.log(now, "created", f"{kind.value}, half-life {new.half_life_days:.0f}d, "
                                f"source={source} (trust {trust:.2f})")
        contradictions = self._detect(new, now)
        self.store.put(new)
        resolutions, questions = self._resolve_all(new, contradictions, now)
        self.store.flush()
        self._emit("added", new, new.content)
        return AddResult(new, contradictions, resolutions, questions=questions)

    def _extract(self, text: str, subject: str, source: str) -> List[Claim]:
        if source != "assistant":
            return self.extractor(text, subject=subject)
        try:
            return self.extractor(text, subject=subject, speaker="assistant")
        except TypeError:  # a custom extractor that doesn't know about speakers
            return self.extractor(text, subject=subject)

    def _add_compound(self, text: str, cl: List[Claim], **kw) -> AddResult:
        """Split 'I work at X and love Y' into atomic memories so each can age and conflict alone."""
        parts: List[AddResult] = []
        for c in cl:
            md = dict(kw.get("metadata") or {})
            md["source_text"] = text
            parts.append(self.add(render_claim(c), claims=[c], **{**kw, "metadata": md}))
        return AddResult(
            memory=parts[0].memory,
            contradictions=[x for p in parts for x in p.contradictions],
            resolutions=[x for p in parts for x in p.resolutions],
            merged=all(p.merged for p in parts),
            parts=parts,
            questions=[q for p in parts for q in p.questions],
        )

    # ----------------------------------------------------- questions (ask)
    def questions(self) -> List[Question]:
        """Open "has that changed?" questions, oldest first."""
        out = []
        for m in sorted(self.store.all(), key=lambda m: m.created_at):
            if m.status == Status.PENDING:
                out.append(self._question(m))
        return out

    def answer(self, question_id: str, yes: bool = True) -> Memory:
        """Settle a question. ``yes``: the new statement replaces the old belief.
        ``no``: the old belief stands and the new statement is set aside."""
        return self._settle(self._require(question_id), yes, self.clock.now(),
                            "the user confirmed it changed" if yes else "the user said it hasn't changed")

    def _question(self, m: Memory) -> Question:
        olds = [o for o in (self.store.get(i) for i in m.pending_against) if o is not None]
        return Question(m.id, m.question or "", m, olds)

    def _ask(self, new: Memory, olds: List[Memory], now: float) -> Question:
        o = olds[0]
        when = fmt_date(o.created_at)
        if o.claims and o.claims[0].subject == "user":   # "you live in Berlin" reads better than a quote
            said = describe_claim(o.claims[0])
            text = (f"You said before that {said} ({when}). Has that changed?" if o.source == "user" else
                    f"I had it on record (from {o.source}, {when}) that {said}. Has that changed?")
        else:
            text = f'You said before: "{_said(o)}" ({when}). Has that changed?'
        new.pending_against = [x.id for x in olds]
        new.question = text
        self._set_status(new, Status.PENDING, now, "conflicts with what the user said before; asking first")
        new.log(now, "asked", text)
        for x in olds:
            x.log(now, "challenged", f"{new.id} says otherwise; waiting for the user to confirm")
            self.store.put(x)
        self.store.put(new)
        return Question(new.id, text, new, olds)

    def _settle(self, m: Memory, yes: bool, now: float, why: str) -> Memory:
        if m.status != Status.PENDING:
            raise ValueError(f"{m.id} has no open question")
        olds = [o for o in (self.store.get(i) for i in m.pending_against) if o is not None]
        m.pending_against, m.question = [], None
        if yes:
            self._set_status(m, Status.ACTIVE, now, why)
            m.confidence = max(m.confidence, 0.9)
            for old in olds:
                if old.status in _LIVE:
                    self._set_status(old, Status.SUPERSEDED, now, f"replaced by {m.id}: {why}")
                    old.superseded_by = m.id
                    if old.id not in m.supersedes:
                        m.supersedes.append(old.id)
                    m.log(now, "supersedes", f"{old.id}: {why}")
                    for pid in list(old.disputes_with):
                        self._unlink_dispute(old, pid, now)
                    self.store.put(old)
        else:
            self._set_status(m, Status.SUPERSEDED, now, why)
            m.superseded_by = olds[0].id if olds else None
            for old in olds:
                old.confidence = min(1.0, old.confidence + (1.0 - old.confidence) * 0.3)
                old.log(now, "confirmed", f"{why}; {m.id} set aside")
                self.store.put(old)
        self.store.put(m)
        self.store.flush()
        self._emit("answered", m, why)
        return m

    # ------------------------------------------- assistant self-consistency
    def check(self, text: str, *, speaker: str = "assistant") -> CheckResult:
        """Dry run: does this text contradict what's on record? Nothing is stored.

        Use it on a draft reply before sending it, or let a stop hook call it."""
        return self._review(text, speaker, store=False)

    def observe(self, text: str, *, speaker: str = "assistant") -> CheckResult:
        """Check an assistant reply *and* remember its claims, so that the next reply can be
        checked against this one. That is how "you said 8080 an hour ago, now you say 3000"
        gets caught.

        The assistant's claims about the *user* are only checked, never stored: a model
        guessing "you live in Toronto" must not become a memory."""
        return self._review(text, speaker, store=True)

    def _review(self, text: str, speaker: str, store: bool) -> CheckResult:
        now = self.clock.now()
        result = CheckResult()
        sentences = assistant_sentences(text) if speaker == "assistant" else split_sentences(text)
        for sentence in sentences:
            claims = self._extract(sentence, "user", speaker)
            if not claims:
                continue
            cue = has_correction_cue(sentence)
            for claim in claims:
                if store and claim.subject != "user":
                    res = self.add(render_claim(claim), claims=[claim], source=speaker, confidence=0.7,
                                   importance=0.3, correction=cue, metadata={"source_text": sentence[:300]})
                    if not res.merged:
                        result.stored.append(res.memory)
                    flagged = {r.old_id for r in res.resolutions if r.action in (DISPUTE, REJECT_NEW)}
                    for c in res.contradictions:
                        if c.old_id in flagged:
                            self._conflict(result, sentence, self.store.get(c.old_id), c.reason, speaker)
                    continue
                probe = Memory(content=sentence, claims=[claim], source=speaker, created_at=now,
                               last_reinforced=now, status_changed_at=now)
                for c in self._detect(probe, now):
                    old = self.store.get(c.old_id)
                    if cue and old is not None and old.source == speaker:
                        continue  # an announced correction of itself is not a contradiction
                    self._conflict(result, sentence, old, c.reason, speaker)
        return result

    @staticmethod
    def _conflict(result: CheckResult, sentence: str, old: Optional[Memory], reason: str,
                  speaker: str) -> None:
        if old is None or any(x.earlier.id == old.id for x in result.conflicts):
            return
        kind = "self" if old.source == speaker else ("user" if old.source == "user" else "memory")
        result.conflicts.append(Conflict(kind, sentence.strip().rstrip("."), old, reason))

    # -------------------------------------------------------------- notices
    def notify(self, text: str, kind: str = "info") -> None:
        """Queue a heads-up for the model. It appears in the next active_context()."""
        notes = self.store.meta.setdefault("notices", [])
        if not any(n.get("text") == text for n in notes):
            notes.append({"t": self.clock.now(), "kind": kind, "text": text})
            self.store.flush()

    def notices(self) -> List[str]:
        return [n["text"] for n in self.store.meta.get("notices", [])]

    def clear_notices(self) -> None:
        if self.store.meta.get("notices"):
            self.store.meta["notices"] = []
            self.store.flush()

    # -------------------------------------------------------------- recall
    def recall(
        self,
        query: str,
        *,
        limit: int = 5,
        token_budget: Optional[int] = None,
        reinforce: Optional[bool] = None,
        min_relevance: Optional[float] = None,
        include_faded: bool = True,
    ) -> List[Hit]:
        """Retrieve the most relevant live memories. Retrieval *is* rehearsal: hits are reinforced."""
        now = self.clock.now()
        hits = self._rank(query, now, include_faded, min_relevance)
        hits = hits[:limit]
        if token_budget is not None:
            hits = self._fit(hits, token_budget)
        do_reinforce = self.config.reinforce_on_recall if reinforce is None else reinforce
        if do_reinforce:
            for h in hits:
                if h.status != Status.DISPUTED:
                    self._reinforce(h.memory, now, f'recalled for "{query}"')
                    self.store.put(h.memory)
            self.store.flush()
        return hits

    def active_context(
        self,
        query: Optional[str] = None,
        *,
        token_budget: int = 400,
        limit: int = 12,
        reinforce: bool = False,
        include_questions: bool = True,
        include_notices: bool = True,
    ) -> ContextPack:
        """The working set to inject into a prompt: current, trusted, relevant, and within budget,
        plus any open questions for the user and heads-ups for the model."""
        now = self.clock.now()
        if query:
            ranked = self._rank(query, now, include_faded=False, min_relevance=None)
        else:
            ranked = []
            for m in self.store.all():
                st = self._live_status(m, now)
                if st in (Status.ACTIVE, Status.DISPUTED) and self._servable(m):
                    r = retention(m, now, self.config)
                    score = (0.4 + 0.6 * m.importance) * r * (0.5 + 0.5 * m.confidence)
                    ranked.append(Hit(m, 1.0, r, score * (0.8 if st == Status.DISPUTED else 1.0), st))
            ranked.sort(key=lambda h: -h.score)
        total = len(ranked)
        chosen = self._fit(ranked[:limit], token_budget)
        if reinforce:
            for h in chosen:
                if h.status != Status.DISPUTED:
                    self._reinforce(h.memory, now, "served in context")
                    self.store.put(h.memory)
            self.store.flush()
        tokens = sum(estimate_tokens(h.memory.content) + 8 for h in chosen)
        return ContextPack(chosen, total - len(chosen), tokens, query,
                           questions=self.questions() if include_questions else [],
                           notices=self.notices() if include_notices else [])

    # --------------------------------------------------------- maintenance
    def sweep(self) -> SweepReport:
        """Age every memory: fade, forget, expire the superseded, settle disputes and stale questions."""
        now = self.clock.now()
        cfg = self.config
        rep = SweepReport(total=len(self.store))
        for m in self.store.all():
            if m.status == Status.PENDING:
                if now - m.status_changed_at > cfg.pending_ttl_days * DAY:
                    yes = cfg.pending_default != "no"
                    self._settle(m, yes, now, f"no answer after {cfg.pending_ttl_days:g} days; "
                                              f"{'kept the newer' if yes else 'kept the older'} statement")
                    rep.answered.append(m.id)
            elif m.status in (Status.ACTIVE, Status.DORMANT):
                new_status = Status.ACTIVE if m.pinned else status_from_retention(
                    retention(m, now, cfg), cfg)
                if new_status != m.status:
                    r = retention(m, now, cfg)
                    if new_status == Status.FORGOTTEN:
                        rep.forgotten.append(m.id)
                        self._set_status(m, Status.FORGOTTEN, now, f"retention fell to {r:.2f}")
                    elif new_status == Status.DORMANT:
                        rep.demoted.append(m.id)
                        self._set_status(m, Status.DORMANT, now, f"retention fell to {r:.2f}")
                    else:
                        self._set_status(m, Status.ACTIVE, now, "retention recovered")
            elif m.status == Status.SUPERSEDED:
                if now - m.status_changed_at > cfg.superseded_ttl_days * DAY:
                    rep.expired.append(m.id)
                    self._set_status(m, Status.FORGOTTEN, now, "superseded record expired")
        # settle disputes whose balance of evidence has shifted
        for m in self.store.all():
            if m.status != Status.DISPUTED:
                continue
            if not m.pinned and retention(m, now, cfg) < cfg.forget_threshold:
                rep.forgotten.append(m.id)
                self._set_status(m, Status.FORGOTTEN, now, "unresolved dispute decayed away")
                for pid in list(m.disputes_with):
                    self._unlink_dispute(m, pid, now)
                continue
            for pid in list(m.disputes_with):
                other = self.store.get(pid)
                if other is None or other.status != Status.DISPUTED:
                    self._unlink_dispute(m, pid, now)
                    continue
                if m.id > pid:
                    continue
                newer, older = (m, other) if m.created_at >= other.created_at else (other, m)
                res = self.resolver.resolve(newer, older, now)
                if res.action != DISPUTE and not (newer.source == older.source == "assistant"
                                                  and cfg.self_contradiction == "flag"):
                    self._apply(newer, older, res, now)
                    rep.resolved.append(f"{newer.id}/{older.id}")
        for m in self.store.all():
            self.store.put(m)
        self.store.flush()
        return rep

    def purge(self) -> int:
        """Permanently delete FORGOTTEN tombstones. Returns how many were removed."""
        gone = [m.id for m in self.store.all() if m.status == Status.FORGOTTEN]
        for mid in gone:
            self.store.delete(mid)
        self.store.flush()
        return len(gone)

    def reinforce(self, memory_id: str) -> Memory:
        m = self._require(memory_id)
        self._reinforce(m, self.clock.now(), "manually reinforced")
        self.store.put(m)
        self.store.flush()
        return m

    def pin(self, memory_id: str, pinned: bool = True) -> Memory:
        m = self._require(memory_id)
        m.pinned = pinned
        m.log(self.clock.now(), "pinned" if pinned else "unpinned")
        self.store.put(m)
        self.store.flush()
        return m

    def forget(self, memory_id: str, reason: str = "manual") -> Memory:
        m = self._require(memory_id)
        now = self.clock.now()
        self._set_status(m, Status.FORGOTTEN, now, reason)
        for pid in list(m.disputes_with):
            self._unlink_dispute(m, pid, now)
        m.pending_against, m.question = [], None
        self.store.put(m)
        self.store.flush()
        return m

    def resolve_dispute(self, winner_id: str, why: str = "won dispute (manual)") -> Memory:
        """Settle a dispute by hand: the winner stays, its rivals are superseded."""
        w = self._require(winner_id)
        now = self.clock.now()
        for pid in list(w.disputes_with):
            loser = self.store.get(pid)
            if loser is None:
                continue
            self._set_status(loser, Status.SUPERSEDED, now, f"dispute settled in favour of {w.id}")
            loser.superseded_by = w.id
            if loser.id not in w.supersedes:
                w.supersedes.append(loser.id)
            loser.disputes_with = []
            self.store.put(loser)
        w.disputes_with = []
        self._set_status(w, Status.ACTIVE, now, why)
        self.store.put(w)
        self.store.flush()
        return w

    # ------------------------------------------------------------- inspect
    def get(self, memory_id: str) -> Optional[Memory]:
        return self.store.get(memory_id)

    def memories(self, *statuses: Status) -> List[Memory]:
        now = self.clock.now()
        out = []
        for m in self.store.all():
            st = self._live_status(m, now)
            if not statuses or st in statuses:
                out.append(m)
        return sorted(out, key=lambda m: m.created_at)

    def retention_of(self, memory_id: str) -> float:
        return retention(self._require(memory_id), self.clock.now(), self.config)

    def explain(self, memory_id: str) -> str:
        """A full audit trail: why does this memory look the way it does?"""
        m = self._require(memory_id)
        now = self.clock.now()
        r = retention(m, now, self.config)
        lines = [
            f'{m.id}  "{m.content}"',
            f"  status={self._live_status(m, now).value}  kind={m.kind.value}  "
            f"retention={r:.2f}  half-life={m.half_life_days:.0f}d  recalled={m.access_count}x",
            f"  confidence={m.confidence:.2f}  source={m.source} (trust {m.source_trust:.2f})",
        ]
        for c in m.claims:
            lines.append(f"  claim: {c}")
        if m.superseded_by:
            lines.append(f"  superseded by {m.superseded_by}")
        if m.question:
            lines.append(f"  waiting on: {m.question}")
        lines.append("  history:")
        for ev in m.history:
            lines.append(f"    {fmt_date(ev['t'])}  {ev['event']:<12} {ev['detail']}")
        return "\n".join(lines)

    def stats(self) -> dict:
        now = self.clock.now()
        counts = {s.value: 0 for s in Status}
        for m in self.store.all():
            counts[self._live_status(m, now).value] += 1
        counts["total"] = len(self.store)
        return counts

    # ------------------------------------------------------------ internals
    def _require(self, mid: str) -> Memory:
        m = self.store.get(mid)
        if m is None:
            raise KeyError(f"no such memory: {mid}")
        return m

    def _emit(self, event: str, m: Memory, detail: str = "") -> None:
        if self.on_event:
            self.on_event(event, m, detail)

    def _servable(self, m: Memory) -> bool:
        return m.source != "assistant" or self.config.context_includes_assistant

    def _live_status(self, m: Memory, now: float) -> Status:
        if m.status in (Status.SUPERSEDED, Status.FORGOTTEN, Status.DISPUTED, Status.PENDING):
            return m.status
        if m.pinned:
            return Status.ACTIVE
        return status_from_retention(retention(m, now, self.config), self.config)

    def _set_status(self, m: Memory, status: Status, now: float, why: str) -> None:
        if m.status == status:
            return
        old = m.status
        m.status = status
        m.status_changed_at = now
        m.log(now, status.value, f"{old.value} -> {status.value}: {why}")
        self._emit(status.value, m, why)

    def _reinforce(self, m: Memory, now: float, why: str) -> None:
        was = self._live_status(m, now)
        m.half_life_days = reinforced_half_life(m, now, self.config)
        m.last_reinforced = now
        m.last_accessed = now
        m.access_count += 1
        m.log(now, "reinforced", f"{why}; half-life now {m.half_life_days:.0f}d")
        if was in (Status.DORMANT,) or m.status == Status.DORMANT:
            self._set_status(m, Status.ACTIVE, now, "revived by recall")

    def _detect(self, new: Memory, now: float) -> List[Contradiction]:
        candidates = [m for m in self.store.all()
                      if m.id != new.id and self._live_status(m, now) in _OPEN]
        found: List[Contradiction] = []
        seen = set()
        for det in self.detectors:
            for c in det.detect(new, candidates):
                if c.old_id not in seen:
                    seen.add(c.old_id)
                    found.append(c)
        return found

    def _find_duplicate(self, new: Memory, now: float) -> Optional[Memory]:
        for old in self.store.all():
            if self._live_status(old, now) not in _OPEN:
                continue
            if new.claims and old.claims:
                if all(any(a.key() == b.key() and a.polarity == b.polarity and
                           values_agree(a.value, b.value) for b in old.claims) for a in new.claims):
                    return old
            elif not new.claims and not old.claims and \
                    old.content.strip().lower() == new.content.strip().lower():
                return old
        return None

    def _policy(self, new: Memory, old: Memory, res: Resolution) -> Resolution:
        """Who-wins rules that sit on top of the credibility scores.

        * The user is the authority on what the user said. A user statement is never
          silently rejected: an explicit correction wins outright; otherwise, if it
          contradicts what the user said earlier, Recall asks (or auto-accepts with
          ``confirm_changes="auto"``).
        * The assistant can never overwrite the user, and when it contradicts *itself*
          both statements are flagged instead of the newest one winning quietly.
        """
        cfg = self.config
        if new.source == "user":
            if new.correction_cue:
                if res.action != SUPERSEDE_OLD:
                    return replace(res, action=SUPERSEDE_OLD,
                                   reason=f"the user explicitly corrected it ({res.new_score:.2f} vs {res.old_score:.2f})")
                return res
            if old.source == "user" or res.action == REJECT_NEW:
                if cfg.confirm_changes == "auto":
                    return replace(res, action=SUPERSEDE_OLD,
                                   reason="auto-confirmed: the user's newest statement wins (confirm=auto)")
                return replace(res, action=ASK, reason="the user said otherwise before; asking whether it changed")
            return res
        if new.source == "assistant":
            if old.source == "user":
                if res.action != REJECT_NEW:
                    return replace(res, action=REJECT_NEW,
                                   reason="what the user said outranks what the assistant said")
                return res
            if old.source == "assistant":
                if new.correction_cue or cfg.self_contradiction == "newest":
                    return replace(res, action=SUPERSEDE_OLD,
                                   reason="the assistant corrected itself" if new.correction_cue else
                                   "newest assistant statement wins (self_contradiction=newest)")
                return replace(res, action=DISPUTE, reason="the assistant contradicted its own earlier statement")
        return res

    def _resolve_all(self, new: Memory, cs: List[Contradiction], now: float):
        if not cs:
            return [], []
        pairs = []
        for c in cs:
            old = self.store.get(c.old_id)
            if old is None:
                continue
            if old.status == Status.PENDING and old.source == new.source:
                # A newer statement replaces an older one that was still waiting for a yes.
                self._set_status(old, Status.SUPERSEDED, now,
                                 f"replaced by newer statement {new.id} before it was confirmed")
                old.superseded_by, old.pending_against, old.question = new.id, [], None
                self.store.put(old)
                continue
            pairs.append((c, old, self._policy(new, old, self.resolver.resolve(new, old, now))))
        # If any trusted incumbent beats the newcomer, the newcomer is quarantined.
        rejected = [r for _, _, r in pairs if r.action == REJECT_NEW]
        if rejected:
            self._apply(new, self.store.get(rejected[0].old_id), rejected[0], now)
            return [rejected[0]], []
        # If the user has to confirm, nothing changes until they answer.
        asks = [old for _, old, r in pairs if r.action == ASK]
        if asks:
            others = [old for _, old, r in pairs if r.action == SUPERSEDE_OLD and old not in asks]
            return [r for _, _, r in pairs], [self._ask(new, asks + others, now)]
        for c, old, r in pairs:
            self._apply(new, old, r, now, c)
        return [r for _, _, r in pairs], []

    def _apply(self, new: Memory, old: Memory, res: Resolution, now: float,
               c: Optional[Contradiction] = None) -> None:
        why = c.reason if c else res.reason
        if res.action == SUPERSEDE_OLD:
            self._set_status(old, Status.SUPERSEDED, now, f"replaced by {new.id}: {res.reason}")
            old.superseded_by = new.id
            if old.id not in new.supersedes:
                new.supersedes.append(old.id)
            new.log(now, "supersedes", f"{old.id}: {why}")
            for pid in list(old.disputes_with):
                self._unlink_dispute(old, pid, now)
            if new.status == Status.DISPUTED and not new.disputes_with:
                self._set_status(new, Status.ACTIVE, now, "dispute cleared")
        elif res.action == REJECT_NEW:
            self._set_status(new, Status.SUPERSEDED, now, f"rejected in favour of {old.id}: {res.reason}")
            new.superseded_by = old.id
            old.log(now, "defended", f"held against {new.id} ({res.reason})")
        else:
            for a, b in ((new, old), (old, new)):
                self._set_status(a, Status.DISPUTED, now, f"conflicts with {b.id}: {why}")
                if b.id not in a.disputes_with:
                    a.disputes_with.append(b.id)
        self.store.put(new)
        self.store.put(old)
        self._emit("resolved:" + res.action, new, res.reason)

    def _unlink_dispute(self, m: Memory, other_id: str, now: float) -> None:
        if other_id in m.disputes_with:
            m.disputes_with.remove(other_id)
        other = self.store.get(other_id)
        if other is not None and m.id in other.disputes_with:
            other.disputes_with.remove(m.id)
            if other.status == Status.DISPUTED and not other.disputes_with:
                self._set_status(other, Status.ACTIVE, now, "dispute cleared")
                self.store.put(other)
        if m.status == Status.DISPUTED and not m.disputes_with:
            self._set_status(m, Status.ACTIVE, now, "dispute cleared")

    def _rank(self, query: str, now: float, include_faded: bool,
              min_relevance: Optional[float]) -> List[Hit]:
        cfg = self.config
        min_rel = cfg.min_relevance if min_relevance is None else min_relevance
        allowed = (Status.ACTIVE, Status.DISPUTED) + ((Status.DORMANT,) if include_faded else ())
        cands = [(m, self._live_status(m, now)) for m in self.store.all() if self._servable(m)]
        cands = [(m, st) for m, st in cands if st in allowed]
        q = tokenize(query)
        if not cands or not q:
            return []
        idx = None if self.relevance_fn else Index(m for m, _ in cands)
        hits: List[Hit] = []
        for m, st in cands:
            if self.relevance_fn:
                rel = max(0.0, min(1.0, float(self.relevance_fn(query, m))))
            else:
                rel = idx.relevance(q, m.id)
            if rel < min_rel:
                continue
            r = retention(m, now, cfg)
            score = rel * (0.45 + 0.55 * r) * (0.5 + 0.5 * m.confidence)
            if st == Status.DISPUTED:
                score *= 0.8
            hits.append(Hit(m, rel, r, score, st))
        hits.sort(key=lambda h: -h.score)
        return hits

    @staticmethod
    def _fit(hits: List[Hit], budget: int) -> List[Hit]:
        out, used = [], 0
        for h in hits:
            cost = estimate_tokens(h.memory.content) + 8
            if used + cost > budget:
                continue
            out.append(h)
            used += cost
        return out

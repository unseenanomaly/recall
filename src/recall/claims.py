"""Lightweight, dependency-free claim extraction.

Turns natural statements into structured ``(subject, predicate, value)`` claims
so contradictions can be detected precisely. It is deliberately simple and
rule-based; plug in your own extractor (e.g. an LLM) via ``Recall(extractor=...)``.
"""
from __future__ import annotations

import re
from typing import List, Optional, Pattern, Tuple

from .models import Claim, Kind

_ARTICLES = re.compile(r"^(?:a|an|the|my|our)\s+", re.I)
_TRAIL = re.compile(r"\s+(?:now|these days|anymore|any more|again|too|lately|currently)$", re.I)
_LEAD = re.compile(r"^(?:actually|well|so|also|btw|oh|ok|okay|and|but|hey|um)[,\s]+", re.I)
_SPLIT = re.compile(  # "." only ends a clause before whitespace, so api.example.com and 2.5 survive
    r"\.+(?=\s|$)|[;!?\n]+|,\s*(?:and|but)\s+|\s+(?:and|but)\s+(?=(?:i|i'm|i've|my|work|live|am)\b)", re.I
)

_CORRECTION = re.compile(
    r"\b(actually|no longer|not anymore|anymore|any more|correction|changed my|instead|"
    r"switched|moved|relocated|i was wrong|i misspoke|my mistake|i stand corrected|to correct myself)\b",
    re.I,
)
_EPHEMERAL = re.compile(
    r"\b(today|tonight|tomorrow|this (?:morning|afternoon|evening|week|weekend)|next (?:week|weekend|monday|tuesday|wednesday|thursday|friday|saturday|sunday)|right now|remind me|todo|to-do)\b", re.I
)
_EVENT = re.compile(
    r"\b(yesterday|last (?:week|month|year)|met with|meeting with|went to|attended|visited|had a)\b", re.I
)
_PAST = re.compile(r"\b(used to|back then|previously|formerly)\b", re.I)


def _clean(v: str) -> str:
    v = v.strip().strip("\"'`").strip()
    v = _TRAIL.sub("", v)
    v = _ARTICLES.sub("", v)
    return re.sub(r"\s+", " ", v).strip(" .,:;!?")


_TAIL_CLAUSE = re.compile(r"\s*(?:[,;:(]|\s-\s|\s(?:so|because|which|where|since|although|though|but|until)\s).*$", re.I)


def _single_value(v: str) -> str:
    # "Toronto, so the 9am standup is early" -> "Toronto"
    return _clean(_TAIL_CLAUSE.sub("", v))


def _multi_values(v: str) -> List[str]:
    parts = re.split(r",|\band\b|\bor\b", v)
    return [x for x in (_clean(p) for p in parts) if x]


# (regex, predicate, single, polarity). First match per clause wins. Order matters.
_I = r"\bi(?:'m| am| have|'ve)?"
_PATTERNS: List[Tuple[Pattern[str], str, bool, bool]] = [
    (re.compile(r"\b(?:i|we)\s+(?:currently |now |still )?live in (?P<v>.+)", re.I), "lives_in", True, True),
    (re.compile(r"\bi(?:'m| am) (?:currently |now )?(?:living|based) in (?P<v>.+)", re.I), "lives_in", True, True),
    (re.compile(r"\b(?:i|we)(?:'ve| have|'m| am)?\s*(?:just |recently |now )?(?:moved|relocated|moving)\s+to (?P<v>.+)", re.I),
     "lives_in", True, True),
    (re.compile(r"\b(?:i\s+)?(?:currently |now )?work (?:at|for) (?P<v>.+)", re.I), "works_at", True, True),
    (re.compile(r"\bi(?:'m| am) (?:now )?(?:a |an )?(?P<v>vegetarian|vegan|pescatarian|gluten[- ]free)\b", re.I),
     "diet", True, True),
    (re.compile(r"\bi(?:'m| am) allergic to (?P<v>.+)", re.I), "allergic_to", False, True),
    (re.compile(r"\bi(?:'m| am) (?P<v>\d{1,3}) years old", re.I), "age", True, True),
    (re.compile(r"\bmy name is (?P<v>.+)", re.I), "name", True, True),
    (re.compile(r"\bi (?:really |do )?(?:don't|do not|dont) (?:like|enjoy|love|eat|drink|use) (?P<v>.+)", re.I),
     "likes", False, False),
    (re.compile(r"\bi (?:really )?(?:hate|dislike|can't stand|cannot stand|no longer (?:like|enjoy|love)) (?P<v>.+)", re.I),
     "likes", False, False),
    (re.compile(r"\bi (?:really )?(?:love|like|enjoy|adore|prefer) (?P<v>.+)", re.I), "likes", False, True),
    (re.compile(r"\bi (?:use|drive|ride) (?P<v>.+)", re.I), "uses", False, True),
]
_COPULA = r"(?P<verb>is|are|isn't|aren't|will be|won't be)"
_MY_X = re.compile(r"\bmy (?P<k>[a-z][a-z' ]{1,30}?) " + _COPULA + r" (?P<v>.+)", re.I)
_WORLD = re.compile(r"\b(?:the|our) (?P<k>[a-z][a-z ]{1,30}?) " + _COPULA + r" (?P<v>.+)", re.I)
_NOT_LEAD = re.compile(r"^(?:not|no longer)\s+", re.I)


def _polar(verb: str, value: str):
    """Lift negation out of the copula or the value: ("isn't", "x") / ("is", "not x") -> (False, "x")."""
    pol = not verb.lower().endswith("n't") and "won't" not in verb.lower()
    if _NOT_LEAD.match(value):
        value, pol = _NOT_LEAD.sub("", value), not pol
    return pol, value
_THIRD = re.compile(
    r"^(?P<s>[A-Z][a-z]+) (?:now |currently )?(?P<verb>lives in|works at|works for|moved to) (?P<v>.+)"
)
_NOT_NAMES = {"She", "He", "They", "It", "We", "The", "This", "That", "There", "Here", "My", "Our"}


def has_correction_cue(text: str) -> bool:
    return bool(_CORRECTION.search(text))


def _clauses(text: str) -> List[str]:
    text = text.replace("\u2019", "'")
    out = []
    for c in _SPLIT.split(text):
        c = c.strip()
        while True:
            n = _LEAD.sub("", c)
            if n == c:
                break
            c = n
        if re.match(r"^(work|live)s?\b", c, re.I):
            c = "I " + c
        if c:
            out.append(c)
    return out


# --------------------------------------------------------------- speakers
# The extractor reads text as if the *user* wrote it ("I live in X" is about the user).
# Assistant replies are read from the other side of the table: "you live in X" is a
# claim about the user, and the assistant's own "I ..." is not.

_FENCE = re.compile(r"```.*?(?:```|$)", re.S)
_SENTENCES = re.compile(r"(?<=[.!?])\s+|\n+")
_HEDGE = re.compile(
    r"\b(might|may|could|would|should|probably|possibly|perhaps|maybe|likely|unlikely|"
    r"seems?|appears?|i think|i believe|i guess|i assume|if|unless|assuming|suppose|"
    r"for example|for instance|e\.g|typically|usually|often|sometimes|generally|depending|"
    r"let's|let me|i'll|we'll|"
    # reported speech is not a new claim: "you said before that you live in X", "earlier I said..."
    r"you (?:said|told|mentioned|wrote|asked)|you'd said|as you said|according to|"
    r"i (?:said|mentioned|told|wrote)|used to)\b",
    re.I,
)
_SWAP = {
    "you're": "I'm", "you've": "I've", "you'll": "I'll", "you'd": "I'd", "you are": "I am",
    "you were": "I was", "yours": "mine", "yourself": "myself", "your": "my", "you": "I",
    "i'm": "you're", "i've": "you've", "i'll": "you'll", "i'd": "you'd", "i am": "you are",
    "i was": "you were", "myself": "yourself", "mine": "yours", "my": "your", "me": "you", "i": "you",
}
_SWAP_RX = re.compile(r"\b(" + "|".join(sorted(map(re.escape, _SWAP), key=len, reverse=True)) + r")\b", re.I)

#: "My X is Y" from a person is only a *personal* fact for these predicates. Everything
#: else ("my build is failing") is task chatter, not something to remember about them.
PERSONAL_PREDICATES = frozenset({
    "lives_in", "works_at", "diet", "allergic_to", "age", "name", "likes", "uses",
    "birthday", "timezone", "time_zone", "pronouns", "job", "role", "job_title", "title", "team",
    "company", "employer", "partner", "wife", "husband", "dog", "cat", "os", "operating_system",
    "editor", "shell", "language", "native_language", "email", "github", "github_username",
    "username", "nickname", "hometown", "city", "country",
})
_PERSONAL_PREFIX = ("favorite_", "favourite_", "preferred_")
_VAGUE_VALUE = re.compile(r"^(that|this|it|these|those|how|when|what|the way|your|you|to|because|which)\b", re.I)
#: Head nouns of "the X is Y" that describe the conversation, not the world.
_DISCOURSE = frozenset(
    "problem issue fix error bug solution answer reason goal idea result output change changes "
    "difference question point plan approach option step key trick catch thing best easiest "
    "simplest first next last main only same other rest good bad news truth case way part code "
    "file function test tests build command line example snippet method response message current "
    "new old following above below latter former culprit cause workaround benefit downside "
    "tradeoff takeaway summary short status state".split()
)


def is_personal(c: Claim) -> bool:
    """True for claims worth remembering about a person (where they live, what they like...)."""
    if c.predicate not in PERSONAL_PREDICATES and not c.predicate.startswith(_PERSONAL_PREFIX):
        return False
    return len(c.value.split()) <= 6 and not _VAGUE_VALUE.match(c.value)


def swap_perspective(text: str) -> str:
    """'you live in Oslo' <-> 'I live in Oslo'. Only used to read assistant text."""
    text = text.replace("’", "'")

    def rep(m: "re.Match[str]") -> str:
        out = _SWAP[m.group(0).lower()]
        if re.match(r"I\b", out):
            return out                                   # "I" is always capitalised
        before = text[:m.start()].rstrip()
        return out[:1].upper() + out[1:] if not before or before[-1] in ".!?:\n" else out
    return _SWAP_RX.sub(rep, text)


def split_sentences(text: str) -> List[str]:
    return [s.strip() for s in _SENTENCES.split(text) if s and s.strip()]


def assistant_sentences(text: str) -> List[str]:
    """Sentences of an assistant reply that make a flat assertion.

    Code blocks, questions, and hedged or conditional sentences ("this might...",
    "if the port is...") are dropped: they aren't claims anyone should be held to.
    """
    text = _FENCE.sub("\n", text.replace("’", "'")).replace("`", "").replace("**", "")
    out = []
    for s in split_sentences(text):
        s = s.strip(" \t-*>#|")
        if s and not s.endswith("?") and not _HEDGE.search(s):
            out.append(s)
    return out


def _assistant_ok(c: Claim) -> bool:
    if c.subject == "user":
        return is_personal(c)
    head = c.predicate.split("_")[-1]
    if head in _DISCOURSE or c.predicate in _DISCOURSE:
        return False
    return len(c.value.split()) <= 6 and not _VAGUE_VALUE.match(c.value)


def extract_claims(text: str, subject: str = "user", speaker: str = "user") -> List[Claim]:
    """Extract structured claims from free text. Returns ``[]`` if nothing is recognised.

    ``speaker="assistant"`` reads the text from the assistant's side: "you live in X"
    becomes a claim about the user, and hedged or conversational sentences are ignored.
    """
    if speaker == "assistant":
        text = ". ".join(swap_perspective(s) for s in assistant_sentences(text))
        return [c for c in extract_claims(text, subject) if _assistant_ok(c)]
    claims: List[Claim] = []
    for clause in _clauses(text):
        if _PAST.search(clause):
            continue  # "I used to live in X" is history, not a current claim
        m3 = _THIRD.match(clause)
        if m3 and m3.group("s") not in _NOT_NAMES:
            verb = m3.group("verb")
            pred = "lives_in" if verb in ("lives in", "moved to") else "works_at"
            val = _single_value(m3.group("v"))
            if val:
                claims.append(Claim(m3.group("s").lower(), pred, val, True, True))
            continue

        matched = False
        for rx, pred, single, polarity in _PATTERNS:
            m = rx.search(clause)
            if not m:
                continue
            matched = True
            if single:
                v = _single_value(m.group("v"))
                if v:
                    claims.append(Claim(subject, pred, v, polarity, True))
            else:
                for v in _multi_values(m.group("v")):
                    claims.append(Claim(subject, pred, v, polarity, False))
            break
        if matched:
            continue

        m = _MY_X.search(clause)
        if m and len(m.group("k").split()) <= 4:
            pred = re.sub(r"\s+", "_", m.group("k").strip().lower())
            pol, raw = _polar(m.group("verb"), m.group("v"))
            v = _single_value(raw)
            if v:
                claims.append(Claim(subject, pred, v, pol, True))
            continue
        m = _WORLD.search(clause)
        if m and len(m.group("k").split()) <= 4:
            pred = re.sub(r"\s+", "_", m.group("k").strip().lower())
            pol, raw = _polar(m.group("verb"), m.group("v"))
            v = _single_value(raw)
            if v:
                claims.append(Claim("world", pred, v, pol, True))

    seen = set()
    unique: List[Claim] = []
    for c in claims:
        k = (c.subject, c.predicate, c.value.lower(), c.polarity)
        if k not in seen:
            seen.add(k)
            unique.append(c)
    return unique


_IDENTITY = {"lives_in", "name", "age"}
_FACT = {"works_at", "diet", "allergic_to"}


def infer_kind(text: str, claims: Optional[List[Claim]] = None) -> Kind:
    if _EPHEMERAL.search(text):
        return Kind.EPHEMERAL
    if claims:
        p = claims[0].predicate
        if p in _IDENTITY:
            return Kind.IDENTITY
        if p in _FACT:
            return Kind.FACT
        if p in ("likes", "uses") or p.startswith("favorite") or p.startswith("favourite"):
            return Kind.PREFERENCE
        return Kind.FACT
    if _EVENT.search(text):
        return Kind.EVENT
    return Kind.FACT


_TEMPLATES = {
    "lives_in": "Lives in {v}",
    "works_at": "Works at {v}",
    "diet": "Diet: {v}",
    "allergic_to": "Allergic to {v}",
    "age": "Is {v} years old",
    "name": "Name is {v}",
    "uses": "Uses {v}",
}


def render_claim(c: Claim) -> str:
    """Canonical one-line rendering of a claim (used when a compound statement is split)."""
    who = "" if c.subject in ("user", "world") else c.subject.capitalize() + ": "
    if c.predicate == "likes":
        text = ("Likes " if c.polarity else "Does not like ") + c.value
    elif c.predicate in _TEMPLATES:
        text = _TEMPLATES[c.predicate].format(v=c.value)
    else:
        pred = c.predicate.replace("_", " ")
        text = f"{pred[:1].upper() + pred[1:]} is {c.value}"
        if c.subject == "world":
            text = f"The {pred} is {c.value}"
    return who + text


_YOU = {
    "lives_in": "you live in {v}",
    "works_at": "you work at {v}",
    "diet": "you're {v}",
    "allergic_to": "you're allergic to {v}",
    "age": "you're {v} years old",
    "name": "your name is {v}",
    "uses": "you use {v}",
}
_THEY = {"lives_in": "{s} lives in {v}", "works_at": "{s} works at {v}"}


def describe_claim(c: Claim) -> str:
    """A claim the way you'd say it back to the user: 'you live in Berlin'."""
    if c.subject == "user":
        if c.predicate == "likes":
            return ("you like " if c.polarity else "you don't like ") + c.value
        if c.predicate in _YOU and c.polarity:
            return _YOU[c.predicate].format(v=c.value)
        pred = c.predicate.replace("_", " ")
        return f"your {pred} {'is' if c.polarity else 'is not'} {c.value}"
    if c.subject == "world":
        pred = c.predicate.replace("_", " ")
        return f"the {pred} {'is' if c.polarity else 'is not'} {c.value}"
    who = c.subject.capitalize()
    if c.predicate in _THEY and c.polarity:
        return _THEY[c.predicate].format(s=who, v=c.value)
    return f"{who}'s {c.predicate.replace('_', ' ')} {'is' if c.polarity else 'is not'} {c.value}"

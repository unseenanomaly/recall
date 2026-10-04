"""Recall: an AI memory that ages information, detects contradictions,
and decides what knowledge stays active."""
from .claims import describe_claim, extract_claims, has_correction_cue, infer_kind, render_claim
from .clock import Clock, ManualClock, SystemClock
from .config import Config, Weights
from .contradiction import (Contradiction, LLMJudgeDetector, NegationDetector,
                            StructuredDetector, values_agree)
from .engine import AddResult, CheckResult, Conflict, ContextPack, Hit, Question, Recall, SweepReport
from .models import Claim, Kind, Memory, Status
from .resolver import Resolution, Resolver
from .store import FileLock, InMemoryStore, JSONStore, Store

__version__ = "0.2.0"

__all__ = [
    "Recall", "AddResult", "Hit", "ContextPack", "SweepReport", "Question", "Conflict", "CheckResult",
    "Memory", "Claim", "Kind", "Status",
    "Config", "Weights",
    "Clock", "SystemClock", "ManualClock",
    "Store", "InMemoryStore", "JSONStore", "FileLock",
    "Contradiction", "StructuredDetector", "NegationDetector", "LLMJudgeDetector", "values_agree",
    "Resolver", "Resolution",
    "extract_claims", "infer_kind", "has_correction_cue", "describe_claim", "render_claim",
    "__version__",
]

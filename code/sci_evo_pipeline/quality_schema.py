"""Typed schema helpers for quality-first Sci-Evo runs."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


SCHEMA_VERSION = "quality_v16_1"

REVIEWER_ROLES = [
    "paper_cartographer",
    "trajectory_judge",
    "evidence_auditor",
    "red_team",
    "repair_planner",
]

DIMENSIONS = [
    "paper_storyline_fidelity",
    "mainline_completeness",
    "step_factuality",
    "evidence_grounding",
    "trajectory_coherence",
    "sci_evo_value",
]


@dataclass
class EvidenceSpan:
    span_id: str
    section: str
    text: str
    char_start: int
    char_end: int
    sha256: str
    numeric_tokens: list[str] = field(default_factory=list)
    mutation_tokens: list[str] = field(default_factory=list)
    method_tokens: list[str] = field(default_factory=list)


@dataclass
class QuoteCheck:
    step_index: int
    evidence_index: int
    section: str
    quote: str
    exact_match: bool
    normalized_match: bool
    match_count: int
    warning: str = ""


@dataclass
class ReviewBlocker:
    type: str
    severity: str
    affected_steps: list[int] = field(default_factory=list)
    paper_basis: str = ""
    problem: str = ""
    code_fix_hint: str = ""


@dataclass
class RepairAction:
    priority: str
    target: str
    description: str
    code_fix_hint: str = ""
    action_type: str = "manual_patch"


@dataclass
class ReviewerVerdict:
    reviewer_role: str
    doc_no: str
    case_id: str
    verdict: str
    confidence: float
    dimension_scores: dict[str, float]
    blockers: list[ReviewBlocker] = field(default_factory=list)
    repairs: list[RepairAction] = field(default_factory=list)
    must_keep: list[str] = field(default_factory=list)
    uncertainties: list[str] = field(default_factory=list)
    summary: str = ""


@dataclass
class ArbiterDecision:
    doc_no: str
    case_id: str
    candidate_id: str
    decision: str
    confidence: float
    reasons: list[str]
    reviewer_count: int
    blocker_count: int
    repair_count: int
    score_mean: float
    score_min: float


def as_jsonable(value: Any) -> Any:
    if hasattr(value, "__dataclass_fields__"):
        return asdict(value)
    if isinstance(value, list):
        return [as_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): as_jsonable(item) for key, item in value.items()}
    return value

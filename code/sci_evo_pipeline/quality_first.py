"""Quality-first AI review protocol utilities.

This module supports the V16 direction: use many AI reviewers for local
quality work, then let code arbitrate structured verdicts. It is not a
large-scale production generator.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any


REVIEWER_ROLES = [
    "paper_cartographer",
    "trajectory_judge",
    "evidence_auditor",
    "red_team",
    "repair_planner",
]

ROLE_DESCRIPTIONS = {
    "paper_cartographer": "Read the paper independently and reconstruct the true research storyline without looking at the candidate answer first.",
    "trajectory_judge": "Compare the candidate trajectory to the reconstructed storyline and score mainline completeness and coherence.",
    "evidence_auditor": "Check whether numbers, mutations, methods, and causal claims are supported by exact paper evidence.",
    "red_team": "Try to falsify the candidate by finding hallucinated experiments, wrong order, missing failures, and misleading compression.",
    "repair_planner": "Convert reviewer findings into code-level fixes, not free-form replacement answers.",
}

DIMENSIONS = [
    "paper_storyline_fidelity",
    "mainline_completeness",
    "step_factuality",
    "evidence_grounding",
    "trajectory_coherence",
    "sci_evo_value",
]


@dataclass
class QualityGate:
    decision: str
    confidence: float
    reasons: list[str]
    score_mean: float
    score_min: float
    blocker_count: int
    repair_count: int
    reviewer_count: int


def doc_no(case: dict[str, Any]) -> str:
    return str(case.get("case_id", "")).split("_")[-1].zfill(4)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def compact_case(case: dict[str, Any]) -> dict[str, Any]:
    steps = []
    for step in case.get("evolution_trajectory") or []:
        steps.append(
            {
                "step_index": step.get("step_index"),
                "phase": step.get("phase"),
                "action_type": step.get("action_type"),
                "result_status": step.get("result_status"),
                "state_before": step.get("state_before", ""),
                "gap_or_uncertainty": step.get("gap_or_uncertainty", ""),
                "hypothesis": step.get("hypothesis", ""),
                "decision": step.get("decision", ""),
                "observation": step.get("observation", ""),
                "next_step_reason": step.get("next_step_reason", ""),
                "tool_or_method": step.get("tool_or_method", {}),
                "parameters": step.get("parameters", {}),
                "evidence": [
                    {
                        "section": ev.get("section", ""),
                        "quote_or_span": ev.get("quote_or_span", ""),
                    }
                    for ev in (step.get("evidence") or [])
                    if isinstance(ev, dict)
                ],
            }
        )
    return {
        "case_id": case.get("case_id", ""),
        "source": case.get("source", {}),
        "initial_request": case.get("initial_request", {}),
        "evolution_trajectory": steps,
        "success_verification": case.get("success_verification", {}),
        "quality_control": case.get("quality_control", {}),
    }


def load_rule_detail(path: Path | None) -> dict[str, dict[str, Any]]:
    if not path or not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    out = {}
    for item in data:
        if isinstance(item, dict) and item.get("doc_no"):
            out[str(item["doc_no"]).zfill(4)] = item
    return out


def review_schema() -> dict[str, Any]:
    return {
        "reviewer_role": "paper_cartographer|trajectory_judge|evidence_auditor|red_team|repair_planner",
        "doc_no": "",
        "case_id": "",
        "verdict": "pass|repair|fail",
        "confidence": 0.0,
        "dimension_scores": {key: 0.0 for key in DIMENSIONS},
        "blockers": [
            {
                "type": "missing_mainline|unsupported_claim|wrong_order|wrong_number|wrong_mutation|weak_evidence|not_sci_evo|evaluator_uncertain",
                "severity": "medium|high",
                "affected_steps": [],
                "paper_basis": "",
                "problem": "",
                "code_fix_hint": "",
            }
        ],
        "repairs": [
            {
                "priority": "low|medium|high",
                "target": "generation|evidence|ordering|schema|selection|prompt|manual_patch",
                "description": "",
                "code_fix_hint": "",
            }
        ],
        "must_keep": [],
        "uncertainties": [],
        "summary": "",
    }


def build_packet_markdown(
    *,
    case: dict[str, Any],
    full_text_path: Path,
    rule_audit: dict[str, Any] | None,
    role: str,
) -> str:
    if role not in REVIEWER_ROLES:
        raise ValueError(f"unknown reviewer role: {role}")
    case_summary = compact_case(case)
    audit_summary = dict(rule_audit or {})
    candidate_step_count = len(case.get("evolution_trajectory") or [])
    if audit_summary.get("step_count") != candidate_step_count:
        audit_summary["step_count"] = candidate_step_count
        audit_summary.pop("source_rule_step_count", None)
        audit_summary.pop("step_count_note", None)
    return f"""# V16 Quality-First Review Packet

## Role

`{role}`: {ROLE_DESCRIPTIONS[role]}

## Important Boundary

This is a local quality review. Do not generate the final dataset directly.
Your job is to find issues, score quality, and provide code-level repair hints.

## Full Paper

Read the full paper from:

`{full_text_path}`

Do not rely only on the evidence quotes below. The full paper is the authority.

## Candidate Case

```json
{json.dumps(case_summary, ensure_ascii=False, indent=2)}
```

## Code Rule Audit

```json
{json.dumps(audit_summary, ensure_ascii=False, indent=2)}
```

## Output JSON Schema

Return JSON only. Use this schema:

```json
{json.dumps(review_schema(), ensure_ascii=False, indent=2)}
```

## Review Rules

- Read the full paper first, then judge the candidate.
- Prefer finding severe issues over being polite.
- A good Sci-Evo case must capture problem, hypothesis/design, experiment or computation, observation, decision logic, failures or corrections when present, validation, and limitations.
- Extra detail is acceptable only when it is evidence-supported and does not replace required mainline events.
- If the candidate is repairable, say exactly what code or rule should change.
- Do not rewrite the entire answer as the final dataset.
"""


def normalize_review(raw: dict[str, Any], fallback_role: str = "") -> dict[str, Any]:
    verdict = raw.get("verdict")
    if verdict == "accept":
        verdict = "pass"
    elif verdict == "reject":
        verdict = "fail"
    if verdict not in {"pass", "repair", "fail"}:
        verdict = "repair"
    role = raw.get("reviewer_role") or raw.get("role") or fallback_role
    if role not in REVIEWER_ROLES:
        role = fallback_role or "trajectory_judge"
    scores = raw.get("dimension_scores") if isinstance(raw.get("dimension_scores"), dict) else {}
    if not scores and isinstance(raw.get("scores"), dict):
        scores = raw["scores"]
    score_aliases = {
        "step_ordering": "trajectory_coherence",
        "step_granularity": "trajectory_coherence",
        "dataset_fit": "sci_evo_value",
        "dataset_value": "sci_evo_value",
        "overall": "sci_evo_value",
    }
    expanded_scores = dict(scores)
    for src, dst in score_aliases.items():
        if src in scores and dst not in expanded_scores:
            expanded_scores[dst] = scores[src]
    numeric_values = []
    for value in expanded_scores.values():
        try:
            numeric_values.append(max(0.0, min(1.0, float(value))))
        except Exception:
            pass
    score_fallback = round(sum(numeric_values) / max(len(numeric_values), 1), 3) if numeric_values else 0.5
    norm_scores = {}
    for key in DIMENSIONS:
        try:
            norm_scores[key] = round(max(0.0, min(1.0, float(expanded_scores.get(key, score_fallback)))), 3)
        except Exception:
            norm_scores[key] = score_fallback
    blockers = []
    blocker_sources = []
    for item in raw.get("blockers") or []:
        blocker_sources.append(("medium", item))
    for item in raw.get("high_impact_issues") or []:
        blocker_sources.append(("high", item))
    for item in raw.get("medium_impact_issues") or []:
        blocker_sources.append(("medium", item))
    for default_severity, item in blocker_sources:
        if not isinstance(item, dict):
            continue
        severity = item.get("severity") or default_severity
        if severity not in {"medium", "high"}:
            severity = "medium"
        affected = item.get("affected_steps") or item.get("target_steps") or []
        if isinstance(affected, int):
            affected = [affected]
        if not isinstance(affected, list):
            affected = []
        blockers.append(
            {
                "type": str(item.get("type", "evaluator_uncertain")),
                "severity": severity,
                "affected_steps": affected,
                "paper_basis": str(item.get("paper_basis", ""))[:1200],
                "problem": str(item.get("problem", ""))[:1200],
                "code_fix_hint": str(item.get("code_fix_hint") or item.get("repair_hint") or item.get("likely_score_damage") or "")[:1200],
            }
        )
    repairs = []
    for item in raw.get("repairs") or []:
        if isinstance(item, dict):
            repairs.append(
                {
                    "priority": item.get("priority") if item.get("priority") in {"low", "medium", "high"} else "medium",
                    "target": str(item.get("target", "")),
                    "description": str(item.get("description", ""))[:1200],
                    "code_fix_hint": str(item.get("code_fix_hint", ""))[:1200],
                }
            )
    for item in raw.get("repair_actions") or []:
        if isinstance(item, dict):
            description = item.get("description") or item.get("action") or item.get("repair") or ""
            target = item.get("target") or item.get("action_type") or item.get("repair_action") or ""
            repairs.append(
                {
                    "priority": item.get("priority") if item.get("priority") in {"low", "medium", "high"} else "medium",
                    "target": str(target),
                    "description": str(description)[:1200],
                    "code_fix_hint": str(item.get("code_fix_hint", ""))[:1200],
                }
            )
    return {
        "reviewer_role": role,
        "doc_no": str(raw.get("doc_no", "")),
        "case_id": str(raw.get("case_id", "")),
        "verdict": verdict,
        "confidence": round(max(0.0, min(1.0, float(raw.get("confidence", 0) or 0))), 3),
        "dimension_scores": norm_scores,
        "blockers": blockers,
        "repairs": repairs,
        "must_keep": raw.get("must_keep") if isinstance(raw.get("must_keep"), list) else [],
        "uncertainties": raw.get("uncertainties") if isinstance(raw.get("uncertainties"), list) else [],
        "summary": str(raw.get("summary", ""))[:1500],
    }


def arbitrate_reviews(reviews: list[dict[str, Any]]) -> QualityGate:
    normalized = [normalize_review(r) for r in reviews if isinstance(r, dict)]
    if not normalized:
        return QualityGate(
            decision="error",
            confidence=0,
            reasons=["no_valid_reviews"],
            score_mean=0,
            score_min=0,
            blocker_count=0,
            repair_count=0,
            reviewer_count=0,
        )
    all_scores = []
    high_blockers = 0
    medium_blockers = 0
    repair_count = 0
    verdicts = []
    confidences = []
    for review in normalized:
        verdicts.append(review["verdict"])
        confidences.append(review["confidence"])
        all_scores.extend(review["dimension_scores"].values())
        repair_count += len(review.get("repairs", []))
        for blocker in review.get("blockers", []):
            if blocker.get("severity") == "high":
                high_blockers += 1
            else:
                medium_blockers += 1
    score_mean = round(sum(all_scores) / max(len(all_scores), 1), 3)
    score_min = round(min(all_scores), 3) if all_scores else 0
    reasons = []
    decision = "pass"
    if "fail" in verdicts or high_blockers >= 2 or score_min < 0.45:
        decision = "fail"
    elif "repair" in verdicts or high_blockers or medium_blockers >= 2 or score_mean < 0.82 or score_min < 0.7:
        decision = "repair"
    if high_blockers:
        reasons.append(f"high_blockers={high_blockers}")
    if medium_blockers:
        reasons.append(f"medium_blockers={medium_blockers}")
    if score_mean < 0.82:
        reasons.append(f"score_mean={score_mean}")
    if score_min < 0.7:
        reasons.append(f"score_min={score_min}")
    if not reasons:
        reasons.append("all_quality_gates_passed")
    confidence = round(sum(confidences) / max(len(confidences), 1), 3)
    return QualityGate(
        decision=decision,
        confidence=confidence,
        reasons=reasons,
        score_mean=score_mean,
        score_min=score_min,
        blocker_count=high_blockers + medium_blockers,
        repair_count=repair_count,
        reviewer_count=len(normalized),
    )


def gate_to_dict(gate: QualityGate) -> dict[str, Any]:
    return asdict(gate)

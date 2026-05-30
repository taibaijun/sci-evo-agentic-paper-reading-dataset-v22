"""Deterministic structure checks for generated Sci-Evo cases."""

from __future__ import annotations

import re
from typing import Any


WET_ACTIONS = {"wet_experiment"}
ANALYSIS_PHASES = {"analysis"}
NON_EXECUTION_PHASES = {"hypothesis", "design", "revision"}
TEXT_FIELDS = [
    "state_before",
    "gap_or_uncertainty",
    "hypothesis",
    "decision",
    "observation",
    "next_step_reason",
]


def _bad_text_reason(text: str) -> str:
    stripped = text.strip()
    if not stripped:
        return ""
    if stripped.count("{") != stripped.count("}") or stripped.count("[") != stripped.count("]"):
        return "unbalanced_brackets"
    if re.search(r"[,;:]?\s*\{$", stripped):
        return "trailing_brace_fragment"
    if re.search(r"\b(step_index|evolution_trajectory|quote_or_span|tool_or_method)\b", stripped):
        return "serialized_json_leak"
    if len(stripped) > 420 and stripped.count(".") <= 1:
        return "likely_concatenated_or_truncated"
    if re.search(r"\b[a-zA-Z]{4,}$", stripped) and not stripped.endswith((".", ")", "]", "%", "μM", "mM")) and len(stripped) > 180:
        return "possible_mid_sentence_truncation"
    return ""


def audit_case_structure(case: dict[str, Any]) -> dict[str, Any]:
    issues = []
    for step in case.get("evolution_trajectory") or []:
        if not isinstance(step, dict):
            continue
        step_index = int(step.get("step_index") or 0)
        phase = str(step.get("phase", ""))
        action_type = str(step.get("action_type", ""))
        if phase in ANALYSIS_PHASES and action_type in WET_ACTIONS:
            issues.append(
                {
                    "type": "phase_action_mismatch",
                    "severity": "medium",
                    "affected_steps": [step_index],
                    "problem": f"phase={phase} but action_type={action_type}.",
                    "code_fix_hint": "Use experiment/validation phase for wet optimization or rescreening steps unless the step is purely interpretive.",
                }
            )
        method_count = 0
        tool = step.get("tool_or_method")
        if isinstance(tool, dict) and tool.get("name"):
            method_count += 1
        text_blob = " ".join(str(step.get(field, "")) for field in TEXT_FIELDS)
        method_terms = re.findall(
            r"\b(?:PCR|FACS|MTP|HPLC|LC-MS|flow cytometry|cloning|transformation|kinetic|screening|sorting)\b",
            text_blob,
            re.I,
        )
        method_count += len({term.lower() for term in method_terms})
        if action_type in WET_ACTIONS and phase not in NON_EXECUTION_PHASES and method_count >= 6:
            issues.append(
                {
                    "type": "overcompressed_step",
                    "severity": "medium",
                    "affected_steps": [step_index],
                    "problem": "Step contains many distinct methods or workflow boundaries and may need splitting.",
                    "code_fix_hint": "Split by method/result boundary when recovery, cloning, screening, selection, and kinetic validation co-occur.",
                }
            )
        for field in TEXT_FIELDS:
            reason = _bad_text_reason(str(step.get(field, "")))
            if reason:
                issues.append(
                    {
                        "type": "text_hygiene",
                        "severity": "medium",
                        "affected_steps": [step_index],
                        "field": field,
                        "problem": f"{field} failed text hygiene: {reason}.",
                        "code_fix_hint": "Regenerate or trim the field; do not accept unmatched braces, JSON leakage, or truncated transition text.",
                    }
                )
    decision = "repair" if issues else "pass"
    return {
        "doc_no": str(case.get("case_id", "")).split("_")[-1].zfill(4),
        "case_id": case.get("case_id", ""),
        "decision": decision,
        "issue_count": len(issues),
        "issues": issues,
    }

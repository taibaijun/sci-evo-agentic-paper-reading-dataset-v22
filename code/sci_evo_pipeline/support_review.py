"""Second-pass semantic support review for extracted Sci-Evo cases."""

from __future__ import annotations

import json
from typing import Any

from .deepseek_client import DeepSeekClient


SUPPORT_REVIEW_SYSTEM = """You are a strict scientific dataset auditor.
You evaluate whether each extracted Sci-Evo trajectory step is supported by its cited evidence snippets.
You must output valid JSON only.
Be conservative. Do not reward a step just because it sounds plausible.
Judge support only from the provided evidence text, not from outside knowledge.
"""


SUPPORT_REVIEW_SCHEMA = {
    "case_id": "sci_evo_0000",
    "overall_support_score": 0.0,
    "case_decision": "accept|revise|reject",
    "step_reviews": [
        {
            "step_index": 1,
            "supported": True,
            "support_score": 0.0,
            "issue_type": "none|weak_evidence|quote_irrelevant|overclaim|missing_metric|sequence_error|not_sci_evo",
            "notes": "",
            "recommended_fix": "",
        }
    ],
    "risk_notes": [],
}


def _clip(text: str, limit: int) -> str:
    text = text or ""
    if len(text) <= limit:
        return text
    return text[:limit] + "\n...[clipped]..."


def build_support_context(case: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    snippets = {
        item.get("evidence_id"): item
        for item in context.get("evidence_snippets", [])
        if isinstance(item, dict)
    }
    steps = []
    for step in case.get("evolution_trajectory") or []:
        cited = []
        for ev in step.get("evidence") or []:
            if not isinstance(ev, dict):
                continue
            evidence_id = ev.get("evidence_id", "")
            snippet = snippets.get(evidence_id, {})
            cited.append(
                {
                    "evidence_id": evidence_id,
                    "section": ev.get("section") or snippet.get("section", ""),
                    "quote_or_span": ev.get("quote_or_span", ""),
                    "snippet_text": _clip(snippet.get("text", ""), 1400),
                }
            )
        steps.append(
            {
                "step_index": step.get("step_index"),
                "phase": step.get("phase"),
                "action_type": step.get("action_type"),
                "result_status": step.get("result_status"),
                "state_before": _clip(step.get("state_before", ""), 700),
                "gap_or_uncertainty": _clip(step.get("gap_or_uncertainty", ""), 700),
                "hypothesis": _clip(step.get("hypothesis", ""), 700),
                "decision": _clip(step.get("decision", ""), 900),
                "tool_or_method": step.get("tool_or_method", {}),
                "parameters": step.get("parameters", {}),
                "observation": _clip(step.get("observation", ""), 900),
                "next_step_reason": _clip(step.get("next_step_reason", ""), 700),
                "cited_evidence": cited,
            }
        )
    return {
        "case_id": case.get("case_id", ""),
        "source": case.get("source", {}),
        "initial_request": case.get("initial_request", {}),
        "success_verification": case.get("success_verification", {}),
        "steps": steps,
    }


def build_support_prompt(review_context: dict[str, Any]) -> str:
    return f"""Review this extracted Sci-Evo case as strict JSON.

Goal:
For each step, decide whether the cited evidence text actually supports the extracted decision, observation, and next_step_reason.

Rules:
1. A step is strongly supported only if its cited evidence contains the key action/result, not merely a related keyword.
2. Penalize overclaims, invented metrics, wrong order, generic summaries, and claims that require outside knowledge.
3. A short exact quote is already checked elsewhere; here you judge semantic support.
4. Use support_score:
   - 0.90-1.00: directly supported by cited evidence.
   - 0.75-0.89: mostly supported, minor wording or context weakness.
   - 0.50-0.74: partially supported; needs revision.
   - 0.00-0.49: weak or unsupported.
5. case_decision:
   - accept: average support is high and no severe unsupported scientific claim.
   - revise: usable but one or more steps need evidence or wording repair.
   - reject: not a real Sci-Evo trajectory or many unsupported claims.
6. Output valid json only. The word json is included for JSON mode.

Expected JSON shape:
{json.dumps(SUPPORT_REVIEW_SCHEMA, ensure_ascii=False, indent=2)}

Case to review:
{json.dumps(review_context, ensure_ascii=False, indent=2)}
"""


def normalize_support_review(review: dict[str, Any], case: dict[str, Any]) -> dict[str, Any]:
    step_count = len(case.get("evolution_trajectory") or [])
    out = {
        "case_id": case.get("case_id", ""),
        "overall_support_score": float(review.get("overall_support_score") or 0),
        "case_decision": review.get("case_decision") if review.get("case_decision") in {"accept", "revise", "reject"} else "revise",
        "step_reviews": [],
        "risk_notes": review.get("risk_notes") if isinstance(review.get("risk_notes"), list) else [],
    }
    seen = set()
    for item in review.get("step_reviews") or []:
        if not isinstance(item, dict):
            continue
        try:
            step_index = int(item.get("step_index"))
        except Exception:
            continue
        seen.add(step_index)
        score = max(0.0, min(1.0, float(item.get("support_score") or 0)))
        issue = item.get("issue_type")
        if issue not in {
            "none",
            "weak_evidence",
            "quote_irrelevant",
            "overclaim",
            "missing_metric",
            "sequence_error",
            "not_sci_evo",
        }:
            issue = "weak_evidence" if score < 0.75 else "none"
        out["step_reviews"].append(
            {
                "step_index": step_index,
                "supported": bool(item.get("supported", score >= 0.75)),
                "support_score": round(score, 3),
                "issue_type": issue,
                "notes": str(item.get("notes", ""))[:600],
                "recommended_fix": str(item.get("recommended_fix", ""))[:600],
            }
        )
    for step_index in range(1, step_count + 1):
        if step_index not in seen:
            out["step_reviews"].append(
                {
                    "step_index": step_index,
                    "supported": False,
                    "support_score": 0.0,
                    "issue_type": "weak_evidence",
                    "notes": "Missing critic review for this step.",
                    "recommended_fix": "Re-run review or manually inspect evidence.",
                }
            )
    out["step_reviews"].sort(key=lambda x: x["step_index"])
    if out["step_reviews"]:
        avg = sum(x["support_score"] for x in out["step_reviews"]) / len(out["step_reviews"])
        # Trust a model-provided score only if it is close to the per-step average.
        if abs(out["overall_support_score"] - avg) > 0.2:
            out["overall_support_score"] = avg
    out["overall_support_score"] = round(max(0.0, min(1.0, out["overall_support_score"])), 3)
    severe = sum(1 for x in out["step_reviews"] if x["support_score"] < 0.5)
    weak = sum(1 for x in out["step_reviews"] if x["support_score"] < 0.75)
    out["severe_unsupported_steps"] = severe
    out["weak_steps"] = weak
    if severe:
        out["case_decision"] = "reject" if severe >= 2 else "revise"
    elif weak and out["case_decision"] == "accept":
        out["case_decision"] = "revise"
    return out


def review_case_support(
    *,
    client: DeepSeekClient,
    case: dict[str, Any],
    context: dict[str, Any],
    temperature: float = 0.0,
) -> dict[str, Any]:
    review_context = build_support_context(case, context)
    raw = client.chat_json(
        system_prompt=SUPPORT_REVIEW_SYSTEM,
        user_prompt=build_support_prompt(review_context),
        temperature=temperature,
        max_tokens=8192,
    )
    normalized = normalize_support_review(raw, case)
    normalized["_api_usage"] = raw.get("_api_usage", {})
    normalized["_api_model"] = raw.get("_api_model", "")
    normalized["_api_finish_reason"] = raw.get("_api_finish_reason", "")
    return normalized


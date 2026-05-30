"""Critic-guided repair of weakly supported Sci-Evo trajectory steps."""

from __future__ import annotations

import json
from typing import Any

from .deepseek_client import DeepSeekClient
from .schema import normalize_case, repair_evidence_quotes, validate_case, validate_evidence_quotes
from .support_review import build_support_context


REPAIR_SYSTEM = """You are a conservative scientific data editor.
You repair extracted Sci-Evo JSON so that every step is supported by its cited evidence snippets.
You must output valid JSON only.
Do not add scientific facts that are not present in the provided evidence text.
Prefer narrowing or weakening claims over inventing new evidence.
"""


def build_repair_prompt(case: dict[str, Any], context: dict[str, Any], review: dict[str, Any]) -> str:
    weak_reviews = [
        item
        for item in review.get("step_reviews", [])
        if float(item.get("support_score") or 0) < 0.75
    ]
    support_context = build_support_context(case, context)
    return f"""Repair this Sci-Evo case as strict json.

Goal:
Revise only the weak steps flagged by the critic so that decision, observation, and next_step_reason are supported by evidence snippets.

Rules:
1. Keep the same case_id and source.
2. Do not invent new experiments, tools, metrics, or results.
3. If a field is not supported, replace it with a narrower supported statement or "unknown".
4. You may change phase/action_type/result_status if the critic shows the original label was too strong.
5. You may replace evidence quotes, but quote_or_span must be an exact short substring copied from the provided snippet text.
6. Do not edit strong steps unless needed for sequence consistency.
7. Output valid json only with root key "case".

Critic weak-step review:
{json.dumps(weak_reviews, ensure_ascii=False, indent=2)}

Original case:
{json.dumps(case, ensure_ascii=False, indent=2)}

Evidence context:
{json.dumps(support_context, ensure_ascii=False, indent=2)}
"""


def repair_case_with_critic(
    *,
    client: DeepSeekClient,
    case: dict[str, Any],
    context: dict[str, Any],
    review: dict[str, Any],
    doc_no: str,
) -> dict[str, Any]:
    raw = client.chat_json(
        system_prompt=REPAIR_SYSTEM,
        user_prompt=build_repair_prompt(case, context, review),
        temperature=0.0,
        max_tokens=8192,
    )
    candidate = raw.get("case") if isinstance(raw.get("case"), dict) else raw
    normalized = normalize_case(candidate, doc_no=doc_no, source=context.get("source", {}))
    repair_count = repair_evidence_quotes(normalized, context)
    return {
        "case": normalized,
        "validation_errors": validate_case(normalized),
        "evidence_quote_errors": validate_evidence_quotes(normalized, context),
        "quote_repair_count": repair_count,
        "critic_repair_source": {
            "previous_support_score": review.get("overall_support_score"),
            "previous_decision": review.get("case_decision"),
            "previous_weak_steps": review.get("weak_steps"),
            "previous_severe_unsupported_steps": review.get("severe_unsupported_steps"),
        },
        "api_usage": raw.get("_api_usage", {}),
        "api_model": raw.get("_api_model", ""),
        "api_finish_reason": raw.get("_api_finish_reason", ""),
    }


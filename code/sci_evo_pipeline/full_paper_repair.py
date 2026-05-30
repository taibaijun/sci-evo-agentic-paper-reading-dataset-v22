"""Full-paper-review-guided repair for Sci-Evo cases."""

from __future__ import annotations

import json
import re
from typing import Any

from .deepseek_client import DeepSeekClient
from .evidence_index import check_quote, normalize_text
from .full_paper_review import split_full_text
from .schema import normalize_case, validate_case


REPAIR_SYSTEM = """You are a conservative scientific dataset editor.
You repair an extracted Sci-Evo JSON case using a full-paper review.
Output valid JSON only.
Do not invent facts. Prefer narrowing claims over adding unsupported detail.
"""


def _squash_ws(text: str) -> str:
    return re.sub(r"\s+", " ", normalize_text(text or "")).strip().lower()


def quote_errors_against_full_text(case: dict[str, Any], full_text: str) -> list[str]:
    """Validate that evidence quotes are exact substrings of the full MinerU markdown."""

    errors: list[str] = []
    for step in case.get("evolution_trajectory") or []:
        step_index = step.get("step_index")
        for evidence_index, ev in enumerate(step.get("evidence") or []):
            if not isinstance(ev, dict):
                continue
            quote = str(ev.get("quote_or_span", ""))
            if not quote:
                errors.append(f"step {step_index} has empty evidence quote")
                continue
            check = check_quote(full_text, quote, step_index=int(step_index or 0), evidence_index=evidence_index)
            if check.warning or not (check.exact_match or check.normalized_match):
                errors.append(f"step {step_index} quote not found in full text: {_squash_ws(quote)[:120]}")
    return errors


def flagged_step_reviews(review: dict[str, Any], *, min_score: float = 0.9) -> list[dict[str, Any]]:
    flagged = []
    for item in review.get("step_reviews") or []:
        if not isinstance(item, dict):
            continue
        score = float(item.get("support_score") or 0)
        issue = item.get("issue_type") or "none"
        if score < min_score or issue != "none" or not bool(item.get("supported", True)):
            flagged.append(item)
    return flagged


def selected_repair_chunks(full_text: str, review: dict[str, Any], flagged_steps: list[dict[str, Any]], *, max_chunks: int = 3) -> list[dict[str, Any]]:
    chunking = review.get("chunking") or {}
    chunks = split_full_text(
        full_text,
        chunk_chars=int(chunking.get("chunk_chars") or 26000),
        overlap=int(chunking.get("overlap") or 1000),
    )
    by_id = {c.chunk_id: c for c in chunks}
    flagged_indices = {int(s.get("step_index")) for s in flagged_steps if s.get("step_index") is not None}
    chunk_ids: list[str] = []

    def add_chunk_id(value: Any) -> None:
        if isinstance(value, str) and value in by_id and value not in chunk_ids:
            chunk_ids.append(value)

    for step in flagged_steps:
        for chunk_id in step.get("best_chunk_ids") or []:
            add_chunk_id(chunk_id)
    for chunk_review in review.get("chunk_reviews") or []:
        chunk_id = chunk_review.get("chunk_id")
        for contradiction in chunk_review.get("contradictions") or []:
            try:
                step_index = int(contradiction.get("step_index"))
            except Exception:
                continue
            if step_index in flagged_indices:
                add_chunk_id(chunk_id)

    if not chunk_ids:
        chunk_ids = [c.chunk_id for c in chunks[:max_chunks]]
    chunk_ids = chunk_ids[:max_chunks]
    return [
        {
            "chunk_id": by_id[cid].chunk_id,
            "char_start": by_id[cid].char_start,
            "char_end": by_id[cid].char_end,
            "text": by_id[cid].text,
        }
        for cid in chunk_ids
    ]


def build_repair_prompt(case: dict[str, Any], review: dict[str, Any], evidence_chunks: list[dict[str, Any]]) -> str:
    weak_steps = flagged_step_reviews(review)
    return f"""Repair this Sci-Evo case as strict JSON.

Goal:
Use the full-paper review to revise only the flagged trajectory steps so every decision, observation, metric, and next-step reason is supported by the paper.

Rules:
1. Keep case_id, dataset_type, source, and the number/order of trajectory steps.
2. Do not edit strong steps unless a flagged-step correction requires a small sequence consistency change.
3. If the review identifies a contradiction, correct the claim to match the paper.
4. If a detail is not supported, remove it, weaken it, or replace it with "unknown".
5. Evidence quote_or_span values must be exact short substrings copied from the provided paper chunks.
6. Keep the result useful as a Sci-Evo trajectory: decision -> observation -> next_step_reason.
7. Output valid JSON only with root key "case".

Flagged full-paper step reviews:
{json.dumps(weak_steps, ensure_ascii=False, indent=2)}

Case-level risks:
{json.dumps(review.get("case_level_risks", []), ensure_ascii=False, indent=2)}

Original case:
{json.dumps(case, ensure_ascii=False, indent=2)}

Relevant full-paper chunks:
{json.dumps(evidence_chunks, ensure_ascii=False, indent=2)}
"""


def repair_case_with_full_review(
    *,
    client: DeepSeekClient,
    case: dict[str, Any],
    review: dict[str, Any],
    full_text: str,
    doc_no: str,
) -> dict[str, Any]:
    evidence_chunks = selected_repair_chunks(full_text, review, flagged_step_reviews(review))
    raw = client.chat_json(
        system_prompt=REPAIR_SYSTEM,
        user_prompt=build_repair_prompt(case, review, evidence_chunks),
        temperature=0.0,
        max_tokens=8192,
    )
    candidate = raw.get("case") if isinstance(raw.get("case"), dict) else raw
    normalized = normalize_case(candidate, doc_no=doc_no, source=case.get("source", {}))
    return {
        "case": normalized,
        "validation_errors": validate_case(normalized),
        "full_text_quote_errors": quote_errors_against_full_text(normalized, full_text),
        "full_paper_repair_source": {
            "previous_full_paper_support_score": review.get("full_paper_support_score"),
            "previous_full_paper_decision": review.get("full_paper_decision"),
            "previous_recommended_action": review.get("recommended_action"),
            "previous_weak_steps": review.get("weak_steps"),
            "previous_severe_steps": review.get("severe_steps"),
            "flagged_steps": [item.get("step_index") for item in flagged_step_reviews(review)],
            "repair_chunk_ids": [item["chunk_id"] for item in evidence_chunks],
        },
        "api_usage": raw.get("_api_usage", {}),
        "api_model": raw.get("_api_model", ""),
        "api_finish_reason": raw.get("_api_finish_reason", ""),
    }

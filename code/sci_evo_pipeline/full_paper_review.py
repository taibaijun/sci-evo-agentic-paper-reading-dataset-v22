"""Full-paper review for selected Sci-Evo cases.

This module reviews an extracted case against the entire MinerU Markdown paper.
It uses a map-reduce pattern:

1. Every paper chunk is read by the model.
2. The model reports which trajectory steps are supported by that chunk.
3. A final model call judges the whole case from all chunk-level findings.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from .deepseek_client import DeepSeekClient


CHUNK_SYSTEM = """You are a strict scientific evidence reader.
You read one chunk of a full paper and identify which extracted Sci-Evo trajectory steps are supported by this chunk.
Output valid JSON only. Do not use outside knowledge.
"""


FINAL_SYSTEM = """You are a strict scientific dataset judge.
You judge whether an extracted Sci-Evo case is supported by a full paper, using chunk-level evidence findings from the complete paper.
Output valid JSON only. Be conservative.
"""


@dataclass
class TextChunk:
    chunk_id: str
    char_start: int
    char_end: int
    text: str


def split_full_text(text: str, chunk_chars: int = 26000, overlap: int = 1000) -> list[TextChunk]:
    chunks: list[TextChunk] = []
    offset = 0
    idx = 1
    while offset < len(text):
        end = min(len(text), offset + chunk_chars)
        piece = text[offset:end]
        chunks.append(TextChunk(f"C{idx:03d}", offset, end, piece))
        if end >= len(text):
            break
        offset = end - overlap
        idx += 1
    return chunks


def compact_case(case: dict[str, Any]) -> dict[str, Any]:
    steps = []
    for step in case.get("evolution_trajectory") or []:
        steps.append(
            {
                "step_index": step.get("step_index"),
                "phase": step.get("phase"),
                "action_type": step.get("action_type"),
                "result_status": step.get("result_status"),
                "decision": step.get("decision", ""),
                "observation": step.get("observation", ""),
                "next_step_reason": step.get("next_step_reason", ""),
                "tool_or_method": step.get("tool_or_method", {}),
                "parameters": step.get("parameters", {}),
            }
        )
    return {
        "case_id": case.get("case_id", ""),
        "source": case.get("source", {}),
        "initial_request": case.get("initial_request", {}),
        "steps": steps,
        "success_verification": case.get("success_verification", {}),
    }


def _clip(text: str, n: int) -> str:
    text = text or ""
    return text if len(text) <= n else text[:n] + "\n...[clipped]..."


def chunk_prompt(case_summary: dict[str, Any], chunk: TextChunk, total_chunks: int) -> str:
    return f"""Read this full-paper chunk and report support for the extracted Sci-Evo steps.

Rules:
1. This is chunk {chunk.chunk_id} of {total_chunks}; all chunks together cover the entire paper.
2. Only report a step if this chunk directly supports its decision, observation, next-step reason, tool/method, or metric.
3. Use exact short quotes copied from the chunk.
4. Do not infer from outside this chunk.
5. If the chunk contradicts or weakens a step, report it in `contradictions`.
6. Output valid json only.

Expected JSON:
{{
  "chunk_id": "{chunk.chunk_id}",
  "supported_steps": [
    {{
      "step_index": 1,
      "support_score": 0.0,
      "supports": ["decision", "observation", "next_step_reason", "metric", "method"],
      "exact_quotes": ["short exact quote from this chunk"],
      "notes": ""
    }}
  ],
  "contradictions": [
    {{
      "step_index": 1,
      "issue": "",
      "exact_quote": ""
    }}
  ],
  "paper_level_notes": []
}}

Extracted case summary:
{json.dumps(case_summary, ensure_ascii=False, indent=2)}

Paper chunk metadata:
{{
  "chunk_id": "{chunk.chunk_id}",
  "char_start": {chunk.char_start},
  "char_end": {chunk.char_end}
}}

Paper chunk text:
{chunk.text}
"""


def normalize_chunk_review(raw: dict[str, Any], chunk: TextChunk) -> dict[str, Any]:
    out = {
        "chunk_id": chunk.chunk_id,
        "char_start": chunk.char_start,
        "char_end": chunk.char_end,
        "supported_steps": [],
        "contradictions": [],
        "paper_level_notes": raw.get("paper_level_notes") if isinstance(raw.get("paper_level_notes"), list) else [],
        "api_usage": raw.get("_api_usage", {}),
    }
    for item in raw.get("supported_steps") or []:
        if not isinstance(item, dict):
            continue
        try:
            step_index = int(item.get("step_index"))
        except Exception:
            continue
        score = max(0.0, min(1.0, float(item.get("support_score") or 0)))
        quotes = item.get("exact_quotes") if isinstance(item.get("exact_quotes"), list) else []
        out["supported_steps"].append(
            {
                "step_index": step_index,
                "support_score": round(score, 3),
                "supports": item.get("supports") if isinstance(item.get("supports"), list) else [],
                "exact_quotes": [str(q)[:300] for q in quotes[:5]],
                "notes": str(item.get("notes", ""))[:700],
            }
        )
    for item in raw.get("contradictions") or []:
        if not isinstance(item, dict):
            continue
        out["contradictions"].append(
            {
                "step_index": item.get("step_index"),
                "issue": str(item.get("issue", ""))[:700],
                "exact_quote": str(item.get("exact_quote", ""))[:300],
            }
        )
    return out


def review_chunk(client: DeepSeekClient, case_summary: dict[str, Any], chunk: TextChunk, total_chunks: int) -> dict[str, Any]:
    raw = client.chat_json(
        system_prompt=CHUNK_SYSTEM,
        user_prompt=chunk_prompt(case_summary, chunk, total_chunks),
        temperature=0.0,
        max_tokens=4096,
    )
    return normalize_chunk_review(raw, chunk)


def build_final_prompt(case_summary: dict[str, Any], chunk_reviews: list[dict[str, Any]], full_text_chars: int) -> str:
    compact_reviews = []
    for review in chunk_reviews:
        compact_reviews.append(
            {
                "chunk_id": review.get("chunk_id"),
                "char_start": review.get("char_start"),
                "char_end": review.get("char_end"),
                "supported_steps": review.get("supported_steps", []),
                "contradictions": review.get("contradictions", []),
            }
        )
    return f"""Judge this extracted Sci-Evo case using full-paper chunk reviews.

The full paper was split into chunks covering all {full_text_chars} characters of MinerU Markdown. A model read every chunk and reported step-level evidence.

Rules:
1. Judge support for each step from the chunk findings.
2. A step is supported if at least one chunk directly supports its key decision and observation, or the missing part is minor.
3. Penalize steps supported only by generic background or only by a title/abstract when the step claims detailed experimental actions.
4. Flag overclaims, wrong sequence, unsupported metrics, and steps that are not really Sci-Evo.
5. Output valid json only.

Expected JSON:
{{
  "case_id": "",
  "full_paper_support_score": 0.0,
  "full_paper_decision": "accept|revise|reject",
  "coverage": {{
    "chunks_read": 0,
    "full_text_chars": 0
  }},
  "step_reviews": [
    {{
      "step_index": 1,
      "support_score": 0.0,
      "supported": true,
      "best_chunk_ids": ["C001"],
      "supporting_quotes": ["short exact quote"],
      "issue_type": "none|weak_evidence|overclaim|missing_metric|sequence_error|contradiction|not_sci_evo",
      "notes": "",
      "recommended_fix": ""
    }}
  ],
  "case_level_risks": [],
  "recommended_action": "keep|repair|drop"
}}

Extracted case:
{json.dumps(case_summary, ensure_ascii=False, indent=2)}

Full-paper chunk findings:
{json.dumps(compact_reviews, ensure_ascii=False, indent=2)}
"""


def normalize_final_review(raw: dict[str, Any], case: dict[str, Any], chunks: list[TextChunk], full_text_chars: int) -> dict[str, Any]:
    step_count = len(case.get("evolution_trajectory") or [])
    out = {
        "case_id": case.get("case_id", ""),
        "full_paper_support_score": float(raw.get("full_paper_support_score") or 0),
        "full_paper_decision": raw.get("full_paper_decision") if raw.get("full_paper_decision") in {"accept", "revise", "reject"} else "revise",
        "coverage": {
            "chunks_read": len(chunks),
            "full_text_chars": full_text_chars,
            "covered_char_start": chunks[0].char_start if chunks else 0,
            "covered_char_end": chunks[-1].char_end if chunks else 0,
        },
        "step_reviews": [],
        "case_level_risks": raw.get("case_level_risks") if isinstance(raw.get("case_level_risks"), list) else [],
        "recommended_action": raw.get("recommended_action") if raw.get("recommended_action") in {"keep", "repair", "drop"} else "repair",
        "api_usage": raw.get("_api_usage", {}),
    }
    seen = set()
    for item in raw.get("step_reviews") or []:
        if not isinstance(item, dict):
            continue
        try:
            step_index = int(item.get("step_index"))
        except Exception:
            continue
        seen.add(step_index)
        score = max(0.0, min(1.0, float(item.get("support_score") or 0)))
        issue = item.get("issue_type")
        if issue not in {"none", "weak_evidence", "overclaim", "missing_metric", "sequence_error", "contradiction", "not_sci_evo"}:
            issue = "none" if score >= 0.8 else "weak_evidence"
        out["step_reviews"].append(
            {
                "step_index": step_index,
                "support_score": round(score, 3),
                "supported": bool(item.get("supported", score >= 0.75)),
                "best_chunk_ids": item.get("best_chunk_ids") if isinstance(item.get("best_chunk_ids"), list) else [],
                "supporting_quotes": item.get("supporting_quotes") if isinstance(item.get("supporting_quotes"), list) else [],
                "issue_type": issue,
                "notes": str(item.get("notes", ""))[:700],
                "recommended_fix": str(item.get("recommended_fix", ""))[:700],
            }
        )
    for step_index in range(1, step_count + 1):
        if step_index not in seen:
            out["step_reviews"].append(
                {
                    "step_index": step_index,
                    "support_score": 0.0,
                    "supported": False,
                    "best_chunk_ids": [],
                    "supporting_quotes": [],
                    "issue_type": "weak_evidence",
                    "notes": "No full-paper review entry for this step.",
                    "recommended_fix": "Manually review or rerun full-paper review.",
                }
            )
    out["step_reviews"].sort(key=lambda x: x["step_index"])
    if out["step_reviews"]:
        avg = sum(x["support_score"] for x in out["step_reviews"]) / len(out["step_reviews"])
        if abs(out["full_paper_support_score"] - avg) > 0.2:
            out["full_paper_support_score"] = avg
    out["full_paper_support_score"] = round(max(0.0, min(1.0, out["full_paper_support_score"])), 3)
    out["weak_steps"] = sum(1 for x in out["step_reviews"] if x["support_score"] < 0.75)
    out["severe_steps"] = sum(1 for x in out["step_reviews"] if x["support_score"] < 0.5)
    if out["severe_steps"]:
        out["recommended_action"] = "drop" if out["severe_steps"] >= 2 else "repair"
    elif out["weak_steps"] == 0 and out["full_paper_support_score"] >= 0.85:
        out["recommended_action"] = "keep"
    elif out["weak_steps"] and out["recommended_action"] == "keep":
        out["recommended_action"] = "repair"
    return out


def final_review(client: DeepSeekClient, case: dict[str, Any], chunks: list[TextChunk], chunk_reviews: list[dict[str, Any]], full_text_chars: int) -> dict[str, Any]:
    case_summary = compact_case(case)
    raw = client.chat_json(
        system_prompt=FINAL_SYSTEM,
        user_prompt=build_final_prompt(case_summary, chunk_reviews, full_text_chars),
        temperature=0.0,
        max_tokens=8192,
    )
    return normalize_final_review(raw, case, chunks, full_text_chars)


def run_full_paper_review(
    *,
    client: DeepSeekClient,
    case: dict[str, Any],
    full_text: str,
    chunk_chars: int = 26000,
    overlap: int = 1000,
) -> dict[str, Any]:
    chunks = split_full_text(full_text, chunk_chars=chunk_chars, overlap=overlap)
    case_summary = compact_case(case)
    chunk_reviews = [review_chunk(client, case_summary, chunk, len(chunks)) for chunk in chunks]
    final = final_review(client, case, chunks, chunk_reviews, len(full_text))
    final["chunk_reviews"] = chunk_reviews
    final["chunking"] = {
        "chunk_chars": chunk_chars,
        "overlap": overlap,
        "chunk_count": len(chunks),
    }
    return final

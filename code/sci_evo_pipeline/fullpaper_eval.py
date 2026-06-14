"""Structured full-paper evaluator for local Sci-Evo testing.

This module is intentionally an evaluator, not a production generator.

The evaluation avoids the common "give the answer to the model and ask if it is
right" failure mode:

1. The model first reads every paper chunk without seeing the candidate case and
   extracts paper-native evolution events with exact quotes.
2. A reducer builds a canonical storyline from those independent events.
3. A judge compares the candidate trajectory against the canonical storyline,
   code audit findings, and dataset quality rubric.
4. A red-team pass looks only for missed severe issues.
5. Deterministic gates convert model outputs into pass/repair/fail decisions.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

from .deepseek_client import DeepSeekClient


EXTRACT_SYSTEM = """You are a strict scientific process reader.
You read one chunk of a paper and extract only paper-native scientific evolution events.
You do not see any candidate dataset answer in this pass.
Use only the chunk text. Output valid JSON only.
"""

REDUCE_SYSTEM = """You are a strict scientific storyline reducer.
You merge chunk-level paper-native events into a canonical research evolution storyline.
Use only the provided chunk event records. Output valid JSON only.
"""

AUDIT_SYSTEM = """You are a skeptical Sci-Evo dataset evaluator.
You compare a candidate trajectory against an independently extracted full-paper storyline.
Your job is to find unsupported claims, missing mainline events, wrong order, and weak evidence.
Output valid JSON only.
"""

REDTEAM_SYSTEM = """You are a red-team evaluator for scientific datasets.
You receive an independent storyline, a candidate trajectory, and an initial audit.
Find severe issues the audit may have missed. Output valid JSON only.
"""


@dataclass
class TextChunk:
    chunk_id: str
    char_start: int
    char_end: int
    text: str


def split_full_text(text: str, chunk_chars: int = 18000, overlap: int = 900) -> list[TextChunk]:
    chunks: list[TextChunk] = []
    offset = 0
    idx = 1
    while offset < len(text):
        end = min(len(text), offset + chunk_chars)
        chunks.append(TextChunk(f"C{idx:03d}", offset, end, text[offset:end]))
        if end >= len(text):
            break
        offset = max(0, end - overlap)
        idx += 1
    return chunks


def compact_case(case: dict[str, Any]) -> dict[str, Any]:
    steps = []
    for step in case.get("evolution_trajectory") or []:
        evidence = []
        for ev in step.get("evidence") or []:
            if isinstance(ev, dict):
                evidence.append(
                    {
                        "section": ev.get("section", ""),
                        "quote_or_span": ev.get("quote_or_span", ""),
                    }
                )
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
                "evidence": evidence[:4],
            }
        )
    return {
        "case_id": case.get("case_id", ""),
        "source": case.get("source", {}),
        "initial_request": case.get("initial_request", {}),
        "evolution_trajectory": steps,
        "success_verification": case.get("success_verification", {}),
    }


def _clip(value: Any, limit: int) -> str:
    text = str(value or "")
    return text if len(text) <= limit else text[:limit] + "\n...[clipped]..."


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip().lower()


def quote_present(quote: str, full_text: str) -> bool:
    q = _norm(quote)
    return bool(q) and q in _norm(full_text)


def extract_prompt(chunk: TextChunk, total_chunks: int, title: str) -> str:
    return f"""Read this paper chunk and extract scientific evolution events.

This is an independent paper-reading pass. You are NOT validating a candidate answer.

Paper title:
{title}

Rules:
1. Extract only events explicitly supported by this chunk.
2. Prefer events that describe a research process: problem, hypothesis, design decision, computational screen, wet experiment, failed/partial result, analysis, revision, validation.
3. Ignore generic background unless it explains the research problem or constraints.
4. Use short exact quotes copied from this chunk.
5. Keep each quote under 240 characters.
6. Return at most 8 events for this chunk. Keep only the most important process events.
7. Use simple JSON strings. Do not include Markdown tables or multiline quotes.
8. Output valid JSON only.

Expected JSON:
{{
  "chunk_id": "{chunk.chunk_id}",
  "events": [
    {{
      "event_id": "C001_E01",
      "event_type": "problem|hypothesis|design|computation|experiment|analysis|revision|validation|failure|limitation",
      "stage_order_hint": 1,
      "summary": "",
      "methods_or_tools": [],
      "entities": [],
      "numbers_or_metrics": [],
      "exact_quotes": []
    }}
  ],
  "negative_or_failed_findings": [],
  "section_markers": [],
  "chunk_relevance": "high|medium|low|none"
}}

Chunk metadata:
{json.dumps(asdict(chunk) | {"total_chunks": total_chunks}, ensure_ascii=False, indent=2)}
"""


def normalize_extract(raw: dict[str, Any], chunk: TextChunk, full_text: str) -> dict[str, Any]:
    events = []
    invalid_quotes = 0
    for idx, item in enumerate(raw.get("events") or [], start=1):
        if not isinstance(item, dict):
            continue
        quotes = [str(q)[:260] for q in item.get("exact_quotes", []) if isinstance(q, str)]
        valid_quotes = [q for q in quotes if quote_present(q, full_text)]
        invalid_quotes += max(0, len(quotes) - len(valid_quotes))
        events.append(
            {
                "event_id": str(item.get("event_id") or f"{chunk.chunk_id}_E{idx:02d}"),
                "event_type": str(item.get("event_type") or "analysis"),
                "stage_order_hint": item.get("stage_order_hint", idx),
                "summary": _clip(item.get("summary", ""), 700),
                "methods_or_tools": item.get("methods_or_tools") if isinstance(item.get("methods_or_tools"), list) else [],
                "entities": item.get("entities") if isinstance(item.get("entities"), list) else [],
                "numbers_or_metrics": item.get("numbers_or_metrics") if isinstance(item.get("numbers_or_metrics"), list) else [],
                "exact_quotes": valid_quotes[:5],
            }
        )
    return {
        "chunk_id": chunk.chunk_id,
        "char_start": chunk.char_start,
        "char_end": chunk.char_end,
        "events": events[:12],
        "negative_or_failed_findings": raw.get("negative_or_failed_findings")
        if isinstance(raw.get("negative_or_failed_findings"), list)
        else [],
        "section_markers": raw.get("section_markers") if isinstance(raw.get("section_markers"), list) else [],
        "chunk_relevance": raw.get("chunk_relevance") if raw.get("chunk_relevance") in {"high", "medium", "low", "none"} else "medium",
        "invalid_quote_count": invalid_quotes,
        "api_usage": raw.get("_api_usage", {}),
    }


def reduce_prompt(case_meta: dict[str, Any], chunk_events: list[dict[str, Any]]) -> str:
    slim_events = []
    for chunk in chunk_events:
        for event in chunk.get("events", []):
            slim = dict(event)
            slim["chunk_id"] = chunk.get("chunk_id")
            slim_events.append(slim)
    return f"""Merge independently extracted paper events into a canonical Sci-Evo storyline.

Rules:
1. Use only the extracted events below.
2. Keep the true paper order as much as possible.
3. Do not invent details absent from event summaries or quotes.
4. Identify the mainline events a good candidate trajectory should cover.
5. Return at most 14 canonical_events. Merge minor details into nearby mainline events.
6. Use simple JSON strings. Do not include Markdown tables or multiline quotes.
7. Output valid JSON only.

Expected JSON:
{{
  "paper_main_problem": "",
  "canonical_events": [
    {{
      "canonical_id": "K01",
      "order": 1,
      "event_type": "problem|hypothesis|design|computation|experiment|analysis|revision|validation|failure|limitation",
      "summary": "",
      "required_for_good_trajectory": true,
      "source_event_ids": [],
      "best_quotes": [],
      "key_entities": [],
      "key_numbers": []
    }}
  ],
  "must_cover_points": [],
  "optional_details": [],
  "paper_not_suitable_reasons": []
}}

Case metadata:
{json.dumps(case_meta, ensure_ascii=False, indent=2)}

Extracted events:
{json.dumps(slim_events, ensure_ascii=False, indent=2)}
"""


def normalize_storyline(raw: dict[str, Any], full_text: str) -> dict[str, Any]:
    events = []
    invalid_quotes = 0
    for idx, item in enumerate(raw.get("canonical_events") or [], start=1):
        if not isinstance(item, dict):
            continue
        quotes = [str(q)[:260] for q in item.get("best_quotes", []) if isinstance(q, str)]
        valid_quotes = [q for q in quotes if quote_present(q, full_text)]
        invalid_quotes += max(0, len(quotes) - len(valid_quotes))
        events.append(
            {
                "canonical_id": str(item.get("canonical_id") or f"K{idx:02d}"),
                "order": int(item.get("order") or idx),
                "event_type": str(item.get("event_type") or "analysis"),
                "summary": _clip(item.get("summary", ""), 800),
                "required_for_good_trajectory": bool(item.get("required_for_good_trajectory", True)),
                "source_event_ids": item.get("source_event_ids") if isinstance(item.get("source_event_ids"), list) else [],
                "best_quotes": valid_quotes[:6],
                "key_entities": item.get("key_entities") if isinstance(item.get("key_entities"), list) else [],
                "key_numbers": item.get("key_numbers") if isinstance(item.get("key_numbers"), list) else [],
            }
        )
    return {
        "paper_main_problem": _clip(raw.get("paper_main_problem", ""), 1200),
        "canonical_events": sorted(events, key=lambda x: x["order"]),
        "must_cover_points": raw.get("must_cover_points") if isinstance(raw.get("must_cover_points"), list) else [],
        "optional_details": raw.get("optional_details") if isinstance(raw.get("optional_details"), list) else [],
        "paper_not_suitable_reasons": raw.get("paper_not_suitable_reasons")
        if isinstance(raw.get("paper_not_suitable_reasons"), list)
        else [],
        "invalid_quote_count": invalid_quotes,
        "api_usage": raw.get("_api_usage", {}),
    }


def audit_prompt(
    *,
    case_summary: dict[str, Any],
    storyline: dict[str, Any],
    rule_audit: dict[str, Any] | None,
) -> str:
    return f"""Evaluate this candidate Sci-Evo trajectory against the independent full-paper storyline.

Important distinction:
- This is a LOCAL TEST. Do not generate replacement data.
- Judge the candidate rigorously so engineers can improve code.

Evaluation rules:
1. A step is "supported" only if the independent storyline contains the same action and result, or a directly equivalent one.
2. Mark "partial" if the step has a correct core but overclaims metrics, methods, entities, causality, or next-step reasoning.
3. Mark "unsupported" if the action/result is not present in the paper storyline.
4. Mark "wrong_order" when the candidate reverses the research process in a meaningful way.
5. Mark missing mainline events if the candidate skips events required for a good trajectory.
6. Penalize vague summary-style steps that do not capture decision/reason/observation.
7. Consider code rule audit findings, but do not blindly trust them.
8. The independent storyline is a compressed test oracle and may omit fine-grained details.
9. If a candidate step is a fine-grained but scientifically meaningful paper detail, and its own exact evidence quote supports it, do NOT mark it unsupported merely because it is absent from canonical_events. Mark it "supported" with low severity note, unless it contradicts the storyline or displaces a required mainline event.
10. Extra supported detail is not a defect; missing required mainline events, wrong causal links, invented metrics, and unsupported experiments are defects.
11. Return exactly one step_audits item per candidate step.
12. Return at most 8 missing_mainline_events.
13. Use simple JSON strings. Do not include Markdown tables or multiline quotes.
14. Output valid JSON only.

Expected JSON:
{{
  "case_id": "",
  "dimension_scores": {{
    "factuality": 0.0,
    "mainline_completeness": 0.0,
    "trajectory_coherence": 0.0,
    "evidence_grounding": 0.0,
    "dataset_value": 0.0
  }},
  "step_audits": [
    {{
      "step_index": 1,
      "verdict": "supported|partial|unsupported|wrong_order|not_sci_evo",
      "severity": "none|low|medium|high",
      "matched_canonical_ids": [],
      "problem": "",
      "code_fix_hint": "",
      "evidence_need": ""
    }}
  ],
  "missing_mainline_events": [
    {{
      "canonical_id": "K01",
      "severity": "low|medium|high",
      "why_it_matters": "",
      "code_fix_hint": ""
    }}
  ],
  "systemic_error_tags": [],
  "final_verdict": "pass|repair|fail",
  "one_sentence_summary": ""
}}

Independent full-paper storyline:
{json.dumps(storyline, ensure_ascii=False, indent=2)}

Candidate case:
{json.dumps(case_summary, ensure_ascii=False, indent=2)}

Code rule audit:
{json.dumps(rule_audit or {}, ensure_ascii=False, indent=2)}
"""


def normalize_audit(raw: dict[str, Any], case: dict[str, Any]) -> dict[str, Any]:
    scores = raw.get("dimension_scores") if isinstance(raw.get("dimension_scores"), dict) else {}
    norm_scores = {}
    for key in ["factuality", "mainline_completeness", "trajectory_coherence", "evidence_grounding", "dataset_value"]:
        try:
            norm_scores[key] = round(max(0.0, min(1.0, float(scores.get(key, 0)))), 3)
        except Exception:
            norm_scores[key] = 0.0
    steps = []
    seen = set()
    for item in raw.get("step_audits") or []:
        if not isinstance(item, dict):
            continue
        try:
            idx = int(item.get("step_index"))
        except Exception:
            continue
        seen.add(idx)
        verdict = item.get("verdict")
        if verdict not in {"supported", "partial", "unsupported", "wrong_order", "not_sci_evo"}:
            verdict = "partial"
        severity = item.get("severity")
        if severity not in {"none", "low", "medium", "high"}:
            severity = "none" if verdict == "supported" else "medium"
        steps.append(
            {
                "step_index": idx,
                "verdict": verdict,
                "severity": severity,
                "matched_canonical_ids": item.get("matched_canonical_ids")
                if isinstance(item.get("matched_canonical_ids"), list)
                else [],
                "problem": _clip(item.get("problem", ""), 900),
                "code_fix_hint": _clip(item.get("code_fix_hint", ""), 900),
                "evidence_need": _clip(item.get("evidence_need", ""), 900),
            }
        )
    for step in case.get("evolution_trajectory") or []:
        idx = int(step.get("step_index") or 0)
        if idx and idx not in seen:
            steps.append(
                {
                    "step_index": idx,
                    "verdict": "partial",
                    "severity": "medium",
                    "matched_canonical_ids": [],
                    "problem": "AI audit omitted this step; treat as uncertain.",
                    "code_fix_hint": "Rerun evaluator or inspect manually.",
                    "evidence_need": "",
                }
            )
    missing = []
    for item in raw.get("missing_mainline_events") or []:
        if isinstance(item, dict):
            severity = item.get("severity")
            if severity not in {"low", "medium", "high"}:
                severity = "medium"
            missing.append(
                {
                    "canonical_id": str(item.get("canonical_id", "")),
                    "severity": severity,
                    "why_it_matters": _clip(item.get("why_it_matters", ""), 900),
                    "code_fix_hint": _clip(item.get("code_fix_hint", ""), 900),
                }
            )
    verdict = raw.get("final_verdict") if raw.get("final_verdict") in {"pass", "repair", "fail"} else "repair"
    return {
        "case_id": case.get("case_id", ""),
        "dimension_scores": norm_scores,
        "step_audits": sorted(steps, key=lambda x: x["step_index"]),
        "missing_mainline_events": missing,
        "systemic_error_tags": raw.get("systemic_error_tags") if isinstance(raw.get("systemic_error_tags"), list) else [],
        "final_verdict": verdict,
        "one_sentence_summary": _clip(raw.get("one_sentence_summary", ""), 1000),
        "api_usage": raw.get("_api_usage", {}),
    }


def redteam_prompt(case_summary: dict[str, Any], storyline: dict[str, Any], audit: dict[str, Any]) -> str:
    return f"""Red-team this local test result.

Look for severe mistakes the initial audit may have missed.
Focus on:
- unsupported experiments/results,
- missing central paper stages,
- wrong causality or step order,
- evidence that seems too weak for a claimed metric or mutation,
- non-Sci-Evo summary disguised as trajectory.

Do not propose full replacement data. Output valid JSON only.
Return at most 6 missed_blockers. Use simple JSON strings only.

Expected JSON:
{{
  "missed_blockers": [
    {{
      "issue": "",
      "severity": "medium|high",
      "affected_steps": [],
      "code_fix_hint": ""
    }}
  ],
  "audit_reliability": 0.0,
  "override_verdict": "none|repair|fail",
  "summary": ""
}}

Independent storyline:
{json.dumps(storyline, ensure_ascii=False, indent=2)}

Candidate case:
{json.dumps(case_summary, ensure_ascii=False, indent=2)}

Initial audit:
{json.dumps(audit, ensure_ascii=False, indent=2)}
"""


def normalize_redteam(raw: dict[str, Any]) -> dict[str, Any]:
    blockers = []
    for item in raw.get("missed_blockers") or []:
        if isinstance(item, dict):
            severity = item.get("severity")
            if severity not in {"medium", "high"}:
                severity = "medium"
            blockers.append(
                {
                    "issue": _clip(item.get("issue", ""), 900),
                    "severity": severity,
                    "affected_steps": item.get("affected_steps") if isinstance(item.get("affected_steps"), list) else [],
                    "code_fix_hint": _clip(item.get("code_fix_hint", ""), 900),
                }
            )
    try:
        reliability = round(max(0.0, min(1.0, float(raw.get("audit_reliability", 0)))), 3)
    except Exception:
        reliability = 0.5
    override = raw.get("override_verdict")
    if override not in {"none", "repair", "fail"}:
        override = "none"
    return {
        "missed_blockers": blockers,
        "audit_reliability": reliability,
        "override_verdict": override,
        "summary": _clip(raw.get("summary", ""), 1000),
        "api_usage": raw.get("_api_usage", {}),
    }


def deterministic_gate(
    *,
    audit: dict[str, Any],
    redteam: dict[str, Any] | None,
    chunk_reviews: list[dict[str, Any]],
    storyline: dict[str, Any],
) -> dict[str, Any]:
    step_audits = audit.get("step_audits", [])
    missing = audit.get("missing_mainline_events", [])
    scores = audit.get("dimension_scores", {})
    severe_verdicts = {"unsupported", "wrong_order", "not_sci_evo"}
    high_step_issues = [
        s
        for s in step_audits
        if s.get("severity") == "high" or (s.get("verdict") in severe_verdicts and s.get("severity") in {"medium", "high"})
    ]
    medium_step_issues = [
        s
        for s in step_audits
        if s.get("severity") == "medium"
        or (s.get("verdict") == "partial" and s.get("severity") in {"low", "medium"})
    ]
    high_missing = [m for m in missing if m.get("severity") == "high"]
    medium_missing = [m for m in missing if m.get("severity") == "medium"]
    red_blockers = []
    if redteam:
        red_blockers = [b for b in redteam.get("missed_blockers", []) if b.get("severity") == "high"]
    invalid_quote_count = sum(int(c.get("invalid_quote_count") or 0) for c in chunk_reviews)
    invalid_quote_count += int(storyline.get("invalid_quote_count") or 0)
    minimum_score = min(float(scores.get(k, 0.0)) for k in scores) if scores else 0.0
    avg_score = round(sum(float(v) for v in scores.values()) / max(len(scores), 1), 3)

    reasons = []
    decision = "pass"
    if high_step_issues:
        decision = "fail" if len(high_step_issues) >= 2 else "repair"
        reasons.append(f"high_step_issues={len(high_step_issues)}")
    if high_missing:
        decision = "repair" if decision == "pass" else decision
        reasons.append(f"high_missing_events={len(high_missing)}")
    if red_blockers:
        decision = "fail" if len(red_blockers) >= 2 else "repair"
        reasons.append(f"redteam_high_blockers={len(red_blockers)}")
    if minimum_score < 0.72:
        decision = "repair" if decision == "pass" else decision
        reasons.append(f"min_dimension_score={minimum_score}")
    if avg_score < 0.78:
        decision = "repair" if decision == "pass" else decision
        reasons.append(f"avg_dimension_score={avg_score}")
    evaluator_warnings = []
    if invalid_quote_count > 0:
        evaluator_warnings.append(f"ai_invalid_quotes={invalid_quote_count}")
    if medium_step_issues or medium_missing:
        reasons.append(f"medium_step_or_missing_issues={len(medium_step_issues) + len(medium_missing)}")

    return {
        "gate_decision": decision,
        "gate_reasons": reasons or ["all_required_gates_passed"],
        "avg_dimension_score": avg_score,
        "min_dimension_score": minimum_score,
        "high_step_issue_count": len(high_step_issues),
        "medium_step_issue_count": len(medium_step_issues),
        "high_missing_count": len(high_missing),
        "medium_missing_count": len(medium_missing),
        "redteam_high_blockers": len(red_blockers),
        "ai_invalid_quote_count": invalid_quote_count,
        "evaluator_warnings": evaluator_warnings,
    }


def run_fullpaper_eval(
    *,
    client: DeepSeekClient,
    case: dict[str, Any],
    full_text: str,
    rule_audit: dict[str, Any] | None = None,
    chunk_chars: int = 18000,
    overlap: int = 900,
    redteam: bool = True,
) -> dict[str, Any]:
    title = case.get("source", {}).get("title", "")
    chunks = split_full_text(full_text, chunk_chars=chunk_chars, overlap=overlap)
    chunk_reviews = []
    for chunk in chunks:
        raw = client.chat_json(
            system_prompt=EXTRACT_SYSTEM,
            user_prompt=extract_prompt(chunk, len(chunks), title),
            temperature=0.0,
            max_tokens=4096,
        )
        chunk_reviews.append(normalize_extract(raw, chunk, full_text))

    case_meta = {"case_id": case.get("case_id", ""), "title": title, "source": case.get("source", {})}
    raw_story = client.chat_json(
        system_prompt=REDUCE_SYSTEM,
        user_prompt=reduce_prompt(case_meta, chunk_reviews),
        temperature=0.0,
        max_tokens=8192,
    )
    storyline = normalize_storyline(raw_story, full_text)
    case_summary = compact_case(case)
    raw_audit = client.chat_json(
        system_prompt=AUDIT_SYSTEM,
        user_prompt=audit_prompt(case_summary=case_summary, storyline=storyline, rule_audit=rule_audit),
        temperature=0.0,
        max_tokens=8192,
    )
    audit = normalize_audit(raw_audit, case)
    red = None
    if redteam:
        raw_red = client.chat_json(
            system_prompt=REDTEAM_SYSTEM,
            user_prompt=redteam_prompt(case_summary, storyline, audit),
            temperature=0.0,
            max_tokens=4096,
        )
        red = normalize_redteam(raw_red)
    gate = deterministic_gate(audit=audit, redteam=red, chunk_reviews=chunk_reviews, storyline=storyline)
    return {
        "case_id": case.get("case_id", ""),
        "doc_no": str(case.get("case_id", "")).split("_")[-1].zfill(4),
        "title": title,
        "coverage": {
            "full_text_chars": len(full_text),
            "chunk_count": len(chunks),
            "chunk_chars": chunk_chars,
            "overlap": overlap,
            "events_extracted": sum(len(c.get("events", [])) for c in chunk_reviews),
        },
        "storyline": storyline,
        "audit": audit,
        "redteam": red,
        "gate": gate,
        "chunk_reviews": chunk_reviews,
    }

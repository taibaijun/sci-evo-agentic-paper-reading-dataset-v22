"""Schema normalization, validation, and scoring for Sci-Evo cases."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
import re


PHASES = {"hypothesis", "design", "simulation", "experiment", "analysis", "revision", "validation"}
ACTION_TYPES = {"dry_experiment", "wet_experiment", "analysis", "literature_reasoning"}
RESULT_STATUSES = {"success", "failure", "partial", "inconclusive"}


def ensure_list(value: Any) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def normalize_case(case: dict[str, Any], *, doc_no: str, source: dict[str, Any]) -> dict[str, Any]:
    case = dict(case or {})
    # The model may copy a schema example or reuse an ID across documents.
    # Force a deterministic ID from the MinerU document number for full-run safety.
    case["case_id"] = f"sci_evo_{doc_no}"
    case["dataset_type"] = "Sci-Evo"
    case["domain"] = case.get("domain") or "unknown"

    src = dict(case.get("source") or {})
    src.setdefault("title", source.get("title", ""))
    src.setdefault("doi", source.get("doi", ""))
    src.setdefault("url", f"https://doi.org/{source.get('doi')}" if source.get("doi") else "")
    src.setdefault("license", source.get("license", ""))
    src.setdefault("publication_date", "")
    src.setdefault("raw_file", source.get("pdf_name", ""))
    src.setdefault("mineru_md", source.get("mineru_md", ""))
    src.setdefault("combined_md", source.get("combined_md", ""))
    case["source"] = src

    initial = dict(case.get("initial_request") or {})
    for key in ["research_problem", "target_object", "known_context"]:
        initial.setdefault(key, "unknown")
    for key in ["constraints", "input_data", "quantifiable_goals"]:
        initial[key] = ensure_list(initial.get(key))
    case["initial_request"] = initial

    trajectory = ensure_list(case.get("evolution_trajectory"))
    normalized_steps = []
    for i, step in enumerate(trajectory, start=1):
        if not isinstance(step, dict):
            continue
        item = dict(step)
        item["step_index"] = int(item.get("step_index") or i)
        if item.get("phase") not in PHASES:
            item["phase"] = "analysis"
        if item.get("action_type") not in ACTION_TYPES:
            item["action_type"] = "analysis"
        if item.get("result_status") not in RESULT_STATUSES:
            item["result_status"] = "inconclusive"
        for key in [
            "state_before",
            "gap_or_uncertainty",
            "hypothesis",
            "decision",
            "observation",
            "next_step_reason",
        ]:
            if not item.get(key):
                item[key] = "unknown"
        tool = item.get("tool_or_method") if isinstance(item.get("tool_or_method"), dict) else {}
        tool.setdefault("name", "unknown")
        tool.setdefault("version", "")
        tool.setdefault("category", "")
        item["tool_or_method"] = tool
        if not isinstance(item.get("parameters"), dict):
            item["parameters"] = {}
        evidence = []
        for ev in ensure_list(item.get("evidence")):
            if not isinstance(ev, dict):
                continue
            evidence.append(
                {
                    "evidence_id": ev.get("evidence_id", ""),
                    "source_file": ev.get("source_file", src.get("combined_md", "")),
                    "section": ev.get("section", ""),
                    "quote_or_span": ev.get("quote_or_span", ""),
                }
            )
        item["evidence"] = evidence
        normalized_steps.append(item)
    case["evolution_trajectory"] = normalized_steps

    success = dict(case.get("success_verification") or {})
    success["validation_methods"] = ensure_list(success.get("validation_methods"))
    success["metrics"] = ensure_list(success.get("metrics"))
    success.setdefault("final_conclusion", "unknown")
    success["limitations"] = ensure_list(success.get("limitations"))
    case["success_verification"] = success

    qc = dict(case.get("quality_control") or {})
    qc.setdefault("traceable", True)
    qc["human_reviewed"] = bool(qc.get("human_reviewed", False))
    qc["risk_notes"] = ensure_list(qc.get("risk_notes"))
    case["quality_control"] = qc
    case["quality_control"]["evidence_coverage"] = evidence_coverage(case)
    case["quality_control"]["auto_quality_score"] = quality_score(case)
    return case


def evidence_coverage(case: dict[str, Any]) -> float:
    steps = case.get("evolution_trajectory") or []
    if not steps:
        return 0.0
    covered = 0
    for step in steps:
        evidence = step.get("evidence") or []
        if any((ev.get("quote_or_span") or "").strip() for ev in evidence if isinstance(ev, dict)):
            covered += 1
    return round(covered / len(steps), 3)


def quality_score(case: dict[str, Any]) -> float:
    steps = case.get("evolution_trajectory") or []
    score = 0.0
    score += min(len(steps), 8) * 6.0
    score += evidence_coverage(case) * 25.0
    metrics = case.get("success_verification", {}).get("metrics") or []
    score += min(len(metrics), 6) * 3.0
    statuses = {s.get("result_status") for s in steps if isinstance(s, dict)}
    if statuses & {"failure", "partial", "inconclusive"}:
        score += 7.0
    if case.get("success_verification", {}).get("limitations"):
        score += 5.0
    src = case.get("source", {})
    if src.get("doi"):
        score += 3.0
    if src.get("license"):
        score += 2.0
    return round(min(score, 100.0), 2)


def validate_case(case: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for key in ["case_id", "dataset_type", "domain", "source", "initial_request", "evolution_trajectory"]:
        if key not in case:
            errors.append(f"missing root key: {key}")
    if case.get("dataset_type") != "Sci-Evo":
        errors.append("dataset_type must be Sci-Evo")
    steps = case.get("evolution_trajectory") or []
    if not isinstance(steps, list) or len(steps) < 2:
        errors.append("evolution_trajectory should contain at least 2 steps")
    for idx, step in enumerate(steps, start=1):
        if not isinstance(step, dict):
            errors.append(f"step {idx} is not an object")
            continue
        if not step.get("decision"):
            errors.append(f"step {idx} missing decision")
        if not step.get("observation"):
            errors.append(f"step {idx} missing observation")
        if step.get("phase") not in PHASES:
            errors.append(f"step {idx} invalid phase")
        if step.get("action_type") not in ACTION_TYPES:
            errors.append(f"step {idx} invalid action_type")
    return errors


def _squash_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip().lower()


def validate_evidence_quotes(case: dict[str, Any], context: dict[str, Any] | None) -> list[str]:
    """Check that short evidence quotes can be traced to retrieved snippets."""

    if not context:
        return ["missing context for evidence validation"]
    snippets = {
        item.get("evidence_id"): _squash_ws(item.get("text", ""))
        for item in context.get("evidence_snippets", [])
        if isinstance(item, dict)
    }
    errors: list[str] = []
    for step in case.get("evolution_trajectory") or []:
        step_index = step.get("step_index")
        for ev in step.get("evidence") or []:
            if not isinstance(ev, dict):
                continue
            evidence_id = ev.get("evidence_id", "")
            quote = _squash_ws(ev.get("quote_or_span", ""))
            if not quote:
                errors.append(f"step {step_index} evidence {evidence_id} has empty quote")
                continue
            snippet_text = snippets.get(evidence_id)
            if not snippet_text:
                errors.append(f"step {step_index} references unknown evidence_id {evidence_id}")
                continue
            if quote not in snippet_text:
                short_quote = quote[:120]
                errors.append(f"step {step_index} quote not found in {evidence_id}: {short_quote}")
    return errors


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-zA-Z0-9α-ωΑ-ΩμΔδββγ]+", _squash_ws(text)))


def _candidate_spans(text: str) -> list[str]:
    cleaned = re.sub(r"\s+", " ", text or "").strip()
    parts = re.split(r"(?<=[.!?;])\s+|\s{2,}", cleaned)
    spans: list[str] = []
    for part in parts:
        part = part.strip()
        if 30 <= len(part) <= 260:
            spans.append(part)
        elif len(part) > 260:
            for start in range(0, len(part), 220):
                piece = part[start : start + 240].strip()
                if len(piece) >= 30:
                    spans.append(piece)
    if not spans and cleaned:
        spans.append(cleaned[:240].strip())
    return spans


def repair_evidence_quotes(case: dict[str, Any], context: dict[str, Any] | None) -> int:
    """Replace non-exact evidence quotes with exact spans from the cited snippet."""

    if not context:
        return 0
    snippets = {
        item.get("evidence_id"): item.get("text", "")
        for item in context.get("evidence_snippets", [])
        if isinstance(item, dict)
    }
    repair_count = 0
    for step in case.get("evolution_trajectory") or []:
        for ev in step.get("evidence") or []:
            if not isinstance(ev, dict):
                continue
            evidence_id = ev.get("evidence_id", "")
            snippet_text = snippets.get(evidence_id, "")
            quote = ev.get("quote_or_span", "") or ""
            if not snippet_text:
                continue
            if _squash_ws(quote) and _squash_ws(quote) in _squash_ws(snippet_text):
                continue
            quote_tokens = _tokens(quote)
            best_span = ""
            best_score = -1.0
            for span in _candidate_spans(snippet_text):
                span_tokens = _tokens(span)
                if not span_tokens:
                    continue
                overlap = len(quote_tokens & span_tokens)
                score = overlap / max(len(quote_tokens), 1)
                score += overlap / max(len(span_tokens), 1) * 0.25
                if score > best_score:
                    best_score = score
                    best_span = span
            if best_span:
                ev["quote_or_span"] = best_span
                repair_count += 1
    if repair_count:
        qc = case.setdefault("quality_control", {})
        notes = qc.setdefault("risk_notes", [])
        if isinstance(notes, list):
            notes.append(f"auto_repaired_evidence_quotes={repair_count}")
    return repair_count


def load_cases_from_dir(cases_dir: Path) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for path in sorted(cases_dir.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        cases.append(data["case"] if "case" in data else data)
    return cases

def write_dataset_jsonl(path: Path, cases: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for case in cases:
            f.write(json.dumps(case, ensure_ascii=False, sort_keys=True) + "\n")

"""Agentic paper-reading generation for Sci-Evo cases.

The V22 pipeline makes the LLM act as a controlled paper-reading agent:
it plans what to read, builds section memories, extracts paper-native
events, constructs an event graph, drafts a Sci-Evo trajectory, critiques
it, and performs at most one evidence-grounded revision.
"""

from __future__ import annotations

import json
import copy
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .corpus import split_sections
from .deepseek_client import DeepSeekClient
from .evidence_index import check_case_evidence, is_bad_quote, normalize_text
from .prompts import SCHEMA_EXAMPLE
from .schema import evidence_coverage, normalize_case, quality_score, validate_case


PLAN_SYSTEM = """You are a scientific paper-reading planner.
You plan how to read a paper to reconstruct its research evolution trajectory.
Output valid JSON only. Do not invent paper content.
"""

GIST_SYSTEM = """You are a scientific paper reader.
You read selected paper sections and create a compact memory of the research process.
Output valid JSON only. Use only provided text.
"""

EVENT_SYSTEM = """You are a strict scientific process reader.
You read one chunk of a paper and extract only paper-native research evolution events.
You do not see any candidate answer. Output valid JSON only.
"""

GRAPH_SYSTEM = """You are a scientific storyline graph builder.
You merge paper-native events into an ordered event graph with evidence.
Output valid JSON only. Use only provided events and evidence IDs.
"""

DRAFT_SYSTEM = """You are a senior Sci-Evo dataset curator.
You draft one evidence-grounded Sci-Evo JSON case from an event graph.
Output valid JSON only. Use only provided evidence IDs and quotes.
"""

CRITIC_SYSTEM = """You are a skeptical Sci-Evo self-critic.
You inspect the candidate against the event graph and evidence bank.
Output valid JSON only. Do not write a replacement case.
"""

REVISE_SYSTEM = """You are a conservative Sci-Evo dataset editor.
You revise one candidate case using critic findings and an evidence bank.
Output valid JSON only. Do not invent facts.
"""


READING_TERMS = (
    "abstract",
    "introduction",
    "background",
    "result",
    "discussion",
    "method",
    "material",
    "conclusion",
    "figure",
    "table",
)

TEXT_FIELDS = (
    "state_before",
    "gap_or_uncertainty",
    "hypothesis",
    "decision",
    "observation",
    "next_step_reason",
)

GENERATION_ONLY_STEP_KEYS = {
    "event_ids",
    "source_event_ids",
    "supporting_event_ids",
    "confidence",
    "critic_notes",
}

ENTITY_RE = re.compile(r"\b[A-Z][0-9]{1,4}[A-Z]\b|\b[A-Z]{1,6}[-_][0-9]{1,4}\b|\b[A-Z][a-z]{2}\d+[A-Z][a-z]{2}\b")
NUMBER_RE = re.compile(r"(?<![A-Za-z])[-+]?\d+(?:[.,]\d+)?(?:\s?(?:%|fold|x|uM|mM|nM|C|bp|kb|h|min|s|M\^-1|s\^-1))?")
WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9_-]{2,}")
SPECIFIC_METRIC_RE = re.compile(
    r"(?i)\b(?:fold|variant|variants|mutant|mutants|mutation|mutations|library|libraries|screen|screened|"
    r"selected|sorted|enrichment|activity|specific activity|conversion|yield|selectivity|fitness|"
    r"kcat|k_cat|km|k_m|u/mg|events|hit rate|round|validated|validation)\b"
)


@dataclass
class AgentChunk:
    chunk_id: str
    char_start: int
    char_end: int
    text: str


@dataclass
class AgentRunConfig:
    model: str = "deepseek-v4-pro"
    base_url: str = "https://api.deepseek.com"
    plan_temperature: float = 0.0
    extract_temperature: float = 0.0
    draft_temperature: float = 0.05
    max_tokens: int = 8192
    chunk_chars: int = 18000
    chunk_overlap: int = 900
    max_gist_sections: int = 14
    max_section_chars: int = 6500
    max_reading_chars: int = 72000
    max_events_per_chunk: int = 8
    max_revision_rounds: int = 1


@dataclass
class StageCall:
    stage: str
    api_usage: dict[str, Any] = field(default_factory=dict)
    api_model: str = ""
    api_finish_reason: str = ""


def compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


def clip(text: Any, limit: int) -> str:
    value = str(text or "")
    return value if len(value) <= limit else value[:limit] + "\n...[clipped]..."


def source_from_record(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": record.get("title", ""),
        "doi": record.get("doi", ""),
        "license": record.get("license", ""),
        "pdf_name": record.get("pdf_name", ""),
        "combined_md": record.get("combined_md", ""),
        "mineru_md": record.get("mineru_md", ""),
    }


def section_outline(full_text: str) -> list[dict[str, Any]]:
    sections = split_sections(full_text)
    outline = []
    for idx, section in enumerate(sections, start=1):
        text = str(section.get("text", ""))
        outline.append(
            {
                "section_index": idx,
                "heading": section.get("heading", ""),
                "level": section.get("level", 0),
                "char_start": section.get("start", 0),
                "char_end": section.get("end", 0),
                "char_count": len(text),
                "preview": clip(normalize_text(text), 420),
            }
        )
    return outline


def split_agent_chunks(full_text: str, *, chunk_chars: int, overlap: int) -> list[AgentChunk]:
    chunks: list[AgentChunk] = []
    offset = 0
    idx = 1
    while offset < len(full_text):
        end = min(len(full_text), offset + chunk_chars)
        chunks.append(AgentChunk(f"C{idx:03d}", offset, end, full_text[offset:end]))
        if end >= len(full_text):
            break
        offset = max(0, end - overlap)
        idx += 1
    return chunks


def quote_window(full_text: str, start: int, end: int, *, limit: int = 520) -> tuple[int, int, str]:
    left = max(0, start - limit // 2)
    right = min(len(full_text), end + limit // 2)
    sentence_left = max(full_text.rfind(".", 0, start), full_text.rfind("\n", 0, start))
    sentence_right_candidates = [pos for pos in (full_text.find(".", end), full_text.find("\n", end)) if pos >= 0]
    sentence_right = min(sentence_right_candidates) + 1 if sentence_right_candidates else right
    if 0 <= sentence_left and sentence_right - sentence_left <= limit:
        left = sentence_left + 1
        right = sentence_right
    elif right - left > limit:
        left = max(0, start - limit // 3)
        right = min(len(full_text), left + limit)
    quote = full_text[left:right].strip()
    return left, right, re.sub(r"\s+", " ", quote)


def augment_specific_evidence_bank(
    evidence_bank: list[dict[str, Any]],
    full_text: str,
    *,
    doc_no: str,
    source_file: str,
    max_items: int = 36,
) -> int:
    """Add deterministic evidence snippets for specific variants and metrics.

    The agent event extractor is deliberately compact. This bank expansion gives
    later quote alignment a way to ground details such as mutation names,
    fold-improvements, screened counts, and final activity values without asking
    the model to reread the full paper during repair.
    """

    existing_quotes = {normalize_text(str(item.get("quote", ""))) for item in evidence_bank}
    existing_ids = {str(item.get("evidence_id", "")) for item in evidence_bank}
    matches: list[tuple[float, int, int, str]] = []
    for regex, base_score in ((ENTITY_RE, 40.0), (NUMBER_RE, 16.0)):
        for match in regex.finditer(full_text):
            start, end = match.span()
            left, right, quote = quote_window(full_text, start, end)
            if len(quote) < 30 or is_bad_quote(quote):
                continue
            quote_norm = normalize_text(quote)
            if quote_norm in existing_quotes:
                continue
            token_count = len(extract_entities(quote)) * 6 + len(extract_numbers(quote)) * 2
            keyword_bonus = 12 if SPECIFIC_METRIC_RE.search(quote) else 0
            score = base_score + token_count + keyword_bonus
            if keyword_bonus or extract_entities(quote):
                matches.append((score, left, right, quote))
    added = 0
    seen_quotes = set(existing_quotes)
    for _score, left, right, quote in sorted(matches, reverse=True):
        quote_norm = normalize_text(quote)
        if quote_norm in seen_quotes:
            continue
        while True:
            eid = f"EV_AUTO_{added + 1:03d}"
            if eid not in existing_ids:
                break
            added += 1
        evidence_bank.append(
            {
                "evidence_id": eid,
                "source_file": source_file or f"docs/{doc_no}/combined.md",
                "section": "auto_specific",
                "char_start": left,
                "char_end": right,
                "quote": quote,
            }
        )
        existing_ids.add(eid)
        seen_quotes.add(quote_norm)
        added += 1
        if added >= max_items:
            break
    return added


def call_json(
    client: DeepSeekClient,
    state: dict[str, Any],
    *,
    stage: str,
    system_prompt: str,
    user_prompt: str,
    temperature: float,
    max_tokens: int,
) -> dict[str, Any]:
    raw = client.chat_json(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    state.setdefault("stage_calls", []).append(
        asdict(
            StageCall(
                stage=stage,
                api_usage=raw.get("_api_usage", {}),
                api_model=raw.get("_api_model", ""),
                api_finish_reason=raw.get("_api_finish_reason", ""),
            )
        )
    )
    return raw


def plan_prompt(record: dict[str, Any], outline: list[dict[str, Any]]) -> str:
    return f"""Plan how to read this paper for a Sci-Evo trajectory.

Goal:
Find the real research evolution process: problem, constraints, hypotheses, designs, computational or wet experiments, observations, failures/partial results, revisions, validations, and limitations.

Return JSON:
{{
  "reading_goal": "",
  "selected_sections": [
    {{"section_index": 1, "reason": "why this section matters"}}
  ],
  "must_find": [],
  "risk_notes": []
}}

Paper metadata:
{compact_json(source_from_record(record))}

Section outline:
{compact_json(outline)}
"""


def normalize_plan(raw: dict[str, Any], outline: list[dict[str, Any]], *, max_sections: int) -> dict[str, Any]:
    valid_indices = {int(item["section_index"]) for item in outline}
    selected: list[dict[str, Any]] = []
    seen: set[int] = set()
    for item in raw.get("selected_sections") or []:
        if not isinstance(item, dict):
            continue
        try:
            idx = int(item.get("section_index"))
        except Exception:
            continue
        if idx in valid_indices and idx not in seen:
            seen.add(idx)
            selected.append({"section_index": idx, "reason": clip(item.get("reason", ""), 400)})
    for item in outline:
        heading = str(item.get("heading", "")).lower()
        if any(term in heading for term in READING_TERMS):
            idx = int(item["section_index"])
            if idx not in seen:
                seen.add(idx)
                selected.append({"section_index": idx, "reason": "mandatory section for research-process reconstruction"})
    selected = sorted(selected, key=lambda x: x["section_index"])[:max_sections]
    return {
        "reading_goal": clip(raw.get("reading_goal", ""), 1000),
        "selected_sections": selected,
        "must_find": raw.get("must_find") if isinstance(raw.get("must_find"), list) else [],
        "risk_notes": raw.get("risk_notes") if isinstance(raw.get("risk_notes"), list) else [],
    }


def selected_section_payload(
    full_text: str,
    outline: list[dict[str, Any]],
    plan: dict[str, Any],
    *,
    max_section_chars: int,
    max_total_chars: int,
) -> list[dict[str, Any]]:
    by_idx = {int(item["section_index"]): item for item in outline}
    payload = []
    used = 0
    for item in plan.get("selected_sections") or []:
        idx = int(item["section_index"])
        sec = by_idx.get(idx)
        if not sec:
            continue
        start = int(sec["char_start"])
        end = int(sec["char_end"])
        text = full_text[start:end]
        text = text[:max_section_chars]
        if payload and used + len(text) > max_total_chars:
            continue
        payload.append(
            {
                "section_index": idx,
                "heading": sec.get("heading", ""),
                "reason": item.get("reason", ""),
                "char_start": start,
                "char_end": min(end, start + len(text)),
                "text": text,
            }
        )
        used += len(text)
    return payload


def gist_prompt(record: dict[str, Any], plan: dict[str, Any], sections: list[dict[str, Any]]) -> str:
    return f"""Read these selected sections and build paper memory for Sci-Evo generation.

Rules:
1. Use only provided section text.
2. Capture process information, not a generic summary.
3. Note important methods, variants, metrics, negative/partial results, and why the paper moved from one stage to the next.
4. Output valid JSON only.

Return JSON:
{{
  "paper_problem_memory": "",
  "section_gists": [
    {{
      "section_index": 1,
      "heading": "",
      "gist": "",
      "process_signals": [],
      "methods": [],
      "metrics": [],
      "failures_or_limits": []
    }}
  ],
  "global_hypotheses_about_storyline": [],
  "uncertainties_to_resolve": []
}}

Paper metadata:
{compact_json(source_from_record(record))}

Reading plan:
{compact_json(plan)}

Selected sections:
{compact_json(sections)}
"""


def normalize_gists(raw: dict[str, Any]) -> dict[str, Any]:
    gists = []
    for item in raw.get("section_gists") or []:
        if not isinstance(item, dict):
            continue
        gists.append(
            {
                "section_index": item.get("section_index"),
                "heading": str(item.get("heading", ""))[:200],
                "gist": clip(item.get("gist", ""), 1000),
                "process_signals": item.get("process_signals") if isinstance(item.get("process_signals"), list) else [],
                "methods": item.get("methods") if isinstance(item.get("methods"), list) else [],
                "metrics": item.get("metrics") if isinstance(item.get("metrics"), list) else [],
                "failures_or_limits": item.get("failures_or_limits") if isinstance(item.get("failures_or_limits"), list) else [],
            }
        )
    return {
        "paper_problem_memory": clip(raw.get("paper_problem_memory", ""), 1400),
        "section_gists": gists,
        "global_hypotheses_about_storyline": raw.get("global_hypotheses_about_storyline")
        if isinstance(raw.get("global_hypotheses_about_storyline"), list)
        else [],
        "uncertainties_to_resolve": raw.get("uncertainties_to_resolve")
        if isinstance(raw.get("uncertainties_to_resolve"), list)
        else [],
    }


def event_prompt(
    record: dict[str, Any],
    gist_memory: dict[str, Any],
    chunk: AgentChunk,
    total_chunks: int,
    *,
    max_events: int,
) -> str:
    return f"""Extract paper-native research evolution events from this chunk.

This is independent extraction. You do NOT see a candidate dataset answer.

Rules:
1. Extract only events explicitly supported by this chunk.
2. Prefer events that describe process: problem, hypothesis, design, computation, experiment, analysis, revision, validation, failure, limitation.
3. Ignore generic background unless it defines the research problem or constraints.
4. Every event must include at least one exact quote copied from this chunk.
5. Keep each quote under 240 characters.
6. Return at most {max_events} events.
7. Output valid JSON only.

Return JSON:
{{
  "chunk_id": "{chunk.chunk_id}",
  "events": [
    {{
      "event_id": "{chunk.chunk_id}_E01",
      "event_type": "problem|hypothesis|design|computation|experiment|analysis|revision|validation|failure|limitation",
      "order_hint": 1,
      "summary": "",
      "methods_or_tools": [],
      "entities": [],
      "numbers_or_metrics": [],
      "exact_quotes": []
    }}
  ],
  "chunk_relevance": "high|medium|low|none",
  "notes": ""
}}

Paper metadata:
{compact_json(source_from_record(record))}

Current paper memory:
{compact_json(gist_memory)}

Chunk metadata:
{compact_json({"chunk_id": chunk.chunk_id, "chunk_number": int(chunk.chunk_id[1:]), "total_chunks": total_chunks, "char_start": chunk.char_start, "char_end": chunk.char_end})}

Chunk text:
{chunk.text}
"""


def quote_char_range(chunk: AgentChunk, full_text: str, quote: str) -> tuple[int, int] | None:
    if not quote or is_bad_quote(quote):
        return None
    local = chunk.text.find(quote)
    if local >= 0:
        start = chunk.char_start + local
        return start, start + len(quote)
    global_pos = full_text.find(quote)
    if global_pos >= 0:
        return global_pos, global_pos + len(quote)
    return None


def normalize_events(
    raw: dict[str, Any],
    chunk: AgentChunk,
    full_text: str,
    *,
    doc_no: str,
    source_file: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    events = []
    evidence_refs = []
    for idx, item in enumerate(raw.get("events") or [], start=1):
        if not isinstance(item, dict):
            continue
        event_id = str(item.get("event_id") or f"{chunk.chunk_id}_E{idx:02d}")
        event_id = re.sub(r"[^A-Za-z0-9_]", "_", event_id)[:40] or f"{chunk.chunk_id}_E{idx:02d}"
        event_refs = []
        for q_idx, raw_quote in enumerate(item.get("exact_quotes") or [], start=1):
            quote = str(raw_quote or "").strip()
            found = quote_char_range(chunk, full_text, quote)
            if not found:
                continue
            eid = f"EV_{event_id}_{q_idx:02d}"
            ref = {
                "evidence_id": eid,
                "source_file": source_file or f"docs/{doc_no}/combined.md",
                "section": chunk.chunk_id,
                "char_start": found[0],
                "char_end": found[1],
                "quote": quote,
            }
            event_refs.append(ref)
            evidence_refs.append(ref)
        if not event_refs:
            continue
        events.append(
            {
                "event_id": event_id,
                "chunk_id": chunk.chunk_id,
                "event_type": str(item.get("event_type") or "analysis"),
                "order_hint": item.get("order_hint", idx),
                "summary": clip(item.get("summary", ""), 900),
                "methods_or_tools": item.get("methods_or_tools") if isinstance(item.get("methods_or_tools"), list) else [],
                "entities": item.get("entities") if isinstance(item.get("entities"), list) else [],
                "numbers_or_metrics": item.get("numbers_or_metrics") if isinstance(item.get("numbers_or_metrics"), list) else [],
                "evidence_ids": [ref["evidence_id"] for ref in event_refs],
            }
        )
    return (
        {
            "chunk_id": chunk.chunk_id,
            "char_start": chunk.char_start,
            "char_end": chunk.char_end,
            "chunk_relevance": raw.get("chunk_relevance") if raw.get("chunk_relevance") in {"high", "medium", "low", "none"} else "medium",
            "events": events,
            "notes": clip(raw.get("notes", ""), 500),
            "api_usage": raw.get("_api_usage", {}),
        },
        evidence_refs,
    )


def graph_prompt(record: dict[str, Any], gists: dict[str, Any], chunk_events: list[dict[str, Any]], evidence_bank: list[dict[str, Any]]) -> str:
    all_events = []
    for chunk in chunk_events:
        all_events.extend(chunk.get("events") or [])
    slim_evidence = [
        {
            "evidence_id": ev["evidence_id"],
            "section": ev["section"],
            "quote": ev["quote"],
        }
        for ev in evidence_bank
    ]
    return f"""Build an ordered event graph for this paper's Sci-Evo trajectory.

Rules:
1. Use only the extracted events and evidence IDs.
2. Merge duplicate or tiny events into canonical events.
3. Preserve true paper order.
4. Mark the mainline events a good final trajectory must cover.
5. Include failure, partial, revision, or limitation events when they matter.
6. Do not make routine protocol details canonical unless they are the scientific decision being evolved.
7. Prefer 10-14 canonical_events focused on problem, design decisions, experimental rounds, model decisions, failures, key quantitative results, validation, and limitations.
8. Output valid JSON only.

Return JSON:
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
      "evidence_ids": [],
      "key_entities": [],
      "key_numbers": []
    }}
  ],
  "edges": [
    {{
      "source": "K01",
      "target": "K02",
      "relation": "follows|enables|refines|contradicts|validates",
      "reason": ""
    }}
  ],
  "must_cover_points": [],
  "paper_not_suitable_reasons": []
}}

Paper metadata:
{compact_json(source_from_record(record))}

Paper memory:
{compact_json(gists)}

Extracted events:
{compact_json(all_events)}

Evidence bank:
{compact_json(slim_evidence)}
"""


def normalize_graph(raw: dict[str, Any], chunk_events: list[dict[str, Any]], evidence_bank: list[dict[str, Any]]) -> dict[str, Any]:
    event_map = {}
    for chunk in chunk_events:
        for event in chunk.get("events") or []:
            event_map[event["event_id"]] = event
    valid_evidence = {ev["evidence_id"] for ev in evidence_bank}
    canonical = []
    for idx, item in enumerate(raw.get("canonical_events") or [], start=1):
        if not isinstance(item, dict):
            continue
        cid = str(item.get("canonical_id") or f"K{idx:02d}")
        cid = re.sub(r"[^A-Za-z0-9_]", "_", cid)[:30] or f"K{idx:02d}"
        source_ids = [str(x) for x in item.get("source_event_ids") or [] if str(x) in event_map]
        evidence_ids = [str(x) for x in item.get("evidence_ids") or [] if str(x) in valid_evidence]
        if not evidence_ids:
            for sid in source_ids:
                for eid in event_map[sid].get("evidence_ids") or []:
                    if eid in valid_evidence and eid not in evidence_ids:
                        evidence_ids.append(eid)
        if not evidence_ids:
            continue
        canonical.append(
            {
                "canonical_id": cid,
                "order": int(item.get("order") or idx),
                "event_type": str(item.get("event_type") or "analysis"),
                "summary": clip(item.get("summary", ""), 1000),
                "required_for_good_trajectory": bool(item.get("required_for_good_trajectory", True)),
                "source_event_ids": source_ids,
                "evidence_ids": evidence_ids[:6],
                "key_entities": item.get("key_entities") if isinstance(item.get("key_entities"), list) else [],
                "key_numbers": item.get("key_numbers") if isinstance(item.get("key_numbers"), list) else [],
            }
        )
    canonical = sorted(canonical, key=lambda x: x["order"])[:18]
    valid_cids = {item["canonical_id"] for item in canonical}
    edges = []
    for item in raw.get("edges") or []:
        if not isinstance(item, dict):
            continue
        src = str(item.get("source", ""))
        dst = str(item.get("target", ""))
        relation = item.get("relation")
        if src in valid_cids and dst in valid_cids and relation in {"follows", "enables", "refines", "contradicts", "validates"}:
            edges.append({"source": src, "target": dst, "relation": relation, "reason": clip(item.get("reason", ""), 400)})
    return {
        "paper_main_problem": clip(raw.get("paper_main_problem", ""), 1400),
        "canonical_events": canonical,
        "edges": edges,
        "must_cover_points": raw.get("must_cover_points") if isinstance(raw.get("must_cover_points"), list) else [],
        "paper_not_suitable_reasons": raw.get("paper_not_suitable_reasons")
        if isinstance(raw.get("paper_not_suitable_reasons"), list)
        else [],
    }


def draft_prompt(record: dict[str, Any], graph: dict[str, Any], evidence_bank: list[dict[str, Any]]) -> str:
    evidence_payload = [
        {
            "evidence_id": ev["evidence_id"],
            "source_file": ev["source_file"],
            "section": ev["section"],
            "quote": ev["quote"],
        }
        for ev in evidence_bank
    ]
    schema_text = compact_json(SCHEMA_EXAMPLE)
    coverage_requirements = coverage_requirements_payload(graph, evidence_bank)
    return f"""Draft one Sci-Evo case from this event graph.

Rules:
1. Use 5-12 trajectory steps when supported.
2. Every step must be based on one or more canonical events.
3. Every step must have at least one evidence item.
4. Evidence IDs and quotes must be copied exactly from the evidence bank.
5. Do not invent methods, variants, metrics, cell lines, or conclusions.
6. Include failures, partial results, revisions, and limitations when present.
7. If the paper is weakly suitable, still produce the best evidence-grounded candidate and note the risk.
8. Do not replace concrete result/validation events with discussion-only limitations.
9. For every step, add an extra internal field `supporting_event_ids` containing the canonical_id values it covers.
10. The final trajectory must cover all Coverage Requirements below, merging nearby requirements into one step when needed.
11. Output valid JSON only.

Expected JSON shape:
{schema_text}

Paper metadata:
{compact_json(source_from_record(record))}

Event graph:
{compact_json(graph)}

Coverage Requirements:
{compact_json(coverage_requirements)}

Evidence bank:
{compact_json(evidence_payload)}
"""


def evidence_context_from_bank(evidence_bank: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "evidence_snippets": [
            {
                "evidence_id": item["evidence_id"],
                "source_file": item["source_file"],
                "section": item["section"],
                "text": item["quote"],
            }
            for item in evidence_bank
        ]
    }


def evidence_by_id(evidence_bank: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {item["evidence_id"]: item for item in evidence_bank}


def tokens(text: str) -> set[str]:
    return {m.group(0).lower() for m in WORD_RE.finditer(normalize_text(text or ""))}


def best_evidence_for_text(evidence_bank: list[dict[str, Any]], text: str) -> dict[str, Any] | None:
    query = tokens(text)
    if not query:
        return evidence_bank[0] if evidence_bank else None
    best = None
    best_score = -1.0
    for ev in evidence_bank:
        ev_tokens = tokens(ev.get("quote", ""))
        overlap = len(query & ev_tokens)
        score = overlap / max(len(query), 1) + overlap / max(len(ev_tokens), 1) * 0.25
        if score > best_score:
            best_score = score
            best = ev
    return best


def align_case_evidence(case: dict[str, Any], evidence_bank: list[dict[str, Any]], *, doc_no: str, source_file: str) -> int:
    bank = evidence_by_id(evidence_bank)
    repair_count = 0
    for step in case.get("evolution_trajectory") or []:
        aligned = []
        for ev in step.get("evidence") or []:
            if not isinstance(ev, dict):
                continue
            eid = str(ev.get("evidence_id", ""))
            ref = bank.get(eid)
            if not ref:
                ref = best_evidence_for_text(evidence_bank, str(ev.get("quote_or_span", "")) + " " + " ".join(str(step.get(k, "")) for k in TEXT_FIELDS))
            if not ref:
                continue
            quote = ref["quote"]
            if ev.get("quote_or_span") != quote or ev.get("evidence_id") != ref["evidence_id"]:
                repair_count += 1
            aligned.append(
                {
                    "evidence_id": ref["evidence_id"],
                    "source_file": source_file or f"docs/{doc_no}/combined.md",
                    "section": ref.get("section", ""),
                    "quote_or_span": quote,
                }
            )
        if not aligned:
            ref = best_evidence_for_text(evidence_bank, " ".join(str(step.get(k, "")) for k in TEXT_FIELDS))
            if ref:
                aligned.append(
                    {
                        "evidence_id": ref["evidence_id"],
                        "source_file": source_file or f"docs/{doc_no}/combined.md",
                        "section": ref.get("section", ""),
                        "quote_or_span": ref["quote"],
                    }
                )
                repair_count += 1
        step["evidence"] = aligned[:4]
    if repair_count:
        notes = case.setdefault("quality_control", {}).setdefault("risk_notes", [])
        if isinstance(notes, list):
            notes.append(f"v22_quote_align_repaired={repair_count}")
    return repair_count


def strip_generation_only_fields(case: dict[str, Any]) -> None:
    for step in case.get("evolution_trajectory") or []:
        if isinstance(step, dict):
            for key in GENERATION_ONLY_STEP_KEYS:
                step.pop(key, None)


def event_priority(event: dict[str, Any], *, index: int, total: int) -> float:
    event_type = str(event.get("event_type", "")).lower()
    summary = " ".join(
        [
            str(event.get("summary", "")),
            " ".join(str(x) for x in event.get("key_entities", []) or []),
            " ".join(str(x) for x in event.get("key_numbers", []) or []),
        ]
    ).lower()
    type_score = {
        "problem": 7.0,
        "hypothesis": 6.0,
        "design": 7.0,
        "computation": 7.0,
        "experiment": 9.0,
        "analysis": 6.0,
        "revision": 7.0,
        "validation": 9.5,
        "failure": 8.0,
        "limitation": 5.0,
    }.get(event_type, 5.0)
    score = type_score
    if event.get("required_for_good_trajectory", True):
        score += 2.0
    if index == 0:
        score += 5.0
    if index >= max(total - 2, 0):
        score += 3.0
    keyword_weights = {
        "round": 2.0,
        "library": 1.5,
        "screen": 1.5,
        "selected": 1.5,
        "variant": 1.5,
        "mutant": 1.5,
        "validated": 2.0,
        "validation": 2.0,
        "activity": 1.5,
        "yield": 1.5,
        "selectivity": 1.5,
        "enanti": 1.5,
        "fold": 1.5,
        "%": 1.0,
        "failed": 2.0,
        "failure": 2.0,
        "final": 1.5,
        "improved": 1.5,
        "achieved": 1.5,
    }
    for token, weight in keyword_weights.items():
        if token in summary:
            score += weight
    low_level_terms = (
        "primer",
        "gibson",
        "gblocks",
        "pjl1",
        "panox",
        "dpni",
        "benchling",
        "santalucia",
        "384-well",
        "overnight culture",
        "plasmid purification",
        "nadh oxidation",
        "template",
        "protocol",
    )
    if any(term in summary for term in low_level_terms):
        score -= 7.0
    if event_type in {"design", "experiment"} and not re.search(
        r"round|library|screen|selected|variant|mutant|improved|fold|%|validation|validated|failed|fitness|activity|yield|selectivity|top|best",
        summary,
    ):
        score -= 3.0
    if event.get("key_numbers"):
        score += 1.5
    if event.get("key_entities"):
        score += 1.0
    return score


def select_priority_events(graph: dict[str, Any], *, max_events: int = 12) -> list[dict[str, Any]]:
    events = [event for event in graph.get("canonical_events") or [] if isinstance(event, dict)]
    if len(events) <= max_events:
        selected = sorted(events, key=lambda x: int(x.get("order") or 0))
        problem_events = [event for event in selected if str(event.get("event_type", "")).lower() == "problem"]
        if len(problem_events) > 1:
            keep_problem = max(
                problem_events,
                key=lambda event: event_priority(event, index=selected.index(event), total=len(selected)),
            )
            selected = [event for event in selected if str(event.get("event_type", "")).lower() != "problem" or event is keep_problem]
        return selected
    scored = [
        (event_priority(event, index=idx, total=len(events)), idx, event)
        for idx, event in enumerate(events)
    ]
    keep_indices = {0, len(events) - 1}
    for _score, idx, _event in sorted(scored, key=lambda item: item[0], reverse=True):
        keep_indices.add(idx)
        if len(keep_indices) >= max_events:
            break
    selected = [events[idx] for idx in sorted(keep_indices)]
    problem_events = [event for event in selected if str(event.get("event_type", "")).lower() == "problem"]
    if len(problem_events) > 1:
        keep_problem = max(
            problem_events,
            key=lambda event: event_priority(event, index=events.index(event), total=len(events)),
        )
        selected = [event for event in selected if str(event.get("event_type", "")).lower() != "problem" or event is keep_problem]
    return sorted(selected, key=lambda x: int(x.get("order") or 0))


def coverage_requirements_payload(graph: dict[str, Any], evidence_bank: list[dict[str, Any]]) -> list[dict[str, Any]]:
    bank = evidence_by_id(evidence_bank)
    requirements = []
    for event in select_priority_events(graph, max_events=12):
        quotes = []
        for eid in event.get("evidence_ids") or []:
            ref = bank.get(str(eid))
            if ref:
                quotes.append({"evidence_id": ref["evidence_id"], "quote": ref["quote"]})
        requirements.append(
            {
                "canonical_id": event.get("canonical_id", ""),
                "order": event.get("order"),
                "event_type": event.get("event_type", ""),
                "summary": event.get("summary", ""),
                "key_entities": event.get("key_entities", []),
                "key_numbers": event.get("key_numbers", []),
                "evidence": quotes[:4],
            }
        )
    return requirements


def step_text(step: dict[str, Any]) -> str:
    return " ".join(str(step.get(key, "")) for key in TEXT_FIELDS)


def step_evidence_ids(step: dict[str, Any]) -> set[str]:
    return {
        str(ev.get("evidence_id", ""))
        for ev in step.get("evidence") or []
        if isinstance(ev, dict) and ev.get("evidence_id")
    }


def explicit_step_event_ids(step: dict[str, Any]) -> set[str]:
    ids: set[str] = set()
    for key in ("supporting_event_ids", "source_event_ids", "event_ids", "canonical_event_ids"):
        value = step.get(key)
        if isinstance(value, list):
            ids.update(str(item) for item in value if item)
        elif isinstance(value, str):
            ids.update(re.findall(r"\bK\d{1,3}\b", value))
    ids.update(re.findall(r"\bK\d{1,3}\b", json.dumps(step, ensure_ascii=False)))
    return ids


def infer_step_event_ids(step: dict[str, Any], graph: dict[str, Any]) -> set[str]:
    ids = explicit_step_event_ids(step)
    evidence_ids = step_evidence_ids(step)
    text_tokens = tokens(step_text(step))
    step_nums = extract_numbers(step_text(step))
    step_entities = extract_entities(step_text(step))
    for event in graph.get("canonical_events") or []:
        cid = str(event.get("canonical_id", ""))
        event_evidence = {str(eid) for eid in event.get("evidence_ids") or []}
        if cid and evidence_ids & event_evidence:
            ids.add(cid)
            continue
        summary_tokens = tokens(str(event.get("summary", "")))
        if not summary_tokens or not text_tokens:
            continue
        overlap = len(summary_tokens & text_tokens)
        token_score = overlap / max(len(summary_tokens), 1)
        event_nums = {compact_number(str(x)) for x in event.get("key_numbers") or []}
        event_entities = {compact_number(str(x)) for x in event.get("key_entities") or []}
        has_specific_overlap = bool((step_nums & event_nums) or (step_entities & event_entities))
        if token_score >= 0.38 and (has_specific_overlap or overlap >= 5):
            ids.add(cid)
    return ids


def coverage_audit(case: dict[str, Any], graph: dict[str, Any], *, max_events: int = 12) -> dict[str, Any]:
    requirements = select_priority_events(graph, max_events=max_events)
    requirement_ids = [str(event.get("canonical_id", "")) for event in requirements if event.get("canonical_id")]
    covered: dict[str, list[int]] = {cid: [] for cid in requirement_ids}
    step_map = []
    for step in case.get("evolution_trajectory") or []:
        if not isinstance(step, dict):
            continue
        step_index = int(step.get("step_index") or 0)
        ids = infer_step_event_ids(step, graph)
        step_map.append({"step_index": step_index, "covered_event_ids": sorted(ids)})
        for cid in requirement_ids:
            if cid in ids:
                covered.setdefault(cid, []).append(step_index)
    event_by_id = {str(event.get("canonical_id", "")): event for event in requirements}
    missing = []
    for cid in requirement_ids:
        if not covered.get(cid):
            event = event_by_id.get(cid, {})
            missing.append(
                {
                    "canonical_id": cid,
                    "order": event.get("order"),
                    "event_type": event.get("event_type", ""),
                    "summary": str(event.get("summary", ""))[:500],
                    "evidence_ids": event.get("evidence_ids", []),
                }
            )
    return {
        "required_event_count": len(requirement_ids),
        "covered_event_count": len(requirement_ids) - len(missing),
        "missing_event_count": len(missing),
        "missing_events": missing,
        "covered": covered,
        "step_event_map": step_map,
    }


def enforce_step_bounds(case: dict[str, Any], *, graph: dict[str, Any] | None = None, max_steps: int = 12) -> None:
    steps = [step for step in case.get("evolution_trajectory") or [] if isinstance(step, dict)]
    if len(steps) <= max_steps:
        return
    if graph:
        requirements = select_priority_events(graph, max_events=max_steps)
        requirement_ids = [str(event.get("canonical_id", "")) for event in requirements if event.get("canonical_id")]
        chosen_indices: set[int] = set()
        for cid in requirement_ids:
            best_idx = None
            best_score = -1.0
            for idx, step in enumerate(steps):
                ids = infer_step_event_ids(step, graph)
                if cid not in ids:
                    continue
                score = 10.0 + len(ids & set(requirement_ids))
                score += len(step.get("evidence") or []) * 0.2
                if score > best_score:
                    best_score = score
                    best_idx = idx
            if best_idx is not None:
                chosen_indices.add(best_idx)
            if len(chosen_indices) >= max_steps:
                break
        if 0 not in chosen_indices:
            chosen_indices.add(0)
        if len(steps) - 1 not in chosen_indices and len(chosen_indices) < max_steps:
            chosen_indices.add(len(steps) - 1)
        if len(chosen_indices) < max_steps:
            scored_steps = []
            req_set = set(requirement_ids)
            for idx, step in enumerate(steps):
                ids = infer_step_event_ids(step, graph)
                score = len(ids & req_set) * 8.0
                score += len(extract_numbers(step_text(step))) * 0.5
                score += len(extract_entities(step_text(step))) * 0.4
                if str(step.get("phase", "")).lower() in {"validation", "revision"}:
                    score += 1.0
                scored_steps.append((score, idx))
            for _score, idx in sorted(scored_steps, reverse=True):
                chosen_indices.add(idx)
                if len(chosen_indices) >= max_steps:
                    break
        if len(chosen_indices) > max_steps:
            must_keep = {0, len(steps) - 1} & chosen_indices
            req_set = set(requirement_ids)
            ranked = []
            for idx in chosen_indices:
                ids = infer_step_event_ids(steps[idx], graph)
                score = len(ids & req_set) * 10.0
                score += len(extract_numbers(step_text(steps[idx]))) * 0.5
                score += len(extract_entities(step_text(steps[idx]))) * 0.4
                if idx in must_keep:
                    score += 100.0
                ranked.append((score, idx))
            chosen_indices = {idx for _score, idx in sorted(ranked, reverse=True)[:max_steps]}
        kept = [steps[idx] for idx in sorted(chosen_indices)]
    else:
        if max_steps <= 2:
            kept = steps[:max_steps]
        else:
            head_count = max_steps - 2
            kept = steps[:head_count] + steps[-2:]
    for idx, step in enumerate(kept, start=1):
        step["step_index"] = idx
    case["evolution_trajectory"] = kept
    notes = case.setdefault("quality_control", {}).setdefault("risk_notes", [])
    if isinstance(notes, list):
        notes.append(f"v22_step_trimmed={len(steps)}_to_{len(kept)}")


def critic_prompt(case: dict[str, Any], graph: dict[str, Any], evidence_bank: list[dict[str, Any]], gate: dict[str, Any]) -> str:
    coverage_requirements = coverage_requirements_payload(graph, evidence_bank)
    return f"""Self-critic this candidate. Do not rewrite it.

Check:
1. missing required mainline events,
2. wrong order or wrong causality,
3. unsupported methods, metrics, variants, or conclusions,
4. weak evidence,
5. steps that are generic summaries rather than agent-like decisions.
6. exact consistency of substrate pairs, round numbers, variant names, mutation names, fold/%, ee/E values, thresholds, sample sizes, and validation panels.
7. whether a revision would delete concrete result/validation events and replace them with generic limitations.

Return JSON:
{{
  "needs_revision": true,
  "findings": [
    {{
      "severity": "low|medium|high",
      "affected_steps": [],
      "problem": "",
      "revision_instruction": ""
    }}
  ],
  "must_keep": [],
  "summary": ""
}}

Event graph:
{compact_json(graph)}

Coverage Requirements:
{compact_json(coverage_requirements)}

Evidence bank:
{compact_json([{"evidence_id": ev["evidence_id"], "quote": ev["quote"]} for ev in evidence_bank])}

Candidate:
{compact_json(case)}

Deterministic gate:
{compact_json(gate)}
"""


def normalize_critic(raw: dict[str, Any]) -> dict[str, Any]:
    findings = []
    for item in raw.get("findings") or []:
        if not isinstance(item, dict):
            continue
        severity = item.get("severity")
        if severity not in {"low", "medium", "high"}:
            severity = "medium"
        findings.append(
            {
                "severity": severity,
                "affected_steps": item.get("affected_steps") if isinstance(item.get("affected_steps"), list) else [],
                "problem": clip(item.get("problem", ""), 800),
                "revision_instruction": clip(item.get("revision_instruction", ""), 800),
            }
        )
    needs_revision = bool(raw.get("needs_revision")) or any(f["severity"] in {"medium", "high"} for f in findings)
    return {
        "needs_revision": needs_revision,
        "findings": findings[:10],
        "must_keep": raw.get("must_keep") if isinstance(raw.get("must_keep"), list) else [],
        "summary": clip(raw.get("summary", ""), 1000),
    }


def revise_prompt(case: dict[str, Any], critic: dict[str, Any], graph: dict[str, Any], evidence_bank: list[dict[str, Any]], gate: dict[str, Any]) -> str:
    schema_text = compact_json(SCHEMA_EXAMPLE)
    coverage_requirements = coverage_requirements_payload(graph, evidence_bank)
    evidence_payload = [
        {
            "evidence_id": ev["evidence_id"],
            "source_file": ev["source_file"],
            "section": ev["section"],
            "quote": ev["quote"],
        }
        for ev in evidence_bank
    ]
    return f"""Revise this Sci-Evo case once, conservatively.

Rules:
1. Use only the event graph and evidence bank.
2. Evidence IDs and quotes must be copied exactly from the evidence bank.
3. Fix critic findings and deterministic gate errors.
4. Do not add unsupported details.
5. Prefer narrowing claims over inventing missing detail.
6. Keep 5-12 useful trajectory steps if evidence supports them.
7. Preserve every Coverage Requirement. If needed, merge nearby requirements into one step, but do not drop concrete result/validation events.
8. Do not replace late experimental results with generic discussion limitations.
9. For every step, add an extra internal field `supporting_event_ids` containing the canonical_id values it covers.
10. For any number, mutation, variant, substrate pair, round number, threshold, or sample size in a step, include evidence whose quote contains that specific item; otherwise narrow the claim.
11. Output valid JSON only.

Expected JSON shape:
{schema_text}

Original candidate:
{compact_json(case)}

Critic:
{compact_json(critic)}

Deterministic gate:
{compact_json(gate)}

Event graph:
{compact_json(graph)}

Coverage Requirements:
{compact_json(coverage_requirements)}

Evidence bank:
{compact_json(evidence_payload)}
"""


def compact_number(value: str) -> str:
    return normalize_text(value).lower().replace(",", "").replace(" ", "")


def extract_numbers(text: str) -> set[str]:
    out = set()
    for match in NUMBER_RE.finditer(str(text or "")):
        token = compact_number(match.group(0))
        if token and token not in {"0", "1", "2", "3", "4", "5", "6", "7", "8", "9", "10"}:
            out.add(token)
    return out


def extract_entities(text: str) -> set[str]:
    return {compact_number(m.group(0)) for m in ENTITY_RE.finditer(str(text or ""))}


def fix_phase_action_mismatch(case: dict[str, Any]) -> int:
    fixed = 0
    for step in case.get("evolution_trajectory") or []:
        if not isinstance(step, dict):
            continue
        action = step.get("action_type")
        phase = step.get("phase")
        if action == "wet_experiment" and phase == "analysis":
            step["phase"] = "experiment"
            fixed += 1
        elif action == "dry_experiment" and phase == "analysis":
            step["phase"] = "simulation"
            fixed += 1
    if fixed:
        notes = case.setdefault("quality_control", {}).setdefault("risk_notes", [])
        if isinstance(notes, list):
            notes.append(f"v22_phase_action_fixed={fixed}")
    return fixed


def backfill_specific_evidence(case: dict[str, Any], evidence_bank: list[dict[str, Any]], *, doc_no: str, source_file: str) -> int:
    bank = evidence_by_id(evidence_bank)
    added = 0
    for step in case.get("evolution_trajectory") or []:
        if not isinstance(step, dict):
            continue
        evidence = [ev for ev in step.get("evidence") or [] if isinstance(ev, dict)]
        current_ids = {str(ev.get("evidence_id", "")) for ev in evidence}
        claim = step_text(step)
        evidence_text = " ".join(str(ev.get("quote_or_span", "")) for ev in evidence)
        missing = sorted((extract_numbers(claim) | extract_entities(claim)) - (extract_numbers(evidence_text) | extract_entities(evidence_text)))
        if not missing:
            step["evidence"] = evidence
            continue
        step_tokens = tokens(claim)
        candidates = []
        for ref in evidence_bank:
            eid = str(ref.get("evidence_id", ""))
            if not eid or eid in current_ids:
                continue
            quote = str(ref.get("quote", ""))
            quote_tokens_specific = extract_numbers(quote) | extract_entities(quote)
            hit_tokens = [tok for tok in missing if tok in quote_tokens_specific]
            if not hit_tokens:
                continue
            overlap = len(step_tokens & tokens(quote))
            score = len(hit_tokens) * 20 + overlap
            candidates.append((score, len(hit_tokens), eid, ref))
        for _score, _hit_count, eid, ref in sorted(candidates, reverse=True):
            if len(evidence) >= 6:
                break
            if eid in current_ids:
                continue
            evidence.append(
                {
                    "evidence_id": ref["evidence_id"],
                    "source_file": source_file or f"docs/{doc_no}/combined.md",
                    "section": ref.get("section", ""),
                    "quote_or_span": ref["quote"],
                }
            )
            current_ids.add(eid)
            added += 1
            evidence_text += " " + str(ref.get("quote", ""))
            remaining = sorted((extract_numbers(claim) | extract_entities(claim)) - (extract_numbers(evidence_text) | extract_entities(evidence_text)))
            if len(remaining) >= len(missing):
                continue
            missing = remaining
            if not missing:
                break
        step["evidence"] = evidence
    if added:
        notes = case.setdefault("quality_control", {}).setdefault("risk_notes", [])
        if isinstance(notes, list):
            notes.append(f"v22_specific_evidence_backfilled={added}")
    return added


def deterministic_gate(case: dict[str, Any], full_text_path: Path, graph: dict[str, Any] | None = None) -> dict[str, Any]:
    schema_errors = validate_case(case)
    steps = case.get("evolution_trajectory") or []
    step_count_errors = []
    if not (5 <= len(steps) <= 12):
        step_count_errors.append(f"step_count_out_of_range={len(steps)} expected 5-12")
    missing_step_evidence = []
    for step in steps:
        if not any(isinstance(ev, dict) and str(ev.get("quote_or_span", "")).strip() for ev in step.get("evidence") or []):
            missing_step_evidence.append(int(step.get("step_index") or 0))
    quote_checks = check_case_evidence(case, full_text_path) if full_text_path.exists() else []
    quote_errors = [
        {
            "step_index": item.step_index,
            "evidence_index": item.evidence_index,
            "warning": item.warning,
            "quote": item.quote[:180],
        }
        for item in quote_checks
        if item.warning or not (item.exact_match or item.normalized_match)
    ]
    warnings = []
    for step in steps:
        claim = " ".join(str(step.get(k, "")) for k in TEXT_FIELDS)
        evidence_text = " ".join(str(ev.get("quote_or_span", "")) for ev in step.get("evidence") or [] if isinstance(ev, dict))
        missing_numbers = sorted(extract_numbers(claim) - extract_numbers(evidence_text))
        missing_entities = sorted(extract_entities(claim) - extract_entities(evidence_text))
        if missing_numbers:
            warnings.append({"step_index": step.get("step_index"), "type": "numbers_not_in_step_evidence", "tokens": missing_numbers[:12]})
        if missing_entities:
            warnings.append({"step_index": step.get("step_index"), "type": "entities_not_in_step_evidence", "tokens": missing_entities[:12]})
    mainline_coverage = coverage_audit(case, graph) if graph else {}
    coverage_errors = mainline_coverage.get("missing_events", []) if mainline_coverage else []
    blockers = bool(schema_errors or step_count_errors or missing_step_evidence or quote_errors or coverage_errors)
    return {
        "decision": "fail" if blockers else "pass",
        "schema_errors": schema_errors,
        "step_count_errors": step_count_errors,
        "missing_step_evidence": missing_step_evidence,
        "quote_errors": quote_errors,
        "coverage_errors": coverage_errors,
        "mainline_coverage": mainline_coverage,
        "warnings": warnings,
        "step_count": len(steps),
        "evidence_coverage": evidence_coverage(case),
        "auto_quality_score": quality_score(case),
    }


def prepare_case(
    raw: dict[str, Any],
    *,
    doc_no: str,
    source: dict[str, Any],
    evidence_bank: list[dict[str, Any]],
    graph: dict[str, Any] | None = None,
    strip_internal_fields: bool = False,
) -> dict[str, Any]:
    case = raw.get("case") if isinstance(raw.get("case"), dict) else raw
    normalized = normalize_case(case, doc_no=doc_no, source=source)
    align_case_evidence(normalized, evidence_bank, doc_no=doc_no, source_file=source.get("combined_md", ""))
    enforce_step_bounds(normalized, graph=graph, max_steps=12)
    fix_phase_action_mismatch(normalized)
    backfill_specific_evidence(normalized, evidence_bank, doc_no=doc_no, source_file=source.get("combined_md", ""))
    if strip_internal_fields:
        strip_generation_only_fields(normalized)
    normalized["quality_control"]["evidence_coverage"] = evidence_coverage(normalized)
    normalized["quality_control"]["auto_quality_score"] = quality_score(normalized)
    notes = normalized.setdefault("quality_control", {}).setdefault("risk_notes", [])
    if isinstance(notes, list):
        if "v22_agentic_generation" not in notes:
            notes.append("v22_agentic_generation")
        if "v22_model=deepseek-v4-pro" not in notes:
            notes.append("v22_model=deepseek-v4-pro")
    return normalized


def public_case(case: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(case)
    strip_generation_only_fields(out)
    out["quality_control"]["evidence_coverage"] = evidence_coverage(out)
    out["quality_control"]["auto_quality_score"] = quality_score(out)
    return out


def case_selection_score(case: dict[str, Any], gate: dict[str, Any]) -> float:
    coverage = gate.get("mainline_coverage") or {}
    score = float(coverage.get("covered_event_count") or 0) * 100.0
    score -= float(coverage.get("missing_event_count") or 0) * 80.0
    score -= len(gate.get("schema_errors") or []) * 100.0
    score -= len(gate.get("quote_errors") or []) * 100.0
    score -= len(gate.get("step_count_errors") or []) * 30.0
    score -= len(gate.get("missing_step_evidence") or []) * 50.0
    score -= len(gate.get("warnings") or []) * 2.0
    score += float(case.get("quality_control", {}).get("auto_quality_score") or 0)
    return score


def choose_revision(
    *,
    candidate: dict[str, Any],
    revised: dict[str, Any],
    candidate_gate: dict[str, Any],
    revised_gate: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], bool, str]:
    candidate_score = case_selection_score(candidate, candidate_gate)
    revised_score = case_selection_score(revised, revised_gate)
    candidate_missing = candidate_gate.get("mainline_coverage", {}).get("missing_event_count", 999)
    revised_missing = revised_gate.get("mainline_coverage", {}).get("missing_event_count", 999)
    if revised_missing > candidate_missing:
        return candidate, candidate_gate, False, "rejected_revision_mainline_regression"
    if revised_score + 1e-6 < candidate_score:
        return candidate, candidate_gate, False, "rejected_revision_quality_regression"
    return revised, revised_gate, True, "accepted_revision"


def generate_agentic_case(
    *,
    input_root: Path,
    record: dict[str, Any],
    output_root: Path,
    client: DeepSeekClient,
    config: AgentRunConfig | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    config = config or AgentRunConfig()
    doc_no = str(record["doc_no"]).zfill(4)
    source = source_from_record(record)
    full_text_path = input_root / record["combined_md"]
    full_text = full_text_path.read_text(encoding="utf-8", errors="replace")

    states_dir = output_root / "states"
    events_dir = output_root / "events"
    cases_dir = output_root / "cases"
    for directory in (states_dir, events_dir, cases_dir):
        directory.mkdir(parents=True, exist_ok=True)
    state_path = states_dir / f"{doc_no}.json"
    event_path = events_dir / f"{doc_no}.json"
    case_path = cases_dir / f"{doc_no}.json"
    if case_path.exists() and state_path.exists() and not overwrite:
        return json.loads(case_path.read_text(encoding="utf-8"))

    state: dict[str, Any] = {
        "doc_no": doc_no,
        "status": "running",
        "model": config.model,
        "source": source,
        "full_text_path": str(full_text_path),
        "full_text_chars": len(full_text),
        "stage_calls": [],
    }

    try:
        outline = section_outline(full_text)
        state["outline"] = outline

        raw_plan = call_json(
            client,
            state,
            stage="plan_reading",
            system_prompt=PLAN_SYSTEM,
            user_prompt=plan_prompt(record, outline),
            temperature=config.plan_temperature,
            max_tokens=config.max_tokens,
        )
        plan = normalize_plan(raw_plan, outline, max_sections=config.max_gist_sections)
        state["reading_plan"] = plan

        selected_sections = selected_section_payload(
            full_text,
            outline,
            plan,
            max_section_chars=config.max_section_chars,
            max_total_chars=config.max_reading_chars,
        )
        state["selected_sections"] = [
            {key: value for key, value in item.items() if key != "text"} | {"text_chars": len(item.get("text", ""))}
            for item in selected_sections
        ]
        raw_gists = call_json(
            client,
            state,
            stage="read_sections",
            system_prompt=GIST_SYSTEM,
            user_prompt=gist_prompt(record, plan, selected_sections),
            temperature=config.extract_temperature,
            max_tokens=config.max_tokens,
        )
        gist_memory = normalize_gists(raw_gists)
        state["gist_memory"] = gist_memory

        chunks = split_agent_chunks(full_text, chunk_chars=config.chunk_chars, overlap=config.chunk_overlap)
        state["chunking"] = {
            "chunk_chars": config.chunk_chars,
            "chunk_overlap": config.chunk_overlap,
            "chunk_count": len(chunks),
        }
        chunk_events: list[dict[str, Any]] = []
        evidence_bank: list[dict[str, Any]] = []
        for chunk in chunks:
            raw_events = call_json(
                client,
                state,
                stage=f"extract_events:{chunk.chunk_id}",
                system_prompt=EVENT_SYSTEM,
                user_prompt=event_prompt(record, gist_memory, chunk, len(chunks), max_events=config.max_events_per_chunk),
                temperature=config.extract_temperature,
                max_tokens=config.max_tokens,
            )
            normalized_chunk, refs = normalize_events(
                raw_events,
                chunk,
                full_text,
                doc_no=doc_no,
                source_file=record.get("combined_md", ""),
            )
            chunk_events.append(normalized_chunk)
            evidence_bank.extend(refs)
        auto_evidence_count = augment_specific_evidence_bank(
            evidence_bank,
            full_text,
            doc_no=doc_no,
            source_file=record.get("combined_md", ""),
        )
        state["chunk_events"] = chunk_events
        state["auto_specific_evidence_count"] = auto_evidence_count
        state["evidence_bank"] = evidence_bank

        raw_graph = call_json(
            client,
            state,
            stage="build_event_graph",
            system_prompt=GRAPH_SYSTEM,
            user_prompt=graph_prompt(record, gist_memory, chunk_events, evidence_bank),
            temperature=config.extract_temperature,
            max_tokens=config.max_tokens,
        )
        graph = normalize_graph(raw_graph, chunk_events, evidence_bank)
        event_graph_payload = {
            "doc_no": doc_no,
            "source": source,
            "gist_memory": gist_memory,
            "chunk_events": chunk_events,
            "evidence_bank": evidence_bank,
            "event_graph": graph,
        }
        event_path.write_text(compact_json(event_graph_payload), encoding="utf-8")
        state["event_graph"] = graph

        raw_draft = call_json(
            client,
            state,
            stage="draft_trajectory",
            system_prompt=DRAFT_SYSTEM,
            user_prompt=draft_prompt(record, graph, evidence_bank),
            temperature=config.draft_temperature,
            max_tokens=config.max_tokens,
        )
        candidate = prepare_case(raw_draft, doc_no=doc_no, source=source, evidence_bank=evidence_bank, graph=graph)
        gate_before = deterministic_gate(candidate, full_text_path, graph)
        state["candidate_before_critic"] = candidate
        state["gate_before_critic"] = gate_before

        raw_critic = call_json(
            client,
            state,
            stage="self_critic",
            system_prompt=CRITIC_SYSTEM,
            user_prompt=critic_prompt(candidate, graph, evidence_bank, gate_before),
            temperature=config.extract_temperature,
            max_tokens=config.max_tokens,
        )
        critic = normalize_critic(raw_critic)
        state["self_critic"] = critic

        final_case = candidate
        gate_final_internal = gate_before
        revision_applied = False
        revision_decision = "not_attempted"
        if config.max_revision_rounds and (critic["needs_revision"] or gate_before["decision"] != "pass"):
            raw_revision = call_json(
                client,
                state,
                stage="revise_once",
                system_prompt=REVISE_SYSTEM,
                user_prompt=revise_prompt(candidate, critic, graph, evidence_bank, gate_before),
                temperature=config.draft_temperature,
                max_tokens=config.max_tokens,
            )
            revised_case = prepare_case(raw_revision, doc_no=doc_no, source=source, evidence_bank=evidence_bank, graph=graph)
            revised_gate = deterministic_gate(revised_case, full_text_path, graph)
            state["revised_case_candidate"] = revised_case
            state["revised_gate"] = revised_gate
            final_case, gate_final_internal, revision_applied, revision_decision = choose_revision(
                candidate=candidate,
                revised=revised_case,
                candidate_gate=gate_before,
                revised_gate=revised_gate,
            )

        notes = final_case.setdefault("quality_control", {}).setdefault("risk_notes", [])
        if isinstance(notes, list):
            notes.append(f"v22_revision_applied={int(revision_applied)}")
            notes.append(f"v22_revision_decision={revision_decision}")
        output_case = public_case(final_case)
        gate_final = deterministic_gate(output_case, full_text_path, graph)
        state["final_case_internal"] = final_case
        state["final_case"] = output_case
        state["deterministic_gate"] = gate_final
        state["final_mainline_coverage"] = gate_final.get("mainline_coverage", {})
        state["revision_applied"] = revision_applied
        state["revision_decision"] = revision_decision
        state["status"] = "completed" if gate_final["decision"] == "pass" else "completed_with_gate_fail"

        result = {
            "case": output_case,
            "state_path": str(state_path),
            "events_path": str(event_path),
            "validation_errors": gate_final["schema_errors"],
            "deterministic_gate": gate_final,
            "api_usage": aggregate_usage(state.get("stage_calls", [])),
            "stage_calls": state.get("stage_calls", []),
        }
        case_path.write_text(compact_json(result), encoding="utf-8")
        state_path.write_text(compact_json(state), encoding="utf-8")
        return result
    except Exception as exc:
        state["status"] = "failed"
        state["error"] = str(exc)
        state_path.write_text(compact_json(state), encoding="utf-8")
        result = {
            "case": None,
            "state_path": str(state_path),
            "events_path": str(event_path),
            "validation_errors": [str(exc)],
            "deterministic_gate": {"decision": "fail", "schema_errors": [str(exc)], "quote_errors": []},
            "api_usage": aggregate_usage(state.get("stage_calls", [])),
            "stage_calls": state.get("stage_calls", []),
            "error": str(exc),
        }
        case_path.write_text(compact_json(result), encoding="utf-8")
        return result


def aggregate_usage(stage_calls: list[dict[str, Any]]) -> dict[str, int]:
    total: dict[str, int] = {}
    for call in stage_calls:
        usage = call.get("api_usage") or {}
        for key, value in usage.items():
            if isinstance(value, int):
                total[key] = total.get(key, 0) + value
    return total

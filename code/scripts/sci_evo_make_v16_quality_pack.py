from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sci_evo_pipeline.evidence_index import build_evidence_index, check_quote, is_bad_quote, normalize_text
from sci_evo_pipeline.quality_first import doc_no, read_jsonl
from sci_evo_pipeline.schema import evidence_coverage, quality_score, write_dataset_jsonl


def note(case: dict[str, Any], text: str) -> None:
    qc = case.setdefault("quality_control", {})
    notes = qc.setdefault("risk_notes", [])
    if isinstance(notes, list) and text not in notes:
        notes.append(text)


def reindex_steps(case: dict[str, Any]) -> None:
    for idx, step in enumerate(case.get("evolution_trajectory") or [], start=1):
        step["step_index"] = idx
    qc = case.setdefault("quality_control", {})
    qc["step_count"] = len(case.get("evolution_trajectory") or [])
    qc["evidence_coverage"] = evidence_coverage(case)
    qc["auto_quality_score"] = quality_score(case)


def evidence(doc: str, eid: str, quote: str, section: str) -> dict[str, str]:
    return {
        "evidence_id": eid,
        "source_file": f"docs/{doc}/combined.md",
        "section": section,
        "quote_or_span": quote,
    }


def clean_quote(text: str) -> str:
    return normalize_text(text)


def paragraph_spans(full_text: str) -> list[str]:
    spans = []
    for raw in re.split(r"\n\s*\n", full_text.replace("\r\n", "\n")):
        raw = raw.strip()
        if not raw or raw.startswith("![]("):
            continue
        if "<table" in raw.lower():
            continue
        clean = normalize_text(raw)
        if len(clean) >= 40 and not is_bad_quote(clean):
            spans.append(clean)
    return spans


def find_span(full_text: str, required: list[str], *, preferred: list[str] | None = None, limit: int = 900) -> str:
    preferred = preferred or []
    candidates = []
    req_norm = [r.lower() for r in required]
    pref_norm = [p.lower() for p in preferred]
    for span in paragraph_spans(full_text):
        low = span.lower()
        if not all(r in low for r in req_norm):
            continue
        score = sum(1 for p in pref_norm if p in low)
        score += max(0, 900 - abs(len(span) - 650)) / 1000
        candidates.append((score, span))
    if not candidates:
        return ""
    text = max(candidates, key=lambda item: item[0])[1]
    if len(text) <= limit:
        return text
    low = text.lower()
    positions = [low.find(r) for r in req_norm if low.find(r) >= 0]
    center = min(positions) if positions else 0
    start = max(0, center - 180)
    end = min(len(text), start + limit)
    start = max(0, end - limit)
    snippet = text[start:end].strip()
    if start > 0:
        first_boundary = re.search(r"(?<=[.!?])\s+", snippet)
        if first_boundary and first_boundary.end() < len(snippet) - 80:
            snippet = snippet[first_boundary.end() :].strip()
    if end < len(text):
        last_boundary = max(snippet.rfind(". "), snippet.rfind(".)"), snippet.rfind(")."), snippet.rfind("."))
        if last_boundary >= 160:
            snippet = snippet[: last_boundary + 1].strip()
    return snippet


BAD_TEXT_RE = re.compile(
    r"!?\[[^\]]*\]\([^)]*(?:/vlm/images/|mineru_output|\.pdf/vlm/images|"
    r"\.(?:jpg|jpeg|png|webp|gif|svg))[^)]*\)|"
    r"\S*(?:/vlm/images/|mineru_output|\.pdf/vlm/images)\S*|"
    r"\S+\.(?:jpg|jpeg|png|webp|gif|svg)\S*|"
    r"<details\b|</details>",
    re.I,
)
WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9_-]{2,}")
ENTITY_RE = re.compile(r"\b[A-Z][0-9]{1,4}[A-Z]\b|\b[A-Z]{1,6}[-_][0-9]{1,4}\b")
NUMBER_RE = re.compile(
    r"(?<![A-Za-z])(?:~|\\~)?\d+(?:[.,]\d+)?(?:\s*(?:×|x|\\times)\s*10\^?\{?\d+\}?)?"
    r"(?:\s*[-–—−每]\s*(?:to\s*)?(?:~|\\~)?\d+(?:[.,]\d+)?)?"
)
STOPWORDS = {
    "about",
    "above",
    "after",
    "again",
    "against",
    "also",
    "among",
    "and",
    "are",
    "around",
    "assay",
    "before",
    "being",
    "between",
    "both",
    "but",
    "can",
    "could",
    "data",
    "did",
    "does",
    "during",
    "each",
    "from",
    "had",
    "has",
    "have",
    "into",
    "its",
    "later",
    "more",
    "not",
    "only",
    "paper",
    "result",
    "results",
    "show",
    "showed",
    "shows",
    "step",
    "such",
    "than",
    "that",
    "the",
    "then",
    "this",
    "through",
    "used",
    "using",
    "was",
    "were",
    "when",
    "where",
    "which",
    "with",
    "workflow",
}
TEXT_FIELDS = (
    "state_before",
    "gap_or_uncertainty",
    "hypothesis",
    "decision",
    "observation",
    "next_step_reason",
)
FIELD_FALLBACKS = {
    "state_before": "The paper starts from a documented engineering bottleneck that motivates the following workflow.",
    "gap_or_uncertainty": "The next action addresses an unresolved performance, screening, or validation gap described in the paper.",
    "hypothesis": "A structured design, screening, or validation choice may improve the target property if supported by the paper evidence.",
    "decision": "Define the next concrete design, screening, or validation action in the paper workflow.",
    "observation": "The paper evidence supports this step, while the previous generated wording contained extraction artifacts.",
    "next_step_reason": "This step motivates the next concrete action in the paper workflow.",
}
PHASE_ORDER = {
    "hypothesis": 0,
    "design": 1,
    "simulation": 2,
    "experiment": 3,
    "analysis": 4,
    "revision": 5,
    "validation": 6,
}
EARLY_VALIDATION_WORDS = re.compile(r"\b(calibrate|gate|sort|screen|assay|test|measure|plate|grow|pick|select|recover)\b", re.I)
FINAL_VALIDATION_WORDS = re.compile(
    r"\b(final|confirm|kinetic|purif|characteri[sz]e|biotransformation|production|gas chromatography|"
    r"complementation|best variant|selected strain|validate|validation)\b",
    re.I,
)


def remove_extraction_artifacts(text: str) -> str:
    clean = normalize_text(str(text or ""))
    clean = BAD_TEXT_RE.sub(" ", clean)
    clean = re.sub(r"\bng_direct_[A-Za-z0-9_./-]+\b", " ", clean)
    clean = re.sub(r"\b[a-f0-9]{32,}\b", " ", clean, flags=re.I)
    return normalize_text(clean)


def text_has_extraction_artifact(text: str) -> bool:
    return bool(BAD_TEXT_RE.search(str(text or "")))


def compact_token(text: str) -> str:
    raw = str(text or "").replace("\\times", "x").replace("\\sim", "~").replace("\\~", "~")
    return (
        normalize_text(raw)
        .lower()
        .replace(",", "")
        .replace(" ", "")
        .replace("{", "")
        .replace("}", "")
        .replace("\\times", "x")
        .replace("×", "x")
        .replace("^", "")
        .replace("~", "")
        .replace("–", "-")
        .replace("—", "-")
        .replace("−", "-")
        .replace("每", "-")
        .replace("-to", "-")
    )


def entity_tokens(text: str) -> set[str]:
    return {compact_token(item) for item in ENTITY_RE.findall(str(text or "")) if item}


def number_tokens(text: str) -> set[str]:
    out: set[str] = set()
    for match in NUMBER_RE.finditer(str(text or "")):
        raw = match.group(0).strip()
        token = compact_token(raw)
        if not token:
            continue
        if token in {"0", "1", "2", "3", "4", "5", "6", "7", "8", "9", "10"}:
            window = str(text or "")[max(0, match.start() - 25) : min(len(str(text or "")), match.end() + 40)].lower()
            if not re.search(r"fold|mm|um|nm|%|variant|library|residue|mutation|mutant|colon|day|hour|min|s-1|m-1|turnover|activity", window):
                continue
        out.add(token)
    return out


def retrieval_tokens(text: str) -> set[str]:
    clean = remove_extraction_artifacts(text)
    tokens: set[str] = set()
    for raw in WORD_RE.findall(clean):
        token = raw.lower().strip("_-")
        if not token or token in STOPWORDS or len(token) < 3 or len(token) > 36:
            continue
        if token.isdigit() or token.startswith(("http", "www")):
            continue
        if token.endswith((".jpg", ".png", ".pdf")):
            continue
        tokens.add(token)
    tokens.update(entity_tokens(clean))
    return tokens


def step_claim_for_retrieval(step: dict[str, Any]) -> str:
    parts: list[str] = []
    for field in TEXT_FIELDS:
        value = str(step.get(field, "") or "")
        if value:
            parts.append(remove_extraction_artifacts(value))
    tool = step.get("tool_or_method") or {}
    if isinstance(tool, dict):
        parts.append(str(tool.get("name", "")))
        parts.append(str(tool.get("category", "")))
    params = step.get("parameters", {})
    if params:
        parts.append(remove_extraction_artifacts(json.dumps(params, ensure_ascii=False)))
    return " ".join(part for part in parts if part)


def shorten_quote_for_field(quote: str, *, limit: int = 260) -> str:
    clean = normalize_text(quote)
    if len(clean) <= limit:
        return clean
    boundary = clean.find(". ", 80, limit)
    if boundary >= 0:
        return clean[: boundary + 1]
    return clean[:limit].rsplit(" ", 1)[0].strip() + "."


def sanitize_step_text(step: dict[str, Any]) -> int:
    changed = 0
    first_quote = ""
    for ev in step.get("evidence") or []:
        if isinstance(ev, dict) and ev.get("quote_or_span"):
            first_quote = str(ev.get("quote_or_span", ""))
            break
    for field in TEXT_FIELDS:
        value = str(step.get(field, "") or "")
        if not value:
            continue
        cleaned = remove_extraction_artifacts(value)
        if cleaned and cleaned != value and len(cleaned) >= 36 and not text_has_extraction_artifact(cleaned):
            step[field] = cleaned
            changed += 1
            continue
        if text_has_extraction_artifact(value) or not cleaned or len(cleaned) < 18:
            if first_quote and field in {"state_before", "gap_or_uncertainty", "observation"}:
                step[field] = f"The paper frames this step around: {shorten_quote_for_field(first_quote)}"
            else:
                step[field] = FIELD_FALLBACKS[field]
            changed += 1
        polished = polish_text_field(str(step.get(field, "") or ""))
        if polished != step.get(field):
            step[field] = polished
            changed += 1
    return changed


def polish_text_field(text: str) -> str:
    clean = normalize_text(text)
    if len(clean) > 420 and clean.count(".") <= 1:
        clean = shorten_quote_for_field(clean, limit=380)
    if (
        len(clean) > 180
        and re.search(r"\b[a-zA-Z]{4,}$", clean)
        and not clean.endswith((".", ")", "]", "%", "渭M", "mM"))
    ):
        clean += "."
    return clean


def span_score(
    span_text: str,
    section: str,
    query_tokens: set[str],
    required_entities: set[str],
    required_numbers: set[str],
    *,
    step_index: int,
) -> float:
    span_clean = normalize_text(span_text)
    span_tokens = retrieval_tokens(span_clean)
    if not span_tokens:
        return 0.0
    overlap = query_tokens & span_tokens
    compact = compact_token(span_clean)
    entity_hits = {ent for ent in required_entities if ent and ent in compact}
    number_hits = {num for num in required_numbers if num and num in compact}
    score = float(len(overlap))
    score += 8.0 * len(entity_hits)
    score += 6.0 * len(number_hits)
    if step_index == 1 and any(key in section.lower() for key in ("abstract", "introduction", "background", "front")):
        score += 2.0
    if any(token in span_tokens for token in ("mutagenesis", "screening", "variant", "library", "activity", "stability", "selection")):
        score += 0.6
    score += max(0.0, 900.0 - abs(len(span_clean) - 650.0)) / 1500.0
    return score


def focused_quote(
    text: str,
    query_tokens: set[str],
    required_entities: set[str],
    required_numbers: set[str] | None = None,
    *,
    limit: int = 1150,
) -> str:
    clean = normalize_text(text)
    required_numbers = required_numbers or set()
    if len(clean) <= limit:
        return clean
    low = clean.lower()
    positions: list[int] = []
    for token in sorted(required_entities | required_numbers | query_tokens, key=len, reverse=True)[:40]:
        if not token:
            continue
        pos = low.find(token.lower())
        if pos >= 0:
            positions.append(pos)
    center = min(positions) if positions else 0
    start = max(0, center - 220)
    end = min(len(clean), start + limit)
    start = max(0, end - limit)
    snippet = clean[start:end].strip()
    if start > 0:
        boundary = re.search(r"(?<=[.!?])\s+", snippet)
        if boundary and boundary.end() < len(snippet) - 120:
            snippet = snippet[boundary.end() :].strip()
    if end < len(clean):
        last = max(snippet.rfind(". "), snippet.rfind("; "), snippet.rfind(")."), snippet.rfind("."))
        if last >= 220:
            snippet = snippet[: last + 1].strip()
    return snippet


def select_backfill_spans(
    full_text: str,
    step: dict[str, Any],
    doc: str,
    *,
    step_index: int,
    required_entities: set[str] | None = None,
    required_numbers: set[str] | None = None,
    banned_quotes: set[str] | None = None,
    max_count: int = 1,
) -> list[dict[str, str]]:
    required_entities = required_entities or set()
    required_numbers = required_numbers or set()
    banned_quotes = {normalize_text(q) for q in (banned_quotes or set()) if q}
    claim = step_claim_for_retrieval(step)
    query = retrieval_tokens(claim)
    if not query and not required_entities:
        query = {"engineering", "activity", "variant", "screening", "mutagenesis", "stability"}
    spans = build_evidence_index(full_text)
    ranked = []
    for span in spans:
        quote = focused_quote(span.text, query, required_entities, required_numbers)
        if is_bad_quote(quote):
            continue
        if normalize_text(quote) in banned_quotes:
            continue
        score = span_score(quote, span.section, query, required_entities, required_numbers, step_index=step_index)
        if required_entities and not any(ent in compact_token(quote) for ent in required_entities):
            score -= 5.0
        if required_numbers and not any(num in compact_token(quote) for num in required_numbers):
            score -= 4.0
        if score <= 0:
            continue
        ranked.append((score, span.section, quote, span.span_id))
    if not ranked:
        for span in spans[:12]:
            quote = focused_quote(span.text, query, required_entities, required_numbers)
            if not is_bad_quote(quote) and normalize_text(quote) not in banned_quotes:
                ranked.append((0.1, span.section, quote, span.span_id))
                break
    selected: list[dict[str, str]] = []
    seen = set()
    for score, section, quote, span_id in sorted(ranked, key=lambda item: item[0], reverse=True):
        if quote in seen:
            continue
        qc = check_quote(full_text, quote)
        if qc.warning or not (qc.exact_match or qc.normalized_match):
            continue
        seen.add(quote)
        selected.append(evidence(doc, f"V16_AUTO_{doc}_{step_index:02d}_{span_id}", quote, section))
        if len(selected) >= max_count:
            break
    return selected


def repair_evidence_against_full_text(case: dict[str, Any], full_text: str, doc: str) -> dict[str, int]:
    stats = {
        "invalid_evidence_removed": 0,
        "text_artifacts_fixed": 0,
        "missing_evidence_backfilled": 0,
        "entity_evidence_backfilled": 0,
        "numeric_evidence_backfilled": 0,
    }
    for step in case.get("evolution_trajectory") or []:
        step_index = int(step.get("step_index") or 0)
        valid_evidence = []
        for idx, ev in enumerate(step.get("evidence") or []):
            if not isinstance(ev, dict):
                stats["invalid_evidence_removed"] += 1
                continue
            quote = normalize_text(str(ev.get("quote_or_span", "")))
            if text_has_extraction_artifact(quote) or is_bad_quote(quote):
                stats["invalid_evidence_removed"] += 1
                continue
            qc = check_quote(full_text, quote, section=str(ev.get("section", "")), step_index=step_index, evidence_index=idx)
            if qc.warning or not (qc.exact_match or qc.normalized_match):
                stats["invalid_evidence_removed"] += 1
                continue
            ev = dict(ev)
            ev["source_file"] = f"docs/{doc}/combined.md"
            ev["quote_or_span"] = quote
            valid_evidence.append(ev)
        step["evidence"] = valid_evidence
        stats["text_artifacts_fixed"] += sanitize_step_text(step)

        if not step["evidence"]:
            backfill = select_backfill_spans(full_text, step, doc, step_index=step_index, max_count=2 if step_index == 1 else 1)
            append_evidence(step, backfill)
            stats["missing_evidence_backfilled"] += len(backfill)

        claim_entities = entity_tokens(step_claim_for_retrieval(step))
        evidence_entities = entity_tokens(" ".join(str(ev.get("quote_or_span", "")) for ev in step.get("evidence") or [] if isinstance(ev, dict)))
        missing_entities = {ent for ent in claim_entities - evidence_entities if ent}
        if missing_entities:
            backfill = select_backfill_spans(
                full_text,
                step,
                doc,
                step_index=step_index,
                required_entities=missing_entities,
                max_count=1,
            )
            before = len(step.get("evidence") or [])
            append_evidence(step, backfill)
            stats["entity_evidence_backfilled"] += max(0, len(step.get("evidence") or []) - before)

        claim_numbers = number_tokens(step_claim_for_retrieval(step))
        evidence_numbers = number_tokens(" ".join(str(ev.get("quote_or_span", "")) for ev in step.get("evidence") or [] if isinstance(ev, dict)))
        missing_numbers = {num for num in claim_numbers - evidence_numbers if num}
        if missing_numbers:
            backfill = select_backfill_spans(
                full_text,
                step,
                doc,
                step_index=step_index,
                required_numbers=missing_numbers,
                max_count=1,
            )
            before = len(step.get("evidence") or [])
            append_evidence(step, backfill)
            stats["numeric_evidence_backfilled"] += max(0, len(step.get("evidence") or []) - before)

    if stats["invalid_evidence_removed"]:
        note(case, f"v16_invalid_evidence_removed={stats['invalid_evidence_removed']}")
    if stats["text_artifacts_fixed"]:
        note(case, f"v16_text_artifacts_fixed={stats['text_artifacts_fixed']}")
    if stats["missing_evidence_backfilled"]:
        note(case, f"v16_missing_evidence_backfilled={stats['missing_evidence_backfilled']}")
    if stats["entity_evidence_backfilled"]:
        note(case, f"v16_entity_evidence_backfilled={stats['entity_evidence_backfilled']}")
    if stats["numeric_evidence_backfilled"]:
        note(case, f"v16_numeric_evidence_backfilled={stats['numeric_evidence_backfilled']}")
    return stats


def diversify_reused_evidence(case: dict[str, Any], full_text: str, doc: str) -> int:
    quote_counts: dict[str, int] = {}
    for step in case.get("evolution_trajectory") or []:
        for ev in step.get("evidence") or []:
            if isinstance(ev, dict):
                quote = normalize_text(str(ev.get("quote_or_span", "")))
                if quote:
                    quote_counts[quote] = quote_counts.get(quote, 0) + 1
    repeated = {quote for quote, count in quote_counts.items() if count >= 3}
    if not repeated:
        return 0

    changed = 0
    seen_repeated: dict[str, int] = {}
    for step in case.get("evolution_trajectory") or []:
        step_index = int(step.get("step_index") or 0)
        evs = [ev for ev in step.get("evidence") or [] if isinstance(ev, dict)]
        if not evs:
            continue
        new_evs = []
        removed_any = False
        for ev in evs:
            quote = normalize_text(str(ev.get("quote_or_span", "")))
            if quote in repeated:
                seen_repeated[quote] = seen_repeated.get(quote, 0) + 1
                if seen_repeated[quote] > 2 and len(evs) > 1:
                    removed_any = True
                    continue
            new_evs.append(ev)
        if removed_any:
            step["evidence"] = new_evs
            changed += 1
        if any(normalize_text(str(ev.get("quote_or_span", ""))) in repeated for ev in step.get("evidence") or []):
            backfill = select_backfill_spans(
                full_text,
                step,
                doc,
                step_index=step_index,
                required_numbers=number_tokens(step_claim_for_retrieval(step)),
                banned_quotes=repeated,
                max_count=1,
            )
            before = {normalize_text(str(ev.get("quote_or_span", ""))) for ev in step.get("evidence") or [] if isinstance(ev, dict)}
            append_evidence(step, backfill)
            after = {normalize_text(str(ev.get("quote_or_span", ""))) for ev in step.get("evidence") or [] if isinstance(ev, dict)}
            if after - before:
                changed += 1
    if changed:
        note(case, f"v16_reused_evidence_diversified={changed}")
    return changed


def cut_after(text: str, marker: str) -> str:
    idx = text.find(marker)
    if idx < 0:
        return text
    return text[: idx + len(marker)].strip()


def table_text_after(full_text: str, title: str, *, limit: int = 1800) -> str:
    title_pos = full_text.find(title)
    if title_pos < 0:
        return ""
    start = full_text.find("<table", title_pos)
    end = full_text.find("</table>", start)
    if start < 0 or end < 0:
        return ""
    text = normalize_text(full_text[title_pos : end + len("</table>")])
    return text[:limit].strip()


def normalized_window(full_text: str, required: list[str], *, limit: int = 900, lead: int = 140) -> str:
    norm = normalize_text(full_text)
    low = norm.lower()
    req = [item.lower() for item in required]
    anchors: list[int] = []
    for item in req:
        start = 0
        while True:
            pos = low.find(item, start)
            if pos < 0:
                break
            anchors.append(pos)
            start = pos + max(1, len(item))
    if not anchors:
        return ""
    center = max(
        anchors,
        key=lambda pos: (
            sum(1 for item in req if item in low[max(0, pos - lead) : min(len(low), pos + limit)]),
            pos,
        ),
    )
    start = max(0, center - lead)
    table_start = max(low.rfind("| group", 0, center), low.rfind("| mutants", 0, center), low.rfind("| mutant", 0, center))
    if table_start >= 0 and center - table_start < 700:
        start = table_start
    prev_image = max(low.rfind(".jpg)", 0, center), low.rfind(".png)", 0, center), low.rfind(".jpeg)", 0, center))
    if prev_image >= 0 and center - prev_image < 900:
        start = max(start, prev_image + len(".jpg)"))
    end = min(len(norm), start + limit)
    quote = norm[start:end].strip()
    artifact = BAD_TEXT_RE.search(quote)
    if artifact and artifact.start() > 180:
        quote = quote[: artifact.start()].strip()
    if end < len(norm):
        last = max(quote.rfind(". "), quote.rfind("\n"), quote.rfind(" Fig."))
        if last >= 300 and not (quote.count("|") >= 6 and last < 520):
            quote = quote[: last + 1].strip()
    return quote


def remove_bad_evidence(case: dict[str, Any]) -> int:
    removed = 0
    for step in case.get("evolution_trajectory") or []:
        clean = []
        for ev in step.get("evidence") or []:
            if not isinstance(ev, dict):
                continue
            quote = str(ev.get("quote_or_span", ""))
            if is_bad_quote(quote):
                removed += 1
                continue
            clean.append(ev)
        step["evidence"] = clean
    if removed:
        note(case, f"v16_removed_bad_evidence={removed}")
    return removed


def add_or_replace_evidence(step: dict[str, Any], evs: list[dict[str, str]]) -> None:
    seen = set()
    new = []
    for ev in evs:
        quote = ev.get("quote_or_span", "")
        if not quote or quote in seen or is_bad_quote(quote):
            continue
        seen.add(quote)
        new.append(ev)
    step["evidence"] = new


def append_evidence(step: dict[str, Any], evs: list[dict[str, str]]) -> None:
    current = [ev for ev in step.get("evidence") or [] if isinstance(ev, dict)]
    seen = {str(ev.get("quote_or_span", "")) for ev in current}
    for ev in evs:
        quote = ev.get("quote_or_span", "")
        if not quote or quote in seen or is_bad_quote(quote):
            continue
        seen.add(quote)
        current.append(ev)
    step["evidence"] = current


def make_step(
    *,
    phase: str,
    action_type: str,
    state_before: str,
    gap: str,
    hypothesis: str,
    decision: str,
    tool_name: str,
    tool_category: str,
    parameters: dict[str, Any],
    observation: str,
    result_status: str,
    next_reason: str,
    evs: list[dict[str, str]],
) -> dict[str, Any]:
    return {
        "step_index": 0,
        "phase": phase,
        "state_before": state_before,
        "gap_or_uncertainty": gap,
        "hypothesis": hypothesis,
        "decision": decision,
        "action_type": action_type,
        "tool_or_method": {"name": tool_name, "version": "", "category": tool_category},
        "parameters": parameters,
        "observation": observation,
        "result_status": result_status,
        "next_step_reason": next_reason,
        "evidence": evs,
    }


def fix_phase_action(case: dict[str, Any]) -> int:
    changed = 0
    for step in case.get("evolution_trajectory") or []:
        if step.get("phase") == "analysis" and step.get("action_type") == "wet_experiment":
            text = " ".join(str(step.get(k, "")) for k in ("decision", "observation", "next_step_reason")).lower()
            step["phase"] = "validation" if any(k in text for k in ("validate", "screen", "character", "sort")) else "experiment"
            changed += 1
    if changed:
        note(case, f"v16_phase_action_fixed={changed}")
    return changed


def repair_phase_order(case: dict[str, Any]) -> int:
    steps = case.get("evolution_trajectory") or []
    changed = 0
    if len(steps) < 3:
        return 0

    for idx, step in enumerate(steps):
        if step.get("phase") != "validation" or idx >= len(steps) - 1:
            continue
        later_orders = [PHASE_ORDER.get(str(s.get("phase")), 4) for s in steps[idx + 1 :]]
        if not later_orders or min(later_orders) >= PHASE_ORDER["analysis"]:
            continue
        text = " ".join(str(step.get(k, "")) for k in TEXT_FIELDS).lower()
        if EARLY_VALIDATION_WORDS.search(text) and not FINAL_VALIDATION_WORDS.search(text):
            step["phase"] = "experiment"
            changed += 1

    max_order = -1
    for step in steps:
        phase = str(step.get("phase") or "analysis")
        order = PHASE_ORDER.get(phase, 4)
        if order < max_order - 2:
            if max_order >= PHASE_ORDER["validation"]:
                step["phase"] = "validation"
            elif max_order >= PHASE_ORDER["revision"]:
                step["phase"] = "revision"
            elif max_order >= PHASE_ORDER["analysis"]:
                step["phase"] = "analysis"
            else:
                step["phase"] = "experiment"
            changed += 1
            order = PHASE_ORDER.get(str(step.get("phase")), order)
        max_order = max(max_order, order)

    if changed:
        note(case, f"v16_phase_order_fixed={changed}")
    return changed


def fix_text_hygiene(case: dict[str, Any]) -> int:
    changed = 0
    for step in case.get("evolution_trajectory") or []:
        nxt = str(step.get("next_step_reason", ""))
        if nxt.count("{") != nxt.count("}") or len(nxt) > 420:
            step["next_step_reason"] = "This result determines the next concrete experiment or validation step in the paper workflow."
            changed += 1
    if changed:
        note(case, f"v16_text_hygiene_fixed={changed}")
    return changed


def normalize_parameter_numbers(value: Any, *, key: str = "") -> Any:
    if isinstance(value, dict):
        return {k: normalize_parameter_numbers(v, key=str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [normalize_parameter_numbers(item, key=key) for item in value]
    if isinstance(value, int):
        if value >= 1_000_000 and value % 1_000_000 == 0:
            return f"{value // 1_000_000} million"
        if value >= 100_000:
            return f"{value:,}"
    if isinstance(value, float):
        if 0 < value < 1 and any(token in key.lower() for token in ("fraction", "retained", "occupancy", "percent")):
            return f"{value * 100:g}%"
    return value


def normalize_numeric_parameters(case: dict[str, Any]) -> int:
    changed = 0
    for step in case.get("evolution_trajectory") or []:
        params = step.get("parameters")
        if not isinstance(params, dict):
            continue
        normalized = normalize_parameter_numbers(params)
        if normalized != params:
            step["parameters"] = normalized
            changed += 1
    if changed:
        note(case, f"v16_numeric_parameters_normalized={changed}")
    return changed


def find_step(case: dict[str, Any], predicate) -> dict[str, Any] | None:
    for step in case.get("evolution_trajectory") or []:
        if predicate(step):
            return step
    return None


def repair_0015(case: dict[str, Any], full_text: str) -> int:
    doc = "0015"
    changes = 0
    step = find_step(
        case,
        lambda s: "site-saturation mutagenesis at position 477" in str(s.get("decision", "")).lower()
        or "k477q" in json.dumps(s.get("parameters", {}), ensure_ascii=False).lower(),
    )
    if step:
        q_reason = find_span(
            full_text,
            ["The K477 site was further mutated", "polar amino acids Q and T", "lower cadaverine yield than K477R"],
            preferred=["positive charges", "477 site", "pH 8.0"],
            limit=1200,
        )
        q_table = normalized_window(full_text, ["K477R", "115", "K477Q", "K477D", "K477H"], limit=850, lead=80)
        step["parameters"] = {
            "site": "477",
            "tested_substitutions": "R, Q, V, T, D, and H",
            "best_substitution": "K477R",
            "best_relative_yield": "115%",
        }
        step["decision"] = "Perform focused site-directed mutagenesis at position 477, testing R, Q, V, T, D, and H substitutions and comparing cadaverine yields."
        step["observation"] = "K477R showed the highest relative yield (115%) compared with wild type; the other tested substitutions were lower than K477R."
        step["next_step_reason"] = "The K477R result supports retaining a more positively charged residue at site 477 for subsequent stabilizing combinations."
        evs = []
        if q_reason:
            evs.append(evidence(doc, "V16_0015_01", q_reason, "Directed evolution of CadA"))
        if q_table and not is_bad_quote(q_table) and not text_has_extraction_artifact(q_table):
            evs.append(evidence(doc, "V16_0015_02", q_table, "Fig. 2 site-directed mutagenesis table"))
        append_evidence(step, evs)
        changes += 1
    if changes:
        note(case, "v16_quality_repair_0015")
    return changes


def repair_0044(case: dict[str, Any], full_text: str) -> int:
    doc = "0044"
    changes = 0
    step6 = find_step(
        case,
        lambda s: "g2-selected" in str(s.get("decision", "")).lower()
        or "T138G-V190A" in json.dumps(s.get("parameters", {}), ensure_ascii=False),
    )
    if step6:
        q_g2 = find_span(
            full_text,
            ["The addition of G2-selected mutations", "production yields nearly 6-fold"],
            preferred=["V190A", "D134S", "G1-T138G", "Fig. 3B"],
            limit=1300,
        )
        step6["state_before"] = "The G1 screen identified T138G as a strong methyl-cinnamate template, and the paper expanded G2 exploration around that background."
        step6["gap_or_uncertainty"] = "The paper had to determine which G2 mutations combined productively with the G1-T138G template and which double mutants should enter G3."
        step6["hypothesis"] = "Adding selected G2 mutations to a successful G1 template can create higher-activity double mutants, but different G2 candidates may not contribute equally."
        step6["decision"] = "Evaluate G2-selected mutations over the G1-T138G template and carry forward the T138G-V190A and T138G-D134S double-mutant templates."
        step6["observation"] = "Adding V190A and D134S to the G1-T138G template allowed selection of double mutants with production yields nearly 6-fold that of wild type; Figure 3 also marks I189T as a G2-tested position, but the text carries T138G-V190A and T138G-D134S into G3."
        step6["next_step_reason"] = "The two selected double-mutant templates then defined the G3 test of whether independently beneficial G2 substitutions would combine additively or synergistically."
        step6["parameters"] = {
            "g1_template": "T138G",
            "g2_tested_positions_in_figure": ["D134S", "V190A", "I189T"],
            "g3_templates_carried_forward": ["T138G-V190A", "T138G-D134S"],
            "reported_g2_effect": "production yields nearly 6-fold that of WT for methyl cinnamate",
        }
        if q_g2:
            append_evidence(step6, [evidence(doc, "V16_0044_01", q_g2, "CalB library screening")])
        changes += 1
    if changes:
        note(case, "v16_quality_repair_0044")
    return changes


def repair_0085(case: dict[str, Any], full_text: str) -> int:
    doc = "0085"
    changes = 0
    steps = case.get("evolution_trajectory") or []

    old_step3 = find_step(case, lambda s: "20 $^{4}$" in json.dumps(s, ensure_ascii=False) or "top 25 predictions" in json.dumps(s, ensure_ascii=False).lower())
    step1 = find_step(case, lambda s: s.get("step_index") == 1)
    step2 = find_step(case, lambda s: s.get("step_index") == 2)
    step4 = find_step(case, lambda s: s.get("step_index") == 4)
    step5 = find_step(case, lambda s: s.get("step_index") == 5)
    step6 = find_step(case, lambda s: s.get("step_index") == 6)
    step7 = find_step(case, lambda s: s.get("step_index") == 7)
    step8 = find_step(case, lambda s: s.get("step_index") == 8)
    step9 = find_step(case, lambda s: s.get("step_index") == 9)
    step10 = find_step(case, lambda s: s.get("step_index") == 10)

    q_scope = find_span(
        full_text,
        ["1100 unique reactions", "11 pharmaceutical compounds", "16"],
        preferred=["substrate scope", "wild-type McbA", "Fig. 2"],
        limit=1500,
    )
    q_leads = find_span(
        full_text,
        ["three high-value molecules", "moclobemide", "metoclopramide", "cinchocaine"],
        preferred=["substrate scope evaluation", "wt conversion"],
        limit=1300,
    )
    q_cfe = find_span(full_text, ["cell-free DNA-assembly", "workflow had five steps"], preferred=["CFE", "LETs"], limit=1200)
    q_hss = find_span(
        full_text,
        ["64 residues", "1216 total single mutants", "LC-MS"],
        preferred=["hot spot screen", "McbA", "three high-value molecules"],
        limit=1300,
    )
    q_fit = find_span(
        full_text,
        ["fit augmented ridge regression models", "single mutant data from the HSS"],
        preferred=["higher order mutants", "zero-shot"],
        limit=1200,
    )
    q_arch = find_span(
        full_text,
        ["EVmutation", "Georgiev encodings", "strong predictive performance"],
        preferred=["NDCG", "site saturation dataset"],
        limit=1500,
    )
    q_ism = find_span(
        full_text,
        ["After three rounds of ISM", "96% conversion", "42-fold increase"],
        preferred=["moclobemide", "quadruple mutant"],
        limit=1500,
    )
    q_cinch = find_span(
        full_text,
        ["cinchocaine", "failed to observe beneficial mutations beyond a double mutant"],
        preferred=["pressure-test", "ISM data"],
        limit=1000,
    )
    q_eval = find_span(
        full_text,
        ["Model prediction performance", "NDCG", "augmented models outperformed"],
        preferred=["Spearman", "training set"],
        limit=1500,
    )
    q_screen = find_span(
        full_text,
        ["Using our trained ML models", "20 $^{4}$", "top 25 predictions"],
        preferred=["experimentally", "surpassing", "screening burden"],
        limit=1600,
    )
    q_all = find_span(
        full_text,
        ["n=160,000", "top 25 predictions", "experimentally tested"],
        preferred=["EVmutation", "Georgiev", "without GPU"],
        limit=1200,
    )
    q_six = find_span(
        full_text,
        ["additional six pharmaceutical compounds", "1.6-fold to 34-fold", "best rational design"],
        preferred=["top 24 predictions", "six compounds"],
        limit=1500,
    )
    q_scale = find_span(
        full_text,
        ["10-mL reaction", "58 mg", "87% isolated yield"],
        preferred=["moclobemide", "NMR"],
        limit=1200,
    )

    substrate_step = make_step(
        phase="design",
        action_type="wet_experiment",
        state_before="The paper had established McbA as a promiscuous amide synthetase candidate, but the target chemical space for engineering had to be chosen.",
        gap="The authors needed to identify which pharmaceutical amidation reactions were accessible to wild-type McbA and which reactions justified engineering campaigns.",
        hypothesis="A broad substrate-scope screen can reveal tractable and challenging McbA reactions that define useful engineering targets.",
        decision="Explore wild-type McbA substrate promiscuity across 1100 reactions, then select moclobemide, metoclopramide, and cinchocaine as initial engineering targets.",
        tool_name="McbA substrate-scope LC-MS screen",
        tool_category="target selection",
        parameters={"substrate_scope_reactions": 1100, "selected_initial_targets": ["moclobemide", "metoclopramide", "cinchocaine"]},
        observation="Wild-type McbA synthesized 16 of 21 high-value molecules, including 11 pharmaceuticals, and the paper chose three initial targets with distinct substrate challenges and low wild-type conversions.",
        result_status="success",
        next_reason="Those target reactions determined which McbA sequence-function datasets had to be generated for model training.",
        evs=[
            evidence(doc, "V16_0085_01", q_scope, "Exploring the biocatalytic synthesis landscape of McbA"),
            evidence(doc, "V16_0085_02", q_leads, "Cell-free protein engineering to rapidly screen sequence-defined protein libraries"),
        ],
    )

    if step4:
        step4.update(
            {
                "phase": "experiment",
                "action_type": "wet_experiment",
                "state_before": "Moclobemide, metoclopramide, and cinchocaine were selected as initial McbA engineering targets.",
                "gap_or_uncertainty": "The model needed dense sequence-function measurements for single mutants at relevant active-site positions.",
                "hypothesis": "Cell-free DNA assembly and CFE can rapidly build and assay sequence-defined McbA site-saturation libraries.",
                "decision": "Build cell-free sequence-defined libraries and run HSS across 64 active-site/tunnel residues for the three selected products.",
                "observation": "The workflow generated hundreds to thousands of mutants per day and the HSS covered 64 residues x 19 amino acids, yielding 1216 single mutants measured by LC-MS for each target product.",
                "parameters": {"selected_residues": 64, "single_mutants_per_product": 1216, "assay": "LC-MS HSS using cell-free expressed McbA variants"},
                "next_step_reason": "The resulting single-mutant data became the training set for ML models and the source of ISM hot spots.",
            }
        )
        add_or_replace_evidence(
            step4,
            [
                evidence(doc, "V16_0085_03", q_cfe, "Cell-free protein engineering workflow"),
                evidence(doc, "V16_0085_04", q_hss, "Hot spot screen"),
            ],
        )
        changes += 1

    if step5:
        step5.update(
            {
                "phase": "analysis",
                "action_type": "dry_experiment",
                "state_before": "The HSS produced single-mutant sequence-function data for multiple McbA target reactions.",
                "gap_or_uncertainty": "The next question was how to extrapolate from single mutants to high-performing higher-order variants.",
                "hypothesis": "Augmented ridge regression models that combine amino acid encodings with zero-shot predictors can rank useful higher-order McbA mutants.",
                "decision": "Fit and compare augmented ridge-regression model architectures using HSS single-mutant data.",
                "observation": "The paper evaluated amino-acid encodings and zero-shot predictors, later selecting an EVmutation probability-density model augmented with Georgiev encodings.",
                "parameters": {
                    "model_family": "augmented ridge regression",
                    "training_data": "single-site saturation data from HSS",
                    "selected_zero_shot_predictor": "EVmutation",
                    "selected_encoding": "Georgiev",
                },
                "next_step_reason": "The model architecture still required benchmarking against higher-order mutants from ISM.",
            }
        )
        add_or_replace_evidence(
            step5,
            [
                evidence(doc, "V16_0085_05", q_fit, "ML-guided, cell-free expression for protein engineering"),
                evidence(doc, "V16_0085_06", q_arch, "Model evaluation and selection"),
            ],
        )
        changes += 1

    if step6:
        step6.update(
            {
                "phase": "validation",
                "action_type": "wet_experiment",
                "state_before": "The HSS identified hot spots and the ML model needed higher-order mutant data for benchmarking.",
                "gap_or_uncertainty": "ISM could reveal whether path-dependent directed evolution found strong higher-order variants and where it failed.",
                "hypothesis": "Iterative saturation mutagenesis provides an experimental benchmark for ML extrapolation from single mutants.",
                "decision": "Run ISM campaigns for moclobemide, metoclopramide, and cinchocaine and use the resulting higher-order mutants for model benchmarking.",
                "observation": "Moclobemide ISM reached a quadruple mutant with 96% conversion and a 42-fold kinetic improvement, whereas the cinchocaine campaign stalled beyond a double mutant.",
                "parameters": {"benchmark_campaigns": ["moclobemide", "metoclopramide", "cinchocaine"], "moclobemide_ism_rounds": 3},
                "next_step_reason": "The ISM outcomes supplied withheld higher-order variants and a pressure test for evaluating model ranking.",
            }
        )
        add_or_replace_evidence(
            step6,
            [
                evidence(doc, "V16_0085_07", q_ism, "Iterative saturation mutagenesis benchmark"),
                evidence(doc, "V16_0085_08", q_cinch, "Cinchocaine ISM pressure test"),
            ],
        )
        changes += 1

    if step7:
        step7.update(
            {
                "phase": "analysis",
                "action_type": "dry_experiment",
                "state_before": "ISM provided higher-order mutant measurements for moclobemide, metoclopramide, and cinchocaine.",
                "gap_or_uncertainty": "The model had to be selected by its ability to rank high-fitness variants while reducing screening burden.",
                "hypothesis": "NDCG-based retrospective evaluation can identify the augmented model most useful for finding high-activity variants.",
                "decision": "Evaluate model ranking performance with NDCG and select the augmented EVmutation-Georgiev ridge model.",
                "observation": "Augmented models outperformed ridge regression alone, and the final selected model used the site-saturation dataset with EVmutation and Georgiev encodings.",
                "parameters": {"selection_metric": "NDCG", "withheld_data": "higher-order ISM mutants", "chosen_model": "EVmutation + Georgiev augmented ridge regression"},
                "next_step_reason": "With the model selected and trained, the paper could screen the full combinatorial space in silico.",
            }
        )
        add_or_replace_evidence(step7, [evidence(doc, "V16_0085_09", q_eval, "Model evaluation and selection")])
        changes += 1

    ml_screen_step = old_step3 or make_step(
        phase="analysis",
        action_type="dry_experiment",
        state_before="The augmented EVmutation-Georgiev model had been selected using HSS and ISM benchmark data.",
        gap="The full four-site combinatorial space was too large to test exhaustively in wet experiments.",
        hypothesis="The trained ML model can rank the full combinatorial mutant space and prioritize a small set of variants for experimental testing.",
        decision="Screen the full four-site combinatorial mutant space in silico and experimentally test the top predictions.",
        tool_name="ML-guided combinatorial variant ranking",
        tool_category="machine learning",
        parameters={},
        observation="The trained models screened the combinatorial space and selected top predictions for experimental testing.",
        result_status="success",
        next_reason="The experimentally tested ML predictions could then be compared against ISM and extended to more products.",
        evs=[],
    )
    ml_screen_step.update(
        {
            "phase": "analysis",
            "action_type": "dry_experiment",
            "state_before": "The EVmutation-Georgiev augmented ridge model was selected after retrospective evaluation on ISM-derived higher-order mutants.",
            "gap_or_uncertainty": "The authors needed to search a 160,000-variant combinatorial space without testing every candidate.",
            "hypothesis": "A trained single-objective ML model for each compound can enrich top-ranked variants for high activity.",
            "decision": "Screen 20^4 combinatorial McbA variants in silico for moclobemide, metoclopramide, and cinchocaine, then build and test the top 25 predictions.",
            "observation": "The ML-predicted variants were enriched for high activity; some surpassed ISM variants, though cinchocaine's best ISM mutant was not included among ML predictions.",
            "parameters": {"combinatorial_space": "20^4 / n=160,000", "predictions_tested": "top 25 per initial compound", "compounds": ["moclobemide", "metoclopramide", "cinchocaine"]},
            "next_step_reason": "The validated ML-ranking workflow was then reused for additional pharmaceutical products.",
        }
    )
    add_or_replace_evidence(
        ml_screen_step,
        [
            evidence(doc, "V16_0085_10", q_screen, "ML-guided directed evolution predicts top variants"),
            evidence(doc, "V16_0085_11", q_all, "Machine learning-guided directed evolution methods"),
        ],
    )
    changes += 1

    if step8:
        step8.update(
            {
                "phase": "experiment",
                "action_type": "wet_experiment",
                "state_before": "The ML-guided workflow had been benchmarked on moclobemide, metoclopramide, and cinchocaine.",
                "gap_or_uncertainty": "The paper still needed to test whether the same framework generalized beyond the initial three products.",
                "hypothesis": "The same HSS-plus-ML workflow can predict useful McbA specialists for additional pharmaceutical amidation reactions.",
                "decision": "Apply the ML-guided workflow to six additional pharmaceutical compounds and test the top predictions.",
                "observation": "Across the six additional compounds, the best variants improved yields by 1.6-fold to 34-fold and outperformed rationally combining the best HSS mutations.",
                "parameters": {"additional_compounds": 6, "predictions_tested": "top 24 per additional reaction", "reported_improvement_range": "1.6-fold to 34-fold"},
                "next_step_reason": "The generalized workflow result supported final comparison and detailed biochemical validation.",
            }
        )
        add_or_replace_evidence(step8, [evidence(doc, "V16_0085_12", q_six, "ML-guided biocatalytic diversification")])
        changes += 1

    if step9:
        step9["phase"] = "analysis"
        step9["action_type"] = "analysis"
        step9["state_before"] = "ML-predicted variants had been tested across initial and additional target reactions."
        step9["gap_or_uncertainty"] = "A practical design question remained: whether ML ranking beats simply combining the best single HSS mutations."
        step9["hypothesis"] = "ML can discover productive higher-order combinations that rationally combining top single mutants would miss."
        step9["decision"] = "Compare the best ML-predicted variant against the best rational design for each compound."
        step9["observation"] = "For each compound, the best predicted mutant outperformed the best rational design."
        step9["next_step_reason"] = "The strongest biochemical success case then required purified-enzyme and preparative validation."
        if q_six:
            add_or_replace_evidence(step9, [evidence(doc, "V16_0085_13", q_six, "ML-guided biocatalytic diversification")])
        changes += 1

    if step10:
        step10.update(
            {
                "phase": "validation",
                "action_type": "wet_experiment",
                "state_before": "The moclobemide campaign identified qm-McbA_moc as a strong engineered variant.",
                "gap_or_uncertainty": "The final variant needed quantitative kinetic characterization and preparative-scale confirmation.",
                "hypothesis": "The optimized moclobemide variant should show improved catalytic efficiency and synthesize isolable product at preparative scale.",
                "decision": "Purify and characterize qm-McbA_moc, then run a 10-mL preparative moclobemide reaction.",
                "observation": "qm-McbA_moc showed a 42-fold increase in catalytic efficiency and produced moclobemide in 58 mg, 87% isolated yield from a 10-mL reaction.",
                "parameters": {"variant": "qm-McbA_moc", "reaction_scale": "10 mL", "isolated_yield": "87%", "isolated_mass": "58 mg"},
                "next_step_reason": "This kinetic and preparative validation anchored the paper's final success claim.",
            }
        )
        add_or_replace_evidence(
            step10,
            [
                evidence(doc, "V16_0085_14", q_ism, "Kinetic characterization"),
                evidence(doc, "V16_0085_15", q_scale, "Preparative scale biosynthesis of moclobemide"),
            ],
        )
        changes += 1

    rebuilt: list[dict[str, Any]] = []
    seen_ids: set[int] = set()
    for candidate in [step1, step2, substrate_step, step4, step5, step6, step7, ml_screen_step, step8, step9, step10]:
        if candidate and id(candidate) not in seen_ids:
            rebuilt.append(candidate)
            seen_ids.add(id(candidate))
    case["evolution_trajectory"] = rebuilt
    success = case.setdefault("success_verification", {})
    success["final_conclusion"] = "ML-guided cell-free engineering mapped McbA sequence-function landscapes, used augmented ridge models to prioritize higher-order variants, and produced specialist enzymes with 1.6- to 42-fold activity improvements across nine pharmaceutical products."
    success["validation_methods"] = [
        "substrate-scope LC-MS screening",
        "cell-free HSS sequence-function mapping",
        "ISM benchmarking",
        "NDCG model evaluation",
        "top-prediction experimental testing",
        "purified-enzyme kinetics and preparative synthesis",
    ]
    note(case, "v16_quality_repair_0085")
    reindex_steps(case)
    return changes


def repair_0003(case: dict[str, Any], full_text: str) -> int:
    doc = "0003"
    changes = 0
    notes = case.get("quality_control", {}).get("risk_notes", [])
    if isinstance(notes, list) and "v16_quality_repair_0003" in notes:
        return 0
    steps = case.get("evolution_trajectory") or []

    step1 = find_step(case, lambda s: s.get("step_index") == 1)
    if step1:
        q1 = find_span(full_text, ["Cal-A is an unusual lipase", "short-chain", "long-chain"])
        step1["state_before"] = "Cal-A is an industrially relevant lipase with broad substrate scope, but the binding mode of bulky triglycerides and how to tune short-chain versus long-chain selectivity were unresolved."
        step1["gap_or_uncertainty"] = "A practical smart-library strategy was needed to explore Cal-A substrate-binding sequence space without making screening unmanageable."
        step1["hypothesis"] = "A Golden Gate smart-library workflow could combine targeted and random mutagenesis while keeping library construction and screening tractable."
        step1["decision"] = "Frame Cal-A selectivity and smart-library generation as the coupled engineering problem."
        step1["observation"] = "The paper motivates both the Cal-A substrate-selectivity target and the need for flexible recombination of mutated gene parts."
        step1["next_step_reason"] = "The target rationale leads to structural hotspot selection and part-wise library design."
        if q1:
            add_or_replace_evidence(step1, [evidence(doc, "V16_0003_01", q1, "Introduction")])
        changes += 1

    step3 = find_step(case, lambda s: s.get("step_index") == 3)
    if step3:
        q_arch = find_span(full_text, ["mother vector", "daughter vector", "recombined"], preferred=["BsaI", "SapI", "pelB"], limit=1600)
        q_enz = find_span(full_text, ["BsaI", "SapI", "customized overhangs"])
        step3.update(
            {
                "phase": "design",
                "action_type": "dry_experiment",
                "state_before": "Hotspots and the randomizable tunnel region were identified, but the paper needed a flexible way to recombine independently mutated Cal-A parts.",
                "gap_or_uncertainty": "Conventional random or single-site methods did not flexibly mix targeted and random mutagenesis products.",
                "hypothesis": "A three-part Golden Gate mother/daughter-vector architecture with customized BsaI/SapI junctions can recombine mutated and native parts scarlessly.",
                "decision": "Design the Cal-A library-generation platform around three codon-optimized parts in mother vectors and a pelB daughter expression vector.",
                "observation": "The architecture allowed independent mutation of parts and flexible recombination into complete Cal-A libraries.",
                "parameters": {
                    "parts": "part 1 includes Tyr93/Tyr183; part 2 is residues 211-350; part 3 contains Phe431/small loop",
                    "vectors": "DNA2.0 pM269 mother vectors and pD441pelB daughter vector",
                    "enzymes": "BsaI and SapI type IIS restriction enzymes",
                },
                "tool_or_method": {
                    "name": "Golden Gate mother/daughter-vector architecture",
                    "version": "",
                    "category": "library design",
                },
                "next_step_reason": "With the architecture designed, the parts could be mutated, assembled, transformed, and screened.",
            }
        )
        add_or_replace_evidence(
            step3,
            [
                evidence(doc, "V16_0003_02", q_arch, "Library design"),
                evidence(doc, "V16_0003_03", q_enz, "Library design"),
            ],
        )
        changes += 1

    step4_mutagenesis = find_step(case, lambda s: any(token in json.dumps(s, ensure_ascii=False).lower() for token in ("quikchange", "genemorph")))
    if step4_mutagenesis:
        q_methods = find_span(full_text, ["QuikChange Lightning", "GeneMorph II"], preferred=["Agilent", "randomly mutated"], limit=1000)
        append_evidence(
            step4_mutagenesis,
            [evidence(doc, "V16_0003_07", q_methods, "Materials and methods")],
        )
        changes += 1

    if not any("non-screenable" in json.dumps(s, ensure_ascii=False).lower() for s in steps):
        q_table = table_text_after(full_text, "Table 1. Mutated Cal-A libraries generated.", limit=1800)
        ns_step = make_step(
            phase="design",
            action_type="analysis",
            state_before="The targeted and random mutated parts existed first as separate mother-vector libraries.",
            gap="The paper distinguishes non-screenable part libraries from the assembled daughter-vector libraries that could enter the phenotype screen.",
            hypothesis="Only assembled full-gene daughter-vector libraries should proceed to expression and substrate-selectivity screening.",
            decision="Mark libraries 1-4 as non-screenable intermediates and route the screenable work through assembled libraries 5-10.",
            tool_name="Library table triage",
            tool_category="library planning",
            parameters={
                "non_screenable_libraries": "1-4: Tyr93, Tyr183, Phe431, and random part-2 mother-vector constructs",
                "screenable_assembled_libraries": "5-10: daughter-vector recombination libraries",
            },
            observation="Table 1 separates the mother-vector part libraries marked NS from the assembled daughter-vector libraries used for screening or later screening decisions.",
            result_status="success",
            next_reason="This triage links part-level mutagenesis to full-gene assembly before any phenotypic screening.",
            evs=[evidence(doc, "V16_0003_12", q_table, "Table 1 mutated Cal-A libraries")],
        )
        insert_at = steps.index(step4_mutagenesis) + 1 if step4_mutagenesis in steps else 4
        steps.insert(insert_at, ns_step)
        changes += 1

    step5 = find_step(case, lambda s: "no transformants" in json.dumps(s, ensure_ascii=False).lower())
    if step5:
        q = find_span(full_text, ["no transformants", "commercial", "pre-cut daughter plasmid"])
        step5.update(
            {
                "phase": "revision",
                "action_type": "analysis",
                "state_before": "Golden Gate assembly and transformation were being used to construct the mutated Cal-A libraries.",
                "gap_or_uncertainty": "One assembled library failed to yield transformants with the circularized daughter plasmid.",
                "hypothesis": "Using the commercial pre-cut daughter plasmid could rescue the failed Tyr93-Phe431 construction.",
                "decision": "Record and resolve the Tyr93-Phe431 no-transformants troubleshooting event during library construction.",
                "observation": "The no-transformants issue was resolved by switching to commercial pre-cut daughter plasmid.",
                "next_step_reason": "After construction troubleshooting, assembled libraries could proceed to sequencing/QC and screening.",
            }
        )
        if q:
            add_or_replace_evidence(step5, [evidence(doc, "V16_0003_04", q, "Library design")])
        changes += 1

    assembly_step = find_step(case, lambda s: "perform one-pot golden gate assembly" in str(s.get("decision", "")).lower())
    if assembly_step:
        q_flow = find_span(
            full_text,
            ["Facile reassembly", "one-pot restriction-ligation reaction using Bsal"],
            preferred=["Table 1", "Sapl", "daughter vector"],
            limit=1200,
        )
        q_scope = find_span(
            full_text,
            ["variety of complex, mutated libraries", "Table 1"],
            preferred=["NDT", "error prone PCR", "ten libraries"],
            limit=1600,
        )
        assembly_step["observation"] = "The standard Fig. 2 workflow generated the chosen complex mutated libraries for screening, including targeted single-site, targeted combination, and random part-2 combinations."
        assembly_step["next_step_reason"] = "The constructed library set still required assembly troubleshooting checks before expression and substrate-selectivity screening."
        append_evidence(
            assembly_step,
            [
                evidence(doc, "V16_0003_08", q_flow, "Fig. 2 assembly workflow"),
                evidence(doc, "V16_0003_09", q_scope, "Library design"),
            ],
        )
        changes += 1

    if not any("simplified one-pot assembly" in json.dumps(s, ensure_ascii=False).lower() for s in steps):
        q_simple = cut_after(
            find_span(
                full_text,
                ["Simplified one-pot assembly procedure", "directly transformed"],
                preferred=["mother vectors", "daughter vector"],
                limit=1100,
            ),
            "assembled by adding the ligase directly to the mixture.",
        )
        q_outcome = find_span(
            full_text,
            ["applied this simplified strategy", "reduced success rate", "standard method"],
            preferred=["wild-type Cal-A", "mutant parts", "solved the problem"],
            limit=900,
        )
        onepot_step = make_step(
            phase="revision",
            action_type="analysis",
            state_before="The standard Golden Gate workflow had been established for recombining independently mutated Cal-A parts.",
            gap="A shorter workflow might skip PCR pre-amplification, but it had to work for mutant-part recombination rather than only wild-type assembly.",
            hypothesis="Directly pooling the three mother vectors with the daughter vector in a single restriction-ligation reaction could simplify the assembly path.",
            decision="Record the simplified one-pot assembly as a rejected shortcut and retain the standard Fig. 2 workflow for mutant libraries.",
            tool_name="Simplified one-pot assembly test",
            tool_category="method troubleshooting",
            parameters={
                "tested_shortcut": "direct restriction-ligation of circular mother vectors with daughter vector",
                "successful_scope": "wild-type Cal-A construct",
                "failed_scope": "mutant-part recombination showed reduced ligation success",
            },
            observation="The shortcut worked for wild-type Cal-A clones, but mutant-part recombination had reduced ligation success; the standard Fig. 2 method solved the problem.",
            result_status="partial",
            next_reason="With the simplified shortcut rejected for mutant libraries, the workflow proceeds through the standard assembled-library route and remaining construction troubleshooting.",
            evs=[
                evidence(doc, "V16_0003_10", q_simple, "S7 Fig. simplified assembly"),
                evidence(doc, "V16_0003_11", q_outcome, "S7 Fig. simplified assembly"),
            ],
        )
        insert_at = steps.index(assembly_step) + 1 if assembly_step in steps else len(steps)
        steps.insert(insert_at, onepot_step)
        changes += 1

    step8 = find_step(case, lambda s: s.get("step_index") == 8)
    if step8:
        q = find_span(full_text, ["four 96-well plates", "20 μL", "Halo analysis is qualitative"], limit=1200)
        step8["phase"] = "experiment"
        step8["decision"] = "Execute the automated whole-cell halo screen using tributyrin and olive oil/rhodamine plates."
        step8["observation"] = "The robotized workflow spotted variants from four 96-well inoculum plates and used qualitative halos to score short-chain and long-chain activity."
        step8["next_step_reason"] = "The automated assay generated per-library activity and substrate-discrimination results."
        if q:
            add_or_replace_evidence(step8, [evidence(doc, "V16_0003_05", q, "Screening of Cal-A variants through automation by liquid handler robot")])
        changes += 1

    step9 = find_step(case, lambda s: s.get("step_index") == 9)
    if step9:
        q = find_span(full_text, ["A total of 735 clones", "88 clones", "39:1"], limit=1100)
        step9["phase"] = "validation"
        step9["observation"] = "Among 735 screened clones, 88 (12%) discriminated between short- and long-chain substrates. The qualitative counts were consistent with Tyr93 libraries showing more long-chain discrimination, Tyr183 substitutions being associated with substantial activity loss except a few short-chain-classified survivors, Phe431 not yielding stronger discrimination, and the random part-2 library giving a 39:1 short-chain to long-chain ratio."
        step9["parameters"] = {
            "total_screened": 735,
            "discriminating_clones": 88,
            "random_library_short_to_long_ratio": "39:1",
        }
        if q:
            add_or_replace_evidence(step9, [evidence(doc, "V16_0003_06", q, "Screening results")])
        changes += 1

    step4 = find_step(case, lambda s: "library 9 was not screened" in json.dumps(s, ensure_ascii=False).lower())
    if step4:
        step4.update(
            {
                "phase": "revision",
                "action_type": "analysis",
                "state_before": "Screening results from library 6 showed that most Tyr183 substitutions abolished activity.",
                "gap_or_uncertainty": "Whether to screen the Tyr183/Phe431 combined library remained after observing the Tyr183 result.",
                "hypothesis": "If only Tyr or Phe at position 183 preserved activity, screening the Tyr183/Phe431 combined library would be low value.",
                "decision": "Use the library 6 screening outcome to stop screening library 9.",
                "next_step_reason": "This screening-derived branch decision is part of the final interpretation of which Cal-A regions affected substrate selectivity.",
            }
        )
        changes += 1

    # Timeline-aware order for this method paper.
    def rank(step: dict[str, Any]) -> int:
        text = json.dumps(step, ensure_ascii=False).lower()
        if step is step1:
            return 10
        if step.get("step_index") == 2:
            return 20
        if step is step3:
            return 30
        if step.get("step_index") == 6:
            return 40
        if "non-screenable" in text:
            return 45
        if step.get("step_index") == 7:
            return 50
        if "simplified one-pot assembly" in text or "standard fig. 2 workflow" in text:
            return 53
        if step is step5:
            return 55
        if step is step8:
            return 60
        if step is step9:
            return 70
        if "library 9 was not screened" in text:
            return 75
        if step.get("step_index") == 10:
            return 80
        return 90 + int(step.get("step_index") or 0)

    case["evolution_trajectory"] = sorted(steps, key=rank)
    success = case.setdefault("success_verification", {})
    success["final_conclusion"] = "Golden Gate part-wise library generation plus automated qualitative whole-cell screening produced Cal-A variants with altered short-chain versus long-chain substrate discrimination."
    success["limitations"] = [
        "The automated halo assay is qualitative rather than quantitative.",
        "Halo diameter and intensity are affected by inoculum/cell-number variation.",
        "Library 9 was not screened after library 6 showed Tyr183 substitutions mostly abolished activity.",
    ]
    note(case, "v16_quality_repair_0003")
    reindex_steps(case)
    return changes


def repair_0130(case: dict[str, Any], full_text: str) -> int:
    doc = "0130"
    changes = 0
    steps = case.get("evolution_trajectory") or []

    step1 = find_step(case, lambda s: s.get("step_index") == 1)
    if step1:
        step1["next_step_reason"] = "This throughput and genotype-phenotype-linkage bottleneck motivates building a cell-free droplet/FACS platform before screening the mutant library."
        changes += 1

    overview_quote = find_span(full_text, ["Figure 1 summarizes", "seven steps"], preferred=["DNA recovery", "PCR"], limit=1300)
    overview_step = make_step(
        phase="design",
        action_type="literature_reasoning",
        state_before="Traditional MTP or agar screening undersampled large random cellulase libraries.",
        gap="A platform was needed to preserve genotype-phenotype linkage, sort active variants, and recover DNA for downstream validation or iteration.",
        hypothesis="An InVitroFlow workflow combining cell-free compartmentalization, FACS, DNA recovery, and MTP validation can cover much larger sequence space.",
        decision="Define the seven-step InVitroFlow campaign architecture before optimizing individual parameters.",
        tool_name="InVitroFlow seven-step workflow",
        tool_category="screening platform",
        parameters={
            "workflow": [
                "library generation",
                "w/o/w emulsion compartmentalization",
                "cell-free expression",
                "flow cytometry sorting",
                "DNA recovery/PCR",
                "cloning/transformation",
                "MTP screening and characterization",
            ],
            "throughput": "up to 10^7 events per hour",
        },
        observation="The platform links mutant genes, expressed cellulase variants, fluorescent product, sorting, DNA recovery, and downstream hit validation.",
        result_status="success",
        next_reason="The platform overview determines which emulsion, substrate, expression, and sorting conditions must be optimized.",
        evs=[evidence(doc, "V16_0130_01", overview_quote, "Results")],
    )

    if not any("seven-step" in str(s.get("decision", "")).lower() or "seven steps" in json.dumps(s, ensure_ascii=False).lower() for s in steps):
        insert_at = 1 if step1 in steps else 0
        steps.insert(insert_at + 1, overview_step)
        changes += 1

    bsa_quote = find_span(full_text, ["BSA", "26.45%"], preferred=["leakage", "4 h", "25"], limit=1000)
    time_temp_quote = find_span(full_text, ["after 4 h", "25"], preferred=["cell-free", "temperature"], limit=700)
    bsa_step = make_step(
        phase="experiment",
        action_type="wet_experiment",
        state_before="FDC/fluorescein had been selected as a sensitive substrate-product pair, but emulsion leakage and cell-free expression conditions still had to be controlled.",
        gap="The platform needed stable signal retention and sufficient in-emulsion cellulase production before real library sorting.",
        hypothesis="BSA supplementation plus optimized incubation time and temperature would reduce interface/leakage problems and improve detectable cellulase activity.",
        decision="Optimize BSA, incubation time, and incubation temperature for cell-free cellulase production in w/o/w emulsions.",
        tool_name="Flow cytometry condition optimization",
        tool_category="platform optimization",
        parameters={"BSA": "1 mg/ml or 1% BSA", "incubation_time": "4 h", "temperature": "25 C"},
        observation="The paper selected 1% BSA, 4 h incubation, and 25 C as conditions that supported usable fluorescent signal in emulsions.",
        result_status="success",
        next_reason="With leakage and expression conditions fixed, template DNA and FDC concentrations could be optimized for sorting.",
        evs=[
            evidence(doc, "V16_0130_02", bsa_quote, "Substrate selection and BSA optimization"),
            evidence(doc, "V16_0130_03", time_temp_quote, "Cell-free expression time and temperature optimization"),
        ],
    )
    if not any("BSA" in json.dumps(s, ensure_ascii=False) and "25" in json.dumps(s, ensure_ascii=False) for s in steps):
        # Insert after substrate selection step if possible.
        idx = next((i for i, s in enumerate(steps) if s.get("step_index") == 3), 2)
        steps.insert(idx + 1, bsa_step)
        changes += 1

    step4 = find_step(case, lambda s: s.get("step_index") == 4)
    if step4:
        q_range = find_span(full_text, ["model library", "0.164", "0.13"], preferred=["3:7", "template DNA"], limit=900)
        q = find_span(full_text, ["0.656", "23.9%", "0.46 mM FDC", "optimal conditions"], limit=1300)
        step4.update(
            {
                "phase": "experiment",
                "action_type": "wet_experiment",
                "state_before": "A 3:7 active-to-inactive model library was available to define a sorting window for high-mutational-load libraries.",
                "gap_or_uncertainty": "The selected template DNA and FDC concentrations had to produce enough fluorescent events without excessive background.",
                "hypothesis": "A specific DNA/FDC condition would separate active droplets from negative-control-like signal.",
                "decision": "Select final DNA and FDC concentrations for InVitroFlow sorting.",
                "observation": "Samples below 0.656 μM template DNA were comparable to negative control; 0.656 μM DNA produced 23.9% fluorescent events, and 0.46 mM FDC gave the best signal-to-noise. The final sorting recipe used 0.6561 μM DNA, 0.46 mM FDC, 1% BSA, 25 C, and 4 h.",
                "parameters": {
                    "selected_DNA": "0.6561 μM",
                    "selected_FDC": "0.46 mM",
                    "BSA": "1%",
                    "temperature": "25 C",
                    "incubation_time": "4 h",
                    "rejected_lower_DNA": "<0.656 μM was comparable to negative control",
                },
                "result_status": "success",
                "next_step_reason": "The optimized recipe was then used to validate sorting gates and screen the epPCR library.",
            }
        )
        if q:
            add_or_replace_evidence(
                step4,
                [
                    evidence(doc, "V16_0130_04_RANGE", q_range, "Optimization of sorting conditions"),
                    evidence(doc, "V16_0130_04_OPT", q, "Optimization of sorting conditions"),
                ],
        )
        changes += 1

    model_step = find_step(case, lambda s: "5:95 model library" in str(s.get("decision", "")) or "5:95" in json.dumps(s, ensure_ascii=False))
    if model_step:
        q_gate_background = find_span(
            full_text,
            ["5:95", "10:90", "1.2%"],
            preferred=["P1", "0% CelA2-H288F", "active-to-inactive"],
            limit=1300,
        )
        q_gate_enrichment = find_span(
            full_text,
            ["26% of the population", "46%", "5.3-fold"],
            preferred=["P1", "Poisson", "57%"],
            limit=1300,
        )
        model_step["decision"] = "Calibrate gate P1 with 0%, 5:95, 10:90, and 100% model libraries, then sort the 5:95 model library to validate enrichment."
        model_step["observation"] = "The model-library calibration established a low inactive-control background (1.2% above P1), increasing positive fractions for 5% and 10% active templates, and a 5.3-fold enrichment after sorting the 5:95 model library."
        model_step["parameters"] = {
            "model_ratios": ["0% active control", "5:95", "10:90", "100% active control"],
            "negative_control_above_P1": "1.2%",
            "five_percent_active_above_P1": "approx. 11%",
            "ten_percent_active_above_P1": "26%",
            "positive_control_above_P1": "46%",
            "event_rate": "1,500 events s^-1",
            "sorting_efficiency": "99.6%",
            "sorted_5_percent_enrichment": "5.3-fold",
        }
        model_step["next_step_reason"] = "This calibrated gate and enrichment result justified using the optimized InVitroFlow recipe for the epPCR mutant library."
        append_evidence(
            model_step,
            [
                evidence(doc, "V16_0130_09", q_gate_background, "Model-library gate calibration"),
                evidence(doc, "V16_0130_10", q_gate_enrichment, "Model-library gate calibration"),
            ],
        )
        changes += 1

    eppcr_step = find_step(case, lambda s: "8.5%" in json.dumps(s, ensure_ascii=False) or "epPCR library" in str(s.get("decision", "")))
    if eppcr_step:
        q_eppcr = find_span(
            full_text,
            ["An average mutation frequency", "12 randomly selected clones", "8.5%"],
            preferred=["1.4", "93.2%", "8.2-fold"],
            limit=1500,
        )
        eppcr_step["decision"] = "Generate an epPCR library with 0.05 mM MnCl2, estimate an average 8 mutations per gene from sequenced clones, and sort the top 8.5% fluorescent events."
        eppcr_step["observation"] = "The epPCR library showed an estimated average mutation frequency of 8 mutations per gene from 12 sequenced clones; sorting 1.4 x 10^7 events at the 8.5% gate produced an 8.2-fold enrichment after reanalysis."
        eppcr_step["parameters"] = {
            "events_analyzed": "1.4 x 10^7",
            "mutation_frequency": "estimated average 8 mutations per gene from 12 randomly selected clones",
            "sorting_efficiency": "93.2%",
            "sorting_gate": "8.5%",
            "enrichment_after_reanalysis": "8.2-fold",
        }
        append_evidence(eppcr_step, [evidence(doc, "V16_0130_11", q_eppcr, "Flow cytometry screening and sorting epPCR libraries")])
        changes += 1

    step7 = find_step(case, lambda s: s.get("step_index") == 7)
    if step7 and step7 in steps:
        q_recovery = find_span(full_text, ["optimized DNA recovery", "PCR amplification", "pET28a"], limit=1000)
        q_mtp = find_span(full_text, ["528 cellulase variants", "33 cellulase variants", "17.5-fold"], limit=1100)
        recovery = make_step(
            phase="experiment",
            action_type="wet_experiment",
            state_before="The epPCR library had been sorted by flow cytometry under optimized InVitroFlow conditions.",
            gap="Genes encoding sorted active droplets had to be recovered and moved into an expression host for quantitative validation.",
            hypothesis="Recovered emulsion DNA can be PCR amplified, cloned, and transformed for MTP rescreening.",
            decision="Recover sorted celA2 DNA, amplify it, clone into pET28a(+), and transform E. coli for downstream validation.",
            tool_name="DNA recovery, PCR, PLICing and transformation",
            tool_category="hit recovery",
            parameters={"vector": "pET28a(+)", "host": "E. coli BL21 Gold(DE3)"},
            observation="The sorted DNA pool was recovered, PCR amplified, cloned by PLICing, and transformed for MTP screening.",
            result_status="success",
            next_reason="Recovered variants could then be rescreened in MTP to identify robust improved cellulases.",
            evs=[evidence(doc, "V16_0130_05", q_recovery, "Directed evolution campaign")],
        )
        mtp = make_step(
            phase="validation",
            action_type="wet_experiment",
            state_before="Recovered variants were available in expression host format for MTP activity screening.",
            gap="The sorted pool still needed variant-level confirmation and best-hit selection.",
            hypothesis="MTP rescreening with 4-MUC and FDC follow-up would identify variants whose improvement was robust beyond the sorting substrate.",
            decision="Screen 528 recovered variants by MTP 4-MUC assay and confirm the best variant with FDC/fluorescein.",
            tool_name="MTP rescreening and FDC confirmation",
            tool_category="hit validation",
            parameters={"screened_variants": 528, "improved_variants": 33, "best_variant": "CelA2-H288F-M1"},
            observation="MTP analysis found 33 improved variants up to 7.2-fold over parent; M1 showed 17.5-fold improvement for FDC/fluorescein and carried N273D/N468S on the H288F parent.",
            result_status="success",
            next_reason="The best variant then required purification and kinetic characterization.",
            evs=[evidence(doc, "V16_0130_06", q_mtp, "Directed evolution campaign")],
        )
        idx = steps.index(step7)
        steps[idx : idx + 1] = [recovery, mtp]
        changes += 1

    step8 = find_step(case, lambda s: s.get("step_index") == 8 and "kinetic" in json.dumps(s, ensure_ascii=False).lower())
    if not step8:
        step8 = next((s for s in steps if "220.6" in json.dumps(s, ensure_ascii=False) or "13.3-fold" in json.dumps(s, ensure_ascii=False)), None)
    if step8:
        q_kin = find_span(full_text, ["purified", ">86", "13.3-fold"], limit=1000)
        q_table = find_span(full_text, ["CelA2-H288F-M1", "220.60", "N273D/H288F/N468S"], limit=1000)
        step8.update(
            {
                "phase": "validation",
                "action_type": "wet_experiment",
                "observation": "Purified CelA2-H288F-M1 (N273D/N468S added to H288F) showed comparable KM to the parent and a specific activity of 220.60 U/mg, corresponding to 13.3-fold over wild type and 3.0-fold over CelA2-H288F.",
                "parameters": {
                    "variant": "CelA2-H288F-M1",
                    "mutations": "N273D/H288F/N468S",
                    "specific_activity": "220.60 U/mg",
                    "kcat": "1.52 min^-1",
                    "KM": "9.66 μM",
                    "baseline_fold_changes": {"vs_wild_type": "13.3-fold", "vs_parent_H288F": "3.0-fold"},
                    "purity": ">86%",
                },
                "next_step_reason": "Kinetic validation confirmed the platform yielded an improved cellulase variant while revealing practical limits for future InVitroFlow development.",
            }
        )
        add_or_replace_evidence(
            step8,
            [
                evidence(doc, "V16_0130_07", q_kin, "Purification and kinetic characterization"),
                evidence(doc, "V16_0130_08", q_table, "Table 1 kinetic characterization"),
            ],
        )
        changes += 1

    success = case.setdefault("success_verification", {})
    success["final_conclusion"] = "InVitroFlow combined cell-free emulsion compartmentalization, flow cytometry sorting, DNA recovery, MTP rescreening, and kinetic validation to evolve CelA2-H288F into M1 with strong activity gains."
    success["validation_methods"] = [
        "flow cytometry model-library gate validation",
        "epPCR campaign sorting and reanalysis",
        "DNA recovery, PLICing, and transformation",
        "MTP rescreening",
        "kinetic characterization",
    ]
    success["metrics"] = [
        "throughput 6.5 x 10^6 events per hour",
        "1.4 x 10^7 events screened in the epPCR campaign",
        "33 improved variants from 528 MTP-screened variants",
        "M1 17.5-fold FDC/fluorescein improvement over CelA2-H288F",
        "M1 13.3-fold specific-activity improvement over wild type and 3.0-fold over CelA2-H288F",
    ]
    success["limitations"] = [
        "Limited efficiency of in vitro enzyme production within w/o/w emulsions.",
        "Fluorescence confinement and leakage/crosstalk remain technical challenges.",
        "Oversampling is required because only a subset of emulsion droplets contains gene template.",
        "Moving the platform to wheat-germ or other eukaryotic extracts is challenging.",
    ]
    note(case, "v16_quality_repair_0130")
    reindex_steps(case)
    return changes


def repair_0018(case: dict[str, Any], full_text: str) -> int:
    changes = 0
    step = find_step(case, lambda s: int(s.get("step_index") or 0) == 5)
    if step:
        params = step.get("parameters") if isinstance(step.get("parameters"), dict) else {}
        if params.get("cycles") == "typically 25-30":
            params["cycles"] = "first overlap PCR stage: 8 cycles; then 25 more cycles after flanking primers are added"
            step["parameters"] = params
            changes += 1
        if "25-30" in json.dumps(step, ensure_ascii=False):
            for key in TEXT_FIELDS:
                if isinstance(step.get(key), str):
                    step[key] = step[key].replace("25-30", "8 cycles followed by 25 additional cycles")
            changes += 1
    if changes:
        note(case, "v16_quality_repair_0018")
    return changes


def repair_0107(case: dict[str, Any], full_text: str) -> int:
    changes = 0
    step = find_step(case, lambda s: int(s.get("step_index") or 0) == 6)
    if step and ("0.74" in json.dumps(step, ensure_ascii=False) or "0.88" in json.dumps(step, ensure_ascii=False)):
        step["observation"] = (
            "ECNet predicted double-mutant fitness from single-mutant training data across six proteins and, for avGFP, "
            "higher-order training data improved prediction of quadruple mutants."
        )
        step["next_step_reason"] = (
            "The higher-order generalization test supports using ECNet rankings to guide protein engineering beyond the measured training set."
        )
        changes += 1
    if changes:
        note(case, "v16_quality_repair_0107")
    return changes


def repair_0118(case: dict[str, Any], full_text: str) -> int:
    changes = 0
    step = find_step(case, lambda s: int(s.get("step_index") or 0) == 8)
    if step and "7.2-fold" in str(step.get("observation", "")):
        step["observation"] = (
            "4D4 had kcat = 4.52 s^-1, Km = 0.390 mM, and kcat/Km 2.7-fold higher than WT; "
            "its H2O2 IC50 increased from 0.97 mM for WT to 7.03 mM, and purified protein yield increased to 2.70 mg."
        )
        changes += 1
    if changes:
        note(case, "v16_quality_repair_0118")
    return changes


def apply_v16_repairs(case: dict[str, Any], mineru_root: Path) -> dict[str, int]:
    d = doc_no(case)
    full_path = mineru_root / "docs" / d / "combined.md"
    stats = {
        "bad_evidence_removed": 0,
        "phase_action_fixed": 0,
        "phase_order_fixed": 0,
        "text_hygiene_fixed": 0,
        "numeric_parameters_normalized": 0,
        "reused_evidence_diversified": 0,
        "doc_specific_changes": 0,
        "invalid_evidence_removed": 0,
        "text_artifacts_fixed": 0,
        "missing_evidence_backfilled": 0,
        "entity_evidence_backfilled": 0,
        "numeric_evidence_backfilled": 0,
    }
    stats["bad_evidence_removed"] = remove_bad_evidence(case)
    stats["phase_action_fixed"] = fix_phase_action(case)
    stats["phase_order_fixed"] = repair_phase_order(case)
    stats["phase_action_fixed"] += fix_phase_action(case)
    stats["text_hygiene_fixed"] = fix_text_hygiene(case)
    stats["numeric_parameters_normalized"] = normalize_numeric_parameters(case)
    if not full_path.exists():
        note(case, "v16_missing_full_text")
        return stats
    full_text = full_path.read_text(encoding="utf-8", errors="replace")
    if d == "0015":
        stats["doc_specific_changes"] = repair_0015(case, full_text)
    elif d == "0044":
        stats["doc_specific_changes"] = repair_0044(case, full_text)
    elif d == "0085":
        stats["doc_specific_changes"] = repair_0085(case, full_text)
    elif d == "0003":
        stats["doc_specific_changes"] = repair_0003(case, full_text)
    elif d == "0130":
        stats["doc_specific_changes"] = repair_0130(case, full_text)
    elif d == "0018":
        stats["doc_specific_changes"] = repair_0018(case, full_text)
    elif d == "0107":
        stats["doc_specific_changes"] = repair_0107(case, full_text)
    elif d == "0118":
        stats["doc_specific_changes"] = repair_0118(case, full_text)
    generic_stats = repair_evidence_against_full_text(case, full_text, d)
    stats.update(generic_stats)
    stats["reused_evidence_diversified"] = diversify_reused_evidence(case, full_text, d)
    stats["phase_order_fixed"] += repair_phase_order(case)
    stats["phase_action_fixed"] += fix_phase_action(case)
    reindex_steps(case)
    return stats


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Build a V16.5 quality-first repaired pack from V15.2 candidates.")
    parser.add_argument("--input-dataset", default=r"outputs\submission_v15_2_core16_framework_repaired\dataset.jsonl")
    parser.add_argument("--mineru-root", default=r"D:\mineru_flat_results_20260521_200done")
    parser.add_argument("--output-dir", default=r"outputs\submission_v16_2_quality_repaired_probe")
    parser.add_argument("--case-ids", default="", help="Comma-separated doc numbers/case IDs. Empty or 'all' repairs every input case.")
    args = parser.parse_args()

    cases = read_jsonl(Path(args.input_dataset))
    wanted = set() if args.case_ids.strip().lower() == "all" else {x.strip() for x in args.case_ids.split(",") if x.strip()}
    normalized = set()
    for item in wanted:
        normalized.add(item)
        if item.isdigit():
            normalized.add(f"{int(item):04d}")
            normalized.add(f"sci_evo_{int(item):04d}")
    if normalized:
        cases = [case for case in cases if doc_no(case) in normalized or case.get("case_id") in normalized]
    cases = [copy.deepcopy(case) for case in cases]
    stats = {}
    for case in cases:
        stats[doc_no(case)] = apply_v16_repairs(case, Path(args.mineru_root))

    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    write_dataset_jsonl(out / "dataset.jsonl", cases)
    (out / "samples.json").write_text(json.dumps(cases, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "v16_5_quality_repair_summary.json").write_text(
        json.dumps({"case_count": len(cases), "stats": stats}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps({"case_count": len(cases), "output_dir": str(out), "stats": stats}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

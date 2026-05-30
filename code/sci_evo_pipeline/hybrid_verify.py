"""Hybrid code-plus-AI verification for Sci-Evo cases.

The verifier follows a claim-verification pattern:

1. Code extracts critical tokens and retrieves compact evidence packets.
2. AI judges step-level semantic support only inside the packet.
3. Code applies hard gates and aggregates final case decisions.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from .deepseek_client import DeepSeekClient
from .full_paper_repair import quote_errors_against_full_text
from .schema import validate_case


MUTATION_RE = re.compile(r"\b[A-Z][0-9]{1,4}[A-Z]\b")
VARIANT_RE = re.compile(r"\b[A-Z]{1,6}[-_][0-9]{1,4}\b")
NUMBER_RE = re.compile(
    r"(?<![A-Za-z])(?:~|\\~)?\d+(?:[.,]\d+)?(?:\s*(?:×|x|\\times)\s*10\^?\{?\d+\}?)?(?:\s*-\s*(?:to\s*)?(?:~|\\~)?\d+(?:[.,]\d+)?)?"
)
WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9_-]{2,}")
STOPWORDS = {
    "the",
    "and",
    "with",
    "for",
    "from",
    "that",
    "this",
    "into",
    "using",
    "were",
    "was",
    "are",
    "its",
    "their",
    "then",
    "than",
    "step",
    "variant",
    "variants",
    "enzyme",
    "activity",
    "assay",
    "analysis",
    "test",
    "perform",
}


@dataclass
class Passage:
    passage_id: str
    char_start: int
    char_end: int
    score: float
    text: str
    source: str


def squash(text: str) -> str:
    text = text or ""
    text = text.replace("×", "x").replace("μ", "u").replace("µ", "u")
    text = text.replace("\\times", "x").replace("\\~", "~")
    text = re.sub(r"\s+", " ", text)
    return text.strip().lower()


def compact_token(token: str) -> str:
    token = squash(token)
    token = token.replace(",", "")
    token = token.replace(" ", "")
    token = token.replace("{", "").replace("}", "")
    token = token.replace("^", "")
    token = token.replace("~", "")
    return token


def extract_entities(text: str) -> set[str]:
    out = set()
    for regex in [MUTATION_RE, VARIANT_RE]:
        for item in regex.findall(text or ""):
            token = compact_token(item)
            if token not in {"m-1", "s-1", "min-1", "h-1"}:
                out.add(token)
    return out


def extract_numbers(text: str) -> set[str]:
    out = set()
    for item in NUMBER_RE.findall(text or ""):
        token = compact_token(item)
        if token:
            out.add(token)
    return out


def extract_keywords(text: str, max_terms: int = 40) -> list[str]:
    counts: dict[str, int] = {}
    for word in WORD_RE.findall(text or ""):
        token = compact_token(word)
        if len(token) < 3 or token in STOPWORDS:
            continue
        counts[token] = counts.get(token, 0) + 1
    for token in extract_entities(text):
        counts[token] = counts.get(token, 0) + 5
    for token in extract_numbers(text):
        counts[token] = counts.get(token, 0) + 2
    return [token for token, _ in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:max_terms]]


def step_claim_text(step: dict[str, Any]) -> str:
    return " ".join(
        [
            str(step.get("decision", "")),
            str(step.get("observation", "")),
            str(step.get("next_step_reason", "")),
            str(step.get("hypothesis", "")),
            json.dumps(step.get("parameters", {}), ensure_ascii=False),
        ]
    )


def quote_contexts(full_text: str, step: dict[str, Any], *, radius: int = 2200) -> list[Passage]:
    passages: list[Passage] = []
    seen: set[tuple[int, int]] = set()
    idx = 1
    for ev in step.get("evidence") or []:
        if not isinstance(ev, dict):
            continue
        quote = str(ev.get("quote_or_span", "") or "")
        pos = full_text.find(quote)
        if pos < 0:
            seed = quote[:80]
            pos = full_text.find(seed) if seed else -1
        if pos < 0:
            continue
        start = max(0, pos - radius)
        end = min(len(full_text), pos + len(quote) + radius)
        key = (start, end)
        if key in seen:
            continue
        seen.add(key)
        passages.append(Passage(f"E{idx:02d}", start, end, 99.0, full_text[start:end], "cited_quote_context"))
        idx += 1
    return passages


def sliding_windows(full_text: str, *, window_chars: int = 1800, stride: int = 900) -> list[tuple[int, int, str]]:
    windows = []
    offset = 0
    while offset < len(full_text):
        end = min(len(full_text), offset + window_chars)
        windows.append((offset, end, full_text[offset:end]))
        if end >= len(full_text):
            break
        offset += stride
    return windows


def retrieve_passages(full_text: str, step: dict[str, Any], *, top_k: int = 6) -> list[Passage]:
    query_text = step_claim_text(step)
    terms = extract_keywords(query_text)
    if not terms:
        return []
    passages: list[Passage] = []
    for start, end, text in sliding_windows(full_text):
        normalized = squash(text)
        score = 0.0
        hits = 0
        for term in terms:
            if term and term in normalized:
                hits += 1
                score += 3.0 if re.match(r"^[a-z]\d+[a-z]$|^[a-z]+[-_]\d+$", term) else 1.0
        if hits:
            score += hits / max(len(terms), 1)
            passages.append(Passage("", start, end, score, text, "code_retrieval"))
    passages.sort(key=lambda p: (-p.score, p.char_start))
    out = []
    seen_ranges: list[tuple[int, int]] = []
    for p in passages:
        overlap = False
        for a, b in seen_ranges:
            if min(p.char_end, b) - max(p.char_start, a) > 600:
                overlap = True
                break
        if overlap:
            continue
        out.append(p)
        seen_ranges.append((p.char_start, p.char_end))
        if len(out) >= top_k:
            break
    for i, p in enumerate(out, start=1):
        p.passage_id = f"R{i:02d}"
    return out


def build_step_packet(case: dict[str, Any], step: dict[str, Any], full_text: str) -> dict[str, Any]:
    claim_text = step_claim_text(step)
    cited = quote_contexts(full_text, step)
    retrieved = retrieve_passages(full_text, step)
    passages = cited + [p for p in retrieved if all(abs(p.char_start - c.char_start) > 800 for c in cited)]
    return {
        "case_id": case.get("case_id", ""),
        "source": case.get("source", {}),
        "step": {
            "step_index": step.get("step_index"),
            "phase": step.get("phase"),
            "action_type": step.get("action_type"),
            "result_status": step.get("result_status"),
            "decision": step.get("decision", ""),
            "hypothesis": step.get("hypothesis", ""),
            "observation": step.get("observation", ""),
            "next_step_reason": step.get("next_step_reason", ""),
            "parameters": step.get("parameters", {}),
            "evidence": step.get("evidence", []),
        },
        "code_claim_tokens": {
            "entities": sorted(extract_entities(claim_text)),
            "numbers": sorted(extract_numbers(claim_text)),
            "keywords": extract_keywords(claim_text, max_terms=30),
        },
        "passages": [
            {
                "passage_id": p.passage_id,
                "source": p.source,
                "char_start": p.char_start,
                "char_end": p.char_end,
                "retrieval_score": round(p.score, 3),
                "text": p.text,
            }
            for p in passages[:10]
        ],
    }


VERIFY_SYSTEM = """You are a scientific claim verification judge.
You verify one Sci-Evo trajectory step using only the provided evidence packet.
Output valid JSON only.
Do not use outside knowledge. Do not assume unsupported details.
"""


def build_verify_prompt(packet: dict[str, Any]) -> str:
    return f"""Verify whether this Sci-Evo step is supported by the evidence packet.

Important rules:
1. The packet was retrieved by code from the full paper. Use only these passages.
2. Decompose the step into atomic claims from decision, observation, next_step_reason, and parameters.
3. Each atomic claim verdict must be one of: supported, partial, contradicted, not_enough_info.
4. A claim is supported only if the packet contains direct evidence or a near-explicit paraphrase.
5. If a number, mutation, variant, method, or metric differs, mark contradicted or partial.
6. supporting_quote must be an exact short substring copied from one passage in the packet.
7. Give final_step_verdict:
   - supported: key decision and observation are supported, no contradiction.
   - partial: useful but missing or over-specific detail.
   - contradicted: packet conflicts with a key claim.
   - not_enough_info: packet lacks enough evidence.
8. recommended_action must be keep, repair, or drop.

Expected JSON:
{{
  "step_index": 1,
  "atomic_claims": [
    {{
      "claim": "",
      "claim_type": "decision|observation|next_step_reason|parameter|method|metric",
      "verdict": "supported|partial|contradicted|not_enough_info",
      "passage_ids": ["E01"],
      "supporting_quote": "",
      "notes": ""
    }}
  ],
  "missing_or_conflicting_tokens": [],
  "final_step_verdict": "supported|partial|contradicted|not_enough_info",
  "support_score": 0.0,
  "recommended_action": "keep|repair|drop",
  "repair_instruction": ""
}}

Evidence packet:
{json.dumps(packet, ensure_ascii=False, indent=2)}
"""


def normalize_ai_step_review(raw: dict[str, Any], packet: dict[str, Any]) -> dict[str, Any]:
    step_index = packet.get("step", {}).get("step_index")
    try:
        step_index = int(raw.get("step_index") or step_index)
    except Exception:
        step_index = packet.get("step", {}).get("step_index")
    claims = []
    valid_verdicts = {"supported", "partial", "contradicted", "not_enough_info"}
    packet_text = "\n".join(p.get("text", "") for p in packet.get("passages") or [])
    for item in raw.get("atomic_claims") or []:
        if not isinstance(item, dict):
            continue
        quote = str(item.get("supporting_quote", "") or "")
        quote_exact = bool(quote and quote in packet_text)
        verdict = item.get("verdict") if item.get("verdict") in valid_verdicts else "not_enough_info"
        if quote and not quote_exact and verdict == "supported":
            verdict = "partial"
        claims.append(
            {
                "claim": str(item.get("claim", ""))[:600],
                "claim_type": item.get("claim_type", ""),
                "verdict": verdict,
                "passage_ids": item.get("passage_ids") if isinstance(item.get("passage_ids"), list) else [],
                "supporting_quote": quote[:500],
                "quote_exact_in_packet": quote_exact,
                "notes": str(item.get("notes", ""))[:600],
            }
        )
    final = raw.get("final_step_verdict") if raw.get("final_step_verdict") in valid_verdicts else "not_enough_info"
    if any(c["verdict"] == "contradicted" for c in claims):
        final = "contradicted"
    score = max(0.0, min(1.0, float(raw.get("support_score") or 0)))
    action = raw.get("recommended_action") if raw.get("recommended_action") in {"keep", "repair", "drop"} else "repair"
    if final == "supported" and score >= 0.85:
        action = "keep"
    elif final == "contradicted":
        action = "repair" if score >= 0.4 else "drop"
    elif final == "not_enough_info" and score < 0.5:
        action = "repair"
    return {
        "step_index": step_index,
        "final_step_verdict": final,
        "support_score": round(score, 3),
        "recommended_action": action,
        "atomic_claims": claims,
        "missing_or_conflicting_tokens": raw.get("missing_or_conflicting_tokens")
        if isinstance(raw.get("missing_or_conflicting_tokens"), list)
        else [],
        "repair_instruction": str(raw.get("repair_instruction", ""))[:800],
        "api_usage": raw.get("_api_usage", {}),
    }


def verify_step_with_ai(client: DeepSeekClient, packet: dict[str, Any]) -> dict[str, Any]:
    raw = client.chat_json(
        system_prompt=VERIFY_SYSTEM,
        user_prompt=build_verify_prompt(packet),
        temperature=0.0,
        max_tokens=4096,
    )
    return normalize_ai_step_review(raw, packet)


def hard_case_errors(case: dict[str, Any], full_text: str) -> list[str]:
    errors = validate_case(case)
    errors.extend(f"quote_full_text: {item}" for item in quote_errors_against_full_text(case, full_text))
    return errors


def aggregate_case_review(case: dict[str, Any], step_reviews: list[dict[str, Any]], hard_errors: list[str]) -> dict[str, Any]:
    if hard_errors:
        decision = "fail"
    elif any(r.get("final_step_verdict") == "contradicted" for r in step_reviews):
        decision = "repair"
    elif any(r.get("final_step_verdict") in {"partial", "not_enough_info"} for r in step_reviews):
        decision = "review"
    else:
        decision = "pass"
    avg = sum(float(r.get("support_score") or 0) for r in step_reviews) / max(len(step_reviews), 1)
    return {
        "case_id": case.get("case_id", ""),
        "doc_no": str(case.get("case_id", "")).split("_")[-1].zfill(4),
        "hybrid_decision": decision,
        "reviewed_steps": len(step_reviews),
        "average_hybrid_support": round(avg, 3),
        "hard_errors": hard_errors,
        "step_reviews": step_reviews,
    }

"""Evidence indexing and quote checks for quality-first runs."""

from __future__ import annotations

import hashlib
import html
import re
from pathlib import Path
from typing import Any

from .quality_schema import EvidenceSpan, QuoteCheck


MUTATION_RE = re.compile(r"\b[A-Z][a-z]{2}\d+[A-Z][a-z]{2}\b|\b[A-Z]\d+[A-Z]\b")
NUMBER_RE = re.compile(r"(?<![A-Za-z])[-+]?\d+(?:\.\d+)?(?:\s?(?:%|fold|x|uM|μM|mM|nM|°C|C|bp|kb|h|min|s))?")
METHOD_RE = re.compile(
    r"\b(?:Golden Gate|BsaI|SapI|NDT|Rosetta|screening|mutagenesis|PCR|FACS|HPLC|LC-MS|docking|MD|Bayesian|active learning)\b",
    re.IGNORECASE,
)
SECTION_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")


def normalize_text(text: str) -> str:
    text = html.unescape(text or "")
    text = re.sub(r"</(?:td|th)>\s*<t[dh][^>]*>", " | ", text, flags=re.I)
    text = re.sub(r"</tr>\s*<tr[^>]*>", " || ", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    replacements = {
        "鈥?": "-",
        "鈥揝": "-S",
        "鈥?": "-",
        "脳": "x",
        "渭": "μ",
        "碌": "μ",
        "掳": "°",
    }
    for src, dst in replacements.items():
        text = text.replace(src, dst)
    return re.sub(r"\s+", " ", text).strip()


def text_sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def is_bad_quote(text: str) -> str:
    compact = text.strip()
    lower = compact.lower()
    if not compact:
        return "empty_quote"
    if (
        "/vlm/images/" in lower
        or "mineru_output" in lower
        or ".pdf/vlm/images" in lower
        or "ng_direct_" in lower
        or re.search(r"\.(?:jpg|jpeg|png|webp|gif|svg)(?:[)\]\s]|$)", lower)
    ):
        return "image_path"
    if any(tag in lower for tag in ("<table", "<td", "<tr", "</table", "</td", "</tr")):
        return "raw_html_table_fragment"
    if compact.count("|") >= 6 and len(compact) < 500:
        return "markdown_table_fragment"
    if len(compact) < 24:
        return "too_short"
    weird = sum(1 for ch in compact if ord(ch) == 65533)
    if weird / max(len(compact), 1) > 0.02:
        return "mojibake_heavy"
    return ""


def split_markdown_sections(text: str) -> list[tuple[str, int, int, str]]:
    lines = text.splitlines(keepends=True)
    sections: list[tuple[str, int, int, str]] = []
    current = "front_matter"
    start = 0
    pos = 0
    for line in lines:
        match = SECTION_RE.match(line.strip())
        if match and pos > start:
            sections.append((current, start, pos, text[start:pos]))
            current = match.group(2).strip()[:160]
            start = pos
        elif match:
            current = match.group(2).strip()[:160]
            start = pos
        pos += len(line)
    if start < len(text):
        sections.append((current, start, len(text), text[start:]))
    return sections


def build_evidence_index(full_text: str, *, max_span_chars: int = 1400) -> list[EvidenceSpan]:
    spans: list[EvidenceSpan] = []
    for sec_idx, (section, sec_start, _sec_end, body) in enumerate(split_markdown_sections(full_text)):
        paragraphs = [p for p in re.split(r"\n\s*\n", body) if normalize_text(p)]
        running = sec_start
        para_idx = 0
        for para in paragraphs:
            local = full_text.find(para, running)
            if local < 0:
                local = running
            running = local + len(para)
            clean = normalize_text(para)
            if len(clean) > max_span_chars:
                chunks = [clean[i : i + max_span_chars] for i in range(0, len(clean), max_span_chars)]
            else:
                chunks = [clean]
            for chunk_idx, chunk in enumerate(chunks):
                if is_bad_quote(chunk):
                    continue
                span_id = f"s{sec_idx:03d}_p{para_idx:03d}_{chunk_idx:02d}"
                spans.append(
                    EvidenceSpan(
                        span_id=span_id,
                        section=section,
                        text=chunk,
                        char_start=local,
                        char_end=local + len(para),
                        sha256=text_sha(chunk),
                        numeric_tokens=sorted(set(m.group(0).strip() for m in NUMBER_RE.finditer(chunk) if m.group(0).strip())),
                        mutation_tokens=sorted(set(m.group(0).strip() for m in MUTATION_RE.finditer(chunk))),
                        method_tokens=sorted(set(m.group(0).strip() for m in METHOD_RE.finditer(chunk))),
                    )
                )
            para_idx += 1
    return spans


def check_quote(full_text: str, quote: str, *, section: str = "", step_index: int = 0, evidence_index: int = 0) -> QuoteCheck:
    warning = is_bad_quote(quote)
    exact_count = full_text.count(quote) if quote else 0
    normalized_full = normalize_text(full_text)
    normalized_quote = normalize_text(quote)
    normalized_count = normalized_full.count(normalized_quote) if normalized_quote else 0
    if not warning and not exact_count and not normalized_count:
        warning = "quote_not_found"
    return QuoteCheck(
        step_index=step_index,
        evidence_index=evidence_index,
        section=section,
        quote=quote,
        exact_match=exact_count > 0,
        normalized_match=normalized_count > 0,
        match_count=max(exact_count, normalized_count),
        warning=warning,
    )


def check_case_evidence(case: dict[str, Any], full_text_path: Path) -> list[QuoteCheck]:
    full_text = full_text_path.read_text(encoding="utf-8", errors="replace")
    checks: list[QuoteCheck] = []
    for step in case.get("evolution_trajectory") or []:
        step_index = int(step.get("step_index") or 0)
        for idx, ev in enumerate(step.get("evidence") or []):
            if not isinstance(ev, dict):
                continue
            checks.append(
                check_quote(
                    full_text,
                    str(ev.get("quote_or_span", "")),
                    section=str(ev.get("section", "")),
                    step_index=step_index,
                    evidence_index=idx,
                )
            )
    return checks

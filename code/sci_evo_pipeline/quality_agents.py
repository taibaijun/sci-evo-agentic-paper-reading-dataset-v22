"""AI reviewer prompts for quality-first Sci-Evo evaluation."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .deepseek_client import DeepSeekClient
from .quality_first import REVIEWER_ROLES, normalize_review


REVIEW_SYSTEM = """You are a strict quality-first Sci-Evo reviewer.
You must read the review packet carefully, including the embedded full paper and candidate JSON.
Your job is not to rewrite the final dataset. Your job is to find quality issues and produce structured JSON only.

Rules:
- If the full paper content is missing, return a repair verdict with evaluator_uncertain.
- Prefer severe, actionable findings over polite summaries.
- Check true paper storyline, mainline completeness, step order, factuality, evidence grounding, and dataset value.
- If a numeric value, mutation, method, or conclusion is not grounded by evidence, report it.
- If a platform/method paper is compressed into a generic directed-evolution summary, report it.
- If the candidate is repairable, give code-level repair actions.
- Output valid JSON only. No Markdown.
"""


FULL_PAPER_PATH_RE = re.compile(r"## Full Paper\s+.*?`([^`]+)`", re.DOTALL)


def embed_full_paper_content(packet_text: str, *, require_full_paper: bool = True) -> tuple[str, dict[str, Any]]:
    """Embed local full-paper text so API reviewers see the same context as local agents."""

    match = FULL_PAPER_PATH_RE.search(packet_text)
    if not match:
        if require_full_paper:
            raise FileNotFoundError("Review packet does not contain a full-paper path")
        return packet_text, {"full_paper_embedded": False, "full_paper_error": "missing_path"}

    full_text_path = Path(match.group(1))
    if not full_text_path.exists():
        if require_full_paper:
            raise FileNotFoundError(f"Full paper file not found: {full_text_path}")
        return packet_text, {"full_paper_embedded": False, "full_paper_path": str(full_text_path), "full_paper_error": "missing_file"}

    full_text = full_text_path.read_text(encoding="utf-8", errors="replace")
    embedded = (
        packet_text
        + "\n\n## Full Paper Content Embedded For API Review\n\n"
        + "<BEGIN_FULL_PAPER>\n"
        + full_text
        + "\n<END_FULL_PAPER>\n"
    )
    return embedded, {
        "full_paper_embedded": True,
        "full_paper_path": str(full_text_path),
        "full_paper_chars": len(full_text),
    }


def review_packet_with_deepseek(
    *,
    client: DeepSeekClient,
    packet_path: Path,
    role: str,
    temperature: float = 0.05,
    max_tokens: int = 8192,
    require_full_paper: bool = True,
) -> dict[str, Any]:
    if role not in REVIEWER_ROLES:
        raise ValueError(f"unknown reviewer role: {role}")
    packet_text = packet_path.read_text(encoding="utf-8")
    packet_text, full_paper_meta = embed_full_paper_content(packet_text, require_full_paper=require_full_paper)
    raw = client.chat_json(
        system_prompt=REVIEW_SYSTEM,
        user_prompt=packet_text,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    normalized = normalize_review(raw, fallback_role=role)
    normalized["_raw_review"] = raw
    normalized["_packet_path"] = str(packet_path)
    normalized["_full_paper"] = full_paper_meta
    return normalized

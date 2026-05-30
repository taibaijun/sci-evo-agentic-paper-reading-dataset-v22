"""Prompts for evidence-bound Sci-Evo extraction."""

from __future__ import annotations

import json
from typing import Any


SYSTEM_PROMPT = """You are a senior scientific data curator building a Sci-Evo dataset.
You extract scientific evolution trajectories from papers. You must output valid JSON only.
Do not invent scientific facts. Prefer "unknown" or [] when the evidence is missing.
Every trajectory step should be grounded in provided evidence snippets. Preserve quantitative metrics exactly when available.
The dataset values should be in English, because the source papers are English.
"""


SCHEMA_EXAMPLE: dict[str, Any] = {
    "case": {
        "case_id": "sci_evo_0001",
        "dataset_type": "Sci-Evo",
        "domain": "protein_engineering",
        "source": {
            "title": "",
            "doi": "",
            "url": "",
            "license": "",
            "publication_date": "",
            "raw_file": "",
            "mineru_md": "",
        },
        "initial_request": {
            "research_problem": "",
            "target_object": "",
            "known_context": "",
            "constraints": [],
            "input_data": [],
            "quantifiable_goals": [],
        },
        "evolution_trajectory": [
            {
                "step_index": 1,
                "phase": "hypothesis|design|simulation|experiment|analysis|revision|validation",
                "state_before": "",
                "gap_or_uncertainty": "",
                "hypothesis": "",
                "decision": "",
                "action_type": "dry_experiment|wet_experiment|analysis|literature_reasoning",
                "tool_or_method": {"name": "", "version": "", "category": ""},
                "parameters": {},
                "observation": "",
                "result_status": "success|failure|partial|inconclusive",
                "next_step_reason": "",
                "evidence": [
                    {
                        "evidence_id": "E01",
                        "source_file": "",
                        "section": "",
                        "quote_or_span": "",
                    }
                ],
            }
        ],
        "success_verification": {
            "validation_methods": [],
            "metrics": [],
            "final_conclusion": "",
            "limitations": [],
        },
        "quality_control": {
            "traceable": True,
            "human_reviewed": False,
            "evidence_coverage": 0.0,
            "risk_notes": [],
        },
    },
    "extraction_notes": {
        "suitability": "high|medium|low",
        "missing_evidence": [],
        "risk_notes": [],
    },
}


def build_user_prompt(context: dict[str, Any]) -> str:
    schema_text = json.dumps(SCHEMA_EXAMPLE, ensure_ascii=False, indent=2)
    context_text = json.dumps(context, ensure_ascii=False, indent=2)
    return f"""Extract one Sci-Evo case as strict json.

Task:
1. Read the source metadata and evidence snippets.
2. Build a machine-readable scientific evolution trajectory, not a generic paper summary.
3. Prefer 5-10 trajectory steps when the evidence supports them. Use fewer steps if the paper has a shorter chain.
4. Each step must include what was known, what gap remained, what decision was made, which tool/method was used, observed result, and why the next step followed.
5. `quote_or_span` must be an exact substring copied from the cited evidence snippet. Do not paraphrase, normalize symbols, add ellipses, or translate inside `quote_or_span`. Keep each quote short, ideally under 35 words.
6. Include failures, partial results, uncertainty, limitations, or revision steps when present.
7. If this source is only a review/perspective and lacks a concrete research trajectory, still produce the best evidence-bound case but mark suitability as low or medium and explain the risk.
8. If a useful claim is supported by a long or awkward passage, choose a short exact phrase from that passage as `quote_or_span`, then explain the interpretation in `observation` or `decision`.
9. Output valid json only. The word json is intentionally included for JSON mode.

Expected JSON shape:
{schema_text}

Source context:
{context_text}
"""

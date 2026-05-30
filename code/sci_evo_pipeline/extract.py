"""Extraction orchestration."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .corpus import build_evidence_context
from .deepseek_client import DeepSeekClient
from .prompts import SYSTEM_PROMPT, build_user_prompt
from .schema import normalize_case, repair_evidence_quotes, validate_case


def extract_record(
    *,
    input_root: Path,
    record: dict[str, Any],
    output_root: Path,
    client: DeepSeekClient,
    max_context_chars: int = 30000,
    overwrite: bool = False,
) -> dict[str, Any]:
    doc_no = str(record["doc_no"]).zfill(4)
    cases_dir = output_root / "cases"
    raw_dir = output_root / "raw_responses"
    context_dir = output_root / "contexts"
    for d in (cases_dir, raw_dir, context_dir):
        d.mkdir(parents=True, exist_ok=True)

    case_path = cases_dir / f"{doc_no}.json"
    if case_path.exists() and not overwrite:
        return json.loads(case_path.read_text(encoding="utf-8"))

    context = build_evidence_context(
        input_root=input_root,
        record=record,
        max_chars=max_context_chars,
    )
    context_path = context_dir / f"{doc_no}.json"
    context_path.write_text(json.dumps(context, ensure_ascii=False, indent=2), encoding="utf-8")

    response = client.chat_json(
        system_prompt=SYSTEM_PROMPT,
        user_prompt=build_user_prompt(context),
        temperature=0.05,
        max_tokens=8192,
    )
    raw_path = raw_dir / f"{doc_no}.json"
    raw_path.write_text(json.dumps(response, ensure_ascii=False, indent=2), encoding="utf-8")

    case = response.get("case") if isinstance(response.get("case"), dict) else response
    normalized = normalize_case(case, doc_no=doc_no, source=context["source"])
    repair_count = repair_evidence_quotes(normalized, context)
    errors = validate_case(normalized)
    output = {
        "case": normalized,
        "validation_errors": errors,
        "extraction_notes": response.get("extraction_notes", {}),
        "api_usage": response.get("_api_usage", {}),
        "api_model": response.get("_api_model", ""),
        "api_finish_reason": response.get("_api_finish_reason", ""),
        "evidence_repair_count": repair_count,
    }
    case_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    return output

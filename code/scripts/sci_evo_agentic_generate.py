from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sci_evo_pipeline.agentic import AgentRunConfig, generate_agentic_case
from sci_evo_pipeline.corpus import read_jsonl
from sci_evo_pipeline.deepseek_client import DeepSeekClient
from sci_evo_pipeline.schema import write_dataset_jsonl


REVIEW_TITLE_RE = re.compile(r"\b(review|perspective|commentary|survey)\b", re.I)
REVIEW_HEADER_RE = re.compile(r"(?im)^\s*(review|perspective|commentary)\s*$")


def is_review_like_record(row: dict[str, Any], input_root: Path) -> bool:
    title = str(row.get("title", ""))
    if REVIEW_TITLE_RE.search(title):
        return True
    md_rel = str(row.get("combined_md") or "")
    if not md_rel:
        return False
    md_path = input_root / md_rel
    if not md_path.exists():
        return False
    header = md_path.read_text(encoding="utf-8", errors="replace")[:6000]
    return bool(REVIEW_HEADER_RE.search(header) or re.search(r"\bthis review\b", header, re.I))


def select_records(
    rows: list[dict[str, Any]],
    doc_nos: list[str],
    limit: int,
    *,
    input_root: Path,
    include_review_like: bool = False,
) -> list[dict[str, Any]]:
    if doc_nos:
        wanted = {str(item).zfill(4) for item in doc_nos}
        return [
            row
            for row in rows
            if str(row.get("doc_no", "")).zfill(4) in wanted
            and (include_review_like or not is_review_like_record(row, input_root))
        ]
    selected: list[dict[str, Any]] = []
    for row in rows:
        if not include_review_like and is_review_like_record(row, input_root):
            continue
        selected.append(row)
        if len(selected) >= limit:
            break
    return selected


def now_run_id() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def summarize_result(result: dict[str, Any]) -> dict[str, Any]:
    case = result.get("case") or {}
    gate = result.get("deterministic_gate") or {}
    return {
        "case_id": case.get("case_id", ""),
        "doc_no": str(case.get("case_id", "")).split("_")[-1] if case else "",
        "gate_decision": gate.get("decision", "fail"),
        "step_count": gate.get("step_count", 0),
        "schema_error_count": len(gate.get("schema_errors") or []),
        "quote_error_count": len(gate.get("quote_errors") or []),
        "coverage_error_count": len(gate.get("coverage_errors") or []),
        "missing_step_evidence_count": len(gate.get("missing_step_evidence") or []),
        "warning_count": len(gate.get("warnings") or []),
        "revision_applied": "v22_revision_applied=1" in (case.get("quality_control", {}).get("risk_notes", []) if case else []),
        "state_path": result.get("state_path", ""),
        "events_path": result.get("events_path", ""),
        "error": result.get("error", ""),
        "api_usage": result.get("api_usage", {}),
    }


def add_usage(total: dict[str, int], usage: dict[str, Any]) -> None:
    for key, value in usage.items():
        if isinstance(value, int):
            total[key] = total.get(key, 0) + value


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="Generate V22 agentic Sci-Evo candidates with DeepSeek-v4-pro.")
    parser.add_argument("--input-root", default=r"D:\mineru_flat_results_20260521_200done")
    parser.add_argument("--index", default=r"outputs\sci_evo_index.jsonl")
    parser.add_argument("--output-root", default="", help="Defaults to outputs/agentic_v22/<run-id>.")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--doc-no", action="append", default=[], help="Specific doc number; repeatable.")
    parser.add_argument("--model", default="deepseek-v4-pro")
    parser.add_argument("--api-base", default=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"))
    parser.add_argument("--api-key-env", default="DEEPSEEK_API_KEY")
    parser.add_argument("--api-timeout", type=int, default=240)
    parser.add_argument("--api-retries", type=int, default=4)
    parser.add_argument("--thinking", choices=["enabled", "disabled"], default="disabled")
    parser.add_argument("--reasoning-effort", choices=["high", "max"], default="")
    parser.add_argument("--chunk-chars", type=int, default=18000)
    parser.add_argument("--chunk-overlap", type=int, default=900)
    parser.add_argument("--max-gist-sections", type=int, default=14)
    parser.add_argument("--max-section-chars", type=int, default=6500)
    parser.add_argument("--max-reading-chars", type=int, default=72000)
    parser.add_argument("--max-events-per-chunk", type=int, default=8)
    parser.add_argument("--include-review-like", action="store_true", help="Allow review/perspective/commentary sources in automatic selection.")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="Print selected records without calling the API or writing outputs.")
    args = parser.parse_args()

    if args.model != "deepseek-v4-pro":
        raise SystemExit("V22 agentic generation is fixed to --model deepseek-v4-pro; no fallback model is allowed.")

    rows = read_jsonl(Path(args.index))
    selected = select_records(
        rows,
        args.doc_no,
        args.limit,
        input_root=Path(args.input_root),
        include_review_like=args.include_review_like,
    )
    if args.dry_run:
        print(
            json.dumps(
                {
                    "selected_count": len(selected),
                    "selected": [
                        {
                            "doc_no": str(row.get("doc_no", "")).zfill(4),
                            "title": row.get("title", ""),
                            "relevance_score": row.get("relevance_score"),
                            "combined_md": row.get("combined_md", ""),
                        }
                        for row in selected
                    ],
                    "model": args.model,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return

    api_key = os.environ.get(args.api_key_env, "").strip()
    if not api_key:
        raise SystemExit(f"Missing API key. Set ${args.api_key_env} before running.")

    run_id = args.run_id or now_run_id()
    output_root = Path(args.output_root) if args.output_root else Path("outputs") / "agentic_v22" / run_id
    output_root.mkdir(parents=True, exist_ok=True)
    client = DeepSeekClient(
        api_key=api_key,
        model=args.model,
        base_url=args.api_base,
        timeout_sec=args.api_timeout,
        max_retries=args.api_retries,
        thinking=args.thinking,
        reasoning_effort=args.reasoning_effort or None,
    )
    config = AgentRunConfig(
        model=args.model,
        base_url=args.api_base,
        chunk_chars=args.chunk_chars,
        chunk_overlap=args.chunk_overlap,
        max_gist_sections=args.max_gist_sections,
        max_section_chars=args.max_section_chars,
        max_reading_chars=args.max_reading_chars,
        max_events_per_chunk=args.max_events_per_chunk,
    )

    accepted_cases = []
    rows_summary = []
    total_usage: dict[str, int] = {}
    for idx, record in enumerate(selected, start=1):
        doc_no = str(record.get("doc_no", "")).zfill(4)
        if not args.include_review_like and is_review_like_record(record, Path(args.input_root)):
            row = {
                "case_id": f"sci_evo_{doc_no}",
                "doc_no": doc_no,
                "gate_decision": "skipped",
                "step_count": 0,
                "schema_error_count": 0,
                "quote_error_count": 0,
                "coverage_error_count": 0,
                "missing_step_evidence_count": 0,
                "warning_count": 1,
                "revision_applied": False,
                "state_path": "",
                "events_path": "",
                "error": "skipped_review_like_source",
                "api_usage": {},
            }
            rows_summary.append(row)
            print(f"[{idx}/{len(selected)}] skip-review-like {doc_no}: {str(record.get('title', ''))[:100]}", flush=True)
            continue
        print(f"[{idx}/{len(selected)}] agentic-generate {doc_no}: {str(record.get('title', ''))[:100]}", flush=True)
        result = generate_agentic_case(
            input_root=Path(args.input_root),
            record=record,
            output_root=output_root,
            client=client,
            config=config,
            overwrite=args.overwrite,
        )
        gate = result.get("deterministic_gate") or {}
        case = result.get("case")
        if case and gate.get("decision") == "pass":
            accepted_cases.append(case)
        row = summarize_result(result)
        rows_summary.append(row)
        add_usage(total_usage, result.get("api_usage") or {})
        print(
            "  "
            + json.dumps(
                {
                    "gate": row["gate_decision"],
                    "steps": row["step_count"],
                    "schema_errors": row["schema_error_count"],
                    "quote_errors": row["quote_error_count"],
                    "coverage_errors": row["coverage_error_count"],
                    "warnings": row["warning_count"],
                    "state": row["state_path"],
                },
                ensure_ascii=False,
            ),
            flush=True,
        )

    dataset_path = output_root / "dataset.jsonl"
    write_dataset_jsonl(dataset_path, accepted_cases)
    summary = {
        "run_id": run_id,
        "model": args.model,
        "input_root": str(Path(args.input_root)),
        "index": str(Path(args.index)),
        "output_root": str(output_root),
        "selected_count": len(selected),
        "accepted_count": len(accepted_cases),
        "failed_or_rejected_count": len(selected) - len(accepted_cases),
        "dataset_jsonl": str(dataset_path),
        "total_api_usage": total_usage,
        "cases": rows_summary,
    }
    (output_root / "run_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sci_evo_pipeline.deepseek_client import DeepSeekClient
from sci_evo_pipeline.hybrid_verify import (
    aggregate_case_review,
    build_step_packet,
    hard_case_errors,
    verify_step_with_ai,
)


def read_jsonl(path: Path) -> list[dict]:
    rows = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def doc_no(case: dict) -> str:
    return str(case.get("case_id", "")).split("_")[-1].zfill(4)


def load_rule_detail(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    rows = json.loads(path.read_text(encoding="utf-8"))
    return {str(row.get("doc_no", "")).zfill(4): row for row in rows}


def flagged_steps_from_rule(row: dict) -> set[int]:
    steps: set[int] = set()
    for message in (row.get("errors") or []) + (row.get("warnings") or []):
        if (
            "mutation/variant tokens not in this step evidence quote" not in message
            and "ai_fullpaper_review_not_strict" not in message
        ):
            continue
        m = re.search(r"step\s+(\d+)", message)
        if m:
            steps.add(int(m.group(1)))
    return steps


def select_steps(case: dict, rule_row: dict | None, scope: str) -> list[dict]:
    steps = case.get("evolution_trajectory") or []
    if scope == "all":
        return steps
    if not rule_row:
        return []
    flagged = flagged_steps_from_rule(rule_row)
    if scope == "review_cases" and rule_row.get("rule_decision") == "review":
        return steps
    return [step for step in steps if int(step.get("step_index") or 0) in flagged]


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Run hybrid code+AI step verification.")
    parser.add_argument("--dataset-jsonl", default=r"dataset.jsonl")
    parser.add_argument("--mineru-root", default=r"mineru_results")
    parser.add_argument("--rule-detail", default=r"audits\rule_audit\rule_audit_detail.json")
    parser.add_argument("--output-root", default=r"outputs\hybrid_verify_v3")
    parser.add_argument("--scope", choices=["flagged", "review_cases", "all"], default="flagged")
    parser.add_argument("--model", default="deepseek-v4-flash")
    parser.add_argument("--api-base", default="https://api.deepseek.com")
    parser.add_argument("--api-key-env", default="DEEPSEEK_API_KEY")
    parser.add_argument("--limit-cases", type=int, default=0)
    parser.add_argument("--limit-steps", type=int, default=0)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    api_key = os.environ.get(args.api_key_env, "").strip()
    if not api_key:
        raise SystemExit(f"Missing API key. Set ${args.api_key_env} before running.")

    output_root = Path(args.output_root)
    cases_dir = output_root / "cases"
    packets_dir = output_root / "packets"
    cases_dir.mkdir(parents=True, exist_ok=True)
    packets_dir.mkdir(parents=True, exist_ok=True)

    client = DeepSeekClient(api_key=api_key, model=args.model, base_url=args.api_base)
    rule_by_doc = load_rule_detail(Path(args.rule_detail))
    cases = read_jsonl(Path(args.dataset_jsonl))

    case_summaries = []
    step_counter = 0
    case_counter = 0
    for case in cases:
        d = doc_no(case)
        rule_row = rule_by_doc.get(d)
        selected_steps = select_steps(case, rule_row, args.scope)
        if not selected_steps:
            continue
        case_counter += 1
        if args.limit_cases and case_counter > args.limit_cases:
            break
        md_path = Path(args.mineru_root) / "docs" / d / "combined.md"
        if not md_path.exists():
            print(f"[missing] {d} {md_path}", flush=True)
            continue
        full_text = md_path.read_text(encoding="utf-8", errors="replace")
        hard_errors = hard_case_errors(case, full_text)
        step_reviews = []
        print(f"[case {d}] selected_steps={len(selected_steps)} hard_errors={len(hard_errors)}", flush=True)
        for step in selected_steps:
            step_index = int(step.get("step_index") or 0)
            if args.limit_steps and step_counter >= args.limit_steps:
                break
            out_path = cases_dir / f"{d}_step{step_index:02d}.json"
            packet_path = packets_dir / f"{d}_step{step_index:02d}.json"
            if out_path.exists() and not args.overwrite:
                review = json.loads(out_path.read_text(encoding="utf-8"))
                print(f"  [cached] step {step_index} verdict={review.get('final_step_verdict')}", flush=True)
            else:
                packet = build_step_packet(case, step, full_text)
                packet_path.write_text(json.dumps(packet, ensure_ascii=False, indent=2), encoding="utf-8")
                print(
                    f"  [verify] step {step_index} passages={len(packet.get('passages', []))} "
                    f"entities={packet.get('code_claim_tokens', {}).get('entities', [])}",
                    flush=True,
                )
                review = verify_step_with_ai(client, packet)
                out_path.write_text(json.dumps(review, ensure_ascii=False, indent=2), encoding="utf-8")
                print(
                    f"    verdict={review.get('final_step_verdict')} score={review.get('support_score')} "
                    f"action={review.get('recommended_action')}",
                    flush=True,
                )
            step_reviews.append(review)
            step_counter += 1
        summary = aggregate_case_review(case, step_reviews, hard_errors)
        (cases_dir / f"{d}_summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        case_summaries.append(summary)
        if args.limit_steps and step_counter >= args.limit_steps:
            break

    summary_rows = [
        {
            "doc_no": row["doc_no"],
            "case_id": row["case_id"],
            "hybrid_decision": row["hybrid_decision"],
            "reviewed_steps": row["reviewed_steps"],
            "average_hybrid_support": row["average_hybrid_support"],
            "hard_errors": len(row["hard_errors"]),
            "contradicted_steps": sum(1 for s in row["step_reviews"] if s.get("final_step_verdict") == "contradicted"),
            "partial_steps": sum(1 for s in row["step_reviews"] if s.get("final_step_verdict") == "partial"),
            "nei_steps": sum(1 for s in row["step_reviews"] if s.get("final_step_verdict") == "not_enough_info"),
        }
        for row in case_summaries
    ]
    if summary_rows:
        with (output_root / "hybrid_case_report.csv").open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(summary_rows[0].keys()))
            writer.writeheader()
            writer.writerows(summary_rows)
    final_summary = {
        "dataset": args.dataset_jsonl,
        "scope": args.scope,
        "case_count": len(case_summaries),
        "reviewed_steps": sum(row["reviewed_steps"] for row in case_summaries),
        "pass": sum(1 for row in case_summaries if row["hybrid_decision"] == "pass"),
        "review": sum(1 for row in case_summaries if row["hybrid_decision"] == "review"),
        "repair": sum(1 for row in case_summaries if row["hybrid_decision"] == "repair"),
        "fail": sum(1 for row in case_summaries if row["hybrid_decision"] == "fail"),
    }
    (output_root / "hybrid_summary.json").write_text(
        json.dumps(final_summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(final_summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

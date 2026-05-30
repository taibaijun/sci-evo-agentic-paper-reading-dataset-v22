from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sci_evo_pipeline.deepseek_client import DeepSeekClient
from sci_evo_pipeline.fullpaper_eval import deterministic_gate, run_fullpaper_eval


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def doc_no(case: dict[str, Any]) -> str:
    return str(case.get("case_id", "")).split("_")[-1].zfill(4)


def load_rule_detail(path: Path | None) -> dict[str, dict[str, Any]]:
    if not path or not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    out = {}
    for item in data:
        if isinstance(item, dict):
            d = str(item.get("doc_no", "")).zfill(4)
            if d:
                out[d] = item
    return out


def summarize_issue_tags(review: dict[str, Any]) -> list[str]:
    tags = []
    for tag in review.get("audit", {}).get("systemic_error_tags", []):
        tags.append(str(tag))
    for step in review.get("audit", {}).get("step_audits", []):
        if step.get("verdict") not in {"supported"}:
            tags.append(f"step_{step.get('verdict')}")
        if step.get("severity") in {"medium", "high"}:
            tags.append(f"severity_{step.get('severity')}")
    for item in review.get("audit", {}).get("missing_mainline_events", []):
        tags.append(f"missing_{item.get('severity')}")
    if review.get("redteam"):
        for item in review["redteam"].get("missed_blockers", []):
            tags.append(f"redteam_{item.get('severity')}")
    return sorted(set(t for t in tags if t))


def review_to_row(review: dict[str, Any]) -> dict[str, Any]:
    gate = review.get("gate", {})
    audit = review.get("audit", {})
    scores = audit.get("dimension_scores", {})
    return {
        "doc_no": review.get("doc_no", ""),
        "case_id": review.get("case_id", ""),
        "title": review.get("title", ""),
        "gate_decision": gate.get("gate_decision", ""),
        "gate_reasons": "; ".join(gate.get("gate_reasons", [])),
        "avg_dimension_score": gate.get("avg_dimension_score", ""),
        "min_dimension_score": gate.get("min_dimension_score", ""),
        "factuality": scores.get("factuality", ""),
        "mainline_completeness": scores.get("mainline_completeness", ""),
        "trajectory_coherence": scores.get("trajectory_coherence", ""),
        "evidence_grounding": scores.get("evidence_grounding", ""),
        "competition_value": scores.get("competition_value", ""),
        "high_step_issue_count": gate.get("high_step_issue_count", ""),
        "medium_step_issue_count": gate.get("medium_step_issue_count", ""),
        "high_missing_count": gate.get("high_missing_count", ""),
        "medium_missing_count": gate.get("medium_missing_count", ""),
        "redteam_high_blockers": gate.get("redteam_high_blockers", ""),
        "ai_invalid_quote_count": gate.get("ai_invalid_quote_count", ""),
        "evaluator_warnings": "; ".join(gate.get("evaluator_warnings", [])),
        "chunk_count": review.get("coverage", {}).get("chunk_count", ""),
        "events_extracted": review.get("coverage", {}).get("events_extracted", ""),
        "issue_tags": "; ".join(summarize_issue_tags(review)),
        "summary": audit.get("one_sentence_summary", ""),
    }


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="Local full-paper AI evaluator for Sci-Evo candidate datasets.")
    parser.add_argument("--dataset-jsonl", required=True)
    parser.add_argument("--mineru-root", default=r"D:\mineru_flat_results_20260521_200done")
    parser.add_argument("--rule-detail", default="")
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--api-key-env", default="DEEPSEEK_API_KEY")
    parser.add_argument("--api-base", default="https://api.deepseek.com")
    parser.add_argument("--model", default="deepseek-v4-flash")
    parser.add_argument("--api-timeout", type=int, default=180)
    parser.add_argument("--api-retries", type=int, default=4)
    parser.add_argument("--chunk-chars", type=int, default=18000)
    parser.add_argument("--overlap", type=int, default=900)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--case-ids", default="", help="Comma-separated case ids or doc numbers to evaluate.")
    parser.add_argument("--no-redteam", action="store_true")
    parser.add_argument("--recompute-gate", action="store_true", help="Recompute deterministic gates for cached reviews.")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    api_key = os.environ.get(args.api_key_env, "").strip()
    if not api_key:
        raise SystemExit(f"Missing API key. Set ${args.api_key_env} before running.")

    cases = read_jsonl(Path(args.dataset_jsonl))
    wanted = {x.strip() for x in args.case_ids.split(",") if x.strip()}
    if wanted:
        normalized = set()
        for item in wanted:
            normalized.add(item)
            if item.isdigit():
                normalized.add(f"sci_evo_{int(item):04d}")
                normalized.add(f"{int(item):04d}")
        cases = [c for c in cases if c.get("case_id") in normalized or doc_no(c) in normalized]
    if args.limit:
        cases = cases[: args.limit]

    output_root = Path(args.output_root)
    reviews_dir = output_root / "reviews"
    reviews_dir.mkdir(parents=True, exist_ok=True)
    rule_map = load_rule_detail(Path(args.rule_detail) if args.rule_detail else None)
    client = DeepSeekClient(
        api_key=api_key,
        model=args.model,
        base_url=args.api_base,
        timeout_sec=args.api_timeout,
        max_retries=args.api_retries,
    )
    mineru_root = Path(args.mineru_root)
    rows = []

    for i, case in enumerate(cases, start=1):
        d = doc_no(case)
        out_path = reviews_dir / f"{d}.json"
        if out_path.exists() and not args.overwrite:
            review = json.loads(out_path.read_text(encoding="utf-8"))
            if args.recompute_gate:
                review["gate"] = deterministic_gate(
                    audit=review.get("audit", {}),
                    redteam=review.get("redteam"),
                    chunk_reviews=review.get("chunk_reviews", []),
                    storyline=review.get("storyline", {}),
                )
                out_path.write_text(json.dumps(review, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"[{i}/{len(cases)}] cached {d} gate={review.get('gate', {}).get('gate_decision')}", flush=True)
        else:
            md_path = mineru_root / "docs" / d / "combined.md"
            if not md_path.exists():
                print(f"[{i}/{len(cases)}] missing full paper {d}: {md_path}", flush=True)
                continue
            full_text = md_path.read_text(encoding="utf-8", errors="replace")
            print(
                f"[{i}/{len(cases)}] fullpaper-eval {d} chars={len(full_text)} "
                f"title={case.get('source', {}).get('title', '')[:80]}",
                flush=True,
            )
            try:
                review = run_fullpaper_eval(
                    client=client,
                    case=case,
                    full_text=full_text,
                    rule_audit=rule_map.get(d),
                    chunk_chars=args.chunk_chars,
                    overlap=args.overlap,
                    redteam=not args.no_redteam,
                )
            except Exception as exc:
                review = {
                    "case_id": case.get("case_id", ""),
                    "doc_no": d,
                    "title": case.get("source", {}).get("title", ""),
                    "coverage": {"full_text_chars": len(full_text), "chunk_count": "", "events_extracted": ""},
                    "storyline": {},
                    "audit": {
                        "dimension_scores": {
                            "factuality": 0,
                            "mainline_completeness": 0,
                            "trajectory_coherence": 0,
                            "evidence_grounding": 0,
                            "competition_value": 0,
                        },
                        "step_audits": [],
                        "missing_mainline_events": [],
                        "systemic_error_tags": ["evaluator_runtime_error"],
                        "final_verdict": "fail",
                        "one_sentence_summary": f"Evaluator runtime error: {type(exc).__name__}: {str(exc)[:500]}",
                    },
                    "redteam": None,
                    "gate": {
                        "gate_decision": "error",
                        "gate_reasons": [f"evaluator_runtime_error={type(exc).__name__}: {str(exc)[:500]}"],
                        "avg_dimension_score": 0,
                        "min_dimension_score": 0,
                        "high_step_issue_count": 0,
                        "medium_step_issue_count": 0,
                        "high_missing_count": 0,
                        "medium_missing_count": 0,
                        "redteam_high_blockers": 0,
                        "ai_invalid_quote_count": 0,
                        "evaluator_warnings": ["runtime_error"],
                    },
                    "chunk_reviews": [],
                }
            out_path.write_text(json.dumps(review, ensure_ascii=False, indent=2), encoding="utf-8")
            gate = review["gate"]
            print(
                f"  gate={gate['gate_decision']} avg={gate['avg_dimension_score']} "
                f"high_step={gate['high_step_issue_count']} high_missing={gate['high_missing_count']} "
                f"chunks={review['coverage']['chunk_count']} events={review['coverage']['events_extracted']}",
                flush=True,
            )
        rows.append(review_to_row(review))

    if rows:
        csv_path = output_root / "fullpaper_eval_report.csv"
        with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)

    summary = {
        "dataset": args.dataset_jsonl,
        "case_count": len(rows),
        "pass": sum(1 for r in rows if r["gate_decision"] == "pass"),
        "repair": sum(1 for r in rows if r["gate_decision"] == "repair"),
        "fail": sum(1 for r in rows if r["gate_decision"] == "fail"),
        "error": sum(1 for r in rows if r["gate_decision"] == "error"),
        "avg_dimension_score": round(sum(float(r["avg_dimension_score"] or 0) for r in rows) / max(len(rows), 1), 3),
        "min_dimension_score": min((float(r["min_dimension_score"] or 0) for r in rows), default=0),
        "high_step_issue_total": sum(int(r["high_step_issue_count"] or 0) for r in rows),
        "medium_step_issue_total": sum(int(r["medium_step_issue_count"] or 0) for r in rows),
        "high_missing_total": sum(int(r["high_missing_count"] or 0) for r in rows),
        "medium_missing_total": sum(int(r["medium_missing_count"] or 0) for r in rows),
        "redteam_high_blockers_total": sum(int(r["redteam_high_blockers"] or 0) for r in rows),
    }
    (output_root / "fullpaper_eval_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

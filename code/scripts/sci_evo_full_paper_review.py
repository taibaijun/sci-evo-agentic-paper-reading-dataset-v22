from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sci_evo_pipeline.deepseek_client import DeepSeekClient
from sci_evo_pipeline.full_paper_review import run_full_paper_review


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


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Run full-paper AI review over selected Sci-Evo cases.")
    parser.add_argument("--dataset-jsonl", default=r"dataset.jsonl")
    parser.add_argument("--mineru-root", default=r"mineru_results")
    parser.add_argument("--output-root", default=r"outputs\full_paper_review_v2")
    parser.add_argument("--model", default="deepseek-v4-flash")
    parser.add_argument("--api-base", default="https://api.deepseek.com")
    parser.add_argument("--api-key-env", default="DEEPSEEK_API_KEY")
    parser.add_argument("--chunk-chars", type=int, default=26000)
    parser.add_argument("--overlap", type=int, default=1000)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    api_key = os.environ.get(args.api_key_env, "").strip()
    if not api_key:
        raise SystemExit(f"Missing API key. Set ${args.api_key_env} before running.")
    client = DeepSeekClient(api_key=api_key, model=args.model, base_url=args.api_base)
    cases = read_jsonl(Path(args.dataset_jsonl))
    if args.limit:
        cases = cases[: args.limit]
    output_root = Path(args.output_root)
    reviews_dir = output_root / "reviews"
    reviews_dir.mkdir(parents=True, exist_ok=True)
    mineru_root = Path(args.mineru_root)
    summary_rows = []

    for i, case in enumerate(cases, start=1):
        d = doc_no(case)
        out_path = reviews_dir / f"{d}.json"
        if out_path.exists() and not args.overwrite:
            review = json.loads(out_path.read_text(encoding="utf-8"))
            print(f"[{i}/{len(cases)}] cached {d} score={review.get('full_paper_support_score')}", flush=True)
        else:
            md_path = mineru_root / "docs" / d / "combined.md"
            if not md_path.exists():
                print(f"[{i}/{len(cases)}] missing markdown {d}: {md_path}", flush=True)
                continue
            full_text = md_path.read_text(encoding="utf-8", errors="replace")
            print(
                f"[{i}/{len(cases)}] full-paper review {d}: chars={len(full_text)} title={case.get('source', {}).get('title', '')[:80]}",
                flush=True,
            )
            review = run_full_paper_review(
                client=client,
                case=case,
                full_text=full_text,
                chunk_chars=args.chunk_chars,
                overlap=args.overlap,
            )
            out_path.write_text(json.dumps(review, ensure_ascii=False, indent=2), encoding="utf-8")
            print(
                f"  full_support={review['full_paper_support_score']} action={review['recommended_action']} "
                f"weak={review['weak_steps']} severe={review['severe_steps']} chunks={review['chunking']['chunk_count']}",
                flush=True,
            )
        summary_rows.append(
            {
                "doc_no": d,
                "case_id": case.get("case_id", ""),
                "title": case.get("source", {}).get("title", ""),
                "quality": case.get("quality_control", {}).get("auto_quality_score", ""),
                "support_review_score": case.get("quality_control", {}).get("support_review", {}).get("overall_support_score", ""),
                "full_paper_support_score": review.get("full_paper_support_score", ""),
                "full_paper_decision": review.get("full_paper_decision", ""),
                "recommended_action": review.get("recommended_action", ""),
                "weak_steps": review.get("weak_steps", ""),
                "severe_steps": review.get("severe_steps", ""),
                "chunks_read": review.get("coverage", {}).get("chunks_read", ""),
                "full_text_chars": review.get("coverage", {}).get("full_text_chars", ""),
            }
        )

    if summary_rows:
        with (output_root / "full_paper_review_summary.csv").open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(summary_rows[0].keys()))
            writer.writeheader()
            writer.writerows(summary_rows)
    summary = {
        "case_count": len(summary_rows),
        "keep": sum(1 for r in summary_rows if r["recommended_action"] == "keep"),
        "repair": sum(1 for r in summary_rows if r["recommended_action"] == "repair"),
        "drop": sum(1 for r in summary_rows if r["recommended_action"] == "drop"),
        "avg_full_paper_support": round(
            sum(float(r["full_paper_support_score"] or 0) for r in summary_rows) / max(len(summary_rows), 1),
            3,
        ),
        "weak_step_total": sum(int(r["weak_steps"] or 0) for r in summary_rows),
        "severe_step_total": sum(int(r["severe_steps"] or 0) for r in summary_rows),
    }
    (output_root / "full_paper_review_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()


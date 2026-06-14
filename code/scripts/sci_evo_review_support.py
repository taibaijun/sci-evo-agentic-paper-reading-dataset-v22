from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sci_evo_pipeline.deepseek_client import DeepSeekClient
from sci_evo_pipeline.support_review import review_case_support


def read_jsonl(path: Path) -> list[dict]:
    rows = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def doc_no_from_case(case: dict) -> str:
    case_id = case.get("case_id", "")
    tail = str(case_id).split("_")[-1]
    return tail.zfill(4)


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Run DeepSeek support critic on extracted Sci-Evo cases.")
    parser.add_argument("--run-root", default=r"outputs\run")
    parser.add_argument("--contexts-root", default="")
    parser.add_argument("--reviews-dir", default="")
    parser.add_argument("--dataset-jsonl", default=r"dataset.jsonl")
    parser.add_argument("--model", default="deepseek-v4-flash")
    parser.add_argument("--api-base", default="https://api.deepseek.com")
    parser.add_argument("--api-key-env", default="DEEPSEEK_API_KEY")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    api_key = os.environ.get(args.api_key_env, "").strip()
    if not api_key:
        raise SystemExit(f"Missing API key. Set ${args.api_key_env} before running.")

    run_root = Path(args.run_root)
    contexts_root = Path(args.contexts_root) if args.contexts_root else run_root / "contexts"
    reviews_dir = Path(args.reviews_dir) if args.reviews_dir else run_root / "support_reviews"
    reviews_dir.mkdir(parents=True, exist_ok=True)
    cases = read_jsonl(Path(args.dataset_jsonl))
    if args.limit:
        cases = cases[: args.limit]
    client = DeepSeekClient(api_key=api_key, model=args.model, base_url=args.api_base)

    summary_rows = []
    for i, case in enumerate(cases, start=1):
        doc_no = doc_no_from_case(case)
        out_path = reviews_dir / f"{doc_no}.json"
        if out_path.exists() and not args.overwrite:
            review = json.loads(out_path.read_text(encoding="utf-8"))
            print(f"[{i}/{len(cases)}] cached {doc_no} score={review.get('overall_support_score')}", flush=True)
        else:
            context_path = contexts_root / f"{doc_no}.json"
            if not context_path.exists():
                print(f"[{i}/{len(cases)}] missing context for {doc_no}", flush=True)
                continue
            context = json.loads(context_path.read_text(encoding="utf-8"))
            print(f"[{i}/{len(cases)}] reviewing {doc_no}: {case.get('source', {}).get('title', '')[:90]}", flush=True)
            review = review_case_support(client=client, case=case, context=context)
            out_path.write_text(json.dumps(review, ensure_ascii=False, indent=2), encoding="utf-8")
            print(
                f"  support={review['overall_support_score']} decision={review['case_decision']} "
                f"weak={review['weak_steps']} severe={review['severe_unsupported_steps']} "
                f"usage={json.dumps(review.get('_api_usage', {}), ensure_ascii=False)}",
                flush=True,
            )
        summary_rows.append(
            {
                "doc_no": doc_no,
                "case_id": case.get("case_id", ""),
                "title": case.get("source", {}).get("title", ""),
                "quality": case.get("quality_control", {}).get("auto_quality_score", ""),
                "steps": len(case.get("evolution_trajectory") or []),
                "overall_support_score": review.get("overall_support_score", 0),
                "case_decision": review.get("case_decision", ""),
                "weak_steps": review.get("weak_steps", 0),
                "severe_unsupported_steps": review.get("severe_unsupported_steps", 0),
            }
        )

    csv_path = run_root / "support_review_summary.csv"
    if summary_rows:
        with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(summary_rows[0].keys()))
            writer.writeheader()
            writer.writerows(summary_rows)
    summary = {
        "case_count": len(summary_rows),
        "accepted": sum(1 for r in summary_rows if r["case_decision"] == "accept"),
        "revise": sum(1 for r in summary_rows if r["case_decision"] == "revise"),
        "reject": sum(1 for r in summary_rows if r["case_decision"] == "reject"),
        "avg_support": round(
            sum(float(r["overall_support_score"]) for r in summary_rows) / max(len(summary_rows), 1),
            3,
        ),
        "weak_step_total": sum(int(r["weak_steps"]) for r in summary_rows),
        "severe_step_total": sum(int(r["severe_unsupported_steps"]) for r in summary_rows),
    }
    (run_root / "support_review_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

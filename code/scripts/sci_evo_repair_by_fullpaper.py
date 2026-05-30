from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sci_evo_pipeline.deepseek_client import DeepSeekClient
from sci_evo_pipeline.full_paper_repair import repair_case_with_full_review
from sci_evo_pipeline.schema import write_dataset_jsonl


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


def should_repair(review: dict) -> bool:
    return int(review.get("weak_steps") or 0) > 0 or int(review.get("severe_steps") or 0) > 0


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Repair cases flagged by full-paper AI review.")
    parser.add_argument("--dataset-jsonl", default=r"outputs\submission_v2_supported\dataset.jsonl")
    parser.add_argument("--full-review-dir", default=r"outputs\full_paper_review_v2\reviews")
    parser.add_argument("--mineru-root", default=r"D:\mineru_flat_results_20260521_200done")
    parser.add_argument("--output-root", default=r"outputs\fullpaper_repaired_v3")
    parser.add_argument("--model", default="deepseek-v4-flash")
    parser.add_argument("--api-base", default="https://api.deepseek.com")
    parser.add_argument("--api-key-env", default="DEEPSEEK_API_KEY")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    api_key = os.environ.get(args.api_key_env, "").strip()
    if not api_key:
        raise SystemExit(f"Missing API key. Set ${args.api_key_env} before running.")

    output_root = Path(args.output_root)
    cases_dir = output_root / "cases"
    cases_dir.mkdir(parents=True, exist_ok=True)
    client = DeepSeekClient(api_key=api_key, model=args.model, base_url=args.api_base)

    repaired_cases = []
    attempts = 0
    for case in read_jsonl(Path(args.dataset_jsonl)):
        d = doc_no(case)
        review_path = Path(args.full_review_dir) / f"{d}.json"
        md_path = Path(args.mineru_root) / "docs" / d / "combined.md"
        if not review_path.exists() or not md_path.exists():
            continue
        review = json.loads(review_path.read_text(encoding="utf-8"))
        if not should_repair(review):
            continue
        attempts += 1
        if args.limit and attempts > args.limit:
            break
        out_path = cases_dir / f"{d}.json"
        if out_path.exists() and not args.overwrite:
            result = json.loads(out_path.read_text(encoding="utf-8"))
            print(f"[cached] {d}", flush=True)
        else:
            print(
                f"[repair {attempts}] {d} full_support={review.get('full_paper_support_score')} "
                f"weak={review.get('weak_steps')} severe={review.get('severe_steps')}",
                flush=True,
            )
            full_text = md_path.read_text(encoding="utf-8", errors="replace")
            result = repair_case_with_full_review(
                client=client,
                case=case,
                review=review,
                full_text=full_text,
                doc_no=d,
            )
            out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            print(
                f"  schema_errors={len(result['validation_errors'])} "
                f"full_text_quote_errors={len(result['full_text_quote_errors'])} "
                f"usage={json.dumps(result.get('api_usage', {}), ensure_ascii=False)}",
                flush=True,
            )
        if not result.get("validation_errors") and not result.get("full_text_quote_errors"):
            repaired_cases.append(result["case"])

    write_dataset_jsonl(output_root / "dataset.jsonl", repaired_cases)
    summary = {
        "attempted": attempts if not args.limit else min(attempts, args.limit),
        "valid_repaired_cases": len(repaired_cases),
    }
    (output_root / "repair_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sci_evo_pipeline.critic_repair import repair_case_with_critic
from sci_evo_pipeline.deepseek_client import DeepSeekClient
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


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Repair critic-flagged Sci-Evo cases.")
    parser.add_argument("--run-root", default=r"outputs\run")
    parser.add_argument("--dataset-jsonl", default=r"dataset.jsonl")
    parser.add_argument("--output-root", default=r"outputs\critic_repaired_core")
    parser.add_argument("--model", default="deepseek-v4-flash")
    parser.add_argument("--api-base", default="https://api.deepseek.com")
    parser.add_argument("--api-key-env", default="DEEPSEEK_API_KEY")
    parser.add_argument("--min-support", type=float, default=0.80)
    parser.add_argument("--max-weak", type=int, default=2)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    api_key = os.environ.get(args.api_key_env, "").strip()
    if not api_key:
        raise SystemExit(f"Missing API key. Set ${args.api_key_env} before running.")

    run_root = Path(args.run_root)
    output_root = Path(args.output_root)
    cases_dir = output_root / "cases"
    cases_dir.mkdir(parents=True, exist_ok=True)
    client = DeepSeekClient(api_key=api_key, model=args.model, base_url=args.api_base)
    base_cases = read_jsonl(Path(args.dataset_jsonl))

    repaired_cases = []
    attempted = 0
    for case in base_cases:
        d = doc_no(case)
        review_path = run_root / "support_reviews" / f"{d}.json"
        context_path = run_root / "contexts" / f"{d}.json"
        if not review_path.exists() or not context_path.exists():
            continue
        review = json.loads(review_path.read_text(encoding="utf-8"))
        score = float(review.get("overall_support_score") or 0)
        weak = int(review.get("weak_steps") or 0)
        severe = int(review.get("severe_unsupported_steps") or 0)
        if review.get("case_decision") != "revise" or severe != 0 or score < args.min_support or weak > args.max_weak:
            continue
        attempted += 1
        if args.limit and attempted > args.limit:
            break
        out_path = cases_dir / f"{d}.json"
        if out_path.exists() and not args.overwrite:
            result = json.loads(out_path.read_text(encoding="utf-8"))
            print(f"[cached] {d}", flush=True)
        else:
            context = json.loads(context_path.read_text(encoding="utf-8"))
            print(
                f"[repair {attempted}] {d} support={score} weak={weak}: {case.get('source', {}).get('title', '')[:90]}",
                flush=True,
            )
            result = repair_case_with_critic(
                client=client,
                case=case,
                context=context,
                review=review,
                doc_no=d,
            )
            out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            print(
                f"  schema_errors={len(result['validation_errors'])} quote_errors={len(result['evidence_quote_errors'])} "
                f"usage={json.dumps(result.get('api_usage', {}), ensure_ascii=False)}",
                flush=True,
            )
        if not result.get("validation_errors") and not result.get("evidence_quote_errors"):
            repaired_cases.append(result["case"])

    write_dataset_jsonl(output_root / "dataset.jsonl", repaired_cases)
    summary = {
        "attempted": attempted if not args.limit else min(attempted, args.limit),
        "valid_repaired_cases": len(repaired_cases),
        "min_support": args.min_support,
        "max_weak": args.max_weak,
    }
    (output_root / "repair_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()


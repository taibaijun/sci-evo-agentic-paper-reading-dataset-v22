from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sci_evo_pipeline.corpus import read_jsonl
from sci_evo_pipeline.deepseek_client import DeepSeekClient
from sci_evo_pipeline.extract import extract_record
from sci_evo_pipeline.schema import write_dataset_jsonl


def select_records(rows: list[dict], doc_nos: list[str], limit: int) -> list[dict]:
    if doc_nos:
        wanted = {str(x).zfill(4) for x in doc_nos}
        selected = [r for r in rows if str(r["doc_no"]).zfill(4) in wanted]
    else:
        selected = rows[:limit]
    return selected


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract Sci-Evo cases with DeepSeek JSON mode.")
    parser.add_argument("--input-root", default=r"D:\mineru_flat_results_20260521_200done")
    parser.add_argument("--index", default=r"outputs\sci_evo_index.jsonl")
    parser.add_argument("--output-root", default=r"outputs\deepseek_trial")
    parser.add_argument("--limit", type=int, default=3)
    parser.add_argument("--doc-no", action="append", default=[], help="Specific doc number; repeatable")
    parser.add_argument("--model", default="deepseek-v4-flash")
    parser.add_argument("--api-base", default="https://api.deepseek.com")
    parser.add_argument("--api-key-env", default="DEEPSEEK_API_KEY")
    parser.add_argument("--max-context-chars", type=int, default=30000)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    api_key = os.environ.get(args.api_key_env, "").strip()
    if not api_key:
        raise SystemExit(f"Missing API key. Set ${args.api_key_env} before running.")

    rows = read_jsonl(Path(args.index))
    selected = select_records(rows, args.doc_no, args.limit)
    output_root = Path(args.output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    client = DeepSeekClient(api_key=api_key, model=args.model, base_url=args.api_base)

    outputs = []
    for i, record in enumerate(selected, start=1):
        doc_no = str(record["doc_no"]).zfill(4)
        print(f"[{i}/{len(selected)}] extracting {doc_no}: {record.get('title','')[:100]}", flush=True)
        result = extract_record(
            input_root=Path(args.input_root),
            record=record,
            output_root=output_root,
            client=client,
            max_context_chars=args.max_context_chars,
            overwrite=args.overwrite,
        )
        outputs.append(result)
        score = result["case"]["quality_control"].get("auto_quality_score")
        errors = len(result.get("validation_errors") or [])
        usage = result.get("api_usage") or {}
        print(f"  quality={score} errors={errors} usage={json.dumps(usage, ensure_ascii=False)}", flush=True)

    cases = [out["case"] for out in outputs]
    write_dataset_jsonl(output_root / "dataset.jsonl", cases)
    print(f"wrote {len(cases)} cases to {output_root / 'dataset.jsonl'}")


if __name__ == "__main__":
    main()

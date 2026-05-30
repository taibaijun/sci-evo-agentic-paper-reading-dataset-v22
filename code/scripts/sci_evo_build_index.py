from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sci_evo_pipeline.corpus import build_index, records_to_dicts, write_jsonl


def main() -> None:
    parser = argparse.ArgumentParser(description="Build and rank the Sci-Evo paper index.")
    parser.add_argument("--input-root", default=r"D:\mineru_flat_results_20260521_200done")
    parser.add_argument("--raw-inventory", default=r"D:\mineru数据比赛\raw_papers\pdf_inventory.csv")
    parser.add_argument("--output", default=r"outputs\sci_evo_index.jsonl")
    args = parser.parse_args()

    records = build_index(Path(args.input_root), Path(args.raw_inventory))
    rows = records_to_dicts(records)
    write_jsonl(Path(args.output), rows)
    print(f"indexed={len(rows)} output={args.output}")
    print("top_10:")
    for row in rows[:10]:
        print(f"{row['doc_no']} score={row['relevance_score']} title={row['title'][:110]}")


if __name__ == "__main__":
    main()

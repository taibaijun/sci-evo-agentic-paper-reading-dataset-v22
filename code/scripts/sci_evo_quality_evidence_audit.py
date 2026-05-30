from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sci_evo_pipeline.evidence_index import check_case_evidence
from sci_evo_pipeline.quality_first import doc_no, read_jsonl


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Audit candidate evidence quotes against full MinerU text.")
    parser.add_argument("--dataset-jsonl", required=True)
    parser.add_argument("--mineru-root", default=r"D:\mineru_flat_results_20260521_200done")
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--output-csv", default="")
    parser.add_argument("--case-ids", default="")
    args = parser.parse_args()

    cases = read_jsonl(Path(args.dataset_jsonl))
    wanted = {x.strip() for x in args.case_ids.split(",") if x.strip()}
    if wanted:
        normalized = set()
        for item in wanted:
            normalized.add(item)
            if item.isdigit():
                normalized.add(f"{int(item):04d}")
                normalized.add(f"sci_evo_{int(item):04d}")
        cases = [case for case in cases if doc_no(case) in normalized or case.get("case_id") in normalized]

    mineru_root = Path(args.mineru_root)
    details = []
    rows = []
    for case in cases:
        d = doc_no(case)
        full_text_path = mineru_root / "docs" / d / "combined.md"
        checks = check_case_evidence(case, full_text_path)
        bad = [item for item in checks if item.warning or not (item.exact_match or item.normalized_match)]
        warning_counts: dict[str, int] = {}
        for item in bad:
            key = item.warning or "not_matched"
            warning_counts[key] = warning_counts.get(key, 0) + 1
        rows.append(
            {
                "doc_no": d,
                "case_id": case.get("case_id", ""),
                "evidence_count": len(checks),
                "bad_evidence_count": len(bad),
                "bad_evidence_ratio": round(len(bad) / max(len(checks), 1), 3),
                "warning_counts": json.dumps(warning_counts, ensure_ascii=False, sort_keys=True),
            }
        )
        details.append(
            {
                **rows[-1],
                "bad_evidence": [
                    {
                        "step_index": item.step_index,
                        "evidence_index": item.evidence_index,
                        "section": item.section,
                        "warning": item.warning,
                        "exact_match": item.exact_match,
                        "normalized_match": item.normalized_match,
                        "quote": item.quote[:500],
                    }
                    for item in bad
                ],
            }
        )

    output_json = Path(args.output_json)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    summary = {
        "case_count": len(rows),
        "total_evidence": sum(row["evidence_count"] for row in rows),
        "total_bad_evidence": sum(row["bad_evidence_count"] for row in rows),
        "cases": details,
    }
    output_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.output_csv and rows:
        output_csv = Path(args.output_csv)
        output_csv.parent.mkdir(parents=True, exist_ok=True)
        with output_csv.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
    print(json.dumps({k: v for k, v in summary.items() if k != "cases"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

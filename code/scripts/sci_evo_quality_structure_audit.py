from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sci_evo_pipeline.quality_first import doc_no, read_jsonl
from sci_evo_pipeline.structure_audit import audit_case_structure


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Run deterministic structure/text hygiene checks.")
    parser.add_argument("--dataset-jsonl", required=True)
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

    details = [audit_case_structure(case) for case in cases]
    rows = [
        {
            "doc_no": item["doc_no"],
            "case_id": item["case_id"],
            "decision": item["decision"],
            "issue_count": item["issue_count"],
            "issue_types": json.dumps(
                sorted({issue.get("type", "") for issue in item["issues"] if issue.get("type")}),
                ensure_ascii=False,
            ),
        }
        for item in details
    ]
    summary = {
        "case_count": len(details),
        "pass": sum(1 for item in details if item["decision"] == "pass"),
        "repair": sum(1 for item in details if item["decision"] == "repair"),
        "total_issues": sum(item["issue_count"] for item in details),
        "cases": details,
    }
    output_json = Path(args.output_json)
    output_json.parent.mkdir(parents=True, exist_ok=True)
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

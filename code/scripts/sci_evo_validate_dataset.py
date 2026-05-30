from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sci_evo_pipeline.schema import (
    load_cases_from_dir,
    validate_case,
    validate_evidence_quotes,
    write_dataset_jsonl,
)


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Validate extracted Sci-Evo cases and build a quality report.")
    parser.add_argument("--cases-dir", default=r"outputs\deepseek_trial\cases")
    parser.add_argument("--contexts-dir", default=r"outputs\deepseek_trial\contexts")
    parser.add_argument("--output-jsonl", default=r"outputs\deepseek_trial\dataset.jsonl")
    parser.add_argument("--report", default=r"outputs\deepseek_trial\quality_report.json")
    args = parser.parse_args()

    cases = load_cases_from_dir(Path(args.cases_dir))
    rows = []
    contexts_dir = Path(args.contexts_dir)
    for case in cases:
        errors = validate_case(case)
        doc_no = str(case.get("case_id", "")).split("_")[-1].zfill(4)
        context_path = contexts_dir / f"{doc_no}.json"
        context = json.loads(context_path.read_text(encoding="utf-8")) if context_path.exists() else None
        evidence_errors = validate_evidence_quotes(case, context)
        qc = case.get("quality_control", {})
        rows.append(
            {
                "case_id": case.get("case_id"),
                "title": case.get("source", {}).get("title"),
                "step_count": len(case.get("evolution_trajectory") or []),
                "evidence_coverage": qc.get("evidence_coverage"),
                "auto_quality_score": qc.get("auto_quality_score"),
                "errors": errors,
                "evidence_quote_errors": evidence_errors,
            }
        )
    write_dataset_jsonl(Path(args.output_jsonl), cases)
    report = {
        "case_count": len(cases),
        "average_quality_score": round(
            sum((r.get("auto_quality_score") or 0) for r in rows) / max(len(rows), 1), 2
        ),
        "average_evidence_coverage": round(
            sum((r.get("evidence_coverage") or 0) for r in rows) / max(len(rows), 1), 3
        ),
        "cases": rows,
    }
    Path(args.report).parent.mkdir(parents=True, exist_ok=True)
    Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

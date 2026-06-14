from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sci_evo_pipeline.schema import (
    normalize_case,
    repair_evidence_quotes,
    validate_case,
    validate_evidence_quotes,
    write_dataset_jsonl,
)


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Re-normalize and repair a run from cached raw responses.")
    parser.add_argument("--run-root", default=r"outputs\run")
    args = parser.parse_args()

    run_root = Path(args.run_root)
    raw_dir = run_root / "raw_responses"
    contexts_dir = run_root / "contexts"
    cases_dir = run_root / "cases"
    cases_dir.mkdir(parents=True, exist_ok=True)
    cases = []
    summary = []

    for raw_path in sorted(raw_dir.glob("*.json")):
        doc_no = raw_path.stem
        response = json.loads(raw_path.read_text(encoding="utf-8"))
        context_path = contexts_dir / f"{doc_no}.json"
        if not context_path.exists():
            summary.append({"doc_no": doc_no, "error": "missing context"})
            continue
        context = json.loads(context_path.read_text(encoding="utf-8"))
        raw_case = response.get("case") if isinstance(response.get("case"), dict) else response
        case = normalize_case(raw_case, doc_no=doc_no, source=context.get("source", {}))
        repair_count = repair_evidence_quotes(case, context)
        schema_errors = validate_case(case)
        quote_errors = validate_evidence_quotes(case, context)
        output = {
            "case": case,
            "validation_errors": schema_errors,
            "evidence_quote_errors": quote_errors,
            "extraction_notes": response.get("extraction_notes", {}),
            "api_usage": response.get("_api_usage", {}),
            "api_model": response.get("_api_model", ""),
            "api_finish_reason": response.get("_api_finish_reason", ""),
            "evidence_repair_count": repair_count,
        }
        (cases_dir / f"{doc_no}.json").write_text(
            json.dumps(output, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        cases.append(case)
        summary.append(
            {
                "doc_no": doc_no,
                "case_id": case.get("case_id"),
                "quality": case.get("quality_control", {}).get("auto_quality_score"),
                "steps": len(case.get("evolution_trajectory") or []),
                "schema_errors": len(schema_errors),
                "quote_errors": len(quote_errors),
                "repairs": repair_count,
            }
        )

    write_dataset_jsonl(run_root / "dataset.jsonl", cases)
    (run_root / "repair_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps({"cases": len(cases), "summary": summary[-10:]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()


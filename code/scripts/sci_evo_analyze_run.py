from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sci_evo_pipeline.schema import validate_case, validate_evidence_quotes


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def status_counts(case: dict) -> dict[str, int]:
    out: dict[str, int] = {}
    for step in case.get("evolution_trajectory") or []:
        status = step.get("result_status", "unknown")
        out[status] = out.get(status, 0) + 1
    return out


def has_revision_signal(case: dict) -> bool:
    blob = json.dumps(case.get("evolution_trajectory", []), ensure_ascii=False).lower()
    keywords = ["failure", "failed", "partial", "inconclusive", "however", "limitation", "revision", "optimiz"]
    return any(k in blob for k in keywords)


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Analyze a Sci-Evo extraction run.")
    parser.add_argument("--run-root", default=r"outputs\run")
    parser.add_argument("--min-quality", type=float, default=75.0)
    parser.add_argument("--min-steps", type=int, default=5)
    args = parser.parse_args()

    run_root = Path(args.run_root)
    cases_dir = run_root / "cases"
    contexts_dir = run_root / "contexts"
    rows = []
    for case_file in sorted(cases_dir.glob("*.json")):
        data = load_json(case_file)
        case = data["case"] if "case" in data else data
        doc_no = case_file.stem
        context_path = contexts_dir / f"{doc_no}.json"
        context = load_json(context_path) if context_path.exists() else None
        schema_errors = validate_case(case)
        quote_errors = validate_evidence_quotes(case, context)
        qc = case.get("quality_control", {})
        steps = case.get("evolution_trajectory") or []
        statuses = status_counts(case)
        metrics = case.get("success_verification", {}).get("metrics") or []
        limitations = case.get("success_verification", {}).get("limitations") or []
        quality = float(qc.get("auto_quality_score") or 0)
        keep = (
            quality >= args.min_quality
            and len(steps) >= args.min_steps
            and not schema_errors
            and not quote_errors
        )
        needs_review = (
            quality < args.min_quality
            or len(steps) < args.min_steps
            or bool(schema_errors)
            or bool(quote_errors)
            or not has_revision_signal(case)
        )
        rows.append(
            {
                "doc_no": doc_no,
                "case_id": case.get("case_id", ""),
                "title": case.get("source", {}).get("title", ""),
                "quality": quality,
                "steps": len(steps),
                "metrics": len(metrics),
                "limitations": len(limitations),
                "evidence_coverage": qc.get("evidence_coverage", 0),
                "repair_note": "; ".join(
                    str(x) for x in qc.get("risk_notes", []) if "auto_repaired_evidence_quotes" in str(x)
                ),
                "success_steps": statuses.get("success", 0),
                "partial_steps": statuses.get("partial", 0),
                "failure_steps": statuses.get("failure", 0),
                "inconclusive_steps": statuses.get("inconclusive", 0),
                "schema_error_count": len(schema_errors),
                "quote_error_count": len(quote_errors),
                "keep_auto": keep,
                "needs_review": needs_review,
            }
        )

    rows.sort(key=lambda r: (not r["keep_auto"], -float(r["quality"]), -int(r["steps"]), r["doc_no"]))
    out_csv = run_root / "run_analysis.csv"
    out_json = run_root / "run_analysis.json"
    if rows:
        with out_csv.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
    summary = {
        "case_count": len(rows),
        "auto_keep_count": sum(1 for r in rows if r["keep_auto"]),
        "needs_review_count": sum(1 for r in rows if r["needs_review"]),
        "avg_quality": round(sum(float(r["quality"]) for r in rows) / max(len(rows), 1), 2),
        "schema_error_total": sum(int(r["schema_error_count"]) for r in rows),
        "quote_error_total": sum(int(r["quote_error_count"]) for r in rows),
        "top_keep": rows[:15],
    }
    out_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()


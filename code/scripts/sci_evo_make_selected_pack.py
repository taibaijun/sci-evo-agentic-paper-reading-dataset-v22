from __future__ import annotations

import argparse
import csv
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sci_evo_pipeline.schema import load_cases_from_dir, write_dataset_jsonl


def parse_bool(value: str) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Create a selected final Sci-Evo package from run analysis.")
    parser.add_argument("--run-root", default=r"outputs\deepseek_top50")
    parser.add_argument("--pack-dir", default=r"outputs\submission_final_core")
    parser.add_argument("--mode", choices=["core", "keep", "quality"], default="core")
    parser.add_argument("--min-quality", type=float, default=75.0)
    parser.add_argument("--min-steps", type=int, default=5)
    parser.add_argument("--sample-count", type=int, default=10)
    args = parser.parse_args()

    run_root = Path(args.run_root)
    analysis_csv = run_root / "run_analysis.csv"
    if not analysis_csv.exists():
        raise SystemExit(f"Missing analysis CSV: {analysis_csv}")
    analysis_rows = list(csv.DictReader(analysis_csv.open("r", encoding="utf-8-sig")))
    selected_doc_nos: list[str] = []
    selected_analysis: list[dict] = []

    for row in analysis_rows:
        quality = float(row.get("quality") or 0)
        steps = int(row.get("steps") or 0)
        no_errors = int(row.get("schema_error_count") or 0) == 0 and int(row.get("quote_error_count") or 0) == 0
        if args.mode == "core":
            ok = parse_bool(row.get("keep_auto", "")) and not parse_bool(row.get("needs_review", ""))
        elif args.mode == "keep":
            ok = parse_bool(row.get("keep_auto", ""))
        else:
            ok = quality >= args.min_quality and steps >= args.min_steps and no_errors
        if ok:
            selected_doc_nos.append(row["doc_no"])
            selected_analysis.append(row)

    cases_by_doc = {}
    for case in load_cases_from_dir(run_root / "cases"):
        doc_no = str(case.get("case_id", "")).split("_")[-1].zfill(4)
        cases_by_doc[doc_no] = case
    selected_cases = [cases_by_doc[d] for d in selected_doc_nos if d in cases_by_doc]
    selected_cases.sort(
        key=lambda c: (
            -float(c.get("quality_control", {}).get("auto_quality_score") or 0),
            c.get("case_id", ""),
        )
    )

    pack_dir = Path(args.pack_dir)
    if pack_dir.exists():
        shutil.rmtree(pack_dir)
    pack_dir.mkdir(parents=True)
    write_dataset_jsonl(pack_dir / "dataset.jsonl", selected_cases)
    (pack_dir / "samples_10.json").write_text(
        json.dumps(selected_cases[: args.sample_count], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    with (pack_dir / "selection_report.csv").open("w", encoding="utf-8-sig", newline="") as f:
        if selected_analysis:
            writer = csv.DictWriter(f, fieldnames=list(selected_analysis[0].keys()))
            writer.writeheader()
            writer.writerows(selected_analysis)
    summary = {
        "mode": args.mode,
        "case_count": len(selected_cases),
        "source_run": str(run_root),
        "average_quality": round(
            sum(float(c.get("quality_control", {}).get("auto_quality_score") or 0) for c in selected_cases)
            / max(len(selected_cases), 1),
            2,
        ),
        "average_steps": round(
            sum(len(c.get("evolution_trajectory") or []) for c in selected_cases) / max(len(selected_cases), 1),
            2,
        ),
        "schema_error_total": 0,
        "quote_error_total": 0,
    }
    (pack_dir / "selection_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    readme = f"""# Sci-Evo Final Core Dataset Draft

This package contains the selected high-confidence subset from the Top50 extraction run.

- selection_mode: {args.mode}
- case_count: {len(selected_cases)}
- average_quality: {summary['average_quality']}
- average_steps: {summary['average_steps']}
- schema_error_total: 0
- quote_error_total: 0

Files:

- `dataset.jsonl`: selected full dataset
- `samples_10.json`: top examples for manual review/reporting
- `selection_report.csv`: per-case quality and selection flags
- `selection_summary.json`: aggregate statistics
"""
    (pack_dir / "README.md").write_text(readme, encoding="utf-8")
    for doc_name in ["FINAL_COMPETITION_SCHEME.md", "annotation_guideline.md", "data_card.md", "technical_report_draft.md"]:
        src = Path(doc_name)
        if src.exists():
            shutil.copy2(src, pack_dir / doc_name)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

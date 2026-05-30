from __future__ import annotations

import argparse
import csv
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

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


def load_review(run_root: Path, doc: str) -> dict | None:
    path = run_root / "support_reviews" / f"{doc}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def keep_case(case: dict, review: dict, mode: str, min_support: float, min_quality: float) -> bool:
    quality = float(case.get("quality_control", {}).get("auto_quality_score") or 0)
    support = float(review.get("overall_support_score") or 0)
    severe = int(review.get("severe_unsupported_steps") or 0)
    weak = int(review.get("weak_steps") or 0)
    decision = review.get("case_decision")
    if quality < min_quality or support < min_support or severe > 0:
        return False
    if mode == "strict":
        return decision == "accept" and weak == 0
    if mode == "supported":
        return decision in {"accept", "revise"} and weak <= 1
    if mode == "broad":
        return decision != "reject"
    raise ValueError(mode)


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Create a package filtered by DeepSeek support critic.")
    parser.add_argument("--run-root", default=r"outputs\deepseek_top50")
    parser.add_argument("--dataset-jsonl", default=r"outputs\submission_final_core\dataset.jsonl")
    parser.add_argument("--pack-dir", default=r"outputs\submission_supported_strict")
    parser.add_argument("--mode", choices=["strict", "supported", "broad"], default="strict")
    parser.add_argument("--min-support", type=float, default=0.85)
    parser.add_argument("--min-quality", type=float, default=85.0)
    parser.add_argument("--sample-count", type=int, default=10)
    args = parser.parse_args()

    run_root = Path(args.run_root)
    cases = read_jsonl(Path(args.dataset_jsonl))
    selected = []
    report_rows = []
    for case in cases:
        d = doc_no(case)
        review = load_review(run_root, d)
        if not review:
            continue
        enriched = json.loads(json.dumps(case, ensure_ascii=False))
        enriched.setdefault("quality_control", {})["support_review"] = {
            "overall_support_score": review.get("overall_support_score"),
            "case_decision": review.get("case_decision"),
            "weak_steps": review.get("weak_steps"),
            "severe_unsupported_steps": review.get("severe_unsupported_steps"),
            "step_reviews": review.get("step_reviews", []),
            "risk_notes": review.get("risk_notes", []),
        }
        is_kept = keep_case(enriched, review, args.mode, args.min_support, args.min_quality)
        row = {
            "doc_no": d,
            "case_id": enriched.get("case_id", ""),
            "title": enriched.get("source", {}).get("title", ""),
            "quality": enriched.get("quality_control", {}).get("auto_quality_score", ""),
            "steps": len(enriched.get("evolution_trajectory") or []),
            "support": review.get("overall_support_score", ""),
            "decision": review.get("case_decision", ""),
            "weak_steps": review.get("weak_steps", ""),
            "severe_unsupported_steps": review.get("severe_unsupported_steps", ""),
            "kept": is_kept,
        }
        report_rows.append(row)
        if is_kept:
            selected.append(enriched)

    selected.sort(
        key=lambda c: (
            -float(c.get("quality_control", {}).get("support_review", {}).get("overall_support_score") or 0),
            -float(c.get("quality_control", {}).get("auto_quality_score") or 0),
            c.get("case_id", ""),
        )
    )
    pack_dir = Path(args.pack_dir)
    if pack_dir.exists():
        shutil.rmtree(pack_dir)
    pack_dir.mkdir(parents=True)
    write_dataset_jsonl(pack_dir / "dataset.jsonl", selected)
    (pack_dir / "samples_10.json").write_text(
        json.dumps(selected[: args.sample_count], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    if report_rows:
        with (pack_dir / "support_selection_report.csv").open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(report_rows[0].keys()))
            writer.writeheader()
            writer.writerows(report_rows)
    avg_quality = sum(float(c.get("quality_control", {}).get("auto_quality_score") or 0) for c in selected) / max(len(selected), 1)
    avg_support = sum(float(c.get("quality_control", {}).get("support_review", {}).get("overall_support_score") or 0) for c in selected) / max(len(selected), 1)
    summary = {
        "mode": args.mode,
        "case_count": len(selected),
        "source_cases": len(cases),
        "min_support": args.min_support,
        "min_quality": args.min_quality,
        "average_quality": round(avg_quality, 2),
        "average_support": round(avg_support, 3),
        "severe_unsupported_total": sum(
            int(c.get("quality_control", {}).get("support_review", {}).get("severe_unsupported_steps") or 0)
            for c in selected
        ),
    }
    (pack_dir / "support_selection_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    for doc_name in [
        "FINAL_COMPETITION_SCHEME.md",
        "annotation_guideline.md",
        "data_card.md",
        "technical_report_draft.md",
    ]:
        src = Path(doc_name)
        if src.exists():
            shutil.copy2(src, pack_dir / doc_name)
    (pack_dir / "README.md").write_text(
        f"""# Sci-Evo Support-Reviewed Dataset

- selection_mode: {args.mode}
- case_count: {len(selected)}
- minimum_support_score: {args.min_support}
- minimum_quality_score: {args.min_quality}
- average_quality: {summary['average_quality']}
- average_support: {summary['average_support']}
- severe_unsupported_total: {summary['severe_unsupported_total']}

This package applies a second-pass DeepSeek evidence-support critic in addition to schema and exact quote validation.
""",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()


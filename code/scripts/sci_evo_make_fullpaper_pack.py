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
    if not path.exists():
        return rows
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def doc_no(case: dict) -> str:
    return str(case.get("case_id", "")).split("_")[-1].zfill(4)


def load_review(path: Path) -> dict | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def review_passes(review: dict, *, mode: str, min_support: float, max_weak: int) -> bool:
    support = float(review.get("full_paper_support_score") or 0)
    weak = int(review.get("weak_steps") or 0)
    severe = int(review.get("severe_steps") or 0)
    decision = review.get("full_paper_decision")
    if decision == "reject" or severe != 0 or support < min_support:
        return False
    if mode == "strict":
        return weak == 0
    return weak <= max_weak


def attach_full_review(case: dict, review: dict, source: str) -> dict:
    out = json.loads(json.dumps(case, ensure_ascii=False))
    qc = out.setdefault("quality_control", {})
    qc["full_paper_review"] = {
        "review_source": source,
        "full_paper_support_score": review.get("full_paper_support_score"),
        "full_paper_decision": review.get("full_paper_decision"),
        "recommended_action": review.get("recommended_action"),
        "weak_steps": review.get("weak_steps"),
        "severe_steps": review.get("severe_steps"),
        "chunks_read": review.get("coverage", {}).get("chunks_read"),
        "full_text_chars": review.get("coverage", {}).get("full_text_chars"),
        "step_reviews": review.get("step_reviews", []),
        "case_level_risks": review.get("case_level_risks", []),
    }
    qc["full_paper_reviewed"] = True
    return out


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Create V3 package from full-paper-reviewed Sci-Evo cases.")
    parser.add_argument("--base-dataset", default=r"outputs\submission_v2_supported\dataset.jsonl")
    parser.add_argument("--base-review-dir", default=r"outputs\full_paper_review_v2\reviews")
    parser.add_argument("--repaired-dataset", default=r"outputs\fullpaper_repaired_v3\dataset.jsonl")
    parser.add_argument("--repaired-review-dir", default=r"outputs\full_paper_review_v3_repaired\reviews")
    parser.add_argument("--pack-dir", default=r"outputs\submission_v3_fullpaper_strict")
    parser.add_argument("--mode", choices=["strict", "supported"], default="strict")
    parser.add_argument("--min-support", type=float, default=0.90)
    parser.add_argument("--max-weak", type=int, default=1)
    parser.add_argument("--sample-count", type=int, default=10)
    args = parser.parse_args()

    base_cases = {doc_no(c): c for c in read_jsonl(Path(args.base_dataset))}
    repaired_cases = {doc_no(c): c for c in read_jsonl(Path(args.repaired_dataset))}
    base_review_dir = Path(args.base_review_dir)
    repaired_review_dir = Path(args.repaired_review_dir)

    selected: dict[str, dict] = {}
    report_rows = []
    rejected_rows = []

    for d in sorted(base_cases):
        candidates = []
        if d in repaired_cases:
            review = load_review(repaired_review_dir / f"{d}.json")
            if review:
                candidates.append(("fullpaper_repaired", repaired_cases[d], review))
        review = load_review(base_review_dir / f"{d}.json")
        if review:
            candidates.append(("original_fullpaper", base_cases[d], review))

        chosen = None
        for source, case, review in candidates:
            if review_passes(review, mode=args.mode, min_support=args.min_support, max_weak=args.max_weak):
                chosen = (source, case, review)
                break
        if chosen:
            source, case, review = chosen
            selected[d] = attach_full_review(case, review, source)
            report_rows.append(
                {
                    "doc_no": d,
                    "case_id": case.get("case_id", ""),
                    "title": case.get("source", {}).get("title", ""),
                    "selected_version": source,
                    "quality": case.get("quality_control", {}).get("auto_quality_score", ""),
                    "full_paper_support": review.get("full_paper_support_score", ""),
                    "full_paper_decision": review.get("full_paper_decision", ""),
                    "recommended_action": review.get("recommended_action", ""),
                    "weak_steps": review.get("weak_steps", ""),
                    "severe_steps": review.get("severe_steps", ""),
                    "chunks_read": review.get("coverage", {}).get("chunks_read", ""),
                    "full_text_chars": review.get("coverage", {}).get("full_text_chars", ""),
                }
            )
        else:
            best = candidates[0] if candidates else ("missing", base_cases[d], {})
            source, case, review = best
            rejected_rows.append(
                {
                    "doc_no": d,
                    "case_id": case.get("case_id", ""),
                    "title": case.get("source", {}).get("title", ""),
                    "best_version": source,
                    "full_paper_support": review.get("full_paper_support_score", ""),
                    "weak_steps": review.get("weak_steps", ""),
                    "severe_steps": review.get("severe_steps", ""),
                }
            )

    cases = list(selected.values())
    cases.sort(
        key=lambda c: (
            -float(c.get("quality_control", {}).get("full_paper_review", {}).get("full_paper_support_score") or 0),
            -float(c.get("quality_control", {}).get("auto_quality_score") or 0),
            c.get("case_id", ""),
        )
    )
    pack_dir = Path(args.pack_dir)
    if pack_dir.exists():
        shutil.rmtree(pack_dir)
    pack_dir.mkdir(parents=True)

    write_dataset_jsonl(pack_dir / "dataset.jsonl", cases)
    (pack_dir / "samples_10.json").write_text(
        json.dumps(cases[: args.sample_count], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    if report_rows:
        with (pack_dir / "v3_selection_report.csv").open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(report_rows[0].keys()))
            writer.writeheader()
            writer.writerows(report_rows)
    if rejected_rows:
        with (pack_dir / "v3_rejected_report.csv").open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(rejected_rows[0].keys()))
            writer.writeheader()
            writer.writerows(rejected_rows)

    avg_quality = sum(float(c.get("quality_control", {}).get("auto_quality_score") or 0) for c in cases) / max(len(cases), 1)
    avg_support = sum(
        float(c.get("quality_control", {}).get("full_paper_review", {}).get("full_paper_support_score") or 0)
        for c in cases
    ) / max(len(cases), 1)
    summary = {
        "case_count": len(cases),
        "mode": args.mode,
        "min_support": args.min_support,
        "average_quality": round(avg_quality, 2),
        "average_full_paper_support": round(avg_support, 3),
        "original_fullpaper_count": sum(
            1
            for c in cases
            if c.get("quality_control", {}).get("full_paper_review", {}).get("review_source") == "original_fullpaper"
        ),
        "fullpaper_repaired_count": sum(
            1
            for c in cases
            if c.get("quality_control", {}).get("full_paper_review", {}).get("review_source") == "fullpaper_repaired"
        ),
        "weak_step_total": sum(
            int(c.get("quality_control", {}).get("full_paper_review", {}).get("weak_steps") or 0) for c in cases
        ),
        "severe_step_total": sum(
            int(c.get("quality_control", {}).get("full_paper_review", {}).get("severe_steps") or 0) for c in cases
        ),
        "rejected_count": len(rejected_rows),
    }
    (pack_dir / "v3_selection_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    for doc_name in [
        "FINAL_COMPETITION_SCHEME_V3.md",
        "technical_report_v3.md",
        "data_card_v3.md",
        "FINAL_COMPETITION_SCHEME_V2.md",
        "technical_report_v2.md",
        "data_card_v2.md",
        "annotation_guideline.md",
    ]:
        src = Path(doc_name)
        if src.exists():
            shutil.copy2(src, pack_dir / doc_name)

    (pack_dir / "README.md").write_text(
        f"""# Sci-Evo V3 Full-Paper-Reviewed Dataset

This package contains cases that passed full-paper AI review over the complete MinerU Markdown for each source paper.

- mode: {summary['mode']}
- case_count: {summary['case_count']}
- average_quality: {summary['average_quality']}
- average_full_paper_support: {summary['average_full_paper_support']}
- original_fullpaper_count: {summary['original_fullpaper_count']}
- fullpaper_repaired_count: {summary['fullpaper_repaired_count']}
- weak_step_total: {summary['weak_step_total']}
- severe_step_total: {summary['severe_step_total']}
""",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

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


def load_review(path: Path) -> dict | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def passes_strict(case: dict, review: dict, min_quality: float = 85.0, min_support: float = 0.85) -> bool:
    quality = float(case.get("quality_control", {}).get("auto_quality_score") or 0)
    return (
        quality >= min_quality
        and float(review.get("overall_support_score") or 0) >= min_support
        and review.get("case_decision") == "accept"
        and int(review.get("weak_steps") or 0) == 0
        and int(review.get("severe_unsupported_steps") or 0) == 0
    )


def passes_supported(case: dict, review: dict, min_quality: float = 85.0, min_support: float = 0.85) -> bool:
    quality = float(case.get("quality_control", {}).get("auto_quality_score") or 0)
    return (
        quality >= min_quality
        and float(review.get("overall_support_score") or 0) >= min_support
        and review.get("case_decision") in {"accept", "revise"}
        and int(review.get("weak_steps") or 0) <= 1
        and int(review.get("severe_unsupported_steps") or 0) == 0
    )


def attach_review(case: dict, review: dict, source: str) -> dict:
    out = json.loads(json.dumps(case, ensure_ascii=False))
    out.setdefault("quality_control", {})["support_review"] = {
        "overall_support_score": review.get("overall_support_score"),
        "case_decision": review.get("case_decision"),
        "weak_steps": review.get("weak_steps"),
        "severe_unsupported_steps": review.get("severe_unsupported_steps"),
        "step_reviews": review.get("step_reviews", []),
        "review_source": source,
    }
    return out


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Merge strict original cases and critic-repaired cases into V2 package.")
    parser.add_argument("--base-dataset", default=r"outputs\submission_final_core\dataset.jsonl")
    parser.add_argument("--base-reviews-dir", default=r"outputs\deepseek_top50\support_reviews")
    parser.add_argument("--repaired-dataset", default=r"outputs\critic_repaired_core\dataset.jsonl")
    parser.add_argument("--repaired-reviews-dir", default=r"outputs\critic_repaired_core\support_reviews")
    parser.add_argument("--pack-dir", default=r"outputs\submission_v2_supported")
    parser.add_argument("--sample-count", type=int, default=10)
    args = parser.parse_args()

    base_cases = {doc_no(c): c for c in read_jsonl(Path(args.base_dataset))}
    repaired_cases = {doc_no(c): c for c in read_jsonl(Path(args.repaired_dataset))}
    base_reviews_dir = Path(args.base_reviews_dir)
    repaired_reviews_dir = Path(args.repaired_reviews_dir)

    selected: dict[str, dict] = {}
    report_rows = []

    for d, case in base_cases.items():
        review = load_review(base_reviews_dir / f"{d}.json")
        if review and passes_strict(case, review):
            selected[d] = attach_review(case, review, "original_strict")
            report_rows.append(
                {
                    "doc_no": d,
                    "case_id": case.get("case_id", ""),
                    "title": case.get("source", {}).get("title", ""),
                    "version": "original_strict",
                    "quality": case.get("quality_control", {}).get("auto_quality_score", ""),
                    "support": review.get("overall_support_score", ""),
                    "decision": review.get("case_decision", ""),
                    "weak_steps": review.get("weak_steps", ""),
                    "severe_unsupported_steps": review.get("severe_unsupported_steps", ""),
                }
            )

    for d, case in repaired_cases.items():
        review = load_review(repaired_reviews_dir / f"{d}.json")
        if review and passes_supported(case, review):
            selected[d] = attach_review(case, review, "critic_repaired")
            report_rows.append(
                {
                    "doc_no": d,
                    "case_id": case.get("case_id", ""),
                    "title": case.get("source", {}).get("title", ""),
                    "version": "critic_repaired",
                    "quality": case.get("quality_control", {}).get("auto_quality_score", ""),
                    "support": review.get("overall_support_score", ""),
                    "decision": review.get("case_decision", ""),
                    "weak_steps": review.get("weak_steps", ""),
                    "severe_unsupported_steps": review.get("severe_unsupported_steps", ""),
                }
            )

    cases = list(selected.values())
    cases.sort(
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
    write_dataset_jsonl(pack_dir / "dataset.jsonl", cases)
    (pack_dir / "samples_10.json").write_text(
        json.dumps(cases[: args.sample_count], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    report_rows.sort(key=lambda r: (r["version"], r["doc_no"]))
    if report_rows:
        with (pack_dir / "v2_selection_report.csv").open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(report_rows[0].keys()))
            writer.writeheader()
            writer.writerows(report_rows)
    avg_quality = sum(float(c.get("quality_control", {}).get("auto_quality_score") or 0) for c in cases) / max(len(cases), 1)
    avg_support = sum(float(c.get("quality_control", {}).get("support_review", {}).get("overall_support_score") or 0) for c in cases) / max(len(cases), 1)
    summary = {
        "case_count": len(cases),
        "average_quality": round(avg_quality, 2),
        "average_support": round(avg_support, 3),
        "original_strict_count": sum(1 for c in cases if c.get("quality_control", {}).get("support_review", {}).get("review_source") == "original_strict"),
        "critic_repaired_count": sum(1 for c in cases if c.get("quality_control", {}).get("support_review", {}).get("review_source") == "critic_repaired"),
        "severe_unsupported_total": sum(int(c.get("quality_control", {}).get("support_review", {}).get("severe_unsupported_steps") or 0) for c in cases),
    }
    (pack_dir / "v2_selection_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    for doc_name in [
        "FINAL_COMPETITION_SCHEME_V2.md",
        "technical_report_v2.md",
        "data_card_v2.md",
        "FINAL_COMPETITION_SCHEME.md",
        "annotation_guideline.md",
        "data_card.md",
        "technical_report_draft.md",
    ]:
        src = Path(doc_name)
        if src.exists():
            shutil.copy2(src, pack_dir / doc_name)
    (pack_dir / "README.md").write_text(
        f"""# Sci-Evo V2 Support-Reviewed Dataset

This package merges:

- original cases that passed strict second-pass support review
- critic-repaired cases that passed a second support review after targeted repair

Statistics:

- case_count: {summary['case_count']}
- average_quality: {summary['average_quality']}
- average_support: {summary['average_support']}
- original_strict_count: {summary['original_strict_count']}
- critic_repaired_count: {summary['critic_repaired_count']}
- severe_unsupported_total: {summary['severe_unsupported_total']}
""",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

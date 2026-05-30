from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sci_evo_pipeline.quality_first import arbitrate_reviews, gate_to_dict, normalize_review
from sci_evo_pipeline.quality_arbiter import (
    collect_fix_tags,
    evidence_audit_to_review,
    load_evidence_audit_map,
    load_rule_audit_map,
    load_structure_audit_map,
    rule_audit_to_review,
    structure_audit_to_review,
)


def read_reviews(case_dir: Path) -> list[dict]:
    reviews = []
    for path in sorted(case_dir.glob("*.review.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            reviews.append(
                {
                    "reviewer_role": path.name.replace(".review.json", ""),
                    "verdict": "repair",
                    "confidence": 0.0,
                    "dimension_scores": {},
                    "blockers": [
                        {
                            "type": "evaluator_uncertain",
                            "severity": "medium",
                            "affected_steps": [],
                            "paper_basis": "",
                            "problem": f"Invalid reviewer JSON: {exc}",
                            "code_fix_hint": "Rerun this reviewer.",
                        }
                    ],
                    "repairs": [],
                    "summary": "Invalid reviewer JSON.",
                }
            )
            continue
        reviews.append(normalize_review(data, fallback_role=path.name.replace(".review.json", "")))
    return reviews


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Arbitrate V16 multi-reviewer quality JSON files.")
    parser.add_argument("--review-root", required=True)
    parser.add_argument("--evidence-audit-json", default="")
    parser.add_argument("--structure-audit-json", default="")
    parser.add_argument("--rule-audit-json", default="")
    parser.add_argument("--output-json", default="")
    parser.add_argument("--output-csv", default="")
    args = parser.parse_args()

    root = Path(args.review_root)
    evidence_map = {}
    if args.evidence_audit_json:
        evidence_map = load_evidence_audit_map(json.loads(Path(args.evidence_audit_json).read_text(encoding="utf-8")))
    structure_map = {}
    if args.structure_audit_json:
        structure_map = load_structure_audit_map(json.loads(Path(args.structure_audit_json).read_text(encoding="utf-8")))
    rule_map = {}
    if args.rule_audit_json:
        rule_map = load_rule_audit_map(json.loads(Path(args.rule_audit_json).read_text(encoding="utf-8")))
    rows = []
    details = []
    for case_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        reviews = read_reviews(case_dir)
        code_evidence_review = evidence_audit_to_review(evidence_map.get(case_dir.name, {}))
        if code_evidence_review:
            reviews.append(normalize_review(code_evidence_review, fallback_role="evidence_auditor"))
        code_structure_review = structure_audit_to_review(structure_map.get(case_dir.name, {}))
        if code_structure_review:
            reviews.append(normalize_review(code_structure_review, fallback_role="trajectory_judge"))
        code_rule_review = rule_audit_to_review(rule_map.get(case_dir.name, {}))
        if code_rule_review:
            reviews.append(normalize_review(code_rule_review, fallback_role="trajectory_judge"))
        gate = arbitrate_reviews(reviews)
        gate_dict = gate_to_dict(gate)
        doc_no = case_dir.name
        high_blockers = []
        repair_hints = []
        for review in reviews:
            for blocker in review.get("blockers", []):
                if blocker.get("severity") == "high":
                    high_blockers.append(
                        {
                            "role": review.get("reviewer_role"),
                            **blocker,
                        }
                    )
            for repair in review.get("repairs", []):
                if repair.get("priority") in {"medium", "high"}:
                    repair_hints.append(
                        {
                            "role": review.get("reviewer_role"),
                            **repair,
                        }
                    )
        details.append(
            {
                "doc_no": doc_no,
                "gate": gate_dict,
                "review_count": len(reviews),
                "high_blockers": high_blockers,
                "repair_hints": repair_hints,
                "fix_tags": collect_fix_tags(reviews),
                "reviews": reviews,
            }
        )
        rows.append(
            {
                "doc_no": doc_no,
                "decision": gate.decision,
                "confidence": gate.confidence,
                "score_mean": gate.score_mean,
                "score_min": gate.score_min,
                "blocker_count": gate.blocker_count,
                "repair_count": gate.repair_count,
                "reviewer_count": gate.reviewer_count,
                "reasons": "; ".join(gate.reasons),
            }
        )

    summary = {
        "case_count": len(rows),
        "pass": sum(1 for r in rows if r["decision"] == "pass"),
        "repair": sum(1 for r in rows if r["decision"] == "repair"),
        "fail": sum(1 for r in rows if r["decision"] == "fail"),
        "error": sum(1 for r in rows if r["decision"] == "error"),
        "cases": details,
    }
    output_json = Path(args.output_json) if args.output_json else root / "quality_arbitration.json"
    output_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    output_csv = Path(args.output_csv) if args.output_csv else root / "quality_arbitration.csv"
    if rows:
        with output_csv.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
    print(json.dumps({k: v for k, v in summary.items() if k != "cases"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

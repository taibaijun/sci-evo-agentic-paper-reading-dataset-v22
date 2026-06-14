from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sci_evo_pipeline.quality_first import (
    REVIEWER_ROLES,
    build_packet_markdown,
    doc_no,
    load_rule_detail,
    read_jsonl,
)


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Create V16 quality-first AI/subagent review packets.")
    parser.add_argument("--dataset-jsonl", required=True)
    parser.add_argument("--mineru-root", default=r"mineru_results")
    parser.add_argument("--rule-detail", default="")
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--case-ids", default="", help="Comma-separated doc numbers or case ids.")
    parser.add_argument("--roles", default=",".join(REVIEWER_ROLES), help="Comma-separated reviewer roles.")
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
    roles = [role.strip() for role in args.roles.split(",") if role.strip()]
    rule_map = load_rule_detail(Path(args.rule_detail) if args.rule_detail else None)
    mineru_root = Path(args.mineru_root)
    output_root = Path(args.output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    index = []

    for case in cases:
        d = doc_no(case)
        full_text_path = mineru_root / "docs" / d / "combined.md"
        case_dir = output_root / d
        case_dir.mkdir(parents=True, exist_ok=True)
        for role in roles:
            packet = build_packet_markdown(
                case=case,
                full_text_path=full_text_path,
                rule_audit=rule_map.get(d),
                role=role,
            )
            packet_path = case_dir / f"{role}.md"
            packet_path.write_text(packet, encoding="utf-8")
            index.append(
                {
                    "doc_no": d,
                    "case_id": case.get("case_id", ""),
                    "role": role,
                    "packet": str(packet_path),
                    "full_text": str(full_text_path),
                    "review_output_expected": str(case_dir / f"{role}.review.json"),
                }
            )
    (output_root / "packet_index.json").write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"case_count": len(cases), "packet_count": len(index), "output_root": str(output_root)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

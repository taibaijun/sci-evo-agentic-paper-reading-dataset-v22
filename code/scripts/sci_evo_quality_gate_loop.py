from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


def run_cmd(cmd: list[str], *, capture_json_to: Path | None = None) -> dict:
    print("RUN", " ".join(cmd))
    proc = subprocess.run(cmd, text=True, encoding="utf-8", errors="replace", capture_output=True)
    if proc.stdout:
        print(proc.stdout.strip())
    if proc.stderr:
        print(proc.stderr.strip(), file=sys.stderr)
    if proc.returncode:
        raise SystemExit(proc.returncode)
    if capture_json_to:
        capture_json_to.parent.mkdir(parents=True, exist_ok=True)
        payload = json.loads(proc.stdout)
        capture_json_to.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return payload
    return {}


def add_if_value(cmd: list[str], flag: str, value: str) -> None:
    if value:
        cmd.extend([flag, value])


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Run the V16 quality gate loop with code audit plus optional full-paper AI review.")
    parser.add_argument("--dataset-jsonl", required=True)
    parser.add_argument("--mineru-root", default=r"mineru_results")
    parser.add_argument("--work-root", required=True)
    parser.add_argument("--case-ids", default="")
    parser.add_argument("--full-review-dir", default="", help="Optional existing full-paper review dir for rule audit.")
    parser.add_argument("--roles", default="paper_cartographer,trajectory_judge,evidence_auditor,red_team,repair_planner")
    parser.add_argument("--run-deepseek", action="store_true", help="Actually call DeepSeek reviewers for risk cases.")
    parser.add_argument("--deepseek-max-cases", type=int, default=0)
    parser.add_argument("--deepseek-model", default=os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash"))
    parser.add_argument("--deepseek-base-url", default=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"))
    parser.add_argument("--deepseek-force", action="store_true")
    args = parser.parse_args()

    root = Path(args.work_root)
    audits = root / "audits"
    packets = root / "packets"
    root.mkdir(parents=True, exist_ok=True)
    audits.mkdir(parents=True, exist_ok=True)

    py = sys.executable
    common_case_args: list[str] = []
    add_if_value(common_case_args, "--case-ids", args.case_ids)

    evidence_json = audits / "quality_evidence_audit.json"
    structure_json = audits / "quality_structure_audit.json"
    rule_root = audits / "rule_audit"
    rule_detail = rule_root / "rule_audit_detail.json"
    arbitration_json = root / "quality_arbitration_with_rule_risk.json"
    arbitration_csv = root / "quality_arbitration_with_rule_risk.csv"

    run_cmd(
        [
            py,
            "scripts/sci_evo_quality_evidence_audit.py",
            "--dataset-jsonl",
            args.dataset_jsonl,
            "--mineru-root",
            args.mineru_root,
            "--output-json",
            str(evidence_json),
            "--output-csv",
            str(audits / "quality_evidence_audit.csv"),
            *common_case_args,
        ]
    )
    run_cmd(
        [
            py,
            "scripts/sci_evo_quality_structure_audit.py",
            "--dataset-jsonl",
            args.dataset_jsonl,
            "--output-json",
            str(structure_json),
            "--output-csv",
            str(audits / "quality_structure_audit.csv"),
            *common_case_args,
        ]
    )

    rule_cmd = [
        py,
        "scripts/sci_evo_rule_audit.py",
        "--dataset-jsonl",
        args.dataset_jsonl,
        "--mineru-root",
        args.mineru_root,
        "--output-root",
        str(rule_root),
        *common_case_args,
    ]
    rule_cmd.extend(["--full-review-dir", args.full_review_dir])
    run_cmd(rule_cmd)

    run_cmd(
        [
            py,
            "scripts/sci_evo_make_quality_packets.py",
            "--dataset-jsonl",
            args.dataset_jsonl,
            "--mineru-root",
            args.mineru_root,
            "--rule-detail",
            str(rule_detail),
            "--output-root",
            str(packets),
            "--roles",
            args.roles,
            *common_case_args,
        ]
    )

    review_cmd = [
        py,
        "scripts/sci_evo_review_packets_deepseek.py",
        "--packet-index",
        str(packets / "packet_index.json"),
        "--rule-audit-json",
        str(rule_detail),
        "--risk-only",
        "--model",
        args.deepseek_model,
        "--base-url",
        args.deepseek_base_url,
    ]
    if args.deepseek_max_cases:
        review_cmd.extend(["--max-cases", str(args.deepseek_max_cases)])
    if args.deepseek_force:
        review_cmd.append("--force")
    if args.run_deepseek:
        run_cmd(review_cmd)
    else:
        run_cmd(review_cmd + ["--dry-run"], capture_json_to=root / "deepseek_risk_selection_dry_run.json")

    run_cmd(
        [
            py,
            "scripts/sci_evo_arbitrate_quality_reviews.py",
            "--review-root",
            str(packets),
            "--evidence-audit-json",
            str(evidence_json),
            "--structure-audit-json",
            str(structure_json),
            "--rule-audit-json",
            str(rule_detail),
            "--output-json",
            str(arbitration_json),
            "--output-csv",
            str(arbitration_csv),
        ],
        capture_json_to=root / "quality_arbitration_summary.json",
    )

    print(
        json.dumps(
            {
                "work_root": str(root),
                "arbitration_json": str(arbitration_json),
                "arbitration_csv": str(arbitration_csv),
                "packets": str(packets),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

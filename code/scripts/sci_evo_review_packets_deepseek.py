from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sci_evo_pipeline.deepseek_client import DeepSeekClient
from sci_evo_pipeline.quality_arbiter import load_rule_audit_map, rule_audit_to_review
from sci_evo_pipeline.quality_agents import review_packet_with_deepseek


def safe_int(value: object, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def risk_score(rule_audit: dict) -> int:
    warnings = [str(item) for item in (rule_audit.get("warnings") or [])]
    score = safe_int(rule_audit.get("warning_count"), len(warnings))
    step_count = safe_int(rule_audit.get("step_count"))
    if safe_int(rule_audit.get("error_count")):
        score += 100
    if rule_audit.get("rule_decision") in {"fail", "review"}:
        score += 50
    if any(w.startswith("short_trajectory") for w in warnings) or (0 < step_count < 5):
        score += 90 if step_count <= 3 else 60
    numeric_full_count = sum(1 for w in warnings if "numeric tokens not found in full paper" in w)
    numeric_evidence_count = sum(1 for w in warnings if "numeric tokens not in this step evidence quote" in w)
    score += 20 * numeric_full_count
    score += 8 * numeric_evidence_count
    if numeric_full_count >= 4:
        score += 40
    if numeric_evidence_count >= 5:
        score += 25
    if len(warnings) >= 6:
        score += 30
    if any("phase_backtrack_count=" in w for w in warnings):
        score += 5
    if any("phase_backtrack_count=2" in w or "phase_backtrack_count=3" in w for w in warnings):
        score += 20
    return score


def unique_ordered(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


def resolve_existing_path(path_text: str, *, fallback_root: Path) -> Path:
    path = Path(path_text)
    if path.is_absolute() or path.exists():
        return path
    rooted = fallback_root / path
    if rooted.exists():
        return rooted
    return path


def resolve_output_path(path_text: str, *, fallback_root: Path) -> Path:
    path = Path(path_text)
    if path.is_absolute():
        return path
    # Packet indices generated from the workspace already contain paths such
    # as outputs/... . Treat those as workspace-relative first, otherwise the
    # fallback root would duplicate the outputs/quality_gate... prefix.
    if path.parts and path.parts[0] in {"outputs", "data", "docs"}:
        return path
    return fallback_root / path


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Run DeepSeek reviewers over V16 quality packets.")
    parser.add_argument("--packet-index", required=True)
    parser.add_argument("--roles", default="", help="Comma-separated roles; default uses roles in packet index.")
    parser.add_argument("--case-ids", default="", help="Comma-separated doc numbers or case ids.")
    parser.add_argument("--rule-audit-json", default="", help="Optional rule_audit_detail.json for risk-prioritized review.")
    parser.add_argument("--risk-only", action="store_true", help="Review only cases that rule-audit risk says cannot be code-only passed.")
    parser.add_argument(
        "--risk-roles",
        default="trajectory_judge,evidence_auditor,red_team,repair_planner",
        help="Roles to use when --risk-only is set and --roles is omitted.",
    )
    parser.add_argument("--max-cases", type=int, default=0, help="Limit distinct selected cases after risk ranking.")
    parser.add_argument("--model", default=os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash"))
    parser.add_argument("--base-url", default=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"))
    parser.add_argument("--temperature", type=float, default=0.05)
    parser.add_argument("--max-tokens", type=int, default=8192)
    parser.add_argument("--sleep-sec", type=float, default=0.0)
    parser.add_argument("--dry-run", action="store_true", help="Print selected packets without calling DeepSeek.")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    packet_index_path = Path(args.packet_index)
    packet_root = packet_index_path.parent
    index = json.loads(packet_index_path.read_text(encoding="utf-8"))
    roles = {x.strip() for x in args.roles.split(",") if x.strip()}
    if args.risk_only and not roles:
        roles = {x.strip() for x in args.risk_roles.split(",") if x.strip()}
    wanted = {x.strip() for x in args.case_ids.split(",") if x.strip()}
    normalized_wanted = set()
    for item in wanted:
        normalized_wanted.add(item)
        if item.isdigit():
            normalized_wanted.add(f"{int(item):04d}")
            normalized_wanted.add(f"sci_evo_{int(item):04d}")

    rule_map = {}
    risk_docs: set[str] = set()
    risk_ranked_docs: list[str] = []
    if args.rule_audit_json:
        rule_map = load_rule_audit_map(json.loads(Path(args.rule_audit_json).read_text(encoding="utf-8")))
        risky = []
        for doc_no, audit in rule_map.items():
            if rule_audit_to_review(audit):
                risky.append((risk_score(audit), doc_no))
        risk_ranked_docs = [doc_no for _, doc_no in sorted(risky, reverse=True)]
        risk_docs = set(risk_ranked_docs)
    if args.risk_only and not rule_map:
        raise SystemExit("--risk-only requires --rule-audit-json")
    if args.risk_only and normalized_wanted:
        wanted_docs = {item for item in normalized_wanted if item.isdigit() and len(item) == 4}
        wanted_docs.update(item.split("_")[-1].zfill(4) for item in normalized_wanted if item.startswith("sci_evo_"))
        risk_docs &= wanted_docs
        risk_ranked_docs = [doc for doc in risk_ranked_docs if doc in risk_docs]
    if args.risk_only:
        packet_doc_candidates = []
        for item in index:
            if roles and item.get("role") not in roles:
                continue
            if normalized_wanted and item.get("doc_no") not in normalized_wanted and item.get("case_id") not in normalized_wanted:
                continue
            packet_doc_candidates.append(str(item.get("doc_no", "")))
        packet_docs = set(packet_doc_candidates)
        risk_ranked_docs = [doc for doc in risk_ranked_docs if doc in packet_docs]
        risk_docs = set(risk_ranked_docs)
    if args.max_cases and risk_ranked_docs:
        risk_ranked_docs = risk_ranked_docs[: args.max_cases]
        risk_docs = set(risk_ranked_docs)

    selected = []
    for item in index:
        if roles and item.get("role") not in roles:
            continue
        if normalized_wanted and item.get("doc_no") not in normalized_wanted and item.get("case_id") not in normalized_wanted:
            continue
        if args.risk_only and item.get("doc_no") not in risk_docs:
            continue
        selected.append(item)

    if args.dry_run:
        distinct_docs = sorted({str(item.get("doc_no")) for item in selected})
        selected_doc_order = unique_ordered([str(item.get("doc_no", "")) for item in selected])
        priority_docs = [doc for doc in risk_ranked_docs if doc in set(distinct_docs)]
        print(
            json.dumps(
                {
                    "selected_packets": len(selected),
                    "selected_case_count": len(distinct_docs),
                    "selected_cases": distinct_docs,
                    "selected_cases_by_risk": priority_docs or selected_doc_order,
                    "roles": sorted({str(item.get("role")) for item in selected}),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return

    api_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("DEEPSEEK_API_KEY is not set")

    client = DeepSeekClient(api_key=api_key, model=args.model, base_url=args.base_url)
    outputs = []
    for item in selected:
        packet_path = resolve_existing_path(item["packet"], fallback_root=packet_root.parent)
        out_path = resolve_output_path(item["review_output_expected"], fallback_root=packet_root.parent)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        if out_path.exists() and not args.force:
            outputs.append({"packet": str(packet_path), "output": str(out_path), "status": "skipped_exists"})
            continue
        review = review_packet_with_deepseek(
            client=client,
            packet_path=packet_path,
            role=item["role"],
            temperature=args.temperature,
            max_tokens=args.max_tokens,
        )
        out_path.write_text(json.dumps(review, ensure_ascii=False, indent=2), encoding="utf-8")
        outputs.append({"packet": str(packet_path), "output": str(out_path), "status": "reviewed"})
        if args.sleep_sec:
            time.sleep(args.sleep_sec)

    print(
        json.dumps(
            {
                "selected": len(selected),
                "risk_case_count": len(risk_docs) if args.risk_only else 0,
                "reviewed": sum(1 for item in outputs if item["status"] == "reviewed"),
                "skipped": sum(1 for item in outputs if item["status"] == "skipped_exists"),
                "outputs": outputs,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

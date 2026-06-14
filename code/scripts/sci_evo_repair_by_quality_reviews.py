from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sci_evo_pipeline.deepseek_client import DeepSeekClient
from sci_evo_pipeline.full_paper_repair import quote_errors_against_full_text
from sci_evo_pipeline.schema import normalize_case, validate_case, write_dataset_jsonl


REPAIR_SYSTEM = """You are a conservative scientific dataset editor.
You repair Sci-Evo JSON cases using full-paper text and strict reviewer findings.
Output valid JSON only.
Do not invent facts. Prefer removing, narrowing, or correcting unsupported detail over adding unsupported precision.
"""


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def doc_no(case: dict[str, Any]) -> str:
    return str(case.get("case_id", "")).split("_")[-1].zfill(4)


def compact_review(review: dict[str, Any]) -> dict[str, Any]:
    return {
        "reviewer_role": review.get("reviewer_role", ""),
        "verdict": review.get("verdict", ""),
        "confidence": review.get("confidence", 0),
        "dimension_scores": review.get("dimension_scores", {}),
        "summary": str(review.get("summary", ""))[:1200],
        "blockers": [
            {
                "type": b.get("type", ""),
                "severity": b.get("severity", ""),
                "affected_steps": b.get("affected_steps", []),
                "problem": str(b.get("problem", ""))[:1000],
                "code_fix_hint": str(b.get("code_fix_hint", ""))[:800],
            }
            for b in (review.get("blockers") or [])[:10]
            if isinstance(b, dict)
        ],
        "repairs": [
            {
                "priority": r.get("priority", ""),
                "target": r.get("target", ""),
                "description": str(r.get("description", ""))[:1000],
                "code_fix_hint": str(r.get("code_fix_hint", ""))[:800],
            }
            for r in (review.get("repairs") or [])[:8]
            if isinstance(r, dict)
        ],
    }


def load_quality_cases(path: Path) -> dict[str, dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    out: dict[str, dict[str, Any]] = {}
    for item in data.get("cases") or []:
        if isinstance(item, dict) and item.get("doc_no"):
            out[str(item["doc_no"]).zfill(4)] = item
    return out


def build_issue_bundle(quality_case: dict[str, Any]) -> dict[str, Any]:
    return {
        "doc_no": quality_case.get("doc_no", ""),
        "gate": quality_case.get("gate", {}),
        "fix_tags": quality_case.get("fix_tags", []),
        "high_blockers": [
            {
                "role": b.get("role", ""),
                "type": b.get("type", ""),
                "severity": b.get("severity", ""),
                "affected_steps": b.get("affected_steps", []),
                "problem": str(b.get("problem", ""))[:1000],
                "code_fix_hint": str(b.get("code_fix_hint", ""))[:800],
            }
            for b in (quality_case.get("high_blockers") or [])[:10]
            if isinstance(b, dict)
        ],
        "repair_hints": [
            {
                "role": r.get("role", ""),
                "priority": r.get("priority", ""),
                "target": r.get("target", ""),
                "description": str(r.get("description", ""))[:1000],
                "code_fix_hint": str(r.get("code_fix_hint", ""))[:800],
            }
            for r in (quality_case.get("repair_hints") or [])[:12]
            if isinstance(r, dict)
        ],
        "reviews": [
            compact_review(r)
            for r in (quality_case.get("reviews") or [])
            if isinstance(r, dict)
            and (
                r.get("verdict") != "pass"
                or r.get("blockers")
                or r.get("repairs")
            )
        ],
    }


def build_repair_prompt(case: dict[str, Any], full_text: str, issue_bundle: dict[str, Any]) -> str:
    return f"""Repair this Sci-Evo case as strict JSON.

Goal:
Resolve the reviewer blockers while preserving the useful scientific trajectory. The repaired case must be publication-quality, traceable, and grounded in the full paper.

Mandatory rules:
1. Keep the same case_id, dataset_type, domain, source, and overall paper identity.
2. You may rewrite, reorder, remove, or add trajectory steps only when required to fix reviewer blockers or a real paper-order problem.
3. Every numeric value, mutation, method name, metric, and conclusion must either be directly supported by same-step evidence, corrected to the paper, or removed.
4. Evidence quote_or_span must be an exact contiguous substring copied from the full paper text below. Keep each quote short but sufficient; prefer one quote that contains the critical number/mutation/method for that step.
5. Do not leave reviewer-identified factual errors in parameters, observation, success metrics, or limitations.
6. If a value is only approximate in the paper, write it approximately and cite the exact paper phrase.
7. Keep 5-10 coherent steps when the paper supports them. Include failures/partial decisions when they are part of the paper's evolution chain.
8. Add a quality_control.risk_notes entry beginning with "v17_quality_review_repaired:" describing the repaired issue categories.
9. Output valid JSON only with root key "case".

Reviewer issue bundle:
{json.dumps(issue_bundle, ensure_ascii=False, indent=2)}

Current case:
{json.dumps(case, ensure_ascii=False, indent=2)}

Full paper text:
<BEGIN_FULL_PAPER>
{full_text}
<END_FULL_PAPER>
"""


def repair_case(
    *,
    client: DeepSeekClient,
    case: dict[str, Any],
    full_text: str,
    issue_bundle: dict[str, Any],
    doc: str,
) -> dict[str, Any]:
    raw = client.chat_json(
        system_prompt=REPAIR_SYSTEM,
        user_prompt=build_repair_prompt(case, full_text, issue_bundle),
        temperature=0.0,
        max_tokens=8192,
    )
    candidate = raw.get("case") if isinstance(raw.get("case"), dict) else raw
    normalized = normalize_case(candidate, doc_no=doc, source=case.get("source", {}))
    notes = normalized.setdefault("quality_control", {}).setdefault("risk_notes", [])
    if isinstance(notes, list) and not any(str(n).startswith("v17_quality_review_repaired:") for n in notes):
        notes.append("v17_quality_review_repaired: AI quality blockers were repaired against full-paper text")
    return {
        "case": normalized,
        "validation_errors": validate_case(normalized),
        "full_text_quote_errors": quote_errors_against_full_text(normalized, full_text),
        "gate_before": issue_bundle.get("gate", {}),
        "fix_tags_before": issue_bundle.get("fix_tags", []),
        "api_usage": raw.get("_api_usage", {}),
        "api_model": raw.get("_api_model", ""),
        "api_finish_reason": raw.get("_api_finish_reason", ""),
    }


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Repair cases using quality-gate AI review findings and full paper text.")
    parser.add_argument("--dataset-jsonl", required=True)
    parser.add_argument("--quality-arbitration-json", required=True)
    parser.add_argument("--mineru-root", default=r"mineru_results")
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--case-ids", default="", help="Comma-separated doc numbers/case IDs; default repairs non-pass cases from arbitration.")
    parser.add_argument("--decisions", default="repair,fail", help="Comma-separated gate decisions to repair when --case-ids is omitted.")
    parser.add_argument("--model", default=os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash"))
    parser.add_argument("--api-base", default=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"))
    parser.add_argument("--api-key-env", default="DEEPSEEK_API_KEY")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    api_key = os.environ.get(args.api_key_env, "").strip()
    if not api_key:
        raise SystemExit(f"Missing API key. Set ${args.api_key_env} before running.")

    output_root = Path(args.output_root)
    cases_dir = output_root / "cases"
    cases_dir.mkdir(parents=True, exist_ok=True)

    base_cases = read_jsonl(Path(args.dataset_jsonl))
    quality_cases = load_quality_cases(Path(args.quality_arbitration_json))
    decisions = {x.strip() for x in args.decisions.split(",") if x.strip()}
    wanted = {x.strip() for x in args.case_ids.split(",") if x.strip()}
    normalized_wanted: set[str] = set()
    for item in wanted:
        normalized_wanted.add(item)
        if item.isdigit():
            normalized_wanted.add(f"{int(item):04d}")
            normalized_wanted.add(f"sci_evo_{int(item):04d}")

    docs_to_repair: set[str] = set()
    if normalized_wanted:
        for case in base_cases:
            d = doc_no(case)
            if d in normalized_wanted or case.get("case_id") in normalized_wanted:
                docs_to_repair.add(d)
    else:
        for d, item in quality_cases.items():
            if (item.get("gate") or {}).get("decision") in decisions:
                docs_to_repair.add(d)

    client = DeepSeekClient(api_key=api_key, model=args.model, base_url=args.api_base)
    repaired_by_doc: dict[str, dict[str, Any]] = {}
    results: dict[str, Any] = {}
    attempts = 0
    for case in base_cases:
        d = doc_no(case)
        if d not in docs_to_repair:
            continue
        attempts += 1
        if args.limit and attempts > args.limit:
            break
        out_path = cases_dir / f"{d}.json"
        if out_path.exists() and not args.overwrite:
            result = json.loads(out_path.read_text(encoding="utf-8"))
            print(f"[cached] {d}", flush=True)
        else:
            md_path = Path(args.mineru_root) / "docs" / d / "combined.md"
            if not md_path.exists():
                print(f"[skip] missing full paper {d}: {md_path}", flush=True)
                continue
            full_text = md_path.read_text(encoding="utf-8", errors="replace")
            issue_bundle = build_issue_bundle(quality_cases.get(d, {}))
            print(
                f"[repair {attempts}] {d} decision={(issue_bundle.get('gate') or {}).get('decision')} "
                f"title={case.get('source', {}).get('title', '')[:90]}",
                flush=True,
            )
            result = repair_case(
                client=client,
                case=case,
                full_text=full_text,
                issue_bundle=issue_bundle,
                doc=d,
            )
            out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            print(
                f"  schema_errors={len(result['validation_errors'])} quote_errors={len(result['full_text_quote_errors'])} "
                f"usage={json.dumps(result.get('api_usage', {}), ensure_ascii=False)}",
                flush=True,
            )
        results[d] = {
            "validation_errors": result.get("validation_errors", []),
            "full_text_quote_errors": result.get("full_text_quote_errors", []),
            "gate_before": result.get("gate_before", {}),
            "api_usage": result.get("api_usage", {}),
        }
        if not result.get("validation_errors"):
            repaired_by_doc[d] = result["case"]

    merged = [repaired_by_doc.get(doc_no(case), case) for case in base_cases]
    write_dataset_jsonl(output_root / "dataset.jsonl", merged)
    summary = {
        "input_dataset": args.dataset_jsonl,
        "quality_arbitration": args.quality_arbitration_json,
        "docs_to_repair": sorted(docs_to_repair),
        "attempted": min(attempts, args.limit) if args.limit else attempts,
        "repaired_schema_valid": len(repaired_by_doc),
        "cases": results,
    }
    (output_root / "repair_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps({k: v for k, v in summary.items() if k != "cases"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

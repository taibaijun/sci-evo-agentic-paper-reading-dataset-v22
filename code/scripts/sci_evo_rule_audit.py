from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sci_evo_pipeline.evidence_index import normalize_text
from sci_evo_pipeline.full_paper_repair import quote_errors_against_full_text
from sci_evo_pipeline.schema import validate_case


MUTATION_RE = re.compile(r"\b[A-Z][0-9]{1,4}[A-Z]\b")
VARIANT_RE = re.compile(r"\b[A-Z]{1,6}[-_][0-9]{1,4}\b")
NUMBER_RE = re.compile(
    r"(?<![A-Za-z])(?:~|\\~)?\d+(?:[.,]\d+)?(?:\s*(?:×|x|\\times)\s*10\^?\{?\d+\}?)?(?:\s*-\s*(?:to\s*)?(?:~|\\~)?\d+(?:[.,]\d+)?)?"
)
NUMBER_RE = re.compile(
    r"(?<![A-Za-z])(?:~|\\~)?\d+(?:[.,]\d+)?(?:\s*(?:脳|×|x|\\times)\s*10\^?\{?\d+\}?)?"
    r"(?:\s*[-–—−每]\s*(?:to\s*)?(?:~|\\~)?\d+(?:[.,]\d+)?)?"
)
UNIT_RE = re.compile(
    r"(?i)(?:fold|mM|uM|µM|μM|nM|%|TTN|turnover|transformant|variant|colon|day|hour|h\b|min\b|s-1|mM-1)"
)
GENERIC_NUMBERS = {"0", "1", "2", "3", "4", "5", "6", "7", "8", "9", "10"}
UNIT_ENTITY_STOP = {"m-1", "s-1", "min-1", "h-1", "m_1", "s_1"}
LOW_SCIEVO_TITLE_RE = re.compile(
    r"\b("
    r"software|visualization|benchmark(?:ing)?|drug repurposing|fda-approved drugs|"
    r"virtual screening|docking enrichment|variant effect predictor|variant effect predictability|"
    r"disease mutation|anti-quorum sensing agents|analysis tool"
    r")\b",
    re.I,
)
PHASE_ORDER = {
    "hypothesis": 0,
    "design": 1,
    "simulation": 2,
    "experiment": 3,
    "analysis": 4,
    "revision": 5,
    "validation": 6,
}


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def squash(text: str) -> str:
    raw = str(text or "")
    raw = raw.replace("\\times", "x").replace("\\sim", "~").replace("\\~", "~")
    text = raw
    text = text.replace("×", "x").replace("μ", "u").replace("µ", "u")
    text = text.replace("\\times", "x").replace("\\sim", "~").replace("\\~", "~")
    text = re.sub(r"(?<=\d)[–—−每](?=\d)", "-", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip().lower()


def compact_token(token: str) -> str:
    token = squash(token)
    token = token.replace(",", "")
    token = token.replace(" ", "")
    token = token.replace("{", "").replace("}", "")
    token = token.replace("^", "")
    token = token.replace("~", "")
    token = token.replace("-to", "-")
    return token


def compact_corpus(text: str) -> str:
    return compact_token(squash(text or ""))


def number_supported(token: str, numbers: set[str], compact_text: str) -> bool:
    if token in numbers or token in compact_text:
        return True
    range_match = re.fullmatch(r"(\d+(?:\.\d+)?)-(\d+(?:\.\d+)?)", token)
    if range_match:
        start, end = range_match.groups()
        start_positions = [m.start() for m in re.finditer(re.escape(start), compact_text)]
        end_positions = [m.start() for m in re.finditer(re.escape(end), compact_text)]
        if any(0 <= ep - sp <= 80 for sp in start_positions for ep in end_positions):
            return True
    if re.fullmatch(r"\d{7,}", token):
        value = int(token)
        if value % 1_000_000 == 0 and f"{value // 1_000_000}million" in compact_text:
            return True
        if value % 1_000 == 0 and f"{value // 1_000}thousand" in compact_text:
            return True
    if token.startswith("0."):
        try:
            percent = float(token) * 100
        except ValueError:
            percent = None
        if percent is not None:
            candidates = {f"{percent:g}%", f"{percent:.1f}%"}
            if any(compact_token(item) in compact_text for item in candidates):
                return True
    return False


def extract_numbers(text: str) -> set[str]:
    out: set[str] = set()
    for match in NUMBER_RE.finditer(text or ""):
        raw = match.group(0).strip()
        if not raw:
            continue
        start, end = match.span()
        window = text[max(0, start - 120) : min(len(text), end + 120)]
        if "," in raw and re.fullmatch(r"\d+(?:,\d+)+", raw) and re.search(
            r"residue|position|site|target|codon", window, re.I
        ):
            for part in raw.split(","):
                token = compact_token(part)
                if token:
                    out.add(token)
            continue
        compact = compact_token(raw)
        if compact in GENERIC_NUMBERS and not UNIT_RE.search(window):
            continue
        out.add(compact)
    return out


def extract_entities(text: str) -> set[str]:
    out = set()
    for regex in [MUTATION_RE, VARIANT_RE]:
        for item in regex.findall(text or ""):
            token = compact_token(item)
            if token in UNIT_ENTITY_STOP:
                continue
            out.add(token)
    return out


def extract_critical_tokens(text: str) -> tuple[set[str], set[str]]:
    return extract_numbers(text), extract_entities(text)


def step_claim_text(step: dict[str, Any]) -> str:
    parts = [
        step.get("decision", ""),
        step.get("observation", ""),
        step.get("next_step_reason", ""),
        step.get("hypothesis", ""),
        json.dumps(step.get("parameters", {}), ensure_ascii=False),
    ]
    return " ".join(str(p) for p in parts)


def step_evidence_text(step: dict[str, Any]) -> str:
    parts = []
    for ev in step.get("evidence") or []:
        if isinstance(ev, dict):
            parts.append(str(ev.get("quote_or_span", "")))
    return " ".join(parts)


def doc_no(case: dict[str, Any]) -> str:
    return str(case.get("case_id", "")).split("_")[-1].zfill(4)


def audit_case(case: dict[str, Any], *, mineru_root: Path, full_review_dir: Path | None) -> dict[str, Any]:
    d = doc_no(case)
    md_path = mineru_root / "docs" / d / "combined.md"
    errors: list[str] = []
    warnings: list[str] = []
    info: list[str] = []

    errors.extend(validate_case(case))
    if not md_path.exists():
        errors.append(f"missing full paper markdown: {md_path}")
        full_text = ""
    else:
        full_text = md_path.read_text(encoding="utf-8", errors="replace")
        for item in quote_errors_against_full_text(case, full_text):
            errors.append(f"quote_full_text: {item}")
    full_numbers, full_entities = extract_critical_tokens(full_text)
    compact_full_text = compact_corpus(full_text)

    steps = case.get("evolution_trajectory") or []
    title = str(case.get("source", {}).get("title", ""))
    header_text = "\n".join(full_text.splitlines()[:18])
    is_review_article = bool(re.search(r"(?im)^\s*review\s*$", header_text)) or bool(
        re.search(r"\b(review|perspective|commentary)\b", title, re.I)
    )
    high_warning_count = 0
    if is_review_article:
        high_warning_count += 1
        warnings.append("review_article_not_primary_research")
    if LOW_SCIEVO_TITLE_RE.search(title):
        high_warning_count += 1
        warnings.append("source_low_scievo_suitability")
    if len(steps) < 5:
        warnings.append(f"short_trajectory: only {len(steps)} steps")

    evidence_quotes = []
    prev_phase = -1
    phase_backtracks = 0
    for step in steps:
        step_index = step.get("step_index", "?")
        evidences = [ev for ev in step.get("evidence") or [] if isinstance(ev, dict)]
        if not evidences:
            errors.append(f"step {step_index}: missing evidence")
        claim_numbers, claim_entities = extract_critical_tokens(step_claim_text(step))
        evidence_text = step_evidence_text(step)
        evidence_numbers, evidence_entities = extract_critical_tokens(evidence_text)
        compact_evidence_text = compact_corpus(evidence_text)
        missing_entities_from_step_evidence = sorted(t for t in claim_entities if t not in evidence_entities)
        missing_numbers_from_step_evidence = sorted(t for t in claim_numbers if not number_supported(t, evidence_numbers, compact_evidence_text))
        missing_entities_from_paper = sorted(t for t in claim_entities if t not in full_entities)
        missing_numbers_from_paper = sorted(t for t in claim_numbers if not number_supported(t, full_numbers, compact_full_text))
        if missing_entities_from_paper:
            errors.append(
                f"step {step_index}: mutation/variant tokens not found in full paper: "
                + ", ".join(missing_entities_from_paper[:12])
            )
        if missing_numbers_from_paper:
            warnings.append(
                f"step {step_index}: numeric tokens not found in full paper after normalization: "
                + ", ".join(missing_numbers_from_paper[:12])
            )
        if missing_entities_from_step_evidence:
            high_warning_count += len(missing_entities_from_step_evidence)
            warnings.append(
                f"step {step_index}: mutation/variant tokens not in this step evidence quote: "
                + ", ".join(missing_entities_from_step_evidence[:12])
            )
        if missing_numbers_from_step_evidence:
            warnings.append(
                f"step {step_index}: numeric tokens not in this step evidence quote: "
                + ", ".join(missing_numbers_from_step_evidence[:12])
            )

        for ev in evidences:
            source_file = str(ev.get("source_file", ""))
            quote = str(ev.get("quote_or_span", "")).strip()
            if f"/{d}/" not in source_file.replace("\\", "/") and source_file:
                errors.append(f"step {step_index}: evidence source_file may not match case doc_no: {source_file}")
            if len(quote) < 25:
                warnings.append(f"step {step_index}: short evidence quote")
            evidence_quotes.append(squash(quote))

        phase = step.get("phase")
        order = PHASE_ORDER.get(phase, prev_phase)
        if order < prev_phase - 2:
            phase_backtracks += 1
        prev_phase = max(prev_phase, order)

    if phase_backtracks:
        warnings.append(f"phase_backtrack_count={phase_backtracks}")

    duplicates = {q: n for q, n in Counter(evidence_quotes).items() if q and n >= 3}
    if duplicates:
        warnings.append(f"evidence_quote_reused_3plus={len(duplicates)}")

    full_review = case.get("quality_control", {}).get("full_paper_review", {})
    review_path = full_review_dir / f"{d}.json" if full_review_dir else None
    if review_path and review_path.exists():
        review = json.loads(review_path.read_text(encoding="utf-8"))
        full_review = {
            "full_paper_support_score": review.get("full_paper_support_score"),
            "weak_steps": review.get("weak_steps"),
            "severe_steps": review.get("severe_steps"),
            "recommended_action": review.get("recommended_action"),
        }
    if full_review:
        support = float(full_review.get("full_paper_support_score") or 0)
        weak = int(full_review.get("weak_steps") or 0)
        severe = int(full_review.get("severe_steps") or 0)
        if support < 0.90 or weak or severe:
            high_warning_count += 1
            warnings.append(f"ai_fullpaper_review_not_strict: support={support} weak={weak} severe={severe}")
        info.append(f"ai_fullpaper_support={support}")

    decision = "pass"
    if errors:
        decision = "fail"
    elif high_warning_count:
        decision = "review"

    return {
        "doc_no": d,
        "case_id": case.get("case_id", ""),
        "title": title,
        "step_count": len(steps),
        "error_count": len(errors),
        "warning_count": len(warnings),
        "high_warning_count": high_warning_count,
        "rule_decision": decision,
        "errors": errors,
        "warnings": warnings,
        "info": info,
    }


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Deterministic full-paper audit for Sci-Evo dataset.")
    parser.add_argument("--dataset-jsonl", default=r"outputs\submission_v3_fullpaper_strict\dataset.jsonl")
    parser.add_argument("--mineru-root", default=r"D:\mineru_flat_results_20260521_200done")
    parser.add_argument("--full-review-dir", default=r"outputs\full_paper_review_v3_repaired\reviews")
    parser.add_argument("--output-root", default=r"outputs\rule_audit_v3")
    parser.add_argument("--case-ids", default="")
    args = parser.parse_args()

    dataset_path = Path(args.dataset_jsonl)
    mineru_root = Path(args.mineru_root)
    full_review_dir = Path(args.full_review_dir) if args.full_review_dir else None
    output_root = Path(args.output_root)
    output_root.mkdir(parents=True, exist_ok=True)

    cases = read_jsonl(dataset_path)
    wanted = {x.strip() for x in args.case_ids.split(",") if x.strip()}
    if wanted:
        normalized = set()
        for item in wanted:
            normalized.add(item)
            if item.isdigit():
                normalized.add(f"{int(item):04d}")
                normalized.add(f"sci_evo_{int(item):04d}")
        cases = [case for case in cases if doc_no(case) in normalized or case.get("case_id") in normalized]
    ids = [c.get("case_id", "") for c in cases]
    duplicate_ids = sorted([case_id for case_id, count in Counter(ids).items() if count > 1])
    rows = [
        audit_case(case, mineru_root=mineru_root, full_review_dir=full_review_dir)
        for case in cases
    ]
    if duplicate_ids:
        for row in rows:
            if row["case_id"] in duplicate_ids:
                row["errors"].append(f"duplicate_case_id: {row['case_id']}")
                row["error_count"] = len(row["errors"])
                row["rule_decision"] = "fail"

    summary = {
        "dataset": str(dataset_path),
        "case_count": len(rows),
        "pass": sum(1 for r in rows if r["rule_decision"] == "pass"),
        "review": sum(1 for r in rows if r["rule_decision"] == "review"),
        "fail": sum(1 for r in rows if r["rule_decision"] == "fail"),
        "total_errors": sum(r["error_count"] for r in rows),
        "total_warnings": sum(r["warning_count"] for r in rows),
        "total_high_warnings": sum(r["high_warning_count"] for r in rows),
        "duplicate_case_ids": duplicate_ids,
        "checks": [
            "schema validation",
            "full-text evidence quote exactness",
            "critical number/mutation/variant token grounding",
            "evidence source doc_no consistency",
            "evidence reuse",
            "phase-order sanity",
            "AI full-paper review used as non-binding auxiliary signal",
        ],
    }
    (output_root / "rule_audit_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output_root / "rule_audit_detail.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    with (output_root / "rule_audit_report.csv").open("w", encoding="utf-8-sig", newline="") as f:
        fieldnames = [
            "doc_no",
            "case_id",
            "title",
            "step_count",
            "error_count",
            "warning_count",
            "high_warning_count",
            "rule_decision",
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})

    with (output_root / "rule_audit_issues.csv").open("w", encoding="utf-8-sig", newline="") as f:
        fieldnames = ["doc_no", "case_id", "severity", "message"]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            for message in row["errors"]:
                writer.writerow(
                    {
                        "doc_no": row["doc_no"],
                        "case_id": row["case_id"],
                        "severity": "error",
                        "message": message,
                    }
                )
            for message in row["warnings"]:
                severity = "high_warning" if "mutation/variant tokens not in this step evidence" in message else "warning"
                writer.writerow(
                    {
                        "doc_no": row["doc_no"],
                        "case_id": row["case_id"],
                        "severity": severity,
                        "message": message,
                    }
                )

    by_decision: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        by_decision[row["rule_decision"]].append(row["doc_no"])
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(json.dumps(dict(by_decision), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

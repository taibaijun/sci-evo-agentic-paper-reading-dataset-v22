from __future__ import annotations

import argparse
import importlib.util
import json
import re
import shutil
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sci_evo_pipeline.schema import write_dataset_jsonl


ROOT = Path(__file__).resolve().parents[1]
V14_PATH = ROOT / "scripts" / "sci_evo_make_v14_top50_pack.py"


def load_v14_module():
    spec = importlib.util.spec_from_file_location("sci_evo_make_v14_top50_pack", V14_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {V14_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


v14 = load_v14_module()
CORE16_DOCS = v14.CORE16_DOCS


def doc_no(case: dict[str, Any]) -> str:
    return str(case.get("case_id", "")).split("_")[-1].zfill(4)


def note(case: dict[str, Any], text: str) -> None:
    qc = case.setdefault("quality_control", {})
    notes = qc.setdefault("risk_notes", [])
    if isinstance(notes, list) and text not in notes:
        notes.append(text)


def step_text(step: dict[str, Any]) -> str:
    parts = [
        step.get("state_before", ""),
        step.get("gap_or_uncertainty", ""),
        step.get("hypothesis", ""),
        step.get("decision", ""),
        step.get("observation", ""),
        step.get("next_step_reason", ""),
        json.dumps(step.get("parameters", {}), ensure_ascii=False),
    ]
    return " ".join(str(x) for x in parts if x)


def trajectory_text(case: dict[str, Any]) -> str:
    return " ".join(step_text(s) for s in case.get("evolution_trajectory") or [])


def evidence_text(step: dict[str, Any]) -> str:
    return " ".join(str(ev.get("quote_or_span", "")) for ev in step.get("evidence") or [] if isinstance(ev, dict))


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip().lower()


def split_spans(text: str) -> list[str]:
    cleaned = text.replace("\r\n", "\n")
    parts = re.split(r"(?<=[.!?。])\s+|\n{2,}|(?<=\|)\n", cleaned)
    spans = []
    for part in parts:
        part = re.sub(r"\s+", " ", part).strip()
        if 45 <= len(part) <= 320:
            spans.append(part)
        elif len(part) > 320:
            for start in range(0, len(part), 260):
                piece = part[start : start + 300].strip()
                if len(piece) >= 45:
                    spans.append(piece)
    return spans


def token_candidates(text: str) -> list[str]:
    tokens: set[str] = set()
    for m in re.finditer(r"\b[A-Z][0-9]{1,4}[A-Z]\b", text):
        tokens.add(m.group(0))
    number_pattern = re.compile(
        r"(?<![A-Za-z0-9])(?:~|>|<|>=|<=)?\d+(?:\.\d+)?(?:\s*(?:-|to|–|—)\s*\d+(?:\.\d+)?)?\s*(?:%|fold|mM|uM|µM|μM|mg|g/L|U/mg|nm|h|min|s|°C|掳C|C)?",
        re.IGNORECASE,
    )
    for m in number_pattern.finditer(text):
        token = re.sub(r"\s+", " ", m.group(0)).strip()
        digits = re.sub(r"\D", "", token)
        has_unit = bool(re.search(r"%|fold|mM|uM|µM|μM|mg|g/L|U/mg|nm|h|min|s|°C|掳C", token, re.I))
        has_range = bool(re.search(r"-|to|–|—", token))
        if len(digits) >= 2 or "." in token or has_unit or has_range:
            tokens.add(token)
    return sorted(tokens, key=lambda x: (-len(x), x.lower()))


def find_span_with_token(full_text: str, spans: list[str], token: str, context_terms: list[str]) -> str:
    token_norm = normalize(token)
    best = ""
    best_score = -1
    for span in spans:
        sn = normalize(span)
        if token_norm not in sn:
            continue
        score = 10
        for term in context_terms:
            if term and normalize(term) in sn:
                score += 2
        if score > best_score:
            best = span
            best_score = score
    if best:
        return best
    idx = normalize(full_text).find(token_norm)
    if idx < 0:
        return ""
    raw_start = max(0, idx - 120)
    raw_end = min(len(full_text), idx + len(token) + 180)
    return re.sub(r"\s+", " ", full_text[raw_start:raw_end]).strip()[:300]


def next_evidence_id(step: dict[str, Any]) -> str:
    max_id = 0
    for ev in step.get("evidence") or []:
        m = re.search(r"(\d+)$", str(ev.get("evidence_id", "")))
        if m:
            max_id = max(max_id, int(m.group(1)))
    return f"EV15_{max_id + 1:02d}"


def ensure_evidence_list(step: dict[str, Any]) -> list[dict[str, Any]]:
    ev = step.get("evidence")
    if not isinstance(ev, list):
        step["evidence"] = []
    return step["evidence"]


def add_quote(step: dict[str, Any], doc: str, quote: str, section: str = "Full paper") -> bool:
    quote_norm = normalize(quote)
    if not quote_norm:
        return False
    ev_list = ensure_evidence_list(step)
    if any(normalize(ev.get("quote_or_span", "")) == quote_norm for ev in ev_list if isinstance(ev, dict)):
        return False
    ev_list.append(
        {
            "evidence_id": next_evidence_id(step),
            "source_file": f"docs/{doc}/combined.md",
            "section": section,
            "quote_or_span": quote,
        }
    )
    return True


def improve_numeric_grounding(case: dict[str, Any], full_text: str, spans: list[str]) -> int:
    added = 0
    doc = doc_no(case)
    for step in case.get("evolution_trajectory") or []:
        st = step_text(step)
        ev_text = evidence_text(step)
        context_terms = []
        tool = step.get("tool_or_method") if isinstance(step.get("tool_or_method"), dict) else {}
        context_terms.extend(str(tool.get(k, "")) for k in ["name", "category"])
        context_terms.extend(re.findall(r"\b[A-Z][A-Za-z0-9+-]{2,}\b", st)[:8])
        missing = [tok for tok in token_candidates(st) if normalize(tok) not in normalize(ev_text) and normalize(tok) in normalize(full_text)]
        for tok in missing[:3]:
            quote = find_span_with_token(full_text, spans, tok, context_terms)
            if quote and add_quote(step, doc, quote, section="Auto evidence expansion"):
                added += 1
    if added:
        note(case, f"v15_numeric_evidence_expanded={added}")
    return added


PROBLEM_HINTS = [
    "problem",
    "challenge",
    "limitation",
    "limited",
    "lack",
    "difficult",
    "need",
    "low",
    "unstable",
    "bottleneck",
    "drawback",
    "disadvantage",
    "high cost",
    "experimentally demanding",
    "flexibility",
    "combinatorial complexity",
    "sequence space",
    "throughput",
    "library sizes",
    "however",
]
PROBLEM_ANTI_HINTS = [
    "overcomes",
    "we developed",
    "we present",
    "finally",
    "resulted",
    "yielded",
    "subsequently",
]


def find_problem_quote(full_text: str, spans: list[str], research_problem: str) -> str:
    problem_terms = [w.lower() for w in re.findall(r"[A-Za-z]{5,}", research_problem)[:8]]
    best = ""
    best_score = -1
    for span in spans[:220]:
        sn = normalize(span)
        score = sum(3 for h in PROBLEM_HINTS if h in sn)
        score += sum(1 for t in problem_terms if t in sn)
        score -= sum(3 for h in PROBLEM_ANTI_HINTS if h in sn)
        if re.search(r"10\^?\{?[48]\}?|10\^?\{?[59]\}?", span):
            score += 4
        if "we need creative solutions" in sn:
            score += 8
        if "disadvantages" in sn and "lack flexibility" in sn:
            score += 8
        if score > best_score:
            best = span
            best_score = score
    return best if best_score >= 3 else ""


def strengthen_problem_framing(case: dict[str, Any], full_text: str, spans: list[str]) -> int:
    steps = case.get("evolution_trajectory") or []
    if not steps:
        return 0
    first = steps[0]
    initial = case.get("initial_request", {})
    research_problem = str(initial.get("research_problem", "") or "")
    quote = find_problem_quote(full_text, spans, research_problem)
    if not quote:
        return 0
    if "v15_problem_framing_step" in normalize(trajectory_text(case)):
        return 0
    old_first_summary = step_text(first)[:500]
    problem_step = {
        "step_index": 0,
        "phase": "hypothesis",
        "state_before": "The paper begins from a research bottleneck that motivates the subsequent engineering workflow.",
        "gap_or_uncertainty": quote,
        "hypothesis": "A structured engineering or evolution strategy can address this paper-level bottleneck.",
        "decision": "Frame the paper-level research problem before choosing concrete design, screening, or validation actions.",
        "action_type": "literature_reasoning",
        "tool_or_method": {"name": "Problem framing from full paper", "version": "", "category": "reasoning"},
        "parameters": {},
        "observation": quote,
        "result_status": "success",
        "next_step_reason": f"This framing motivates the original first design step: {old_first_summary}",
        "evidence": [
            {
                "evidence_id": "EV15_01",
                "source_file": f"docs/{doc_no(case)}/combined.md",
                "section": "Problem framing",
                "quote_or_span": quote,
            }
        ],
    }
    case.setdefault("evolution_trajectory", []).insert(0, problem_step)
    reindex_steps(case)
    note(case, "v15_problem_framing_step_added")
    return 1


PROCESS_PATTERNS = [
    {
        "name": "failed_transformants_resolution",
        "needles": ["no transformants"],
        "decision": "Record the failed library-construction attempt and the troubleshooting change.",
        "phase": "revision",
        "result_status": "partial",
        "after_keywords": ["assembly", "library", "construct"],
    },
    {
        "name": "not_screened_after_preliminary_result",
        "needles": ["not screened", "maintain activity"],
        "decision": "Record the preliminary screening result that changed which library was screened next.",
        "phase": "analysis",
        "result_status": "partial",
        "after_keywords": ["screen", "library"],
    },
    {
        "name": "negative_selection",
        "needles": ["negative selection", "uninduced"],
        "decision": "Record the negative-selection step used to remove constitutively active or false-positive variants.",
        "phase": "revision",
        "result_status": "success",
        "after_keywords": ["positive selection", "selection", "sort"],
    },
    {
        "name": "growth_selection_platform",
        "needles": ["growth selection platform", "cell growth"],
        "decision": "Describe the growth-coupled selection platform before using it for directed evolution.",
        "phase": "design",
        "result_status": "success",
        "after_keywords": ["problem framing", "research problem"],
    },
    {
        "name": "top_prediction_screen",
        "needles": ["top 25", "in silico"],
        "decision": "Record the in silico combinatorial screening and experimental testing of top predicted variants.",
        "phase": "simulation",
        "result_status": "success",
        "after_keywords": ["machine learning", "model", "training"],
    },
]


def find_pattern_quote(spans: list[str], needles: list[str]) -> str:
    best = ""
    best_score = -1
    for span in spans:
        sn = normalize(span)
        score = sum(1 for n in needles if n in sn)
        if score > best_score:
            best = span
            best_score = score
    return best if best_score == len(needles) else ""


def insert_process_checkpoints(case: dict[str, Any], spans: list[str]) -> int:
    added = 0
    doc = doc_no(case)
    traj_norm = normalize(trajectory_text(case))
    for pattern in PROCESS_PATTERNS:
        if any(n in traj_norm for n in pattern["needles"]):
            continue
        quote = find_pattern_quote(spans, pattern["needles"])
        if not quote:
            continue
        new_step = {
            "step_index": 0,
            "phase": pattern["phase"],
            "state_before": "A process checkpoint in the paper changed or validated the research trajectory.",
            "gap_or_uncertainty": "Whether the current workflow would avoid false positives or proceed as planned.",
            "hypothesis": "Capturing the checkpoint improves fidelity to the paper's scientific evolution process.",
            "decision": pattern["decision"],
            "action_type": "analysis" if pattern["phase"] in {"analysis", "revision"} else "dry_experiment",
            "tool_or_method": {"name": "Paper process checkpoint", "version": "", "category": pattern["phase"]},
            "parameters": {},
            "observation": quote,
            "result_status": pattern["result_status"],
            "next_step_reason": "This checkpoint explains the subsequent screening or validation choice.",
            "evidence": [
                {
                    "evidence_id": "EV15_01",
                    "source_file": f"docs/{doc}/combined.md",
                    "section": "Process checkpoint",
                    "quote_or_span": quote,
                }
            ],
        }
        insert_at = min(max(len(case.get("evolution_trajectory") or []) - 1, 1), len(case.get("evolution_trajectory") or []))
        for idx, existing in enumerate(case.get("evolution_trajectory") or []):
            if idx == 0 and existing.get("action_type") == "literature_reasoning":
                continue
            existing_text = normalize(step_text(existing))
            if any(k in existing_text for k in pattern.get("after_keywords", [])):
                insert_at = idx + 1
                break
        case.setdefault("evolution_trajectory", []).insert(insert_at, new_step)
        added += 1
        traj_norm += " " + normalize(quote)
        note(case, f"v15_process_checkpoint_added={pattern['name']}")
    if added:
        reindex_steps(case)
    return added


def reindex_steps(case: dict[str, Any]) -> None:
    for idx, step in enumerate(case.get("evolution_trajectory") or [], start=1):
        step["step_index"] = idx


def apply_v15_enhancements(case: dict[str, Any], mineru_root: Path) -> dict[str, int]:
    doc = doc_no(case)
    path = mineru_root / "docs" / doc / "combined.md"
    stats = {"problem_quotes": 0, "numeric_quotes": 0, "process_steps": 0}
    if not path.exists():
        note(case, "v15_missing_full_text_for_enhancement")
        return stats
    full_text = path.read_text(encoding="utf-8", errors="replace")
    spans = split_spans(full_text)
    stats["problem_quotes"] = strengthen_problem_framing(case, full_text, spans)
    stats["numeric_quotes"] = improve_numeric_grounding(case, full_text, spans)
    stats["process_steps"] = insert_process_checkpoints(case, spans)
    return stats


def write_pack(pack_dir: Path, cases: list[dict[str, Any]], *, label: str, stats: dict[str, Any]) -> None:
    if pack_dir.exists():
        shutil.rmtree(pack_dir)
    pack_dir.mkdir(parents=True)
    write_dataset_jsonl(pack_dir / "dataset.jsonl", cases)
    (pack_dir / "samples_10.json").write_text(json.dumps(cases[:10], ensure_ascii=False, indent=2), encoding="utf-8")
    summary = {
        "label": label,
        "case_count": len(cases),
        "v15_stats": stats,
    }
    (pack_dir / "v15_patch_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (pack_dir / "README.md").write_text(
        f"""# Sci-Evo V15 Candidate Pack

{label}

This pack keeps the V14 targeted repairs and adds scalable V15 production-side improvements derived from local full-paper evaluation:

- stronger first-step research-problem framing;
- automatic evidence expansion for numeric and mutation claims;
- conservative insertion of process checkpoints such as failed attempts, negative selection, platform validation, and in-silico top-prediction testing when exact paper quotes are present.
""",
        encoding="utf-8",
    )


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Build V15 Top50/Core16 candidate packs from V14 plus scalable enhancements.")
    parser.add_argument("--input-dataset", default=r"outputs\submission_top50\dataset.jsonl")
    parser.add_argument("--mineru-root", default=r"D:\mineru_flat_results_20260521_200done")
    parser.add_argument("--top50-dir", default=r"outputs\submission_top50_v15_framework_repaired")
    parser.add_argument("--core16-dir", default=r"outputs\submission_v15_core16_framework_repaired")
    args = parser.parse_args()

    cases = v14.read_jsonl(Path(args.input_dataset))
    mineru_root = Path(args.mineru_root)
    total_stats = {"problem_quotes": 0, "numeric_quotes": 0, "process_steps": 0}
    per_doc = {}
    for case in cases:
        d = doc_no(case)
        if d in v14.PATCHERS:
            v14.PATCHERS[d](case)
            note(case, "v14_targeted_repair_applied")
        stats = apply_v15_enhancements(case, mineru_root)
        per_doc[d] = stats
        for key, value in stats.items():
            total_stats[key] += value
        note(case, "v15_framework_enhancement_applied")

    total_stats["per_doc"] = per_doc
    write_pack(Path(args.top50_dir), cases, label="Top50 V15 framework candidate set", stats=total_stats)
    core16 = [case for case in cases if doc_no(case) in CORE16_DOCS]
    core16.sort(key=lambda c: c.get("case_id", ""))
    write_pack(Path(args.core16_dir), core16, label="Core16 V15 validation subset", stats=total_stats)
    print(json.dumps({"top50_count": len(cases), "core16_count": len(core16), "v15_stats": total_stats}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

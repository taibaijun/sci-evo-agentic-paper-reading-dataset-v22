"""Code-side arbitration helpers for quality-first reviews."""

from __future__ import annotations

import re
from typing import Any


def evidence_audit_to_review(case_audit: dict[str, Any]) -> dict[str, Any] | None:
    bad_count = int(case_audit.get("bad_evidence_count") or 0)
    total = int(case_audit.get("evidence_count") or 0)
    if total <= 0:
        return None
    ratio = bad_count / max(total, 1)
    warning_counts = case_audit.get("warning_counts")
    if isinstance(warning_counts, str):
        import json

        try:
            warning_counts = json.loads(warning_counts)
        except Exception:
            warning_counts = {}
    if not isinstance(warning_counts, dict):
        warning_counts = {}

    blockers = []
    repairs = []
    if bad_count:
        for warning, count in sorted(warning_counts.items()):
            severity = "high" if warning in {"image_path", "raw_html_table_fragment"} else "medium"
            blockers.append(
                {
                    "type": "bad_evidence",
                    "severity": severity,
                    "affected_steps": [
                        int(item.get("step_index") or 0)
                        for item in case_audit.get("bad_evidence", [])
                        if item.get("warning") == warning
                    ],
                    "paper_basis": "",
                    "problem": f"{count} evidence span(s) failed code hygiene with warning={warning}.",
                    "code_fix_hint": "Replace invalid quote_or_span with clean prose or normalized parsed table evidence.",
                }
            )
        repairs.append(
            {
                "priority": "high" if any(k in warning_counts for k in ("image_path", "raw_html_table_fragment")) else "medium",
                "target": "evidence",
                "description": "Repair or replace bad evidence spans found by deterministic code audit.",
                "code_fix_hint": "Use evidence_index.is_bad_quote before accepting auto evidence expansion.",
            }
        )

    score = round(max(0.0, 1.0 - ratio), 3)
    return {
        "reviewer_role": "evidence_auditor",
        "doc_no": str(case_audit.get("doc_no", "")),
        "case_id": str(case_audit.get("case_id", "")),
        "verdict": "repair" if bad_count else "pass",
        "confidence": 1.0,
        "dimension_scores": {
            "paper_storyline_fidelity": 0.8,
            "mainline_completeness": 0.8,
            "step_factuality": 0.8,
            "evidence_grounding": score,
            "trajectory_coherence": 0.8,
            "sci_evo_value": 0.8,
        },
        "blockers": blockers,
        "repairs": repairs,
        "summary": f"Code evidence audit: {bad_count}/{total} bad evidence spans.",
    }


def load_evidence_audit_map(data: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not data:
        return {}
    out = {}
    for item in data.get("cases") or []:
        if isinstance(item, dict) and item.get("doc_no"):
            out[str(item["doc_no"]).zfill(4)] = item
    return out


def structure_audit_to_review(case_audit: dict[str, Any]) -> dict[str, Any] | None:
    issue_count = int(case_audit.get("issue_count") or 0)
    if issue_count <= 0 and case_audit.get("decision") != "repair":
        return None
    blockers = []
    repairs = []
    for issue in case_audit.get("issues") or []:
        if not isinstance(issue, dict):
            continue
        severity = issue.get("severity") if issue.get("severity") in {"medium", "high"} else "medium"
        blockers.append(
            {
                "type": issue.get("type", "structure_issue"),
                "severity": severity,
                "affected_steps": issue.get("affected_steps") if isinstance(issue.get("affected_steps"), list) else [],
                "paper_basis": "",
                "problem": issue.get("problem", ""),
                "code_fix_hint": issue.get("code_fix_hint", ""),
            }
        )
    if issue_count:
        repairs.append(
            {
                "priority": "medium",
                "target": "schema",
                "description": "Repair deterministic structure/text hygiene issues.",
                "code_fix_hint": "Apply structure_audit gates before accepting candidate cases.",
            }
        )
    score = round(max(0.0, 1.0 - min(issue_count, 8) * 0.08), 3)
    return {
        "reviewer_role": "trajectory_judge",
        "doc_no": str(case_audit.get("doc_no", "")),
        "case_id": str(case_audit.get("case_id", "")),
        "verdict": "repair" if issue_count else "pass",
        "confidence": 1.0,
        "dimension_scores": {
            "paper_storyline_fidelity": 0.8,
            "mainline_completeness": 0.8,
            "step_factuality": score,
            "evidence_grounding": 0.8,
            "trajectory_coherence": score,
            "sci_evo_value": 0.8,
        },
        "blockers": blockers,
        "repairs": repairs,
        "summary": f"Code structure audit: {issue_count} issue(s).",
    }


def load_structure_audit_map(data: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not data:
        return {}
    out = {}
    for item in data.get("cases") or []:
        if isinstance(item, dict) and item.get("doc_no"):
            out[str(item["doc_no"]).zfill(4)] = item
    return out


def _warning_steps(warnings: list[str], needle: str = "") -> list[int]:
    steps: set[int] = set()
    for warning in warnings:
        if needle and needle not in warning:
            continue
        match = re.search(r"\bstep\s+(\d+)\b", warning)
        if match:
            steps.add(int(match.group(1)))
    return sorted(steps)


def _phase_backtrack_count(warnings: list[str]) -> int:
    for warning in warnings:
        match = re.search(r"phase_backtrack_count=(\d+)", warning)
        if match:
            return int(match.group(1))
    return 0


def rule_audit_to_review(case_audit: dict[str, Any]) -> dict[str, Any] | None:
    """Convert deterministic rule-audit warnings into a quality-gate review.

    Evidence hygiene alone cannot prove that a candidate captures the paper's
    storyline. This adapter makes risk signals visible to arbitration so a
    code-only pass does not hide short or weakly grounded trajectories.
    """

    if not case_audit:
        return None
    warnings = [str(item) for item in (case_audit.get("warnings") or []) if item is not None]
    errors = [str(item) for item in (case_audit.get("errors") or []) if item is not None]
    rule_decision = str(case_audit.get("rule_decision") or "pass")
    try:
        step_count = int(case_audit.get("step_count") or 0)
    except Exception:
        step_count = 0
    try:
        warning_count = int(case_audit.get("warning_count") or len(warnings))
    except Exception:
        warning_count = len(warnings)
    try:
        high_warning_count = int(case_audit.get("high_warning_count") or 0)
    except Exception:
        high_warning_count = 0

    numeric_full = [w for w in warnings if "numeric tokens not found in full paper" in w]
    numeric_evidence = [w for w in warnings if "numeric tokens not in this step evidence quote" in w]
    review_article = any(w == "review_article_not_primary_research" for w in warnings)
    low_scievo_source = any(w == "source_low_scievo_suitability" for w in warnings)
    short_trajectory = any(w.startswith("short_trajectory") for w in warnings) or (0 < step_count < 5)
    reused_evidence = [w for w in warnings if "evidence_quote_reused_3plus" in w]
    phase_backtracks = _phase_backtrack_count(warnings)

    blockers = []
    repairs = []
    scores = {
        "paper_storyline_fidelity": 0.86,
        "mainline_completeness": 0.86,
        "step_factuality": 0.86,
        "evidence_grounding": 0.86,
        "trajectory_coherence": 0.86,
        "sci_evo_value": 0.86,
    }

    if errors or rule_decision == "fail":
        blockers.append(
            {
                "type": "rule_error",
                "severity": "high",
                "affected_steps": _warning_steps(errors),
                "paper_basis": "",
                "problem": f"Deterministic rule audit failed: {'; '.join(errors[:4])}",
                "code_fix_hint": "Do not arbitrate failed rule-audit cases as pass; repair schema, evidence, and entity grounding first.",
            }
        )
        repairs.append(
            {
                "priority": "high",
                "target": "generation",
                "description": "Repair hard rule-audit failures before any AI arbitration.",
                "code_fix_hint": "Feed rule audit failures into the repair loop as blocking constraints.",
            }
        )
        scores.update({"step_factuality": 0.5, "evidence_grounding": 0.5, "trajectory_coherence": 0.55})

    if rule_decision == "review" or high_warning_count:
        severity = "high" if high_warning_count >= 2 else "medium"
        blockers.append(
            {
                "type": "rule_review_required",
                "severity": severity,
                "affected_steps": _warning_steps(warnings),
                "paper_basis": "",
                "problem": f"Rule audit requested review with high_warning_count={high_warning_count}.",
                "code_fix_hint": "Route this case to AI/local paper review instead of treating code hygiene as sufficient.",
            }
        )
        repairs.append(
            {
                "priority": "high" if severity == "high" else "medium",
                "target": "selection",
                "description": "Escalate rule-review cases to reviewer packets.",
                "code_fix_hint": "Use the rule-audit risk flags to choose DeepSeek/subagent review cases.",
            }
        )
        scores["paper_storyline_fidelity"] = min(scores["paper_storyline_fidelity"], 0.7)

    if review_article:
        blockers.append(
            {
                "type": "review_article_not_primary_research",
                "severity": "high",
                "affected_steps": [],
                "paper_basis": "",
                "problem": "The source paper is marked as a Review/Perspective rather than a primary experimental Sci-Evo article.",
                "code_fix_hint": "Exclude review articles during selection unless a separate review-summary dataset type is explicitly allowed.",
            }
        )
        repairs.append(
            {
                "priority": "high",
                "target": "selection",
                "description": "Drop or down-rank review articles before generation.",
                "code_fix_hint": "Add source-type filtering over MinerU headers and title metadata before selecting candidate papers.",
            }
        )
        scores["paper_storyline_fidelity"] = min(scores["paper_storyline_fidelity"], 0.45)
        scores["mainline_completeness"] = min(scores["mainline_completeness"], 0.45)
        scores["sci_evo_value"] = min(scores["sci_evo_value"], 0.5)

    if low_scievo_source:
        blockers.append(
            {
                "type": "source_low_scievo_suitability",
                "severity": "high",
                "affected_steps": [],
                "paper_basis": "",
                "problem": "The source title suggests a software, benchmark, drug-repurposing, or virtual-screening paper rather than a concrete scientific evolution/engineering trajectory.",
                "code_fix_hint": "Exclude low-suitability source types unless AI review confirms a real design-build-test-learn or optimization trajectory.",
            }
        )
        repairs.append(
            {
                "priority": "high",
                "target": "selection",
                "description": "Drop or separately review low Sci-Evo suitability sources.",
                "code_fix_hint": "Use title/source-type filters before final selection and route borderline papers to AI review.",
            }
        )
        scores["paper_storyline_fidelity"] = min(scores["paper_storyline_fidelity"], 0.55)
        scores["mainline_completeness"] = min(scores["mainline_completeness"], 0.55)
        scores["sci_evo_value"] = min(scores["sci_evo_value"], 0.45)

    if short_trajectory:
        severity = "high" if step_count <= 3 else "medium"
        blockers.append(
            {
                "type": "short_trajectory",
                "severity": severity,
                "affected_steps": [],
                "paper_basis": "",
                "problem": f"Candidate has only {step_count} trajectory step(s), which is too compressed for a Sci-Evo paper trajectory.",
                "code_fix_hint": "Force reconstruction of the full problem-design-screen-observe-select-validate storyline instead of accepting terse repaired output.",
            }
        )
        repairs.append(
            {
                "priority": "high",
                "target": "generation",
                "description": "Rebuild the trajectory from paper sections, not by evidence backfill only.",
                "code_fix_hint": "Add a storyline extraction stage that proposes required events before JSON step generation.",
            }
        )
        scores["paper_storyline_fidelity"] = min(scores["paper_storyline_fidelity"], 0.6)
        scores["mainline_completeness"] = min(scores["mainline_completeness"], 0.55 if severity == "high" else 0.68)
        scores["trajectory_coherence"] = min(scores["trajectory_coherence"], 0.64)

    if numeric_full:
        severity = "high" if len(numeric_full) >= 4 else "medium"
        blockers.append(
            {
                "type": "wrong_or_unverified_number",
                "severity": severity,
                "affected_steps": _warning_steps(numeric_full),
                "paper_basis": "",
                "problem": f"{len(numeric_full)} numeric warning(s) could not be verified in the full paper after normalization.",
                "code_fix_hint": "Before accepting numeric claims, retrieve table/prose spans by number and either cite exact support or remove/normalize the number.",
            }
        )
        repairs.append(
            {
                "priority": "high" if severity == "high" else "medium",
                "target": "evidence",
                "description": "Repair unverified numeric claims against the full paper.",
                "code_fix_hint": "Add numeric-aware table/prose retrieval and reject claims whose values cannot be recovered.",
            }
        )
        scores["step_factuality"] = min(scores["step_factuality"], 0.56 if severity == "high" else 0.66)
        scores["evidence_grounding"] = min(scores["evidence_grounding"], 0.58 if severity == "high" else 0.68)

    if numeric_evidence:
        severity = "high" if len(numeric_evidence) >= 8 else "medium"
        if len(numeric_evidence) >= 5:
            blockers.append(
                {
                    "type": "weak_numeric_evidence",
                    "severity": severity,
                    "affected_steps": _warning_steps(numeric_evidence),
                    "paper_basis": "",
                    "problem": f"{len(numeric_evidence)} step-level numeric warning(s) show numbers are not grounded in their own evidence spans.",
                    "code_fix_hint": "Run number-by-number evidence binding after span backfill; do not allow unrelated global evidence to justify a step claim.",
                }
            )
            repairs.append(
                {
                    "priority": "high" if severity == "high" else "medium",
                    "target": "evidence",
                    "description": "Bind each important numeric value to same-step evidence.",
                    "code_fix_hint": "Require same-step evidence quotes to contain or normalize to the claimed numbers.",
                }
            )
            scores["evidence_grounding"] = min(scores["evidence_grounding"], 0.6 if severity == "high" else 0.68)
            scores["step_factuality"] = min(scores["step_factuality"], 0.66)

    if warning_count >= 6:
        blockers.append(
            {
                "type": "warning_concentration",
                "severity": "medium",
                "affected_steps": _warning_steps(warnings),
                "paper_basis": "",
                "problem": f"Rule audit produced {warning_count} warning(s), enough to require local review before pass.",
                "code_fix_hint": "Treat concentrated warnings as a review trigger even when each individual warning is soft.",
            }
        )
        repairs.append(
            {
                "priority": "medium",
                "target": "selection",
                "description": "Route concentrated-warning cases to AI/subagent review.",
                "code_fix_hint": "Select cases by warning density for quality packets instead of random sampling only.",
            }
        )
        scores["paper_storyline_fidelity"] = min(scores["paper_storyline_fidelity"], 0.76)
        scores["evidence_grounding"] = min(scores["evidence_grounding"], 0.7)

    if phase_backtracks >= 1:
        blockers.append(
            {
                "type": "possible_wrong_order",
                "severity": "medium",
                "affected_steps": [],
                "paper_basis": "",
                "problem": f"Trajectory phase order backtracked {phase_backtracks} time(s), suggesting ordering or phase-label drift.",
                "code_fix_hint": "Repair phases with timeline-aware ordering, or explicitly justify non-linear branches.",
            }
        )
        repairs.append(
            {
                "priority": "medium",
                "target": "ordering",
                "description": "Review and repair phase order.",
                "code_fix_hint": "Use paper section anchors and temporal markers before final phase labels are assigned.",
            }
        )
        scores["trajectory_coherence"] = min(scores["trajectory_coherence"], 0.68 if phase_backtracks >= 2 else 0.72)

    if reused_evidence:
        blockers.append(
            {
                "type": "reused_evidence",
                "severity": "medium",
                "affected_steps": _warning_steps(reused_evidence),
                "paper_basis": "",
                "problem": f"{len(reused_evidence)} warning(s) indicate repeated evidence supporting too many steps.",
                "code_fix_hint": "Diversify step evidence by retrieving event-specific spans instead of global abstract/result snippets.",
            }
        )
        repairs.append(
            {
                "priority": "medium",
                "target": "evidence",
                "description": "Replace reused evidence with event-specific support.",
                "code_fix_hint": "Penalize repeated evidence spans during backfill and retrieval.",
            }
        )
        scores["evidence_grounding"] = min(scores["evidence_grounding"], 0.68)

    if not blockers and rule_decision == "pass":
        return None

    verdict = "fail" if errors or rule_decision == "fail" else "repair"
    return {
        "reviewer_role": "trajectory_judge",
        "doc_no": str(case_audit.get("doc_no", "")),
        "case_id": str(case_audit.get("case_id", "")),
        "verdict": verdict,
        "confidence": 1.0,
        "dimension_scores": {key: round(value, 3) for key, value in scores.items()},
        "blockers": blockers,
        "repairs": repairs,
        "summary": (
            "Code rule audit risk: "
            f"errors={len(errors)}, warnings={warning_count}, numeric_full={len(numeric_full)}, "
            f"numeric_evidence={len(numeric_evidence)}, phase_backtracks={phase_backtracks}."
        ),
    }


def load_rule_audit_map(data: Any | None) -> dict[str, dict[str, Any]]:
    if not data:
        return {}
    items = data.get("cases") if isinstance(data, dict) else data
    out: dict[str, dict[str, Any]] = {}
    for item in items or []:
        if isinstance(item, dict) and item.get("doc_no"):
            out[str(item["doc_no"]).zfill(4)] = item
    return out


def collect_fix_tags(reviews: list[dict[str, Any]]) -> list[str]:
    tags = set()
    for review in reviews:
        for blocker in review.get("blockers", []):
            btype = str(blocker.get("type", ""))
            if btype:
                tags.add(f"blocker:{btype}")
            hint = (blocker.get("code_fix_hint") or "").lower()
            if "timeline" in hint or "anchor" in hint or "order" in hint:
                tags.add("fix:timeline_aware_ordering")
            if "evidence" in hint or "quote" in hint:
                tags.add("fix:evidence_hygiene")
            if "table" in hint:
                tags.add("fix:table_parsing")
            if "platform" in hint or "method" in hint:
                tags.add("fix:platform_method_template")
            if "phase" in hint or "brace" in hint or "hygiene" in hint:
                tags.add("fix:structure_hygiene")
            if "number" in hint or "numeric" in hint:
                tags.add("fix:numeric_evidence_binding")
            if "storyline" in hint or "reconstruct" in hint:
                tags.add("fix:storyline_reconstruction")
        for repair in review.get("repairs", []):
            target = str(repair.get("target", ""))
            if target:
                tags.add(f"repair:{target}")
    return sorted(tags)

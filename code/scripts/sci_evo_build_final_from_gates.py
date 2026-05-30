from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


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


def strict_json_dumps(obj: Any, *, sort_keys: bool = False, indent: int | None = None) -> str:
    """Emit ASCII-only strict JSON that old PowerShell parsers also accept."""

    text = json.dumps(obj, ensure_ascii=True, allow_nan=False, sort_keys=sort_keys, indent=indent)
    # Windows PowerShell 5's ConvertFrom-Json can mis-handle LaTeX-like
    # escaped backslashes before non-JSON escape characters. Encoding the
    # backslash itself as a Unicode escape preserves the parsed value while
    # avoiding sequences such as "\\*" or "\\%".
    return text.replace("\\\\", "\\u005c")


def write_strict_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(strict_json_dumps(row, sort_keys=True) + "\n")


def load_gate_pass_docs(path: Path) -> set[str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    passed: set[str] = set()
    for item in data.get("cases") or []:
        if not isinstance(item, dict):
            continue
        gate = item.get("gate") or {}
        if gate.get("decision") == "pass":
            passed.add(str(item.get("doc_no", "")).zfill(4))
    return passed


def parse_source(value: str) -> tuple[str, Path, Path | None]:
    parts = value.split("|")
    if len(parts) not in {2, 3}:
        raise argparse.ArgumentTypeError("source must be label|dataset.jsonl or label|dataset.jsonl|gate.json")
    label = parts[0].strip()
    dataset = Path(parts[1].strip())
    gate = Path(parts[2].strip()) if len(parts) == 3 and parts[2].strip() else None
    if not label:
        raise argparse.ArgumentTypeError("source label cannot be empty")
    if not dataset.exists():
        raise argparse.ArgumentTypeError(f"dataset does not exist: {dataset}")
    if gate and not gate.exists():
        raise argparse.ArgumentTypeError(f"gate json does not exist: {gate}")
    return label, dataset, gate


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Build final Sci-Evo dataset from gate-passed source batches.")
    parser.add_argument(
        "--source",
        action="append",
        required=True,
        help="Repeatable: label|dataset.jsonl|quality_arbitration_with_rule_risk.json. If gate is omitted, all dataset cases are accepted.",
    )
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--sample-count", type=int, default=20)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    sources = [parse_source(item) for item in args.source]
    out = Path(args.output_dir)
    if out.exists() and args.overwrite:
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)

    selected: dict[str, dict[str, Any]] = {}
    selected_source: dict[str, str] = {}
    source_summaries: list[dict[str, Any]] = []
    for label, dataset_path, gate_path in sources:
        cases = read_jsonl(dataset_path)
        pass_docs = load_gate_pass_docs(gate_path) if gate_path else {doc_no(c) for c in cases}
        accepted = 0
        duplicates = 0
        for case in cases:
            d = doc_no(case)
            if d not in pass_docs:
                continue
            if d in selected:
                duplicates += 1
                continue
            selected[d] = case
            selected_source[d] = label
            accepted += 1
        source_summaries.append(
            {
                "label": label,
                "dataset": str(dataset_path),
                "gate": str(gate_path) if gate_path else "",
                "dataset_cases": len(cases),
                "gate_pass_cases": len(pass_docs),
                "accepted_new_cases": accepted,
                "duplicate_pass_cases_skipped": duplicates,
            }
        )

    ordered_docs = sorted(selected)
    final_cases = [selected[d] for d in ordered_docs]
    write_strict_jsonl(out / "dataset.jsonl", final_cases)
    (out / "samples.json").write_text(
        strict_json_dumps(final_cases[: args.sample_count], indent=2),
        encoding="utf-8",
    )
    summary = {
        "case_count": len(final_cases),
        "doc_nos": ordered_docs,
        "sources": source_summaries,
        "selected_source": selected_source,
    }
    (out / "selection_summary.json").write_text(
        strict_json_dumps(summary, indent=2),
        encoding="utf-8",
    )
    print(strict_json_dumps({k: v for k, v in summary.items() if k != "selected_source"}, indent=2))


if __name__ == "__main__":
    main()

"""Corpus indexing, scoring, and evidence-context construction."""

from __future__ import annotations

import csv
import json
import math
import re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable


HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)

DOMAIN_KEYWORDS = {
    "directed evolution": 9,
    "protein engineering": 8,
    "enzyme engineering": 8,
    "active learning": 7,
    "bayesian optimization": 7,
    "mutagenesis": 7,
    "variant": 4,
    "library": 4,
    "screening": 5,
    "high-throughput": 5,
    "biosensor": 4,
    "metabolic engineering": 4,
    "protein design": 6,
    "de novo": 5,
    "alphafold": 5,
    "rosetta": 5,
    "proteinmpnn": 5,
}

TRAJECTORY_KEYWORDS = {
    "round": 5,
    "iteration": 6,
    "iterative": 6,
    "selected": 4,
    "identified": 3,
    "optimized": 4,
    "improved": 4,
    "failed": 7,
    "failure": 7,
    "however": 3,
    "therefore": 3,
    "next": 3,
    "subsequent": 3,
    "validation": 4,
    "assay": 4,
    "activity": 4,
    "fitness": 5,
    "enrichment": 5,
    "variant": 4,
}

METRIC_KEYWORDS = {
    "fold": 3,
    "kcat": 5,
    "km": 4,
    "ic50": 4,
    "tm": 4,
    "yield": 4,
    "titer": 4,
    "conversion": 4,
    "selectivity": 4,
    "activity": 3,
    "fluorescence": 3,
    "luminescence": 3,
    "auc": 3,
    "rmsd": 3,
    "plddt": 4,
}

SECTION_HINTS = (
    "abstract",
    "introduction",
    "background",
    "results",
    "discussion",
    "methods",
    "materials",
    "conclusion",
    "figure",
    "table",
)


@dataclass
class DocumentRecord:
    doc_no: str
    doc_id: str
    title: str
    doi: str
    license: str
    pdf_name: str
    combined_md: str
    mineru_md: str
    text_chars: int
    heading_count: int
    relevance_score: float
    signal_counts: dict[str, int]


def read_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def write_jsonl(path: Path, rows: Iterable[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def load_raw_inventory(path: Path | None) -> dict[str, dict[str, str]]:
    if not path or not path.exists():
        return {}
    out: dict[str, dict[str, str]] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            seq = (row.get("seq") or "").strip()
            if seq:
                out[f"{int(seq):04d}"] = row
    return out


def clean_title_from_markdown(text: str) -> str:
    for match in HEADING_RE.finditer(text[:5000]):
        title = match.group(2).strip()
        low = title.lower()
        if low.startswith("combined mineru") or low.startswith("pdf pages"):
            continue
        if low in {"research", "open access", "article", "review"}:
            continue
        return re.sub(r"\s+", " ", title)
    return ""


def count_keywords(text_lc: str, weighted_keywords: dict[str, int]) -> tuple[int, int]:
    raw_count = 0
    weighted = 0
    for kw, weight in weighted_keywords.items():
        count = text_lc.count(kw)
        raw_count += count
        weighted += min(count, 12) * weight
    return raw_count, weighted


def score_document(text: str, title: str) -> tuple[float, dict[str, int]]:
    text_lc = (title + "\n" + text[:80000]).lower()
    domain_raw, domain_weighted = count_keywords(text_lc, DOMAIN_KEYWORDS)
    traj_raw, traj_weighted = count_keywords(text_lc, TRAJECTORY_KEYWORDS)
    metric_raw, metric_weighted = count_keywords(text_lc, METRIC_KEYWORDS)

    heading_hits = sum(
        1
        for m in HEADING_RE.finditer(text)
        if any(h in m.group(2).lower() for h in SECTION_HINTS)
    )
    length_bonus = min(math.log(max(len(text), 1), 10) * 2.0, 12.0)
    score = domain_weighted * 0.55 + traj_weighted * 0.35 + metric_weighted * 0.20
    score += min(heading_hits, 20) * 1.5 + length_bonus
    signals = {
        "domain_hits": domain_raw,
        "trajectory_hits": traj_raw,
        "metric_hits": metric_raw,
        "useful_headings": heading_hits,
    }
    return round(score, 3), signals


def build_index(input_root: Path, raw_inventory: Path | None = None) -> list[DocumentRecord]:
    manifest = read_jsonl(input_root / "manifest.jsonl")
    inventory = load_raw_inventory(raw_inventory)
    records: list[DocumentRecord] = []

    for row in manifest:
        doc_no = str(row["doc_no"]).zfill(4)
        md_rel = row.get("combined_md") or f"docs/{doc_no}/combined.md"
        md_path = input_root / md_rel
        text = md_path.read_text(encoding="utf-8", errors="replace")
        inv = inventory.get(doc_no, {})
        title = (inv.get("title") or "").strip().strip('"') or clean_title_from_markdown(text)
        doi = (inv.get("doi") or "").strip()
        license_name = (inv.get("license") or "").strip()
        heading_count = len(list(HEADING_RE.finditer(text)))
        score, signals = score_document(text, title)
        records.append(
            DocumentRecord(
                doc_no=doc_no,
                doc_id=row.get("doc_id") or "",
                title=title,
                doi=doi,
                license=license_name,
                pdf_name=row.get("pdf_name") or inv.get("file") or "",
                combined_md=md_rel,
                mineru_md=row.get("mineru_md") or f"docs/{doc_no}/mineru.md",
                text_chars=len(text),
                heading_count=heading_count,
                relevance_score=score,
                signal_counts=signals,
            )
        )
    records.sort(key=lambda r: r.relevance_score, reverse=True)
    return records


def records_to_dicts(records: Iterable[DocumentRecord]) -> list[dict]:
    return [asdict(r) for r in records]


def split_sections(text: str) -> list[dict]:
    matches = list(HEADING_RE.finditer(text))
    if not matches:
        return [{"heading": "full_text", "level": 0, "start": 0, "end": len(text), "text": text}]
    sections: list[dict] = []
    for i, match in enumerate(matches):
        start = match.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        sections.append(
            {
                "heading": match.group(2).strip(),
                "level": len(match.group(1)),
                "start": start,
                "end": end,
                "text": text[start:end].strip(),
            }
        )
    return sections


def _chunk_text(section: dict, chunk_chars: int = 2600, overlap: int = 350) -> list[dict]:
    text = section["text"]
    chunks: list[dict] = []
    if len(text) <= chunk_chars:
        item = dict(section)
        item["chunk_start"] = section["start"]
        item["chunk_end"] = section["end"]
        chunks.append(item)
        return chunks
    offset = 0
    while offset < len(text):
        piece = text[offset : offset + chunk_chars]
        item = {
            "heading": section["heading"],
            "level": section["level"],
            "start": section["start"],
            "end": section["end"],
            "chunk_start": section["start"] + offset,
            "chunk_end": section["start"] + offset + len(piece),
            "text": piece.strip(),
        }
        chunks.append(item)
        if offset + chunk_chars >= len(text):
            break
        offset += chunk_chars - overlap
    return chunks


def build_evidence_context(
    *,
    input_root: Path,
    record: dict,
    max_chars: int = 30000,
) -> dict:
    md_path = input_root / record["combined_md"]
    text = md_path.read_text(encoding="utf-8", errors="replace")
    sections = split_sections(text)
    all_chunks: list[dict] = []
    for section in sections:
        all_chunks.extend(_chunk_text(section))

    title_lc = (record.get("title") or "").lower()
    scored: list[tuple[float, int, dict]] = []
    for idx, chunk in enumerate(all_chunks):
        blob = (chunk["heading"] + "\n" + chunk["text"]).lower()
        _, domain_score = count_keywords(blob, DOMAIN_KEYWORDS)
        _, traj_score = count_keywords(blob, TRAJECTORY_KEYWORDS)
        _, metric_score = count_keywords(blob, METRIC_KEYWORDS)
        heading = chunk["heading"].lower()
        section_bonus = 0
        if any(h in heading for h in SECTION_HINTS):
            section_bonus += 25
        if "abstract" in heading:
            section_bonus += 45
        if "result" in heading:
            section_bonus += 35
        if "method" in heading or "material" in heading:
            section_bonus += 25
        if any(kw in title_lc for kw in ("directed evolution", "screening", "optimization")):
            section_bonus += 5
        score = section_bonus + domain_score * 0.6 + traj_score * 0.7 + metric_score * 0.4
        scored.append((score, idx, chunk))

    selected: list[dict] = []
    used = 0
    seen_ranges: set[tuple[int, int]] = set()

    def add_chunk(chunk: dict) -> bool:
        nonlocal used
        key = (chunk["chunk_start"], chunk["chunk_end"])
        if key in seen_ranges:
            return False
        text_piece = re.sub(r"\n{3,}", "\n\n", chunk["text"]).strip()
        if not text_piece:
            return False
        extra = len(text_piece)
        if used + extra > max_chars and selected:
            return False
        seen_ranges.add(key)
        selected.append(
            {
                "evidence_id": f"E{len(selected) + 1:02d}",
                "source_file": record["combined_md"],
                "section": chunk["heading"],
                "char_start": chunk["chunk_start"],
                "char_end": chunk["chunk_end"],
                "text": text_piece[:3600],
            }
        )
        used += extra
        return True

    for chunk in all_chunks[:3]:
        add_chunk(chunk)
    for _, _, chunk in sorted(scored, key=lambda x: x[0], reverse=True):
        if used >= max_chars:
            break
        add_chunk(chunk)

    return {
        "doc_no": record["doc_no"],
        "source": {
            "title": record.get("title", ""),
            "doi": record.get("doi", ""),
            "license": record.get("license", ""),
            "pdf_name": record.get("pdf_name", ""),
            "combined_md": record.get("combined_md", ""),
            "mineru_md": record.get("mineru_md", ""),
        },
        "ranking": {
            "relevance_score": record.get("relevance_score"),
            "signal_counts": record.get("signal_counts"),
            "text_chars": record.get("text_chars"),
        },
        "evidence_snippets": selected,
    }


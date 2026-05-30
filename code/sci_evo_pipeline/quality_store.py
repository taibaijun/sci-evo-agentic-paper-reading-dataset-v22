"""Append-only storage helpers for quality-first experiments."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .quality_schema import SCHEMA_VERSION, as_jsonable


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class QualityRunStore:
    def __init__(self, root: Path | str):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def write_json(self, rel_path: str | Path, data: Any) -> Path:
        path = self.root / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = as_jsonable(data)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def append_jsonl(self, rel_path: str | Path, data: Any) -> Path:
        path = self.root / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(as_jsonable(data), ensure_ascii=False) + "\n")
        return path

    def init_manifest(self, *, run_id: str, source_dataset: str, notes: str = "") -> Path:
        return self.write_json(
            "manifest.json",
            {
                "schema_version": SCHEMA_VERSION,
                "run_id": run_id,
                "created_at": now_iso(),
                "source_dataset": source_dataset,
                "notes": notes,
            },
        )

    def doc_dir(self, doc_no: str) -> Path:
        path = self.root / "docs" / str(doc_no).zfill(4)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def write_doc_json(self, doc_no: str, rel_path: str | Path, data: Any) -> Path:
        doc_path = Path("docs") / str(doc_no).zfill(4) / rel_path
        return self.write_json(doc_path, data)

    def write_review(self, doc_no: str, candidate_id: str, role: str, data: Any) -> Path:
        return self.write_doc_json(doc_no, Path("reviews") / candidate_id / f"{role}.json", data)

    def write_arbitration(self, doc_no: str, candidate_id: str, data: Any) -> Path:
        return self.write_doc_json(doc_no, Path("arbitration") / f"{candidate_id}.json", data)

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class EvidenceRecord:
    # First field so it leads every serialised line, which makes the log
    # readable by eye. Required, never defaulted: a default would let
    # distinct runs silently share an id and merge downstream.
    run_id: str
    skill: str
    backend: str
    model: str
    input_summary: str
    output: str
    duration_ms: int
    status: str  # "ok" | "failed" | "unavailable"
    timestamp: str  # ISO 8601
    error: str | None = None


def append_evidence(record: EvidenceRecord, runs_dir: str | Path = "runs") -> Path:
    runs_path = Path(runs_dir)
    runs_path.mkdir(parents=True, exist_ok=True)

    date_part = record.timestamp[:10]
    out_file = runs_path / f"{date_part}.jsonl"

    with out_file.open("a") as f:
        f.write(json.dumps(asdict(record)) + "\n")

    return out_file

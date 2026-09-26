from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path


# The scheme under which a Sylvae run names itself to other systems. A run's
# cross-system identity is ``sylvae:run/<run_id>``; when a coordinator records a
# Sylvae run as evidence elsewhere (e.g. as a WeftMark evidence producer id), it
# uses this namespaced form so the run stays resolvable back here. Keep the
# scheme stable -- consumers match on the ``sylvae:`` prefix.
RUNTIME_SCHEME = "sylvae"


def validate_run_id(value: str) -> str:
    """Return a canonical Sylvae run id or reject an invalid external id."""
    try:
        parsed = uuid.UUID(value)
    except (AttributeError, ValueError) as exc:
        raise ValueError("run id must be 32 lowercase hexadecimal characters") from exc
    if value != parsed.hex or parsed.version != 4:
        raise ValueError("run id must be 32 lowercase hexadecimal characters")
    return value


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

    @property
    def runtime_ref(self) -> str:
        """This run's stable cross-system identity, ``sylvae:run/<run_id>``.

        It is a derived property, not a field, so it never enters the JSONL
        evidence log (``asdict`` serialises fields only) and the on-disk record
        stays byte-stable. Callers that hand a run's identity to another system
        should use this rather than re-formatting ``run_id`` by hand.
        """
        return f"{RUNTIME_SCHEME}:run/{self.run_id}"


def append_evidence(record: EvidenceRecord, runs_dir: str | Path = "runs") -> Path:
    runs_path = Path(runs_dir)
    runs_path.mkdir(parents=True, exist_ok=True)

    date_part = record.timestamp[:10]
    out_file = runs_path / f"{date_part}.jsonl"

    with out_file.open("a") as f:
        f.write(json.dumps(asdict(record)) + "\n")

    return out_file

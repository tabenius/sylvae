"""Optional Minotaur snapshot projection and human Nostoi workflow commands."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path


def load_runtime_status(path=None, *, now=None):
    path = path or os.environ.get("RAGBAZ_RUNTIME_STATUS")
    base = {"schema": "ragbaz.runtime-status.v1", "status": "not-configured",
            "summary": ["Runtime status not configured (set RAGBAZ_RUNTIME_STATUS to Minotaur's snapshot).",
                        "Native evidence and human review remain available without Ephor."]}
    if not path:
        return base
    try:
        with Path(path).expanduser().open("rb") as stream:
            raw = stream.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            raise ValueError("oversized snapshot")
        data = json.loads(raw)
        if not isinstance(data, dict) or data.get("schema") != base["schema"]:
            raise ValueError("unknown schema")
        timestamp = datetime.fromisoformat(data["observed_at"].replace("Z", "+00:00"))
        lines = data.get("summary")
        if timestamp.tzinfo is None or not isinstance(data.get("components"), dict):
            raise ValueError("invalid observation")
        if not isinstance(lines, list) or len(lines) > 1024 or not all(isinstance(s, str) for s in lines):
            raise ValueError("invalid summary")
        age = ((now or datetime.now(timezone.utc)) - timestamp).total_seconds()
        status = "current" if 0 <= age <= 120 else "stale" if age > 120 else "clock-skew"
        lines = ["".join(c if c.isprintable() else " " for c in s) for s in lines]
        return {**data, "status": status, "age_seconds": age,
                "summary": [f"Runtime snapshot: {status} (observations, not authority)"] + lines}
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return {**base, "status": "unavailable", "summary": [
            "Runtime snapshot unavailable or invalid; optional services are unknown."]}


def workflow_commands(runs_dir):
    chain = str(Path(os.environ.get("SYLVAE_NOSTOI_LEDGER", str(Path(runs_dir) / "nostoi.jsonl"))).expanduser())
    return {"chain": chain, "chain_exists": Path(chain).is_file(),
            "verify": ["nostoi", "verify", chain, "--format", "nostoi-v1", "--json"],
            "attest": ["nostoi", "attest", chain, "--principal", "YOU@HOST", "--key", "KEY"],
            "verify_attestation": ["nostoi", "verify-attestation", chain, "--principal", "YOU@HOST",
                                   "--allowed-signers", "SIGNERS", "--fingerprint", "SHA256:PIN"],
            "signature": "unchecked", "human_step": True,
            "note": "Attest a verified audit chain, not daily run JSONL. A signature is not test evidence or independent review."}

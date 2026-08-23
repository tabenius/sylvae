from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from sylvae.backends.anthropic_backend import AnthropicBackend
from sylvae.backends.base import Backend
from sylvae.backends.ollama_backend import OllamaBackend
from sylvae.backends.shellout_backend import ShelloutBackend
from sylvae.evidence import EvidenceRecord, append_evidence
from sylvae.loader import Skill, load_skill

BACKENDS: dict[str, type[Backend]] = {
    "anthropic": AnthropicBackend,
    "ollama": OllamaBackend,
    "shellout": ShelloutBackend,
}


def resolve_input(raw: str) -> str:
    path = Path(raw)
    if path.is_file():
        return path.read_text()
    return raw


def build_prompt(skill: Skill, resolved_input: str) -> str:
    return f"{skill.instructions}\n\n---\n\nTask input:\n{resolved_input}"


def run_skill(
    skill_path: str | Path,
    backend_name: str,
    raw_input: str,
    runs_dir: str | Path = "runs",
) -> EvidenceRecord:
    if backend_name not in BACKENDS:
        raise ValueError(f"unknown backend: {backend_name!r} (known: {sorted(BACKENDS)})")

    skill = load_skill(skill_path)
    resolved_input = resolve_input(raw_input)
    prompt = build_prompt(skill, resolved_input)

    backend = BACKENDS[backend_name]()
    result = backend.run(prompt, skill)

    record = EvidenceRecord(
        skill=skill.slug,
        backend=backend_name,
        model=result.model,
        input_summary=resolved_input[:200],
        output=result.output,
        duration_ms=result.duration_ms,
        status=result.status,
        timestamp=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    )
    append_evidence(record, runs_dir=runs_dir)
    return record

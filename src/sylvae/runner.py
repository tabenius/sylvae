from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from sylvae.backends.anthropic_backend import AnthropicBackend
from sylvae.backends.base import Backend
from sylvae.backends.claudecode_backend import ClaudeCodeBackend
from sylvae.backends.ollama_backend import OllamaBackend
from sylvae.backends.opencode_backend import OpenCodeBackend
from sylvae.backends.shellout_backend import ShelloutBackend
from sylvae.evidence import EvidenceRecord, append_evidence
from sylvae.loader import Skill, load_skill

BACKENDS: dict[str, type[Backend]] = {
    "anthropic": AnthropicBackend,
    "claudecode": ClaudeCodeBackend,
    "ollama": OllamaBackend,
    "shellout": ShelloutBackend,
    "opencode": OpenCodeBackend,
}


def resolve_input(raw: str) -> str:
    path = Path(raw)
    if path.is_file():
        return path.read_text()
    return raw


def build_prompt(skill: Skill, resolved_input: str) -> str:
    return f"{skill.instructions}\n\n---\n\nTask input:\n{resolved_input}"


def resolve_backend(skill: Skill, requested_backend: str) -> str:
    """Map "auto" to a concrete backend using the skill's declared tier.

    A skill with no declared tier defaults to "frontier" (the safe
    choice) rather than silently getting downgraded to a cheap backend
    nobody vetted it against. Any explicit (non-"auto") choice passes
    through unchanged.
    """
    if requested_backend != "auto":
        return requested_backend
    if skill.tier == "cheap":
        return "ollama"
    return "anthropic"


def run_skill(
    skill_path: str | Path,
    backend_name: str,
    raw_input: str,
    runs_dir: str | Path = "runs",
    model: str | None = None,
) -> EvidenceRecord:
    if backend_name != "auto" and backend_name not in BACKENDS:
        raise ValueError(f"unknown backend: {backend_name!r} (known: {sorted(BACKENDS)} + 'auto')")

    skill = load_skill(skill_path)
    resolved_backend_name = resolve_backend(skill, backend_name)
    if resolved_backend_name not in BACKENDS:
        raise ValueError(f"unknown backend: {resolved_backend_name!r} (known: {sorted(BACKENDS)})")

    resolved_input = resolve_input(raw_input)
    prompt = build_prompt(skill, resolved_input)

    backend = BACKENDS[resolved_backend_name]()
    run_kwargs = {"model": model} if model else {}
    result = backend.run(prompt, skill, **run_kwargs)

    record = EvidenceRecord(
        skill=skill.slug,
        backend=resolved_backend_name,
        model=result.model,
        input_summary=resolved_input[:200],
        output=result.output,
        duration_ms=result.duration_ms,
        status=result.status,
        timestamp=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        error=result.error,
    )
    append_evidence(record, runs_dir=runs_dir)
    return record

from __future__ import annotations

import os
import uuid

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


# Which concrete backend each tier routes to under `--backend auto`.
#
# "frontier" deliberately does NOT point at the Anthropic API backend. That
# was the original mapping and it made `--backend auto` fail outright for
# every skill not marked tier: cheap, because this machine has no Anthropic
# API key and cannot obtain one -- an API key being a separate paid product
# from a Claude subscription.
#
# It points at OpenCode instead, chosen for a specific reason: unlike
# claudecode, OpenCode draws on its own account rather than the operator's
# interactive Claude budget. Automatic routing should not quietly spend the
# scarcest resource its owner has.
#
# Overridable per tier via SYLVAE_BACKEND_<TIER>, because hardcoding this is
# precisely what produced the original bug and the right target genuinely
# differs per operator.
DEFAULT_TIER_BACKENDS: dict[str, str] = {
    "cheap": "ollama",
    "frontier": "opencode",
    # Codex: a real agent harness with tools, on its own account. Kept
    # distinct from the frontier target on purpose -- if the two collapsed
    # to one backend the tier would carry no information and the vocabulary
    # would be lying about what it expresses.
    "agent": "shellout",
}

# Skills with no declared tier fall here: the safe choice, not the cheap
# one. An author who has not thought about the tradeoff should not get
# silently downgraded output.
FALLBACK_TIER = "frontier"


def tier_backends() -> dict[str, str]:
    """Resolve the tier map, applying SYLVAE_BACKEND_<TIER> overrides.

    Validates every target against BACKENDS, so a typo surfaces as a clear
    error at routing time rather than as a confusing failure inside a
    backend that does not exist.
    """
    resolved = dict(DEFAULT_TIER_BACKENDS)
    for tier in resolved:
        override = os.environ.get(f"SYLVAE_BACKEND_{tier.upper()}")
        if override:
            resolved[tier] = override
    for tier, backend in resolved.items():
        if backend not in BACKENDS:
            raise ValueError(
                f"tier {tier!r} is mapped to unknown backend {backend!r} "
                f"(known: {', '.join(sorted(BACKENDS))})"
            )
    return resolved


def resolve_backend(skill: Skill, requested_backend: str) -> str:
    """Map "auto" to a concrete backend using the skill's declared tier.

    Any explicit (non-"auto") choice passes through unchanged -- a human
    naming a backend is never overridden.
    """
    if requested_backend != "auto":
        return requested_backend
    mapping = tier_backends()
    return mapping.get(skill.tier or FALLBACK_TIER, mapping[FALLBACK_TIER])


def run_skill(
    skill_path: str | Path,
    backend_name: str,
    raw_input: str,
    runs_dir: str | Path = "runs",
    model: str | None = None,
    timeout: float | None = None,
) -> EvidenceRecord:
    if backend_name != "auto" and backend_name not in BACKENDS:
        raise ValueError(f"unknown backend: {backend_name!r} (known: {sorted(BACKENDS)} + 'auto')")

    skill = load_skill(skill_path)
    resolved_backend_name = resolve_backend(skill, backend_name)
    if resolved_backend_name not in BACKENDS:
        raise ValueError(f"unknown backend: {resolved_backend_name!r} (known: {sorted(BACKENDS)})")

    resolved_input = resolve_input(raw_input)
    prompt = build_prompt(skill, resolved_input)

    # Every backend accepts a timeout; passing it here is what actually
    # bounds the call. Callers that leave it None get the backend default.
    backend_kwargs = {} if timeout is None else {"timeout": timeout}
    backend = BACKENDS[resolved_backend_name](**backend_kwargs)
    run_kwargs = {"model": model} if model else {}
    result = backend.run(prompt, skill, **run_kwargs)

    record = EvidenceRecord(
        run_id=uuid.uuid4().hex,
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

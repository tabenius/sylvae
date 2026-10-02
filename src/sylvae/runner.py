from __future__ import annotations

import os
import hashlib
import importlib.util
import threading
import time
import uuid

from datetime import datetime, timezone
from pathlib import Path

from sylvae.backends.anthropic_backend import AnthropicBackend
from sylvae.backends.base import Backend
from sylvae.backends.claudecode_backend import ClaudeCodeBackend
from sylvae.backends.ollama_backend import OllamaBackend
from sylvae.backends.opencode_backend import OpenCodeBackend
from sylvae.backends.shellout_backend import ShelloutBackend
from sylvae.evidence import EvidenceRecord, append_evidence, validate_run_id
from sylvae.loader import Skill, load_skill

BACKENDS: dict[str, type[Backend]] = {
    "anthropic": AnthropicBackend,
    "claudecode": ClaudeCodeBackend,
    "ollama": OllamaBackend,
    "shellout": ShelloutBackend,
    "opencode": OpenCodeBackend,
}

MAX_RUN_INPUT_CHARS = 100_000
MAX_RUNS_PER_MINUTE = 60
_run_admission_lock = threading.Lock()
_run_admissions: list[float] = []
_run_limit_recorded_minute: int | None = None
_nostoi_module = None


class RunRateLimited(RuntimeError):
    """Provider call refused because the local run budget is full."""


def _admit_run(runs_dir: str | Path) -> None:
    global _run_limit_recorded_minute
    now = time.monotonic()
    minute = int(time.time() // 60)
    with _run_admission_lock:
        while _run_admissions and now - _run_admissions[0] >= 60:
            _run_admissions.pop(0)
        if len(_run_admissions) >= MAX_RUNS_PER_MINUTE:
            if _run_limit_recorded_minute != minute:
                _append_nostoi(
                    runs_dir, kind="skill.run.rate_limited", actor=_run_actor(),
                    subject=f"minute:{minute}", body={"limit": MAX_RUNS_PER_MINUTE},
                )
                _run_limit_recorded_minute = minute
            raise RunRateLimited("Sylvae run limit reached; try again after the current minute")
        _run_admissions.append(now)


def _run_actor() -> str:
    actor = os.environ.get("SYLVAE_AGENT", "local")[:128]
    return actor or "local"


def _nostoi():
    global _nostoi_module
    if _nostoi_module is not None:
        return _nostoi_module
    configured = os.environ.get("SYLVAE_NOSTOI_PYTHON")
    candidates = [Path(configured).expanduser()] if configured else []
    candidates.extend((
        Path(__file__).with_name("nostoi_reference.py"),
        Path(__file__).resolve().parents[3] / "nostoi" / "contrib" / "python" / "nostoi.py",
        Path(os.environ.get("RAGBAZ_SRC_ROOT", Path(__file__).resolve().parents[3]))
        / "nostoi" / "contrib" / "python" / "nostoi.py",
    ))
    source = next((path.resolve() for path in candidates if path.is_file()), None)
    if source is None:
        raise RuntimeError(
            "Nostoi's Python reference is unavailable; set SYLVAE_NOSTOI_PYTHON"
        )
    spec = importlib.util.spec_from_file_location("sylvae_nostoi_reference", source)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load Nostoi reference from {source}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _nostoi_module = module
    return module


def _append_nostoi(
    runs_dir: str | Path, *, kind: str, actor: str, subject: str, body: dict
) -> dict:
    ledger = Path(os.environ.get("SYLVAE_NOSTOI_LEDGER", Path(runs_dir) / "nostoi.jsonl"))
    ledger.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    return _nostoi().append(
        ledger, kind=kind, actor=actor, subject=subject,
        at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"), body=body,
    )


def resolve_input(raw: str) -> str:
    path = Path(raw)
    if path.is_file():
        if path.stat().st_size > MAX_RUN_INPUT_CHARS:
            raise ValueError(f"input exceeds the {MAX_RUN_INPUT_CHARS}-character run limit")
        return path.read_text()
    if len(raw) > MAX_RUN_INPUT_CHARS:
        raise ValueError(f"input exceeds the {MAX_RUN_INPUT_CHARS}-character run limit")
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
    run_id: str | None = None,
) -> EvidenceRecord:
    if backend_name != "auto" and backend_name not in BACKENDS:
        raise ValueError(f"unknown backend: {backend_name!r} (known: {sorted(BACKENDS)} + 'auto')")
    resolved_run_id = uuid.uuid4().hex if run_id is None else validate_run_id(run_id)

    skill = load_skill(skill_path)
    resolved_backend_name = resolve_backend(skill, backend_name)
    if resolved_backend_name not in BACKENDS:
        raise ValueError(f"unknown backend: {resolved_backend_name!r} (known: {sorted(BACKENDS)})")

    resolved_input = resolve_input(raw_input)
    prompt = build_prompt(skill, resolved_input)

    _admit_run(runs_dir)
    actor = _run_actor()
    intent = _append_nostoi(
        runs_dir,
        kind="skill.run.requested",
        actor=actor,
        subject=resolved_run_id,
        body={
            "skill": skill.slug,
            "backend": resolved_backend_name,
            "model": model or "",
            "input": resolved_input,
            "input_sha256": hashlib.sha256(resolved_input.encode("utf-8")).hexdigest(),
            "input_chars": len(resolved_input),
            "timeout_seconds": str(timeout) if timeout is not None else "backend-default",
        },
    )

    # Every backend accepts a timeout; passing it here is what actually
    # bounds the call. Callers that leave it None get the backend default.
    backend_kwargs = {} if timeout is None else {"timeout": timeout}
    try:
        backend = BACKENDS[resolved_backend_name](**backend_kwargs)
        run_kwargs = {"model": model} if model else {}
        result = backend.run(prompt, skill, **run_kwargs)
    except Exception as error:
        _append_nostoi(
            runs_dir, kind="skill.run.failed", actor=actor,
            subject=resolved_run_id,
            body={"intent_digest": intent["digest"], "error_type": type(error).__name__},
        )
        raise

    _append_nostoi(
        runs_dir, kind="skill.run.completed", actor=actor,
        subject=resolved_run_id,
        body={
            "intent_digest": intent["digest"],
            "status": result.status,
            "model": result.model,
            "duration_ms": result.duration_ms,
            "output_sha256": hashlib.sha256(result.output.encode("utf-8")).hexdigest(),
            "output_chars": len(result.output),
            "error_type": type(result.error).__name__ if result.error else "",
        },
    )

    record = EvidenceRecord(
        run_id=resolved_run_id,
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

from __future__ import annotations

import subprocess
import time
from typing import Callable

from sylvae.backends.base import BackendResult, InvalidModelName, elapsed_ms, validate_model_name


def guard_model(model: str | None) -> str | None:
    """Validate an optional model id, or raise InvalidModelName.

    Applied by every CLI-spawning backend before argv is assembled, so a
    flag-shaped value never reaches a downstream argument parser.
    """
    if model is None:
        return None
    return validate_model_name(model)


def run_subprocess_backend(
    cmd: list[str],
    *,
    command_name: str,
    model: str,
    timeout: float,
    extract_output: Callable[[subprocess.CompletedProcess], str],
) -> BackendResult:
    """Shared subprocess-invocation and error-mapping for CLI-harness
    backends (Codex, OpenCode, ...). Each backend builds its own argv and
    output-extraction logic — the mechanics of running it, timing it, and
    classifying what went wrong are identical across harnesses, so they
    live here once rather than duplicated per backend.
    """
    start = time.monotonic()
    try:
        result = subprocess.run(
            cmd, stdin=subprocess.DEVNULL, capture_output=True,
            text=True, timeout=timeout,
        )
    except FileNotFoundError:
        return BackendResult(
            output="", model=model, duration_ms=elapsed_ms(start),
            status="unavailable", error=f"{command_name!r} not found on PATH",
        )
    except subprocess.TimeoutExpired:
        return BackendResult(
            output="", model=model, duration_ms=elapsed_ms(start),
            status="unavailable", error=f"{command_name} timed out after {timeout}s",
        )

    if result.returncode != 0:
        stderr_tail = (result.stderr or "").strip()[-500:]
        return BackendResult(
            output="", model=model, duration_ms=elapsed_ms(start),
            status="failed", error=f"{command_name} exited {result.returncode}: {stderr_tail}",
        )

    output = extract_output(result)
    return BackendResult(output=output, model=model, duration_ms=elapsed_ms(start), status="ok")

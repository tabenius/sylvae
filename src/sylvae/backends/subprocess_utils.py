from __future__ import annotations

import subprocess
import time
from typing import Callable

from sylvae.backends.base import BackendResult, elapsed_ms


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

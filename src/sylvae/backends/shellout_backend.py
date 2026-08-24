from __future__ import annotations

import subprocess
import tempfile
import time
from pathlib import Path

from sylvae.backends.base import BackendResult, elapsed_ms
from sylvae.loader import Skill


class ShelloutBackend:
    """Runs a CLI-only harness (currently: Codex) as a subprocess.

    Uses `codex exec -o <file>` — non-interactive, and `-o` captures just
    the agent's final message with no banner/log noise to parse. Sandboxed
    read-only: these skills are pure text-in/text-out, so Codex never
    needs write access to run one.
    """

    name = "shellout"

    def __init__(self, command: str = "codex", timeout: float = 180.0):
        self.command = command
        self.timeout = timeout

    def run(self, prompt: str, skill: Skill, **kwargs: str) -> BackendResult:
        start = time.monotonic()
        model = kwargs.get("model")

        with tempfile.TemporaryDirectory() as tmp_dir:
            output_path = Path(tmp_dir) / "output.txt"
            cmd = [
                self.command, "exec",
                "--sandbox", "read-only",
                "--skip-git-repo-check",
                "-o", str(output_path),
            ]
            if model:
                cmd += ["-m", model]
            cmd.append(prompt)

            try:
                result = subprocess.run(
                    cmd, stdin=subprocess.DEVNULL, capture_output=True,
                    text=True, timeout=self.timeout,
                )
            except FileNotFoundError:
                return BackendResult(
                    output="", model=self.command, duration_ms=elapsed_ms(start),
                    status="unavailable", error=f"{self.command!r} not found on PATH",
                )
            except subprocess.TimeoutExpired:
                return BackendResult(
                    output="", model=self.command, duration_ms=elapsed_ms(start),
                    status="unavailable", error=f"{self.command} exec timed out after {self.timeout}s",
                )

            if result.returncode != 0:
                stderr_tail = (result.stderr or "").strip()[-500:]
                return BackendResult(
                    output="", model=self.command, duration_ms=elapsed_ms(start),
                    status="failed",
                    error=f"{self.command} exited {result.returncode}: {stderr_tail}",
                )

            output = output_path.read_text().strip() if output_path.exists() else ""

        return BackendResult(output=output, model=self.command, duration_ms=elapsed_ms(start), status="ok")

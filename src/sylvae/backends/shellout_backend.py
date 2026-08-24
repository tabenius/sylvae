from __future__ import annotations

import tempfile
from pathlib import Path

from sylvae.backends.base import BackendResult, InvalidModelName
from sylvae.backends.subprocess_utils import guard_model, run_subprocess_backend
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
        try:
            model = guard_model(kwargs.get("model"))
        except InvalidModelName as exc:
            return BackendResult(
                output="", model=str(kwargs.get("model")), duration_ms=0,
                status="failed", error=str(exc),
            )

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

            return run_subprocess_backend(
                cmd, command_name=self.command, model=self.command, timeout=self.timeout,
                extract_output=lambda _completed: (
                    output_path.read_text().strip() if output_path.exists() else ""
                ),
            )

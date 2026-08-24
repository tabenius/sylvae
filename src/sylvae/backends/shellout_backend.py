from __future__ import annotations

from sylvae.backends.base import BackendResult
from sylvae.loader import Skill


class ShelloutBackend:
    """Runs a CLI-only harness (Codex, OpenCode) as a subprocess.

    Not implemented in phase 1 — see the open question in the phase-1
    spec. The interface is wired up now so the runner and CLI don't need
    changes when a real implementation lands.
    """

    name = "shellout"

    def __init__(self, command: str = "codex"):
        self.command = command

    def run(self, prompt: str, skill: Skill, **kwargs: object) -> BackendResult:
        return BackendResult(
            output="",
            model=self.command,
            duration_ms=0,
            status="unavailable",
            error="shellout backend not implemented in phase 1",
        )

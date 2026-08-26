from __future__ import annotations

import json

from sylvae.backends.base import DEFAULT_BACKEND_TIMEOUT, BackendResult, InvalidModelName
from sylvae.backends.subprocess_utils import guard_model, run_subprocess_backend
from sylvae.loader import Skill


def _extract_text(stdout: str) -> str:
    """Pull the assistant's text out of `opencode run --format json`'s
    JSONL event stream. Each `type: "text"` event's `part.text` is one
    chunk of the reply; join them in order. Anything else (step markers,
    tool calls, non-JSON noise) is ignored.
    """
    texts = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "text":
            text = event.get("part", {}).get("text")
            if text:
                texts.append(text)
    return "\n".join(texts).strip()


class OpenCodeBackend:
    """Runs OpenCode's own model catalog (OpenCode Zen — gpt-5.x, kimi,
    glm, big-pickle, and many more) as a subprocess, via `opencode run`.

    Uses --format json rather than the default formatted/ANSI-colored
    text output, since the JSON event stream is the only reliable way to
    isolate the final reply from banners and step markers.
    """

    name = "opencode"

    def __init__(self, command: str = "opencode", model: str = "opencode/big-pickle", timeout: float = DEFAULT_BACKEND_TIMEOUT):
        self.command = command
        self.model = model
        self.timeout = timeout

    def run(self, prompt: str, skill: Skill, **kwargs: str) -> BackendResult:
        try:
            model = guard_model(kwargs.get("model", self.model))
        except InvalidModelName as exc:
            return BackendResult(
                output="", model=str(kwargs.get("model")), duration_ms=0,
                status="failed", error=str(exc),
            )
        cmd = [self.command, "run", "--model", model, "--format", "json", prompt]

        return run_subprocess_backend(
            cmd, command_name=self.command, model=model, timeout=self.timeout,
            extract_output=lambda completed: _extract_text(completed.stdout),
        )

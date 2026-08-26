from __future__ import annotations

import json
import time

from sylvae.backends.base import DEFAULT_BACKEND_TIMEOUT, BackendResult, InvalidModelName, elapsed_ms
from sylvae.backends.subprocess_utils import guard_model, run_subprocess_backend
from sylvae.loader import Skill

# The three flags below are load-bearing for cost, not style.
#
# Measured on konsonans, claude 2.1.238, identical trivial prompt:
#   default `claude -p --output-format json`      28,424 tokens   $0.1706
#   + --setting-sources "" --strict-mcp-config     3,146 tokens   $0.0267
#
# The default invocation loads every installed plugin, skill, agent and
# slash command before answering — ~25k tokens of bootstrap that Sylvae
# has no use for, since a skill run is pure text in / text out. Dropping
# the setting sources drops all of that while auth survives (it lives
# outside settings), verified by the call still succeeding.
#
# Two things that DON'T help, both measured, so nobody re-derives them:
#   --bare            skips plugins but also skips the settings carrying
#                     auth -> "Not logged in · Please run /login"
#   --system-prompt   replacing the default prompt pushed usage back UP
#                     to 16,574 tokens / $0.1005
_MINIMAL_FLAGS = ["--output-format", "json", "--setting-sources", "", "--strict-mcp-config"]


class _Unavailable(Exception):
    """Raised during output parsing when the CLI reports it could not run
    (rate limit exhausted, not logged in). Distinct from a bad answer."""


def _extract_result(stdout: str) -> str:
    """Pull the assistant's text out of `claude -p --output-format json`.

    The CLI emits a JSON array of events; the final element carries the
    `result` field plus `is_error`. Rate-limit and auth failures arrive
    as a successful process exit with a diagnostic payload, so they have
    to be detected here rather than from the exit code.
    """
    data = json.loads(stdout)
    events = data if isinstance(data, list) else [data]
    final = events[-1]

    for event in events:
        if event.get("type") == "rate_limit_event":
            status = event.get("rate_limit_info", {}).get("status")
            if status and status != "allowed":
                limit_type = event.get("rate_limit_info", {}).get("rateLimitType", "unknown")
                raise _Unavailable(f"Claude Code rate limit hit ({limit_type}, status={status})")

    text = (final.get("result") or "").strip()

    # Auth failure exits 0 and returns its complaint as the result text.
    if "not logged in" in text.lower():
        raise _Unavailable(f"Claude Code is not logged in: {text}")

    if final.get("is_error"):
        raise ValueError(f"Claude Code reported an error: {text}")

    return text


class ClaudeCodeBackend:
    """Runs the local Claude Code CLI headlessly.

    Authenticates via the operator's existing Claude subscription rather
    than an ANTHROPIC_API_KEY (`apiKeySource: none` in the CLI's own
    output), which is the point: it provides real Claude access on a
    machine where no API key exists.

    Cost caveat worth knowing before routing to it: unlike Codex and
    OpenCode, which draw on separate accounts, this shares the operator's
    interactive five-hour budget. A run here is spending the same
    allowance its owner uses to work.
    """

    name = "claudecode"

    def __init__(self, command: str = "claude", timeout: float = DEFAULT_BACKEND_TIMEOUT):
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
        cmd = [self.command, "-p", *_MINIMAL_FLAGS]
        if model:
            cmd += ["--model", model]
        cmd.append(prompt)

        reported_model = model or self.command
        start = time.monotonic()
        try:
            return run_subprocess_backend(
                cmd, command_name=self.command, model=reported_model, timeout=self.timeout,
                extract_output=lambda completed: _extract_result(completed.stdout),
            )
        except _Unavailable as exc:
            return BackendResult(
                output="", model=reported_model, duration_ms=elapsed_ms(start),
                status="unavailable", error=str(exc),
            )
        except (json.JSONDecodeError, ValueError, KeyError, IndexError) as exc:
            return BackendResult(
                output="", model=reported_model, duration_ms=elapsed_ms(start),
                status="failed", error=f"could not parse {self.command} output: {exc}",
            )

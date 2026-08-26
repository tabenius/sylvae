"""Provider-neutral facade for the optional MCP server.

This module intentionally contains no MCP SDK imports, so it can be tested
as an ordinary adapter and so the core package keeps working when the SDK
is not installed. ``sylvae.mcp.server`` maps these operations onto the
protocol.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sylvae.loader import SkillLoadError, load_skill, resolve_skill_dir
from sylvae.review import list_skills as discover_skills
from sylvae.runner import BACKENDS, run_skill

# When an agent calls Sylvae, the entire point is to move work somewhere
# cheaper than the agent itself. Landing on a peer-priced backend achieves
# nothing: it costs the same or more than doing the work inline, while
# still returning a correct-looking answer. So the default is the cheapest
# thing available rather than whatever the skill's tier would pick.
DEFAULT_MCP_BACKEND = "ollama"

# Backends that spawn an agent harness which could itself call back into
# Sylvae. A Claude Code session invoking sylvae_run_skill, routed to the
# claudecode backend, spawns another Claude Code -- which can call Sylvae
# again. Nothing downstream breaks that cycle, and it drains the operator's
# shared five-hour budget quickly and silently.
RECURSION_RISK_BACKENDS = frozenset({"claudecode"})

# "auto" is refused for the same reason: tier-based routing can select a
# recursion-risk backend, so allowing it would reopen the hole this guard
# closes. An MCP caller must name a concrete backend or accept the default.
_AUTO = "auto"

# An MCP client cannot sit through a 76-second Ollama call without the user
# assuming it hung, so this path is stricter than the CLI's 180s.
DEFAULT_MCP_TIMEOUT = 90.0

# An unbounded prompt is unbounded cost, and this surface is driven by a
# model rather than a person: the text it passes may itself have come from
# somewhere untrusted. 100k characters is far above any real skill input
# here (the largest so far is a few KB of diff) and far below anything that
# would run up a surprising bill.
MAX_INPUT_CHARS = 100_000


class McpToolService:
    """Sylvae operations exposed to MCP callers, with cost and recursion
    guards applied before anything is executed."""

    def __init__(
        self,
        skills_dir: str | Path = "skills",
        runs_dir: str | Path = "runs",
        default_backend: str = DEFAULT_MCP_BACKEND,
        allow_recursive_backends: bool = False,
        timeout: float = DEFAULT_MCP_TIMEOUT,
    ):
        self.skills_dir = Path(skills_dir)
        self.runs_dir = Path(runs_dir)
        self.default_backend = default_backend
        # Deliberately a constructor argument, never a per-call one: the human
        # registering the server decides this, not the model calling the tool.
        # A model must not be able to opt itself into spending the operator's
        # interactive quota.
        self.allow_recursive_backends = allow_recursive_backends
        self.timeout = timeout

    def list_skills(self) -> dict[str, Any]:
        skills = discover_skills(self.skills_dir)
        return {
            "ok": True,
            "skills": [
                {"slug": s.slug, "description": s.description, "tier": s.tier}
                for s in skills
            ],
        }

    def run_skill(
        self,
        skill: str,
        input: str,
        backend: str | None = None,
        model: str | None = None,
    ) -> dict[str, Any]:
        if len(input) > MAX_INPUT_CHARS:
            return self._error(
                f"input too large: {len(input)} characters, limit {MAX_INPUT_CHARS}"
            )

        chosen = backend or self.default_backend

        if chosen == _AUTO:
            return self._error(
                "backend 'auto' is not available over MCP: tier routing could select a "
                f"recursion-risk backend ({', '.join(sorted(RECURSION_RISK_BACKENDS))}). "
                "Name a concrete backend instead."
            )

        if chosen in RECURSION_RISK_BACKENDS and not self.allow_recursive_backends:
            return self._error(
                f"backend {chosen!r} is refused over MCP: recursion risk. It spawns an "
                "agent harness that can call Sylvae again, and it spends the operator's "
                "own interactive quota. The operator can enable it when starting the "
                "server; a caller cannot enable it per-call."
            )

        if chosen not in BACKENDS:
            return self._error(
                f"unknown backend {chosen!r} (known: {', '.join(sorted(BACKENDS))})"
            )

        # Path traversal through this parameter was demonstrated before this
        # check existed: a slug of "../../../../../tmp/evil-skill" loaded and
        # ran a SKILL.md planted outside skills_dir. This surface is called by
        # a model, so untrusted text it is processing can reach here.
        try:
            skill_path = resolve_skill_dir(self.skills_dir, skill)
            load_skill(skill_path)
        except SkillLoadError as exc:
            return self._error(f"skill {skill!r} could not be loaded: {exc}")

        try:
            record = run_skill(
                str(skill_path), chosen, input,
                runs_dir=str(self.runs_dir), model=model, timeout=self.timeout,
            )
        except Exception as exc:  # never surface a traceback through a tool call
            return self._error(f"run failed: {type(exc).__name__}: {exc}")

        # "ok" describes the TOOL CALL, not the run. A run that came back
        # unavailable is a successful call reporting a real outcome, and the
        # caller needs to tell those apart to decide what to do next.
        return {
            "ok": True,
            "skill": record.skill,
            "backend": record.backend,
            "model": record.model,
            "status": record.status,
            "output": record.output,
            "duration_ms": record.duration_ms,
            "error_detail": record.error,
        }

    @staticmethod
    def _error(message: str) -> dict[str, Any]:
        return {"ok": False, "error": message}

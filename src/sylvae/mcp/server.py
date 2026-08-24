"""Optional stdio MCP server over Sylvae's tool service.

The MCP SDK is an optional dependency: install with the 'mcp' extra. Core
Sylvae -- the CLI, the runner, the review UI -- works without it, and the
service layer this binds to is testable without it too.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sylvae.mcp.service import DEFAULT_MCP_TIMEOUT, McpToolService


class McpDependencyError(RuntimeError):
    """Raised when the optional MCP SDK is not installed."""


_INSTRUCTIONS = (
    "Sylvae runs SKILL.md-format skills against a chosen model backend and records "
    "each run as durable evidence. Use it to delegate small, well-specified, "
    "text-in/text-out work to a cheaper model than yourself -- summarising, "
    "extracting, reformatting, checking against a stated rule.\n\n"
    "Runs default to a local Ollama model. Expect seconds to a minute; local model "
    "latency is variable. A run may come back with status 'unavailable' (the backend "
    "could not be reached, or a model is not pulled) rather than a result -- that is "
    "a normal outcome, not a tool failure.\n\n"
    "Skills that need tool use, file access or multi-step reasoning are a poor fit: "
    "a Sylvae run is a single text-in/text-out call with no tools."
)


def build_server(service: McpToolService):
    """Build an MCP server over the service, keeping the SDK optional."""
    try:
        from mcp.server import MCPServer
        from mcp.types import ToolAnnotations
    except ModuleNotFoundError as error:
        raise McpDependencyError(
            "MCP support is optional; install Sylvae with the 'mcp' extra "
            '(pip install -e ".[mcp]")'
        ) from error

    server = MCPServer("Sylvae", instructions=_INSTRUCTIONS)

    read_annotations = ToolAnnotations(
        read_only_hint=True,
        idempotent_hint=True,
        open_world_hint=False,
    )
    # Not read-only and not idempotent: a run spends real resources and appends
    # to the evidence log. open_world because it calls out to a model.
    run_annotations = ToolAnnotations(
        read_only_hint=False,
        idempotent_hint=False,
        open_world_hint=True,
    )

    @server.tool(
        name="sylvae_list_skills",
        title="List Sylvae skills",
        annotations=read_annotations,
    )
    def sylvae_list_skills() -> dict[str, Any]:
        """List available skills: slug, what each does, and its cost tier."""
        return service.list_skills()

    @server.tool(
        name="sylvae_run_skill",
        title="Run a Sylvae skill",
        annotations=run_annotations,
    )
    def sylvae_run_skill(
        skill: str,
        input: str,
        backend: str | None = None,
        model: str | None = None,
    ) -> dict[str, Any]:
        """Run one skill against the given input text on a cheaper model.

        skill: slug from sylvae_list_skills. input: the text to work on.
        backend: optional; defaults to a cheap local model. Some backends are
        refused here to prevent recursion and runaway cost.
        model: optional model override for the chosen backend.
        """
        return service.run_skill(skill=skill, input=input, backend=backend, model=model)

    return server


def _protect_stdio() -> None:
    """Keep third-party logging off stdout.

    MCP over stdio uses stdout for the JSON-RPC stream itself, so anything
    else printed there corrupts the protocol. LiteLLM currently logs to
    stderr (verified), which is safe -- but that is a property of its
    default config, not a guarantee, and a stray stdout write would surface
    as an inscrutable protocol error rather than an obvious logging bug.
    Belt and braces, since the cost is two lines.
    """
    import logging

    try:
        import litellm

        litellm.suppress_debug_info = True
    except Exception:  # litellm absent or its API changed; nothing to protect
        pass

    for name in ("LiteLLM", "litellm", "httpx"):
        logging.getLogger(name).setLevel(logging.WARNING)


def serve(
    skills_dir: str | Path = "skills",
    runs_dir: str | Path = "runs",
    allow_recursive_backends: bool = False,
    timeout: float = DEFAULT_MCP_TIMEOUT,
) -> None:
    _protect_stdio()
    service = McpToolService(
        skills_dir=skills_dir,
        runs_dir=runs_dir,
        allow_recursive_backends=allow_recursive_backends,
        timeout=timeout,
    )
    build_server(service).run()

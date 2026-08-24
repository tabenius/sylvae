"""Optional stdio MCP server over Sylvae's tool service.

The MCP SDK is an optional dependency: install with the 'mcp' extra. Core
Sylvae -- the CLI, the runner, the review UI -- works without it, and the
service layer this binds to is testable without it too.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Sequence

from sylvae.mcp.service import DEFAULT_MCP_TIMEOUT, McpToolService

# Dependency loggers quieted while serving over stdio. Each of these can emit
# request or response bodies -- for Sylvae that means skill input and output,
# i.e. arbitrary caller-supplied text. See quiet_dependency_logging() for why
# that matters more under MCP than it does on the CLI.
DEPENDENCY_LOGGERS: tuple[str, ...] = (
    "LiteLLM",    # Ollama path; logs full completion payloads at INFO
    "litellm",    # same library — some versions use the lowercase logger
    "httpx",      # HTTP client beneath litellm/anthropic; logs request URLs
    "httpcore",   # transport beneath httpx; very chatty at DEBUG
    "anthropic",  # Anthropic SDK
    "openai",     # pulled in transitively by litellm
)

# WARNING, not ERROR: genuine problems (retries, deprecations, degraded
# backends) still need to reach the operator's log. The goal is to drop
# payload-bearing INFO/DEBUG chatter, not to go silent.
DEFAULT_DEPENDENCY_LOG_LEVEL: int = logging.WARNING


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


def quiet_dependency_logging(
    level: int = DEFAULT_DEPENDENCY_LOG_LEVEL,
    loggers: Sequence[str] = DEPENDENCY_LOGGERS,
) -> dict[str, int]:
    """Raise dependency logger levels, and report exactly what changed.

    This is NOT what protects the JSON-RPC wire. The SDK already does that,
    and does it properly: while serving, `stdio_server()` dups the real
    descriptors aside and points fd 0 at the null device and fd 1 at stderr,
    restoring both on exit. Verified empirically in
    tests/test_mcp_transport_integrity.py -- a tool doing `print()`,
    `sys.stdout.write()` and even raw `os.write(1, ...)` cannot corrupt the
    response. Nothing at Python level could improve on that.

    What this function is actually for is the consequence of that design.
    Because fd 1 is redirected to stderr, every stray byte a dependency
    emits lands on stderr -- and MCP clients routinely capture stderr to a
    log file. LiteLLM logs completion payloads at INFO, which for Sylvae
    means the skill's INPUT and OUTPUT: arbitrary caller-supplied text that
    may contain a diff with credentials in it, personal data, or anything
    else the caller passed. Quiet-by-default keeps that off disk.

    Returns the previous level of each logger it touched, so the change is
    auditable and reversible rather than an invisible global mutation.
    """
    previous: dict[str, int] = {}
    for name in loggers:
        logger = logging.getLogger(name)
        previous[name] = logger.level
        logger.setLevel(level)
    return previous


def _quiet_litellm_banner() -> bool:
    """Silence LiteLLM's non-logging banner output. Returns whether it applied.

    Separate from logger levels because it is a module attribute, not a
    logger, and it is version-specific -- hence narrow exception handling
    rather than a bare `except Exception`, so a genuine failure here is
    still visible rather than swallowed.
    """
    try:
        import litellm
    except ModuleNotFoundError:
        return False  # litellm not installed; the Ollama path is unavailable anyway

    try:
        litellm.suppress_debug_info = True
    except AttributeError:  # attribute renamed/removed in this version
        return False
    return True


def serve(
    skills_dir: str | Path = "skills",
    runs_dir: str | Path = "runs",
    allow_recursive_backends: bool = False,
    timeout: float = DEFAULT_MCP_TIMEOUT,
    dependency_log_level: int = DEFAULT_DEPENDENCY_LOG_LEVEL,
) -> None:
    quiet_dependency_logging(level=dependency_log_level)
    _quiet_litellm_banner()
    service = McpToolService(
        skills_dir=skills_dir,
        runs_dir=runs_dir,
        allow_recursive_backends=allow_recursive_backends,
        timeout=timeout,
    )
    build_server(service).run()

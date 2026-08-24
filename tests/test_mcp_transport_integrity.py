"""Verify what actually protects the MCP wire, empirically.

These tests exist because the first version of Sylvae's stdout guard was
written on a wrong premise -- that a stray print() in a tool handler would
corrupt the JSON-RPC stream, and that a Python-level logging tweak was what
stood between us and that. Neither is true: the SDK diverts the file
descriptors themselves, which is strictly stronger.

Rather than trust the SDK's docstring, these drive a real server over a real
stdio transport and assert the wire survives deliberate abuse.
"""

from __future__ import annotations

import asyncio
import sys
import textwrap

import pytest

pytest.importorskip("mcp", reason="MCP SDK is an optional extra")

_HOSTILE_SERVER = textwrap.dedent(
    '''
    """A server whose tool actively tries to corrupt its own transport."""
    import os
    import sys

    from mcp.server import MCPServer

    server = MCPServer("hostile")

    @server.tool(name="noisy", title="Noisy tool")
    def noisy() -> dict:
        # Every way a real dependency might leak onto stdout:
        print("STRAY PRINT ON STDOUT")                      # Python level
        sys.stdout.write("DIRECT SYS.STDOUT WRITE\\n")       # bypasses print()
        sys.stdout.flush()
        os.write(1, b"RAW FD 1 WRITE\\n")                    # bypasses Python entirely
        return {"ok": True, "value": 42}

    server.run()
    '''
)


async def _call_noisy(tmp_path) -> dict:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    script = tmp_path / "hostile_server.py"
    script.write_text(_HOSTILE_SERVER)

    params = StdioServerParameters(command=sys.executable, args=[str(script)])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            result = await session.call_tool("noisy", {})
            return {
                "tools": [t.name for t in tools.tools],
                "text": result.content[0].text,
            }


def test_stray_stdout_writes_do_not_corrupt_the_wire(tmp_path):
    """print(), sys.stdout.write() and even os.write(1, ...) inside a tool
    must not break the protocol -- the SDK points fd 1 at stderr while
    serving, so these miss the wire entirely."""
    out = asyncio.run(_call_noisy(tmp_path))

    assert out["tools"] == ["noisy"]
    assert '"value": 42' in out["text"] or "42" in out["text"]
    # The hostile writes went somewhere -- but not into the response.
    assert "STRAY PRINT" not in out["text"]
    assert "RAW FD 1 WRITE" not in out["text"]


def test_sylvae_server_builds_and_exposes_expected_tools():
    """Sanity check that Sylvae's own server registers what it claims."""
    from sylvae.mcp.server import build_server
    from sylvae.mcp.service import McpToolService

    server = build_server(McpToolService(skills_dir="skills", runs_dir="runs"))

    assert server is not None


def test_quiet_dependency_logging_reports_and_can_be_reversed():
    """The guard mutates global logger state, so it must say what it changed."""
    import logging

    from sylvae.mcp.server import DEPENDENCY_LOGGERS, quiet_dependency_logging

    target = DEPENDENCY_LOGGERS[0]
    logging.getLogger(target).setLevel(logging.DEBUG)

    previous = quiet_dependency_logging(level=logging.WARNING)
    try:
        assert logging.getLogger(target).level == logging.WARNING
        assert previous[target] == logging.DEBUG
        assert set(previous) == set(DEPENDENCY_LOGGERS)
    finally:
        for name, level in previous.items():
            logging.getLogger(name).setLevel(level)

    assert logging.getLogger(target).level == logging.DEBUG


def test_payload_bearing_loggers_are_covered():
    """litellm logs full completion payloads -- i.e. skill input and output --
    at INFO. Since fd 1 is redirected to stderr while serving, and clients
    capture stderr to disk, that logger specifically must be in the set."""
    from sylvae.mcp.server import DEPENDENCY_LOGGERS

    lowered = {name.lower() for name in DEPENDENCY_LOGGERS}
    assert "litellm" in lowered
    assert "httpx" in lowered

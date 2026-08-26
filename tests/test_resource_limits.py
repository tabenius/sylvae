"""Resource-exhaustion and availability hardening tests.

Each case corresponds to a gap found by inspection of this codebase:

  * two backends made model calls with no timeout at all, so a hung server
    hung Sylvae indefinitely;
  * the MCP service stored a timeout, documented it as stricter than the
    CLI's, and never passed it to anything;
  * the review server read Content-Length bytes with no cap and no
    validation.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sylvae.backends.base import DEFAULT_BACKEND_TIMEOUT
from sylvae.loader import Skill


def _skill() -> Skill:
    return Skill(slug="s", name="s", description="d", instructions="i", path=Path("."))


# --------------------------------------------------------------------------
# Every backend must bound its call. Previously only the three subprocess
# backends did; the two API backends had no timeout on the model call.
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "module_path, cls_name",
    [
        ("sylvae.backends.ollama_backend", "OllamaBackend"),
        ("sylvae.backends.anthropic_backend", "AnthropicBackend"),
        ("sylvae.backends.shellout_backend", "ShelloutBackend"),
        ("sylvae.backends.opencode_backend", "OpenCodeBackend"),
        ("sylvae.backends.claudecode_backend", "ClaudeCodeBackend"),
    ],
)
def test_every_backend_accepts_a_timeout(module_path, cls_name):
    import importlib

    cls = getattr(importlib.import_module(module_path), cls_name)
    backend = cls(timeout=42.0)

    assert backend.timeout == 42.0


@patch("sylvae.backends.ollama_backend._check_model_availability", return_value=(True, True))
@patch("sylvae.backends.ollama_backend.litellm.completion")
def test_ollama_passes_timeout_to_the_model_call(mock_completion, _probe):
    from sylvae.backends.ollama_backend import OllamaBackend

    mock_completion.return_value = {"choices": [{"message": {"content": "ok"}}]}

    OllamaBackend(timeout=7.0).run("prompt", _skill())

    assert mock_completion.call_args.kwargs["timeout"] == 7.0


@patch("sylvae.backends.anthropic_backend.Anthropic")
def test_anthropic_passes_timeout_to_the_model_call(mock_cls):
    from sylvae.backends.anthropic_backend import AnthropicBackend

    block = MagicMock(type="text", text="ok")
    client = MagicMock()
    client.messages.create.return_value = MagicMock(content=[block])
    mock_cls.return_value = client

    AnthropicBackend(api_key="fake", timeout=7.0).run("prompt", _skill())

    assert client.messages.create.call_args.kwargs["timeout"] == 7.0


# --------------------------------------------------------------------------
# The timeout has to actually travel from caller to backend. It previously
# stopped at McpToolService.__init__ and went no further.
# --------------------------------------------------------------------------

def test_run_skill_forwards_timeout_to_the_backend(tmp_path):
    from sylvae.runner import BACKENDS, run_skill

    skill_dir = tmp_path / "skills" / "s"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: s\ndescription: d\n---\nbody")

    constructed = {}

    def _factory(**kwargs):
        constructed.update(kwargs)
        backend = MagicMock()
        backend.run.return_value = MagicMock(
            output="o", model="m", duration_ms=1, status="ok", error=None
        )
        return backend

    with patch.dict(BACKENDS, {"fake": _factory}):
        run_skill(skill_dir, "fake", "input", runs_dir=tmp_path / "runs", timeout=11.0)

    assert constructed.get("timeout") == 11.0


@patch("sylvae.mcp.service.run_skill")
def test_mcp_service_timeout_reaches_run_skill(mock_run, tmp_path):
    from sylvae.mcp.service import McpToolService

    skill_dir = tmp_path / "skills" / "s"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: s\ndescription: d\n---\nbody")
    mock_run.return_value = MagicMock(
        skill="s", backend="ollama", model="m", status="ok",
        output="o", duration_ms=1, error=None,
    )

    service = McpToolService(
        skills_dir=tmp_path / "skills", runs_dir=tmp_path / "runs", timeout=13.0
    )
    service.run_skill(skill="s", input="hi")

    assert mock_run.call_args.kwargs["timeout"] == 13.0


# --------------------------------------------------------------------------
# Input size. An unbounded prompt is unbounded cost, and the MCP surface is
# driven by a model rather than a person.
# --------------------------------------------------------------------------

def test_mcp_refuses_oversized_input(tmp_path):
    from sylvae.mcp.service import MAX_INPUT_CHARS, McpToolService

    skill_dir = tmp_path / "skills" / "s"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: s\ndescription: d\n---\nbody")
    service = McpToolService(skills_dir=tmp_path / "skills", runs_dir=tmp_path / "runs")

    with patch("sylvae.mcp.service.run_skill") as mock_run:
        out = service.run_skill(skill="s", input="x" * (MAX_INPUT_CHARS + 1))

    assert out["ok"] is False
    assert "too large" in out["error"].lower()
    mock_run.assert_not_called()


def test_mcp_accepts_input_at_the_limit(tmp_path):
    from sylvae.mcp.service import MAX_INPUT_CHARS, McpToolService

    skill_dir = tmp_path / "skills" / "s"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: s\ndescription: d\n---\nbody")
    service = McpToolService(skills_dir=tmp_path / "skills", runs_dir=tmp_path / "runs")

    with patch("sylvae.mcp.service.run_skill") as mock_run:
        mock_run.return_value = MagicMock(
            skill="s", backend="ollama", model="m", status="ok",
            output="o", duration_ms=1, error=None,
        )
        out = service.run_skill(skill="s", input="x" * MAX_INPUT_CHARS)

    assert out["ok"] is True


def test_default_backend_timeout_is_a_real_number():
    assert isinstance(DEFAULT_BACKEND_TIMEOUT, (int, float))
    assert DEFAULT_BACKEND_TIMEOUT > 0

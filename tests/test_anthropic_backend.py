from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
from anthropic import APIConnectionError

from sylvae.backends.anthropic_backend import AnthropicBackend
from sylvae.loader import Skill


def make_skill() -> Skill:
    return Skill(slug="s", name="s", description="d", instructions="do X", path=Path("."))


@patch("sylvae.backends.anthropic_backend.Anthropic")
def test_run_returns_ok_on_success(mock_anthropic_cls):
    mock_block = MagicMock(type="text", text="hello there")
    mock_response = MagicMock(content=[mock_block])
    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_response
    mock_anthropic_cls.return_value = mock_client

    backend = AnthropicBackend(api_key="fake")
    result = backend.run("prompt", make_skill())

    assert result.status == "ok"
    assert result.output == "hello there"
    assert result.model == "claude-sonnet-5"


@patch("sylvae.backends.anthropic_backend.Anthropic")
def test_run_returns_unavailable_on_connection_error(mock_anthropic_cls):
    mock_client = MagicMock()
    mock_client.messages.create.side_effect = APIConnectionError(
        message="boom", request=httpx.Request("POST", "https://api.anthropic.com")
    )
    mock_anthropic_cls.return_value = mock_client

    backend = AnthropicBackend(api_key="fake")
    result = backend.run("prompt", make_skill())

    assert result.status == "unavailable"


@patch("sylvae.backends.anthropic_backend.Anthropic")
def test_run_returns_failed_on_other_errors(mock_anthropic_cls):
    mock_client = MagicMock()
    mock_client.messages.create.side_effect = RuntimeError("something else broke")
    mock_anthropic_cls.return_value = mock_client

    backend = AnthropicBackend(api_key="fake")
    result = backend.run("prompt", make_skill())

    assert result.status == "failed"

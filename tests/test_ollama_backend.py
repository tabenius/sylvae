from pathlib import Path
from unittest.mock import patch

from litellm.exceptions import APIConnectionError

from sylvae.backends.ollama_backend import OllamaBackend
from sylvae.loader import Skill


def make_skill() -> Skill:
    return Skill(slug="s", name="s", description="d", instructions="do X", path=Path("."))


@patch("sylvae.backends.ollama_backend.litellm.completion")
def test_run_returns_ok_on_success(mock_completion):
    mock_completion.return_value = {
        "choices": [{"message": {"content": "the local answer"}}]
    }

    backend = OllamaBackend()
    result = backend.run("prompt", make_skill())

    assert result.status == "ok"
    assert result.output == "the local answer"
    assert result.model == "ollama/qwen2.5:14b"


@patch("sylvae.backends.ollama_backend.litellm.completion")
def test_run_returns_unavailable_when_ollama_unreachable(mock_completion):
    mock_completion.side_effect = APIConnectionError(
        message="connection refused", llm_provider="ollama", model="qwen2.5:14b"
    )

    backend = OllamaBackend()
    result = backend.run("prompt", make_skill())

    assert result.status == "unavailable"


@patch("sylvae.backends.ollama_backend.litellm.completion")
def test_run_returns_failed_on_other_errors(mock_completion):
    mock_completion.side_effect = RuntimeError("something else broke")

    backend = OllamaBackend()
    result = backend.run("prompt", make_skill())

    assert result.status == "failed"


@patch("sylvae.backends.ollama_backend.litellm.completion")
def test_run_model_kwarg_overrides_default(mock_completion):
    mock_completion.return_value = {
        "choices": [{"message": {"content": "mistral answer"}}]
    }

    backend = OllamaBackend()
    result = backend.run("prompt", make_skill(), model="ollama/mistral:latest")

    assert result.model == "ollama/mistral:latest"
    assert mock_completion.call_args.kwargs["model"] == "ollama/mistral:latest"
    assert backend.model == "ollama/qwen2.5:14b"

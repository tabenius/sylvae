import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

from litellm.exceptions import APIConnectionError

from sylvae.backends.ollama_backend import OllamaBackend
from sylvae.loader import Skill


def make_skill() -> Skill:
    return Skill(slug="s", name="s", description="d", instructions="do X", path=Path("."))


def _preflight_ok():
    """Patch target + return value for a reachable server that has the model."""
    return patch("sylvae.backends.ollama_backend._check_model_availability", return_value=(True, True))


@_preflight_ok()
@patch("sylvae.backends.ollama_backend.litellm.completion")
def test_run_returns_ok_on_success(mock_completion, mock_preflight):
    mock_completion.return_value = {
        "choices": [{"message": {"content": "the local answer"}}]
    }

    backend = OllamaBackend()
    result = backend.run("prompt", make_skill())

    assert result.status == "ok"
    assert result.output == "the local answer"
    assert result.model == "ollama/qwen2.5:14b"


@_preflight_ok()
@patch("sylvae.backends.ollama_backend.litellm.completion")
def test_run_returns_unavailable_when_completion_call_still_fails(mock_completion, mock_preflight):
    # Preflight passed (server reachable, model present), but the completion
    # call itself still raises a connection error mid-request.
    mock_completion.side_effect = APIConnectionError(
        message="connection refused", llm_provider="ollama", model="qwen2.5:14b"
    )

    backend = OllamaBackend()
    result = backend.run("prompt", make_skill())

    assert result.status == "unavailable"


@_preflight_ok()
@patch("sylvae.backends.ollama_backend.litellm.completion")
def test_run_returns_failed_on_other_errors(mock_completion, mock_preflight):
    mock_completion.side_effect = RuntimeError("something else broke")

    backend = OllamaBackend()
    result = backend.run("prompt", make_skill())

    assert result.status == "failed"


@_preflight_ok()
@patch("sylvae.backends.ollama_backend.litellm.completion")
def test_run_model_kwarg_overrides_default(mock_completion, mock_preflight):
    mock_completion.return_value = {
        "choices": [{"message": {"content": "mistral answer"}}]
    }

    backend = OllamaBackend()
    result = backend.run("prompt", make_skill(), model="ollama/mistral:latest")

    assert result.model == "ollama/mistral:latest"
    assert mock_completion.call_args.kwargs["model"] == "ollama/mistral:latest"
    assert backend.model == "ollama/qwen2.5:14b"


@patch("sylvae.backends.ollama_backend._check_model_availability", return_value=(False, False))
def test_run_returns_unavailable_with_clear_error_when_server_unreachable(mock_preflight):
    backend = OllamaBackend()
    result = backend.run("prompt", make_skill())

    assert result.status == "unavailable"
    assert "unreachable" in result.error.lower()
    assert backend.api_base in result.error


@patch("sylvae.backends.ollama_backend._check_model_availability", return_value=(True, False))
def test_run_returns_unavailable_with_clear_error_when_model_not_pulled(mock_preflight):
    backend = OllamaBackend()
    result = backend.run("prompt", make_skill())

    assert result.status == "unavailable"
    assert "not found" in result.error.lower()
    assert "qwen2.5:14b" in result.error
    assert "pull" in result.error.lower()


def test_check_model_availability_reports_unreachable_on_connection_error():
    from sylvae.backends.ollama_backend import _check_model_availability

    with patch("sylvae.backends.ollama_backend.urllib.request.urlopen", side_effect=urllib.error.URLError("refused")):
        reachable, has_model = _check_model_availability("http://localhost:11434", "ollama/mistral:latest")

    assert reachable is False
    assert has_model is False


def test_check_model_availability_reports_model_presence():
    from sylvae.backends.ollama_backend import _check_model_availability

    mock_response = MagicMock()
    mock_response.read.return_value = b'{"models": [{"name": "mistral:latest"}]}'
    mock_response.__enter__.return_value = mock_response

    with patch("sylvae.backends.ollama_backend.urllib.request.urlopen", return_value=mock_response):
        reachable, has_model = _check_model_availability("http://localhost:11434", "ollama/mistral:latest")

    assert reachable is True
    assert has_model is True


@_preflight_ok()
@patch("sylvae.backends.ollama_backend.litellm.completion")
def test_run_auto_prefixes_bare_model_kwarg(mock_completion, mock_preflight):
    mock_completion.return_value = {"choices": [{"message": {"content": "ok"}}]}

    backend = OllamaBackend()
    result = backend.run("prompt", make_skill(), model="qwen2.5:14b")

    assert mock_completion.call_args.kwargs["model"] == "ollama/qwen2.5:14b"
    assert result.model == "ollama/qwen2.5:14b"
    # the availability check must see the same normalized model too
    mock_preflight.assert_called_once()
    assert mock_preflight.call_args.args[1] == "ollama/qwen2.5:14b"


@_preflight_ok()
@patch("sylvae.backends.ollama_backend.litellm.completion")
def test_run_does_not_double_prefix_an_already_prefixed_model(mock_completion, mock_preflight):
    mock_completion.return_value = {"choices": [{"message": {"content": "ok"}}]}

    backend = OllamaBackend()
    result = backend.run("prompt", make_skill(), model="ollama/mistral:latest")

    assert result.model == "ollama/mistral:latest"
    assert mock_completion.call_args.kwargs["model"] == "ollama/mistral:latest"

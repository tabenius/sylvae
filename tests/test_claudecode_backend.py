import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from sylvae.backends.claudecode_backend import ClaudeCodeBackend
from sylvae.loader import Skill


def make_skill() -> Skill:
    return Skill(slug="s", name="s", description="d", instructions="do X", path=Path("."))


def _cli_json(result_text: str = "the answer", rate_limit_status: str = "allowed", is_error: bool = False) -> str:
    """Mimic the real `claude -p --output-format json` array shape."""
    return json.dumps([
        {"type": "system", "subtype": "init", "tools": [], "apiKeySource": "none"},
        {"type": "assistant", "message": {"content": [{"type": "text", "text": result_text}]}},
        {"type": "rate_limit_event", "rate_limit_info": {"status": rate_limit_status, "rateLimitType": "five_hour"}},
        {"type": "result", "subtype": "success", "is_error": is_error, "result": result_text,
         "total_cost_usd": 0.0266, "usage": {"cache_creation_input_tokens": 3146}},
    ])


@patch("sylvae.backends.subprocess_utils.subprocess.run")
def test_run_extracts_result_field(mock_run):
    mock_run.return_value = MagicMock(returncode=0, stdout=_cli_json("hello from claude code"), stderr="")

    result = ClaudeCodeBackend().run("prompt", make_skill())

    assert result.status == "ok"
    assert result.output == "hello from claude code"


@patch("sylvae.backends.subprocess_utils.subprocess.run")
def test_run_uses_minimal_invocation_flags(mock_run):
    mock_run.return_value = MagicMock(returncode=0, stdout=_cli_json(), stderr="")

    ClaudeCodeBackend().run("some prompt; $(danger)", make_skill())

    cmd = mock_run.call_args.args[0]
    # These three flags are what cut per-call cost from ~28.4k tokens to ~3.1k.
    # If they disappear, cost regresses ~6x silently.
    assert cmd[cmd.index("--output-format") + 1] == "json"
    assert "--strict-mcp-config" in cmd
    assert cmd[cmd.index("--setting-sources") + 1] == ""
    assert "some prompt; $(danger)" in cmd
    assert mock_run.call_args.kwargs.get("shell") is not True


@patch("sylvae.backends.subprocess_utils.subprocess.run")
def test_run_forwards_model_override(mock_run):
    mock_run.return_value = MagicMock(returncode=0, stdout=_cli_json(), stderr="")

    result = ClaudeCodeBackend().run("prompt", make_skill(), model="claude-opus-5")

    cmd = mock_run.call_args.args[0]
    assert cmd[cmd.index("--model") + 1] == "claude-opus-5"
    assert result.model == "claude-opus-5"


@patch("sylvae.backends.subprocess_utils.subprocess.run")
def test_run_omits_model_flag_when_not_given(mock_run):
    mock_run.return_value = MagicMock(returncode=0, stdout=_cli_json(), stderr="")

    ClaudeCodeBackend().run("prompt", make_skill())

    assert "--model" not in mock_run.call_args.args[0]


@patch("sylvae.backends.subprocess_utils.subprocess.run")
def test_rate_limited_maps_to_unavailable_not_failed(mock_run):
    mock_run.return_value = MagicMock(
        returncode=0, stdout=_cli_json(rate_limit_status="rejected"), stderr=""
    )

    result = ClaudeCodeBackend().run("prompt", make_skill())

    # Out of budget is "we never got an answer", not "we got a bad answer".
    assert result.status == "unavailable"
    assert "rate limit" in result.error.lower()


@patch("sylvae.backends.subprocess_utils.subprocess.run")
def test_not_logged_in_maps_to_unavailable(mock_run):
    mock_run.return_value = MagicMock(
        returncode=0, stdout=_cli_json("Not logged in · Please run /login"), stderr=""
    )

    result = ClaudeCodeBackend().run("prompt", make_skill())

    assert result.status == "unavailable"
    assert "logged in" in result.error.lower()


@patch("sylvae.backends.subprocess_utils.subprocess.run")
def test_cli_reported_error_maps_to_failed(mock_run):
    mock_run.return_value = MagicMock(
        returncode=0, stdout=_cli_json("something broke", is_error=True), stderr=""
    )

    result = ClaudeCodeBackend().run("prompt", make_skill())

    assert result.status == "failed"


@patch("sylvae.backends.subprocess_utils.subprocess.run")
def test_unparseable_output_maps_to_failed(mock_run):
    mock_run.return_value = MagicMock(returncode=0, stdout="not json at all", stderr="")

    result = ClaudeCodeBackend().run("prompt", make_skill())

    assert result.status == "failed"


@patch("sylvae.backends.subprocess_utils.subprocess.run")
def test_binary_missing_maps_to_unavailable(mock_run):
    mock_run.side_effect = FileNotFoundError()

    assert ClaudeCodeBackend().run("prompt", make_skill()).status == "unavailable"


def test_backend_name_and_defaults():
    backend = ClaudeCodeBackend()

    assert backend.name == "claudecode"
    assert backend.command == "claude"

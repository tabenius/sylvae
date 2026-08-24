import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from sylvae.backends.opencode_backend import OpenCodeBackend
from sylvae.loader import Skill


def make_skill() -> Skill:
    return Skill(slug="s", name="s", description="d", instructions="do X", path=Path("."))


def _jsonl_events(*texts: str) -> str:
    lines = [
        json.dumps({"type": "text", "part": {"type": "text", "text": text}})
        for text in texts
    ]
    lines.append(json.dumps({"type": "step_finish", "part": {"type": "step-finish"}}))
    return "\n".join(lines)


@patch("sylvae.backends.subprocess_utils.subprocess.run")
def test_run_returns_ok_extracting_text_events(mock_run):
    mock_run.return_value = MagicMock(returncode=0, stdout=_jsonl_events("hello from opencode"), stderr="")

    backend = OpenCodeBackend()
    result = backend.run("prompt", make_skill())

    assert result.status == "ok"
    assert result.output == "hello from opencode"
    assert result.model == "opencode/big-pickle"


@patch("sylvae.backends.subprocess_utils.subprocess.run")
def test_run_joins_multiple_text_events(mock_run):
    mock_run.return_value = MagicMock(returncode=0, stdout=_jsonl_events("first part", "second part"), stderr="")

    backend = OpenCodeBackend()
    result = backend.run("prompt", make_skill())

    assert result.output == "first part\nsecond part"


@patch("sylvae.backends.subprocess_utils.subprocess.run")
def test_run_ignores_non_json_and_non_text_lines(mock_run):
    stdout = 'not json at all\n{"type":"step_start","part":{}}\n' + _jsonl_events("the real reply")
    mock_run.return_value = MagicMock(returncode=0, stdout=stdout, stderr="")

    backend = OpenCodeBackend()
    result = backend.run("prompt", make_skill())

    assert result.output == "the real reply"


@patch("sylvae.backends.subprocess_utils.subprocess.run")
def test_run_uses_model_kwarg_override(mock_run):
    mock_run.return_value = MagicMock(returncode=0, stdout=_jsonl_events("ok"), stderr="")

    backend = OpenCodeBackend()
    result = backend.run("prompt", make_skill(), model="opencode/kimi-k3")

    cmd = mock_run.call_args.args[0]
    assert cmd[cmd.index("--model") + 1] == "opencode/kimi-k3"
    assert result.model == "opencode/kimi-k3"


@patch("sylvae.backends.subprocess_utils.subprocess.run")
def test_run_uses_json_format_and_passes_prompt_as_argv(mock_run):
    mock_run.return_value = MagicMock(returncode=0, stdout=_jsonl_events("ok"), stderr="")

    backend = OpenCodeBackend()
    backend.run("some prompt; $(danger)", make_skill())

    cmd = mock_run.call_args.args[0]
    assert cmd[cmd.index("--format") + 1] == "json"
    assert "some prompt; $(danger)" in cmd
    assert mock_run.call_args.kwargs.get("shell") is not True


@patch("sylvae.backends.subprocess_utils.subprocess.run")
def test_run_returns_unavailable_when_binary_not_found(mock_run):
    mock_run.side_effect = FileNotFoundError()

    backend = OpenCodeBackend()
    result = backend.run("prompt", make_skill())

    assert result.status == "unavailable"


@patch("sylvae.backends.subprocess_utils.subprocess.run")
def test_run_returns_failed_on_nonzero_exit(mock_run):
    mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="opencode blew up")

    backend = OpenCodeBackend()
    result = backend.run("prompt", make_skill())

    assert result.status == "failed"
    assert "opencode blew up" in result.error


def test_backend_name_and_defaults():
    backend = OpenCodeBackend()

    assert backend.name == "opencode"
    assert backend.command == "opencode"
    assert backend.model == "opencode/big-pickle"

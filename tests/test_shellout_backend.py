import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

from sylvae.backends.shellout_backend import ShelloutBackend
from sylvae.loader import Skill


def make_skill() -> Skill:
    return Skill(slug="s", name="s", description="d", instructions="do X", path=Path("."))


def _fake_success(output_text: str):
    """Build a subprocess.run side_effect that writes to the real -o path
    the code passed, mimicking what `codex exec -o <file>` actually does."""

    def _run(cmd, **kwargs):
        output_path = Path(cmd[cmd.index("-o") + 1])
        output_path.write_text(output_text)
        return MagicMock(returncode=0, stdout="", stderr="")

    return _run


@patch("sylvae.backends.shellout_backend.subprocess.run")
def test_run_returns_ok_with_output_file_contents(mock_run):
    mock_run.side_effect = _fake_success("the codex answer\n")

    backend = ShelloutBackend()
    result = backend.run("prompt", make_skill())

    assert result.status == "ok"
    assert result.output == "the codex answer"
    assert result.model == "codex"


@patch("sylvae.backends.shellout_backend.subprocess.run")
def test_run_passes_prompt_as_a_separate_argv_element(mock_run):
    mock_run.side_effect = _fake_success("ok")

    backend = ShelloutBackend()
    backend.run("some prompt text with; shell $(metacharacters)", make_skill())

    cmd = mock_run.call_args.args[0]
    assert "some prompt text with; shell $(metacharacters)" in cmd
    assert mock_run.call_args.kwargs.get("shell") is not True


@patch("sylvae.backends.shellout_backend.subprocess.run")
def test_run_forwards_model_kwarg_as_dash_m_flag(mock_run):
    mock_run.side_effect = _fake_success("ok")

    backend = ShelloutBackend()
    backend.run("prompt", make_skill(), model="gpt-5.6-sol")

    cmd = mock_run.call_args.args[0]
    assert "-m" in cmd
    assert cmd[cmd.index("-m") + 1] == "gpt-5.6-sol"


@patch("sylvae.backends.shellout_backend.subprocess.run")
def test_run_omits_dash_m_flag_when_no_model_given(mock_run):
    mock_run.side_effect = _fake_success("ok")

    backend = ShelloutBackend()
    backend.run("prompt", make_skill())

    cmd = mock_run.call_args.args[0]
    assert "-m" not in cmd


@patch("sylvae.backends.shellout_backend.subprocess.run")
def test_run_returns_unavailable_when_binary_not_found(mock_run):
    mock_run.side_effect = FileNotFoundError("no such file")

    backend = ShelloutBackend()
    result = backend.run("prompt", make_skill())

    assert result.status == "unavailable"
    assert "codex" in result.error.lower()


@patch("sylvae.backends.shellout_backend.subprocess.run")
def test_run_returns_unavailable_on_timeout(mock_run):
    mock_run.side_effect = subprocess.TimeoutExpired(cmd="codex", timeout=180)

    backend = ShelloutBackend()
    result = backend.run("prompt", make_skill())

    assert result.status == "unavailable"
    assert "timed out" in result.error.lower()


@patch("sylvae.backends.shellout_backend.subprocess.run")
def test_run_returns_failed_on_nonzero_exit(mock_run):
    mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="something went wrong")

    backend = ShelloutBackend()
    result = backend.run("prompt", make_skill())

    assert result.status == "failed"
    assert "something went wrong" in result.error


def test_backend_name_and_default_command():
    backend = ShelloutBackend()

    assert backend.name == "shellout"
    assert backend.command == "codex"

import subprocess
from unittest.mock import MagicMock, patch

from sylvae.backends.subprocess_utils import run_subprocess_backend


@patch("sylvae.backends.subprocess_utils.subprocess.run")
def test_returns_ok_with_extracted_output(mock_run):
    mock_run.return_value = MagicMock(returncode=0, stdout="raw stdout", stderr="")

    result = run_subprocess_backend(
        ["some-cli", "arg"], command_name="some-cli", model="some-model",
        timeout=30.0, extract_output=lambda completed: completed.stdout.upper(),
    )

    assert result.status == "ok"
    assert result.output == "RAW STDOUT"
    assert result.model == "some-model"


@patch("sylvae.backends.subprocess_utils.subprocess.run")
def test_never_uses_a_shell(mock_run):
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

    run_subprocess_backend(
        ["some-cli"], command_name="some-cli", model="m", timeout=30.0,
        extract_output=lambda completed: "",
    )

    assert mock_run.call_args.kwargs.get("shell") is not True
    assert mock_run.call_args.kwargs.get("stdin") == subprocess.DEVNULL


@patch("sylvae.backends.subprocess_utils.subprocess.run")
def test_returns_unavailable_when_binary_not_found(mock_run):
    mock_run.side_effect = FileNotFoundError()

    result = run_subprocess_backend(
        ["missing-cli"], command_name="missing-cli", model="m", timeout=30.0,
        extract_output=lambda completed: "",
    )

    assert result.status == "unavailable"
    assert "missing-cli" in result.error
    assert result.model == "m"


@patch("sylvae.backends.subprocess_utils.subprocess.run")
def test_returns_unavailable_on_timeout(mock_run):
    mock_run.side_effect = subprocess.TimeoutExpired(cmd="some-cli", timeout=30.0)

    result = run_subprocess_backend(
        ["some-cli"], command_name="some-cli", model="m", timeout=30.0,
        extract_output=lambda completed: "",
    )

    assert result.status == "unavailable"
    assert "timed out" in result.error.lower()


@patch("sylvae.backends.subprocess_utils.subprocess.run")
def test_returns_failed_on_nonzero_exit_with_stderr_tail(mock_run):
    mock_run.return_value = MagicMock(returncode=2, stdout="", stderr="the real problem")

    result = run_subprocess_backend(
        ["some-cli"], command_name="some-cli", model="m", timeout=30.0,
        extract_output=lambda completed: "",
    )

    assert result.status == "failed"
    assert "the real problem" in result.error
    assert "2" in result.error


@patch("sylvae.backends.subprocess_utils.subprocess.run")
def test_extract_output_not_called_on_failure(mock_run):
    mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="boom")
    extractor = MagicMock()

    run_subprocess_backend(
        ["some-cli"], command_name="some-cli", model="m", timeout=30.0,
        extract_output=extractor,
    )

    extractor.assert_not_called()

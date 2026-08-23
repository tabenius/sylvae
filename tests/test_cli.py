from unittest.mock import MagicMock, patch

import pytest

from sylvae.evidence import EvidenceRecord
from sylvae.cli import main


def make_record(status: str = "ok") -> EvidenceRecord:
    return EvidenceRecord(
        skill="summarize-diff", backend="anthropic", model="claude-sonnet-5",
        input_summary="x", output="the output", duration_ms=1,
        status=status, timestamp="2026-08-23T10:00:00+00:00",
    )


@patch("sylvae.cli.run_skill")
def test_main_prints_output_and_returns_zero_on_ok(mock_run_skill, capsys):
    mock_run_skill.return_value = make_record(status="ok")

    exit_code = main(["run", "skills/summarize-diff", "--backend", "anthropic", "--input", "hi"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "the output" in captured.out


@patch("sylvae.cli.run_skill")
def test_main_returns_one_on_non_ok_status(mock_run_skill, capsys):
    mock_run_skill.return_value = make_record(status="unavailable")

    exit_code = main(["run", "skills/summarize-diff", "--backend", "ollama", "--input", "hi"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "unavailable" in captured.err


def test_main_rejects_unknown_backend_before_running():
    with pytest.raises(SystemExit) as exc_info:
        main(["run", "skills/summarize-diff", "--backend", "not-real", "--input", "hi"])
    assert exc_info.value.code == 2

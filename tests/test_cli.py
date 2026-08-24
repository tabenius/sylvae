import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sylvae.evidence import EvidenceRecord
from sylvae.cli import main


def make_record(status: str = "ok", error: str | None = None) -> EvidenceRecord:
    return EvidenceRecord(
        skill="summarize-diff", backend="anthropic", model="claude-sonnet-5",
        input_summary="x", output="the output", duration_ms=1,
        status=status, timestamp="2026-08-23T10:00:00+00:00", error=error,
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


@patch("sylvae.cli.run_skill")
def test_main_prints_real_error_when_present(mock_run_skill, capsys):
    mock_run_skill.return_value = make_record(
        status="unavailable",
        error="model 'qwen2.5:14b' not found on Ollama server — run `ollama pull qwen2.5:14b`",
    )

    exit_code = main(["run", "skills/summarize-diff", "--backend", "ollama", "--input", "hi"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "ollama pull qwen2.5:14b" in captured.err


def test_main_rejects_unknown_backend_before_running():
    with pytest.raises(SystemExit) as exc_info:
        main(["run", "skills/summarize-diff", "--backend", "not-real", "--input", "hi"])
    assert exc_info.value.code == 2


def test_main_end_to_end_via_shellout(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    repo_root = Path(__file__).parent.parent
    skill_path = repo_root / "skills" / "summarize-diff"

    exit_code = main(["run", str(skill_path), "--backend", "shellout", "--input", "some text"])

    assert exit_code == 1
    runs_files = list((tmp_path / "runs").glob("*.jsonl"))
    assert len(runs_files) == 1
    record = json.loads(runs_files[0].read_text().strip())
    assert record["status"] == "unavailable"
    assert record["skill"] == "summarize-diff"


@patch("sylvae.cli.run_skill")
def test_main_forwards_model_flag(mock_run_skill):
    mock_run_skill.return_value = make_record(status="ok")

    main(["run", "skills/summarize-diff", "--backend", "ollama", "--input", "hi", "--model", "ollama/mistral:latest"])

    assert mock_run_skill.call_args.kwargs["model"] == "ollama/mistral:latest"


@patch("sylvae.cli.run_skill")
def test_main_omits_model_kwarg_when_flag_not_given(mock_run_skill):
    mock_run_skill.return_value = make_record(status="ok")

    main(["run", "skills/summarize-diff", "--backend", "anthropic", "--input", "hi"])

    assert mock_run_skill.call_args.kwargs.get("model") is None


@patch("sylvae.cli.run_skill")
def test_main_accepts_auto_backend(mock_run_skill):
    mock_run_skill.return_value = make_record(status="ok")

    exit_code = main(["run", "skills/disk-report", "--backend", "auto", "--input", "hi"])

    assert exit_code == 0
    assert mock_run_skill.call_args.args[1] == "auto"

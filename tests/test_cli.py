import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sylvae.evidence import EvidenceRecord, append_evidence
from sylvae.cli import main


def make_record(status: str = "ok", error: str | None = None) -> EvidenceRecord:
    return EvidenceRecord(
        run_id="deadbeef" * 4,
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


@patch("sylvae.backends.subprocess_utils.subprocess.run", side_effect=FileNotFoundError())
def test_main_end_to_end_via_shellout(mock_subprocess_run, tmp_path, monkeypatch):
    # Now that ShelloutBackend is real (not a phase-1 stub), the subprocess
    # boundary must stay mocked here — otherwise this "no live deps" proof
    # would itself become a live external process call. Simulating codex
    # missing from PATH still exercises the full real chain (cli -> loader
    # -> runner -> backend -> evidence) without depending on codex being
    # installed wherever this suite runs.
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
def test_main_forwards_preallocated_run_id(mock_run_skill):
    mock_run_skill.return_value = make_record(status="ok")
    run_id = "12345678123442348234123456789abc"

    main([
        "run", "skills/summarize-diff", "--backend", "anthropic",
        "--input", "hi", "--run-id", run_id,
    ])

    assert mock_run_skill.call_args.kwargs["run_id"] == run_id


@patch("sylvae.cli.run_skill")
def test_main_accepts_auto_backend(mock_run_skill):
    mock_run_skill.return_value = make_record(status="ok")

    exit_code = main(["run", "skills/disk-report", "--backend", "auto", "--input", "hi"])

    assert exit_code == 0
    assert mock_run_skill.call_args.args[1] == "auto"


@patch("sylvae.cli.serve")
def test_main_review_forwards_defaults(mock_serve):
    exit_code = main(["review"])

    assert exit_code == 0
    mock_serve.assert_called_once_with(runs_dir="runs", skills_dir="skills", host="127.0.0.1", port=8971)


@patch("sylvae.cli.serve")
def test_main_review_forwards_custom_flags(mock_serve):
    main([
        "review", "--runs-dir", "/tmp/other-runs", "--skills-dir", "/tmp/other-skills",
        "--host", "0.0.0.0", "--port", "9999",
    ])

    mock_serve.assert_called_once_with(
        runs_dir="/tmp/other-runs", skills_dir="/tmp/other-skills", host="0.0.0.0", port=9999,
    )


def _seed_runs(runs_dir: Path) -> None:
    # Two runs on distinct days so most-recent-first ordering is observable.
    append_evidence(
        EvidenceRecord(
            run_id="a" * 32, skill="summarize-diff", backend="ollama",
            model="ollama/mistral", input_summary="x", output="o", duration_ms=5,
            status="ok", timestamp="2026-08-23T10:00:00+00:00",
        ),
        runs_dir=runs_dir,
    )
    append_evidence(
        EvidenceRecord(
            run_id="b" * 32, skill="disk-report", backend="anthropic",
            model="claude-sonnet-5", input_summary="y", output="", duration_ms=9,
            status="failed", timestamp="2026-08-24T11:00:00+00:00", error="boom",
        ),
        runs_dir=runs_dir,
    )


def test_runs_json_lists_records_with_runtime_ref_most_recent_first(tmp_path, capsys):
    _seed_runs(tmp_path)

    exit_code = main(["runs", "--runs-dir", str(tmp_path), "--json"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert [r["run_id"] for r in payload] == ["b" * 32, "a" * 32]  # most recent first
    # The derived runtime_ref is surfaced even though it never enters the log.
    assert payload[0]["runtime_ref"] == "sylvae:run/" + "b" * 32
    assert payload[1]["runtime_ref"] == "sylvae:run/" + "a" * 32


def test_runs_table_shows_header_and_runtime_ref(tmp_path, capsys):
    _seed_runs(tmp_path)

    exit_code = main(["runs", "--runs-dir", str(tmp_path)])

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "RUNTIME_REF" in out
    assert "sylvae:run/" + "a" * 32 in out
    assert "summarize-diff" in out and "disk-report" in out


def test_runs_filters_and_limit(tmp_path, capsys):
    _seed_runs(tmp_path)

    # Filter by status.
    main(["runs", "--runs-dir", str(tmp_path), "--status", "failed", "--json"])
    failed = json.loads(capsys.readouterr().out)
    assert [r["run_id"] for r in failed] == ["b" * 32]

    # Filter by backend.
    main(["runs", "--runs-dir", str(tmp_path), "--backend", "ollama", "--json"])
    ollama = json.loads(capsys.readouterr().out)
    assert [r["skill"] for r in ollama] == ["summarize-diff"]

    # Limit caps the (most-recent-first) list.
    main(["runs", "--runs-dir", str(tmp_path), "--limit", "1", "--json"])
    limited = json.loads(capsys.readouterr().out)
    assert [r["run_id"] for r in limited] == ["b" * 32]


def test_runs_empty_log_is_not_an_error(tmp_path, capsys):
    exit_code = main(["runs", "--runs-dir", str(tmp_path / "nope"), "--json"])
    assert exit_code == 0
    assert json.loads(capsys.readouterr().out) == []

    exit_code = main(["runs", "--runs-dir", str(tmp_path / "nope")])
    assert exit_code == 0
    assert "No runs recorded." in capsys.readouterr().err


def test_show_json_returns_the_record_with_runtime_ref(tmp_path, capsys):
    _seed_runs(tmp_path)

    exit_code = main(["show", "b" * 32, "--runs-dir", str(tmp_path), "--json"])

    assert exit_code == 0
    record = json.loads(capsys.readouterr().out)
    assert record["run_id"] == "b" * 32
    assert record["runtime_ref"] == "sylvae:run/" + "b" * 32
    assert record["skill"] == "disk-report"
    assert record["error"] == "boom"


def test_show_accepts_an_unambiguous_prefix_and_prints_detail(tmp_path, capsys):
    _seed_runs(tmp_path)

    exit_code = main(["show", "aaaa", "--runs-dir", str(tmp_path)])

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "sylvae:run/" + "a" * 32 in out
    assert "summarize-diff" in out
    assert "--- output ---" in out  # the recorded output section is shown


def test_show_unknown_run_id_is_an_error(tmp_path, capsys):
    _seed_runs(tmp_path)

    exit_code = main(["show", "does-not-exist", "--runs-dir", str(tmp_path)])

    assert exit_code == 1
    assert "No run found" in capsys.readouterr().err


def test_show_ambiguous_prefix_is_refused_not_guessed(tmp_path, capsys):
    # Two runs whose ids share a prefix.
    for suffix in ("1", "2"):
        append_evidence(
            EvidenceRecord(
                run_id="cafe" + suffix + "0" * 27, skill="s", backend="ollama",
                model="m", input_summary="i", output="o", duration_ms=1,
                status="ok", timestamp="2026-08-25T0" + suffix + ":00:00+00:00",
            ),
            runs_dir=tmp_path,
        )

    exit_code = main(["show", "cafe", "--runs-dir", str(tmp_path)])

    assert exit_code == 1
    assert "ambiguous" in capsys.readouterr().err

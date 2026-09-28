import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from sylvae.backends.base import BackendResult
from sylvae.runner import (
    BACKENDS,
    RunRateLimited,
    _nostoi,
    build_prompt,
    resolve_backend,
    resolve_input,
    run_skill,
)
from sylvae.loader import Skill

SKILL_PATH = Path(__file__).parent.parent / "skills" / "summarize-diff"


def test_resolve_input_reads_existing_file(tmp_path):
    f = tmp_path / "diff.txt"
    f.write_text("diff --git a/x b/x")

    assert resolve_input(str(f)) == "diff --git a/x b/x"


def test_resolve_input_passes_through_literal_text():
    assert resolve_input("just some text") == "just some text"


def test_build_prompt_includes_skill_instructions_and_input():
    skill = Skill(slug="s", name="s", description="d", instructions="Summarize it.", path=Path("."))

    prompt = build_prompt(skill, "the diff content")

    assert "Summarize it." in prompt
    assert "the diff content" in prompt


def test_run_skill_writes_evidence_and_returns_record(tmp_path, monkeypatch):
    fake_backend = MagicMock()
    fake_backend.run.return_value = BackendResult(
        output="a summary", model="fake-model", duration_ms=10, status="ok"
    )
    monkeypatch.setitem(BACKENDS, "fake", MagicMock(return_value=fake_backend))

    record = run_skill(
        SKILL_PATH, "fake", "some input text", runs_dir=tmp_path,
        run_id="12345678123442348234123456789abc",
    )

    assert record.status == "ok"
    assert record.output == "a summary"
    assert record.skill == "summarize-diff"
    assert (tmp_path / f"{record.timestamp[:10]}.jsonl").exists()
    report = _nostoi().verify(tmp_path / "nostoi.jsonl")
    assert report["ok"] is True
    assert report["verified"] == 2
    records = [json.loads(line) for line in (tmp_path / "nostoi.jsonl").read_text().splitlines()]
    assert records[0]["kind"] == "skill.run.requested"
    assert records[0]["body"]["input"] == "some input text"
    assert records[1]["kind"] == "skill.run.completed"
    assert records[1]["body"]["intent_digest"] == records[0]["digest"]
    fake_backend.run.assert_called_once()


def test_run_skill_uses_valid_preallocated_run_id(tmp_path, monkeypatch):
    fake_backend = MagicMock()
    fake_backend.run.return_value = BackendResult(
        output="a summary", model="fake-model", duration_ms=10, status="ok"
    )
    monkeypatch.setitem(BACKENDS, "fake", MagicMock(return_value=fake_backend))
    run_id = "12345678123442348234123456789abc"

    record = run_skill(
        SKILL_PATH, "fake", "some input", runs_dir=tmp_path, run_id=run_id
    )

    assert record.run_id == run_id
    assert record.runtime_ref == f"sylvae:run/{run_id}"


def test_run_skill_rejects_noncanonical_preallocated_run_id(tmp_path, monkeypatch):
    monkeypatch.setitem(BACKENDS, "fake", MagicMock())
    with pytest.raises(ValueError, match="32 lowercase hexadecimal"):
        run_skill(
            SKILL_PATH,
            "fake",
            "some input",
            runs_dir=tmp_path,
            run_id="not-a-run-id",
        )


def test_run_skill_rejects_unknown_backend(tmp_path):
    with pytest.raises(ValueError):
        run_skill(SKILL_PATH, "not-a-real-backend", "input", runs_dir=tmp_path)


def test_run_skill_forwards_model_override_to_backend(tmp_path, monkeypatch):
    fake_backend = MagicMock()
    fake_backend.run.return_value = BackendResult(
        output="a summary", model="custom-model", duration_ms=10, status="ok"
    )
    monkeypatch.setitem(BACKENDS, "fake", MagicMock(return_value=fake_backend))

    record = run_skill(SKILL_PATH, "fake", "some input text", runs_dir=tmp_path, model="custom-model")

    assert record.model == "custom-model"
    fake_backend.run.assert_called_once()
    assert fake_backend.run.call_args.kwargs["model"] == "custom-model"


def test_run_skill_omits_model_kwarg_when_not_given(tmp_path, monkeypatch):
    fake_backend = MagicMock()
    fake_backend.run.return_value = BackendResult(
        output="a summary", model="default-model", duration_ms=10, status="ok"
    )
    monkeypatch.setitem(BACKENDS, "fake", MagicMock(return_value=fake_backend))

    run_skill(SKILL_PATH, "fake", "some input text", runs_dir=tmp_path)

    assert "model" not in fake_backend.run.call_args.kwargs


def test_run_skill_threads_backend_error_into_evidence_record(tmp_path, monkeypatch):
    fake_backend = MagicMock()
    fake_backend.run.return_value = BackendResult(
        output="", model="fake-model", duration_ms=5, status="unavailable",
        error="model 'x' not found on Ollama server — run `ollama pull x`",
    )
    monkeypatch.setitem(BACKENDS, "fake", MagicMock(return_value=fake_backend))

    record = run_skill(SKILL_PATH, "fake", "some input text", runs_dir=tmp_path)

    assert record.status == "unavailable"
    assert record.error == "model 'x' not found on Ollama server — run `ollama pull x`"


def test_provider_exception_leaves_a_linked_failure_in_nostoi(tmp_path, monkeypatch):
    fake_backend = MagicMock()
    fake_backend.run.side_effect = RuntimeError("provider failed")
    monkeypatch.setitem(BACKENDS, "fake", MagicMock(return_value=fake_backend))

    with pytest.raises(RuntimeError, match="provider failed"):
        run_skill(
            SKILL_PATH, "fake", "private prompt", runs_dir=tmp_path,
            run_id="12345678123442348234123456789abc",
        )

    records = [json.loads(line) for line in (tmp_path / "nostoi.jsonl").read_text().splitlines()]
    assert [record["kind"] for record in records] == [
        "skill.run.requested", "skill.run.failed"
    ]
    assert records[0]["body"]["input"] == "private prompt"
    assert records[1]["body"]["intent_digest"] == records[0]["digest"]
    assert records[1]["body"]["error_type"] == "RuntimeError"


def test_run_budget_records_only_one_limited_event(tmp_path, monkeypatch):
    import sylvae.runner as runner

    fake_backend = MagicMock()
    fake_backend.run.return_value = BackendResult(
        output="ok", model="fake", duration_ms=1, status="ok"
    )
    monkeypatch.setitem(BACKENDS, "fake", MagicMock(return_value=fake_backend))
    monkeypatch.setattr(runner, "MAX_RUNS_PER_MINUTE", 1)
    monkeypatch.setattr(runner, "_run_admissions", [])
    monkeypatch.setattr(runner, "_run_limit_recorded_minute", None)

    run_skill(SKILL_PATH, "fake", "one", runs_dir=tmp_path)
    for _ in range(2):
        with pytest.raises(RunRateLimited):
            run_skill(SKILL_PATH, "fake", "flood", runs_dir=tmp_path)

    records = [json.loads(line) for line in (tmp_path / "nostoi.jsonl").read_text().splitlines()]
    assert [record["kind"] for record in records].count("skill.run.rate_limited") == 1
    assert fake_backend.run.call_count == 1


def test_run_input_is_bounded(tmp_path):
    with pytest.raises(ValueError, match="100000-character run limit"):
        resolve_input("x" * 100_001)
    source = tmp_path / "large.txt"
    source.write_text("x" * 100_001)
    with pytest.raises(ValueError, match="100000-character run limit"):
        resolve_input(str(source))


def test_resolve_backend_passes_through_explicit_choice():
    skill = Skill(slug="s", name="s", description="d", instructions="i", path=Path("."), tier="cheap")

    assert resolve_backend(skill, "anthropic") == "anthropic"


def test_resolve_backend_routes_cheap_tier_to_ollama():
    skill = Skill(slug="s", name="s", description="d", instructions="i", path=Path("."), tier="cheap")

    assert resolve_backend(skill, "auto") == "ollama"


# Frontier-tier and unset-tier routing moved to tests/test_tier_routing.py.
# The tests that lived here asserted the target was "anthropic", which was
# the bug: it made --backend auto fail for every skill not marked cheap,
# since no Anthropic credentials exist here. The replacements assert against
# the tier map rather than a hardcoded backend name, so retargeting does not
# silently break them again.


def test_run_skill_auto_routes_cheap_tier_skill_to_ollama(tmp_path, monkeypatch):
    fake_ollama = MagicMock()
    fake_ollama.run.return_value = BackendResult(
        output="cheap answer", model="ollama/mistral:latest", duration_ms=5, status="ok"
    )
    monkeypatch.setitem(BACKENDS, "ollama", MagicMock(return_value=fake_ollama))

    skill_dir = tmp_path / "cheap-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("---\nname: cheap-skill\ndescription: d\ntier: cheap\n---\nbody")

    record = run_skill(skill_dir, "auto", "some input", runs_dir=tmp_path / "runs")

    assert record.backend == "ollama"
    assert record.output == "cheap answer"


def test_run_skill_rejects_unknown_explicit_backend_without_touching_filesystem(tmp_path):
    with pytest.raises(ValueError):
        run_skill(Path("/does/not/exist"), "not-a-real-backend", "input", runs_dir=tmp_path)

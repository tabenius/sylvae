from pathlib import Path
from unittest.mock import MagicMock

import pytest

from sylvae.backends.base import BackendResult
from sylvae.runner import BACKENDS, build_prompt, resolve_backend, resolve_input, run_skill
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

    record = run_skill(SKILL_PATH, "fake", "some input text", runs_dir=tmp_path)

    assert record.status == "ok"
    assert record.output == "a summary"
    assert record.skill == "summarize-diff"
    assert (tmp_path / f"{record.timestamp[:10]}.jsonl").exists()


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


def test_resolve_backend_passes_through_explicit_choice():
    skill = Skill(slug="s", name="s", description="d", instructions="i", path=Path("."), tier="cheap")

    assert resolve_backend(skill, "anthropic") == "anthropic"


def test_resolve_backend_routes_cheap_tier_to_ollama():
    skill = Skill(slug="s", name="s", description="d", instructions="i", path=Path("."), tier="cheap")

    assert resolve_backend(skill, "auto") == "ollama"


def test_resolve_backend_routes_frontier_tier_to_anthropic():
    skill = Skill(slug="s", name="s", description="d", instructions="i", path=Path("."), tier="frontier")

    assert resolve_backend(skill, "auto") == "anthropic"


def test_resolve_backend_defaults_missing_tier_to_anthropic():
    skill = Skill(slug="s", name="s", description="d", instructions="i", path=Path("."), tier=None)

    assert resolve_backend(skill, "auto") == "anthropic"


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

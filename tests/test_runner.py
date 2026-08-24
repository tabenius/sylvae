from pathlib import Path
from unittest.mock import MagicMock

import pytest

from sylvae.backends.base import BackendResult
from sylvae.runner import BACKENDS, build_prompt, resolve_input, run_skill
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

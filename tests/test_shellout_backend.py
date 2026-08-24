from pathlib import Path

from sylvae.backends.shellout_backend import ShelloutBackend
from sylvae.loader import Skill


def test_run_is_unavailable_in_phase_one():
    skill = Skill(slug="s", name="s", description="d", instructions="do X", path=Path("."))
    backend = ShelloutBackend()

    result = backend.run("prompt", skill)

    assert result.status == "unavailable"
    assert backend.name == "shellout"
    assert "not implemented" in (result.error or "").lower()


def test_run_accepts_and_ignores_model_kwarg():
    skill = Skill(slug="s", name="s", description="d", instructions="do X", path=Path("."))
    backend = ShelloutBackend()

    result = backend.run("prompt", skill, model="whatever")

    assert result.status == "unavailable"

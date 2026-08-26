"""The third tier, and strict tier validation.

Codex and OpenCode are not "expensive Ollama" or "cheap Anthropic" -- they
are a structurally different resource. Both are full agent invocations with
fixed bootstrap overhead regardless of task size (measured in phase 1 at
~6s/11.5k tokens for a trivial Codex prompt, 13-25s/26k for OpenCode). A
two-value vocabulary had nowhere to put that, which is why they were
excluded from routing rather than mis-slotted into it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sylvae.loader import VALID_TIERS, SkillLoadError, load_skill
from sylvae.runner import DEFAULT_TIER_BACKENDS, BACKENDS, resolve_backend, tier_backends


def _skill_file(tmp_path: Path, tier: str | None) -> Path:
    d = tmp_path / "s"
    d.mkdir(parents=True, exist_ok=True)
    tier_line = f"tier: {tier}\n" if tier is not None else ""
    (d / "SKILL.md").write_text(f"---\nname: s\ndescription: d\n{tier_line}---\nbody")
    return d


def test_agent_is_a_recognised_tier():
    assert "agent" in VALID_TIERS
    assert VALID_TIERS == {"cheap", "frontier", "agent"}


def test_agent_tier_loads(tmp_path):
    assert load_skill(_skill_file(tmp_path, "agent")).tier == "agent"


def test_agent_tier_routes_to_a_subprocess_backend(tmp_path):
    skill = load_skill(_skill_file(tmp_path, "agent"))

    target = resolve_backend(skill, "auto")

    assert target == DEFAULT_TIER_BACKENDS["agent"]
    assert target in BACKENDS


def test_agent_target_is_distinct_from_the_frontier_target():
    """If they collapse to the same backend the tier carries no information
    and the vocabulary is lying about what it expresses."""
    assert DEFAULT_TIER_BACKENDS["agent"] != DEFAULT_TIER_BACKENDS["frontier"]


def test_agent_target_is_configurable(monkeypatch):
    monkeypatch.setenv("SYLVAE_BACKEND_AGENT", "opencode")

    assert tier_backends()["agent"] == "opencode"


# --------------------------------------------------------------------------
# Strict validation. With three values a typo becomes likelier, and silent
# fallthrough would route the typo'd skill to the most expensive backend --
# a costly failure nobody notices until the bill.
# --------------------------------------------------------------------------

@pytest.mark.parametrize("bad", ["cheep", "Frontier", "AGENT", "fast", "expensive", ""])
def test_unrecognised_tier_is_a_load_error_not_a_silent_fallthrough(tmp_path, bad):
    with pytest.raises(SkillLoadError) as exc:
        load_skill(_skill_file(tmp_path, bad))

    assert "tier" in str(exc.value).lower()


def test_absent_tier_remains_valid(tmp_path):
    """Declaring a tier stays optional: absence means "unset", which routes
    to the safe target. Only a WRONG value is an error."""
    assert load_skill(_skill_file(tmp_path, None)).tier is None


def test_shipped_skills_all_declare_valid_tiers():
    repo_skills = Path(__file__).parent.parent / "skills"
    for skill_md in repo_skills.glob("*/SKILL.md"):
        skill = load_skill(skill_md.parent)
        assert skill.tier is None or skill.tier in VALID_TIERS


def test_cli_reports_a_tier_typo_cleanly_rather_than_by_traceback(tmp_path, capsys):
    """Strict validation only helps if the message reaches the author. A
    traceback is the wrong way to say "you wrote tier: cheep"."""
    from sylvae.cli import main

    _skill_file(tmp_path, "cheep")

    exit_code = main(["run", str(tmp_path / "s"), "--backend", "auto", "--input", "x"])

    assert exit_code == 1
    err = capsys.readouterr().err
    assert "cheep" in err
    assert "Traceback" not in err

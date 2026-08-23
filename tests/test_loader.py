from pathlib import Path

import pytest

from sylvae.loader import Skill, SkillLoadError, load_skill

FIXTURE = Path(__file__).parent.parent / "skills" / "summarize-diff"


def test_load_skill_parses_frontmatter_and_body():
    skill = load_skill(FIXTURE)

    assert isinstance(skill, Skill)
    assert skill.slug == "summarize-diff"
    assert skill.name == "summarize-diff"
    assert "diff" in skill.description.lower()
    assert len(skill.instructions.strip()) > 0
    assert skill.path == FIXTURE


def test_load_skill_missing_directory_raises():
    with pytest.raises(SkillLoadError):
        load_skill(Path(__file__).parent / "does-not-exist")


def test_load_skill_missing_frontmatter_raises(tmp_path):
    bad = tmp_path / "bad-skill"
    bad.mkdir()
    (bad / "SKILL.md").write_text("no frontmatter here")

    with pytest.raises(SkillLoadError):
        load_skill(bad)

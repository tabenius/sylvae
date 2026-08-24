from pathlib import Path

import pytest

from sylvae.loader import Skill, SkillLoadError, load_skill

FIXTURE = Path(__file__).parent.parent / "skills" / "summarize-diff"
DISK_REPORT_FIXTURE = Path(__file__).parent.parent / "skills" / "disk-report"


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


def test_load_skill_disk_report_fixture():
    skill = load_skill(DISK_REPORT_FIXTURE)

    assert skill.slug == "disk-report"
    assert "85%" in skill.instructions


def test_load_skill_tier_defaults_to_none_when_not_declared(tmp_path):
    skill_dir = tmp_path / "no-tier"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("---\nname: no-tier\ndescription: d\n---\nbody")

    skill = load_skill(skill_dir)

    assert skill.tier is None


def test_load_skill_parses_declared_tier(tmp_path):
    skill_dir = tmp_path / "cheap-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("---\nname: cheap-skill\ndescription: d\ntier: cheap\n---\nbody")

    skill = load_skill(skill_dir)

    assert skill.tier == "cheap"

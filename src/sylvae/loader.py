from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


class SkillLoadError(Exception):
    pass


@dataclass(frozen=True)
class Skill:
    slug: str
    name: str
    description: str
    instructions: str
    path: Path
    tier: str | None = None  # "cheap" | "frontier" | None (unset)


def load_skill(skill_dir: str | Path) -> Skill:
    path = Path(skill_dir)
    skill_file = path / "SKILL.md"
    if not skill_file.is_file():
        raise SkillLoadError(f"no SKILL.md found in {path}")

    raw = skill_file.read_text()
    if not raw.startswith("---"):
        raise SkillLoadError(f"{skill_file} is missing YAML frontmatter")

    parts = raw.split("---", 2)
    if len(parts) < 3:
        raise SkillLoadError(f"{skill_file} has malformed frontmatter")

    try:
        meta = yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError as exc:
        raise SkillLoadError(f"{skill_file} has invalid YAML frontmatter: {exc}") from exc

    for key in ("name", "description"):
        if key not in meta:
            raise SkillLoadError(f"{skill_file} frontmatter is missing required key '{key}'")

    return Skill(
        slug=path.name,
        name=meta["name"],
        description=meta["description"],
        instructions=parts[2].strip(),
        path=path,
        tier=meta.get("tier"),
    )

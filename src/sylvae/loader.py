from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml


class SkillLoadError(Exception):
    pass


# A skill slug is a single directory name and nothing else. Anchored, so no
# separator, parent reference, or absolute path can appear anywhere in it.
# Leading dot excluded so hidden directories are not addressable either.
_SAFE_SLUG = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._-]*\Z")


def validate_skill_slug(slug: str) -> str:
    """Reject any slug that is not a plain directory name.

    Path traversal through this parameter was demonstrated against the MCP
    service: a slug of "../../../../../tmp/evil-skill" loaded and ran a
    SKILL.md planted outside the configured skills directory. That surface
    is driven by a model rather than a person, so untrusted text being
    processed can reach it.

    The same defect had already been found and fixed once, in the review
    web UI, and was reintroduced in a second surface. Hence validating here
    -- at the point every caller passes through -- instead of at each one.
    """
    if not isinstance(slug, str) or not _SAFE_SLUG.match(slug):
        raise SkillLoadError(
            f"invalid skill name {slug!r}: must be a single directory name "
            "matching [A-Za-z0-9][A-Za-z0-9._-]*"
        )
    if ".." in slug:  # unreachable via the pattern; kept as an explicit assertion
        raise SkillLoadError(f"invalid skill name {slug!r}: parent references are refused")
    return slug


def resolve_skill_dir(skills_dir: str | Path, slug: str) -> Path:
    """Resolve a slug to a real path, refusing anything outside skills_dir.

    Two independent checks, deliberately. The slug pattern stops the obvious
    string attacks; the post-resolution containment check stops the ones a
    pattern cannot see -- notably a symlink inside skills/ pointing out of
    it, whose name is a perfectly ordinary word.
    """
    validate_skill_slug(slug)
    root = Path(skills_dir).resolve()
    candidate = (root / slug).resolve()
    if not candidate.is_relative_to(root):
        raise SkillLoadError(
            f"skill {slug!r} resolves outside the skills directory and was refused"
        )
    return candidate


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

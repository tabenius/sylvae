"""Security regression tests.

Every case here corresponds to a real defect that was demonstrated against
this codebase, not a hypothetical. Two of them are the same class of bug
appearing twice in different surfaces, which is the reason the fixes live at
choke points (loader, backend base) rather than per-caller.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from sylvae.backends.base import InvalidModelName, validate_model_name
from sylvae.loader import SkillLoadError, resolve_skill_dir, validate_skill_slug

# --------------------------------------------------------------------------
# Path traversal via skill slug
#
# Confirmed exploitable in the MCP service before the fix: a slug of
# "../../../../../tmp/evil-skill" loaded and ran a SKILL.md planted outside
# the configured skills directory. The MCP surface is driven by a MODEL, so
# prompt injection in the text being processed could reach it.
# --------------------------------------------------------------------------

TRAVERSAL_SLUGS = [
    "../../../../../tmp/evil-skill",
    "../evil",
    "..",
    "sub/dir",
    "sub\\dir",
    "/etc",
    "/absolute/path",
    ".hidden",
    "",
    " ",
    "ok/../../escape",
]


@pytest.mark.parametrize("slug", TRAVERSAL_SLUGS)
def test_validate_skill_slug_rejects_non_plain_names(slug):
    with pytest.raises(SkillLoadError):
        validate_skill_slug(slug)


@pytest.mark.parametrize("slug", ["disk-report", "summarize_diff", "judge-run", "a", "a.b"])
def test_validate_skill_slug_accepts_ordinary_names(slug):
    assert validate_skill_slug(slug) == slug


@pytest.mark.parametrize("slug", TRAVERSAL_SLUGS)
def test_resolve_skill_dir_refuses_to_escape(tmp_path, slug):
    (tmp_path / "real").mkdir()
    with pytest.raises(SkillLoadError):
        resolve_skill_dir(tmp_path, slug)


def test_resolve_skill_dir_returns_a_contained_path(tmp_path):
    (tmp_path / "real").mkdir()

    resolved = resolve_skill_dir(tmp_path, "real")

    assert resolved == (tmp_path / "real").resolve()
    assert resolved.is_relative_to(tmp_path.resolve())


def test_resolve_skill_dir_blocks_symlink_escape(tmp_path):
    """A symlink inside skills/ pointing out of it must not be a way through.

    Slug validation alone would pass this -- the name is a plain word -- so
    the containment check has to happen after resolution, not just on the
    string."""
    outside = tmp_path / "outside"
    outside.mkdir()
    skills = tmp_path / "skills"
    skills.mkdir()
    (skills / "sneaky").symlink_to(outside, target_is_directory=True)

    with pytest.raises(SkillLoadError):
        resolve_skill_dir(skills, "sneaky")


# --------------------------------------------------------------------------
# Argument injection via model name
#
# Demonstrated: ShelloutBackend().run(..., model="--dangerously-bypass-
# approvals-and-sandbox") produced argv containing that token, which is a
# REAL codex flag that disables sandboxing. Whether the downstream parser
# treats it as -m's value or as a flag is version-dependent; relying on a
# third-party parser to disambiguate is not a security control.
# --------------------------------------------------------------------------

HOSTILE_MODELS = [
    "--dangerously-bypass-approvals-and-sandbox",
    "--dangerously-skip-permissions",
    "-c",
    "--add-dir=/",
    "-",
    "--",
]


@pytest.mark.parametrize("model", HOSTILE_MODELS)
def test_validate_model_name_rejects_flag_shaped_values(model):
    with pytest.raises(InvalidModelName):
        validate_model_name(model)


@pytest.mark.parametrize(
    "model",
    ["claude-sonnet-5", "ollama/mistral:latest", "opencode/big-pickle",
     "mistral:7b-instruct-q4_0", "gpt-5.6-sol"],
)
def test_validate_model_name_accepts_real_model_ids(model):
    assert validate_model_name(model) == model


@pytest.mark.parametrize("model", ["a b", "a;b", "a$(id)b", "a\nb", "a`b`"])
def test_validate_model_name_rejects_shell_metacharacters(model):
    # Not exploitable today (argv is list-form, never a shell string) but a
    # model id containing these is malformed by any reading, and refusing
    # them removes the question entirely if a future backend ever builds a
    # command string.
    with pytest.raises(InvalidModelName):
        validate_model_name(model)


def test_backends_reject_hostile_model_before_spawning_anything():
    from sylvae.backends.shellout_backend import ShelloutBackend
    from sylvae.loader import Skill

    skill = Skill(slug="s", name="s", description="d", instructions="i", path=Path("."))

    with patch("sylvae.backends.subprocess_utils.subprocess.run") as mock_run:
        result = ShelloutBackend().run(
            "prompt", skill, model="--dangerously-bypass-approvals-and-sandbox"
        )

    assert result.status == "failed"
    mock_run.assert_not_called()


def test_mcp_service_refuses_traversal_slug(tmp_path):
    from sylvae.mcp.service import McpToolService

    (tmp_path / "skills" / "real").mkdir(parents=True)
    (tmp_path / "skills" / "real" / "SKILL.md").write_text(
        "---\nname: real\ndescription: d\n---\nbody"
    )
    service = McpToolService(skills_dir=tmp_path / "skills", runs_dir=tmp_path / "runs")

    with patch("sylvae.mcp.service.run_skill") as mock_run:
        out = service.run_skill(skill="../../../../../tmp/evil-skill", input="x")

    assert out["ok"] is False
    mock_run.assert_not_called()

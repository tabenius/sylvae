from pathlib import Path
from unittest.mock import MagicMock, patch

from sylvae.evidence import EvidenceRecord
from sylvae.mcp.service import DEFAULT_MCP_BACKEND, RECURSION_RISK_BACKENDS, McpToolService


def _make_skill(skills_dir: Path, slug: str, tier: str | None = None) -> None:
    d = skills_dir / slug
    d.mkdir(parents=True)
    tier_line = f"tier: {tier}\n" if tier else ""
    (d / "SKILL.md").write_text(f"---\nname: {slug}\ndescription: does {slug}\n{tier_line}---\nDo it.")


def _service(tmp_path: Path, **kw) -> McpToolService:
    return McpToolService(skills_dir=tmp_path / "skills", runs_dir=tmp_path / "runs", **kw)


def _record(**over) -> EvidenceRecord:
    base = dict(
        run_id="a" * 32,
        skill="s", backend="ollama", model="ollama/mistral:latest", input_summary="x",
        output="the output", duration_ms=12, status="ok",
        timestamp="2026-08-24T12:00:00Z", error=None,
    )
    base.update(over)
    return EvidenceRecord(**base)


def test_list_skills_reports_slug_description_and_tier(tmp_path):
    _make_skill(tmp_path / "skills", "disk-report", tier="cheap")

    out = _service(tmp_path).list_skills()

    assert out["ok"] is True
    entry = next(s for s in out["skills"] if s["slug"] == "disk-report")
    assert entry["tier"] == "cheap"
    assert "disk-report" in entry["description"]


def test_list_skills_on_missing_dir_is_empty_not_an_error(tmp_path):
    out = _service(tmp_path).list_skills()

    assert out["ok"] is True
    assert out["skills"] == []


@patch("sylvae.mcp.service.run_skill")
def test_run_skill_defaults_to_the_cheap_backend(mock_run, tmp_path):
    _make_skill(tmp_path / "skills", "s")
    mock_run.return_value = _record()

    out = _service(tmp_path).run_skill(skill="s", input="hi")

    assert out["ok"] is True
    assert out["output"] == "the output"
    # An agent calling Sylvae must not land on something as costly as itself.
    assert mock_run.call_args.args[1] == DEFAULT_MCP_BACKEND
    assert DEFAULT_MCP_BACKEND == "ollama"


@patch("sylvae.mcp.service.run_skill")
def test_run_skill_honours_an_explicit_cheap_backend(mock_run, tmp_path):
    _make_skill(tmp_path / "skills", "s")
    mock_run.return_value = _record(backend="opencode")

    out = _service(tmp_path).run_skill(skill="s", input="hi", backend="opencode")

    assert out["ok"] is True
    assert mock_run.call_args.args[1] == "opencode"


@patch("sylvae.mcp.service.run_skill")
def test_recursion_risk_backend_is_refused_by_default(mock_run, tmp_path):
    _make_skill(tmp_path / "skills", "s")

    out = _service(tmp_path).run_skill(skill="s", input="hi", backend="claudecode")

    assert out["ok"] is False
    assert "recursion" in out["error"].lower()
    mock_run.assert_not_called()
    assert "claudecode" in RECURSION_RISK_BACKENDS


@patch("sylvae.mcp.service.run_skill")
def test_recursion_risk_backend_allowed_only_by_operator_config(mock_run, tmp_path):
    _make_skill(tmp_path / "skills", "s")
    mock_run.return_value = _record(backend="claudecode")

    # allow_recursive_backends is constructor-level: set by the human registering
    # the server, never reachable as a per-call argument a model could pass.
    out = _service(tmp_path, allow_recursive_backends=True).run_skill(
        skill="s", input="hi", backend="claudecode"
    )

    assert out["ok"] is True
    assert mock_run.call_args.args[1] == "claudecode"


@patch("sylvae.mcp.service.run_skill")
def test_auto_backend_is_refused_because_it_could_route_to_a_recursive_backend(mock_run, tmp_path):
    _make_skill(tmp_path / "skills", "s")

    out = _service(tmp_path).run_skill(skill="s", input="hi", backend="auto")

    assert out["ok"] is False
    mock_run.assert_not_called()


def test_unknown_skill_returns_structured_error_not_an_exception(tmp_path):
    _make_skill(tmp_path / "skills", "real")

    out = _service(tmp_path).run_skill(skill="nope", input="hi")

    assert out["ok"] is False
    assert "nope" in out["error"]


def test_unknown_backend_returns_structured_error(tmp_path):
    _make_skill(tmp_path / "skills", "s")

    out = _service(tmp_path).run_skill(skill="s", input="hi", backend="not-a-backend")

    assert out["ok"] is False
    assert "not-a-backend" in out["error"]


@patch("sylvae.mcp.service.run_skill")
def test_failed_run_is_reported_without_raising(mock_run, tmp_path):
    _make_skill(tmp_path / "skills", "s")
    mock_run.return_value = _record(status="unavailable", output="", error="ollama is down")

    out = _service(tmp_path).run_skill(skill="s", input="hi")

    # The tool call itself succeeded; the run did not. Those are different facts
    # and the caller needs both.
    assert out["ok"] is True
    assert out["status"] == "unavailable"
    assert out["error_detail"] == "ollama is down"


@patch("sylvae.mcp.service.run_skill")
def test_run_skill_forwards_model_override(mock_run, tmp_path):
    _make_skill(tmp_path / "skills", "s")
    mock_run.return_value = _record()

    _service(tmp_path).run_skill(skill="s", input="hi", model="mistral:latest")

    assert mock_run.call_args.kwargs["model"] == "mistral:latest"


@patch("sylvae.mcp.service.run_skill")
def test_run_skill_reports_backend_model_and_duration(mock_run, tmp_path):
    _make_skill(tmp_path / "skills", "s")
    mock_run.return_value = _record()

    out = _service(tmp_path).run_skill(skill="s", input="hi")

    assert out["backend"] == "ollama"
    assert out["model"] == "ollama/mistral:latest"
    assert out["duration_ms"] == 12


@patch("sylvae.mcp.service.run_skill", side_effect=RuntimeError("something exploded"))
def test_unexpected_exception_becomes_a_structured_error_not_a_traceback(mock_run, tmp_path):
    _make_skill(tmp_path / "skills", "s")

    out = _service(tmp_path).run_skill(skill="s", input="hi")

    assert out["ok"] is False
    assert "something exploded" in out["error"]


def test_missing_sdk_raises_a_clear_dependency_error(tmp_path):
    # The SDK is an optional extra; core Sylvae must not require it. This is
    # what a user sees if they run `sylvae mcp` without installing it.
    import builtins

    from sylvae.mcp.server import McpDependencyError, build_server

    real_import = builtins.__import__

    def _no_mcp(name, *args, **kwargs):
        if name.startswith("mcp"):
            raise ModuleNotFoundError(name)
        return real_import(name, *args, **kwargs)

    with patch.object(builtins, "__import__", _no_mcp):
        try:
            build_server(_service(tmp_path))
            raised = None
        except McpDependencyError as exc:
            raised = exc

    assert raised is not None
    assert "mcp" in str(raised).lower()

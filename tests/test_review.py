import json
import threading
import urllib.error
import urllib.parse
import urllib.request
from unittest.mock import patch

from sylvae.evidence import EvidenceRecord
from sylvae.review import list_skills, load_all_runs, render_html, start_server


def _write_jsonl(path, records):
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n")


def make_record(**overrides):
    record = {
        "skill": "summarize-diff", "backend": "ollama", "model": "ollama/mistral:latest",
        "input_summary": "diff --git a/x b/x", "output": "Changed x.", "duration_ms": 1234,
        "status": "ok", "timestamp": "2026-08-24T10:00:00Z", "error": None,
    }
    record.update(overrides)
    return record


def test_load_all_runs_reads_and_combines_multiple_files(tmp_path):
    _write_jsonl(tmp_path / "2026-08-23.jsonl", [make_record(timestamp="2026-08-23T10:00:00Z")])
    _write_jsonl(tmp_path / "2026-08-24.jsonl", [make_record(timestamp="2026-08-24T10:00:00Z")])

    records = load_all_runs(tmp_path)

    assert len(records) == 2


def test_load_all_runs_sorts_most_recent_first(tmp_path):
    _write_jsonl(tmp_path / "runs.jsonl", [
        make_record(timestamp="2026-08-24T10:00:00Z", skill="early"),
        make_record(timestamp="2026-08-24T12:00:00Z", skill="late"),
    ])

    records = load_all_runs(tmp_path)

    assert records[0]["skill"] == "late"
    assert records[1]["skill"] == "early"


def test_load_all_runs_returns_empty_list_for_missing_dir(tmp_path):
    assert load_all_runs(tmp_path / "does-not-exist") == []


def test_load_all_runs_skips_blank_lines(tmp_path):
    path = tmp_path / "runs.jsonl"
    path.write_text(json.dumps(make_record()) + "\n\n")

    records = load_all_runs(tmp_path)

    assert len(records) == 1


def test_render_html_includes_run_fields():
    html = render_html([make_record()])

    assert "summarize-diff" in html
    assert "ollama" in html
    assert "ok" in html
    assert "Changed x." in html


def test_render_html_escapes_output_content():
    html = render_html([make_record(output="<script>alert(1)</script>")])

    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_render_html_handles_empty_run_list():
    html = render_html([])

    assert "no runs" in html.lower()


def test_render_html_shows_error_when_present():
    html = render_html([make_record(status="unavailable", error="model not found — run `ollama pull x`")])

    assert "model not found" in html


def test_server_serves_rendered_page_on_loopback_only(tmp_path):
    _write_jsonl(tmp_path / "runs.jsonl", [make_record(skill="live-test-skill")])

    server = start_server(runs_dir=tmp_path, host="127.0.0.1", port=0)
    try:
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5) as resp:
            body = resp.read().decode("utf-8")
            status = resp.status
    finally:
        server.shutdown()
        server.server_close()

    assert status == 200
    assert "live-test-skill" in body


def _make_skill_fixture(skills_dir, slug, tier=None):
    skill_dir = skills_dir / slug
    skill_dir.mkdir(parents=True)
    tier_line = f"tier: {tier}\n" if tier else ""
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {slug}\ndescription: a test skill\n{tier_line}---\nDo the thing."
    )


def test_list_skills_reads_real_skill_fixtures(tmp_path):
    _make_skill_fixture(tmp_path, "alpha", tier="cheap")
    _make_skill_fixture(tmp_path, "beta")

    skills = list_skills(tmp_path)

    assert {s.slug for s in skills} == {"alpha", "beta"}
    assert next(s for s in skills if s.slug == "alpha").tier == "cheap"


def test_list_skills_returns_empty_list_for_missing_dir(tmp_path):
    assert list_skills(tmp_path / "does-not-exist") == []


def test_list_skills_skips_a_malformed_skill_without_crashing(tmp_path):
    _make_skill_fixture(tmp_path, "good")
    broken_dir = tmp_path / "broken"
    broken_dir.mkdir()
    (broken_dir / "SKILL.md").write_text("not even frontmatter")

    skills = list_skills(tmp_path)

    assert {s.slug for s in skills} == {"good"}


def _running_server(tmp_path, **overrides):
    kwargs = {"runs_dir": tmp_path / "runs", "skills_dir": tmp_path / "skills", "host": "127.0.0.1", "port": 0}
    kwargs.update(overrides)
    server = start_server(**kwargs)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, port


def test_get_root_includes_a_run_form_with_skill_options(tmp_path):
    (tmp_path / "runs").mkdir()
    _make_skill_fixture(tmp_path / "skills", "summarize-diff")

    server, port = _running_server(tmp_path)
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5) as resp:
            body = resp.read().decode("utf-8")
    finally:
        server.shutdown()
        server.server_close()

    assert '<form' in body
    assert 'value="summarize-diff"' in body
    assert 'action="/run"' in body


@patch("sylvae.review.run_skill")
def test_post_run_triggers_run_skill_and_shows_result(mock_run_skill, tmp_path):
    (tmp_path / "runs").mkdir()
    _make_skill_fixture(tmp_path / "skills", "summarize-diff")
    mock_run_skill.return_value = EvidenceRecord(
        skill="summarize-diff", backend="ollama", model="ollama/mistral:latest",
        input_summary="hello", output="a real result", duration_ms=42,
        status="ok", timestamp="2026-08-24T10:00:00Z", error=None,
    )

    server, port = _running_server(tmp_path)
    try:
        data = urllib.parse.urlencode({
            "skill": "summarize-diff", "backend": "ollama", "model": "", "input_text": "hello",
        }).encode()
        req = urllib.request.Request(f"http://127.0.0.1:{port}/run", data=data, method="POST")
        with urllib.request.urlopen(req, timeout=5) as resp:
            body = resp.read().decode("utf-8")
            status = resp.status
    finally:
        server.shutdown()
        server.server_close()

    assert status == 200
    assert "a real result" in body
    mock_run_skill.assert_called_once()
    call_kwargs = mock_run_skill.call_args.kwargs
    assert call_kwargs.get("model") is None
    call_args = mock_run_skill.call_args.args
    assert str(tmp_path / "skills" / "summarize-diff") in str(call_args[0])
    assert call_args[1] == "ollama"
    assert call_args[2] == "hello"


@patch("sylvae.review.run_skill")
def test_post_run_forwards_model_override(mock_run_skill, tmp_path):
    (tmp_path / "runs").mkdir()
    _make_skill_fixture(tmp_path / "skills", "summarize-diff")
    mock_run_skill.return_value = EvidenceRecord(
        skill="summarize-diff", backend="ollama", model="ollama/mistral:latest",
        input_summary="hello", output="ok", duration_ms=1,
        status="ok", timestamp="2026-08-24T10:00:00Z", error=None,
    )

    server, port = _running_server(tmp_path)
    try:
        data = urllib.parse.urlencode({
            "skill": "summarize-diff", "backend": "ollama", "model": "ollama/mistral:latest", "input_text": "hi",
        }).encode()
        req = urllib.request.Request(f"http://127.0.0.1:{port}/run", data=data, method="POST")
        urllib.request.urlopen(req, timeout=5).close()
    finally:
        server.shutdown()
        server.server_close()

    assert mock_run_skill.call_args.kwargs["model"] == "ollama/mistral:latest"


def test_post_run_with_unknown_skill_returns_client_error_not_a_crash(tmp_path):
    (tmp_path / "runs").mkdir()
    _make_skill_fixture(tmp_path / "skills", "summarize-diff")

    server, port = _running_server(tmp_path)
    try:
        data = urllib.parse.urlencode({
            "skill": "does-not-exist", "backend": "ollama", "model": "", "input_text": "hi",
        }).encode()
        req = urllib.request.Request(f"http://127.0.0.1:{port}/run", data=data, method="POST")
        try:
            urllib.request.urlopen(req, timeout=5)
            raised = None
        except urllib.error.HTTPError as exc:
            raised = exc
    finally:
        server.shutdown()
        server.server_close()

    assert raised is not None
    assert raised.code == 400


@patch("sylvae.review.run_skill")
def test_post_run_rejects_path_traversal_slug_without_calling_run_skill(mock_run_skill, tmp_path):
    (tmp_path / "runs").mkdir()
    _make_skill_fixture(tmp_path / "skills", "summarize-diff")

    server, port = _running_server(tmp_path)
    try:
        data = urllib.parse.urlencode({
            "skill": "../../../../etc", "backend": "ollama", "model": "", "input_text": "hi",
        }).encode()
        req = urllib.request.Request(f"http://127.0.0.1:{port}/run", data=data, method="POST")
        try:
            urllib.request.urlopen(req, timeout=5)
            raised = None
        except urllib.error.HTTPError as exc:
            raised = exc
    finally:
        server.shutdown()
        server.server_close()

    assert raised is not None
    assert raised.code == 400
    mock_run_skill.assert_not_called()


@patch("sylvae.review.run_skill")
def test_post_run_rejects_cross_origin_request(mock_run_skill, tmp_path):
    (tmp_path / "runs").mkdir()
    _make_skill_fixture(tmp_path / "skills", "summarize-diff")

    server, port = _running_server(tmp_path)
    try:
        data = urllib.parse.urlencode({
            "skill": "summarize-diff", "backend": "ollama", "model": "", "input_text": "hi",
        }).encode()
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/run", data=data, method="POST",
            headers={"Origin": "http://evil.example"},
        )
        try:
            urllib.request.urlopen(req, timeout=5)
            raised = None
        except urllib.error.HTTPError as exc:
            raised = exc
    finally:
        server.shutdown()
        server.server_close()

    assert raised is not None
    assert raised.code == 403
    mock_run_skill.assert_not_called()


@patch("sylvae.review.run_skill")
def test_post_run_allows_matching_same_origin_request(mock_run_skill, tmp_path):
    (tmp_path / "runs").mkdir()
    _make_skill_fixture(tmp_path / "skills", "summarize-diff")
    mock_run_skill.return_value = EvidenceRecord(
        skill="summarize-diff", backend="ollama", model="ollama/mistral:latest",
        input_summary="hi", output="ok", duration_ms=1,
        status="ok", timestamp="2026-08-24T10:00:00Z", error=None,
    )

    server, port = _running_server(tmp_path)
    try:
        data = urllib.parse.urlencode({
            "skill": "summarize-diff", "backend": "ollama", "model": "", "input_text": "hi",
        }).encode()
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/run", data=data, method="POST",
            headers={"Origin": f"http://127.0.0.1:{port}"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            status = resp.status
    finally:
        server.shutdown()
        server.server_close()

    assert status == 200
    mock_run_skill.assert_called_once()

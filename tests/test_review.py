import json
import threading
import urllib.error
import urllib.parse
import urllib.request
from unittest.mock import patch

import pytest

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


def test_render_html_surfaces_runtime_ref_when_run_id_present():
    html = render_html([make_record(run_id="a" * 32)])

    assert "runtime ref" in html
    assert "sylvae:run/" + "a" * 32 in html


def test_render_html_omits_runtime_ref_without_run_id():
    html = render_html([make_record()])  # make_record has no run_id

    assert "runtime ref" not in html


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
        run_id="b" * 32,
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
        run_id="b" * 32,
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
        run_id="b" * 32,
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


# ── hardening: Host allowlist, token, headers, fail-closed bind ──────────────

def _raw_request(port, method="GET", path="/", headers=None, body=b""):
    """Send one HTTP request with exactly the given headers (urllib would
    rewrite Host), and return (status, headers, body)."""
    import http.client

    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    conn.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
    for name, value in (headers or {}).items():
        conn.putheader(name, value)
    if body:
        conn.putheader("Content-Length", str(len(body)))
    conn.endheaders(body or None)
    resp = conn.getresponse()
    data = resp.read().decode("utf-8", "replace")
    conn.close()
    return resp.status, dict(resp.getheaders()), data


@patch("sylvae.review.run_skill")
def test_dns_rebinding_host_is_refused_for_reads_and_runs(mock_run_skill, tmp_path):
    """A rebinding page reaches 127.0.0.1 under its own hostname, and its
    Origin matches its Host, so the Origin check alone would let it in."""
    (tmp_path / "runs").mkdir()
    _make_skill_fixture(tmp_path / "skills", "summarize-diff")
    server, port = _running_server(tmp_path)
    evil = f"rebind.evil.example:{port}"
    form = urllib.parse.urlencode({"skill": "summarize-diff", "backend": "ollama", "model": "", "input_text": "hi"}).encode()
    try:
        get_status, _, _ = _raw_request(port, headers={"Host": evil})
        post_status, _, _ = _raw_request(
            port, "POST", "/run", body=form,
            headers={"Host": evil, "Origin": f"http://{evil}", "Content-Type": "application/x-www-form-urlencoded"},
        )
        ok_status, headers, _ = _raw_request(port, headers={"Host": f"127.0.0.1:{port}"})
        localhost_status, _, _ = _raw_request(port, headers={"Host": f"localhost:{port}"})
    finally:
        server.shutdown()
        server.server_close()
    assert get_status == 403
    assert post_status == 403
    mock_run_skill.assert_not_called()
    assert ok_status == 200 and localhost_status == 200
    assert "frame-ancestors 'none'" in headers["Content-Security-Policy"]
    assert headers["X-Frame-Options"] == "DENY"
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["Cache-Control"] == "no-store"


@patch("sylvae.review.run_skill")
def test_token_is_required_on_every_request_when_configured(mock_run_skill, tmp_path):
    (tmp_path / "runs").mkdir()
    _make_skill_fixture(tmp_path / "skills", "summarize-diff")
    mock_run_skill.return_value = EvidenceRecord(
        run_id="c" * 32, skill="summarize-diff", backend="ollama", model="ollama/mistral:latest",
        input_summary="hi", output="ok", duration_ms=1, status="ok", timestamp="2026-09-26T10:00:00Z", error=None,
    )
    server, port = _running_server(tmp_path, token="s3cret-token")
    form = urllib.parse.urlencode({"skill": "summarize-diff", "backend": "ollama", "model": "", "input_text": "hi"}).encode()
    host = {"Host": f"127.0.0.1:{port}"}
    ctype = {"Content-Type": "application/x-www-form-urlencoded"}
    try:
        no_token, no_token_headers, _ = _raw_request(port, headers=host)
        wrong, _, _ = _raw_request(port, headers={**host, "Authorization": "Bearer nope"})
        run_without, _, _ = _raw_request(port, "POST", "/run", body=form, headers={**host, **ctype})
        ok, _, _ = _raw_request(port, headers={**host, "Authorization": "Bearer s3cret-token"})
        # With a token the Host header is not what protects the server.
        lan, _, _ = _raw_request(port, headers={"Host": "reviewer.lan:8971", "Authorization": "Bearer s3cret-token"})
        run_with, _, _ = _raw_request(port, "POST", "/run", body=form,
                                      headers={**host, **ctype, "Authorization": "Bearer s3cret-token"})
    finally:
        server.shutdown()
        server.server_close()
    assert no_token == 401 and no_token_headers["WWW-Authenticate"] == "Bearer"
    assert wrong == 401 and run_without == 401
    assert ok == 200 and lan == 200 and run_with == 200
    mock_run_skill.assert_called_once()


def test_binding_beyond_loopback_requires_a_token(tmp_path):
    from sylvae.review import ReviewConfigError

    with pytest.raises(ReviewConfigError):
        start_server(runs_dir=tmp_path, skills_dir=tmp_path, host="0.0.0.0", port=0)
    server = start_server(runs_dir=tmp_path, skills_dir=tmp_path, host="0.0.0.0", port=0, token="t0ken")
    server.server_close()


def test_cli_reports_an_unsafe_bind_instead_of_a_traceback(tmp_path, monkeypatch, capsys):
    from sylvae.cli import main

    monkeypatch.delenv("SYLVAE_REVIEW_TOKEN", raising=False)
    assert main(["review", "--host", "0.0.0.0", "--port", "0", "--runs-dir", str(tmp_path)]) == 2
    assert "SYLVAE_REVIEW_TOKEN" in capsys.readouterr().err


def test_handler_times_out_stalled_clients():
    from sylvae.review import REQUEST_TIMEOUT_SECONDS, _ReviewHandler

    assert _ReviewHandler.timeout == REQUEST_TIMEOUT_SECONDS == 30

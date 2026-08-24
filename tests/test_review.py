import json
import threading
import urllib.request

from sylvae.review import load_all_runs, render_html, start_server


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

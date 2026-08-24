from __future__ import annotations

import html
import json
import urllib.parse
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from sylvae.loader import Skill, SkillLoadError, load_skill
from sylvae.runner import BACKENDS, run_skill

_STATUS_COLORS = {"ok": "#2e7d46", "failed": "#b3261e", "unavailable": "#9a6300"}


def load_all_runs(runs_dir: str | Path) -> list[dict]:
    """Read every runs/*.jsonl file and return all records, most recent
    first. Re-read fresh on every call — the log is small enough (one
    line per run) that there's no reason to cache and risk staleness."""
    runs_path = Path(runs_dir)
    if not runs_path.is_dir():
        return []

    records = []
    for jsonl_file in sorted(runs_path.glob("*.jsonl")):
        for line in jsonl_file.read_text().splitlines():
            line = line.strip()
            if line:
                records.append(json.loads(line))

    records.sort(key=lambda r: r.get("timestamp", ""), reverse=True)
    return records


def list_skills(skills_dir: str | Path) -> list[Skill]:
    """Discover skills for the run-trigger form. A skill that fails to
    load (malformed SKILL.md) is skipped rather than taking down the
    whole picker — the other skills are still usable."""
    skills_path = Path(skills_dir)
    if not skills_path.is_dir():
        return []

    skills = []
    for skill_md in sorted(skills_path.glob("*/SKILL.md")):
        try:
            skills.append(load_skill(skill_md.parent))
        except SkillLoadError:
            continue
    return skills


def _run_block(record: dict) -> str:
    status = record.get("status", "")
    color = _STATUS_COLORS.get(status, "#666")

    detail_parts = []
    if record.get("input_summary"):
        detail_parts.append(f'<div class="field"><strong>input</strong><pre>{html.escape(record["input_summary"])}</pre></div>')
    if record.get("output"):
        detail_parts.append(f'<div class="field"><strong>output</strong><pre>{html.escape(record["output"])}</pre></div>')
    if record.get("error"):
        detail_parts.append(f'<div class="field"><strong>error</strong><pre>{html.escape(record["error"])}</pre></div>')
    detail = "".join(detail_parts) or '<div class="field">(no output)</div>'

    skill = html.escape(record.get("skill", ""))
    backend = html.escape(record.get("backend", ""))
    model = html.escape(record.get("model", ""))
    timestamp = html.escape(record.get("timestamp", ""))
    duration = record.get("duration_ms", "")

    return f"""
    <div class="run" data-skill="{skill}" data-backend="{backend}" data-status="{html.escape(status)}">
      <details open>
        <summary>
          <span class="status" style="background:{color}">{html.escape(status)}</span>
          <span class="time">{timestamp}</span>
          <span class="skill">{skill}</span>
          <span class="backend">{backend}</span>
          <span class="model">{model}</span>
          <span class="duration">{duration} ms</span>
        </summary>
        <div class="detail">{detail}</div>
      </details>
    </div>
    """


def _run_form_html(skills: list[Skill]) -> str:
    if not skills:
        return '<p class="hint">No skills found to run — add one under the skills directory.</p>'

    skill_options = "".join(
        f'<option value="{html.escape(s.slug)}">{html.escape(s.slug)} — {html.escape(s.description)}</option>'
        for s in skills
    )
    backend_options = "".join(f'<option value="{html.escape(b)}">{html.escape(b)}</option>' for b in ["auto"] + sorted(BACKENDS))

    return f"""
    <form method="POST" action="/run" class="run-form">
      <h2>Run a skill</h2>
      <label>skill
        <select name="skill" required>{skill_options}</select>
      </label>
      <label>backend
        <select name="backend" required>{backend_options}</select>
      </label>
      <label>model override <span class="hint">(optional)</span>
        <input type="text" name="model" placeholder="e.g. ollama/mistral:latest">
      </label>
      <label>input
        <textarea name="input_text" rows="5" required placeholder="Pasted text — the raw diff, df -h output, etc."></textarea>
      </label>
      <button type="submit">Run</button>
    </form>
    """


_STYLE = """
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #fafaf8; color: #1c1c1a; margin: 2rem auto; max-width: 68rem; }
  @media (prefers-color-scheme: dark) { body { background: #14201d; color: #e2e6e2; } summary { color: #e2e6e2; } .detail { background: rgba(255,255,255,0.04) !important; } .run, .run-form { border-color: #2c3a35 !important; } .run-form { background: #182420 !important; } input, select, textarea { background: #0e1613; color: #e2e6e2; border-color: #2c3a35 !important; } }
  h1 { font-size: 1.3rem; font-weight: 600; }
  h2 { font-size: 1rem; font-weight: 600; margin: 0 0 0.8rem; }
  .run-form { border: 1px solid #ddd; border-radius: 6px; padding: 1rem 1.2rem; margin-bottom: 1.5rem; background: #f2f2ee; display: flex; flex-direction: column; gap: 0.7rem; max-width: 34rem; }
  .run-form label { display: flex; flex-direction: column; gap: 0.25rem; font-size: 0.82rem; font-weight: 600; }
  .run-form .hint { font-weight: 400; color: #888; }
  .run-form select, .run-form input, .run-form textarea { font: inherit; font-size: 0.85rem; padding: 0.4rem 0.5rem; border: 1px solid #ccc; border-radius: 4px; font-weight: 400; }
  .run-form button { align-self: flex-start; padding: 0.5rem 1.2rem; border: none; border-radius: 4px; background: #2e6b46; color: white; font-weight: 600; cursor: pointer; }
  .run-form button:hover { background: #24593a; }
  .filters { display: flex; gap: 1.2rem; align-items: center; margin: 1rem 0; font-size: 0.85rem; }
  .filters select { margin-left: 0.3rem; }
  #count { color: #777; }
  .run { border: 1px solid #ddd; border-radius: 6px; margin-bottom: 0.5rem; }
  .run[hidden] { display: none; }
  summary { cursor: pointer; padding: 0.5rem 0.8rem; display: flex; gap: 1rem; align-items: center; font-size: 0.85rem; list-style: none; }
  summary::-webkit-details-marker { display: none; }
  .status { color: white; padding: 0.1rem 0.55rem; border-radius: 3px; font-size: 0.72rem; font-weight: 600; min-width: 4.5rem; text-align: center; }
  .time { color: #777; font-variant-numeric: tabular-nums; }
  .skill { font-weight: 600; }
  .backend { color: #555; }
  .model { color: #555; flex: 1; }
  .duration { color: #777; font-variant-numeric: tabular-nums; }
  .detail { padding: 0 0.8rem 0.8rem; background: rgba(0,0,0,0.02); }
  .field { margin: 0.5rem 0; }
  .field strong { display: block; font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.04em; color: #888; margin-bottom: 0.2rem; }
  pre { white-space: pre-wrap; word-break: break-word; font-size: 0.82rem; margin: 0; }
  .back-link { display: inline-block; margin-top: 1rem; font-size: 0.85rem; }
  .error-box { border: 1px solid #b3261e; background: rgba(179,38,30,0.08); color: #b3261e; padding: 0.8rem 1rem; border-radius: 6px; margin-bottom: 1rem; }
"""

_FILTER_SCRIPT = """
function filterRuns() {
  var s = document.getElementById('f-skill');
  var b = document.getElementById('f-backend');
  var st = document.getElementById('f-status');
  s = s ? s.value : '';
  b = b ? b.value : '';
  st = st ? st.value : '';
  var shown = 0;
  document.querySelectorAll('.run').forEach(function(run) {
    var match = (!s || run.dataset.skill === s) && (!b || run.dataset.backend === b) && (!st || run.dataset.status === st);
    if (match) { run.removeAttribute('hidden'); shown++; } else { run.setAttribute('hidden', ''); }
  });
  var countEl = document.getElementById('count');
  if (countEl) countEl.textContent = shown + ' run(s)';
}
filterRuns();
"""


def _page(title: str, body: str, script: str = "") -> str:
    return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>{html.escape(title)}</title>
<style>{_STYLE}</style>
</head>
<body>
{body}
<script>{script}</script>
</body>
</html>
"""


def render_html(records: list[dict], skills: list[Skill] | None = None) -> str:
    form = _run_form_html(skills) if skills is not None else ""

    if not records:
        list_body = "<p>No runs yet.</p>"
    else:
        skill_vals = sorted({r.get("skill", "") for r in records})
        backend_vals = sorted({r.get("backend", "") for r in records})
        status_vals = sorted({r.get("status", "") for r in records})

        def _options(values: list[str]) -> str:
            return "".join(f'<option value="{html.escape(v)}">{html.escape(v)}</option>' for v in values)

        runs_html = "".join(_run_block(r) for r in records)
        list_body = f"""
        <div class="filters">
          <label>skill <select id="f-skill" onchange="filterRuns()"><option value="">all</option>{_options(skill_vals)}</select></label>
          <label>backend <select id="f-backend" onchange="filterRuns()"><option value="">all</option>{_options(backend_vals)}</select></label>
          <label>status <select id="f-status" onchange="filterRuns()"><option value="">all</option>{_options(status_vals)}</select></label>
          <span id="count"></span>
        </div>
        <div id="runs">{runs_html}</div>
        """

    body = f"<h1>Sylvae — evidence log</h1>\n{form}\n{list_body}"
    return _page("Sylvae — evidence", body, _FILTER_SCRIPT)


def render_run_result(record: dict) -> str:
    body = f'<h1>Run result</h1>\n{_run_block(record)}\n<a class="back-link" href="/">&larr; back to evidence log</a>'
    return _page("Sylvae — run result", body)


def render_error(message: str) -> str:
    body = f'<h1>Run result</h1>\n<div class="error-box">{html.escape(message)}</div>\n<a class="back-link" href="/">&larr; back to evidence log</a>'
    return _page("Sylvae — run error", body)


class _ReviewHandler(BaseHTTPRequestHandler):
    runs_dir: Path = Path("runs")
    skills_dir: Path = Path("skills")

    def _write_html(self, page: str, status: int = 200) -> None:
        body = page.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 (stdlib method name)
        records = load_all_runs(self.runs_dir)
        skills = list_skills(self.skills_dir)
        self._write_html(render_html(records, skills=skills))

    def do_POST(self) -> None:  # noqa: N802 (stdlib method name)
        if self.path != "/run":
            self._write_html(render_error(f"no such route: {self.path}"), status=404)
            return

        # A plain HTML form has no built-in cross-origin protection, and
        # this server triggers real, costly backend calls — a page open
        # in the operator's browser could otherwise POST here silently.
        # Browsers send Origin on cross-site POSTs; a request with no
        # Origin (curl, scripts) is allowed through unchanged.
        origin = self.headers.get("Origin")
        if origin is not None and origin != f"http://{self.headers.get('Host', '')}":
            self._write_html(render_error("cross-origin request rejected"), status=403)
            return

        length = int(self.headers.get("Content-Length", 0))
        raw_body = self.rfile.read(length).decode("utf-8")
        fields = urllib.parse.parse_qs(raw_body)
        skill_slug = (fields.get("skill") or [""])[0]
        backend = (fields.get("backend") or [""])[0]
        model = (fields.get("model") or [""])[0].strip() or None
        input_text = (fields.get("input_text") or [""])[0]

        # Only a slug that list_skills() itself discovered is allowed —
        # closes path traversal (a slug containing "../" can never match
        # a real discovered directory name) without needing a separate
        # character blocklist.
        allowed_slugs = {s.slug for s in list_skills(self.skills_dir)}
        if skill_slug not in allowed_slugs:
            self._write_html(render_error(f"unknown skill: {skill_slug!r}"), status=400)
            return

        skill_path = Path(self.skills_dir) / skill_slug

        try:
            record = run_skill(
                str(skill_path), backend, input_text,
                runs_dir=str(self.runs_dir), model=model,
            )
        except (SkillLoadError, ValueError) as exc:
            self._write_html(render_error(str(exc)), status=400)
            return

        self._write_html(render_run_result(asdict(record)))

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        pass  # quiet by default; this is a local dev tool, not a service


def start_server(
    runs_dir: str | Path = "runs",
    skills_dir: str | Path = "skills",
    host: str = "127.0.0.1",
    port: int = 8971,
) -> ThreadingHTTPServer:
    """Create (but do not run) a loopback-only HTTP server. Threading so a
    long-running triggered skill run (real backends take seconds to
    minutes) doesn't block the evidence list for anyone else looking at
    it concurrently. Caller drives it — serve_forever() blocks, so tests
    and the CLI each own that."""
    handler = type(
        "_BoundReviewHandler", (_ReviewHandler,),
        {"runs_dir": Path(runs_dir), "skills_dir": Path(skills_dir)},
    )
    return ThreadingHTTPServer((host, port), handler)


def serve(
    runs_dir: str | Path = "runs",
    skills_dir: str | Path = "skills",
    host: str = "127.0.0.1",
    port: int = 8971,
) -> None:
    server = start_server(runs_dir=runs_dir, skills_dir=skills_dir, host=host, port=port)
    print(f"Sylvae evidence review at http://{host}:{port}/ (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()

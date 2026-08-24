from __future__ import annotations

import html
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

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
      <details>
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


def render_html(records: list[dict]) -> str:
    if not records:
        body = "<p>No runs yet.</p>"
    else:
        skills = sorted({r.get("skill", "") for r in records})
        backends = sorted({r.get("backend", "") for r in records})
        statuses = sorted({r.get("status", "") for r in records})

        def _options(values: list[str]) -> str:
            return "".join(f'<option value="{html.escape(v)}">{html.escape(v)}</option>' for v in values)

        runs_html = "".join(_run_block(r) for r in records)
        body = f"""
        <div class="filters">
          <label>skill <select id="f-skill" onchange="filterRuns()"><option value="">all</option>{_options(skills)}</select></label>
          <label>backend <select id="f-backend" onchange="filterRuns()"><option value="">all</option>{_options(backends)}</select></label>
          <label>status <select id="f-status" onchange="filterRuns()"><option value="">all</option>{_options(statuses)}</select></label>
          <span id="count"></span>
        </div>
        <div id="runs">{runs_html}</div>
        """

    return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>Sylvae — evidence</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #fafaf8; color: #1c1c1a; margin: 2rem auto; max-width: 68rem; }}
  @media (prefers-color-scheme: dark) {{ body {{ background: #14201d; color: #e2e6e2; }} summary {{ color: #e2e6e2; }} .detail {{ background: rgba(255,255,255,0.04) !important; }} .run {{ border-color: #2c3a35 !important; }} }}
  h1 {{ font-size: 1.3rem; font-weight: 600; }}
  .filters {{ display: flex; gap: 1.2rem; align-items: center; margin: 1rem 0; font-size: 0.85rem; }}
  .filters select {{ margin-left: 0.3rem; }}
  #count {{ color: #777; }}
  .run {{ border: 1px solid #ddd; border-radius: 6px; margin-bottom: 0.5rem; }}
  .run[hidden] {{ display: none; }}
  summary {{ cursor: pointer; padding: 0.5rem 0.8rem; display: flex; gap: 1rem; align-items: center; font-size: 0.85rem; list-style: none; }}
  summary::-webkit-details-marker {{ display: none; }}
  .status {{ color: white; padding: 0.1rem 0.55rem; border-radius: 3px; font-size: 0.72rem; font-weight: 600; min-width: 4.5rem; text-align: center; }}
  .time {{ color: #777; font-variant-numeric: tabular-nums; }}
  .skill {{ font-weight: 600; }}
  .backend {{ color: #555; }}
  .model {{ color: #555; flex: 1; }}
  .duration {{ color: #777; font-variant-numeric: tabular-nums; }}
  .detail {{ padding: 0 0.8rem 0.8rem; background: rgba(0,0,0,0.02); }}
  .field {{ margin: 0.5rem 0; }}
  .field strong {{ display: block; font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.04em; color: #888; margin-bottom: 0.2rem; }}
  pre {{ white-space: pre-wrap; word-break: break-word; font-size: 0.82rem; margin: 0; }}
</style>
</head>
<body>
<h1>Sylvae — evidence log</h1>
{body}
<script>
function filterRuns() {{
  var s = document.getElementById('f-skill');
  var b = document.getElementById('f-backend');
  var st = document.getElementById('f-status');
  s = s ? s.value : '';
  b = b ? b.value : '';
  st = st ? st.value : '';
  var shown = 0;
  document.querySelectorAll('.run').forEach(function(run) {{
    var match = (!s || run.dataset.skill === s) && (!b || run.dataset.backend === b) && (!st || run.dataset.status === st);
    if (match) {{ run.removeAttribute('hidden'); shown++; }} else {{ run.setAttribute('hidden', ''); }}
  }});
  var countEl = document.getElementById('count');
  if (countEl) countEl.textContent = shown + ' run(s)';
}}
filterRuns();
</script>
</body>
</html>
"""


class _ReviewHandler(BaseHTTPRequestHandler):
    runs_dir: Path = Path("runs")

    def do_GET(self) -> None:  # noqa: N802 (stdlib method name)
        records = load_all_runs(self.runs_dir)
        page = render_html(records).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(page)))
        self.end_headers()
        self.wfile.write(page)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        pass  # quiet by default; this is a local dev tool, not a service


def start_server(runs_dir: str | Path = "runs", host: str = "127.0.0.1", port: int = 8971) -> HTTPServer:
    """Create (but do not run) a loopback-only HTTP server. Caller drives
    it — serve_forever() blocks, so tests and the CLI each own that."""
    handler = type("_BoundReviewHandler", (_ReviewHandler,), {"runs_dir": Path(runs_dir)})
    return HTTPServer((host, port), handler)


def serve(runs_dir: str | Path = "runs", host: str = "127.0.0.1", port: int = 8971) -> None:
    server = start_server(runs_dir=runs_dir, host=host, port=port)
    print(f"Sylvae evidence review at http://{host}:{port}/ (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()

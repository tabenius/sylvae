from datetime import datetime, timedelta, timezone
import json
import threading
import urllib.error
import urllib.request

from sylvae.cli import main
from sylvae.review import load_all_runs, start_server
from sylvae.runtime_status import load_runtime_status, workflow_commands


def test_stale_and_invalid_observations_are_explicit(tmp_path):
    now = datetime.now(timezone.utc)
    path = tmp_path / "state.json"
    path.write_text(json.dumps({"schema": "ragbaz.runtime-status.v1", "components": {},
        "observed_at": (now - timedelta(minutes=3)).isoformat(), "summary": ["ephor: not-installed"]}))
    assert load_runtime_status(str(path), now=now)["status"] == "stale"
    path.write_text("[]")
    assert load_runtime_status(str(path))["status"] == "unavailable"


def test_audit_chain_is_not_a_run_even_with_custom_name(tmp_path, monkeypatch):
    chain = tmp_path / "custom.jsonl"
    chain.write_text('{"v":"nostoi-v1","seq":1}\n')
    (tmp_path / "2026-10-03.jsonl").write_text('{"skill":"test","timestamp":"today"}\n')
    monkeypatch.setenv("SYLVAE_NOSTOI_LEDGER", str(chain))
    assert len(load_all_runs(tmp_path)) == 1
    assert workflow_commands(tmp_path)["chain"] == str(chain)


def test_health_and_system_endpoints_retain_auth_and_do_not_load_runs(tmp_path, monkeypatch):
    monkeypatch.setenv("SYLVAE_REVIEW_TOKEN", "test-token")
    monkeypatch.setattr("sylvae.review.load_all_runs", lambda path: (_ for _ in ()).throw(AssertionError("must not load run log")))
    server = start_server(runs_dir=tmp_path, host="127.0.0.1", port=0, token="test-token")
    threading.Thread(target=server.serve_forever, daemon=True).start()
    origin = f"http://127.0.0.1:{server.server_port}"
    try:
        try:
            urllib.request.urlopen(origin + "/healthz")
        except urllib.error.HTTPError as error:
            assert error.code == 401
        else:
            raise AssertionError("unauthenticated health request allowed")
        for route, field in (("/healthz", "ok"), ("/api/system", "runtime")):
            request = urllib.request.Request(origin + route, headers={"Authorization": "Bearer test-token"})
            with urllib.request.urlopen(request) as response:
                assert field in json.load(response)
    finally:
        server.shutdown()
        server.server_close()


def test_audit_command_keeps_signing_explicit_and_return_code(monkeypatch, tmp_path):
    import subprocess
    calls = []
    monkeypatch.setattr("sylvae.cli.shutil.which", lambda name: "nostoi")
    def run(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 1)
    monkeypatch.setattr("sylvae.cli.subprocess.run", run)
    assert main(["audit", "--runs-dir", str(tmp_path), "verify-attestation", "--principal", "alice",
                 "--allowed-signers", "signers", "--fingerprint", "SHA256:pin"]) == 1
    assert calls[0][1] == "verify-attestation"

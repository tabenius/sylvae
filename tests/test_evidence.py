import json

from sylvae.evidence import EvidenceRecord, append_evidence


def make_record(timestamp: str = "2026-08-23T10:00:00+00:00") -> EvidenceRecord:
    return EvidenceRecord(
        skill="summarize-diff",
        backend="ollama",
        model="ollama/qwen2.5:14b",
        input_summary="diff --git a/x b/x",
        output="Changed x.",
        duration_ms=1234,
        status="ok",
        timestamp=timestamp,
    )


def test_append_evidence_writes_one_json_line(tmp_path):
    runs_dir = tmp_path / "runs"
    record = make_record()

    written_path = append_evidence(record, runs_dir=runs_dir)

    assert written_path == runs_dir / "2026-08-23.jsonl"
    lines = written_path.read_text().strip().splitlines()
    assert len(lines) == 1
    loaded = json.loads(lines[0])
    assert loaded["skill"] == "summarize-diff"
    assert loaded["status"] == "ok"


def test_append_evidence_appends_to_same_day_file(tmp_path):
    runs_dir = tmp_path / "runs"
    append_evidence(make_record(), runs_dir=runs_dir)
    append_evidence(make_record(), runs_dir=runs_dir)

    lines = (runs_dir / "2026-08-23.jsonl").read_text().strip().splitlines()
    assert len(lines) == 2


def test_evidence_record_error_defaults_to_none_and_round_trips_when_set(tmp_path):
    runs_dir = tmp_path / "runs"
    record = EvidenceRecord(
        skill="summarize-diff", backend="ollama", model="ollama/qwen2.5:14b",
        input_summary="x", output="", duration_ms=14, status="unavailable",
        timestamp="2026-08-23T10:00:00+00:00", error="model 'qwen2.5:14b' not found",
    )
    assert make_record().error is None

    append_evidence(record, runs_dir=runs_dir)

    loaded = json.loads((runs_dir / "2026-08-23.jsonl").read_text().strip())
    assert loaded["error"] == "model 'qwen2.5:14b' not found"

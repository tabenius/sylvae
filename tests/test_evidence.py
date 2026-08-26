import json
import uuid

from sylvae.evidence import EvidenceRecord, append_evidence


def make_record(timestamp: str = "2026-08-23T10:00:00+00:00") -> EvidenceRecord:
    return EvidenceRecord(
        run_id=uuid.uuid4().hex,
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
        run_id=uuid.uuid4().hex,
        skill="summarize-diff", backend="ollama", model="ollama/qwen2.5:14b",
        input_summary="x", output="", duration_ms=14, status="unavailable",
        timestamp="2026-08-23T10:00:00+00:00", error="model 'qwen2.5:14b' not found",
    )
    assert make_record().error is None

    append_evidence(record, runs_dir=runs_dir)

    loaded = json.loads((runs_dir / "2026-08-23.jsonl").read_text().strip())
    assert loaded["error"] == "model 'qwen2.5:14b' not found"


# --------------------------------------------------------------------------
# run_id: a rating necessarily arrives AFTER the run it judges, so it must be
# able to name that run. Without an id there is nothing to attach one to,
# which blocks the whole quality-signal and adaptive-routing chain.
# --------------------------------------------------------------------------

def test_run_id_is_required_not_defaulted():
    """A defaulted id invites records that silently share the empty string,
    which would silently merge distinct runs downstream."""
    import dataclasses

    field = {f.name: f for f in dataclasses.fields(EvidenceRecord)}["run_id"]
    assert field.default is dataclasses.MISSING
    assert field.default_factory is dataclasses.MISSING


def test_run_id_is_first_in_the_serialised_record(tmp_path):
    import dataclasses

    assert list(dataclasses.asdict(make_record()))[0] == "run_id"


def test_run_id_survives_the_jsonl_round_trip(tmp_path):
    runs_dir = tmp_path / "runs"
    record = make_record()

    append_evidence(record, runs_dir=runs_dir)

    loaded = json.loads((runs_dir / "2026-08-23.jsonl").read_text().strip())
    assert loaded["run_id"] == record.run_id


def test_two_runs_of_the_same_skill_get_distinct_ids(tmp_path):
    from unittest.mock import MagicMock, patch

    from sylvae.backends.base import BackendResult
    from sylvae.runner import BACKENDS, run_skill

    skill_dir = tmp_path / "skills" / "s"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: s\ndescription: d\n---\nbody")

    backend = MagicMock()
    backend.run.return_value = BackendResult(
        output="o", model="m", duration_ms=1, status="ok"
    )

    with patch.dict(BACKENDS, {"fake": MagicMock(return_value=backend)}):
        first = run_skill(skill_dir, "fake", "in", runs_dir=tmp_path / "runs")
        second = run_skill(skill_dir, "fake", "in", runs_dir=tmp_path / "runs")

    assert first.run_id != second.run_id
    assert len(first.run_id) == 32  # uuid4 hex, no dashes


def test_readers_tolerate_historical_records_without_a_run_id(tmp_path):
    """The committed docs/phase1-runs.jsonl and the live log both predate
    run_id. Those records are NOT backfilled -- rewriting an append-only
    ledger to add synthetic ids is exactly the after-the-fact mutation this
    project exists to make impossible. They simply cannot be rated."""
    from sylvae.review import load_all_runs

    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    legacy = {
        "skill": "disk-report", "backend": "ollama", "model": "m",
        "input_summary": "x", "output": "o", "duration_ms": 1,
        "status": "ok", "timestamp": "2026-08-24T10:00:00Z", "error": None,
    }
    (runs_dir / "2026-08-24.jsonl").write_text(json.dumps(legacy) + "\n")

    records = load_all_runs(runs_dir)

    assert len(records) == 1
    assert records[0].get("run_id") is None

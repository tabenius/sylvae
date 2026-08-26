"""Per-(skill, backend) aggregation over runs and ratings.

The rules encoded here are guards against statistics that look reasonable
and mislead. The whole point of phase 2 is replacing an anecdote with a
measurement, so a subtly wrong measurement would be a WORSE outcome than
the anecdote it replaced -- it would carry more authority.
"""

from __future__ import annotations

from sylvae.ratings import Rating
from sylvae.stats import aggregate


def _run(run_id="r1", skill="disk-report", backend="ollama", status="ok", duration_ms=1000):
    return {
        "run_id": run_id, "skill": skill, "backend": backend, "model": "m",
        "input_summary": "x", "output": "o", "duration_ms": duration_ms,
        "status": status, "timestamp": "2026-08-26T10:00:00Z", "error": None,
    }


def _rating(run_id, score, rater="human", timestamp="2026-08-26T10:00:00Z"):
    return Rating(rating_id="x" * 32, run_id=run_id, score=score,
                  rater=rater, rationale=None, timestamp=timestamp)


def test_groups_by_skill_and_backend():
    runs = [
        _run("a", skill="disk-report", backend="ollama"),
        _run("b", skill="disk-report", backend="opencode"),
        _run("c", skill="summarize-diff", backend="ollama"),
    ]

    stats = aggregate(runs, [])

    assert set(stats) == {
        ("disk-report", "ollama"), ("disk-report", "opencode"), ("summarize-diff", "ollama"),
    }


def test_never_pools_across_skills():
    """There is no meaningful global "is Ollama good" number. Good for
    disk-report (did it flag the right filesystem?) means something
    different from good for summarize-diff (did it avoid inventing
    changes?). A pooled figure would answer no actual question."""
    runs = [
        _run("a", skill="disk-report", backend="ollama"),
        _run("b", skill="summarize-diff", backend="ollama"),
    ]

    stats = aggregate(runs, [])

    assert ("disk-report", "ollama") in stats
    assert ("summarize-diff", "ollama") in stats
    assert all(isinstance(k, tuple) and len(k) == 2 for k in stats)


def test_ok_rate_counts_only_successful_runs():
    runs = [
        _run("a", status="ok"), _run("b", status="ok"),
        _run("c", status="failed"), _run("d", status="unavailable"),
    ]

    s = aggregate(runs, [])[("disk-report", "ollama")]

    assert s.runs == 4
    assert s.ok == 2
    assert s.ok_rate == 0.5


def test_duration_uses_median_not_mean():
    """Ollama latency here is wildly variable -- the same skill on the same
    model measured at both 27s and 76s. A mean over a handful of runs is
    dominated by whichever happened to be slow."""
    runs = [
        _run("a", duration_ms=1000), _run("b", duration_ms=1000),
        _run("c", duration_ms=1000), _run("d", duration_ms=100000),
    ]

    s = aggregate(runs, [])[("disk-report", "ollama")]

    assert s.median_duration_ms == 1000  # mean would be 25750


def test_one_score_per_run_before_aggregating_across_runs():
    """A heavily-discussed run must not outweigh a quiet one. Resolve to one
    score per run first, then aggregate across runs -- not the other way
    round."""
    runs = [_run("a"), _run("b")]
    ratings = [
        _rating("a", 1), _rating("a", 1, rater="j1"), _rating("a", 1, rater="j2"),
        _rating("b", 5),
    ]

    s = aggregate(runs, ratings)[("disk-report", "ollama")]

    # run a -> 1, run b -> 5, mean over RUNS = 3.0
    # (mean over the four rating records would be 2.0)
    assert s.mean_score == 3.0
    assert s.rated_runs == 2


def test_latest_rating_per_rater_supersedes():
    runs = [_run("a")]
    ratings = [
        _rating("a", 1, timestamp="2026-08-26T10:00:00Z"),
        _rating("a", 5, timestamp="2026-08-26T12:00:00Z"),
    ]

    s = aggregate(runs, ratings)[("disk-report", "ollama")]

    assert s.mean_score == 5.0


def test_human_and_judge_counts_reported_separately():
    """Their reliability differs. A caller deciding whether to trust an
    aggregate needs to know if it rests on one human or forty machines."""
    runs = [_run("a"), _run("b"), _run("c")]
    ratings = [
        _rating("a", 4, rater="human"),
        _rating("b", 4, rater="claude-sonnet-5"),
        _rating("c", 4, rater="claude-sonnet-5"),
    ]

    s = aggregate(runs, ratings)[("disk-report", "ollama")]

    assert s.human_rated_runs == 1
    assert s.judge_rated_runs == 2
    assert s.rated_runs == 3


def test_runs_without_run_id_count_toward_volume_but_cannot_be_rated():
    """The 20 legacy records predate run_id. They are real runs and belong
    in the volume figures; they simply carry no judgment."""
    legacy = _run()
    del legacy["run_id"]
    runs = [legacy, _run("a")]
    ratings = [_rating("a", 5)]

    s = aggregate(runs, ratings)[("disk-report", "ollama")]

    assert s.runs == 2
    assert s.rated_runs == 1
    assert s.mean_score == 5.0


def test_unrated_group_reports_no_score_rather_than_zero():
    """Zero would read as 'terrible'. Absent judgment is not bad judgment."""
    s = aggregate([_run("a")], [])[("disk-report", "ollama")]

    assert s.rated_runs == 0
    assert s.mean_score is None


def test_ratings_for_unknown_runs_are_ignored():
    s = aggregate([_run("a")], [_rating("ghost", 5)])[("disk-report", "ollama")]

    assert s.rated_runs == 0


def test_empty_input_is_empty_not_an_error():
    assert aggregate([], []) == {}


# --------------------------------------------------------------------------
# Availability is not capability.
#
# Found by reading the real table rather than by reasoning: summarize-diff
# on ollama showed 0% ok, which looked like a quality catastrophe. Both runs
# were actually 'unavailable' -- qwen2.5:14b had never been pulled. A router
# reading a naive ok_rate would conclude the model is hopeless at the skill,
# when the model was never given the chance to try.
# --------------------------------------------------------------------------

def test_failed_and_unavailable_are_counted_separately():
    runs = [
        _run("a", status="ok"),
        _run("b", status="failed"),
        _run("c", status="unavailable"),
        _run("d", status="unavailable"),
    ]

    s = aggregate(runs, [])[("disk-report", "ollama")]

    assert s.ok == 1
    assert s.failed == 1
    assert s.unavailable == 2


def test_quality_rate_excludes_runs_that_never_happened():
    """Of the runs that actually executed, how many succeeded? This is the
    figure a router should read when judging capability."""
    runs = [
        _run("a", status="ok"),
        _run("b", status="failed"),
        _run("c", status="unavailable"),
        _run("d", status="unavailable"),
    ]

    s = aggregate(runs, [])[("disk-report", "ollama")]

    assert s.ok_rate == 0.25            # of all attempts
    assert s.quality_rate == 0.5        # of attempts that actually ran


def test_quality_rate_is_none_when_nothing_ever_ran():
    """Not 0.0 -- zero would read as 'always fails', which is a claim the
    evidence does not support. Nothing ran, so nothing is known."""
    runs = [_run("a", status="unavailable"), _run("b", status="unavailable")]

    s = aggregate(runs, [])[("disk-report", "ollama")]

    assert s.ok_rate == 0.0
    assert s.quality_rate is None

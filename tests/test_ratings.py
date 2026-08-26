"""Ratings: later opinions ABOUT runs, stored separately from the runs.

The architectural constraint here is the whole point. runs/*.jsonl is an
append-only ledger of what happened; a rating is a judgment formed
afterwards. Collapsing them would mean rewriting historical evidence to
reflect present opinion -- exactly the after-the-fact mutation this project
exists to prevent, and the same principle WeftMark is built on.
"""

from __future__ import annotations

import json

import pytest

from sylvae.ratings import (
    MAX_SCORE,
    MIN_SCORE,
    Rating,
    append_rating,
    current_scores_by_run,
    load_all_ratings,
)


def _rating(**over) -> Rating:
    base = dict(
        run_id="a" * 32, score=4, rater="human", rationale=None,
        timestamp="2026-08-26T10:00:00Z",
    )
    base.update(over)
    return Rating.create(**base) if "rating_id" not in base else Rating(**base)


def test_round_trips_through_jsonl(tmp_path):
    path = append_rating(_rating(), ratings_dir=tmp_path)

    assert path == tmp_path / "2026-08-26.jsonl"
    loaded = json.loads(path.read_text().strip())
    assert loaded["run_id"] == "a" * 32
    assert loaded["score"] == 4


def test_each_rating_gets_its_own_identity():
    assert _rating().rating_id != _rating().rating_id


def test_a_run_may_carry_several_ratings(tmp_path):
    """A human and a judge may both rate the same run, and two humans may
    disagree. Uniqueness on run_id is deliberately NOT enforced -- the
    disagreement is the interesting signal, not a conflict to resolve."""
    append_rating(_rating(rater="human", score=2), ratings_dir=tmp_path)
    append_rating(_rating(rater="claude-sonnet-5", score=5), ratings_dir=tmp_path)

    ratings = load_all_ratings(tmp_path)

    assert len(ratings) == 2
    assert {r.rater for r in ratings} == {"human", "claude-sonnet-5"}


def test_orphan_run_id_loads_without_raising(tmp_path):
    """A rating may outlive the run it names (log rotated, file deleted).
    That is a dangling reference, not corruption."""
    append_rating(_rating(run_id="f" * 32), ratings_dir=tmp_path)

    assert len(load_all_ratings(tmp_path)) == 1


def test_missing_directory_is_empty_not_an_error(tmp_path):
    assert load_all_ratings(tmp_path / "nope") == []


def test_blank_lines_are_skipped(tmp_path):
    (tmp_path / "r.jsonl").write_text(json.dumps({
        "rating_id": "x" * 32, "run_id": "a" * 32, "score": 3,
        "rater": "human", "rationale": None, "timestamp": "2026-08-26T10:00:00Z",
    }) + "\n\n")

    assert len(load_all_ratings(tmp_path)) == 1


@pytest.mark.parametrize("score", [0, -1, 6, 99])
def test_score_outside_the_scale_is_refused(score):
    with pytest.raises(ValueError):
        Rating.create(run_id="a" * 32, score=score, rater="human")


@pytest.mark.parametrize("score", [MIN_SCORE, 3, MAX_SCORE])
def test_scores_on_the_scale_are_accepted(score):
    assert Rating.create(run_id="a" * 32, score=score, rater="human").score == score


def test_empty_rater_is_refused():
    """Ratings from an unnamed source cannot be weighed later -- human and
    judge ratings carry different confidence and must stay separable."""
    with pytest.raises(ValueError):
        Rating.create(run_id="a" * 32, score=3, rater="")


# --------------------------------------------------------------------------
# Superseding. A changed opinion is a NEW rating with a later timestamp,
# never an edit. Resolving "what does this rater currently think" is the
# consumer's job, so it lives here rather than in the writer.
# --------------------------------------------------------------------------

def test_latest_rating_per_rater_supersedes_earlier_ones():
    ratings = [
        _rating(rater="human", score=2, timestamp="2026-08-26T10:00:00Z"),
        _rating(rater="human", score=5, timestamp="2026-08-26T12:00:00Z"),
    ]

    current = current_scores_by_run(ratings)

    assert current["a" * 32] == {"human": 5}


def test_distinct_raters_are_kept_apart_not_averaged():
    ratings = [
        _rating(rater="human", score=2),
        _rating(rater="claude-sonnet-5", score=5),
    ]

    current = current_scores_by_run(ratings)

    assert current["a" * 32] == {"human": 2, "claude-sonnet-5": 5}


def test_ratings_for_different_runs_do_not_mix():
    ratings = [_rating(run_id="a" * 32, score=1), _rating(run_id="b" * 32, score=5)]

    current = current_scores_by_run(ratings)

    assert current["a" * 32]["human"] == 1
    assert current["b" * 32]["human"] == 5

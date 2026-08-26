"""Ratings: later opinions about runs, stored beside them, never inside them.

The separation from ``sylvae.evidence`` is the load-bearing design decision,
not an organisational one. ``runs/*.jsonl`` is an append-only ledger of what
happened; a rating is a judgment formed afterwards, by a human or a judge
model. Writing ratings into the evidence records would mean rewriting
history to reflect present opinion -- precisely the after-the-fact mutation
this project exists to make impossible, and the same principle WeftMark is
built on.

If a future change makes it tempting to just add a `score` field to
EvidenceRecord, that temptation is the thing to refuse.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

# 1-5 rather than thumbs up/down. A binary signal cannot express the case
# that actually matters here: output that is usable but subtly wrong -- the
# mistral disk-report run that correctly read 92% and then declared nothing
# above 85% in the same breath. That is not a "bad" run or a "good" one, and
# routing needs to know the difference.
MIN_SCORE = 1
MAX_SCORE = 5

# Conventional rater name for a person. Judge models use their model id, so
# human and machine judgment stay separable when aggregated -- they carry
# different confidence and must never be silently pooled.
HUMAN_RATER = "human"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class Rating:
    rating_id: str  # this record's own identity
    run_id: str     # the EvidenceRecord being judged -- the join key
    score: int
    rater: str      # "human", or the judging model's id
    rationale: str | None  # optional for humans, expected from a judge
    timestamp: str  # ISO 8601, matching the evidence convention exactly

    @classmethod
    def create(
        cls,
        run_id: str,
        score: int,
        rater: str,
        rationale: str | None = None,
        timestamp: str | None = None,
    ) -> "Rating":
        """Build a validated rating, generating id and timestamp."""
        if not isinstance(score, int) or isinstance(score, bool) or not (
            MIN_SCORE <= score <= MAX_SCORE
        ):
            raise ValueError(
                f"score must be an integer in {MIN_SCORE}..{MAX_SCORE}, got {score!r}"
            )
        if not rater or not rater.strip():
            raise ValueError(
                "rater must be named: human and judge ratings carry different "
                "confidence and have to stay separable when aggregated"
            )
        if not run_id:
            raise ValueError("run_id is required: a rating must name the run it judges")
        return cls(
            rating_id=uuid.uuid4().hex,
            run_id=run_id,
            score=score,
            rater=rater.strip(),
            rationale=rationale,
            timestamp=timestamp or _now(),
        )


def append_rating(rating: Rating, ratings_dir: str | Path = "ratings") -> Path:
    """Append one rating to its date-partitioned file. Never edits, never
    deletes -- a changed opinion is a NEW rating with a later timestamp."""
    dir_path = Path(ratings_dir)
    dir_path.mkdir(parents=True, exist_ok=True)
    out_file = dir_path / f"{rating.timestamp[:10]}.jsonl"
    with out_file.open("a") as f:
        f.write(json.dumps(asdict(rating)) + "\n")
    return out_file


def load_all_ratings(ratings_dir: str | Path = "ratings") -> list[Rating]:
    """Read every ratings/*.jsonl file.

    Tolerates ratings whose run_id no longer resolves: a rating can outlive
    the run it names (log rotated, file deleted). That is a dangling
    reference, not corruption, and dropping it would silently discard real
    judgment.
    """
    dir_path = Path(ratings_dir)
    if not dir_path.is_dir():
        return []

    ratings: list[Rating] = []
    for jsonl_file in sorted(dir_path.glob("*.jsonl")):
        for line in jsonl_file.read_text().splitlines():
            line = line.strip()
            if line:
                ratings.append(Rating(**json.loads(line)))
    return ratings


def current_scores_by_run(ratings: list[Rating]) -> dict[str, dict[str, int]]:
    """Resolve to the current score per rater, per run.

    Since ratings are append-only, a rater who changes their mind leaves
    several records. The latest timestamp wins for that rater. Raters are
    kept apart rather than averaged here: collapsing a human's 2 and a
    judge's 5 into 3.5 would hide precisely the disagreement worth seeing.
    Any weighting across raters belongs to the caller.
    """
    latest: dict[str, dict[str, Rating]] = {}
    for rating in ratings:
        by_rater = latest.setdefault(rating.run_id, {})
        seen = by_rater.get(rating.rater)
        if seen is None or rating.timestamp > seen.timestamp:
            by_rater[rating.rater] = rating
    return {
        run_id: {rater: r.score for rater, r in by_rater.items()}
        for run_id, by_rater in latest.items()
    }

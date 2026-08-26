"""Per-(skill, backend) aggregation over the evidence log and the ratings.

This is the layer that turns accumulated evidence into something a routing
decision can read. It is deliberately separate from the router because it
has a second consumer -- the review UI shows a human these same numbers --
and duplicating the aggregation is how the displayed figures and the
acted-on figures silently drift apart.

Pure functions over already-loaded lists: no filesystem access, so it is
trivially testable and both consumers share one computation.

Every rule below is a guard against statistics that look reasonable and
mislead. The point of phase 2 is replacing an anecdote with a measurement;
a subtly wrong measurement is a worse outcome than the anecdote, because it
carries more authority.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import Iterable

from sylvae.ratings import HUMAN_RATER, Rating, current_scores_by_run


@dataclass(frozen=True)
class GroupStats:
    skill: str
    backend: str
    runs: int
    ok: int
    failed: int
    unavailable: int
    # Share of ALL attempts that succeeded.
    ok_rate: float
    # Share of attempts that actually RAN and succeeded -- the figure that
    # speaks to capability. Availability and capability are different axes,
    # and conflating them makes a backend that was never reachable look
    # incapable. None when nothing ever ran: zero would assert "always
    # fails", which the evidence does not support.
    quality_rate: float | None
    median_duration_ms: float | None
    rated_runs: int
    human_rated_runs: int
    judge_rated_runs: int
    # None, never 0.0, when nothing is rated: zero would read as "terrible",
    # and absent judgment is not bad judgment.
    mean_score: float | None


def aggregate(
    runs: Iterable[dict],
    ratings: Iterable[Rating],
) -> dict[tuple[str, str], GroupStats]:
    """Aggregate per (skill, backend).

    Never pooled across skills. There is no meaningful global "is Ollama
    good" number: good for disk-report (did it flag the right filesystem?)
    means something different from good for summarize-diff (did it avoid
    inventing changes?). A pooled figure would look authoritative and
    answer no actual question.
    """
    scores_by_run = current_scores_by_run(list(ratings))

    grouped: dict[tuple[str, str], list[dict]] = {}
    for record in runs:
        key = (record.get("skill", ""), record.get("backend", ""))
        grouped.setdefault(key, []).append(record)

    out: dict[tuple[str, str], GroupStats] = {}
    for (skill, backend), records in grouped.items():
        durations = [
            r["duration_ms"] for r in records
            if isinstance(r.get("duration_ms"), (int, float))
        ]
        ok = sum(1 for r in records if r.get("status") == "ok")
        failed = sum(1 for r in records if r.get("status") == "failed")
        unavailable = sum(1 for r in records if r.get("status") == "unavailable")
        attempted = ok + failed

        # Resolve to ONE score per run before aggregating across runs. Doing
        # it the other way round would let a heavily-discussed run outweigh a
        # quiet one purely by rating count.
        per_run_scores: list[float] = []
        human_rated = 0
        judge_rated = 0
        for record in records:
            # Legacy records have no run_id and can never be rated. They are
            # still real runs and belong in the volume figures.
            run_id = record.get("run_id")
            if not run_id:
                continue
            by_rater = scores_by_run.get(run_id)
            if not by_rater:
                continue
            per_run_scores.append(statistics.fmean(by_rater.values()))
            if HUMAN_RATER in by_rater:
                human_rated += 1
            if any(rater != HUMAN_RATER for rater in by_rater):
                judge_rated += 1

        out[(skill, backend)] = GroupStats(
            skill=skill,
            backend=backend,
            runs=len(records),
            ok=ok,
            failed=failed,
            unavailable=unavailable,
            ok_rate=ok / len(records) if records else 0.0,
            quality_rate=(ok / attempted) if attempted else None,
            # Median, not mean. Ollama latency here is wildly variable -- the
            # same skill on the same model measured at both 27s and 76s -- and
            # a mean over a handful of runs is dominated by the slow one.
            median_duration_ms=statistics.median(durations) if durations else None,
            rated_runs=len(per_run_scores),
            human_rated_runs=human_rated,
            judge_rated_runs=judge_rated,
            mean_score=statistics.fmean(per_run_scores) if per_run_scores else None,
        )
    return out

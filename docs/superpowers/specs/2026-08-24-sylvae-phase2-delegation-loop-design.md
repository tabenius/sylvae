---
title: Sylvae — Phase 2 design: closing the delegation loop
status: planned
date: 2026-08-24
---

# Sylvae Phase 2 — Closing the delegation loop

## The problem this phase exists to solve

Sylvae's premise is that simple, well-specified work should run on cheap
local models and only hard work should reach a frontier model. Phase 1
built the machinery to *execute* that (four backends, a runner, evidence
records) and phase 1.5 added `--backend auto` to *decide* it.

But the decision is currently a hand-declaration. `skills/disk-report`
says `tier: cheap` because one human read one mistral output once and
judged it good enough. `skills/summarize-diff` says `tier: frontier`
because that same reading caught a hallucinated "changed function
signature" claim. Two data points, read by eye, written into frontmatter
as if settled.

That is an anecdote wearing the costume of a policy.

The original ask behind this whole project was help *pinpointing* what
weak local models can reliably handle. Pinpointing requires measurement.
Phase 2 replaces the declaration with evidence, while keeping the
declaration as the honest starting prior for skills that have no evidence
yet.

## The core model: declared tier as prior, evidence as posterior

The existing `tier:` field is not discarded — it is repositioned.

- **No evidence yet (cold start):** route by the declared tier. This is
  exactly today's behavior, and it is the right default: a skill author's
  judgment beats a coin flip.
- **Enough evidence accumulated:** route by what actually happened.
  A skill declared `frontier` that consistently scores well on Ollama
  gets promoted to cheap. A skill declared `cheap` that starts failing
  gets demoted.
- **Always:** the decision is explainable. Any routing choice can state
  which rule fired and on what data.

This framing means no work is wasted and no existing behavior silently
changes for skills that lack data.

## What has to exist for that to be possible

Four things are missing today, in dependency order.

### 1. Runs have no stable identity

`EvidenceRecord` has no id. A quality judgment necessarily arrives
*after* the run it judges, so it must be able to name that run. Without
an id there is nothing to attach a rating to.

A `run_id` is also the natural join key for future WeftMark ingestion, so
this is not single-purpose work.

### 2. There is no way to generate comparable runs

To learn whether Ollama is good enough for a skill, the same input must
go through more than one backend. Today that is entirely manual — it is
literally what was done by hand to produce `docs/phase1-comparison.md`.

A `sylvae compare` command turns that manual exercise into a repeatable
one, and is the data generator everything downstream depends on.

### 3. Nothing measures output quality

`status: ok` only means the call completed. It says nothing about whether
the answer was any good. The mistral `summarize-diff` run that
hallucinated a function-signature change was recorded as `ok`.

Two honest sources of a quality signal, both needed for different reasons:

- **Human rating** — trustworthy, doesn't scale. The person who asked for
  the output is the ground truth on whether it was useful.
- **LLM judge** — scales, but is itself a model call with its own
  fallibility.

Both must write to a store *separate* from `runs/*.jsonl`. The evidence
log is an append-only ledger of what happened; ratings are later opinions
*about* those events. Mutating evidence records to add ratings would
destroy that distinction (and it is the same principle WeftMark is built
on — evidence is not editable after the fact).

### 4. Routing can't read any of it

`resolve_backend()` today looks only at `skill.tier`. It needs to consult
aggregated per-(skill, backend) statistics, with a minimum-sample gate so
three lucky runs don't flip a routing decision.

## Known tensions, stated rather than papered over

**The judge-cost paradox.** If the LLM judge is a cheap model, it may not
detect the subtle errors that are exactly what distinguishes cheap output
from frontier output. If the judge is a frontier model, judging every run
costs as much as just having run it on the frontier model in the first
place — defeating the point.

Mitigation: judge with a strong model, but only on a **sample** of runs,
not all of them. Sampling keeps cost bounded and sub-linear in run volume
while still accumulating signal. This is a real tradeoff, not a solved
problem; the sample rate should be configurable and its cost visible.

**Quality is task-relative and partly subjective.** "Good" for
`disk-report` (did it flag the right filesystem?) means something
different from "good" for `summarize-diff` (did it avoid inventing
changes?). Ratings must therefore be aggregated **per skill**, never
pooled across skills into a single "is Ollama good" number. There is no
such number.

**Input difficulty varies within a skill.** The same skill on a 3-line
diff and a 300-line diff are different problems. Tracking input
characteristics to control for this is real work and is deliberately
*not* in this phase — it is a known limitation of the resulting
statistics and should be documented as such rather than silently assumed
away.

**Small-N statistics.** A skill with three runs must not drive routing.
Every evidence-based rule needs an explicit minimum-sample gate, and
below that gate the declared tier stands.

**The frontier endpoint is not Anthropic.** *(Revised 2026-08-24, after
the first draft of this document got it wrong.)*

The original draft named the Anthropic backend as the frontier endpoint
and made verifying it a hard blocker. That was a planning error: Anthropic
API access is a separate paid product from a Claude subscription, and no
key is obtainable here. Blocking the critical path on it would have
blocked everything on something that cannot happen.

Worse, the assumption had already shipped as a live defect. `--backend
auto` routes `tier: frontier` — *and unset tier, the default for every
undeclared skill* — to Anthropic, so the default path of the headline
feature fails on auth. It went unnoticed because manual testing always
passed an explicit `--backend`, and the single `auto` test used
`disk-report`, which is `tier: cheap` and takes the one working branch.

What is actually available here, all verified working:

- **Ollama** locally (free, unlimited, currently only mistral pulled)
- **Codex** via `codex exec`, on existing ChatGPT-account auth
- **OpenCode** via `opencode run`, reaching the OpenCode Zen catalog —
  including six free models (`hy3-free`, `mimo-v2.5-free`,
  `muse-spark-1.2-contributor-free`, `nemotron-3-ultra-free`,
  `nemotron-3.5-lightning-free`, `x-preview-f-free`)

Free-tier reliability is genuinely variable: on the same trivial prompt,
`mimo-v2.5-free` answered in ~8s while `nemotron-3-ultra-free` returned
an upstream 502. That is not a nuisance to route around — it means
`ok_rate` carries real signal here rather than being a formality that
always reads 1.0, and it makes the `unavailable` vs `failed` distinction
load-bearing in a way it would not be against a single reliable paid API.

This reframing is better on the merits than what it replaced. The
interesting delegation question was never local-mistral versus a frontier
API. It is: given a local model, several free hosted models of uneven
reliability, and two full agent harnesses, which work goes where? That is
a closer fit to the original question about what weak models can handle,
and it is answerable with resources that actually exist.

The Anthropic backend stays in the codebase — mock-tested, unreachable in
practice, and immediately usable by anyone who does have a key. That is an
honest state, not a broken one.

## Three tiers, not two

Codex and OpenCode are currently excluded from `--backend auto` entirely,
because the cheap/frontier binary has no slot for them. They are neither:
they are full agent invocations with bootstrap overhead (measured: ~6s and
~11.5k tokens for a trivial Codex prompt; ~13s and ~26k tokens for
OpenCode). That is a third kind of resource — more capable than a raw
completion call, and correspondingly more expensive per invocation.

Phase 2 introduces `tier: agent` alongside `cheap` and `frontier`, so
skills that genuinely need tool use or multi-step work can declare it and
be routed accordingly.

## Deliberately out of scope for phase 2

- Input-difficulty modeling (named above as a known limitation).
- Cost accounting in currency — token/latency proxies only.
- Multi-turn or conversational skills; everything stays single-shot.
- Memory-unification and semantic-definitions threads (separate
  initiatives from the original three-thread brainstorm).
- Any change to the `SKILL.md` format beyond the `tier` vocabulary.

## Success criteria

Phase 2 is done when all of the following are demonstrably true:

1. A run can be named, rated, and the rating retrieved — without ever
   mutating the evidence log.
2. `sylvae compare` produces a paired multi-backend artifact from one
   command, replacing the manual process behind
   `docs/phase1-comparison.md`.
3. Aggregated stats exist per (skill, backend) and are inspectable by a
   human in the review UI.
4. `--backend auto` demonstrably changes its decision for at least one
   real skill based on accumulated evidence rather than frontmatter, and
   can explain why it did.
5. `--backend auto` works at all for a skill that is not `tier: cheap`
   — it does not today (see the revised tension above), which makes this
   the first thing to fix, not the last.
6. The whole thing still passes CI on a clean checkout.

# Sylvae

A portable skill runner: load a `SKILL.md`-format skill and run it against
Anthropic's API, a local Ollama model, Codex, or OpenCode (the latter two
via their own CLIs, run sandboxed/subprocessed) — with every run logged as
a durable evidence record.

Phase 1 goal, architecture, and rationale: see
`docs/superpowers/specs/2026-08-21-sylvae-phase1-skill-runner-design.md`.

## Setup

    python -m venv .venv
    . .venv/bin/activate
    pip install -e ".[dev]"

## Run

    sylvae run skills/summarize-diff --backend anthropic --input path/to/diff.txt

Override the backend's default model with `--model`. For Ollama, a bare
model name is auto-prefixed with litellm's `ollama/` convention if you
leave it off:

    sylvae run skills/summarize-diff --backend ollama --model mistral:latest --input path/to/diff.txt

Or let the skill decide: `--backend auto` reads the `tier` a skill declares
in its `SKILL.md` frontmatter (`tier: cheap` or `tier: frontier`) and routes
to Ollama or Anthropic accordingly. A skill with no declared tier defaults to
frontier — the safe choice, not the cheap one:

    sylvae run skills/disk-report --backend auto --input path/to/disk-usage.txt

The `shellout` (Codex) and `opencode` backends both require their own CLI
on `PATH` and their own auth already configured — both are real agent
invocations, not plain completion calls, so expect real latency (several
seconds minimum, agent bootstrap overhead) and real cost even for trivial
prompts. Neither participates in `--backend auto` routing for this reason —
they aren't a "cheap" tier the way Ollama is, just a different kind of
resource:

    sylvae run skills/disk-report --backend shellout --input path/to/disk-usage.txt
    sylvae run skills/disk-report --backend opencode --model opencode/big-pickle --input path/to/disk-usage.txt

`opencode`'s own model catalog (`opencode models`) is large — gpt-5.x,
kimi, glm, deepseek, big-pickle, and many more — all reachable through
`--model opencode/<name>`.

## Review

Browse the evidence log in a local, loopback-only web page — filter by
skill/backend/status, expand a run to see its input/output/error — and
trigger new runs straight from the page (pick a skill, backend, optional
model, paste input, submit):

    sylvae review

Opens at `http://127.0.0.1:8971/` by default. `--runs-dir`, `--skills-dir`,
`--host`, and `--port` override the defaults; `--host 0.0.0.0` allows LAN
access if you actually want that (the default is loopback-only on purpose).
Triggered runs use real backends — a run through `shellout`/`opencode` can
take a while and costs the same as running it from the CLI; there's no
"cheap preview" mode.

## Test

    pytest

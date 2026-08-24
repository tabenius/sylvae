# Sylvae

A portable skill runner: load a `SKILL.md`-format skill and run it against
Anthropic's API, a local Ollama model, or (stubbed for now) a CLI-only
harness — with every run logged as a durable evidence record.

Phase 1 goal, architecture, and rationale: see
`docs/superpowers/specs/2026-08-21-sylvae-phase1-skill-runner-design.md`.

## Setup

    python -m venv .venv
    . .venv/bin/activate
    pip install -e ".[dev]"

## Run

    sylvae run skills/summarize-diff --backend anthropic --input path/to/diff.txt

Override the backend's default model with `--model`. Use the full identifier
the backend expects — for Ollama that means litellm's `ollama/<name>` form:

    sylvae run skills/summarize-diff --backend ollama --model ollama/mistral:latest --input path/to/diff.txt

Or let the skill decide: `--backend auto` reads the `tier` a skill declares
in its `SKILL.md` frontmatter (`tier: cheap` or `tier: frontier`) and routes
to Ollama or Anthropic accordingly. A skill with no declared tier defaults to
frontier — the safe choice, not the cheap one:

    sylvae run skills/disk-report --backend auto --input path/to/disk-usage.txt

## Test

    pytest

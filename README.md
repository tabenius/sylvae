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

## Test

    pytest

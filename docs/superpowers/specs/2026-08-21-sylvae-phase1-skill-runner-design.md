---
title: Sylvae — Phase 1 design: a portable skill runner
status: approved-in-chat
date: 2026-08-21
---

# Sylvae — Phase 1 design

## What Sylvae is

Sylvae is an experiment in making agent skills/macros portable across agent
families — able to run under Claude Code, Codex, OpenCode, or a local
Ollama-hosted model (qwen, mistral, gemma), not just the harness they were
authored in.

The name and its narrative: real forests share resources and warning signals
between different tree *species* through underground mycorrhizal networks —
the "wood wide web." Sylvae aims to be that shared underground layer for
agent skills: different agent species draw on a common substrate of
portable, invocable knowledge without being homogenized into one vendor's
format.

This is one of three related threads the user identified (memories,
skills/macros, semantic definitions) for a broader HCI-for-agent-memory
initiative. Skills/macros was chosen to go first because the `SKILL.md`
format already has real cross-vendor momentum (adopted beyond Anthropic
within months of its release), and because it's the most direct lever on
the practical goal: delegating simple, well-specified tasks to cheaper local
models instead of spending frontier-model tokens on them.

Sylvae is a **standalone experiment**, sibling to `WeftMark` under
`/data/src/experiments/`, with its own git repository. It is explicitly not
built inside WeftMark's runtime — WeftMark's evidence/review discipline is
appropriate once patterns have proven out, not while they're still being
discovered. Evidence records Sylvae produces are shaped to be
WeftMark-compatible (see below) so they can be ingested later without a
redesign, but Sylvae does not depend on WeftMark and WeftMark does not
depend on Sylvae.

## Goal for phase 1

Prove the full loop end-to-end, cheaply:

> A portable skill definition → dispatched to a chosen backend (including a
> local Ollama model) → executes → produces a durable, comparable record of
> what happened.

The deliverable for phase 1 is **not** a polished tool. It is a working CLI
plus a short comparison report: 2-3 real, low-stakes skills run through all
three backends, compared on output quality, latency, and rough cost.

## Architecture

Four small, independently testable components:

1. **Skill loader** (`sylvae/loader.py` or equivalent) — parses a
   `SKILL.md`-format directory (YAML frontmatter with `name`/`description`,
   a Markdown instruction body, optional `scripts/` and `references/`
   subdirectories) into a normalized in-memory `Skill` object. Reuses the
   format already in active use in this environment; Sylvae does not invent
   a new skill format.

2. **Backend adapters** (`sylvae/backends/`) — a thin common interface,
   `run(prompt: str, skill: Skill, **kwargs) -> BackendResult`, with three
   phase-1 implementations:
   - `anthropic` — direct Claude API call.
   - `ollama` — local model via an OpenAI-compatible endpoint, using
     LiteLLM as the multi-backend abstraction layer (mature, already
     supports Ollama and a complexity-tiered router we may adopt in a later
     phase).
   - `shellout` — invokes a CLI-only harness (Codex, OpenCode) as a
     subprocess when no direct API is available.

   Each adapter is small, has no knowledge of the other two, and is unit
   tested against a fake/mock transport plus one real smoke-test call.

3. **Runner CLI** (`sylvae run <skill-path> --backend <name> --input ...`)
   — loads the skill via the loader, builds a prompt from the skill body
   plus the caller's input, calls the selected backend adapter, and prints
   the result. Backend selection is a required manual flag in phase 1; no
   automatic routing/classification yet (that's phase 2, and it needs real
   run data to tune against — this phase produces that data).

4. **Evidence record** — every run appends one JSON record to a local
   `runs/YYYY-MM-DD.jsonl` log:
   ```json
   {
     "skill": "summarize-diff",
     "backend": "ollama",
     "model": "qwen2.5:14b",
     "input_summary": "...",
     "output": "...",
     "duration_ms": 4210,
     "status": "ok",
     "timestamp": "2026-08-21T13:04:00Z"
   }
   ```
   Field names deliberately echo WeftMark's evidence vocabulary
   (`status: ok|failed|unavailable`, not just pass/fail) so a future
   ingestion path doesn't require renaming data, without Sylvae taking a
   runtime dependency on WeftMark.

## Data flow (example)

1. Human or agent runs `sylvae run skills/summarize-diff --backend ollama --input diff.txt`.
2. Loader reads `skills/summarize-diff/SKILL.md`.
3. Runner builds the prompt (skill body + `diff.txt` contents).
4. `ollama` adapter sends it to a local model via LiteLLM's OpenAI-compatible
   client, pointed at `localhost:11434`.
5. Adapter returns output + timing; runner prints it and writes the evidence
   record.

## Error handling

A backend that is down or misconfigured (e.g., no Ollama server running) is
reported as `status: unavailable`, not `status: failed` — WeftMark's own
distinction, reused because it's the right one: a job that never ran is not
a job that ran and produced a wrong answer. Sylvae fails closed: it never
silently substitutes a different backend than the one requested.

## Testing / success criteria for phase 1

- Unit tests for the loader against a handful of real `SKILL.md` fixtures
  already present in this environment.
- Unit tests for each backend adapter against a mocked transport.
- One integration smoke test per backend, run manually (not in CI, since it
  needs live credentials/a running Ollama instance).
- The actual experimental output: 2-3 skills run through all three
  backends, with a short written comparison (quality/latency/cost) — this
  is the artifact that decides whether phase 2 (routing) is worth building.

## Explicitly out of scope for phase 1

- Automatic backend/model routing or complexity classification.
- Any GUI or browsing surface.
- The semantic-definitions (shared vocabulary/ontology) thread.
- The memory-unification thread.
- Wiring evidence records into WeftMark itself.

## Open questions for the implementation plan

- Language/runtime: Python (matches WeftMark's stack, and LiteLLM is
  Python-native) vs. something else — leaning Python unless there's a
  reason otherwise.
- Which 2-3 skills to use as the first test set — should be real, already
  slightly annoying manual tasks in this environment, not synthetic demos.
- Whether `shellout` (Codex/OpenCode adapter) ships in phase 1 or is
  stubbed until the Anthropic/Ollama path is proven — it's the highest-risk
  adapter (no stable API, output parsing is harness-specific) and could be
  deferred without weakening the phase-1 proof.

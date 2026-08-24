# Sylvae

A portable skill runner: load a `SKILL.md`-format skill and run it against
a local Ollama model, Claude Code, Codex, OpenCode, or the Anthropic API —
with every run logged as a durable evidence record.

Four of the five backends need no API key of their own: they reuse CLI
tools you're already logged into. Sylvae spans four agent families without
any single vendor's credentials being required for it to work.

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

### The `claudecode` backend

Runs the local `claude` CLI headlessly, authenticating with your existing
Claude subscription rather than an `ANTHROPIC_API_KEY` — useful when you
have the former and not the latter:

    sylvae run skills/disk-report --backend claudecode --input path/to/disk-usage.txt

It invokes `claude -p --output-format json --setting-sources "" --strict-mcp-config`.
Those last two flags are there for cost, not tidiness. Measured on the
same trivial prompt:

| invocation | tokens | cost |
| --- | --- | --- |
| default | 28,424 | $0.171 |
| with both flags | 3,146 | $0.027 |

The default loads every installed plugin, skill, and agent before
answering — bootstrap Sylvae has no use for, since a skill run is plain
text in, text out. Dropping the setting sources sheds all of it; auth
lives outside settings and survives. (`--bare` sheds more but also drops
auth; replacing the system prompt with `--system-prompt` made it *worse*,
back up to 16,574 tokens.)

**One caveat worth knowing before routing to it.** Codex and OpenCode
draw on separate accounts. This one shares your interactive Claude
budget — every run spends the same five-hour allowance you use to work.
Hitting that limit is reported as `unavailable`, not `failed`: the run
never happened, it didn't happen badly.

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

## Use from an agent (MCP)

Sylvae can expose itself as an MCP server, so an agent can delegate work to
a cheaper model mid-task instead of doing it inline:

    pip install -e ".[mcp]"
    claude mcp add sylvae -- /path/to/.venv/bin/sylvae mcp \
        --skills-dir /path/to/skills --runs-dir /path/to/runs

Two tools: `sylvae_list_skills` and `sylvae_run_skill`. Runs still land in
the evidence log exactly as CLI runs do.

**Two guards, on by default.** Runs default to the cheap local backend — an
agent calling Sylvae and landing on something as expensive as itself has
achieved nothing while still looking like it worked. And the `claudecode`
backend is *refused* over MCP: it spawns an agent harness that can call
Sylvae again, and it spends the same interactive quota the caller is
already using. `--allow-recursive-backends` lifts that, but it's a flag
*you* set when starting the server — deliberately not something a calling
model can grant itself.

`--backend auto` is refused here too, since tier routing could select a
recursion-risk backend and reopen the hole.

**On transport integrity, and what actually guards it.** The MCP SDK owns
this, at the file-descriptor level: while serving, it dups the real
descriptors aside and points fd 0 at the null device and fd 1 at stderr,
restoring both on exit. A tool doing `print()`, `sys.stdout.write()`, or
even raw `os.write(1, ...)` cannot corrupt the wire, and a subprocess
cannot swallow protocol bytes from stdin. That's verified empirically in
`tests/test_mcp_transport_integrity.py` rather than taken on faith.

Sylvae adds nothing there — nothing at Python level could improve on it.
What Sylvae does add is a consequence of that design: since fd 1 is
redirected to stderr, every stray byte lands on stderr, and MCP clients
routinely capture stderr to a log file. LiteLLM logs completion payloads
at INFO — for Sylvae that's the skill's *input and output*, arbitrary
caller-supplied text. So dependency loggers default to `warning`.
`--dependency-log-level debug` lifts that for troubleshooting and will
write caller content to disk; the flag's help says so.

## Test

    pytest
